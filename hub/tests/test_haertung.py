"""Härtung des Hubs: Zeitlimit, Fehlerarten, Statuscodes, ETag, Herkunft, Zwischenspeicher.

Was hier festgehalten wird:

* ein hängender Plugin-Aufruf endet als `timeout` und zählt für den Breaker; Werkzeuge mit eigenem Limit
  (`ToolDescriptor.zeitlimit_s`) laufen länger
* Eingabefehler (`ValueError`) sind `bad_arguments` und sperren das Plugin nicht; echte Ausfälle tun es weiter
* JSON, das kein Objekt ist, ergibt 400 statt 500; Fehlerart bestimmt den HTTP-Status
* `/hub/apps` und `/hub/resource` tragen ETag und beantworten `If-None-Match` mit 304
* `ui://`-Dateien werden nach Änderungszeit zwischengespeichert
* schreibende `/hub/`-Wege lehnen fremde Browser-Herkunft ab und verlangen `application/json`
* der Zwischenspeicher der Plugins ist begrenzt
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_hub import herkunft
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.circuit_breaker import CircuitBreakerConfig, CircuitState
from mcp_hub.plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from mcp_hub.plugins import _oberflaeche

FREIGABE = threading.Event()


class _Probe(HubPlugin):
    name = "probe"
    version = "0"

    def register(self) -> None:
        pass

    def describe_tools(self) -> list[ToolDescriptor]:
        def t(name: str, **kw: Any) -> ToolDescriptor:
            return ToolDescriptor(name=name, description=name, input_schema={}, tags=["read", "flaeche"], **kw)

        return [
            t("gut"),
            t("pruefen"),
            t("json_kaputt"),
            t("kaputt"),
            t("haengt"),
            t("haengt_lang", zeitlimit_s=2.0),
            t("haengt_nie_begrenzt", zeitlimit_s=0),
            t("wer"),
            t("langsam", zeitlimit_s=2.0),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [ResourceDescriptor(uri="ui://probe/x.html", name="x", read=lambda: "<p>x</p>")]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if method == "gut":
            return {"ok": True, "wert": 1}
        if method == "pruefen":
            raise ValueError("limit muss eine Zahl sein")
        if method == "json_kaputt":
            raise json.JSONDecodeError("Expecting value", "<html>", 0)
        if method == "kaputt":
            raise RuntimeError("Upstream tot")
        if method in ("haengt", "haengt_lang", "haengt_nie_begrenzt"):
            FREIGABE.wait(5)
            return {"ok": True}
        if method == "wer":
            return {"ok": True, "aufrufer": hub_registry.AUFRUFER.get()}
        if method == "langsam":
            time.sleep(0.3)
            return {"ok": True, "fertig": True}
        raise KeyError(method)


@pytest.fixture
def reg(monkeypatch: pytest.MonkeyPatch):
    FREIGABE.clear()
    r = hub_registry.PluginRegistry()
    r.breakers.default_config = CircuitBreakerConfig(failure_threshold=5, timeout_sec=30.0, half_open_max_calls=3)
    r.aufruf_zeitlimit_s = 0.2  # kurz, damit die Tests schnell sind
    hub_registry._register_one(r, "probe", _Probe())
    monkeypatch.setattr(hub_server, "_REGISTRY", r)
    yield r
    FREIGABE.set()  # haengende Faeden entlassen


@pytest.fixture
def client(reg) -> TestClient:
    app = Starlette(
        routes=[
            Route("/hub/call", hub_server.rest_call, methods=["POST"]),
            Route("/hub/mehr", hub_server.rest_mehr, methods=["POST"]),
            Route("/hub/app-call", hub_server.rest_app_call, methods=["POST"]),
            Route("/hub/apps", hub_server.rest_apps, methods=["GET"]),
            Route("/hub/resource", hub_server.rest_resource, methods=["GET"]),
        ]
    )
    return TestClient(app)


# ── Fehlerart und Breaker ─────────────────────────────────────────────────────────────────────────


def test_eingabefehler_ist_bad_arguments_und_zaehlt_nicht_fuer_den_breaker(reg):
    for _ in range(8):  # mehr als die Schwelle (5)
        r = hub_registry.dispatch(reg, "probe.pruefen", {})
        assert r["ok"] is False and r["kind"] == "bad_arguments" and "limit muss" in r["error"]
    assert reg.breakers.get("probe").state is CircuitState.CLOSED
    assert hub_registry.dispatch(reg, "probe.gut", {})["ok"] is True  # das Plugin ist nicht gesperrt


def test_echter_ausfall_sperrt_weiter(reg):
    for _ in range(5):
        r = hub_registry.dispatch(reg, "probe.kaputt", {})
        assert r["kind"] == "plugin_error"
    assert reg.breakers.get("probe").state is CircuitState.OPEN
    assert hub_registry.dispatch(reg, "probe.gut", {})["kind"] == "circuit_open"


def test_kaputte_json_antwort_des_upstreams_ist_kein_eingabefehler(reg):
    # JSONDecodeError ist ein ValueError, aber der Dienst dahinter hat Muell geliefert: das ist ein Ausfall
    for _ in range(5):
        assert hub_registry.dispatch(reg, "probe.json_kaputt", {})["kind"] == "plugin_error"
    assert reg.breakers.get("probe").state is CircuitState.OPEN


def test_fehlerart():
    assert hub_registry.fehlerart(ValueError("x")) == "bad_arguments"
    assert hub_registry.fehlerart(json.JSONDecodeError("m", "d", 0)) == "plugin_error"
    assert hub_registry.fehlerart(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "m")) == "plugin_error"
    assert hub_registry.fehlerart(RuntimeError("x")) == "plugin_error"
    assert hub_registry.fehlerart(hub_registry.AufrufZeitueberschreitung("x")) == "timeout"


# ── Zeitlimit ─────────────────────────────────────────────────────────────────────────────────────


def test_haengender_aufruf_endet_als_timeout_und_zaehlt_fuer_den_breaker(reg):
    t0 = time.monotonic()
    r = hub_registry.dispatch(reg, "probe.haengt", {})
    assert time.monotonic() - t0 < 2
    assert r["ok"] is False and r["kind"] == "timeout" and "Zeitlimit" in r["error"]
    assert reg.breakers.get("probe").snapshot()["consecutive_failures"] == 1
    for _ in range(4):
        hub_registry.dispatch(reg, "probe.haengt", {})
    assert reg.breakers.get("probe").state is CircuitState.OPEN


def test_eigenes_zeitlimit_des_werkzeugs_gilt_statt_der_vorgabe(reg):
    # Vorgabe 0,2 s, das Werkzeug darf 2 s und braucht 0,3 s
    r = hub_registry.dispatch(reg, "probe.langsam", {})
    assert r["ok"] is True and r["result"] == {"ok": True, "fertig": True}


def test_zeitlimit_null_heisst_kein_limit(reg):
    reg.aufruf_zeitlimit_s = 0
    FREIGABE.set()
    assert hub_registry.dispatch(reg, "probe.gut", {})["ok"] is True
    tool = reg.get_tool("probe.haengt_nie_begrenzt")
    assert hub_registry.zeitlimit_fuer(reg, tool) == 0.0


def test_aufrufer_wandert_in_den_zeitlimit_faden(reg):
    marke = hub_registry.AUFRUFER.set("fyos-web")
    try:
        r = hub_registry.dispatch(reg, "probe.wer", {})
    finally:
        hub_registry.AUFRUFER.reset(marke)
    assert r["result"]["aufrufer"] == "fyos-web"


def test_vorgabe_aus_umgebung_und_konfiguration(monkeypatch):
    monkeypatch.delenv("MCP_HUB_AUFRUF_ZEITLIMIT_S", raising=False)
    assert hub_registry.PluginRegistry().aufruf_zeitlimit_s == hub_registry.AUFRUF_ZEITLIMIT_S == 120.0
    monkeypatch.setenv("MCP_HUB_AUFRUF_ZEITLIMIT_S", "45")
    assert hub_registry.PluginRegistry().aufruf_zeitlimit_s == 45.0
    monkeypatch.setenv("MCP_HUB_AUFRUF_ZEITLIMIT_S", "kaputt")
    assert hub_registry.PluginRegistry().aufruf_zeitlimit_s == 120.0


def test_langlaeufer_tragen_ihr_eigenes_limit():
    from mcp_hub.plugins.werkstatt import ZEIT_MAX, WerkstattPlugin

    def limits(plugin: HubPlugin) -> dict[str, float | None]:
        return {d.name: d.zeitlimit_s for d in plugin.describe_tools()}

    assert limits(WerkstattPlugin({}))["ausfuehren"] == ZEIT_MAX + 30


# ── HTTP: Koerper, Status ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pfad", ["/hub/call", "/hub/app-call", "/hub/mehr"])
@pytest.mark.parametrize("roh", [b"[1]", b"5", b'"x"', b"null", b"true"])
def test_json_ohne_objekt_ist_400_statt_500(client, pfad, roh):
    r = client.post(pfad, content=roh, headers={"content-type": "application/json"})
    assert r.status_code == 400
    j = r.json()
    assert j["ok"] is False and j["kind"] == "bad_request" and "JSON-Objekt" in j["error"]


@pytest.mark.parametrize("pfad", ["/hub/call", "/hub/app-call"])
def test_kaputtes_json_bleibt_400(client, pfad):
    r = client.post(pfad, content=b"{nein", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "invalid json"


def test_falsche_typen_in_den_feldern_sind_400(client):
    assert client.post("/hub/call", json={"tool": 5}).status_code == 400
    assert client.post("/hub/call", json={"tool": "probe.gut", "arguments": [1]}).status_code == 400
    assert client.post("/hub/app-call", json={"tool": ["a"]}).status_code == 400
    assert client.post("/hub/app-call", json={"name": 7}).status_code == 400
    assert client.post("/hub/app-call", json={"tool": "probe.gut", "arguments": "x"}).status_code == 400
    assert client.post("/hub/mehr", json={"ergebnis_id": "x", "limit": "viel"}).status_code in (400, 404)


def test_status_nach_art(client, reg):
    ok = client.post("/hub/app-call", json={"tool": "probe.gut"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert client.post("/hub/app-call", json={"tool": "probe.pruefen"}).status_code == 400  # Eingabefehler
    assert client.post("/hub/app-call", json={"tool": "probe.nirgends"}).status_code == 403  # kein Flaechen-Werkzeug
    assert client.post("/hub/call", json={"tool": "probe.nirgends"}).status_code == 404
    assert client.post("/hub/call", json={"tool": "ohnepunkt"}).status_code == 400
    assert client.post("/hub/app-call", json={"tool": "probe.haengt"}).status_code == 504  # Zeitueberschreitung
    assert client.post("/hub/call", json={"tool": "probe.kaputt"}).status_code == 502  # Plugin-Fehler


def test_status_fuer_tabelle():
    s = hub_server.status_fuer
    assert s({"ok": True}) == 200
    assert s({"ok": False, "kind": "bad_arguments"}) == 400
    assert s({"ok": False, "kind": "nur_oberflaeche"}) == 403
    assert s({"ok": False, "kind": "timeout"}) == 504
    assert s({"ok": False, "kind": "circuit_open"}) == 503
    assert s({"ok": False, "kind": "plugin_error"}) == 502
    assert s({"ok": False, "kind": "tool_failed"}) == 502
    assert s({"ok": False}) == 502


# ── HTTP: ETag ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pfad", ["/hub/apps", "/hub/resource?uri=ui://probe/x.html"])
def test_lesende_wege_haben_etag_und_antworten_304(client, pfad):
    r = client.get(pfad)
    assert r.status_code == 200 and r.json()["ok"] is True
    etag = r.headers["etag"]
    assert etag.startswith('"') and r.headers["cache-control"] == "private, no-cache"
    r2 = client.get(pfad, headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.content == b"" and r2.headers["etag"] == etag
    assert client.get(pfad, headers={"If-None-Match": "W/" + etag}).status_code == 304  # nginx macht ihn schwach
    assert client.get(pfad, headers={"If-None-Match": '"anders", ' + etag}).status_code == 304
    assert client.get(pfad, headers={"If-None-Match": '"anders"'}).status_code == 200


def test_apps_antwortformat_bleibt(client):
    j = client.get("/hub/apps").json()
    # `dinge` und `uebergaben` (Übergaben per Ziehen) kamen dazu; die bisherigen Felder bleiben
    assert set(j) == {"ok", "count", "apps", "dinge", "uebergaben"} and j["count"] == len(j["apps"]) > 0
    assert {"tool", "name", "title", "description", "inputSchema", "_meta", "scope", "hatUi"} <= set(j["apps"][0])


def test_etag_aendert_sich_mit_dem_inhalt(client, reg):
    e1 = client.get("/hub/apps").headers["etag"]
    del reg.tools["probe.gut"]
    r = client.get("/hub/apps", headers={"If-None-Match": e1})
    assert r.status_code == 200 and r.headers["etag"] != e1


# ── ui://-Dateien nach Aenderungszeit ─────────────────────────────────────────────────────────────


@pytest.fixture
def ui(tmp_path, monkeypatch):
    (tmp_path / "x.html").write_text("<style>/*STIL*/</style><p>eins</p><script>/*BRUECKE*/</script>", encoding="utf-8")
    (tmp_path / "_stil.css").write_text("b{}", encoding="utf-8")
    (tmp_path / "_bruecke.js").write_text("var a=1", encoding="utf-8")
    monkeypatch.setattr(_oberflaeche, "UI_DIR", tmp_path)
    _oberflaeche._DATEI_ZWISCHENSPEICHER.clear()
    yield tmp_path
    _oberflaeche._DATEI_ZWISCHENSPEICHER.clear()


def test_oberflaeche_liest_jede_datei_nur_einmal(ui, monkeypatch):
    gelesen: list[str] = []
    orig = type(ui).read_text

    def zaehlen(self, *a, **kw):
        gelesen.append(self.name)
        return orig(self, *a, **kw)

    monkeypatch.setattr(type(ui), "read_text", zaehlen)
    a = _oberflaeche.oberflaeche("x.html")
    b = _oberflaeche.oberflaeche("x.html")
    assert a == b and "eins" in a and "b{}" in a and "var a=1" in a
    # beim zweiten Aufruf nichts mehr gelesen (die Glyphentabelle _symbole.json hat ihren eigenen lru_cache)
    assert [gelesen.count(n) for n in ("x.html", "_stil.css", "_bruecke.js")] == [1, 1, 1]


def test_oberflaeche_liest_neu_wenn_die_datei_sich_aendert(ui):
    assert "eins" in _oberflaeche.oberflaeche("x.html")
    datei = ui / "x.html"
    datei.write_text(datei.read_text(encoding="utf-8").replace("eins", "zwei"), encoding="utf-8")  # gleiche Laenge
    st = datei.stat()
    os.utime(datei, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert "zwei" in _oberflaeche.oberflaeche("x.html")
    stil = ui / "_stil.css"
    stil.write_text("i{}", encoding="utf-8")
    os.utime(stil, ns=(st.st_atime_ns, st.st_mtime_ns + 9_000_000_000))
    assert "i{}" in _oberflaeche.oberflaeche("x.html")


# ── Herkunft und Inhaltstyp ───────────────────────────────────────────────────────────────────────

HOSTS = herkunft.erlaubte_hosts("")


@pytest.fixture
def geschuetzt(reg) -> TestClient:
    async def entwicklung(request):
        from starlette.responses import JSONResponse

        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/hub/call", hub_server.rest_call, methods=["POST"]),
            Route("/hub/app-call", hub_server.rest_app_call, methods=["POST"]),
            Route("/hub/apps", hub_server.rest_apps, methods=["GET"]),
            Route("/hub/os/melden", hub_server.rest_call, methods=["POST"]),  # nur fuer die Kopfpruefung
            Route("/hub/entwicklung/melden", entwicklung, methods=["POST"]),
            Route("/health", entwicklung, methods=["GET"]),
        ],
        middleware=[Middleware(herkunft.HerkunftMiddleware)],
    )
    return TestClient(app)


JSON_KOPF = {"content-type": "application/json"}


def test_ohne_origin_bleibt_erlaubt(geschuetzt):
    """curl, Server-zu-Server, Agent im Cluster: kein Origin-Kopf."""
    r = geschuetzt.post("/hub/app-call", json={"tool": "probe.gut"})
    assert r.status_code == 200 and r.json()["ok"] is True




@pytest.mark.parametrize(
    "origin",
    ["https://boese.example", "null", "http://fyos.example.org.boese.example", "https://example.org", "https://x.example.org", "file://", ""],
)
def test_fremder_origin_ist_403(geschuetzt, origin):
    r = geschuetzt.post("/hub/app-call", json={"tool": "probe.gut"}, headers={"Origin": origin})
    assert r.status_code == 403
    j = r.json()
    assert j["ok"] is False and j["kind"] == "fremde_herkunft" and "Origin" in j["error"]


def test_cross_site_ist_403_auch_mit_eigenem_origin(geschuetzt):
    r = geschuetzt.post("/hub/app-call", json={"tool": "probe.gut"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json()["kind"] == "fremde_herkunft"
    r = geschuetzt.post(
        "/hub/app-call", json={"tool": "probe.gut"}, headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://fyos.example.org"}
    )
    assert r.status_code == 403


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_andere_fetch_metadaten_sind_erlaubt(geschuetzt, site):
    r = geschuetzt.post("/hub/app-call", json={"tool": "probe.gut"}, headers={"Sec-Fetch-Site": site})
    assert r.status_code == 200


def test_drive_by_text_plain_ist_zu_(geschuetzt):
    """Der Angriff: einfacher POST einer fremden Seite, text/plain, kein Preflight."""
    r = geschuetzt.post(
        "/hub/app-call",
        content=b'{"tool": "probe.gut"}',
        headers={"content-type": "text/plain", "Origin": "https://boese.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize("pfad", ["/hub/call", "/hub/app-call", "/hub/os/melden"])
def test_json_wege_verlangen_application_json(geschuetzt, pfad):
    for typ in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
        r = geschuetzt.post(pfad, content=b'{"tool": "probe.gut"}', headers={"content-type": typ})
        assert r.status_code == 415 and r.json()["kind"] == "bad_content_type"
    assert geschuetzt.post(pfad, content=b'{"tool": "probe.gut"}').status_code == 415  # ohne Inhaltstyp
    ok = geschuetzt.post(pfad, content=b'{"tool": "probe.gut"}', headers={"content-type": "application/json; charset=utf-8"})
    assert ok.status_code != 415


def test_lesende_methoden_und_andere_pfade_bleiben_unberuehrt(geschuetzt):
    assert geschuetzt.get("/hub/apps", headers={"Origin": "https://boese.example"}).status_code == 200
    assert geschuetzt.get("/health", headers={"Origin": "https://boese.example"}).status_code == 200




def test_echter_hub_hat_die_middleware_vorn(monkeypatch):
    monkeypatch.setattr(hub_server, "_REGISTRY", None)
    monkeypatch.setattr(hub_server, "_CONFIG", None)
    from pathlib import Path

    app = hub_server.build_app(str(Path(hub_server.__file__).parents[1] / "config.example.yaml"))
    assert app.user_middleware[0].cls is herkunft.HerkunftMiddleware
    c = TestClient(app)
    assert c.post("/hub/app-call", json={}, headers={"Origin": "https://boese.example"}).status_code == 403
    assert c.post("/hub/app-call", content=b"{}", headers={"content-type": "text/plain"}).status_code == 415
    assert c.post("/hub/app-call", json={}).status_code == 403  # ohne Herkunft durch: kein Flaechen-Werkzeug, aber nicht 415/403-Herkunft
    assert c.post("/hub/app-call", json={}).json()["kind"] == "not_an_app"
