"""lesen — einen Artikel in FYOS lesen, ohne die Seite zu verlassen (20.10.2026).

Wunsch: eine Nachricht in einem Fenster im Vordergrund lesen, als generative Oberfläche, ohne FYOS zu verlassen.

    lesen.artikel {url}   lädt die Seite, zieht Titel, Quelle, Datum und die Absätze des Haupttexts heraus und gibt sie
                          als Daten zurück — Form der gui-Vorlage „artikel“. Die Zentrale öffnet damit ein Fenster:
                          gui.bauen {vorlage: "artikel", quelle: {werkzeug: "lesen.artikel", argumente: {url}}}.

Herausziehen ohne Zusatzbibliothek (html.parser): Skripte, Stile, Navigation, Kopf- und Fußzeilen, Formulare und
Seitenleisten fallen weg. Gewertet wird jedes Element nach der Textmenge der Absätze darunter (Eltern voll, Großeltern
halb, wie bei Readability); das beste Element, oder das textreichste <article>, liefert die Blöcke (Absätze,
Zwischenüberschriften, Aufzählungen, Zitate). Bilder und Skripte der Seite kommen nie mit.

Schutz gegen Abrufe ins eigene Netz (SSRF): nur https auf Port 443, keine Zugangsdaten in der Adresse. Der Name wird
aufgelöst; ist auch nur eine Adresse nicht öffentlich (privat, lokal, Link-Local, Multicast, reserviert, CGNAT), wird
abgewiesen. Verbunden wird mit genau der geprüften Adresse (SNI und Host bleiben der Name, das Zertifikat wird gegen den
Namen geprüft), so hilft auch ein Umbiegen des DNS zwischen Prüfen und Verbinden nicht. Weiterleitungen (höchstens 4)
laufen durch dieselbe Prüfung. Höchstens 3 MB, 10 s, nur text/html.

Links aus dem Google-News-Feed (viele Karten kommen von dort) werden zur Originaladresse aufgelöst
(`google_news_aufloesen`). Reddit sperrt Abrufe ohne Anmeldung (403); dann bietet die Zentrale den Browser an.

Ablage über `mcp_hub.kv`: `fyos:lesen:<sha1 der Adresse>` (6 Stunden), damit das Fenster beim Nachladen nicht jedes
Mal die Seite holt.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx

from .. import kv
from ..plugin import HubPlugin, ToolDescriptor

logger = logging.getLogger(__name__)

SCHLUESSEL = "fyos:lesen:"
ABLAGE_TTL_S = 6 * 3600
URL_MAX = 2000
GROESSE_MAX = 3 * 1024 * 1024
FRIST_S = 10.0
WEITERLEITUNGEN_MAX = 4
BLOECKE_MAX = 300
ZEICHEN_MAX = 80_000
ABSATZ_MIN = 40  # kürzere Absätze sind meist Bildunterschriften, Teilen-Knöpfe, Werbung
WOERTER_JE_MINUTE = 220
WOERTER_WENIG = 80  # darunter ist es meist ein Anreißer vor der Bezahlschranke oder ein App-Hinweis
KENNUNG = "FYOS-Lesen/1.0"

_WEG = {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form", "button",
        "select", "iframe", "figure", "figcaption", "dialog", "menu"}
_LEER = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOECKE = {"p": "p", "h2": "h", "h3": "h", "h4": "h", "li": "li", "blockquote": "zitat", "pre": "p"}
_NEBEN = re.compile(r"(^|[\s_-])(comment|kommentar|share|teilen|social|related|verwandt|newsletter|promo|werbung|anzeige|"
                    r"advert|cookie|consent|footer|sidebar|breadcrumb|paywall|teaser-list|navigation)([\s_-]|$)", re.IGNORECASE)
_LEERRAUM = re.compile(r"\s+")


class Abgewiesen(ValueError):
    """Die Adresse darf nicht geholt werden (Schema, Port, nicht öffentliche Adresse)."""


# ── Adresse prüfen ─────────────────────────────────────────────────────────

def adresse_oeffentlich(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return bool(a.is_global) and not (a.is_multicast or a.is_reserved or a.is_loopback or a.is_link_local or a.is_private)


def url_pruefen(url: Any) -> tuple[str, str]:
    """→ (saubere Adresse, Rechnername). Nur https, Port 443, ohne Zugangsdaten."""
    if not isinstance(url, str) or not url.strip() or len(url) > URL_MAX:
        raise Abgewiesen("url: https-Adresse eines Artikels (höchstens 2000 Zeichen)")
    url = url.strip()
    teile = urlsplit(url)
    if teile.scheme.lower() != "https":
        raise Abgewiesen("url: nur https-Adressen")
    if teile.username or teile.password:
        raise Abgewiesen("url: keine Zugangsdaten in der Adresse")
    host = (teile.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise Abgewiesen("url: kein öffentlicher Rechner")
    try:
        port = teile.port
    except ValueError:
        raise Abgewiesen("url: Port ist ungültig") from None
    if port not in (None, 443):
        raise Abgewiesen("url: nur Port 443")
    return url, host


def aufloesen(host: str, aufloeser: Callable[..., Any] = socket.getaddrinfo) -> str:
    """Erste Adresse des Namens — nur, wenn ALLE seine Adressen öffentlich sind."""
    try:
        eintraege = aufloeser(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise Abgewiesen(f"{host} lässt sich nicht auflösen") from None
    ips = [e[4][0] for e in eintraege]
    if not ips:
        raise Abgewiesen(f"{host} lässt sich nicht auflösen")
    if not all(adresse_oeffentlich(ip) for ip in ips):
        raise Abgewiesen(f"{host} zeigt auf eine nicht öffentliche Adresse")
    return ips[0]


# ── Holen ──────────────────────────────────────────────────────────────────

def _abruf(c: httpx.Client, url: str, aufloeser: Callable[..., Any], daten: str | None = None, html: bool = True) -> tuple[str, str]:
    """Eine Anfrage (GET, mit `daten` POST als Formular) → (endgültige Adresse, Text). Jede Station, auch nach einer
    Weiterleitung, wird geprüft und über genau die geprüfte IP verbunden."""
    for _ in range(WEITERLEITUNGEN_MAX + 1):
        url, host = url_pruefen(url)
        ip = aufloesen(host, aufloeser)
        ziel = urlsplit(url)._replace(netloc=f"[{ip}]" if ":" in ip else ip).geturl()
        kopf = {"Host": host, "User-Agent": KENNUNG, "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
                "Accept-Language": "de,en;q=0.8"}
        if daten is not None:
            kopf["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8"
        with c.stream("POST" if daten is not None else "GET", ziel, headers=kopf, content=daten,
                      extensions={"sni_hostname": host}) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url, daten = urljoin(url, r.headers["location"]), None
                continue
            if r.status_code != 200:
                raise ValueError(f"Die Seite antwortet mit {r.status_code}")
            if html and "html" not in r.headers.get("content-type", "").lower():
                raise ValueError("Die Adresse ist keine Webseite (kein HTML)")
            roh = bytearray()
            for stueck in r.iter_bytes():
                roh += stueck
                if len(roh) > GROESSE_MAX:
                    raise ValueError("Die Seite ist zu groß (über 3 MB)")
            return url, roh.decode(r.encoding or "utf-8", errors="replace")
    raise ValueError("Zu viele Weiterleitungen")


_GN_ARTIKEL = re.compile(r"^/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]{20,})")
_GN_SIGNATUR = re.compile(r'data-n-a-sg="([^"]+)"')
_GN_ZEIT = re.compile(r'data-n-a-ts="(\d+)"')


def google_news_aufloesen(c: httpx.Client, url: str, aufloeser: Callable[..., Any]) -> str | None:
    """Links aus dem Google-News-Feed führen auf eine Zwischenseite, die erst per Skript weiterleitet. Die Zwischenseite
    trägt Signatur und Zeitstempel; damit nennt Googles Endpunkt `batchexecute` die Originaladresse. None = nicht
    auflösbar (dann zeigt das Fenster den Hinweis)."""
    teile = urlsplit(url)
    m = _GN_ARTIKEL.match(teile.path)
    if (teile.hostname or "").lower() != "news.google.com" or not m:
        return None
    kennung = m.group(1)
    _, seite = _abruf(c, f"https://news.google.com/rss/articles/{kennung}", aufloeser)
    sg, ts = _GN_SIGNATUR.search(seite), _GN_ZEIT.search(seite)
    if not sg or not ts:
        return None
    anfrage = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,'
               f'[1,1,1],1,1,null,0,0,null,0],"{kennung}",{ts.group(1)},"{sg.group(1)}"]')
    daten = "f.req=" + quote(json.dumps([[["Fbv4je", anfrage]]]))
    _, antwort = _abruf(c, "https://news.google.com/_/DotsSplashUi/data/batchexecute", aufloeser, daten=daten, html=False)
    try:
        teil = json.loads(antwort.split("\n\n", 1)[1])
        ziel = json.loads(teil[0][2])[1]
    except (IndexError, ValueError, TypeError, KeyError):
        return None
    return ziel if isinstance(ziel, str) and ziel.startswith("https://") else None


def holen(url: str, aufloeser: Callable[..., Any] = socket.getaddrinfo, transport: Any = None) -> tuple[str, str]:
    """→ (endgültige Adresse, HTML)."""
    with httpx.Client(timeout=FRIST_S, follow_redirects=False, transport=transport) as c:
        if (urlsplit(url).hostname or "").lower() == "news.google.com":
            try:
                url = google_news_aufloesen(c, url, aufloeser) or url
            except (ValueError, httpx.HTTPError) as e:
                logger.info("lesen: Google-News-Link nicht aufgelöst: %s", type(e).__name__)
        return _abruf(c, url, aufloeser)


# ── Herausziehen ───────────────────────────────────────────────────────────

class _Leser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stapel: list[tuple[str, int, bool]] = []  # (tag, element-nr, weg)
        self.zaehler = 0
        self.eltern: dict[int, int | None] = {}
        self.artikel: set[int] = set()
        self.bloecke: list[dict[str, Any]] = []  # {art, text, kette}
        self.meta: dict[str, str] = {}
        self.titel_tag = ""
        self._im_titel = False
        self._block: dict[str, Any] | None = None
        self._zeit = ""

    def _weg(self) -> bool:
        return any(w for _, _, w in self.stapel)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            schluessel = (a.get("property") or a.get("name") or "").lower()
            if schluessel in ("og:title", "og:site_name", "article:published_time", "description", "og:description",
                              "author", "article:author", "twitter:title", "date", "dc.date"):
                self.meta.setdefault(schluessel, a.get("content", "").strip())
            return
        if tag == "time" and a.get("datetime") and not self._zeit:
            self._zeit = a["datetime"].strip()
        if tag in _LEER:
            if tag == "br" and self._block is not None:
                self._block["text"] += " "
            return
        if tag == "title":
            self._im_titel = True
        if tag in _BLOECKE and self._block is not None:
            self._block_schliessen()  # <p> ohne </p>: der nächste Block beendet ihn
        klassen = f"{a.get('class', '')} {a.get('id', '')} {a.get('role', '')}"
        weg = tag in _WEG or bool(_NEBEN.search(klassen)) or a.get("aria-hidden") == "true" or "hidden" in a
        self.zaehler += 1
        nr = self.zaehler
        self.eltern[nr] = self.stapel[-1][1] if self.stapel else 0
        if tag == "article" or a.get("itemprop") == "articleBody":
            self.artikel.add(nr)
        self.stapel.append((tag, nr, weg))
        if tag in _BLOECKE and not self._weg():
            # Kette der Vorfahren, vorn die gedachte Wurzel 0 (auch Absätze ohne umgebendes Element zählen)
            self._block = {"art": _BLOECKE[tag], "text": "", "kette": [0] + [n for _, n, _ in self.stapel[:-1]], "tag": tag, "nr": nr}

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._im_titel = False
        if self._block is not None and tag == self._block["tag"]:
            self._block_schliessen()
        if any(t == tag for t, _, _ in self.stapel):
            while self.stapel:
                t, nr, _ = self.stapel.pop()
                if self._block is not None and nr == self._block["nr"]:
                    self._block_schliessen()
                if t == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self._im_titel:
            self.titel_tag += data
        if self._block is not None and not self._weg():
            self._block["text"] += data

    def _block_schliessen(self) -> None:
        b, self._block = self._block, None
        if b is None:
            return
        text = _LEERRAUM.sub(" ", b["text"]).strip()
        if text:
            self.bloecke.append({"art": b["art"], "text": text, "kette": b["kette"]})


def _vorfahren(leser: _Leser, nr: int | None) -> list[int]:
    aus = []
    while nr is not None:
        aus.append(nr)
        nr = leser.eltern.get(nr)
    return aus


def herausziehen(html: str, url: str = "") -> dict[str, Any]:
    leser = _Leser()
    try:
        leser.feed(html)
        leser.close()
    except Exception as e:  # noqa: BLE001 — kaputtes HTML: nehmen, was bis dahin gelesen ist
        logger.info("lesen: HTML nicht ganz lesbar: %s", type(e).__name__)
    leser._block_schliessen()
    bloecke = leser.bloecke

    # Wertung: jeder lange Absatz zählt für Eltern (voll) und Großeltern (halb).
    wert: dict[int, float] = {}
    for b in bloecke:
        if b["art"] != "p" or len(b["text"]) < ABSATZ_MIN:
            continue
        n = min(len(b["text"]), 1500)
        wert[b["kette"][-1]] = wert.get(b["kette"][-1], 0) + n
        if len(b["kette"]) > 1:
            wert[b["kette"][-2]] = wert.get(b["kette"][-2], 0) + n / 2
    bester = max(wert, key=lambda k: wert[k]) if wert else None
    # Ein <article> mit dem besten Element darin (oder darunter) ist der sauberere Rahmen.
    if bester is not None:
        for nr in _vorfahren(leser, bester):
            if nr in leser.artikel:
                bester = nr
                break

    gesehen: set[str] = set()
    absaetze: list[dict[str, str]] = []
    zeichen = 0
    for b in bloecke:
        if bester is not None and bester not in b["kette"]:
            continue
        text = b["text"]
        if b["art"] == "p" and len(text) < ABSATZ_MIN:
            continue
        if b["art"] == "li" and len(text) < 20:
            continue
        if text in gesehen:
            continue
        gesehen.add(text)
        absaetze.append({"art": b["art"], "text": text[:4000]})
        zeichen += len(text)
        if len(absaetze) >= BLOECKE_MAX or zeichen >= ZEICHEN_MAX:
            break
    # Zwischenüberschriften ohne folgenden Text am Ende sind Reste von Kästen.
    while absaetze and absaetze[-1]["art"] == "h":
        absaetze.pop()

    m = leser.meta
    titel = m.get("og:title") or m.get("twitter:title") or _LEERRAUM.sub(" ", leser.titel_tag).strip()
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    woerter = sum(len(a["text"].split()) for a in absaetze)
    return {
        "titel": titel[:300] or host or "Artikel",
        "quelle": (m.get("og:site_name") or host)[:120],
        "url": url,
        "datum": (m.get("article:published_time") or m.get("date") or m.get("dc.date") or leser._zeit)[:40],
        "autor": (m.get("author") or m.get("article:author") or "")[:120],
        "einleitung": (m.get("og:description") or m.get("description") or "")[:600],
        "absaetze": absaetze,
        "woerter": woerter,
        "lesezeit": max(1, round(woerter / WOERTER_JE_MINUTE)),
    }


# ── Plugin ─────────────────────────────────────────────────────────────────

class LesenPlugin(HubPlugin):
    name = "lesen"
    description = (
        "Artikel lesen, ohne FYOS zu verlassen: holt den Haupttext einer Nachricht (https, nur öffentliche Seiten) als "
        "Daten für die gui-Vorlage „artikel“."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self._r: Any = None  # Tests setzen eine Attrappe
        self._holen: Callable[[str], tuple[str, str]] = holen

    def register(self) -> None:
        return None

    def redis(self) -> Any:
        return self._r if self._r is not None else kv.klient()

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "healthy"}

    def artikel(self, args: dict[str, Any]) -> dict[str, Any]:
        url, _ = url_pruefen(args.get("url"))
        schluessel = SCHLUESSEL + hashlib.sha1(url.encode()).hexdigest()
        if not args.get("frisch"):
            try:
                roh = self.redis().get(schluessel)
                if roh:
                    return json.loads(roh)
            except Exception as e:  # noqa: BLE001 — Ablage weg: dann eben frisch holen
                logger.info("lesen: Ablage nicht erreichbar: %s", type(e).__name__)
        try:
            endgueltig, html = self._holen(url)
        except Abgewiesen:
            raise
        except httpx.HTTPError as e:
            raise ValueError(f"Seite nicht erreichbar ({type(e).__name__})") from None
        aus = herausziehen(html, endgueltig)
        if aus["woerter"] < WOERTER_WENIG:
            aus["hinweis"] = ("Kein Artikeltext gefunden (Bezahlschranke oder Seite nur mit JavaScript) — im Browser öffnen."
                              if not aus["absaetze"] else "Hier steht wohl nur ein Teil des Artikels — ganz im Browser.")
        aus["satz"] = f"„{aus['titel']}“ ({aus['quelle']}), {aus['woerter']} Wörter, etwa {aus['lesezeit']} min."
        try:
            self.redis().set(schluessel, json.dumps(aus, ensure_ascii=False), ex=ABLAGE_TTL_S)
        except Exception as e:  # noqa: BLE001
            logger.info("lesen: Ablage nicht erreichbar: %s", type(e).__name__)
        return aus

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="artikel",
                title="Artikel lesen",
                description=(
                    "Holt den Haupttext eines Artikels (Titel, Quelle, Datum, Absätze) ohne Bilder und Skripte, damit er "
                    "in FYOS gelesen werden kann. Nur https und öffentliche Seiten; 6 Stunden zwischengespeichert. "
                    "Als Fenster: gui.bauen {vorlage: \"artikel\", quelle: {werkzeug: \"lesen.artikel\", argumente: {url}}}. "
                    "Nur lesend."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "maxLength": URL_MAX, "description": "https-Adresse des Artikels"},
                        "frisch": {"type": "boolean", "description": "Zwischenspeicher übergehen"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                },
                tags=["lesen", "read"],
            )
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "artikel":
            return self.artikel(args)
        raise ValueError(f"lesen hat kein Werkzeug {method!r}")
