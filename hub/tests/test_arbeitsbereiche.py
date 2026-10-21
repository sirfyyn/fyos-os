"""Arbeitsbereiche eines Agenten: das Feld im Eingang, die Meldung des Runners und die Auswahl im Chatfenster (ohne Netz)."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import _agenteneingang as eingang
from mcp_hub.plugins import _arbeitsbereiche as bereiche
from mcp_hub.plugins.agent import AgentPlugin

JETZT_MS = 1_792_270_000_000
RUNNER_TOKEN = "r" * 32
MAX_TOKEN = "m" * 32


class FakeRedis:
    def __init__(self) -> None:
        self.daten: dict[str, str] = {}
        self.ausfall = False

    def set(self, schluessel, wert):
        if self.ausfall:
            raise OSError("Redis weg")
        self.daten[schluessel] = wert

    def get(self, schluessel):
        if self.ausfall:
            raise OSError("Redis weg")
        return self.daten.get(schluessel)


@pytest.fixture()
def r():
    return FakeRedis()


@pytest.fixture()
def client(r):
    plugin = AgentPlugin({"agent": "helfer"}, redis=r)
    return TestClient(Starlette(routes=plugin.routen()))


def test_eingang_traegt_den_namen_nur_bei_max():
    e = eingang.eintrag({"quelle": "max", "text": "Hallo", "arbeitsbereich": "projekt"}, JETZT_MS)
    assert e["arbeitsbereich"] == "projekt" and e["klasse"] == "max"
    # eine Hintergrundquelle wählt nichts: das Feld fällt weg, der Auftrag geht trotzdem durch
    a = eingang.eintrag({"quelle": "alarm", "text": "Platte", "arbeitsbereich": "projekt"}, JETZT_MS)
    assert "arbeitsbereich" not in a
    # ohne Feld kein Eintrag (Rückfall: standard)
    assert "arbeitsbereich" not in eingang.eintrag({"quelle": "max", "text": "Hallo"}, JETZT_MS)


@pytest.mark.parametrize("name", ["/etc", "../x", "Gross", "mit leer", "a" * 41, "x;y"])
def test_eingang_lehnt_pfade_und_fremde_namen_ab(name):
    with pytest.raises(ValueError, match="arbeitsbereich"):
        eingang.eintrag({"quelle": "max", "text": "Hallo", "arbeitsbereich": name}, JETZT_MS)


def test_liste_ohne_meldung_ist_nur_standard(client):
    antwort = client.get("/hub/agent/arbeitsbereiche")
    assert antwort.status_code == 200
    assert antwort.json() == {"ok": True, "bereiche": [{"name": "standard", "titel": "Standard"}]}


def test_runner_meldet_chatfenster_liest_standard_zuerst(client):
    ok = client.post("/hub/agent/arbeitsbereiche", json={"agent": "helfer", "bereiche": [
        {"name": "fyos", "titel": "FYOS Repo"}, {"name": "standard", "titel": "Standard"}]})
    assert ok.status_code == 200
    liste = client.get("/hub/agent/arbeitsbereiche?agent=helfer").json()["bereiche"]
    assert [b["name"] for b in liste] == ["standard", "fyos"]
    # ohne Angabe gilt der Agent des Plugins
    assert [b["name"] for b in client.get("/hub/agent/arbeitsbereiche").json()["bereiche"]] == ["standard", "fyos"]


@pytest.mark.parametrize("rumpf", [
    {"bereiche": []},
    {"bereiche": [{"name": "fyos", "titel": "ohne standard"}]},
    {"bereiche": [{"name": "/etc", "titel": "Pfad"}, {"name": "standard"}]},
    {"bereiche": [{"name": "standard"}, {"name": "standard"}]},
    {"bereiche": "kein Array"},
    {"agent": "BÖSE", "bereiche": [{"name": "standard"}]},
    ["kein", "Objekt"],
])
def test_meldung_prueft_streng(client, r, rumpf):
    assert client.post("/hub/agent/arbeitsbereiche", json=rumpf).status_code == 400
    assert r.daten == {}


def test_redis_weg_ist_ehrlich_503(client, r):
    r.ausfall = True
    assert client.get("/hub/agent/arbeitsbereiche").status_code == 503
    assert client.post("/hub/agent/arbeitsbereiche", json={"bereiche": [{"name": "standard"}]}).status_code == 503


def test_mit_tokens_meldet_nur_der_runner_und_liest_nur_max(r):
    plugin = AgentPlugin({"agent": "helfer", "tokens": f"runner={RUNNER_TOKEN},max={MAX_TOKEN}"}, redis=r)
    c = TestClient(Starlette(routes=plugin.routen()))
    rumpf = {"bereiche": [{"name": "standard"}, {"name": "fyos"}]}
    runner, leser = {"x-agent-token": RUNNER_TOKEN}, {"x-agent-token": MAX_TOKEN}
    assert c.post("/hub/agent/arbeitsbereiche", json=rumpf).status_code == 401
    assert c.post("/hub/agent/arbeitsbereiche", json=rumpf, headers=leser).status_code == 401
    assert c.post("/hub/agent/arbeitsbereiche", json=rumpf, headers=runner).status_code == 200
    assert c.get("/hub/agent/arbeitsbereiche").status_code == 401
    assert c.get("/hub/agent/arbeitsbereiche", headers=runner).status_code == 401
    assert [b["name"] for b in c.get("/hub/agent/arbeitsbereiche", headers=leser).json()["bereiche"]] == [
        "standard", "fyos"]


def test_titel_wird_gekuerzt_und_gesaeubert():
    liste = bereiche.pruefen([{"name": "standard", "titel": "S\x00tan" + "d" * 100}])
    assert len(liste[0]["titel"]) <= bereiche.TITEL_MAX and "\x00" not in liste[0]["titel"]
