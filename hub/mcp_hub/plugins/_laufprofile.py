"""Laufprofile für isolierte Läufe des Agenten (Cron-Aufträge, Routinen): welche Werkzeuge ein Lauf bekommt.

OpenClaw kennt je Auftrag eine Werkzeugliste (``payload.toolsAllow``). Fehlt sie, gilt „alles“ (``["*"]``); eine leere
Liste heißt „keine“ (der Lauf kann nur antworten). Beides ist für Routinen selten richtig. Die drei Profile hier geben
jedem Lauftyp eine benannte, dokumentierte Liste:

``lesen``      liest: Arbeitsordner, Gedächtnis, Workboard, Web, Dateien (lesend), Hub nur suchen und erklären.
``reflexion``  denkt und hält fest: wie ``lesen``, dazu Hub-Werkzeuge und Ansichten (Apps) sowie Karten anlegen und
               kommentieren. Ergebnisse stehen in Karten, nicht nur in der Sitzung.
``melden``     wie ``reflexion``, dazu darf er eine Nachricht senden und Karten weiterbewegen.

Schreibende Dateiwerkzeuge (``write``, ``edit``, ``exec``, ``file_write``) stehen in keinem Profil; wer sie braucht,
setzt die Liste eines einzelnen Auftrags bewusst von Hand. Die Werkzeugnamen sind die von OpenClaw 2026.9; die des Hubs
tragen das Präfix ``hub__`` (Server) und dann den Hub-Namen (``hub__hub__call_tool``).

Nichts hier legt Aufträge an: ``vorlage`` baut den Aufruf (Befehl und Nutzlast), den ein Mensch oder der Agent selbst
ausführt. Die Brücke bleibt bei lesenden Cron-Methoden.
"""

from __future__ import annotations

import shlex
from typing import Any

# Bausteine
_ARBEIT = ("read", "dir_list", "file_fetch", "web_fetch", "session_status")
_GEDAECHTNIS = ("memory_search", "memory_get")
_BOARD_LESEN = ("workboard_boards", "workboard_list", "workboard_read")
_HUB_LESEN = (
    "hub__hub__search_tools", "hub__hub__schema", "hub__hub__map", "hub__hub__mehr", "hub__hub__health",
    "hub__hub__list_servers", "hub__dateien__liste", "hub__werkstatt__suchen", "hub__werkstatt__beschreiben",
    "hub__prompts_list", "hub__resources_list", "hub__resources_read",
)
_HUB_VOLL = ("hub__hub__call_tool", "hub__gui__bauen", "hub__gui__zeigen", "hub__mcp__uebersicht",
             "hub__mcp__werkzeug", "hub__mcp__ausprobieren", "hub__prompts_get")
_BOARD_SCHREIBEN = ("workboard_create", "workboard_comment", "workboard_link")
_BOARD_BEWEGEN = ("workboard_move", "workboard_complete", "workboard_block", "workboard_unblock")

PROFILE: dict[str, dict[str, Any]] = {
    "lesen": {
        "zweck": "Nachsehen und zusammenfassen, ohne etwas zu verändern.",
        "beispiele": ["Wochenüberblick der Karten", "Ordner auflisten", "Gedächtnis befragen"],
        "werkzeuge": [*_ARBEIT, *_GEDAECHTNIS, *_BOARD_LESEN, *_HUB_LESEN],
        "zeitlimit_s": 300,
    },
    "reflexion": {
        "zweck": "Nachdenken und das Ergebnis in Karten festhalten; Hub-Werkzeuge und Ansichten (Apps) nutzen.",
        "beispiele": ["Tagesrückblick", "Neugier-Lauf", "Bestand prüfen und Karte anlegen"],
        "werkzeuge": [*_ARBEIT, *_GEDAECHTNIS, *_BOARD_LESEN, *_HUB_LESEN, *_HUB_VOLL, *_BOARD_SCHREIBEN],
        "zeitlimit_s": 600,
    },
    "melden": {
        "zweck": "Wie Reflexion, dazu eine Nachricht an den Besitzer senden und Karten weiterbewegen.",
        "beispiele": ["Morgenbericht", "Wache mit Meldung", "Erinnerung an einen Termin"],
        "werkzeuge": [*_ARBEIT, "message", *_GEDAECHTNIS, *_BOARD_LESEN, *_HUB_LESEN, *_HUB_VOLL, *_BOARD_SCHREIBEN,
                      *_BOARD_BEWEGEN],
        "zeitlimit_s": 600,
    },
}

VERBOTEN_IN_PROFILEN = ("write", "edit", "apply_patch", "exec", "process", "file_write", "dir_fetch", "cron",
                        "gateway", "*")

REIHENFOLGE = ("lesen", "reflexion", "melden")


class ProfilFehler(ValueError):
    pass


def namen() -> list[str]:
    return list(REIHENFOLGE)


def werkzeugliste(profil: str) -> list[str]:
    if profil not in PROFILE:
        raise ProfilFehler(f"kein Laufprofil {profil!r} (gibt es: {', '.join(REIHENFOLGE)})")
    return list(PROFILE[profil]["werkzeuge"])


def profile() -> list[dict[str, Any]]:
    """Alle Profile mit Zweck, Beispielen, Zeitlimit und Werkzeugliste, vom kleinsten zum größten."""
    return [{"name": n, "zweck": PROFILE[n]["zweck"], "beispiele": list(PROFILE[n]["beispiele"]),
             "zeitlimit_s": PROFILE[n]["zeitlimit_s"], "werkzeuge": werkzeugliste(n),
             "anzahl": len(PROFILE[n]["werkzeuge"])} for n in REIHENFOLGE]


def erkenne(tools_allow: Any) -> str:
    """Zu einer ``toolsAllow``-Liste: Profilname, ``alle`` (fehlt oder ``*``), ``keine`` (leer) oder ``eigene``."""
    if tools_allow is None:
        return "alle"
    if not isinstance(tools_allow, list):
        return "eigene"
    liste = [str(x) for x in tools_allow]
    if not liste:
        return "keine"
    if "*" in liste:
        return "alle"
    menge = set(liste)
    for n in REIHENFOLGE:
        if menge == set(PROFILE[n]["werkzeuge"]):
            return n
    return "eigene"


def pruefen(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Cron-Aufträge (mit Nutzlast) nach Profil ordnen. Trägt nur Namen, Nummern und Zählungen, nie die Nachricht.

    Ein Auftrag mit ``*`` oder ohne Liste gilt als offen; die Verwaltungsaufträge von OpenClaw selbst (Heartbeat,
    Skill-Review, Gedächtnis) laufen mit ihrer eigenen Richtlinie und werden getrennt gezählt.
    """
    zeilen: list[dict[str, Any]] = []
    zaehler: dict[str, int] = {}
    for j in jobs:
        if not isinstance(j, dict):
            continue
        nutz = j.get("payload") if isinstance(j.get("payload"), dict) else {}
        # Systembefehle und Hinweise ohne Modell haben keine Werkzeugliste
        art = str(nutz.get("kind") or "")
        schluessel = str(j.get("declarationKey") or "")
        verwaltet = schluessel.startswith(("heartbeat:", "skill-collection-review:", "memory-core:"))
        if art and art != "agentTurn":
            profil = "ohne Modell"
        elif verwaltet:
            profil = "verwaltet"
        else:
            profil = erkenne(nutz.get("toolsAllow") if "toolsAllow" in nutz else None)
        zaehler[profil] = zaehler.get(profil, 0) + 1
        zeilen.append({"id": j.get("id"), "name": j.get("name") or j.get("displayName"), "profil": profil,
                       "an": bool(j.get("enabled", True)), "werkzeuge": len(nutz.get("toolsAllow") or [])})
    offen = [z for z in zeilen if z["profil"] in ("alle", "eigene") and z["an"]]
    return {"auftraege": zeilen, "je_profil": zaehler, "ohne_profil": [z["name"] for z in offen]}


def _plan(plan: dict[str, Any]) -> list[str]:
    """Zeitplan als Befehlsflags: genau eines von ``cron`` (Ausdruck), ``alle`` (Dauer), ``um`` (Zeitpunkt oder Dauer)."""
    if not isinstance(plan, dict):
        raise ProfilFehler("plan: Objekt mit cron, alle oder um erwartet")
    gesetzt = [k for k in ("cron", "alle", "um") if str(plan.get(k) or "").strip()]
    if len(gesetzt) != 1:
        raise ProfilFehler("plan: genau eines von cron, alle, um angeben")
    k = gesetzt[0]
    wert = " ".join(str(plan[k]).split())
    if len(wert) > 80 or any(c in wert for c in ";&|`$<>\n"):
        raise ProfilFehler(f"plan.{k}: ungültiger Wert")
    flag = {"cron": "--cron", "alle": "--every", "um": "--at"}[k]
    flags = [flag, wert]
    if plan.get("zeitzone"):
        zone = str(plan["zeitzone"]).strip()
        if not zone.replace("/", "").replace("_", "").replace("-", "").isalnum():
            raise ProfilFehler("plan.zeitzone: ungültiger Wert")
        flags += ["--tz", zone]
    return flags


def vorlage(profil: str, name: str, text: str, plan: dict[str, Any], agent: str = "", sitzung: str = "") -> dict[str, Any]:
    """Der Aufruf für einen Auftrag mit diesem Profil: ``befehl`` (Shell, für ``openclaw cron add``) und ``auftrag``.

    ``sitzung`` bindet den Lauf an eine feste Sitzung (z. B. ``agent:<id>:vorgang:INC-1``); ohne sie läuft er isoliert.
    """
    liste = werkzeugliste(profil)
    name = " ".join(str(name or "").split())
    text = str(text or "").strip()
    if not name or len(name) > 80:
        raise ProfilFehler("name: 1 bis 80 Zeichen")
    if not text or len(text) > 8000:
        raise ProfilFehler("text: 1 bis 8000 Zeichen")
    flags = _plan(plan)
    zeitlimit = int(PROFILE[profil]["zeitlimit_s"])
    teile = ["openclaw", "cron", "add", "--name", name, *flags]
    if agent:
        teile += ["--agent", agent]
    if sitzung:
        teile += ["--session-key", sitzung]
    else:
        teile += ["--session", "isolated"]
    teile += ["--tools", ",".join(liste), "--light-context", "--timeout-seconds", str(zeitlimit), "--no-deliver",
              "--message", text]
    auftrag = {
        "name": name,
        **({"sessionKey": sitzung} if sitzung else {"sessionTarget": "isolated"}),
        "payload": {"kind": "agentTurn", "message": text, "lightContext": True, "toolsAllow": liste,
                    "timeoutSeconds": zeitlimit},
        "delivery": {"mode": "none"},
        **({"agentId": agent} if agent else {}),
    }
    return {"profil": profil, "befehl": " ".join(shlex.quote(t) for t in teile), "auftrag": auftrag,
            "werkzeuge": liste, "hinweis": "Legt nichts an; ausführen im Agenten-Pod oder durch den Agenten selbst."}
