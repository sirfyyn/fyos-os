/**
 * transport.ts — die eine Strecke, über die die Oberfläche JSON holt.
 *
 * `hole()` (Fehler als Rückgabewert) und `fetchJson()` (Fehler als Wurf) bauten
 * `API_BASE`, `fetch` und das Lesen des Fehlerkörpers bisher doppelt. Beide
 * sitzen jetzt hier drauf. Was die Strecke zusätzlich kann:
 *
 * - **Sitzung abgelaufen erkennen.** Ein vorgeschalteter Anmelde-Proxy antwortet dann oft nicht mit 401,
 *   sondern mit 302 zur Anmeldeseite — auch für API-Aufrufe. `fetch`
 *   folgt, scheitert an CORS und meldet „Failed to fetch": die Oberfläche sagte
 *   „Backend tot", Agenten lasen leere Listen als Wahrheit. Mit `redirect: 'manual'` wird
 *   daraus eine erkennbare `opaqueredirect`-Antwort.
 * - **Zeitgrenze.** Ohne sie hängt eine Pane bei einem stummen Backend unbegrenzt.
 * - **HTML statt JSON erkennen** (Login-Seite mit 200) statt `SyntaxError`.
 *
 * Bei erkannter Sitzung wird `meldeSitzungAbgelaufen()` ausgelöst — das Banner
 * (SitzungsBanner.tsx) und das Werkzeug-Register hören darauf.
 */

export const API_BASE = import.meta.env.PUBLIC_API_BASE || '';

/** Vorgabe für die Zeitgrenze. Lange Vorgänge (Upload, Export) geben eigene `zeitMs` an. */
export const ZEIT_MS = 20_000;

export type Strecke =
  | { art: 'ok'; res: Response; daten: unknown }
  | { art: 'http'; res: Response; status: number; grund: string; koerper?: unknown }
  | { art: 'sitzung'; grund: string }
  | { art: 'zeit'; grund: string }
  | { art: 'abgebrochen'; grund: string }
  | { art: 'netz'; grund: string }
  | { art: 'kein_json'; res: Response; grund: string };

export const SITZUNG_EREIGNIS = 'fyos:sitzung-abgelaufen';
let gemeldet = false;

/** Einmal je Seitenleben melden — das Banner soll nicht bei jedem Aufruf neu aufpoppen. */
export function meldeSitzungAbgelaufen(): void {
  if (gemeldet || typeof window === 'undefined') return;
  gemeldet = true;
  window.dispatchEvent(new CustomEvent(SITZUNG_EREIGNIS));
}

export function sitzungAbgelaufen(): boolean {
  return gemeldet;
}

/** Nur für Tests. */
export function _sitzungZuruecksetzen(): void {
  gemeldet = false;
}

function signalMit(zeitMs: number, eigenes?: AbortSignal | null): { signal: AbortSignal; zeit: AbortSignal } {
  const zeit = AbortSignal.timeout(zeitMs);
  if (!eigenes) return { signal: zeit, zeit };
  // AbortSignal.any gibt es seit Chrome 116 / Safari 17.4 / Firefox 124.
  const any = (AbortSignal as unknown as { any?: (s: AbortSignal[]) => AbortSignal }).any;
  return { signal: any ? any([eigenes, zeit]) : eigenes, zeit };
}

function textVon(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Eine Anfrage, klassifiziert. Wirft nie — jeder Ausgang ist ein Wert.
 * `init.zeitMs` überschreibt die Zeitgrenze; `0` schaltet sie ab (Streams).
 */
export async function strecke(pfad: string, init: RequestInit & { zeitMs?: number } = {}): Promise<Strecke> {
  const { zeitMs = ZEIT_MS, ...rest } = init;
  const url = pfad.startsWith('http') ? pfad : `${API_BASE}${pfad}`;
  const s = zeitMs > 0 ? signalMit(zeitMs, rest.signal) : null;
  let res: Response;
  try {
    res = await fetch(url, {
      credentials: 'include',
      redirect: 'manual',
      ...rest,
      signal: s ? s.signal : rest.signal,
      headers: { Accept: 'application/json', ...(rest.headers ?? {}) },
    });
  } catch (e) {
    if (s?.zeit.aborted) return { art: 'zeit', grund: `keine Antwort nach ${Math.round(zeitMs / 1000)} s` };
    if (rest.signal?.aborted || (e instanceof DOMException && e.name === 'AbortError')) {
      return { art: 'abgebrochen', grund: 'abgebrochen' };
    }
    return { art: 'netz', grund: textVon(e) };
  }

  // 302 zu Authentik → opaqueredirect (Status 0). Eine 401 zählt genauso.
  if (res.type === 'opaqueredirect' || res.status === 401) {
    meldeSitzungAbgelaufen();
    return { art: 'sitzung', grund: 'Sitzung abgelaufen — neu anmelden' };
  }

  if (!res.ok) {
    let koerper: unknown;
    let grund = `HTTP ${res.status}`;
    try {
      koerper = await res.clone().json();
      const p = koerper as { detail?: unknown; title?: unknown };
      const d = typeof p?.detail === 'string' ? p.detail : typeof p?.title === 'string' ? p.title : '';
      if (d) grund = d;
    } catch {
      grund = `HTTP ${res.status} (kein Fehlertext im Körper)`;
    }
    return { art: 'http', res, status: res.status, grund, koerper };
  }

  if (res.status === 204) return { art: 'ok', res, daten: null };

  const typ = res.headers?.get?.('content-type') ?? '';
  if (typ.includes('text/html')) {
    // Eine HTML-Seite, wo JSON erwartet war, ist fast immer die Anmeldeseite.
    meldeSitzungAbgelaufen();
    return { art: 'sitzung', grund: 'Sitzung abgelaufen — neu anmelden (HTML statt Daten)' };
  }
  try {
    return { art: 'ok', res, daten: await res.json() };
  } catch (e) {
    return { art: 'kein_json', res, grund: `Antwort war kein JSON (${textVon(e)})` };
  }
}
