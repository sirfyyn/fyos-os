import { describe, expect, it, vi } from 'vitest';
import { AgentApi } from '~/lib/agent-runner/api';
import { AGENT_BASIS, AgentVerbindung, RunnerFehler } from '~/lib/agent-runner/verbindung';

const json = (daten: unknown, status = 200): Response =>
  new Response(JSON.stringify(daten), { status, headers: { 'Content-Type': 'application/json' } });

function mitFetch(antwort: Response | ((url: string, init: RequestInit) => Response | Promise<Response>)) {
  const f = vi.fn(async (url: string, init: RequestInit) => (typeof antwort === 'function' ? antwort(url, init) : typeof antwort.clone === 'function' ? antwort.clone() : antwort));
  return { f, v: new AgentVerbindung({ fetch: f as unknown as typeof fetch }) };
}

describe('AgentVerbindung', () => {
  it('spricht /api/agent mit Pflicht-Kopf, redirect manual und ohne Token', async () => {
    const { f, v } = mitFetch(json({ ok: true, agent: 'agent' }));
    const d = await v.anfrage<{ agent: string }>('api/health');
    expect(d.agent).toBe('agent');
    const [url, init] = f.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${AGENT_BASIS}/api/health`);
    expect(init.redirect).toBe('manual');
    expect(init.method).toBe('GET');
    const kopf = init.headers as Record<string, string>;
    expect(kopf['X-FYOS-Agent']).toBe('1');
    expect(Object.keys(kopf).map((k) => k.toLowerCase())).not.toContain('authorization');
  });

  it('schickt JSON-Körper mit Content-Type', async () => {
    const { f, v } = mitFetch(json({ ok: true }));
    await v.anfrage('api/gespraech/1/nachricht', { methode: 'POST', koerper: { text: 'x' } });
    const [, init] = f.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBe('{"text":"x"}');
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('opaqueredirect heißt Anmeldung nötig (nicht wiederholbar)', async () => {
    const antwort = { type: 'opaqueredirect', status: 0, ok: false, text: async () => '' } as unknown as Response;
    const { v } = mitFetch(antwort);
    const f = await v.anfrage('api/health').catch((e: unknown) => e);
    expect(f).toBeInstanceOf(RunnerFehler);
    expect(f).toMatchObject({ art: 'anmeldung', wiederholbar: false });
  });

  it.each([
    [401, { ok: false, fehler: 'Nicht erlaubt' }, 'token', false],
    [403, { ok: false }, 'anmeldung', false],
    [404, { ok: false, fehler: 'Gespräch nicht gefunden' }, 'anfrage', false],
    [503, { ok: false }, 'nicht-erreichbar', true],
    [500, { ok: false, fehler: 'kaputt' }, 'server', true],
  ])('Status %i wird zu %s', async (status, body, art, wiederholbar) => {
    const { v } = mitFetch(json(body, status));
    const f = await v.anfrage('x').catch((e: unknown) => e);
    expect(f).toMatchObject({ art, wiederholbar, status });
  });

  it('404 ohne JSON (Text des Proxys) heißt nicht freigegeben', async () => {
    const { v } = mitFetch(new Response('nicht freigegeben', { status: 404 }));
    const f = await v.anfrage('x').catch((e: unknown) => e);
    expect(f).toMatchObject({ art: 'nicht-freigegeben', message: 'nicht freigegeben' });
  });

  it('ok:false im Körper ist ein Fehler, auch bei Status 200', async () => {
    const { v } = mitFetch(json({ ok: false, fehler: 'Schon entschieden' }));
    await expect(v.anfrage('x')).rejects.toMatchObject({ art: 'anfrage', message: 'Schon entschieden' });
  });

  it('ein Netzfehler wird zu art netz', async () => {
    const v = new AgentVerbindung({ fetch: (async () => { throw new TypeError('Failed to fetch'); }) as unknown as typeof fetch });
    await expect(v.anfrage('x')).rejects.toMatchObject({ art: 'netz', wiederholbar: true });
  });

  it('die Zeitgrenze meldet „nicht erreichbar“', async () => {
    const haengt = ((_u: string, init: RequestInit) =>
      new Promise((_ok, nein) => init.signal?.addEventListener('abort', () => nein(Object.assign(new Error('abgebrochen'), { name: 'AbortError' }))))) as unknown as typeof fetch;
    const v = new AgentVerbindung({ fetch: haengt, timeoutMs: 20 });
    await expect(v.anfrage('x')).rejects.toMatchObject({ art: 'nicht-erreichbar' });
  });

  it('Ströme: Accept text/event-stream, Fehler wie bei Anfragen', async () => {
    const { f, v } = mitFetch(new Response('', { status: 503 }));
    await expect(v.oeffneStrom('api/strom')).rejects.toMatchObject({ art: 'nicht-erreichbar' });
    const [, init] = f.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream');
    expect((init.headers as Record<string, string>)['X-FYOS-Agent']).toBe('1');
  });
});

describe('AgentApi: die Wege stehen im Protokoll', () => {
  function api() {
    const aufrufe: Array<[string, string, unknown]> = [];
    const v = new AgentVerbindung({
      fetch: (async (url: string, init: RequestInit) => {
        aufrufe.push([init.method ?? '', url.replace(AGENT_BASIS, ''), init.body ? JSON.parse(String(init.body)) : undefined]);
        return json({ ok: true, gespraeche: [], freigaben: [{ id: 'f', status: 'offen' }], laeufe: [], zustand: { werte: { a: 1 } }, gespraech: { id: 5, titel: 'n', art: 'mensch' }, lauf: { id: '9', status: 'laeuft' } }, url.endsWith('/laeufe') && init.method === 'POST' ? 201 : 200);
      }) as unknown as typeof fetch,
    });
    return { a: new AgentApi(v), aufrufe };
  }

  it('Gespräch, Nachricht, Abbrechen', async () => {
    const { a, aufrufe } = api();
    await a.gespraeche();
    await a.neuesGespraech('Test');
    await a.ansicht(14);
    await a.sende(14, 'hallo', 'steuern', 'web:1');
    await a.abbrechen(14);
    expect(aufrufe).toEqual([
      ['GET', '/api/gespraeche', undefined],
      ['POST', '/api/gespraeche', { titel: 'Test' }],
      ['GET', '/api/gespraech/14/ansicht', undefined],
      ['POST', '/api/gespraech/14/nachricht', { text: 'hallo', art: 'steuern', requestId: 'web:1' }],
      ['POST', '/api/gespraech/14/abbrechen', {}],
    ]);
  });

  it('Freigaben, Läufe, Zustand', async () => {
    const { a, aufrufe } = api();
    expect(await a.entscheideFreigabe('fr-1', 'erteilt')).toHaveLength(1);
    await a.entscheideFreigabe('fr 2', 'abgelehnt', 'zu riskant');
    await a.laeufe();
    await a.neuerLauf(1, { titel: 'T', auftrag: 'A' });
    await a.laufAbbrechen('13');
    await a.zustand();
    await a.zustandSetzen('a/b', { x: 1 });
    await a.zustandLoeschen('a');
    expect(aufrufe).toEqual([
      ['POST', '/api/freigaben/fr-1', { entscheidung: 'erteilt', von: 'mensch' }],
      ['POST', '/api/freigaben/fr%202', { entscheidung: 'abgelehnt', notiz: 'zu riskant', von: 'mensch' }],
      ['GET', '/api/laeufe', undefined],
      ['POST', '/api/gespraech/1/laeufe', { titel: 'T', auftrag: 'A' }],
      ['POST', '/api/laeufe/13/abbrechen', {}],
      ['GET', '/api/zustand', undefined],
      ['PUT', '/api/zustand/a%2Fb', { wert: { x: 1 } }],
      ['DELETE', '/api/zustand/a', undefined],
    ]);
  });
});
