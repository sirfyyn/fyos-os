"""Agenten-Eingang `fyos:agent:eingang` — der Ereignisstrom, den ein Agenten-Runner betrachtet.

Der Agent reagiert auf Ereignisse, nicht auf einen Chatkanal. Eingänge sind Web-Chat, Matrix und Stimme (der
Benutzer), ein Vorgangssystem (Vorgang, Freigabe-Antwort), ein Zeitplan-Tick, Beobachtungen und Alarme.
Alle Quellen legen ihr Ereignis hier ab (`POST /hub/agent/eingang`, Plugin `agent`); der Runner liest
den Strom per Long-Poll (`GET /hub/agent/eingang?nach=…&warte=…`) und braucht selbst keinen Zugang
zu Redis.

Der Ausgang bleibt `fyos:agent` (_agentenstrom.py). Eingang und Ausgang sind getrennte Ströme,
damit Betrachter des Ausgangs keine Aufträge sehen, die noch niemand angenommen hat, und der
Runner nie seine eigenen Ereignisse liest.

Wie _agentenstrom nur Standardbibliothek: ein Runner kann dieselbe Datei nutzen.

Felder je Eintrag (Zeichenketten, wie Redis sie liefert):
    t        Zeit in Millisekunden seit 1970 (Annahme im Hub)
    v        Vertragsversion ("1")
    a        Agenten-ID (^[a-z0-9_-]{1,32}$), Vorgabe VORGABE_AGENT (im Plugin einstellbar)
    quelle   QUELLEN
    klasse   max | hintergrund (max zuerst). Vorgabe aus der Quelle: die eigenen Kanäle des Benutzers
             Kanäle (QUELLEN_MAX) sind max, alles andere hintergrund. Eine Hintergrundquelle
             kann sich nicht zu max hochstufen.
    text     ≤ TEXT_MAX, Steuerzeichen außer Zeilenumbruch und Tabulator fallen weg
    bezug    optional, ≤ 64 (Vorgang, Matrix-Ereignis, Sitzung — für die Antwort)
    von      optional, ≤ 64 (wer hat es eingeworfen, z. B. "@max:…" oder "itsm")
    schwere  optional, SCHWEREN (niedrig | mittel | hoch) — für Alarme und Beobachtungen; die
             Reflexe eines Runners können darauf ohne Modell reagieren
    arbeitsbereich  optional, nur bei klasse max, ^[a-z0-9_-]{1,40}$: Name eines Arbeitsbereichs aus der
             Liste des Runners (GET /hub/agent/arbeitsbereiche). Nur der Name, nie ein Pfad; der Runner
             löst ihn auf und kennt nur seine eigene feste Liste. Fehlt das Feld, gilt „standard“
"""

from __future__ import annotations

import re
from typing import Any

STROM = "fyos:agent:eingang"
VERTRAG = "1"
#: Eingänge sind selten (Menschen, Tick, Beobachtungen) — 5000 reichen für Wochen.
MAXLEN = 5_000
#: Agenten-ID, wenn ein Ereignis keine nennt.
VORGABE_AGENT = "agent"

QUELLEN = ("max", "web", "matrix", "stimme", "itsm", "zeitplan", "syl", "alarm", "probe")
#: Die eigenen Kanäle des Benutzers: Vorfahrt.
#: `stimme`: gesprochene Sätze des Benutzers (Sprach-Pipeline im Haus, Raum-Mikros nach dem Weckwort).
QUELLEN_MAX = ("max", "web", "matrix", "stimme")
KLASSEN = ("max", "hintergrund")
SCHWEREN = ("niedrig", "mittel", "hoch")

TEXT_MAX = 8_000
BEZUG_MAX = 64
VON_MAX = 64
#: Long-Poll: höchstens so lange hält der Hub eine Leseanfrage offen.
WARTE_MAX_S = 25
ANZAHL_MAX = 50

_AGENT = re.compile(r"^[a-z0-9_-]{1,32}$")
BEREICH = re.compile(r"^[a-z0-9_-]{1,40}$")
_STROM_ID = re.compile(r"^(\$|0|\d{1,20}-\d{1,20})$")
_EINZEILIG = re.compile(r"[\x00-\x1f\x7f]")
_MEHRZEILIG = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _kurz(s: str, grenze: int) -> str:
    return s if len(s) <= grenze else s[: grenze - 1] + "…"


def eintrag(roh: Any, jetzt_ms: int, agent_vorgabe: str = VORGABE_AGENT) -> dict[str, str]:
    """Ein eingeworfenes Ereignis prüfen und als Redis-Eintrag formen. Wirft ValueError."""
    if not isinstance(roh, dict):
        raise ValueError("Ereignis muss ein Objekt sein")
    quelle = str(roh.get("quelle") or "")
    if quelle not in QUELLEN:
        raise ValueError(f"quelle: eine aus {', '.join(QUELLEN)}")
    text = _MEHRZEILIG.sub("", str(roh.get("text") or "")).strip()
    if not text:
        raise ValueError("text fehlt")
    if len(text) > TEXT_MAX:
        raise ValueError(f"text: höchstens {TEXT_MAX} Zeichen")
    agent = str(roh.get("agent") or agent_vorgabe)
    if not _AGENT.match(agent):
        raise ValueError("agent: ^[a-z0-9_-]{1,32}$")
    vorgabe = "max" if quelle in QUELLEN_MAX else "hintergrund"
    klasse = str(roh.get("klasse") or vorgabe)
    if klasse not in KLASSEN:
        raise ValueError("klasse: max oder hintergrund")
    if klasse == "max" and vorgabe != "max":
        raise ValueError(f"klasse: Quelle {quelle} darf nicht max sein")
    schwere = str(roh.get("schwere") or "")
    if schwere and schwere not in SCHWEREN:
        raise ValueError(f"schwere: eine aus {', '.join(SCHWEREN)}")
    e = {
        "t": str(int(jetzt_ms)),
        "v": VERTRAG,
        "a": agent,
        "quelle": quelle,
        "klasse": klasse,
        "text": text,
    }
    for feld, grenze in (("bezug", BEZUG_MAX), ("von", VON_MAX)):
        wert = _EINZEILIG.sub("", str(roh.get(feld) or "")).strip()
        if wert:
            e[feld] = _kurz(wert, grenze)
    if schwere:
        e["schwere"] = schwere
    bereich = str(roh.get("arbeitsbereich") or "").strip()
    if bereich:
        if not BEREICH.match(bereich):
            raise ValueError("arbeitsbereich: ^[a-z0-9_-]{1,40}$ (der Name, kein Pfad)")
        if klasse == "max":  # Hintergrundquellen wählen keinen Arbeitsbereich: das Feld fällt weg
            e["arbeitsbereich"] = bereich
    return e


def einwerfen(r: Any, roh: Any, jetzt_ms: int, agent_vorgabe: str = VORGABE_AGENT) -> str:
    """Prüfen und in den Eingang legen; liefert die Strom-ID."""
    return str(r.xadd(STROM, eintrag(roh, jetzt_ms, agent_vorgabe), maxlen=MAXLEN, approximate=True))


def strom_id(wert: Any) -> str:
    """Leseposition prüfen: "$" (nur Neues), "0" (alles) oder eine Strom-ID."""
    s = str(wert or "$")
    if not _STROM_ID.match(s):
        raise ValueError("nach: $, 0 oder eine Strom-ID wie 1792270000000-0")
    return s


def lesen(r: Any, nach: str, warte_s: float, anzahl: int, agent: str = VORGABE_AGENT) -> dict[str, Any]:
    """Einträge nach `nach` lesen, höchstens `warte_s` blockierend. Liefert {eintraege, letzte}.

    `letzte` ist die Position für den nächsten Aufruf — auch wenn nichts für diesen Agenten dabei
    war, rückt sie vor (Einträge anderer Agenten werden übersprungen, nicht wiederholt).
    Bei `nach == "$"` ohne Treffer ist `letzte` die aktuelle Spitze, damit der nächste Aufruf
    nichts verpasst, was dazwischen kam."""
    nach = strom_id(nach)
    warte_ms = int(max(0.0, min(float(warte_s), WARTE_MAX_S)) * 1000)
    anzahl = max(1, min(int(anzahl), ANZAHL_MAX))
    if nach == "$":
        spitze = r.xrevrange(STROM, count=1)
        nach = spitze[0][0] if spitze else "0"
    antwort = r.xread({STROM: nach}, count=anzahl, block=warte_ms or None)
    eintraege: list[dict[str, Any]] = []
    letzte = nach
    for _name, liste in antwort or []:
        for sid, felder in liste:
            letzte = sid
            if felder.get("a", agent) != agent:
                continue
            eintraege.append({"id": sid, **felder})
    return {"eintraege": eintraege, "letzte": letzte}
