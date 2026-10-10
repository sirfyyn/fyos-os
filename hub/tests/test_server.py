"""mcp_hub.tests.test_server — Gate-1 / config tests for MCP-Hub.

Covers:
    1. Hub builds + 4 meta-tools are registered on FastMCP.
    2. Example plugin loads + hub__search_tools('echo') finds it.
    3. hub__call_tool('echo.say', {'text': 'hello'}) returns 'hello'.
    4. hub__list_servers() enumerates example_echo with 1 tool.

Tests deliberately call the Hub meta-tool functions directly (not via HTTP) so
the suite stays fast and does not require a running uvicorn process. HTTP-layer
tests follow in S-MCP-HUB.1.2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hub import config as hub_config
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.plugin import HubPlugin, ToolDescriptor

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"


@pytest.fixture(autouse=True)
def _build_hub_with_example():
    """Rebuild registry with example_echo before every test. Auto-applied."""
    hub_server.build_app(str(CONFIG_PATH))
    yield
    # Don't tear down — FastMCP tool registrations are module-level and safe to leave.


# ---------------------------------------------------------------------------
# Test 1 — Hub builds, meta-tools + example plugin visible
# ---------------------------------------------------------------------------


def test_hub_exposes_meta_tools():
    """The Hub must expose the ADR-105 meta-tools."""
    expected = {"hub__search_tools", "hub__call_tool", "hub__list_servers", "hub__audit_log"}
    # FastMCP stores registered tools in its internal ToolManager.
    registered = set(hub_server.mcp._tool_manager._tools.keys())
    missing = expected - registered
    assert not missing, f"missing meta-tools: {missing}"


def test_example_plugin_loaded():
    """example_echo should be present in the registry with 1 tool."""
    reg = hub_server.get_registry()
    assert "echo" in reg.plugins, f"echo plugin missing. got: {list(reg.plugins)}"
    assert "echo.say" in reg.tools, f"echo.say missing. got: {list(reg.tools)}"
    assert reg.tools["echo.say"].descriptor.name == "say"


# ---------------------------------------------------------------------------
# Test 2 — hub__search_tools
# ---------------------------------------------------------------------------


def test_search_tools_finds_echo():
    """search_tools('echo') must return the echo.say descriptor."""
    result = hub_server.hub__search_tools(query="echo")
    assert result["ok"] is True
    names = [t["name"] for t in result["tools"]]
    assert "echo.say" in names
    # kurz: ohne Schema; voll: wie früher
    assert "inputSchema" not in result["tools"][0]
    result = hub_server.hub__search_tools(query="echo", ansicht="voll")
    entry = next(t for t in result["tools"] if t["name"] == "echo.say")
    assert entry["plugin"] == "echo"
    assert "text" in entry["inputSchema"]["properties"]


def test_search_tools_empty_query_returns_all():
    """Empty query returns every registered tool."""
    result = hub_server.hub__search_tools(query="")
    assert result["count"] >= 1
    assert any(t["name"] == "echo.say" for t in result["tools"])


def test_search_tools_no_match():
    """Query that matches nothing returns count=0 (not an error)."""
    result = hub_server.hub__search_tools(query="does-not-exist-xyz")
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["tools"] == []


# ---------------------------------------------------------------------------
# Test 3 — hub__call_tool dispatch
# ---------------------------------------------------------------------------


def test_call_tool_echo_roundtrip():
    """call_tool('echo.say', {'text': 'hello'}) must return {'echo': 'hello'}."""
    result = hub_server.hub__call_tool(tool="echo.say", arguments={"text": "hello"})
    assert result["ok"] is True, result
    assert result["result"] == {"echo": "hello"}


def test_call_tool_bad_format_rejected():
    """Tool-id without a dot is a bad request, not a not_found."""
    result = hub_server.hub__call_tool(tool="echo_say", arguments={})
    assert result["ok"] is False
    assert result["kind"] == "bad_request"


def test_call_tool_unknown_returns_not_found():
    """Unknown fqtn returns kind='not_found'."""
    result = hub_server.hub__call_tool(tool="ghost.say", arguments={})
    assert result["ok"] is False
    assert result["kind"] == "not_found"


def test_call_tool_plugin_error_is_captured():
    """Plugin exceptions are caught and returned as kind='plugin_error'."""
    result = hub_server.hub__call_tool(tool="echo.say", arguments={"text": 5})  # 'text' must be str
    assert result["ok"] is False
    assert result["kind"] == "plugin_error"
    # Ganz ohne Argumente fängt schon der Hub ab.
    assert hub_server.hub__call_tool(tool="echo.say", arguments={})["kind"] == "bad_arguments"


# ---------------------------------------------------------------------------
# Test 4 — hub__list_servers
# ---------------------------------------------------------------------------


def test_list_servers_shows_echo():
    """list_servers must include echo with tool_count=1."""
    result = hub_server.hub__list_servers()
    assert result["ok"] is True
    names = {s["name"]: s for s in result["servers"]}
    assert "echo" in names
    assert names["echo"]["tool_count"] == 1
    assert names["echo"]["healthy"] is True


# ---------------------------------------------------------------------------
# Bonus — config loader + secret resolution
# ---------------------------------------------------------------------------




def test_config_missing_file_returns_empty_hub(tmp_path):
    cfg = hub_config.load_config(tmp_path / "does-not-exist.yaml")
    assert cfg.plugins == []
    assert cfg.port == hub_config.DEFAULT_PORT


def test_inject_secrets_resolves_from_env(monkeypatch):
    monkeypatch.setenv("GITEA_TOKEN", "gitea-secret")
    monkeypatch.setenv("argocd_token", "argocd-secret")
    out = hub_config.inject_secrets(["gitea-token", "argocd_token"])
    assert out == {
        "gitea-token": "gitea-secret",
        "argocd_token": "argocd-secret",
    }


def test_inject_secrets_empty_list_returns_empty():
    assert hub_config.inject_secrets([]) == {}


def test_inject_secrets_prefers_explicit_env_name(monkeypatch):
    monkeypatch.setenv("ARGOCD_AUTH_TOKEN", "token-123")
    binding = hub_config.SecretBinding(name="argocd-api-token", env="ARGOCD_AUTH_TOKEN")
    out = hub_config.inject_secrets([binding])
    assert out == {"argocd-api-token": "token-123"}


# ---------------------------------------------------------------------------
# Plugin-Protocol smoke — custom plugin via direct registry build
# ---------------------------------------------------------------------------


class _StubPlugin(HubPlugin):
    name = "stub"
    description = "in-test stub"
    version = "0.0.1"

    def register(self) -> None:
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="ping", description="ping", input_schema={})]

    def call(self, method, args):
        if method == "ping":
            return "pong"
        raise ValueError(f"unknown {method}")


def test_registry_register_one_custom_plugin():
    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "stub", _StubPlugin())
    assert "stub" in reg.plugins
    assert "stub.ping" in reg.tools
    out = hub_registry.dispatch(reg, "stub.ping", {})
    # S-MCP-HUB.1.2 adds latency_ms to every dispatch response.
    assert out["ok"] is True
    assert out["result"] == "pong"
    assert "latency_ms" in out


# ---------------------------------------------------------------------------
# Nur ueber die Oberflaeche: visibility ["app"] gilt auch im Verteiler
# ---------------------------------------------------------------------------
def test_nur_oberflaeche_sperrt_den_allgemeinen_verteiler():
    """Schleifen schaltet der Betreiber selbst. Ein Modell kommt ueber hub__call_tool und /hub/call
    nicht an Werkzeuge, die nur eine Oberflaeche rufen darf."""
    reg = hub_server.get_registry()
    echo = reg.tools["echo.say"]
    reg.tools["echo.nur_app"] = hub_registry.RegisteredTool(
        plugin_name="echo",
        tool_name="say",
        fqtn="echo.nur_app",
        descriptor=ToolDescriptor(
            name="say",
            description="nur fuer die App",
            input_schema=echo.descriptor.input_schema,
            meta={"ui": {"resourceUri": "ui://x", "visibility": ["app"]}},
        ),
    )
    try:
        r = hub_server.hub__call_tool(tool="echo.nur_app", arguments={"text": "x"})
        assert r["ok"] is False and r["kind"] == "nur_oberflaeche"
        assert hub_server.nur_oberflaeche(reg, "echo.say") is None
        assert hub_server.hub__call_tool(tool="echo.say", arguments={"text": "x"})["ok"] is True
    finally:
        del reg.tools["echo.nur_app"]


def test_rest_health_und_servers_nur_lesen():
    """`hub.py health|servers`: dieselben Daten wie die Meta-Werkzeuge, auch je Plugin."""
    import asyncio
    import json
    from types import SimpleNamespace

    def hole(coro):
        r = asyncio.run(coro)
        return r.status_code, json.loads(r.body)

    status, alle = hole(hub_server.rest_health(SimpleNamespace(query_params={})))
    assert status == 200 and alle["ok"] and "echo" in alle["plugins"]
    status, eins = hole(hub_server.rest_health(SimpleNamespace(query_params={"plugin": "echo"})))
    assert status == 200 and eins["plugin"] == "echo" and eins["healthy"] is True
    status, fehlt = hole(hub_server.rest_health(SimpleNamespace(query_params={"plugin": "nix"})))
    assert status == 404 and fehlt["kind"] == "not_found"
    status, liste = hole(hub_server.rest_servers(SimpleNamespace(query_params={})))
    assert status == 200 and {s["name"] for s in liste["servers"]} >= {"echo"}
