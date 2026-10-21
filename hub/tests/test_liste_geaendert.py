"""Hot-Reload Stufe 2: offene Sitzungen erfahren, dass sich die Werkzeugliste geändert hat."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from mcp_hub import liste_geaendert as lg
from mcp_hub import server as hub_server
from mcp_hub.config import HubConfig, load_config


class _Sitzung:
    def __init__(self, *, kaputt: bool = False, haengt: bool = False) -> None:
        self.kaputt, self.haengt = kaputt, haengt
        self.tools = 0
        self.ressourcen = 0

    async def send_tool_list_changed(self) -> None:
        if self.kaputt:
            raise RuntimeError("Strom zu")
        if self.haengt:
            await asyncio.sleep(60)
        self.tools += 1

    async def send_resource_list_changed(self) -> None:
        self.ressourcen += 1


class _Verteiler:
    def __init__(self) -> None:
        self.ereignisse: list[Any] = []

    async def publish(self, ereignis: Any) -> None:
        self.ereignisse.append(ereignis)


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    lg.MELDER.zuruecksetzen()
    monkeypatch.setattr(lg, "SENDE_TIMEOUT_S", 0.2)
    yield
    lg.MELDER.zuruecksetzen()


def test_vorgabe_aus():
    cfg = HubConfig()
    assert cfg.liste_melden is False and cfg.mcp_sitzungen is False
    m = lg.Melder()
    assert m.sitzung_merken(_Sitzung()) is False
    assert m.melden() is False


def test_config_aus_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("liste_melden: true\nmcp_sitzungen: true\nplugins: {}\n", encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.liste_melden is True and cfg.mcp_sitzungen is True


def test_sitzungen_brauchen_melden():
    m = lg.Melder()
    m.konfigurieren(melden=False, sitzungen=True)
    assert m.sitzungen_an is False
    m.konfigurieren(melden=True, sitzungen=False)
    assert m.sitzung_merken(_Sitzung()) is False


def test_alle_sitzungen_bekommen_beides_und_fehler_werden_geschluckt():
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=True)
    gut, kaputt, haengt = _Sitzung(), _Sitzung(kaputt=True), _Sitzung(haengt=True)
    for s in (gut, kaputt, haengt):
        assert m.sitzung_merken(s) is True
    res = asyncio.run(m.melden_async())
    assert (gut.tools, gut.ressourcen) == (1, 1)
    assert res["sitzungen"] == 1 and res["fehler"] == 2
    # die kaputten sind vergessen, die gute bleibt
    assert m.anzahl_sitzungen() == 1
    asyncio.run(m.melden_async())
    assert gut.tools == 2


def test_moderne_protokolle_haben_keine_sitzung():
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=True)
    assert m.sitzung_merken(_Sitzung(), "2026-07-28") is False
    assert m.sitzung_merken(_Sitzung(), "2025-11-25") is True


def test_sitzung_verschwindet_mit_dem_objekt():
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=True)
    s = _Sitzung()
    m.sitzung_merken(s)
    assert m.anzahl_sitzungen() == 1
    del s
    import gc

    gc.collect()
    assert m.anzahl_sitzungen() == 0


def test_verteiler_bekommt_tools_und_ressourcen(monkeypatch):
    class _Tools: ...

    class _Res: ...

    monkeypatch.setattr(lg, "_verteiler_ereignisse", lambda: [_Tools, _Res])
    v = _Verteiler()
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=False, verteiler=v)
    res = asyncio.run(m.melden_async())
    assert [type(e) for e in v.ereignisse] == [_Tools, _Res]
    assert res["verteiler"] is True


def test_kaputter_verteiler_wirft_nicht(monkeypatch):
    class _E: ...

    class _Kaputt:
        async def publish(self, e):
            raise RuntimeError("bus weg")

    monkeypatch.setattr(lg, "_verteiler_ereignisse", lambda: [_E])
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=False, verteiler=_Kaputt())
    res = asyncio.run(m.melden_async())
    assert res["verteiler"] is False and res["fehler"] == 1


def test_melden_aus_arbeitsthread_laeuft_auf_der_schleife():
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=True)
    s = _Sitzung()
    m.sitzung_merken(s)

    async def lauf() -> None:
        m.schleife_setzen(asyncio.get_running_loop())
        ergebnis: list[bool] = []
        t = threading.Thread(target=lambda: ergebnis.append(m.melden()))
        t.start()
        await asyncio.to_thread(t.join)
        for _ in range(50):
            if s.tools:
                break
            await asyncio.sleep(0.02)
        assert ergebnis == [True]

    asyncio.run(lauf())
    assert s.tools == 1 and s.ressourcen == 1


def test_melden_ohne_schleife_ist_kein_fehler():
    m = lg.Melder()
    m.konfigurieren(melden=True, sitzungen=True)
    assert m.melden() is False


def test_nach_plugin_aenderung_meldet(monkeypatch):
    aufrufe: list[str] = []
    monkeypatch.setattr(hub_server, "_REGISTRY", object())
    monkeypatch.setattr(hub_server, "_apps_anbinden", lambda reg: aufrufe.append("apps"))
    monkeypatch.setattr(hub_server, "search_tools", lambda reg, q: [])
    monkeypatch.setattr(hub_server._hybrid.HYBRID, "vorwaermen", lambda t: None)
    monkeypatch.setattr(hub_server._plugins_live, "ereignis", lambda reg, e: aufrufe.append("ereignis"))
    monkeypatch.setattr(lg.MELDER, "melden", lambda: aufrufe.append("melden") or True)
    hub_server._nach_plugin_aenderung({"geladen": ["x"]})
    assert aufrufe == ["apps", "ereignis", "melden"]


def test_einrichten_sitzungen_an_und_wieder_aus():
    alt = hub_server._TRANSPORT["stateless_http"]
    try:
        hub_server._liste_melden_einrichten(HubConfig(liste_melden=True, mcp_sitzungen=True))
        assert hub_server._TRANSPORT["stateless_http"] is False
        assert lg.MELDER.sitzungen_an is True
        if not hub_server._SDK_V2:
            assert hub_server.mcp.settings.stateless_http is False
            caps = hub_server.mcp._mcp_server.create_initialization_options().capabilities
            assert caps.tools.listChanged is True and caps.resources.listChanged is True
        # Rückweg: Schalter aus, wieder zustandslos
        hub_server._liste_melden_einrichten(HubConfig(liste_melden=True, mcp_sitzungen=False))
        assert hub_server._TRANSPORT["stateless_http"] is True
        assert lg.MELDER.sitzungen_an is False
        if not hub_server._SDK_V2:
            assert hub_server.mcp.settings.stateless_http is True
    finally:
        hub_server._TRANSPORT["stateless_http"] = alt
        if not hub_server._SDK_V2:
            hub_server.mcp.settings.stateless_http = alt


def test_list_tools_merkt_die_sitzung(monkeypatch):
    if hub_server._SDK_V2:
        pytest.skip("mcp 2: _handle_list_tools(ctx, params), eigener Test unten")
    lg.MELDER.konfigurieren(melden=True, sitzungen=True)
    s = _Sitzung()

    class _Ctx:
        session = s

    monkeypatch.setattr(type(hub_server.mcp), "get_context", lambda self: _Ctx())
    asyncio.run(hub_server.mcp.list_tools())
    assert lg.MELDER.anzahl_sitzungen() == 1


def test_list_tools_ohne_sitzungen_merkt_nichts(monkeypatch):
    if hub_server._SDK_V2:
        pytest.skip("mcp 1.x-Pfad")
    lg.MELDER.konfigurieren(melden=True, sitzungen=False)
    asyncio.run(hub_server.mcp.list_tools())
    assert lg.MELDER.anzahl_sitzungen() == 0


def test_list_tools_v2_merkt_die_sitzung():
    if not hub_server._SDK_V2:
        pytest.skip("nur mcp 2")
    lg.MELDER.konfigurieren(melden=True, sitzungen=True)
    s = _Sitzung()

    class _Ctx:
        session = s
        protocol_version = "2025-11-25"

    asyncio.run(hub_server.mcp._handle_list_tools(_Ctx(), None))
    assert lg.MELDER.anzahl_sitzungen() == 1
