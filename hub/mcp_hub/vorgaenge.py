"""Vorgänge für Plugins: eine Quelle, gleich ob Vorgangs-Dienst oder Workboard.

Plugins, die Vorgänge lesen oder beantworten (Leitstand, Zentrale, „Braucht dich“), tragen keine Adresse fest ein,
sondern fragen hier. Es gilt der Vorgangs-Vertrag aus docs/KOPPLUNG-OPENCLAW.md (Abschnitt 4):
``GET /tickets?status=&limit=``, ``GET /tickets/{id}``, ``POST /tickets``, ``POST /tickets/{id}/comments``
``{actor, text}``, ``PATCH /tickets/{id}`` ``{status, expected_status?, actor?, title?, description?, priority?}``.

Reihenfolge der Quellen (``quelle()``):

1. **Vorgangs-Dienst**, wenn eine Adresse gesetzt ist (Argument ``url``, der Dienst, den das Plugin ``openclaw``
   spiegelt, oder ``FYOS_VORGAENGE_URL``): HTTP auf ``<adresse>/tickets…``, mit der Kopfzeile aus
   ``FYOS_VORGAENGE_KOPF``. Das ist die Ausbaustufe, etwa ein eigener Ticketdienst. Kann der Dienst mehr als der
   Vertrag (Verlauf, Wartelisten), reicht ``roh()`` solche Pfade unverändert durch.
2. **Workboard** des Agenten, wenn das Hub-Plugin ``openclaw`` als Ablage läuft (Grundstufe, prozessintern). Was
   das Workboard nicht kennt (Zuständige, ``waiting_for``), gibt es dann nicht; den Verlauf bilden die Kommentare
   der Karte.
3. **Keine**: Listen bleiben leer, Einzelabruf und Schreiben melden ``NichtEingerichtet``.

Plugins fragen ``quelle()`` bei jedem Aufruf neu; das ist billig und nimmt eine Ablage mit, die sich erst nach ihnen
anmeldet. Fehler: ``VorgangFehlt`` (404), ``VorgangKonflikt`` (409, mit dem aktuellen Stand), ``ValueError``
(Eingabe), ``QuelleFehler`` (Dienst oder Brücke antworten nicht wie vereinbart), ``NichtEingerichtet`` (keine Quelle).
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from typing import Any, Callable, Protocol

VORGANG_STATUS = ("new", "triage", "in_progress", "waiting_approval", "resolved", "closed")
OFFEN = ("new", "triage", "in_progress", "waiting_approval")
FREIGABE = "waiting_approval"
#: Felder, die ``PATCH /tickets/{id}`` laut Vertrag annimmt. Alles andere bleibt beim Dienst (oder fällt im Workboard weg).
AENDERBAR = ("status", "expected_status", "actor", "title", "description", "priority")
FRIST_LESEN_S = 8.0
FRIST_SCHREIBEN_S = 12.0
GRENZE_MAX = 500
ANTWORT_MAX = 4 * 1024 * 1024


class QuelleFehler(RuntimeError):
    """Die Quelle antwortet nicht wie vereinbart (Netz, Brücke, unerwarteter Status)."""

    def __init__(self, text: str, status: int = 502) -> None:
        super().__init__(text)
        self.status = status


class NichtEingerichtet(QuelleFehler):
    """Es gibt keine Quelle für Vorgänge (kein Vorgangs-Dienst, keine Ablage im Workboard)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text or (
            "Keine Ablage für Vorgänge eingerichtet: weder ein Vorgangs-Dienst (FYOS_VORGAENGE_URL) noch das Workboard "
            "des Agenten (Hub-Plugin openclaw mit FYOS_AGENT_URL)."
        ), 501)


class VorgangFehlt(LookupError):
    """Den Vorgang gibt es in der Quelle nicht."""


class VorgangKonflikt(RuntimeError):
    """Der Vorgang steht inzwischen anders als erwartet (``expected_status``)."""

    def __init__(self, text: str, vorgang: dict[str, Any] | None = None) -> None:
        super().__init__(text)
        self.vorgang = vorgang or {}


class Ablage(Protocol):
    """Was das Hub-Plugin ``openclaw`` im Ablage-Betrieb anbietet (Daten statt HTTP)."""

    def ablage_liste(self, status: str = "", grenze: int = 50) -> list[dict[str, Any]]: ...

    def ablage_holen(self, vid: str) -> dict[str, Any] | None: ...

    def ablage_anlegen(self, koerper: dict[str, Any]) -> dict[str, Any]: ...

    def ablage_kommentieren(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]: ...

    def ablage_aendern(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]: ...

    def ablage_verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]: ...


_sperre = threading.Lock()
_ablage: Ablage | None = None
_dienst: tuple[str, dict[str, str]] | None = None


def ablage_anmelden(ablage: Ablage | None) -> None:
    """Das Workboard (Plugin ``openclaw`` als Ablage) meldet sich an; ``None`` meldet ab."""
    global _ablage
    with _sperre:
        _ablage = ablage


def angemeldete_ablage() -> Ablage | None:
    with _sperre:
        return _ablage


def dienst_anmelden(url: str | None, kopf: dict[str, str] | None = None) -> None:
    """Das Plugin ``openclaw`` meldet im Spiegel-Betrieb den Dienst an, den es spiegelt (Adresse und Kopfzeile aus
    seiner ``config`` oder der Umgebung): so fragen alle Plugins denselben Dienst. ``None`` meldet ab."""
    global _dienst
    with _sperre:
        _dienst = (url.strip().rstrip("/"), dict(kopf or {})) if url and url.strip() else None


def angemeldeter_dienst() -> tuple[str, dict[str, str]] | None:
    with _sperre:
        return _dienst


def _grenze(wert: Any) -> int:
    try:
        return max(1, min(int(wert), GRENZE_MAX))
    except (TypeError, ValueError):
        return 50


def _status_liste(status: str | Iterable[str] | None) -> list[str]:
    if not status:
        return []
    roh = [status] if isinstance(status, str) else list(status)
    teile = [s.strip() for x in roh for s in str(x).split(",") if s.strip()]
    for s in teile:
        if s not in VORGANG_STATUS:
            raise ValueError(f"unbekannter Status {s!r} (erlaubt: {', '.join(VORGANG_STATUS)})")
    return list(dict.fromkeys(teile))


def _vorgang_aus(daten: Any) -> dict[str, Any]:
    """Einzelvorgang aus einer Antwort: manche Dienste verpacken ihn als ``{"ticket": {...}}``."""
    if isinstance(daten, dict) and isinstance(daten.get("ticket"), dict):
        return daten["ticket"]
    return daten if isinstance(daten, dict) else {}


def _aenderung(felder: dict[str, Any]) -> dict[str, Any]:
    koerper = {k: v for k, v in felder.items() if k in AENDERBAR and v not in (None, "")}
    if "description" in felder and felder["description"] is not None:
        koerper["description"] = str(felder["description"])
    ziel = koerper.get("status")
    if ziel and ziel not in VORGANG_STATUS:
        raise ValueError(f"unbekannter Status {ziel!r}")
    return koerper


class Quelle:
    """Gemeinsame Form aller Quellen. ``art``: dienst | workboard | keine."""

    art = "keine"

    @property
    def eingerichtet(self) -> bool:
        return self.art != "keine"

    def beschreibung(self) -> str:
        return "keine Ablage für Vorgänge"

    # Lesen
    def liste(self, status: str | Iterable[str] | None = None, grenze: int = 50) -> list[dict[str, Any]]:
        """Vorgänge mit einem der Status (leer: alle), höchstens ``grenze`` je Status."""
        _status_liste(status)
        return []

    def holen(self, vid: str) -> dict[str, Any]:
        raise NichtEingerichtet()

    def verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        """Verlauf eines Vorgangs, neueste zuerst: ``{ts, event, actor, detail}``. Im Workboard sind es die Kommentare
        der Karte (``event`` = ``comment``)."""
        raise NichtEingerichtet()

    def offen(self, grenze: int = 200) -> list[dict[str, Any]]:
        return self.liste(OFFEN, grenze)

    def freigaben(self, grenze: int = 200) -> list[dict[str, Any]]:
        """Vorgänge, die auf eine Freigabe warten (``waiting_approval``, im Workboard die Spalte ``review``)."""
        return self.liste(FREIGABE, grenze)

    # Schreiben
    def anlegen(self, title: str, description: str = "", *, status: str = "new", priority: str = "", typ: str = "",
                source_url: str = "", actor: str = "") -> dict[str, Any]:
        raise NichtEingerichtet()

    def kommentieren(self, vid: str, text: str, actor: str = "") -> None:
        raise NichtEingerichtet()

    def aendern(self, vid: str, **felder: Any) -> dict[str, Any]:
        raise NichtEingerichtet()

    # Durchreichen (Pfade relativ zur Quelle, z. B. ``/tickets/INC-1/history``)
    def roh(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S) -> tuple[int, Any]:
        """(Status, JSON) wie ein HTTP-Aufruf beim Vorgangs-Dienst. Fehler kommen als Status, nicht als Ausnahme."""
        return _vertrag_auf_methoden(self, methode, pfad, koerper)

    def als_dict(self) -> dict[str, Any]:
        return {"art": self.art, "eingerichtet": self.eingerichtet, "beschreibung": self.beschreibung()}


class Dienst(Quelle):
    """Vorgangs-Dienst per HTTP (Vertrag ``/tickets…`` unter ``url``)."""

    art = "dienst"

    def __init__(self, url: str, kopf: dict[str, str] | None = None,
                 aufruf: Callable[[str, str, Any, float], tuple[int, Any]] | None = None) -> None:
        self.url = url.rstrip("/")
        self.kopf = dict(kopf or {})
        self._aufruf = aufruf

    def beschreibung(self) -> str:
        teile = urllib.parse.urlsplit(self.url)
        return f"Vorgangs-Dienst {teile.netloc or self.url}"

    def roh(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S) -> tuple[int, Any]:
        if self._aufruf is not None:
            return self._aufruf(methode, pfad, koerper, frist)
        daten = json.dumps(koerper).encode() if koerper is not None else None
        kopf = {"Accept": "application/json", **self.kopf}
        if daten is not None:
            kopf["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + pfad, data=daten, method=methode, headers=kopf)
        try:
            with urllib.request.urlopen(req, timeout=frist) as r:  # noqa: S310 — Adresse aus der Konfiguration
                roh, status = r.read(ANTWORT_MAX), r.status
        except urllib.error.HTTPError as e:
            roh, status = (e.read(65536) if e.fp else b""), e.code
        except (urllib.error.URLError, OSError) as e:
            raise QuelleFehler(f"{self.beschreibung()} nicht erreichbar ({type(e).__name__})") from e
        try:
            return status, json.loads(roh.decode() or "{}")
        except ValueError:
            return status, {}

    def _json(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S) -> Any:
        status, d = self.roh(methode, pfad, koerper, frist)
        if status == 404:
            raise VorgangFehlt(_grund(d, status))
        if status == 409:
            raise VorgangKonflikt(_grund(d, status), _vorgang_aus(d) if isinstance(d, dict) and d.get("ticket") else None)
        if status in (400, 422):
            raise ValueError(_grund(d, status))
        if status >= 400:
            raise QuelleFehler(f"{self.beschreibung()} antwortet mit {status}: {_grund(d, status)}", status)
        return d

    def liste(self, status: str | Iterable[str] | None = None, grenze: int = 50) -> list[dict[str, Any]]:
        n = _grenze(grenze)
        ergebnis: list[dict[str, Any]] = []
        for s in _status_liste(status) or [""]:
            abfrage = urllib.parse.urlencode({k: v for k, v in (("status", s), ("limit", n)) if v != ""})
            d = self._json("GET", f"/tickets?{abfrage}")
            tickets = [t for t in (d.get("tickets") if isinstance(d, dict) else None) or [] if isinstance(t, dict)]
            ergebnis += tickets[:n]
        return ergebnis

    def holen(self, vid: str) -> dict[str, Any]:
        t = _vorgang_aus(self._json("GET", f"/tickets/{_id(vid)}"))
        if not t.get("id"):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort zu {vid} ist kein Vorgang")
        return t

    def verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        d = self._json("GET", f"/tickets/{_id(vid)}/history?limit={_grenze(grenze)}")
        return [e for e in (d.get("history") if isinstance(d, dict) else None) or [] if isinstance(e, dict)]

    def anlegen(self, title: str, description: str = "", *, status: str = "new", priority: str = "", typ: str = "",
                source_url: str = "", actor: str = "") -> dict[str, Any]:
        koerper = _neu(title, description, status, priority, typ, source_url, actor)
        return _vorgang_aus(self._json("POST", "/tickets", koerper, FRIST_SCHREIBEN_S))

    def kommentieren(self, vid: str, text: str, actor: str = "") -> None:
        if not str(text or "").strip():
            raise ValueError("text fehlt")
        self._json("POST", f"/tickets/{_id(vid)}/comments", {"actor": actor, "text": text}, FRIST_SCHREIBEN_S)

    def aendern(self, vid: str, **felder: Any) -> dict[str, Any]:
        d = self._json("PATCH", f"/tickets/{_id(vid)}", _aenderung(felder), FRIST_SCHREIBEN_S)
        return _vorgang_aus(d)


class Workboard(Quelle):
    """Das Workboard des Agenten als Ablage (prozessintern über das Hub-Plugin ``openclaw``)."""

    art = "workboard"

    def __init__(self, ablage: Ablage) -> None:
        self.ablage = ablage

    def beschreibung(self) -> str:
        return "Workboard des Agenten (OpenClaw)"

    @staticmethod
    def _rufe(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except json.JSONDecodeError as exc:  # kaputte Antwort der Brücke, kein Eingabefehler
            raise QuelleFehler(f"Workboard antwortet unlesbar: {str(exc)[:200]}") from exc
        except (VorgangFehlt, VorgangKonflikt, ValueError, QuelleFehler):
            raise
        except Exception as exc:  # noqa: BLE001 — Brücke oder Gateway; die Nachricht trägt den Grund
            if "conflict" in str(exc).lower():  # jemand hat die Karte inzwischen bewegt
                raise VorgangKonflikt(f"Workboard: {str(exc)[:300]}") from exc
            raise QuelleFehler(f"Workboard nicht erreichbar: {str(exc)[:300]}") from exc

    def liste(self, status: str | Iterable[str] | None = None, grenze: int = 50) -> list[dict[str, Any]]:
        gesucht = _status_liste(status)
        n = _grenze(grenze)
        alle = self._rufe(lambda: self.ablage.ablage_liste("", GRENZE_MAX))
        if not gesucht:
            return alle[:n]
        return [t for s in gesucht for t in [x for x in alle if x.get("status") == s][:n]]

    def holen(self, vid: str) -> dict[str, Any]:
        t = self._rufe(lambda: self.ablage.ablage_holen(str(vid)))
        if not t:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        return t

    def verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        return self._rufe(lambda: self.ablage.ablage_verlauf(str(vid), _grenze(grenze)))

    def anlegen(self, title: str, description: str = "", *, status: str = "new", priority: str = "", typ: str = "",
                source_url: str = "", actor: str = "") -> dict[str, Any]:
        koerper = _neu(title, description, status, priority, typ, source_url, actor)
        return self._rufe(lambda: self.ablage.ablage_anlegen(koerper))

    def kommentieren(self, vid: str, text: str, actor: str = "") -> None:
        if not str(text or "").strip():
            raise ValueError("text fehlt")
        self._rufe(lambda: self.ablage.ablage_kommentieren(str(vid), {"actor": actor, "text": text}))

    def aendern(self, vid: str, **felder: Any) -> dict[str, Any]:
        koerper = _aenderung(felder)
        return self._rufe(lambda: self.ablage.ablage_aendern(str(vid), koerper))


def _id(vid: Any) -> str:
    t = str(vid or "").strip()
    if not t or len(t) > 64 or any(c in t for c in "/?#\\") or not t.isprintable():
        raise ValueError("Kennung eines Vorgangs fehlt oder ist ungültig")
    return urllib.parse.quote(t, safe="")


def _neu(title: str, description: str, status: str, priority: str, typ: str, source_url: str, actor: str) -> dict[str, Any]:
    titel = " ".join(str(title or "").split())
    if not titel:
        raise ValueError("title fehlt")
    if status not in VORGANG_STATUS:
        raise ValueError(f"unbekannter Status {status!r}")
    koerper: dict[str, Any] = {"title": titel, "description": str(description or ""), "status": status}
    for k, v in (("priority", priority), ("type", typ), ("source_url", source_url), ("actor", actor)):
        if v:
            koerper[k] = v
    return koerper


def _grund(d: Any, status: int) -> str:
    if isinstance(d, dict):
        for k in ("detail", "error", "fehler", "hinweis"):
            if d.get(k):
                return str(d[k])[:300]
    return f"HTTP {status}"


def _vertrag_auf_methoden(q: Quelle, methode: str, pfad: str, koerper: Any) -> tuple[int, Any]:
    """Pfade des Vertrags auf die Methoden einer Quelle ohne HTTP (Workboard, keine): (Status, JSON)."""
    teile = urllib.parse.urlsplit(pfad)
    stuecke = [urllib.parse.unquote(s) for s in teile.path.strip("/").split("/") if s]
    abfrage = dict(urllib.parse.parse_qsl(teile.query))
    try:
        if stuecke == ["tickets"] and methode == "GET":
            tickets = q.liste(abfrage.get("status") or None, _grenze(abfrage.get("limit") or 50))
            return 200, {"tickets": tickets, "quelle": q.art}
        if stuecke == ["tickets"] and methode == "POST":
            k = koerper if isinstance(koerper, dict) else {}
            t = q.anlegen(str(k.get("title") or ""), str(k.get("description") or ""),
                          status=str(k.get("status") or "new"), priority=str(k.get("priority") or ""),
                          typ=str(k.get("type") or ""), source_url=str(k.get("source_url") or ""),
                          actor=str(k.get("actor") or ""))
            return 201, {"ok": True, "ticket": t}
        if len(stuecke) == 2 and stuecke[0] == "tickets" and methode == "GET":
            return 200, {"ok": True, "ticket": q.holen(stuecke[1])}
        if len(stuecke) == 2 and stuecke[0] == "tickets" and methode == "PATCH":
            k = koerper if isinstance(koerper, dict) else {}
            return 200, {"ok": True, "ticket": q.aendern(stuecke[1], **k)}
        if len(stuecke) == 3 and stuecke[0] == "tickets" and stuecke[2] == "comments" and methode == "POST":
            k = koerper if isinstance(koerper, dict) else {}
            q.kommentieren(stuecke[1], str(k.get("text") or ""), str(k.get("actor") or ""))
            return 200, {"ok": True, "id": stuecke[1]}
        if len(stuecke) == 3 and stuecke[0] == "tickets" and stuecke[2] == "history" and methode == "GET":
            return 200, {"ok": True, "history": q.verlauf(stuecke[1], _grenze(abfrage.get("limit") or 20))}
    except VorgangFehlt as e:
        return 404, {"detail": str(e)}
    except VorgangKonflikt as e:
        return 409, {"detail": str(e), "ticket": e.vorgang}
    except ValueError as e:
        return 400, {"detail": str(e)}
    except QuelleFehler as e:
        return e.status, {"detail": str(e)}
    if not q.eingerichtet:
        return 501, {"detail": str(NichtEingerichtet())}
    return 501, {"detail": f"{methode} {teile.path} gibt es im {q.beschreibung()} nicht (nur mit einem Vorgangs-Dienst)."}


def kopf_aus(text: str) -> dict[str, str]:
    """``"Name: Wert"`` als Kopfzeile (leer oder kaputt: keine)."""
    name, _, wert = str(text or "").partition(":")
    name, wert = name.strip(), wert.strip()
    if not name or not wert or any(c in name for c in " \t\r\n") or "\n" in wert or "\r" in wert:
        return {}
    return {name: wert}


def quelle(url: str | None = None, kopf: str | None = None) -> Quelle:
    """Die Quelle der Vorgänge für diesen Aufruf. Reihenfolge: ``url``; der Dienst, den das Plugin ``openclaw``
    spiegelt; ``FYOS_VORGAENGE_URL``; das Workboard als Ablage; keine. ``kopf`` (``"Name: Wert"``) überschreibt die
    Kopfzeile (sonst die des Spiegels bzw. ``FYOS_VORGAENGE_KOPF``). Eine Adresse auf die eigene Ablage
    (``…/hub/vorgaenge``) zählt nicht als Dienst: das wäre das Workboard über einen Umweg."""
    gespiegelt = angemeldeter_dienst() if url is None else None
    if gespiegelt is not None:
        return Dienst(gespiegelt[0], gespiegelt[1] if kopf is None else kopf_aus(kopf))
    adresse = (os.getenv("FYOS_VORGAENGE_URL", "") if url is None else url).strip().rstrip("/")
    if adresse and not adresse.endswith("/hub/vorgaenge"):
        return Dienst(adresse, kopf_aus(os.getenv("FYOS_VORGAENGE_KOPF", "") if kopf is None else kopf))
    ablage = angemeldete_ablage()
    if ablage is not None:
        return Workboard(ablage)
    return Quelle()
