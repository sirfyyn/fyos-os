/**
 * status.ts — was der Kopf der Fläche über den Agenten sagt: bereit, arbeitet, wartet auf dich, pausiert; welches Modell;
 * und wann ein Zug so lange nichts mehr gemeldet hat, dass die Oberfläche nachfragen lässt.
 */
import type { Gespraech, GespraechsZustand } from './typen';

export type KopfStatus = 'pausiert' | 'wartet' | 'arbeitet' | 'bereit';

export const KOPF_TEXT: Record<KopfStatus, string> = {
  pausiert: 'Pausiert',
  wartet: 'Wartet auf dich',
  arbeitet: 'Arbeitet …',
  bereit: 'Bereit',
};

/** Der Ton des Punkts vor dem Zustand. */
export const KOPF_TON: Record<KopfStatus, 'ok' | 'warn' | 'aus' | 'fehler'> = {
  pausiert: 'aus',
  wartet: 'warn',
  arbeitet: 'ok',
  bereit: 'ok',
};

/**
 * Pausiert geht vor (Spielmodus: der Runner arbeitet nicht von selbst), dann was auf dich wartet, dann Arbeit.
 * `spielmodus` kommt aus `GET /api/health` (Name der Marke, oder leer).
 */
export function kopfStatus(p: { busy: boolean; offeneFreigaben: number; spielmodus: string | null }): KopfStatus {
  if (p.spielmodus) return 'pausiert';
  if (p.offeneFreigaben > 0) return 'wartet';
  if (p.busy) return 'arbeitet';
  return 'bereit';
}

/** „Pausiert (Spielmodus)“ für den Kopf: der Grund steht dabei. */
export function kopfText(status: KopfStatus, spielmodus: string | null): string {
  if (status === 'pausiert') return /spielmodus/i.test(spielmodus ?? '') ? 'Pausiert (Spielmodus)' : 'Pausiert';
  return KOPF_TEXT[status];
}

function modellVon(wert: unknown): string {
  if (!wert) return '';
  if (typeof wert === 'string') return wert;
  if (typeof wert === 'object') {
    const m = wert as { id?: unknown; name?: unknown; model?: unknown };
    for (const k of [m.id, m.name, m.model]) if (typeof k === 'string' && k) return k;
  }
  return '';
}

/** Kurzer Modellname: „anthropic/claude-sonnet-4“ wird „claude-sonnet-4“. Leer, wenn der Runner keinen nennt. */
export function modellName(z: Pick<GespraechsZustand, 'agent' | 'meta'>, g?: Pick<Gespraech, 'modell'> | null): string {
  const agent = z.agent as { model?: unknown } | null | undefined;
  const roh = modellVon(agent?.model) || modellVon(z.meta?.modell) || modellVon(z.meta?.model) || modellVon(g?.modell);
  const teile = roh.split('/');
  return teile[teile.length - 1] ?? '';
}

/** So lange darf ein Zug nichts melden, bevor die Oberfläche es sagt. */
export const FLAUTE_MS = 15 * 60_000;

/** Läuft ein Zug, der seit `FLAUTE_MS` nichts mehr gemeldet hat? */
export function zugFlaute(p: { busy: boolean; letzteRegung: number; jetzt?: number }): boolean {
  if (!p.busy || !p.letzteRegung) return false;
  return (p.jetzt ?? Date.now()) - p.letzteRegung >= FLAUTE_MS;
}

/** „Keine fertige Antwort nach 15 min.“ */
export function flauteText(p: { letzteRegung: number; jetzt?: number }): string {
  const min = Math.max(1, Math.floor(((p.jetzt ?? Date.now()) - p.letzteRegung) / 60_000));
  return `Keine fertige Antwort nach ${min} min.`;
}

/** Was „Nachfassen“ an den laufenden Zug schickt. */
export const NACHFASS_TEXT = 'Kurze Rückfrage: Wie ist der Stand? Bitte melde dich mit dem, was du bisher hast, und sag, was noch fehlt.';
