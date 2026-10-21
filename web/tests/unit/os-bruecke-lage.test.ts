/**
 * OS-Brücke, reiner Teil: die Lage des OS (lib/os/bruecke-lage.ts) und das Auflösen eines Worts zur Fläche.
 * („Der Agent zeigt dir …“: tests/unit/os-agent-zeigt.test.ts.)
 */
import { describe, expect, it } from 'vitest';
import { leer, type Arbeitsplatz } from '~/lib/os/bildschirme';
import {
  ANRUF_ID,
  FLAECHEN_MAX,
  falte,
  istSichtbarOffen,
  lageBauen,
  loeseAuf,
  loeseFensterAuf,
  type LageQuelle,
} from '~/lib/os/bruecke-lage';
import type { Flaeche, FlaechenArt } from '~/lib/os/flaechen';

const F = (id: string, titel: string, gruppe = 'Allgemein', art: FlaechenArt = 'seite'): Flaeche => ({ id, titel, gruppe, art, kuerzel: titel.slice(0, 2).toUpperCase() });

const FLAECHEN: Flaeche[] = [
  F('seite:berichte', 'Berichte', 'Arbeit'),
  F('seite:berichte-budget', 'Berichte Budget', 'Arbeit'),
  F('app:notizen__liste', 'Notizen', 'Notizen', 'hubapp'),
  F('seite:notizen-verlauf', 'Notizen-Verlauf', 'Notizen'),
  F('seite:uebersicht', 'Übersicht'),
  F('nativ:anruf', 'Anruf', 'Agent', 'nativ'),
  F('agent', 'Agent', 'Agent', 'agent'),
];
const flaecheVon = (id: string) => FLAECHEN.find((f) => f.id === id);

const platz = (bildschirme: { name: string; fenster: [string, boolean?][] }[], aktiv: number): Arbeitsplatz => ({
  bildschirme: bildschirme.map((b, i) => ({ id: `b${i}`, name: b.name, fenster: b.fenster.map(([id, min]) => ({ id, min: !!min })) })),
  aktiv,
  zuletzt: Math.max(1, aktiv),
});

const quelle = (ap: Arbeitsplatz, extra: Partial<LageQuelle> = {}): LageQuelle => ({ ap, fokus: null, agent: false, flaeche: flaecheVon, flaechen: FLAECHEN, ...extra });

describe('lageBauen', () => {
  it('beschreibt den leeren Start', () => {
    const l = lageBauen(quelle(leer()));
    expect(l).toMatchObject({
      anruf: false,
      agent_vorne: false,
      bildschirm: 0,
      bildschirme: [{ index: 0, name: 'Start' }],
      fenster: [],
    });
    expect(l.flaechen).toHaveLength(FLAECHEN.length);
    expect(l.flaechen[0]).toEqual({ id: 'seite:berichte', titel: 'Berichte', gruppe: 'Arbeit' });
  });

  it('listet Fenster aller Bildschirme und markiert das vorderste des aktiven', () => {
    const ap = platz(
      [
        { name: 'Arbeit', fenster: [['seite:berichte'], ['app:notizen__liste', true]] },
        { name: 'Lesen', fenster: [['seite:uebersicht']] },
      ],
      1,
    );
    const l = lageBauen(quelle(ap, { fokus: 'seite:berichte' }));
    expect(l.bildschirm).toBe(1);
    expect(l.bildschirme).toEqual([
      { index: 0, name: 'Start' },
      { index: 1, name: 'Arbeit' },
      { index: 2, name: 'Lesen' },
    ]);
    expect(l.fenster).toEqual([
      { id: 'seite:berichte', titel: 'Berichte', art: 'seite', bildschirm: 1, bildschirm_name: 'Arbeit', vorne: true, min: false },
      { id: 'app:notizen__liste', titel: 'Notizen', art: 'hubapp', bildschirm: 1, bildschirm_name: 'Arbeit', vorne: false, min: true },
      { id: 'seite:uebersicht', titel: 'Übersicht', art: 'seite', bildschirm: 2, bildschirm_name: 'Lesen', vorne: false, min: false },
    ]);
  });

  it('nimmt ohne Fokus das erste nicht minimierte Fenster als vorderstes — auch wenn der Fokus minimiert oder woanders ist', () => {
    const ap = platz([{ name: 'A', fenster: [['seite:berichte', true], ['seite:uebersicht'], ['app:notizen__liste']] }, { name: 'B', fenster: [['nativ:anruf', true]] }], 1);
    expect(lageBauen(quelle(ap)).fenster.filter((w) => w.vorne).map((w) => w.id)).toEqual(['seite:uebersicht']);
    expect(lageBauen(quelle(ap, { fokus: 'seite:berichte' })).fenster.filter((w) => w.vorne).map((w) => w.id)).toEqual(['seite:uebersicht']);
    expect(lageBauen(quelle(ap, { fokus: 'nativ:anruf' })).fenster.filter((w) => w.vorne).map((w) => w.id)).toEqual(['seite:uebersicht']);
  });

  it('lässt Fenster weg, deren Fläche es nicht mehr gibt', () => {
    const ap = platz([{ name: 'A', fenster: [['seite:weg'], ['seite:berichte']] }], 1);
    expect(lageBauen(quelle(ap)).fenster.map((w) => w.id)).toEqual(['seite:berichte']);
  });

  it('sagt „Agent vorn“, wenn der Anruf offen ist, der Agent-Dock offen ist oder das Agent-Fenster vorn liegt', () => {
    const mitAnruf = platz([{ name: 'A', fenster: [['seite:berichte'], [ANRUF_ID]] }], 1);
    expect(lageBauen(quelle(mitAnruf))).toMatchObject({ anruf: true, agent_vorne: true });
    const anrufMin = platz([{ name: 'A', fenster: [['seite:berichte'], [ANRUF_ID, true]] }], 1);
    expect(lageBauen(quelle(anrufMin))).toMatchObject({ anruf: false, agent_vorne: false });
    expect(lageBauen(quelle(anrufMin, { agent: true }))).toMatchObject({ anruf: false, agent_vorne: true });
    const agentFenster = platz([{ name: 'A', fenster: [['seite:berichte'], ['agent']] }], 1);
    expect(lageBauen(quelle(agentFenster, { fokus: 'agent' }))).toMatchObject({ anruf: false, agent_vorne: true });
    expect(lageBauen(quelle(agentFenster, { fokus: 'seite:berichte' }))).toMatchObject({ agent_vorne: false });
  });

  it('meldet höchstens 300 Flächen', () => {
    const viele = Array.from({ length: 450 }, (_, i) => F(`seite:s${i}`, `Seite ${i}`));
    expect(lageBauen(quelle(leer(), { flaechen: viele })).flaechen).toHaveLength(FLAECHEN_MAX);
  });
});

describe('istSichtbarOffen', () => {
  const ap = platz([{ name: 'A', fenster: [['seite:berichte'], ['seite:uebersicht', true]] }], 1);
  it('zählt offene, nicht minimierte Fenster', () => {
    expect(istSichtbarOffen({ ap, agent: false }, 'seite:berichte')).toBe(true);
    expect(istSichtbarOffen({ ap, agent: false }, 'seite:uebersicht')).toBe(false);
    expect(istSichtbarOffen({ ap, agent: false }, 'seite:nix')).toBe(false);
  });
  it('der Agent zählt auch als Dock', () => {
    expect(istSichtbarOffen({ ap, agent: true }, 'agent')).toBe(true);
    expect(istSichtbarOffen({ ap, agent: false }, 'agent')).toBe(false);
  });
});

describe('falte', () => {
  it('macht Umlaute, Akzente und Schreibweisen vergleichbar', () => {
    expect(falte('Übersicht')).toBe(falte('Uebersicht'));
    expect(falte('Übersicht')).toBe(falte('ubersicht'));
    expect(falte('Größe')).toBe(falte('Groesse'));
    expect(falte('Café  Au   Lait')).toBe('cafe au lait');
    expect(falte('  STRASSE ')).toBe(falte('Straße'));
  });
});

describe('loeseAuf', () => {
  const id = (ziel: unknown) => {
    const r = loeseAuf(ziel, FLAECHEN);
    return r.ok ? r.id : r;
  };

  it('nimmt eine ID, auch ohne Vorsatz und in Großbuchstaben', () => {
    expect(id('seite:berichte')).toBe('seite:berichte');
    expect(id('app:notizen__liste')).toBe('app:notizen__liste');
    expect(id('agent')).toBe('agent');
    expect(id('berichte')).toBe('seite:berichte');
    expect(id('notizen__liste')).toBe('app:notizen__liste');
    expect(id('anruf')).toBe('nativ:anruf');
    expect(id('SEITE:BERICHTE')).toBe('seite:berichte');
    expect(id('  seite:berichte  ')).toBe('seite:berichte');
  });

  it('löst ein Werkzeug mit derselben Oberfläche zur Fläche der App auf (Steuerpult: cluster__lage → cluster__knoten)', () => {
    const steuerpult: Flaeche = { ...F('app:cluster__knoten', 'Steuerpult', 'Agent & Betrieb', 'hubapp'), appName: 'cluster__knoten', mitglieder: ['cluster__knoten', 'cluster__lage'] };
    const liste = [...FLAECHEN, steuerpult];
    for (const ziel of ['app:cluster__lage', 'cluster__lage', 'APP:Cluster__Lage', 'app:cluster__knoten']) {
      const r = loeseAuf(ziel, liste);
      expect(r.ok && r.id).toBe('app:cluster__knoten');
    }
    // ein Werkzeug, das zu keiner Fläche gehört, bleibt ein ehrlicher Fehler
    expect(loeseAuf('app:cluster__gibtsnicht', liste)).toMatchObject({ ok: false });
    // Seiten haben keine Mitglieder
    expect(loeseAuf('app:berichte', liste)).toMatchObject({ ok: false });
  });

  it('findet einen Titel: erst genau, dann am Anfang, dann irgendwo — nur wenn es eindeutig ist', () => {
    expect(id('Berichte')).toBe('seite:berichte'); // genau, obwohl „Berichte Budget“ auch passen würde
    expect(id('Notizen')).toBe('app:notizen__liste');
    expect(id('Notizen-V')).toBe('seite:notizen-verlauf'); // Anfang
    expect(id('verlauf')).toBe('seite:notizen-verlauf'); // Teilstück
    expect(id('Uebersicht')).toBe('seite:uebersicht'); // ue = ü
    expect(id('Anr')).toBe('nativ:anruf');
  });

  it('nennt bei mehreren Treffern die Kandidaten', () => {
    const r = loeseAuf('Beri', FLAECHEN);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.fehler).toMatch(/mehrere Flächen/);
    expect(r.kandidaten).toEqual(['Berichte (seite:berichte)', 'Berichte Budget (seite:berichte-budget)']);
  });

  it('sagt ehrlich, wenn es die Fläche nicht gibt', () => {
    const a = loeseAuf('seite:gibtsnicht', FLAECHEN);
    expect(a).toMatchObject({ ok: false });
    expect(a.ok === false && a.fehler).toMatch(/gibt es hier nicht/);
    expect(a.ok === false && a.kandidaten?.length).toBeGreaterThan(0);
    const b = loeseAuf('Quantenküche', FLAECHEN);
    expect(b.ok === false && b.fehler).toMatch(/Keine Fläche passt.*Es gibt zum Beispiel: Berichte \(seite:berichte\), Berichte Budget/);
    expect(b.ok === false && b.kandidaten?.[0]).toBe('Berichte (seite:berichte)');
    expect(a.ok === false && a.fehler).toMatch(/Es gibt zum Beispiel: Berichte \(seite:berichte\)/);
  });

  it('ohne geladene Flächen sagt es das, statt Beispiele zu erfinden', () => {
    const r = loeseAuf('Berichte', []);
    expect(r.ok === false && r.fehler).toBe('Keine Fläche passt zu „Berichte“. Es sind noch keine Flächen geladen.');
    expect(r.ok === false && r.kandidaten).toEqual([]);
  });

  it('verlangt ein Ziel', () => {
    for (const leerziel of [undefined, null, '', '   ', 42, {}]) {
      const r = loeseAuf(leerziel, FLAECHEN);
      expect(r.ok).toBe(false);
      expect(r.ok === false && r.fehler).toMatch(/ziel fehlt/);
    }
  });
});

describe('loeseFensterAuf', () => {
  const ap = platz([{ name: 'A', fenster: [['seite:berichte'], ['seite:berichte-budget'], ['app:notizen__liste', true]] }], 1);
  const fenster = lageBauen(quelle(ap)).fenster;

  it('findet ID, Titel und Titelanfang', () => {
    expect(loeseFensterAuf('seite:berichte', fenster)).toMatchObject({ ok: true, fenster: { id: 'seite:berichte' } });
    expect(loeseFensterAuf('Berichte', fenster)).toMatchObject({ ok: true, fenster: { id: 'seite:berichte' } });
    expect(loeseFensterAuf('notizen', fenster)).toMatchObject({ ok: true, fenster: { id: 'app:notizen__liste' } });
    expect(loeseFensterAuf('budget', fenster)).toMatchObject({ ok: true, fenster: { id: 'seite:berichte-budget' } });
  });

  it('zählt auf, was offen ist, wenn nichts passt oder mehreres', () => {
    const mehrere = loeseFensterAuf('Beri', fenster);
    expect(mehrere.ok).toBe(false);
    expect(mehrere.ok === false && mehrere.fehler).toMatch(/mehrere offene Fenster.*Berichte \(seite:berichte\).*Berichte Budget/);
    const keins = loeseFensterAuf('Anruf', fenster);
    expect(keins.ok === false && keins.fehler).toMatch(/Kein offenes Fenster passt.*Offen: Berichte \(seite:berichte\)/);
    expect(loeseFensterAuf('x', []).ok === false && (loeseFensterAuf('x', []) as { fehler: string }).fehler).toMatch(/Offen: keines/);
    expect(loeseFensterAuf('', fenster)).toMatchObject({ ok: false });
  });
});
