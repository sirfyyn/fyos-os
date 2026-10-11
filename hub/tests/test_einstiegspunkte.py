"""Ein externes Plugin meldet sich ueber die Entry-Point-Gruppe ``mcp_hub.plugins`` -- ohne Eintrag im Hub-Code."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from mcp_hub.config import HubConfig, PluginConfig, load_config
from mcp_hub.registry import build_registry, call

PLUGIN = '''
from mcp_hub.plugin import HubPlugin, ToolDescriptor


class FremdPlugin(HubPlugin):
    name = "fremd"
    description = "Ein Plugin aus einem anderen Paket."
    version = "1.2.3"

    def __init__(self, config=None):
        super().__init__()
        self.gruss = (config or {}).get("gruss", "hallo")

    def register(self):
        pass

    def describe_tools(self):
        return [ToolDescriptor(name="gruss", description="gibt den Gruss zurueck", input_schema={"type": "object"}, tags=["read"])]

    def call(self, method, args):
        if method == "gruss":
            return {"gruss": self.gruss}
        raise ValueError(method)
'''


@pytest.fixture
def installiertes_plugin(tmp_path: Path, monkeypatch):
    """Legt ein Paket mit dist-info und entry_points.txt an -- so, wie pip es installiert."""
    (tmp_path / "fremdpaket").mkdir()
    (tmp_path / "fremdpaket" / "__init__.py").write_text("")
    (tmp_path / "fremdpaket" / "plugin.py").write_text(textwrap.dedent(PLUGIN))
    info = tmp_path / "fyos_fremd-1.2.3.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: fyos-fremd\nVersion: 1.2.3\n")
    (info / "entry_points.txt").write_text("[mcp_hub.plugins]\nfremd = fremdpaket.plugin:FremdPlugin\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield
    for m in [m for m in sys.modules if m.startswith("fremdpaket")]:
        sys.modules.pop(m, None)


def test_plugin_ohne_eintrag_wird_ueber_den_entry_point_geladen(installiertes_plugin):
    reg = build_registry(HubConfig())
    assert "fremd" in reg.plugins
    assert call(reg, "fremd.gruss", {}).result == {"gruss": "hallo"}


def test_yaml_eintrag_ohne_module_nimmt_den_entry_point_mit_config(installiertes_plugin, tmp_path):
    datei = tmp_path / "config.yaml"
    datei.write_text("plugins:\n  - name: fremd\n    config:\n      gruss: moin\n")
    cfg = load_config(datei)
    assert cfg.plugins[0].module == ""
    reg = build_registry(cfg)
    assert call(reg, "fremd.gruss", {}).result == {"gruss": "moin"}


def test_abgeschaltet_im_yaml_gewinnt_gegen_den_entry_point(installiertes_plugin):
    reg = build_registry(HubConfig(plugins=[PluginConfig(name="fremd", enabled=False)]))
    assert "fremd" not in reg.plugins and "fremd" in reg.abgeschaltet


def test_eintrag_ohne_installiertes_paket_wird_nicht_geladen_aber_der_hub_laeuft():
    reg = build_registry(HubConfig(plugins=[PluginConfig(name="gibtsnicht")]))
    assert "gibtsnicht" in reg.nicht_geladen and "Entry-Point" in reg.nicht_geladen["gibtsnicht"]


def test_kernplugins_sind_als_entry_points_registriert():
    from mcp_hub.registry import _discover_entry_points

    namen = {n for n, _ in _discover_entry_points()}
    assert {"audit", "skills", "werkstatt", "mcp", "shell", "gui", "os", "beispiel_app", "dateien", "event_bus_publisher"} <= namen
