"""Startskript der Shell: unter Kubernetes den kurzen Agent-Namen voll ausschreiben (web/nginx/18-fyos-agent-fqdn.envsh).

Testserver 02.11.2026: Der nginx-Resolver kennt keine Suchdomänen; `agent` blieb dort 502 „could not be resolved“.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
SKRIPT = WEB / "nginx" / "18-fyos-agent-fqdn.envsh"


def _fqdn(url: str, resolv: str, tmp_path) -> str:
    datei = tmp_path / "resolv.conf"
    datei.write_text(resolv)
    aus = subprocess.run(
        ["sh", "-c", f'. "{SKRIPT}" >/dev/null; printf %s "$FYOS_AGENT_UPSTREAM"'],
        env={"FYOS_AGENT_UPSTREAM": url, "FYOS_RESOLV_CONF": str(datei), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    return aus.stdout


K8S = "search fyos-os-test.svc.cluster.local svc.cluster.local cluster.local\nnameserver 192.0.2.53\n"


def test_kurzer_name_wird_unter_kubernetes_voll(tmp_path):
    assert _fqdn("http://agent:18438", K8S, tmp_path) == "http://agent.fyos-os-test.svc.cluster.local:18438"


def test_name_mit_punkt_bleibt(tmp_path):
    assert _fqdn("http://agent.anders:18438", K8S, tmp_path) == "http://agent.anders:18438"


def test_docker_compose_bleibt_unveraendert(tmp_path):
    assert _fqdn("http://agent:18438", "search fritz.box\nnameserver 127.0.0.11\n", tmp_path) == "http://agent:18438"


def test_das_bild_bringt_das_skript_mit():
    assert "nginx/18-fyos-agent-fqdn.envsh /docker-entrypoint.d/18-fyos-agent-fqdn.envsh" in (WEB / "Dockerfile").read_text()
