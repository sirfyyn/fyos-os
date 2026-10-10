/**
 * Abruf mit DREI Ausgängen — damit „nichts da" und „nicht erreichbar" nicht dasselbe sind.
 *
 * ## Warum es das gibt
 *
 * Ein fehlgeschlagener `fetch`, der als leeres Ergebnis erscheint, ist eine Lüge: die Oberfläche
 * zeigt „Keine Einträge", obwohl das Backend nur nicht erreichbar ist. Besonders teuer ist der
 * **Totalausfall** — ein Backend, das gar nicht antwortet, erzeugt keinen Statuscode, sondern
 * einen Wurf, und den fängt ein `catch { return [] }` still ab.
 *
 * ## Warum ein Rückgabetyp und nicht „bitte immer melden"
 *
 * `fetchJson` wirft bereits sauber. Stumme Stellen entstehen trotzdem, und zwar aus
 * **Gewohnheit**: `catch { return [] }` ist zwei Zeichen kürzer als jede ehrliche Alternative.
 *
 * Gegen Gewohnheiten hilft kein Merkposten, sondern eine Form, in der das Ehrliche der
 * kürzere Weg ist. Hier: der Zustand ist Teil des Rückgabewerts, und wer ihn ignoriert,
 * bekommt von TypeScript keine Daten.
 *
 * ## Verhaeltnis zu `client.ts`
 *
 * Beide sitzen auf transport.ts — gleiche Strecke, zwei Formen: `hole()` gibt den Fehler
 * zurueck, `fetchJson()` wirft ihn.
 *
 * Es gibt in diesem Verzeichnis zwei Schichten, und wer neu dazukommt, muss wissen,
 * welche er nimmt.
 *
 *     client.ts   getippter Transport (openapi-fetch, RFC 7807) — WIRFT bei nicht-2xx
 *     abruf.ts    macht den Fehler zum Rueckgabewert — er laesst sich nicht ueberspringen
 *
 * Sie loesen verschiedene Haelften desselben Problems. `fetchJson` wirft bereits sauber;
 * stumme Stellen entstehen an der **Aufrufstelle**, wo `catch { return [] }` zwei Zeichen
 * kuerzer ist. Diese Datei setzt genau dort an.
 *
 * Faustregel: neue Aufrufe nehmen `hole()`. Wer `fetchJson` benutzt, muss den Wurf selbst
 * fangen UND melden — dann ist er gleich gut.
 *
 * ## Gebrauch
 *
 *     const a = await hole<Server[]>('/api/fyos/mcp');
 *     if (a.zustand === 'nicht_erreichbar') return <Hinweis text={a.grund} />;
 *     if (a.zustand === 'leer')             return <p>Keine Server eingerichtet.</p>;
 *     return <Liste eintraege={a.daten} />;
 *
 * `a.daten` existiert **nur** im Zweig `'daten'` — die anderen beiden Fälle lassen sich
 * nicht überspringen, ohne dass der Compiler es merkt.
 */

import { strecke } from './transport';

/** Die drei Zustände. `leer` ist eine Aussage über die Daten, `nicht_erreichbar` über die Strecke. */
export type Abruf<T> =
  | { zustand: 'daten'; daten: T }
  | { zustand: 'leer' }
  | {
      zustand: 'nicht_erreichbar';
      grund: string;
      status?: number;
      /** Die Strecke war da, nur die Anmeldung ist abgelaufen (Banner zeigt „neu anmelden"). */
      sitzung?: boolean;
    };

/** Gilt eine leere Liste als `leer`? Vorgabe ja — ein leeres Array ist keine Antwort mit Inhalt. */
function istLeer(d: unknown): boolean {
  if (d === null || d === undefined) return true;
  if (Array.isArray(d)) return d.length === 0;
  if (typeof d === 'object') return Object.keys(d as object).length === 0;
  return false;
}

/**
 * Einen JSON-Endpunkt abrufen. Wirft nicht — der Fehlerfall ist Teil des Rückgabewerts.
 *
 * Wichtig: **kein Statuscode ist auch ein Ergebnis.** Ein `TypeError: Failed to fetch`
 * (Backend weg, DNS tot, Netz weg) landet hier als `nicht_erreichbar` OHNE `status`.
 * Über transport.ts: abgelaufene Sitzung (302 → Anmeldung) wird als
 * solche erkannt statt als „nicht erreichbar", und nach `ZEIT_MS` ist Schluss.
 */
export async function hole<T>(pfad: string, init?: RequestInit & { zeitMs?: number }): Promise<Abruf<T>> {
  const s = await strecke(pfad, init);
  switch (s.art) {
    case 'ok':
      return istLeer(s.daten) ? { zustand: 'leer' } : { zustand: 'daten', daten: s.daten as T };
    case 'http':
      return { zustand: 'nicht_erreichbar', grund: s.grund, status: s.status };
    case 'sitzung':
      return { zustand: 'nicht_erreichbar', grund: s.grund, status: 401, sitzung: true };
    case 'kein_json':
      // 200 mit kaputtem Körper ist ein Defekt, kein leeres Ergebnis.
      return { zustand: 'nicht_erreichbar', grund: s.grund, status: s.res.status };
    default:
      return { zustand: 'nicht_erreichbar', grund: s.grund };
  }
}

/**
 * Kurzform für die Oberfläche: ein Satz, der den Zustand benennt — oder `null` bei Daten.
 *
 * Bewusst KEIN Text wie „keine Daten vorhanden" für beide Fälle. Der Unterschied ist der
 * einzige, der zählt.
 */
export function hinweisText<T>(a: Abruf<T>, wasLeer = 'Nichts vorhanden.'): string | null {
  if (a.zustand === 'daten') return null;
  if (a.zustand === 'leer') return wasLeer;
  return `Nicht erreichbar: ${a.grund}`;
}
