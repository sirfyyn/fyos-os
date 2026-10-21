/**
 * Raum Betrieb (components/raeume/RaumBetrieb.tsx): Leiste nach Bereich, alles als Hub-App, die ein eingerichtetes
 * Plugin liefert; fehlt sie im Hub, steht „Noch nicht eingerichtet.“ da.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const hub = vi.hoisted(() => ({ namen: [] as string[], aus: false }));
vi.mock('~/lib/mcp-apps/host', () => ({
  apps: async () => {
    if (hub.aus) throw new Error('weg');
    return hub.namen.map((name) => ({ name }));
  },
}));
vi.mock('~/components/apps/AppEingebettet', () => ({
  default: (p: { name: string }) => {
    const name = p.name;
    return <div data-testid="app" data-name={name} />;
  },
}));
vi.mock('~/components/os/Fenster', () => ({ Inhalt: () => <div data-testid="seite" /> }));

import RaumBetrieb, { EINTRAEGE } from '~/components/raeume/RaumBetrieb';

const ALLE = ['leitstand__lagebild', 'cluster__knoten', 'repos__uebersicht', 'vorgaenge__zeigen', 'modelle__zustand', 'werkstatt__suchen', 'mcp__uebersicht', 'desktop__zeigen'];

beforeEach(() => {
  localStorage.clear();
  hub.namen = ALLE;
  hub.aus = false;
});
afterEach(() => cleanup());

const zeigen = (schmal = false) => render(() => <RaumBetrieb oeffne={vi.fn()} schmal={schmal} heim={vi.fn()} />);
const knopf = (id: string) => document.querySelector(`[data-betrieb="${id}"]`) as HTMLButtonElement;

describe('Raum Betrieb', () => {
  it('gliedert nach Bereich und beginnt mit dem Lagebild', async () => {
    zeigen();
    expect([...document.querySelectorAll('[data-betrieb-gruppe]')].map((g) => g.getAttribute('data-betrieb-gruppe'))).toEqual([
      'Lage',
      'Cluster',
      'Agenten und Modelle',
      'Werkzeuge',
      'Rechner',
    ]);
    expect((await screen.findByTestId('app')).dataset.name).toBe('leitstand__lagebild');
  });

  it('wechselt zwischen Apps, ohne die vorige stehen zu lassen', async () => {
    zeigen();
    fireEvent.click(knopf('steuerpult'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('cluster__knoten'));
    fireEvent.click(knopf('plugins'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('mcp__uebersicht'));
    fireEvent.click(knopf('werkstatt'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('werkstatt__suchen'));
    expect(screen.getAllByTestId('app').length).toBe(1);
  });

  it('jede App fehlt im Hub: „Noch nicht eingerichtet.“, und die Leiste bleibt benutzbar', async () => {
    hub.namen = [];
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(screen.queryByTestId('app')).toBeNull();
    for (const e of EINTRAEGE) {
      fireEvent.click(knopf(e.id));
      await waitFor(() => expect(document.querySelector(`[data-betrieb-mitte="${e.id}"] [data-nicht-eingerichtet]`)).toBeTruthy());
    }
  });

  it('antwortet der Hub nicht, steht derselbe Satz da', async () => {
    hub.aus = true;
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(document.querySelector('[data-nicht-eingerichtet]')!.textContent).toContain('Noch nicht eingerichtet.');
  });

  it('nichts ist bloß geplant, und die Wahl wird gemerkt', async () => {
    zeigen();
    fireEvent.click(knopf('desktop'));
    expect(localStorage.getItem('fyos.raum.betrieb')).toBe('desktop');
    expect(EINTRAEGE.filter((e) => e.inhalt.art === 'geplant')).toEqual([]);
    cleanup();
    zeigen();
    expect((await screen.findByTestId('app')).dataset.name).toBe('desktop__zeigen');
  });

  it('im schmalen Fenster steht die Leiste als eine Reihe oben', () => {
    zeigen(true);
    expect(document.querySelector('[data-betrieb-gruppe]')).toBeNull();
    expect(document.querySelectorAll('[data-betrieb]').length).toBe(EINTRAEGE.length);
  });
});
