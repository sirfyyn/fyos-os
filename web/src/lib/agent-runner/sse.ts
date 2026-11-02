/**
 * sse.ts — Server-Sent Events per fetch gelesen.
 *
 * `EventSource` kann keinen eigenen Kopf setzen; der Zugang über die Shell (nginx) verlangt aber `X-FYOS-Agent: 1` (eine fremde Seite
 * darf ihn nicht senden). Darum liest dieser Leser den Strom selbst: Parser für das Textformat, Leseschleife und
 * Wiederverbinden mit wachsender Wartezeit. Nach jedem Verbinden schickt der Runner zuerst wieder einen `snapshot`.
 */

export interface SseNachricht {
  event: string;
  data: string;
  id?: string;
}

/** Zerlegt einen Textstrom in Nachrichten. Kommentarzeilen (`: wach`) und halbe Zeilen am Rand werden richtig behandelt. */
export class SseParser {
  private puffer = '';
  private event = '';
  private daten: string[] = [];
  private id: string | undefined;

  push(stueck: string): SseNachricht[] {
    this.puffer += stueck;
    const aus: SseNachricht[] = [];
    for (;;) {
      const m = /\r\n|\n|\r/.exec(this.puffer);
      if (!m) break;
      // Ein einzelnes \r am Ende des Puffers kann der Anfang eines \r\n sein: auf das nächste Stück warten.
      if (m[0] === '\r' && m.index + 1 === this.puffer.length) break;
      const zeile = this.puffer.slice(0, m.index);
      this.puffer = this.puffer.slice(m.index + m[0].length);
      if (zeile === '') {
        if (this.daten.length || this.event) {
          aus.push({ event: this.event || 'message', data: this.daten.join('\n'), ...(this.id !== undefined ? { id: this.id } : {}) });
        }
        this.event = '';
        this.daten = [];
        continue;
      }
      if (zeile.startsWith(':')) continue;
      const i = zeile.indexOf(':');
      const feld = i < 0 ? zeile : zeile.slice(0, i);
      let wert = i < 0 ? '' : zeile.slice(i + 1);
      if (wert.startsWith(' ')) wert = wert.slice(1);
      if (feld === 'event') this.event = wert;
      else if (feld === 'data') this.daten.push(wert);
      else if (feld === 'id') this.id = wert;
    }
    return aus;
  }
}

/** Liest eine SSE-Antwort bis zum Ende oder bis `signal` abbricht. */
export async function liesSse(antwort: Response, beiNachricht: (n: SseNachricht) => void, signal?: AbortSignal): Promise<void> {
  const leser = antwort.body?.getReader();
  if (!leser) throw new Error('Die Antwort hat keinen lesbaren Strom.');
  const dekoder = new TextDecoder('utf-8');
  const parser = new SseParser();
  const abbrechen = () => void leser.cancel().catch(() => {});
  signal?.addEventListener('abort', abbrechen, { once: true });
  try {
    for (;;) {
      const { done, value } = await leser.read();
      if (done) break;
      for (const n of parser.push(dekoder.decode(value, { stream: true }))) beiNachricht(n);
    }
  } finally {
    signal?.removeEventListener('abort', abbrechen);
  }
}

export type StromStatus = 'verbinde' | 'offen' | 'getrennt' | 'beendet';

export interface HaltStromOptionen {
  oeffnen: (signal: AbortSignal) => Promise<Response>;
  beiNachricht: (n: SseNachricht) => void;
  beiStatus?: (s: StromStatus) => void;
  /** `endgueltig`: es wird nicht wieder verbunden (z. B. Anmeldung fehlt). */
  beiFehler?: (fehler: unknown, endgueltig: boolean) => void;
  /** Wartet `ms`; ersetzbar in Tests. */
  warte?: (ms: number, signal: AbortSignal) => Promise<void>;
  minMs?: number;
  maxMs?: number;
}

const warteStandard = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise((ok) => {
    const t = setTimeout(ok, ms);
    signal.addEventListener('abort', () => { clearTimeout(t); ok(); }, { once: true });
  });

/** Hält einen Strom offen und verbindet nach einem Abbruch neu. `schliessen()` beendet ihn endgültig. */
export function haltStrom(opt: HaltStromOptionen): { schliessen: () => void } {
  const steuerung = new AbortController();
  const warte = opt.warte ?? warteStandard;
  const minMs = opt.minMs ?? 1000;
  const maxMs = opt.maxMs ?? 15_000;
  void (async () => {
    let pause = minMs;
    while (!steuerung.signal.aborted) {
      try {
        opt.beiStatus?.('verbinde');
        const antwort = await opt.oeffnen(steuerung.signal);
        if (steuerung.signal.aborted) break;
        opt.beiStatus?.('offen');
        pause = minMs;
        await liesSse(antwort, opt.beiNachricht, steuerung.signal);
        if (steuerung.signal.aborted) break;
        opt.beiStatus?.('getrennt');
      } catch (fehler) {
        if (steuerung.signal.aborted) break;
        const wiederholbar = (fehler as { wiederholbar?: boolean } | null)?.wiederholbar !== false;
        opt.beiFehler?.(fehler, !wiederholbar);
        if (!wiederholbar) break;
        opt.beiStatus?.('getrennt');
      }
      await warte(pause, steuerung.signal);
      pause = Math.min(maxMs, pause * 2);
    }
    opt.beiStatus?.('beendet');
  })();
  return { schliessen: () => steuerung.abort() };
}
