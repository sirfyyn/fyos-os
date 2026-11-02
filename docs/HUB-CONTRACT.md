# Hub contract

What the Hub (`hub/`, package `mcp_hub`) promises to the outside: HTTP routes, formats, plugin interface. The shell
(`web/`) and your own plugin packages build on it. The Hub listens on **port 8080**.

## 1. Routes at a glance

| Route | Method | Purpose |
|---|---|---|
| `/mcp` | MCP (Streamable HTTP) | Agents, chat clients; path from `path` in the configuration |
| `/health` | GET | Liveness for the container check |
| `/metrics` | GET | Metrics as Prometheus text (core, `metrics()` and `zeitplan()` of the plugins, for schedules with limits also `fyos_zeitplan_laeufe_heute`, `fyos_zeitplan_max_pro_tag` and `fyos_zeitplan_uebersprungen_total{takt, grund}`); open inside, 404 from outside |
| `/hub/search?query=&limit=&voll=` | GET | Search tools (like `hub__search_tools`) |
| `/hub/map` | GET | Tool map: domains, tools, scope, short text |
| `/hub/health` | GET | State per plugin |
| `/hub/servers` | GET | Loaded plugins with their tool count |
| `/hub/call` | POST | Call any tool (inside only, never to the outside) |
| `/hub/mehr` | POST | Drill into a shortened result (`ergebnis_id`, `pfad`, `felder`, `filter`, `suche`, `limit`, `cursor`) |
| `/hub/apps` | GET | Surface tools for the shell (with ETag); next to `apps` and `count`, the register of draggable things (`dinge`) and their handovers (`uebergaben`, EXTENDING.md §3.7) |
| `/hub/resource?uri=ui://…` | GET | A plugin's interface (with ETag) |
| `/hub/app-call` | POST | Call a surface tool (the browser's route) |
| `/hub/gui/<id>` | GET | A built view (plugin `gui`) as a whole, standalone page for surfaces without an MCP Apps host; read-only, also through the shell; invalid or unknown id: 404 |
| `/hub/gui/<id>/daten` | GET | Fresh data from this view's live source (JSON as with `/hub/call`); read-only, also through the shell |
| `/hub/os/strom?sitzung=&geraet=&nach=` | GET | OS bridge: commands as server-sent events |
| `/hub/os/melden` | POST | OS bridge: report the session's state |
| `/hub/os/antwort` | POST | OS bridge: answer to a command |
| `/hub/dateien/datei?pfad=` | GET, PUT | File store (plugin `dateien`): download or show a file (GET, `laden=1` forces a download) and upload one (PUT, the body is the content, `ueberschreiben=1` replaces an existing file); section "Downloading and uploading files" below |
| `/hub/agent/eingang` | GET, POST | Agent inbox (plugin `agent`): sources drop events in (POST), the runner reads by long poll (GET `?nach=&warte=&anzahl=&agent=`); section "Agent runner" below |
| `/hub/agent/melden` | POST | Agent outbox: the runner reports its session in batches into the stream `fyos:agent` |
| `/hub/agent/alarm` | POST | Alertmanager webhook (v4) as debounced alarms into the agent inbox |
| `/hub/<own route>` | per plugin | Routes from plugins (`routen()`, section 4), after those of the core; for example `/hub/agent/eingang` (plugin `agent`) |

### The shell's nginx

The browser talks only to the shell. It passes through exactly these routes; under `/hub-api` it removes the prefix,
the built views keep their path:

```
/hub-api/apps          -> http://hub:8080/hub/apps
/hub-api/resource      -> http://hub:8080/hub/resource
/hub-api/app-call      -> http://hub:8080/hub/app-call
/hub-api/os/strom      -> http://hub:8080/hub/os/strom     (proxy_buffering off, proxy_read_timeout >= 700s, HTTP/1.1)
/hub-api/os/melden     -> http://hub:8080/hub/os/melden
/hub-api/os/antwort    -> http://hub:8080/hub/os/antwort
/hub-api/dateien/datei -> http://hub:8080/hub/dateien/datei    (GET and PUT only, proxy_request_buffering off, the Hub limits the size)
/hub/gui/<id>          -> http://hub:8080/hub/gui/<id>         (GET only; id g- plus 12 hex characters)
/hub/gui/<id>/daten    -> http://hub:8080/hub/gui/<id>/daten
```

`/hub/call`, `/hub/mehr`, `/hub/search`, `/hub/map`, `/hub/health`, `/hub/servers`, `/metrics` and `/mcp` do **not**
belong on the browser route: behind `/hub/call` are all tools. The answer of `/hub/os/strom` sets
`X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`; the proxy must not buffer anything.

Since 0.1.1 the built views go through the shell, so that a view link in the browser or in the panel of a development
environment (mod `fyos-ansicht`) opens behind the same login as the shell. The path stays, because the page loads its
data from `/hub/gui/<id>/daten`. The shell rewrites every matching request to exactly one of the two forms (without a
query part) before passing it on; no other route under `/hub/` can be reached through it, not even with `..` or percent
encoding in the path. This opens no new access: `gui.zeigen` already delivers the same data through
`/hub-api/app-call`. The generated script runs in an iframe with `sandbox="allow-scripts"` (without same-origin) and its
own CSP, and reaches neither the shell nor the network.

## 2. Call and answer

`POST /hub/call {"tool": "<plugin>.<tool>", "arguments": {…}, "ansicht": "kurz"}` and
`POST /hub/app-call {"tool": "<plugin>.<tool>" | "name": "<plugin>__<tool>", "arguments": {…}}`.

Answer (JSON): `{"ok": true, "result": …}` or `{"ok": false, "error": "…", "kind": "…"}`. An app tool with an
interface also carries the link "Open in FYOS" in its result.

`/hub/app-call` accepts only tools with `meta.ui` or the tag `flaeche`; every other tool answers 403 `not_an_app`. A
tool with `meta.ui.visibility == ["app"]` is for interfaces only: `/hub/call` and `/mcp` reject it with 403
`nur_oberflaeche`.

### Status codes

| `kind` | HTTP |
|---|---|
| (ok) | 200 |
| `bad_arguments`, `bad_request` | 400 |
| `forbidden`, `verboten`, `nur_oberflaeche`, `not_an_app` | 403 |
| `not_found` | 404 |
| `circuit_open` | 503 |
| `timeout` | 504 |
| everything else (plugin raised, tool reports `ok=false`) | 502 |

Also: 400 for broken JSON or when the body is not an object, 413 for a report that is too large, 415 for the wrong
content type, 503 `not_initialized` while the Hub is starting.

### Origin and content type

- Writing methods under `/hub/` answer 403 when `Sec-Fetch-Site: cross-site` is set or an `Origin` is present whose
  host is not allowed. Requests without `Origin` (scripts, agents) stay allowed.
- Allowed hosts: `FYOS_ERLAUBTE_HOSTS` (comma-separated), the host of `FYOS_OEFFENTLICH_URL`, always `localhost` and
  `127.0.0.1`. The port does not count. The `Host` header does not count.
- `/hub/call`, `/hub/mehr`, `/hub/app-call`, `/hub/os/melden`, `/hub/os/antwort` require
  `Content-Type: application/json` (otherwise 415).

### Downloading and uploading files

Besides its tools, the plugin `dateien` has a route of its own for the content of files (tool answers are JSON and the
wrong carrier for large or binary content). It lives in the plugin's `routen()` and applies only when `FYOS_DATEIEN`
points to a folder (otherwise 501 `nicht_eingerichtet`).

- `GET /hub/dateien/datei?pfad=<path>[&laden=1]` delivers the file. The path is relative to the store, separated by
  `/`; `..`, links and the management folder `.fyos` do not get through (400), a missing file is 404. Because the files
  are foreign content and come from the shell's origin, the browser only displays what cannot execute anything: images
  (with `Content-Security-Policy: sandbox`), PDF, audio, video and text (always as `text/plain`). Everything else,
  HTML included, comes as an attachment (`Content-Disposition: attachment`, `application/octet-stream`); every answer
  carries `X-Content-Type-Options: nosniff`. `laden=1` forces the attachment.
- `PUT /hub/dateien/datei?pfad=<path>[&ueberschreiben=1]` creates the file; the body is the content (any content type,
  not JSON). Missing folders are created along the way. An existing file is replaced only with `ueberschreiben=1`
  (otherwise 409 `existiert`); the old version is kept as an earlier version. Too large (`FYOS_DATEIEN_MAX_MB`,
  default 25) is 413 `zu_gross`; the Hub stops reading the body as soon as it gets too big. The answer is
  `{"ok": true, "result": {pfad, groesse, ersetzt, version_gesichert, url}}`.

Neither route goes through the tool registry: they do not appear in the tool audit, and there is no dry run. The
tools' protection is replaced by the origin protection (writing like `POST`: no foreign `Origin`, no
`Sec-Fetch-Site: cross-site`; a `PUT` with `application/octet-stream` from foreign pages also triggers a preflight
that the Hub never answers) and by the login in front of the shell. An app in the sandbox iframe has the origin `null`
and therefore may not upload itself; the shell takes the file by the message `fyos/datei-hochladen` and sends it from
its own origin (`App.hochladen` in the bridge, only for the app "Files"). The Hub is built for **one** process per
store (versions and trash are not meant for two concurrent writers).

### ETag

`/hub/apps` and `/hub/resource` send `ETag` and `Cache-Control: private, no-cache`; `If-None-Match` leads to 304.

### Callers

The Hub records who is calling: `X-Hub-Caller` wins; otherwise `/hub/app-call|apps|resource` = `fyos-web` (the
shell), other `/hub/*` = `rest:<User-Agent product>`, `/mcp` = `mcp:<product>`; after login `oauth:<audience>`.

## 3. OS bridge, wire protocol v1

An agent sees and controls the open shell. State lives in Redis (`REDIS_URL`).

**`GET /hub/os/strom?sitzung=<id>&geraet=<name>[&nach=<stream-id>]`**, the header `Last-Event-ID` takes precedence.
`text/event-stream`. First line `retry: 3000`, then `event: hallo` (`{"sitzung", "ablauf_s": 90, "bekannt": bool}`;
`bekannt: false` means `melden` right away). Then `event: befehl` with `id:` = stream id, `data:` = the command as
JSON. Every 15 s `: ping`. After 10 min the stream ends cleanly; the browser reconnects with `Last-Event-ID` and loses
nothing. Redis failure: `event: abbruch` `{"grund": "redis"}`.

**`POST /hub/os/melden`** `{sitzung, geraet, art, seite, sichtbar, aktiv_vor_s, anruf, agent_vorne, bildschirm,
bildschirme[], fenster[], flaechen[], werkzeuge[], audio?, version: 1, gesendet}` answers
`{ok: true, ablauf_s: 90, sitzungen: n}`; every 30 s and on changes. `{sitzung, ende: true, gesendet}` ends the
session. Sessions without a stream report `abholen: true` (+ `nach`) and get commands in the answer.

**`POST /hub/os/antwort`** `{sitzung, befehl, ok, ergebnis?, fehler?}` answers `{ok: true}`. Only the session the
command went to may answer (otherwise 400).

Commands (`data` of `event: befehl`):

```
{"id": "b-…", "art": "zeigen",     "ziel": "app:<plugin>__<werkzeug>", "eingabe": {…}|null, "von": "agent"}
{"id": "b-…", "art": "ausfuehren", "werkzeug": "<name>", "argumente": {…}, "von": "agent"}
{"id": "b-…", "art": "zeigt",      "zeigt": {ziel, app, titel, untertitel, symbol, ton, vorschau, eingabe, link,
                                               audio: {modus, klang, sprechen}, [art: "mitteilung", dringlichkeit],
                                               [nachgeholt: true, entstanden: <Unix seconds>]},
                                    "von": "agent"}              (no answer)
```

**Queuing.** `os.mitteilen` delivers when someone sits in front of an open shell (visible, used in the last 10 min).
Otherwise it answers `{"zugestellt": false, "vorgemerkt": true, "rueckfall": "vorgemerkt"}` and puts the notice into
the Redis list `fyos:os:ausstehend` (at most 20 entries, 24 h lifetime). The next report (`POST /hub/os/melden`) or
connection (`GET /hub/os/strom`) of a session someone is sitting in front of delivers it: oldest first, each exactly
once (atomic removal, also with several Hub replicas and devices), as `zeigt` with `nachgeholt: true` and `entstanden`,
without a chime and without reading aloud. Whatever is older than 24 h at delivery is dropped. `OS_NACHHOLEN=aus` (or
the plugin config `nachholen: false`) turns queuing off; `os.mitteilen` then answers `rueckfall: "kanal"` again. Flow
and operation: [`NIGHT-WORK.md`](NIGHT-WORK.md).

Surface ids: `agent`, `seite:<name>`, `app:<plugin>__<tool>`, `nativ:<name>`. Caller names that count as the agent are
in `OS_AGENT_AUFRUFER` (comma-separated, `name*` = prefix; default `agent*`); `OS_AGENT_ZEIGT=aus` turns off
"agent shows".

## 4. Plugin interface

A plugin is a class `mcp_hub.plugin.HubPlugin`:

| Method | Required | Purpose |
|---|---|---|
| `register()` | yes | once at startup: connections, credentials |
| `init()` | no | extended setup after `register` |
| `describe_tools()` | yes | list of `ToolDescriptor` |
| `describe_resources()` | no | list of `ResourceDescriptor` (`ui://` interfaces) |
| `call(method, args)` | yes | runs the tool `method`; the return value must be JSON-serialisable |
| `health()` | no | `{"ok": bool, …}` |
| `routen()` | no | own HTTP routes (Starlette `Route`) for things that should not be a tool, for example a client's telemetry |
| `registry_anbinden(registry)` | no | once after all plugins have loaded: the registry (other plugins, `on_call_hooks` for audit and bus) |
| `oeffnen_ziel(werkzeug, args)` | no | redirects a tool's "Open in FYOS" link: `("<plugin>.<tool>", arguments)` of the tool that shows the state, otherwise `None`. Needed when the input does not fit into a link (more than 4000 characters of JSON); `gui.bauen` points to `gui.zeigen {id}` this way. The target must itself be read-only and visible to the model; on any error the link stays on the tool itself |
| `metrics()` | no | metrics for `/metrics`: numbers on the top and next level as `fyos_plugin_wert{plugin, schluessel}`, own series under `"_proben"` (`[{name, wert, labels?, typ? gauge\|counter, hilfe?}]`, names without `fyos_` get `fyos_<plugin>_`); cached for 30 s, so no expensive queries |
| `zeitplan()` | no | recurring jobs for `mcp.zeitplan` and `/metrics` (`fyos_zeitplan_*`): `[{id, name, takt, beschreibung?, an?, naechster?, letzter?, letzter_status? ok\|fehler, letzter_fehler?, quelle?, max_pro_tag?, fenster?, ruht?, laeufe_heute?, uebersprungen?, protokoll?}]`, times in Unix seconds, from memory; the last six fields come from the guard `mcp_hub.takt` for schedules with a daily limit and time window (`EXTENDING.md` §2.12) |
| `skills_beitrag()` | no | skills for `skills.suchen`/`skills.lesen`: `[{name, beschreibung, text \| lesen, quelle?, ausloeser?}]`; file sources win on equal names |
| `shutdown()` | no | clean up |

Routes from `routen()` must live under `/hub/` so that origin and login protection apply (sections 2 and 5). The core
mounts them after its own and rejects a route that is already taken, with a warning in the log; if `routen()` fails,
only this plugin's routes are missing. A route appears neither in `hub__map` nor in the tool audit.

Class attributes: `name`, `description`, `version`, `argumente_vertraulich` (`True`: arguments appear on the event bus
only as `{"redacted": true}`, regardless of `event_bus_publisher.skip_arg_publish`).

`ToolDescriptor`: `name`, `description`, `input_schema`, `tags`, `meta`, `title`, `zeitlimit_s`. The tool id is
`<plugin>.<name>`. Tags: exactly one of `read`, `write`, `destructive`, `exec` (scope), `extern` for calls to the
outside; `flaeche` allows the call through `/hub/app-call`. `meta.ui.resourceUri` connects the tool to an interface,
`meta.ui.visibility = ["app"]` makes it visible only to the interface, `meta.app` carries the identity (`titel`,
`untertitel`, `symbol`, `ton`, `kategorie`), `meta.kurz` a one-liner for the short view.
`ResourceDescriptor`: `uri`, `name`, `read` (returns HTML), `description`, `mime_type`
(`text/html;profile=mcp-app`), `meta`.

### Registering

1. **Entry point** in the plugin's package (the Hub loads it without configuration):

   ```
   [project.entry-points."mcp_hub.plugins"]
   meins = "mein_paket.plugin:MeinPlugin"
   ```

2. **Configuration** in `config.yaml`: an entry with `name` and optionally `config`, `secrets`, `enabled`. Without
   `module`, the entry point of the same name applies; with `module` (+ `class`) the module is imported directly.
   `enabled: false` also turns off a plugin installed by entry point. A class with a `config` parameter receives the
   plugin configuration in its constructor.

A plugin that fails to load does not take the Hub down with it; `/hub/health` names the reason.

### Interface

`_oberflaeche.oberflaeche(datei, ui_verzeichnis)` reads the HTML file from a path or from `<package>/ui/` (package
name as text). Placeholders for style, bridge and the app's header are filled in.
`_identitaet.registriere_app(schluessel, eintrag, datei=, hauptwerkzeug=, art=)` registers title, symbol, colour tone
and category (`System`, `Betrieb`, `Wissen`, `Beispiele`); the shell then shows the app in the dock and the tiles.
`art` is `"widget"` (default, a tile in the grid) or `"anwendung"` (opens large, can be maximised, its own full-screen
screen); it appears as `art` in `meta["app"]` and at the top of every app in `GET /hub/apps`. More in `EXTENDING.md`
§3.5.

## 5. Login

Optional. Without `FYOS_OIDC_ISSUER` the Hub is open inside and answers requests from outside (header
`X-FYOS-Zugang: extern` or a host from `FYOS_OIDC_HOSTS`) to `/mcp` with 403. With an issuer, `/mcp` requires a bearer
token (JWT, RS256/ES256/EdDSA, keys by discovery) for requests from outside; without a token 401 with
`WWW-Authenticate: Bearer … resource_metadata="<url>/.well-known/oauth-protected-resource/mcp"`, keys not loadable
503. Variables: `FYOS_OIDC_ISSUER`, `FYOS_OIDC_CLIENTS`, `FYOS_OIDC_MODUS` (`aus|an|streng`), `FYOS_OIDC_HOSTS`,
`FYOS_OIDC_REST` (default `/hub/app-call`, never `/hub/call`), `FYOS_OIDC_BENUTZER` (default `*`), `FYOS_OIDC_SCOPES`,
`FYOS_OIDC_JWKS_URL`, `FYOS_OIDC_LEEWAY_S`. The `Authorization` header is not passed on.

## 6. Tasks (MCP Tasks)

Long-running tools return an id at once instead of the result (extension `io.modelcontextprotocol/tasks`, SEP-2663,
schema 2026-07-28). Code: `hub/mcp_hub/aufgaben.py` (storage, permissions, limits), `aufgaben_mcp.py` (extension on
the SDK), `server.py` (REST).

- **Routes.** MCP 2026-07-28 (`/mcp`, only with `mcp` 2.x): `tasks/get|update|cancel`; `server/discover` announces the
  extension. REST: `POST /hub/call` with `"aufgabe": true` (or the extension's `_meta` envelope) answers `202` with
  `{ok, resultType: "task", taskId, status, ttlMs, pollIntervalMs, …}`; `POST /hub/aufgaben/get|update|cancel`
  `{taskId, inputResponses?}` and `GET /hub/aufgaben/liste`. The handshake era (2024-11-05 to 2025-11-25) stays
  synchronous.
- **Never unasked.** A task exists only when the client has declared the extension **and** the tool allows it:
  `ToolDescriptor(aufgabe=True)`. No bundled plugin sets the hint; plugins with `aufgabe=True` need a Hub that carries
  this version. `__dry_run__` calls, the interface lock and missing required arguments stay synchronous.
  `hub__schema` and the search show `aufgabe: true`.
- **States.** `working`, `input_required`, `completed`, `failed`, `cancelled`; the last three are final. A tool result
  `{"ok": false}` is a normal result (`completed`), as it is synchronously; `failed` is for errors of the Hub
  (exception in the thread, pod restart, input deadline of 15 minutes).
- **Permissions.** Only the actor (`AUFRUFER`) who created the task may read, change or cancel it; foreign and unknown
  ids answer the same way (-32602, REST 404). Id: 24 characters from the random generator.
- **Limits.** Open tasks: 5 per actor, 20 in the Hub (otherwise -32000, REST 429); `ttlMs` at most 24 h (default 1 h).
- **State.** Through the same store as `ergebnis_id` (`ansicht.Ablage`: Redis, otherwise the pod's memory). If the pod
  loses the thread, `get` reports `failed` ("Hub restarted, task lost").
- **Cancelling is cooperative.** `cancel` sets `cancelled` at once; the tool runs to the end, and its result is
  discarded. Plugins ask `mcp_hub.aufgaben.aktuelle().abgebrochen()` and request input with
  `.eingabe(schluessel, anfrage)`.
- **Not built.** `notifications/tasks` and `subscriptions/listen`; polling at the pace of `pollIntervalMs` is the normal
  way.

## Agent runner (plugin `agent`)

An agent runner (a model agent in RPC mode, for example as a system service) needs no access to Redis: it reads its
inbox `fyos:agent:eingang` by long poll through `GET /hub/agent/eingang` and reports through `POST /hub/agent/melden`
into the outbox `fyos:agent`, which interfaces and bridges read. Sources (web chat, Matrix, ticket system, schedule,
observations) drop events in through `POST /hub/agent/eingang`, Alertmanager through `POST /hub/agent/alarm` (severity
→ `schwere`, repetitions debounced, "resolved" only for what was dropped in). The contracts are in
`hub/mcp_hub/plugins/_agenteneingang.py`, `_agentenstrom.py` and `_agentenalarm.py`.

Event kinds of the outbox: `part.updated`, `part.done`, `plan.update`, `proposal`, `ui_request`, `usage`,
`session.idle`, `error` and `ruhe`. `ruhe` reports a runner's quiet switch (required: `an`, `pausiert` as
`"1"`/`"0"`; optional `stufe` `normal|tief`, `quelle`, `grund`, `bis`, `von`). A Hub from before this kind rejects the
whole batch with 400 if it contains a `ruhe`; a runner therefore reports the kind only once its Hub knows it.

All routes require `application/json` (otherwise 415). Without source tokens they are open inside, like the rest of
the Hub. With `FYOS_AGENT_TOKENS` (`role=token`, separated by commas or line breaks; the roles are the inbox sources
and `runner`) every route requires a token (`Authorization: Bearer …` or `X-Agent-Token`), and the source of a dropped
event follows the token, not the body. `runner` may read and report, `alarm` may use the alarm route, every other
source may only drop events in. `FYOS_AGENT_STRENG=1` closes everything as long as there is no usable token. Do not put
the shared Hub key on `/hub/agent`: it removes `Authorization`, and the source tokens would never arrive.

## Tickets and ITSM (plugin `itsm`)

Tickets come from one source for all plugins, `mcp_hub.vorgaenge.quelle()` (EXTENDING.md §2.13): a ticket service
(`FYOS_VORGAENGE_URL`, ticket contract `/tickets…`) or a store in the Hub. Since 0.3.0 the core ships the store: the
plugin `itsm` keeps tickets in the Hub's Redis and registers with `vorgaenge.ablage_anmelden`. With a ticket service
configured, the same tools pass through to the service instead (it takes precedence; Redis is then not needed). Without
either it is "not set up". There is exactly one plugin `itsm` in a Hub; a package that brings its own ticket service
registers the service via `FYOS_VORGAENGE_URL`, not a second `itsm`. Guide: [ITSM.md](ITSM.md).

**Ticket.** Id `<kind>-<number>` (`INC` incident, `CHG` change, `VOR` project; one number sequence for all). Status
`new triage in_progress waiting_approval resolved closed`. An approval is `waiting_approval`; `→ in_progress` means
approved, `→ triage` rejected. Only the owner sets or leaves `closed`. `expected_status` when writing: if it no longer
matches, that is a conflict (the first answer wins).

**Actors.** Answers from the interface (`/hub/app-call`) are recorded under the owner (`FYOS_BESITZER_AKTEUR`, default
`besitzer`), everything else under `wer` or the agent (`FYOS_AGENT_ID`, else the first name in `FYOS_AGENTEN`, default
`agent`). A tool call cannot claim to be the owner; `itsm.freigeben`, `itsm.ablehnen` and `itsm.status` can only be used
through the interface.

**Fields the runner relies on** (fyos-agent, ITSM watch):

| Tool | Answer |
|---|---|
| `itsm.vorgang {id, verlauf?}` | `id`, `titel`, `status`, `art`, `prioritaet`, `wartet_auf`, `zustaendig`, `melder`, `beschreibung`, `erstellt`, `aktualisiert`, `antwort` (`freigabe`\|null), `folge_status`, `verlauf` newest first as `{ts, ereignis, wer, text}` with `ereignis` `created`\|`comment`\|`updated`; a status change appears in `text` as `status old→new` (for example `status waiting_approval→in_progress`); `ts` is ISO 8601 in UTC with microseconds, strictly increasing |
| `itsm.wartend {}` | `ts`, `besitzer`, `anzahl`, `tickets` (open approvals and tickets with `wartet_auf` = owner, oldest first: `id`, `titel`, `art`, `typ`, `status`, `prioritaet`, `worauf`, `zustaendig`, `alter_tage`, `wartet_seit`, `aktualisiert`, `beschreibung`), `andere_wartende` |

With a ticket service the answers carry the same fields plus what only a service knows: `schwere` (severity),
`wiedervorlage`, `archiviert`, `warnungen`; `itsm.wartend` sorts by severity and age and adds `art` (`waiting` from
`GET /waiting`, else `freigaben`) and is cached for 20 s.

Writing tools carry the tag `write` and show the plan with `__dry_run__: true`. On the store, `anlegen`,
`kommentieren`, `status_setzen`, `freigeben` and `ablehnen` write only with `bestaetigt: true`; with a ticket service
only `freigeben` and `ablehnen` need it. `notiz` (append a note as the agent) and `freigabe_beantragen` (the agent asks
for approval on its own ticket: `waiting_approval`, waiting for the owner, the request with checksum first in the
description as `## Freigabe angefragt (Prüfsumme <hex>)` and as a comment) never need it. `itsm.status` (owner, status
button) has its own dry run: without `ausfuehren: true` it only shows from, to and effect. Keys in Redis:
`fyos:itsm:nr`, `fyos:itsm:alle` (sorted set), `fyos:itsm:v:<id>` (hash), `fyos:itsm:verlauf:<id>` (list, at most 1000
entries).
