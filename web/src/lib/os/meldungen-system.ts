/**
 * meldungen-system.ts — Systemmitteilungen (macOS Mitteilungszentrale, Windows, Linux) für den Meldungsdienst (28.10.2026).
 *
 * Drei Wege, in dieser Reihenfolge:
 *   huelle   in der Desktop-Hülle über `window.__FYOS_HUELLE__.benachrichtigen` (apps/fyos-shell, Profil os). Die Seite spricht nie die
 *            Tauri-Schnittstellen der Hülle selbst; die Hülle prüft Absender, Länge und Rate.
 *   browser  im Browser über die Notification-API. Die Erlaubnis wird NIE von allein erfragt, nur auf einen Klick
 *            (`erlaubnisAnfragen`, Knopf in den Einstellungen).
 *   keine    sonst nur Toast und Verlauf.
 *
 * Gesendet wird nur, wenn die Seite im Hintergrund ist (verborgen oder ohne Fokus) und die Stufe mindestens „normal“ ist. Ein Klick
 * auf die Systemmitteilung bringt das Fenster nach vorn; die Hülle meldet den Klick nicht zurück, darum gilt: Kommt der Fokus binnen
 * 10 s nach der letzten Systemmitteilung zurück, öffnet das OS deren Ziel (Browser: der Klick selbst).
 * Datenschutz: Titel und Text stammen aus den Quellen (Mail: Absender und Betreff, nie ein Textauszug).
 */
import type { Aufnahme, Meldung } from './meldungen';
import type { MeldungenEinstellungen } from './meldungen-einstellungen';

/** Innerhalb dieser Zeit nach einer Systemmitteilung gilt die Rückkehr in den Vordergrund als Klick darauf. */
export const KLICK_FENSTER_MS = 10_000;

export interface HuelleBruecke {
  profil?: string;
  version?: string;
  benachrichtigen(titel: string, text: string, optionen?: { still?: boolean }): Promise<{ gezeigt?: boolean; unterdrueckt?: boolean }>;
}

interface BrowserMitteilungKlasse {
  new (titel: string, optionen?: { body?: string; tag?: string; silent?: boolean }): { onclick: ((e: unknown) => void) | null; close(): void };
  permission: string;
  requestPermission(): Promise<string>;
}

export type BrueckenArt = 'huelle' | 'browser' | 'keine';

export interface Umgebung {
  huelle?: HuelleBruecke | undefined;
  notification?: BrowserMitteilungKlasse | undefined;
}

/** Die Umgebung dieses Fensters (ohne Fenster, z. B. im Test, leer). */
export function umgebungLesen(): Umgebung {
  if (typeof window === 'undefined') return {};
  const w = window as unknown as { __FYOS_HUELLE__?: HuelleBruecke; Notification?: BrowserMitteilungKlasse };
  const h = w.__FYOS_HUELLE__;
  return { huelle: h && typeof h.benachrichtigen === 'function' ? h : undefined, notification: w.Notification };
}

/** Hülle vor Browser; im Browser nur mit erteilter Erlaubnis. */
export function waehleBruecke(u: Umgebung): BrueckenArt {
  if (u.huelle) return 'huelle';
  if (u.notification && u.notification.permission === 'granted') return 'browser';
  return 'keine';
}

/** Kann der Browser noch fragen (Erlaubnis weder erteilt noch verweigert)? */
export function kannErlaubnisAnfragen(u: Umgebung): boolean {
  return !u.huelle && !!u.notification && u.notification.permission === 'default';
}

export interface SystemOptionen {
  einstellungen: () => MeldungenEinstellungen;
  umgebung?: () => Umgebung;
  /** Ist die Seite im Hintergrund (verborgen oder ohne Fokus)? */
  hintergrund?: () => boolean;
  jetzt?: () => number;
  /** Das Ziel der Meldung im OS öffnen */
  oeffne: (m: Meldung) => void;
  /** Meldung als gelesen markieren (Toast schließt) */
  gelesen: (id: string) => void;
}

export function seiteImHintergrund(): boolean {
  if (typeof document === 'undefined') return false;
  return document.visibilityState === 'hidden' || !document.hasFocus();
}

export class SystemMitteilungen {
  private zuletzt: { meldung: Meldung; zeit: number } | null = null;
  private readonly umgebung: () => Umgebung;
  private readonly hintergrund: () => boolean;
  private readonly jetzt: () => number;

  constructor(private readonly opt: SystemOptionen) {
    this.umgebung = opt.umgebung ?? umgebungLesen;
    this.hintergrund = opt.hintergrund ?? seiteImHintergrund;
    this.jetzt = opt.jetzt ?? (() => Date.now());
  }

  /** Eine neue Meldung: im Hintergrund als Systemmitteilung senden. Gibt zurück, auf welchem Weg (oder `keine`). */
  async beiNeu(a: Aufnahme): Promise<BrueckenArt> {
    if (!a.system || !this.opt.einstellungen().system || !this.hintergrund()) return 'keine';
    const u = this.umgebung();
    const weg = waehleBruecke(u);
    const m = a.meldung;
    // Sperrbildschirm: ohne Schalter nur die sichere Fassung (Mail: „Neue Mail“, Agent: „Agent hat geschrieben“)
    const sicher = !this.opt.einstellungen().systemDetails && m.sicher;
    const titel = sicher ? sicher.titel : m.titel;
    const text = sicher ? sicher.text : m.text;
    if (weg === 'huelle') {
      try {
        const r = await u.huelle!.benachrichtigen(titel.slice(0, 80), text.slice(0, 240), { still: m.stufe === 'normal' });
        if (r && r.gezeigt === false && r.unterdrueckt !== true) return 'keine';
      } catch {
        // Fehler der Hülle (zum Beispiel MITTEILUNGEN_NICHT_ERLAUBT): Toast und Verlauf genügen, nichts erneut versuchen
        return 'keine';
      }
      this.zuletzt = { meldung: m, zeit: this.jetzt() };
      return 'huelle';
    }
    if (weg === 'browser') {
      try {
        const N = u.notification!;
        const n = new N(titel, { body: text, tag: sicher ? m.quelle : `${m.quelle}|${m.schluessel}`, silent: m.stufe === 'normal' });
        n.onclick = () => {
          this.zuletzt = null;
          try {
            if (typeof window !== 'undefined') window.focus();
          } catch {
            /* ohne Fokusrecht bleibt das Fenster, wo es ist */
          }
          this.opt.oeffne(m);
          this.opt.gelesen(m.id);
          n.close();
        };
      } catch {
        return 'keine';
      }
      this.zuletzt = { meldung: m, zeit: this.jetzt() };
      return 'browser';
    }
    return 'keine';
  }

  /** Die Seite hat den Fokus wieder: kam er binnen 10 s nach einer Systemmitteilung, öffnet deren Ziel. true = geöffnet. */
  beiFokus(): boolean {
    const z = this.zuletzt;
    this.zuletzt = null;
    if (!z || this.jetzt() - z.zeit > KLICK_FENSTER_MS) return false;
    this.opt.oeffne(z.meldung);
    this.opt.gelesen(z.meldung.id);
    return true;
  }

  /** Nur auf einen Klick des Nutzers rufen: fragt den Browser nach der Erlaubnis. */
  async erlaubnisAnfragen(): Promise<string> {
    const u = this.umgebung();
    if (!kannErlaubnisAnfragen(u)) return u.huelle ? 'huelle' : (u.notification?.permission ?? 'nicht-verfuegbar');
    try {
      return await u.notification!.requestPermission();
    } catch {
      return 'fehler';
    }
  }
}
