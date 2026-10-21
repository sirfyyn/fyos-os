/**
 * bruecke-lage.ts — was die OS-Brücke dem Hub vom offenen OS erzählt.
 *
 * Die Brücke (lib/os/bruecke-neu.ts) verbindet das offene OS mit dem Hub: Der Agent sieht, was auf dem Bildschirm
 * offen ist, und kann etwas zeigen. Hier steht der reine Teil davon — aus dem Zustand der Shell (Arbeitsplatz,
 * Fokus, Agent-Dock, Flächen) wird die „Lage“ gebaut, ein Wort („Berichte“, „Notizen“) wird zu einer Fläche
 * aufgelöst. Kein Solid, kein DOM. (Deeplinks schreibt lib/os/oeffnen.ts.)
 *
 * Begriffe wie in der Shell: Bildschirm 0 ist der Start (die Zentrale), ab 1 die Arbeitsbildschirme;
 * eine Fläche ist `seite:<slug>`, `app:<plugin>__<werkzeug>`, `nativ:<name>` oder `agent`.
 */
import { START, bildschirmBei, type Arbeitsplatz } from './bildschirme';
import type { Flaeche, FlaechenArt } from './flaechen';

/** Der Agent als Fläche (flaechen.ts: AGENT_ID) — hier als Wert, damit dieses Modul leicht bleibt. */
const AGENT = 'agent';
/** Der Web-Anruf, falls ein Plugin ihn als native Fläche anbietet. */
export const ANRUF_ID = 'nativ:anruf';
/** Mehr Flächen meldet die Brücke nicht (der Hub begrenzt die Meldung ebenso). */
export const FLAECHEN_MAX = 300;

export interface LageFenster {
  id: string;
  titel: string;
  art: FlaechenArt;
  /** Index des Arbeitsbildschirms (ab 1) */
  bildschirm: number;
  bildschirm_name: string;
  /** Das Fenster, das auf dem aktiven Bildschirm vorn ist (Fokus, sonst das erste nicht minimierte) */
  vorne: boolean;
  min: boolean;
}

export interface Lage {
  /** Der Web-Anruf ist offen und nicht minimiert */
  anruf: boolean;
  /** Der Agent ist vorn: Anruf offen, Agent-Dock offen oder das Agent-Fenster vorn */
  agent_vorne: boolean;
  /** Aktiver Bildschirm, 0 = Start */
  bildschirm: number;
  bildschirme: { index: number; name: string }[];
  fenster: LageFenster[];
  flaechen: { id: string; titel: string; gruppe: string }[];
}

/** Was die Shell der Brücke gibt (Zugriffsfunktionen der Shell, ausgelesen zum Zeitpunkt der Frage). */
export interface LageQuelle {
  ap: Arbeitsplatz;
  fokus: string | null;
  /** Agent-Dock offen */
  agent: boolean;
  flaeche: (id: string) => Flaeche | undefined;
  flaechen: Flaeche[];
}

export function lageBauen(q: LageQuelle): Lage {
  const { ap } = q;
  const aktiv = bildschirmBei(ap, ap.aktiv);
  const sichtbar = aktiv ? aktiv.fenster.filter((w) => !w.min && q.flaeche(w.id)) : [];
  const vorneId = q.fokus && sichtbar.some((w) => w.id === q.fokus) ? q.fokus : (sichtbar[0]?.id ?? null);

  const fenster: LageFenster[] = [];
  ap.bildschirme.forEach((b, j) => {
    for (const w of b.fenster) {
      const f = q.flaeche(w.id);
      if (!f) continue; // eine Fläche, die es nicht mehr gibt, steht auch im Dock nicht
      fenster.push({
        id: w.id,
        titel: f.titel,
        art: f.art,
        bildschirm: j + 1,
        bildschirm_name: b.name,
        vorne: ap.aktiv === j + 1 && w.id === vorneId,
        min: !!w.min,
      });
    }
  });

  const anruf = fenster.some((w) => w.id === ANRUF_ID && !w.min);
  return {
    anruf,
    agent_vorne: anruf || q.agent || vorneId === AGENT,
    bildschirm: ap.aktiv,
    bildschirme: [{ index: START, name: 'Start' }, ...ap.bildschirme.map((b, j) => ({ index: j + 1, name: b.name }))],
    fenster,
    flaechen: q.flaechen.slice(0, FLAECHEN_MAX).map((f) => ({ id: f.id, titel: f.titel, gruppe: f.gruppe })),
  };
}

/** Ist die Fläche offen und nicht minimiert (der Agent auch als Dock)? */
export function istSichtbarOffen(q: Pick<LageQuelle, 'ap' | 'agent'>, id: string): boolean {
  if (id === AGENT && q.agent) return true;
  return q.ap.bildschirme.some((b) => b.fenster.some((w) => w.id === id && !w.min));
}

// ── Ein Wort wird zur Fläche ─────────────────────────────────────────────────────────────────

/** Vergleichsform: klein, ohne Umlaute und Akzente („Übersicht“ = „uebersicht“ = „ubersicht“). */
export function falte(s: string): string {
  return s
    .toLowerCase()
    .replace(/ß/g, 'ss')
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .replace(/ae/g, 'a')
    .replace(/oe/g, 'o')
    .replace(/ue/g, 'u')
    .replace(/\s+/g, ' ')
    .trim();
}

export type Aufloesung = { ok: true; id: string; flaeche: Flaeche } | { ok: false; fehler: string; kandidaten?: string[] };

const praeFix = /^(seite|app|nativ):/;

const nenne = (f: Flaeche): string => `${f.titel} (${f.id})`;

/**
 * Werkzeuge mit derselben Oberfläche sind EINE Fläche (`notizen__suche` gehört zur Notizen-App, deren Fläche
 * `app:notizen__liste` heißt). Wer ein Mitglied nennt — der Agent tut das nach jedem Aufruf —, meint diese Fläche.
 */
function mitgliedFlaeche(flaechen: Flaeche[], name: string): Flaeche | undefined {
  const werkzeug = name.replace(/^app:/, '');
  return flaechen.find((f) => f.art === 'hubapp' && f.mitglieder?.includes(werkzeug));
}

/**
 * `ziel` ist eine ID (`app:notizen__liste`, `seite:berichte`, `nativ:anruf`, `agent`), eine ID ohne
 * Vorsatz (`berichte`, `notizen__liste`) oder ein Titel („Berichte“, „Notizen“). Titel: exakt, dann Anfang,
 * dann Teilstück — gilt nur, wenn genau eine Fläche passt; sonst steht in der Antwort, was passt.
 */
export function loeseAuf(ziel: unknown, flaechen: Flaeche[]): Aufloesung {
  const roh = typeof ziel === 'string' ? ziel.trim() : '';
  if (!roh) return { ok: false, fehler: 'ziel fehlt: eine Fläche wie „seite:berichte“, „app:notizen__liste“ oder ein Name wie „Berichte“.' };

  const exakt = flaechen.find((f) => f.id === roh);
  if (exakt) return { ok: true, id: exakt.id, flaeche: exakt };

  const klein = roh.toLowerCase();
  if (praeFix.test(klein)) {
    const f = flaechen.find((x) => x.id === klein) ?? mitgliedFlaeche(flaechen, klein);
    if (f) return { ok: true, id: f.id, flaeche: f };
    const k = bekannte(flaechen, 8);
    return { ok: false, fehler: `Die Fläche „${roh}“ gibt es hier nicht (oder sie ist noch nicht geladen).${beispiele(k)}`, kandidaten: k };
  }
  for (const vorsatz of ['seite:', 'app:', 'nativ:']) {
    const f = flaechen.find((x) => x.id === vorsatz + klein);
    if (f) return { ok: true, id: f.id, flaeche: f };
  }
  const m = mitgliedFlaeche(flaechen, klein);
  if (m) return { ok: true, id: m.id, flaeche: m };

  const q = falte(roh);
  const stufen: ((f: Flaeche) => boolean)[] = [
    (f) => falte(f.titel) === q,
    (f) => falte(f.titel).startsWith(q),
    (f) => falte(f.titel).includes(q),
  ];
  for (const passt of stufen) {
    const treffer = flaechen.filter(passt);
    if (treffer.length === 1) return { ok: true, id: treffer[0]!.id, flaeche: treffer[0]! };
    if (treffer.length > 1) {
      const namen = treffer.slice(0, 6).map(nenne);
      return { ok: false, fehler: `„${roh}“ passt auf mehrere Flächen: ${namen.join(', ')}. Nimm die ID.`, kandidaten: namen };
    }
  }
  const k = bekannte(flaechen, 12);
  return { ok: false, fehler: `Keine Fläche passt zu „${roh}“.${beispiele(k)}`, kandidaten: k };
}

function bekannte(flaechen: Flaeche[], n: number): string[] {
  return flaechen.slice(0, n).map(nenne);
}

/** Was nach „gibt es nicht“ hilft: ein paar Flächen, die es gibt. */
const beispiele = (k: string[]): string => (k.length ? ` Es gibt zum Beispiel: ${k.join(', ')}.` : ' Es sind noch keine Flächen geladen.');

/** Wie `loeseAuf`, aber nur unter den offenen Fenstern (zum Schließen und Lesen). */
export function loeseFensterAuf(ziel: unknown, fenster: LageFenster[]): { ok: true; fenster: LageFenster } | { ok: false; fehler: string } {
  const roh = typeof ziel === 'string' ? ziel.trim() : '';
  if (!roh) return { ok: false, fehler: 'ziel fehlt: die ID oder der Name eines offenen Fensters.' };
  const stufen: ((w: LageFenster) => boolean)[] = [
    (w) => w.id === roh || w.id === roh.toLowerCase(),
    (w) => falte(w.titel) === falte(roh),
    (w) => falte(w.titel).startsWith(falte(roh)),
    (w) => falte(w.titel).includes(falte(roh)),
  ];
  for (const passt of stufen) {
    const treffer = fenster.filter(passt);
    if (treffer.length === 1) return { ok: true, fenster: treffer[0]! };
    if (treffer.length > 1) {
      return { ok: false, fehler: `„${roh}“ passt auf mehrere offene Fenster: ${treffer.map((w) => `${w.titel} (${w.id})`).join(', ')}. Nimm die ID.` };
    }
  }
  const offen = fenster.length ? fenster.map((w) => `${w.titel} (${w.id})`).join(', ') : 'keines';
  return { ok: false, fehler: `Kein offenes Fenster passt zu „${roh}“. Offen: ${offen}.` };
}
