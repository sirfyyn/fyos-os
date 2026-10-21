"""Plugins live nachladen: geaenderte Module aus Quellverzeichnissen ersetzen die im Bild, ohne Neustart.

Das „Bild“ ist ein tmp-Ordner mit dem Paket ``livetest_pkg`` (auf dem Suchpfad), die „Quelle“ ein zweiter tmp-Ordner
mit gleich aufgebauten Dateien (``<quelle>/livetest_pkg/<modul>.py``).
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

from mcp_hub import plugins_live as live
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.config import HubConfig, PluginConfig, SecretBinding, load_config
from mcp_hub.plugin import HubPlugin

PAKET = "livetest_pkg"

_QUELLE = '''
import os
from mcp_hub.plugin import HubPlugin, ResourceDescriptor, ToolDescriptor

VERSION = "{version}"


class {klasse}(HubPlugin):
    name = "{name}"
    description = "Probe {version}"

    def __init__(self, config=None):
        super().__init__()
        self.konfig = config or {{}}
        {bauen}

    def register(self):
        {registrieren}

    def describe_tools(self):
        werkzeuge = [
            ToolDescriptor(
                name="ping",
                description="ping " + VERSION,
                input_schema={{"type": "object", "properties": {{}}}},
                meta={{"ui": {{"resourceUri": "ui://probe/{name}"}}}},
            )
        ]
        if VERSION == "v2":
            werkzeuge.append(ToolDescriptor(name="pong", description="pong", input_schema={{"type": "object"}}))
        return werkzeuge

    def describe_resources(self):
        return [ResourceDescriptor(uri="ui://probe/{name}", name="{name}", read=lambda: "<p>" + VERSION + "</p>")]

    def call(self, method, args):
        return {{"ok": True, "version": VERSION, "methode": method, "konfig": self.konfig}}

    def shutdown(self):
        log = os.environ.get("LIVETEST_LOG")
        if log:
            with open(log, "a") as f:
                f.write("shutdown " + VERSION + "\\n")
'''


def _quelle(name: str, version: str = "v1", *, bauen: str = "pass", registrieren: str = "pass") -> str:
    return _QUELLE.format(
        version=version, klasse=name.capitalize() + "Plugin", name=name, bauen=bauen, registrieren=registrieren
    )


class Umgebung:
    def __init__(self, bild: Path, klon: Path, log: Path):
        self.bild, self.klon, self.log = bild, klon, log

    def im_bild(self, stem: str, text: str) -> Path:
        p = self.bild / PAKET / f"{stem}.py"
        p.write_text(text, encoding="utf-8")
        return p

    def in_quelle(self, stem: str, text: str) -> Path:
        p = self.klon / PAKET / f"{stem}.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def cfg(self, *module: str, **kw) -> HubConfig:
        """Konfiguration mit Live-Laden an und je Modul einem Eintrag ``livetest_<stem>``."""
        eintraege = [PluginConfig(name=f"{m}", module=f"{PAKET}.{m}") for m in module]
        cfg = HubConfig(plugins_live=True, plugins=eintraege, **kw)
        return cfg


@pytest.fixture()
def umgebung(tmp_path: Path, monkeypatch):
    bild = tmp_path / "bild"
    (bild / PAKET).mkdir(parents=True)
    (bild / PAKET / "__init__.py").write_text("")
    klon = tmp_path / "klon"
    klon.mkdir()
    monkeypatch.syspath_prepend(str(bild))
    monkeypatch.setenv("LIVETEST_LOG", str(tmp_path / "log.txt"))
    monkeypatch.delenv(live.UMGEBUNG_QUELLEN, raising=False)
    # Die installierten Entry-Point-Plugins des Kerns gehoeren nicht in diese Tests.
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [])
    paket = importlib_paket()
    pfad_vorher = list(paket.__path__)
    live.zuruecksetzen()
    yield Umgebung(bild, klon, tmp_path / "log.txt")
    live.zuruecksetzen()
    paket.__path__[:] = pfad_vorher
    live._PFAD_ERGAENZT.clear()
    for m in [m for m in sys.modules if m == PAKET or m.startswith(PAKET + ".") or m.startswith("mcp_hub.plugins.livetest")]:
        sys.modules.pop(m, None)
        if m.startswith("mcp_hub.plugins.") and hasattr(paket, m.rpartition(".")[2]):
            delattr(paket, m.rpartition(".")[2])


def importlib_paket():
    import importlib

    return importlib.import_module("mcp_hub.plugins")


def _rufe(reg, fqtn: str) -> dict:
    return hub_registry.dispatch(reg, fqtn, {})["result"]


def _bauen(umgebung: Umgebung, *module: str, **kw):
    """Hub mit den Modulen aus dem Bild bauen (Quelle leer) und die Quelle danach einschalten."""
    cfg = umgebung.cfg(*module, **kw)
    reg = hub_registry.build_registry(cfg)
    assert live.konfigurieren(cfg, quellen=[umgebung.klon]) is True
    return cfg, reg


# ── Schalter ──────────────────────────────────────────────────────────────────


def test_schalter_aus_aendert_nichts(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    umgebung.in_quelle("a", _quelle("a", "v2"))
    cfg = HubConfig(plugins=[PluginConfig(name="a", module=f"{PAKET}.a")])  # plugins_live: Vorgabe False
    assert live.konfigurieren(cfg, quellen=[umgebung.klon]) is False
    res = live.nachladen(hub_registry.PluginRegistry(), cfg)
    assert res["ok"] is False and res["kind"] == "aus"
    assert live.plugin_status(object()) is None and live.uebersicht() is None
    assert live.vorladen(f"{PAKET}.a") is False
    assert live.ui_datei("x", "a.html") is None
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "a.ping")["version"] == "v1"  # die Quelle wurde nie gelesen


def test_schalter_an_ohne_quelle_bleibt_aus(umgebung):
    assert live.konfigurieren(HubConfig(plugins_live=True)) is False
    assert live.aktiv() is False
    assert live.konfigurieren(HubConfig(plugins_live=True, plugins_live_quellen=[str(umgebung.klon / "gibt-es-nicht")])) is False


def test_quellen_aus_konfiguration_und_umgebung(umgebung, monkeypatch, tmp_path):
    zweite = tmp_path / "zweite"
    zweite.mkdir()
    assert live.konfigurieren(HubConfig(plugins_live=True, plugins_live_quellen=[str(umgebung.klon)])) is True
    assert live.quellen() == [umgebung.klon]
    monkeypatch.setenv(live.UMGEBUNG_QUELLEN, f"{umgebung.klon}:{zweite}")
    assert live.konfigurieren(HubConfig(plugins_live=True)) is True
    assert live.quellen() == [umgebung.klon, zweite]
    # die Konfiguration geht der Umgebung vor
    assert live.konfigurieren(HubConfig(plugins_live=True, plugins_live_quellen=[str(zweite)])) is True
    assert live.quellen() == [zweite]


def test_config_schalter_aus_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "plugins_live: true\nplugins_live_takt_s: 5\nplugins_live_quellen: [/a, /b]\n"
        "liste_melden: true\nmcp_sitzungen: true\nplugins: []\n",
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.plugins_live is True and cfg.plugins_live_takt_s == 5.0 and cfg.plugins_live_quellen == ["/a", "/b"]
    assert cfg.liste_melden is True and cfg.mcp_sitzungen is True
    leer = HubConfig()
    assert (leer.plugins_live, leer.liste_melden, leer.mcp_sitzungen, leer.plugins_live_quellen) == (False, False, False, [])
    p.write_text("plugins_live_quellen: /a:/b\n", encoding="utf-8")
    assert load_config(str(p)).plugins_live_quellen == ["/a", "/b"]


# ── Nachladen ─────────────────────────────────────────────────────────────────


def test_geaendertes_plugin_wird_atomar_ersetzt(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    alt = reg.plugins["a"]
    assert live.nachladen(reg, cfg)["unveraendert"] == 0  # die Quelle hat die Datei nicht
    datei = umgebung.in_quelle("a", _quelle("a", "v1"))  # gleicher Inhalt wie im Bild: kein Neuladen
    assert live.nachladen(reg, cfg)["unveraendert"] == 1
    assert reg.plugins["a"] is alt

    datei.write_text(_quelle("a", "v2"), encoding="utf-8")
    vorher_tools = reg.tools
    res = live.nachladen(reg, cfg)
    assert res["ok"] and res["geladen"] == ["a"]
    assert reg.plugins["a"] is not alt
    assert set(reg.tools) == {"a.ping", "a.pong"}
    assert _rufe(reg, "a.ping")["version"] == "v2"
    assert reg.tools is not vorher_tools and set(vorher_tools) == {"a.ping"}  # Austausch, kein Umbau
    assert reg.resources["ui://probe/a"][1].read() == "<p>v2</p>"
    assert umgebung.log.read_text() == "shutdown v1\n"  # altes shutdown() lief genau einmal
    status = live.plugin_status(reg.plugins["a"])
    assert status["geladen_aus"] == "klon" and status["letzter_fehler"] is None


def test_konfiguration_des_eintrags_bleibt_beim_nachladen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg = umgebung.cfg("a")
    cfg.plugins[0].config = {"adresse": "x"}
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "a.ping")["konfig"] == {"adresse": "x"}
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    umgebung.in_quelle("a", _quelle("a", "v2"))
    assert live.nachladen(reg, cfg)["geladen"] == ["a"]
    assert _rufe(reg, "a.ping")["konfig"] == {"adresse": "x"} and _rufe(reg, "a.ping")["version"] == "v2"


def test_plugin_aus_entry_point_ohne_eintrag_wird_nachgeladen(umgebung, monkeypatch):
    umgebung.im_bild("ep", _quelle("ep", "v1"))
    import importlib

    def entry_points(group=None):
        return [types.SimpleNamespace(name="ep", module=f"{PAKET}.ep", load=lambda: importlib.import_module(f"{PAKET}.ep").EpPlugin)]

    monkeypatch.setattr("importlib.metadata.entry_points", entry_points)
    cfg = HubConfig(plugins_live=True, plugins_live_quellen=[str(umgebung.klon)])
    umgebung.in_quelle("ep", _quelle("ep", "v2"))
    reg = hub_registry.build_registry(cfg)  # vorladen: der Entry-Point bekommt gleich den Stand der Quelle
    assert _rufe(reg, "ep.ping")["version"] == "v2"
    assert live.plugin_status(reg.plugins["ep"])["geladen_aus"] == "klon"

    umgebung.in_quelle("ep", _quelle("ep", "v1") + "\n# neu\n")
    assert live.nachladen(reg, cfg)["geladen"] == ["ep"]
    assert _rufe(reg, "ep.ping")["version"] == "v1"
    assert umgebung.log.read_text() == "shutdown v2\n"


def test_modul_mit_zwei_plugins(umgebung):
    zwei = _quelle("erstes", "v1") + "\n\n" + _quelle("zweites", "v1").split("VERSION = ", 1)[1].split("\n", 1)[1]
    umgebung.im_bild("zwei", zwei)
    cfg = HubConfig(
        plugins_live=True,
        plugins=[
            PluginConfig(name="erstes", module=f"{PAKET}.zwei", class_name="ErstesPlugin"),
            PluginConfig(name="zweites", module=f"{PAKET}.zwei", class_name="ZweitesPlugin"),
        ],
    )
    reg = hub_registry.build_registry(cfg)
    assert {"erstes.ping", "zweites.ping"} <= set(reg.tools)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    umgebung.in_quelle("zwei", zwei.replace('VERSION = "v1"', 'VERSION = "v2"', 1))
    assert live.nachladen(reg, cfg)["geladen"] == ["zwei"]
    assert {"erstes.ping", "zweites.ping"} <= set(reg.tools)
    assert reg.plugins["erstes"] is not None and reg.plugins["zweites"] is not None
    assert _rufe(reg, "erstes.ping")["version"] == "v2"


def test_kaputte_datei_laesst_altes_plugin_stehen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    datei = umgebung.in_quelle("a", "def kaputt(:\n")
    res = live.nachladen(reg, cfg)
    assert res["ok"] is False and "SyntaxError" in res["fehler"]["a"]
    assert _rufe(reg, "a.ping")["version"] == "v1"
    assert sys.modules[f"{PAKET}.a"].VERSION == "v1"
    assert "SyntaxError" in live.plugin_status(reg.plugins["a"])["letzter_fehler"]
    assert "a" in live.uebersicht()["fehler"]
    assert not umgebung.log.exists()  # das alte Plugin wurde nicht heruntergefahren

    # dieselbe kaputte Datei wird nicht erneut geladen, nur gemeldet; mit `erzwingen` ein neuer Versuch
    assert "a" in live.nachladen(reg, cfg)["fehler"]
    assert "a" in live.nachladen(reg, cfg, erzwingen=True)["fehler"]

    datei.write_text(_quelle("a", "v2"), encoding="utf-8")  # repariert
    assert live.nachladen(reg, cfg)["geladen"] == ["a"]
    assert _rufe(reg, "a.ping")["version"] == "v2"
    assert live.plugin_status(reg.plugins["a"])["letzter_fehler"] is None


def test_fehler_im_aufbau_laesst_altes_plugin_stehen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    umgebung.in_quelle("a", _quelle("a", "v2", registrieren="raise RuntimeError('register kaputt')"))
    res = live.nachladen(reg, cfg)
    assert "register kaputt" in res["fehler"]["a"]
    assert _rufe(reg, "a.ping")["version"] == "v1"
    assert set(reg.tools) == {"a.ping"}
    assert umgebung.log.read_text() == "shutdown v2\n"  # nur das verworfene neue Plugin wurde aufgeraeumt
    assert sys.modules[f"{PAKET}.a"].VERSION == "v1"


def test_werkzeugname_eines_fremden_plugins_wird_nicht_ueberschrieben(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    umgebung.im_bild("b", _quelle("b", "v1"))
    cfg, reg = _bauen(umgebung, "a", "b")
    # a will jetzt unter dem Namen b auftreten: der Name ist von b belegt
    umgebung.in_quelle("a", _quelle("a", "v2").replace('name = "a"', 'name = "b"'))
    res = live.nachladen(reg, cfg)
    assert "belegt" in res["fehler"]["a"]
    assert _rufe(reg, "a.ping")["version"] == "v1" and _rufe(reg, "b.ping")["version"] == "v1"


def test_aus_der_quelle_verschwundenes_modul_bleibt_geladen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    datei = umgebung.in_quelle("a", _quelle("a", "v2"))
    live.nachladen(reg, cfg)
    datei.unlink()
    res = live.nachladen(reg, cfg)
    assert "a" in reg.plugins and "a.ping" in reg.tools and res["ok"]
    assert _rufe(reg, "a.ping")["version"] == "v2"


def test_abgeschaltetes_plugin_bleibt_aus(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg = HubConfig(plugins_live=True, plugins=[PluginConfig(name="a", module=f"{PAKET}.a", enabled=False)])
    reg = hub_registry.build_registry(cfg)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    umgebung.in_quelle("a", _quelle("a", "v2"))
    res = live.nachladen(reg, cfg)
    assert reg.plugins == {} and res["neu"] == [] and res["geladen"] == []


def test_nur_ein_plugin_nachladen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    umgebung.im_bild("b", _quelle("b", "v1"))
    cfg, reg = _bauen(umgebung, "a", "b")
    umgebung.in_quelle("a", _quelle("a", "v2"))
    umgebung.in_quelle("b", _quelle("b", "v2"))
    res = live.nachladen(reg, cfg, nur="b")
    assert res["geladen"] == ["b"]
    assert _rufe(reg, "a.ping")["version"] == "v1" and _rufe(reg, "b.ping")["version"] == "v2"
    assert live.nachladen(reg, cfg, nur="gibt-es-nicht")["kind"] == "not_found"
    assert live.nachladen(reg, cfg, nur=f"{PAKET}.a")["geladen"] == ["a"]  # auch mit vollem Modulnamen


def test_erste_quelle_gewinnt(umgebung, tmp_path):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg = umgebung.cfg("a")
    reg = hub_registry.build_registry(cfg)
    zweite = tmp_path / "zweite"
    live.konfigurieren(cfg, quellen=[umgebung.klon, zweite])
    umgebung.in_quelle("a", _quelle("a", "v2"))
    (zweite / PAKET).mkdir(parents=True)
    (zweite / PAKET / "a.py").write_text(_quelle("a", "v3"), encoding="utf-8")
    live.nachladen(reg, cfg)
    assert _rufe(reg, "a.ping")["version"] == "v2"


def test_neues_plugin_aus_mcp_hub_plugins_wird_aufgenommen(umgebung):
    ordner = umgebung.klon / "mcp_hub" / "plugins"
    ordner.mkdir(parents=True)
    cfg = HubConfig(plugins_live=True, plugins_von_selbst=True)
    assert live.konfigurieren(cfg, quellen=[umgebung.klon]) is True
    reg = hub_registry.PluginRegistry()
    assert live.nachladen(reg, cfg)["neu"] == []
    (ordner / "livetest_n.py").write_text(_quelle("livetest_n", "v1"), encoding="utf-8")
    res = live.nachladen(reg, cfg)
    assert res["ok"] and res["neu"] == ["livetest_n"] and res["geladen"] == []
    assert "livetest_n.ping" in reg.tools and _rufe(reg, "livetest_n.ping")["version"] == "v1"
    assert "ui://probe/livetest_n" in reg.resources
    assert live.plugin_status(reg.plugins["livetest_n"])["geladen_aus"] == "klon"


def test_hilfsmodul_und_unterstrich_werden_nicht_zum_plugin(umgebung):
    ordner = umgebung.klon / "mcp_hub" / "plugins"
    ordner.mkdir(parents=True)
    cfg = HubConfig(plugins_live=True, plugins_von_selbst=True)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    (ordner / "livetest_hilfe.py").write_text("def rechne():\n    return 1\n", encoding="utf-8")
    (ordner / "_livetest_intern.py").write_text(_quelle("livetest_intern"), encoding="utf-8")
    reg = hub_registry.PluginRegistry()
    res = live.nachladen(reg, cfg)
    assert res["neu"] == [] and res["geladen"] == [] and reg.plugins == {}
    assert live.nachladen(reg, cfg)["unveraendert"] == 1  # nicht jede Runde neu geprueft


def test_neues_plugin_ohne_von_selbst_wird_nicht_aufgenommen(umgebung):
    ordner = umgebung.klon / "mcp_hub" / "plugins"
    ordner.mkdir(parents=True)
    cfg = HubConfig(plugins_live=True)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    (ordner / "livetest_n.py").write_text(_quelle("livetest_n", "v1"), encoding="utf-8")
    assert live.nachladen(hub_registry.PluginRegistry(), cfg)["neu"] == []


# ── Start ─────────────────────────────────────────────────────────────────────


def test_start_nimmt_stand_der_quelle_wenn_er_vom_bild_abweicht(umgebung):
    umgebung.im_bild("b", _quelle("b", "v1"))
    umgebung.in_quelle("b", _quelle("b", "v2"))
    cfg = umgebung.cfg("b")
    reg = hub_registry.build_registry(cfg)
    # ohne Quelle (konfigurieren lief ohne Quellen): Bild-Stand
    assert _rufe(reg, "b.ping")["version"] == "v1"
    for m in [m for m in sys.modules if m.startswith(PAKET + ".")]:
        sys.modules.pop(m)
    cfg.plugins_live_quellen = [str(umgebung.klon)]
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "b.ping")["version"] == "v2"
    assert live.plugin_status(reg.plugins["b"])["geladen_aus"] == "klon"
    assert live.nachladen(reg, cfg)["unveraendert"] == 1  # danach nichts mehr zu tun


def test_start_faellt_auf_das_bild_zurueck_wenn_der_stand_der_quelle_nicht_baut(umgebung):
    umgebung.im_bild("b", _quelle("b", "v1"))
    umgebung.in_quelle("b", _quelle("b", "v2", bauen="raise RuntimeError('baut nicht')"))
    cfg = umgebung.cfg("b", plugins_live_quellen=[str(umgebung.klon)])
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "b.ping")["version"] == "v1"
    status = live.plugin_status(reg.plugins["b"])
    assert status["geladen_aus"] == "image" and "baut nicht" in status["letzter_fehler"]
    assert live.nachladen(reg, cfg)["fehler"].keys() == {"b"}  # derselbe kaputte Stand wird nicht noch einmal geladen


def test_start_faellt_auf_das_bild_zurueck_bei_syntaxfehler(umgebung):
    umgebung.im_bild("b", _quelle("b", "v1"))
    umgebung.in_quelle("b", "def kaputt(:\n")
    cfg = umgebung.cfg("b", plugins_live_quellen=[str(umgebung.klon)])
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "b.ping")["version"] == "v1"
    assert "SyntaxError" in live.plugin_status(reg.plugins["b"])["letzter_fehler"]


def test_entry_point_faellt_beim_start_auf_das_bild_zurueck(umgebung, monkeypatch):
    umgebung.im_bild("ep", _quelle("ep", "v1"))
    import importlib

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [
            types.SimpleNamespace(
                name="ep", module=f"{PAKET}.ep", load=lambda: importlib.import_module(f"{PAKET}.ep").EpPlugin
            )
        ],
    )
    umgebung.in_quelle("ep", _quelle("ep", "v2", bauen="raise RuntimeError('baut nicht')"))
    cfg = HubConfig(plugins_live=True, plugins_live_quellen=[str(umgebung.klon)])
    reg = hub_registry.build_registry(cfg)
    assert _rufe(reg, "ep.ping")["version"] == "v1"
    assert "baut nicht" in live.plugin_status(reg.plugins["ep"])["letzter_fehler"]


# ── Haken, Oberflaechen ───────────────────────────────────────────────────────


_ZUSATZ = '''
    def registry_anbinden(self, reg):
        self.reg = reg
        reg.register_result_hook(_ergebnis_hook)
        reg.register_call_hook(_aufruf_hook)

    def register_as_listener(self, registry):
        selbst = self
        registry.register_call_hook(lambda ev: selbst)


def _ergebnis_hook(tool, arguments, tir):
    return VERSION


def _aufruf_hook(ev):
    return VERSION
'''


def test_registry_anbinden_und_hooks_ohne_doppelte(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1") + _ZUSATZ)
    cfg = umgebung.cfg("a")
    reg = hub_registry.build_registry(cfg)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    reg.plugins["a"].registry_anbinden(reg)
    reg.plugins["a"].register_as_listener(reg)
    assert len(reg.ergebnis_hooks) == 1 and len(reg.on_call_hooks) == 2
    umgebung.in_quelle("a", _quelle("a", "v2") + _ZUSATZ)
    assert live.nachladen(reg, cfg)["geladen"] == ["a"]
    # neues Plugin bekam registry_anbinden und register_as_listener, die Haken des alten sind weg (nicht doppelt)
    assert reg.plugins["a"].reg is reg
    assert len(reg.ergebnis_hooks) == 1 and len(reg.on_call_hooks) == 2
    assert reg.ergebnis_hooks[0](None, {}, None) == "v2"
    assert any(h(None) == "v2" for h in reg.on_call_hooks if h.__name__ == "_aufruf_hook")
    assert isinstance(reg.plugins["a"], HubPlugin)


def test_fremde_hooks_bleiben_stehen(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1") + _ZUSATZ)
    cfg = umgebung.cfg("a")
    reg = hub_registry.build_registry(cfg)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    fremd = lambda ev: None  # noqa: E731
    reg.register_call_hook(fremd)
    reg.plugins["a"].registry_anbinden(reg)
    umgebung.in_quelle("a", _quelle("a", "v2") + _ZUSATZ)
    live.nachladen(reg, cfg)
    # fremder Haken, Hakenfunktion des neuen Moduls und der Zuhoerer des neuen Plugins (an die Stelle des alten)
    assert fremd in reg.on_call_hooks and len(reg.on_call_hooks) == 3


def test_oberflaeche_aus_der_quelle(umgebung, tmp_path):
    from mcp_hub.plugins import _oberflaeche

    assert live.konfigurieren(HubConfig(plugins_live=True), quellen=[umgebung.klon]) is True
    ui = umgebung.klon / PAKET / "ui"
    ui.mkdir(parents=True)
    (ui / "x.html").write_text("<p>aus der Quelle</p>", encoding="utf-8")
    assert live.ui_datei(PAKET, "x.html") == ui / "x.html"
    (umgebung.klon / "geheim.html").write_text("nein", encoding="utf-8")
    assert live.ui_datei(PAKET, "../../geheim.html") is None  # nur der Dateiname zaehlt, nie aus dem Ordner hinaus
    assert live.ui_datei(PAKET, "fehlt.html") is None
    assert live.ui_datei(tmp_path, "x.html") is None  # ein ausdruecklich genannter Ordner bleibt
    assert _oberflaeche._plugin_text(PAKET, "x.html") == "<p>aus der Quelle</p>"
    # der Kern: <quelle>/mcp_hub/plugins/ui
    kern_ui = umgebung.klon / "mcp_hub" / "plugins" / "ui"
    kern_ui.mkdir(parents=True)
    (kern_ui / "_stil.css").write_text("/* neu */", encoding="utf-8")
    assert live.ui_datei(None, "_stil.css") == kern_ui / "_stil.css"
    live.zuruecksetzen()
    assert live.ui_datei(PAKET, "x.html") is None


# ── Server ────────────────────────────────────────────────────────────────────


def test_app_werkzeuge_und_ressourcen_nach_reload_aktualisiert(umgebung, monkeypatch):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    monkeypatch.setattr(hub_server, "_REGISTRY", reg)
    monkeypatch.setattr(hub_server._hybrid.HYBRID, "vorwaermen", lambda *a, **k: None)
    try:
        hub_server._apps_anbinden(reg)
        tools = {t.name: t for t in asyncio.run(hub_server.mcp.list_tools())}
        assert tools["a__ping"].description == "ping v1"
        umgebung.in_quelle("a", _quelle("a", "v2"))
        live.nachladen(reg, cfg, nach_aenderung=hub_server._nach_plugin_aenderung)
        tools = {t.name: t for t in asyncio.run(hub_server.mcp.list_tools())}
        assert tools["a__ping"].description == "ping v2"
        uris = {str(r.uri) for r in asyncio.run(hub_server.mcp.list_resources())}
        assert "ui://probe/a" in uris
    finally:
        hub_server._apps_anbinden(hub_registry.PluginRegistry())


def test_health_zeigt_live_angaben(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    umgebung.in_quelle("a", _quelle("a", "v2"))
    live.nachladen(reg, cfg)
    bericht = hub_server._health_bericht(reg)
    assert bericht["live"]["an"] is True and bericht["live"]["quellen"] == [str(umgebung.klon)]
    assert bericht["plugins"]["a"]["live"]["geladen_aus"] == "klon"
    live.zuruecksetzen()
    bericht = hub_server._health_bericht(reg)
    assert "live" not in bericht and "live" not in bericht["plugins"]["a"]


def test_endpunkt_neu_laden(umgebung, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    monkeypatch.setattr(hub_server, "_REGISTRY", reg)
    monkeypatch.setattr(hub_server, "_CONFIG", cfg)
    monkeypatch.setattr(hub_server._hybrid.HYBRID, "vorwaermen", lambda *a, **k: None)
    umgebung.in_quelle("a", _quelle("a", "v2"))
    app = Starlette(routes=[Route("/hub/plugins/neu-laden", hub_server.rest_plugins_neu_laden, methods=["POST"])])
    try:
        r = TestClient(app).post("/hub/plugins/neu-laden")
        assert r.status_code == 200 and r.json()["geladen"] == ["a"] and "liste_melden" in r.json()
        assert TestClient(app).post("/hub/plugins/neu-laden", json={"plugin": "nix"}).status_code == 404
        assert TestClient(app).post("/hub/plugins/neu-laden", json=[1]).status_code == 400
        live.zuruecksetzen()  # Schalter aus: 409, nichts passiert
        assert TestClient(app).post("/hub/plugins/neu-laden").status_code == 409
    finally:
        hub_server._apps_anbinden(hub_registry.PluginRegistry())


def test_route_ist_im_hub_angemeldet():
    app = hub_server.build_app.__code__.co_names
    assert "rest_plugins_neu_laden" in app


def test_waechter_laedt_nur_bei_neuem_commit(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    git = umgebung.klon / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    ref = git / "refs" / "heads" / "main"
    ref.write_text("a" * 40 + "\n")
    assert live.commit_lesen(umgebung.klon) == "a" * 40

    datei = umgebung.in_quelle("a", _quelle("a", "v2"))
    w = live.Waechter(reg, cfg)
    assert w.tick()["geladen"] == ["a"]
    datei.write_text(_quelle("a", "v3"), encoding="utf-8")
    assert w.tick() is None  # gleicher Commit: nicht einmal gehasht
    assert _rufe(reg, "a.ping")["version"] == "v2"
    ref.write_text("b" * 40 + "\n")
    assert w.tick()["geladen"] == ["a"]
    assert _rufe(reg, "a.ping")["version"] == "v3"


def test_waechter_ohne_git_prueft_jede_runde(umgebung):
    umgebung.im_bild("a", _quelle("a", "v1"))
    cfg, reg = _bauen(umgebung, "a")
    w = live.Waechter(reg, cfg)
    assert w.tick()["unveraendert"] == 0
    datei = umgebung.in_quelle("a", _quelle("a", "v2"))
    assert w.tick()["geladen"] == ["a"]
    assert w.tick()["unveraendert"] == 1
    datei.write_text(_quelle("a", "v3"), encoding="utf-8")
    assert w.tick()["geladen"] == ["a"]


def test_commit_aus_packed_refs(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text("# pack-refs\n" + "c" * 40 + " refs/heads/main\n")
    assert live.commit_lesen(tmp_path) == "c" * 40
    (git / "HEAD").write_text("d" * 40 + "\n")  # abgekoppelter Kopf
    assert live.commit_lesen(tmp_path) == "d" * 40
    assert live.commit_lesen(tmp_path / "nix") is None


def test_secrets_des_eintrags_gelten_beim_nachladen(umgebung, monkeypatch):
    umgebung.im_bild("a", _quelle("a", "v1", bauen="self.token = os.environ.get('LIVETEST_TOKEN')"))
    cfg = umgebung.cfg("a")
    cfg.plugins[0].secrets = [SecretBinding(name="livetest-token", env="LIVETEST_TOKEN")]
    monkeypatch.setenv("LIVETEST_TOKEN", "geheim")
    reg = hub_registry.build_registry(cfg)
    live.konfigurieren(cfg, quellen=[umgebung.klon])
    umgebung.in_quelle("a", _quelle("a", "v2", bauen="self.token = os.environ.get('LIVETEST_TOKEN')"))
    assert live.nachladen(reg, cfg)["geladen"] == ["a"]
    assert reg.plugins["a"].token == "geheim"
