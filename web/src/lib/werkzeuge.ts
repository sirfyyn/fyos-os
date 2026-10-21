/**
 * werkzeuge.ts — das Werkzeug-Register der offenen Seite.
 *
 * Leitbild „eine Fähigkeit, alle Flächen": Agenten sollen FYOS OS bedienen und der Benutzer etwas
 * ZEIGEN können — ohne Screenshots und Klickpfade. Jede Pane meldet ihre Werkzeuge hier an
 * (`registriereWerkzeuge`), beim Seitenwechsel verschwinden sie wieder.
 *
 * EINE Liste, drei Wege nach aussen:
 *   window.fyos.werkzeuge  — heute nutzbar, z. B. von mcp-playwright im Cluster:
 *                            `await fyos.werkzeuge.rufen('zeige_lauf', { lauf: 'x' })`
 *   WebMCP                 — `document.modelContext`, sobald der Browser es kann (Chrome ab 150; lokal
 *                            `chrome://flags/#enable-webmcp-testing`). Ältere Chrome und Polyfills haben es
 *                            noch als `navigator.modelContext`; dort wird zurückgegriffen, wenn
 *                            `document.modelContext` fehlt. Angemeldet wird nur mit
 *                            `registerTool(werkzeug, { signal })`, abgemeldet über das `signal` — je Werkzeug
 *                            ein AbortController. `provideContext`, `unregisterTool` und `clearContext`
 *                            gibt es dort nicht mehr und werden nie aufgerufen. Der Abgleich wirft nie.
 *   OS-Brücke              — das offene /os meldet diese Liste dem Hub (`fuerBruecke`), der Agent ruft
 *                            sie über `os.ausfuehren` (`rufenFuerBruecke`, lib/os/bruecke.ts).
 *                            `bruecke: false` hält ein Werkzeug aus der Brücke heraus (die aus dem
 *                            Hub abgeleiteten App-Werkzeuge: der Agent hat sie direkt im Hub).
 *
 * Apps in OS-Fenstern (iframes) melden eigene Werkzeuge über `App.werkzeug(name, beschreibung, schema, fn)` an; der
 * Host trägt sie mit dem Präfix ihres Plugins hier ein und beim Schließen des Fensters wieder aus
 * (lib/mcp-apps/app-werkzeuge.ts). Sie tragen `fenster` und `app`, damit `os.lage` sie dem Fenster zuordnet.
 *
 * Werkzeuge liefern MCP-Ergebnisse ({content, isError}); `window.fyos.werkzeuge` und die Brücke geben sie so weiter,
 * WebMCP bekommt die Nutzdaten ohne Hülle (`fuerWebmcp`). `lesend` setzt readOnlyHint.
 * Nachsehen im Browser: `fyos.werkzeuge.webmcp()` sagt, über welchen Kontext was angemeldet ist.
 */

export type WerkzeugErgebnis = { content: { type: 'text'; text: string }[]; isError?: boolean; structuredContent?: unknown };

export interface Werkzeug {
  name: string;
  beschreibung: string;
  eingabe?: Record<string, unknown>;
  lesend?: boolean;
  /** Über die OS-Brücke für den Agenten freigeben (Vorgabe: ja) */
  bruecke?: boolean;
  /** Werkzeug einer App in einem OS-Fenster (lib/mcp-apps/app-werkzeuge.ts): ID des Fensters (= Fläche) */
  fenster?: string;
  /** … und das Plugin der App (Präfix des Namens) */
  app?: string;
  ausfuehren: (args: Record<string, unknown>) => Promise<WerkzeugErgebnis | unknown>;
}

/** Ein Werkzeug im Meldeformat der OS-Brücke (POST /hub-api/os/melden → werkzeuge[]). */
export interface BrueckeWerkzeug {
  name: string;
  /** höchstens 300 Zeichen */
  beschreibung: string;
  /** JSON-Schema der Eingabe; fehlt, wenn es größer als 2 KB wäre */
  eingabe?: Record<string, unknown>;
  lesend: boolean;
  /** nur bei App-Werkzeugen: das Fenster, in dem die App läuft, und ihr Plugin (`os.lage` ordnet sie dem Fenster zu) */
  fenster?: string;
  app?: string;
}

export const BRUECKE_MAX_WERKZEUGE = 64;
export const BRUECKE_MAX_BESCHREIBUNG = 300;
export const BRUECKE_MAX_SCHEMA_BYTES = 2048;

/** WebMCP, wie Chrome es seit 150 zeigt: Werkzeuge nur über `registerTool(werkzeug, { signal })`, abmelden per Abbruch. */
type ModelContext = {
  registerTool?: (werkzeug: unknown, optionen?: { signal?: AbortSignal }) => unknown;
};

const register = new Map<string, Werkzeug>();
/** Was bei WebMCP angemeldet ist: Name → (Werkzeug, Abbruch). Der AbortController meldet genau dieses Werkzeug wieder ab. */
const bei = new Map<string, { w: Werkzeug; stopp: AbortController }>();

export const ergebnis = (daten: unknown): WerkzeugErgebnis => ({
  content: [{ type: 'text', text: typeof daten === 'string' ? daten : JSON.stringify(daten) }],
  structuredContent: typeof daten === 'object' && daten !== null ? daten : undefined,
});
export const fehler = (text: string): WerkzeugErgebnis => ({ content: [{ type: 'text', text }], isError: true });

const schemaVon = (w: Werkzeug): Record<string, unknown> => ({ type: 'object', properties: {}, ...(w.eingabe ?? {}) });

/**
 * Was ein WebMCP-Agent bekommt: die Nutzdaten statt der MCP-Hülle. Chrome macht aus dem Rückgabewert JSON-Text,
 * wertet `isError` nicht aus und meldet bei einem Wurf nur „invocation failed“ ohne den Grund (Chrome 154 mit
 * `--enable-features=WebMCP` gemessen). Die Hülle hieße: alles doppelt (Text und structuredContent) und ein Fehler,
 * der wie Erfolg aussieht. Ein Fehler geht deshalb als `{ fehler: <Text> }` zurück — der Agent liest den Grund.
 */
function fuerWebmcp(r: WerkzeugErgebnis): unknown {
  const text = (r.content ?? [])
    .map((c) => c.text)
    .filter(Boolean)
    .join('\n');
  if (r.isError) return { fehler: text || 'Das Werkzeug ist fehlgeschlagen.' };
  return r.structuredContent ?? text;
}

function alsMcp(w: Werkzeug) {
  return {
    name: w.name,
    description: w.beschreibung.trim() || w.name, // Chrome lehnt eine leere Beschreibung ab
    inputSchema: schemaVon(w),
    annotations: { readOnlyHint: !!w.lesend },
    execute: async (args: Record<string, unknown>) => fuerWebmcp(await rufen(w.name, args ?? {})),
  };
}

type KontextArt = 'document' | 'navigator';

/**
 * Der WebMCP-Kontext des Browsers. Chrome führt `navigator.modelContext` seit 150 als veraltet; die Schnittstelle
 * heißt jetzt `document.modelContext`. Zuerst dieser, dann — ältere Chrome, Polyfills — jener. Ein Kontext ohne
 * `registerTool` zählt nicht, ein Zugriff, der wirft, auch nicht. Der veraltete Weg wird nur angefasst, wenn der
 * neue fehlt (sonst gäbe Chrome dafür eine Warnung aus).
 */
function modelContext(): { mc: ModelContext; art: KontextArt } | undefined {
  const quellen: { art: KontextArt; lesen: () => unknown }[] = [
    { art: 'document', lesen: () => (typeof document === 'undefined' ? undefined : (document as Document & { modelContext?: unknown }).modelContext) },
    { art: 'navigator', lesen: () => (typeof navigator === 'undefined' ? undefined : (navigator as Navigator & { modelContext?: unknown }).modelContext) },
  ];
  for (const q of quellen) {
    try {
      const mc = q.lesen() as ModelContext | null | undefined;
      if (mc && (typeof mc === 'object' || typeof mc === 'function') && typeof mc.registerTool === 'function') return { mc, art: q.art };
    } catch {
      /* WebMCP ist Vorschau — ein Fehler dort darf die Seite nicht stören */
    }
  }
  return undefined;
}

/**
 * Ein Aufruf an WebMCP, der nie wirft. `registerTool` darf ein Versprechen liefern (Chrome: `await registerTool(…)`);
 * wird es abgelehnt, bleibt das unbemerkt und `beiAblehnung` läuft.
 */
function versuche<T>(f: () => T, beiAblehnung?: () => void): { ok: true; wert: T } | { ok: false } {
  try {
    const wert = f();
    if (wert && typeof (wert as { then?: unknown }).then === 'function') {
      try {
        (wert as unknown as Promise<unknown>).then(undefined, () => versuche(() => beiAblehnung?.()));
      } catch {
        /* ein Versprechen, das sich nicht abfragen lässt */
      }
    }
    return { ok: true, wert };
  } catch {
    return { ok: false };
  }
}

/** Ein Werkzeug bei WebMCP abmelden: sein Abbruch auslösen. */
function webmcpAbmelden(name: string): void {
  const a = bei.get(name);
  bei.delete(name);
  if (a) versuche(() => a.stopp.abort());
}

/** Der Kontext, an dem `bei` hängt: wechselt er (der neue Weg erscheint, ein Polyfill kommt später), beginnt die Anmeldung dort von vorn. */
let angemeldetBei: ModelContext | undefined;

/**
 * WebMCP an das Register angleichen: jedes Werkzeug einzeln mit `registerTool(werkzeug, { signal })` anmelden, ein
 * entferntes oder ersetztes über sein `signal` abmelden (erst abmelden, dann neu anmelden). Scheitert eine Anmeldung
 * (Ausnahme, abgelehntes Versprechen, Name vergeben), gilt das Werkzeug als nicht angemeldet; der nächste Abgleich
 * versucht es noch einmal. Ohne `document.modelContext` und ohne `navigator.modelContext` passiert nichts. Wirft nie.
 */
export function webmcpAbgleichen(): void {
  try {
    const k = modelContext();
    const mc = k?.mc;
    if (angemeldetBei !== mc) {
      for (const name of [...bei.keys()]) webmcpAbmelden(name); // am alten Kontext (falls es ihn noch gibt) beenden
      angemeldetBei = mc;
    }
    if (!mc) return;
    for (const name of [...bei.keys()]) {
      if (register.get(name) !== bei.get(name)!.w) webmcpAbmelden(name);
    }
    for (const w of register.values()) {
      if (bei.has(w.name)) continue;
      const stopp = new AbortController();
      const r = versuche(
        () => mc.registerTool!(alsMcp(w), { signal: stopp.signal }),
        () => {
          // abgelehnt (z. B. Name vergeben): nicht als angemeldet führen, der nächste Abgleich versucht es erneut
          if (bei.get(w.name)?.stopp === stopp) bei.delete(w.name);
        },
      );
      if (r.ok) bei.set(w.name, { w, stopp });
    }
  } catch {
    /* siehe oben */
  }
}

/** Wo WebMCP steht — zum Nachsehen im Browser (`fyos.werkzeuge.webmcp()`): welcher Kontext, welche Werkzeuge angemeldet sind. */
export function webmcpStatus(): { kontext: KontextArt | null; angemeldet: string[] } {
  return { kontext: modelContext()?.art ?? null, angemeldet: [...bei.keys()].sort() };
}

const lauscher = new Set<() => void>();
function aenderungMelden(): void {
  for (const f of lauscher) {
    try {
      f();
    } catch {
      /* ein Lauscher darf die Anmeldung nicht stören */
    }
  }
}

/** Ruft `f`, sobald sich die Liste der Werkzeuge ändert (die OS-Brücke meldet sie dann neu). Gibt die Abmeldung zurück. */
export function beiAenderung(f: () => void): () => void {
  lauscher.add(f);
  return () => {
    lauscher.delete(f);
  };
}

export async function rufen(name: string, args: Record<string, unknown> = {}): Promise<WerkzeugErgebnis> {
  const w = register.get(name);
  if (!w) return fehler(`Unbekanntes Werkzeug: ${name}. Verfügbar: ${[...register.keys()].join(', ')}`);
  try {
    const r = await w.ausfuehren(args);
    return r && typeof r === 'object' && 'content' in (r as object) ? (r as WerkzeugErgebnis) : ergebnis(r);
  } catch (e) {
    return fehler(e instanceof Error ? e.message : String(e));
  }
}

/**
 * Werkzeuge anmelden. `dauerhaft` = gilt seitenübergreifend (Navigation, Suche, Hub);
 * sonst verschwinden sie beim nächsten Seitenwechsel. Gibt eine Abmeldung zurück.
 */
export function registriereWerkzeuge(liste: Werkzeug[], opt: { dauerhaft?: boolean } = {}): () => void {
  for (const w of liste) register.set(w.name, w);
  webmcpAbgleichen();
  aenderungMelden();
  const ab = () => {
    let weg = false;
    for (const w of liste) {
      if (register.get(w.name) === w) {
        register.delete(w.name);
        weg = true;
      }
    }
    if (weg) {
      webmcpAbgleichen();
      aenderungMelden();
    }
  };
  if (!opt.dauerhaft && typeof document !== 'undefined') {
    document.addEventListener('astro:before-swap', ab, { once: true });
  }
  return ab;
}

export function liste(): { name: string; beschreibung: string; eingabe?: Record<string, unknown>; lesend: boolean }[] {
  return [...register.values()].map((w) => ({ name: w.name, beschreibung: w.beschreibung, eingabe: w.eingabe, lesend: !!w.lesend }));
}

const kuerzen = (t: string, max: number): string => (t.length <= max ? t : `${t.slice(0, max - 1).trimEnd()}…`);

/**
 * Die Werkzeuge im Meldeformat der OS-Brücke: ohne `bruecke: false`, nach Namen sortiert (damit eine
 * unveränderte Liste auch unverändert gemeldet wird), höchstens 64; Beschreibung höchstens 300
 * Zeichen; das Schema nur, wenn es nicht größer als 2 KB ist.
 */
export function fuerBruecke(): BrueckeWerkzeug[] {
  const kodierer = new TextEncoder();
  const aus: BrueckeWerkzeug[] = [];
  for (const w of [...register.values()].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
    if (w.bruecke === false) continue;
    const e: BrueckeWerkzeug = { name: w.name, beschreibung: kuerzen(w.beschreibung, BRUECKE_MAX_BESCHREIBUNG), lesend: !!w.lesend };
    if (w.fenster) e.fenster = w.fenster;
    if (w.app) e.app = w.app;
    const schema = schemaVon(w);
    if (kodierer.encode(JSON.stringify(schema)).length <= BRUECKE_MAX_SCHEMA_BYTES) e.eingabe = schema;
    aus.push(e);
    if (aus.length >= BRUECKE_MAX_WERKZEUGE) break;
  }
  return aus;
}

/** `rufen` für Befehle aus der OS-Brücke: nur, was die Brücke auch meldet. */
export async function rufenFuerBruecke(name: string, args: Record<string, unknown> = {}): Promise<WerkzeugErgebnis> {
  const w = register.get(name);
  if (!w || w.bruecke === false) {
    const frei = fuerBruecke().map((x) => x.name);
    return fehler(
      w
        ? `Das Werkzeug ${name} ist nicht für die Brücke freigegeben. Freigegeben: ${frei.join(', ')}`
        : `Unbekanntes Werkzeug: ${name}. Verfügbar: ${frei.join(', ')}`,
    );
  }
  return rufen(name, args);
}

declare global {
  interface Window {
    fyos?: { werkzeuge?: { liste: typeof liste; rufen: typeof rufen; fuerBruecke: typeof fuerBruecke; webmcp: typeof webmcpStatus } };
  }
}

if (typeof window !== 'undefined') {
  window.fyos = { ...(window.fyos ?? {}), werkzeuge: { liste, rufen, fuerBruecke, webmcp: webmcpStatus } };
}
