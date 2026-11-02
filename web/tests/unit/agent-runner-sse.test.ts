import { describe, expect, it, vi } from 'vitest';
import { SseParser, haltStrom, liesSse, type SseNachricht, type StromStatus } from '~/lib/agent-runner/sse';

const strom = (...stuecke: string[]): Response => {
  const kodierer = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(c) {
        for (const s of stuecke) c.enqueue(kodierer.encode(s));
        c.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
};

describe('SseParser', () => {
  it('liest event und data, ignoriert Kommentare', () => {
    const p = new SseParser();
    const n = p.push(': fyos-agent\n\nevent: snapshot\ndata: {"a":1}\n\n');
    expect(n).toEqual([{ event: 'snapshot', data: '{"a":1}' }]);
  });

  it('setzt halbe Zeilen und Nachrichten über Stücke hinweg zusammen', () => {
    const p = new SseParser();
    expect(p.push('event: zei')).toEqual([]);
    expect(p.push('le\ndata: {"t":')).toEqual([]);
    expect(p.push('1}\n')).toEqual([]);
    expect(p.push('\n')).toEqual([{ event: 'zeile', data: '{"t":1}' }]);
  });

  it('versteht CRLF auch wenn \\r und \\n in getrennten Stücken kommen', () => {
    const p = new SseParser();
    expect(p.push('event: a\r')).toEqual([]);
    expect(p.push('\ndata: x\r\n\r')).toEqual([]);
    expect(p.push('\n')).toEqual([{ event: 'a', data: 'x' }]);
  });

  it('verbindet mehrere data-Zeilen mit Zeilenumbruch und nimmt „message“ ohne event', () => {
    const p = new SseParser();
    expect(p.push('data: a\ndata: b\n\n')).toEqual([{ event: 'message', data: 'a\nb' }]);
  });

  it('zwei Nachrichten in einem Stück', () => {
    const p = new SseParser();
    const n = p.push('event: a\ndata: 1\n\nevent: b\ndata: 2\n\n');
    expect(n.map((x) => x.event)).toEqual(['a', 'b']);
  });
});

describe('liesSse', () => {
  it('liest eine Antwort bis zum Ende', async () => {
    const aus: SseNachricht[] = [];
    await liesSse(strom('event: hallo\ndata: {}\n\n', 'event: zeile\ndata: {"t":1}\n\n'), (n) => aus.push(n));
    expect(aus.map((n) => n.event)).toEqual(['hallo', 'zeile']);
  });
});

describe('haltStrom', () => {
  it('verbindet nach einem Ende neu und meldet den Status', async () => {
    const status: StromStatus[] = [];
    const aus: string[] = [];
    let n = 0;
    const warte = vi.fn(async () => {});
    const h = haltStrom({
      oeffnen: async () => {
        n++;
        if (n > 2) await new Promise(() => {}); // dritter Versuch hängt offen
        return strom(`event: snapshot\ndata: ${n}\n\n`);
      },
      beiNachricht: (m) => aus.push(`${m.event}:${m.data}`),
      beiStatus: (s) => status.push(s),
      warte,
    });
    await vi.waitFor(() => expect(aus).toEqual(['snapshot:1', 'snapshot:2']));
    expect(status).toContain('offen');
    expect(status).toContain('getrennt');
    expect(warte).toHaveBeenCalled();
    h.schliessen();
  });

  it('wartet länger bei wiederholten Fehlern und setzt nach Erfolg zurück', async () => {
    const pausen: number[] = [];
    let n = 0;
    const h = haltStrom({
      oeffnen: async () => {
        n++;
        if (n <= 3) throw new Error('weg');
        await new Promise(() => {});
        return strom();
      },
      beiNachricht: () => {},
      warte: async (ms) => void pausen.push(ms),
      minMs: 100,
      maxMs: 350,
    });
    await vi.waitFor(() => expect(n).toBeGreaterThanOrEqual(4));
    expect(pausen.slice(0, 3)).toEqual([100, 200, 350]);
    h.schliessen();
  });

  it('gibt bei einem endgültigen Fehler auf (Anmeldung fehlt) und meldet ihn', async () => {
    const fehler: Array<[unknown, boolean]> = [];
    const status: StromStatus[] = [];
    let n = 0;
    haltStrom({
      oeffnen: async () => {
        n++;
        throw Object.assign(new Error('anmelden'), { wiederholbar: false });
      },
      beiNachricht: () => {},
      beiStatus: (s) => status.push(s),
      beiFehler: (f, e) => fehler.push([f, e]),
      warte: async () => {},
    });
    await vi.waitFor(() => expect(status).toContain('beendet'));
    expect(n).toBe(1);
    expect(fehler[0]?.[1]).toBe(true);
  });

  it('schliessen beendet die Schleife', async () => {
    let n = 0;
    const h = haltStrom({
      oeffnen: async () => {
        n++;
        return strom('event: a\ndata: 1\n\n');
      },
      beiNachricht: () => {},
      warte: (_ms, signal) => new Promise((ok) => signal.addEventListener('abort', () => ok(), { once: true })),
    });
    await vi.waitFor(() => expect(n).toBe(1));
    h.schliessen();
    await new Promise((r) => setTimeout(r, 20));
    expect(n).toBe(1);
  });
});
