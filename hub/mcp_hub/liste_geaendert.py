"""mcp_hub.liste_geaendert — offenen MCP-Clients sagen, dass sich die Werkzeugliste geändert hat (Hot-Reload Stufe 2).

Stufe 1 (``plugins_live``, siehe ``mcp_hub.plugins_live``) tauscht Plugins im laufenden Hub aus; hier erfahren offene
Sitzungen davon, damit neue und geänderte Werkzeuge ohne Neustart der Sitzung erscheinen.

Zwei Wege, je nach Protokoll des Clients:

1. **Neu (mcp >= 2, Protokoll 2026-07-28), ohne Sitzungen.** Der Client öffnet ``subscriptions/listen``; die Antwort ist der
   Ereignisstrom. Der SDK-Server hält dafür einen Verteiler (``MCPServer._subscriptions``); ``ToolsListChanged`` und
   ``ResourcesListChanged`` dorthin zu senden genügt. Kein Zustand zwischen Anfragen, also auch mit mehreren Replikas
   richtig: ein Strom hängt an der TCP-Verbindung zu genau einem Pod, und jeder Pod lädt aus seinem eigenen Klon nach
   und meldet selbst.
2. **Alt (Handshake-Protokolle, z. B. Claude Code), nur mit ``mcp_sitzungen``.** Dafür braucht der Server
   zustandsbehaftete Sitzungen mit GET-Strom (``stateless_http`` aus). Der Hub merkt sich die Sitzung jedes Clients, der
   ``tools/list`` abruft (schwach, verschwindet mit der Sitzung), und schickt allen ``notifications/tools/list_changed``
   und ``notifications/resources/list_changed``. Sitzungen leben im Speicher EINES Pods: bei mehreren Replikas ohne
   Sticky-Routing landet ein Folgeaufruf auf dem falschen Pod (404 „Session not found“). Darum Vorgabe aus.

Fehler einzelner Sitzungen werden verschluckt (und die Sitzung vergessen); das Melden blockiert nie das Nachladen.
Rückweg: ``liste_melden: false`` und/oder ``mcp_sitzungen: false`` in der Config.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import weakref
from typing import Any

logger = logging.getLogger(__name__)

SENDE_TIMEOUT_S = 5.0
"""So lange darf ein einzelner Client auf eine Benachrichtigung warten, bevor sie verworfen wird."""

_MODERN_AB = "2026-07-28"
"""Ab dieser Protokollversion gibt es keine Sitzungen mehr; Änderungen laufen nur über ``subscriptions/listen``."""


def _verteiler_ereignisse() -> list[Any]:
    """Ereignis-Klassen des SDK-Verteilers (mcp >= 2); leer, wenn das SDK sie nicht kennt (mcp 1.x)."""
    try:
        from mcp.shared.subscriptions import ResourcesListChanged, ToolsListChanged  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — mcp 1.x hat sie nicht
        return []
    return [ToolsListChanged, ResourcesListChanged]


class Melder:
    """Verwaltet die Sitzungen und verschickt „Liste geändert“. Eine Instanz je Hub (``MELDER``)."""

    def __init__(self) -> None:
        self.melden_an = False
        self.sitzungen_an = False
        self._verteiler: Any = None
        self._schleife: asyncio.AbstractEventLoop | None = None
        self._sitzungen: weakref.WeakSet[Any] = weakref.WeakSet()
        self._sperre = threading.Lock()
        self.gesendet = 0
        self.fehler = 0
        self.letzte_meldung: float | None = None

    # -- Einrichtung ---------------------------------------------------------------------------------------------

    def konfigurieren(self, *, melden: bool, sitzungen: bool, verteiler: Any = None) -> None:
        self.melden_an = bool(melden)
        self.sitzungen_an = bool(melden and sitzungen)
        self._verteiler = verteiler if melden else None

    def schleife_setzen(self, schleife: asyncio.AbstractEventLoop | None) -> None:
        """Ereignisschleife des Servers (im ``lifespan``); die Meldung kommt aus Arbeitsthreads."""
        self._schleife = schleife

    def zuruecksetzen(self) -> None:
        self.konfigurieren(melden=False, sitzungen=False)
        self._schleife = None
        with self._sperre:
            self._sitzungen = weakref.WeakSet()
        self.gesendet = self.fehler = 0
        self.letzte_meldung = None

    # -- Sitzungen -----------------------------------------------------------------------------------------------

    def sitzung_merken(self, sitzung: Any, protokoll: str | None = None) -> bool:
        """Sitzung für spätere Meldungen merken (nur mit ``mcp_sitzungen``; moderne Protokolle haben keine Sitzung)."""
        if not self.sitzungen_an or sitzung is None:
            return False
        if protokoll and str(protokoll) >= _MODERN_AB:
            return False
        try:
            with self._sperre:
                self._sitzungen.add(sitzung)
        except TypeError:  # nicht schwach referenzierbar: lieber gar nicht merken als festhalten
            return False
        return True

    def anzahl_sitzungen(self) -> int:
        with self._sperre:
            return len(self._sitzungen)

    def zustand(self) -> dict[str, Any]:
        return {
            "melden": self.melden_an,
            "sitzungen_an": self.sitzungen_an,
            "sitzungen": self.anzahl_sitzungen(),
            "gesendet": self.gesendet,
            "fehler": self.fehler,
            "letzte_meldung": self.letzte_meldung,
        }

    # -- Senden --------------------------------------------------------------------------------------------------

    async def _an_sitzung(self, sitzung: Any) -> bool:
        try:
            await asyncio.wait_for(sitzung.send_tool_list_changed(), SENDE_TIMEOUT_S)
            fn = getattr(sitzung, "send_resource_list_changed", None)
            if fn is not None:
                await asyncio.wait_for(fn(), SENDE_TIMEOUT_S)
            return True
        except Exception as exc:  # noqa: BLE001 — tote Sitzung, Zeitablauf, geschlossener Strom
            logger.debug("liste_geaendert: Sitzung nicht erreichbar (%s)", exc)
            return False

    async def melden_async(self) -> dict[str, Any]:
        """Verteiler und alle gemerkten Sitzungen benachrichtigen; liefert eine Zählung (für Tests und Log)."""
        import time  # noqa: PLC0415

        res: dict[str, Any] = {"verteiler": False, "sitzungen": 0, "fehler": 0}
        if not self.melden_an:
            return res
        verteiler = self._verteiler
        if verteiler is not None:
            try:
                for klasse in _verteiler_ereignisse():
                    await asyncio.wait_for(verteiler.publish(klasse()), SENDE_TIMEOUT_S)
                    res["verteiler"] = True
            except Exception as exc:  # noqa: BLE001
                res["fehler"] += 1
                logger.warning("liste_geaendert: Verteiler nicht erreichbar: %s", exc)
        if self.sitzungen_an:
            with self._sperre:
                sitzungen = list(self._sitzungen)
            erfolge = await asyncio.gather(*(self._an_sitzung(s) for s in sitzungen))
            for s, ok in zip(sitzungen, erfolge, strict=True):
                if ok:
                    res["sitzungen"] += 1
                else:
                    res["fehler"] += 1
                    with self._sperre:
                        self._sitzungen.discard(s)
        self.gesendet += res["sitzungen"] + (1 if res["verteiler"] else 0)
        self.fehler += res["fehler"]
        self.letzte_meldung = time.time()
        if res["sitzungen"] or res["fehler"] or res["verteiler"]:
            logger.info("liste_geaendert: Werkzeugliste gemeldet — %s", res)
        return res

    def melden(self) -> bool:
        """Aus einem Arbeitsthread: Meldung auf der Ereignisschleife einplanen und sofort zurückkehren.

        True, wenn eingeplant. Nie ein Fehler nach außen: Das Nachladen der Plugins darf daran nicht scheitern."""
        schleife = self._schleife
        if not self.melden_an or schleife is None or schleife.is_closed():
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(self.melden_async(), schleife)
        except Exception as exc:  # noqa: BLE001
            logger.warning("liste_geaendert: nicht einplanbar: %s", exc)
            return False

        def _fertig(f: Any) -> None:
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("liste_geaendert: Meldung gescheitert: %s", exc)

        fut.add_done_callback(_fertig)
        return True


MELDER = Melder()


def listchanged_ankuendigen(lowlevel: Any) -> bool:
    """Im Handshake (alte Protokolle) ``tools.listChanged`` und ``resources.listChanged`` ankündigen.

    Das SDK meldet sie nur, wenn der Aufrufer ``NotificationOptions`` mitgibt; der Sitzungsverwalter tut das nicht.
    Nur aufrufen, wenn Sitzungen an sind (sonst wäre die Ankündigung falsch). Für den neuen Weg leitet das SDK die
    Flags selbst aus dem ``subscriptions/listen``-Handler ab."""
    if lowlevel is None:
        return False
    if getattr(lowlevel.create_initialization_options, "_fyos_listchanged", False):
        return True
    try:
        from mcp.server.lowlevel.server import NotificationOptions  # noqa: PLC0415

        original = lowlevel.create_initialization_options

        def mit_meldung(notification_options: Any = None, *args: Any, **kwargs: Any) -> Any:
            if notification_options is None:
                notification_options = NotificationOptions(tools_changed=True, resources_changed=True)
            return original(notification_options, *args, **kwargs)

        mit_meldung._fyos_listchanged = True  # type: ignore[attr-defined]
        lowlevel.create_initialization_options = mit_meldung
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("liste_geaendert: listChanged nicht ankündbar: %s", exc)
        return False
