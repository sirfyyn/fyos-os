"""Eigene HTTP-Wege aus Plugins (``HubPlugin.routen``): nur unter /hub/, nie über einen Weg des Kerns."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.plugin import HubPlugin, ToolDescriptor

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"


async def _antwort(request):
    return JSONResponse({"ok": True, "von": "plugin"})


class _MitWegen(HubPlugin):
    name = "wege"
    description = "Plugin mit eigenem Weg"
    version = "0.0.1"

    def __init__(self, routen=None, fehler: bool = False):
        self._routen = routen if routen is not None else [Route("/hub/wege/melden", _antwort, methods=["POST"])]
        self._fehler = fehler

    def register(self) -> None:
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [ToolDescriptor(name="ping", description="ping", input_schema={})]

    def call(self, method, args):
        return "pong"

    def routen(self):
        if self._fehler:
            raise RuntimeError("kaputt")
        return self._routen


def _registry(*plugins):
    return SimpleNamespace(plugins={p.name: p for p in plugins})


def test_vorgabe_ohne_wege():
    class _Ohne(_MitWegen):
        routen = HubPlugin.routen

    assert _Ohne().routen() == []


def test_nur_unter_hub_und_nie_doppelt():
    gut = Route("/hub/wege/melden", _antwort, methods=["POST"])
    draussen = Route("/anderswo", _antwort)
    kern = Route("/hub/call", _antwort, methods=["POST"])
    doppelt = Route("/hub/wege/melden", _antwort, methods=["GET"])
    plugin = _MitWegen([gut, draussen, kern, doppelt])
    raus = hub_server._plugin_routen(_registry(plugin), {"/hub/call"})
    assert raus == [gut]


def test_fehler_im_plugin_kostet_nur_dessen_wege():
    kaputt = _MitWegen(fehler=True)
    kaputt.name = "kaputt"
    heil = _MitWegen()
    raus = hub_server._plugin_routen(_registry(kaputt, heil), set())
    assert [r.path for r in raus] == ["/hub/wege/melden"]


def test_build_app_haengt_plugin_wege_nach_dem_kern_ein(monkeypatch):
    original = hub_server.build_registry

    def mit_plugin(config):
        reg = original(config)
        hub_registry._register_one(reg, "wege", _MitWegen())
        return reg

    monkeypatch.setattr(hub_server, "build_registry", mit_plugin)
    app = hub_server.build_app(str(CONFIG_PATH))
    pfade = [getattr(r, "path", None) for r in app.routes]
    assert "/hub/wege/melden" in pfade
    assert pfade.index("/hub/wege/melden") > pfade.index("/hub/app-call")
    r = TestClient(app).post("/hub/wege/melden", content=b"{}")
    assert r.status_code == 200 and r.json() == {"ok": True, "von": "plugin"}
