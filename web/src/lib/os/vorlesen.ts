/**
 * vorlesen.ts — der Agent liest eine Mitteilung vor (mit Kopfhörern „interaktiv“ oder „zurückhaltend“, lib/os/ton-modus.ts).
 * Ob vorgelesen wird, entscheidet der Hub (`audio.sprechen`, nur mit Kopfhörern); hier nur das Wie: eine Stimme,
 * die ein Plugin einrichtet (`stimmeSetzen`), liefert einen WAV-Strom (44-Byte-Kopf, danach PCM16 mono); die
 * Wiedergabe läuft über Web Audio.
 *
 * Ohne eingerichtete Stimme liefert `vorlesen` false — der Aufrufer spielt dann den Hinweiston, damit die Mitteilung
 * nicht stumm untergeht. Immer nur eine Mitteilung zugleich; eine neue bricht die laufende ab. Nach 45 s ist Schluss.
 */

export const VORLESEN_MAX_MS = 45_000;
const TEXT_MAX = 400;

/** Denk-Blöcke und Werkzeugmarken aus einem Antworttext entfernen (auch halb offene am Ende). */
function bereinigen(roh: string): string {
  let t = roh.replace(/<think>[\s\S]*?<\/think>/gi, '');
  const offen = t.search(/<think>/i);
  if (offen >= 0) t = t.slice(0, offen);
  return t.replace(/\[Tool:\s*[^\]]*\]\s*/g, '');
}

/** Was vorgelesen wird: Titel, dann der Text — ohne Markdown, gekürzt. */
export function vorlesetext(titel: string, vorschau: string | null): string {
  const t = bereinigen([titel, vorschau].filter(Boolean).join('. ')).trim();
  return t.length <= TEXT_MAX ? t : t.slice(0, TEXT_MAX - 1).trimEnd() + '…';
}

/** Eine Stimme: Text hinein, WAV-Strom heraus. */
export type Stimme = (text: string, signal: AbortSignal) => Promise<ReadableStream<Uint8Array>>;

export interface VorlesenAbh {
  sprechen: Stimme;
  kontext: () => AudioContext;
}

let stimme: Stimme | null = null;

/** Ein Plugin richtet die Stimme ein (oder nimmt sie mit `null` wieder weg). */
export function stimmeSetzen(f: Stimme | null): void {
  stimme = f;
}

const echt: VorlesenAbh = {
  sprechen: async (text, signal) => {
    if (!stimme) throw new Error('Noch nicht eingerichtet.');
    return stimme(text, signal);
  },
  kontext: () => new AudioContext(),
};

// ── WAV-Strom → PCM-Blöcke ────────────────────────────────────────────────────────────────────────

interface PcmBlock {
  rate: number;
  pcm: Int16Array;
}

/** Liest den Strom: 44-Byte-Kopf (Länge unbekannt), danach PCM16 mono. Halbe Samples warten auf den nächsten Block. */
async function* pcmBloecke(body: ReadableStream<Uint8Array>): AsyncGenerator<PcmBlock> {
  const leser = body.getReader();
  let kopf = new Uint8Array(0);
  let rate = 0;
  let rest: Uint8Array = new Uint8Array(0);
  try {
    for (;;) {
      const { done, value } = await leser.read();
      if (done) return;
      let teil: Uint8Array = value;
      if (!rate) {
        const z = new Uint8Array(kopf.length + teil.length);
        z.set(kopf);
        z.set(teil, kopf.length);
        if (z.length < 44) {
          kopf = z;
          continue;
        }
        rate = new DataView(z.buffer, z.byteOffset).getUint32(24, true);
        if (!rate || rate < 8000 || rate > 96000) throw new Error('Stimme: unbrauchbarer WAV-Kopf');
        teil = z.subarray(44);
      }
      if (rest.length) {
        const z = new Uint8Array(rest.length + teil.length);
        z.set(rest);
        z.set(teil, rest.length);
        teil = z;
        rest = new Uint8Array(0);
      }
      const gerade = teil.length - (teil.length % 2);
      if (gerade < teil.length) rest = teil.slice(gerade);
      if (gerade === 0) continue;
      // kopieren: Ausrichtung auf 2 Byte nicht garantiert
      const kopie = teil.slice(0, gerade);
      yield { rate, pcm: new Int16Array(kopie.buffer, 0, gerade / 2) };
    }
  } finally {
    leser.releaseLock();
  }
}

// ── Wiedergabe per Web Audio ──────────────────────────────────────────────────────────────────────

/** PCM-Blöcke werden lückenlos hintereinander eingeplant; `stoppen()` beendet alles sofort. */
class Spieler {
  onLeer: (() => void) | null = null;
  private naechste = 0;
  private quellen = new Set<AudioBufferSourceNode>();
  /** kleine Vorlaufzeit gegen Knacken beim ersten Block */
  private static readonly VORLAUF_S = 0.04;

  constructor(private readonly ctx: AudioContext) {}

  einreihen(pcm: Int16Array, rate: number): void {
    if (!pcm.length) return;
    const f = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) f[i] = pcm[i]! / 32768;
    const buf = this.ctx.createBuffer(1, f.length, rate);
    buf.copyToChannel(f, 0);
    const q = this.ctx.createBufferSource();
    q.buffer = buf;
    q.connect(this.ctx.destination);
    const start = Math.max(this.ctx.currentTime + Spieler.VORLAUF_S, this.naechste);
    q.start(start);
    this.naechste = start + buf.duration;
    this.quellen.add(q);
    q.onended = () => {
      this.quellen.delete(q);
      if (!this.quellen.size) this.onLeer?.();
    };
  }

  stoppen(): void {
    const alle = [...this.quellen];
    this.quellen.clear();
    this.naechste = 0;
    for (const q of alle) {
      q.onended = null;
      try {
        q.stop();
      } catch {
        /* lief nie an */
      }
      try {
        q.disconnect();
      } catch {
        /* schon getrennt */
      }
    }
  }

  aktiv(): boolean {
    return this.quellen.size > 0;
  }
}

let laufend: AbortController | null = null;

export async function vorlesen(text: string, abh: VorlesenAbh = echt): Promise<boolean> {
  if (!text) return false;
  laufend?.abort();
  const ab = new AbortController();
  laufend = ab;
  const frist = setTimeout(() => ab.abort(), VORLESEN_MAX_MS);
  let ctx: AudioContext | null = null;
  let spieler: Spieler | null = null;
  try {
    ctx = abh.kontext();
    if (ctx.state === 'suspended') await ctx.resume().catch(() => undefined);
    spieler = new Spieler(ctx);
    const strom = await abh.sprechen(text, ab.signal);
    let bloecke = 0;
    for await (const b of pcmBloecke(strom)) {
      if (ab.signal.aborted) break;
      spieler.einreihen(b.pcm, b.rate);
      bloecke++;
    }
    if (ab.signal.aborted || !bloecke) {
      spieler.stoppen();
      return false;
    }
    // zu Ende spielen lassen, dann aufräumen
    const s = spieler;
    await new Promise<void>((fertig) => {
      if (!s.aktiv()) return fertig();
      s.onLeer = () => fertig();
      ab.signal.addEventListener('abort', () => {
        s.stoppen();
        fertig();
      });
    });
    return !ab.signal.aborted;
  } catch {
    spieler?.stoppen();
    return false;
  } finally {
    clearTimeout(frist);
    if (laufend === ab) laufend = null;
    void ctx?.close().catch(() => undefined);
  }
}

/** Laufendes Vorlesen abbrechen (z. B. wenn ein Anruf beginnt). */
export function vorlesenStoppen(): void {
  laufend?.abort();
}
