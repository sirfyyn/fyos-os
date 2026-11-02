/** Lage-Ampel in der Menüleiste: Farbe aus lage.ampel, Grund im Tooltip, Klick öffnet das Lagebild. */
import { cleanup, fireEvent, render, waitFor } from '@solidjs/testing-library';
import { afterEach, describe, expect, it, vi } from 'vitest';

const hubMock = vi.hoisted(() => vi.fn());
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hubMock(...a) }));

import AmpelPunkt, { ampelSatz } from '~/components/os/AmpelPunkt';

afterEach(() => {
  cleanup();
  hubMock.mockReset();
});

describe('AmpelPunkt', () => {
  it('Satz aus Zustand und Gründen', () => {
    expect(ampelSatz({ zustand: 'blau', warum: ['9 Fehler in der letzten Stunde'] })).toBe('Online, mit kleinen Problemen: 9 Fehler in der letzten Stunde');
    expect(ampelSatz({ zustand: 'gruen' })).toBe('Alles in Ordnung');
    expect(ampelSatz(undefined)).toBe('');
  });

  it('zeigt die Farbe und öffnet das Lagebild', async () => {
    hubMock.mockResolvedValue({ zustand: 'rot', warum: ['CI rot'] });
    const oeffne = vi.fn();
    const v = render(() => (
      <AmpelPunkt oeffne={oeffne} />
    ));
    await waitFor(() => expect(v.container.querySelector('[data-ampel="rot"]')).toBeTruthy());
    const knopf = v.container.querySelector('[data-ampel]') as HTMLButtonElement;
    expect(knopf.title).toBe('Störung: CI rot');
    fireEvent.click(knopf);
    expect(oeffne).toHaveBeenCalledWith('app:leitstand__lagebild');
  });

  it('ohne Antwort kein Punkt', async () => {
    hubMock.mockRejectedValue(new Error('aus'));
    const v = render(() => (
      <AmpelPunkt oeffne={vi.fn()} />
    ));
    await new Promise((r) => setTimeout(r, 20));
    expect(v.container.querySelector('[data-ampel]')).toBeNull();
  });
});
