/**
 * anzeige.ts — aus dem Zustand eines Gesprächs die Dinge, die der Chat zeigt (Sprechblasen, Werkzeugkarten, Gedanken).
 * Nach `renderChat` in der Oberfläche des Runners (public/app.js), aber als Daten statt DOM.
 */
import { nachrichten } from './gespraech';
import { ergebnisText, eintragZeit, inhaltText, wertText } from './text';
import type { Block, Eintrag, GespraechsZustand, Nachricht, WerkzeugSlot } from './typen';

export type KartenStatus = 'laeuft' | 'fertig' | 'fehler' | 'offen';

export interface WerkzeugKarte {
  id?: string;
  name: string;
  status: KartenStatus;
  eingabe: string;
  ausgabe: string;
  diagnose: string;
  /** Wie lange das Werkzeug lief (ms), wenn der Client Start und Ende gesehen hat. */
  dauerMs?: number | null;
  /** Beginn (ms), solange es läuft: die Oberfläche rechnet die Dauer selbst weiter. */
  seit?: number | null;
}

/** Woher ein Eingang kam: `klasse` „max“ heißt, ein Mensch hat über einen Kanal geschrieben (z. B. Matrix). */
export interface EingangsHerkunft {
  quelle: string;
  von: string;
  klasse: string;
}

export type AnzeigeBlock =
  | { art: 'text'; text: string }
  | { art: 'gedanken'; text: string }
  | { art: 'werkzeug'; karte: WerkzeugKarte };

export type Anzeige =
  | { art: 'mensch'; schluessel: string; text: string; steuern: boolean; zeit: number | null }
  | { art: 'agent'; schluessel: string; name: string; bloecke: AnzeigeBlock[]; zeit: number | null; live: boolean; verbrauch: string }
  | { art: 'system'; schluessel: string; titel: string; text: string; zeit: number | null; eingang?: EingangsHerkunft; lauf?: boolean }
  | { art: 'werkzeug'; schluessel: string; karte: WerkzeugKarte; zeit: number | null }
  | { art: 'arbeitet'; schluessel: string };

export interface AnzeigeOptionen {
  /** Name, unter dem der Agent schreibt (aus /api/health: „agent“ wird „Agent“). */
  agentName?: string;
  jetzt?: number;
}

export function agentAnzeigename(roh: string | null | undefined): string {
  const t = String(roh ?? '').trim();
  if (!t || t === 'agent') return 'Agent';
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function verbrauchText(u: Nachricht['usage']): string {
  if (!u) return '';
  const teile: string[] = [];
  if (u.input) teile.push(`${u.input} ein`);
  if (u.output) teile.push(`${u.output} aus`);
  if (u.cacheRead) teile.push(`${u.cacheRead} cache`);
  return teile.join(' · ');
}

function karteAusSlot(t: WerkzeugSlot | undefined, name: string | undefined, args: unknown, ergebnis: Nachricht | null | undefined): WerkzeugKarte {
  const ausgabe = ergebnis ? ergebnisText(ergebnis) || t?.output || '' : (t?.output ?? '');
  const fehler = !!ergebnis?.isError || t?.status === 'error';
  const status: KartenStatus = fehler ? 'fehler' : t?.status === 'running' ? 'laeuft' : ergebnis || t?.status === 'fertig' ? 'fertig' : 'offen';
  const eingabeWert = args && typeof args === 'object' && Object.keys(args).length ? args : (t?.args ?? {});
  const dauerMs = t?.gestartet && t.beendet ? Math.max(0, t.beendet - t.gestartet) : null;
  return {
    dauerMs,
    seit: status === 'laeuft' ? (t?.gestartet ?? null) : null,
    id: t?.id,
    name: name || t?.name || 'Werkzeug',
    status,
    eingabe: wertText(eingabeWert),
    ausgabe,
    diagnose: t?.diagnostics?.length ? wertText(t.diagnostics) : '',
  };
}

function assistentBloecke(m: Nachricht, z: GespraechsZustand, resultate: Map<string, Nachricht>, gerendert: Set<string>): AnzeigeBlock[] {
  const aus: AnzeigeBlock[] = [];
  const inhalt = Array.isArray(m.content) ? (m.content as Block[]) : typeof m.content === 'string' && m.content ? [{ type: 'text', text: m.content }] : [];
  for (const b of inhalt) {
    if (!b || typeof b !== 'object') continue;
    if (b.type === 'text' && b.text) aus.push({ art: 'text', text: b.text });
    else if (b.type === 'thinking' && b.thinking) aus.push({ art: 'gedanken', text: b.thinking });
    else if (b.type === 'toolCall') {
      const id = b.id;
      if (id) gerendert.add(id);
      aus.push({ art: 'werkzeug', karte: karteAusSlot(id ? z.tools[id] : undefined, b.name, b.arguments, id ? resultate.get(id) : null) });
    }
  }
  return aus;
}

/** Baut die Anzeige-Liste des Chats. */
export function baueAnzeige(z: GespraechsZustand, opt: AnzeigeOptionen = {}): Anzeige[] {
  const name = opt.agentName ?? 'Agent';
  const resultate = new Map<string, Nachricht>();
  const werkzeugAufrufe = new Set<string>();
  const menschenTexte = new Set<string>();
  for (const e of z.entries) {
    if (e.kind === 'fyos.mensch') {
      const t = String(e.data?.text ?? '').trim();
      if (t) menschenTexte.add(t);
    }
    for (const m of nachrichten(e)) {
      if (m?.role === 'toolResult' && m.toolCallId) resultate.set(m.toolCallId, m);
      if (m?.role === 'assistant' && Array.isArray(m.content)) {
        for (const b of m.content as Block[]) if (b?.type === 'toolCall' && b.id) werkzeugAufrufe.add(b.id);
      }
    }
  }

  const aus: Anzeige[] = [];
  const gerendert = new Set<string>();
  z.entries.forEach((e: Eintrag, i) => {
    const kind = String(e.kind ?? '');
    const msgs = nachrichten(e);
    const schl = `e${e.id ?? `i${i}`}`;
    const zeit = eintragZeit(e);

    if (kind === 'fyos.mensch') {
      const text = String(e.data?.text ?? '');
      if (text) aus.push({ art: 'mensch', schluessel: schl, text, steuern: e.data?.art === 'steuern', zeit });
      return;
    }
    if (kind === 'fyos.freigabe-entscheidung') {
      const d = (e.data ?? {}) as { id?: string; entscheidung?: string; notiz?: string };
      aus.push({ art: 'system', schluessel: schl, titel: 'Freigabe', text: `Freigabe ${d.id ?? ''}: ${d.entscheidung ?? 'entschieden'}${d.notiz ? ` · ${d.notiz}` : ''}`, zeit });
      return;
    }
    if (kind === 'fyos.lauf.auftrag') {
      const d = (e.data ?? {}) as { lauf?: string | number; titel?: string };
      aus.push({ art: 'system', schluessel: schl, titel: 'Lauf', text: `Auftrag für Lauf ${d.lauf ?? ''}: ${d.titel ?? ''}`, zeit, lauf: true });
      return;
    }
    if (kind === 'fyos.eingang') {
      const d = (e.data ?? {}) as { quelle?: string; von?: string; klasse?: string; text?: string };
      aus.push({
        art: 'system',
        schluessel: schl,
        titel: `Eingang · ${d.quelle ?? '?'}${d.von && d.von !== d.quelle ? ` · ${d.von}` : ''}`,
        text: String(d.text ?? ''),
        zeit,
        eingang: { quelle: String(d.quelle ?? '?'), von: String(d.von ?? ''), klasse: String(d.klasse ?? '') },
      });
      return;
    }
    if (kind.startsWith('fyos.') && !msgs.length) {
      const text = e.data?.text ?? wertText(e.data ?? e);
      aus.push({ art: 'system', schluessel: schl, titel: kind.replace(/^fyos\./, ''), text: String(text), zeit });
      return;
    }

    msgs.forEach((m, j) => {
      if (!m || typeof m !== 'object') return;
      const s = `${schl}.${j}`;
      if (m.role === 'user') {
        const text = inhaltText(m.content);
        if (text && !menschenTexte.has(text.trim())) {
          aus.push({ art: 'mensch', schluessel: s, text, steuern: false, zeit: m.timestamp ?? zeit });
        }
        return;
      }
      if (m.role === 'assistant') {
        const bloecke = assistentBloecke(m, z, resultate, gerendert);
        aus.push({ art: 'agent', schluessel: s, name, bloecke, zeit: m.timestamp ?? zeit, live: false, verbrauch: verbrauchText(m.usage) });
        return;
      }
      if (m.role === 'toolResult') {
        if (m.toolCallId && werkzeugAufrufe.has(m.toolCallId)) return;
        if (m.toolCallId) gerendert.add(m.toolCallId);
        aus.push({
          art: 'werkzeug',
          schluessel: s,
          karte: karteAusSlot(m.toolCallId ? z.tools[m.toolCallId] : undefined, m.toolName, null, m),
          zeit: m.timestamp ?? zeit,
        });
      }
      // role "system" (Regelwerk) bleibt unsichtbar
    });
  });

  if (z.liveMessage?.role === 'assistant') {
    const bloecke = assistentBloecke(z.liveMessage, z, resultate, gerendert);
    aus.push({ art: 'agent', schluessel: 'live', name, bloecke, zeit: z.liveMessage.timestamp ?? opt.jetzt ?? null, live: true, verbrauch: verbrauchText(z.liveMessage.usage) });
  }

  for (const id of z.toolReihenfolge) {
    const t = z.tools[id];
    if (!t || gerendert.has(t.id)) continue;
    if (t.status !== 'running' && !t.output && !werkzeugAufrufe.has(t.id)) continue;
    aus.push({ art: 'werkzeug', schluessel: `w${t.id}`, karte: karteAusSlot(t, t.name, t.args, null), zeit: null });
  }

  if (z.busy && !z.liveMessage) aus.push({ art: 'arbeitet', schluessel: 'arbeitet' });
  return aus;
}

function gleich(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Behält von der alten Liste jedes Objekt, das sich nicht geändert hat. Eine Oberfläche mit `<For>` baut dann
 * nur die Zeilen neu, die sich ändern (beim Schreiben ist das die letzte), nicht den ganzen Verlauf.
 */
export function stabilisiere(alt: Anzeige[], neu: Anzeige[]): Anzeige[] {
  if (!alt.length) return neu;
  const nachSchluessel = new Map(alt.map((a) => [a.schluessel, a]));
  return neu.map((n) => {
    const a = nachSchluessel.get(n.schluessel);
    return a && gleich(a, n) ? a : n;
  });
}
