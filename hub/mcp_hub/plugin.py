"""mcp_hub.plugin — HubPlugin Abstract Base Class + error-taxonomy + ToolInvocationResult.

Every FYOS MCP-Hub plugin implements this interface. Plugins run in-process (no
HTTP-Roundtrip between Hub and Plugin).

Minimal lifecycle:
    1. Hub instantiates plugin via ``Plugin()`` (no args) or via factory hook.
    2. Hub calls ``register()`` once at startup — plugin may set up connections,
       load credentials, warm caches.
    3. Hub calls ``init()`` for one-time extended setup after registration
       (optional — default no-op).
    4. Hub calls ``describe_tools()`` to collect ToolDescriptors for schema-merge.
    5. For every tool-call, Hub calls ``call(method, args)`` — plugin dispatches
       internally.
    6. Hub periodically calls ``health()`` and ``metrics()`` for observability.
    7. On hub-shutdown, Hub calls ``shutdown()`` for graceful cleanup (optional).

Error-Taxonomy:
    PluginError         — base class, all plugin-surfaced errors subclass this
    PluginCallError     — raised when plugin.call() fails (wrapped plugin exc)
    PluginHealthError   — raised when plugin.health() probe fails

Tool-ID Convention:
    ``"{plugin_name}.{tool_name}"`` — e.g. ``"echo.say"``, ``"math.add"``.
    The ``plugin_name`` comes from ``Plugin.name`` (must be unique within Hub).

Example:
    >>> class MyPlugin(HubPlugin):
    ...     name = "my"
    ...     version = "1.0.0"
    ...     description = "Demo plugin"
    ...     def register(self) -> None: ...
    ...     def describe_tools(self): return [ToolDescriptor(name="ping", description="ping")]
    ...     def call(self, method, args):
    ...         if method == "ping": return {"pong": True}
    ...         raise ValueError(f"unknown {method}")
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Dry-Run Sentinel + Result-Builder.
# ---------------------------------------------------------------------------


DRY_RUN_FLAG = "__dry_run__"
"""Args-key that triggers per-action dry-run mode in plugin.call().

When ``True`` in the ``args`` dict passed to ``HubPlugin.call()``, a plugin
that supports dry-run MUST return a plan-shape (see ``build_dry_run_result``)
WITHOUT executing the underlying side-effect (HTTP write, subprocess, etc.).
Plugins that do NOT support dry-run MUST return ``build_dry_run_unsupported``
to signal graceful-degradation (no crash). The Hub-level registry.call()
treats this exactly like any other arg — the contract lives entirely in the
plugin.

Design:
    - one flag, one branch, no execution;
    - predictable side-effects build trust.

Naming choice:
    Double-underscore prefix `__dry_run__` (instead of plain `dry_run`) so it
    cannot collide with plugin-internal args. Some plugins expose a server-side
    `dry_run` of their own — the sentinel is a different layer (Hub-side
    pre-action) and must be unambiguous.
"""


def is_dry_run(args: dict[str, Any]) -> bool:
    """Detect the dry-run sentinel without mutating args. Pattern H19."""
    return bool(args.get(DRY_RUN_FLAG, False))


def build_dry_run_result(
    *,
    would_execute: str,
    expected_side_effects: Optional[list[str]] = None,
    estimated_cost: Optional[int] = None,
    plugin: Optional[str] = None,
    method: Optional[str] = None,
    args_preview: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Construct a canonical dry-run plan-result for a plugin tool-call.

    Returns a dict that downstream consumers (UI, agents) can render either as
    JSON or as a single sentence. Schema is stable across plugins.

    Args:
        would_execute: Single sentence describing the action — present tense,
            human-readable. Example: ``"sync application 'demo' with
            hard-refresh enabled"``.
        expected_side_effects: List of side-effect strings each in the
            ``"<resource>: <change>"`` format. Empty list when no side-effects.
        estimated_cost: Optional integer cost-estimate (HTTP-calls, k8s-ops,
            git-pushes, LLM-tokens — caller-decided unit). ``None`` if N/A.
        plugin: Plugin-name (filled in by callers; not strictly required).
        method: Tool-name (same).
        args_preview: Sanitized snapshot of the args that WOULD have been sent
            (use to drop secrets / large blobs). Default None.

    Returns:
        Dict with the canonical keys::

            {
                "ok": True,
                "dry_run": True,
                "would_execute": <str>,
                "expected_side_effects": [<str>, ...],
                "estimated_cost": <int|None>,
                "plugin": <str|None>,
                "method": <str|None>,
                "args_preview": <dict|None>,
            }

    Pattern:
        Mirrors ``ToolInvocationResult`` shape so a Hub-caller cannot tell the
        difference between "ran successfully" and "would have run successfully"
        in terms of envelope-keys — only the ``dry_run`` flag distinguishes.
    """
    return {
        "ok": True,
        "dry_run": True,
        "would_execute": would_execute,
        "expected_side_effects": list(expected_side_effects or []),
        "estimated_cost": estimated_cost,
        "plugin": plugin,
        "method": method,
        "args_preview": args_preview,
    }


def build_dry_run_unsupported(plugin: str, method: str) -> dict[str, Any]:
    """Construct the canonical "plugin-does-not-support-dry-run" response.

    Plugins that opt out of dry-run MUST surface this shape (instead of crashing
    or silently executing). Hub-side consumers branch on ``ok=False`` +
    ``error="dry_run_unsupported"``.

    Args:
        plugin: Plugin-name (e.g. ``"echo"``).
        method: Tool-name (e.g. ``"say"``).

    Returns:
        Dict::

            {
                "ok": False,
                "error": "dry_run_unsupported",
                "plugin": <plugin>,
                "method": <method>,
            }
    """
    return {
        "ok": False,
        "error": "dry_run_unsupported",
        "plugin": plugin,
        "method": method,
    }


# ---------------------------------------------------------------------------
# Error taxonomy — Hub catches these + converts to ToolInvocationResult.
# ---------------------------------------------------------------------------


def meldet_fehler(ergebnis: Any) -> Optional[str]:
    """Grund, wenn ein Werkzeug-Ergebnis einen Fehlschlag meldet — sonst None.

    `{"ok": false, ...}` oder `{"error": "..."}` ohne `ok` (ein Proxy, der `{"error": "nicht erreichbar"}`
    liefert, soll nicht als ok:true gelten).
    """
    if not isinstance(ergebnis, dict):
        return None
    if ergebnis.get("ok") is False or ("ok" not in ergebnis and ergebnis.get("error")):
        grund = ergebnis.get("error") or ergebnis.get("message") or "ok=false"
        return str(grund)
    return None


def tiefe_health(
    besitzer: Any,
    erreichbar: Callable[[], Any],
    probe_name: str,
    probe: Callable[[], Any],
    ttl_sec: float = 60.0,
) -> dict[str, Any]:
    """Health fuer Proxy-Plugins: erreichbar UND liefert Daten.

    Ein reiner Statusaufruf antwortet auch dann, wenn jeder Datenabruf scheitert.

    Stufe 1 `erreichbar()`: wirft sie, ist der Dienst `unreachable`.
    Stufe 2 `probe()` (ein LESENDER Aufruf): wirft sie oder meldet sie einen Fehler, ist das
    Plugin `unhealthy` mit Grund. Ergebnis wird `ttl_sec` lang gehalten — hub__map fragt
    Health bei jedem Aufruf ab, die Probe soll den Dienst nicht im Sekundentakt treffen.
    """
    jetzt = time.monotonic()
    zwischen = getattr(besitzer, "_tiefe_health_cache", None)
    if zwischen and jetzt - zwischen[0] < ttl_sec:
        return dict(zwischen[1])
    try:
        upstream = erreichbar()
    except Exception as exc:  # noqa: BLE001
        out: dict[str, Any] = {"status": "unreachable", "error": str(exc)[:300]}
    else:
        out = {"status": "ok", "upstream": upstream, "probe": probe_name}
        try:
            grund = meldet_fehler(probe())
        except Exception as exc:  # noqa: BLE001
            grund = f"{type(exc).__name__}: {exc}"
        if grund:
            out.update({"status": "unhealthy", "reason": f"{probe_name}: {grund}"[:300]})
    besitzer._tiefe_health_cache = (jetzt, out)
    return dict(out)


class PluginError(Exception):
    """Base class for all plugin-surfaced errors.

    Plugin-authors should raise subclasses of this instead of bare Exception
    so the Hub can differentiate between expected plugin-errors (logged INFO)
    and true crashes (logged ERROR + circuit-breaker trip).
    """


class PluginCallError(PluginError):
    """Raised when a plugin.call() dispatch fails.

    Wraps the original exception so trace-info survives Hub-side handling.

    Attributes:
        plugin: plugin-name (e.g. ``"echo"``)
        method: local tool-name (e.g. ``"say"``)
        cause: the original exception (optional)
    """

    def __init__(
        self, plugin: str, method: str, message: str, cause: Optional[BaseException] = None
    ):
        super().__init__(f"{plugin}.{method}: {message}")
        self.plugin = plugin
        self.method = method
        self.cause = cause


class PluginHealthError(PluginError):
    """Raised when a plugin.health() probe fails or reports unhealthy state."""


# ---------------------------------------------------------------------------
# Result-Wrapper — returned by registry.call().
# ---------------------------------------------------------------------------


@dataclass
class ToolInvocationResult:
    """Structured response for every ``registry.call()`` / ``dispatch()``.

    The Hub ALWAYS produces a ToolInvocationResult even for errors — plugin
    exceptions must never crash the Hub. This is the primary contract of the
    wrap-not-raise error-propagation pattern.

    Attributes:
        status: ``"ok"`` for success, ``"error"`` for any failure mode.
        result: The plugin's return-value on success (any JSON-compatible type).
        error: Human-readable error-message on failure (None on success).
        latency_ms: Wall-clock dispatch latency in milliseconds (float).
        kind: Optional error-kind classifier for caller-branch logic
              (``"plugin_error" | "circuit_open" | "not_found" | ...``).

    Example (success):
        >>> r = ToolInvocationResult(status="ok", result={"echo": "hi"}, latency_ms=0.42)
        >>> r.status, r.result
        ('ok', {'echo': 'hi'})

    Example (error):
        >>> r = ToolInvocationResult(
        ...     status="error", result=None,
        ...     error="ZeroDivisionError: division by zero",
        ...     latency_ms=0.11, kind="plugin_error")
    """

    status: str
    result: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    kind: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Backwards-compatible alias — ``True`` iff status=='ok'."""
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        """Convert to plain dict for MCP-wire transport. Mirrors 1.1 ``dispatch()`` shape."""
        if self.ok:
            return {"ok": True, "result": self.result, "latency_ms": self.latency_ms}
        out = {
            "ok": False,
            "error": self.error or "unknown_error",
            "kind": self.kind or "plugin_error",
            "latency_ms": self.latency_ms,
        }
        # kind=tool_failed: das Plugin hat geantwortet (stdout/stderr/exit_code) —
        # die Details gehen mit, sonst sieht der Aufrufer nur „fehlgeschlagen".
        if self.result is not None:
            out["result"] = self.result
        return out


class KontoFehlt(Exception):
    """Ein Werkzeug braucht ein Konto des Menschen, das (noch) nicht verbunden ist.

    Kein Fehler des Plugins: Der Verteiler (registry.call) macht daraus `kind: "konto_fehlt"` mit dem
    Verbinden-Link im Ergebnis und zählt es nicht gegen den Breaker. MCP-Clients bekommen über die
    App-Werkzeuge eine URL-Elicitation (Fehler -32042, MCP 2025-11-25): der Mensch öffnet den Link, meldet sich
    beim Anbieter an, der Token landet im Tresor — nie im Chat, nie beim Modell.
    """

    def __init__(self, anbieter: str, name: str, link: str, grund: str = "nicht verbunden"):
        self.anbieter = anbieter
        self.name = name
        self.link = link
        self.grund = grund
        super().__init__(f"{name} ist {grund} — bitte einmal verbinden: {link}")

    def als_ergebnis(self) -> dict[str, Any]:
        return {
            "konto_fehlt": True,
            "anbieter": self.anbieter,
            "name": self.name,
            "grund": self.grund,
            "verbinden": self.link,
            "hinweis": f"{self.name} ist {self.grund}. Der Mensch verbindet es einmal über den Link (Anmeldung beim Anbieter).",
        }


# ---------------------------------------------------------------------------
# Tool + Server descriptors (unchanged from 1.1).
# ---------------------------------------------------------------------------


@dataclass
class ToolDescriptor:
    """Describes a tool exposed by a plugin — used for schema-merge in hub__search_tools.

    Fields map 1:1 to MCP-SDK Tool schema (name / description / inputSchema).
    The full-qualified-name ``<plugin>.<tool>`` is computed by the registry.
    """

    name: str
    """Short local name, e.g. ``"say"`` — becomes ``<plugin>.<name>`` at dispatch."""

    description: str
    """Human-readable summary, indexed by hub__search_tools query matching."""

    input_schema: dict[str, Any] = field(default_factory=dict)
    """JSON-Schema for arguments (MCP inputSchema format). Empty = no args."""

    tags: list[str] = field(default_factory=list)
    """Optional tags for future category-filtering (not used in 1.1 skeleton)."""

    meta: Optional[dict[str, Any]] = None
    """MCP-`_meta` des Werkzeugs, z. B. ``{"ui": {"resourceUri": "ui://fyos/..."}}``
    fuer MCP Apps. Ein Werkzeug mit ``meta["ui"]`` wird zusaetzlich als eigenes
    MCP-Werkzeug ``<plugin>__<name>`` angeboten, damit Hosts die Oberflaeche finden."""

    title: Optional[str] = None
    """Anzeigename fuer Hosts (optional)."""

    zeitlimit_s: Optional[float] = None
    """Zeitlimit dieses Werkzeugs in Sekunden (registry.call). ``None`` = Vorgabe des Hubs
    (``registry.AUFRUF_ZEITLIMIT_S``, 120 s; Konfiguration ``aufruf_zeitlimit_s``), ``0`` = kein Limit.
    Werkzeuge, die legitim laenger laufen (werkstatt.ausfuehren bis 30 min, lage.fenster_setzen ~4 min),
    setzen ihr eigenes."""


@dataclass
class ResourceDescriptor:
    """Eine Ressource, die ein Plugin anbietet — fuer MCP Apps die HTML-Oberflaeche
    unter ``ui://…`` mit ``mime_type="text/html;profile=mcp-app"``.

    ``read`` wird bei jedem ``resources/read`` aufgerufen und liefert den Text.
    """

    uri: str
    name: str
    read: Any  # Callable[[], str]
    description: str = ""
    mime_type: str = "text/html;profile=mcp-app"
    meta: Optional[dict[str, Any]] = None


@dataclass
class ServerInfo:
    """Summary struct returned by hub__list_servers."""

    name: str
    description: str
    tool_count: int
    healthy: bool
    version: str = "0.0.0"
    # dritte Spalte neben healthy/aus — das Ziel des Plugins ist nicht
    # erreichbar (DNS/TCP-Probe im Plugin fehlgeschlagen). "unreachable" und
    # "aus" und "healthy" sind drei verschiedene Aussagen; sie in ein bool zu
    # falten war die Ursache des Health-Theaters.
    unreachable: bool = False


# ---------------------------------------------------------------------------
# HubPlugin ABC — extended with init() / shutdown() lifecycle in 1.2.
# ---------------------------------------------------------------------------


class HubPlugin(abc.ABC):
    """Abstract base class every in-process MCP-Hub plugin MUST subclass.

    Subclasses declare a unique ``name`` attribute (class-level) and implement
    the three required lifecycle methods (``register``, ``describe_tools``,
    ``call``). The ``init`` / ``shutdown`` / ``health`` / ``metrics`` hooks
    are optional — sensible no-op defaults are provided.

    Metadata attributes (class-level):
        name         — unique plugin identifier (tool-id prefix).
        description  — short human summary shown in hub__list_servers.
        version      — SemVer string, logged on register() for audit.
    """

    name: str = ""
    """Unique plugin-name. Used as tool-id prefix (<name>.<tool>). Must not be empty."""

    description: str = ""
    """Short human-readable description — shown in hub__list_servers."""

    version: str = "0.0.0"
    """SemVer. Hub logs version on register() for audit-trail."""

    argumente_vertraulich: bool = False
    """True: Argumente der Werkzeuge erscheinen nie im Klartext auf dem Ereignisbus (Zugangsdaten, persoenliche
    Notizen). Gilt unabhaengig von ``event_bus_publisher.skip_arg_publish``, also auch bei zusammengesetzten
    Konfigurationen, die das Plugin nicht kennen."""

    # --- required hooks ----------------------------------------------------

    @abc.abstractmethod
    def register(self) -> None:
        """Called once at hub-startup. Initialize connections, warm caches.

        Must not raise for trivial reasons — use health() to report degraded state.
        A raise here BLOCKS hub startup until fixed (fail-fast policy).
        """

    @abc.abstractmethod
    def describe_tools(self) -> list[ToolDescriptor]:
        """Return ALL tools this plugin exposes. Called once after register(),
        cached by the registry. Must be stable across calls (no dynamic discovery
        in the skeleton — will be extended later for hot-reload)."""

    def describe_resources(self) -> list[ResourceDescriptor]:
        """Ressourcen des Plugins (MCP Apps: ``ui://``-Oberflaechen). Standard: keine."""
        return []

    @abc.abstractmethod
    def call(self, method: str, args: dict[str, Any]) -> Any:
        """Dispatch a tool-call. ``method`` is the local tool-name (without plugin
        prefix). ``args`` is the caller's arguments dict (already json-loaded).

        Plugin is responsible for:
          - validating ``method`` against its exposed tools
          - validating ``args`` against inputSchema
          - raising informative exceptions (caught by hub + converted to
            ToolInvocationResult with status='error')
        """

    # --- optional lifecycle hooks (1.2) ------------------------------------

    def init(self) -> None:
        """One-time extended setup called by the Hub AFTER ``register()``.

        Default: no-op. Override to perform setup that depends on sibling
        plugins already being registered (e.g. cross-plugin routing).
        """
        return None

    def shutdown(self) -> None:
        """Called at Hub shutdown for graceful resource-release.

        Default: no-op. Override to close connections, flush caches, persist
        state. Must not raise — exceptions are logged but swallowed so one
        plugin cannot block the Hub from shutting down.
        """
        return None

    # --- optional HTTP routes -------------------------------------------------

    def routen(self) -> list[Any]:
        """Eigene HTTP-Wege des Plugins (Starlette-``Route``). Default: keine.

        Fuer Dinge, die kein Werkzeug sein sollen, etwa Telemetrie eines Clients, die sonst in jeder
        Werkzeugliste stuende. Jeder Weg muss unter ``/hub/`` liegen, damit Herkunfts- und Anmeldeschutz
        greifen; ein Weg des Kerns gewinnt immer. Der Hub fragt einmal beim Start.
        """
        return []

    # --- optional observability hooks --------------------------------------

    def health(self) -> dict[str, Any]:
        """Default health-check. Override for live connection-probes.

        Returns ``{"ok": True, "status": "healthy"}`` by default.

        Raises:
            PluginHealthError: if the probe fails and the plugin wishes to
                signal unhealthy-state via exception (rather than returning
                ``{"ok": False}``). Both forms are accepted by the Hub.
        """
        return {"ok": True, "status": "healthy"}

    def metrics(self) -> dict[str, Any]:
        """Optionale Kennzahlen für ``/metrics`` (Prometheus-Text, ``mcp_hub.metriken``). Default leer.

        Zahlen (int, float, bool) auf oberster Ebene und eine Ebene tiefer erscheinen als
        ``fyos_plugin_wert{plugin, schluessel}``; Texte werden übergangen. Eigene Reihen mit Labels liefert ein Plugin
        unter dem Schlüssel ``"_proben"``: Liste von ``{"name", "wert", "labels"?, "typ"? (gauge|counter), "hilfe"?}``;
        Namen ohne ``fyos_`` bekommen ``fyos_<plugin>_`` davor. Wird bei jedem Abruf gerufen (Zwischenablage 30 s),
        also ohne teure Abfragen.
        """
        return {}

    # --- optionale Beiträge zu gemeinsamen Ansichten ------------------------

    def zeitplan(self) -> list[dict[str, Any]]:
        """Wiederkehrende Aufgaben des Plugins für die gemeinsame Ansicht ``mcp.zeitplan`` und ``/metrics``.

        Je Eintrag: ``id`` (im Plugin eindeutig), ``name``, ``takt`` (Text wie ``"alle 60 s"`` oder ein
        Cron-Ausdruck); optional ``beschreibung``, ``an`` (bool), ``naechster`` und ``letzter`` (Unix-Sekunden),
        ``letzter_status`` (``"ok"`` oder ``"fehler"``), ``letzter_fehler``, ``quelle`` (Herkunft, wenn nicht das
        Plugin selbst, etwa ``"openclaw"`` für die Cron-Aufträge des Agenten). Antwortet aus dem Speicher (keine
        Netzabfrage); Fehler fängt der Kern ab. Default: keine.

        Fährt das Plugin einen Takt über ``mcp_hub.takt.Waechter`` (Grenzen ``max_pro_tag`` und ``fenster``, Laufprotokoll),
        hängt es ``**waechter.felder(id)`` an den Eintrag: ``max_pro_tag``, ``fenster``, ``ruht``, ``laeufe_heute``,
        ``uebersprungen`` und ``protokoll``. ``felder`` liest nur den Hub-Speicher (Redis oder Prozess), nie ein Fremdsystem.
        """
        return []

    def skills_beitrag(self) -> list[dict[str, Any]]:
        """Skills, die das Plugin mitbringt oder von einem angebundenen Dienst kennt, für ``skills.suchen``/``lesen``.

        Je Eintrag: ``name``, ``beschreibung`` und entweder ``text`` (die ganze SKILL.md) oder ``lesen`` (Aufruf ohne
        Argumente, der sie erst bei ``skills.lesen`` holt); optional ``quelle`` (sonst der Plugin-Name), ``ausloeser``.
        Datei-Quellen des Skills-Plugins haben bei gleichem Namen Vorrang. Antwortet aus dem Speicher. Default: keine.
        """
        return []
