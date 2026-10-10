/**
 * Ziehen und Ablegen im OS (lib/os/ziehen.ts): eine Sprache für Fenster, Flächen und Dinge; die Ziele
 * im Dock verstehen sie, sagen vorher, was passiert, und springen beim Verweilen auf.
 */
import { fireEvent, render, screen } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Dock, { type DockProps } from '~/components/os/Dock';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import {
  VERWEILEN_MS, WARTEN_MS, _wartend, ablageZiel, aktuellerZug, frageZu, gutArt, gutLesen, gutSetzen, wasPassiert, zugEndet,
  zugHinweis, zustellen, zustellungAbholen,
} from '~/lib/os/ziehen';

/** jsdom hat kein DataTransfer: ein schlichtes Gegenstück mit denselben Feldern. */
class Zug {
  daten = new Map<string, string>();
  effectAllowed = 'all';
  dropEffect = 'none';
  get types(): string[] {
    return [...this.daten.keys()];
  }
  setData(t: string, v: string) {
    this.daten.set(t.toLowerCase(), v);
  }
  getData(t: string) {
    return this.daten.get(t.toLowerCase()) ?? '';
  }
  setDragImage() {}
}
const dt = () => new Zug() as unknown as DataTransfer;

beforeEach(() => {
  registriereFlaechen({ dinge: { notiz: { name: 'Notiz', pfad: '/notizen/' }, termin: { name: 'Termin', pfad: '/kalender/' } } });
});

afterEach(() => {
  registerZuruecksetzen();
  zugEndet();
  _wartend.clear();
  vi.useRealTimers();
});

describe('Ziehsprache', () => {
  it('Fenster, Fläche und Ding hin und zurück', () => {
    for (const [gut, art] of [
      [{ art: 'fenster', id: 'seite:kalender' }, 'fenster'],
      [{ art: 'flaeche', id: 'app:haus__favoriten' }, 'flaeche'],
      [{ art: 'ding', typ: 'notiz', id: 'n-4133', label: 'Kameras' }, 'notiz'],
    ] as const) {
      const d = dt();
      gutSetzen(d, gut);
      expect(gutArt(d)).toBe(art);
      expect(gutLesen(d)).toEqual(gut);
    }
  });

  it('Fenster ziehen heißt verschieben, Dinge kopieren', () => {
    const f = dt();
    gutSetzen(f, { art: 'fenster', id: 'x' });
    expect(f.effectAllowed).toBe('move');
    const d = dt();
    gutSetzen(d, { art: 'ding', typ: 'termin', id: 't1' });
    expect(d.effectAllowed).toBe('copyMove');
  });

  it('versteht auch eine nackte fyos://-Adresse (Karte einer Seite) und trägt den Titel mit', () => {
    const alt = dt();
    alt.setData('text/plain', 'fyos://notiz/n-12');
    expect(gutLesen(alt)).toEqual({ art: 'ding', typ: 'notiz', id: 'n-12' });

    const mit = dt();
    gutSetzen(mit, { art: 'ding', typ: 'termin', id: 'e9' }, 'Zahnarzt');
    expect(gutArt(mit)).toBe('termin');
    expect(gutLesen(mit)).toEqual({ art: 'ding', typ: 'termin', id: 'e9', label: 'Zahnarzt' });
  });

  it('nur registrierte Typen sind Dinge', () => {
    const d = dt();
    d.setData('text/plain', 'fyos://unbekannt/1');
    expect(gutLesen(d)).toBeNull();
  });

  it('Fremdes und Unbekanntes ist kein Gut', () => {
    const d = dt();
    d.setData('text/plain', 'einfach Text');
    expect(gutLesen(d)).toBeNull();
    expect(gutArt(d)).toBeNull();
    const boese = dt();
    boese.setData('text/plain', 'fyos://constructor/abc');
    expect(gutLesen(boese)).toBeNull();
  });

  it('sagt, was beim Loslassen passiert', () => {
    expect(wasPassiert('fenster', 'bildschirm', 'Haus')).toBe('Auf „Haus“ verschieben');
    expect(wasPassiert('notiz', 'bildschirm', 'Haus')).toBe('Auf „Haus“ öffnen');
    expect(wasPassiert('notiz', 'schreibtisch')).toBe('Notiz öffnen');
    expect(wasPassiert('flaeche', 'neu')).toBe('Auf neuem Bildschirm öffnen');
    expect(wasPassiert('termin', 'agent')).toBe('Agent dazu fragen');
    // Der Startbildschirm ist ein Launcher: dort liegt nichts ab
    expect(wasPassiert('fenster', 'start')).toBeNull();
    expect(wasPassiert(null, 'agent')).toBeNull();
  });

  it('formuliert die Frage an den Agenten mit Kennung und Titel', () => {
    expect(frageZu({ art: 'ding', typ: 'notiz', id: 'n-1', label: 'Kamera aus' })).toContain('Notiz n-1 („Kamera aus“)');
    expect(frageZu({ art: 'fenster', id: 'seite:kalender' }, 'Kalender')).toContain('„Kalender“');
  });
});

describe('Ablageziel', () => {
  it('nimmt an, zeigt den Hinweis, legt ab und räumt auf', () => {
    const ablegen = vi.fn();
    const an = vi.fn();
    const z = ablageZiel({ ziel: 'bildschirm', name: () => 'Haus', ablegen, an });
    const el = document.createElement('button');
    document.body.appendChild(el);
    const d = dt();
    gutSetzen(d, { art: 'fenster', id: 'seite:kalender' });
    const ev = (typ: string) => Object.assign(new Event(typ, { cancelable: true, bubbles: true }), { dataTransfer: d }) as unknown as DragEvent;

    const over = ev('dragover');
    el.addEventListener('dragover', (e) => z.onDragOver(e as DragEvent));
    el.dispatchEvent(over);
    expect(over.defaultPrevented).toBe(true);
    expect(d.dropEffect).toBe('move');
    expect(an).toHaveBeenLastCalledWith(true);
    expect(zugHinweis()?.text).toBe('Auf „Haus“ verschieben');

    const drop = ev('drop');
    el.addEventListener('drop', (e) => z.onDrop(e as DragEvent));
    el.dispatchEvent(drop);
    expect(ablegen).toHaveBeenCalledWith({ art: 'fenster', id: 'seite:kalender' });
    expect(an).toHaveBeenLastCalledWith(false);
    expect(zugHinweis()).toBeNull();
    expect(aktuellerZug()).toBeNull();
    el.remove();
  });

  it('legt nicht ab, was es beim Darüberfahren nicht angenommen hätte', () => {
    const ablegen = vi.fn();
    const z = ablageZiel({ ziel: 'bildschirm', annehmen: () => false, ablegen });
    const d = dt();
    gutSetzen(d, { art: 'flaeche', id: 'seite:kalender' });
    const el = document.createElement('div');
    el.addEventListener('drop', (e) => z.onDrop(e as DragEvent));
    el.dispatchEvent(Object.assign(new Event('drop', { cancelable: true }), { dataTransfer: d }));
    expect(ablegen).not.toHaveBeenCalled();
  });
});

describe('Dock als Ziel', () => {
  function dock(extra: Partial<DockProps> = {}) {
    const p: DockProps = {
      bildschirme: [{ index: 1, name: 'Arbeit' }, { index: 2, name: 'Haus' }],
      aktiv: 1,
      onWechseln: vi.fn(),
      onNeuerBildschirm: vi.fn(),
      startOffen: false,
      onStart: vi.fn(),
      fenster: [{ id: 'seite:kalender', titel: 'Kalender', min: false }],
      fokus: null,
      onFenster: vi.fn(),
      agent: false,
      onAgent: vi.fn(),
      onAblegen: vi.fn(),
      onAblegenNeu: vi.fn(),
      onAgentAblegen: vi.fn(),
      ...extra,
    };
    render(() => <Dock {...p} />);
    return p;
  }

  it('Objekt auf einen Punkt: dort öffnen; auf „+“: neuer Bildschirm; auf den Agent: Agent fragen', () => {
    const p = dock();
    const objekt = () => {
      const d = dt();
      gutSetzen(d, { art: 'ding', typ: 'notiz', id: 'n-7' });
      return d;
    };
    const haus = screen.getByRole('tab', { name: 'Haus' });
    fireEvent.dragOver(haus, { dataTransfer: objekt() });
    fireEvent.drop(haus, { dataTransfer: objekt() });
    expect(p.onAblegen).toHaveBeenCalledWith(2, { art: 'ding', typ: 'notiz', id: 'n-7' });

    fireEvent.drop(screen.getByRole('button', { name: 'Neuer Bildschirm' }), { dataTransfer: objekt() });
    expect(p.onAblegenNeu).toHaveBeenCalled();

    fireEvent.drop(screen.getByRole('button', { name: 'Agent' }), { dataTransfer: objekt() });
    expect(p.onAgentAblegen).toHaveBeenCalledWith({ art: 'ding', typ: 'notiz', id: 'n-7' });
  });

  it('auf dem Start-Punkt wird nichts abgelegt, aber Verweilen wechselt hin', () => {
    vi.useFakeTimers();
    const p = dock();
    const d = dt();
    gutSetzen(d, { art: 'fenster', id: 'seite:kalender' });
    const start = screen.getByRole('tab', { name: 'Start' });
    fireEvent.dragEnter(start, { dataTransfer: d });
    fireEvent.drop(start, { dataTransfer: d });
    expect(p.onAblegen).not.toHaveBeenCalled();
    fireEvent.dragEnter(start, { dataTransfer: d });
    vi.advanceTimersByTime(VERWEILEN_MS + 10);
    expect(p.onWechseln).toHaveBeenCalledWith(0);
  });

  it('Verlassen vor der Zeit wechselt nicht', () => {
    vi.useFakeTimers();
    const p = dock();
    const d = dt();
    gutSetzen(d, { art: 'flaeche', id: 'seite:kalender' });
    const haus = screen.getByRole('tab', { name: 'Haus' });
    fireEvent.dragEnter(haus, { dataTransfer: d });
    fireEvent.dragLeave(haus, { dataTransfer: d });
    vi.advanceTimersByTime(VERWEILEN_MS + 10);
    expect(p.onWechseln).not.toHaveBeenCalled();
  });

  it('Fenstersymbol lässt sich ziehen (als Fenster)', () => {
    dock();
    const d = dt();
    fireEvent.dragStart(screen.getByRole('button', { name: 'Kalender' }), { dataTransfer: d });
    expect(gutLesen(d)).toEqual({ art: 'fenster', id: 'seite:kalender' });
    expect(aktuellerZug()?.art).toBe('fenster');
  });
});

describe('Zustellung an Seiten im Fenster', () => {
  it('wartet, bis das Fenster geladen ist, und geht dann genau einmal hin', () => {
    zustellen('seite:notizen', { fyosOeffne: { typ: 'notiz', id: 'n-1' } });
    const ziel = { postMessage: vi.fn() } as unknown as Window;
    zustellungAbholen('seite:notizen', ziel);
    zustellungAbholen('seite:notizen', ziel);
    expect(ziel.postMessage).toHaveBeenCalledTimes(1);
    expect(ziel.postMessage).toHaveBeenCalledWith({ fyosOeffne: { typ: 'notiz', id: 'n-1' } }, location.origin);
  });

  it('verfällt nach WARTEN_MS: ein spät geöffnetes Fenster bekommt kein altes Objekt mehr', () => {
    vi.useFakeTimers();
    try {
      zustellen('seite:notizen', { fyosOeffne: { typ: 'notiz', id: 'n-2' } });
      vi.advanceTimersByTime(WARTEN_MS + 1);
      const ziel = { postMessage: vi.fn() } as unknown as Window;
      zustellungAbholen('seite:notizen', ziel);
      expect(ziel.postMessage).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
