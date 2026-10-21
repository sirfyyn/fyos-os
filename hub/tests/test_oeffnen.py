"""„Öffnen mit“: die Gegenstelle (``mcp_hub/oeffnen.py``) und die Werkzeuge ``dateien.oeffnen_programme`` / ``oeffnen_mit``.

Die Gegenstelle ist hier ein kleiner Dienst auf 127.0.0.1, der den Vertrag von ``fyos-oeffnen`` nachspielt:
``GET /programme`` und ``POST /oeffnen`` mit Bearer-Token. Geprüft wird, was der Hub daraus macht: nicht eingerichtet
ist ein klarer Zustand, nichts Schreibendes ohne Plan und Bestätigung, das Token taucht nirgends in Antworten auf.
"""

from __future__ import annotations

import http.server
import json
import threading

import pytest

from mcp_hub import dateien as store
from mcp_hub import oeffnen
from mcp_hub.plugins.dateien import DateienPlugin

TOKEN = "t0ken-" + "x" * 40

PROGRAMME = [
    {"id": "papers", "name": "Papers (PDF)", "endungen": [".pdf"]},
    {"id": "wordcraft", "name": "WordCraft", "endungen": [".docx", ".odt", ".rtf"]},
    {"id": "gridcraft", "name": "GridCraft", "endungen": [".xlsx", ".xlsm"]},
]


class Attrappe:
    """Spielt fyos-oeffnen nach und merkt sich, was ankam."""

    def __init__(self) -> None:
        self.anfragen: list[tuple[str, str, dict | None, str | None]] = []
        self.programme_status = 200
        self.oeffnen_status = 200
        self.oeffnen_antwort: dict = {"ok": True, "programm": "Papers (PDF)", "groesse": 602}
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
                if self.path == "/programme" and self._pruefen():
                    if attrappe.programme_status != 200:
                        return self._senden(attrappe.programme_status, {"ok": False, "error": "kaputt"})
                    self._senden(200, {"ok": True, "programme": PROGRAMME})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length", "0"))
                d = json.loads(self.rfile.read(n))
                attrappe.anfragen.append(("POST", self.path, d, self.headers.get("Authorization")))
                if self.path == "/oeffnen" and self._pruefen():
                    self._senden(attrappe.oeffnen_status, attrappe.oeffnen_antwort)

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
    for name in ("FYOS_DATEIEN", oeffnen.ENV_GEGENSTELLE, oeffnen.ENV_TOKEN):
        monkeypatch.delenv(name, raising=False)
    store.verzeichnis_anmelden(None)
    yield
    store.verzeichnis_anmelden(None)


@pytest.fixture
def gegenstelle():
    a = Attrappe()
    yield a
    a.ende()


def _plugin(tmp_path, konf: dict | None):
    ablage = tmp_path / "ablage"
    ablage.mkdir(exist_ok=True)
    (ablage / "Berichte").mkdir(exist_ok=True)
    (ablage / "Berichte" / "bericht.pdf").write_bytes(b"%PDF-1.4\n")
    (ablage / "Berichte" / "brief.docx").write_bytes(b"PK")
    (ablage / "Berichte" / "notiz.md").write_text("# n\n")
    (ablage / "Berichte" / "ordner.pdf").mkdir(exist_ok=True)
    config = {"verzeichnis": str(ablage)}
    if konf is not None:
        config["oeffnen"] = konf
    p = DateienPlugin(config)
    p.register()
    return p


@pytest.fixture
def plugin(tmp_path, gegenstelle, monkeypatch):
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    p = _plugin(tmp_path, {"gegenstelle": gegenstelle.url})
    yield p
    p.shutdown()


# ── Beschreibung ────────────────────────────────────────────────────────────────────────────────────


def test_werkzeuge_sind_beschrieben(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert "read" in tools["oeffnen_programme"].tags and "flaeche" in tools["oeffnen_programme"].tags
    assert "exec" in tools["oeffnen_mit"].tags and "flaeche" in tools["oeffnen_mit"].tags
    assert "bestaetigt" in tools["oeffnen_mit"].input_schema["properties"]
    assert tools["oeffnen_mit"].input_schema["required"] == ["pfad", "programm"]
    assert not (tools["oeffnen_mit"].meta or {}).get("ui")


# ── Nicht eingerichtet ──────────────────────────────────────────────────────────────────────────────


def test_ohne_gegenstelle_ist_es_ein_klarer_zustand(tmp_path):
    p = _plugin(tmp_path, None)
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht eingerichtet" and r["programme"] == [] and "gegenstelle" in r["hinweis"]
    m = p.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers", "bestaetigt": True})
    assert m["ok"] is False and m["zustand"] == "nicht eingerichtet"
    p.shutdown()


def test_ohne_token_ist_es_nicht_eingerichtet(tmp_path, gegenstelle):
    p = _plugin(tmp_path, {"gegenstelle": gegenstelle.url})
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht eingerichtet" and oeffnen.ENV_TOKEN in r["hinweis"]
    assert gegenstelle.anfragen == []
    p.shutdown()


def test_eigener_name_der_token_variable(tmp_path, gegenstelle, monkeypatch):
    monkeypatch.setenv("MEIN_TOKEN", TOKEN)
    p = _plugin(tmp_path, {"gegenstelle": gegenstelle.url, "token_env": "MEIN_TOKEN"})
    assert p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})["zustand"] == "ok"
    p.shutdown()


def test_gegenstelle_aus_der_umgebung(tmp_path, gegenstelle, monkeypatch):
    monkeypatch.setenv(oeffnen.ENV_GEGENSTELLE, gegenstelle.url)
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    p = _plugin(tmp_path, None)
    assert p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})["zustand"] == "ok"
    p.shutdown()


@pytest.mark.parametrize("url", ["ftp://rechner:18445", "rechner:18445", "http://user:pw@rechner:18445", "http://", "file:///etc"])
def test_ungueltige_adresse_wird_abgelehnt(tmp_path, monkeypatch, url):
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    p = _plugin(tmp_path, {"gegenstelle": url})
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht eingerichtet" and "Adresse" in r["hinweis"]
    assert "pw" not in json.dumps(r)
    p.shutdown()


# ── Programme ───────────────────────────────────────────────────────────────────────────────────────


def test_programme_nach_endung(plugin, gegenstelle):
    r = plugin.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "ok" and r["programme"] == [{"id": "papers", "name": "Papers (PDF)"}]
    assert "Papers" in r["satz"]
    r = plugin.call("oeffnen_programme", {"pfad": "Berichte/brief.docx"})
    assert [p["id"] for p in r["programme"]] == ["wordcraft"]
    r = plugin.call("oeffnen_programme", {"pfad": "Berichte/notiz.md"})
    assert r["programme"] == [] and "kein Programm" in r["satz"]


def test_programme_stehen_eine_minute_im_zwischenspeicher(plugin, gegenstelle):
    for _ in range(3):
        plugin.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert len([a for a in gegenstelle.anfragen if a[1] == "/programme"]) == 1


def test_programme_pruefen_die_datei_zuerst(plugin, gegenstelle):
    with pytest.raises(store.Fehler):
        plugin.call("oeffnen_programme", {"pfad": "gibt/es/nicht.pdf"})
    with pytest.raises(store.Fehler):
        plugin.call("oeffnen_programme", {"pfad": "../ausserhalb.pdf"})
    assert gegenstelle.anfragen == []


def test_gegenstelle_nicht_erreichbar(tmp_path, monkeypatch):
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    p = _plugin(tmp_path, {"gegenstelle": "http://127.0.0.1:1"})
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht erreichbar" and r["programme"] == [] and "nicht erreichbar" in r["hinweis"]
    p.shutdown()


def test_falsches_token_wird_gemeldet_ohne_es_zu_nennen(tmp_path, gegenstelle, monkeypatch):
    monkeypatch.setenv(oeffnen.ENV_TOKEN, "ein-anderes-token-" + "y" * 30)
    p = _plugin(tmp_path, {"gegenstelle": gegenstelle.url})
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht erreichbar" and "Token" in r["hinweis"] and "ein-anderes-token" not in json.dumps(r)
    p.shutdown()


# ── Öffnen mit ──────────────────────────────────────────────────────────────────────────────────────


def test_trockenlauf_zeigt_den_plan_und_oeffnet_nichts(plugin, gegenstelle):
    r = plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers", "__dry_run__": True})
    assert r["dry_run"] is True and "Papers" in r["would_execute"]
    assert r["args_preview"] == {"pfad": "Berichte/bericht.pdf", "programm": "papers"}
    assert gegenstelle.posts() == []


def test_echter_lauf_braucht_die_bestaetigung(plugin, gegenstelle):
    with pytest.raises(ValueError, match="bestaetigt"):
        plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers"})
    assert gegenstelle.posts() == []


def test_oeffnen_schickt_pfad_und_programm_mit_token(plugin, gegenstelle):
    r = plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers", "bestaetigt": True})
    assert r["ok"] is True and r["programm"] == "Papers (PDF)" and "bericht.pdf" in r["satz"]
    (_, weg, koerper, kopf), = gegenstelle.posts()
    assert weg == "/oeffnen" and koerper == {"pfad": "Berichte/bericht.pdf", "programm": "papers"}
    assert kopf == f"Bearer {TOKEN}"
    assert TOKEN not in json.dumps(r)


def test_falsches_programm_fuer_den_dateityp(plugin, gegenstelle):
    with pytest.raises(ValueError, match="öffnet"):
        plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "gridcraft", "bestaetigt": True})
    with pytest.raises(ValueError, match="öffnet"):
        plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "rm -rf", "__dry_run__": True})
    assert gegenstelle.posts() == []


def test_programm_ist_pflicht(plugin):
    for programm in (None, "", "  ", 5):
        with pytest.raises(ValueError, match="programm"):
            plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": programm, "bestaetigt": True})


def test_ordner_und_fehlende_dateien_werden_nicht_geoeffnet(plugin, gegenstelle):
    for pfad in ("Berichte/ordner.pdf", "Berichte/fehlt.pdf", "../x.pdf", "/etc/passwd"):
        with pytest.raises(store.Fehler):
            plugin.call("oeffnen_mit", {"pfad": pfad, "programm": "papers", "bestaetigt": True})
    assert gegenstelle.posts() == []


def test_fehler_der_gegenstelle_kommt_als_lesbarer_text(plugin, gegenstelle):
    gegenstelle.oeffnen_status = 500
    gegenstelle.oeffnen_antwort = {"ok": False, "error": "Start fehlgeschlagen: keine Hyprland-Sitzung"}
    r = plugin.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers", "bestaetigt": True})
    assert r["ok"] is False and r["zustand"] == "fehler" and "Hyprland" in r["error"]
    assert TOKEN not in json.dumps(r)


def test_ohne_gegenstelle_wird_nichts_gestartet_auch_im_trockenlauf(tmp_path):
    p = _plugin(tmp_path, None)
    r = p.call("oeffnen_mit", {"pfad": "Berichte/bericht.pdf", "programm": "papers", "__dry_run__": True})
    assert r["ok"] is False and r["zustand"] == "nicht eingerichtet"
    p.shutdown()


def test_umleitungen_werden_nicht_verfolgt(tmp_path, monkeypatch):
    """Eine Gegenstelle, die umleitet, bekommt das Token nur einmal; der Umleitung folgt der Hub nicht."""
    ziel = Attrappe()
    gesehen: list[str | None] = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):  # noqa: N802
            gesehen.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", ziel.url + "/programme")
            self.end_headers()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv(oeffnen.ENV_TOKEN, TOKEN)
    p = _plugin(tmp_path, {"gegenstelle": f"http://127.0.0.1:{srv.server_address[1]}"})
    r = p.call("oeffnen_programme", {"pfad": "Berichte/bericht.pdf"})
    assert r["zustand"] == "nicht erreichbar"
    assert gesehen == [f"Bearer {TOKEN}"] and ziel.anfragen == []
    srv.shutdown()
    srv.server_close()
    ziel.ende()
    p.shutdown()


def test_endung():
    assert oeffnen.endung("a/b/Bericht.PDF") == ".pdf"
    assert oeffnen.endung("a/.pdf") == ""
    assert oeffnen.endung("a/ohne") == ""
    assert oeffnen.endung("a.b/ohne") == ""
