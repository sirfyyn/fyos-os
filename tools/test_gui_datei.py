"""gui_datei.py: eine gebaute Ansicht als eigenständige HTML-Datei, aus dem Hub oder aus einer JSON-Datei."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import gui_datei as g

ID = "g-4a0a210a33a7"
BEISPIEL = {"titel": "Zahlen", "vorlage": "kennzahlen", "daten": {"kacheln": [{"titel": "Aufrufe", "wert": 7}]}}


class _Hub(BaseHTTPRequestHandler):
    """Ein Hub, der nur POST /hub/call kennt und merkt, was er bekommen hat."""

    gesehen: list[dict] = []
    antwort: dict = {}
    status = 200

    def do_POST(self):  # noqa: N802
        laenge = int(self.headers.get("Content-Length") or 0)
        _Hub.gesehen.append({"pfad": self.path, "typ": self.headers.get("Content-Type"), "koerper": json.loads(self.rfile.read(laenge))})
        roh = json.dumps(_Hub.antwort).encode("utf-8")
        self.send_response(_Hub.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def log_message(self, *_):
        pass


@pytest.fixture()
def hub(monkeypatch):
    _Hub.gesehen, _Hub.antwort, _Hub.status = [], {}, 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("FYOS_HUB_URL", f"http://127.0.0.1:{server.server_port}/mcp")   # wie in FYOS: die MCP-Adresse
    yield _Hub
    server.shutdown()
    server.server_close()


def test_hub_adresse():
    assert g.hub_adresse(None) == "http://localhost:8080"
    assert g.hub_adresse("") == "http://localhost:8080"
    assert g.hub_adresse("http://hub:8080/mcp") == "http://hub:8080"
    assert g.hub_adresse("http://hub:8080/mcp/") == "http://hub:8080"
    assert g.hub_adresse("https://fyos.example/") == "https://fyos.example"
    assert g.hub_adresse("https://fyos.example/hub/mcp") == "https://fyos.example/hub"
    assert g.hub_adresse("http://mcp") == "http://mcp"
    assert g.hub_adresse("http://nutzer:xx@hub:8080/mcp") == "http://hub:8080"   # Zugangsdaten gehören nicht in die Adresse
    for fremd in ("javascript:alert(1)", "file:///etc/hosts", "ftp://hub.example", "hub:8080", "http://[::1"):
        assert g.hub_adresse(fremd) == "http://localhost:8080", fremd


def test_datei_wird_zur_ansicht(tmp_path, capsys):
    quelle = tmp_path / "ansicht.json"
    quelle.write_text(json.dumps(BEISPIEL), encoding="utf-8")
    ziel = tmp_path / "aus.html"
    assert g.main([str(quelle), str(ziel)]) == 0
    assert capsys.readouterr().out.strip() == str(ziel.resolve())
    seite = ziel.read_text(encoding="utf-8")
    assert seite.startswith("<!doctype html>") and "<title>Zahlen</title>" in seite
    # Dieselbe Sandbox wie in der Shell, und die Daten der Vorlage stecken in der Datei
    assert 'sandbox="allow-scripts"' in seite and "Aufrufe" in seite


def test_ohne_ziel_heisst_die_datei_nach_der_id(tmp_path, monkeypatch, capsys):
    quelle = tmp_path / "ansicht.json"
    quelle.write_text(json.dumps({"titel": "T", "html": "<p>x</p>"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert g.main([str(quelle)]) == 0
    name = Path(capsys.readouterr().out.strip()).name
    assert re.fullmatch(r"gui-g-[0-9a-f]{12}\.html", name) and (tmp_path / name).is_file()


def test_ansicht_kommt_aus_dem_hub(hub, tmp_path, capsys):
    doc = g.GuiPlugin().dokument(BEISPIEL, live=False)
    hub.antwort = {"ok": True, "result": {"id": ID, "dokument": doc, "hinweis": "Nicht aktualisiert: Quelle weg"}}
    ziel = tmp_path / "hub.html"
    assert g.main([ID, str(ziel)]) == 0
    assert hub.gesehen == [{"pfad": "/hub/call", "typ": "application/json",
                            "koerper": {"tool": "gui.zeigen", "arguments": {"id": ID}}}]
    assert "<title>Zahlen</title>" in ziel.read_text(encoding="utf-8")
    assert "Nicht aktualisiert" in capsys.readouterr().err   # der Hinweis des Hubs geht nicht verloren


def test_fehler_des_hubs_sind_eine_meldung_kein_stapel(hub, tmp_path, capsys):
    hub.antwort, hub.status = {"ok": False, "kind": "bad_request", "error": f"Ansicht {ID} gibt es nicht (mehr)"}, 400
    assert g.main([ID, str(tmp_path / "x.html")]) == 1
    assert "gibt es nicht" in capsys.readouterr().err and not (tmp_path / "x.html").exists()
    hub.antwort, hub.status = {"ok": True, "result": {"id": ID}}, 200
    assert g.main([ID, str(tmp_path / "x.html")]) == 1
    assert "kein Dokument" in capsys.readouterr().err


def test_hub_nicht_erreichbar(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FYOS_HUB_URL", "http://127.0.0.1:1/mcp")   # dort lauscht niemand
    assert g.main([ID, str(tmp_path / "x.html")]) == 1
    assert "nicht erreichbar" in capsys.readouterr().err


def test_aufruf_ohne_oder_mit_falschen_argumenten(capsys):
    assert g.main([]) == 2 and "gui_datei.py" in capsys.readouterr().out
    assert g.main(["-h"]) == 0
    assert g.main(["a", "b", "c"]) == 2
    capsys.readouterr()
    assert g.main(["gibt-es-nicht.json"]) == 2
    assert "weder eine Ansicht-Id" in capsys.readouterr().err


def test_kaputte_dateien_sind_eine_meldung(tmp_path, capsys):
    kaputt = tmp_path / "kaputt.json"
    kaputt.write_text("{nicht json", encoding="utf-8")
    assert g.main([str(kaputt)]) == 1
    liste = tmp_path / "liste.json"
    liste.write_text("[1]", encoding="utf-8")
    assert g.main([str(liste)]) == 1 and "JSON-Objekt" in capsys.readouterr().err
    ohne_titel = tmp_path / "ohne.json"
    ohne_titel.write_text(json.dumps({"html": "<p/>"}), encoding="utf-8")
    assert g.main([str(ohne_titel)]) == 1 and "titel" in capsys.readouterr().err


def test_oeffnen_nimmt_den_standardbrowser(tmp_path, monkeypatch):
    geoeffnet = []
    monkeypatch.setattr(g.webbrowser, "open", lambda url: geoeffnet.append(url) or True)
    quelle = tmp_path / "ansicht.json"
    quelle.write_text(json.dumps({"titel": "T", "html": "<p/>"}), encoding="utf-8")
    ziel = tmp_path / "o.html"
    assert g.main(["--oeffnen", str(quelle), str(ziel)]) == 0
    assert geoeffnet == [ziel.resolve().as_uri()]
