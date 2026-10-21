"""TLS zum Gateway des Agenten: Vorgabe prüfen, CA-Datei oder abgeschaltete Prüfung für interne Netze."""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from mcp_hub import agent_tls, kv
from mcp_hub import vorgaenge as VG
from mcp_hub.plugins.openclaw import BrueckeFehler, OpenClawPlugin

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl fehlt")


class _Antwort(BaseHTTPRequestHandler):
    def _senden(self) -> None:
        roh = json.dumps({"ok": True, "payload": {"da": True}, "status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self) -> None:  # noqa: N802
        self._senden()

    def do_POST(self) -> None:  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._senden()

    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture(scope="module")
def gateway(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "gateway.crt", d / "gateway.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
         "-days", "2", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
        check=True, capture_output=True,
    )
    server = HTTPServer(("127.0.0.1", 0), _Antwort)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{server.server_address[1]}", str(cert)
    server.shutdown()


def _plugin(url: str, **cfg) -> OpenClawPlugin:
    return OpenClawPlugin(config={"gateway_url": url, "token": "t", "kv_fabrik": kv.SpeicherKv, **cfg})


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT_CA", raising=False)
    monkeypatch.delenv("FYOS_AGENT_TLS_PRUEFEN", raising=False)


def test_vorgabe_prueft_und_lehnt_selbstsigniert_ab(gateway):
    url, _ = gateway
    assert agent_tls.kontext() is None
    with pytest.raises(BrueckeFehler, match="nicht erreichbar"):
        _plugin(url).rpc("cron.list")


def test_ca_datei_aus_der_konfiguration(gateway):
    url, cert = gateway
    p = _plugin(url, agent_ca=cert)
    assert p.rpc("cron.list") == {"da": True}
    assert p._get(url + "/healthz")[0] == 200


def test_ca_datei_aus_der_umgebung(gateway, monkeypatch):
    url, cert = gateway
    monkeypatch.setenv("FYOS_AGENT_CA", cert)
    assert _plugin(url).rpc("cron.list") == {"da": True}


def test_pruefung_abschaltbar_per_konfig_und_umgebung(gateway, monkeypatch):
    url, _ = gateway
    assert _plugin(url, agent_tls_pruefen=False).rpc("cron.list") == {"da": True}
    monkeypatch.setenv("FYOS_AGENT_TLS_PRUEFEN", "false")
    assert _plugin(url).rpc("cron.list") == {"da": True}
    monkeypatch.setenv("FYOS_AGENT_TLS_PRUEFEN", "true")
    with pytest.raises(BrueckeFehler):
        _plugin(url).rpc("cron.list")


def test_falsche_ca_schlaegt_fehl_statt_ungeprueft_zu_verbinden(gateway, tmp_path):
    url, _ = gateway
    leer = tmp_path / "leer.pem"
    leer.write_text("kein zertifikat")
    with pytest.raises(Exception):
        _plugin(url, agent_ca=str(leer)).rpc("cron.list")


def test_ca_gewinnt_vor_abgeschalteter_pruefung(gateway, tmp_path):
    ctx = agent_tls.kontext(gateway[1], False)
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_vorgangs_dienst_nutzt_dieselbe_einstellung(gateway):
    url, cert = gateway
    VG.dienst_anmelden(url, {}, _plugin(url, agent_ca=cert)._kontext)
    try:
        status, d = VG.quelle().roh("GET", "/tickets")
        assert status == 200 and d["ok"] is True
    finally:
        VG.dienst_anmelden(None)
    with pytest.raises(VG.QuelleFehler):
        VG.Dienst(url).roh("GET", "/tickets")
