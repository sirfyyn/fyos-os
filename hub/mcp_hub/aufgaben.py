"""aufgaben — MCP Tasks (Erweiterung `io.modelcontextprotocol/tasks`, SEP-2663, Schema 2026-07-28) im Hub (2026-10-25).

Ein lang laufendes Werkzeug liefert sofort eine Kennung statt des Ergebnisses; danach: Stand abfragen (`tasks/get`),
Eingabe nachreichen (`tasks/update`), abbrechen (`tasks/cancel`). Plan und Begruendung: `docs/current/MCP-TASKS.md`.

Dieses Modul kennt weder das SDK noch HTTP. Es haelt den Speicher (Redis ueber `ansicht.Ablage`, ohne Redis im Pod), startet
die Arbeit in einem Faden und beantwortet get/update/cancel. Die Anbindung steht in `aufgaben_mcp.py` (MCP, SDK 2.x) und in
`server.py` (REST `/hub/aufgaben/*`, `/hub/call` mit `aufgabe`).

Regeln, die hier gelten:
  * Nie eine Aufgabe an einen Aufrufer, der die Erweiterung nicht erklaert hat (`erklaert`), und nur fuer Werkzeuge, die
    ihr Plugin als Task-faehig meldet (`ToolDescriptor.aufgabe`).
  * Nur der Akteur, der die Aufgabe angelegt hat, darf sie lesen, aendern, abbrechen; fremde und unbekannte Kennungen
    antworten gleich (kein Hinweis, dass es sie gibt).
  * Ein endgueltiger Zustand (completed, failed, cancelled) aendert sich nie mehr.
  * Abbruch ist kooperativ: der Faden laeuft zu Ende, sein spaetes Ergebnis wird verworfen.
"""

from __future__ import annotations

import contextvars
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .ansicht import Ablage

logger = logging.getLogger(__name__)

ERWEITERUNG = "io.modelcontextprotocol/tasks"
HUELLE_FAEHIGKEITEN = "io.modelcontextprotocol/clientCapabilities"

WORKING, INPUT_REQUIRED, COMPLETED, FAILED, CANCELLED = "working", "input_required", "completed", "failed", "cancelled"
OFFEN = (WORKING, INPUT_REQUIRED)
ENDGUELTIG = (COMPLETED, FAILED, CANCELLED)

TTL_VORGABE_MS = 3_600_000  # 1 h
TTL_MAX_MS = 86_400_000  # 24 h
POLL_MS = 2000
MAX_OFFEN_AKTEUR = 5
MAX_OFFEN_GESAMT = 20
EINGABE_FRIST_S = 900.0  # 15 min ohne Antwort -> failed
LEBT_TAKT_S = 20.0
LEBT_FRIST_S = 90

#: JSON-RPC-Fehlercodes (Spezifikation: -32602 = ungueltige Angabe; -32000 bis -32099 = Server)
FEHLER_UNBEKANNT = -32602
FEHLER_ZU_VIELE = -32000
FEHLER_INTERN = -32603


class AufgabenFehler(Exception):
    """Fehler beim Umgang mit Aufgaben; `code` = JSON-RPC, `status` = HTTP fuer die REST-Wege."""

    def __init__(self, code: int, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def als_fehler(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def _unbekannt() -> AufgabenFehler:
    return AufgabenFehler(FEHLER_UNBEKANNT, "Aufgabe nicht gefunden", 404)


def _zeit(t: float | None = None) -> str:
    d = datetime.fromtimestamp(time.time() if t is None else t, tz=timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def erklaert(meta_oder_koerper: Any) -> bool:
    """Hat der Aufrufer die Erweiterung erklaert?

    Gilt fuer `params._meta`/den REST-Koerper: entweder die Huelle
    `_meta["io.modelcontextprotocol/clientCapabilities"].extensions` oder (REST, Kurzform) `aufgabe: true`.
    """
    if not isinstance(meta_oder_koerper, dict):
        return False
    if meta_oder_koerper.get("aufgabe") is True:
        return True
    meta = meta_oder_koerper.get("_meta", meta_oder_koerper)
    faehig = meta.get(HUELLE_FAEHIGKEITEN) if isinstance(meta, dict) else None
    erweiterungen = faehig.get("extensions") if isinstance(faehig, dict) else None
    return isinstance(erweiterungen, dict) and ERWEITERUNG in erweiterungen


class AufgabeAbgebrochen(Exception):
    """Wird in `Handle.eingabe` geworfen, wenn die Aufgabe waehrend des Wartens abgebrochen wurde."""


#: Die Aufgabe, in deren Faden der Code gerade laeuft (None bei einem synchronen Aufruf).
AKTUELL: contextvars.ContextVar[Handle | None] = contextvars.ContextVar("mcp_hub_aufgabe", default=None)


def aktuelle() -> Handle | None:
    """Fuer Plugins: das Handle der laufenden Aufgabe oder None, wenn das Werkzeug synchron laeuft."""
    return AKTUELL.get()


class Handle:
    """Was ein Werkzeug in seiner Aufgabe tun kann: Abbruch erfahren, Stand melden, Eingabe erfragen."""

    def __init__(self, aufgaben: Aufgaben, task_id: str):
        self._a = aufgaben
        self.task_id = task_id

    def abgebrochen(self) -> bool:
        rec = self._a._laden(self.task_id)  # noqa: SLF001
        return rec is None or rec["status"] == CANCELLED or bool(rec.get("abbruch"))

    def meldung(self, text: str) -> None:
        """Kurzer Statustext (`statusMessage`) fuer `tasks/get`."""
        self._a._aendern(self.task_id, lambda r: r.update(statusMessage=str(text)[:300]) if r["status"] in OFFEN else None)  # noqa: SLF001

    def eingabe(self, schluessel: str, anfrage: dict[str, Any], frist_s: float = EINGABE_FRIST_S) -> dict[str, Any]:
        """Ruft eine Eingabe vom Client ab (kleine Elicitation) und wartet auf `tasks/update`.

        `anfrage` ist `{"message": "...", "requestedSchema": {...}}` (Formular-Elicitation). Rueckgabe: die Antwort des
        Clients `{"action": "accept"|"decline"|"cancel", "content": {...}}`. Wirft `AufgabeAbgebrochen`, wenn die Aufgabe
        waehrend des Wartens abgebrochen wird, und `TimeoutError` nach `frist_s`.
        """
        return self._a._eingabe_abwarten(self.task_id, schluessel, anfrage, frist_s)  # noqa: SLF001


class Aufgaben:
    def __init__(self, ablage: Ablage | None = None, instanz: str | None = None):
        self.ablage = ablage or Ablage()
        self.instanz = instanz or secrets.token_hex(6)
        self._lock = threading.RLock()
        self._laufend: set[str] = set()
        self._lebt: threading.Thread | None = None
        self._aus = threading.Event()

    # ── Speicher ────────────────────────────────────────────────────────────────
    @staticmethod
    def _schluessel(task_id: str) -> str:
        return f"hub:aufgabe:{task_id}"

    def _laden(self, task_id: str) -> dict[str, Any] | None:
        roh = self.ablage.holen(self._schluessel(task_id))
        if not roh:
            return None
        try:
            return json.loads(roh)
        except ValueError:
            return None

    def _speichern(self, rec: dict[str, Any]) -> None:
        rest_s = int(max(5, (rec["_ablauf"] - time.time()) + 60))  # etwas Nachlauf, damit ein „abgelaufen“ lesbar bleibt
        self.ablage.setzen(self._schluessel(rec["taskId"]), json.dumps(rec, ensure_ascii=False, default=str), rest_s)

    def _aendern(self, task_id: str, fn: Callable[[dict[str, Any]], Any]) -> dict[str, Any] | None:
        """Laden, aendern, speichern unter der Sperre dieses Pods. Endgueltige Aufgaben bleiben unveraendert."""
        with self._lock:
            rec = self._laden(task_id)
            if rec is None or rec["status"] in ENDGUELTIG:
                return rec
            fn(rec)
            rec["lastUpdatedAt"] = _zeit()
            self._speichern(rec)
            return rec

    def _index(self, schluessel: str) -> list[str]:
        roh = self.ablage.holen(schluessel)
        try:
            liste = json.loads(roh) if roh else []
        except ValueError:
            liste = []
        return [str(x) for x in liste] if isinstance(liste, list) else []

    def _index_anhaengen(self, schluessel: str, task_id: str) -> None:
        with self._lock:
            liste = [i for i in self._index(schluessel) if self._laden(i) is not None][-100:]
            liste.append(task_id)
            self.ablage.setzen(schluessel, json.dumps(liste), TTL_MAX_MS // 1000)

    # ── Lebenszeichen und verwaiste Aufgaben ───────────────────────────────────────
    def _lebt_schluessel(self, instanz: str) -> str:
        return f"hub:aufgaben:lebt:{instanz}"

    def _lebt_schlagen(self) -> None:
        while not self._aus.wait(LEBT_TAKT_S):
            if self._laufend:
                self.ablage.setzen(self._lebt_schluessel(self.instanz), "1", LEBT_FRIST_S)

    def _lebt_sicherstellen(self) -> None:
        self.ablage.setzen(self._lebt_schluessel(self.instanz), "1", LEBT_FRIST_S)
        if self._lebt is None or not self._lebt.is_alive():
            self._aus.clear()
            self._lebt = threading.Thread(target=self._lebt_schlagen, name="hub-aufgaben-lebt", daemon=True)
            self._lebt.start()

    def _verwaist(self, rec: dict[str, Any]) -> bool:
        if rec["status"] not in OFFEN:
            return False
        if rec["instanz"] == self.instanz:
            return rec["taskId"] not in self._laufend
        return self.ablage.holen(self._lebt_schluessel(rec["instanz"])) is None

    def _frisch(self, rec: dict[str, Any]) -> dict[str, Any]:
        """Verwaiste Aufgaben (Pod neu gestartet, Faden weg) werden `failed`, statt ewig `working` zu zeigen."""
        if rec["status"] in OFFEN and self._verwaist(rec):
            neu = self._aendern(
                rec["taskId"],
                lambda r: r.update(
                    status=FAILED,
                    statusMessage="Hub neu gestartet, Aufgabe verloren",
                    error={"code": FEHLER_INTERN, "message": "Hub neu gestartet, Aufgabe verloren"},
                    inputRequests=None,
                ),
            )
            return neu or rec
        return rec

    # ── Anlegen ─────────────────────────────────────────────────────────────────
    def _offene_zaehlen(self, schluessel: str) -> int:
        n = 0
        for i in self._index(schluessel):
            rec = self._laden(i)
            if rec is not None and self._frisch(rec)["status"] in OFFEN:
                n += 1
        return n

    def start(
        self,
        werkzeug: str,
        lauf: Callable[[], dict[str, Any]],
        akteur: str,
        ttl_ms: int | None = None,
        kontext: contextvars.Context | None = None,
    ) -> dict[str, Any]:
        """Legt die Aufgabe an (dauerhaft, vor der Antwort), startet `lauf` im Hintergrund, liefert `CreateTaskResult`.

        `lauf()` gibt das Ergebnis zurueck, das der Aufruf synchron geliefert haette (bei `tools/call`: ein `CallToolResult`
        als Dictionary), oder wirft (dann `failed`).
        """
        akteur = str(akteur or "unbekannt")
        if self._offene_zaehlen(f"hub:aufgaben:akteur:{akteur}") >= MAX_OFFEN_AKTEUR:
            raise AufgabenFehler(
                FEHLER_ZU_VIELE, f"zu viele offene Aufgaben ({MAX_OFFEN_AKTEUR} je Akteur) — erst abholen oder abbrechen", 429
            )
        if self._offene_zaehlen("hub:aufgaben:offen") >= MAX_OFFEN_GESAMT:
            raise AufgabenFehler(FEHLER_ZU_VIELE, f"zu viele offene Aufgaben im Hub ({MAX_OFFEN_GESAMT})", 429)
        ttl = TTL_VORGABE_MS if not ttl_ms else max(1000, min(int(ttl_ms), TTL_MAX_MS))
        jetzt = time.time()
        task_id = secrets.token_urlsafe(18)
        rec: dict[str, Any] = {
            "taskId": task_id,
            "status": WORKING,
            "createdAt": _zeit(jetzt),
            "lastUpdatedAt": _zeit(jetzt),
            "ttlMs": ttl,
            "pollIntervalMs": POLL_MS,
            "werkzeug": werkzeug,
            "akteur": akteur,
            "instanz": self.instanz,
            "_ablauf": jetzt + ttl / 1000,
        }
        with self._lock:
            self._speichern(rec)
            self._index_anhaengen(f"hub:aufgaben:akteur:{akteur}", task_id)
            self._index_anhaengen("hub:aufgaben:offen", task_id)
            self._laufend.add(task_id)
        self._lebt_sicherstellen()
        ctx = kontext or contextvars.copy_context()
        threading.Thread(
            target=ctx.run, args=(self._arbeiten, task_id, lauf), name=f"hub-aufgabe-{werkzeug}", daemon=True
        ).start()
        return self._oeffentlich(rec, mit_ergebnis=False)

    def _arbeiten(self, task_id: str, lauf: Callable[[], dict[str, Any]]) -> None:
        marke = AKTUELL.set(Handle(self, task_id))
        try:
            ergebnis = lauf()
            self._aendern(task_id, lambda r: r.update(status=COMPLETED, result=ergebnis, inputRequests=None))
        except AufgabeAbgebrochen:
            pass  # bereits `cancelled`
        except TimeoutError as exc:
            self._fehlschlag(task_id, f"Eingabe-Frist abgelaufen: {exc}")
        except Exception as exc:  # noqa: BLE001 — jede Ausnahme des Werkzeugs wird zur Antwort `failed`, nie zum Absturz
            logger.warning("aufgabe %s: %s: %s", task_id, type(exc).__name__, exc)
            self._fehlschlag(task_id, f"{type(exc).__name__}: {exc}")
        finally:
            AKTUELL.reset(marke)
            self._laufend.discard(task_id)

    def _fehlschlag(self, task_id: str, text: str) -> None:
        fehler = {"code": FEHLER_INTERN, "message": text[:400]}
        self._aendern(task_id, lambda r: r.update(status=FAILED, error=fehler, statusMessage=text[:300], inputRequests=None))

    # ── Lesen, Aendern, Abbrechen ───────────────────────────────────────────────
    def _eigene(self, task_id: str, akteur: str) -> dict[str, Any]:
        rec = self._laden(str(task_id or ""))
        if rec is None or rec.get("akteur") != str(akteur or "unbekannt"):
            raise _unbekannt()
        return self._frisch(rec)

    @staticmethod
    def _oeffentlich(rec: dict[str, Any], mit_ergebnis: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "resultType": "task",
            "taskId": rec["taskId"],
            "status": rec["status"],
            "createdAt": rec["createdAt"],
            "lastUpdatedAt": rec["lastUpdatedAt"],
            "ttlMs": rec["ttlMs"],
            "pollIntervalMs": rec["pollIntervalMs"],
            "_meta": {"fyos/werkzeug": rec.get("werkzeug")},
        }
        if rec.get("statusMessage"):
            out["statusMessage"] = rec["statusMessage"]
        if not mit_ergebnis:
            return out
        out["resultType"] = "complete"
        if rec["status"] == COMPLETED:
            out["result"] = rec.get("result")
        elif rec["status"] == FAILED:
            out["error"] = rec.get("error") or {"code": FEHLER_INTERN, "message": "fehlgeschlagen"}
        elif rec["status"] == INPUT_REQUIRED:
            out["inputRequests"] = rec.get("inputRequests") or {}
        return out

    def lesen(self, task_id: str, akteur: str) -> dict[str, Any]:
        """`tasks/get`: die Aufgabe im aktuellen Zustand (Ergebnis, Fehler oder offene Eingaben je nach Zustand)."""
        return self._oeffentlich(self._eigene(task_id, akteur))

    def aktualisieren(self, task_id: str, akteur: str, antworten: Any) -> dict[str, Any]:
        """`tasks/update`: Antworten auf `inputRequests`. Unbekannte oder erledigte Schluessel werden uebergangen."""
        if not isinstance(antworten, dict) or not all(isinstance(v, dict) for v in antworten.values()):
            raise AufgabenFehler(FEHLER_UNBEKANNT, "inputResponses muss eine Karte von Antworten sein", 400)
        self._eigene(task_id, akteur)

        def tun(r: dict[str, Any]) -> None:
            if r["status"] != INPUT_REQUIRED:
                return
            offene = r.get("inputRequests") or {}
            gegeben = r.setdefault("inputResponses", {})
            for k, v in antworten.items():
                if k in offene:
                    gegeben[k] = v
            if all(k in gegeben for k in offene):
                r["status"] = WORKING
                r["inputRequests"] = None

        self._aendern(task_id, tun)
        return {"resultType": "complete"}

    def abbrechen(self, task_id: str, akteur: str) -> dict[str, Any]:
        """`tasks/cancel`: sofort `cancelled`, Abbruchmarke fuer das Werkzeug; der Faden laeuft ggf. zu Ende (kooperativ)."""
        self._eigene(task_id, akteur)
        self._aendern(
            task_id,
            lambda r: r.update(status=CANCELLED, abbruch=True, statusMessage="abgebrochen", inputRequests=None),
        )
        return {"resultType": "complete"}

    def liste(self, akteur: str) -> list[dict[str, Any]]:
        """Die Aufgaben dieses Akteurs, neueste zuerst, ohne Ergebnis (Kurzform fuer `hub.py aufgabe liste`)."""
        out = []
        for i in reversed(self._index(f"hub:aufgaben:akteur:{akteur}")):
            rec = self._laden(i)
            if rec is None:
                continue
            kurz = self._oeffentlich(self._frisch(rec), mit_ergebnis=False)
            kurz.pop("resultType", None)
            out.append(kurz)
        return out

    # ── Eingabe (input_required) ────────────────────────────────────────────────
    def _eingabe_abwarten(self, task_id: str, schluessel: str, anfrage: dict[str, Any], frist_s: float) -> dict[str, Any]:
        elicitation = {
            "method": "elicitation/create",
            "params": {
                "mode": "form",
                "message": str(anfrage.get("message") or "Eingabe nötig")[:500],
                "requestedSchema": anfrage.get("requestedSchema") or {"type": "object", "properties": {}},
            },
        }

        def setzen(r: dict[str, Any]) -> None:
            r["status"] = INPUT_REQUIRED
            r["inputRequests"] = {**(r.get("inputRequests") or {}), schluessel: elicitation}
            (r.get("inputResponses") or {}).pop(schluessel, None)
            r["statusMessage"] = elicitation["params"]["message"][:300]

        self._aendern(task_id, setzen)
        ende = time.monotonic() + frist_s
        while True:
            rec = self._laden(task_id)
            if rec is None or rec["status"] == CANCELLED or rec.get("abbruch"):
                raise AufgabeAbgebrochen()
            antwort = (rec.get("inputResponses") or {}).get(schluessel)
            if antwort is not None:
                return antwort
            if time.monotonic() > ende:
                raise TimeoutError(f"keine Antwort auf {schluessel!r} nach {frist_s:g} s")
            time.sleep(0.05 if frist_s < 5 else 0.5)

    def beenden(self) -> None:
        self._aus.set()


AUFGABEN = Aufgaben()


def ergebnis_als_aufruf(out: Any, text: Any = None) -> dict[str, Any]:
    """Ein Werkzeug-Ergebnis (Dictionary) als `CallToolResult`-Karte, wie der synchrone MCP-Weg es ausliefert.

    `isError` steht nur, wenn das Werkzeug `ok: false` meldet (anders als synchron, wo der Fehler im Koerper steht und
    der Aufruf trotzdem „gelungen“ ist — hier hilft es Clients, die nur den Zustand `completed` lesen).
    """
    karte: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(out if text is None else text, ensure_ascii=False, default=str)}],
        "structuredContent": out if isinstance(out, dict) else {"result": out},
    }
    if isinstance(out, dict) and out.get("ok") is False:
        karte["isError"] = True
    return karte
