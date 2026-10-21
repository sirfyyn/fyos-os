"""Plugin ``desktop``: der Desktop eines Rechners als Werkzeuge.

Die Gegenstelle ist ein kleiner Dienst auf 127.0.0.1, der den Vertrag der Desktop-Brücke von ``fyos-oeffnen`` nachspielt
(``/lage``, ``/fenster``, ``/starter``, ``/bild``, ``/starten``, ``/fokus``, ``/schliessen``, alles mit Bearer-Token).
Geprüft wird, was der Hub daraus macht: nicht eingerichtet ist ein klarer Zustand, nichts Schreibendes ohne Plan und
Bestätigung, nur bekannte Starter und Fensteradressen gehen hinaus, das Token taucht nirgends in Antworten auf.
"""

from __future__ import annotations

import base64
import http.server
import json
import threading

import pytest

from mcp_hub import oeffnen
from mcp_hub.plugins.desktop import DesktopPlugin

TOKEN = "t0ken-" + "y" * 40
ADRESSE = "0x6491740897c0"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()

FENSTER = [
    {"adresse": ADRESSE, "klasse": "firefox_firefox", "titel": "FYOS — Mozilla Firefox", "arbeitsflaeche": 2, "vollbild": False, "fokus": True, "pid": 1},
    {"adresse": "0xabc123", "klasse": "foot", "titel": "nutzer@rechner", "arbeitsflaeche": 1, "vollbild": False, "fokus": False, "pid": 2},
]


AGENT_FENSTER = {"adresse": "g5", "klasse": "foot", "titel": "foot", "arbeitsflaeche": 1, "vollbild": False, "fokus": True, "pid": 7}


class Attrappe:
    def __init__(self) -> None:
        self.anfragen: list[tuple[str, str, dict | None, str | None]] = []
        self.lage_status = 200
        self.freigabe = False
        self.uebernommen = False
        attrappe = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):  # still
                pass

            def _senden(self, status, obj):
                b = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _pruefen(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._senden(401, {"ok": False, "error": "Token fehlt"})
                    return False
                return True

            def do_GET(self):  # noqa: N802
                attrappe.anfragen.append(("GET", self.path, None, self.headers.get("Authorization")))
                if not self._pruefen():
                    return
                agent = "ziel=agent" in self.path
                if agent and self.path.startswith("/fenster"):
                    return self._senden(200, {"ok": True, "ziel": "agent", "fenster": [AGENT_FENSTER]})
                if agent and self.path.startswith("/eingabe"):
                    return self._senden(200, {"ok": True, "ziel": "agent", "freigabe": not attrappe.uebernommen, "uebernommen": attrappe.uebernommen, "rest_sekunden": None})
                if agent and self.path.startswith("/lage"):
                    return self._senden(200, {"ok": True, "ziel": "agent", "arbeitsflaeche": "1", "fenster": 1, "modus": "agent",
                                              "monitore": [{"name": "HEADLESS-1", "breite": 1920, "hoehe": 1080, "takt": 0.0, "skala": 1.0}]})
                if agent and self.path.startswith("/bild"):
                    return self._senden(200, {"ok": True, "ziel": "agent", "typ": "image/png", "skala": 0.3, "groesse": 72, "daten": PNG})
                if self.path == "/lage":
                    if attrappe.lage_status != 200:
                        return self._senden(attrappe.lage_status, {"ok": False, "error": "keine Hyprland-Sitzung"})
                    return self._senden(200, {"ok": True, "arbeitsflaeche": 2, "fenster": 2, "modus": "gross",
                                              "monitore": [{"name": "HDMI-A-1", "breite": 3840, "hoehe": 1080, "takt": 120.0, "skala": 1.0}]})
                if self.path == "/fenster":
                    return self._senden(200, {"ok": True, "fenster": FENSTER})
                if self.path == "/starter":
                    return self._senden(200, {"ok": True, "starter": [{"id": "terminal", "name": "Terminal"}, {"id": "browser", "name": "Firefox"}]})
                if self.path == "/eingabe":
                    return self._senden(200, {"ok": True, "freigabe": attrappe.freigabe, "rest_sekunden": 540 if attrappe.freigabe else 0})
                if self.path.startswith("/bild"):
                    typ = "image/jpeg" if "format=jpeg" in self.path else "image/png"
                    return self._senden(200, {"ok": True, "typ": typ, "skala": 0.3, "groesse": 72, "daten": PNG})
                self._senden(404, {"ok": False, "error": "unbekannter Weg"})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", "0"))
                d = json.loads(self.rfile.read(n))
                attrappe.anfragen.append(("POST", self.path, d, self.headers.get("Authorization")))
                if not self._pruefen():
                    return
                if self.path == "/uebernehmen":
                    attrappe.uebernommen = d.get("an") is True
                    return self._senden(200, {"ok": True, "ziel": "agent", "uebernommen": attrappe.uebernommen})
                if self.path in ("/klick", "/tippen", "/taste", "/scrollen") and d.get("ziel") == "agent":
                    if attrappe.uebernommen:
                        return self._senden(423, {"ok": False, "uebernommen": True, "error": "Der Mensch hat übernommen"})
                    return self._senden(200, {"ok": True, "ziel": "agent", "aktion": self.path[1:]})
                if self.path in ("/klick", "/tippen", "/taste", "/scrollen"):
                    if not attrappe.freigabe:
                        return self._senden(423, {"ok": False, "freigabe": False, "error": "Keine Freigabe: Computer Use gibt nur ein Mensch am Rechner frei."})
                    return self._senden(200, {"ok": True, "aktion": self.path[1:], "rest_sekunden": 540})
                self._senden(200, {"ok": True})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def posts(self):
        return [a for a in self.anfragen if a[0] == "POST"]

    def ende(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in (oeffnen.ENV_GEGENSTELLE, oeffnen.ENV_TOKEN):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def gegenstelle():
    a = Attrappe()
    yield a
    a.ende()


def _plugin(gegenstelle: Attrappe | None, monkeypatch=None) -> DesktopPlugin:
    if gegenstelle is not None and monkeypatch is not None:
        monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    return DesktopPlugin({"gegenstelle": gegenstelle.url} if gegenstelle else {})


def test_werkzeuge_und_tags():
    namen = {t.name: t for t in DesktopPlugin({}).describe_tools()}
    assert set(namen) == {"zeigen", "fenster_lesen", "lage", "fenster", "starter", "bild", "starten", "fokus", "schliessen",
                          "eingabe", "uebernehmen", "klick", "tippen", "taste", "scrollen"}
    # die App darf alles außer der Eingabe aufrufen: klicken und tippen gehört dem Agenten, nicht einer Fläche
    assert all(("flaeche" in t.tags) == (n not in ("eingabe", "klick", "tippen", "taste", "scrollen")) for n, t in namen.items())
    assert "destructive" in namen["schliessen"].tags and "exec" in namen["starten"].tags
    for lesend in ("lage", "fenster", "starter", "bild"):
        assert "read" in namen[lesend].tags


def test_nicht_eingerichtet_ist_ein_zustand_kein_absturz():
    r = DesktopPlugin({}).call("lage", {})
    assert r["ok"] is False and r["zustand"] == "nicht eingerichtet"
    assert DesktopPlugin({}).health()["eingerichtet"] is False


def test_token_fehlt_in_der_umgebung(gegenstelle):
    r = DesktopPlugin({"gegenstelle": gegenstelle.url}).call("fenster", {})
    assert r["zustand"] == "nicht eingerichtet" and oeffnen.ENV_TOKEN in r["error"]
    assert gegenstelle.anfragen == []


def test_lage_fenster_starter(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    lage = p.call("lage", {})
    assert lage["ok"] and lage["modus"] == "gross" and "3840x1080" in lage["satz"]
    fenster = p.call("fenster", {})
    assert [f["adresse"] for f in fenster["fenster"]] == [ADRESSE, "0xabc123"]
    assert "2 Fenster" in fenster["satz"]
    assert [s["id"] for s in p.call("starter", {})["starter"]] == ["terminal", "browser"]
    assert all(a[3] == f"Bearer {TOKEN}" for a in gegenstelle.anfragen)


def test_bild_und_skala(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("bild", {"skala": 0.5})
    assert r["ok"] and r["typ"] == "image/png" and r["daten_base64"] == PNG
    assert gegenstelle.anfragen[-1][1] == "/bild?skala=0.50"
    for schlecht in (0.01, 2, "viel", True):
        with pytest.raises(ValueError):
            p.call("bild", {"skala": schlecht})


@pytest.mark.parametrize("werkzeug,args", [("starten", {"starter": "terminal"}), ("fokus", {"adresse": ADRESSE}), ("schliessen", {"adresse": ADRESSE})])
def test_schreibendes_braucht_bestaetigung(gegenstelle, monkeypatch, werkzeug, args):
    p = _plugin(gegenstelle, monkeypatch)
    with pytest.raises(ValueError, match="bestaetigt"):
        p.call(werkzeug, args)
    plan = p.call(werkzeug, {**args, "__dry_run__": True})
    assert plan.get("dry_run") is True or "would_execute" in json.dumps(plan)
    assert gegenstelle.posts() == []
    p.call(werkzeug, {**args, "bestaetigt": True})
    assert len(gegenstelle.posts()) == 1


def test_starten_nur_bekannte_starter(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    with pytest.raises(ValueError, match="kein freigegebener Starter"):
        p.call("starten", {"starter": "rm -rf /", "bestaetigt": True})
    r = p.call("starten", {"starter": "terminal", "bestaetigt": True})
    assert r["ok"] and gegenstelle.posts()[0][1:3] == ("/starten", {"starter": "terminal"})


def test_fenster_nur_mit_echter_adresse(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    for schlecht in ("firefox", "0x", "0xZZ", "0x6491740897c0; ls", 5, None):
        with pytest.raises(ValueError, match="adresse"):
            p.call("fokus", {"adresse": schlecht, "bestaetigt": True})
    with pytest.raises(ValueError, match="Kein offenes Fenster"):
        p.call("schliessen", {"adresse": "0xdead", "bestaetigt": True})
    assert gegenstelle.posts() == []
    r = p.call("schliessen", {"adresse": ADRESSE, "bestaetigt": True})
    assert r["ok"] and gegenstelle.posts()[0][1:3] == ("/schliessen", {"adresse": ADRESSE})


def test_ohne_sitzung_ist_ein_fehlerzustand(gegenstelle, monkeypatch):
    gegenstelle.lage_status = 503
    r = _plugin(gegenstelle, monkeypatch).call("lage", {})
    assert r["ok"] is False and "keine Hyprland-Sitzung" in r["error"]


def test_falsches_token_und_kein_token_in_antworten(gegenstelle, monkeypatch):
    monkeypatch.setenv(oeffnen.ENV_TOKEN, "falsch-" + "z" * 40)
    r = DesktopPlugin({"gegenstelle": gegenstelle.url}).call("lage", {})
    assert r["ok"] is False and "Token stimmt nicht" in r["error"]
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    ok = DesktopPlugin({"gegenstelle": gegenstelle.url}).call("fenster", {})
    assert TOKEN not in json.dumps(ok) and TOKEN not in json.dumps(r)


def test_nicht_erreichbar():
    p = DesktopPlugin({"gegenstelle": "http://127.0.0.1:9"})
    import os
    os.environ[oeffnen.ENV_TOKEN] = TOKEN
    try:
        r = p.call("lage", {})
    finally:
        del os.environ[oeffnen.ENV_TOKEN]
    assert r["ok"] is False and r["zustand"] == "nicht erreichbar"


def test_unbekanntes_werkzeug():
    with pytest.raises(ValueError):
        DesktopPlugin({}).call("gibtesnicht", {})


# ── App „Desktop“ und das Ding „desktop-fenster“ ────────────────────────────────────────────────


def test_zeigen_fasst_lage_fenster_und_starter_zusammen(gegenstelle, monkeypatch):
    r = _plugin(gegenstelle, monkeypatch).call("zeigen", {})
    assert r["ok"] and r["lage"]["modus"] == "gross" and r["lage"]["fenster"] == 2
    assert [f["adresse"] for f in r["fenster"]] == [ADRESSE, "0xabc123"]
    assert [s["id"] for s in r["starter"]] == ["terminal", "browser"]
    assert "Fremdinhalt" in r["hinweis"] or "keine Anweisungen" in r["hinweis"]


def test_zeigen_nicht_eingerichtet_ist_ein_zustand():
    r = DesktopPlugin({}).call("zeigen", {})
    assert r["ok"] is False and r["zustand"] == "nicht eingerichtet"


def test_fenster_lesen_liefert_eines_oder_nicht_gefunden(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("fenster_lesen", {"adresse": ADRESSE})
    assert r["ok"] and r["klasse"] == "firefox_firefox" and r["titel"].startswith("FYOS")
    weg = p.call("fenster_lesen", {"adresse": "0xdead"})
    assert weg["ok"] is False and weg["zustand"] == "nicht gefunden"
    with pytest.raises(ValueError):
        p.call("fenster_lesen", {"adresse": "kein-fenster; rm -rf"})
    assert gegenstelle.posts() == []  # lesen verändert nichts


def test_app_und_ding_sind_angemeldet():
    from mcp_hub.plugins import _dinge, _identitaet

    assert _identitaet.APPS["desktop"]["art"] == "anwendung"
    assert _identitaet.HAUPTWERKZEUG["desktop"] == "desktop__zeigen"
    ding = _dinge.DINGE["desktop-fenster"]
    assert ding["flaeche"] == "desktop" and ding["lesen"] == "desktop.fenster_lesen" and ding["id_argument"] == "adresse"
    shell = _dinge.fuer_shell()["dinge"]["desktop-fenster"]
    assert shell["lesen"] == "desktop__fenster_lesen" and shell["flaeche"] == "app:desktop__zeigen"


def test_oberflaeche_wird_ausgeliefert_und_nennt_ding_und_werkzeuge():
    p = DesktopPlugin({})
    ressource = p.describe_resources()[0]
    html = ressource.read()
    assert "/*BRUECKE*/" not in html and "/*STIL*/" not in html  # Marken sind ersetzt
    for erwartet in ("desktop-fenster", "desktop__", '"zeigen"', '"fokus"', '"schliessen"', '"starten"'):
        assert erwartet in html, erwartet
    assert "App.ziehbar" in html and "App.beantragen" in html  # Schreibendes nur über Plan und „Ja“


# ── Eingabe (Computer Use) ───────────────────────────────────────────────────────────────────────


def test_eingabe_gesperrt_ist_ein_zustand_kein_fehler(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    for methode, args in (("klick", {"x": 10, "y": 10}), ("tippen", {"text": "hallo"}), ("taste", {"kombi": "Return"}), ("scrollen", {"dy": -3})):
        r = p.call(methode, args)
        assert r["ok"] is False and r["zustand"] == "gesperrt", methode
    assert p.call("eingabe", {})["freigabe"] is False


def test_eingabe_laeuft_mit_freigabe_und_reicht_die_werte_durch(gegenstelle, monkeypatch):
    gegenstelle.freigabe = True
    p = _plugin(gegenstelle, monkeypatch)
    assert p.call("eingabe", {})["freigabe"] is True
    r = p.call("klick", {"x": 120.5, "y": 80, "doppelt": True, "unbekannt": "wird verworfen"})
    assert r["ok"] and r["aktion"] == "klick"
    r = p.call("tippen", {"text": "FYOS"})
    assert r["ok"] and r["aktion"] == "tippen"
    posts = {pfad: koerper for _, pfad, koerper, _ in gegenstelle.posts()}
    assert posts["/klick"] == {"x": 120.5, "y": 80, "doppelt": True, "skala": 0.3}  # Skala wie bei desktop.bild
    assert posts["/tippen"] == {"text": "FYOS"}


def test_eingabe_trockenlauf_sendet_nichts_und_zeigt_den_text_nicht(gegenstelle, monkeypatch):
    gegenstelle.freigabe = True
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("tippen", {"text": "passwort-123", "__dry_run__": True})
    assert r["dry_run"] is True and "passwort-123" not in json.dumps(r) and "12 Zeichen" in json.dumps(r)
    assert gegenstelle.posts() == []


def test_zeigen_nennt_den_stand_der_freigabe(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    assert p.call("zeigen", {})["eingabe"] == {"freigabe": False, "rest_sekunden": 0}
    gegenstelle.freigabe = True
    assert p.call("zeigen", {})["eingabe"] == {"freigabe": True, "rest_sekunden": 540}


def test_kein_werkzeug_gibt_frei():
    namen = {t.name for t in DesktopPlugin({}).describe_tools()}
    assert not {n for n in namen if "freigeb" in n or "freigabe" in n or n in ("an", "aus")}  # nur `eingabe` liest den Stand


# ── Ziel „agent“: der eigene Desktop des Agenten ─────────────────────────────────────────────────────────────

def test_ziel_agent_liest_den_anderen_desktop(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    fenster = p.call("fenster", {"ziel": "agent"})
    assert [f["adresse"] for f in fenster["fenster"]] == ["g5"]
    assert gegenstelle.anfragen[-1][1] == "/fenster?ziel=agent"
    assert "Desktop des Agenten" in p.call("lage", {"ziel": "agent"})["satz"]
    assert gegenstelle.anfragen[-1][1] == "/lage?ziel=agent"
    p.call("bild", {"ziel": "agent", "skala": 0.5})
    assert gegenstelle.anfragen[-1][1] == "/bild?skala=0.50&ziel=agent"
    assert p.call("fenster", {})["fenster"][0]["adresse"] == ADRESSE  # ohne ziel bleibt es der Desktop des Menschen
    with pytest.raises(ValueError, match="ziel"):
        p.call("fenster", {"ziel": "alle"})


def test_adresse_mit_g_trifft_agents_desktop_ohne_ziel(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("fenster_lesen", {"adresse": "g5"})
    assert r["ok"] and r["klasse"] == "foot"
    assert gegenstelle.anfragen[-1][1] == "/fenster?ziel=agent"
    plan = p.call("fokus", {"adresse": "g5", "__dry_run__": True})
    assert "foot" in json.dumps(plan, ensure_ascii=False) and gegenstelle.posts() == []
    p.call("fokus", {"adresse": "g5", "bestaetigt": True})
    assert gegenstelle.posts()[-1][2] == {"adresse": "g5", "ziel": "agent"}


def test_agent_tippt_ohne_freigabe_und_ruht_beim_uebernehmen(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    assert gegenstelle.freigabe is False  # keine Freigabe am Rechner des Menschen
    r = p.call("tippen", {"ziel": "agent", "text": "hallo"})
    assert r["ok"] and gegenstelle.posts()[-1][2] == {"text": "hallo", "ziel": "agent"}
    assert p.call("eingabe", {"ziel": "agent"})["freigabe"] is True
    assert p.call("uebernehmen", {"an": True})["uebernommen"] is True  # Übernehmen hält der Agent nur an, braucht keine Bestätigung
    r = p.call("klick", {"ziel": "agent", "x": 10, "y": 10})
    assert r["zustand"] == "gesperrt" and "übernommen" in r["satz"]
    assert p.call("eingabe", {"ziel": "agent"})["uebernommen"] is True
    with pytest.raises(ValueError, match="bestaetigt"):  # Zurückgeben ist ein echter Lauf
        p.call("uebernehmen", {"an": False})
    assert "would_execute" in json.dumps(p.call("uebernehmen", {"an": False, "__dry_run__": True}))
    assert gegenstelle.uebernommen is True
    assert p.call("uebernehmen", {"an": False, "bestaetigt": True})["uebernommen"] is False
    assert p.call("tippen", {"ziel": "agent", "text": "wieder"})["ok"]


def test_max_bleibt_hinter_der_freigabe_auch_wenn_agent_frei_ist(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("tippen", {"text": "hallo"})  # ziel mensch
    assert r["zustand"] == "gesperrt" and "Mensch am Rechner" in r["satz"]
    assert "ziel" not in gegenstelle.posts()[-1][2]


def test_bild_als_jpeg_fuer_die_live_ansicht(gegenstelle, monkeypatch):
    p = _plugin(gegenstelle, monkeypatch)
    r = p.call("bild", {"skala": 0.5, "format": "jpeg", "qualitaet": 60})
    assert r["ok"] and r["typ"] == "image/jpeg"
    assert gegenstelle.anfragen[-1][1] == "/bild?skala=0.50&format=jpeg&qualitaet=60"
    p.call("bild", {"ziel": "agent", "format": "jpeg"})
    assert gegenstelle.anfragen[-1][1] == "/bild?skala=0.30&format=jpeg&qualitaet=70&ziel=agent"
    for schlecht in ({"format": "gif"}, {"qualitaet": 5}, {"qualitaet": "hoch"}, {"qualitaet": True}):
        with pytest.raises(ValueError):
            p.call("bild", {"format": "jpeg", **schlecht} if "format" not in schlecht else schlecht)
