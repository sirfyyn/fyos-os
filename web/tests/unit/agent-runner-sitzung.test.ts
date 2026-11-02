import { describe, expect, it, vi } from 'vitest';
import type { AgentApi } from '~/lib/agent-runner/api';
import { AgentSitzung, werteAusEingabe, FOKUS_SPEICHER } from '~/lib/agent-runner/sitzung';
import { RunnerFehler } from '~/lib/agent-runner/verbindung';
import type { Freigabe, Gespraech } from '~/lib/agent-runner/typen';

/** Ein SSE-Strom, den der Test von Hand füttert. */
function offenerStrom() {
  const k = new TextEncoder();
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const antwort = new Response(new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c) }));
  return {
    antwort,
    sende: (event: string, daten: unknown) => ctrl.enqueue(k.encode(`event: ${event}\ndata: ${JSON.stringify(daten)}\n\n`)),
    zu: () => { try { ctrl.close(); } catch { /* schon zu */ } },
  };
}

const root: Gespraech = { id: 1, titel: 'Hauptgespräch', art: 'root' };
const frei = (id: string, status = 'offen'): Freigabe => ({ id, status, aktion: `Aktion ${id}`, risiko: 'high' });

function baue(opt: { gespraeche?: Gespraech[] | Error; freigaben?: Freigabe[] } = {}) {
  const gespraechsStroeme: Array<ReturnType<typeof offenerStrom>> = [];
  const wirken = offenerStrom();
  const dok = offenerStrom();
  const api = {
    health: vi.fn(async () => ({ ok: true, agent: 'agent', geraet: { name: 'Werkbank' } })),
    gespraeche: vi.fn(async () => {
      if (opt.gespraeche instanceof Error) throw opt.gespraeche;
      return opt.gespraeche ?? [root];
    }),
    freigaben: vi.fn(async () => opt.freigaben ?? []),
    laeufe: vi.fn(async () => []),
    zustand: vi.fn(async () => ({ werte: { k: 'v' } })),
    ansicht: vi.fn(async () => ({ id: 1, entries: [{ id: 1, kind: 'fyos.mensch', data: { text: 'früher' }, model: [{ role: 'user', content: 'früher' }] }] })),
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
    entscheideFreigabe: vi.fn(async (id: string) => [frei(id, 'erteilt')]),
    neuerLauf: vi.fn(async () => ({ id: '5', titel: 'Lauf', status: 'laeuft' })),
    laufAbbrechen: vi.fn(async () => ({})),
    zustandSetzen: vi.fn(async () => ({})),
    zustandLoeschen: vi.fn(async () => ({})),
  };
  const speicher = new Map<string, string>();
  const s = new AgentSitzung({
    api: api as unknown as AgentApi,
    speicher: { getItem: (k) => speicher.get(k) ?? null, setItem: (k, v) => void speicher.set(k, v) },
    verzoegerungMs: 5,
    warte: (_ms, signal) => new Promise((ok) => signal.addEventListener('abort', () => ok(), { once: true })),
    zufall: () => 'zz',
  });
  return { s, api, speicher, gespraechsStroeme, wirken, dok };
}

describe('AgentSitzung', () => {
  it('startet: lädt alles, öffnet das Hauptgespräch, Live ist an', async () => {
    const { s, api, speicher } = baue({ freigaben: [frei('a')] });
    await s.starte();
    const st = s.stand;
    expect(st.start).toBe('bereit');
    expect(st.agentName).toBe('Agent');
    expect(st.geraet).toBe('Werkbank');
    expect(st.fokus).toBe(1);
    expect(st.live).toBe(true);
    expect(api.wirkenStrom).toHaveBeenCalledTimes(1);
    expect(api.dokumenteStrom).toHaveBeenCalledTimes(1);
    expect(st.freigaben.map((f) => f.id)).toEqual(['a']);
    expect(st.zustand?.werte).toEqual({ k: 'v' });
    expect(speicher.get(FOKUS_SPEICHER)).toBe('1');
    expect(st.gespraech.entries).toHaveLength(1); // aus der Ansicht, noch vor dem Snapshot
    s.beende();
  });

  it('Snapshot und Ereignisse des Stroms landen im Gespräch', async () => {
    const { s, gespraechsStroeme } = baue();
    await s.starte();
    await vi.waitFor(() => expect(gespraechsStroeme).toHaveLength(1));
    const g = gespraechsStroeme[0]!;
    g.sende('snapshot', { entries: [], generation: null });
    g.sende('ereignisse', [
      { type: 'turn_start' },
      { type: 'message_start', message: { role: 'assistant', content: [] } },
      { type: 'message_update', changes: [{ type: 'text_start', contentIndex: 0 }, { type: 'text_delta', contentIndex: 0, delta: 'Hallo' }] },
    ]);
    await vi.waitFor(() => expect(s.stand.gespraech.liveMessage?.content).toEqual([{ type: 'text', text: 'Hallo' }]));
    expect(s.stand.gespraech.busy).toBe(true);
    s.beende();
  });

  it('ein Zugangsfehler bei der Liste ist ein Startfehler mit Grund; „erneut“ klappt danach', async () => {
    const { s, api } = baue({ gespraeche: new RunnerFehler('anmeldung', 0) });
    await s.starte();
    expect(s.stand.start).toBe('fehler');
    expect(s.stand.fehler?.art).toBe('anmeldung');
    expect(api.wirkenStrom).not.toHaveBeenCalled();
    api.gespraeche.mockResolvedValue([root]);
    await s.erneut();
    expect(s.stand.start).toBe('bereit');
    s.beende();
  });

  it('/live schaltet nur die Anzeige und schickt nichts an den Agenten; der Fokus bleibt', async () => {
    const { s, api, speicher } = baue();
    await s.starte();
    expect((await s.sende('/live aus')).befehl).toBe(true);
    expect(s.stand.live).toBe(false);
    expect(s.stand.stromStatus).toBe('aus');
    expect(speicher.get('fyos:agent:live')).toBe('aus');
    expect(api.sende).not.toHaveBeenCalled();
    expect(s.stand.fokus).toBe(1);
    await s.sende('/live');
    expect(s.stand.live).toBe(true);
    expect(api.wirkenStrom).toHaveBeenCalledTimes(2);
    s.beende();
  });

  it('war Live gespeichert aus, bleibt der Strom zu', async () => {
    const { api, speicher } = baue();
    speicher.set('fyos:agent:live', 'aus');
    const s = new AgentSitzung({
      api: api as unknown as AgentApi,
      speicher: { getItem: (k) => speicher.get(k) ?? null, setItem: (k, v) => void speicher.set(k, v) },
      verzoegerungMs: 5,
      warte: () => new Promise(() => {}),
    });
    await s.starte();
    expect(s.stand.live).toBe(false);
    expect(api.wirkenStrom).not.toHaveBeenCalled();
    s.beende();
  });

  it('Text geht mit Art und Anforderungskennung ins offene Gespräch', async () => {
    const { s, api } = baue();
    await s.starte();
    await s.sende('  mach das  ', 'steuern');
    expect(api.sende).toHaveBeenCalledWith(1, 'mach das', 'steuern', 'web:zz');
    s.beende();
  });

  it('eine Zeile des Stroms ändert den Fokus nicht, ein Klick darauf schon', async () => {
    const { s, wirken, gespraechsStroeme } = baue();
    await s.starte();
    await vi.waitFor(() => expect(s.stand.stromStatus).toBe('offen'));
    wirken.sende('hallo', { gespraeche: [{ id: 1, titel: 'Hauptgespräch', art: 'root' }, { id: 14, titel: 'Lauf 13', art: 'lauf' }] });
    wirken.sende('zeile', { t: 5, gespraech: 14, titel: 'Lauf 13', art: 'lauf', typ: 'schritt', text: 'prüft' });
    await vi.waitFor(() => expect(s.stand.strom.zeilen).toHaveLength(1));
    expect(s.stand.fokus).toBe(1);
    await s.oeffneGespraech(14);
    expect(s.stand.fokus).toBe(14);
    expect(gespraechsStroeme).toHaveLength(2);
    expect(s.titelVon(14)).toBe('Lauf 13');
    s.beende();
  });

  it('Freigabe erteilen setzt die Liste neu und meldet', async () => {
    const { s, api } = baue({ freigaben: [frei('a')] });
    await s.starte();
    await s.entscheideFreigabe('a', 'erteilt');
    expect(api.entscheideFreigabe).toHaveBeenCalledWith('a', 'erteilt', undefined);
    expect(s.stand.freigaben[0]?.status).toBe('erteilt');
    expect(s.stand.hinweis?.text).toBe('Freigabe erteilt.');
    s.beende();
  });

  it('eine neue Freigabe aus dem Dokumentenstrom wird nachgeladen und gemeldet', async () => {
    const { s, api, dok } = baue();
    await s.starte();
    await vi.waitFor(() => expect(api.dokumenteStrom).toHaveBeenCalled());
    api.freigaben.mockResolvedValue([frei('neu')]);
    dok.sende('dokument', { name: 'freigaben', wert: {} });
    await vi.waitFor(() => expect(s.stand.freigaben.map((f) => f.id)).toEqual(['neu']));
    expect(s.stand.hinweis?.text).toBe('Neue Freigabe: Aktion neu');
    s.beende();
  });

  it('Lauf starten braucht ein offenes Gespräch und startet vom Fokus aus', async () => {
    const { s, api } = baue();
    await s.starte();
    await s.neuerLauf(' Titel ', ' Auftrag ');
    expect(api.neuerLauf).toHaveBeenCalledWith(1, { titel: 'Titel', auftrag: 'Auftrag' });
    s.beende();
  });

  it('neues Gespräch wird geöffnet', async () => {
    const { s } = baue();
    await s.starte();
    await s.neuesGespraech('Neu');
    expect(s.stand.fokus).toBe(2);
    expect(s.stand.gespraeche.map((g) => g.id)).toContain(2);
    s.beende();
  });

  it('Zustand: JSON-Werte werden JSON, alles andere Text', () => {
    expect(werteAusEingabe('42')).toBe(42);
    expect(werteAusEingabe('true')).toBe(true);
    expect(werteAusEingabe('{"a":1}')).toEqual({ a: 1 });
    expect(werteAusEingabe('"x"')).toBe('x');
    expect(werteAusEingabe('{kaputt')).toBe('{kaputt');
    expect(werteAusEingabe('Hallo Welt')).toBe('Hallo Welt');
    expect(werteAusEingabe('007')).toBe('007');
    expect(werteAusEingabe('  ')).toBe('');
  });
});
