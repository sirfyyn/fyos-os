/**
 * entwurf.ts — der angefangene Text im Eingabefeld bleibt erhalten: je Gespräch ein Entwurf im lokalen Speicher.
 * Wer das Fenster schließt, neu lädt oder das Gespräch wechselt, findet seinen Satz wieder.
 */
type Speicher = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export const ENTWURF_PREFIX = 'fyos:agent:entwurf:';

const standard = (): Speicher | null => {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
};

export function liesEntwurf(id: number | null, speicher: Speicher | null = standard()): string {
  if (id === null) return '';
  try {
    return speicher?.getItem(`${ENTWURF_PREFIX}${id}`) ?? '';
  } catch {
    return '';
  }
}

/** Leerer Text löscht den Entwurf. */
export function schreibeEntwurf(id: number | null, text: string, speicher: Speicher | null = standard()): void {
  if (id === null) return;
  try {
    if (text.trim()) speicher?.setItem(`${ENTWURF_PREFIX}${id}`, text);
    else speicher?.removeItem(`${ENTWURF_PREFIX}${id}`);
  } catch {
    /* ohne Speicher gilt der Entwurf nur, solange das Fenster offen ist */
  }
}
