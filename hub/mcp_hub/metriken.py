"""metriken — ``/metrics`` im Prometheus-Textformat.

Quellen, ohne eigene Zählwerke:
    * Kern: geladene Plugins und Werkzeuge, Aufrufe und Summe der Dauer je Werkzeug (``registry.call_counts``,
      ``registry.latency_totals_ms``).
    * ``HubPlugin.metrics()``: Zahlen auf oberster Ebene und eine Ebene tiefer als
      ``fyos_plugin_wert{plugin, schluessel}``; eigene Reihen unter ``"_proben"`` (siehe ``HubPlugin.metrics``).
    * ``HubPlugin.zeitplan()``: je Aufgabe ob an, Zeit des letzten Laufs und ob er gelang; bei Takten mit Wächter
      (``mcp_hub.takt``) außerdem Läufe heute, Tageslimit und übersprungene Läufe je Grund (Fenster, Limit).

Der Weg ist innen offen wie ``/health``; auf einem Außenhost antwortet er 404 (``anmeldung``). Der Text wird 30 s
zwischengespeichert, damit ein Abruf nicht jedes Plugin neu fragt.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Any

from . import zeitplan as _zeitplan

logger = logging.getLogger(__name__)

TTL_S = 30.0
_NAME_GUELTIG = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_NICHT_NAME = re.compile(r"[^a-zA-Z0-9_]")
_TYPEN = ("gauge", "counter")

_sperre = threading.Lock()
_ablage: dict[int, tuple[float, str]] = {}


def _bezeichner(text: str) -> str:
    return _NICHT_NAME.sub("_", str(text)).strip("_").lower() or "x"


def _label(wert: Any) -> str:
    return str(wert).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')[:200]


def _zahl(wert: Any) -> float | None:
    if isinstance(wert, bool):
        return 1.0 if wert else 0.0
    if isinstance(wert, (int, float)):
        z = float(wert)
        return z if math.isfinite(z) else None
    return None


class _Text:
    """Sammelt Reihen je Name (HELP/TYPE einmal, Reihen darunter)."""

    def __init__(self) -> None:
        self._reihen: dict[str, tuple[str, str, list[str]]] = {}

    def probe(self, name: str, wert: Any, labels: dict[str, Any] | None = None, typ: str = "gauge", hilfe: str = "") -> None:
        z = _zahl(wert)
        if z is None or not _NAME_GUELTIG.match(name):
            return
        typ = typ if typ in _TYPEN else "gauge"
        if name not in self._reihen:
            self._reihen[name] = (typ, hilfe, [])
        teile = ",".join(f'{_bezeichner(k)}="{_label(v)}"' for k, v in sorted((labels or {}).items()))
        zahl = repr(z) if not z.is_integer() else str(int(z))
        self._reihen[name][2].append(f"{name}{{{teile}}} {zahl}" if teile else f"{name} {zahl}")

    def text(self) -> str:
        zeilen: list[str] = []
        for name, (typ, hilfe, reihen) in self._reihen.items():
            if hilfe:
                zeilen.append(f"# HELP {name} {' '.join(hilfe.split())}")
            zeilen.append(f"# TYPE {name} {typ}")
            zeilen.extend(reihen)
        return "\n".join(zeilen) + "\n"


def _plugin_proben(t: _Text, name: str, werte: dict[str, Any]) -> None:
    for schluessel, wert in werte.items():
        if schluessel == "_proben":
            for p in wert if isinstance(wert, list) else []:
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                pname = _bezeichner(p["name"])
                if not pname.startswith("fyos_"):
                    pname = f"fyos_{_bezeichner(name)}_{pname}"
                labels = p.get("labels") if isinstance(p.get("labels"), dict) else {}
                t.probe(pname, p.get("wert"), labels, str(p.get("typ") or "gauge"), str(p.get("hilfe") or ""))
            continue
        if isinstance(wert, dict):
            for unter, w in wert.items():
                t.probe("fyos_plugin_wert", w, {"plugin": name, "schluessel": f"{schluessel}.{unter}"},
                        hilfe="Zahlen aus HubPlugin.metrics()")
        else:
            t.probe("fyos_plugin_wert", wert, {"plugin": name, "schluessel": schluessel},
                    hilfe="Zahlen aus HubPlugin.metrics()")


def erzeugen(registry: Any) -> str:
    """Den ganzen Text frisch erzeugen (ohne Zwischenablage)."""
    t = _Text()
    plugins = getattr(registry, "plugins", None) or {}
    t.probe("fyos_hub_plugins", len(plugins), hilfe="Geladene Plugins")
    t.probe("fyos_hub_werkzeuge", len(getattr(registry, "tools", None) or {}), hilfe="Angemeldete Werkzeuge")
    t.probe("fyos_hub_nicht_geladen", len(getattr(registry, "nicht_geladen", None) or {}),
            hilfe="Plugins, die beim Start scheiterten")
    for fqtn, n in sorted((getattr(registry, "call_counts", None) or {}).items()):
        t.probe("fyos_hub_aufrufe_total", n, {"werkzeug": fqtn}, "counter", "Werkzeugaufrufe seit dem Start")
    for fqtn, ms in sorted((getattr(registry, "latency_totals_ms", None) or {}).items()):
        t.probe("fyos_hub_aufruf_ms_summe", ms, {"werkzeug": fqtn}, "counter", "Summe der Aufrufdauer in ms seit dem Start")
    for name, plugin in plugins.items():
        holen = getattr(plugin, "metrics", None)
        if not callable(holen):
            continue
        try:
            werte = holen() or {}
        except Exception as exc:  # noqa: BLE001 — ein Plugin kostet nur seine eigenen Reihen
            logger.debug("metrics(%s) gescheitert: %s", name, exc)
            t.probe("fyos_plugin_metrics_fehler", 1, {"plugin": name}, hilfe="metrics() des Plugins scheiterte")
            continue
        if isinstance(werte, dict):
            _plugin_proben(t, name, werte)
    plan = _zeitplan.sammeln(registry)
    for e in plan["eintraege"]:
        labels = {"plugin": e["plugin"], "quelle": e["quelle"], "aufgabe": e["name"]}
        t.probe("fyos_zeitplan_an", e["an"], labels, hilfe="Aufgabe eingeschaltet (1) oder aus (0)")
        if e["letzter"] is not None:
            t.probe("fyos_zeitplan_letzter_lauf_s", e["letzter"], labels, hilfe="Ende des letzten Laufs (Unix-Sekunden)")
        if e["letzter_status"] is not None:
            t.probe("fyos_zeitplan_letzter_ok", e["letzter_status"] == "ok", labels,
                    hilfe="Letzter Lauf gelang (1) oder scheiterte (0)")
        takt = {"takt": e["id"]}
        if e["laeufe_heute"] is not None:
            t.probe("fyos_zeitplan_laeufe_heute", e["laeufe_heute"], takt,
                    hilfe="Läufe der Aufgabe heute (Tag der Zeitzone des Hubs)")
        if e["max_pro_tag"] is not None:
            t.probe("fyos_zeitplan_max_pro_tag", e["max_pro_tag"], takt, hilfe="Tageslimit der Aufgabe (Läufe je Tag)")
        for grund, n in sorted(e["uebersprungen"].items()):
            t.probe("fyos_zeitplan_uebersprungen_total", n, {**takt, "grund": grund}, "counter",
                    hilfe="Heute übersprungene Läufe, nach Grund (fenster: außerhalb der Uhrzeiten, limit: Tageslimit erreicht)")
    return t.text()


def text(registry: Any, ttl_s: float = TTL_S) -> str:
    """Text mit Zwischenablage je Register."""
    schluessel = id(registry)
    jetzt = time.monotonic()
    with _sperre:
        alt = _ablage.get(schluessel)
        if alt is not None and jetzt - alt[0] < ttl_s:
            return alt[1]
    neu = erzeugen(registry)
    with _sperre:
        _ablage[schluessel] = (time.monotonic(), neu)
    return neu
