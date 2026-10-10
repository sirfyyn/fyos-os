/**
 * Dock — Bildschirm-Punkte als Reiter: nur der aktive Punkt ist im Tab-Weg, Pfeiltasten, Pos1 und Ende
 * wechseln den Bildschirm (Bestandsaufnahme: role="tablist" ohne Tastaturbedienung).
 */
import { fireEvent, render, screen } from '@solidjs/testing-library';
import { describe, expect, it, vi } from 'vitest';
import Dock, { type DockProps } from '~/components/os/Dock';

function dock(aktiv: number, onWechseln = vi.fn()) {
  const p: DockProps = {
    bildschirme: [{ index: 1, name: 'Arbeit' }, { index: 2, name: 'Haus' }],
    aktiv,
    onWechseln,
    onNeuerBildschirm: vi.fn(),
    startOffen: false,
    onStart: vi.fn(),
    fenster: [],
    fokus: null,
    onFenster: vi.fn(),
    agent: false,
    onAgent: vi.fn(),
  };
  render(() => <Dock {...p} />);
  return onWechseln;
}

describe('Dock: Bildschirm-Punkte', () => {
  it('nur der aktive Punkt ist im Tab-Weg', () => {
    dock(1);
    const reiter = screen.getAllByRole('tab');
    expect(reiter.map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
  });

  it('Pfeiltasten, Pos1 und Ende wechseln den Bildschirm, am Rand bleibt er stehen', () => {
    const wechseln = dock(1);
    const liste = screen.getByRole('tablist', { name: 'Bildschirme' });
    fireEvent.keyDown(liste, { key: 'ArrowRight' });
    fireEvent.keyDown(liste, { key: 'ArrowLeft' });
    fireEvent.keyDown(liste, { key: 'End' });
    fireEvent.keyDown(liste, { key: 'Home' });
    fireEvent.keyDown(liste, { key: 'a' });
    expect(wechseln.mock.calls.map((c) => c[0])).toEqual([2, 0, 2, 0]);
  });

  it('am Ende ändert ArrowRight nichts', () => {
    const wechseln = dock(2);
    fireEvent.keyDown(screen.getByRole('tablist', { name: 'Bildschirme' }), { key: 'ArrowRight' });
    expect(wechseln).not.toHaveBeenCalled();
  });
});
