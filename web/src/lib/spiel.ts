/**
 * spiel.ts — Spielstand im Browser (OS-Neubau P9, Nr. 707: „ernsthaft mit punkten und leveln. das soll spaß machen“).
 *
 * Ein Speicher für alle Flächen: `spielStand()` (Level, Punkte, Anteil, Freischaltungen der Katze). `spielMelden()` meldet
 * ein ECHTES Ereignis an `spiel.ereignis` (idempotent über den Schlüssel) und feuert bei neuen Punkten `fyos:spiel` am
 * window; die Feier (components/spiel/SpielFeier.tsx) zeigt sie, nie als Meldung, die unterbricht. Ist das Spiel aus,
 * wird gezählt, aber nichts gezeigt.
 */
import { createSignal } from 'solid-js';
import { hub } from '~/lib/hub';

export interface SpielKurz {
  level: number;
  name: string;
  punkte: number;
  anteil: number;
  freigeschaltet: string[];
  an: boolean;
  naechstes_ab?: number | null;
}

export interface SpielFeierDetail {
  punkte: number;
  satz: string;
  levelAuf: boolean;
  freigeschaltet: string | null;
  abzeichen: { id: string; text: string }[];
  stand: SpielKurz;
}

export const SPIEL_EREIGNIS = 'fyos:spiel';

const [stand, setStand] = createSignal<SpielKurz | null>(null);
export const spielStand = stand;

let laeuft: Promise<void> | null = null;
export function spielLaden(): Promise<void> {
  laeuft ??= hub<SpielKurz>('spiel.stand')
    .then((s) => {
      if (s && typeof s.level === 'number') setStand(s);
    })
    .catch(() => undefined)
    .finally(() => {
      laeuft = null;
    });
  return laeuft;
}

interface EreignisAntwort {
  neu?: boolean;
  punkte?: number;
  satz?: string;
  level_auf?: boolean;
  freigeschaltet?: string | null;
  abzeichen_neu?: { id: string; text: string }[];
  stand?: SpielKurz;
}

/** Ein echtes Ereignis melden. Fehler schlucken: das Spiel darf nie eine Handlung scheitern lassen. */
export async function spielMelden(art: string, schluessel: string, mehr: Record<string, unknown> = {}): Promise<void> {
  try {
    const r = await hub<EreignisAntwort>('spiel.ereignis', { art, schluessel, ...mehr }, { art: 'bewusst' });
    if (r?.stand) setStand(r.stand);
    if (!r?.neu || !r.stand?.an) return;
    if (!r.punkte && !r.level_auf && !r.abzeichen_neu?.length) return;
    const detail: SpielFeierDetail = {
      punkte: r.punkte ?? 0,
      satz: r.satz ?? '',
      levelAuf: !!r.level_auf,
      freigeschaltet: r.freigeschaltet ?? null,
      abzeichen: r.abzeichen_neu ?? [],
      stand: r.stand,
    };
    window.dispatchEvent(new CustomEvent<SpielFeierDetail>(SPIEL_EREIGNIS, { detail }));
  } catch {
    /* ohne Spiel-Plugin: still weiter */
  }
}

/** Ist ein ISO-Zeitpunkt heute (Ortszeit)? Für „am selben Tag beantwortet“. */
export function istHeute(iso: string | null | undefined, jetzt = new Date()): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && d.toDateString() === jetzt.toDateString();
}

/** Nur für Tests. */
export function spielZuruecksetzen(): void {
  setStand(null);
  laeuft = null;
}
