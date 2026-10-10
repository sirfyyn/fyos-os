/**
 * MCP Apps: die ui://-Oberflaeche eines Hub-Plugins laeuft im Sandbox-iframe NUR mit
 * allow-scripts und allow-forms — Ursprung „null", kein Zugriff auf Cookies/Speicher von fyos-web —,
 * und aus der App heraus sind nur Werkzeuge desselben Plugins aufrufbar.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { APP_SANDBOX, appCsp, appEinhaengen, type McpApp } from '../../src/lib/mcp-apps/host';

const APP: McpApp = {
  tool: 'fle.messungen',
  name: 'fle__messungen',
  description: '',
  inputSchema: {},
  _meta: { ui: { resourceUri: 'ui://fyos/fle/messcockpit.html' } },
  scope: 'READ',
};

afterEach(() => vi.restoreAllMocks());

describe('MCP-Apps-Host — Sandbox', () => {
  it('setzt sandbox=allow-scripts allow-forms ohne allow-same-origin', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true, text: '<p>x</p>' }))));
    const f = document.createElement('iframe');
    document.body.appendChild(f);
    const ab = await appEinhaengen(f, { app: APP, args: {}, ergebnis: { content: [] }, theme: () => 'dark' });
    expect(f.getAttribute('sandbox')).toBe('allow-scripts allow-forms');
    expect(f.getAttribute('sandbox')).toBe(APP_SANDBOX);
    expect(f.getAttribute('sandbox')).not.toContain('allow-same-origin');
    ab();
  });

  it('erlaubt genau Skripte und Formulare und sonst nichts', () => {
    // allow-forms: ohne das Recht feuert das submit-Ereignis gar nicht (Notizzettel: Knopf wie Enter blockiert).
    expect(APP_SANDBOX.split(' ').sort()).toEqual(['allow-forms', 'allow-scripts']);
  });

  it('lässt ein echtes Absenden gesperrt: form-action none in den Inhaltsregeln', () => {
    // Die Formulare der Apps werden per Skript behandelt (preventDefault); ein natives Absenden fände kein Ziel.
    expect(appCsp()).toContain("form-action 'none'");
    // auch eine Ressource kann es nicht öffnen: _meta.ui.csp kennt kein form-action
    expect(appCsp({ ui: { csp: { connectDomains: ['https://api.example.com'], 'form-action': ['https://x.example.com'], formDomains: ['https://x.example.com'] } } }))
      .toContain("form-action 'none'");
    expect(appCsp({ ui: { csp: { connectDomains: ['https://api.example.com'], 'form-action': ['https://x.example.com'] } } }))
      .not.toContain('x.example.com');
  });

  it('lehnt Werkzeugaufrufe an fremde Plugins ab', async () => {
    const aufrufe: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      aufrufe.push(String(url));
      return new Response(JSON.stringify({ ok: true, text: '<p>x</p>', result: {} }));
    }));
    const f = document.createElement('iframe');
    document.body.appendChild(f);
    const antworten: unknown[] = [];
    const ab = await appEinhaengen(f, { app: APP, args: {}, ergebnis: { content: [] }, theme: () => 'dark' });
    vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => { antworten.push(m); });
    window.dispatchEvent(new MessageEvent('message', {
      source: f.contentWindow,
      data: { jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name: 'k8s__exec_pod', arguments: {} } },
    }));
    await new Promise((r) => setTimeout(r, 0));
    expect(aufrufe.some((u) => u.includes('app-call'))).toBe(false);
    expect(antworten).toContainEqual(expect.objectContaining({ id: 7, error: expect.anything() }));
    ab();
  });
});
