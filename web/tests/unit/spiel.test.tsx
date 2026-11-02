/**
 * Spiel im Browser (OS-Neubau P9): melden setzt den Stand und feiert nur neue Punkte, ein Fehler im Spiel bricht nichts,
 * „heute“ zählt nach Ortszeit, die Feier zeigt Punkte und einen Levelaufstieg.
 */
import { cleanup, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const hubMock = vi.hoisted(() => vi.fn());
vi.mock('~/lib/hub', () => ({ hub: hubMock }));

import SpielFeier from '~/components/spiel/SpielFeier';
import { SPIEL_EREIGNIS, istHeute, spielMelden, spielStand, spielZuruecksetzen } from '~/lib/spiel';

const STAND = { level: 2, name: 'Mitbewohnerin', punkte: 120, anteil: 0.1, freigeschaltet: ['halsband'], an: true };

beforeEach(() => {
  hubMock.mockReset();
  spielZuruecksetzen();
});
afterEach(() => cleanup());

describe('spielMelden', () => {
  it('setzt den Stand und feiert neue Punkte', async () => {
    hubMock.mockResolvedValue({ neu: true, punkte: 25, satz: '+25 · Vorgang abgeschlossen', level_auf: false, abzeichen_neu: [], stand: STAND });
    const gehoert = vi.fn();
    window.addEventListener(SPIEL_EREIGNIS, gehoert);
    await spielMelden('vorgang_fertig', 'PRB-1');
    expect(hubMock).toHaveBeenCalledWith('spiel.ereignis', { art: 'vorgang_fertig', schluessel: 'PRB-1' }, { art: 'bewusst' });
    expect(spielStand()?.level).toBe(2);
    expect(gehoert).toHaveBeenCalledTimes(1);
    window.removeEventListener(SPIEL_EREIGNIS, gehoert);
  });

  it('feiert nicht, wenn schon gezählt oder das Spiel aus ist; Fehler bleiben still', async () => {
    const gehoert = vi.fn();
    window.addEventListener(SPIEL_EREIGNIS, gehoert);
    hubMock.mockResolvedValueOnce({ neu: false, punkte: 0, stand: STAND });
    await spielMelden('vorgang_fertig', 'PRB-1');
    hubMock.mockResolvedValueOnce({ neu: true, punkte: 10, stand: { ...STAND, an: false } });
    await spielMelden('freigabe_heute', 'w:1');
    hubMock.mockRejectedValueOnce(new Error('Unbekanntes Werkzeug spiel.ereignis'));
    await expect(spielMelden('boss', 'w44')).resolves.toBeUndefined();
    expect(gehoert).not.toHaveBeenCalled();
    window.removeEventListener(SPIEL_EREIGNIS, gehoert);
  });
});

describe('istHeute', () => {
  it('vergleicht nach Ortszeit', () => {
    const jetzt = new Date(2026, 10, 1, 21, 0);
    expect(istHeute(new Date(2026, 10, 1, 8, 0).toISOString(), jetzt)).toBe(true);
    expect(istHeute(new Date(2026, 9, 31, 23, 0).toISOString(), jetzt)).toBe(false);
    expect(istHeute(null, jetzt)).toBe(false);
  });
});

describe('SpielFeier', () => {
  it('zeigt Punkte und einen Levelaufstieg mit Freischaltung', async () => {
    render(() => <SpielFeier />);
    window.dispatchEvent(new CustomEvent(SPIEL_EREIGNIS, { detail: { punkte: 10, satz: '+10 · Freigabe am selben Tag beantwortet', levelAuf: false, freigeschaltet: null, abzeichen: [], stand: STAND } }));
    await waitFor(() => expect(screen.getByText('+10')).toBeTruthy());
    window.dispatchEvent(new CustomEvent(SPIEL_EREIGNIS, { detail: { punkte: 150, satz: '+150 · Boss der Woche besiegt', levelAuf: true, freigeschaltet: 'brille', abzeichen: [{ id: 'boss', text: 'Einen Boss der Woche besiegt' }], stand: { ...STAND, level: 3, name: 'Hausgeist', freigeschaltet: ['halsband', 'brille'] } } }));
    await waitFor(() => expect(screen.getByText('Level 3 · Hausgeist')).toBeTruthy());
    expect(screen.getByText(/Agent hat jetzt eine Brille/)).toBeTruthy();
    expect(document.querySelector('.pk-brille')).toBeTruthy();
  });
});
