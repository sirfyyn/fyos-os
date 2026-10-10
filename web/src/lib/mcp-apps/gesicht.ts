/**
 * gesicht.ts — das Gesicht einer Hub-App: Titel, Untertitel, Symbol, Farbe, Kategorie.
 *
 * Der Hub liefert je App `titel`, `untertitel`, `symbol`,
 * `ton`, `kategorie` und `icon` (GET /hub/apps, dazu `_meta.app` am Werkzeug). Solange er das nicht
 * tut, leiten wir das Gesicht aus dem ab, was da ist: Name des Werkzeugs, erster Satz der Beschreibung
 * (ohne „(App):", Backticks und Klammerreste), Symbol und Farbe aus lib/os/symbole.ts. Katalog, Start,
 * Dock und Fensterkopf fragen immer hier — so sieht eine App überall gleich aus.
 *
 * Reine Funktionen ohne DOM; nur `gesichterMerken` schreibt (die Symbole, damit auch Dock und Start
 * die Glyphe und Farbe des Hubs übernehmen).
 */
import type { McpApp } from './host';
import { farbton, glyphe, symboleSetzen, type SymbolUeberschrieb } from '~/lib/os/symbole';
import { SYMBOLE } from '~/lib/os/symbole-daten';

export interface AppGesicht {
  titel: string;
  /** Eine Zeile: was man damit tut. */
  untertitel: string;
  /** Name einer Glyphe aus symbole-daten.ts */
  symbol: string;
  /** Farbton 0–359 (HSL, wie in lib/os/symbole.ts) */
  ton: number;
  kategorie: string;
  /** Fertiges SVG-Bild des Hubs (data:image/svg+xml), falls wir die Glyphe selbst nicht kennen */
  icon?: string;
  /** true = Felder vom Hub; false = aus Name und Beschreibung abgeleitet */
  vomHub: boolean;
}

/** Reihenfolge der Kategorien im Katalog; Unbekanntes kommt danach, „Weitere“ zuletzt. */
export const KATEGORIEN = ['Zuhause', 'System', 'Betrieb', 'Wissen', 'Messen'] as const;
export const KATEGORIE_REST = 'Weitere';

export const kategorieRang = (k: string): number => {
  const i = (KATEGORIEN as readonly string[]).indexOf(k);
  if (i >= 0) return i;
  return k === KATEGORIE_REST ? 1000 : 100;
};


// ── Felder vom Hub ──────────────────────────────────────────────────────────────────────────────

interface HubFelder {
  titel?: unknown;
  untertitel?: unknown;
  symbol?: unknown;
  ton?: unknown;
  kategorie?: unknown;
  icon?: unknown;
}

/** Oberste Ebene (GET /hub/apps) hat Vorrang, sonst `_meta.app` des Werkzeugs. */
function hubFelder(app: McpApp): HubFelder {
  const oben = app as unknown as HubFelder;
  const meta = ((app._meta as unknown as { app?: HubFelder } | undefined)?.app ?? {}) as HubFelder;
  return {
    titel: oben.titel ?? meta.titel,
    untertitel: oben.untertitel ?? meta.untertitel,
    symbol: oben.symbol ?? meta.symbol,
    ton: oben.ton ?? meta.ton,
    kategorie: oben.kategorie ?? meta.kategorie,
    icon: oben.icon ?? meta.icon,
  };
}

const text = (x: unknown, max = 200): string | undefined => {
  if (typeof x !== 'string') return undefined;
  const t = x.replace(/\s+/g, ' ').trim();
  return t && t.length <= max ? t : undefined;
};
const tonZahl = (x: unknown): number | undefined =>
  typeof x === 'number' && Number.isFinite(x) ? ((Math.round(x) % 360) + 360) % 360 : undefined;
/** Nur ein SVG als data:-Adresse und nicht riesig; als <img> gezeigt, führt es keine Skripte aus. */
const bildAdresse = (x: unknown): string | undefined =>
  typeof x === 'string' && x.length <= 40_000 && /^data:image\/svg\+xml[;,]/i.test(x) ? x : undefined;

// ── Untertitel aus der Beschreibung ─────────────────────────────────────────────────────────────

const KUERZEL = ['z. B.', 'z.B.', 'd. h.', 'u. a.', 'u. U.', 'ggf.', 'bzw.', 'ca.', 'inkl.', 'evtl.', 'usw.', 'etc.', 'vgl.', 'Nr.', 'ggü.'];
const PUNKT = '∙'; // Platzhalter für Punkte in Kürzeln, damit sie keinen Satz beenden

/**
 * Erster Satz einer Werkzeug-Beschreibung als Untertitel: ohne „(App):", Backticks und Klammerreste,
 * höchstens `max` Zeichen, an einer Wortgrenze gekürzt. Leer, wenn nichts Brauchbares übrig bleibt.
 */
export function untertitelAus(roh: string | null | undefined, max = 72): string {
  let t = String(roh ?? '').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  // „Kalender (App): Termine …" → „Termine …"; „(App) Das nächste …"; „Zeigt (App) die …"
  t = t.replace(/^[^:.]{0,80}\(App\)\s*:\s*/i, '');
  t = t.replace(/\s*\(App\)\s*:?\s*/gi, ' ');
  // Code-Schreibweise: die Wörter bleiben, die Backticks gehen
  t = t.replace(/`/g, '');
  // Klammern samt Inhalt (von innen nach außen), auch halbe am Ende des gekürzten Texts
  for (let i = 0; i < 4 && /\([^()]*\)/.test(t); i++) t = t.replace(/\s*\([^()]*\)/g, '');
  t = t.replace(/\s*\([^)]*$/, '');
  t = t.replace(/\s+([,.;:!?])/g, '$1').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  // Erster Satz (Kürzel wie „z. B." beenden keinen)
  for (const k of KUERZEL) t = t.split(k).join(k.replace(/\./g, PUNKT));
  const satz = /[.!?](?=\s+[A-ZÄÖÜ„"(]|$)/.exec(t);
  if (satz) t = t.slice(0, satz.index + 1);
  t = t.split(PUNKT).join('.');
  // Gedankenstrich und Semikolon trennen Nebensächliches ab, wenn davor schon genug steht
  for (const trenner of [' — ', ' – ', '; ']) {
    const i = t.indexOf(trenner);
    if (i >= 12) t = t.slice(0, i);
  }
  t = t.replace(/[\s.,;:\-–—]+$/, '');
  if (t.length > max) {
    const schnitt = t.lastIndexOf(' ', max - 1);
    t = `${t.slice(0, schnitt > max * 0.55 ? schnitt : max - 1).replace(/[\s.,;:\-–—]+$/, '')}…`;
  }
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** „braucht_dich" → „Braucht dich" (letzter Rückfall, wenn ein Werkzeug gar keinen Titel hat). */
const lesbar = (name: string): string => {
  const w = (name.split('__')[1] ?? name).replace(/_/g, ' ').trim();
  return w.charAt(0).toUpperCase() + w.slice(1);
};

/** „Werkstatt — ausführen" → „Werkstatt" (mehrere Werkzeuge mit derselben Oberfläche tragen den App-Namen vorn). */
export const titelKopf = (t: string): string => (t.split(' — ')[0] ?? t).trim();

export function kategorieFuer(app: McpApp): string {
  return text(hubFelder(app).kategorie, 40) ?? KATEGORIE_REST;
}

/**
 * Das Gesicht einer App. `gruppe`: das Werkzeug gehört zu mehreren mit derselben Oberfläche (dann steht
 * vor „ — " der Name der App). `info`: fester Untertitel für bekannte Oberflächen, wenn der Hub keinen liefert.
 */
export function gesichtVon(app: McpApp, opt: { gruppe?: boolean; info?: string } = {}): AppGesicht {
  const h = hubFelder(app);
  const eigenerTitel = (app.title ?? '').trim();
  const titel = text(h.titel, 80) ?? (eigenerTitel ? (opt.gruppe ? titelKopf(eigenerTitel) : eigenerTitel) : lesbar(app.name));
  const hubUntertitel = text(h.untertitel, 160);
  const id = `app:${app.name}`;
  const hubSymbol = typeof h.symbol === 'string' && SYMBOLE[h.symbol] ? h.symbol : undefined;
  const hubTon = tonZahl(h.ton);
  const icon = hubSymbol ? undefined : bildAdresse(h.icon);
  return {
    titel,
    untertitel: hubUntertitel ?? opt.info ?? untertitelAus(app.description),
    symbol: hubSymbol ?? glyphe(id),
    ton: hubTon ?? farbton(id),
    kategorie: kategorieFuer(app),
    icon,
    vomHub: !!(text(h.titel, 80) && hubUntertitel && (hubSymbol || icon) && hubTon !== undefined),
  };
}

/**
 * Symbol und Farbe, die der Hub mitliefert, für alle Flächen übernehmen (Dock, Start, Fensterkopf,
 * Katalog lesen sie über lib/os/symbole.ts). Ohne Felder vom Hub bleibt alles bei der Tabelle.
 */
export function gesichterMerken(liste: McpApp[]): void {
  const neu: Record<string, SymbolUeberschrieb> = {};
  for (const a of liste) {
    if (!a?._meta?.ui) continue;
    const h = hubFelder(a);
    const g = typeof h.symbol === 'string' && SYMBOLE[h.symbol] ? h.symbol : undefined;
    const ton = tonZahl(h.ton);
    const icon = g ? undefined : bildAdresse(h.icon);
    if (!g && ton === undefined && !icon) continue;
    neu[`app:${a.name}`] = { glyphe: g, ton, icon };
  }
  if (Object.keys(neu).length) symboleSetzen(neu);
}
