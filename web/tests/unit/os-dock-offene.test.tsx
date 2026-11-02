/**
 * Das neue Dock (components/os/Dock.tsx, Modus „offene“, 28.10.2026): zeigt nur geöffnete Anwendungen, blendet sich aus,
 * kommt über den unteren Rand, den Pfeil oder die Tastatur zurück. Ohne offene Anwendung steht nichts da.
 */
import { cleanup, fireEvent, render, screen, within } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Dock, { type DockProps } from '~/components/os/Dock';
import { DOCK_AUSBLENDEN_MS, DOCK_EINBLENDEN_MS, DOCK_PFEIL_MS, dockSicht } from '~/lib/os/dock-sichtbar';

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const FENSTER = [
  { id: 'seite:finance', titel: 'Finance', min: false },
  { id: 'seite:kalender', titel: 'Kalender', min: true },
  { id: 'app:leitstand__lagebild', titel: 'Lagebild', min: false },
];

function dock(extra: Partial<DockProps> = {}) {
  const sicht = dockSicht();
  const p: DockProps = {
    bildschirme: [{ index: 1, name: 'Arbeit' }],
    aktiv: 1,
    onWechseln: vi.fn(),
    onNeuerBildschirm: vi.fn(),
    startOffen: false,
    onStart: vi.fn(),
    fenster: FENSTER,
    fokus: 'seite:finance',
    onFenster: vi.fn(),
    agent: false,
    onAgent: vi.fn(),
    modus: 'offene',
    sicht,
    ...extra,
  };
  render(() => <Dock {...p} />);
  return { p, sicht };
}
const huelle = () => document.querySelector('[data-dock="offene"]') as HTMLElement;
const sichtbar = () => huelle().dataset.sichtbar === 'ja';
const zone = () => document.querySelector('[data-dock-zone]') as HTMLElement;

describe('Dock (offene): Inhalt', () => {
  it('zeigt nur die geöffneten Anwendungen — kein FYOS, kein Agent, keine Bildschirm-Punkte, kein „+“', () => {
    dock();
    const leiste = screen.getByRole('navigation', { name: 'Bodenleiste' });
    expect(within(leiste).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Finance', 'Kalender', 'Lagebild']);
    expect(within(leiste).queryByRole('button', { name: 'FYOS' })).toBeNull();
    expect(within(leiste).queryByRole('button', { name: 'Agent' })).toBeNull();
    expect(within(leiste).queryByRole('tab')).toBeNull();
    expect(within(leiste).queryByRole('button', { name: 'Neuer Bildschirm' })).toBeNull();
  });

  it('minimierte Anwendungen bleiben, gedimmt und als minimiert benannt; die im Fokus trägt das Licht', () => {
    dock();
    const k = screen.getByRole('button', { name: 'Kalender' });
    expect(k.classList.contains('os-dock-min')).toBe(true);
    expect(k.title).toContain('minimiert');
    expect(screen.getByRole('button', { name: 'Finance' }).classList.contains('os-dock-fokus')).toBe(true);
    expect(screen.getByRole('button', { name: 'Lagebild' }).classList.contains('os-dock-fokus')).toBe(false);
  });

  it('ein Klick meldet die Anwendung (die Shell holt sie nach vorn)', () => {
    const { p } = dock();
    fireEvent.click(screen.getByRole('button', { name: 'Lagebild' }));
    expect(p.onFenster).toHaveBeenCalledWith('app:leitstand__lagebild');
  });

  it('ohne offene Anwendung steht nichts da, auch kein Pfeil', () => {
    dock({ fenster: [], fokus: null });
    expect(document.querySelector('[data-dock]')).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Bodenleiste' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dock einblenden' })).toBeNull();
  });
});

describe('Dock (offene): ein- und ausblenden', () => {
  it('ist zunächst verborgen', () => {
    dock();
    expect(sichtbar()).toBe(false);
  });

  it('der Zeiger am unteren Rand blendet es nach kurzer Verzögerung ein, Weggehen blendet aus', () => {
    dock();
    fireEvent.pointerEnter(zone());
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS - 1);
    expect(sichtbar()).toBe(false);
    vi.advanceTimersByTime(1);
    expect(sichtbar()).toBe(true);
    fireEvent.pointerLeave(zone());
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(sichtbar()).toBe(false);
  });

  it('der Pfeil blendet es für 30 Sekunden ein; der Pfeil selbst verschwindet währenddessen', () => {
    dock();
    const pfeil = screen.getByRole('button', { name: 'Dock einblenden' });
    expect(pfeil.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(pfeil);
    expect(sichtbar()).toBe(true);
    expect(pfeil.classList.contains('os-dock-pfeil-weg')).toBe(true);
    vi.advanceTimersByTime(DOCK_PFEIL_MS - 1);
    expect(sichtbar()).toBe(true);
    vi.advanceTimersByTime(1);
    expect(sichtbar()).toBe(false);
    expect(pfeil.classList.contains('os-dock-pfeil-weg')).toBe(false);
  });

  it('Zeiger auf dem Dock hält den 30-s-Zähler an', () => {
    dock();
    fireEvent.click(screen.getByRole('button', { name: 'Dock einblenden' }));
    const glas = document.querySelector('.os-dock') as HTMLElement;
    fireEvent.pointerEnter(glas);
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 3);
    expect(sichtbar()).toBe(true);
    fireEvent.pointerLeave(glas);
    vi.advanceTimersByTime(DOCK_PFEIL_MS);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(sichtbar()).toBe(false);
  });

  it('Tastaturfokus in einem Symbol blendet es ein, Esc blendet es aus', () => {
    dock();
    const symbol = screen.getByRole('button', { name: 'Finance' });
    symbol.focus();
    fireEvent.focusIn(symbol);
    expect(sichtbar()).toBe(true);
    fireEvent.keyDown(symbol, { key: 'Escape' });
    expect(sichtbar()).toBe(false);
  });

  it('Pfeil per Tastatur (Enter) schiebt den Fokus ins Dock', () => {
    dock();
    const pfeil = screen.getByRole('button', { name: 'Dock einblenden' });
    fireEvent.click(pfeil, { detail: 0 });
    return Promise.resolve().then(() => {
      expect((document.activeElement as HTMLElement).getAttribute('aria-label')).toBe('Finance');
    });
  });

  it('das letzte Fenster geht zu: das Dock verschwindet samt Pfeil', async () => {
    const { sicht } = dock();
    sicht.pfeil();
    expect(sicht.sichtbar()).toBe(true);
    sicht.leer(true);
    expect(sicht.sichtbar()).toBe(false);
  });

  it('bewegt nichts im Layout: das Dock liegt in einer Hülle ohne eigene Höhe (Überlagerung, keine Verschiebung)', () => {
    dock();
    expect(huelle().classList.contains('os-dock-huelle')).toBe(true);
    expect(huelle().contains(screen.getByRole('navigation', { name: 'Bodenleiste' }))).toBe(true);
  });
});

describe('Dock (klassisch) bleibt für schmale Fenster', () => {
  it('zeigt FYOS, Punkte und Agent wie bisher und immer', () => {
    dock({ modus: 'klassisch' });
    const leiste = screen.getByRole('navigation', { name: 'Bodenleiste' });
    expect(within(leiste).getByRole('button', { name: 'FYOS' })).toBeTruthy();
    expect(within(leiste).getByRole('button', { name: 'Agent' })).toBeTruthy();
    expect(within(leiste).getAllByRole('tab').length).toBe(2);
    expect(document.querySelector('[data-dock]')).toBeNull();
  });
});
