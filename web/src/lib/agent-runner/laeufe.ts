/**
 * laeufe.ts — Läufe lesen und ordnen. Ein Lauf ist langes Arbeiten mit Phasen (start → arbeiten → freigabe? → abschluss),
 * hat ein eigenes Kindgespräch und überlebt Abstürze.
 */
import type { Lauf } from './typen';
import { tr } from '~/lib/i18n';

export type LaufTon = 'laeuft' | 'fertig' | 'fehler' | 'offen';

export const laeuft = (l: Lauf): boolean => l.status === 'laeuft';

export function laufTon(l: Lauf): LaufTon {
  if (laeuft(l)) return 'laeuft';
  if (l.status === 'abgeschlossen') return 'fertig';
  if (l.status === 'fehler' || l.status === 'abgebrochen' || l.status === 'abgelehnt') return 'fehler';
  return 'offen';
}

export const STATUS_TEXT: Record<string, string> = {
  laeuft: 'läuft',
  abgeschlossen: 'abgeschlossen',
  fehler: 'Fehler',
  abgelehnt: 'abgelehnt',
  abgebrochen: 'abgebrochen',
};

export const statusText = (l: Lauf): string => (STATUS_TEXT[l.status] ? tr(STATUS_TEXT[l.status]!) : l.status);

/** Laufende zuerst, danach nach Alter (neueste zuerst). */
export function ordneLaeufe(liste: Lauf[]): Lauf[] {
  return liste.slice().sort((a, b) => {
    const ao = laeuft(a) ? 0 : 1;
    const bo = laeuft(b) ? 0 : 1;
    if (ao !== bo) return ao - bo;
    return (b.erstellt ?? 0) - (a.erstellt ?? 0);
  });
}

export const laufendeZahl = (liste: Lauf[]): number => liste.filter(laeuft).length;
