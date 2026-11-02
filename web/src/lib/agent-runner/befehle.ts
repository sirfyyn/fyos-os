/**
 * befehle.ts — Schnellbefehle der Eingabe. Ein Befehl beginnt mit „/“ und ist ein Wunsch an die Fläche, nicht Text
 * an den Agenten. Unbekanntes mit „/“ geht als normaler Text durch (Pfade, Brüche).
 *
 * /live [an|aus]  blendet Ginnys eigenständige Arbeit ein oder aus (der Agent merkt nichts)
 * /ruhe           wie „/live aus“
 * /neu            neues Gespräch
 * /stopp          hält den laufenden Zug an (auch /pause: der Runner kennt kein Anhalten, nur Abbrechen)
 */

export type BefehlName = 'live' | 'ruhe' | 'neu' | 'stopp';

export interface BefehlInfo {
  name: BefehlName;
  /** So steht er in der Eingabe. */
  zeichen: string;
  hilfe: string;
  /** Weitere Schreibweisen. */
  aliase: string[];
}

export const BEFEHLE: readonly BefehlInfo[] = [
  { name: 'live', zeichen: '/live', hilfe: 'Ginnys eigenständige Arbeit ein- oder ausblenden', aliase: [] },
  { name: 'ruhe', zeichen: '/ruhe', hilfe: 'Ruhe: eigenständige Arbeit ausblenden', aliase: [] },
  { name: 'neu', zeichen: '/neu', hilfe: 'Neues Gespräch beginnen', aliase: [] },
  { name: 'stopp', zeichen: '/stopp', hilfe: 'Laufenden Zug anhalten', aliase: ['/pause'] },
];

export interface GelesenerBefehl {
  name: BefehlName;
  /** Was nach dem Befehl steht („aus“ bei „/live aus“). */
  rest: string;
}

/** Liest einen Befehl aus dem ganzen Eingabetext; `null`, wenn es keiner ist. */
export function liesBefehl(text: string): GelesenerBefehl | null {
  const t = String(text ?? '').trim();
  if (!t.startsWith('/')) return null;
  const [kopf = '', ...rest] = t.split(/\s+/);
  const k = kopf.toLowerCase();
  const b = BEFEHLE.find((x) => x.zeichen === k || x.aliase.includes(k));
  return b ? { name: b.name, rest: rest.join(' ').trim() } : null;
}

/**
 * Befehle, die zur Eingabe passen, solange sie noch ein Wort mit „/“ ist: „/l“ → /live. Leer, sobald ein Leerzeichen
 * oder Zeilenumbruch folgt oder die Eingabe nicht mit „/“ beginnt.
 */
export function passendeBefehle(eingabe: string): BefehlInfo[] {
  if (!/^\/\S*$/.test(eingabe)) return [];
  const e = eingabe.toLowerCase();
  return BEFEHLE.filter((b) => b.zeichen.startsWith(e) || b.aliase.some((a) => a.startsWith(e)));
}
