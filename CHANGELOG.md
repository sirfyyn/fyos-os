# Changelog

All notable changes to FYOS are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the versions follow
[Semantic Versioning](https://semver.org/). The numbers in brackets are the pull request numbers.

A version applies to the whole package: interface (`web`), Hub (`fyos-hub`) and installer (`fyos-install`) carry the
same number. The agent (from 0.2.0 the runner, before that OpenClaw with the FYOS plugins) comes from the sister repo
`fyos-agent` and is published with the same tag; its changes are in its own `CHANGELOG.md`.

Up to 0.2.1 this changelog was written in German; the entries below are translated. Identifiers (tool names, keys,
environment variables) are unchanged; [`docs/GLOSSARY.md`](docs/GLOSSARY.md) explains the German ones.

## [Unreleased]

## [0.3.0] – 2026-11-02

### Added
- **ITSM: confirmation is a setting.** `bestaetigung` in the hub configuration decides, for all writing tools or per tool,
  whether a real run needs `bestaetigt: true`. See `docs/ITSM.md`.
- **ITSM in the core (Hub plugin `itsm`).** Tickets with a kind (`INC` incident, `CHG` change, `VOR` project), title,
  text, status (`new triage in_progress waiting_approval resolved closed`), priority, assignee, comments, history (who,
  when, what) and approvals (`waiting_approval → in_progress` approved, `→ triage` rejected), in the Hub's Redis
  (`fyos:itsm:*`). The plugin registers as the store for tickets; without Redis and without a ticket service it is
  "not set up", and a configured ticket service takes precedence. Tools: `itsm.liste`, `itsm.vorgang`, `itsm.wartend` (reading), `itsm.anlegen`,
  `itsm.kommentieren`, `itsm.status_setzen` (plan with `__dry_run__`, real with `bestaetigt: true`), `itsm.freigeben`,
  `itsm.ablehnen` (interface only, as the owner). `itsm.vorgang` and `itsm.wartend` deliver the fields the runner's
  ITSM watch reads. Guide: docs/ITSM.md, contract: docs/HUB-CONTRACT.md.
- **ITSM passes through to a ticket service.** With `FYOS_VORGAENGE_URL` set, the plugin `itsm` no longer rests: its
  tools pass through to the service (`/tickets…`, plus `/history` and `/waiting` when the service has them), without
  Redis. New tools on both paths: `itsm.notiz` (the agent appends a note), `itsm.freigabe_beantragen` (the agent asks
  for approval of one step on its own ticket, with checksum, optionally `risiko`, `zerstoererisch`, `kontext`) and
  `itsm.status` (the owner sets a status by button, dry run first; interface only). `itsm.anlegen` also takes
  `schwere`, `fingerprint` and `verweise`; ticket ids may be other kinds (`PRB`) and work cards (`WB-…`). With a
  service, `anlegen`, `kommentieren` and `status_setzen` write without `bestaetigt`. This covers the tools of the
  control room's own `itsm` plugin with the same names, so a Hub has exactly one `itsm` (docs/ITSM.md).
- **App "Tickets":** shows kind, assignee and what a ticket is waiting for, sets the status by button
  (`vorgaenge.status`) and answers approvals with "Approve" and "Reject" (`vorgaenge.entscheiden`), each only after a
  plan and "Yes".
- **Installer:** `itsm` belongs to the building block core and is on; `agent-runner.json` carries `itsm.besitzer` and
  `itsm.agent` matching the Hub.

### Changed
- Comments and new tickets from the app "Tickets" are recorded under the owner's actor (`FYOS_BESITZER_AKTEUR`, default
  `besitzer`, new `vorgaenge.besitzer_akteur()`) instead of `shell`; that is how the agent recognises them.
- **Light mode follows the device.** Without a saved choice the colour scheme is now "System" (`prefers-color-scheme`)
  instead of always dark, and it switches along when the device does; Settings → Appearance, the control center and
  the menu bar offer Light, Dark and System. The menu bar and control center no longer have their own "Automatic" by
  time of day (a saved `auto` counts as System) and share one place with the settings
  (`lib/einstellungen/farbschema.ts`). Hub apps follow the device as well until the shell reports its scheme.
- **Documentation in English.** README, `docs/`, the READMEs of `hub/`, `installer/` and `web/`, `RELEASE.md`, this
  changelog, the bundled skills and the comments in `deploy/` and the CI workflows are now English. The German README
  remains as `README.de.md`. Renamed: `docs/ARCHITEKTUR.md` → `docs/ARCHITECTURE.md`, `docs/ERWEITERN.md` →
  `docs/EXTENDING.md`, `docs/HUB-VERTRAG.md` → `docs/HUB-CONTRACT.md`, `docs/NACHBAU.md` → `docs/REBUILD.md`,
  `docs/NACHTARBEIT.md` → `docs/NIGHT-WORK.md`; `README.en.md` is now `README.md`. New: `docs/GLOSSARY.md`.
- **The rest of the distribution in English, German selectable.** Texts from the interface's program logic (agent
  history, live bar, notifications, OS bridge and page tools, hub apps in their frame) go through `tr()`; the hub apps
  Files, Desktop, Built view, MCP, Mail, Appointments, Workshop and the example app are bilingual like Tickets (the
  bridge translates fixed texts of `zustand`, `satz`, buttons and confirmations, and the app header takes `titel_en` and
  `untertitel_en` from the app identity). Tool descriptions of the core plugins, `hub/config.example.yaml`, the texts of
  the `gui` templates, the comments in the files the installer generates, the catalog schema errors and the maturity
  table in `installer/README.md` are English. Tool names, keys, field names and environment variables are unchanged.
- **Last German leftovers in the English interface translated.** Apps page (Back, By room, A–Z, Recent, New screen,
  Save, the search error lines), the "here" mark in screen menus, Yes/Cancel of search actions, Clear and Settings in
  the notification history, the Do-not-disturb time window, "reversible", "writing …" and a few reload buttons. A new
  test (`web/tests/unit/i18n-englisch-reste.test.tsx`) renders the shell in English, opens the Apps page, menus,
  submenus and context menus, and fails on umlauts or typical German words. The ⌥⌘D dock focus no longer depends on
  the German label of the bottom bar.

### Fixed
- **The agent app shows the agent's name.** Its header, input and history said "Main", the runner's agent ID
  (`agent: "main"` in `agent-runner.json`), instead of the name from the setup. They now use the name from
  `fyos.config.json` (`agent.name`); the ID only appears as a tooltip. The installer writes the persona's agent name
  into `fyos.config.json` for Compose and Kubernetes.
- **Flaky shell test.** `os-shell.test.tsx` failed now and then in CI with "Unable to find role=button name
  /Notizen/": the Apps page is loaded lazily, and the first test that opened it also paid for Vite transforming the
  module, which on a busy runner took longer than the one-second `findBy` window. The shell tests now load the lazy
  parts once in `beforeAll` (`web/tests/unit/shell-vorladen.ts`).

### Note
- Released together with fyos-agent 0.3.0 (the runner speaks English by default; approvals follow `itsm.besitzer`).

## [0.2.1] – 2026-11-02

### Removed
- **OpenClaw entirely.** The runner from `fyos-agent` replaces the old agent completely; there is no image
  `fyos-agent/openclaw` in the distribution any more, no fallback and no choice.
- **Chat channels through OpenClaw.** The installer building blocks Telegram, WhatsApp and Matrix
  (katalog_kanaele.yaml, kanaele.py), the derived agent image (agent/Dockerfile, `agent_bild_k8s`) and the channel
  acceptance check (`--kanaele`) are gone. The runner sets up Matrix as a route for approval messages itself
  (`pi_durable.freigabe_meldung.kanaele` in `agent-runner.json`).
- **Option `agent`.** `optionen.agent` and the persona file fyos.yaml no longer exist; an old answer is skipped with a
  hint. `bild_agent` now names the runner's image.
- **Route `/agent`.** The interface no longer passes a gateway through: location `/agent`, `FYOS_OPENCLAW_UPSTREAM`,
  the embedded chat (surface "Agent chat", `agentPfad()`, `?draft=`) and `agent.pfad` in `fyos.config.json` are gone.
  Questions to the agent go as a draft into the native agent app; the room "Conversation" shows them too.
- **Hub plugin `openclaw`** with its entry point, tests and the parts only it used (wake-up, memory query, run
  profiles, workboard mirror, service check, sign of life) and the doc KOPPLUNG-OPENCLAW.md. The store for tickets
  stays as a general connection (`vorgaenge.ablage_anmelden`, kind `ablage`). tools/nachtauftrag.py (cron of the old
  agent) is gone; night jobs are runner schedules (`docs/NIGHT-WORK.md`).

### Added
- **Runner on Kubernetes.** `deploy/k8s/base/agent.yaml` is a deployment of the runner (image `fyos-agent/runner`,
  port 18438, service `agent`, ConfigMap `fyos-agent-config` with `agent-runner.json`, Secret `fyos-agent-token`, model
  from `fyos-modell`, state in the volume `agent-zustand` under `/home/node/.fyos`, uid 1000). `web` reaches it through
  `FYOS_AGENT_UPSTREAM=http://agent:18438`. The installer generates the matching overlay.

### Changed
- `deploy/compose` is built like the installer's setup (runner, `agent-runner.json`).
- The installer pulls `fyos-agent/runner` with the tag `v0.2.1`.

## [0.2.0] – 2026-11-02

### Added
- **Interface from the OS rebuild.** An apps page instead of the start dialog, a rooms bar with apps and the agent as
  drop targets, a waiting drawer, messages, a status light, a dock with the open applications. The native agent app
  talks to the runner through `/api/agent` (nginx authenticates with `FYOS_AGENT_TOKEN`; a shell reachable from outside
  needs a login in front of it). It still hides empty rooms.

### Changed
- **The agent is now the runner.** For Docker Compose the installer sets up the runner from `fyos-agent` 0.2.0 (image
  `fyos-agent/runner`, port 18438) instead of OpenClaw: `agent-runner.json` without secrets, token and model from
  `.env` (`FYOS_AGENT_TOKEN`, `FYOS_MODELL_*`). The interface reaches it through `/api/agent`.
- **OpenClaw is deprecated.** It remains with chosen chat channels (Telegram, WhatsApp, Matrix) and with Kubernetes,
  with a hint, and can be chosen with `optionen.agent: openclaw`. Migration: CHANGELOG of `fyos-agent`, section 0.2.0.
- **Interface: new variable `FYOS_OPENCLAW_UPSTREAM`.** `FYOS_AGENT_UPSTREAM` now points to the runner (default
  `http://agent:18438`); the deprecated OpenClaw route `/agent` reads `FYOS_OPENCLAW_UPSTREAM`. Your own Compose and
  Kubernetes files with OpenClaw must rename the variable (the bundled ones are adjusted).

## [0.1.5] – 2026-10-26

### Added
- **MCP Tasks in the Hub.** Long-running tools return an id at once on request (extension
  `io.modelcontextprotocol/tasks`, schema 2026-07-28): `tasks/get|update|cancel` over MCP (with `mcp` 2.x), over REST
  `POST /hub/call` with `"aufgabe": true` (202) and `/hub/aufgaben/*`. Only for clients that declare the extension and
  only for tools with `ToolDescriptor(aufgabe=True)`; no bundled plugin sets the hint, everything stays synchronous as
  before. 5 open tasks per actor, 20 in the Hub; cancelling is cooperative. Details: `docs/HUB-CONTRACT.md`, section 6.
- **Agent stream: event kind `ruhe`.** The outbox `fyos:agent` accepts a runner's quiet switch through
  `POST /hub/agent/melden` (`an`, `pausiert`, `stufe`, `quelle`, `grund`, `bis`, `von`). Wrong levels and booleans are
  rejected with 400. Older Hubs do not know the kind and reject the whole batch; runners report it only once the Hub
  supports it.

## [0.1.4] – 2026-10-22

### Added
- **Hiding rooms.** If you need only some of the rooms, hide the others one by one in the settings under "Rooms and
  dock" ("Hide", "Show all"). Control center and settings always stay; if you hide the open room, you go back to the
  control center.
- **Empty rooms disappear by themselves.** A room for which no plugin in the Hub delivers anything (Home without the
  home plugin, Office without an inbox) is not in the bar and not in the switch with ⌥⌘←/→. When the plugin is added,
  it is back. The switch "Hide empty rooms" is in the same settings; if the Hub cannot be reached, all rooms stay
  visible.
- **A hint with the way to set things up.** Instead of only "Not set up yet." the shell now says that a plugin fills
  this place and points to the plugin template (`fyos-plugin-vorlage` on PyPI) and the guide `docs/EXTENDING.md`.

### Fixed
- **The bridge to the agent was not wired into the shell in 0.1.2 and 0.1.3.** Both releases named it, but the shell
  started only the slim bridge (picking up notices). Now the full bridge is wired in (`Bruecke`): the shell reports its
  situation to the Hub (windows, surfaces, tools), the agent opens and closes surfaces (`os.zeigen`) and calls the page
  tools (`os.ausfuehren`); notices with sound, reading aloud and the "Undo" card run over the same bridge. If you do
  not want it: `localStorage` `fyos:os:bruecke` = `aus`.

## [0.1.3] – 2026-10-22

### Fixed
- "Undo" after closing: the card at the top right did not appear in 0.1.2 because the shell gave the notice list a
  signal of its own instead of the shared card. It now reads the same card as the bridge.

## [0.1.2] – 2026-10-22

### Added

- **Rooms in the shell.** A rooms bar with eight rooms (Conversation, Collection, Studio, Projects, Office, Home,
  Operations, Settings). Every room shows only what the configured plugins deliver through the Hub; without a plugin it
  says "Not set up yet." (#62).
- **Wallpapers, undo, snapping.** A wallpaper of its own per screen, "Undo" after closing a window or screen, snapping
  windows (keys, edge zones with preview), full-screen screen, one screen high instead of endless, and "Straighten
  view" (#62).
- **Handles, capabilities, tools.** Handles in Start (the Hub tool `griffe.liste`), capability switches in the menu
  bar, app tools (`App.werkzeug`) with a shared tool register, sound mode and reading aloud, the bridge to the agent
  with situation and tools (#62).
- **Reading news in FYOS.** `lesen.artikel` and the view template `artikel` (`gui.bauen`) show an article for reading
  in the shell (#58).
- **Remembering wallpapers in the Hub.** The shell's chosen wallpaper follows the user across devices (#57).
- **One view per tile size.** Hub apps and core apps show a view of their own that fits small and large tiles
  (`blick`, `kompakt`, `normal`, `weit`) (#59, #60).
- **Agent runner: workspaces and source `stimme`.** The plugin `agent` reports and reads workspaces and carries a field
  in the inbox; new source `stimme` (voice) (#51, #52).

- **Desktop: a desktop of its own for the agent (`ziel`).** Every tool of the plugin `desktop` takes
  `ziel: mensch|agent`. `agent` is a second, headless desktop of the agent: there it needs no approval, the person
  watches in the app "Desktop" (toggle, live view with JPEG, about three pictures per second; `desktop.bild` takes
  `format` and `qualitaet` for this) and can take over with `desktop.uebernehmen`, and then the agent rests. Window
  addresses there are called `g5`. Also new are the input tools (`klick`, `tippen`, `taste`, `scrollen`); on the
  person's desktop they apply only during an approval that only the person at the machine sets
  (`docs/EXTENDING.md` §2.19).
- **App "Desktop" in the shell (plugin `desktop`).** `desktop.zeigen` opens a surface with the machine's situation,
  open windows and launchers, refreshed every ten seconds, with a screenshot on request. Every open window is a thing of
  the type `desktop-fenster` (id = window address, reading tool `desktop.fenster_lesen`): you can drag it onto another
  app or onto the agent. "To front", "Close" and starting run through plan and "Yes" as everywhere.
- **Agent runner through the Hub (plugin `agent`).** `POST|GET /hub/agent/eingang`, `POST /hub/agent/melden` and
  `POST /hub/agent/alarm` (Alertmanager, debounced) connect an agent runner without Redis access to inbox and outbox.
  Optionally with source tokens (`FYOS_AGENT_TOKENS`): the source follows the token, `FYOS_AGENT_STRENG` closes
  everything without a token (`docs/HUB-CONTRACT.md`, section "Agent runner").
- **Plugin `desktop`: a machine's desktop as tools.** `desktop.lage`, `desktop.fenster`, `desktop.starter` and
  `desktop.bild` (screenshot) read; `desktop.starten`, `desktop.fokus` and `desktop.schliessen` change things and need a
  plan and `bestaetigt: true`. Only what the service on the desktop allows under `starter` is started, never a free
  command; windows are addressed only by the address of an open window. The same counterpart as "Open with"
  (`config: {gegenstelle, token_env}` or `FYOS_OEFFNEN_GEGENSTELLE`/`FYOS_OEFFNEN_TOKEN`); without it "not set up"
  (`docs/EXTENDING.md` §2.19).
- **Files: "Open with".** For a PDF, document or spreadsheet file the preview shows buttons for programs on a machine
  with a screen (Papers, WordCraft, GridCraft on the desktop machine); a click asks first, loads the file there and
  starts the program in a window. New: `dateien.oeffnen_programme` and `dateien.oeffnen_mit`, set up with
  `oeffnen: {gegenstelle, token_env}` on the plugin (`docs/EXTENDING.md` §2.17); without a counterpart everything stays
  as before.
- Hub: `FYOS_AGENT_CA` (path to a CA/certificate file) and `FYOS_AGENT_TLS_PRUEFEN=false` for a gateway with a
  self-signed certificate (config `agent_ca`, `agent_tls_pruefen`); the default stays verifying. Applies to gateway
  calls and the mirrored ticket service.

- **Reloading plugins live.** With `plugins_live: true` and `plugins_live_quellen` (or `FYOS_PLUGINS_LIVE_QUELLEN`)
  changed plugin files from a source replace those in the image: at startup, on every new commit of the source and
  with `POST /hub/plugins/neu-laden`, atomically and without a restart. `/hub/health` shows `live` per plugin
  (`docs/EXTENDING.md` §10.5).
- **Open clients learn about changes to the tool list.** `liste_melden` reports them through `subscriptions/listen`;
  `mcp_sitzungen` offers the same to clients with the old handshake (stateful sessions, only with one Hub replica).
- **Built views in a file store.** With the config `daten` (or `FYOS_GUI_DATEN`) the plugin `gui` stores every view as
  `<daten>/gui/g-….json`, for example on a shared network drive. The file format stayed the same; views already stored
  are kept when switching. Without the setting, `mcp_hub.kv` still applies.
- **Search across everything in ⌘K.** Besides surfaces, the start field also finds tickets, mail, files and notes,
  grouped by source, and says which source was not set up. Plugins register further sources with
  `suche_alles.registriere_quelle` (`docs/EXTENDING.md` §2.18).
- **Work apps "Tickets", "Mail" and "Appointments"** with the first handovers: a mail becomes a ticket (subject,
  excerpt, source), a ticket attaches info with a reference as a comment to another ticket, a ticket becomes an
  appointment. Writing happens only after a plan and confirmation. Without a configured source the apps show "not set
  up".
- **Dragging a note onto the agent** takes its content along as context (shortened, marked as foreign content).
- **State of the repo clone in skills and workshop.** `skills.suchen`/`lesen` and `werkstatt.suchen` name `stand`
  (commit and date of the clone, otherwise `null`); the skill directory rereads on a new commit. Cache lifetime:
  `FYOS_KLONSTAND_TTL_S` (default 60).
- **Installations of your own configure skills and workshop.** Skills: `nur_sichtbar` hides a source's skills from
  the search (they stay readable). Workshop: `orte`, `im_hub`, `env_weg` and `favoriten_schluessel`.

### Changed

- Shell and workshop are denser: more compact spacing in windows, a tighter header and dock, a wider list with a
  one-line purpose (#53, #56).
- App windows first report "taking longer" and show an error only after 30 seconds; the window is ready at the
  handshake instead of at the first height (#54, #55).
- A thing with a registered handover can also be dragged onto the window of its own app.

## [0.1.1] – 2026-10-11

Prepared: the tag `v0.1.1` and the publication follow the steps in [`RELEASE.md`](RELEASE.md).

### Added

- **The installer uses published images.** Without a registry of your own, `fyos-install` pulls the finished images
  from `ghcr.io/sirfyyn` at its own version. You do not have to build anything yourself to try FYOS (#6). <!-- sauber: ok -->
- **Tier per capability.** Tickets, appointments, mailbox, mail and documents come in a basic tier (without a service
  of its own, for example directly against a CalDAV calendar or an IMAP mailbox) and an extended tier (with a service
  of its own). You choose in the assistant, in the text interface or with `--stufe`, or let the default by deployment
  type apply: Docker Compose takes the basic tier, Kubernetes the extended tier (#34).
- **Chat channels in the installer.** Matrix, Telegram and WhatsApp can be chosen when installing. Afterwards the
  acceptance check tests whether every enabled channel really runs. If an access value is missing, FYOS starts anyway,
  and the installer says what is still missing (#21).
- **Building block FYOS Post in the installer catalog.** Sending mail is now part of the selection (#13).
- **Appointments, mailbox and documents in the Hub.** Three new sources for the control room: calendar over CalDAV or
  ICS, reading a mailbox over IMAP, documents from Paperless-ngx or a store. If nothing is set up, it honestly says
  "not set up" instead of showing an empty list (#7, #10, #14).
- **Tickets for plugins.** Plugins access tickets through `mcp_hub.vorgaenge`; a ticket's history also comes from the
  agent's workboard (#3, #4).
- **Files.** A new Hub plugin with the app "Files": a store in a folder, with trash and earlier versions (#20).
- **Built views.** The plugin `gui` builds views from templates (metrics, bars, history, table, flow and more), plus
  the template `diagramm` for diagrams. The mod `fyos-ansicht` opens them in the Claude Code panel (#8, #17).
- **Views in the shell.** The shell passes built views through under `/hub/gui/<id>`, read-only. A link to a view
  opens in the browser and in the panel (#9).
- **Handovers between apps.** Things from one app can be dragged onto another app and dropped (#22).
- **Applications instead of widgets.** Apps open large, can be maximised and fill the whole screen on request (#24).
- **Night work.** Through `os.mitteilen` the agent can queue something for later; the notice waits up to 24 hours and
  appears in the shell in the morning. There is also a night job "sort notes" that reads the notepad in the Hub (#19,
  #25).
- **Urgent notice over the chat channel.** For important things the agent reaches the owner directly over the
  configured channel (#21).
- **Coupling to the agent (OpenClaw).** The Hub accepts the agent's events in a fixed envelope and now knows:
  - waking and ticket sessions: the Hub can wake the agent for a ticket; every session belongs to exactly one ticket
    (#27, #28),
  - run profiles for isolated runs (read, think, report) (#29),
  - a single way to remember (`erinnern`) and the state of the memory (#30),
  - `openclaw.lebt` with heartbeat, sessions and a progress card per ticket (#31),
  - optional services for router, reranker, mouth and ear (`openclaw.dienste`) (#32),
  - an acceptance check on the test server and a table of which behaviour of the original system has been rebuilt
    (#26, #33).
- **Rebuild plan.** `docs/REBUILD.md` (then `docs/NACHBAU.md`) shows per capability how far the rebuild with your own
  accounts and services has come (#11, #12, #15).

### Changed

- Installer 0.1.1 and Hub 0.1.1 carry the package number. The agent image is pulled with the tag `v0.1.1` (before
  `v0.1.0`).
- On Kubernetes the installer takes the extended tier as the default, on Docker Compose the basic tier (#34).
- The Gitea CI also runs daily on a schedule against the newest packages from the index, even without a new commit
  (#16). The secret check (gitleaks) knows a narrowly defined exception for pinned checksums (#18).

### Fixed

- Kubernetes: the Hub deployment with strategy `Recreate` now sets `rollingUpdate` explicitly to null, so that an
  existing deployment can be switched without an error message (#23).
- A configured ticket service now also applies while the coupling to the agent rests (#5).

## [0.1.0] – 2026-10-10

First release of FYOS (For Your Own Sake).

### Added

- **Desktop shell** (`web`, Astro with SolidJS): windows, dock, tiles and menu bar in the browser. It shows apps of the
  Hub plugins without any code of its own and has the agent chat in a window.
- **MCP hub** (`fyos-hub`): MCP at `/mcp`, REST at `/hub/*`, plugins by entry point, login through OIDC, schedules
  with a daily limit and time window, `/metrics`. The coupling to OpenClaw is a plugin of its own.
- **Installer** (`fyos-install`): web assistant, text interface and command line. It explains every building block
  with pictures, generates Docker Compose or Kubernetes and checks after installation at which maturity level each
  layer stands.
- **Agent** (sister repo `fyos-agent`): OpenClaw with behaviour plugins, templates and a contract for approvals.
- **Guide to extending** (`docs/EXTENDING.md`, then `docs/ERWEITERN.md`): plugins, interfaces, skills and agent
  behaviour of your own.
- **Cleanliness check** (`tools/sauber.py`): finds personal data and secrets, also in the Git history
  (`--historie`).

### Changed

- License Apache-2.0, English README, `uv` with your own package index before PyPI (#1).
- GitHub workflows for tests, PyPI publication and images on `ghcr.io` (#2).
