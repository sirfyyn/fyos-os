"""vorgaenge — die App „Vorgänge“: offene Aufgaben ansehen, Info anhängen, aus einer Mail einen Vorgang machen.

Das Plugin macht aus der Vorgangs-Quelle des Kerns (``mcp_hub.vorgaenge``: Vorgangs-Dienst oder Ablage eines Plugins,
siehe ``docs/EXTENDING.md`` §2.13) Werkzeuge und eine App. Ohne Quelle sagt die App das und zeigt keine leere Liste.

Ein Vorgang ist ein **Ding** (Typ ``vorgang``): man zieht ihn aus der App auf andere Fenster. Dazu nimmt die App an:

* eine **Mail** (Typ ``mail``) wird ein neuer Vorgang: Betreff als Titel, Auszug und Quelle im Text;
* ein **Vorgang** (Typ ``vorgang``) auf einen geöffneten Vorgang: seine Info wird als Kommentar mit Verweis angehängt.

Beides legt nur nach Plan und „Ja“ etwas an (``App.beantragen``).

Werkzeuge (``vorgaenge.<name>``):
    zeigen        Vorgänge anzeigen (öffnet die App)
    lesen         ein Vorgang mit Verlauf (nur Oberfläche; macht ihn zum ziehbaren Ding)
    anlegen       neuen Vorgang anlegen (Plan, dann bestaetigt)
    kommentieren  Kommentar anhängen (Plan, dann bestaetigt)
    status        Status setzen (nur Oberfläche; Plan, dann bestaetigt)
    entscheiden   Freigabe erteilen oder ablehnen (nur Oberfläche; Plan, dann bestaetigt)

Was die App schreibt, steht unter dem Akteur des Besitzers (``vorgaenge.besitzer_akteur()``, ``FYOS_BESITZER_AKTEUR``):
so erkennt der Agent Kommentare und Freigaben aus der App.
"""

from __future__ import annotations

from typing import Any

from .. import vorgaenge as quelle_des_kerns
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from . import _arbeit, _dinge, _identitaet
from ._oberflaeche import oberflaeche

UI_URI = "ui://fyos/vorgaenge.html"
UI_DATEI = "vorgaenge.html"
TITEL_MAX = 180
TEXT_MAX = 4000
AUSZUG_MAX = 600
ANZAHL_MAX = 100
#: Status, die ein Knopf der App setzt (eine Freigabe beantwortet `entscheiden`)
STATUS_ZIELE = ("triage", "in_progress", "resolved", "closed")

_identitaet.registriere_app(
    "vorgaenge",
    {
        "titel": "Vorgänge",
        "untertitel": "Aufgaben und Freigaben, Info per Ziehen weitergeben",
        "titel_en": "Tickets",
        "untertitel_en": "Tasks and approvals, hand info on by dragging",
        "symbol": "ticket",
        "ton": 18,
        "kategorie": "Arbeit",
    },
    datei=UI_DATEI,
    hauptwerkzeug="vorgaenge__zeigen",
    art="anwendung",
)

# Ein Vorgang ist ein ziehbares Ding. `titel`, `status` und `auszug` berechnet `vorgaenge.lesen`, damit Übergaben sie nur einsetzen.
_dinge.registriere_ding("vorgang", "Vorgang", flaeche="vorgaenge", lesen="vorgaenge.lesen", felder=("titel", "status", "auszug"))
# Mail → Vorgang: Betreff als Titel, Auszug und Quelle im Text. Die App zeigt den Plan von vorgaenge.anlegen und fragt.
_dinge.registriere_uebergabe(
    "mail", "vorgaenge", "vorgaenge.anlegen",
    {"titel": "{betreff}", "beschreibung": "{auszug}\n\nQuelle: Mail von {von}, fyos://mail/{id}"},
    "Aus der Mail einen Vorgang anlegen",
)
# Vorgang → Vorgang: Info übergeben. Welcher Vorgang sie bekommt, bestimmt die App (der geöffnete); darum fehlt `id` hier.
_dinge.registriere_uebergabe(
    "vorgang", "vorgaenge", "vorgaenge.kommentieren",
    {"text": "Info aus {id} „{titel}“ (Status {status}):\n{auszug}\n\nVerweis: fyos://vorgang/{id}"},
    "Info als Kommentar an den geöffneten Vorgang hängen",
)


def _zeile(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(v.get("id") or ""),
        "titel": _arbeit.kurz(v.get("title"), TITEL_MAX),
        "status": str(v.get("status") or ""),
        "prioritaet": str(v.get("priority") or ""),
        "aktualisiert": v.get("updated_at") or v.get("created_at"),
    }


class VorgaengePlugin(HubPlugin):
    name = "vorgaenge"
    description = "Vorgänge: Aufgaben und Freigaben ansehen, anlegen und kommentieren; Mail und Vorgang per Ziehen übergeben."
    version = "0.1.0"
    # Mailauszüge und Kommentare gehören nicht auf den Ereignisbus
    argumente_vertraulich = True

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.config = dict(config or {})
        ui = self.config.get("ui_verzeichnis")
        self._ui_verzeichnis = ui if ui else None

    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        q = quelle_des_kerns.quelle()
        return {"ok": True, "status": "healthy" if q.eingerichtet else "nicht eingerichtet", "quelle": q.art}

    # ── Beschreibung ─────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        vid = {"type": "string", "minLength": 1, "maxLength": 64, "description": "Id of the ticket (from vorgaenge.zeigen)"}

        def werkzeug(name, titel, beschreibung, eigenschaften, pflicht, tags, meta=None):
            return ToolDescriptor(
                name=name, title=titel, description=beschreibung,
                input_schema={"type": "object", "properties": eigenschaften, "required": pflicht, "additionalProperties": False},
                tags=["vorgaenge", "flaeche", *tags], meta=meta,
            )

        return [
            werkzeug(
                "zeigen", "Vorgänge",
                (
                    "Shows the tickets (ticket service or a plugin's store) and opens the app \"Tickets\". "
                    "Without status the open ones (new, triage, in_progress, waiting_approval). If no "
                    "source is set up, the answer says so. Read-only."
                ),
                {
                    "status": {"type": "string", "description": "one or more statuses, separated by commas; \"alle\" for all"},
                    "anzahl": {"type": "integer", "minimum": 1, "maximum": ANZAHL_MAX, "description": f"höchstens so viele (Vorgabe 50, höchstens {ANZAHL_MAX})"},
                },
                [], ["read"], _arbeit.meta(UI_URI, "vorgaenge"),
            ),
            werkzeug(
                "lesen", "Vorgang lesen",
                (
                    "Returns a ticket by its id with title, status, text and history (newest first). The "
                    "text is third-party content. Read-only."
                ),
                {"id": vid}, ["id"], ["read"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "anlegen", "Vorgang anlegen",
                (
                    "Creates a new ticket (status new). With `__dry_run__: true` only the plan comes "
                    "back; a real run needs bestaetigt: true."
                ),
                {
                    "titel": {"type": "string", "minLength": 1, "maxLength": TITEL_MAX},
                    "beschreibung": {"type": "string", "maxLength": TEXT_MAX},
                    "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["titel"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "kommentieren", "Kommentar anhängen",
                (
                    "Attaches a comment to a ticket. With `__dry_run__: true` only the plan comes back; "
                    "a real run needs bestaetigt: true."
                ),
                {"id": vid, "text": {"type": "string", "minLength": 1, "maxLength": TEXT_MAX}, "bestaetigt": _arbeit.BESTAETIGT},
                ["id", "text"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "status", "Status setzen",
                (
                    "Sets the status of a ticket as the owner (triage, in_progress, resolved, closed); "
                    "expected_status is the state you saw. An approval is answered with "
                    "vorgaenge.entscheiden. With `__dry_run__: true` only the plan comes back; a real "
                    "run needs bestaetigt: true."
                ),
                {
                    "id": vid, "status": {"type": "string", "enum": list(STATUS_ZIELE)},
                    "expected_status": {"type": "string", "enum": list(quelle_des_kerns.VORGANG_STATUS)},
                    "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["id", "status"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "entscheiden", "Freigabe beantworten",
                (
                    "Answers an approval as the owner: granted (waiting_approval → in_progress) or "
                    "rejected (→ triage); begruendung goes first as a comment. With `__dry_run__: true` "
                    "only the plan comes back; a real run needs bestaetigt: true."
                ),
                {
                    "id": vid, "entscheidung": {"type": "string", "enum": ["erteilt", "abgelehnt"]},
                    "begruendung": {"type": "string", "maxLength": TEXT_MAX}, "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["id", "entscheidung"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI, name="Vorgänge", description="View tickets, attach info, turn a mail into a ticket",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis), meta={"ui": {"prefersBorder": True}},
            )
        ]

    # ── Aufrufe ──────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        werkzeuge = {"zeigen": self._zeigen, "lesen": self._lesen, "anlegen": self._anlegen, "kommentieren": self._kommentieren,
                     "status": self._status, "entscheiden": self._entscheiden}
        if method not in werkzeuge:
            raise ValueError(f"vorgaenge hat kein Werkzeug {method!r}")
        try:
            return werkzeuge[method](args)
        except quelle_des_kerns.NichtEingerichtet as e:
            if method == "zeigen":
                return {"zustand": "nicht eingerichtet", "satz": "Keine Ablage für Vorgänge eingerichtet.", "hinweis": str(e), "vorgaenge": []}
            return {"ok": False, "zustand": "nicht eingerichtet", "error": str(e)}
        except quelle_des_kerns.VorgangFehlt as e:
            raise ValueError(str(e)) from e
        except quelle_des_kerns.VorgangKonflikt as e:
            return {"ok": False, "zustand": "konflikt", "error": f"{e} Bitte neu laden."}
        except quelle_des_kerns.QuelleFehler as e:
            if method == "zeigen":
                return {"zustand": "fehler", "satz": "Die Vorgänge lassen sich gerade nicht abrufen.", "error": str(e), "vorgaenge": []}
            return {"ok": False, "zustand": "fehler", "error": str(e)}

    def _zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        q = quelle_des_kerns.quelle()
        if not q.eingerichtet:
            raise quelle_des_kerns.NichtEingerichtet()
        wunsch = str(args.get("status") or "").strip()
        if wunsch == "alle":
            liste = q.liste(None, args.get("anzahl") or 50)
        elif wunsch:
            liste = q.liste(wunsch, args.get("anzahl") or 50)
        else:
            liste = q.offen(args.get("anzahl") or 50)
        zeilen = [_zeile(v) for v in liste if v.get("id")]
        satz = f"{len(zeilen)} Vorgang{'e' if len(zeilen) != 1 else ''}" if zeilen else "Keine Vorgänge"
        return {"zustand": "ok", "satz": satz + f" ({q.beschreibung()}).", "quelle": q.art, "vorgaenge": zeilen}

    def _lesen(self, args: dict[str, Any]) -> dict[str, Any]:
        q = quelle_des_kerns.quelle()
        vid = str(args.get("id") or "").strip()
        if not vid:
            raise ValueError("id fehlt")
        v = q.holen(vid)
        text = _arbeit.block(v.get("description"), TEXT_MAX)
        try:
            verlauf = q.verlauf(vid, 20)
        except quelle_des_kerns.QuelleFehler:
            verlauf = []  # der Vorgang ist da, nur der Verlauf nicht: lieber ohne ihn zeigen
        status = str(v.get("status") or "")
        return {
            "id": str(v.get("id") or vid),
            "titel": _arbeit.kurz(v.get("title"), TITEL_MAX) or vid,
            "status": status,
            "prioritaet": str(v.get("priority") or ""),
            "art": str(v.get("type") or ""),
            "zustaendig": str(v.get("assignee") or ""),
            "wartet_auf": str(v.get("waiting_for") or ""),
            "beschreibung": text,
            "auszug": _arbeit.kurz(text, AUSZUG_MAX),
            # Knöpfe der App: eine Freigabe beantwortet man, sonst gehen die übrigen Status
            "antwort": "freigabe" if status == quelle_des_kerns.FREIGABE else None,
            "folge_status": [] if status == quelle_des_kerns.FREIGABE else [s for s in STATUS_ZIELE if s != status],
            "verlauf": [{"ts": e.get("ts"), "von": _arbeit.kurz(e.get("actor"), 40), "ereignis": str(e.get("event") or ""),
                         "text": _arbeit.block(e.get("detail"), 600)}
                        for e in verlauf if isinstance(e, dict)],
            "hinweis": _arbeit.FREMDINHALT,
        }

    def _anlegen(self, args: dict[str, Any]) -> dict[str, Any]:
        titel = _arbeit.kurz(args.get("titel"), TITEL_MAX)
        if not titel:
            raise ValueError("titel fehlt")
        text = _arbeit.block(args.get("beschreibung"), TEXT_MAX)
        q = quelle_des_kerns.quelle()
        if not q.eingerichtet:
            raise quelle_des_kerns.NichtEingerichtet()
        if not _arbeit.echt(args):
            return _arbeit.plan(
                self.name, "anlegen", f"Vorgang „{titel}“ anlegen",
                [f"vorgang: neu angelegt ({q.beschreibung()})"], {"titel": titel, "beschreibung": text},
            )
        neu = q.anlegen(titel, text, actor=quelle_des_kerns.besitzer_akteur())
        return {"ok": True, "vorgang": _zeile(neu), "satz": f"Vorgang {neu.get('id', '')} „{titel}“ angelegt.".replace("  ", " ")}

    def _kommentieren(self, args: dict[str, Any]) -> dict[str, Any]:
        vid = str(args.get("id") or "").strip()
        text = _arbeit.block(args.get("text"), TEXT_MAX)
        if not vid:
            raise ValueError("id fehlt")
        if not text:
            raise ValueError("text fehlt")
        q = quelle_des_kerns.quelle()
        v = q.holen(vid)  # gibt es den Vorgang? sonst kein Plan für etwas, das ins Leere läuft
        titel = _arbeit.kurz(v.get("title"), 80) or vid
        if not _arbeit.echt(args):
            return _arbeit.plan(
                self.name, "kommentieren", f"Kommentar an {vid} „{titel}“ hängen",
                [f"vorgang {vid}: ein Kommentar mehr"], {"id": vid, "text": text},
            )
        q.kommentieren(vid, text, actor=quelle_des_kerns.besitzer_akteur())
        return {"ok": True, "satz": f"Kommentar an {vid} angehängt."}

    def _status(self, args: dict[str, Any]) -> dict[str, Any]:
        vid = str(args.get("id") or "").strip()
        ziel = str(args.get("status") or "").strip()
        if not vid:
            raise ValueError("id fehlt")
        if ziel not in STATUS_ZIELE:
            raise ValueError(f"status: einer von {', '.join(STATUS_ZIELE)}")
        q = quelle_des_kerns.quelle()
        v = q.holen(vid)
        alt = str(v.get("status") or "")
        erwartet = str(args.get("expected_status") or "") or alt
        if alt == quelle_des_kerns.FREIGABE and ziel in ("in_progress", "triage"):
            raise ValueError("Eine Freigabe beantwortest du mit „Erteilen“ oder „Ablehnen“.")
        if not _arbeit.echt(args):
            return _arbeit.plan(self.name, "status", f"{vid} „{_arbeit.kurz(v.get('title'), 80)}“ auf {ziel} setzen",
                                [f"vorgang {vid}: status {alt}→{ziel}"], {"id": vid, "status": ziel, "expected_status": erwartet})
        neu = q.aendern(vid, status=ziel, expected_status=erwartet, actor=quelle_des_kerns.besitzer_akteur())
        return {"ok": True, "vorgang": _zeile(neu) if neu.get("id") else None, "satz": f"{vid} steht jetzt auf {ziel}."}

    def _entscheiden(self, args: dict[str, Any]) -> dict[str, Any]:
        vid = str(args.get("id") or "").strip()
        wort = str(args.get("entscheidung") or "").strip()
        if not vid:
            raise ValueError("id fehlt")
        if wort not in ("erteilt", "abgelehnt"):
            raise ValueError("entscheidung: erteilt oder abgelehnt")
        ziel = "in_progress" if wort == "erteilt" else "triage"
        q = quelle_des_kerns.quelle()
        v = q.holen(vid)
        if str(v.get("status") or "") != quelle_des_kerns.FREIGABE:
            return {"ok": False, "zustand": "konflikt",
                    "error": f"{vid} wartet nicht (mehr) auf eine Freigabe (Status {v.get('status')}): bereits entschieden."}
        begruendung = _arbeit.block(args.get("begruendung"), TEXT_MAX)
        if not _arbeit.echt(args):
            return _arbeit.plan(self.name, "entscheiden", f"Freigabe an {vid} „{_arbeit.kurz(v.get('title'), 80)}“ {wort}",
                                [f"vorgang {vid}: status waiting_approval→{ziel}"], {"id": vid, "entscheidung": wort, "begruendung": begruendung})
        wer = quelle_des_kerns.besitzer_akteur()
        if begruendung:
            q.kommentieren(vid, begruendung, actor=wer)
        neu = q.aendern(vid, status=ziel, expected_status=quelle_des_kerns.FREIGABE, actor=wer)
        return {"ok": True, "vorgang": _zeile(neu) if neu.get("id") else None, "satz": f"Freigabe an {vid} {wort}."}
