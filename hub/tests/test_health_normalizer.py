"""plugin_healthy normalisiert die drei gewachsenen health()-Schemata.

Vorher wertete server_infos() ``.get("ok", False)`` aus — Proxies ({"status":
"ok"}) und CLI-Wrapper ({"available": True}) waren damit IMMER unhealthy,
unabhängig vom echten Backend-Zustand (10/20 Plugins falsch-negativ).
"""

from __future__ import annotations

from mcp_hub.plugin import HubPlugin
from mcp_hub.registry import PluginRegistry, plugin_healthy


def test_contract_schema_ok_key_wins():
    assert plugin_healthy({"ok": True}) is True
    assert plugin_healthy({"ok": False, "status": "ok"}) is False  # ok-Key gewinnt
    assert plugin_healthy({"ok": True, "status": "unreachable"}) is True


def test_proxy_schema_status():
    assert plugin_healthy({"status": "ok"}) is True
    assert plugin_healthy({"status": "healthy"}) is True
    assert plugin_healthy({"status": "unreachable", "error": "boom"}) is False
    assert plugin_healthy({"status": "degraded"}) is False


def test_cli_schema_available():
    assert plugin_healthy({"available": True, "binary_path": "/x"}) is True
    assert plugin_healthy({"available": False}) is False


def test_unknown_schema_fails_closed():
    assert plugin_healthy({}) is False
    assert plugin_healthy({"irgendwas": 1}) is False
    assert plugin_healthy(None) is False  # type: ignore[arg-type]


class _StatusPlugin(HubPlugin):
    """Plugin im Proxy-Schema — muss als healthy erscheinen."""

    name = "statusproxy"
    description = "test"
    version = "0.0.1"

    def register(self) -> None:
        return None

    def describe_tools(self):
        return []

    def call(self, method: str, args):  # pragma: no cover - nicht benutzt
        return {}

    def health(self):
        return {"status": "ok", "upstream": {"x": 1}}


def test_server_infos_uses_normalizer():
    reg = PluginRegistry()
    plugin = _StatusPlugin()
    reg.plugins[plugin.name] = plugin
    infos = reg.server_infos()
    assert len(infos) == 1
    assert infos[0].healthy is True  # vorher: False (ok-Key fehlte)


# ── P1 Tool-Map (SPEC-MCP-HUB-REBUILD §6) ────────────────────────────────────


def _registry_with_status_plugin():
    from mcp_hub.plugin import ToolDescriptor

    class _MapPlugin(_StatusPlugin):
        name = "mappy"
        description = "Karten-Testplugin — erste Zeile.\nzweite Zeile."

        def describe_tools(self):
            return [
                ToolDescriptor(
                    name="lesen",
                    description="Liest Dinge.\nDetails hier.",
                    input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
                    tags=["mappy", "read"],
                ),
                ToolDescriptor(
                    name="brennen",
                    description="Zerstört Dinge.",
                    tags=["mappy", "write", "destructive"],
                ),
                ToolDescriptor(name="mystery", description="", tags=[]),
            ]

    from mcp_hub.registry import PluginRegistry, RegisteredTool

    reg = PluginRegistry()
    plugin = _MapPlugin()
    reg.plugins[plugin.name] = plugin
    for td in plugin.describe_tools():
        fq = f"{plugin.name}.{td.name}"
        reg.tools[fq] = RegisteredTool(
            plugin_name=plugin.name, tool_name=td.name, fqtn=fq, descriptor=td
        )
    return reg


def test_scope_from_tags_strictest_wins():
    from mcp_hub.registry import scope_from_tags

    assert scope_from_tags(["read"]) == "READ"
    assert scope_from_tags(["write", "destructive"]) == "DESTRUCTIVE"
    assert scope_from_tags(["extern", "write"]) == "EXTERN"
    assert scope_from_tags([]) == "UNKNOWN"
    assert scope_from_tags(None) == "UNKNOWN"


def test_map_view_compact_no_schemas():
    from mcp_hub.registry import map_view

    reg = _registry_with_status_plugin()
    out = map_view(reg, include_health=False)
    assert out["ok"] and out["count"] == 1
    d = out["domains"][0]
    assert d["domain"] == "mappy"
    assert d["summary"].startswith("Karten-Testplugin")
    assert d["tool_count"] == 3
    tools = {t["tool"]: t for t in d["tools"]}
    assert tools["mappy.lesen"]["scope"] == "READ"
    assert tools["mappy.lesen"]["summary"] == "Liest Dinge."
    assert tools["mappy.brennen"]["scope"] == "DESTRUCTIVE"
    assert tools["mappy.mystery"]["scope"] == "UNKNOWN"
    # KEINE Schemas in der Map — das ist der Small-Model-Hebel
    assert "inputSchema" not in str(d["tools"])


def test_map_view_health_flag():
    from mcp_hub.registry import map_view

    reg = _registry_with_status_plugin()
    out = map_view(reg, include_health=True)
    assert out["domains"][0]["healthy"] is True  # _StatusPlugin.health → status ok


def test_map_view_domain_filter():
    from mcp_hub.registry import map_view

    reg = _registry_with_status_plugin()
    assert map_view(reg, domain="mappy", include_health=False)["count"] == 1
    assert map_view(reg, domain="gibtsnicht", include_health=False)["count"] == 0


def test_tool_schema_stage_two():
    from mcp_hub.registry import tool_schema

    reg = _registry_with_status_plugin()
    out = tool_schema(reg, "mappy.lesen")
    assert out["ok"] and out["scope"] == "READ"
    assert out["inputSchema"]["properties"]["q"]["type"] == "string"
    missing = tool_schema(reg, "mappy.fehlt")
    assert not missing["ok"] and missing["kind"] == "not_found"
