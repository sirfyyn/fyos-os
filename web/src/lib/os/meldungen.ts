/**
 * meldungen.ts — der Meldungsdienst des OS (28.10.2026): EIN Speicher für alles, was du gemeldet werden soll — Agent-Nachrichten,
 * Freigaben, Störungen, Termine, Mail. Daraus zeigen Toasts (components/os/MeldungenHost.tsx), der Verlauf (Glocke in der Menüleiste)
 * und die Systemmitteilungen (lib/os/meldungen-system.ts).
 *
 * Regeln:
 *   kritisch  bleibt stehen, bis es bestätigt wird (Störung, Freigabe mit hohem Risiko)
 *   hoch      30 s (Freigabe, Termin in höchstens 10 Min), mit Aktionsknöpfen
 *   normal    6 s (Agent-Nachricht, Mail)
 *   niedrig   3 s
 * Höchstens 3 Toasts zugleich (kritisch zuerst, dann nach Stufe und Zeit); die übrigen warten. Gleiche Quelle + gleicher Schlüssel
 * kommen nur einmal. Mehrere gleichartige (Mail, Agent) werden zusammengefasst („3 neue Mails“). „Nicht stören“ und Ruhe lassen
 * Meldungen still im Verlauf landen. Die Uhr (`jetzt`) ist einsetzbar, damit Tests ohne echte Zeit auskommen.
 * Modi (P4, 31.10.2026, lib/os/modi.ts): Ruhe nur kritisch, Normal höchstens 5 Unterbrechungen am Tag (du Nr. 707), Bereit alle.
 *
 * Die Anzeigedauer selbst läuft in der Host-Komponente (Darüberfahren und Fokus halten offen); hier steht nur `DAUER_MS`.
 */
import type { OsZiel } from './oeffnen';
import { QUELLEN, stillHalten, type MeldungenEinstellungen, type Quelle, type Stufe } from './meldungen-einstellungen';

export type { Quelle, Stufe } from './meldungen-einstellungen';

/** So lange bleibt ein Toast, `null` = bis zur Bestätigung. */
export const DAUER_MS: Record<Stufe, number | null> = { kritisch: null, hoch: 30_000, normal: 6_000, niedrig: 3_000 };
/** Gleichzeitig sichtbare Toasts. */
export const MAX_SICHTBAR = 3;
/** Größe des Verlaufs. */
export const VERLAUF_MAX = 100;
/** Gleiche Quelle + Schlüssel innerhalb dieser Zeit: nur einmal. */
export const ENTDOPPELN_MS = 6 * 60 * 60_000;
/** Gleichartige Meldungen innerhalb dieser Zeit werden zusammengefasst. */
export const SAMMEL_MS = 60_000;

export const RANG: Record<Stufe, number> = { kritisch: 0, hoch: 1, normal: 2, niedrig: 3 };

/** Ein Knopf an der Meldung. `ziel` öffnet im OS; ohne `ziel` schließt er nur. */
export interface MeldungAktion {
  id: string;
  text: string;
  ziel?: OsZiel;
}

export interface MeldungEingabe {
  quelle: Quelle;
  /** Identifiziert den Sachverhalt (Freigabe-Id, Mail-Id, Termin-Id + Phase …); derselbe Schlüssel meldet nicht zweimal */
  schluessel: string;
  stufe: Stufe;
  titel: string;
  text?: string;
  ziel?: OsZiel;
  aktionen?: MeldungAktion[];
  /** Gleichartige zusammenfassen: Titel bei n ≥ 2 (z. B. „3 neue Mails“) */
  sammeln?: (n: number) => string;
  /** Fassung für die Systemmitteilung (Sperrbildschirm): ohne Absender, Betreff und Textauszug; gilt, solange „Details in Systemmitteilungen“ aus ist */
  sicher?: { titel: string; text?: string; sammeln?: (n: number) => string };
  /** Abweichende Entdoppelungszeit (ms), z. B. kürzer bei Störungen, die wiederkehren */
  entdoppelnMs?: number;
  /** Keine Systemmitteilung und kein Toast, nur Verlauf */
  nurVerlauf?: boolean;
}

export interface Meldung {
  id: string;
  quelle: Quelle;
  schluessel: string;
  stufe: Stufe;
  titel: string;
  text: string;
  ziel?: OsZiel;
  aktionen: MeldungAktion[];
  zeit: number;
  gelesen: boolean;
  /** Wie viele Einzelmeldungen darin stecken (Zusammenfassung) */
  anzahl: number;
  /** Zählt Auffrischungen (neue Einzelmeldung in der Zusammenfassung): die Anzeige startet ihre Uhr neu */
  stand: number;
  sammeln?: (n: number) => string;
  sicher?: { titel: string; text: string; sammeln?: (n: number) => string };
}

/** Was nach `melde` für diese Meldung gilt. */
export interface Aufnahme {
  meldung: Meldung;
  /** Toast gewollt (nicht still) */
  toast: boolean;
  /** Systemmitteilung erlaubt (nicht still, Stufe ≥ normal, nicht nurVerlauf) */
  system: boolean;
  /** In eine vorhandene Meldung eingefaltet */
  zusammengefasst: boolean;
}

export interface MeldungenZustand {
  verlauf: Meldung[];
  /** Die jetzt sichtbaren Toasts (höchstens MAX_SICHTBAR), in Anzeigereihenfolge */
  sichtbar: Meldung[];
  /** Wartende Toasts */
  wartend: number;
  ungelesen: number;
}

type Hoerer = (z: MeldungenZustand) => void;
type NeuHoerer = (a: Aufnahme) => void;

export interface DienstOptionen {
  einstellungen: () => MeldungenEinstellungen;
  jetzt?: () => number;
  /** Ruht Agent gerade (Ruhe-Schalter oder Spielmodus)? Nur lesend. */
  ruhe?: () => boolean;
  /**
   * Modus des OS (lib/os/modi.ts, P4): `ruhe` lässt nur Kritisches unterbrechen, `normal` höchstens `budget()` Unterbrechungen am Tag
   * (du Nr. 707: 5; der Rest still in den Verlauf, Kritisches immer und ohne Abzug), `bereit` alles (des Agenten Ruhe hält dann nichts still).
   * Ohne `modus` gilt das alte Verhalten.
   */
  modus?: () => 'ruhe' | 'normal' | 'bereit' | undefined;
  budget?: () => number;
  /** Merkt den Tageszähler über Neuladen hinweg (localStorage); ohne nur im Speicher. */
  budgetSpeicher?: Pick<Storage, 'getItem' | 'setItem'> | null;
}

export const BUDGET_SCHLUESSEL = 'fyos:os:meldebudget';

/** Kalendertag (Ortszeit) als Schlüssel des Tageszählers. */
const tagVon = (t: number): string => {
  const d = new Date(t);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export class Meldungsdienst {
  private verlauf: Meldung[] = [];
  private offen = new Set<string>(); // Toast-Kandidaten (nicht weggeklickt, nicht abgelaufen)
  private bekannt = new Map<string, number>();
  private zaehler = 0;
  private budgetTag: { tag: string; n: number } | null = null;
  private hoerer = new Set<Hoerer>();
  private neuHoerer = new Set<NeuHoerer>();
  private readonly jetzt: () => number;

  constructor(private readonly opt: DienstOptionen) {
    this.jetzt = opt.jetzt ?? (() => Date.now());
  }

  /** Eine Meldung aufnehmen. null: Quelle aus oder gleicher Sachverhalt schon gemeldet. */
  melde(e: MeldungEingabe): Aufnahme | null {
    const einst = this.opt.einstellungen();
    if (!einst.quellen[e.quelle]) return null;
    const jetzt = this.jetzt();
    const key = `${e.quelle}|${e.schluessel}`;
    const zuletzt = this.bekannt.get(key);
    if (zuletzt !== undefined && jetzt - zuletzt < (e.entdoppelnMs ?? ENTDOPPELN_MS)) return null;
    this.bekannt.set(key, jetzt);
    if (this.bekannt.size > 600) {
      const aelteste = [...this.bekannt.entries()].sort((a, b) => a[1] - b[1]).slice(0, 100);
      for (const [k] of aelteste) this.bekannt.delete(k);
    }

    const modus = this.opt.modus?.();
    const ruhe = modus === 'bereit' ? false : (this.opt.ruhe?.() ?? false);
    let still = e.nurVerlauf || stillHalten(einst, e.stufe, new Date(jetzt), ruhe) || (modus === 'ruhe' && e.stufe !== 'kritisch');

    // Zusammenfassen: eine ungelesene, noch offene Meldung derselben Quelle mit `sammeln`, jünger als SAMMEL_MS
    const ziel = e.sammeln
      ? this.verlauf.find((m) => m.quelle === e.quelle && m.sammeln && !m.gelesen && this.offen.has(m.id) && jetzt - m.zeit < SAMMEL_MS)
      : undefined;
    // Meldebudget im Normalmodus: eine neue Unterbrechung kostet eins, eine eingefaltete nicht, Kritisches nie
    if (!still && !ziel && modus === 'normal' && e.stufe !== 'kritisch') {
      if (this.budgetRest(jetzt) <= 0) still = true;
      else this.budgetZaehlen(jetzt);
    }
    const toast = !still;
    const system = toast && (e.stufe === 'kritisch' || e.stufe === 'hoch' || e.stufe === 'normal');

    if (ziel) {
      ziel.anzahl += 1;
      ziel.stand += 1;
      ziel.zeit = jetzt;
      ziel.titel = (e.sammeln ?? ziel.sammeln!)(ziel.anzahl);
      ziel.text = e.text ?? '';
      ziel.stufe = RANG[e.stufe] < RANG[ziel.stufe] ? e.stufe : ziel.stufe;
      ziel.ziel = e.ziel ?? ziel.ziel;
      ziel.aktionen = e.aktionen ?? ziel.aktionen;
      if (ziel.sicher) ziel.sicher = { ...ziel.sicher, titel: ziel.sicher.sammeln ? ziel.sicher.sammeln(ziel.anzahl) : ziel.sicher.titel };
      const a: Aufnahme = { meldung: ziel, toast, system, zusammengefasst: true };
      this.melden(a);
      this.aendern();
      return a;
    }

    const m: Meldung = {
      id: `m${++this.zaehler}`,
      quelle: e.quelle,
      schluessel: e.schluessel,
      stufe: e.stufe,
      titel: e.titel,
      text: e.text ?? '',
      ...(e.ziel ? { ziel: e.ziel } : {}),
      aktionen: e.aktionen ?? [],
      zeit: jetzt,
      gelesen: false,
      anzahl: 1,
      stand: 0,
      ...(e.sammeln ? { sammeln: e.sammeln } : {}),
      ...(e.sicher ? { sicher: { titel: e.sicher.titel, text: e.sicher.text ?? '', ...(e.sicher.sammeln ? { sammeln: e.sicher.sammeln } : {}) } } : {}),
    };
    this.verlauf.unshift(m);
    if (this.verlauf.length > VERLAUF_MAX) {
      for (const weg of this.verlauf.splice(VERLAUF_MAX)) this.offen.delete(weg.id);
    }
    if (toast) this.offen.add(m.id);
    const a: Aufnahme = { meldung: m, toast, system, zusammengefasst: false };
    this.melden(a);
    this.aendern();
    return a;
  }

  /** Toast schliessen (Verlauf bleibt). `gelesen`: bestätigt/geöffnet; Ablauf der Zeit lässt es ungelesen. */
  schliesse(id: string, gelesen = false): void {
    const m = this.verlauf.find((x) => x.id === id);
    if (!m) return;
    let geaendert = this.offen.delete(id);
    if (gelesen && !m.gelesen) {
      m.gelesen = true;
      geaendert = true;
    }
    if (geaendert) this.aendern();
  }

  /** Im Verlauf als gelesen markieren (Toast schließt mit). */
  lies(id: string): void {
    this.schliesse(id, true);
  }

  alleGelesen(): void {
    for (const m of this.verlauf) m.gelesen = true;
    this.offen.clear();
    this.aendern();
  }

  verlaufLeeren(): void {
    this.verlauf = [];
    this.offen.clear();
    this.aendern();
  }

  /** Abbild für die Anzeige: Kopien, damit Solid Änderungen (Zusammenfassung, gelesen) erkennt; die Anzeige schlüsselt nach `id`. */
  get zustand(): MeldungenZustand {
    const kandidaten = this.verlauf.filter((m) => this.offen.has(m.id));
    const geordnet = kandidaten.slice().sort((a, b) => RANG[a.stufe] - RANG[b.stufe] || b.zeit - a.zeit);
    const sichtbar = geordnet.slice(0, MAX_SICHTBAR).map((m) => ({ ...m }));
    return {
      verlauf: this.verlauf.map((m) => ({ ...m })),
      sichtbar,
      wartend: Math.max(0, geordnet.length - sichtbar.length),
      ungelesen: this.verlauf.filter((m) => !m.gelesen).length,
    };
  }

  abonniere(f: Hoerer): () => void {
    this.hoerer.add(f);
    f(this.zustand);
    return () => this.hoerer.delete(f);
  }

  /** Für die Systemmitteilungen: jede neue oder aufgefrischte Meldung. */
  beiNeu(f: NeuHoerer): () => void {
    this.neuHoerer.add(f);
    return () => this.neuHoerer.delete(f);
  }

  /** Quelle für die Einstellungs-Seite: Zahl je Quelle im Verlauf. */
  zaehleJeQuelle(): Record<Quelle, number> {
    const z = Object.fromEntries(QUELLEN.map((q) => [q, 0])) as Record<Quelle, number>;
    for (const m of this.verlauf) z[m.quelle] += 1;
    return z;
  }

  /** Wie viele Unterbrechungen der Normalmodus heute noch erlaubt (Budget minus verbraucht, nie unter 0). */
  budgetRest(jetzt = this.jetzt()): number {
    const budget = Math.max(0, this.opt.budget?.() ?? 5);
    return Math.max(0, budget - this.budgetStand(jetzt).n);
  }

  private budgetStand(jetzt: number): { tag: string; n: number } {
    const tag = tagVon(jetzt);
    if (this.budgetTag?.tag === tag) return this.budgetTag;
    let n = 0;
    try {
      const roh = JSON.parse(this.opt.budgetSpeicher?.getItem(BUDGET_SCHLUESSEL) ?? 'null') as { tag?: string; n?: number } | null;
      if (roh?.tag === tag && typeof roh.n === 'number' && roh.n >= 0) n = roh.n;
    } catch {
      n = 0;
    }
    this.budgetTag = { tag, n };
    return this.budgetTag;
  }

  private budgetZaehlen(jetzt: number): void {
    const s = this.budgetStand(jetzt);
    s.n += 1;
    try {
      this.opt.budgetSpeicher?.setItem(BUDGET_SCHLUESSEL, JSON.stringify(s));
    } catch {
      /* gilt dann bis zum Neuladen */
    }
  }

  private melden(a: Aufnahme): void {
    for (const f of [...this.neuHoerer]) {
      try {
        f(a);
      } catch {
        /* ein Hörer darf die anderen nicht aufhalten */
      }
    }
  }

  private aendern(): void {
    const z = this.zustand;
    for (const f of [...this.hoerer]) f(z);
  }
}
