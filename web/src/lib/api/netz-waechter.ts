/**
 * netz-waechter.ts — erkennt eine abgelaufene Sitzung auch bei den ~280 rohen `fetch`-Aufrufen.
 *
 * Die eigenen Abrufschichten (hole/fetchJson) erkennen die Sitzung selbst (transport.ts).
 * Die übrigen Aufrufe sehen bei abgelaufener Sitzung nur „Failed to fetch": Ein Anmelde-Proxy leitet
 * zur Anmeldeseite um, der Browser scheitert an CORS. Statt 280 Stellen anzufassen,
 * beobachtet dieser Wächter `fetch` — **ohne dessen Verhalten zu ändern**: Ergebnis und
 * Fehler gehen unverändert an den Aufrufer zurück. Nur wenn ein Aufruf an die eigene
 * Herkunft mit einem Netzfehler endet, prüft er (höchstens alle 15 s) mit einer kleinen
 * Probe, ob die Sitzung abgelaufen ist, und löst dann das Banner aus.
 *
 * Offline/Online wird als eigenes Ereignis gemeldet.
 */
import { meldeSitzungAbgelaufen, sitzungAbgelaufen } from './transport';

export const OFFLINE_EREIGNIS = 'fyos:netz';
const PROBE = '/healthz';
const PROBE_ABSTAND_MS = 15_000;

let letzteProbe = 0;
let installiert = false;

function eigeneHerkunft(input: RequestInfo | URL): boolean {
  try {
    const u = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    return u.origin === location.origin;
  } catch {
    return false;
  }
}

/** Ist die Sitzung abgelaufen? Eine Umleitung auf die Probe heisst: Caddy will anmelden. */
export async function sitzungPruefen(f: typeof fetch = fetch): Promise<boolean> {
  try {
    const r = await f(`${PROBE}?t=${Date.now()}`, {
      credentials: 'include',
      redirect: 'manual',
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    return r.type === 'opaqueredirect' || r.status === 401;
  } catch {
    return false; // Netz weg — das ist „offline", nicht „abgemeldet".
  }
}

export function netzWaechterInstallieren(): void {
  if (installiert || typeof window === 'undefined') return;
  installiert = true;
  const original = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    try {
      return await original(input, init);
    } catch (e) {
      const abbruch = e instanceof DOMException && e.name === 'AbortError';
      if (!abbruch && navigator.onLine && !sitzungAbgelaufen() && eigeneHerkunft(input)) {
        const jetzt = Date.now();
        if (jetzt - letzteProbe > PROBE_ABSTAND_MS) {
          letzteProbe = jetzt;
          void sitzungPruefen(original).then((ab) => ab && meldeSitzungAbgelaufen());
        }
      }
      throw e;
    }
  };

  const melde = () => window.dispatchEvent(new CustomEvent(OFFLINE_EREIGNIS, { detail: { online: navigator.onLine } }));
  window.addEventListener('online', melde);
  window.addEventListener('offline', melde);
}
