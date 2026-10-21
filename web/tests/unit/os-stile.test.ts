/**
 * Wächter für die Stylesheets der Shell.
 *
 * Lightning CSS (über Tailwind) setzt Herstellerpräfixe nur für feste Werte selbst. Die Glasflächen der Shell
 * nehmen den Filter aus Variablen (`--os-glas-filter`, `--os-glas-filter-leicht`); dafür steht das Präfix von Hand
 * davor, mit demselben Wert, und `backdrop-filter` folgt gleich darauf. Fehlt eines von beiden, verlieren Safari
 * oder Chrome die Unschärfe (die ⌘K-Palette zeigte den Schreibtisch scharf durch).
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const STILE = resolve(__dirname, '../../src/styles');

describe('OS-Stile', () => {
  it('ein handgeschriebenes -webkit-backdrop-filter hat gleich danach backdrop-filter mit demselben Wert', () => {
    const funde = readdirSync(STILE)
      .filter((name) => name.endsWith('.css'))
      .flatMap((name) => {
        const zeilen = readFileSync(resolve(STILE, name), 'utf8').split('\n');
        return zeilen.flatMap((zeile, i) => {
          const m = /^\s*-webkit-backdrop-filter\s*:\s*(.+);\s*$/.exec(zeile);
          if (!m) return [];
          const danach = /^\s*backdrop-filter\s*:\s*(.+);\s*$/.exec(zeilen[i + 1] ?? '');
          return danach && danach[1] === m[1] ? [] : [`${name}:${i + 1}`];
        });
      });
    expect(funde).toEqual([]);
  });

  it('die ⌘K-Palette behält ihre Unschärfe', () => {
    const os = readFileSync(resolve(STILE, 'os.css'), 'utf8');
    const panel = os.slice(os.indexOf('.os-start-panel {'), os.indexOf('}', os.indexOf('.os-start-panel {')));
    expect(panel).toContain('backdrop-filter: var(--os-glas-filter);');
  });
});
