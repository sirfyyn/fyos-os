/**
 * bruecke.ts — die Shell als Sitzung der OS-Brücke (Protokoll v1, docs/HUB-VERTRAG.md).
 *
 * Damit weiß der Hub, dass jemand vor der Shell sitzt, und der Agent erreicht ihn mit `os.mitteilen`:
 * Die Shell meldet sich (`POST /hub-api/os/melden`), sagt, ob der Tab sichtbar ist und wann zuletzt etwas getan
 * wurde, und bekommt in derselben Antwort ihre Mitteilungen (`abholen: true`, ohne Eventstrom). Was ein Agent
 * nachts vorgemerkt hat, kommt mit der ersten Meldung nach dem Öffnen der Shell — mit `nachgeholt` und `entstanden`.
 *
 * Diese Sitzung zeigt nur Mitteilungen („Agent zeigt dir …“); sie antwortet nicht auf `zeigen`/`ausfuehren`, der
 * Hub wählt sie dafür nicht. Jede Mitteilung wird als Fensterereignis `fyos:zeigt` weitergegeben (lib/os/mitteilungen.ts).
 *
 * Alles hier ist still: ein Hub, der fehlt oder nicht antwortet, stört die Shell nicht.
 */
import { ZEIGT_EREIGNIS } from './mitteilungen';

export const MELDEN_URL = '/hub-api/os/melden';
export const SITZUNG_SCHLUESSEL = 'fyos:os:sitzung';
/** Im sichtbaren Tab so oft melden (die Mitteilung kommt in der Antwort). */
export const TAKT_SICHTBAR_MS = 5_000;
/** Im verdeckten Tab selten; dort sitzt niemand davor, die Sitzung soll nur nicht ablaufen (Hub: 90 s). */
export const TAKT_VERDECKT_MS = 30_000;
/** Nach einem Fehler langsamer weiter. */
export const TAKT_FEHLER_MS = 30_000;

export interface BrueckeEinstellung {
  /** Der Browser: `fetch` mit gleichem Ursprung */
  holen?: typeof fetch;
  /** Wohin Mitteilungen gehen (Vorgabe: Fensterereignis `fyos:zeigt`) */
  zeigt?: (daten: Record<string, unknown>) => void;
  jetzt?: () => number;
  speicher?: Pick<Storage, 'getItem' | 'setItem'> | null;
  /** Schmales Gerät oder Handy statt Computer */
  art?: 'computer' | 'telefon' | 'tablet';
  geraet?: string;
}

const zufall = (): string => {
  const c = globalThis.crypto;
  if (c?.getRandomValues) {
    return [...c.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  return Math.random().toString(16).slice(2, 18).padEnd(16, '0');
};

const sessionSpeicher = (): Storage | null => {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage;
  } catch {
    return null; // gesperrt: dann hat jedes Neuladen eine neue Sitzung, das ist in Ordnung
  }
};

/** Die Sitzungs-ID dieses Tabs: bleibt beim Neuladen, ein neuer Tab bekommt eine neue. */
export function sitzungsId(speicher: Pick<Storage, 'getItem' | 'setItem'> | null = sessionSpeicher()): string {
  try {
    const alt = speicher?.getItem(SITZUNG_SCHLUESSEL);
    if (alt && /^[A-Za-z0-9_-]{6,64}$/.test(alt)) return alt;
  } catch {
    /* gesperrt */
  }
  const neu = `s-${zufall()}`;
  try {
    speicher?.setItem(SITZUNG_SCHLUESSEL, neu);
  } catch {
    /* gesperrt */
  }
  return neu;
}

/** Aus der Antwort des Hubs die Mitteilungen (Befehle der Art `zeigt`), jede nur einmal. */
export function mitteilungenAus(antwort: unknown, gesehen: Set<string>): Record<string, unknown>[] {
  const befehle = (antwort as { befehle?: unknown } | null)?.befehle;
  if (!Array.isArray(befehle)) return [];
  const aus: Record<string, unknown>[] = [];
  for (const b of befehle) {
    if (!b || typeof b !== 'object') continue;
    const { id, art, zeigt } = b as { id?: unknown; art?: unknown; zeigt?: unknown };
    if (art !== 'zeigt' || !zeigt || typeof zeigt !== 'object') continue;
    if (typeof id === 'string') {
      if (gesehen.has(id)) continue;
      gesehen.add(id);
      if (gesehen.size > 200) gesehen.delete(gesehen.values().next().value as string);
    }
    aus.push(zeigt as Record<string, unknown>);
  }
  return aus;
}

/**
 * Die Brücke starten. Gibt eine Funktion zurück, die sie beendet (meldet den Abschied).
 * Ohne `fetch` oder ohne Fenster tut sie nichts.
 */
export function brueckeStarten(einst: BrueckeEinstellung = {}): () => void {
  const holen = einst.holen ?? (typeof fetch === 'function' ? fetch.bind(globalThis) : undefined);
  if (!holen || typeof window === 'undefined') return () => {};
  const jetzt = einst.jetzt ?? Date.now;
  const zeigt = einst.zeigt ?? ((d) => window.dispatchEvent(new CustomEvent(ZEIGT_EREIGNIS, { detail: d })));
  const sitzung = sitzungsId(einst.speicher === undefined ? sessionSpeicher() : einst.speicher);
  const gesehen = new Set<string>();
  let nach: string | null = null;
  let zuletzt = jetzt();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let aus = false;
  let laeuft = false;

  const sichtbar = () => typeof document === 'undefined' || document.visibilityState !== 'hidden';
  const aktivitaet = () => {
    zuletzt = jetzt();
  };

  const meldung = () => ({
    sitzung,
    geraet: einst.geraet ?? 'Browser',
    art: einst.art ?? 'computer',
    seite: typeof location === 'undefined' ? '' : location.pathname,
    sichtbar: sichtbar(),
    aktiv_vor_s: Math.max(0, Math.round((jetzt() - zuletzt) / 1000)),
    // Die Shell spielt keinen Ton: so legt der Hub keinen Hinweiston und keine Stimme in die Mitteilung.
    audio: { modus: 'stumm', kopfhoerer: false },
    abholen: true,
    nach,
    version: 1,
    gesendet: jetzt(),
  });

  const melden = async (): Promise<boolean> => {
    if (laeuft || aus) return true;
    laeuft = true;
    try {
      const r = await holen(MELDEN_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(meldung()),
        credentials: 'same-origin',
      });
      if (!r.ok) return false;
      const antwort = (await r.json()) as { nach?: unknown };
      if (typeof antwort.nach === 'string') nach = antwort.nach;
      for (const z of mitteilungenAus(antwort, gesehen)) zeigt(z);
      return true;
    } catch {
      return false; // Hub weg, Anmeldung abgelaufen, kein JSON: die Shell läuft allein weiter
    } finally {
      laeuft = false;
    }
  };

  const takt = async () => {
    const gut = await melden();
    if (aus) return;
    timer = setTimeout(() => void takt(), !gut ? TAKT_FEHLER_MS : sichtbar() ? TAKT_SICHTBAR_MS : TAKT_VERDECKT_MS);
  };

  const sichtbarkeit = () => {
    if (aus || !sichtbar()) return;
    // Wieder da: sofort melden, damit Vorgemerktes gleich erscheint.
    clearTimeout(timer);
    void takt();
  };

  const abschied = () => {
    try {
      navigator.sendBeacon?.(MELDEN_URL, new Blob([JSON.stringify({ sitzung, ende: true, gesendet: jetzt() })], { type: 'application/json' }));
    } catch {
      /* Die Sitzung läuft nach 90 s von selbst ab. */
    }
  };

  const ereignisse = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'pointermove'] as const;
  for (const e of ereignisse) window.addEventListener(e, aktivitaet, { passive: true });
  document.addEventListener('visibilitychange', sichtbarkeit);
  window.addEventListener('pagehide', abschied);
  void takt();

  return () => {
    aus = true;
    clearTimeout(timer);
    for (const e of ereignisse) window.removeEventListener(e, aktivitaet);
    document.removeEventListener('visibilitychange', sichtbarkeit);
    window.removeEventListener('pagehide', abschied);
    abschied();
  };
}
