/**
 * typen.ts — Formen der Runner-Antworten, wie sie das Client-Protokoll des Runners beschreibt.
 *
 * Bewusst locker: der Runner liefert Sitzungs-Einträge, deren Innenleben sich mit dem Modell ändert.
 * Alles Optionale ist optional, weil der Server es nicht immer setzt; die Logik fragt immer defensiv.
 */

/** Gesprächs-IDs sind Zahlen (in Adressen als Text). */
export type GespraechId = number;

export interface Gespraech {
  id: GespraechId;
  titel: string;
  erstellt?: number;
  arbeitsbereich?: string | null;
  modell?: string | null;
  art: 'root' | 'mensch' | 'zweig' | 'lauf' | string;
  parent?: GespraechId | null;
  archiviert?: boolean;
}

/** Ein Inhaltsblock einer Nachricht. */
export interface Block {
  type: string;
  text?: string;
  thinking?: string;
  id?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  [rest: string]: unknown;
}

export interface Nachricht {
  role: 'user' | 'assistant' | 'toolResult' | 'system' | string;
  content?: string | Block[] | unknown;
  timestamp?: number;
  toolCallId?: string;
  toolName?: string;
  isError?: boolean;
  stopReason?: string;
  usage?: { input?: number; output?: number; cacheRead?: number; [rest: string]: unknown };
  [rest: string]: unknown;
}

/** Sitzungs-Eintrag: `kind` ist `pi.user|pi.assistant|pi.system` oder ein FYOS-Eintrag (`fyos.*`). */
export interface Eintrag {
  id?: number;
  kind?: string;
  data?: Record<string, unknown>;
  model?: Nachricht[] | Nachricht;
  conversationId?: number;
  createdAt?: number;
  [rest: string]: unknown;
}

export type WerkzeugStatus = 'running' | 'fertig' | 'error';

/** Eine laufende oder gelaufene Werkzeugausführung (aus Snapshot und `tool_execution_*`). */
export interface WerkzeugSlot {
  id: string;
  name: string;
  args: Record<string, unknown>;
  output: string;
  details: unknown;
  diagnostics: unknown[];
  status: WerkzeugStatus;
  /** Wann der Client den Start / das Ende gesehen hat (ms); fehlt bei Werkzeugen aus einem Snapshot. */
  gestartet?: number;
  beendet?: number;
}

export interface Verbrauch {
  input?: number;
  output?: number;
  [rest: string]: unknown;
}

/** Zustand eines geöffneten Gesprächs (siehe gespraech.ts). */
export interface GespraechsZustand {
  meta: Record<string, unknown> | null;
  usage: Verbrauch | null;
  agent: unknown;
  entries: Eintrag[];
  /** Die Nachricht, die gerade geschrieben wird (Text-Deltas). */
  liveMessage: Nachricht | null;
  tools: Record<string, WerkzeugSlot>;
  /** Reihenfolge der Werkzeug-IDs, damit lose Karten stabil stehen. */
  toolReihenfolge: string[];
  /** Läuft gerade ein Zug? */
  busy: boolean;
  /** Ist schon ein Snapshot da (sonst zeigt die Fläche „lädt“)? */
  geladen: boolean;
}

/** Eine Meldung, die die Oberfläche kurz zeigt (statt eines Toasts in der Bibliothek). */
export interface Hinweis {
  text: string;
  fehler?: boolean;
}

export type Risiko = 'low' | 'medium' | 'high' | string;

export interface Freigabe {
  id: string;
  conversationId?: number;
  gespraechTitel?: string | null;
  taskId?: number | null;
  aktion?: string | null;
  risiko?: Risiko;
  kontext?: string | null;
  zerstoererisch?: boolean;
  werkzeug?: string | null;
  befehl?: string | null;
  status: 'offen' | 'erteilt' | 'abgelehnt' | string;
  erstellt?: number;
  entschieden?: number | null;
  entschiedenVon?: string | null;
  notiz?: string | null;
}

export interface Lauf {
  id: string;
  titel?: string;
  auftrag?: string;
  quelle?: string;
  erstellt?: number;
  phase?: string;
  status: 'laeuft' | 'abgeschlossen' | 'fehler' | 'abgelehnt' | 'abgebrochen' | string;
  kindId?: GespraechId | null;
  freigabeId?: string | null;
  taskStatus?: string | null;
  outcome?: unknown;
  abgebrochen?: boolean;
  antwort?: string;
  fehler?: string;
  notiz?: string;
}

export interface GeteilterZustand {
  version?: number;
  werte: Record<string, unknown>;
  geaendert?: number | null;
  von?: string | null;
}

export type StromTyp = 'eingang' | 'mensch' | 'sagt' | 'werkzeug' | 'fehler' | 'freigabe' | 'lauf' | 'schritt' | 'fertig' | string;

export interface StromZeile {
  t: number;
  gespraech: GespraechId;
  titel?: string;
  art?: string;
  typ: StromTyp;
  text: string;
  /** Bei `werkzeug`: Name des Werkzeugs. */
  wz?: string;
}

export interface StromGespraech {
  id: GespraechId;
  titel: string;
  art: string;
}

/** Ein Ereignis aus `event: ereignisse` (Stapel von Einträgen). */
export interface GespraechsEreignis {
  type: string;
  [rest: string]: unknown;
}
