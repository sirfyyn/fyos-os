"""mcp_hub.plugins.event_bus_publisher — Event-Bus für Werkzeugaufrufe.

Publiziert pro Hub-Werkzeugaufruf ein Event auf einen Redis-Stream
(``bus.tool.<plugin>.<method>.<status>``). Andere Dienste (Live-Feeds, Mustererkennung) lesen sie per XREAD.
Ohne ``REDIS_URL`` landen die Ereignisse im Speicher des Prozesses (``mcp_hub.kv``) — nützlich zum Ausprobieren,
nicht zum Weiterverarbeiten.

Pattern:
    - Subscriber zum ``PluginRegistry.on_call``-Hook (wie ``mcp_hub.plugins.audit``). Verändert den
      Dispatch-Pfad NICHT.
    - Fail-safe: Redis unerreichbar → log + degraded-state, der Plugin-Call läuft weiter.
    - Sample-Truncation auf ``sample_max_chars`` (Default 200) — verhindert, dass grosse Bulk-Payloads oder
      Geheimnisse in den Stream landen.
    - Sensitive-Plugin-Skip: Plugins in ``skip_arg_publish`` und Plugins mit ``argumente_vertraulich = True``
      (Selbstauskunft, gilt ohne Konfiguration) bekommen ein Event mit args=``{"redacted": true}`` statt des
      args-Samples.

Stream-Topics sind ``bus.tool.<plugin>.<method>.<ok|fail>``.

Config (from Hub YAML ``plugins[].config``):
    enabled            bool, Default ``True``
    redis_url          Default: Umgebung ``REDIS_URL``; leer = Speicher des Prozesses
    stream_prefix      Default ``"bus.tool"``
    sample_max_chars   int, Default 200
    publish_pending    bool, Default False — pre-call ``.pending`` Event publizieren?
    skip_arg_publish   list[str], Default ``["audit","event_bus_publisher"]``
    maxlen             int, Default 1000 — XADD MAXLEN ~Trim-Cap pro Stream
    skip_self          bool, Default True — keine event_bus_publisher.* Calls publizieren
    live               bool, Default True — zusaetzlich ein kompaktes Ereignis in den Sammelstrom
                       ``fyos:live``: nur Name/Plugin/Status/Dauer/Aufrufer, KEINE Argumente (siehe _livestrom.py)
    live_maxlen        int, Default 5000

Read-Tools (passive, fuer Diagnose):
    event_bus_publisher.stats()      — Counter (publish_count, errors, last_ts)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from .. import kv
from ..plugin import HubPlugin, ToolDescriptor
from . import _livestrom

logger = logging.getLogger(__name__)

# Default-Config
DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "")
DEFAULT_STREAM_PREFIX = "bus.tool"
DEFAULT_SAMPLE_MAX_CHARS = 200
DEFAULT_MAXLEN = 1000
# Sensitive plugins where args MUST NOT be published verbatim (Audit-Selbstschleife, Zugangsdaten-Plugins).
DEFAULT_SKIP_ARG_PUBLISH = ["audit", "event_bus_publisher"]


def _anzeige(url: str) -> str:
    """Adresse ohne Zugangsdaten für Status und Health ("" = Speicher des Prozesses)."""
    if not url:
        return "(speicher)"
    return url.split("@", 1)[-1] if "@" in url else url


def _truncate(value: Any, max_chars: int) -> str:
    """Best-effort string-truncation for stream-safe publishing."""
    try:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        value = repr(value)
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


class EventBusPublisherPlugin(HubPlugin):
    """Subscribes to ``PluginRegistry.on_call`` and publishes ``bus.tool.*`` events."""

    name = "event_bus_publisher"
    description = (
        "Publishes hub tool-calls onto the Redis-Streams event-bus "
        "(bus.tool.<plugin>.<method>.<ok|fail>) for live feeds and pattern detection. "
        "Fail-safe; never blocks dispatch."
    )
    version = "0.1.0"

    def __init__(self) -> None:
        self._redis_client: Optional[Any] = None
        self._redis_url: str = DEFAULT_REDIS_URL
        self._stream_prefix: str = DEFAULT_STREAM_PREFIX
        self._sample_max_chars: int = DEFAULT_SAMPLE_MAX_CHARS
        self._publish_pending: bool = False
        self._skip_arg_publish: list[str] = list(DEFAULT_SKIP_ARG_PUBLISH)
        self._maxlen: int = DEFAULT_MAXLEN
        self._skip_self: bool = True
        self._live: bool = True
        self._live_maxlen: int = _livestrom.MAXLEN
        self._registered_with: Optional[Any] = None

        # Telemetry
        self._publish_count: int = 0
        self._publish_errors: int = 0
        self._last_publish_ts: float = 0.0
        self._last_error: Optional[str] = None
        self._degraded: bool = False
        self._live_count: int = 0
        self._live_errors: int = 0

    # --- lifecycle ---------------------------------------------------------

    def register(self) -> None:
        cfg = getattr(self, "config", {}) or {}
        self._redis_url = str(cfg.get("redis_url") or DEFAULT_REDIS_URL)
        self._stream_prefix = str(cfg.get("stream_prefix", DEFAULT_STREAM_PREFIX))
        self._sample_max_chars = int(cfg.get("sample_max_chars", DEFAULT_SAMPLE_MAX_CHARS))
        self._publish_pending = bool(cfg.get("publish_pending", False))
        skip = cfg.get("skip_arg_publish", DEFAULT_SKIP_ARG_PUBLISH)
        if isinstance(skip, list):
            self._skip_arg_publish = [str(s) for s in skip]
        self._maxlen = int(cfg.get("maxlen", DEFAULT_MAXLEN))
        self._skip_self = bool(cfg.get("skip_self", True))
        self._live = bool(cfg.get("live", True))
        self._live_maxlen = int(cfg.get("live_maxlen", _livestrom.MAXLEN))

        # Redis-Connect ist best-effort; degraded falls Redis nicht erreichbar.
        # Test-Hook: ``cfg["redis_client_factory"]`` erlaubt DI eines Mocks.
        factory = cfg.get("redis_client_factory")
        try:
            if factory is not None:
                self._redis_client = factory()
            else:
                self._redis_client = kv.klient(self._redis_url)
            # Best-effort Ping um Reachability-State zu kennen
            try:
                self._redis_client.ping()
                self._degraded = False
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "event_bus_publisher: Redis ping failed (%s) — running degraded", exc
                )
                self._degraded = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event_bus_publisher: Redis-Connect fehlgeschlagen (%s) — degraded", exc
            )
            self._redis_client = None
            self._degraded = True

    def init(self) -> None:
        """No-op — listener wird in ``register_as_listener`` angehaengt."""
        return None

    def register_as_listener(self, registry: Any) -> None:
        """Attach this plugin to a ``PluginRegistry`` via its ``on_call`` hook.

        Called from ``mcp_hub.server.build_app()`` after build_registry(). Safe
        to re-call — registry de-dupes hooks.
        """
        self._registered_with = registry

        def _on_call(ev: Any) -> None:
            # ev: AuditEvent (mcp_hub.audit_log) — has tool_name / plugin_name
            # / arguments (json-str) / result_status / latency_ms / error.
            if self._skip_self and getattr(ev, "plugin_name", "") == self.name:
                return
            try:
                self._publish_event(ev)
            except Exception as exc:  # noqa: BLE001
                # Fail-safe: ein Hook-Fehler darf NIE den Dispatch blockieren.
                self._publish_errors += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.debug("event_bus_publisher: publish failed: %s", exc)

        try:
            registry.register_call_hook(_on_call)
        except AttributeError:
            logger.warning("event_bus_publisher: registry has no register_call_hook API")

    # --- describe + call ---------------------------------------------------

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="stats",
                description=(
                    "Event-bus publisher telemetry: publish-count, errors, "
                    "degraded-state, last-publish-timestamp."
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                tags=["event-bus", "observability", "read"],
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if method == "stats":
            return self._stats_dict()
        raise ValueError(f"EventBusPublisherPlugin has no tool {method!r}")

    def health(self) -> dict[str, Any]:
        ok = (self._redis_client is not None) and (not self._degraded)
        return {
            "ok": ok,
            "status": "healthy" if ok else "degraded",
            "redis_url": _anzeige(self._redis_url),
            "publish_count": self._publish_count,
            "publish_errors": self._publish_errors,
            "degraded": self._degraded,
        }

    def metrics(self) -> dict[str, Any]:
        return self._stats_dict()

    # --- internal ----------------------------------------------------------

    def _stats_dict(self) -> dict[str, Any]:
        return {
            "publish_count": self._publish_count,
            "publish_errors": self._publish_errors,
            "live_count": self._live_count,
            "live_errors": self._live_errors,
            "last_publish_ts": self._last_publish_ts,
            "last_error": self._last_error,
            "degraded": self._degraded,
            "redis_url": _anzeige(self._redis_url),
            "stream_prefix": self._stream_prefix,
            "sample_max_chars": self._sample_max_chars,
            "skip_arg_publish": list(self._skip_arg_publish),
        }

    def _vertraulich(self, plugin_name: str) -> bool:
        """Selbstauskunft des Plugins (``HubPlugin.argumente_vertraulich``); scheitert die Abfrage, gilt es als vertraulich."""
        plugins = getattr(self._registered_with, "plugins", None)
        if not isinstance(plugins, dict):
            return False
        try:
            return bool(getattr(plugins.get(plugin_name), "argumente_vertraulich", False))
        except Exception:  # noqa: BLE001 — ein seltsames Plugin-Objekt schwaerzt lieber
            return True

    def _publish_event(self, ev: Any) -> None:
        """Publiziere ein einzelnes ``AuditEvent`` auf den passenden Stream."""
        if self._redis_client is None:
            self._degraded = True
            return

        plugin_name = str(getattr(ev, "plugin_name", "") or "unknown")
        tool_name = str(getattr(ev, "tool_name", "") or "unknown")
        if tool_name in _livestrom.LEISE:
            return  # Abfragen der Live-Ansicht selbst: weder Bus noch Sammelstrom (kaeme im Takt von Sekunden)
        # tool_name ist FQTN (``"<plugin>.<method>"``) — extrahiere method
        method = tool_name.split(".", 1)[1] if "." in tool_name else tool_name
        result_status = str(getattr(ev, "result_status", "unknown") or "unknown")
        suffix = "ok" if result_status == "ok" else "fail"
        stream = f"{self._stream_prefix}.{plugin_name}.{method}.{suffix}"

        # Args: Sensitive-Plugin (Liste oder Selbstauskunft argumente_vertraulich) → redacted, sonst truncate.
        if plugin_name in self._skip_arg_publish or self._vertraulich(plugin_name):
            args_field = json.dumps({"redacted": True})
        else:
            args_field = _truncate(getattr(ev, "arguments", ""), self._sample_max_chars)

        # Result-Sample: gibt es kein "result" am AuditEvent — wir truncaten
        # error-Feld bei Fail, sonst skip (Schema-Disziplin: Stream haelt
        # nur tool-id + Status + Latency + sample, keine vollen Payloads).
        latency_ms = float(getattr(ev, "latency_ms", 0.0) or 0.0)
        error_field = getattr(ev, "error", None)
        result_sample: Optional[str] = None
        if error_field:
            result_sample = _truncate(error_field, self._sample_max_chars)

        entry = {
            "ts": str(int(time.time())),
            "plugin": plugin_name,
            "method": method,
            "status": result_status,
            "latency_ms": f"{latency_ms:.3f}",
            "args_sample": args_field,
        }
        if result_sample is not None:
            entry["result_sample"] = result_sample

        # Sammelstrom fuer die Live-Ansicht ZUERST und fuer sich: sein Ausfall aendert nichts am Bus-Zustand.
        if self._live:
            try:
                kompakt = _livestrom.eintrag_aus_audit(ev)
                if kompakt is not None:
                    self._redis_client.xadd(
                        _livestrom.STROM, kompakt, maxlen=self._live_maxlen, approximate=True
                    )
                    self._live_count += 1
            except Exception as exc:  # noqa: BLE001
                self._live_errors += 1
                logger.debug("event_bus_publisher: Sammelstrom xadd failed: %s", exc)

        try:
            self._redis_client.xadd(stream, entry, maxlen=self._maxlen, approximate=True)
            self._publish_count += 1
            self._last_publish_ts = time.time()
            # Auto-Recover: erfolgreicher Publish → degraded-flag clearen
            if self._degraded:
                self._degraded = False
        except Exception as exc:  # noqa: BLE001
            self._publish_errors += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._degraded = True
            logger.debug("event_bus_publisher: xadd failed for %s: %s", stream, exc)
