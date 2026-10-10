"""mcp_hub — der MCP-Hub von FYOS (Federated Mode).

Das Paket enthaelt:
- den Hub-Kern (MCP-Server mit Meta-Werkzeugen und REST-Wegen fuer die Shell),
- die Plugin-Registry (YAML-Konfiguration und Entry-Point-Gruppe ``mcp_hub.plugins``),
- die Basisklasse ``HubPlugin`` fuer Plugins, die im Prozess des Hubs laufen,
- die Kern-Plugins unter ``mcp_hub.plugins``.

Persoenliches (Hosts, Konten, Dienste eines bestimmten Zuhauses) gehoert nicht in diesen Kern,
sondern in Plugin-Pakete. Hosts, Redis, Qdrant und Anmeldung kommen aus Konfiguration oder Umgebung.
"""

from __future__ import annotations

__version__ = "0.1.1"
