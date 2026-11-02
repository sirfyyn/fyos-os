/**
 * dialoge.ts — zentraler Dialogdienst (28.10.2026, Desktop-App „FYOS OS“).
 *
 * Ersetzt window.confirm/alert/prompt. Der System-WebView der Desktop-App (WKWebView/WebView2) zeigt native
 * JS-Dialoge nicht an: confirm() liefert sofort false, alert/prompt zeigen nichts — Vorgänge brachen still ab.
 * Hier laufen alle Rückfragen durch EINEN Host (components/ui/DialogHost.tsx, eingebaut in BaseLayout), der
 * in jedem Fenster des OS und auf jeder Seite sitzt.
 *
 *   if (!(await bestaetigen({ titel: 'Löschen?', gefaehrlich: true }))) return;
 *   await meldung({ titel: 'Fertig', text: '3 von 3 gesetzt.', art: 'erfolg' });
 *   const name = await eingabe({ titel: 'Neuer Name', wert: alt });   // null = abgebrochen
 *
 * Bewusst KEIN Rückfall auf native Dialoge, auch nicht im Browser: ein Rückfall, der nur manchmal greift,
 * versteckt genau den Fehler, den dieser Dienst beseitigt (Wächter: tests/unit/keine-native-dialoge.test.ts).
 * Ohne Host (SSR) wird nicht gezeigt, sondern sicher beantwortet: bestaetigen → false, eingabe → null.
 * Mehrere Aufrufe hintereinander bilden eine Warteschlange; gezeigt wird immer der erste.
 */
import { createSignal } from 'solid-js';

export type MeldungsArt = 'info' | 'erfolg' | 'warnung' | 'fehler';

interface Basis {
  titel: string;
  /** Fließtext; Zeilenumbrüche bleiben erhalten, langer Text scrollt im Dialog. */
  text?: string;
  /** Liste unter dem Text (z. B. Fehlerliste, gesperrte Vorgänge), scrollbar. */
  details?: string[];
  /** Überschrift der Liste. */
  detailsTitel?: string;
  /** Farbton der Liste: warn (gesperrt) oder fehler (fehlgeschlagen). */
  detailsTon?: 'warn' | 'fehler';
}

export interface BestaetigenOptionen extends Basis {
  ok?: string;
  abbrechen?: string;
  /** Zerstörerisch: rote Darstellung, Fokus zunächst auf „Abbrechen“. */
  gefaehrlich?: boolean;
}

export interface MeldungOptionen extends Basis {
  art?: MeldungsArt;
  ok?: string;
}

export interface EingabeOptionen extends Basis {
  wert?: string;
  platzhalter?: string;
  ok?: string;
  abbrechen?: string;
  /** Liefert eine Fehlermeldung (Dialog bleibt offen) oder null/undefined/'' wenn der Wert passt. */
  pruefen?: (wert: string) => string | null | undefined;
}

export type DialogAnfrage =
  | { id: number; typ: 'bestaetigen'; opt: BestaetigenOptionen; antwort: (v: boolean) => void }
  | { id: number; typ: 'meldung'; opt: MeldungOptionen; antwort: (v: void) => void }
  | { id: number; typ: 'eingabe'; opt: EingabeOptionen; antwort: (v: string | null) => void };

const [warteschlange, setWarteschlange] = createSignal<DialogAnfrage[]>([]);
let zaehler = 0;

/** Die Anfrage, die gerade gezeigt wird (vorderste der Warteschlange). */
export const aktiverDialog = (): DialogAnfrage | undefined => warteschlange()[0];
/** Anzahl wartender Anfragen inklusive der gezeigten. */
export const dialogeOffen = (): number => warteschlange().length;

/** Beendet die vorderste Anfrage; der Host zeigt danach die nächste. */
export function dialogSchliessen(id: number): void {
  setWarteschlange((q) => q.filter((a) => a.id !== id));
}

const hatHost = (): boolean => typeof document !== 'undefined';

function einreihen<T>(bau: (id: number, antwort: (v: T) => void) => DialogAnfrage, ohneHost: T): Promise<T> {
  if (!hatHost()) return Promise.resolve(ohneHost);
  return new Promise<T>((aufloesen) => {
    const id = ++zaehler;
    let beantwortet = false;
    const antwort = (v: T) => {
      if (beantwortet) return;
      beantwortet = true;
      dialogSchliessen(id);
      aufloesen(v);
    };
    setWarteschlange((q) => [...q, bau(id, antwort)]);
  });
}

/** Ja/Nein-Rückfrage. true = bestätigt; Esc, Klick daneben und „Abbrechen“ = false. */
export function bestaetigen(opt: BestaetigenOptionen): Promise<boolean> {
  return einreihen<boolean>((id, antwort) => ({ id, typ: 'bestaetigen', opt, antwort }), false);
}

/** Hinweis mit einem „OK“. Löst auf, wenn er geschlossen wird. */
export function meldung(opt: MeldungOptionen): Promise<void> {
  return einreihen<void>((id, antwort) => ({ id, typ: 'meldung', opt, antwort }), undefined);
}

/** Texteingabe. Löst mit dem Text auf, bei Abbruch (Esc, Klick daneben, „Abbrechen“) mit null. */
export function eingabe(opt: EingabeOptionen): Promise<string | null> {
  return einreihen<string | null>((id, antwort) => ({ id, typ: 'eingabe', opt, antwort }), null);
}

/** Nur für Tests: räumt die Warteschlange und beantwortet offene Anfragen als abgebrochen. */
export function dialogeZuruecksetzen(): void {
  for (const a of warteschlange()) {
    if (a.typ === 'bestaetigen') a.antwort(false);
    else if (a.typ === 'eingabe') a.antwort(null);
    else a.antwort();
  }
  setWarteschlange([]);
}
