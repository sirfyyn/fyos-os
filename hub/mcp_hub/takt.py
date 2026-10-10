"""takt — Leitplanken und Laufprotokoll für die wiederkehrenden Aufgaben (Routinen) der Plugins.

Der Hub hat keinen zentralen Zeitplaner: Jedes Plugin fährt seine Takte selbst und meldet sie über
``HubPlugin.zeitplan()`` (Sammelansicht ``mcp.zeitplan``, Reihen ``fyos_zeitplan_*`` in ``/metrics``). Dieser Baustein
gibt einem Takt zwei optionale Leitplanken, damit eine Routine nachts nicht läuft und nicht ohne Ende:

    max_pro_tag   höchstens so viele Läufe je Kalendertag (ganze Zahl ab 1)
    fenster       nur zwischen diesen Uhrzeiten, ``"07:00-22:00"`` (Anfang eingeschlossen, Ende ausgeschlossen);
                  ein Fenster über Mitternacht geht ebenso (``"22:00-06:00"``), ``"24:00"`` ist als Ende erlaubt

Tag und Uhrzeit gelten in der Zeitzone des Hub-Prozesses (Umgebungsvariable ``TZ``, im Container ohne Angabe UTC) —
dieselbe, nach der der Hub auch sonst Tage zählt. Ein Lauf außerhalb des Fensters oder über dem Tageslimit wird nicht
ausgeführt, sondern gezählt (Grund ``fenster`` oder ``limit``); das Fenster wird zuerst geprüft, ein Lauf außerhalb
verbraucht also nichts vom Tageslimit. Ohne Grenzen läuft jeder Lauf wie bisher.

So bindet ein Plugin einen Takt an (statt ``tun()`` direkt zu rufen)::

    self._waechter = Waechter(self.name, cfg.get("takt_grenzen"))       # {"abgleich": {"fenster": "07:00-22:00"}}
    lauf = self._waechter.ausfuehren("abgleich", tun)                   # Lauf(gelaufen=False, grund="fenster") = übersprungen
    ...
    {"id": "abgleich", "name": "…", "takt": "alle 60 s", **self._waechter.felder("abgleich")}   # in zeitplan()

Das Laufprotokoll liegt im Hub-Speicher (``mcp_hub.kv``: Redis, sonst der Speicher des Prozesses) und ist knapp:

    fyos:takt:<plugin>:tag:<JJJJ-MM-TT>   Hash, Zähler je Takt (``<takt>`` = Läufe, ``<takt>|<grund>`` = Übersprungene),
                                          läuft nach 3 Tagen ab
    fyos:takt:<plugin>:<takt>:laeufe      Liste der letzten 20 Läufe (Start, Dauer, Ergebnis), neueste zuerst,
                                          läuft nach 7 Tagen ohne Lauf ab

Der Speicher ist nur Zubehör: Scheitert ein Zugriff, läuft der Takt trotzdem; den Tageszähler führt der Wächter dann im
Prozess weiter (ab 0) und lässt den Speicher 30 s in Ruhe, statt bei jedem Lauf auf die Zeitüberschreitung zu warten.
Ohne ``REDIS_URL`` gelten die Zähler nur bis zum Neustart des Hubs.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from . import kv as _kv
from .audit_log import schwaerzen
from .plugin import meldet_fehler

logger = logging.getLogger(__name__)

PRAEFIX = "fyos:takt:"
PROTOKOLL_MAX = 20  # Läufe je Takt im Protokoll (Kappung)
PROTOKOLL_ANZEIGE = 5  # so viele davon trägt ein Eintrag von zeitplan() (felder)
PROTOKOLL_TTL_S = 7 * 86400
TAG_TTL_S = 3 * 86400
RUHE_S = 30.0  # so lange bleibt ein gestörter Speicher unberührt
GRUENDE = ("fenster", "limit")

_FENSTER = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")
_SCHLUESSEL = ("max_pro_tag", "fenster")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class GrenzenFehler(ValueError):
    """Eine Grenze ist nicht lesbar: Tippfehler im Schlüssel, ``fenster: "abends"``, ``max_pro_tag: 0``."""


def _uhr_text(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _minute(stunde: str, minute: str, ende: bool) -> int | None:
    st, mi = int(stunde), int(minute)
    if mi > 59 or st > 24 or (st == 24 and (mi != 0 or not ende)):
        return None
    return st * 60 + mi


def fenster_lesen(text: Any) -> tuple[int, int]:
    """``"07:00-22:00"`` → (420, 1320) als Minuten des Tages; wirft ``GrenzenFehler``."""
    treffer = _FENSTER.match(str(text))
    von = bis = None
    if treffer:
        von = _minute(treffer[1], treffer[2], ende=False)
        bis = _minute(treffer[3], treffer[4], ende=True)
    if von is None or bis is None:
        raise GrenzenFehler(f'fenster {text!r}: erwartet "HH:MM-HH:MM" wie "07:00-22:00" (Uhrzeiten von 00:00 bis 24:00)')
    if von == bis:
        raise GrenzenFehler(f'fenster {text!r}: Anfang und Ende sind gleich (ganztägig ist "00:00-24:00", also keines nötig)')
    return von, bis


def _tageslimit(wert: Any) -> int:
    z: Any = wert
    if isinstance(z, str) and z.strip().isdigit():
        z = int(z.strip())
    if isinstance(z, float) and z.is_integer():
        z = int(z)
    if isinstance(z, bool) or not isinstance(z, int) or z < 1:
        raise GrenzenFehler(f"max_pro_tag {wert!r}: erwartet eine ganze Zahl ab 1")
    return z


@dataclass(frozen=True)
class Grenzen:
    """Die Leitplanken eines Takts; ohne Angaben ist alles erlaubt."""

    max_pro_tag: int | None = None
    von: int | None = None  # Minute des Tages, eingeschlossen
    bis: int | None = None  # Minute des Tages, ausgeschlossen (1440 = Mitternacht am Ende des Tages)

    @classmethod
    def lesen(cls, roh: Any, wo: str = "") -> "Grenzen":
        """Aus einer Konfiguration ``{"max_pro_tag": 12, "fenster": "07:00-22:00"}``; ``None`` oder leer = keine Grenzen."""
        vor = f"{wo}: " if wo else ""
        if roh is None or roh == {}:
            return cls()
        if not isinstance(roh, Mapping):
            raise GrenzenFehler(f"{vor}Grenzen sind ein Eintrag mit max_pro_tag und/oder fenster, nicht {type(roh).__name__}")
        unbekannt = sorted(str(k) for k in roh if k not in _SCHLUESSEL)
        if unbekannt:
            raise GrenzenFehler(f"{vor}unbekannt: {', '.join(unbekannt)} (erlaubt: {', '.join(_SCHLUESSEL)})")
        try:
            limit = None if roh.get("max_pro_tag") in (None, "") else _tageslimit(roh["max_pro_tag"])
            fenster = None if roh.get("fenster") in (None, "") else fenster_lesen(roh["fenster"])
        except GrenzenFehler as exc:
            raise GrenzenFehler(f"{vor}{exc}") from None
        return cls(limit, *(fenster or (None, None)))

    @property
    def leer(self) -> bool:
        return self.max_pro_tag is None and self.von is None

    @property
    def fenster(self) -> str | None:
        return None if self.von is None or self.bis is None else f"{_uhr_text(self.von)}-{_uhr_text(self.bis)}"

    def im_fenster(self, minute: int) -> bool:
        """Liegt diese Minute des Tages (0–1439) im Fenster? Ohne Fenster immer."""
        if self.von is None or self.bis is None:
            return True
        if self.von < self.bis:
            return self.von <= minute < self.bis
        return minute >= self.von or minute < self.bis  # über Mitternacht


@dataclass
class Lauf:
    """Ergebnis von ``Waechter.ausfuehren``: gelaufen (dann ``wert`` = Rückgabe) oder übersprungen (dann ``grund``)."""

    gelaufen: bool
    grund: str | None = None
    wert: Any = None


def _text(x: Any) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _ganz(wert: Any) -> int:
    try:
        return max(0, int(_text(wert)))
    except (TypeError, ValueError):
        return 0


def _fehlergrund(wert: Any) -> str | None:
    """Meldet das Ergebnis eines Laufs einen Fehlschlag (``{"ok": false, …}``)? Dann der Grund, sonst ``None``."""
    grund = meldet_fehler(wert)
    if grund == "ok=false" and isinstance(wert, dict) and wert.get("satz"):
        return str(wert["satz"])
    return grund


class Waechter:
    """Leitplanken und Laufprotokoll der Takte eines Plugins (siehe Moduldoku).

    ``grenzen``: ``{takt: {"max_pro_tag": …, "fenster": …}}``; mit ``takte`` werden nur diese Namen angenommen (so
    fällt ein Tippfehler beim Start auf, statt eine Grenze still zu verlieren). ``speicher``: Aufruf ohne Argumente,
    der den kv-Klienten liefert (Vorgabe ``kv.klient``). ``uhr``: Sekunden seit 1970, für Tests austauschbar.
    """

    def __init__(
        self,
        plugin: str,
        grenzen: Mapping[str, Any] | None = None,
        speicher: Callable[[], Any] | None = None,
        uhr: Callable[[], float] = time.time,
        takte: Iterable[str] | None = None,
    ) -> None:
        if grenzen is not None and not isinstance(grenzen, Mapping):
            raise GrenzenFehler(f"{plugin}: takt_grenzen ist eine Zuordnung Takt → Grenzen, nicht {type(grenzen).__name__}")
        gueltig = None if takte is None else tuple(takte)
        self.plugin = plugin
        self._grenzen: dict[str, Grenzen] = {}
        for takt, roh in (grenzen or {}).items():
            if gueltig is not None and takt not in gueltig:
                raise GrenzenFehler(f"{plugin}: {takt!r} ist kein Takt dieses Plugins (bekannt: {', '.join(gueltig)})")
            self._grenzen[str(takt)] = Grenzen.lesen(roh, f"{plugin}.{takt}")
        self._fabrik = speicher or _kv.klient
        self._klient: Any = None
        self._uhr = uhr
        self._sperre = threading.Lock()
        self._ruht_bis = 0.0  # time.monotonic()
        self._notzaehler: dict[tuple[str, str], int] = {}  # (Tag, Feld) → Zähler, solange der Speicher nicht antwortet

    # ── Grenzen und Uhr ───────────────────────────────────────────────────────────────────────

    def grenzen(self, takt: str) -> Grenzen:
        return self._grenzen.get(takt, Grenzen())

    def _jetzt(self) -> tuple[str, int]:
        """(Tag ``JJJJ-MM-TT``, Minute des Tages) in der Zeitzone des Prozesses."""
        lokal = time.localtime(self._uhr())
        return time.strftime("%Y-%m-%d", lokal), lokal.tm_hour * 60 + lokal.tm_min

    @staticmethod
    def _pruefen(takt: str) -> str:
        if not isinstance(takt, str) or not _NAME.match(takt):
            raise ValueError(f"Takt-Name {takt!r}: erlaubt sind Buchstaben, Ziffern, _ . - (bis 64 Zeichen)")
        return takt

    # ── Speicher (nur Zubehör) ────────────────────────────────────────────────────────────────

    def _versuche(self, fn: Callable[[Any], Any]) -> Any:
        """Ein Zugriff auf den Speicher; ``None``, wenn er nicht klappt oder gerade ruht (kein Wert von ``fn`` ist ``None``)."""
        if time.monotonic() < self._ruht_bis:
            return None
        try:
            if self._klient is None:
                self._klient = self._fabrik()
            return fn(self._klient)
        except Exception as exc:  # noqa: BLE001 — der Speicher darf keinen Takt aufhalten
            self._ruht_bis = time.monotonic() + RUHE_S
            logger.warning("takt(%s): Speicher antwortet nicht, Zähler laufen im Prozess weiter: %s", self.plugin, exc)
            return None

    def _tagesschluessel(self, tag: str) -> str:
        return f"{PRAEFIX}{self.plugin}:tag:{tag}"

    def _protokollschluessel(self, takt: str) -> str:
        return f"{PRAEFIX}{self.plugin}:{takt}:laeufe"

    def _zaehlen(self, tag: str, feld: str, schritt: int = 1) -> int:
        """Zähler ``feld`` des Tages um ``schritt`` ändern; gibt den neuen Stand zurück."""
        schluessel = self._tagesschluessel(tag)

        def tun(c: Any) -> int:
            n = int(c.hincrby(schluessel, feld, schritt))
            c.expire(schluessel, TAG_TTL_S)
            return n

        n = self._versuche(tun)
        if n is not None:
            return n
        with self._sperre:
            self._notzaehler = {k: v for k, v in self._notzaehler.items() if k[0] == tag}  # frühere Tage vergessen
            neu = self._notzaehler.get((tag, feld), 0) + schritt
            self._notzaehler[(tag, feld)] = neu
            return neu

    def _tageswerte(self, tag: str) -> dict[str, str]:
        werte = self._versuche(lambda c: c.hgetall(self._tagesschluessel(tag)))
        if werte is None:
            with self._sperre:
                return {feld: str(n) for (t, feld), n in self._notzaehler.items() if t == tag}
        return {_text(k): _text(v) for k, v in werte.items()}

    # ── Läufe ─────────────────────────────────────────────────────────────────────────────────

    def zulassen(self, takt: str) -> str | None:
        """Darf dieser Lauf jetzt? ``None``: ja (und er ist gezählt); sonst der Grund (``fenster``/``limit``), gezählt als übersprungen."""
        takt = self._pruefen(takt)
        g = self.grenzen(takt)
        tag, minute = self._jetzt()
        if not g.im_fenster(minute):
            self._zaehlen(tag, f"{takt}|fenster")
            return "fenster"
        n = self._zaehlen(tag, takt)
        if g.max_pro_tag is not None and n > g.max_pro_tag:
            self._zaehlen(tag, takt, -1)  # der Lauf findet nicht statt, also auch kein Lauf mehr heute
            self._zaehlen(tag, f"{takt}|limit")
            return "limit"
        return None

    def ausfuehren(self, takt: str, tun: Callable[[], Any]) -> Lauf:
        """``tun()`` ausführen, wenn Fenster und Tageslimit es erlauben; sonst überspringen und zählen.

        Das Protokoll bekommt Start, Dauer und Ergebnis. Wirft ``tun``, steht der Fehler (gekürzt, ohne Geheimnisse)
        im Protokoll und die Ausnahme geht unverändert weiter; ein Rückgabewert ``{"ok": false, …}`` gilt als Fehler.
        """
        grund = self.zulassen(takt)
        if grund:
            return Lauf(False, grund)
        start, t0 = self._uhr(), time.monotonic()
        try:
            wert = tun()
        except Exception as exc:
            self._protokollieren(takt, start, time.monotonic() - t0, "fehler", f"{type(exc).__name__}: {exc}")
            raise
        fehler = _fehlergrund(wert)
        self._protokollieren(takt, start, time.monotonic() - t0, "fehler" if fehler else "ok", fehler or "")
        return Lauf(True, None, wert)

    def _protokollieren(self, takt: str, start: float, dauer: float, ergebnis: str, fehler: str = "") -> None:
        eintrag: dict[str, Any] = {"start": int(start), "dauer_s": round(dauer, 2), "ergebnis": ergebnis}
        if fehler:
            eintrag["fehler"] = schwaerzen(" ".join(fehler.split()))[:120]
        text = json.dumps(eintrag, ensure_ascii=False, separators=(",", ":"))
        schluessel = self._protokollschluessel(takt)

        def tun(c: Any) -> bool:
            c.lpush(schluessel, text)
            c.ltrim(schluessel, 0, PROTOKOLL_MAX - 1)
            c.expire(schluessel, PROTOKOLL_TTL_S)
            return True

        self._versuche(tun)

    # ── Beitrag zu zeitplan() ─────────────────────────────────────────────────────────────────

    def protokoll(self, takt: str, anzahl: int = PROTOKOLL_ANZEIGE) -> list[dict[str, Any]]:
        """Die letzten Läufe des Takts, neueste zuerst: ``[{"start", "dauer_s", "ergebnis", "fehler"?}]``."""
        schluessel = self._protokollschluessel(self._pruefen(takt))
        if anzahl < 1:
            return []
        roh = self._versuche(lambda c: c.lrange(schluessel, 0, anzahl - 1)) or []
        out: list[dict[str, Any]] = []
        for zeile in roh:
            try:
                e = json.loads(_text(zeile))
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
        return out

    def felder(self, takt: str) -> dict[str, Any]:
        """Die Felder, die ein Eintrag von ``zeitplan()`` für diesen Takt zusätzlich trägt.

        ``max_pro_tag`` und ``fenster`` (die Grenzen oder ``None``), ``ruht`` (``fenster``/``limit``, wenn der Takt
        jetzt nicht laufen dürfte), ``laeufe_heute``, ``uebersprungen`` (heute, je Grund; konfigurierte Gründe auch
        mit 0) und ``protokoll`` (die letzten Läufe).
        """
        takt = self._pruefen(takt)
        g = self.grenzen(takt)
        tag, minute = self._jetzt()
        werte = self._tageswerte(tag)
        laeufe = _ganz(werte.get(takt))
        uebersprungen = {}
        for grund, gesetzt in (("fenster", g.von is not None), ("limit", g.max_pro_tag is not None)):
            n = _ganz(werte.get(f"{takt}|{grund}"))
            if gesetzt or n:
                uebersprungen[grund] = n
        ruht = None
        if not g.im_fenster(minute):
            ruht = "fenster"
        elif g.max_pro_tag is not None and laeufe >= g.max_pro_tag:
            ruht = "limit"
        return {
            "max_pro_tag": g.max_pro_tag,
            "fenster": g.fenster,
            "ruht": ruht,
            "laeufe_heute": laeufe,
            "uebersprungen": uebersprungen,
            "protokoll": self.protokoll(takt),
        }
