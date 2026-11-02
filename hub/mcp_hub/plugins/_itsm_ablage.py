"""Ablage des ITSM im Redis des Hubs: Vorgänge, Verlauf, Kennungen (Schlüssel unter ``fyos:itsm:``).

Die Ablage erfüllt das Protokoll ``mcp_hub.vorgaenge.Ablage`` (Vorgangs-Vertrag, Felder ``title``, ``status`` …) und
kennt darüber hinaus Art, Zuständige und ``waiting_for``. Das Plugin ``itsm`` meldet sie beim Hub an; die App
„Vorgänge“ und andere Plugins lesen sie über ``vorgaenge.quelle()``.

Schlüssel:

    fyos:itsm:nr              laufende Nummer (INCR), eine für alle Arten
    fyos:itsm:alle            Sorted Set Kennung → letzte Änderung (Unix-Sekunden)
    fyos:itsm:v:<id>          Hash mit den Feldern des Vorgangs
    fyos:itsm:verlauf:<id>    Liste (neueste zuerst) aus JSON ``{ts, event, actor, detail}``

Verlauf: ``created``, ``comment`` und ``updated``; ein Statuswechsel steht in ``updated`` als ``status alt→neu``. So
erkennt der Runner (ITSM-Wache, fyos-agent) eine Freigabe: ``waiting_approval→in_progress`` vom Besitzer.

Regeln: ``closed`` setzt und verlässt nur der Besitzer (ein Agent nimmt ``resolved``). ``expected_status`` macht aus
parallelen Antworten „die erste gewinnt“: Stimmt er nicht mehr, kommt ``VorgangKonflikt`` mit dem aktuellen Stand.
Schreiben läuft in einer Redis-Transaktion (WATCH) je Vorgang.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from typing import Any, Callable

from ..vorgaenge import VORGANG_STATUS, FREIGABE, OFFEN, VorgangFehlt, VorgangKonflikt

PRAEFIX = "fyos:itsm:"
K_NR = PRAEFIX + "nr"
K_ALLE = PRAEFIX + "alle"
ARTEN = ("INC", "CHG", "VOR")
ART_VORGABE = "INC"
PRIORITAETEN = ("niedrig", "normal", "hoch", "dringend")
KENNUNG = re.compile(r"^(INC|CHG|VOR)-[1-9][0-9]{0,9}$")
AKTEUR = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
TITEL_MAX = 300
TEXT_MAX = 8000
KOMMENTAR_MAX = 4000
FELD_MAX = 100
VERLAUF_BEHALTEN = 1000
DETAIL_MAX = 4000
LISTE_MAX = 2000
VERSUCHE = 8

#: Felder eines Vorgangs in der Form des Vorgangs-Vertrags (alle als Text im Hash)
FELDER = (
    "id", "type", "title", "description", "status", "priority", "assignee", "waiting_for", "reporter",
    "source_url", "created_at", "updated_at", "waiting_since", "resolved_at", "closed_at",
)


def k_vorgang(vid: str) -> str:
    return f"{PRAEFIX}v:{vid}"


def k_verlauf(vid: str) -> str:
    return f"{PRAEFIX}verlauf:{vid}"


def kennung(vid: Any) -> str:
    t = str(vid or "").strip().upper()
    if not KENNUNG.match(t):
        raise ValueError("id: Vorgang wie INC-12, CHG-3 oder VOR-7")
    return t


def akteur(wer: Any, vorgabe: str = "") -> str:
    t = str(wer or "").strip().lower() or vorgabe
    if not AKTEUR.match(t):
        raise ValueError("akteur: Kleinbuchstaben, Ziffern, Punkt, _ oder -, höchstens 40 Zeichen")
    return t


def _zeile(text: Any, grenze: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= grenze else t[: grenze - 1].rstrip() + "…"


def _block(text: Any, grenze: int) -> str:
    t = "".join(c for c in str(text or "").replace("\r\n", "\n").replace("\r", "\n") if c in "\n\t" or c >= " ").strip()
    if len(t) > grenze:
        raise ValueError(f"Text zu lang (höchstens {grenze} Zeichen)")
    return t


class _Uhr:
    """ISO-Zeit in UTC mit Mikrosekunden, im Prozess streng steigend (der Runner vergleicht Zeitstempel als Text)."""

    def __init__(self, jetzt: Callable[[], float] | None = None) -> None:
        self._jetzt = jetzt or time.time
        self._letzte = 0.0
        self._sperre = threading.Lock()

    def __call__(self) -> tuple[str, float]:
        with self._sperre:
            t = max(float(self._jetzt()), self._letzte + 1e-6)
            self._letzte = t
        return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="microseconds"), t


class ItsmAblage:
    """Vorgänge im Redis. ``r``: Redis-Client mit ``decode_responses=True``. ``besitzer``: Akteur des Besitzers."""

    def __init__(self, r: Any, besitzer: str = "besitzer", jetzt: Callable[[], float] | None = None) -> None:
        self.r = r
        self.besitzer = akteur(besitzer)
        self.uhr = _Uhr(jetzt)

    # ── Lesen ───────────────────────────────────────────────────────────────────────────────────────
    def _laden(self, vid: str, r: Any = None) -> dict[str, Any] | None:
        h = (r or self.r).hgetall(k_vorgang(vid))
        if not h:
            return None
        return {k: h.get(k, "") for k in FELDER}

    def holen(self, vid: Any) -> dict[str, Any] | None:
        try:
            k = kennung(vid)
        except ValueError:
            return None
        return self._laden(k)

    def muss(self, vid: Any) -> dict[str, Any]:
        t = self.holen(vid)
        if t is None:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        return t

    def alle(self, grenze: int = LISTE_MAX) -> list[dict[str, Any]]:
        """Alle Vorgänge, zuletzt geänderte zuerst."""
        ids = self.r.zrevrange(K_ALLE, 0, max(0, min(int(grenze), LISTE_MAX)) - 1)
        if not ids:
            return []
        pipe = self.r.pipeline(transaction=False)
        for vid in ids:
            pipe.hgetall(k_vorgang(vid))
        return [{k: h.get(k, "") for k in FELDER} for h in pipe.execute() if h]

    def verlauf(self, vid: Any, grenze: int = 20) -> list[dict[str, Any]]:
        k = kennung(vid)
        if not self.r.exists(k_vorgang(k)):
            raise VorgangFehlt(f"kein Vorgang {vid}")
        roh = self.r.lrange(k_verlauf(k), 0, max(0, int(grenze)) - 1) if grenze > 0 else []
        aus: list[dict[str, Any]] = []
        for z in roh:
            try:
                e = json.loads(z)
            except ValueError:
                continue
            if isinstance(e, dict):
                aus.append(e)
        return aus

    # ── Schreiben ───────────────────────────────────────────────────────────────────────────────────
    def _eintrag(self, pipe: Any, vid: str, event: str, actor: str, detail: str, ts: str) -> None:
        detail = detail if len(detail) <= DETAIL_MAX else detail[: DETAIL_MAX - 1] + "…"
        pipe.lpush(k_verlauf(vid), json.dumps({"ts": ts, "event": event, "actor": actor, "detail": detail}, ensure_ascii=False))
        pipe.ltrim(k_verlauf(vid), 0, VERLAUF_BEHALTEN - 1)

    def anlegen(self, *, titel: Any, beschreibung: Any = "", art: Any = ART_VORGABE, status: Any = "new",
                prioritaet: Any = "", zustaendig: Any = "", wartet_auf: Any = "", quelle_url: Any = "",
                actor: str) -> dict[str, Any]:
        titel_t = _zeile(titel, TITEL_MAX)
        if not titel_t:
            raise ValueError("titel fehlt")
        art_t = str(art or ART_VORGABE).strip().upper()
        if art_t not in ARTEN:
            raise ValueError(f"art: eine von {', '.join(ARTEN)}")
        status_t = str(status or "new").strip()
        if status_t not in VORGANG_STATUS:
            raise ValueError(f"unbekannter Status {status_t!r}")
        wer = akteur(actor)
        if status_t == "closed" and wer != self.besitzer:
            raise ValueError("closed setzt nur der Besitzer; ein Agent nimmt resolved")
        ts, t = self.uhr()
        vid = f"{art_t}-{int(self.r.incr(K_NR))}"
        warten = _zeile(wartet_auf, FELD_MAX).lower()
        if status_t == FREIGABE and not warten:
            warten = self.besitzer
        felder = {
            "id": vid, "type": art_t, "title": titel_t, "description": _block(beschreibung, TEXT_MAX),
            "status": status_t, "priority": _zeile(prioritaet, 20) or "normal", "assignee": _zeile(zustaendig, FELD_MAX).lower(),
            "waiting_for": warten, "reporter": wer, "source_url": _zeile(quelle_url, 500),
            "created_at": ts, "updated_at": ts, "waiting_since": ts if status_t == FREIGABE else "",
            "resolved_at": ts if status_t == "resolved" else "", "closed_at": ts if status_t == "closed" else "",
        }
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(k_vorgang(vid), mapping=felder)
        pipe.zadd(K_ALLE, {vid: t})
        self._eintrag(pipe, vid, "created", wer, f"{art_t} „{titel_t[:80]}“ angelegt (Status {status_t})", ts)
        pipe.execute()
        return {k: felder.get(k, "") for k in FELDER}

    def kommentieren(self, vid: Any, text: Any, actor: str) -> dict[str, Any]:
        k = kennung(vid)
        inhalt = _block(text, KOMMENTAR_MAX)
        if not inhalt:
            raise ValueError("text fehlt")
        wer = akteur(actor)
        if not self.r.exists(k_vorgang(k)):
            raise VorgangFehlt(f"kein Vorgang {vid}")
        ts, t = self.uhr()
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(k_vorgang(k), "updated_at", ts)
        pipe.zadd(K_ALLE, {k: t})
        self._eintrag(pipe, k, "comment", wer, inhalt, ts)
        pipe.execute()
        return {"ok": True, "id": k, "ts": ts}

    def aendern(self, vid: Any, *, actor: str, status: Any = None, expected_status: Any = None, titel: Any = None,
                beschreibung: Any = None, prioritaet: Any = None, zustaendig: Any = None,
                wartet_auf: Any = None) -> dict[str, Any]:
        """Felder ändern; ``None`` heißt „bleibt“. Eine Transaktion je Vorgang (WATCH), höchstens ``VERSUCHE`` Anläufe."""
        k = kennung(vid)
        wer = akteur(actor)
        ziel = str(status).strip() if status not in (None, "") else None
        if ziel is not None and ziel not in VORGANG_STATUS:
            raise ValueError(f"unbekannter Status {ziel!r} (erlaubt: {', '.join(VORGANG_STATUS)})")
        erwartet = str(expected_status).strip() if expected_status not in (None, "") else None
        if erwartet is not None and erwartet not in VORGANG_STATUS:
            raise ValueError(f"expected_status: einer von {', '.join(VORGANG_STATUS)}")
        import redis as _redis_mod  # im Hub-Bild vorhanden (WatchError)

        for _ in range(VERSUCHE):
            with self.r.pipeline(transaction=True) as pipe:
                try:
                    pipe.watch(k_vorgang(k))
                    alt = self._laden(k, pipe)
                    if alt is None:
                        raise VorgangFehlt(f"kein Vorgang {vid}")
                    neu, aenderungen = self._neu(alt, wer, ziel, erwartet, titel, beschreibung, prioritaet, zustaendig, wartet_auf)
                    if not aenderungen:
                        pipe.unwatch()
                        return alt
                    ts, t = self.uhr()
                    neu["updated_at"] = ts
                    for feld in ("waiting_since", "resolved_at", "closed_at"):
                        if neu.get(feld) == "<jetzt>":
                            neu[feld] = ts
                    pipe.multi()
                    pipe.hset(k_vorgang(k), mapping=neu)
                    pipe.zadd(K_ALLE, {k: t})
                    self._eintrag(pipe, k, "updated", wer, "; ".join(aenderungen), ts)
                    pipe.execute()
                    return neu
                except _redis_mod.WatchError:
                    continue
        raise RuntimeError(f"Vorgang {k}: zu viele gleichzeitige Änderungen, bitte noch einmal")

    def _neu(self, alt: dict[str, Any], wer: str, ziel: str | None, erwartet: str | None, titel: Any, beschreibung: Any,
             prioritaet: Any, zustaendig: Any, wartet_auf: Any) -> tuple[dict[str, Any], list[str]]:
        vid, vorher = alt["id"], alt["status"]
        if erwartet is not None and vorher != erwartet:
            raise VorgangKonflikt(f"{vid} wurde bereits entschieden (Status: {vorher}, erwartet: {erwartet})", alt)
        neu = dict(alt)
        aenderungen: list[str] = []
        ist_besitzer = wer == self.besitzer
        if ziel is not None and ziel != vorher:
            if (ziel == "closed" or vorher == "closed") and not ist_besitzer:
                raise ValueError(
                    f"{vid}: closed setzt und verlässt nur der Besitzer; ein Agent nimmt resolved "
                    "oder legt einen neuen Vorgang an"
                )
            neu["status"] = ziel
            aenderungen.append(f"status {vorher}→{ziel}")
            if ziel == FREIGABE:
                neu["waiting_since"] = "<jetzt>"
                if not neu.get("waiting_for") and wartet_auf is None:
                    neu["waiting_for"] = self.besitzer
            elif vorher == FREIGABE:
                neu["waiting_since"] = ""
                if neu.get("waiting_for") == self.besitzer and wartet_auf is None:
                    neu["waiting_for"] = ""
            if ziel == "resolved":
                neu["resolved_at"] = "<jetzt>"
            if ziel == "closed":
                neu["closed_at"] = "<jetzt>"
            elif vorher == "closed":
                neu["closed_at"] = ""
            if ziel not in OFFEN and wartet_auf is None:
                neu["waiting_for"] = ""
        if titel is not None:
            t = _zeile(titel, TITEL_MAX)
            if not t:
                raise ValueError("titel darf nicht leer sein")
            if t != alt["title"]:
                neu["title"] = t
                aenderungen.append("titel geändert")
        if beschreibung is not None:
            b = _block(beschreibung, TEXT_MAX)
            if b != alt["description"]:
                neu["description"] = b
                aenderungen.append("beschreibung geändert")
        for feld, wert, name, grenze in (("priority", prioritaet, "priorität", 20), ("assignee", zustaendig, "zuständig", FELD_MAX),
                                         ("waiting_for", wartet_auf, "wartet auf", FELD_MAX)):
            if wert is None:
                continue
            w = _zeile(wert, grenze)
            if feld != "priority":
                w = w.lower()
            if w != neu.get(feld, ""):
                aenderungen.append(f"{name} {neu.get(feld) or '–'}→{w or '–'}")
                neu[feld] = w
        return neu, aenderungen

    # ── Protokoll vorgaenge.Ablage (Vorgangs-Vertrag) ───────────────────────────────────────────────
    def ablage_liste(self, status: str = "", grenze: int = 50) -> list[dict[str, Any]]:
        alle = self.alle()
        if status:
            gesucht = {s.strip() for s in str(status).split(",") if s.strip()}
            alle = [t for t in alle if t["status"] in gesucht]
        return alle[: max(1, int(grenze))]

    def ablage_holen(self, vid: str) -> dict[str, Any] | None:
        return self.holen(vid)

    def ablage_anlegen(self, koerper: dict[str, Any]) -> dict[str, Any]:
        art = str(koerper.get("type") or ART_VORGABE).upper()
        return self.anlegen(
            titel=koerper.get("title"), beschreibung=koerper.get("description") or "", art=art if art in ARTEN else ART_VORGABE,
            status=koerper.get("status") or "new", prioritaet=koerper.get("priority") or "",
            quelle_url=koerper.get("source_url") or "", actor=akteur(koerper.get("actor"), "hub"),
        )

    def ablage_kommentieren(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        return self.kommentieren(vid, koerper.get("text"), akteur(koerper.get("actor"), "hub"))

    def ablage_aendern(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        if self.holen(vid) is None:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        return self.aendern(
            vid, actor=akteur(koerper.get("actor"), "hub"), status=koerper.get("status"),
            expected_status=koerper.get("expected_status"), titel=koerper.get("title"),
            beschreibung=koerper.get("description"), prioritaet=koerper.get("priority"),
        )

    def ablage_verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        try:
            return self.verlauf(vid, grenze)
        except ValueError as e:
            raise VorgangFehlt(f"kein Vorgang {vid}") from e
