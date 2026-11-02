# FYOS Hub

The Hub of FYOS (For Your Own Sake): an MCP server that offers many plugins under one address. A plugin delivers tools
and, if it wants, an interface (`ui://` HTML). The shell shows these interfaces as windows; every MCP client that
supports MCP apps shows them in the conversation.

The Hub speaks three things:

- **MCP** at `/mcp` (Streamable HTTP) for agents and chat clients,
- **REST** at `/hub/*` for the shell and scripts,
- **health** at `/health`.

The exact routes and formats are in [`docs/HUB-CONTRACT.md`](../docs/HUB-CONTRACT.md).

## Installing and starting

```
pip install ".[suche]"          # core; [suche] brings the Qdrant client and numpy (optional)
fyos-hub                        # or: python3 -m mcp_hub.server
```

As an image: `docker build -t fyos-hub hub/` (the build argument `EXTRA_PIP` installs further plugin packages, e.g.
`--build-arg EXTRA_PIP="fyos-plugin-finanzen"`). The image listens on port 8080.

The image installs plugin packages with `uv` instead of `pip`. If they live in a package index of your own, its address
comes as `--build-arg FYOS_INDEX_URL=<index URL>` and thereby goes before PyPI. `--index-strategy first-index` is set
explicitly in the command: uv takes a package only from the first index that carries it, so a package of the same name
on PyPI cannot displace your own (dependency confusion; with `pip --extra-index-url` it could). The version of uv is
pinned in the Dockerfile.

Without a configuration file the Hub loads every installed plugin of the entry point group `mcp_hub.plugins` with its
defaults. A file (`MCP_HUB_CONFIG_PATH`, default `./config.yaml`) is only needed for plugin settings, secrets or
`enabled: false`; see `config.example.yaml`.

## Bundled plugins

| Plugin | Purpose |
|---|---|
| `skills` | search and read work instructions (`<source>/<name>/SKILL.md`) |
| `werkstatt` | workshop: find registered scripts (header block `WERKSTATT`) and run them with a dry run |
| `mcp` | toolbox: look at the Hub's plugins, tools, apps and logs |
| `shell` | layout of the open shell (windows, grid) as tools |
| `os` | connection to the shell: `os.lage`, `os.zeigen`, `os.ausfuehren`, `os.mitteilen`; notices with no one to receive them wait for up to 24 h (docs/NIGHT-WORK.md) |
| `audit` | log of all tool calls (ring buffer, with Qdrant vector search) |
| `event_bus_publisher` | events per tool call on Redis streams (otherwise in memory) |
| `gui` | build views: metrics, bars, history, table … from templates or free-form, as an app and as a page (see below) |
| `dateien` | shared file store with the app "Files": folders, preview, upload by dragging, trash, earlier versions; folder through `FYOS_DATEIEN`, "Open with" for programs on a machine through `oeffnen.gegenstelle` (docs/EXTENDING.md §2.17) |
| `beispiel_app` | notepad with an interface, template for apps of your own |
| `vorgaenge`, `posteingang`, `termine` | work apps "Tickets", "Mail" (read-only) and "Appointments" on the core's sources (§2.13 to §2.15); mail and tickets are things you can drag onto other windows (§3.7) |
| `itsm` | the core's ITSM: tickets (INC, CHG, VOR) with status, comments, history and approvals in the Hub's Redis (`fyos:itsm:*`); registers as the store for tickets and so fills the app "Tickets"; the runner reads `itsm.wartend` and `itsm.vorgang` (docs/ITSM.md) |
| `suche` | search across everything (⌘K): tickets, mail, files, notes and sources that plugins register (§2.18) |
| `echo`, `math` | reference plugins, off by default |

Everything else (finances, home, operations …) comes as packages of their own that register through the entry point.

## Building views (`gui`)

The plugin `gui` lets the agent build an interactive view for the moment instead of only answering. `gui.vorlagen`
lists nine templates (metrics, bars, history, table, comparison, flow, timeline, status, diagram; the diagram template
embeds SeeCode, MIT, see `NOTICE`). `gui.bauen` shows one with data (`vorlage` and `daten`), on request live from a
reading tool (`quelle`), or a free-form one (`html`, `css`, `js`). The view runs in a sandbox without network;
`gui.zeigen` fetches a built one again.

The instructions (skill `generative-ui`) and the templates are package data of the core (`mcp_hub/skills/generative-ui/`).
The plugin `skills` finds the skill without any setting through the entry point group `fyos.skills` (source `kern`);
templates of your own are added with `config: {vorlagen: <folder>}`. At most 300 views are stored in `mcp_hub.kv`: with
`REDIS_URL` in Redis (as long as its persistence lasts), otherwise in the process's memory (then until the Hub
restarts).

For surfaces without an MCP Apps host the Hub delivers a view as a whole page: `GET /hub/gui/<id>`, plus
`GET /hub/gui/<id>/daten` for fresh data from a live source (description in
[`docs/HUB-CONTRACT.md`](../docs/HUB-CONTRACT.md)). The mod [`fyos-ansicht`](../tools/claude-code/fyos-ansicht/README.md)
for Claude Code uses this to open them in the terminal panel.

## A plugin of your own

```
# pyproject.toml of the plugin package
[project.entry-points."mcp_hub.plugins"]
meins = "mein_paket.plugin:MeinPlugin"
```

```
uv pip install ./mein-plugin    # afterwards the Hub loads it without an entry in config.yaml
```

The class inherits from `mcp_hub.plugin.HubPlugin` (`register`, `describe_tools`, `call`, optionally `health`,
`describe_resources`). If the plugin has an interface, the HTML files live in `<package>/ui/`; the plugin passes the
package name to `mcp_hub.plugins._oberflaeche.oberflaeche(datei, "mein_paket")`, and
`_identitaet.registriere_app(...)` gives the app its title, symbol and colour tone. `plugins/beispiel_app.py` shows
everything in 200 lines.

## Environment variables

| Variable | Effect |
|---|---|
| `MCP_HUB_CONFIG_PATH` | path of the YAML file |
| `MCP_HUB_HOST`, `MCP_HUB_PORT`, `MCP_HUB_PATH` | address, port (8080), MCP path (`/mcp`) |
| `FYOS_OEFFENTLICH_URL` | public address of the installation (links, allowed origin, audience of the login) |
| `FYOS_ERLAUBTE_HOSTS` | further allowed host names/origins, comma-separated (default: `localhost`, `127.0.0.1`) |
| `FYOS_OS_URL` | address of the shell, if not `<FYOS_OEFFENTLICH_URL>/os` |
| `TZ` | the Hub's time zone (daily counters and time windows of schedules), e.g. `Europe/Berlin`; UTC if unset |
| `REDIS_URL` | Redis for views, search trail, events, OS bridge; without it: memory in the process |
| `QDRANT_URL` | vector search in the audit log; without it: ring buffer |
| `FYOS_EMBED_URL`, `FYOS_EMBED_MODEL`, `FYOS_EMBED_KEY` | OpenAI-compatible embedding service (`/v1/embeddings`) for audit and tool search |
| `FYOS_SKILLS_PATH` | skill sources, separated by `:` (default `/opt/fyos/skills`) |
| `FYOS_REPO_PATH` | the workshop's repo (default `/opt/fyos/repo`) |
| `FYOS_DATEIEN`, `FYOS_DATEIEN_MAX_MB`, `FYOS_DATEIEN_VERSIONEN`, `FYOS_DATEIEN_PAPIERKORB_TAGE` | folder of the file store (in the image `/data/dateien`), largest file in MB (25), earlier versions per file (10), days in the trash (30) |
| `FYOS_OIDC_ISSUER` | turns on login (see below) |

The OS bridge needs Redis for several replicas; a single Hub works only with `REDIS_URL`.

## Limiting schedules

A plugin's recurring jobs appear in `mcp.zeitplan` and `/metrics`. If the plugin runs them through the guard
`mcp_hub.takt`, they can have two limits: `max_pro_tag` (runs per day) and `fenster` (times such as `"07:00-22:00"`,
also across midnight). Outside the window or above the limit the job does not run; the Hub counts the skipped runs
(`fyos_zeitplan_uebersprungen_total{takt, grund}`, plus `fyos_zeitplan_laeufe_heute{takt}`) and keeps a short run log
per schedule (start, duration, result; the last 20 runs) in the Hub's storage. Day and time apply in the Hub's time
zone (`TZ`). Without limits everything runs as before. Plugins include the guard as described in
[`docs/EXTENDING.md`](../docs/EXTENDING.md) §2.12.

## Login (optional)

Inside, on your own network, the Hub is open. If it should also be reachable from the internet, an OpenID Connect
provider is enough: set `FYOS_OIDC_ISSUER` and `FYOS_OIDC_CLIENTS` (client ids, comma-separated); the reverse proxy
sets the header `X-FYOS-Zugang: extern` on requests from the internet. Then `/mcp` requires a valid token for these
requests (RFC 9728, key discovery, only RS256/ES256/EdDSA). Further switches: `FYOS_OIDC_MODUS` (`aus`, `an`,
`streng`), `FYOS_OIDC_HOSTS`, `FYOS_OIDC_REST`, `FYOS_OIDC_BENUTZER`, `FYOS_OIDC_SCOPES`, `FYOS_OIDC_JWKS_URL`. Without
`FYOS_OIDC_ISSUER`, requests from outside are answered with 403.

## Deliberately not included

Only the general-purpose parts were taken over from this Hub's origin. Not included are the plugins `wissen` and
`gedaechtnis`, the development view (`entwicklung`, `lage`), the chat gate (`chat_gateway`: the Hub itself is an
OIDC-protected resource server) and everything that belongs to a single installation. Such plugins belong in packages
of their own.

## Tests

```
pip install -e ".[suche,test]"
python3 -m pytest hub/tests -q
```
