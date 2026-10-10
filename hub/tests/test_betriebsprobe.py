"""Der Hub muss STARTEN und antworten — nicht nur importierbar sein.

## Warum es diesen Test gibt

Frueherer Fehler: `mcp_hub/server.py` importierte `mcp.server.fastmcp`,
das in neueren SDK-Fassungen umgezogen ist. Der Hub lief trotzdem — weil seine
Prozesse lange nicht neu gestartet wurden. Er war damit EINEN Neustart vom
Totalausfall entfernt, und aufgefallen ist es nur durch Zufall.

Kein Test hat das gesehen, weil alle Tests Plugins in der Hand pruefen und
keiner die App baut. Ein Import-Test haette es auch nicht gefunden: der
Importfehler steckte in einer Zeile, die beim Modulimport durchaus laeuft —
was fehlte, war der Beweis, dass daraus ein bedienbarer Server wird.

## Was hier geprueft wird

  1. `build_app()` baut durch (Mount + lifespan)
  2. `GET /health` antwortet 200
  3. ein echter MCP-Roundtrip (initialize + tools/list) kommt durch den Mount

Punkt 3 deckt ab, was ein Import nicht kann. Ab mcp 2.0 schaltet
`streamable_http_app()` den DNS-Rebinding-Schutz selbsttaetig ein, wenn `host`
`127.0.0.1`/`localhost`/`::1` ist — und die Vorgabe der Fabrikmethode IST
`127.0.0.1`. Der TestClient sendet `Host: testserver` OHNE Port, was die
Auto-Allowlist (`127.0.0.1:*`, `localhost:*`, `[::1]:*`) nicht trifft. Waere der
Schutz an, kaeme hier `421 Invalid Host header` statt `200`. Dieser Test ist
damit zugleich die Probe darauf, dass `host` bis in die Fabrikmethode
durchgereicht wird.

Laeuft unter mcp 1.x wie unter 2.x — `mcp_hub.server` traegt beide (siehe
`_SDK_V2` dort).
"""

from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("starlette.testclient")

from starlette.testclient import TestClient  # noqa: E402

from mcp_hub import server as hub_server  # noqa: E402

_KONFIG = str(pathlib.Path(__file__).resolve().parents[1] / "config_example.yaml")

_ERWARTETE_META = {
    "hub__search_tools",
    "hub__call_tool",
    "hub__map",
    "hub__schema",
    "hub__health",
    "hub__list_servers",
}

_KOPF = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _nutzlast(text: str) -> dict:
    """JSON-Antwort ODER SSE-Rahmen — beide Formen sind zulaessig."""
    schlank = text.lstrip()
    if schlank.startswith(("event:", "data:")):
        for zeile in text.splitlines():
            if zeile.startswith("data: "):
                return json.loads(zeile[6:])
        raise AssertionError(f"SSE ohne data-Zeile: {text[:200]}")
    return json.loads(text)


@pytest.fixture(scope="module")
def app():
    return hub_server.build_app(_KONFIG)


@pytest.fixture(scope="module")
def client(app):
    """EIN Client fuer alle Tests.

    `StreamableHTTPSessionManager.run()` darf pro Instanz nur einmal laufen; ein
    frischer `TestClient` je Test betritt den lifespan erneut und laeuft in
    `RuntimeError: .run() can only be called once`. Der geteilte Client haelt
    den lifespan ueber das ganze Modul offen — so, wie der Pod ihn auch haelt.
    """
    with TestClient(app) as c:
        yield c


def test_die_probe_kennt_ihre_sdk_fassung():
    """Selbstprobe — der Test muss sagen koennen, WAS er gerade prueft."""
    assert isinstance(hub_server._SDK_V2, bool)
    # v1: FastMCP, v2: MCPServer. Beides zulaessig, aber nicht irgendetwas.
    assert type(hub_server.mcp).__name__ in ("FastMCP", "MCPServer")


def test_app_baut_durch(app):
    from starlette.applications import Starlette

    assert isinstance(app, Starlette)


def test_health_antwortet(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("tools", 0) > 0, f"Hub meldet 0 Werkzeuge: {d}"


def test_mcp_initialize_kommt_durch_den_mount(client):
    """Deckt den 421-Fall ab: Host-Header ohne Port bei aktivem Rebinding-Schutz."""
    mount = hub_server._CONFIG.path if hub_server._CONFIG else "/mcp"
    r = client.post(
        mount,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "betriebsprobe", "version": "1"},
            },
        },
        headers=_KOPF,
    )
    assert r.status_code != 421, (
        "421 Invalid Host header — der DNS-Rebinding-Schutz ist an. Ab mcp 2.0 "
        "schaltet ihn `streamable_http_app()` selbst ein, wenn `host` nicht "
        "durchgereicht wird (Vorgabe 127.0.0.1). Siehe _TRANSPORT in server.py."
    )
    assert r.status_code == 200, r.text
    assert _nutzlast(r.text)["result"]["serverInfo"]["name"] == "FYOS MCP-Hub"


def test_tools_list_liefert_die_meta_werkzeuge(client):
    mount = hub_server._CONFIG.path if hub_server._CONFIG else "/mcp"
    r = client.post(
        mount,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=_KOPF,
    )
    assert r.status_code == 200, r.text
    namen = {t["name"] for t in _nutzlast(r.text)["result"]["tools"]}
    fehlt = _ERWARTETE_META - namen
    assert not fehlt, f"Meta-Werkzeuge fehlen: {sorted(fehlt)} (da: {sorted(namen)})"


# ── Identität auf dem Draht ───────────────────
# Spezifikation 2025-11-25: `serverInfo.icons`, `Tool.title/icons`, `Resource.title/description/icons`. Beide
# SDK-Linien (mcp 1.28 und 2.x) schreiben sie selbst; dieser Test sieht, was wirklich beim Client ankommt.


def _rpc(client, methode: str, params: dict | None = None, id_: int = 10) -> dict:
    mount = hub_server._CONFIG.path if hub_server._CONFIG else "/mcp"
    r = client.post(
        mount,
        json={"jsonrpc": "2.0", "id": id_, "method": methode, "params": params or {}},
        headers=_KOPF,
    )
    assert r.status_code == 200, r.text
    return _nutzlast(r.text)["result"]






# ── Aufrufer im Audit ──────────────────────────────────────────


def _mitschreiben():
    gesehen: list[str] = []
    hub_server.get_registry().register_call_hook(lambda ev: gesehen.append(ev.caller))
    return gesehen


def test_rest_call_traegt_aufrufer_aus_kopfzeile(client):
    gesehen = _mitschreiben()
    r = client.post(
        "/hub/call",
        json={"tool": "echo.say", "arguments": {"text": "hallo"}},
        headers={"X-Hub-Caller": "agent"},
    )
    assert r.status_code == 200, r.text
    assert gesehen[-1] == "agent"


def test_mcp_call_traegt_client_aus_user_agent(client):
    gesehen = _mitschreiben()
    mount = hub_server._CONFIG.path if hub_server._CONFIG else "/mcp"
    r = client.post(
        mount,
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "hub__call_tool",
                "arguments": {"tool": "echo.say", "arguments": {"text": "x"}},
            },
        },
        headers={**_KOPF, "User-Agent": "claude-code/2.1.0 (cli)"},
    )
    assert r.status_code == 200, r.text
    assert gesehen and gesehen[-1] == "mcp:claude-code"


def test_aufrufer_aus_pfad():
    assert hub_server.aufrufer_aus("/hub/app-call", {}) == "fyos-web"
    assert (
        hub_server.aufrufer_aus("/hub/call", {"user-agent": "python-requests/2.32"})
        == "rest:python-requests"
    )
    assert hub_server.aufrufer_aus("/mcp", {"x-hub-caller": "kleinmodell"}) == "kleinmodell"
    assert hub_server.aufrufer_aus("/mcp", {}) == "mcp:unbekannt"


def test_unbekannte_argumente_werden_abgelehnt(client):
    """`additionalProperties: false` wird zentral durchgesetzt."""
    r = client.post(
        "/hub/call", json={"tool": "echo.say", "arguments": {"text": "x", "laut": True}}
    )
    d = r.json()
    assert d["ok"] is False
    assert d["kind"] == "bad_arguments"
    assert "laut" in d["error"] and "text" in d["error"]
