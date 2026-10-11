/**
 * menue.ts — ein Menümodell für das ganze OS.
 *
 * Rechtsklick, Langdruck auf dem
 * Handy, die Menüleiste oben und der ⋯-Knopf im Fensterkopf zeigen alle dasselbe Menü
 * (components/os/Menue.tsx). Wer ein Menü will, baut eine Liste aus `MenuePunkt` und ruft
 * `menueOeffnen` — es gibt immer nur eines.
 */
import { createSignal } from 'solid-js';

export type MenuePunkt =
  | {
      art?: 'punkt';
      text: string;
      /** Tastenkürzel zur Anzeige rechts (⌘K, ⌥⌘→ …) — ausgeführt wird es woanders. */
      kuerzel?: string;
      /** Häkchen davor (Auswahl, Schalter) */
      an?: boolean;
      /** Name einer Glyphe aus lib/os/symbole-daten.ts, links vor dem Text (ein Häkchen geht vor) */
      symbol?: string;
      aus?: boolean;
      gefahr?: boolean;
      tun: () => void;
    }
  | { art: 'trenner' }
  | { art: 'titel'; text: string }
  | { art: 'unter'; text: string; punkte: MenuePunkt[]; aus?: boolean; symbol?: string };

export interface MenueOffen {
  x: number;
  y: number;
  punkte: MenuePunkt[];
  /** Aus der Menüleiste: unter dem Eintrag, links bündig; `quelle` markiert ihn als offen. */
  quelle?: string;
  /** Mit der Tastatur geöffnet: der erste Punkt ist gleich gewählt. */
  tastatur?: boolean;
}

const [offen, setOffen] = createSignal<MenueOffen | null>(null);
export const menue = offen;

/** Vorher gefilterte Liste ohne doppelte, führende oder schließende Trenner. */
export function aufraeumen(punkte: (MenuePunkt | false | null | undefined)[]): MenuePunkt[] {
  const out: MenuePunkt[] = [];
  for (const p of punkte) {
    if (!p) continue;
    if (p.art === 'trenner' && (out.length === 0 || out[out.length - 1]!.art === 'trenner')) continue;
    if (p.art === 'unter') {
      const u = aufraeumen(p.punkte);
      if (!u.length) continue;
      out.push({ ...p, punkte: u });
      continue;
    }
    out.push(p);
  }
  while (out.length && out[out.length - 1]!.art === 'trenner') out.pop();
  return out;
}

export function menueOeffnen(m: MenueOffen): void {
  const punkte = aufraeumen(m.punkte);
  setOffen(punkte.length ? { ...m, punkte } : null);
}
export const menueZu = (): void => {
  setOffen(null);
};

/** Wählbar = ein Punkt oder Untermenü, das nicht ausgegraut ist. */
export const waehlbar = (p: MenuePunkt): boolean => (p.art === undefined || p.art === 'punkt' || p.art === 'unter') && !('aus' in p && p.aus);

/** Nächster wählbarer Index in Richtung `r` (rundum). -1, wenn keiner. */
export function naechster(punkte: MenuePunkt[], ab: number, r: 1 | -1): number {
  const n = punkte.length;
  for (let k = 1; k <= n; k++) {
    const i = (((ab + r * k) % n) + n) % n;
    if (waehlbar(punkte[i]!)) return i;
  }
  return -1;
}

/** Wohin ein Menü der Größe `b`×`h` an Punkt (x, y) passt, ohne aus dem Fenster zu ragen. */
export function lage(x: number, y: number, b: number, h: number, vw: number, vh: number, rand = 8): { x: number; y: number } {
  let nx = x;
  let ny = y;
  if (nx + b > vw - rand) nx = Math.max(rand, x - b);
  if (ny + h > vh - rand) ny = Math.max(rand, vh - rand - h);
  return { x: Math.max(rand, nx), y: Math.max(rand, ny) };
}

/** Tastenkürzel passend zum Gerät: ⌘ auf dem Mac, sonst Strg. */
export const IST_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
export const mod = (rest: string): string => (IST_MAC ? `⌘${rest}` : `Strg+${rest}`);
export const modAlt = (rest: string): string => (IST_MAC ? `⌥⌘${rest}` : `Strg+Alt+${rest}`);
/** ⌃⌘ (Vollbild-Bildschirm): auf Windows und Linux Strg+Alt, weil dort die Windows-Taste dem System gehört */
export const ctrlMod = (rest: string): string => (IST_MAC ? `⌃⌘${rest}` : `Strg+Alt+${rest}`);
/** ⌥⇧ (Fenster im Kopf rücken): auf Windows und Linux „Alt+Umschalt“ statt Mac-Zeichen */
export const altUmschalt = (rest: string): string => (IST_MAC ? `⌥⇧${rest}` : `Alt+Umschalt+${rest}`);
