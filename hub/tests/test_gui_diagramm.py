"""Vorlage „diagramm“ (SeeCode, MIT) für gui.bauen: Herkunft, keine Abrufe, Darstellung eines Beispiels, Escaping.

Die Rechenfunktionen der eingebetteten Fassung laufen unter Node (Prüfstand gui_diagramm_pruefstand.js); ohne Node
werden nur die statischen Prüfungen ausgeführt.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mcp_hub import kv
from mcp_hub.plugins import gui as gui_mod
from mcp_hub.plugins.gui import GRENZEN, GuiPlugin

# Die Vorlagen sind Paketdaten des Kerns; für Node und den Dateivergleich brauchen wir echte Pfade (Quellbaum).
ORDNER = Path(gui_mod.__file__).resolve().parents[1] / "skills" / "generative-ui" / "vorlagen" / "diagramm"
PRUEFSTAND = Path(__file__).with_name("gui_diagramm_pruefstand.js")
SEECODE_SHA = "82c33b68be60578aeb21f429de5662a7d892a99f"
NODE = shutil.which("node")


@pytest.fixture()
def plugin():
    """Das Plugin mit eigener Ablage im Speicher: kein Test sieht die Ansichten eines anderen."""
    p = GuiPlugin()
    p._r = kv.SpeicherKv()
    return p


def _ohne_kommentare(js: str) -> str:
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)


# ── statisch ──────────────────────────────────────────────────────────────────────────────────────────

def test_kopf_nennt_herkunft_lizenz_und_gepinnten_stand():
    js = (ORDNER / "ansicht.js").read_text(encoding="utf-8")
    kopf = js[: js.index("*/")]
    assert "SeeCode" in kopf and "github.com/Aryanutkarsh/SeeCode" in kopf
    assert SEECODE_SHA in kopf
    assert "MIT License" in kopf and "Permission is hereby granted" in kopf and "Copyright (c) 2026 Aryanutkarsh" in kopf
    assert "Geändert" in kopf and "Wasserzeichen" in kopf and "Google-Fonts" in kopf


def test_passt_in_die_grenzen_von_gui_bauen(plugin):
    v = gui_mod.vorlage_laden(plugin.vorlagen, "diagramm")
    assert v and len(v["js"]) <= GRENZEN["js"] and len(v["css"]) <= GRENZEN["css"] and len(v["html"]) <= GRENZEN["html"]
    r = plugin.bauen({"titel": "Weg einer Ansicht", "vorlage": "diagramm", "daten": v["beispiel"]})
    doc = plugin.zeigen({"id": r["id"]})["dokument"]
    assert doc["vorlage"] == "diagramm" and "GUI.beiDaten" in doc["js"]


def test_kein_abruf_und_keine_codeausfuehrung_im_quelltext():
    code = _ohne_kommentare((ORDNER / "ansicht.js").read_text(encoding="utf-8"))
    for verboten in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "import(", "importScripts", "sendBeacon", "eval(",
                     "new Function", "Function(", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "setTimeout(\"",
                     "localStorage", "sessionStorage", "indexedDB", "document.cookie", "window.open", "location"):
        assert verboten not in code, verboten
    assert "://" not in code and "googleapis" not in code and "gstatic" not in code
    css = (ORDNER / "ansicht.css").read_text(encoding="utf-8")
    assert not re.search(r"url\(|@import|https?:|//", css.replace("/*", "").replace("*/", ""))
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)


# ── Rechnen unter Node ───────────────────────────────────────────────────────────────────────────────

def _spec(typ: str, **rest) -> dict:
    return {"type": typ, **rest}


def _knoten(n: int) -> list[dict]:
    return [{"id": f"n{i}", "label": f"Knoten {i}", "row": i // 8, "col": i % 8} for i in range(n)]


BOESE_ID = "<img src=x onerror=alert(1)>"
FAELLE: dict[str, dict] = {
    "boese": {"spec": _spec(
        "architecture",
        ueberschrift="</title><script>alert(1)</script>",
        nodes=[
            {"id": "a", "label": BOESE_ID, "sub": '"><script>x</script>', "tag": "<b>", "row": 0, "col": 0, "group": "g"},
            {"id": "b", "label": "javascript:alert(1)", "row": 0, "col": 1, "group": "g"},
        ],
        groups=[{"id": "g", "label": "<svg onload=alert(1)>"}],
        edges=[{"from": "a", "to": "b", "label": "<b>&amp;</b>"}],
    )},
    "boese_id": {"spec": _spec("architecture", nodes=[{"id": 'a"onload="x', "label": "A"}])},
    "unbekannt": {"spec": _spec("mindmap", nodes=[])},
    "zu_gross": {"spec": _spec("architecture", budget="off", nodes=_knoten(49))},
    "kante_ins_leere": {"spec": _spec("flowchart", nodes=[{"id": "a", "label": "A"}], edges=[["a", "x"]])},
    "steuerzeichen": {"spec": _spec("architecture", nodes=[{"id": "a", "label": "A\u0001B\u0000C", "row": 0, "col": 0}])},
    "proto": {"spec": json.loads('{"type": "architecture", "__proto__": {"nodes": []}, "nodes": [{"id": "a", "label": "A", "row": 0, "col": 0}]}')},
    "flowchart": {"spec": _spec(
        "flowchart", nodes=[
            {"id": "s", "shape": "start"}, {"id": "p", "label": "Prüfen"}, {"id": "d", "label": "Passt?", "shape": "decision"},
            {"id": "e", "shape": "end"}],
        edges=[["s", "p"], ["p", "d"], ["d", "e", "ja"], ["d", "p", "nein"]])},
    "state": {"spec": _spec("state", nodes=[{"id": "a", "label": "Offen"}, {"id": "b", "label": "Zu"}], edges=[["a", "b", "schließen"], ["b", "a", "öffnen"], ["a", "a", "warten"]])},
    "er": {"spec": _spec(
        "er", nodes=[
            {"id": "kunde", "label": "Kunde", "fields": ["id PK uuid", "name text"]},
            {"id": "auftrag", "label": "Auftrag", "fields": ["id PK uuid", "kunde_id FK uuid"]}],
        edges=[{"from": "kunde.id", "to": "auftrag.kunde_id", "kind": "one-many"}])},
    "sequence": {"spec": _spec(
        "sequence", participants=[{"id": "a", "label": "Agent"}, {"id": "h", "label": "Hub"}],
        messages=[["a", "h", "gui.bauen"], ["h", "a", "id", "reply"], ["h", "h", "ablegen"]], numbered=True)},
    "baum": {"spec": _spec("tree", root={"label": "Wurzel", "children": [{"label": "Ast", "children": [{"label": "Blatt"}]}, {"label": "Ast 2"}]})},
    "organigramm": {"spec": _spec("org-chart", root={"label": "Leitung", "children": [{"label": "Team A"}, {"label": "Team B"}]})},
    "abwandlung": {"spec": _spec("sequence-oauth", participants=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}], messages=[["a", "b", "x"]])},
    "medallion": {"spec": _spec("medallion", stages=[{"label": "Roh", "items": ["Logs"]}, {"label": "Sauber", "items": ["Tabellen"]}])},
    # Strenge Prüfung des SVG-Textes
    "svg_gut": {"svg": '<svg class="dg-svg" viewBox="0 0 10 10"><g class="a" data-x="1"><rect x="1" y="1" width="2" height="2"/><text x="1" y="2">a &amp; b</text></g></svg>'},
    "svg_script": {"svg": '<svg viewBox="0 0 1 1"><script>alert(1)</script></svg>'},
    "svg_href": {"svg": '<svg viewBox="0 0 1 1"><a href="https://x.example"><rect/></a></svg>'},
    "svg_ereignis": {"svg": '<svg viewBox="0 0 1 1"><rect onclick="alert(1)"/></svg>'},
    "svg_url_style": {"svg": '<svg viewBox="0 0 1 1"><rect style="fill:url(https://x.example/a)"/></svg>'},
    "svg_url_attr": {"svg": '<svg viewBox="0 0 1 1"><rect fill="url(#a)"/></svg>'},
    "svg_foreign": {"svg": '<svg viewBox="0 0 1 1"><foreignObject><div/></foreignObject></svg>'},
    "svg_image": {"svg": '<svg viewBox="0 0 1 1"><image href="data:image/png;base64,AA"/></svg>'},
    "svg_entitaet": {"svg": '<svg viewBox="0 0 1 1"><text>&#60;script&#62;</text></svg>'},
    "svg_offen": {"svg": '<svg viewBox="0 0 1 1"><g><rect/></svg>'},
    "svg_loses_zeichen": {"svg": '<svg viewBox="0 0 1 1"><text>a < b</text></svg>'},
}


def _doku_beispiel() -> dict:
    """Das Beispiel-Diagramm aus der Skill-Doku (gui.bauen-Aufruf mit vorlage diagramm)."""
    doku = (ORDNER.parents[1] / "SKILL.md").read_text(encoding="utf-8")
    for block in re.findall(r"```json\n(.*?)\n```", doku, re.S):
        if '"vorlage": "diagramm"' in block:
            return json.loads(block)
    raise AssertionError("kein diagramm-Beispiel in SKILL.md")


def test_doku_beispiel_besteht_die_hubpruefung(plugin):
    aufruf = _doku_beispiel()
    r = plugin.bauen(aufruf)
    assert plugin.zeigen({"id": r["id"]})["dokument"]["vorlage"] == "diagramm"


@pytest.fixture(scope="module")
def ergebnis(tmp_path_factory):
    if not NODE:
        pytest.skip("node fehlt")
    beispiel = json.loads((ORDNER / "vorlage.json").read_text(encoding="utf-8"))["beispiel"]
    faelle = [{"name": "beispiel", "spec": beispiel}, {"name": "doku", "spec": _doku_beispiel()["daten"]}]
    faelle += [{"name": n, **f} for n, f in FAELLE.items()]
    datei = tmp_path_factory.mktemp("diagramm") / "faelle.json"
    datei.write_text(json.dumps(faelle), encoding="utf-8")
    lauf = subprocess.run([NODE, str(PRUEFSTAND), str(ORDNER / "ansicht.js"), str(datei)], capture_output=True, text=True, timeout=60, check=False)
    assert lauf.returncode == 0, lauf.stderr[-2000:]
    return json.loads(lauf.stdout)


def test_beispiel_wird_gezeichnet(ergebnis):
    e = ergebnis["beispiel"]
    assert e["ok"] and e["art"] == "graph"
    svg = e["svg"]
    assert svg.startswith("<svg ") and svg.endswith("</svg>") and 'role="img"' in svg
    for knoten in ("agent", "bauen", "vorlage", "ablage", "app", "chat", "os", "panel"):
        assert f'data-sc-node="{knoten}"' in svg
    assert svg.count("data-sc-edge=") == 8
    assert "Wie eine Ansicht in den Chat kommt" in svg   # Titel der Zeichnung (title-Element)
    assert e["hinweise"] == []
    assert "Agent → gui.bauen: Spezifikation" in e["liste"]["verbindungen"]
    assert "gui.bauen" in e["liste"]["elemente"]
    # Legende deutsch
    assert "LEGENDE" in svg.upper() and "Hauptweg" in svg


def test_doku_beispiel_wird_gezeichnet(ergebnis):
    e = ergebnis["doku"]
    assert e["ok"] and e["hinweise"] == [] and "Alles grün?" in e["svg"]
    assert "Alles grün? → Nach main mergen: ja" in e["liste"]["verbindungen"]


def test_ergebnis_ohne_abruf(ergebnis):
    for name in ("doku", "beispiel", "flowchart", "state", "er", "sequence", "baum", "organigramm", "medallion", "abwandlung", "boese"):
        e = ergebnis[name]
        assert e["ok"], (name, e)
        svg = e["svg"]
        # (Im bösen Fall steht „javascript:alert(1)“ als Beschriftung da, als Text, nie als Adresse.)
        muster = r"https?:|//|href|<script|<style|<image|<foreignObject|url\(|@import" + ("" if name == "boese" else r"|javascript:")
        assert not re.search(muster, svg), name
        assert not re.search(r'\son[a-z]+="', svg), name   # kein Ereignis-Attribut (maskierter Text hat nie ein echtes " danach)


def test_jede_art_wird_gezeichnet(ergebnis):
    arten = {"flowchart": "graph", "state": "graph", "er": "graph", "sequence": "sequence", "baum": "tree", "organigramm": "tree",
             "medallion": "stages", "abwandlung": "sequence"}
    for name, art in arten.items():
        assert ergebnis[name]["art"] == art, name
    assert "Prüfen" in ergebnis["flowchart"]["svg"]
    assert 'data-from="kunde" data-to="auftrag"' in ergebnis["er"]["svg"]


def test_boese_beschriftungen_werden_maskiert(ergebnis):
    e = ergebnis["boese"]
    assert e["ok"]
    svg = e["svg"]
    assert "<img" not in svg and "<script" not in svg and "<b>" not in svg and "<svg onload" not in svg
    assert "&lt;img src=x onerror=alert(1)&gt;" in svg
    assert "&lt;SVG ONLOAD=ALERT(1)&gt;" in svg   # Gruppenname (SeeCode setzt ihn in Großbuchstaben)
    # Die Überschrift (Titel der Zeichnung) ist maskiert, kann das title-Element nicht schließen
    assert svg.count("<title") == 1
    assert "&lt;/title&gt;&lt;script&gt;" in svg
    assert e["liste"]["elemente"][0].startswith(BOESE_ID)


def test_eingabefehler_werden_gemeldet(ergebnis):
    assert not ergebnis["boese_id"]["ok"] and any("id" in p["at"] for p in ergebnis["boese_id"]["probleme"])
    assert ergebnis["unbekannt"]["probleme"][0]["code"] == "E_TYPE"
    assert ergebnis["zu_gross"]["probleme"][0]["code"] == "E_GROESSE"
    assert not ergebnis["kante_ins_leere"]["ok"] and "unknown node" in ergebnis["kante_ins_leere"]["probleme"][0]["msg"]


def test_steuerzeichen_und_proto_schluessel(ergebnis):
    svg = ergebnis["steuerzeichen"]["svg"]
    assert "\u0001" not in svg and "\u0000" not in svg and "ABC" in svg
    assert ergebnis["proto"]["ok"]


def test_strenge_svg_pruefung(ergebnis):
    assert ergebnis["svg_gut"]["verstoesse"] == []
    for name in [n for n in ergebnis if n.startswith("svg_") and n != "svg_gut"]:
        assert ergebnis[name]["verstoesse"], name
