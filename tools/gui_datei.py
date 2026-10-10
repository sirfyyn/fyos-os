#!/usr/bin/env python3
"""gui_datei.py - eine gebaute Ansicht (gui.bauen) als eigenständige HTML-Datei.

Im Terminal gibt es keinen MCP-Apps-Host. Die Datei bringt einen kleinen Host mit, der die App ui://fyos/gui.html wie
die Shell einbettet (gleiche Sandbox und CSP). Mit dem Mod fyos-ansicht (tools/claude-code/fyos-ansicht) zeigt Claude
Code die Ansicht rechts im Panel; diese Datei ist der Weg ohne Mod: `--oeffnen` zeigt sie im Standardbrowser.

    gui_datei.py g-3f9a0c1d2e4b [ZIEL.html]   abgelegte Ansicht aus dem Hub holen (gui.zeigen über POST /hub/call)
    gui_datei.py ansicht.json [ZIEL.html]     dieselben Felder wie gui.bauen aus einer Datei (ohne Hub), auch
                                              {"titel": "…", "vorlage": "balken", "daten": {…}}
    --oeffnen                                 danach im Standardbrowser öffnen

Ohne ZIEL: ./gui-<id>.html. Gibt den Pfad aus. Der Hub steht in FYOS_HUB_URL (Vorgabe http://localhost:8080, ein /mcp
am Ende wird abgeschnitten); `/hub/call` erreicht nur, wer den Hub selbst erreicht (siehe docs/HUB-VERTRAG.md).
Eine Live-Quelle bleibt in der Datei auf dem Stand des Abrufs: die Datei lädt nichts nach.

Braucht Python 3.11 oder neuer und den Quelltext des Hubs: das installierte Paket fyos-hub oder, in einem Checkout
dieses Repos, das Verzeichnis hub/ (es wird bei Bedarf selbst gefunden, Abhängigkeiten braucht dieses Skript keine).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import mcp_hub  # noqa: F401 - installierter Hub
except ImportError:  # Checkout ohne Installation: hub/ liegt neben tools/
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hub"))

from mcp_hub.plugins.gui import ID_MUSTER, GuiPlugin, dokument_id, eigenstaendig  # noqa: E402

HUB_STANDARD = "http://localhost:8080"
FRIST_S = 20


def hub_adresse(wert: str | None) -> str:
    """Adresse des Hubs ohne Schrägstrich und ohne /mcp am Ende. FYOS_HUB_URL ist in FYOS die MCP-Adresse des Hubs
    (http://hub:8080/mcp); hier zählt der Hub selbst. Alles außer http(s) fällt auf die Vorgabe zurück."""
    try:
        teile = urlsplit((wert or "").strip())
        if teile.scheme not in ("http", "https") or not teile.hostname:
            return HUB_STANDARD
        pfad = teile.path.rstrip("/")
        if pfad.endswith("/mcp"):
            pfad = pfad[: -len("/mcp")]
        return f"{teile.scheme}://{teile.netloc.rsplit('@', 1)[-1]}{pfad}"
    except ValueError:
        return HUB_STANDARD


def ansicht_holen(basis: str, i: str) -> dict[str, Any]:
    """gui.zeigen {id} über POST /hub/call; liefert das Ergebnis (id, dokument, ggf. hinweis). Wirft ValueError."""
    roh = json.dumps({"tool": "gui.zeigen", "arguments": {"id": i}}).encode("utf-8")
    anfrage = urllib.request.Request(
        f"{basis}/hub/call", data=roh, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=FRIST_S) as r:  # noqa: S310 - http(s) ist oben erzwungen
            antwort = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            antwort = json.loads(e.read())  # Fehler des Hubs sind JSON mit ok=false
        except ValueError:
            raise ValueError(f"Hub {basis}: HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ValueError(f"Hub {basis} nicht erreichbar: {getattr(e, 'reason', e)}") from None
    if not isinstance(antwort, dict) or not antwort.get("ok"):
        fehler = antwort.get("error") if isinstance(antwort, dict) else None
        raise ValueError(f"gui.zeigen {i}: {fehler or antwort}")
    ergebnis = antwort.get("result")
    if not isinstance(ergebnis, dict) or not isinstance(ergebnis.get("dokument"), dict):
        raise ValueError(f"gui.zeigen {i}: kein Dokument in der Antwort")
    return ergebnis


def main(argv: list[str]) -> int:
    oeffnen = "--oeffnen" in argv
    argv = [a for a in argv if a != "--oeffnen"]
    if not argv or argv[0] in ("-h", "--help") or len(argv) > 2:
        print((__doc__ or "").strip())
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    quelle = argv[0]
    try:
        if ID_MUSTER.fullmatch(quelle):
            ergebnis = ansicht_holen(hub_adresse(os.environ.get("FYOS_HUB_URL")), quelle)
            doc, i = ergebnis["dokument"], quelle
            if ergebnis.get("hinweis"):
                print(ergebnis["hinweis"], file=sys.stderr)
        else:
            datei = Path(quelle)
            if not datei.is_file():
                print(f"{quelle}: weder eine Ansicht-Id (g- und 12 Hex-Zeichen) noch eine Datei", file=sys.stderr)
                return 2
            felder = json.loads(datei.read_text(encoding="utf-8"))
            if not isinstance(felder, dict):
                raise ValueError("die Datei muss ein JSON-Objekt sein (die Felder von gui.bauen)")
            # Wie gui.bauen (auch vorlage + daten), aber ohne Hub und ohne Ablage: eine Live-Quelle wird nicht abgefragt.
            doc = GuiPlugin().dokument(felder, live=False)
            i = dokument_id(doc)
    except (ValueError, OSError) as e:
        print(f"{quelle}: {e}", file=sys.stderr)
        return 1
    ziel = Path(argv[1]) if len(argv) == 2 else Path(f"gui-{i}.html")
    ziel.write_text(eigenstaendig(doc), encoding="utf-8")
    print(ziel.resolve())
    if oeffnen:
        webbrowser.open(ziel.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
