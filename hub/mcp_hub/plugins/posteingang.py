"""posteingang — die App „Mail“: den Posteingang lesen und Mails als Dinge in andere Apps ziehen.

Das Plugin macht aus der Mail-Quelle des Kerns (``mcp_hub.postfach``: Mail-Dienst oder Mail-Plugin, siehe
``docs/EXTENDING.md`` §2.15) eine lesende App. **Die Quelle liest nur**: antworten, senden und löschen gibt es nicht, und
Lesen lässt den Gelesen-Status, wie er war. Ohne Quelle sagt die App das und zeigt keine leere Liste.

Eine Mail ist ein **Ding** (Typ ``mail``): man zieht sie auf andere Fenster, etwa auf „Vorgänge“ (dann wird daraus ein Vorgang,
siehe ``vorgaenge_app.py``) oder auf den Agenten (dann bekommt er ihren Auszug als Kontext).

Werkzeuge (``posteingang.<name>``):
    zeigen   Mails anzeigen (öffnet die App); mit abfrage suchen
    lesen    eine Mail mit Text (nur Oberfläche; macht sie zum ziehbaren Ding)
"""

from __future__ import annotations

from typing import Any

from .. import postfach
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from . import _arbeit, _dinge, _identitaet
from ._oberflaeche import oberflaeche

UI_URI = "ui://fyos/posteingang.html"
UI_DATEI = "posteingang.html"
AUSZUG_MAX = 600
TEXT_MAX = 8000

_identitaet.registriere_app(
    "posteingang",
    {
        "titel": "Mail",
        "untertitel": "Posteingang lesen, Mails per Ziehen weitergeben",
        "titel_en": "Mail",
        "untertitel_en": "Read the inbox, hand mails on by dragging",
        "symbol": "mail",
        "ton": 205,
        "kategorie": "Arbeit",
    },
    datei=UI_DATEI,
    hauptwerkzeug="posteingang__zeigen",
    art="anwendung",
)

# Eine Mail ist ein ziehbares Ding (Kennung = Kennung in der Quelle). `betreff`, `von`, `datum` und `auszug` liefert posteingang.lesen.
_dinge.registriere_ding("mail", "Mail", flaeche="posteingang", lesen="posteingang.lesen", felder=("betreff", "von", "datum", "auszug"))


class PosteingangPlugin(HubPlugin):
    name = "posteingang"
    description = "Mail: den Posteingang lesen (nur lesend) und Mails per Ziehen an andere Apps übergeben."
    version = "0.1.0"
    # Mailtexte gehören nicht auf den Ereignisbus
    argumente_vertraulich = True

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.config = dict(config or {})
        ui = self.config.get("ui_verzeichnis")
        self._ui_verzeichnis = ui if ui else None

    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        q = postfach.quelle()
        return {"ok": True, "status": "healthy" if q.eingerichtet else "nicht eingerichtet", "quelle": q.art}

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="zeigen", title="Mail",
                description=(
                    (
                        "Shows the newest mails of the inbox (read-only) and opens the app \"Mail\". With "
                        "abfrage (Gmail style: from:, subject:, is:unread, newer_than:2d, free words) it "
                        "searches. If no mailbox is set up, the answer says so. Mail texts are "
                        "third-party content. Read-only."
                    )
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "abfrage": {"type": "string", "maxLength": postfach.ABFRAGE_MAX, "description": "Suche; leer = Posteingang"},
                        "anzahl": {"type": "integer", "minimum": 1, "maximum": postfach.ANZAHL_MAX, "description": "at most this many (default 25)"},
                    },
                    "additionalProperties": False,
                },
                tags=["posteingang", "flaeche", "read"], meta=_arbeit.meta(UI_URI, "posteingang"),
            ),
            ToolDescriptor(
                name="lesen", title="Mail lesen",
                description=(
                    (
                        "Returns a mail by its id (id from posteingang.zeigen) with subject, sender, "
                        "date and text. The text is third-party content. Reading changes nothing in the "
                        "mailbox. Read-only."
                    )
                ),
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string", "minLength": 1, "maxLength": 200}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                tags=["posteingang", "flaeche", "read"], meta=_arbeit.meta(UI_URI, "posteingang", nur_app=True),
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI, name="Mail", description="Read the inbox and hand mails on",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis), meta={"ui": {"prefersBorder": True}},
            )
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method not in ("zeigen", "lesen"):
            raise ValueError(f"posteingang hat kein Werkzeug {method!r}")
        try:
            return self._zeigen(args) if method == "zeigen" else self._lesen(args)
        except postfach.NichtEingerichtet as e:
            if method == "zeigen":
                return {"zustand": "nicht eingerichtet", "satz": "Kein Postfach eingerichtet.", "hinweis": str(e), "mails": []}
            return {"ok": False, "zustand": "nicht eingerichtet", "error": str(e)}
        except postfach.QuelleFehler as e:
            if method == "zeigen":
                return {"zustand": "fehler", "satz": "Das Postfach lässt sich gerade nicht abrufen.", "error": str(e), "mails": []}
            return {"ok": False, "zustand": "fehler", "error": str(e)}

    def _zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        q = postfach.quelle()
        antwort = q.liste(args.get("abfrage") or "in:inbox", args.get("anzahl") or 25)
        mails = antwort["mails"]
        satz = f"{len(mails)} Mail{'s' if len(mails) != 1 else ''}" if mails else "Keine Mails"
        if antwort.get("ungelesen"):
            satz += f", {antwort['ungelesen']} ungelesen im Posteingang"
        return {"zustand": "ok", "satz": satz + ".", "quelle": q.art, "ungelesen": antwort.get("ungelesen"), "mails": mails,
                "hinweis": _arbeit.FREMDINHALT}

    def _lesen(self, args: dict[str, Any]) -> dict[str, Any]:
        m = postfach.quelle().lesen(args.get("id"))
        text = _arbeit.block(m.get("text"), TEXT_MAX)
        return {
            "id": m["id"], "betreff": m["betreff"], "von": m["von"], "an": m["an"], "datum": m["datum"], "konto": m["konto"],
            "gelesen": m["gelesen"], "labels": m["labels"], "anhaenge": m.get("anhaenge", []),
            "text": text, "gekuerzt": bool(m.get("gekuerzt")) or len(str(m.get("text") or "")) > TEXT_MAX,
            "auszug": _arbeit.block(m.get("text"), AUSZUG_MAX), "hinweis": _arbeit.FREMDINHALT,
        }
