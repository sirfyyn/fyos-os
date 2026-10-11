"""Umschlag gegen die Formen der Hub-Erzeuger: Zeiten als Text, Verweis- und Kurzfelder, Sammelströme."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from mcp_hub import umschlag as u

T = 1791000000  # Sekunden; die Stream-Id trägt dieselbe Zeit in Millisekunden
EID = f"{T * 1000}-0"
SPAETER = T + 100
FELDER = {"id", "strom", "thema", "zeit", "zeit_unix", "schwere", "quelle", "verweis", "von", "daten"}


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def j(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False)


QUELLEN = {
    "bus.zustand": ("fyos:events:geraet.zustand", {"data": j(entity_id="sensor.flur", domaene="sensor", name="Flur",
                                                              **{"von": "off", "nach": "on"}), "source": "geraete"}),
    "bus.dokument": ("fyos:events:dms.document_added", {"data": j(id=77, titel="Rechnung", typ="Rechnung"),
                                                         "source": "ablage", "ts": str(float(SPAETER))}),
    "bus.lauf": ("fyos:events:werkstatt.lauf", {"data": j(id="skripte/x.py", trocken=False, rc=0, dauer_s=1.5, wer="wache"),
                                                 "source": "hub/werkstatt", "ts": str(SPAETER)}),
    "bus.aktion": ("fyos:events:ops.action", {"data": j(werkzeug="cluster.raeumen", ziel="knoten-1", grund="Platte",
                                                         ergebnis="ok", wer="berta"), "source": "hub/cluster", "ts": str(SPAETER)}),
    "bus.befehl": ("fyos:events:modell.aktion", {"data": j(befehl="profil", profil="p1", **{"von": "carla"}, grund="Messung",
                                                            aktion_id="a-1"), "source": "hub/modelle", "ts": str(SPAETER)}),
    "bus.entscheidung": ("fyos:events:decision.created", {"data": j(id="d-1", title="Soll ich?", type="ask", ts=iso(T)),
                                                           "source": "entscheidungen"}),
    "bus.stand": ("fyos:events:stand.geaendert", {"data": j(v=12, teile=["arbeit", "haus"]), "source": "hub"}),
    "thema.knoten": ("fyos:events:node.critical", {"ts": str(SPAETER), "source": "monitor", "topic": "node.critical",
                                                    "payload": j(node="knoten-1", severity="critical"), "id": "ab12cd34"}),
    "thema.entitaet": ("fyos:events:geraet.alarm", {"ts": str(SPAETER), "source": "geraete", "topic": "geraet.alarm",
                                                    "payload": j(entity_id="sensor.flur", title="Alarm"), "id": "11223344"}),
    "flach.freigabe": ("fyos:events:freigabe.angefragt", {"ticket": "CHG-9", "titel": "Frage", "assignee": "berta",
                                                           "waiting_for": "berta", "severity": "high", "beschreibung": "x",
                                                           "ts": iso(T)}),
    "tool.ok": ("bus.tool.cluster.lage.ok", {"plugin": "cluster", "method": "lage", "status": "ok", "latency_ms": "41",
                                              "args_sample": "{}"}),
    "tool.fail": ("bus.tool.mail.suchen.fail", {"plugin": "mail", "method": "suchen", "status": "fail", "latency_ms": "3001"}),
    "live": ("fyos:live", {"t": str(SPAETER * 1000), "p": "cluster", "m": "lage", "s": "fail", "k": "tool_failed", "d": "12",
                           "w": "web"}),
    "entwicklung": ("fyos:entwicklung:ereignisse", {"t": str(SPAETER * 1000), "a": "w", "q": "editor", "o": "projekt",
                                                     "n": "Bash", "d": "800"}),
    "dwell": ("fyos:pane:dwell", {"pane": "arbeit", "start": iso(T), "dauer_ms": "5000"}),
    "schleife": ("fyos:schleifen:ereignisse", {"art": "modus", "workflow": "ci_rot", "modus": "live", "wer": "carla", "ts": iso(T)}),
    "erkunden": ("fyos:erkunden:ereignisse", {"art": "durchgang", "bereich": "cluster", "anzahl": "3", "ok": "1", "ts": iso(T)}),
}


@pytest.mark.parametrize("name", sorted(QUELLEN))
def test_jede_erzeugerform_laesst_sich_normalisieren(name):
    strom, felder = QUELLEN[name]
    e = u.normalisieren(strom, EID, felder)
    assert e is not None, name
    assert set(e) == FELDER
    assert e["id"] == f"{strom}|{EID}" and e["strom"] == strom
    assert e["thema"] and " " not in e["thema"]
    assert e["schwere"] in u.SCHWEREN
    assert e["zeit_unix"] and e["zeit_unix"] > 1.7e9 and e["zeit"] == iso(e["zeit_unix"])
    assert e["verweis"] is None or isinstance(e["verweis"], str)
    assert e["von"] is None or e["von"] == e["von"].lower()
    assert all(isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200 for v in e["daten"].values())
    json.dumps(e)


def norm(name):
    strom, felder = QUELLEN[name]
    return u.normalisieren(strom, EID, felder)


def test_zeiten_als_text():
    assert u.zeit_unix("1791000100000") == SPAETER  # Millisekunden als Text
    assert u.zeit_unix(str(SPAETER)) == SPAETER
    assert u.zeit_unix(f"{SPAETER}.5") == SPAETER + 0.5
    assert u.zeit_unix("2026-10-03T12:00:00Z") is not None
    for kaputt in ("kein-datum", True, "99999999999999999", "", None, -5, 0, float("nan")):
        assert u.zeit_unix(kaputt) is None, kaputt
    assert norm("bus.dokument")["zeit_unix"] == SPAETER
    assert norm("bus.lauf")["zeit_unix"] == SPAETER
    assert norm("thema.knoten")["zeit_unix"] == SPAETER


def test_ohne_eigene_zeit_gilt_die_zeit_der_stream_id():
    e = norm("bus.stand")
    assert e["zeit_unix"] == T
    assert e["daten"]["v"] == 12 and "arbeit" in e["daten"]["teile"]


def test_verweis_aus_den_kurzfeldern_der_erzeuger():
    assert norm("bus.zustand")["verweis"] == "sensor.flur"
    assert norm("bus.dokument")["verweis"] == "77"
    assert norm("bus.lauf")["verweis"] == "skripte/x.py"
    assert norm("bus.aktion")["verweis"] == "knoten-1"
    assert norm("bus.befehl")["verweis"] == "a-1"
    assert norm("bus.entscheidung")["verweis"] == "d-1"
    assert norm("thema.entitaet")["verweis"] == "sensor.flur"


def test_titel_englisch_wird_zu_titel():
    assert norm("bus.entscheidung")["daten"]["titel"] == "Soll ich?"
    assert norm("thema.entitaet")["daten"]["title"] == "Alarm"


def test_zustandswechsel_hat_keinen_akteur():
    """`von` ist bei einem Wechsel von/nach der alte Zustand, sonst der Akteur."""
    e = norm("bus.zustand")
    assert e["von"] is None
    assert (e["daten"]["von"], e["daten"]["nach"], e["daten"]["entity_id"]) == ("off", "on", "sensor.flur")
    assert norm("bus.befehl")["von"] == "carla"
    assert norm("bus.aktion")["von"] == "berta"
    assert norm("bus.lauf")["von"] == "wache"


def test_sammelstroeme_des_hub():
    t = norm("tool.ok")
    assert (t["thema"], t["verweis"], t["schwere"], t["daten"]["latency_ms"]) == ("bus.tool.cluster.lage.ok", "cluster.lage", "info", "41")
    assert "args_sample" not in t["daten"]  # Stichproben der Argumente gehören nicht in den Umschlag
    assert norm("tool.fail")["schwere"] == "normal"
    lv = norm("live")
    assert (lv["thema"], lv["verweis"], lv["von"], lv["schwere"], lv["zeit_unix"]) == ("live", "cluster.lage", "web", "normal", SPAETER)
    assert lv["daten"]["art"] == "tool_failed"
    en = norm("entwicklung")
    assert (en["thema"], en["verweis"], en["daten"]["art"], en["daten"]["werkzeug"], en["zeit_unix"]) == (
        "entwicklung.ereignisse", "projekt", "werkzeug", "Bash", SPAETER)
    dw = norm("dwell")
    assert (dw["thema"], dw["verweis"], dw["zeit_unix"]) == ("pane.dwell", "arbeit", T)


def test_schleifen_tragen_workflow_modus_und_zaehler():
    s = norm("schleife")
    assert (s["thema"], s["von"], s["daten"]["workflow"], s["daten"]["modus"]) == ("schleifen.modus", "carla", "ci_rot", "live")
    e = norm("erkunden")
    assert (e["thema"], e["daten"]["bereich"], e["daten"]["anzahl"], e["daten"]["ok"]) == ("erkunden.durchgang", "cluster", "3", "1")


def test_freigabe_ohne_inhalte():
    f = norm("flach.freigabe")
    assert (f["thema"], f["verweis"], f["von"], f["schwere"], f["daten"]["waiting_for"]) == (
        "freigabe.angefragt", "CHG-9", "berta", "hoch", "berta")
    assert "beschreibung" not in f["daten"]


@pytest.mark.parametrize("felder", [
    {}, {"data": ""}, {"data": "[1, 2]"}, {"data": "null"}, {"data": json.dumps({"ts": "morgen", "von": None})},
    {"payload": "{kaputt", "topic": "x.y"}, {"ts": "heute", "t": "-5"}, {"ts": None}, {"x": None},
])
def test_krumme_eintraege_werfen_nie(felder):
    for strom in ("fyos:itsm:events", "fyos:schleifen:ereignisse", "fyos:events:x", "bus.tool.a.b.ok", "fyos:live"):
        e = u.normalisieren(strom, "nicht-numerisch", felder)
        assert e is None or (set(e) == FELDER and e["schwere"] in u.SCHWEREN)


def test_quelle_stumm_geht_durch_den_umschlag():
    assert {"quelle.stumm", "quelle.lebt"} <= set(u.EREIGNISARTEN)
    e = u.normalisieren("fyos:events:quelle.stumm", EID, {"data": j(ts=iso(T), schwere="hoch", verweis="wache:mail", name="wache:mail",
                                                                  art="wache", text="Fehler 400", seit=iso(T - 900)), "source": "waechter"})
    assert (e["thema"], e["schwere"], e["verweis"], e["quelle"]) == ("quelle.stumm", "hoch", "wache:mail", "waechter")
    assert e["daten"]["name"] == "wache:mail" and e["daten"]["art"] == "wache" and e["daten"]["text"] == "Fehler 400"
