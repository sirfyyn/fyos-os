"""App-Identität — Name, Untertitel, Symbol, Farbton und Kategorie jeder MCP-App an einer Stelle.

Daraus entstehen
  * `meta["app"]` an jedem Werkzeug mit Oberfläche — die Plugins schreiben `"app": identitaet("meine_app")`,
  * `Tool.icons`, `Resource.icons` und `serverInfo.icons` nach MCP-Spezifikation 2025-11-25
    (SVG als Data-URI, Glyphe weiß auf abgerundeter Fläche im Farbton),
  * der Kopf jeder Oberfläche (Marke `<!--KOPF-->` in ui/*.html, siehe _oberflaeche.py),
  * der Deeplink „In FYOS öffnen“: `oeffnen_link`.

Die Glyphen stehen in ui/_symbole.json (Lucide, ISC-Lizenz). Der Kern kennt nur seine eigenen Apps (`werkstatt`,
`mcp`, `gui`, `beispiel_app`); jedes weitere Plugin meldet seine App mit `registriere_app(...)` an, meist beim Import.
"""

from __future__ import annotations

import base64
import colorsys
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

UI_DIR = Path(__file__).with_name("ui")

#: Öffentliche Adresse der Installation (ohne Schrägstrich am Ende); leer, wenn nicht gesetzt.
OEFFENTLICHE_URL = os.getenv("FYOS_OEFFENTLICH_URL", "").strip().rstrip("/")

#: Adresse der Shell (Oberfläche). `FYOS_OS_URL` gewinnt; sonst `<öffentliche URL>/os`; sonst `/os` (relativ).
OS_ADRESSE = (os.getenv("FYOS_OS_URL") or (f"{OEFFENTLICHE_URL}/os" if OEFFENTLICHE_URL else "/os")).rstrip("/")

KATEGORIEN = ("System", "Betrieb", "Wissen", "Beispiele")

#: Eine Zeile je App. Schlüssel = Kurzname; `symbol` (Glyphe aus _symbole.json) und `ton` (Farbton 0–359).
APPS: dict[str, dict[str, Any]] = {
    "werkstatt": {
        "titel": "Werkstatt",
        "untertitel": "Skripte starten, Ergebnisse ansehen",
        "symbol": "square-terminal",
        "ton": 250,
        "kategorie": "System",
    },
    "mcp": {
        "titel": "MCP",
        "untertitel": "Plugins, Werkzeuge, Apps und Protokolle des Hubs",
        "symbol": "toolbox",
        "ton": 190,
        "kategorie": "System",
    },
    # Eine Fläche des Systems selbst, wie Werkstatt und MCP: sie zeigt, was der Agent als Ansicht baut (Diagramme,
    # Rechner, Vergleiche) — Inhalt aus jedem Bereich, deshalb weder „Betrieb“ noch „Wissen“.
    "gui": {
        "titel": "Gebaute Ansicht",
        "untertitel": "Diagramme, Rechner und Vergleiche, vom Agenten gebaut",
        "symbol": "wand-sparkles",
        "ton": 300,
        "kategorie": "System",
    },
    "beispiel_app": {
        "titel": "Notizzettel",
        "untertitel": "Kleine Beispiel-App: Notizen merken",
        "symbol": "package",
        "ton": 36,
        "kategorie": "Beispiele",
    },
}

#: Oberfläche (Dateiname in ui/) → Schlüssel in APPS. `<!--KOPF-->` in der Datei wird zum Kopf dieser App.
DATEIEN: dict[str, str] = {
    "werkstatt.html": "werkstatt",
    "mcp.html": "mcp",
    "gui.html": "gui",
    "beispiel-app.html": "beispiel_app",
}

#: Das Werkzeug, mit dem die Oberfläche geöffnet wird (modellsichtbar, lesend) — Grundlage des Deeplinks, wenn
#: der Host weder `_meta["fyos/oeffnen"]` noch `toolInfo` liefert (siehe ui/_bruecke.js, „In FYOS öffnen“).
HAUPTWERKZEUG: dict[str, str] = {
    "werkstatt": "werkstatt__suchen",
    "mcp": "mcp__uebersicht",
    "gui": "gui__zeigen",
    "beispiel_app": "beispiel_app__zeigen",
}


#: Die zwei Arten von Flächen in der Shell: ein Widget ist eine Kachel im Raster (viele nebeneinander), eine Anwendung
#: öffnet groß, lässt sich maximieren und bekommt einen eigenen Vollbild-Bildschirm.
ARTEN = ("widget", "anwendung")
ART_VORGABE = "widget"


def registriere_app(
    schluessel: str,
    eintrag: dict[str, Any],
    datei: str | None = None,
    hauptwerkzeug: str | None = None,
    art: str | None = None,
) -> None:
    """Meldet die App eines Plugins an (Titel, Untertitel, Symbol, Ton, Kategorie).

    `datei` ist der Dateiname der Oberfläche in ihrem UI-Verzeichnis (für Kopf und Brücken-Konfiguration),
    `hauptwerkzeug` das Werkzeug, das sie öffnet (`<plugin>__<name>`). Wiederholtes Anmelden überschreibt.
    `art` ist `"widget"` (Vorgabe: Kachel im Raster, viele nebeneinander, etwa ein Lagebild) oder `"anwendung"` (öffnet groß,
    maximierbar, eigener Vollbild-Bildschirm, etwa Dateien). Ohne Angabe gilt, was im `eintrag` steht, sonst `"widget"`.
    """
    art = art if art is not None else eintrag.get("art", ART_VORGABE)
    if art not in ARTEN:
        raise ValueError(f"App {schluessel!r}: art muss {' oder '.join(ARTEN)} sein, nicht {art!r}")
    APPS[schluessel] = {**eintrag, "art": art}
    if datei:
        DATEIEN[Path(datei).name] = schluessel
    if hauptwerkzeug:
        HAUPTWERKZEUG[schluessel] = hauptwerkzeug
    kategorie = str(eintrag.get("kategorie") or "")
    global KATEGORIEN
    if kategorie and kategorie not in KATEGORIEN:
        KATEGORIEN = (*KATEGORIEN, kategorie)


def identitaet(schluessel: str) -> dict[str, Any]:
    """Identität für `meta["app"]` — eine Kopie, damit Plugins sie nicht gemeinsam verändern. `art` steht immer darin."""
    return {**APPS[schluessel], "art": APPS[schluessel].get("art", ART_VORGABE)}


def fuer_datei(datei: str) -> dict[str, Any] | None:
    """Identität der Oberfläche `ui/<datei>` (None, wenn die Datei keine App ist, z. B. _stil.css)."""
    schluessel = DATEIEN.get(Path(datei).name)
    return dict(APPS[schluessel]) if schluessel else None


def bruecken_konfig(datei: str) -> dict[str, Any]:
    """Werte, die der Hub beim Ausliefern in die Brücke setzt (`KONFIG`): wer die App ist und wohin „In FYOS öffnen“ führt."""
    schluessel = DATEIEN.get(Path(datei).name)
    if not schluessel:
        return {"os": OS_ADRESSE}
    app = APPS[schluessel]
    return {
        "app": schluessel,
        "titel": app["titel"],
        "symbol": app["symbol"],
        "ton": app["ton"],
        "werkzeug": HAUPTWERKZEUG.get(schluessel, ""),
        "os": OS_ADRESSE,
    }


# ── Glyphen und Symbole ─────────────────────────────────────────────────────────────────────────


#: Jede Glyphe aus @iconify-json/lucide trägt an jedem Element dieselben Zeichenvorgaben. Der Hub nimmt sie weg und
#: setzt sie einmal an den umgebenden <svg> (CSS `.ico`, bei App-Symbolen die Gruppe in `icon_svg`) — so steuert
#: das Aussehen allein der Stil (Strichstärke, gefüllter Stern) und die Seiten werden kleiner.
_ZEICHENVORGABE = ' fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"'


@lru_cache(maxsize=1)
def symbole() -> dict[str, str]:
    """Alle Glyphen: Name → inneres SVG (24×24; Strich, Rundung und Farbe kommen vom umgebenden <svg>)."""
    roh = json.loads((UI_DIR / "_symbole.json").read_text(encoding="utf-8"))
    return {name: koerper.replace(_ZEICHENVORGABE, "") for name, koerper in roh.items()}


def glyphe(name: str) -> str:
    """Inneres SVG einer Glyphe; Unbekanntes wird ein Fenster-Symbol (nie ein Fehler beim Ausliefern)."""
    tabelle = symbole()
    return tabelle.get(name) or tabelle["app-window"]


def _hex(farbton: float, saettigung: float, helligkeit: float) -> str:
    r, g, b = colorsys.hls_to_rgb((farbton % 360) / 360, helligkeit, saettigung)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


@lru_cache(maxsize=256)
def icon_svg(symbol: str, ton: int) -> str:
    """App-Symbol als SVG: weiße Glyphe auf abgerundeter Fläche (Radius 22 %), Verlauf im Farbton.

    Gleiche Farben wie die Kachel in der Shell: oben hsl(h 82 % 62 %),
    unten hsl(h+8 78 % 44 %), darüber ein heller Glanz und ein feiner Innenrand.
    """
    oben, unten = _hex(ton, 0.82, 0.62), _hex(ton + 8, 0.78, 0.44)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">'
        "<defs>"
        f'<linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{oben}"/>'
        f'<stop offset="1" stop-color="{unten}"/></linearGradient>'
        '<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".3"/>'
        '<stop offset=".55" stop-color="#fff" stop-opacity="0"/></linearGradient>'
        "</defs>"
        '<rect width="96" height="96" rx="21" fill="url(#f)"/>'
        '<rect width="96" height="96" rx="21" fill="url(#g)"/>'
        '<rect x=".5" y=".5" width="95" height="95" rx="20.5" fill="none" stroke="#fff" stroke-opacity=".28"/>'
        '<g transform="translate(21 21) scale(2.25)" fill="none" stroke="#fff" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round">'
        # Als Bild (<img>, Data-URI) gibt es kein `currentColor`: gefüllte Punkte (z. B. bei „tag“) wären schwarz.
        f"{glyphe(symbol).replace('currentColor', '#fff')}"
        "</g></svg>"
    )


def _daten_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def icon(symbol: str, ton: int) -> dict[str, Any]:
    """MCP-`Icon` (Spezifikation 2025-11-25) für ein App-Symbol: `src` als Data-URI, SVG, beliebige Größe."""
    return {
        "src": _daten_uri(icon_svg(symbol, int(ton))),
        "mimeType": "image/svg+xml",
        "sizes": ["any"],
    }


def icon_fuer(identitaet: dict[str, Any] | None) -> dict[str, Any] | None:
    """`icon()` aus einem `meta["app"]`-Eintrag; None, wenn die Identität unvollständig ist."""
    if not isinstance(identitaet, dict) or "symbol" not in identitaet or "ton" not in identitaet:
        return None
    return icon(str(identitaet["symbol"]), int(identitaet["ton"]))


#: FYOS-Zeichen, als Linien gezeichnet — unabhängig von Schriften, damit es in jedem Client gleich aussieht.
FYOS_ZEICHEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
    '<rect width="64" height="64" rx="16" fill="#f8f7f4"/>'
    '<rect x="5" y="5" width="54" height="54" rx="13" fill="none" stroke="#e2e1de"/>'
    '<g fill="none" stroke="#0f1520" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M22 43V22.5C22 18 24.8 15.5 29.5 15.5"/><path d="M16.5 27H27.5"/>'
    '<path d="M33.5 27 40.4 41.6"/><path d="M47.5 27 36.6 50"/></g></svg>'
)


def fyos_zeichen() -> dict[str, Any]:
    """MCP-`Icon` mit dem FYOS-Zeichen — für `serverInfo.icons` (Hub und mcp-chat)."""
    return {"src": _daten_uri(FYOS_ZEICHEN_SVG), "mimeType": "image/svg+xml", "sizes": ["any"]}


# ── Deeplink ────────────────────────────────────────────────────────────────────────


#: Größte Eingabe (JSON-Zeichen) in einem Link. Die EINE Grenze für Hub und Browser: die Shell liest eine größere
#: Eingabe nicht. Der Hub lässt eine größere deshalb beim Bauen des Links weg, statt einen Link auszugeben,
#: den die Shell nicht auflösen würde.
EINGABE_MAX = 4000


def eingabe_json(args: dict[str, Any] | None) -> str | None:
    """JSON-Text der Argumente (UTF-8, Schlüssel sortiert, ohne Leerraum); None, wenn es keine gibt."""
    if not args:
        return None
    return json.dumps(args, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def eingabe_zu_gross(args: dict[str, Any] | None) -> bool:
    """True, wenn die Argumente nicht in einen Link passen (über `EINGABE_MAX` Zeichen JSON)."""
    roh = eingabe_json(args)
    return roh is not None and len(roh) > EINGABE_MAX


def eingabe_kodiert(args: dict[str, Any] | None) -> str | None:
    """Base64url nach RFC 4648 §5 ohne Auffüllzeichen („=“) vom JSON der Argumente; None, wenn keine da sind
    oder sie zu groß für einen Link sind (`eingabe_zu_gross`)."""
    roh = eingabe_json(args)
    if roh is None or len(roh) > EINGABE_MAX:
        return None
    return base64.urlsafe_b64encode(roh.encode("utf-8")).decode("ascii").rstrip("=")


def oeffnen_link(fqtn: str, args: dict[str, Any] | None = None) -> str:
    """`https://…/os?offen=app:<plugin>__<werkzeug>&eingabe=<base64url(JSON der Argumente)>`.

    `eingabe` fehlt, wenn es keine Argumente gibt — und, wenn sie über `EINGABE_MAX` Zeichen JSON groß sind: dann
    öffnet der Link die App ohne Eingabe (wer das wissen muss, fragt `eingabe_zu_gross`). Base64url nach RFC 4648 §5
    ohne Auffüllzeichen („=“); der JSON-Text ist UTF-8, Schlüssel sortiert (gleicher Zustand ergibt gleichen Link).
    """
    name = fqtn.replace(".", "__", 1)
    link = f"{OS_ADRESSE}?offen=app:{name}"
    kodiert = eingabe_kodiert(args)
    if kodiert:
        link += "&eingabe=" + kodiert
    return link


def link_erlaubt(meta: dict[str, Any] | None, scope: str) -> bool:
    """Darf zu diesem Werkzeug ein Deeplink ausgegeben werden?

    Ein Link wird in Matrix, im Chat oder per Klick geöffnet — das OS ruft das Werkzeug dann mit genau diesen
    Argumenten auf. Deshalb nur: Werkzeug mit Oberfläche (`resourceUri`), lesend (`READ`) und für das Modell
    sichtbar (nicht `visibility ["app"]`). Alles Schreibende bleibt der Oberfläche vorbehalten; ein Link darf
    nie etwas auslösen.
    """
    ui = meta.get("ui") if isinstance(meta, dict) else None
    if not isinstance(ui, dict) or not ui.get("resourceUri"):
        return False
    if ui.get("visibility") == ["app"]:
        return False
    return scope == "READ"


#: Letzte Textzeile jedes Ergebnisses mit Link.
LINK_ZEILE = "In FYOS öffnen: "
