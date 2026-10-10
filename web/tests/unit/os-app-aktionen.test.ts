/**
 * App-Rahmen: die drei Aktionen am Fensterkopf und im Fenstermenü.
 *   Agent fragen             löst `fyos:agent-fragen` aus hier zählt das vollständige `detail`
 *   Link kopieren            Deeplink mit der Eingabe der aktuellen Ansicht
 *   An den Start heften   die Pins, mit Grenze und ehrlicher Rückmeldung
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_PINS, istAngepinnt, pins } from '~/lib/mcp-apps/pins';
import { zustandLeeren, zustandMerken } from '~/lib/mcp-apps/zustand';
import {
  AGENT_FRAGEN, KONTEXT_MAX, aktionsPunkte, ansicht, appLink, appFragen, heften, kannHeften, kontextKuerzen, linkKopieren, melden, rueckmeldung,
  type AgentFragenDetail,
} from '~/lib/os/app-aktionen';
import type { Flaeche } from '~/lib/os/flaechen';
import { eingabeLesen } from '~/lib/os/oeffnen';
import { SYMBOLE } from '~/lib/os/symbole-daten';

const flaeche = (name: string, titel: string, extra: Partial<Flaeche> = {}): Flaeche => ({
  id: `app:${name}`, titel, gruppe: 'Zuhause', art: 'hubapp', kuerzel: 'Ha', appName: name, mitglieder: [name], startbar: true, ...extra,
});
const HAUS = flaeche('haus__favoriten', 'Haus');

let ereignisse: AgentFragenDetail[];
const hoerer = (e: Event) => void ereignisse.push((e as CustomEvent<AgentFragenDetail>).detail);

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
  zustandLeeren();
  ereignisse = [];
  window.addEventListener(AGENT_FRAGEN, hoerer);
});
afterEach(() => {
  window.removeEventListener(AGENT_FRAGEN, hoerer);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, 'clipboard');
  Reflect.deleteProperty(document, 'execCommand');
});

describe('Agent fragen', () => {
  it('löst fyos:agent-fragen mit vollständigem detail aus (Anfangsansicht der App)', () => {
    const rueck = appFragen(HAUS);
    expect(ereignisse).toHaveLength(1);
    expect(ereignisse[0]).toEqual(rueck);
    expect(ereignisse[0]).toEqual({
      text: expect.stringContaining('Haus'),
      kontext: { app: 'haus__favoriten', titel: 'Haus', eingabe: {}, modellKontext: null },
      quelle: 'app',
    });
    expect(typeof ereignisse[0]!.text).toBe('string');
    expect(ereignisse[0]!.text.length).toBeGreaterThan(5);
  });

  it('nimmt Werkzeug, Eingabe und Modellkontext der Ansicht mit, wie der Host sie mitgeschrieben hat', () => {
    const modellKontext = { content: [{ type: 'text', text: 'Bad: 2 Lichter an' }], structuredContent: { raum: 'Bad' } };
    zustandMerken(HAUS.id, { werkzeug: 'haus__szenen', eingabe: { raum: 'Bad' }, modellKontext });
    appFragen(HAUS);
    expect(ereignisse[0]!.kontext).toEqual({ app: 'haus__szenen', titel: 'Haus', eingabe: { raum: 'Bad' }, modellKontext });
    expect(ereignisse[0]!.quelle).toBe('app');
  });

  it('ohne Mitschrift gilt der Start aus dem Link; mit Mitschrift gewinnt diese', () => {
    const start = { werkzeug: 'haus__szenen', eingabe: { raum: 'Küche' } };
    appFragen(HAUS, start);
    expect(ereignisse[0]!.kontext).toMatchObject({ app: 'haus__szenen', eingabe: { raum: 'Küche' } });
    zustandMerken(HAUS.id, { werkzeug: 'haus__favoriten', eingabe: { raum: 'Bad' } });
    appFragen(HAUS, start);
    expect(ereignisse[1]!.kontext).toMatchObject({ app: 'haus__favoriten', eingabe: { raum: 'Bad' } });
  });

  it('kürzt einen riesigen Modellkontext, statt ihn ungeprüft mitzuschicken', () => {
    zustandMerken(HAUS.id, { modellKontext: { text: 'x'.repeat(KONTEXT_MAX * 2) } });
    appFragen(HAUS);
    const k = ereignisse[0]!.kontext.modellKontext as { gekuerzt: boolean; text: string };
    expect(k.gekuerzt).toBe(true);
    expect(k.text.length).toBe(KONTEXT_MAX);
  });

  it('kontextKuerzen: Nichts bleibt null, Kleines bleibt, Unbrauchbares wird null', () => {
    expect(kontextKuerzen(undefined)).toBeNull();
    expect(kontextKuerzen(null)).toBeNull();
    const klein = { a: 1 };
    expect(kontextKuerzen(klein)).toBe(klein);
    expect(kontextKuerzen('text')).toBe('text');
    const kreis: Record<string, unknown> = {};
    kreis.selbst = kreis;
    expect(kontextKuerzen(kreis)).toBeNull();
    expect(kontextKuerzen(10n)).toBeNull(); // BigInt lässt sich nicht als JSON schreiben
  });
});

describe('Ansicht und Link', () => {
  it('der Link nennt das Werkzeug der aktuellen Ansicht und deren Eingabe', () => {
    zustandMerken(HAUS.id, { werkzeug: 'haus__szenen', eingabe: { raum: 'Küche', n: 2 } });
    const u = new URL(appLink(HAUS));
    expect(u.pathname).toBe('/os/');
    expect(u.searchParams.get('offen')).toBe('app:haus__szenen');
    expect(eingabeLesen(u.searchParams.get('eingabe'))).toEqual({ raum: 'Küche', n: 2 });
  });

  it('ohne Mitschrift: der Start aus dem Link, sonst die App selbst ohne Eingabe', () => {
    expect(ansicht(HAUS)).toEqual({ app: 'haus__favoriten', eingabe: {} });
    expect(ansicht(HAUS, { werkzeug: 'haus__szenen', eingabe: { raum: 'Bad' } })).toEqual({ app: 'haus__szenen', eingabe: { raum: 'Bad' } });
    const u = new URL(appLink(HAUS));
    expect(u.searchParams.get('offen')).toBe('app:haus__favoriten');
    expect(u.searchParams.has('eingabe')).toBe(false);
  });

  it('ohne appName fällt die Fläche auf ihre ID zurück', () => {
    expect(ansicht({ ...HAUS, appName: undefined, id: 'app:x__y' })).toEqual({ app: 'x__y', eingabe: {} });
  });
});

describe('Link kopieren', () => {
  it('schreibt den Link in die Zwischenablage und meldet „Link kopiert" im Kopf dieses Fensters', async () => {
    const schreiben = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: schreiben }, configurable: true });
    zustandMerken(HAUS.id, { werkzeug: 'haus__szenen', eingabe: { raum: 'Küche' } });
    expect(await linkKopieren(HAUS)).toBe(true);
    expect(schreiben).toHaveBeenCalledWith(appLink(HAUS));
    expect(rueckmeldung()).toEqual({ id: HAUS.id, text: 'Link kopiert', art: 'ok' });
  });

  it('die Rückmeldung verschwindet von selbst', () => {
    vi.useFakeTimers();
    melden(HAUS.id, 'Link kopiert');
    expect(rueckmeldung()).not.toBeNull();
    vi.advanceTimersByTime(2100);
    expect(rueckmeldung()).not.toBeNull();
    vi.advanceTimersByTime(200);
    expect(rueckmeldung()).toBeNull();
  });

  it('ohne Clipboard-API (http im LAN) geht es über ein verstecktes Textfeld und räumt auf', async () => {
    let kopierter = '';
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn(() => {
        kopierter = (document.querySelector('textarea') as HTMLTextAreaElement).value;
        return true;
      }),
      configurable: true,
    });
    expect(await linkKopieren(HAUS)).toBe(true);
    expect(kopierter).toBe(appLink(HAUS));
    expect(document.querySelector('textarea')).toBeNull();
    expect(rueckmeldung()).toMatchObject({ text: 'Link kopiert', art: 'ok' });
  });

  it('wird die Erlaubnis verweigert, geht der Umweg; scheitert auch der, sagt die Rückmeldung es ehrlich', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => { throw new Error('verweigert'); }) }, configurable: true });
    expect(await linkKopieren(HAUS)).toBe(false); // jsdom kennt execCommand nicht
    expect(rueckmeldung()).toEqual({ id: HAUS.id, text: 'Kopieren nicht möglich', art: 'hinweis' });
    expect(document.querySelector('textarea')).toBeNull();
  });
});

describe('An den Start heften', () => {
  it('heftet und löst wieder, mit Rückmeldung', () => {
    expect(heften(HAUS)).toBe(true);
    expect(istAngepinnt('haus__favoriten')).toBe(true);
    expect(rueckmeldung()).toMatchObject({ id: HAUS.id, text: 'An den Start geheftet', art: 'ok' });
    expect(heften(HAUS)).toBe(false);
    expect(istAngepinnt('haus__favoriten')).toBe(false);
    expect(rueckmeldung()).toMatchObject({ text: 'Vom Start gelöst', art: 'ok' });
  });

  it('heftet nichts an, was beim Laden des Startbildschirms etwas auslösen könnte', () => {
    const gruppe = flaeche('werkstatt__suchen', 'Werkstatt', { startbar: false, mitglieder: ['werkstatt__suchen', 'werkstatt__ausfuehren'] });
    expect(kannHeften(gruppe)).toBe(false);
    expect(heften(gruppe)).toBe(false);
    expect(pins()).toEqual([]);
    expect(rueckmeldung()).toMatchObject({ text: 'Diese App lässt sich nicht heften', art: 'hinweis' });
  });

  it(`hält die Grenze von ${MAX_PINS} Apps ein und sagt es`, () => {
    for (const n of ['a__x', 'b__x', 'c__x']) expect(heften(flaeche(n, n))).toBe(true);
    const vierte = flaeche('d__x', 'D');
    expect(heften(vierte)).toBe(false);
    expect(pins()).toEqual(['a__x', 'b__x', 'c__x']);
    expect(rueckmeldung()).toMatchObject({ text: `Es sind schon ${MAX_PINS} Apps geheftet`, art: 'hinweis' });
  });

  it('eine geheftete App lässt sich auch lösen, wenn sie inzwischen nicht mehr startbar ist', () => {
    heften(HAUS);
    const jetztGruppe = { ...HAUS, startbar: false };
    expect(kannHeften(jetztGruppe)).toBe(true);
    expect(heften(jetztGruppe)).toBe(false);
    expect(istAngepinnt('haus__favoriten')).toBe(false);
  });

  it('eine Fläche ohne App (Seite, Agent) lässt sich nicht heften', () => {
    const seite: Flaeche = { id: 'seite:finance', titel: 'Finance', gruppe: 'Geld', art: 'seite', kuerzel: 'Fi', pfad: '/finance/' };
    expect(kannHeften(seite)).toBe(false);
    expect(heften(seite)).toBe(false);
  });
});

describe('Menüpunkte im Fenstermenü', () => {
  type Eintrag = { text: string; symbol?: string; tun: () => void };
  const eintraege = (f: Flaeche) => aktionsPunkte(f) as Eintrag[];

  it('bietet die drei Aktionen mit Symbol — dieselben wie im Fensterkopf', () => {
    const punkte = eintraege(HAUS);
    expect(punkte.map((p) => [p.text, p.symbol])).toEqual([
      ['Agent fragen', 'sparkles'],
      ['Link kopieren', 'link'],
      ['An den Start heften', 'pin'],
    ]);
  });

  it('heften wird zu lösen, sobald die App geheftet ist', () => {
    heften(HAUS);
    expect(eintraege(HAUS).map((p) => [p.text, p.symbol])).toContainEqual(['Vom Start lösen', 'pin-off']);
  });

  it('bietet das Heften nicht an, wo es nicht geht', () => {
    const gruppe = flaeche('werkstatt__suchen', 'Werkstatt', { startbar: false });
    expect(eintraege(gruppe).map((p) => p.text)).toEqual(['Agent fragen', 'Link kopieren']);
  });

  it('die Punkte tun, was sie sagen', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => {}) }, configurable: true });
    const [fragen, link, anheften] = eintraege(HAUS);
    fragen!.tun();
    expect(ereignisse).toHaveLength(1);
    link!.tun();
    await vi.waitFor(() => expect(rueckmeldung()?.text).toBe('Link kopiert'));
    anheften!.tun();
    expect(istAngepinnt('haus__favoriten')).toBe(true);
  });

  it('alle Symbole der Aktionen gibt es im Glyphensatz', () => {
    heften(HAUS);
    for (const p of [...eintraege(HAUS), ...eintraege({ ...HAUS, appName: 'x__y' })]) expect(SYMBOLE[p.symbol!], p.text).toBeTruthy();
  });
});
