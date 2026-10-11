/**
 * MCP-Apps-Host — App „Dateien“:
 *  - nur dieses Plugin bekommt die Fähigkeit `fyosDateien` und darf über den Host hochladen (`fyos/datei-hochladen`)
 *  - der Host schickt die Datei als PUT aus dem Ursprung der Shell (die App im Sandbox-iframe darf es selbst nicht)
 *  - Fehler des Hubs (Datei da, zu groß) kommen als gewöhnliches Ergebnis zurück, nicht als Absturz
 *  - `ui/open-link` setzt den relativen Weg zur Datei auf den Ursprung der Shell, nur für dieses Plugin und nur diesen Weg
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DATEI_ADRESSE, appEinhaengen, dateiHochladen, type McpApp } from '~/lib/mcp-apps/host';

const app = (name: string): McpApp =>
  ({ tool: name.replace('__', '.'), name, description: 'x', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/x.html' } }, scope: 'READ' }) as McpApp;

const DATEIEN = app('dateien__liste');
const HAUS = app('haus__favoriten');

type Put = { url: string; methode: string; kopf: Record<string, string>; koerper: unknown };
let puts: Put[];
let antwortDesHubs: () => Response;
const abmeldungen: (() => void)[] = [];

beforeEach(() => {
  puts = [];
  antwortDesHubs = () => new Response(JSON.stringify({ ok: true, result: { pfad: 'a/b.md', groesse: 3, ersetzt: false } }), { headers: { 'content-type': 'application/json' } });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes('/hub-api/resource')) return new Response(JSON.stringify({ ok: true, text: '<p>x</p>' }));
      if (u.includes('/hub-api/dateien/datei')) {
        puts.push({ url: u, methode: String(init?.method), kopf: (init?.headers ?? {}) as Record<string, string>, koerper: init?.body });
        return antwortDesHubs();
      }
      return new Response('{}', { status: 404 });
    }),
  );
});
afterEach(() => {
  while (abmeldungen.length) abmeldungen.pop()!();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function einhaengen(a: McpApp) {
  const f = document.createElement('iframe');
  document.body.appendChild(f);
  const antworten: { id?: number; result?: Record<string, unknown>; error?: { message: string } }[] = [];
  abmeldungen.push(await appEinhaengen(f, { app: a, args: {}, ergebnis: { content: [] }, theme: () => 'dark' }));
  vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
    antworten.push(m as (typeof antworten)[number]);
  });
  const sprechen = (method: string, params: unknown, id?: number) =>
    window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: { jsonrpc: '2.0', ...(id != null ? { id } : {}), method, params } }));
  const auf = (id: number) => vi.waitFor(() => expect(antworten.find((x) => x.id === id)).toBeTruthy()).then(() => antworten.find((x) => x.id === id)!);
  return { sprechen, auf };
}

const blob = () => new Blob(['abc'], { type: 'text/markdown' });

describe('Fähigkeit', () => {
  it('meldet fyosDateien nur der App „Dateien“', async () => {
    const d = await einhaengen(DATEIEN);
    d.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    expect(((await d.auf(1)).result as { hostCapabilities: object }).hostCapabilities).toHaveProperty('fyosDateien');
    const h = await einhaengen(HAUS);
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 2);
    expect(((await h.auf(2)).result as { hostCapabilities: object }).hostCapabilities).not.toHaveProperty('fyosDateien');
  });
});

describe('fyos/datei-hochladen', () => {
  it('schickt die Datei als PUT mit dem Pfad in der Adresse und gibt das Ergebnis zurück', async () => {
    const d = await einhaengen(DATEIEN);
    d.sprechen('fyos/datei-hochladen', { pfad: 'Projekt/Notizen & mehr/heute.md', datei: blob() }, 5);
    expect(await d.auf(5)).toMatchObject({ result: { ok: true, result: { pfad: 'a/b.md', groesse: 3 } } });
    expect(puts).toHaveLength(1);
    expect(puts[0].methode).toBe('PUT');
    expect(puts[0].url).toBe('/hub-api/dateien/datei?pfad=Projekt%2FNotizen+%26+mehr%2Fheute.md');
    expect(puts[0].koerper).toBeInstanceOf(Blob);
  });

  it('setzt ueberschreiben nur auf Wunsch', async () => {
    const d = await einhaengen(DATEIEN);
    d.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: blob(), ueberschreiben: true }, 6);
    await d.auf(6);
    d.sprechen('fyos/datei-hochladen', { pfad: 'b.md', datei: blob(), ueberschreiben: 'ja' }, 7);
    await d.auf(7);
    expect(puts[0].url).toContain('ueberschreiben=1');
    expect(puts[1].url).not.toContain('ueberschreiben');
  });

  it('gibt einen Fehler des Hubs als Ergebnis zurück (Datei da, zu groß), nicht als Absturz', async () => {
    antwortDesHubs = () =>
      new Response(JSON.stringify({ ok: false, kind: 'existiert', error: 'Die Datei gibt es schon' }), { status: 409, headers: { 'content-type': 'application/json' } });
    const d = await einhaengen(DATEIEN);
    d.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: blob() }, 8);
    expect(await d.auf(8)).toMatchObject({ result: { ok: false, kind: 'existiert', error: 'Die Datei gibt es schon' } });
    antwortDesHubs = () => new Response('zu groß', { status: 413 });
    d.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: blob() }, 9);
    expect(await d.auf(9)).toMatchObject({ result: { ok: false, kind: 'zu_gross' } });
  });

  it('lehnt andere Apps ab, ebenso fehlenden Pfad, fehlende Datei und zu lange Pfade', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: blob() }, 10);
    expect(await h.auf(10)).toMatchObject({ error: { message: expect.stringContaining('nur in der App') } });
    const d = await einhaengen(DATEIEN);
    d.sprechen('fyos/datei-hochladen', { pfad: '', datei: blob() }, 11);
    d.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: 'text statt Datei' }, 12);
    d.sprechen('fyos/datei-hochladen', { pfad: 'x'.repeat(401), datei: blob() }, 13);
    for (const id of [11, 12, 13]) expect(await d.auf(id)).toMatchObject({ error: {} });
    expect(puts).toEqual([]);
  });

  it('wirft mit Grund, wenn statt JSON die Anmeldeseite kommt, und die App bekommt einen Fehler', async () => {
    antwortDesHubs = () => new Response('<html>Anmelden</html>', { headers: { 'content-type': 'text/html' } });
    await expect(dateiHochladen('a.md', blob())).rejects.toThrow(/Anmeldung abgelaufen/);
    const d = await einhaengen(DATEIEN);
    d.sprechen('fyos/datei-hochladen', { pfad: 'a.md', datei: blob() }, 14);
    expect(await d.auf(14)).toMatchObject({ error: { message: expect.stringContaining('Anmeldung abgelaufen') } });
  });
});

describe('ui/open-link für Dateien', () => {
  let tab: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    tab = vi.fn();
    vi.stubGlobal('open', tab);
  });

  it('setzt den relativen Weg zur Datei auf den Ursprung der Shell', async () => {
    const d = await einhaengen(DATEIEN);
    const rel = `${DATEI_ADRESSE}pfad=Bericht.pdf`;
    d.sprechen('ui/open-link', { url: rel }, 20);
    expect(await d.auf(20)).toMatchObject({ result: {} });
    expect(tab).toHaveBeenCalledWith(`${window.location.origin}${rel}`, '_blank', 'noopener');
  });

  it('lässt andere relative Adressen und andere Apps nicht durch', async () => {
    const d = await einhaengen(DATEIEN);
    d.sprechen('ui/open-link', { url: '/hub-api/app-call' }, 21);
    expect(await d.auf(21)).toMatchObject({ result: { isError: true } });
    const h = await einhaengen(HAUS);
    h.sprechen('ui/open-link', { url: `${DATEI_ADRESSE}pfad=x.pdf` }, 22);
    expect(await h.auf(22)).toMatchObject({ result: { isError: true } });
    expect(tab).not.toHaveBeenCalled();
  });
});
