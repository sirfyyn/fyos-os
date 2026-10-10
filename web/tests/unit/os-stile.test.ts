/**
 * Wächter für die Stylesheets der Shell.
 *
 * Lightning CSS (über Tailwind) setzt Herstellerpräfixe selbst. Steht ein handgeschriebenes
 * `-webkit-backdrop-filter` hinter `backdrop-filter`, behält der Minifier nur die letzte Deklaration:
 * Chrome und Firefox verlieren die Unschärfe aller Glasflächen (09.10.: die ⌘K-Palette zeigte den
 * Schreibtisch scharf durch). Deshalb nur `backdrop-filter` schreiben.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const STILE = resolve(__dirname, '../../src/styles');

describe('OS-Stile', () => {
  it('kein handgeschriebenes -webkit-backdrop-filter', () => {
    const funde = readdirSync(STILE)
      .filter((name) => name.endsWith('.css'))
      .flatMap((name) =>
        readFileSync(resolve(STILE, name), 'utf8')
          .split('\n')
          .flatMap((zeile, i) => (/-webkit-backdrop-filter\s*:/.test(zeile) ? [`${name}:${i + 1}`] : [])),
      );
    expect(funde).toEqual([]);
  });

  it('die ⌘K-Palette behält ihre Unschärfe', () => {
    const os = readFileSync(resolve(STILE, 'os.css'), 'utf8');
    const panel = os.slice(os.indexOf('.os-start-panel {'), os.indexOf('}', os.indexOf('.os-start-panel {')));
    expect(panel).toContain('backdrop-filter: blur(40px) saturate(1.8);');
  });
});
