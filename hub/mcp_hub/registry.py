"""mcp_hub.registry — Plugin-Loader (statisches YAML + Entry-Points).

Zwei Wege, ein Plugin zu laden:
    - Statisch: die Hub-Konfiguration nennt Plugins mit Modulpfad (``module:``). Ein Eintrag ohne ``module``
      verweist auf ein Plugin aus der Entry-Point-Gruppe (Name = Entry-Point-Name) und kann es so konfigurieren.
    - Dynamisch: die Entry-Point-Gruppe ``mcp_hub.plugins`` entdeckt installierte Plugin-Pakete von selbst.
    - Reihenfolge: erst die Konfiguration (deterministisch), dann die Entry-Points; ein Plugin, dessen ``name``
      schon vergeben oder per ``enabled: false`` abgeschaltet ist, wird nicht noch einmal geladen.

Tool-ID Convention:
    Fully-qualified tool-ids are ``"{plugin.name}.{tool.name}"``. The registry
    owns the forward-lookup tables.
"""

from __future__ import annotations

import contextvars
import importlib
import inspect
import json
import logging
import os
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable

from .circuit_breaker import BreakerRegistry, CircuitBreakerConfig
from .config import (
    HubConfig,
    PluginConfig,
    SecretBinding,
    inject_secrets,
    normalize_secret_env_name,
)
from .plugin import (
    HubPlugin,
    KontoFehlt,
    PluginCallError,
    PluginHealthError,
    ServerInfo,
    ToolDescriptor,
    ToolInvocationResult,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "mcp_hub.plugins"

# Zeitlimit je Plugin-Aufruf. Ohne Limit belegte ein haengender Aufruf (Upstream antwortet nie, Socket ohne
# Timeout) einen Arbeitsthread fuer immer, und der Breaker griff nie, weil der Aufruf weder gelang noch scheiterte.
# Vorgabe grosszuegig (120 s); Umgebung `MCP_HUB_AUFRUF_ZEITLIMIT_S` oder Konfiguration `aufruf_zeitlimit_s`
# aendern sie, 0 schaltet sie ab. Werkzeuge, die legitim laenger laufen, tragen ihr eigenes
# `ToolDescriptor.zeitlimit_s` (z. B. werkstatt.ausfuehren).
AUFRUF_ZEITLIMIT_S = 120.0


def _vorgabe_zeitlimit() -> float:
    roh = os.getenv("MCP_HUB_AUFRUF_ZEITLIMIT_S")
    try:
        return float(roh) if roh not in (None, "") else AUFRUF_ZEITLIMIT_S
    except ValueError:
        return AUFRUF_ZEITLIMIT_S

# Wer ruft gerade? Der Server setzt das je Anfrage (REST app-call = fyos-web, MCP = Client-Name aus
# Kopfzeile/User-Agent); das Audit-Log schreibt es zu jedem Ereignis.
AUFRUFER: ContextVar[str] = ContextVar("mcp_hub_aufrufer", default="unknown")
# Ausdrueckliche Art des Aufrufs aus der Kopfzeile `X-Hub-Art` (bewusst | abfrage);
# leer = der Aufrufername entscheidet (audit_log.art_aus).
ART: ContextVar[str] = ContextVar("mcp_hub_art", default="")

# Wer kam zuletzt, auf welchem Weg und mit welcher Protokollversion?
# Das Merkbuch lebt hier und nicht in server.py: der Hub laeuft als `python -m mcp_hub.server` (Modul `__main__`),
# ein Import von `mcp_hub.server` im Plugin saehe ein zweites, leeres Modul. Nur im Speicher dieses Prozesses, bewusst
# klein (die Zahl der verschiedenen Aufrufer ist ein paar Dutzend) und ohne Inhalte — Name, Weg, Zeit, Zaehler.
_FLAECHEN: dict[str, dict[str, Any]] = {}
_FLAECHEN_MAX = 64
_FLAECHEN_SPERRE = threading.Lock()


def flaeche_vermerken(aufrufer: str, weg: str, protokoll: str | None, zeit: float | None = None) -> None:
    """Einen Aufruf von `aufrufer` (Weg: mcp | rest | os) mit dessen `MCP-Protocol-Version` vermerken."""
    jetzt = zeit if zeit is not None else time.time()
    with _FLAECHEN_SPERRE:
        e = _FLAECHEN.get(aufrufer)
        if e is None:
            if len(_FLAECHEN) >= _FLAECHEN_MAX:  # den aeltesten verdraengen
                _FLAECHEN.pop(min(_FLAECHEN, key=lambda k: _FLAECHEN[k]["zuletzt"]), None)
            e = _FLAECHEN[aufrufer] = {"aufrufer": aufrufer, "seit": jetzt, "anzahl": 0, "protokolle": {}}
        e["zuletzt"] = jetzt
        e["weg"] = weg
        e["anzahl"] += 1
        if protokoll:
            e["protokolle"][protokoll[:12]] = e["protokolle"].get(protokoll[:12], 0) + 1


def flaechen_gesehen() -> list[dict[str, Any]]:
    """Kopie des Merkbuchs, juengste zuerst."""
    with _FLAECHEN_SPERRE:
        rows = [{**e, "protokolle": dict(e["protokolle"])} for e in _FLAECHEN.values()]
    return sorted(rows, key=lambda e: e["zuletzt"], reverse=True)


def ist_flaechen_werkzeug(descriptor: ToolDescriptor) -> bool:
    """Darf der Browser (fyos-web /hub-api, WebMCP) dieses Werkzeug rufen?

    Ja, wenn es eine Oberflaeche hat (`meta["ui"]`) oder ausdruecklich mit dem Tag `flaeche` markiert ist. Alles
    andere (z. B. Werkzeuge, die Prozesse starten) bleibt dem MCP-Weg vorbehalten. Eine Stelle fuer REST
    (`/hub/apps`, `/hub/app-call`) und die MCP-App „MCP“.
    """
    return bool(descriptor.meta and "ui" in descriptor.meta) or "flaeche" in (descriptor.tags or [])


def sichtbarkeit(descriptor: ToolDescriptor) -> str:
    """`modell` | `app` | `beide` — wer das Werkzeug sieht (MCP Apps: `_meta.ui.visibility`; ohne Angabe beide)."""
    ui = ((descriptor.meta or {}).get("ui") or {}) if descriptor.meta else {}
    v = ui.get("visibility") if isinstance(ui, dict) else None
    if not isinstance(v, list) or not v:
        return "beide" if ui else "modell"
    if v == ["app"]:
        return "app"
    if v == ["model"]:
        return "modell"
    return "beide"


@dataclass
class RegisteredTool:
    """Internal row: plugin + local-tool-name + descriptor — used for dispatch."""

    plugin_name: str
    tool_name: str  # local (without plugin-prefix)
    fqtn: str  # fully-qualified: "<plugin>.<tool>"
    descriptor: ToolDescriptor


@dataclass
class PluginRegistry:
    """Owns all loaded plugins + their tool-tables + per-plugin circuit-breakers."""

    plugins: dict[str, HubPlugin] = field(default_factory=dict)
    tools: dict[str, RegisteredTool] = field(default_factory=dict)  # keyed by fqtn
    # MCP Apps: ui://-Ressourcen der Plugins, keyed by uri -> (plugin_name, ResourceDescriptor)
    resources: dict[str, tuple[str, Any]] = field(default_factory=dict)
    # Plugins, die nicht geladen werden konnten (Name -> Grund). Ein kaputtes Plugin reisst den Hub nicht mit.
    nicht_geladen: dict[str, str] = field(default_factory=dict)
    # In der Konfiguration abgeschaltete Plugins (enabled: false) — absichtlich aus, nicht kaputt.
    abgeschaltet: set[str] = field(default_factory=set)
    breakers: BreakerRegistry = field(default_factory=BreakerRegistry)
    # Zeitlimit je Aufruf, wenn das Werkzeug keins nennt (s. AUFRUF_ZEITLIMIT_S); 0 = kein Limit.
    aufruf_zeitlimit_s: float = field(default_factory=_vorgabe_zeitlimit)
    # cumulative latency tracking (per fqtn), used by 1.3 audit-plugin
    latency_totals_ms: dict[str, float] = field(default_factory=dict)
    call_counts: dict[str, int] = field(default_factory=dict)
    # on_call hooks — invoked after every registry.call() with
    # the built AuditEvent. Plugins subscribe via register_call_hook().
    on_call_hooks: list[Callable[[Any], None]] = field(default_factory=list)
    # Hooks, die das ERGEBNIS eines gelungenen Aufrufs sehen (der AuditEvent traegt es nicht).
    # Signatur: hook(tool: RegisteredTool, arguments, tir).
    ergebnis_hooks: list[Callable[[Any, dict[str, Any], Any], None]] = field(default_factory=list)

    def register_call_hook(self, callback: Callable[[Any], None]) -> None:
        """Register a callback invoked post-dispatch with an AuditEvent.

        Duplicate registrations are de-duped by identity. Hook-exceptions are
        swallowed by the caller in ``call()`` — no hook can crash dispatch.
        """
        if callback in self.on_call_hooks:
            return
        self.on_call_hooks.append(callback)

    def register_result_hook(self, callback: Callable[[Any, dict[str, Any], Any], None]) -> None:
        """Hook nach jedem GELUNGENEN Aufruf, mit Werkzeug, Argumenten und Ergebnis.

        Wie ``register_call_hook``: Doppelte werden verworfen, Ausnahmen geschluckt, ein Hook
        verzoegert den Aufrufer hoechstens um seine eigene Laufzeit (also: schnell bleiben).
        """
        if callback in self.ergebnis_hooks:
            return
        self.ergebnis_hooks.append(callback)

    def all_tools(self) -> list[RegisteredTool]:
        return list(self.tools.values())

    def get_tool(self, fqtn: str) -> RegisteredTool | None:
        return self.tools.get(fqtn)

    def oeffnen_ziel(self, fqtn: str, args: dict[str, Any] | None) -> tuple[str, dict[str, Any] | None]:
        """Wohin „In FYOS öffnen“ für diesen Aufruf führt.

        Vorgabe: dasselbe Werkzeug mit denselben Argumenten. Ein Plugin darf umlenken, indem es
        ``oeffnen_ziel(werkzeug, args) -> (fqtn, args) | None`` anbietet — etwa wenn die Argumente zu groß für
        einen Link sind (``gui.bauen`` trägt ganze HTML-Dokumente, verlinkt wird ``gui.zeigen {id}``). Das Ziel
        muss ein geladenes Werkzeug sein; sonst und bei jedem Fehler bleibt es bei der Vorgabe.
        """
        rt = self.tools.get(fqtn)
        fn = getattr(self.plugins.get(rt.plugin_name), "oeffnen_ziel", None) if rt is not None else None
        if not callable(fn):
            return fqtn, args
        try:
            z = fn(rt.tool_name, dict(args or {}))
        except Exception as exc:  # noqa: BLE001 — ein Link ist Zugabe, nie ein Fehler des Aufrufs
            logger.info("mcp_hub.registry: oeffnen_ziel %s: %s", fqtn, exc)
            return fqtn, args
        if isinstance(z, tuple) and len(z) == 2 and isinstance(z[0], str) and z[0] in self.tools:
            return z[0], z[1] if isinstance(z[1], dict) else None
        return fqtn, args

    def server_infos(self) -> list[ServerInfo]:
        infos: list[ServerInfo] = []
        for plugin_name, plugin in self.plugins.items():
            tool_count = sum(1 for t in self.tools.values() if t.plugin_name == plugin_name)
            raw_health: dict[str, Any] = {}
            try:
                raw_health = plugin.health() or {}
            except PluginHealthError as exc:
                logger.info(
                    "mcp_hub.registry: health() reported unhealthy for %s: %s", plugin_name, exc
                )
                raw_health = {"ok": False, "status": "unhealthy", "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_hub.registry: health() failed for %s: %s", plugin_name, exc)
                raw_health = {"ok": False, "status": "unhealthy", "reason": str(exc)}
            healthy = plugin_healthy(raw_health)
            # unreachable separat tragen — ein totes Ziel ist kein "vielleicht gleich wieder gut", es ist ein Befund.
            unreachable = str(raw_health.get("status", "")).lower() == "unreachable"
            infos.append(
                ServerInfo(
                    name=plugin_name,
                    description=plugin.description or "",
                    tool_count=tool_count,
                    healthy=healthy,
                    version=plugin.version or "0.0.0",
                    unreachable=unreachable,
                )
            )
        return infos

    def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Run health() across every plugin + collect results.

        Returns a dict keyed by plugin-name. Each value is either the plugin's
        own health-dict (on success) or ``{"ok": False, "error": "..."}`` on
        exception. Never raises — safe to hook into k8s readiness probes.
        """
        out: dict[str, dict[str, Any]] = {}
        for plugin_name, plugin in self.plugins.items():
            try:
                res = plugin.health() or {}
                if not isinstance(res, dict):
                    res = {"ok": False, "error": f"health() returned {type(res).__name__}"}
                out[plugin_name] = res
            except PluginHealthError as exc:
                out[plugin_name] = {"ok": False, "error": str(exc), "kind": "plugin_health_error"}
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_hub.registry: health() raised for %s: %s", plugin_name, exc)
                out[plugin_name] = {"ok": False, "error": str(exc), "kind": "plugin_error"}
            out[plugin_name].setdefault("breaker", self.breakers.get(plugin_name).snapshot())
        return out


# ── Tool-Map ─────────────────────────────────────────────────────────────────

_SCOPE_ORDER = ("destructive", "extern", "exec", "write", "read")


def scope_from_tags(tags: list[str] | None) -> str:
    """Scope-Klasse aus Tool-Tags (Konvention: read/write/destructive/extern).

    Schärfste Wirkung gewinnt (destructive > extern > exec > write > read).
    Ohne Scope-Tag → "unknown" (fail-visible: Karte zeigt ungetaggte Tools,
    statt sie falsch als read zu verkaufen).
    """
    low = {str(t).lower() for t in (tags or [])}
    for scope in _SCOPE_ORDER:
        if scope in low:
            return scope.upper()
    return "UNKNOWN"


def map_view(
    reg: "PluginRegistry", domain: str | None = None, include_health: bool = True
) -> dict[str, Any]:
    """Die Tool-Map: domain → tools mit scope + 1-Zeilen-Summary, OHNE Schemas.

    Discovery-first für Small-Models: map → hub__schema(tool) → hub__call_tool.
    health kommt live aus plugin.health() (tote Tools sind sichtbar tot).
    """
    health: dict[str, bool] = {}
    if include_health:
        health = {i.name: i.healthy for i in reg.server_infos()}
    domains: list[dict[str, Any]] = []
    for pname, plugin in reg.plugins.items():
        if domain and pname != domain:
            continue
        tools = []
        for rt in reg.tools.values():
            if rt.plugin_name != pname:
                continue
            summary = (rt.descriptor.description or "").strip().splitlines()
            tools.append(
                {
                    "tool": rt.fqtn,
                    "scope": scope_from_tags(getattr(rt.descriptor, "tags", None)),
                    "summary": (summary[0] if summary else "")[:140],
                }
            )
        entry: dict[str, Any] = {
            "domain": pname,
            "summary": (plugin.description or "").strip().splitlines()[0][:140]
            if plugin.description
            else "",
            "tool_count": len(tools),
            "tools": sorted(tools, key=lambda t: t["tool"]),
        }
        if include_health:
            entry["healthy"] = health.get(pname)
        domains.append(entry)
    return {
        "ok": True,
        "domains": sorted(domains, key=lambda d: d["domain"]),
        "count": len(domains),
    }


def tool_schema(reg: "PluginRegistry", fqtn: str) -> dict[str, Any]:
    """Schema EINES Tools (Stufe 2 des 3-Stufen-Calls map→schema→call)."""
    rt = reg.get_tool(fqtn)
    if rt is None:
        return {"ok": False, "error": f"unbekanntes Tool {fqtn!r}", "kind": "not_found"}
    return {
        "ok": True,
        "tool": rt.fqtn,
        "scope": scope_from_tags(getattr(rt.descriptor, "tags", None)),
        "description": rt.descriptor.description,
        "inputSchema": rt.descriptor.input_schema,
    }


def plugin_aus(result: dict[str, Any]) -> bool:
    """Ist dieses Plugin ABSICHTLICH aus?

    „Abgeschaltet" und „unerreichbar" sehen im Ergebnis gleich aus und bedeuten das Gegenteil.
    Wer sie nicht trennt, faerbt einen bewusst ruhenden Dienst rot — und dann faellt der Tag
    nicht mehr auf, an dem wirklich etwas ausfaellt.
    """
    if not isinstance(result, dict):
        return False
    return str(result.get("status", "")).lower() in ("disabled", "aus", "off")


def plugin_healthy(result: dict[str, Any]) -> bool:
    """EINE Wahrheit über die drei üblichen health()-Schemata.

    Kontrakt (plugin.py): ``{"ok": bool}``. Verbreitet sind außerdem ``{"status": "ok"}`` und
    ``{"available": bool}``. Der ok-Key gewinnt; ohne jedes bekannte Feld → fail-closed False.
    """
    if not isinstance(result, dict):
        return False
    if "ok" in result:
        return bool(result["ok"])
    if "status" in result:
        return str(result["status"]).lower() in ("ok", "healthy")
    if "available" in result:
        return bool(result["available"])
    return False


def _instantiate_plugin(pcfg: PluginConfig, klasse: type[HubPlugin] | None = None) -> HubPlugin:
    """Import the module + find the HubPlugin subclass + instantiate.

    If ``pcfg.class_name`` is provided, use that class. Otherwise pick the first
    HubPlugin subclass declared in the module. Without ``pcfg.module`` the plugin
    is looked up in the entry-point group by name (or taken from ``klasse``).
    """
    module = None
    cls: Any = klasse
    if klasse is not None:
        pass
    elif not pcfg.module:
        cls = _entry_point_klasse(pcfg.name)
    else:
        module = importlib.import_module(pcfg.module)

    if module is None:
        pass
    elif pcfg.class_name:
        cls = getattr(module, pcfg.class_name, None)
        if cls is None:
            raise ImportError(f"{pcfg.module} has no attribute {pcfg.class_name}")
    else:
        cls = None
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is HubPlugin:
                continue
            if issubclass(obj, HubPlugin) and obj.__module__ == module.__name__:
                cls = obj
                break
        if cls is None:
            raise ImportError(f"{pcfg.module} exports no HubPlugin subclass")

    if not issubclass(cls, HubPlugin):
        raise TypeError(f"{cls.__name__} is not a HubPlugin subclass")

    # Plugins, die ihre Config im Konstruktor lesen (Parameter `config`), bekommen sie dort; sonst
    # fielen alle YAML-Werte still auf die Vorgaben zurueck.
    try:
        nimmt_config = "config" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        nimmt_config = False
    instance = cls(config=pcfg.config or {}) if nimmt_config else cls()
    # Attach plugin-specific config so plugin.register() can read it.
    if pcfg.config:
        instance.config = pcfg.config  # type: ignore[attr-defined]
    return instance


def _entry_point_klasse(name: str) -> type[HubPlugin]:
    """Plugin-Klasse eines Entry-Points der Gruppe ``mcp_hub.plugins`` nach Name (fuer Eintraege ohne ``module``)."""
    for ep_name, cls in _discover_entry_points():
        if ep_name == name:
            return cls
    raise ImportError(
        f"plugin {name!r} hat kein 'module' und ist auch nicht als Entry-Point der Gruppe {ENTRY_POINT_GROUP!r} installiert"
    )


def _discover_entry_points() -> list[tuple[str, type[HubPlugin]]]:
    """Scan ``mcp_hub.plugins`` entry-points group. Returns ``(name, class)``.

    Silently returns empty on older Pythons / missing metadata — entry-point
    discovery is opt-in, never a hard requirement.
    """
    results: list[tuple[str, type[HubPlugin]]] = []
    try:
        from importlib.metadata import entry_points

        try:
            eps = entry_points(group=ENTRY_POINT_GROUP)  # type: ignore[call-arg]
        except TypeError:
            # Python < 3.10 fallback: entry_points returns dict
            eps = entry_points().get(ENTRY_POINT_GROUP, [])  # type: ignore[assignment]
    except Exception as exc:  # noqa: BLE001
        logger.debug("mcp_hub.registry: entry-point discovery skipped: %s", exc)
        return results

    for ep in eps:
        try:
            cls = ep.load()
            if inspect.isclass(cls) and issubclass(cls, HubPlugin):
                results.append((ep.name, cls))
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.registry: entry-point %s failed to load: %s", ep.name, exc)
    return results


def plugins_ohne_eintrag(cfg: HubConfig, paket: str = "mcp_hub.plugins") -> list[PluginConfig]:
    """Plugin-Module ohne Eintrag in ``cfg.plugins`` (Option ``plugins_von_selbst``).

    Ein Modul zählt, wenn es nicht mit ``_`` beginnt und selbst eine HubPlugin-Klasse definiert.
    Hilfsmodule fallen so heraus. Ein Eintrag mit ``enabled: false`` bleibt der Weg,
    ein Plugin abzuschalten; ein Modul, das nicht importiert, landet wie sonst unter ``nicht_geladen``.
    """
    import pkgutil  # noqa: PLC0415

    vergeben = {p.module for p in cfg.plugins}
    namen = {p.name for p in cfg.plugins}
    paket_mod = importlib.import_module(paket)
    neu: list[PluginConfig] = []
    for info in sorted(pkgutil.iter_modules(paket_mod.__path__), key=lambda i: i.name):
        modul = f"{paket}.{info.name}"
        if info.name.startswith("_") or info.ispkg or modul in vergeben:
            continue
        try:
            mod = importlib.import_module(modul)
        except Exception as exc:  # noqa: BLE001 — wie ein kaputter Eintrag: sichtbar, nicht tödlich
            neu.append(PluginConfig(name=info.name, module=modul))
            logger.warning("mcp_hub.registry: %s ohne Eintrag importiert nicht: %s", modul, exc)
            continue
        klassen = [
            obj
            for _, obj in inspect.getmembers(mod, inspect.isclass)
            if issubclass(obj, HubPlugin) and not inspect.isabstract(obj) and obj.__module__ == mod.__name__
        ]
        if not klassen:
            continue
        name = getattr(klassen[0], "name", "") or info.name
        if name in namen:
            continue
        logger.info("mcp_hub.registry: %s lädt ohne Eintrag (als %s)", modul, name)
        neu.append(PluginConfig(name=name, module=modul, class_name=klassen[0].__name__))
        namen.add(name)
    return neu


def build_registry(cfg: HubConfig) -> PluginRegistry:
    """Build the complete plugin-registry from config + entry-points.

    1. Static YAML plugins first (fail-fast on config errors).
    2. Entry-point plugins merged if name not yet taken.
    3. Each plugin gets ``register()`` → ``init()`` → ``describe_tools()``
       called in that order (1.2 adds the init() hook).
    4. Circuit-breaker defaults from ``cfg.circuit_breaker`` (if present) are
       applied to the BreakerRegistry.
    """
    reg = PluginRegistry()
    if getattr(cfg, "aufruf_zeitlimit_s", None) is not None and not os.getenv("MCP_HUB_AUFRUF_ZEITLIMIT_S"):
        reg.aufruf_zeitlimit_s = float(cfg.aufruf_zeitlimit_s)

    # Apply circuit-breaker defaults from config (if present).
    cb_cfg_raw = getattr(cfg, "circuit_breaker", None) or {}
    if cb_cfg_raw:
        reg.breakers.default_config = CircuitBreakerConfig(
            failure_threshold=int(cb_cfg_raw.get("failure_threshold", 5)),
            timeout_sec=float(cb_cfg_raw.get("timeout_sec", 30.0)),
            half_open_max_calls=int(cb_cfg_raw.get("half_open_max_calls", 3)),
            enabled=bool(cb_cfg_raw.get("enabled", True)),
        )

    # --- Static YAML, danach Plugin-Dateien ohne Eintrag (Regel statt Liste) -
    eintraege = list(cfg.plugins)
    if getattr(cfg, "plugins_von_selbst", False):
        eintraege += plugins_ohne_eintrag(cfg)
    for pcfg in eintraege:
        if not pcfg.enabled:
            logger.info("mcp_hub.registry: skip disabled plugin %s", pcfg.name)
            reg.abgeschaltet.add(pcfg.name)
            continue
        _inject_plugin_secrets_into_env(pcfg)
        try:
            plugin = _instantiate_plugin(pcfg)
        except Exception as exc:  # noqa: BLE001 — ein Plugin darf den Hub nicht mitreissen
            logger.error("mcp_hub.registry: failed to instantiate %s: %s", pcfg.name, exc)
            reg.nicht_geladen[pcfg.name] = f"{type(exc).__name__}: {exc}"
            continue

        declared_name = plugin.name or pcfg.name
        if declared_name != pcfg.name:
            logger.warning(
                "mcp_hub.registry: plugin class name=%r overrides config name=%r",
                declared_name,
                pcfg.name,
            )
        if declared_name in reg.plugins:
            raise ValueError(f"mcp_hub.registry: duplicate plugin name {declared_name!r}")
        try:
            _register_one(reg, declared_name, plugin)
        except Exception as exc:  # noqa: BLE001
            logger.error("mcp_hub.registry: register of %s failed: %s", declared_name, exc)
            reg.nicht_geladen[declared_name] = f"{type(exc).__name__}: {exc}"
            # Halb registrierte Werkzeuge wieder entfernen.
            for fqtn in [t for t, rt in reg.tools.items() if rt.plugin_name == declared_name]:
                reg.tools.pop(fqtn, None)
            reg.plugins.pop(declared_name, None)

    # --- Entry-points merge ------------------------------------------------
    for ep_name, cls in _discover_entry_points():
        declared_name = getattr(cls, "name", "") or ep_name
        if declared_name in reg.plugins or declared_name in reg.abgeschaltet or declared_name in reg.nicht_geladen:
            logger.debug(
                "mcp_hub.registry: entry-point %s skipped (already registered or disabled)",
                declared_name,
            )
            continue
        try:
            plugin = _instantiate_plugin(PluginConfig(name=ep_name, module="", class_name=""), klasse=cls)
            declared_name = plugin.name or ep_name
            _register_one(reg, declared_name, plugin)
        except Exception as exc:  # noqa: BLE001 — ein Plugin darf den Hub nicht mitreissen
            logger.error("mcp_hub.registry: entry-point plugin %s failed: %s", ep_name, exc)
            reg.nicht_geladen[declared_name] = f"{type(exc).__name__}: {exc}"
            for fqtn in [t for t, rt in reg.tools.items() if rt.plugin_name == declared_name]:
                reg.tools.pop(fqtn, None)
            reg.plugins.pop(declared_name, None)

    logger.info(
        "mcp_hub.registry: loaded %d plugin(s) exposing %d tool(s)",
        len(reg.plugins),
        len(reg.tools),
    )
    return reg


def _inject_plugin_secrets_into_env(pcfg: PluginConfig) -> None:
    """Resolve plugin secrets and expose them under stable env-var targets.

    Priority:
    1. explicit ``secrets: [{name, env}]``
    2. plugin ``*_env`` config keys when exactly one secret is bound
    3. normalized secret-name env (``argocd-api-token`` -> ``ARGOCD_API_TOKEN``)
    Existing env-vars win over injected values.
    """
    if not pcfg.secrets:
        return

    resolved = inject_secrets(pcfg.secrets)
    if not resolved:
        return

    configured_env_targets = [
        str(value).strip()
        for key, value in (pcfg.config or {}).items()
        if key.endswith("_env") and isinstance(value, str) and str(value).strip()
    ]

    single_secret = len(pcfg.secrets) == 1
    for binding in pcfg.secrets:
        if isinstance(binding, str):
            binding = SecretBinding(name=binding)
        value = resolved.get(binding.name)
        if not value:
            continue

        targets = {normalize_secret_env_name(binding.name)}
        if binding.env:
            targets.add(binding.env)
        if single_secret:
            targets.update(configured_env_targets)

        for env_name in targets:
            if env_name and not os.getenv(env_name):
                os.environ[env_name] = value


def _register_one(reg: PluginRegistry, name: str, plugin: HubPlugin) -> None:
    """Register a single plugin: register() → init() → describe_tools() → index tools.

    ``init()`` is a lifecycle hook — called after register() but before the
    tool-descriptors are indexed, so plugins may set up cross-plugin state.
    Errors in init() are fatal (same semantics as register()).
    """
    try:
        plugin.register()
    except Exception as exc:
        logger.error("mcp_hub.registry: %s.register() failed: %s", name, exc)
        raise

    try:
        plugin.init()
    except Exception as exc:
        logger.error("mcp_hub.registry: %s.init() failed: %s", name, exc)
        raise

    descriptors = plugin.describe_tools() or []
    for desc in descriptors:
        if not desc.name:
            raise ValueError(f"mcp_hub.registry: {name} exposes a ToolDescriptor without name")
        fqtn = f"{name}.{desc.name}"
        if fqtn in reg.tools:
            raise ValueError(f"mcp_hub.registry: duplicate tool-id {fqtn!r}")
        reg.tools[fqtn] = RegisteredTool(
            plugin_name=name,
            tool_name=desc.name,
            fqtn=fqtn,
            descriptor=desc,
        )

    for res in plugin.describe_resources() or []:
        if res.uri in reg.resources:
            raise ValueError(f"mcp_hub.registry: duplicate resource {res.uri!r}")
        reg.resources[res.uri] = (name, res)

    reg.plugins[name] = plugin
    # Pre-create breaker for this plugin (stable snapshot counts from start).
    reg.breakers.get(name)

    logger.info(
        "mcp_hub.registry: registered plugin %s v%s with %d tools",
        name,
        plugin.version,
        len(descriptors),
    )


def shutdown_registry(reg: PluginRegistry) -> None:
    """Call ``shutdown()`` on every plugin, swallowing exceptions.

    Best-effort cleanup during Hub teardown. One plugin's
    shutdown-failure must not block the others.
    """
    for name, plugin in reg.plugins.items():
        try:
            plugin.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.registry: %s.shutdown() failed: %s", name, exc)


# ---------------------------------------------------------------------------
# Search helpers (used by hub__search_tools meta-tool)
# ---------------------------------------------------------------------------


def search_tools(reg: PluginRegistry, query: str) -> list[dict[str, Any]]:
    """Case-insensitive substring match over fqtn + description.

    Returns MCP-compatible dicts (name, description, inputSchema). Empty query
    returns ALL tools — useful for first-time inventory.
    """
    q = (query or "").strip().lower()
    results: list[dict[str, Any]] = []
    for tool in reg.all_tools():
        if (
            q
            and q not in tool.fqtn.lower()
            and q not in (tool.descriptor.description or "").lower()
        ):
            continue
        results.append(
            {
                "name": tool.fqtn,
                "description": tool.descriptor.description,
                "inputSchema": tool.descriptor.input_schema or {"type": "object", "properties": {}},
                "plugin": tool.plugin_name,
                "tags": tool.descriptor.tags,
            }
        )
    return results


def call(reg: PluginRegistry, fqtn: str, arguments: dict[str, Any]) -> ToolInvocationResult:
    """Structured plugin-dispatch with circuit-breaker + latency-tracking.

    This is the 1.2 entry-point. Returns a :class:`ToolInvocationResult`
    whose ``status`` is ``"ok"`` or ``"error"`` — never raises (except for
    pathological Python-level errors unrelated to the plugin).

    Flow:
        1. Resolve fqtn → (plugin_name, tool_name, plugin-instance).
        2. Consult per-plugin circuit-breaker: if OPEN → fast-fail.
        3. Time the call, capture exceptions, wrap into ToolInvocationResult.
        4. Record outcome on the breaker (success/failure).
        5. Update cumulative latency + call-count telemetry on ``reg``.

    Used by the wire-level ``dispatch()`` wrapper below for backwards-compat
    with the dict-based response.
    """
    tool = reg.get_tool(fqtn)
    if tool is None:
        return ToolInvocationResult(
            status="error",
            error=f"unknown tool {fqtn!r}",
            kind="not_found",
        )

    plugin = reg.plugins.get(tool.plugin_name)
    if plugin is None:
        return ToolInvocationResult(
            status="error",
            error=f"plugin {tool.plugin_name!r} missing",
            kind="not_found",
        )

    # Unbekannte Argumente wuerden sonst still ignoriert — der Aufrufer bekaeme ein Ergebnis fuer eine
    # Frage, die er nicht gestellt hat. Wer `additionalProperties: false` deklariert, bekommt die
    # Pruefung zentral hier.
    falsch = unbekannte_argumente(tool.descriptor.input_schema, arguments)
    if falsch:
        erlaubt = sorted((tool.descriptor.input_schema or {}).get("properties") or {})
        tir = ToolInvocationResult(
            status="error",
            error=(
                f"{fqtn}: unbekannte Argumente {falsch} — erlaubt sind "
                f"{erlaubt if erlaubt else 'keine Argumente'}"
            ),
            kind="bad_arguments",
        )
        _fire_on_call_hooks(reg, fqtn, arguments, tir)
        return tir

    breaker = reg.breakers.get(tool.plugin_name)
    if not breaker.allow_call():
        return ToolInvocationResult(
            status="error",
            error=f"circuit open for plugin {tool.plugin_name!r} — fast-failing",
            kind="circuit_open",
        )

    t0 = time.monotonic()
    zeitlimit = zeitlimit_fuer(reg, tool)
    try:
        result = _aufruf_mit_zeitlimit(plugin, tool.tool_name, dict(arguments or {}), zeitlimit, fqtn)
    except KontoFehlt as exc:
        # Kein Ausfall des Plugins (kein Breaker-Fehlschlag): der Mensch muss ein Konto verbinden. Der Link geht mit.
        latency_ms = (time.monotonic() - t0) * 1000.0
        _record_latency(reg, fqtn, latency_ms)
        tir = ToolInvocationResult(
            status="error",
            result=exc.als_ergebnis(),
            error=str(exc),
            latency_ms=latency_ms,
            kind="konto_fehlt",
        )
        _fire_on_call_hooks(reg, fqtn, arguments, tir)
        return tir
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.monotonic() - t0) * 1000.0
        art = fehlerart(exc)
        if art == "bad_arguments":
            # Eingabefehler (falsches Argument des Aufrufers) sind kein Ausfall des Plugins: fuenf davon
            # sperrten es sonst 30 s fuer alle. Wie das Konto-Beispiel oben: kein Breaker.
            _record_latency(reg, fqtn, latency_ms)
            tir = ToolInvocationResult(
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms,
                kind="bad_arguments",
            )
            _fire_on_call_hooks(reg, fqtn, arguments, tir)
            return tir
        breaker.record_failure()
        logger.info(
            "mcp_hub.registry: dispatch %s raised %s (latency=%.2fms)",
            fqtn,
            type(exc).__name__,
            latency_ms,
        )
        # Wrap plugin exc into PluginCallError trace for structured logging.
        _pce = PluginCallError(tool.plugin_name, tool.tool_name, str(exc), cause=exc)
        _record_latency(reg, fqtn, latency_ms)
        tir = ToolInvocationResult(
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            latency_ms=latency_ms,
            kind=art,
        )
        _fire_on_call_hooks(reg, fqtn, arguments, tir)
        return tir

    latency_ms = (time.monotonic() - t0) * 1000.0
    breaker.record_success()
    _record_latency(reg, fqtn, latency_ms)
    # Manche Plugins melden Fehlschlaege als `{"ok": false}` statt zu werfen. Ohne diese Pruefung wuerde
    # daraus `{"ok": true, "result": {"ok": false}}` — ein Fehlschlag, der nach Erfolg aussieht. Der Breaker
    # zaehlt es weiter als Erfolg (das Plugin hat geantwortet), der Aufrufer und das Audit sehen `error`.
    # Ebenso `{"error": "..."}` OHNE `ok`. Ein ausdrueckliches `ok: true` gewinnt.
    if isinstance(result, dict) and (
        result.get("ok") is False or ("ok" not in result and result.get("error"))
    ):
        grund = result.get("error") or result.get("stderr") or result.get("message")
        tir = ToolInvocationResult(
            status="error",
            result=result,
            error=str(grund) if grund else f"{fqtn} meldet ok=false",
            latency_ms=latency_ms,
            kind="tool_failed",
        )
        _fire_on_call_hooks(reg, fqtn, arguments, tir)
        return tir
    tir = ToolInvocationResult(
        status="ok",
        result=result,
        latency_ms=latency_ms,
    )
    _fire_on_call_hooks(reg, fqtn, arguments, tir)
    _fire_ergebnis_hooks(reg, tool, arguments, tir)
    return tir


class AufrufZeitueberschreitung(Exception):
    """Ein Plugin-Aufruf hat sein Zeitlimit ueberschritten (kind ``timeout``, zaehlt gegen den Breaker)."""


def zeitlimit_fuer(reg: PluginRegistry, tool: RegisteredTool) -> float:
    """Zeitlimit dieses Werkzeugs: eigenes (`ToolDescriptor.zeitlimit_s`), sonst das des Hubs; 0 = keins."""
    eigenes = getattr(tool.descriptor, "zeitlimit_s", None)
    return float(eigenes if eigenes is not None else reg.aufruf_zeitlimit_s)


def fehlerart(exc: BaseException) -> str:
    """`kind` zu einer Ausnahme aus einem Plugin: Eingabefehler, Zeitueberschreitung oder Plugin-Fehler.

    `ValueError` ist ein Eingabefehler (Plugins pruefen Argumente so: ``raise ValueError("limit muss ...")``) —
    ausser Lesefehlern, die das Plugin selbst von seinem Upstream bekommt: eine kaputte JSON-Antwort
    (`json.JSONDecodeError`) oder ungueltige Kodierung (`UnicodeDecodeError`) sind Ausfaelle des Dienstes
    dahinter und zaehlen weiter gegen den Breaker.
    """
    if isinstance(exc, AufrufZeitueberschreitung):
        return "timeout"
    if isinstance(exc, ValueError) and not isinstance(exc, (json.JSONDecodeError, UnicodeError)):
        return "bad_arguments"
    return "plugin_error"


def _aufruf_mit_zeitlimit(plugin: Any, tool_name: str, arguments: dict[str, Any], zeitlimit_s: float, fqtn: str) -> Any:
    """`plugin.call` mit Zeitlimit in einem eigenen Faden; ohne Limit (<= 0) direkt im aufrufenden Faden.

    Ein Python-Faden laesst sich nicht toeten. Nach Ablauf kehrt der Hub zurueck (Fehler `timeout`, der Breaker
    zaehlt ihn), der haengende Faden laeuft im Hintergrund weiter bis das Plugin von selbst fertig wird oder der
    Pod endet; er ist ein Daemon und haelt den Hub nicht am Beenden. Sein spaetes Ergebnis wird verworfen.
    Plugins sollen deshalb eigene Netz- und Prozess-Timeouts setzen — dieses Limit ist das Netz darunter, nicht
    der Ersatz. Der Kontext (AUFRUFER) wandert in den Faden mit.
    """
    if not zeitlimit_s or zeitlimit_s <= 0:
        return plugin.call(tool_name, arguments)
    ergebnis: dict[str, Any] = {}
    fertig = threading.Event()
    kontext = contextvars.copy_context()

    def lauf() -> None:
        try:
            ergebnis["wert"] = kontext.run(plugin.call, tool_name, arguments)
        except BaseException as exc:  # noqa: BLE001 — wird im Aufrufer unveraendert neu geworfen
            ergebnis["fehler"] = exc
        finally:
            fertig.set()

    threading.Thread(target=lauf, name=f"hub-aufruf-{fqtn}", daemon=True).start()
    if not fertig.wait(zeitlimit_s):
        raise AufrufZeitueberschreitung(f"{fqtn}: keine Antwort nach {zeitlimit_s:g} s (Zeitlimit des Hubs)")
    if "fehler" in ergebnis:
        raise ergebnis["fehler"]
    return ergebnis.get("wert")


def unbekannte_argumente(
    schema: dict[str, Any] | None, arguments: dict[str, Any] | None
) -> list[str]:
    """Argumente, die das Schema nicht kennt — nur bei ``additionalProperties: false``.

    Schemas ohne diese Angabe bleiben offen. Das Hub-interne
    Trockenlauf-Signal ``__dry_run__`` (plugin.is_dry_run) ist immer erlaubt.
    """
    if not isinstance(schema, dict) or schema.get("additionalProperties") is not False:
        return []
    erlaubt = set((schema.get("properties") or {}).keys()) | {"__dry_run__"}
    return sorted(k for k in (arguments or {}) if k not in erlaubt)


def _fire_on_call_hooks(
    reg: PluginRegistry,
    fqtn: str,
    arguments: dict[str, Any],
    tir: ToolInvocationResult,
) -> None:
    """Build an AuditEvent and fan-out to every registered on_call hook.

    Imports :mod:`mcp_hub.audit_log` lazily so the registry stays importable
    when the audit subsystem is absent (e.g. unit tests that bypass the audit-
    plugin). Hook-exceptions are swallowed — one broken subscriber must never
    crash dispatch.
    """
    if not reg.on_call_hooks:
        return
    try:
        from .audit_log import build_event_from_call  # noqa: PLC0415

        event = build_event_from_call(
            fqtn=fqtn, arguments=arguments or {}, result=tir, caller=AUFRUFER.get(), art=ART.get()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("mcp_hub.registry: build_event_from_call failed: %s", exc)
        return

    for hook in list(reg.on_call_hooks):
        try:
            hook(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.registry: on_call hook raised: %s", exc)

    # Suchspur: schließt eine vorangegangene Suche desselben Aufrufers ab — Labels
    # „Anfrage → gewähltes Werkzeug“ für die Messung der Werkzeugsuche.
    try:
        from . import suchspur  # noqa: PLC0415

        suchspur.schliesse_ab(event.caller, fqtn)
    except Exception as exc:  # noqa: BLE001
        logger.debug("mcp_hub.registry: suchspur failed: %s", exc)


def _fire_ergebnis_hooks(
    reg: PluginRegistry,
    tool: RegisteredTool,
    arguments: dict[str, Any],
    tir: ToolInvocationResult,
) -> None:
    """Ergebnis-Hooks (``register_result_hook``) nach einem gelungenen Aufruf; Fehler werden geschluckt."""
    for hook in list(reg.ergebnis_hooks):
        try:
            hook(tool, dict(arguments or {}), tir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.registry: result hook raised: %s", exc)


def _record_latency(reg: PluginRegistry, fqtn: str, latency_ms: float) -> None:
    reg.latency_totals_ms[fqtn] = reg.latency_totals_ms.get(fqtn, 0.0) + latency_ms
    reg.call_counts[fqtn] = reg.call_counts.get(fqtn, 0) + 1


def dispatch(reg: PluginRegistry, fqtn: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Wire-level wrapper — preserves the dict-shape for callers
    that already consume ``{"ok": bool, "result"|"error": ...}``.

    Internally delegates to :func:`call` for circuit-breaker + latency tracking.
    """
    res = call(reg, fqtn, arguments)
    return res.to_dict()
