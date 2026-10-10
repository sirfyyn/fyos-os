/**
 * lib/os/allein.ts + components/os/Allein.tsx — eine Fläche allein im Tab, mit Weg zurück ins OS.
 */
import { render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apps = vi.hoisted(() => vi.fn());
vi.mock('~/lib/mcp-apps/host', async (orig) => ({ ...(await orig<object>()), apps }));
vi.mock('~/components/apps/AppEingebettet', () => ({ default: (p: { name: string }) => <div data-app={p.name} /> }));

import Allein from '~/components/os/Allein';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { OS_NAME, alleinAdresse, inNeuemTab, osAdresse, osTabMelden, pfadFlaeche, zielAufloesen, zurueckZumOs } from '~/lib/os/allein';
import { alleFlaechen } from '~/lib/os/flaechen';
import { eingabeLesen } from '~/lib/os/oeffnen';

const WERKSTATT = [
  { name: 'werkstatt__suchen', tool: 'werkstatt.suchen', title: 'Werkstatt', scope: 'READ', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } } },
  { name: 'werkstatt__beschreiben', tool: 'werkstatt.beschreiben', title: 'Werkstatt', scope: 'READ', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } } },
];

const SEITEN = [
  { id: 'seite:notizen', titel: 'Notizen', gruppe: 'Arbeit', art: 'seite' as const, kuerzel: 'No', pfad: '/notizen/' },
  { id: 'seite:wiki-suche', titel: 'Suche', gruppe: 'Arbeit', art: 'seite' as const, kuerzel: 'Su', pfad: '/wiki/?tab=suche' },
];

beforeEach(() => registriereFlaechen({ flaechen: SEITEN }));

afterEach(() => {
  history.replaceState(null, '', '/');
  apps.mockReset();
  registerZuruecksetzen();
});

describe('Adressen', () => {
  it('Allein-Ansicht mit Ziel und Eingabe, OS mit der Fläche im Fenster', () => {
    const a = alleinAdresse('app:werkstatt__beschreiben', { id: 'ausrollen' });
    const q = new URL(a, 'https://x').searchParams;
    expect(a.startsWith('/os/allein/?')).toBe(true);
    expect(q.get('ziel')).toBe('app:werkstatt__beschreiben');
    expect(eingabeLesen(q.get('eingabe'))).toEqual({ id: 'ausrollen' });
    expect(osAdresse('seite:notizen')).toBe('/os/?offen=seite%3Anotizen');
    expect(osAdresse('/notizen/')).toBe('/os/');
  });

  it('„In neuem Tab öffnen“ geht in die Allein-Ansicht und behält den opener (sonst kein Weg zurück)', () => {
    const open = vi.fn();
    inNeuemTab({ id: 'seite:notizen' }, undefined, { open } as unknown as Window);
    expect(open).toHaveBeenCalledWith(alleinAdresse('seite:notizen'), '_blank');
    open.mockClear();
    inNeuemTab({ id: 'app:werkstatt__suchen' }, { werkzeug: 'werkstatt__beschreiben', eingabe: { id: 'x' } }, { open } as unknown as Window);
    expect(open).toHaveBeenCalledWith(alleinAdresse('app:werkstatt__beschreiben', { id: 'x' }), '_blank');
  });
});

describe('zielAufloesen (eine Regel für Shell und Allein-Ansicht)', () => {
  const liste = () => alleFlaechen(WERKSTATT as never);
  it('Fläche, Pfad, Werkzeug einer App mit Startzustand, Unbekanntes', () => {
    expect(zielAufloesen(liste(), 'seite:notizen')?.f.id).toBe('seite:notizen');
    expect(zielAufloesen(liste(), '/notizen/')?.f.id).toBe('seite:notizen');
    const w = zielAufloesen(liste(), 'app:werkstatt__beschreiben', { id: 'ausrollen' });
    expect(w?.f.id).toBe('app:werkstatt__suchen');
    expect(w?.start).toEqual({ werkzeug: 'werkstatt__beschreiben', eingabe: { id: 'ausrollen' } });
    expect(zielAufloesen(liste(), 'app:werkstatt__suchen')?.start).toBeUndefined();
    expect(zielAufloesen(liste(), 'seite:gibt-es-nicht')).toBeNull();
  });

  it('Pfad einer direkt aufgerufenen Seite: auch mit Filtern und Unterreitern, die genaueste Fläche gewinnt', () => {
    expect(pfadFlaeche(liste(), '/notizen')?.id).toBe('seite:notizen');
    expect(pfadFlaeche(liste(), '/notizen/?monat=9')?.id).toBe('seite:notizen');
    expect(pfadFlaeche(liste(), '/wiki/?tab=suche&ticket=7')?.id).toBe('seite:wiki-suche');
    expect(pfadFlaeche(liste(), '/wiki/?ticket=7')).toBeUndefined(); // die Seite ohne den Reiter ist keine Fläche
    expect(pfadFlaeche(liste(), '/gibt/es/nicht/')).toBeUndefined();
  });

  it('externe Dienste (Gruppe „Extern“) öffnen direkt, ohne Allein-Ansicht und ohne opener', () => {
    const open = vi.fn();
    inNeuemTab({ id: 'extern:gitea', extern: 'https://git.example.org' }, undefined, { open } as unknown as Window);
    expect(open).toHaveBeenCalledWith('https://git.example.org', '_blank', 'noopener');
  });
});

/** Ein Fenster zum Prüfen: Ursprung, Pfad, opener, open/close/focus. */
function fenster(pfad: string, o: Partial<{ opener: unknown; open: unknown }> = {}) {
  const w = {
    closed: false,
    name: '',
    opener: o.opener ?? null,
    top: undefined as unknown,
    location: { origin: 'https://fyos.test', pathname: pfad, href: `https://fyos.test${pfad}`, assign: vi.fn() },
    focus: vi.fn(),
    close: vi.fn(),
    open: o.open ?? vi.fn(),
  };
  w.top = w;
  return w;
}

describe('zurueckZumOs', () => {
  it('kam die Fläche aus dem OS: jenen Tab nach vorn, diesen schließen', async () => {
    const os = fenster('/os/');
    const ich = fenster('/os/allein/', { opener: os });
    expect(await zurueckZumOs('seite:notizen', ich as unknown as Window)).toBe('opener');
    expect(os.focus).toHaveBeenCalled();
    expect(ich.close).toHaveBeenCalled();
    expect(ich.location.assign).not.toHaveBeenCalled();
  });

  it('ohne opener: findet den offenen OS-Tab über Kanal und Namen', async () => {
    const os = fenster('/os/');
    const abmelden = osTabMelden(os as unknown as Window);
    expect(os.name).toBe(OS_NAME);
    try {
      const open = vi.fn(() => os);
      const ich = fenster('/os/allein/', { open });
      expect(await zurueckZumOs('seite:notizen', ich as unknown as Window)).toBe('name');
      expect(open).toHaveBeenCalledWith('', OS_NAME);
      expect(os.focus).toHaveBeenCalled();
    } finally {
      abmelden();
    }
  });

  it('fremder Tab, den Namen kennt er nicht: das leere Fenster geht wieder zu, dieser Tab wird das OS', async () => {
    const os = fenster('/os/');
    const abmelden = osTabMelden(os as unknown as Window);
    try {
      const leer = fenster('blank');
      const ich = fenster('/os/allein/', { open: vi.fn(() => leer) });
      expect(await zurueckZumOs('seite:notizen', ich as unknown as Window)).toBe('hier');
      expect(leer.close).toHaveBeenCalled();
      expect(ich.location.assign).toHaveBeenCalledWith('/os/?offen=seite%3Anotizen');
    } finally {
      abmelden();
    }
  });

  it('kein OS offen: dieser Tab wird das OS, ohne fremde Fenster anzulegen', async () => {
    const open = vi.fn();
    const ich = fenster('/os/allein/', { open });
    expect(await zurueckZumOs('app:werkstatt__suchen', ich as unknown as Window)).toBe('hier');
    expect(open).not.toHaveBeenCalled();
    expect(ich.location.assign).toHaveBeenCalledWith('/os/?offen=app%3Awerkstatt__suchen');
  });
});

describe('Allein-Ansicht', () => {
  it('zeigt die Hub-App im Fensterglas mit Zurück-Knopf, ohne Seitenleiste, und setzt den Titel', async () => {
    apps.mockResolvedValue(WERKSTATT);
    history.replaceState(null, '', alleinAdresse('app:werkstatt__suchen'));
    const { container } = render(() => <Allein />);
    expect(screen.getByRole('button', { name: 'Zurück ins OS' })).toBeTruthy();
    await waitFor(() => expect(container.querySelector('[data-app="werkstatt__suchen"]')).toBeTruthy());
    expect(container.querySelector('section.os-fenster[data-fenster="app:werkstatt__suchen"]')).toBeTruthy();
    expect(document.title).toContain('Werkstatt');
  });

  it('eine Seite läuft als eingebettete Seite (ohne Navigation) im Glas', async () => {
    apps.mockResolvedValue([]);
    history.replaceState(null, '', alleinAdresse('seite:notizen'));
    const { container } = render(() => <Allein />);
    const f = await waitFor(() => {
      const el = container.querySelector('iframe');
      if (!el) throw new Error('noch nicht');
      return el;
    });
    expect(f.getAttribute('src')).toContain('notizen');
  });

  it('direkt aufgerufene Seite: lädt genau die aufgerufene Adresse im Glas', async () => {
    apps.mockResolvedValue([]);
    history.replaceState(null, '', alleinAdresse('/notizen/?monat=9'));
    const { container } = render(() => <Allein />);
    const f = await waitFor(() => {
      const el = container.querySelector('iframe');
      if (!el) throw new Error('noch nicht');
      return el;
    });
    expect(f.getAttribute('src')).toBe('/notizen/?monat=9');
    expect(container.querySelector('section[data-fenster="seite:notizen"]')).toBeTruthy();
  });

  it('der alte Weg zu einer App (/apps/mcp/?app=…) zeigt die App selbst', async () => {
    apps.mockResolvedValue(WERKSTATT);
    history.replaceState(null, '', alleinAdresse('/apps/mcp/?app=werkstatt__beschreiben'));
    const { container } = render(() => <Allein />);
    await waitFor(() => expect(container.querySelector('section[data-fenster="app:werkstatt__suchen"]')).toBeTruthy());
  });

  it('sagt es, wenn es die Fläche nicht gibt', async () => {
    apps.mockResolvedValue([]);
    history.replaceState(null, '', alleinAdresse('app:weg__damit'));
    render(() => <Allein />);
    expect(await screen.findByText('Diese Fläche gibt es nicht (mehr).')).toBeTruthy();
  });
});
