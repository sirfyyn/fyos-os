/**
 * i18n — Sprache der Oberfläche (Englisch als Vorgabe, Deutsch wählbar).
 *
 * Schlüssel sind die deutschen Ausgangstexte (wie bei gettext): `t('Einstellungen')`. `en.ts` bildet sie auf
 * Englisch ab, `de.ts` trägt nur Abweichungen vom Schlüssel. Fehlt eine Übersetzung, erscheint der Schlüssel.
 * Platzhalter: `t('{0} schließen', titel)` oder `t('Noch {n}', { n: 3 })`.
 *
 * Reihenfolge der Wahl: Auswahl in den Einstellungen (localStorage `fyos.sprache`) > Laufzeit-Konfiguration
 * (`/fyos.config.json`, Feld `sprache` oder `language`) > Vorgabe `en`. `t()` liest ein Signal: Texte, die beim
 * Zeichnen übersetzt werden, folgen einem Wechsel sofort. Werte aus Datentabellen (Flächen-Titel, Räume …) bleiben
 * deutsch gespeichert und werden erst an der Anzeige übersetzt (`t(f.titel)`).
 */
import { createSignal } from 'solid-js';
import { de } from './de';
import { en } from './en';

export type Sprache = 'en' | 'de';
export const SPRACHEN: readonly Sprache[] = ['en', 'de'];
export const SPRACHE_NAMEN: Record<Sprache, string> = { en: 'English', de: 'Deutsch' };
export const VORGABE_SPRACHE: Sprache = 'en';
const SPEICHER = 'fyos.sprache';

const TABELLEN: Record<Sprache, Record<string, string>> = { en, de };

export function istSprache(x: unknown): x is Sprache {
  return typeof x === 'string' && (SPRACHEN as readonly string[]).includes(x);
}

/** Wandelt `de`, `de-DE`, `German`, `deutsch`, `EN` … in eine bekannte Sprache, sonst undefined. */
export function spracheAus(x: unknown): Sprache | undefined {
  if (typeof x !== 'string') return undefined;
  const s = x.trim().toLowerCase();
  if (s.startsWith('de') || s === 'german') return 'de';
  if (s.startsWith('en')) return 'en';
  return undefined;
}

function gemerkt(): Sprache | undefined {
  try {
    return spracheAus(globalThis.localStorage?.getItem(SPEICHER));
  } catch {
    return undefined;
  }
}

const [gewaehlt, setGewaehlt] = createSignal<Sprache | undefined>(gemerkt());
const [konfiguriert, setKonfiguriert] = createSignal<Sprache | undefined>(undefined);
const [fest, setFest] = createSignal<Sprache | undefined>(undefined);

/** Die aktive Sprache. */
export const sprache = (): Sprache => fest() ?? gewaehlt() ?? konfiguriert() ?? VORGABE_SPRACHE;

/** BCP-47-Kennung für Intl und `lang`. */
export const gebietsschema = (): string => (sprache() === 'de' ? 'de-DE' : 'en-US');

function langSetzen(): void {
  try {
    if (typeof document !== 'undefined') document.documentElement.lang = sprache();
  } catch {
    /* ohne DOM */
  }
}

/** Auswahl in den Einstellungen; undefined nimmt die Auswahl zurück (dann gilt die Konfiguration). */
export function spracheWaehlen(s: Sprache | undefined): void {
  setGewaehlt(s);
  langSetzen();
  try {
    if (s) globalThis.localStorage?.setItem(SPEICHER, s);
    else globalThis.localStorage?.removeItem(SPEICHER);
  } catch {
    /* privates Fenster: nur für diese Sitzung */
  }
}

/** Die Sprache, die nicht aus der Auswahl kommt (Konfiguration oder Vorgabe). */
export const spracheOhneWahl = (): Sprache => konfiguriert() ?? VORGABE_SPRACHE;

/** Aus der Laufzeit-Konfiguration (config.ts). */
export function spracheKonfigurieren(x: unknown): void {
  setKonfiguriert(spracheAus(x));
  langSetzen();
}

/** Nur für Tests: feste Sprache über allem (undefined hebt sie auf). */
export function spracheFestlegen(s: Sprache | undefined): void {
  setFest(s);
}

/** Nur für Tests: Auswahl und Konfiguration vergessen. */
export function spracheZuruecksetzen(): void {
  setGewaehlt(undefined);
  setKonfiguriert(undefined);
  try {
    globalThis.localStorage?.removeItem(SPEICHER);
  } catch {
    /* egal */
  }
}

type Werte = Record<string, unknown>;

function einsetzen(text: string, args: unknown[]): string {
  if (!args.length) return text;
  const benannt = args.length === 1 && args[0] !== null && typeof args[0] === 'object' ? (args[0] as Werte) : undefined;
  return text.replace(/\{(\w+)\}/g, (ganz, k: string) => {
    const v = benannt ? benannt[k] : /^\d+$/.test(k) ? args[Number(k)] : undefined;
    return v === undefined ? ganz : String(v);
  });
}

/** Übersetzt den deutschen Ausgangstext `schluessel` in die aktive Sprache (in Komponenten als `tr` importiert,
 *  weil `t` dort oft eine lokale Variable ist). */
export function tr(schluessel: string, ...args: unknown[]): string {
  const s = sprache();
  const text = TABELLEN[s][schluessel] ?? schluessel;
  return einsetzen(text, args);
}

/** Übersetzt in eine bestimmte Sprache (z. B. für Tests oder Vorschau). */
export function tIn(s: Sprache, schluessel: string, ...args: unknown[]): string {
  return einsetzen(TABELLEN[s][schluessel] ?? schluessel, args);
}

/** Einzahl/Mehrzahl: `tn(n, '{n} Fläche', '{n} Flächen')`. */
export function tn(n: number, eins: string, mehr: string): string {
  return tr(n === 1 ? eins : mehr, { n });
}

/** Kurzname. */
export const t = tr;

/** Datum/Uhrzeit nach Sprache. */
export function datumFormat(d: Date | number | string, opt: Intl.DateTimeFormatOptions = {}): string {
  const x = d instanceof Date ? d : new Date(d);
  if (Number.isNaN(x.getTime())) return '';
  return new Intl.DateTimeFormat(gebietsschema(), opt).format(x);
}

/** Zahl nach Sprache. */
export function zahlFormat(n: number, opt: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(gebietsschema(), opt).format(n);
}
