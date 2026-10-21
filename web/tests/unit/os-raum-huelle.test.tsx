/**
 * Raum-Hüllen (components/raeume/Huelle.tsx, RaumVorhaben, RaumZuhause, RaumEinstellungen): jede Hub-App kommt nur,
 * wenn ein Plugin sie liefert; sonst steht „Noch nicht eingerichtet.“ da, ohne einen privaten Dienst fest zu verdrahten.
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
  default: (p: { name: string; ohneKopf?: boolean }) => {
    const name = p.name;
    return <div data-testid="app" data-name={name} data-ohne-kopf={String(!!p.ohneKopf)} />;
  },
}));
vi.mock('~/components/os/Fenster', () => ({ Inhalt: () => <div data-testid="seite" /> }));
vi.mock('~/components/einstellungen/Erscheinungsbild', () => ({ default: () => <div data-testid="erscheinungsbild" /> }));
vi.mock('~/components/einstellungen/RaeumeEinstellen', () => ({ default: () => <div data-testid="raeume-einstellen" /> }));

import { Geplant, HubApp, NICHT_EINGERICHTET, NichtEingerichtet } from '~/components/raeume/Huelle';
import RaumEinstellungen, { BEREICHE } from '~/components/raeume/RaumEinstellungen';
import RaumVorhaben from '~/components/raeume/RaumVorhaben';
import RaumZuhause from '~/components/raeume/RaumZuhause';

beforeEach(() => {
  localStorage.clear();
  hub.namen = [];
  hub.aus = false;
});
afterEach(() => cleanup());

const props = (schmal = false) => ({ oeffne: vi.fn(), schmal, heim: vi.fn() });

describe('Bausteine', () => {
  it('NichtEingerichtet sagt den einen Satz und nennt auf Wunsch, was fehlt', () => {
    render(() => <NichtEingerichtet detail="Das Plugin fehlt." data-probe="x" />);
    const el = document.querySelector('[data-nicht-eingerichtet]')!;
    expect(el.textContent).toContain(NICHT_EINGERICHTET);
    expect(el.textContent).toContain('Das Plugin fehlt.');
    expect(el.getAttribute('data-probe')).toBe('x');
    expect(NICHT_EINGERICHTET).toBe('Noch nicht eingerichtet.');
  });

  it('Geplant nennt die Quelle', () => {
    render(() => <Geplant titel="Beispiel" quelle="die Sicherungen" />);
    expect(screen.getByRole('heading', { name: 'Beispiel' })).toBeTruthy();
    expect(document.body.textContent).toContain('Noch nicht gebaut. Hier kommt zusammen: die Sicherungen.');
  });

  it('HubApp bettet die App ein, wenn der Hub sie kennt', async () => {
    hub.namen = ['erstes__zeigen'];
    render(() => <HubApp name="erstes__zeigen" titel="Erstes" schluessel="t" ohneKopf />);
    const app = await screen.findByTestId('app');
    expect(app.dataset.name).toBe('erstes__zeigen');
    expect(app.dataset.ohneKopf).toBe('true');
  });

  it('HubApp nimmt den zweiten Namen, wenn der erste fehlt', async () => {
    hub.namen = ['zweites__zeigen'];
    render(() => <HubApp name="erstes__zeigen" oder="zweites__zeigen" titel="Erstes" schluessel="t" />);
    expect((await screen.findByTestId('app')).dataset.name).toBe('zweites__zeigen');
  });

  it('HubApp sagt „Noch nicht eingerichtet.“ und nennt das fehlende Werkzeug', async () => {
    render(() => <HubApp name="erstes__zeigen" titel="Erstes" schluessel="t" />);
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(document.querySelector('[data-nicht-eingerichtet]')!.textContent).toContain('erstes__zeigen');
    expect(screen.queryByTestId('app')).toBeNull();
  });

  it('HubApp sagt es auch, wenn der Hub nicht antwortet', async () => {
    hub.aus = true;
    render(() => <HubApp name="erstes__zeigen" titel="Erstes" schluessel="t" />);
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
    expect(document.querySelector('[data-nicht-eingerichtet]')!.textContent).toContain('Hub antwortet gerade nicht');
  });
});

describe('Raum Vorhaben', () => {
  it('zeigt das Brett des Plugins', async () => {
    hub.namen = ['vorhaben__brett'];
    render(() => <RaumVorhaben {...props()} />);
    expect((await screen.findByTestId('app')).dataset.name).toBe('vorhaben__brett');
  });

  it('fällt auf die Vorgänge zurück, wenn kein Brett da ist', async () => {
    hub.namen = ['vorgaenge__zeigen'];
    render(() => <RaumVorhaben {...props()} />);
    expect((await screen.findByTestId('app')).dataset.name).toBe('vorgaenge__zeigen');
  });

  it('ohne beides: „Noch nicht eingerichtet.“', async () => {
    render(() => <RaumVorhaben {...props()} />);
    await waitFor(() => expect(document.querySelector('[data-raum-vorhaben] [data-nicht-eingerichtet]')).toBeTruthy());
  });
});

describe('Raum Zuhause', () => {
  it('zeigt die Geräte-App des Haus-Plugins', async () => {
    hub.namen = ['haus__geraete'];
    render(() => <RaumZuhause {...props()} />);
    expect((await screen.findByTestId('app')).dataset.name).toBe('haus__geraete');
  });

  it('ohne Haus-Plugin: „Noch nicht eingerichtet.“', async () => {
    render(() => <RaumZuhause {...props()} />);
    await waitFor(() => expect(document.querySelector('[data-raum-zuhause] [data-nicht-eingerichtet]')).toBeTruthy());
  });
});

describe('Raum Einstellungen', () => {
  const bereich = (id: string) => document.querySelector(`[data-bereich="${id}"]`) as HTMLButtonElement;

  it('beginnt beim Erscheinungsbild und nimmt die Räume-Einstellung auf', () => {
    render(() => <RaumEinstellungen {...props()} />);
    expect(screen.getByTestId('erscheinungsbild')).toBeTruthy();
    fireEvent.click(bereich('raeume'));
    expect(screen.getByTestId('raeume-einstellen')).toBeTruthy();
    expect(localStorage.getItem('fyos.raum.einstellungen.bereich')).toBe('raeume');
  });

  it('Apps kommen aus dem Hub, ein Wechsel hängt die neue App ein', async () => {
    hub.namen = ['mcp__uebersicht', 'modelle__zustand'];
    render(() => <RaumEinstellungen {...props()} />);
    fireEvent.click(bereich('plugins'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('mcp__uebersicht'));
    fireEvent.click(bereich('modelle'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('modelle__zustand'));
    expect(screen.getAllByTestId('app').length).toBe(1);
  });

  it('eine App, die kein Plugin liefert, sagt „Noch nicht eingerichtet.“', async () => {
    render(() => <RaumEinstellungen {...props()} />);
    fireEvent.click(bereich('konten'));
    await waitFor(() => expect(document.querySelector('[data-nicht-eingerichtet]')).toBeTruthy());
  });

  it('Bereiche ohne Grundlage stehen ehrlich als geplant da', () => {
    render(() => <RaumEinstellungen {...props()} />);
    const geplant = BEREICHE.filter((b) => b.inhalt.art === 'geplant').map((b) => b.id);
    expect(geplant).toEqual(['agenten', 'kanaele', 'zuhause', 'stimme', 'sicherungen']);
    fireEvent.click(bereich('sicherungen'));
    expect(document.body.textContent).toContain('Noch nicht gebaut');
  });

  it('die Suche filtert die Bereiche', () => {
    render(() => <RaumEinstellungen {...props()} />);
    fireEvent.input(screen.getByRole('searchbox', { name: 'In allen Einstellungen suchen' }), { target: { value: 'backup' } });
    expect(document.querySelectorAll('[data-bereich]').length).toBe(1);
    expect(bereich('sicherungen')).toBeTruthy();
    fireEvent.input(screen.getByRole('searchbox', { name: 'In allen Einstellungen suchen' }), { target: { value: 'gibtesnicht' } });
    expect(document.body.textContent).toContain('Kein Bereich passt.');
  });
});
