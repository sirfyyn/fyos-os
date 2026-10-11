#!/usr/bin/env python3
"""SeeCode-Teile für die Vorlage `diagramm` in eine einzige Datei einbetten.

SeeCode (github.com/Aryanutkarsh/SeeCode, MIT) rechnet aus einer kurzen JSON-Spezifikation ein SVG-Diagramm. Dieses
Skript nimmt von dort nur den Kern: Spezifikationsformat (Schemas), Prüfer, Text-Messung und die Renderer für
Graph-, Sequenz- und Baumdiagramme. Es schreibt `ansicht.js` der Vorlage neu:

    python3 -I tools/seecode_einbetten/einbetten.py <SeeCode-Checkout> [<ansicht.js>]

Ohne zweites Argument schreibt es nach
`hub/mcp_hub/skills/generative-ui/vorlagen/diagramm/ansicht.js`.

Das Skript braucht die SeeCode-Quellen: einen Checkout von github.com/Aryanutkarsh/SeeCode auf dem gepinnten Commit
(unten `SEECODE_COMMIT`). Zum Betrieb des Hubs und für die Tests ist es nicht nötig, `ansicht.js` liegt fertig im
Repo. Die Quelle wird vorher gegen die SHA-256 der Dateien geprüft (gepinnter Stand), verändert wird sie nur durch die
unten aufgeführten, einzeln geprüften Ersetzungen. Nichts davon läuft hier: gelesen und als Text zusammengesetzt.
Der Kleber (kleber.js) ist eigener Code dieses Projekts.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SEECODE_COMMIT = "82c33b68be60578aeb21f429de5662a7d892a99f"
SEECODE_VERSION = "0.6.1"
SEECODE_URL = "https://github.com/Aryanutkarsh/SeeCode"
STAND = "2026-10-11"

SKILL = "skills/seecode/"
LIB = SKILL + "scripts/lib/"

# Gepinnter Inhalt der übernommenen Dateien (SHA-256).
SHA256 = {
    "LICENSE": "5be261958981f40476e2f0c073bd427f362f92d5f8903b1134eb3527f3854785",
    LIB + "svg.mjs": "302984d2543004459d41e577aee00344e104654d0729c632c23fd3658f6400ae",
    LIB + "text.mjs": "e835b186a607bb9da2db677ee232acbd1eae378af07aada1edec4a8447b8694e",
    LIB + "motion.mjs": "1fbd33b5165cb6e9dc2f502c156dc7335c5ee8ce03369cfc506709428baa8796",
    LIB + "tokens.mjs": "873ad7c8908ec3efa95b9127be1dc72bae5bea5907bd42bffe21997881eb0fe3",
    LIB + "schema.mjs": "65fe114f45baecea99d580770df1e58fe0d6096657a74e469a01fdfe0e7df3c5",
    LIB + "render/shared/icons.mjs": "4f3ed529829d42fdf45aa504cbca1206abf15c0305757e97ddde4a846579bcc9",
    LIB + "render/shared/nodes.mjs": "ccdccc649b69a6d23adc4b21718e62b2f34ef65ed62a9da7d7030b4b06a69603",
    LIB + "render/shared/edges.mjs": "b04c41ec0e8fc90d1071968165e0385834c8c372cf3e0e186d3c24228ed40c9e",
    LIB + "render/shared/legend.mjs": "61bc831265ab2f7792f073e74605c07d6fb7ef4e6958cdd957a83df78d005cee",
    LIB + "render/graph/route.mjs": "88bc7125004218c8a79d184a65f3494a22f02ef3aa0f981bb1dd78267f2ae0b3",
    LIB + "render/graph/graph.mjs": "204f0935d212e08e03543673abe8b3cc93a4305ffa866a225c936b1f00e51de6",
    LIB + "render/lanes/sequence.mjs": "0560fa4c29975bedbbae5e0d117c9b9b3173111ac34979f0b96466f00df60401",
    LIB + "render/structure/tree.mjs": "dcdd6b7051b08cdfdc010d0b9bae9cb91a3c13e14eb157694d0f4a2610215ecb",
    SKILL + "schemas/common.schema.json": "8bcfd066f15b8555df0014da9240a935a05b63430fdc1e5d9c64d03ae774fad6",
    SKILL + "schemas/graph.schema.json": "12a50111a6f9658f3c7859286846c56eac5c044c053a2cba1c6625763c4a4d25",
    SKILL + "schemas/stages.schema.json": "24cd1d4693ec74973579c468b3eea1e1de3e9a117c43569e502ee55b57fc3bf4",
    SKILL + "schemas/sequence.schema.json": "d10f5b0e93d113106e3e57b5e5ea239ef58ed53cebeab87f96bffc8289eae8d8",
    SKILL + "schemas/tree.schema.json": "8d2ea3e231a29735a0a99a7313c8bc6a2f5475da01633864b0b363952886651a",
}

# Reihenfolge = Abhängigkeiten. (Schlüssel, Datei, Ersetzungen (alt, neu), Abschnitt ab dem Marker abschneiden)
MODULE: list[tuple[str, str, list[tuple[str, str]], str | None]] = [
    ("svg", LIB + "svg.mjs", [], None),
    ("text", LIB + "text.mjs", [], None),
    # nur Schritt-Verdichtung (compressSteps); Zeitwerte und CSS der Bewegung entfallen
    ("motion", LIB + "motion.mjs", [], "// Timing:"),
    ("icons", LIB + "render/shared/icons.mjs", [], None),
    (
        "nodes",
        LIB + "render/shared/nodes.mjs",
        [
            ("'+ NEW'", "'+ NEU'"),
            ("'− REMOVED'", "'− ENTFERNT'"),
            ("'~ CHANGED'", "'~ GEÄNDERT'"),
        ],
        None,
    ),
    ("edges", LIB + "render/shared/edges.mjs", [], None),
    (
        "legend",
        LIB + "render/shared/legend.mjs",
        [
            (
                "{ focal: 'Focal', backend: 'Service', store: 'Store', external: 'External', input: 'Input', optional: 'Optional', security: 'Security', muted: 'Context' }",
                "{ focal: 'Fokus', backend: 'Dienst', store: 'Speicher', external: 'Extern', input: 'Eingang', optional: 'Optional', security: 'Sicherheit', muted: 'Kontext' }",
            ),
            (
                "{ default: 'Call / flow', primary: 'Primary path', link: 'HTTP / API', async: 'Async', return: 'Return', muted: 'Secondary' }",
                "{ default: 'Aufruf / Fluss', primary: 'Hauptweg', link: 'HTTP / API', async: 'Asynchron', return: 'Rückgabe', muted: 'Nebenweg' }",
            ),
            ("(custom.title || 'Legend')", "(custom.title || 'Legende')"),
        ],
        None,
    ),
    ("route", LIB + "render/graph/route.mjs", [], None),
    (
        "graph",
        LIB + "render/graph/graph.mjs",
        [
            # Wegprüfung (nur Hinweistexte) entfällt
            ("import { checkRoutes } from './verify.mjs';\n", ""),
            ("  problems.push(...checkRoutes(nodes, edges));\n", ""),
            # Wandernde Marke (Endlos-Animation) entfällt
            ("  const chain = tokenChain(nodes, edges, byId);\n", "  const chain = null;\n"),
            # Beschriftungen auf Deutsch
            ("{ ok: 'Healthy', risk: 'At risk', legacy: 'Legacy', retire: 'Retire' }", "{ ok: 'Gesund', risk: 'Gefährdet', legacy: 'Altbestand', retire: 'Ablösen' }"),
            ("{ added: '+ New', removed: '− Removed', changed: '~ Changed' }", "{ added: '+ Neu', removed: '− Entfernt', changed: '~ Geändert' }"),
        ],
        "// One token traveling",
    ),
    ("sequence", LIB + "render/lanes/sequence.mjs", [], None),
    ("tree", LIB + "render/structure/tree.mjs", [], None),
    ("schema", LIB + "schema.mjs", [], None),
]

SCHEMAS = [
    ("graph", "graph.schema.json"),
    ("stages", "stages.schema.json"),
    ("sequence", "sequence.schema.json"),
    ("tree", "tree.schema.json"),
]

IMPORT = re.compile(r"^import \{([^}]*)\} from '([^']+)';$")
EXPORT_DECL = re.compile(r"^export (?:const|let|function|class) ([A-Za-z_$][\w$]*)")
EXPORT_LISTE = re.compile(r"^export \{([^}]*)\};$")


def lesen(wurzel: Path, rel: str) -> str:
    roh = (wurzel / rel).read_bytes()
    if hashlib.sha256(roh).hexdigest() != SHA256[rel]:
        raise SystemExit(f"Quelle weicht vom gepinnten Stand ab: {rel}")
    return roh.decode("utf-8")


def ersetzen(text: str, alt: str, neu: str, rel: str) -> str:
    if text.count(alt) != 1:
        raise SystemExit(f"Ersetzung in {rel} trifft nicht genau einmal: {alt.strip()[:60]!r}")
    return text.replace(alt, neu)


def modul(schluessel: str, rel: str, ersetzungen: list[tuple[str, str]], schnitt: str | None, wurzel: Path) -> str:
    text = lesen(wurzel, rel)
    if schnitt:
        if text.count(schnitt) != 1:
            raise SystemExit(f"Schnittmarke in {rel} nicht eindeutig: {schnitt!r}")
        text = text[: text.index(schnitt)]
    for alt, neu in ersetzungen:
        text = ersetzen(text, alt, neu, rel)
    kopf: list[str] = []
    koerper: list[str] = []
    ausfuhr: list[str] = []
    for zeile in text.splitlines():
        s = zeile.strip()
        if not s or s.startswith("//"):
            continue  # Kommentarzeilen und Leerzeilen entfallen (Größe)
        m = IMPORT.match(s)
        if m:
            namen = [n.strip() for n in m.group(1).split(",") if n.strip()]
            quelle = Path(m.group(2)).stem
            kopf.append(f"const {{ {', '.join(namen)} }} = M.{quelle};")
            continue
        if s.startswith("import "):
            raise SystemExit(f"Import in {rel} nicht verstanden: {s}")
        m = EXPORT_LISTE.match(s)
        if m:
            ausfuhr += [n.strip() for n in m.group(1).split(",") if n.strip()]
            continue
        m = EXPORT_DECL.match(s)
        if m:
            ausfuhr.append(m.group(1))
            zeile = zeile.replace("export ", "", 1)
        elif s.startswith("export "):
            raise SystemExit(f"Export in {rel} nicht verstanden: {s}")
        koerper.append(zeile)
    teile = [f"M.{schluessel} = (() => {{", *kopf, *koerper, f"return {{ {', '.join(dict.fromkeys(ausfuhr))} }};", "})();"]
    return "\n".join(teile)


def tokens(wurzel: Path) -> str:
    """Aus tokens.mjs nur die Schrifthöhen (TYPE); die Farben und das CSS stehen in ansicht.css."""
    text = lesen(wurzel, LIB + "tokens.mjs")
    m = re.search(r"^export const TYPE = (\{[^}]*\});$", text, re.M)
    if not m:
        raise SystemExit("TYPE in tokens.mjs nicht gefunden")
    return f"M.tokens = (() => {{\nconst TYPE = {m.group(1)};\nreturn {{ TYPE }};\n}})();"


def entkernen(wert, unter_properties: bool = False):
    """Schema ohne Titel und Beschreibungen (nur Text, keine Prüfregel)."""
    if isinstance(wert, dict):
        aus = {}
        for k, v in wert.items():
            if not unter_properties and k in ("title", "description") and isinstance(v, str):
                continue
            aus[k] = entkernen(v, unter_properties=(k == "properties" and not unter_properties))
        return aus
    if isinstance(wert, list):
        return [entkernen(x) for x in wert]
    return wert


def schemas(wurzel: Path) -> str:
    gemeinsam = json.loads(lesen(wurzel, SKILL + "schemas/common.schema.json"))
    aus = {}
    for name, datei in SCHEMAS:
        koerper = json.loads(lesen(wurzel, SKILL + "schemas/" + datei))
        koerper["properties"] = {**gemeinsam["properties"], **koerper["properties"]}
        aus[name] = entkernen(koerper)
    roh = json.dumps(aus, ensure_ascii=False, separators=(",", ":"))
    if " " in roh or " " in roh or "</" in roh:
        raise SystemExit("Schema enthält ein Zeichen, das im Skript nicht stehen darf")
    return f"const SCHEMAS = {roh};"


def kopfkommentar(lizenz: str) -> str:
    text = lizenz.strip()
    zeilen = "\n".join(f" * {z}".rstrip() for z in text.splitlines())
    return f"""/*
 * Vorlage „diagramm“: Diagramme aus einer kurzen JSON-Spezifikation (Graph, Sequenz, Baum).
 *
 * Herkunft: SeeCode {SEECODE_VERSION}, {SEECODE_URL}
 * Gepinnter Stand: Commit {SEECODE_COMMIT} (übernommen am {STAND}).
 * Lizenz: MIT, Copyright (c) 2026 Aryanutkarsh. Der Lizenztext steht unten und gilt für die aus SeeCode
 * übernommenen Teile dieser Datei (alles zwischen „SeeCode-Anfang“ und „SeeCode-Ende“).
 *
 * Übernommen (wörtlich, Dateien gegen SHA-256 geprüft): lib/svg, lib/text, lib/schema, render/shared/{{icons,nodes,
 * edges,legend}}, render/graph/{{graph,route}}, render/lanes/sequence, render/structure/tree und die Schemas
 * {{common,graph,stages,sequence,tree}}.
 *
 * Geändert:
 *  - Aus Node-Modulen (import/export) wurden Funktionen in einer Datei; Kommentarzeilen und Leerzeilen entfernt.
 *  - Entfernt: Seite, Betrachter, Export, Marke (Wasserzeichen), Google-Fonts-Verweise, Schrift- und Marken-Import,
 *    Bewegung (Animation, wandernde Marke), Dateizugriff, Wegprüfung (verify), alle anderen Diagrammarten.
 *  - Beschriftungen der Legende, Status und Änderungsmarken ins Deutsche (nur Texte).
 *  - Farben und Schriften kommen vom Host (ansicht.css, --color-*, --font-*); von SeeCode bleibt nur die Maßrechnung
 *    (Plex-Breiten, deshalb Breitenfaktor 1,08 für die Systemschrift).
 *  - Schemas ohne Titel und Beschreibungen; Prüfung und Darstellung im Kleber (eigener Code, ab „FYOS-Kleber“).
 *
 * Keine Abrufe: kein fetch, XHR, WebSocket, import(), eval, new Function, innerHTML. Das erzeugte SVG wird vor dem
 * Einsetzen streng geprüft (nur bekannte Elemente und Attribute, keine Verweise, keine Ereignisse).
 *
 * Neu erzeugen: python3 -I tools/seecode_einbetten/einbetten.py <SeeCode-Checkout>
 *
 * MIT License
 *
{zeilen}
 */"""


def bauen(wurzel: Path) -> str:
    lizenz = lesen(wurzel, "LICENSE")
    kleber = (Path(__file__).resolve().parent / "kleber.js").read_text(encoding="utf-8")
    teile = [
        kopfkommentar(lizenz),
        "(() => {",
        '"use strict";',
        "const M = {};",
        "/* ── SeeCode-Anfang ── */",
        tokens(wurzel),
    ]
    for schluessel, rel, ersetzungen, schnitt in MODULE:
        teile.append(modul(schluessel, rel, ersetzungen, schnitt, wurzel))
    teile.append(schemas(wurzel))
    teile.append("/* ── SeeCode-Ende ── */")
    teile.append(kleber.rstrip())
    teile.append("})();")
    return "\n".join(teile) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    wurzel = Path(argv[1]).resolve()
    ziel = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parents[2] / "hub/mcp_hub/skills/generative-ui/vorlagen/diagramm/ansicht.js"
    text = bauen(wurzel)
    if len(text) > 118_000:
        raise SystemExit(f"ansicht.js ist zu groß für gui.bauen (js höchstens 120000 Zeichen): {len(text)}")
    ziel.write_text(text, encoding="utf-8")
    print(f"{ziel}: {len(text)} Zeichen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
