/**
 * Raum Sammlung (components/raeume/RaumSammlung.tsx): Stücke aus Ansichten und Geschichten mischen, filtern, Typen
 * rechts, ehrliche „geplant“-Bereiche, und eine ausgefallene Quelle nimmt der anderen nichts weg.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '~/lib/api/client';

vi.mock('~/lib/mcp-apps/host', () => ({ apps: async () => [] }));
vi.mock('~/components/apps/AppEingebettet', () => ({ default: () => <div data-testid="app" /> }));
vi.mock('~/components/os/Fenster', () => ({ Inhalt: () => <div data-testid="seite" /> }));
const hubMock = vi.fn();
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hubMock(...a) }));
const oeffnenMock = vi.fn(() => true);
vi.mock('~/lib/os/oeffnen', () => ({ imOsOeffnen: (...a: unknown[]) => oeffnenMock(...(a as [])) }));

import RaumSammlung, { TYPEN, filtere, stueckeAus } from '~/components/raeume/RaumSammlung';

const ANSICHTEN = {
  ansichten: [
    { id: 'g-aaaaaaaaaaaa', titel: 'Umsatz Oktober', beschreibung: 'Balken je Tag', angelegt: '2026-10-19T10:00:00Z' },
    { id: 'g-bbbbbbbbbbbb', titel: 'Durchsatz Test', beschreibung: '', angelegt: '2026-10-12T08:00:00Z' },
  ],
};
const GESCHICHTEN = { anzahl: 1, geschichten: [{ id: 's1', titel: 'Die Brücke', geaendert: '2026-10-20T07:00:00Z', woerter: 1200, kapitel: 3, status: 'entwurf' }] };

beforeEach(() => {
  localStorage.clear();
  hubMock.mockReset();
  oeffnenMock.mockClear();
});
afterEach(() => cleanup());

describe('Stücke', () => {
  it('mischt Ansichten und Geschichten, neueste zuerst', () => {
    const s = stueckeAus(ANSICHTEN, GESCHICHTEN);
    expect(s.map((x) => x.id)).toEqual(['s1', 'g-aaaaaaaaaaaa', 'g-bbbbbbbbbbbb']);
    expect(s[0]).toMatchObject({ typ: 'geschichte', titel: 'Die Brücke' });
    expect(s[0]!.text).toContain('3 Kapitel');
    expect(stueckeAus(undefined, undefined)).toEqual([]);
  });

  it('filtert nach Typ und nach allen Suchwörtern', () => {
    const s = stueckeAus(ANSICHTEN, GESCHICHTEN);
    expect(filtere(s, 'ansicht', '').length).toBe(2);
    expect(filtere(s, null, 'umsatz tag').map((x) => x.id)).toEqual(['g-aaaaaaaaaaaa']);
    expect(filtere(s, 'geschichte', 'umsatz')).toEqual([]);
  });

  it('nennt die geplanten Typen ehrlich mit ihrer Quelle', () => {
    const geplant = TYPEN.filter((t) => t.inhalt.art === 'geplant').map((t) => t.id);
    expect(geplant).toEqual(['berichte', 'bilder', 'mappen']);
  });
});

describe('Raum', () => {
  const heim = vi.fn();
  const oeffne = vi.fn();
  const zeigen = () => render(() => <RaumSammlung oeffne={oeffne} schmal={false} heim={heim} />);

  it('zeigt die Stücke, zählt je Typ und öffnet eine Ansicht im Fenster', async () => {
    hubMock.mockImplementation((tool: string) => Promise.resolve(tool === 'gui.zeigen' ? ANSICHTEN : GESCHICHTEN));
    zeigen();
    await waitFor(() => expect(screen.getByText('Umsatz Oktober')).toBeTruthy());
    expect(screen.getByText('Die Brücke')).toBeTruthy();
    const ansichten = document.querySelector('[data-typ="ansichten"]')!;
    expect(ansichten.textContent).toContain('2');
    fireEvent.click(document.querySelector('[data-stueck="ansicht:g-aaaaaaaaaaaa"]')!);
    expect(oeffnenMock).toHaveBeenCalledWith({ ziel: 'app:gui__zeigen', eingabe: { id: 'g-aaaaaaaaaaaa' }, vorn: true });
    fireEvent.click(document.querySelector('[data-stueck="geschichte:s1"]')!);
    expect(oeffnenMock).toHaveBeenLastCalledWith({ ziel: 'app:geschichten__liste', eingabe: { id: 's1' }, vorn: true });
    // Kennt der Browser keinen Weg ins Fenster, öffnet die Shell über oeffne
    oeffnenMock.mockReturnValueOnce(false);
    fireEvent.click(document.querySelector('[data-stueck="geschichte:s1"]')!);
    expect(oeffne).toHaveBeenCalledWith('app:geschichten__liste');
  });

  it('eine ausgefallene Quelle nimmt der anderen nichts weg', async () => {
    hubMock.mockImplementation((tool: string) => (tool === 'gui.zeigen' ? Promise.reject(new Error('weg')) : Promise.resolve(GESCHICHTEN)));
    zeigen();
    await waitFor(() => expect(screen.getByText('Die Brücke')).toBeTruthy());
    expect(screen.getByRole('status').textContent).toContain('Ansichten');
  });

  it('eine Quelle ohne Plugin (404) ist nur nicht eingerichtet, nicht ausgefallen', async () => {
    hubMock.mockImplementation((tool: string) => (tool === 'gui.zeigen' ? Promise.resolve(ANSICHTEN) : Promise.reject(new ApiError(404, undefined, 'unbekannt'))));
    zeigen();
    await waitFor(() => expect(screen.getByText('Umsatz Oktober')).toBeTruthy());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('ohne jede Quelle sagt die Sammlung „Noch nicht eingerichtet.“', async () => {
    hubMock.mockRejectedValue(new ApiError(404, undefined, 'unbekannt'));
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(document.querySelector('[data-nicht-eingerichtet]')!.textContent).toBe('Noch nicht eingerichtet.');
  });

  it('die Suche filtert, und ein geplanter Typ sagt, woher er kommen wird', async () => {
    hubMock.mockImplementation((tool: string) => Promise.resolve(tool === 'gui.zeigen' ? ANSICHTEN : GESCHICHTEN));
    zeigen();
    await waitFor(() => expect(screen.getByText('Die Brücke')).toBeTruthy());
    fireEvent.input(screen.getByRole('searchbox', { name: 'In der Sammlung suchen' }), { target: { value: 'durchsatz' } });
    expect(screen.queryByText('Die Brücke')).toBeNull();
    expect(screen.getByText('Durchsatz Test')).toBeTruthy();
    fireEvent.click(document.querySelector('[data-typ="mappen"]')!);
    expect(document.querySelector('[data-sammlung-typ="mappen"]')!.textContent).toContain('registriere_ding');
  });
});
