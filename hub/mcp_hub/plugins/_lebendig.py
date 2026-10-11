"""„Lebt der Agent?“ aus FYOS-Sicht: Herzschlag, Sitzungen, Fortschrittskarten je Vorgang.

Quellen sind drei lesende Gateway-Methoden: ``last-heartbeat`` (das Ergebnis des letzten Herzschlags), ``sessions.list``
(Sitzungen mit Lauf und Fehler) und ``progressCard.get`` (die Karte, die der Agent in einer Sitzung pflegt: Schritte und
eine kurze Notiz). Nichts davon trägt Gesprächsinhalt; von der Karte kommen Schrittzahlen und ein gekürzter Notiztext.

Das Urteil ist bewusst grob:

``gestoert``  das Gateway ist nicht bereit, oder der letzte Lauf einer Sitzung scheiterte (häufig: das Modell antwortet nicht)
``laeuft``    mindestens ein Lauf ist gerade aktiv
``bereit``    nichts davon
"""

from __future__ import annotations

import time
from typing import Any

from .. import umschlag as U

NOTIZ_MAX = 240
FEHLER_MAX = 200


def _kurz(text: Any, grenze: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= grenze else t[: grenze - 1].rstrip() + "…"


def _ms(wert: Any) -> int | None:
    try:
        n = float(wert)
    except (TypeError, ValueError):
        return None
    return int(n) if n > 0 else None


def herzschlag_aus(roh: Any, jetzt_s: float | None = None) -> dict[str, Any] | None:
    """Ergebnis des letzten Herzschlags; ``None``, wenn es noch keinen gab."""
    if not isinstance(roh, dict) or not roh.get("ts"):
        return None
    jetzt = time.time() if jetzt_s is None else jetzt_s
    ms = _ms(roh.get("ts"))
    return {"zeit_ms": ms, "alter_s": round(jetzt - ms / 1000) if ms else None, "status": str(roh.get("status") or "") or None,
            "grund": str(roh.get("reason") or "") or None, "still": bool(roh.get("silent")), "dauer_ms": _ms(roh.get("durationMs"))}


def sitzung_aus(roh: Any) -> dict[str, Any] | None:
    if not isinstance(roh, dict) or not roh.get("key"):
        return None
    schluessel = str(roh["key"])
    vorgang = U.vorgang_aus_schluessel(schluessel)
    return {
        "schluessel": schluessel, "art": str(roh.get("classification") or roh.get("kind") or "") or None,
        "vorgang": vorgang[1] if vorgang else None, "status": str(roh.get("status") or "") or None,
        "aktiv": bool(roh.get("hasActiveRun")), "begonnen_ms": _ms(roh.get("startedAt")),
        "beendet_ms": _ms(roh.get("endedAt")), "aktualisiert_ms": _ms(roh.get("updatedAt")),
        "fehler": _kurz(roh.get("lastRunError"), FEHLER_MAX) or None,
    }


def karte_aus(roh: Any) -> dict[str, Any] | None:
    """Fortschrittskarte kurz: Revision, Zeit, Schrittzahlen, aktueller Schritt, gekürzte Notiz; ``None`` ohne Karte."""
    karte = roh.get("card") if isinstance(roh, dict) and "card" in roh else roh
    if not isinstance(karte, dict) or not karte:
        return None
    plan = [p for p in (karte.get("plan") or []) if isinstance(p, dict)]
    fertig = sum(1 for p in plan if p.get("status") == "completed")
    aktuell = next((p for p in plan if p.get("status") == "in_progress"), None) \
        or next((p for p in plan if p.get("status") == "pending"), None)
    return {
        "revision": karte.get("revision") if isinstance(karte.get("revision"), int) else None,
        "aktualisiert_ms": _ms(karte.get("updatedAt")),
        "schritte": {"fertig": fertig, "gesamt": len(plan)} if plan else None,
        "aktuell": _kurz(aktuell.get("step"), 160) if aktuell else None,
        "notiz": _kurz(karte.get("markdown"), NOTIZ_MAX) or None,
    }


def urteil(bereit: bool | None, sitzungen: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """``(zustand, gruende)``: gestoert, laeuft oder bereit, mit den Gründen im Klartext."""
    gruende: list[str] = []
    if bereit is False:
        gruende.append("Gateway nicht bereit")
    # Nur der jüngste beendete Lauf zählt: ein alter Fehler bleibt nicht für immer stehen, sobald danach etwas gelang.
    beendet = [s for s in sitzungen if s.get("beendet_ms") and not s.get("aktiv")]
    neueste = max(beendet, key=lambda s: s["beendet_ms"]) if beendet else None
    if neueste is not None and neueste.get("status") == "failed":
        gruende.append(f"letzter Lauf scheiterte in {neueste['schluessel']}" + (f": {neueste['fehler']}" if neueste.get("fehler") else ""))
    if gruende:
        return "gestoert", gruende
    if any(s.get("aktiv") for s in sitzungen):
        return "laeuft", ["ein Lauf ist aktiv"]
    return "bereit", []
