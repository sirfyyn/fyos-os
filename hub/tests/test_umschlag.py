"""Umschlag: Familien, Weckregeln, Sitzungsschlüssel (rein, ohne Netz)."""

from __future__ import annotations

import pytest

from mcp_hub import umschlag as u


def test_itsm_kommentar_hat_vorgang_akteur_und_zeit():
    e = u.normalisieren(u.STROM_ITSM, "1760000000000-0",
                        {"ticket_id": "INC-12", "event": "comment", "actor": "Berta", "ts": "2026-10-11T10:00:00Z"})
    assert e["thema"] == "itsm.kommentar"
    assert e["verweis"] == "INC-12"
    assert e["von"] == "berta"
    assert e["quelle"] == "itsm"
    assert e["zeit"].startswith("2026-10-11T10:00:00")
    assert e["id"] == "fyos:itsm:events|1760000000000-0"


@pytest.mark.parametrize("detail,schwere", [
    ("severity=critical", "kritisch"), ("severity=high", "hoch"), ("severity=low", "info"), ("title=x", "normal"),
])
def test_itsm_neu_schwere(detail, schwere):
    e = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "created", "detail": detail})
    assert e["thema"] == "itsm.neu"
    assert e["schwere"] == schwere


def test_itsm_aktualisiert_unterscheidet_zustaendigkeit_und_status():
    z = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "updated", "detail": "assignee; status"})
    s = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "updated", "detail": "status"})
    a = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "updated", "detail": "titel"})
    assert (z["thema"], s["thema"], a["thema"]) == ("itsm.zugewiesen", "itsm.status", "itsm.aktualisiert")


def test_itsm_ohne_ticket_ist_nichts():
    assert u.normalisieren(u.STROM_ITSM, "1-0", {"event": "comment"}) is None
    assert u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1"}) is None


def test_schleifen_totmann_ist_hoch():
    e = u.normalisieren(u.STROM_SCHLEIFEN, "1-0", {"art": "totmann", "schleife": "arbeit", "stunden": 7, "ts": 1760000000})
    assert e["thema"] == "schleifen.totmann"
    assert e["schwere"] == "hoch"
    assert e["daten"] == {"schleife": "arbeit", "stunden": 7}
    anstoss = u.normalisieren(u.STROM_ERKUNDEN, "1-0", {"art": "anstoss"})
    assert anstoss["thema"] == "erkunden.anstoss"
    assert anstoss["schwere"] == "info"


def test_bus_data_json_und_schwere_aus_thema():
    e = u.normalisieren("fyos:events:node.critical", "1760000000123-0",
                        {"source": "monitor", "data": '{"node": "knoten-1", "name": "knoten-1", "ts": 1760000000}'})
    assert e["thema"] == "node.critical"
    assert e["schwere"] == "kritisch"
    assert e["verweis"] == "knoten-1"
    assert e["quelle"] == "monitor"
    assert e["zeit_unix"] == 1760000000.0


def test_bus_ohne_zeit_nimmt_die_zeit_der_eintrags_id():
    e = u.normalisieren("fyos:events:ci.lauf", "1760000000500-3", {"data": '{"ergebnis": "fehler", "lauf": 12}'})
    assert e["zeit_unix"] == 1760000000.5
    assert e["daten"] == {"ergebnis": "fehler", "lauf": 12}


def test_thema_payload_familie():
    e = u.normalisieren("fyos:events:services", "1-0", {
        "topic": "services.service_down", "source": "probe", "payload": '{"service": "hub", "severity": "error"}', "ts": "2026-10-11T08:00:00+00:00"})
    assert e["thema"] == "services.service_down"
    assert e["schwere"] == "hoch"
    assert e["verweis"] == "hub"


def test_flach():
    e = u.normalisieren("fyos:events:freigabe.neu", "1-0", {"ticket": "INC-5", "titel": "Frage", "assignee": "Carla"})
    assert e["thema"] == "freigabe.neu"
    assert e["verweis"] == "INC-5"
    assert e["von"] == "carla"


def test_normalisieren_wirft_nie():
    assert u.normalisieren("x", "1-0", {}) is None
    assert u.normalisieren("x", "1-0", None) is None
    assert u.normalisieren("fyos:events:a", "kaputt", {"data": "kein json"}) is not None  # leere Daten, aber lesbar


def test_zeit_formate():
    assert u._zeit(1760000000000) == 1760000000.0
    assert u._zeit("2026-10-11T10:00:00") == u._zeit("2026-10-11T10:00:00Z")
    assert u._zeit("morgen") is None
    assert u._zeit("") is None


def test_passt_muster():
    assert u.passt("itsm.kommentar", ["itsm.*"])
    assert u.passt("ci.lauf", ["*"])
    assert u.passt("ci.lauf", ["ci.lauf"])
    assert not u.passt("ci.lauf", ["itsm.*", "flux.alert"])
    assert not u.passt("itsmx.neu", ["itsm.*"])


def test_weckt_diese_erste_passende_regel_und_kein_echo():
    regeln = [
        {"name": "vorgang", "thema": ["itsm.kommentar", "itsm.neu"], "nicht_von": ["wache"]},
        {"name": "alles", "thema": ["ci.*"]},
        {"name": "nur_person", "thema": ["x.*"], "von": ["carla"]},
    ]
    e = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "comment", "actor": "Wache"})
    assert u.weckt_diese(e, regeln) is None  # eigene Spur
    e = u.normalisieren(u.STROM_ITSM, "1-0", {"ticket_id": "INC-1", "event": "comment", "actor": "Carla"})
    assert u.weckt_diese(e, regeln)["name"] == "vorgang"
    ci = u.normalisieren("fyos:events:ci.lauf", "1-0", {"data": "{}"})
    assert u.weckt_diese(ci, regeln)["name"] == "alles"
    nur = u.normalisieren("fyos:events:x.y", "1-0", {"data": '{"actor": "bert"}'})
    assert u.weckt_diese(nur, regeln) is None
    nur = u.normalisieren("fyos:events:x.y", "1-0", {"data": '{"actor": "carla"}'})
    assert u.weckt_diese(nur, regeln)["name"] == "nur_person"
    assert u.weckt_diese(ci, []) is None


def test_schwerer():
    assert u.schwerer("info", "hoch") == "hoch"
    assert u.schwerer("kritisch", "normal") == "kritisch"


def test_sitzungsschluessel_und_umkehrung(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT", raising=False)
    assert u.sitzungsschluessel("inc-1234", "wache") == "agent:wache:vorgang:INC-1234"
    assert u.vorgang_aus_schluessel("agent:wache:vorgang:INC-1234") == ("wache", "INC-1234")
    assert u.vorgang_aus_schluessel("agent:wache:main") is None
    assert u.vorgang_aus_schluessel("agent:wache:vorgang:nix") is None
    assert u.vorgang_aus_schluessel("agent::vorgang:INC-1") is None


def test_agent_kennung_argument_umgebung_vorgabe(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT", raising=False)
    assert u.agent_kennung() == "main"
    monkeypatch.setenv("FYOS_AGENT", "wache")
    assert u.agent_kennung() == "wache"
    assert u.agent_kennung("andere") == "andere"
    assert u.sitzungsschluessel("INC-7") == "agent:wache:vorgang:INC-7"


def test_ereignisarten_sind_punktnamen():
    assert "itsm.kommentar" in u.EREIGNISARTEN
    assert all("." in t and u.EREIGNISARTEN[t] for t in u.EREIGNISARTEN)
