#!/usr/bin/env python3
"""Nachtauftrag: ein Auftrag, der nachts läuft und morgens in der Shell meldet (Beispiel „Notizen ordnen“).

Der Agent legt keine Zeitpläne für sich selbst an: Ein Nachtauftrag ist eine Entscheidung des Besitzers. Dieses
Werkzeug legt ihn als nativen Cron-Auftrag in OpenClaw an (`openclaw cron add`, innerhalb des Agenten-Containers) und
ruft zum Schluss selbst `os.mitteilen` im Hub auf. Ist morgens noch niemand an der Shell, wartet die Mitteilung (bis zu
24 h) und erscheint mit der Uhrzeit der Entstehung, sobald die Shell geöffnet wird (docs/NACHTARBEIT.md).

Aufruf (der Agent läuft in Compose als Dienst `agent`, in Kubernetes als Pod `agent-0`):

    python3 tools/nachtauftrag.py                                   # Compose, täglich 03:00
    python3 tools/nachtauftrag.py --in "kubectl -n fyos exec agent-0 --" --um 02:30
    python3 tools/nachtauftrag.py --jetzt                           # anlegen und sofort einmal laufen lassen
    python3 tools/nachtauftrag.py --entfernen
    python3 tools/nachtauftrag.py --trocken                         # nur zeigen, was gerufen würde

Wiederholbar: Der Auftrag trägt einen festen Schlüssel (`--declaration-key`); gibt es ihn schon, wird er nicht noch
einmal angelegt (hat er einen älteren Auftragstext, wird nur der Text nachgezogen). Exitcode 0 bei Erfolg, 1 bei einem Fehler des Agenten, 2 bei falschem Aufruf.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from typing import Any, Callable

SCHLUESSEL = "fyos:nachtauftrag:notizen"
NAME = "Nachtauftrag: Notizen ordnen"
BESCHREIBUNG = "Sichtet nachts die Notizen und meldet morgens in der Shell (os.mitteilen). Angelegt von tools/nachtauftrag.py."
VORGABE_IN = "docker compose exec -T agent"
VORGABE_UM = "03:00"
FRIST_S = 900  # so lange darf ein Lauf höchstens dauern

#: Das Hub-Werkzeug, aus dem der Auftrag die Notizen liest (Notizzettel, hub/mcp_hub/plugins/beispiel_app.py).
LESE_WERKZEUG = "beispiel_app.zeigen"

AUFTRAG = (
    "Nachtauftrag Notizen. Die Notizen des Besitzers stehen auf dem Notizzettel im Hub, nicht in Dateien. Rufe das "
    f"Hub-Werkzeug {LESE_WERKZEUG} auf (über hub__call_tool: tool \"{LESE_WERKZEUG}\", arguments {{}}, ansicht \"voll\"); "
    "es liefert anzahl und notizen (je id, text, zeit). Kommt das Ergebnis gekürzt, hol den Rest mit hub__mehr. Suche die "
    "Notizen nicht im Workspace und nicht in MEMORY.md. Gruppiere sie nach Thema und fasse sie in höchstens fünf Sätzen "
    "zusammen: wie viele Notizen es sind, welche Themen vorkommen und was offen ist. Schreibe in keinen Chat und an "
    "keinen Kanal. Rufe zum Schluss genau einmal das Hub-Werkzeug os.mitteilen auf: titel \"Notizen geordnet\", text "
    "deine Zusammenfassung (höchstens 300 Zeichen), quelle \"Nacht\", dringlichkeit \"niedrig\". Sitzt niemand an der "
    "Shell, antwortet das Werkzeug mit vorgemerkt: true; das ist richtig, die Karte erscheint, sobald der Besitzer die "
    "Shell öffnet. Nur wenn der Notizzettel leer ist (anzahl 0), melde das ebenso knapp (titel \"Keine neuen Notizen\"). "
    f"Scheitert der Aufruf von {LESE_WERKZEUG}, melde titel \"Notizzettel nicht erreichbar\" mit der Fehlermeldung als "
    "text und behaupte nie, der Notizzettel sei leer. Frage nichts zurück: niemand antwortet nachts."
)

_UHR = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

Lauf = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def cron_ausdruck(uhr: str) -> str:
    """`03:00` -> `0 3 * * *` (täglich zu dieser Uhrzeit). Wirft ValueError."""
    m = _UHR.match(uhr.strip())
    if not m:
        raise ValueError(f'Uhrzeit {uhr!r}: erwartet HH:MM wie "03:00"')
    return f"{int(m[2])} {int(m[1])} * * *"


def add_argumente(uhr: str = VORGABE_UM, zeitzone: str = "") -> list[str]:
    """Die Argumente von `openclaw cron add` für den Nachtauftrag."""
    args = [
        "openclaw", "cron", "add",
        "--name", NAME,
        "--description", BESCHREIBUNG,
        "--declaration-key", SCHLUESSEL,
        "--cron", cron_ausdruck(uhr),
        "--exact",
        "--session", "isolated",
        "--no-deliver",  # gemeldet wird über os.mitteilen, nicht über einen Chat
        "--timeout-seconds", str(FRIST_S),
        "--message", AUFTRAG,
    ]
    if zeitzone:
        args += ["--tz", zeitzone]
    return args


def _json(text: str) -> Any:
    """Die erste JSON-Struktur in der Ausgabe (OpenClaw schreibt gelegentlich eine Kopfzeile davor)."""
    for i, zeichen in enumerate(text):
        if zeichen in "{[":
            try:
                return json.JSONDecoder().raw_decode(text[i:])[0]
            except ValueError:
                continue
    raise ValueError("keine JSON-Antwort")


def finde_auftrag(liste: Any) -> dict[str, Any] | None:
    jobs = liste.get("jobs") if isinstance(liste, dict) else liste
    for j in jobs if isinstance(jobs, list) else []:
        if isinstance(j, dict) and j.get("declarationKey") == SCHLUESSEL:
            return j
    return None


class Fehler(RuntimeError):
    pass


def machen(
    *, vorsatz: list[str], uhr: str, zeitzone: str, jetzt: bool, entfernen: bool, trocken: bool,
    lauf: Lauf, ausgabe: Callable[[str], None] = print,
) -> int:
    def rufen(args: list[str]) -> str:
        befehl = vorsatz + args
        if trocken:
            ausgabe("$ " + shlex.join(befehl))
            return ""
        erg = lauf(befehl)
        if erg.returncode != 0:
            raise Fehler(f"{shlex.join(args[:3])} scheiterte (Exitcode {erg.returncode}): {(erg.stderr or erg.stdout).strip()[:400]}")
        return erg.stdout

    def bestehender() -> dict[str, Any] | None:
        roh = rufen(["openclaw", "cron", "list", "--json"])
        return None if trocken else finde_auftrag(_json(roh))

    try:
        auftrag = bestehender()
        if entfernen:
            if auftrag is None and not trocken:
                ausgabe("Der Nachtauftrag ist nicht angelegt.")
                return 0
            rufen(["openclaw", "cron", "rm", str(auftrag["id"]) if auftrag else "<id>"])
            ausgabe("Der Nachtauftrag ist entfernt.")
            return 0
        if auftrag is None:
            rufen(add_argumente(uhr, zeitzone))
            auftrag = bestehender()
            if auftrag is None and not trocken:
                raise Fehler("Der Auftrag wurde angelegt, steht aber nicht in `openclaw cron list` (declarationKey fehlt).")
            ausgabe(f"Angelegt: {NAME}, täglich {uhr}.")
        elif (auftrag.get("payload") or {}).get("message") != AUFTRAG:
            # Ein älterer Auftrag (anderer Text): nur den Text nachziehen, Zeitplan und Id bleiben.
            rufen(["openclaw", "cron", "edit", str(auftrag["id"]), "--message", AUFTRAG])
            ausgabe(f"Schon angelegt: {auftrag.get('name') or NAME} (Auftrag {auftrag.get('id')}); Auftragstext aktualisiert.")
        else:
            ausgabe(f"Schon angelegt: {auftrag.get('name') or NAME} (Auftrag {auftrag.get('id')}); nichts geändert.")
        if jetzt:
            ausgabe("Läuft jetzt einmal (kann einige Minuten dauern) …")
            rufen(["openclaw", "cron", "run", str(auftrag["id"]) if auftrag else "<id>", "--wait", "--wait-timeout", "10m"])
            ausgabe("Fertig. Die Mitteilung steht in der Shell, sobald sie geöffnet ist (oder wartet bis dahin, bis zu 24 h).")
        return 0
    except Fehler as exc:
        ausgabe(f"Fehler: {exc}")
        return 1


def main(argv: list[str] | None = None, lauf: Lauf | None = None) -> int:
    p = argparse.ArgumentParser(description="Nachtauftrag „Notizen ordnen“ im Agenten anlegen (OpenClaw-Cron).")
    p.add_argument("--in", dest="vorsatz", default=VORGABE_IN,
                   help=f'Befehl, der Programme im Agenten-Container ausführt (Vorgabe: "{VORGABE_IN}")')
    p.add_argument("--um", default=VORGABE_UM, help=f"Uhrzeit HH:MM, täglich (Vorgabe {VORGABE_UM})")
    p.add_argument("--zeitzone", default="", help="IANA-Zeitzone der Uhrzeit, z. B. Europe/Berlin (Vorgabe: die des Gateways)")
    p.add_argument("--jetzt", action="store_true", help="den Auftrag sofort einmal laufen lassen (wartet auf das Ende)")
    p.add_argument("--entfernen", action="store_true", help="den Nachtauftrag wieder entfernen")
    p.add_argument("--trocken", action="store_true", help="nur anzeigen, was gerufen würde")
    a = p.parse_args(argv)
    try:
        cron_ausdruck(a.um)
        vorsatz = shlex.split(a.vorsatz)
    except ValueError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    if not vorsatz:
        print("Fehler: --in darf nicht leer sein", file=sys.stderr)
        return 2

    def echt(befehl: list[str]) -> "subprocess.CompletedProcess[str]":
        try:
            return subprocess.run(befehl, capture_output=True, text=True, timeout=900 if "run" in befehl else 120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(befehl, 1, "", str(exc))

    return machen(
        vorsatz=vorsatz, uhr=a.um, zeitzone=a.zeitzone, jetzt=a.jetzt, entfernen=a.entfernen,
        trocken=a.trocken, lauf=lauf or echt,
    )


if __name__ == "__main__":
    sys.exit(main())
