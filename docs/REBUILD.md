# Rebuild: run every capability yourself

FYOS grew out of a private system. The goal of the distribution: anyone who wants to can rebuild every capability of
that system, with their own accounts and their own services and without taking over anything personal. This document
records how far that has come and in which order it continues. It is a plan and is updated with every step.

## The pattern

Every capability consists of a Hub plugin and a **source**. The plugin does not hard-code an address; it asks the source
anew on every call. The source looks in a fixed order:

1. an address: as an argument, registered by a plugin or from the environment (`FYOS_<CAPABILITY>_URL`, plus a header
   line `FYOS_<CAPABILITY>_KOPF` in the format `Name: Value`);
2. a store that a plugin registers (for example an account that a plugin reads directly);
3. otherwise: not set up (`NichtEingerichtet`, HTTP 501) with a hint on how to set it up.

This leads to three states that every interface shows separately: **data** (an empty list included), **error** (service
down or login refused, never disguised as "empty") and **not set up** (neither red nor empty, with the way to set it
up). Defaults exist only for general-purpose things; an empty environment means "not set up", never "some machine on
the network". The model is in [`EXTENDING.md`](EXTENDING.md) §2.13 (`mcp_hub.vorgaenge.quelle()`).

## Basic tier and extended tier

- **Basic tier:** what the agent brings itself (schedules, skills) and what can be connected directly without a service
  of its own (a CalDAV calendar, an IMAP mailbox). Little to run, good for Compose on one machine.
- **Extended tier:** services of their own as in the original system (a ticket service, a calendar and a mailbox
  service, Paperless-ngx, Listmonk …). More to run, in return history, waiting lists, several accounts in one service.
- Both speak the same contract; the choice applies per capability. The plugins, the sources and the docs are the same in
  both tiers and come first.

**Decided:** the tier can be **chosen per capability**, in the assistant and in the text interface with one choice per
capability, without an interface with `--stufe termine=ausbau` or `stufen:` in the answers file. Where it makes sense,
there is also the choice **off**: set up nothing, and the capability then honestly reports "not set up". Without a
choice the **default by deployment type** applies: Kubernetes takes the extended tier, Docker Compose (and "files only")
the basic tier. Where there is no basic tier (sending mail, today also documents), extended and off remain, and the
default is extended.

What the choice does: with the **basic tier** the installer renders no service and sets no service address; the plugin
takes the direct route (CalDAV, IMAP, store in the Hub). With the **extended tier** the service's address is in the
Hub's environment (`FYOS_TERMINE_URL` and so on). The installer renders a service for it **as soon as a building block
exists for it**; until then it does not ship the extended-tier services, writes the line for you to fill in and says
honestly in the plan which variable you have to enter yourself. See `installer/README.md`, section "Tier per
capability", and `EXTENDING.md` §7.3.

## Status per capability

The column "Default" names the tier the installer takes without a choice (Compose / Kubernetes).

| Capability | Plugin (package) | Basic tier | Extended tier | Default | Status |
|---|---|---|---|---|---|
| Tickets | `vorgaenge` (core), `vorgangsquelle` (fyos-plugin-leitstand) | A plugin's store | Ticket service (`FYOS_VORGAENGE_URL`) | basic / extended | Basic tier done (0.1.0); tier choice in the installer; the installer does not ship the extended-tier service yet |
| Appointments | `termine` (core), `kalender` (fyos-plugin-kalender), control room | CalDAV and ICS accounts directly | Appointment service (`FYOS_TERMINE_URL`) | basic / extended | Basic tier done, ships with 0.1.1; tier choice in the installer; the extended-tier service is still missing as a building block |
| Read mailbox | `postfach` (core), `mail` (fyos-plugin-mail), watch in the control room | IMAP directly, read-only | Mailbox service (`FYOS_POSTFACH_URL`) | basic / extended | Basic tier done, ships with 0.1.1; tier choice in the installer; the extended-tier service is still missing as a building block |
| Send mail | `post` (fyos-plugin-mail) | — | Listmonk (`FYOS_POST_URL`) | extended / extended | Plugin done (fyos-plugin-mail 0.2.0); only extended or off; Listmonk is still missing as a building block in the installer (you enter `FYOS_POST_URL` yourself) |
| Documents | `dokumente` (core), `dokumente` (fyos-plugin-leitstand) | Folder store (planned) | Paperless-ngx (`FYOS_DOKUMENTE_URL`, token in `FYOS_DOKUMENTE_KOPF`) | extended / extended, until the folder store exists | Source and control room done (extended tier), ships with 0.1.1; basic tier open, Paperless-ngx still missing as a building block |
| Files | `dateien` (core, with the app "Files") | Folder on a volume (`FYOS_DATEIEN`) with trash and earlier versions | — | done, ships with 0.1.1; store of the core, no service needed (`EXTENDING.md` §2.17) |
| Views | `gui` (core) | In the Hub; with Redis they survive a restart | — | done; from 0.1.1 also through the shell |
| Agent | fyos-agent | Runner on pi-durable (`fyos-agent/runner`), Compose and Kubernetes | — | done (0.2.1) |
| Night work | `os` (core), runner schedule | Schedule in `agent-runner.json`; the notice waits in Redis for up to 24 h | — | Notice done; the trigger needs `schleifen.darf` in the Hub, see [`NIGHT-WORK.md`](NIGHT-WORK.md) |
| Home | fyos-plugin-haus | conceivable: Home Assistant directly | Home service in front of Home Assistant, cameras through Frigate and MQTT | Package present; today needs the home service |
| Accounts | fyos-plugin-konten | conceivable: one access per account directly | Accounts service as a vault for credentials; photos through Immich | Cleaned up (0.2.0); today needs the accounts service |
| Finances | fyos-plugin-finanzen | — | Finance service (monthly plan, account data) | Cleaned up (0.2.0); today needs the finance service |
| Operations | fyos-plugin-betrieb | — | Kubernetes, Gitea, Prometheus, Postgres for the operations graph | Cleaned up (0.3.1) |
| Model | fyos-plugin-modell | The model the agent uses | Your own model server with a control desk | Cleaned up (0.2.0) |
| Control room | fyos-plugin-leitstand | Redis | Postgres (decisions), Qdrant (knowledge), further services | Package present; sources follow capability by capability |

"Package present" means: the plugin was taken over from the original system and runs when the services behind it are
there. In home and control room some defaults still point to service names of a particular cluster, and some environment
variables still carry proper names; both go away in the cleanup (step 6). "Cleaned up" means: no default points to a
machine or service (without a setting: "not set up"), variables have neutral names, the old ones keep working as
aliases; the table of settings is in the package's README.

## Order

1. Tickets, basic tier — done.
2. Move the plugins from the original system into the packages — done.
3. Appointments: source in the core, CalDAV and ICS plugin, control room reads through the source — done.
4. Mailbox and mail: source in the core, read-only IMAP plugin, watch through the source — done; after that the plugin
   `post` for Listmonk with a setup command for the template — done.
5. Documents: source in the core with Paperless-ngx as the service, control room reads through the source — done; the
   store without a service of its own (basic tier, a folder) is still to be built.
6. Cleanup in home, accounts, finances, operations, model and control room: no default pointing to internal service
   names (empty = not set up), neutral names for environment variables with proper names (the old ones stay as aliases
   for a while), and where there is a basic tier, a source following the pattern above — accounts, finances, operations
   and model done; home and control room follow. The agent service in operations is called `FYOS_AGENTDIENST_URL` (up
   to 0.2.0, `FYOS_AGENT_URL` meant the gateway of the old agent).
7. The tier per capability in the installer (choice, default by deployment type, effect on the generated files) — done.
8. Still open: the extended-tier services as building blocks in the installer (ticket service, appointment service,
   mailbox service, Listmonk, Paperless-ngx; until then you enter their address yourself) and the basic-tier store for
   documents (a folder) in the core.

A step is only done when `tools/sauber.py` reports 0 findings for the repo, the tests are green and the three states are
visible in the interface.
