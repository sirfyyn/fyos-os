# fyos-ansicht — gebaute FYOS-Ansichten im Terminal

Ein Mod für Claude Code. Baut der Agent mit dem Hub-Plugin `gui` eine Ansicht (Kennzahlen, Diagramm, Tabelle, Rechner …),
öffnet der Mod sie rechts im Panel des Terminals, ohne dir den Fokus zu nehmen. Claude Code im Terminal ist kein
MCP-Apps-Host und kann die App deshalb nicht selbst zeigen. Der Hub liefert die Ansicht darum als ganze Seite
(`GET /hub/gui/<id>`; Live-Quellen laden über `/hub/gui/<id>/daten` nach), und der Mod terminal-browser zeichnet sie als
Bild in sein Panel.

## Voraussetzungen

- Ein laufender FYOS-Hub mit dem Plugin `gui` (es gehört zum Kern) und Claude Code, das den Hub als MCP-Server nutzt,
  zum Beispiel `claude mcp add --transport http fyos http://localhost:8080/mcp`.
- Der Hub muss für Claude Code selbst erreichbar sein, nicht nur die Shell (Abschnitt „Hub-Adresse“).
- Der Mod terminal-browser (Projekt [zenbu-labs/terminal-browser](https://github.com/zenbu-labs/terminal-browser)) samt
  App und ein Terminal mit kitty-Grafikprotokoll, etwa kitty oder Ghostty. Einrichtung und Einstellungen der App
  (auch zur Telemetrie) regelt dieses Projekt. Ohne ihn tut fyos-ansicht nichts.
- Mods nutzen die Schnittstelle „Function Hooks“ von Claude Code. Sie kann sich zwischen Versionen ändern. Wo deine
  Version sie nicht von selbst anbietet, setzt du `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` unter `env` in der
  Einstellungsdatei von Claude Code, so verlangt es auch terminal-browser. Dieser Mod besteht `claude plugin validate`
  und `claude plugin test` mit Claude Code 2.1.295.

## Einrichten

Im Checkout dieses Repos, in Claude Code:

```text
/plugin marketplace add ./tools/claude-code
/plugin install fyos-ansicht@fyos-tools
```

Danach Claude Code neu starten. Nur für eine Sitzung und ohne Installation:

```sh
claude --plugin-dir tools/claude-code/fyos-ansicht
```

## Benutzen

- Ruft Claude `gui.bauen` oder `gui.zeigen` mit einer `id` auf, auch über `hub__call_tool`, öffnet der Mod die Ansicht
  rechts im Panel. Der Fokus bleibt im Eingabefeld; ein Klick ins Panel gibt ihm die Tastatur. Die Liste aller
  Ansichten und reine Datenabfragen öffnen nichts.
- `/ansicht` öffnet die zuletzt gezeigte Ansicht dieser Sitzung noch einmal, `/ansicht g-…` eine bestimmte (die Id
  steht in der Antwort von `gui.bauen`), `/ansicht zu` schließt das Panel.
- `FYOS_ANSICHT_AUTO=0` schaltet das automatische Öffnen ab. `/ansicht` geht weiter.
- Eine Live-Ansicht (`gui.bauen` mit `quelle`) lädt im Panel selbst nach.

## Hub-Adresse

`FYOS_HUB_URL` nennt den Hub; Vorgabe ist `http://localhost:8080`, der Standardport des Hubs. Es ist dieselbe Adresse,
die FYOS dem Agenten gibt, mit `/mcp` am Ende (`http://localhost:8080/mcp`). Der Mod schneidet das `/mcp` ab, denn die
Seite liegt unter `/hub/gui/<id>` am Hub selbst. Setze die Variable, bevor du Claude Code startest, oder unter `env` in
der Einstellungsdatei von Claude Code.

Seit 0.1.1 reicht auch die Shell `/hub/gui/…` durch, nur lesend (siehe `docs/HUB-VERTRAG.md`, Abschnitt „nginx der
Shell“). Dem Mod genügt also eine Adresse, unter der die Shell oder der Hub antwortet. Claude Code selbst braucht für die
MCP-Verbindung den Hub, denn `/mcp` geht nicht durch die Shell. Am einfachsten zeigt `FYOS_HUB_URL` deshalb auf dieselbe
Adresse wie die MCP-Verbindung:

- **`fyos-hub` direkt gestartet:** `http://localhost:8080`, die Vorgabe.
- **Docker Compose:** Der Hub veröffentlicht keinen Port. Eine Override-Datei neben `docker-compose.yml` öffnet einen,
  nur für diesen Rechner, denn innen ist der Hub offen: `FYOS_HUB_URL=http://127.0.0.1:8081/mcp`.

  ```yaml
  # deploy/compose/docker-compose.override.yml
  services:
    hub:
      ports:
        - "127.0.0.1:8081:8080"
  ```

  Ohne `FYOS_HUB_URL` trifft die Vorgabe die Shell auf `http://localhost:8080` (oder dem Port aus `FYOS_PORT`); auch
  dort gehen die Ansichten auf.
- **Kubernetes:** `kubectl port-forward svc/hub 8081:8080` (mit `-n <Namespace>`), dann
  `FYOS_HUB_URL=http://127.0.0.1:8081/mcp`. Die Adresse der Shell geht auch, wenn terminal-browser deren Anmeldung hat.

## Was der Mod tut

- Er liest nur die Ergebnisse von `gui__bauen`, `gui__zeigen` und `hub__call_tool` und reicht sie unverändert weiter.
  Er schickt nichts ins Modell, liest keine Dateien, startet keine Prozesse und hat kein eigenes Netz. Laden tut
  terminal-browser.
- Er liest die Umgebungsvariablen `FYOS_HUB_URL`, `FYOS_ANSICHT_AUTO` und `CLAUDE_JOB_DIR` und schreibt keine.
- Die Ansicht läuft wie in der Shell in einer Sandbox ohne Netz: das vom Agenten erzeugte Skript erreicht weder den Hub
  noch das Internet.

## Grenzen

- Nur in der Terminal-Oberfläche von Claude Code. Desktop-App, claude.ai und Handy sind MCP-Apps-Hosts und zeigen die
  App selbst.
- In angehängten Hintergrund-Sitzungen (der Mod erkennt sie an `CLAUDE_JOB_DIR`) zeichnet kitty das Panel, aber nicht
  das Bild darin: es bleibt grau. Der Mod öffnet dort nichts und zeigt einen Hinweis. In einer normalen Sitzung öffnet
  `/ansicht <id>` die Ansicht.
- Ist der Hub nicht erreichbar, zeigt das Panel nur die Fehlerseite des Browsers. Der Mod prüft das nicht vorher.
- Ohne den Mod macht `tools/gui_datei.py` aus einer Ansicht eine HTML-Datei, die `--oeffnen` im Standardbrowser zeigt.

## Tests

```sh
claude plugin validate tools/claude-code/fyos-ansicht     # statische Prüfung der Hooks und Aufrufe
claude plugin test tools/claude-code/fyos-ansicht         # 6 Tests, ohne Sitzung und ohne Netz
```

`claude plugin test` ist der Läufer von Claude Code: Die Tests holen ihr Werkzeug aus dem Testkit, das Claude Code
selbst mitbringt (Modul „claude-code/testing“). Mit einem anderen Läufer laufen sie nicht, und die CI dieses Repos
führt sie darum nicht aus.
