"""mcp_hub.plugins.audit — passives Audit-Plugin.

Subscribes to the registry's ``on_call`` hook at ``init()`` time — every Hub
tool-call produces an :class:`AuditEvent` persisted via :class:`AuditLogger`.

Exposes four passive read-only tools:
    ``audit.stats()``            — telemetry snapshot
    ``audit.nutzung(tage)``      — je Werkzeug bewusste Aufrufe, Abfragen, letzte bewusste Nutzung
    ``audit.recall(query, limit)`` — semantic-search over past tool-calls
    ``audit.recent(limit, ...)`` — chronological tail with optional filter

The plugin itself is NEVER invoked by the audit-hook (infinite-loop guard in
``register_call_hook`` + self-call skip below). Its read-tools are safe to call
recursively because they are themselves logged, but that's intentional — self-
audit is desirable for traceability.

Config (from Hub YAML ``plugins[].config``):
    qdrant_url         (default: Umgebung QDRANT_URL; leer = Puffermodus ohne Qdrant)
    embed_url          (default: Umgebung FYOS_EMBED_URL; leer = keine Vektoren)
    collection_name    (default: ``mcp_audit_log``)
    embedding_model    (default: Umgebung FYOS_EMBED_MODEL)
    skip_self          (default: True — don't log audit.* calls themselves)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from ..audit_log import (
    DEFAULT_COLLECTION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBED_URL,
    DEFAULT_QDRANT_URL,
    AuditEvent,
    AuditLogger,
    art_von_aufrufer,
)
from ..plugin import HubPlugin, ToolDescriptor

logger = logging.getLogger(__name__)

# Abfragen im Sekundentakt der Shell: je Aufruf ein Embedding und ein Qdrant-Punkt fuellten das Log mit
# Rauschen (shell.abholen stand oben in jedem `recent`). Sie werden nur gezaehlt; Fehlschlaege landen trotzdem im
# Log. Plugins mit eigenen Takt-Werkzeugen ergaenzen die Liste ueber die Plugin-Config `nur_zaehlen`.
NUR_ZAEHLEN = frozenset(
    {
        "shell.abholen",
        "shell.merken",
    }
)


class AuditPlugin(HubPlugin):
    """Passive logger + recall-surface for cross-session tool-call history."""

    name = "audit"
    description = (
        "Passive audit-log of all Hub tool-calls with Qdrant semantic-recall. "
        "Subscribes to the registry on_call hook; exposes stats/recall/recent."
    )
    version = "0.1.0"

    def __init__(self) -> None:
        self._audit_logger: Optional[AuditLogger] = None
        self._skip_self = True
        self._registered_with: Optional[Any] = None  # PluginRegistry ref
        self._nur_zaehlen: frozenset[str] = NUR_ZAEHLEN
        self._takt: dict[str, int] = {}
        self._takt_seit = time.time()
        self._takt_lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------

    def register(self) -> None:
        cfg = getattr(self, "config", {}) or {}
        self._skip_self = bool(cfg.get("skip_self", True))
        if cfg.get("nur_zaehlen") is not None:
            self._nur_zaehlen = frozenset(str(x) for x in cfg.get("nur_zaehlen") or [])
        self._audit_logger = AuditLogger(
            qdrant_url=str(cfg.get("qdrant_url", DEFAULT_QDRANT_URL)),
            embed_url=str(cfg.get("embed_url", DEFAULT_EMBED_URL)),
            collection_name=str(cfg.get("collection_name", DEFAULT_COLLECTION)),
            embedding_model=str(cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
            qdrant_client_factory=cfg.get("qdrant_client_factory"),
            embedder=cfg.get("embedder"),
        )
        # Best-effort; may return False in buffer-only mode.
        self._audit_logger.init_collection()

    def init(self) -> None:
        """Subscribe to the registry on_call hook. Only runs once Hub ready."""
        # Registration happens in register_as_listener() — called by server
        # build_app() AFTER the registry is fully built. No-op here to avoid
        # double-registration during ``_register_one`` construction.
        return None

    def register_as_listener(self, registry: Any) -> None:
        """Attach this plugin to a PluginRegistry via its on_call hook.

        Called from ``mcp_hub.server.build_app()`` after build_registry(). Safe
        to re-call — registry de-dupes hooks.
        """
        if self._audit_logger is None:
            logger.warning("audit: register_as_listener before register() — skipped")
            return
        self._registered_with = registry

        def _on_call(ev: AuditEvent) -> None:
            if self._skip_self and ev.plugin_name == self.name:
                return
            if ev.tool_name in self._nur_zaehlen and ev.result_status == "ok":
                with self._takt_lock:
                    self._takt[ev.tool_name] = self._takt.get(ev.tool_name, 0) + 1
                return
            assert self._audit_logger is not None
            self._audit_logger.log_event(ev)

        try:
            registry.register_call_hook(_on_call)
        except AttributeError:
            logger.warning("audit: registry has no register_call_hook API")

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="stats",
                description=(
                    "Audit-log telemetry: Ereignisse gesamt und in 24 h, Top-Plugins und -Aufrufer "
                    "(24 h), dazu die nur gezaehlten Sekundentakt-Abfragen."
                ),
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                tags=["audit", "observability", "read"],
            ),
            ToolDescriptor(
                name="nutzung",
                description=(
                    "Nutzung je Werkzeug in `tage` Tagen (Vorgabe 30), getrennt nach Art: bewusste Aufrufe "
                    "(Mensch oder Agent fragt gezielt), Abfragen (Kachel-Auffrischung, Polling, Laeufer) und "
                    "unbekannte (kein Absender, eine Luecke), dazu die letzte bewusste Nutzung. Auch "
                    "Werkzeuge ohne jeden Aufruf stehen drin. Nur gezaehlte Sekundentakt-Werkzeuge "
                    "(audit.stats) fehlen im Log."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"tage": {"type": "integer", "minimum": 1, "maximum": 90}},
                    "additionalProperties": False,
                },
                tags=["audit", "observability", "read"],
            ),
            ToolDescriptor(
                name="recall",
                description="Semantic recall over historic Hub tool-calls.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                        "filter": {"type": "object"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                tags=["audit", "recall", "read"],
            ),
            ToolDescriptor(
                name="recent",
                description="Chronological tail of audit-events (newest first, nach timestamp sortiert).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                        "filter": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                tags=["audit", "recall", "read"],
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if self._audit_logger is None:
            raise RuntimeError("audit plugin not registered")

        if method == "stats":
            return {**self._audit_logger.stats(), **self._takt_stand()}

        if method == "nutzung":
            return self.nutzung(int(args.get("tage", 30)))

        if method == "recall":
            query = args.get("query", "")
            if not isinstance(query, str):
                raise TypeError("audit.recall requires 'query' (str)")
            limit = int(args.get("limit", 10))
            flt = args.get("filter")
            events = self._audit_logger.semantic_recall(query, limit=limit, filter=flt)
            return {"count": len(events), "events": [_event_to_dict(e) for e in events]}

        if method == "recent":
            limit = int(args.get("limit", 20))
            flt = args.get("filter")
            events = self._audit_logger.recent(limit=limit, filter=flt)
            return {"count": len(events), "events": [_event_to_dict(e) for e in events]}

        raise ValueError(f"AuditPlugin has no tool {method!r}")

    def nutzung(self, tage: int = 30) -> dict[str, Any]:
        """Je Werkzeug bewusst/abfrage/unbekannt und letzte bewusste Nutzung (siehe `audit_log.art_aus`)."""
        assert self._audit_logger is not None
        tage = max(1, min(int(tage), 90))
        jetzt = time.time()
        gezaehlt = self._audit_logger.nutzung_je_werkzeug(jetzt - tage * 86400)
        reg = self._registered_with
        for fqtn in sorted(getattr(reg, "tools", None) or {}):
            gezaehlt.setdefault(
                fqtn, {"bewusst": 0, "abfrage": 0, "unbekannt": 0, "letzte_bewusst": None}
            )
        zeilen = [
            {
                "werkzeug": w,
                "bewusst": z["bewusst"],
                "abfrage": z["abfrage"],
                "unbekannt": z["unbekannt"],
                "letzte_bewusst": z["letzte_bewusst"],
                "nur_gezaehlt": w in self._nur_zaehlen,
            }
            for w, z in gezaehlt.items()
        ]
        zeilen.sort(key=lambda r: (-r["bewusst"], -r["abfrage"], r["werkzeug"]))
        summe = {a: sum(r[a] for r in zeilen) for a in ("bewusst", "abfrage", "unbekannt")}
        return {
            "tage": tage,
            "summe": summe,
            "ohne_bewusste_nutzung": sum(1 for r in zeilen if r["bewusst"] == 0),
            "werkzeuge": zeilen,
            "hinweis": (
                "Art je Aufruf: Kopfzeile X-Hub-Art (Shell), sonst Aufrufername; `unbekannt` = kein "
                "Absender. Aufrufe ohne Art werden nach Aufrufername eingeordnet; die Shell "
                "zaehlt dort als unbekannt."
            ),
        }

    def _takt_stand(self) -> dict[str, Any]:
        """Nur gezaehlte Sekundentakt-Abfragen (seit Pod-Start, je Replika)."""
        with self._takt_lock:
            zahlen = dict(self._takt)
        return {
            "nur_gezaehlt": {
                "werkzeuge": sorted(self._nur_zaehlen),
                "aufrufe": zahlen,
                "seit": self._takt_seit,
                "hinweis": "nicht im Log (Sekundentakt); Fehlschlaege werden dennoch protokolliert",
            }
        }

    def health(self) -> dict[str, Any]:
        if self._audit_logger is None:
            return {"ok": False, "status": "not_registered"}
        stats = self._audit_logger.stats()
        return {
            "ok": True,
            "status": "healthy",
            "collection_ready": stats["collection_ready"],
            "buffer_len": stats["buffer_len"],
            "total_logged": stats["total_logged"],
        }

    def metrics(self) -> dict[str, Any]:
        if self._audit_logger is None:
            return {}
        return self._audit_logger.stats()


def _event_to_dict(ev: AuditEvent) -> dict[str, Any]:
    """Compact wire-representation — omits embedding_vector for size."""
    return {
        "timestamp": ev.timestamp,
        "session_id": ev.session_id,
        "caller": ev.caller,
        "tool_name": ev.tool_name,
        "plugin_name": ev.plugin_name,
        "arguments": ev.arguments,
        "result_status": ev.result_status,
        "latency_ms": ev.latency_ms,
        "error": ev.error,
        "art": ev.art or art_von_aufrufer(ev.caller),
    }
