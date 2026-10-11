"""Auslieferung der ui://-Oberflaechen: Stil und Bruecke kommen aus je einer Quelle.

``mcp_hub/plugins/_oberflaeche.py`` setzt beim Lesen jeder Oberflaeche ``ui/_stil.css`` an die Markierung
STIL im ``<style>`` und ``ui/_bruecke.js`` an die Markierung BRUECKE im ``<script>`` ein. Hier steht, was
dabei nie kaputtgehen darf: kein Markierungsrest, keine Kopien, kein eigenes Farbschema je App, keine
Modaldialoge (das iframe laeuft im Host ohne ``allow-modals``).

Dazu kommen der Kopf jeder App (``<!--KOPF-->`` wird zu Kachel, Titel, Satz und Aktionen aus
``_identitaet.py``), die Symbole (``<svg data-symbol="…">`` im HTML, ``App.symbol("…")`` im Skript) und die zwei
Werte, die der Hub in die Bruecke setzt (``KONFIG``, ``SYMBOLE``).
"""

from __future__ import annotations

import html as _html
import json
import re

import pytest

from mcp_hub.plugins import _identitaet, _oberflaeche
from mcp_hub.plugins import dateien as _dateien  # noqa: F401 — meldet die App „Dateien“ beim Import an (Kopf der Oberfläche)
from mcp_hub.plugins._oberflaeche import (
    BRUECKE,
    BRUECKE_SYMBOLE,
    KONFIG,
    KOPF,
    KOPF_ENDE,
    STIL,
    SYMBOLE,
    UI_DIR,
    genutzte_symbole,
    kopf_html,
    oberflaeche,
)

APPS = sorted(p.name for p in UI_DIR.glob("*.html"))


def test_setzt_stil_und_bruecke_ein(tmp_path, monkeypatch):
    (tmp_path / "_stil.css").write_text("a { color: red }", encoding="utf-8")
    (tmp_path / "_bruecke.js").write_text("const App = 1;", encoding="utf-8")
    (tmp_path / "x.html").write_text(
        f"<style>{STIL}\n.b {{}}</style><script>\n{BRUECKE}\nApp.start();</script>", encoding="utf-8"
    )
    monkeypatch.setattr(_oberflaeche, "UI_DIR", tmp_path)
    html = oberflaeche("x.html")
    assert html == "<style>a { color: red }\n.b {}</style><script>\nconst App = 1;\nApp.start();</script>"


def test_ersetzt_nur_die_erste_markierung(tmp_path, monkeypatch):
    (tmp_path / "_stil.css").write_text("S", encoding="utf-8")
    (tmp_path / "_bruecke.js").write_text("B", encoding="utf-8")
    (tmp_path / "x.html").write_text(f"{STIL}{STIL}{BRUECKE}{BRUECKE}", encoding="utf-8")
    monkeypatch.setattr(_oberflaeche, "UI_DIR", tmp_path)
    assert oberflaeche("x.html") == f"S{STIL}B{BRUECKE}"


def test_stil_und_bruecke_tragen_keine_markierung_voneinander():
    stil = (UI_DIR / "_stil.css").read_text(encoding="utf-8")
    bruecke = (UI_DIR / "_bruecke.js").read_text(encoding="utf-8")
    assert BRUECKE not in stil and STIL not in stil
    assert BRUECKE not in bruecke and STIL not in bruecke


def test_stil_folgt_den_variablen_der_spezifikation():
    """Der Host setzt nur Schluessel der MCP-Apps-Spezifikation; das Stylesheet benutzt genau diese Namen."""
    stil = (UI_DIR / "_stil.css").read_text(encoding="utf-8")
    for name in (
        "--color-background-primary",
        "--color-background-secondary",
        "--color-text-primary",
        "--color-text-secondary",
        "--color-border-secondary",
        "--color-ring-primary",
        "--font-sans",
        "--font-mono",
        "--border-radius-lg",
    ):
        assert f"{name}:" in stil, name
    # hell und dunkel ueber das Thema, das die Bruecke setzt; Vorgabe dunkel
    assert ':root[data-theme="light"]' in stil and ':root[data-theme="dark"]' in stil
    # der Grund bleibt durchsichtig, damit das Glas des Fensters scheint
    assert re.search(r"--color-background-primary:\s*transparent", stil)


@pytest.mark.parametrize("datei", APPS)
def test_oberflaeche_ist_vollstaendig_und_ohne_rest(datei):
    roh = (UI_DIR / datei).read_text(encoding="utf-8")
    assert roh.count(STIL) == 1 and roh.count(BRUECKE) == 1, "je Markierung genau einmal"
    assert f"<style>{STIL}" in roh and re.search(rf"<script>\s*{re.escape(BRUECKE)}", roh)
    html = oberflaeche(datei)
    assert STIL not in html and BRUECKE not in html
    assert "--color-background-primary" in html and "const App" in html
    assert html.count("ui/initialize") == 1, "die Bruecke steht einmal, nicht kopiert"
    assert '<html lang="de" data-theme="dark">' in html and 'name="viewport"' in html


@pytest.mark.parametrize("datei", APPS)
def test_app_hat_kein_eigenes_farbschema_und_keine_modaldialoge(datei):
    roh = (UI_DIR / datei).read_text(encoding="utf-8")
    assert "prefers-color-scheme" not in roh, "Thema kommt vom Host ueber die Bruecke"
    assert not re.search(r":root\s*[{,]", roh), "keine eigenen Farbdefinitionen — nur _stil.css"
    assert "host-context-changed" not in roh, "Thema und Gestaltungswerte setzt die Bruecke fuer alle"
    for aufruf in ("confirm(", "alert(", "prompt("):
        assert aufruf not in roh, f"{aufruf} liefert im Sandbox-iframe still false"


# ── Kopf, Symbole und Werte für die Brücke ─────────────────────────


def _oberflaeche_in(tmp_path, monkeypatch, name, html):
    """Ausliefern aus einem eigenen Verzeichnis mit knapper Brücke — prüft die Pipeline, nicht eine echte App."""
    (tmp_path / "_stil.css").write_text("/* stil */", encoding="utf-8")
    (tmp_path / "_bruecke.js").write_text(
        f"const KONFIG = {KONFIG};\nconst SYMBOLE = {SYMBOLE};", encoding="utf-8"
    )
    (tmp_path / name).write_text(html, encoding="utf-8")
    monkeypatch.setattr(_oberflaeche, "UI_DIR", tmp_path)
    return oberflaeche(name)


def _eingesetzt(html: str, name: str):
    """Der JSON-Wert hinter `const <name> = ` in der ausgelieferten Seite."""
    marke = f"const {name} = "
    return json.JSONDecoder().raw_decode(html[html.index(marke) + len(marke) :])[0]




def test_kopf_ohne_aktionen(tmp_path, monkeypatch):
    html = _oberflaeche_in(tmp_path, monkeypatch, "werkstatt.html", f"<body>{KOPF}<main></main></body>")
    assert '<div class="aktionen" id="aktionen"></div>' in html and KOPF not in html


def test_kopf_einer_datei_ohne_identitaet_ist_nur_der_aktionsstreifen(tmp_path, monkeypatch):
    html = _oberflaeche_in(tmp_path, monkeypatch, "x.html", f"<body>{KOPF}<button>a</button>{KOPF_ENDE}</body>")
    assert "<h1" not in html and "kachel" not in html
    assert '<div class="aktionen" id="aktionen"><button>a</button></div>' in html


def test_kopf_maskiert_was_der_hub_einsetzt():
    kopf = kopf_html({"titel": 'A&B <x> "q"', "untertitel": "<i>u</i>", "symbol": "house", "ton": 3}, "")
    assert "A&amp;B &lt;x&gt; &quot;q&quot;" in kopf and "&lt;i&gt;u&lt;/i&gt;" in kopf
    assert "<x>" not in kopf and "<i>" not in kopf


def test_nur_die_erste_kopf_marke_zaehlt(tmp_path, monkeypatch):
    html = _oberflaeche_in(tmp_path, monkeypatch, "werkstatt.html", f"<body>{KOPF}{KOPF}</body>")
    assert html.count('<header class="kopf">') == 1 and html.count(KOPF) == 1


def test_symbole_werden_im_html_gefuellt_im_skript_nicht(tmp_path, monkeypatch):
    skript = "const s = '<svg class=\"ico\" data-symbol=\"house\"></svg>';"
    html = _oberflaeche_in(
        tmp_path,
        monkeypatch,
        "x.html",
        '<svg class="x ico" data-symbol="house"></svg>\n<svg data-symbol="gibt-es-nicht"></svg>'
        f"<script>{skript}</script>",
    )
    assert re.search(r'<svg class="x ico" data-symbol="house" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><', html)
    assert _identitaet.glyphe("house") in html
    assert _identitaet.glyphe("app-window") in html, "ein unbekannter Name zeigt ein Fenster-Symbol, nie nichts"
    assert skript in html, "im Skript bleibt der Text, wie er ist (dort füllt App.symbol)"


def test_bruecke_traegt_konfig_und_symbole_je_einmal():
    bruecke = (UI_DIR / "_bruecke.js").read_text(encoding="utf-8")
    assert bruecke.count(KONFIG) == 1 and bruecke.count(SYMBOLE) == 1
    stil = (UI_DIR / "_stil.css").read_text(encoding="utf-8")
    assert KONFIG not in stil and SYMBOLE not in stil


@pytest.mark.parametrize("datei", APPS)
def test_ausgeliefert_sind_konfig_und_symbole_eingesetzt(datei):
    html = oberflaeche(datei)
    assert KONFIG not in html and SYMBOLE not in html
    assert _eingesetzt(html, "KONFIG") == _identitaet.bruecken_konfig(datei)
    symbole = _eingesetzt(html, "SYMBOLE")
    alle = _identitaet.symbole()
    assert set(BRUECKE_SYMBOLE) <= set(symbole), "die Brücke braucht ihre eigenen Symbole immer"
    assert all(alle[name] == koerper for name, koerper in symbole.items())


def test_json_im_skript_schliesst_das_skript_nicht():
    wert = {"a": "</script><b>", "umlaut": "Küche"}
    text = _oberflaeche._als_skriptjson(wert)
    assert "</" not in text and json.loads(text) == wert and "Küche" in text


def test_genutzte_symbole_sind_die_benannten_glyphen_und_die_der_bruecke():
    namen = genutzte_symbole("x('house'); y(\"gibt-es-nicht\"); z(`radar`); 'plain'")
    assert "house" in namen and "radar" in namen and "gibt-es-nicht" not in namen
    assert set(BRUECKE_SYMBOLE) <= set(namen) and namen == sorted(namen)


_SYMBOL_ATTRIBUT = re.compile(r'data-symbol="([^"]*)"')
_SYMBOL_AUFRUF = re.compile(r"""\b(?:symbol|kachel)\(\s*["'`]([a-z0-9-]+)["'`]""")
_SYMBOL_EIGENSCHAFT = re.compile(r"""\bsymbol:\s*["'`]([a-z0-9-]+)["'`]""")


def _skripte(roh: str) -> str:
    return "".join(_oberflaeche._SKRIPT.findall(roh))


@pytest.mark.parametrize("datei", APPS)
def test_jede_oberflaeche_hat_genau_einen_kopf_vom_hub(datei):
    roh = (UI_DIR / datei).read_text(encoding="utf-8")
    assert roh.count(KOPF) == 1 and roh.count(KOPF_ENDE) <= 1, "genau eine Kopf-Marke"
    assert re.search(r"<body[^>]*>\s*" + re.escape(KOPF), roh), "der Kopf steht als Erstes im <body>"
    assert "<h1" not in roh and 'class="kopf"' not in roh, (
        "Titel und Kopf kommen aus _identitaet.py, nicht aus der App (Überschriften im Inhalt sind <h2>/<h3>)"
    )
    html = oberflaeche(datei)
    app = _identitaet.fuer_datei(datei)
    assert KOPF not in html and KOPF_ENDE not in html
    assert html.count('<header class="kopf">') == 1 and html.count("<h1") == 1
    assert html.count(f"<h1>{_html.escape(app['titel'])}</h1>") == 1
    assert html.count('id="kopf-satz"') == 1 and html.count('id="aktionen"') == 1


@pytest.mark.parametrize("datei", APPS)
def test_jedes_genannte_symbol_gibt_es(datei):
    roh = (UI_DIR / datei).read_text(encoding="utf-8")
    skripte = _skripte(roh)
    bekannt = _identitaet.symbole()
    genannt = set(_SYMBOL_ATTRIBUT.findall(roh)) | set(_SYMBOL_AUFRUF.findall(skripte)) | set(_SYMBOL_EIGENSCHAFT.findall(skripte))
    fehlt = sorted(n for n in genannt if n not in bekannt)
    assert not fehlt, (
        f"{datei}: Symbole nicht in ui/_symbole.json: {fehlt} — in fyos-web/scripts/os-symbole.mjs (HUB_NAMEN) "
        "eintragen und `node scripts/os-symbole.mjs` laufen lassen"
    )


@pytest.mark.parametrize("datei", APPS)
def test_symbole_stehen_nicht_im_skript_und_keines_bleibt_leer(datei):
    roh = (UI_DIR / datei).read_text(encoding="utf-8")
    assert "data-symbol" not in _skripte(roh), "im Skript baut App.symbol(name) das Symbol — data-symbol bliebe leer"
    html = oberflaeche(datei)
    assert not re.search(r"<svg\b[^>]*data-symbol=[^>]*></svg>", html), "ein Symbol ohne Linien"


# ── Gemeinsame Bausteine: Klassenliste, Aktions- und Aufklappblock, Zeithelfer ─────────────────


def _stil_klassen() -> set[str]:
    stil = re.sub(r"/\*.*?\*/", "", (UI_DIR / "_stil.css").read_text(encoding="utf-8"), flags=re.S)
    stil = re.sub(r"url\([^)]*\)", "url()", stil)
    namen: set[str] = set()
    for kopf in re.findall(r"([^{}]+)\{", stil):
        if kopf.strip().startswith("@"):
            continue
        namen.update(re.findall(r"\.([a-zA-Z][\w-]*)", kopf))
    return namen


def test_kopfkommentar_nennt_jede_klasse_der_schicht():
    """Die Liste der reservierten Klassennamen im Kopf von _stil.css ist vollständig (neue Klasse → Liste ergänzen)."""
    stil = (UI_DIR / "_stil.css").read_text(encoding="utf-8")
    kopf = stil[: stil.index("*/")]
    liste = kopf[kopf.index("Reservierte Klassennamen") :]
    genannt = set(re.findall(r"[a-z][a-z0-9-]*", liste))
    fehlt = sorted(_stil_klassen() - genannt)
    assert not fehlt, f"nicht in der Liste reservierter Klassen im Kopf von _stil.css: {fehlt}"


@pytest.mark.parametrize(
    "name",
    ["knopf", "knoepfe", "bestaetigung", "aufklapper", "offenMerken", "aufklappen", "frische", "veraltet", "plan", "beantragen"],
)
def test_bruecke_bietet_die_gemeinsamen_bloecke(name):
    bruecke = (UI_DIR / "_bruecke.js").read_text(encoding="utf-8")
    assert re.search(rf"\b{name}\b\s*[,:}}]", bruecke.split("return {")[-1]), f"App.{name} fehlt im Export der Brücke"


def test_bruecke_zeit_kennt_relativ_voll_und_stempel():
    bruecke = (UI_DIR / "_bruecke.js").read_text(encoding="utf-8")
    for name in ("seit", "voll", "stempel", "vor"):
        assert re.search(rf"\b{name}\b", bruecke.split("const zeit")[-1][:6000]), f"App.zeit.{name} fehlt"


def test_karte_ist_container_und_reiter_fuellt_die_breite():
    stil = (UI_DIR / "_stil.css").read_text(encoding="utf-8")
    assert re.search(r"\.karte\s*\{[^}]*container:\s*karte\s*/\s*inline-size", stil)
    assert "@container karte" in stil
    assert re.search(r'\.reiter\[role="tablist"\]:not\(\.kompakt\)', stil)
