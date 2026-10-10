/**
 * mitteilungen.ts — Daten, Stapel und Einstellung der Mitteilungen im OS.
 *
 * Eine Mitteilung sagt „schau dir diese Fläche an“ (z. B. das Ergebnis einer Hub-App, das der Agent
 * geholt hat). Das OS zeigt sie oben rechts (components/os/Mitteilungen.tsx); ein Klick öffnet die Fläche.
 *
 * Hier der reine Teil: die Nutzlast prüfen, den Stapel führen (höchstens 3, gleiche Fläche mit gleicher
 * Eingabe binnen 60 s ersetzt statt zu stapeln) und die Einstellung „stumm / aus“ lesen und schreiben.
 * Kein Solid, kein DOM — Speicher und Uhr kommen herein.
 */

export const SPEICHER_SCHLUESSEL = 'fyos:os:mitteilungen';
/** Fensterereignis, mit dem eine Quelle eine Mitteilung übergibt: `new CustomEvent(ZEIGT_EREIGNIS, { detail: { ziel, titel, … } })` */
export const ZEIGT_EREIGNIS = 'fyos:zeigt';
/** Höchstens so viele Mitteilungen stehen gleichzeitig da. */
export const MAX_STAPEL = 3;
/** Dieselbe Fläche mit derselben Eingabe zählt binnen dieser Zeit als dieselbe Mitteilung. */
export const GLEICH_MS = 60_000;
/** So lange bleibt eine Mitteilung stehen (pausiert beim Darüberfahren und im Hintergrund-Tab). */
export const ANZEIGE_MS = 10_000;

export interface ZeigtDaten {
  /** Fläche, z. B. `app:notizen__liste` */
  ziel: string;
  /** Name des Werkzeugs, z. B. `notizen__liste` */
  app: string | null;
  titel: string;
  untertitel: string | null;
  /** Ein, zwei Sätze zum Ergebnis */
  vorschau: string | null;
  /** Argumente, mit denen die Fläche geöffnet werden soll */
  eingabe: Record<string, unknown> | null;
  /** Deeplink zum Kopieren */
  link: string | null;
}

export interface Mitteilung {
  /** Schlüssel für „gleiche Mitteilung“: Ziel + Eingabe */
  key: string;
  /** Eindeutig je Erscheinen — ein ersetzter Eintrag bekommt eine neue ID */
  id: number;
  zeigt: ZeigtDaten;
  seit: number;
}

const text = (x: unknown, max: number): string | null => {
  if (typeof x !== 'string') return null;
  const t = x.replace(/\s+/g, ' ').trim();
  return t ? t.slice(0, max) : null;
};

/** Die Nutzlast prüfen und auf die Form bringen, die das OS zeigt. Ohne Ziel: null. */
export function zeigtPruefen(roh: unknown): ZeigtDaten | null {
  if (!roh || typeof roh !== 'object') return null;
  const r = roh as Record<string, unknown>;
  const ziel = text(r.ziel, 200);
  if (!ziel) return null;
  const app = text(r.app, 120);
  const eingabe = r.eingabe && typeof r.eingabe === 'object' && !Array.isArray(r.eingabe) ? (r.eingabe as Record<string, unknown>) : null;
  return {
    ziel,
    app,
    titel: text(r.titel, 80) ?? app ?? ziel,
    untertitel: text(r.untertitel, 80),
    vorschau: text(r.vorschau, 400),
    eingabe,
    link: text(r.link, 2000),
  };
}

/** Schlüsselsortiertes JSON: gleiche Eingabe, egal in welcher Reihenfolge die Felder kamen. */
export function stabilJson(x: unknown): string {
  if (Array.isArray(x)) return `[${x.map(stabilJson).join(',')}]`;
  if (x && typeof x === 'object') {
    const o = x as Record<string, unknown>;
    return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${stabilJson(o[k])}`).join(',')}}`;
  }
  return JSON.stringify(x) ?? 'null';
}

export const schluesselVon = (z: ZeigtDaten): string => `${z.ziel}|${z.eingabe ? stabilJson(z.eingabe) : ''}`;

let zaehler = 0;

/**
 * Neue Mitteilung oben einreihen. Dieselbe wie eine vorhandene (Ziel + Eingabe, jünger als 60 s)
 * ersetzt diese; sonst fliegt die älteste hinaus, wenn mehr als MAX_STAPEL da wären.
 */
export function hinzufuegen(liste: Mitteilung[], neu: ZeigtDaten, jetzt: number): Mitteilung[] {
  const key = schluesselVon(neu);
  const rest = liste.filter((m) => !(m.key === key && jetzt - m.seit < GLEICH_MS));
  const m: Mitteilung = { key, id: ++zaehler, zeigt: neu, seit: jetzt };
  return [m, ...rest].slice(0, MAX_STAPEL);
}

/** „jetzt“, „vor 2 min“, „vor 3 Std.“ */
export function zeitText(seit: number, jetzt: number): string {
  const s = Math.max(0, Math.round((jetzt - seit) / 1000));
  if (s < 45) return 'jetzt';
  const min = Math.round(s / 60);
  if (min < 60) return `vor ${Math.max(1, min)} min`;
  const h = Math.round(min / 60);
  return h < 24 ? `vor ${h} Std.` : 'gestern';
}

// ── Einstellung: stumm / aus ──────────────────────────────────────────────────────────────────

export interface ZeigtEinstellung {
  /** Keine Mitteilungen, bis sie wieder eingeschaltet werden */
  aus: boolean;
  /** Stumm bis zu diesem Zeitpunkt (ms seit 1970), 0 = nicht stumm */
  stumm_bis: number;
}

type LeseSpeicher = Pick<Storage, 'getItem'>;
type SchreibSpeicher = Pick<Storage, 'setItem'>;

const standardSpeicher = (): Storage | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null; // Zugriff gesperrt (privates Fenster, blockierte Website-Daten)
  }
};

export function einstellungLesen(speicher: LeseSpeicher | null = standardSpeicher()): ZeigtEinstellung {
  try {
    const roh = speicher?.getItem(SPEICHER_SCHLUESSEL);
    if (roh) {
      const j = JSON.parse(roh) as Partial<ZeigtEinstellung>;
      return { aus: j.aus === true, stumm_bis: typeof j.stumm_bis === 'number' && Number.isFinite(j.stumm_bis) ? j.stumm_bis : 0 };
    }
  } catch {
    /* kaputt oder gesperrt: wie nie gesetzt */
  }
  return { aus: false, stumm_bis: 0 };
}

export function einstellungSchreiben(e: ZeigtEinstellung, speicher: SchreibSpeicher | null = standardSpeicher()): void {
  try {
    speicher?.setItem(SPEICHER_SCHLUESSEL, JSON.stringify(e));
  } catch {
    /* gilt dann nur, bis die Seite neu lädt */
  }
}

export const istStumm = (e: ZeigtEinstellung, jetzt: number): boolean => e.aus || e.stumm_bis > jetzt;
