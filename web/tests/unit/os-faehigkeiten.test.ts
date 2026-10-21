/**
 * Feste Schalter Agent / Voice / Eyes: Zustand und Schalten über die Hub-Werkzeuge der eingerichteten Plugins.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';

const hub = vi.fn();
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hub(...a) }));

const { anstossen, laden, schalten } = await import('~/lib/os/faehigkeiten');

beforeEach(() => hub.mockReset());
afterEach(() => konfigurationZuruecksetzen());

describe('Fähigkeiten', () => {
  it('Agent: Schleifen als Schalter, Hinweis wenn an aber wartet; der Name kommt aus der Konfiguration', async () => {
    konfigurationSetzen({ agent: { name: 'Robin' } });
    hub.mockResolvedValueOnce({
      satz: 'Der Agent wartet.',
      schleifen: [
        { id: 'arbeit', name: 'Arbeitsschleife', an: true, darf_jetzt: false, warum: 'Das Modell ist nicht frei.' },
        { id: 'gedaechtnis', name: 'Gedächtnisschleife', an: false, darf_jetzt: false },
      ],
    });
    const f = await laden('agent');
    expect(hub).toHaveBeenCalledWith('schleifen.zustand');
    expect(f.name).toBe('Robin');
    expect(f.aktiv).toBe(true);
    expect(f.schalter).toEqual([
      { id: 'arbeit', text: 'Arbeitsschleife', an: true, hinweis: 'Das Modell ist nicht frei.', anstoss: 'moeglich' },
      { id: 'gedaechtnis', text: 'Gedächtnisschleife', an: false, hinweis: undefined, anstoss: undefined },
    ]);
  });

  it('Agent anstoßen: über schleifen.anstossen; aus = Fehler mit dem Satz des Hubs', async () => {
    hub
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ schleifen: [{ id: 'gedaechtnis', name: 'Gedächtnisschleife', an: true, darf_jetzt: true, angestossen: { seit: 'x' } }] });
    const f = await anstossen('gedaechtnis');
    expect(hub).toHaveBeenNthCalledWith(1, 'schleifen.anstossen', { schleife: 'gedaechtnis', von: 'nutzer' });
    expect(f.schalter[0]?.anstoss).toBe('laeuft');
    hub.mockResolvedValueOnce({ ok: false, warum: 'Die Arbeitsschleife ist aus.' });
    await expect(anstossen('arbeit')).rejects.toThrow('Die Arbeitsschleife ist aus.');
  });

  it('Voice: Lauscher je Raum; Dienst weg = nicht erreichbar (aktiv null)', async () => {
    hub.mockResolvedValueOnce({ erreichbar: true, satz: 'Die Stimme hört im Raum Nord zu.', lauscher: [{ raum: 'nord', an: true }, { raum: 'buero', an: false }] });
    const f = await laden('stimme');
    expect(f.aktiv).toBe(true);
    expect(f.schalter.map((s) => s.text)).toEqual(['Nord', 'Büro']);
    hub.mockResolvedValueOnce({ erreichbar: false });
    expect((await laden('stimme')).aktiv).toBeNull();
  });

  it('fehlendes Werkzeug zeigt „Noch nicht eingerichtet.“ statt eines falschen Zustands', async () => {
    hub.mockRejectedValueOnce(new Error('tool not_found: augen.zustand'));
    const f = await laden('augen');
    expect(f.aktiv).toBeNull();
    expect(f.satz).toBe('Noch nicht eingerichtet.');
    expect(f.schalter).toEqual([]);
  });

  it('403 und 404 des Hubs heißen auch „nicht eingerichtet“, ein anderer Fehler „gerade nicht erreichbar“', async () => {
    hub.mockRejectedValueOnce(new Error('403 Forbidden'));
    expect((await laden('stimme')).satz).toBe('Noch nicht eingerichtet.');
    hub.mockRejectedValueOnce(new Error('Failed to fetch'));
    expect((await laden('stimme')).satz).toBe('Gerade nicht erreichbar.');
  });

  it('schaltet über die richtigen Werkzeuge', async () => {
    hub.mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ schleifen: [] });
    await schalten('agent', 'alle', false);
    expect(hub).toHaveBeenNthCalledWith(1, 'schleifen.schalten', { schleife: 'alle', an: false, von: 'nutzer' });
    hub.mockResolvedValueOnce({ erreichbar: true, lauscher: [] });
    await schalten('stimme', 'nord', true);
    expect(hub).toHaveBeenLastCalledWith('stimme.lauscher', { raum: 'nord', an: true, von: 'nutzer' });
    hub.mockResolvedValueOnce({ erreichbar: true, kameras: [{ name: 'garten', erkennung: false }] });
    const f = await schalten('augen', 'garten', false);
    expect(hub).toHaveBeenLastCalledWith('augen.schalten', { kamera: 'garten', an: false, von: 'nutzer' });
    expect(f.schalter[0]).toMatchObject({ id: 'garten', an: false });
  });
});
