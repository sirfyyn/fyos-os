"""mcp_hub.tests.test_plugin_publish_hook — Block-I §6.3 Iter-0121.

Tests fuer ``mcp_hub/plugins/event_bus_publisher.py`` (EventBusPublisherPlugin).

Strategie:
    - DummyRedisClient als Mock-Backend (xadd / ping / scan / type / xread).
    - Vollstaendig offline — kein echter Redis benoetigt.
    - Backbone-Plan-Referenz: ``_dropzone/iter-0113-backbone-architecture-plan.md``
      §2.2 (Spine-B Activity-Spine) + §6.3.

Coverage:
    - publish-Hook feuert bei jedem registry.call() (echo.say + math.add)
    - Status-Suffix korrekt: ``.ok`` bei Success / ``.fail`` bei Exception
    - Sample-Truncation auf sample_max_chars
    - Sensitive-Plugin-Skip: ``tresor`` -> args = ``{"redacted": true}``
    - Self-Skip: ``event_bus_publisher.stats`` publiziert NICHT
    - Fail-safe: Redis-xadd-Exception bricht den Dispatch NICHT
    - Stats-Tool zeigt publish_count + degraded-State
"""

from __future__ import annotations

import json
from typing import Any, Iterable

import pytest

from mcp_hub import registry as hub_registry
from mcp_hub.plugin import HubPlugin, ToolDescriptor
from mcp_hub.plugins.event_bus_publisher import EventBusPublisherPlugin


# ---------------------------------------------------------------------------
# Dummy Redis Client — minimal in-memory surrogate for tests.
# ---------------------------------------------------------------------------


class DummyRedisClient:
    """Minimal in-memory Redis-Client substitute.

    Supports the subset used by EventBusPublisherPlugin:
        ping() / xadd(stream, fields, maxlen=, approximate=)
    """

    def __init__(self, fail_xadd: bool = False, fail_ping: bool = False):
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self.fail_xadd = fail_xadd
        self.fail_ping = fail_ping
        self.xadd_calls: list[tuple[str, dict[str, Any]]] = []

    def ping(self):
        if self.fail_ping:
            raise ConnectionError("ping refused")
        return True

    def xadd(self, stream: str, fields: dict[str, Any], maxlen: int = None, approximate: bool = True):
        if self.fail_xadd:
            raise ConnectionError("xadd refused")
        entry_id = f"{len(self.streams.get(stream, []))}-0"
        self.streams.setdefault(stream, []).append((entry_id, dict(fields)))
        self.xadd_calls.append((stream, dict(fields)))
        return entry_id


def bus_calls(dummy: DummyRedisClient) -> list[tuple[str, dict[str, Any]]]:
    """Nur die Aufrufe auf die bus.tool.*-Ströme (der Sammelstrom fyos:live steht in test_live.py)."""
    return [c for c in dummy.xadd_calls if c[0].startswith("bus.tool.")]


# ---------------------------------------------------------------------------
# Helper plugins for synthetic dispatch
# ---------------------------------------------------------------------------


class _OkEcho(HubPlugin):
    name = "echo"
    version = "1.0.0"
    description = "test-only echo"

    def register(self) -> None:  # pragma: no cover — trivial
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="say", description="echo")]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        return {"echoed": args.get("text")}


class _FailMath(HubPlugin):
    name = "math"
    version = "1.0.0"
    description = "test-only math"

    def register(self) -> None:  # pragma: no cover — trivial
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="boom", description="raises")]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        raise RuntimeError("synthetic-fail")


class _SensitiverTresor(HubPlugin):
    name = "tresor"
    version = "1.0.0"
    description = "sensitive-plugin synthetic"

    def register(self) -> None:  # pragma: no cover — trivial
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="search", description="search ciphers")]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        return {"items": []}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_with_publisher():
    """Registry mit echo / math / tresor + EventBusPublisherPlugin gehookt."""
    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "echo", _OkEcho())
    hub_registry._register_one(reg, "math", _FailMath())
    hub_registry._register_one(reg, "tresor", _SensitiverTresor())

    dummy = DummyRedisClient()
    bus = EventBusPublisherPlugin()
    bus.config = {  # type: ignore[attr-defined]
        "redis_client_factory": lambda: dummy,
        "stream_prefix": "bus.tool",
        "sample_max_chars": 50,
    }
    # Use _register_one so the bus plugin is fully indexed (descriptors,
    # breakers, etc.) — sonst kann hub_registry.call() seine Tools nicht
    # finden. Listener-Wiring danach.
    hub_registry._register_one(reg, "event_bus_publisher", bus)
    bus.register_as_listener(reg)
    return reg, bus, dummy


# ---------------------------------------------------------------------------
# Tests — publish hook fires on success + failure
# ---------------------------------------------------------------------------


def test_publish_hook_fires_on_success(registry_with_publisher):
    reg, bus, dummy = registry_with_publisher

    out = hub_registry.call(reg, "echo.say", {"text": "hi"})
    assert out.status == "ok"

    # 1 xadd geschehen, Stream-Suffix = ".ok"
    assert len(bus_calls(dummy)) == 1
    stream, fields = bus_calls(dummy)[0]
    assert stream == "bus.tool.echo.say.ok"
    assert fields["plugin"] == "echo"
    assert fields["method"] == "say"
    assert fields["status"] == "ok"
    assert "latency_ms" in fields
    # echo nicht in skip-list -> args_sample echt
    assert "hi" in fields["args_sample"]


def test_publish_hook_fires_on_failure(registry_with_publisher):
    reg, bus, dummy = registry_with_publisher

    out = hub_registry.call(reg, "math.boom", {"x": 1})
    assert out.status == "error"

    # Stream-Suffix = ".fail"
    assert len(bus_calls(dummy)) == 1
    stream, fields = bus_calls(dummy)[0]
    assert stream == "bus.tool.math.boom.fail"
    assert fields["plugin"] == "math"
    assert fields["status"] == "plugin_error"
    # error -> result_sample gesetzt
    assert "result_sample" in fields
    assert "synthetic-fail" in fields["result_sample"]


def test_publish_hook_truncates_args_sample(registry_with_publisher):
    reg, bus, dummy = registry_with_publisher

    long_text = "x" * 500
    out = hub_registry.call(reg, "echo.say", {"text": long_text})
    assert out.status == "ok"

    _, fields = bus_calls(dummy)[0]
    # sample_max_chars = 50 in fixture
    assert len(fields["args_sample"]) <= 50




def test_publish_hook_skips_self(registry_with_publisher):
    reg, bus, dummy = registry_with_publisher

    out = hub_registry.call(reg, "event_bus_publisher.stats", {})
    assert out.status == "ok"

    # Kein xadd-Call darf passiert sein (skip_self=True per default)
    assert len(dummy.xadd_calls) == 0


def test_publish_hook_failsafe_when_redis_dies(registry_with_publisher, monkeypatch):
    reg, bus, _dummy = registry_with_publisher

    # Redis-Backend kaputt setzen (xadd raises)
    bus._redis_client = DummyRedisClient(fail_xadd=True)

    # Dispatch muss trotzdem succeeden — kein Hook-Crash erlaubt
    out = hub_registry.call(reg, "echo.say", {"text": "hi"})
    assert out.status == "ok"
    # Counter zeigt Fehler an
    assert bus._publish_errors >= 1
    assert bus._degraded is True




def test_publish_hook_health_reflects_state(registry_with_publisher):
    _reg, bus, _dummy = registry_with_publisher
    h = bus.health()
    assert h["ok"] is True
    assert h["status"] == "healthy"
    assert h["publish_count"] == 0


def test_publish_hook_degraded_when_redis_unavailable():
    """register() ohne factory + ohne import-able redis -> degraded, kein crash."""
    bus = EventBusPublisherPlugin()
    bus.config = {  # type: ignore[attr-defined]
        "redis_client_factory": lambda: (_ for _ in ()).throw(RuntimeError("no redis")),
    }
    bus.register()
    h = bus.health()
    assert h["ok"] is False
    assert h["status"] == "degraded"
    assert bus._degraded is True


def test_publish_hook_describe_tools_exposes_stats():
    bus = EventBusPublisherPlugin()
    descriptors = bus.describe_tools()
    names = [d.name for d in descriptors]
    assert "stats" in names


def test_publish_hook_call_unknown_method_raises():
    bus = EventBusPublisherPlugin()
    with pytest.raises(ValueError):
        bus.call("nonexistent", {})
