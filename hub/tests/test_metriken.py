"""/metrics: Prometheus-Text aus Kernzählern, HubPlugin.metrics() und Zeitplan."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from starlette.testclient import TestClient

from mcp_hub import kv
from mcp_hub import metriken
from mcp_hub import server as hub_server

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.example.yaml"


class _P:
    def __init__(self, name: str, werte: Any = None, fehler: bool = False, plan: list | None = None) -> None:
        self.name = name
        self._w = werte if werte is not None else {}
        self._f = fehler
        self._plan = plan or []

    def metrics(self) -> Any:
        if self._f:
            raise RuntimeError("kaputt")
        return self._w

    def zeitplan(self) -> list:
        return self._plan


def _reg(*plugins: _P) -> SimpleNamespace:
    return SimpleNamespace(
        plugins={p.name: p for p in plugins},
        tools={"a.x": object(), "b.y": object()},
        nicht_geladen={"weg": "ImportError"},
        call_counts={"a.x": 3},
        latency_totals_ms={"a.x": 12.5},
    )


def test_text_hat_kern_plugins_proben_und_zeitplan():
    reg = _reg(
        _P("a", {"gesamt": 7, "an": True, "name": "text wird übergangen", "tief": {"puffer": 2, "x": "y"},
                 "_proben": [
                     {"name": "fyos_a_reihe", "wert": 1.5, "labels": {"modell": 'r"h\nea'}, "typ": "counter", "hilfe": "Hilfe"},
                     {"name": "ohne_vorsilbe", "wert": 4},
                     {"name": "ungültig!", "wert": "keine zahl"},
                 ]}),
        _P("b", fehler=True),
        _P("c", plan=[{"id": "t", "name": "Takt", "takt": "alle 60 s", "letzter": 100.0, "letzter_status": "ok"}]),
    )
    text = metriken.erzeugen(reg)
    assert "fyos_hub_plugins 3" in text and "fyos_hub_werkzeuge 2" in text and "fyos_hub_nicht_geladen 1" in text
    assert 'fyos_hub_aufrufe_total{werkzeug="a.x"} 3' in text and 'fyos_hub_aufruf_ms_summe{werkzeug="a.x"} 12.5' in text
    assert 'fyos_plugin_wert{plugin="a",schluessel="gesamt"} 7' in text
    assert 'fyos_plugin_wert{plugin="a",schluessel="an"} 1' in text
    assert 'fyos_plugin_wert{plugin="a",schluessel="tief.puffer"} 2' in text
    assert "übergangen" not in text
    assert 'fyos_a_reihe{modell="r\\"h\\nea"} 1.5' in text and "# TYPE fyos_a_reihe counter" in text
    assert "fyos_a_ohne_vorsilbe 4" in text
    assert 'fyos_plugin_metrics_fehler{plugin="b"} 1' in text
    assert 'fyos_zeitplan_letzter_ok{aufgabe="Takt",plugin="c",quelle="c"} 1' in text
    assert 'fyos_zeitplan_letzter_lauf_s{aufgabe="Takt",plugin="c",quelle="c"} 100' in text
    assert text.count("# TYPE fyos_plugin_wert gauge") == 1


def test_zwischenablage_haelt_den_text():
    p = _P("a", {"n": 1})
    reg = _reg(p)
    erst = metriken.text(reg, ttl_s=60)
    p._w = {"n": 2}
    assert metriken.text(reg, ttl_s=60) == erst
    assert 'schluessel="n"} 2' in metriken.text(reg, ttl_s=0)


def test_server_liefert_metrics(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT_URL", raising=False)
    app = hub_server.build_app(str(CONFIG_PATH))
    r = TestClient(app).get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "fyos_hub_plugins " in r.text


def test_speicher_kv_hincrby():
    c = kv.SpeicherKv()
    assert c.hincrby("h", "a") == 1 and c.hincrby("h", "a", 4) == 5
    assert c.hgetall("h") == {"a": "5"}
