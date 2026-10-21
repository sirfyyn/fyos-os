/**
 * „Der Agent zeigt dir …“ über die Brücke (lib/os/agent-zeigt.ts): die Nutzlast des Hubs mit Symbol, Farbton,
 * Dringlichkeit und Audio-Anweisung; Stapel und Einstellung kommen aus lib/os/mitteilungen.ts (os-mitteilung.test.tsx).
 */
import { describe, expect, it } from 'vitest';
import { hinzufuegen, istStumm, schluesselVon, zeigtPruefen, type ZeigtDaten } from '~/lib/os/agent-zeigt';
import * as grund from '~/lib/os/mitteilungen';

describe('zeigtPruefen (Brücke)', () => {
  it('verlangt ein Ziel', () => {
    expect(zeigtPruefen(null)).toBeNull();
    expect(zeigtPruefen('x')).toBeNull();
    expect(zeigtPruefen({})).toBeNull();
    expect(zeigtPruefen({ ziel: '   ' })).toBeNull();
    expect(zeigtPruefen({ ziel: 5 })).toBeNull();
  });

  it('liefert die Felder der Mitteilung und die der Brücke', () => {
    const z = zeigtPruefen({ ziel: 'app:notizen__liste', app: 'notizen__liste', titel: 'Notizen', vorschau: '3 Einträge' });
    expect(z).toMatchObject({
      ziel: 'app:notizen__liste',
      app: 'notizen__liste',
      titel: 'Notizen',
      untertitel: null,
      vorschau: '3 Einträge',
      eingabe: null,
      link: null,
      symbol: null,
      ton: null,
      audio: null,
      dringlichkeit: null,
    });
  });

  it('putzt Symbol, nimmt nur eine Zahl als Farbton', () => {
    expect(zeigtPruefen({ ziel: 'seite:a', symbol: '  house ', ton: 210 })).toMatchObject({ symbol: 'house', ton: 210 });
    expect(zeigtPruefen({ ziel: 'a', symbol: 'x'.repeat(100) })?.symbol).toHaveLength(40);
    expect(zeigtPruefen({ ziel: 'a', ton: '210' })?.ton).toBeNull();
    expect(zeigtPruefen({ ziel: 'a', ton: Number.NaN })?.ton).toBeNull();
  });

  it('Dringlichkeit: nur niedrig, normal oder hoch', () => {
    expect(zeigtPruefen({ ziel: 'a', dringlichkeit: 'hoch' })?.dringlichkeit).toBe('hoch');
    expect(zeigtPruefen({ ziel: 'a', dringlichkeit: 'sofort' })?.dringlichkeit).toBeNull();
  });

  it('Audio: Hinweiston und Vorlesen nur bei ausdrücklichem true; der Modus wird gekürzt', () => {
    expect(zeigtPruefen({ ziel: 'a', audio: { modus: 'interaktiv', klang: true, sprechen: true } })?.audio).toEqual({ modus: 'interaktiv', klang: true, sprechen: true });
    expect(zeigtPruefen({ ziel: 'a', audio: { klang: 'ja', sprechen: 1 } })?.audio).toEqual({ modus: 'ton', klang: false, sprechen: false });
    expect(zeigtPruefen({ ziel: 'a', audio: { modus: 'm'.repeat(50) } })?.audio?.modus).toHaveLength(20);
    expect(zeigtPruefen({ ziel: 'a', audio: 'laut' })?.audio).toBeNull();
  });

  it('nachgeholte Mitteilungen behalten ihre Kennzeichen aus lib/os/mitteilungen.ts', () => {
    const z = zeigtPruefen({ ziel: 'a', art: 'mitteilung', nachgeholt: true, entstanden: 1_700_000_000 });
    expect(z).toMatchObject({ art: 'mitteilung', nachgeholt: true, entstanden: 1_700_000_000_000 });
  });
});

describe('Weitergereichtes', () => {
  it('Stapel und Einstellung sind dieselben wie in lib/os/mitteilungen.ts', () => {
    expect(hinzufuegen).toBe(grund.hinzufuegen);
    expect(istStumm).toBe(grund.istStumm);
    expect(schluesselVon).toBe(grund.schluesselVon);
  });

  it('eine erweiterte Nutzlast lässt sich einreihen', () => {
    const z = zeigtPruefen({ ziel: 'seite:a', titel: 'A' }) as ZeigtDaten;
    const liste = hinzufuegen([], z, 1_000);
    expect(liste).toHaveLength(1);
    expect(liste[0]!.zeigt.ziel).toBe('seite:a');
  });
});
