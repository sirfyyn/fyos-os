"""agent — den Ausgang mitlesen (GET /hub/agent/strom): Long-Poll, SSE, Filter, Tokens; ohne Netz."""

from __future__ import annotations

import json

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import _agentenstrom as strom
from mcp_hub.plugins import agent

from .test_agent_tokens import FakeRedis

MAX = "m" * 32
WEB = "w" * 32
RUNNER = "r" * 32
ALARM = "a" * 32
TOKENS = f"max={MAX},web={WEB},runner={RUNNER},alarm={ALARM}"


def _client(r, **cfg):
    return TestClient(Starlette(routes=agent.AgentPlugin({"agent": "helfer", **cfg}, redis=r).routen()))


def _kopf(token, **mehr):
    return {"Authorization": f"Bearer {token}", **mehr}


def _melden(r, *texte, agent_id="helfer", sitzung="s-1"):
    for i, text in enumerate(texte, start=1):
        strom.senden(r, {"typ": "part.updated", "agent": agent_id, "sitzung": sitzung, "q": i, "pt": "text",
                         "id": f"m{i}:0", "delta": text}, 1_792_270_000_000)


@pytest.fixture
def r():
    return FakeRedis()


def test_lesen_filtert_agent_und_sitzung_und_rueckt_vor(r):
    _melden(r, "hallo", "welt")
    _melden(r, "fremd", agent_id="codex")
    _melden(r, "andere", sitzung="s-2")
    alles = strom.lesen(r, "0", 0, 50, "helfer")
    assert [e["delta"] for e in alles["eintraege"]] == ["hallo", "welt", "andere"]
    assert alles["letzte"] == r.eintraege[-1][0]
    assert alles["eintraege"][0]["sid"] == r.eintraege[0][0] and alles["eintraege"][0]["id"] == "m1:0"
    nur = strom.lesen(r, "0", 0, 50, "helfer", "s-2")
    assert [e["delta"] for e in nur["eintraege"]] == ["andere"]
    spitze = strom.lesen(r, "$", 0, 50, "helfer")
    assert spitze["eintraege"] == [] and spitze["letzte"] == r.eintraege[-1][0]
    with pytest.raises(ValueError):
        strom.lese_id("1; DROP")


def test_long_poll_ohne_tokens_offen(r):
    _melden(r, "eins")
    c = _client(r)
    antwort = c.get("/hub/agent/strom", params={"nach": "0"}).json()
    assert antwort["ok"] and antwort["eintraege"][0]["delta"] == "eins" and antwort["eintraege"][0]["typ"] == "part.updated"
    assert c.get("/hub/agent/strom", params={"nach": "x"}).status_code == 400
    assert c.get("/hub/agent/strom", params={"agent": "Böse"}).status_code == 400
    assert c.get("/hub/agent/strom", params={"sitzung": "a b"}).status_code == 400


@pytest.mark.parametrize("token,status", [(MAX, 200), (WEB, 200), (RUNNER, 401), (ALARM, 401), ("x" * 32, 401), ("", 401)])
def test_nur_max_und_web_lesen_mit(r, token, status):
    c = _client(r, tokens=TOKENS)
    assert c.get("/hub/agent/strom", params={"nach": "0"}, headers=_kopf(token)).status_code == status


def test_max_token_wirft_als_max_ein(r):
    c = _client(r, tokens=TOKENS)
    antwort = c.post("/hub/agent/eingang", json={"quelle": "web", "text": "Bau mir X"}, headers=_kopf(MAX))
    assert antwort.status_code == 200
    assert r.eintraege[-1][1]["quelle"] == "max"


def test_sse_liefert_ereignisse_mit_id_und_setzt_fort(r):
    _melden(r, "a", "b", "c")
    c = _client(r, tokens=TOKENS, sse_dauer_s=0)  # eine Runde, dann endet die Verbindung
    zweite = r.eintraege[1][0]
    with c.stream("GET", "/hub/agent/strom", headers=_kopf(MAX, Accept="text/event-stream", **{"Last-Event-ID": zweite})) as antwort:
        assert antwort.status_code == 200
        assert antwort.headers["content-type"].startswith("text/event-stream")
        puffer = ""
        for stueck in antwort.iter_text():
            puffer += stueck
        bloecke = [b for b in puffer.split("\n\n") if b]
    assert bloecke[0] == "retry: 3000"
    ereignisse = [b for b in bloecke if "event: ereignis" in b]
    assert len(ereignisse) == 1  # nur nach der zweiten: „c“
    zeilen = dict(z.split(": ", 1) for z in ereignisse[0].splitlines())
    daten = json.loads(zeilen["data"])
    assert zeilen["id"] == r.eintraege[2][0] == daten["sid"] and daten["delta"] == "c" and daten["id"] == "m3:0"


def test_sse_ohne_token_401(r):
    c = _client(r, tokens=TOKENS)
    assert c.get("/hub/agent/strom", headers={"Accept": "text/event-stream"}).status_code == 401
