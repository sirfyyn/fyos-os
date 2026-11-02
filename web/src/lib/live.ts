import { tr } from '~/lib/i18n';
/**
 * Live-Weg: ein EventSource auf den Bus (/api/smarthome/live), geteilt von allen Flaechen.
 *
 * Ein Dienst hinter der Shell gibt ausgewaehlte Themen des Busses per SSE weiter. Hier haengt genau eine
 * Verbindung pro Tab; sie oeffnet mit dem ersten Abonnenten und schliesst mit dem letzten. Gibt es den Weg
 * nicht (404), schliesst der Browser den Strom selbst und die Flaechen bleiben still.
 */

export interface BusEreignis {
  thema: string;
  id: string;
  ts: string;
  quelle?: string | null;
  daten: Record<string, unknown>;
}

export type LiveZustand = 'aus' | 'verbindet' | 'verbunden' | 'getrennt';

type Hoerer = (e: BusEreignis) => void;

/**
 * Das Ereignis des Hub-Wächters (mcp_hub/plugins/stand.py): „an der Startseite hat sich etwas geändert“. Nutzlast
 * nur `{v, teile: [Namen]}`. Es läuft über einen eigenen Kanal (`hoereStand`) und erscheint in keiner Liste,
 * keinem Puffer und keiner Rauschquote.
 */
export const STAND_THEMA = 'stand.geaendert';

const hoerer = new Set<Hoerer>();
const standHoerer = new Set<Hoerer>();
const zustandsHoerer = new Set<(z: LiveZustand) => void>();
let strom: EventSource | undefined;
let zustand: LiveZustand = 'aus';
/** Die letzten Ereignisse, damit spaet eingehaengte Flaechen nicht leer anfangen. */
const puffer: BusEreignis[] = [];
const PUFFER_MAX = 30;

function setzeZustand(z: LiveZustand): void {
  zustand = z;
  zustandsHoerer.forEach((f) => f(z));
}

function oeffnen(): void {
  if (strom || typeof EventSource === 'undefined') return;
  setzeZustand('verbindet');
  strom = new EventSource('/api/smarthome/live?rueckblick=12', { withCredentials: true });
  strom.onopen = () => setzeZustand('verbunden');
  strom.onerror = () => setzeZustand('getrennt'); // EventSource verbindet selbst neu
  strom.addEventListener('bus', (m) => {
    let e: BusEreignis;
    try {
      e = JSON.parse((m as MessageEvent).data);
    } catch {
      return;
    }
    if (e.thema === STAND_THEMA) {
      setzeZustand('verbunden');
      standHoerer.forEach((f) => f(e));
      return;
    }
    if (!nimmAuf(e)) return;
    setzeZustand('verbunden');
    hoerer.forEach((f) => f(e));
  });
}

// ── Rauschquote ─────────────────────────────────────────────────────────────

/**
 * Roh-Ereignisse gegen angezeigte Zeilen (Sitzung, je Tab). Eine Zeile entsteht, wenn ein
 * Ereignis nicht in das Bündel des vorigen Ereignisses fällt. Was das Backend entprellt
 * (LIVE_ENTPRELL_S), kommt hier gar nicht an — die Kennzahl misst den Rest.
 */
let rohZahl = 0;
let zeilenZahl = 0;

/** Kennzahl „angezeigte Zeilen je 100 Roh-Ereignisse" (kleiner = ruhiger). */
export function rauschquote(): { roh: number; zeilen: number; je100: number | undefined } {
  return {
    roh: rohZahl,
    zeilen: zeilenZahl,
    je100: rohZahl > 0 ? Math.round((zeilenZahl / rohZahl) * 1000) / 10 : undefined,
  };
}

/** Nimmt ein Ereignis in Puffer und Zähler auf; false, wenn es schon bekannt war. */
export function nimmAuf(e: BusEreignis): boolean {
  if (istRauschen(e)) return false;
  if (puffer.some((p) => p.id === e.id && p.thema === e.thema)) return false;
  rohZahl += 1;
  const vorher = puffer[puffer.length - 1];
  if (!vorher || buendelSchluessel(vorher) !== buendelSchluessel(e)) zeilenZahl += 1;
  puffer.push(e);
  if (puffer.length > PUFFER_MAX) puffer.shift();
  return true;
}

/** Nur für Tests. */
export function setzeZurueck(): void {
  puffer.length = 0;
  rohZahl = 0;
  zeilenZahl = 0;
}

function schliessen(): void {
  strom?.close();
  strom = undefined;
  setzeZustand('aus');
}

/** Abonniert den Bus. Rueckgabe beendet das Abo. Bereits Gepuffertes kommt sofort. */
export function hoere(f: Hoerer): () => void {
  hoerer.add(f);
  puffer.forEach(f);
  oeffnen();
  return () => {
    hoerer.delete(f);
    if (hoerer.size === 0 && standHoerer.size === 0) schliessen();
  };
}

/** Abonniert nur „an der Startseite hat sich etwas geändert“ (kein Puffer, keine Anzeige). Hält den Strom offen. */
export function hoereStand(f: Hoerer): () => void {
  standHoerer.add(f);
  oeffnen();
  return () => {
    standHoerer.delete(f);
    if (hoerer.size === 0 && standHoerer.size === 0) schliessen();
  };
}

export function hoereZustand(f: (z: LiveZustand) => void): () => void {
  zustandsHoerer.add(f);
  f(zustand);
  return () => zustandsHoerer.delete(f);
}

// ── Darstellung ─────────────────────────────────────────────────────────────

const ZUSTAND_DE: Record<string, string> = {
  on: 'an',
  off: 'aus',
  open: 'offen',
  opening: 'öffnet',
  closed: 'zu',
  closing: 'schließt',
  locked: 'verriegelt',
  unlocked: 'entriegelt',
  playing: 'spielt',
  paused: 'pausiert',
  idle: 'bereit',
  standby: 'Standby',
  heat: 'heizt',
  cool: 'kühlt',
  auto: 'automatisch',
  dry: 'entfeuchtet',
  fan_only: 'lüftet',
  cleaning: 'saugt',
  docked: 'in der Station',
  returning: 'fährt zurück',
  unavailable: 'nicht erreichbar',
  unknown: 'unbekannt',
};

/** Modus-Kategorie (lib/modus.ts) je Thema — was im Demo- oder Arbeitsmodus verschwindet. */
export function kategorieFuer(thema: string): string | undefined {
  if (thema.startsWith('haus.') || thema.startsWith('smarthome.')) return 'haus';
  if (thema.startsWith('camera.')) return 'video';
  if (thema.startsWith('life.')) return 'aufgaben';
  if (thema.startsWith('calendar.')) return 'termine';
  if (thema.startsWith('dms.')) return 'dokumente';
  if (thema.startsWith('finance.')) return 'finanzen';
  if (thema.startsWith('decision.') || thema.startsWith('freigabe.')) return 'privat';
  return undefined;
}

const THEMA_DE: Record<string, string> = {
  'grow.alert': 'Grow',
  'energy.alert': 'Energie',
  'cluster.degraded': 'Cluster eingeschränkt',
  'cluster.recovered': 'Cluster wieder gesund',
  'node.critical': 'Knoten kritisch',
  'services.service_down': 'Dienst ausgefallen',
  'services.service_recovered': 'Dienst wieder da',
  'freigabe.angefragt': 'Freigabe angefragt',
  'decision.created': 'Neue Entscheidung',
  'life.task_created': 'Neue Aufgabe',
  'life.task_completed': 'Aufgabe erledigt',
  'calendar.event_created': 'Neuer Termin',
  'dms.document_added': 'Neues Dokument',
  'camera.detection': 'Kamera',
  'smarthome.entity_toggled': 'Umgeschaltet',
  'decision.resolved': 'Entscheidung getroffen',
  'freigabe.erteilt': 'Freigabe erteilt',
  'freigabe.abgelehnt': 'Freigabe abgelehnt',
  'finance.transactions_ingested': 'Umsätze importiert',
  'wiki.page_created': 'Neue Wiki-Seite',
  'llm.availability.degraded': 'Modell ausgefallen',
  'llm.availability.recovered': 'Modell erreichbar',
  'werkstatt.lauf': 'Werkstatt',
  'steuerpult.aktion': 'Steuerpult',
  'modell.umgeschaltet': 'Modell umgeschaltet',
};

/**
 * Darstellung: `warn` nur für echte Störungen. Ein Modell-Ausfall ist `info` — bei offenem
 * Dev-Fenster ist er erwartet (nicht hervorheben).
 */
export function ton(e: BusEreignis): 'warn' | 'info' | 'normal' {
  if (e.thema.startsWith('llm.availability.')) return 'info';
  if (['node.critical', 'services.service_down', 'cluster.degraded', 'freigabe.abgelehnt'].includes(e.thema))
    return 'warn';
  return 'normal';
}

function text(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim() ? v.trim() : undefined;
}

const EINSTELLUNG = /(_can_|erkennung|detect|motion|recording|snapshot|review|audio|bark|occupancy|presence|trigger|people|person|vehicle)/i;
const EINSTELLUNG_DOMAENEN = new Set(['switch', 'number', 'select', 'button', 'text', 'update', 'sensor']);

/** Kamera-/Geräteeinstellungen, die nie Neuigkeiten sind (Frigate-Schalter, Zähler, Firmware). */
export function istRauschen(e: BusEreignis): boolean {
  if (e.thema !== 'haus.zustand') return false;
  const id = String(e.daten?.entity_id ?? '');
  const dom = id.split('.', 1)[0] ?? '';
  return EINSTELLUNG_DOMAENEN.has(dom) || EINSTELLUNG.test(id) || EINSTELLUNG.test(String(e.daten?.name ?? ''));
}

/** Eine Zeile Text für ein Ereignis. */
export function beschreibe(e: BusEreignis): { titel: string; detail?: string } {
  const d = e.daten ?? {};
  if (e.thema === 'haus.zustand') {
    const nach = String(d.nach ?? '');
    return { titel: text(d.name) ?? String(d.entity_id ?? ''), detail: ZUSTAND_DE[nach] ? tr(ZUSTAND_DE[nach]) : nach };
  }
  if (e.thema === 'camera.detection') {
    return {
      titel: tr('Kamera'),
      detail: [text(d.label), text(d.camera)].filter(Boolean).join(' · ') || undefined,
    };
  }
  if (e.thema === 'werkstatt.lauf') {
    const wer = text(d.wer);
    const rc = typeof d.rc === 'number' ? `rc ${d.rc}` : undefined;
    return {
      titel: tr('Werkstatt: {0}', text(d.id) ?? tr('Skript')) + (wer ? ` (${wer})` : ''),
      detail: [d.trocken ? tr('Trockenlauf') : undefined, rc].filter(Boolean).join(' · ') || undefined,
    };
  }
  if (e.thema.startsWith('llm.availability.')) {
    return { titel: tr(THEMA_DE[e.thema]!), detail: text(d.primary) };
  }
  if (e.thema === 'finance.transactions_ingested' && typeof d.transactions === 'number') {
    return { titel: tr(THEMA_DE[e.thema]!), detail: tr('{0} Buchungen', d.transactions) };
  }
  if (e.thema === 'decision.resolved') {
    const opt = text(d.resolved_option);
    return { titel: tr(THEMA_DE[e.thema]!), detail: [text(d.title), opt ? `→ ${opt}` : undefined].filter(Boolean).join(' ') || undefined };
  }
  const de = THEMA_DE[e.thema];
  const titel = de ? tr(de) : e.thema;
  const inhalt =
    text(d.title) ??
    text(d.titel) ??
    text(d.name) ??
    text(d.node) ??
    text(d.entity_id) ??
    text(d.message)?.split('\n').slice(-1)[0];
  return { titel, detail: inhalt ? inhalt.slice(0, 140) : undefined };
}

/** Ein Bündel aufeinanderfolgender Ereignisse desselben Geräts bzw. Titels. */
export interface Buendel {
  /** Das jüngste Ereignis des Bündels (Zeit, Titel, Detail). */
  e: BusEreignis;
  anzahl: number;
}

export function buendelSchluessel(e: BusEreignis): string {
  const id = e.daten?.entity_id;
  return `${e.thema}|${typeof id === 'string' && id ? id : beschreibe(e).titel}`;
}

/**
 * Bündelt AUFEINANDERFOLGENDE Ereignisse desselben entity_id/Titels (UI-Audit 30.09.2026:
 * Attributwechsel einer Kamera füllten 6 von 8 Zeilen „Esszimmer Can …"). Eingabe neueste
 * zuerst; jedes Bündel trägt das jüngste Ereignis und die Anzahl.
 */
export function buendle(ereignisse: BusEreignis[], max = Infinity): Buendel[] {
  const aus: Buendel[] = [];
  let letzter = '';
  for (const e of ereignisse) {
    const k = buendelSchluessel(e);
    const oben = aus[aus.length - 1];
    if (oben && k === letzter) {
      oben.anzahl += 1;
      continue;
    }
    if (aus.length >= max) break;
    aus.push({ e, anzahl: 1 });
    letzter = k;
  }
  return aus;
}

/**
 * Gruppiert nach Gerät/Thema über die GANZE Liste (nicht nur Nachbarn): Flattern zwischen
 * zwei Geräten bleibt so je eine Zeile. Reihenfolge = jüngstes Ereignis je Gruppe zuerst.
 */
export function gruppiere(ereignisse: BusEreignis[]): Buendel[] {
  const nach = new Map<string, Buendel>();
  for (const e of ereignisse) {
    const k = buendelSchluessel(e);
    const b = nach.get(k);
    if (b) b.anzahl += 1;
    else nach.set(k, { e, anzahl: 1 });
  }
  return [...nach.values()];
}

// ── Entscheidungen direkt in der Leiste ─────────────────────────────────────

/** Diese Optionen verlangen eine zweite Bestätigung. */
const NEGATIV = new Set(['nein', 'ignorieren', 'drop', 'löschen', 'loeschen', 'ablehnen', 'verwerfen']);
export const istNegativ = (option: string): boolean => NEGATIV.has(option.trim().toLowerCase());

/** Optionen einer `decision.created`-Meldung (Zeichenketten oder {label|value}); sonst leer. */
export function optionenVon(e: BusEreignis): string[] {
  if (e.thema !== 'decision.created') return [];
  const o = e.daten?.options ?? e.daten?.optionen;
  if (!Array.isArray(o)) return [];
  return o
    .map((x) => (typeof x === 'string' ? x : text((x as Record<string, unknown>)?.label) ?? text((x as Record<string, unknown>)?.value)))
    .filter((x): x is string => !!x);
}

export const entscheidungsId = (e: BusEreignis): string | undefined => text(e.daten?.id);

/** Ids, zu denen der Puffer schon ein `decision.resolved` kennt. */
export function erledigteIds(ereignisse: BusEreignis[]): Set<string> {
  const ids = new Set<string>();
  for (const e of ereignisse) if (e.thema === 'decision.resolved') {
    const id = entscheidungsId(e);
    if (id) ids.add(id);
  }
  return ids;
}

/**
 * Die Aktion, die AttentionInbox/syl-bridge für dieselbe Option bauen: PATCH auf den
 * Decisions-Dienst. Keine eigene Berechtigung — die Sitzung des Browsers entscheidet.
 */
export function entscheidungsAktion(id: string, option: string) {
  return {
    label: option,
    method: 'PATCH',
    endpoint: `/api/decisions/${encodeURIComponent(id)}`,
    body: { status: 'resolved', resolved_option: option },
  };
}

const offenCache = new Map<string, boolean>();

/**
 * Ist die Entscheidung noch offen? Der Puffer ist kurz; ein älteres `decision.resolved`
 * kann herausgefallen sein. 404 und „resolved" → false, bei Fehlern bleibt sie offen
 * (der Klick meldet dann selbst den Fehler).
 */
export async function entscheidungOffen(id: string): Promise<boolean> {
  const c = offenCache.get(id);
  if (c !== undefined) return c;
  try {
    const r = await fetch(`/api/decisions/${encodeURIComponent(id)}`, { credentials: 'include' });
    if (r.status === 404) return false;
    if (!r.ok) return true;
    const offen = (await r.json())?.status === 'pending';
    offenCache.set(id, offen);
    return offen;
  } catch {
    return true;
  }
}
