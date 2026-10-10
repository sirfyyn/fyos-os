"""Reifegrad je Schicht: aus der gewählten Konfiguration abgeleitet.

FYOS hat vier Schichten, jede mit drei Stufen. Zu jeder Stufe gehört ein Satz, woran man sie im laufenden System
erkennt. Der Installer zeigt vor dem Schreiben, auf welcher Stufe jede Schicht mit der gewählten Konfiguration steht
und was die nächste Stufe wäre. Er sagt damit, was man bekommt, und gibt ein Ziel vor, wenn man weitergehen will.

    gedaechtnis   was der Agent über dich und deine Umgebung weiß
    agent         was er selbst tut
    takte         was von selbst läuft (Routinen) und wie begrenzt
    oberflaeche   was du im Browser siehst

Herleitung: Jede Schicht beginnt auf Stufe 1; das leistet der Kern mit dem Agenten, beide sind Pflicht. Ein Baustein hebt
sie, indem sein Katalogeintrag unter `reife` eine höhere Stufe nennt (`katalog.py`); es zählt die höchste Stufe unter den
gewählten Bausteinen. Für `takte` kommt eine Regel aus der erzeugten Hub-Konfiguration dazu: Trägt ein gewähltes
Hub-Plugin `takt_grenzen` (Tageslimit und Zeitfenster der Takte, `docs/ERWEITERN.md` 2.12), steht die Schicht auf Stufe 3.

Das ist eine Auskunft über die Konfiguration, kein Messwert. Ob die Dienste nach dem Start antworten, prüft die
Gesundheitsprüfung (`ausfuehren.py`), ob der Hub verbotene Anfragen ablehnt, die Abnahme (`abnahme.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:  # nur für die Typangaben; katalog.py importiert dieses Modul
    from .katalog import Baustein

SCHICHTEN = ("gedaechtnis", "agent", "takte", "oberflaeche")
MAX_STUFE = 3

TITEL = {"gedaechtnis": "Gedächtnis", "agent": "Agent", "takte": "Takte", "oberflaeche": "Oberfläche"}
FRAGE = {
    "gedaechtnis": "Was der Agent über dich und deine Umgebung weiß.",
    "agent": "Was der Agent selbst tut.",
    "takte": "Was von selbst läuft und wie begrenzt.",
    "oberflaeche": "Was du im Browser siehst.",
}


@dataclass(frozen=True)
class Stufe:
    name: str
    erkennbar: str  # ein Satz: woran man die Stufe im laufenden System erkennt


LEITER: dict[str, tuple[Stufe, Stufe, Stufe]] = {
    "gedaechtnis": (
        Stufe("Persona", "Der Agent nennt auf Nachfrage seinen Namen und deinen aus der Einrichtung, auch nach einem Neustart des Agenten."),
        Stufe("Wissen aus Bausteinen", "Er beantwortet Fragen zu den gewählten Bausteinen mit Werten aus deren Werkzeugen."),
        Stufe("Verlauf und Vorgänge", "Ein Verlauf zeigt, was der Agent getan hat und warum, und erledigte Vorgänge bleiben nachlesbar."),
    ),
    "agent": (
        Stufe("Chat", "Das Chatfenster antwortet unter dem gewählten Namen und legt Schweres zuerst als Freigabe vor."),
        Stufe("Werkzeuge", "Er ruft Werkzeuge der gewählten Bausteine auf und meldet das Ergebnis knapp im Chat."),
        Stufe("Vorgänge", "Er legt Vorgänge an, arbeitet sie ab und meldet den Stand, und Freigaben stehen in einer Liste."),
    ),
    "takte": (
        Stufe("Von Hand", "Nichts läuft von selbst: `mcp.zeitplan` ist leer, und der Agent handelt nur auf Zuruf."),
        Stufe("Routinen", "Routinen sind eingerichtet, und `mcp.zeitplan` oder die Fläche des Bausteins zeigt, was läuft und was gerade erlaubt ist."),
        Stufe("Routinen mit Grenzen", "Jede Routine hat Tageslimit und Zeitfenster, und `mcp.zeitplan` zeigt beides samt Laufprotokoll."),
    ),
    "oberflaeche": (
        Stufe("Desktop", "Die Adresse öffnet den Desktop mit Dock und Chatfenster, aber noch ohne Fach-Apps."),
        Stufe("Apps", "Im Dock erscheint für jeden gewählten Baustein mit Oberfläche eine eigene App (Liste: `/hub-api/apps`)."),
        Stufe("Zentrale", "Eine Zentrale zeigt die Lage in einem Satz und, was auf dich wartet, als Kacheln nach Dringlichkeit."),
    ),
}


@dataclass(frozen=True)
class Reife:
    schicht: str
    titel: str
    frage: str
    stufe: int  # 1 bis MAX_STUFE
    name: str  # Name der erreichten Stufe
    erkennbar: str  # Satz der erreichten Stufe
    naechste: str  # Satz der nächsten Stufe; leer auf der obersten

    def als_dict(self) -> dict[str, Any]:
        return {
            "schicht": self.schicht, "titel": self.titel, "frage": self.frage, "stufe": self.stufe, "von": MAX_STUFE,
            "name": self.name, "erkennbar": self.erkennbar, "naechste": self.naechste,
        }

    def zeile(self) -> str:
        """Eine Zeile für Text-Oberflächen: `Gedächtnis: Stufe 2 von 3 (Wissen aus Bausteinen)`."""
        return f"{self.titel}: Stufe {self.stufe} von {MAX_STUFE} ({self.name})"


def _traegt_grenzen(eintrag: dict[str, Any]) -> bool:
    """Gewähltes Hub-Plugin mit `takt_grenzen` in seiner Konfiguration."""
    config = eintrag.get("config")
    return eintrag.get("enabled", True) is not False and isinstance(config, dict) and bool(config.get("takt_grenzen"))


def stufen_von(bausteine: Iterable[Baustein]) -> dict[str, int]:
    """Stufe je Schicht für die gewählten Bausteine (jede mindestens 1)."""
    stufe = dict.fromkeys(SCHICHTEN, 1)
    for b in bausteine:
        for schicht, n in b.reife.items():
            if schicht in stufe:
                stufe[schicht] = max(stufe[schicht], min(int(n), MAX_STUFE))
        if any(_traegt_grenzen(p) for p in b.hub_plugins):
            stufe["takte"] = MAX_STUFE
    return stufe


def bestimme(bausteine: Iterable[Baustein]) -> list[Reife]:
    """Der Reifegrad aller Schichten in fester Reihenfolge (`SCHICHTEN`)."""
    stufe = stufen_von(bausteine)
    ergebnis = []
    for schicht in SCHICHTEN:
        leiter, n = LEITER[schicht], stufe[schicht]
        ergebnis.append(Reife(
            schicht=schicht, titel=TITEL[schicht], frage=FRAGE[schicht], stufe=n,
            name=leiter[n - 1].name, erkennbar=leiter[n - 1].erkennbar,
            naechste=leiter[n].erkennbar if n < MAX_STUFE else "",
        ))
    return ergebnis


def zeilen(reife: Iterable[Reife]) -> list[str]:
    """Zeilen für die Kommandozeile: Kopf, dann je Schicht Stufe und Satz."""
    ergebnis = [f"Reifegrad (je Schicht Stufe 1 bis {MAX_STUFE}, aus der Auswahl abgeleitet):"]
    for r in reife:
        ergebnis.append(f"  {r.zeile()}")
        ergebnis.append(f"    Erkennbar: {r.erkennbar}")
        if r.naechste:
            ergebnis.append(f"    Nächste Stufe: {r.naechste}")
    return ergebnis
