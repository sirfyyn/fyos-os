/**
 * AppEingebettet: eine fest eingebettete Hub-App darf die Seite nie mitreißen.
 * Fehlt die App oder ist der Hub weg, steht eine Zeile da — sonst nichts.
 * Mit `start` (Deeplink mit Eingabe) läuft nur ein LESENDES Werkzeug derselben Oberfläche — nie etwas Schreibendes.
 */
import { fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apps = vi.hoisted(() => vi.fn());
const appCall = vi.hoisted(() => vi.fn());
const appEinhaengen = vi.hoisted(() => vi.fn());
const agentFragen = vi.hoisted(() => vi.fn());
vi.mock('~/lib/mcp-apps/host', () => ({
  apps,
  appCall,
  appEinhaengen,
  aktuellesTheme: () => 'dark',
}));
vi.mock('~/lib/os/agent-fragen', () => ({ agentFragen }));

import AppEingebettet from '~/components/apps/AppEingebettet';

beforeEach(() => {
  apps.mockReset();
  appCall.mockReset();
  appEinhaengen.mockReset();
  agentFragen.mockReset();
  appCall.mockResolvedValue({ content: [{ type: 'text', text: '{}' }] });
  appEinhaengen.mockResolvedValue(() => {});
});

describe('AppEingebettet', () => {
  it('ruft die App auf und zeigt ihren Rahmen', async () => {
    apps.mockResolvedValue([{ name: 'dokumente__eingang', tool: 'dokumente.eingang', scope: 'READ', inputSchema: {}, _meta: { ui: {} } }]);
    render(() => <AppEingebettet name="dokumente__eingang" titel="Eingang" />);
    expect(screen.getByRole('region', { name: 'Eingang' })).toBeTruthy();
    await waitFor(() => expect(appCall).toHaveBeenCalledWith('dokumente__eingang', {}));
  });

  it('sagt es, wenn es die App nicht gibt', async () => {
    apps.mockResolvedValue([]);
    render(() => <AppEingebettet name="weg__damit" titel="X" />);
    expect(await screen.findByText(/gibt es im Hub nicht/)).toBeTruthy();
    expect(appCall).not.toHaveBeenCalled();
  });

  it('übersteht einen toten Hub', async () => {
    apps.mockRejectedValue(new Error('HTTP 502'));
    render(() => <AppEingebettet name="dokumente__eingang" titel="Eingang" />);
    expect(await screen.findByText(/Hub nicht erreichbar: HTTP 502/)).toBeTruthy();
  });
});

describe('AppEingebettet im OS-Fenster (wachsen, eine Scrollebene)', () => {
  it('lässt die App ihre Höhe selbst melden und wächst mit: freier Rahmen, iframe so hoch wie gemeldet', async () => {
    apps.mockResolvedValue([{ name: 'werkstatt__suchen', tool: 'werkstatt.suchen', scope: 'READ', inputSchema: {}, _meta: { ui: {} } }]);
    const { container } = render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" wachsen />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    const o = appEinhaengen.mock.calls[0]![1];
    expect(o.fuellen).toBeFalsy(); // kein fester Rahmen: die App misst sich selbst (size-changed)
    const region = screen.getByRole('region', { name: 'Werkstatt' });
    expect(region.className).not.toContain('h-full'); // klemmt das Fenster nicht auf seine Höhe
    expect(region.style.minHeight).toBe('12rem'); // Platzhalter, bis die App ihre Höhe meldet
    o.onHeight(2600);
    const rahmen = container.querySelector('iframe')!;
    await waitFor(() => expect(rahmen.style.height).toBe('2600px'));
    expect(region.style.minHeight).toBe('');
  });
});

describe('AppEingebettet mit Startzustand (Deeplink mit Eingabe)', () => {
  const ui = (uri: string) => ({ ui: { resourceUri: uri } });
  const WERKSTATT = 'ui://fyos/werkstatt.html';
  const LISTE = [
    { name: 'werkstatt__suchen', tool: 'werkstatt.suchen', scope: 'READ', inputSchema: {}, _meta: ui(WERKSTATT) },
    { name: 'werkstatt__beschreiben', tool: 'werkstatt.beschreiben', scope: 'READ', inputSchema: { required: ['id'] }, _meta: ui(WERKSTATT) },
    { name: 'werkstatt__ausfuehren', tool: 'werkstatt.ausfuehren', scope: 'WRITE', inputSchema: { required: ['id'] }, _meta: ui(WERKSTATT) },
    { name: 'werkstatt__anderes', tool: 'werkstatt.anderes', scope: 'READ', inputSchema: {}, _meta: ui('ui://fyos/anderes.html') },
  ];
  const zeigen = (start?: { werkzeug: string; eingabe: Record<string, unknown> }, schluessel?: string) => {
    apps.mockResolvedValue(LISTE);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" start={start} schluessel={schluessel} fuellen />);
  };
  const aufgerufen = () => appCall.mock.calls.map((c) => [c[0], c[1]]);

  it('startet ein lesendes Werkzeug derselben Oberfläche mit der Eingabe aus dem Link', async () => {
    zeigen({ werkzeug: 'werkstatt__beschreiben', eingabe: { id: 'ausrollen' } }, 'app:werkstatt__suchen');
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__beschreiben', { id: 'ausrollen' }]]);
    const o = appEinhaengen.mock.calls[0]![1];
    expect(o.app.name).toBe('werkstatt__beschreiben');
    expect(o.args).toEqual({ id: 'ausrollen' });
    expect(o.schluessel).toBe('app:werkstatt__suchen'); // der Host merkt die Ansicht unter der Fläche
  });

  it('ein Link auf die App selbst startet sie mit der Eingabe', async () => {
    zeigen({ werkzeug: 'werkstatt__suchen', eingabe: { q: 'ausrollen' } });
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__suchen', { q: 'ausrollen' }]]);
  });

  it('startet nie ein schreibendes Werkzeug: die Anfangsansicht öffnet, ohne Eingabe', async () => {
    zeigen({ werkzeug: 'werkstatt__ausfuehren', eingabe: { id: 'ausrollen', ausfuehren: true } });
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__suchen', {}]]);
    expect(appEinhaengen.mock.calls[0]![1].args).toEqual({});
  });

  it('startet kein Werkzeug einer anderen Oberfläche und kein unbekanntes', async () => {
    zeigen({ werkzeug: 'werkstatt__anderes', eingabe: { x: 1 } });
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__suchen', {}]]);
  });

  it('ein unbekanntes Werkzeug öffnet ebenfalls nur die Anfangsansicht', async () => {
    zeigen({ werkzeug: 'werkstatt__gibt_es_nicht', eingabe: { x: 1 } });
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__suchen', {}]]);
  });

  it('ohne Startzustand läuft die App wie bisher mit leerer Eingabe', async () => {
    zeigen();
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(aufgerufen()).toEqual([['werkstatt__suchen', {}]]);
    expect(appEinhaengen.mock.calls[0]![1].schluessel).toBeUndefined();
  });
});

describe('AppEingebettet: nur aufrufen, was von selbst laufen darf', () => {
  const ui = { ui: { resourceUri: 'ui://fyos/werkstatt.html' } };
  const LISTE = [
    { name: 'werkstatt__suchen', tool: 'werkstatt.suchen', scope: 'READ', inputSchema: {}, _meta: ui },
    { name: 'werkstatt__beschreiben', tool: 'werkstatt.beschreiben', scope: 'READ', inputSchema: { required: ['id'] }, _meta: ui },
    { name: 'werkstatt__ausfuehren', tool: 'werkstatt.ausfuehren', scope: 'WRITE', inputSchema: {}, _meta: ui },
  ];

  it('ein Werkzeug mit Pflichtfeldern, die niemand belegt hat, läuft nicht: die App öffnet ohne Ergebnis', async () => {
    apps.mockResolvedValue([LISTE[1]!]);
    render(() => <AppEingebettet name="werkstatt__beschreiben" titel="Werkstatt" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(appCall).not.toHaveBeenCalled();
    expect(appEinhaengen.mock.calls[0]![1].ergebnis).toBeUndefined();
    expect(appEinhaengen.mock.calls[0]![1].args).toEqual({});
  });

  it('mit vollständiger Eingabe läuft es', async () => {
    apps.mockResolvedValue(LISTE);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" start={{ werkzeug: 'werkstatt__beschreiben', eingabe: { id: 'x' } }} />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(appCall.mock.calls).toEqual([['werkstatt__beschreiben', { id: 'x' }]]);
    expect(appEinhaengen.mock.calls[0]![1].ergebnis).toBeDefined();
  });

  it('ein Link mit unvollständiger Eingabe lässt das Werkzeug nicht mit halber Eingabe laufen', async () => {
    apps.mockResolvedValue(LISTE);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" start={{ werkzeug: 'werkstatt__beschreiben', eingabe: { anderes: 1 } }} />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(appCall).not.toHaveBeenCalled();
    expect(appEinhaengen.mock.calls[0]![1].ergebnis).toBeUndefined();
  });

  it('eine App, deren Kopf schreibend ist, ruft nie von selbst', async () => {
    apps.mockResolvedValue([LISTE[2]!]);
    render(() => <AppEingebettet name="werkstatt__ausfuehren" titel="Werkstatt" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(appCall).not.toHaveBeenCalled();
  });
});

describe('AppEingebettet: Aufräumen und Neuversuch', () => {
  const kopf = { name: 'werkstatt__suchen', tool: 'werkstatt.suchen', scope: 'READ', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } } };

  afterEach(() => vi.useRealTimers());

  it('meldet eine App sofort wieder ab, die erst einhing, als das Fenster schon zu war (kein Listener-Leck)', async () => {
    apps.mockResolvedValue([kopf]);
    const abmelden = vi.fn();
    let fertig: (f: () => void) => void = () => {};
    appEinhaengen.mockReturnValue(new Promise<() => void>((r) => (fertig = r)));
    const { unmount } = render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    unmount();
    expect(abmelden).not.toHaveBeenCalled();
    fertig(abmelden);
    await waitFor(() => expect(abmelden).toHaveBeenCalledTimes(1));
  });

  it('meldet beim Schließen die eingehängte App ab — genau einmal', async () => {
    apps.mockResolvedValue([kopf]);
    const abmelden = vi.fn();
    appEinhaengen.mockResolvedValue(abmelden);
    const { unmount } = render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    await Promise.resolve();
    unmount();
    expect(abmelden).toHaveBeenCalledTimes(1);
  });

  it('bricht ein Neuladen ab, das nach dem Schließen zurückkommt (Hub antwortet spät)', async () => {
    let liste: (l: unknown[]) => void = () => {};
    apps.mockReturnValue(new Promise((r) => (liste = r)));
    const { unmount } = render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" />);
    await waitFor(() => expect(apps).toHaveBeenCalled());
    unmount();
    liste([kopf]);
    await new Promise((r) => setTimeout(r, 20));
    expect(appCall).not.toHaveBeenCalled();
    expect(appEinhaengen).not.toHaveBeenCalled();
  });

  it('„Erneut versuchen“ meldet die alte App ab, lädt neu und setzt den Fehler zurück', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    apps.mockResolvedValue([kopf]);
    const ab1 = vi.fn();
    const ab2 = vi.fn();
    appEinhaengen.mockResolvedValueOnce(ab1).mockResolvedValueOnce(ab2);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" />);
    await vi.advanceTimersByTimeAsync(0);
    expect(appEinhaengen).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_000); // die App meldet keine Höhe: „konnte nicht geladen werden“
    const knopf = await screen.findByRole('button', { name: 'Erneut versuchen' });
    fireEvent.click(knopf);
    await vi.advanceTimersByTimeAsync(0);
    expect(ab1).toHaveBeenCalledTimes(1);
    expect(appEinhaengen).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('button', { name: 'Erneut versuchen' })).toBeNull(); // wieder „wird geladen …“
  });
});

describe('AppEingebettet: ui/message nur im OS-Fenster', () => {
  const kopf = { name: 'werkstatt__suchen', tool: 'werkstatt.suchen', scope: 'READ', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } }, titel: 'Werkstatt-Titel' };

  it('ohne Schlüssel (gewöhnliche Seite) gibt es keinen Weg zum Agenten', async () => {
    apps.mockResolvedValue([kopf]);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    expect(appEinhaengen.mock.calls[0]![1].onMessage).toBeUndefined();
  });

  it('mit Schlüssel (OS-Fenster) geht die Nachricht an den Agenten, mit App und Titel als Kontext', async () => {
    apps.mockResolvedValue([kopf]);
    render(() => <AppEingebettet name="werkstatt__suchen" titel="Werkstatt" schluessel="app:werkstatt__suchen" />);
    await waitFor(() => expect(appEinhaengen).toHaveBeenCalled());
    appEinhaengen.mock.calls[0]![1].onMessage('Was heißt das?');
    expect(agentFragen).toHaveBeenCalledWith({ text: 'Was heißt das?', kontext: { app: 'werkstatt__suchen', titel: 'Werkstatt' }, quelle: 'app' });
  });
});
