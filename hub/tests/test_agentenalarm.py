"""agentenalarm — Alertmanager-Webhook → Agenten-Eingang (POST /hub/agent/alarm), ohne Netz."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import agent
from mcp_hub.plugins import _agentenalarm as alarm
from mcp_hub.plugins import _agenteneingang as eingang

JETZT_MS = 1_792_270_000_000
JSON = {"content-type": "application/json"}


class FakeRedis:
    """xadd für den Eingang, set/get/delete für die Merke (mit nx/ex wie redis-py)."""

    def __init__(self, ausfall_xadd: bool = False) -> None:
        self.eintraege: list[tuple[str, dict]] = []
        self.merke: dict[str, str] = {}
        self.ablauf: dict[str, int] = {}
        self.ausfall_xadd = ausfall_xadd

    def xadd(self, name, felder, maxlen=None, approximate=True):
        if self.ausfall_xadd:
            raise OSError("Redis weg")
        assert name == eingang.STROM
        sid = f"{JETZT_MS}-{len(self.eintraege) + 1}"
        self.eintraege.append((sid, dict(felder)))
        return sid

    def set(self, schluessel, wert, nx=False, ex=None):
        if nx and schluessel in self.merke:
            return None
        self.merke[schluessel] = wert
        self.ablauf[schluessel] = ex
        return True

    def get(self, schluessel):
        return self.merke.get(schluessel)

    def delete(self, schluessel):
        return 1 if self.merke.pop(schluessel, None) is not None else 0


def _alarm(name="KubePodCrashLooping", severity="critical", status="firing", fp="a1b2c3", **mehr):
    labels = {"alertname": name, "namespace": "fyos", "pod": "mcp-hub-7d9", "severity": severity}
    if severity is None:
        labels.pop("severity")
    return {
        "status": status,
        "labels": labels,
        "annotations": {
            "summary": "Pod startet immer wieder neu",
            "description": "mcp-hub-7d9 ist seit 15 min im CrashLoop.",
        },
        "fingerprint": fp,
        **mehr,
    }


def _webhook(*alarme, gruppe='{}:{alertname="X"}'):
    return {
        "version": "4",
        "status": "firing",
        "receiver": "agent-eingang",
        "groupKey": gruppe,
        "alerts": list(alarme),
    }


@pytest.fixture
def r():
    fake = FakeRedis()
    yield fake


@pytest.fixture
def client(r):
    return TestClient(Starlette(routes=agent.AgentPlugin({}, redis=r).routen()))


def test_ereignis_bildet_schwere_text_und_bezug_ab():
    e = alarm.ereignis(_alarm())
    assert e["quelle"] == "alarm" and e["schwere"] == "hoch" and e["von"] == "alertmanager"
    assert e["bezug"] == "am:a1b2c3"
    assert e["text"] == (
        "KubePodCrashLooping: Pod startet immer wieder neu\n"
        "mcp-hub-7d9 ist seit 15 min im CrashLoop.\n(namespace=fyos, pod=mcp-hub-7d9)"
    )
    assert alarm.ereignis(_alarm(severity="warning"))["schwere"] == "mittel"
    assert alarm.ereignis(_alarm(severity="info"))["schwere"] == "niedrig"
    assert alarm.ereignis(_alarm(severity=None))["schwere"] == "mittel"  # ohne Label: mittel
    behoben = alarm.ereignis(_alarm(status="resolved"))
    assert behoben["schwere"] == "niedrig" and behoben["text"].startswith(
        "Behoben: KubePodCrashLooping"
    )
    # Herzschläge des Stacks und severity none kommen nie in den Eingang
    assert alarm.ereignis(_alarm(name="Watchdog", severity="none")) is None
    assert alarm.ereignis(_alarm(name="InfoInhibitor", severity="info")) is None
    assert alarm.ereignis(_alarm(severity="none")) is None
    assert alarm.ereignis({"labels": {}}) is None and alarm.ereignis("kaputt") is None
    # Jedes Ereignis hält den Eingangsvertrag
    roh = {k: w for k, w in e.items() if not k.startswith("_")}
    assert eingang.eintrag(roh, JETZT_MS)["schwere"] == "hoch"


def test_wiederholung_wird_entprellt_und_steigende_schwere_kommt_durch(r):
    erst = alarm.aus_alertmanager(r, _webhook(_alarm(severity="warning")), JETZT_MS)
    assert len(erst["eingeworfen"]) == 1 and erst["uebersprungen"] == 0
    assert r.ablauf[alarm.MERK_PREFIX + "a1b2c3"] == alarm.MERK_S
    nochmal = alarm.aus_alertmanager(r, _webhook(_alarm(severity="warning")), JETZT_MS)
    assert nochmal == {"eingeworfen": [], "uebersprungen": 1}  # repeat_interval: kein zweites Mal
    schlimmer = alarm.aus_alertmanager(r, _webhook(_alarm(severity="critical")), JETZT_MS)
    assert len(schlimmer["eingeworfen"]) == 1
    assert [f["schwere"] for _, f in r.eintraege] == ["mittel", "hoch"]
    milder = alarm.aus_alertmanager(r, _webhook(_alarm(severity="warning")), JETZT_MS)
    assert milder["eingeworfen"] == []


def test_behoben_nur_fuer_eingeworfene(r):
    assert alarm.aus_alertmanager(r, _webhook(_alarm(status="resolved", fp="nie")), JETZT_MS) == {
        "eingeworfen": [],
        "uebersprungen": 1,
    }
    alarm.aus_alertmanager(r, _webhook(_alarm()), JETZT_MS)
    behoben = alarm.aus_alertmanager(r, _webhook(_alarm(status="resolved")), JETZT_MS)
    assert len(behoben["eingeworfen"]) == 1
    felder = r.eintraege[-1][1]
    assert felder["schwere"] == "niedrig" and felder["text"].startswith("Behoben:")
    assert felder["bezug"] == "am:a1b2c3" and felder["klasse"] == "hintergrund"
    assert alarm.MERK_PREFIX + "a1b2c3" not in r.merke
    # zweites „behoben“ (Alertmanager wiederholt) kommt nicht mehr durch
    assert (
        alarm.aus_alertmanager(r, _webhook(_alarm(status="resolved")), JETZT_MS)["eingeworfen"]
        == []
    )


def test_sturm_wird_ein_sammelereignis(r):
    viele = [
        _alarm(name=f"Alarm{i:02d}", fp=f"f{i}", severity="warning")
        for i in range(alarm.ALARME_MAX + 5)
    ]
    viele[3] = _alarm(name="Alarm03", fp="f3", severity="critical")
    ergebnis = alarm.aus_alertmanager(r, _webhook(*viele), JETZT_MS)
    assert len(ergebnis["eingeworfen"]) == 1 and len(r.eintraege) == 1
    felder = r.eintraege[0][1]
    assert felder["schwere"] == "hoch" and felder["text"].startswith(
        "25 Alarme auf einmal: Alarm00"
    )
    assert felder["bezug"].startswith("am:gruppe:")
    # dieselbe Gruppe noch einmal: entprellt
    assert alarm.aus_alertmanager(r, _webhook(*viele), JETZT_MS)["eingeworfen"] == []


def test_scheitert_das_einwerfen_bleibt_keine_merke(r):
    r.ausfall_xadd = True
    with pytest.raises(OSError):
        alarm.aus_alertmanager(r, _webhook(_alarm()), JETZT_MS)
    assert r.merke == {}  # der Wiederholversuch von Alertmanager kommt durch
    r.ausfall_xadd = False
    assert len(alarm.aus_alertmanager(r, _webhook(_alarm()), JETZT_MS)["eingeworfen"]) == 1


def test_route_nimmt_den_webhook_an(client, r):
    antwort = client.post(
        "/hub/agent/alarm", json=_webhook(_alarm(), _alarm(name="Watchdog", severity="none"))
    )
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["ok"] is True and daten["uebersprungen"] == 1
    assert daten["eingeworfen"] == [{"id": f"{JETZT_MS}-1", "bezug": "am:a1b2c3"}]
    # Eingeworfen wie jedes andere Eingangsereignis (Lesen prüft test_agenteneingang)
    felder = r.eintraege[0][1]
    assert felder["quelle"] == "alarm" and felder["schwere"] == "hoch" and felder["a"] == "agent"


def test_route_fehlerwege(client, r):
    assert client.post("/hub/agent/alarm", content=b"{kaputt", headers=JSON).status_code == 400
    assert client.post("/hub/agent/alarm", json={"alerts": "nein"}).status_code == 400
    r.ausfall_xadd = True
    assert client.post("/hub/agent/alarm", json=_webhook(_alarm())).status_code == 503
