/**
 * FYOS-Shell: Start, Arbeitsfläche, Bodenleiste. Geprüft wird, was schiefgehen würde, ohne dass
 * es jemand merkt: eine Fläche, die sich nicht öffnen oder wieder schließen lässt, eine
 * Anordnung, die den Neuladen nicht übersteht, ein ausgefallener Hub, der die Shell mitreißt.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const hub = vi.hoisted(() => vi.fn());
const hubApps = vi.hoisted(() => vi.fn());
vi.mock('~/lib/hub', () => ({ hub }));
vi.mock('~/lib/mcp-apps/host', () => ({
  apps: hubApps,
  appCall: vi.fn(async () => ({ content: [{ type: 'text', text: '{}' }] })),
  appEinhaengen: vi.fn(async () => () => {}),
  aktuellesTheme: () => 'dark',
}));

import Shell from '~/components/os/Shell';
import { appCall } from '~/lib/mcp-apps/host';
import { AGENT_FRAGEN, type AgentFragenDetail } from '~/lib/os/app-aktionen';
import { konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';
import { OEFFNEN, eingabeKodieren, eingabeLesen } from '~/lib/os/oeffnen';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { ZEIGT_EREIGNIS } from '~/lib/os/mitteilungen';

const seite = (id: string, titel: string, pfad: string) => ({ id, titel, gruppe: 'Arbeit', art: 'seite' as const, kuerzel: titel.slice(0, 2), pfad });

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
  // Die Distribution bringt keine eigenen Seiten mit: Plugins melden ihre über registriereFlaechen an.
  registriereFlaechen({
    flaechen: [seite('seite:notizen', 'Notizen', '/notizen/'), seite('seite:kalender', 'Kalender', '/kalender/'), seite('seite:wiki', 'Wiki', '/wiki/')],
    standardPlaetze: [{ name: 'Schreiben', ids: ['seite:notizen', 'seite:kalender', 'seite:wiki'] }],
    dinge: { notiz: { name: 'Notiz', pfad: '/notizen/' } },
  });
  konfigurationSetzen({ extern: [{ slug: 'git', titel: 'Git', url: 'https://git.example.org' }] });
  hub.mockReset();
  hub.mockResolvedValue({});
  hubApps.mockReset();
  hubApps.mockResolvedValue([
    { name: 'leitstand__lagebild', tool: 'leitstand.lagebild', title: 'Lagebild', description: '', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://x' } }, scope: 'READ' },
  ]);
});
afterEach(() => {
  cleanup();
  registerZuruecksetzen();
  konfigurationZuruecksetzen();
  vi.unstubAllGlobals();
});

const bodenleiste = () => screen.getByRole('navigation', { name: 'Bodenleiste' });
/** Einen Punkt im offenen Menü (auch im Untermenü) anklicken. */
const menuePunkt = async (name: string) => {
  const text = await screen.findByText(name, { selector: '[data-os-menue] [role^="menuitem"] span' });
  fireEvent.click(text.closest('[role^="menuitem"]')!);
};
/** Menü eines Fensters über ⋯ öffnen und einem Pfad folgen (Untermenü → Punkt). */
const fensterMenue = async (fenster: HTMLElement, titel: string, ...pfad: string[]) => {
  fireEvent.click(within(fenster).getByRole('button', { name: `${titel}: Größe und Platz` }));
  for (const name of pfad) await menuePunkt(name);
  await waitFor(() => expect(document.querySelector('[data-os-menue]')).toBeNull());
};

describe('Shell', () => {
  it('zeigt ohne offene Flächen den Startbildschirm, keine leere Fläche', () => {
    render(() => <Shell />);
    expect(screen.getByRole('region', { name: 'Start' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'FYOS' })).toBeTruthy();
    expect(within(bodenleiste()).getByRole('button', { name: 'FYOS' })).toBeTruthy();
  });

  it('öffnet eine Fläche über den Start und zeigt sie in Arbeitsfläche und Bodenleiste', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
    expect(within(bodenleiste()).getByRole('button', { name: /Notizen/ })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'FYOS' })).toBeNull(); // Start schließt sich
  });

  it('ein externer Dienst (Gruppe „Extern“) öffnet in neuem Tab, nicht als Fenster', async () => {
    const open = vi.fn();
    vi.stubGlobal('open', open);
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Git/ }));
    expect(open).toHaveBeenCalledWith('https://git.example.org', '_blank', 'noopener');
    expect(screen.queryByRole('region', { name: 'Git' })).toBeNull();
    expect(screen.queryByRole('dialog', { name: 'FYOS' })).toBeNull(); // Start schließt sich
  });

  it('findet Hub-Apps von selbst im Start', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Lagebild/ }));
    expect(await screen.findByRole('region', { name: 'Lagebild' })).toBeTruthy();
  });

  it('minimiert, holt zurück und schließt', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    await screen.findByRole('region', { name: 'Notizen' });
    fireEvent.click(screen.getByRole('button', { name: 'Notizen minimieren' }));
    expect(screen.queryByRole('region', { name: 'Notizen' })).toBeNull();
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: /Notizen/ }));
    await screen.findByRole('region', { name: 'Notizen' });
    fireEvent.click(screen.getByRole('button', { name: 'Notizen schließen' }));
    expect(screen.queryByRole('region', { name: 'Notizen' })).toBeNull();
    expect(within(bodenleiste()).queryByRole('button', { name: /Notizen/ })).toBeNull();
  });

  it('merkt sich die Anordnung über ein Neuladen', async () => {
    const a = render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    await screen.findByRole('region', { name: 'Notizen' });
    a.unmount();
    render(() => <Shell />);
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });

  it('übersteht einen nicht erreichbaren Hub (Flächen aus Seiten gehen weiter)', async () => {
    hub.mockRejectedValue(new Error('HTTP 502'));
    hubApps.mockRejectedValue(new Error('HTTP 502'));
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });

  it('der Agent öffnet als Dock und bleibt danach geladen', async () => {
    render(() => <Shell />);
    expect(document.querySelector('iframe[title="Agent-Chat"]')).toBeNull(); // nichts vorab geladen
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Agent' }));
    await waitFor(() => expect(document.querySelector('iframe[title="Agent-Chat"]')).not.toBeNull());
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Agent' }));
    expect(document.querySelector('iframe[title="Agent-Chat"]')).not.toBeNull(); // bleibt im Hintergrund
  });

  it('Strg+K öffnet den Start, Esc schließt ihn', async () => {
    render(() => <Shell />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(await screen.findByRole('dialog', { name: 'FYOS' })).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'FYOS' })).toBeNull());
  });

  it('Enter in der Suche öffnet den ersten Treffer', async () => {
    render(() => <Shell />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const feld = await screen.findByRole('searchbox', { name: 'Fläche suchen' });
    fireEvent.input(feld, { target: { value: 'notizen' } });
    fireEvent.keyDown(feld, { key: 'Enter' });
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });
});

describe('Shell und Agent über den Hub', () => {
  it('meldet die Anordnung dem Hub (damit der Agent sieht, was offen ist)', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    await screen.findByRole('region', { name: 'Notizen' });
    await waitFor(() => {
      const aufruf = hub.mock.calls.find((c) => c[0] === 'shell.merken');
      expect(aufruf).toBeTruthy();
      expect(aufruf![1].fenster.map((w: { id: string }) => w.id)).toContain('seite:notizen');
      expect(aufruf![1].verfuegbar.length).toBeGreaterThan(5);
    }, { timeout: 3000 });
  });

  it('führt Befehle des Agenten aus: öffnen und minimieren; Unbekanntes wird übergangen', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const befehle = [
      { befehle: [{ aktion: 'oeffnen', flaeche: 'seite:notizen' }, { aktion: 'oeffnen', flaeche: 'seite:gibt-es-nicht' }] },
      { befehle: [{ aktion: 'minimieren', flaeche: 'seite:notizen' }] },
    ];
    hub.mockImplementation(async (tool: string) => (tool === 'shell.abholen' ? (befehle.shift() ?? { befehle: [] }) : { ampel: 'gruen', kacheln: [] }));
    render(() => <Shell />);
    await vi.advanceTimersByTimeAsync(3100);
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Notizen' })).toBeNull());
    expect(within(bodenleiste()).getByRole('button', { name: /Notizen/ })).toBeTruthy(); // minimiert, nicht weg
    vi.useRealTimers();
  });

  it('übernimmt auf einem neuen Gerät die Anordnung aus dem Hub', async () => {
    hub.mockImplementation(async (tool: string) =>
      tool === 'shell.zustand' ? { bekannt: true, fenster: [{ id: 'seite:notizen', min: false, breit: false }], agent: false } : { ampel: 'gruen', kacheln: [] });
    render(() => <Shell />);
    // Die alte Meldung wird ein Arbeitsbildschirm, der nach seinem Fenster heißt; gezeigt wird zuerst der Start.
    const reiter = await screen.findByRole('tab', { name: 'Notizen' });
    await waitFor(() => expect(hub.mock.calls.some((c) => c[0] === 'shell.zustand')).toBe(true));
    fireEvent.click(reiter);
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });
});

describe('Arbeitsplätze und Handy', () => {
  it('ein vorgegebener Arbeitsplatz ersetzt die offenen Flächen durch seine', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Schreiben/ }));
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Kalender' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Wiki' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: 'FYOS' })).toBeNull();
  });

  it('speichert die aktuelle Anordnung unter einem Namen im Hub und zeigt Fehler', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    await screen.findByRole('region', { name: 'Notizen' });
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    const feld = await screen.findByRole('textbox', { name: 'Name für die Vorlage' });
    fireEvent.input(feld, { target: { value: 'Mein Platz' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => {
      const a = hub.mock.calls.find((c) => c[0] === 'shell.platz_speichern');
      expect(a![1].name).toBe('Mein Platz');
      expect(a![1].fenster.map((w: { id: string }) => w.id)).toEqual(['seite:notizen']);
    });
    hub.mockImplementation(async (tool: string) => { if (tool === 'shell.platz_speichern') throw new Error('Schon 12 Arbeitsplaetze'); return { plaetze: [] }; });
    fireEvent.input(feld, { target: { value: 'Noch einer' } });
    fireEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(await screen.findByText(/Schon 12 Arbeitsplaetze/)).toBeTruthy();
  });

  it('auf dem Handy steht immer genau eine Fläche da; die Bodenleiste wechselt', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('767'), media: q, addEventListener() {}, removeEventListener() {} }));
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Schreiben/ }));
    await screen.findAllByRole('region');
    expect(screen.getAllByRole('region')).toHaveLength(1); // drei Flächen offen, eine zu sehen
    const sichtbar = screen.getAllByRole('region')[0]!.getAttribute('aria-label');
    const andere = ['Notizen', 'Kalender', 'Wiki'].find((n) => n !== sichtbar)!;
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: new RegExp(andere) }));
    await waitFor(() => expect(screen.getByRole('region', { name: andere })).toBeTruthy());
    expect(screen.getAllByRole('region')).toHaveLength(1);
  });

  it('der Agent kann einen Arbeitsplatz laden (Befehl platz)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let gesendet = false;
    hub.mockImplementation(async (tool: string) => {
      if (tool === 'shell.abholen') { if (gesendet) return { befehle: [] }; gesendet = true; return { befehle: [{ aktion: 'platz', name: 'Planung' }] }; }
      if (tool === 'shell.plaetze') return { plaetze: [{ name: 'Planung', fenster: [{ id: 'seite:wiki', min: false, breit: false }] }] };
      return { ampel: 'gruen', kacheln: [] };
    });
    render(() => <Shell />);
    await vi.advanceTimersByTimeAsync(3300);
    expect(await screen.findByRole('region', { name: 'Wiki' })).toBeTruthy();
    vi.useRealTimers();
  });
});

describe('Bildschirme und Raster', () => {
  const notizenOeffnen = async () => {
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    return screen.findByRole('region', { name: 'Notizen' });
  };

  it('vom Start aus geöffnet, landet die Fläche auf einem Arbeitsbildschirm, der nach ihr heißt; die Punkte im Dock wechseln', async () => {
    render(() => <Shell />);
    await notizenOeffnen();
    expect(screen.queryByRole('region', { name: 'Start' })).toBeNull(); // Start ist verdeckt
    fireEvent.click(within(bodenleiste()).getByRole('tab', { name: 'Start' }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Start' })).toBeTruthy());
    expect(screen.queryByRole('region', { name: 'Notizen' })).toBeNull();
    fireEvent.click(within(bodenleiste()).getByRole('tab', { name: 'Notizen' }));
    await waitFor(() => expect(screen.getByRole('region', { name: 'Notizen' })).toBeTruthy());
  });

  it('⌥⌘← und ⌥⌘→ wechseln den Bildschirm, ⌥⌘1 geht zum Start', async () => {
    render(() => <Shell />);
    await notizenOeffnen();
    fireEvent.keyDown(window, { key: 'ArrowLeft', metaKey: true, altKey: true });
    await waitFor(() => expect(screen.getByRole('region', { name: 'Start' })).toBeTruthy());
    fireEvent.keyDown(window, { key: 'ArrowRight', metaKey: true, altKey: true });
    await waitFor(() => expect(screen.getByRole('region', { name: 'Notizen' })).toBeTruthy());
    // Mit ⌥ liefert e.key am Mac „¡“ statt „1“: das OS liest die Taste (e.code)
    fireEvent.keyDown(window, { key: '¡', code: 'Digit1', ctrlKey: true, altKey: true });
    await waitFor(() => expect(screen.getByRole('region', { name: 'Start' })).toBeTruthy());
  });

  it('„+“ im Dock legt einen neuen, leeren Bildschirm an und zeigt, wie es weitergeht', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    expect(await screen.findByText('Dieser Bildschirm ist leer.')).toBeTruthy();
    expect(within(bodenleiste()).getByRole('tab', { name: 'Bildschirm 2' }).getAttribute('aria-selected')).toBe('true');
  });

  it('das Fenstermenü setzt Breite, Höhe und „neue Zeile“ — und das bleibt gespeichert', async () => {
    render(() => <Shell />);
    const fenster = await notizenOeffnen();
    // Eine Scrollebene: Zeilen nach oben offen — Fenster wachsen mit ihrem Inhalt, nur die Fläche scrollt
    const raster = (fenster as HTMLElement).parentElement!;
    expect(raster.getAttribute('style')).toContain('minmax(22rem, auto)');
    await fensterMenue(fenster as HTMLElement, 'Notizen', 'Breite', 'Zwei Drittel');
    await fensterMenue(fenster as HTMLElement, 'Notizen', 'Höhe', 'Groß');
    await fensterMenue(fenster as HTMLElement, 'Notizen', 'In neuer Zeile beginnen');
    await waitFor(() => expect((fenster as HTMLElement).style.gridColumn).toBe('1 / span 8'));
    expect((fenster as HTMLElement).style.gridRow).toBe('span 14');
    // von Hand: die gewählte Höhe ist die Mindesthöhe, die Zeilen dehnen sich nicht über den Bildschirm
    expect(raster.getAttribute('style')).toContain('grid-auto-rows: minmax(2.5rem, auto)');
    expect(raster.getAttribute('style')).toContain('align-content: start');
    const gespeichert = JSON.parse(localStorage.getItem('fyos:os:bildschirme:v1')!);
    expect(gespeichert.bildschirme[0].fenster[0]).toMatchObject({ id: 'seite:notizen', spalten: 8, zeilen: 14, neueZeile: true });
  });

  it('„Bildschirmhoch“ passt das Fenster genau in den sichtbaren Bereich (Seiten mit eigenen Spalten)', async () => {
    const hoch = vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(1000); // 62,5 rem → (62,5 − 1,25) / 3,25 = 18
    render(() => <Shell />);
    const fenster = await notizenOeffnen();
    await fensterMenue(fenster as HTMLElement, 'Notizen', 'Höhe', 'Bildschirmhoch');
    await waitFor(() => expect((fenster as HTMLElement).style.gridRow).toBe('span 18'));
    hoch.mockRestore();
  });

  it('verschiebt ein Fenster über das Menü auf einen anderen Bildschirm und wechselt mit', async () => {
    render(() => <Shell />);
    await notizenOeffnen();
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    fireEvent.click(within(bodenleiste()).getByRole('tab', { name: 'Notizen' }));
    const fenster = await screen.findByRole('region', { name: 'Notizen' });
    await fensterMenue(fenster as HTMLElement, 'Notizen', 'Auf Bildschirm', 'Bildschirm 3');
    await waitFor(() => expect(within(bodenleiste()).getByRole('tab', { name: 'Notizen' }).getAttribute('aria-selected')).toBe('true'));
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
    const gespeichert = JSON.parse(localStorage.getItem('fyos:os:bildschirme:v1')!);
    expect(gespeichert.bildschirme.map((b: { fenster: { id: string }[] }) => b.fenster.map((w) => w.id))).toEqual([[], ['seite:notizen']]);
  });

  // Ziehen und Ablegen (lib/os/ziehen.ts). jsdom hat kein DataTransfer — ein schlichtes Gegenstück.
  const zug = () => {
    const daten = new Map<string, string>();
    return {
      effectAllowed: 'all',
      dropEffect: 'none',
      get types() { return [...daten.keys()]; },
      setData: (t: string, v: string) => void daten.set(t.toLowerCase(), v),
      getData: (t: string) => daten.get(t.toLowerCase()) ?? '',
      setDragImage: () => {},
    };
  };

  it('eine Notiz auf den leeren Schreibtisch gezogen öffnet die Fläche, auf der sie lebt', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    const leer = (await screen.findByText('Dieser Bildschirm ist leer.')).parentElement!;
    const d = zug();
    d.setData('text/plain', 'fyos://notiz/n-4133');
    fireEvent.dragOver(leer, { dataTransfer: d });
    fireEvent.drop(leer, { dataTransfer: d });
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });

  it('ein Dock-Symbol auf einen Bildschirm-Punkt gezogen verschiebt das Fenster dorthin', async () => {
    render(() => <Shell />);
    await notizenOeffnen();
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    fireEvent.click(within(bodenleiste()).getByRole('tab', { name: 'Notizen' }));
    const d = zug();
    fireEvent.dragStart(within(bodenleiste()).getByRole('button', { name: 'Notizen' }), { dataTransfer: d });
    const ziel = within(bodenleiste()).getAllByRole('tab').at(-1)!;
    fireEvent.dragOver(ziel, { dataTransfer: d });
    fireEvent.drop(ziel, { dataTransfer: d });
    await waitFor(() => {
      const gespeichert = JSON.parse(localStorage.getItem('fyos:os:bildschirme:v1')!);
      expect(gespeichert.bildschirme.map((b: { fenster: { id: string }[] }) => b.fenster.map((w) => w.id))).toEqual([[], ['seite:notizen']]);
    });
  });
});

describe('Menüs, Übersicht und Gesten', () => {
  const notizenOeffnen = async () => {
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    fireEvent.click(await screen.findByRole('button', { name: /Notizen/ }));
    return (await screen.findByRole('region', { name: 'Notizen' })) as HTMLElement;
  };
  it('Rechtsklick auf den Fensterkopf öffnet das Fenstermenü; Schließen schließt', async () => {
    render(() => <Shell />);
    const fenster = await notizenOeffnen();
    const kopf = fenster.querySelector('header')!;
    fireEvent.contextMenu(kopf, { clientX: 200, clientY: 120 });
    expect(await screen.findByRole('menu')).toBeTruthy();
    expect(screen.getByText('Neu laden')).toBeTruthy();
    await menuePunkt('Schließen');
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Notizen' })).toBeNull());
  });

  it('Rechtsklick in den Inhalt eines Fensters lässt das Menü des Browsers', async () => {
    render(() => <Shell />);
    const fenster = await notizenOeffnen();
    const inhalt = fenster.querySelector('[data-kontext="inhalt"]')!;
    const ereignis = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
    inhalt.dispatchEvent(ereignis);
    expect(ereignis.defaultPrevented).toBe(false);
    expect(document.querySelector('[data-os-menue]')).toBeNull();
  });

  it('Rechtsklick auf den Schreibtisch bietet einen neuen Bildschirm an', async () => {
    render(() => <Shell />);
    fireEvent.contextMenu(document.querySelector('[data-schreibtisch]')!, { clientX: 300, clientY: 300 });
    await menuePunkt('Neuer Bildschirm');
    await waitFor(() => expect(within(bodenleiste()).getByRole('tab', { name: 'Bildschirm 2' }).getAttribute('aria-selected')).toBe('true'));
  });

  it('Rechtsklick auf einen Bildschirm-Punkt kann ihn schließen', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    fireEvent.contextMenu(within(bodenleiste()).getByRole('tab', { name: 'Bildschirm 2' }));
    await menuePunkt('Bildschirm schließen');
    await waitFor(() => expect(within(bodenleiste()).queryByRole('tab', { name: 'Bildschirm 2' })).toBeNull());
  });

  it('die Menüleiste öffnet ihre Menüs; Darstellung › Übersicht zeigt alle Bildschirme', async () => {
    render(() => <Shell />);
    const leiste = screen.getByRole('banner', { name: 'Menüleiste' });
    fireEvent.pointerDown(within(leiste).getByRole('button', { name: 'Darstellung' }), { button: 0 });
    await menuePunkt('Übersicht');
    await waitFor(() => expect(document.querySelector('.os-uebersicht')).toBeTruthy());
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(document.querySelector('.os-uebersicht')).toBeNull());
  });

  it('mit offenem Menü: Darüberfahren wechselt, der Klick danach lässt das neue Menü offen', async () => {
    render(() => <Shell />);
    const leiste = screen.getByRole('banner', { name: 'Menüleiste' });
    fireEvent.pointerDown(within(leiste).getByRole('button', { name: 'Darstellung' }), { button: 0 });
    await screen.findByText('Übersicht', { selector: '[data-os-menue] [role^="menuitem"] span' });
    const ablage = within(leiste).getByRole('button', { name: 'Ablage' });
    fireEvent.pointerEnter(ablage);
    fireEvent.pointerDown(ablage, { button: 0 });
    expect(await screen.findByText('Neuer Bildschirm', { selector: '[data-os-menue] [role^="menuitem"] span' })).toBeTruthy();
    expect(ablage.getAttribute('aria-expanded')).toBe('true');
    // Ein zweiter Klick schließt wie gewohnt
    fireEvent.pointerDown(ablage, { button: 0 });
    await waitFor(() => expect(document.querySelector('[data-os-menue]')).toBeNull());
  });

  it('⌥⌘↑ schaltet die Übersicht; ein Klick auf einen Bildschirm wechselt dorthin', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'Neuer Bildschirm' }));
    fireEvent.click(within(bodenleiste()).getByRole('tab', { name: 'Start' }));
    fireEvent.keyDown(window, { key: 'ArrowUp', metaKey: true, altKey: true });
    await waitFor(() => expect(document.querySelector('.os-uebersicht')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Bildschirm 2' }));
    await waitFor(() => expect(document.querySelector('.os-uebersicht')).toBeNull());
    expect(within(bodenleiste()).getByRole('tab', { name: 'Bildschirm 2' }).getAttribute('aria-selected')).toBe('true');
  });

  it('Kneifen auf dem Trackpad (wheel mit ctrlKey) öffnet die Übersicht, statt die Seite zu zoomen', async () => {
    render(() => <Shell />);
    const wurzel = document.querySelector('[data-shell]')!;
    const ereignis = new WheelEvent('wheel', { deltaY: 90, ctrlKey: true, bubbles: true, cancelable: true });
    wurzel.dispatchEvent(ereignis);
    expect(ereignis.defaultPrevented).toBe(true);
    await waitFor(() => expect(document.querySelector('.os-uebersicht')).toBeTruthy());
  });

  it('eine Mitteilung (fyos:zeigt) erscheint oben rechts; „Öffnen“ öffnet die Fläche', async () => {
    render(() => <Shell />);
    window.dispatchEvent(new CustomEvent(ZEIGT_EREIGNIS, { detail: { ziel: 'seite:notizen', titel: 'Notizen', vorschau: 'Drei neue Einträge.' } }));
    expect(await screen.findByText('Drei neue Einträge.')).toBeTruthy();
    expect(screen.getByText('Agent zeigt dir')).toBeTruthy();
    // Keine Fläche wurde dabei geöffnet: es bleibt beim Start
    expect(within(bodenleiste()).getByRole('tab', { name: 'Start' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: /Öffnen/ }));
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });

  it('eine Mitteilung für eine unbekannte Fläche wird nicht gezeigt', async () => {
    render(() => <Shell />);
    window.dispatchEvent(new CustomEvent(ZEIGT_EREIGNIS, { detail: { ziel: 'seite:gibt-es-nicht', titel: 'Nichts' } }));
    await new Promise((r) => setTimeout(r, 20));
    expect(document.querySelector('[data-mitteilung]')).toBeNull();
  });
});

describe('Übergänge: Deeplink mit Eingabe, fyos:oeffnen und der App-Rahmen', () => {
  const adresse = (suche: string) => history.replaceState(null, '', `/os/${suche}`);
  const werkstatt = (name: string, scope: string, required: string[] = []) => ({
    name, tool: name.replace('__', '.'), title: `Werkstatt — ${name.split('__')[1]}`, description: '', inputSchema: { required }, scope,
    _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } },
  });
  const gespeichert = () => JSON.parse(localStorage.getItem('fyos:os:bildschirme:v1')!);
  const fensterDerApp = async () => (await screen.findByRole('region', { name: 'Lagebild' })) as HTMLElement;
  /** Ereignis an die Shell schicken; true = sie hat es übernommen (preventDefault). */
  const oeffnenSenden = (detail: unknown) => {
    const e = new CustomEvent(OEFFNEN, { detail, cancelable: true });
    window.dispatchEvent(e);
    return e.defaultPrevented;
  };

  beforeEach(() => vi.mocked(appCall).mockClear());
  afterEach(() => {
    history.replaceState(null, '', '/');
    Reflect.deleteProperty(navigator, 'clipboard');
  });

  it('?offen=app:… öffnet die App; ?eingabe=… startet sie mit genau diesen Argumenten und merkt sie im Fenster', async () => {
    adresse(`?offen=app:leitstand__lagebild&eingabe=${eingabeKodieren({ tage: 3 })}`);
    render(() => <Shell />);
    await fensterDerApp();
    await waitFor(() => expect(appCall).toHaveBeenCalledWith('leitstand__lagebild', { tage: 3 }));
    expect(gespeichert().bildschirme[0].fenster[0]).toMatchObject({
      id: 'app:leitstand__lagebild',
      start: { werkzeug: 'leitstand__lagebild', eingabe: { tage: 3 } },
    });
  });

  it('eine unlesbare Eingabe in der Adresse öffnet die App trotzdem, mit der Anfangsansicht', async () => {
    adresse('?offen=app:leitstand__lagebild&eingabe=%25%25kaputt');
    render(() => <Shell />);
    await fensterDerApp();
    await waitFor(() => expect(appCall).toHaveBeenCalledWith('leitstand__lagebild', {}));
    expect(gespeichert().bildschirme[0].fenster[0].start).toBeUndefined();
  });

  it('die Eingabe gilt nur für die erste Fläche der Liste', async () => {
    adresse(`?offen=app:leitstand__lagebild,seite:notizen&eingabe=${eingabeKodieren({ tage: 3 })}`);
    render(() => <Shell />);
    await screen.findByRole('region', { name: 'Notizen' });
    const fenster = gespeichert().bildschirme[0].fenster;
    expect(fenster.find((w: { id: string }) => w.id === 'seite:notizen').start).toBeUndefined();
    expect(fenster.find((w: { id: string }) => w.id === 'app:leitstand__lagebild').start).toBeDefined();
  });

  it('ein Link auf ein Werkzeug einer App mit mehreren öffnet die App selbst; geschrieben wird dabei nichts', async () => {
    hubApps.mockResolvedValue([werkstatt('werkstatt__suchen', 'READ'), werkstatt('werkstatt__ausfuehren', 'WRITE', ['id'])]);
    adresse(`?offen=app:werkstatt__ausfuehren&eingabe=${eingabeKodieren({ id: 'ausrollen', ausfuehren: true })}`);
    render(() => <Shell />);
    expect(await screen.findByRole('region', { name: 'Werkstatt' })).toBeTruthy();
    await waitFor(() => expect(gespeichert().bildschirme[0].fenster.map((w: { id: string }) => w.id)).toEqual(['app:werkstatt__suchen']));
    await waitFor(() => expect(appCall).toHaveBeenCalled());
    // nur ein lesendes Werkzeug läuft; das schreibende wurde nie aufgerufen
    expect(vi.mocked(appCall).mock.calls.map((c) => c[0])).not.toContain('werkstatt__ausfuehren');
  });

  it('fyos:oeffnen öffnet eine Fläche und gilt damit als übernommen; Unbekanntes bleibt unübernommen', async () => {
    render(() => <Shell />);
    expect(oeffnenSenden({ ziel: 'seite:notizen' })).toBe(true);
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
    expect(oeffnenSenden({ ziel: 'seite:gibt-es-nicht' })).toBe(false);
    expect(oeffnenSenden({ ziel: 'app:gibt__es_nicht' })).toBe(false);
    expect(oeffnenSenden({ ziel: '/gibt/es/nicht/' })).toBe(false);
    expect(oeffnenSenden(undefined)).toBe(false);
    expect(oeffnenSenden({ ziel: 42 })).toBe(false);
  });

  it('fyos:oeffnen mit dem Pfad einer Seite findet die Fläche dazu (mit und ohne Schrägstrich am Ende)', async () => {
    render(() => <Shell />);
    expect(oeffnenSenden({ ziel: '/notizen/' })).toBe(true);
    await screen.findByRole('region', { name: 'Notizen' });
    fireEvent.click(screen.getByRole('button', { name: 'Notizen schließen' }));
    expect(oeffnenSenden({ ziel: '/notizen' })).toBe(true);
    expect(await screen.findByRole('region', { name: 'Notizen' })).toBeTruthy();
  });

  it('fyos:oeffnen mit Eingabe startet die App damit; eine schon offene App übernimmt die neue Eingabe', async () => {
    render(() => <Shell />);
    await waitFor(() => expect(oeffnenSenden({ ziel: 'app:leitstand__lagebild', eingabe: { tage: 1 } })).toBe(true));
    await fensterDerApp();
    await waitFor(() => expect(appCall).toHaveBeenCalledWith('leitstand__lagebild', { tage: 1 }));
    oeffnenSenden({ ziel: 'app:leitstand__lagebild', eingabe: { tage: 7 } });
    await waitFor(() => expect(appCall).toHaveBeenCalledWith('leitstand__lagebild', { tage: 7 })); // lädt mit der neuen Eingabe neu
    expect(screen.getAllByRole('region', { name: 'Lagebild' })).toHaveLength(1);
  });

  describe('App-Rahmen im Fensterkopf', () => {
    it('trägt Symbol und Titel der App und bietet Agent fragen, Link kopieren und Heften an — Seiten nicht', async () => {
      adresse('?offen=app:leitstand__lagebild,seite:notizen');
      render(() => <Shell />);
      const app = await fensterDerApp();
      expect(app.querySelector('header.os-kopf-app .os-app-titel .os-symbol')).toBeTruthy();
      expect(within(app).getByRole('heading', { name: 'Lagebild' })).toBeTruthy();
      for (const name of ['Lagebild: Agent fragen', 'Lagebild: Link kopieren', 'Lagebild: an den Start heften', 'Lagebild: Größe und Platz']) {
        expect(within(app).getByRole('button', { name }), name).toBeTruthy();
      }
      const seite = await screen.findByRole('region', { name: 'Notizen' });
      expect(seite.querySelector('.os-app-aktionen')).toBeNull();
      expect(within(seite).queryByRole('button', { name: /Agent fragen/ })).toBeNull();
    });

    it('Agent fragen löst fyos:agent-fragen mit Name, Eingabe und Modellkontext der App aus', async () => {
      adresse(`?offen=app:leitstand__lagebild&eingabe=${eingabeKodieren({ tage: 3 })}`);
      const gehoert: AgentFragenDetail[] = [];
      const hoerer = (e: Event) => void gehoert.push((e as CustomEvent<AgentFragenDetail>).detail);
      window.addEventListener(AGENT_FRAGEN, hoerer);
      try {
        render(() => <Shell />);
        const app = await fensterDerApp();
        await waitFor(() => expect(appCall).toHaveBeenCalled());
        fireEvent.click(within(app).getByRole('button', { name: 'Lagebild: Agent fragen' }));
        expect(gehoert).toEqual([
          {
            text: expect.stringContaining('Lagebild'),
            kontext: { app: 'leitstand__lagebild', titel: 'Lagebild', eingabe: { tage: 3 }, modellKontext: null },
            quelle: 'app',
          },
        ]);
      } finally {
        window.removeEventListener(AGENT_FRAGEN, hoerer);
      }
    });

    it('Link kopieren legt den Link mit der Eingabe in die Zwischenablage und sagt „Link kopiert" im Kopf', async () => {
      const schreiben = vi.fn(async () => {});
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: schreiben }, configurable: true });
      adresse(`?offen=app:leitstand__lagebild&eingabe=${eingabeKodieren({ tage: 3 })}`);
      render(() => <Shell />);
      const app = await fensterDerApp();
      fireEvent.click(within(app).getByRole('button', { name: 'Lagebild: Link kopieren' }));
      await waitFor(() => expect(schreiben).toHaveBeenCalledTimes(1));
      const link = new URL(String((schreiben.mock.calls[0] as unknown[])[0]));
      expect(link.pathname).toBe('/os/');
      expect(link.searchParams.get('offen')).toBe('app:leitstand__lagebild');
      expect(eingabeLesen(link.searchParams.get('eingabe'))).toEqual({ tage: 3 });
      await waitFor(() => expect(app.querySelector('.os-app-melder')!.textContent).toContain('Link kopiert'));
      expect(app.querySelector('.os-app-melder')!.hasAttribute('data-an')).toBe(true);
      expect(within(app).getByRole('button', { name: 'Lagebild: Link kopieren' }).classList.contains('os-app-gut')).toBe(true);
    });

    it('Heften zeigt die App im Startbildschirm vor; ein zweiter Klick löst sie wieder', async () => {
      adresse('?offen=app:leitstand__lagebild');
      render(() => <Shell />);
      const app = await fensterDerApp();
      fireEvent.click(within(app).getByRole('button', { name: 'Lagebild: an den Start heften' }));
      const gelost = await within(app).findByRole('button', { name: 'Lagebild: vom Start lösen' });
      expect(gelost.getAttribute('aria-pressed')).toBe('true');
      expect(JSON.parse(localStorage.getItem('fyos:app-pins')!)).toEqual(['leitstand__lagebild']);
      fireEvent.click(gelost);
      await within(app).findByRole('button', { name: 'Lagebild: an den Start heften' });
      expect(JSON.parse(localStorage.getItem('fyos:app-pins')!)).toEqual([]);
    });

    it('eine App mit mehreren Werkzeugen lässt sich nicht heften (sie liefe beim Laden des Startbildschirms von selbst)', async () => {
      hubApps.mockResolvedValue([werkstatt('werkstatt__suchen', 'READ'), werkstatt('werkstatt__ausfuehren', 'WRITE', ['id'])]);
      adresse('?offen=app:werkstatt__suchen');
      render(() => <Shell />);
      const app = (await screen.findByRole('region', { name: 'Werkstatt' })) as HTMLElement;
      expect(within(app).getByRole('button', { name: 'Werkstatt: Agent fragen' })).toBeTruthy();
      expect(within(app).queryByRole('button', { name: /an den Start heften/ })).toBeNull();
    });

    it('das Fenstermenü führt dieselben Aktionen zuerst auf, mit Symbolen vor jedem Punkt', async () => {
      adresse('?offen=app:leitstand__lagebild');
      render(() => <Shell />);
      const app = await fensterDerApp();
      fireEvent.click(within(app).getByRole('button', { name: 'Lagebild: Größe und Platz' }));
      const menu = await screen.findByRole('menu');
      const punkte = within(menu).getAllByRole('menuitem');
      expect(punkte.slice(0, 3).map((p) => p.textContent)).toEqual([
        expect.stringContaining('Agent fragen'),
        expect.stringContaining('Link kopieren'),
        expect.stringContaining('An den Start heften'),
      ]);
      // „Link kopieren" steht für Apps nur einmal im Menü (oben, mit der aktuellen Eingabe)
      expect(punkte.filter((p) => p.textContent?.includes('Link kopieren'))).toHaveLength(1);
      // jeder Punkt trägt ein Symbol
      for (const p of punkte) expect(p.querySelector('.os-menue-haken svg'), p.textContent ?? '').toBeTruthy();
    });

    it('das Fenstermenü einer Seite bleibt, wie es war: Link kopieren, aber kein Agent fragen', async () => {
      adresse('?offen=seite:notizen');
      render(() => <Shell />);
      const seite = (await screen.findByRole('region', { name: 'Notizen' })) as HTMLElement;
      fireEvent.click(within(seite).getByRole('button', { name: 'Notizen: Größe und Platz' }));
      const menu = await screen.findByRole('menu');
      const texte = within(menu).getAllByRole('menuitem').map((p) => p.textContent ?? '');
      expect(texte.some((t) => t.includes('Link kopieren'))).toBe(true);
      expect(texte.some((t) => t.includes('Agent fragen'))).toBe(false);
    });
  });

  it('Rechtsklick auf eine App im Start bietet Heften an', async () => {
    render(() => <Shell />);
    fireEvent.click(within(bodenleiste()).getByRole('button', { name: 'FYOS' }));
    const panel = await screen.findByRole('dialog', { name: 'FYOS' });
    const kachel = await within(panel).findByRole('button', { name: /Lagebild/ });
    fireEvent.contextMenu(kachel, { clientX: 200, clientY: 200 });
    await menuePunkt('An den Start heften');
    await waitFor(() => expect(JSON.parse(localStorage.getItem('fyos:app-pins')!)).toEqual(['leitstand__lagebild']));
    // die Kachel zeigt die Anheftung
    expect(await within(panel).findByRole('button', { name: /Lagebild/ }).then((k) => k.querySelector('.os-kachel-pin'))).toBeTruthy();
  });
});
