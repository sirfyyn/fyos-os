"""mcp_hub.audit_log — Audit-Protokoll für alle Werkzeugaufrufe des Hubs (Qdrant optional).

Zweck:
    Jeder ``registry.call()`` erzeugt ein :class:`AuditEvent`. Der :class:`AuditLogger` bettet den
    Argument-/Ergebnistext über einen OpenAI-kompatiblen Embedding-Dienst ein (``mcp_hub.embedding``) und legt das
    Ereignis in der Qdrant-Sammlung ``mcp_audit_log`` ab. Verbraucher:

        1. **Recall über Sitzungen hinweg** — ``hub__audit_log(query)`` liefert semantisch ähnliche frühere Aufrufe.
        2. **Nutzungsmessung** — ``nutzung_je_werkzeug`` zählt Aufrufe nach Art (bewusst / Abfrage / unbekannt).

Ohne Zusatzdienste läuft alles weiter:
    - ``qdrant-client`` ist eine OPTIONALE Abhängigkeit, und ``QDRANT_URL`` leer heißt: kein Qdrant. Dann arbeitet der
      AuditLogger im Puffermodus (begrenzter Ringpuffer) und meldet das einmal beim Start.
    - Embeddings sind Kür. Ist kein Dienst eingerichtet (``FYOS_EMBED_URL``) oder nicht erreichbar, wird das Ereignis
      ohne Vektor gespeichert; ``semantic_recall()`` fällt auf Textsuche im Puffer bzw. chronologische Ordnung zurück.
    - Weder Qdrant noch der Embedding-Dienst dürfen den Hub zum Absturz bringen. Jede öffentliche Methode fängt Fehler.

Thread-Sicherheit:
    Der Ringpuffer ist mit ``threading.Lock`` gesichert. Qdrant-Aufrufe laufen synchron.

Schema (ein Qdrant-Punkt je AuditEvent):
    id              — uuid4
    vector          — Embedding (Länge ``embedding_dim``, Nullvektor, wenn keines da ist)
    payload         — AuditEvent.to_payload()
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional

from . import embedding
from .embedding import Ziel

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "mcp_audit_log"
DEFAULT_EMBEDDING_DIM = 768  # Länge der Vektoren des eingesetzten Modells; ändern, wenn das Modell andere liefert
#: Basisadresse des Embedding-Dienstes (OpenAI-Pfad /v1/embeddings); leer = keine Vektoren.
DEFAULT_EMBED_URL = os.getenv("FYOS_EMBED_URL", "").strip().rstrip("/")
DEFAULT_EMBEDDING_MODEL = os.getenv("FYOS_EMBED_MODEL", "embedding").strip() or "embedding"
#: Qdrant: leer = kein Qdrant (Puffermodus).
DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
DEFAULT_BUFFER_SIZE = 1000
DEFAULT_INDEXING_THRESHOLD = 1000

# ---------------------------------------------------------------------------
# Art des Aufrufs (Nutzung messen)
# ---------------------------------------------------------------------------
# Jeder Aufruf trägt eine Art: `bewusst` (Mensch oder Agent fragt gezielt), `abfrage` (Kachel, Polling,
# Wächter-Läufer, Prüfskripte) oder `unbekannt` (kein Absender, eine Lücke, die gezählt wird). Gesetzt wird sie an der
# Quelle (Kopfzeile `X-Hub-Art`); fehlt sie, entscheidet der Aufrufername.
ART_BEWUSST = "bewusst"
ART_ABFRAGE = "abfrage"
ART_UNBEKANNT = "unbekannt"
ART_WERTE = (ART_BEWUSST, ART_ABFRAGE, ART_UNBEKANNT)
#: Aufrufernamen (Kleinschreibung, fnmatch), die von sich aus nur abfragen. Überschreibbar mit der Umgebung
#: `HUB_ABFRAGE_AUFRUFER` (Komma getrennt).
ABFRAGE_AUFRUFER_VORGABE = (
    "wache*",
    "waechter*",
    "monitor*",
    "pruef*",
    "probe*",
    "rest:python-urllib*",
)


def _abfrage_muster() -> tuple[str, ...]:
    roh = os.getenv("HUB_ABFRAGE_AUFRUFER")
    if roh is None:
        return ABFRAGE_AUFRUFER_VORGABE
    return tuple(p.strip().lower() for p in roh.split(",") if p.strip())


def art_von_aufrufer(aufrufer: Optional[str]) -> str:
    """Art nach Aufrufername allein (ohne ausdrueckliche Kopfzeile).

    Ohne Namen oder mit `unknown`/`unbekannt` bleibt es `unbekannt`. Die Shell (`shell`) ist ohne `X-Hub-Art`
    ebenfalls `unbekannt`: Dort mischen sich Klick und Auffrischung, der Name allein sagt nichts.
    """
    name = (aufrufer or "").strip().lower()
    if name in ("", "unknown", "unbekannt", "shell", "fyos-web") or name.endswith((":unknown", ":unbekannt")):
        return ART_UNBEKANNT
    if any(fnmatch.fnmatchcase(name, m) for m in _abfrage_muster()):
        return ART_ABFRAGE
    return ART_BEWUSST


def art_aus(aufrufer: Optional[str], kopf_art: Optional[str] = None) -> str:
    """Art eines Aufrufs: gueltige Kopfzeile `X-Hub-Art` gewinnt, sonst der Aufrufername.

    Eine Kopfzeile ohne Absender (`unbekannt`) bleibt eine Luecke: ohne Namen gilt auch ein behauptetes `bewusst`
    nur, wenn der Aufrufer bekannt ist.
    """
    name = (aufrufer or "").strip().lower()
    wert = (kopf_art or "").strip().lower()
    if wert in (ART_BEWUSST, ART_ABFRAGE) and name not in ("", "unknown", "unbekannt"):
        return wert
    return art_von_aufrufer(aufrufer)


# ---------------------------------------------------------------------------
# AuditEvent dataclass
# ---------------------------------------------------------------------------


@dataclass
class AuditEvent:
    """One audit row — a single Hub tool-invocation.

    Attributes:
        timestamp: Unix-seconds float (``time.time()``) at dispatch start.
        session_id: Caller-provided or hub-generated session correlation-id.
        caller: Identity of the caller (``"agent"``, ``"shell"``, ``"unknown"``).
        tool_name: Fully-qualified tool-id (``"<plugin>.<tool>"``).
        plugin_name: Short plugin-name (derived from ``tool_name``).
        arguments: JSON-serialized arguments dict (capped for size).
        result_status: ``"ok" | "error" | "circuit_open" | "not_found" | ...``
        latency_ms: Wall-clock dispatch latency in ms.
        error: Error message on failure, ``None`` on success.
        embedding_vector: 768-dim embedding list, ``None`` if no embedding service is reachable.
    """

    timestamp: float
    session_id: str
    caller: str
    tool_name: str
    plugin_name: str
    arguments: str  # JSON-str of dict (size-capped)
    result_status: str
    latency_ms: float
    error: Optional[str] = None
    embedding_vector: Optional[list[float]] = None
    art: str = ""  # bewusst | abfrage | unbekannt (leer = ohne Artmessung geschrieben)

    # --- serialization -----------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        """Serialize for Qdrant payload. Embedding is stored in the vector-slot,
        not payload — so it's omitted here."""
        return {
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "caller": self.caller,
            "tool_name": self.tool_name,
            "plugin_name": self.plugin_name,
            "arguments": self.arguments,
            "result_status": self.result_status,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "art": self.art,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AuditEvent":
        """Reverse of :meth:`to_payload` — embedding is re-attached by caller."""
        return cls(
            timestamp=float(payload.get("timestamp", 0.0)),
            session_id=str(payload.get("session_id", "")),
            caller=str(payload.get("caller", "unknown")),
            tool_name=str(payload.get("tool_name", "")),
            plugin_name=str(payload.get("plugin_name", "")),
            arguments=str(payload.get("arguments", "{}")),
            result_status=str(payload.get("result_status", "unknown")),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            error=payload.get("error"),
            embedding_vector=None,
            art=str(payload.get("art") or ""),
        )

    def embedding_text(self) -> str:
        """Text used for embedding. Concatenates tool-id + args + error for
        maximal semantic-retrieval-surface."""
        parts = [self.tool_name, self.arguments]
        if self.error:
            parts.append(self.error)
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# AuditLogger — Qdrant wrapper + in-memory fallback
# ---------------------------------------------------------------------------


class AuditLogger:
    """Wraps Qdrant + an embedding service for audit-log persistence + semantic-recall.

    All external IO is best-effort. If Qdrant is unreachable at ``log_event``,
    the event is pushed into a bounded in-memory deque (``_buffer``). On next
    ``init_collection()`` the buffer is flushed. Semantic-recall falls back to
    buffer-scan when Qdrant is down.

    Usage:
        >>> logger = AuditLogger(qdrant_url="...", embed_url="...")
        >>> logger.init_collection()
        >>> logger.log_event(AuditEvent(...))
        >>> hits = logger.semantic_recall("echo text", limit=10)
    """

    def __init__(
        self,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        embed_url: str = DEFAULT_EMBED_URL,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        embedding_dim: int = DEFAULT_EMBEDDING_DIM,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        qdrant_client_factory: Optional[Callable[[], Any]] = None,
        embedder: Optional[Callable[[str], Optional[list[float]]]] = None,
    ):
        self.qdrant_url = qdrant_url
        self.embed_url = embed_url
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim

        self._buffer: Deque[AuditEvent] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._collection_ready = False
        self._qdrant_client: Any = None
        self._qdrant_client_factory = qdrant_client_factory
        self._embedder = embedder
        self._qdrant_module = None  # lazy-imported qdrant_client module handle

        # Telemetry
        self._total_logged = 0
        self._total_buffered = 0
        self._total_embedded = 0
        self._total_embed_failed = 0
        # Schreibfehler an Qdrant: „Server disconnected“ ist meist eine tote Verbindung — einmal
        # mit neuem Client wiederholen; erst der zweite Fehlschlag zählt als verloren (landet im Puffer).
        self._total_write_retries = 0
        self._total_write_failed = 0
        self._last_write_error: Optional[str] = None

    # --- internal helpers --------------------------------------------------

    def _get_qdrant(self) -> Any:
        """Lazy-init Qdrant client. Returns None if unavailable."""
        # Hard-skip via env-var — set by pytest conftest for skeleton/plugin-
        # protocol tests that don't want Qdrant dial-out attempts. Honours only
        # the REAL-client path; factory-injected test clients still work.
        if os.getenv("MCP_HUB_AUDIT_SKIP_QDRANT") == "1" and self._qdrant_client_factory is None:
            return None
        if self._qdrant_client is not None:
            return self._qdrant_client
        if not self.qdrant_url and self._qdrant_client_factory is None:
            return None  # kein Qdrant eingerichtet: Puffermodus
        if self._qdrant_client_factory is not None:
            try:
                self._qdrant_client = self._qdrant_client_factory()
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_hub.audit_log: qdrant factory failed: %s", exc)
                return None
            # Also try to load qmodels so filter/vector helpers work even with
            # a factory-injected stub client (tests).
            if self._qdrant_module is None:
                try:
                    from qdrant_client import models as qmodels  # type: ignore

                    self._qdrant_module = qmodels
                except ImportError:
                    self._qdrant_module = None
            return self._qdrant_client
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client import models as qmodels  # type: ignore

            self._qdrant_module = qmodels
            # Short timeout so a missing Qdrant (e.g. in unit tests that load
            # the default YAML) degrades to buffer-mode quickly instead of
            # stalling the Hub startup. Production deployments override the
            # URL via Hub config so this path succeeds fast.
            self._qdrant_client = QdrantClient(url=self.qdrant_url, timeout=0.3, prefer_grpc=False)
            return self._qdrant_client
        except ImportError:
            logger.warning("mcp_hub.audit_log: qdrant-client not installed — buffer-only mode")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.audit_log: qdrant client init failed: %s", exc)
            return None

    def _ziel(self) -> Ziel:
        """Sammlung + Modell, mit denen JETZT gelesen/geschrieben wird."""
        return Ziel(self.collection_name, self.embedding_model)

    @property
    def aktive_sammlung(self) -> str:
        """Name der Sammlung, die gerade gelesen wird."""
        return self._ziel().sammlung

    def _embed(self, text: str, z: Optional[Ziel] = None, art: str = "dokument") -> Optional[list[float]]:
        """Embedding über einen OpenAI-kompatiblen Endpunkt (``<embed_url>/v1/embeddings``).

        ``art``: ``dokument`` oder ``anfrage`` (manche Modelle verlangen unterschiedliche Vorsätze, siehe
        ``mcp_hub.embedding``). Ein eingespeister Embedder (Tests) hat Vorrang.
        """
        if self._embedder is not None:
            try:
                vec = self._embedder(text)
                if vec is not None:
                    self._total_embedded += 1
                else:
                    self._total_embed_failed += 1
                return vec
            except Exception as exc:  # noqa: BLE001
                logger.debug("mcp_hub.audit_log: custom embedder failed: %s", exc)
                self._total_embed_failed += 1
                return None
        if not self.embed_url:
            return None  # kein Dienst eingerichtet: kein Fehler, nur kein Vektor
        vec = embedding.embed(text, self.embed_url, (z.modell if z else self.embedding_model), art)
        if vec is None:
            self._total_embed_failed += 1
            return None
        self._total_embedded += 1
        return vec

    # --- public lifecycle --------------------------------------------------

    def init_collection(self) -> bool:
        """Create Qdrant collection if not present. Flushes buffered events.

        Returns:
            ``True`` when collection is ready (either already existed or was
            created). ``False`` when Qdrant is unreachable (buffer-only mode).
        """
        client = self._get_qdrant()
        if client is None:
            return False

        try:
            existing = {c.name for c in client.get_collections().collections}
            if self.collection_name not in existing:
                qmodels = self._qdrant_module
                if qmodels is None:
                    try:
                        from qdrant_client import models as _qmodels  # type: ignore

                        qmodels = _qmodels
                        self._qdrant_module = qmodels
                    except ImportError:
                        qmodels = None
                if qmodels is not None:
                    client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=qmodels.VectorParams(
                            size=self.embedding_dim,
                            distance=qmodels.Distance.COSINE,
                        ),
                        optimizers_config=qmodels.OptimizersConfigDiff(
                            indexing_threshold=DEFAULT_INDEXING_THRESHOLD,
                        ),
                    )
                else:
                    # Factory-mode test: caller has already set up the collection.
                    pass
            self._collection_ready = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.audit_log: init_collection failed: %s (buffer-only)", exc)
            self._collection_ready = False
            return False

        self._indizes_anlegen(client)

        # Flush buffer.
        with self._lock:
            pending = list(self._buffer)
            self._buffer.clear()
        for ev in pending:
            self._write_point(ev)
        return True

    def _indizes_anlegen(self, client: Any) -> None:
        """Payload-Indizes fuer Zeitsortierung und Zaehlung .

        Ohne Index auf `timestamp` kann Qdrant weder nach Zeit sortieren (`order_by`) noch
        schnell zaehlen; `recent` lieferte deshalb eine zufaellige Auswahl (scroll laeuft in
        id-Reihenfolge, die ids sind uuid4) und `stats` zaehlte 24 h nur im Puffer — also 0.
        Wiederholbar: ein schon vorhandener Index ist kein Fehler.
        """
        qmodels = self._qdrant_module
        if qmodels is None or not hasattr(client, "create_payload_index"):
            return
        felder = (
            ("timestamp", qmodels.PayloadSchemaType.FLOAT),
            ("plugin_name", qmodels.PayloadSchemaType.KEYWORD),
            ("tool_name", qmodels.PayloadSchemaType.KEYWORD),
            ("caller", qmodels.PayloadSchemaType.KEYWORD),
            ("art", qmodels.PayloadSchemaType.KEYWORD),
        )
        for feld, typ in felder:
            try:
                client.create_payload_index(
                    collection_name=self.collection_name, field_name=feld, field_schema=typ
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("mcp_hub.audit_log: index %s: %s", feld, exc)

    def _filter(self, filter: Optional[dict[str, Any]], seit: Optional[float] = None) -> Any:
        """Qdrant-Filter aus Feld=Wert-Paaren, optional mit Zeitgrenze."""
        qmodels = self._qdrant_module
        if qmodels is None or (not filter and seit is None):
            return None
        must = [
            qmodels.FieldCondition(key=k, match=qmodels.MatchValue(value=v))
            for k, v in (filter or {}).items()
        ]
        if seit is not None:
            must.append(qmodels.FieldCondition(key="timestamp", range=qmodels.Range(gte=seit)))
        return qmodels.Filter(must=must)

    def log_event(self, event: AuditEvent) -> None:
        """Persist a single AuditEvent. Embeds if an embedding service is reachable, writes to
        Qdrant if reachable, otherwise buffers in-memory.

        Never raises — logging must never crash the Hub.
        """
        try:
            # EIN Ziel fuer Einbetten UND Schreiben: ein Umschalten dazwischen darf die Raeume nicht mischen.
            z = self._ziel()
            if event.embedding_vector is None:
                event.embedding_vector = self._embed(event.embedding_text(), z)
                event._embed_modell = z.modell  # fuer den Puffer: Vektor gehoert zu diesem Modell

            self._total_logged += 1

            if not self._collection_ready:
                self._get_qdrant()  # lazy-try (non-blocking)

            if self._collection_ready:
                ok = self._write_point(event, z)
                if not ok:
                    self._buffer_event(event)
            else:
                self._buffer_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.audit_log: log_event swallowed: %s", exc)
            self._buffer_event(event)

    def _buffer_event(self, event: AuditEvent) -> None:
        with self._lock:
            self._buffer.append(event)
            self._total_buffered += 1

    #: Pause vor dem zweiten Schreibversuch (Sekunden).
    WRITE_RETRY_PAUSE_S = 0.2

    def _write_point(self, event: AuditEvent, z: Optional[Ziel] = None) -> bool:
        """Ein Punkt nach Qdrant; bei Fehler einmal mit frischem Client wiederholen.

        ``z``: Ziel des Vorgangs (Sammlung + Modell). Ein gepufferter Ereignis-Vektor aus einem ANDEREN Modell
        wird neu eingebettet, sonst landete er in der falschen Vektor-Raum-Sammlung.
        """
        z = z or self._ziel()
        point_id = str(uuid.uuid4())
        if event.embedding_vector is not None and getattr(event, "_embed_modell", z.modell) != z.modell:
            event.embedding_vector = self._embed(event.embedding_text(), z)
            event._embed_modell = z.modell
        for versuch in (1, 2):
            client = self._get_qdrant()
            if client is None:
                return False
            try:
                self._upsert(client, point_id, event, z)
                return True
            except Exception as exc:  # noqa: BLE001
                self._last_write_error = f"{type(exc).__name__}: {exc}"[:200]
                if versuch == 1:
                    self._total_write_retries += 1
                    logger.info("mcp_hub.audit_log: upsert failed, retry once: %s", exc)
                    self._qdrant_client = None  # tote Verbindung nicht wiederverwenden
                    time.sleep(self.WRITE_RETRY_PAUSE_S)
                    continue
                self._total_write_failed += 1
                logger.warning("mcp_hub.audit_log: upsert failed: %s", exc)
        return False

    def _upsert(
        self, client: Any, point_id: str, event: AuditEvent, z: Optional[Ziel] = None
    ) -> None:
        sammlung = (z or self._ziel()).sammlung
        qmodels = self._qdrant_module
        # When a vector is missing, Qdrant still requires one — use zero-vec.
        vector = event.embedding_vector or [0.0] * self.embedding_dim
        if qmodels is not None:
            punkt: Any = qmodels.PointStruct(id=point_id, vector=vector, payload=event.to_payload())
        else:
            # Factory-mode fallback for tests with stub client.
            punkt = {"id": point_id, "vector": vector, "payload": event.to_payload()}
        client.upsert(collection_name=sammlung, points=[punkt])

    # --- recall / query -----------------------------------------------------

    def semantic_recall(
        self,
        query: str,
        limit: int = 10,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[AuditEvent]:
        """Return up to ``limit`` audit-events semantically similar to ``query``.

        When ``query`` is empty, returns recent events chronologically.
        When no embedding service is reachable, vector-search is skipped and we fall back
        to chronological-limit filtering.

        ``filter`` example: ``{"caller": "agent", "plugin_name": "echo"}``.
        """
        # Chronological fallback path.
        if not query:
            return self.recent(limit=limit, filter=filter)

        client = self._get_qdrant()
        if client is None or not self._collection_ready:
            return self._buffer_filter(query, limit, filter)

        z = self._ziel()  # EIN Ziel: Anfrage-Vektor und Sammlung muessen zusammenpassen
        query_vec = self._embed(query, z, art="anfrage")
        if query_vec is None:
            return self.recent(limit=limit, filter=filter)

        try:
            flt = self._filter(filter)
            # qdrant-client >= 1.16 hat kein `search` mehr — der Rueckfall auf
            # den Puffer machte `recall` stumm. `query_points` ist der Nachfolger.
            if hasattr(client, "query_points"):
                hits = client.query_points(
                    collection_name=z.sammlung,
                    query=query_vec,
                    limit=limit,
                    query_filter=flt,
                    with_payload=True,
                ).points
            else:
                hits = client.search(
                    collection_name=z.sammlung,
                    query_vector=query_vec,
                    limit=limit,
                    query_filter=flt,
                )
            events: list[AuditEvent] = []
            for h in hits:
                payload = getattr(h, "payload", None) or {}
                events.append(AuditEvent.from_payload(payload))
            return events
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp_hub.audit_log: semantic_recall failed: %s", exc)
            return self._buffer_filter(query, limit, filter)

    def recent(
        self,
        limit: int = 20,
        filter: Optional[dict[str, Any]] = None,
    ) -> list[AuditEvent]:
        """Return ``limit`` most-recent events (chronological, newest first).

        When Qdrant is reachable: scrolls the collection + filters.
        Else: reads from in-memory buffer.
        """
        client = self._get_qdrant()
        if client is not None and self._collection_ready:
            try:
                qmodels = self._qdrant_module
                flt = self._filter(filter)
                # Qdrant sortiert serverseitig nach Zeit (Index auf `timestamp`).
                # Vorher: limit*4 Punkte in id-Reihenfolge (uuid4 = zufaellig) und dann sortiert —
                # „die neuesten" waren die neuesten einer Zufallsstichprobe.
                kw: dict[str, Any] = {}
                if qmodels is not None and hasattr(qmodels, "OrderBy"):
                    kw["order_by"] = qmodels.OrderBy(
                        key="timestamp", direction=qmodels.Direction.DESC
                    )
                    anzahl = limit
                else:
                    anzahl = max(limit * 4, limit)
                points, _ = client.scroll(
                    collection_name=self._ziel().sammlung,
                    limit=anzahl,
                    scroll_filter=flt,
                    with_payload=True,
                    with_vectors=False,
                    **kw,
                )
                events = [
                    AuditEvent.from_payload(getattr(p, "payload", None) or {}) for p in points
                ]
                events.sort(key=lambda e: e.timestamp, reverse=True)
                return events[:limit]
            except Exception as exc:  # noqa: BLE001
                logger.warning("mcp_hub.audit_log: recent() fallback to buffer: %s", exc)

        return self._buffer_filter(None, limit, filter, sort_desc=True)

    def _buffer_filter(
        self,
        query: Optional[str],
        limit: int,
        filter: Optional[dict[str, Any]],
        sort_desc: bool = True,
    ) -> list[AuditEvent]:
        with self._lock:
            events = list(self._buffer)
        if filter:
            events = [e for e in events if all(getattr(e, k, None) == v for k, v in filter.items())]
        if query:
            q = query.lower()
            events = [
                e
                for e in events
                if q in e.tool_name.lower()
                or q in e.arguments.lower()
                or (e.error and q in e.error.lower())
            ]
        if sort_desc:
            events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    # --- Nutzung nach Art ----------------------------------------------------

    def _nutzungs_filter(self, seit: float, **felder: str) -> Any:
        """Zeitgrenze plus Feld=Wert; `art=""` heisst: Punkte ohne Feld `art` (vor der Artmessung geschrieben)."""
        qmodels = self._qdrant_module
        must: list[Any] = [qmodels.FieldCondition(key="timestamp", range=qmodels.Range(gte=seit))]
        for k, v in felder.items():
            if k == "art" and v == "":
                must.append(qmodels.IsEmptyCondition(is_empty=qmodels.PayloadField(key="art")))
            else:
                must.append(qmodels.FieldCondition(key=k, match=qmodels.MatchValue(value=v)))
        return qmodels.Filter(must=must)

    def _facet(
        self, client: Any, key: str, flt: Any, sammlung: Optional[str] = None
    ) -> dict[str, int]:
        res = client.facet(
            collection_name=sammlung or self._ziel().sammlung,
            key=key,
            facet_filter=flt,
            limit=2000,
            exact=True,
        )
        return {str(h.value): int(h.count) for h in getattr(res, "hits", []) or []}

    def nutzung_je_werkzeug(self, seit: float, mit_letzter: bool = True) -> dict[str, dict[str, Any]]:
        """Aufrufe je Werkzeug seit `seit`, getrennt nach Art, plus letzte bewusste Nutzung.

        Neue Punkte tragen `art`. Aeltere (ohne Feld) werden nach Aufrufername eingeordnet
        (`art_von_aufrufer`): je Aufrufer eine Zaehlung, die Zahl der Aufrufer ist klein. Wirft, wenn Qdrant
        nicht bereit ist; ohne Stichproben-Puffer, weil dort nie die ganze Woche steht.
        """
        client = self._get_qdrant()
        if client is None or not self._collection_ready or self._qdrant_module is None:
            raise RuntimeError("Qdrant-Sammlung nicht bereit")
        out: dict[str, dict[str, Any]] = {}
        alt_bewusst: dict[str, list[str]] = {}
        sammlung = self._ziel().sammlung  # alle Zaehlungen dieses Aufrufs aus derselben Sammlung

        def buchen(werkzeug: str, art: str, n: int) -> dict[str, Any]:
            z = out.setdefault(
                werkzeug,
                {ART_BEWUSST: 0, ART_ABFRAGE: 0, ART_UNBEKANNT: 0, "letzte_bewusst": None},
            )
            z[art] += n
            return z

        for art in ART_WERTE:
            for werkzeug, n in self._facet(
                client, "tool_name", self._nutzungs_filter(seit, art=art), sammlung
            ).items():
                buchen(werkzeug, art, n)
        for aufrufer in self._facet(client, "caller", self._nutzungs_filter(seit, art=""), sammlung):
            art = art_von_aufrufer(aufrufer)
            je_werkzeug = self._facet(
                client, "tool_name", self._nutzungs_filter(seit, art="", caller=aufrufer), sammlung
            )
            for werkzeug, n in je_werkzeug.items():
                buchen(werkzeug, art, n)
                if art == ART_BEWUSST:
                    alt_bewusst.setdefault(werkzeug, []).append(aufrufer)
        if mit_letzter:
            for werkzeug, z in out.items():
                if z[ART_BEWUSST] > 0:
                    z["letzte_bewusst"] = self._letzte(
                        client, seit, werkzeug, alt_bewusst.get(werkzeug, []), sammlung
                    )
        return out

    def _letzte(
        self,
        client: Any,
        seit: float,
        werkzeug: str,
        alte_aufrufer: list[str],
        sammlung: Optional[str] = None,
    ) -> Optional[float]:
        qmodels = self._qdrant_module
        sammlung = sammlung or self._ziel().sammlung
        kandidaten = [self._nutzungs_filter(seit, tool_name=werkzeug, art=ART_BEWUSST)] + [
            self._nutzungs_filter(seit, tool_name=werkzeug, art="", caller=c) for c in alte_aufrufer[:10]
        ]
        beste: Optional[float] = None
        for flt in kandidaten:
            try:
                punkte, _ = client.scroll(
                    collection_name=sammlung,
                    limit=1,
                    scroll_filter=flt,
                    with_payload=True,
                    with_vectors=False,
                    order_by=qmodels.OrderBy(key="timestamp", direction=qmodels.Direction.DESC),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("mcp_hub.audit_log: letzte bewusste Nutzung %s: %s", werkzeug, exc)
                continue
            for p in punkte:
                t = float((getattr(p, "payload", None) or {}).get("timestamp", 0.0))
                if beste is None or t > beste:
                    beste = t
        return beste

    # --- stats --------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Telemetry snapshot for monitoring + audit plugin tool."""
        now = time.time()
        last_24h = now - 86400
        count_total = 0
        count_24h = 0
        top_plugins: dict[str, int] = {}

        top_callers: dict[str, int] = {}

        # 24 h und Top-Plugins kamen nur aus dem Puffer — der ist leer, sobald
        # Qdrant laeuft, also stand dort immer 0. Jetzt zaehlt Qdrant selbst (count + facet).
        aktiv = self._ziel()
        client = self._get_qdrant()
        if client is not None and self._collection_ready:
            try:
                info = client.get_collection(aktiv.sammlung)
                count_total = getattr(info, "points_count", 0) or 0
            except Exception:  # noqa: BLE001
                pass
            flt_24h = self._filter(None, seit=last_24h)
            if flt_24h is not None:
                try:
                    res = client.count(
                        collection_name=aktiv.sammlung, count_filter=flt_24h, exact=True
                    )
                    count_24h = int(getattr(res, "count", 0) or 0)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("mcp_hub.audit_log: count 24h: %s", exc)
                for feld, ziel in (("plugin_name", top_plugins), ("caller", top_callers)):
                    try:
                        res = client.facet(
                            collection_name=aktiv.sammlung,
                            key=feld,
                            facet_filter=flt_24h,
                            limit=10,
                            exact=True,
                        )
                        for hit in getattr(res, "hits", []) or []:
                            ziel[str(hit.value)] = int(hit.count)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("mcp_hub.audit_log: facet %s: %s", feld, exc)

        with self._lock:
            for ev in self._buffer:
                count_total += 1
                if ev.timestamp >= last_24h:
                    count_24h += 1
                    top_plugins[ev.plugin_name] = top_plugins.get(ev.plugin_name, 0) + 1
                    top_callers[ev.caller] = top_callers.get(ev.caller, 0) + 1

        top = sorted(top_plugins.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "collection": self.collection_name,
            "collection_aktiv": aktiv.sammlung,
            "embed_modell": aktiv.modell,
            "total_logged": self._total_logged,
            "total_buffered": self._total_buffered,
            "total_embedded": self._total_embedded,
            "total_embed_failed": self._total_embed_failed,
            "write_retries": self._total_write_retries,
            "write_failed": self._total_write_failed,
            "last_write_error": self._last_write_error,
            "points_in_collection": count_total,
            "events_last_24h": count_24h,
            "top_plugins": top,
            "top_callers_24h": sorted(top_callers.items(), key=lambda kv: kv[1], reverse=True)[:5],
            "collection_ready": self._collection_ready,
            "buffer_len": len(self._buffer),
        }


# ---------------------------------------------------------------------------
# Helper: build an AuditEvent from a registry.call() ToolInvocationResult
# ---------------------------------------------------------------------------


# Das Audit landet in Qdrant und geht als Text an den Embedder. Zugangsdaten in
# Argumenten (exec-Kommandos, DSNs, Header) sollen dort nicht im Klartext stehen.
# Bewusst grob: lieber ein Wort zu viel geschwaerzt als ein Passwort gespeichert.
_SCHWAERZEN = (
    (re.compile(r"(://)[^/\s:@\"']+:[^/\s@\"']+@"), r"\1<geschwaerzt>@"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1<geschwaerzt>"),
    (
        re.compile(
            r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|authorization)"
            r"[\\\"']*\s*[:=]\s*[\\\"']*)[^\\\"'\s,}&]+"
        ),
        r"\1<geschwaerzt>",
    ),
)


def schwaerzen(text: str) -> str:
    for muster, ersatz in _SCHWAERZEN:
        text = muster.sub(ersatz, text)
    return text


def build_event_from_call(
    fqtn: str,
    arguments: dict[str, Any],
    result: Any,  # ToolInvocationResult
    session_id: str = "unknown",
    caller: str = "unknown",
    max_arg_bytes: int = 1000,
    art: str = "",
) -> AuditEvent:
    """Construct an AuditEvent from a ``ToolInvocationResult``.

    Used by the audit-plugin's on-call hook. Keeps the adapter logic in one
    place (so tests can build events without going through the whole Hub).
    """
    plugin_name = fqtn.split(".", 1)[0] if "." in fqtn else fqtn
    try:
        args_json = json.dumps(arguments or {}, default=str)
    except Exception:  # noqa: BLE001
        args_json = "{}"
    args_json = schwaerzen(args_json)
    if len(args_json) > max_arg_bytes:
        args_json = args_json[:max_arg_bytes] + "..."

    status = getattr(result, "status", "unknown")
    latency_ms = float(getattr(result, "latency_ms", 0.0) or 0.0)
    err = getattr(result, "error", None)
    if err:
        err = schwaerzen(str(err))[:500]
    kind = getattr(result, "kind", None)
    if status == "error" and kind:
        # Fold kind into status for richer recall filters.
        status = kind

    return AuditEvent(
        timestamp=time.time(),
        session_id=session_id,
        caller=caller,
        tool_name=fqtn,
        plugin_name=plugin_name,
        arguments=args_json,
        result_status=status,
        latency_ms=latency_ms,
        error=err,
        art=art_aus(caller, art),
    )
