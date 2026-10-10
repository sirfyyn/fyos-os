"""beispiel_app — eine kleine MCP-App zum Abgucken: ein Notizzettel mit Oberfläche (`ui://`).

Das Plugin zeigt, wie eine App im Hub aussieht:

  * Werkzeuge mit `meta["ui"]["resourceUri"]` gehören zu einer Oberfläche; die Shell öffnet sie als Fenster, jeder
    MCP-Client mit MCP-Apps-Unterstützung (SEP-1865) zeigt sie im Gespräch.
  * Die Oberfläche (`ui/beispiel-app.html`) ist reines HTML mit Platzhaltern für Stil, Brücke und Kopf
    (siehe `_oberflaeche.py`). Aus welchem Verzeichnis sie kommt, bestimmt das Plugin: `oberflaeche(datei, ui_verzeichnis)`
    liest aus einem Pfad oder aus dem Unterverzeichnis `ui` eines Python-Pakets. Dieses Plugin nutzt das Verzeichnis
    des Kerns; ein eigenes Plugin-Paket legt seine HTML-Dateien in `<paket>/ui/` und übergibt den Paketnamen.
  * Name, Symbol und Farbton der App stehen in der Identität (`_identitaet.registriere_app`).
  * Lesende Werkzeuge tragen das Tag `read`, schreibende `write`; das Tag `flaeche` erlaubt der Shell, sie über
    `/hub/app-call` aufzurufen. Ein Werkzeug mit `visibility ["app"]` ist nur für die Oberfläche selbst sichtbar.

Werkzeuge:
    beispiel_app.zeigen        Notizen anzeigen (öffnet die App)
    beispiel_app.hinzufuegen   Notiz anfügen (nur Oberfläche)
    beispiel_app.loeschen      Notiz entfernen (nur Oberfläche)

Die Notizen liegen in `mcp_hub.kv` (Redis, sonst im Speicher des Prozesses).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .. import kv
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from . import _identitaet
from ._identitaet import identitaet
from ._oberflaeche import oberflaeche

UI_URI = "ui://fyos/beispiel-app.html"
UI_DATEI = "beispiel-app.html"
SCHLUESSEL = "fyos:beispiel_app:notizen"
NOTIZEN_MAX = 50
TEXT_MAX = 500

_identitaet.registriere_app("beispiel_app", _identitaet.APPS["beispiel_app"], datei=UI_DATEI, hauptwerkzeug="beispiel_app__zeigen")


class BeispielAppPlugin(HubPlugin):
    name = "beispiel_app"
    description = "Beispiel-App: ein Notizzettel mit Oberfläche (zeigt, wie MCP-Apps im Hub gebaut sind)."
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        cfg = config or {}
        #: Verzeichnis (Path) oder Paketname, aus dem die HTML-Datei gelesen wird; leer = Verzeichnis des Kerns.
        ui = cfg.get("ui_verzeichnis")
        self._ui_verzeichnis: Path | str | None = Path(ui) if ui and "/" in str(ui) else (str(ui) if ui else None)
        self._r: Any = None  # Tests setzen eine Attrappe

    def redis(self) -> Any:
        return self._r if self._r is not None else kv.klient()

    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "healthy", "notizen": len(self._lesen())}

    # ── Daten ────────────────────────────────────────────────────────────────
    def _lesen(self) -> list[dict[str, Any]]:
        roh = self.redis().get(SCHLUESSEL)
        try:
            liste = json.loads(roh) if roh else []
        except ValueError:
            liste = []
        return [n for n in liste if isinstance(n, dict) and isinstance(n.get("id"), str)]

    def _schreiben(self, liste: list[dict[str, Any]]) -> None:
        self.redis().set(SCHLUESSEL, json.dumps(liste, ensure_ascii=False))

    # ── Beschreibung ─────────────────────────────────────────────────────────
    def _meta(self, nur_app: bool = False) -> dict[str, Any]:
        ui: dict[str, Any] = {"resourceUri": UI_URI}
        if nur_app:
            ui["visibility"] = ["app"]
        return {"ui": ui, "app": identitaet("beispiel_app")}

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="zeigen",
                title="Notizzettel",
                description="Zeigt die Notizen des Notizzettels (Beispiel-App) und öffnet ihre Oberfläche.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                tags=["beispiel_app", "flaeche", "read"],
                meta=self._meta(),
            ),
            ToolDescriptor(
                name="hinzufuegen",
                title="Notiz hinzufügen",
                description="Hängt eine Notiz an den Notizzettel (höchstens 50 Notizen, je 500 Zeichen).",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": TEXT_MAX}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                tags=["beispiel_app", "flaeche", "write"],
                meta=self._meta(nur_app=True),
            ),
            ToolDescriptor(
                name="loeschen",
                title="Notiz löschen",
                description="Entfernt eine Notiz vom Notizzettel (id aus beispiel_app.zeigen).",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                tags=["beispiel_app", "flaeche", "write"],
                meta=self._meta(nur_app=True),
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI,
                name="Notizzettel",
                description="Beispiel-App: Notizen anzeigen, hinzufügen und löschen",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis),
                meta={"ui": {"prefersBorder": True}},
            )
        ]

    # ── Aufrufe ──────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "zeigen":
            return self.zeigen()
        if method == "hinzufuegen":
            return self.hinzufuegen(args.get("text"))
        if method == "loeschen":
            return self.loeschen(args.get("id"))
        raise ValueError(f"beispiel_app hat kein Werkzeug {method!r}")

    def zeigen(self) -> dict[str, Any]:
        notizen = self._lesen()
        satz = f"{len(notizen)} Notiz{'en' if len(notizen) != 1 else ''} auf dem Zettel." if notizen else "Der Zettel ist leer."
        return {"satz": satz, "anzahl": len(notizen), "notizen": notizen}

    def hinzufuegen(self, text: Any) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text fehlt")
        liste = self._lesen()
        if len(liste) >= NOTIZEN_MAX:
            raise ValueError(f"Der Zettel ist voll ({NOTIZEN_MAX} Notizen) — erst eine löschen")
        liste.append({"id": uuid.uuid4().hex[:8], "text": text.strip()[:TEXT_MAX], "zeit": int(time.time())})
        self._schreiben(liste)
        return {"ok": True, "anzahl": len(liste), "notizen": liste}

    def loeschen(self, id_: Any) -> dict[str, Any]:
        if not isinstance(id_, str) or not id_:
            raise ValueError("id fehlt")
        liste = self._lesen()
        rest = [n for n in liste if n["id"] != id_]
        if len(rest) == len(liste):
            raise ValueError(f"keine Notiz {id_!r}")
        self._schreiben(rest)
        return {"ok": True, "anzahl": len(rest), "notizen": rest}
