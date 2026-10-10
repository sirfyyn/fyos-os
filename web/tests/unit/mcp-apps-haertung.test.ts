/**
 * MCP-Apps-Host — Härtung:
 *  - Inhaltsregeln (CSP) im srcdoc: `appCsp` und `htmlMitCsp`, `_meta.ui.csp` der Ressource
 *  - `tools/call` nur für Werkzeuge, die für Apps sichtbar sind (`_meta.ui.visibility`)
 *  - `ui/message` nur mit Einbetter, Text und Geste; `hostCapabilities.message` nur dann
 *  - Anfragen ohne `id` (Benachrichtigungen) bekommen keine Antwort und lösen nichts aus
 *  - `size-changed` mit NaN/Unendlich, `ui/resource-teardown` beim Abmelden
 *  - abgelaufene Anmeldung (Umleitung, 401, HTML) → Ereignis und Fehler mit Grund
 *  - `_meta` des Hub-Ergebnisses (fyos/oeffnen) wandert ins `_meta` des CallToolResult
 *  - ohne `ergebnis` kein `tool-result`
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SITZUNG_FEHLER, appCall, appCsp, appEinhaengen, htmlMitCsp, nachrichtText, resource, ressourceLesen, type McpApp } from '~/lib/mcp-apps/host';
import { SITZUNG_EREIGNIS, _sitzungZuruecksetzen } from '~/lib/api/transport';
import { zustandLeeren } from '~/lib/mcp-apps/zustand';

const app = (name: string, extra: Partial<McpApp> & Record<string, unknown> = {}): McpApp =>
  ({
    tool: name.replace('__', '.'),
    name,
    description: 'Haus',
    inputSchema: {},
    _meta: { ui: { resourceUri: 'ui://fyos/haus.html' } },
    scope: 'READ',
    ...extra,
  }) as McpApp;

const HAUS = app('haus__favoriten');
const LISTE: McpApp[] = [
  HAUS,
  app('haus__geraete', { _meta: { ui: { resourceUri: 'ui://fyos/haus.html', visibility: ['app'] } } }),
  app('haus__nur_modell', { _meta: { ui: { resourceUri: 'ui://fyos/haus.html', visibility: ['model'] } } }),
];

const antwort = (x: unknown, init?: ResponseInit) => new Response(JSON.stringify(x), init);
let aufrufe: { name: string; arguments: Record<string, unknown> }[];
let ressource: { ok: boolean; text?: string; _meta?: unknown };
let hubApps: McpApp[];
let appCallErgebnis: unknown;
const abmeldungen: (() => void)[] = [];

beforeEach(() => {
  aufrufe = [];
  hubApps = LISTE;
  ressource = { ok: true, text: '<html><head><title>x</title></head><body>hallo</body></html>' };
  appCallErgebnis = { ok: 1 };
  zustandLeeren();
  _sitzungZuruecksetzen(); // das Ereignis kommt einmal je Seitenleben
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/hub-api/apps')) return antwort({ apps: hubApps });
      if (u.includes('/hub-api/resource')) return antwort(ressource);
      if (u.endsWith('/hub-api/app-call')) {
        aufrufe.push(JSON.parse(String(init?.body)));
        return antwort({ ok: true, result: appCallErgebnis });
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

async function einhaengen(a: McpApp, opt: Partial<Parameters<typeof appEinhaengen>[1]> = {}) {
  const f = document.createElement('iframe');
  document.body.appendChild(f);
  const antworten: { id?: number | string; method?: string; params?: unknown; result?: Record<string, unknown>; error?: { message: string } }[] = [];
  const ab = await appEinhaengen(f, { app: a, args: { x: 1 }, ergebnis: { content: [] }, theme: () => 'dark', ...opt });
  abmeldungen.push(ab);
  vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
    antworten.push(m as (typeof antworten)[number]);
  });
  const sprechen = (method: string, params: unknown, id?: number) =>
    window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: { jsonrpc: '2.0', ...(id != null ? { id } : {}), method, params } }));
  const auf = (id: number) => vi.waitFor(() => expect(antworten.find((x) => x.id === id)).toBeTruthy()).then(() => antworten.find((x) => x.id === id)!);
  /** Eine Runde warten, damit eine ausbleibende Antwort auch wirklich ausgeblieben ist */
  const ruhe = () => new Promise((fertig) => setTimeout(fertig, 20));
  return { f, antworten, sprechen, auf, ruhe, ab };
}

// ── Inhaltsregeln ───────────────────────────────────────────────────────────────────────────────

describe('appCsp', () => {
  it('schließt standardmäßig alles, was die Apps nicht brauchen', () => {
    const c = appCsp();
    expect(c).toContain("default-src 'none'");
    expect(c).toContain("script-src 'unsafe-inline'");
    expect(c).toContain("connect-src 'none'");
    expect(c).toContain("frame-src 'none'");
    expect(c).toContain("base-uri 'none'");
    expect(c).toContain("form-action 'none'");
    expect(c).toContain('img-src data: blob: https:');
    expect(c).not.toMatch(/unsafe-eval/);
  });

  it('nimmt Quellen aus _meta.ui.csp auf', () => {
    const c = appCsp({ ui: { csp: { connectDomains: ['https://api.example.com', 'wss://live.example.com:8443'], resourceDomains: ['https://*.cdn.example.com'], frameDomains: ['https://karte.example.com'], baseUriDomains: ['https://example.com'] } } });
    expect(c).toContain('connect-src https://api.example.com wss://live.example.com:8443');
    expect(c).toContain("script-src 'unsafe-inline' https://*.cdn.example.com");
    expect(c).toContain('style-src \'unsafe-inline\' https://*.cdn.example.com');
    expect(c).toContain('font-src data: https://*.cdn.example.com');
    expect(c).toContain('frame-src https://karte.example.com');
    expect(c).toContain('base-uri https://example.com');
  });

  it('lässt alles weg, was die Regel verlassen oder aufweichen könnte', () => {
    const boese = ["'unsafe-eval'", '*', 'https://a.example; script-src *', 'https://x.example\n', 'javascript:alert(1)', 'data:', 'https://', 'http://-x.example', 42, null, { a: 1 }];
    const c = appCsp({ ui: { csp: { connectDomains: boese, resourceDomains: boese, frameDomains: boese, baseUriDomains: boese } } });
    expect(c).toContain("connect-src 'none'");
    expect(c).toContain("frame-src 'none'");
    expect(c).toContain("base-uri 'none'");
    expect(c).not.toContain('unsafe-eval');
    expect(c).not.toContain('javascript:');
    expect(c.split(';').filter((t) => /script-src/.test(t))).toHaveLength(1); // kein eingeschleustes zweites script-src
    expect(c).toContain("script-src 'unsafe-inline'");
    expect(c).not.toMatch(/script-src[^;]*\*/);
  });

  it('kommt mit Unsinn als _meta zurecht', () => {
    for (const meta of [null, 'x', 3, [], { ui: null }, { ui: { csp: 'x' } }, { ui: { csp: { connectDomains: 'https://a.example' } } }]) {
      expect(appCsp(meta)).toContain("connect-src 'none'");
    }
  });
});

describe('htmlMitCsp', () => {
  const csp = "default-src 'none'";
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`;

  it('setzt die Regel als erstes Element in den <head>', () => {
    expect(htmlMitCsp('<!doctype html><html><head><title>x</title></head><body></body></html>', csp)).toBe(
      `<!doctype html><html><head>${meta}<title>x</title></head><body></body></html>`,
    );
    expect(htmlMitCsp('<head lang="de"><script>1</script></head>', csp)).toBe(`<head lang="de">${meta}<script>1</script></head>`);
  });

  it('legt einen <head> an, wenn keiner da ist — vor dem Inhalt', () => {
    const r = htmlMitCsp('<!DOCTYPE html><html><body><script>1</script></body></html>', csp);
    expect(r).toBe(`<!DOCTYPE html><html><head>${meta}</head><body><script>1</script></body></html>`);
    expect(htmlMitCsp('<p>nur ein Absatz</p><script>1</script>', csp)).toBe(`<head>${meta}</head><p>nur ein Absatz</p><script>1</script>`);
    expect(htmlMitCsp('', csp)).toBe(`<head>${meta}</head>`);
  });

  it('verwechselt <header> nicht mit <head>', () => {
    const r = htmlMitCsp('<html><body><header>x</header></body></html>', csp);
    expect(r.indexOf('Content-Security-Policy')).toBeLessThan(r.indexOf('<header>'));
    expect(r).toBe(`<html><head>${meta}</head><body><header>x</header></body></html>`);
  });
});

describe('Ressource im srcdoc', () => {
  it('trägt die Inhaltsregeln als erstes Element im <head>', async () => {
    const h = await einhaengen(HAUS);
    const doc = h.f.srcdoc;
    expect(doc).toContain('http-equiv="Content-Security-Policy"');
    expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('<title>'));
    expect(doc).toContain("connect-src 'none'");
    expect(h.f.getAttribute('sandbox')).toBe('allow-scripts allow-forms');
  });

  it('übernimmt _meta.ui.csp der Ressource', async () => {
    ressource = { ok: true, text: '<html><head></head><body></body></html>', _meta: { ui: { csp: { connectDomains: ['https://api.example.com'] } } } };
    const h = await einhaengen(HAUS);
    expect(h.f.srcdoc).toContain('connect-src https://api.example.com');
  });

  it('ressourceLesen liefert Text und _meta; resource nur den Text', async () => {
    ressource = { ok: true, text: '<p>x</p>', _meta: { ui: { csp: {} } } };
    expect(await ressourceLesen('ui://fyos/haus.html')).toEqual({ text: '<p>x</p>', meta: { ui: { csp: {} } } });
    expect(await resource('ui://fyos/haus.html')).toBe('<p>x</p>');
  });
});

// ── tools/call und Sichtbarkeit ─────────────────────────────────────────────────────────────────

describe('tools/call', () => {
  it('ruft ein Werkzeug, das für Apps sichtbar ist (auch eines nur für die App)', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('tools/call', { name: 'haus__geraete', arguments: { raum: 'Küche' } }, 1);
    expect(await h.auf(1)).toMatchObject({ result: { structuredContent: { ok: 1 } } });
    expect(aufrufe).toEqual([{ name: 'haus__geraete', arguments: { raum: 'Küche' } }]);
  });

  it('lehnt ein Werkzeug ab, das nur für das Modell gedacht ist', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('tools/call', { name: 'haus__nur_modell', arguments: {} }, 2);
    const r = await h.auf(2);
    expect(r.error?.message).toMatch(/nur für das Modell/);
    expect(aufrufe).toHaveLength(0);
  });

  it('lehnt ein Werkzeug ab, das der Hub nicht kennt — nach einmaligem Neuladen der Liste', async () => {
    const h = await einhaengen(HAUS);
    const f = vi.mocked(fetch);
    const vorher = f.mock.calls.filter((c) => String(c[0]).endsWith('/hub-api/apps')).length;
    h.sprechen('tools/call', { name: 'haus__gibtsnicht', arguments: {} }, 3);
    expect((await h.auf(3)).error?.message).toMatch(/kennt der Hub nicht/);
    expect(f.mock.calls.filter((c) => String(c[0]).endsWith('/hub-api/apps')).length).toBe(vorher + 1);
    expect(aufrufe).toHaveLength(0);
  });

  it('findet ein neues Werkzeug nach dem Neuladen der Liste', async () => {
    const h = await einhaengen(HAUS);
    hubApps = [...LISTE, app('haus__neu')];
    h.sprechen('tools/call', { name: 'haus__neu', arguments: {} }, 4);
    expect(await h.auf(4)).toMatchObject({ result: { structuredContent: { ok: 1 } } });
  });

  it('lehnt Werkzeuge anderer Plugins ab', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('tools/call', { name: 'konten__uebersicht', arguments: {} }, 5);
    expect((await h.auf(5)).error?.message).toMatch(/gehört nicht zu dieser App/);
    expect(aufrufe).toHaveLength(0);
  });
});

// ── Anfragen ohne id ────────────────────────────────────────────────────────────────────────────

describe('Anfragen ohne id (Benachrichtigungen)', () => {
  it('tools/call ohne id löst nichts aus', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('tools/call', { name: 'haus__geraete', arguments: {} });
    await h.ruhe();
    expect(aufrufe).toHaveLength(0);
    expect(h.antworten).toHaveLength(0);
  });

  it('ui/open-link und ui/message ohne id lösen nichts aus', async () => {
    const tab = vi.spyOn(window, 'open').mockImplementation(() => null);
    const onMessage = vi.fn();
    const h = await einhaengen(HAUS, { onMessage });
    h.sprechen('ui/open-link', { url: 'https://example.com/' });
    h.sprechen('ui/message', { role: 'user', content: { type: 'text', text: 'hallo' } });
    await h.ruhe();
    expect(tab).not.toHaveBeenCalled();
    expect(onMessage).not.toHaveBeenCalled();
    expect(h.antworten).toHaveLength(0);
  });

  it('ui/initialize ohne id bleibt unbeantwortet; eine unbekannte Benachrichtigung bekommt keinen Fehler', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' });
    h.sprechen('gibt/es/nicht', {});
    await h.ruhe();
    expect(h.antworten).toHaveLength(0);
  });

  it('eine unbekannte Anfrage mit id bekommt einen Fehler', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('gibt/es/nicht', {}, 9);
    expect((await h.auf(9)).error?.message).toMatch(/nicht unterstützt/);
  });
});

// ── ui/message ──────────────────────────────────────────────────────────────────────────────────

describe('ui/message', () => {
  const text = (t: string) => ({ role: 'user', content: { type: 'text', text: t } });

  it('ohne Einbetter keine Fähigkeit „message“ und die Anfrage wird abgelehnt', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    expect((await h.auf(1)).result!.hostCapabilities).not.toHaveProperty('message');
    h.sprechen('ui/message', text('hallo'), 2);
    expect(await h.auf(2)).toMatchObject({ result: { isError: true } });
  });

  it('mit Einbetter: Fähigkeit gemeldet, Text weitergegeben, Antwort leer', async () => {
    const onMessage = vi.fn();
    const h = await einhaengen(HAUS, { onMessage });
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    expect((await h.auf(1)).result!.hostCapabilities).toHaveProperty('message');
    h.sprechen('ui/message', text('Was ist mit dem Licht?'), 2);
    expect(await h.auf(2)).toMatchObject({ result: {} });
    expect((await h.auf(2)).result).not.toHaveProperty('isError');
    expect(onMessage).toHaveBeenCalledWith('Was ist mit dem Licht?');
  });

  it('lehnt leere Nachrichten und solche ohne Geste ab', async () => {
    const onMessage = vi.fn();
    const h = await einhaengen(HAUS, { onMessage });
    h.sprechen('ui/message', text('   '), 3);
    expect(await h.auf(3)).toMatchObject({ result: { isError: true } });
    vi.stubGlobal('navigator', { userActivation: { isActive: false } });
    h.sprechen('ui/message', text('hallo'), 4);
    expect(await h.auf(4)).toMatchObject({ result: { isError: true } });
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('nachrichtText nimmt einen Block oder eine Liste und kürzt auf 4000 Zeichen', () => {
    expect(nachrichtText({ type: 'text', text: ' a ' })).toBe('a');
    expect(nachrichtText([{ type: 'text', text: 'a' }, { type: 'image', data: 'x' }, { type: 'text', text: 'b' }])).toBe('a\nb');
    expect(nachrichtText({ type: 'text', text: 'x'.repeat(5000) })).toHaveLength(4000);
    expect(nachrichtText(null)).toBe('');
    expect(nachrichtText('nur ein String')).toBe('');
  });
});

// ── Größe, Abbau, tool-result ───────────────────────────────────────────────────────────────────

describe('size-changed', () => {
  it('gibt endliche Höhen begrenzt weiter und ignoriert NaN, Unendlich und Texte', async () => {
    const onHeight = vi.fn();
    const h = await einhaengen(HAUS, { onHeight });
    h.sprechen('ui/notifications/size-changed', { height: 300 });
    h.sprechen('ui/notifications/size-changed', { height: 5 });
    h.sprechen('ui/notifications/size-changed', { height: Number.NaN });
    h.sprechen('ui/notifications/size-changed', { height: Number.POSITIVE_INFINITY });
    h.sprechen('ui/notifications/size-changed', { height: '400' });
    expect(onHeight.mock.calls.map((c) => c[0])).toEqual([300, 120]);
  });
});

describe('Abbau', () => {
  it('schickt ui/resource-teardown beim Abmelden, ohne zu warten', async () => {
    const h = await einhaengen(HAUS);
    h.ab();
    expect(h.antworten.find((x) => x.method === 'ui/resource-teardown')).toMatchObject({ id: 'abbau', params: {} });
    // danach hört der Host nicht mehr zu
    h.sprechen('tools/call', { name: 'haus__geraete', arguments: {} }, 7);
    await h.ruhe();
    expect(aufrufe).toHaveLength(0);
  });
});

describe('tool-result', () => {
  it('kommt nach initialized mit dem Ergebnis des Starts', async () => {
    const ergebnis = { content: [{ type: 'text' as const, text: '{"a":1}' }], structuredContent: { a: 1 } };
    const h = await einhaengen(HAUS, { ergebnis });
    h.sprechen('ui/notifications/initialized', {});
    await vi.waitFor(() => expect(h.antworten.map((x) => x.method)).toEqual(['ui/notifications/tool-input', 'ui/notifications/tool-result']));
    expect(h.antworten[1]!.params).toEqual(ergebnis);
  });

  it('entfällt ganz, wenn es kein Ergebnis gibt: die App bekommt nur tool-input und holt ihre Daten selbst', async () => {
    const h = await einhaengen(HAUS, { ergebnis: undefined });
    h.sprechen('ui/notifications/initialized', {});
    await vi.waitFor(() => expect(h.antworten.map((x) => x.method)).toContain('ui/notifications/tool-input'));
    await h.ruhe();
    expect(h.antworten.map((x) => x.method)).not.toContain('ui/notifications/tool-result');
  });
});

// ── Anmeldung und _meta ─────────────────────────────────────────────────────────────────────────

describe('abgelaufene Anmeldung', () => {
  const opaque = () => ({ type: 'opaqueredirect', status: 0, ok: false, headers: new Headers(), json: async () => ({}) }) as unknown as Response;
  const ereignisse = () => {
    const f = vi.fn();
    window.addEventListener(SITZUNG_EREIGNIS, f);
    abmeldungen.push(() => window.removeEventListener(SITZUNG_EREIGNIS, f));
    return f;
  };

  it('eine Umleitung zur Anmeldung meldet das Ereignis und wirft einen Fehler mit Grund', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => opaque()));
    const f = ereignisse();
    await expect(resource('ui://fyos/haus.html')).rejects.toThrow(SITZUNG_FEHLER);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('ein 401 und eine HTML-Antwort zählen ebenso (das Ereignis kommt einmal je Seitenleben)', async () => {
    const f = ereignisse();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 401 })));
    await expect(appCall('haus__favoriten', {})).rejects.toThrow(SITZUNG_FEHLER);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Anmelden</html>', { headers: { 'content-type': 'text/html; charset=utf-8' } })));
    await expect(ressourceLesen('ui://x')).rejects.toThrow(SITZUNG_FEHLER);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it('die App bekommt bei tools/call den Grund statt eines stillen Fehlschlags', async () => {
    const h = await einhaengen(HAUS);
    vi.stubGlobal('fetch', vi.fn(async () => opaque()));
    ereignisse();
    h.sprechen('tools/call', { name: 'haus__geraete', arguments: {} }, 8);
    expect((await h.auf(8)).error?.message).toBe(SITZUNG_FEHLER);
  });

  it('eine Antwort, die kein JSON ist, ist ein Fehler und keine leere Ressource', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('kaputt', { status: 502 })));
    await expect(ressourceLesen('ui://x')).rejects.toThrow(/HTTP 502/);
  });
});

describe('appCall und _meta', () => {
  it('legt _meta des Hub-Ergebnisses ins _meta des CallToolResult und aus den Daten heraus', async () => {
    appCallErgebnis = { ok: 1, zahl: 3, _meta: { 'fyos/oeffnen': { link: 'https://fyos.example/os/?offen=app:haus__favoriten' } } };
    const r = await appCall('haus__favoriten', {});
    expect(r._meta).toEqual({ 'fyos/oeffnen': { link: 'https://fyos.example/os/?offen=app:haus__favoriten' } });
    expect(r.structuredContent).toEqual({ ok: 1, zahl: 3 });
    expect(r.content[0]!.text).not.toContain('fyos/oeffnen');
  });

  it('ohne _meta bleibt das Ergebnis, wie es war; ein Hub-Fehler wird zu isError', async () => {
    const r = await appCall('haus__favoriten', {});
    expect(r).not.toHaveProperty('_meta');
    expect(r.structuredContent).toEqual({ ok: 1 });
    vi.stubGlobal('fetch', vi.fn(async () => antwort({ ok: false, error: 'Boom' })));
    expect(await appCall('haus__favoriten', {})).toMatchObject({ isError: true, content: [{ text: 'Boom' }] });
  });
});
