import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  agentName, agentPfad, externeFlaechen, konfigurationLadenZuruecksetzen, konfigurationLaden, konfigurationSetzen, konfigurationZuruecksetzen, systemName,
} from '~/lib/config';
import { alleFlaechen } from '~/lib/os/flaechen';
import { farbton, glyphe } from '~/lib/os/symbole';
import {
  gruppeFuerApp, registerZuruecksetzen, registriereFlaechen, registrierteAlias, registrierteDinge, registrierteFlaechen, registrierteSymbole,
} from '~/lib/os/register';

afterEach(() => {
  registerZuruecksetzen();
  konfigurationZuruecksetzen();
  konfigurationLadenZuruecksetzen();
});

const flaeche = (id: string, titel: string, extra: Record<string, unknown> = {}) =>
  ({ id, titel, gruppe: 'Arbeit', art: 'seite' as const, kuerzel: 'Xx', pfad: '/x/', ...extra });

describe('registriereFlaechen', () => {
  it('nimmt Flächen, Symbole, Aliasse, Gruppen und Dinge auf', () => {
    registriereFlaechen({
      flaechen: [flaeche('seite:notizen', 'Notizen')],
      symbole: { 'seite:notizen': ['file-text', 200] },
      alias: { 'seite:memo': 'seite:notizen' },
      gruppen: { plugin: { notizen: 'Arbeit' } },
      dinge: { notiz: { name: 'Notiz', pfad: '/notizen/' } },
    });
    expect(registrierteFlaechen().map((f) => f.id)).toEqual(['seite:notizen']);
    expect(registrierteSymbole('seite:notizen')).toEqual(['file-text', 200]);
    expect(registrierteAlias('seite:memo')).toBe('seite:notizen');
    expect(gruppeFuerApp('notizen__liste')).toBe('Arbeit');
    expect(gruppeFuerApp('anderes__liste')).toBe('Apps');
    expect(registrierteDinge('notiz')).toEqual({ name: 'Notiz', pfad: '/notizen/' });
  });

  it('wiederholt: dieselbe Kennung ersetzt, nichts doppelt', () => {
    registriereFlaechen({ flaechen: [flaeche('seite:a', 'Alt')] });
    registriereFlaechen({ flaechen: [flaeche('seite:a', 'Neu')] });
    expect(registrierteFlaechen().map((f) => f.titel)).toEqual(['Neu']);
  });

  it('eine Quelle ersetzt ihre früheren Flächen, andere bleiben', () => {
    registriereFlaechen({ flaechen: [flaeche('seite:fest', 'Fest')] });
    registriereFlaechen({ flaechen: [flaeche('extern:a', 'A')], quelle: 'konfiguration' });
    registriereFlaechen({ flaechen: [flaeche('extern:b', 'B')], quelle: 'konfiguration' });
    expect(registrierteFlaechen().map((f) => f.id)).toEqual(['seite:fest', 'extern:b']);
  });

  it('übergeht Unbrauchbares und gefährliche Schlüssel', () => {
    registriereFlaechen({
      flaechen: [{ id: '', titel: 'x', gruppe: 'g' } as never, null as never, flaeche('seite:ok', 'Ok')],
      symbole: { __proto__: ['x', 1], 'seite:ok': ['book', 'rot'] } as never,
      alias: JSON.parse('{"__proto__": "x", "constructor": "y"}'),
    });
    expect(registrierteFlaechen().map((f) => f.id)).toEqual(['seite:ok']);
    expect(registrierteSymbole('seite:ok')).toBeUndefined();
    expect(registrierteAlias('__proto__')).toBeUndefined();
  });

  it('die Fläche erscheint im Verzeichnis, das Symbol in der Symboltabelle', () => {
    registriereFlaechen({ flaechen: [flaeche('seite:notizen', 'Notizen')], symbole: { 'seite:notizen': ['file-text', 200] } });
    expect(alleFlaechen([]).map((f) => f.id)).toContain('seite:notizen');
    expect(glyphe('seite:notizen')).toBe('file-text');
    expect(farbton('seite:notizen')).toBe(200);
  });
});

describe('Laufzeit-Konfiguration', () => {
  it('Vorgaben ohne Datei', () => {
    expect(systemName()).toBe('FYOS');
    expect(agentName()).toBe('Agent');
    expect(agentPfad()).toBe('/agent/');
  });

  it('Name, Agent und externe Dienste aus der Datei', () => {
    konfigurationSetzen({
      name: 'Mein System',
      agent: { name: 'Ada', pfad: '/chat/' },
      extern: [{ slug: 'gitea', titel: 'Gitea', url: 'https://git.example.org/' }],
    });
    expect(systemName()).toBe('Mein System');
    expect(agentName()).toBe('Ada');
    expect(agentPfad()).toBe('/chat/');
    const e = alleFlaechen([]).find((f) => f.id === 'extern:gitea');
    expect(e).toMatchObject({ titel: 'Gitea', gruppe: 'Extern', extern: 'https://git.example.org/' });
    expect(e?.pfad).toBeUndefined();
  });

  it('ein Agentpfad muss mit / beginnen', () => {
    konfigurationSetzen({ agent: { pfad: 'https://fremd.example/' } });
    expect(agentPfad()).toBe('/agent/');
  });

  it('externe Dienste: nur http(s) und saubere Kennungen', () => {
    const l = externeFlaechen([
      { slug: 'ok', titel: 'Ok', url: 'https://a.example/' },
      { slug: 'js', titel: 'Böse', url: 'javascript:alert(1)' },
      { slug: '../x', titel: 'Pfad', url: 'https://b.example/' },
      { slug: 'leer', titel: 'Leer' } as never,
    ]);
    expect(l.map((f) => f.id)).toEqual(['extern:ok']);
  });

  it('neu laden ersetzt die externen Dienste', () => {
    konfigurationSetzen({ extern: [{ slug: 'a', titel: 'A', url: 'https://a.example/' }] });
    konfigurationSetzen({ extern: [{ slug: 'b', titel: 'B', url: 'https://b.example/' }] });
    expect(registrierteFlaechen().map((f) => f.id)).toEqual(['extern:b']);
  });

  it('lädt /fyos.config.json einmal; Fehler und HTML ergeben die Vorgaben', async () => {
    const holen = vi.fn(async () => new Response(JSON.stringify({ name: 'Aus Datei' }), { headers: { 'content-type': 'application/json' } }));
    await konfigurationLaden(holen as never);
    await konfigurationLaden(holen as never);
    expect(holen).toHaveBeenCalledTimes(1);
    expect(systemName()).toBe('Aus Datei');

    konfigurationZuruecksetzen();
    konfigurationLadenZuruecksetzen();
    const html = vi.fn(async () => new Response('<html></html>', { headers: { 'content-type': 'text/html' } }));
    expect(await konfigurationLaden(html as never)).toEqual({});
    expect(systemName()).toBe('FYOS');

    konfigurationLadenZuruecksetzen();
    const kaputt = vi.fn(async () => {
      throw new Error('netz');
    });
    expect(await konfigurationLaden(kaputt as never)).toEqual({});
  });
});
