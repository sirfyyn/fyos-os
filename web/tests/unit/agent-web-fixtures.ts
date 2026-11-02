/**
 * Ereignisformen des Runners für die Tests der Gesprächsfläche (Form wie `GET …/ereignisse` und `ansicht`):
 * Sitzungs-Einträge mit `kind`, `data`, `model:[{role,content}]`, dazu die Stapel `message_*`, `tool_execution_*`, `run_end`.
 * So laufen die Tests durch denselben Reducer wie die Fläche selbst.
 */
import { baueAnzeige } from '~/lib/agent-runner/anzeige';
import { leerGespraech, mitEreignissen, mitSnapshot } from '~/lib/agent-runner/gespraech';
import type { Eintrag, GespraechsEreignis, GespraechsZustand } from '~/lib/agent-runner/typen';
import { baueVerlauf } from '~/lib/agent-runner/verlauf';

export const T0 = Date.UTC(2026, 9, 25, 12, 0, 0);

export const mensch = (id: number, text: string, t = T0, art = 'folgen'): Eintrag => ({
  id,
  kind: 'fyos.mensch',
  data: { text, art },
  model: [{ role: 'user', content: [{ type: 'text', text }], timestamp: t }],
});

export const eingang = (id: number, quelle: string, text: string, klasse = 'system', t = T0): Eintrag => ({
  id,
  kind: 'fyos.eingang',
  data: { quelle, von: quelle, klasse, text, stromId: `s${id}` },
  model: [{ role: 'user', content: [{ type: 'text', text }], timestamp: t }],
});

export const assistent = (id: number, content: unknown[], t: number, extra: Record<string, unknown> = {}): Eintrag => ({
  id,
  kind: 'pi.assistant',
  model: [{ role: 'assistant', content, timestamp: t, stopReason: 'stop', ...extra }],
});

export const werkzeugErgebnis = (id: number, toolCallId: string, toolName: string, text: string, isError = false, t = T0): Eintrag => ({
  id,
  kind: 'pi.user',
  model: [{ role: 'toolResult', toolCallId, toolName, content: [{ type: 'text', text }], isError, timestamp: t }],
});

export const aufruf = (id: string, name: string, args: Record<string, unknown>) => ({ type: 'toolCall', id, name, arguments: args });

/** Ein Zug, wie ihn der Runner im Verlauf ablegt: Gedanken + Werkzeugaufrufe, Ergebnisse, Schlusstext. */
export function zugEintraege(start: number, opt: { fehler?: boolean } = {}): Eintrag[] {
  return [
    assistent(start + 1, [
      { type: 'thinking', thinking: 'The user wants the incident. I should look up INC-4905 first, then summarise it for them.' },
      { type: 'text', text: 'Ich schaue kurz nach.' },
      aufruf('c1', 'hub_aufrufen', { werkzeug: 'vorgaenge.zeigen', argumente: { id: 'INC-4905' } }),
    ], T0 + 2_000),
    werkzeugErgebnis(start + 2, 'c1', 'hub_aufrufen', '{"id":"INC-4905","status":"offen"}', false, T0 + 4_000),
    assistent(start + 3, [aufruf('c2', 'bash', { command: opt.fehler ? 'cd /repo && python3 nach_main.py' : 'cd /repo && git push origin main' })], T0 + 6_000),
    werkzeugErgebnis(
      start + 4,
      'c2',
      'bash',
      opt.fehler ? 'usage: nach_main.py [-h] --vorgang V\nKein Gitea-Token' : 'To gitea\n   abc..def  main -> main',
      !!opt.fehler,
      T0 + 9_000,
    ),
    assistent(start + 5, [{ type: 'text', text: 'INC-4905 ist **offen**. Siehe [Vorgang](https://itsm.example/INC-4905).' }], T0 + 38_000),
  ];
}

export function zustand(entries: Eintrag[], ereignisse: GespraechsEreignis[][] = [], busy = false): GespraechsZustand {
  let z = mitSnapshot(leerGespraech(), { entries, run: busy ? {} : null });
  for (const stapel of ereignisse) z = mitEreignissen(z, stapel).zustand;
  return z;
}

export const verlaufAus = (z: GespraechsZustand, opt: { jetzt?: number } = {}) => baueVerlauf(baueAnzeige(z, { agentName: 'Agent' }), { jetzt: opt.jetzt ?? T0 + 60_000 });

/** Stapel eines laufenden Zugs: Text wird gerade geschrieben. */
export const schreibenStapel = (text: string): GespraechsEreignis[] => [
  { type: 'turn_start' },
  { type: 'message_start', message: { role: 'assistant', content: [], timestamp: T0 + 70_000 } },
  { type: 'message_update', changes: [{ type: 'text_start', contentIndex: 0 }, { type: 'text_delta', contentIndex: 0, delta: text }] },
];
