"""itsm — Vorgänge (Störungen, Änderungen, Vorhaben) mit Verlauf und Freigaben, im Redis des Hubs.

Das ITSM des Kerns. Es arbeitet gegen die Quelle aus ``vorgaenge.quelle()``, gefragt bei jedem Aufruf:

* **Vorgangs-Dienst** (``FYOS_VORGAENGE_URL`` oder ``vorgaenge.dienst_anmelden``): Die Werkzeuge reichen an den Dienst
  durch (``_itsm_wege``, Vorgangs-Vertrag ``/tickets…`` samt ``/history`` und ``/waiting``). Redis braucht es dafür nicht.
* **Ablage**: Vorgänge in ``fyos:itsm:*`` (``_itsm_ablage``); das Plugin meldet sich beim Hub als Ablage an
  (``mcp_hub.vorgaenge.ablage_anmelden``) und füllt so die App „Vorgänge“. Ohne Dienst und ohne Redis (weder
  ``config.redis_url`` noch ``REDIS_URL``) ist es „nicht eingerichtet“.

Es gibt im Hub nur dieses eine Plugin ``itsm``; ein Paket, das Vorgänge eines eigenen Dienstes zeigt, meldet den Dienst
über ``FYOS_VORGAENGE_URL`` an und registriert kein zweites ``itsm``.

Ein Vorgang hat eine Art (``INC`` Störung, ``CHG`` Änderung, ``VOR`` Vorhaben), Titel, Text, Status
(``new triage in_progress waiting_approval resolved closed``), Priorität, Zuständige, worauf er wartet, Kommentare und
einen Verlauf (wer, wann, was). Eine Freigabe ist der Status ``waiting_approval``: ``→ in_progress`` heißt erteilt,
``→ triage`` abgelehnt. Antworten des Besitzers stehen unter dem Akteur ``FYOS_BESITZER_AKTEUR`` (Vorgabe ``besitzer``);
der Runner (fyos-agent) erkennt sie daran, wenn seine Konfiguration denselben Namen als ``itsm.besitzer`` trägt.

Werkzeuge (``itsm.<name>``):
    liste                Vorgänge nach Status, Art, Zuständigem (lesend)
    vorgang              ein Vorgang mit Verlauf ``[{ts, ereignis, wer, text}]`` (lesend; Form der ITSM-Wache des Runners)
    wartend              offene Vorgänge, die auf den Besitzer warten (lesend; ``{anzahl, tickets, andere_wartende}``)
    anlegen              neuer Vorgang (schreibend)
    kommentieren         Kommentar anhängen (schreibend)
    notiz                Notiz des Agenten anhängen (schreibend, ohne Bestätigung: nur anhängen)
    status_setzen        Status setzen (schreibend)
    freigabe_beantragen  der Agent legt einen schweren Schritt am eigenen Vorgang dem Besitzer vor (ohne Bestätigung)
    status               Status per Knopf als Besitzer, Trockenlauf und Gegenprobe (nur Oberfläche)
    freigeben            Freigabe erteilen (nur Oberfläche; als Besitzer)
    ablehnen             Freigabe ablehnen (nur Oberfläche; als Besitzer)

Bestätigung: Auf der Ablage brauchen ``anlegen``, ``kommentieren``, ``status_setzen``, ``freigeben`` und ``ablehnen``
``bestaetigt: true`` (Plan mit ``__dry_run__``). Beim Vorgangs-Dienst schreiben ``anlegen``, ``kommentieren`` und
``status_setzen`` ohne (wie Agenten sie dort gewohnt sind; ``__dry_run__`` zeigt den Plan), ``freigeben`` und ``ablehnen``
brauchen sie auch dort.

Wer schreibt: über die Oberfläche (``/hub/app-call``) der Besitzer, sonst ``wer`` aus den Argumenten oder der Agent
(``config.agent``, ``FYOS_AGENT_ID``, der erste Name aus ``FYOS_AGENTEN``, Vorgabe ``agent``). Den Besitzer kann ein
Werkzeugaufruf nicht vorgeben.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Any

from .. import vorgaenge as quelle_des_kerns
from ..plugin import HubPlugin, ToolDescriptor, is_dry_run
from ..registry import AUFRUFER
from . import _arbeit
from . import _itsm_wege as wege
from ._itsm_ablage import (
    ARTEN, KOMMENTAR_MAX, PRIORITAETEN, TEXT_MAX, TITEL_MAX, ItsmAblage, akteur, kennung,
)

VERLAUF_VORGABE = 15
VERLAUF_MAX = 50
VERLAUF_TEXT_MAX = 600
BESCHREIBUNG_MAX = 4000
AUSZUG_MAX = 300
ANZAHL_MAX = 200
#: Ziele, die ein Knopf setzen kann (eine Freigabe beantwortet man mit freigeben/ablehnen)
STATUS_ZIELE = ("triage", "in_progress", "resolved", "closed")
#: Über diesen Weg ruft die Oberfläche (registry.AUFRUFER)
OBERFLAECHE = "fyos-web"
NICHT_EINGERICHTET = (
    "ITSM nicht eingerichtet: Es braucht einen Vorgangs-Dienst (FYOS_VORGAENGE_URL) oder das Redis des Hubs "
    "(REDIS_URL oder config.redis_url)."
)


class ItsmNichtBereit(RuntimeError):
    """Weder ein Vorgangs-Dienst noch Redis für die Ablage."""


def _jetzt_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _alter_tage(iso: str) -> int | None:
    try:
        t = dt.datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    return max(0, (dt.datetime.now(dt.timezone.utc) - t).days)


def _zeile(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"], "titel": t["title"], "art": t["type"], "status": t["status"],
        "prioritaet": t.get("priority") or None, "zustaendig": t.get("assignee") or None,
        "wartet_auf": t.get("waiting_for") or None, "aktualisiert": t.get("updated_at") or None,
    }


def _verlaufseintrag(e: dict[str, Any]) -> dict[str, Any]:
    text = str(e.get("detail") or "")
    if len(text) > VERLAUF_TEXT_MAX:
        text = text[:VERLAUF_TEXT_MAX].rstrip() + " …"
    return {"ts": e.get("ts") or None, "ereignis": e.get("event") or None, "wer": e.get("actor") or None, "text": text or None}


#: Schreibende Werkzeuge, deren Bestätigung einstellbar ist (``bestaetigung`` in der Konfiguration)
EINSTELLBAR = ("anlegen", "kommentieren", "status_setzen", "notiz")


class ItsmPlugin(HubPlugin):
    name = "itsm"
    description = "ITSM: Vorgänge (INC, CHG, VOR) mit Status, Kommentaren, Verlauf und Freigaben; Ablage der App „Vorgänge“."
    version = "0.3.0"
    # Texte und Kommentare der Vorgänge gehören nicht auf den Ereignisbus
    argumente_vertraulich = True

    def __init__(self, config: dict[str, Any] | None = None, redis: Any = None):
        super().__init__()
        cfg = dict(config or {})
        self.config = cfg
        self.redis_url = str(cfg.get("redis_url") or os.getenv("REDIS_URL") or "").strip()
        self.agent = akteur(cfg.get("agent") or os.getenv("FYOS_AGENT_ID") or (wege.namen("FYOS_AGENTEN") or ("agent",))[0])
        self._besitzer_cfg = str(cfg.get("besitzer") or "").strip().lower()
        self._redis = redis
        self._ablage: ItsmAblage | None = None
        self._sperre = threading.Lock()
        #: ``wartend`` beim Vorgangs-Dienst, kurz zwischengespeichert: (Zeitpunkt, Antwort)
        self._wartend_frisch: tuple[float, dict[str, Any]] | None = None

    # ── Lebenslauf ──────────────────────────────────────────────────────────────────────────────────
    @property
    def besitzer(self) -> str:
        return akteur(self._besitzer_cfg or quelle_des_kerns.besitzer_akteur())

    @property
    def eingerichtet(self) -> bool:
        return self._redis is not None or bool(self.redis_url)

    def ablage(self) -> ItsmAblage:
        if not self.eingerichtet:
            raise ItsmNichtBereit(NICHT_EINGERICHTET)
        with self._sperre:
            if self._ablage is None:
                if self._redis is None:
                    import redis as _redis_mod  # im Hub-Bild vorhanden

                    self._redis = _redis_mod.Redis.from_url(
                        self.redis_url, socket_timeout=3, socket_connect_timeout=3, decode_responses=True
                    )
                self._ablage = ItsmAblage(self._redis, self.besitzer)
            self._ablage.besitzer = self.besitzer
            return self._ablage

    def register(self) -> None:
        if self.eingerichtet:
            # Die Ablage meldet sich an; ein Vorgangs-Dienst geht in vorgaenge.quelle() trotzdem vor
            quelle_des_kerns.ablage_anmelden(_Anmeldung(self))

    def shutdown(self) -> None:
        if isinstance(quelle_des_kerns.angemeldete_ablage(), _Anmeldung):
            quelle_des_kerns.ablage_anmelden(None)

    def health(self) -> dict[str, Any]:
        q = quelle_des_kerns.quelle()
        if q.art == "dienst":
            # Kein Netzaufruf: der Dienst meldet sich selbst; hier zählt, wohin durchgereicht wird
            return {"ok": True, "status": "healthy", "weg": "dienst", "quelle": q.beschreibung(),
                    "besitzer": self.besitzer, "agent": self.agent}
        if not self.eingerichtet:
            return {"ok": True, "status": "nicht eingerichtet", "hinweis": NICHT_EINGERICHTET}
        try:
            self.ablage().r.ping()
        except Exception as e:  # noqa: BLE001 — Health meldet, wirft nicht
            return {"ok": False, "status": "redis nicht erreichbar", "error": str(e)[:200]}
        return {"ok": True, "status": "healthy", "weg": "ablage", "besitzer": self.besitzer, "agent": self.agent}

    # ── Beschreibung ────────────────────────────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        # Die Ablage kennt INC, CHG, VOR; ein Vorgangs-Dienst auch andere Arten (PRB) und Arbeitskarten (WB-…)
        vid = {"type": "string", "pattern": "^[A-Za-z]{2,6}-[0-9A-Za-z]{1,9}$", "description": "ticket, e.g. INC-12"}
        wer = {"type": "string", "pattern": "^[a-z0-9][a-z0-9_.-]{0,39}$",
               "description": "Actor (default: the agent). Through the interface it is always the owner who writes."}

        def werkzeug(name, titel, beschreibung, eigenschaften, pflicht, tags, meta=None):
            return ToolDescriptor(
                name=name, title=titel, description=beschreibung,
                input_schema={"type": "object", "properties": eigenschaften, "required": pflicht, "additionalProperties": False},
                tags=["itsm", *tags], meta=meta,
            )

        nur_app = {"ui": {"visibility": ["app"]}}
        schreib = ("Mit `__dry_run__: true` kommt nur der Plan; auf der Ablage braucht ein echter Lauf bestaetigt: true "
                   "(beim Vorgangs-Dienst nicht).")
        arten = [*ARTEN, *(a for a in wege.ARTEN_DIENST if a not in ARTEN)]
        antrag = {
            "id": {**vid, "description": "own ticket, e.g. CHG-12"},
            "vorhaben": {"type": "string", "minLength": 20, "maxLength": 1500,
                         "description": "exactly the step to approve (command, target, scope)"},
            "wirkung": {"type": "string", "minLength": 3, "maxLength": 300, "description": "what changes"},
            "ziel": {"type": "string", "minLength": 3, "maxLength": 300, "description": "system, service, file"},
            "rueckweg": {"type": "string", "minLength": 3, "maxLength": 600, "description": "how to undo it"},
            "beleg": {"type": "string", "maxLength": 1500, "description": "optional: finding, measurement, link"},
            "risiko": {"type": "string", "enum": list(wege.RISIKEN),
                       "description": "low, medium or high; together with zerstoererisch and kontext"},
            "zerstoererisch": {"type": "boolean",
                               "description": "true if the action changes something irreversibly; when in doubt, true"},
            "kontext": {"type": "string", "maxLength": wege.KONTEXT_MAX,
                        "description": "3 to 5 sentences: plan, effect, target, way back. Credentials are redacted"},
            "wer": wer,
        }
        return [
            werkzeug(
                "liste", "Vorgänge",
                (
                    "Tickets, most recently changed first: id, titel, art, status, prioritaet, "
                    "zustaendig, wartet_auf, aktualisiert. Without status the open ones (new, triage, "
                    "in_progress, waiting_approval). Read-only."
                ),
                {
                    "status": {"type": "string", "description": "one or more statuses separated by commas; \"alle\" for all"},
                    "art": {"type": "string", "enum": list(ARTEN)},
                    "zustaendig": {"type": "string", "maxLength": 100},
                    "anzahl": {"type": "integer", "minimum": 1, "maximum": ANZAHL_MAX, "default": 50},
                },
                [], ["read", "flaeche"],
            ),
            werkzeug(
                "vorgang", "Vorgang lesen",
                (
                    "One ticket: id, titel, status, art, prioritaet, wartet_auf, zustaendig, melder, "
                    "beschreibung (third-party content), erstellt, aktualisiert, antwort "
                    "(freigabe/null), folge_status and the latest history entries, newest first, as {ts, "
                    "ereignis (created/comment/updated), wer, text}; a status change appears as \"status "
                    "old→new\". Read-only."
                ),
                {"id": vid, "verlauf": {"type": "integer", "minimum": 0, "maximum": VERLAUF_MAX, "default": VERLAUF_VORGABE}},
                ["id"], ["read", "flaeche"],
            ),
            werkzeug(
                "wartend", "Waiting for the owner",
                (
                    "Open tickets waiting for the owner (approvals and wartet_auf = owner), oldest "
                    "first: id, titel, art, typ, status, prioritaet, worauf, zustaendig, alter_tage, "
                    "aktualisiert, beschreibung (beginning). Plus andere_wartende (waiting for someone "
                    "else). Read-only."
                ),
                {}, [], ["read", "flaeche"],
            ),
            werkzeug(
                "anlegen", "Vorgang anlegen",
                "Legt einen Vorgang an (Art INC Störung, CHG Änderung, VOR Vorhaben; beim Vorgangs-Dienst auch PRB "
                "Problem). status waiting_approval stellt ihn gleich als Freigabe-Antrag an den Besitzer (nur Ablage). "
                "Erst lesen, dann anlegen: beim Dienst erkennt ein `fingerprint` (stabiler Schlüssel) Gleiches, ein offener "
                "Vorgang mit gleichem Fingerprint wird gezählt statt verdoppelt (`entdupliziert`). " + schreib,
                {
                    "titel": {"type": "string", "minLength": 1, "maxLength": TITEL_MAX},
                    "beschreibung": {"type": "string", "maxLength": TEXT_MAX},
                    "art": {"type": "string", "enum": arten, "default": "INC"},
                    "typ": {"type": "string", "enum": arten, "description": "other name for art"},
                    "status": {"type": "string", "enum": ["new", "triage", "in_progress", "waiting_approval"], "default": "new"},
                    "prioritaet": {"type": "string", "enum": list(PRIORITAETEN), "default": "normal"},
                    "schwere": {"type": "string", "enum": list(wege.SCHWEREN),
                                "description": "with a ticket service (default from prioritaet, otherwise medium)"},
                    "fingerprint": {"type": "string", "maxLength": 200, "description": "with a ticket service"},
                    "verweise": {"type": "array", "items": {"type": "string"}, "maxItems": 20,
                                 "description": "related tickets (with a ticket service)"},
                    "zustaendig": {"type": "string", "maxLength": 100, "description": "Default: whoever creates it (except the owner)"},
                    "wartet_auf": {"type": "string", "maxLength": 200},
                    "worauf": {"type": "string", "maxLength": 200, "description": "other name for wartet_auf"},
                    "wer": wer,
                    "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["titel"], ["write", "flaeche"],
            ),
            werkzeug(
                "kommentieren", "Kommentar anhängen",
                "Hängt einen Kommentar an einen Vorgang; Status und Zuordnung bleiben. " + schreib,
                {"id": vid, "text": {"type": "string", "minLength": 1, "maxLength": KOMMENTAR_MAX}, "wer": wer,
                 "bestaetigt": _arbeit.BESTAETIGT},
                ["id", "text"], ["write", "flaeche"],
            ),
            werkzeug(
                "notiz", "Notiz an Vorgang",
                "Für den Agenten: hängt eine Notiz an einen Vorgang (Fortschritt, Befund, Ergebnis, Beleg). Ändert weder "
                "Status noch Zuordnung. Nur anhängen: ohne Bestätigung; `__dry_run__` zeigt den Plan.",
                {"id": vid, "text": {"type": "string", "minLength": 1, "maxLength": KOMMENTAR_MAX}, "wer": wer},
                ["id", "text"], ["write"],
            ),
            werkzeug(
                "status_setzen", "Status setzen",
                "Setzt den Status eines Vorgangs. Ein Agent nimmt in_progress, triage oder resolved; closed setzt und "
                "verlässt nur der Besitzer. Auf der Ablage stellt waiting_approval einen Freigabe-Antrag, beim "
                "Vorgangs-Dienst geht das nur über itsm.freigabe_beantragen (dort ist expected_status Pflicht). Eine "
                "Freigabe beantwortet nur der Besitzer (itsm.freigeben, itsm.ablehnen). expected_status (der gesehene "
                "Stand) verhindert, dass eine spätere Antwort eine frühere überschreibt; text geht als Kommentar voraus. "
                + schreib,
                {
                    "id": vid, "status": {"type": "string", "enum": list(quelle_des_kerns.VORGANG_STATUS)},
                    "expected_status": {"type": "string", "enum": list(quelle_des_kerns.VORGANG_STATUS)},
                    "text": {"type": "string", "maxLength": KOMMENTAR_MAX},
                    "begruendung": {"type": "string", "maxLength": KOMMENTAR_MAX, "description": "other name for text"},
                    "wartet_auf": {"type": "string", "maxLength": 100},
                    "zustaendig": {"type": "string", "maxLength": 100},
                    "wer": wer, "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["id", "status"], ["write", "flaeche"],
            ),
            werkzeug(
                "freigabe_beantragen", "Freigabe beantragen",
                "Für den Agenten: hält einen schweren Schritt am eigenen Vorgang an und legt ihn dem Besitzer zur Freigabe "
                "vor. Der Vorgang muss dem Agenten gehören und in_progress sein. Setzt waiting_approval (wartet auf den "
                "Besitzer), stellt das Vorhaben mit Prüfsumme vorne in die Beschreibung (`## Freigabe angefragt (Prüfsumme "
                "…)`) und als Kommentar an den Vorgang. Danach anhalten: die Antwort kommt als Statuswechsel, Schweigen ist "
                "kein Ja. Gleiches Vorhaben noch einmal ist idempotent. risiko, zerstoererisch und kontext kommen zusammen "
                "oder gar nicht (beim Vorgangs-Dienst im selben Schritt wie waiting_approval). Ohne Bestätigung: der Antrag "
                "ist selbst die Frage.",
                antrag, ["id", "vorhaben", "wirkung", "ziel", "rueckweg"], ["write"],
            ),
            werkzeug(
                "status", "Status setzen (Besitzer)",
                "Setzt den Status eines Vorgangs als Besitzer: in_progress, triage, resolved oder closed; nie "
                "waiting_approval (eine Freigabe beantwortet itsm.freigeben/itsm.ablehnen). Wartet der Vorgang auf den "
                "Besitzer, wird waiting_for geleert. Trockenlauf ist Standard (von, zu, Wirkung, ausfuehren_mit); "
                "`ausfuehren: true` braucht expected_status, schreibt (begruendung geht als Kommentar voraus) und prüft nach "
                "(`bestaetigt`). Nur über die Oberfläche.",
                {
                    "id": vid, "status": {"type": "string", "enum": list(wege.BESITZER_ZIELE)},
                    "expected_status": {"type": "string", "enum": list(quelle_des_kerns.VORGANG_STATUS),
                                        "description": "the state the interface saw (required when executing)"},
                    "begruendung": {"type": "string", "maxLength": 2000},
                    "ausfuehren": {"type": "boolean", "default": False},
                },
                ["id", "status"], ["write", "flaeche"], nur_app,
            ),
            werkzeug(
                "freigeben", "Freigabe erteilen",
                "Erteilt die Freigabe an einem Vorgang (waiting_approval → in_progress) als Besitzer; begruendung geht als "
                "Kommentar voraus. Nur über die Oberfläche. " + schreib,
                {"id": vid, "begruendung": {"type": "string", "maxLength": KOMMENTAR_MAX}, "bestaetigt": _arbeit.BESTAETIGT},
                ["id"], ["write", "flaeche"], nur_app,
            ),
            werkzeug(
                "ablehnen", "Freigabe ablehnen",
                "Lehnt die Freigabe an einem Vorgang ab (waiting_approval → triage) als Besitzer; begruendung geht als "
                "Kommentar voraus. Nur über die Oberfläche. " + schreib,
                {"id": vid, "begruendung": {"type": "string", "maxLength": KOMMENTAR_MAX}, "bestaetigt": _arbeit.BESTAETIGT},
                ["id"], ["write", "flaeche"], nur_app,
            ),
        ]

    # ── Aufrufe ─────────────────────────────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = dict(args or {})
        werkzeuge = {
            "liste": self._liste, "vorgang": self._vorgang, "wartend": self._wartend, "anlegen": self._anlegen,
            "kommentieren": self._kommentieren, "status_setzen": self._status_setzen,
            "freigeben": lambda a: self._entscheiden(a, "in_progress"), "ablehnen": lambda a: self._entscheiden(a, "triage"),
            # auf beiden Wegen gleich
            "notiz": lambda a: wege.notiz(self, wege.AblageWeg(self.ablage()), a),
            "freigabe_beantragen": lambda a: wege.freigabe_beantragen(self, wege.AblageWeg(self.ablage()), a),
            "status": lambda a: wege.status(self, wege.AblageWeg(self.ablage()), a),
        }
        if method not in werkzeuge:
            raise ValueError(f"itsm hat kein Werkzeug {method!r}")
        q = quelle_des_kerns.quelle()
        try:
            if q.art == "dienst":
                return self._beim_dienst(method, wege.DienstWeg(q), args)
            if not self.eingerichtet:
                return {"ok": False, "zustand": "nicht eingerichtet", "error": NICHT_EINGERICHTET}
            return werkzeuge[method](args)
        except quelle_des_kerns.VorgangFehlt as e:
            raise ValueError(str(e)) from e
        except quelle_des_kerns.VorgangKonflikt as e:
            stand = e.vorgang.get("status") if e.vorgang else None
            return {"ok": False, "zustand": "konflikt", "error": str(e), "status": stand}

    def _beim_dienst(self, method: str, weg: wege.DienstWeg, args: dict[str, Any]) -> dict[str, Any]:
        """Durchreichen an den Vorgangs-Dienst (``_itsm_wege``); ``wartend`` kurz zwischengespeichert."""
        if method in wege.SCHREIBEND:
            self._wartend_frisch = None
        if method == "wartend":
            stand = self._wartend_frisch
            if stand is not None and time.monotonic() - stand[0] < wege.WARTEND_FRISCH_S:
                return stand[1]
            antwort = wege.wartend(self, weg, args)
            self._wartend_frisch = (time.monotonic(), antwort)
            return antwort
        if method == "vorgang":
            return wege.vorgang(self, weg, args, VERLAUF_VORGABE, VERLAUF_MAX)
        if method in ("freigeben", "ablehnen"):
            return wege.entscheiden(self, weg, args, "in_progress" if method == "freigeben" else "triage")
        if method in EINSTELLBAR:
            args = self._bestaetigung_anwenden(method, weg, args)
        handler = {
            "liste": wege.liste, "anlegen": wege.anlegen, "kommentieren": wege.kommentieren, "notiz": wege.notiz,
            "status_setzen": wege.status_setzen, "freigabe_beantragen": wege.freigabe_beantragen, "status": wege.status,
        }[method]
        return handler(self, weg, args)

    # Bestätigung (Entscheidung Nr. 740: der Nutzer entscheidet)
    def braucht_bestaetigung(self, method: str, weg: Any) -> bool:
        """Ob ``method`` einen echten Lauf nur mit ``bestaetigt: true`` macht.

        Vorgabe: auf der eigenen Ablage ja, beim Vorgangs-Dienst nein (dort schreibt der Agent wie gewohnt), ``notiz`` nie.
        Einstellbar in der Hub-Konfiguration: ``bestaetigung: true|false`` für alle oder ``bestaetigung: {anlegen: …,
        kommentieren: …, status_setzen: …, notiz: …}`` je Werkzeug. ``freigeben``/``ablehnen`` sind nicht einstellbar
        (nur über die Oberfläche, immer bestätigt).
        """
        vorgabe = method != "notiz" and not isinstance(weg, wege.DienstWeg)
        einstellung = self.config.get("bestaetigung")
        if isinstance(einstellung, bool):
            return einstellung
        if isinstance(einstellung, dict) and isinstance(einstellung.get(method), bool):
            return einstellung[method]
        return vorgabe

    def _bestaetigung_anwenden(self, method: str, weg: Any, args: dict[str, Any]) -> dict[str, Any]:
        if is_dry_run(args):
            return args
        if self.braucht_bestaetigung(method, weg):
            if args.get("bestaetigt") is not True:
                raise ValueError(_arbeit.NICHT_BESTAETIGT)
            return args
        return {**args, "bestaetigt": True}

    # Wer schreibt
    def _akteur(self, args: dict[str, Any]) -> str:
        if AUFRUFER.get() == OBERFLAECHE:
            return self.besitzer
        wer = akteur(args.get("wer"), self.agent)
        if wer == self.besitzer:
            raise ValueError("wer: Als Besitzer schreibt nur die Oberfläche")
        return wer

    # Lesen
    def _liste(self, args: dict[str, Any]) -> dict[str, Any]:
        wunsch = str(args.get("status") or "").strip()
        status = None if wunsch == "alle" else ([s.strip() for s in wunsch.split(",") if s.strip()] if wunsch
                                                else list(quelle_des_kerns.OFFEN))
        for s in status or []:
            if s not in quelle_des_kerns.VORGANG_STATUS:
                raise ValueError(f"unbekannter Status {s!r} (erlaubt: {', '.join(quelle_des_kerns.VORGANG_STATUS)}, alle)")
        art = str(args.get("art") or "").strip().upper()
        zust = str(args.get("zustaendig") or "").strip().lower()
        n = max(1, min(int(args.get("anzahl") or 50), ANZAHL_MAX))
        treffer = [
            t for t in self.ablage().alle()
            if (status is None or t["status"] in status) and (not art or t["type"] == art) and (not zust or t["assignee"] == zust)
        ]
        zeilen = [_zeile(t) for t in treffer[:n]]
        satz = f"{len(treffer)} Vorgang{'e' if len(treffer) != 1 else ''}" if treffer else "Keine Vorgänge"
        return {"ok": True, "anzahl": len(treffer), "gezeigt": len(zeilen), "satz": satz + ".", "vorgaenge": zeilen}

    def _vorgang(self, args: dict[str, Any]) -> dict[str, Any]:
        n = args.get("verlauf", VERLAUF_VORGABE)
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= VERLAUF_MAX:
            raise ValueError(f"verlauf: Anzahl der Einträge, 0 bis {VERLAUF_MAX}")
        a = self.ablage()
        t = a.muss(kennung(args.get("id")))
        status = t["status"]
        text = t["description"]
        return {
            "ok": True, "id": t["id"], "titel": t["title"], "status": status, "art": t["type"],
            "prioritaet": t["priority"] or None, "wartet_auf": t["waiting_for"] or None, "zustaendig": t["assignee"] or None,
            "melder": t["reporter"] or None,
            "beschreibung": (text if len(text) <= BESCHREIBUNG_MAX else text[: BESCHREIBUNG_MAX - 1] + "…") or None,
            "erstellt": t["created_at"] or None, "aktualisiert": t["updated_at"] or None,
            "wartet_seit": t["waiting_since"] or None, "wiedervorlage": None,
            "antwort": "freigabe" if status == quelle_des_kerns.FREIGABE else None,
            "folge_status": [] if status == quelle_des_kerns.FREIGABE else [s for s in STATUS_ZIELE if s != status],
            "verlauf": [_verlaufseintrag(e) for e in a.verlauf(t["id"], n)] if n else [],
            "hinweis": _arbeit.FREMDINHALT,
            "text": f"{t['id']} „{t['title']}“ — {status}",
        }

    def _wartend(self, args: dict[str, Any]) -> dict[str, Any]:
        b = self.besitzer
        offen = [t for t in self.ablage().alle() if t["status"] in quelle_des_kerns.OFFEN]
        warten = [t for t in offen if t["status"] == quelle_des_kerns.FREIGABE or t["waiting_for"] == b]
        andere = sum(1 for t in offen if t["waiting_for"] and t["waiting_for"] != b and t["status"] != quelle_des_kerns.FREIGABE)
        warten.sort(key=lambda t: (t["waiting_since"] or t["updated_at"] or "", t["id"]))
        tickets = []
        for t in warten:
            text = " ".join(t["description"].split())
            tickets.append({
                "id": t["id"], "titel": t["title"], "art": t["type"], "typ": t["type"], "status": t["status"],
                "prioritaet": t["priority"] or None, "worauf": "freigabe" if t["status"] == quelle_des_kerns.FREIGABE else (t["waiting_for"] or None),
                "zustaendig": t["assignee"] or None, "alter_tage": _alter_tage(t["created_at"]),
                "wartet_seit": t["waiting_since"] or None, "aktualisiert": t["updated_at"] or None,
                "beschreibung": (text if len(text) <= AUSZUG_MAX else text[: AUSZUG_MAX - 1] + "…") or None,
            })
        return {"ok": True, "ts": _jetzt_iso(), "besitzer": b, "anzahl": len(tickets), "tickets": tickets, "andere_wartende": andere}

    # Schreiben
    def _anlegen(self, args: dict[str, Any]) -> dict[str, Any]:
        wer = self._akteur(args)
        titel = _arbeit.kurz(args.get("titel"), TITEL_MAX)
        if not titel:
            raise ValueError("titel fehlt")
        art = str(args.get("art") or args.get("typ") or "INC").upper()
        if art not in ARTEN:
            raise ValueError(f"art: eine von {', '.join(ARTEN)}")
        status = str(args.get("status") or "new")
        if status not in ("new", "triage", "in_progress", "waiting_approval"):
            raise ValueError("status beim Anlegen: new, triage, in_progress oder waiting_approval")
        zust = args.get("zustaendig")
        if zust is None:
            zust = "" if wer == self.besitzer else wer
        if not _arbeit.echt(args):
            return _arbeit.plan(
                self.name, "anlegen", f"{art}-Vorgang „{titel}“ anlegen (Status {status})",
                ["itsm: ein Vorgang mehr"] + (["Freigabe-Antrag an den Besitzer"] if status == quelle_des_kerns.FREIGABE else []),
                {"titel": titel, "art": art, "status": status, "zustaendig": zust, "wer": wer},
            )
        t = self.ablage().anlegen(
            titel=titel, beschreibung=args.get("beschreibung") or "", art=art, status=status,
            prioritaet=args.get("prioritaet") or "", zustaendig=zust,
            wartet_auf=args.get("wartet_auf") or args.get("worauf") or "", actor=wer,
        )
        return {"ok": True, "id": t["id"], "vorgang": _zeile(t), "satz": f"Vorgang {t['id']} „{t['title']}“ angelegt."}

    def _kommentieren(self, args: dict[str, Any]) -> dict[str, Any]:
        wer = self._akteur(args)
        a = self.ablage()
        t = a.muss(kennung(args.get("id")))
        text = str(args.get("text") or "").strip()
        if not text:
            raise ValueError("text fehlt")
        if not _arbeit.echt(args):
            return _arbeit.plan(self.name, "kommentieren", f"Kommentar an {t['id']} „{_arbeit.kurz(t['title'], 80)}“ hängen",
                                [f"itsm {t['id']}: ein Kommentar mehr"], {"id": t["id"], "text": text, "wer": wer})
        r = a.kommentieren(t["id"], text, wer)
        return {"ok": True, "id": t["id"], "ts": r["ts"], "satz": f"Kommentar an {t['id']} angehängt."}

    def _status_setzen(self, args: dict[str, Any]) -> dict[str, Any]:
        wer = self._akteur(args)
        a = self.ablage()
        t = a.muss(kennung(args.get("id")))
        ziel = str(args.get("status") or "").strip()
        if ziel not in quelle_des_kerns.VORGANG_STATUS:
            raise ValueError(f"status: einer von {', '.join(quelle_des_kerns.VORGANG_STATUS)}")
        erwartet = args.get("expected_status")
        if t["status"] == quelle_des_kerns.FREIGABE and wer == self.besitzer and ziel in ("in_progress", "triage"):
            raise ValueError("Eine Freigabe beantwortest du mit itsm.freigeben oder itsm.ablehnen.")
        if ziel == quelle_des_kerns.FREIGABE and wer == self.besitzer:
            raise ValueError("waiting_approval ist eine Frage an den Besitzer; er setzt sie nicht selbst.")
        if not _arbeit.echt(args):
            wirkung = [f"itsm {t['id']}: status {t['status']}→{ziel}"]
            if ziel == quelle_des_kerns.FREIGABE:
                wirkung.append("Freigabe-Antrag an den Besitzer")
            return _arbeit.plan(self.name, "status_setzen", f"{t['id']} auf {ziel} setzen", wirkung,
                                {"id": t["id"], "status": ziel, "expected_status": erwartet, "wer": wer})
        if erwartet and t["status"] != erwartet:  # vor dem Kommentar prüfen, sonst bliebe er an einem entschiedenen Vorgang
            raise quelle_des_kerns.VorgangKonflikt(
                f"{t['id']} wurde bereits entschieden (Status: {t['status']}, erwartet: {erwartet})", t)
        text = str(args.get("text") or args.get("begruendung") or "").strip()
        if text:
            a.kommentieren(t["id"], text, wer)
        neu = a.aendern(t["id"], actor=wer, status=ziel, expected_status=erwartet,
                        wartet_auf=args.get("wartet_auf"), zustaendig=args.get("zustaendig"))
        return {"ok": True, "id": neu["id"], "status": neu["status"], "vorgang": _zeile(neu),
                "satz": f"{neu['id']} steht jetzt auf {neu['status']}."}

    def _entscheiden(self, args: dict[str, Any], ziel: str) -> dict[str, Any]:
        # Nur über die Oberfläche (visibility app; der allgemeine Aufruf sperrt das Werkzeug): es schreibt der Besitzer
        wer = self.besitzer
        a = self.ablage()
        t = a.muss(kennung(args.get("id")))
        wort = "erteilt" if ziel == "in_progress" else "abgelehnt"
        if t["status"] != quelle_des_kerns.FREIGABE:
            return {"ok": False, "zustand": "konflikt", "status": t["status"],
                    "error": f"{t['id']} wartet nicht (mehr) auf eine Freigabe (Status {t['status']}): bereits entschieden."}
        if not _arbeit.echt(args):
            return _arbeit.plan(self.name, "freigeben" if ziel == "in_progress" else "ablehnen",
                                f"Freigabe an {t['id']} „{_arbeit.kurz(t['title'], 80)}“ {wort}",
                                [f"itsm {t['id']}: status waiting_approval→{ziel}", "der Agent erfährt es über den Verlauf"],
                                {"id": t["id"], "begruendung": args.get("begruendung") or ""})
        begruendung = str(args.get("begruendung") or "").strip()
        if begruendung:
            a.kommentieren(t["id"], begruendung, wer)
        neu = a.aendern(t["id"], actor=wer, status=ziel, expected_status=quelle_des_kerns.FREIGABE)
        return {"ok": True, "id": neu["id"], "status": neu["status"], "entscheidung": wort,
                "satz": f"Freigabe an {neu['id']} {wort}."}


class _Anmeldung:
    """Die Ablage des Plugins für ``vorgaenge.quelle()`` (Protokoll ``vorgaenge.Ablage``), frisch je Aufruf."""

    def __init__(self, plugin: ItsmPlugin) -> None:
        self.plugin = plugin

    def ablage_liste(self, status: str = "", grenze: int = 50) -> list[dict[str, Any]]:
        return self.plugin.ablage().ablage_liste(status, grenze)

    def ablage_holen(self, vid: str) -> dict[str, Any] | None:
        return self.plugin.ablage().ablage_holen(vid)

    def ablage_anlegen(self, koerper: dict[str, Any]) -> dict[str, Any]:
        return self.plugin.ablage().ablage_anlegen(koerper)

    def ablage_kommentieren(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        return self.plugin.ablage().ablage_kommentieren(vid, koerper)

    def ablage_aendern(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        return self.plugin.ablage().ablage_aendern(vid, koerper)

    def ablage_verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        return self.plugin.ablage().ablage_verlauf(vid, grenze)
