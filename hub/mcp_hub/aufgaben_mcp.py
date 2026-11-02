"""aufgaben_mcp — die Erweiterung `io.modelcontextprotocol/tasks` am MCP-Server des Hubs (mcp >= 2.1, 2026-10-25).

Das SDK traegt die Schnittstelle fuer Erweiterungen (`mcp.server.extension.Extension`), nicht die Tasks selbst. Hier:

  * `tasks/get`, `tasks/update`, `tasks/cancel` als eigene Methoden — nur im modernen Zeitalter (2026-07-28);
  * Eintrag in `capabilities.extensions` (und damit in `server/discover`), vom SDK aus `identifier` und `settings()`;
  * Abfangen von `tools/call`: erklaert der Client die Erweiterung und ist das Ziel Task-faehig, kommt statt des Ergebnisses
    `CreateTaskResult` (`resultType: "task"`). Sonst laeuft alles wie bisher.

Das Handshake-Zeitalter (2024-11-05 bis 2025-11-25) bekommt nie eine Aufgabe: `resultType: "task"` gibt es dort nicht.
Die Logik steht in `aufgaben.py` (kein SDK); `loese` kommt aus `server.py` und sagt, welches Werkzeug hinter einem Namen
steckt und wie es auszufuehren ist.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolRequestParams
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import Field

try:  # Name des Basistyps der Parameter je nach Fassung
    from mcp_types import RequestParams
except ImportError:  # pragma: no cover
    from mcp.types import RequestParams  # type: ignore[no-redef]

from .aufgaben import AUFGABEN, ERWEITERUNG, Aufgaben, AufgabenFehler
from .registry import AUFRUFER

#: `loese(name, arguments)` -> (Werkzeug `plugin.name`, lauf) wenn der Aufruf als Aufgabe laufen darf, sonst None.
Loeser = Callable[[str, dict[str, Any]], "tuple[str, Callable[[], dict[str, Any]]] | None"]


class _AufgabeParams(RequestParams):
    task_id: str = Field(alias="taskId")


class _AktualisierenParams(_AufgabeParams):
    input_responses: dict[str, Any] = Field(alias="inputResponses", default_factory=dict)


def _fehler(exc: AufgabenFehler) -> MCPError:
    return MCPError(code=exc.code, message=exc.message)


class AufgabenErweiterung(Extension):
    identifier = ERWEITERUNG

    def __init__(self, loese: Loeser, aufgaben: Aufgaben | None = None) -> None:
        self._loese = loese
        self._a = aufgaben or AUFGABEN

    def settings(self) -> dict[str, Any]:
        return {}

    def methods(self) -> list[MethodBinding]:
        modern = frozenset(MODERN_PROTOCOL_VERSIONS)
        return [
            MethodBinding("tasks/get", _AufgabeParams, self._get, protocol_versions=modern),
            MethodBinding("tasks/update", _AktualisierenParams, self._update, protocol_versions=modern),
            MethodBinding("tasks/cancel", _AufgabeParams, self._cancel, protocol_versions=modern),
        ]

    # ── tasks/* ──────────────────────────────────────────────────────────────
    async def _get(self, ctx: Any, params: _AufgabeParams) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._a.lesen, params.task_id, AUFRUFER.get())
        except AufgabenFehler as exc:
            raise _fehler(exc) from None

    async def _update(self, ctx: Any, params: _AktualisierenParams) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._a.aktualisieren, params.task_id, AUFRUFER.get(), params.input_responses)
        except AufgabenFehler as exc:
            raise _fehler(exc) from None

    async def _cancel(self, ctx: Any, params: _AufgabeParams) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._a.abbrechen, params.task_id, AUFRUFER.get())
        except AufgabenFehler as exc:
            raise _fehler(exc) from None

    # ── tools/call ───────────────────────────────────────────────────────────
    @staticmethod
    def _client_erklaert(ctx: Any) -> bool:
        faehig = getattr(ctx.session, "client_capabilities", None)
        erweiterungen = getattr(faehig, "extensions", None) if faehig is not None else None
        return isinstance(erweiterungen, dict) and ERWEITERUNG in erweiterungen

    async def intercept_tool_call(self, params: CallToolRequestParams, ctx: Any, call_next: Any) -> Any:
        if ctx.protocol_version in MODERN_PROTOCOL_VERSIONS and self._client_erklaert(ctx):
            ziel = self._loese(params.name, dict(params.arguments or {}))
            if ziel is not None:
                werkzeug, lauf = ziel
                try:
                    return await asyncio.to_thread(self._a.start, werkzeug, lauf, AUFRUFER.get())
                except AufgabenFehler as exc:
                    raise _fehler(exc) from None
        return await call_next(ctx)
