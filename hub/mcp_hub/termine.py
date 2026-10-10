"""Termine für Plugins: eine Quelle, gleich ob Kalender-Dienst oder Kalender-Plugin.

Plugins, die Termine zeigen (Leitstand, Tagesbrief, Startseite), tragen keine Adresse fest ein und sprechen auch kein
CalDAV: sie fragen hier. Wer Termine liefert, meldet sich an; die Leser wissen nichts voneinander.

**Terminformat** (Ergebnis von ``termine()`` und ``anlegen()``, jeder Termin ein ``dict``):

======================  ======================================================================================
``id``                  Kennung in der Quelle (nie leer)
``titel``               Titel in einer Zeile (``(ohne Titel)``, wenn die Quelle keinen nennt)
``start``               ganztägig: Datum ``JJJJ-MM-TT``; sonst Zeitstempel ISO 8601, mit Versatz, wenn die Quelle einen nennt
``ende``                wie ``start``; bei ganztägigen Terminen der Tag **nach** dem letzten Tag (wie iCalendar und Google)
``ganztaegig``          ``true`` | ``false``
``ort``                 Ort in einer Zeile, sonst ``""``
``kalender``            Name des Kalenders, sonst ``""``
``konto``               Name des Kontos oder der Quelle dahinter, sonst ``""``
======================  ======================================================================================

Ein Kalender (``kalender()``) heißt ``{id, name, konto, schreibbar}``.

**Reihenfolge der Quellen** (``quelle()``):

1. **Termin-Dienst**, wenn eine Adresse gesetzt ist (Argument ``url``, ein mit ``dienst_anmelden`` angemeldeter Dienst
   oder ``FYOS_TERMINE_URL``; Kopfzeile aus ``FYOS_TERMINE_KOPF``). Das ist die Ausbaustufe: ein eigener Dienst, der
   HTTP spricht wie ``GET /api/calendar/events?who=all&days=N`` (siehe ``Dienst``).
2. **Kalender-Plugin** als Ablage (Grundstufe, prozessintern): ein Hub-Plugin, das sich mit ``ablage_anmelden`` meldet,
   etwa ``fyos-plugin-kalender`` mit CalDAV- und ICS-Konten.
3. **Keine**: ``termine()``, ``kalender()`` und ``anlegen()`` melden ``NichtEingerichtet``.

Plugins fragen ``quelle()`` bei jedem Aufruf neu; das ist billig und nimmt eine Ablage mit, die sich erst nach ihnen
anmeldet.

**Drei Zustände, die Aufrufer trennen müssen.** Ein Ergebnis (auch die leere Liste) heißt: die Quelle hat geantwortet,
es gibt diese Termine. ``QuelleFehler``: die Quelle ist aus oder ohne Zugang, das ist nie „keine Termine“.
``NichtEingerichtet`` (ein ``QuelleFehler``): es gibt gar keine Quelle. Anders als bei den Vorgängen liefert die Quelle
„keine“ deshalb **keine leere Liste**, sondern wirft: wer vergisst, ``eingerichtet`` zu prüfen, zeigt nie fälschlich
einen freien Tag.

**Zeit.** Ganztägige Termine und Zeitpunkte ohne Versatz gelten in der Zeitzone des Hubs (``FYOS_ZEITZONE``, ein
IANA-Name wie ``Europe/Berlin``; ohne Angabe die des Rechners). ``von`` ist eingeschlossen, ``bis`` ausgeschlossen; ein
Termin gehört ins Fenster, wenn er es berührt.

**Fehler.** ``QuelleFehler`` erbt von ``vorgaenge.QuelleFehler``, damit ein Aufrufer beide Quellen mit einem
``except`` fängt (Text und ``status`` sind gleich gebaut). ``NichtEingerichtet`` erbt dagegen nur von
``termine.QuelleFehler``: wer „keine Vorgangs-Quelle“ fängt, soll nicht versehentlich „kein Kalender“ fangen.
``ValueError`` bedeutet falsche Eingabe.

**Umgebung** (bei jedem Aufruf gelesen):

* ``FYOS_TERMINE_URL``   Adresse des Termin-Dienstes (Ausbaustufe)
* ``FYOS_TERMINE_KOPF``  eine Kopfzeile für den Dienst, ``Name: Wert``
* ``FYOS_ZEITZONE``      Zeitzone des Hubs (IANA-Name oder ``UTC``)
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import math
import os
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from mcp_hub import vorgaenge
from mcp_hub.vorgaenge import kopf_aus

_log = logging.getLogger(__name__)

FRIST_LESEN_S = 8.0
FRIST_SCHREIBEN_S = 12.0
ANTWORT_MAX = 4 * 1024 * 1024
#: Längstes Fenster für ``termine()`` und längster einzelner Termin
FENSTER_MAX_TAGE = 366
#: So viele Termine liefert ``termine()`` höchstens
TERMINE_MAX = 1000
#: Wie viele Tage der Dienst höchstens in ``days`` annimmt (``start``/``end`` können mehr)
DIENST_TAGE_MAX = 90
TITEL_MAX = 200
ORT_MAX = 200
KALENDER_MAX = 200
BESCHREIBUNG_MAX = 2000
OHNE_TITEL = "(ohne Titel)"


class QuelleFehler(vorgaenge.QuelleFehler):
    """Die Quelle der Termine antwortet nicht wie vereinbart: aus, ohne Zugang, Netz, unerwarteter Status."""


class NichtEingerichtet(QuelleFehler):
    """Es gibt keine Quelle für Termine (kein Termin-Dienst, kein Kalender-Plugin)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text or (
            "Kein Kalender eingerichtet: weder ein Termin-Dienst (FYOS_TERMINE_URL) noch das Plugin kalender "
            "(Paket fyos-plugin-kalender mit FYOS_KALENDER_URL, FYOS_KALENDER_NUTZER und FYOS_KALENDER_PASSWORT)."
        ), 501)


class Ablage(Protocol):
    """Was ein Kalender-Plugin anbietet, das sich als Quelle anmeldet (Daten statt HTTP)."""

    def ablage_kalender(self) -> list[dict[str, Any]]:
        """Die Kalender: ``{id, name, konto, schreibbar}``."""
        ...

    def ablage_termine(self, von: datetime, bis: datetime, kalender: str | None = None) -> list[dict[str, Any]]:
        """Termine im Fenster ``[von, bis)`` im Terminformat; ``von`` und ``bis`` tragen einen Versatz. ``kalender``
        ist Name oder Kennung eines Kalenders (``None``: alle)."""
        ...

    def ablage_anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
        """Legt einen Termin an (``titel start ende ganztaegig ort beschreibung kalender``, schon geprüft) und liefert
        ihn im Terminformat."""
        ...


_sperre = threading.Lock()
_ablage: Ablage | None = None
_dienst: tuple[str, dict[str, str]] | None = None
_gewarnt: set[str] = set()


def ablage_anmelden(ablage: Ablage | None) -> None:
    """Ein Kalender-Plugin meldet sich als Quelle an; ``None`` meldet ab."""
    global _ablage
    with _sperre:
        _ablage = ablage


def angemeldete_ablage() -> Ablage | None:
    with _sperre:
        return _ablage


def dienst_anmelden(url: str | None, kopf: dict[str, str] | None = None) -> None:
    """Ein Plugin meldet einen Termin-Dienst an (Adresse und Kopfzeile); so fragen alle Plugins denselben Dienst.
    ``None`` meldet ab."""
    global _dienst
    with _sperre:
        _dienst = (url.strip().rstrip("/"), dict(kopf or {})) if url and url.strip() else None


def angemeldeter_dienst() -> tuple[str, dict[str, str]] | None:
    with _sperre:
        return _dienst


# ── Zeit ────────────────────────────────────────────────────────────────────────────────────────────────
def lokale_zone() -> tzinfo | None:
    """Die Zeitzone aus ``FYOS_ZEITZONE``; ``None``: keine oder unbekannte Angabe (dann gilt die des Rechners)."""
    name = (os.getenv("FYOS_ZEITZONE") or "").strip()
    if not name:
        return None
    if name.upper() in ("UTC", "Z"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — unbekannter Name oder keine Zeitzonen-Datenbank auf dem Rechner
        if name not in _gewarnt:
            _gewarnt.add(name)
            _log.warning("FYOS_ZEITZONE=%s ist unbekannt; es gilt die Zeitzone des Rechners", name[:60])
        return None


def lokalisiere(zeit: datetime) -> datetime:
    """Die Zeit mit Versatz; eine Zeit ohne Versatz gilt als Zeit des Hubs."""
    if zeit.tzinfo is not None and zeit.utcoffset() is not None:
        return zeit
    zone = lokale_zone()
    return zeit.replace(tzinfo=zone) if zone is not None else zeit.astimezone()


def _lies(wert: Any) -> date | datetime | None:
    """Datum (``JJJJ-MM-TT``) oder Zeitstempel (ISO 8601) aus einem Text; sonst ``None``."""
    if isinstance(wert, datetime):
        return wert
    if isinstance(wert, date):
        return wert
    t = str(wert or "").strip()
    if not t:
        return None
    try:
        if "T" not in t and " " not in t:
            return date.fromisoformat(t)
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def _zeit_eingabe(wert: Any, name: str) -> datetime:
    gelesen = _lies(wert)
    if gelesen is None:
        raise ValueError(f"{name}: keine gültige Zeit (ISO 8601, etwa 2026-10-12 oder 2026-10-12T09:00:00+02:00)")
    if not isinstance(gelesen, datetime):
        gelesen = datetime.combine(gelesen, time.min)
    return lokalisiere(gelesen)


def _fenster(von: Any, bis: Any) -> tuple[datetime, datetime]:
    a, b = _zeit_eingabe(von, "von"), _zeit_eingabe(bis, "bis")
    if b <= a:
        raise ValueError("bis muss nach von liegen")
    if b - a > timedelta(days=FENSTER_MAX_TAGE):
        raise ValueError(f"das Fenster ist länger als {FENSTER_MAX_TAGE} Tage")
    return a, b


def _tage(wert: Any) -> int:
    try:
        n = int(wert)
    except (TypeError, ValueError):
        raise ValueError("tage muss eine ganze Zahl sein") from None
    if not 1 <= n <= FENSTER_MAX_TAGE:
        raise ValueError(f"tage muss zwischen 1 und {FENSTER_MAX_TAGE} liegen")
    return n


def _spanne(t: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Beginn und Ende eines Termins im Terminformat als Zeiten mit Versatz; ``None``, wenn nicht lesbar."""
    s, e = _lies(t.get("start")), _lies(t.get("ende"))
    try:
        if t.get("ganztaegig") or not isinstance(s, datetime):
            if s is None:
                return None
            tag = s.date() if isinstance(s, datetime) else s
            ende_tag = (e.date() if isinstance(e, datetime) else e) if e is not None else tag + timedelta(days=1)
            a = lokalisiere(datetime.combine(tag, time.min))
            b = lokalisiere(datetime.combine(ende_tag, time.min))
        else:
            a = lokalisiere(s)
            b = lokalisiere(e) if isinstance(e, datetime) else a
    except (ValueError, OverflowError, OSError):
        return None
    return a, max(a, b)


def _im_fenster(t: dict[str, Any], von: datetime, bis: datetime) -> bool:
    spanne = _spanne(t)
    if spanne is None:
        return False
    a, b = spanne
    if a == b:
        return von <= a < bis
    return a < bis and b > von


def _sortierschluessel(t: dict[str, Any]) -> tuple[Any, ...]:
    spanne = _spanne(t)
    anfang = spanne[0].astimezone(timezone.utc) if spanne else datetime.max.replace(tzinfo=timezone.utc)
    return anfang, 0 if t.get("ganztaegig") else 1, str(t.get("titel") or "").casefold(), str(t.get("id") or "")


# ── Terminformat ────────────────────────────────────────────────────────────────────────────────────────
def _zeile(wert: Any, grenze: int | None = None) -> str:
    text = " ".join(str(wert).split()) if wert is not None else ""
    return text[:grenze] if grenze else text


def _zeit_text(wert: Any) -> str:
    """Start oder Ende, wie Dienste ihn liefern: Text oder ``{"dateTime": …}`` / ``{"date": …}`` (Google)."""
    if isinstance(wert, dict):
        wert = wert.get("dateTime") or wert.get("date")
    return str(wert or "").strip()


def termin_aus(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Bringt einen Termin in das Terminformat; ``None``, wenn er keinen lesbaren Beginn hat (dann ist er nicht
    einzuordnen). Fehlende Felder werden ergänzt, Zeiten vereinheitlicht."""
    start = _lies(_zeit_text(roh.get("start")))
    if start is None:
        return None
    ende = _lies(_zeit_text(roh.get("ende")))
    ganztaegig = bool(roh.get("ganztaegig")) or not isinstance(start, datetime)
    if ganztaegig:
        s = start.date() if isinstance(start, datetime) else start
        e = (ende.date() if isinstance(ende, datetime) else ende) if ende is not None else s + timedelta(days=1)
        if e <= s:
            e = s + timedelta(days=1)
        start_text, ende_text = s.isoformat(), e.isoformat()
    else:
        start_text = start.isoformat()
        ende_text = ende.isoformat() if isinstance(ende, datetime) else start_text
    titel = _zeile(roh.get("titel"), TITEL_MAX) or OHNE_TITEL
    ort = _zeile(roh.get("ort"), ORT_MAX)
    kalender = _zeile(roh.get("kalender"), KALENDER_MAX)
    konto = _zeile(roh.get("konto"), KALENDER_MAX)
    kennung = _zeile(roh.get("id"), 200)
    if not kennung:
        kennung = "t-" + hashlib.sha1(f"{kalender}|{start_text}|{titel}".encode()).hexdigest()[:12]  # noqa: S324
    return {"id": kennung, "titel": titel, "start": start_text, "ende": ende_text, "ganztaegig": ganztaegig,
            "ort": ort, "kalender": kalender, "konto": konto}


def kalender_aus(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Bringt einen Kalender in die Form ``{id, name, konto, schreibbar}``; ``None`` ohne Kennung."""
    kennung = _zeile(roh.get("id"), 300)
    if not kennung:
        return None
    return {"id": kennung, "name": _zeile(roh.get("name"), KALENDER_MAX) or kennung,
            "konto": _zeile(roh.get("konto"), KALENDER_MAX), "schreibbar": bool(roh.get("schreibbar"))}


_NEU_FELDER = ("titel", "start", "ende", "ganztaegig", "ort", "beschreibung", "kalender")


def pruefe_neu(termin: Any) -> dict[str, Any]:
    """Prüft die Eingabe für ``anlegen()`` und liefert sie bereinigt: ``titel start ende ganztaegig ort beschreibung
    kalender``. Ganztägig: ``start`` und ``ende`` sind Tage, ``ende`` der Tag nach dem letzten (fehlt er, ist es ein Tag).
    Sonst haben ``start`` und ``ende`` eine Uhrzeit; fehlt ``ende``, dauert der Termin eine Stunde. Zeiten ohne
    Versatz gelten in der Zeitzone des Hubs. ``ValueError`` bei falscher Eingabe."""
    if not isinstance(termin, dict):
        raise ValueError("termin: ein Objekt mit titel, start, ende … erwartet")
    fremd = sorted(str(k) for k in set(termin) - set(_NEU_FELDER))
    if fremd:
        raise ValueError(f"termin: unbekannte Felder {', '.join(fremd)} (erlaubt: {', '.join(_NEU_FELDER)})")
    titel = _zeile(termin.get("titel"))
    if not titel:
        raise ValueError("titel fehlt")
    if len(titel) > TITEL_MAX:
        raise ValueError(f"titel ist länger als {TITEL_MAX} Zeichen")
    start = _lies(termin.get("start"))
    if start is None:
        raise ValueError("start fehlt oder ist keine gültige Zeit (ISO 8601: JJJJ-MM-TT oder JJJJ-MM-TTThh:mm)")
    roh_ende = termin.get("ende")
    ende = _lies(roh_ende) if roh_ende not in (None, "") else None
    if roh_ende not in (None, "") and ende is None:
        raise ValueError("ende ist keine gültige Zeit (ISO 8601: JJJJ-MM-TT oder JJJJ-MM-TTThh:mm)")
    ganztaegig = termin.get("ganztaegig")
    if ganztaegig is None:
        ganztaegig = not isinstance(start, datetime)
    elif not isinstance(ganztaegig, bool):
        raise ValueError("ganztaegig muss true oder false sein")
    if ganztaegig:
        s = start.date() if isinstance(start, datetime) else start
        e = (ende.date() if isinstance(ende, datetime) else ende) if ende is not None else s
        if e < s:
            raise ValueError("ende liegt vor start")
        if e == s:
            e = s + timedelta(days=1)
        if e - s > timedelta(days=FENSTER_MAX_TAGE):
            raise ValueError(f"der Termin ist länger als {FENSTER_MAX_TAGE} Tage")
        start_text, ende_text = s.isoformat(), e.isoformat()
    else:
        if not isinstance(start, datetime):
            raise ValueError("start braucht eine Uhrzeit (oder ganztaegig: true)")
        if ende is not None and not isinstance(ende, datetime):
            raise ValueError("ende braucht eine Uhrzeit (oder ganztaegig: true)")
        e = ende if ende is not None else start + timedelta(hours=1)
        if lokalisiere(e) <= lokalisiere(start):
            raise ValueError("ende muss nach start liegen")
        if lokalisiere(e) - lokalisiere(start) > timedelta(days=FENSTER_MAX_TAGE):
            raise ValueError(f"der Termin ist länger als {FENSTER_MAX_TAGE} Tage")
        start_text, ende_text = start.isoformat(), e.isoformat()
    ort = _zeile(termin.get("ort"))
    if len(ort) > ORT_MAX:
        raise ValueError(f"ort ist länger als {ORT_MAX} Zeichen")
    kalender = _zeile(termin.get("kalender"))
    if len(kalender) > KALENDER_MAX:
        raise ValueError(f"kalender ist länger als {KALENDER_MAX} Zeichen")
    beschreibung = "".join(c for c in str(termin.get("beschreibung") or "").replace("\r\n", "\n").replace("\r", "\n")
                           if c in "\n\t" or c >= " ").strip()
    if len(beschreibung) > BESCHREIBUNG_MAX:
        raise ValueError(f"beschreibung ist länger als {BESCHREIBUNG_MAX} Zeichen")
    return {"titel": titel, "start": start_text, "ende": ende_text, "ganztaegig": ganztaegig, "ort": ort,
            "beschreibung": beschreibung, "kalender": kalender}


def _kalender_filter(kalender: Any) -> str | None:
    text = _zeile(kalender)
    if len(text) > KALENDER_MAX:
        raise ValueError(f"kalender ist länger als {KALENDER_MAX} Zeichen")
    return text or None


# ── Quellen ─────────────────────────────────────────────────────────────────────────────────────────────
class Quelle:
    """Gemeinsame Form aller Quellen. ``art``: dienst | ablage | keine. Diese Grundform ist die Quelle „keine“."""

    art = "keine"

    @property
    def eingerichtet(self) -> bool:
        return self.art != "keine"

    def beschreibung(self) -> str:
        return "kein Kalender eingerichtet"

    def kalender(self) -> list[dict[str, Any]]:
        """Die Kalender: ``{id, name, konto, schreibbar}``."""
        raise NichtEingerichtet()

    def termine(self, von: Any, bis: Any, kalender: str | None = None) -> list[dict[str, Any]]:
        """Termine im Fenster ``[von, bis)`` (``datetime``, ``date`` oder ISO-Text), nach Beginn sortiert, ganztägige
        eines Tages zuerst. ``kalender``: Name oder Kennung (``None``: alle). Die Antwort „keine Termine“ ist die leere
        Liste; ist die Quelle aus oder ohne Zugang, wirft der Aufruf ``QuelleFehler``."""
        a, b = _fenster(von, bis)
        gesucht = _kalender_filter(kalender)
        liste = self._termine(a, b, gesucht)
        treffer = [t for t in liste if _im_fenster(t, a, b)]
        treffer.sort(key=_sortierschluessel)
        return treffer[:TERMINE_MAX]

    def anstehende(self, tage: int = 1, kalender: str | None = None) -> list[dict[str, Any]]:
        """Die Termine der nächsten ``tage`` Tage ab jetzt (laufende eingeschlossen)."""
        n = _tage(tage)
        jetzt = datetime.now(timezone.utc).replace(microsecond=0)
        return self.termine(jetzt, jetzt + timedelta(days=n), kalender)

    def anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
        """Legt einen Termin an (Felder: siehe ``pruefe_neu``) und liefert ihn im Terminformat."""
        raise NichtEingerichtet()

    def als_dict(self) -> dict[str, Any]:
        return {"art": self.art, "eingerichtet": self.eingerichtet, "beschreibung": self.beschreibung()}

    def _termine(self, von: datetime, bis: datetime, kalender: str | None) -> list[dict[str, Any]]:
        raise NichtEingerichtet()


class AblageQuelle(Quelle):
    """Ein Kalender-Plugin als Quelle (prozessintern)."""

    art = "ablage"

    def __init__(self, ablage: Ablage) -> None:
        self.ablage = ablage

    def beschreibung(self) -> str:
        name = _zeile(getattr(self.ablage, "name", ""), 60)
        return f"Kalender-Plugin {name}" if name else "Kalender-Plugin"

    @staticmethod
    def _rufe(fn: Any) -> Any:
        try:
            return fn()
        except (QuelleFehler, ValueError):
            raise
        except vorgaenge.QuelleFehler as exc:  # ein Plugin mit der Fehlerklasse der Vorgänge
            raise QuelleFehler(str(exc), exc.status) from exc
        except NotImplementedError as exc:
            raise QuelleFehler("Das Kalender-Plugin kann das nicht.", 501) from exc
        except Exception as exc:  # noqa: BLE001 — Plugin-Fehler; nur der Typ geht an die Leser, nie der Text
            _log.warning("Kalender-Plugin: unerwarteter Fehler (%s)", type(exc).__name__,
                         exc_info=_log.isEnabledFor(logging.DEBUG))
            raise QuelleFehler(f"Das Kalender-Plugin meldet einen Fehler ({type(exc).__name__}).") from exc

    def kalender(self) -> list[dict[str, Any]]:
        roh = self._rufe(self.ablage.ablage_kalender)
        if not isinstance(roh, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Kalenderliste")
        return [k for k in (kalender_aus(x) for x in roh if isinstance(x, dict)) if k]

    def _termine(self, von: datetime, bis: datetime, kalender: str | None) -> list[dict[str, Any]]:
        roh = self._rufe(lambda: self.ablage.ablage_termine(von, bis, kalender))
        if not isinstance(roh, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Terminliste")
        fertig = [t for t in (termin_aus(x) for x in roh if isinstance(x, dict)) if t]
        if len(fertig) < len(roh):
            _log.warning("%s: %d Einträge ohne lesbaren Beginn übersprungen", self.beschreibung(), len(roh) - len(fertig))
        return fertig

    def anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
        neu = pruefe_neu(termin)
        schreiben = getattr(self.ablage, "ablage_anlegen", None)
        if schreiben is None:
            raise QuelleFehler(f"{self.beschreibung()} kann keine Termine anlegen.", 501)
        roh = self._rufe(lambda: schreiben(neu))
        fertig = termin_aus(roh) if isinstance(roh, dict) else None
        if fertig is None:
            raise QuelleFehler(f"{self.beschreibung()} hat den Termin nicht bestätigt.")
        return fertig


class _KeineUmleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Umleitung: die Kopfzeile des Dienstes geht an die eingetragene Adresse und an keine andere."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_OFFEN = urllib.request.build_opener(_KeineUmleitung)


def _netzfehler(e: BaseException) -> str:
    ursache = e.reason if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException) else e
    if isinstance(ursache, TimeoutError):
        return "Zeitüberschreitung"
    if isinstance(ursache, ConnectionRefusedError):
        return "Verbindung abgelehnt"
    if isinstance(ursache, socket.gaierror):
        return "Name nicht aufgelöst"
    if isinstance(ursache, ssl.SSLError):
        return "TLS-Fehler"
    return type(ursache).__name__


def _grund(d: Any, status: int) -> str:
    if isinstance(d, dict):
        for k in ("detail", "error", "fehler", "hinweis", "_message"):
            if d.get(k):
                return _zeile(d[k], 300)
    return f"HTTP {status}"


class Dienst(Quelle):
    """Termin-Dienst per HTTP unter ``url``. Der Vertrag ist der des Kalender-Dienstes, den FYOS bisher betrieben hat:

    * ``GET /api/calendar/events?who=all&days=N&start=<ISO>&end=<ISO>`` liefert ``{"events": [{id, title, start, end,
      all_day, location, calendar_id, calendar_name, source}], "_stub": false}``. Ein Dienst, der nur ``days`` versteht,
      liefert dann das Fenster ab jetzt. ``"_stub": true`` heißt: ohne Zugang zu den Kalendern (``_message`` sagt warum);
      das ist ein ``QuelleFehler`` mit Status 503, nie „keine Termine“.
    * ``GET /api/calendar/calendars`` liefert ``{"calendars": [{id, summary, access_role}], "status": "live"}``.
    * ``POST /api/calendar/events`` mit ``{title, start, end, all_day, location, description, calendar_id}`` legt einen
      Termin an und liefert ``{"id": …}``. Kennt der Dienst die Route nicht, meldet ``anlegen()`` das klar.

    Umleitungen werden nicht verfolgt (die Kopfzeile geht nur an die eingetragene Adresse)."""

    art = "dienst"

    def __init__(self, url: str, kopf: dict[str, str] | None = None, aufruf: Any = None) -> None:
        self.url = url.rstrip("/")
        self.kopf = dict(kopf or {})
        self._aufruf = aufruf

    def beschreibung(self) -> str:
        try:
            teile = urllib.parse.urlsplit(self.url)
            host = teile.hostname
            port = teile.port
        except ValueError:
            return "Kalender-Dienst"
        if not host:
            return "Kalender-Dienst"
        return f"Kalender-Dienst {host}" + (f":{port}" if port else "")

    def roh(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S) -> tuple[int, Any]:
        """(Status, JSON) vom Dienst; Fehlerstatus kommen als Wert, ein unlesbarer Rumpf als ``None``. Ist der
        Dienst nicht erreichbar, wirft der Aufruf ``QuelleFehler``."""
        if self._aufruf is not None:
            return self._aufruf(methode, pfad, koerper, frist)
        daten = json.dumps(koerper).encode() if koerper is not None else None
        kopf = {"Accept": "application/json", "User-Agent": "fyos-hub", **self.kopf}
        if daten is not None:
            kopf["Content-Type"] = "application/json"
        try:
            req = urllib.request.Request(self.url + pfad, data=daten, method=methode, headers=kopf)
        except ValueError:
            raise QuelleFehler(f"{self.beschreibung()}: die Adresse ist keine gültige URL (http:// oder https://).") from None
        try:
            with _OFFEN.open(req, timeout=frist) as r:  # noqa: S310 — Adresse aus der Konfiguration
                roh, status = r.read(ANTWORT_MAX + 1), r.status
        except urllib.error.HTTPError as e:
            roh, status = (e.read(65536) if e.fp else b""), e.code
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise QuelleFehler(f"{self.beschreibung()} nicht erreichbar ({_netzfehler(e)}).") from e
        if len(roh) > ANTWORT_MAX:
            raise QuelleFehler(f"{self.beschreibung()}: die Antwort ist zu groß.")
        try:
            return status, json.loads(roh.decode() or "{}")
        except ValueError:
            return status, None

    def _antwort(self, status: int, d: Any) -> dict[str, Any]:
        """Die Antwort als Objekt oder ein ``QuelleFehler`` mit dem Grund."""
        if status in (401, 403):
            raise QuelleFehler(
                f"{self.beschreibung()} lehnt die Anfrage ab ({status}); Zugang prüfen (FYOS_TERMINE_KOPF).", status)
        if 300 <= status < 400:
            raise QuelleFehler(
                f"{self.beschreibung()} antwortet mit {status} (Umleitungen werden nicht verfolgt; Adresse prüfen).", status)
        if status >= 400:
            raise QuelleFehler(f"{self.beschreibung()} antwortet mit {status}: {_grund(d, status)}", status)
        if not isinstance(d, dict):
            raise QuelleFehler(f"{self.beschreibung()} antwortet nicht mit lesbaren Daten.")
        return d

    def _ohne_zugang(self, d: dict[str, Any]) -> QuelleFehler:
        grund = _zeile(d.get("_message") or d.get("status") or "ohne Angabe", 300)
        return QuelleFehler(f"{self.beschreibung()} hat keinen Zugang zu den Kalendern: {grund}", 503)

    def kalender(self) -> list[dict[str, Any]]:
        d = self._antwort(*self.roh("GET", "/api/calendar/calendars", None, FRIST_LESEN_S))
        liste = d.get("calendars")
        if not isinstance(liste, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Kalenderliste.")
        if not liste and str(d.get("status") or "live") not in ("live", "refreshed"):
            raise self._ohne_zugang(d)
        rollen = ("owner", "writer")
        return [k for k in (kalender_aus({"id": c.get("id"), "name": c.get("summary") or c.get("name"),
                                          "konto": c.get("konto") or "", "schreibbar": c.get("access_role") in rollen})
                            for c in liste if isinstance(c, dict)) if k]

    def _termine(self, von: datetime, bis: datetime, kalender: str | None) -> list[dict[str, Any]]:
        tage = max(1, min(DIENST_TAGE_MAX, math.ceil((bis - von) / timedelta(days=1))))
        abfrage = urllib.parse.urlencode({
            "who": "all",
            "days": tage,
            "start": von.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            "end": bis.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        })
        d = self._antwort(*self.roh("GET", f"/api/calendar/events?{abfrage}", None, FRIST_LESEN_S))
        if d.get("_stub"):
            raise self._ohne_zugang(d)
        ereignisse = d.get("events")
        if not isinstance(ereignisse, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Terminliste.")
        gesucht = kalender.casefold() if kalender else None
        fertig: list[dict[str, Any]] = []
        uebersprungen = 0
        for ev in ereignisse:
            if not isinstance(ev, dict):
                uebersprungen += 1
                continue
            if gesucht and gesucht not in (str(ev.get("calendar_name") or "").casefold(),
                                           str(ev.get("calendar_id") or "").casefold()):
                continue
            t = termin_aus({
                "id": ev.get("id") or ev.get("uid"),
                "titel": ev.get("title") or ev.get("summary"),
                "start": ev.get("start"),
                "ende": ev.get("end"),
                "ganztaegig": ev.get("all_day"),
                "ort": ev.get("location"),
                "kalender": ev.get("calendar_name") or ev.get("calendar_id"),
                "konto": ev.get("source"),
            })
            if t is None:
                uebersprungen += 1
            else:
                fertig.append(t)
        if uebersprungen:
            _log.warning("%s: %d Einträge ohne lesbaren Beginn übersprungen", self.beschreibung(), uebersprungen)
        return fertig

    def anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
        neu = pruefe_neu(termin)
        koerper: dict[str, Any] = {"title": neu["titel"], "start": neu["start"], "end": neu["ende"],
                                   "all_day": neu["ganztaegig"], "location": neu["ort"],
                                   "description": neu["beschreibung"]}
        if neu["kalender"]:
            koerper["calendar_id"] = neu["kalender"]
        status, d = self.roh("POST", "/api/calendar/events", koerper, FRIST_SCHREIBEN_S)
        if status in (404, 405, 501):
            raise QuelleFehler(
                f"{self.beschreibung()} kann keine Termine anlegen (POST /api/calendar/events antwortet mit {status}).", 501)
        d = self._antwort(status, d)
        if not d.get("id"):
            raise QuelleFehler(f"{self.beschreibung()} hat den Termin nicht bestätigt.")
        fertig = termin_aus({"id": d.get("id"), "titel": d.get("summary") or neu["titel"], "start": neu["start"],
                             "ende": neu["ende"], "ganztaegig": neu["ganztaegig"], "ort": neu["ort"],
                             "kalender": neu["kalender"], "konto": ""})
        if fertig is None:  # nicht erreichbar: start und ende sind oben geprüft
            raise QuelleFehler(f"{self.beschreibung()} hat den Termin nicht bestätigt.")
        return fertig


def quelle(url: str | None = None, kopf: str | None = None) -> Quelle:
    """Die Quelle der Termine für diesen Aufruf. Reihenfolge: ``url`` (leer zählt als nicht angegeben); der mit
    ``dienst_anmelden`` angemeldete Dienst; ``FYOS_TERMINE_URL``; das angemeldete Kalender-Plugin; keine. ``kopf``
    (``"Name: Wert"``) überschreibt die Kopfzeile (sonst die des angemeldeten Dienstes bzw. ``FYOS_TERMINE_KOPF``)."""
    adresse = (url or "").strip().rstrip("/")
    if not adresse:
        gespiegelt = angemeldeter_dienst()
        if gespiegelt is not None:
            return Dienst(gespiegelt[0], gespiegelt[1] if kopf is None else kopf_aus(kopf))
        adresse = os.getenv("FYOS_TERMINE_URL", "").strip().rstrip("/")
    if adresse:
        return Dienst(adresse, kopf_aus(os.getenv("FYOS_TERMINE_KOPF", "") if kopf is None else kopf))
    ablage = angemeldete_ablage()
    if ablage is not None:
        return AblageQuelle(ablage)
    return Quelle()
