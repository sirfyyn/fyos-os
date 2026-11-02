/**
 * Keine deutschen Reste in der englischen Oberfläche. Die Shell wird englisch gezeichnet und Fläche für Fläche
 * geöffnet (Apps-Seite in allen Ansichten, Menüleiste mit Untermenüs, Fenster und Fenstermenü, leerer Bildschirm,
 * Kontrollzentrum, Hilfe, Glocke). Alles Sichtbare und Vorgelesene (Text, aria-label, title, placeholder) darf weder
 * Umlaute noch typisch deutsche Wörter tragen. Eigennamen stehen in der kleinen Ausnahmeliste unten.
 *
 * Fällt dieser Test, fehlt meist ein tr() um einen Text oder ein Schlüssel in lib/i18n/en.ts (Begriffe: docs/GLOSSARY.md).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@solidjs/testing-library';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const hub = vi.hoisted(() => vi.fn());
const hubApps = vi.hoisted(() => vi.fn());
vi.mock('~/lib/hub', () => ({ hub }));
vi.mock('~/lib/os/bruecke-neu', async (orig) => ({
  ...(await orig<typeof import('~/lib/os/bruecke-neu')>()),
  erzeugeBruecke: () => ({ start: () => true, stop: () => {}, aendern: () => {}, melden: async () => {}, status: () => 'aus', gesperrt: () => null, sitzungen: () => null }),
}));
vi.mock('~/components/os/nativ/Agent', () => ({ default: () => <div class="agent-runner" /> }));
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
import { konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';
import { spracheFestlegen } from '~/lib/i18n';
import { menueZu } from '~/lib/os/menue';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { raeume, raeumeSetzen, raeumeZuruecksetzen } from '~/lib/os/raeume';
import { wartetZuruecksetzen } from '~/lib/os/wartet';
import { shellTeileVorladen } from './shell-vorladen';

/** Typisch deutsche Wörter der Oberfläche (ganze Wörter; Groß/klein egal). Englische Doppelgänger (Start, Agent, Filter) fehlen bewusst. */
const DEUTSCHE_WOERTER = [
  'und', 'nicht', 'mit', 'für', 'ist', 'ein', 'eine', 'einen', 'der', 'die', 'das', 'den', 'dem', 'des', 'auf', 'zu', 'noch',
  'neu', 'neuer', 'neue', 'neues', 'alle', 'keine', 'kein', 'oder', 'wird', 'kann', 'gibt', 'hier', 'jetzt', 'vom', 'zum',
  'zur', 'bei', 'von', 'bis', 'nach', 'ja', 'nein', 'zurück', 'speichern', 'schließen', 'öffnen', 'bildschirm', 'bildschirme',
  'vorlage', 'vorlagen', 'zuletzt', 'fläche', 'flächen', 'fenster', 'ansicht', 'einstellungen', 'leeren', 'abbrechen',
  'löschen', 'suchen', 'darstellung', 'ablage', 'hilfe', 'offen', 'heute', 'gestern', 'uhr', 'raum', 'räume', 'gehe',
];
const WORT = new RegExp(`(^|[^\\p{L}])(${DEUTSCHE_WOERTER.join('|')})(?=$|[^\\p{L}])`, 'iu');
const UMLAUT = /[äöüÄÖÜß„]/;
/** Eigennamen und Kennungen, die in jeder Sprache so heißen. */
const AUSNAHMEN = new Set<string>(['FYOS']);

/** Alles Sichtbare und Vorgelesene unter `wurzel`, als einzelne Texte. */
function texte(wurzel: ParentNode = document.body): string[] {
  const aus: string[] = [];
  const gang = document.createTreeWalker(wurzel as Node, NodeFilter.SHOW_TEXT);
  for (let n = gang.nextNode(); n; n = gang.nextNode()) {
    const el = n.parentElement;
    if (!el || el.closest('script, style, [aria-hidden="true"]')) continue;
    const t = (n.textContent ?? '').trim();
    if (t) aus.push(t);
  }
  for (const el of (wurzel as Element).querySelectorAll?.('[aria-label], [title], [placeholder]') ?? []) {
    for (const a of ['aria-label', 'title', 'placeholder']) {
      const v = el.getAttribute(a)?.trim();
      if (v) aus.push(v);
    }
  }
  return aus;
}

function deutscheReste(liste: string[]): string[] {
  return [...new Set(liste)].filter((t) => !AUSNAHMEN.has(t) && (UMLAUT.test(t) || WORT.test(t)));
}

/** Gesammelte Texte aller Schritte; am Ende eines Tests geprüft, damit eine Liste alle Reste zeigt. */
let gesammelt: string[] = [];
const sammeln = (wurzel?: ParentNode) => void gesammelt.push(...texte(wurzel));
const bodenleiste = () => document.querySelector<HTMLElement>('nav[data-kontext="dock"]')!;
const menueSchliessen = async () => {
  menueZu();
  await waitFor(() => expect(document.querySelector('[data-os-menue]')).toBeNull());
};
/** Das offene Menü einsammeln, dabei jedes Untermenü einmal aufklappen. */
async function menueSammeln() {
  const menue = await screen.findByRole('menu');
  sammeln(menue);
  const unter = within(menue).queryAllByRole('menuitem').filter((p) => p.getAttribute('aria-haspopup') === 'menu');
  for (const u of unter) {
    fireEvent.click(u);
    await waitFor(() => expect(screen.getAllByRole('menu').length).toBeGreaterThan(1));
    for (const m of screen.getAllByRole('menu')) sammeln(m);
  }
}

beforeAll(shellTeileVorladen);

beforeEach(() => {
  spracheFestlegen('en');
  gesammelt = [];
  wartetZuruecksetzen();
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
  // Eine Fläche eines Plugins: ihr Titel ist Sache des Plugins (hier schon englisch), die Gruppe ein Schlüssel der Shell
  registriereFlaechen({
    flaechen: [{ id: 'seite:notizen', titel: 'Notes', gruppe: 'Arbeit', art: 'seite', kuerzel: 'No', pfad: '/notizen/' }],
    standardPlaetze: [],
    dinge: {},
  });
  konfigurationSetzen({});
  raeumeZuruecksetzen();
  raeumeSetzen({ ...raeume(), an: false });
  history.replaceState(null, '', '/os/');
  hub.mockReset();
  hub.mockResolvedValue({});
  hubApps.mockReset();
  hubApps.mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  registerZuruecksetzen();
  konfigurationZuruecksetzen();
  vi.unstubAllGlobals();
  spracheFestlegen('de');
});

describe('Englische Oberfläche ohne deutsche Reste', () => {
  it('der Prüfer selbst erkennt Deutsch und lässt Englisch durch', () => {
    expect(deutscheReste(['‹ Zurück', 'Nach Raum', 'Diesen Bildschirm speichern als …', 'Neuer Bildschirm', 'Vorlagen'])).toHaveLength(5);
    expect(deutscheReste(['‹ Back', 'By room', 'A–Z', 'Recent', 'Save this screen as …', 'New screen', 'Templates', 'FYOS', 'Start'])).toEqual([]);
  });

  it('Apps-Seite (alle drei Ansichten), Menüleiste, Fenster und Fenstermenü', async () => {
    render(() => <Shell />);
    sammeln();
    // Apps-Seite
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    const apps = await screen.findByRole('region', { name: 'Apps' });
    await within(apps).findByRole('button', { name: 'Notes' });
    sammeln(apps);
    for (const ansicht of ['A–Z', 'Recent']) {
      fireEvent.click(within(apps).getByRole('button', { name: ansicht }));
      sammeln(apps);
    }
    fireEvent.click(within(apps).getByRole('button', { name: 'By room' }));
    // eine Fläche öffnen: Fenster, Dock, leerer zweiter Bildschirm
    fireEvent.click(within(apps).getByRole('button', { name: 'Notes' }));
    const fenster = (await screen.findByRole('region', { name: 'Notes' })) as HTMLElement;
    sammeln();
    fireEvent.click(within(fenster).getByRole('button', { name: 'Notes: size and position' }));
    await menueSammeln();
    await menueSchliessen();
    // Menüleiste: jedes Menü mit seinen Untermenüs
    const leiste = screen.getByRole('banner', { name: 'Menu bar' });
    for (const knopf of within(leiste).getAllByRole('button').filter((b) => b.hasAttribute('data-menueleiste-punkt'))) {
      fireEvent.pointerDown(knopf, { button: 0 });
      await menueSammeln();
      await menueSchliessen();
    }
    // die Apps-Seite noch einmal mit offenem Fenster (Vorlage speichern ist dann möglich)
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    sammeln(await screen.findByRole('region', { name: 'Apps' }));
    expect(deutscheReste(gesammelt)).toEqual([]);
  });

  it('leerer Bildschirm und Rechtsklick-Menüs', async () => {
    render(() => <Shell />);
    fireEvent.contextMenu(document.querySelector('[data-schreibtisch]')!, { clientX: 300, clientY: 300 });
    await menueSammeln();
    await menueSchliessen();
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'New screen' }));
    await screen.findByText('This screen is empty.');
    sammeln();
    fireEvent.contextMenu(within(bodenleiste()).getAllByRole('tab').at(-1)!);
    await menueSammeln();
    await menueSchliessen();
    expect(deutscheReste(gesammelt)).toEqual([]);
  });
});
