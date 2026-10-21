/**
 * Das Werkzeug-Register als gemeinsame Quelle für WebMCP und OS-Brücke (lib/werkzeuge.ts):
 * `fuerBruecke` (Meldeformat), `rufenFuerBruecke` (nur Freigegebenes) und `beiAenderung`.
 *
 * `astro:transitions/client` löst vitest.config.ts dafür auf einen Stub auf.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BRUECKE_MAX_BESCHREIBUNG,
  BRUECKE_MAX_SCHEMA_BYTES,
  BRUECKE_MAX_WERKZEUGE,
  beiAenderung,
  fuerBruecke,
  liste,
  registriereWerkzeuge,
  rufen,
  rufenFuerBruecke,
  type Werkzeug,
} from '../../src/lib/werkzeuge';

const w = (name: string, extra: Partial<Werkzeug> = {}): Werkzeug => ({ name, beschreibung: `Beschreibung ${name}`, ausfuehren: async () => ({ von: name }), ...extra });

const abmelder: (() => void)[] = [];
const melde = (...a: Parameters<typeof registriereWerkzeuge>) => {
  const ab = registriereWerkzeuge(...a);
  abmelder.push(ab);
  return ab;
};

afterEach(() => {
  while (abmelder.length) abmelder.pop()!();
  document.documentElement.classList.remove('fyos-bare');
});

describe('fuerBruecke', () => {
  it('liefert Name, Beschreibung, Schema und lesend — nach Namen sortiert', () => {
    melde([w('rt_b', { lesend: true }), w('rt_a', { eingabe: { properties: { x: { type: 'string' } }, required: ['x'] } })], { dauerhaft: true });
    const l = fuerBruecke().filter((x) => x.name.startsWith('rt_'));
    expect(l.map((x) => x.name)).toEqual(['rt_a', 'rt_b']);
    expect(l[0]).toEqual({
      name: 'rt_a',
      beschreibung: 'Beschreibung rt_a',
      lesend: false,
      eingabe: { type: 'object', properties: { x: { type: 'string' } }, required: ['x'] },
    });
    expect(l[1]).toEqual({ name: 'rt_b', beschreibung: 'Beschreibung rt_b', lesend: true, eingabe: { type: 'object', properties: {} } });
  });

  it('lässt Werkzeuge mit bruecke:false weg, sie bleiben aber für WebMCP und window.fyos da', () => {
    melde([w('rt_frei'), w('rt_nur_hub', { bruecke: false }), w('rt_ausdruecklich', { bruecke: true })], { dauerhaft: true });
    const namen = fuerBruecke().map((x) => x.name);
    expect(namen).toContain('rt_frei');
    expect(namen).toContain('rt_ausdruecklich');
    expect(namen).not.toContain('rt_nur_hub');
    expect(liste().map((x) => x.name)).toContain('rt_nur_hub');
  });

  it('kürzt eine lange Beschreibung auf 300 Zeichen und lässt kurze, wie sie sind', () => {
    melde([w('rt_lang', { beschreibung: 'ä'.repeat(500) }), w('rt_genau', { beschreibung: 'g'.repeat(BRUECKE_MAX_BESCHREIBUNG) })], { dauerhaft: true });
    const l = Object.fromEntries(fuerBruecke().map((x) => [x.name, x.beschreibung]));
    expect(l.rt_lang).toHaveLength(BRUECKE_MAX_BESCHREIBUNG);
    expect(l.rt_lang!.endsWith('…')).toBe(true);
    expect(l.rt_genau).toBe('g'.repeat(BRUECKE_MAX_BESCHREIBUNG));
  });

  it('lässt ein Schema über 2 KB weg — das Werkzeug bleibt in der Liste', () => {
    const gross = { properties: Object.fromEntries(Array.from({ length: 80 }, (_, i) => [`feld_${i}`, { type: 'string', description: 'x'.repeat(30) }])) };
    expect(new TextEncoder().encode(JSON.stringify(gross)).length).toBeGreaterThan(BRUECKE_MAX_SCHEMA_BYTES);
    melde([w('rt_gross', { eingabe: gross }), w('rt_klein', { eingabe: { properties: {} } })], { dauerhaft: true });
    const l = Object.fromEntries(fuerBruecke().map((x) => [x.name, x]));
    expect(l.rt_gross).toBeDefined();
    expect(l.rt_gross).not.toHaveProperty('eingabe');
    expect(l.rt_klein).toHaveProperty('eingabe');
  });

  it('meldet höchstens 64 Werkzeuge', () => {
    melde(Array.from({ length: 80 }, (_, i) => w(`rt_viele_${String(i).padStart(2, '0')}`)), { dauerhaft: true });
    expect(fuerBruecke()).toHaveLength(BRUECKE_MAX_WERKZEUGE);
  });

  it('ist stabil: dieselbe Liste ergibt dieselbe Meldung', () => {
    melde([w('rt_z'), w('rt_y')], { dauerhaft: true });
    expect(JSON.stringify(fuerBruecke())).toBe(JSON.stringify(fuerBruecke()));
  });

  it('meldet das Werkzeug nicht mehr, wenn es abgemeldet ist oder die Seite wechselt', () => {
    const ab = melde([w('rt_weg')], { dauerhaft: true });
    expect(fuerBruecke().map((x) => x.name)).toContain('rt_weg');
    ab();
    expect(fuerBruecke().map((x) => x.name)).not.toContain('rt_weg');
    registriereWerkzeuge([w('rt_seite')]);
    expect(fuerBruecke().map((x) => x.name)).toContain('rt_seite');
    document.dispatchEvent(new Event('astro:before-swap'));
    expect(fuerBruecke().map((x) => x.name)).not.toContain('rt_seite');
  });
});

describe('rufenFuerBruecke', () => {
  it('ruft ein freigegebenes Werkzeug', async () => {
    melde([w('rt_ok', { ausfuehren: async (a) => ({ echo: a }) })], { dauerhaft: true });
    const r = await rufenFuerBruecke('rt_ok', { x: 1 });
    expect(r.isError).toBeFalsy();
    expect(JSON.parse(r.content[0]!.text)).toEqual({ echo: { x: 1 } });
  });

  it('verweigert ein Werkzeug mit bruecke:false und sagt, was freigegeben ist', async () => {
    melde([w('rt_zu', { bruecke: false }), w('rt_offen')], { dauerhaft: true });
    const r = await rufenFuerBruecke('rt_zu', {});
    expect(r.isError).toBe(true);
    expect(r.content[0]!.text).toMatch(/rt_zu ist nicht für die Brücke freigegeben\. Freigegeben: .*rt_offen/);
    expect(r.content[0]!.text).not.toMatch(/Freigegeben:.*rt_zu(,|$)/);
    // über das Register direkt bleibt es erreichbar (WebMCP, window.fyos)
    expect((await rufen('rt_zu')).isError).toBeFalsy();
  });

  it('kennt ein unbekanntes Werkzeug nicht', async () => {
    const r = await rufenFuerBruecke('rt_gibtsnicht');
    expect(r.isError).toBe(true);
    expect(r.content[0]!.text).toMatch(/Unbekanntes Werkzeug: rt_gibtsnicht\. Verfügbar:/);
  });

  it('macht aus einem Wurf im Werkzeug ein Fehler-Ergebnis', async () => {
    melde(
      [
        w('rt_wurf', {
          ausfuehren: async () => {
            throw new Error('Backend weg');
          },
        }),
      ],
      { dauerhaft: true },
    );
    expect(await rufenFuerBruecke('rt_wurf')).toMatchObject({ isError: true, content: [{ text: 'Backend weg' }] });
  });
});

describe('beiAenderung', () => {
  it('meldet jede Änderung der Liste: anmelden und abmelden', () => {
    const f = vi.fn();
    const weg = beiAenderung(f);
    try {
      const ab = registriereWerkzeuge([w('rt_l1')], { dauerhaft: true });
      expect(f).toHaveBeenCalledTimes(1);
      ab();
      expect(f).toHaveBeenCalledTimes(2);
      ab(); // nichts mehr abzumelden
      expect(f).toHaveBeenCalledTimes(2);
    } finally {
      weg();
    }
  });

  it('auch der Seitenwechsel gilt als Änderung', () => {
    const f = vi.fn();
    const weg = beiAenderung(f);
    registriereWerkzeuge([w('rt_l2')]);
    expect(f).toHaveBeenCalledTimes(1);
    document.dispatchEvent(new Event('astro:before-swap'));
    expect(f).toHaveBeenCalledTimes(2);
    weg();
  });

  it('die Abmeldung des Lauschers wirkt; ein Lauscher, der wirft, stört weder die anderen noch die Anmeldung', () => {
    const still = vi.fn();
    const abmeldenStill = beiAenderung(still);
    abmeldenStill();
    const wirft = beiAenderung(() => {
      throw new Error('Lauscher kaputt');
    });
    const dahinter = vi.fn();
    const weg2 = beiAenderung(dahinter);
    expect(() => melde([w('rt_l3')], { dauerhaft: true })).not.toThrow();
    expect(still).not.toHaveBeenCalled();
    expect(dahinter).toHaveBeenCalledTimes(1);
    expect(fuerBruecke().map((x) => x.name)).toContain('rt_l3');
    wirft();
    weg2();
  });
});
