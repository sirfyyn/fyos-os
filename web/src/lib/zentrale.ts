/**
 * zentrale.ts — Vertrag des gebündelten Stands (`zentrale.zustand`), den der App-Drawer (lib/os/drawer.ts) für die
 * Stand-Zeile je App liest. In der öffentlichen Fassung nur der Vertrag: liefert der Hub das Werkzeug nicht, zeigen die
 * Apps ihren Untertitel statt eines Stands. Frei von Solid und DOM.
 */

export const ZUSTAND_WERKZEUG = 'zentrale.zustand';
/** Die Oberfläche braucht alle Daten; ohne `form` liefert der Hub nur die Kurzform. */
export const ZUSTAND_ARGUMENTE = { form: 'voll' } as const;

export type Ampel = 'gruen' | 'blau' | 'dev' | 'debug' | 'gelb' | 'rot';

export interface Aktion {
  label: string;
  art: 'link' | 'werkzeug';
  ziel?: string;
  werkzeug?: string;
  argumente?: Record<string, unknown>;
  schreibt?: boolean;
}

/** Ein Befund, der Dringlichkeit oder Lage-Satz treibt; quittierbar als „bekannt". */
export interface Befund {
  schluessel: string;
  text: string;
  quittiert: boolean;
  bis?: string | null;
}

export interface Kachel<D = unknown> {
  id: string;
  titel: string;
  dringlichkeit: number;
  /** Nur bei einem Problem zeigen: bei Dringlichkeit < 30 gar nicht */
  nur_bei_problem?: boolean;
  grund: string;
  befunde?: Befund[];
  kurz: string;
  daten: D | null;
  fehler: string | null;
  /** Nach Zeitüberschreitung der Quelle: letzter guter Stand, sonst fehlt das Feld. */
  stand_von?: string | null;
  veraltet_s?: number | null;
  aktionen: Aktion[];
}

export interface ZentraleZustand {
  ts: string;
  lage_satz: string;
  ampel: Ampel | string;
  kacheln: Kachel[];
  quellen?: Record<string, { ok: boolean; fehler: string | null; ms?: number }>;
}

/** Ton einer Zeile oder Kachel (Farbe des Stands). */
export type Ton = 'error' | 'warn' | 'ok' | 'leise';
