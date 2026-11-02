/**
 * gespraech.ts — der Reducer eines Gesprächs: Ansicht und Snapshot setzen den Stand, Stapel von Ereignissen
 * (`event: ereignisse`) verändern ihn. Nachgebaut nach der Oberfläche des Runners (public/app.js)
 * (`starteGespraechsSse`, `verarbeiteEreignisse`), ohne DOM.
 *
 * Alle Funktionen geben einen NEUEN Zustand zurück (oberste Ebene kopiert), der alte bleibt unverändert —
 * so kann eine Oberfläche mit Signalen darüber liegen.
 */
import type { Block, Eintrag, GespraechsEreignis, GespraechsZustand, Hinweis, Nachricht, WerkzeugSlot } from './typen';
import { ergebnisText, inhaltText } from './text';

/** Mehr Einträge hält der Client nicht im Speicher (app.js: 5000). */
export const EINTRAEGE_MAX = 5000;

export function leerGespraech(): GespraechsZustand {
  return {
    meta: null,
    usage: null,
    agent: null,
    entries: [],
    liveMessage: null,
    tools: {},
    toolReihenfolge: [],
    busy: false,
    geladen: false,
  };
}

function kopie<T>(wert: T): T {
  if (typeof structuredClone === 'function') return structuredClone(wert);
  return JSON.parse(JSON.stringify(wert)) as T;
}

/** Nachrichten eines Eintrags als Liste (der Runner liefert eine Liste oder eine einzelne). */
export function nachrichten(e: Eintrag): Nachricht[] {
  if (Array.isArray(e.model)) return e.model;
  return e.model ? [e.model] : [];
}

function flach(z: GespraechsZustand): GespraechsZustand {
  return { ...z, entries: z.entries.slice(), tools: { ...z.tools }, toolReihenfolge: z.toolReihenfolge.slice() };
}

function setzeWerkzeug(z: GespraechsZustand, slot: WerkzeugSlot): void {
  if (!z.tools[slot.id]) z.toolReihenfolge.push(slot.id);
  z.tools[slot.id] = slot;
}

function aendereWerkzeug(z: GespraechsZustand, id: string, f: (t: WerkzeugSlot) => void): void {
  const alt = z.tools[id];
  if (!alt) return;
  const neu: WerkzeugSlot = { ...alt };
  f(neu);
  z.tools[id] = neu;
}

function fuegeEintragHinzu(z: GespraechsZustand, eintrag: Eintrag | undefined): void {
  if (!eintrag) return;
  if (eintrag.id !== undefined && z.entries.some((e) => e.id === eintrag.id)) return;
  z.entries.push(eintrag);
  if (z.entries.length > EINTRAEGE_MAX) z.entries.splice(0, z.entries.length - EINTRAEGE_MAX);
}

/** Der bisherige Verlauf (`GET …/ansicht`), bevor der Strom antwortet. */
export function mitAnsicht(
  alt: GespraechsZustand,
  a: { meta?: Record<string, unknown> | null; usage?: GespraechsZustand['usage']; entries?: Eintrag[] },
): GespraechsZustand {
  return {
    ...alt,
    meta: a.meta ?? alt.meta,
    usage: a.usage ?? alt.usage,
    entries: Array.isArray(a.entries) ? a.entries.slice(-EINTRAEGE_MAX) : alt.entries,
    geladen: true,
  };
}

interface Snapshot {
  entries?: Eintrag[];
  generation?: { message?: Nachricht } | null;
  run?: unknown;
  tools?: SnapshotWerkzeug[];
  nestedTools?: SnapshotWerkzeug[];
  agent?: unknown;
  usage?: GespraechsZustand['usage'];
}
interface SnapshotWerkzeug {
  callId?: string;
  taskId?: string | number;
  name?: string;
  arguments?: Record<string, unknown>;
  output?: unknown;
  details?: unknown;
  diagnostics?: unknown[];
  status?: string;
}

/** Der erste Stand aus dem Strom (`event: snapshot`): ersetzt Einträge, laufende Nachricht und Werkzeuge. */
export function mitSnapshot(alt: GespraechsZustand, s: Snapshot): GespraechsZustand {
  const z: GespraechsZustand = {
    ...alt,
    entries: Array.isArray(s.entries) ? s.entries.slice(-EINTRAEGE_MAX) : [],
    liveMessage: s.generation?.message ? kopie(s.generation.message) : null,
    busy: !!s.run || !!s.generation,
    tools: {},
    toolReihenfolge: [],
    agent: s.agent ?? alt.agent,
    usage: s.usage ?? alt.usage,
    geladen: true,
  };
  for (const slot of [...(s.tools ?? []), ...(s.nestedTools ?? [])]) {
    const id = slot.callId ?? slot.taskId;
    if (id === undefined || id === null || id === '') continue;
    setzeWerkzeug(z, {
      id: String(id),
      name: slot.name ?? 'Werkzeug',
      args: slot.arguments ?? {},
      output: typeof slot.output === 'string' ? slot.output : '',
      details: slot.details ?? null,
      diagnostics: slot.diagnostics ?? [],
      status: slot.status === 'done' ? 'fertig' : 'running',
    });
  }
  return z;
}

export interface EreignisErgebnis {
  zustand: GespraechsZustand;
  /** Kurze Meldungen für den Nutzer (Freigabe entschieden, Aufgabe fehlgeschlagen …). */
  hinweise: Hinweis[];
  /** Ein Zug oder Lauf ist zu Ende: die Oberfläche kann Liste und Zahlen auffrischen. */
  fertig: boolean;
  /** Es hat sich etwas geändert, das sich zu zeichnen lohnt. */
  neu: boolean;
}

function wendeBlockAenderungen(msg: Nachricht, aenderungen: Array<Record<string, unknown>>): Nachricht {
  let m = msg;
  for (const a of aenderungen) {
    const typ = a.type;
    if (typ === 'message') {
      m = kopie(a.message as Nachricht);
      continue;
    }
    const idx = Number(a.contentIndex);
    if (typ === 'text_start' || typ === 'thinking_start' || typ === 'toolcall_start') {
      const inhalt: Block[] = Array.isArray(m.content) ? (m.content as Block[]).slice() : [];
      if (typ === 'text_start') inhalt[idx] = { type: 'text', text: '' };
      else if (typ === 'thinking_start') inhalt[idx] = { type: 'thinking', thinking: '' };
      else {
        const b = (a.block ?? {}) as { id?: string; name?: string; arguments?: Record<string, unknown> };
        inhalt[idx] = { type: 'toolCall', id: b.id, name: b.name, arguments: b.arguments ?? {} };
      }
      m = { ...m, content: inhalt };
      continue;
    }
    if (typ === 'text_delta' || typ === 'thinking_delta') {
      const inhalt = Array.isArray(m.content) ? (m.content as Block[]).slice() : [];
      const block = inhalt[idx];
      if (!block) continue;
      const delta = String(a.delta ?? '');
      inhalt[idx] =
        typ === 'text_delta'
          ? { ...block, text: String(block.text ?? '') + delta }
          : { ...block, thinking: String(block.thinking ?? '') + delta };
      m = { ...m, content: inhalt };
      continue;
    }
    if (typ === 'block') {
      const inhalt: Block[] = Array.isArray(m.content) ? (m.content as Block[]).slice() : [];
      inhalt[idx] = a.block as Block;
      m = { ...m, content: inhalt };
    }
  }
  return m;
}

/** Ergebnis einer Werkzeugnachricht in die Karte schreiben. */
function werkzeugErgebnis(z: GespraechsZustand, m: Nachricht): void {
  const id = m.toolCallId;
  if (!id) return;
  aendereWerkzeug(z, id, (t) => {
    t.output = inhaltText(m.content);
    t.status = m.isError ? 'error' : 'fertig';
    t.beendet ??= Date.now();
  });
}

/** Einen Stapel Ereignisse anwenden (`event: ereignisse`). */
export function mitEreignissen(alt: GespraechsZustand, ereignisse: GespraechsEreignis[]): EreignisErgebnis {
  const z = flach(alt);
  const hinweise: Hinweis[] = [];
  let neu = false;
  let fertig = false;

  for (const ev of ereignisse) {
    switch (ev.type) {
      case 'message_start': {
        const m = ev.message as Nachricht | undefined;
        if (m?.role === 'assistant') {
          z.liveMessage = kopie(m);
          neu = true;
        } else if (m?.role === 'toolResult' && m.toolCallId) {
          werkzeugErgebnis(z, m);
        }
        break;
      }
      case 'message_update': {
        if (!z.liveMessage) break;
        z.liveMessage = wendeBlockAenderungen(z.liveMessage, (ev.changes as Array<Record<string, unknown>> | undefined) ?? []);
        if (ev.usage) z.liveMessage = { ...z.liveMessage, usage: ev.usage as Nachricht['usage'] };
        neu = true;
        break;
      }
      case 'message_end': {
        const eintrag = ev.entry as Eintrag | undefined;
        if (!eintrag) break;
        fuegeEintragHinzu(z, eintrag);
        const m = nachrichten(eintrag)[0];
        if (m?.role === 'assistant') z.liveMessage = null;
        if (m?.role === 'toolResult' && m.toolCallId) werkzeugErgebnis(z, m);
        neu = true;
        break;
      }
      case 'entry_appended': {
        const eintrag = ev.entry as Eintrag | undefined;
        if (!eintrag) break;
        fuegeEintragHinzu(z, eintrag);
        neu = true;
        if (eintrag.kind === 'fyos.freigabe-entscheidung') {
          const d = (eintrag.data ?? {}) as { entscheidung?: string };
          hinweise.push({ text: `Freigabe ${d.entscheidung ?? 'entschieden'}.` });
        }
        break;
      }
      case 'tool_execution_start': {
        const id = ev.toolCallId ?? ev.taskId;
        if (id === undefined || id === null || id === '') break;
        setzeWerkzeug(z, {
          id: String(id),
          name: (ev.toolName as string | undefined) ?? 'Werkzeug',
          args: (ev.args as Record<string, unknown> | undefined) ?? {},
          output: '',
          details: null,
          diagnostics: [],
          status: 'running',
          gestartet: Date.now(),
        });
        neu = true;
        break;
      }
      case 'tool_execution_update': {
        const id = String(ev.toolCallId ?? ev.taskId ?? '');
        if (!z.tools[id]) break;
        aendereWerkzeug(z, id, (t) => {
          const o = ev.output as { set?: unknown; trimStart?: unknown; append?: unknown } | undefined;
          if (o) {
            if (typeof o.set === 'string') t.output = o.set;
            else {
              if (Number(o.trimStart) > 0) t.output = t.output.slice(Number(o.trimStart));
              if (typeof o.append === 'string') t.output += o.append;
            }
          }
          if (ev.details !== undefined) t.details = ev.details;
          if (Array.isArray(ev.diagnostics)) t.diagnostics = ev.diagnostics;
        });
        neu = true;
        break;
      }
      case 'tool_execution_end': {
        const id = String(ev.toolCallId ?? ev.taskId ?? '');
        if (!z.tools[id]) {
          neu = true;
          break;
        }
        aendereWerkzeug(z, id, (t) => {
          t.status = 'fertig';
          t.beendet ??= Date.now();
          if (ev.result !== undefined) {
            t.output = ergebnisText(ev.result);
            if ((ev.result as { isError?: boolean } | null)?.isError) t.status = 'error';
          }
          const m = ev.entry ? nachrichten(ev.entry as Eintrag)[0] : undefined;
          if (m?.role === 'toolResult') {
            t.output = inhaltText(m.content);
            t.status = m.isError ? 'error' : 'fertig';
          }
        });
        neu = true;
        break;
      }
      case 'turn_start':
      case 'run_start':
        z.busy = true;
        break;
      case 'turn_end':
        z.busy = false;
        if (z.liveMessage?.stopReason && z.liveMessage.stopReason !== 'pending') z.liveMessage = null;
        fertig = true;
        neu = true;
        break;
      case 'run_end':
        z.busy = false;
        fertig = true;
        neu = true;
        break;
      case 'submission':
        neu = true;
        break;
      case 'task_failed':
        hinweise.push({ text: `Aufgabe fehlgeschlagen: ${(ev.message as string | undefined) ?? (ev.kind as string | undefined) ?? ''}`.trim(), fehler: true });
        break;
      case 'auto_retry_start':
        hinweise.push({ text: `Modell antwortet nicht; neuer Versuch ${(ev.attempt as number | undefined) ?? ''}.`.trim() });
        break;
      case 'compaction_start':
        hinweise.push({ text: 'Verdichte Verlauf …' });
        break;
      case 'compaction_end':
        if (ev.error) {
          const e = ev.error as { message?: string } | string;
          hinweise.push({ text: `Verdichten fehlgeschlagen: ${typeof e === 'string' ? e : (e.message ?? '')}`, fehler: true });
        }
        break;
      case 'agent_changed':
        z.agent = ev.agent;
        break;
      case 'usage_changed':
        z.usage = ev.usage as GespraechsZustand['usage'];
        break;
      default:
        break;
    }
  }
  return { zustand: z, hinweise, fertig, neu };
}
