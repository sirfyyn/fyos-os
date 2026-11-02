/**
 * Datenschutz und Merker (29.10.2026, du): Systemmitteilungen zeigen für Mail nur „Neue Mail“ und für Agent nur „Agent hat geschrieben“,
 * solange „Details in Systemmitteilungen“ aus ist (Vorgabe); der Toast im OS zeigt weiter Absender, Betreff und den kurzen Auszug.
 * Kritische Freigaben beim ersten Abruf: genau einmal als Toast, je Id, auch nach Neuladen, Ablauf nach 24 h; die übrigen nur im Verlauf.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Freigabe } from '~/lib/agent-runner/typen';
import { Meldungsdienst } from '~/lib/os/meldungen';
import { VORGABE, bereinige, type MeldungenEinstellungen } from '~/lib/os/meldungen-einstellungen';
import { MERKER_MS, agentMeldung, mailMeldung, quellenStarten, speicherMerker, type Anschluesse } from '~/lib/os/meldungen-quellen';
import { SystemMitteilungen, type HuelleBruecke } from '~/lib/os/meldungen-system';

const JETZT = Date.parse('2026-10-29T10:00:00Z');

describe('Vorgabe', () => {
  it('Details in Systemmitteilungen sind aus; ungültige Werte bleiben aus', () => {
    expect(VORGABE.systemDetails).toBe(false);
    expect(bereinige({ systemDetails: 'ja' }).systemDetails).toBe(false);
    expect(bereinige({ systemDetails: true }).systemDetails).toBe(true);
  });
});

describe('Systemmitteilung ohne Details', () => {
  let einst: MeldungenEinstellungen;
  let h: HuelleBruecke & { benachrichtigen: ReturnType<typeof vi.fn> };
  let d: Meldungsdienst;
  let s: SystemMitteilungen;
  beforeEach(() => {
    einst = structuredClone(VORGABE);
    h = { benachrichtigen: vi.fn(async () => ({ gezeigt: true })) };
    d = new Meldungsdienst({ einstellungen: () => einst, jetzt: () => JETZT });
    s = new SystemMitteilungen({ einstellungen: () => einst, umgebung: () => ({ huelle: h }), hintergrund: () => true, oeffne: () => {}, gelesen: () => {} });
  });

  it('Mail: Toast mit Absender und Betreff, System nur „Neue Mail“; Zusammenfassung „2 neue Mails“ ohne Namen', async () => {
    const a = d.melde(mailMeldung({ id: 'a', absender: 'Eva Beispiel', betreff: 'Rechnung' }))!;
    expect(a.meldung).toMatchObject({ titel: 'Neue Mail von Eva Beispiel', text: 'Rechnung' });
    await s.beiNeu(a);
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('Neue Mail', '', { still: true });
    const b = d.melde(mailMeldung({ id: 'b', absender: 'Bob', betreff: 'Geheim' }))!;
    expect(b.meldung.titel).toBe('2 neue Mails');
    await s.beiNeu(b);
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('2 neue Mails', '', { still: true });
    expect(JSON.stringify(h.benachrichtigen.mock.calls)).not.toMatch(/Eva|Bob|Rechnung|Geheim/);
  });

  it('Agent: Toast mit Auszug, System nur „Agent hat geschrieben“', async () => {
    const a = d.melde(agentMeldung('Wohnung', 'Das Licht ist an.', 7, 1))!;
    expect(a.meldung.text).toBe('Das Licht ist an.');
    await s.beiNeu(a);
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('Agent hat geschrieben', '', { still: true });
  });

  it('mit dem Schalter an: volle Fassung', async () => {
    einst.systemDetails = true;
    await s.beiNeu(d.melde(mailMeldung({ id: 'c', absender: 'Eva', betreff: 'Rechnung' }))!);
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('Neue Mail von Eva', 'Rechnung', { still: true });
  });

  it('Meldungen ohne sichere Fassung (Freigabe, Störung) bleiben unverändert', async () => {
    const a = d.melde({ quelle: 'stoerung', schluessel: 'x', stufe: 'kritisch', titel: 'Dienst ausgefallen: a', text: 'weg' })!;
    await s.beiNeu(a);
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('Dienst ausgefallen: a', 'weg', { still: false });
  });
});

describe('Kritische Freigaben beim ersten Abruf', () => {
  const fg = (id: string, risiko: string): Freigabe => ({ id, status: 'offen', risiko, aktion: 'Pod löschen' });
  let t = JETZT;
  let daten: Map<string, string>;
  const sp = () => ({ getItem: (k: string) => daten.get(k) ?? null, setItem: (k: string, v: string) => void daten.set(k, v) });
  let aus: (() => void) | undefined;

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(JETZT);
    t = JETZT;
    daten = new Map();
  });
  afterEach(() => {
    aus?.();
    aus = undefined;
    vi.useRealTimers();
  });

  async function start(liste: Freigabe[]) {
    const gemeldet: Array<{ schluessel: string; nurVerlauf?: boolean; stufe: string }> = [];
    const a: Anschluesse = {
      einstellungen: () => ({ ...structuredClone(VORGABE), quellen: { agent: false, freigabe: true, stoerung: false, termin: false, mail: false } }),
      melde: (e) => void gemeldet.push(e as never),
      jetzt: () => t,
      setInterval: (f, ms) => setInterval(f, ms),
      clearInterval: (x) => clearInterval(x as never),
      setTimeout: (f, ms) => setTimeout(f, ms),
      clearTimeout: (x) => clearTimeout(x as never),
      bus: () => () => {},
      freigaben: async () => liste,
      freigabenAenderung: () => () => {},
      stromZeilen: () => () => {},
      agentVorn: () => false,
      merker: speicherMerker(sp(), () => t),
      kalender: async () => ({}),
      mail: async () => ({}),
    };
    aus = quellenStarten(a);
    await vi.advanceTimersByTimeAsync(0);
    aus();
    aus = undefined;
    return gemeldet;
  }

  it('kritische einmal als Toast, die anderen nur Verlauf; nach Neuladen die kritische nur noch im Verlauf', async () => {
    const liste = [fg('k', 'high'), fg('m', 'medium'), fg('n', 'low')];
    const erster = await start(liste);
    expect(erster.find((m) => m.schluessel === 'k')).toMatchObject({ stufe: 'kritisch' });
    expect(erster.find((m) => m.schluessel === 'k')!.nurVerlauf).toBeUndefined();
    expect(erster.filter((m) => m.schluessel !== 'k').every((m) => m.nurVerlauf === true)).toBe(true);
    // Neuladen: gleicher Speicher
    const zweiter = await start(liste);
    expect(zweiter.find((m) => m.schluessel === 'k')!.nurVerlauf).toBe(true);
  });

  it('nach 24 h kommt dieselbe noch offene Freigabe wieder einmal als Toast', async () => {
    await start([fg('k', 'high')]);
    t += MERKER_MS - 1000;
    expect((await start([fg('k', 'high')]))[0]!.nurVerlauf).toBe(true);
    t += 2 * MERKER_MS;
    expect((await start([fg('k', 'high')]))[0]!.nurVerlauf).toBeUndefined();
  });

  it('Merker: Ablauf, kaputter und gesperrter Speicher', () => {
    const m = speicherMerker(sp(), () => t);
    expect(m.gesehen('x')).toBe(false);
    m.merke('x');
    expect(m.gesehen('x')).toBe(true);
    t += MERKER_MS + 1;
    expect(m.gesehen('x')).toBe(false);
    daten.set('fyos:os:meldungen:freigaben', '{kaputt');
    expect(speicherMerker(sp(), () => t).gesehen('x')).toBe(false);
    const gesperrt = speicherMerker({ getItem: () => { throw new Error('gesperrt'); }, setItem: () => { throw new Error('gesperrt'); } }, () => t);
    gesperrt.merke('y');
    expect(gesperrt.gesehen('y')).toBe(true);
  });
});
