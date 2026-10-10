"""Suchspur: welche Suchanfrage führte zu welchem Werkzeug (Labels für die Werkzeugwahl).

Der größte Hebel für schnelle Antworten und wenig Token ist die Werkzeugwahl (Wortsuche in
``server.rangliste``). Das Audit-Log kennt aber weder die Suchanfrage noch eine Sitzung; ohne diese Labels
lässt sich Recall@k einer besseren Suche (BM25, Embeddings) nicht messen.

Ablauf: ``hub__search_tools`` merkt sich je Aufrufer die letzte Suche (Anfrage + Rangliste) in
Redis (TTL 10 min, gilt über alle Hub-Replikas). Der nächste echte Werkzeugaufruf desselben
Aufrufers schließt sie ab: ein Datensatz ``{anfrage, kandidaten, gewaehlt, rang}`` landet in der
Liste ``fyos:hub:suchspur`` (die letzten 5000). ``rang`` ist die Position des gewählten Werkzeugs
in der damaligen Rangliste (0 = erster Treffer, -1 = nicht darunter).

Fail-open: ohne Redis passiert nichts, kein Aufruf wird langsamer oder scheitert deshalb. Gespeichert
wird nur die Suchanfrage und Werkzeugnamen, keine Argumente oder Ergebnisse.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

LISTE = "fyos:hub:suchspur"
OFFEN = "fyos:hub:suchspur:offen:"
HALTEN = 5000
FRIST_S = 600
KANDIDATEN = 20
# Meta-Werkzeuge schließen eine Suche nicht ab — gezählt wird erst das Werkzeug, das die Arbeit macht.
META = ("hub.", "skills.suchen", "werkstatt.suchen")

_client: Any = None
_versucht = False
_aus_bis = 0.0


def _redis() -> Any:
    global _client, _versucht
    if time.time() < _aus_bis:
        return None
    if not _versucht:
        _versucht = True
        if not os.getenv("REDIS_URL"):
            return None  # ohne REDIS_URL (Tests, Einzelplatz): keine Spur
        try:
            import redis  # noqa: PLC0415 — im Hub-Image vorhanden

            url = os.environ["REDIS_URL"]
            _client = redis.Redis.from_url(url, socket_timeout=1, decode_responses=True)
        except Exception as exc:  # noqa: BLE001
            logger.info("suchspur: kein Redis (%s) — Spur aus", exc)
            _client = None
    return _client


def _pause(exc: Exception) -> None:
    global _aus_bis
    _aus_bis = time.time() + 60
    logger.info("suchspur: Redis-Fehler %s — 60 s Pause", exc)


def merke_suche(aufrufer: str, anfrage: str, namen: list[str], r: Any = None) -> None:
    """Letzte Suche dieses Aufrufers vormerken (leere Anfrage = Katalog blättern, nicht gemerkt)."""
    if not (anfrage or "").strip():
        return
    r = r if r is not None else _redis()
    if r is None:
        return
    satz = {"ts": round(time.time(), 1), "anfrage": anfrage.strip()[:200], "kandidaten": namen[:KANDIDATEN]}
    try:
        r.set(OFFEN + (aufrufer or "unknown"), json.dumps(satz, ensure_ascii=False), ex=FRIST_S)
    except Exception as exc:  # noqa: BLE001
        _pause(exc)


def schliesse_ab(aufrufer: str, werkzeug: str, r: Any = None) -> dict[str, Any] | None:
    """Erster echter Aufruf nach einer Suche: Datensatz anhängen. Gibt ihn zurück (für Tests)."""
    if not werkzeug or werkzeug.startswith(META):
        return None
    r = r if r is not None else _redis()
    if r is None:
        return None
    schluessel = OFFEN + (aufrufer or "unknown")
    try:
        roh = r.get(schluessel)
        if not roh:
            return None
        r.delete(schluessel)
        offen = json.loads(roh)
        kandidaten = list(offen.get("kandidaten") or [])
        satz = {
            "ts": round(time.time(), 1),
            "aufrufer": aufrufer or "unknown",
            "anfrage": offen.get("anfrage", ""),
            "kandidaten": kandidaten,
            "gewaehlt": werkzeug,
            "rang": kandidaten.index(werkzeug) if werkzeug in kandidaten else -1,
            "abstand_s": round(time.time() - float(offen.get("ts") or time.time()), 1),
        }
        r.lpush(LISTE, json.dumps(satz, ensure_ascii=False))
        r.ltrim(LISTE, 0, HALTEN - 1)
        return satz
    except Exception as exc:  # noqa: BLE001
        _pause(exc)
        return None
