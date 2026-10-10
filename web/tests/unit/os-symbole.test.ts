import { afterEach, describe, expect, it } from 'vitest';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { SYMBOL_TABELLE, farbton, glyphe, symboleSetzen, symboleZuruecksetzen } from '~/lib/os/symbole';
import { SYMBOLE } from '~/lib/os/symbole-daten';

afterEach(() => {
  registerZuruecksetzen();
  symboleZuruecksetzen();
});

describe('OS-Symbole', () => {
  it('jede eingebaute Fläche hat eine eigene Glyphe, und jede Glyphe ist im Satz', () => {
    const glyphen = Object.values(SYMBOL_TABELLE).map(([g]) => g);
    const doppelt = glyphen.filter((g, i) => glyphen.indexOf(g) !== i);
    expect(doppelt).toEqual([]);
    for (const g of glyphen) expect(SYMBOLE[g], g).toBeTruthy();
    expect(glyphen).not.toContain('app-window');
  });

  it('Plugins bringen ihr Symbol über registriereFlaechen mit', () => {
    registriereFlaechen({ symbole: { 'seite:notizen': ['file-text', 200] } });
    expect(glyphe('seite:notizen')).toBe('file-text');
    expect(farbton('seite:notizen')).toBe(200);
  });

  it('Hub-Apps bringen ihr Gesicht selbst mit; ohne bleibt das Fenster-Symbol', () => {
    expect(glyphe('app:unbekannt__x')).toBe('app-window');
    symboleSetzen({ 'app:haus__favoriten': { glyphe: 'house', ton: 26 } });
    expect(glyphe('app:haus__favoriten')).toBe('house');
    expect(farbton('app:haus__favoriten')).toBe(26);
  });

  it('Unbekanntes bekommt einen gültigen Farbton', () => {
    const t = farbton('seite:neu');
    expect(t).toBeGreaterThanOrEqual(0);
    expect(t).toBeLessThan(360);
  });
});
