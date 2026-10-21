/**
 * Raum Atelier (components/raeume/RaumAtelier.tsx, BildWerkstatt.tsx): Leiste nach Tätigkeit, Geschichten öffnen ihre
 * App, Bild erzeugen über medien.*: fehlen die Medien-Werkzeuge, sagt der Raum „Noch nicht eingerichtet.“.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '~/lib/api/client';

vi.mock('~/lib/mcp-apps/host', () => ({ apps: async () => [] }));
vi.mock('~/components/apps/AppEingebettet', () => ({ default: () => <div data-testid="app" /> }));
vi.mock('~/components/os/Fenster', () => ({ Inhalt: () => <div data-testid="seite" /> }));
const hubMock = vi.fn();
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hubMock(...a) }));

import RaumAtelier, { EINTRAEGE } from '~/components/raeume/RaumAtelier';

beforeEach(() => {
  localStorage.clear();
  hubMock.mockReset();
});
afterEach(() => cleanup());

const oeffne = vi.fn();
const zeigen = () => render(() => <RaumAtelier oeffne={oeffne} schmal={false} heim={vi.fn()} />);
const knopf = (id: string) => document.querySelector(`[data-atelier="${id}"]`) as HTMLButtonElement;

describe('Raum Atelier', () => {
  it('gliedert nach Tätigkeit', () => {
    hubMock.mockResolvedValue({ erreichbar: true, satz: 'Der Bild-Dienst läuft.' });
    zeigen();
    expect([...document.querySelectorAll('[data-atelier-gruppe]')].map((g) => g.getAttribute('data-atelier-gruppe'))).toEqual([
      'Erzeugen',
      'Schreiben',
      'Bearbeiten',
    ]);
  });

  it('Geschichten öffnen ihre App, Geplantes sagt, woher es kommt', () => {
    hubMock.mockResolvedValue({});
    zeigen();
    fireEvent.click(knopf('geschichten'));
    fireEvent.click(document.querySelector('[data-atelier-oeffnen]')!);
    expect(oeffne).toHaveBeenCalledWith('app:geschichten__liste');
    fireEvent.click(knopf('dokumente'));
    expect(document.querySelector('[data-atelier-mitte="dokumente"]')!.textContent).toContain('PDF');
    expect(EINTRAEGE.filter((e) => e.inhalt.art === 'geplant').map((e) => e.id)).toEqual(['video', 'dokumente', 'photo', 'vektor']);
  });

  it('erzeugt ein Bild: medien.bild, dann medien.datei, und zeigt es', async () => {
    hubMock.mockImplementation((tool: string) => {
      if (tool === 'medien.status') return Promise.resolve({ erreichbar: true, satz: 'Der Bild-Dienst läuft.' });
      if (tool === 'medien.bild') return Promise.resolve({ ok: true, id: 'b1', datei: '2026-10-21/b1.png', satz: 'Bild b1 in 8 s.' });
      if (tool === 'medien.datei') return Promise.resolve({ base64: 'AAAA', mime: 'image/png' });
      return Promise.reject(new Error(tool));
    });
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-medien-status]')!.textContent).toContain('Bild-Dienst'));
    fireEvent.input(screen.getByRole('textbox', { name: 'Beschreibung des Bildes' }), { target: { value: 'Ein Leuchtturm im Nebel' } });
    fireEvent.click(screen.getByRole('button', { name: 'Erzeugen' }));
    await waitFor(() => expect(document.querySelector('[data-bild="b1"] img')).toBeTruthy());
    expect(hubMock).toHaveBeenCalledWith('medien.bild', { prompt: 'Ein Leuchtturm im Nebel' }, expect.objectContaining({ art: 'bewusst' }));
    expect((document.querySelector('[data-bild="b1"] img') as HTMLImageElement).src).toContain('data:image/png;base64,AAAA');
    // Mit nur einem Modell gibt es keine Auswahl
    expect(screen.queryByRole('combobox', { name: 'Modell' })).toBeNull();
  });

  it('ein Dienst, der gerade nicht kann, ist ein Satz, kein Absturz', async () => {
    hubMock.mockImplementation((tool: string) =>
      Promise.resolve(tool === 'medien.bild' ? { ok: false, nicht_jetzt: true, satz: 'Gerade kein Bild: Dienst ausgelastet' } : { erreichbar: true, satz: 'ok' }),
    );
    zeigen();
    fireEvent.input(screen.getByRole('textbox', { name: 'Beschreibung des Bildes' }), { target: { value: 'Katze' } });
    fireEvent.click(screen.getByRole('button', { name: 'Erzeugen' }));
    await waitFor(() => expect(document.querySelector('[data-bild-meldung]')!.textContent).toContain('Dienst ausgelastet'));
    expect(document.querySelector('[data-bild]')).toBeNull();
  });

  it('fehlende oder gesperrte Medien-Werkzeuge (403/404) sagen „Noch nicht eingerichtet.“ statt eines toten Knopfs', async () => {
    hubMock.mockRejectedValue(new ApiError(403, undefined, 'kein Flächen-Werkzeug'));
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-medien-gesperrt]')).toBeTruthy());
    expect(document.querySelector('[data-medien-gesperrt]')!.textContent).toContain('Noch nicht eingerichtet.');
    expect(screen.queryByRole('button', { name: 'Erzeugen' })).toBeNull();
  });
});
