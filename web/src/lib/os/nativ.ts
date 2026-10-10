/**
 * nativ.ts — native Flächen des OS: Solid-Komponenten, die direkt im Fenster laufen, ohne eingebettete Seite.
 *
 * Vertrag für alle, die eine native Fläche bauen:
 *   - Eingebaute stehen in EINER Datei unter lib/os/nativ/ (je Strang eine Datei); Plugins registrieren ihre über
 *     `registriereFlaechen({ flaechen: [{ art: 'nativ', laden, … }] })` (lib/os/register.ts).
 *   - `id` beginnt mit `nativ:`; `laden` lädt die Komponente erst, wenn das Fenster aufgeht.
 *   - Die Komponente bekommt `NativProps`, füllt die Fensterfläche (h-full, eigenes Scrollen) und
 *     benutzt die Klassen aus styles/os.css — kein eigener Stil.
 *   - Sie lädt ihre Daten selbst über `hub()` (lib/hub.ts) und zeigt Laden, Leer und Fehler ehrlich.
 */
import type { Component } from 'solid-js';
import type { Flaeche } from './flaechen';
import { EINSTELLUNGEN } from './nativ/einstellungen';
import { KACHELN } from './nativ/kacheln';
import { registrierteFlaechen } from './register';

export interface NativProps {
  /** Öffnet eine andere Fläche im OS (z. B. aus einer Kachel heraus). */
  oeffne: (id: string) => void;
  /** Das Fenster ist gerade schmal (Handy oder schmale Spalte) — kompakter darstellen. */
  schmal: boolean;
}

export interface NativEintrag {
  id: `nativ:${string}`;
  titel: string;
  /** Gruppe im Start, wie bei den übrigen Flächen (GRUPPEN_REIHENFOLGE in flaechen.ts) */
  gruppe: string;
  kuerzel: string;
  laden: () => Promise<{ default: Component<NativProps> }>;
  /** Beim Öffnen gleich über die ganze Breite */
  breit?: boolean;
}

/** Eingebaute native Flächen. */
export const NATIVE: NativEintrag[] = [...KACHELN, ...EINSTELLUNGEN];

export const nativZu = (id: string): Pick<NativEintrag, 'id' | 'laden'> | undefined => {
  const eingebaut = NATIVE.find((n) => n.id === id);
  if (eingebaut) return eingebaut;
  const f = registrierteFlaechen().find((x) => x.id === id && x.art === 'nativ' && x.laden);
  return f ? { id: f.id as `nativ:${string}`, laden: f.laden! } : undefined;
};

export function nativeFlaechen(): Flaeche[] {
  return NATIVE.map((n) => ({
    id: n.id,
    titel: n.titel,
    gruppe: n.gruppe,
    art: 'nativ' as const,
    kuerzel: n.kuerzel,
    breit: n.breit,
  }));
}
