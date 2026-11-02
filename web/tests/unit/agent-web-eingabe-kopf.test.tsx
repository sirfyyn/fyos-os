/**
 * Gesprächsfläche: Eingabe (Enter, Umschalt+Enter, Entwurf, Befehlsmenü, Stopp) und Kopf (Zustand, Modell, Ruhe, Freigaben).
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { createSignal } from 'solid-js';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Eingabe } from '~/components/os/nativ/agent/Eingabe';
import { Kopf } from '~/components/os/nativ/agent/Kopf';
import { ENTWURF_PREFIX } from '~/lib/agent-runner/entwurf';
import { RunnerFehler } from '~/lib/agent-runner/verbindung';

beforeEach(() => localStorage.clear());
afterEach(() => cleanup());

function eingabe(p: Partial<Parameters<typeof Eingabe>[0]> = {}) {
  const sende = vi.fn(async () => ({}));
  const abbrechen = vi.fn(async () => {});
  render(() => <Eingabe agentName="Agent" busy={false} gesperrt={false} gespraechId={1} sende={sende} abbrechen={abbrechen} anmelden={() => {}} schmal={false} {...p} />);
  const feld = screen.getByLabelText('Nachricht an Agent') as HTMLTextAreaElement;
  const tippe = (t: string) => fireEvent.input(feld, { target: { value: t } });
  return { sende, abbrechen, feld, tippe };
}

describe('Eingabe', () => {
  it('Enter sendet, danach ist das Feld leer und der Entwurf weg', async () => {
    const { sende, feld, tippe } = eingabe();
    tippe('Wie steht INC-4905?');
    expect(localStorage.getItem(`${ENTWURF_PREFIX}1`)).toBe('Wie steht INC-4905?');
    fireEvent.keyDown(feld, { key: 'Enter' });
    await waitFor(() => expect(sende).toHaveBeenCalledWith('Wie steht INC-4905?', 'folgen'));
    await waitFor(() => expect(feld.value).toBe(''));
    expect(localStorage.getItem(`${ENTWURF_PREFIX}1`)).toBeNull();
  });

  it('Umschalt+Enter sendet nicht (Zeilenumbruch); leere Eingabe sendet nie', () => {
    const { sende, feld, tippe } = eingabe();
    tippe('Zeile 1');
    fireEvent.keyDown(feld, { key: 'Enter', shiftKey: true });
    expect(sende).not.toHaveBeenCalled();
    tippe('   ');
    fireEvent.keyDown(feld, { key: 'Enter' });
    expect(sende).not.toHaveBeenCalled();
    expect((screen.getByRole('button', { name: 'Senden' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('Entwurf bleibt je Gespräch erhalten, auch nach dem Wechsel und Neuzeichnen', async () => {
    localStorage.setItem(`${ENTWURF_PREFIX}7`, 'halber Satz');
    const [id, setId] = createSignal<number | null>(7);
    render(() => <Eingabe agentName="Agent" busy={false} gesperrt={false} gespraechId={id()} sende={vi.fn()} abbrechen={vi.fn()} anmelden={() => {}} schmal={false} />);
    const feld = screen.getByLabelText('Nachricht an Agent') as HTMLTextAreaElement;
    expect(feld.value).toBe('halber Satz');
    fireEvent.input(feld, { target: { value: 'halber Satz, weiter' } });
    setId(8);
    await waitFor(() => expect(feld.value).toBe(''));
    expect(localStorage.getItem(`${ENTWURF_PREFIX}7`)).toBe('halber Satz, weiter');
    setId(7);
    await waitFor(() => expect(feld.value).toBe('halber Satz, weiter'));
  });

  it('scheitert das Senden, bleibt der Text stehen und der Fehler wird gesagt', async () => {
    const sende = vi.fn(async () => {
      throw new RunnerFehler('nicht-erreichbar', 502, 'Runner antwortet nicht');
    });
    const { feld, tippe } = eingabe({ sende });
    tippe('wichtig');
    fireEvent.keyDown(feld, { key: 'Enter' });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Runner antwortet nicht'));
    expect(feld.value).toBe('wichtig');
    expect(localStorage.getItem(`${ENTWURF_PREFIX}1`)).toBe('wichtig');
  });

  it('Stopp erscheint nur, solange der Agent arbeitet, und bricht den Zug ab; dann gibt es Folgen/Steuern', async () => {
    const { abbrechen } = eingabe({ busy: true });
    fireEvent.click(screen.getByRole('button', { name: 'Zug abbrechen' }));
    await waitFor(() => expect(abbrechen).toHaveBeenCalled());
    expect(screen.getByRole('radio', { name: 'Steuern' })).toBeTruthy();
    cleanup();
    eingabe({ busy: false });
    expect(screen.queryByRole('button', { name: 'Zug abbrechen' })).toBeNull();
    expect(screen.queryByRole('radio', { name: 'Steuern' })).toBeNull();
  });

  it('Steuern schickt die Art mit', async () => {
    const { sende, feld, tippe } = eingabe({ busy: true });
    fireEvent.click(screen.getByRole('radio', { name: 'Steuern' }));
    tippe('lass das');
    fireEvent.keyDown(feld, { key: 'Enter' });
    await waitFor(() => expect(sende).toHaveBeenCalledWith('lass das', 'steuern'));
  });
});

describe('Eingabe: Schnellbefehle', () => {
  it('„/“ öffnet das Menü, Pfeile wählen, Enter vervollständigt, zweites Enter sendet den Befehl', async () => {
    const { sende, feld, tippe } = eingabe();
    expect(screen.queryByRole('listbox')).toBeNull();
    tippe('/');
    const menue = screen.getByRole('listbox', { name: 'Schnellbefehle' });
    expect(menue.querySelectorAll('[role="option"]')).toHaveLength(4);
    expect(feld.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(feld, { key: 'ArrowDown' });
    fireEvent.keyDown(feld, { key: 'ArrowDown' });
    expect(menue.querySelectorAll('[role="option"]')[2]!.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(feld, { key: 'Enter' });
    expect(feld.value).toBe('/neu ');
    expect(sende).not.toHaveBeenCalled();
    expect(screen.queryByRole('listbox')).toBeNull();
    fireEvent.keyDown(feld, { key: 'Enter' });
    await waitFor(() => expect(sende).toHaveBeenCalledWith('/neu', 'folgen'));
  });

  it('Filtern beim Tippen, Escape schließt, Klick wählt', () => {
    const { feld, tippe } = eingabe();
    tippe('/l');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([expect.stringContaining('/live')]);
    fireEvent.keyDown(feld, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    tippe('/');
    fireEvent.mouseDown(screen.getByRole('option', { name: /\/stopp/ }));
    expect(feld.value).toBe('/stopp ');
  });

  it('unbekanntes „/…“ ist normaler Text und öffnet kein Menü', () => {
    const { tippe } = eingabe();
    tippe('/etc/hosts');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});

describe('Kopf', () => {
  const kopf = (p: Partial<Parameters<typeof Kopf>[0]> = {}) => {
    const props = { setzeLive: vi.fn(), zurFreigabenListe: vi.fn() };
    render(() => (
      <Kopf agentName="Agent" geraet="Werkbank" busy={false} offeneFreigaben={0} spielmodus={null} modell="claude-sonnet-4" live getrennt={false} {...props} {...p} />
    ));
    return props;
  };

  it('zeigt Name, Gerät, Modell und den Zustand', () => {
    kopf();
    expect(screen.getByRole('heading', { name: /Agent/ }).textContent).toContain('Werkbank');
    expect(document.querySelector('[data-modell]')!.textContent).toBe('claude-sonnet-4');
    expect(document.querySelector('[data-kopf-status]')!.textContent).toBe('Bereit');
  });

  it.each([
    [{ busy: true }, 'Arbeitet …'],
    [{ busy: true, offeneFreigaben: 3 }, 'Wartet auf dich'],
    [{ busy: true, offeneFreigaben: 3, spielmodus: 'spielmodus.nachhut' }, 'Pausiert (Spielmodus)'],
    [{ getrennt: true }, 'Verbindung verloren'],
  ])('Zustand %j → %s', (p, text) => {
    kopf(p);
    expect(document.querySelector('[data-kopf-status]')!.textContent).toBe(text);
  });

  it('„3 Freigaben“ führt zur Liste; ohne offene Freigabe fehlt das Zeichen (die Zahl „wartet“ hat nur die Menüleiste)', () => {
    const p = kopf({ offeneFreigaben: 3 });
    const badge = screen.getByRole('button', { name: /3 Freigaben von Agent offen/ });
    expect(badge.textContent).toContain('3 Freigaben');
    expect(badge.textContent).not.toContain('auf dich');
    fireEvent.click(badge);
    expect(p.zurFreigabenListe).toHaveBeenCalled();
    cleanup();
    kopf();
    expect(document.querySelector('[data-freigaben-badge]')).toBeNull();
  });

  it('Ruhe-Schalter blendet die eigenständige Arbeit des Agenten aus und wieder ein', () => {
    const p = kopf();
    const ruhe = screen.getByRole('button', { name: /Ruhe/ });
    expect(ruhe.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(ruhe);
    expect(p.setzeLive).toHaveBeenCalledWith(false);
    cleanup();
    const q = kopf({ live: false });
    const an = screen.getByRole('button', { name: /Ruhe/ });
    expect(an.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(an);
    expect(q.setzeLive).toHaveBeenCalledWith(true);
  });
});
