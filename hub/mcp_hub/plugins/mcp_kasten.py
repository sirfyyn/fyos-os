"""mcp — der Werkzeugkasten für das ganze MCP-Zeug, in der Art des MCP Inspectors, aber in FYOS.

Der offizielle MCP Inspector lässt sich optional verlinken („Im Inspector öffnen“, `uebersicht()["inspector"]`, nur wenn
`MCP_INSPECTOR_URL` gesetzt ist); hier steht, was der Hub selbst weiß, lesend und ohne Geheimnisse:

    mcp.uebersicht    Plugins mit Gesundheit, Werkzeuge mit Scope, Sichtbarkeit und App, Apps, ui://-Ressourcen,
                      Protokollversionen und die Aufrufer, die zuletzt kamen
    mcp.werkzeug      EIN Werkzeug im Detail: Beschreibung, Eingabeschema als lesbare Felder, Beispielaufruf, zugehörige App
    mcp.ausprobieren  ein lesendes, für das Modell sichtbares Werkzeug der Oberflächen wirklich aufrufen (nichts Schreibendes)

Oberfläche: ui://fyos/mcp.html (ui/mcp.html), Identität „MCP“ in _identitaet.py. Die Oberfläche ruft nur Werkzeuge dieses
Plugins (`mcp__…`), so wie es die Shell verlangt; „Ausprobieren“ geht deshalb über `mcp.ausprobieren`, das selbst prüft:

  * Scope READ und Flächen-Werkzeug (`registry.ist_flaechen_werkzeug`) — also nur, was der Browser über `/hub/app-call`
    ohnehin rufen darf; nichts aus dem MCP-Weg allein,
  * nicht „nur für die Oberfläche“ (`visibility ["app"]`) — das schaltet die Oberfläche der jeweiligen App, nicht dieser Kasten,
  * nicht die Plugins mit privaten Inhalten (`PRIVAT_PLUGINS`, per Plugin-Config `privat_plugins` erweiterbar) und nicht
    die Werkzeuge in `PRIVAT_WERKZEUGE`,
  * nicht für Aufrufer von außen (angemeldet über OIDC, Aufrufername `oauth:…`),
  * Ergebnis ohne Felder, die nach Geheimnis heißen (`entschaerfen`), und gekürzt.

Geheimnisse: Das Plugin zeigt weder Konfiguration noch Secret-Bindings noch Rohfelder der Gesundheitsprüfung, sondern
Status, Grund (entschärft, gekürzt) und Zustand der Sicherung je Plugin.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .. import __version__ as HUB_VERSION
from .. import ansicht as _ansicht
from .. import registry as _registry
from .. import zeitplan as _zeitplan
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from ..protokolle import TOR_PROTOKOLLE, sdk_protokolle
from . import _identitaet
from ._identitaet import identitaet
from ._oberflaeche import oberflaeche

UI_MCP = "ui://fyos/mcp.html"
_TAGS = ["mcp", "read", "flaeche"]
GESUNDHEIT_TTL_S = 20.0
ERGEBNIS_MAX_ZEICHEN = 30_000
ZEICHEN_GRUND = 220

#: Plugins, deren Ergebnisse private Inhalte sind (Texte, Geld, Dokumente, Befehle) — die probiert man in
#: ihrer eigenen App, nicht im Werkzeugkasten. Weitere Plugins nennt die Plugin-Config `privat_plugins`.
PRIVAT_PLUGINS = frozenset({"shell", "werkstatt"})
#: Einzelne Werkzeuge mit privatem Inhalt in sonst harmlosen Plugins (Plugin-Config `privat_werkzeuge`).
PRIVAT_WERKZEUGE: frozenset[str] = frozenset()

_GEHEIM_SCHLUESSEL = re.compile(
    r"(?i)(token|secret|passwor|passwd|api[_-]?key|apikey|authorization|bearer|cookie|credential|private[_-]?key|session[_-]?id)"
)
_GEHEIM_TEXT = re.compile(
    r"(?i)((?:token|secret|passwor[dt]|api[_-]?key|authorization)\"?\s*[:=]\s*|\bbearer\s+)(\"[^\"]*\"|'[^']*'|\S+)"
)
_ANMELDUNG_IN_URL = re.compile(r"(\w+://)[^/@\s]+:[^/@\s]+@")
_LANG = re.compile(r"[A-Za-z0-9+/=_-]{40,}")

#: Der offizielle MCP Inspector: ein eigener Dienst, den der Betreiber aufsetzt. `MCP_INSPECTOR_URL` setzt die Adresse
#: (leer = kein Link). `MCP_INSPECTOR_HUB_ZIEL` nennt die Hub-Adresse, die der Inspector ansprechen soll (Vorgabe:
#: öffentliche URL + /mcp, sonst lokal).
INSPECTOR_VERSION = ""

_GESTARTET = time.time()
#: Aufrufer, die der Hub selbst über OIDC angemeldet hat, heißen `oauth:<Zielgruppe>` (siehe anmeldung.py): von außen.
AUFRUFER_EXTERN = "oauth:"


def _extern() -> bool:
    return (_registry.AUFRUFER.get() or "").startswith(AUFRUFER_EXTERN)


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat(timespec="seconds") if t else None


def entschaerfen(text: Any, n: int = ZEICHEN_GRUND) -> str:
    """Text aus einer Gesundheitsprüfung für die Anzeige: Anmeldedaten in Adressen, `token=…`-Paare und lange Schlüssel raus."""
    t = _ANMELDUNG_IN_URL.sub(r"\1«entfernt»@", str(text or ""))
    t = _GEHEIM_TEXT.sub(r"\1«entfernt»", t)
    t = _LANG.sub("«entfernt»", t).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def schwaerzen(wert: Any, tiefe: int = 0) -> Any:
    """Ergebnis eines Probeaufrufs: Werte unter Schlüsseln, die nach Geheimnis heißen, ersetzen; Texte entschärfen."""
    if tiefe > 12:
        return "«zu tief»"
    if isinstance(wert, dict):
        return {
            k: ("«entfernt»" if isinstance(k, str) and _GEHEIM_SCHLUESSEL.search(k) and v not in (None, "", False) else schwaerzen(v, tiefe + 1))
            for k, v in wert.items()
        }
    if isinstance(wert, list):
        return [schwaerzen(v, tiefe + 1) for v in wert[:500]]
    if isinstance(wert, str):
        return entschaerfen(wert, 4000) if wert.strip() else wert
    return wert


# ── Eingabeschema als lesbare Felder ────────────────────────────────────────────────────────────

_TYP_TEXT = {
    "string": "Text",
    "integer": "Ganzzahl",
    "number": "Zahl",
    "boolean": "Ja/Nein",
    "array": "Liste",
    "object": "Objekt",
    "null": "leer",
}


def _typ(schema: dict[str, Any]) -> tuple[str, bool]:
    """(Typname, darf_leer_sein) — `anyOf: [{type: X}, {type: null}]` und `type: [X, null]` sind „X, optional“."""
    t = schema.get("type")
    leer = False
    if isinstance(t, list):
        leer = "null" in t
        rest = [x for x in t if x != "null"]
        t = rest[0] if rest else "null"
    elif t is None:
        for ast in schema.get("anyOf") or schema.get("oneOf") or []:
            if isinstance(ast, dict):
                if ast.get("type") == "null":
                    leer = True
                elif t is None:
                    t = ast.get("type")
                    if "enum" in ast and "enum" not in schema:
                        schema = {**schema, "enum": ast["enum"]}
    if t is None and "enum" in schema:
        t = "string"
    return (t if isinstance(t, str) else "any"), leer


def felder_aus_schema(schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Die Eigenschaften eines JSON-Schemas als Liste lesbarer Felder (Pflichtfelder zuerst).

    Je Feld: `name`, `typ` (JSON-Typ), `typ_text` (deutsch), `pflicht`, `beschreibung`, `standard`, `auswahl`
    (aus `enum`), `von`/`bis` (minimum/maximum), `liste_von` (Elementtyp), `leer_erlaubt`.
    """
    if not isinstance(schema, dict):
        return []
    eigenschaften = schema.get("properties") or {}
    pflicht = set(schema.get("required") or [])
    felder: list[dict[str, Any]] = []
    for name, s in eigenschaften.items():
        s = s if isinstance(s, dict) else {}
        typ, leer = _typ(s)
        eintrag: dict[str, Any] = {
            "name": str(name),
            "typ": typ,
            "typ_text": _TYP_TEXT.get(typ, "beliebig"),
            "pflicht": name in pflicht,
            "beschreibung": str(s.get("description") or "")[:600],
        }
        if leer:
            eintrag["leer_erlaubt"] = True
        if "default" in s:
            eintrag["standard"] = s["default"]
        if isinstance(s.get("enum"), list):
            eintrag["auswahl"] = s["enum"][:60]
        for quelle, ziel in (("minimum", "von"), ("maximum", "bis")):
            if isinstance(s.get(quelle), (int, float)) and not isinstance(s.get(quelle), bool):
                eintrag[ziel] = s[quelle]
        if typ == "array" and isinstance(s.get("items"), dict):
            elem, _ = _typ(s["items"])
            eintrag["liste_von"] = _TYP_TEXT.get(elem, "beliebig")
        if s.get("format"):
            eintrag["format"] = str(s["format"])
        felder.append(eintrag)
    return sorted(felder, key=lambda f: not f["pflicht"])


def beispiel_aus_felder(felder: list[dict[str, Any]]) -> dict[str, Any]:
    """Kleinster gültiger Aufruf: Pflichtfelder mit Platzhalter (Standard, erste Auswahl, sonst leerer Wert seines Typs)."""
    out: dict[str, Any] = {}
    leer = {"string": "", "integer": 0, "number": 0, "boolean": False, "array": [], "object": {}}
    for f in felder:
        if not f["pflicht"]:
            continue
        if "standard" in f:
            out[f["name"]] = f["standard"]
        elif f.get("auswahl"):
            out[f["name"]] = f["auswahl"][0]
        else:
            out[f["name"]] = leer.get(f["typ"], None)
    return out


# ── Das Plugin ──────────────────────────────────────────────────────────────────────────────────


def _chat_tor() -> tuple[set[str], set[str]]:
    """(freigegebene Werkzeuge, davon nur für die Oberfläche) eines vorgeschalteten Tores.

    Dieser Hub bringt kein Tor mit (Anmeldung und Freigabe regelt `anmeldung.py` direkt am MCP-Endpunkt); die Anzeige
    bleibt für Erweiterungen erhalten und ist hier leer.
    """
    return set(), set()


class McpPlugin(HubPlugin):
    name = "mcp"
    description = "Werkzeugkasten für MCP: Plugins, Werkzeuge, Apps, Protokollversionen und Aufrufer des Hubs (lesend)."
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        cfg = config or {}
        self._privat_plugins = PRIVAT_PLUGINS | frozenset(str(x) for x in cfg.get("privat_plugins") or [])
        self._privat_werkzeuge = PRIVAT_WERKZEUGE | frozenset(str(x) for x in cfg.get("privat_werkzeuge") or [])
        self._registry: Any = None
        self._gesundheit: tuple[float, dict[str, dict[str, Any]]] | None = None
        self._sperre = threading.Lock()

    def register(self) -> None:
        return None

    def registry_anbinden(self, registry: Any) -> None:
        """Vom Server nach dem Laden gerufen — die Quelle von allem, was dieses Plugin zeigt."""
        self._registry = registry

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "ok"}

    # ── Daten ─────────────────────────────────────────────────────────────────────────────────

    def _reg(self) -> Any:
        if self._registry is None:
            raise RuntimeError("Der Hub hat dem Werkzeugkasten seine Register noch nicht gegeben")
        return self._registry

    def _gesundheit_lesen(self, frisch: bool) -> dict[str, dict[str, Any]]:
        """`health_check_all` mit kurzer Zwischenablage — jeder Tipp auf „Aktualisieren“ fragt sonst alle Dienste neu."""
        with self._sperre:
            jetzt = time.monotonic()
            if not frisch and self._gesundheit and jetzt - self._gesundheit[0] < GESUNDHEIT_TTL_S:
                return self._gesundheit[1]
            roh = self._reg().health_check_all()
            self._gesundheit = (jetzt, roh)
            return roh

    def _plugin_zeilen(self, frisch: bool) -> list[dict[str, Any]]:
        reg = self._reg()
        roh = self._gesundheit_lesen(frisch)
        zeilen: list[dict[str, Any]] = []
        for name, plugin in reg.plugins.items():
            res = roh.get(name) or {}
            tools = [t for t in reg.tools.values() if t.plugin_name == name]
            if str(res.get("status", "")).lower() == "unreachable":
                status = "unerreichbar"
            elif _registry.plugin_aus(res):
                status = "aus"
            elif _registry.plugin_healthy(res):
                status = "ok"
            else:
                status = "krank"
            grund = res.get("reason") or res.get("error") or res.get("message") or ""
            zeilen.append(
                {
                    "name": name,
                    "beschreibung": (plugin.description or "").strip().splitlines()[0][:240] if plugin.description else "",
                    "version": plugin.version or "",
                    "status": status,
                    "grund": entschaerfen(grund) if status != "ok" else "",
                    "sicherung": str(((res.get("breaker") or {}).get("state")) or ""),
                    "werkzeuge": len(tools),
                    "lesend": sum(1 for t in tools if _registry.scope_from_tags(t.descriptor.tags) == "READ"),
                    "mit_app": sum(1 for t in tools if "ui" in (t.descriptor.meta or {})),
                }
            )
        for name, grund in reg.nicht_geladen.items():
            zeilen.append(
                {
                    "name": name,
                    "beschreibung": "",
                    "version": "",
                    "status": "nicht_geladen",
                    "grund": entschaerfen(grund),
                    "sicherung": "",
                    "werkzeuge": 0,
                    "lesend": 0,
                    "mit_app": 0,
                }
            )
        for name in sorted(getattr(reg, "abgeschaltet", None) or ()):
            if name in reg.plugins or name in reg.nicht_geladen:
                continue
            zeilen.append(
                {
                    "name": name,
                    "beschreibung": "",
                    "version": "",
                    "status": "aus",
                    "grund": "In der Konfiguration abgeschaltet (enabled: false).",
                    "sicherung": "",
                    "werkzeuge": 0,
                    "lesend": 0,
                    "mit_app": 0,
                }
            )
        return sorted(zeilen, key=lambda z: z["name"])

    def _ausprobierbar(self, rt: Any) -> tuple[bool, str]:
        """Darf `mcp.ausprobieren` dieses Werkzeug rufen? Mit Grund, wenn nicht (die Oberfläche zeigt ihn)."""
        d = rt.descriptor
        scope = _registry.scope_from_tags(d.tags)
        if rt.plugin_name == self.name:
            return False, "Das ist der Werkzeugkasten selbst."
        if scope != "READ":
            return False, f"Nur lesende Werkzeuge (Scope {scope}) — Schreibendes bedient die jeweilige App."
        if not _registry.ist_flaechen_werkzeug(d):
            return False, "Dieses Werkzeug gehört nur dem MCP-Weg (kein Flächen-Werkzeug)."
        if _registry.sichtbarkeit(d) == "app":
            return False, "Nur für die Oberfläche der App sichtbar."
        if rt.plugin_name in self._privat_plugins or rt.fqtn in self._privat_werkzeuge:
            return False, "Private Inhalte — nur in der eigenen App."
        if _extern():
            # Von außen angemeldet: der Kasten wäre sonst ein Umweg zu Werkzeugen, die der MCP-Endpunkt nicht freigibt.
            return False, "Von außen nicht möglich — die Werkzeuge dort ruft man direkt über MCP."
        return True, ""

    def _werkzeug_zeile(self, rt: Any, chat: set[str], chat_app: set[str]) -> dict[str, Any]:
        d = rt.descriptor
        scope = _registry.scope_from_tags(d.tags)
        ui = (d.meta or {}).get("ui") if d.meta else None
        uri = ui.get("resourceUri") if isinstance(ui, dict) else None
        app = (d.meta or {}).get("app") if d.meta else None
        mcp_name = rt.fqtn.replace(".", "__", 1)
        felder = felder_aus_schema(d.input_schema)
        gut, grund = self._ausprobierbar(rt)
        kurz = (d.description or "").strip().splitlines()
        return {
            "id": rt.fqtn,
            "plugin": rt.plugin_name,
            "name": rt.tool_name,
            "titel": d.title or "",
            "kurz": (kurz[0] if kurz else "")[:200],
            "scope": scope,
            "sicht": _registry.sichtbarkeit(d),
            "oberflaeche": uri if isinstance(uri, str) else None,
            "app": app.get("titel") if isinstance(app, dict) else None,
            "flaeche": _registry.ist_flaechen_werkzeug(d),
            "mcp_name": mcp_name if uri else None,
            "chat": mcp_name in chat,
            "chat_nur_app": mcp_name in chat_app,
            "felder": len(felder),
            "pflicht": sum(1 for f in felder if f["pflicht"]),
            "ausprobierbar": gut,
            "ausprobier_grund": grund,
        }

    def _apps(self) -> list[dict[str, Any]]:
        """Je `ui://`-Oberfläche eine App: Identität, Werkzeuge, Hauptwerkzeug und Link-Fähigkeit."""
        reg = self._reg()
        nach_uri: dict[str, dict[str, Any]] = {}
        for rt in reg.tools.values():
            d = rt.descriptor
            ui = (d.meta or {}).get("ui") if d.meta else None
            uri = ui.get("resourceUri") if isinstance(ui, dict) else None
            if not uri:
                continue
            app = (d.meta or {}).get("app")
            e = nach_uri.setdefault(
                uri,
                {
                    "uri": uri,
                    "titel": (app or {}).get("titel") if isinstance(app, dict) else rt.plugin_name,
                    "untertitel": (app or {}).get("untertitel", "") if isinstance(app, dict) else "",
                    "symbol": (app or {}).get("symbol", "app-window") if isinstance(app, dict) else "app-window",
                    "ton": (app or {}).get("ton", 250) if isinstance(app, dict) else 250,
                    "kategorie": (app or {}).get("kategorie", "") if isinstance(app, dict) else "",
                    "plugin": rt.plugin_name,
                    "werkzeuge": [],
                    "haupt": None,
                },
            )
            e["werkzeuge"].append(rt.fqtn)
            # Hauptwerkzeug: das Werkzeug, das die App ohne Pflichtargument öffnet (Vorrang: HAUPTWERKZEUG der Identität)
            if _identitaet.link_erlaubt(d.meta, _registry.scope_from_tags(d.tags)) and not (d.input_schema or {}).get("required"):
                if e["haupt"] is None or rt.fqtn.replace(".", "__", 1) in _identitaet.HAUPTWERKZEUG.values():
                    e["haupt"] = rt.fqtn
        for e in nach_uri.values():
            e["werkzeuge"].sort()
            e["oeffnen"] = _identitaet.oeffnen_link(e["haupt"]) if e["haupt"] else None
        return sorted(nach_uri.values(), key=lambda a: (a["kategorie"], a["titel"]))

    def _ressourcen(self) -> list[dict[str, Any]]:
        reg = self._reg()
        zeilen = []
        for uri, (plugin, res) in reg.resources.items():
            zeilen.append(
                {
                    "uri": uri,
                    "plugin": plugin,
                    "name": res.name,
                    "mime": res.mime_type,
                    "beschreibung": (res.description or "")[:200],
                }
            )
        return sorted(zeilen, key=lambda r: r["uri"])

    def _zugaenge(self, chat: set[str]) -> list[dict[str, Any]]:
        sdk = sdk_protokolle()
        modern = sdk["modern"]
        return [
            {
                "name": "Hub (MCP)",
                "pfad": "/mcp",
                "wer": "MCP-Clients (Code-Agenten, Chat-Konnektoren, eigene Clients); von außen mit OIDC-Anmeldung",
                "protokolle": sdk["handshake"] + modern,
                "art": "Handshake und zustandslos" if modern else "Handshake",
            },
            {
                "name": "REST",
                "pfad": "/hub/call, /hub/map, /hub/search",
                "wer": "Skripte und Agenten ohne MCP-Handshake",
                "protokolle": [],
                "art": "JSON ohne MCP-Handshake",
            },
            {
                "name": "Shell",
                "pfad": "/hub/apps, /hub/app-call, /hub/resource",
                "wer": "die Shell im Browser (Fenster, Dock)",
                "protokolle": [],
                "art": "Flächen-Werkzeuge, ui://-Ressourcen",
            },
        ]

    def _inspector(self) -> dict[str, Any] | None:
        """Der Link „Im Inspector öffnen“ — oder nichts, wenn keiner eingerichtet ist.

        Nur http(s)-Adressen (die Umgebung ist Konfiguration, aber der Wert landet im Browser). Von außen angemeldete
        Aufrufer bekommen keinen Link.
        """
        if _extern():
            return None
        url = os.environ.get("MCP_INSPECTOR_URL", "").strip()
        if not re.match(r"https?://[^\s]+$", url):
            return None
        ziel = os.environ.get("MCP_INSPECTOR_HUB_ZIEL", "").strip() or (
            f"{_identitaet.OEFFENTLICHE_URL}/mcp" if _identitaet.OEFFENTLICHE_URL else "http://localhost:8080/mcp"
        )
        return {
            "url": url,
            "version": INSPECTOR_VERSION,
            "hub_ziel": ziel,
            "hinweis": "Offizielles Werkzeug; der Hub-Endpunkt ist dort als Server einzutragen.",
        }

    def uebersicht(self, frisch: bool = False, voll: bool = False, plugin: str = "") -> dict[str, Any]:
        """Ohne `voll` die knappe Ansicht (KI): Zähler, Satz, Plugins in einer Zeile; die Werkzeugliste nur mit `plugin`."""
        reg = self._reg()
        chat, chat_app = _chat_tor()
        plugins = self._plugin_zeilen(bool(frisch))
        if not voll:
            return self._knapp(reg, plugins, str(plugin or "").strip(), chat, chat_app)
        werkzeuge = [self._werkzeug_zeile(rt, chat, chat_app) for rt in reg.tools.values()]
        werkzeuge.sort(key=lambda w: w["id"])
        sdk = sdk_protokolle()
        jetzt = time.time()
        flaechen = [
            {
                "aufrufer": e["aufrufer"],
                "weg": e["weg"],
                "zuletzt": _iso(e["zuletzt"]),
                "vor_s": round(jetzt - e["zuletzt"]),
                "anzahl": e["anzahl"],
                "protokolle": e["protokolle"],
            }
            for e in _registry.flaechen_gesehen()
        ]
        zaehler = {s: sum(1 for p in plugins if p["status"] == s) for s in ("ok", "krank", "unerreichbar", "aus", "nicht_geladen")}
        return {
            "ok": True,
            "satz": self._satz(plugins, len(werkzeuge), len({w["oberflaeche"] for w in werkzeuge if w["oberflaeche"]})),
            "stand": _iso(jetzt),
            "hub": {
                "version": HUB_VERSION,
                "gestartet": _iso(_GESTARTET),
                "sdk": sdk["sdk"],
                "sdk_linie": sdk["linie"],
                "handshake": sdk["handshake"],
                "modern": sdk["modern"],
                "tor": list(TOR_PROTOKOLLE),
            },
            "zaehler": {
                "plugins": len(plugins),
                "werkzeuge": len(werkzeuge),
                "lesend": sum(1 for w in werkzeuge if w["scope"] == "READ"),
                "mit_app": sum(1 for w in werkzeuge if w["oberflaeche"]),
                "apps": len({w["oberflaeche"] for w in werkzeuge if w["oberflaeche"]}),
                "ressourcen": len(reg.resources),
                **zaehler,
            },
            "plugins": plugins,
            "werkzeuge": werkzeuge,
            "apps": self._apps(),
            "ressourcen": self._ressourcen(),
            "zugaenge": self._zugaenge(chat),
            "inspector": self._inspector(),
            "flaechen": flaechen,
            "flaechen_hinweis": "Seit dem Start dieses Hub-Pods; nur Name, Weg, Zeit und Zähler — keine Inhalte.",
            "ansicht_messung": _ansicht.messung(7),
        }

    @staticmethod
    def _satz(plugins: list[dict[str, Any]], werkzeuge: int, apps: int) -> str:
        nicht_ok = [p["name"] for p in plugins if p["status"] != "ok"]
        if not nicht_ok:
            kopf = f"Alle {len(plugins)} Plugins gesund"
        else:
            zeigen = ", ".join(nicht_ok[:4]) + (f" und {len(nicht_ok) - 4} weitere" if len(nicht_ok) > 4 else "")
            kopf = f"{len(nicht_ok)} von {len(plugins)} Plugins nicht gesund ({zeigen})"
        return f"{kopf} · {werkzeuge} Werkzeuge · {apps} Apps."

    def _knapp(self, reg: Any, plugins: list[dict[str, Any]], plugin: str, chat: set[str], chat_app: set[str]) -> dict[str, Any]:
        """Die Antwort ohne `voll`: kein Werkzeugkatalog (der war 136 KB), Plugins in einer Zeile, Rest auf Anfrage."""
        tools = list(reg.tools.values())
        uris = {
            ((rt.descriptor.meta or {}).get("ui") or {}).get("resourceUri")
            for rt in tools
            if isinstance((rt.descriptor.meta or {}).get("ui"), dict)
        } - {None}
        lesend = sum(1 for rt in tools if _registry.scope_from_tags(rt.descriptor.tags) == "READ")
        zaehler = {s: sum(1 for p in plugins if p["status"] == s) for s in ("ok", "krank", "unerreichbar", "aus", "nicht_geladen")}
        sdk = sdk_protokolle()
        zeilen = []
        for p in plugins:
            z = {"name": p["name"], "status": p["status"], "werkzeuge": p["werkzeuge"], "lesend": p["lesend"], "mit_app": p["mit_app"]}
            if p["status"] != "ok" and p["grund"]:
                z["grund"] = p["grund"][:160]
            zeilen.append(z)
        out: dict[str, Any] = {
            "ok": True,
            "knapp": True,
            "satz": self._satz(plugins, len(tools), len(uris)),
            "stand": _iso(time.time()),
            "hub": {"version": HUB_VERSION, "sdk": sdk["sdk"], "handshake": sdk["handshake"], "modern": sdk["modern"], "tor": list(TOR_PROTOKOLLE)},
            "zaehler": {"plugins": len(plugins), "werkzeuge": len(tools), "lesend": lesend, "apps": len(uris), "ressourcen": len(reg.resources), **zaehler},
            "plugins": zeilen,
            "zugaenge": [{"name": z["name"], "pfad": z["pfad"], "wer": z["wer"]} for z in self._zugaenge(chat)],
            "mehr": "Werkzeuge eines Plugins: mcp.uebersicht {plugin: \"<name>\"}; ein Werkzeug im Detail: mcp.werkzeug; alles (Oberfläche): voll: true.",
        }
        if plugin:
            if plugin not in reg.plugins:
                raise ValueError(f"unbekanntes Plugin {plugin!r} (siehe `plugins`)")
            zeilen_w = [self._werkzeug_zeile(rt, chat, chat_app) for rt in tools if rt.plugin_name == plugin]
            out["werkzeuge"] = sorted(
                ({"id": w["id"], "scope": w["scope"], "sicht": w["sicht"], "app": w["app"], "kurz": w["kurz"][:120]} for w in zeilen_w),
                key=lambda w: w["id"],
            )
        return out

    def werkzeug(self, name: str) -> dict[str, Any]:
        reg = self._reg()
        rt = reg.get_tool(name)
        if rt is None:
            raise ValueError(f"unbekanntes Werkzeug {name!r} (Form: <plugin>.<werkzeug>)")
        d = rt.descriptor
        chat, chat_app = _chat_tor()
        zeile = self._werkzeug_zeile(rt, chat, chat_app)
        felder = felder_aus_schema(d.input_schema)
        scope = zeile["scope"]
        link = _identitaet.oeffnen_link(name) if _identitaet.link_erlaubt(d.meta, scope) and not (d.input_schema or {}).get("required") else None
        ui = (d.meta or {}).get("ui") if d.meta else None
        kurz = (d.meta or {}).get("kurz") if d.meta else None
        aufruf_hub = f'hub__call_tool(tool="{name}", arguments=…)'
        return {
            "ok": True,
            **zeile,
            "beschreibung": (d.description or "").strip(),
            "tags": list(d.tags or []),
            "schema": d.input_schema or {"type": "object", "properties": {}},
            "eingabefelder": felder,
            "beispiel": beispiel_aus_felder(felder),
            "aufruf_hub": aufruf_hub,
            "aufruf_app": zeile["mcp_name"],
            "ui": ui if isinstance(ui, dict) else None,
            "oeffnen": link,
            "kurze_ansicht": _ansicht.sicht_bericht(name, kurz if isinstance(kurz, dict) else None),
            "plugin_beschreibung": (reg.plugins[rt.plugin_name].description or "").strip().splitlines()[0][:240]
            if rt.plugin_name in reg.plugins and reg.plugins[rt.plugin_name].description
            else "",
        }

    def ausprobieren(self, werkzeug: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        reg = self._reg()
        rt = reg.get_tool(werkzeug)
        if rt is None:
            raise ValueError(f"unbekanntes Werkzeug {werkzeug!r}")
        gut, grund = self._ausprobierbar(rt)
        if not gut:
            return {"ok": False, "error": f"{werkzeug} lässt sich hier nicht ausprobieren: {grund}", "kind": "nicht_erlaubt"}
        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("arguments muss ein Objekt sein")
        t0 = time.monotonic()
        res = _registry.dispatch(reg, werkzeug, dict(arguments or {}))
        dauer = round((time.monotonic() - t0) * 1000)
        if not res.get("ok"):
            return {
                "ok": False,
                "werkzeug": werkzeug,
                "error": entschaerfen(res.get("error") or "Fehler", 600),
                "kind": res.get("kind") or "plugin_error",
                "ms": dauer,
            }
        sauber = schwaerzen(res.get("result"))
        text = json.dumps(sauber, ensure_ascii=False, indent=1, default=str)
        gekuerzt = len(text) > ERGEBNIS_MAX_ZEICHEN
        return {
            "ok": True,
            "werkzeug": werkzeug,
            "ms": dauer,
            "zeichen": len(text),
            "gekuerzt": gekuerzt,
            "text": text[:ERGEBNIS_MAX_ZEICHEN],
        }

    # ── Plugin-Vertrag ────────────────────────────────────────────────────────────────────────

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if method == "uebersicht":
            return self.uebersicht(bool(args.get("frisch")), bool(args.get("voll")), str(args.get("plugin") or ""))
        if method == "werkzeug":
            name = str(args.get("name") or "").strip()
            if not name:
                raise ValueError("werkzeug: `name` ist erforderlich (<plugin>.<werkzeug>)")
            return self.werkzeug(name)
        if method == "ausprobieren":
            name = str(args.get("werkzeug") or "").strip()
            if not name:
                raise ValueError("ausprobieren: `werkzeug` ist erforderlich (<plugin>.<werkzeug>)")
            return self.ausprobieren(name, args.get("arguments"))
        if method == "zeitplan":
            return _zeitplan.sammeln(self._reg(), str(args.get("quelle") or ""))
        raise ValueError(f"mcp hat kein Werkzeug {method!r}")

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_MCP,
                name="MCP",
                description="Plugins, Werkzeuge, Apps und Protokolle des Hubs — ein Werkzeugkasten im Stil des MCP Inspectors",
                read=lambda: oberflaeche("mcp.html"),
                meta={"ui": {"prefersBorder": True}},
            )
        ]

    def describe_tools(self) -> list[ToolDescriptor]:
        meta = {"ui": {"resourceUri": UI_MCP}, "app": identitaet("mcp")}
        return [
            ToolDescriptor(
                name="uebersicht",
                title="MCP",
                description=(
                    "(App) Der Werkzeugkasten des Hubs, lesend. Knapp (Standard, für Modelle): `satz`, Zähler, alle Plugins mit "
                    "Gesundheit in einer Zeile, Zugänge und Protokollversionen; mit `plugin` zusätzlich dessen Werkzeuge. Mit "
                    "`voll: true` (die Oberfläche nutzt das): alle Werkzeuge mit Scope, Sichtbarkeit und App, ui://-Ressourcen "
                    "und die Aufrufer, die zuletzt kamen (rund 160 KB). Zeigt keine Geheimnisse. Werkzeug suchen: hub__search_tools."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "voll": {
                            "type": "boolean",
                            "description": "Alles inklusive Werkzeugkatalog (gross; die Oberfläche nutzt das). Ohne: knappe Ansicht",
                            "default": False,
                        },
                        "plugin": {
                            "type": "string",
                            "description": "Nur knapp: zusätzlich die Werkzeuge dieses Plugins auflisten (z. B. shell)",
                        },
                        "frisch": {
                            "type": "boolean",
                            "description": "Gesundheit neu prüfen statt der Prüfung der letzten 20 Sekunden",
                            "default": False,
                        }
                    },
                    "additionalProperties": False,
                },
                tags=_TAGS,
                meta=meta,
            ),
            ToolDescriptor(
                name="werkzeug",
                title="MCP — Werkzeug",
                description=(
                    "(App) Ein Hub-Werkzeug im Detail: Beschreibung, Eingabeschema als lesbare Felder, Beispielaufruf, "
                    "Scope, Sichtbarkeit und die zugehörige App mit Link."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "Werkzeug-Kennung, z. B. werkstatt.suchen"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                tags=_TAGS,
                meta=meta,
            ),
            ToolDescriptor(
                name="ausprobieren",
                title="MCP — Ausprobieren",
                description=(
                    "(App) Ein lesendes, für das Modell sichtbares Flächen-Werkzeug wirklich aufrufen und das Ergebnis "
                    "zeigen (gekürzt, ohne Felder, die nach Geheimnis heißen). Nichts Schreibendes, keine privaten Inhalte."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "werkzeug": {"type": "string", "description": "Werkzeug-Kennung, z. B. lage.ampel"},
                        "arguments": {"type": "object", "description": "Argumente des Werkzeugs", "default": {}},
                    },
                    "required": ["werkzeug"],
                    "additionalProperties": False,
                },
                tags=_TAGS,
                meta=meta,
            ),
            ToolDescriptor(
                name="zeitplan",
                title="Zeitplan",
                description=(
                    "Was wann läuft: die Takte der Hub-Plugins und, über die OpenClaw-Brücke, die Cron-Aufträge des "
                    "Agenten — je Aufgabe Takt, nächster und letzter Lauf und ob er gelang. Takte mit Grenzen zeigen "
                    "zusätzlich `fenster` (Uhrzeiten), `max_pro_tag`, `laeufe_heute`, `uebersprungen` (heute, nach Grund "
                    "fenster/limit), `ruht` (läuft jetzt nicht) und `protokoll` (letzte Läufe mit Start, Dauer, Ergebnis). "
                    "`quelle` filtert (z. B. openclaw). Aufgaben mit Modell gehören in den Cron des Agenten, Aufgaben "
                    "ohne Modell in ein Plugin."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"quelle": {"type": "string", "description": "Nur diese Quelle oder dieses Plugin"}},
                    "additionalProperties": False,
                },
                tags=_TAGS,
            ),
        ]
