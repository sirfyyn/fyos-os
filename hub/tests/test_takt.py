"""takt: Tageslimit, Zeitfenster und Laufprotokoll der Plugin-Takte — ohne Redis, mit eigener Uhr und Zeitzone."""

from __future__ import annotations

import calendar
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_hub import kv, metriken, takt, zeitplan
from mcp_hub.takt import Grenzen, GrenzenFehler, Waechter, fenster_lesen

pytestmark = pytest.mark.skipif(not hasattr(time, "tzset"), reason="Zeitzone per TZ nur auf Unix umschaltbar")

VERSATZ_H = 2  # TZ=UTC-2 heißt (POSIX): zwei Stunden vor UTC, ohne Zeitzonen-Datenbank


@pytest.fixture(autouse=True)
def zeitzone(monkeypatch):
    monkeypatch.setenv("TZ", f"UTC-{VERSATZ_H}")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def lokal(stunde: int, minute: int = 0, tag: int = 9) -> float:
    """Unix-Sekunden für „Oktober 2026, <tag>., <stunde>:<minute> Uhr“ in der Zeitzone des Tests."""
    return float(calendar.timegm((2026, 10, tag, stunde, minute, 0)) - VERSATZ_H * 3600)


class Uhr:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _waechter(grenzen: dict[str, Any] | None = None, t: float | None = None, **kw: Any):
    uhr = Uhr(lokal(12) if t is None else t)
    speicher = kv.SpeicherKv(uhr=uhr)
    return Waechter("demo", grenzen, speicher=lambda: speicher, uhr=uhr, **kw), uhr, speicher


class Zaehler:
    """Eine Aufgabe, die mitzählt, wie oft sie lief."""

    def __init__(self, wert: Any = "fertig") -> None:
        self.n = 0
        self.wert = wert
        self._sperre = threading.Lock()

    def __call__(self) -> Any:
        with self._sperre:
            self.n += 1
        return self.wert


# ── Grenzen lesen ───────────────────────────────────────────────────────────────────────────────


def test_fenster_lesen_nimmt_uhrzeiten_an():
    assert fenster_lesen("07:00-22:00") == (420, 1320)
    assert fenster_lesen(" 7:05 – 22:30 ") == (425, 1350)
    assert fenster_lesen("00:00-24:00") == (0, 1440)
    assert fenster_lesen("22:00-06:00") == (1320, 360)


@pytest.mark.parametrize("text", ["abends", "07:00", "07:60-08:00", "25:00-26:00", "24:00-02:00", "07:00-24:30", "08:00-08:00", "", None])
def test_fenster_lesen_lehnt_unbrauchbares_ab(text):
    with pytest.raises(GrenzenFehler):
        fenster_lesen(text)


def test_grenzen_aus_der_konfiguration():
    assert Grenzen.lesen(None).leer and Grenzen.lesen({}).leer and Grenzen.lesen({"fenster": "", "max_pro_tag": None}).leer
    g = Grenzen.lesen({"max_pro_tag": 5, "fenster": "07:00-22:00"})
    assert (g.max_pro_tag, g.fenster, g.leer) == (5, "07:00-22:00", False)
    assert Grenzen.lesen({"max_pro_tag": "12"}).max_pro_tag == 12 and Grenzen.lesen({"max_pro_tag": 12.0}).max_pro_tag == 12
    assert Grenzen.lesen({"fenster": "7:00-9:05"}).fenster == "07:00-09:05"


@pytest.mark.parametrize("roh", [{"max_pro_tag": 0}, {"max_pro_tag": -1}, {"max_pro_tag": True}, {"max_pro_tag": 1.5},
                                 {"max_pro_tag": "viele"}, {"max_pro_tag": [3]}, {"fenster": "abends"}, "07:00-22:00", [1]])
def test_grenzen_lehnen_unbrauchbares_ab(roh):
    with pytest.raises(GrenzenFehler):
        Grenzen.lesen(roh)


def test_tippfehler_im_schluessel_fallen_auf_und_nennen_den_ort():
    with pytest.raises(GrenzenFehler, match=r"^openclaw\.abgleich: unbekannt: max_pro_tage"):
        Grenzen.lesen({"max_pro_tage": 3}, "openclaw.abgleich")
    with pytest.raises(GrenzenFehler, match=r"^openclaw\.abgleich: fenster 'abends'"):
        Grenzen.lesen({"fenster": "abends"}, "openclaw.abgleich")


def test_im_fenster_gilt_von_einschliesslich_bis_ausschliesslich():
    tag = Grenzen.lesen({"fenster": "07:00-22:00"})
    assert [tag.im_fenster(m) for m in (419, 420, 1319, 1320)] == [False, True, True, False]
    nacht = Grenzen.lesen({"fenster": "22:00-06:00"})  # über Mitternacht
    assert [nacht.im_fenster(m) for m in (1319, 1320, 0, 359, 360, 720)] == [False, True, True, True, False, False]
    ganz = Grenzen.lesen({"fenster": "00:00-24:00"})
    assert ganz.im_fenster(0) and ganz.im_fenster(1439)
    assert Grenzen().im_fenster(0) and Grenzen().im_fenster(1439)


# ── Läufe ───────────────────────────────────────────────────────────────────────────────────────


def test_ohne_grenzen_laeuft_alles_wie_bisher():
    w, _uhr, _kv = _waechter()
    aufgabe = Zaehler()
    laeufe = [w.ausfuehren("abgleich", aufgabe) for _ in range(50)]
    assert aufgabe.n == 50 and all(l.gelaufen and l.grund is None and l.wert == "fertig" for l in laeufe)
    f = w.felder("abgleich")
    assert (f["max_pro_tag"], f["fenster"], f["ruht"], f["uebersprungen"]) == (None, None, None, {})
    assert f["laeufe_heute"] == 50


def test_tageslimit_ueberspringt_zaehlt_und_beginnt_morgen_neu():
    w, uhr, speicher = _waechter({"abgleich": {"max_pro_tag": 3}})
    aufgabe = Zaehler()
    ergebnisse = [w.ausfuehren("abgleich", aufgabe) for _ in range(5)]
    assert [e.gelaufen for e in ergebnisse] == [True, True, True, False, False]
    assert [e.grund for e in ergebnisse[3:]] == ["limit", "limit"] and aufgabe.n == 3
    f = w.felder("abgleich")
    assert (f["laeufe_heute"], f["uebersprungen"], f["ruht"], f["max_pro_tag"]) == (3, {"limit": 2}, "limit", 3)
    # Ein anderer Takt hat sein eigenes Konto.
    assert w.ausfuehren("skills", Zaehler()).gelaufen
    # Am nächsten Kalendertag (Zeitzone des Hubs) beginnt das Konto von vorn.
    uhr.t = lokal(0, 1, tag=10)
    assert w.ausfuehren("abgleich", aufgabe).gelaufen
    f = w.felder("abgleich")
    assert (f["laeufe_heute"], f["uebersprungen"], f["ruht"]) == (1, {"limit": 0}, None)
    # Der Tageszähler läuft ab: nach drei Tagen ist der Schlüssel weg.
    assert speicher.exists("fyos:takt:demo:tag:2026-10-09") == 1
    uhr.t = lokal(12, tag=13)
    assert speicher.exists("fyos:takt:demo:tag:2026-10-09") == 0


def test_fenster_ueberspringt_und_verbraucht_kein_tageslimit():
    w, uhr, _kv = _waechter({"abgleich": {"fenster": "07:00-22:00", "max_pro_tag": 2}})
    aufgabe = Zaehler()
    uhr.t = lokal(6, 59)
    assert [w.ausfuehren("abgleich", aufgabe).grund for _ in range(2)] == ["fenster", "fenster"]
    assert w.felder("abgleich")["ruht"] == "fenster" and aufgabe.n == 0
    uhr.t = lokal(7, 0)
    assert w.ausfuehren("abgleich", aufgabe).gelaufen
    uhr.t = lokal(7, 1)
    assert w.ausfuehren("abgleich", aufgabe).gelaufen
    uhr.t = lokal(8, 0)
    assert w.ausfuehren("abgleich", aufgabe).grund == "limit"
    uhr.t = lokal(22, 0)
    assert w.ausfuehren("abgleich", aufgabe).grund == "fenster"
    f = w.felder("abgleich")
    assert (f["laeufe_heute"], f["uebersprungen"], f["ruht"]) == (2, {"fenster": 3, "limit": 1}, "fenster")
    assert aufgabe.n == 2


def test_fenster_ueber_mitternacht_und_tageswechsel():
    w, uhr, _kv = _waechter({"nacht": {"fenster": "22:00-06:00"}})
    aufgabe = Zaehler()
    uhr.t = lokal(23, 30, tag=9)
    assert w.ausfuehren("nacht", aufgabe).gelaufen
    uhr.t = lokal(5, 59, tag=10)
    assert w.ausfuehren("nacht", aufgabe).gelaufen
    uhr.t = lokal(6, 0, tag=10)
    assert w.ausfuehren("nacht", aufgabe).grund == "fenster"
    assert aufgabe.n == 2
    assert w.felder("nacht")["laeufe_heute"] == 1  # der Tag zählt nach dem Kalender, nicht nach dem Fenster


def test_die_zeitzone_ist_die_des_hub_prozesses(monkeypatch):
    # 05:30 UTC = 07:30 in UTC+2 (im Fenster), aber 05:30 in UTC (außerhalb)
    t = float(calendar.timegm((2026, 10, 9, 5, 30, 0)))
    w, _uhr, _kv = _waechter({"abgleich": {"fenster": "07:00-22:00"}}, t=t)
    assert w.ausfuehren("abgleich", Zaehler()).gelaufen
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    assert w.ausfuehren("abgleich", Zaehler()).grund == "fenster"


def test_nebenlaeufige_takte_halten_das_tageslimit_genau():
    w, _uhr, _kv = _waechter({"abgleich": {"max_pro_tag": 25}})
    aufgabe = Zaehler()

    def versuche() -> None:
        for _ in range(10):
            w.ausfuehren("abgleich", aufgabe)

    faeden = [threading.Thread(target=versuche) for _ in range(8)]
    [f.start() for f in faeden]
    [f.join() for f in faeden]
    f = w.felder("abgleich")
    assert aufgabe.n == 25 and f["laeufe_heute"] == 25 and f["uebersprungen"] == {"limit": 55}


# ── Laufprotokoll ───────────────────────────────────────────────────────────────────────────────


def test_protokoll_hat_start_dauer_ergebnis_und_ist_gekappt():
    w, uhr, speicher = _waechter()
    for i in range(25):
        uhr.t = lokal(12, 0) + i
        w.ausfuehren("abgleich", Zaehler())
    liste = speicher.lrange("fyos:takt:demo:abgleich:laeufe", 0, -1)
    assert len(liste) == takt.PROTOKOLL_MAX == 20
    neueste = w.protokoll("abgleich", 3)
    assert [e["start"] for e in neueste] == [int(lokal(12, 0)) + 24, int(lokal(12, 0)) + 23, int(lokal(12, 0)) + 22]
    assert all(e["ergebnis"] == "ok" and 0 <= e["dauer_s"] < 5 and "fehler" not in e for e in neueste)
    assert len(w.felder("abgleich")["protokoll"]) == takt.PROTOKOLL_ANZEIGE == 5
    assert w.protokoll("abgleich", 0) == []
    # Ohne weiteren Lauf läuft das Protokoll nach einer Woche ab.
    uhr.t += 8 * 86400
    assert w.protokoll("abgleich") == []


def test_fehler_stehen_im_protokoll_und_die_ausnahme_geht_weiter():
    w, _uhr, _kv = _waechter({"abgleich": {"max_pro_tag": 5}})

    def kaputt() -> None:
        raise RuntimeError("Anmeldung gescheitert: password=hunter2hunter2 " + "x" * 400)

    with pytest.raises(RuntimeError):
        w.ausfuehren("abgleich", kaputt)
    (e,) = w.protokoll("abgleich")
    assert e["ergebnis"] == "fehler" and e["fehler"].startswith("RuntimeError: Anmeldung gescheitert")
    assert "hunter2" not in e["fehler"] and len(e["fehler"]) <= 120
    assert w.felder("abgleich")["laeufe_heute"] == 1  # der Lauf hat stattgefunden


def test_ein_ergebnis_mit_ok_false_gilt_als_fehlgeschlagen():
    w, _uhr, _kv = _waechter()
    w.ausfuehren("a", lambda: {"ok": False, "satz": "Abgleich gescheitert: Dienst weg"})
    w.ausfuehren("a", lambda: {"ok": False, "error": "kein Zugriff"})
    w.ausfuehren("a", lambda: {"ok": True, "schritte": 0})
    neu, mitte, alt = w.protokoll("a")
    assert (alt["ergebnis"], mitte["ergebnis"], neu["ergebnis"]) == ("fehler", "fehler", "ok")
    assert alt["fehler"] == "Abgleich gescheitert: Dienst weg" and mitte["fehler"] == "kein Zugriff"


# ── Speicher fällt aus ──────────────────────────────────────────────────────────────────────────


class Kaputt:
    """Ein Speicher, der nicht antwortet; zählt die Versuche."""

    def __init__(self) -> None:
        self.versuche = 0

    def __getattr__(self, name: str):
        def aufruf(*_a: Any, **_k: Any) -> None:
            self.versuche += 1
            raise ConnectionError("Redis weg")

        return aufruf


def test_ausfall_des_speichers_haelt_den_takt_nicht_auf():
    kaputt = Kaputt()
    uhr = Uhr(lokal(12))
    w = Waechter("demo", {"abgleich": {"max_pro_tag": 2}}, speicher=lambda: kaputt, uhr=uhr)
    aufgabe = Zaehler()
    gruende = [w.ausfuehren("abgleich", aufgabe).grund for _ in range(4)]
    assert gruende == [None, None, "limit", "limit"] and aufgabe.n == 2  # das Limit gilt im Prozess weiter
    assert kaputt.versuche == 1  # danach ruht der Speicher, kein Warten auf Zeitüberschreitungen
    f = w.felder("abgleich")
    assert (f["laeufe_heute"], f["uebersprungen"], f["protokoll"]) == (2, {"limit": 2}, [])
    assert kaputt.versuche == 1


def test_der_speicher_wird_nach_der_ruhe_wieder_benutzt():
    echt = kv.SpeicherKv()
    stand = {"kaputt": True}

    class Wackelig:
        def __getattr__(self, name: str):
            def aufruf(*a: Any, **k: Any) -> Any:
                if stand["kaputt"]:
                    raise ConnectionError("weg")
                return getattr(echt, name)(*a, **k)

            return aufruf

    w = Waechter("demo", speicher=lambda: Wackelig(), uhr=Uhr(lokal(12)))
    w.ausfuehren("a", Zaehler())  # zählt im Prozess
    stand["kaputt"] = False
    w.ausfuehren("a", Zaehler())  # Speicher ruht noch
    assert echt.hgetall("fyos:takt:demo:tag:2026-10-09") == {}
    w._ruht_bis = 0.0
    w.ausfuehren("a", Zaehler())
    assert echt.hgetall("fyos:takt:demo:tag:2026-10-09") == {"a": "1"}
    assert len(w.protokoll("a")) == 1


# ── Prüfungen beim Aufbau ───────────────────────────────────────────────────────────────────────


def test_unbekannte_takte_und_namen_werden_abgelehnt():
    with pytest.raises(GrenzenFehler, match=r"'abgleichh'.*bekannt: abgleich, skills"):
        Waechter("openclaw", {"abgleichh": {"max_pro_tag": 1}}, takte=("abgleich", "skills"))
    with pytest.raises(GrenzenFehler, match="Zuordnung"):
        Waechter("openclaw", ["abgleich"])
    w, _uhr, _kv = _waechter()
    for schlecht in ("", "a b", "../x", "a:b", "a|b", "x" * 65, None):
        with pytest.raises(ValueError):
            w.zulassen(schlecht)


# ── Eintrag in zeitplan() und Reihen in /metrics ────────────────────────────────────────────────


def _plan(w: Waechter) -> list[dict[str, Any]]:
    return [{"id": "a", "name": "Abgleich", "takt": "alle 60 s", **w.felder("a")}]


def test_felder_fliessen_in_den_eintrag_und_die_zeitplan_ansicht():
    w, uhr, _kv = _waechter({"a": {"max_pro_tag": 1, "fenster": "07:00-22:00"}})
    w.ausfuehren("a", Zaehler())
    w.ausfuehren("a", Zaehler())  # über dem Limit
    plugin = SimpleNamespace(name="demo", zeitplan=lambda: _plan(w))
    ansicht = zeitplan.sammeln(SimpleNamespace(plugins={"demo": plugin}))
    (e,) = ansicht["eintraege"]
    assert (e["max_pro_tag"], e["fenster"], e["ruht"], e["laeufe_heute"]) == (1, "07:00-22:00", "limit", 1)
    assert e["uebersprungen"] == {"fenster": 0, "limit": 1}
    assert e["protokoll"][0]["ergebnis"] == "ok" and set(e["protokoll"][0]) == {"start", "dauer_s", "ergebnis"}
    assert "ruhen gerade" in ansicht["satz"] and "Abgleich" in ansicht["satz"]


def test_eintraege_ohne_waechter_bleiben_wie_sie_waren():
    e = zeitplan.eintrag("demo", {"id": "a", "name": "A", "takt": "alle 60 s", "letzter": 100.0, "letzter_status": "ok"})
    assert (e["max_pro_tag"], e["fenster"], e["ruht"], e["laeufe_heute"], e["uebersprungen"], e["protokoll"]) == \
           (None, None, None, None, {}, [])
    assert "ruhen" not in zeitplan.sammeln(SimpleNamespace(plugins={"demo": SimpleNamespace(zeitplan=lambda: [
        {"id": "a", "name": "A", "takt": "x"}])}))["satz"]


def test_eintrag_nimmt_nichts_ungeprueftes_an():
    e = zeitplan.eintrag("demo", {"id": "a", "max_pro_tag": "x", "fenster": None, "laeufe_heute": -3, "ruht": "",
                                  "uebersprungen": "kaputt", "protokoll": "kaputt"})
    assert (e["max_pro_tag"], e["laeufe_heute"], e["ruht"], e["uebersprungen"], e["protokoll"]) == (None, None, None, {}, [])
    e = zeitplan.eintrag("demo", {"id": "a", "max_pro_tag": True, "laeufe_heute": True,
                                  "uebersprungen": {"limit": "3", "fenster": -1, "": 5, "x": "n"},
                                  "protokoll": [1, {}, {"start": 5, "ergebnis": "ok"}]})
    assert e["max_pro_tag"] is None and e["laeufe_heute"] is None and e["uebersprungen"] == {"limit": 3}
    assert e["protokoll"] == [{"start": 5.0, "dauer_s": 0.0, "ergebnis": "ok"}]
    lang = zeitplan.eintrag("demo", {"id": "a", "protokoll": [{"start": 100 + i, "fehler": "f" * 500} for i in range(30)]})
    assert len(lang["protokoll"]) == zeitplan.PROTOKOLL_MAX and len(lang["protokoll"][0]["fehler"]) == 200


def test_metrics_fuehrt_laeufe_heute_limit_und_uebersprungene():
    w, uhr, _kv = _waechter({"a": {"max_pro_tag": 3, "fenster": "07:00-22:00"}})
    for _ in range(3):
        w.ausfuehren("a", Zaehler())
    w.ausfuehren("a", Zaehler())  # Limit
    uhr.t = lokal(3)
    w.ausfuehren("a", Zaehler())  # Fenster
    plugin = SimpleNamespace(name="demo", zeitplan=lambda: _plan(w), metrics=lambda: {})
    reg = SimpleNamespace(plugins={"demo": plugin}, tools={}, nicht_geladen={}, call_counts={}, latency_totals_ms={})
    text = metriken.erzeugen(reg)
    assert 'fyos_zeitplan_laeufe_heute{takt="demo:a"} 3' in text
    assert 'fyos_zeitplan_max_pro_tag{takt="demo:a"} 3' in text
    assert 'fyos_zeitplan_uebersprungen_total{grund="fenster",takt="demo:a"} 1' in text
    assert 'fyos_zeitplan_uebersprungen_total{grund="limit",takt="demo:a"} 1' in text
    assert "# TYPE fyos_zeitplan_uebersprungen_total counter" in text and "# TYPE fyos_zeitplan_laeufe_heute gauge" in text
    # Aufgaben ohne Wächter erzeugen keine dieser Reihen.
    ohne = SimpleNamespace(name="ohne", zeitplan=lambda: [{"id": "t", "name": "T", "takt": "x"}], metrics=lambda: {})
    text = metriken.erzeugen(SimpleNamespace(plugins={"ohne": ohne}, tools={}, nicht_geladen={}, call_counts={}, latency_totals_ms={}))
    assert "laeufe_heute" not in text and "uebersprungen" not in text and "max_pro_tag" not in text
