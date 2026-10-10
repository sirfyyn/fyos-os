"""Sammelstrom `fyos:live` — was der Hub je Werkzeugaufruf schreibt (ohne Netz).

Der Hub schreibt (`event_bus_publisher`, `_livestrom`); Leser dieses Stroms sind Oberflächen ausserhalb des Hubs.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from mcp_hub.audit_log import AuditEvent
from mcp_hub.plugins import _livestrom
from mcp_hub.plugins.event_bus_publisher import EventBusPublisherPlugin

JETZT = 1_791_100_000.0  # Sekunden
JETZT_MS = int(JETZT * 1000)


def _audit(**kw):
    felder = dict(
        timestamp=100.0,
        session_id="s",
        caller="mcp:claude-code",
        tool_name="cluster.lage",
        plugin_name="cluster",
        arguments='{"geheim": "nicht in den Strom"}',
        result_status="ok",
        latency_ms=12.7,
        error=None,
    )
    felder.update(kw)
    return AuditEvent(**felder)


def test_eintrag_traegt_nur_name_plugin_ergebnis_dauer_aufrufer():
    e = _livestrom.eintrag_aus_audit(_audit(), jetzt=JETZT)
    assert e == {
        "t": str(JETZT_MS),
        "p": "cluster",
        "m": "lage",
        "s": "ok",
        "d": "12",
        "w": "mcp:claude-code",
    }
    assert "geheim" not in json.dumps(e) and "arguments" not in e


def test_fehler_bekommt_art_aber_keinen_text():
    e = _livestrom.eintrag_aus_audit(
        _audit(result_status="plugin_error", error="Token abc123 ungültig"), jetzt=JETZT
    )
    assert e["s"] == "fail" and e["k"] == "plugin_error"
    assert "abc123" not in json.dumps(e)


def test_aufrufername_wird_bereinigt():
    assert _livestrom.aufrufer_bereinigen("a b<script>\n") == "abscript"
    assert len(_livestrom.aufrufer_bereinigen("x" * 200)) == 40
    assert _livestrom.aufrufer_bereinigen("") == "unbekannt"


def test_leise_aufrufe_kommen_nicht_in_den_strom(monkeypatch):
    # LEISE ist leer, seit es `live.ereignisse` nicht mehr gibt; was darin steht, bleibt draußen.
    assert _livestrom.LEISE == frozenset()
    monkeypatch.setattr(_livestrom, "LEISE", frozenset({"cluster.lage"}))
    assert _livestrom.eintrag_aus_audit(_audit()) is None


@pytest.mark.parametrize(
    "aufrufer,flaeche",
    [
        ("shell", "os"),
        ("fyos-web", "os"),
        ("claude-chat", "chat"),
        ("mcp:claude-code", "code"),
        ("mcp:codex", "code"),
        ("mcp:Claude-User", "chat"),
        ("agent", "agent"),
        ("agent-1", "agent"),
        ("mcp:undici", "dienste"),
        ("rest:node", "dienste"),
        ("rest:Python-urllib", "dienste"),
        ("unknown", "dienste"),
        ("", "dienste"),
    ],
)
def test_flaeche_aus_dem_aufrufer(aufrufer, flaeche):
    assert _livestrom.flaeche_aus(aufrufer) == flaeche


def test_publisher_schreibt_sammelstrom_und_bus_getrennt():
    r = MagicMock()
    p = EventBusPublisherPlugin()
    p.config = {"redis_client_factory": lambda: r}
    p.register()
    p._publish_event(_audit())
    strom = [c for c in r.xadd.call_args_list if c.args[0] == "fyos:live"]
    bus = [c for c in r.xadd.call_args_list if c.args[0].startswith("bus.tool.")]
    assert len(strom) == 1 and len(bus) == 1
    assert strom[0].args[1]["w"] == "mcp:claude-code" and "args_sample" not in strom[0].args[1]
    assert strom[0].kwargs == {"maxlen": 5000, "approximate": True}


def test_ausfall_des_sammelstroms_stoert_den_bus_nicht():
    r = MagicMock()
    r.xadd.side_effect = lambda name, *a, **k: (
        (_ for _ in ()).throw(OSError("x")) if name == "fyos:live" else "1-0"
    )
    p = EventBusPublisherPlugin()
    p.config = {"redis_client_factory": lambda: r}
    p.register()
    p._publish_event(_audit())
    assert p._live_errors == 1 and p._publish_count == 1 and p._degraded is False


def test_publisher_live_abschaltbar():
    r = MagicMock()
    p = EventBusPublisherPlugin()
    p.config = {"redis_client_factory": lambda: r, "live": False}
    p.register()
    p._publish_event(_audit())
    assert [c.args[0] for c in r.xadd.call_args_list] == ["bus.tool.cluster.lage.ok"]
