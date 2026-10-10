/**
 * Menümodell und Gesten des FYOS-OS: was nicht kaputtgehen darf, ohne dass man es sofort
 * sieht — leere Untermenüs, doppelte Trenner, ein Menü, das aus dem Fenster ragt, ein Wischen,
 * das am Rand ins Leere läuft, ein Kneifen, das zu früh auslöst.
 */
import { describe, expect, it } from 'vitest';
import { gummiband, kneifen, wischZiel } from '~/lib/os/gesten';
import { aufraeumen, lage, naechster, type MenuePunkt } from '~/lib/os/menue';

const p = (text: string, aus = false): MenuePunkt => ({ text, aus, tun: () => {} });

describe('Menümodell', () => {
  it('räumt Trenner am Anfang, am Ende und doppelte weg; leere Untermenüs fallen raus', () => {
    const r = aufraeumen([
      { art: 'trenner' },
      p('A'),
      { art: 'trenner' },
      { art: 'trenner' },
      false,
      { art: 'unter', text: 'Leer', punkte: [{ art: 'trenner' }] },
      p('B'),
      { art: 'trenner' },
    ]);
    expect(r.map((x) => ('text' in x ? x.text : x.art))).toEqual(['A', 'trenner', 'B']);
  });

  it('Pfeiltasten überspringen Trenner und ausgegraute Punkte, rundum', () => {
    const l: MenuePunkt[] = [p('A'), { art: 'trenner' }, p('B', true), p('C')];
    expect(naechster(l, 0, 1)).toBe(3);
    expect(naechster(l, 3, 1)).toBe(0);
    expect(naechster(l, 0, -1)).toBe(3);
    expect(naechster([p('X', true)], -1, 1)).toBe(-1);
  });

  it('ein Menü am rechten oder unteren Rand klappt nach innen', () => {
    expect(lage(100, 100, 200, 300, 1000, 800)).toEqual({ x: 100, y: 100 });
    expect(lage(900, 100, 200, 300, 1000, 800)).toEqual({ x: 700, y: 100 });
    expect(lage(100, 700, 200, 300, 1000, 800)).toEqual({ x: 100, y: 492 });
  });
});

describe('Gesten', () => {
  it('zwischen zwei Bildschirmen folgt das Band dem Finger, am Rand gibt es zäh nach', () => {
    expect(gummiband(-300, 1000, true, true)).toBe(-300);
    const rand = gummiband(-300, 1000, true, false);
    expect(rand).toBeLessThan(0);
    expect(Math.abs(rand)).toBeLessThan(200);
    expect(gummiband(5000, 1000, true, true)).toBe(1000);
  });

  it('weit genug oder schnell genug gewischt wechselt, sonst zurück', () => {
    expect(wischZiel(-250, 1000, 0, true, true)).toBe(1);
    expect(wischZiel(250, 1000, 0, true, true)).toBe(-1);
    expect(wischZiel(-60, 1000, 0, true, true)).toBe(0);
    expect(wischZiel(-60, 1000, -0.8, true, true)).toBe(1);
    expect(wischZiel(-500, 1000, 0, true, false)).toBe(0);
  });

  it('Kneifen löst erst nach einer Schwelle aus', () => {
    expect(kneifen(30)).toBeNull();
    expect(kneifen(90)).toBe('zu');
    expect(kneifen(-90)).toBe('auf');
  });
});
