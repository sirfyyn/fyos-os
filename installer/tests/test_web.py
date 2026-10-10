import http.client
import json
import threading

import pytest

from fyos_installer import ausfuehren as ausf
from fyos_installer import web


@pytest.fixture
def server(katalog, tmp_path):
    z = web.Zustand(katalog, token="tok123", verzeichnis=tmp_path / "ziel", docker=lambda: (True, "bereit"), umgebung={})
    s = web.Server(z)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()


def anfrage(server, methode, pfad, daten=None, token="tok123", host=None, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", server.zustand.port, timeout=10)
    h = {}
    if token:
        h["X-Fyos-Token"] = token
    if host:
        h["Host"] = host
    if cookie:
        h["Cookie"] = cookie
    body = None
    if daten is not None:
        body = json.dumps(daten)
        h["Content-Type"] = "application/json"
    c.request(methode, pfad, body, h)
    r = c.getresponse()
    return r, r.read()


def test_token_verlangt(server):
    for pfad in ("/", "/api/katalog", "/static/app.js", "/bild/kern/0"):
        assert anfrage(server, "GET", pfad, token=None)[0].status == 403
    assert anfrage(server, "GET", "/api/katalog", token="falsch")[0].status == 403
    assert anfrage(server, "POST", "/api/plan", {"auswahl": []}, token=None)[0].status == 403
    assert anfrage(server, "GET", "/api/katalog", host="boese.example.com")[0].status == 403


def test_link_setzt_cookie(server):
    r, _ = anfrage(server, "GET", "/?t=tok123", token=None)
    assert r.status == 302 and "HttpOnly" in r.getheader("Set-Cookie")
    cookie = r.getheader("Set-Cookie").split(";")[0]
    r, body = anfrage(server, "GET", "/", token=None, cookie=cookie)
    assert r.status == 200 and b"FYOS" in body and "script-src 'self'" in r.getheader("Content-Security-Policy")


def test_katalog_bild_statisch(server):
    r, body = anfrage(server, "GET", "/api/katalog")
    k = json.loads(body)
    assert r.status == 200 and {b["id"] for b in k["bausteine"]} >= {"kern", "finanzen"} and k["docker"]["bereit"]
    assert k["bausteine"][0]["bilder"] == ["/bild/kern/0", "/bild/kern/1"]
    r, body = anfrage(server, "GET", "/bild/kern/0")
    assert r.status == 200 and r.getheader("Content-Type") == "image/svg+xml" and b"<svg" in body
    assert anfrage(server, "GET", "/bild/kern/9")[0].status == 404
    assert anfrage(server, "GET", "/static/app.js")[0].status == 200
    r, body = anfrage(server, "GET", "/favicon.ico")
    assert r.status == 200 and r.getheader("Content-Type") == "image/svg+xml" and b"<svg" in body
    assert anfrage(server, "GET", "/static/favicon.svg")[0].status == 200
    felder = [f for b in k["bausteine"] for f in b["konfiguration"]]
    assert felder and all(f["titel"] and f["titel"] != f["name"] for f in felder)
    assert k["vorgaben"]["optionen"]["bezug"] == "index" and k["vorgaben"]["optionen"]["bild_web"]
    assert b'rel="icon"' in anfrage(server, "GET", "/")[1]
    assert anfrage(server, "GET", "/static/../katalog.py")[0].status == 404


def test_plan(server):
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": ["kern"], "ziel": "dateien"})
    plan = json.loads(body)
    assert r.status == 200 and plan["ok"] and any(d["pfad"] == ".env" for d in plan["dateien"])
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": ["finanzen"], "ziel": "compose"})
    assert not json.loads(body)["ok"]
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": "kern"})
    assert not json.loads(body)["ok"]


def test_plan_traegt_den_reifegrad(server):
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": ["beispiel_app"], "ziel": "compose"})
    plan = json.loads(body)
    assert r.status == 200 and plan["ok"]
    assert [x["schicht"] for x in plan["reife"]] == ["gedaechtnis", "agent", "takte", "oberflaeche"]
    assert {x["schicht"]: x["stufe"] for x in plan["reife"]} == {"gedaechtnis": 1, "agent": 2, "takte": 1, "oberflaeche": 2}
    assert all(x["von"] == 3 and x["titel"] and x["name"] and x["erkennbar"] for x in plan["reife"])
    assert [bool(x["naechste"]) for x in plan["reife"]] == [True, True, True, True]  # keine Schicht ist oben angekommen
    assert any(h.startswith("Abnahme: ") for h in plan["hinweise"])
    # auch ein Plan mit Fehlern nennt den Reifegrad (der Assistent zeigt ihn erst bei einem guten Plan)
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": ["finanzen"], "ziel": "compose"})
    assert json.loads(body)["reife"]
    r, body = anfrage(server, "POST", "/api/plan", {"auswahl": "kern"})
    assert json.loads(body)["reife"] == []


def _protokoll(server):
    c = http.client.HTTPConnection("127.0.0.1", server.zustand.port, timeout=15)
    c.request("GET", "/api/protokoll", headers={"X-Fyos-Token": "tok123"})
    r = c.getresponse()
    text = ""
    while "event: ende" not in text:
        zeile = r.fp.readline().decode()
        assert zeile, text
        text += zeile
    text += r.fp.readline().decode()
    return text


def _ende(text):
    """Die Daten des Ereignisses `ende` aus dem Protokoll."""
    zeilen = text.splitlines()
    return json.loads(zeilen[zeilen.index("event: ende") + 1].removeprefix("data: "))


def test_installieren_dateien(server, tmp_path):
    r, _ = anfrage(server, "POST", "/api/installieren", {"auswahl": ["kern"], "ziel": "dateien", "verzeichnis": str(tmp_path / "ziel")})
    assert r.status == 202
    text = _protokoll(server)
    assert "geschrieben:" in text and '"ok": true' in text
    assert (tmp_path / "ziel" / "docker-compose.yml").is_file()
    assert _ende(text)["abnahme"] is None  # nichts gestartet, nichts abzunehmen


def test_installieren_compose_gemockt(server, tmp_path, monkeypatch):
    monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log, **k: (log("gebaut"), ausf.Ergebnis(True, "FYOS läuft", plan.url))[1])
    anfrage(server, "POST", "/api/installieren", {"auswahl": [], "ziel": "compose", "verzeichnis": str(tmp_path / "c")})
    text = _protokoll(server)
    assert "gebaut" in text and "http://localhost:8080" in text
    assert _ende(text)["abnahme"] is None  # die Abnahme lief nicht (hier gemockt): kein Befund, kein Fehler


@pytest.mark.parametrize("bestanden", [True, False])
def test_installieren_compose_meldet_die_abnahme(server, tmp_path, monkeypatch, abnahme_von, bestanden):
    ab = abnahme_von(bestanden)
    monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log, **k: ausf.Ergebnis(True, "FYOS läuft", plan.url, ab))
    anfrage(server, "POST", "/api/installieren", {"auswahl": [], "ziel": "compose", "verzeichnis": str(tmp_path / "c")})
    ende = _ende(_protokoll(server))
    assert ende["ok"] is True and ende["url"] == "http://localhost:8080"  # FYOS läuft in beiden Fällen
    assert ende["abnahme"] == ab.als_dict() and ende["abnahme"]["bestanden"] is bestanden
    assert [b["id"] for b in ende["abnahme"]["befunde"]] == ["gegenprobe", "aufruf_endpunkt", "fremde_herkunft", "kein_flaechenwerkzeug"]
    assert [b["ok"] for b in ende["abnahme"]["befunde"]] == ([True] * 4 if bestanden else [True, False, True, True])


class _Popen:
    """Ein `docker`, das alles gelingen lässt."""

    stdout = ["zeile\n"]

    def __call__(self, argv, **k):
        return self

    def wait(self):
        return 0


def test_installieren_die_abnahme_laeuft_mit_der_echten_ausfuehrung(server, tmp_path, monkeypatch, abnahme_von):
    """Der Assistent reicht weiter, was `ausfuehren` aus der Abnahme macht: Protokollzeilen, Meldung und Befunde."""
    echte = ausf.ausfuehren
    ab = abnahme_von(False)
    monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log: echte(
        plan, log, docker=lambda: (True, "bereit"), popen=_Popen(), pruefer=lambda: {"web": True, "hub": True},
        schlaf=lambda s: None, abnahme=lambda adresse: ab,
    ))
    anfrage(server, "POST", "/api/installieren", {"auswahl": [], "ziel": "compose", "verzeichnis": str(tmp_path / "c")})
    text = _protokoll(server)
    ende = _ende(text)
    assert ende["ok"] is True and ende["abnahme"]["bestanden"] is False
    assert "Abnahme NICHT bestanden: 2 von 3 verbotenen Anfragen wurden abgelehnt." in ende["meldung"]
    assert "== Abnahme: verbotene Anfragen" in text  # die Zeilen der Abnahme stehen im Protokoll des Assistenten


def test_installieren_fehlerhafter_plan(server):
    r, body = anfrage(server, "POST", "/api/installieren", {"auswahl": ["finanzen"], "ziel": "compose"})
    assert r.status == 422 and json.loads(body)["fehler"]
