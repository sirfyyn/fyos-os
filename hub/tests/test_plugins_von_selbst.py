"""Regel statt Liste: Plugin-Module laden ohne Config-Eintrag."""

from __future__ import annotations

import sys

import pytest

from mcp_hub.config import HubConfig, PluginConfig
from mcp_hub.registry import build_registry, plugins_ohne_eintrag

_PLUGIN = '''
from mcp_hub.plugin import HubPlugin, ToolDescriptor


class {klasse}(HubPlugin):
    name = "{name}"

    def register(self):
        pass

    def describe_tools(self):
        return [ToolDescriptor(name="zustand", description="d", input_schema={{"type": "object"}})]

    def call(self, method, args):
        return {{"ok": True}}
'''


@pytest.fixture
def paket(tmp_path, monkeypatch):
    p = tmp_path / "probeplugins"
    p.mkdir()
    (p / "__init__.py").write_text("")
    (p / "neu.py").write_text(_PLUGIN.format(klasse="NeuPlugin", name="neu"))
    (p / "aus.py").write_text(_PLUGIN.format(klasse="AusPlugin", name="aus"))
    (p / "eingetragen.py").write_text(_PLUGIN.format(klasse="EinPlugin", name="ein"))
    (p / "hilfe.py").write_text("def rechne():\n    return 1\n")
    (p / "_intern.py").write_text(_PLUGIN.format(klasse="InternPlugin", name="intern"))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "probeplugins"
    for m in [m for m in sys.modules if m.startswith("probeplugins")]:
        sys.modules.pop(m, None)


def test_nur_plugin_module_ohne_eintrag(paket):
    cfg = HubConfig(
        plugins=[
            PluginConfig(name="ein", module=f"{paket}.eingetragen"),
            PluginConfig(name="aus", module=f"{paket}.aus", enabled=False),
        ]
    )
    neu = plugins_ohne_eintrag(cfg, paket=paket)
    assert [(p.name, p.module) for p in neu] == [("neu", f"{paket}.neu")]  # Hilfsmodul, _intern, Einträge: nein


def test_registry_laedt_neues_nur_mit_schalter(paket, monkeypatch):
    import mcp_hub.registry as r

    monkeypatch.setattr(r, "plugins_ohne_eintrag", lambda cfg: plugins_ohne_eintrag(cfg, paket=paket))
    aus = PluginConfig(name="aus", module=f"{paket}.aus", enabled=False)
    assert "neu" not in build_registry(HubConfig(plugins=[aus])).plugins
    reg = build_registry(HubConfig(plugins=[aus], plugins_von_selbst=True))
    assert "neu" in reg.plugins and "aus" not in reg.plugins and "aus" in reg.abgeschaltet
