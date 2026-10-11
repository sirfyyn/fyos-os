"""Optionale Dienste neben dem Agenten: Weiche, Reranker, Mund und Ohr.

Keiner dieser Dienste ist Pflicht. Fehlt die Adresse oder antwortet der Dienst nicht, arbeitet alles wie ohne ihn
(Fail-open): die Weiche lässt den Weckruf durch, der Reranker lässt die Reihenfolge des Rangmischens stehen. Mund und Ohr
nutzt der Agent selbst (Sprachausgabe, Spracheingabe); der Hub prüft sie nur, damit ein Ausfall sichtbar ist.

Adressen (Konfiguration ``dienste`` oder Umgebung):

    weiche_url   FYOS_WEICHE_URL    ``POST <url>/entscheiden``  ``{"umschlag": {...}}`` -> ``{"wecken": bool, "grund": "..."}``
    rerank_url   FYOS_RERANK_URL    ``POST <url>/rerank``       ``{"query": "...", "documents": ["..."]}`` ->
                                    ``{"results": [{"index": 0, "score": 0.9}]}`` (auch eine nackte Liste)
    mund_url     FYOS_MUND_URL      Sprachausgabe (OpenAI-kompatibel, ``/v1/audio/speech``), vom Agenten genutzt
    ohr_url      FYOS_OHR_URL       Spracheingabe (OpenAI-kompatibel, ``/v1/audio/transcriptions``), vom Agenten genutzt

Die Weiche gilt nur für Weckregeln mit ``weiche: true``; sie entscheidet je Ereignis über Namen und Zahlen des Umschlags
(Thema, Schwere, von, Verweis), nie über Inhalte.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger(__name__)

NAMEN = ("weiche", "rerank", "mund", "ohr")
UMGEBUNG = {"weiche": "FYOS_WEICHE_URL", "rerank": "FYOS_RERANK_URL", "mund": "FYOS_MUND_URL", "ohr": "FYOS_OHR_URL"}
ZEIT_S = {"weiche": 2.0, "rerank": 3.0, "mund": 3.0, "ohr": 3.0}
UMSCHLAG_FELDER = ("id", "strom", "thema", "zeit", "zeit_unix", "schwere", "quelle", "verweis", "von")
DOKUMENT_MAX = 600


def adressen(cfg: dict[str, Any] | None) -> dict[str, str]:
    """Adresse je Dienst: Konfiguration vor Umgebung, ohne Schrägstrich am Ende; leer heißt nicht eingerichtet."""
    cfg = cfg or {}
    aus: dict[str, str] = {}
    for n in NAMEN:
        url = str(cfg.get(f"{n}_url") or os.getenv(UMGEBUNG[n]) or "").strip().rstrip("/")
        if url:
            aus[n] = url
    return aus


def _post(url: str, koerper: dict[str, Any], zeit_s: float) -> Any:
    daten = json.dumps(koerper).encode()
    anfrage = urllib.request.Request(url, data=daten, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=zeit_s) as antwort:  # noqa: S310 -- Adresse aus der eigenen Konfiguration
        return json.loads(antwort.read(1_000_000) or b"null")


def _get(url: str, zeit_s: float) -> int:
    """HTTP-Status; ein Fehlerstatus des Dienstes zählt als erreicht, nur kein Kontakt wirft."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=zeit_s) as antwort:  # noqa: S310
            return int(antwort.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


class Dienste:
    """Die optionalen Dienste eines Hubs, mit Messwerten je Dienst."""

    def __init__(self, cfg: dict[str, Any] | None = None, *, post: Callable[[str, dict[str, Any], float], Any] | None = None,
                 get: Callable[[str, float], int] | None = None) -> None:
        self.urls = adressen(cfg)
        self._post = post or _post
        self._get = get or _get
        self.zaehler: dict[str, dict[str, Any]] = {n: {"anfragen": 0, "fehler": 0, "ms_zuletzt": 0, "fehler_zuletzt": None}
                                                  for n in NAMEN}
        self.weiche_urteile = {"wecken": 0, "ruhig": 0, "offen": 0}

    def eingerichtet(self, name: str) -> bool:
        return name in self.urls

    def _messen(self, name: str, ok: bool, ms: float, fehler: str = "") -> None:
        z = self.zaehler[name]
        z["anfragen"] += 1
        z["fehler"] += 0 if ok else 1
        z["ms_zuletzt"] = round(ms)
        z["fehler_zuletzt"] = fehler[:160] or None if not ok else None

    # Weiche -----------------------------------------------------------------------------------
    def weiche(self, umschlag: dict[str, Any]) -> tuple[bool, str]:
        """Soll dieses Ereignis wecken? Ohne Dienst oder bei Ausfall: ja (Fail-open). Zweiter Wert: Begründung."""
        if not self.eingerichtet("weiche"):
            return True, "keine Weiche"
        t0 = time.monotonic()
        try:
            roh = self._post(self.urls["weiche"] + "/entscheiden",
                             {"umschlag": {k: umschlag.get(k) for k in UMSCHLAG_FELDER}}, ZEIT_S["weiche"])
            if not isinstance(roh, dict) or not isinstance(roh.get("wecken"), bool):
                raise ValueError("Antwort ohne wecken")
        except Exception as exc:  # noqa: BLE001 -- fällt die Weiche aus, weckt der Hub wie ohne sie
            self._messen("weiche", False, (time.monotonic() - t0) * 1000, f"{type(exc).__name__}: {exc}")
            self.weiche_urteile["offen"] += 1
            return True, "Weiche nicht erreichbar, offen"
        self._messen("weiche", True, (time.monotonic() - t0) * 1000)
        self.weiche_urteile["wecken" if roh["wecken"] else "ruhig"] += 1
        return roh["wecken"], " ".join(str(roh.get("grund") or "").split())[:160]

    # Reranker ---------------------------------------------------------------------------------
    def rerank(self, frage: str, treffer: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Treffer nach Reranker-Punkten neu geordnet. Ohne Dienst oder bei Ausfall bleibt die Reihenfolge; zweiter Wert
        ist der Vermerk für die Messung (``ok``, ``grund``, ``ms``)."""
        if not self.eingerichtet("rerank"):
            return treffer, {"ok": False, "grund": "nicht eingerichtet", "ms": 0}
        if len(treffer) < 2:
            return treffer, {"ok": True, "grund": "weniger als zwei Treffer", "ms": 0}
        t0 = time.monotonic()
        try:
            texte = [f"{t.get('titel') or ''}. {t.get('auszug') or ''}"[:DOKUMENT_MAX] for t in treffer]
            roh = self._post(self.urls["rerank"] + "/rerank", {"query": frage, "documents": texte}, ZEIT_S["rerank"])
            liste = roh if isinstance(roh, list) else (roh.get("results") or roh.get("data") or []) if isinstance(roh, dict) else []
            punkte: dict[int, float] = {}
            for r in liste:
                i = int(r["index"])
                if 0 <= i < len(treffer):
                    punkte[i] = float(r.get("score", r.get("relevance_score", 0.0)))
            if not punkte:
                raise ValueError("Antwort ohne Punkte")
        except Exception as exc:  # noqa: BLE001 -- ohne Reranker bleibt das Rangmischen
            ms = (time.monotonic() - t0) * 1000
            self._messen("rerank", False, ms, f"{type(exc).__name__}: {exc}")
            return treffer, {"ok": False, "grund": f"{type(exc).__name__}: {exc}"[:160], "ms": round(ms)}
        ms = (time.monotonic() - t0) * 1000
        self._messen("rerank", True, ms)
        ordnung = sorted(range(len(treffer)), key=lambda i: (-punkte.get(i, float("-inf")), i))
        return ([{**treffer[i], "rerank_punkte": round(punkte[i], 4) if i in punkte else None} for i in ordnung],
                {"ok": True, "ms": round(ms)})

    # Prüfung ----------------------------------------------------------------------------------
    def pruefen(self, proben: bool = True) -> dict[str, Any]:
        """Je Dienst: eingerichtet, erreichbar (kurze Probe), Zähler. Die Probe schickt keine Nutzdaten."""
        aus: dict[str, Any] = {}
        for n in NAMEN:
            eintrag: dict[str, Any] = {"eingerichtet": self.eingerichtet(n), "adresse": self.urls.get(n),
                                       "gemessen": dict(self.zaehler[n])}
            if self.eingerichtet(n) and proben:
                t0 = time.monotonic()
                try:
                    status = self._get(self.urls[n], 2.0)
                    eintrag.update(erreichbar=True, status=status, ms=round((time.monotonic() - t0) * 1000))
                except Exception as exc:  # noqa: BLE001
                    eintrag.update(erreichbar=False, fehler=f"{type(exc).__name__}: {exc}"[:160])
            else:
                eintrag["erreichbar"] = None
            aus[n] = eintrag
        return aus
