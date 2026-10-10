"""Sammelstrom `fyos:live` — gemeinsame Sprache von Schreiber und Leser.

Der Hub schreibt zu jedem Werkzeugaufruf ein kompaktes Ereignis in den Strom `fyos:live` (neben den
`bus.tool.*`-Strömen; event_bus_publisher). Der Kern bringt keinen Leser mit; das Schreiben lässt sich mit
`live: false` in der Konfiguration des event_bus_publisher abschalten.

Eisenharte Regel: ein Ereignis trägt NUR Name, Plugin, Ergebnis (ok/fail), Dauer und Aufrufer. Keine Argumente,
keine Ergebnisse, keine Texte. Wer hier ein Feld ergänzt, ergänzt es für alle Betrachter.

Felder je Eintrag (alles Zeichenketten, wie Redis sie liefert):
    t   Zeit in Millisekunden seit 1970 (Ende des Aufrufs)
    p   Plugin ("werkstatt")
    m   Werkzeug ohne Plugin ("suchen")
    s   "ok" oder "fail"
    k   nur bei fail: Art des Scheiterns ("plugin_error", "tool_failed", "circuit_open" …)
    d   Dauer in Millisekunden (ganzzahlig)
    w   Aufrufer wie im Audit ("shell", "mcp:claude-code", "agent" …), bereinigt
    a   Art des Aufrufs: "bewusst", "abfrage" oder "unbekannt" (audit_log.art_aus)
"""

from __future__ import annotations

import re
import time
from typing import Any

STROM = "fyos:live"
#: Obergrenze (ungefähr, `MAXLEN ~`).
MAXLEN = 5000

#: Aufrufe, die NICHT in den Sammelstrom und nicht auf den Bus gehören (Selbstabfragen im Sekundentakt).
#: Leer; der Mechanismus bleibt für Abfrage-Werkzeuge, die ein Plugin ergänzt (`LEISE |= {...}`).
LEISE: frozenset[str] = frozenset()

#: Flächen (wer ruft): Kennung, Anzeigename, Symbol (aus ui/_symbole.json). Reihenfolge = Reihenfolge links.
FLAECHEN: tuple[tuple[str, str, str], ...] = (
    ("os", "Shell", "monitor"),
    ("chat", "Chat", "message-circle"),
    ("code", "Code-Agent", "terminal"),
    ("agent", "Agent", "sparkles"),
    ("dienste", "Dienste", "cog"),
)

_UNERLAUBT = re.compile(r"[^A-Za-z0-9._:@/-]")


def aufrufer_bereinigen(aufrufer: Any) -> str:
    """Aufrufername für den Strom: kurz, ohne Sonderzeichen (er stammt aus einer Kopfzeile)."""
    return _UNERLAUBT.sub("", str(aufrufer or ""))[:40] or "unbekannt"


def flaeche_aus(aufrufer: str) -> str:
    """Fläche zu einem Aufrufernamen (`registry.AUFRUFER`): `os`, `chat`, `code`, `agent` oder `dienste`.

    `shell` (oder `fyos-web`) = die offene Shell im Browser; `mcp:claude-code`/`codex` = ein Code-Agent;
    `oauth:…` oder ein Name mit `claude` = ein Chat-Konnektor; `agent…` = ein Agent. Alles andere (Skripte, Python,
    Node) sind Dienste.
    """
    k = (aufrufer or "").lower()
    if k.startswith(("shell", "fyos-web")):
        return "os"
    if any(w in k for w in ("claude-code", "claude_code", "claude-cli", "codex")):
        return "code"
    if k.startswith("oauth:") or "claude" in k:
        return "chat"
    if k.startswith("agent"):
        return "agent"
    return "dienste"


def eintrag_aus_audit(ev: Any, jetzt: float | None = None) -> dict[str, str] | None:
    """Kompaktes Ereignis aus einem `AuditEvent`; None für leise Aufrufe (`LEISE`)."""
    tool = str(getattr(ev, "tool_name", "") or "")
    plugin = str(getattr(ev, "plugin_name", "") or "unbekannt")
    methode = tool.split(".", 1)[1] if "." in tool else tool
    if f"{plugin}.{methode}" in LEISE:
        return None
    status = str(getattr(ev, "result_status", "") or "unknown")
    eintrag = {
        "t": str(int((jetzt if jetzt is not None else time.time()) * 1000)),
        "p": plugin,
        "m": methode or "unbekannt",
        "s": "ok" if status == "ok" else "fail",
        "d": str(int(float(getattr(ev, "latency_ms", 0.0) or 0.0))),
        "w": aufrufer_bereinigen(getattr(ev, "caller", "")),
    }
    art = str(getattr(ev, "art", "") or "")
    if art in ("bewusst", "abfrage", "unbekannt"):
        eintrag["a"] = art
    if status != "ok":
        eintrag["k"] = aufrufer_bereinigen(status)
    return eintrag
