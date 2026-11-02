/**
 * wartet.ts — „Wartet auf dich“: EINE Quelle, EINE Zahl für jede Fläche (OS-Neubau P2, 31.10.2026).
 *
 * Quelle ist das Hub-Werkzeug `wartet.eingang` (Plugin plugins/wartet): Runner-Freigaben, Vorgänge, Entscheidungen und
 * Kalendervorschläge in einer Liste. Jede Fläche, die „wartet“ zählt (Menüleiste, Zentrale, Seit-Streifen, Meldungen),
 * liest nur `wartetZahl()` bzw. `zahl` — keine eigene Zählung mehr.
 *
 * Ein Abruf für alle: `wartetBeobachten()` hängt eine Fläche an (Zählung der Beobachter); solange eine hängt, lädt der
 * Speicher bei `stand.geaendert` (lib/live.ts), bei Änderungen des Runners (`fyos:agent-offen`), bei Rückkehr in den Tab
 * und sonst alle 30 s (nur sichtbar). Nach jeder Antwort sofort frisch. Jede neue Zahl geht als Ereignis `fyos:wartet`
 * ({zahl}) an `window`, damit Teile ohne Solid-Bezug (Meldungsdienst) mitlesen.
 */
import { createSignal, onCleanup, onMount, type Accessor } from 'solid-js';
import { hub } from '~/lib/hub';
import { hoereStand } from '~/lib/live';
import { istHeute, spielMelden } from '~/lib/spiel';

export type WartetQuelle = 'runner' | 'itsm' | 'entscheidung' | 'kalender' | 'wache';
export type WartetAktion = 'ja' | 'nein' | 'spaeter' | 'immer' | 'oeffnen';

export type WartetEintrag = {
  id: string;
  quelle: WartetQuelle;
  satz: string;
  warum: string;
  wirkung: string;
  umkehrbar: boolean;
  zerstoererisch: boolean;
  buendelbar: boolean;
  seit: string | null;
  aktionen: WartetAktion[];
  ziel: string;
  art?: string;
  risiko?: 'low' | 'medium' | 'high' | null;
  dringlichkeit?: string;
  frist?: string | null;
  kontext?: string | null;
  gespraech?: string | null;
  werkzeug?: string | null;
  hat_befehl?: boolean;
  optionen?: string[] | null;
  regel?: { satz?: string; angelegt?: string; nr?: number | null } | null;
};

export type WartetEingang = {
  zahl: number;
  satz: string;
  eintraege: WartetEintrag[];
  gruppen: { freigabe: number; fragen: number; buendelbar: number };
  zurueckgestellt: { id: string; satz: string; bis: string | null }[];
  ausfall: Record<string, string>;
  vollstaendig: boolean;
  stand: string;
};

export type WartetAntwort = { ok: boolean; text?: string; ziel?: string; warnungen?: string[]; beantwortet?: number };

export const TAKT_MS = 30_000;
export const EREIGNIS = 'fyos:wartet';

// ── reine Helfer (getestet) ──────────────────────────────────────────────────────────────────
export const QUELLE_NAME: Record<WartetQuelle, string> = {
  runner: 'Runner',
  itsm: 'Vorgang',
  entscheidung: 'Entscheidung',
  kalender: 'Kalender',
  wache: 'Wache',
};

/** Die zwei Gruppen der Schublade: nicht Umkehrbares (Freigabe, einzeln) und Umkehrbares (Fragen, bündelbar). */
export function gruppiere(eintraege: readonly WartetEintrag[]): { freigaben: WartetEintrag[]; fragen: WartetEintrag[] } {
  return {
    freigaben: eintraege.filter((e) => !e.umkehrbar),
    fragen: eintraege.filter((e) => e.umkehrbar),
  };
}

/** Was „Alle n umkehrbaren erlauben“ beantwortet: nur Bündelbares, nie Zerstörerisches. */
export function buendelIds(eintraege: readonly WartetEintrag[]): string[] {
  return eintraege.filter((e) => e.buendelbar && e.umkehrbar && !e.zerstoererisch && e.aktionen.includes('ja')).map((e) => e.id);
}

export function zahlText(n: number): string {
  return n === 0 ? 'Nichts wartet auf dich' : n === 1 ? 'Eins wartet auf dich' : `${n} warten auf dich`;
}

/** „seit 3 Tagen“, „seit gestern“, „heute“ — `jetzt` für Tests. */
export function seitText(iso: string | null | undefined, jetzt: number = Date.now()): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(t)) return '';
  const tage = Math.floor((jetzt - t) / 86_400_000);
  if (tage <= 0) {
    const min = Math.max(0, Math.round((jetzt - t) / 60_000));
    return min < 60 ? `vor ${Math.max(1, min)} Min.` : `vor ${Math.round(min / 60)} Std.`;
  }
  return tage === 1 ? 'seit gestern' : `seit ${tage} Tagen`;
}

/** Ids, die seit dem letzten Stand neu sind (für eine Meldung „neu wartet …“). */
export function neueIds(vorher: readonly WartetEintrag[] | null, jetzt: readonly WartetEintrag[]): string[] {
  if (vorher == null) return [];
  const alt = new Set(vorher.map((e) => e.id));
  return jetzt.filter((e) => !alt.has(e.id)).map((e) => e.id);
}

// ── gemeinsamer Speicher ─────────────────────────────────────────────────────────────────────
const [eingang, setEingang] = createSignal<WartetEingang | null>(null);
const [fehler, setFehler] = createSignal<string | null>(null);
const [laedt, setLaedt] = createSignal(false);

/** Der letzte Stand (null bis zum ersten Abruf). */
export const wartetEingang: Accessor<WartetEingang | null> = eingang;
/** DIE Zahl. null = noch unbekannt (nichts zeigen), 0 = nichts wartet. */
export const wartetZahl: Accessor<number | null> = () => eingang()?.zahl ?? null;
export const wartetFehler: Accessor<string | null> = fehler;
export const wartetLaedt: Accessor<boolean> = laedt;

let lauf: Promise<WartetEingang | null> | null = null;
let nachLauf = false;

function melden(d: WartetEingang): void {
  try {
    window.dispatchEvent(new CustomEvent(EREIGNIS, { detail: { zahl: d.zahl, gruppen: d.gruppen } }));
  } catch {
    /* ohne window (Tests, Server) */
  }
}

/** Lädt `wartet.eingang`; laufende Abrufe werden geteilt, ein frischer Wunsch hängt einen zweiten an. */
export function wartetLaden(frisch = false): Promise<WartetEingang | null> {
  if (lauf) {
    if (frisch) nachLauf = true;
    return lauf;
  }
  setLaedt(true);
  lauf = hub<WartetEingang>('wartet.eingang', frisch ? { frisch: true } : {}, { zeitMs: 20_000 })
    .then((d) => {
      // Nur eine Antwort in der Form des Vertrags gilt (ein älterer Hub oder eine Attrappe liefert sonst `{}`).
      if (!d || !Array.isArray(d.eintraege) || typeof d.zahl !== 'number') throw new Error('wartet.eingang: unerwartete Antwort');
      setEingang(d);
      setFehler(null);
      melden(d);
      return d;
    })
    .catch((e: unknown) => {
      setFehler(e instanceof Error ? e.message : String(e));
      return eingang();
    })
    .finally(() => {
      lauf = null;
      setLaedt(false);
      if (nachLauf) {
        nachLauf = false;
        void wartetLaden(true);
      }
    });
  return lauf;
}

/** Ein Eintrag beantworten (Klick in der Schublade). Lädt danach frisch. */
export async function wartetAntworten(
  id: string,
  aktion: WartetAktion,
  mehr: { stunden?: number; bestaetigt?: boolean; notiz?: string } = {},
): Promise<WartetAntwort> {
  // Für das Spiel (P9): beantwortet am selben Tag, an dem es auflief → Punkte (einmal je Eintrag).
  const seit = eingang()?.eintraege.find((e) => e.id === id)?.seit;
  try {
    const r = await hub<WartetAntwort>('wartet.antworten', { id, aktion, ...mehr }, { art: 'bewusst', zeitMs: 60_000 });
    if ((aktion === 'ja' || aktion === 'nein' || aktion === 'immer') && istHeute(seit)) void spielMelden('freigabe_heute', `wartet:${id}`);
    return r;
  } finally {
    void wartetLaden(true);
  }
}

/** „Alle n umkehrbaren erlauben“. */
export async function wartetBuendel(ids: string[]): Promise<WartetAntwort> {
  try {
    return await hub<WartetAntwort>('wartet.antworten', { ids, aktion: 'ja' }, { art: 'bewusst', zeitMs: 60_000 });
  } finally {
    void wartetLaden(true);
  }
}

// ── Beobachten (eine Schleife für alle Flächen) ──────────────────────────────────────────────
let beobachter = 0;
let abbauen: (() => void) | null = null;

function starten(): () => void {
  const timer = setInterval(() => {
    if (document.visibilityState !== 'hidden') void wartetLaden();
  }, TAKT_MS);
  const sicht = () => {
    if (document.visibilityState === 'visible') void wartetLaden();
  };
  const runner = () => void wartetLaden(true);
  document.addEventListener('visibilitychange', sicht);
  window.addEventListener('fyos:agent-offen', runner);
  const abStand = hoereStand(() => void wartetLaden());
  void wartetLaden();
  return () => {
    clearInterval(timer);
    document.removeEventListener('visibilitychange', sicht);
    window.removeEventListener('fyos:agent-offen', runner);
    abStand();
  };
}

/** Hängt die Fläche an den gemeinsamen Abruf (ohne Solid: Rückgabe ist das Abhängen). */
export function wartetAnhaengen(): () => void {
  beobachter += 1;
  if (beobachter === 1) abbauen = starten();
  // Läuft die Schleife schon (z. B. für den Meldungsdienst), hat aber noch keinen Stand: eine später dazukommende Fläche
  // (Menüleiste) holt ihn sich, statt bis zum nächsten Takt ohne Zahl zu bleiben.
  else if (eingang() === null) void wartetLaden();
  let weg = false;
  return () => {
    if (weg) return;
    weg = true;
    beobachter -= 1;
    if (beobachter === 0 && abbauen) {
      abbauen();
      abbauen = null;
    }
  };
}

/** Wie `wartetAnhaengen`, für Solid-Komponenten. Rückgabe: die Zahl. */
export function wartetBeobachten(): Accessor<number | null> {
  onMount(() => onCleanup(wartetAnhaengen()));
  return wartetZahl;
}

/** Nur für Tests. */
export function wartetZuruecksetzen(): void {
  setEingang(null);
  setFehler(null);
  lauf = null;
  nachLauf = false;
}
