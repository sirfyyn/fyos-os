/**
 * Die Shell als Sitzung der OS-Brücke (lib/os/bruecke.ts): meldet sich beim Hub, holt Mitteilungen in der Antwort
 * ab (auch die vorgemerkten der Nacht) und gibt jede genau einmal als Fensterereignis `fyos:zeigt` weiter.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MELDEN_URL, SITZUNG_SCHLUESSEL, TAKT_FEHLER_MS, TAKT_SICHTBAR_MS, TAKT_VERDECKT_MS, brueckeStarten, mitteilungenAus, sitzungsId,
} from '~/lib/os/bruecke';
import { ZEIGT_EREIGNIS, zeigtPruefen } from '~/lib/os/mitteilungen';

const speicherAus = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};

const zeigtBefehl = (id: string, zeigt: Record<string, unknown> = {}) => ({
  id,
  art: 'zeigt',
  von: 'agent',
  zeigt: { ziel: 'agent', titel: 'Notizen geordnet', art: 'mitteilung', ...zeigt },
});

type Antwort = { ok?: boolean; json?: unknown; wirft?: boolean };

/** Ein Hub, der der Reihe nach antwortet; merkt sich, was die Shell schickt. */
function hubAttrappe(antworten: Antwort[]) {
  const aufrufe: { url: string; body: Record<string, unknown> }[] = [];
  let i = 0;
  const holen = vi.fn(async (url: string, init?: RequestInit) => {
    aufrufe.push({ url, body: JSON.parse(String(init?.body)) as Record<string, unknown> });
    const a = antworten[Math.min(i++, antworten.length - 1)] ?? { json: { ok: true } };
    if (a.wirft) throw new TypeError('Failed to fetch');
    return { ok: a.ok !== false, json: async () => a.json ?? { ok: true } } as Response;
  });
  return { holen: holen as unknown as typeof fetch, aufrufe };
}

let sichtbarkeit: DocumentVisibilityState;
beforeEach(() => {
  sichtbarkeit = 'visible';
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.setSystemTime(new Date('2030-01-01T03:30:00Z'));
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => sichtbarkeit });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const lass = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

describe('sitzungsId', () => {
  it('legt eine ID an, die der Hub annimmt, und behält sie beim Neuladen', () => {
    const sp = speicherAus();
    const a = sitzungsId(sp);
    expect(a).toMatch(/^[A-Za-z0-9_-]{6,64}$/);
    expect(sp.m.get(SITZUNG_SCHLUESSEL)).toBe(a);
    expect(sitzungsId(sp)).toBe(a);
  });

  it('ersetzt eine unbrauchbare gespeicherte ID und kommt mit gesperrtem Speicher zurecht', () => {
    const sp = speicherAus();
    sp.m.set(SITZUNG_SCHLUESSEL, 'a b/c');
    expect(sitzungsId(sp)).not.toBe('a b/c');
    const gesperrt = { getItem: () => { throw new Error('gesperrt'); }, setItem: () => { throw new Error('gesperrt'); } };
    expect(sitzungsId(gesperrt)).toMatch(/^[A-Za-z0-9_-]{6,64}$/);
    expect(sitzungsId(null)).toMatch(/^[A-Za-z0-9_-]{6,64}$/);
  });
});

describe('mitteilungenAus', () => {
  it('nimmt nur Befehle der Art zeigt und jede ID nur einmal', () => {
    const gesehen = new Set<string>();
    const antwort = {
      befehle: [
        zeigtBefehl('b-1'),
        { id: 'b-2', art: 'zeigen', ziel: 'app:x__y' },
        { id: 'b-3', art: 'zeigt' },
        null,
        zeigtBefehl('b-1'),
        zeigtBefehl('b-4', { titel: 'Zweite' }),
      ],
    };
    expect(mitteilungenAus(antwort, gesehen).map((z) => z.titel)).toEqual(['Notizen geordnet', 'Zweite']);
    expect(mitteilungenAus(antwort, gesehen)).toEqual([]);
  });

  it('übersteht Unsinn', () => {
    expect(mitteilungenAus(null, new Set())).toEqual([]);
    expect(mitteilungenAus({ befehle: 'x' }, new Set())).toEqual([]);
    expect(mitteilungenAus('x', new Set())).toEqual([]);
  });
});

describe('brueckeStarten', () => {
  const starten = (antworten: Antwort[], extra: Parameters<typeof brueckeStarten>[0] = {}) => {
    const hub = hubAttrappe(antworten);
    const gezeigt: Record<string, unknown>[] = [];
    const ende = brueckeStarten({ holen: hub.holen, zeigt: (d) => gezeigt.push(d), speicher: speicherAus(), ...extra });
    return { ...hub, gezeigt, ende };
  };

  it('meldet sich sofort als Sitzung ohne Strom, ohne Ton, mit Version 1 und Uhr des Browsers', async () => {
    const { aufrufe, ende } = starten([{ json: { ok: true, befehle: [], nach: null } }], { art: 'telefon', geraet: 'Testgerät' });
    await lass(0);
    expect(aufrufe).toHaveLength(1);
    expect(aufrufe[0]!.url).toBe(MELDEN_URL);
    expect(aufrufe[0]!.body).toMatchObject({
      geraet: 'Testgerät', art: 'telefon', sichtbar: true, abholen: true, version: 1, nach: null, aktiv_vor_s: 0,
      audio: { modus: 'stumm', kopfhoerer: false }, gesendet: Date.now(),
    });
    expect(String(aufrufe[0]!.body.sitzung)).toMatch(/^[A-Za-z0-9_-]{6,64}$/);
    ende();
  });

  it('gibt vorgemerkte Mitteilungen der Nacht weiter, mit nachgeholt und entstanden, genau einmal', async () => {
    const nacht = zeigtBefehl('b-nacht', { nachgeholt: true, entstanden: 1_893_467_520 });
    const { gezeigt, aufrufe, ende } = starten([
      { json: { ok: true, befehle: [nacht], nach: '1700-0' } },
      { json: { ok: true, befehle: [nacht], nach: '1700-0' } },
    ]);
    await lass(0);
    expect(gezeigt).toHaveLength(1);
    expect(zeigtPruefen(gezeigt[0])).toMatchObject({ ziel: 'agent', art: 'mitteilung', nachgeholt: true, entstanden: 1_893_467_520_000 });
    await lass(TAKT_SICHTBAR_MS);
    expect(aufrufe).toHaveLength(2);
    expect(aufrufe[1]!.body.nach).toBe('1700-0'); // liest ab der letzten Stream-ID weiter
    expect(gezeigt).toHaveLength(1); // dieselbe ID kommt nicht noch einmal auf den Schirm
    ende();
  });

  it('meldet im sichtbaren Tab alle 5 s, im verdeckten alle 30 s, und nach der Rückkehr sofort', async () => {
    const { aufrufe, ende } = starten([{ json: { ok: true } }]);
    await lass(0);
    await lass(TAKT_SICHTBAR_MS);
    expect(aufrufe).toHaveLength(2);
    sichtbarkeit = 'hidden';
    await lass(TAKT_SICHTBAR_MS); // der schon geplante Schritt läuft noch
    const n = aufrufe.length;
    expect(aufrufe[n - 1]!.body.sichtbar).toBe(false);
    await lass(TAKT_VERDECKT_MS - 1_000);
    expect(aufrufe).toHaveLength(n);
    await lass(1_000);
    expect(aufrufe).toHaveLength(n + 1);
    sichtbarkeit = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    await lass(0);
    expect(aufrufe).toHaveLength(n + 2);
    expect(aufrufe[n + 1]!.body.sichtbar).toBe(true);
    ende();
  });

  it('sagt, wie lange der letzte Handgriff her ist (der Hub rechnet damit, ob jemand davor sitzt)', async () => {
    const { aufrufe, ende } = starten([{ json: { ok: true } }]);
    await lass(0);
    await lass(4_000);
    window.dispatchEvent(new Event('pointerdown'));
    await lass(1_000); // 5 s nach dem Start meldet sie wieder: 1 s seit dem Handgriff
    expect(aufrufe[1]!.body.aktiv_vor_s).toBe(1);
    await lass(TAKT_SICHTBAR_MS);
    expect(aufrufe[2]!.body.aktiv_vor_s).toBe(6);
    ende();
  });

  it('ein Hub, der fehlt oder Unsinn sendet, stört nicht und wird langsamer gefragt', async () => {
    const { aufrufe, gezeigt, ende } = starten([{ wirft: true }, { ok: false }, { json: { ok: true, befehle: [zeigtBefehl('b-9')] } }]);
    await lass(0);
    expect(aufrufe).toHaveLength(1);
    await lass(TAKT_SICHTBAR_MS);
    expect(aufrufe).toHaveLength(1); // nach einem Fehler erst nach TAKT_FEHLER_MS wieder
    await lass(TAKT_FEHLER_MS - TAKT_SICHTBAR_MS);
    expect(aufrufe).toHaveLength(2);
    await lass(TAKT_FEHLER_MS);
    expect(aufrufe).toHaveLength(3);
    expect(gezeigt).toHaveLength(1);
    ende();
  });

  it('meldet den Abschied und hört auf, wenn sie beendet wird', async () => {
    const sendBeacon = vi.fn(() => true);
    vi.stubGlobal('navigator', { ...navigator, sendBeacon });
    const { aufrufe, ende } = starten([{ json: { ok: true } }]);
    await lass(0);
    ende();
    expect(sendBeacon).toHaveBeenCalledTimes(1);
    expect(sendBeacon.mock.calls[0]![0]).toBe(MELDEN_URL);
    await lass(TAKT_FEHLER_MS * 2);
    expect(aufrufe).toHaveLength(1);
  });

  it('gibt Mitteilungen als Fensterereignis fyos:zeigt weiter, wenn niemand etwas anderes angibt', async () => {
    const empfangen: unknown[] = [];
    const hoerer = (e: Event) => empfangen.push((e as CustomEvent).detail);
    window.addEventListener(ZEIGT_EREIGNIS, hoerer);
    const hub = hubAttrappe([{ json: { ok: true, befehle: [zeigtBefehl('b-w')] } }]);
    const ende = brueckeStarten({ holen: hub.holen, speicher: speicherAus() });
    await lass(0);
    window.removeEventListener(ZEIGT_EREIGNIS, hoerer);
    ende();
    expect(empfangen).toHaveLength(1);
    expect(zeigtPruefen(empfangen[0])).toMatchObject({ ziel: 'agent', titel: 'Notizen geordnet' });
  });

  it('ohne fetch tut sie nichts', () => {
    vi.stubGlobal('fetch', undefined);
    const ende = brueckeStarten({ speicher: speicherAus() });
    expect(() => ende()).not.toThrow();
  });
});
