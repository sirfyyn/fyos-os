/**
 * lib/os/ansicht.ts — die OS-Ansicht gerade halten.
 * Beobachtung: „manchmal verschiebt sich die OS-Ansicht und verkeilt sich dann.“ Ursache: scrollIntoView rollt auch den
 * `overflow: hidden`-Bereich der Bildschirme waagrecht; das Band bleibt danach verrutscht.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { geradeRuecken, osAnsichtRuecken, zugFestgefahren } from '~/lib/os/ansicht';
import { inDenBlick } from '~/lib/os/uebergang';

afterEach(() => {
  document.body.innerHTML = '';
});

/** Ein Element mit frei beschreibbarer Rollposition (jsdom rechnet keine). */
function rollbar(el: HTMLElement, links = 0, oben = 0): HTMLElement {
  let l = links;
  let o = oben;
  Object.defineProperty(el, 'scrollLeft', { get: () => l, set: (v: number) => { l = v; }, configurable: true });
  Object.defineProperty(el, 'scrollTop', { get: () => o, set: (v: number) => { o = v; }, configurable: true });
  return el;
}

describe('geradeRuecken', () => {
  it('setzt verrutschte Ziele auf null und zählt sie', () => {
    const a = { scrollLeft: 640, scrollTop: 0 };
    const b = { scrollLeft: 0, scrollTop: 0 };
    const c = { scrollLeft: 0, scrollTop: 12 };
    expect(geradeRuecken([a, b, c, null, undefined])).toBe(2);
    expect(a).toEqual({ scrollLeft: 0, scrollTop: 0 });
    expect(c).toEqual({ scrollLeft: 0, scrollTop: 0 });
  });

  it('fasst Gerades nicht an (kein Schreibzugriff, kein Scroll-Ereignis)', () => {
    const schreib = vi.fn();
    const z = { get scrollLeft() { return 0; }, set scrollLeft(_v: number) { schreib(); }, get scrollTop() { return 0; }, set scrollTop(_v: number) { schreib(); } };
    expect(geradeRuecken([z])).toBe(0);
    expect(schreib).not.toHaveBeenCalled();
  });
});

describe('zugFestgefahren (verwaister Wisch-Versatz)', () => {
  it('ohne Versatz nie', () => {
    expect(zugFestgefahren(0, 0, 99_999)).toBe(false);
  });
  it('ohne Finger nach kurzer Stille', () => {
    expect(zugFestgefahren(180, 0, 300)).toBe(false);
    expect(zugFestgefahren(180, 0, 800)).toBe(true);
  });
  it('ein ruhender Finger darf länger halten, ein verlorenes pointerup nicht ewig', () => {
    expect(zugFestgefahren(180, 1, 2000)).toBe(false);
    expect(zugFestgefahren(180, 1, 6000)).toBe(true);
  });
});

describe('osAnsichtRuecken (Bereich, Shell, Seite)', () => {
  it('rückt den Bereich der Bildschirme und die Shell zurück, liefert die Zahl', () => {
    document.body.innerHTML = '<div data-shell><div data-os-bereich></div></div><div id="anderes"></div>';
    const shell = rollbar(document.querySelector<HTMLElement>('[data-shell]')!);
    const bereich = rollbar(document.querySelector<HTMLElement>('[data-os-bereich]')!, 640);
    const anderes = rollbar(document.querySelector<HTMLElement>('#anderes')!, 55);
    expect(osAnsichtRuecken()).toBe(1);
    expect(bereich.scrollLeft).toBe(0);
    expect(shell.scrollLeft).toBe(0);
    expect(anderes.scrollLeft).toBe(55); // fremde Rollflächen bleiben unberührt
    expect(osAnsichtRuecken()).toBe(0);
  });
});

describe('Fokus holt ein Fenster in den Blick, ohne das Band zu verschieben', () => {
  it('scrollIntoView rollt den Bereich um eine Bildschirmbreite — inDenBlick stellt ihn zurück', () => {
    document.body.innerHTML = `
      <div data-os-bereich><div class="os-platz-an"><section data-fenster="seite:tickets"></section></div></div>`;
    const bereich = rollbar(document.querySelector<HTMLElement>('[data-os-bereich]')!);
    const fenster = document.querySelector<HTMLElement>('[data-fenster]')!;
    fenster.getBoundingClientRect = () => ({ left: 2000, top: 3300, width: 900, height: 600, right: 2900, bottom: 3900, x: 2000, y: 3300, toJSON: () => ({}) }) as DOMRect;
    // Das Band gleitet noch: das Fenster liegt rechts außerhalb, der Browser rollt den Bereich dorthin  (Fehlerbild)
    fenster.scrollIntoView = vi.fn(() => { bereich.scrollLeft = 2000; });
    inDenBlick('seite:tickets');
    expect(fenster.scrollIntoView).toHaveBeenCalledTimes(1);
    expect(bereich.scrollLeft).toBe(0);
  });
});
