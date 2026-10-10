/**
 * Angeheftete Hub-Apps (lib/mcp-apps/pins.ts).
 *
 * Was schiefgehen würde, ohne dass es jemand merkt: ein Startbildschirm, der ohne Pins etwas
 * zeigt oder nachlädt, ein Pin auf eine schreibende App (würde beim Laden etwas auslösen),
 * oder ein Pin, der nach dem Entfernen des Werkzeugs aus dem Hub den Startbildschirm zerlegt.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apps = vi.hoisted(() => vi.fn());
const appCall = vi.hoisted(() => vi.fn());
vi.mock('~/lib/mcp-apps/host', () => ({
  apps,
  appCall,
  appEinhaengen: vi.fn(async () => () => {}),
  aktuellesTheme: () => 'dark',
}));

import { MAX_PINS, aufrufbar, istAngepinnt, pinUmschalten, pins, startbar } from '~/lib/mcp-apps/pins';

const app = (name: string, extra: Record<string, unknown> = {}) => ({
  tool: name.replace('__', '.'),
  name,
  title: name,
  description: '',
  inputSchema: {},
  _meta: { ui: { resourceUri: 'ui://x' } },
  scope: 'READ',
  ...extra,
});

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    clear: () => m.clear(),
  });
  apps.mockReset();
  appCall.mockReset();
  appCall.mockResolvedValue({ content: [{ type: 'text', text: '{}' }] });
});
afterEach(() => vi.unstubAllGlobals());

describe('pins', () => {
  it('schaltet um und merkt sich', () => {
    expect(pinUmschalten('a__b')).toBe(true);
    expect(istAngepinnt('a__b')).toBe(true);
    expect(pinUmschalten('a__b')).toBe(false);
    expect(pins()).toEqual([]);
  });

  it('hält höchstens MAX_PINS', () => {
    for (let i = 0; i < MAX_PINS + 2; i++) pinUmschalten(`p__${i}`);
    expect(pins()).toHaveLength(MAX_PINS);
  });

  it('übersteht kaputten Speicher', () => {
    localStorage.setItem('fyos:app-pins', '{kaputt');
    expect(pins()).toEqual([]);
    localStorage.setItem('fyos:app-pins', JSON.stringify([1, 'ok__x', null]));
    expect(pins()).toEqual(['ok__x']);
  });
});

describe('startbar', () => {
  it('nur lesend und ohne Pflichtfelder', () => {
    expect(startbar(app('a__b') as never)).toBe(true);
    expect(startbar(app('a__b', { scope: 'WRITE' }) as never)).toBe(false);
    expect(startbar(app('a__b', { inputSchema: { required: ['x'] } }) as never)).toBe(false);
  });
});

describe('aufrufbar', () => {
  const mitPflicht = app('a__b', { inputSchema: { required: ['id', 'q'] } }) as never;

  it('lesend und alle Pflichtfelder belegt', () => {
    expect(aufrufbar(mitPflicht, { id: '1', q: 'x' })).toBe(true);
    expect(aufrufbar(mitPflicht, { id: '1' })).toBe(false);
    expect(aufrufbar(mitPflicht, {})).toBe(false);
  });

  it('null und undefined belegen nichts; 0, false und leerer Text schon', () => {
    expect(aufrufbar(mitPflicht, { id: null, q: 'x' })).toBe(false);
    expect(aufrufbar(mitPflicht, { id: undefined, q: 'x' })).toBe(false);
    expect(aufrufbar(mitPflicht, { id: 0, q: false })).toBe(true);
    expect(aufrufbar(mitPflicht, { id: '', q: '' })).toBe(true);
  });

  it('schreibend nie, auch nicht mit allen Angaben', () => {
    expect(aufrufbar(app('a__b', { scope: 'WRITE' }) as never, {})).toBe(false);
    expect(aufrufbar(app('a__b', { scope: 'WRITE', inputSchema: { required: ['x'] } }) as never, { x: 1 })).toBe(false);
  });

  it('ohne Pflichtfelder genügt lesend', () => {
    expect(aufrufbar(app('a__b') as never, {})).toBe(true);
    expect(aufrufbar(app('a__b', { inputSchema: undefined }) as never, {})).toBe(true);
  });
});
