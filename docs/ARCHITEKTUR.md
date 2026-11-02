# FYOS — For Your Own Sake: Architektur der Distribution

FYOS ist ein persönliches Betriebssystem im Browser, das auf einem eigenen Agenten
aufbaut. Die Distribution enthält nur Allgemeines. Alles, was ein bestimmtes Zuhause,
ein Konto oder eine Person braucht, kommt als Plugin aus einem eigenen Repo.

## Schichten

```text
┌──────────────────────────────────────────────────────────────┐
│ Plugins (je ein Repo)   fyos-plugin-finanzen, -haus, …       │  persönlich, optional
├──────────────────────────────────────────────────────────────┤
│ fyos-os                 web/  Desktop-Shell (Astro/Solid)    │
│                         hub/  MCP-Hub-Kern + Kern-Plugins    │  allgemein
│                         deploy/ Compose + Kubernetes         │
├──────────────────────────────────────────────────────────────┤
│ fyos-agent (Grundlage)  der Agent: Runner auf pi-durable     │  allgemein
│                         (Bild fyos-agent/runner)             │
└──────────────────────────────────────────────────────────────┘
```

### fyos-agent — der Agent

Der Agent ist der Runner aus `fyos-agent` (`runner/`): ein dauerhafter Prozess auf pi-durable mit eigener Oberfläche,
Gesprächen, Läufen, Freigaben und Takten. Sein Zustand liegt in SQLite unter `~/.fyos` (im Container
`/home/node/.fyos`, ein Volume). Konfiguration: `agent-runner.json` (Vorlage
`fyos-agent/runner/beispiele/agent-runner.beispiel.json`); Modell und Token kommen aus der Umgebung.

### fyos-os — Shell, Hub, Auslieferung

- **Hub** (`hub/`, Python-Paket `mcp_hub`): MCP-Server mit Plugin-Registry. Plugins
  kommen aus der YAML-Konfiguration (`module:`) oder über die Entry-Point-Gruppe
  `mcp_hub.plugins`. Hosts, Redis, Qdrant, Anmeldung (OIDC) kommen aus Konfiguration
  oder Umgebung, nie aus dem Code.
- **Shell** (`web/`): Fenster, Dock, Kacheln, Menüleiste. Flächen kommen aus
  `registriereFlaechen()` und dynamisch aus Hub-Apps (`ui://`). Ein Plugin mit
  Oberfläche liefert eine Hub-App; die Shell zeigt sie ohne eigenen Code.
- **Vertrag Shell ↔ Hub**: `/hub-api/apps`, `/hub-api/resource`, `/hub-api/app-call`,
  `/hub-api/os/{strom,melden,antwort}` und, für Dateien, `/hub-api/dateien/datei` (siehe `docs/HUB-VERTRAG.md`).

### Plugins

Ein Plugin-Repo ist ein Python-Paket mit Entry-Point `mcp_hub.plugins` und optional
Oberflächen (`ui://`-HTML), Skills für den Agenten und Begleitskripten. Installiert
wird es ins Hub-Bild (`uv pip install`) oder per `module:`-Eintrag. Plugins, die Vorgänge,
Termine, Mails oder Dokumente zeigen, tragen keinen festen Dienst ein, sondern fragen eine gemeinsame Quelle des Hubs
(`mcp_hub.vorgaenge`, `mcp_hub.termine`, `mcp_hub.postfach`, `mcp_hub.dokumente`; `ERWEITERN.md` §2.13 bis §2.16): ein Dienst,
wenn einer eingetragen ist, sonst die Ablage eines Plugins. Dateien (Notizen, Bilder, PDFs) liegen in einer Ordner-Ablage
des Kerns (`mcp_hub.dateien`, `FYOS_DATEIEN`, ein Volume; `ERWEITERN.md` §2.17), die das Plugin `dateien` mit der App
„Dateien“ zeigt.

| Repo | Inhalt |
|---|---|
| fyos-plugin-finanzen | Finanzen mit MoneyMoney (Export auf dem Mac, Import, Werkzeuge `finance.*`) |
| fyos-plugin-haus | Haus, Licht, Anwesenheit, Augen, Stimme, Belegung, Wetter |
| fyos-plugin-konten | Konten, Passwort-Tresor, Medien, Fotos, Mail, Kalender, Bestellungen |
| fyos-plugin-kalender | Kalender mit CalDAV- und ICS-Konten, meldet sich als Termin-Quelle des Hubs an (`mcp_hub.termine`) |
| fyos-plugin-mail | Mails nur lesen, aus IMAP-Konten mit App-Passwort (Werkzeuge `mail.*`); meldet sich als Postfach-Quelle des Hubs an (`mcp_hub.postfach`, `ERWEITERN.md` §2.15) |
| fyos-plugin-betrieb | Cluster, Git, CI, Netz und Speicher |
| fyos-plugin-modell | eigenes Sprachmodell, Rechner, Messkette |
| fyos-plugin-leitstand | Leitstand, Vorgänge, Agenten-Schleifen einer bestimmten Installation |

## Laufzeit

| Dienst | Bild | Port | Wichtige Umgebung |
|---|---|---|---|
| web | `fyos-os/web` | 8080 (nginx) | `FYOS_HUB_UPSTREAM` (z. B. `http://hub:8080`), `FYOS_AGENT_UPSTREAM` |
| hub | `fyos-os/hub` | 8080 (`/mcp`, `/hub/*`, `/health`, `/metrics`) | `MCP_HUB_CONFIG_PATH`, `FYOS_OEFFENTLICH_URL`, `FYOS_ERLAUBTE_HOSTS`, `FYOS_OIDC_ISSUER`, `REDIS_URL`, `QDRANT_URL`, `FYOS_AGENT_TOKENS` |
| agent | `fyos-agent/runner` | 18438 | `FYOS_RUNNER_TOKEN` (= `FYOS_AGENT_TOKEN` der Oberfläche), `FYOS_HUB_URL`, `FYOS_MODELL_BASIS_URL`, `FYOS_MODELL_NAME`, `FYOS_MODELL_SCHLUESSEL`; Konfiguration `/etc/fyos/agent-runner.json` |
| redis | `redis:7` | 6379 | – |

Der Browser spricht nur mit `web`: `/hub-api/*` geht an den Hub, `/api/agent/*` ohne Präfix an den Runner. Das Token des
Runners setzt `web` (nginx, `FYOS_AGENT_TOKEN`), der Browser kennt es nie; ohne den Kopf `X-FYOS-Agent: 1` antwortet der
Weg 404 (`web/README.md`). Anmeldung ist optional (OIDC-Forward-Auth vor `web`); ohne sie läuft FYOS als Einzelplatz im
eigenen Netz.

Hub und Agent sind gekoppelt: Der Agent ruft die Werkzeuge des Hubs, und das Plugin `agent` (`/hub/agent/*`) nimmt
Eingänge an (Web-Chat, Alarme) und Meldungen des Runners über seine Läufe entgegen. Gesprochen wird nur über diese Wege;
eine zweite Brücke gibt es nicht.

## Sauberkeit

`tools/sauber.py` läuft in jedem Repo der Distribution in der CI und lokal vor jedem
Commit. Verbotene Wörter stehen nur als Hash in `.sauber/verboten.sha256`.
Plugin-Repos dürfen persönliche Konfiguration enthalten; sie bleiben privat.

Die Doku soll nur versprechen, was es gibt: `tools/doku_pruefen.py` gleicht jede Nacht (und auf Knopfdruck) alle
Markdown-Dateien dieses Repos mit dem Dateibaum ab. Tote Links und Anker, genannte Pfade und die festen Abschnitte der
READMEs fallen so auf, bevor jemand darüber stolpert. Was die Doku von anderen Repos oder vom Betrieb nennt, steht mit
Grund in `.doku/ausserhalb.txt`; die Liste meldet sich selbst, wenn ein Eintrag nichts mehr trifft.
