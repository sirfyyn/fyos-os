"""termine — die App „Termine“: anstehende Termine ansehen und aus einem Vorgang einen Termin machen.

Das Plugin macht aus der Termin-Quelle des Kerns (``mcp_hub.termine``: Termin-Dienst oder Kalender-Plugin, siehe
``docs/EXTENDING.md`` §2.14) Werkzeuge und eine App. Ohne Quelle sagt die App das und zeigt keine leere Liste.

Die App nimmt einen **Vorgang** (Typ ``vorgang``) an, der auf ihr Fenster fällt: sie fragt nach dem Zeitpunkt, zeigt den Plan
von ``termine.anlegen`` und legt den Termin erst nach „Ja“ an (``App.beantragen``). Titel und Verweis kommen aus dem Vorgang.

Werkzeuge (``termine.<name>``):
    zeigen   anstehende Termine anzeigen (öffnet die App)
    anlegen  Termin anlegen (Plan, dann bestaetigt)
"""

from __future__ import annotations

from typing import Any

from .. import termine
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from . import _arbeit, _dinge, _identitaet
from ._oberflaeche import oberflaeche

UI_URI = "ui://fyos/termine.html"
UI_DATEI = "termine.html"

_identitaet.registriere_app(
    "termine",
    {
        "titel": "Termine",
        "untertitel": "Anstehende Termine, Termine aus Vorgängen anlegen",
        "titel_en": "Appointments",
        "untertitel_en": "Upcoming appointments, create appointments from tickets",
        "symbol": "calendar-days",
        "ton": 150,
        "kategorie": "Arbeit",
    },
    datei=UI_DATEI,
    hauptwerkzeug="termine__zeigen",
    art="anwendung",
)

# Vorgang → Termine: Titel und Verweis kommen aus dem Vorgang; den Zeitpunkt fragt die App ab (`start` fehlt hier mit Absicht).
_dinge.registriere_uebergabe(
    "vorgang", "termine", "termine.anlegen",
    {"titel": "{titel}", "beschreibung": "Vorgang {id}: {auszug}\n\nVerweis: fyos://vorgang/{id}"},
    "Aus dem Vorgang einen Termin anlegen (Zeitpunkt wählst du)",
)


class TerminePlugin(HubPlugin):
    name = "termine"
    description = "Termine: anstehende ansehen und anlegen; Vorgänge werden per Ziehen zu Terminen."
    version = "0.1.0"
    argumente_vertraulich = True

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.config = dict(config or {})
        ui = self.config.get("ui_verzeichnis")
        self._ui_verzeichnis = ui if ui else None

    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        q = termine.quelle()
        return {"ok": True, "status": "healthy" if q.eingerichtet else "nicht eingerichtet", "quelle": q.art}

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="zeigen", title="Termine",
                description=(
                    (
                        "Shows the upcoming appointments of the next days (appointment service or "
                        "calendar plugin) and opens the app \"Appointments\". If no calendar is set up, "
                        "the answer says so — that is not \"no appointments\". Read-only."
                    )
                ),
                input_schema={
                    "type": "object",
                    "properties": {"tage": {"type": "integer", "minimum": 1, "maximum": termine.DIENST_TAGE_MAX, "description": "Fenster ab jetzt in Tagen (Vorgabe 14)"}},
                    "additionalProperties": False,
                },
                tags=["termine", "flaeche", "read"], meta=_arbeit.meta(UI_URI, "termine"),
            ),
            ToolDescriptor(
                name="anlegen", title="Termin anlegen",
                description=(
                    (
                        "Creates an appointment in the calendar. start is ISO 8601 (YYYY-MM-DD all day, "
                        "otherwise YYYY-MM-DDThh:mm; without an offset the Hub's time zone applies); if "
                        "ende is missing it lasts one hour (all day: one day). With `__dry_run__: true` "
                        "only the plan comes back; a real run needs bestaetigt: true."
                    )
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "titel": {"type": "string", "minLength": 1, "maxLength": termine.TITEL_MAX},
                        "start": {"type": "string", "minLength": 8, "maxLength": 40},
                        "ende": {"type": "string", "maxLength": 40},
                        "ganztaegig": {"type": "boolean"},
                        "ort": {"type": "string", "maxLength": termine.ORT_MAX},
                        "beschreibung": {"type": "string", "maxLength": termine.BESCHREIBUNG_MAX},
                        "kalender": {"type": "string", "maxLength": termine.KALENDER_MAX},
                        "bestaetigt": _arbeit.BESTAETIGT,
                    },
                    "required": ["titel", "start"],
                    "additionalProperties": False,
                },
                tags=["termine", "flaeche", "write"], meta=_arbeit.meta(UI_URI, "termine", nur_app=True),
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI, name="Termine", description="Upcoming appointments and appointments from tickets",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis), meta={"ui": {"prefersBorder": True}},
            )
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method not in ("zeigen", "anlegen"):
            raise ValueError(f"termine hat kein Werkzeug {method!r}")
        try:
            return self._zeigen(args) if method == "zeigen" else self._anlegen(args)
        except termine.NichtEingerichtet as e:
            if method == "zeigen":
                return {"zustand": "nicht eingerichtet", "satz": "Kein Kalender eingerichtet.", "hinweis": str(e), "termine": []}
            return {"ok": False, "zustand": "nicht eingerichtet", "error": str(e)}
        except termine.QuelleFehler as e:
            if method == "zeigen":
                return {"zustand": "fehler", "satz": "Der Kalender lässt sich gerade nicht abrufen.", "error": str(e), "termine": []}
            return {"ok": False, "zustand": "fehler", "error": str(e)}

    def _zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        q = termine.quelle()
        liste = q.anstehende(int(args.get("tage") or 14))
        satz = f"{len(liste)} Termin{'e' if len(liste) != 1 else ''}" if liste else "Keine Termine"
        return {"zustand": "ok", "satz": satz + f" in den nächsten {int(args.get('tage') or 14)} Tagen.", "quelle": q.art, "termine": liste,
                "hinweis": _arbeit.FREMDINHALT}

    def _anlegen(self, args: dict[str, Any]) -> dict[str, Any]:
        felder = {k: args[k] for k in ("titel", "start", "ende", "ganztaegig", "ort", "beschreibung", "kalender") if args.get(k) not in (None, "")}
        neu = termine.pruefe_neu(felder)  # Eingabefehler zuerst, auch beim Plan
        q = termine.quelle()
        if not q.eingerichtet:
            raise termine.NichtEingerichtet()
        if not _arbeit.echt(args):
            wo = f" im Kalender „{neu['kalender']}“" if neu["kalender"] else ""
            return _arbeit.plan(
                self.name, "anlegen", f"Termin „{neu['titel']}“ am {neu['start']}{wo} anlegen",
                [f"kalender: ein Termin mehr ({q.beschreibung()})"], {k: v for k, v in neu.items() if v not in ("", None)},
            )
        t = q.anlegen(felder)
        return {"ok": True, "termin": t, "satz": f"Termin „{t['titel']}“ am {t['start']} angelegt."}
