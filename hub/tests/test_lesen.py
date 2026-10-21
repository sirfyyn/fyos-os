"""lesen.artikel: Adresse prüfen (SSRF), Haupttext herausziehen, Abruf über die geprüfte IP, Zwischenspeicher."""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from mcp_hub.plugins import lesen
from mcp_hub.plugins.lesen import (
    Abgewiesen,
    LesenPlugin,
    adresse_oeffentlich,
    aufloesen,
    herausziehen,
    holen,
    url_pruefen,
)


def _aufloeser(tabelle: dict[str, list[str]]):
    def f(host, port, type=None):  # Signatur wie socket.getaddrinfo
        if host not in tabelle:
            raise socket.gaierror("unbekannt")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in tabelle[host]]
    return f


@pytest.mark.parametrize("url", [
    "http://example.org/a", "ftp://example.org/a", "https://user:pw@example.org/a", "https://localhost/a",
    "https://drucker.local/a", "https://example.org:8443/a", "https://rechner.lan/x", "", None, "https://" + "a" * 2100,
])
def test_url_abgewiesen(url):
    with pytest.raises(Abgewiesen):
        url_pruefen(url)


def test_url_gut():
    assert url_pruefen(" https://www.example.org/artikel?id=1 ") == ("https://www.example.org/artikel?id=1", "www.example.org")
    assert url_pruefen("https://example.org:443/a")[1] == "example.org"


@pytest.mark.parametrize("ip,ok", [
    ("93.184.216.34", True), ("2606:4700::1111", True),
    ("10.0.0.1", False), ("192.168.1.10", False), ("172.16.5.5", False), ("127.0.0.1", False), ("169.254.169.254", False),  # sauber: ok (Prüfwerte)
    ("100.64.0.1", False), ("0.0.0.0", False), ("::1", False), ("fd00::1", False), ("fe80::1", False),  # sauber: ok (Prüfwerte)
    ("::ffff:10.0.0.1", False), ("224.0.0.1", False), ("kein-ip", False),  # sauber: ok (Prüfwerte)
])
def test_adresse_oeffentlich(ip, ok):
    assert adresse_oeffentlich(ip) is ok


def test_aufloesen_verlangt_nur_oeffentliche_adressen():
    f = _aufloeser({"gut.example": ["93.184.216.34"], "gemischt.example": ["93.184.216.34", "10.0.0.5"], "intern.example": ["192.168.0.2"]})  # sauber: ok (Prüfwerte)
    assert aufloesen("gut.example", f) == "93.184.216.34"
    for host in ("gemischt.example", "intern.example", "fehlt.example"):
        with pytest.raises(Abgewiesen):
            aufloesen(host, f)


SEITE = """<!doctype html><html><head><title>Titel im Tab | Zeitung</title>
<meta property="og:title" content="Neue Batterien halten doppelt so lange">
<meta property="og:site_name" content="Beispielzeitung">
<meta property="article:published_time" content="2026-10-20T08:00:00+02:00">
<script>var x = "<p>kein Text</p>";</script><style>p{color:red}</style></head>
<body><nav><p>Startseite Politik Wirtschaft Wissen Sport Kultur Reisen Auto Digital Karriere</p></nav>
<header><h1>Neue Batterien</h1></header>
<div class="layout"><article><div class="body">
<p>Forschende haben eine Zelle vorgestellt, die nach tausend Ladezyklen noch neunzig Prozent hält.
<p>Statt Graphit nutzt die Anode eine dünne Siliziumschicht, die beim Laden weniger aufquillt &amp; reißt.</p>
<div class="share-box"><p>Teilen Sie diesen Artikel mit Ihren Freunden auf allen Kanälen, jetzt sofort.</p></div>
<h2>Was anders ist</h2>
<p>Die Schicht ist nur wenige Nanometer dick und wird bei Raumtemperatur aufgebracht, was Kosten spart.</p>
<ul><li>Mehr Zyklen bei gleicher Größe</li><li>Weniger Wärme beim Schnellladen</li></ul>
<figure><img src="x.jpg"><figcaption>Bildunterschrift, die nicht in den Text gehört, auch wenn sie lang ist.</figcaption></figure>
<p>Kurz.</p>
</div></article>
<aside><p>Lesen Sie auch: Zehn Tipps für längere Akkulaufzeit im Winter und andere Dinge.</p></aside></div>
<footer><p>Impressum Datenschutz Kontakt Abo kündigen Werbung Jobs Presse Newsletter</p></footer></body></html>"""


def test_herausziehen_nimmt_nur_den_haupttext():
    a = herausziehen(SEITE, "https://www.beispiel.example/batterie")
    assert a["titel"] == "Neue Batterien halten doppelt so lange"
    assert a["quelle"] == "Beispielzeitung"
    assert a["datum"].startswith("2026-10-20")
    texte = [x["text"] for x in a["absaetze"]]
    assert texte[0].startswith("Forschende haben")
    assert "reißt." in texte[1] and "&amp;" not in texte[1]
    assert {"art": "h", "text": "Was anders ist"} in a["absaetze"]
    assert {"art": "li", "text": "Mehr Zyklen bei gleicher Größe"} in a["absaetze"]
    alles = " ".join(texte)
    for weg in ("Startseite", "Teilen Sie", "Bildunterschrift", "Lesen Sie auch", "Impressum", "kein Text", "Kurz."):
        assert weg not in alles
    assert a["woerter"] > 30 and a["lesezeit"] == 1


def test_herausziehen_ohne_text_und_kaputtes_html():
    a = herausziehen("<html><head><title>Nur JS</title></head><body><div id=app></div><script>x()</script>", "https://a.example/")
    assert a["titel"] == "Nur JS" and a["absaetze"] == []
    b = herausziehen("<p>" + "Ein langer Satz ohne Ende " * 5 + "<div><p>noch einer, der auch lang genug ist für einen Absatz.", "https://b.example/")
    assert len(b["absaetze"]) == 2


def _transport(antworten: dict[str, httpx.Response], gesehen: list):
    def handler(req: httpx.Request) -> httpx.Response:
        gesehen.append((str(req.url), req.headers.get("host"), req.extensions.get("sni_hostname")))
        return antworten[str(req.url)]
    return httpx.MockTransport(handler)


def test_holen_verbindet_mit_der_geprueften_ip_und_folgt_weiterleitungen():
    f = _aufloeser({"a.example": ["93.184.216.34"], "b.example": ["2606:4700::1111"]})
    gesehen: list = []
    t = _transport({
        "https://93.184.216.34/x": httpx.Response(301, headers={"location": "https://b.example/y"}),
        "https://[2606:4700::1111]/y": httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text="<p>hallo</p>"),
    }, gesehen)
    url, html = holen("https://a.example/x", f, t)
    assert url == "https://b.example/y" and html == "<p>hallo</p>"
    assert gesehen[0][1:] == ("a.example", "a.example")
    assert gesehen[1][1:] == ("b.example", "b.example")


def test_holen_weist_weiterleitung_ins_eigene_netz_ab():
    f = _aufloeser({"a.example": ["93.184.216.34"], "intern.example": ["10.1.2.3"]})  # sauber: ok (Prüfwert)
    gesehen: list = []
    t = _transport({"https://93.184.216.34/x": httpx.Response(302, headers={"location": "https://intern.example/geheim"})}, gesehen)
    with pytest.raises(Abgewiesen):
        holen("https://a.example/x", f, t)
    t2 = _transport({"https://93.184.216.34/x": httpx.Response(302, headers={"location": "http://a.example/x"})}, [])
    with pytest.raises(Abgewiesen):
        holen("https://a.example/x", f, t2)
    assert len(gesehen) == 1


def test_holen_nur_html_und_begrenzt(monkeypatch):
    f = _aufloeser({"a.example": ["93.184.216.34"]})
    t = _transport({"https://93.184.216.34/x": httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")}, [])
    with pytest.raises(ValueError, match="kein HTML"):
        holen("https://a.example/x", f, t)
    monkeypatch.setattr(lesen, "GROESSE_MAX", 10)
    t2 = _transport({"https://93.184.216.34/x": httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 50)}, [])
    with pytest.raises(ValueError, match="zu groß"):
        holen("https://a.example/x", f, t2)
    t3 = _transport({"https://93.184.216.34/x": httpx.Response(404, headers={"content-type": "text/html"})}, [])
    with pytest.raises(ValueError, match="404"):
        holen("https://a.example/x", f, t3)


def test_google_news_link_wird_zur_originaladresse_aufgeloest():
    f = _aufloeser({"news.google.com": ["142.250.1.1"], "ziel.example": ["93.184.216.34"]})
    kennung = "CBMiQWh0dHBzOi8vemllbC5leGFtcGxlL2E"
    antwort_be = ')]}\'\n\n' + json.dumps([["wrb.fr", "Fbv4je", json.dumps(["garturlres", "https://ziel.example/a", 1]), None]])
    gesehen: list = []

    def handler(req: httpx.Request) -> httpx.Response:
        gesehen.append((req.method, str(req.url)))
        if req.method == "GET" and req.url.path == f"/rss/articles/{kennung}":
            return httpx.Response(200, headers={"content-type": "text/html"}, text='<c-wiz><div data-n-a-sg="SIG" data-n-a-ts="1792476000"></div></c-wiz>')
        if req.method == "POST":
            assert b"SIG" in req.content and b"1792476000" in req.content
            return httpx.Response(200, headers={"content-type": "application/json"}, text=antwort_be)
        if str(req.url) == "https://93.184.216.34/a":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Original</p>")
        return httpx.Response(404)

    url, html = holen(f"https://news.google.com/rss/articles/{kennung}?oc=5", f, httpx.MockTransport(handler))
    assert url == "https://ziel.example/a" and html == "<p>Original</p>"
    assert [m for m, _ in gesehen] == ["GET", "POST", "GET"]


def test_google_news_ohne_signatur_bleibt_beim_link():
    f = _aufloeser({"news.google.com": ["142.250.1.1"]})
    t = httpx.MockTransport(lambda req: httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Google News</p>"))
    url, html = holen("https://news.google.com/rss/articles/CBMiQWh0dHBzOi8vemllbC5leGFtcGxlL2E", f, t)
    assert url.startswith("https://news.google.com/") and "Google News" in html


class _Ablage:
    def __init__(self):
        self.d: dict[str, str] = {}

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v, ex=None):
        self.d[k] = v
        return True


def test_plugin_artikel_speichert_zwischen():
    p = LesenPlugin()
    p._r = _Ablage()
    aufrufe = []

    def holen_attrappe(url):
        aufrufe.append(url)
        return url, SEITE

    p._holen = holen_attrappe
    a = p.call("artikel", {"url": "https://www.beispiel.example/batterie"})
    assert a["titel"].startswith("Neue Batterien") and "Wörter" in a["satz"]
    b = p.call("artikel", {"url": "https://www.beispiel.example/batterie"})
    assert b == a and len(aufrufe) == 1
    p.call("artikel", {"url": "https://www.beispiel.example/batterie", "frisch": True})
    assert len(aufrufe) == 2
    with pytest.raises(Abgewiesen):
        p.call("artikel", {"url": "http://www.beispiel.example/batterie"})


def test_plugin_hinweis_ohne_text():
    p = LesenPlugin()
    p._r = _Ablage()
    p._holen = lambda url: (url, "<html><title>Abo</title><body><div class=paywall><p>" + "Nur für Abonnenten lesbar. " * 4 + "</p></div>")
    a = p.call("artikel", {"url": "https://zeitung.example/x"})
    assert a["absaetze"] == [] and "Bezahlschranke" in a["hinweis"]


def test_werkzeug_ist_lesend():
    (t,) = LesenPlugin().describe_tools()
    assert t.name == "artikel" and "read" in t.tags and t.input_schema["required"] == ["url"]
