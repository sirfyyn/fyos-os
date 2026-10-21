/**
 * suche.ts — Suche über alles in ⌘K (Start).
 *
 * Neben den Flächen (nach Namen) fragt der Start den Hub (`suche__alles`, Plugin `suche`): Vorgänge, Mail, Dateien, Notizen und
 * was Plugins als Quelle anmelden (docs/ERWEITERN.md, „Suche über alles"). Hier liegt alles, was ohne Oberfläche geht:
 *
 *   - `sucheStarten`        wartet, bis die Eingabe ruht, fragt den Hub einmal und wirft veraltete Antworten weg
 *   - `gruppiert`           Treffer nach Quelle, in der Reihenfolge, in der sie ankamen
 *   - `trefferWeg`          was ein Klick auf den Treffer tut: das Ding in seiner App zeigen (oder nichts, wenn es kein Ding ist)
 *
 * Treffer sind Fremdinhalt (Betreffzeilen, Dateitext): sie werden nur als Text angezeigt, nie als HTML.
 */
import { registrierteDinge } from './register';

/** Ein Treffer, wie `suche__alles` ihn liefert. */
export interface Treffer {
  quelle: string;
  quelle_titel: string;
  /** Ding-Typ (`fyos://<typ>/<id>`), wenn die Quelle einen hat */
  typ?: string;
  id: string;
  titel: string;
  auszug: string;
}

export interface QuellenBericht {
  quelle: string;
  titel: string;
  zustand: 'ok' | 'nicht eingerichtet' | 'fehler';
  anzahl: number;
}

export interface SucheAntwort {
  abfrage: string;
  treffer: Treffer[];
  quellen: QuellenBericht[];
}

export type SucheZustand =
  | { art: 'leer' }
  | { art: 'laeuft'; abfrage: string }
  | { art: 'fertig'; abfrage: string; treffer: Treffer[]; fehlend: string[] }
  | { art: 'fehler'; abfrage: string; text: string };

/** Ab so vielen Zeichen wird gesucht (der Hub verlangt dasselbe). */
export const ABFRAGE_MIN = 2;
export const WARTEZEIT_MS = 250;

/** Die Abfrage, wie sie an den Hub geht: Leerraum zusammengezogen. */
export const abfrageSauber = (roh: string): string => roh.split(/\s+/).filter(Boolean).join(' ');

export const sucheMoeglich = (roh: string): boolean => abfrageSauber(roh).length >= ABFRAGE_MIN;

const istObjekt = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): string => (typeof v === 'string' ? v : '');

/** Antwort des Hubs prüfen und auf bekannte Felder zurechtstutzen (sie kommt von außen). Unbrauchbares ergibt `null`. */
export function antwortLesen(roh: unknown): SucheAntwort | null {
  if (!istObjekt(roh) || !Array.isArray(roh.treffer)) return null;
  const treffer: Treffer[] = [];
  for (const t of roh.treffer) {
    if (!istObjekt(t) || typeof t.id !== 'string' || !t.id || typeof t.quelle !== 'string') continue;
    const e: Treffer = { quelle: t.quelle, quelle_titel: text(t.quelle_titel) || t.quelle, id: t.id, titel: text(t.titel) || t.id, auszug: text(t.auszug) };
    if (typeof t.typ === 'string' && /^[a-z][a-z0-9-]*$/.test(t.typ)) e.typ = t.typ;
    treffer.push(e);
  }
  const quellen: QuellenBericht[] = [];
  for (const q of Array.isArray(roh.quellen) ? roh.quellen : []) {
    if (!istObjekt(q) || typeof q.quelle !== 'string') continue;
    const zustand = q.zustand === 'nicht eingerichtet' || q.zustand === 'fehler' ? q.zustand : 'ok';
    quellen.push({ quelle: q.quelle, titel: text(q.titel) || q.quelle, zustand, anzahl: typeof q.anzahl === 'number' ? q.anzahl : 0 });
  }
  return { abfrage: text(roh.abfrage), treffer, quellen };
}

/** Treffer nach Quelle gruppiert; die Reihenfolge der ersten Treffer bestimmt die der Gruppen. */
export function gruppiert(treffer: Treffer[]): { quelle: string; titel: string; treffer: Treffer[] }[] {
  const gruppen = new Map<string, { quelle: string; titel: string; treffer: Treffer[] }>();
  for (const t of treffer) {
    const g = gruppen.get(t.quelle) ?? { quelle: t.quelle, titel: t.quelle_titel, treffer: [] };
    g.treffer.push(t);
    gruppen.set(t.quelle, g);
  }
  return [...gruppen.values()];
}

/**
 * Was ein Klick auf den Treffer tut. Ein Treffer mit bekanntem Ding-Typ öffnet die App, die das Ding zeigt (und springt dorthin);
 * sonst gibt es nichts zu öffnen — der Treffer bleibt eine Anzeige.
 */
export function trefferWeg(t: Treffer): { typ: string; id: string; label: string } | null {
  if (!t.typ || !registrierteDinge(t.typ)) return null;
  return { typ: t.typ, id: t.id, label: t.titel };
}

/** Quellen, die nicht geantwortet haben (nicht eingerichtet oder Fehler): sie fehlen in den Treffern und werden genannt. */
export const fehlende = (q: QuellenBericht[]): string[] => q.filter((x) => x.zustand !== 'ok').map((x) => x.titel);

/**
 * Sucht, sobald die Eingabe `wartezeit` ruht. Jede neue Eingabe verwirft die laufende; eine Antwort auf eine alte Abfrage
 * kommt nie an. `ruf` fragt den Hub; ein Fehler wird zu einem Satz im Zustand (`fehler`), nie zu „nichts gefunden".
 */
export function sucheStarten(
  ruf: (abfrage: string) => Promise<unknown>,
  an: (z: SucheZustand) => void,
  wartezeit = WARTEZEIT_MS,
): { eingabe: (roh: string) => void; stopp: () => void } {
  let nr = 0;
  let uhr: ReturnType<typeof setTimeout> | undefined;
  const stopp = () => {
    nr++;
    if (uhr) clearTimeout(uhr);
    uhr = undefined;
  };
  return {
    stopp,
    eingabe(roh) {
      stopp();
      if (!sucheMoeglich(roh)) {
        an({ art: 'leer' });
        return;
      }
      const abfrage = abfrageSauber(roh);
      const mein = nr;
      an({ art: 'laeuft', abfrage });
      uhr = setTimeout(() => {
        uhr = undefined;
        Promise.resolve().then(() => ruf(abfrage)).then(
          (r) => {
            if (mein !== nr) return;
            const a = antwortLesen(r);
            if (!a) an({ art: 'fehler', abfrage, text: 'Die Suche hat nichts Brauchbares geantwortet.' });
            else an({ art: 'fertig', abfrage, treffer: a.treffer, fehlend: fehlende(a.quellen) });
          },
          (e: unknown) => {
            if (mein !== nr) return;
            an({ art: 'fehler', abfrage, text: e instanceof Error && e.message ? e.message : 'Die Suche ging nicht.' });
          },
        );
      }, wartezeit);
    },
  };
}
