/**
 * Anwendungen statt Widgets: die Art einer Fläche, große Fenster, Maximieren und der Vollbild-Bildschirm.
 * Reine Funktionen (anordnung.ts, bildschirme.ts) und was Hub und Verzeichnis daraus machen (gesicht.ts, flaechen.ts).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { gesichtVon } from '~/lib/mcp-apps/gesicht';
import {
  SPALTEN, ZEILEN_MAX, ZEILEN_MIN, fensterPruefen, listePruefen, maximieren, oeffnen, zeilenFuerHoehe, type Fenster,
} from '~/lib/os/anordnung';
import {
  BILDSCHIRME_MAX, flaecheOeffnen, fensterAendern, istVollbild, laden, leer, neuerBildschirm, pruefen, speichern, verschiebenNach, vollbildAn,
  vollbildAus, wo, type Arbeitsplatz,
} from '~/lib/os/bildschirme';
import { alleFlaechen, hubFlaechen } from '~/lib/os/flaechen';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
});
afterEach(() => registerZuruecksetzen());

const f = (id: string, extra: Partial<Fenster> = {}): Fenster => ({ id, min: false, ...extra });
const ids = (ap: Arbeitsplatz, i: number) => ap.bildschirme[i - 1]!.fenster.map((w) => w.id);
/** Ein Arbeitsplatz mit den gegebenen Bildschirmen (Fenster-IDs), der erste ist aktiv. */
const platz = (...bildschirme: string[][]): Arbeitsplatz => {
  let ap = leer();
  for (const l of bildschirme) ap = neuerBildschirm(ap, undefined, l.map((id) => f(id)));
  return { ...ap, aktiv: 1, zuletzt: 1 };
};

describe('Art der Fläche (Widget oder Anwendung)', () => {
  const app = (name: string, extra: Record<string, unknown> = {}) =>
    ({ name, tool: name.replace('__', '.'), title: name, description: '', inputSchema: {}, _meta: { ui: { resourceUri: `ui://${name}` } }, scope: 'READ', ...extra }) as never;

  it('das Gesicht trägt die Art vom Hub; ohne Angabe oder mit Unbekanntem ist es ein Widget', () => {
    expect(gesichtVon(app('dateien__liste', { art: 'anwendung' })).art).toBe('anwendung');
    expect(gesichtVon(app('x__y', { _meta: { ui: { resourceUri: 'ui://y' }, app: { art: 'anwendung' } } })).art).toBe('anwendung');
    expect(gesichtVon(app('haus__favoriten', { art: 'widget' })).art).toBe('widget');
    expect(gesichtVon(app('haus__favoriten')).art).toBe('widget');
    expect(gesichtVon(app('haus__favoriten', { art: 'fenster' })).art).toBe('widget');
  });

  it('Hub-Apps werden zur Anwendung, wenn der Hub es sagt; alles andere bleibt ein Widget', () => {
    const l = hubFlaechen([app('dateien__liste', { art: 'anwendung' }), app('haus__favoriten', { art: 'widget' }), app('lage__bild')]);
    const nach = Object.fromEntries(l.map((x) => [x.id, x.anwendung]));
    expect(nach).toEqual({ 'app:dateien__liste': true, 'app:haus__favoriten': undefined, 'app:lage__bild': undefined });
  });

  it('eine registrierte Fläche kann selbst eine Anwendung sein', () => {
    registriereFlaechen({ flaechen: [{ id: 'seite:editor', titel: 'Editor', gruppe: 'Arbeit', art: 'seite', kuerzel: 'Ed', pfad: '/editor/', anwendung: true }] });
    expect(alleFlaechen([]).find((x) => x.id === 'seite:editor')?.anwendung).toBe(true);
  });
});

describe('Große Fenster', () => {
  it('zeilenFuerHoehe: so viele Rasterzeilen, wie hineinpassen, begrenzt', () => {
    expect(zeilenFuerHoehe(800, 16)).toBe(15); // (50 - 1,25) / 3,25
    expect(zeilenFuerHoehe(0, 16)).toBe(ZEILEN_MIN);
    expect(zeilenFuerHoehe(100000, 16)).toBe(ZEILEN_MAX);
    expect(zeilenFuerHoehe(800, 0)).toBe(15); // ohne gültige Schrift gelten 16 px
  });

  it('eine Anwendung öffnet über die ganze Breite, so hoch wie der Bildschirm, mit festgehaltener Höhe', () => {
    const l = oeffnen([f('a')], 'dateien', { gross: 14 });
    expect(l[1]).toEqual({ id: 'dateien', min: false, spalten: SPALTEN, zeilen: 14, fest: true });
  });

  it('ein Widget öffnet wie bisher: Automatik, bei Handanordnung halbe Breite', () => {
    expect(oeffnen([f('a')], 'w')[1]).toEqual({ id: 'w', min: false });
    expect(oeffnen([f('a', { spalten: 6, zeilen: 10 })], 'w')[1]).toMatchObject({ spalten: 6, zeilen: 10 });
  });

  it('die Größe einer großen Anwendung wird begrenzt', () => {
    expect(oeffnen([], 'x', { gross: 999 })[0]!.zeilen).toBe(ZEILEN_MAX);
    expect(oeffnen([], 'x', { gross: 0 })[0]!.zeilen).toBe(ZEILEN_MIN);
  });
});

describe('Maximieren', () => {
  it('maximiert ein Fenster, hält seine Höhe fest und beendet es wieder; unbekannte IDs ändern nichts', () => {
    const l = [f('a'), f('b')];
    const m = maximieren(l, 'a', true);
    expect(m[0]).toEqual({ id: 'a', min: false, max: true, fest: true });
    expect(m[1]).toBe(l[1]);
    const zu = maximieren(m, 'a', false);
    expect(zu[0]).toEqual({ id: 'a', min: false, fest: true }); // die Höhe bleibt festgehalten, der Inhalt baut sich nicht neu auf
    expect(maximieren(l, 'weg', true)).toBe(l);
  });

  it('höchstens ein Fenster je Bildschirm ist maximiert', () => {
    const m = maximieren(maximieren([f('a'), f('b')], 'a', true), 'b', true);
    expect(m.map((w) => !!w.max)).toEqual([false, true]);
  });

  it('ein neues oder nach vorn geholtes Fenster beendet die Maximierung der anderen', () => {
    const m = maximieren([f('a'), f('b')], 'a', true);
    expect(oeffnen(m, 'c').map((w) => !!w.max)).toEqual([false, false, false]);
    expect(oeffnen(m, 'b').map((w) => !!w.max)).toEqual([false, false]);
    expect(oeffnen(m, 'a')[0]!.max).toBe(true); // das maximierte selbst bleibt es
  });

  it('wird gespeichert und geprüft: max bleibt, doppeltes Maximieren zählt nur das erste', () => {
    expect(fensterPruefen({ id: 'a', max: true })).toEqual({ id: 'a', min: false, max: true });
    expect(fensterPruefen({ id: 'a', max: 'ja' })).toEqual({ id: 'a', min: false });
    expect(listePruefen([{ id: 'a', max: true }, { id: 'b', max: true }]).map((w) => !!w.max)).toEqual([true, false]);
  });
});

describe('Vollbild-Bildschirm', () => {
  it('eine Anwendung neben anderen Fenstern bekommt einen eigenen Bildschirm direkt dahinter und ist dort maximiert', () => {
    const ap = vollbildAn(platz(['a', 'dateien'], ['b']), 'dateien');
    expect(ap.bildschirme).toHaveLength(3);
    expect(ids(ap, 1)).toEqual(['a']);
    expect(ids(ap, 2)).toEqual(['dateien']);
    expect(ids(ap, 3)).toEqual(['b']);
    expect(ap.bildschirme[1]).toMatchObject({ vollbild: true, vollbildVon: ap.bildschirme[0]!.id });
    expect(ap.bildschirme[1]!.fenster[0]).toMatchObject({ max: true, fest: true, min: false });
    expect(ap.aktiv).toBe(2);
    expect(ap.zuletzt).toBe(2);
    expect(istVollbild(ap, 2)).toBe(true);
    expect(istVollbild(ap, 1)).toBe(false);
  });

  it('ist die Anwendung allein auf ihrem Bildschirm, wird dieser selbst zum Vollbild-Bildschirm (keiner bleibt leer zurück)', () => {
    const ap = vollbildAn(platz(['dateien'], ['b']), 'dateien');
    expect(ap.bildschirme).toHaveLength(2);
    expect(ap.bildschirme[0]).toMatchObject({ vollbild: true });
    expect(ap.bildschirme[0]!.vollbildVon).toBeUndefined();
    expect(ap.bildschirme[0]!.fenster[0]!.max).toBe(true);
    expect(ap.aktiv).toBe(1);
  });

  it('bei vollen BILDSCHIRME_MAX bleibt alles, wie es ist (der Aufrufer meldet es)', () => {
    let ap = platz(['dateien', 'x']);
    for (let i = 1; i < BILDSCHIRME_MAX; i++) ap = neuerBildschirm(ap, undefined, [f(`w${i}`)]);
    expect(ap.bildschirme).toHaveLength(BILDSCHIRME_MAX);
    expect(vollbildAn(ap, 'dateien')).toBe(ap);
  });

  it('was nicht offen oder schon im Vollbild ist, ändert nichts', () => {
    const ap = vollbildAn(platz(['a', 'dateien']), 'dateien');
    expect(vollbildAn(ap, 'dateien')).toBe(ap);
    expect(vollbildAn(ap, 'gibtsnicht')).toBe(ap);
  });

  it('beim Verlassen kehrt die Anwendung auf ihren Bildschirm zurück, ohne Maximierung; der Vollbild-Bildschirm verschwindet', () => {
    const an = vollbildAn(platz(['a', 'dateien'], ['b']), 'dateien');
    const aus = vollbildAus(an, 2);
    expect(aus.bildschirme).toHaveLength(2);
    expect(ids(aus, 1)).toEqual(['a', 'dateien']);
    expect(ids(aus, 2)).toEqual(['b']);
    expect(aus.bildschirme[0]!.fenster[1]).toEqual({ id: 'dateien', min: false, fest: true });
    expect(aus.aktiv).toBe(1);
    expect(aus.bildschirme.some((b) => b.vollbild)).toBe(false);
  });

  it('liegt der alte Bildschirm hinter dem Vollbild-Bildschirm, stimmt die Nummer nach dem Entfernen', () => {
    const ap = platz(['a'], ['b', 'dateien']);
    const an = vollbildAn(ap, 'dateien'); // Bildschirme: a | b | dateien(Vollbild)
    expect(an.bildschirme).toHaveLength(3);
    const aus = vollbildAus(an, 3);
    expect(ids(aus, 2)).toEqual(['b', 'dateien']);
    expect(aus.aktiv).toBe(2);
    // Von einem Bildschirm davor kommend: der Vollbild-Bildschirm steht hinter dem Heimatbildschirm, dann zählt das Entfernen
    const a2 = vollbildAn(platz(['b', 'dateien'], ['c']), 'dateien'); // b | dateien(Vollbild) | c
    const z2 = vollbildAus(a2, 2);
    expect(z2.bildschirme).toHaveLength(2);
    expect(ids(z2, 1)).toEqual(['b', 'dateien']);
    expect(ids(z2, 2)).toEqual(['c']);
    expect(z2.aktiv).toBe(1);
  });

  it('der Heimatbildschirm ist weg oder die Anwendung war allein: der Bildschirm bleibt, als gewöhnlicher', () => {
    const allein = vollbildAus(vollbildAn(platz(['dateien'], ['b']), 'dateien'), 1);
    expect(allein.bildschirme[0]).toMatchObject({ fenster: [{ id: 'dateien', min: false, fest: true }] });
    expect(allein.bildschirme[0]!.vollbild).toBeUndefined();
    const an = vollbildAn(platz(['a', 'dateien'], ['b']), 'dateien');
    const ohneHeimat = { ...an, bildschirme: an.bildschirme.filter((b) => b.id !== an.bildschirme[1]!.vollbildVon) };
    const aus = vollbildAus({ ...ohneHeimat, aktiv: 1 }, 1);
    expect(aus.bildschirme[0]!.vollbild).toBeUndefined();
    expect(ids(aus, 1)).toEqual(['dateien']);
    expect(aus.bildschirme[0]!.fenster[0]!.max).toBeUndefined();
  });

  it('vollbildAus auf einem gewöhnlichen Bildschirm ändert nichts', () => {
    const ap = platz(['a']);
    expect(vollbildAus(ap, 1)).toBe(ap);
    expect(vollbildAus(ap, 7)).toBe(ap);
  });

  it('Fenster ziehen weder auf einen Vollbild-Bildschirm noch von ihm weg', () => {
    const an = vollbildAn(platz(['a', 'dateien'], ['b']), 'dateien'); // a | dateien(V) | b
    expect(verschiebenNach(an, 'b', 2)).toBe(an);
    expect(verschiebenNach(an, 'dateien', 1)).toBe(an);
    expect(ids(verschiebenNach(an, 'b', 1), 1)).toEqual(['a', 'b']);
  });

  it('ein verschobenes Fenster ist nirgends mehr maximiert, und der Zielbildschirm auch nicht', () => {
    const ap = platz(['a'], ['b']);
    const mit = fensterAendern(ap, 1, (l) => maximieren(l, 'a', true));
    const weg = verschiebenNach(mit, 'a', 2);
    expect(weg.bildschirme[1]!.fenster.every((w) => !w.max)).toBe(true);
    const mit2 = fensterAendern(ap, 2, (l) => maximieren(l, 'b', true));
    const dazu = verschiebenNach(mit2, 'a', 2);
    expect(dazu.bildschirme[1]!.fenster.every((w) => !w.max)).toBe(true);
  });

  it('eine neue Fläche vom Vollbild-Bildschirm aus kommt auf einen anderen Bildschirm, nie in den Vollbild', () => {
    const an = vollbildAn(platz(['a', 'dateien'], ['b']), 'dateien'); // a | dateien(V) | b, aktiv 2
    const r = flaecheOeffnen(an, 'neu');
    expect(r.voll).toBe(false);
    expect(wo(r.ap, 'neu')).not.toBe(2);
    expect(ids(r.ap, 2)).toEqual(['dateien']);
  });

  it('gibt es nur den Vollbild-Bildschirm, entsteht für eine neue Fläche ein neuer', () => {
    const an = vollbildAn(platz(['dateien']), 'dateien');
    const r = flaecheOeffnen(an, 'neu');
    expect(r.ap.bildschirme).toHaveLength(2);
    expect(ids(r.ap, 1)).toEqual(['dateien']);
    expect(ids(r.ap, 2)).toEqual(['neu']);
  });

  it('eine Anwendung öffnet über flaecheOeffnen groß; eine schon offene wird nach vorn geholt und beendet fremde Maximierung', () => {
    const r = flaecheOeffnen(leer(), 'dateien', { gross: 12 });
    expect(r.ap.bildschirme[0]!.fenster[0]).toMatchObject({ id: 'dateien', spalten: SPALTEN, zeilen: 12, fest: true });
    const mit = fensterAendern(platz(['a', 'b']), 1, (l) => maximieren(l, 'a', true));
    const vorn = flaecheOeffnen(mit, 'b');
    expect(vorn.ap.bildschirme[0]!.fenster.map((w) => !!w.max)).toEqual([false, false]);
  });

  it('schließt jemand die Anwendung im Vollbild, bleibt ein gewöhnlicher leerer Bildschirm (kein Vollbild ohne Anwendung)', () => {
    const an = vollbildAn(platz(['a', 'dateien']), 'dateien');
    const zu = fensterAendern(an, 2, () => []);
    expect(zu.bildschirme[1]!.vollbild).toBeUndefined();
    expect(zu.bildschirme[1]!.vollbildVon).toBeUndefined();
  });

  it('wird gespeichert und wieder geladen; Vollbild ohne genau ein Fenster ist ein gewöhnlicher Bildschirm', () => {
    const an = vollbildAn(platz(['a', 'dateien']), 'dateien');
    speichern(an);
    const geladen = laden();
    expect(geladen.bildschirme[1]).toMatchObject({ vollbild: true, vollbildVon: an.bildschirme[0]!.id });
    expect(geladen.bildschirme[1]!.fenster[0]!.max).toBe(true);
    const kaputt = pruefen({ bildschirme: [{ id: 'x', name: 'X', vollbild: true, fenster: [{ id: 'a' }, { id: 'b' }] }, { id: 'y', name: 'Y', vollbild: true, fenster: [] }] });
    expect(kaputt.bildschirme.every((b) => !b.vollbild)).toBe(true);
    const gut = pruefen({ bildschirme: [{ id: 'x', name: 'X', vollbild: true, vollbildVon: 'w', fenster: [{ id: 'a' }] }] });
    expect(gut.bildschirme[0]).toMatchObject({ vollbild: true, vollbildVon: 'w' });
    expect(gut.bildschirme[0]!.fenster[0]!.max).toBe(true);
  });
});
