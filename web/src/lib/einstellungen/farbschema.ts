/**
 * farbschema.ts — Hell, Dunkel oder System.
 *
 * EINE Stelle für das Farbschema. Die Einstellungen, die Schnellregler, der Theme-Knopf
 * (ThemeDock) und die alte Darstellung im Overlay lesen und schreiben hierüber. Gespeichert wird
 * im Browser, in denselben Schlüsseln wie bisher:
 *
 *   fyos-theme       'light' | 'dark' — liest das Inline-Skript in BaseLayout vor dem ersten Bild
 *   fyos-theme-mode  'manual:light' | 'manual:dark' | 'system'
 *                    (früher auch 'auto' nach Uhrzeit; das setzt nichts mehr, es gilt dann fyos-theme)
 *
 * „System" folgt dem Gerät (prefers-color-scheme). BaseLayout löst es vor dem ersten Bild auf und
 * zieht bei einem Wechsel des Geräts nach; `fyos-theme` hält dabei den zuletzt aufgelösten Wert für
 * Leser, die „System" nicht kennen. Dieses Dokument erfährt Änderungen über `fyos:farbschema`,
 * andere Fenster (Tabs, eingebettete Seiten) über das `storage`-Ereignis.
 */

export type Farbschema = 'hell' | 'dunkel' | 'system';
export type Aufgeloest = 'light' | 'dark';

export const FARBSCHEMATA: readonly Farbschema[] = ['hell', 'dunkel', 'system'];
export const THEME_SCHLUESSEL = 'fyos-theme';
export const THEME_MODUS_SCHLUESSEL = 'fyos-theme-mode';
export const FARBSCHEMA_EREIGNIS = 'fyos:farbschema';
/** Ohne gespeicherte Wahl: dunkel (BaseLayout rendert data-theme="dark"). */
export const FARBSCHEMA_STANDARD: Farbschema = 'dunkel';

const GERAET_HELL = '(prefers-color-scheme: light)';

function lesen(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}

/** Die Wahl aus beiden Schlüsseln (Zusammenführung der Altstände). „system" im Modus gewinnt. */
export function farbschemaAus(theme: string | null, modus: string | null): Farbschema {
  if (modus === 'system') return 'system';
  if (theme === 'light') return 'hell';
  if (theme === 'dark') return 'dunkel';
  if (modus === 'manual:light') return 'hell';
  if (modus === 'manual:dark') return 'dunkel';
  return FARBSCHEMA_STANDARD;
}

export function farbschemaLaden(): Farbschema {
  return farbschemaAus(lesen(THEME_SCHLUESSEL), lesen(THEME_MODUS_SCHLUESSEL));
}

/** Ist das Gerät gerade hell eingestellt? Ohne matchMedia: nein. */
export function geraetHell(): boolean {
  try {
    return typeof matchMedia === 'function' && matchMedia(GERAET_HELL).matches;
  } catch {
    return false;
  }
}

export function aufloesen(s: Farbschema, hell: boolean = geraetHell()): Aufgeloest {
  if (s === 'hell') return 'light';
  if (s === 'dunkel') return 'dark';
  return hell ? 'light' : 'dark';
}

/** Setzt `data-theme` nach der gespeicherten (oder übergebenen) Wahl. */
export function farbschemaAnwenden(s: Farbschema = farbschemaLaden()): Aufgeloest {
  const a = aufloesen(s);
  if (typeof document !== 'undefined') document.documentElement.dataset.theme = a;
  return a;
}

/** Wählt, speichert, wendet an und meldet. Wirkt sofort, auch in offenen Fenstern (storage). */
export function farbschemaSetzen(s: Farbschema): Aufgeloest {
  const a = aufloesen(s);
  try {
    localStorage.setItem(THEME_MODUS_SCHLUESSEL, s === 'system' ? 'system' : s === 'hell' ? 'manual:light' : 'manual:dark');
    localStorage.setItem(THEME_SCHLUESSEL, a);
  } catch {
    /* Speicher gesperrt (privater Modus): gilt bis zum Neuladen */
  }
  farbschemaAnwenden(s);
  window.dispatchEvent(new CustomEvent(FARBSCHEMA_EREIGNIS, { detail: { wahl: s, aufgeloest: a } }));
  return a;
}

/**
 * Hört auf Änderungen: eigenes Ereignis, andere Fenster (storage) und — bei „System" — das Gerät.
 * Hält dabei `data-theme` aktuell. Gibt die Abmeldung zurück.
 */
export function hoereFarbschema(f: (wahl: Farbschema, aufgeloest: Aufgeloest) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const melden = () => {
    const w = farbschemaLaden();
    f(w, aufloesen(w));
  };
  const speicher = (e: StorageEvent) => {
    if (e.key !== null && e.key !== THEME_SCHLUESSEL && e.key !== THEME_MODUS_SCHLUESSEL) return;
    farbschemaAnwenden();
    melden();
  };
  const geraet = () => {
    if (farbschemaLaden() !== 'system') return;
    farbschemaAnwenden('system');
    melden();
  };
  window.addEventListener(FARBSCHEMA_EREIGNIS, melden);
  window.addEventListener('storage', speicher);
  let mq: MediaQueryList | null = null;
  try {
    mq = typeof matchMedia === 'function' ? matchMedia(GERAET_HELL) : null;
    mq?.addEventListener?.('change', geraet);
  } catch {
    mq = null;
  }
  return () => {
    window.removeEventListener(FARBSCHEMA_EREIGNIS, melden);
    window.removeEventListener('storage', speicher);
    mq?.removeEventListener?.('change', geraet);
  };
}
