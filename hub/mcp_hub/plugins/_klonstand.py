"""Stand eines Repo-Klons, aus dem Plugins lesen (skills, werkstatt).

Liegen Skills und Skripte in einem Git-Klon, der von aussen aktuell gehalten wird (etwa von einem Sidecar oder einem
Zeitplan), nennen die lesenden Plugins in ihrer Antwort `stand` = {commit, datum}. So sieht der Leser, wie alt das
Gelesene ist, und ein Verzeichnis-Cache wird beim neuen Commit verworfen.

Ein Fehler (kein Klon, kein Git, kein Repo) ergibt `None` - nie eine Ausnahme.

Einstellung ueber die Umgebung:
    FYOS_KLONSTAND_TTL_S   Lebensdauer des Zwischenspeichers in Sekunden (Vorgabe 60; 0 = nie zwischenspeichern)
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

CACHE_S = 60.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, str] | None]] = {}


def _frist() -> float:
    try:
        return max(0.0, float(os.getenv("FYOS_KLONSTAND_TTL_S", CACHE_S)))
    except ValueError:
        return CACHE_S


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout.strip()


def stand(repo: Path | str) -> dict[str, str] | None:
    """{commit (kurz), datum (Commitzeit ISO)} von HEAD im Klon, kurz zwischengespeichert; bei Fehler None."""
    key = str(repo)
    jetzt = time.monotonic()
    frist = _frist()
    with _lock:
        e = _cache.get(key)
        if e and jetzt - e[0] < frist:
            return e[1]
    try:
        zeile = _git(Path(repo), "log", "-1", "--format=%h %cI", "HEAD")
        commit, datum = zeile.split(" ", 1)
        wert: dict[str, str] | None = {"commit": commit, "datum": datum}
    except Exception:  # noqa: BLE001 - der Stand ist Beigabe, er darf keine Antwort kippen
        wert = None
    with _lock:
        _cache[key] = (jetzt, wert)
    return wert


def commit(repo: Path | str) -> str | None:
    """Kurz-Commit von HEAD (aus `stand`), None bei Fehler - Schluessel zum Verwerfen von Verzeichnis-Caches."""
    s = stand(repo)
    return s["commit"] if s else None


def vergessen() -> None:
    """Zwischenspeicher leeren (Tests)."""
    with _lock:
        _cache.clear()


__all__ = ["stand", "commit", "vergessen"]
