import { describe, expect, it } from 'vitest';
import { baueAnzeige, stabilisiere, agentAnzeigename } from '~/lib/agent-runner/anzeige';
import { leerGespraech, mitAnsicht, mitEreignissen, mitSnapshot } from '~/lib/agent-runner/gespraech';
import type { Eintrag, GespraechsEreignis } from '~/lib/agent-runner/typen';

const assistent = (id: number, content: unknown, extra: Record<string, unknown> = {}): Eintrag => ({
  id,
  kind: 'pi.assistant',
  model: [{ role: 'assistant', content, timestamp: 1000 + id, ...extra }],
});

describe('Reducer: Snapshot und Ansicht', () => {
  it('Ansicht setzt Verlauf und markiert geladen', () => {
    const z = mitAnsicht(leerGespraech(), { meta: { titel: 'x' }, entries: [assistent(1, 'hallo')], usage: { input: 3 } });
    expect(z.geladen).toBe(true);
    expect(z.entries).toHaveLength(1);
    expect(z.usage).toEqual({ input: 3 });
  });

  it('Snapshot ersetzt Einträge, übernimmt laufende Nachricht und Werkzeuge (tools und nestedTools)', () => {
    const z = mitSnapshot(mitAnsicht(leerGespraech(), { entries: [assistent(9, 'alt')] }), {
      entries: [assistent(1, 'neu')],
      generation: { message: { role: 'assistant', content: [{ type: 'text', text: 'tipp' }] } },
      tools: [{ callId: 'c1', name: 'bash', arguments: { befehl: 'ls' }, output: 'a', status: 'done' }],
      nestedTools: [{ taskId: 7, name: 'lauf', status: 'running' }],
    });
    expect(z.entries.map((e) => e.id)).toEqual([1]);
    expect(z.busy).toBe(true);
    expect(z.liveMessage?.content).toEqual([{ type: 'text', text: 'tipp' }]);
    expect(z.tools.c1).toMatchObject({ name: 'bash', status: 'fertig', output: 'a', args: { befehl: 'ls' } });
    expect(z.tools['7']).toMatchObject({ name: 'lauf', status: 'running' });
    expect(z.toolReihenfolge).toEqual(['c1', '7']);
  });
});

describe('Reducer: Ereignisse', () => {
  const text = (delta: string, idx = 0): GespraechsEreignis => ({ type: 'message_update', changes: [{ type: 'text_delta', contentIndex: idx, delta }] });

  it('Text-Deltas wachsen im Live-Block, message_end legt den Eintrag ab und leert ihn', () => {
    let z = leerGespraech();
    const r1 = mitEreignissen(z, [
      { type: 'turn_start' },
      { type: 'message_start', message: { role: 'assistant', content: [] } },
      { type: 'message_update', changes: [{ type: 'text_start', contentIndex: 0 }] },
      text('Hal'),
      text('lo'),
    ]);
    z = r1.zustand;
    expect(z.busy).toBe(true);
    expect(z.liveMessage?.content).toEqual([{ type: 'text', text: 'Hallo' }]);
    const r2 = mitEreignissen(z, [
      { type: 'message_end', entry: assistent(5, [{ type: 'text', text: 'Hallo' }]) },
      { type: 'turn_end' },
    ]);
    expect(r2.zustand.liveMessage).toBeNull();
    expect(r2.zustand.entries.map((e) => e.id)).toEqual([5]);
    expect(r2.zustand.busy).toBe(false);
    expect(r2.fertig).toBe(true);
  });

  it('verändert den alten Zustand nicht', () => {
    const alt = leerGespraech();
    const r = mitEreignissen(alt, [{ type: 'message_end', entry: assistent(1, 'x') }]);
    expect(alt.entries).toHaveLength(0);
    expect(r.zustand.entries).toHaveLength(1);
  });

  it('legt einen Eintrag nicht doppelt ab', () => {
    const e = assistent(2, 'x');
    const r = mitEreignissen(mitEreignissen(leerGespraech(), [{ type: 'message_end', entry: e }]).zustand, [{ type: 'entry_appended', entry: e }]);
    expect(r.zustand.entries).toHaveLength(1);
  });

  it('Werkzeug: start, update (append, trimStart, set) und end', () => {
    const r = mitEreignissen(leerGespraech(), [
      { type: 'tool_execution_start', toolCallId: 't1', toolName: 'bash', args: { befehl: 'ls' } },
      { type: 'tool_execution_update', toolCallId: 't1', output: { append: 'abc' } },
      { type: 'tool_execution_update', toolCallId: 't1', output: { append: 'def', trimStart: 1 } },
    ]);
    expect(r.zustand.tools.t1).toMatchObject({ status: 'running', output: 'bcdef' });
    const r2 = mitEreignissen(r.zustand, [
      { type: 'tool_execution_update', toolCallId: 't1', output: { set: 'neu' } },
      { type: 'tool_execution_end', toolCallId: 't1', result: { output: 'fertig!' } },
    ]);
    expect(r2.zustand.tools.t1).toMatchObject({ status: 'fertig', output: 'fertig!' });
    const r3 = mitEreignissen(r2.zustand, [{ type: 'tool_execution_end', toolCallId: 't1', result: { isError: true, output: 'kaputt' } }]);
    expect(r3.zustand.tools.t1?.status).toBe('error');
  });

  it('Werkzeugergebnis als Nachricht füllt die Karte', () => {
    const start = mitEreignissen(leerGespraech(), [{ type: 'tool_execution_start', toolCallId: 't2', toolName: 'hub' }]).zustand;
    const r = mitEreignissen(start, [
      { type: 'message_end', entry: { id: 3, kind: 'pi.user', model: [{ role: 'toolResult', toolCallId: 't2', content: [{ type: 'text', text: 'ok' }], isError: false }] } },
    ]);
    expect(r.zustand.tools.t2).toMatchObject({ output: 'ok', status: 'fertig' });
  });

  it('sammelt Hinweise: Freigabe entschieden, Aufgabe fehlgeschlagen', () => {
    const r = mitEreignissen(leerGespraech(), [
      { type: 'entry_appended', entry: { id: 8, kind: 'fyos.freigabe-entscheidung', data: { id: 'fr-1', entscheidung: 'erteilt' } } },
      { type: 'task_failed', message: 'Zeit um' },
    ]);
    expect(r.hinweise).toEqual([{ text: 'Freigabe erteilt.' }, { text: 'Aufgabe fehlgeschlagen: Zeit um', fehler: true }]);
  });

  it('ein vollständiges message-Ereignis ersetzt die laufende Nachricht', () => {
    const z = mitEreignissen(leerGespraech(), [
      { type: 'message_start', message: { role: 'assistant', content: [] } },
      { type: 'message_update', changes: [{ type: 'message', message: { role: 'assistant', content: [{ type: 'text', text: 'ganz' }] } }] },
    ]).zustand;
    expect(z.liveMessage?.content).toEqual([{ type: 'text', text: 'ganz' }]);
  });

  it('turn_end mit abgeschlossener Nachricht räumt die laufende weg; pending bleibt', () => {
    const live = (stopReason: string) =>
      mitEreignissen(mitEreignissen(leerGespraech(), [{ type: 'message_start', message: { role: 'assistant', content: [], stopReason } }]).zustand, [{ type: 'turn_end' }]).zustand.liveMessage;
    expect(live('stop')).toBeNull();
    expect(live('pending')).not.toBeNull();
  });
});

describe('Anzeige', () => {
  it('zeigt Mensch, Agent mit Gedanken und Werkzeugkarte, ohne Regelwerk (system)', () => {
    const z = mitAnsicht(leerGespraech(), {
      entries: [
        { id: 1, kind: 'pi.system', model: [{ role: 'system', content: '' }] },
        { id: 2, kind: 'fyos.mensch', data: { text: 'Wie steht der Cluster?' }, model: [{ role: 'user', content: 'Wie steht der Cluster?' }] },
        assistent(3, [
          { type: 'thinking', thinking: 'ich schaue nach' },
          { type: 'text', text: 'Ich prüfe.' },
          { type: 'toolCall', id: 'c1', name: 'cluster_lage', arguments: { tief: true } },
        ]),
        { id: 4, kind: 'pi.user', model: [{ role: 'toolResult', toolCallId: 'c1', toolName: 'cluster_lage', content: [{ type: 'text', text: 'alles grün' }] }] },
      ],
    });
    const a = baueAnzeige(z);
    expect(a.map((x) => x.art)).toEqual(['mensch', 'agent']);
    const agent = a[1];
    if (agent?.art !== 'agent') throw new Error('Agent erwartet');
    expect(agent.bloecke.map((b) => b.art)).toEqual(['gedanken', 'text', 'werkzeug']);
    const karte = agent.bloecke[2];
    if (karte?.art !== 'werkzeug') throw new Error('Karte erwartet');
    expect(karte.karte).toMatchObject({ name: 'cluster_lage', status: 'fertig', ausgabe: 'alles grün' });
    expect(karte.karte.eingabe).toContain('"tief": true');
  });

  it('doppelte Nutzertexte (fyos.mensch + pi.user) erscheinen einmal; Eingänge sind eigene Systemzeilen', () => {
    const z = mitAnsicht(leerGespraech(), {
      entries: [
        { id: 1, kind: 'fyos.mensch', data: { text: 'hi', art: 'steuern' }, model: [{ role: 'user', content: 'hi' }] },
        { id: 2, kind: 'pi.user', model: [{ role: 'user', content: 'hi' }] },
        { id: 3, kind: 'fyos.eingang', data: { quelle: 'zeitplan', von: 'zeitplan', text: 'Takt Morgen' }, model: [{ role: 'user', content: 'Eingang von zeitplan …' }] },
      ],
    });
    const a = baueAnzeige(z);
    expect(a).toHaveLength(2);
    expect(a[0]).toMatchObject({ art: 'mensch', steuern: true });
    expect(a[1]).toMatchObject({ art: 'system', titel: 'Eingang · zeitplan', text: 'Takt Morgen' });
  });

  it('zeigt die laufende Nachricht, lose laufende Werkzeuge und „arbeitet“', () => {
    let z = mitEreignissen(leerGespraech(), [
      { type: 'turn_start' },
      { type: 'tool_execution_start', toolCallId: 'x', toolName: 'bash', args: {} },
    ]).zustand;
    expect(baueAnzeige(z).map((x) => x.art)).toEqual(['werkzeug', 'arbeitet']);
    z = mitEreignissen(z, [{ type: 'message_start', message: { role: 'assistant', content: [{ type: 'text', text: 'tipp' }] } }]).zustand;
    const a = baueAnzeige(z);
    expect(a.map((x) => x.art)).toEqual(['agent', 'werkzeug']);
    expect(a[0]).toMatchObject({ live: true });
  });

  it('stabilisiere behält unveränderte Zeilen (gleiche Objekte)', () => {
    const z1 = mitAnsicht(leerGespraech(), { entries: [assistent(1, 'a'), assistent(2, 'b')] });
    const a1 = baueAnzeige(z1);
    const z2 = mitEreignissen(z1, [{ type: 'message_end', entry: assistent(3, 'c') }]).zustand;
    const a2 = stabilisiere(a1, baueAnzeige(z2));
    expect(a2[0]).toBe(a1[0]);
    expect(a2[1]).toBe(a1[1]);
    expect(a2).toHaveLength(3);
  });

  it('Agentenname', () => {
    expect(agentAnzeigename('agent')).toBe('Agent');
    expect(agentAnzeigename('')).toBe('Agent');
    expect(agentAnzeigename('hermes')).toBe('Hermes');
  });
});
