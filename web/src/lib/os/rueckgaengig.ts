/**
 * rueckgaengig.ts — „Rückgängig“ nach dem Schließen.
 *
 * Wer ein Fenster oder einen Bildschirm schließt, sieht oben rechts für einige Sekunden eine Karte mit „Rückgängig“
 * (components/os/Mitteilungen.tsx, `HinweisKarte`). Diese Datei hält die eine Karte, die gerade steht (Shell und Brücke
 * teilen sie), und die reinen Funktionen, die das Geschlossene zurückholen: an dieselbe Stelle, mit Größe und
 * Startzustand. Was inzwischen anderswo offen ist, bleibt dort (nichts doppelt).
 */
import { createSignal } from 'solid-js';
import type { Fenster } from './anordnung';
import { BILDSCHIRME_MAX, wo, type Arbeitsplatz, type Bildschirm } from './bildschirme';

export interface RueckHinweis {
  text: string;
  /** Fehlt bei etwas, das sich nicht zurücknehmen lässt (eine Szene): dann nur die Meldung, ohne Knopf */
  zurueck?: () => void;
  /** Glyphe der Karte (lib/os/symbole-daten.ts), Vorgabe `bell-off` */
  symbol?: string;
}

const [hinweis, setHinweis] = createSignal<RueckHinweis | null>(null);
/** Die Karte, die gerade steht (oder null). */
export const rueckHinweis = hinweis;
/** Eine Karte zeigen; eine stehende wird ersetzt. */
export const rueckgaengigAnbieten = (h: RueckHinweis | null): void => {
  setHinweis(h);
};

/** Fenster, die in `neu` fehlen (geschlossen), mit ihrer alten Stelle. Minimierte zählen mit. */
export function geschlossene(alt: Fenster[], neu: Fenster[]): { fenster: Fenster; index: number }[] {
  const bleibt = new Set(neu.map((w) => w.id));
  return alt.flatMap((fenster, index) => (bleibt.has(fenster.id) ? [] : [{ fenster, index }]));
}

/**
 * Geschlossene Fenster zurück auf ihren Bildschirm (über die Kennung), jedes an seine alte Stelle. Gibt es den Bildschirm
 * nicht mehr, kommen sie auf einen neuen. Was inzwischen wieder offen ist, wird übersprungen.
 */
export function fensterZurueck(ap: Arbeitsplatz, bildschirmId: string, eintraege: { fenster: Fenster; index: number }[]): Arbeitsplatz {
  const fehlen = eintraege.filter((e) => wo(ap, e.fenster.id) < 0).sort((a, b) => a.index - b.index);
  if (!fehlen.length) return ap;
  const j = ap.bildschirme.findIndex((b) => b.id === bildschirmId);
  if (j < 0) {
    if (ap.bildschirme.length >= BILDSCHIRME_MAX) return ap;
    const b: Bildschirm = { id: bildschirmId, name: `Bildschirm ${ap.bildschirme.length + 1}`, fenster: fehlen.map((e) => e.fenster) };
    const bildschirme = [...ap.bildschirme, b];
    return { ...ap, bildschirme, aktiv: bildschirme.length, zuletzt: bildschirme.length };
  }
  const liste = [...ap.bildschirme[j]!.fenster];
  for (const e of fehlen) liste.splice(Math.min(e.index, liste.length), 0, e.fenster);
  return { ...ap, bildschirme: ap.bildschirme.map((b, k) => (k === j ? { ...b, fenster: liste } : b)), aktiv: j + 1 };
}

/**
 * Einen entfernten Bildschirm an seine alte Stelle zurück (`index` wie in bildschirme.ts, 1 = erster Arbeitsbildschirm)
 * und dorthin wechseln. Fenster, die inzwischen anderswo offen sind, bleiben dort.
 */
export function bildschirmZurueck(ap: Arbeitsplatz, index: number, b: Bildschirm): Arbeitsplatz {
  if (ap.bildschirme.some((x) => x.id === b.id) || ap.bildschirme.length >= BILDSCHIRME_MAX) return ap;
  const fenster = b.fenster.filter((w) => wo(ap, w.id) < 0);
  const pos = Math.max(0, Math.min(index - 1, ap.bildschirme.length));
  const bildschirme = [...ap.bildschirme.slice(0, pos), { ...b, fenster }, ...ap.bildschirme.slice(pos)];
  return { ...ap, bildschirme, aktiv: pos + 1, zuletzt: pos + 1 };
}

/** Kurzer Satz für die Karte nach dem Schließen. */
export function schliessText(titel: string[], bildschirm?: string): string {
  if (bildschirm) return `„${bildschirm}“ entfernt.`;
  if (titel.length === 1) return `„${titel[0]}“ geschlossen.`;
  return `${titel.length} Fenster geschlossen.`;
}
