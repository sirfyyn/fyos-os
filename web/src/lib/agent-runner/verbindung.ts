/**
 * verbindung.ts — die Anbindung der Web-App an den Agenten-Runner.
 *
 * Alles läuft über dieselbe Herkunft: `/api/agent/…` (nginx der Shell, web/nginx/default.conf.template; im Dev der Proxy
 * aus astro.config.mjs). Dort stehen der Pflicht-Kopf `X-FYOS-Agent: 1` und das Runner-Token — der Browser kennt das
 * Token nie. Es gilt `redirect: 'manual'`: verlangt ein Proxy davor eine Anmeldung, antwortet er mit einer Umleitung
 * (`opaqueredirect`); die Fläche bietet dann „Anmelden“ an (neu laden).
 */
import { fehlerText } from './text';
import { tr } from '~/lib/i18n';

export const AGENT_BASIS = '/api/agent';
export const AGENT_KOPF = 'X-FYOS-Agent';

export type FehlerArt =
  | 'anmeldung' // ein Proxy davor will eine Anmeldung (Umleitung oder 403)
  | 'token' // der Runner lehnt das Token ab (401): Secret fehlt oder ist falsch
  | 'nicht-freigegeben' // die Shell leitet nicht weiter (404 ohne Runner-Antwort)
  | 'nicht-erreichbar' // 502/503/504: der Runner läuft nicht oder ist unterwegs
  | 'netz' // der Browser kam nicht durch
  | 'server' // 5xx des Runners
  | 'anfrage'; // 4xx des Runners (falsche Eingabe, unbekanntes Gespräch)

const TITEL: Record<FehlerArt, string> = {
  anmeldung: 'Anmeldung nötig',
  token: 'Der Runner nimmt das Token nicht an',
  'nicht-freigegeben': 'Der Zugang ist nicht freigegeben',
  'nicht-erreichbar': 'Der Runner ist nicht erreichbar',
  netz: 'Keine Verbindung',
  server: 'Der Runner meldet einen Fehler',
  anfrage: 'Der Runner lehnt die Anfrage ab',
};

export class RunnerFehler extends Error {
  readonly art: FehlerArt;
  readonly status: number;
  /** Lohnt sich ein neuer Versuch von selbst (Strom verbindet dann wieder)? */
  readonly wiederholbar: boolean;
  constructor(art: FehlerArt, status: number, nachricht?: string) {
    super(nachricht || tr(TITEL[art]));
    this.name = 'RunnerFehler';
    this.art = art;
    this.status = status;
    this.wiederholbar = art === 'nicht-erreichbar' || art === 'netz' || art === 'server';
  }
  get titel(): string {
    return tr(TITEL[this.art]);
  }
}

export interface VerbindungOptionen {
  basis?: string;
  fetch?: typeof fetch;
  /** Zeitgrenze für gewöhnliche Anfragen (Ströme haben keine). */
  timeoutMs?: number;
}

export interface AnfrageOptionen {
  methode?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  koerper?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function klassifiziere(res: Response, daten: { fehler?: unknown } | null, text: string): RunnerFehler {
  const meldung = typeof daten?.fehler === 'string' ? daten.fehler : undefined;
  if (res.type === 'opaqueredirect' || res.status === 0) return new RunnerFehler('anmeldung', 0);
  if (res.status === 401) return new RunnerFehler('token', 401, meldung);
  if (res.status === 403) return new RunnerFehler('anmeldung', 403, meldung);
  if (res.status === 404 && !daten) return new RunnerFehler('nicht-freigegeben', 404, text.trim().slice(0, 200) || undefined);
  if (res.status === 502 || res.status === 503 || res.status === 504) return new RunnerFehler('nicht-erreichbar', res.status, meldung);
  if (res.status >= 500) return new RunnerFehler('server', res.status, meldung);
  return new RunnerFehler('anfrage', res.status, meldung ?? `HTTP ${res.status}`);
}

export class AgentVerbindung {
  readonly basis: string;
  private readonly hol: typeof fetch;
  private readonly timeoutMs: number;

  constructor(opt: VerbindungOptionen = {}) {
    this.basis = (opt.basis ?? AGENT_BASIS).replace(/\/+$/, '');
    this.hol = opt.fetch ?? ((...a) => globalThis.fetch(...a));
    this.timeoutMs = opt.timeoutMs ?? 45_000;
  }

  url(pfad: string): string {
    return `${this.basis}/${String(pfad).replace(/^\/+/, '')}`;
  }

  private kopfzeilen(mitKoerper: boolean, strom: boolean): Record<string, string> {
    const k: Record<string, string> = { [AGENT_KOPF]: '1', Accept: strom ? 'text/event-stream' : 'application/json' };
    if (mitKoerper) k['Content-Type'] = 'application/json';
    return k;
  }

  private async rohAnfrage(pfad: string, opt: AnfrageOptionen, strom: boolean): Promise<Response> {
    try {
      return await this.hol(this.url(pfad), {
        method: opt.methode ?? 'GET',
        headers: this.kopfzeilen(opt.koerper !== undefined, strom),
        body: opt.koerper === undefined ? undefined : JSON.stringify(opt.koerper),
        redirect: 'manual',
        credentials: 'include',
        cache: 'no-store',
        signal: opt.signal,
      });
    } catch (f) {
      if ((f as { name?: string } | null)?.name === 'AbortError') throw f;
      throw new RunnerFehler('netz', 0, fehlerText(f));
    }
  }

  /** JSON-Anfrage; löst mit dem Körper auf, wirft `RunnerFehler`. */
  async anfrage<T = Record<string, unknown>>(pfad: string, opt: AnfrageOptionen = {}): Promise<T> {
    const steuerung = new AbortController();
    const grenze = opt.timeoutMs ?? this.timeoutMs;
    const timer = setTimeout(() => steuerung.abort(), grenze);
    const aussen = opt.signal;
    const weiter = () => steuerung.abort();
    aussen?.addEventListener('abort', weiter, { once: true });
    try {
      const res = await this.rohAnfrage(pfad, { ...opt, signal: steuerung.signal }, false).catch((f) => {
        if ((f as { name?: string } | null)?.name === 'AbortError') {
          if (aussen?.aborted) throw f;
          throw new RunnerFehler('nicht-erreichbar', 0, tr('Der Runner antwortet nicht rechtzeitig.'));
        }
        throw f;
      });
      const text = res.type === 'opaqueredirect' ? '' : await res.text();
      let daten: Record<string, unknown> | null = null;
      try {
        daten = text ? (JSON.parse(text) as Record<string, unknown>) : {};
      } catch {
        daten = null;
      }
      if (!res.ok || (daten && daten.ok === false)) throw klassifiziere(res, daten, text);
      if (daten === null) throw new RunnerFehler('server', res.status, tr('Die Antwort des Runners ist kein JSON.'));
      return daten as T;
    } finally {
      clearTimeout(timer);
      aussen?.removeEventListener('abort', weiter);
    }
  }

  /** Öffnet einen SSE-Strom; wirft `RunnerFehler`, wenn der Zugang nicht klappt. */
  async oeffneStrom(pfad: string, signal?: AbortSignal): Promise<Response> {
    const res = await this.rohAnfrage(pfad, { signal }, true);
    if (res.type === 'opaqueredirect' || !res.ok) {
      const text = res.type === 'opaqueredirect' ? '' : await res.text().catch(() => '');
      let daten: { fehler?: unknown } | null = null;
      try {
        daten = text ? (JSON.parse(text) as { fehler?: unknown }) : null;
      } catch {
        daten = null;
      }
      throw klassifiziere(res, daten, text);
    }
    return res;
  }
}
