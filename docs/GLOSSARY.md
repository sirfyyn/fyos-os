# Glossary: German ↔ English

FYOS started in German, and many identifiers still are: tool names (`itsm.freigeben`), configuration keys
(`bestaetigt`, `wartet_auf`), environment variables (`FYOS_DATEIEN`) and file names in the code. Those are part of the
contract and stay as they are. Prose, interface texts and documentation use the English words below, so that the docs,
the shell and the installer speak the same language.

When a German identifier appears in English text, keep it in code formatting (`` `vorgaenge` ``) and, the first time,
add the English word next to it: "the `vorgaenge` source (tickets)".

## Core terms

| German | English | Note |
|---|---|---|
| Agent | agent | the runner from `fyos-agent` |
| Runner | runner | the agent process (`fyos-agent/runner`); lower case in prose |
| Hub, MCP-Hub | Hub, MCP hub | capitalised as a proper name |
| Plugin | plugin | |
| Werkzeug | tool | an MCP tool, `<plugin>.<tool>` |
| Oberfläche | interface, UI | "app interface" for an `ui://` resource |
| Shell, Desktop-Shell | shell, desktop shell | the browser desktop in `web/` |
| App | app | a hub app (`ui://`) shown in a window |
| Fläche | surface | a window content the shell can open |
| Kachel | tile | |
| Fenster | window | |
| Menüleiste | menu bar | |
| Raum, Räume | room, rooms | |
| Zentrale | control center | |
| Kontrollzentrum | control center | same word as Zentrale in prose |
| Leitstand | control room | the plugin `fyos-plugin-leitstand` keeps its name |
| Baustein | building block | in the installer |
| Kern | core | the parts every installation gets |
| Bild (Container-Bild) | image | |
| Auslieferung | delivery | what the installer generates |
| Einzelplatz | single machine | |
| Erscheinungsbild | appearance | settings section |
| Farbschema: Hell / Dunkel / System | colour scheme: Light / Dark / System | System follows the device (`prefers-color-scheme`), the default |
| Name des Agenten | agent name | from the persona, shown in the interface (`agent.name` in `fyos.config.json`) |
| Kennung | ID | e.g. the runner's agent ID `main`; never shown as a name |

## Work and approval

| German | English | Note |
|---|---|---|
| Vorgang, Vorgänge | ticket, tickets | ITSM record; tool names keep `vorgang` |
| Störung (`INC`) | incident | |
| Änderung (`CHG`) | change | |
| Vorhaben (`VOR`) | project | |
| Freigabe | approval | |
| freigeben / erteilen | approve / grant | |
| ablehnen | reject | |
| Besitzer | owner | the person who runs FYOS |
| Akteur | actor | |
| Verlauf | history | |
| Melder | reporter | |
| Zuständig | assignee | |
| Lauf, Läufe | run, runs | |
| Takt, Takte | schedule, schedules | timed wake-ups of the runner |
| Schleife | loop | |
| Tor | gate | `schleifen.darf` |
| Nachtarbeit | night work | |
| Nachtauftrag | night job | |
| Mitteilung | notice | a card in the shell |
| Meldung | message, report | depends on context |
| vormerken | queue (for later) | |
| Trockenlauf (`__dry_run__`) | dry run | |
| bestätigt | confirmed | key `bestaetigt` stays |
| Werkstatt | workshop | registered scripts |
| Ansicht | view | built by the plugin `gui` |
| Vorlage | template | |
| Fähigkeit | capability | |
| Quelle | source | a pluggable data source of the Hub |
| Ablage | store | a plugin's own storage behind a source |
| Dateiablage | file store | |
| Postfach | mailbox | |
| Termin | appointment, event | |
| Dokument | document | |
| Ding, Dinge | thing, things | typed objects apps hand over |
| Übergabe | handover | |
| Begleitskript, Begleitdienst | companion script, companion service | |
| Grundstufe / Ausbaustufe | basic tier / extended tier | |
| nicht eingerichtet | not set up | the third state next to data and error |
| Sauberkeitsprüfung | cleanliness check | `tools/sauber.py` |
| Doku-Abgleich | docs check | `tools/doku_pruefen.py` |

## Style

- Plain, active sentences. Say what something does, not how good it is.
- One word per thing: if the table says "ticket", do not switch to "issue" or "task".
- Keep identifiers, tool names, configuration keys and environment variables unchanged, even when they are German.
