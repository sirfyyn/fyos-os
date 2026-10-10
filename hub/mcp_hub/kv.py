"""kv — Schlüssel-Wert-Ablage der Plugins: Redis, wenn `REDIS_URL` gesetzt ist, sonst der Speicher des Prozesses.

Die Kern-Plugins (shell, werkstatt, Ereignisbus) brauchen nur wenige Redis-Befehle. Ohne Redis läuft der Hub trotzdem:
`klient()` liefert dann eine kleine Attrappe im Speicher (`SpeicherKv`), die genau diese Befehle versteht, samt
Ablaufzeiten. Sie gilt nur für diesen einen Prozess und überlebt keinen Neustart — für den Einzelplatz genau richtig;
mehrere Hub-Prozesse oder dauerhafte Daten brauchen `REDIS_URL`.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

_LOCK = threading.RLock()
_GETEILT: Optional["SpeicherKv"] = None


class SpeicherKv:
    """Redis-Teilmenge im Speicher (Zeichenketten, Listen, Hashes, Streams, Zähler) mit Ablaufzeiten."""

    def __init__(self, uhr: Any = time.time) -> None:
        self._uhr = uhr
        self._d: dict[str, Any] = {}
        self._bis: dict[str, float] = {}
        self._strom_zaehler = 0

    # -- Hilfen ---------------------------------------------------------------
    def _lebt(self, name: str) -> bool:
        bis = self._bis.get(name)
        if bis is not None and bis <= self._uhr():
            self._d.pop(name, None)
            self._bis.pop(name, None)
        return name in self._d

    @staticmethod
    def _text(x: Any) -> str:
        return x if isinstance(x, str) else (x.decode() if isinstance(x, bytes) else str(x))

    # -- Zeichenketten --------------------------------------------------------
    def ping(self) -> bool:
        return True

    def get(self, name: str) -> Optional[str]:
        with _LOCK:
            return self._d[name] if self._lebt(name) and isinstance(self._d[name], str) else None

    def set(self, name: str, wert: Any, ex: Optional[int] = None, nx: bool = False, **_: Any) -> Optional[bool]:
        with _LOCK:
            if nx and self._lebt(name):
                return None
            self._d[name] = self._text(wert)
            if ex:
                self._bis[name] = self._uhr() + ex
            else:
                self._bis.pop(name, None)
            return True

    def mget(self, namen: list[str]) -> list[Optional[str]]:
        return [self.get(n) for n in namen]

    def incr(self, name: str) -> int:
        with _LOCK:
            n = int(self._d[name]) + 1 if self._lebt(name) else 1
            self._d[name] = str(n)
            return n

    def exists(self, *namen: str) -> int:
        with _LOCK:
            return sum(1 for n in namen if self._lebt(n))

    def delete(self, *namen: str) -> int:
        with _LOCK:
            n = 0
            for name in namen:
                if self._lebt(name):
                    n += 1
                self._d.pop(name, None)
                self._bis.pop(name, None)
            return n

    def expire(self, name: str, sekunden: int) -> bool:
        with _LOCK:
            if not self._lebt(name):
                return False
            self._bis[name] = self._uhr() + sekunden
            return True

    # -- Listen ---------------------------------------------------------------
    def _liste(self, name: str) -> list[str]:
        if not self._lebt(name) or not isinstance(self._d[name], list):
            self._d[name] = []
            self._bis.pop(name, None)
        return self._d[name]

    def rpush(self, name: str, *werte: Any) -> int:
        with _LOCK:
            liste = self._liste(name)
            liste.extend(self._text(w) for w in werte)
            return len(liste)

    def lpush(self, name: str, *werte: Any) -> int:
        with _LOCK:
            liste = self._liste(name)
            for w in werte:
                liste.insert(0, self._text(w))
            return len(liste)

    def lrange(self, name: str, start: int, ende: int) -> list[str]:
        with _LOCK:
            if not self._lebt(name) or not isinstance(self._d[name], list):
                return []
            liste = self._d[name]
            n = len(liste)
            von = max(0, start if start >= 0 else n + start)
            bis = (ende if ende >= 0 else n + ende) + 1
            return list(liste[von:bis])

    def ltrim(self, name: str, start: int, ende: int) -> bool:
        with _LOCK:
            if self._lebt(name) and isinstance(self._d[name], list):
                self._d[name] = self.lrange(name, start, ende)
            return True

    # -- Hashes ---------------------------------------------------------------
    def _hash(self, name: str) -> dict[str, str]:
        if not self._lebt(name) or not isinstance(self._d[name], dict):
            self._d[name] = {}
            self._bis.pop(name, None)
        return self._d[name]

    def hset(self, name: str, key: Optional[str] = None, value: Any = None, mapping: Optional[dict] = None) -> int:
        with _LOCK:
            h = self._hash(name)
            neu = 0
            paare = dict(mapping or {})
            if key is not None:
                paare[key] = value
            for k, v in paare.items():
                neu += k not in h
                h[self._text(k)] = self._text(v)
            return neu

    def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        with _LOCK:
            h = self._hash(name)
            wert = int(h.get(self._text(key), "0")) + int(amount)
            h[self._text(key)] = str(wert)
            return wert

    def hgetall(self, name: str) -> dict[str, str]:
        with _LOCK:
            return dict(self._d[name]) if self._lebt(name) and isinstance(self._d[name], dict) else {}

    def hdel(self, name: str, *keys: str) -> int:
        with _LOCK:
            if not self._lebt(name) or not isinstance(self._d[name], dict):
                return 0
            return sum(1 for k in keys if self._d[name].pop(k, None) is not None)

    def hexists(self, name: str, key: str) -> bool:
        with _LOCK:
            return self._lebt(name) and isinstance(self._d[name], dict) and key in self._d[name]

    # -- Streams --------------------------------------------------------------
    def xadd(self, name: str, felder: dict, maxlen: Optional[int] = None, approximate: bool = True, **_: Any) -> str:
        with _LOCK:
            liste = self._liste(name)
            self._strom_zaehler += 1
            eid = f"{int(self._uhr() * 1000)}-{self._strom_zaehler}"
            liste.append((eid, {self._text(k): self._text(v) for k, v in felder.items()}))  # type: ignore[arg-type]
            if maxlen and len(liste) > maxlen:
                del liste[: len(liste) - maxlen]
            return eid

    def xrevrange(self, name: str, count: Optional[int] = None, **_: Any) -> list[tuple[str, dict[str, str]]]:
        with _LOCK:
            if not self._lebt(name) or not isinstance(self._d[name], list):
                return []
            umgekehrt = list(reversed(self._d[name]))
            return umgekehrt[:count] if count else umgekehrt


def klient(url: Optional[str] = None) -> Any:
    """Redis-Klient (`decode_responses=True`) für `url` oder `REDIS_URL`; ohne beides die gemeinsame Speicher-Attrappe."""
    import os

    adresse = url if url is not None else os.getenv("REDIS_URL", "")
    if adresse:
        import redis  # noqa: PLC0415

        return redis.Redis.from_url(adresse, socket_timeout=3, decode_responses=True)
    global _GETEILT
    with _LOCK:
        if _GETEILT is None:
            _GETEILT = SpeicherKv()
        return _GETEILT


def ist_speicher(c: Any) -> bool:
    return isinstance(c, SpeicherKv)
