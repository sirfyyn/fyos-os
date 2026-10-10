"""Protokollversionen des Hubs — eine Quelle.

MCP kennt seit 2026-07-28 zwei Zeitalter:

  * handshake (`initialize`, Sitzung): 2024-11-05 bis 2025-11-25 — so sprechen die meisten Clients (Chat-Konnektoren,
    Code-Agenten, der Python-SDK-Client im Modus `legacy`);
  * modern (zustandslos, `_meta` je Anfrage, `server/discover`, Kopfzeilen `Mcp-Method`/`Mcp-Name`): 2026-07-28.

Der Hub (`mcp_hub.server`) spricht beides, solange das SDK es kann (mcp 2.x; mcp 1.x kennt nur handshake). Ein von
Hand geschriebenes Tor, das nur den Handshake spricht, sagt das einem modernen Client ausdruecklich (HTTP 400, -32022
mit der Liste), statt ihm eine Antwort im alten Format zu geben, die er fuer modern halten koennte.

Diese Datei hat keine Abhaengigkeiten (kein SDK, kein JWT), damit Hub, Plugins und Tests sie gleich lesen.
"""

from __future__ import annotations

from typing import Any

#: Ein handshake-only-Tor bietet 2025-11-25 zuerst an: erst damit gelten `icons` und `title` (Symbole der Apps in der Konnektorliste).
TOR_PROTOKOLLE: tuple[str, ...] = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

#: Modern im Sinn der Spezifikation: Version steht in `params._meta` jeder Anfrage.
MODERN: tuple[str, ...] = ("2026-07-28",)

#: Schluessel der Huelle in `params._meta` (Spezifikation 2026-07-28, basic/index „Per-request protocol fields“).
VERSION_SCHLUESSEL = "io.modelcontextprotocol/protocolVersion"

#: JSON-RPC-Fehler `UnsupportedProtocolVersion`; HTTP-Status dazu 400 (basic/transports/streamable-http).
FEHLER_VERSION = -32022


def sdk_protokolle() -> dict[str, Any]:
    """Was das installierte SDK spricht: `{"sdk": "mcp 2.1.1", "linie": 2, "handshake": [...], "modern": [...]}`."""
    try:
        from importlib.metadata import version as _version  # noqa: PLC0415

        sdk = f"mcp {_version('mcp')}"
    except Exception:  # noqa: BLE001
        sdk = "mcp (Version unbekannt)"
    try:
        from mcp_types import version as v  # noqa: PLC0415 — mcp >= 2.0

        return {
            "sdk": sdk,
            "linie": 2,
            "handshake": list(v.HANDSHAKE_PROTOCOL_VERSIONS),
            "modern": list(v.MODERN_PROTOCOL_VERSIONS),
        }
    except ModuleNotFoundError:
        pass
    try:
        from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS  # noqa: PLC0415 — mcp 1.x

        return {"sdk": sdk, "linie": 1, "handshake": list(SUPPORTED_PROTOCOL_VERSIONS), "modern": []}
    except Exception:  # noqa: BLE001
        return {"sdk": sdk, "linie": 0, "handshake": [], "modern": []}


def modern_angefragt(nachricht: dict[str, Any], kopf_version: str | None) -> str | None:
    """Die moderne Version, die diese Anfrage verlangt — oder None (dann handshake-Zeitalter).

    Massgeblich ist die Huelle in `params._meta`; ihr Schluessel gibt es nur ab 2026-07-28. Ohne Huelle zaehlt die
    Kopfzeile `MCP-Protocol-Version`, aber nur, wenn sie eine moderne Version nennt (handshake-Clients senden
    dort 2025-06-18 oder 2025-11-25 und gehoeren nicht hierher).
    """
    par = nachricht.get("params")
    meta = par.get("_meta") if isinstance(par, dict) else None
    if isinstance(meta, dict) and VERSION_SCHLUESSEL in meta:
        v = meta[VERSION_SCHLUESSEL]
        return v if isinstance(v, str) and v else "?"
    if kopf_version and kopf_version in MODERN:
        return kopf_version
    return None
