# FYOS shell (`web/`)

The desktop shell of FYOS — For Your Own Sake: home screen, work screens made of windows, dock, menu bar, agent dock,
notices. It contains no content of its own: surfaces come from the Hub (apps), from plugins (`registriereFlaechen`) and
from the runtime configuration (external services).

Technology: Astro 5 (static) with SolidJS (not React), Tailwind 4, Kobalte. Served by nginx on port 8080.

## How the shell talks

The browser talks only to this server:

| Path | goes to | Purpose |
| --- | --- | --- |
| `/hub-api/apps`, `/hub-api/resource`, `/hub-api/app-call` | `${FYOS_HUB_UPSTREAM}/hub/…` | list hub apps, load interfaces, call tools |
| `/hub-api/os/*` | `${FYOS_HUB_UPSTREAM}/hub/os/…` | OS bridge: the shell checks in (`lib/os/bruecke.ts`) and picks up the agent's notices, including those queued at night |
| `/hub-api/dateien/datei` | `${FYOS_HUB_UPSTREAM}/hub/dateien/datei` | download (GET) and upload (PUT, without buffering; the Hub limits the size) files of the store; uploads come from the shell (`lib/mcp-apps/host.ts`), not from the app |
| `/hub/gui/<id>`, `/hub/gui/<id>/daten` | `${FYOS_HUB_UPSTREAM}/hub/gui/…` | built views as a whole page for a link (GET only, the path stays; reasons in `docs/HUB-CONTRACT.md`) |
| `/api/agent/*` | `${FYOS_AGENT_UPSTREAM}/…` (prefix removed) | agent runner for the native agent app (dock and surface `nativ:agent`): conversations, live stream (SSE), approvals, runs. Only with the header `X-FYOS-Agent: 1`, otherwise 404; nginx sets `Authorization: Bearer ${FYOS_AGENT_TOKEN}` and strips the browser's cookie and authorization; no buffering, read timeout 1 h |
| `/fyos.config.json` | file `/etc/fyos/fyos.config.json` | runtime configuration |
| `/healthz` | nginx | health check |

The template `nginx/default.conf.template` is an envsubst template (`NGINX_ENVSUBST_FILTER=FYOS_`). Environment:

| Variable | Default in the image | Purpose |
| --- | --- | --- |
| `FYOS_HUB_UPSTREAM` | `http://hub:8080` | Hub |
| `FYOS_AGENT_UPSTREAM` | `http://agent:18438` | the agent (runner), without a path |
| `FYOS_AGENT_TOKEN` | empty | the runner's token; nginx sets it as `Authorization: Bearer …`. If it is empty, the runner rejects every request (401). |

There is no fixed resolver; the upstreams are names that nginx resolves at startup.

**Runner access:** the browser never sees the runner token; nginx sets it. So anyone who reaches `/api/agent/` talks
with the runner's permissions. If you expose the shell beyond your own network, put a login in front of it (a proxy
with login); the agent app recognises a redirect to the login and offers "Sign in". The required header
`X-FYOS-Agent: 1` keeps foreign pages out: a browser sends it cross-origin only after a preflight, which nginx does not
answer. In the dev server: `FYOS_DEV_RUNNER=http://localhost:18438 FYOS_DEV_RUNNER_TOKEN=… npm run dev`.

## Structure

```
src/
  pages/            index (redirects to /os/), os (the shell), os/allein (one surface alone in a tab), 404
  components/os/    shell, home screen, Start (search), dock, menu bar, window, grid, menu,
                    notices, control center, help, app frame, symbol
  components/apps/  AppEingebettet (shows a hub app in a window)
  lib/os/           model: surfaces, layout, screens, menus, dragging, opening (deep links), notices,
                    symbols, register.ts (the interface for plugins)
  lib/mcp-apps/     host for MCP apps (ui:// interfaces in an iframe, hardening, state, pins)
  lib/config.ts     names, agent and external services from build time and runtime
  plugins/          files here are executed when the shell starts (see below)
  styles/           theme and OS styles
tests/unit/         Vitest (jsdom)
nginx/              template and default configuration
Dockerfile          node:22-alpine builds, nginx:1.27-alpine serves
```

## `registriereFlaechen`

`lib/os/register.ts` is the one interface through which plugins bring surfaces into the shell. The call can be repeated
and may happen at any time; the shell redraws.

```ts
import { registriereFlaechen } from '~/lib/os/register';

registriereFlaechen({
  flaechen: [{ id: 'seite:notizen', titel: 'Notes', gruppe: 'Arbeit', art: 'seite', kuerzel: 'No', pfad: '/notizen/' }],
  symbole: { 'seite:notizen': ['file-text', 200] },            // glyph (Lucide name) and colour tone 0–359
  gruppen: { reihenfolge: ['Arbeit'], plugin: { notizen: 'Arbeit' }, app: { notizen__liste: 'Arbeit' } },
  standardPlaetze: [{ name: 'Writing', ids: ['seite:notizen', 'app:kalender__heute'] }],
  alias: { 'seite:alt': 'seite:notizen' },
  dinge: { notiz: { name: 'Note', pfad: '/notizen/' } },      // optional: draggable things (fyos://notiz/<id>)
  quelle: 'mein-plugin',                                       // optional: replaces earlier entries from the same source
});
```

| Field | Meaning |
| --- | --- |
| `flaechen` | pages (`art: 'seite'` with `pfad`, runs in a window), external services (`extern: <url>`, new tab) and native surfaces (`art: 'nativ'` with `laden`, a Solid component in the window) |
| `symbole` | glyph and colour tone per surface; hub apps bring their own face |
| `gruppen` | order of the groups in Start and assignment of hub apps to a group (first the full tool name, then the plugin prefix before `__`, otherwise "Apps") |
| `standardPlaetze` | templates that Start offers; missing surfaces are skipped |
| `alias` | old ids lead to today's surface (saved layouts, bookmarks, `?offen=`) |
| `dinge` | types of draggable things: the shell opens the surface with the given path and tells it which thing is meant |
| `quelle` | a new registration from the same source replaces the old one |

Where the call belongs: every file `src/plugins/*.ts` is executed when the shell loads. A plugin puts a file there that
calls `registriereFlaechen`; the shell itself stays unchanged.

## How a plugin with a hub app appears

A Hub plugin whose tool has an interface (`_meta.ui.resourceUri`) appears in the shell without an entry: the shell
queries `/hub-api/apps` (at startup, every two minutes and when you return to the tab). Surface, dock entry and catalog
tile come from that.

- The shell takes title, subtitle, category, symbol and colour from the Hub (top level of `/hub/apps` or `_meta.app`
  on the tool: `titel`, `untertitel`, `symbol`, `ton`, `kategorie`, `icon`); if something is missing, it derives it
  from name and description, the colour from the name.
- The group in Start comes from `gruppen.app` / `gruppen.plugin`; without an entry the app is in "Apps".
- Tools with the same interface are one surface. Only reading tools without required fields can be pinned to the home
  screen.
- Deep link: `/os/?offen=app:<plugin>__<tool>[&eingabe=<base64url(JSON)>]` opens the app; the input only for reading
  tools.

Pages that a plugin serves itself run as `art: 'seite'` in a window (iframe, same origin).

## Runtime configuration

The name comes from build time (`PUBLIC_FYOS_NAME`, default "FYOS"), everything else from `/fyos.config.json`
(example: `public/fyos.config.example.json`). If the file is missing, the shell runs with the defaults. The origin is
always `window.location.origin`.

```json
{
  "name": "FYOS",
  "oeffentlicheUrl": "https://os.example.org",
  "agent": { "name": "Agent" },
  "extern": [{ "slug": "git", "titel": "Git", "url": "https://git.example.org/" }]
}
```

- `name`: name in the menu, Start and page title (overrides `PUBLIC_FYOS_NAME`).
- `oeffentlicheUrl`: an additional origin whose links open in the OS (behind a proxy).
- `agent.name`: display name of the agent (dock, window header, room "Conversation").
- `extern`: services with an interface of their own; they open in a new tab (only `http`/`https`).

The image contains an empty default file `{}` at `/etc/fyos/fyos.config.json`; if you want your own values, mount a
file there.

## Notices and questions to the agent

A source (for example the agent) shows a notice at the top right with a window event; a click opens the surface. At
most three are stacked; identical ones within a minute replace each other; "muted" and "off" can be undone.

```js
window.dispatchEvent(new CustomEvent('fyos:zeigt', {
  detail: { ziel: 'app:notizen__liste', titel: 'Notes', untertitel: 'Today', vorschau: 'Three new entries.', eingabe: { tag: 'heute' } },
}));
```

Asking the agent (from apps, pages and objects): `fyos:agent-fragen` with `detail: { text, kontext, quelle }` on the
window, from a page in a window by `postMessage({ fyosAgentFragen: { … } })`. The shell opens the agent dock (native
agent app against the runner) with the question and its context as a draft in the input field; Enter sends it.

Opening surfaces: `fyos:oeffnen` with `detail: { ziel, eingabe }` (`ziel` is a surface or a path); the shell calls
`preventDefault()` when it takes over.

## Developing and testing

```
npm install
npm run dev          # http://localhost:4321/os/
npx vitest run       # unit tests (jsdom)
npx astro build      # static pages into dist/
```

For `npm run dev` the development proxy forwards to running services if set:

```
FYOS_DEV_HUB=http://localhost:8080 FYOS_DEV_RUNNER=http://localhost:18438 FYOS_DEV_RUNNER_TOKEN=… npm run dev
```

It behaves like the delivery: `/hub-api/*` becomes `/hub/*`, `/api/agent/*` goes to the runner without the prefix and
with the token as `Authorization: Bearer` (only with `X-FYOS-Agent: 1`).

Type check of the sources: `npx tsc --noEmit -p .` (the tests are excluded).

## Image

```
docker build -t fyos-web .
docker run -p 8080:8080 -e FYOS_HUB_UPSTREAM=http://hub:8080 -e FYOS_AGENT_UPSTREAM=http://agent:18438 -e FYOS_AGENT_TOKEN=… fyos-web
```

Health: `GET /healthz`.

## Notes

- The host name the shell introduces itself with to hub apps (`fyos-web`) is deliberately unchanged; apps check it.
- The shell calls the Hub tools `shell.plaetze`, `shell.platz_speichern`, `shell.platz_entfernen`, `shell.abholen`,
  `shell.merken` and `shell.zustand` on a best-effort basis (templates, reporting the layout, picking up the agent's
  commands). If the Hub does not answer, the shell carries on without them.
