/**
 * Anordnung der Fenster eines Bildschirms (FYOS-Shell): welche Flächen offen sind, in welcher
 * Reihenfolge, wie groß, ob ein Fenster eine neue Zeile beginnt. Reine Funktionen auf einer
 * Liste — der Zustand wird nie verändert, sondern ersetzt. Die Bildschirme (mehrere solcher
 * Listen) verwaltet lib/os/bildschirme.ts.
 *
 * Raster: 12 Spalten, Zeilen zu je einer Rastereinheit. Ein Fenster ohne `spalten` gehört der
 * Automatik (füllt die Zeile gleichmäßig); sobald jemand eine Größe setzt, gilt diese.
 */
import { eingabeSauber } from './oeffnen';

export interface Fenster {
  id: string;
  min: boolean;
  /** Breite in Spalten des 12er-Rasters (SPALTEN_MIN–12). Fehlt sie, verteilt die Automatik. */
  spalten?: number;
  /** Höhe in Rasterzeilen (ZEILEN_MIN–ZEILEN_MAX). Fehlt sie, füllt die Automatik die Höhe. */
  zeilen?: number;
  /** Beginnt eine neue Zeile, auch wenn daneben noch Platz wäre. */
  neueZeile?: boolean;
  /**
   * Höhe festgehalten: Apps und native Flächen wachsen sonst mit ihrem Inhalt (eine Scrollebene); fest
   * bleibt das Fenster so hoch wie gewählt und der Inhalt scrollt in ihm. Setzt sich beim Ziehen der Höhe.
   */
  fest?: boolean;
  /** Alt: über die ganze Breite. Wird beim Laden zu `spalten: 12`. */
  breit?: boolean;
  /**
   * Startzustand einer App aus einem Deeplink (`?offen=app:…&eingabe=…`, Vertrag 2): mit welchem Werkzeug
   * und welchen Argumenten sie beim Öffnen läuft. Nur lesende Werkzeuge; gilt, solange das Fenster offen ist.
   */
  start?: StartZustand;
}

export interface StartZustand {
  /** `<plugin>__<werkzeug>` */
  werkzeug: string;
  eingabe: Record<string, unknown>;
}

export const MAX_OFFEN = 8;
export const SPALTEN = 12;
export const SPALTEN_MIN = 3;
export const ZEILEN_MIN = 4;
export const ZEILEN_MAX = 24;
/** Größe eines neuen Fensters, wenn der Bildschirm schon von Hand geordnet ist. */
export const NEU_SPALTEN = 6;
export const NEU_ZEILEN = 10;

const SCHLUESSEL = 'fyos:os:anordnung:v1';

const grenzen = (w: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, Math.round(w)));

/** Ist der Bildschirm von Hand geordnet (mindestens ein Fenster hat eine eigene Größe)? */
export const vonHand = (liste: Fenster[]): boolean => liste.some((w) => !w.min && w.spalten != null);

/**
 * Öffnet `id` (oder holt sie aus der Minimierung); `vor` setzt sie vor ein anderes Fenster. `start` ist der
 * Startzustand einer App aus einem Deeplink; ein offenes Fenster übernimmt einen neuen.
 */
export function oeffnen(liste: Fenster[], id: string, opt: { vor?: string | null; breit?: boolean; start?: StartZustand } = {}): Fenster[] {
  const da = liste.find((w) => w.id === id);
  if (da) return liste.map((w) => (w.id === id ? { ...w, min: false, ...(opt.start ? { start: opt.start } : {}) } : w));
  if (liste.filter((w) => !w.min).length >= MAX_OFFEN) {
    // Zu viele offene: es wird nichts geöffnet, der Aufrufer meldet es
    return liste;
  }
  const neu: Fenster = { id, min: false };
  if (opt.start) neu.start = opt.start;
  // Von Hand geordnet: das neue Fenster bekommt eine feste Größe, sonst bleibt alles Automatik.
  if (vonHand(liste) || opt.breit) {
    neu.spalten = opt.breit ? SPALTEN : NEU_SPALTEN;
    neu.zeilen = NEU_ZEILEN;
  }
  const i = opt.vor ? liste.findIndex((w) => w.id === opt.vor) : -1;
  return i >= 0 ? [...liste.slice(0, i), neu, ...liste.slice(i)] : [...liste, neu];
}

export const schliessen = (liste: Fenster[], id: string): Fenster[] => liste.filter((w) => w.id !== id);

export const minimieren = (liste: Fenster[], id: string): Fenster[] =>
  liste.map((w) => (w.id === id ? { ...w, min: true } : w));

/** „Alle einblenden“ (Bildschirm-Menü): holt minimierte Fenster zurück, bis MAX_OFFEN offen sind; `rest` = was im Dock bleibt. */
export function alleEinblenden(liste: Fenster[]): { liste: Fenster[]; rest: number } {
  let offen = liste.filter((w) => !w.min).length;
  let rest = 0;
  const neu = liste.map((w) => {
    if (!w.min) return w;
    if (offen >= MAX_OFFEN) {
      rest++;
      return w;
    }
    offen++;
    return { ...w, min: false };
  });
  return { liste: neu, rest };
}

/**
 * Größe setzen. Der erste Eingriff von Hand friert die Automatik ein: Alle anderen sichtbaren
 * Fenster bekommen die Größe, die sie gerade haben (`automatik`), damit nichts springt.
 */
export function groesseSetzen(
  liste: Fenster[],
  id: string,
  groesse: { spalten?: number; zeilen?: number; fest?: boolean },
  automatik?: Map<string, { spalten: number; zeilen: number }>,
): Fenster[] {
  const eingefroren = vonHand(liste)
    ? liste
    : liste.map((w) => {
        const a = automatik?.get(w.id);
        return a && !w.min ? { ...w, spalten: a.spalten, zeilen: a.zeilen } : w;
      });
  return eingefroren.map((w) => {
    if (w.id !== id) return w;
    const spalten = grenzen(groesse.spalten ?? w.spalten ?? NEU_SPALTEN, SPALTEN_MIN, SPALTEN);
    const zeilen = grenzen(groesse.zeilen ?? w.zeilen ?? NEU_ZEILEN, ZEILEN_MIN, ZEILEN_MAX);
    return festSetzen1({ ...w, spalten, zeilen }, groesse.fest ?? w.fest);
  });
}

const festSetzen1 = (w: Fenster, fest: boolean | undefined): Fenster => {
  const { fest: _f, ...rest } = w;
  return fest ? { ...rest, fest: true } : rest;
};

/** Höhe festhalten (der Inhalt scrollt im Fenster) oder wieder mit dem Inhalt wachsen lassen. */
export const festSetzen = (liste: Fenster[], id: string, fest: boolean): Fenster[] =>
  liste.map((w) => (w.id === id ? festSetzen1(w, fest) : w));

/** Alle Fenster zurück in die Automatik (gleichmäßig verteilt). */
export const automatisch = (liste: Fenster[]): Fenster[] =>
  liste.map(({ spalten: _s, zeilen: _z, neueZeile: _n, breit: _b, ...rest }) => rest);

export const neueZeileUmschalten = (liste: Fenster[], id: string): Fenster[] =>
  liste.map((w) => (w.id === id ? { ...w, neueZeile: !w.neueZeile } : w));

/** Vertauscht zwei Fenster; unbekannte oder gleiche IDs ändern nichts. */
export function tauschen(liste: Fenster[], a: string, b: string): Fenster[] {
  const i = liste.findIndex((w) => w.id === a);
  const j = liste.findIndex((w) => w.id === b);
  if (i < 0 || j < 0 || i === j) return liste;
  const kopie = [...liste];
  [kopie[i], kopie[j]] = [kopie[j]!, kopie[i]!];
  return kopie;
}

/** Setzt `id` vor `ziel` (Ziehen auf ein anderes Fenster). Ohne gültiges Ziel: ans Ende. */
export function davorSetzen(liste: Fenster[], id: string, ziel: string | null): Fenster[] {
  const w = liste.find((x) => x.id === id);
  if (!w || id === ziel) return liste;
  const ohne = liste.filter((x) => x.id !== id);
  const j = ziel ? ohne.findIndex((x) => x.id === ziel) : -1;
  return j >= 0 ? [...ohne.slice(0, j), w, ...ohne.slice(j)] : [...ohne, w];
}

/** Ein Platz nach links (-1) oder rechts (+1) — die Tastatur-Entsprechung zum Ziehen. */
export function verschieben(liste: Fenster[], id: string, richtung: -1 | 1): Fenster[] {
  const sichtbar = liste.filter((w) => !w.min).map((w) => w.id);
  const i = sichtbar.indexOf(id);
  const j = i + richtung;
  if (i < 0 || j < 0 || j >= sichtbar.length) return liste;
  return tauschen(liste, id, sichtbar[j]!);
}

/** Entfernt Fenster, deren Fläche es nicht mehr gibt (z. B. eine Hub-App, die abgebaut wurde). */
export const bereinigen = (liste: Fenster[], bekannt: (id: string) => boolean): Fenster[] =>
  liste.filter((w) => bekannt(w.id));

/** Startzustand aus Speicher oder Adresse: Werkzeugname und ein kleines JSON-Objekt, sonst nichts. */
export function startPruefen(s: unknown): StartZustand | undefined {
  if (!s || typeof s !== 'object') return undefined;
  const r = s as Record<string, unknown>;
  if (typeof r.werkzeug !== 'string' || !/^[A-Za-z0-9_]{1,60}__[A-Za-z0-9_]{1,60}$/.test(r.werkzeug)) return undefined;
  const eingabe = eingabeSauber(r.eingabe);
  return eingabe ? { werkzeug: r.werkzeug, eingabe } : undefined;
}

/** Ein Fenster aus Speicher oder Hub in die heutige Form bringen (Grenzen, alte Felder). */
export function fensterPruefen(w: unknown): Fenster | null {
  if (!w || typeof w !== 'object') return null;
  const r = w as Record<string, unknown>;
  if (typeof r.id !== 'string' || !r.id) return null;
  const f: Fenster = { id: r.id, min: !!r.min };
  const start = startPruefen(r.start);
  if (start) f.start = start;
  const spalten = typeof r.spalten === 'number' ? r.spalten : r.breit === true ? SPALTEN : undefined;
  if (spalten != null && Number.isFinite(spalten)) {
    f.spalten = grenzen(spalten, SPALTEN_MIN, SPALTEN);
    f.zeilen = grenzen(typeof r.zeilen === 'number' && Number.isFinite(r.zeilen) ? r.zeilen : NEU_ZEILEN, ZEILEN_MIN, ZEILEN_MAX);
  }
  if (r.neueZeile === true) f.neueZeile = true;
  if (r.fest === true) f.fest = true;
  return f;
}

/** Liste prüfen: gültige Fenster, keine Doppelten, höchstens 16. */
export function listePruefen(roh: unknown): Fenster[] {
  if (!Array.isArray(roh)) return [];
  const gesehen = new Set<string>();
  const out: Fenster[] = [];
  for (const w of roh) {
    const f = fensterPruefen(w);
    if (f && !gesehen.has(f.id)) {
      gesehen.add(f.id);
      out.push(f);
    }
  }
  return out.slice(0, 16);
}

/** Alte Anordnung (eine Liste, vor den Bildschirmen) — nur noch zum Übernehmen. */
export function laden(): Fenster[] {
  try {
    return listePruefen(JSON.parse(localStorage.getItem(SCHLUESSEL) ?? 'null'));
  } catch {
    return [];
  }
}

export function speichern(liste: Fenster[]): void {
  try {
    localStorage.setItem(SCHLUESSEL, JSON.stringify(liste));
  } catch {
    /* Speicher gesperrt — die Anordnung gilt dann nur für diese Sitzung */
  }
}

/**
 * Automatik: Spalten je Fenster, wenn nichts von Hand gesetzt ist. 1 Fenster füllt alles,
 * 2 nebeneinander, 3 in einer Zeile, 4 als 2×2, ab 5 drei je Zeile.
 */
export function autoSpalten(anzahl: number): number {
  if (anzahl <= 1) return SPALTEN;
  if (anzahl === 2 || anzahl === 4) return SPALTEN / 2;
  return SPALTEN / 3;
}

/** Wie viele Zeilen die Automatik bei `anzahl` Fenstern braucht. */
export const autoReihen = (anzahl: number): number => Math.max(1, Math.ceil(anzahl / (SPALTEN / autoSpalten(anzahl))));
