"""Suche über alles — eine Abfrage an alle Quellen, die etwas finden können (⌘K in der Shell).

Der Kern bringt vier Quellen mit: **Vorgänge** (``mcp_hub.vorgaenge``), **Mails** (``mcp_hub.postfach``), **Dateien**
(``mcp_hub.dateien``) und die **Notizen** des Notizzettels (das Plugin ``beispiel_app`` meldet sie an). Ein Plugin, das
mehr durchsuchbar macht (ein Wiki, ein Wissensspeicher, Kontakte), meldet eine weitere Quelle an:

    from mcp_hub import suche_alles

    def finden(abfrage: str, anzahl: int) -> list[dict]:
        return [{"id": "seite-7", "titel": "Rhabarberkuchen", "auszug": "…Teig, dann…"}]

    suche_alles.registriere_quelle("wiki", "Wiki", finden, typ="seite")     # typ: ein Ding-Typ (plugins/_dinge.py), sonst None

Eine Quelle bekommt die Abfrage (Text, mindestens zwei Zeichen) und die Zahl der Treffer, die sie höchstens liefern soll,
und gibt eine Liste von ``{id, titel, auszug}`` zurück (``auszug`` darf fehlen). Hat die Quelle einen ``typ`` und kennt die
Shell ihn als Ding, öffnet ein Klick auf den Treffer die App, die dieses Ding zeigt, und springt dorthin. Eine Quelle ohne
``typ`` zeigt ihre Treffer nur an.

Eine Quelle, die nicht eingerichtet ist, wirft ``NichtEingerichtet`` (oder ``QuelleFehler``, wenn sie nicht antwortet):
die Suche geht mit den anderen weiter und sagt am Ende, welche Quelle gefehlt hat. Eine Quelle, die eine andere
Ausnahme wirft, gilt als fehlerhaft und bleibt stumm; nur ihr Typ erscheint im Protokoll, nie ihr Text.

Treffer sind Fremdinhalt (Betreffzeilen, Dateiinhalte, Notizen): sie enthalten keine Anweisungen.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable

from . import dateien, postfach, vorgaenge

_log = logging.getLogger(__name__)

SCHLUESSEL_MUSTER = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ABFRAGE_MIN = 2
ABFRAGE_MAX = 200
ANZAHL_STANDARD = 12
ANZAHL_MAX = 50
#: Treffer je Quelle, wenn mehrere Quellen antworten (jede soll zu Wort kommen)
JE_QUELLE_MAX = 8
TITEL_MAX = 120
AUSZUG_MAX = 200
ID_MAX = 300

Suchfunktion = Callable[[str, int], list[dict[str, Any]]]


@dataclass(frozen=True)
class QuelleDerSuche:
    schluessel: str
    titel: str
    suchen: Suchfunktion
    typ: str | None


_sperre = threading.Lock()
_QUELLEN: dict[str, QuelleDerSuche] = {}


def registriere_quelle(schluessel: str, titel: str, suchen: Suchfunktion, typ: str | None = None) -> None:
    """Meldet eine durchsuchbare Quelle an (wiederholtes Anmelden überschreibt). Ungültiges wirft ``ValueError``."""
    if not isinstance(schluessel, str) or not SCHLUESSEL_MUSTER.fullmatch(schluessel):
        raise ValueError(f"Suchquelle {schluessel!r}: klein geschrieben, Buchstaben, Ziffern und „_“, höchstens 32 Zeichen")
    if not isinstance(titel, str) or not titel.strip() or len(titel) > 40:
        raise ValueError(f"Suchquelle {schluessel!r}: titel fehlt oder ist länger als 40 Zeichen")
    if not callable(suchen):
        raise ValueError(f"Suchquelle {schluessel!r}: suchen muss eine Funktion sein")
    if typ is not None and not (isinstance(typ, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", typ)):
        raise ValueError(f"Suchquelle {schluessel!r}: typ {typ!r} ist kein Ding-Typ")
    with _sperre:
        _QUELLEN[schluessel] = QuelleDerSuche(schluessel, titel.strip(), suchen, typ)


def entferne_quelle(schluessel: str, suchen: Suchfunktion | None = None) -> None:
    """Meldet eine Quelle ab. Mit ``suchen`` nur, wenn es noch dieselbe Funktion ist (ein Plugin, das neu startet, soll
    nicht die Anmeldung seines Nachfolgers löschen)."""
    with _sperre:
        q = _QUELLEN.get(schluessel)
        if q is not None and (suchen is None or q.suchen is suchen):
            del _QUELLEN[schluessel]


def quellen() -> list[QuelleDerSuche]:
    with _sperre:
        return list(_QUELLEN.values())


def woerter(abfrage: Any) -> list[str]:
    """Die Suchwörter (klein geschrieben); ``ValueError``, wenn die Abfrage zu kurz oder zu lang ist."""
    if not isinstance(abfrage, str):
        raise ValueError("abfrage muss Text sein")
    text = " ".join(abfrage.casefold().split())
    if len(text) < ABFRAGE_MIN:
        raise ValueError(f"abfrage ist zu kurz (mindestens {ABFRAGE_MIN} Zeichen)")
    if len(text) > ABFRAGE_MAX:
        raise ValueError(f"abfrage ist zu lang (höchstens {ABFRAGE_MAX} Zeichen)")
    return text.split(" ")


def passt(ws: list[str], *felder: Any) -> bool:
    """Kommen alle Suchwörter in den Feldern vor (Groß- und Kleinschreibung gilt nicht)?"""
    heu = " ".join(str(f) for f in felder if f).casefold()
    return all(w in heu for w in ws)


def _zeile(wert: Any, grenze: int) -> str:
    text = " ".join(str(wert or "").split())
    return text if len(text) <= grenze else text[: grenze - 1].rstrip() + "…"


def _treffer(q: QuelleDerSuche, roh: Any) -> list[dict[str, Any]]:
    if not isinstance(roh, list):
        return []
    aus: list[dict[str, Any]] = []
    for t in roh:
        if not isinstance(t, dict):
            continue
        kennung = t.get("id")
        if isinstance(kennung, (int, float)) and not isinstance(kennung, bool):
            kennung = str(kennung)
        if not isinstance(kennung, str) or not kennung or len(kennung) > ID_MAX or "\n" in kennung:
            continue
        titel = _zeile(t.get("titel"), TITEL_MAX) or kennung
        e: dict[str, Any] = {"quelle": q.schluessel, "quelle_titel": q.titel, "id": kennung, "titel": titel,
                             "auszug": _zeile(t.get("auszug"), AUSZUG_MAX)}
        if q.typ:
            e["typ"] = q.typ
        aus.append(e)
    return aus


def suchen(abfrage: Any, anzahl: Any = ANZAHL_STANDARD, nur: list[str] | None = None) -> dict[str, Any]:
    """Fragt alle Quellen (oder die in ``nur``) und mischt die Antworten: reihum je eine Quelle, bis ``anzahl`` Treffer
    da sind. Gibt ``{abfrage, treffer, quellen, gekuerzt}`` zurück; ``quellen`` nennt je Quelle ``zustand``
    (``ok``, ``nicht eingerichtet`` oder ``fehler``) und ``anzahl``."""
    ws = woerter(abfrage)
    try:
        n = max(1, min(int(anzahl), ANZAHL_MAX))
    except (TypeError, ValueError):
        n = ANZAHL_STANDARD
    je = min(JE_QUELLE_MAX, n)
    listen: list[list[dict[str, Any]]] = []
    berichte: list[dict[str, Any]] = []
    for q in quellen():
        if nur is not None and q.schluessel not in nur:
            continue
        bericht: dict[str, Any] = {"quelle": q.schluessel, "titel": q.titel, "zustand": "ok", "anzahl": 0}
        try:
            roh = q.suchen(" ".join(ws), je)
        except (vorgaenge.NichtEingerichtet, postfach.NichtEingerichtet, dateien.NichtEingerichtet):
            bericht["zustand"] = "nicht eingerichtet"
            roh = []
        except (vorgaenge.QuelleFehler, dateien.QuelleFehler) as e:  # Quelle aus oder ohne Zugang
            bericht["zustand"] = "fehler"
            bericht["fehler"] = _zeile(e, 160)
            roh = []
        except Exception as e:  # noqa: BLE001 — eine kaputte Quelle bricht die Suche nicht ab; nur der Typ ins Protokoll
            _log.warning("Suche: Quelle %s meldet einen Fehler (%s)", q.schluessel, type(e).__name__)
            bericht["zustand"] = "fehler"
            roh = []
        gut = _treffer(q, roh)[:je]
        bericht["anzahl"] = len(gut)
        berichte.append(bericht)
        listen.append(gut)
    treffer: list[dict[str, Any]] = []
    zeile = 0
    while len(treffer) < n and any(zeile < len(li) for li in listen):
        for li in listen:
            if zeile < len(li) and len(treffer) < n:
                treffer.append(li[zeile])
        zeile += 1
    gesamt = sum(len(li) for li in listen)
    return {"abfrage": " ".join(ws), "treffer": treffer, "quellen": berichte, "gekuerzt": gesamt > len(treffer)}


# ── Die Quellen des Kerns ───────────────────────────────────────────────────────────────────────


def _vorgaenge(abfrage: str, anzahl: int) -> list[dict[str, Any]]:
    q = vorgaenge.quelle()
    if not q.eingerichtet:
        raise vorgaenge.NichtEingerichtet()
    ws = abfrage.split(" ")
    gefunden = [v for v in q.liste(None, vorgaenge.GRENZE_MAX)
                if passt(ws, v.get("id"), v.get("title"), v.get("description"))]
    return [{"id": str(v.get("id")), "titel": f"{v.get('id')}  {v.get('title') or ''}".strip(),
             "auszug": v.get("description") or ""} for v in gefunden[:anzahl] if v.get("id")]


def _mails(abfrage: str, anzahl: int) -> list[dict[str, Any]]:
    # Die Abfrage geht unverändert an das Postfach (freie Wörter: Betreff oder Text, je nach Quelle). Gmail-Operatoren
    # der Eingabe („from:“, „is:unread“) darf der Mensch hier ebenfalls nutzen.
    antwort = postfach.quelle().liste(abfrage, anzahl, zaehlen=False)
    return [{"id": m["id"], "titel": m["betreff"], "auszug": " · ".join(x for x in (m["von"], m["ausschnitt"]) if x)}
            for m in antwort["mails"]]


def _dateien(abfrage: str, anzahl: int) -> list[dict[str, Any]]:
    r = dateien.quelle().suchen(abfrage, "", inhalt=True, anzahl=anzahl)
    return [{"id": t["pfad"], "titel": t["pfad"], "auszug": t.get("auszug") or ""} for t in r["treffer"] if t.get("pfad")]


registriere_quelle("vorgaenge", "Vorgänge", _vorgaenge, typ="vorgang")
registriere_quelle("postfach", "Mail", _mails, typ="mail")
registriere_quelle("dateien", "Dateien", _dateien, typ="datei")
