#!/usr/bin/env python3
"""Doku-Vollabgleich: prueft alle Markdown-Dateien des Repos gegen den Dateibaum.

Die Sauberkeitspruefung (sauber.py) schaut auf Inhalte, diese auf den Zusammenhang: Die Doku soll nur versprechen,
was es gibt. Sie laeuft jede Nacht in der CI (.gitea/workflows/doku-nachts.yml) und auf Wunsch von Hand.

Geprueft wird jede versionierte .md-Datei (Vorlagen ausgenommen, siehe VORLAGEN) auf

  * Links: relative Links, Bilder, Referenzdefinitionen und href/src in HTML zeigen auf etwas, das es gibt; ein Anker
    (`datei.md#abschnitt`, `#abschnitt`) passt zu einer Ueberschrift der Zieldatei (Schreibweise von GitHub oder von
    Gitea/goldmark, beide gelten). Adressen mit Schema (https:, mailto:), Pfade mit fuehrendem Schraegstrich und
    Platzhalter ({..}, $..) lassen sich vom Dateibaum aus nicht pruefen und werden uebersprungen.
  * Pfade in Inline-Code (`web/src/lib/hub.ts`, `tools/`, `docker-compose.yml`): gibt es im Repo, vom Wurzelordner
    aus, vom Ordner der Datei aus oder als Endstueck eines versionierten Pfads (`plugins/skills.py` fuer
    hub/mcp_hub/plugins/skills.py). Als Pfad gilt nur ein einzelnes Wort aus Buchstaben, Ziffern und `_.-/*`, das
    einen Schraegstrich oder eine bekannte Dateiendung hat. Nicht geprueft werden (sichtbar mit --ausfuehrlich):
    Befehle und Beispiele mit Leerzeichen, Platzhalter und Optionen (< > { } $ = : @ ...), Endungen und Klassen
    (.png, .datum), URL-Pfade (/hub/call), Adressen (registry.example.com/..), Bezeichner wie Europe/Berlin oder
    text/event-stream (ohne Endung, ohne Schraegstrich am Ende, erster Teil kommt im Repo nicht vor), Pfade, die das
    Repo verlassen (../fyos-os/web), Pfade anderer Repos (fyos-agent/, fyos-plugin-..) und der Inhalt von
    Codezaeunen: dort stehen Beispiele.
    Was die Doku nennt und nicht in diesem Repo liegt (Dateien von fyos-agent oder von Plugin-Repos, Beispiele der
    Anleitung, Dateien, die erst im Betrieb entstehen), steht mit Grund in .doku/ausserhalb.txt. Eintraege, die
    nichts mehr treffen, meldet das Werkzeug selbst, damit die Liste nicht verrottet.
  * README.md: die festen Abschnitte, die alle READMEs des Repos heute einhalten (siehe pruefe_readme), und fuer die
    Wurzel-README die vier Abschnitte des Wegweisers.
  * ungeschlossene Codezaeune: sie verschluckten den Rest der Datei und damit jeden weiteren Befund.

Aufruf:
  python3 tools/doku_pruefen.py [WURZEL] [--json] [--ausfuehrlich]

WURZEL ist standardmaessig das Repo, in dem dieses Skript liegt. Exitcode 0 ohne Befund, 1 mit Befund, 2 bei falschem
Aufruf. --json gibt die Befunde als JSON aus, --ausfuehrlich zusaetzlich jeden uebersprungenen Pfad mit Grund.
"""

from __future__ import annotations

import argparse
import bisect
import fnmatch
import json
import posixpath
import re
import subprocess
import sys
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- Festlegungen

# Vorlagen werden erst beim Erzeugen gerendert ({{platzhalter}}); ihre Pfade gelten im Zielordner, nicht in diesem Repo.
VORLAGEN = ("installer/fyos_installer/vorlagen/",)

# Pfade, die mit diesen Namen beginnen, liegen in einem anderen Repo und sind von hier aus nicht zu pruefen.
ANDERE_REPOS = ("fyos-agent", "fyos-plugin-", "fyos-privat")

# Das Repo selbst heisst fyos-os: `fyos-os/web/...` ist `web/...`.
REPO_NAME = "fyos-os"

# Ohne Schraegstrich gilt ein Wort nur als Pfad, wenn es eine dieser Endungen oder einen dieser Namen hat.
ENDUNGEN = frozenset(
    "py md yaml yml json json5 js mjs cjs ts tsx jsx astro css html svg png jpg jpeg webp gif toml sh conf txt ini cfg "
    "lock template tmpl example sql mdx".split()
)
DATEINAMEN = frozenset({"Dockerfile", "Makefile", "LICENSE", "Procfile"})

# Was die Doku nennt und nicht in diesem Repo liegt (eine Zeile je Name oder Muster, dahinter nach # der Grund).
AUSNAHMEN_DATEI = ".doku/ausserhalb.txt"

# Feste Abschnitte (aus dem Bestand abgeleitet, siehe pruefe_readme).
WURZEL_ABSCHNITTE = ("Was hier liegt", "Loslegen", "Erweitern", "Entwickeln")
PRUEF_ABSCHNITT = ("tests", "entwickeln")  # Anfang einer H2 in jeder README

CODEZAUN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
UEBERSCHRIFT = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
KOMMENTAR = re.compile(r"<!--.*?-->", re.S)
CODESPAN = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.S)
LINK_ANFANG = re.compile(r"\]\(")
LINK_ZIEL = re.compile(
    r"""\s*(<[^>\n]*>|[^\s()]*(?:\([^\s()]*\)[^\s()]*)*)(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?\s*\)"""
)
REFERENZ = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*(<[^>\n]*>|\S+)", re.M)  # nicht [^1]: (Fussnote)
HTML_ZIEL = re.compile(r"""\b(?:href|src)\s*=\s*(?:"([^"\n]*)"|'([^'\n]*)')""", re.I)
HTML_ANKER = re.compile(r"""\b(?:id|name)\s*=\s*(?:"([^"\n]*)"|'([^'\n]*)')""", re.I)
SCHEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
PFAD_ZEICHEN = re.compile(r"^[A-Za-z0-9_./*\-]+$")


@dataclass(frozen=True)
class Befund:
    datei: str
    zeile: int  # 1-basiert, 0 = die ganze Datei
    regel: str  # link | anker | pfad | ausnahme | readme | zaun | lesen
    text: str

    def __str__(self) -> str:
        ort = f"{self.datei}:{self.zeile}" if self.zeile else self.datei
        return f"{ort}: [{self.regel}] {self.text}"


@dataclass
class Baum:
    """Alle Dateien und Ordner, die ein frischer Checkout enthielte (Pfade mit /, ohne fuehrenden Schraegstrich)."""

    dateien: set[str]
    ordner: set[str]
    # jedes Endstueck ab einer Pfadgrenze (b/c.py, c.py), getrennt nach Dateien und Ordnern zusammen und nur Ordnern
    endstuecke: set[str] = field(default_factory=set)
    endstuecke_ordner: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for quelle, ziel in ((self.dateien | self.ordner, self.endstuecke), (self.ordner, self.endstuecke_ordner)):
            for p in quelle:
                teile = p.split("/")
                ziel.update("/".join(teile[i:]) for i in range(len(teile)))

    def gibt_es(self, pfad: str, ordner: bool = False) -> bool:
        return pfad in self.ordner if ordner else pfad in self.dateien or pfad in self.ordner

    def passt(self, muster: str, ordner: bool = False, endstueck: bool = False) -> bool:
        """Gibt es einen Pfad, der zum Muster (mit * als Platzhalter) passt? Ohne * genau dieser Pfad.

        Mit endstueck darf der Pfad davor noch Ordner haben (`b/c.py` passt auf `a/b/c.py`).
        """
        if "*" not in muster:
            if endstueck:
                return muster in (self.endstuecke_ordner if ordner else self.endstuecke)
            return self.gibt_es(muster, ordner)
        quelle = self.ordner if ordner else self.dateien | self.ordner
        regex = re.compile(fnmatch.translate(("*/" if endstueck else "") + muster))
        return any(regex.match(p) for p in quelle)


def dateibaum(wurzel: Path) -> Baum:
    """Was ein frischer Checkout enthaelt: versionierte Dateien (git), sonst alles ausser Erzeugtem."""
    try:
        aus = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=wurzel, capture_output=True, check=True
        ).stdout.decode("utf-8", "replace")
        pfade = [p for p in aus.split("\0") if p and (wurzel / p).is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        erzeugt = {".git", "node_modules", "dist", ".venv", "__pycache__", ".astro", ".pytest_cache", "build"}
        pfade = [
            p.relative_to(wurzel).as_posix()
            for p in wurzel.rglob("*")
            if p.is_file() and not erzeugt & set(p.relative_to(wurzel).parts)
        ]
    ordner: set[str] = set()
    for p in pfade:
        teile = p.split("/")
        ordner.update("/".join(teile[:i]) for i in range(1, len(teile)))
    return Baum(set(pfade), ordner)


@dataclass
class Ausnahmen:
    """Namen, die die Doku nennt und die nicht in diesem Repo liegen.

    Ein Muster mit / am Ende meint den Ordner und alles darin, jedes andere gilt als fnmatch-Muster (* ist beliebig
    viel Text). Verglichen wird der Name ohne ./ und ohne fyos-os/ davor und ohne / am Ende.
    """

    eintraege: list[tuple[int, str]] = field(default_factory=list)  # (Zeile in der Datei, Muster)
    genutzt: set[int] = field(default_factory=set)

    def trifft(self, pfad: str) -> bool:
        for nr, muster in self.eintraege:
            if muster.endswith("/"):
                passt = pfad == muster[:-1] or pfad.startswith(muster)
            else:
                passt = fnmatch.fnmatchcase(pfad, muster)
            if passt:
                self.genutzt.add(nr)
                return True
        return False

    def ungenutzt(self) -> list[tuple[int, str]]:
        return [(nr, m) for nr, m in self.eintraege if nr not in self.genutzt]


def lade_ausnahmen(wurzel: Path) -> Ausnahmen:
    try:
        text = (wurzel / AUSNAHMEN_DATEI).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return Ausnahmen()
    eintraege = []
    for nr, zeile in enumerate(text.splitlines(), 1):
        muster = zeile.split("#", 1)[0].strip()
        if muster:
            eintraege.append((nr, muster))
    return Ausnahmen(eintraege)


# ---------------------------------------------------------------- Markdown zerlegen


@dataclass
class Ueberschrift:
    ebene: int
    text: str  # wie im Dokument, ohne die #-Zeichen
    zeile: int


@dataclass
class Dokument:
    pfad: str
    zeilen: list[str]  # Originalzeilen
    prosa: str  # Text ohne Zaeune und Kommentare (gleiche Zeilenzahl), Codespans noch enthalten
    ueberschriften: list[Ueberschrift]
    befunde: list[Befund]
    _starts: list[int] = field(default_factory=list)

    def zeile_von(self, versatz: int) -> int:
        if not self._starts:
            pos = 0
            for z in self.prosa.split("\n"):
                self._starts.append(pos)
                pos += len(z) + 1
        return bisect.bisect_right(self._starts, versatz)


def zerlegen(pfad: str, text: str) -> Dokument:
    """Trennt Prosa von Codezaeunen, sammelt Ueberschriften (ATX) und meldet ungeschlossene Zaeune."""
    zeilen = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    prosa: list[str] = []
    befunde: list[Befund] = []
    zaun: tuple[str, int, int] | None = None  # (Zeichen, Laenge, Startzeile)
    kopf = 0  # Zeilen des Front-Matters am Anfang (--- key: wert --- ): kein Markdown
    if len(zeilen) > 1 and zeilen[0].strip() == "---" and re.match(r"[A-Za-z_][\w-]*\s*:", zeilen[1]):
        ende = next((i for i, z in enumerate(zeilen[1:], 1) if z.strip() in ("---", "...")), None)
        kopf = 0 if ende is None else ende + 1
    for nr, z in enumerate(zeilen, 1):
        m = CODEZAUN.match(z)
        if nr <= kopf:
            prosa.append("")
        elif zaun is not None:
            if m and m.group(1)[0] == zaun[0] and len(m.group(1)) >= zaun[1] and not m.group(2).strip():
                zaun = None
            prosa.append("")
        elif m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            zaun = (m.group(1)[0], len(m.group(1)), nr)
            prosa.append("")
        else:
            prosa.append(z)
    if zaun is not None:
        befunde.append(Befund(pfad, zaun[2], "zaun", "Codezaun wird nie geschlossen; der Rest der Datei bleibt ungeprueft"))
    roh = "\n".join(prosa)
    ohne_kommentare = KOMMENTAR.sub(lambda m: re.sub(r"[^\n]", "", m.group(0)), roh)
    ueberschriften = []
    for nr, z in enumerate(ohne_kommentare.split("\n"), 1):
        m = UEBERSCHRIFT.match(z)
        if m:
            ueberschriften.append(Ueberschrift(len(m.group(1)), (m.group(2) or "").strip(), nr))
    return Dokument(pfad, zeilen, ohne_kommentare, ueberschriften, befunde)


def ohne_codespans(prosa: str) -> str:
    """Codespans durch Leerzeichen ersetzen (Zeilenumbrueche bleiben), damit Links darin nicht zaehlen."""
    return CODESPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), prosa)


def codespans(prosa: str) -> list[tuple[int, str]]:
    """(Versatz, Inhalt) jedes Inline-Codespans; Zeilenumbrueche im Inhalt werden zu Leerzeichen."""
    ergebnis = []
    for m in CODESPAN.finditer(prosa):
        inhalt = m.group(2).replace("\n", " ")
        if inhalt.startswith(" ") and inhalt.endswith(" ") and inhalt.strip():
            inhalt = inhalt[1:-1]
        ergebnis.append((m.start(), inhalt))
    return ergebnis


# ---------------------------------------------------------------- Anker


def _klartext(ueberschrift: str) -> str:
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", ueberschrift)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[`*]+", "", t).strip()


def slug_github(text: str) -> str:
    s = unicodedata.normalize("NFC", _klartext(text)).lower()
    return re.sub(r"[^\w\- ]", "", s).replace(" ", "-")


def slug_goldmark(text: str) -> str:
    """Gitea (goldmark): nur ASCII-Buchstaben und Ziffern bleiben, Leerzeichen, - und _ werden zu -."""
    aus = []
    for ch in _klartext(text):
        if ord(ch) > 127:
            continue
        if ch.isalnum():
            aus.append(ch.lower())
        elif ch.isspace() or ch in "-_":
            aus.append("-")
    return "".join(aus)


def anker_von(dok: Dokument) -> set[str]:
    """Alle Anker, die ein Link auf diese Datei treffen darf (beide Schreibweisen, doppelte mit -1, -2 ..)."""
    anker: set[str] = set()
    zaehler: dict[tuple[str, str], int] = {}
    for u in dok.ueberschriften:
        for art, slug in (("github", slug_github(u.text)), ("goldmark", slug_goldmark(u.text))):
            n = zaehler.get((art, slug), 0)
            zaehler[(art, slug)] = n + 1
            anker.add(slug if n == 0 else f"{slug}-{n}")
    for m in HTML_ANKER.finditer(dok.prosa):
        anker.add(m.group(1) or m.group(2))
    return {a.lower() for a in anker}


# ---------------------------------------------------------------- Links


def _link_ziele(dok: Dokument) -> list[tuple[int, str]]:
    """(Zeile, Ziel) aller Links, Bilder, Referenzdefinitionen und href/src ausserhalb von Code."""
    prosa = ohne_codespans(dok.prosa)
    ziele: list[tuple[int, str]] = []
    for m in LINK_ANFANG.finditer(prosa):
        ziel = LINK_ZIEL.match(prosa, m.end())
        if ziel:
            ziele.append((dok.zeile_von(m.end()), ziel.group(1).strip("<>")))
    for m in REFERENZ.finditer(prosa):
        ziele.append((dok.zeile_von(m.start(1)), m.group(1).strip("<>")))
    for m in HTML_ZIEL.finditer(prosa):
        ziele.append((dok.zeile_von(m.start()), m.group(1) if m.group(1) is not None else m.group(2)))
    return ziele


def _normal(ordner: str, pfad: str) -> str | None:
    """Pfad relativ zu ordner aufloesen; None, wenn er das Repo verlaesst."""
    ziel = posixpath.normpath(posixpath.join(ordner, pfad)) if ordner else posixpath.normpath(pfad)
    return None if ziel == ".." or ziel.startswith("../") else ("" if ziel == "." else ziel)


def pruefe_links(dok: Dokument, baum: Baum, anker_cache: dict[str, set[str] | None], lesen) -> list[Befund]:
    befunde: list[Befund] = []
    ordner = posixpath.dirname(dok.pfad)
    for zeile, ziel in _link_ziele(dok):
        if not ziel or SCHEMA.match(ziel) or ziel.startswith(("/", "{", "$", "<", "%7B")):
            continue  # Adresse mit Schema, Server-Pfad oder Platzhalter: vom Dateibaum aus nicht zu pruefen
        pfad_teil, _, anker = ziel.partition("#")
        pfad_teil = urllib.parse.unquote(pfad_teil.split("?", 1)[0])
        anker = urllib.parse.unquote(anker)
        if pfad_teil:
            aufgeloest = _normal(ordner, pfad_teil)
            if aufgeloest is None:
                befunde.append(Befund(dok.pfad, zeile, "link", f"Link `{ziel}` zeigt aus dem Repo hinaus"))
                continue
            if aufgeloest and not baum.gibt_es(aufgeloest, ordner=pfad_teil.endswith("/")):
                befunde.append(Befund(dok.pfad, zeile, "link", f"toter Link `{ziel}`: {aufgeloest} gibt es nicht"))
                continue
            ziel_datei = aufgeloest
        else:
            ziel_datei = dok.pfad
        if anker and ziel_datei.lower().endswith(".md") and ziel_datei in baum.dateien:
            if ziel_datei not in anker_cache:
                text = lesen(ziel_datei)
                anker_cache[ziel_datei] = None if text is None else anker_von(zerlegen(ziel_datei, text))
            vorhanden = anker_cache[ziel_datei]
            if vorhanden is not None and anker.lower() not in vorhanden:
                befunde.append(Befund(dok.pfad, zeile, "anker", f"Anker `#{anker}` gibt es in {ziel_datei} nicht"))
    return befunde


# ---------------------------------------------------------------- Pfade in Inline-Code


def _hat_endung(wort: str) -> bool:
    return wort in DATEINAMEN or ("." in wort.strip(".") and wort.rsplit(".", 1)[-1].lower() in ENDUNGEN)


def normalisiert(pfad: str) -> str:
    """Der Pfad ohne ./, ohne den Repo-Namen davor und ohne Schraegstrich am Ende."""
    q = pfad.rstrip("/")
    while q.startswith("./"):
        q = q[2:]
    return q[len(REPO_NAME) + 1:] if q.startswith(REPO_NAME + "/") else q


def pfad_behauptung(span: str) -> tuple[str | None, str]:
    """(Pfad, "") wenn der Span einen Pfad behauptet, sonst (None, Grund)."""
    s = span.strip()
    if not s:
        return None, "leer"
    if re.search(r"\s", s):
        return None, "Befehl oder Beispiel (Leerzeichen)"
    if s.startswith("/"):
        return None, "URL-Pfad oder absoluter Pfad"
    if not PFAD_ZEICHEN.match(s):
        return None, "Platzhalter, Option oder Adresse (Sonderzeichen)"
    teile = s.rstrip("/").split("/")
    if any(t and set(t) == {"."} and t not in (".", "..") for t in teile):
        return None, "Auslassung (...)"
    if len(teile) == 1 and not s.endswith("/"):
        if teile[0].startswith("."):
            return None, "Endung, Klasse oder Dotfile"
        if not _hat_endung(teile[0]):
            return None, "kein Pfad"
    if teile[0].startswith(ANDERE_REPOS):
        return None, "Pfad eines anderen Repos"
    if len(teile) > 1 and "." in teile[0].strip(".") and teile[0].rsplit(".", 1)[-1].lower() not in ENDUNGEN:
        return None, "Adresse eines Servers"
    return s, ""


def ist_bezeichner(pfad: str, baum: Baum) -> bool:
    """Wort mit Schraegstrich ohne Endung (Europe/Berlin, text/event-stream), dessen erster Teil im Repo fehlt."""
    q = normalisiert(pfad)
    teile = q.split("/")
    return (
        len(teile) > 1
        and not pfad.endswith("/")
        and not pfad.startswith(".")
        and not _hat_endung(teile[-1])
        and teile[0] not in baum.endstuecke
        and "*" not in teile[0]
    )


def pfad_vorhanden(pfad: str, datei: str, baum: Baum) -> bool | None:
    """True/False, ob es den Pfad gibt; None, wenn er das Repo verlaesst (Geschwister-Checkout, nicht pruefbar)."""
    ist_ordner = pfad.endswith("/")
    p = normalisiert(pfad)
    if p == REPO_NAME:
        return True
    ordner = posixpath.dirname(datei)
    kandidaten = [k for k in (_normal("", p), _normal(ordner, p)) if k is not None]
    if not kandidaten:
        return None
    if "" in kandidaten or any(baum.passt(k, ordner=ist_ordner) for k in kandidaten):
        return True  # "" ist die Wurzel des Repos selbst (`./`, `..` aus einem Unterordner)
    if pfad.startswith(("./", "../")):
        return False  # ausdruecklich relativ: genau dieser Ort, kein Endstueck-Raten
    return baum.passt(p, ordner=ist_ordner, endstueck=True)


def pruefe_pfade(dok: Dokument, baum: Baum, ausnahmen: Ausnahmen) -> tuple[list[Befund], list[str]]:
    """(Befunde, uebersprungene Spans mit Grund)."""
    befunde: list[Befund] = []
    uebersprungen: list[str] = []
    for versatz, span in codespans(dok.prosa):
        zeile = dok.zeile_von(versatz)
        pfad, grund = pfad_behauptung(span)
        if pfad is None:
            if grund not in ("leer", "kein Pfad"):
                uebersprungen.append(f"{dok.pfad}:{zeile}: `{span}` ({grund})")
            continue
        if ist_bezeichner(pfad, baum):
            uebersprungen.append(f"{dok.pfad}:{zeile}: `{span}` (Bezeichner, kein Pfad dieses Repos)")
            continue
        da = pfad_vorhanden(pfad, dok.pfad, baum)
        if da is None:
            uebersprungen.append(f"{dok.pfad}:{zeile}: `{span}` (verlaesst das Repo)")
        elif not da:
            if ausnahmen.trifft(normalisiert(pfad)):
                uebersprungen.append(f"{dok.pfad}:{zeile}: `{span}` (steht in {AUSNAHMEN_DATEI})")
            else:
                befunde.append(Befund(
                    dok.pfad, zeile, "pfad",
                    f"`{span}` gibt es im Repo nicht (gehoert es zu einem anderen Repo oder entsteht es erst im Betrieb: "
                    f"{AUSNAHMEN_DATEI})",
                ))
    return befunde, uebersprungen


# ---------------------------------------------------------------- README


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _klartext(text)).strip().lower()


def pruefe_readme(dok: Dokument) -> list[Befund]:
    """Die festen Abschnitte, die alle READMEs dieses Repos heute einhalten:

    * genau eine H1, und sie steht vor jeder anderen Ueberschrift,
    * zwischen der H1 und der naechsten Ueberschrift steht Text (was das hier ist),
    * ein H2, das mit "Tests" oder "Entwickeln" beginnt (wie man es prueft),
    * die Wurzel-README zusaetzlich: "Was hier liegt", "Loslegen", "Erweitern", "Entwickeln" (der Wegweiser).
    """
    befunde: list[Befund] = []
    ue = dok.ueberschriften
    h1 = [u for u in ue if u.ebene == 1]
    if len(h1) != 1:
        zeile = h1[1].zeile if len(h1) > 1 else 0
        befunde.append(Befund(dok.pfad, zeile, "readme", f"genau eine H1 (# Titel) erwartet, gefunden: {len(h1)}"))
    elif ue[0] is not h1[0]:
        befunde.append(Befund(dok.pfad, ue[0].zeile, "readme", "die H1 muss die erste Ueberschrift sein"))
    else:
        naechste = ue[1].zeile if len(ue) > 1 else len(dok.zeilen) + 1
        if not any(z.strip() for z in dok.zeilen[h1[0].zeile:naechste - 1]):
            befunde.append(Befund(dok.pfad, h1[0].zeile, "readme", "nach der H1 fehlt ein Einleitungstext vor dem ersten Abschnitt"))
    h2 = [_norm(u.text) for u in ue if u.ebene == 2]
    if not any(t.startswith(PRUEF_ABSCHNITT) for t in h2):
        befunde.append(Befund(
            dok.pfad, 0, "readme", 'Abschnitt "Tests" oder "Entwickeln" (H2) fehlt; alle READMEs des Repos haben ihn'
        ))
    if posixpath.dirname(dok.pfad) == "":
        for name in WURZEL_ABSCHNITTE:
            if _norm(name) not in h2:
                befunde.append(Befund(dok.pfad, 0, "readme", f'Abschnitt "{name}" (H2) fehlt in der Wurzel-README'))
    return befunde


# ---------------------------------------------------------------- Zusammenspiel


def markdown_dateien(baum: Baum) -> list[str]:
    return sorted(p for p in baum.dateien if p.lower().endswith(".md") and not p.startswith(VORLAGEN))


def pruefen(wurzel: Path, uebersprungen: list[str] | None = None, baum: Baum | None = None) -> list[Befund]:
    """Alle Befunde der Markdown-Dateien unter wurzel. Uebersprungene Pfade (mit Grund) kommen in `uebersprungen`."""
    baum = baum or dateibaum(wurzel)
    ausnahmen = lade_ausnahmen(wurzel)
    gelesen: dict[str, str | None] = {}

    def lesen(pfad: str) -> str | None:
        if pfad not in gelesen:
            try:
                gelesen[pfad] = (wurzel / pfad).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                gelesen[pfad] = None
        return gelesen[pfad]

    befunde: list[Befund] = []
    anker_cache: dict[str, set[str] | None] = {}
    for pfad in markdown_dateien(baum):
        text = lesen(pfad)
        if text is None:
            befunde.append(Befund(pfad, 0, "lesen", "nicht als UTF-8 lesbar"))
            continue
        dok = zerlegen(pfad, text)
        befunde += dok.befunde
        befunde += pruefe_links(dok, baum, anker_cache, lesen)
        pfad_befunde, pfad_uebersprungen = pruefe_pfade(dok, baum, ausnahmen)
        befunde += pfad_befunde
        if uebersprungen is not None:
            uebersprungen += pfad_uebersprungen
        if posixpath.basename(pfad).lower() == "readme.md":
            befunde += pruefe_readme(dok)
    for nr, muster in ausnahmen.ungenutzt():
        befunde.append(Befund(
            AUSNAHMEN_DATEI, nr, "ausnahme", f"`{muster}` wird in keiner Datei mehr gebraucht; Zeile streichen"
        ))
    return sorted(befunde, key=lambda b: (b.datei, b.zeile, b.regel, b.text))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="doku_pruefen.py", description="Doku-Vollabgleich: Links, Pfade, feste Abschnitte")
    ap.add_argument("wurzel", nargs="?", default=str(Path(__file__).resolve().parent.parent), help="Wurzel des Repos")
    ap.add_argument("--json", action="store_true", help="Befunde als JSON ausgeben")
    ap.add_argument("--ausfuehrlich", action="store_true", help="auch uebersprungene Pfade mit Grund zeigen")
    args = ap.parse_args(argv)
    wurzel = Path(args.wurzel).resolve()
    if not wurzel.is_dir():
        print(f"doku_pruefen: {args.wurzel} ist kein Ordner", file=sys.stderr)
        return 2
    uebersprungen: list[str] | None = [] if args.ausfuehrlich else None
    baum = dateibaum(wurzel)
    befunde = pruefen(wurzel, uebersprungen, baum)
    if args.json:
        daten: dict[str, object] = {"wurzel": wurzel.name, "befunde": [asdict(b) for b in befunde]}
        if uebersprungen is not None:
            daten["uebersprungen"] = uebersprungen
        print(json.dumps(daten, ensure_ascii=False, indent=1))
    else:
        for b in befunde:
            print(b)
        for u in uebersprungen or []:
            print("uebersprungen " + u)
    print(
        f"doku_pruefen: {len(befunde)} Befund(e) in {len(markdown_dateien(baum))} Markdown-Datei(en) von {wurzel.name}",
        file=sys.stderr,
    )
    return 1 if befunde else 0


if __name__ == "__main__":
    sys.exit(main())
