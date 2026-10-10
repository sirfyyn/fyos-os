/**
 * Bildschirme des OS: Start (Zentrale) plus Arbeitsbildschirme, Wechsel nach links/rechts,
 * Öffnen vom Start aus, Verschieben, Entfernen, Speichern und das Übernehmen der alten Anordnung.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  BILDSCHIRME_MAX, START, anzeigeName, automatischBenannt, entfernen, flaecheOeffnen, fremdesSpeichern, idsUmbenennen, laden, leer, nachLinks, nachRechts, neuerBildschirm, pruefen, speichern,
  umbenennen, verschiebenNach, wechseln, wo,
} from '~/lib/os/bildschirme';

beforeEach(() => {
  const m = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
  });
});

const ids = (a: ReturnType<typeof leer>, i: number) => a.bildschirme[i - 1]!.fenster.map((w) => w.id);

describe('Bildschirme', () => {
  it('vom Start aus geöffnet landet eine Fläche auf einem Arbeitsbildschirm (neu, wenn keiner da ist)', () => {
    const r = flaecheOeffnen(leer(), 'seite:finance');
    expect(r.ap.aktiv).toBe(1);
    expect(r.ap.bildschirme[0]!.name).toBe('Bildschirm 1');
    expect(ids(r.ap, 1)).toEqual(['seite:finance']);
    // zurück zum Start, nächste Fläche: auf den zuletzt benutzten Bildschirm
    const r2 = flaecheOeffnen(wechseln(r.ap, START), 'seite:papra');
    expect(r2.ap.aktiv).toBe(1);
    expect(ids(r2.ap, 1)).toEqual(['seite:finance', 'seite:papra']);
  });

  it('voller Bildschirm: das Dock meldet „voll“, ein Link öffnet auf einem neuen Bildschirm', () => {
    let a = leer();
    for (let i = 0; i < 8; i++) a = flaecheOeffnen(a, `app:p${i}__x`).ap;
    expect(ids(a, 1)).toHaveLength(8);
    const dock = flaecheOeffnen(a, 'app:mcp__uebersicht');
    expect(dock.voll).toBe(true);
    expect(wo(dock.ap, 'app:mcp__uebersicht')).toBe(-1);
    const link = flaecheOeffnen(a, 'app:mcp__uebersicht', { sonstNeu: true });
    expect(link.voll).toBe(false);
    expect(link.ap.aktiv).toBe(2);
    expect(ids(link.ap, 2)).toEqual(['app:mcp__uebersicht']);
    expect(ids(link.ap, 1)).toHaveLength(8);
  });

  it('eine schon offene Fläche wird nicht doppelt geöffnet — es wird zu ihrem Bildschirm gewechselt', () => {
    let a = flaecheOeffnen(leer(), 'seite:finance').ap;
    a = neuerBildschirm(a, 'Zwei');
    a = flaecheOeffnen(a, 'seite:papra').ap;
    expect(a.aktiv).toBe(2);
    const r = flaecheOeffnen(a, 'seite:finance');
    expect(r.ap.aktiv).toBe(1);
    expect(ids(r.ap, 1)).toEqual(['seite:finance']);
    expect(wo(r.ap, 'seite:papra')).toBe(2);
  });

  it('wechselt nach links und rechts, begrenzt an den Enden', () => {
    let a = neuerBildschirm(neuerBildschirm(leer()));
    expect(a.aktiv).toBe(2);
    a = nachRechts(a);
    expect(a.aktiv).toBe(2);
    a = nachLinks(nachLinks(a));
    expect(a.aktiv).toBe(START);
    expect(nachLinks(a).aktiv).toBe(START);
    expect(wechseln(a, 99).aktiv).toBe(2);
  });

  it('verschiebt ein Fenster samt Größe auf einen anderen Bildschirm', () => {
    let a = flaecheOeffnen(leer(), 'seite:finance').ap;
    a = { ...a, bildschirme: a.bildschirme.map((b) => ({ ...b, fenster: b.fenster.map((w) => ({ ...w, spalten: 8, zeilen: 12 })) })) };
    a = neuerBildschirm(a, 'Zwei');
    a = verschiebenNach(a, 'seite:finance', 2);
    expect(ids(a, 1)).toEqual([]);
    expect(a.bildschirme[1]!.fenster[0]).toMatchObject({ id: 'seite:finance', spalten: 8, zeilen: 12 });
    expect(a.aktiv).toBe(2);
  });

  it('entfernt Bildschirme, der Start bleibt; höchstens BILDSCHIRME_MAX', () => {
    let a = leer();
    for (let i = 0; i < BILDSCHIRME_MAX + 2; i++) a = neuerBildschirm(a);
    expect(a.bildschirme).toHaveLength(BILDSCHIRME_MAX);
    a = entfernen(a, 3);
    expect(a.bildschirme).toHaveLength(BILDSCHIRME_MAX - 1);
    expect(entfernen(a, START)).toBe(a);
    expect(umbenennen(a, 1, '  Geld  ').bildschirme[0]!.name).toBe('Geld');
    expect(umbenennen(a, 1, '   ')).toBe(a);
  });

  it('speichert und lädt; Müll ergibt einen leeren Start; jede Fläche nur einmal über alle Bildschirme', () => {
    const a = flaecheOeffnen(leer(), 'seite:finance').ap;
    speichern(a);
    expect(laden().bildschirme[0]!.fenster.map((w) => w.id)).toEqual(['seite:finance']);
    localStorage.setItem('fyos:os:bildschirme:v1', '{kaputt');
    expect(laden()).toEqual(leer());
    const doppelt = pruefen({
      bildschirme: [{ name: 'A', fenster: [{ id: 'x' }] }, { name: 'B', fenster: [{ id: 'x' }, { id: 'y' }] }],
      aktiv: 7,
    });
    expect(doppelt.bildschirme.map((b) => b.fenster.map((w) => w.id))).toEqual([['x'], ['y']]);
    expect(doppelt.aktiv).toBe(2);
  });

  it('übernimmt die alte Anordnung (eine Liste) als „Bildschirm 1", gezeigt wird zuerst der Start', () => {
    const a = laden(() => [{ id: 'seite:finance', min: false }]);
    expect(a.aktiv).toBe(START);
    expect(a.bildschirme[0]).toMatchObject({ name: 'Bildschirm 1' });
    expect(ids(a, 1)).toEqual(['seite:finance']);
  });
});

describe('Namen nach dem Inhalt', () => {
  const titel = (id: string) => ({ itsm: 'Tickets', cluster: 'Steuerpult', haus: 'Haus', geld: 'Finanzen' })[id];

  it('ohne eigenen Namen heißt ein Bildschirm nach seinen Fenstern, sichtbare zuerst', () => {
    let a = neuerBildschirm(leer());
    const b = () => a.bildschirme[0]!;
    expect(anzeigeName(b(), 1, titel)).toBe('Bildschirm 2');
    a = flaecheOeffnen(a, 'itsm').ap;
    expect(anzeigeName(b(), 1, titel)).toBe('Tickets');
    a = flaecheOeffnen(a, 'cluster').ap;
    expect(anzeigeName(b(), 1, titel)).toBe('Tickets & Steuerpult');
    a = flaecheOeffnen(flaecheOeffnen(a, 'haus').ap, 'geld').ap;
    expect(anzeigeName(b(), 1, titel)).toBe('Tickets, Steuerpult +2');
    const mitMin = { ...b(), fenster: b().fenster.map((w) => (w.id === 'itsm' ? { ...w, min: true } : w)) };
    expect(anzeigeName(mitMin, 1, titel)).toBe('Steuerpult, Haus +2');
    // Unbekannte Flächen (entfernte App) zählen nicht
    expect(anzeigeName({ ...b(), fenster: [{ ...b().fenster[0]!, id: 'weg' }] }, 1, titel)).toBe('Bildschirm 2');
  });

  it('ein eigener Name gilt; leer umbenannt kehrt der Bildschirm zur Automatik zurück', () => {
    let a = flaecheOeffnen(leer(), 'itsm').ap;
    expect(automatischBenannt(a.bildschirme[0]!.name)).toBe(true);
    a = umbenennen(a, 1, 'Geld');
    expect(anzeigeName(a.bildschirme[0]!, 1, titel)).toBe('Geld');
    expect(automatischBenannt('Geld')).toBe(false);
    a = umbenennen(a, 1, '');
    expect(a.bildschirme[0]!.name).toBe('Bildschirm 1');
    expect(anzeigeName(a.bildschirme[0]!, 1, titel)).toBe('Tickets');
    // Alte Speicherstände mit „Bildschirm 3“ gelten ebenfalls als automatisch
    expect(automatischBenannt('Bildschirm 3')).toBe(true);
    expect(automatischBenannt('Bildschirm drei')).toBe(false);
  });
});

describe('Deeplink mit Eingabe', () => {
  const start = { werkzeug: 'haus__szenen', eingabe: { raum: 'Küche' } };
  const spaeter = { werkzeug: 'haus__szenen', eingabe: { raum: 'Bad' } };

  it('öffnet die Fläche mit ihrem Startzustand und speichert ihn mit', () => {
    const r = flaecheOeffnen(leer(), 'app:haus__favoriten', { start });
    expect(r.ap.bildschirme[0]!.fenster[0]).toEqual({ id: 'app:haus__favoriten', min: false, start });
    speichern(r.ap);
    expect(laden().bildschirme[0]!.fenster[0]!.start).toEqual(start);
  });

  it('ist die Fläche schon offen, holt der Link sie nach vorn, nimmt den neuen Start auf und löst die Minimierung', () => {
    let a = flaecheOeffnen(leer(), 'app:haus__favoriten', { start }).ap;
    a = flaecheOeffnen(a, 'seite:finance').ap;
    a = flaecheOeffnen(wechseln(a, START), 'app:haus__favoriten', { start: spaeter }).ap;
    expect(a.aktiv).toBe(1);
    expect(a.bildschirme[0]!.fenster.find((w) => w.id === 'app:haus__favoriten')).toMatchObject({ min: false, start: spaeter });
    // ohne neuen Start bleibt der alte
    const b = flaecheOeffnen(wechseln(a, START), 'app:haus__favoriten').ap;
    expect(b.bildschirme[0]!.fenster.find((w) => w.id === 'app:haus__favoriten')!.start).toEqual(spaeter);
  });

  it('ein Link auf ein Werkzeug einer App mit mehreren heißt danach wie die App (idsUmbenennen)', () => {
    let a = flaecheOeffnen(leer(), 'app:werkstatt__ausfuehren', { start: { werkzeug: 'werkstatt__ausfuehren', eingabe: { skript: 'x' } } }).ap;
    a = flaecheOeffnen(a, 'seite:finance').ap;
    const r = idsUmbenennen(a, (id) => (id === 'app:werkstatt__ausfuehren' ? 'app:werkstatt__suchen' : id));
    expect(ids(r, 1)).toEqual(['app:werkstatt__suchen', 'seite:finance']);
    // Start, Größe und Zustand wandern mit
    expect(r.bildschirme[0]!.fenster[0]).toMatchObject({ start: { werkzeug: 'werkstatt__ausfuehren', eingabe: { skript: 'x' } } });
  });

  it('idsUmbenennen ändert nichts, wenn nichts umzubenennen ist (derselbe Arbeitsplatz zurück)', () => {
    const a = flaecheOeffnen(leer(), 'seite:finance').ap;
    expect(idsUmbenennen(a, (id) => id)).toBe(a);
  });

  it('idsUmbenennen führt keine Fläche doppelt auf einem Bildschirm: das erste Fenster bleibt', () => {
    let a = flaecheOeffnen(leer(), 'app:werkstatt__suchen').ap;
    a = flaecheOeffnen(a, 'app:werkstatt__ausfuehren').ap;
    const r = idsUmbenennen(a, (id) => (id.startsWith('app:werkstatt__') ? 'app:werkstatt__suchen' : id));
    expect(ids(r, 1)).toEqual(['app:werkstatt__suchen']);
  });
});

describe('Zweiter Tab', () => {
  it('übernimmt die Anordnung, die ein anderer Tab gespeichert hat; fremde Schlüssel und Kaputtes zählen nicht', () => {
    const gesehen: number[] = [];
    const ab = fremdesSpeichern((ap) => gesehen.push(ap.bildschirme[0]?.fenster.length ?? -1));
    const a = flaecheOeffnen(leer(), 'seite:finance').ap;
    window.dispatchEvent(new StorageEvent('storage', { key: 'fyos:os:bildschirme:v1', newValue: JSON.stringify(a) }));
    window.dispatchEvent(new StorageEvent('storage', { key: 'anderes', newValue: '{}' }));
    window.dispatchEvent(new StorageEvent('storage', { key: 'fyos:os:bildschirme:v1', newValue: '{kaputt' }));
    ab();
    window.dispatchEvent(new StorageEvent('storage', { key: 'fyos:os:bildschirme:v1', newValue: JSON.stringify(a) }));
    expect(gesehen).toEqual([1]);
  });
});
