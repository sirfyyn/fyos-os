/**
 * meldungen-einstellungen.ts — Einstellungen des Meldungsdienstes (28.10.2026), gespeichert wie die übrigen OS-Einstellungen in
 * localStorage (`fyos:os:meldungen`). Je Quelle an/aus, Systemmitteilungen, „Nicht stören“ (von Hand und mit Zeitfenster, kritisch
 * durchbricht auf Wunsch), Ruhe von Agent/Spielmodus beachten, Mail-Ordner. Reine Funktionen, keine Oberfläche.
 */
export type Quelle = 'agent' | 'freigabe' | 'stoerung' | 'termin' | 'mail';
export type Stufe = 'kritisch' | 'hoch' | 'normal' | 'niedrig';

export const QUELLEN: readonly Quelle[] = ['agent', 'freigabe', 'stoerung', 'termin', 'mail'];
export const QUELLEN_NAME: Record<Quelle, string> = {
  agent: 'Agent-Nachrichten',
  freigabe: 'Freigaben',
  stoerung: 'Störungen',
  termin: 'Termine',
  mail: 'Mail',
};

export interface NichtStoeren {
  /** Von Hand eingeschaltet (bis zum Ausschalten) */
  manuell: boolean;
  /** Zeitfenster aktiv */
  zeit: boolean;
  von: string;
  bis: string;
  /** Kritische Meldungen kommen trotzdem durch */
  kritischDurchbrechen: boolean;
}

export interface MeldungenEinstellungen {
  quellen: Record<Quelle, boolean>;
  /** Mail: nur diese Ordner (Gmail-Systemordner-IDs); Vorgabe nur der Posteingang */
  mailOrdner: string[];
  /** Systemmitteilungen (Hülle oder Browser), wenn die Seite im Hintergrund ist */
  system: boolean;
  nichtStoeren: NichtStoeren;
  /** Details (Absender, Betreff, Textauszug) auch in Systemmitteilungen; Vorgabe aus: dort nur „Neue Mail“ bzw. „Agent hat geschrieben“ */
  systemDetails: boolean;
  /** Ruhe von Agent oder Spielmodus (agenten.ruhe, nur lesend) wie „Nicht stören“ behandeln */
  ruheBeachten: boolean;
}

export const SCHLUESSEL = 'fyos:os:meldungen';

export const VORGABE: MeldungenEinstellungen = {
  quellen: { agent: true, freigabe: true, stoerung: true, termin: true, mail: true },
  mailOrdner: ['INBOX'],
  system: true,
  systemDetails: false,
  nichtStoeren: { manuell: false, zeit: false, von: '22:00', bis: '07:00', kritischDurchbrechen: true },
  ruheBeachten: true,
};

const UHR = /^([01]\d|2[0-3]):([0-5]\d)$/;

function bool(x: unknown, vorgabe: boolean): boolean {
  return typeof x === 'boolean' ? x : vorgabe;
}
function uhr(x: unknown, vorgabe: string): string {
  return typeof x === 'string' && UHR.test(x) ? x : vorgabe;
}

/** Aus unbekannten (gespeicherten) Daten saubere Einstellungen; Fehlendes und Ungültiges fällt auf die Vorgabe. */
export function bereinige(roh: unknown): MeldungenEinstellungen {
  const r = (roh && typeof roh === 'object' ? roh : {}) as Record<string, unknown>;
  const q = (r.quellen && typeof r.quellen === 'object' ? r.quellen : {}) as Record<string, unknown>;
  const n = (r.nichtStoeren && typeof r.nichtStoeren === 'object' ? r.nichtStoeren : {}) as Record<string, unknown>;
  const ordner = Array.isArray(r.mailOrdner) ? r.mailOrdner.filter((o): o is string => typeof o === 'string' && o.length > 0 && o.length < 80).slice(0, 20) : VORGABE.mailOrdner;
  return {
    quellen: Object.fromEntries(QUELLEN.map((k) => [k, bool(q[k], VORGABE.quellen[k])])) as Record<Quelle, boolean>,
    mailOrdner: ordner.length ? ordner : VORGABE.mailOrdner,
    system: bool(r.system, VORGABE.system),
    systemDetails: bool(r.systemDetails, false),
    nichtStoeren: {
      manuell: bool(n.manuell, false),
      zeit: bool(n.zeit, false),
      von: uhr(n.von, VORGABE.nichtStoeren.von),
      bis: uhr(n.bis, VORGABE.nichtStoeren.bis),
      kritischDurchbrechen: bool(n.kritischDurchbrechen, true),
    },
    ruheBeachten: bool(r.ruheBeachten, true),
  };
}

export function lesen(speicher: Pick<Storage, 'getItem'> | null = standardSpeicher()): MeldungenEinstellungen {
  try {
    const roh = speicher?.getItem(SCHLUESSEL);
    return bereinige(roh ? JSON.parse(roh) : null);
  } catch {
    return bereinige(null);
  }
}

export function schreiben(e: MeldungenEinstellungen, speicher: Pick<Storage, 'setItem'> | null = standardSpeicher()): void {
  try {
    speicher?.setItem(SCHLUESSEL, JSON.stringify(e));
  } catch {
    /* Speicher gesperrt: die Einstellung gilt dann nur bis zum Neuladen */
  }
}

function standardSpeicher(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

function minuten(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

/** Liegt `d` im Zeitfenster `von`–`bis` (auch über Mitternacht; von = bis heißt: nie)? */
export function imFenster(von: string, bis: string, d: Date): boolean {
  const a = minuten(von);
  const b = minuten(bis);
  const jetzt = d.getHours() * 60 + d.getMinutes();
  if (a === b) return false;
  return a < b ? jetzt >= a && jetzt < b : jetzt >= a || jetzt < b;
}

export function nichtStoerenAktiv(e: MeldungenEinstellungen, d: Date): boolean {
  const n = e.nichtStoeren;
  return n.manuell || (n.zeit && imFenster(n.von, n.bis, d));
}

/** Soll eine Meldung der Stufe `s` jetzt still bleiben (nur Verlauf)? `ruhe`: Agent/Spielmodus ruht (agenten.ruhe). */
export function stillHalten(e: MeldungenEinstellungen, s: Stufe, d: Date, ruhe = false): boolean {
  const aktiv = nichtStoerenAktiv(e, d) || (e.ruheBeachten && ruhe);
  if (!aktiv) return false;
  return !(s === 'kritisch' && e.nichtStoeren.kritischDurchbrechen);
}
