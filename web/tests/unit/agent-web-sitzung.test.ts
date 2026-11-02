/**
 * Sitzung für die Gesprächsfläche: Schnellbefehle, Nachfassen, Spielmodus aus /api/health, Regung des Stroms,
 * und ein Zug als SSE-Strom mit echten Ereignisformen von Hand eingespeist, bis zum fertigen Verlauf.
 */
import { describe, expect, it, vi } from 'vitest';
import type { AgentApi } from '~/lib/agent-runner/api';
import { AgentSitzung } from '~/lib/agent-runner/sitzung';
import { NACHFASS_TEXT } from '~/lib/agent-runner/status';
import type { Gespraech } from '~/lib/agent-runner/typen';
import { baueAnzeige } from '~/lib/agent-runner/anzeige';
import { baueVerlauf } from '~/lib/agent-runner/verlauf';
import { T0, assistent, aufruf, mensch, werkzeugErgebnis } from './agent-web-fixtures';

function offenerStrom() {
  const k = new TextEncoder();
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const antwort = new Response(new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) }));
  return {
    antwort,
    sende: (event: string, daten: unknown) => ctrl.enqueue(k.encode(`event: ${event}\ndata: ${JSON.stringify(daten)}\n\n`)),
    zu: () => {
      try {
        ctrl.close();
      } catch {
        /* schon zu */
      }
    },
  };
}

const root: Gespraech = { id: 1, titel: 'Hauptgespräch', art: 'root' };

function baue(health: () => Record<string, unknown> = () => ({ ok: true, agent: 'agent', geraet: { name: 'Werkbank' } }), gesundheitMs = 0) {
  const gespraechsStroeme: Array<ReturnType<typeof offenerStrom>> = [];
  const wirken = offenerStrom();
  const dok = offenerStrom();
  const api = {
    health: vi.fn(async () => health()),
    gespraeche: vi.fn(async () => [root]),
    freigaben: vi.fn(async () => []),
    laeufe: vi.fn(async () => []),
    zustand: vi.fn(async () => ({ werte: {} })),
    ansicht: vi.fn(async () => ({ id: 1, entries: [] })),
    gespraechsStrom: vi.fn(async () => {
      const s = offenerStrom();
      gespraechsStroeme.push(s);
      return s.antwort;
    }),
    wirkenStrom: vi.fn(async () => wirken.antwort),
    dokumenteStrom: vi.fn(async () => dok.antwort),
    sende: vi.fn(async () => ({})),
    abbrechen: vi.fn(async () => ({})),
    neuesGespraech: vi.fn(async () => ({ id: 2, titel: 'Neu', art: 'mensch' }) as Gespraech),
  };
  const speicher = new Map<string, string>();
  const s = new AgentSitzung({
    api: api as unknown as AgentApi,
    speicher: { getItem: (k) => speicher.get(k) ?? null, setItem: (k, v) => void speicher.set(k, v) },
    verzoegerungMs: 5,
    warte: (_ms, signal) => new Promise((ok) => signal.addEventListener('abort', () => ok(), { once: true })),
    zufall: () => 'zz',
    gesundheitMs,
  });
  return { s, api, gespraechsStroeme };
}

describe('Schnellbefehle', () => {
  it('/neu öffnet ein neues Gespräch und schickt nichts an den Agenten', async () => {
    const { s, api } = baue();
    await s.starte();
    expect(await s.sende('/neu')).toEqual({ befehl: true });
    expect(api.neuesGespraech).toHaveBeenCalled();
    expect(api.sende).not.toHaveBeenCalled();
    expect(s.stand.fokus).toBe(2);
    s.beende();
  });

  it('/stopp und /pause brechen den Zug ab', async () => {
    const { s, api } = baue();
    await s.starte();
    await s.sende('/stopp');
    await s.sende('/pause');
    expect(api.abbrechen).toHaveBeenCalledTimes(2);
    expect(api.abbrechen).toHaveBeenCalledWith(1);
    expect(api.sende).not.toHaveBeenCalled();
    s.beende();
  });

  it('/ruhe blendet die autonome Arbeit aus, /live bringt sie zurück', async () => {
    const { s } = baue();
    await s.starte();
    await s.sende('/ruhe');
    expect(s.stand.live).toBe(false);
    await s.sende('/live an');
    expect(s.stand.live).toBe(true);
    s.beende();
  });

  it('ein Pfad mit „/“ geht als Text an den Agenten', async () => {
    const { s, api } = baue();
    await s.starte();
    await s.sende('/etc/hosts lesen');
    expect(api.sende).toHaveBeenCalledWith(1, '/etc/hosts lesen', 'folgen', 'web:zz');
    s.beende();
  });
});

describe('Nachfassen, Regung, Spielmodus', () => {
  it('Nachfassen greift in den laufenden Zug ein und setzt die Regung zurück', async () => {
    const { s, api } = baue();
    await s.starte();
    await s.nachfassen();
    expect(api.sende).toHaveBeenCalledWith(1, NACHFASS_TEXT, 'steuern', 'web:zz');
    expect(Date.now() - s.stand.letzteRegung).toBeLessThan(2000);
    s.beende();
  });

  it('jede Meldung des Gesprächsstroms setzt die Regung', async () => {
    const { s, gespraechsStroeme } = baue();
    await s.starte();
    await vi.waitFor(() => expect(gespraechsStroeme).toHaveLength(1));
    const vorher = s.stand.letzteRegung;
    await new Promise((r) => setTimeout(r, 15));
    gespraechsStroeme[0]!.sende('ereignisse', [{ type: 'run_start' }]);
    await vi.waitFor(() => expect(s.stand.letzteRegung).toBeGreaterThan(vorher));
    s.beende();
  });

  it('Spielmodus kommt aus /api/health beim Start und wird nachgefragt', async () => {
    let marke: string | null = 'spielmodus.nachhut';
    const { s } = baue(() => ({ ok: true, agent: 'agent', spielmodus: marke }), 20);
    await s.starte();
    expect(s.stand.spielmodus).toBe('spielmodus.nachhut');
    marke = null;
    await vi.waitFor(() => expect(s.stand.spielmodus).toBeNull());
    s.beende();
  });
});

describe('Ein Zug als SSE-Strom, bis zum Verlauf', () => {
  it('Snapshot, Schreiben, Werkzeug, Antwort: ein Zug mit Arbeitszeile und Antwort', async () => {
    const { s, gespraechsStroeme } = baue();
    await s.starte();
    await vi.waitFor(() => expect(gespraechsStroeme).toHaveLength(1));
    const g = gespraechsStroeme[0]!;
    const frage = mensch(1, 'Pushe main', T0);
    g.sende('snapshot', { entries: [frage], tools: [], nestedTools: [], inbox: [], generation: null });
    await vi.waitFor(() => expect(s.stand.gespraech.geladen).toBe(true));

    g.sende('ereignisse', [
      { type: 'run_start' },
      { type: 'turn_start' },
      { type: 'message_start', message: { role: 'assistant', content: [], timestamp: T0 + 1000 } },
      { type: 'message_update', changes: [{ type: 'thinking_start', contentIndex: 0 }, { type: 'thinking_delta', contentIndex: 0, delta: 'Need to push.' }] },
      { type: 'message_update', changes: [{ type: 'toolcall_start', contentIndex: 1, block: { id: 'c9', name: 'bash', arguments: { command: 'git push' } } }] },
    ]);
    await vi.waitFor(() => expect(s.stand.gespraech.liveMessage).not.toBeNull());
    const waehrend = baueVerlauf(baueAnzeige(s.stand.gespraech), { jetzt: T0 + 5000 });
    expect(waehrend.map((p) => p.art)).toEqual(['mensch', 'zug']);
    expect(waehrend[1]).toMatchObject({ laeuft: true });

    g.sende('ereignisse', [
      { type: 'message_end', entry: assistent(2, [{ type: 'thinking', thinking: 'Need to push.' }, aufruf('c9', 'bash', { command: 'git push' })], T0 + 1000) },
      { type: 'tool_execution_start', toolCallId: 'c9', toolName: 'bash', args: { command: 'git push' } },
      { type: 'tool_execution_update', toolCallId: 'c9', output: { append: 'Everything up-to-date' } },
      { type: 'tool_execution_end', toolCallId: 'c9', result: { output: 'Everything up-to-date' }, entry: werkzeugErgebnis(3, 'c9', 'bash', 'Everything up-to-date', false, T0 + 3000) },
      { type: 'message_end', entry: werkzeugErgebnis(3, 'c9', 'bash', 'Everything up-to-date', false, T0 + 3000) },
      { type: 'message_start', message: { role: 'assistant', content: [], timestamp: T0 + 4000 } },
      { type: 'message_update', changes: [{ type: 'text_start', contentIndex: 0 }, { type: 'text_delta', contentIndex: 0, delta: 'Schon alles oben.' }] },
      { type: 'message_end', entry: assistent(4, [{ type: 'text', text: 'Schon alles oben.' }], T0 + 4000) },
      { type: 'turn_end' },
      { type: 'run_end' },
    ]);
    await vi.waitFor(() => expect(s.stand.gespraech.busy).toBe(false));
    const v = baueVerlauf(baueAnzeige(s.stand.gespraech), { jetzt: T0 + 60_000 });
    expect(v.map((p) => p.art)).toEqual(['mensch', 'zug']);
    const zug = v[1];
    if (zug?.art !== 'zug') throw new Error('Zug erwartet');
    expect(zug.antwort).toBe('Schon alles oben.');
    expect(zug.schrittZahl).toBe(1);
    expect(zug.schritte.map((x) => x.art)).toEqual(['gedanken', 'werkzeug']);
    expect(zug.schritte[1]).toMatchObject({ titel: 'Shell: git push', status: 'fertig', ausgabe: 'Everything up-to-date' });
    expect(zug.laeuft).toBe(false);
    s.beende();
  });
});
