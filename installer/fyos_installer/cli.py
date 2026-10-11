"""Kommandozeile: Web-Assistent (Standard), --tui oder ohne Oberfläche mit --auswahl."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable

from . import __version__, abnahme as abn, ausfuehren as ausf, erzeugen, reife, stufen
from .katalog import Katalog, KatalogFehler, lade_standard

BESCHREIBUNG = """\
FYOS einrichten. Ohne Argumente startet ein Assistent im Browser (nur auf diesem Rechner erreichbar).

Beispiele:
  fyos-install                         Web-Assistent
  fyos-install --tui                   Textoberfläche (pip install "fyos-installer[tui]")
  fyos-install --auswahl kern,agent --ziel compose --verzeichnis ./fyos --trocken
  fyos-install --auswahl kern,agent,kalender --ziel k8s --stufe termine=grund --trocken
                                       Stufe je Fähigkeit umstellen (Vorgabe: Kubernetes Ausbau, Compose Grund)
  fyos-install --abnahme http://localhost:8080     Abnahme einer laufenden Installation
  fyos-install --abnahme http://localhost:8080 --kanaele telegram    ... und: ist der Chat-Kanal im Agenten aktiv?

Rückgabewerte: 0 gut, 1 Installation oder Start gescheitert, 2 falsche Eingabe, 3 FYOS läuft, aber die Abnahme
ist nicht bestanden.
"""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fyos-install", description=BESCHREIBUNG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"fyos-install {__version__}")
    p.add_argument("--tui", action="store_true", help="Textoberfläche statt Browser (braucht Textual)")
    p.add_argument("--auswahl", help="Bausteine, durch Komma getrennt (schaltet in den Modus ohne Oberfläche)")
    p.add_argument("--ziel", choices=list(erzeugen.ZIELE), help="compose, k8s oder dateien (Vorgabe ohne Oberfläche: compose)")
    p.add_argument("--antworten", metavar="DATEI", help="YAML mit persona, modell, felder, optionen, stufen")
    p.add_argument("--stufe", action="append", default=[], metavar="FÄHIGKEIT=STUFE",
                   help="Stufe einer Fähigkeit: grund, ausbau oder aus (mehrfach möglich; Fähigkeiten zeigt --liste). "
                   "Ohne Angabe gilt die Vorgabe der Bauart: Kubernetes Ausbau, Compose Grund")
    p.add_argument("--verzeichnis", default=None, metavar="ORDNER", help="Zielordner (Vorgabe: ./fyos)")
    p.add_argument("--trocken", action="store_true", help="nur zeigen, was entstünde; nichts schreiben, nichts starten")
    p.add_argument("--ja", action="store_true", help="ohne Rückfrage ausführen")
    p.add_argument("--katalog", action="append", default=[], metavar="URL|DATEI", help="zusätzlicher Katalog (mehrfach möglich)")
    p.add_argument("--ohne-plugin-kataloge", action="store_true", help="Kataloge installierter Plugin-Pakete nicht einlesen")
    p.add_argument("--liste", action="store_true", help="Bausteine auflisten und beenden")
    p.add_argument("--abnahme", metavar="ADRESSE",
                   help="nur die Abnahme gegen eine laufende Installation (Adresse der Shell, zum Beispiel http://localhost:8080)")
    p.add_argument("--kanaele", metavar="LISTE",
                   help="mit --abnahme: Chat-Kanäle (matrix, telegram, whatsapp), die im Agenten aktiv sein müssen; "
                   "fragt den Agenten per `docker compose exec` im Ordner --verzeichnis (Vorgabe: hier)")
    p.add_argument("--port", type=int, default=0, help="Port des Web-Assistenten (Vorgabe: zufällig)")
    p.add_argument("--kein-browser", action="store_true", help="Browser nicht automatisch öffnen")
    return p


def zeige_liste(katalog: Katalog, aus: Callable[[str], None] = print) -> None:
    for b in katalog:
        marke = "Pflicht" if b.pflicht else b.art
        aus(f"{b.id:<16} [{marke}] {b.titel}: {b.kurz}")
    if katalog.faehigkeiten:
        aus("")
        aus("Fähigkeiten (Stufe wählen mit --stufe FÄHIGKEIT=grund|ausbau|aus):")
        for zeile in stufen.beschreibe_katalog(katalog):
            aus(f"  {zeile}")


def zeige_plan(plan: erzeugen.Plan, aus: Callable[[str], None] = print) -> None:
    aus(f"Ziel: {erzeugen.ZIELE[plan.ziel]}")
    aus("Bausteine: " + ", ".join(plan.auswahl))
    aus(f"Zielordner: {plan.verzeichnis}")
    if plan.stufen:
        aus("Stufe je Fähigkeit (Vorgabe nach Bauart, umstellbar mit --stufe FÄHIGKEIT=grund|ausbau|aus):")
        for zeile in stufen.zeilen(plan.stufen):
            aus(f"  {zeile}")
    if plan.reife:
        for zeile in reife.zeilen(plan.reife):
            aus(zeile)
    aus("Dateien:")
    for d in plan.dateien:
        aus(f"  {d.pfad}  ({oct(d.modus)[2:]})  {d.beschreibung}")
    aus("Befehle:")
    for b in plan.befehle:
        aus(f"  {b}")
    for hinweis in plan.hinweise:
        aus(f"Hinweis: {hinweis}")


def mit_stufen(antworten: dict, angaben: list[str]) -> dict:
    """Legt die Angaben von `--stufe FÄHIGKEIT=STUFE` über `stufen:` der Antwortdatei (die Option gewinnt)."""
    if not angaben:
        return antworten
    gewaehlt = dict(antworten.get("stufen") or {}) if isinstance(antworten.get("stufen"), dict) else {}
    for angabe in angaben:
        name, gleich, stufe = angabe.partition("=")
        if not gleich or not name.strip() or not stufe.strip():
            raise ValueError(f"--stufe {angabe!r}: erwartet FÄHIGKEIT=STUFE, zum Beispiel termine=grund")
        gewaehlt[name.strip()] = stufe.strip()
    return {**antworten, "stufen": gewaehlt}


def ohne_oberflaeche(args: argparse.Namespace, katalog: Katalog) -> int:
    ids = [a.strip() for a in args.auswahl.split(",") if a.strip()]
    try:
        antworten = erzeugen.lade_antworten(args.antworten) if args.antworten else {}
    except ValueError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2
    try:
        antworten = mit_stufen(antworten, args.stufe)
    except ValueError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2
    plan = erzeugen.erstelle_plan(katalog, ids, args.ziel or "compose", antworten, args.verzeichnis or "./fyos")
    if not plan.ok:
        print("Das geht so nicht:", file=sys.stderr)
        for f in plan.fehler:
            print(f"  - {f}", file=sys.stderr)
        return 2
    zeige_plan(plan)
    if args.trocken:
        print("Trocken: nichts wurde geschrieben oder gestartet.")
        return 0
    if not args.ja:
        if not sys.stdin.isatty():
            print("Ohne Terminal bitte --ja angeben (oder --trocken zum Ansehen).", file=sys.stderr)
            return 2
        if input("Dateien schreiben" + (" und starten" if plan.ausfuehrbar else "") + "? [j/N] ").strip().lower() not in ("j", "ja", "y"):
            print("Abgebrochen.")
            return 1
    for pfad in erzeugen.schreiben(plan):
        print(f"geschrieben: {pfad}")
    if plan.ausfuehrbar:
        erg = ausf.ausfuehren(plan, print)
        if not erg.ok:
            return 1
        return 3 if erg.nicht_abgenommen else 0
    print("Fertig. Die nächsten Schritte stehen in ANLEITUNG.md im Zielordner.")
    return 0


def nur_abnahme(
    adresse: str, aus: Callable[[str], None] = print, kanaele: str | None = None, verzeichnis: str | None = None,
) -> int:
    """`--abnahme`: die Abnahme gegen eine laufende Installation, ohne Katalog und ohne etwas zu schreiben. Mit
    `kanaele` fragt sie auch den Agenten, ob die genannten Chat-Kanäle aktiv sind."""
    namen = [k.strip() for k in (kanaele or "").split(",") if k.strip()]
    unbekannt = [k for k in namen if k not in abn.KANAL_TITEL]
    if unbekannt:
        print(f"Fehler: unbekannter Kanal {', '.join(unbekannt)} (erlaubt: {', '.join(abn.KANAL_TITEL)})", file=sys.stderr)
        return 2
    try:
        ergebnis = abn.pruefen(adresse)
    except ValueError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 2
    if namen:
        ergebnis.kanaele = abn.kanal_proben(
            {k: True for k in namen}, abn.kanal_abfrage_compose(verzeichnis or "."))
    for zeile in ergebnis.zeilen():
        aus(zeile)
    return 0 if ergebnis.bestanden else 3


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.abnahme is not None:
        return nur_abnahme(args.abnahme, kanaele=args.kanaele, verzeichnis=args.verzeichnis)
    try:
        katalog = lade_standard(args.katalog, plugins=not args.ohne_plugin_kataloge)
    except KatalogFehler as e:
        print(f"Katalog fehlerhaft:\n{e}", file=sys.stderr)
        return 2
    if args.liste:
        zeige_liste(katalog)
        return 0
    if args.auswahl is not None:
        return ohne_oberflaeche(args, katalog)
    if args.tui:
        try:
            tui = importlib.import_module("fyos_installer.tui")
        except ImportError:
            print(
                "Die Textoberfläche braucht Textual. Installiere es mit:\n"
                '  pip install "fyos-installer[tui]"        (optional Bilder: "fyos-installer[tui,bilder]")\n'
                "Oder nutze den Web-Assistenten (fyos-install) bzw. --auswahl.",
                file=sys.stderr,
            )
            return 2
        return tui.starte(katalog, verzeichnis=args.verzeichnis or "./fyos")
    from . import web

    return web.starte(katalog, port=args.port, browser=not args.kein_browser, verzeichnis=args.verzeichnis or "fyos")
