# ITSM: tickets, history and approvals in the core

Since 0.3.0 the Hub ships a small ITSM, the plugin `itsm`. It keeps tickets with status, comments, history and approvals
in the Hub's Redis, with no extra service. The app "Tickets" shows them; the agent (runner) creates them, asks for
permission through them and learns through them what you decided.

| Part | What | Where |
|---|---|---|
| Store | Tickets and history in Redis (`fyos:itsm:*`), registered as the store for tickets | [`hub/mcp_hub/plugins/_itsm_ablage.py`](../hub/mcp_hub/plugins/_itsm_ablage.py) |
| Tools | `itsm.liste`, `itsm.vorgang`, `itsm.wartend`, `itsm.anlegen`, `itsm.kommentieren`, `itsm.notiz`, `itsm.status_setzen`, `itsm.freigabe_beantragen`, `itsm.status`, `itsm.freigeben`, `itsm.ablehnen` | [`hub/mcp_hub/plugins/itsm.py`](../hub/mcp_hub/plugins/itsm.py) |
| Pass-through | The same tools against a ticket service (`FYOS_VORGAENGE_URL`); `notiz`, `freigabe_beantragen` and `status` on both paths | [`hub/mcp_hub/plugins/_itsm_wege.py`](../hub/mcp_hub/plugins/_itsm_wege.py) |
| Interface | App "Tickets": list, ticket with history, comment, status buttons, "Approve" and "Reject" | [`hub/mcp_hub/plugins/vorgaenge_app.py`](../hub/mcp_hub/plugins/vorgaenge_app.py), [`ui/vorgaenge.html`](../hub/mcp_hub/plugins/ui/vorgaenge.html) |
| Agent | The runner's ITSM watch: reads `itsm.wartend` and `itsm.vorgang`, wakes the agent on your comment or decision | fyos-agent, `runner/src/itsm-wache.js` |

## Setting up

Nothing to do if the Hub has a Redis (`REDIS_URL`; Compose and Kubernetes set it): the installer turns on `itsm` as part
of the core. Without Redis the plugin reports "not set up", and the app says "No store for tickets".

If your own ticket service is configured (`FYOS_VORGAENGE_URL`, ticket contract in EXTENDING.md §2.13), it takes
precedence: the app reads that service, and the `itsm` tools pass through to it (health says `weg: dienst`). Redis is
then not needed. The plugin asks `vorgaenge.quelle()` on every call, so switching the service on or off needs no
restart of the plugin. What a service knows beyond the contract is used when it answers: `GET /tickets/{id}/history`
for the history, `GET /waiting` (groups by `waiting_for`) for `itsm.wartend` (without it: the open approvals), and
fields such as `severity`, `fingerprint` (deduplication on `anlegen`), `links`, `wiedervorlage`.

Differences between the two paths, on purpose:

| | Store (Redis) | Ticket service |
|---|---|---|
| `anlegen`, `kommentieren`, `status_setzen` | need `bestaetigt: true` | write without it (as agents are used to there) |
| Kinds | `INC`, `CHG`, `VOR` | also `PRB` and work cards `WB-…` |
| Agent sets `waiting_approval` | with `status_setzen` | only with `freigabe_beantragen`; `expected_status` is required |
| `wartend` | oldest first | most severe, then oldest first; cached for 20 s |

Settings (all optional, in `hub-config.yaml` under `itsm` → `config` or in the Hub's environment):

| Setting | Environment | Default | Effect |
|---|---|---|---|
| `besitzer` | `FYOS_BESITZER_AKTEUR` | `besitzer` | Actor for your answers from the interface (owner) |
| `agent` | `FYOS_AGENT_ID`, else the first name in `FYOS_AGENTEN` | `agent` | Actor when a tool call does not pass `wer` |
| – | `FYOS_BESITZER_NAMEN` | the owner actor | Names in `waiting_for` that mean "waiting for the owner" (comma-separated; ticket service) |
| `redis_url` | `REDIS_URL` | – | The Hub's Redis |
| – | `FYOS_VORGAENGE_URL`, `FYOS_VORGAENGE_KOPF` | – | Ticket service and its header; the tools pass through to it |

**Important for the runner:** it recognises your comments and approvals by the actor. In `agent-runner.json`,
`itsm.besitzer` must carry the same name as `FYOS_BESITZER_AKTEUR`, and `itsm.agent` the agent's actor. Since 0.3.0 the
installer writes `"itsm": {"besitzer": "besitzer", "agent": "agent"}` into it; if you change the names, change both
sides. Otherwise the watch sees the answers but wakes no one.

## A ticket

- **Kind:** `INC` (incident), `CHG` (change), `VOR` (project). IDs such as `INC-12`, one number sequence for all.
- **Status:** `new` → `triage` → `in_progress` → `waiting_approval` → `resolved` / `closed`. Every transition is
  allowed, with two rules: only the owner sets or leaves `closed` (an agent uses `resolved` or opens a new ticket), and
  only the owner answers an approval.
- **Fields:** title, text, priority (`niedrig` low, `normal`, `hoch` high, `dringend` urgent), assignee, what it is
  waiting for, reporter.
- **History:** every entry with time, actor and text: `created`, `comment`, `updated` (for example
  `status waiting_approval→in_progress`). The last 1000 entries per ticket are kept.

## Confirmation

Whether a writing tool needs `bestaetigt: true` (after a plan with `__dry_run__: true`) is your choice. The default:
with your own store (Redis), `anlegen`, `kommentieren` and `status_setzen` need it and `notiz` does not; with a ticket
service (`FYOS_VORGAENGE_URL`) none of them do, so an agent can work as it is used to. Change it in the hub configuration:

```yaml
- name: itsm
  config:
    bestaetigung: true            # all writing tools
    # or per tool:
    # bestaetigung: {anlegen: true, kommentieren: false, status_setzen: true, notiz: false}
```

Approving and rejecting (`freigeben`, `ablehnen`) are not part of this setting: they only work from the interface and
always ask first.

## Approvals

1. The agent describes on the ticket what it wants to do (comment) and sets it to `waiting_approval`
   (`itsm.status_setzen`, or right away when creating it). `wartet_auf` becomes the owner.
2. `itsm.wartend` lists it; the app "Tickets" shows "Approve" and "Reject" on the ticket.
3. You decide in the app (first the plan, then "Yes"). Approved means `waiting_approval → in_progress`, rejected
   `→ triage`; a reason goes in first as a comment. If two places decide at the same time, the first wins and the second
   gets "already decided".
4. The runner's ITSM watch sees the transition in the history and wakes the agent: on "approved" it carries out exactly
   the requested step, on "rejected" it does not.

If the agent moves the status out of `waiting_approval` itself, that appears under its name in the history; the runner
does not count it as an approval.

For a single risky step on a ticket it is already working on, the agent uses `itsm.freigabe_beantragen` (both paths):
the ticket must be assigned to the agent and `in_progress`. The tool sets `waiting_approval` (waiting for the owner),
puts the request first in the description as `## Freigabe angefragt (Prüfsumme <hex>)` with plan, effect, target and
way back, and adds the same block as a comment. Asking again with the same request is idempotent. `risiko`,
`zerstoererisch` and `kontext` (3 to 5 sentences, secrets are masked) come together or not at all; a ticket service
receives them in the same change as `waiting_approval`. Progress, findings and results go on the ticket with
`itsm.notiz`.

## Trying it out

```
hub.call_tool itsm.anlegen        {"titel": "Router neu starten", "art": "CHG", "__dry_run__": true}
hub.call_tool itsm.anlegen        {"titel": "Router neu starten", "art": "CHG", "bestaetigt": true}
hub.call_tool itsm.status_setzen  {"id": "CHG-1", "status": "waiting_approval", "text": "Neustart heute 22 Uhr", "bestaetigt": true}
hub.call_tool itsm.wartend        {}
```

Then open the ticket in the app "Tickets" and choose "Approve"; afterwards `itsm.wartend` is empty again and
`itsm.vorgang {"id": "CHG-1"}` shows `status waiting_approval→in_progress` by the owner in the history.

## With fyos-plugin-leitstand

Older versions of the control room shipped their own plugin named `itsm` for their ticket service. The core `itsm`
now covers those tools with the same names and compatible fields (`wartend`, `vorgang`, `kommentieren`, `notiz`,
`anlegen`, `status_setzen`, `freigabe_beantragen`, `status`) by passing through to the ticket service, so the control
room no longer registers one. With an older control room the Hub would see two plugins named `itsm`, and the load
order would decide: update the control room together with the core, and make sure a `hub-config.yaml` entry `itsm`
points to the core (`module: mcp_hub.plugins.itsm`) or is removed.

Fields and keys in detail: [HUB-CONTRACT.md](HUB-CONTRACT.md), section "Tickets and ITSM".
