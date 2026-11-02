# Night work: done at night, in the morning the shell reports "done"

The agent works at night on its own. In the morning, when someone opens the shell, a card is waiting: "Notes sorted"
with the time it finished ("last night, 03:12"). Three parts belong to this:

| Part | What | Where |
|---|---|---|
| Trigger | a schedule of the agent (runner, `takt.eintraege` in `agent-runner.json`), at night | `agent-runner.json` (fyos-agent/runner/README.md) |
| Notice | the Hub tool `os.mitteilen`; if no one is there, the notice waits in Redis | [`hub/mcp_hub/plugins/os.py`](../hub/mcp_hub/plugins/os.py), [`hub/mcp_hub/os_bruecke.py`](../hub/mcp_hub/os_bruecke.py) |
| Display | the shell checks in with the Hub, picks it up and shows the card | [`web/src/lib/os/bruecke.ts`](../web/src/lib/os/bruecke.ts), [`web/src/components/os/Mitteilungen.tsx`](../web/src/components/os/Mitteilungen.tsx) |

## How it runs

1. At 03:00 a runner schedule wakes the agent with the job "sort notes" (no chat, no delivery to a channel).
2. The agent reads the notepad through the Hub tool `beispiel_app.zeigen` (not from files in the workspace, see "Where
   the notes come from" below), summarises the notes and at the end calls `os.mitteilen` in the Hub exactly once. It
   reports "no new notes" only when the notepad is empty; if reading fails, it reports "notepad not reachable".
3. If someone sits in front of an open shell (visible, used in the last 10 minutes), the card appears at once. Otherwise
   the tool answers `vorgemerkt: true`: the notice is queued in Redis (list `fyos:os:ausstehend`, at most 20, for 24
   hours).
4. The shell checks in as a session of the OS bridge, every 5 seconds while the tab is visible. The first check-in after
   opening delivers the queued notices, oldest first, each exactly once, without sound. The card carries the time it was
   created and stays for 30 seconds (an ordinary one for 10).

Nothing wakes anyone at night: queued notices play neither a chime nor a voice.

## Setting up

A night job is the owner's decision; the agent does not create schedules for itself, and the Hub does not start any.
The trigger is a schedule of its own in the runner's `agent-runner.json` (the installer's template turns off the
built-in daily rhythm with `"takt": {"an": false}`):

```json
"takt": {
  "an": true,
  "zone": "Europe/Berlin",
  "eintraege": [
    {"id": "nacht-notizen", "um": "03:00", "fenster_min": 120, "schleife": "arbeit", "art": "melden",
     "text": "Night job notes: read the notepad with beispiel_app.zeigen, summarise it and report with os.mitteilen (quelle Nacht, dringlichkeit niedrig)."}
  ]
}
```

Your own entries replace the built-in rhythm (`takt.mit_standard: true` adds it back); after the change, restart the
agent (`docker compose restart agent`). The runner wakes the agent only when its loop's gate is open (Hub tool
`schleifen.darf`); a Hub without this tool keeps the gate closed, and the schedule then lapses silently. The job ends
with `os.mitteilen`. The instructions for the agent are in the skill `nachtarbeit` (part of the core).

## Where the notes come from

The notepad (plugin `beispiel_app`) lives in the Hub, in Redis. The night job reads it with `beispiel_app.zeigen`
(`hub__call_tool`, `tool: "beispiel_app.zeigen"`); the answer has `anzahl` and `notizen` with `id`, `text` and `zeit`.
The agent can see this tool; `beispiel_app.lesen`, `hinzufuegen` and `loeschen` exist only for the interface.

Whatever a night job should process belongs behind a Hub tool that delivers the data, not in a folder whose file names
the agent could only guess. And a job reports "empty" only when the tool said "empty".

## The tool `os.mitteilen`

```
os.mitteilen {titel, text?, ziel?, eingabe?, dringlichkeit?, quelle?}
```

`titel` (up to 80 characters) and `text` (up to 300) must make sense hours later without context. `ziel` opens a
surface on click (default: the chat with the agent). The answer:

| Answer | Meaning |
|---|---|
| `zugestellt: true` | the card is on the device someone is sitting in front of |
| `zugestellt: true`, `weg: "kanal"`, `kanal` | no one there, but `dringlichkeit: hoch`: went out at once over a registered chat route (`os_bruecke.kanal_anmelden`); nothing waits |
| `vorgemerkt: true`, `rueckfall: "vorgemerkt"` | no one there; the notice waits for up to 24 hours |
| `kanal_fehler` (with `vorgemerkt`) | urgent, but the chat route failed (`zu_viele`, `nicht_zugestellt`); it waits for the shell |
| `grund: "doppelt"` | the same notice is already shown or already waiting |
| `rueckfall: "gebuendelt"` | more than 6 in 10 minutes; summarise |
| `rueckfall: "kanal"` | no one there and queuing is off; take another route |

The tools `os.lage`, `os.zeigen` and `os.ausfuehren` belong to the same plugin (see
[`HUB-CONTRACT.md`](HUB-CONTRACT.md) §3 for the protocol).

## Settings

| Setting | Effect |
|---|---|
| `REDIS_URL` | required; without Redis there are no sessions and nothing can wait (`os.lage` reports `redis`) |
| `OS_NACHHOLEN=aus` or plugin config `nachholen: false` | do not queue notices; `os.mitteilen` then answers `rueckfall: "kanal"` |
| `OS_KANAL=aus` or plugin config `kanal: false` | urgent notices (`hoch`) do not go to the chat without a device; they are queued like everything else |
| `OS_AGENT_AUFRUFER` | names that count as the agent (default `agent*`) |
| Notices "muted" / "off" in the shell | the card then does not appear; a queued notice is still delivered and thereby used up |

## Limits

- At most 20 notices wait; the oldest drop out; each expires after 24 hours. The shell shows at most three cards on top
  of each other (the newest). If you have more to report, summarise.
- The shell has to be opened once: only a session with a check-in picks up queued notices. A native app without a stream
  checks in with `abholen: true` and gets them in the answer, just like the shell.
- The time on the card is the device's local time.
- The chat route is for urgent things, not for filing: the same notice at most once per 10 minutes, at most 6 in total
  per 10 minutes (after that they are queued). It needs a plugin that registers a chat route (`kanal_anmelden`); the
  distribution ships none, so queuing remains. The runner sets up Matrix as a route for approval messages itself
  (`pi_durable.freigabe_meldung.kanaele` in `agent-runner.json`).

## Testing

- Hub: `hub/tests/test_os.py` (queuing, upper limit, expiry, deliver exactly once) and
  `hub/tests/test_einstiegspunkte.py`.
- Shell: `web/tests/unit/os-bruecke.test.ts`, `web/tests/unit/os-mitteilung.test.tsx`, `web/tests/unit/os-shell.test.tsx`.
