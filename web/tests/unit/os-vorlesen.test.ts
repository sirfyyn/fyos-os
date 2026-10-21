/**
 * Vorlesen einer Mitteilung (lib/os/vorlesen.ts): die Stimme richtet ein Plugin ein, ohne sie liefert `vorlesen` false.
 */
import { describe, expect, it, vi } from 'vitest';
import { stimmeSetzen, vorlesen, vorlesetext, type VorlesenAbh } from '~/lib/os/vorlesen';

/** WAV-Strom: 44-Byte-Kopf mit Rate, danach PCM16. */
function wavStrom(samples: number, rate = 24000): ReadableStream<Uint8Array> {
  const kopf = new Uint8Array(44);
  new DataView(kopf.buffer).setUint32(24, rate, true);
  const pcm = new Uint8Array(samples * 2);
  return new ReadableStream({
    start(c) {
      c.enqueue(kopf);
      c.enqueue(pcm);
      c.close();
    },
  });
}

/** Ein AudioContext, dessen Quellen sofort „zu Ende gespielt“ sind. */
function fakeKontext() {
  const quellen: { onended: (() => void) | null }[] = [];
  const ctx = {
    state: 'running',
    currentTime: 0,
    destination: {},
    resume: vi.fn(async () => undefined),
    close: vi.fn(async () => undefined),
    createBuffer: (_k: number, laenge: number, rate: number) => ({ duration: laenge / rate, copyToChannel: () => undefined }),
    createBufferSource: () => {
      const q = {
        buffer: null as unknown,
        onended: null as (() => void) | null,
        connect: () => undefined,
        disconnect: () => undefined,
        start: () => queueMicrotask(() => q.onended?.()),
        stop: () => undefined,
      };
      quellen.push(q);
      return q;
    },
  };
  return { ctx: ctx as unknown as AudioContext, quellen };
}

describe('vorlesen', () => {
  it('Text: Titel und Vorschau, ohne Denkblöcke, gekürzt', () => {
    expect(vorlesetext('Neue Nachricht', 'Frist Freitag.')).toBe('Neue Nachricht. Frist Freitag.');
    expect(vorlesetext('Paket', null)).toBe('Paket');
    expect(vorlesetext('Paket', '<think>nein</think>Unterwegs.')).toBe('Paket. Unterwegs.');
    expect(vorlesetext('x', 'y'.repeat(600)).length).toBeLessThanOrEqual(400);
  });

  it('spricht über die Stimme und spielt zu Ende', async () => {
    const { ctx, quellen } = fakeKontext();
    const sprechen = vi.fn(async () => wavStrom(2400));
    const abh: VorlesenAbh = { sprechen, kontext: () => ctx };
    await expect(vorlesen('Hallo', abh)).resolves.toBe(true);
    expect(sprechen).toHaveBeenCalledWith('Hallo', expect.any(AbortSignal));
    expect(quellen.length).toBeGreaterThan(0);
    expect(ctx.close).toHaveBeenCalled();
  });

  it('Stimme weg oder leerer Strom: false (der Aufrufer spielt dann den Hinweiston)', async () => {
    const { ctx } = fakeKontext();
    await expect(vorlesen('x', { sprechen: async () => { throw new Error('Stimme weg'); }, kontext: () => ctx })).resolves.toBe(false);
    await expect(vorlesen('x', { sprechen: async () => wavStrom(0), kontext: () => ctx })).resolves.toBe(false);
    await expect(vorlesen('', { sprechen: async () => wavStrom(10), kontext: () => ctx })).resolves.toBe(false);
  });

  it('eine neue Mitteilung bricht die laufende ab', async () => {
    const { ctx } = fakeKontext();
    let freigeben: (s: ReadableStream<Uint8Array>) => void = () => undefined;
    const erste = vorlesen('eins', { sprechen: () => new Promise((r) => (freigeben = r)), kontext: () => ctx });
    const zweite = vorlesen('zwei', { sprechen: async () => wavStrom(100), kontext: () => ctx });
    freigeben(wavStrom(100));
    await expect(erste).resolves.toBe(false);
    await expect(zweite).resolves.toBe(true);
  });

  it('ohne eingerichtete Stimme: false; ein Plugin kann sie einrichten', async () => {
    const { ctx } = fakeKontext();
    vi.stubGlobal('AudioContext', function () { return ctx; });
    try {
      stimmeSetzen(null);
      await expect(vorlesen('x')).resolves.toBe(false);
      stimmeSetzen(async () => wavStrom(100));
      await expect(vorlesen('x')).resolves.toBe(true);
    } finally {
      stimmeSetzen(null);
      vi.unstubAllGlobals();
    }
  });
});
