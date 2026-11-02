/**
 * modi.ts — Ruhe, Normal, Bereit im Browser (OS-Neubau P4).
 *
 * Der Modus gehört dem Hub (`modus.zustand`, `modus.setzen`, Plugin fyos-plugin-modus); hier stehen das Signal `modus()`,
 * `setzeModus()` und was das Gerät selbst schaltet, wenn der Modus wechselt:
 *   - Ton je Gerät (ton-modus.ts): Ruhe stumm, Normal zurückhaltend, Bereit interaktiv — nur beim WECHSEL, damit deine eigene
 *     Wahl am Gerät zwischen zwei Wechseln stehen bleibt
 *   - Meldungsdienst (meldungen.ts): liest `modus()` und `meldebudget()` selbst
 *   - Bildschirm: nur am Gerät, an dem umgeschaltet wurde (Ruhe → HomeTwin, Bereit → Bereit-Seite)
 * Jeder Wechsel geht als `fyos:modus` an `window` (`detail: {modus, vorher, zustand, hier}`).
 *
 * Wechsel an einem anderen Gerät oder per Stimme kommen über die Abfrage (alle 60 s, beim Zurückkehren in den Tab sofort).
 */
import { createSignal } from 'solid-js';
import { hub } from '~/lib/hub';
import { imOsOeffnen } from './oeffnen';
import { TON_MODI, tonModusLesen, tonModusSchreiben, type TonModus } from './ton-modus';

export type Modus = 'ruhe' | 'normal' | 'bereit';
export const MODI: readonly Modus[] = ['ruhe', 'normal', 'bereit'];
export const MODUS_NAME: Record<Modus, string> = { ruhe: 'Ruhe', normal: 'Normal', bereit: 'Bereit' };
export const MODUS_EREIGNIS = 'fyos:modus';
export const MELDEBUDGET_VORGABE = 5;
/** Merkt sich je Gerät, welcher Wechsel (Modus + seit) hier schon angewendet ist. */
export const ANGEWENDET_SCHLUESSEL = 'fyos:os:modus-angewendet';
export const ABFRAGE_MS = 60_000;

export interface Geschaltet {
  id: string;
  titel: string;
  zustand: 'an' | 'aus' | 'schatten' | 'browser' | 'uebersprungen' | 'fehler' | 'nicht_eingerichtet';
  satz?: string;
  wert?: unknown;
  ms?: number;
}

export interface ModusZustand {
  modus: Modus;
  seit: string | null;
  geschaltet: Geschaltet[];
  gewaehlt?: Modus;
  automatisch?: boolean;
  grund?: string | null;
  meldebudget?: number;
  browser?: { meldungen?: string | null; ton?: string | null; bildschirm?: string | null };
  satz?: string;
  dauer_ms?: number;
  lagebild?: string;
}

export interface ModusEreignis {
  modus: Modus;
  vorher: Modus;
  zustand: ModusZustand;
  /** An diesem Gerät umgeschaltet (sonst: von woanders erfahren) */
  hier: boolean;
}

const istModus = (x: unknown): x is Modus => typeof x === 'string' && (MODI as readonly string[]).includes(x);

/** Antwort des Hubs prüfen; Unbrauchbares ergibt null. */
export function zustandLesen(roh: unknown): ModusZustand | null {
  if (!roh || typeof roh !== 'object') return null;
  const r = roh as Record<string, unknown>;
  if (!istModus(r.modus)) return null;
  return {
    ...(r as unknown as ModusZustand),
    seit: typeof r.seit === 'string' ? r.seit : null,
    geschaltet: Array.isArray(r.geschaltet) ? (r.geschaltet as Geschaltet[]) : [],
  };
}

const [zustand, setzeZustand] = createSignal<ModusZustand | null>(null);
/** Der volle Zustand (null, solange der Hub nicht geantwortet hat). */
export const modusZustand = zustand;
/** Der wirksame Modus; unbekannt gilt als Normal. */
export const modus = (): Modus => zustand()?.modus ?? 'normal';
export const meldebudget = (): number => zustand()?.meldebudget ?? MELDEBUDGET_VORGABE;
const [schaltet, setzeSchaltet] = createSignal<Modus | null>(null);
/** Ein Wechsel läuft gerade (der Zielmodus), sonst null */
export const modusSchaltet = schaltet;

export interface Abh {
  hub: <T>(werkzeug: string, args: Record<string, unknown>) => Promise<T>;
  speicher: Pick<Storage, 'getItem' | 'setItem'> | null;
  ton: (t: TonModus) => void;
  tonLesen: () => TonModus | null;
  oeffne: (ziel: string) => boolean;
  ereignis: (e: ModusEreignis) => void;
  jetzt: () => number;
}

const standardSpeicher = (): Storage | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
};

const echt: Abh = {
  hub: (w, a) => hub(w, a, { art: w === 'modus.setzen' ? 'bewusst' : 'abfrage', zeitMs: 15_000 }),
  speicher: standardSpeicher(),
  ton: (t) => tonModusSchreiben(t),
  tonLesen: () => tonModusLesen(),
  oeffne: (ziel) => imOsOeffnen({ ziel, vorn: true }),
  ereignis: (e) => {
    try {
      window.dispatchEvent(new CustomEvent(MODUS_EREIGNIS, { detail: e }));
    } catch {
      /* ohne window (Tests, Server) */
    }
  },
  jetzt: () => Date.now(),
};

/** Ton je Modus, wie die Vorgabe im Plugin (wirkungen.py); der Hub kann ihn abwählen (`browser.ton: null`). */
export const SOFORT_TON: Record<Modus, TonModus> = { ruhe: 'stumm', normal: 'zurueckhaltend', bereit: 'interaktiv' };

const marke = (z: ModusZustand): string => `${z.modus}|${z.seit ?? ''}`;

/**
 * Einen Zustand am Gerät anwenden. Der Ton wechselt nur, wenn dieser Wechsel hier noch nicht angewendet ist; der Bildschirm nur
 * mit `hier`. Liefert, ob sich der Modus gegenüber dem bisherigen Signal geändert hat.
 */
export function anwenden(z: ModusZustand, hier: boolean, abh: Abh = echt): boolean {
  const vorher = zustand()?.modus ?? null;
  setzeZustand(z);
  let gemerkt: string | null = null;
  try {
    gemerkt = abh.speicher?.getItem(ANGEWENDET_SCHLUESSEL) ?? null;
  } catch {
    gemerkt = null;
  }
  // Ohne Merker (erstes Laden an diesem Gerät) nur merken, nichts umstellen: deine Ton bleibt
  if (hier || (gemerkt !== null && gemerkt !== marke(z))) {
    const ton = z.browser?.ton;
    if (typeof ton === 'string' && (TON_MODI as readonly string[]).includes(ton)) abh.ton(ton as TonModus);
  }
  try {
    abh.speicher?.setItem(ANGEWENDET_SCHLUESSEL, marke(z));
  } catch {
    /* gilt dann bis zum Neuladen */
  }
  if (hier) {
    const ziel = z.browser?.bildschirm;
    if (typeof ziel === 'string' && ziel.startsWith('nativ:')) abh.oeffne(ziel);
  }
  if (vorher !== z.modus || hier) abh.ereignis({ modus: z.modus, vorher: vorher ?? 'normal', zustand: z, hier });
  return vorher !== z.modus;
}

/** Zustand vom Hub holen und anwenden. Fehler lassen den letzten Stand stehen. */
export async function modusLesen(abh: Abh = echt): Promise<ModusZustand | null> {
  try {
    const z = zustandLesen(await abh.hub<unknown>('modus.zustand', {}));
    if (z) anwenden(z, false, abh);
    return z;
  } catch {
    return zustand();
  }
}

/**
 * Den Modus setzen. Der Ton stellt sich sofort um (bevor der Hub antwortet), der Rest nach der Antwort. Wirft, wenn der Hub ablehnt;
 * dann gilt wieder der vorige Zustand.
 */
export async function setzeModus(m: Modus, opt: { von?: string; grund?: string } = {}, abh: Abh = echt): Promise<ModusZustand> {
  setzeSchaltet(m);
  const t0 = abh.jetzt();
  const tonVorher = abh.tonLesen();
  try {
    // Sofort hörbar: der Ton stellt sich vor der Antwort um; ist die Wirkung abgewählt, kommt er danach zurück
    abh.ton(SOFORT_TON[m]);
    const roh = await abh.hub<unknown>('modus.setzen', { modus: m, von: opt.von ?? 'max', ...(opt.grund ? { grund: opt.grund } : {}) });
    const z = zustandLesen(roh);
    if (!z) throw new Error('modus.setzen: unbrauchbare Antwort');
    z.dauer_ms = z.dauer_ms ?? abh.jetzt() - t0;
    if (!z.browser?.ton && tonVorher) abh.ton(tonVorher);
    anwenden(z, true, abh);
    return z;
  } catch (e) {
    if (tonVorher) abh.ton(tonVorher);
    throw e;
  } finally {
    setzeSchaltet(null);
  }
}

/** Startet die Abfrage (sofort, alle 60 s, beim Zurückkehren in den Tab). Rückgabe beendet sie. */
export function modiStarten(abh: Abh = echt): () => void {
  void modusLesen(abh);
  const takt = setInterval(() => void modusLesen(abh), ABFRAGE_MS);
  const sicht = () => {
    if (document.visibilityState === 'visible') void modusLesen(abh);
  };
  document.addEventListener('visibilitychange', sicht);
  return () => {
    clearInterval(takt);
    document.removeEventListener('visibilitychange', sicht);
  };
}

/** Sätze für ⌘K, Stimme und die Kachel: „Ruhe“, „Ich bin da“. */
export const MODUS_GRIFF: Record<Modus, { titel: string; woerter: string[] }> = {
  ruhe: { titel: 'Ruhe', woerter: ['ruhe', 'ruhig', 'still', 'nicht stoeren', 'feierabend', 'modus'] },
  normal: { titel: 'Normal', woerter: ['normal', 'modus', 'alltag'] },
  bereit: { titel: 'Ich bin da', woerter: ['bereit', 'ich bin da', 'da', 'arbeiten', 'los', 'modus', 'fokus'] },
};

/** Nur für Tests: Signal zurücksetzen. */
export function _zuruecksetzen(): void {
  setzeZustand(null);
  setzeSchaltet(null);
}
