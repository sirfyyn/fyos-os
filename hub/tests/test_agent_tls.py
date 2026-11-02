"""TLS zum Vorgangs-Dienst (agent_tls): Vorgabe prüfen, CA-Datei oder abgeschaltete Prüfung für interne Netze."""

from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from mcp_hub import agent_tls
from mcp_hub import vorgaenge as VG

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


def _liste(url: str) -> list:
    return VG.Dienst(url).liste()


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT_CA", raising=False)
    monkeypatch.delenv("FYOS_AGENT_TLS_PRUEFEN", raising=False)


def test_vorgabe_prueft_und_lehnt_selbstsigniert_ab(gateway):
    url, _ = gateway
    assert agent_tls.kontext() is None
    with pytest.raises(VG.QuelleFehler, match="nicht erreichbar"):
        _liste(url)


def test_ca_datei_aus_der_umgebung(gateway, monkeypatch):
    url, cert = gateway
    monkeypatch.setenv("FYOS_AGENT_CA", cert)
    assert VG.Dienst(url).roh("GET", "/tickets")[0] == 200


def test_pruefung_abschaltbar_per_umgebung(gateway, monkeypatch):
    url, _ = gateway
    monkeypatch.setenv("FYOS_AGENT_TLS_PRUEFEN", "false")
    assert VG.Dienst(url).roh("GET", "/tickets")[0] == 200
    monkeypatch.setenv("FYOS_AGENT_TLS_PRUEFEN", "true")
    with pytest.raises(VG.QuelleFehler):
        _liste(url)


def test_falsche_ca_schlaegt_fehl_statt_ungeprueft_zu_verbinden(tmp_path):
    leer = tmp_path / "leer.pem"
    leer.write_text("kein zertifikat")
    with pytest.raises(Exception):
        agent_tls.kontext(str(leer))


def test_ca_gewinnt_vor_abgeschalteter_pruefung(gateway, tmp_path):
    ctx = agent_tls.kontext(gateway[1], False)
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_angemeldeter_vorgangs_dienst_nutzt_den_kontext_des_plugins(gateway):
    url, cert = gateway
    VG.dienst_anmelden(url, {}, lambda: agent_tls.kontext(cert))
    try:
        status, d = VG.quelle().roh("GET", "/tickets")
        assert status == 200 and d["ok"] is True
    finally:
        VG.dienst_anmelden(None)
    with pytest.raises(VG.QuelleFehler):
        VG.Dienst(url).roh("GET", "/tickets")
