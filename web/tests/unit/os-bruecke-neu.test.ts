/**
 * Volle OS-Brücke (lib/os/bruecke-neu.ts): Ereignisstrom lesen, dem Hub die Lage melden, Befehle ausführen.
 * Vertrag „Brücke v1“: GET /hub-api/os/strom (SSE), POST /hub-api/os/melden, POST /hub-api/os/antwort.
 *
 * Der Hub ist hier ein Fake: `fetch` antwortet je nach Pfad, der Strom ist ein ReadableStream, in den der
 * Test Text schreibt — auch zerhackt, mitten im Feld und mitten im UTF-8-Zeichen. Die Zeit läuft mit
 * Fake-Timern (nur setTimeout und Date; Promises und Streams bleiben echt).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE } from '../../src/lib/api/transport';
import {
  ANGEMELDET_EREIGNIS,
  ANMELDE_EREIGNIS,
  ALTER_AUSFUEHREN_S,
  ALTER_ZEIGEN_S,
  ALTER_ZEIGT_S,
  AUSFUEHREN_MAX_MS,
  BACKOFF_MS,
  BUENDEL_MS,
  DUPLIKAT_WARTE_MS,
  GESEHEN_MAX,
  LANGSAM_MS,
  PFAD_ANTWORT,
  PFAD_MELDEN,
  PFAD_STROM,
  SCHALTER,
  SCHLUESSEL_GERAET,
  SCHLUESSEL_SITZUNG,
  STILLE_MS,
  TAKT_MS,
  VERDECKT_MAX_MS,
  SseParser,
  aktivitaetBeobachten,
  backoffNach,
  erzeugeBruecke,
  geraetErkennen,
  sitzungsId,
  sperrgrund,
  echteUmgebung,
  type BrueckeOptionen,
  type BrueckeStatus,
  type BrueckeUmgebung,
  type KanalKurz,
  type ToolErgebnis,
  type ZeigenAntwort,
} from '../../src/lib/os/bruecke-neu';
import type { Lage } from '../../src/lib/os/bruecke-lage';

// ── Server-Sent Events lesen ────────────────────────────────────────────────────────────────────

describe('SseParser', () => {
  const alle = (teile: string[]) => {
    const p = new SseParser();
    return { p, ereignisse: teile.flatMap((t) => p.push(t)) };
  };

  it('liest ein Ereignis mit Name, Kennung und Daten', () => {
    const { ereignisse, p } = alle(['id: 5-0\nevent: befehl\ndata: {"id":"x"}\n\n']);
    expect(ereignisse).toEqual([{ event: 'befehl', data: '{"id":"x"}', id: '5-0', retry: null }]);
    expect(p.letzteId).toBe('5-0');
  });

  it('nimmt „message“, wenn kein Name da ist, und trennt mehrere Ereignisse in einem Stück', () => {
    const { ereignisse } = alle(['data: eins\n\nevent: hallo\ndata: zwei\n\n']);
    expect(ereignisse.map((e) => [e.event, e.data])).toEqual([
      ['message', 'eins'],
      ['hallo', 'zwei'],
    ]);
  });

  it('fügt mehrzeilige data mit \\n zusammen', () => {
    expect(alle(['data: a\ndata: b\ndata:\ndata: d\n\n']).ereignisse[0]!.data).toBe('a\nb\n\nd');
  });

  it('überliest Kommentare (der Hub schickt „: ping“) und Ereignisse ohne data', () => {
    const { ereignisse } = alle([': ping\n\n', 'event: leer\n\n', ': noch ein ping\nevent: x\ndata: ok\n\n']);
    expect(ereignisse).toEqual([{ event: 'x', data: 'ok', id: null, retry: null }]);
  });

  it('versteht \\r\\n und \\r als Zeilenende', () => {
    expect(alle(['event: a\r\ndata: 1\r\n\r\n']).ereignisse).toMatchObject([{ event: 'a', data: '1' }]);
    expect(alle(['event: a\rdata: 1\r\r']).ereignisse).toMatchObject([{ event: 'a', data: '1' }]);
    expect(alle(['event: a\r\ndata: 1\n\r\ndata: 2\r\r\n']).ereignisse.map((e) => e.data)).toEqual(['1', '2']);
  });

  it('ein \\r am Ende eines Stücks und das \\n gleich im nächsten sind ein Zeilenende', () => {
    const { ereignisse } = alle(['event: a\r\ndata: 1\r', '\n\r', '\ndata: 2\r\n\r\n']);
    expect(ereignisse.map((e) => [e.event, e.data])).toEqual([
      ['a', '1'],
      ['message', '2'],
    ]);
  });

  it('kommt mit Stücken zurecht, die mitten im Feld enden — auch Zeichen für Zeichen', () => {
    const text = 'retry: 3000\nid: 9-1\nevent: befehl\ndata: {"id":"c","art":"zeigen"}\n\n: ping\n\nevent: hallo\ndata: {}\n\n';
    const ganz = new SseParser().push(text);
    const stueckweise = new SseParser();
    const aus = [...text].flatMap((z) => stueckweise.push(z));
    expect(aus).toEqual(ganz);
    expect(aus.map((e) => e.event)).toEqual(['befehl', 'hallo']);
    expect(aus[0]).toMatchObject({ id: '9-1', retry: 3000, data: '{"id":"c","art":"zeigen"}' });
  });

  it('merkt sich retry und die letzte Kennung; eine Kennung mit NUL zählt nicht', () => {
    const p = new SseParser();
    p.push('retry: 3000\nid: 1\ndata: a\n\nid: 2\ndata: b\n\n');
    expect(p.retry).toBe(3000);
    expect(p.letzteId).toBe('2');
    p.push('id: x\u0000y\ndata: c\n\n');
    expect(p.letzteId).toBe('2');
    p.push('retry: soon\ndata: d\n\n');
    expect(p.retry).toBe(3000);
  });

  it('nimmt ein Feld ohne Doppelpunkt als leeren Wert und schneidet genau ein Leerzeichen ab', () => {
    const { ereignisse } = alle(['data\n\ndata:  zwei\n\ndata:eins\n\n']);
    expect(ereignisse.map((e) => e.data)).toEqual(['', ' zwei', 'eins']);
  });

  it('die Kennung gilt auch ohne Daten (wie lastEventId bei EventSource)', () => {
    const p = new SseParser();
    expect(p.push('id: 42\n\n')).toEqual([]);
    expect(p.letzteId).toBe('42');
  });
});

describe('geraetErkennen', () => {
  const UA = {
    mac: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
    ipad: 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
    androidHandy: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36',
    androidTablet: 'Mozilla/5.0 (Linux; Android 14; SM-X900) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
    windows: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
    linux: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
    chromeos: 'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
  };

  it('nennt das Gerät, wie ein Mensch es nennen würde', () => {
    expect(geraetErkennen({ userAgent: UA.mac, maxTouchPoints: 0 })).toEqual({ name: 'MacBook', art: 'computer' });
    expect(geraetErkennen({ userAgent: UA.iphone, maxTouchPoints: 5 })).toEqual({ name: 'iPhone', art: 'telefon' });
    expect(geraetErkennen({ userAgent: UA.ipad, maxTouchPoints: 5 })).toEqual({ name: 'iPad', art: 'tablet' });
    expect(geraetErkennen({ userAgent: UA.androidHandy, maxTouchPoints: 5 })).toEqual({ name: 'Android-Handy', art: 'telefon' });
    expect(geraetErkennen({ userAgent: UA.androidTablet, maxTouchPoints: 5 })).toEqual({ name: 'Android-Tablet', art: 'tablet' });
    expect(geraetErkennen({ userAgent: UA.windows })).toEqual({ name: 'Windows-PC', art: 'computer' });
    expect(geraetErkennen({ userAgent: UA.linux })).toEqual({ name: 'Linux-PC', art: 'computer' });
    expect(geraetErkennen({ userAgent: UA.chromeos })).toEqual({ name: 'Browser', art: 'computer' });
    expect(geraetErkennen({})).toEqual({ name: 'Browser', art: 'computer' });
  });

  it('iPadOS gibt sich als Mac aus — mit Touch ist es ein iPad', () => {
    expect(geraetErkennen({ userAgent: UA.mac, maxTouchPoints: 5 })).toEqual({ name: 'iPad', art: 'tablet' });
    expect(geraetErkennen({ userAgent: UA.mac, maxTouchPoints: 1 })).toEqual({ name: 'MacBook', art: 'computer' });
  });

  it('ein eigener Name gewinnt, bereinigt und auf 40 Zeichen gekürzt; die Art bleibt erkannt', () => {
    expect(geraetErkennen({ userAgent: UA.mac }, '  Mein Büro-Mac  ')).toEqual({ name: 'Mein Büro-Mac', art: 'computer' });
    expect(geraetErkennen({ userAgent: UA.iphone }, 'Mein\u0000 Telefon\n').name).toBe('Mein Telefon');
    expect(geraetErkennen({ userAgent: UA.mac }, 'x'.repeat(60)).name).toHaveLength(40);
    expect(geraetErkennen({ userAgent: UA.iphone }, '   ')).toEqual({ name: 'iPhone', art: 'telefon' });
    expect(geraetErkennen({ userAgent: UA.iphone }, 'Handy').art).toBe('telefon');
  });
});

describe('sitzungsId', () => {
  const speicher = () => {
    const m = new Map<string, string>();
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
  };

  it('ist „s-“ und zehn Zeichen aus [a-z0-9], und bleibt im Tab gleich', () => {
    const s = speicher();
    const id = sitzungsId(s);
    expect(id).toMatch(/^s-[a-z0-9]{10}$/);
    expect(s.m.get(SCHLUESSEL_SITZUNG)).toBe(id);
    expect(sitzungsId(s)).toBe(id);
  });

  it('ersetzt eine unbrauchbare gespeicherte ID', () => {
    const s = speicher();
    s.m.set(SCHLUESSEL_SITZUNG, 'irgendwas');
    const id = sitzungsId(s);
    expect(id).toMatch(/^s-[a-z0-9]{10}$/);
    expect(s.m.get(SCHLUESSEL_SITZUNG)).toBe(id);
  });

  it('kommt ohne Speicher und mit gesperrtem Speicher zurecht', () => {
    expect(sitzungsId(null)).toMatch(/^s-[a-z0-9]{10}$/);
    const gesperrt = {
      getItem: () => {
        throw new Error('gesperrt');
      },
      setItem: () => {
        throw new Error('gesperrt');
      },
    };
    expect(sitzungsId(gesperrt)).toMatch(/^s-[a-z0-9]{10}$/);
  });

  it('zwei Tabs bekommen verschiedene IDs', () => {
    expect(sitzungsId(speicher())).not.toBe(sitzungsId(speicher()));
  });
});

describe('sperrgrund', () => {
  const mit = (schalter: string | null, nav: BrueckeUmgebung['navigator'], f: unknown = () => {}) =>
    sperrgrund({ lokal: { getItem: (k: string) => (k === SCHALTER ? schalter : null) }, navigator: nav, fetch: f as typeof fetch });

  it('darf in einem normalen Browser', () => {
    expect(mit(null, { userAgent: 'Mozilla/5.0 (Macintosh) Safari', webdriver: false })).toBeNull();
  });
  it('der Schalter „aus“ stoppt immer', () => {
    expect(mit('aus', { userAgent: 'Safari' })).toBe('schalter');
  });
  it('ferngesteuerte Browser melden sich nicht — außer es steht „an“', () => {
    expect(mit(null, { userAgent: 'HeadlessChrome', webdriver: true })).toBe('webdriver');
    expect(mit('an', { userAgent: 'HeadlessChrome', webdriver: true })).toBeNull();
  });
  it('die Testumgebung (jsdom) startet nicht — außer es steht „an“', () => {
    expect(mit(null, { userAgent: 'Mozilla/5.0 (linux) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/24.0.0' })).toBe('testumgebung');
    expect(mit('an', { userAgent: 'jsdom/24.0.0' })).toBeNull();
  });
  it('ohne fetch geht nichts', () => {
    expect(mit(null, { userAgent: 'Safari' }, null)).toBe('kein-fetch');
  });
  it('gesperrter Speicher blockiert nicht', () => {
    const r = sperrgrund({
      lokal: {
        getItem: () => {
          throw new Error('gesperrt');
        },
      },
      navigator: { userAgent: 'Safari' },
      fetch: (() => {}) as unknown as typeof fetch,
    });
    expect(r).toBeNull();
  });
});

describe('backoffNach', () => {
  it('wartet 1, 2, 4, 8, dann immer 15 Sekunden', () => {
    expect([0, 1, 2, 3, 4, 5, 6, 50].map(backoffNach)).toEqual([1000, 2000, 4000, 8000, 15000, 15000, 15000, 15000]);
    expect(BACKOFF_MS).toEqual([1000, 2000, 4000, 8000, 15000]);
    expect(backoffNach(-3)).toBe(1000);
  });
});

describe('aktivitaetBeobachten', () => {
  it('liefert die Sekunden seit der letzten Eingabe, null solange keine kam', () => {
    const ziel = new EventTarget();
    let jetzt = 100_000;
    const a = aktivitaetBeobachten(ziel as unknown as Window, () => jetzt);
    expect(a.vorSekunden()).toBeNull();
    ziel.dispatchEvent(new Event('keydown'));
    expect(a.vorSekunden()).toBe(0);
    jetzt += 12_400;
    expect(a.vorSekunden()).toBe(12);
    ziel.dispatchEvent(new Event('pointerdown'));
    expect(a.vorSekunden()).toBe(0);
    a.stop();
    jetzt += 5_000;
    ziel.dispatchEvent(new Event('keydown'));
    expect(a.vorSekunden()).toBe(5); // nach stop() zählt nichts mehr
  });

  it('Mausbewegung zählt, aber höchstens alle zwei Sekunden neu', () => {
    const ziel = new EventTarget();
    let jetzt = 10_000;
    const a = aktivitaetBeobachten(ziel as unknown as Window, () => jetzt);
    ziel.dispatchEvent(new Event('pointermove'));
    jetzt += 1_000;
    ziel.dispatchEvent(new Event('pointermove')); // zu früh: ignoriert
    jetzt += 1_500;
    expect(a.vorSekunden()).toBe(3);
    ziel.dispatchEvent(new Event('pointermove'));
    expect(a.vorSekunden()).toBe(0);
  });
});

// ── Die Brücke gegen einen Fake-Hub ─────────────────────────────────────────────────────────────

const MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15';

type Post = { pfad: string; body: Record<string, unknown>; init: RequestInit; zeit: number };
type Get = { url: URL; init: RequestInit; zeit: number };
type StromArt = 'offen' | 'fehler' | 'http500' | 'http401' | 'umleitung' | 'html' | 'nicht_da' | 'kein_strom';
interface Strom {
  schicke: (text: string | Uint8Array) => void;
  zu: () => void;
  abgebrochen: boolean;
}

const antwortJson = (daten: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, type: 'basic', headers: new Headers({ 'content-type': 'application/json' }), json: async () => daten, body: null }) as unknown as Response;

function hubBauen() {
  const posts: Post[] = [];
  const gets: Get[] = [];
  const stroeme: Strom[] = [];
  const enc = new TextEncoder();
  const h = {
    posts,
    gets,
    stroeme,
    strom: 'offen' as StromArt,
    melden: (): { status: number; daten: unknown } => ({ status: 200, daten: { ok: true, ablauf_s: 90, sitzungen: 2 } }),
    /** Wie oft das nächste POST /antwort an einem Netzfehler scheitert */
    antwortFehler: 0,
    fetch: vi.fn(async (url: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
      const u = new URL(String(url), 'http://hub.test');
      if (init.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push({ pfad: u.pathname, body, init, zeit: Date.now() });
        if (u.pathname === PFAD_MELDEN) {
          const r = h.melden();
          return antwortJson(r.daten, r.status);
        }
        if (u.pathname === PFAD_ANTWORT && h.antwortFehler > 0) {
          h.antwortFehler -= 1;
          throw new TypeError('Failed to fetch');
        }
        return antwortJson({ ok: true });
      }
      gets.push({ url: u, init, zeit: Date.now() });
      switch (h.strom) {
        case 'fehler':
          throw new TypeError('Failed to fetch');
        case 'http500':
          return antwortJson('boom', 500);
        case 'http401':
          return antwortJson('', 401);
        case 'nicht_da':
          return antwortJson('', 404);
        case 'umleitung':
          return { type: 'opaqueredirect', status: 0, ok: false, headers: new Headers(), body: null } as unknown as Response;
        case 'html':
          return { ok: true, status: 200, type: 'basic', headers: new Headers({ 'content-type': 'text/html' }), body: new ReadableStream() } as unknown as Response;
        case 'kein_strom':
          return { ok: true, status: 200, type: 'basic', headers: new Headers({ 'content-type': 'application/json' }), body: new ReadableStream() } as unknown as Response;
        default: {
          let c!: ReadableStreamDefaultController<Uint8Array>;
          const s: Strom = {
            abgebrochen: false,
            schicke: (t) => c.enqueue(typeof t === 'string' ? enc.encode(t) : t),
            zu: () => c.close(),
          };
          const body = new ReadableStream<Uint8Array>({
            start(ctrl) {
              c = ctrl;
            },
            cancel() {
              s.abgebrochen = true;
            },
          });
          stroeme.push(s);
          return { ok: true, status: 200, type: 'basic', headers: new Headers({ 'content-type': 'text/event-stream; charset=utf-8' }), body } as unknown as Response;
        }
      }
    }),
  };
  return h;
}
type Hub = ReturnType<typeof hubBauen>;

const LAGE: Lage = {
  anruf: false,
  agent_vorne: false,
  bildschirm: 1,
  bildschirme: [
    { index: 0, name: 'Start' },
    { index: 1, name: 'Arbeit' },
  ],
  fenster: [{ id: 'seite:berichte', titel: 'Berichte', art: 'seite', bildschirm: 1, bildschirm_name: 'Arbeit', vorne: true, min: false }],
  flaechen: [
    { id: 'seite:berichte', titel: 'Berichte', gruppe: 'Auswertung' },
    { id: 'app:notizen__liste', titel: 'Notizen', gruppe: 'Notizen' },
  ],
};
const WERKZEUGE = [{ name: 'os_fenster', beschreibung: 'Liest die Fenster', lesend: true, eingabe: { type: 'object', properties: {} } }];

interface Aufbau {
  hub: Hub;
  b: ReturnType<typeof erzeugeBruecke>;
  lage: Lage;
  stati: BrueckeStatus[];
  zeigen: ReturnType<typeof vi.fn<(ziel: string, eingabe: Record<string, unknown> | null) => Promise<ZeigenAntwort>>>;
  ausfuehren: ReturnType<typeof vi.fn<(w: string, a: Record<string, unknown>) => Promise<ToolErgebnis>>>;
  zeigt: ReturnType<typeof vi.fn>;
  u: BrueckeUmgebung & { sitzungAbgelaufen: ReturnType<typeof vi.fn>; beacons: { url: string; daten: unknown }[]; lokalMap: Map<string, string>; fenster: EventTarget; dokument: EventTarget };
}

function aufbau(extra: { hub?: Hub; lage?: Partial<Lage>; lokal?: Record<string, string>; nav?: Partial<BrueckeUmgebung['navigator']>; sichtbar?: () => boolean; beacon?: boolean; audio?: BrueckeOptionen['audio']; kanal?: BrueckeUmgebung['kanal']; sitzungId?: string; zufall?: () => number } = {}): Aufbau {
  const hub = extra.hub ?? hubBauen();
  const lage: Lage = { ...LAGE, ...extra.lage };
  const lokalMap = new Map<string, string>(Object.entries(extra.lokal ?? {}));
  const sitz = new Map<string, string>(extra.sitzungId ? [[SCHLUESSEL_SITZUNG, extra.sitzungId]] : []);
  const beacons: { url: string; daten: unknown }[] = [];
  const u = {
    fetch: hub.fetch as unknown as typeof fetch,
    jetzt: () => Date.now(),
    navigator: {
      userAgent: MAC_UA,
      maxTouchPoints: 0,
      webdriver: false,
      sendBeacon: extra.beacon === false ? undefined : (url: string, daten?: BodyInit | null) => {
        beacons.push({ url, daten });
        return true;
      },
      ...extra.nav,
    },
    lokal: { getItem: (k: string) => lokalMap.get(k) ?? null },
    sitzung: { getItem: (k: string) => sitz.get(k) ?? null, setItem: (k: string, v: string) => void sitz.set(k, v) },
    pfad: () => '/os',
    sichtbar: extra.sichtbar ?? (() => true),
    aktivitaet: () => 7,
    fenster: new EventTarget(),
    dokument: new EventTarget(),
    zufall: extra.zufall ?? (() => 1), // kein Jitter: die Wartezeiten sind genau die Stufen aus BACKOFF_MS
    kanal: extra.kanal ?? (() => null), // die Tests melden sofort; den BroadcastChannel des Prüfers gibt es nur mit `kanal`
    sitzungAbgelaufen: vi.fn(),
    beacons,
    lokalMap,
  } as unknown as Aufbau['u'];
  const stati: BrueckeStatus[] = [];
  const zeigen = vi.fn(async (ziel: string): Promise<ZeigenAntwort> => ({ ok: true, ergebnis: { gezeigt: true, ziel, titel: 'Berichte', bildschirm: 1 } }));
  const ausfuehren = vi.fn(async (): Promise<ToolErgebnis> => ({ content: [{ type: 'text', text: '{"fenster":[]}' }] }));
  const zeigt = vi.fn();
  const opt: BrueckeOptionen = {
    lage: () => lage,
    werkzeuge: () => WERKZEUGE,
    zeigen,
    ausfuehren,
    zeigt,
    onStatus: (s) => stati.push(s),
    umgebung: u,
    ...(extra.audio ? { audio: extra.audio } : {}),
  };
  return { hub, b: erzeugeBruecke(opt), lage, stati, zeigen, ausfuehren, zeigt, u };
}

const START = Date.parse('2026-10-03T10:00:00Z'); // die Uhr, auf die die Tests `vi.setSystemTime` stellen
/** Der Text eines Blobs (jsdom kennt `Blob.text()` nicht überall). */
const blobText = (blob: Blob): Promise<string> =>
  typeof blob.text === 'function'
    ? blob.text()
    : new Promise<string>((res) => {
        const r = new FileReader();
        r.onload = () => res(String(r.result));
        r.readAsText(blob);
      });
const lass = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const fluss = async () => {
  for (let i = 0; i < 4; i++) await lass(0);
};
const befehlText = (b: object, id?: string) => `${id ? `id: ${id}\n` : ''}event: befehl\ndata: ${JSON.stringify(b)}\n\n`;
const zeigtBefehl = (id: string, extra: object = {}, alter = 0) => ({ id, art: 'zeigt', zeigt: { ziel: 'app:notizen__liste', app: 'notizen__liste', titel: 'Notizen', vorschau: '3 Einträge neu', ...extra }, alter_s: alter });
const melde = (h: Hub) => h.posts.filter((p) => p.pfad === PFAD_MELDEN);
const antworten = (h: Hub) => h.posts.filter((p) => p.pfad === PFAD_ANTWORT);

describe('Brücke gegen den Fake-Hub', () => {
  let laufend: Aufbau | undefined;
  const los = async (extra: Parameters<typeof aufbau>[0] = {}) => {
    const a = aufbau(extra);
    laufend = a;
    expect(a.b.start()).toBe(true);
    await fluss();
    return a;
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    vi.setSystemTime(START);
  });
  afterEach(() => {
    laufend?.b.stop();
    laufend = undefined;
    vi.useRealTimers();
  });

  describe('Melden', () => {
    it('meldet sofort beim Start, mit allem, was der Vertrag verlangt', async () => {
      const a = await los();
      const m = melde(a.hub);
      expect(m).toHaveLength(1);
      const p = m[0]!;
      expect(`${API_BASE}${PFAD_MELDEN}`).toMatch(/\/hub-api\/os\/melden$/);
      expect(p.init).toMatchObject({ method: 'POST', credentials: 'include', redirect: 'manual' });
      expect(p.init.headers).toMatchObject({ 'Content-Type': 'application/json' });
      expect(p.body).toEqual({
        sitzung: a.b.sitzung,
        geraet: 'MacBook',
        art: 'computer',
        seite: '/os',
        sichtbar: true,
        aktiv_vor_s: 7,
        anruf: false,
        agent_vorne: false,
        bildschirm: 1,
        bildschirme: LAGE.bildschirme,
        fenster: LAGE.fenster,
        flaechen: LAGE.flaechen,
        werkzeuge: WERKZEUGE,
        version: 1,
        gesendet: START,
      });
      expect(a.b.sitzung).toMatch(/^s-[a-z0-9]{10}$/);
      expect(a.b.sitzungen()).toBe(2);
    });

    it('meldet den Ton-Modus des Geräts mit, und eine Änderung meldet neu', async () => {
      let audio = { modus: 'interaktiv' as const, kopfhoerer: true as boolean | null };
      const a = await los({ audio: () => audio });
      expect(melde(a.hub)[0]!.body).toMatchObject({ audio: { modus: 'interaktiv', kopfhoerer: true } });
      audio = { ...audio, kopfhoerer: false }; // AirPods raus
      a.b.aendern();
      await lass(2_000);
      expect(melde(a.hub)).toHaveLength(2);
      expect(melde(a.hub)[1]!.body).toMatchObject({ audio: { modus: 'interaktiv', kopfhoerer: false } });
      const kaputt = await los({ audio: () => { throw new Error('Speicher gesperrt'); } });
      expect(melde(kaputt.hub)[0]!.body).toMatchObject({ audio: { modus: null, kopfhoerer: null } });
    });

    it('nimmt einen eigenen Gerätenamen aus dem Speicher', async () => {
      const a = await los({ lokal: { [SCHLUESSEL_GERAET]: 'Büro-Mac' } });
      expect(melde(a.hub)[0]!.body).toMatchObject({ geraet: 'Büro-Mac', art: 'computer' });
      expect(a.hub.gets[0]!.url.searchParams.get('geraet')).toBe('Büro-Mac');
    });

    it('meldet alle 30 Sekunden, auch wenn sich nichts geändert hat', async () => {
      const a = await los();
      expect(melde(a.hub)).toHaveLength(1);
      await lass(TAKT_MS - 1);
      expect(melde(a.hub)).toHaveLength(1);
      await lass(1);
      expect(melde(a.hub)).toHaveLength(2);
      await lass(TAKT_MS);
      expect(melde(a.hub)).toHaveLength(3);
    });

    it('bündelt Änderungen: eine Meldung 1,5 s nach der ersten, nichts bei gleichbleibender Lage', async () => {
      const a = await los();
      a.b.aendern(); // nichts geändert
      await lass(BUENDEL_MS + 10);
      expect(melde(a.hub)).toHaveLength(1);

      a.lage.bildschirm = 0;
      a.b.aendern();
      a.b.aendern();
      a.lage.fenster = [];
      a.b.aendern();
      await lass(BUENDEL_MS - 1);
      expect(melde(a.hub)).toHaveLength(1);
      await lass(1);
      await fluss();
      const m = melde(a.hub);
      expect(m).toHaveLength(2);
      expect(m[1]!.body).toMatchObject({ bildschirm: 0, fenster: [] });
    });

    it('meldet sofort, wenn der Tab wieder sichtbar wird', async () => {
      const a = await los();
      a.u.dokument.dispatchEvent(new Event('visibilitychange'));
      await fluss();
      expect(melde(a.hub)).toHaveLength(2);
    });

    it('sagt im Hintergrund-Tab „sichtbar: false“', async () => {
      let sichtbar = false;
      const a = await los({ sichtbar: () => sichtbar });
      expect(melde(a.hub)[0]!.body.sichtbar).toBe(false);
      sichtbar = true;
      a.u.dokument.dispatchEvent(new Event('visibilitychange'));
      await fluss();
      expect(melde(a.hub)[1]!.body.sichtbar).toBe(true);
    });

    it('wirft nichts, wenn der Hub nicht antwortet, und versucht es mit dem nächsten Takt wieder', async () => {
      const hub = hubBauen();
      hub.melden = () => {
        throw new TypeError('Failed to fetch');
      };
      const a = await los({ hub });
      expect(melde(hub)).toHaveLength(1);
      await lass(TAKT_MS);
      expect(melde(hub)).toHaveLength(2);
      expect(a.b.sitzungen()).toBeNull();
    });

    it('fragt nach einer abgelaufenen Sitzung (401) nur noch einmal je Minute', async () => {
      const hub = hubBauen();
      hub.melden = () => ({ status: 401, daten: {} });
      const a = await los({ hub });
      expect(melde(hub)).toHaveLength(1);
      expect(a.u.sitzungAbgelaufen).toHaveBeenCalled();
      a.lage.bildschirm = 0;
      a.b.aendern();
      await lass(BUENDEL_MS + 10);
      expect(melde(hub)).toHaveLength(1); // gesperrt
      await lass(LANGSAM_MS);
      expect(melde(hub).length).toBeGreaterThanOrEqual(2); // der Takt probiert es wieder
    });

    it('ein Hub ohne den Weg (404) wird fünf Minuten in Ruhe gelassen — bis „hallo“ zeigt, dass er ihn kennt', async () => {
      const hub = hubBauen();
      hub.melden = () => ({ status: 404, daten: {} });
      const a = await los({ hub });
      expect(melde(hub)).toHaveLength(1);
      a.lage.bildschirm = 0;
      a.b.aendern();
      await lass(BUENDEL_MS + 10);
      expect(melde(hub)).toHaveLength(1);

      hub.melden = () => ({ status: 200, daten: { ok: true, sitzungen: 1 } });
      await lass(2_000); // „hallo“ kommt erst bei einer neuen Verbindung, nicht gleich nach der Meldung
      hub.stroeme[0]!.schicke('retry: 3000\nevent: hallo\ndata: {}\n\n');
      await fluss();
      expect(melde(hub)).toHaveLength(2);
      expect(a.b.sitzungen()).toBe(1);
    });

    it('nach „hallo“ innerhalb von zwei Sekunden nach der Meldung kommt keine zweite', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke('retry: 3000\nevent: hallo\ndata: {}\n\n');
      await fluss();
      expect(melde(a.hub)).toHaveLength(1);
    });

    it('nach einer Wiederverbindung meldet „hallo“ neu — der Hub kann uns inzwischen vergessen haben', async () => {
      const a = await los();
      await lass(5_000);
      a.hub.stroeme[0]!.zu();
      await lass(BACKOFF_MS[0]);
      await fluss();
      expect(a.hub.stroeme).toHaveLength(2);
      const vorher = melde(a.hub).length;
      a.hub.stroeme[1]!.schicke('event: hallo\ndata: {}\n\n');
      await fluss();
      expect(melde(a.hub).length).toBe(vorher + 1);
    });

    it('fasst eine Meldung, die während einer laufenden kommt, zu einer nachfolgenden zusammen', async () => {
      const hub = hubBauen();
      let frei: () => void = () => {};
      const warte = new Promise<void>((r) => (frei = r));
      const echt = hub.fetch.getMockImplementation()!;
      hub.fetch.mockImplementation(async (url, init) => {
        if (init?.method === 'POST' && String(url).includes('melden') && hub.posts.length === 0) {
          const r = echt(url, init);
          await warte; // die erste Meldung hängt
          return r;
        }
        return echt(url, init);
      });
      const a = aufbau({ hub });
      laufend = a;
      a.b.start();
      await fluss();
      expect(melde(hub)).toHaveLength(1);
      void a.b.melden();
      void a.b.melden();
      void a.b.melden();
      await fluss();
      expect(melde(hub)).toHaveLength(1); // wartet auf die laufende
      frei();
      await fluss();
      expect(melde(hub)).toHaveLength(2); // eine einzige danach
    });
  });

  describe('Strom', () => {
    it('öffnet den Strom mit Sitzung und Gerät, Kopf und Anmeldedaten', async () => {
      const a = await los();
      expect(a.hub.gets).toHaveLength(1);
      const g = a.hub.gets[0]!;
      expect(g.url.pathname).toBe(PFAD_STROM);
      expect(g.url.searchParams.get('sitzung')).toBe(a.b.sitzung);
      expect(g.url.searchParams.get('geraet')).toBe('MacBook');
      expect(g.url.searchParams.has('nach')).toBe(false);
      expect(g.init).toMatchObject({ method: 'GET', credentials: 'include', redirect: 'manual' });
      expect(g.init.headers).toMatchObject({ Accept: 'text/event-stream' });
      expect((g.init.headers as Record<string, string>)['Last-Event-ID']).toBeUndefined();
      expect(a.b.status()).toBe('verbunden');
      expect(a.stati).toEqual(['verbindet', 'verbunden']);
    });

    it('verbindet sich nach einem Abbruch neu und schickt die letzte Kennung als Last-Event-ID und ?nach=', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', ziel: 'seite:berichte', alter_s: 0 }, '7-0'));
      await fluss();
      a.hub.stroeme[0]!.zu();
      await fluss();
      expect(a.b.status()).toBe('getrennt');
      await lass(BACKOFF_MS[0]);
      await fluss();
      expect(a.hub.gets).toHaveLength(2);
      const g = a.hub.gets[1]!;
      expect((g.init.headers as Record<string, string>)['Last-Event-ID']).toBe('7-0');
      expect(g.url.searchParams.get('nach')).toBe('7-0');
      expect(a.b.status()).toBe('verbunden');
    });

    it('führt einen Befehl, den der Hub nach der Wiederverbindung noch einmal schickt, nicht zweimal aus', async () => {
      const a = await los();
      const cmd = { id: 'c1', art: 'zeigen', ziel: 'seite:berichte', alter_s: 0 };
      a.hub.stroeme[0]!.schicke(befehlText(cmd, '7-0'));
      await fluss();
      a.hub.stroeme[0]!.zu();
      await lass(BACKOFF_MS[0]);
      await fluss();
      a.hub.stroeme[1]!.schicke(befehlText(cmd, '7-0'));
      await fluss();
      expect(a.zeigen).toHaveBeenCalledTimes(1);
      expect(antworten(a.hub)).toHaveLength(1);
    });

    it('wartet 1, 2, 4, 8, 15, 15 Sekunden zwischen Fehlversuchen', async () => {
      const hub = hubBauen();
      hub.strom = 'fehler';
      const a = await los({ hub });
      await lass(1_000 + 2_000 + 4_000 + 8_000 + 15_000 + 15_000 + 10);
      await fluss();
      const t = hub.gets.map((g) => g.zeit);
      expect(t.length).toBeGreaterThanOrEqual(7);
      expect(t.slice(1, 7).map((z, i) => z - t[i]!)).toEqual([1_000, 2_000, 4_000, 8_000, 15_000, 15_000]);
      expect(a.b.status()).not.toBe('verbunden');
    });

    it('auch ein HTTP-Fehler (500) und eine Antwort ohne Ereignisstrom werden mit Pause wiederholt', async () => {
      const hub = hubBauen();
      hub.strom = 'http500';
      await los({ hub });
      await lass(1_000);
      expect(hub.gets).toHaveLength(2);
      hub.strom = 'kein_strom';
      await lass(2_000);
      await lass(4_000);
      expect(hub.gets.length).toBeGreaterThanOrEqual(4);
      hub.strom = 'offen';
      await lass(8_000);
      await fluss();
      expect(laufend!.b.status()).toBe('verbunden');
    });

    it('geht nach einer stabilen Verbindung (hallo, mindestens 3 s) wieder auf 1 Sekunde zurück', async () => {
      const hub = hubBauen();
      hub.strom = 'fehler';
      await los({ hub });
      await lass(1_000); // Versuch 2 scheitert
      await lass(2_000); // Versuch 3 scheitert
      hub.strom = 'offen';
      await lass(4_000); // Versuch 4: offen
      await fluss();
      expect(hub.stroeme).toHaveLength(1);
      hub.stroeme[0]!.schicke('event: hallo\ndata: {}\n\n');
      await lass(5_000); // hält länger als 3 s
      hub.stroeme[0]!.zu();
      const zu = Date.now();
      await fluss();
      await lass(1_000);
      await fluss();
      expect(hub.stroeme).toHaveLength(2);
      expect(hub.gets.at(-1)!.zeit - zu).toBe(1_000);
    });

    it('eine Verbindung, die gleich wieder abbricht, setzt die Wartezeit nicht zurück', async () => {
      const hub = hubBauen();
      hub.strom = 'fehler';
      await los({ hub });
      await lass(1_000); // Versuch 2 scheitert, nun 2 s
      hub.strom = 'offen';
      await lass(2_000); // Versuch 3 öffnet …
      await fluss();
      hub.stroeme[0]!.schicke('event: hallo\ndata: {}\n\n');
      await lass(500); // … und fällt nach 0,5 s wieder weg
      hub.stroeme[0]!.zu();
      const zu = Date.now();
      await fluss();
      await lass(4_000);
      await fluss();
      expect(hub.gets.at(-1)!.zeit - zu).toBe(4_000);
    });

    it('bricht einen Strom ab, der 40 Sekunden schweigt, und verbindet neu — ein „: ping“ hält ihn am Leben', async () => {
      const a = await los();
      await lass(30_000);
      a.hub.stroeme[0]!.schicke(': ping\n\n');
      await fluss();
      await lass(STILLE_MS - 1_000); // 39 s nach dem Ping
      expect(a.hub.gets).toHaveLength(1);
      expect(a.hub.stroeme[0]!.abgebrochen).toBe(false);
      await lass(1_001); // 40 s Stille
      await fluss();
      expect(a.hub.stroeme[0]!.abgebrochen).toBe(true);
      await lass(BACKOFF_MS[0]);
      await fluss();
      expect(a.hub.gets).toHaveLength(2);
      expect(a.b.status()).toBe('verbunden');
    });

    it('eine abgelaufene Sitzung (401) wird gemeldet, danach wird nur noch jede Minute gefragt', async () => {
      const hub = hubBauen();
      hub.strom = 'http401';
      const a = await los({ hub });
      expect(hub.gets).toHaveLength(1);
      expect(a.b.status()).toBe('sitzung_abgelaufen');
      expect(a.u.sitzungAbgelaufen).toHaveBeenCalledTimes(1);
      await lass(LANGSAM_MS - 1);
      expect(hub.gets).toHaveLength(1);
      await lass(1);
      await fluss();
      expect(hub.gets).toHaveLength(2);
      expect(a.u.sitzungAbgelaufen).toHaveBeenCalledTimes(2); // transport.ts macht daraus nur ein Banner
    });

    it('erkennt die Umleitung zur Anmeldung (opaqueredirect) und die Anmeldeseite mit Status 200', async () => {
      const hub = hubBauen();
      hub.strom = 'umleitung';
      const a = await los({ hub });
      expect(a.b.status()).toBe('sitzung_abgelaufen');
      expect(a.u.sitzungAbgelaufen).toHaveBeenCalledTimes(1);
      hub.strom = 'html';
      await lass(LANGSAM_MS);
      await fluss();
      expect(a.b.status()).toBe('sitzung_abgelaufen');
      expect(a.u.sitzungAbgelaufen).toHaveBeenCalledTimes(2);
    });

    it('nach der Anmeldung (fyos:angemeldet) gleich wieder melden und verbinden, nicht erst nach einer Minute', async () => {
      const hub = hubBauen();
      hub.strom = 'umleitung';
      const a = await los({ hub });
      expect(a.b.status()).toBe('sitzung_abgelaufen');
      const vorher = melde(hub).length;
      hub.strom = 'offen';
      a.u.fenster.dispatchEvent(new Event(ANGEMELDET_EREIGNIS));
      await fluss();
      expect(hub.gets).toHaveLength(2);
      expect(a.b.status()).toBe('verbunden');
      expect(melde(hub).length).toBeGreaterThan(vorher);
    });

    it('im Browser heißt „keine Anmeldung“: einmal „Anmelden“ anbieten, nicht das rote Banner (innen lädt alles andere weiter)', () => {
      let n = 0;
      const h = () => {
        n += 1;
      };
      window.addEventListener(ANMELDE_EREIGNIS, h);
      try {
        echteUmgebung().sitzungAbgelaufen();
      } finally {
        window.removeEventListener(ANMELDE_EREIGNIS, h);
      }
      expect(n).toBe(1);
    });

    it('ein Hub ohne den Strom (404) wird nur jede Minute gefragt', async () => {
      const hub = hubBauen();
      hub.strom = 'nicht_da';
      const a = await los({ hub });
      expect(a.b.status()).toBe('getrennt');
      await lass(LANGSAM_MS - 1);
      expect(hub.gets).toHaveLength(1);
      hub.strom = 'offen';
      await lass(1);
      await fluss();
      expect(hub.gets).toHaveLength(2);
      expect(a.b.status()).toBe('verbunden');
    });

    it('liest UTF-8 über Stückgrenzen hinweg (ü mitten im Byte-Paar)', async () => {
      const a = await los();
      const bytes = new TextEncoder().encode(befehlText(zeigtBefehl('u1', { titel: 'Neue Einträge', vorschau: 'Entwurf 😀' })));
      const ue = bytes.indexOf(0xc3); // erstes Byte von „ü“
      const smiley = bytes.indexOf(0xf0);
      a.hub.stroeme[0]!.schicke(bytes.slice(0, ue + 1));
      await fluss();
      a.hub.stroeme[0]!.schicke(bytes.slice(ue + 1, smiley + 2));
      await fluss();
      a.hub.stroeme[0]!.schicke(bytes.slice(smiley + 2));
      await fluss();
      expect(a.zeigt).toHaveBeenCalledTimes(1);
      expect(a.zeigt.mock.calls[0]![0]).toMatchObject({ titel: 'Neue Einträge', vorschau: 'Entwurf 😀' });
    });
  });

  describe('Befehl „zeigen“', () => {
    it('öffnet die Fläche und antwortet mit dem Ergebnis', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', ziel: 'seite:berichte', eingabe: { jahr: 2026 }, von: 'agent', alter_s: 1 }, '1-0'));
      await fluss();
      expect(a.zeigen).toHaveBeenCalledWith('seite:berichte', { jahr: 2026 });
      const r = antworten(a.hub);
      expect(r).toHaveLength(1);
      expect(r[0]!.body).toEqual({ sitzung: a.b.sitzung, befehl: 'c1', ok: true, ergebnis: { gezeigt: true, ziel: 'seite:berichte', titel: 'Berichte', bildschirm: 1 } });
      expect(r[0]!.init).toMatchObject({ credentials: 'include', redirect: 'manual' });
    });

    it('gibt ohne Eingabe null weiter und ignoriert eine Eingabe, die kein Objekt ist', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', ziel: 'agent', alter_s: 0 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c2', art: 'zeigen', ziel: 'agent', eingabe: ['x'], alter_s: 0 }));
      await fluss();
      expect(a.zeigen.mock.calls).toEqual([
        ['agent', null],
        ['agent', null],
      ]);
    });

    it('antwortet mit dem Fehler, wenn das Öffnen nicht ging oder wirft', async () => {
      const a = await los();
      a.zeigen.mockResolvedValueOnce({ ok: false, fehler: 'Keine Fläche passt zu „Quanten“.' });
      a.zeigen.mockRejectedValueOnce(new Error('kaputt'));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', ziel: 'Quanten', alter_s: 0 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c2', art: 'zeigen', ziel: 'Berichte', alter_s: 0 }));
      await fluss();
      expect(antworten(a.hub).map((p) => p.body)).toEqual([
        { sitzung: a.b.sitzung, befehl: 'c1', ok: false, fehler: 'Keine Fläche passt zu „Quanten“.' },
        { sitzung: a.b.sitzung, befehl: 'c2', ok: false, fehler: 'kaputt' },
      ]);
    });

    it('fordert ein Ziel', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', alter_s: 0 }));
      await fluss();
      expect(a.zeigen).not.toHaveBeenCalled();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ befehl: 'c1', ok: false, fehler: 'ziel fehlt' });
    });

    it('antwortet nach 12 Sekunden mit einer Zeitüberschreitung, wenn das Öffnen hängt', async () => {
      const a = await los();
      a.zeigen.mockImplementationOnce(() => new Promise(() => {}));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'zeigen', ziel: 'seite:berichte', alter_s: 0 }));
      await fluss();
      await lass(AUSFUEHREN_MAX_MS - 1);
      expect(antworten(a.hub)).toHaveLength(0);
      await lass(1);
      await fluss();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ befehl: 'c1', ok: false });
      expect(String(antworten(a.hub)[0]!.body.fehler)).toMatch(/Zeitüberschreitung/);
    });

    it('verwirft einen Befehl, der älter als 8 Sekunden ist — danach hat der Hub schon „keine Bestätigung“ gemeldet', async () => {
      expect(ALTER_ZEIGEN_S).toBe(8); // = ZEIGEN_FRIST_S in mcp_hub/os_bruecke.py
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'alt', art: 'zeigen', ziel: 'seite:berichte', alter_s: ALTER_ZEIGEN_S + 1 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'schlafender-tab', art: 'zeigen', ziel: 'seite:berichte', alter_s: 40 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'grenze', art: 'zeigen', ziel: 'seite:berichte', alter_s: ALTER_ZEIGEN_S }));
      await fluss();
      expect(a.zeigen).toHaveBeenCalledTimes(1);
      expect(antworten(a.hub).map((p) => p.body.befehl)).toEqual(['grenze']);
    });
  });

  describe('Befehl „ausfuehren“', () => {
    const cmd = (id: string, extra: object = {}) => ({ id, art: 'ausfuehren', werkzeug: 'os_fenster', argumente: { a: 1 }, alter_s: 0, ...extra });

    it('ruft das Werkzeug und antwortet mit dessen MCP-Ergebnis', async () => {
      const a = await los();
      const ergebnis: ToolErgebnis = { content: [{ type: 'text', text: '{"fenster":[1]}' }], structuredContent: { fenster: [1] } };
      a.ausfuehren.mockResolvedValueOnce(ergebnis);
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      await fluss();
      expect(a.ausfuehren).toHaveBeenCalledWith('os_fenster', { a: 1 });
      expect(antworten(a.hub)[0]!.body).toEqual({ sitzung: a.b.sitzung, befehl: 'c1', ok: true, ergebnis });
    });

    it('gibt ein leeres Objekt, wenn keine Argumente kommen', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1', { argumente: null })));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c2', { argumente: 'x' })));
      await fluss();
      expect(a.ausfuehren.mock.calls.map((c) => c[1])).toEqual([{}, {}]);
    });

    it('macht aus isError ein ok:false mit dem Text als Fehler', async () => {
      const a = await los();
      const ergebnis: ToolErgebnis = { content: [{ type: 'text', text: 'Kein offenes Fenster.' }], isError: true };
      a.ausfuehren.mockResolvedValueOnce(ergebnis);
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      await fluss();
      expect(antworten(a.hub)[0]!.body).toEqual({ sitzung: a.b.sitzung, befehl: 'c1', ok: false, ergebnis, fehler: 'Kein offenes Fenster.' });
    });

    it('antwortet auch bei einem Wurf', async () => {
      const a = await los();
      a.ausfuehren.mockRejectedValueOnce(new Error('Absturz im Werkzeug'));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      await fluss();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ befehl: 'c1', ok: false, fehler: 'Absturz im Werkzeug' });
    });

    it('fordert ein Werkzeug', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1', { werkzeug: '' })));
      await fluss();
      expect(a.ausfuehren).not.toHaveBeenCalled();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ ok: false, fehler: 'werkzeug fehlt' });
    });

    it('gibt nach 12 Sekunden auf', async () => {
      const a = await los();
      a.ausfuehren.mockImplementationOnce(() => new Promise(() => {}));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      await fluss();
      await lass(AUSFUEHREN_MAX_MS);
      await fluss();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ befehl: 'c1', ok: false });
      expect(String(antworten(a.hub)[0]!.body.fehler)).toMatch(/Zeitüberschreitung: Werkzeug os_fenster/);
    });

    it('verwirft einen Befehl, der älter als 15 Sekunden ist', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText(cmd('alt', { alter_s: ALTER_AUSFUEHREN_S + 1 })));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('grenze', { alter_s: ALTER_AUSFUEHREN_S })));
      await fluss();
      expect(a.ausfuehren).toHaveBeenCalledTimes(1);
      expect(antworten(a.hub).map((p) => p.body.befehl)).toEqual(['grenze']);
    });

    it('arbeitet Befehle nacheinander ab — „zeigt“ geht am Stapel vorbei', async () => {
      const a = await los();
      let fertig: (e: ToolErgebnis) => void = () => {};
      a.ausfuehren.mockImplementationOnce(() => new Promise<ToolErgebnis>((r) => (fertig = r)));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c2')));
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('z1')));
      await fluss();
      expect(a.ausfuehren).toHaveBeenCalledTimes(1); // c2 wartet
      expect(a.zeigt).toHaveBeenCalledTimes(1); // „zeigt“ nicht
      fertig({ content: [{ type: 'text', text: 'ok' }] });
      await fluss();
      expect(a.ausfuehren).toHaveBeenCalledTimes(2);
      expect(antworten(a.hub).map((p) => p.body.befehl)).toEqual(['c1', 'c2']);
    });

    it('legt eine Antwort, die am Netz scheitert, einmal nach', async () => {
      const a = await los();
      a.hub.antwortFehler = 1;
      a.hub.stroeme[0]!.schicke(befehlText(cmd('c1')));
      await fluss();
      expect(antworten(a.hub)).toHaveLength(2);
      expect(antworten(a.hub).map((p) => p.body.befehl)).toEqual(['c1', 'c1']);
    });
  });

  describe('Befehl „zeigt“ (Der Agent zeigt dir …)', () => {
    it('gibt die geprüfte Nutzlast weiter und antwortet nicht', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('z1', { untertitel: '  Privat ', eingabe: { eintrag: 'Entwurf' }, link: 'https://x/os?offen=a' })));
      await fluss();
      expect(a.zeigt).toHaveBeenCalledTimes(1);
      expect(a.zeigt.mock.calls[0]![0]).toEqual({
        ziel: 'app:notizen__liste',
        app: 'notizen__liste',
        titel: 'Notizen',
        untertitel: 'Privat',
        symbol: null,
        ton: null,
        vorschau: '3 Einträge neu',
        eingabe: { eintrag: 'Entwurf' },
        link: 'https://x/os?offen=a',
        audio: null,
        dringlichkeit: null,
      });
      expect(antworten(a.hub)).toHaveLength(0);
    });

    it('übergeht eine Nutzlast ohne Ziel', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'z1', art: 'zeigt', zeigt: { titel: 'ohne Ziel' }, alter_s: 0 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'z2', art: 'zeigt', alter_s: 0 }));
      await fluss();
      expect(a.zeigt).not.toHaveBeenCalled();
    });

    it('verwirft eine, die älter als 60 Sekunden ist — eine Mitteilung darf länger liegen als ein Öffnen-Befehl', async () => {
      expect(ALTER_ZEIGT_S).toBe(60);
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('alt', {}, ALTER_ZEIGT_S + 1)));
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('mittel', {}, ALTER_ZEIGEN_S + 10))); // für „zeigen“ schon zu alt
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('grenze', {}, ALTER_ZEIGT_S)));
      await fluss();
      expect(a.zeigt).toHaveBeenCalledTimes(2);
    });

    it('ein Wurf im Anzeigen stört den Strom nicht', async () => {
      const a = await los();
      a.zeigt.mockImplementationOnce(() => {
        throw new Error('Anzeige kaputt');
      });
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('z1')));
      a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl('z2')));
      await fluss();
      expect(a.zeigt).toHaveBeenCalledTimes(2);
      expect(a.b.status()).toBe('verbunden');
    });
  });

  describe('Befehle allgemein', () => {
    it('antwortet auf eine unbekannte Art, damit der Hub nicht wartet', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'tanzen', alter_s: 0 }));
      await fluss();
      expect(antworten(a.hub)[0]!.body).toMatchObject({ befehl: 'c1', ok: false, fehler: 'Unbekannte Befehlsart: tanzen' });
    });

    it('übergeht Kaputtes: kein JSON, keine ID, kein Objekt', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke('event: befehl\ndata: {kaputt\n\n');
      a.hub.stroeme[0]!.schicke('event: befehl\ndata: "text"\n\n');
      a.hub.stroeme[0]!.schicke('event: befehl\ndata: null\n\n');
      a.hub.stroeme[0]!.schicke(befehlText({ art: 'zeigen', ziel: 'x' }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: '', art: 'zeigen', ziel: 'x' }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 7, art: 'zeigen', ziel: 'x' }));
      await fluss();
      expect(a.zeigen).not.toHaveBeenCalled();
      expect(antworten(a.hub)).toHaveLength(0);
      expect(a.b.status()).toBe('verbunden');
    });

    it('übergeht Ereignisse, die kein „befehl“ sind', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke(`event: irgendwas\ndata: ${JSON.stringify({ id: 'c1', art: 'zeigen', ziel: 'x' })}\n\n`);
      a.hub.stroeme[0]!.schicke(`data: ${JSON.stringify({ id: 'c2', art: 'zeigen', ziel: 'x' })}\n\n`);
      await fluss();
      expect(a.zeigen).not.toHaveBeenCalled();
    });

    it('merkt sich die letzten 100 Befehls-IDs: ein Wiederholer läuft nicht zweimal, ein sehr alter schon', async () => {
      const a = await los();
      const schick = async (id: string) => {
        a.hub.stroeme[0]!.schicke(befehlText(zeigtBefehl(id)));
        await fluss();
      };
      await schick('erster');
      expect(a.zeigt).toHaveBeenCalledTimes(1);
      await schick('erster'); // gleich noch einmal
      expect(a.zeigt).toHaveBeenCalledTimes(1);
      for (let i = 1; i < GESEHEN_MAX - 1; i++) await schick(`x${i}`); // 98 weitere: „erster“ ist noch drin
      expect(a.zeigt).toHaveBeenCalledTimes(1 + (GESEHEN_MAX - 2));
      await schick('erster');
      expect(a.zeigt).toHaveBeenCalledTimes(1 + (GESEHEN_MAX - 2));
      await schick('x-a'); // 100. weitere ID (die Liste ist voll) …
      await schick('x-b'); // … und die 101.: „erster“ fliegt heraus
      await schick('erster');
      expect(a.zeigt).toHaveBeenCalledTimes(1 + (GESEHEN_MAX - 2) + 2 + 1);
    });
  });

  describe('Start und Ende', () => {
    it('startet nicht in einem ferngesteuerten Browser — außer der Schalter steht auf „an“', async () => {
      const gesperrt = aufbau({ nav: { webdriver: true } });
      laufend = gesperrt;
      expect(gesperrt.b.start()).toBe(false);
      expect(gesperrt.b.gesperrt()).toBe('webdriver');
      expect(gesperrt.b.status()).toBe('aus');
      await fluss();
      expect(gesperrt.hub.fetch).not.toHaveBeenCalled();

      const frei = await los({ nav: { webdriver: true }, lokal: { [SCHALTER]: 'an' } });
      expect(frei.b.gesperrt()).toBeNull();
      expect(frei.hub.posts.length).toBeGreaterThan(0);
    });

    it('der Schalter „aus“ hält die Brücke an', async () => {
      const a = aufbau({ lokal: { [SCHALTER]: 'aus' } });
      laufend = a;
      expect(a.b.start()).toBe(false);
      expect(a.b.gesperrt()).toBe('schalter');
      await lass(TAKT_MS * 2);
      expect(a.hub.fetch).not.toHaveBeenCalled();
    });

    it('startet nicht in der Testumgebung (jsdom)', async () => {
      const a = aufbau({ nav: { userAgent: 'Mozilla/5.0 (linux) AppleWebKit/537.36 (KHTML, like Gecko) jsdom/24.0.0' } });
      laufend = a;
      expect(a.b.start()).toBe(false);
      expect(a.b.gesperrt()).toBe('testumgebung');
    });

    it('ein zweiter Start ändert nichts', async () => {
      const a = await los();
      expect(a.b.start()).toBe(true);
      await fluss();
      expect(a.hub.gets).toHaveLength(1);
      expect(melde(a.hub)).toHaveLength(1);
    });

    it('stop() sagt dem Hub „Ende“ (sendBeacon), schließt den Strom und hört auf', async () => {
      const a = await los();
      a.b.stop();
      expect(a.b.status()).toBe('aus');
      await fluss();
      expect(a.hub.stroeme[0]!.abgebrochen).toBe(true);
      expect(a.u.beacons).toHaveLength(1);
      const { url, daten } = a.u.beacons[0]!;
      expect(url).toBe(`${API_BASE}${PFAD_MELDEN}`);
      const blob = daten as Blob;
      expect(blob.type).toBe('application/json');
      expect(JSON.parse(await blobText(blob))).toEqual({ sitzung: a.b.sitzung, ende: true, gesendet: START });
      const gets = a.hub.gets.length;
      const posts = a.hub.posts.length;
      await lass(TAKT_MS * 3);
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      a.u.dokument.dispatchEvent(new Event('visibilitychange'));
      await fluss();
      expect(a.hub.gets.length).toBe(gets);
      expect(a.hub.posts.length).toBe(posts);
      expect(a.u.beacons).toHaveLength(1);
    });

    it('beim Verlassen der Seite (pagehide) kommt ein „Ende“ — ohne dass die Brücke anhält', async () => {
      const a = await los();
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      expect(a.u.beacons).toHaveLength(1);
      expect(a.b.status()).toBe('verbunden');
    });

    it('ohne sendBeacon geht das „Ende“ als fetch mit keepalive', async () => {
      const a = await los({ beacon: false });
      a.b.stop();
      await fluss();
      const ende = a.hub.posts.at(-1)!;
      expect(ende.pfad).toBe(PFAD_MELDEN);
      expect(ende.body).toEqual({ sitzung: a.b.sitzung, ende: true, gesendet: START });
      expect(ende.init.keepalive).toBe(true);
    });

    it('Meldung und „Ende“ tragen die Uhr des Browsers: das Ende ist später als jede Meldung davor', async () => {
      // So erkennt der Hub eine Meldung, die beim Schließen des Tabs noch unterwegs war und nach dem Ende ankommt.
      const a = await los();
      await lass(TAKT_MS);
      await lass(12_345);
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      const gesendet = melde(a.hub).map((p) => (p.body as { gesendet: number }).gesendet);
      expect(gesendet).toEqual([START, START + TAKT_MS]);
      const ende = JSON.parse(await blobText(a.u.beacons[0]!.daten as Blob)) as { gesendet: number; ende: boolean };
      expect(ende).toMatchObject({ ende: true, gesendet: START + TAKT_MS + 12_345 });
      expect(ende.gesendet).toBeGreaterThan(Math.max(...gesendet));
    });

    it('nach pagehide schweigt die Brücke: das visibilitychange, das Chrome beim Schließen nachschickt, meldet nichts', async () => {
      // Im echten Chrome gemessen: pagehide → (Ende) → visibilitychange:hidden → Meldung. Ohne diese Sperre öffnete
      // die späte Meldung den geschlossenen Tab für 90 s neu beim Hub.
      const a = await los({ sichtbar: () => false });
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      a.u.dokument.dispatchEvent(new Event('visibilitychange'));
      a.b.aendern();
      await fluss();
      await lass(BUENDEL_MS + TAKT_MS + 100);
      expect(melde(a.hub)).toHaveLength(1); // nur die erste Meldung vom Start
      expect(a.hub.posts.filter((p) => (p.body as { ende?: boolean }).ende)).toHaveLength(0); // das Ende ging als Beacon
      expect(a.u.beacons).toHaveLength(1);
    });

    it('ein pageshow ohne bfcache (persisted: false) macht die Brücke nicht wieder gesprächig', async () => {
      const a = await los();
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      a.u.fenster.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: false }));
      await fluss();
      await lass(TAKT_MS * 2);
      expect(melde(a.hub)).toHaveLength(1);
    });

    it('zurück aus dem bfcache (pageshow, persisted) meldet wieder, mit späterer Uhr als das Ende', async () => {
      const a = await los();
      await lass(5_000);
      a.u.fenster.dispatchEvent(new Event('pagehide'));
      const ende = JSON.parse(await blobText(a.u.beacons[0]!.daten as Blob)) as { gesendet: number };
      await lass(20_000);
      a.u.fenster.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }));
      await fluss();
      const m = melde(a.hub);
      expect(m).toHaveLength(2);
      expect((m[1]!.body as { gesendet: number }).gesendet).toBeGreaterThan(ende.gesendet);
      await lass(TAKT_MS); // und der Takt läuft wieder
      expect(melde(a.hub)).toHaveLength(3);
    });

    it('die Uhr in der Meldung zählt nicht als Änderung: gleiche Lage, nichts Neues beim Hub', async () => {
      const a = await los();
      await lass(BUENDEL_MS + 10);
      a.b.aendern();
      await lass(BUENDEL_MS + 10);
      expect(melde(a.hub)).toHaveLength(1);
    });

    it('stop() im Warten zwischen zwei Versuchen weckt die Schleife und beendet sie', async () => {
      const hub = hubBauen();
      hub.strom = 'fehler';
      const a = await los({ hub });
      a.b.stop();
      const gets = hub.gets.length;
      await lass(60_000);
      expect(hub.gets.length).toBe(gets);
    });

    it('nach stop() kann die Brücke wieder starten und baut Meldung und Strom neu auf', async () => {
      const a = await los();
      a.b.stop();
      expect(a.b.start()).toBe(true);
      await fluss();
      expect(a.hub.stroeme).toHaveLength(2);
      expect(melde(a.hub)).toHaveLength(2);
      expect(a.b.status()).toBe('verbunden');
    });
  });

  describe('Härtung: Hub-Wissen, Antworten, Fristen', () => {
    it('„hallo“ mit bekannt:false meldet sofort — auch wenn die letzte Meldung eben erst war (Hub hat uns vergessen)', async () => {
      const a = await los();
      expect(melde(a.hub)).toHaveLength(1);
      a.hub.stroeme[0]!.schicke('event: hallo\ndata: {"bekannt":false}\n\n');
      await fluss();
      expect(melde(a.hub)).toHaveLength(2);
    });

    it('„hallo“ mit bekannt:true (oder ohne Angabe) und frischer Meldung löst keine zweite aus', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke('event: hallo\ndata: {"bekannt":true}\n\n');
      await fluss();
      expect(melde(a.hub)).toHaveLength(1);
    });

    it('eine gescheiterte Meldung zählt nicht als gemeldet: „hallo“ meldet gleich noch einmal', async () => {
      const hub = hubBauen();
      hub.melden = () => ({ status: 500, daten: {} });
      const a = await los({ hub });
      expect(melde(hub)).toHaveLength(1);
      hub.melden = () => ({ status: 200, daten: { ok: true, sitzungen: 1 } });
      hub.stroeme[0]!.schicke('event: hallo\ndata: {}\n\n'); // < 2 s nach dem Versuch, aber der war nicht angekommen
      await fluss();
      expect(melde(hub)).toHaveLength(2);
      expect(a.b.sitzungen()).toBe(1);
    });

    it('legt eine Antwort nach einem 5xx des Hubs nach kurzer Pause noch einmal ab', async () => {
      const a = await los();
      const echt = a.hub.fetch.getMockImplementation()!;
      let n = 0;
      a.hub.fetch.mockImplementation(async (url, init) => {
        if (init?.method === 'POST' && String(url).includes('antwort') && n++ === 0) {
          a.hub.posts.push({ pfad: PFAD_ANTWORT, body: JSON.parse(String(init.body)), init, zeit: Date.now() });
          return { ok: false, status: 503, type: 'basic', headers: new Headers(), json: async () => ({}) } as unknown as Response;
        }
        return echt(url, init);
      });
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'ausfuehren', werkzeug: 'os_fenster', alter_s: 0 }));
      await fluss();
      expect(antworten(a.hub)).toHaveLength(1); // noch in der Pause
      await lass(500);
      await fluss();
      expect(antworten(a.hub)).toHaveLength(2);
      expect(warn).not.toHaveBeenCalled(); // der zweite Versuch kam an
      warn.mockRestore();
    });

    it('meldet im Fehlerfall, dass eine Antwort nicht ankam (Warnung statt Schweigen) — und wiederholt eine 4xx nicht', async () => {
      const a = await los();
      const echt = a.hub.fetch.getMockImplementation()!;
      a.hub.fetch.mockImplementation(async (url, init) => {
        if (init?.method === 'POST' && String(url).includes('antwort')) {
          a.hub.posts.push({ pfad: PFAD_ANTWORT, body: JSON.parse(String(init.body)), init, zeit: Date.now() });
          return { ok: false, status: 409, type: 'basic', headers: new Headers(), json: async () => ({}) } as unknown as Response;
        }
        return echt(url, init);
      });
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'c1', art: 'ausfuehren', werkzeug: 'os_fenster', alter_s: 0 }));
      await fluss();
      await lass(1_000);
      expect(antworten(a.hub)).toHaveLength(1);
      expect(warn).toHaveBeenCalledTimes(1);
      expect(String(warn.mock.calls[0]![0])).toMatch(/c1.*HTTP 409/);
      warn.mockRestore();
    });

    it('prüft das Alter eines Befehls auch beim Start: was in der Schlange lange wartete, läuft nicht mehr', async () => {
      const a = await los();
      a.ausfuehren.mockImplementationOnce(() => new Promise<ToolErgebnis>(() => {})); // hängt bis zur Frist (12 s)
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'haengt', art: 'ausfuehren', werkzeug: 'os_fenster', alter_s: 0 }));
      a.hub.stroeme[0]!.schicke(befehlText({ id: 'wartet', art: 'zeigen', ziel: 'seite:berichte', alter_s: 0 }));
      await fluss();
      await lass(AUSFUEHREN_MAX_MS);
      await fluss();
      // „haengt“ endet mit Zeitüberschreitung; „wartet“ ist nun 12 s alt und damit über den 8 s des Hubs: kein Geisterfenster
      expect(a.zeigen).not.toHaveBeenCalled();
      expect(antworten(a.hub).map((p) => p.body.befehl)).toEqual(['haengt']);
    });

    it('der Hub-Abbruch (event: abbruch) zählt nicht als stabile Verbindung: die Wartezeit wächst weiter', async () => {
      const hub = hubBauen();
      hub.strom = 'fehler';
      await los({ hub });
      await lass(1_000); // Versuch 2 scheitert
      hub.strom = 'offen';
      await lass(2_000); // Versuch 3 öffnet
      await fluss();
      hub.stroeme[0]!.schicke('event: hallo\ndata: {}\n\n');
      await lass(5_000); // länger als STABIL_MS …
      hub.stroeme[0]!.schicke('event: abbruch\ndata: {"grund":"redis"}\n\n');
      hub.stroeme[0]!.zu();
      const zu = Date.now();
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      await fluss();
      await lass(4_000);
      await fluss();
      expect(hub.gets.at(-1)!.zeit - zu).toBe(4_000); // … trotzdem keine Rückkehr auf 1 s
      expect(warn).toHaveBeenCalled();
      warn.mockRestore();
    });
  });

  describe('Härtung: Wiederverbindung (Jitter, retry, verdeckter Tab)', () => {
    /** Zeit zwischen dem Ende des Stroms und dem nächsten Versuch */
    const pause = async (a: Aufbau, hoechstens = 60_000): Promise<number> => {
      a.hub.stroeme[0]!.zu();
      const zu = Date.now();
      const vorher = a.hub.gets.length;
      await fluss();
      for (let t = 0; t < hoechstens && a.hub.gets.length === vorher; t += 10) await lass(10);
      return a.hub.gets.at(-1)!.zeit - zu;
    };

    it('streut die Pause auf die obere Hälfte der Stufe (zufall 0 → halbe Stufe)', async () => {
      const a = await los({ zufall: () => 0 });
      expect(await pause(a)).toBe(BACKOFF_MS[0] / 2);
    });

    it('das retry des Hubs ist die Untergrenze der Pause', async () => {
      const a = await los({ zufall: () => 0 });
      a.hub.stroeme[0]!.schicke('retry: 3000\nevent: hallo\ndata: {}\n\n');
      await fluss();
      expect(await pause(a)).toBe(3_000);
    });

    it('ein irrsinniges retry wird gedeckelt', async () => {
      const a = await los();
      a.hub.stroeme[0]!.schicke('retry: 99999999\nevent: hallo\ndata: {}\n\n');
      await fluss();
      expect(await pause(a, 120_000)).toBe(VERDECKT_MAX_MS);
    });

    it('im verdeckten Tab ist die Pause doppelt so lang', async () => {
      let sichtbar = true;
      const a = await los({ sichtbar: () => sichtbar });
      sichtbar = false;
      expect(await pause(a)).toBe(BACKOFF_MS[0] * 2);
    });

    it('wird der verdeckte Tab wieder sichtbar, endet die Pause sofort', async () => {
      let sichtbar = true;
      const a = await los({ sichtbar: () => sichtbar });
      sichtbar = false;
      a.hub.stroeme[0]!.zu();
      await fluss();
      expect(a.hub.gets).toHaveLength(1);
      await lass(500);
      sichtbar = true;
      a.u.dokument.dispatchEvent(new Event('visibilitychange'));
      await fluss();
      expect(a.hub.gets).toHaveLength(2);
    });
  });

  describe('Härtung: Tab duplizieren (BroadcastChannel)', () => {
    /** Ein Bus wie BroadcastChannel: jeder Kanal hört, was die anderen senden, nicht sich selbst */
    const bus = () => {
      const alle: (KanalKurz & { zu: boolean })[] = [];
      return () => {
        const k = {
          onmessage: null as KanalKurz['onmessage'],
          zu: false,
          postMessage(d: unknown) {
            for (const o of alle) if (o !== k && !o.zu) o.onmessage?.({ data: d } as MessageEvent);
          },
          close() {
            k.zu = true;
          },
        } as KanalKurz & { zu: boolean };
        alle.push(k);
        return k;
      };
    };

    it('wartet mit der ersten Meldung, bis geklärt ist, ob ein anderer Tab die ID führt', async () => {
      const a = aufbau({ kanal: bus(), sitzungId: 's-aaaaaaaaaa' });
      laufend = a;
      a.b.start();
      await fluss();
      expect(melde(a.hub)).toHaveLength(0);
      await lass(DUPLIKAT_WARTE_MS - 1);
      expect(melde(a.hub)).toHaveLength(0);
      await lass(1);
      await fluss();
      expect(melde(a.hub)).toHaveLength(1);
      expect(a.hub.gets).toHaveLength(1);
      expect(a.b.sitzung).toBe('s-aaaaaaaaaa');
    });

    it('ein duplizierter Tab (gleiche ID, später gestartet) bekommt eine neue ID, der ältere behält seine', async () => {
      const kanal = bus();
      const alt = aufbau({ kanal, sitzungId: 's-aaaaaaaaaa' });
      laufend = alt;
      alt.b.start();
      await lass(DUPLIKAT_WARTE_MS + 10);
      await fluss();
      expect(melde(alt.hub)).toHaveLength(1);

      await lass(1_000);
      const neu = aufbau({ kanal, sitzungId: 's-aaaaaaaaaa' });
      expect(neu.b.sitzung).toBe('s-aaaaaaaaaa');
      expect(neu.b.start()).toBe(true);
      await lass(DUPLIKAT_WARTE_MS + 10);
      await fluss();
      expect(neu.b.sitzung).not.toBe('s-aaaaaaaaaa');
      expect(neu.b.sitzung).toMatch(/^s-[a-z0-9]{10}$/);
      expect(alt.b.sitzung).toBe('s-aaaaaaaaaa');
      expect((melde(neu.hub)[0]!.body as { sitzung: string }).sitzung).toBe(neu.b.sitzung);
      expect(neu.hub.gets[0]!.url.searchParams.get('sitzung')).toBe(neu.b.sitzung);
      neu.b.stop();
    });

    it('stop() schließt den Kanal', async () => {
      const kanal = bus();
      let offen: (KanalKurz & { zu?: boolean }) | null = null;
      const a = aufbau({ kanal: () => (offen = kanal()) });
      laufend = a;
      a.b.start();
      await fluss();
      a.b.stop();
      expect((offen as unknown as { zu: boolean }).zu).toBe(true);
    });
  });
});
