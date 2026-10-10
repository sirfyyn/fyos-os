"""mcp_hub.tests.test_audit — S-MCP-HUB.1.3 Gate tests.

Covers:
    - AuditEvent dataclass serialization/deserialization
    - AuditLogger.log_event with dummy Qdrant client
    - AuditLogger.semantic_recall returns mock-embedded results
    - AuditLogger graceful-degradation when Qdrant is unreachable
    - AuditLogger filter-based recall (caller, plugin_name)
    - Hub integration: echo.say dispatch produces an audit-event
    - 4th meta-tool hub__audit_log returns the event
    - Registry on_call hook fan-out + exception isolation
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.audit_log import (
    DEFAULT_EMBEDDING_DIM,
    AuditEvent,
    AuditLogger,
    build_event_from_call,
)
from mcp_hub.plugin import ToolInvocationResult
from mcp_hub.plugins.audit import AuditPlugin

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"


# ---------------------------------------------------------------------------
# Dummy Qdrant client — in-memory surrogate for integration tests.
# ---------------------------------------------------------------------------


class _DummyCollections:
    def __init__(self, names):
        self.collections = [type("C", (), {"name": n})() for n in names]


class _DummyPoint:
    def __init__(self, point_id, vector, payload):
        self.id = point_id
        self.vector = vector
        self.payload = payload


class _DummyHit:
    def __init__(self, point):
        self.payload = point.payload
        self.score = 1.0


class DummyQdrantClient:
    """Minimal in-memory substitute for QdrantClient used in tests."""

    def __init__(self):
        self.collections: dict[str, list[_DummyPoint]] = {}

    # ---- collection lifecycle ----
    def get_collections(self):
        return _DummyCollections(list(self.collections.keys()))

    def create_collection(self, collection_name, vectors_config=None, **kwargs):
        self.collections.setdefault(collection_name, [])

    def get_collection(self, name):
        pts = self.collections.get(name, [])
        return type("Info", (), {"points_count": len(pts)})()

    # ---- writes ----
    def upsert(self, collection_name, points):
        dest = self.collections.setdefault(collection_name, [])
        for p in points:
            if isinstance(p, dict):
                dest.append(_DummyPoint(p["id"], p["vector"], p["payload"]))
            else:
                dest.append(_DummyPoint(p.id, p.vector, p.payload))

    # ---- reads ----
    def search(self, collection_name, query_vector, limit=10, query_filter=None):
        points = self.collections.get(collection_name, [])
        # Trivial: return last N matching filter (no real vector math — tests
        # only check that the path works).
        filtered = [p for p in points if self._match_filter(p, query_filter)]
        return [_DummyHit(p) for p in filtered[-limit:]][::-1]

    def scroll(
        self,
        collection_name,
        limit=10,
        scroll_filter=None,
        with_payload=True,
        with_vectors=False,
        order_by=None,
    ):
        points = self.collections.get(collection_name, [])
        filtered = [p for p in points if self._match_filter(p, scroll_filter)]
        if order_by is not None:
            absteigend = "desc" in str(getattr(order_by, "direction", "")).lower()
            filtered.sort(key=lambda p: p.payload.get(order_by.key, 0), reverse=absteigend)
        return filtered[:limit], None

    def create_payload_index(self, collection_name, field_name, field_schema=None):
        self.indizes = getattr(self, "indizes", set()) | {field_name}

    def count(self, collection_name, count_filter=None, exact=True):
        points = self.collections.get(collection_name, [])
        return type(
            "R", (), {"count": sum(1 for p in points if self._match_filter(p, count_filter))}
        )()

    def facet(self, collection_name, key, facet_filter=None, limit=10, exact=True):
        zaehler: dict = {}
        for p in self.collections.get(collection_name, []):
            if self._match_filter(p, facet_filter):
                zaehler[p.payload.get(key)] = zaehler.get(p.payload.get(key), 0) + 1
        hits = [type("H", (), {"value": k, "count": v})() for k, v in zaehler.items()]
        return type("F", (), {"hits": sorted(hits, key=lambda h: -h.count)[:limit]})()

    @staticmethod
    def _match_filter(point, flt):
        if flt is None:
            return True
        # Handle both real qmodels.Filter and our dict-variant (never hits in tests).
        must = getattr(flt, "must", None)
        if not must:
            return True
        for cond in must:
            key = getattr(cond, "key", None)
            bereich = getattr(cond, "range", None)
            if bereich is not None:
                gte = getattr(bereich, "gte", None)
                if gte is not None and float(point.payload.get(key, 0)) < gte:
                    return False
                continue
            match = getattr(cond, "match", None)
            value = getattr(match, "value", None) if match else None
            if point.payload.get(key) != value:
                return False
        return True


def _fake_embedder(text: str):
    """Deterministic embedding for tests — length-based 768-dim vector."""
    base = float(len(text) % 100) / 100.0
    return [base] * DEFAULT_EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_logger():
    """AuditLogger wired to DummyQdrantClient + fake embedder — fully offline."""
    client = DummyQdrantClient()
    logger = AuditLogger(
        qdrant_url="http://dummy",
        embed_url="http://dummy",
        collection_name="test_audit",
        qdrant_client_factory=lambda: client,
        embedder=_fake_embedder,
    )
    logger.init_collection()
    return logger, client


@pytest.fixture
def hub_with_dummy_audit(monkeypatch):
    """Rebuild Hub + inject dummy Qdrant into the audit plugin's logger.

    We patch the AuditPlugin.register() to swap in DummyQdrantClient factory +
    fake embedder so the whole integration runs offline.
    """
    client = DummyQdrantClient()

    original_register = AuditPlugin.register

    def patched_register(self):
        cfg = dict(getattr(self, "config", {}) or {})
        cfg["qdrant_client_factory"] = lambda: client
        cfg["embedder"] = _fake_embedder
        cfg["collection_name"] = "test_audit"  # override YAML default
        self.config = cfg  # type: ignore[attr-defined]
        original_register(self)

    monkeypatch.setattr(AuditPlugin, "register", patched_register)
    hub_server.build_app(str(CONFIG_PATH))
    yield client


# ---------------------------------------------------------------------------
# AuditEvent serialization
# ---------------------------------------------------------------------------


def test_audit_event_to_payload_and_from_payload_roundtrip():
    ev = AuditEvent(
        timestamp=1234.5,
        session_id="s1",
        caller="agent",
        tool_name="echo.say",
        plugin_name="echo",
        arguments='{"text": "hi"}',
        result_status="ok",
        latency_ms=1.2,
        error=None,
    )
    payload = ev.to_payload()
    assert payload["tool_name"] == "echo.say"
    assert payload["caller"] == "agent"
    ev2 = AuditEvent.from_payload(payload)
    assert ev2.tool_name == ev.tool_name
    assert ev2.latency_ms == pytest.approx(1.2)
    assert ev2.embedding_vector is None  # not round-tripped via payload


def test_audit_event_embedding_text_includes_error():
    ev = AuditEvent(
        timestamp=0,
        session_id="s",
        caller="c",
        tool_name="math.divide",
        plugin_name="math",
        arguments='{"a":1,"b":0}',
        result_status="plugin_error",
        latency_ms=0.1,
        error="ZeroDivisionError",
    )
    txt = ev.embedding_text()
    assert "math.divide" in txt
    assert "ZeroDivisionError" in txt


def test_build_event_from_call_adapts_tool_invocation_result():
    tir = ToolInvocationResult(status="ok", result={"x": 1}, latency_ms=0.42)
    ev = build_event_from_call("echo.say", {"text": "hi"}, tir, caller="max")
    assert ev.tool_name == "echo.say"
    assert ev.plugin_name == "echo"
    assert ev.caller == "max"
    assert ev.result_status == "ok"
    assert json.loads(ev.arguments) == {"text": "hi"}
    assert ev.latency_ms == pytest.approx(0.42)


def test_build_event_from_call_error_kind_folded_into_status():
    tir = ToolInvocationResult(
        status="error",
        error="ZeroDivisionError: x",
        latency_ms=0.1,
        kind="plugin_error",
    )
    ev = build_event_from_call("math.divide", {"a": 1, "b": 0}, tir)
    assert ev.result_status == "plugin_error"
    assert ev.error and "ZeroDivision" in ev.error


# ---------------------------------------------------------------------------
# AuditLogger end-to-end with dummy client
# ---------------------------------------------------------------------------


def test_audit_logger_log_event_writes_to_qdrant(dummy_logger):
    logger, client = dummy_logger
    ev = AuditEvent(
        timestamp=time.time(),
        session_id="s1",
        caller="agent",
        tool_name="echo.say",
        plugin_name="echo",
        arguments='{"text":"hello"}',
        result_status="ok",
        latency_ms=0.5,
    )
    logger.log_event(ev)
    points = client.collections["test_audit"]
    assert len(points) == 1
    assert points[0].payload["tool_name"] == "echo.say"
    assert points[0].vector and len(points[0].vector) == DEFAULT_EMBEDDING_DIM


def test_audit_logger_semantic_recall_returns_events(dummy_logger):
    logger, _ = dummy_logger
    for i in range(3):
        logger.log_event(
            AuditEvent(
                timestamp=time.time(),
                session_id="s",
                caller="agent",
                tool_name="echo.say",
                plugin_name="echo",
                arguments=f'{{"text":"hi {i}"}}',
                result_status="ok",
                latency_ms=0.1,
            )
        )
    hits = logger.semantic_recall("echo", limit=5)
    assert len(hits) == 3
    assert all(h.tool_name == "echo.say" for h in hits)


def test_audit_logger_filter_by_caller(dummy_logger):
    logger, _ = dummy_logger
    logger.log_event(
        AuditEvent(
            timestamp=time.time(),
            session_id="s",
            caller="agent",
            tool_name="echo.say",
            plugin_name="echo",
            arguments="{}",
            result_status="ok",
            latency_ms=0.1,
        )
    )
    logger.log_event(
        AuditEvent(
            timestamp=time.time(),
            session_id="s",
            caller="max",
            tool_name="echo.say",
            plugin_name="echo",
            arguments="{}",
            result_status="ok",
            latency_ms=0.1,
        )
    )
    hits_agent = logger.semantic_recall("echo", limit=10, filter={"caller": "agent"})
    assert len(hits_agent) == 1
    assert hits_agent[0].caller == "agent"


def test_audit_logger_recent_returns_newest_first(dummy_logger):
    logger, _ = dummy_logger
    now = time.time()
    for i in range(3):
        ev = AuditEvent(
            timestamp=now - (3 - i),
            session_id="s",
            caller="c",
            tool_name=f"tool.v{i}",
            plugin_name="tool",
            arguments="{}",
            result_status="ok",
            latency_ms=0.1,
        )
        logger.log_event(ev)
    hits = logger.recent(limit=10)
    assert len(hits) == 3
    assert hits[0].tool_name == "tool.v2"  # newest first


def test_audit_logger_graceful_degrade_no_qdrant():
    """Logger without any Qdrant-access falls back to in-memory buffer."""
    logger = AuditLogger(
        qdrant_url="http://unreachable.example",
        qdrant_client_factory=lambda: (_ for _ in ()).throw(RuntimeError("no qdrant")),
        embedder=_fake_embedder,
    )
    # init_collection returns False, no crash.
    assert logger.init_collection() is False
    ev = AuditEvent(
        timestamp=time.time(),
        session_id="s",
        caller="c",
        tool_name="echo.say",
        plugin_name="echo",
        arguments="{}",
        result_status="ok",
        latency_ms=0.1,
    )
    logger.log_event(ev)  # must not raise
    hits = logger.recent(limit=5)
    assert len(hits) == 1
    assert hits[0].tool_name == "echo.say"


def _ereignis():
    return AuditEvent(
        timestamp=time.time(),
        session_id="s",
        caller="c",
        tool_name="echo.say",
        plugin_name="echo",
        arguments="{}",
        result_status="ok",
        latency_ms=0.1,
    )


def test_audit_upsert_einmal_wiederholen_und_zaehlen(dummy_logger, monkeypatch):
    """„Server disconnected“ einmal: zweiter Versuch schreibt, der Zähler weist ihn aus, kein Pufferplatz."""
    logger, client = dummy_logger
    monkeypatch.setattr(AuditLogger, "WRITE_RETRY_PAUSE_S", 0.0)
    echtes_upsert = client.upsert
    aufrufe = []

    def wackelig(collection_name, points):
        aufrufe.append(1)
        if len(aufrufe) == 1:
            raise RuntimeError("Server disconnected without sending a response")
        echtes_upsert(collection_name, points)

    client.upsert = wackelig
    logger.log_event(_ereignis())
    assert len(aufrufe) == 2 and len(client.collections["test_audit"]) == 1
    s = logger.stats()
    assert s["write_retries"] == 1 and s["write_failed"] == 0 and s["buffer_len"] == 0
    assert "Server disconnected" in s["last_write_error"]


def test_audit_upsert_zweimal_fehl_geht_in_den_puffer(dummy_logger, monkeypatch):
    logger, client = dummy_logger
    monkeypatch.setattr(AuditLogger, "WRITE_RETRY_PAUSE_S", 0.0)

    def kaputt(collection_name, points):
        raise RuntimeError("Server disconnected")

    client.upsert = kaputt
    logger.log_event(_ereignis())  # darf nicht werfen
    s = logger.stats()
    assert s["write_retries"] == 1 and s["write_failed"] == 1 and s["buffer_len"] == 1


def test_audit_logger_stats_reports_telemetry(dummy_logger):
    logger, _ = dummy_logger
    logger.log_event(
        AuditEvent(
            timestamp=time.time(),
            session_id="s",
            caller="c",
            tool_name="echo.say",
            plugin_name="echo",
            arguments="{}",
            result_status="ok",
            latency_ms=0.1,
        )
    )
    s = logger.stats()
    assert s["collection"] == "test_audit"
    assert s["total_logged"] >= 1
    assert s["collection_ready"] is True


def test_audit_stats_zaehlt_24h_aus_qdrant(dummy_logger):
    """24 h kam nur aus dem (leeren) Puffer -> immer 0."""
    logger, _ = dummy_logger
    jetzt = time.time()
    for alter, caller in ((10, "shell"), (60, "shell"), (3 * 86400, "agent")):
        logger.log_event(
            AuditEvent(
                timestamp=jetzt - alter,
                session_id="s",
                caller=caller,
                tool_name="lage.chronik",
                plugin_name="lage",
                arguments="{}",
                result_status="ok",
                latency_ms=0.1,
            )
        )
    s = logger.stats()
    assert s["buffer_len"] == 0  # alles in Qdrant
    assert s["events_last_24h"] == 2
    assert dict(s["top_plugins"]) == {"lage": 2}
    assert dict(s["top_callers_24h"]) == {"shell": 2}


def test_audit_recent_sortiert_nach_zeit_nicht_nach_id(dummy_logger):
    logger, client = dummy_logger
    jetzt = time.time()
    # Einfuegereihenfolge != Zeitreihenfolge (in Qdrant: uuid4-ids, also zufaellig)
    for alter in (500, 5, 50):
        logger.log_event(
            AuditEvent(
                timestamp=jetzt - alter,
                session_id="s",
                caller="c",
                tool_name=f"t.{alter}",
                plugin_name="t",
                arguments="{}",
                result_status="ok",
                latency_ms=0.1,
            )
        )
    namen = [e.tool_name for e in logger.recent(limit=2)]
    assert namen == ["t.5", "t.50"]
    assert {"timestamp", "caller"} <= getattr(client, "indizes", set())


def test_audit_sekundentakt_wird_nur_gezaehlt(hub_with_dummy_audit):
    client = hub_with_dummy_audit
    plugin = hub_server.get_registry().plugins["audit"]
    plugin._nur_zaehlen = frozenset({"echo.say"})
    vorher = len(client.collections.get("test_audit", []))
    for _ in range(3):
        hub_server.hub__call_tool(tool="echo.say", arguments={"text": "takt"})
    assert len(client.collections.get("test_audit", [])) == vorher
    stand = hub_server.hub__call_tool(tool="audit.stats", arguments={})["result"]
    assert stand["nur_gezaehlt"]["aufrufe"]["echo.say"] == 3


# ---------------------------------------------------------------------------
# Registry on_call hook
# ---------------------------------------------------------------------------


def test_registry_on_call_hook_is_fired():
    captured = []

    reg = hub_registry.PluginRegistry()
    from mcp_hub.plugins.example_echo import EchoPlugin

    hub_registry._register_one(reg, "echo", EchoPlugin())
    reg.register_call_hook(lambda ev: captured.append(ev))

    out = hub_registry.call(reg, "echo.say", {"text": "hi"})
    assert out.status == "ok"
    assert len(captured) == 1
    assert captured[0].tool_name == "echo.say"
    assert captured[0].result_status == "ok"


def test_registry_on_call_hook_exception_does_not_crash():
    reg = hub_registry.PluginRegistry()
    from mcp_hub.plugins.example_echo import EchoPlugin

    hub_registry._register_one(reg, "echo", EchoPlugin())
    reg.register_call_hook(lambda ev: (_ for _ in ()).throw(RuntimeError("boom")))

    out = hub_registry.call(reg, "echo.say", {"text": "hi"})
    assert out.status == "ok"  # dispatch unaffected


def test_registry_register_call_hook_dedup():
    reg = hub_registry.PluginRegistry()
    fn = lambda ev: None
    reg.register_call_hook(fn)
    reg.register_call_hook(fn)
    assert len(reg.on_call_hooks) == 1


# ---------------------------------------------------------------------------
# Full Hub integration — echo.say triggers audit event + hub__audit_log sees it
# ---------------------------------------------------------------------------


def test_hub_integration_echo_produces_audit_event(hub_with_dummy_audit):
    """echo.say dispatch must result in an audit-event visible via audit.recent."""
    client = hub_with_dummy_audit
    out = hub_server.hub__call_tool(tool="echo.say", arguments={"text": "trace-me"})
    assert out["ok"] is True

    # Collection received the event.
    points = client.collections.get("test_audit", [])
    assert any(p.payload["tool_name"] == "echo.say" for p in points), (
        f"no echo.say audit-event persisted. got: {[p.payload for p in points]}"
    )


def test_hub_audit_log_meta_tool_returns_events(hub_with_dummy_audit):
    """4th meta-tool hub__audit_log returns events from the Qdrant-backed logger."""
    hub_server.hub__call_tool(tool="echo.say", arguments={"text": "recall-me"})

    # Semantic recall mode
    out = hub_server.hub__audit_log(query="recall-me", limit=10)
    assert out["ok"] is True
    assert out["count"] >= 1
    tool_names = [e["tool_name"] for e in out["events"]]
    assert "echo.say" in tool_names

    # Chronological tail mode (empty query)
    out2 = hub_server.hub__audit_log(query="", limit=5)
    assert out2["ok"] is True
    assert out2["count"] >= 1


def test_hub_audit_log_meta_tool_filter(hub_with_dummy_audit):
    hub_server.hub__call_tool(tool="echo.say", arguments={"text": "A"})
    hub_server.hub__call_tool(tool="math.add", arguments={"a": 1, "b": 2})
    out = hub_server.hub__audit_log(query="", limit=10, filter={"plugin_name": "echo"})
    assert out["ok"] is True
    for ev in out["events"]:
        assert ev["plugin_name"] == "echo"


def test_audit_plugin_skips_self(hub_with_dummy_audit):
    """Calls to audit.* must NOT produce audit-events (infinite-loop guard)."""
    client = hub_with_dummy_audit
    # Seed one echo event first.
    hub_server.hub__call_tool(tool="echo.say", arguments={"text": "seed"})
    seed_count = len(client.collections.get("test_audit", []))

    # Now call audit.stats via meta-tool dispatch.
    hub_server.hub__call_tool(tool="audit.stats", arguments={})
    new_count = len(client.collections.get("test_audit", []))
    # No new audit-entries from the audit.* call itself.
    assert new_count == seed_count


def test_hub_audit_log_without_plugin_returns_not_found(monkeypatch):
    """If audit plugin isn't loaded, hub__audit_log returns not_found."""
    # Build a fresh hub without the audit plugin by writing a minimal config.
    import tempfile

    minimal = tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8")
    minimal.write(
        "host: 0.0.0.0\nport: 8080\npath: /mcp\n"
        "plugins:\n"
        "  - name: echo\n"
        "    module: mcp_hub.plugins.example_echo\n"
        "    class: EchoPlugin\n"
        "    enabled: true\n"
        "  - name: audit\n"
        "    enabled: false\n"
    )
    minimal.close()
    hub_server.build_app(minimal.name)

    out = hub_server.hub__audit_log(query="anything")
    assert out["ok"] is False
    assert out["kind"] == "not_found"


def test_audit_plugin_describes_four_tools(hub_with_dummy_audit):
    reg = hub_server.get_registry()
    audit_tools = [t for t in reg.tools if t.startswith("audit.")]
    assert set(audit_tools) == {"audit.stats", "audit.recall", "audit.recent", "audit.nutzung"}


# ---------------------------------------------------------------------------
# Coverage sanity
# ---------------------------------------------------------------------------


def test_meta_tool_hub_audit_log_registered_on_fastmcp():
    """hub__audit_log must be registered on the shared FastMCP instance."""
    registered = set(hub_server.mcp._tool_manager._tools.keys())
    assert "hub__audit_log" in registered
