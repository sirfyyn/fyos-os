/**
 * Apps in Fenstern bieten eigene Seitenwerkzeuge an:
 *  - Einheit: Name mit Präfix, Prüfung des Angebots, Register/Brücke/WebMCP, Abmelden, Frist, Schreibwächter
 *  - Strecke: die ECHTE hub/mcp_hub/plugins/ui/_bruecke.js (App.werkzeug, App.beantragen) gegen den echten Host
 *    (`appEinhaengen`): Anmelden mit Präfix, Aufruf aus der Brücke, Abmelden beim Schließen des Fensters,
 *    Bestätigungspflicht für Schreibendes. Kennt die _bruecke.js im Hub das noch nicht, wird die Strecke übersprungen.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  APP_WERKZEUGE_MAX,
  NACHLAUF_MS,
  angebotPruefen,
  appWerkzeugName,
  appWerkzeugeFuer,
  ergebnisSauber,
} from '~/lib/mcp-apps/app-werkzeuge';
import { appEinhaengen, type McpApp } from '~/lib/mcp-apps/host';
import { _sitzungZuruecksetzen } from '~/lib/api/transport';
import { zustandLeeren } from '~/lib/mcp-apps/zustand';
import { fuerBruecke, liste, rufen, rufenFuerBruecke } from '~/lib/werkzeuge';

const SCHEMA = { type: 'object', properties: { eintrag: { type: 'string' } } };

afterEach(() => {
  delete (document as unknown as { modelContext?: unknown }).modelContext;
});

// ── Einheit ──────────────────────────────────────────────────────────────────────────────────

describe('appWerkzeugName', () => {
  it('setzt das Präfix des Plugins davor und doppelt es nicht', () => {
    expect(appWerkzeugName('notizen', 'eintrag_zeigen')).toBe('notizen_eintrag_zeigen');
    expect(appWerkzeugName('notizen', 'notizen_eintrag_zeigen')).toBe('notizen_eintrag_zeigen');
  });
  it('lehnt Namen ab, die kein Werkzeugname sind', () => {
    for (const n of ['', 'Eintrag', '1eintrag', 'eintrag zeigen', 'eintrag-zeigen', 'a'.repeat(41), '../x']) expect(appWerkzeugName('notizen', n)).toBeNull();
    expect(appWerkzeugName('Notizen', 'x')).toBeNull();
    expect(appWerkzeugName('', 'x')).toBeNull();
  });
});

describe('angebotPruefen', () => {
  it('nimmt ein vollständiges Angebot', () => {
    const r = angebotPruefen('notizen', { name: 'eintrag_zeigen', beschreibung: ' Zeigt   einen Eintrag. ', eingabe: SCHEMA, lesend: true });
    expect(r).toEqual({
      ok: true,
      angebot: { kurz: 'eintrag_zeigen', name: 'notizen_eintrag_zeigen', beschreibung: 'Zeigt einen Eintrag.', eingabe: SCHEMA, lesend: true },
    });
  });
  it('ohne Schema gilt ein leeres Objekt, ohne lesend gilt: verändernd', () => {
    const r = angebotPruefen('notizen', { name: 'x', beschreibung: 'y' });
    expect(r.ok && r.angebot.eingabe).toEqual({ type: 'object', properties: {} });
    expect(r.ok && r.angebot.lesend).toBe(false);
  });
  it('verlangt Name, Beschreibung und ein Objekt-Schema bis 2 KB', () => {
    expect(angebotPruefen('notizen', { name: 'Böse', beschreibung: 'x' })).toMatchObject({ ok: false });
    expect(angebotPruefen('notizen', { name: 'x', beschreibung: '  ' })).toMatchObject({ ok: false, fehler: expect.stringContaining('Beschreibung') });
    expect(angebotPruefen('notizen', { name: 'x', beschreibung: 'y', eingabe: [] })).toMatchObject({ ok: false });
    expect(angebotPruefen('notizen', { name: 'x', beschreibung: 'y', eingabe: { type: 'string' } })).toMatchObject({ ok: false });
    expect(angebotPruefen('notizen', { name: 'x', beschreibung: 'y', eingabe: { type: 'object', description: 'z'.repeat(3000) } })).toMatchObject({ ok: false, fehler: expect.stringContaining('2048') });
    expect(angebotPruefen('notizen', null)).toMatchObject({ ok: false });
  });
  it('kürzt die Beschreibung auf 300 Zeichen', () => {
    const r = angebotPruefen('notizen', { name: 'x', beschreibung: 'a'.repeat(500) });
    expect(r.ok && r.angebot.beschreibung.length).toBe(300);
  });
});

describe('ergebnisSauber', () => {
  it('lässt MCP-Ergebnisse durch, nur Textblöcke, und macht Rohdaten zu einem', () => {
    expect(ergebnisSauber({ content: [{ type: 'text', text: 'a' }, { type: 'image', data: 'x' }], isError: true })).toEqual({ content: [{ type: 'text', text: 'a' }], isError: true });
    expect(ergebnisSauber({ a: 1 }).structuredContent).toEqual({ a: 1 });
    expect(ergebnisSauber('hallo').content[0]!.text).toBe('hallo');
    expect(ergebnisSauber(undefined).content[0]!.text).toBe('null');
  });
});

describe('appWerkzeugeFuer', () => {
  const ab: (() => void)[] = [];
  afterEach(() => {
    while (ab.length) ab.pop()!();
  });
  const ort = (fenster = 'app:notizen__liste', rufenFn: (a: { name: string; voll: string; arguments: Record<string, unknown> }) => Promise<unknown> = async (a) => ({ ruf: a })) => {
    const w = appWerkzeugeFuer({ plugin: 'notizen', fenster, rufen: rufenFn });
    ab.push(() => w.alleAbmelden());
    return w;
  };

  it('meldet mit Präfix im Register an, ordnet es dem Fenster zu und ruft die App', async () => {
    const w = ort();
    expect(w.anmelden({ name: 'eintrag_zeigen', beschreibung: 'Zeigt einen Eintrag.', eingabe: SCHEMA, lesend: true })).toEqual({ ok: true, name: 'notizen_eintrag_zeigen' });
    expect(liste().find((x) => x.name === 'notizen_eintrag_zeigen')).toMatchObject({ lesend: true, beschreibung: 'Zeigt einen Eintrag.' });
    expect(fuerBruecke().find((x) => x.name === 'notizen_eintrag_zeigen')).toEqual({
      name: 'notizen_eintrag_zeigen',
      beschreibung: 'Zeigt einen Eintrag.',
      lesend: true,
      eingabe: SCHEMA,
      fenster: 'app:notizen__liste',
      app: 'notizen',
    });
    const r = await rufenFuerBruecke('notizen_eintrag_zeigen', { eintrag: 'Entwurf' });
    expect(r.structuredContent).toEqual({ ruf: { name: 'eintrag_zeigen', voll: 'notizen_eintrag_zeigen', arguments: { eintrag: 'Entwurf' } } });
  });

  it('meldet ab: einzeln, alle, und ein Unbekanntes ist kein Fehler', () => {
    const w = ort();
    w.anmelden({ name: 'a', beschreibung: 'x' });
    w.anmelden({ name: 'b', beschreibung: 'x' });
    expect(w.namen()).toEqual(['notizen_a', 'notizen_b']);
    expect(w.abmelden('a')).toBe(true);
    expect(w.abmelden('notizen_a')).toBe(false);
    expect(w.abmelden(42)).toBe(false);
    expect(liste().some((x) => x.name === 'notizen_a')).toBe(false);
    w.alleAbmelden();
    expect(liste().some((x) => x.name.startsWith('notizen_'))).toBe(false);
    expect(fuerBruecke().some((x) => x.name.startsWith('notizen_'))).toBe(false);
  });

  it('erneutes Anmelden ersetzt; derselbe Name in einem zweiten Fenster wird abgelehnt', () => {
    const eins = ort('app:notizen__liste');
    const zwei = ort('app:notizen__suche');
    expect(eins.anmelden({ name: 'a', beschreibung: 'alt' })).toMatchObject({ ok: true });
    expect(eins.anmelden({ name: 'a', beschreibung: 'neu' })).toMatchObject({ ok: true });
    expect(liste().filter((x) => x.name === 'notizen_a')).toHaveLength(1);
    expect(liste().find((x) => x.name === 'notizen_a')!.beschreibung).toBe('neu');
    expect(zwei.anmelden({ name: 'a', beschreibung: 'x' })).toMatchObject({ ok: false, fehler: expect.stringContaining('schon ein anderes') });
    eins.alleAbmelden();
    expect(zwei.anmelden({ name: 'a', beschreibung: 'x' })).toMatchObject({ ok: true });
  });

  it('begrenzt die Zahl der Werkzeuge je Fenster', () => {
    const w = ort();
    for (let i = 0; i < APP_WERKZEUGE_MAX; i++) expect(w.anmelden({ name: `w${i}`, beschreibung: 'x' })).toMatchObject({ ok: true });
    expect(w.anmelden({ name: 'zuviel', beschreibung: 'x' })).toMatchObject({ ok: false });
    expect(w.anmelden({ name: 'w0', beschreibung: 'ersetzt' })).toMatchObject({ ok: true }); // Ersetzen zählt nicht neu
  });

  it('hält WebMCP synchron: anmelden mit signal, abmelden bricht es ab', async () => {
    const aufrufe: { werkzeug: { name: string; annotations: { readOnlyHint: boolean }; execute: (a: unknown) => Promise<unknown> }; signal: AbortSignal }[] = [];
    (document as unknown as { modelContext: unknown }).modelContext = { registerTool: (werkzeug: never, o: { signal: AbortSignal }) => aufrufe.push({ werkzeug, signal: o.signal }) };
    const w = ort();
    w.anmelden({ name: 'eintrag_zeigen', beschreibung: 'Zeigt.', lesend: true });
    const e = aufrufe.find((x) => x.werkzeug.name === 'notizen_eintrag_zeigen')!;
    expect(e.werkzeug.annotations.readOnlyHint).toBe(true);
    expect(e.signal.aborted).toBe(false);
    expect(await e.werkzeug.execute({ eintrag: 'x' })).toEqual({ ruf: { name: 'eintrag_zeigen', voll: 'notizen_eintrag_zeigen', arguments: { eintrag: 'x' } } });
    w.alleAbmelden();
    expect(e.signal.aborted).toBe(true);
  });

  it('Fehler der App kommen als Fehlerergebnis zurück, nicht als Wurf', async () => {
    const w = ort('app:notizen__liste', async () => {
      throw new Error('App antwortet nicht');
    });
    w.anmelden({ name: 'a', beschreibung: 'x' });
    const r = await rufen('notizen_a', {});
    expect(r.isError).toBe(true);
    expect(r.content[0]!.text).toContain('App antwortet nicht');
  });

  describe('Schreibwächter', () => {
    it('mit Geste immer erlaubt; ohne nicht während und nicht kurz nach einem Agentenaufruf', async () => {
      let t = 1_000_000;
      let fertig!: () => void;
      const w = appWerkzeugeFuer({
        plugin: 'notizen',
        fenster: 'f',
        jetzt: () => t,
        rufen: () => new Promise((ok) => (fertig = () => ok('ok'))),
      });
      ab.push(() => w.alleAbmelden());
      expect(w.schreibenErlaubt(false)).toBe(true); // noch nie ein Agentenaufruf: die App arbeitet für sich
      w.anmelden({ name: 'a', beschreibung: 'x' });
      const lauf = rufen('notizen_a', {});
      expect(w.schreibenErlaubt(false)).toBe(false);
      expect(w.schreibenErlaubt(true)).toBe(true);
      fertig();
      await lauf;
      expect(w.schreibenErlaubt(false)).toBe(false); // Nachlauf
      expect(w.schreibenErlaubt(true)).toBe(true);
      t += NACHLAUF_MS + 1;
      expect(w.schreibenErlaubt(false)).toBe(true);
    });
  });
});

// ── Strecke: echte Brücke der App gegen den echten Host ──────────────────────────────────────

const BRUECKE_QUELLE = readFileSync(resolve(__dirname, '../../../hub/mcp_hub/plugins/ui/_bruecke.js'), 'utf8');

const mcpApp = (name: string, extra: Partial<McpApp> & Record<string, unknown> = {}): McpApp =>
  ({
    tool: name.replace('__', '.'),
    name,
    description: 'Notizen',
    inputSchema: {},
    _meta: { ui: { resourceUri: 'ui://fyos/notizen.html' } },
    scope: 'READ',
    ...extra,
  }) as McpApp;

const NOTIZEN = mcpApp('notizen__liste');
const SCHREIBEN = mcpApp('notizen__liste_setzen', { scope: 'WRITE', _meta: { ui: { resourceUri: 'ui://fyos/notizen.html', visibility: ['app'] } } });
const LESEN = mcpApp('notizen__suche', { _meta: { ui: { resourceUri: 'ui://fyos/notizen.html', visibility: ['app'] } } });

type AppApi = {
  start: (n: string) => Promise<unknown>;
  kann: (n: string) => boolean;
  werkzeug: (...a: unknown[]) => Promise<string | null>;
  werkzeugWeg: (n: string) => void;
  beantragen: (o: { frage: string }) => Promise<boolean>;
  rufen: (n: string, a?: unknown) => Promise<unknown>;
};

const KANN_WERKZEUGE = BRUECKE_QUELLE.includes('werkzeug-anmelden');

describe.skipIf(!KANN_WERKZEUGE)('Strecke App ↔ Host', () => {
  let appCalls: { name: string }[];
  const aufraeumen: (() => void)[] = [];
  const antwort = (x: unknown) => new Response(JSON.stringify(x), { headers: { 'content-type': 'application/json' } });

  beforeEach(() => {
    appCalls = [];
    zustandLeeren();
    _sitzungZuruecksetzen();
    vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        if (u.endsWith('/hub-api/apps')) return antwort({ apps: [NOTIZEN, SCHREIBEN, LESEN] });
        if (u.includes('/hub-api/resource')) return antwort({ ok: true, text: '<html><head></head><body></body></html>' });
        if (u.endsWith('/hub-api/app-call')) {
          appCalls.push(JSON.parse(String(init?.body)));
          return antwort({ ok: true, result: { ok: 1 } });
        }
        return new Response('{}', { status: 404 });
      }),
    );
  });
  afterEach(() => {
    while (aufraeumen.length) aufraeumen.pop()!();
    document.body.innerHTML = '';
    delete document.documentElement.dataset.host;
    delete (navigator as unknown as { userActivation?: unknown }).userActivation;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  /** Hängt die App ein und lässt die echte Brücke darin laufen (ohne Browser-iframe: die Brücke bekommt ein eigenes `window`). */
  async function appStarten(opt: { schluessel?: string } = {}) {
    const f = document.createElement('iframe');
    document.body.appendChild(f);
    const hoerer: ((e: { source: unknown; data: unknown }) => void)[] = [];
    const eltern = {
      postMessage: (m: unknown) => {
        window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: m }));
      },
    };
    const meinFenster = {
      parent: eltern,
      innerWidth: 800,
      matchMedia: () => ({ matches: false }),
      addEventListener: (art: string, fn: (e: { source: unknown; data: unknown }) => void) => art === 'message' && hoerer.push(fn),
      removeEventListener: () => {},
    };
    const ab = await appEinhaengen(f, { app: NOTIZEN, args: {}, theme: () => 'dark', ...opt });
    aufraeumen.push(ab);
    const initAntwort: { hostCapabilities?: Record<string, unknown> }[] = [];
    vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
      const d = m as { result?: { hostCapabilities?: Record<string, unknown> } };
      if (d.result?.hostCapabilities) initAntwort.push(d.result);
      queueMicrotask(() => hoerer.forEach((h) => h({ source: eltern, data: m })));
    });
    const App = new Function('window', `${BRUECKE_QUELLE}\nreturn App;`)(meinFenster) as AppApi;
    await App.start('test-notizen');
    return { App, ab, initAntwort };
  }

  it('im OS-Fenster: Fähigkeit gemeldet, Anmelden mit Präfix, Aufruf über die Brücke, Abmelden', async () => {
    const { App, initAntwort } = await appStarten({ schluessel: 'app:notizen__liste' });
    expect(initAntwort[0]!.hostCapabilities).toHaveProperty('fyosWerkzeuge');
    expect(App.kann('fyosWerkzeuge')).toBe(true);

    const fn = vi.fn(async (a: { eintrag?: string }) => ({ satz: `gezeigt: ${a.eintrag}` }));
    const voll = await App.werkzeug('eintrag_zeigen', 'Zeigt einen Eintrag.', SCHEMA, fn, { lesend: true });
    expect(voll).toBe('notizen_eintrag_zeigen');
    expect(fuerBruecke().find((w) => w.name === 'notizen_eintrag_zeigen')).toMatchObject({ fenster: 'app:notizen__liste', app: 'notizen', lesend: true });

    const r = await rufenFuerBruecke('notizen_eintrag_zeigen', { eintrag: 'Entwurf' });
    expect(fn).toHaveBeenCalledWith({ eintrag: 'Entwurf' });
    expect(r.isError).toBeUndefined();
    expect(r.structuredContent).toEqual({ satz: 'gezeigt: Entwurf' });

    App.werkzeugWeg('eintrag_zeigen');
    await vi.waitFor(() => expect(liste().some((w) => w.name === 'notizen_eintrag_zeigen')).toBe(false));
    expect((await rufen('notizen_eintrag_zeigen', {})).isError).toBe(true);
  });

  it('Schließen des Fensters meldet alle Werkzeuge der App ab, offene Aufrufe enden mit Fehler', async () => {
    const { App, ab } = await appStarten({ schluessel: 'app:notizen__liste' });
    await App.werkzeug('haengt', 'Antwortet nie.', undefined, () => new Promise(() => {}), { lesend: true });
    await App.werkzeug('eintrag_zeigen', 'Zeigt.', SCHEMA, async () => 'ok', { lesend: true });
    expect(liste().filter((w) => w.name.startsWith('notizen_'))).toHaveLength(2);
    const offen = rufen('notizen_haengt', {});
    ab();
    const r = await offen;
    expect(r.isError).toBe(true);
    expect(r.content[0]!.text).toContain('geschlossen');
    expect(liste().filter((w) => w.name.startsWith('notizen_'))).toHaveLength(0);
    expect(fuerBruecke().filter((w) => w.name.startsWith('notizen_'))).toHaveLength(0);
  });

  it('ohne OS-Fenster (kein Schlüssel) gibt es keine Fähigkeit und nichts wird angemeldet', async () => {
    const { App, initAntwort } = await appStarten();
    expect(initAntwort[0]!.hostCapabilities).not.toHaveProperty('fyosWerkzeuge');
    expect(await App.werkzeug('eintrag_zeigen', 'Zeigt.', SCHEMA, async () => 'ok', { lesend: true })).toBeNull();
    expect(liste().some((w) => w.name === 'notizen_eintrag_zeigen')).toBe(false);
  });

  it('App.werkzeug(name, args) ruft weiterhin ein Hub-Werkzeug', async () => {
    const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
    const r = (await App.werkzeug('notizen__suche', { eintrag: 'x' })) as unknown as { structuredContent: unknown };
    expect(r.structuredContent).toEqual({ ok: 1 });
    expect(appCalls.map((c) => c.name)).toEqual(['notizen__suche']);
  });

  it('Fehler und Wurf der App-Funktion kommen als Fehler beim Agenten an', async () => {
    const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
    await App.werkzeug('kaputt', 'Wirft.', undefined, async () => {
      throw new Error('Kein Eintrag passt.');
    });
    const r = await rufenFuerBruecke('notizen_kaputt', {});
    expect(r.isError).toBe(true);
    expect(r.content[0]!.text).toContain('Kein Eintrag passt.');
  });

  describe('Bestätigungspflicht', () => {
    const schreiben = (App: AppApi) =>
      App.werkzeug(
        'liste_leeren',
        'Leert die Liste.',
        undefined,
        async () => {
          if (!(await App.beantragen({ frage: 'Liste leeren?' }))) return { geschrieben: false };
          await App.rufen('notizen__liste_setzen', { eintraege: [] });
          return { geschrieben: true };
        },
        { lesend: false },
      );
    const knopf = (art: 'ja' | 'nein') => document.querySelector<HTMLButtonElement>(`[data-aktion$="-${art}"]`)!;

    it('der Agent bekommt sofort „liegt dem Benutzer vor“, geschrieben wird erst nach dem Ja', async () => {
      const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
      await schreiben(App);
      const gesehen: unknown[] = [];
      window.addEventListener('fyos:beantragt', (e) => gesehen.push((e as CustomEvent).detail));
      const r = await rufenFuerBruecke('notizen_liste_leeren', {});
      expect(r.structuredContent).toMatchObject({ vorgelegt: true, frage: 'Liste leeren?' });
      expect(r.content[0]!.text).toContain('Erst nach seinem Ja');
      expect(knopf('ja')).toBeTruthy();
      expect(appCalls).toEqual([]);
      await vi.waitFor(() => expect(gesehen).toEqual([{ fenster: 'app:notizen__liste', app: 'notizen', frage: 'Liste leeren?' }]));

      knopf('ja').click();
      await vi.waitFor(() => expect(appCalls.map((c) => c.name)).toEqual(['notizen__liste_setzen']));
      expect(document.querySelector('.beantragt')).toBeNull();
    });

    it('„Abbrechen“ schreibt nichts', async () => {
      const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
      await schreiben(App);
      await rufenFuerBruecke('notizen_liste_leeren', {});
      knopf('nein').click();
      await vi.waitFor(() => expect(document.querySelector('.beantragt')).toBeNull());
      await new Promise((ok) => setTimeout(ok, 30));
      expect(appCalls).toEqual([]);
    });

    it('der Host lehnt Schreibendes aus einem Agentenaufruf ohne Klick ab, auch wenn die App „vergisst“ zu fragen', async () => {
      Object.defineProperty(navigator, 'userActivation', { value: { isActive: false }, configurable: true });
      const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
      await App.werkzeug('frech', 'Schreibt ohne zu fragen.', undefined, async () => App.rufen('notizen__liste_setzen', { eintraege: [] }));
      const r = await rufenFuerBruecke('notizen_frech', {});
      expect(r.isError).toBe(true);
      expect(r.content[0]!.text).toContain('Bestätigung');
      expect(appCalls).toEqual([]);
      // Lesen bleibt erlaubt
      await App.werkzeug('liest', 'Liest.', undefined, async () => App.rufen('notizen__suche', {}), { lesend: true });
      expect((await rufenFuerBruecke('notizen_liest', {})).isError).toBeUndefined();
      expect(appCalls.map((c) => c.name)).toEqual(['notizen__suche']);
    });

    it('ohne Agentenaufruf schreibt die App wie bisher (Klick des Benutzers)', async () => {
      Object.defineProperty(navigator, 'userActivation', { value: { isActive: false }, configurable: true });
      const { App } = await appStarten({ schluessel: 'app:notizen__liste' });
      await App.rufen('notizen__liste_setzen', { eintraege: [] });
      expect(appCalls.map((c) => c.name)).toEqual(['notizen__liste_setzen']);
    });
  });
});
