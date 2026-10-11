"""Wecker: Quellen, Regeln, Flussschutz, Weckruf an die Brücke (alles mit Attrappen, ohne Netz)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mcp_hub import kv, umschlag as U
from mcp_hub.plugins import _wecker as W
from mcp_hub.plugins.openclaw import OpenClawPlugin


class Uhr:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Vorgaenge:
    """Vorgangs-Quelle: Liste offener Vorgänge und Verlauf je Vorgang (neueste zuerst)."""

    eingerichtet = True

    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self.history: dict[str, list[dict[str, Any]]] = {}

    def offen(self, grenze: int = 200) -> list[dict[str, Any]]:
        return list(self.tickets.values())

    def verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        return list(self.history.get(vid, []))


def ticket(vid: str, status: str = "new", zustaendig: str = "", stempel: str = "t0", **mehr: Any) -> dict[str, Any]:
    return {"id": vid, "status": status, "assignee": zustaendig, "updated_at": stempel, **mehr}


class Weckrufe:
    def __init__(self) -> None:
        self.aufrufe: list[dict[str, Any]] = []
        self.fehler: Exception | None = None

    def __call__(self, params: dict[str, Any]) -> dict[str, Any]:
        if self.fehler:
            raise self.fehler
        self.aufrufe.append(params)
        return {"geweckt": True}


def bauen(quellen, uhr, regeln=None, **kw):
    weck = Weckrufe()
    speicher = kv.SpeicherKv()
    w = W.Wecker(quellen=quellen, regeln=regeln or W.vorgaben_regeln(("wache",)), schicken=weck,
                 speicher=lambda: speicher, agent="wache", uhr=uhr, **kw)
    return w, weck, speicher


# ── Vorgänge ────────────────────────────────────────────────────────────────────────────────

def test_erste_runde_legt_nur_den_stand_fest():
    uhr, q = Uhr(), Vorgaenge()
    q.tickets = {"INC-1": ticket("INC-1")}
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    assert w.schlag() == {"gelesen": 0, "geweckt": 0, "wartend": 0}
    assert weck.aufrufe == []


def test_neuer_vorgang_weckt_seine_sitzung_ohne_inhalte():
    uhr, q = Uhr(), Vorgaenge()
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-7"] = ticket("INC-7", priority="high", title="GEHEIMER TITEL", created_by="Berta")
    assert w.schlag()["geweckt"] == 1
    (ruf,) = weck.aufrufe
    assert ruf["vorgang"] == "INC-7" and ruf["modus"] == "jetzt"
    assert "INC-7" in ruf["text"] and "hoch" in ruf["text"] and "berta" in ruf["text"]
    assert "GEHEIMER" not in ruf["text"]


def test_kommentar_weckt_nur_einmal_und_nur_fremde():
    uhr, q = Uhr(), Vorgaenge()
    q.tickets = {"INC-1": ticket("INC-1", status="in_progress")}
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-1"]["updated_at"] = "t1"
    q.history["INC-1"] = [{"ts": uhr.t - 5, "event": "comment", "actor": "Berta", "detail": "GEHEIM"}]
    assert w.schlag()["geweckt"] == 1
    assert "Kommentar von berta" in weck.aufrufe[0]["text"] and "GEHEIM" not in weck.aufrufe[0]["text"]
    assert weck.aufrufe[0]["vorgang"] == "INC-1"
    uhr.t += 20
    assert w.schlag()["geweckt"] == 0, "derselbe Kommentar weckt nicht noch einmal"
    # eigener Kommentar (Echo) und der Akteur des Spiegels wecken nie
    uhr.t += 20
    q.tickets["INC-1"]["updated_at"] = "t2"
    q.history["INC-1"] = [
        {"ts": uhr.t - 2, "event": "comment", "actor": "wache", "detail": "x"},
        {"ts": uhr.t - 1, "event": "comment", "actor": "openclaw", "detail": "y"},
    ] + q.history["INC-1"]
    assert w.schlag()["geweckt"] == 0
    assert len(weck.aufrufe) == 1
    assert w.zaehler["ignoriert"] == 2


def test_status_und_zustaendigkeit_wecken_nicht_aber_zuweisung_schon():
    uhr, q = Uhr(), Vorgaenge()
    q.tickets = {"INC-1": ticket("INC-1")}
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-1"].update(status="in_progress", updated_at="t1")
    w.schlag()
    assert weck.aufrufe == []  # itsm.status steht in keiner Vorgaberegel
    uhr.t += 20
    q.tickets["INC-1"].update(assignee="wache", updated_at="t2")
    w.schlag()
    assert len(weck.aufrufe) == 1 and "Zuständigkeit" in weck.aufrufe[0]["text"]


def test_stand_ueberlebt_einen_neustart():
    uhr, q = Uhr(), Vorgaenge()
    q.tickets = {"INC-1": ticket("INC-1")}
    speicher = kv.SpeicherKv()
    weck = Weckrufe()
    def neu():
        return W.Wecker(quellen=[W.VorgangsQuelle(lambda: q)], regeln=W.vorgaben_regeln(), schicken=weck,
                        speicher=lambda: speicher, uhr=uhr)
    neu().schlag()
    uhr.t += 20
    q.tickets["INC-2"] = ticket("INC-2")
    assert neu().schlag()["geweckt"] == 1, "ein neuer Wecker kennt den Stand und weckt für das Neue"


def test_nicht_eingerichtete_quelle_und_kranke_quelle_stoeren_nicht():
    uhr = Uhr()
    q = Vorgaenge()
    q.eingerichtet = False
    def kaputt():
        raise RuntimeError("weg")
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q), W.VorgangsQuelle(kaputt)], uhr)
    assert w.schlag()["geweckt"] == 0
    assert w.zaehler["quellfehler"] == 1 and "weg" in w.letzter_fehler


# ── Termine, Postfach, Dokumente, Ströme ───────────────────────────────────────────────────────

def termin(minuten: float, uhr: Uhr, **mehr: Any) -> dict[str, Any]:
    import datetime as dt

    start = dt.datetime.fromtimestamp(uhr.t + minuten * 60, dt.timezone.utc).isoformat()
    return {"id": "t1", "titel": "GEHEIM", "start": start, "ende": start, "ganztaegig": False, **mehr}


def test_termin_weckt_einmal_ohne_titel():
    uhr = Uhr()
    liste = [termin(8, uhr)]
    q = SimpleNamespace(eingerichtet=True, anstehende=lambda tage: liste)
    w, weck, _ = bauen([W.TerminQuelle(lambda: q, 10)], uhr)
    assert w.schlag()["geweckt"] == 1
    assert "8 Minuten" in weck.aufrufe[0]["text"] and "GEHEIM" not in weck.aufrufe[0]["text"]
    assert "vorgang" not in weck.aufrufe[0]
    uhr.t += 15
    assert w.schlag()["geweckt"] == 0
    liste[:] = [termin(40, uhr, id="t2"), termin(5, uhr, id="t3", ganztaegig=True)]
    assert w.schlag()["geweckt"] == 0, "zu weit weg oder ganztägig"


def test_postfach_und_dokumente_sammeln_still_fuer_den_naechsten_herzschlag():
    uhr = Uhr()
    mails = [{"id": "m1", "gelesen": False}]
    docs = [{"id": 1}]
    post = SimpleNamespace(eingerichtet=True, liste=lambda *a: {"mails": list(mails)})
    ablage = SimpleNamespace(eingerichtet=True, neueste=lambda n: {"dokumente": list(docs)})
    w, weck, _ = bauen([W.PostfachQuelle(lambda: post), W.DokumentQuelle(lambda: ablage)], uhr)
    w.schlag()
    mails.insert(0, {"id": "m2", "gelesen": False, "betreff": "GEHEIM"})
    mails.insert(0, {"id": "m3", "gelesen": True})
    assert w.schlag()["geweckt"] == 1
    docs.insert(0, {"id": 2})
    assert w.schlag()["geweckt"] == 1
    texte = [r["text"] for r in weck.aufrufe]
    assert texte[0].startswith("1 neue ungelesene Mails") and texte[1].startswith("1 neue Dokumente")
    assert {r["modus"] for r in weck.aufrufe} == {"naechster"}
    assert all("GEHEIM" not in t for t in texte)
    assert w.schlag()["geweckt"] == 0


def test_strom_quelle_liest_nur_neue_eintraege_und_wendet_regeln_an():
    uhr = Uhr()
    speicher = kv.SpeicherKv(uhr=uhr)
    weck = Weckrufe()
    w = W.Wecker(quellen=[W.StromQuelle(lambda: speicher, "fyos:events:node.critical")], regeln=W.vorgaben_regeln(),
                 schicken=weck, speicher=lambda: speicher, uhr=uhr)
    speicher.xadd("fyos:events:node.critical", {"source": "alt", "data": '{"node": "n0", "name": "n0"}'})
    w.schlag()  # Ausgangsstand
    speicher.xadd("fyos:events:node.critical", {"source": "monitor", "data": '{"node": "knoten-1", "name": "knoten-1"}'})
    assert w.schlag()["geweckt"] == 1
    assert "node.critical" in weck.aufrufe[0]["text"] and "kritisch" in weck.aufrufe[0]["text"]
    assert w.schlag()["geweckt"] == 0


# ── Regeln und Flussschutz ───────────────────────────────────────────────────────────────────

def test_regeln_pruefen_verwirft_fehlerhaftes_und_fuellt_vorgaben():
    assert [r["name"] for r in W.regeln_pruefen(None)] == ["vorgang", "termin", "eingang", "dringend"]
    regeln = W.regeln_pruefen([
        {"name": "a", "thema": ["ci.*"], "ziel": "haupt", "modus": "naechster", "max_pro_stunde": "5"},
        {"name": "ohne"}, {"thema": ["x"], "ziel": "woanders"}, {"thema": ["x"], "min_schwere": "extrem"}, "kein Objekt",
    ])
    assert [r["name"] for r in regeln] == ["a"] and regeln[0]["max_pro_stunde"] == 5
    assert W.regeln_pruefen([{"name": "kaputt"}])[0]["name"] == "vorgang"  # nichts Brauchbares: Vorgaben


def test_regel_mit_von_und_schwere():
    uhr = Uhr()
    w, _, _ = bauen([], uhr, regeln=W.regeln_pruefen([
        {"name": "nur_berta", "thema": ["itsm.*"], "von": ["Berta"], "min_schwere": "hoch"}]))
    def e(von, schwere):
        return {"thema": "itsm.neu", "von": von, "schwere": schwere}
    assert w.regel_fuer(e("berta", "hoch"))["name"] == "nur_berta"
    assert w.regel_fuer(e("carla", "hoch")) is None
    assert w.regel_fuer(e("berta", "normal")) is None


def test_mehrere_ereignisse_eines_ziels_werden_ein_weckruf():
    uhr, q = Uhr(), Vorgaenge()
    q.tickets = {"INC-1": ticket("INC-1")}
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-1"]["updated_at"] = "t1"
    q.history["INC-1"] = [{"ts": uhr.t - 1, "event": "comment", "actor": "carla"}, {"ts": uhr.t - 2, "event": "comment", "actor": "berta"}]
    assert w.schlag()["geweckt"] == 1
    assert weck.aufrufe[0]["text"].startswith("2 neue Ereignisse (itsm.kommentar)")
    assert w.zaehler["geweckt"] == 1 and w.zaehler["ereignisse"] == 2


def test_fluss_pro_minute_haelt_zurueck_und_holt_nach():
    uhr, q = Uhr(), Vorgaenge()
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr, max_pro_minute=2)
    w.schlag()
    uhr.t += 20
    for n in range(1, 5):
        q.tickets[f"INC-{n}"] = ticket(f"INC-{n}")
    r = w.schlag()
    assert (r["geweckt"], r["wartend"]) == (2, 2)
    uhr.t += 61
    r = w.schlag()
    assert (r["geweckt"], r["wartend"]) == (2, 0)
    assert sorted(a["vorgang"] for a in weck.aufrufe) == ["INC-1", "INC-2", "INC-3", "INC-4"]


def test_stundengrenze_je_regel_und_zu_altes_faellt_weg():
    uhr, q = Uhr(), Vorgaenge()
    regeln = W.regeln_pruefen([{"name": "v", "thema": ["itsm.neu"], "ziel": "vorgang", "max_pro_stunde": 1}])
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr, regeln=regeln, max_alter_s=100)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-1"] = ticket("INC-1")
    q.tickets["INC-2"] = ticket("INC-2")
    assert w.schlag()["geweckt"] == 1
    uhr.t += 150
    r = w.schlag()
    assert (r["geweckt"], r["wartend"]) == (0, 0)
    assert w.zaehler["verworfen"] == 1
    assert w.verlauf[-1]["ergebnis"] == "verworfen"


def test_fehler_beim_wecken_wird_wiederholt_und_nach_drei_versuchen_verworfen():
    uhr, q = Uhr(), Vorgaenge()
    w, weck, speicher = bauen([W.VorgangsQuelle(lambda: q)], uhr)
    w.schlag()
    weck.fehler = RuntimeError("Brücke weg")
    uhr.t += 20
    q.tickets["INC-1"] = ticket("INC-1")
    for _ in range(3):
        assert w.schlag()["geweckt"] == 0
        uhr.t += 20
    assert w.zaehler["fehler"] == 3 and "Brücke weg" in w.letzter_fehler
    w.schlag()
    assert w.zaehler["verworfen"] == 1 and not w._offen
    weck.fehler = None
    q.tickets["INC-2"] = ticket("INC-2")
    uhr.t += 20
    assert w.schlag()["geweckt"] == 1
    verlauf = w.zustand()["verlauf"]
    assert verlauf[0]["ergebnis"] == "geweckt" and verlauf[0]["ziel"] == "agent:wache:vorgang:INC-2"
    assert any(z["ergebnis"] == "fehler" for z in verlauf)
    assert speicher.xrevrange(W.STROM, count=1), "der Weckverlauf liegt auch im Strom"


# ── Plugin ───────────────────────────────────────────────────────────────────────────────────

def _plugin(**cfg: Any) -> tuple[OpenClawPlugin, list[tuple[str, dict[str, Any]]]]:
    aufrufe: list[tuple[str, dict[str, Any]]] = []

    def rpc(methode: str, params: dict[str, Any]) -> Any:
        aufrufe.append((methode, params))
        return {"geweckt": True, "sitzung": "agent:x:main"}

    speicher = kv.SpeicherKv()
    p = OpenClawPlugin({"gateway_url": "http://agent:18789", "token": "t", "rpc_aufruf": rpc,
                        "http_get": lambda url: (200, {"status": "live"}), "kv_fabrik": lambda: speicher, **cfg})
    return p, aufrufe


def test_plugin_wecker_ruft_fyos_wecken_mit_agent_und_modus():
    q = Vorgaenge()
    p, aufrufe = _plugin(agent="wache", wecken={"quellen_objekte": [W.VorgangsQuelle(lambda: q)], "quellen": {}})
    p.wecker_schlag()
    q.tickets["INC-3"] = ticket("INC-3")
    p.wecker_schlag()
    assert aufrufe and aufrufe[-1][0] == "fyos.wecken"
    assert aufrufe[-1][1]["vorgang"] == "INC-3" and aufrufe[-1][1]["agent"] == "wache"


def test_plugin_tools_wecken_vorgang_senden_ereignisse():
    p, aufrufe = _plugin(agent="wache")
    assert p.call("wecken", {"text": "Hallo", "vorgang": "INC-1", "modus": "naechster"})["geweckt"] is True
    assert aufrufe[-1] == ("fyos.wecken", {"text": "Hallo", "modus": "naechster", "vorgang": "INC-1", "agent": "wache"})
    p.call("vorgang_senden", {"vorgang": "INC-1", "text": "Nachricht", "schluessel": "k1"})
    assert aufrufe[-1] == ("fyos.vorgang.senden", {"vorgang": "INC-1", "text": "Nachricht", "schluessel": "k1", "agent": "wache"})
    z = p.call("ereignisse", {})
    assert z["aktiv"] is True and [r["name"] for r in z["regeln"]][0] == "vorgang" and "satz" in z
    aus, _ = _plugin(wecken={"aktiv": False})
    assert aus.call("ereignisse", {})["aktiv"] is False


def test_plugin_agent_main_schickt_keine_kennung_mit():
    p, aufrufe = _plugin()
    p.call("wecken", {"text": "Hallo"})
    assert "agent" not in aufrufe[-1][1]


def test_takt_fuehrt_den_wecker_aus_und_zeitplan_nennt_ihn():
    q = Vorgaenge()
    p, aufrufe = _plugin(wecken={"quellen_objekte": [W.VorgangsQuelle(lambda: q)], "intervall_s": 15})
    letzte: dict[str, float] = {}
    p.takt_schritt(letzte, jetzt=0.0)
    q.tickets["INC-9"] = ticket("INC-9")
    p.takt_schritt(letzte, jetzt=5.0)
    assert not [a for a in aufrufe if a[0] == "fyos.wecken"], "vor Ablauf des Abstands läuft der Wecker nicht"
    p.takt_schritt(letzte, jetzt=20.0)
    assert [a for a in aufrufe if a[0] == "fyos.wecken"][0][1]["vorgang"] == "INC-9"
    assert "wecken" in {x["id"] for x in p.zeitplan()}
    namen = {m["name"] for m in p.metrics()["_proben"]}
    assert {"fyos_openclaw_wecken_total", "fyos_openclaw_wecken_wartend"} <= namen
    aus, _ = _plugin(wecken={"aktiv": False})
    assert "wecken" not in {x["id"] for x in aus.zeitplan()}


def test_sitzungsereignis_mit_vorgang_landet_in_der_aktivitaet():
    p, _ = _plugin()
    p.annehmen({"bruecke": {}, "ereignisse": [{"art": "sitzung", "phase": "beginn", "sitzung": "abc", "agent": "wache",
                                                "vorgang": "INC-5", "zeit": 1_800_000_000_000}]})
    e = p.aktivitaet(5)["eintraege"][0]
    assert e["vorgang"] == "INC-5" and e["art"] == "sitzung"


def test_umschlag_und_wecker_sprechen_dieselbe_sitzung():
    assert U.sitzungsschluessel("inc-1", "wache") == "agent:wache:vorgang:INC-1"
    assert U.vorgang_gueltig("WB-1a2b3c4d") and not U.vorgang_gueltig("kein vorgang")
    assert U.vorgang_aus_schluessel("agent:wache:vorgang:WB-1a2b3c4d") == ("wache", "WB-1A2B3C4D")
