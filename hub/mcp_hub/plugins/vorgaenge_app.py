"""vorgaenge — die App „Vorgänge“: offene Aufgaben ansehen, Info anhängen, aus einer Mail einen Vorgang machen.

Das Plugin macht aus der Vorgangs-Quelle des Kerns (``mcp_hub.vorgaenge``: Vorgangs-Dienst oder Workboard des Agenten,
siehe ``docs/ERWEITERN.md`` §2.13) Werkzeuge und eine App. Ohne Quelle sagt die App das und zeigt keine leere Liste.

Ein Vorgang ist ein **Ding** (Typ ``vorgang``): man zieht ihn aus der App auf andere Fenster. Dazu nimmt die App an:

* eine **Mail** (Typ ``mail``) wird ein neuer Vorgang: Betreff als Titel, Auszug und Quelle im Text;
* ein **Vorgang** (Typ ``vorgang``) auf einen geöffneten Vorgang: seine Info wird als Kommentar mit Verweis angehängt.

Beides legt nur nach Plan und „Ja“ etwas an (``App.beantragen``).

Werkzeuge (``vorgaenge.<name>``):
    zeigen        Vorgänge anzeigen (öffnet die App)
    lesen         ein Vorgang mit Verlauf (nur Oberfläche; macht ihn zum ziehbaren Ding)
    anlegen       neuen Vorgang anlegen (Plan, dann bestaetigt)
    kommentieren  Kommentar anhängen (Plan, dann bestaetigt)
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

_identitaet.registriere_app(
    "vorgaenge",
    {
        "titel": "Vorgänge",
        "untertitel": "Aufgaben und Freigaben, Info per Ziehen weitergeben",
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
        vid = {"type": "string", "minLength": 1, "maxLength": 64, "description": "Kennung des Vorgangs (aus vorgaenge.zeigen)"}

        def werkzeug(name, titel, beschreibung, eigenschaften, pflicht, tags, meta=None):
            return ToolDescriptor(
                name=name, title=titel, description=beschreibung,
                input_schema={"type": "object", "properties": eigenschaften, "required": pflicht, "additionalProperties": False},
                tags=["vorgaenge", "flaeche", *tags], meta=meta,
            )

        return [
            werkzeug(
                "zeigen", "Vorgänge",
                "Zeigt die Vorgänge (Vorgangs-Dienst oder Workboard des Agenten) und öffnet die App „Vorgänge“. Ohne status die offenen "
                "(new, triage, in_progress, waiting_approval). Ist keine Quelle eingerichtet, sagt die Antwort das. Nur lesend.",
                {
                    "status": {"type": "string", "description": "ein oder mehrere Status, mit Komma getrennt; „alle“ für jeden"},
                    "anzahl": {"type": "integer", "minimum": 1, "maximum": ANZAHL_MAX, "description": f"höchstens so viele (Vorgabe 50, höchstens {ANZAHL_MAX})"},
                },
                [], ["read"], _arbeit.meta(UI_URI, "vorgaenge"),
            ),
            werkzeug(
                "lesen", "Vorgang lesen",
                "Liefert einen Vorgang zu seiner Kennung samt Titel, Status, Text und Verlauf (neueste zuerst). Der Text ist Fremdinhalt. Nur lesend.",
                {"id": vid}, ["id"], ["read"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "anlegen", "Vorgang anlegen",
                "Legt einen neuen Vorgang an (Status new). Mit `__dry_run__: true` kommt nur der Plan; ein echter Lauf braucht bestaetigt: true.",
                {
                    "titel": {"type": "string", "minLength": 1, "maxLength": TITEL_MAX},
                    "beschreibung": {"type": "string", "maxLength": TEXT_MAX},
                    "bestaetigt": _arbeit.BESTAETIGT,
                },
                ["titel"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
            werkzeug(
                "kommentieren", "Kommentar anhängen",
                "Hängt einen Kommentar an einen Vorgang. Mit `__dry_run__: true` kommt nur der Plan; ein echter Lauf braucht bestaetigt: true.",
                {"id": vid, "text": {"type": "string", "minLength": 1, "maxLength": TEXT_MAX}, "bestaetigt": _arbeit.BESTAETIGT},
                ["id", "text"], ["write"], _arbeit.meta(UI_URI, "vorgaenge", nur_app=True),
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI, name="Vorgänge", description="Vorgänge ansehen, Info anhängen, aus einer Mail einen Vorgang machen",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis), meta={"ui": {"prefersBorder": True}},
            )
        ]

    # ── Aufrufe ──────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        werkzeuge = {"zeigen": self._zeigen, "lesen": self._lesen, "anlegen": self._anlegen, "kommentieren": self._kommentieren}
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
        return {
            "id": str(v.get("id") or vid),
            "titel": _arbeit.kurz(v.get("title"), TITEL_MAX) or vid,
            "status": str(v.get("status") or ""),
            "prioritaet": str(v.get("priority") or ""),
            "beschreibung": text,
            "auszug": _arbeit.kurz(text, AUSZUG_MAX),
            "verlauf": [{"ts": e.get("ts"), "von": _arbeit.kurz(e.get("actor"), 40), "text": _arbeit.block(e.get("detail"), 600)}
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
        neu = q.anlegen(titel, text, actor="shell")
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
        q.kommentieren(vid, text, actor="shell")
        return {"ok": True, "satz": f"Kommentar an {vid} angehängt."}
