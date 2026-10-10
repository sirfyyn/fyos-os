/**
 * Flächen-Werkzeuge ohne ui://-Oberfläche (Stimme, Augen melden `_meta.ui = {}`) sind keine Apps:
 * `apps()` nimmt nur Werkzeuge mit echter `resourceUri` — sonst wird daraus eine Karte, die beim Öffnen mit
 * `ressourceLesen(undefined)` scheitert.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apps } from '~/lib/mcp-apps/host';

const werkzeug = (name: string, meta: Record<string, unknown>) => ({
  tool: name.replace('__', '.'),
  name,
  description: '',
  inputSchema: {},
  _meta: meta,
  scope: 'READ',
  hatUi: 'ui' in meta,
});

afterEach(() => vi.unstubAllGlobals());

describe('apps()', () => {
  it('lässt Werkzeuge mit leerem `ui: {}` und ohne `ui` weg', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            apps: [
              werkzeug('haus__favoriten', { ui: { resourceUri: 'ui://fyos/haus.html' } }),
              werkzeug('stimme__zustand', { ui: {} }),
              werkzeug('augen__zustand', { ui: {} }),
              werkzeug('lage__ampel', {}),
              werkzeug('haus__schalten', { ui: { resourceUri: 'ui://fyos/haus.html', visibility: ['app'] } }),
            ],
          }),
        ),
      ),
    );
    expect((await apps(true)).map((a) => a.name)).toEqual(['haus__favoriten']);
    expect((await apps(false)).map((a) => a.name)).toEqual(['haus__favoriten', 'haus__schalten']);
  });
});
