/**
 * griffe.ts — kurz etwas schalten, ohne ein Fenster.
 *
 * Ein Griff ist ein schreibender Hub-Aufruf mit fertigen Argumenten („Lesezeichen setzen“, „Bericht anlegen“).
 * Die Befehlszeile des Startbildschirms und die Suche im Start (⌘K) schlagen beim Tippen passende Griffe vor; ein Klick
 * oder Enter schaltet. Es sind dieselben Werkzeuge, die die Apps der Plugins benutzen — nur ohne die App zu öffnen.
 *
 * Welche Griffe es gibt, bestimmen die eingerichteten Plugins: Ein Plugin, das Griffe anbietet, liefert sie über das
 * Hub-Werkzeug `griffe.liste` (`{ griffe: [{ id, titel, werkzeug, argumente, … }] }`). Fehlt das Werkzeug oder
 * antwortet es nicht, gibt es keine Griffe — die Suche bleibt benutzbar.
 *
 * Dazu kommen die Modus-Griffe „Ruhe“, „Normal“, „Ich bin da“, sobald der Hub einen Modus kennt (lib/os/modi.ts).
 *
 * `griffQuellenLaden` holt die Angebote, `griffeBauen` und `griffeFinden` sind rein und ohne Browser prüfbar.
 */
import { hub } from './hub';
import { MODI, MODUS_GRIFF, modusZustand, setzeModus, type Modus } from './os/modi';

export interface Griff {
  id: string;
  titel: string;
  /** Kopf der Gruppe in der Vorschlagsliste (frei, vom Plugin gewählt) */
  gruppe: string;
  /** Glyphe (lib/os/symbole-daten.ts) */
  symbol: string;
  werkzeug: string;
  argumente: Record<string, unknown>;
  /** Satz nach dem Schalten („Lesezeichen gesetzt“) */
  erfolg: string;
  /** Unterbricht etwas für Minuten: erst nachfragen */
  nachfragen?: boolean;
  /** Steht schon so (Schalter ist an): rückt nach hinten */
  istSchon?: boolean;
  /** Der Griff, der es zurücknimmt (an ↔ aus); fehlt bei einmaligen Handgriffen */
  gegen?: Omit<Griff, 'gegen'>;
  /** Zusätzliche Suchwörter */
  woerter?: string[];
}

/** Was ein Plugin als Griff anbietet; fehlende Felder füllt `griffeBauen` auf. */
export interface GriffAngebot {
  id: string;
  titel: string;
  werkzeug: string;
  argumente?: Record<string, unknown>;
  gruppe?: string;
  symbol?: string;
  erfolg?: string;
  nachfragen?: boolean;
  istSchon?: boolean;
  gegen?: Omit<GriffAngebot, 'gegen'>;
  woerter?: string[];
}

export interface GriffQuellen {
  /** Angebote der Plugins (Werkzeug `griffe.liste`) */
  griffe?: readonly GriffAngebot[];
  /** Der Modus jetzt (modus.zustand); fehlt er, gibt es keine Modus-Griffe */
  modus?: Modus;
}

/** Höchstens so viele Griffe nehmen wir von den Plugins an. */
const GRIFFE_MAX = 200;
const WERKZEUG_FORM = /^[A-Za-z0-9_.-]{1,120}$/;
const VORGABE_GRUPPE = 'Schalten';
const VORGABE_SYMBOL = 'wand-sparkles';

/** Raum- und Gerätenamen aus Kennungen, deren Umlaute ausgeschrieben sind */
const UMLAUT: Record<string, string> = { buero: 'büro', kueche: 'küche', gaeste: 'gäste', baeder: 'bäder', grosse: 'große' };

/** „ordner_neu“ → „Ordner neu“, „buero“ → „Büro“ */
export const schoen = (s: string): string => {
  const t = s.replace(/[_-]+/g, ' ').trim().split(/\s+/).map((w) => UMLAUT[w] ?? w).join(' ');
  return t ? t[0]!.toUpperCase() + t.slice(1) : t;
};

const text = (x: unknown, max: number): string | null => {
  if (typeof x !== 'string') return null;
  const t = x.replace(/\s+/g, ' ').trim();
  return t ? t.slice(0, max) : null;
};

function einzeln(a: GriffAngebot | Omit<GriffAngebot, 'gegen'>): Omit<Griff, 'gegen'> | null {
  if (!a || typeof a !== 'object') return null;
  const id = text(a.id, 120);
  const titel = text(a.titel, 80);
  const werkzeug = typeof a.werkzeug === 'string' && WERKZEUG_FORM.test(a.werkzeug) ? a.werkzeug : null;
  if (!id || !titel || !werkzeug) return null;
  const argumente = a.argumente && typeof a.argumente === 'object' && !Array.isArray(a.argumente) ? a.argumente : {};
  return {
    id,
    titel,
    gruppe: text(a.gruppe, 40) ?? VORGABE_GRUPPE,
    symbol: text(a.symbol, 40) ?? VORGABE_SYMBOL,
    werkzeug,
    argumente,
    erfolg: text(a.erfolg, 120) ?? titel,
    ...(a.nachfragen === true ? { nachfragen: true } : {}),
    ...(a.istSchon === true ? { istSchon: true } : {}),
    ...(Array.isArray(a.woerter) ? { woerter: a.woerter.filter((w): w is string => typeof w === 'string').slice(0, 20) } : {}),
  };
}

/** Alle Griffe aus den Quellen, in der Reihenfolge der Angebote; Ungültiges und Doppeltes fällt weg. */
export function griffeBauen(q: GriffQuellen): Griff[] {
  const g: Griff[] = [];
  const jetzt = q.modus;
  if (jetzt) {
    // Ausgeführt über setzeModus, damit das Gerät sofort mitschaltet (griffAusfuehren)
    const ein = (m: Modus): Omit<Griff, 'gegen'> => ({
      id: `modus:${m}`, titel: MODUS_GRIFF[m].titel, gruppe: 'Modus', symbol: m === 'ruhe' ? 'moon' : m === 'bereit' ? 'sparkles' : 'bell',
      werkzeug: 'modus.setzen', argumente: { modus: m, von: 'griff' }, erfolg: `Modus ${m === 'bereit' ? 'Bereit' : MODUS_GRIFF[m].titel}`,
      istSchon: jetzt === m, woerter: MODUS_GRIFF[m].woerter,
    });
    for (const m of MODI) g.push({ ...ein(m), ...(jetzt !== m ? { gegen: ein(jetzt) } : {}) });
  }
  const gesehen = new Set<string>(g.map((x) => x.id));
  for (const a of (q.griffe ?? []).slice(0, GRIFFE_MAX)) {
    const eins = einzeln(a);
    if (!eins || gesehen.has(eins.id)) continue;
    gesehen.add(eins.id);
    const gegen = a.gegen ? einzeln(a.gegen) : null;
    g.push(gegen ? { ...eins, gegen } : eins);
  }
  return g;
}

const norm = (s: string): string =>
  s.toLowerCase().replace(/ß/g, 'ss').replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/[_\-.,!?:;„“"]+/g, ' ');
const woerterVon = (s: string): string[] => norm(s).split(/\s+/).filter(Boolean);

/** Füllwörter: zählen, wenn sie passen, und stören nicht, wenn nicht („schalte das Licht im Flur aus“). */
const FUELL = new Set(['schalte', 'schalten', 'mach', 'mache', 'bitte', 'auf', 'die', 'den', 'das', 'der', 'im', 'in', 'am', 'zu', 'szene', 'licht', 'lampe', 'ein']);

function passt(frage: string, wort: string): boolean {
  // Kurze Wörter nur genau („an“ ist nicht der Anfang von „Anker“), längere auch als Anfang
  if (frage.length <= 3) return wort === frage;
  return wort.startsWith(frage);
}

/**
 * Griffe zur Eingabe, bester zuerst. Jedes Wort der Eingabe außer Füllwörtern muss zu einem Wort des Griffs passen;
 * „ein“ heißt „an“. Was schon so steht, kommt nach hinten. Leere oder einbuchstabige Eingaben finden nichts.
 */
export function griffeFinden(griffe: readonly Griff[], eingabe: string, max = 6): Griff[] {
  const frage = woerterVon(eingabe).map((w) => (w === 'ein' ? 'an' : w));
  if (!frage.length || norm(eingabe).trim().length < 2) return [];
  const bewertet: { g: Griff; wert: number }[] = [];
  for (const g of griffe) {
    const titel = woerterVon(g.titel);
    const alle = [...titel, ...(g.woerter ?? []).flatMap(woerterVon)];
    let wert = 0;
    let ok = true;
    let echte = 0;
    for (const f of frage) {
      const imTitel = titel.some((w) => passt(f, w));
      if (imTitel || alle.some((w) => passt(f, w))) {
        wert += imTitel ? 2 : 1;
        // Ein Griff braucht ein echtes Wort ab drei Zeichen: „an“ allein schaltet nichts
        if (!FUELL.has(f) && f.length >= 3) echte += 1;
      } else if (!FUELL.has(f)) {
        ok = false;
        break;
      }
    }
    if (!ok || !echte) continue;
    // Kürzere Titel, die die Eingabe ganz abdecken, zuerst; was schon so steht, zuletzt
    wert -= titel.length * 0.1;
    if (g.istSchon) wert -= 5;
    bewertet.push({ g, wert });
  }
  return bewertet.sort((a, b) => b.wert - a.wert).slice(0, max).map((x) => x.g);
}

type Lesen = <T>(werkzeug: string) => Promise<T | undefined>;
const lesen: Lesen = async <T,>(werkzeug: string) => {
  try {
    return await hub<T>(werkzeug, {}, { zeitMs: 6000 });
  } catch {
    return undefined; // 403/404/Fehler: das Plugin ist nicht eingerichtet — dann gibt es keine Griffe
  }
};

/** Holt die Angebote aus dem Hub; was nicht antwortet, fehlt. Den Modus kennt modi.ts schon (eigene Abfrage). */
export async function griffQuellenLaden(l: Lesen = lesen, m: () => Modus | undefined = () => modusZustand()?.modus): Promise<GriffQuellen> {
  const r = await l<{ griffe?: GriffAngebot[] }>('griffe.liste');
  const modus = m();
  return { griffe: Array.isArray(r?.griffe) ? r.griffe : undefined, ...(modus ? { modus } : {}) };
}

/** Einmal geholt, 60 s lang wiederverwendet (Befehlszeile und Start teilen sich das). */
let vorrat: { zeit: number; griffe: Promise<Griff[]> } | null = null;
export function griffeHolen(jetzt = Date.now()): Promise<Griff[]> {
  if (!vorrat || jetzt - vorrat.zeit > 60_000) vorrat = { zeit: jetzt, griffe: griffQuellenLaden().then(griffeBauen) };
  return vorrat.griffe;
}
/** Nach dem Schalten: beim nächsten Tippen frisch holen (der Zustand hat sich geändert). */
export const griffeVergessen = (): void => {
  vorrat = null;
};

/** Schaltet; wirft mit dem Grund des Hubs, wenn es nicht ging. */
export async function griffAusfuehren(g: Pick<Griff, 'werkzeug' | 'argumente'>): Promise<void> {
  const m = g.argumente.modus;
  if (g.werkzeug === 'modus.setzen' && (MODI as readonly unknown[]).includes(m)) await setzeModus(m as Modus, { von: 'griff' });
  else await hub(g.werkzeug, g.argumente, { art: 'bewusst', zeitMs: 20_000 });
  griffeVergessen();
}
