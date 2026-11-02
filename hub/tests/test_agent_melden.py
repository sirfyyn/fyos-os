"""agent — Annahme der Agenten-Ereignisse des Runners (POST /hub/agent/melden), ohne Netz.

Geprüft: strenge Form (Vertrag aus _agentenstrom), nichts Fremdes im Strom, Grenzen, Fehlerwege,
und dass die Route kein Werkzeug ist. Die Kürzungsregel selbst prüft test_agentenstrom.py.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import agent
from mcp_hub import server as hub_server
from mcp_hub.plugins import _agentenstrom as strom

JETZT_MS = 1_792_270_000_000
JSON = {"content-type": "application/json"}


class Pipe:
    def __init__(self, r: "FakeRedis"):
        self.r, self.befehle = r, []

    def xadd(self, name, felder, maxlen=None, approximate=True):
        self.befehle.append((name, dict(felder), maxlen, approximate))

    def execute(self):
        if self.r.ausfall:
            raise OSError("Redis weg")
        for name, felder, maxlen, approximate in self.befehle:
            self.r.n += 1
            self.r.stroeme.setdefault(name, []).append((f"{JETZT_MS + self.r.n}-0", felder))
            self.r.maxlen = (maxlen, approximate)
        return [True] * len(self.befehle)


class FakeRedis:
    def __init__(self, ausfall=False):
        self.stroeme: dict[str, list[tuple[str, dict]]] = {}
        self.n = 0
        self.ausfall = ausfall
        self.maxlen = None

    def pipeline(self, transaction=True):
        return Pipe(self)


def ereignis(typ, q, **felder):
    return {"typ": typ, "agent": "agent", "sitzung": "lauf-1", "q": q, **felder}


TEXT = ereignis("part.updated", 1, pt="text", id="m1:0", delta="Ich schaue kurz.")
TOOL_LAEUFT = ereignis("part.updated", 2, pt="tool", id="call_1", wz="lage", st="running")
TOOL_FERTIG = ereignis(
    "part.updated", 3, pt="tool", id="call_1", wz="lage", st="completed", ergebnis="ok"
)


def anfrage(*ereignisse):
    return {"ereignisse": list(ereignisse)}


def test_route_nimmt_an_und_schreibt_in_den_strom(client, redis):
    r = client.post("/hub/agent/melden", json=anfrage(TEXT, TOOL_LAEUFT, TOOL_FERTIG))
    assert r.status_code == 200 and r.json() == {"ok": True, "angenommen": 3}
    eintraege = [felder for _, felder in redis.stroeme[strom.STROM]]
    assert [e["q"] for e in eintraege] == ["1", "2", "3"]
    assert eintraege[0]["pt"] == "text" and eintraege[0]["delta"] == "Ich schaue kurz."
    assert eintraege[2]["st"] == "completed" and eintraege[2]["ergebnis"] == "ok"
    assert all(
        e["v"] == strom.VERTRAG and e["a"] == "agent" and e["s"] == "lauf-1" for e in eintraege
    )
    assert redis.maxlen == (strom.MAXLEN, True)  # der Strom wächst nicht unbegrenzt


def test_route_stempelt_die_empfangszeit(client, redis, monkeypatch):
    monkeypatch.setattr(agent, "_jetzt_ms", lambda: JETZT_MS)
    client.post("/hub/agent/melden", json=anfrage(TEXT))
    ((_, felder),) = redis.stroeme[strom.STROM]
    assert felder["t"] == str(JETZT_MS)


def test_route_nimmt_ruhe_an(client, redis):
    ruhe = ereignis("ruhe", 4, an="1", pausiert="1", stufe="tief", quelle="schalter", von="app")
    r = client.post("/hub/agent/melden", json=anfrage(TEXT, ruhe))
    assert r.status_code == 200 and r.json() == {"ok": True, "angenommen": 2}
    eintraege = [felder for _, felder in redis.stroeme[strom.STROM]]
    assert eintraege[1]["typ"] == "ruhe" and eintraege[1]["stufe"] == "tief" and eintraege[1]["von"] == "app"


def test_route_lehnt_falsche_ruhe_ab_und_schreibt_nichts(client, redis):
    falsch = ereignis("ruhe", 2, an="vielleicht", pausiert="0")
    r = client.post("/hub/agent/melden", json=anfrage(TEXT, falsch))
    assert r.status_code == 400 and r.json()["kind"] == "bad_request"
    assert "Ereignis 1" in r.json()["error"]  # der Stapel wird als Ganzes abgelehnt, der Fehler nennt das Stück
    assert redis.stroeme == {}


def test_route_fehlerwege(client, redis):
    assert client.post("/hub/agent/melden", content=b"{kaputt", headers=JSON).status_code == 400
    r = client.post("/hub/agent/melden", json=anfrage(ereignis("unbekannt.typ", 1)))
    assert r.status_code == 400 and r.json()["ok"] is False and r.json()["kind"] == "bad_request"
    assert "Ereignis 0" in r.json()["error"]  # der Fehler nennt das schuldige Stück
    assert client.post("/hub/agent/melden", json={"ereignisse": []}).status_code == 400
    viele = anfrage(*[ereignis("session.idle", i + 1) for i in range(strom.EREIGNISSE_MAX + 1)])
    assert client.post("/hub/agent/melden", json=viele).status_code == 400
    gross = client.post("/hub/agent/melden", content=b" " * (strom.BODY_MAX_BYTES + 1), headers=JSON)
    assert gross.status_code == 413 and gross.json()["kind"] == "zu_gross"
    assert client.get("/hub/agent/melden").status_code == 405
    assert redis.stroeme == {}  # nichts davon hat geschrieben


def test_route_redis_weg_ist_ehrlich_503(client, redis):
    redis.ausfall = True
    r = client.post("/hub/agent/melden", json=anfrage(TEXT))
    assert r.status_code == 503 and r.json()["kind"] == "redis"


def test_geheimnis_in_werkzeug_argumenten_kommt_nicht_in_den_strom(client, redis):
    frech = ereignis(
        "part.updated",
        1,
        pt="tool",
        id="call_9",
        wz="cluster",
        args={"token": "hunter2", "ns": "fyos"},
    )
    assert client.post("/hub/agent/melden", json=anfrage(frech)).status_code == 200
    ((_, felder),) = redis.stroeme[strom.STROM]
    assert "hunter2" not in felder["args"] and "…" in felder["args"] and "fyos" in felder["args"]


def test_build_app_haengt_die_route_ein(tmp_path, monkeypatch):
    pfad = tmp_path / "hub.yaml"
    pfad.write_text(
        "host: 127.0.0.1\nport: 8080\npath: /mcp\nplugins:\n"
        "  - {name: agent, module: mcp_hub.plugins.agent, class: AgentPlugin, enabled: true,"
        " config: {}, secrets: []}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hub_server, "_REGISTRY", None)
    monkeypatch.setattr(hub_server, "_CONFIG", None)
    app = hub_server.build_app(str(pfad))
    wege = {getattr(r, "path", None) for r in app.routes}
    assert {"/hub/agent/melden", "/hub/agent/eingang", "/hub/agent/alarm"} <= wege
    # Kein Werkzeug: die Meldung steht in keiner Werkzeugliste, die ein Modell sieht
    assert not any(t.startswith("agent.") for t in hub_server._REGISTRY.tools)


# ── Fixtures ────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def redis():
    r = FakeRedis()
    yield r


@pytest.fixture()
def client(redis):
    with TestClient(Starlette(routes=agent.AgentPlugin({}, redis=redis).routen())) as c:
        yield c
