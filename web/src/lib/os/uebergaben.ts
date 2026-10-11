/**
 * uebergaben.ts — aus einem gezogenen Ding und einer Übergabe die Argumente des Zielwerkzeugs machen.
 *
 * Der Hub sagt je Paar „Ding-Typ → App“ (`registriere_uebergabe`, docs/ERWEITERN.md): welches Werkzeug der Ziel-App läuft und
 * wie die Felder des Dings seine Argumente füllen (`abbildung`, Texte mit `{id}`, `{label}`, `{feld}`). Hier wird das
 * ausgeführt: nötigenfalls das Ding über sein lesendes Werkzeug laden, die Platzhalter einsetzen, prüfen, was herauskommt.
 * Nichts davon ändert etwas: das Ergebnis geht an die Ziel-App, die den Plan zeigt und fragt (`App.beantragen`).
 *
 * Eingesetzt wird genau einmal und nur als Text: ein Feld, das selbst „{id}“ enthält, wird nicht noch einmal ersetzt.
 */
import type { DingArt, Uebergabe } from './register';

/** Felder, die jedes gezogene Ding hat. */
const GRUNDFELDER = ['id', 'label'];
/** Ein Platzhalter in einem Text der Abbildung. */
const PLATZHALTER = /\{([a-z][a-z0-9_]*)\}/g;
/** Größte Länge eines eingesetzten Textes und der Argumente insgesamt (JSON-Zeichen): eine Übergabe ist für Notizen und Verweise, nicht für Dateien. */
export const TEXT_MAX = 100_000;
export const ARGUMENTE_MAX = 200_000;

/** Wie das lesende Werkzeug des Typs gerufen wird: Name (`<plugin>__<name>`) und Argumente → die Daten des Dings. */
export type DingLesen = (werkzeug: string, argumente: Record<string, unknown>) => Promise<Record<string, unknown>>;

export interface GezogenesDing {
  typ: string;
  id: string;
  label?: string;
}

/** Was die Ziel-App bekommt (`fyos/uebergabe`). */
export interface Vorbereitet {
  typ: string;
  id: string;
  label: string;
  /** Werkzeug der Ziel-App (`<plugin>__<name>`) */
  werkzeug: string;
  argumente: Record<string, string | number | boolean>;
  /** Satz zum Anzeigen: was geschieht */
  wirkung: string;
}

/** Alle Namen in `{…}` aus den Textwerten einer Abbildung. */
export function platzhalterIn(abbildung: Uebergabe['abbildung']): Set<string> {
  const namen = new Set<string>();
  for (const w of Object.values(abbildung)) {
    if (typeof w === 'string') for (const m of w.matchAll(PLATZHALTER)) namen.add(m[1]!);
  }
  return namen;
}

/** Muss das Ding erst gelesen werden (die Abbildung nennt mehr als Kennung und Namen)? */
export const brauchtLesen = (u: Uebergabe): boolean => [...platzhalterIn(u.abbildung)].some((n) => !GRUNDFELDER.includes(n));

/** Setzt die Werte in die Abbildung ein; ein Platzhalter ohne Wert wirft (lieber keine Übergabe als eine mit Loch). */
export function ausfuellen(abbildung: Uebergabe['abbildung'], werte: Record<string, string>): Vorbereitet['argumente'] {
  const aus: Vorbereitet['argumente'] = {};
  let summe = 0;
  for (const [arg, wert] of Object.entries(abbildung)) {
    if (typeof wert !== 'string') {
      aus[arg] = wert;
      continue;
    }
    const text = wert.replace(PLATZHALTER, (_m, name: string) => {
      const v = werte[name];
      if (v === undefined) throw new Error(`Das Feld „${name}“ fehlt.`);
      return v;
    });
    if (text.length > TEXT_MAX) throw new Error('Das ist für eine Übergabe zu groß.');
    summe += text.length;
    aus[arg] = text;
  }
  if (summe > ARGUMENTE_MAX) throw new Error('Das ist für eine Übergabe zu groß.');
  return aus;
}

/** Einzelwert aus dem Ergebnis des Lesewerkzeugs als Text (nur Zahlen, Texte, Wahrheitswerte). */
const alsText = (v: unknown): string | undefined => (typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : undefined);

/**
 * Bereitet eine Übergabe vor: liest das Ding, wenn die Abbildung Felder braucht, und setzt alles ein.
 * Wirft mit einem Satz für Menschen, wenn das Ding nicht zu lesen ist oder ein Feld fehlt.
 */
export async function uebergabeVorbereiten(u: Uebergabe, ding: DingArt | undefined, gezogen: GezogenesDing, lesen: DingLesen): Promise<Vorbereitet> {
  const label = gezogen.label || gezogen.id;
  const werte: Record<string, string> = { id: gezogen.id, label };
  if (brauchtLesen(u)) {
    if (!ding?.lesen) throw new Error(`${ding?.name ?? 'Das Ding'} lässt sich nicht lesen.`);
    let daten: Record<string, unknown>;
    try {
      daten = await lesen(ding.lesen, { [ding.idArgument ?? 'id']: gezogen.id });
    } catch (e) {
      throw new Error(`${ding.name} „${label}“ lässt sich nicht lesen: ${(e as Error).message || e}`);
    }
    for (const f of ding.felder ?? []) {
      const t = alsText(daten[f]);
      if (t !== undefined) werte[f] = t;
    }
  }
  let argumente: Vorbereitet['argumente'];
  try {
    argumente = ausfuellen(u.abbildung, werte);
  } catch (e) {
    throw new Error(`${ding?.name ?? 'Das Ding'} „${label}“ lässt sich hier nicht ablegen: ${(e as Error).message}`);
  }
  return { typ: gezogen.typ, id: gezogen.id, label, werkzeug: u.werkzeug, argumente, wirkung: u.wirkung };
}
