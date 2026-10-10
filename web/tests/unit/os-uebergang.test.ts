/**
 * lib/os/uebergang.ts — Fenster fliegen ins Dock und zurück, Schließen klingt aus.
 * jsdom kann keine Web Animations: dort muss die Änderung sofort passieren; mit einer (gefälschten) animate()
 * erst, wenn die Animation endet.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BLICK_NACH_MS, _herkunft, ausHerkunft, ausklingen, herkunftMerken, imBlickHalten, inDenBlick, insDock } from '~/lib/os/uebergang';

function aufbau(): { fenster: HTMLElement; dock: HTMLElement } {
  document.body.innerHTML = `
    <div class="os-platz-an"><section data-fenster="seite:kalender"></section></div>
    <button data-kontext="dock-fenster:seite:kalender"></button>`;
  const fenster = document.querySelector<HTMLElement>('[data-fenster]')!;
  const dock = document.querySelector<HTMLElement>('[data-kontext]')!;
  const rect = (x: number, y: number, w: number, h: number) => ({ left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, x, y, toJSON: () => ({}) }) as DOMRect;
  fenster.getBoundingClientRect = () => rect(100, 100, 800, 600);
  dock.getBoundingClientRect = () => rect(480, 900, 40, 40);
  return { fenster, dock };
}

/** animate()-Attrappe: merkt sich die Keyframes, endet erst auf `fertig()` */
function animierbar(el: HTMLElement) {
  const a: { onfinish: (() => void) | null; oncancel: (() => void) | null; frames?: Keyframe[] } = { onfinish: null, oncancel: null };
  (el as unknown as { animate: unknown }).animate = vi.fn((frames: Keyframe[]) => {
    a.frames = frames;
    return a;
  });
  return { a, fertig: () => a.onfinish?.() };
}

afterEach(() => {
  document.body.innerHTML = '';
  _herkunft.clear();
  vi.useRealTimers();
});

describe('ohne Animation (jsdom)', () => {
  it('minimiert und schließt sofort', () => {
    aufbau();
    const m = vi.fn();
    const s = vi.fn();
    insDock('seite:kalender', m);
    ausklingen('seite:kalender', s);
    expect(m).toHaveBeenCalledOnce();
    expect(s).toHaveBeenCalledOnce();
  });

  it('ohne Fenster im DOM: sofort', () => {
    const m = vi.fn();
    insDock('gibt-es-nicht', m);
    expect(m).toHaveBeenCalledOnce();
  });
});

describe('mit Animation', () => {
  it('fliegt Mitte auf Mitte ins Dock-Symbol und ändert den Zustand erst danach — genau einmal', () => {
    vi.useFakeTimers();
    const { fenster } = aufbau();
    const { a, fertig } = animierbar(fenster);
    const m = vi.fn();
    insDock('seite:kalender', m);
    expect(m).not.toHaveBeenCalled();
    // Mitte Fenster (500, 400) → Mitte Symbol (500, 920); Maßstab = min(40/800, 40/600) = 0.05
    expect(String(a.frames![1].transform)).toBe('translate(0px, 520px) scale(0.05)');
    fertig();
    expect(m).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(1000); // die Sicherung feuert nicht ein zweites Mal
    expect(m).toHaveBeenCalledOnce();
  });

  it('verschluckt der Browser die Animation, greift die Sicherung', () => {
    vi.useFakeTimers();
    const { fenster } = aufbau();
    animierbar(fenster);
    const s = vi.fn();
    ausklingen('seite:kalender', s);
    expect(s).not.toHaveBeenCalled();
    vi.advanceTimersByTime(400);
    expect(s).toHaveBeenCalledOnce();
  });

  it('Wiederherstellen wächst aus dem gemerkten Dock-Symbol auf, nur einmal', () => {
    const { fenster } = aufbau();
    const { a } = animierbar(fenster);
    herkunftMerken('seite:kalender');
    ausHerkunft('seite:kalender', fenster);
    expect(String(a.frames![0].transform)).toBe('translate(0px, 520px) scale(0.05)');
    expect(a.frames![1].transform).toBe('none');
    (fenster.animate as ReturnType<typeof vi.fn>).mockClear();
    ausHerkunft('seite:kalender', fenster); // ein normales Neuzeichnen später: keine Animation mehr
    expect(fenster.animate).not.toHaveBeenCalled();
  });

  it('holt ein wiederhergestelltes Fenster unterhalb des Sichtbaren erst in den Blick', () => {
    const { fenster } = aufbau();
    animierbar(fenster);
    const tief = { left: 100, top: 3300, width: 800, height: 600, right: 900, bottom: 3900, x: 100, y: 3300, toJSON: () => ({}) } as DOMRect;
    fenster.getBoundingClientRect = () => tief;
    const blick = vi.fn();
    fenster.scrollIntoView = blick;
    herkunftMerken('seite:kalender');
    ausHerkunft('seite:kalender', fenster);
    expect(blick).toHaveBeenCalledWith({ block: 'nearest' });
  });
});

describe('inDenBlick (Fokus holt das Fenster in den Blick)', () => {
  const rect = (top: number) => ({ left: 0, top, width: 700, height: 400, right: 700, bottom: top + 400, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;

  it('scrollt ein Fenster weit unterhalb, ein sichtbares nicht (live 04.10.: Verlauf 4200 px tief)', () => {
    const { fenster } = aufbau();
    const blick = vi.fn();
    fenster.scrollIntoView = blick;
    fenster.getBoundingClientRect = () => rect(4249);
    inDenBlick('seite:kalender');
    expect(blick).toHaveBeenCalledTimes(1);
    blick.mockClear();
    fenster.getBoundingClientRect = () => rect(300);
    inDenBlick('seite:kalender');
    expect(blick).not.toHaveBeenCalled();
  });

  it('springt weite Wege sofort, weich nur kurze (live 04.10.: smooth bewegte im Hintergrund-Tab nichts)', () => {
    const { fenster } = aufbau();
    const blick = vi.fn();
    fenster.scrollIntoView = blick;
    fenster.getBoundingClientRect = () => rect(4249);
    inDenBlick('seite:kalender');
    expect(blick).toHaveBeenLastCalledWith({ block: 'nearest', behavior: 'auto' });
    fenster.getBoundingClientRect = () => rect(innerHeight + 10);
    inDenBlick('seite:kalender');
    expect(blick.mock.calls.at(-1)?.[0]?.block).toBe('nearest');
  });

  it('holt das Fenster zurück, wenn Apps darüber nachladen, und lässt los, sobald selbst gescrollt wird', () => {
    vi.useFakeTimers();
    try {
      const { fenster } = aufbau();
      let oben = 4249;
      const blick = vi.fn(() => { oben = 300; });
      fenster.scrollIntoView = blick;
      fenster.getBoundingClientRect = () => rect(oben);
      imBlickHalten('seite:kalender');
      vi.advanceTimersByTime(0);
      expect(blick).toHaveBeenCalledTimes(1);
      oben = 3966; // ITSM-Tabelle darüber ist gewachsen
      vi.advanceTimersByTime(BLICK_NACH_MS[1]);
      expect(blick).toHaveBeenCalledTimes(2);
      dispatchEvent(new Event('wheel'));
      oben = 3000;
      vi.advanceTimersByTime(BLICK_NACH_MS[BLICK_NACH_MS.length - 1]);
      expect(blick).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
