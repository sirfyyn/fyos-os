# FYOS — For Your Own Sake: architecture of the distribution

FYOS is a personal operating system in the browser, built on an agent of your own. The distribution contains only
general-purpose parts. Everything a particular home, account or person needs comes as a plugin from a repo of its own.

## Layers

```text
┌──────────────────────────────────────────────────────────────┐
│ Plugins (one repo each) fyos-plugin-finanzen, -haus, …       │  personal, optional
├──────────────────────────────────────────────────────────────┤
│ fyos-os                 web/  desktop shell (Astro/Solid)    │
│                         hub/  MCP hub core + core plugins    │  general
│                         deploy/ Compose + Kubernetes         │
├──────────────────────────────────────────────────────────────┤
│ fyos-agent (foundation) the agent: runner on pi-durable      │  general
│                         (image fyos-agent/runner)            │
└──────────────────────────────────────────────────────────────┘
```

### fyos-agent — the agent

The agent is the runner from `fyos-agent` (`runner/`): a long-running process on pi-durable with its own interface,
conversations, runs, approvals and schedules. Its state lives in SQLite under `~/.fyos` (in the container
`/home/node/.fyos`, a volume). Configuration: `agent-runner.json` (template
`fyos-agent/runner/beispiele/agent-runner.beispiel.json`); model and token come from the environment.

### fyos-os — shell, Hub, delivery

- **Hub** (`hub/`, Python package `mcp_hub`): MCP server with a plugin registry. Plugins come from the YAML
  configuration (`module:`) or through the entry point group `mcp_hub.plugins`. Hosts, Redis, Qdrant and login (OIDC)
  come from configuration or the environment, never from the code.
- **Shell** (`web/`): windows, dock, tiles, menu bar. Surfaces come from `registriereFlaechen()` and dynamically from
  hub apps (`ui://`). A plugin with an interface ships a hub app; the shell shows it without any code of its own.
- **Contract shell ↔ Hub**: `/hub-api/apps`, `/hub-api/resource`, `/hub-api/app-call`,
  `/hub-api/os/{strom,melden,antwort}` and, for files, `/hub-api/dateien/datei` (see `docs/HUB-CONTRACT.md`).

### Plugins

A plugin repo is a Python package with the entry point `mcp_hub.plugins` and, optionally, interfaces (`ui://` HTML),
skills for the agent and companion scripts. It is installed into the hub image (`uv pip install`) or through a
`module:` entry. Plugins that show tickets, appointments, mail or documents do not hard-code a service; they ask a shared
source of the Hub (`mcp_hub.vorgaenge`, `mcp_hub.termine`, `mcp_hub.postfach`, `mcp_hub.dokumente`; `EXTENDING.md`
§2.13 to §2.16): a service if one is configured, otherwise a plugin's store. Files (notes, pictures, PDFs) live in a
folder store of the core (`mcp_hub.dateien`, `FYOS_DATEIEN`, a volume; `EXTENDING.md` §2.17), which the plugin
`dateien` shows with the app "Files".

| Repo | Contents |
|---|---|
| fyos-plugin-finanzen | Finances with MoneyMoney (export on the Mac, import, tools `finance.*`) |
| fyos-plugin-haus | Home, lights, presence, cameras, voice, occupancy, weather |
| fyos-plugin-konten | Accounts, password vault, media, photos, mail, calendar, orders |
| fyos-plugin-kalender | Calendar with CalDAV and ICS accounts; registers as the appointment source of the Hub (`mcp_hub.termine`) |
| fyos-plugin-mail | Read-only mail from IMAP accounts with an app password (tools `mail.*`); registers as the mailbox source of the Hub (`mcp_hub.postfach`, `EXTENDING.md` §2.15) |
| fyos-plugin-betrieb | Cluster, Git, CI, network and storage |
| fyos-plugin-modell | Your own language model, machines, measurement chain |
| fyos-plugin-leitstand | Control room, tickets, agent loops of a particular installation |

## Runtime

| Service | Image | Port | Important environment |
|---|---|---|---|
| web | `fyos-os/web` | 8080 (nginx) | `FYOS_HUB_UPSTREAM` (e.g. `http://hub:8080`), `FYOS_AGENT_UPSTREAM` |
| hub | `fyos-os/hub` | 8080 (`/mcp`, `/hub/*`, `/health`, `/metrics`) | `MCP_HUB_CONFIG_PATH`, `FYOS_OEFFENTLICH_URL`, `FYOS_ERLAUBTE_HOSTS`, `FYOS_OIDC_ISSUER`, `REDIS_URL`, `QDRANT_URL`, `FYOS_AGENT_TOKENS` |
| agent | `fyos-agent/runner` | 18438 | `FYOS_RUNNER_TOKEN` (= `FYOS_AGENT_TOKEN` of the interface), `FYOS_HUB_URL`, `FYOS_MODELL_BASIS_URL`, `FYOS_MODELL_NAME`, `FYOS_MODELL_SCHLUESSEL`; configuration `/etc/fyos/agent-runner.json` |
| redis | `redis:7` | 6379 | – |

The browser talks only to `web`: `/hub-api/*` goes to the Hub, `/api/agent/*` goes to the runner with the prefix
removed. `web` (nginx, `FYOS_AGENT_TOKEN`) sets the runner's token; the browser never sees it. Without the header
`X-FYOS-Agent: 1` the route answers 404 (`web/README.md`). Login is optional (OIDC forward auth in front of `web`);
without it FYOS runs as a single machine on your own network.

Hub and agent are coupled: the agent calls the Hub's tools, and the plugin `agent` (`/hub/agent/*`) accepts inputs (web
chat, alarms) and the runner's reports about its runs. They talk only over these routes; there is no second bridge.

## Cleanliness

`tools/sauber.py` runs in every repo of the distribution, in the CI and locally before every commit. Forbidden words are
stored only as hashes in `.sauber/verboten.sha256`. Plugin repos may contain personal configuration; they stay private.

The docs should promise only what exists: every night (and on demand) `tools/doku_pruefen.py` checks all Markdown files
of this repo against the file tree. Dead links and anchors, named paths and the fixed sections of the READMEs show up
before anyone trips over them. What the docs name from other repos or from operation is listed with a reason in
`.doku/ausserhalb.txt`; the list reports itself when an entry no longer matches anything.
