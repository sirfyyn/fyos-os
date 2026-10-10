/**
 * Der Abruf mit drei Ausgängen darf sie nicht vermischen.
 *
 * Hintergrund: 114 Stellen im Frontend verwandeln einen fehlgeschlagenen `fetch`
 * in ein leeres Ergebnis. Der teuerste Fall sind die 48, die brav ein HTTP 500 melden und
 * beim **Totalausfall** schweigen — ein Backend, das gar nicht antwortet, erzeugt keinen
 * Statuscode, sondern einen Wurf. So bleibt ein Totalausfall unbemerkt.
 *
 * Diese Datei hält fest, dass `hole()` genau diesen Fall nicht verliert.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { hole, hinweisText } from '~/lib/api/abruf';

function antwortet(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    clone() {
      return this;
    },
  } as unknown as Response);
}

afterEach(() => vi.unstubAllGlobals());

describe('hole()', () => {
  it('liefert Daten als `daten`', async () => {
    vi.stubGlobal('fetch', antwortet([{ a: 1 }]));
    const a = await hole<{ a: number }[]>('/x');
    expect(a.zustand).toBe('daten');
    if (a.zustand === 'daten') expect(a.daten).toHaveLength(1);
  });

  it('unterscheidet eine leere Liste von einem Fehlschlag', async () => {
    vi.stubGlobal('fetch', antwortet([]));
    expect((await hole('/x')).zustand).toBe('leer');
  });

  it('ein HTTP-Fehler ist NICHT leer', async () => {
    vi.stubGlobal('fetch', antwortet({ detail: 'kaputt' }, 500));
    const a = await hole('/x');
    expect(a.zustand).toBe('nicht_erreichbar');
    if (a.zustand === 'nicht_erreichbar') {
      expect(a.status).toBe(500);
      expect(a.grund).toBe('kaputt');
    }
  });

  it('ein Verbindungsabbruch OHNE Statuscode ist der wichtigste Fall', async () => {
    // Genau dieser Wurf entsteht, wenn das Backend gar nicht antwortet. Die 48
    // Halb-Behandlungen im Bestand verschlucken ihn, weil sie nur `!r.ok` prüfen.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('Failed to fetch')),
    );
    const a = await hole('/x');
    expect(a.zustand).toBe('nicht_erreichbar');
    if (a.zustand === 'nicht_erreichbar') {
      expect(a.grund).toContain('Failed to fetch');
      expect(a.status).toBeUndefined(); // kein Statuscode — genau das ist der Punkt
    }
  });

  it('200 mit kaputtem Körper ist ein Defekt, kein leeres Ergebnis', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError('Unexpected token <');
        },
        clone() {
          return this;
        },
      } as unknown as Response),
    );
    const a = await hole('/x');
    expect(a.zustand).toBe('nicht_erreichbar');
  });
});

describe('hinweisText()', () => {
  it('sagt bei leer und bei nicht erreichbar VERSCHIEDENES', async () => {
    vi.stubGlobal('fetch', antwortet([]));
    const leer = hinweisText(await hole('/x'), 'Keine Server eingerichtet.');

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const weg = hinweisText(await hole('/x'), 'Keine Server eingerichtet.');

    expect(leer).toBe('Keine Server eingerichtet.');
    expect(weg).toContain('Nicht erreichbar');
    expect(leer).not.toBe(weg); // der einzige Unterschied, der zählt
  });

  it('gibt bei Daten null zurück', async () => {
    vi.stubGlobal('fetch', antwortet([1]));
    expect(hinweisText(await hole('/x'))).toBeNull();
  });
});
