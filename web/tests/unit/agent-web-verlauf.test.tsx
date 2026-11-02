/**
 * Gesprächsfläche: Verlauf (Nachrichtenblasen, Arbeitszeile, Autonomes, Freigabekarte, Statuszeilen).
 * Der Zustand kommt durch denselben Reducer wie im Betrieb, aus Ereignisformen des Runners (agent-web-fixtures).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createSignal, type JSX } from 'solid-js';
import { Verlauf } from '~/components/os/nativ/agent/Verlauf';
import type { Freigabe, GespraechsZustand } from '~/lib/agent-runner/typen';
import { T0, assistent, aufruf, eingang, mensch, schreibenStapel, werkzeugErgebnis, zugEintraege, zustand } from './agent-web-fixtures';

beforeEach(() => {
  // jsdom kennt scrollTo an Elementen nicht
  (Element.prototype as unknown as { scrollTo: () => void }).scrollTo = vi.fn();
});
afterEach(() => cleanup());

const frei = (id: string, extra: Partial<Freigabe> = {}): Freigabe => ({
  id,
  conversationId: 1,
  status: 'offen',
  aktion: `Branch löschen ${id}`,
  risiko: 'high',
  kontext: 'Der Branch ist gemergt.',
  werkzeug: 'bash',
  befehl: 'git push origin --delete alt',
  ...extra,
});

function zeige(z: GespraechsZustand, p: Partial<Parameters<typeof Verlauf>[0]> = {}): { p: Parameters<typeof Verlauf>[0] } {
  const props: Parameters<typeof Verlauf>[0] = {
    z,
    agentName: 'Agent',
    fehler: null,
    verbunden: true,
    live: true,
    fokus: 1,
    freigaben: [],
    weitere: 0,
    entscheide: vi.fn(async () => {}),
    spaeter: vi.fn(),
    zurFreigabenListe: vi.fn(),
    letzteRegung: Date.now(),
    flaute: false,
    nachfassen: vi.fn(async () => {}),
    abbrechen: vi.fn(async () => {}),
    ...p,
  };
  render(() => (<Verlauf {...props} />) as JSX.Element);
  return { p: props };
}

const gespraech = () => zustand([mensch(1, 'Wie steht INC-4905?'), ...zugEintraege(1)]);

describe('Verlauf: Chat statt Terminal', () => {
  it('du rechts, Agent links; die Antwort steht prominent, Links sind klickbar', () => {
    zeige(gespraech());
    const max = document.querySelector('[data-art="mensch"]')!;
    expect(max.textContent).toContain('Wie steht INC-4905?');
    expect(max.className).toContain('self-end');
    const zug = document.querySelector('[data-art="zug"]')!;
    expect(zug.className).toContain('self-start');
    const antwort = zug.querySelector('[data-antwort]')!;
    expect(antwort.textContent).toContain('INC-4905 ist offen.');
    expect(antwort.querySelector('strong')?.textContent).toBe('offen');
    const link = antwort.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('https://itsm.example/INC-4905');
    expect(link.getAttribute('rel')).toContain('noopener');
    // Uhrzeit steht dabei
    expect(zug.textContent).toMatch(/Agent · \d\d:\d\d/);
  });

  it('Arbeit ist EINE Zeile je Zug und zu; weder Gedanken noch Werkzeugnamen stehen im Fließtext', () => {
    zeige(gespraech());
    const arbeit = screen.getByRole('button', { name: /Gearbeitet · 2 Schritte · 38 s/ });
    expect(arbeit.getAttribute('aria-expanded')).toBe('false');
    const text = document.querySelector('[data-verlauf]')!.textContent ?? '';
    expect(text).not.toContain('The user wants');
    expect(text).not.toContain('hub_aufrufen');
    expect(text).not.toContain('git push');
    expect(text).not.toContain('Ich schaue kurz nach');
    expect(document.querySelectorAll('[data-arbeit]')).toHaveLength(1);
  });

  it('aufgeklappt: Schritte mit Klartext-Titel und Status; Gedanken erst auf Wunsch; Rohausgabe noch eine Ebene tiefer', () => {
    zeige(gespraech());
    fireEvent.click(screen.getByRole('button', { name: /Gearbeitet/ }));
    const schritte = document.querySelector('[data-schritte]')!;
    expect(within(schritte as HTMLElement).getByText('Vorgang INC-4905 gelesen')).toBeTruthy();
    expect(within(schritte as HTMLElement).getByText('Shell: git push origin main')).toBeTruthy();
    expect(schritte.querySelectorAll('[data-schritt="werkzeug"][data-status="fertig"]')).toHaveLength(2);
    // Zwischentext liegt in der Arbeit
    expect(schritte.textContent).toContain('Ich schaue kurz nach.');
    // Gedanken: nur die Zeile, der Text kommt erst nach Klick
    expect(schritte.textContent).toContain('Gedanken ·');
    expect(schritte.textContent).not.toContain('The user wants');
    fireEvent.click(within(schritte as HTMLElement).getByRole('button', { name: /Gedanken/ }));
    expect(schritte.textContent).toContain('The user wants');
    // Rohausgabe
    expect(schritte.textContent).not.toContain('main -> main');
    fireEvent.click(within(schritte as HTMLElement).getByRole('button', { name: /Shell: git push/ }));
    expect(schritte.textContent).toContain('main -> main');
  });

  it('ein Fehler ist am Schritt markiert und zählt in der Arbeitszeile, nicht im Fließtext', () => {
    zeige(zustand([mensch(1, 'Pushe es'), ...zugEintraege(1, { fehler: true })]));
    const arbeit = screen.getByRole('button', { name: /1 Fehler/ });
    fireEvent.click(arbeit);
    const schritt = document.querySelector('[data-schritt="werkzeug"][data-status="fehler"]')!;
    expect(schritt.textContent).toContain('Shell: python3 nach_main.py');
    expect(schritt.textContent).toContain('usage: nach_main.py [-h] --vorgang V');
    expect(within(document.querySelector('[data-antwort]') as HTMLElement).queryByText(/usage:/)).toBeNull();
    fireEvent.click(schritt.querySelector('button')!);
    expect(schritt.textContent).toContain('Fehlermeldung');
    expect(schritt.textContent).toContain('Kein Gitea-Token');
  });

  it('aufgeklappte Arbeit bleibt offen, während der Zug weiterschreibt und fertig wird', () => {
    const [z, setZ] = createSignal(zustand([mensch(1, 'Frage', T0)], [[{ type: 'run_start' }, { type: 'tool_execution_start', toolCallId: 'k', toolName: 'bash', args: { command: 'ls' } }]], true));
    render(() => (
      <Verlauf z={z()} agentName="Agent" fehler={null} verbunden live fokus={1} freigaben={[]} weitere={0} entscheide={async () => {}} spaeter={() => {}} zurFreigabenListe={() => {}} letzteRegung={Date.now()} flaute={false} nachfassen={async () => {}} abbrechen={async () => {}} />
    ));
    fireEvent.click(screen.getByRole('button', { name: /Arbeitet …/ }));
    expect(document.querySelector('[data-schritte]')!.textContent).toContain('Shell: ls');
    setZ(zustand([mensch(1, 'Frage', T0), ...zugEintraege(1)]));
    // derselbe Zug (gleicher Schlüssel) ist jetzt fertig und noch aufgeklappt
    expect(screen.getByRole('button', { name: /Gearbeitet/ }).getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('[data-schritte]')!.textContent).toContain('Vorgang INC-4905 gelesen');
  });

  it('laufender Zug: Arbeitet … und schreibt …, Antwort wächst', () => {
    zeige(zustand([mensch(1, 'Frage', Date.now() - 4000)], [schreibenStapel('Gleich')], true));
    const arbeit = screen.getByRole('button', { name: /Arbeitet …/ });
    expect(arbeit).toBeTruthy();
    expect(document.querySelector('[data-art="zug"]')!.getAttribute('aria-busy')).toBe('true');
    expect(document.querySelector('[data-antwort]')!.textContent).toContain('Gleich');
    expect(document.querySelector('[data-art="zug"]')!.textContent).toContain('schreibt …');
  });

  it('ohne Verlauf: freundlicher Leerzustand; noch nicht geladen: Platzhalter', () => {
    zeige({ ...zustand([]), geladen: true });
    expect(screen.getByText(/Noch nichts gesagt/)).toBeTruthy();
    cleanup();
    zeige({ ...zustand([]), geladen: false });
    expect(screen.getByLabelText('Gespräch wird geladen')).toBeTruthy();
  });
});

describe('Verlauf: die eigenständige Arbeit des Agenten', () => {
  const mitTakt = () =>
    zustand([
      eingang(1, 'zeitplan', 'Takt Morgen', 'system', T0),
      assistent(2, [aufruf('a', 'hub_aufrufen', { werkzeug: 'cluster.lage' })], T0 + 1_000),
      werkzeugErgebnis(3, 'a', 'hub_aufrufen', 'grün', false, T0 + 2_000),
      assistent(4, [{ type: 'text', text: 'Alles ruhig.' }], T0 + 3_000),
      mensch(5, 'Danke, und jetzt?', T0 + 20_000),
      assistent(6, [{ type: 'text', text: 'Ich warte.' }], T0 + 21_000),
    ]);

  it('Live an: dezente Zeile mit Anlass, aufklappbar; du\' Gespräch bleibt als Blase daneben', () => {
    zeige(mitTakt());
    const auto = document.querySelector('[data-art="autonom"]')!;
    expect(auto.textContent).toContain('zeitplan');
    expect(auto.textContent).toContain('Takt Morgen');
    expect(auto.textContent).toContain('1 Schritt');
    expect(auto.textContent).not.toContain('Alles ruhig.');
    fireEvent.click(auto.querySelector('button')!);
    expect(auto.textContent).toContain('Alles ruhig.');
    expect(document.querySelectorAll('[data-art="mensch"]')).toHaveLength(1);
  });

  it('Live aus (Ruhe): sie fehlt im Verlauf, ein Hinweis zählt sie', () => {
    zeige(mitTakt(), { live: false });
    expect(document.querySelector('[data-art="autonom"]')).toBeNull();
    expect(document.querySelector('[data-ausgeblendet]')!.textContent).toContain('1 eigenständige Arbeit ausgeblendet');
    expect(screen.getByText('Ich warte.')).toBeTruthy();
  });
});

describe('Verlauf: Freigaben, Flaute, Verbindung', () => {
  it('Freigabekarte im Verlauf: Aktion, Risiko, Befehl; Erlauben, Ablehnen, Später', async () => {
    const { p } = zeige(gespraech(), { freigaben: [frei('fr-1')], weitere: 2 });
    const karte = document.querySelector('[data-freigabe="fr-1"]') as HTMLElement;
    expect(karte.textContent).toContain('Branch löschen fr-1');
    expect(karte.textContent).toContain('Risiko hoch');
    expect(karte.textContent).toContain('git push origin --delete alt');
    fireEvent.click(within(karte).getByRole('button', { name: 'Erlauben' }));
    await waitFor(() => expect(p.entscheide).toHaveBeenCalledWith('fr-1', 'erteilt'));
    fireEvent.click(within(karte).getByRole('button', { name: 'Ablehnen' }));
    await waitFor(() => expect(p.entscheide).toHaveBeenCalledWith('fr-1', 'abgelehnt'));
    fireEvent.click(within(karte).getByRole('button', { name: 'Später' }));
    expect(p.spaeter).toHaveBeenCalledWith('fr-1');
    fireEvent.click(screen.getByRole('button', { name: /2 weitere Freigaben warten/ }));
    expect(p.zurFreigabenListe).toHaveBeenCalled();
  });

  it('langer Kontext wird gekürzt und lässt sich ausklappen', () => {
    zeige(gespraech(), { freigaben: [frei('fr-2', { kontext: 'x'.repeat(600) })] });
    const karte = document.querySelector('[data-freigabe="fr-2"]') as HTMLElement;
    expect(karte.textContent).not.toContain('x'.repeat(600));
    fireEvent.click(within(karte).getByRole('button', { name: 'mehr' }));
    expect(karte.textContent).toContain('x'.repeat(600));
  });

  it('Zeitüberschreitung ist eine Statuszeile mit Nachfassen, kein Text im Verlauf', async () => {
    const { p } = zeige(zustand([mensch(1, 'Frage')], [], true), { flaute: true, letzteRegung: Date.now() - 16 * 60_000 });
    const zeile = document.querySelector('[data-statuszeile="flaute"]') as HTMLElement;
    expect(zeile.getAttribute('role')).toBe('status');
    expect(zeile.textContent).toContain('Keine fertige Antwort nach 16 min.');
    expect(document.querySelector('[data-art="zug"]')?.textContent ?? '').not.toContain('Keine fertige Antwort');
    fireEvent.click(within(zeile).getByRole('button', { name: 'Nachfassen' }));
    await waitFor(() => expect(p.nachfassen).toHaveBeenCalled());
    fireEvent.click(within(zeile).getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(p.abbrechen).toHaveBeenCalled());
  });

  it('abgerissene Verbindung: sichtbarer Zustand', () => {
    zeige({ ...gespraech(), geladen: true }, { verbunden: false });
    expect(document.querySelector('[data-statuszeile="verbindung"]')!.textContent).toContain('Verbindung verloren – versuche erneut');
  });
});

describe('Verlauf: lange Verläufe bleiben flüssig', () => {
  it('zeichnet die letzten 60 Punkte; „Ältere anzeigen“ holt die nächste Seite', async () => {
    const viele = Array.from({ length: 150 }, (_, i) => mensch(i + 1, `Nachricht ${i + 1}`, T0 + i * 1000));
    zeige(zustand(viele));
    expect(document.querySelectorAll('[data-art="mensch"]')).toHaveLength(60);
    expect(screen.getByText('Nachricht 150')).toBeTruthy();
    expect(screen.queryByText('Nachricht 90')).toBeNull();
    const mehr = document.querySelector('[data-aelteres]') as HTMLButtonElement;
    expect(mehr.textContent).toContain('90');
    fireEvent.click(mehr);
    await waitFor(() => expect(document.querySelectorAll('[data-art="mensch"]')).toHaveLength(120));
    fireEvent.click(document.querySelector('[data-aelteres]') as HTMLButtonElement);
    await waitFor(() => expect(document.querySelectorAll('[data-art="mensch"]')).toHaveLength(150));
    expect(document.querySelector('[data-aelteres]')).toBeNull();
  });
});
