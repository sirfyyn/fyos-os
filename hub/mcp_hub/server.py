"""mcp_hub.server — MCP-Server des Hubs mit den Meta-Werkzeugen und den REST-Wegen fuer die Shell.

Meta-Werkzeuge (Federated Mode):
    - hub__search_tools(query)    — Werkzeuge nach Name/Beschreibung finden
    - hub__call_tool(tool, args)  — an das richtige Plugin weiterreichen
    - hub__list_servers()         — geladene Plugins mit Werkzeugzahl
    - hub__audit_log()            — semantische Suche ueber fruehere Aufrufe (Plugin ``audit``)

Start:
    python3 -m mcp_hub.server                # liest MCP_HUB_CONFIG_PATH
    MCP_HUB_CONFIG_PATH=./custom.yaml python3 -m mcp_hub.server

Einhaengen:
    HTTP POST http://<host>:<port>/mcp   (streamable-HTTP MCP transport)
REST fuer die Shell: siehe docs/HUB-VERTRAG.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any

try:
    # mcp >= 2.0: `mcp.server.fastmcp` ist weg, die Klasse heisst MCPServer.
    from mcp.server.mcpserver import MCPServer as _HubServer
    from mcp_types import CallToolResult as _CallToolResult
    from mcp_types import Icon as _Icon

    _SDK_V2 = True
except ModuleNotFoundError:
    # mcp 1.x. Der Leitfaden nennt genau diesen Rueckfall ausdruecklich als tragfaehig.
    from mcp.server.fastmcp import FastMCP as _HubServer
    from mcp.types import CallToolResult as _CallToolResult
    from mcp.types import Icon as _Icon

    _SDK_V2 = False

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from . import __version__ as HUB_VERSION
from . import ansicht as _ansicht
from . import hybrid as _hybrid
from . import metriken as _metriken
from . import suchrang as _suchrang
from . import suchspur as _suchspur
from .anmeldung import AnmeldungMiddleware
from .anmeldung import Konfig as AnmeldeKonfig
from .config import DEFAULT_HOST, DEFAULT_PATH, HubConfig, load_config
from .herkunft import HerkunftMiddleware
from .os_bruecke import os_routen
from .plugins import _identitaet
from .plugins.gui import ID_MUSTER, eigenstaendig
from .registry import (
    ART,
    AUFRUFER,
    PluginRegistry,
    build_registry,
    dispatch,
    flaeche_vermerken,
    ist_flaechen_werkzeug,
    map_view,
    plugin_aus,
    plugin_healthy,
    scope_from_tags,
    search_tools,
    tool_schema,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — set by build_app() so meta-tools can reach them.
# FastMCP's @tool decorator binds at import-time, so we keep a global registry
# handle rather than a class-bound one.
# ---------------------------------------------------------------------------

_REGISTRY: PluginRegistry | None = None
_CONFIG: HubConfig | None = None

# So lange wartet uvicorn nach SIGTERM auf offene Antworten, bevor es sie abbricht. Orchestratoren geben einem
# Prozess meist 30 s; bis dahin muessen auch die Plugin-Aufraeumhaken gelaufen sein.
GNADENFRIST_S = 20


def get_registry() -> PluginRegistry:
    if _REGISTRY is None:
        raise RuntimeError("mcp_hub.server: registry not initialized — call build_app() first")
    return _REGISTRY


# ---------------------------------------------------------------------------
# FastMCP instance + 3 Meta-Tools
# ---------------------------------------------------------------------------

# Transport-Parameter. In mcp 1.x gehoeren sie an den Konstruktor, ab 2.0 an
# `streamable_http_app()` — derselbe Satz Werte, nur eine Ebene tiefer.
#
# `host` MUSS mitgereicht werden, auch wenn es wie eine Doppelung aussieht:
# ab 2.0 schaltet `streamable_http_app()` den DNS-Rebinding-Schutz selbsttaetig
# ein, wenn der Host `127.0.0.1`/`localhost`/`::1` ist — und der Vorgabewert der
# Fabrikmethode IST `127.0.0.1`. Ohne diese Zeile liefe der Hub im Cluster in
# `421 Invalid Host header`, waehrend jeder lokale Test gruen bleibt.
_TRANSPORT: dict[str, Any] = {
    "host": os.getenv("MCP_HUB_HOST", DEFAULT_HOST),
    "stateless_http": True,
    "json_response": True,
    "streamable_http_path": "/",
}

mcp = _HubServer(
    name="FYOS MCP-Hub",
    instructions=(
        "FYOS MCP-Hub (Federated Mode). Exposes 9 meta-tools over all "
        "loaded plugins:\n"
        "  hub__search_tools(query, ansicht='kurz', limit, voll) — find tools (all words, else best partial hits), "
        "ranked: the best 10 with a rank value, voll=true for all; kurz = name + one line, ansicht='voll' adds inputSchema.\n"
        "  hub__call_tool(tool, arguments, ansicht='kurz') — dispatch to the right plugin "
        "(tool-id format: '<plugin>.<tool>'). Large results come back shortened with an ergebnis_id.\n"
        "  hub__mehr(ergebnis_id, pfad, felder, filter, suche, limit, cursor) — drill into a shortened result "
        "without calling the tool again; fields you ask for show up in the short view from then on.\n"
        "  hub__ansicht_merken(tool, pfad, felder) — store which fields the short view of a list shows.\n"
        "  hub__map(domain?) — the tool-map: domains → tools with scope + summary, no schemas.\n"
        "  hub__schema(tool) — full inputSchema for ONE tool.\n"
        "  hub__list_servers() — enumerate loaded plugins + tool-counts.\n"
        "  hub__health() — per-plugin health detail (the WHY behind healthy=false).\n"
        "Discovery-first: hub__map -> hub__schema(tool) -> hub__call_tool.\n"
        "  hub__audit_log(query, filter, limit) — semantic-recall over the "
        "audit log of earlier tool calls (plugin `audit`).\n"
        "Always call hub__search_tools first to discover exact tool-ids, then "
        "hub__call_tool with the matching inputSchema.\n"
        "Before a non-trivial task, look up the know-how and the scripts: skills.suchen(q) lists agent skills "
        "(work instructions, read one with skills.lesen), werkstatt.suchen(q) the registered repo scripts "
        "(werkstatt.beschreiben, werkstatt.ausfuehren). Skills name the Werkstatt ids they use.\n"
        "App tools (<plugin>__<name>) answer with the data and end with the line "
        "'In FYOS öffnen: <link>'. If your surface cannot show the app, pass that link on to the user "
        "(it opens the app in FYOS with exactly this state).\n"
        "Show, don't list: when data has many values, offer a view — gui.vorlagen lists templates "
        "(kennzahlen, balken, verlauf, tabelle, vergleich, ablauf, zeitleiste, status), gui.bauen {vorlage, quelle: "
        "{werkzeug: '<read tool>'}} keeps it live (skill generative-ui)."
    ),
    # Spezifikation 2025-11-25: Zeichen und Adresse des Servers (Clients zeigen sie in der Konnektorliste).
    # Die Adresse ist die oeffentliche URL der Installation (FYOS_OEFFENTLICH_URL); ohne sie entfaellt das Feld.
    website_url=_identitaet.OEFFENTLICHE_URL or None,
    icons=[_Icon.model_validate(_identitaet.fyos_zeichen())],
    # v1 nimmt die Transport-Werte hier entgegen, v2 lehnt sie hier ab.
    **({} if _SDK_V2 else _TRANSPORT),
    # v2 meldet sonst `version: ""` in serverInfo und in `server/discover` (v1 hat das Feld am
    # Konstruktor nicht und nimmt die Version des SDK).
    **({"version": HUB_VERSION} if _SDK_V2 else {}),
)


def rangliste(reg: PluginRegistry, query: str) -> tuple[list[dict[str, Any]], bool]:
    """Werkzeuge zur Suche, bestes zuerst, je mit ``wert`` (0..1); zweiter Wert True = nur Teiltreffer (MCP- und REST-Suche).

    Die Rangfolge steht in ``mcp_hub.suchrang`` (Wortwertung + BM25 + Einbetter per RRF);
    ohne Einbetter (``FYOS_EMBED_URL``) bleibt es bei der Wortwertung.
    """
    return _suchrang.rangliste(search_tools(reg, ""), query, _hybrid.HYBRID)


SUCH_LIMIT = 10  # Treffer je Suche mit Suchwort (``voll`` liefert mehr)


def such_grenze(query: str, limit: int | None, voll: bool) -> int:
    """So viele Treffer liefert die Suche: ``limit`` wenn gesetzt; ``voll`` alle (200); sonst 10 mit Suchwort und 25 ohne
    (das Verzeichnis aller Werkzeuge; Agenten-Bruecken laden damit ihre Schemata)."""
    if limit:
        return max(1, min(int(limit), 200))
    if voll:
        return 200
    return SUCH_LIMIT if (query or "").strip() else 25


@mcp.tool()
def hub__search_tools(query: str = "", ansicht: str = "kurz", limit: int = 0, voll: bool = False) -> dict[str, Any]:
    """Search all Hub-plugin tools by name/description; every word should match (else: best partial hits).

    Everyday German words also find their tools (geld → finance, handy, paket → bestellungen, doku → context7 …).
    If no tool matches every word, the tools matching the most words come back with ``teiltreffer: true``.

    Args:
        query: Words to match against tool-id (``<plugin>.<tool>``) or description. Empty = all tools.
        ansicht: ``"kurz"`` (default): name, one line, required arguments, scope — ranked, name hits first.
                 ``"voll"``: additionally full description and inputSchema (large; prefer hub__schema(tool)).
        limit: Maximum tools to return (1-200). Default: the best 10 by rank (25 for an empty query).
        voll: ``true`` = all hits (up to 200) instead of the best 10.

    Returns:
        ``{"ok": True, "count": N, "gezeigt": M, "tools": [...]}``; every tool carries ``wert`` (rank value 0..1,
        best = 1) when the query has words.
    """
    treffer, teil = rangliste(get_registry(), query)
    _suchspur.merke_suche(AUFRUFER.get(), query, [t["name"] for t in treffer])
    limit = such_grenze(query, limit, voll)
    mit_wert = bool((query or "").strip())
    if ansicht == "voll":
        tools = treffer[:limit]
    else:
        tools = [
            {
                "name": t["name"],
                "kurz": _ansicht.einzeiler(t.get("description")),
                "pflicht": list((t.get("inputSchema") or {}).get("required") or []),
                "scope": scope_from_tags(t.get("tags")),
                **({"wert": t["wert"]} if mit_wert and "wert" in t else {}),
            }
            for t in treffer[:limit]
        ]
    antwort: dict[str, Any] = {"ok": True, "count": len(treffer), "gezeigt": len(tools), "tools": tools}
    if teil and treffer:
        antwort["teiltreffer"] = True
        antwort["hinweis"] = "Kein Werkzeug trifft alle Wörter — gezeigt: die mit den meisten Treffern."
    elif len(treffer) > limit:
        antwort["hinweis"] = f"{len(treffer) - limit} weitere — voll: true, limit erhöhen oder Suchwörter schärfen."
    return antwort


def nur_oberflaeche(reg: PluginRegistry, fqtn: str) -> dict[str, Any] | None:
    """Werkzeuge mit `_meta.ui.visibility == ["app"]` ruft nur eine Oberflaeche.

    Ein MCP-Apps-Host versteckt sie vor dem Modell — ueber den allgemeinen Verteiler
    (`hub__call_tool`, REST `/hub/call`) kaeme ein Modell aber trotzdem hin. Schaltende Werkzeuge
    soll der Mensch ueber die Oberflaeche bedienen, nicht ein Modell. Oberflaechen rufen weiter ueber
    `/hub/app-call` bzw. das App-Werkzeug `<plugin>__<name>`.
    """
    rt = reg.get_tool(fqtn)
    ui = ((rt.descriptor.meta or {}).get("ui") or {}) if rt is not None else {}
    if ui.get("visibility") == ["app"]:
        return {
            "ok": False,
            "error": f"{fqtn} ist nur über die Oberfläche bedienbar (der Mensch schaltet selbst), "
            "nicht über den allgemeinen Aufruf.",
            "kind": "nur_oberflaeche",
        }
    return None


def plugin_sicht(reg: PluginRegistry, fqtn: str) -> dict[str, list[str]] | None:
    """Sicht, die ein Plugin für die kurze Ansicht mitliefert: `meta["kurz"] = {"<pfad>": [felder]}`."""
    rt = reg.get_tool(fqtn)
    k = (rt.descriptor.meta or {}).get("kurz") if rt is not None else None
    return k if isinstance(k, dict) else None


def kurz_fuer_modell(reg: PluginRegistry, fqtn: str, args: Any, out: Any) -> tuple[Any, dict[str, Any] | None]:
    """Ergebnis im Budget des Aufrufers (ansicht.py); volles Ergebnis bleibt unter `ergebnis_id` abrufbar."""
    return _ansicht.kurz(
        fqtn,
        args if isinstance(args, dict) else {},
        out,
        budget=_ansicht.budget_fuer(AUFRUFER.get()),
        plugin_sicht=plugin_sicht(reg, fqtn),
        aufrufer=AUFRUFER.get() or "unbekannt",
    )


@mcp.tool()
def hub__call_tool(tool: str, arguments: dict[str, Any] | None = None, ansicht: str = "kurz") -> dict[str, Any]:
    """Dispatch a tool-call to the correct Hub-plugin.

    Args:
        tool: Fully-qualified tool-id ``"<plugin>.<tool>"`` — e.g. ``"echo.say"``.
        arguments: Arguments dict matching the tool's inputSchema.
        ansicht: ``"kurz"`` (default): results above the caller's budget come back shortened — lists show
                 their first entries with key fields, plus count and available fields — together with an
                 ``ergebnis_id`` for hub__mehr. ``"voll"``: the complete result.

    Returns:
        ``{"ok": True, "result": <plugin-return>}`` on success (shortened: also ``"ansicht": {...}``), or
        ``{"ok": False, "error": "...", "kind": "not_found|plugin_error"}``.
        Reads of an app tool (with a ``ui://`` surface) also carry
        ``"_meta": {"fyos/oeffnen": "<link>"}`` — the link that opens the app in FYOS.
    """
    out = _hub_call(tool, arguments)
    if ansicht != "voll" and isinstance(out, dict) and out.get("ok") and "result" in out:
        gekuerzt, info = kurz_fuer_modell(get_registry(), tool, arguments, out["result"])
        if info:
            out = {**out, "result": gekuerzt, "ansicht": info}
    return out


@mcp.tool()
def hub__mehr(
    ergebnis_id: str,
    pfad: str = "",
    felder: list[str] | None = None,
    filter: dict[str, Any] | None = None,
    suche: str = "",
    limit: int = 20,
    cursor: int = 0,
) -> dict[str, Any]:
    """Drill into a shortened result (``ansicht.ergebnis_id`` of hub__call_tool or an app tool) — no new call.

    Args:
        ergebnis_id: The id from the shortened result (valid 15 min).
        pfad: Where to look, dotted: ``"pods"``, ``"deployments.3.containers"``. Empty = the whole result.
        felder: Only these fields of each list entry (or of the object). Asked-for fields join the short view.
        filter: Keep list entries whose fields match: ``{"status": "Failed"}``; strings match as substring.
        suche: Keep list entries containing this text anywhere.
        limit: Entries per page (1-200).
        cursor: Start index; the answer's ``weiter`` is the next cursor (None = end).
    """
    eintrag = _ansicht.abgelegt(ergebnis_id)
    if eintrag is None:
        return {"ok": False, "kind": "abgelaufen",
                "error": "ergebnis_id unbekannt oder abgelaufen (15 min) — Werkzeug erneut rufen."}
    r = _ansicht.mehr(
        eintrag, pfad=pfad, felder=felder, filter_=filter, suche=suche, limit=limit, cursor=cursor,
        budget=_ansicht.budget_fuer(AUFRUFER.get()),
    )
    _ansicht.messen(AUFRUFER.get(), nachgeholt=_ansicht._laenge(r))  # noqa: SLF001 — dieselbe Zählweise wie kurz()
    return r


@mcp.tool()
def hub__ansicht_merken(tool: str, felder: list[str], pfad: str = "") -> dict[str, Any]:
    """Store which fields the short view shows for a list in a tool's result (self-extending view).

    Args:
        tool: ``"<plugin>.<tool>"``.
        felder: Field names to show for each list entry, e.g. ``["name", "namespace", "status", "neustarts"]``.
        pfad: The list's path in the result (``ansicht.listen`` of a shortened result names them; ``""`` = top).
    Unused views expire after 30 days.
    """
    if get_registry().get_tool(tool) is None:
        return {"ok": False, "error": f"unbekanntes Tool {tool!r}", "kind": "not_found"}
    return _ansicht.merken(tool, pfad, felder)


def _hub_call(tool: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    reg = get_registry()
    if not tool or "." not in tool:
        return {
            "ok": False,
            "error": f"tool must be '<plugin>.<tool>', got {tool!r}",
            "kind": "bad_request",
        }
    gesperrt = nur_oberflaeche(reg, tool)
    if gesperrt:
        return gesperrt
    # Ein Agent schickte `args` statt `arguments` — das SDK verwirft den unbekannten Schlüssel, das Plugin
    # bekam {} und meldete „kennt kein Werkzeug ''“. Ohne jedes Argument bei einem Werkzeug mit
    # Pflichtfeldern ist das fast immer der falsche Schlüssel: früh und deutlich sagen.
    rt = reg.get_tool(tool)
    pflicht = list(((rt.descriptor.input_schema or {}).get("required") or [])) if rt is not None else []
    if pflicht and not arguments:
        return {
            "ok": False,
            "error": f"{tool} braucht {pflicht} — als hub__call_tool(tool={tool!r}, arguments={{...}}) "
            "übergeben (der Schlüssel heißt `arguments`).",
            "kind": "bad_arguments",
        }
    return _mit_link(reg, tool, arguments, dispatch(reg, tool, arguments or {}))


@mcp.tool()
def hub__map(domain: str = "", include_health: bool = True) -> dict[str, Any]:
    """Die Tool-Map — Hierarchie domain → tools,
    kompakt OHNE Schemas: pro Tool nur scope (READ/WRITE/DESTRUCTIVE/EXTERN)
    + 1-Zeilen-Summary, pro Domain der Live-Health-Flag.

    Discovery-first-Pfad für Agents (Small-Model-Hebel): hub__map →
    hub__schema(tool) → hub__call_tool. Tote Domains sind sichtbar tot.

    Args:
        domain: Optional eine Domain (Plugin-Name) statt der ganzen Karte.
        include_health: Live-Health pro Domain mitliefern (kostet Probes).
    """
    reg = get_registry()
    return map_view(reg, domain=domain or None, include_health=include_health)


@mcp.tool()
def hub__schema(tool: str) -> dict[str, Any]:
    """Schema EINES Tools — Stufe 2 des 3-Stufen-Calls (map → schema → call).

    Args:
        tool: Fully-qualified tool-id ``"<plugin>.<tool>"``.

    Returns:
        ``{"ok": True, "tool", "scope", "description", "inputSchema"}`` oder
        ``{"ok": False, "kind": "not_found"}``.
    """
    reg = get_registry()
    return tool_schema(reg, tool)


@mcp.tool()
def hub__health() -> dict[str, Any]:
    """Per-plugin health DETAIL — das WARUM hinter healthy=false.

    Runs every plugin's health() probe and returns the raw result per plugin
    (reason/error/server_url/breaker) plus the normalized healthy-flag.
    Gläsernes-System-Regel: der Hub erklärt seinen eigenen Zustand, statt nur
    ein Bool zu zeigen.

    Returns:
        ``{"ok": True, "count": N, "unhealthy": [names], "plugins":
        {name: {"healthy": bool, ...raw health()-dict}}}``.
    """
    return _health_bericht(get_registry())


def _health_bericht(reg: Any) -> dict[str, Any]:
    """Rumpf von `hub__health`; auch fuer REST `GET /hub/health` (hub.py health)."""
    results = reg.health_check_all()
    plugins: dict[str, Any] = {}
    unhealthy: list[str] = []
    unreachable: list[str] = []
    for name, res in results.items():
        flag = plugin_healthy(res)
        # `aus` ist weder gesund noch krank. Ohne diese Trennung zaehlt ein bewusst
        # ruhendes Plugin als Ausfall, die Ampel steht dauerhaft rot, und echte Ausfaelle
        # verschwinden im Rauschen.
        aus = plugin_aus(res)
        # `unreachable` ist ein BEFUND, kein Ausfall-Zustand desselben
        # Typs — das Plugin-Ziel existiert nicht (mehr). Es zaehlt nicht als
        # "unhealthy" (der Hub selbst ist gesund), sondern in die eigene Liste.
        tot = str(res.get("status", "")).lower() == "unreachable"
        plugins[name] = {"healthy": flag, "aus": aus, "unreachable": tot, **res}
        if tot:
            unreachable.append(name)
        # Nur ECHTE Ausfaelle zaehlen. Ein `aus`-Plugin gehoert nicht in die
        # Ausfallliste — sonst steht sie dauerhaft gefuellt und verliert ihre Aussage.
        # unreachable ebensowenig — es hat die eigene Liste oben.
        if not flag and not aus and not tot:
            unhealthy.append(name)
    # Nicht ladbare Plugins sind echte Ausfaelle — sichtbar, statt den Hub abstuerzen zu lassen.
    for name, grund in reg.nicht_geladen.items():
        plugins[name] = {
            "healthy": False,
            "aus": False,
            "unreachable": False,
            "status": "nicht_geladen",
            "reason": grund,
        }
        unhealthy.append(name)
    return {
        "ok": True,
        "count": len(plugins),
        "unhealthy": unhealthy,
        "unreachable": unreachable,
        "nicht_geladen": sorted(reg.nicht_geladen),
        "aus": [n for n, v in plugins.items() if v.get("aus")],
        "plugins": plugins,
    }


@mcp.tool()
def hub__audit_log(
    query: str = "",
    filter: dict[str, Any] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Semantic-recall over historic Hub tool-calls.

    Delegates to the ``audit`` plugin if loaded. Empty query returns the most
    recent events chronologically. Filter is passed through as Qdrant-payload
    match (e.g. ``{"caller": "my-agent", "plugin_name": "echo"}``).

    Args:
        query: Free-text query for semantic search. Empty → chronological tail.
        filter: Optional payload-filter dict.
        limit: Maximum events to return (1-500).

    Returns:
        ``{"ok": True, "count": N, "events": [...]}`` — each event is a compact
        dict (timestamp, caller, tool_name, arguments, result_status, ...).
        ``{"ok": False, "error": "audit plugin not loaded"}`` when the audit
        plugin is absent.
    """
    reg = get_registry()
    plugin = reg.plugins.get("audit")
    if plugin is None:
        return {"ok": False, "error": "audit plugin not loaded", "kind": "not_found"}
    try:
        limit_int = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit_int = 20
    try:
        if query:
            payload = plugin.call("recall", {"query": query, "limit": limit_int, "filter": filter})
        else:
            payload = plugin.call("recent", {"limit": limit_int, "filter": filter})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "kind": "plugin_error"}
    return {"ok": True, **(payload if isinstance(payload, dict) else {"result": payload})}


@mcp.tool()
def hub__list_servers() -> dict[str, Any]:
    """List all loaded Hub-plugins with tool-counts + health status.

    Returns:
        ``{"ok": True, "count": N, "servers": [{name, description, tool_count, healthy, version}]}``.
    """
    reg = get_registry()
    infos = reg.server_infos()
    return {
        "ok": True,
        "count": len(infos),
        "servers": [asdict(info) for info in infos],
    }


# ---------------------------------------------------------------------------
# MCP Apps: Werkzeuge mit Oberflaeche als eigene MCP-Tools
# ---------------------------------------------------------------------------
#
# Hinter `hub__call_tool` sieht ein Host die Plugin-Werkzeuge nicht, also auch nicht
# ihr `_meta.ui.resourceUri` — MCP Apps funktionierten sonst ueber den Hub gar nicht.
# Jedes Werkzeug, dessen ToolDescriptor `meta["ui"]` traegt,
# wird deshalb zusaetzlich als `<plugin>__<name>` angeboten, mit echtem inputSchema,
# `_meta` und Hinweisen (readOnly/destructive aus dem Scope). Der Aufruf laeuft trotzdem
# durch `registry.call` — Audit, Breaker und Event-Bus sehen ihn wie jeden anderen.
# Die `ui://`-Ressourcen der Plugins werden als MCP-Ressourcen registriert.
#
# Spezifikation: MCP Apps 2026-01-26 (io.modelcontextprotocol/ui),
# MIME `text/html;profile=mcp-app`, `_meta.ui.resourceUri`, `_meta.ui.visibility`.

_APP_TOOLS: set[str] = set()
_APP_RESOURCES: set[str] = set()


def _app_tool_name(fqtn: str) -> str:
    return fqtn.replace(".", "__", 1)


def _hinweise(scope: str) -> Any:
    try:
        from mcp.types import ToolAnnotations  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return None
    return ToolAnnotations(
        readOnlyHint=scope == "READ",
        destructiveHint=scope in ("DESTRUCTIVE", "EXEC"),
    )


def oeffnen_link_fuer(
    reg: PluginRegistry, fqtn: str, args: dict[str, Any] | None
) -> str | None:
    """Deeplink „In FYOS öffnen“ (Vertrag 2) für das Ergebnis dieses App-Werkzeugs — oder None.

    Zentral an einer Stelle: MCP-App-Werkzeuge (`_app_fn`), REST `/hub/app-call` und das Chat-Tor
    (über `/hub/app-call`) bekommen denselben Link. Nur für Werkzeuge mit Oberfläche, lesend und
    für das Modell sichtbar (`_identitaet.link_erlaubt`): ein Link darf nie etwas auslösen.
    """
    rt = reg.get_tool(fqtn)
    if rt is None:
        return None
    d = rt.descriptor
    if not _identitaet.link_erlaubt(d.meta, scope_from_tags(d.tags)):
        return None
    # Ein Plugin darf auf ein anderes Werkzeug umlenken (gui.bauen → gui.zeigen {id}); das Ziel muss selbst verlinkbar sein.
    ziel, ziel_args = reg.oeffnen_ziel(fqtn, args)
    if ziel != fqtn:
        zt = reg.get_tool(ziel)
        if zt is None or not _identitaet.link_erlaubt(zt.descriptor.meta, scope_from_tags(zt.descriptor.tags)):
            return None
    return _identitaet.oeffnen_link(ziel, ziel_args)


def _mit_link(reg: PluginRegistry, fqtn: str, args: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis des allgemeinen Verteilers (`hub__call_tool`, `/hub/call`, `/hub/app-call`) um den Link ergänzen.

    Hier gibt es keine „letzte Textzeile“ — das Ergebnis ist ein Wörterbuch; der Link steht unter `_meta`.
    """
    if isinstance(result, dict) and result.get("ok"):
        link = oeffnen_link_fuer(reg, fqtn, args if isinstance(args, dict) else {})
        if link:
            return {**result, "_meta": {"fyos/oeffnen": link}}
    return result


def _ergebnis_mit_link(out: dict[str, Any], link: str | None, text: Any = None) -> Any:
    """Ergebnis eines App-Werkzeugs: Text fürs Modell, `structuredContent` voll für die Oberfläche.

    `text` ist die kurze Ansicht (ansicht.py), sonst das Ergebnis selbst — kompakt, ohne Einrückung: früher
    ging das Ergebnis eingerückt als Text UND als structuredContent, also doppelt und aufgebläht.
    """
    inhalt = [{"type": "text", "text": json.dumps(out if text is None else text, ensure_ascii=False, default=str)}]
    if link:
        inhalt.append({"type": "text", "text": _identitaet.LINK_ZEILE + link})
    return _CallToolResult.model_validate(
        {
            "content": inhalt,
            "structuredContent": out,
            **({"_meta": {"fyos/oeffnen": link}} if link else {}),
        }
    )


def konto_elicitation(fehlt: dict[str, Any], text: str | None = None) -> Exception:
    """`KontoFehlt` (plugin.py) als URL-Elicitation nach MCP 2025-11-25 (Fehler -32042).

    Der Client zeigt dem Menschen den Link; er meldet sich beim Anbieter an, der Token landet im Tresor
    des Plugins und nie beim Modell. Danach ruft der Client das Werkzeug erneut. Kennt das SDK die
    URL-Elicitation nicht, bleibt es ein gewöhnlicher Fehler mit dem Link im Text.
    """
    link = str(fehlt.get("verbinden") or "")
    nachricht = text or f"{fehlt.get('name') or 'Ein Konto'} ist nicht verbunden."
    try:
        from mcp.shared.exceptions import UrlElicitationRequiredError  # noqa: PLC0415
        from mcp.types import ElicitRequestURLParams  # noqa: PLC0415
    except ImportError:  # pragma: no cover — ältere SDK-Fassung
        return RuntimeError(nachricht)
    return UrlElicitationRequiredError(
        [
            ElicitRequestURLParams(
                mode="url",
                message=f"{fehlt.get('name') or 'Konto'} verbinden: einmal beim Anbieter anmelden.",
                url=link,
                elicitationId=f"konto-{fehlt.get('anbieter') or 'unbekannt'}",
            )
        ],
        message=nachricht,
    )


def _app_fn(reg: PluginRegistry, fqtn: str, schema: dict[str, Any]):
    import inspect  # noqa: PLC0415

    def fn(**kwargs: Any) -> Any:
        args = {k: v for k, v in kwargs.items() if v is not None}
        res = dispatch(reg, fqtn, args)
        if not res.get("ok") and res.get("kind") == "konto_fehlt":
            raise konto_elicitation(res.get("result") or {}, res.get("error"))
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"{fqtn} fehlgeschlagen")
        out = res.get("result")
        out = out if isinstance(out, dict) else {"result": out}
        link = oeffnen_link_fuer(reg, fqtn, args)
        gekuerzt, info = kurz_fuer_modell(reg, fqtn, args, out)
        if info is None:
            return _ergebnis_mit_link(out, link) if link else out
        return _ergebnis_mit_link(out, link, {**gekuerzt, "_ansicht": info} if isinstance(gekuerzt, dict) else
                                  {"result": gekuerzt, "_ansicht": info})

    required = set(schema.get("required") or [])
    params = [
        inspect.Parameter(
            k,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=Any,
            default=inspect.Parameter.empty if k in required else None,
        )
        for k in (schema.get("properties") or {})
    ]
    fn.__signature__ = inspect.Signature(params, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    fn.__name__ = _app_tool_name(fqtn)
    return fn


def _apps_anbinden(reg: PluginRegistry) -> None:
    """Werkzeuge mit `meta["ui"]` und alle Plugin-Ressourcen am MCP-Server anmelden.

    Wiederholbar: build_app() laeuft in Tests mehrfach gegen dieselbe Server-Instanz.
    """
    import importlib  # noqa: PLC0415

    tools = mcp._tool_manager._tools  # noqa: SLF001 — beide SDK-Linien: dict
    for name in _APP_TOOLS:
        tools.pop(name, None)
    _APP_TOOLS.clear()
    resources = mcp._resource_manager._resources  # noqa: SLF001
    for uri in _APP_RESOURCES:
        resources.pop(uri, None)
    _APP_RESOURCES.clear()

    # Identität je Oberfläche (Vertrag 1): die Ressource gehört zu den Werkzeugen, die auf sie zeigen.
    identitaeten: dict[str, dict[str, Any]] = {}
    for fqtn, rt in reg.tools.items():
        desc = rt.descriptor
        if not (desc.meta and "ui" in desc.meta):
            continue
        app = desc.meta.get("app") if isinstance(desc.meta.get("app"), dict) else None
        uri = (desc.meta.get("ui") or {}).get("resourceUri")
        if app and uri:
            identitaeten.setdefault(uri, app)
        schema = desc.input_schema or {"type": "object", "properties": {}}
        name = _app_tool_name(fqtn)
        icon = _identitaet.icon_fuer(app)
        mcp.add_tool(
            _app_fn(reg, fqtn, schema),
            name=name,
            title=desc.title or (app or {}).get("titel"),
            description=desc.description,
            annotations=_hinweise(scope_from_tags(desc.tags)),
            icons=[_Icon.model_validate(icon)] if icon else None,
            meta=desc.meta,
            structured_output=True,
        )
        mcp._tool_manager.get_tool(name).parameters = schema  # noqa: SLF001
        _APP_TOOLS.add(name)

    base = "mcp.server.mcpserver" if _SDK_V2 else "mcp.server.fastmcp"
    function_resource = importlib.import_module(base + ".resources").FunctionResource
    for uri, (_plugin, res) in reg.resources.items():
        app = identitaeten.get(uri)
        icon = _identitaet.icon_fuer(app)
        mcp.add_resource(
            function_resource(
                uri=uri,
                name=res.name,
                # Titel und Untertitel der App (Vertrag 1); ohne Identität bleibt es bei Name und Beschreibung.
                title=(app or {}).get("titel") or res.name,
                description=(app or {}).get("untertitel") or res.description or None,
                mime_type=res.mime_type,
                fn=res.read,
                icons=[_Icon.model_validate(icon)] if icon else None,
                meta=res.meta,
            )
        )
        _APP_RESOURCES.add(uri)
    if _APP_TOOLS or _APP_RESOURCES:
        logger.info(
            "mcp_hub.server: MCP Apps — %d Werkzeuge, %d Ressourcen",
            len(_APP_TOOLS),
            len(_APP_RESOURCES),
        )


# ---------------------------------------------------------------------------
# Starlette application — health probe + MCP mount
# ---------------------------------------------------------------------------


async def health(request: Request) -> JSONResponse:
    """k8s liveness/readiness — reports plugin-count + tool-count."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    return JSONResponse(
        {
            "ok": True,
            "plugins": len(_REGISTRY.plugins),
            "tools": len(_REGISTRY.tools),
            # Wirksamer Modus der Anmeldung von aussen (aus/probe/an), siehe anmeldung.py
            "oauth": AnmeldeKonfig.aus_umgebung().wirksam,
        }
    )


async def metriken(request: Request) -> Response:
    """Prometheus-Text: Kernzähler, ``HubPlugin.metrics()`` und Zeitplan (``mcp_hub.metriken``)."""
    if _REGISTRY is None:
        return Response("# Hub startet noch\n", status_code=503, media_type="text/plain")
    text = await asyncio.to_thread(_metriken.text, _REGISTRY)
    return Response(text, media_type="text/plain; version=0.0.4; charset=utf-8")


# ── Plain-REST-Bridge: server-to-server ohne MCP-Handshake.
# Agenten-Bruecken und Skripte rufen diese Routen statt den streamable-http-MCP-Stack.
async def dispatch_im_thread(
    reg: PluginRegistry, fqtn: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """`dispatch` in einem Arbeitsthread (OS-Bruecke).

    Werkzeuge duerfen warten: `os.ausfuehren` wartet bis 15 s auf den Browser. Liefe das auf der
    Ereignisschleife, koennte dieselbe Instanz die Antwort des Browsers (`POST /hub/os/antwort`)
    nicht annehmen, und jedes lange Werkzeug (CI-Umzug, 4 min) legte die ganze Instanz lahm.
    Der MCP-Weg laeuft ohnehin in Arbeitsthreads; der Kontext (AUFRUFER) wandert mit.
    """
    return await asyncio.to_thread(dispatch, reg, fqtn, arguments)


async def rest_search(request: Request) -> JSONResponse:
    """GET /hub/search?query= — Hub-Tools auflisten (wie hub__search_tools)."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    query = request.query_params.get("query", "")
    # Dieselbe Rangfolge wie hub__search_tools (Wörter, Synonyme, Teiltreffer) statt eines
    # Teilstrings über die ganze Anfrage.
    # Im Arbeitsthread: die Hybrid-Stufe fragt den Einbetter (bis HUB_SUCHE_EMBED_TIMEOUT_S).
    tools, teil = await asyncio.to_thread(rangliste, _REGISTRY, query)
    await asyncio.to_thread(_suchspur.merke_suche, AUFRUFER.get(), query, [t["name"] for t in tools])
    # Mit Suchwort hoechstens 10 nach Rang (`limit=` oder `voll=1` fuer mehr); ohne Suchwort bleibt es
    # das ganze Verzeichnis (Agenten-Bruecken laden damit ihre Schemata).
    gesamt = len(tools)
    if query.strip():
        try:
            limit = int(request.query_params.get("limit") or 0)
        except ValueError:
            limit = 0
        voll = request.query_params.get("voll", "").lower() in ("1", "true", "ja")
        tools = tools[: such_grenze(query, limit, voll)]
    antwort: dict[str, Any] = {"ok": True, "count": gesamt, "gezeigt": len(tools), "tools": tools}
    if teil:
        antwort["teiltreffer"] = True
    if len(tools) < gesamt:
        antwort["hinweis"] = f"{gesamt - len(tools)} weitere — voll=1 oder limit=N."
    return JSONResponse(antwort)


async def rest_map(request: Request) -> JSONResponse:
    """GET /hub/map?domain= — strukturierte Tool-Karte (wie hub__map).

    Der discovery-first-Einstieg map→schema→call fuer REST-Clients.
    """
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    domain = request.query_params.get("domain", "")
    return JSONResponse(map_view(_REGISTRY, domain=domain or None, include_health=False))


async def rest_health(request: Request) -> JSONResponse:
    """GET /hub/health?plugin= — Gesundheit je Plugin samt Grund (wie hub__health); nur lesen."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    bericht = await asyncio.to_thread(_health_bericht, _REGISTRY)
    name = request.query_params.get("plugin", "")
    if name:
        if name not in bericht["plugins"]:
            return JSONResponse(
                status_code=404, content={"ok": False, "kind": "not_found", "error": f"Plugin {name!r} unbekannt"}
            )
        return JSONResponse({"ok": True, "plugin": name, **bericht["plugins"][name]})
    return JSONResponse(bericht)


async def rest_servers(request: Request) -> JSONResponse:
    """GET /hub/servers — geladene Plugins mit Werkzeugzahl und Gesundheit (wie hub__list_servers)."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    infos = await asyncio.to_thread(_REGISTRY.server_infos)
    return JSONResponse({"ok": True, "count": len(infos), "servers": [asdict(i) for i in infos]})


# Fehlerart (`kind` aus registry.call) → HTTP-Status. Sonst wäre jeder Fehler ein 502, auch ein
# falsches Argument; wer den Status liest (Monitoring, Wiederholungslogik), hielt es fuer einen Ausfall.
#   Eingabefehler -> 400, verboten -> 403, unbekannt -> 404, Zeitueberschreitung -> 504, Breaker offen -> 503,
#   alles andere (Plugin geworfen, Werkzeug meldet ok=false, Konto fehlt) -> 502.
_STATUS_NACH_ART: dict[str, int] = {
    "bad_arguments": 400,
    "bad_request": 400,
    "forbidden": 403,
    "verboten": 403,
    "nur_oberflaeche": 403,
    "not_an_app": 403,
    "not_found": 404,
    "circuit_open": 503,
    "timeout": 504,
}


def status_fuer(result: Any) -> int:
    """HTTP-Status zu einem Ergebnis von `dispatch` / `_hub_call`."""
    if isinstance(result, dict) and result.get("ok"):
        return 200
    art = result.get("kind") if isinstance(result, dict) else None
    return _STATUS_NACH_ART.get(str(art), 502)


def _anfrage_fehler(meldung: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"ok": False, "error": meldung, "kind": "bad_request"})


async def _body_objekt(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """Anfragekoerper als JSON-Objekt lesen — sonst 400 mit klarer Meldung (statt 500 bei `[1]`, `5`, `"x"`)."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — kaputtes JSON, falsche Kodierung, abgebrochener Koerper
        return None, _anfrage_fehler("invalid json")
    if not isinstance(body, dict):
        art = type(body).__name__ if body is not None else "null"
        return None, _anfrage_fehler(f"Der Anfragekörper muss ein JSON-Objekt sein, nicht {art}.")
    return body, None


def _argumente_aus(body: dict[str, Any]) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """`arguments` des Koerpers: fehlt/leer -> {}, sonst muss es ein Objekt sein (400 sonst)."""
    roh = body.get("arguments")
    if roh is None or roh == {}:
        return {}, None
    if not isinstance(roh, dict):
        return None, _anfrage_fehler(f"`arguments` muss ein JSON-Objekt sein, nicht {type(roh).__name__}.")
    return roh, None


async def rest_call(request: Request) -> JSONResponse:
    """POST /hub/call {tool: '<plugin>.<tool>', arguments: {...}} — dispatchen."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    body, fehler = await _body_objekt(request)
    if fehler is not None:
        return fehler
    tool = body.get("tool", "")
    if not isinstance(tool, str):
        return _anfrage_fehler(f"`tool` muss ein Text sein, nicht {type(tool).__name__}.")
    if not tool or "." not in tool:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": f"tool must be '<plugin>.<tool>', got {tool!r}",
                "kind": "bad_request",
            },
        )
    gesperrt = nur_oberflaeche(_REGISTRY, tool)
    if gesperrt:
        return JSONResponse(status_code=403, content=gesperrt)
    argumente, fehler = _argumente_aus(body)
    if fehler is not None:
        return fehler
    result = _mit_link(_REGISTRY, tool, argumente, await dispatch_im_thread(_REGISTRY, tool, argumente))
    # Modelle über REST bitten um `ansicht: "kurz"`; Oberflächen bekommen weiter alles.
    if body.get("ansicht") == "kurz" and result.get("ok") and "result" in result:
        gekuerzt, info = kurz_fuer_modell(_REGISTRY, tool, argumente, result["result"])
        if info:
            result = {**result, "result": gekuerzt, "ansicht": info}
    return JSONResponse(status_code=status_fuer(result), content=result)


async def rest_mehr(request: Request) -> JSONResponse:
    """POST /hub/mehr {ergebnis_id, pfad?, felder?, filter?, suche?, limit?, cursor?} — wie hub__mehr."""
    body, fehler = await _body_objekt(request)
    if fehler is not None:
        return fehler
    erlaubt = {"pfad", "felder", "filter", "suche", "limit", "cursor"}
    try:
        res = hub__mehr(str(body.get("ergebnis_id") or ""), **{k: v for k, v in body.items() if k in erlaubt})
    except (TypeError, ValueError) as exc:  # falscher Typ eines Feldes (limit: "x", felder: 5)
        return _anfrage_fehler(f"ungültige Angabe: {exc}")
    return JSONResponse(status_code=200 if res.get("ok") else 404, content=res)


def _flaechen_werkzeug(rt: Any) -> bool:
    """Darf der Browser (fyos-web /hub-api, WebMCP) dieses Werkzeug rufen? Regel: `registry.ist_flaechen_werkzeug`."""
    return ist_flaechen_werkzeug(rt.descriptor)


def _mit_etag(request: Request, inhalt: dict[str, Any]) -> Response:
    """Lesende Antwort mit ETag (Hash des Inhalts) und `Cache-Control: private, no-cache`.

    `no-cache` heisst nicht „nicht speichern“, sondern „vor jeder Nutzung nachfragen“: der Browser schickt
    `If-None-Match` von selbst, bei gleichem Inhalt kommt ein leeres 304 statt der Liste (alle Apps mit Schemas)
    bzw. der HTML-Oberflaeche. `private`: nichts fuer Zwischenspeicher (Reverse-Proxys). Das Antwortformat bleibt.
    """
    koerper = json.dumps(inhalt, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    etag = '"' + hashlib.sha256(koerper).hexdigest()[:32] + '"'
    kopf = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if _etag_passt(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=kopf)
    return Response(content=koerper, media_type="application/json", headers=kopf)


def _etag_passt(wunsch: str | None, etag: str) -> bool:
    """`If-None-Match` (Liste, `*`, schwache Form `W/"…"`) gegen den aktuellen ETag."""
    if not wunsch:
        return False
    if wunsch.strip() == "*":
        return True
    return any(t.strip().removeprefix("W/") == etag for t in wunsch.split(","))


async def rest_apps(request: Request) -> Response:
    """GET /hub/apps — Flaechen-Werkzeuge (mit Oberflaeche oder Tag `flaeche`) fuer fyos-web."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    apps = [
        {
            "tool": fqtn,
            "name": _app_tool_name(fqtn),
            "title": rt.descriptor.title,
            "description": rt.descriptor.description,
            "inputSchema": rt.descriptor.input_schema,
            "_meta": rt.descriptor.meta,
            "scope": scope_from_tags(rt.descriptor.tags),
            "hatUi": bool(rt.descriptor.meta and "ui" in rt.descriptor.meta),
            **_identitaet_felder(rt.descriptor.meta),
        }
        for fqtn, rt in _REGISTRY.tools.items()
        if _flaechen_werkzeug(rt)
    ]
    return _mit_etag(request, {"ok": True, "count": len(apps), "apps": apps})


def _identitaet_felder(meta: dict[str, Any] | None) -> dict[str, Any]:
    """`titel, untertitel, symbol, ton, kategorie, icon` aus `meta["app"]` (Vertrag 1) — leer ohne Identität."""
    app = (meta or {}).get("app")
    if not isinstance(app, dict):
        return {}
    felder = {k: app[k] for k in ("titel", "untertitel", "symbol", "ton", "kategorie") if k in app}
    icon = _identitaet.icon_fuer(app)
    if icon:
        felder["icon"] = icon
    return felder


async def rest_resource(request: Request) -> JSONResponse:
    """GET /hub/resource?uri=ui://… — Inhalt einer Plugin-Ressource."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    uri = request.query_params.get("uri", "")
    eintrag = _REGISTRY.resources.get(uri)
    if eintrag is None:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": f"unknown resource {uri!r}"}
        )
    _plugin, res = eintrag
    return _mit_etag(
        request, {"ok": True, "uri": uri, "mimeType": res.mime_type, "text": res.read(), "_meta": res.meta}
    )


def _gui_seite_fehler(meldung: str) -> Response:
    """Kleine Fehlerseite für `GET /hub/gui/{id}`: der Text wird maskiert, nichts aus der Anfrage kommt ungeprüft hinein."""
    import html as _html  # noqa: PLC0415

    seite = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>Ansicht</title><p style="font:14px system-ui">{_html.escape(meldung)}</p>'
    )
    return Response(seite, status_code=404, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


async def rest_gui_seite(request: Request) -> Response:
    """GET /hub/gui/{id} — eine gebaute Ansicht (`gui.bauen`) als ganze, eigenständige Seite.

    Für Flächen ohne MCP-Apps-Host: ein Browser, das Panel einer Entwicklungsumgebung (Mod fyos-ansicht). Eine
    Live-Quelle bringt beim Laden frische Daten mit und lädt danach über `/hub/gui/{id}/daten` nach. Nur lesend;
    die Id muss das Muster `g-` plus 12 Hex-Zeichen haben (alles andere ist 404, bevor ein Plugin gefragt wird).
    """
    if _REGISTRY is None:
        return Response("Hub startet noch.", status_code=503, media_type="text/plain; charset=utf-8")
    i = str(request.path_params.get("id", ""))
    if not ID_MUSTER.fullmatch(i):
        return _gui_seite_fehler("Ansicht nicht gefunden")
    result = await dispatch_im_thread(_REGISTRY, "gui.zeigen", {"id": i})
    erg = result.get("result") if isinstance(result, dict) and result.get("ok") else None
    if not isinstance(erg, dict) or not isinstance(erg.get("dokument"), dict):
        return _gui_seite_fehler(str((result.get("error") if isinstance(result, dict) else None) or "Ansicht nicht gefunden"))
    link = _identitaet.oeffnen_link("gui.zeigen", {"id": i})
    seite = eigenstaendig(erg["dokument"], link, ergebnis=erg, daten_url=f"/hub/gui/{i}/daten")
    return Response(seite, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


async def rest_gui_daten(request: Request) -> JSONResponse:
    """GET /hub/gui/{id}/daten — frische Daten der Live-Quelle (`gui.zeigen {id, nur_daten}`) für die Seite oben."""
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    i = str(request.path_params.get("id", ""))
    if not ID_MUSTER.fullmatch(i):
        return JSONResponse(
            status_code=404, content={"ok": False, "kind": "not_found", "error": "Ansicht nicht gefunden"},
            headers={"Cache-Control": "no-store"},
        )
    result = await dispatch_im_thread(_REGISTRY, "gui.zeigen", {"id": i, "nur_daten": True})
    return JSONResponse(status_code=status_fuer(result), content=result, headers={"Cache-Control": "no-store"})


async def rest_app_call(request: Request) -> JSONResponse:
    """POST /hub/app-call {name: "<plugin>__<tool>" | tool: "<plugin>.<tool>", arguments}

    Nur fuer Flaechen-Werkzeuge (Oberflaeche oder Tag `flaeche`). fyos-web reicht genau diese Route
    (plus /hub/apps und /hub/resource) an den Browser durch — nicht /hub/call, hinter dem
    alle Werkzeuge liegen, auch die mit Seiteneffekten.
    """
    if _REGISTRY is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "not_initialized"})
    body, fehler = await _body_objekt(request)
    if fehler is not None:
        return fehler
    fqtn = body.get("tool") or body.get("name") or ""
    if not isinstance(fqtn, str):
        return _anfrage_fehler(f"`tool`/`name` muss ein Text sein, nicht {type(fqtn).__name__}.")
    fqtn = fqtn if body.get("tool") else fqtn.replace("__", ".", 1)
    rt = _REGISTRY.tools.get(fqtn)
    if rt is None or not _flaechen_werkzeug(rt):
        return JSONResponse(
            status_code=403,
            content={
                "ok": False,
                "error": f"{fqtn!r} ist kein Flaechen-Werkzeug",
                "kind": "not_an_app",
            },
        )
    argumente, fehler = _argumente_aus(body)
    if fehler is not None:
        return fehler
    # Vertrag 2: jedes Ergebnis eines App-Werkzeugs (lesend, sichtbar) trägt den Link „In FYOS öffnen“.
    result = _mit_link(_REGISTRY, fqtn, argumente, await dispatch_im_thread(_REGISTRY, fqtn, argumente))
    return JSONResponse(status_code=status_fuer(result), content=result)


# ── Aufrufer ────────────────────────────────────────────────────────────────
# Der Hub weiss, ueber welchen Weg ein Aufruf kommt: /hub/app-call ist fyos-web (Browser, WebMCP, Apps),
# /hub/call die REST-Schiene (Skripte, Agenten-Bruecken), alles unter dem MCP-Mount ein MCP-Client. Eine
# ausdrueckliche Kopfzeile `X-Hub-Caller` (Agent, Chat-Tor) gewinnt.
_UA_PRODUKT = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")


def aufrufer_aus(pfad: str, kopf: dict[str, str]) -> str:
    """Aufrufer-Name aus Pfad und Kopfzeilen (kleingeschriebene Schluessel)."""
    ausdruecklich = (kopf.get("x-hub-caller") or "").strip()
    if ausdruecklich:
        return ausdruecklich[:60]
    if pfad.startswith(("/hub/app-call", "/hub/apps", "/hub/resource")):
        return "fyos-web"
    treffer = _UA_PRODUKT.match((kopf.get("user-agent") or "").strip())
    produkt = treffer.group(0)[:40] if treffer else "unbekannt"
    if pfad.startswith("/hub/"):
        return f"rest:{produkt}"
    return f"mcp:{produkt}"


class AufruferMiddleware:
    """Reine ASGI-Middleware: setzt AUFRUFER fuer die Dauer der Anfrage.

    ContextVars wandern mit: anyio-Tasks und `to_thread.run_sync` kopieren den Kontext
    der Anfrage, auch im zustandslosen MCP-Transport.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        kopf = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []
        }
        pfad = str(scope.get("path") or "")
        wer = aufrufer_aus(pfad, kopf)
        if pfad != "/health":
            flaeche_vermerken(
                wer,
                "os" if pfad.startswith(("/hub/app-call", "/hub/apps", "/hub/resource")) else (
                    "rest" if pfad.startswith("/hub/") else "mcp"
                ),
                kopf.get("mcp-protocol-version"),
            )
        marke = AUFRUFER.set(wer)
        art_marke = ART.set((kopf.get("x-hub-art") or "").strip().lower()[:20])
        try:
            await self.app(scope, receive, send)
        finally:
            ART.reset(art_marke)
            AUFRUFER.reset(marke)


class EndpunktOhneSchraegstrich:
    """`POST /mcp` genauso beantworten wie `POST /mcp/`.

    Starlette haengt einen `Mount` auf `/mcp/` und antwortet auf `/mcp` mit `307 → /mcp/`. Hinter einem Reverse-Proxy
    lautet das Ziel `http://…/mcp/` (Schema und Port gehen verloren). Ein Client, der Weiterleitungen bei POST nicht
    verfolgt oder von https auf http nicht folgt, kommt dann nie an. Die Spezifikation verlangt EINEN Endpunkt
    (transports/streamable-http: „single HTTP endpoint path“), also gilt der Pfad mit und ohne Schraegstrich.
    """

    def __init__(self, app: Any, pfad: str) -> None:
        self.app = app
        self.pfad = "/" + pfad.strip("/")

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path") == self.pfad:
            scope = {**scope, "path": self.pfad + "/", "raw_path": (self.pfad + "/").encode("latin-1")}
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    logger.info(
        "mcp-hub started — port=%s path=%s plugins=%d tools=%d",
        _CONFIG.port if _CONFIG else "?",
        _CONFIG.path if _CONFIG else "?",
        len(_REGISTRY.plugins) if _REGISTRY else 0,
        len(_REGISTRY.tools) if _REGISTRY else 0,
    )
    async with mcp.session_manager.run():
        yield


def _plugin_routen(registry: Any, belegt: set[str]) -> list[Any]:
    """Eigene Wege aus Plugins (``HubPlugin.routen()``): nur unter /hub/, nie ueber einen schon belegten Weg.

    Unter /hub/ greifen Herkunfts- und Anmeldeschutz wie fuer die Wege des Kerns. Ein Plugin, dessen
    ``routen()`` scheitert, verliert nur seine Wege.
    """
    raus: list[Any] = []
    for plugin in registry.plugins.values():
        holen = getattr(plugin, "routen", None)
        if not callable(holen):
            continue
        try:
            routen = list(holen() or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.server: routen(%s) failed: %s", getattr(plugin, "name", "?"), exc)
            continue
        for route in routen:
            pfad = getattr(route, "path", "")
            if not isinstance(pfad, str) or not pfad.startswith("/hub/") or pfad in belegt:
                logger.warning("mcp_hub.server: Weg %r von %s abgelehnt (nur unter /hub/, nicht doppelt)",
                               pfad, getattr(plugin, "name", "?"))
                continue
            belegt.add(pfad)
            raus.append(route)
    return raus


def build_app(config_path: str | None = None) -> Starlette:
    """Load config, build registry, mount MCP under config.path, return ASGI app."""
    global _REGISTRY, _CONFIG
    _CONFIG = load_config(config_path)
    _REGISTRY = build_registry(_CONFIG)
    # Katalog-Vektoren fuer die Hybrid-Suche im Hintergrund holen (bis sie da sind: Wortwertung).
    _hybrid.HYBRID.vorwaermen(search_tools(_REGISTRY, ""))
    # Audit-Plugin als on_call-Listener der Registry anhaengen (falls geladen).
    audit_plugin = _REGISTRY.plugins.get("audit")
    if audit_plugin is not None and hasattr(audit_plugin, "register_as_listener"):
        try:
            audit_plugin.register_as_listener(_REGISTRY)
            logger.info("mcp_hub.server: audit plugin wired as on_call listener")
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.server: audit listener wiring failed: %s", exc)
    # event_bus_publisher als on_call-Listener anhaengen: jeder Werkzeugaufruf geht als Ereignis auf
    # Redis Streams (bus.tool.*). Fail-safe — der Listener blockiert den Aufruf nie.
    bus_plugin = _REGISTRY.plugins.get("event_bus_publisher")
    if bus_plugin is not None and hasattr(bus_plugin, "register_as_listener"):
        try:
            bus_plugin.register_as_listener(_REGISTRY)
            logger.info("mcp_hub.server: event_bus_publisher wired as on_call listener")
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.server: event_bus_publisher wiring failed: %s", exc)
    # Plugins, die die Hub-Karte selbst lesen (mcp.uebersicht), bekommen die Registry.
    # Der Hub laeuft als `python -m mcp_hub.server` (Modul `__main__`); ein Import von
    # `mcp_hub.server` im Plugin saehe eine zweite, leere Registry.
    for plugin in _REGISTRY.plugins.values():
        anbinden = getattr(plugin, "registry_anbinden", None)
        if callable(anbinden):
            try:
                anbinden(_REGISTRY)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_hub.server: registry_anbinden(%s) failed: %s", plugin.name, exc)
    _apps_anbinden(_REGISTRY)
    mount_path = _CONFIG.path or DEFAULT_PATH
    kern = [
        Route("/health", health),
        # Prometheus: innen offen wie /health, auf einem Außenhost 404 (anmeldung.py)
        Route("/metrics", metriken, methods=["GET"]),
        Route("/hub/search", rest_search, methods=["GET"]),
        Route("/hub/map", rest_map, methods=["GET"]),
        Route("/hub/health", rest_health, methods=["GET"]),
        Route("/hub/servers", rest_servers, methods=["GET"]),
        Route("/hub/call", rest_call, methods=["POST"]),
        Route("/hub/mehr", rest_mehr, methods=["POST"]),
        Route("/hub/apps", rest_apps, methods=["GET"]),
        Route("/hub/resource", rest_resource, methods=["GET"]),
        Route("/hub/app-call", rest_app_call, methods=["POST"]),
        # Gebaute Ansichten (Plugin gui) als eigenstaendige Seite und ihre frischen Daten: nur lesend
        Route("/hub/gui/{id}", rest_gui_seite, methods=["GET"]),
        Route("/hub/gui/{id}/daten", rest_gui_daten, methods=["GET"]),
        # OS-Bruecke: Browser-Kanal, ueber den ein Agent auf das offene OS wirkt (SSE + 2x POST)
        *os_routen(),
    ]
    app = Starlette(
        routes=[
            *kern,
            # Eigene Wege der Plugins (HubPlugin.routen) nach denen des Kerns
            *_plugin_routen(_REGISTRY, {r.path for r in kern}),
            Mount(
                mount_path,
                # v2 will die Transport-Werte hier, v1 hatte sie schon am Konstruktor.
                app=mcp.streamable_http_app(**(_TRANSPORT if _SDK_V2 else {})),
            ),
        ],
        lifespan=lifespan,
        # Anmeldung ganz aussen: sie entfernt den Authorization-Kopf und setzt den Aufrufer, bevor AufruferMiddleware ihn liest.
        middleware=[
            # Ganz aussen: fremde Webseiten im Browser kommen an schreibenden /hub/-Wegen gar nicht erst vorbei.
            Middleware(HerkunftMiddleware),
            Middleware(AnmeldungMiddleware, mcp_pfad=mount_path),
            Middleware(AufruferMiddleware),
            Middleware(EndpunktOhneSchraegstrich, pfad=mount_path),
        ],
    )
    return app


def main() -> None:
    logging.basicConfig(
        level=os.getenv("MCP_HUB_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    import uvicorn  # noqa: PLC0415 — deferred import so `import mcp_hub.server` is cheap

    app = build_app()
    cfg = _CONFIG or HubConfig()
    # Offene Antworten (Stroeme der OS-Bruecke, lange Aufrufe) sollen das Beenden nicht bis zum SIGKILL
    # aufhalten; nach GNADENFRIST_S bricht uvicorn sie ab (requirements.txt: uvicorn >= 0.30, der
    # Parameter besteht seit 0.24).
    uvicorn.run(app, host=cfg.host, port=cfg.port, timeout_graceful_shutdown=GNADENFRIST_S)


if __name__ == "__main__":
    main()
