/**
 * zustand.ts — woran sich eine geöffnete App erinnert, solange sie offen ist.
 *
 * Der App-Rahmen (Fensterkopf im OS) braucht drei Dinge, die nur der Host mitbekommt:
 *   - die Eingabe, mit der die Ansicht gerade zustande gekommen ist (letzter lesender Werkzeugaufruf
 *     der App) — daraus wird der Link „Link kopieren" und die Eingabe bei „Agent fragen";
 *   - den Modellkontext, den die App selbst meldet (`ui/update-model-context`);
 *   - nichts davon verlässt den Browser, solange niemand „Agent fragen" oder „Link kopieren" drückt.
 *
 * Der Host (host.ts) schreibt, der Rahmen (rahmen.ts) liest. Schlüssel ist, was der Einbetter vergibt
 * (im OS die ID der Fläche, `app:<name>`); eigene Datei ohne Abhängigkeiten, damit beide sie laden
 * können, ohne einander zu brauchen.
 */
export interface AppZustand {
  /** Werkzeug, dessen Aufruf die aktuelle Ansicht ergeben hat (`<plugin>__<werkzeug>`). */
  werkzeug?: string;
  /** Argumente dieses Aufrufs. */
  eingabe?: Record<string, unknown>;
  /** Letzter Inhalt aus `ui/update-model-context`, wie die App ihn geschickt hat. */
  modellKontext?: unknown;
}

const MAX_EINTRAEGE = 40;
const speicher = new Map<string, AppZustand>();

/** Ergänzt den Zustand der App `schluessel`; was nicht genannt wird, bleibt. */
export function zustandMerken(schluessel: string, teil: Partial<AppZustand>): void {
  const alt = speicher.get(schluessel);
  speicher.delete(schluessel); // ans Ende: die zuletzt benutzten bleiben
  speicher.set(schluessel, { ...alt, ...teil });
  while (speicher.size > MAX_EINTRAEGE) {
    const aeltester = speicher.keys().next().value;
    if (aeltester === undefined) break;
    speicher.delete(aeltester);
  }
}

export const zustandVon = (schluessel: string): AppZustand => speicher.get(schluessel) ?? {};

/** Nur für Tests. */
export function zustandLeeren(): void {
  speicher.clear();
}
