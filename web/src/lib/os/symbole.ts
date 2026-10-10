/**
 * symbole.ts — Symbol und Farbe je Fläche.
 *
 * Jede Fläche hat eine Glyphe (Lucide, lib/os/symbole-daten.ts) auf einer Kachel in der Farbe ihres Bereichs —
 * wie App-Symbole am Mac. Unbekannte Flächen fallen auf ein Fenster-Symbol zurück, ihr Farbton kommt aus der ID.
 *
 * Quellen, von stark nach schwach:
 *   1. Gesichter, die der Hub für Apps mitliefert (`symboleSetzen`, lib/mcp-apps/gesicht.ts)
 *   2. die Tabelle, die Plugins und die Konfiguration über `registriereFlaechen({ symbole })` füllen
 *   3. die eingebaute Tabelle unten (Agent, Einstellungen)
 */
import { createSignal } from 'solid-js';
import { registrierteSymbole } from './register';
import { SYMBOLE } from './symbole-daten';

/**
 * Glyphe und Farbton der eingebauten Flächen — jede Fläche hat ihre EIGENE Glyphe. Farbton 0–359,
 * -1 = grafit (wie Systemeinstellungen), -2 = Neonverlauf des OS (Agent).
 */
export const SYMBOL_TABELLE: Record<string, [glyphe: string, ton: number]> = {
  agent: ['sparkles', -2],
  'nativ:einstellungen': ['settings', -1],
};

const eintrag = (id: string): [string, number] | undefined => {
  const eigen = registrierteSymbole(id);
  if (eigen) return eigen;
  if (SYMBOL_TABELLE[id]) return SYMBOL_TABELLE[id];
  if (id.startsWith('app:')) {
    const praefix = `app:${id.slice(4).split('__')[0]}`;
    return registrierteSymbole(praefix) ?? SYMBOL_TABELLE[praefix];
  }
  return undefined;
};

/** Unbekannte Flächen: Fenster-Symbol, Farbton aus der ID (über den ganzen Farbkreis). */
const tonAusId = (id: string): number => {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
};

/**
 * Gesichter, die der Hub mitliefert: Symbol und Farbe einer App kommen aus EINER Quelle und gelten in Dock,
 * Start, Fensterkopf und Katalog gleich. Das Signal sorgt dafür, dass bereits gezeichnete Symbole nachziehen,
 * sobald die Liste da ist.
 *
 *   glyphe  Name einer Glyphe aus symbole-daten.ts (nur gesetzt, wenn wir sie selbst zeichnen können)
 *   ton     Farbton wie in der Tabelle
 *   icon    fertiges SVG-Bild des Hubs (data:image/svg+xml), falls die Glyphe bei uns fehlt
 */
export interface SymbolUeberschrieb {
  glyphe?: string;
  ton?: number;
  icon?: string;
}
const [stand, setStand] = createSignal(0);
const ueberschrieben = new Map<string, SymbolUeberschrieb>();

export function symboleSetzen(liste: Record<string, SymbolUeberschrieb>): void {
  let geaendert = false;
  for (const [id, neu] of Object.entries(liste)) {
    const alt = ueberschrieben.get(id);
    if (alt && alt.glyphe === neu.glyphe && alt.ton === neu.ton && alt.icon === neu.icon) continue;
    ueberschrieben.set(id, neu);
    geaendert = true;
  }
  if (geaendert) setStand((n) => n + 1);
}

/** Nur für Tests: alle Hub-Gesichter vergessen. */
export function symboleZuruecksetzen(): void {
  ueberschrieben.clear();
  setStand((n) => n + 1);
}

export const glyphe = (id: string): string => {
  stand();
  return ueberschrieben.get(id)?.glyphe ?? eintrag(id)?.[0] ?? 'app-window';
};

/** SVG-Inhalt (Pfade) einer Glyphe, 24×24, Strich über currentColor. */
export const glypheSvg = (name: string): string => SYMBOLE[name] ?? SYMBOLE['app-window']!;

/** Farbton der Kachel: -1 = grafit, -2 = Neon des OS, sonst 0–359. */
export const farbton = (id: string): number => {
  stand();
  return ueberschrieben.get(id)?.ton ?? eintrag(id)?.[1] ?? tonAusId(id);
};

/** Fertiges Bild des Hubs, wenn die Glyphe der App bei uns nicht vorkommt (sonst undefined). */
export const symbolBild = (id: string): string | undefined => {
  stand();
  const u = ueberschrieben.get(id);
  return u?.icon && !u.glyphe ? u.icon : undefined;
};
