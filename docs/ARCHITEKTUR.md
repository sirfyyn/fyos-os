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
│ fyos-agent (Grundlage)  OpenClaw-Mod: Bild, Patches,         │
│                         Verhaltens-Plugins, Workspace-       │  allgemein
│                         Vorlagen, Verhaltensvertrag, Skills  │
├──────────────────────────────────────────────────────────────┤
│ OpenClaw (Upstream)     ghcr.io/openclaw/openclaw@<digest>   │
└──────────────────────────────────────────────────────────────┘
```

### fyos-agent — das Agentenverhalten als Grundlage

Ein Mod auf das Upstream-Bild von OpenClaw, kein Quell-Fork: Basisbild per Digest,
versionsgebundene Patches (brechen bei Upstream-Drift den Bau ab), FYOS-Plugins
unter `/opt/fyos/`. Das Verhalten steht in drei Formen:

1. **Verhaltensvertrag** (`vertrag/`): Betriebskonzept (Kleines selbst mit Rückweg,
   Schweres entscheidet der Mensch), Freigabeweg, Fortschrittsmeldungen,
   Meldebudget und Ruhezeiten, Werkzeugentdeckung, Datenschutz (Geheimnisse und
   Finanz-/Gesundheitsdaten bleiben lokal).
2. **Workspace-Vorlagen** (`workspace/*.md.tmpl`): `AGENTS.md`, `SOUL.md`,
   `IDENTITY.md`, `USER.md` mit Platzhaltern (`{{agent.name}}`, `{{besitzer.name}}`,
   `{{sprache}}` …), gerendert aus `fyos.yaml`.
3. **Verhaltens-Plugins** (`plugins/`): Freigabe im Chat, Kontext-Edit,
   Meldebudget, Priorität, Schleifen-Läufer.

### fyos-os — Shell, Hub, Auslieferung

- **Hub** (`hub/`, Python-Paket `mcp_hub`): MCP-Server mit Plugin-Registry. Plugins
  kommen aus der YAML-Konfiguration (`module:`) oder über die Entry-Point-Gruppe
  `mcp_hub.plugins`. Hosts, Redis, Qdrant, Anmeldung (OIDC) kommen aus Konfiguration
  oder Umgebung, nie aus dem Code.
- **Shell** (`web/`): Fenster, Dock, Kacheln, Menüleiste. Flächen kommen aus
  `registriereFlaechen()` und dynamisch aus Hub-Apps (`ui://`). Ein Plugin mit
  Oberfläche liefert eine Hub-App; die Shell zeigt sie ohne eigenen Code.
- **Vertrag Shell ↔ Hub**: `/hub-api/apps`, `/hub-api/resource`, `/hub-api/app-call`,
  `/hub-api/os/{strom,melden,antwort}` (siehe `docs/HUB-VERTRAG.md`).

### Plugins

Ein Plugin-Repo ist ein Python-Paket mit Entry-Point `mcp_hub.plugins` und optional
Oberflächen (`ui://`-HTML), Skills für den Agenten und Begleitskripten. Installiert
wird es ins Hub-Bild (`uv pip install`) oder per `module:`-Eintrag. Plugins, die Vorgänge,
Termine, Mails oder Dokumente zeigen, tragen keinen festen Dienst ein, sondern fragen eine gemeinsame Quelle des Hubs
(`mcp_hub.vorgaenge`, `mcp_hub.termine`, `mcp_hub.postfach`, `mcp_hub.dokumente`; `ERWEITERN.md` §2.13 bis §2.16): ein Dienst,
wenn einer eingetragen ist, sonst die Ablage eines Plugins.

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
| hub | `fyos-os/hub` | 8080 (`/mcp`, `/hub/*`, `/health`, `/metrics`) | `MCP_HUB_CONFIG_PATH`, `FYOS_OEFFENTLICH_URL`, `FYOS_ERLAUBTE_HOSTS`, `FYOS_OIDC_ISSUER`, `REDIS_URL`, `QDRANT_URL`, `FYOS_AGENT_URL`, `FYOS_AGENT_TOKEN` |
| agent | `fyos-agent/openclaw` | 18789 (Gateway) | `FYOS_CONFIG` (Pfad zu `fyos.yaml`), `FYOS_MODELL_BASIS_URL`, `FYOS_MODELL_NAME`, `FYOS_MODELL_SCHLUESSEL`, `FYOS_HUB_URL`, `OPENCLAW_GATEWAY_TOKEN`, `FYOS_OEFFENTLICH_URL` |
| redis | `redis:7` | 6379 | – |

Der Browser spricht nur mit `web`: `/hub-api/*` geht an den Hub, `/agent/*` mit Präfix an
das OpenClaw-Gateway (Control UI unter `/agent/`). Die Shell streicht dabei die
Herkunftsköpfe und erlaubt die Einbettung im eigenen Ursprung (`web/README.md`); das
Gateway lässt nur den Ursprung `FYOS_OEFFENTLICH_URL` zu. Anmeldung ist optional
(OIDC-Forward-Auth vor `web`); ohne sie läuft FYOS als Einzelplatz im eigenen Netz.

Hub und Agent sind gekoppelt (`KOPPLUNG-OPENCLAW.md`): Der Agent ruft die Werkzeuge des
Hubs über MCP, die Brücke `fyos-bruecke` meldet seine Aktivität ohne Inhalte an den Hub,
und der Hub liest Workboard, Skills, Cron und Nutzung des Agenten über eine feste
Methodenliste. Vorgänge und Workboard, Takte und Cron, Audit und Nutzung erscheinen so
je in einer Ansicht.

## Sauberkeit

`tools/sauber.py` läuft in jedem Repo der Distribution in der CI und lokal vor jedem
Commit. Verbotene Wörter stehen nur als Hash in `.sauber/verboten.sha256`.
Plugin-Repos dürfen persönliche Konfiguration enthalten; sie bleiben privat.

Die Doku soll nur versprechen, was es gibt: `tools/doku_pruefen.py` gleicht jede Nacht (und auf Knopfdruck) alle
Markdown-Dateien dieses Repos mit dem Dateibaum ab. Tote Links und Anker, genannte Pfade und die festen Abschnitte der
READMEs fallen so auf, bevor jemand darüber stolpert. Was die Doku von anderen Repos oder vom Betrieb nennt, steht mit
Grund in `.doku/ausserhalb.txt`; die Liste meldet sich selbst, wenn ein Eintrag nichts mehr trifft.
