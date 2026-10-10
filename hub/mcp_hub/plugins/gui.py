"""gui — generative Oberflächen: ein Agent baut für den Moment eine Ansicht, die man bedienen kann.

Übernommen ist das Prinzip von Open Intelligent UI (CopilotKit, MIT, github.com/CopilotKit/OpenIntelligentUI): Statt
nur Text antwortet der Agent, wo es hilft, mit einer eigenen kleinen Oberfläche — Erklärung mit Regler, Vergleich als
Diagramm, Rechner, SVG-Ablauf. Nicht übernommen: ein Dienst, der pro Nachricht die Darstellung wählt (hier entscheidet
das Modell nach dem Skill `generative-ui`), und die Next.js/CopilotKit-Laufzeit (hier zeigen die Shell und jeder
MCP-Apps-Client die App).

Wie es läuft:
    gui.bauen     Modell (mit Oberfläche ui://fyos/gui.html): titel, beschreibung, html, optional css, js, hoehe — oder
                  eine Vorlage mit Daten, auf Wunsch live aus einem lesenden Hub-Werkzeug. Die App bekommt das Fragment
                  über `ui/notifications/tool-input` und zeigt es in einem INNEREN iframe (`sandbox="allow-scripts"`,
                  ohne same-origin): das erzeugte Skript sieht weder die Brücke der App noch den Host, kann also keine
                  Hub-Werkzeuge rufen. Die CSP der Ressource erlaubt Skripte von esm.sh, jsDelivr, cdnjs und unpkg (d3,
                  three, chart.js, gsap, Leaflet); connect-src bleibt zu — nichts geht nach außen. Die Ansicht wird
                  unter einer Inhalts-Id abgelegt (gleicher Inhalt → gleiche Id), damit es einen Link gibt.
    gui.zeigen    Modell und App, lesend: mit id die abgelegte Ansicht (Ziel von „In FYOS öffnen“ — das lenkt
                  `oeffnen_ziel` von bauen hierher um, denn ein ganzes Dokument passt in keinen Link); ohne id die
                  letzten Ansichten.
    gui.vorlagen  Modell, lesend: die Vorlagen (Kennzahlen, Balken, Verlauf, Tabelle, Vergleich, Ablauf, Zeitleiste,
                  Status), mit name Datenform und Beispiel.

Dazu zwei Wege in server.py: `GET /hub/gui/{id}` liefert eine Ansicht als eigenständige Seite (für Flächen ohne
MCP-Apps-Host, etwa einen Browser oder das Panel einer Entwicklungsumgebung), `GET /hub/gui/{id}/daten` die frischen
Daten einer Live-Quelle.

Brücke im inneren Rahmen (für das erzeugte Skript, Namen wie bei Open Intelligent UI): `sendPrompt(text)` schreibt nach
einem Klick eine Nachricht ins Gespräch (ui/message), `openLink(url)` öffnet https-Adressen; auch als
`Websandbox.connection.remote.*`. Gestaltungswerte (--color-*, --font-*, --border-radius-*) reicht die App hinein, das
Design-System (SVG-Farbrampen .c-*, Formulare) steht in ui/gui.html.

Vorlagen und Anleitung (Skill `generative-ui`) liegen als Paketdaten im Kern: `mcp_hub/skills/generative-ui/`.

Ablage: wie bei den anderen Kern-Plugins in `mcp_hub.kv` — Redis, wenn `REDIS_URL` gesetzt ist, sonst im Speicher des
Prozesses (dann überlebt eine Ansicht keinen Neustart des Hubs; mit Redis so lange wie dessen Persistenz). Höchstens
ABLAGE_MAX Ansichten; zuerst gehen die, die am längsten nicht (neu) gebaut wurden.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import logging
import re
from importlib import resources
from pathlib import Path
from typing import Any

from .. import kv
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from ._identitaet import identitaet, oeffnen_link
from ._oberflaeche import oberflaeche

logger = logging.getLogger(__name__)

UI_GUI = "ui://fyos/gui.html"
#: Schlüssel in mcp_hub.kv: `fyos:gui:doc:<id>` je Ansicht (JSON), `fyos:gui:index` (Hash id → laufende Nummer der
#: letzten Benutzung) und `fyos:gui:zaehler`. Die Nummer statt einer Uhrzeit: lückenlos steigend, auch bei gleichem Takt.
SCHLUESSEL_DOKUMENT = "fyos:gui:doc:"
SCHLUESSEL_INDEX = "fyos:gui:index"
SCHLUESSEL_ZAEHLER = "fyos:gui:zaehler"

#: Quellen, aus denen das erzeugte Skript Bibliotheken laden darf (script-src/style-src/img-src der Ressource).
CDN = ["https://esm.sh", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://unpkg.com"]

#: Immer mit `fullmatch` prüfen: `$` ließe in Python einen angehängten Zeilenumbruch durch (als JSON-Schema-`pattern` ist es richtig).
ID_MUSTER = re.compile(r"^g-[0-9a-f]{12}$")
GRENZEN = {"titel": 120, "beschreibung": 400, "html": 200_000, "css": 60_000, "js": 120_000}
HOEHE_MIN, HOEHE_MAX = 120, 2400
ABLAGE_MAX = 300
LISTE_MAX = 20

_STEUER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _jetzt_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _nummer(wert: Any) -> int:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return 0


def _text(x: Any, n: int) -> str:
    if isinstance(x, bool) or not isinstance(x, (str, int, float)):
        return ""
    return _STEUER.sub("", str(x))[:n]


def dokument_pruefen(args: dict[str, Any]) -> dict[str, Any]:
    """Eingabe von gui.bauen → sauberes Dokument {titel, beschreibung, html, css, js, hoehe}. Wirft bei Fehlern."""
    titel = _text(args.get("titel"), GRENZEN["titel"]).strip()
    if not titel:
        raise ValueError("titel fehlt: kurz, z. B. „Kosten je Platz“")
    html = args.get("html")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("html fehlt: ein Fragment für den <body> (SVG, Markup, <script> erlaubt)")
    doc: dict[str, Any] = {"titel": titel, "beschreibung": _text(args.get("beschreibung"), GRENZEN["beschreibung"]).strip()}
    for feld in ("html", "css", "js"):
        wert = args.get(feld)
        if wert is None or wert == "":
            doc[feld] = ""
            continue
        if not isinstance(wert, str):
            raise ValueError(f"{feld} muss Text sein")
        if len(wert) > GRENZEN[feld]:
            raise ValueError(f"{feld} ist zu groß ({len(wert)} Zeichen, höchstens {GRENZEN[feld]}) — kleiner bauen oder aufteilen")
        doc[feld] = wert
    hoehe = args.get("hoehe")
    if hoehe is not None:
        if isinstance(hoehe, bool) or not isinstance(hoehe, (int, float)):
            raise ValueError("hoehe muss eine Zahl (Pixel) sein")
        doc["hoehe"] = int(min(HOEHE_MAX, max(HOEHE_MIN, hoehe)))
    return doc


_DATENBLOCK = re.compile(r'<script type="application/json" id="gui-daten">.*?</script>\n?', re.S)


def dokument_id(doc: dict[str, Any]) -> str:
    """Inhalts-Id: gleicher Inhalt ergibt dieselbe Id (ein zweites bauen legt nichts doppelt ab). Mit Live-Quelle zählen
    die Daten nicht mit — dieselbe Ansicht derselben Quelle bleibt dieselbe Id, auch wenn sich die Werte ändern."""
    felder = {k: doc.get(k, "") for k in ("titel", "beschreibung", "html", "css", "js")}
    if doc.get("quelle"):
        felder["html"] = _DATENBLOCK.sub("", felder["html"], count=1)
        felder["quelle"] = doc["quelle"]
    roh = json.dumps(felder, ensure_ascii=False, sort_keys=True)
    return "g-" + hashlib.sha256(roh.encode("utf-8")).hexdigest()[:12]


# ── Vorlagen ───────────────────────────────────────────────────────────────────────────────────────────
# Eine Vorlage ist ein Ordner mit vorlage.json (titel, zweck, schema, beispiel) und ansicht.html/.css/.js. Der Agent
# liefert nur Daten; die Ansicht liest sie mit GUI.beiDaten (ui/gui.html). Die mitgelieferten Vorlagen sind Paketdaten
# des Kerns (`mcp_hub/skills/generative-ui/vorlagen/<name>/`, neben dem Skill, der sie beschreibt) und werden über
# `importlib.resources` gelesen — nie über einen festen Pfad, also auch aus einem installierten Rad. Die Plugin-Config
# `vorlagen` zeigt auf einen eigenen Ordner mit demselben Aufbau.
VORLAGE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
DATEN_MAX = 200_000
TAKT_MIN = 30


def vorlagen_ordner(konfig: str | None = None) -> Any:
    """Ordner der Vorlagen: der konfigurierte (`Path`) oder der des Kerns (Paketdaten, `Traversable`)."""
    if konfig:
        return Path(konfig)
    return resources.files("mcp_hub") / "skills" / "generative-ui" / "vorlagen"


def vorlage_laden(ordner: Any, name: str) -> dict[str, Any] | None:
    if not VORLAGE_NAME.match(name or ""):
        return None
    d = ordner / name
    try:
        meta = json.loads((d / "vorlage.json").read_text(encoding="utf-8"))
        teile = {
            t: (d / f"ansicht.{t}").read_text(encoding="utf-8") if (d / f"ansicht.{t}").is_file() else ""
            for t in ("html", "css", "js")
        }
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not teile["html"]:
        return None
    return {"name": name, **meta, **teile}


def vorlagen_liste(ordner: Any) -> list[dict[str, Any]]:
    aus = []
    with contextlib.suppress(OSError):
        for d in sorted((p for p in ordner.iterdir() if p.is_dir()), key=lambda p: p.name):
            v = vorlage_laden(ordner, d.name)
            if v:
                aus.append({"name": v["name"], "titel": v.get("titel", v["name"]), "zweck": v.get("zweck", "")})
    return aus


_TYPEN = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}


def daten_pruefen(wert: Any, schema: dict[str, Any], pfad: str = "daten") -> list[str]:
    """Kleine Schemaprüfung für Vorlagendaten (type, required, properties, items, enum, min/maxItems). Liefert Fehler."""
    if not isinstance(schema, dict):
        return []
    typen = schema.get("type")
    if typen:
        erlaubt = typen if isinstance(typen, list) else [typen]
        passt = any(
            isinstance(wert, _TYPEN[t]) and not (t in ("integer", "number") and isinstance(wert, bool))
            for t in erlaubt if t in _TYPEN
        )
        if not passt:
            return [f"{pfad}: erwartet {' oder '.join(erlaubt)}"]
    fehler: list[str] = []
    if "enum" in schema and wert not in schema["enum"]:
        fehler.append(f"{pfad}: erlaubt sind {', '.join(map(str, schema['enum']))}")
    if isinstance(wert, dict):
        for k in schema.get("required") or []:
            if k not in wert:
                fehler.append(f"{pfad}.{k} fehlt")
        for k, s in (schema.get("properties") or {}).items():
            if k in wert:
                fehler += daten_pruefen(wert[k], s, f"{pfad}.{k}")
    if isinstance(wert, list):
        if "minItems" in schema and len(wert) < schema["minItems"]:
            fehler.append(f"{pfad}: mindestens {schema['minItems']} Einträge")
        if "maxItems" in schema and len(wert) > schema["maxItems"]:
            fehler.append(f"{pfad}: höchstens {schema['maxItems']} Einträge")
        if isinstance(schema.get("items"), dict):
            for i, x in enumerate(wert[:2000]):
                fehler += daten_pruefen(x, schema["items"], f"{pfad}[{i}]")
                if len(fehler) > 12:
                    break
    return fehler[:12]


def daten_einbetten(daten: Any) -> str:
    """Daten als JSON-Block für GUI.daten(); `<` maskiert, damit nichts den Block schließt."""
    roh = json.dumps(daten, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f'<script type="application/json" id="gui-daten">{roh}</script>\n'


def mit_daten(doc: dict[str, Any], daten: Any) -> dict[str, Any]:
    """Dokument mit (neuen) Daten: ersetzt einen vorhandenen #gui-daten-Block oder setzt ihn vor das html."""
    html = re.sub(r'<script type="application/json" id="gui-daten">.*?</script>\n?', "", doc.get("html", ""), count=1, flags=re.S)
    return {**doc, "html": daten_einbetten(daten) + html}


def _pfad_holen(wert: Any, pfad: str) -> Any:
    for teil in [p for p in (pfad or "").split(".") if p]:
        if isinstance(wert, dict):
            wert = wert.get(teil)
        elif isinstance(wert, list) and teil.isdigit() and int(teil) < len(wert):
            wert = wert[int(teil)]
        else:
            return None
    return wert


def _csp_der_app() -> str:
    """CSP, die die Shell der App gibt (`appCsp` in web/src/lib/mcp-apps/host.ts mit den resourceDomains), damit die
    eigenständige Seite dieselbe Sandbox hat."""
    r = " ".join(CDN)
    return "; ".join([
        "default-src 'none'", f"script-src 'unsafe-inline' {r}", f"style-src 'unsafe-inline' {r}",
        f"img-src data: blob: https: {r}", f"media-src blob: https: {r}", f"font-src data: {r}",
        "frame-src 'none'", "connect-src 'none'", "base-uri 'none'", "form-action 'none'",
    ])


def eigenstaendig(doc: dict[str, Any], link: str = "", ergebnis: dict[str, Any] | None = None, daten_url: str = "") -> str:
    """Eine Ansicht als eigenständige HTML-Seite: für Flächen ohne MCP-Apps-Host, z. B. ein Browser, das Panel einer
    Entwicklungsumgebung (`GET /hub/gui/<id>`, Mod fyos-ansicht), eine Datei (tools/gui_datei.py) oder ein Anhang.
    Darin ein kleiner Host, der die App ui://fyos/gui.html so einbettet wie die Shell (srcdoc-iframe mit
    sandbox="allow-scripts" und derselben CSP) und ihr die Ansicht als tool-input reicht. Ohne Gespräch dahinter:
    sendPrompt meldet „nicht verfügbar“, Links öffnen sich in einem neuen Fenster.
    Alles skaliert aufs Fenster, damit man nicht scrollen muss, und lässt sich zoomen: der Host passt die Ansicht
    ein (breiter auslegen und kleiner zeigen, bis sie ganz zu sehen ist) und zoomt darüber: Knöpfe, ⌘/Strg +/−/0,
    Touchpad-Pinch (die App reicht ihn aus dem Rahmen weiter, nur wenn dieser Host es anbietet).

    Vom Hub ausgeliefert (`GET /hub/gui/<id>`): `ergebnis` ist das von gui.zeigen (id, stand, hinweis), `daten_url`
    die Adresse für frische Daten. Dann meldet der Host serverTools und beantwortet den Nachlade-Aufruf der App
    (gui__zeigen {nur_daten}) über diese Adresse — die Live-Quelle bleibt live."""
    import html as _html

    app = oberflaeche("gui.html")
    kopf = app.index("<head>") + len("<head>")
    app = app[:kopf] + f'<meta http-equiv="Content-Security-Policy" content="{_csp_der_app()}">' + app[kopf:]
    titel = _html.escape(_text(doc.get("titel"), GRENZEN["titel"]) or "Gebaute Ansicht")

    def als_js(wert: Any) -> str:
        return json.dumps(wert, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    args = als_js(doc)
    erg = als_js({k: v for k, v in (ergebnis or {}).items() if k != "dokument"})
    RAND_PX = 10  # Abstand zum Fensterrand in CSS-Pixeln
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titel}</title>
<style>
:root {{ color-scheme: light dark; --grund: #f6f7f9; --leiste: rgba(255,255,255,.92); --text: #1d232c; --linie: rgba(0,0,0,.14); }}
@media (prefers-color-scheme: dark) {{ :root {{ --grund: #0d121b; --leiste: rgba(22,28,38,.92); --text: #e6e9ee; --linie: rgba(255,255,255,.16); }} }}
html, body {{ margin: 0; height: 100%; background: var(--grund); overflow: hidden; }}
body.frei {{ overflow: auto; }}
#huelle {{ position: relative; margin: {RAND_PX}px auto; }}
#app {{ position: absolute; left: 0; top: 0; border: 0; background: transparent; transform-origin: 0 0; }}
#zoom {{ position: fixed; right: 10px; bottom: 10px; display: flex; gap: 2px; padding: 3px; border-radius: 10px;
  background: var(--leiste); border: 1px solid var(--linie); font: 12px system-ui, sans-serif; opacity: .55; transition: opacity .15s; }}
#zoom:hover, #zoom:focus-within {{ opacity: 1; }}
#zoom button {{ min-width: 28px; height: 26px; padding: 0 6px; border: 0; border-radius: 7px; background: transparent; color: var(--text); font: inherit; cursor: pointer; }}
#zoom button:hover {{ background: var(--linie); }}
#zoom button:focus-visible {{ outline: 2px solid #4c8dff; outline-offset: 1px; }}
</style></head>
<body><div id="huelle"><iframe id="app" title="{titel}" sandbox="allow-scripts" srcdoc="{_html.escape(app, quote=True)}"></iframe></div>
<div id="zoom" role="toolbar" aria-label="Zoom">
<button type="button" id="kleiner" aria-label="Verkleinern">−</button><button type="button" id="passend" title="Einpassen (⌘0)">100 %</button><button type="button" id="groesser" aria-label="Vergrößern">+</button>
</div>
<script>
const f = document.getElementById("app"), huelle = document.getElementById("huelle");
const ANSICHT = {args};
const LINK = {json.dumps(link if link.startswith("https://") else "")};
const ERGEBNIS = {erg}, DATEN = {json.dumps(daten_url if daten_url.startswith("/") else "")};
const dunkel = matchMedia("(prefers-color-scheme: dark)");
const an = (m) => f.contentWindow && f.contentWindow.postMessage(m, "*");
const thema = () => (dunkel.matches ? "dark" : "light");

// Einpassen: die Ansicht füllt das Fenster ohne Scrollen. Passt sie in Fensterbreite, bleibt es dabei. Sonst probieren
// wir Layoutbreiten (schmaler und breiter) und nehmen die, bei der die ganze Ansicht am größten erscheint — Text wird
// breiter flacher, ein SVG mit width:100% dagegen höher; ein flacher Balken bekommt so oft ein schmales Layout.
const RAND = {RAND_PX}, BREITE_MAX = 2400, FIT_MIN = 0.2, ZOOM_MIN = 0.5, ZOOM_MAX = 5;
const BREITEN = [360, 480, 640, 800, 1000, 1280, 1600, 2000, 2400];
let inhaltH = 0, breite = 0, fit = 1, zoom = 1, ruhe = 0, messen = null, lauf = 0, bereit = false;
const platz = () => ({{ w: Math.max(160, innerWidth - 2 * RAND), h: Math.max(100, innerHeight - 2 * RAND) }});
function zeichnen() {{
  const s = fit * zoom, h = inhaltH || platz().h;
  f.style.width = breite + "px"; f.style.height = h + "px"; f.style.transform = `scale(${{s}})`;
  huelle.style.width = Math.ceil(breite * s) + "px"; huelle.style.height = Math.ceil(h * s) + "px";
  document.body.classList.toggle("frei", zoom > 1.001 || breite * s > innerWidth || h * s + 2 * RAND > innerHeight + 1);
  document.getElementById("passend").textContent = Math.round(zoom * 100) + " %";
}}
const massstab = (L, H) => Math.min(1, platz().w / L, platz().h / Math.max(1, H));
function abschluss() {{ if (inhaltH) {{ fit = Math.max(FIT_MIN, massstab(breite, inhaltH)); zeichnen(); }} }}
// Höhe nach einer Breitenänderung: die nächste Meldung der App abwarten, bis 220 ms Ruhe ist (höchstens 700 ms).
function hoeheAbwarten() {{
  return new Promise((ok) => {{
    const fertig = () => {{ clearTimeout(m.t); clearTimeout(m.max); messen = null; ok(inhaltH); }};
    const m = {{ weiter: () => {{ clearTimeout(m.t); m.t = setTimeout(fertig, 220); }} }};
    m.t = setTimeout(fertig, 260); m.max = setTimeout(fertig, 700); messen = m;
  }});
}}
async function einpassen() {{
  const meinLauf = ++lauf, p = platz();
  breite = Math.min(p.w, BREITE_MAX); fit = 1; zeichnen();
  let H = await hoeheAbwarten();
  if (meinLauf !== lauf) return;
  let best = {{ L: breite, s: massstab(breite, H) }};
  if (best.s < 0.999) {{
    huelle.style.visibility = "hidden";
    for (const L of BREITEN.filter((x) => Math.abs(x - p.w) > 40)) {{
      breite = L; zeichnen(); H = await hoeheAbwarten();
      if (meinLauf !== lauf) return;
      const s = massstab(L, H);
      if (s > best.s + 0.01 || (s > best.s - 0.01 && Math.abs(L - p.w) < Math.abs(best.L - p.w))) best = {{ L, s }};
    }}
    breite = best.L; zeichnen(); await hoeheAbwarten();
    if (meinLauf !== lauf) return;
    huelle.style.visibility = "";
  }}
  abschluss();
}}
// Erst einpassen, wenn die Ansicht steht (400 ms ohne neue Höhe); spätere Änderungen (Regler, Bibliothek geladen)
// passen nur noch den Maßstab an.
function hoeheNeu(h) {{
  inhaltH = h;
  if (messen) return messen.weiter();
  if (!bereit) {{ clearTimeout(ruhe); ruhe = setTimeout(() => {{ bereit = true; einpassen(); }}, 400); return; }}
  abschluss();
}}
function zoomen(neu) {{
  neu = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, neu));
  const el = document.scrollingElement, bx = (el.scrollLeft + innerWidth / 2) / Math.max(1, el.scrollWidth),
    by = (el.scrollTop + innerHeight / 2) / Math.max(1, el.scrollHeight);
  zoom = neu; zeichnen();
  el.scrollLeft = bx * el.scrollWidth - innerWidth / 2; el.scrollTop = by * el.scrollHeight - innerHeight / 2;
}}
const schritt = (s) => (s === 0 ? zoomen(1) : zoomen(zoom * (s > 0 ? 1.25 : 0.8)));
// Touchpad-Pinch liefert viele kleine Schritte (|dy| ≈ 1–10), ein Mausrad mit Strg große (≈ 100): gedeckelt auf ±20 %.
const rad = (dy) => zoomen(zoom * Math.exp(-Math.max(-20, Math.min(20, dy)) * 0.01));
document.getElementById("kleiner").onclick = () => schritt(-1);
document.getElementById("groesser").onclick = () => schritt(1);
document.getElementById("passend").onclick = () => schritt(0);
addEventListener("wheel", (e) => {{ if (e.ctrlKey) {{ e.preventDefault(); rad(e.deltaY); }} }}, {{ passive: false }});
addEventListener("keydown", (e) => {{
  const s = {{ "+": 1, "=": 1, "-": -1, "0": 0 }}[e.key];
  if ((e.ctrlKey || e.metaKey) && s !== undefined) {{ e.preventDefault(); schritt(s); }}
}});
let groesse = 0;
addEventListener("resize", () => {{ clearTimeout(groesse); groesse = setTimeout(() => {{ if (bereit) einpassen(); }}, 150); }});
breite = Math.min(platz().w, BREITE_MAX); zeichnen();

addEventListener("message", (e) => {{
  if (e.source !== f.contentWindow) return;
  const m = e.data || {{}};
  if (m.typ === "gui-zoom") {{ if ([1, -1, 0].includes(m.schritt)) schritt(m.schritt); else rad(Number(m.dy) || 0); return; }}
  if (m.method === "ui/initialize") an({{jsonrpc: "2.0", id: m.id, result: {{protocolVersion: "2026-01-26",
    hostInfo: {{name: "fyos-datei", version: "1"}}, hostCapabilities: DATEN ? {{openLinks: {{}}, serverTools: {{}}}} : {{openLinks: {{}}}},
    hostContext: {{theme: thema()}}}}}});
  else if (m.method === "ui/notifications/initialized") {{
    an({{typ: "gui-host", zoom: true}});
    an({{jsonrpc: "2.0", method: "ui/notifications/tool-input", params: {{arguments: ANSICHT}}}});
    const sc = ERGEBNIS.id ? {{...ERGEBNIS, dokument: ANSICHT, link: LINK}} : {{satz: "Datei", link: LINK}};
    an({{jsonrpc: "2.0", method: "ui/notifications/tool-result", params: {{structuredContent: sc}}}});
  }} else if (DATEN && m.method === "tools/call" && m.id != null && (m.params || {{}}).name === "gui__zeigen"
             && ((m.params || {{}}).arguments || {{}}).nur_daten) {{
    // Nachladen der Live-Quelle: frische Daten vom Hub (gleicher Ursprung), Antwort wie ein Werkzeugergebnis
    fetch(DATEN, {{cache: "no-store"}}).then((r) => r.json()).then((j) => {{
      if (j && j.ok) an({{jsonrpc: "2.0", id: m.id, result: {{structuredContent: j.result, content: []}}}});
      else an({{jsonrpc: "2.0", id: m.id, error: {{code: -32000, message: String((j && j.error) || "Nicht aktualisiert")}}}});
    }}).catch((err) => an({{jsonrpc: "2.0", id: m.id, error: {{code: -32000, message: String(err)}}}}));
  }} else if (m.method === "ui/open-link") {{
    const url = String((m.params || {{}}).url || "");
    if (/^https:\\/\\//.test(url)) window.open(url, "_blank", "noopener");
    if (m.id != null) an({{jsonrpc: "2.0", id: m.id, result: {{}}}});
  }} else if (m.method === "ui/notifications/size-changed") {{
    const h = Number((m.params || {{}}).height);
    if (Number.isFinite(h) && h > 0) hoeheNeu(Math.min(8000, Math.ceil(h)));
  }} else if (m.id != null && m.method) {{
    an({{jsonrpc: "2.0", id: m.id, error: {{code: -32601, message: "In der Datei nicht verfügbar"}}}});
  }}
}});
dunkel.addEventListener("change", () => an({{jsonrpc: "2.0", method: "ui/notifications/host-context-changed", params: {{theme: thema()}}}}));
</script></body></html>
"""


class GuiPlugin(HubPlugin):
    name = "gui"
    description = (
        "Generative Oberflächen: Der Agent baut für eine Frage eine bedienbare Ansicht (Diagramm, Rechner, Vergleich, "
        "SVG-Ablauf) und zeigt sie als App in der FYOS-Shell und in jedem MCP-Apps-Client. Anleitung: Skill generative-ui."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        cfg = config or {}
        #: Ordner mit eigenen Vorlagen (Aufbau wie `mcp_hub/skills/generative-ui/vorlagen`); leer = die des Kerns.
        self._vorlagen_konfig = cfg.get("vorlagen")
        self._reg: Any = None
        self._r: Any = None  # Tests setzen eine Attrappe

    def redis(self) -> Any:
        return self._r if self._r is not None else kv.klient()

    def register(self) -> None:
        return None

    def registry_anbinden(self, reg: Any) -> None:
        """Für Live-Quellen: lesende Hub-Werkzeuge rufen (server.py ruft das nach build_registry)."""
        self._reg = reg

    @property
    def vorlagen(self) -> Any:
        return vorlagen_ordner(self._vorlagen_konfig)

    # ── Live-Quelle ────────────────────────────────────────────────────────
    def _quelle_pruefen(self, q: Any) -> dict[str, Any] | None:
        """{werkzeug, argumente?, pfad?, takt?} → sauber. Nur lesende Werkzeuge, die das Modell sieht, nie gui selbst."""
        if q is None:
            return None
        if not isinstance(q, dict):
            raise ValueError("quelle muss ein Objekt sein: {werkzeug, argumente?, pfad?, takt?}")
        werkzeug = _text(q.get("werkzeug"), 120).strip()
        if not re.match(r"^[a-z0-9_]+\.[a-z0-9_]+$", werkzeug):
            raise ValueError("quelle.werkzeug: Name wie audit.stats (plugin.werkzeug)")
        if werkzeug.startswith("gui."):
            raise ValueError("quelle.werkzeug: gui selbst geht nicht")
        argumente = q.get("argumente") or {}
        if not isinstance(argumente, dict) or len(json.dumps(argumente)) > 4000:
            raise ValueError("quelle.argumente muss ein kleines Objekt sein")
        aus: dict[str, Any] = {"werkzeug": werkzeug, "argumente": argumente}
        if q.get("pfad"):
            aus["pfad"] = _text(q.get("pfad"), 120).strip()
        if q.get("takt") is not None:
            takt = q.get("takt")
            if isinstance(takt, bool) or not isinstance(takt, (int, float)):
                raise ValueError("quelle.takt: Sekunden als Zahl")
            aus["takt"] = int(max(TAKT_MIN, min(3600, takt)))
        if self._reg is not None:
            from ..registry import scope_from_tags, sichtbarkeit

            rt = self._reg.get_tool(werkzeug)
            if rt is None:
                raise ValueError(f"quelle.werkzeug {werkzeug} gibt es nicht (hub.search_tools)")
            if scope_from_tags(getattr(rt.descriptor, "tags", None)) != "READ" or sichtbarkeit(rt.descriptor) == "app":
                raise ValueError(f"quelle.werkzeug {werkzeug} ist nicht nur lesend — Quellen müssen lesend sein")
        return aus

    def _quelle_holen(self, q: dict[str, Any]) -> Any:
        if self._reg is None:
            raise ValueError("Live-Quelle hier nicht verfügbar (keine Registry)")
        from ..registry import call as hub_call

        r = hub_call(self._reg, q["werkzeug"], dict(q.get("argumente") or {}))
        if r.status != "ok":
            raise ValueError(f"Quelle {q['werkzeug']}: {r.error}")
        wert = _pfad_holen(r.result, q["pfad"]) if q.get("pfad") else r.result
        if len(json.dumps(wert, ensure_ascii=False, default=str)) > DATEN_MAX:
            raise ValueError(f"Quelle {q['werkzeug']}: Daten zu groß (höchstens {DATEN_MAX} Zeichen) — pfad oder Argumente enger")
        return json.loads(json.dumps(wert, ensure_ascii=False, default=str))

    # ── Dokument bauen (eigenes html oder Vorlage + Daten) ─────────────────
    def dokument(self, args: dict[str, Any], live: bool = True) -> dict[str, Any]:
        name = _text(args.get("vorlage"), 40).strip()
        quelle = self._quelle_pruefen(args.get("quelle"))
        umformen = args.get("umformen")
        if umformen is not None and (not isinstance(umformen, str) or len(umformen) > 4000):
            raise ValueError("umformen: JS-Funktion als Text, höchstens 4000 Zeichen, z. B. \"d => ({kacheln: …})\"")
        vorlage = None
        if name:
            if any(args.get(k) for k in ("html", "css", "js")):
                raise ValueError("Entweder vorlage + daten oder eigenes html/css/js — nicht beides")
            vorlage = vorlage_laden(self.vorlagen, name)
            if vorlage is None:
                raise ValueError(f"Vorlage {name!r} gibt es nicht — gui.vorlagen listet sie")
            doc = dokument_pruefen({"titel": args.get("titel"), "beschreibung": args.get("beschreibung"), "hoehe": args.get("hoehe"),
                                    "html": vorlage["html"], "css": vorlage["css"], "js": vorlage["js"]})
            doc["vorlage"] = name
        else:
            doc = dokument_pruefen(args)
        if umformen:
            doc["js"] = f"GUI.umformen = ({umformen.strip()});\n" + doc.get("js", "")
        daten = args.get("daten")
        if quelle:
            doc["quelle"] = quelle
            if live:
                daten = self._quelle_holen(quelle)
        if daten is None and vorlage is not None and not quelle:
            raise ValueError(f"daten fehlen für Vorlage {name} — Form: gui.vorlagen {{name: \"{name}\"}}")
        if daten is not None:
            if len(json.dumps(daten, ensure_ascii=False, default=str)) > DATEN_MAX:
                raise ValueError(f"daten zu groß (höchstens {DATEN_MAX} Zeichen)")
            if vorlage is not None and not umformen:
                fehler = daten_pruefen(daten, vorlage.get("schema") or {})
                if fehler:
                    raise ValueError(f"Daten passen nicht zur Vorlage {name}: " + "; ".join(fehler))
            doc = mit_daten(doc, daten)
        return doc

    def health(self) -> dict[str, Any]:
        try:
            r = self.redis()
            anzahl = len(r.hgetall(SCHLUESSEL_INDEX))
        except Exception as e:  # noqa: BLE001 — Redis weg: nicht gesund, aber kein Fehler des Hubs
            return {"ok": False, "status": "unhealthy", "grund": f"Ablage (mcp_hub.kv) nicht erreichbar: {type(e).__name__}"}
        return {"ok": True, "status": "healthy", "ansichten": anzahl, "ablage": "speicher" if kv.ist_speicher(r) else "redis"}

    # ── Ablage (mcp_hub.kv) ────────────────────────────────────────────────
    def _ablegen(self, i: str, doc: dict[str, Any]) -> bool:
        """Legt ab und räumt die am längsten unbenutzten weg. False, wenn die Ablage fehlt — die Ansicht wird trotzdem gezeigt."""
        try:
            r = self.redis()
            schluessel = SCHLUESSEL_DOKUMENT + i
            if not r.exists(schluessel):
                r.set(schluessel, json.dumps({"id": i, **doc, "angelegt": _jetzt_iso()}, ensure_ascii=False))
            # Auch eine schon vorhandene Ansicht gilt als benutzt: sie rückt beim Aufräumen nach hinten.
            r.hset(SCHLUESSEL_INDEX, i, str(r.incr(SCHLUESSEL_ZAEHLER)))
            self._aufraeumen(r)
            return True
        except Exception as e:  # noqa: BLE001 — Redis nicht erreichbar o. ä.: die Ansicht erscheint trotzdem
            logger.info("gui: Ablage nicht erreichbar: %s", type(e).__name__)
            return False

    @staticmethod
    def _aufraeumen(r: Any) -> None:
        index = r.hgetall(SCHLUESSEL_INDEX)
        zuviel = len(index) - ABLAGE_MAX
        if zuviel <= 0:
            return
        for k in sorted(index, key=lambda k: _nummer(index[k]))[:zuviel]:
            r.delete(SCHLUESSEL_DOKUMENT + k)
            r.hdel(SCHLUESSEL_INDEX, k)

    def _index(self) -> dict[str, str]:
        """id → laufende Nummer der letzten Benutzung."""
        try:
            return dict(self.redis().hgetall(SCHLUESSEL_INDEX))
        except Exception as e:  # noqa: BLE001
            logger.info("gui: Ablage nicht erreichbar: %s", type(e).__name__)
            raise ValueError("Die Ablage der Ansichten (mcp_hub.kv) ist gerade nicht erreichbar") from None

    def _lesen(self, i: str) -> dict[str, Any] | None:
        try:
            roh = self.redis().get(SCHLUESSEL_DOKUMENT + i)
        except Exception as e:  # noqa: BLE001
            logger.info("gui: Ablage nicht erreichbar: %s", type(e).__name__)
            raise ValueError("Die Ablage der Ansichten (mcp_hub.kv) ist gerade nicht erreichbar") from None
        try:
            d = json.loads(roh) if roh else None
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    # ── Werkzeuge ──────────────────────────────────────────────────────────
    def bauen(self, args: dict[str, Any]) -> dict[str, Any]:
        doc = self.dokument(args)
        i = dokument_id(doc)
        abgelegt = self._ablegen(i, doc)
        link = oeffnen_link("gui.zeigen", {"id": i})
        satz = f"Ansicht „{doc['titel']}“ gebaut ({i})."
        if not abgelegt:
            satz += " Nicht abgelegt (Ablage fehlt) — der Link öffnet sie nicht."
        return {"satz": satz, "id": i, "abgelegt": abgelegt, "link": link}

    def zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        i = _text(args.get("id"), 40).strip()
        if i:
            if not ID_MUSTER.fullmatch(i):
                raise ValueError("id ist ungültig: g- und 12 Hex-Zeichen, z. B. g-3f9a0c1d2e4b")
            d = self._lesen(i)
            if d is None:
                raise ValueError(
                    f"Ansicht {i} gibt es nicht (mehr) — die Ablage hält die letzten {ABLAGE_MAX} "
                    "(ohne Redis nur bis zum Neustart des Hubs)"
                )
            dokument = {k: d.get(k, "") for k in ("titel", "beschreibung", "html", "css", "js")}
            if isinstance(d.get("hoehe"), int):
                dokument["hoehe"] = d["hoehe"]
            for k in ("vorlage", "quelle"):
                if d.get(k):
                    dokument[k] = d[k]
            aus = {"satz": f"Ansicht „{dokument['titel']}“.", "id": i, "angelegt": d.get("angelegt")}
            quelle = d.get("quelle") if isinstance(d.get("quelle"), dict) else None
            if quelle:
                # Live-Quelle: frische Daten holen. Klappt das nicht, bleibt der abgelegte Stand und ein Hinweis.
                try:
                    daten = self._quelle_holen(quelle)
                    aus["stand"] = _jetzt_iso()
                    if args.get("nur_daten"):
                        return {**aus, "satz": f"Daten für „{dokument['titel']}“.", "daten": daten}
                    dokument = mit_daten(dokument, daten)
                except ValueError as e:
                    aus["hinweis"] = f"Nicht aktualisiert: {e}"
                    if args.get("nur_daten"):
                        raise
            return {**aus, "dokument": dokument}
        liste = []
        index = self._index()
        for k in sorted(index, key=lambda k: _nummer(index[k]), reverse=True)[:LISTE_MAX]:
            d = self._lesen(k)
            if d:
                liste.append({"id": k, "titel": _text(d.get("titel"), 120), "beschreibung": _text(d.get("beschreibung"), 200), "angelegt": d.get("angelegt")})
        satz = f"{len(liste)} zuletzt gebaute Ansichten." if liste else "Noch keine gebauten Ansichten."
        return {"satz": satz, "ansichten": liste}

    def oeffnen_ziel(self, werkzeug: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Registry-Haken: der Link „In FYOS öffnen“ von bauen führt zu zeigen {id} (die Id folgt aus dem Inhalt)."""
        if werkzeug != "bauen":
            return None
        # Ohne Live-Abruf: die Id einer Quellen-Ansicht hängt nicht an den Daten, die einer Vorlage nur an den daten.
        return "gui.zeigen", {"id": dokument_id(self.dokument(args, live=False))}

    def vorlagen_zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        name = _text(args.get("name"), 40).strip()
        if name:
            v = vorlage_laden(self.vorlagen, name)
            if v is None:
                raise ValueError(f"Vorlage {name!r} gibt es nicht — ohne name kommt die Liste")
            return {"satz": f"Vorlage „{v.get('titel', name)}“: {v.get('zweck', '')}", "name": name, "titel": v.get("titel", name),
                    "zweck": v.get("zweck", ""), "schema": v.get("schema", {}), "beispiel": v.get("beispiel")}
        liste = vorlagen_liste(self.vorlagen)
        return {"satz": f"{len(liste)} Vorlagen. Mit name kommen Datenform (schema) und Beispiel.", "vorlagen": liste}

    # ── Hub ────────────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        meta = {"ui": {"resourceUri": UI_GUI}, "app": identitaet("gui")}
        return [
            ToolDescriptor(
                name="bauen",
                title="Ansicht bauen",
                description=(
                    "Zeigt eine bedienbare Ansicht als App: Kennzahlen, Balken, Verlauf, Tabelle, Vergleich, Ablauf, "
                    "Zeitleiste, Status — oder frei gebaut (Rechner, 3D). Nur wenn Bild oder Interaktion mehr hilft als "
                    "Text — VORHER Skill generative-ui lesen (skills.lesen). Am einfachsten: vorlage + daten (Form aus "
                    "gui.vorlagen {name}). Live: quelle {werkzeug, argumente, pfad?, takt?} — ein lesendes Hub-Werkzeug "
                    "liefert die Daten und die Ansicht frischt sie nach; passt dessen Form nicht zur Vorlage, formt "
                    "umformen (JS-Funktion, z. B. \"d => ({kacheln: …})\") sie um. Frei: html (Body-Fragment, <script> "
                    "auch type=module mit import aus three, d3, chart.js, gsap), css, js; Daten per GUI.beiDaten. Sandbox "
                    "ohne Netz; sendPrompt(text) nach Klick schreibt ins Gespräch. Antwort: id und Link „In FYOS öffnen“."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "titel": {"type": "string", "maxLength": GRENZEN["titel"], "description": "Kurz, Satzanfang groß"},
                        "beschreibung": {"type": "string", "maxLength": GRENZEN["beschreibung"], "description": "Ein Satz: was die Ansicht zeigt (auch Textersatz)"},
                        "vorlage": {"type": "string", "description": "Name aus gui.vorlagen (statt html/css/js)"},
                        "daten": {"description": "Daten für die Vorlage (Form: gui.vorlagen {name}) oder für GUI.daten() im eigenen html"},
                        "quelle": {
                            "type": "object",
                            "description": "Live-Daten aus einem LESENDEN Hub-Werkzeug statt daten",
                            "properties": {
                                "werkzeug": {"type": "string", "description": "plugin.werkzeug, z. B. audit.stats"},
                                "argumente": {"type": "object"},
                                "pfad": {"type": "string", "description": "Teil des Ergebnisses, z. B. aufrufe oder liste.0"},
                                "takt": {"type": "integer", "minimum": TAKT_MIN, "maximum": 3600, "description": "Selbst nachladen alle n Sekunden"},
                            },
                            "required": ["werkzeug"],
                            "additionalProperties": False,
                        },
                        "umformen": {"type": "string", "maxLength": 4000, "description": "JS-Funktion Rohdaten → Vorlagendaten, läuft in der Sandbox"},
                        "html": {"type": "string", "description": "Body-Fragment, kein <html>/<head> (ohne vorlage)"},
                        "css": {"type": "string", "description": "Nur ansichtseigene Stile"},
                        "js": {"type": "string", "description": "Klassisches Skript nach dem html (kein top-level await)"},
                        "hoehe": {"type": "integer", "minimum": HOEHE_MIN, "maximum": HOEHE_MAX, "description": "Geschätzte Höhe in Pixel"},
                    },
                    "required": ["titel"],
                    "additionalProperties": False,
                },
                # „read“: bauen wirkt nirgends — es legt nur eine Kopie seiner eigenen Ausgabe für den Link ab.
                tags=["gui", "read", "flaeche"],
                meta=meta,
            ),
            ToolDescriptor(
                name="zeigen",
                title="Gebaute Ansichten",
                description=(
                    "Eine früher gebaute Ansicht wieder zeigen (id aus gui.bauen) — Ziel der Links „In FYOS öffnen“. "
                    "Ohne id: die letzten Ansichten mit Titel. Nur lesend."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": ID_MUSTER.pattern, "description": "id aus gui.bauen"},
                        "nur_daten": {"type": "boolean", "description": "Nur frische Daten der Live-Quelle (für die App)"},
                    },
                    "additionalProperties": False,
                },
                tags=["gui", "read", "flaeche"],
                meta=meta,
            ),
            ToolDescriptor(
                name="vorlagen",
                title="Ansichts-Vorlagen",
                description=(
                    "Vorlagen für gui.bauen: ohne name die Liste (Kennzahlen, Balken, Verlauf, Tabelle, Vergleich, "
                    "Ablauf, Zeitleiste, Status …), mit name Zweck, Datenform (schema) und ein Beispiel. Nur lesend."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Vorlage, z. B. balken"}},
                    "additionalProperties": False,
                },
                tags=["gui", "read"],
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_GUI,
                name="Gebaute Ansicht",
                description="Vom Agenten gebaute, bedienbare Ansicht in einer Sandbox",
                read=lambda: oberflaeche("gui.html"),
                meta={"ui": {"prefersBorder": True, "csp": {"resourceDomains": list(CDN)}}},
            )
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "bauen":
            return self.bauen(args)
        if method == "zeigen":
            return self.zeigen(args)
        if method == "vorlagen":
            return self.vorlagen_zeigen(args)
        raise ValueError(f"gui hat kein Werkzeug {method!r}")
