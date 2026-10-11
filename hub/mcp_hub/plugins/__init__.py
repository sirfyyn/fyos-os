"""mcp_hub.plugins — die Kern-Plugins des Hubs.

Referenz-Plugins (``example_echo``, ``example_math``), Betrieb (``audit``, ``event_bus_publisher``), Verzeichnisse
(``skills``, ``werkstatt``), Werkzeugkasten (``mcp_kasten``), Shell-Anordnung (``shell``), Verbindung zur Shell
(``os``), gebaute Ansichten (``gui``) und eine kleine Beispiel-App (``beispiel_app``). Weitere Plugins kommen als eigene Pakete über die
Entry-Point-Gruppe ``mcp_hub.plugins`` (siehe ``docs/HUB-VERTRAG.md``).
"""

from __future__ import annotations
