/**
 * MCP-Apps-Host — Übergänge:
 *  - `hostInfo.name` ist `fyos-web` (Apps zeigen „In FYOS öffnen" nur bei anderen Hosts)
 *  - `ui/open-link` mit einer Adresse von fyos öffnet ein Fenster im OS (Ereignis `fyos:oeffnen`), nie einen Tab;
 *    fremde Adressen und Seiten ohne OS öffnen wie bisher einen Tab; alles andere nichts
 *  - der Host merkt sich je Einbettung die Eingabe der Ansicht (nur lesende Aufrufe) und den Modellkontext
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HOEHE_MAX, HOST_NAME, apps, appEinhaengen, containerMasse, kanteOben, obenVerdeckt, type McpApp } from '~/lib/mcp-apps/host';
import { zustandLeeren, zustandVon } from '~/lib/mcp-apps/zustand';
import { OEFFNEN, eingabeKodieren, oeffentlicherUrsprungSetzen, type OsZiel } from '~/lib/os/oeffnen';

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
  app('haus__szenen'),
  app('haus__geraete', { _meta: { ui: { resourceUri: 'ui://fyos/haus.html', visibility: ['app'] } } }), // lesend, aber nur für die App
  app('haus__schalten', { scope: 'WRITE', _meta: { ui: { resourceUri: 'ui://fyos/haus.html', visibility: ['app'] } } }),
  app('haus__kaputt'),
  app('haus__andere_ansicht', { _meta: { ui: { resourceUri: 'ui://fyos/andere.html' } } }),
];

const antwort = (x: unknown) => new Response(JSON.stringify(x));
let aufrufe: { name: string; arguments: Record<string, unknown> }[];
const abmeldungen: (() => void)[] = [];

beforeEach(() => {
  aufrufe = [];
  zustandLeeren();
  oeffentlicherUrsprungSetzen('https://fyos.example');
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/hub-api/apps')) return antwort({ apps: LISTE });
      if (u.includes('/hub-api/resource')) return antwort({ ok: true, text: '<p>x</p>' });
      if (u.endsWith('/hub-api/app-call')) {
        const body = JSON.parse(String(init?.body)) as { name: string; arguments: Record<string, unknown> };
        aufrufe.push(body);
        if (body.name === 'haus__kaputt') return antwort({ ok: false, error: 'Boom' });
        return antwort({ ok: true, result: { ok: 1 } });
      }
      return new Response('{}', { status: 404 });
    }),
  );
});
afterEach(() => {
  oeffentlicherUrsprungSetzen(null);
  while (abmeldungen.length) abmeldungen.pop()!();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Hängt eine App ein und gibt Mittel zurück, um als App zu sprechen und mitzulesen, was der Host antwortet. */
async function einhaengen(a: McpApp, opt: Partial<Parameters<typeof appEinhaengen>[1]> = {}) {
  const f = document.createElement('iframe');
  document.body.appendChild(f);
  const antworten: { id?: number; result?: Record<string, unknown>; error?: { message: string } }[] = [];
  const ab = await appEinhaengen(f, { app: a, args: {}, ergebnis: { content: [] }, theme: () => 'dark', ...opt });
  abmeldungen.push(ab);
  vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
    antworten.push(m as (typeof antworten)[number]);
  });
  const sprechen = (method: string, params: unknown, id?: number) =>
    window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: { jsonrpc: '2.0', ...(id != null ? { id } : {}), method, params } }));
  const auf = (id: number) => vi.waitFor(() => expect(antworten.find((x) => x.id === id)).toBeTruthy()).then(() => antworten.find((x) => x.id === id)!);
  return { f, antworten, sprechen, auf };
}

describe('hostInfo', () => {
  it('stellt sich als „fyos-web" vor', async () => {
    expect(HOST_NAME).toBe('fyos-web');
    const h = await einhaengen(HAUS);
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    const r = (await h.auf(1)).result as { hostInfo: { name: string }; hostCapabilities: Record<string, unknown> };
    expect(r.hostInfo.name).toBe('fyos-web');
    expect(r.hostCapabilities).toHaveProperty('openLinks'); // Apps dürfen ui/open-link benutzen
  });
});

describe('containerDimensions', () => {
  it('im Fenster feste Höhe, sonst Breite und Obergrenze', () => {
    expect(containerMasse(380.4, 260.6, true)).toEqual({ width: 380, height: 261 });
    expect(containerMasse(640, 120, false)).toEqual({ width: 640, maxHeight: HOEHE_MAX });
    expect(containerMasse(640, 0, true)).toEqual({ width: 640, maxHeight: HOEHE_MAX }); // noch ohne Höhe: nichts Festes behaupten
  });

  it('meldet die Größe des Rahmens beim Start mit', async () => {
    const f0 = HTMLIFrameElement.prototype;
    const breite = vi.spyOn(f0, 'clientWidth', 'get').mockReturnValue(520);
    const hoehe = vi.spyOn(f0, 'clientHeight', 'get').mockReturnValue(440);
    const h = await einhaengen(HAUS, { fuellen: true });
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    const r = (await h.auf(1)).result as { hostContext: Record<string, unknown> };
    expect(r.hostContext.containerDimensions).toEqual({ width: 520, height: 440 });
    expect(r.hostContext.platform).toBe('web');
    breite.mockRestore();
    hoehe.mockRestore();
  });
});

describe('Sichtbarer Ausschnitt für klebende Köpfe', () => {
  const rechteck = (top: number, height: number) => ({ top, bottom: top + height, height, left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

  it('rechnet unter dem klebenden Fensterkopf, nicht unter dem Rand der Fläche', () => {
    const fl = document.createElement('div');
    fl.innerHTML = '<section data-fenster="a"><header class="os-kopf"></header><div><iframe></iframe></div></section>';
    document.body.appendChild(fl);
    const f = fl.querySelector('iframe')!;
    vi.spyOn(fl, 'getBoundingClientRect').mockReturnValue(rechteck(50, 900));
    vi.spyOn(fl.querySelector('.os-kopf')!, 'getBoundingClientRect').mockReturnValue(rechteck(50, 40));
    const r = vi.spyOn(f, 'getBoundingClientRect').mockReturnValue(rechteck(200, 600));
    expect(kanteOben(f, fl)).toBe(90);
    expect(obenVerdeckt(f, fl)).toBe(0); // Anfang zu sehen
    r.mockReturnValue(rechteck(-110, 600));
    expect(obenVerdeckt(f, fl)).toBe(200); // 90 − (−110)
    r.mockReturnValue(rechteck(-900, 600));
    expect(obenVerdeckt(f, fl)).toBe(600); // ganz weg: höchstens die eigene Höhe
  });

  it('meldet fyos/sichtbar nach dem Start und beim Bildlauf, aber nur bei Änderung', async () => {
    const h = await einhaengen(HAUS, { sichtbar: true });
    const r = vi.spyOn(h.f, 'getBoundingClientRect').mockReturnValue(rechteck(-120, 800));
    const meldungen = () => h.antworten.filter((x) => (x as { method?: string }).method === 'fyos/sichtbar') as unknown as { params: { oben: number } }[];
    h.sprechen('ui/notifications/initialized', {});
    await vi.waitFor(() => expect(meldungen().map((m) => m.params.oben)).toEqual([120]));
    window.dispatchEvent(new Event('scroll'));
    await new Promise((fertig) => requestAnimationFrame(() => fertig(null)));
    expect(meldungen()).toHaveLength(1); // nichts bewegt: keine neue Meldung
    r.mockReturnValue(rechteck(-300, 800));
    window.dispatchEvent(new Event('scroll'));
    await vi.waitFor(() => expect(meldungen().map((m) => m.params.oben)).toEqual([120, 300]));
  });

  it('ohne sichtbar bleibt es still', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('ui/notifications/initialized', {});
    window.dispatchEvent(new Event('scroll'));
    await new Promise((fertig) => requestAnimationFrame(() => fertig(null)));
    expect(h.antworten.some((x) => (x as { method?: string }).method === 'fyos/sichtbar')).toBe(false);
  });
});

describe('ui/open-link', () => {
  let tab: ReturnType<typeof vi.fn>;
  let gesehen: OsZiel[];
  let uebernimmt: boolean;
  const hoerer = (e: Event) => {
    gesehen.push((e as CustomEvent<OsZiel>).detail);
    if (uebernimmt) e.preventDefault();
  };
  beforeEach(() => {
    tab = vi.fn();
    vi.stubGlobal('open', tab);
    gesehen = [];
    uebernimmt = true;
    window.addEventListener(OEFFNEN, hoerer);
  });
  afterEach(() => window.removeEventListener(OEFFNEN, hoerer));

  it('öffnet eine Adresse von fyos als Fenster im OS, mit der Eingabe, und keinen Tab', async () => {
    const h = await einhaengen(HAUS);
    const e = eingabeKodieren({ raum: 'Küche' });
    h.sprechen('ui/open-link', { url: `https://fyos.example/os?offen=app:haus__szenen&eingabe=${e}` }, 5);
    expect(await h.auf(5)).toMatchObject({ result: {} });
    expect(gesehen).toEqual([{ ziel: 'app:haus__szenen', eingabe: { raum: 'Küche' } }]);
    expect(tab).not.toHaveBeenCalled();
  });

  it('öffnet auch eine Seite von fyos im OS (Pfad als Ziel)', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('ui/open-link', { url: `${location.origin}/finance/` }, 6);
    await h.auf(6);
    expect(gesehen).toEqual([{ ziel: '/finance' }]);
    expect(tab).not.toHaveBeenCalled();
  });

  it('öffnet einen Tab, wenn hier kein OS läuft (niemand übernimmt)', async () => {
    uebernimmt = false;
    const h = await einhaengen(HAUS);
    const url = 'https://fyos.example/os?offen=app:haus__szenen';
    h.sprechen('ui/open-link', { url }, 7);
    await h.auf(7);
    expect(gesehen).toHaveLength(1);
    expect(tab).toHaveBeenCalledWith(url, '_blank', 'noopener');
  });

  it('öffnet fremde Adressen wie bisher in einem neuen Tab — ohne das OS zu fragen', async () => {
    const h = await einhaengen(HAUS);
    h.sprechen('ui/open-link', { url: 'https://example.com/seite?x=1' }, 8);
    await h.auf(8);
    expect(gesehen).toEqual([]);
    expect(tab).toHaveBeenCalledWith('https://example.com/seite?x=1', '_blank', 'noopener');
  });

  it('öffnet nichts bei Adressen, die keine Webadressen sind, und sagt der App, dass es abgelehnt wurde', async () => {
    const h = await einhaengen(HAUS);
    for (const [i, url] of ['javascript:alert(1)', 'data:text/html,<b>x</b>', 'mailto:max@example.com', ''].entries()) {
      h.sprechen('ui/open-link', { url }, 20 + i);
      expect(await h.auf(20 + i)).toMatchObject({ result: { isError: true } });
    }
    expect(gesehen).toEqual([]);
    expect(tab).not.toHaveBeenCalled();
  });

  describe('ohne Nutzergeste', () => {
    const ohneGeste = () => vi.stubGlobal('navigator', { userActivation: { isActive: false } });

    it('öffnet keinen fremden Tab und antwortet mit isError', async () => {
      const h = await einhaengen(HAUS);
      ohneGeste();
      h.sprechen('ui/open-link', { url: 'https://example.com/' }, 40);
      expect(await h.auf(40)).toMatchObject({ result: { isError: true } });
      expect(tab).not.toHaveBeenCalled();
    });

    it('öffnet eine Adresse von fyos trotzdem im OS (kein Tab, nichts Aufpoppendes)', async () => {
      const h = await einhaengen(HAUS);
      ohneGeste();
      h.sprechen('ui/open-link', { url: 'https://fyos.example/os?offen=app:haus__szenen' }, 41);
      expect(await h.auf(41)).toMatchObject({ result: {} });
      expect(gesehen).toHaveLength(1);
    });

    it('mit Geste öffnet der Tab', async () => {
      const h = await einhaengen(HAUS);
      vi.stubGlobal('navigator', { userActivation: { isActive: true } });
      h.sprechen('ui/open-link', { url: 'https://example.com/' }, 42);
      expect(await h.auf(42)).toMatchObject({ result: {} });
      expect(tab).toHaveBeenCalledWith('https://example.com/', '_blank', 'noopener');
    });
  });
});

describe('Zustand der Ansicht (für „Link kopieren" und „Agent fragen")', () => {
  const SCHLUESSEL = 'app:haus__favoriten';

  it('merkt die Eingabe, mit der die lesende App gestartet wurde', async () => {
    await einhaengen(HAUS, { schluessel: SCHLUESSEL, args: { raum: 'Küche' } });
    expect(zustandVon(SCHLUESSEL)).toMatchObject({ werkzeug: 'haus__favoriten', eingabe: { raum: 'Küche' } });
  });

  it('merkt von einer schreibenden App keine Eingabe (nie in einen Link)', async () => {
    await einhaengen(app('haus__schalten', { scope: 'WRITE' }), { schluessel: 'app:haus__schalten', args: { an: true } });
    expect(zustandVon('app:haus__schalten').werkzeug).toBeUndefined();
    expect(zustandVon('app:haus__schalten').eingabe).toBeUndefined();
  });

  it('ohne Schlüssel merkt der Host nichts', async () => {
    const h = await einhaengen(HAUS, { args: { raum: 'Küche' } });
    h.sprechen('ui/update-model-context', { content: [{ type: 'text', text: 'x' }] }, 1);
    await h.auf(1);
    expect(zustandVon(SCHLUESSEL)).toEqual({});
  });

  it('übernimmt lesende Aufrufe der App an Werkzeuge derselben Oberfläche als neue Ansicht', async () => {
    await apps(false); // der Host weiß dann, welche Werkzeuge lesen
    const h = await einhaengen(HAUS, { schluessel: SCHLUESSEL });
    h.sprechen('tools/call', { name: 'haus__szenen', arguments: { raum: 'Bad' } }, 2);
    await h.auf(2);
    expect(zustandVon(SCHLUESSEL)).toMatchObject({ werkzeug: 'haus__szenen', eingabe: { raum: 'Bad' } });
  });

  it('übernimmt keine schreibenden, keine nur für die App sichtbaren, keine fremden und keine gescheiterten Aufrufe', async () => {
    await apps(false);
    const h = await einhaengen(HAUS, { schluessel: SCHLUESSEL, args: { raum: 'Küche' } });
    const nachher = () => zustandVon(SCHLUESSEL);
    let id = 30;
    for (const name of ['haus__schalten', 'haus__geraete', 'haus__andere_ansicht', 'haus__kaputt']) {
      h.sprechen('tools/call', { name, arguments: { was: name } }, ++id);
      await h.auf(id);
      expect(nachher()).toMatchObject({ werkzeug: 'haus__favoriten', eingabe: { raum: 'Küche' } }); // unverändert
    }
    // ein Werkzeug, das der Hub nicht kennt, ruft der Host gar nicht erst
    h.sprechen('tools/call', { name: 'haus__unbekannt', arguments: {} }, 99);
    expect(await h.auf(99)).toMatchObject({ error: { message: expect.stringContaining('kennt der Hub nicht') } });
    expect(aufrufe.map((a) => a.name)).toEqual(['haus__schalten', 'haus__geraete', 'haus__andere_ansicht', 'haus__kaputt']);
  });

  it('merkt den Modellkontext, den die App meldet', async () => {
    const h = await einhaengen(HAUS, { schluessel: SCHLUESSEL });
    const kontext = { content: [{ type: 'text', text: 'Küche: 3 Lichter an' }], structuredContent: { an: 3 } };
    h.sprechen('ui/update-model-context', kontext, 3);
    expect(await h.auf(3)).toMatchObject({ result: {} });
    expect(zustandVon(SCHLUESSEL).modellKontext).toEqual(kontext);
  });

  it('beginnt eine neue Einbettung mit leerem Modellkontext (kein Rest vom Fenster davor)', async () => {
    const h = await einhaengen(HAUS, { schluessel: SCHLUESSEL });
    h.sprechen('ui/update-model-context', { content: [] }, 4);
    await h.auf(4);
    expect(zustandVon(SCHLUESSEL).modellKontext).toBeDefined();
    await einhaengen(HAUS, { schluessel: SCHLUESSEL });
    expect(zustandVon(SCHLUESSEL).modellKontext).toBeUndefined();
  });
});
