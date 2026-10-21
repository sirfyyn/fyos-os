"""Arbeitsbereiche eines Agenten — die feste Liste, aus der der Benutzer im Chatfenster wählt.

Der Runner kennt die Ordner (Name → Pfad) und meldet dem Hub nur Namen und Titel
(`POST /hub/agent/arbeitsbereiche`); Pfade verlassen den Rechner des Runners nie. Chatfenster lesen die Liste mit
`GET /hub/agent/arbeitsbereiche` und schicken beim Auftrag nur den Namen (`arbeitsbereich` im Eingang,
siehe _agenteneingang). Fehlt der Name, gilt „standard“: das ist der Rückfall, auch nach dem Schließen
des Fensters, weil die Wahl nie als Zustand gespeichert wird, sondern an jedem Auftrag hängt.

Wie die anderen Agentenmodule nur Standardbibliothek.
"""

from __future__ import annotations

import json
import re
from typing import Any

STANDARD = "standard"
SCHLUESSEL = "fyos:agent:arbeitsbereiche:{agent}"
MAX_EINTRAEGE = 20
TITEL_MAX = 60

_NAME = re.compile(r"^[a-z0-9_-]{1,40}$")
_AGENT = re.compile(r"^[a-z0-9_-]{1,32}$")
_ZEICHEN = re.compile(r"[\x00-\x1f\x7f]")


def pruefen(roh: Any) -> list[dict[str, str]]:
    """Die gemeldete Liste prüfen und bereinigen. Wirft ValueError. „standard“ gehört immer an den Anfang."""
    if not isinstance(roh, list) or not roh:
        raise ValueError("bereiche: nicht leere Liste aus {name, titel}")
    if len(roh) > MAX_EINTRAEGE:
        raise ValueError(f"bereiche: höchstens {MAX_EINTRAEGE} Einträge")
    aus: list[dict[str, str]] = []
    gesehen: set[str] = set()
    for b in roh:
        if not isinstance(b, dict):
            raise ValueError("bereiche: jeder Eintrag ein Objekt {name, titel}")
        name = str(b.get("name") or "")
        if not _NAME.match(name):
            raise ValueError("bereiche: name ^[a-z0-9_-]{1,40}$ (der Name, kein Pfad)")
        if name in gesehen:
            raise ValueError(f"bereiche: {name} doppelt")
        gesehen.add(name)
        titel = _ZEICHEN.sub("", str(b.get("titel") or name)).strip()[:TITEL_MAX] or name
        aus.append({"name": name, "titel": titel})
    if STANDARD not in gesehen:
        raise ValueError("bereiche: „standard“ fehlt")
    aus.sort(key=lambda b: b["name"] != STANDARD)  # standard zuerst, Rest in der Reihenfolge des Runners
    return aus


def agent_pruefen(agent: Any, vorgabe: str = "agent") -> str:
    a = str(agent or vorgabe)
    if not _AGENT.match(a):
        raise ValueError("agent: ^[a-z0-9_-]{1,32}$")
    return a


def setzen(r: Any, agent: Any, roh: Any, vorgabe: str = "agent") -> list[dict[str, str]]:
    liste = pruefen(roh)
    r.set(SCHLUESSEL.format(agent=agent_pruefen(agent, vorgabe)), json.dumps(liste, ensure_ascii=False))
    return liste


def lesen(r: Any, agent: Any = None, vorgabe: str = "agent") -> list[dict[str, str]]:
    """Die zuletzt gemeldete Liste; ohne Meldung nur „standard“ (das Chatfenster zeigt dann keine Auswahl)."""
    roh = r.get(SCHLUESSEL.format(agent=agent_pruefen(agent, vorgabe)))
    if isinstance(roh, bytes):
        roh = roh.decode("utf-8", "replace")
    try:
        return pruefen(json.loads(roh)) if roh else [{"name": STANDARD, "titel": "Standard"}]
    except ValueError:
        return [{"name": STANDARD, "titel": "Standard"}]
