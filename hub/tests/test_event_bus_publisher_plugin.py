"""mcp_hub.tests.test_event_bus_publisher_plugin — fyos-Iter-0136.

Closes Pre-Commit-Drift-Detector-Warning fuer mcp_hub/plugins/event_bus_publisher.py
(Iter-0121 hatte Plugin geshipt, Test-Suite war pending).

Coverage:
  - Plugin-Contract (name/description/version/ToolDescriptors)
  - Lifecycle register() mit DI redis_client_factory
  - Lifecycle register() Redis-Connect-Fail -> degraded
  - register_as_listener attached on_call hook to mock-registry
  - _publish_event happy-path (xadd called with correct stream + entry)
  - _publish_event redacted-skip fuer sensitive plugins (tresor/audit)
  - _publish_event truncates large args
  - _publish_event fail-state (xadd raises -> errors++ + degraded=True)
  - _publish_event auto-recover (degraded=True -> success -> degraded=False)
  - _publish_event skip_self prevents recursive event_bus_publisher events
  - stats() + health() + metrics() Schemas
  - Stream-Topic-Computation: bus.tool.<plugin>.<method>.<ok|fail>
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mcp_hub.audit_log import AuditEvent
from mcp_hub.plugin import ToolDescriptor
from mcp_hub.plugins.event_bus_publisher import (
    DEFAULT_MAXLEN,
    DEFAULT_SAMPLE_MAX_CHARS,
    DEFAULT_SKIP_ARG_PUBLISH,
    DEFAULT_STREAM_PREFIX,
    EventBusPublisherPlugin,
    _truncate,
)


def _make_audit_event(
    plugin_name: str = "repomix",
    tool_name: str = "repomix.pack",
    result_status: str = "ok",
    arguments: str = '{"path": "/repo"}',
    latency_ms: float = 12.5,
    error=None,
) -> AuditEvent:
    return AuditEvent(
        timestamp=100.0,
        session_id="sess-1",
        caller="agent",
        tool_name=tool_name,
        plugin_name=plugin_name,
        arguments=arguments,
        result_status=result_status,
        latency_ms=latency_ms,
        error=error,
    )


def _make_plugin_with_redis(mock_redis):
    plugin = EventBusPublisherPlugin()
    plugin.config = {"redis_client_factory": lambda: mock_redis}
    plugin.register()
    return plugin


# ─── Plugin Contract ────────────────────────────────────────────────────────


def test_plugin_contract():
    p = EventBusPublisherPlugin()
    assert p.name == "event_bus_publisher"
    assert p.version == "0.1.0"
    assert "Redis-Streams" in p.description or "event-bus" in p.description
    p.config = {"redis_client_factory": lambda: MagicMock()}
    p.register()
    tools = p.describe_tools()
    assert len(tools) >= 1
    assert all(isinstance(t, ToolDescriptor) for t in tools)
    assert any(t.name == "stats" for t in tools)


# ─── Lifecycle ──────────────────────────────────────────────────────────────


def test_register_with_di_factory():
    mock_r = MagicMock()
    plugin = EventBusPublisherPlugin()
    plugin.config = {"redis_client_factory": lambda: mock_r}
    plugin.register()
    assert plugin._redis_client is mock_r
    assert plugin._degraded is False
    mock_r.ping.assert_called_once()


def test_register_redis_ping_failure_marks_degraded():
    mock_r = MagicMock()
    mock_r.ping.side_effect = ConnectionError("redis-down")
    plugin = EventBusPublisherPlugin()
    plugin.config = {"redis_client_factory": lambda: mock_r}
    plugin.register()
    assert plugin._redis_client is mock_r
    assert plugin._degraded is True


def test_register_factory_throws_marks_degraded():
    plugin = EventBusPublisherPlugin()

    def _broken_factory():
        raise RuntimeError("connect-broken")

    plugin.config = {"redis_client_factory": _broken_factory}
    plugin.register()
    assert plugin._redis_client is None
    assert plugin._degraded is True


def test_register_reads_custom_config():
    mock_r = MagicMock()
    plugin = EventBusPublisherPlugin()
    plugin.config = {
        "redis_client_factory": lambda: mock_r,
        "stream_prefix": "custom.bus",
        "sample_max_chars": 50,
        "publish_pending": True,
        "skip_arg_publish": ["my_plugin"],
        "maxlen": 5000,
        "skip_self": False,
    }
    plugin.register()
    assert plugin._stream_prefix == "custom.bus"
    assert plugin._sample_max_chars == 50
    assert plugin._publish_pending is True
    assert plugin._skip_arg_publish == ["my_plugin"]
    assert plugin._maxlen == 5000
    assert plugin._skip_self is False


# ─── register_as_listener ────────────────────────────────────────────────────


def test_register_as_listener_attaches_hook():
    plugin = _make_plugin_with_redis(MagicMock())
    mock_registry = MagicMock()
    plugin.register_as_listener(mock_registry)
    mock_registry.register_call_hook.assert_called_once()
    assert plugin._registered_with is mock_registry


def test_register_as_listener_handles_missing_api():
    plugin = _make_plugin_with_redis(MagicMock())
    mock_registry = MagicMock()
    del mock_registry.register_call_hook
    mock_registry.register_call_hook = MagicMock(
        side_effect=AttributeError("no register_call_hook")
    )
    plugin.register_as_listener(mock_registry)


def test_listener_hook_publishes_audit_event():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    captured_hooks = []

    class FakeRegistry:
        def register_call_hook(self, hook):
            captured_hooks.append(hook)

    plugin.register_as_listener(FakeRegistry())
    assert len(captured_hooks) == 1
    hook = captured_hooks[0]
    ev = _make_audit_event()
    hook(ev)
    assert mock_r.xadd.called
    stream_name = mock_r.xadd.call_args[0][0]
    assert stream_name == "bus.tool.repomix.pack.ok"


def test_listener_hook_skips_self():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    captured = []

    class FakeRegistry:
        def register_call_hook(self, hook):
            captured.append(hook)

    plugin.register_as_listener(FakeRegistry())
    self_event = _make_audit_event(plugin_name="event_bus_publisher", tool_name="event_bus_publisher.stats")
    captured[0](self_event)
    assert not mock_r.xadd.called


def test_listener_hook_swallows_exceptions():
    """Hook MUST NEVER raise — Dispatch darf nie blockieren."""
    mock_r = MagicMock()
    mock_r.xadd.side_effect = RuntimeError("bus-down")
    plugin = _make_plugin_with_redis(mock_r)
    captured = []

    class FakeRegistry:
        def register_call_hook(self, hook):
            captured.append(hook)

    plugin.register_as_listener(FakeRegistry())
    captured[0](_make_audit_event())
    assert plugin._publish_errors == 1


# ─── _publish_event Behavior ─────────────────────────────────────────────────


def test_publish_event_writes_correct_stream_and_entry():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    ev = _make_audit_event(plugin_name="repomix", tool_name="repomix.pack", result_status="ok")
    plugin._publish_event(ev)
    assert mock_r.xadd.called
    args, kwargs = mock_r.xadd.call_args
    assert args[0] == "bus.tool.repomix.pack.ok"
    entry = args[1]
    assert entry["plugin"] == "repomix"
    assert entry["method"] == "pack"
    assert entry["status"] == "ok"
    assert "latency_ms" in entry
    assert "args_sample" in entry
    assert kwargs.get("maxlen") == DEFAULT_MAXLEN
    assert plugin._publish_count == 1


def test_publish_event_fail_status_uses_fail_suffix():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    ev = _make_audit_event(result_status="error", error="boom")
    plugin._publish_event(ev)
    args, _ = mock_r.xadd.call_args
    assert args[0].endswith(".fail")
    entry = args[1]
    assert entry["status"] == "error"
    assert "result_sample" in entry
    assert "boom" in entry["result_sample"]


def test_publish_event_redacts_sensitive_plugin_args():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    for sensitive in DEFAULT_SKIP_ARG_PUBLISH:
        if sensitive == "event_bus_publisher":
            continue
        ev = _make_audit_event(
            plugin_name=sensitive,
            tool_name=f"{sensitive}.read_secret",
            arguments='{"secret_name": "vault-token"}',
        )
        mock_r.reset_mock()
        plugin._publish_event(ev)
        args, _ = mock_r.xadd.call_args
        entry = args[1]
        decoded = json.loads(entry["args_sample"])
        assert decoded == {"redacted": True}


def test_publish_event_schwaerzt_selbstauskunft_ohne_liste():
    """argumente_vertraulich am Plugin gilt auch, wenn skip_arg_publish das Plugin nicht nennt."""

    class Tresor:
        argumente_vertraulich = True

    class Offen:
        pass

    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    plugin.register_as_listener(MagicMock(plugins={"tresor": Tresor(), "offen": Offen()}))
    assert "tresor" not in plugin._skip_arg_publish

    plugin._publish_event(_make_audit_event(plugin_name="tresor", tool_name="tresor.hole",
                                            arguments='{"eintrag": "bank"}'))
    assert json.loads(mock_r.xadd.call_args[0][1]["args_sample"]) == {"redacted": True}
    plugin._publish_event(_make_audit_event(plugin_name="offen", tool_name="offen.lies",
                                            arguments='{"pfad": "/a"}'))
    assert "/a" in mock_r.xadd.call_args[0][1]["args_sample"]


def test_publish_event_truncates_large_args():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    big_args = "x" * (DEFAULT_SAMPLE_MAX_CHARS * 3)
    ev = _make_audit_event(arguments=big_args)
    plugin._publish_event(ev)
    args, _ = mock_r.xadd.call_args
    entry = args[1]
    assert len(entry["args_sample"]) == DEFAULT_SAMPLE_MAX_CHARS
    assert entry["args_sample"].endswith("...")


def test_publish_event_xadd_failure_marks_degraded():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    mock_r.xadd.side_effect = ConnectionError("redis-write-fail")
    plugin._publish_event(_make_audit_event())
    assert plugin._publish_errors == 1
    assert plugin._degraded is True
    assert plugin._last_error is not None


def test_publish_event_auto_recovers_from_degraded():
    mock_r = MagicMock()
    plugin = _make_plugin_with_redis(mock_r)
    plugin._degraded = True
    plugin._publish_event(_make_audit_event())
    assert plugin._degraded is False


def test_publish_event_no_redis_client_marks_degraded():
    plugin = EventBusPublisherPlugin()
    plugin.config = {"redis_client_factory": lambda: None}
    plugin.register()
    plugin._redis_client = None
    plugin._publish_event(_make_audit_event())
    assert plugin._degraded is True


# ─── Read-Tools (stats/health/metrics) ──────────────────────────────────────


def test_call_stats_returns_telemetry_dict():
    plugin = _make_plugin_with_redis(MagicMock())
    result = plugin.call("stats", {})
    assert "publish_count" in result
    assert "publish_errors" in result
    assert "degraded" in result
    assert result["stream_prefix"] == DEFAULT_STREAM_PREFIX


def test_call_unknown_method_raises():
    plugin = _make_plugin_with_redis(MagicMock())
    try:
        plugin.call("nonexistent", {})
    except ValueError as e:
        assert "nonexistent" in str(e)
    else:
        raise AssertionError("Expected ValueError for unknown method")


def test_health_reflects_degraded_state():
    plugin = _make_plugin_with_redis(MagicMock())
    h = plugin.health()
    assert h["ok"] is True
    assert h["status"] == "healthy"
    plugin._degraded = True
    h2 = plugin.health()
    assert h2["ok"] is False
    assert h2["status"] == "degraded"


def test_metrics_returns_same_as_stats():
    plugin = _make_plugin_with_redis(MagicMock())
    assert plugin.metrics() == plugin._stats_dict()


# ─── _truncate helper ────────────────────────────────────────────────────────


def test_truncate_preserves_short_strings():
    assert _truncate("hello", 200) == "hello"


def test_truncate_serializes_non_string_to_json():
    out = _truncate({"key": "value"}, 200)
    assert "key" in out
    assert "value" in out


def test_truncate_caps_long_strings_with_ellipsis():
    out = _truncate("a" * 500, 100)
    assert len(out) == 100
    assert out.endswith("...")


def test_truncate_handles_unrepresentable_objects():
    class Weird:
        def __repr__(self):
            return "<Weird>"

    out = _truncate(Weird(), 200)
    assert "Weird" in out
