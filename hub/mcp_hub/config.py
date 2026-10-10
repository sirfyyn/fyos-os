"""mcp_hub.config — Konfiguration des Hubs aus YAML und Umgebung.

Aufbau der YAML-Datei (alles optional)::

    host: 0.0.0.0
    port: 8080
    path: /mcp
    circuit_breaker: {failure_threshold: 5, timeout_sec: 30, half_open_max_calls: 3, enabled: true}
    plugins:
      - name: audit
        module: mcp_hub.plugins.audit      # leer lassen: das Plugin kommt dann aus der Entry-Point-Gruppe
        class: AuditPlugin                 # optional
        enabled: true
        config: {}                         # wird dem Plugin als Attribut ``config`` mitgegeben
        secrets: [MEIN_TOKEN]              # werden aus der Umgebung (oder /run/secrets/<name>) aufgeloest

Plugins, die als Paket installiert sind und die Entry-Point-Gruppe ``mcp_hub.plugins`` bedienen, laden auch
ohne Eintrag. Ein Eintrag braucht es nur fuer Konfiguration, Geheimnisse oder ``enabled: false``.

Umgebung (alles optional):
    MCP_HUB_CONFIG_PATH   Pfad der YAML-Datei (Vorgabe: ./config.yaml; fehlt sie, laden nur Entry-Point-Plugins)
    MCP_HUB_HOST          Bind-Adresse (Vorgabe 0.0.0.0)
    MCP_HUB_PORT          Port (Vorgabe 8080)
    MCP_HUB_PATH          Pfad des MCP-Endpunkts (Vorgabe /mcp)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# Kubernetes setzt <DIENST>_PORT=tcp://… in die Umgebung; das kollidiert mit der Zahl-Auswertung.
# Deshalb zuerst MCP_HUB_SERVER_*, dann MCP_HUB_*, und ein unlesbarer Wert faellt auf die Vorgabe zurueck.
def _safe_port(primary: str, legacy: str, default: str) -> int:
    raw = os.getenv(primary) or os.getenv(legacy) or default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


DEFAULT_HOST = os.getenv("MCP_HUB_SERVER_HOST") or os.getenv("MCP_HUB_HOST", "0.0.0.0")  # noqa: S104
DEFAULT_PORT = _safe_port("MCP_HUB_SERVER_PORT", "MCP_HUB_PORT", "8080")
DEFAULT_PATH = os.getenv("MCP_HUB_SERVER_PATH") or os.getenv("MCP_HUB_PATH", "/mcp")
DEFAULT_CONFIG_PATH = os.getenv("MCP_HUB_CONFIG_PATH", "config.yaml")


@dataclass
class PluginConfig:
    """Ein Eintrag der ``plugins:``-Liste."""

    name: str
    """Name des Plugins (muss zu ``HubPlugin.name`` passen)."""

    module: str = ""
    """Python-Modulpfad mit der Plugin-Klasse. Leer: das Plugin kommt aus der Entry-Point-Gruppe
    ``mcp_hub.plugins`` (Entry-Point-Name = ``name``)."""

    class_name: str = ""
    """Klassenname im Modul. Leer: die erste HubPlugin-Unterklasse des Moduls."""

    enabled: bool = True
    """Abgeschaltete Plugins ueberspringt die Registry (auch wenn sie ueber Entry-Point installiert sind)."""

    config: dict[str, Any] = field(default_factory=dict)
    """Plugin-eigene Konfiguration; das Plugin findet sie als Attribut ``config``."""

    secrets: list["SecretBinding"] = field(default_factory=list)
    """Geheimnisse, die aus der Umgebung gelesen werden."""


@dataclass
class SecretBinding:
    """Ein Geheimnis fuer ein Plugin."""

    name: str
    """Logischer Name, zugleich Name der Umgebungsvariable (oder Datei unter /run/secrets)."""

    env: str = ""
    """Optional: zusaetzlicher Name der Umgebungsvariable, unter der das Plugin das Geheimnis findet."""


@dataclass
class HubConfig:
    """Oberste Ebene der Hub-Konfiguration."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    path: str = DEFAULT_PATH
    plugins: list[PluginConfig] = field(default_factory=list)
    circuit_breaker: dict[str, Any] = field(default_factory=dict)
    """Vorgaben des Sicherungsschalters fuer jedes Plugin: ``failure_threshold``, ``timeout_sec``,
    ``half_open_max_calls``, ``enabled``. Leer = Vorgaben von ``CircuitBreakerConfig``."""
    aufruf_zeitlimit_s: float | None = None
    """Zeitlimit je Plugin-Aufruf in Sekunden. ``None`` = ``AUFRUF_ZEITLIMIT_S`` (120 s), ``0`` = kein Limit.
    Einzelne Werkzeuge setzen ihr eigenes (``ToolDescriptor.zeitlimit_s``)."""
    plugins_von_selbst: bool = False
    """Jedes Modul unter ``mcp_hub/plugins/`` mit einer HubPlugin-Klasse laedt ohne Eintrag. Aus in Tests und
    Beispielkonfigurationen (dort soll genau die Liste gelten)."""


def load_config(path: str | Path | None = None) -> HubConfig:
    """Hub-Konfiguration aus YAML lesen. Fehlt die Datei, gilt ein leerer Hub (nur Entry-Point-Plugins)."""
    config_path = Path(path or DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        logger.warning("mcp_hub.config: %s nicht gefunden — leere Vorgabe", config_path)
        return HubConfig()

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"mcp_hub.config: top-level must be a mapping, got {type(raw)}")

    plugins: list[PluginConfig] = []
    for idx, entry in enumerate(raw.get("plugins", []) or []):
        if not isinstance(entry, dict):
            raise ValueError(f"mcp_hub.config: plugins[{idx}] must be a mapping")
        if "name" not in entry:
            raise ValueError(f"mcp_hub.config: plugins[{idx}] missing 'name'")
        plugins.append(
            PluginConfig(
                name=str(entry["name"]),
                module=str(entry.get("module", "") or ""),
                class_name=str(entry.get("class", "") or ""),
                enabled=bool(entry.get("enabled", True)),
                config=dict(entry.get("config", {}) or {}),
                secrets=_parse_secret_bindings(entry.get("secrets", []) or []),
            )
        )

    cb_raw = raw.get("circuit_breaker", {}) or {}
    if not isinstance(cb_raw, dict):
        raise ValueError(
            f"mcp_hub.config: circuit_breaker must be a mapping, got {type(cb_raw).__name__}"
        )

    return HubConfig(
        host=str(raw.get("host", DEFAULT_HOST)),
        port=int(raw.get("port", DEFAULT_PORT)),
        path=str(raw.get("path", DEFAULT_PATH)),
        plugins=plugins,
        circuit_breaker=dict(cb_raw),
        aufruf_zeitlimit_s=(
            float(raw["aufruf_zeitlimit_s"]) if raw.get("aufruf_zeitlimit_s") is not None else None
        ),
        plugins_von_selbst=bool(raw.get("plugins_von_selbst", False)),
    )


def _parse_secret_bindings(raw_items: list[Any]) -> list[SecretBinding]:
    bindings: list[SecretBinding] = []
    for idx, item in enumerate(raw_items):
        if isinstance(item, str):
            bindings.append(SecretBinding(name=item))
            continue
        if not isinstance(item, dict):
            raise ValueError(
                f"mcp_hub.config: secrets[{idx}] must be a string or mapping, got {type(item)}"
            )
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"mcp_hub.config: secrets[{idx}] missing 'name'")
        bindings.append(
            SecretBinding(
                name=name,
                env=str(item.get("env") or "").strip(),
            )
        )
    return bindings


def normalize_secret_env_name(secret_name: str) -> str:
    """Namen wie ``mein-api-token`` in Umgebungsform bringen (``MEIN_API_TOKEN``)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", secret_name).strip("_").upper()


def _aus_datei(secret_name: str) -> str:
    """Geheimnis aus ``/run/secrets/<name>`` (Docker/Compose-Secrets); Verzeichnis ueber FYOS_SECRETS_DIR."""
    basis = Path(os.getenv("FYOS_SECRETS_DIR", "/run/secrets"))
    for name in (secret_name, normalize_secret_env_name(secret_name), normalize_secret_env_name(secret_name).lower()):
        if "/" in name or name.startswith("."):
            continue
        datei = basis / name
        try:
            if datei.is_file():
                return datei.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    return ""


def inject_secrets(secret_bindings: list[SecretBinding | str]) -> dict[str, str]:
    """Geheimnisse nach Namen aufloesen, ohne sie zu protokollieren.

    Reihenfolge je Geheimnis: 1. Umgebungsvariable ``env`` der Bindung, 2. Variable mit dem genauen Namen,
    3. Variable in Umgebungsform (``mein-token`` -> ``MEIN_TOKEN``), 4. Datei unter ``/run/secrets``.
    """
    if not secret_bindings:
        return {}

    resolved: dict[str, str] = {}
    for binding in secret_bindings:
        explicit_env = ""
        if isinstance(binding, str):
            secret_name = binding
        else:
            secret_name = binding.name
            explicit_env = binding.env
        if not secret_name:
            continue

        value = os.getenv(explicit_env, "").strip() if explicit_env else ""
        if not value:
            value = os.getenv(secret_name, "").strip()
        if not value:
            value = os.getenv(normalize_secret_env_name(secret_name), "").strip()
        if not value:
            value = _aus_datei(secret_name)

        if value:
            resolved[secret_name] = value
        else:
            logger.warning("mcp_hub.config: secret %s unresolved", secret_name)
    return resolved
