/**
 * freigaben.ts — Freigaben lesen und ordnen. Nur Destruktives geht durch eine Freigabe, und sie liegt
 * im Runner, nicht im ITSM. Die Karte zeigt Aktion, Risiko, Kontext und Befehl; Erteilen und Ablehnen sind zwei Knöpfe.
 */
import type { Freigabe } from './typen';
import { tr } from '~/lib/i18n';

export const istOffen = (f: Freigabe): boolean => f.status === 'offen';

/** Offene zuerst (hohes Risiko vor niedrigem, dann neueste zuerst), danach die entschiedenen (neueste zuerst). */
export function ordneFreigaben(liste: Freigabe[]): Freigabe[] {
  const rang = (r: string | undefined): number => (r === 'high' ? 0 : r === 'medium' ? 1 : r === 'low' ? 2 : 1);
  return liste.slice().sort((a, b) => {
    const ao = istOffen(a) ? 0 : 1;
    const bo = istOffen(b) ? 0 : 1;
    if (ao !== bo) return ao - bo;
    if (ao === 0 && rang(a.risiko) !== rang(b.risiko)) return rang(a.risiko) - rang(b.risiko);
    return (b.erstellt ?? 0) - (a.erstellt ?? 0);
  });
}

/** Die Zahl, die im Fenster und im Start steht. */
export const offeneZahl = (liste: Freigabe[]): number => liste.filter(istOffen).length;

export const RISIKO_TEXT: Record<string, string> = { low: 'niedrig', medium: 'mittel', high: 'hoch' };

export function risikoText(r: string | undefined): string {
  return tr(RISIKO_TEXT[r ?? ''] ?? (r || 'mittel'));
}

export type Entscheidung = 'erteilt' | 'abgelehnt';

/** Der Befehl, der ausgeführt würde, wenn man erteilt (für die Karte); leer, wenn keiner genannt ist. */
export function befehlsZeile(f: Freigabe): string {
  const w = f.werkzeug ? `${f.werkzeug}: ` : '';
  return f.befehl ? `${w}${f.befehl}` : '';
}
