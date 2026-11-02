/**
 * strom.ts — „Live“: der Strom der autonomen Arbeit über alle Gespräche und Läufe (`GET /api/strom`).
 *
 * Live ist die Voreinstellung. `/live` (oder ein Schalter) blendet nur die ANZEIGE aus, der Agent merkt nichts.
 * Schreiben ändert nur den Fokus (welches Gespräch groß ist), nie den Strom. Ein Klick auf eine Zeile verschiebt den Fokus.
 */
import type { StromGespraech, StromZeile } from './typen';
import { werkzeugTitel } from './verlauf';

/** So viele Zeilen hält der Client (app.js: 200). */
export const STROM_MAX = 200;
/** Ein Strom, der in den letzten 30 s etwas gesagt hat, gilt als „aktiv“. */
export const STROM_AKTIV_MS = 30_000;

export interface StromZustand {
  zeilen: StromZeile[];
  gespraeche: StromGespraech[];
  /** Zeitpunkt der letzten Zeile (0 = noch keine). */
  letzte: number;
}

export const leerStrom = (): StromZustand => ({ zeilen: [], gespraeche: [], letzte: 0 });

export function mitHallo(alt: StromZustand, daten: { gespraeche?: StromGespraech[] } | null | undefined): StromZustand {
  return { ...alt, gespraeche: Array.isArray(daten?.gespraeche) ? daten.gespraeche : alt.gespraeche };
}

/** Eine neue Zeile anhängen; ältere über `STROM_MAX` fallen weg. Ungültige Zeilen ändern nichts. */
export function mitZeile(alt: StromZustand, zeile: unknown): StromZustand {
  const z = zeile as Partial<StromZeile> | null;
  if (!z || typeof z !== 'object' || typeof z.text !== 'string' || typeof z.typ !== 'string') return alt;
  const t = typeof z.t === 'number' ? z.t : Date.now();
  const voll: StromZeile = { ...(z as StromZeile), t };
  let zeilen = [...alt.zeilen, voll];
  if (zeilen.length > STROM_MAX) zeilen = zeilen.slice(zeilen.length - STROM_MAX);
  // Ein Gespräch, das der Strom zum ersten Mal nennt (z. B. ein neuer Lauf), in die Namensliste aufnehmen.
  let gespraeche = alt.gespraeche;
  if (typeof z.gespraech === 'number' && !gespraeche.some((g) => g.id === z.gespraech)) {
    gespraeche = [...gespraeche, { id: z.gespraech, titel: z.titel ?? `Gespräch ${z.gespraech}`, art: z.art ?? '' }];
  }
  return { zeilen, gespraeche, letzte: t };
}

export const stromAktiv = (s: StromZustand, jetzt: number = Date.now()): boolean => s.letzte > 0 && jetzt - s.letzte < STROM_AKTIV_MS;

/** Titel eines Gesprächs aus Strom-Namensliste oder Zeilen. */
export function stromTitel(s: StromZustand, id: number): string | undefined {
  const genannt = s.gespraeche.find((g) => g.id === id)?.titel;
  if (genannt) return genannt;
  for (let i = s.zeilen.length - 1; i >= 0; i--) {
    const z = s.zeilen[i];
    if (z && z.gespraech === id && z.titel) return z.titel;
  }
  return undefined;
}

/** Wie lange eine Zeile des Stroms als „arbeitet gerade“ gilt. */
export const AKTIVITAET_MS = 2 * 60_000;

/** Für `werkzeugTitel`: das Kernargument, das der Strom als Text mitgibt, unter dem Namen, den das Werkzeug erwartet. */
function argAusKurz(werkzeug: string, kurz: string): Record<string, unknown> {
  if (werkzeug === 'bash' || werkzeug === 'knoten_befehl') return { command: kurz };
  if (werkzeug === 'read' || werkzeug === 'write' || werkzeug === 'edit') return { path: kurz };
  if (werkzeug === 'hub_aufrufen' || werkzeug === 'hub_schema') return { werkzeug: kurz };
  if (werkzeug === 'web_holen') return { url: kurz };
  return { suche: kurz, titel: kurz, aktion: kurz };
}

/** Eine Zeile des Stroms in Klartext: „Shell: git push“, „Eingang: matrix …“. */
export function stromKlartext(z: StromZeile): string {
  const wz = z.wz;
  if (z.typ === 'werkzeug' && wz) {
    const kurz = z.text.startsWith(wz) ? z.text.slice(wz.length).trim() : z.text;
    return werkzeugTitel(wz, argAusKurz(wz, kurz));
  }
  if (z.typ === 'fehler') return z.text;
  if (z.typ === 'sagt') return `schreibt: ${z.text}`;
  if (z.typ === 'fertig') return 'Zug fertig';
  return z.text;
}

/**
 * Die dezente Aktivitätszeile: „Agent arbeitet an INC-4905 …“, solange der Strom in den letzten zwei Minuten etwas
 * gemeldet hat, sonst „Agent ist ruhig“. Zeilen des Gesprächs im Fokus zählen mit; die Zeile sagt, was Agent tut,
 * auch wenn du gerade mit ihr schreibt.
 */
export function aktivitaet(s: StromZustand, agentName: string, jetzt: number = Date.now()): { aktiv: boolean; text: string; zeile: StromZeile | null } {
  let zeile: StromZeile | null = null;
  for (let i = s.zeilen.length - 1; i >= 0; i--) {
    const z = s.zeilen[i];
    if (z && z.typ !== 'mensch') {
      zeile = z;
      break;
    }
  }
  if (!zeile || jetzt - zeile.t > AKTIVITAET_MS || zeile.typ === 'fertig') return { aktiv: false, text: `${agentName} ist ruhig`, zeile };
  const titel = zeile.art === 'lauf' && zeile.titel ? zeile.titel.replace(/^Lauf\s+\S+:\s*/, '') : '';
  const ort = titel ? ` an ${titel}` : '';
  const was = zeile.typ === 'eingang' ? `liest Eingang ${stromKlartext(zeile)}` : stromKlartext(zeile);
  return { aktiv: true, text: `${agentName} arbeitet${ort}: ${was}`, zeile };
}

export type LiveBefehl = 'an' | 'aus' | 'wechseln';

/**
 * `/live`, `/live an`, `/live aus` (auch `ein`). Gibt `null` zurück, wenn der Text kein Befehl ist — er geht dann an den Agenten.
 */
export function liveBefehl(text: string): LiveBefehl | null {
  const m = /^\/live(?:\s+(an|aus|ein))?\s*$/i.exec(String(text ?? '').trim());
  if (!m) return null;
  const wunsch = m[1]?.toLowerCase();
  if (!wunsch) return 'wechseln';
  return wunsch === 'aus' ? 'aus' : 'an';
}

export const LIVE_SPEICHER = 'fyos:agent:live';

/** Live ist an, solange nicht ausdrücklich „aus“ gespeichert ist. */
export function liesLive(speicher: Pick<Storage, 'getItem'> | null | undefined): boolean {
  try {
    return speicher?.getItem(LIVE_SPEICHER) !== 'aus';
  } catch {
    return true;
  }
}

export function schreibeLive(speicher: Pick<Storage, 'setItem'> | null | undefined, an: boolean): void {
  try {
    speicher?.setItem(LIVE_SPEICHER, an ? 'an' : 'aus');
  } catch {
    /* ohne Speicher gilt die Voreinstellung */
  }
}
