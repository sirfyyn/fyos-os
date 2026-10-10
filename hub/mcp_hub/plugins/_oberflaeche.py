"""Auslieferung der MCP-Apps-Oberflaechen (ui/*.html) — eine Stelle fuer alle Plugins.

Jede Oberflaeche traegt Markierungen, die beim Lesen der Ressource ersetzt werden:

    <style>/*STIL*/ …Layout der App…</style>    -> ui/_stil.css   (gemeinsames Aussehen)
    <script>/*BRUECKE*/ …Logik der App…</script> -> ui/_bruecke.js (MCP-Apps-Protokoll, Host-Stile, Bausteine)
    <!--KOPF--> … <!--/KOPF-->                    -> Kopf der App aus ihrer Identitaet (siehe unten)
    <svg class="ico" data-symbol="house"></svg>  -> Symbol, die Linien setzt der Hub ein

Eine Quelle, keine Kopien: wer das Aussehen aendert, aendert _stil.css; wer das Protokoll aendert,
_bruecke.js; Name, Symbol und Farbton einer App stehen in ihrer Identitaet (_identitaet.py).
Alles wird bei jedem Lesen frisch eingesetzt.

UI-Verzeichnis je Plugin: ``oberflaeche(datei, ui_verzeichnis)`` liest die HTML-Datei aus dem Verzeichnis des
Plugins (ein ``Path`` oder ein Paketname wie ``"mein_paket"``, dann das Unterverzeichnis ``ui`` dieses Pakets
ueber ``importlib.resources``). Stil, Bruecke und Symbole kommen immer aus dem Kern; so sehen alle Apps gleich aus.
Ohne Angabe gilt das UI-Verzeichnis des Kerns.

Kopf: `<!--KOPF-->` steht am Anfang des <body>. Optional folgen die Aktionen der App (Knoepfe) bis `<!--/KOPF-->`:

    <!--KOPF-->
      <button id="neu" class="rund drehen" aria-label="Aktualisieren">…</button>
    <!--/KOPF-->

Der Kopf zeigt App-Kachel und Titel nur ausserhalb der Shell (in der Shell liefert das Fenster beides);
der Satz darunter (`App.satz(text, ton)`) und die Aktionen stehen immer da. Der Hub setzt dazu zwei
Werte in die Bruecke: `KONFIG` (App, Titel, Haupt-Werkzeug, Adresse der Shell) und `SYMBOLE` (nur die Glyphen,
die diese App nutzt: jedes in Anfuehrungszeichen stehende Wort aus dem Skript, das eine Glyphe benennt).
"""

from __future__ import annotations

import html as _html
import json
import re
from importlib import resources
from pathlib import Path

from . import _identitaet

UI_DIR = Path(__file__).with_name("ui")
STIL = "/*STIL*/"
BRUECKE = "/*BRUECKE*/"
KOPF = "<!--KOPF-->"
KOPF_ENDE = "<!--/KOPF-->"
KONFIG = "/*KONFIG*/{}"
SYMBOLE = "/*SYMBOLE*/{}"

#: Glyphen, die die Bruecke selbst braucht (zusaetzlich zu denen, die das Skript der App nennt).
BRUECKE_SYMBOLE = ("app-window", "circle-help", "circle-alert", "square-arrow-out-up-right")

_SKRIPT = re.compile(r"(<script\b.*?</script>)", re.S | re.I)
_SYMBOL_ELEMENT = re.compile(r'<svg\b([^>]*?)\sdata-symbol="([a-z0-9-]+)"([^>]*)>\s*</svg>')
_WORT_IN_ANFUEHRUNG = re.compile(r"""["'`]([a-z][a-z0-9]*(?:-[a-z0-9]+)*)["'`]""")
_KOPF_MAKRO = re.compile(re.escape(KOPF) + r"(?:(.*?)" + re.escape(KOPF_ENDE) + ")?", re.S)


def kopf_html(ident: dict | None, aktionen: str = "") -> str:
    """Kopf der App: Kachel, Titel, Satz (leer, bis die App ihn setzt) und die Aktionen der App.

    Ohne Identitaet (Datei ist keine App) bleibt nur der Aktionsstreifen.
    """
    if not ident:
        return f'<header class="kopf"><div class="kopf-text"></div><div class="aktionen" id="aktionen">{aktionen}</div></header>'
    titel = _html.escape(ident["titel"])
    return (
        '<header class="kopf">'
        f'<span class="kachel app" style="--h:{int(ident["ton"])}" aria-hidden="true">'
        f'<svg class="ico" data-symbol="{_html.escape(ident["symbol"])}"></svg></span>'
        f'<div class="kopf-text"><h1>{titel}</h1>'
        f'<p class="kopf-satz" id="kopf-satz" role="status" aria-live="polite">{_html.escape(ident["untertitel"])}</p></div>'
        f'<div class="aktionen" id="aktionen">{aktionen}</div>'
        "</header>"
    )


def _symbol_fuellen(text: str) -> str:
    """`<svg class="ico" data-symbol="name"></svg>` bekommt viewBox und Linien der Glyphe."""

    def ersetze(m: re.Match) -> str:
        name = m.group(2)
        attribute = (m.group(1) + m.group(3)).rstrip()
        return (
            f'<svg{attribute} data-symbol="{name}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f"{_identitaet.glyphe(name)}</svg>"
        )

    return _SYMBOL_ELEMENT.sub(ersetze, text)


def genutzte_symbole(skripte: str) -> list[str]:
    """Glyphen, die das Skript nennt: jedes Wort in Anfuehrungszeichen, das eine bekannte Glyphe ist."""
    bekannt = _identitaet.symbole()
    namen = {w for w in _WORT_IN_ANFUEHRUNG.findall(skripte) if w in bekannt}
    namen.update(n for n in BRUECKE_SYMBOLE if n in bekannt)
    return sorted(namen)


def _als_skriptjson(wert: object) -> str:
    # `</` kann ein <script> beenden — in JSON-Zeichenketten ist `<\/` dasselbe.
    return json.dumps(wert, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# Dateien der Oberflaeche nach Aenderungszeit zwischenspeichern. Aendert sich eine Datei (mtime oder Groesse),
# wird sie neu gelesen; Ausrollen und Entwicklungsbetrieb sehen also sofort die neue Fassung. Eingesetzt (Kopf,
# Symbole, Konfiguration) wird weiter bei jedem Aufruf: das ist billig und haengt von Code ab, nicht von Dateien.
_DATEI_ZWISCHENSPEICHER: dict[Path, tuple[tuple[int, int], str]] = {}


def _datei_text(pfad: Path) -> str:
    st = pfad.stat()
    stand = (st.st_mtime_ns, st.st_size)
    treffer = _DATEI_ZWISCHENSPEICHER.get(pfad)
    if treffer is not None and treffer[0] == stand:
        return treffer[1]
    text = pfad.read_text(encoding="utf-8")
    _DATEI_ZWISCHENSPEICHER[pfad] = (stand, text)
    return text


def _plugin_text(ui_verzeichnis: "Path | str | None", datei: str) -> str:
    """Text einer Datei im UI-Verzeichnis eines Plugins (Path, Paketname oder None = Kern)."""
    if ui_verzeichnis is None:
        return _datei_text(UI_DIR / datei)
    if isinstance(ui_verzeichnis, Path):
        return _datei_text(ui_verzeichnis / datei)
    name = Path(datei).name  # nie aus dem Verzeichnis hinauslaufen
    return (resources.files(ui_verzeichnis) / "ui" / name).read_text(encoding="utf-8")


def oberflaeche(datei: str, ui_verzeichnis: "Path | str | None" = None) -> str:
    """HTML der Oberflaeche ``<ui_verzeichnis>/<datei>`` mit eingesetztem Stil, Bruecke, Kopf und Symbolen."""
    text = _plugin_text(ui_verzeichnis, datei)
    stil = _datei_text(UI_DIR / "_stil.css")
    bruecke = _datei_text(UI_DIR / "_bruecke.js")
    ident = _identitaet.fuer_datei(datei)

    # 1. Kopf (vor dem Zerlegen: die Aktionen enthalten Symbole, die gleich mit gefuellt werden)
    text = _KOPF_MAKRO.sub(lambda m: kopf_html(ident, (m.group(1) or "").strip()), text, count=1)

    # 2. Symbole im HTML (nicht in <script>: dort stehen sie in Zeichenketten und kommen ueber App.symbol)
    teile = _SKRIPT.split(text)
    for i in range(0, len(teile), 2):
        teile[i] = _symbol_fuellen(teile[i])
    text = "".join(teile)

    # 3. Stil und Bruecke
    text = text.replace(STIL, stil, 1).replace(BRUECKE, bruecke, 1)

    # 4. Werte fuer die Bruecke: Konfiguration und die Glyphen, die das Skript nennt
    skripte = "".join(s for s in _SKRIPT.findall(text))
    bekannt = _identitaet.symbole()
    tabelle = {n: bekannt[n] for n in genutzte_symbole(skripte)}
    konfig = _identitaet.bruecken_konfig(datei)
    return text.replace(KONFIG, _als_skriptjson(konfig), 1).replace(
        SYMBOLE, _als_skriptjson(tabelle), 1
    )
