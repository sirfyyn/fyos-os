/**
 * Werkzeug-Register (lib/werkzeuge.ts) und hub() — die Agenten-Schnittstelle der Seite.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { liste, registriereWerkzeuge, rufen } from '../../src/lib/werkzeuge';
import { hub } from '../../src/lib/hub';

afterEach(() => {
  vi.unstubAllGlobals();
  delete (document as unknown as { modelContext?: unknown }).modelContext;
  delete (navigator as unknown as { modelContext?: unknown }).modelContext;
});

describe('Werkzeug-Register', () => {
  it('meldet an, ruft auf und meldet beim Seitenwechsel wieder ab', async () => {
    registriereWerkzeuge([{ name: 'zeige_lauf', beschreibung: 'x', lesend: true, ausfuehren: async (a) => ({ lauf: a.lauf }) }]);
    expect(liste().map((w) => w.name)).toContain('zeige_lauf');
    const r = await rufen('zeige_lauf', { lauf: 'b1' });
    expect(r.isError).toBeFalsy();
    expect(JSON.parse(r.content[0]!.text)).toEqual({ lauf: 'b1' });
    document.dispatchEvent(new Event('astro:before-swap'));
    expect(liste().map((w) => w.name)).not.toContain('zeige_lauf');
  });

  it('dauerhafte Werkzeuge überleben den Seitenwechsel, Fehler werden zum Ergebnis', async () => {
    const ab = registriereWerkzeuge([{ name: 'kaputt', beschreibung: 'x', ausfuehren: async () => { throw new Error('Backend weg'); } }], { dauerhaft: true });
    document.dispatchEvent(new Event('astro:before-swap'));
    const r = await rufen('kaputt');
    expect(r).toMatchObject({ isError: true, content: [{ text: 'Backend weg' }] });
    ab();
    expect((await rufen('kaputt')).isError).toBe(true);
    expect((await rufen('kaputt')).content[0]!.text).toMatch(/Unbekanntes Werkzeug/);
  });

  it('ist über window.fyos.werkzeuge erreichbar (Weg für mcp-playwright)', async () => {
    registriereWerkzeuge([{ name: 'ping', beschreibung: 'x', ausfuehren: async () => 'pong' }], { dauerhaft: true });
    const r = await window.fyos!.werkzeuge!.rufen('ping');
    expect(r.content[0]!.text).toBe('pong');
  });

  it('hält WebMCP synchron, wenn der Browser es kann (document.modelContext, Abmelden über das signal)', () => {
    const registerTool = vi.fn();
    (document as unknown as { modelContext: unknown }).modelContext = { registerTool };
    const ab = registriereWerkzeuge([{ name: 'wm_test', beschreibung: 'x', lesend: true, ausfuehren: async () => 1 }], { dauerhaft: true });
    const [werkzeug, optionen] = registerTool.mock.calls.at(-1)! as unknown as [{ name: string; annotations: { readOnlyHint: boolean } }, { signal: AbortSignal }];
    expect(werkzeug.name).toBe('wm_test');
    expect(werkzeug.annotations.readOnlyHint).toBe(true);
    expect(optionen.signal.aborted).toBe(false);
    ab();
    expect(optionen.signal.aborted).toBe(true);
  });
});

describe('hub()', () => {
  const antwort = (d: unknown, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'content-type': 'application/json' } });

  it('liefert das Ergebnis des Hub-Werkzeugs', async () => {
    const f = vi.fn(async () => antwort({ ok: true, result: { farbe: 'gruen' } }));
    vi.stubGlobal('fetch', f);
    expect(await hub('lage.ampel')).toEqual({ farbe: 'gruen' });
    expect(JSON.parse((f.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ tool: 'lage.ampel', arguments: {} });
  });

  it('meldet den Werkzeugfehler mit dem Text des Hubs', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => antwort({ ok: false, error: 'Prometheus nicht erreichbar', kind: 'tool_failed' }, 502)));
    await expect(hub('lage.ampel')).rejects.toMatchObject({ message: 'Prometheus nicht erreichbar', status: 502 });
  });
});
