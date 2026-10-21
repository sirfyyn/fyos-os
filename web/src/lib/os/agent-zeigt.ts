/**
 * agent-zeigt.ts — „Der Agent zeigt dir …“ über die OS-Brücke (lib/os/bruecke-neu.ts).
 *
 * Ruft der Agent eine Hub-App auf, schickt der Hub das Ergebnis zusätzlich an die offenen OS-Sitzungen (Befehl
 * `zeigt`). Das OS zeigt es als Mitteilung oben rechts (components/os/Mitteilungen.tsx); ein Klick öffnet die App.
 * Ist gerade ein Anruf offen oder die Fläche des Agenten vorn, öffnet es sofort — dort würde eine Mitteilung nur
 * stören.
 *
 * Daten, Stapel (höchstens 3, gleiche App mit gleicher Eingabe binnen 60 s ersetzt statt zu stapeln) und die
 * Einstellung „stumm / aus“ liegen in lib/os/mitteilungen.ts; hier werden sie weitergereicht und um das ergänzt,
 * was nur die Brücke mitbringt: Symbol und Farbton der App, die Dringlichkeit und was das Gerät dazu tut (`audio`:
 * Hinweiston, Vorlesen — der Hub rechnet es aus dem Ton-Modus, lib/os/ton-modus.ts).
 * Kein Solid, kein DOM.
 */
import { zeigtPruefen as zeigtGrundPruefen, type ZeigtDaten as ZeigtGrund } from './mitteilungen';

export {
  ANZEIGE_MS,
  GLEICH_MS,
  MAX_STAPEL,
  SPEICHER_SCHLUESSEL,
  einstellungLesen,
  einstellungSchreiben,
  hinzufuegen,
  istStumm,
  schluesselVon,
  stabilJson,
  zeitText,
  type Mitteilung,
  type ZeigtEinstellung,
} from './mitteilungen';

export interface ZeigtDaten extends ZeigtGrund {
  /** Lucide-Name und Farbton, falls der Hub sie mitgibt (das OS nimmt zuerst die eigene Tabelle) */
  symbol: string | null;
  ton: number | null;
  /** Was das Gerät dazu tut — der Hub rechnet es aus dem Ton-Modus (lib/os/ton-modus.ts); null = nichts */
  audio: { modus: string; klang: boolean; sprechen: boolean } | null;
  dringlichkeit: 'niedrig' | 'normal' | 'hoch' | null;
}

const text = (x: unknown, max: number): string | null => {
  if (typeof x !== 'string') return null;
  const t = x.replace(/\s+/g, ' ').trim();
  return t ? t.slice(0, max) : null;
};

function audioPruefen(x: unknown): ZeigtDaten['audio'] {
  if (!x || typeof x !== 'object') return null;
  const a = x as Record<string, unknown>;
  return { modus: typeof a.modus === 'string' ? a.modus.slice(0, 20) : 'ton', klang: a.klang === true, sprechen: a.sprechen === true };
}

/** Die Nutzlast des Hubs prüfen und auf die Form bringen, die das OS zeigt. Ohne Ziel: null. */
export function zeigtPruefen(roh: unknown): ZeigtDaten | null {
  const grund = zeigtGrundPruefen(roh);
  if (!grund) return null;
  const r = roh as Record<string, unknown>;
  return {
    ...grund,
    symbol: text(r.symbol, 40),
    ton: typeof r.ton === 'number' && Number.isFinite(r.ton) ? r.ton : null,
    audio: audioPruefen(r.audio),
    dringlichkeit: r.dringlichkeit === 'niedrig' || r.dringlichkeit === 'normal' || r.dringlichkeit === 'hoch' ? r.dringlichkeit : null,
  };
}
