/**
 * Toasts und Glocke des Meldungsdienstes (components/os/MeldungenHost.tsx, MeldungenGlocke.tsx): Rollen, Tastatur, Schließen,
 * Anzeigedauer je Stufe (gefälschte Uhr), Halten bei Maus und Fokus, verborgener Tab, Klick öffnet das Ziel, Obergrenze, reduzierte Bewegung.
 * Die Quellen (Ströme, Abfragen) sind ausgetauscht; der Dienst ist der echte.
 */
import { cleanup, fireEvent, render, screen, within } from '@solidjs/testing-library';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MeldungenGlocke from '~/components/os/MeldungenGlocke';
import MeldungenHost, { AUS_MS } from '~/components/os/MeldungenHost';
import { OEFFNEN, type OsZiel } from '~/lib/os/oeffnen';
import type { MeldungEingabe } from '~/lib/os/meldungen';
import { VORGABE } from '~/lib/os/meldungen-einstellungen';
import { aendereEinstellungen, dienst } from '~/lib/os/meldungen-produktiv';

let n = 0;
const m = (extra: Partial<MeldungEingabe> = {}): MeldungEingabe => ({ quelle: 'agent', schluessel: `h${++n}`, stufe: 'normal', titel: `Titel ${n}`, text: 'Text', ...extra });
const lass = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
let geoeffnet: Array<OsZiel>;
let sichtbar = true;
let hoerer: EventListener;

const hostRendern = () => render(() => <MeldungenHost agentVorn={() => false} starten={() => () => {}} />);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
  vi.setSystemTime(new Date('2026-10-28T12:00:00'));
  aendereEinstellungen(() => structuredClone(VORGABE));
  dienst.verlaufLeeren();
  geoeffnet = [];
  sichtbar = true;
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (sichtbar ? 'visible' : 'hidden') });
  hoerer = ((e: CustomEvent<OsZiel>) => {
    geoeffnet.push(e.detail);
    e.preventDefault();
  }) as EventListener;
  window.addEventListener(OEFFNEN, hoerer);
});
afterEach(() => {
  window.removeEventListener(OEFFNEN, hoerer);
  cleanup();
  vi.useRealTimers();
});

describe('Toasts', () => {
  it('Rollen: kritisch und hoch sind alert, normal und niedrig status; die Gruppe heißt Meldungen', async () => {
    hostRendern();
    dienst.melde(m({ stufe: 'kritisch', quelle: 'stoerung', titel: 'Dienst ausgefallen' }));
    dienst.melde(m({ stufe: 'hoch', quelle: 'freigabe', titel: 'Freigabe: Pod' }));
    dienst.melde(m({ stufe: 'normal', titel: 'Hallo' }));
    await lass();
    expect(screen.getByRole('group', { name: 'Meldungen' })).toBeInTheDocument();
    const alarme = screen.getAllByRole('alert').map((a) => a.getAttribute('data-stufe')).sort();
    expect(alarme).toEqual(['hoch', 'kritisch']);
    expect(screen.getAllByRole('status').filter((s) => s.hasAttribute('data-stufe')).map((s) => s.getAttribute('data-stufe'))).toEqual(['normal']);
    // Stufe steht auch als Wort da, nicht nur als Farbe
    expect(screen.getByText(/Kritisch/)).toBeInTheDocument();
    expect(screen.getByText(/Wichtig/)).toBeInTheDocument();
  });

  it('normal verschwindet nach 6 s, hoch nach 30 s, niedrig nach 3 s; der Verlauf behält sie ungelesen', async () => {
    hostRendern();
    dienst.melde(m({ stufe: 'niedrig', titel: 'leise' }));
    dienst.melde(m({ stufe: 'normal', titel: 'mittel' }));
    dienst.melde(m({ stufe: 'hoch', titel: 'wichtig' }));
    await lass();
    expect(screen.getByText('leise')).toBeInTheDocument();
    await lass(3000 + AUS_MS + 20);
    expect(screen.queryByText('leise')).not.toBeInTheDocument();
    expect(screen.getByText('mittel')).toBeInTheDocument();
    await lass(3000 + AUS_MS + 20);
    expect(screen.queryByText('mittel')).not.toBeInTheDocument();
    expect(screen.getByText('wichtig')).toBeInTheDocument();
    await lass(24_000 + AUS_MS + 20);
    expect(screen.queryByText('wichtig')).not.toBeInTheDocument();
    expect(dienst.zustand.ungelesen).toBe(3);
  });

  it('kritisch bleibt stehen, bis „Verstanden“', async () => {
    hostRendern();
    dienst.melde(m({ stufe: 'kritisch', quelle: 'stoerung', titel: 'Knoten kritisch' }));
    await lass(10 * 60_000);
    expect(screen.getByText('Knoten kritisch')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Verstanden' }));
    await lass(AUS_MS + 20);
    expect(screen.queryByText('Knoten kritisch')).not.toBeInTheDocument();
    expect(dienst.zustand.ungelesen).toBe(0);
  });

  it('Darüberfahren und Fokus halten offen; danach läuft der Rest', async () => {
    hostRendern();
    dienst.melde(m({ titel: 'halten' }));
    await lass();
    const karte = screen.getByText('halten').closest('article')!;
    await lass(4000);
    fireEvent.pointerEnter(karte);
    await lass(60_000);
    expect(screen.getByText('halten')).toBeInTheDocument();
    fireEvent.pointerLeave(karte);
    await lass(1500);
    expect(screen.getByText('halten')).toBeInTheDocument();
    await lass(1500 + AUS_MS + 20);
    expect(screen.queryByText('halten')).not.toBeInTheDocument();

    dienst.melde(m({ titel: 'fokus' }));
    await lass();
    const k2 = screen.getByText('fokus').closest('article')!;
    fireEvent.focusIn(k2.querySelector('button.os-meldung-haupt')!);
    await lass(60_000);
    expect(screen.getByText('fokus')).toBeInTheDocument();
  });

  it('ein verborgener Tab zählt die Zeit nicht: die Meldung wartet auf die Rückkehr', async () => {
    hostRendern();
    dienst.melde(m({ titel: 'wartet' }));
    await lass(1000);
    sichtbar = false;
    document.dispatchEvent(new Event('visibilitychange'));
    await lass(60_000);
    expect(screen.getByText('wartet')).toBeInTheDocument();
    sichtbar = true;
    document.dispatchEvent(new Event('visibilitychange'));
    await lass(2000);
    expect(screen.getByText('wartet')).toBeInTheDocument();
    await lass(5000 + AUS_MS + 20);
    expect(screen.queryByText('wartet')).not.toBeInTheDocument();
  });

  it('höchstens drei sichtbar, der Rest wartet („+N weitere“) und rückt nach', async () => {
    hostRendern();
    for (let i = 1; i <= 5; i++) {
      await lass(10);
      dienst.melde(m({ titel: `T${i}` }));
    }
    await lass();
    expect(document.querySelectorAll('article.os-meldung')).toHaveLength(3);
    expect(screen.getByText('+2 weitere in der Glocke')).toBeInTheDocument();
    await lass(6000 + AUS_MS + 50);
    expect(document.querySelectorAll('article.os-meldung').length).toBeGreaterThan(0);
    expect(screen.queryByText(/weitere in der Glocke/)).not.toBeInTheDocument();
  });

  it('Klick öffnet das Ziel (richtiges Fenster nach vorn), liest und schließt; Aktionsknopf „Freigabe öffnen“ ebenso', async () => {
    hostRendern();
    const ziel = { ziel: 'nativ:agent' };
    dienst.melde(m({ quelle: 'freigabe', stufe: 'hoch', titel: 'Freigabe: Pod löschen', text: 'Risiko mittel', ziel, aktionen: [{ id: 'o', text: 'Freigabe öffnen', ziel }] }));
    await lass();
    fireEvent.click(screen.getByRole('button', { name: 'Freigabe öffnen' }));
    expect(geoeffnet).toEqual([{ ziel: 'nativ:agent', vorn: true }]);
    await lass();
    expect(dienst.zustand.ungelesen).toBe(0);
    await lass(AUS_MS + 20);
    expect(screen.queryByText('Freigabe: Pod löschen')).not.toBeInTheDocument();

    dienst.melde(m({ titel: 'Mail da', ziel: { ziel: 'seite:mail-inbox' } }));
    await lass();
    fireEvent.click(screen.getByText('Mail da'));
    expect(geoeffnet.at(-1)).toEqual({ ziel: 'seite:mail-inbox', vorn: true });
  });

  it('Tastatur: Enter/Leertaste auf dem Haupttext (echte Knöpfe), Esc schließt die Meldung mit dem Fokus', async () => {
    hostRendern();
    dienst.melde(m({ titel: 'taste' }));
    await lass();
    const haupt = screen.getByText('taste').closest('button')!;
    expect(haupt.tagName).toBe('BUTTON');
    haupt.focus();
    fireEvent.keyDown(haupt, { key: 'Escape' });
    await lass(AUS_MS + 20);
    expect(screen.queryByText('taste')).not.toBeInTheDocument();
  });

  it('Zusammenfassung zeigt „3 neue Mails“ und startet die Uhr neu', async () => {
    hostRendern();
    const mail = (id: string): MeldungEingabe => ({ quelle: 'mail', schluessel: id, stufe: 'normal', titel: `Neue Mail von ${id}`, text: id, sammeln: (k) => `${k} neue Mails` });
    dienst.melde(mail('a'));
    await lass(5000);
    dienst.melde(mail('b'));
    dienst.melde(mail('c'));
    await lass();
    expect(screen.getByText('3 neue Mails')).toBeInTheDocument();
    await lass(5000);
    expect(screen.getByText('3 neue Mails')).toBeInTheDocument();
    await lass(1000 + AUS_MS + 20);
    expect(screen.queryByText('3 neue Mails')).not.toBeInTheDocument();
  });

  it('Nicht stören: kein Toast, die Glocke zählt', async () => {
    hostRendern();
    aendereEinstellungen((e) => ({ ...e, nichtStoeren: { ...e.nichtStoeren, manuell: true } }));
    dienst.melde(m({ titel: 'still' }));
    await lass();
    expect(screen.queryByText('still')).not.toBeInTheDocument();
    expect(dienst.zustand.ungelesen).toBe(1);
  });

  it('Mail- und Agent-Text tragen data-privat (verschwindet im Demo-Modus)', async () => {
    hostRendern();
    dienst.melde(m({ quelle: 'mail', titel: 'Neue Mail von Alex', text: 'Betreff geheim' }));
    await lass();
    expect(screen.getByText('Betreff geheim')).toHaveAttribute('data-privat', 'privat');
  });
});

describe('Reduzierte Bewegung', () => {
  it('CSS: mit prefers-reduced-motion nur Einblenden (Deckkraft), kein Gleiten', () => {
    const css = readFileSync(join(__dirname, '..', '..', 'src', 'styles', 'os-meldungen.css'), 'utf8');
    const i = css.indexOf('@media (prefers-reduced-motion: reduce)');
    expect(i).toBeGreaterThan(0);
    const block = css.slice(i, css.indexOf('}\n\n}', i) + 3);
    expect(block).toContain('animation-name: os-meldung-ein-ruhig');
    expect(block).toContain('transition-property: opacity');
    expect(block).toContain('transform: none');
    // die ruhige Einblendung bewegt nichts
    const ruhig = /@keyframes os-meldung-ein-ruhig\s*\{([^}]*\{[^}]*\})/.exec(css)?.[1] ?? '';
    expect(ruhig).toContain('opacity: 0');
    expect(ruhig).not.toContain('transform');
  });
});

describe('Glocke', () => {
  it('zeigt ungelesene, öffnet den Verlauf als Dialog, Eintrag öffnet das Ziel, Alle gelesen, Esc bringt den Fokus zurück', async () => {
    render(() => <MeldungenGlocke />);
    dienst.melde(m({ titel: 'eins', ziel: { ziel: 'seite:kalender' } }));
    dienst.melde(m({ titel: 'zwei', stufe: 'kritisch', quelle: 'stoerung' }));
    await lass();
    const knopf = screen.getByRole('button', { name: /Meldungen, 2 ungelesen/ });
    expect(knopf).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(knopf);
    await lass();
    const dialog = screen.getByRole('dialog', { name: 'Verlauf der Meldungen' });
    expect(knopf).toHaveAttribute('aria-expanded', 'true');
    expect(within(dialog).getByText(/eins/)).toBeInTheDocument();
    expect(within(dialog).getByText(/zwei/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /eins/ }));
    expect(geoeffnet).toContainEqual({ ziel: 'seite:kalender', vorn: true });
    expect(dienst.zustand.ungelesen).toBe(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(knopf);
    await lass();
    fireEvent.click(screen.getByRole('button', { name: 'Alle gelesen' }));
    expect(dienst.zustand.ungelesen).toBe(0);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(knopf);
  });

  it('leer: erklärt, was hier erscheint', async () => {
    render(() => <MeldungenGlocke />);
    fireEvent.click(screen.getByRole('button', { name: /Meldungen/ }));
    await lass();
    expect(screen.getByText(/Keine Meldungen/)).toBeInTheDocument();
  });

  it('der Verlauf hängt an der Shell, nicht in der Glocke (dort schrumpfte seine Breite auf wenige Pixel)', async () => {
    render(() => (
      <div data-shell>
        <MeldungenGlocke />
      </div>
    ));
    fireEvent.click(screen.getByRole('button', { name: /Meldungen/ }));
    await lass();
    const tafel = screen.getByRole('dialog', { name: /Verlauf der Meldungen/ });
    expect(tafel.closest('.os-glocke')).toBeNull();
    expect(tafel.closest('[data-shell]')).not.toBeNull();
  });

  it('Nicht stören im Verlauf schaltet und zeigt sich im Namen der Glocke', async () => {
    render(() => <MeldungenGlocke />);
    fireEvent.click(screen.getByRole('button', { name: /Meldungen/ }));
    await lass();
    const nm = screen.getByRole('button', { name: 'Nicht stören' });
    expect(nm).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(nm);
    await lass();
    expect(screen.getByRole('button', { name: 'Nicht stören' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Nicht stören ist an/ })).toBeInTheDocument();
  });
});

describe('Handy: gemeinsamer Stapel mit „Agent zeigt dir …“', () => {
  it('schmal und mit Container der Agent-Hinweise stehen die Toasts in ihm; sonst eigener Container', async () => {
    const stapel = document.createElement('div');
    stapel.className = 'os-mitteilungen';
    document.body.append(stapel);
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('max-width: 767px'), addEventListener: () => {}, removeEventListener: () => {} }));
    hostRendern();
    dienst.melde(m({ titel: 'im Stapel' }));
    await lass();
    expect(stapel.querySelector('.os-meldungen')).not.toBeNull();
    expect(within(stapel).getByText('im Stapel')).toBeInTheDocument();
    stapel.remove();
    vi.unstubAllGlobals();
  });
});
