"""zeitplan — was im Hub und in angebundenen Diensten wann läuft (``HubPlugin.zeitplan``).

Jedes Plugin meldet seine wiederkehrenden Aufgaben selbst; die OpenClaw-Brücke meldet über das Plugin ``openclaw``
die Cron-Aufträge des Agenten. Hier werden sie zu einer Liste zusammengeführt (Werkzeug ``mcp.zeitplan``,
Reihen in ``/metrics``). Führung: Aufgaben, die das Modell brauchen (ein Prompt an den Agenten), gehören in den
Cron von OpenClaw; Aufgaben ohne Modell (Abgleich, Aufräumen, Messen) in ein Hub-Plugin. Beide erscheinen hier.

Takte, die ihr Plugin über den Wächter (``mcp_hub.takt``) fährt, tragen zusätzlich ihre Leitplanken und das Laufprotokoll:
``max_pro_tag``, ``fenster``, ``ruht`` (``fenster``/``limit``, wenn sie jetzt nicht laufen dürften), ``laeufe_heute``,
``uebersprungen`` (heute, je Grund) und ``protokoll`` (die letzten Läufe). ``/metrics`` führt sie als
``fyos_zeitplan_laeufe_heute``, ``fyos_zeitplan_max_pro_tag`` und ``fyos_zeitplan_uebersprungen_total``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

STATUS = ("ok", "fehler")
PROTOKOLL_MAX = 10  # so viele Läufe trägt ein Eintrag höchstens


def _zahl(wert: Any) -> float | None:
    try:
        z = float(wert)
    except (TypeError, ValueError):
        return None
    return z if z > 0 else None


def _ganz(wert: Any, mindestens: int = 0) -> int | None:
    """Ganze Zahl ab ``mindestens``; alles andere (auch Wahrheitswerte) als None."""
    if isinstance(wert, bool):
        return None
    try:
        z = int(wert)
    except (TypeError, ValueError):
        return None
    return z if z >= mindestens else None


def _kurz(wert: Any, grenze: int) -> str | None:
    return " ".join(str(wert or "").split())[:grenze] or None


def _gruende(wert: Any) -> dict[str, int]:
    """``{"fenster": 3, "limit": 0}`` — Zähler der übersprungenen Läufe je Grund."""
    out: dict[str, int] = {}
    for grund, n in (wert.items() if isinstance(wert, dict) else ()):
        name, z = _kurz(grund, 30), _ganz(n)
        if name and z is not None:
            out[name] = z
    return out


def _protokoll(wert: Any) -> list[dict[str, Any]]:
    """Die letzten Läufe: ``[{"start", "dauer_s", "ergebnis", "fehler"?}]``, neueste zuerst, gekürzt."""
    out: list[dict[str, Any]] = []
    for lauf in wert if isinstance(wert, list) else []:
        if not isinstance(lauf, dict) or _zahl(lauf.get("start")) is None:
            continue
        e: dict[str, Any] = {"start": _zahl(lauf.get("start")), "dauer_s": _zahl(lauf.get("dauer_s")) or 0.0,
                             "ergebnis": _kurz(lauf.get("ergebnis"), 20)}
        if lauf.get("fehler"):
            e["fehler"] = _kurz(lauf["fehler"], 200)
        out.append(e)
        if len(out) >= PROTOKOLL_MAX:
            break
    return out


def eintrag(plugin: str, roh: dict[str, Any]) -> dict[str, Any]:
    """Ein Eintrag in fester Form (fehlende Felder als None)."""
    status = str(roh.get("letzter_status") or "").lower() or None
    if status not in STATUS:
        status = None
    fehler = roh.get("letzter_fehler")
    return {
        "id": f"{plugin}:{roh.get('id')}",
        "plugin": plugin,
        "quelle": str(roh.get("quelle") or plugin),
        "name": str(roh.get("name") or roh.get("id")),
        "beschreibung": " ".join(str(roh.get("beschreibung") or "").split())[:300],
        "takt": str(roh.get("takt") or ""),
        "an": bool(roh.get("an", True)),
        "naechster": _zahl(roh.get("naechster")),
        "letzter": _zahl(roh.get("letzter")),
        "letzter_status": status,
        "letzter_fehler": str(fehler)[:300] if fehler else None,
        "max_pro_tag": _ganz(roh.get("max_pro_tag"), 1),
        "fenster": _kurz(roh.get("fenster"), 20),
        "ruht": _kurz(roh.get("ruht"), 20),
        "laeufe_heute": _ganz(roh.get("laeufe_heute")),
        "uebersprungen": _gruende(roh.get("uebersprungen")),
        "protokoll": _protokoll(roh.get("protokoll")),
    }


def sammeln(registry: Any, quelle: str = "") -> dict[str, Any]:
    """Alle Einträge aller Plugins, nach nächstem Lauf sortiert; ein scheiterndes Plugin fehlt nur selbst."""
    eintraege: list[dict[str, Any]] = []
    fehler: dict[str, str] = {}
    for name, plugin in (getattr(registry, "plugins", None) or {}).items():
        holen = getattr(plugin, "zeitplan", None)
        if not callable(holen):
            continue
        try:
            roh = list(holen() or [])
        except Exception as exc:  # noqa: BLE001 — ein Plugin darf die Ansicht nicht kippen
            fehler[name] = f"{type(exc).__name__}: {exc}"[:200]
            logger.debug("zeitplan(%s) gescheitert: %s", name, exc)
            continue
        for r in roh:
            if isinstance(r, dict) and r.get("id") not in (None, ""):
                e = eintrag(name, r)
                if not quelle or e["quelle"] == quelle or e["plugin"] == quelle:
                    eintraege.append(e)
    eintraege.sort(key=lambda e: (e["naechster"] is None, e["naechster"] or 0.0, e["quelle"], e["name"]))
    jetzt = time.time()
    rot = [e for e in eintraege if e["letzter_status"] == "fehler"]
    quellen = sorted({e["quelle"] for e in eintraege})
    satz = f"{len(eintraege)} Aufgaben aus {len(quellen)} Quellen ({', '.join(quellen) or '–'})"
    if rot:
        satz += f"; zuletzt gescheitert: {', '.join(e['name'] for e in rot[:5])}"
    ruhend = [e for e in eintraege if e["ruht"]]
    if ruhend:
        satz += f"; ruhen gerade (Fenster oder Tageslimit): {', '.join(e['name'] for e in ruhend[:5])}"
    return {
        "satz": satz + ".",
        "anzahl": len(eintraege),
        "quellen": quellen,
        "eintraege": eintraege,
        "fehler": fehler,
        "stand": jetzt,
    }
