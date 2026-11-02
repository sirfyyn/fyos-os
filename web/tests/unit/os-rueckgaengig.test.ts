/**
 * „Rückgängig“ nach dem Schließen (lib/os/rueckgaengig.ts): geschlossene Fenster und Bildschirme
 * kommen an dieselbe Stelle zurück.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { leer, neuerBildschirm, entfernen, START, type Arbeitsplatz } from '~/lib/os/bildschirme';
import { bildschirmZurueck, fensterZurueck, geschlossene, schliessText } from '~/lib/os/rueckgaengig';

describe('Rückgängig nach dem Schließen', () => {
  const mitFenstern = (): Arbeitsplatz => neuerBildschirm(leer(), 'Arbeit', [
    { id: 'seite:a', min: false, spalten: 6, zeilen: 10 },
    { id: 'seite:b', min: false },
    { id: 'seite:c', min: true },
  ]);
  it('holt geschlossene Fenster an ihre Stelle zurück, mit Größe', () => {
    const ap = mitFenstern();
    const b = ap.bildschirme[0]!;
    const neu = b.fenster.filter((w) => w.id !== 'seite:a');
    const weg = geschlossene(b.fenster, neu);
    expect(weg).toEqual([{ fenster: b.fenster[0], index: 0 }]);
    const zu = { ...ap, bildschirme: [{ ...b, fenster: neu }] };
    const zurueck = fensterZurueck(zu, b.id, weg);
    expect(zurueck.bildschirme[0]!.fenster).toEqual(b.fenster);
    expect(zurueck.aktiv).toBe(1);
  });
  it('überspringt, was inzwischen anderswo offen ist, und legt einen fehlenden Bildschirm neu an', () => {
    const ap = mitFenstern();
    const b = ap.bildschirme[0]!;
    const weg = geschlossene(b.fenster, []);
    const anderswo = neuerBildschirm(leer(), 'Anderer', [{ id: 'seite:b', min: false }]);
    const zurueck = fensterZurueck(anderswo, b.id, weg);
    expect(zurueck.bildschirme).toHaveLength(2);
    expect(zurueck.bildschirme[1]!.fenster.map((w) => w.id)).toEqual(['seite:a', 'seite:c']);
    expect(fensterZurueck(ap, b.id, weg)).toBe(ap); // alles noch offen: nichts zu tun
  });
  it('holt einen entfernten Bildschirm an seine Stelle zurück', () => {
    let ap = neuerBildschirm(mitFenstern(), 'Zweiter', [{ id: 'seite:z', min: false }]);
    ap = neuerBildschirm(ap, 'Dritter');
    const zweiter = ap.bildschirme[1]!;
    const ohne = entfernen(ap, 2);
    const zurueck = bildschirmZurueck(ohne, 2, zweiter);
    expect(zurueck.bildschirme.map((b) => b.name)).toEqual(['Arbeit', 'Zweiter', 'Dritter']);
    expect(zurueck.aktiv).toBe(2);
    expect(bildschirmZurueck(zurueck, 2, zweiter)).toBe(zurueck); // schon da
    expect(zurueck.aktiv).not.toBe(START);
  });
  it('Text der Karte', () => {
    expect(schliessText(['Kalender'])).toBe('„Kalender“ geschlossen.');
    expect(schliessText(['A', 'B'])).toBe('2 Fenster geschlossen.');
    expect(schliessText([], 'Eins')).toBe('„Eins“ entfernt.');
  });
});

describe('Die Karte oben rechts', () => {
  // 0.1.2 zeigte nach dem Schließen keine Karte: die Shell gab Mitteilungen ein eigenes Signal statt der geteilten Karte
  // Seit 0.1.4 zeigt die Brücke die Karte (components/os/Bruecke.tsx), die Shell hängt nur die Brücke ein
  it('liest die Brücke aus der geteilten Karte, in die rueckgaengigAnbieten schreibt', () => {
    const bruecke = readFileSync(resolve(process.cwd(), 'src/components/os/Bruecke.tsx'), 'utf8');
    expect(bruecke).toContain('const hinweis = rueckHinweis;');
    expect(bruecke).toContain('hinweis={hinweis}');
    expect(bruecke).toContain('rueckgaengigAnbieten(h)');
    const shell = readFileSync(resolve(process.cwd(), 'src/components/os/Shell.tsx'), 'utf8');
    expect(shell).toContain('<Bruecke');
    expect(shell).not.toContain('<Mitteilungen');
    expect(shell).not.toContain('setMittHinweis');
  });
});
