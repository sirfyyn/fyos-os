/**
 * Dialogdienst (lib/ui/dialoge.ts) + Host (components/ui/DialogHost.tsx).
 * Der System-WebView der Desktop-App zeigt keine nativen Dialoge: alles muss durch den eigenen Host gehen.
 */
import { cleanup, fireEvent, render, screen } from '@solidjs/testing-library';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { DialogHost } from '../../src/components/ui/DialogHost';
import { bestaetigen, dialogeOffen, dialogeZuruecksetzen, eingabe, meldung } from '../../src/lib/ui/dialoge';

let nativ: { confirm: ReturnType<typeof vi.fn>; alert: ReturnType<typeof vi.fn>; prompt: ReturnType<typeof vi.fn> };

beforeEach(() => {
  nativ = { confirm: vi.fn(() => true), alert: vi.fn(), prompt: vi.fn(() => 'x') };
  vi.stubGlobal('confirm', nativ.confirm);
  vi.stubGlobal('alert', nativ.alert);
  vi.stubGlobal('prompt', nativ.prompt);
  window.confirm = nativ.confirm as never;
  window.alert = nativ.alert as never;
  window.prompt = nativ.prompt as never;
});
afterEach(() => {
  dialogeZuruecksetzen();
  cleanup();
  vi.unstubAllGlobals();
});

const taste = (key: string, ziel?: Element) => fireEvent.keyDown(ziel ?? document.activeElement ?? document.body, { key });

it('bestaetigen: OK löst mit true auf, Abbrechen mit false, kein nativer Aufruf', async () => {
  render(() => <DialogHost />);
  const p = bestaetigen({ titel: 'Schließen?', text: '3 Vorgänge', ok: 'Ja' });
  const dlg = await screen.findByRole('dialog');
  expect(dlg.getAttribute('aria-modal')).toBe('true');
  expect(dlg.getAttribute('aria-labelledby')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Ja' }));
  await expect(p).resolves.toBe(true);
  expect(screen.queryByRole('dialog')).toBeNull();

  const q = bestaetigen({ titel: 'Nochmal?' });
  await screen.findByRole('dialog');
  fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
  await expect(q).resolves.toBe(false);
  expect(nativ.confirm).not.toHaveBeenCalled();
  expect(nativ.alert).not.toHaveBeenCalled();
  expect(nativ.prompt).not.toHaveBeenCalled();
});

it('Esc bricht ab (bestaetigen false, eingabe null, meldung schließt)', async () => {
  render(() => <DialogHost />);
  const a = bestaetigen({ titel: 'A' });
  await screen.findByRole('dialog');
  taste('Escape');
  await expect(a).resolves.toBe(false);

  const b = eingabe({ titel: 'B', wert: 'abc' });
  await screen.findByRole('dialog');
  taste('Escape');
  await expect(b).resolves.toBeNull();

  const c = meldung({ titel: 'C' });
  await screen.findByRole('dialog');
  taste('Escape');
  await expect(c).resolves.toBeUndefined();
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('Enter bestätigt (Rückfrage) und übernimmt die Eingabe', async () => {
  render(() => <DialogHost />);
  const a = bestaetigen({ titel: 'A' });
  await screen.findByRole('dialog');
  // Fokus liegt auf dem OK-Knopf: Enter löst dessen eigenen Klick aus (jsdom: Klick simulieren)
  fireEvent.keyDown(document.body, { key: 'Enter' });
  await expect(a).resolves.toBe(true);

  const e = eingabe({ titel: 'Name', wert: 'alt' });
  const feld = (await screen.findByRole('textbox')) as HTMLInputElement;
  expect(document.activeElement).toBe(feld);
  expect(feld.value).toBe('alt');
  fireEvent.input(feld, { target: { value: 'neu' } });
  fireEvent.keyDown(feld, { key: 'Enter' });
  await expect(e).resolves.toBe('neu');
});

it('gefährliche Rückfrage: Fokus auf Abbrechen, Enter daneben bestätigt nicht', async () => {
  render(() => <DialogHost />);
  const p = bestaetigen({ titel: 'Löschen?', gefaehrlich: true });
  const dlg = await screen.findByRole('alertdialog');
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Abbrechen' }));
  fireEvent.keyDown(dlg, { key: 'Enter' });
  expect(dialogeOffen()).toBe(1);
  fireEvent.click(screen.getByRole('button', { name: 'Löschen' }));
  await expect(p).resolves.toBe(true);
});

it('eingabe: pruefen hält den Dialog offen und zeigt den Fehler', async () => {
  render(() => <DialogHost />);
  const p = eingabe({ titel: 'Datum', wert: 'x', pruefen: (w) => (/^\d+$/.test(w) ? null : 'Nur Ziffern') });
  const feld = (await screen.findByRole('textbox')) as HTMLInputElement;
  fireEvent.keyDown(feld, { key: 'Enter' });
  expect((await screen.findByRole('alert')).textContent).toBe('Nur Ziffern');
  expect(dialogeOffen()).toBe(1);
  fireEvent.input(feld, { target: { value: '42' } });
  fireEvent.keyDown(feld, { key: 'Enter' });
  await expect(p).resolves.toBe('42');
});

it('Warteschlange: nacheinander, in Reihenfolge, immer nur einer sichtbar', async () => {
  render(() => <DialogHost />);
  const erste = bestaetigen({ titel: 'Erste' });
  const zweite = bestaetigen({ titel: 'Zweite' });
  const dritte = meldung({ titel: 'Dritte' });
  expect(dialogeOffen()).toBe(3);
  expect((await screen.findByRole('dialog')).textContent).toContain('Erste');
  expect(screen.getAllByRole('dialog')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Bestätigen' }));
  await expect(erste).resolves.toBe(true);
  await screen.findByText('Zweite');
  taste('Escape');
  await expect(zweite).resolves.toBe(false);
  await screen.findByText('Dritte');
  fireEvent.click(screen.getByRole('button', { name: 'OK' }));
  await expect(dritte).resolves.toBeUndefined();
  expect(dialogeOffen()).toBe(0);
});

it('Fokus: Tab bleibt im Dialog, danach kehrt der Fokus zurück', async () => {
  render(() => <button>Auslöser</button>);
  render(() => <DialogHost />);
  const ausloeser = screen.getByRole('button', { name: 'Auslöser' });
  ausloeser.focus();
  const p = bestaetigen({ titel: 'Frage' });
  const dlg = await screen.findByRole('dialog');
  const ok = screen.getByRole('button', { name: 'Bestätigen' });
  const abbrechen = screen.getByRole('button', { name: 'Abbrechen' });
  expect(document.activeElement).toBe(ok);
  taste('Tab'); // letztes Element → wieder zum ersten
  expect(document.activeElement).toBe(abbrechen);
  abbrechen.focus();
  fireEvent.keyDown(abbrechen, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(ok);
  expect(dlg.contains(document.activeElement)).toBe(true);
  taste('Escape');
  await p;
  await vi.waitFor(() => expect(document.activeElement).toBe(ausloeser));
});

it('Klick auf den Hintergrund bricht ab', async () => {
  render(() => <DialogHost />);
  const p = bestaetigen({ titel: 'Frage' });
  const dlg = await screen.findByRole('dialog');
  fireEvent.mouseDown(dlg.parentElement!);
  await expect(p).resolves.toBe(false);
});

it('meldung zeigt langen Text und Liste scrollbar, ARIA-Rolle nach Art', async () => {
  render(() => <DialogHost />);
  const fehler = Array.from({ length: 40 }, (_, i) => `PRB-${i}: HTTP 500`);
  const p = meldung({ titel: 'Stapel', text: 'a\nb', details: fehler, detailsTitel: 'Fehlgeschlagen', art: 'fehler' });
  const dlg = await screen.findByRole('alertdialog');
  expect(dlg.querySelectorAll('[data-dialog-details] li')).toHaveLength(40);
  expect(dlg.querySelector('[data-dialog-details]')!.className).toContain('overflow-y-auto');
  expect(screen.queryByRole('button', { name: 'Abbrechen' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'OK' }));
  await p;
});

it('ohne Host (Server) wird sicher beantwortet statt nativ gefragt', async () => {
  const doc = globalThis.document;
  // @ts-expect-error Server simulieren
  delete globalThis.document;
  try {
    await expect(bestaetigen({ titel: 'x' })).resolves.toBe(false);
    await expect(eingabe({ titel: 'x' })).resolves.toBeNull();
    await expect(meldung({ titel: 'x' })).resolves.toBeUndefined();
  } finally {
    globalThis.document = doc;
  }
  expect(nativ.confirm).not.toHaveBeenCalled();
});
