import { describe, expect, it } from 'vitest';
import { griffQuellenLaden, griffeBauen, griffeFinden, schoen, type GriffQuellen } from '~/lib/griffe';

const QUELLEN: GriffQuellen = {
  griffe: [
    { id: 'lesezeichen:an', titel: 'Lesezeichen Bericht an', werkzeug: 'lesezeichen.schalten', argumente: { name: 'bericht', an: true }, gruppe: 'Notizen', symbol: 'star', woerter: ['merken'], gegen: { id: 'lesezeichen:aus', titel: 'Lesezeichen Bericht aus', werkzeug: 'lesezeichen.schalten', argumente: { name: 'bericht', an: false } } },
    { id: 'lesezeichen:aus', titel: 'Lesezeichen Bericht aus', werkzeug: 'lesezeichen.schalten', argumente: { name: 'bericht', an: false }, gruppe: 'Notizen', istSchon: true },
    { id: 'zusammenfassung', titel: 'Zusammenfassung anlegen', werkzeug: 'berichte.anlegen', argumente: { art: 'woche' }, erfolg: 'Zusammenfassung angelegt', woerter: ['bericht', 'woche'] },
    { id: 'anker', titel: 'Anker Vorlage', werkzeug: 'vorlagen.oeffnen', argumente: {} },
    { id: 'wechsel', titel: 'Modell wechseln', werkzeug: 'modelle.umschalten', argumente: { ziel: 'klein', ausfuehren: true }, nachfragen: true },
    // ungültig: ohne Werkzeug, mit fremden Zeichen im Werkzeug, doppelte Kennung
    { id: 'kaputt', titel: 'Kaputt', werkzeug: '' },
    { id: 'frech', titel: 'Frech', werkzeug: 'a b; rm' },
    { id: 'anker', titel: 'Anker doppelt', werkzeug: 'vorlagen.oeffnen' },
  ],
};
const alle = griffeBauen(QUELLEN);
const titel = (q: string) => griffeFinden(alle, q).map((g) => g.titel);

describe('Griffe bauen', () => {
  it('nimmt gültige Angebote der Plugins auf und füllt Vorgaben auf', () => {
    expect(alle.map((g) => g.id)).toEqual(['lesezeichen:an', 'lesezeichen:aus', 'zusammenfassung', 'anker', 'wechsel']);
    const z = alle.find((g) => g.id === 'zusammenfassung')!;
    expect(z).toMatchObject({ gruppe: 'Schalten', erfolg: 'Zusammenfassung angelegt', argumente: { art: 'woche' } });
    expect(z.symbol.length).toBeGreaterThan(0);
    expect(alle.find((g) => g.id === 'anker')!.erfolg).toBe('Anker Vorlage');
  });

  it('übergeht Ungültiges und Doppeltes (Werkzeug fehlt oder trägt fremde Zeichen, gleiche Kennung)', () => {
    const t = alle.map((g) => g.titel);
    expect(t).not.toContain('Kaputt');
    expect(t).not.toContain('Frech');
    expect(t).not.toContain('Anker doppelt');
  });

  it('der Wechsel fragt nach, der Rückweg ist ein eigener Griff', () => {
    expect(alle.find((g) => g.id === 'wechsel')!.nachfragen).toBe(true);
    expect(alle.find((g) => g.id === 'lesezeichen:an')!.gegen).toMatchObject({ titel: 'Lesezeichen Bericht aus', argumente: { an: false } });
    expect(alle.find((g) => g.id === 'zusammenfassung')!.gegen).toBeUndefined();
  });

  it('„ordner_neu“ wird „Ordner neu“, „buero“ wird „Büro“', () => {
    expect(schoen('ordner_neu')).toBe('Ordner neu');
    expect(schoen('buero')).toBe('Büro');
  });

  it('ohne Angebote gibt es keine Griffe', () => {
    expect(griffeBauen({})).toEqual([]);
    expect(griffeBauen({ griffe: [] })).toEqual([]);
  });
});

describe('Griffe finden', () => {
  it('findet nach Titel und Suchwörtern', () => {
    expect(titel('zusammenfassung')[0]).toBe('Zusammenfassung anlegen');
    expect(titel('bericht woche')[0]).toBe('Zusammenfassung anlegen');
    expect(titel('modell wechseln')[0]).toBe('Modell wechseln');
  });

  it('an/aus entscheidet; „ein“ heißt an; was schon so steht, kommt nach hinten', () => {
    expect(titel('lesezeichen bericht an')[0]).toBe('Lesezeichen Bericht an');
    expect(titel('schalte lesezeichen bericht ein')[0]).toBe('Lesezeichen Bericht an');
    expect(titel('lesezeichen bericht')[0]).toBe('Lesezeichen Bericht an'); // „aus“ steht schon so → hinten
  });

  it('kurze Wörter nur genau: „an“ findet nicht „Anker“', () => {
    expect(titel('an')).toEqual([]);
    expect(titel('anker')).toEqual(['Anker Vorlage']);
  });

  it('eine Frage an den Agenten ist kein Griff', () => {
    expect(titel('wie spät ist es in tokio')).toEqual([]);
    expect(titel('x')).toEqual([]);
    expect(titel('')).toEqual([]);
  });
});

describe('Quellen laden', () => {
  it('fragt das Werkzeug griffe.liste', async () => {
    const gefragt: string[] = [];
    const q = await griffQuellenLaden(async <T,>(w: string) => {
      gefragt.push(w);
      return { griffe: [{ id: 'a', titel: 'A', werkzeug: 'a.tun' }] } as T;
    });
    expect(gefragt).toEqual(['griffe.liste']);
    expect(griffeBauen(q).map((g) => g.id)).toEqual(['a']);
  });

  it('ein Ausfall (Plugin nicht eingerichtet) lässt die Liste leer', async () => {
    const q = await griffQuellenLaden(async () => undefined);
    expect(q.griffe).toBeUndefined();
    expect(griffeBauen(q)).toEqual([]);
    expect((await griffQuellenLaden(async <T,>() => ({ griffe: 'x' }) as T)).griffe).toBeUndefined();
  });
});
