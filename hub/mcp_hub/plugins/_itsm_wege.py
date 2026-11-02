"""Wege des ITSM: Vorgangs-Dienst (Durchreichen) und Ablage, dazu die Werkzeuge, die auf beiden gleich arbeiten.

``itsm`` fragt bei jedem Aufruf ``vorgaenge.quelle()``. Ist ein Vorgangs-Dienst eingetragen (``FYOS_VORGAENGE_URL`` oder
``vorgaenge.dienst_anmelden``), reicht das Plugin seine Werkzeuge an ihn durch: ``DIENST_WERKZEUGE`` sprechen den
Vorgangs-Vertrag (``/tickets…``, dazu ``/tickets/{id}/history`` und ``/waiting``, wenn der Dienst sie kennt) über
``Quelle.roh``. Sonst arbeitet es auf der eigenen Ablage im Redis (``itsm.py``, unverändert).

Ein ``Weg`` ist der kleinste gemeinsame Zugriff auf einen Vorgang (holen, Verlauf, Kommentar, Änderung). Darauf stehen
die Werkzeuge, die es auf beiden Wegen gleich gibt: ``notiz`` (der Agent schreibt an einen Vorgang),
``freigabe_beantragen`` (der Agent hält einen schweren Schritt an und fragt den Besitzer) und ``status`` (der Besitzer
setzt einen Status, nur über die Oberfläche, mit Trockenlauf und Gegenprobe).

Felder der Antworten auf dem Dienst-Weg: dieselben wie auf dem Ablage-Weg (``id``, ``titel``, ``status``, ``art``,
``verlauf[{ts, ereignis, wer, text}]``, ``tickets[{id, zustaendig, worauf}]``), dazu was nur ein Dienst kennt
(``schwere``, ``wiedervorlage``, ``archiviert``, ``entdupliziert``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import vorgaenge as VG
from ..plugin import is_dry_run
from . import _arbeit
from ._itsm_ablage import ItsmAblage, kennung as ablage_kennung

FRIST_LESEN_S = 8.0
FRIST_DETAILS_S = 3.0
FRIST_SCHREIBEN_S = 10.0
TEXT_MAX = 4000
TITEL_MAX = 300
BESCHREIBUNG_MAX = 4000
AUSZUG_MAX = 280
VERLAUF_TEXT_MAX = 600
#: Für so viele wartende Vorgänge holt ``wartend`` auf dem Dienst-Weg die Einzelheiten (Alter, Beschreibung)
DETAILS_MAX = 25
FREIGABEN_MAX = 100
#: So lange gilt ``wartend`` auf dem Dienst-Weg als frisch (Oberflächen fragen jede Minute); Schreiben leert es
WARTEND_FRISCH_S = 20.0
#: Kennung beim Dienst: Buchstaben, Bindestrich, Nummer (INC-12, PRB-3); eine Arbeitskarte als ``WB-`` und acht Zeichen
DIENST_KENNUNG = re.compile(r"^[A-Z]{2,6}-[0-9]{1,9}$")
KARTEN_KENNUNG = re.compile(r"^WB-[0-9a-f]{8}$", re.IGNORECASE)
#: Statusziele eines Agenten (nie waiting_approval: dafür freigabe_beantragen; nie closed: das bleibt beim Besitzer)
AGENT_ZIELE = ("in_progress", "triage", "resolved")
#: Statusziele des Besitzers per Knopf (eine Freigabe beantwortet er mit freigeben/ablehnen)
BESITZER_ZIELE = ("in_progress", "triage", "resolved", "closed")
#: Darauf darf eine Text-Antwort des Besitzers stehen
ANTWORT_STATUS = ("new", "triage", "in_progress", VG.FREIGABE)
ARTEN_DIENST = ("INC", "PRB", "CHG", "VOR")
SCHWEREN = ("low", "medium", "high", "critical")
SCHWERE_NAME = {"critical": "kritisch", "high": "hoch", "medium": "mittel", "low": "niedrig"}
_SCHWERE_RANG = {"critical": 0, "high": 1, "medium": 2, "low": 3}
#: Priorität der Ablage → Schwere beim Dienst
PRIORITAET_SCHWERE = {"niedrig": "low", "normal": "medium", "hoch": "high", "dringend": "critical"}
ANTRAG_MARKE = "## Freigabe angefragt"
#: Freigabe-Antrag: Grenzen je Feld (Zeichen)
ANTRAG_FELDER = {"vorhaben": (20, 1500), "wirkung": (3, 300), "ziel": (3, 300), "rueckweg": (3, 600), "beleg": (0, 1500)}
RISIKEN = ("low", "medium", "high")
KONTEXT_MAX = 600
_HTML_KOMMENTAR = re.compile(r"<!--.*?-->", re.DOTALL)


# ── Wer ist wer ─────────────────────────────────────────────────────────────────────────────────────────
def namen(variable: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(n.strip().lower() for n in (os.getenv(variable) or "").split(",") if n.strip()))


def besitzer_namen(besitzer: str) -> tuple[str, ...]:
    """Namen in ``waiting_for``, die „wartet auf den Besitzer“ heißen (``FYOS_BESITZER_NAMEN``, sonst der Akteur)."""
    return namen("FYOS_BESITZER_NAMEN") or (besitzer,)


def wartet_auf_besitzer(worauf: Any, besitzer: str) -> bool:
    """``waiting_for`` ist Freitext („besitzer: Freigabe — …“): nennt er einen der Namen als ganzes Wort?"""
    t = str(worauf or "").lower()
    return any(re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", t) for n in besitzer_namen(besitzer))


def dienst_kennung(wert: Any) -> str:
    t = str(wert or "").strip() if isinstance(wert, str) else ""
    if KARTEN_KENNUNG.match(t):
        return "WB-" + t[3:].lower()
    t = t.upper()
    if not DIENST_KENNUNG.match(t):
        raise ValueError("id: Kennung eines Vorgangs, z. B. INC-12 oder CHG-3")
    return t


def kurz(text: Any, n: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _text(wert: Any, name: str, *, pflicht: bool = False, maximum: int = TEXT_MAX) -> str:
    if wert is None or wert == "":
        if pflicht:
            raise ValueError(f"{name} fehlt")
        return ""
    if not isinstance(wert, str):
        raise ValueError(f"{name} muss Text sein")
    t = wert.strip()
    if pflicht and not t:
        raise ValueError(f"{name} fehlt")
    if len(t) > maximum:
        raise ValueError(f"{name} ist zu lang ({len(t)} Zeichen, höchstens {maximum})")
    return t


def _status_wort(wert: Any, name: str) -> str | None:
    if wert is None or wert == "":
        return None
    s = str(wert).strip().lower()
    if s not in VG.VORGANG_STATUS:
        raise ValueError(f"{name}: einer von {', '.join(VG.VORGANG_STATUS)}")
    return s


def _jetzt_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _alter_tage(iso: Any, jetzt: float | None = None) -> int | None:
    try:
        t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return max(0, int(((jetzt or time.time()) - t.timestamp()) // 86400))


# ── Wege ────────────────────────────────────────────────────────────────────────────────────────────────
class DienstWeg:
    """Vorgangs-Dienst per HTTP (``Quelle.roh``); Felder gehen unverändert durch, auch die, die der Vertrag nicht nennt."""

    art = "dienst"

    def __init__(self, quelle: VG.Quelle) -> None:
        self.q = quelle

    def kennung(self, wert: Any) -> str:
        return dienst_kennung(wert)

    def rufe(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S) -> Any:
        status, d = self.q.roh(methode, pfad, koerper, frist)
        grund = VG._grund(d, status)
        if status == 404:
            raise VG.VorgangFehlt(grund)
        if status == 409:
            ticket = d.get("ticket") if isinstance(d, dict) and isinstance(d.get("ticket"), dict) else None
            raise VG.VorgangKonflikt(grund, ticket)
        if status in (400, 403, 422):
            raise ValueError(grund)
        if status >= 400:
            raise VG.QuelleFehler(f"{self.q.beschreibung()} antwortet mit {status}: {grund}", status)
        if isinstance(d, dict) and d.get("zurueckgehalten"):
            # Sperre beim Dienst: die Änderung liegt im Rückstau, angewendet ist sie nicht
            raise VG.QuelleFehler(str(d.get("hinweis") or "Der Vorgang ist gesperrt; die Änderung wurde nicht angewendet.")[:300])
        return d

    @staticmethod
    def pfad(vid: str, rest: str = "") -> str:
        return f"/tickets/{urllib.parse.quote(vid, safe='')}{rest}"

    def holen(self, vid: str, frist: float = FRIST_LESEN_S) -> dict[str, Any]:
        t = VG._vorgang_aus(self.rufe("GET", self.pfad(vid), None, frist))
        if not t.get("id"):
            raise VG.QuelleFehler(f"{self.q.beschreibung()}: Antwort zu {vid} ist kein Vorgang")
        return t

    def verlauf(self, vid: str, n: int) -> list[dict[str, Any]]:
        d = self.rufe("GET", self.pfad(vid, f"/history?limit={int(n)}"))
        return [e for e in (d.get("history") if isinstance(d, dict) else None) or [] if isinstance(e, dict)]

    def kommentieren(self, vid: str, text: str, actor: str) -> Any:
        return self.rufe("POST", self.pfad(vid, "/comments"), {"actor": actor, "text": text}, FRIST_SCHREIBEN_S)

    def aendern(self, vid: str, patch: dict[str, Any]) -> dict[str, Any]:
        return VG._vorgang_aus(self.rufe("PATCH", self.pfad(vid), patch, FRIST_SCHREIBEN_S))


class AblageWeg:
    """Die Ablage des Plugins (Redis); ``waiting_for`` und ``assignee`` gehen als Felder der Ablage durch."""

    art = "ablage"

    def __init__(self, ablage: ItsmAblage) -> None:
        self.a = ablage

    def kennung(self, wert: Any) -> str:
        return ablage_kennung(wert)

    def holen(self, vid: str, frist: float = FRIST_LESEN_S) -> dict[str, Any]:
        return self.a.muss(vid)

    def verlauf(self, vid: str, n: int) -> list[dict[str, Any]]:
        return self.a.verlauf(vid, n)

    def kommentieren(self, vid: str, text: str, actor: str) -> Any:
        return self.a.kommentieren(vid, text, actor)

    def aendern(self, vid: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self.a.aendern(
            vid, actor=patch["actor"], status=patch.get("status"), expected_status=patch.get("expected_status"),
            beschreibung=patch.get("description"), wartet_auf=patch.get("waiting_for"), zustaendig=patch.get("assignee"),
        )


# ── Formen ──────────────────────────────────────────────────────────────────────────────────────────────
def beschreibung(t: dict[str, Any], maximum: int) -> str | None:
    text = _HTML_KOMMENTAR.sub("", str(t.get("description") or "")).strip()
    return (text if len(text) <= maximum else text[: maximum - 1].rstrip() + "…") or None


def verlaufseintrag(e: dict[str, Any]) -> dict[str, Any]:
    text = _HTML_KOMMENTAR.sub("", str(e.get("detail") or "")).strip()
    if len(text) > VERLAUF_TEXT_MAX:
        text = text[:VERLAUF_TEXT_MAX].rstrip() + " …"
    return {"ts": e.get("ts") or None, "ereignis": e.get("event") or None, "wer": e.get("actor") or None, "text": text or None}


def zeile(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t.get("id"), "titel": t.get("title") or "", "art": t.get("type") or None, "status": t.get("status") or None,
        "prioritaet": t.get("priority") or None, "schwere": t.get("severity") or None,
        "zustaendig": t.get("assignee") or None, "wartet_auf": t.get("waiting_for") or None,
        "aktualisiert": t.get("updated_at") or None,
    }


def folge_status(status: str, archiviert: bool = False) -> list[str]:
    if archiviert or status == VG.FREIGABE:
        return []
    return [s for s in BESITZER_ZIELE if s != status]


def antwort_art(t: dict[str, Any], besitzer: str) -> str | None:
    """``freigabe`` | ``text`` | None: wie der Besitzer den Vorgang beantworten kann."""
    status = str(t.get("status") or "")
    if status == VG.FREIGABE:
        return "freigabe"
    if status in ANTWORT_STATUS and wartet_auf_besitzer(t.get("waiting_for"), besitzer):
        return "text"
    return None


# ── Werkzeuge nur auf dem Dienst-Weg (der Ablage-Weg steht in itsm.py) ─────────────────────────────────
def liste(p: Any, w: DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
    wunsch = str(args.get("status") or "").strip()
    status = None if wunsch == "alle" else ([s.strip() for s in wunsch.split(",") if s.strip()] if wunsch else list(VG.OFFEN))
    for s in status or []:
        _status_wort(s, "status")
    art = str(args.get("art") or "").strip().upper()
    zust = str(args.get("zustaendig") or "").strip().lower()
    n = max(1, min(int(args.get("anzahl") or 50), 200))
    alle = w.q.liste(status, VG.GRENZE_MAX if (art or zust) else n)
    treffer = [t for t in alle if (not art or str(t.get("type") or "").upper() == art)
               and (not zust or str(t.get("assignee") or "").lower() == zust)]
    treffer.sort(key=lambda t: str(t.get("updated_at") or ""), reverse=True)
    zeilen = [zeile(t) for t in treffer[:n]]
    satz = f"{len(treffer)} Vorgang{'e' if len(treffer) != 1 else ''}" if treffer else "Keine Vorgänge"
    return {"ok": True, "anzahl": len(treffer), "gezeigt": len(zeilen), "satz": satz + ".", "vorgaenge": zeilen,
            "quelle": "dienst"}


def vorgang(p: Any, w: DienstWeg, args: dict[str, Any], verlauf_vorgabe: int, verlauf_max: int) -> dict[str, Any]:
    n = args.get("verlauf", verlauf_vorgabe)
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= verlauf_max:
        raise ValueError(f"verlauf: Anzahl der Einträge, 0 bis {verlauf_max}")
    vid = w.kennung(args.get("id"))
    t = w.holen(vid)
    warnungen: list[str] = []
    eintraege: list[dict[str, Any]] = []
    if n:
        try:
            eintraege = [verlaufseintrag(e) for e in w.verlauf(vid, n)]
        except (VG.QuelleFehler, VG.VorgangFehlt, ValueError) as e:  # der Vorgang steht, nur der Verlauf fehlt
            warnungen.append(f"Verlauf nicht lesbar ({str(e)[:120]}).")
    status = str(t.get("status") or "")
    archiviert = bool(t.get("archived_at"))
    return {
        "ok": True, "id": t.get("id"), "titel": t.get("title") or "", "status": status or None,
        "art": t.get("type") or None, "schwere": t.get("severity") or None, "prioritaet": t.get("priority") or None,
        "wartet_auf": t.get("waiting_for") or None, "zustaendig": t.get("assignee") or None,
        "melder": t.get("reporter") or None, "beschreibung": beschreibung(t, BESCHREIBUNG_MAX),
        "erstellt": t.get("created_at") or None, "aktualisiert": t.get("updated_at") or None,
        "wartet_seit": t.get("waiting_since") or None, "wiedervorlage": t.get("wiedervorlage") or None,
        "archiviert": archiviert, "antwort": antwort_art(t, p.besitzer),
        "folge_status": folge_status(status, archiviert), "verlauf": eintraege, "warnungen": warnungen,
        "hinweis": _arbeit.FREMDINHALT, "text": f"{t.get('id')} „{t.get('title') or ''}“ — {status or 'ohne Status'}",
    }


def _wartende(p: Any, w: DienstWeg) -> dict[str, Any]:
    """Was auf den Besitzer wartet: ``/waiting`` (Gruppen nach ``waiting_for``), sonst die Freigaben."""
    try:
        r = w.rufe("GET", "/waiting")
    except VG.VorgangFehlt:
        r = None
    except VG.QuelleFehler as e:
        if e.status != 501:
            raise
        r = None
    if r is not None:
        if not isinstance(r, dict) or not isinstance(r.get("gruppen"), dict):
            raise VG.QuelleFehler(f"{w.q.beschreibung()}: /waiting ohne gruppen")
        tickets = [dict(t, worauf=k) for k, gruppe in r["gruppen"].items() if wartet_auf_besitzer(k, p.besitzer)
                   for t in gruppe or [] if isinstance(t, dict)]
        return {"tickets": tickets, "wartende": int(r.get("wartende") or 0), "art": "waiting"}
    tickets = [dict(t, worauf="freigabe") for t in w.q.liste(VG.FREIGABE, FREIGABEN_MAX)]
    return {"tickets": tickets, "wartende": len(tickets), "art": "freigaben"}


def wartend(p: Any, w: DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
    roh = _wartende(p, w)
    jetzt = time.time()

    def einzelheiten(t: dict[str, Any]) -> dict[str, Any]:
        try:
            d = w.holen(str(t.get("id")), FRIST_DETAILS_S)
        except Exception:  # noqa: BLE001 — ohne Einzelheiten bleibt der Vorgang in der Liste
            return {"alter_tage": None}
        return {
            "alter_tage": _alter_tage(d.get("created_at"), jetzt) if d.get("created_at") else None,
            "aktualisiert": d.get("updated_at") or None, "zustaendig": d.get("assignee") or None,
            "wartet_seit": d.get("waiting_since") or None,
            "beschreibung": kurz(_HTML_KOMMENTAR.sub("", str(d.get("description") or "")), AUSZUG_MAX) or None,
        }

    tickets = [
        {"id": t.get("id"), "titel": t.get("title") or "", "art": t.get("type") or None, "typ": t.get("type") or None,
         "status": t.get("status") or None, "severity": t.get("severity") or None, "prioritaet": t.get("priority") or None,
         "worauf": t.get("worauf") or None, "zustaendig": t.get("assignee") or None}
        for t in roh["tickets"] if t.get("id")
    ]
    if tickets:
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="itsm-wartend") as pool:
            for t, d in zip(tickets, list(pool.map(einzelheiten, tickets[:DETAILS_MAX]))):
                t.update({k: v for k, v in d.items() if v is not None or k not in t})
    for t in tickets[DETAILS_MAX:]:
        t["alter_tage"] = None
    tickets.sort(key=lambda t: (_SCHWERE_RANG.get(t.get("severity") or "", 9), -(t.get("alter_tage") or 0), str(t["id"])))
    for t in tickets:
        t["schwere"] = SCHWERE_NAME.get(t.get("severity") or "", t.get("severity"))
    return {"ok": True, "ts": _jetzt_iso(), "besitzer": p.besitzer, "anzahl": len(tickets), "tickets": tickets,
            "andere_wartende": max(0, roh["wartende"] - len(tickets)), "art": roh["art"], "quelle": "dienst"}


def kommentieren(p: Any, w: DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
    wer = p._akteur(args)
    vid = w.kennung(args.get("id"))
    text = _text(args.get("text"), "text", pflicht=True)
    if is_dry_run(args):
        return _arbeit.plan(p.name, "kommentieren", f"Kommentar an {vid} hängen", [f"itsm {vid}: ein Kommentar mehr"],
                            {"id": vid, "text": text, "wer": wer})
    w.kommentieren(vid, text, wer)
    return {"ok": True, "id": vid, "von": wer, "satz": f"Kommentar an {vid} angehängt."}


def anlegen(p: Any, w: DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
    wer = p._akteur(args)
    titel = kurz(args.get("titel"), TITEL_MAX)
    if not titel:
        raise ValueError("titel fehlt")
    text = _text(args.get("beschreibung"), "beschreibung", maximum=TEXT_MAX * 2)
    art = str(args.get("art") or args.get("typ") or "INC").upper()
    if art not in ARTEN_DIENST:
        raise ValueError(f"art: eine von {', '.join(ARTEN_DIENST)}")
    schwere = str(args.get("schwere") or PRIORITAET_SCHWERE.get(str(args.get("prioritaet") or ""), "medium")).lower()
    if schwere not in SCHWEREN:
        raise ValueError(f"schwere: eine von {', '.join(SCHWEREN)}")
    verweise = [w.kennung(v) for v in args.get("verweise") or []]
    zust = args.get("zustaendig")
    zust = ("" if wer == p.besitzer else wer) if zust is None else str(zust).strip().lower()[:100]
    koerper: dict[str, Any] = {"type": art, "title": titel, "description": text, "severity": schwere,
                               "source": wer, "actor": wer, "reporter": wer, "assignee": zust}
    status = _status_wort(args.get("status"), "status")
    if status and status != "new":
        if status not in VG.OFFEN:
            raise ValueError("status beim Anlegen: new, triage, in_progress oder waiting_approval")
        koerper["status"] = status
    fp = str(args.get("fingerprint") or "").strip()[:200]
    if fp:
        koerper["fingerprint"] = fp
    if verweise:
        koerper["links"] = verweise
    worauf = str(args.get("wartet_auf") or args.get("worauf") or "").strip()[:200]
    if worauf:
        koerper["waiting_for"] = worauf
    if is_dry_run(args):
        return _arbeit.plan(p.name, "anlegen", f"{art}-Vorgang „{titel}“ anlegen", ["Vorgangs-Dienst: ein Vorgang mehr"],
                            {"titel": titel, "art": art, "schwere": schwere, "zustaendig": zust, "wer": wer})
    d = w.rufe("POST", "/tickets", koerper, FRIST_SCHREIBEN_S) or {}
    t = VG._vorgang_aus(d)
    vid = t.get("id") or d.get("entdupliziert_auf") or d.get("id")
    neu = d.get("angelegt", True) is not False
    return {"ok": True, "id": vid, "angelegt": neu, "entdupliziert": bool(d.get("entdupliziert")),
            "status": t.get("status"), "zustaendig": t.get("assignee") or zust or None,
            "vorgang": zeile(t) if t.get("id") else None,
            "satz": f"Vorgang {vid} „{titel}“ angelegt." if neu else f"Schon offen als {vid}; Vorkommen gezählt."}


def status_setzen(p: Any, w: DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
    wer = p._akteur(args)
    vid = w.kennung(args.get("id"))
    ziel = _status_wort(args.get("status"), "status")
    erwartet = _status_wort(args.get("expected_status"), "expected_status")
    als_besitzer = wer == p.besitzer
    if ziel == VG.FREIGABE:
        raise ValueError("waiting_approval nur über itsm.freigabe_beantragen" if not als_besitzer else
                         "waiting_approval ist eine Frage an den Besitzer; er setzt sie nicht selbst.")
    if not als_besitzer:
        if ziel == "closed":
            raise ValueError("closed setzt nur der Besitzer; setz resolved und schreib das Ergebnis dazu")
        if ziel not in AGENT_ZIELE:
            raise ValueError(f"status: einer von {', '.join(AGENT_ZIELE)}")
        if not erwartet:
            raise ValueError("expected_status: der Zustand, den du gesehen hast")
    elif ziel not in BESITZER_ZIELE:
        raise ValueError(f"status: einer von {', '.join(BESITZER_ZIELE)}")
    t = w.holen(vid, 5.0)
    alt = str(t.get("status") or "")
    if erwartet and alt != erwartet:
        raise VG.VorgangKonflikt(f"{vid} steht auf „{alt}“, nicht „{erwartet}“ — neu lesen, dann entscheiden", t)
    if alt == VG.FREIGABE:
        raise ValueError(f"{vid} wartet auf die Freigabe des Besitzers; die beantwortet nur er (itsm.freigeben, itsm.ablehnen)")
    if alt == ziel:
        return {"ok": True, "id": vid, "vorgang": vid, "status": alt, "geaendert": False, "satz": f"{vid} steht schon auf {alt}."}
    text = _text(args.get("text") or args.get("begruendung"), "text", maximum=TEXT_MAX)
    patch: dict[str, Any] = {"actor": wer, "status": ziel, "expected_status": alt}
    for feld, schluessel in (("waiting_for", "wartet_auf"), ("assignee", "zustaendig")):
        if args.get(schluessel) is not None:
            patch[feld] = str(args[schluessel]).strip()[:100]
    if is_dry_run(args):
        return _arbeit.plan(p.name, "status_setzen", f"{vid} auf {ziel} setzen", [f"itsm {vid}: status {alt}→{ziel}"],
                            {"id": vid, "status": ziel, "expected_status": alt, "wer": wer})
    if text:
        w.kommentieren(vid, text, wer)
    w.aendern(vid, patch)
    return {"ok": True, "id": vid, "vorgang": vid, "von": alt, "status": ziel, "geaendert": True,
            "satz": f"{vid}: {alt} → {ziel}."}


def entscheiden(p: Any, w: DienstWeg, args: dict[str, Any], ziel: str) -> dict[str, Any]:
    """Freigabe erteilen (→ in_progress) oder ablehnen (→ triage) als Besitzer; nur über die Oberfläche."""
    vid = w.kennung(args.get("id"))
    t = w.holen(vid)
    wort = "erteilt" if ziel == "in_progress" else "abgelehnt"
    if t.get("status") != VG.FREIGABE:
        return {"ok": False, "zustand": "konflikt", "status": t.get("status"),
                "error": f"{vid} wartet nicht (mehr) auf eine Freigabe (Status {t.get('status')}): bereits entschieden."}
    if not _arbeit.echt(args):
        return _arbeit.plan(p.name, "freigeben" if ziel == "in_progress" else "ablehnen", f"Freigabe an {vid} {wort}",
                            [f"itsm {vid}: status waiting_approval→{ziel}"], {"id": vid, "begruendung": args.get("begruendung") or ""})
    begruendung = _text(args.get("begruendung"), "begruendung")
    if begruendung:
        w.kommentieren(vid, begruendung, p.besitzer)
    w.aendern(vid, {"actor": p.besitzer, "status": ziel, "expected_status": VG.FREIGABE})
    return {"ok": True, "id": vid, "status": ziel, "entscheidung": wort, "satz": f"Freigabe an {vid} {wort}."}


# ── Werkzeuge auf beiden Wegen ─────────────────────────────────────────────────────────────────────────
def notiz(p: Any, w: DienstWeg | AblageWeg, args: dict[str, Any]) -> dict[str, Any]:
    """Der Agent hängt eine Notiz an (Fortschritt, Befund, Beleg). Nur anhängen, nichts geht verloren: ohne Bestätigung."""
    wer = p._akteur(args)
    vid = w.kennung(args.get("id"))
    text = _text(args.get("text"), "text", pflicht=True)
    if is_dry_run(args):
        return _arbeit.plan(p.name, "notiz", f"Notiz an {vid} hängen", [f"itsm {vid}: ein Kommentar mehr"],
                            {"id": vid, "text": text, "wer": wer})
    w.kommentieren(vid, text, wer)
    return {"ok": True, "id": vid, "vorgang": vid, "von": wer, "satz": f"Notiz an {vid} gespeichert."}


def _saetze(text: str) -> list[str]:
    t = re.sub(r"\b(z\.\s?B|d\.\s?h|u\.\s?a|bzw|ca|ggf|usw|etc|vgl|Nr)\.", lambda m: m.group(0).replace(".", "․"), text,
               flags=re.IGNORECASE)
    return [s for s in re.split(r"(?<=[.!?…])\s+", t) if s.strip()]


_SCHWAERZEN = (
    (re.compile(r"<private>[\s\S]*?</private>", re.IGNORECASE), "[privat]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{11,}[A-Za-z0-9_~+/=-]"), "Bearer [geschwärzt]"),
    (re.compile(r"\b(?:ghp_|gho_|glpat-|xox[bpa]-|sk-|AKIA)[A-Za-z0-9_-]{8,}"), "[geschwärzt]"),
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), "[geschwärzt]"),
    (re.compile(r"((?:token|passwort|password|passwd|secret|api[_-]?key|kennwort)\s*[:=]\s*)\S*[^\s.,;:!?)]", re.IGNORECASE),
     r"\1[geschwärzt]"),
)


def antrag_angaben(args: dict[str, Any]) -> dict[str, Any] | None:
    """``risiko``, ``zerstoererisch``, ``kontext`` eines Freigabe-Antrags: alle drei oder keine. Fehler → ValueError."""
    namen_ = ("risiko", "zerstoererisch", "kontext")
    if all(args.get(n) is None for n in namen_):
        return None
    fehlt = [n for n in namen_ if args.get(n) is None]
    if fehlt:
        raise ValueError("risiko, zerstoererisch und kontext kommen zusammen; es fehlt: " + ", ".join(fehlt))
    r = {"niedrig": "low", "mittel": "medium", "hoch": "high"}.get(str(args["risiko"]).strip().lower(),
                                                                    str(args["risiko"]).strip().lower())
    if r not in RISIKEN:
        raise ValueError(f"risiko muss low, medium oder high sein, nicht {args['risiko']!r}")
    z = args["zerstoererisch"]
    if not isinstance(z, bool):
        z = {"true": True, "ja": True, "false": False, "nein": False}.get(str(z).strip().lower())
        if z is None:
            raise ValueError(f"zerstoererisch muss true oder false sein, nicht {args['zerstoererisch']!r}")
    if not isinstance(args["kontext"], str):
        raise ValueError("kontext muss ein Text sein")
    k = args["kontext"]
    for muster, ersatz in _SCHWAERZEN:
        k = muster.sub(ersatz, k)
    k = " ".join(k.split())
    if not 3 <= len(_saetze(k)) <= 5:
        raise ValueError("kontext braucht 3 bis 5 Sätze: was ist das Vorhaben, was ändert es, wo, wie kommt man zurück")
    if len(k) > KONTEXT_MAX:
        raise ValueError(f"kontext ist {len(k)} Zeichen lang, erlaubt sind {KONTEXT_MAX}")
    return {"risiko": r, "zerstoererisch": z, "kontext": k}


def freigabe_beantragen(p: Any, w: DienstWeg | AblageWeg, args: dict[str, Any]) -> dict[str, Any]:
    """Der Agent hält einen schweren Schritt am eigenen Vorgang an und legt ihn dem Besitzer vor.

    Der Vorgang gehört dem Agenten und steht auf in_progress. Danach: waiting_approval, wartet auf den Besitzer, das
    Vorhaben steht vorne in der Beschreibung (Kopf ``## Freigabe angefragt (Prüfsumme <hex>)``) und als Kommentar.
    Dasselbe Vorhaben noch einmal ist idempotent. Kein Bestätigungsschritt: der Antrag ist selbst die Frage."""
    wer = p._akteur(args)
    vid = w.kennung(args.get("id"))
    felder: dict[str, str] = {}
    for name, (mind, hoechst) in ANTRAG_FELDER.items():
        wert = str(args.get(name) or "").strip()
        if not mind <= len(wert) <= hoechst:
            raise ValueError(f"{name}: {mind}–{hoechst} Zeichen")
        felder[name] = wert
    angaben = antrag_angaben(args)
    t = w.holen(vid, 5.0)
    pruef = hashlib.sha256(json.dumps({**felder, **(angaben or {})}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    if t.get("status") == VG.FREIGABE:
        if pruef in str(t.get("description") or ""):
            return {"ok": True, "id": vid, "vorgang": vid, "status": VG.FREIGABE, "pruefsumme": pruef, "idempotent": True,
                    "satz": f"{vid} wartet schon mit diesem Vorhaben auf die Freigabe."}
        raise ValueError(f"{vid} wartet schon auf eine andere Freigabe; erst deren Antwort abwarten")
    if str(t.get("assignee") or "").lower() != wer:
        raise ValueError(f"{vid} gehört nicht {wer} (zuständig: {t.get('assignee') or 'niemand'}); erst übernehmen")
    if t.get("status") != "in_progress":
        raise ValueError(f"{vid} ist {t.get('status')}, nicht in_progress; erst übernehmen")
    block = (
        f"{ANTRAG_MARKE} (Prüfsumme {pruef})\n"
        f"**Vorhaben:** {felder['vorhaben']}\n**Wirkung:** {felder['wirkung']}\n**Ziel:** {felder['ziel']}\n"
        f"**Rückweg:** {felder['rueckweg']}" + (f"\n**Beleg:** {felder['beleg']}" if felder["beleg"] else "")
    )
    if is_dry_run(args):
        return _arbeit.plan(p.name, "freigabe_beantragen", f"Freigabe für {vid} beantragen",
                            [f"itsm {vid}: status in_progress→waiting_approval", "Freigabe-Antrag an den Besitzer"],
                            {"id": vid, "vorhaben": felder["vorhaben"], "pruefsumme": pruef})
    worauf = (f"{besitzer_namen(p.besitzer)[0]}: Freigabe — {kurz(felder['vorhaben'], 120)}" if w.art == "dienst"
              else p.besitzer)
    # Erst der Status, dann der Kommentar: wer den Verlauf liest, sieht nie „angefragt“ an einem Vorgang in_progress
    patch: dict[str, Any] = {"actor": wer, "status": VG.FREIGABE, "expected_status": "in_progress", "waiting_for": worauf,
                             "description": f"{block}\n\n---\n{t.get('description') or ''}"[: TEXT_MAX * 4]}
    if angaben and w.art == "dienst":  # im selben PATCH wie waiting_approval: ein Dienst nimmt sie nur so an
        patch.update(angaben)
    w.aendern(vid, patch)
    w.kommentieren(vid, block, wer)
    erg = {"ok": True, "id": vid, "vorgang": vid, "status": VG.FREIGABE, "pruefsumme": pruef,
           "satz": f"{vid} wartet auf die Freigabe des Besitzers. Bis zur Antwort nichts davon ausführen."}
    if angaben:
        erg.update(risiko=angaben["risiko"], zerstoererisch=angaben["zerstoererisch"])
    return erg


def status(p: Any, w: DienstWeg | AblageWeg, args: dict[str, Any]) -> dict[str, Any]:
    """Der Besitzer setzt einen Status per Knopf (nur Oberfläche). Trockenlauf ist Standard; ``ausfuehren`` braucht
    ``expected_status`` (der gesehene Stand); danach liest es den Vorgang neu (``bestaetigt``)."""
    vid = w.kennung(args.get("id"))
    ziel = _status_wort(args.get("status"), "status")
    if ziel == VG.FREIGABE:
        raise ValueError("waiting_approval setzt du nicht selbst — das ist eine Frage an dich, kein Zustand für einen Knopf.")
    if ziel not in BESITZER_ZIELE:
        raise ValueError(f"status: einer von {', '.join(BESITZER_ZIELE)}")
    begruendung = _text(args.get("begruendung"), "begruendung", maximum=2000)
    erwartet = _status_wort(args.get("expected_status"), "expected_status")
    ausfuehren = args.get("ausfuehren") is True and not is_dry_run(args)
    if ausfuehren and not erwartet:
        raise ValueError("expected_status fehlt — der Zustand, den du gesehen hast (aus dem Trockenlauf)")
    t = w.holen(vid)
    alt = str(t.get("status") or "")
    grund = None
    if t.get("archived_at"):
        grund = f"{vid} ist archiviert — erst im Vorgangs-Dienst wieder öffnen."
    elif erwartet and alt != erwartet:
        grund = f"{vid} steht inzwischen auf „{alt}“ (gesehen: „{erwartet}“) — vermutlich schon beantwortet. Bitte neu laden."
    elif alt == VG.FREIGABE:
        grund = f"{vid} wartet auf deine Freigabe — erlaube oder lehne ab, statt den Status zu setzen."
    elif alt == ziel:
        grund = f"{vid} steht schon auf „{ziel}“."
    leeren = wartet_auf_besitzer(t.get("waiting_for"), p.besitzer)
    patch: dict[str, Any] = {"actor": p.besitzer, "status": ziel, "expected_status": alt}
    if leeren:
        patch["waiting_for"] = ""
    wirkung = [f"Der Vorgang geht von „{alt}“ auf „{ziel}“."]
    if alt == "closed":
        wirkung.append("Er wird wieder geöffnet.")
    if ziel == "triage" and w.art == "dienst":
        wirkung.append("Er bekommt beim Dienst eine Wiedervorlage; daraus wird vorerst nicht gearbeitet.")
    elif ziel == "closed":
        wirkung.append("Er ist dann abgeschlossen; nur ein Mensch kann ihn wieder öffnen.")
    if leeren:
        wirkung.append("Er wartet danach nicht mehr auf dich.")
    if begruendung:
        wirkung.append("Deine Begründung steht vorher als Kommentar im Vorgang.")
    kopf = {"ok": True, "aktion": "status", "vorgang": zeile(t), "von": alt, "zu": ziel, "wirkung": wirkung,
            "begruendung": begruendung or None}
    if not ausfuehren:
        frei = {k: v for k, v in args.items() if k not in ("ausfuehren", "__dry_run__")}
        return {**kopf, "trockenlauf": True, "erlaubt": grund is None, "grund": grund,
                "text": f"Trockenlauf: {vid} {alt} → {ziel} — noch nichts geändert.",
                "ausfuehren_mit": {**frei, "id": vid, "status": ziel, "expected_status": alt, "ausfuehren": True}
                if grund is None else None}
    if grund:
        raise ValueError(grund)
    if begruendung:
        w.kommentieren(vid, begruendung, p.besitzer)
    try:
        w.aendern(vid, patch)
    except (ValueError, VG.VorgangKonflikt) as e:
        if begruendung:
            raise ValueError(f"Deine Begründung steht im Vorgang, der Statuswechsel wurde aber abgelehnt: {e}") from e
        raise
    bestaetigt: bool | None
    try:
        danach = w.holen(vid)
        bestaetigt = danach.get("status") == ziel and not (leeren and danach.get("waiting_for"))
    except Exception:  # noqa: BLE001 — geschrieben ist geschrieben, nur die Gegenprobe fehlt
        bestaetigt = None
    hinweise = ([] if bestaetigt else ["Gegenprobe: Der Vorgang zeigt den neuen Zustand nicht — bitte nachsehen."]
                if bestaetigt is False else ["Gegenprobe nicht möglich (Quelle gerade nicht lesbar)."])
    return {**kopf, "trockenlauf": False, "ergebnis": "gesetzt", "id": vid, "status": ziel, "bestaetigt": bestaetigt,
            "warnungen": hinweise, "text": f"{vid} steht jetzt auf „{ziel}“." + ("" if bestaetigt else " Bitte prüfen.")}


#: Werkzeuge, deren Antwort ``wartend`` veralten lässt
SCHREIBEND = frozenset({"anlegen", "kommentieren", "notiz", "status_setzen", "status", "freigabe_beantragen", "freigeben", "ablehnen"})
