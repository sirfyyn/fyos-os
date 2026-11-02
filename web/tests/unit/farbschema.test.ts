/**
 * Farbschema: ohne Wahl folgt die Oberfläche dem Gerät (seit 0.3.0), Menü und Kontrollzentrum (lib/os/thema.ts)
 * schreiben dieselben Schlüssel wie die Einstellungen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FARBSCHEMA_STANDARD, aufloesen, farbschemaAnwenden, farbschemaAus, farbschemaLaden, hoereFarbschema } from '~/lib/einstellungen/farbschema';
import { themaSetzen, themaWahl } from '~/lib/os/thema';

function geraet(hell: boolean) {
  const hoerer = new Set<() => void>();
  const mq = {
    matches: hell,
    addEventListener: (_: string, f: () => void) => hoerer.add(f),
    removeEventListener: (_: string, f: () => void) => hoerer.delete(f),
  };
  vi.stubGlobal('matchMedia', vi.fn(() => mq));
  return {
    umschalten(h: boolean) {
      mq.matches = h;
      for (const f of hoerer) f();
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Farbschema', () => {
  it('ohne gespeicherte Wahl gilt System, auch das alte „auto“', () => {
    expect(FARBSCHEMA_STANDARD).toBe('system');
    expect(farbschemaAus(null, null)).toBe('system');
    expect(farbschemaAus('dark', 'auto')).toBe('system');
    expect(farbschemaAus('light', null)).toBe('hell');
    expect(farbschemaAus(null, 'manual:dark')).toBe('dunkel');
  });

  it('System löst nach dem Gerät auf und zieht bei einem Wechsel nach', () => {
    const g = geraet(true);
    expect(farbschemaAnwenden()).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    const f = vi.fn();
    const ab = hoereFarbschema(f);
    g.umschalten(false);
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(f).toHaveBeenCalledWith('system', 'dark');
    ab();
  });

  it('eine feste Wahl bleibt, egal was das Gerät meldet', () => {
    geraet(true);
    expect(aufloesen('dunkel')).toBe('dark');
    themaSetzen('dark');
    expect(farbschemaLaden()).toBe('dunkel');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('Menü und Kontrollzentrum: Hell/Dunkel/System über dieselben Schlüssel', () => {
    geraet(false);
    expect(themaWahl()).toBe('system');
    themaSetzen('light');
    expect(localStorage.getItem('fyos-theme-mode')).toBe('manual:light');
    expect(localStorage.getItem('fyos-theme')).toBe('light');
    expect(themaWahl()).toBe('light');
    themaSetzen('system');
    expect(localStorage.getItem('fyos-theme-mode')).toBe('system');
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(themaWahl()).toBe('system');
  });
});
