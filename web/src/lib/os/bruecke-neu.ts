/**
 * bruecke-neu.ts — die volle OS-Brücke (Protokoll v1, docs/HUB-VERTRAG.md): der Agent wirkt auf das offene OS.
 *
 * Gegenstück zur schlanken `bruecke.ts` (die nur pollt und Mitteilungen zeigt): diese Brücke ist Duplex.
 * Das offene /os meldet sich beim Hub an und hört auf Befehle:
 *
 *   POST /hub-api/os/melden    „ich bin MacBook, das sind meine Fenster, Flächen und Werkzeuge“ —
 *                              sofort, dann alle 30 s und bei Änderungen (gebündelt nach 1,5 s).
 *                              Jede Meldung trägt `gesendet` (Uhr des Browsers, ms). Beim Verlassen der Seite
 *                              (`pagehide`) geht `{sitzung, ende: true, gesendet}`, danach schweigt die Brücke bis
 *                              zum `pageshow` aus dem bfcache (Chrome löst nach `pagehide` noch `visibilitychange`
 *                              aus, und die Meldung daraus öffnete den geschlossenen Tab für 90 s neu). Eine
 *                              Meldung, die vor dem Ende abgeschickt wurde, aber danach ankommt, lässt der Hub
 *                              nicht wieder aufleben (Antwort `veraltet`).
 *   GET  /hub-api/os/strom     Server-Sent Events: `hallo`, danach `befehl`; zwischendurch `: ping`
 *   POST /hub-api/os/antwort   das Ergebnis eines Befehls (zeigen, ausfuehren)
 *
 * Befehle (Ereignis `befehl`, data = JSON; `alter_s` = Alter beim Ausliefern):
 *   zeigen     {id, art, ziel, eingabe?}          Fläche öffnen → Antwort {gezeigt, ziel, titel, bildschirm}
 *   ausfuehren {id, art, werkzeug, argumente?}    Seitenwerkzeug aus lib/werkzeuge.ts → Antwort = dessen Ergebnis
 *   zeigt      {id, art, zeigt: {…}}              „Der Agent zeigt dir …“ (Mitteilung), keine Antwort
 * Älter als 8 s (zeigen), 15 s (ausfuehren) bzw. 60 s (zeigt) wird verworfen — niemand wartet mehr darauf:
 * der Hub gibt bei `zeigen` nach 8 s auf (`ZEIGEN_FRIST_S` im Hub, `ausfuehren` nach 15 s) und
 * meldet „keine Bestätigung“ samt Link zurück, ein Tab, der später aufwacht, soll nicht noch von selbst öffnen
 * (Geisterfenster). Das Alter zählt beim START des Befehls, nicht beim Empfang: `alter_s` vom Hub plus die Zeit, die
 * er hier in der Schlange stand. Eine Mitteilung (`zeigt`) darf länger liegen.
 * Befehls-IDs der letzten 100 werden gemerkt: ein wiederholter Befehl (Wiederverbindung mit
 * Last-Event-ID) läuft nie zweimal. Befehle laufen nacheinander; „zeigt“ geht am Stapel vorbei.
 *
 * Gelesen wird der Strom mit `fetch` + ReadableStream, nicht mit EventSource: EventSource sieht
 * weder eine Umleitung zur Anmeldung (302/401 hinter einem Anmelde-Proxy) noch kann es
 * `Last-Event-ID` selbst setzen, und es lässt sich schlecht testen. Wiederverbindung: Wartezeit
 * 1 → 2 → 4 → 8 → 15 s, je mit Streuung (die Hälfte bis das Ganze, damit nach einem Neustart des Hubs nicht alle Tabs
 * im selben Moment kommen), nie unter dem `retry`, das der Hub im Strom nennt, im verdeckten Tab doppelt so lang
 * (höchstens 30 s; der Strom bleibt, damit der Agent das OS weiter erreicht, und beim Sichtbarwerden verbindet die
 * Brücke sofort). Sie fällt auf 1 s zurück, wenn die Verbindung `hallo` gebracht und mindestens 3 s gehalten hat;
 * `event: abbruch` (der Hub gibt den Strom auf) zählt als Fehlschlag. Sagt `hallo` `bekannt: false`
 * (der Hub kennt die Sitzung nicht mehr), wird sofort gemeldet. Schweigt der Strom 40 s (nicht einmal ein `: ping`),
 * wird er abgebrochen und neu aufgebaut. Keine Anmeldung (opaqueredirect, 401, HTML statt Strom): das OS kann dann
 * einmal „Anmelden“ anbieten (ANMELDE_EREIGNIS), die Brücke versucht es nur noch alle 60 s — und sofort wieder,
 * sobald ANGEMELDET_EREIGNIS kommt.
 *
 * Sitzungs-ID: eine je Tab (sessionStorage). „Tab duplizieren“ kopiert den Speicher mit — zwei Tabs mit derselben ID
 * überschrieben sich beim Hub gegenseitig. Darum fragt jede Brücke beim Start über einen BroadcastChannel, ob ein
 * anderer Tab diese ID schon führt; der ältere behält sie, der jüngere würfelt eine neue (KANAL_NAME).
 *
 * Abhängigkeiten (fetch, Uhr, Speicher, Seite) sind einsteckbar; was fehlt, kommt aus dem Browser.
 * Die Brücke startet nicht, wenn localStorage `fyos:os:bruecke` = `aus` ist, und nicht in
 * ferngesteuerten Browsern (`navigator.webdriver`, z. B. ein Test-Browser), außer es steht `an` —
 * damit ein Browser-Agent sich nicht als Gerät des Benutzers meldet.
 */
import { API_BASE } from '~/lib/api/transport';
import type { BrueckeWerkzeug } from '~/lib/werkzeuge';
import type { Lage } from './bruecke-lage';
import { zeigtPruefen, type ZeigtDaten } from './agent-zeigt';
import type { AudioMeldung } from './ton-modus';

/** Die Brücke findet keine Anmeldung: die Shell darf einmal „Anmelden“ anbieten (höchstens alle 10 min). */
export const ANMELDE_EREIGNIS = 'fyos:bruecke-anmelden';
/** Die Shell ist (wieder) angemeldet: die Brücke meldet und verbindet sofort. */
export const ANGEMELDET_EREIGNIS = 'fyos:angemeldet';

export const PFAD_STROM = '/hub-api/os/strom';
export const PFAD_MELDEN = '/hub-api/os/melden';
export const PFAD_ANTWORT = '/hub-api/os/antwort';
export const VERSION = 1;

export const SCHALTER = 'fyos:os:bruecke';
export const SCHLUESSEL_GERAET = 'fyos:os:geraet';
export const SCHLUESSEL_SITZUNG = 'fyos:os:sitzung';

export const TAKT_MS = 30_000;
export const BUENDEL_MS = 1_500;
export const STILLE_MS = 40_000;
export const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 15_000] as const;
export const STABIL_MS = 3_000;
export const LANGSAM_MS = 60_000;
/** So alt darf ein `zeigen` beim Start sein: dieselbe Zahl wie die Frist des Hubs (`ZEIGEN_FRIST_S`, hub/mcp_hub/os_bruecke.py). */
export const ALTER_ZEIGEN_S = 8;
export const ALTER_ZEIGT_S = 60;
/** … ein `ausfuehren`: wie `AUSFUEHREN_FRIST_S` des Hubs. */
export const ALTER_AUSFUEHREN_S = 15;
export const AUSFUEHREN_MAX_MS = 12_000;
export const GESEHEN_MAX = 100;
/** Im verdeckten Tab wartet die Wiederverbindung doppelt so lang, höchstens so lange. */
export const VERDECKT_MAX_MS = 30_000;
/** Kanal, über den Tabs derselben Seite klären, wer eine Sitzungs-ID führt. */
export const KANAL_NAME = 'fyos:os:sitzung';
/** So lange wartet der Start auf Einspruch eines älteren Tabs mit derselben ID. */
export const DUPLIKAT_WARTE_MS = 150;
const POST_FRIST_MS = 8_000;
/** Pause vor dem zweiten Versuch einer Antwort, wenn der Hub mit 5xx antwortet. */
const ANTWORT_NOCHMAL_MS = 500;

export type BrueckeStatus = 'verbindet' | 'verbunden' | 'getrennt' | 'sitzung_abgelaufen' | 'aus';
export type Sperrgrund = 'schalter' | 'webdriver' | 'testumgebung' | 'kein-fetch';
export type GeraeteArt = 'computer' | 'telefon' | 'tablet';

// ── Gerät und Sitzung ─────────────────────────────────────────────────────────────────────────

export interface NavigatorKurz {
  userAgent?: string;
  maxTouchPoints?: number;
  webdriver?: boolean;
  sendBeacon?: (url: string, daten?: BodyInit | null) => boolean;
}

/** Wie das Gerät heißt: „MacBook“, „iPhone“ … Überschreibbar mit localStorage `fyos:os:geraet`. */
export function geraetErkennen(nav: NavigatorKurz, ueberschrieben?: string | null): { name: string; art: GeraeteArt } {
  const ua = nav.userAgent ?? '';
  const beruehrung = (nav.maxTouchPoints ?? 0) > 1;
  let erkannt: { name: string; art: GeraeteArt };
  if (/iPhone|iPod/.test(ua)) erkannt = { name: 'iPhone', art: 'telefon' };
  else if (/iPad/.test(ua) || (/Macintosh/.test(ua) && beruehrung)) erkannt = { name: 'iPad', art: 'tablet' }; // iPadOS gibt sich als Mac aus
  else if (/Android/.test(ua)) erkannt = /Mobile/.test(ua) ? { name: 'Android-Handy', art: 'telefon' } : { name: 'Android-Tablet', art: 'tablet' };
  else if (/Windows/.test(ua)) erkannt = { name: 'Windows-PC', art: 'computer' };
  else if (/Macintosh|Mac OS X/.test(ua)) erkannt = { name: 'MacBook', art: 'computer' };
  else if (/Linux|X11/.test(ua) && !/CrOS/.test(ua)) erkannt = { name: 'Linux-PC', art: 'computer' };
  else erkannt = { name: 'Browser', art: 'computer' };
  // eslint-disable-next-line no-control-regex -- Steuerzeichen aus dem Namen
  const eigen = (ueberschrieben ?? '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 40);
  return eigen ? { name: eigen, art: erkannt.art } : erkannt;
}

const SITZUNG_FORM = /^s-[a-z0-9]{10}$/;
const ZEICHEN = 'abcdefghijklmnopqrstuvwxyz0123456789';

function zufallsZeichen(n: number): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  const b = new Uint8Array(n);
  if (c?.getRandomValues) c.getRandomValues(b);
  else for (let i = 0; i < n; i++) b[i] = Math.floor(Math.random() * 256);
  let s = '';
  for (const x of b) s += ZEICHEN[x % ZEICHEN.length];
  return s;
}

/** Eine ID je Tab (sessionStorage): `s-` + 10 Zeichen aus [a-z0-9]. Ohne Speicher: neu je Aufruf. */
export function sitzungsId(speicher: Pick<Storage, 'getItem' | 'setItem'> | null): string {
  try {
    const da = speicher?.getItem(SCHLUESSEL_SITZUNG);
    if (da && SITZUNG_FORM.test(da)) return da;
  } catch {
    /* gesperrt */
  }
  return sitzungsIdNeu(speicher);
}

/** Würfelt eine neue ID und merkt sie im Tab (der Tab hatte die alte nur geerbt, „Tab duplizieren“). */
export function sitzungsIdNeu(speicher: Pick<Storage, 'getItem' | 'setItem'> | null): string {
  const neu = `s-${zufallsZeichen(10)}`;
  try {
    speicher?.setItem(SCHLUESSEL_SITZUNG, neu);
  } catch {
    /* gesperrt: gilt, solange die Brücke läuft */
  }
  return neu;
}

/** Nachricht zwischen Tabs (BroadcastChannel): „führt jemand diese ID?“ — „ja, ich, und ich bin älter“. */
type KanalNachricht = { art: 'frage'; sitzung: string; token: string; seit: number } | { art: 'belegt'; sitzung: string; an: string };

export interface KanalKurz {
  postMessage: (daten: unknown) => void;
  close: () => void;
  onmessage: ((e: { data: unknown }) => void) | null;
}

// ── Server-Sent Events lesen ──────────────────────────────────────────────────────────────────

export interface SseEreignis {
  event: string;
  data: string;
  id: string | null;
  retry: number | null;
}

/**
 * Zerlegt einen Textstrom in Ereignisse (WHATWG „Server-sent events“): Zeilenenden \n, \r\n und \r,
 * mehrzeilige `data`, Kommentare (`:`), `id`, `retry`. Chunks dürfen mitten im Feld enden. Das
 * Dekodieren der Bytes (UTF-8 über Chunkgrenzen) macht der Aufrufer mit `TextDecoder({stream})`.
 */
export class SseParser {
  /** Zuletzt gesehene Ereignis-ID (bleibt stehen, wie `lastEventId` bei EventSource) */
  letzteId: string | null = null;
  /** Zuletzt gesehene `retry`-Zeit in ms */
  retry: number | null = null;
  private rest = '';
  private nachCr = false;
  private daten: string[] = [];
  private event = '';
  private id: string | null = null;

  push(chunk: string): SseEreignis[] {
    let text = this.rest + chunk;
    this.rest = '';
    if (this.nachCr) {
      // Der letzte Chunk endete auf \r: ein \n gleich danach gehört noch zu diesem Zeilenende.
      if (text.startsWith('\n')) text = text.slice(1);
      this.nachCr = false;
    }
    const aus: SseEreignis[] = [];
    let von = 0;
    for (let i = 0; i < text.length; i++) {
      const z = text[i];
      if (z !== '\n' && z !== '\r') continue;
      const zeile = text.slice(von, i);
      if (z === '\r') {
        if (text[i + 1] === '\n') i++;
        else if (i === text.length - 1) this.nachCr = true;
      }
      von = i + 1;
      this.zeile(zeile, aus);
    }
    this.rest = text.slice(von);
    return aus;
  }

  private zeile(zeile: string, aus: SseEreignis[]): void {
    if (zeile === '') {
      if (this.id !== null) this.letzteId = this.id;
      if (this.daten.length) aus.push({ event: this.event || 'message', data: this.daten.join('\n'), id: this.id, retry: this.retry });
      this.daten = [];
      this.event = '';
      this.id = null;
      return;
    }
    if (zeile.startsWith(':')) return; // Kommentar (der Hub schickt `: ping`)
    const i = zeile.indexOf(':');
    const feld = i < 0 ? zeile : zeile.slice(0, i);
    let wert = i < 0 ? '' : zeile.slice(i + 1);
    if (wert.startsWith(' ')) wert = wert.slice(1);
    if (feld === 'event') this.event = wert;
    else if (feld === 'data') this.daten.push(wert);
    else if (feld === 'id') {
      if (!wert.includes('\0')) this.id = wert;
    } else if (feld === 'retry' && /^\d+$/.test(wert)) this.retry = Number(wert);
  }
}

// ── Befehle ───────────────────────────────────────────────────────────────────────────────────

interface BefehlBasis {
  id: string;
  von?: string;
  alter_s?: number;
}
export type BefehlZeigen = BefehlBasis & { art: 'zeigen'; ziel: string; eingabe?: Record<string, unknown> | null };
export type BefehlAusfuehren = BefehlBasis & { art: 'ausfuehren'; werkzeug: string; argumente?: Record<string, unknown> | null };
export type BefehlZeigt = BefehlBasis & { art: 'zeigt'; zeigt: unknown };
export type Befehl = BefehlZeigen | BefehlAusfuehren | BefehlZeigt;

/** Was das OS auf `zeigen` antwortet (die Brücke leitet es als Antwort an den Hub weiter). */
export type ZeigenAntwort = { ok: true; ergebnis: Record<string, unknown> } | { ok: false; fehler: string };

/** MCP-Ergebnis eines Seitenwerkzeugs (lib/werkzeuge.ts). */
export interface ToolErgebnis {
  content?: { type: string; text?: string }[];
  structuredContent?: unknown;
  isError?: boolean;
}

export interface Antwort {
  sitzung: string;
  befehl: string;
  ok: boolean;
  ergebnis?: unknown;
  fehler?: string;
}

// ── Die Brücke ────────────────────────────────────────────────────────────────────────────────

export interface BrueckeUmgebung {
  fetch: typeof fetch;
  jetzt: () => number;
  navigator: NavigatorKurz;
  lokal: Pick<Storage, 'getItem'> | null;
  sitzung: Pick<Storage, 'getItem' | 'setItem'> | null;
  pfad: () => string;
  sichtbar: () => boolean;
  /** Sekunden seit der letzten Eingabe des Benutzers, null = noch keine gesehen */
  aktivitaet: () => number | null;
  fenster: Pick<Window, 'addEventListener' | 'removeEventListener'> | null;
  dokument: Pick<Document, 'addEventListener' | 'removeEventListener'> | null;
  /**
   * Keine Anmeldung für die Brücke: im Browser die Mitteilung „einmal anmelden“ (ANMELDE_EREIGNIS, höchstens
   * alle 10 min). Nicht das rote Banner der Seite: innen laden alle anderen Daten weiter, und Neuladen meldet
   * nicht an.
   */
  sitzungAbgelaufen: () => void;
  /** Zufallszahl [0, 1) für die Streuung der Wartezeiten */
  zufall: () => number;
  /** Kanal zu den anderen Tabs (Duplikat-Erkennung); null = es gibt keinen, dann entfällt die Prüfung */
  kanal: () => KanalKurz | null;
}

function sicher<T>(f: () => T, sonst: T): T {
  try {
    return f();
  } catch {
    return sonst; // z. B. gesperrter Speicher
  }
}

export function echteUmgebung(): BrueckeUmgebung {
  const hat = typeof window !== 'undefined';
  return {
    fetch: (...a) => globalThis.fetch(...a),
    jetzt: () => Date.now(),
    navigator: typeof navigator !== 'undefined' ? (navigator as NavigatorKurz) : {},
    lokal: sicher(() => (typeof localStorage !== 'undefined' ? localStorage : null), null),
    sitzung: sicher(() => (typeof sessionStorage !== 'undefined' ? sessionStorage : null), null),
    pfad: () => (hat ? location.pathname : '/'),
    sichtbar: () => (typeof document === 'undefined' ? true : document.visibilityState === 'visible'),
    aktivitaet: () => null,
    fenster: hat ? window : null,
    dokument: typeof document !== 'undefined' ? document : null,
    sitzungAbgelaufen: () => {
      if (hat) sicher(() => window.dispatchEvent(new CustomEvent(ANMELDE_EREIGNIS)), true);
    },
    zufall: () => Math.random(),
    kanal: () => sicher(() => (typeof BroadcastChannel === 'function' ? (new BroadcastChannel(KANAL_NAME) as unknown as KanalKurz) : null), null),
  };
}

/** Warum die Brücke nicht startet — null, wenn sie darf. */
export function sperrgrund(u: Pick<BrueckeUmgebung, 'lokal' | 'navigator' | 'fetch'>): Sperrgrund | null {
  const schalter = sicher(() => u.lokal?.getItem(SCHALTER) ?? null, null);
  if (schalter === 'aus') return 'schalter';
  if (schalter !== 'an') {
    if (u.navigator.webdriver === true) return 'webdriver';
    if (/jsdom/i.test(u.navigator.userAgent ?? '')) return 'testumgebung';
  }
  if (typeof u.fetch !== 'function') return 'kein-fetch';
  return null;
}

/** Beobachtet Eingaben des Benutzers (Maus, Tastatur, Rad, Berührung); liefert „Sekunden seit der letzten“. */
export function aktivitaetBeobachten(win: Pick<Window, 'addEventListener' | 'removeEventListener'>, jetzt: () => number = Date.now): { vorSekunden: () => number | null; stop: () => void } {
  let zuletzt: number | null = null;
  let bewegt = 0;
  const eingabe = () => {
    zuletzt = jetzt();
  };
  const zeiger = () => {
    const j = jetzt();
    if (j - bewegt > 2_000) {
      bewegt = j;
      zuletzt = j;
    }
  };
  const ereignisse = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;
  for (const e of ereignisse) win.addEventListener(e, eingabe, { passive: true } as AddEventListenerOptions);
  win.addEventListener('pointermove', zeiger, { passive: true } as AddEventListenerOptions);
  return {
    vorSekunden: () => (zuletzt === null ? null : Math.max(0, Math.round((jetzt() - zuletzt) / 1000))),
    stop: () => {
      for (const e of ereignisse) win.removeEventListener(e, eingabe);
      win.removeEventListener('pointermove', zeiger);
    },
  };
}

export interface BrueckeOptionen {
  /** Die Lage des OS jetzt (Fenster, Flächen …) — die Shell baut sie, lib/os/bruecke-lage.ts */
  lage: () => Lage;
  /** Die Werkzeuge der Seite im Meldeformat (lib/werkzeuge.ts: fuerBruecke) */
  werkzeuge: () => BrueckeWerkzeug[];
  /** Fläche öffnen */
  zeigen: (ziel: string, eingabe: Record<string, unknown> | null) => Promise<ZeigenAntwort>;
  /** Seitenwerkzeug ausführen (nur freigegebene) */
  ausfuehren: (werkzeug: string, argumente: Record<string, unknown>) => Promise<ToolErgebnis>;
  /** „Der Agent zeigt dir …“ */
  zeigt: (z: ZeigtDaten) => void;
  /** Ton-Modus dieses Geräts und ob Kopfhörer drin sind (lib/os/ton-modus.ts); fehlt = nicht melden */
  audio?: () => AudioMeldung;
  onStatus?: (s: BrueckeStatus) => void;
  umgebung?: Partial<BrueckeUmgebung>;
}

export interface BrueckeLauf {
  readonly sitzung: string;
  readonly geraet: string;
  readonly art: GeraeteArt;
  /** false, wenn die Brücke nicht darf (Grund: `gesperrt()`) */
  start: () => boolean;
  stop: () => void;
  /** Die Lage hat sich geändert: gebündelt melden (nur, wenn sich wirklich etwas geändert hat) */
  aendern: () => void;
  /** Sofort melden */
  melden: () => Promise<void>;
  status: () => BrueckeStatus;
  gesperrt: () => Sperrgrund | null;
  /** Wie viele Geräte der Hub gerade kennt (aus der letzten Antwort), sonst null */
  sitzungen: () => number | null;
}

type PostErgebnis = { art: 'ok'; daten: unknown } | { art: 'sitzung' } | { art: 'http'; status: number } | { art: 'netz'; grund: string };

export function erzeugeBruecke(opt: BrueckeOptionen): BrueckeLauf {
  const u: BrueckeUmgebung = { ...echteUmgebung(), ...opt.umgebung };
  const eigenerName = sicher(() => (u.lokal as Pick<Storage, 'getItem'> | null)?.getItem(SCHLUESSEL_GERAET) ?? null, null);
  const geraet = geraetErkennen(u.navigator, eigenerName);
  let sitzung = sitzungsId(u.sitzung);
  // Duplikat-Erkennung („Tab duplizieren“ kopiert sessionStorage und damit die ID)
  const token = zufallsZeichen(8);
  let startZeit = 0;
  let kanal: KanalKurz | null = null;
  /** Solange die ID geprüft wird, meldet die Brücke noch nichts (sie könnte die eines anderen Tabs überschreiben). */
  let pruefung = false;
  let belegt = false;
  /** Worauf die Schleife gerade wartet: der Wiederverbindung (`backoff`, ein Sichtbarwerden weckt sie) oder der Anmeldung (`langsam`) */
  let wartetAuf: 'backoff' | 'langsam' | null = null;
  /** `retry` aus dem Strom (ms): so lange will der Hub mindestens warten lassen */
  let retryMs = 0;

  let status: BrueckeStatus = 'aus';
  let laeuft = false;
  let generation = 0;
  let sperre: Sperrgrund | null = null;
  let strom: AbortController | null = null;
  let weck: (() => void) | null = null;
  let takt: ReturnType<typeof setTimeout> | undefined;
  let buendel: ReturnType<typeof setTimeout> | undefined;
  let melden_: Promise<void> | null = null;
  let nochmal = false;
  let erzwungen = false;
  let zuletztGemeldet = 0;
  let letzteLage = '';
  let meldenGesperrtBis = 0;
  /** `pagehide` war: die Seite geht weg. Bis zum `pageshow` aus dem bfcache wird nichts mehr gemeldet. */
  let verlassen = false;
  let sitzungenZahl: number | null = null;
  let letzteId: string | null = null;
  let letztesByte = 0;
  let schlange: Promise<void> = Promise.resolve();
  const gesehen: string[] = [];
  let abmelden: (() => void) | null = null;

  const setStatus = (s: BrueckeStatus) => {
    if (s === status) return;
    status = s;
    sicher(() => opt.onStatus?.(s), undefined);
  };

  // ── POST ────────────────────────────────────────────────────────────────────────────────────
  async function post(pfad: string, body: unknown, keepalive = false): Promise<PostErgebnis> {
    try {
      const res = await u.fetch(`${API_BASE}${pfad}`, {
        method: 'POST',
        credentials: 'include',
        redirect: 'manual',
        keepalive,
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
        signal: sicher(() => AbortSignal.timeout(POST_FRIST_MS), undefined),
      });
      if (res.type === 'opaqueredirect' || res.status === 401) {
        u.sitzungAbgelaufen();
        return { art: 'sitzung' };
      }
      if (!res.ok) return { art: 'http', status: res.status };
      if ((res.headers?.get?.('content-type') ?? '').includes('text/html')) {
        u.sitzungAbgelaufen();
        return { art: 'sitzung' };
      }
      let daten: unknown = null;
      try {
        daten = await res.json();
      } catch {
        /* Antwort ohne Körper ist in Ordnung */
      }
      return { art: 'ok', daten };
    } catch (e) {
      return { art: 'netz', grund: e instanceof Error ? e.message : String(e) };
    }
  }

  // ── Melden ──────────────────────────────────────────────────────────────────────────────────
  function meldungBauen() {
    const lage = opt.lage();
    return {
      sitzung,
      geraet: geraet.name,
      art: geraet.art,
      seite: u.pfad(),
      sichtbar: u.sichtbar(),
      aktiv_vor_s: u.aktivitaet(),
      anruf: lage.anruf,
      agent_vorne: lage.agent_vorne,
      bildschirm: lage.bildschirm,
      bildschirme: lage.bildschirme,
      fenster: lage.fenster,
      flaechen: lage.flaechen,
      werkzeuge: opt.werkzeuge(),
      ...(opt.audio ? { audio: sicher(opt.audio, { modus: null, kopfhoerer: null }) } : {}),
      version: VERSION,
      // Uhr dieses Browsers, in ms: ordnet Meldung und „Ende“ (siehe seiteVerlassen), auch wenn sie überholt ankommen
      gesendet: u.jetzt(),
    };
  }

  function planeTakt() {
    clearTimeout(takt);
    if (!laeuft) return;
    takt = setTimeout(() => void melden(), TAKT_MS);
  }

  async function einmalMelden(nurWennGeaendert: boolean): Promise<void> {
    if (!laeuft || verlassen || pruefung) return;
    if (u.jetzt() < meldenGesperrtBis) return;
    const m = meldungBauen();
    const schluessel = JSON.stringify({ ...m, aktiv_vor_s: 0, gesendet: 0 });
    if (nurWennGeaendert && schluessel === letzteLage) return;
    const r = await post(PFAD_MELDEN, m);
    if (r.art === 'ok') {
      zuletztGemeldet = u.jetzt(); // erst nach Erfolg: sonst hielte ein gescheiterter Versuch das „hallo“ davon ab, neu zu melden
      letzteLage = schluessel;
      const n = (r.daten as { sitzungen?: unknown } | null)?.sitzungen;
      sitzungenZahl = typeof n === 'number' ? n : sitzungenZahl;
    } else if (r.art === 'sitzung') {
      meldenGesperrtBis = u.jetzt() + LANGSAM_MS;
    } else if (r.art === 'http' && (r.status === 404 || r.status === 405 || r.status === 501)) {
      meldenGesperrtBis = u.jetzt() + 5 * LANGSAM_MS; // der Hub kennt den Weg noch nicht
    }
  }

  /** Melden. `nurWennGeaendert`: nichts senden, wenn die Lage so schon beim Hub liegt (außer jemand wollte es erzwingen). */
  function melden(nurWennGeaendert = false): Promise<void> {
    if (!nurWennGeaendert) erzwungen = true;
    clearTimeout(takt);
    if (melden_) {
      nochmal = true; // läuft gerade eine Meldung: danach gleich noch eine mit dem neuesten Stand
      return melden_;
    }
    melden_ = (async () => {
      try {
        do {
          nochmal = false;
          const erzwingen = erzwungen;
          erzwungen = false;
          await einmalMelden(!erzwingen);
        } while (nochmal && laeuft);
      } finally {
        melden_ = null;
        planeTakt();
      }
    })();
    return melden_;
  }

  function aendern() {
    if (!laeuft || buendel !== undefined) return;
    buendel = setTimeout(() => {
      buendel = undefined;
      void melden(true);
    }, BUENDEL_MS);
  }

  // ── Antworten ───────────────────────────────────────────────────────────────────────────────
  async function antworten(a: Omit<Antwort, 'sitzung'>): Promise<void> {
    const body: Antwort = { sitzung, ...a };
    if (typeof body.fehler === 'string') body.fehler = body.fehler.slice(0, 2_000);
    let r = await post(PFAD_ANTWORT, body);
    // Einmal nachlegen (der Hub wartet höchstens 15 s): bei einem Netzfehler gleich, bei einem 5xx des Hubs (Pod
    // wechselt, Redis hakt) nach einer kurzen Pause. Eine 4xx ist endgültig; eine 401 hat `post` schon als abgelaufene
    // Sitzung gemeldet (Anmelden anbieten) — dann hilft kein zweiter Versuch.
    if (r.art === 'netz') r = await post(PFAD_ANTWORT, body);
    else if (r.art === 'http' && r.status >= 500) {
      await new Promise<void>((fertig) => setTimeout(fertig, ANTWORT_NOCHMAL_MS));
      r = await post(PFAD_ANTWORT, body);
    }
    if (r.art !== 'ok') {
      const grund = r.art === 'sitzung' ? 'Anmeldung abgelaufen' : r.art === 'http' ? `HTTP ${r.status}` : r.grund;
      sicher(() => console.warn(`[os-bruecke] Antwort auf ${a.befehl} nicht angekommen: ${grund}`), undefined);
    }
  }

  const textVon = (r: ToolErgebnis): string => (r.content ?? []).map((c) => c.text ?? '').filter(Boolean).join('\n');

  async function mitFrist<T>(p: Promise<T>, ms: number, was: string): Promise<T | { zeitueberschreitung: string }> {
    let t: ReturnType<typeof setTimeout> | undefined;
    const frist = new Promise<{ zeitueberschreitung: string }>((r) => {
      t = setTimeout(() => r({ zeitueberschreitung: `Zeitüberschreitung: ${was} hat nach ${Math.round(ms / 1000)} s nicht geantwortet.` }), ms);
    });
    try {
      return await Promise.race([p, frist]);
    } finally {
      clearTimeout(t);
    }
  }

  async function ausfuehren(b: BefehlAusfuehren) {
    if (typeof b.werkzeug !== 'string' || !b.werkzeug) {
      await antworten({ befehl: b.id, ok: false, fehler: 'werkzeug fehlt' });
      return;
    }
    const r = await mitFrist(opt.ausfuehren(b.werkzeug, b.argumente && typeof b.argumente === 'object' ? b.argumente : {}), AUSFUEHREN_MAX_MS, `Werkzeug ${b.werkzeug}`);
    if ('zeitueberschreitung' in r) {
      await antworten({ befehl: b.id, ok: false, fehler: r.zeitueberschreitung });
      return;
    }
    if (r.isError) await antworten({ befehl: b.id, ok: false, ergebnis: r, fehler: textVon(r) || `${b.werkzeug} ist fehlgeschlagen` });
    else await antworten({ befehl: b.id, ok: true, ergebnis: r });
  }

  async function zeigen(b: BefehlZeigen) {
    if (typeof b.ziel !== 'string' || !b.ziel) {
      await antworten({ befehl: b.id, ok: false, fehler: 'ziel fehlt' });
      return;
    }
    const eingabe = b.eingabe && typeof b.eingabe === 'object' && !Array.isArray(b.eingabe) ? b.eingabe : null;
    const r = await mitFrist(opt.zeigen(b.ziel, eingabe), AUSFUEHREN_MAX_MS, `Öffnen von ${b.ziel}`);
    if ('zeitueberschreitung' in r) await antworten({ befehl: b.id, ok: false, fehler: r.zeitueberschreitung });
    else if (r.ok) await antworten({ befehl: b.id, ok: true, ergebnis: r.ergebnis });
    else await antworten({ befehl: b.id, ok: false, fehler: r.fehler });
  }

  /** Ein Befehl aus dem Strom. Wirft nie. */
  function befehl(daten: string) {
    let b: Befehl;
    try {
      b = JSON.parse(daten) as Befehl;
    } catch {
      return;
    }
    if (!b || typeof b !== 'object' || typeof b.id !== 'string' || !b.id) return;
    const id = b.id;
    if (gesehen.includes(id)) return;
    gesehen.push(id);
    if (gesehen.length > GESEHEN_MAX) gesehen.shift();
    const alter = typeof b.alter_s === 'number' && Number.isFinite(b.alter_s) ? b.alter_s : 0;
    const empfangen = u.jetzt();
    /** Alter jetzt: das des Hubs beim Ausliefern plus die Zeit seit dem Empfang (Schlange, träger Tab) */
    const alterJetzt = () => alter + Math.max(0, u.jetzt() - empfangen) / 1000;

    if (b.art === 'zeigt') {
      if (alter > ALTER_ZEIGT_S) return;
      const z = zeigtPruefen(b.zeigt);
      if (z) sicher(() => opt.zeigt(z), undefined);
      return;
    }
    if (b.art !== 'zeigen' && b.art !== 'ausfuehren') {
      void antworten({ befehl: id, ok: false, fehler: `Unbekannte Befehlsart: ${String((b as { art?: unknown }).art)}` });
      return;
    }
    const grenze = b.art === 'zeigen' ? ALTER_ZEIGEN_S : ALTER_AUSFUEHREN_S;
    if (alter > grenze) return; // niemand wartet mehr
    const lauf = async () => {
      // Befehle laufen nacheinander: was in der Schlange hinter einem langsamen stand, ist inzwischen vielleicht zu alt
      // — der Hub hat dann längst aufgegeben und das Fenster ginge als Geist auf.
      if (alterJetzt() > grenze) return;
      try {
        if (b.art === 'zeigen') await zeigen(b);
        else await ausfuehren(b);
      } catch (e) {
        await antworten({ befehl: b.id, ok: false, fehler: e instanceof Error ? e.message : String(e) });
      }
    };
    schlange = schlange.then(lauf, lauf);
  }

  // ── Strom ───────────────────────────────────────────────────────────────────────────────────
  type Ende = 'ende' | 'sitzung' | 'nicht_da';

  /** JSON aus `data:` eines Ereignisses; null, wenn es keins ist */
  const jsonAus = (text: string): unknown => {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  };

  async function einmalVerbinden(ctl: AbortController): Promise<{ ende: Ende; hallo: boolean; abbruch?: boolean }> {
    const q = new URLSearchParams({ sitzung, geraet: geraet.name });
    if (letzteId) q.set('nach', letzteId);
    const kopf: Record<string, string> = { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' };
    if (letzteId) kopf['Last-Event-ID'] = letzteId;
    const res = await u.fetch(`${API_BASE}${PFAD_STROM}?${q}`, { method: 'GET', headers: kopf, credentials: 'include', redirect: 'manual', cache: 'no-store', signal: ctl.signal });
    if (res.type === 'opaqueredirect' || res.status === 401) {
      u.sitzungAbgelaufen();
      return { ende: 'sitzung', hallo: false };
    }
    if (res.status === 404 || res.status === 405 || res.status === 501) return { ende: 'nicht_da', hallo: false };
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const typ = res.headers?.get?.('content-type') ?? '';
    if (typ.includes('text/html')) {
      u.sitzungAbgelaufen(); // die Anmeldeseite mit Status 200
      return { ende: 'sitzung', hallo: false };
    }
    if (typ && !typ.includes('text/event-stream')) throw new Error(`kein Ereignisstrom (${typ})`);
    setStatus('verbunden');
    letztesByte = u.jetzt();

    const leser = res.body.getReader();
    const dekoder = new TextDecoder('utf-8');
    const parser = new SseParser();
    parser.letzteId = letzteId;
    const abbruch = new Promise<never>((_, nein) => {
      const los = () => nein(new DOMException('abgebrochen', 'AbortError'));
      if (ctl.signal.aborted) los();
      else ctl.signal.addEventListener('abort', los, { once: true });
    });
    abbruch.catch(() => {});
    let stille: ReturnType<typeof setTimeout> | undefined;
    const scharf = () => {
      clearTimeout(stille);
      stille = setTimeout(() => ctl.abort(), STILLE_MS);
    };
    let hallo = false;
    let abgebrochen = false;
    scharf();
    try {
      for (;;) {
        const { done, value } = await Promise.race([leser.read(), abbruch]);
        if (done) return { ende: 'ende', hallo, abbruch: abgebrochen };
        letztesByte = u.jetzt();
        scharf();
        for (const ev of parser.push(dekoder.decode(value, { stream: true }))) {
          if (ev.id) letzteId = ev.id;
          // `retry:` des Hubs gilt für die nächste Wiederverbindung (wie bei EventSource), in vernünftigen Grenzen
          if (parser.retry !== null) retryMs = Math.min(Math.max(parser.retry, 0), VERDECKT_MAX_MS);
          if (ev.event === 'hallo') {
            hallo = true;
            meldenGesperrtBis = 0; // der Hub kennt die Wege
            // Der Hub kennt die Sitzung nicht (mehr) — Neustart des Pods, Ablauf nach 90 s: sofort melden (Vertrag 3).
            // Sonst nur, wenn die letzte Meldung länger her ist; läuft gerade eine, trägt sie den Stand.
            const bekannt = (jsonAus(ev.data) as { bekannt?: unknown } | null)?.bekannt;
            if (bekannt === false) void melden();
            else if (!melden_ && u.jetzt() - zuletztGemeldet > 2_000) void melden();
          } else if (ev.event === 'befehl') befehl(ev.data);
          else if (ev.event === 'abbruch') {
            // Der Hub gibt den Strom auf (Redis weg): kein Grund, gleich wieder hineinzulaufen
            abgebrochen = true;
            sicher(() => console.warn(`[os-bruecke] Hub beendet den Strom: ${String((jsonAus(ev.data) as { grund?: unknown } | null)?.grund ?? 'ohne Grund')}`), undefined);
          }
        }
      }
    } finally {
      clearTimeout(stille);
      sicher(() => void leser.cancel().catch(() => {}), undefined);
    }
  }

  function warte(ms: number): Promise<void> {
    return new Promise((fertig) => {
      const t = setTimeout(() => {
        weck = null;
        fertig();
      }, ms);
      weck = () => {
        clearTimeout(t);
        weck = null;
        fertig();
      };
    });
  }

  async function schleife(gen: number) {
    let versuch = 0;
    while (gen === generation) {
      setStatus('verbindet');
      const ctl = new AbortController();
      strom = ctl;
      const t0 = u.jetzt();
      let ende: Ende | 'fehler' = 'fehler';
      let hallo = false;
      let abbruch = false;
      try {
        const r = await einmalVerbinden(ctl);
        ende = r.ende;
        hallo = r.hallo;
        abbruch = !!r.abbruch;
      } catch {
        ende = 'fehler';
      } finally {
        if (strom === ctl) strom = null;
      }
      if (gen !== generation) return;
      if (ende === 'sitzung') {
        setStatus('sitzung_abgelaufen');
        wartetAuf = 'langsam';
        await warte(LANGSAM_MS);
        wartetAuf = null;
        continue;
      }
      setStatus('getrennt');
      if (ende === 'nicht_da') {
        wartetAuf = 'langsam';
        await warte(LANGSAM_MS);
        wartetAuf = null;
        continue;
      }
      // Ein Strom, den der Hub selbst aufgegeben hat (`event: abbruch`), war keine stabile Verbindung
      if (hallo && !abbruch && u.jetzt() - t0 >= STABIL_MS) versuch = 0;
      wartetAuf = 'backoff';
      await warte(wiederverbindenNach(versuch));
      wartetAuf = null;
      versuch += 1;
    }
  }

  /**
   * Wartezeit vor der nächsten Verbindung: die Stufe der Leiter (1, 2, 4, 8, 15 s), gestreut auf die obere Hälfte, im
   * verdeckten Tab doppelt so lang (höchstens VERDECKT_MAX_MS), nie kürzer als das `retry` des Hubs.
   */
  function wiederverbindenNach(versuch: number): number {
    let ms = backoffNach(versuch);
    if (!sicher(u.sichtbar, true)) ms = Math.min(ms * 2, VERDECKT_MAX_MS);
    ms = Math.round(ms * (0.5 + 0.5 * Math.min(Math.max(u.zufall(), 0), 1)));
    return Math.max(ms, retryMs);
  }

  // ── Start und Ende ──────────────────────────────────────────────────────────────────────────
  function sichtbarkeit() {
    // Aus dem Schlaf zurück: Strom, der lange nichts gebracht hat, ist vermutlich tot.
    if (u.sichtbar() && strom && u.jetzt() - letztesByte > STILLE_MS + 5_000) strom.abort();
    // Wieder sichtbar und gerade in der (im verdeckten Tab verlängerten) Pause: gleich verbinden
    if (u.sichtbar() && wartetAuf === 'backoff') weck?.();
    void melden();
  }
  const seiteVerlassen = () => {
    // Im echten Chrome folgt auf `pagehide` noch `visibilitychange` (hidden), und das löst eine Meldung aus: sie
    // käme NACH dem Ende beim Hub an und öffnete den geschlossenen Tab für 90 s wieder. Also danach still sein.
    verlassen = true;
    // `gesendet`: beim Schließen eines Tabs überholt das „Ende“ außerdem eine Meldung, die schon unterwegs ist.
    // Der Hub merkt sich die Zeit des Endes und lässt ältere Meldungen dieser Sitzung nicht wieder aufleben.
    const body = JSON.stringify({ sitzung, ende: true, gesendet: u.jetzt() });
    const url = `${API_BASE}${PFAD_MELDEN}`;
    const ok = sicher(() => (u.navigator.sendBeacon ? u.navigator.sendBeacon(url, new Blob([body], { type: 'application/json' })) : false), false);
    if (!ok) {
      sicher(
        () =>
          void u
            .fetch(url, { method: 'POST', keepalive: true, credentials: 'include', headers: { 'Content-Type': 'application/json' }, body })
            .catch(() => {}),
        undefined,
      );
    }
  };
  const zurueck = (e: Event) => {
    if (!(e as PageTransitionEvent).persisted) return;
    verlassen = false; // aus dem bfcache zurück: der Hub hat die Sitzung vergessen, also neu melden
    void melden();
  };
  const wiederOnline = () => weck?.();
  // Nach der Anmeldung (ANGEMELDET_EREIGNIS) nicht bis zu 60 s warten: gleich melden und verbinden.
  const angemeldet = () => {
    meldenGesperrtBis = 0;
    weck?.();
    void melden();
  };

  function start(): boolean {
    if (laeuft) return true;
    sperre = sperrgrund(u);
    if (sperre) {
      setStatus('aus');
      return false;
    }
    laeuft = true;
    verlassen = false;
    generation += 1;
    const gen = generation;
    u.dokument?.addEventListener('visibilitychange', sichtbarkeit);
    u.fenster?.addEventListener('pagehide', seiteVerlassen);
    u.fenster?.addEventListener('pageshow', zurueck);
    u.fenster?.addEventListener('online', wiederOnline);
    u.fenster?.addEventListener(ANGEMELDET_EREIGNIS, angemeldet);
    abmelden = () => {
      u.dokument?.removeEventListener('visibilitychange', sichtbarkeit);
      u.fenster?.removeEventListener('pagehide', seiteVerlassen);
      u.fenster?.removeEventListener('pageshow', zurueck);
      u.fenster?.removeEventListener('online', wiederOnline);
      u.fenster?.removeEventListener(ANGEMELDET_EREIGNIS, angemeldet);
    };
    startZeit = u.jetzt();
    kanalOeffnen();
    if (!kanal) {
      void melden();
      void schleife(gen);
      return true;
    }
    // Erst klären, ob ein älterer Tab diese ID führt (Tab duplizieren); so lange wird nichts gemeldet.
    pruefung = true;
    belegt = false;
    sicher(() => kanal?.postMessage({ art: 'frage', sitzung, token, seit: startZeit } as KanalNachricht), undefined);
    setTimeout(() => {
      if (gen !== generation) return;
      pruefung = false;
      if (belegt) {
        belegt = false;
        sitzung = sitzungsIdNeu(u.sitzung);
      }
      void melden();
      void schleife(gen);
    }, DUPLIKAT_WARTE_MS);
    return true;
  }

  /** Hört auf die anderen Tabs: wer älter ist als der Fragende, behält die ID und sagt es. */
  function kanalOeffnen() {
    kanal = sicher(() => u.kanal(), null);
    if (!kanal) return;
    const k = kanal;
    k.onmessage = (e) => {
      const d = e.data as Partial<KanalNachricht> | null;
      if (!d || typeof d !== 'object' || d.sitzung !== sitzung) return;
      if (d.art === 'belegt' && d.an === token) {
        belegt = true;
      } else if (d.art === 'frage' && d.token !== token && typeof d.seit === 'number' && typeof d.token === 'string') {
        // Gleich alt (selber Tick): der kleinere Token behält die ID — beide fragen, genau einer gewinnt
        const aelter = startZeit < d.seit || (startZeit === d.seit && token < d.token);
        const an = d.token;
        if (aelter) sicher(() => k.postMessage({ art: 'belegt', sitzung, an } as KanalNachricht), undefined);
      }
    };
  }

  function stop() {
    if (!laeuft) {
      setStatus('aus');
      return;
    }
    laeuft = false;
    pruefung = false;
    sicher(() => kanal?.close(), undefined);
    kanal = null;
    generation += 1;
    clearTimeout(takt);
    clearTimeout(buendel);
    buendel = undefined;
    strom?.abort();
    strom = null;
    weck?.();
    abmelden?.();
    abmelden = null;
    letzteLage = '';
    seiteVerlassen();
    setStatus('aus');
  }

  return {
    get sitzung() {
      return sitzung;
    },
    geraet: geraet.name,
    art: geraet.art,
    start,
    stop,
    aendern,
    melden: () => melden(),
    status: () => status,
    gesperrt: () => sperre,
    sitzungen: () => sitzungenZahl,
  };
}

/** Wartezeit vor dem Wiederverbinden nach dem n-ten Fehlschlag (n ab 0): 1, 2, 4, 8, dann immer 15 s. */
export const backoffNach = (versuch: number): number => BACKOFF_MS[Math.min(Math.max(0, versuch), BACKOFF_MS.length - 1)]!;
