import { beforeEach, describe, expect, it, vi } from 'vitest';
import { griffeBauen, griffeFinden } from '~/lib/griffe';
import { Meldungsdienst, type MeldungEingabe } from '~/lib/os/meldungen';
import { bereinige } from '~/lib/os/meldungen-einstellungen';
import { quellenStarten, wartetAus, type WartetMeldbar } from '~/lib/os/meldungen-quellen';
import { ANGEWENDET_SCHLUESSEL, _zuruecksetzen, anwenden, modus, modusLesen, setzeModus, type Abh, type ModusZustand } from '~/lib/os/modi';

function speicher(): Pick<Storage, 'getItem' | 'setItem'> & { daten: Map<string, string> } {
  const daten = new Map<string, string>();
  return { daten, getItem: (k) => daten.get(k) ?? null, setItem: (k, v) => void daten.set(k, v) };
}

const Z = (m: ModusZustand['modus'], seit = '2026-10-31T21:00:00Z', ton: string | null = { ruhe: 'stumm', normal: 'zurueckhaltend', bereit: 'interaktiv' }[m]): ModusZustand => ({
  modus: m,
  seit,
  geschaltet: [],
  meldebudget: 5,
  browser: { meldungen: m === 'normal' ? 'budget:5' : m === 'ruhe' ? 'kritisch' : 'alle', ton, bildschirm: m === 'bereit' ? 'nativ:bereit' : m === 'ruhe' ? 'nativ:agent-zimmer' : 'zentrale' },
});

function abh(antwort: (w: string, a: Record<string, unknown>) => unknown = () => Z('normal')) {
  const s = speicher();
  const a: Abh & { tonListe: string[]; offen: string[]; ereignisse: { modus: string; hier: boolean }[]; aufrufe: string[]; tonJetzt: string | null } = {
    tonListe: [],
    offen: [],
    ereignisse: [],
    aufrufe: [],
    tonJetzt: 'ton',
    hub: async <T,>(w: string, args: Record<string, unknown>) => {
      a.aufrufe.push(w);
      return antwort(w, args) as T;
    },
    speicher: s,
    ton: (t) => {
      a.tonListe.push(t);
      a.tonJetzt = t;
    },
    tonLesen: () => a.tonJetzt as never,
    oeffne: (z) => {
      a.offen.push(z);
      return true;
    },
    ereignis: (e) => a.ereignisse.push({ modus: e.modus, hier: e.hier }),
    jetzt: () => 1000,
  };
  return a;
}

beforeEach(() => _zuruecksetzen());

describe('modi.ts: Signal und Wechsel', () => {
  it('erstes Laden ohne Merker stellt den Ton nicht um, ein späterer Wechsel von woanders schon', async () => {
    const a = abh(() => Z('normal'));
    await modusLesen(a);
    expect(modus()).toBe('normal');
    expect(a.tonListe).toEqual([]);
    anwenden(Z('ruhe', '2026-10-31T22:00:00Z'), false, a);
    expect(modus()).toBe('ruhe');
    expect(a.tonListe).toEqual(['stumm']);
    expect(a.offen).toEqual([]); // Bildschirm nur am Gerät, das umschaltet
    expect(a.ereignisse.at(-1)).toEqual({ modus: 'ruhe', hier: false });
    anwenden(Z('ruhe', '2026-10-31T22:00:00Z'), false, a); // dieselbe Abfrage nochmal: nichts
    expect(a.tonListe).toEqual(['stumm']);
  });

  it('setzeModus: Ton sofort, Bereit-Seite öffnet sich hier, Ereignis mit hier=true', async () => {
    const a = abh((w, args) => (w === 'modus.setzen' ? { ...Z(args.modus as 'bereit'), dauer_ms: 812 } : Z('normal')));
    const z = await setzeModus('bereit', {}, a);
    expect(z.dauer_ms).toBe(812);
    expect(a.tonListe[0]).toBe('interaktiv');
    expect(a.offen).toEqual(['nativ:bereit']);
    expect(a.ereignisse.at(-1)).toEqual({ modus: 'bereit', hier: true });
    expect(a.speicher!.getItem(ANGEWENDET_SCHLUESSEL)).toBe('bereit|2026-10-31T21:00:00Z');
  });

  it('abgewählter Ton kommt zurück, Fehler des Hubs auch', async () => {
    const a = abh((w) => (w === 'modus.setzen' ? Z('ruhe', 'x', null) : Z('normal')));
    await setzeModus('ruhe', {}, a);
    expect(a.tonJetzt).toBe('ton');
    const b = abh(() => {
      throw new Error('Hub weg');
    });
    await expect(setzeModus('bereit', {}, b)).rejects.toThrow('Hub weg');
    expect(b.tonJetzt).toBe('ton');
  });
});

describe('Meldebudget (Nr. 707)', () => {
  const einst = bereinige(null);
  const e = (i: number, stufe: MeldungEingabe['stufe'] = 'normal'): MeldungEingabe => ({ quelle: 'agent', schluessel: `k${i}`, stufe, titel: `M${i}` });

  it('Normal: fünf unterbrechen, der Rest still; Kritisches immer und ohne Abzug; neuer Tag neues Budget', () => {
    let jetzt = new Date(2026, 9, 31, 10).getTime();
    const s = speicher();
    const d = new Meldungsdienst({ einstellungen: () => einst, jetzt: () => jetzt, modus: () => 'normal', budget: () => 5, budgetSpeicher: s });
    const toasts = [0, 1, 2, 3, 4, 5, 6].map((i) => d.melde(e(i))!.toast);
    expect(toasts).toEqual([true, true, true, true, true, false, false]);
    expect(d.melde(e(9, 'kritisch'))!.toast).toBe(true);
    expect(d.budgetRest()).toBe(0);
    // Neu geladen: der Zähler steht im Speicher
    const d2 = new Meldungsdienst({ einstellungen: () => einst, jetzt: () => jetzt, modus: () => 'normal', budget: () => 5, budgetSpeicher: s });
    expect(d2.budgetRest()).toBe(0);
    jetzt = new Date(2026, 10, 1, 8).getTime();
    expect(d2.budgetRest()).toBe(5);
  });

  it('Ruhe nur kritisch, Bereit alles auch bei des Agenten Ruhe, ohne Modus wie bisher', () => {
    const r = new Meldungsdienst({ einstellungen: () => einst, modus: () => 'ruhe' });
    expect(r.melde(e(1, 'hoch'))!.toast).toBe(false);
    expect(r.melde(e(2, 'kritisch'))!.toast).toBe(true);
    const b = new Meldungsdienst({ einstellungen: () => einst, modus: () => 'bereit', ruhe: () => true });
    expect([1, 2, 3, 4, 5, 6, 7].every((i) => b.melde(e(i))!.toast)).toBe(true);
    const alt = new Meldungsdienst({ einstellungen: () => einst, modus: () => undefined });
    expect([1, 2, 3, 4, 5, 6, 7].every((i) => alt.melde(e(i))!.toast)).toBe(true);
  });

  it('Zusammengefasstes kostet kein Budget', () => {
    const d = new Meldungsdienst({ einstellungen: () => einst, modus: () => 'normal', budget: () => 2, jetzt: () => 5_000 });
    const mail = (i: number): MeldungEingabe => ({ quelle: 'mail', schluessel: `m${i}`, stufe: 'normal', titel: 'Mail', sammeln: (n) => `${n} neue Mails` });
    expect(d.melde(mail(1))!.toast).toBe(true);
    expect(d.melde(mail(2))!.zusammengefasst).toBe(true);
    expect(d.budgetRest()).toBe(1);
  });
});

describe('Modus-Griffe in ⌘K', () => {
  it('„Ruhe“ und „Ich bin da“ finden, nur mit bekanntem Modus', () => {
    const g = griffeBauen({ modus: 'normal' });
    expect(griffeFinden(g, 'Ruhe')[0]).toMatchObject({ werkzeug: 'modus.setzen', argumente: { modus: 'ruhe' } });
    expect(griffeFinden(g, 'ich bin da')[0]).toMatchObject({ argumente: { modus: 'bereit' } });
    expect(g.find((x) => x.id === 'modus:normal')!.istSchon).toBe(true);
    expect(g.find((x) => x.id === 'modus:ruhe')!.gegen).toMatchObject({ argumente: { modus: 'normal' } });
    expect(griffeBauen({}).some((x) => x.gruppe === 'Modus')).toBe(false);
  });
});

describe('Freigabe-Meldungen aus „Wartet auf dich“ (P2)', () => {
  const w = (id: string, extra: Partial<WartetMeldbar> = {}): WartetMeldbar => ({ id, quelle: 'runner', satz: `Satz ${id}`, umkehrbar: false, zerstoererisch: false, ...extra });

  it('Stufen: zerstörerisch kritisch, nicht umkehrbar hoch, Fragen normal und gesammelt', () => {
    expect(wartetAus(w('a', { zerstoererisch: true })).stufe).toBe('kritisch');
    expect(wartetAus(w('b')).stufe).toBe('hoch');
    const f = wartetAus(w('c', { umkehrbar: true, quelle: 'itsm', ziel: 'app:itsm__vorgang' }));
    expect(f).toMatchObject({ stufe: 'normal', ziel: { ziel: 'app:itsm__vorgang' }, schluessel: 'wartet:c' });
    expect(f.sammeln!(3)).toBe('3 Fragen warten auf dich');
    expect(wartetAus(w('d', { quelle: 'kalender', ziel: 'https://x' })).ziel).toBeUndefined();
  });

  it('ersetzt den Runner-Abruf: erster Stand nur Verlauf (Kritisches als Toast), danach nur Neues', () => {
    let hoerer: ((e: readonly WartetMeldbar[]) => void) | undefined;
    const gemeldet: MeldungEingabe[] = [];
    const freigaben = vi.fn(async () => []);
    const aus = quellenStarten({
      einstellungen: () => bereinige({ quellen: { stoerung: false, agent: false, termin: false, mail: false } }),
      melde: (e) => void gemeldet.push(e),
      jetzt: () => 0,
      setInterval: () => 0,
      clearInterval: () => undefined,
      setTimeout: () => 0,
      clearTimeout: () => undefined,
      bus: () => () => undefined,
      freigaben,
      freigabenAenderung: () => () => undefined,
      stromZeilen: () => () => undefined,
      agentVorn: () => false,
      kalender: async () => ({ events: [] }),
      mail: async () => ({ messages: [] }),
      wartet: (f) => {
        hoerer = f;
        return () => (hoerer = undefined);
      },
    });
    hoerer!([w('alt'), w('boese', { zerstoererisch: true })]);
    expect(gemeldet.map((m) => [m.schluessel, !!m.nurVerlauf])).toEqual([['wartet:alt', true], ['wartet:boese', false]]);
    hoerer!([w('alt'), w('boese', { zerstoererisch: true }), w('neu')]);
    expect(gemeldet.at(-1)).toMatchObject({ schluessel: 'wartet:neu', stufe: 'hoch' });
    expect(gemeldet.at(-1)!.nurVerlauf).toBeUndefined();
    expect(gemeldet).toHaveLength(3);
    expect(freigaben).not.toHaveBeenCalled();
    aus();
  });
});

vi.mock('~/lib/hub', () => ({ hub: vi.fn() }));
