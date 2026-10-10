"""mcp_hub.tests.test_plugin_protocol — S-MCP-HUB.1.2 Gate tests.

Covers:
    - Plugin-Protocol metadata (name/version/description/tags)
    - Lifecycle hooks (init / shutdown) + order
    - Error-taxonomy (PluginError / PluginCallError / PluginHealthError)
    - ToolInvocationResult wrap-not-raise semantics
    - Circuit-breaker state-machine (CLOSED → OPEN → HALF_OPEN → CLOSED)
    - math-plugin happy + crash paths
    - Integration: math.divide by zero does NOT crash the Hub + eventually
      fast-fails via circuit_open.
    - health_check_all() aggregation
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mcp_hub import config as hub_config
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.circuit_breaker import (
    BreakerRegistry,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from mcp_hub.plugin import (
    HubPlugin,
    PluginCallError,
    PluginError,
    PluginHealthError,
    ToolDescriptor,
    ToolInvocationResult,
)
from mcp_hub.plugins.example_math import MathPlugin


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _build_hub_with_examples():
    """Rebuild hub with the two reference plugins before each test."""
    hub_server.build_app(str(CONFIG_PATH))
    yield


@pytest.fixture
def fresh_registry():
    """Standalone registry with only the MathPlugin — full control for breaker tests."""
    reg = hub_registry.PluginRegistry()
    # Tight breaker config so tests finish quickly.
    reg.breakers.default_config = CircuitBreakerConfig(
        failure_threshold=5,
        timeout_sec=0.05,  # 50ms — tests can wait this out
        half_open_max_calls=3,
        enabled=True,
    )
    hub_registry._register_one(reg, "math", MathPlugin())
    return reg


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


def test_plugin_metadata_fields_present_on_math():
    p = MathPlugin()
    assert p.name == "math"
    assert p.version and isinstance(p.version, str)
    assert p.description and "arithmetic" in p.description.lower()


def test_plugin_metadata_fields_present_on_echo():
    from mcp_hub.plugins.example_echo import EchoPlugin

    p = EchoPlugin()
    assert p.name == "echo"
    assert p.version == "0.1.0"
    assert p.description


def test_tool_descriptor_tags_round_trip():
    tools = MathPlugin().describe_tools()
    tags = {t.name: t.tags for t in tools}
    assert "reference" in tags["add"]
    assert "crash-test" in tags["divide"]


# ---------------------------------------------------------------------------
# Lifecycle tests — init / shutdown hooks exist + ordered
# ---------------------------------------------------------------------------


def test_init_and_shutdown_are_called_in_order():
    order: list[str] = []

    class _Trace(HubPlugin):
        name = "trace"
        version = "0.0.1"
        description = "trace"

        def register(self):
            order.append("register")

        def init(self):
            order.append("init")

        def describe_tools(self):
            order.append("describe")
            return [ToolDescriptor(name="noop", description="noop")]

        def call(self, method, args):
            return {}

        def shutdown(self):
            order.append("shutdown")

    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "trace", _Trace())
    assert order == ["register", "init", "describe"]

    hub_registry.shutdown_registry(reg)
    assert order[-1] == "shutdown"


def test_shutdown_swallows_plugin_errors():
    class _BrokenShutdown(HubPlugin):
        name = "bad_shutdown"
        version = "0.0.1"
        description = "bad_shutdown"

        def register(self): ...
        def describe_tools(self):
            return []
        def call(self, method, args):
            return None
        def shutdown(self):
            raise RuntimeError("boom")

    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "bad_shutdown", _BrokenShutdown())
    # Must NOT raise — exception is swallowed + logged.
    hub_registry.shutdown_registry(reg)


# ---------------------------------------------------------------------------
# Error taxonomy tests
# ---------------------------------------------------------------------------


def test_plugin_error_hierarchy():
    assert issubclass(PluginCallError, PluginError)
    assert issubclass(PluginHealthError, PluginError)
    assert issubclass(PluginError, Exception)


def test_plugin_call_error_retains_cause():
    cause = ValueError("root")
    pce = PluginCallError("math", "divide", "bad", cause=cause)
    assert pce.plugin == "math"
    assert pce.method == "divide"
    assert pce.cause is cause
    assert "math.divide" in str(pce)


# ---------------------------------------------------------------------------
# ToolInvocationResult tests
# ---------------------------------------------------------------------------


def test_tool_invocation_result_success_to_dict():
    r = ToolInvocationResult(status="ok", result={"x": 1}, latency_ms=0.5)
    assert r.ok is True
    d = r.to_dict()
    assert d["ok"] is True
    assert d["result"] == {"x": 1}
    assert d["latency_ms"] == 0.5


def test_tool_invocation_result_error_to_dict():
    r = ToolInvocationResult(
        status="error", error="ZeroDivisionError", latency_ms=0.1, kind="plugin_error"
    )
    assert r.ok is False
    d = r.to_dict()
    assert d["ok"] is False
    assert d["error"] == "ZeroDivisionError"
    assert d["kind"] == "plugin_error"


# ---------------------------------------------------------------------------
# Circuit-breaker unit tests
# ---------------------------------------------------------------------------


def test_breaker_starts_closed_and_allows_calls():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=3, timeout_sec=0.01))
    assert cb.state is CircuitState.CLOSED
    assert cb.allow_call() is True


def test_breaker_trips_open_after_threshold_failures():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=3, timeout_sec=10))
    for _ in range(3):
        cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_call() is False


def test_breaker_resets_failure_count_on_success():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=3, timeout_sec=10))
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    # Still CLOSED, counter reset.
    assert cb.state is CircuitState.CLOSED
    # Need 3 more consecutive fails to trip.
    cb.record_failure()
    cb.record_failure()
    assert cb.state is CircuitState.CLOSED
    cb.record_failure()
    assert cb.state is CircuitState.OPEN


def test_breaker_transitions_to_half_open_after_timeout():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=2, timeout_sec=0.02))
    cb.record_failure()
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    time.sleep(0.04)
    # Accessing .state auto-transitions.
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow_call() is True


def test_breaker_half_open_closes_after_successes():
    cb = CircuitBreaker(
        "t", CircuitBreakerConfig(failure_threshold=2, timeout_sec=0.02, half_open_max_calls=2)
    )
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.04)
    assert cb.state is CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state is CircuitState.HALF_OPEN  # 1 of 2
    cb.record_success()
    assert cb.state is CircuitState.CLOSED


def test_breaker_half_open_reopens_on_failure():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=2, timeout_sec=0.02))
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.04)
    _ = cb.state  # trigger HALF_OPEN
    cb.record_failure()
    assert cb.state is CircuitState.OPEN


def test_breaker_force_reset():
    cb = CircuitBreaker("t", CircuitBreakerConfig(failure_threshold=1, timeout_sec=60))
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    cb.force_reset()
    assert cb.state is CircuitState.CLOSED


def test_breaker_disabled_is_noop():
    cb = CircuitBreaker(
        "t", CircuitBreakerConfig(failure_threshold=1, timeout_sec=10, enabled=False)
    )
    cb.record_failure()
    cb.record_failure()
    assert cb.allow_call() is True
    assert cb.state is CircuitState.CLOSED


def test_breaker_registry_isolates_plugins():
    breg = BreakerRegistry(default_config=CircuitBreakerConfig(failure_threshold=1))
    a = breg.get("a")
    b = breg.get("b")
    a.record_failure()
    assert a.state is CircuitState.OPEN
    assert b.state is CircuitState.CLOSED  # isolated
    assert breg.get("a") is a  # same instance on re-get


# ---------------------------------------------------------------------------
# math-plugin happy + crash
# ---------------------------------------------------------------------------


def test_math_add_happy_path():
    result = hub_server.hub__call_tool(tool="math.add", arguments={"a": 2, "b": 3})
    assert result["ok"] is True
    assert result["result"] == {"sum": 5.0}
    assert result["latency_ms"] >= 0.0


def test_math_divide_happy_path():
    result = hub_server.hub__call_tool(tool="math.divide", arguments={"a": 10, "b": 4})
    assert result["ok"] is True
    assert result["result"] == {"quotient": 2.5}


def test_math_divide_by_zero_does_not_crash_hub():
    """Hub must survive a plugin-crash — returns error-dict instead of raising."""
    result = hub_server.hub__call_tool(tool="math.divide", arguments={"a": 1, "b": 0})
    assert result["ok"] is False
    assert result["kind"] == "plugin_error"
    assert "ZeroDivisionError" in result["error"] or "division" in result["error"].lower()


# ---------------------------------------------------------------------------
# Registry.call() circuit-breaker integration
# ---------------------------------------------------------------------------


def test_registry_call_returns_tool_invocation_result(fresh_registry):
    res = hub_registry.call(fresh_registry, "math.add", {"a": 1, "b": 2})
    assert isinstance(res, ToolInvocationResult)
    assert res.status == "ok"
    assert res.result == {"sum": 3.0}


def test_registry_call_wraps_plugin_crash(fresh_registry):
    res = hub_registry.call(fresh_registry, "math.divide", {"a": 1, "b": 0})
    assert res.status == "error"
    assert res.kind == "plugin_error"
    assert "ZeroDivision" in (res.error or "")
    # Breaker recorded one failure.
    assert fresh_registry.breakers.get("math").snapshot()["consecutive_failures"] == 1


def test_registry_call_trips_breaker_after_5_failures(fresh_registry):
    for _ in range(5):
        res = hub_registry.call(fresh_registry, "math.divide", {"a": 1, "b": 0})
        assert res.status == "error"
    # Next call must be fast-failed by breaker (no plugin invocation).
    res = hub_registry.call(fresh_registry, "math.divide", {"a": 1, "b": 0})
    assert res.status == "error"
    assert res.kind == "circuit_open"
    assert "circuit open" in (res.error or "").lower()


def test_registry_call_recovers_via_half_open(fresh_registry):
    # Trip the breaker first.
    for _ in range(5):
        hub_registry.call(fresh_registry, "math.divide", {"a": 1, "b": 0})
    assert fresh_registry.breakers.get("math").state is CircuitState.OPEN

    # Wait for the 50ms OPEN-timeout configured in fresh_registry.
    time.sleep(0.08)

    # Trip into HALF_OPEN + do 3 consecutive successes on math.add.
    res1 = hub_registry.call(fresh_registry, "math.add", {"a": 1, "b": 1})
    assert res1.status == "ok"
    res2 = hub_registry.call(fresh_registry, "math.add", {"a": 2, "b": 2})
    assert res2.status == "ok"
    res3 = hub_registry.call(fresh_registry, "math.add", {"a": 3, "b": 3})
    assert res3.status == "ok"

    # Breaker should now be CLOSED again.
    assert fresh_registry.breakers.get("math").state is CircuitState.CLOSED


def test_registry_call_latency_tracked(fresh_registry):
    hub_registry.call(fresh_registry, "math.add", {"a": 1, "b": 1})
    hub_registry.call(fresh_registry, "math.add", {"a": 2, "b": 2})
    assert fresh_registry.call_counts["math.add"] == 2
    assert fresh_registry.latency_totals_ms["math.add"] >= 0.0


def test_registry_call_unknown_tool_no_breaker_trip(fresh_registry):
    res = hub_registry.call(fresh_registry, "ghost.foo", {})
    assert res.status == "error"
    assert res.kind == "not_found"
    # Unknown tools don't touch any breaker.
    assert fresh_registry.breakers.get("math").snapshot()["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# health_check_all aggregation
# ---------------------------------------------------------------------------


def test_health_check_all_covers_every_plugin():
    reg = hub_server.get_registry()
    out = reg.health_check_all()
    assert set(out.keys()) >= {"echo", "math"}
    assert out["echo"]["ok"] is True
    assert out["math"]["ok"] is True
    # Each entry must include a breaker-snapshot.
    assert "breaker" in out["echo"]
    assert out["echo"]["breaker"]["name"] == "echo"


def test_health_check_all_catches_plugin_exceptions():
    class _BadHealth(HubPlugin):
        name = "bad_health"
        version = "0.0.1"
        description = "bad_health"

        def register(self): ...
        def describe_tools(self):
            return []
        def call(self, method, args):
            return None
        def health(self):
            raise RuntimeError("probe failed")

    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "bad_health", _BadHealth())
    out = reg.health_check_all()
    assert out["bad_health"]["ok"] is False
    assert "probe failed" in out["bad_health"]["error"]


# ---------------------------------------------------------------------------
# Config: circuit_breaker section loads + defaults
# ---------------------------------------------------------------------------




def test_config_missing_circuit_breaker_section_ok(tmp_path):
    minimal = tmp_path / "min.yaml"
    minimal.write_text("host: 0.0.0.0\nport: 9000\nplugins: []\n")
    cfg = hub_config.load_config(minimal)
    assert cfg.circuit_breaker == {}
