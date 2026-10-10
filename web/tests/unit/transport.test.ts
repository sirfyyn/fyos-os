/**
 * transport.ts / hole() / fetchJson() / netz-waechter — alle Ausgänge der einen Strecke.
 *
 * Anlass: ein Proxy antwortet bei abgelaufener Sitzung mit 302 zur Anmeldung.
 * fetch meldete „Failed to fetch", die Oberfläche „Backend tot", Agenten lasen leere Listen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { hole } from '../../src/lib/api/abruf';
import { ApiError, fetchJson } from '../../src/lib/api/client';
import { SITZUNG_EREIGNIS, _sitzungZuruecksetzen, strecke } from '../../src/lib/api/transport';
import { netzWaechterInstallieren, sitzungPruefen } from '../../src/lib/api/netz-waechter';

function antwort(body: string, init: ResponseInit & { typ?: ResponseType } = {}): Response {
  const r = new Response(body, { status: init.status ?? 200, headers: init.headers });
  if (init.typ) Object.defineProperty(r, 'type', { value: init.typ });
  return r;
}
const json = (d: unknown, status = 200) => antwort(JSON.stringify(d), { status, headers: { 'content-type': 'application/json' } });
const umleitung = () => {
  const r = new Response(null, { status: 200 });
  Object.defineProperty(r, 'type', { value: 'opaqueredirect' });
  Object.defineProperty(r, 'status', { value: 0 });
  Object.defineProperty(r, 'ok', { value: false });
  return r;
};

let ereignisse = 0;
const zaehle = () => { ereignisse += 1; };
beforeEach(() => {
  _sitzungZuruecksetzen();
  ereignisse = 0;
  window.addEventListener(SITZUNG_EREIGNIS, zaehle);
});
afterEach(() => {
  window.removeEventListener(SITZUNG_EREIGNIS, zaehle);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('strecke', () => {
  it('Umleitung zur Anmeldung = Sitzung abgelaufen, einmal gemeldet', async () => {
    const f = vi.fn(async () => umleitung());
    vi.stubGlobal('fetch', f);
    expect((await strecke('/api/x')).art).toBe('sitzung');
    expect((await strecke('/api/y')).art).toBe('sitzung');
    expect(ereignisse).toBe(1);
    expect(f.mock.calls[0][1]).toMatchObject({ redirect: 'manual', credentials: 'include' });
  });

  it('401 und HTML statt JSON zählen ebenfalls als Sitzung', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({}, 401)));
    expect((await strecke('/api/x')).art).toBe('sitzung');
    _sitzungZuruecksetzen();
    vi.stubGlobal('fetch', vi.fn(async () => antwort('<html>login</html>', { headers: { 'content-type': 'text/html' } })));
    expect((await strecke('/api/x')).art).toBe('sitzung');
  });

  it('HTTP-Fehler trägt den Text aus detail/title', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'kaputt' }, 500)));
    const s = await strecke('/api/x');
    expect(s).toMatchObject({ art: 'http', status: 500, grund: 'kaputt' });
  });

  it('Zeitgrenze, Abbruch und Netzfehler sind drei verschiedene Ausgänge', async () => {
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit) => new Promise((_ok, fail) => {
      init.signal?.addEventListener('abort', () => fail(new DOMException('aborted', 'AbortError')));
    })));
    expect((await strecke('/api/x', { zeitMs: 20 })).art).toBe('zeit');
    const ac = new AbortController();
    const p = strecke('/api/x', { signal: ac.signal, zeitMs: 5000 });
    ac.abort();
    expect((await p).art).toBe('abgebrochen');
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    expect(await strecke('/api/x')).toMatchObject({ art: 'netz', grund: 'Failed to fetch' });
  });

  it('204 und kaputtes JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })));
    expect(await strecke('/api/x')).toMatchObject({ art: 'ok', daten: null });
    vi.stubGlobal('fetch', vi.fn(async () => antwort('{kaputt', { headers: { 'content-type': 'application/json' } })));
    expect((await strecke('/api/x')).art).toBe('kein_json');
  });
});

describe('hole() und fetchJson() auf derselben Strecke', () => {
  it('hole: Sitzung ist nicht_erreichbar mit sitzung=true, leer bleibt leer', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => umleitung()));
    expect(await hole('/api/x')).toMatchObject({ zustand: 'nicht_erreichbar', status: 401, sitzung: true });
    vi.stubGlobal('fetch', vi.fn(async () => json([])));
    expect(await hole('/api/x')).toEqual({ zustand: 'leer' });
    vi.stubGlobal('fetch', vi.fn(async () => json([1])));
    expect(await hole('/api/x')).toEqual({ zustand: 'daten', daten: [1] });
  });

  it('fetchJson wirft ApiError mit sprechendem Status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => umleitung()));
    const e = await fetchJson('/api/x').catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(401);
    expect(e.sitzungAbgelaufen).toBe(true);
    vi.stubGlobal('fetch', vi.fn(async () => json({ title: 'nein' }, 404)));
    expect((await fetchJson('/api/x').catch((x) => x)).status).toBe(404);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    expect((await fetchJson('/api/x').catch((x) => x)).status).toBe(0);
  });
});

describe('Netz-Wächter', () => {
  it('sitzungPruefen: Umleitung = abgelaufen, Netzfehler = nicht abgelaufen', async () => {
    expect(await sitzungPruefen(vi.fn(async () => umleitung()) as unknown as typeof fetch)).toBe(true);
    expect(await sitzungPruefen(vi.fn(async () => json({ ok: true })) as unknown as typeof fetch)).toBe(false);
    expect(await sitzungPruefen(vi.fn(async () => { throw new TypeError('x'); }) as unknown as typeof fetch)).toBe(false);
  });

  it('ändert das Verhalten roher fetch-Aufrufe nicht, meldet aber die Sitzung', async () => {
    const aufrufe: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      aufrufe.push(String(u));
      if (String(u).startsWith('/healthz')) return umleitung();
      throw new TypeError('Failed to fetch');
    }));
    netzWaechterInstallieren();
    await expect(window.fetch('/api/roh')).rejects.toThrow('Failed to fetch');
    await new Promise((r) => setTimeout(r, 0));
    expect(aufrufe.some((u) => u.startsWith('/healthz'))).toBe(true);
    expect(ereignisse).toBe(1);
  });
});
