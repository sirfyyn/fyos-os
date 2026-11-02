/**
 * Sichtbarkeit des Docks (lib/os/dock-sichtbar.ts, 28.10.2026): Zeiger am unteren Rand mit Verzögerung, Zeiger und Fokus
 * halten es offen, der Pfeil zeigt es 30 Sekunden (der Zähler steht still, solange jemand am Dock ist), ohne offene
 * Anwendungen nie. Alle Zeiten mit falschen Uhren.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DOCK_AUSBLENDEN_MS, DOCK_EINBLENDEN_MS, DOCK_PFEIL_MS, dockSichtbarkeit } from '~/lib/os/dock-sichtbar';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function neu() {
  const verlauf: boolean[] = [];
  const s = dockSichtbarkeit((v) => verlauf.push(v));
  return { s, verlauf };
}

describe('Dock-Sichtbarkeit: Zeiger am unteren Rand', () => {
  it('ist am Anfang unsichtbar', () => {
    const { s } = neu();
    expect(s.sichtbar()).toBe(false);
  });

  it('kommt erst nach der Verzögerung (Zufallsberührung zählt nicht)', () => {
    const { s } = neu();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS - 1);
    expect(s.sichtbar()).toBe(false);
    vi.advanceTimersByTime(1);
    expect(s.sichtbar()).toBe(true);
  });

  it('eine kurze Berührung (Zeiger geht vor Ablauf wieder) zeigt nichts', () => {
    const { s, verlauf } = neu();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS - 50);
    s.zone(false);
    vi.advanceTimersByTime(5000);
    expect(s.sichtbar()).toBe(false);
    expect(verlauf).toEqual([]);
  });

  it('verschwindet nach dem Weggehen mit kleiner Verzögerung', () => {
    const { s } = neu();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS);
    s.zone(false);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS - 1);
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(1);
    expect(s.sichtbar()).toBe(false);
  });

  it('der Zeiger auf dem Dock hält es offen; erst danach läuft das Ausblenden', () => {
    const { s } = neu();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS);
    s.dock(true); // vom Rand aufs Dock
    s.zone(false);
    vi.advanceTimersByTime(60_000);
    expect(s.sichtbar()).toBe(true);
    s.dock(false);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(s.sichtbar()).toBe(false);
  });

  it('Zeiger kehrt zurück, bevor es zugeht: es bleibt offen', () => {
    const { s } = neu();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS);
    s.zone(false);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS - 100);
    s.zone(true);
    vi.advanceTimersByTime(10_000);
    expect(s.sichtbar()).toBe(true);
  });
});

describe('Dock-Sichtbarkeit: Pfeil (30 Sekunden)', () => {
  it('zeigt das Dock sofort und blendet es nach 30 s wieder aus', () => {
    const { s } = neu();
    s.pfeil();
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(DOCK_PFEIL_MS - 1);
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(1);
    expect(s.sichtbar()).toBe(false);
  });

  it('der Zähler steht still, solange der Zeiger auf dem Dock ist, und beginnt danach von vorn', () => {
    const { s } = neu();
    s.pfeil();
    vi.advanceTimersByTime(20_000);
    s.dock(true);
    vi.advanceTimersByTime(120_000);
    expect(s.sichtbar()).toBe(true);
    expect(s.pfeilRest()).toBeNull(); // angehalten
    s.dock(false);
    vi.advanceTimersByTime(DOCK_PFEIL_MS - 1);
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(1);
    // der Pfeil ist um; Zeiger und Zone sind nicht mehr da
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(s.sichtbar()).toBe(false);
  });

  it('Fokus im Dock hält es ebenso offen und stoppt den Zähler', () => {
    const { s } = neu();
    s.pfeil();
    s.fokus(true);
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 3);
    expect(s.sichtbar()).toBe(true);
    s.fokus(false);
    vi.advanceTimersByTime(DOCK_PFEIL_MS);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(s.sichtbar()).toBe(false);
  });

  it('ein zweiter Druck setzt den Zähler zurück', () => {
    const { s } = neu();
    s.pfeil();
    vi.advanceTimersByTime(25_000);
    s.pfeil();
    vi.advanceTimersByTime(25_000);
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(5_000);
    expect(s.sichtbar()).toBe(false);
  });

  it('meldet die Restzeit', () => {
    const { s } = neu();
    expect(s.pfeilRest()).toBeNull();
    s.pfeil();
    vi.advanceTimersByTime(10_000);
    expect(s.pfeilRest()).toBe(DOCK_PFEIL_MS - 10_000);
  });
});

describe('Dock-Sichtbarkeit: Fokus, Esc, leer', () => {
  it('Tastaturfokus zeigt das Dock sofort und hält es', () => {
    const { s } = neu();
    s.fokus(true);
    expect(s.sichtbar()).toBe(true);
    vi.advanceTimersByTime(60_000);
    expect(s.sichtbar()).toBe(true);
    s.fokus(false);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS);
    expect(s.sichtbar()).toBe(false);
  });

  it('verbergen (Esc) schließt sofort, auch mitten im Pfeil', () => {
    const { s } = neu();
    s.pfeil();
    s.verbergen();
    expect(s.sichtbar()).toBe(false);
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 2);
    expect(s.sichtbar()).toBe(false);
  });

  it('ohne offene Anwendungen wird nie etwas gezeigt, und Wartendes verfällt', () => {
    const { s } = neu();
    s.pfeil();
    s.leer(true);
    expect(s.sichtbar()).toBe(false);
    s.pfeil();
    s.zone(true);
    vi.advanceTimersByTime(DOCK_EINBLENDEN_MS * 2);
    s.fokus(true);
    expect(s.sichtbar()).toBe(false);
    s.fokus(false);
    s.zone(false);
    s.leer(false);
    expect(s.sichtbar()).toBe(false);
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 2);
    expect(s.sichtbar()).toBe(false);
  });

  it('melden nur Änderungen, nicht jeden Anstoß', () => {
    const { s, verlauf } = neu();
    s.pfeil();
    s.pfeil();
    s.fokus(true);
    s.fokus(true);
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 2);
    s.fokus(false);
    vi.advanceTimersByTime(DOCK_AUSBLENDEN_MS + DOCK_PFEIL_MS);
    expect(verlauf).toEqual([true, false]);
  });

  it('aufraeumen stoppt alle Timer', () => {
    const { s, verlauf } = neu();
    s.pfeil();
    s.aufraeumen();
    vi.advanceTimersByTime(DOCK_PFEIL_MS * 2);
    expect(verlauf).toEqual([true]); // der Pfeil-Timer lief nicht mehr ab
  });
});
