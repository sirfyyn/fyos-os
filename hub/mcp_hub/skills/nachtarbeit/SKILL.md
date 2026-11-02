---
name: nachtarbeit
description: When work should run at night or otherwise without the user and they want to see the result later in the shell (runner schedule, night run, "do this overnight", "let me know when you're done"). How a night job comes about, how you work in a run without the user and how you report with os.mitteilen, even when no one is there.
ausloeser: at night, overnight, night job, night run, cron, schedule, report in the morning, report done, os.mitteilen, notice, queued, sort notes, night work
fuer: [agent]
---

# Night work: done at night, reported in the morning

A night job is work that runs without the user and whose result they see later. It has two parts: the **schedule**
(when and what) and the **notice** at the end (os.mitteilen).

## 1. How a night job comes about

Nothing invents work: the built-in daily rhythm is off, and you create **no schedule for yourself**. A night job is the
owner's decision. The owner enters it as a schedule in `agent-runner.json` (`takt.eintraege`, for example
`{"id": "nacht-notizen", "um": "03:00", "fenster_min": 120, "schleife": "arbeit", "art": "melden", "text": "…"}`, plus
`"takt": {"an": true}`) and restarts the agent. Tell the user the entry and ask when it should run; do not enter it
yourself. Guide: `docs/NIGHT-WORK.md` of the distribution.

## 2. How you work in a night run

- **No one answers.** Do not ask back. If something is missing, decide the small things yourself (small things
  yourself, heavy things the person decides) and do not do the heavy things; instead, write in the notice what was
  left undone.
- **No chat, no channel.** Quiet hours apply (22:00 to 07:00): no proactive chat message goes out at night. Report only
  through `os.mitteilen`.
- **Data from the Hub, not from folders.** Whoever guesses file names gets "not found" and takes a full folder for an
  empty one. Fetch the data through a Hub tool (the notes: `beispiel_app.zeigen`) and report "empty" only when the
  tool says "empty"; if the call fails, report the error.
- **Exactly one notice at the end** (with many sub-tasks one per result, never one per intermediate step).

## 3. The notice

```
os.mitteilen {titel, text?, ziel?, eingabe?, dringlichkeit?, quelle?}
```

- `titel` (≤ 80 characters) and `text` (≤ 300) must make sense **hours later without context**: not "Done", but
  "Notes sorted: 12 notes, 3 topics, 2 open".
- `quelle: "Nacht"`, `dringlichkeit: "niedrig"` (never a sound at night, not later either). `hoch` only if the user may
  be woken; quiet hours do not protect them if you set it.
- `ziel` opens a surface on click, e.g. the app with the result (`app:meine_app__zeigen`, with `eingabe`). Without
  `ziel` the card opens the chat with you.

The answer says what happened:

| Answer | Meaning | What you do |
|---|---|---|
| `zugestellt: true` | someone sits in front of the shell, the card is shown | nothing |
| `zugestellt: false`, `vorgemerkt: true` | no one there; the notice **waits up to 24 h** and appears without sound with the time it was created ("last night, 03:12") as soon as the shell is opened | nothing, this is the normal case at night |
| `zugestellt: true`, `weg: kanal` | no one at the shell, but `dringlichkeit: hoch`: went straight into the user's chat | nothing; `hoch` only for urgent things (something is broken, a deadline is running out) |
| `kanal_fehler` | urgent, the chat route failed; the notice is queued | nothing |
| `grund: doppelt` | the same notice is already shown | nothing |
| `rueckfall: gebuendelt` | too many in a short time | combine results into one notice |
| `rueckfall: kanal` | no one there and nothing is queued (queuing is off) | leave the result in a ticket or a note |

At most 20 queued notices accumulate; the oldest drop out. So summarise.

## 4. Checking

- `os.lage` shows whether a shell is open. `os.mitteilen` appears at once with an open shell; without one it waits.
- A test run: enter the schedule for the next minute, restart the agent, then open the shell.
