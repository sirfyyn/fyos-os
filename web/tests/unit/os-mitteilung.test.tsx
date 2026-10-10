/**
 * Mitteilungen im OS: die Karte (components/os/Mitteilungen.tsx) mit Stapel, Bedienung per Maus und Tastatur,
 * ⋯-Menü, Stumm und Aus mit „Rückgängig“ — und der reine Teil in lib/os/mitteilungen.ts (Prüfung der Nutzlast,
 * Stapel, Zeittext, Einstellung).
 */
import { cleanup, fireEvent, render, screen, within } from '@solidjs/testing-library';
import { createSignal } from 'solid-js';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Mitteilungen, { type Hinweis, type MitteilungenProps } from '~/components/os/Mitteilungen';
import type { Flaeche, FlaechenArt } from '~/lib/os/flaechen';
import { menue, menueZu } from '~/lib/os/menue';
import {
  ANZEIGE_MS, GLEICH_MS, MAX_STAPEL, SPEICHER_SCHLUESSEL, ZEIGT_EREIGNIS, einstellungLesen, einstellungSchreiben, hinzufuegen, istStumm,
  schluesselVon, zeigtPruefen, zeitText, type Mitteilung, type ZeigtDaten,
} from '~/lib/os/mitteilungen';

const F = (id: string, titel: string, gruppe = 'Allgemein', art: FlaechenArt = 'seite'): Flaeche => ({ id, titel, gruppe, art, kuerzel: titel.slice(0, 2).toUpperCase() });
const FLAECHEN: Flaeche[] = [F('app:haus__favoriten', 'Haus', 'Haus', 'hubapp'), F('seite:notizen', 'Notizen', 'Arbeit', 'seite')];
const flaecheVon = (id: string) => FLAECHEN.find((f) => f.id === id);

const zeigt = (extra: Partial<ZeigtDaten> = {}): ZeigtDaten => ({
  ziel: 'app:haus__favoriten',
  app: 'haus__favoriten',
  titel: 'Haus',
  untertitel: 'Wohnzimmer',
  vorschau: 'Drei Lichter sind an, die Heizung läuft.',
  eingabe: null,
  link: null,
  ...extra,
});

let speicher: Map<string, string>;
beforeEach(() => {
  speicher = new Map();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => speicher.get(k) ?? null,
    setItem: (k: string, v: string) => void speicher.set(k, v),
    removeItem: (k: string) => void speicher.delete(k),
  });
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
  vi.setSystemTime(new Date('2030-01-01T10:00:00Z'));
});
afterEach(() => {
  cleanup();
  menueZu();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const lass = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

// ── Der reine Teil ──────────────────────────────────────────────────────────────────────────────

describe('lib/os/mitteilungen', () => {
  it('prüft die Nutzlast: ohne Ziel nichts, Texte gekürzt, Titel fällt auf App und Ziel zurück', () => {
    expect(zeigtPruefen(null)).toBeNull();
    expect(zeigtPruefen('x')).toBeNull();
    expect(zeigtPruefen({ titel: 'ohne Ziel' })).toBeNull();
    expect(zeigtPruefen({ ziel: 'seite:a' })).toMatchObject({ ziel: 'seite:a', titel: 'seite:a', app: null, vorschau: null, eingabe: null });
    expect(zeigtPruefen({ ziel: 'app:a__b', app: 'a__b' })!.titel).toBe('a__b');
    const z = zeigtPruefen({ ziel: 'seite:a', titel: 'x'.repeat(200), vorschau: ' zwei \n  Zeilen ', eingabe: [1] })!;
    expect(z.titel.length).toBe(80);
    expect(z.vorschau).toBe('zwei Zeilen');
    expect(z.eingabe).toBeNull();
  });

  it('der Schlüssel hängt nicht von der Reihenfolge der Eingabefelder ab', () => {
    const a = schluesselVon(zeigt({ eingabe: { a: 1, b: { c: 2, d: 3 } } }));
    const b = schluesselVon(zeigt({ eingabe: { b: { d: 3, c: 2 }, a: 1 } }));
    expect(a).toBe(b);
    expect(a).not.toBe(schluesselVon(zeigt({ eingabe: { a: 2 } })));
  });

  it(`stapelt höchstens ${MAX_STAPEL}, die neueste oben; dieselbe binnen ${GLEICH_MS / 1000} s ersetzt die vorige`, () => {
    const t = Date.now();
    let l: Mitteilung[] = [];
    for (const z of ['seite:a', 'seite:b', 'seite:c', 'seite:d']) l = hinzufuegen(l, zeigt({ ziel: z }), t);
    expect(l.map((m) => m.zeigt.ziel)).toEqual(['seite:d', 'seite:c', 'seite:b']);
    const ersetzt = hinzufuegen(l, zeigt({ ziel: 'seite:c', vorschau: 'neu' }), t + 1000);
    expect(ersetzt.map((m) => m.zeigt.ziel)).toEqual(['seite:c', 'seite:d', 'seite:b']);
    expect(ersetzt[0]!.zeigt.vorschau).toBe('neu');
    const spaeter = hinzufuegen(l, zeigt({ ziel: 'seite:c' }), t + GLEICH_MS + 1);
    // nach Ablauf der Gleichzeit ersetzt sie die ältere nicht mehr
    expect(spaeter.filter((m) => m.zeigt.ziel === 'seite:c')).toHaveLength(2);
    expect(spaeter).toHaveLength(MAX_STAPEL);
  });

  it('Zeittext: jetzt, Minuten, Stunden, gestern', () => {
    const t = 1_000_000_000;
    expect(zeitText(t, t + 10_000)).toBe('jetzt');
    expect(zeitText(t, t + 125_000)).toBe('vor 2 min');
    expect(zeitText(t, t + 3 * 3_600_000)).toBe('vor 3 Std.');
    expect(zeitText(t, t + 30 * 3_600_000)).toBe('gestern');
  });

  it('Einstellung: Vorgabe, Schreiben, Lesen, kaputter Speicher', () => {
    expect(einstellungLesen()).toEqual({ aus: false, stumm_bis: 0 });
    einstellungSchreiben({ aus: true, stumm_bis: 5 });
    expect(einstellungLesen()).toEqual({ aus: true, stumm_bis: 5 });
    speicher.set(SPEICHER_SCHLUESSEL, '{kaputt');
    expect(einstellungLesen()).toEqual({ aus: false, stumm_bis: 0 });
    expect(einstellungLesen({ getItem: () => { throw new Error('gesperrt'); } })).toEqual({ aus: false, stumm_bis: 0 });
    expect(() => einstellungSchreiben({ aus: false, stumm_bis: 0 }, { setItem: () => { throw new Error('voll'); } })).not.toThrow();
  });

  it('stumm ist, wer aus ist oder noch Stummzeit hat', () => {
    expect(istStumm({ aus: true, stumm_bis: 0 }, 100)).toBe(true);
    expect(istStumm({ aus: false, stumm_bis: 200 }, 100)).toBe(true);
    expect(istStumm({ aus: false, stumm_bis: 100 }, 100)).toBe(false);
    expect(istStumm({ aus: false, stumm_bis: 0 }, 100)).toBe(false);
  });

  it('das Ereignis, mit dem eine Quelle eine Mitteilung übergibt, heißt fyos:zeigt', () => {
    expect(ZEIGT_EREIGNIS).toBe('fyos:zeigt');
  });
});

// ── Die Karten ──────────────────────────────────────────────────────────────────────────────────

function mitteilungen(start: Mitteilung[] = [], extra: Partial<MitteilungenProps> = {}) {
  const [l, setL] = createSignal<Mitteilung[]>(start);
  const [h, setH] = createSignal<Hinweis | null>(null);
  const onOeffnen = vi.fn(async (_m: Mitteilung): Promise<string | null> => null);
  const onWeg = vi.fn();
  const onStumm = vi.fn();
  const onAus = vi.fn();
  const onHinweisWeg = vi.fn(() => setH(null));
  const r = render(() => (
    <Mitteilungen liste={l} flaeche={flaecheVon} onOeffnen={onOeffnen} onWeg={onWeg} onStumm={onStumm} onAus={onAus} hinweis={h} onHinweisWeg={onHinweisWeg} {...extra} />
  ));
  return { ...r, setL, setH, onOeffnen, onWeg, onStumm, onAus, onHinweisWeg };
}
const eine = (z: Partial<ZeigtDaten> = {}) => hinzufuegen([], zeigt(z), Date.now());
const karte = () => document.querySelector<HTMLElement>('[data-mitteilung]')!;

describe('Mitteilungen', () => {
  it('ist ein stiller Bereich für Screenreader, auch wenn nichts da ist', () => {
    mitteilungen();
    const bereich = screen.getByRole('status', { name: 'Mitteilungen von Agent' });
    expect(bereich.getAttribute('aria-live')).toBe('polite');
    expect(document.querySelectorAll('[data-mitteilung]')).toHaveLength(0);
  });

  it('zeigt „Agent zeigt dir“, die Zeit, den Namen der App, den Zusatz und die Vorschau', () => {
    mitteilungen(eine());
    const k = karte();
    expect(within(k).getByText('Agent zeigt dir')).toBeTruthy();
    expect(within(k).getByText('jetzt')).toBeTruthy();
    expect(k.querySelector('strong')!.textContent).toBe('Haus');
    expect(k.querySelector('.os-mitteilung-unter')!.textContent!.trim()).toBe('Wohnzimmer');
    expect(within(k).getByText('Drei Lichter sind an, die Heizung läuft.')).toBeTruthy();
    expect(within(k).getByRole('button', { name: /Öffnen/ })).toBeTruthy();
    expect(within(k).getByRole('button', { name: 'Schließen' })).toBeTruthy();
  });

  it('ohne Vorschau und ohne Zusatz fehlen die Zeilen', () => {
    mitteilungen(eine({ vorschau: null, untertitel: null }));
    expect(document.querySelector('.os-mitteilung-vorschau')).toBeNull();
    expect(document.querySelector('.os-mitteilung-unter')).toBeNull();
  });

  it('nimmt den Namen der Fläche, wenn die Nutzlast keinen Titel hat', () => {
    mitteilungen(eine({ titel: '' }));
    expect(karte().querySelector('strong')!.textContent).toBe('Haus');
  });

  it('die Karte ist fokussierbar und sagt, was sie ist und was Enter und Escape tun', () => {
    mitteilungen(eine());
    const k = karte();
    expect(k.getAttribute('tabindex')).toBe('0');
    expect(k.getAttribute('role')).toBe('group');
    expect(k.getAttribute('aria-label')).toBe('Agent zeigt dir Haus. Enter öffnet, Escape schließt.');
  });

  it('stapelt bis zu drei, die neueste oben, jede mit ihrer Stufe', () => {
    let l: Mitteilung[] = [];
    for (const z of ['seite:notizen', 'app:haus__favoriten', 'seite:drittes']) l = hinzufuegen(l, zeigt({ ziel: z, titel: z, vorschau: null }), Date.now());
    mitteilungen(l);
    const ks = [...document.querySelectorAll<HTMLElement>('[data-mitteilung]')];
    expect(ks.map((k) => k.querySelector('strong')!.textContent)).toEqual(['seite:drittes', 'app:haus__favoriten', 'seite:notizen']);
    expect(ks.map((k) => k.style.getPropertyValue('--stufe'))).toEqual(['0', '1', '2']);
  });

  it('nimmt eine neue Mitteilung oben auf und verschiebt die Stufen', async () => {
    const { setL } = mitteilungen(eine({ ziel: 'seite:notizen', titel: 'Notizen' }));
    setL((vorher) => hinzufuegen(vorher, zeigt({ titel: 'Haus' }), Date.now()));
    await lass();
    const ks = [...document.querySelectorAll<HTMLElement>('[data-mitteilung]')];
    expect(ks.map((k) => k.querySelector('strong')!.textContent)).toEqual(['Haus', 'Notizen']);
    expect(ks.map((k) => k.style.getPropertyValue('--stufe'))).toEqual(['0', '1']);
  });

  it('die Zeit läuft mit: „vor 2 min“', () => {
    const alt: Mitteilung[] = [{ key: 'k', id: 999, zeigt: zeigt(), seit: Date.now() - 125_000 }];
    mitteilungen(alt);
    expect(screen.getByText('vor 2 min')).toBeTruthy();
  });

  describe('Öffnen', () => {
    it('ein Klick auf die Karte öffnet die App und blendet die Karte danach aus', async () => {
      const { onOeffnen, onWeg } = mitteilungen(eine());
      const m = karte();
      fireEvent.click(m);
      await lass(0);
      expect(onOeffnen).toHaveBeenCalledTimes(1);
      expect(onOeffnen.mock.calls[0]![0].zeigt.ziel).toBe('app:haus__favoriten');
      expect(m.classList.contains('os-mitteilung-weg')).toBe(true);
      expect(onWeg).not.toHaveBeenCalled();
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
    });

    it('der Knopf „Öffnen“ tut dasselbe', async () => {
      const { onOeffnen } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: /Öffnen/ }));
      await lass(0);
      expect(onOeffnen).toHaveBeenCalledTimes(1);
    });

    it('Enter und Leertaste auf der Karte öffnen', async () => {
      const { onOeffnen } = mitteilungen(eine());
      fireEvent.keyDown(karte(), { key: 'Enter' });
      await lass(0);
      expect(onOeffnen).toHaveBeenCalledTimes(1);
      cleanup();
      const zweite = mitteilungen(eine());
      fireEvent.keyDown(karte(), { key: ' ' });
      await lass(0);
      expect(zweite.onOeffnen).toHaveBeenCalledTimes(1);
    });

    it('Enter auf einem Knopf in der Karte gehört dem Knopf, nicht der Karte', async () => {
      const { onOeffnen, onWeg } = mitteilungen(eine());
      fireEvent.keyDown(within(karte()).getByRole('button', { name: 'Schließen' }), { key: 'Enter' });
      await lass(0);
      expect(onOeffnen).not.toHaveBeenCalled();
      expect(onWeg).not.toHaveBeenCalled();
    });

    it('geht das Öffnen schief, bleibt die Karte stehen und sagt warum', async () => {
      const onOeffnen = vi.fn(async () => '„Haus“ ließ sich nicht öffnen.');
      const { onWeg } = mitteilungen(eine(), { onOeffnen });
      fireEvent.click(karte());
      await lass(0);
      expect(screen.getByRole('alert').textContent).toBe('„Haus“ ließ sich nicht öffnen.');
      await lass(60_000);
      expect(onWeg).not.toHaveBeenCalled();
      expect(karte().classList.contains('os-mitteilung-weg')).toBe(false);
    });

    it('wirft das Öffnen, bleibt die Karte ebenfalls und zeigt den Text des Fehlers', async () => {
      const onOeffnen = vi.fn(async () => {
        throw new Error('Kaputt im Rahmen');
      });
      mitteilungen(eine(), { onOeffnen });
      fireEvent.click(karte());
      await lass(0);
      expect(screen.getByRole('alert').textContent).toBe('Kaputt im Rahmen');
    });

    it('ein zweiter Klick, während das Öffnen läuft, öffnet nicht noch einmal', async () => {
      let fertig: (v: string | null) => void = () => {};
      const onOeffnen = vi.fn(() => new Promise<string | null>((r) => (fertig = r)));
      mitteilungen(eine(), { onOeffnen });
      fireEvent.click(karte());
      fireEvent.click(karte());
      fireEvent.click(within(karte()).getByRole('button', { name: /Öffnen/ }));
      expect(onOeffnen).toHaveBeenCalledTimes(1);
      fertig(null);
      await lass(0);
    });
  });

  describe('Schließen', () => {
    it('der Knopf „Schließen“ blendet aus und nimmt die Karte danach heraus, ohne zu öffnen', async () => {
      const { onOeffnen, onWeg } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Schließen' }));
      expect(karte().classList.contains('os-mitteilung-weg')).toBe(true);
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
      expect(onOeffnen).not.toHaveBeenCalled();
    });

    it('Escape schließt die Karte, in der der Fokus steht, und öffnet nichts', async () => {
      const { onOeffnen, onWeg } = mitteilungen(eine());
      karte().focus();
      fireEvent.keyDown(karte(), { key: 'Escape' });
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
      expect(onOeffnen).not.toHaveBeenCalled();
    });

    it('Escape schließt nur die Karte mit dem Fokus, nicht den ganzen Stapel', async () => {
      let l: Mitteilung[] = hinzufuegen([], zeigt({ ziel: 'seite:notizen', titel: 'Notizen' }), Date.now());
      l = hinzufuegen(l, zeigt({ titel: 'Haus' }), Date.now());
      const { onWeg } = mitteilungen(l);
      const ks = [...document.querySelectorAll<HTMLElement>('[data-mitteilung]')];
      fireEvent.keyDown(ks[1]!, { key: 'Escape' });
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
      expect(onWeg.mock.calls[0]![0]).toBe(l[1]!.id);
    });

    it('geht nach zehn Sekunden von selbst', async () => {
      const { onWeg } = mitteilungen(eine());
      await lass(ANZEIGE_MS - 100);
      expect(onWeg).not.toHaveBeenCalled();
      await lass(100 + 250);
      expect(onWeg).toHaveBeenCalledTimes(1);
    });

    it('bleibt, solange der Zeiger darüber steht; danach mindestens noch ein paar Sekunden', async () => {
      const { onWeg } = mitteilungen(eine());
      await lass(ANZEIGE_MS - 1_000);
      fireEvent.pointerEnter(karte());
      await lass(120_000);
      expect(onWeg).not.toHaveBeenCalled();
      fireEvent.pointerLeave(karte());
      await lass(3_500);
      expect(onWeg).not.toHaveBeenCalled();
      await lass(1_000);
      expect(onWeg).toHaveBeenCalledTimes(1);
    });

    it('bleibt, solange der Fokus in der Karte ist', async () => {
      const { onWeg } = mitteilungen(eine());
      fireEvent.focusIn(karte());
      await lass(60_000);
      expect(onWeg).not.toHaveBeenCalled();
    });
  });

  describe('⋯-Menü', () => {
    const menuePunkt = (text: string) => {
      const p = menue()!.punkte.find((x) => 'text' in x && x.text === text);
      if (!p || !('tun' in p)) throw new Error(`kein Menüpunkt „${text}“`);
      return p;
    };

    it('bietet Öffnen, Schließen, Link kopieren, Eine Stunde stumm und Mitteilungen ausschalten, mit Glyphen', () => {
      mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      const m = menue()!;
      expect(m.quelle).toMatch(/^mitteilung:/);
      expect(m.punkte.map((p) => ('text' in p ? p.text : p.art))).toEqual(['Öffnen', 'Schließen', 'Link kopieren', 'trenner', 'Eine Stunde stumm', 'Mitteilungen ausschalten']);
      expect(m.punkte.filter((p) => 'symbol' in p).map((p) => (p as { symbol?: string }).symbol)).toEqual(['arrow-up-right', 'x', 'link', 'moon', 'bell-off']);
    });

    it('„Öffnen“ im Menü öffnet die App', async () => {
      const { onOeffnen } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Öffnen').tun();
      await lass(0);
      expect(onOeffnen).toHaveBeenCalledTimes(1);
    });

    it('„Schließen“ im Menü schließt die Karte, ohne zu öffnen', async () => {
      const { onOeffnen, onWeg } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Schließen').tun();
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
      expect(onOeffnen).not.toHaveBeenCalled();
    });

    it('„Link kopieren“ nimmt den Link der Nutzlast, sonst einen Deeplink aus Ziel und Eingabe', () => {
      const writeText = vi.fn(async (_text: string) => {});
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
      mitteilungen(eine({ link: 'https://fyos.example/os?offen=app:haus__favoriten&eingabe=abc' }));
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Link kopieren').tun();
      expect(writeText).toHaveBeenLastCalledWith('https://fyos.example/os?offen=app:haus__favoriten&eingabe=abc');
      cleanup();
      menueZu();
      mitteilungen(eine({ link: null, eingabe: { raum: 'Küche' } }));
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Link kopieren').tun();
      const url = new URL(writeText.mock.calls.at(-1)![0] as string);
      expect(url.pathname).toBe('/os/');
      expect(url.search).toMatch(/^\?offen=app:haus__favoriten&eingabe=[A-Za-z0-9_-]+$/);
    });

    it('„Link kopieren“ stürzt nicht ab, wenn die Zwischenablage fehlt oder abgelehnt wird', () => {
      vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
      mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      expect(() => menuePunkt('Link kopieren').tun()).not.toThrow();
      vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: () => Promise.reject(new Error('verweigert')) } });
      expect(() => menuePunkt('Link kopieren').tun()).not.toThrow();
    });

    it('„Eine Stunde stumm“ und „ausschalten“ melden es weiter und schließen die Karte', async () => {
      const { onStumm, onAus, onWeg } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Eine Stunde stumm').tun();
      expect(onStumm).toHaveBeenCalledWith(60);
      await lass(250);
      expect(onWeg).toHaveBeenCalledTimes(1);
      cleanup();
      menueZu();
      const zwei = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      menuePunkt('Mitteilungen ausschalten').tun();
      expect(zwei.onAus).toHaveBeenCalledTimes(1);
      expect(onAus).not.toHaveBeenCalled();
    });

    it('solange das Menü offen ist, geht die Karte nicht weg', async () => {
      const { onWeg } = mitteilungen(eine());
      fireEvent.click(within(karte()).getByRole('button', { name: 'Weitere Aktionen' }));
      await lass(120_000);
      expect(onWeg).not.toHaveBeenCalled();
    });
  });

  describe('Rückmeldung mit „Rückgängig“', () => {
    it('zeigt den Text und nimmt mit „Rückgängig“ zurück', async () => {
      const zurueck = vi.fn();
      const { setH, onHinweisWeg } = mitteilungen();
      setH({ text: 'Mitteilungen sind aus.', zurueck });
      await lass(0);
      expect(screen.getByText('Mitteilungen sind aus.')).toBeTruthy();
      fireEvent.click(screen.getByRole('button', { name: 'Rückgängig' }));
      expect(zurueck).toHaveBeenCalledTimes(1);
      await lass(250);
      expect(onHinweisWeg).toHaveBeenCalledTimes(1);
    });

    it('geht nach acht Sekunden von selbst, ohne etwas zurückzunehmen', async () => {
      const zurueck = vi.fn();
      const { setH, onHinweisWeg } = mitteilungen();
      setH({ text: 'Stumm.', zurueck });
      await lass(7_500);
      expect(onHinweisWeg).not.toHaveBeenCalled();
      await lass(1_000);
      expect(onHinweisWeg).toHaveBeenCalledTimes(1);
      expect(zurueck).not.toHaveBeenCalled();
    });
  });
});
