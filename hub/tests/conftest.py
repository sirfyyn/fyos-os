"""Gemeinsame pytest-Vorgaben fuer die Hub-Tests.

``MCP_HUB_AUDIT_SKIP_QDRANT=1`` verhindert, dass Tests ein echtes Qdrant ansprechen. Audit-Tests, die einen
Qdrant-Ersatz einspeisen (Factory), ueberschreiben das mit monkeypatch.
"""

from __future__ import annotations

import os


def pytest_configure(config):
    os.environ.setdefault("MCP_HUB_AUDIT_SKIP_QDRANT", "1")
    # Tests laufen ohne Redis, Qdrant und Embedding-Dienst, egal was die Umgebung des Rechners setzt.
    for name in ("REDIS_URL", "QDRANT_URL", "FYOS_EMBED_URL", "HUB_SUCHE_EMBED_URL", "FYOS_OIDC_ISSUER"):
        os.environ.pop(name, None)
