/**
 * Systemmitteilungen (lib/os/meldungen-system.ts): Brückenwahl (Hülle / Browser / keine), nur im Hintergrund und ab „normal“,
 * Erlaubnis nur auf Klick, Rückkehr binnen 10 s öffnet das Ziel. Dazu eine Quelltextprüfung: die Seite spricht nie
 * `__TAURI_INTERNALS__` und ruft nie window.confirm/alert/prompt (im System-WebView der Hülle gehen sie nicht).
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import type { Aufnahme, Meldung } from '~/lib/os/meldungen';
import { VORGABE, type MeldungenEinstellungen } from '~/lib/os/meldungen-einstellungen';
import { KLICK_FENSTER_MS, SystemMitteilungen, kannErlaubnisAnfragen, waehleBruecke, type HuelleBruecke, type Umgebung } from '~/lib/os/meldungen-system';

const meldung = (extra: Partial<Meldung> = {}): Meldung => ({
  id: 'm1', quelle: 'mail', schluessel: 's', stufe: 'normal', titel: 'Neue Mail von Alex', text: 'Rechnung', aktionen: [], zeit: 0, gelesen: false, anzahl: 1, stand: 0, ziel: { ziel: 'seite:mail-inbox' }, ...extra,
});
const aufnahme = (extra: Partial<Aufnahme> = {}, m: Partial<Meldung> = {}): Aufnahme => ({ meldung: meldung(m), toast: true, system: true, zusammengefasst: false, ...extra });

class FakeNotification {
  static permission = 'granted';
  static gesendet: Array<{ titel: string; o?: { body?: string; tag?: string; silent?: boolean } }> = [];
  static anfragen = vi.fn(async () => 'granted');
  static letzte: FakeNotification | undefined;
  onclick: ((e: unknown) => void) | null = null;
  constructor(titel: string, o?: { body?: string; tag?: string; silent?: boolean }) {
    FakeNotification.gesendet.push({ titel, ...(o ? { o } : {}) });
    FakeNotification.letzte = this;
  }
  close() {}
  static requestPermission() {
    return FakeNotification.anfragen();
  }
}

function aufbau(u: Umgebung, extra: { einst?: Partial<MeldungenEinstellungen>; hintergrund?: boolean } = {}) {
  let jetzt = 1_000_000;
  const einst = { ...structuredClone(VORGABE), ...extra.einst } as MeldungenEinstellungen;
  const oeffne = vi.fn();
  const gelesen = vi.fn();
  const s = new SystemMitteilungen({ einstellungen: () => einst, umgebung: () => u, hintergrund: () => extra.hintergrund ?? true, jetzt: () => jetzt, oeffne, gelesen });
  return { s, oeffne, gelesen, zeit: (ms: number) => (jetzt += ms) };
}
const huelle = (): HuelleBruecke & { benachrichtigen: ReturnType<typeof vi.fn> } => ({ profil: 'os', version: '0.0.4', benachrichtigen: vi.fn(async () => ({ gezeigt: true })) });

describe('Brückenwahl', () => {
  it('Hülle vor Browser; Browser nur mit erteilter Erlaubnis; sonst keine', () => {
    const h = huelle();
    FakeNotification.permission = 'granted';
    expect(waehleBruecke({ huelle: h, notification: FakeNotification as never })).toBe('huelle');
    expect(waehleBruecke({ notification: FakeNotification as never })).toBe('browser');
    FakeNotification.permission = 'default';
    expect(waehleBruecke({ notification: FakeNotification as never })).toBe('keine');
    FakeNotification.permission = 'denied';
    expect(waehleBruecke({ notification: FakeNotification as never })).toBe('keine');
    expect(waehleBruecke({})).toBe('keine');
  });

  it('die Erlaubnis kann nur im Browser und nur im Zustand „default“ erfragt werden', () => {
    FakeNotification.permission = 'default';
    expect(kannErlaubnisAnfragen({ notification: FakeNotification as never })).toBe(true);
    expect(kannErlaubnisAnfragen({ huelle: huelle(), notification: FakeNotification as never })).toBe(false);
    FakeNotification.permission = 'denied';
    expect(kannErlaubnisAnfragen({ notification: FakeNotification as never })).toBe(false);
  });
});

describe('Senden', () => {
  it('Hülle: Titel, Text; normal ist still, hoch mit Ton', async () => {
    const h = huelle();
    const { s } = aufbau({ huelle: h });
    expect(await s.beiNeu(aufnahme())).toBe('huelle');
    expect(h.benachrichtigen).toHaveBeenCalledWith('Neue Mail von Alex', 'Rechnung', { still: true });
    await s.beiNeu(aufnahme({}, { stufe: 'hoch' }));
    expect(h.benachrichtigen).toHaveBeenLastCalledWith('Neue Mail von Alex', 'Rechnung', { still: false });
  });

  it('nur im Hintergrund, nur wenn erlaubt (system), nur Aufnahmen mit system:true, nicht ohne Einstellung', async () => {
    const h = huelle();
    expect(await aufbau({ huelle: h }, { hintergrund: false }).s.beiNeu(aufnahme())).toBe('keine');
    expect(await aufbau({ huelle: h }).s.beiNeu(aufnahme({ system: false }))).toBe('keine');
    expect(await aufbau({ huelle: h }, { einst: { system: false } }).s.beiNeu(aufnahme())).toBe('keine');
    expect(h.benachrichtigen).not.toHaveBeenCalled();
  });

  it('Fehler der Hülle (zum Beispiel MITTEILUNGEN_NICHT_ERLAUBT) bleiben folgenlos: Toast und Verlauf genügen', async () => {
    const h = huelle();
    h.benachrichtigen.mockRejectedValue({ code: 'MITTEILUNGEN_NICHT_ERLAUBT' });
    const { s, oeffne } = aufbau({ huelle: h });
    expect(await s.beiNeu(aufnahme())).toBe('keine');
    expect(s.beiFokus()).toBe(false);
    expect(oeffne).not.toHaveBeenCalled();
  });

  it('Browser: Notification mit Tag, Klick öffnet das Ziel und liest', async () => {
    FakeNotification.permission = 'granted';
    FakeNotification.gesendet = [];
    const { s, oeffne, gelesen } = aufbau({ notification: FakeNotification as never });
    expect(await s.beiNeu(aufnahme())).toBe('browser');
    expect(FakeNotification.gesendet[0]).toMatchObject({ titel: 'Neue Mail von Alex', o: { body: 'Rechnung', tag: 'mail|s', silent: true } });
    FakeNotification.letzte!.onclick!({});
    expect(oeffne).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }));
    expect(gelesen).toHaveBeenCalledWith('m1');
    expect(s.beiFokus()).toBe(false);
  });

  it('keine Brücke: nichts wird gesendet, und die Erlaubnis wird nie von allein erfragt', async () => {
    FakeNotification.permission = 'default';
    FakeNotification.anfragen.mockClear();
    const { s } = aufbau({ notification: FakeNotification as never });
    expect(await s.beiNeu(aufnahme())).toBe('keine');
    expect(FakeNotification.anfragen).not.toHaveBeenCalled();
    expect(await s.erlaubnisAnfragen()).toBe('granted');
    expect(FakeNotification.anfragen).toHaveBeenCalledTimes(1);
  });
});

describe('Rückkehr in den Vordergrund', () => {
  it('binnen 10 s nach einer Systemmitteilung öffnet das Ziel, danach nicht mehr; nur einmal', async () => {
    const { s, oeffne, gelesen, zeit } = aufbau({ huelle: huelle() });
    await s.beiNeu(aufnahme());
    zeit(KLICK_FENSTER_MS - 1);
    expect(s.beiFokus()).toBe(true);
    expect(oeffne).toHaveBeenCalledTimes(1);
    expect(gelesen).toHaveBeenCalledWith('m1');
    expect(s.beiFokus()).toBe(false);

    await s.beiNeu(aufnahme());
    zeit(KLICK_FENSTER_MS + 1);
    expect(s.beiFokus()).toBe(false);
    expect(oeffne).toHaveBeenCalledTimes(1);
  });
});

// ── Quelltext-Wächter ───────────────────────────────────────────────────────────────────────────

function dateien(ordner: string, aus: string[] = []): string[] {
  for (const e of readdirSync(ordner, { withFileTypes: true })) {
    const p = join(ordner, e.name);
    if (e.isDirectory()) dateien(p, aus);
    else if (/\.(ts|tsx)$/.test(e.name)) aus.push(p);
  }
  return aus;
}

describe('Wächter', () => {
  const ROOT = join(__dirname, '..', '..', 'src');
  const alle = dateien(ROOT);

  it('keine Seite von fyos-web spricht __TAURI_INTERNALS__ oder __TAURI__ (nur die Brücke window.__FYOS_HUELLE__ der Hülle)', () => {
    const treffer = alle.filter((f) => /__TAURI(_INTERNALS)?__/.test(readFileSync(f, 'utf8')));
    expect(treffer).toEqual([]);
  });

  it('die Dateien des Meldungsdienstes rufen keine nativen Dialoge', () => {
    const eigene = alle.filter((f) => /(lib\/os\/meldungen[-.\w]*|components\/os\/Meldungen(Host|Glocke)|einstellungen\/MeldungenEinstellen)\.tsx?$/.test(f));
    expect(eigene.length).toBe(8);
    for (const f of eigene) {
      expect(readFileSync(f, 'utf8'), f).not.toMatch(/(^|[^\w.\x27\x22-])(confirm|alert|prompt)\(|window\.(confirm|alert|prompt)\(/m);
    }
  });
});
