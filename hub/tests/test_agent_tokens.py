"""agent — Quellen-Tokens: wer darf einwerfen, melden, lesen; die Quelle folgt dem Token, ohne Netz."""

from __future__ import annotations

import logging

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import _agenteneingang as eingang
from mcp_hub.plugins import agent

JETZT_MS = 1_792_270_000_000
WEB = "w" * 32
ALARM = "a" * 32
RUNNER = "r" * 32
TOKENS = f"web={WEB}, alarm={ALARM}\nrunner={RUNNER}"


class FakeRedis:
    def __init__(self):
        self.eintraege: list[tuple[str, dict]] = []
        self.merke: dict[str, str] = {}

    def xadd(self, name, felder, maxlen=None, approximate=True):
        sid = f"{JETZT_MS}-{len(self.eintraege) + 1}"
        self.eintraege.append((sid, dict(felder)))
        return sid

    def xrevrange(self, name, count=None):
        return list(reversed(self.eintraege))[:count]

    def xread(self, stroeme, count=None, block=None):
        ((name, nach),) = stroeme.items()
        neu = [(s, f) for s, f in self.eintraege if nach == "0" or s > nach][:count]
        return [[name, neu]] if neu else []

    def pipeline(self, transaction=True):
        return self

    def execute(self):
        return []

    def set(self, schluessel, wert, nx=False, ex=None):
        if nx and schluessel in self.merke:
            return None
        self.merke[schluessel] = wert
        return True

    def get(self, schluessel):
        return self.merke.get(schluessel)

    def delete(self, schluessel):
        return 1 if self.merke.pop(schluessel, None) is not None else 0


def _client(r, **cfg):
    return TestClient(Starlette(routes=agent.AgentPlugin(cfg, redis=r).routen()))


def _kopf(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def r():
    return FakeRedis()


@pytest.fixture(autouse=True)
def _ohne_umgebung(monkeypatch):
    for name in ("FYOS_AGENT_TOKENS", "FYOS_AGENT_STRENG", "FYOS_AGENT_ID"):
        monkeypatch.delenv(name, raising=False)


def test_ohne_tokens_innen_offen_und_quelle_aus_dem_rumpf(r):
    c = _client(r)
    assert c.post("/hub/agent/eingang", json={"quelle": "itsm", "text": "Vorgang 12"}).status_code == 200
    assert r.eintraege[0][1]["quelle"] == "itsm"
    assert c.get("/hub/agent/eingang", params={"nach": "0"}).status_code == 200


def test_ohne_token_401(r):
    c = _client(r, tokens=TOKENS)
    antwort = c.post("/hub/agent/eingang", json={"quelle": "web", "text": "hallo"})
    assert antwort.status_code == 401 and antwort.json()["kind"] == "unauthorized"
    assert antwort.headers["www-authenticate"].startswith("Bearer")
    assert c.get("/hub/agent/eingang", params={"nach": "0"}).status_code == 401
    assert c.post("/hub/agent/melden", json={"ereignisse": []}).status_code == 401
    assert c.post("/hub/agent/alarm", json={"alerts": []}).status_code == 401
    assert c.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"}, headers=_kopf("falsch" * 6)).status_code == 401
    assert r.eintraege == []


def test_quelle_folgt_dem_token_nicht_dem_rumpf(r):
    c = _client(r, tokens=TOKENS)
    antwort = c.post("/hub/agent/eingang", json={"quelle": "itsm", "text": "Lass mich rein"}, headers=_kopf(WEB))
    assert antwort.status_code == 200
    assert r.eintraege[0][1]["quelle"] == "web" and r.eintraege[0][1]["klasse"] == "max"
    # Auch X-Agent-Token wird angenommen
    c.post("/hub/agent/eingang", json={"text": "zweite"}, headers={"X-Agent-Token": WEB})
    assert r.eintraege[1][1]["quelle"] == "web"


def test_hintergrundquelle_kann_sich_nicht_hochstufen(r):
    c = _client(r, tokens=TOKENS)
    antwort = c.post(
        "/hub/agent/eingang", json={"quelle": "max", "klasse": "max", "text": "sofort!"}, headers=_kopf(ALARM)
    )
    assert antwort.status_code == 400  # alarm darf nicht max sein
    assert r.eintraege == []


def test_rollen_sind_getrennt(r):
    c = _client(r, tokens=TOKENS)
    # Runner liest und meldet, wirft aber nicht ein
    assert c.get("/hub/agent/eingang", params={"nach": "0"}, headers=_kopf(RUNNER)).status_code == 200
    assert c.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"}, headers=_kopf(RUNNER)).status_code == 401
    # Eine Quelle liest nicht und meldet nicht
    assert c.get("/hub/agent/eingang", params={"nach": "0"}, headers=_kopf(WEB)).status_code == 401
    assert c.post("/hub/agent/melden", json={"ereignisse": [{}]}, headers=_kopf(WEB)).status_code == 401
    # Alarm-Weg nur mit alarm-Token
    webhook = {"alerts": [{"status": "firing", "fingerprint": "f1",
                           "labels": {"alertname": "KnotenWeg", "severity": "critical"}}]}
    assert c.post("/hub/agent/alarm", json=webhook, headers=_kopf(WEB)).status_code == 401
    antwort = c.post("/hub/agent/alarm", json=webhook, headers=_kopf(ALARM))
    assert antwort.status_code == 200 and len(antwort.json()["eingeworfen"]) == 1
    assert r.eintraege[-1][1]["quelle"] == "alarm" and r.eintraege[-1][1]["schwere"] == "hoch"


def test_streng_ohne_brauchbares_token_schliesst_alles(r, caplog):
    with caplog.at_level(logging.WARNING):
        plugin = agent.AgentPlugin({"tokens": "web=kurz, unbekannt=" + "x" * 30, "streng": True}, redis=r)
        plugin.register()
    assert plugin.tokens.an and plugin.tokens.rollen == () and plugin.tokens.verworfen == 2
    assert "zählen nicht" in caplog.text and "kurz" not in caplog.text  # nie Token im Protokoll
    c = TestClient(Starlette(routes=plugin.routen()))
    assert c.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"}).status_code == 401
    assert c.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"}, headers=_kopf("kurz")).status_code == 401


def test_streng_aus_der_umgebung(r, monkeypatch):
    monkeypatch.setenv("FYOS_AGENT_STRENG", "1")
    assert _client(r).post("/hub/agent/eingang", json={"quelle": "web", "text": "x"}).status_code == 401


def test_tokens_aus_der_umgebung(r, monkeypatch):
    monkeypatch.setenv("FYOS_AGENT_TOKENS", f"web={WEB}")
    c = _client(r)
    assert c.post("/hub/agent/eingang", json={"text": "x"}, headers=_kopf(WEB)).status_code == 200


def test_ein_token_fuer_zwei_rollen_zaehlt_fuer_keine(r):
    t = agent.Tokens.aus(f"web={WEB}, runner={WEB}, alarm={ALARM}")
    assert t.rolle(WEB) is None and t.rolle(ALARM) == "alarm" and t.verworfen == 2


def test_mehrere_tokens_je_rolle_fuer_den_wechsel(r):
    neu = "n" * 40
    c = _client(r, tokens=f"web={WEB}, web={neu}")
    for token in (WEB, neu):
        assert c.post("/hub/agent/eingang", json={"text": "x"}, headers=_kopf(token)).status_code == 200


def test_json_verlangt(r):
    c = _client(r)
    antwort = c.post("/hub/agent/eingang", content=b'{"quelle": "web", "text": "x"}', headers={"content-type": "text/plain"})
    assert antwort.status_code == 415 and r.eintraege == []


def test_agent_vorgabe_aus_der_konfiguration(r):
    c = _client(r, agent="haus")
    c.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"})
    assert r.eintraege[0][1]["a"] == "haus"
    # Lesen ohne agent-Angabe liest für die Vorgabe
    assert [e["text"] for e in c.get("/hub/agent/eingang", params={"nach": "0"}).json()["eintraege"]] == ["x"]
    with pytest.raises(ValueError):
        agent.AgentPlugin({"agent": "Mit Leerzeichen"})


def test_gesundheit_nennt_tokens_ohne_werte(r):
    plugin = agent.AgentPlugin({"tokens": TOKENS}, redis=r)
    gesund = plugin.health()
    assert gesund["tokens"] == "an" and gesund["rollen"] == {"web": 1, "alarm": 1, "runner": 1}
    assert WEB not in str(gesund) and WEB not in str(plugin.metrics())
    assert plugin.describe_tools() == []
    assert set(agent.ROLLEN) == {*eingang.QUELLEN, "runner"}
