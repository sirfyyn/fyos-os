/**
 * App-Drawer (OS-Neubau P7): Stand je App aus den Kurzsätzen der Zentrale und der einen „wartet“-Zahl, Ton bei
 * Abweichung, A–Z ohne Doppelte, „Zuletzt“ im Speicher (auch wenn er wirft).
 */
import { describe, expect, it } from 'vitest';
import { ZULETZT_MAX, alphabetisch, standFuer, standTon, zuletztFlaechen, zuletztLesen, zuletztMerken } from '~/lib/os/drawer';
import type { Flaeche } from '~/lib/os/flaechen';
import type { Kachel, ZentraleZustand } from '~/lib/zentrale';

const k = (id: string, kurz: string, dringlichkeit = 10, fehler: string | null = null): Kachel => ({
  id, titel: id, kurz, dringlichkeit, fehler, grund: '', daten: {}, aktionen: [],
});
const zustand: ZentraleZustand = {
  ts: '', lage_satz: '', ampel: 'gruen',
  kacheln: [k('geld', 'Oktober 2.044 von 2.044 € bezahlt'), k('cluster', '77 von 77 Pods'), k('betrieb', 'CI auf **main** rot', 65), k('haus', '', 5, 'timeout')],
};
const f = (id: string, titel: string, appName?: string): Flaeche => ({ id, titel, gruppe: 'x', art: 'hubapp', kuerzel: '', appName });

describe('standFuer', () => {
  it('nimmt den Kurzsatz der passenden Kachel', () => {
    expect(standFuer(f('seite:finance', 'Finanzen'), { zustand })).toBe('Oktober 2.044 von 2.044 € bezahlt');
    expect(standFuer(f('app:cluster__knoten', 'Steuerpult', 'cluster__knoten'), { zustand })).toBe('77 von 77 Pods');
    expect(standFuer(f('nativ:betrieb', 'Betrieb'), { zustand })).toBe('CI auf main rot');
  });
  it('Vorgänge zeigen die eine Zahl aus „Wartet auf dich“', () => {
    expect(standFuer(f('app:vorgaenge__zeigen', 'Vorgänge'), { zustand, wartet: 2 })).toBe('2 warten auf dich');
    expect(standFuer(f('app:vorgaenge__zeigen', 'Vorgänge'), { zustand, wartet: 0 })).toBe('nichts wartet auf dich');
  });
  it('ausgefallen heißt „nicht abrufbar“, unbekannt null', () => {
    expect(standFuer(f('seite:smarthome', 'Haus'), { zustand })).toBe('nicht abrufbar');
    expect(standFuer(f('app:geschichten', 'Geschichten'), { zustand })).toBeNull();
  });
});

describe('standTon', () => {
  it('rot ab 60 oder Ausfall, gelb ab 30, sonst nichts', () => {
    expect(standTon(f('nativ:betrieb', 'Betrieb'), { zustand })).toBe('rot');
    expect(standTon(f('seite:smarthome', 'Haus'), { zustand })).toBe('rot');
    expect(standTon(f('seite:finance', 'Finanzen'), { zustand })).toBeNull();
    expect(standTon(f('app:vorgaenge__zeigen', 'Vorgänge'), { zustand, wartet: 1 })).toBe('gelb');
  });
});

describe('alphabetisch', () => {
  it('sortiert deutsch und ohne Doppelte', () => {
    const a = f('a', 'Übersicht');
    const b = f('b', 'Atelier');
    expect(alphabetisch([{ flaechen: [a, b] }, { flaechen: [b] }]).map((x) => x.titel)).toEqual(['Atelier', 'Übersicht']);
  });
});

describe('Zuletzt', () => {
  const speicher = () => {
    const m = new Map<string, string>();
    return { getItem: (s: string) => m.get(s) ?? null, setItem: (s: string, v: string) => void m.set(s, v) };
  };
  it('merkt vorn, rückt Doppelte nach vorn, höchstens zwölf', () => {
    const s = speicher();
    zuletztMerken('a', s);
    zuletztMerken('b', s);
    expect(zuletztMerken('a', s)).toEqual(['a', 'b']);
    for (let i = 0; i < 20; i++) zuletztMerken(`x${i}`, s);
    expect(zuletztLesen(s)).toHaveLength(ZULETZT_MAX);
  });
  it('wirft der Speicher, bleibt es leer', () => {
    expect(zuletztLesen({ getItem: () => { throw new Error('gesperrt'); } })).toEqual([]);
  });
  it('unbekannte Kennungen fallen weg', () => {
    expect(zuletztFlaechen(['weg', 'a'], [{ flaechen: [f('a', 'A')] }]).map((x) => x.id)).toEqual(['a']);
  });
});
