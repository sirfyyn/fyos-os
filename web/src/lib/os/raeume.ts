/**
 * Räume des OS.
 *
 * Ein Raum ist ein Vollbild-Bildschirm der Shell, keine zweite Website: Räume-Leiste links allein, Mitte, Leiste des
 * Raums rechts. Die Zentrale steht fest oben und ist die Heimat (der Start mit seinen Arbeitsbildschirmen,
 * lib/os/bildschirme.ts), die Einstellungen fest unten. Die Räume dazwischen lassen sich ordnen.
 * In der Leiste stehen nur gebaute Räume; die übrigen kommen mit ihrem Bau dazu.
 *
 * Die Räume sind leere Hüllen: sie zeigen nur, was eingerichtete Plugins über den Hub liefern (components/os/Raum.tsx),
 * sonst steht dort „Noch nicht eingerichtet.“.
 *
 * Reine Funktionen plus ein kleiner Speicher (Signal) für Shell und Einstellungen; gespeichert im Browser.
 * Die Räume sind an, solange niemand sie ausschaltet (Einstellungen oder `?raeume=0`; `?raeume=1` schaltet ein).
 */
import { createSignal } from 'solid-js';

export type RaumId = 'zentrale' | 'gespraech' | 'sammlung' | 'atelier' | 'vorhaben' | 'buero' | 'zuhause' | 'betrieb' | 'einstellungen';

export interface RaumEintrag {
  id: RaumId;
  name: string;
  /** Wofür der Raum da ist (Tooltip, Einstellungen) */
  zweck: string;
  /** SVG-Pfad auf 24×24, Strich wie Lucide */
  d: string;
  /** In der Leiste nur, wenn gebaut */
  gebaut: boolean;
  /** Fester Platz: oben (Zentrale) oder unten (Einstellungen) */
  fest?: 'oben' | 'unten';
}

export const RAEUME: readonly RaumEintrag[] = [
  { id: 'zentrale', name: 'Zentrale', zweck: 'Heimat: Start, Apps und Arbeitsbildschirme', d: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z', gebaut: true, fest: 'oben' },
  { id: 'gespraech', name: 'Gespräch', zweck: 'Ein Chat für den Agenten, Vorgänge und Kanäle', d: 'M4 5h16v11H9l-5 4z', gebaut: true },
  { id: 'sammlung', name: 'Sammlung', zweck: 'Alles, was entsteht: Ansichten, Berichte, Bilder, Dokumente', d: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5', gebaut: true },
  { id: 'atelier', name: 'Atelier', zweck: 'Bilder, Bearbeiten, Dokumente, Schreiben', d: 'M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6', gebaut: true },
  { id: 'vorhaben', name: 'Vorhaben', zweck: 'Geplante Anpassungen als Brett, „live gesehen“ nur mit Beleg', d: 'M4 4h4v16H4zM10 4h4v10h-4zM16 4h4v6h-4z', gebaut: true },
  { id: 'buero', name: 'Büro', zweck: 'Mail, Kalender, Finanzen, Post, Bestellungen', d: 'M3 6h18v12H3zM3 6l9 7 9-7', gebaut: true },
  { id: 'zuhause', name: 'Zuhause', zweck: 'Das Zuhause: Geräte und Schalter', d: 'M3 11l9-7 9 7v9H3zM10 20v-6h4v6', gebaut: true },
  { id: 'betrieb', name: 'Betrieb', zweck: 'Lage, Cluster, Repos, Agenten, Modelle, Werkstatt', d: 'M3 12h4l3-7 4 14 3-7h4', gebaut: true },
  {
    id: 'einstellungen',
    name: 'Einstellungen',
    zweck: 'Aussehen, Räume, Konten, Plugins, Modelle, Gedächtnis',
    d: 'M12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1',
    gebaut: true,
    fest: 'unten',
  },
];

export const ZENTRALE: RaumId = 'zentrale';
// v2: Räume sind an, wenn niemand sie ausgeschaltet hat. Aus v1 kommt nur die eigene Ordnung mit,
// denn „aus“ war dort die alte Vorgabe und keine Wahl.
const SCHLUESSEL = 'fyos:os:raeume:v2';
const SCHLUESSEL_V1 = 'fyos:os:raeume:v1';
/** Die ordenbaren Räume zwischen Zentrale und Einstellungen, in der Grundordnung */
const MITTE: readonly RaumId[] = RAEUME.filter((r) => !r.fest).map((r) => r.id);

export interface RaeumeZustand {
  /** Räume eingeschaltet (Leiste sichtbar) */
  an: boolean;
  /** Der Raum vorn; `zentrale` = die Shell wie bisher (Start und Arbeitsbildschirme) */
  aktiv: RaumId;
  /** Reihenfolge der ordenbaren Räume (alle, auch noch nicht gebaute) */
  reihenfolge: RaumId[];
}

export const raumZu = (id: string): RaumEintrag | undefined => RAEUME.find((r) => r.id === id);
const gebaut = (id: string): boolean => !!raumZu(id)?.gebaut;

export const standard = (): RaeumeZustand => ({ an: true, aktiv: ZENTRALE, reihenfolge: [...MITTE] });

/** Aus Speicher: gültige Werte, fehlende Räume hinten angehängt, Unbekanntes verworfen. */
export function pruefen(roh: unknown): RaeumeZustand {
  const r = (roh && typeof roh === 'object' ? roh : {}) as Partial<RaeumeZustand>;
  const reihenfolge: RaumId[] = [];
  for (const id of Array.isArray(r.reihenfolge) ? r.reihenfolge : []) {
    if (typeof id === 'string' && (MITTE as readonly string[]).includes(id) && !reihenfolge.includes(id as RaumId)) reihenfolge.push(id as RaumId);
  }
  for (const id of MITTE) if (!reihenfolge.includes(id)) reihenfolge.push(id);
  const an = r.an !== false;
  const aktiv = an && typeof r.aktiv === 'string' && gebaut(r.aktiv) ? (r.aktiv as RaumId) : ZENTRALE;
  return { an, aktiv, reihenfolge };
}

/** Was die Leiste zeigt, von oben nach unten: Zentrale, die gebauten Räume in eigener Ordnung, Einstellungen. */
export function leiste(z: RaeumeZustand): RaumEintrag[] {
  const oben = RAEUME.filter((r) => r.fest === 'oben');
  const unten = RAEUME.filter((r) => r.fest === 'unten');
  const mitte = z.reihenfolge.map(raumZu).filter((r): r is RaumEintrag => !!r && r.gebaut);
  return [...oben, ...mitte, ...unten];
}

/** Zu Raum `id` wechseln; nicht gebaute oder unbekannte Räume ändern nichts. */
export function wechseln(z: RaeumeZustand, id: string): RaeumeZustand {
  if (!gebaut(id) || id === z.aktiv) return z;
  return { ...z, aktiv: id as RaumId };
}

/** Einen Raum weiter (+1) oder zurück (−1) in der Leiste, im Kreis (⌥⌘→ / ⌥⌘← im Raum, Wischen). */
export function schritt(z: RaeumeZustand, richtung: 1 | -1): RaeumeZustand {
  const l = leiste(z);
  const i = Math.max(0, l.findIndex((r) => r.id === z.aktiv));
  const ziel = l[(i + richtung + l.length) % l.length]!;
  return wechseln(z, ziel.id);
}

/** Raum in der eigenen Ordnung verschieben: tauscht mit dem nächsten gebauten Nachbarn (die Leiste zeigt nur diese). */
export function verschieben(z: RaeumeZustand, id: RaumId, richtung: 1 | -1): RaeumeZustand {
  const i = z.reihenfolge.indexOf(id);
  if (i < 0) return z;
  let j = i + richtung;
  while (j >= 0 && j < z.reihenfolge.length && !gebaut(z.reihenfolge[j]!)) j += richtung;
  if (j < 0 || j >= z.reihenfolge.length) return z;
  const reihenfolge = [...z.reihenfolge];
  [reihenfolge[i], reihenfolge[j]] = [reihenfolge[j]!, reihenfolge[i]!];
  return { ...z, reihenfolge };
}

/** Räume ein- oder ausschalten; aus heißt zurück in die Zentrale. */
export const einschalten = (z: RaeumeZustand, an: boolean): RaeumeZustand =>
  an === z.an ? z : { ...z, an, aktiv: an ? z.aktiv : ZENTRALE };

/** Grundordnung wiederherstellen (behält an/aus und den Raum vorn). */
export const ordnungZuruecksetzen = (z: RaeumeZustand): RaeumeZustand => ({ ...z, reihenfolge: [...MITTE] });

export function laden(): RaeumeZustand {
  let z = standard();
  try {
    const roh = localStorage.getItem(SCHLUESSEL);
    if (roh) z = pruefen(JSON.parse(roh));
    else {
      const alt = localStorage.getItem(SCHLUESSEL_V1);
      if (alt) z = { ...standard(), reihenfolge: pruefen(JSON.parse(alt)).reihenfolge };
    }
  } catch {
    /* kaputt oder gesperrt: wie neu */
  }
  try {
    const p = new URLSearchParams(location.search).get('raeume');
    if (p === '1') z = einschalten(z, true);
    else if (p === '0') z = einschalten(z, false);
  } catch {
    /* ohne location (Tests): nichts */
  }
  return z;
}

export function speichern(z: RaeumeZustand): void {
  try {
    localStorage.setItem(SCHLUESSEL, JSON.stringify(z));
  } catch {
    /* Speicher gesperrt: gilt nur für diese Sitzung */
  }
}

// ── Speicher für Shell und Einstellungen (ein Zustand, beide lesen ihn) ───────────────────────
const [zustand, setZustand] = createSignal<RaeumeZustand>(standard());
let geladen = false;

/** Der aktuelle Zustand; lädt beim ersten Lesen aus dem Browser. */
export function raeume(): RaeumeZustand {
  if (!geladen) {
    geladen = true;
    setZustand(laden());
  }
  return zustand();
}

export function raeumeSetzen(neu: RaeumeZustand): void {
  geladen = true;
  if (neu === zustand()) return;
  setZustand(neu);
  speichern(neu);
}

/** Nur für Tests: Speicher auf Anfang. */
export function raeumeZuruecksetzen(): void {
  geladen = false;
  setZustand(standard());
}
