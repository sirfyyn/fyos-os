import { describe, expect, it } from 'vitest';
import { RAST_TASTEN, SPALTEN, ZEILEN_MIN, einrasten, type Fenster } from '~/lib/os/anordnung';
import { randZone, zonenRechteck } from '~/components/os/Raster';

const vier = (): Fenster[] => [
  { id: 'seite:a', min: false },
  { id: 'seite:b', min: false },
  { id: 'seite:c', min: true },
  { id: 'seite:d', min: false },
  { id: 'seite:e', min: false },
];

describe('einrasten', () => {
  it('rechte Hälfte: 6 Spalten, volle Höhe, zweiter sichtbarer Platz, Höhe fest', () => {
    const l = einrasten(vier(), 'seite:e', 'rechts', 18);
    const sichtbar = l.filter((w) => !w.min).map((w) => w.id);
    expect(sichtbar.indexOf('seite:e')).toBe(1);
    expect(l.find((w) => w.id === 'seite:e')).toMatchObject({ spalten: SPALTEN / 2, zeilen: 18, fest: true });
    expect(l.some((w) => w.id === 'seite:c' && w.min)).toBe(true); // Minimierte bleiben
    expect(l).toHaveLength(5);
  });
  it('Viertel unten rechts: halbe Höhe, vierter Platz; ganz: 12 Spalten, erster Platz', () => {
    const v = einrasten(vier(), 'seite:a', 'unten-rechts', 18);
    expect(v.filter((w) => !w.min).map((w) => w.id)).toEqual(['seite:b', 'seite:d', 'seite:e', 'seite:a']);
    expect(v.find((w) => w.id === 'seite:a')).toMatchObject({ spalten: 6, zeilen: 9 });
    const g = einrasten(vier(), 'seite:d', 'voll', 18);
    expect(g[0]).toMatchObject({ id: 'seite:d', spalten: SPALTEN, zeilen: 18 });
  });
  it('friert die Automatik ein, nimmt „neue Zeile“ weg und hält die Mindesthöhe', () => {
    const auto = new Map([['seite:a', { spalten: 4, zeilen: 12 }], ['seite:b', { spalten: 4, zeilen: 12 }], ['seite:d', { spalten: 4, zeilen: 12 }]]);
    const l = einrasten([...vier().slice(0, 2), { id: 'seite:d', min: false, neueZeile: true }], 'seite:d', 'oben-links', 5, auto);
    expect(l[0]).toMatchObject({ id: 'seite:d', zeilen: ZEILEN_MIN });
    expect(l[0]!.neueZeile).toBeUndefined();
    expect(l.find((w) => w.id === 'seite:a')).toMatchObject({ spalten: 4, zeilen: 12 });
  });
  it('unbekannte oder minimierte Fenster ändern nichts', () => {
    const l = vier();
    expect(einrasten(l, 'seite:x', 'links', 18)).toBe(l);
    expect(einrasten(l, 'seite:c', 'links', 18)).toBe(l);
  });
  it('Tastenkürzel decken alle Ziele ab', () => {
    expect(new Set(Object.values(RAST_TASTEN)).size).toBe(7);
  });
});

describe('Randzonen beim Ziehen', () => {
  const r = { left: 0, top: 100, right: 1200, bottom: 900 };
  it('links, rechts, Ecken, Mitte', () => {
    expect(randZone(20, 500, r)).toBe('links');
    expect(randZone(1190, 500, r)).toBe('rechts');
    expect(randZone(10, 120, r)).toBe('oben-links');
    expect(randZone(1180, 880, r)).toBe('unten-rechts');
    expect(randZone(600, 500, r)).toBeNull();
    expect(randZone(10, 50, r)).toBeNull();
  });
  it('Vorschau: Hälften und Viertel des Sichtfelds', () => {
    expect(zonenRechteck('rechts', r)).toEqual({ left: 600, top: 100, width: 600, height: 800 });
    expect(zonenRechteck('unten-links', r)).toEqual({ left: 0, top: 500, width: 600, height: 400 });
    expect(zonenRechteck('voll', r)).toEqual({ left: 0, top: 100, width: 1200, height: 800 });
  });
});
