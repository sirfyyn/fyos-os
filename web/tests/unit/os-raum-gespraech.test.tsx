/**
 * Raum Gespräch (components/raeume/RaumGespraech.tsx): der Agent in der Mitte (native Agent-App), rechts
 * Gespräche, Vorgänge und Kanäle; Hub-Apps kommen eingebettet, Fehlendes steht als „geplant“ oder
 * „Noch nicht eingerichtet.“ da, und die Wahl übersteht das Neuladen.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '~/lib/api/client';
import { konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';

const hub = vi.hoisted(() => ({ namen: [] as string[] }));
vi.mock('~/lib/mcp-apps/host', () => ({ apps: async () => hub.namen.map((name) => ({ name })) }));
// Wie die echte App: `name` zählt nur beim Einhängen (laden() liest es einmal). So fällt auf, wenn ein Wechsel nicht neu einhängt.
vi.mock('~/components/apps/AppEingebettet', () => ({
  default: (p: { name: string; ohneKopf?: boolean }) => {
    const name = p.name;
    return <div data-testid="app" data-name={name} data-ohne-kopf={String(!!p.ohneKopf)} />;
  },
}));
vi.mock('~/components/os/Fenster', () => ({ Inhalt: () => <div data-testid="seite" /> }));
vi.mock('~/components/os/nativ/Agent', () => ({ default: () => <div data-testid="agent-app" /> }));

const hubMock = vi.fn();
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hubMock(...a) }));

import RaumGespraech, { EINTRAEGE } from '~/components/raeume/RaumGespraech';
import { kurzName, ordne } from '~/components/raeume/MatrixVerlauf';

beforeEach(() => {
  localStorage.clear();
  hubMock.mockReset();
  hub.namen = ['vorgaenge__zeigen'];
  konfigurationZuruecksetzen();
});
afterEach(() => cleanup());

const zeigen = (schmal = false) => render(() => <RaumGespraech oeffne={vi.fn()} schmal={schmal} heim={vi.fn()} />);
const knopf = (id: string) => document.querySelector(`[data-gespraech="${id}"]`) as HTMLButtonElement;

describe('Raum Gespräch', () => {
  it('beginnt beim Agenten (native Agent-App, kein iframe) und gliedert die Leiste in Gespräche, Sitzungen und Kanäle', async () => {
    zeigen();
    expect(await screen.findByTestId('agent-app')).toBeTruthy();
    expect(document.querySelector('iframe')).toBeNull();
    const gruppen = [...document.querySelectorAll('[data-gespraech-gruppe]')].map((g) => g.getAttribute('data-gespraech-gruppe'));
    expect(gruppen).toEqual(['Gespräche', 'Agenten-Sitzungen', 'Kanäle']);
    expect(knopf('agent').getAttribute('aria-current')).toBe('page');
  });

  it('nimmt den Namen des Agenten aus der Konfiguration', () => {
    konfigurationSetzen({ agent: { name: 'Mira' } });
    zeigen();
    expect(knopf('agent').textContent).toContain('Mira');
  });

  it('bettet die Hub-Apps ohne zweite Überschrift ein und merkt sich die Wahl', async () => {
    zeigen();
    fireEvent.click(knopf('vorgaenge'));
    const app = await screen.findByTestId('app');
    expect(app.dataset.name).toBe('vorgaenge__zeigen');
    expect(app.dataset.ohneKopf).toBe('true');
    expect(screen.queryByTestId('agent-app')).toBeNull();
    cleanup();
    zeigen();
    expect((await screen.findByTestId('app')).dataset.name).toBe('vorgaenge__zeigen');
  });

  it('eine App, die der Hub nicht kennt, sagt „Noch nicht eingerichtet.“', async () => {
    hub.namen = [];
    zeigen();
    fireEvent.click(knopf('vorgaenge'));
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(document.querySelector('[data-nicht-eingerichtet]')!.textContent).toContain('Noch nicht eingerichtet.');
    expect(screen.queryByTestId('app')).toBeNull();
  });

  it('Matrix liest chat.matrix_lesen, ältere oben, Absender kurz', async () => {
    hubMock.mockResolvedValue({
      raum: 'allgemein',
      nachrichten: [
        { sender: '@robin:matrix.example.org', ts: 2000, text: 'Antwort' },
        { sender: '@alex:matrix.example.org', ts: 1000, text: 'Frage' },
        { sender: '@alex:matrix.example.org', ts: 1500, text: '  ' },
      ],
    });
    zeigen();
    fireEvent.click(knopf('matrix'));
    await waitFor(() => expect(document.querySelectorAll('[data-matrix-nachricht]').length).toBe(2));
    expect(hubMock).toHaveBeenCalledWith('chat.matrix_lesen', { limit: 50 });
    const texte = [...document.querySelectorAll('[data-matrix-nachricht]')].map((n) => n.textContent);
    expect(texte[0]).toContain('alex');
    expect(texte[0]).toContain('Frage');
    expect(texte[1]).toContain('robin');
    expect(kurzName('@robin:matrix.example.org')).toBe('robin');
    expect(ordne(undefined)).toEqual([]);
  });

  it('Matrix nicht erreichbar sagt es, statt leer zu bleiben', async () => {
    hubMock.mockRejectedValue(new Error('weg'));
    zeigen();
    fireEvent.click(knopf('matrix'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('nicht erreichbar'));
  });

  it('Matrix ohne Plugin oder ohne Freigabe (403/404) sagt „Noch nicht eingerichtet.“', async () => {
    hubMock.mockRejectedValue(new ApiError(404, undefined, 'unbekanntes Werkzeug'));
    zeigen();
    fireEvent.click(knopf('matrix'));
    await waitFor(() => expect(document.querySelector('[data-matrix-gesperrt]')).toBeTruthy());
    expect(document.querySelector('[data-matrix-gesperrt]')!.textContent).toContain('Noch nicht eingerichtet.');
  });

  it('nennt Fehlendes ehrlich als geplant', () => {
    zeigen();
    expect(knopf('telegram').textContent).toContain('geplant');
    fireEvent.click(knopf('telegram'));
    expect(document.querySelector('[data-gespraech-mitte="telegram"]')!.textContent).toContain('Noch nicht gebaut');
    expect(EINTRAEGE.filter((e) => e.inhalt.art === 'geplant').map((e) => e.id)).toEqual(['telegram']);
  });

  it('im schmalen Fenster eine Zeile ohne Gruppen', () => {
    zeigen(true);
    expect(document.querySelector('[data-gespraech-gruppe]')).toBeNull();
    expect(document.querySelectorAll('[data-gespraech]').length).toBe(EINTRAEGE.length);
  });
});
