/**
 * Meldungsdienst (lib/os/meldungen.ts) und seine Einstellungen (lib/os/meldungen-einstellungen.ts): Stufen, Obergrenze von drei
 * Toasts, Entdoppeln, Zusammenfassen, „Nicht stören“ und Ruhe, Verlauf, Quellen einzeln abschaltbar. Die Uhr ist gefälscht.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DAUER_MS, ENTDOPPELN_MS, MAX_SICHTBAR, Meldungsdienst, SAMMEL_MS, VERLAUF_MAX, type MeldungEingabe } from '~/lib/os/meldungen';
import {
  SCHLUESSEL,
  VORGABE,
  bereinige,
  imFenster,
  lesen,
  nichtStoerenAktiv,
  schreiben,
  stillHalten,
  type MeldungenEinstellungen,
} from '~/lib/os/meldungen-einstellungen';

let jetzt = Date.parse('2026-10-28T12:00:00');
let einst: MeldungenEinstellungen;
let ruhe = false;
const neu = () => new Meldungsdienst({ einstellungen: () => einst, jetzt: () => jetzt, ruhe: () => ruhe });
let n = 0;
const e = (extra: Partial<MeldungEingabe> = {}): MeldungEingabe => ({ quelle: 'agent', schluessel: `k${++n}`, stufe: 'normal', titel: 'Titel', ...extra });

beforeEach(() => {
  jetzt = Date.parse('2026-10-28T12:00:00');
  einst = structuredClone(VORGABE);
  ruhe = false;
});

describe('Stufen und Sichtbarkeit', () => {
  it('Dauer: kritisch bleibt, hoch 30 s, normal 6 s, niedrig 3 s', () => {
    expect(DAUER_MS).toEqual({ kritisch: null, hoch: 30_000, normal: 6_000, niedrig: 3_000 });
  });

  it('höchstens drei Toasts; kritisch vor hoch vor normal, bei gleicher Stufe die neueste zuerst', () => {
    const d = neu();
    d.melde(e({ titel: 'n1' }));
    jetzt += 10;
    d.melde(e({ titel: 'n2' }));
    jetzt += 10;
    d.melde(e({ titel: 'n3' }));
    jetzt += 10;
    d.melde(e({ titel: 'n4' }));
    let z = d.zustand;
    expect(z.sichtbar.map((m) => m.titel)).toEqual(['n4', 'n3', 'n2']);
    expect(z.wartend).toBe(1);
    jetzt += 10;
    d.melde(e({ titel: 'F', quelle: 'freigabe', stufe: 'hoch' }));
    jetzt += 10;
    d.melde(e({ titel: 'S', quelle: 'stoerung', stufe: 'kritisch' }));
    z = d.zustand;
    expect(z.sichtbar.map((m) => m.titel)).toEqual(['S', 'F', 'n4']);
    expect(z.wartend).toBe(3);
    expect(z.sichtbar.length).toBeLessThanOrEqual(MAX_SICHTBAR);
  });

  it('ein geschlossener Toast gibt den Platz an den wartenden frei; der Verlauf behält alles', () => {
    const d = neu();
    for (let i = 1; i <= 4; i++) {
      jetzt += 10;
      d.melde(e({ titel: `n${i}` }));
    }
    const vorn = d.zustand.sichtbar[0]!;
    d.schliesse(vorn.id);
    const z = d.zustand;
    expect(z.sichtbar.map((m) => m.titel)).toEqual(['n3', 'n2', 'n1']);
    expect(z.verlauf).toHaveLength(4);
    // ablaufen lässt ungelesen, bestätigen liest
    expect(z.ungelesen).toBe(4);
    d.lies(z.sichtbar[0]!.id);
    expect(d.zustand.ungelesen).toBe(3);
  });

  it('Alle gelesen leert die Toasts und setzt die Zahl auf 0; der Verlauf bleibt', () => {
    const d = neu();
    d.melde(e());
    d.melde(e({ stufe: 'kritisch', quelle: 'stoerung' }));
    d.alleGelesen();
    const z = d.zustand;
    expect(z.ungelesen).toBe(0);
    expect(z.sichtbar).toHaveLength(0);
    expect(z.verlauf).toHaveLength(2);
  });

  it('der Verlauf ist auf 100 Einträge begrenzt', () => {
    const d = neu();
    for (let i = 0; i < VERLAUF_MAX + 20; i++) d.melde(e());
    expect(d.zustand.verlauf).toHaveLength(VERLAUF_MAX);
  });

  it('Aufnahme sagt, ob Toast und Systemmitteilung gelten: niedrig nie System', () => {
    const d = neu();
    expect(d.melde(e({ stufe: 'niedrig' }))).toMatchObject({ toast: true, system: false });
    expect(d.melde(e({ stufe: 'normal' }))).toMatchObject({ toast: true, system: true });
    expect(d.melde(e({ stufe: 'kritisch' }))).toMatchObject({ toast: true, system: true });
  });
});

describe('Entdoppeln und Zusammenfassen', () => {
  it('gleiche Quelle + Schlüssel nur einmal; andere Quelle oder Schlüssel zählt neu; nach der Frist wieder', () => {
    const d = neu();
    expect(d.melde(e({ schluessel: 'x' }))).not.toBeNull();
    expect(d.melde(e({ schluessel: 'x' }))).toBeNull();
    expect(d.melde(e({ schluessel: 'x', quelle: 'mail' }))).not.toBeNull();
    expect(d.melde(e({ schluessel: 'y' }))).not.toBeNull();
    jetzt += ENTDOPPELN_MS + 1;
    expect(d.melde(e({ schluessel: 'x' }))).not.toBeNull();
    expect(d.zustand.verlauf.filter((m) => m.schluessel === 'x')).toHaveLength(3);
  });

  it('eigene Entdoppelungszeit je Meldung (Störungen kehren wieder)', () => {
    const d = neu();
    d.melde(e({ schluessel: 's', quelle: 'stoerung', stufe: 'kritisch', entdoppelnMs: 1000 }));
    jetzt += 500;
    expect(d.melde(e({ schluessel: 's', quelle: 'stoerung', stufe: 'kritisch', entdoppelnMs: 1000 }))).toBeNull();
    jetzt += 600;
    expect(d.melde(e({ schluessel: 's', quelle: 'stoerung', stufe: 'kritisch', entdoppelnMs: 1000 }))).not.toBeNull();
  });

  it('gleichartige Mails werden zu „3 neue Mails“, ein Eintrag, die Uhr startet neu (stand steigt)', () => {
    const d = neu();
    const mail = (id: string, betreff: string): MeldungEingabe => ({ quelle: 'mail', schluessel: id, stufe: 'normal', titel: `Neue Mail von ${id}`, text: betreff, sammeln: (k) => `${k} neue Mails` });
    const a = d.melde(mail('a', 'Eins'))!;
    expect(a.zusammengefasst).toBe(false);
    const b = d.melde(mail('b', 'Zwei'))!;
    expect(b.zusammengefasst).toBe(true);
    d.melde(mail('c', 'Drei'));
    const z = d.zustand;
    expect(z.verlauf).toHaveLength(1);
    expect(z.sichtbar[0]).toMatchObject({ titel: '3 neue Mails', anzahl: 3, text: 'Drei', stand: 2 });
  });

  it('nach der Sammelfrist oder nach dem Lesen beginnt eine neue Meldung', () => {
    const d = neu();
    const mail = (id: string): MeldungEingabe => ({ quelle: 'mail', schluessel: id, stufe: 'normal', titel: id, sammeln: (k) => `${k} neue Mails` });
    d.melde(mail('a'));
    jetzt += SAMMEL_MS + 1;
    d.melde(mail('b'));
    expect(d.zustand.verlauf).toHaveLength(2);
    d.lies(d.zustand.verlauf[0]!.id);
    d.melde(mail('c'));
    expect(d.zustand.verlauf).toHaveLength(3);
  });

  it('eine höhere Stufe in der Zusammenfassung hebt die ganze Meldung an', () => {
    const d = neu();
    const g = (id: string, stufe: 'normal' | 'hoch'): MeldungEingabe => ({ quelle: 'agent', schluessel: id, stufe, titel: id, sammeln: (k) => `${k} Nachrichten` });
    d.melde(g('a', 'normal'));
    d.melde(g('b', 'hoch'));
    expect(d.zustand.sichtbar[0]!.stufe).toBe('hoch');
  });
});

describe('Quellen, Nicht stören, Ruhe', () => {
  it('eine ausgeschaltete Quelle meldet nichts (auch nicht in den Verlauf)', () => {
    einst.quellen.mail = false;
    const d = neu();
    expect(d.melde(e({ quelle: 'mail' }))).toBeNull();
    expect(d.melde(e({ quelle: 'agent' }))).not.toBeNull();
    expect(d.zustand.verlauf).toHaveLength(1);
  });

  it('Nicht stören (von Hand): nur Verlauf, kein Toast, keine Systemmitteilung; kritisch durchbricht, wenn gewünscht', () => {
    einst.nichtStoeren.manuell = true;
    const d = neu();
    expect(d.melde(e({ stufe: 'hoch' }))).toMatchObject({ toast: false, system: false });
    expect(d.zustand.sichtbar).toHaveLength(0);
    expect(d.zustand.verlauf).toHaveLength(1);
    expect(d.zustand.ungelesen).toBe(1);
    expect(d.melde(e({ stufe: 'kritisch', quelle: 'stoerung' }))).toMatchObject({ toast: true, system: true });
    einst.nichtStoeren.kritischDurchbrechen = false;
    expect(d.melde(e({ stufe: 'kritisch', quelle: 'stoerung' }))).toMatchObject({ toast: false, system: false });
  });

  it('Zeitfenster über Mitternacht', () => {
    expect(imFenster('22:00', '07:00', new Date('2026-10-28T23:30:00'))).toBe(true);
    expect(imFenster('22:00', '07:00', new Date('2026-10-28T06:59:00'))).toBe(true);
    expect(imFenster('22:00', '07:00', new Date('2026-10-28T07:00:00'))).toBe(false);
    expect(imFenster('22:00', '07:00', new Date('2026-10-28T12:00:00'))).toBe(false);
    expect(imFenster('08:00', '18:00', new Date('2026-10-28T12:00:00'))).toBe(true);
    expect(imFenster('08:00', '08:00', new Date('2026-10-28T08:00:00'))).toBe(false);
  });

  it('Nicht stören nach Uhrzeit wirkt nur im Fenster', () => {
    einst.nichtStoeren.zeit = true;
    const d = neu();
    jetzt = Date.parse('2026-10-28T23:00:00');
    expect(nichtStoerenAktiv(einst, new Date(jetzt))).toBe(true);
    expect(d.melde(e())).toMatchObject({ toast: false });
    jetzt = Date.parse('2026-10-29T09:00:00');
    expect(d.melde(e())).toMatchObject({ toast: true });
  });

  it('Ruhe von Agent/Spielmodus wirkt wie Nicht stören, wenn beachtet; Kritisches bleibt', () => {
    const d = neu();
    ruhe = true;
    expect(d.melde(e())).toMatchObject({ toast: false });
    expect(d.melde(e({ stufe: 'kritisch', quelle: 'stoerung' }))).toMatchObject({ toast: true });
    einst.ruheBeachten = false;
    expect(d.melde(e())).toMatchObject({ toast: true });
  });

  it('nurVerlauf legt still ab', () => {
    const d = neu();
    expect(d.melde(e({ nurVerlauf: true, stufe: 'kritisch' }))).toMatchObject({ toast: false, system: false });
  });

  it('Hörer bekommen den Zustand und jede neue Meldung; ein Fehler eines Hörers stört die anderen nicht', () => {
    const d = neu();
    const z = vi.fn();
    const a = vi.fn();
    d.abonniere(z);
    d.beiNeu(() => {
      throw new Error('kaputt');
    });
    d.beiNeu(a);
    d.melde(e());
    expect(a).toHaveBeenCalledTimes(1);
    expect(z.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});

describe('Einstellungen', () => {
  it('bereinige: Vorgaben bei Müll, gültige Werte bleiben', () => {
    expect(bereinige(null)).toEqual(VORGABE);
    expect(bereinige('x')).toEqual(VORGABE);
    const b = bereinige({ quellen: { mail: false, agent: 'ja' }, mailOrdner: [], system: false, nichtStoeren: { von: '25:00', bis: '06:30', zeit: true } });
    expect(b.quellen.mail).toBe(false);
    expect(b.quellen.agent).toBe(true);
    expect(b.mailOrdner).toEqual(['INBOX']);
    expect(b.system).toBe(false);
    expect(b.nichtStoeren).toMatchObject({ von: '22:00', bis: '06:30', zeit: true, kritischDurchbrechen: true });
  });

  it('Vorgabe: alle Quellen an, Mail nur Posteingang, Systemmitteilungen an', () => {
    expect(Object.values(VORGABE.quellen).every(Boolean)).toBe(true);
    expect(VORGABE.mailOrdner).toEqual(['INBOX']);
    expect(VORGABE.system).toBe(true);
  });

  it('lesen/schreiben gehen durch den Speicher und überstehen einen kaputten oder fehlenden Speicher', () => {
    const daten = new Map<string, string>();
    const sp = { getItem: (k: string) => daten.get(k) ?? null, setItem: (k: string, v: string) => void daten.set(k, v) };
    schreiben({ ...VORGABE, system: false }, sp);
    expect(daten.has(SCHLUESSEL)).toBe(true);
    expect(lesen(sp).system).toBe(false);
    daten.set(SCHLUESSEL, '{kaputt');
    expect(lesen(sp)).toEqual(VORGABE);
    expect(lesen(null)).toEqual(VORGABE);
    expect(() => schreiben(VORGABE, { setItem: () => { throw new Error('voll'); } })).not.toThrow();
  });

  it('stillHalten: ohne Nicht stören nie', () => {
    expect(stillHalten(VORGABE, 'normal', new Date('2026-10-28T23:00:00'), false)).toBe(false);
    expect(stillHalten(VORGABE, 'normal', new Date('2026-10-28T23:00:00'), true)).toBe(true);
  });
});
