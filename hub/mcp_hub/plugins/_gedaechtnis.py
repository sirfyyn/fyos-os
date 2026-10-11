"""Gedächtnis des Agenten aus FYOS-Sicht: ein Recall-Weg (``erinnern``) und der Stand (``gedaechtnis``).

``erinnern`` fragt zwei Seiten und mischt die Ränge (Reciprocal Rank Fusion, wie die Werkzeugsuche des Hubs):

* ``gedaechtnis``  das Gedächtnis des Agenten (OpenClaw ``memory.search``: Notizen, Gesprächsauszüge, Traumbericht);
  es sucht nach Vektoren, wenn ein Embedding-Dienst eingerichtet ist (``searchMode`` hybrid), sonst im Text (``fts-only``)
* ``dokumente``    die Dokumentenquelle des Hubs (Ablage oder Dokumentendienst), falls eingerichtet

Zu jedem Weg gehört ein Messwert (Dauer, Anzahl, Modus), damit sichtbar ist, was der Recall tut und wie schnell. Treffer
tragen Quelle, Verweis, Titel und einen kurzen Auszug; ein Weg, der ausfällt, ist ein Vermerk, kein Fehler.

``stand_aus`` fasst ``doctor.memory.status`` zusammen: Anbieter, Dreaming (Phasen, nächster Lauf, Zahlen) ohne die
Auszüge der Kurzzeiteinträge.
"""

from __future__ import annotations

import time
from typing import Any, Callable

RRF_K = 60
AUSZUG_MAX = 280
LIMIT_MAX = 20
WEGE = ("gedaechtnis", "dokumente")


def _kurz(text: Any, grenze: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= grenze else t[: grenze - 1].rstrip() + "…"


def _zahl(wert: Any) -> float:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return 0.0


def treffer_aus_gedaechtnis(antwort: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Treffer und Kopfdaten aus der Antwort von ``memory.search`` (Reihenfolge wie geliefert)."""
    if not isinstance(antwort, dict):
        return [], {}
    kopf = {"anbieter": str(antwort.get("provider") or "") or None, "modus": str(antwort.get("searchMode") or "") or None}
    aus: list[dict[str, Any]] = []
    for r in antwort.get("results") or []:
        if not isinstance(r, dict):
            continue
        pfad = str(r.get("path") or "")
        von, bis = r.get("startLine"), r.get("endLine")
        verweis = f"{pfad}:{von}-{bis}" if pfad and von is not None and bis is not None else pfad
        aus.append({"quelle": "gedaechtnis", "verweis": verweis, "titel": pfad.rsplit("/", 1)[-1] or pfad or "Gedächtnis",
                    "auszug": _kurz(r.get("snippet"), AUSZUG_MAX), "punkte": round(_zahl(r.get("score")), 4),
                    "art": str(r.get("source") or "") or None})
    return aus, kopf


def treffer_aus_dokumenten(antwort: Any) -> list[dict[str, Any]]:
    if not isinstance(antwort, dict):
        return []
    aus: list[dict[str, Any]] = []
    for d in antwort.get("dokumente") or []:
        if not isinstance(d, dict) or d.get("id") is None:
            continue
        aus.append({"quelle": "dokumente", "verweis": f"dokument:{d['id']}", "titel": _kurz(d.get("titel"), 120),
                    "auszug": _kurz(d.get("auszug"), AUSZUG_MAX), "link": d.get("link"), "punkte": None, "art": d.get("typ")})
    return aus


def mischen(listen: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    """Ränge mehrerer Listen zu einer Reihenfolge (RRF); gleiche Verweise zählen einmal und tragen alle Quellen."""
    punkte: dict[str, float] = {}
    erster: dict[str, dict[str, Any]] = {}
    for liste in listen:
        for rang, t in enumerate(liste):
            schluessel = f"{t['quelle']}|{t['verweis']}"
            punkte[schluessel] = punkte.get(schluessel, 0.0) + 1.0 / (RRF_K + rang + 1)
            erster.setdefault(schluessel, t)
    ordnung = sorted(punkte, key=lambda k: (-punkte[k], k))
    return [{**erster[k], "rang_punkte": round(punkte[k], 5)} for k in ordnung[:limit]]


def erinnern(frage: str, limit: int, wege: dict[str, Callable[[str, int], Any]]) -> dict[str, Any]:
    """Die Frage an jeden Weg, gemischt, mit Messwert je Weg. ``wege``: Name -> ``f(frage, n)`` liefert die Rohantwort."""
    frage = " ".join(str(frage or "").split())
    if not frage:
        raise ValueError("frage fehlt")
    limit = max(1, min(int(limit or 8), LIMIT_MAX))
    listen: list[list[dict[str, Any]]] = []
    messung: dict[str, Any] = {}
    start = time.monotonic()
    for name in WEGE:
        weg = wege.get(name)
        if weg is None:
            messung[name] = {"ok": False, "grund": "nicht eingerichtet", "ms": 0, "anzahl": 0}
            continue
        t0 = time.monotonic()
        try:
            roh = weg(frage, limit)
        except Exception as exc:  # noqa: BLE001 -- ein ausfallender Weg ist ein Vermerk
            messung[name] = {"ok": False, "grund": _kurz(f"{type(exc).__name__}: {exc}", 160),
                             "ms": round((time.monotonic() - t0) * 1000), "anzahl": 0}
            continue
        if name == "gedaechtnis":
            treffer, kopf = treffer_aus_gedaechtnis(roh)
        else:
            treffer, kopf = treffer_aus_dokumenten(roh), {}
        listen.append(treffer)
        messung[name] = {"ok": True, "ms": round((time.monotonic() - t0) * 1000), "anzahl": len(treffer), **kopf}
    gemischt = mischen(listen, limit)
    ok = [n for n, m in messung.items() if m["ok"]]
    return {"frage": frage, "treffer": gemischt, "messung": {**messung, "gesamt_ms": round((time.monotonic() - start) * 1000)},
            "satz": (f"{len(gemischt)} Treffer aus {', '.join(ok)}." if ok else "Kein Weg des Gedächtnisses erreichbar.")}


def stand_aus(status: Any) -> dict[str, Any]:
    """Kurzfassung von ``doctor.memory.status`` ohne die Auszüge der Kurzzeiteinträge."""
    if not isinstance(status, dict):
        return {}
    traum = status.get("dreaming") if isinstance(status.get("dreaming"), dict) else {}
    phasen: dict[str, Any] = {}
    for name, p in (traum.get("phases") or {}).items():
        if isinstance(p, dict):
            phasen[name] = {"an": bool(p.get("enabled")), "zeitplan": p.get("cron"), "naechster_lauf_ms": p.get("nextRunAtMs"),
                            "verwaltet": bool(p.get("managedCronPresent"))}
    emb = status.get("embedding") if isinstance(status.get("embedding"), dict) else {}
    return {
        "anbieter": status.get("provider"),
        "embedding": {"ok": bool(emb.get("ok")), "geprueft": bool(emb.get("checked")), "fehler": _kurz(emb.get("error"), 200) or None},
        "dreaming": {
            "an": bool(traum.get("enabled")), "phasen": phasen,
            "kurzzeit": int(_zahl(traum.get("shortTermCount"))), "signale": int(_zahl(traum.get("totalSignalCount"))),
            "uebernommen": int(_zahl(traum.get("promotedTotal"))), "heute_uebernommen": int(_zahl(traum.get("promotedToday"))),
        },
    }
