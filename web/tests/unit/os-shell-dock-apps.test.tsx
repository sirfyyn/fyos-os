/**
 * Shell mit Räumen: Apps-Knopf in der Räume-Leiste öffnet die Apps-Seite (/os/apps/) statt eines Raums,
 * der Agent-Knopf steht links, das Dock zeigt nur geöffnete Anwendungen und blendet sich aus. Alte Speicherstände
 * (Reihenfolge der Räume, Pins) gelten weiter.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const hub = vi.hoisted(() => vi.fn());
const hubApps = vi.hoisted(() => vi.fn());
vi.mock('~/lib/hub', () => ({ hub }));
vi.mock('~/components/os/nativ/Agent', () => ({ default: () => <div class="agent-pi" /> }));
vi.mock('~/lib/mcp-apps/host', () => ({
  apps: hubApps,
  uebergabeStarten: vi.fn(async () => {}),
  alleSuchen: vi.fn(async () => ({ abfrage: '', treffer: [], quellen: [] })),
  dingLesen: vi.fn(async () => ({})),
  appCall: vi.fn(async () => ({ content: [{ type: 'text', text: '{}' }] })),
  appEinhaengen: vi.fn(async () => () => {}),
  aktuellesTheme: () => 'dark',
}));

import Shell from '~/components/os/Shell';
import { raeume, raeumeSetzen, raeumeZuruecksetzen } from '~/lib/os/raeume';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
  raeumeZuruecksetzen();
  // Die Distribution bringt keine eigenen Seiten mit: eine Seite kommt wie von einem Plugin
  registriereFlaechen({ flaechen: [{ id: 'seite:finance', titel: 'Finance', gruppe: 'Arbeit', art: 'seite', kuerzel: 'Fi', pfad: '/finance/' }] });
  history.replaceState(null, '', '/os/');
  hub.mockReset();
  hub.mockResolvedValue({ ampel: 'dev', lage_satz: 'Alles ruhig.', kacheln: [] });
  hubApps.mockReset();
  hubApps.mockResolvedValue([
    { name: 'leitstand__lagebild', tool: 'leitstand.lagebild', title: 'Lagebild', description: '', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://x' } }, scope: 'READ' },
  ]);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  registerZuruecksetzen();
  raeumeZuruecksetzen();
  history.replaceState(null, '', '/');
});

const leiste = () => screen.getByRole('navigation', { name: 'Räume' });
const appsKnopf = () => within(leiste()).getByRole('button', { name: 'Apps' });
const bodenleiste = () => screen.queryByRole('navigation', { name: 'Bodenleiste' });
const appsSeite = () => screen.queryByRole('region', { name: 'Apps' });
/** Finance über die Apps-Seite öffnen */
async function financeOeffnen() {
  fireEvent.click(appsKnopf());
  fireEvent.click(await screen.findByRole('button', { name: /Finance/ }, { timeout: 3000 }));
  await screen.findByRole('region', { name: 'Finance' });
}

describe('Räume-Leiste: Apps und Agent', () => {
  it('trägt einen Apps-Knopf (kein Raum) und den Agent-Knopf, beide unterhalb der Räume', () => {
    render(() => <Shell />);
    const knoepfe = within(leiste()).getAllByRole('button');
    const namen = knoepfe.map((b) => b.getAttribute('aria-label') ?? '');
    const iApps = namen.indexOf('Apps');
    const iAgent = namen.findIndex((n) => n.startsWith('Agent fragen'));
    const iLetzterRaum = Math.max(...['Zentrale', 'Gespräch', 'Zuhause', 'Betrieb'].map((n) => namen.indexOf(n)));
    expect(iApps).toBeGreaterThan(iLetzterRaum);
    expect(iAgent).toBeGreaterThan(iApps);
    expect(appsKnopf().hasAttribute('data-raum')).toBe(false); // kein Raum
  });

  it('der Agent-Knopf in der Leiste öffnet und schließt den Agenten wie früher der im Dock', async () => {
    render(() => <Shell />);
    expect(document.querySelector('.agent-pi')).toBeNull();
    const agent = within(leiste()).getByRole('button', { name: /Agent fragen/ });
    expect(agent.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(agent);
    await waitFor(() => expect(document.querySelector('.agent-pi')).not.toBeNull());
    expect(agent.getAttribute('aria-pressed')).toBe('true');
    expect(document.querySelector('aside[aria-label="Agent"]')!.classList.contains('hidden')).toBe(false);
    fireEvent.click(agent);
    expect(document.querySelector('aside[aria-label="Agent"]')!.classList.contains('hidden')).toBe(true);
  });
});

describe('Apps-Seite', () => {
  it('der Knopf öffnet eine eigene Seite unter /os/apps/, mit Suche, Zurück und markiertem Knopf', async () => {
    render(() => <Shell />);
    expect(appsSeite()).toBeNull();
    expect(appsKnopf().getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(appsKnopf());
    // die Seite wird nachgeladen; auf dem vollen CI-Läufer reicht 1 s nicht (01.11.2026)
    const seite = await screen.findByRole('region', { name: 'Apps' }, { timeout: 8000 });
    expect(location.pathname).toBe('/os/apps/');
    expect(appsKnopf().getAttribute('aria-pressed')).toBe('true');
    expect(within(seite).getByRole('searchbox', { name: 'Alles durchsuchen' })).toBeTruthy();
    expect(within(seite).getByRole('button', { name: 'Zurück' })).toBeTruthy();
    expect(seite.closest('[data-os-bereich]')).toBeTruthy(); // im Bereich, die Räume-Leiste bleibt sichtbar
    expect(screen.queryByRole('dialog', { name: 'FYOS' })).toBeNull(); // kein Panel mehr
  });

  it('der Raum bleibt im Hintergrund erhalten; Zurück, Esc und der Knopf führen dorthin', async () => {
    raeumeSetzen({ ...raeume(), aktiv: 'einstellungen' });
    render(() => <Shell />);
    await waitFor(() => expect(document.querySelector('section[data-raum="einstellungen"]')).toBeTruthy());
    const raumKnopf = within(leiste()).getByRole('button', { name: 'Einstellungen' });
    expect(raumKnopf.getAttribute('aria-current')).toBe('page');

    fireEvent.click(appsKnopf());
    await screen.findByRole('region', { name: 'Apps' });
    expect(raeume().aktiv).toBe('einstellungen'); // Zustand unberührt
    expect(document.querySelector('section[data-raum="einstellungen"]')).toBeTruthy(); // noch gemountet
    expect(raumKnopf.getAttribute('aria-current')).toBeNull(); // die Markierung wandert zu Apps
    expect(document.querySelector('[data-os-bereich]')!.classList.contains('os-apps-offen')).toBe(true);

    fireEvent.click(within(appsSeite()!).getByRole('button', { name: 'Zurück' }));
    await waitFor(() => expect(appsSeite()).toBeNull());
    expect(raumKnopf.getAttribute('aria-current')).toBe('page');

    fireEvent.click(appsKnopf());
    await screen.findByRole('region', { name: 'Apps' });
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(appsSeite()).toBeNull());

    fireEvent.click(appsKnopf());
    await screen.findByRole('region', { name: 'Apps' });
    fireEvent.click(appsKnopf());
    await waitFor(() => expect(appsSeite()).toBeNull());
    expect(raeume().aktiv).toBe('einstellungen');
  });

  it('ein Raum-Knopf holt den Raum nach vorn und schließt die Seite', async () => {
    render(() => <Shell />);
    fireEvent.click(appsKnopf());
    await screen.findByRole('region', { name: 'Apps' });
    fireEvent.click(within(leiste()).getByRole('button', { name: 'Einstellungen' }));
    await waitFor(() => expect(appsSeite()).toBeNull());
    expect(raeume().aktiv).toBe('einstellungen');
  });

  it('die Adresse hat einen Verlauf: Zurück des Browsers schließt, Vor öffnet wieder', async () => {
    render(() => <Shell />);
    fireEvent.click(appsKnopf());
    await screen.findByRole('region', { name: 'Apps' });
    history.back();
    await waitFor(() => expect(appsSeite()).toBeNull());
    expect(location.pathname).toBe('/os/');
    history.forward();
    await screen.findByRole('region', { name: 'Apps' });
    expect(location.pathname).toBe('/os/apps/');
  });

  it('der Link /os/apps/ öffnet die Seite gleich; Schließen führt auf /os/ (Abfrage bleibt)', async () => {
    history.replaceState(null, '', '/os/apps/?raeume=1');
    render(() => <Shell />);
    await screen.findByRole('region', { name: 'Apps' });
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(appsSeite()).toBeNull());
    expect(location.pathname).toBe('/os/');
    expect(location.search).toBe('?raeume=1');
  });

  it('⌘K / Strg+K öffnet sie wie bisher, ein zweites Mal schließt sie', async () => {
    render(() => <Shell />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await screen.findByRole('region', { name: 'Apps' });
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await waitFor(() => expect(appsSeite()).toBeNull());
  });

  it('eine Fläche öffnen schließt die Seite und führt zu ihr', async () => {
    render(() => <Shell />);
    await financeOeffnen();
    expect(appsSeite()).toBeNull();
    await waitFor(() => expect(location.pathname).toBe('/os/'));
  });

  it('Favoriten: angeheftete Apps (Schlüssel fyos:app-pins) stehen oben', async () => {
    localStorage.setItem('fyos:app-pins', JSON.stringify(['leitstand__lagebild']));
    render(() => <Shell />);
    fireEvent.click(appsKnopf());
    const fav = await screen.findByRole('region', { name: 'Favoriten' });
    expect(within(fav).getByRole('button', { name: /Lagebild/ })).toBeTruthy();
    expect(within(fav).queryByRole('button', { name: /Finance/ })).toBeNull();
  });
});

describe('Dock im neuen Modus', () => {
  it('ist ohne offene Anwendung gar nicht da', () => {
    render(() => <Shell />);
    expect(bodenleiste()).toBeNull();
    expect(screen.queryByRole('button', { name: 'Dock einblenden' })).toBeNull();
  });

  it('zeigt nach dem Öffnen nur die geöffnete Anwendung, ohne FYOS, Agent, Punkte und „+“', async () => {
    render(() => <Shell />);
    await financeOeffnen();
    const dock = bodenleiste()!;
    expect(within(dock).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(['Finance']);
    expect(within(dock).queryByRole('tab')).toBeNull();
    expect(within(dock).queryByRole('button', { name: 'FYOS' })).toBeNull();
    expect(within(dock).queryByRole('button', { name: 'Agent' })).toBeNull();
    // er überlagert den Inhalt, statt ihn zu verschieben: die Hülle ist absolut positioniert in der Shell
    expect(document.querySelector('[data-dock="offene"]')!.parentElement!.hasAttribute('data-shell')).toBe(true);
    expect(document.querySelector('[data-dock="offene"]')!.getAttribute('data-sichtbar')).toBe('nein');
  });

  it('zeigt auch Anwendungen anderer Bildschirme; ein Klick führt zu ihnen', async () => {
    render(() => <Shell />);
    await financeOeffnen();
    fireEvent.click(within(leiste()).getByRole('button', { name: 'Zentrale' })); // zurück zum Start
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Finance' })).toBeNull());
    const symbol = within(bodenleiste()!).getByRole('button', { name: 'Finance' });
    fireEvent.click(symbol);
    expect(await screen.findByRole('region', { name: 'Finance' })).toBeTruthy();
  });

  it('der Pfeil blendet es ein (30 s), Esc wieder aus', async () => {
    render(() => <Shell />);
    await financeOeffnen();
    const huelle = () => document.querySelector('[data-dock="offene"]')!;
    fireEvent.click(screen.getByRole('button', { name: 'Dock einblenden' }));
    expect(huelle().getAttribute('data-sichtbar')).toBe('ja');
    fireEvent.keyDown(within(bodenleiste()!).getByRole('button', { name: 'Finance' }), { key: 'Escape' });
    expect(huelle().getAttribute('data-sichtbar')).toBe('nein');
  });

  it('Strg+Alt+D holt das Dock und setzt den Fokus aufs erste Symbol', async () => {
    render(() => <Shell />);
    await financeOeffnen();
    fireEvent.keyDown(window, { code: 'KeyD', key: 'd', ctrlKey: true, altKey: true });
    expect(document.querySelector('[data-dock="offene"]')!.getAttribute('data-sichtbar')).toBe('ja');
    await waitFor(() => expect((document.activeElement as HTMLElement).getAttribute('aria-label')).toBe('Finance'));
  });

  it('ohne Räume (aus) bleibt das klassische Dock mit FYOS, Punkten und Agent', async () => {
    raeumeSetzen({ ...raeume(), an: false });
    render(() => <Shell />);
    const dock = screen.getByRole('navigation', { name: 'Bodenleiste' });
    expect(within(dock).getByRole('button', { name: 'FYOS' })).toBeTruthy();
    expect(within(dock).getByRole('button', { name: 'Agent' })).toBeTruthy();
    expect(within(dock).getAllByRole('tab').length).toBeGreaterThan(0);
    expect(screen.queryByRole('navigation', { name: 'Räume' })).toBeNull();
    // FYOS im klassischen Dock öffnet dieselbe Apps-Seite
    fireEvent.click(within(dock).getByRole('button', { name: 'FYOS' }));
    expect(await screen.findByRole('region', { name: 'Apps' })).toBeTruthy();
  });
});

describe('Speicherstände bleiben gültig (keine Migration nötig)', () => {
  it('die gespeicherte Reihenfolge der Räume (fyos:os:raeume:v2) gilt weiter', () => {
    localStorage.setItem('fyos:os:raeume:v2', JSON.stringify({ an: true, aktiv: 'zentrale', reihenfolge: ['zuhause', 'betrieb', 'buero', 'vorhaben', 'atelier', 'sammlung', 'gespraech'] }));
    raeumeZuruecksetzen();
    render(() => <Shell />);
    const raeumeNamen = within(leiste()).getAllByRole('button').map((b) => b.getAttribute('data-raum')).filter(Boolean);
    expect(raeumeNamen).toEqual(['zentrale', 'zuhause', 'betrieb', 'buero', 'vorhaben', 'atelier', 'sammlung', 'gespraech', 'einstellungen']);
    // nichts umgeschrieben: dieselben Schlüssel, derselbe Inhalt
    expect(JSON.parse(localStorage.getItem('fyos:os:raeume:v2')!).reihenfolge[0]).toBe('zuhause');
  });
});
