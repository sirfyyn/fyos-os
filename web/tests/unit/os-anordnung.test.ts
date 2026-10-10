import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MAX_OFFEN, NEU_SPALTEN, NEU_ZEILEN, SPALTEN, alleEinblenden, autoReihen, autoSpalten, automatisch, bereinigen, davorSetzen, festSetzen, groesseSetzen,
  laden, listePruefen, minimieren, neueZeileUmschalten, oeffnen, schliessen, speichern, tauschen, verschieben,
  fensterPruefen, startPruefen, vonHand, type Fenster,
} from '~/lib/os/anordnung';

const f = (id: string, min = false): Fenster => ({ id, min });

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
});

describe('Anordnung', () => {
  it('öffnet hinten, vor einem Fenster oder holt ein minimiertes zurück', () => {
    expect(oeffnen([f('a')], 'b').map((w) => w.id)).toEqual(['a', 'b']);
    expect(oeffnen([f('a'), f('b')], 'c', { vor: 'b' }).map((w) => w.id)).toEqual(['a', 'c', 'b']);
    const r = oeffnen([f('a', true)], 'a');
    expect(r).toHaveLength(1);
    expect(r[0]!.min).toBe(false);
  });

  it('öffnet nichts, wenn schon MAX_OFFEN sichtbar sind (minimierte zählen nicht)', () => {
    const voll = Array.from({ length: MAX_OFFEN }, (_, i) => f(`w${i}`));
    expect(oeffnen(voll, 'neu')).toBe(voll);
    const mitMin = [...voll.slice(0, MAX_OFFEN - 1), f('x', true)];
    expect(oeffnen(mitMin, 'neu')).toHaveLength(MAX_OFFEN + 1);
  });

  it('schließt und minimiert', () => {
    expect(schliessen([f('a'), f('b')], 'a').map((w) => w.id)).toEqual(['b']);
    expect(minimieren([f('a')], 'a')[0]!.min).toBe(true);
  });

  it('„Alle einblenden“ holt höchstens bis MAX_OFFEN zurück, der Rest bleibt im Dock', () => {
    const l = [...Array.from({ length: MAX_OFFEN - 2 }, (_, i) => f(`w${i}`)), f('m1', true), f('m2', true), f('m3', true)];
    const r = alleEinblenden(l);
    expect(r.liste.filter((w) => !w.min)).toHaveLength(MAX_OFFEN);
    expect(r.liste.find((w) => w.id === 'm3')!.min).toBe(true);
    expect(r.rest).toBe(1);
    expect(alleEinblenden([f('a', true)])).toEqual({ liste: [f('a')], rest: 0 });
  });

  it('tauscht, setzt davor und verschiebt nur sichtbare Nachbarn', () => {
    expect(tauschen([f('a'), f('b'), f('c')], 'a', 'c').map((w) => w.id)).toEqual(['c', 'b', 'a']);
    expect(tauschen([f('a')], 'a', 'zzz').map((w) => w.id)).toEqual(['a']);
    expect(davorSetzen([f('a'), f('b'), f('c')], 'c', 'a').map((w) => w.id)).toEqual(['c', 'a', 'b']);
    expect(davorSetzen([f('a'), f('b'), f('c')], 'a', null).map((w) => w.id)).toEqual(['b', 'c', 'a']);
    const l = [f('a'), f('m', true), f('c')];
    expect(verschieben(l, 'a', 1).map((w) => w.id)).toEqual(['c', 'm', 'a']); // springt über das minimierte
    expect(verschieben(l, 'a', -1)).toBe(l);
  });

  it('bereinigt unbekannte Flächen', () => {
    expect(bereinigen([f('a'), f('weg')], (id) => id === 'a').map((w) => w.id)).toEqual(['a']);
  });

  it('speichert und lädt; Müll im Speicher ergibt eine leere Liste; „breit" wird zu 12 Spalten', () => {
    speichern([f('a'), { id: 'b', min: true, breit: true }]);
    expect(laden()).toEqual([f('a'), { id: 'b', min: true, spalten: SPALTEN, zeilen: NEU_ZEILEN }]);
    localStorage.setItem('fyos:os:anordnung:v1', '{kaputt');
    expect(laden()).toEqual([]);
    localStorage.setItem('fyos:os:anordnung:v1', JSON.stringify([{ id: 'a' }, { id: 'a' }, 5, null]));
    expect(laden().map((w) => w.id)).toEqual(['a']);
  });
});

describe('Raster: Größe, neue Zeile, Automatik', () => {
  it('Automatik verteilt gleichmäßig: 1 voll, 2 halb, 3 Drittel, 4 als 2×2, ab 5 drei je Zeile', () => {
    expect([1, 2, 3, 4, 5, 7].map(autoSpalten)).toEqual([12, 6, 4, 6, 4, 4]);
    expect([1, 2, 3, 4, 5, 7].map(autoReihen)).toEqual([1, 1, 1, 2, 2, 3]);
  });

  it('der erste Eingriff friert die Automatik ein — nichts springt', () => {
    const l = [f('a'), f('b')];
    expect(vonHand(l)).toBe(false);
    const auto = new Map([['a', { spalten: 6, zeilen: 12 }], ['b', { spalten: 6, zeilen: 12 }]]);
    const r = groesseSetzen(l, 'a', { spalten: 8 }, auto);
    expect(r).toEqual([{ id: 'a', min: false, spalten: 8, zeilen: 12 }, { id: 'b', min: false, spalten: 6, zeilen: 12 }]);
    expect(vonHand(r)).toBe(true);
  });

  it('Größen bleiben im Raster (3–12 Spalten, 4–24 Zeilen)', () => {
    const r = groesseSetzen([{ id: 'a', min: false, spalten: 6, zeilen: 10 }], 'a', { spalten: 99, zeilen: 1 });
    expect(r[0]).toMatchObject({ spalten: 12, zeilen: 4 });
    expect(groesseSetzen(r, 'a', { spalten: 1 })[0]!.spalten).toBe(3);
  });

  it('neue Fenster: Automatik, solange nichts von Hand gesetzt ist; sonst Standardgröße', () => {
    expect(oeffnen([f('a')], 'b')[1]).toEqual({ id: 'b', min: false });
    const hand = [{ id: 'a', min: false, spalten: 4, zeilen: 8 }];
    expect(oeffnen(hand, 'b')[1]).toEqual({ id: 'b', min: false, spalten: NEU_SPALTEN, zeilen: NEU_ZEILEN });
  });

  it('neue Zeile schaltet um, „Neu verteilen" nimmt alles zurück in die Automatik', () => {
    const l = neueZeileUmschalten([{ id: 'a', min: false, spalten: 4, zeilen: 8 }], 'a');
    expect(l[0]!.neueZeile).toBe(true);
    expect(automatisch(l)).toEqual([{ id: 'a', min: false }]);
  });

  it('Prüfung räumt Unsinn weg: Grenzen, fremde Felder, Doppelte', () => {
    expect(listePruefen([{ id: 'a', spalten: 40, zeilen: 'x', neueZeile: 'ja', fremd: 1 }, { id: 'a' }])).toEqual([
      { id: 'a', min: false, spalten: 12, zeilen: NEU_ZEILEN },
    ]);
  });
});

describe('Höhe festhalten (05.10.: Fenster wachsen sonst mit ihrem Inhalt)', () => {
  it('eine gezogene oder gewählte Höhe hält fest, „Mit Inhalt wachsen“ lässt los; die Breite allein ändert nichts daran', () => {
    const l = [{ id: 'app:werkstatt__suchen', min: false, spalten: 6, zeilen: 10 }];
    const fest = groesseSetzen(l, 'app:werkstatt__suchen', { zeilen: 7, fest: true });
    expect(fest[0]).toMatchObject({ zeilen: 7, fest: true });
    expect(groesseSetzen(fest, 'app:werkstatt__suchen', { spalten: 12 })[0]).toMatchObject({ spalten: 12, fest: true });
    const los = festSetzen(fest, 'app:werkstatt__suchen', false);
    expect(los[0].fest).toBeUndefined();
    expect(los[0].zeilen).toBe(7); // die gewählte Höhe bleibt als Mindesthöhe
  });

  it('übersteht Speichern und Laden; Unsinn wird nicht fest', () => {
    expect(fensterPruefen({ id: 'app:x__y', min: false, spalten: 6, zeilen: 8, fest: true })?.fest).toBe(true);
    expect(fensterPruefen({ id: 'app:x__y', min: false, fest: 'ja' })?.fest).toBeUndefined();
  });
});

describe('Startzustand einer App (Deeplink mit Eingabe)', () => {
  const start = { werkzeug: 'haus__szenen', eingabe: { raum: 'Küche' } };

  it('ein neues Fenster trägt den Startzustand; ohne bleibt es, wie es war', () => {
    expect(oeffnen([], 'app:haus__favoriten', { start })[0]).toEqual({ id: 'app:haus__favoriten', min: false, start });
    expect(oeffnen([], 'app:haus__favoriten')[0]).toEqual({ id: 'app:haus__favoriten', min: false });
  });

  it('ein offenes oder minimiertes Fenster übernimmt einen neuen Startzustand, behält aber den alten ohne', () => {
    const offen: Fenster[] = [{ id: 'app:haus__favoriten', min: true, spalten: 6, zeilen: 10 }];
    const mit = oeffnen(offen, 'app:haus__favoriten', { start });
    expect(mit[0]).toEqual({ id: 'app:haus__favoriten', min: false, spalten: 6, zeilen: 10, start });
    expect(oeffnen(mit, 'app:haus__favoriten')[0]!.start).toEqual(start);
  });

  it('startPruefen lässt nur einen Werkzeugnamen mit kleiner JSON-Eingabe durch', () => {
    expect(startPruefen(start)).toEqual(start);
    expect(startPruefen({ werkzeug: 'haus__szenen', eingabe: {} })).toEqual({ werkzeug: 'haus__szenen', eingabe: {} });
    for (const schlecht of [
      null, 'text', 5, [], {},
      { werkzeug: 'haus', eingabe: {} }, // kein Plugin__Werkzeug
      { werkzeug: 'haus__szenen' }, // Eingabe fehlt
      { werkzeug: 'haus__szenen', eingabe: [1] },
      { werkzeug: 'haus__sz/enen', eingabe: {} },
      { werkzeug: '../x__y', eingabe: {} },
      { werkzeug: 'haus__szenen', eingabe: { text: 'x'.repeat(4000) } },
    ]) expect(startPruefen(schlecht), JSON.stringify(schlecht)).toBeUndefined();
  });

  it('startPruefen entfernt gefährliche Schlüssel', () => {
    const roh = JSON.parse('{"werkzeug":"haus__szenen","eingabe":{"__proto__":{"x":1},"constructor":2,"raum":"Bad"}}');
    expect(startPruefen(roh)!.eingabe).toEqual({ raum: 'Bad' });
  });

  it('überlebt Speichern und Laden; kaputter Start fällt weg, das Fenster bleibt', () => {
    expect(fensterPruefen({ id: 'app:haus__favoriten', start })).toEqual({ id: 'app:haus__favoriten', min: false, start });
    expect(fensterPruefen({ id: 'app:haus__favoriten', start: { werkzeug: 'x', eingabe: {} } })).toEqual({ id: 'app:haus__favoriten', min: false });
    expect(listePruefen([{ id: 'app:haus__favoriten', min: false, start }])).toEqual([{ id: 'app:haus__favoriten', min: false, start }]);
  });
});
