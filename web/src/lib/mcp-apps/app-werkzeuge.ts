/**
 * app-werkzeuge.ts — Seitenwerkzeuge der Apps in OS-Fenstern.
 *
 * Eine Hub-App im OS-Fenster (Sandbox-iframe) meldet mit `App.werkzeug(name, beschreibung, schema, fn, {lesend})`
 * ein Werkzeug an (`fyos/werkzeug-anmelden`). Der Host (host.ts) reicht es hierher:
 *   - Name mit dem Präfix des Plugins: `liste_zeigen` in der App `notizen` wird `notizen_liste_zeigen`
 *   - eingetragen im einen Register (lib/werkzeuge.ts), also bei WebMCP (`document.modelContext`) und in der
 *     OS-Brücke (der Agent: `os.lage` ordnet es über `fenster` dem Fenster zu, `os.ausfuehren` ruft es)
 *   - ausgeführt in der App (`fyos/werkzeug-rufen`; der Host wartet höchstens APP_WERKZEUG_FRIST_MS, weil
 *     `os.ausfuehren` im Hub nach 15 s aufgibt)
 *   - abgemeldet, wenn die App es zurückzieht (`fyos/werkzeug-abmelden`) oder das Fenster schließt
 *
 * Bestätigungspflicht: Lesen und Zeigen ohne Rückfrage. Was schreibt, legt die App dem Benutzer mit `App.beantragen`
 * vor, geschrieben wird erst nach seinem „Ja“ (ein Klick, also eine Nutzergeste). Der Host setzt das durch: Solange
 * ein Agent ein Werkzeug der App ausführt und NACHLAUF_MS danach, lehnt er jeden nicht lesenden Hub-Aufruf der App
 * ohne Nutzergeste ab (`schreibenErlaubt`). Was die App von sich aus tut, wenn der Benutzer klickt, bleibt wie bisher.
 */
import { ergebnis, liste, registriereWerkzeuge, type Werkzeug, type WerkzeugErgebnis } from '~/lib/werkzeuge';
import { tr } from '~/lib/i18n';

/** Höchstens so viele Werkzeuge je Fenster */
export const APP_WERKZEUGE_MAX = 16;
/** So lange wartet der Host auf die App (os.ausfuehren im Hub: 15 s) */
export const APP_WERKZEUG_FRIST_MS = 12_000;
/** So lange nach einem Agentenaufruf schreibt die App nur nach einer Geste */
export const NACHLAUF_MS = 30_000;
export const BESCHREIBUNG_MAX = 300;
export const SCHEMA_MAX_BYTES = 2048;
const ERGEBNIS_MAX_ZEICHEN = 60_000;

const KURZ = /^[a-z][a-z0-9_]{0,39}$/;
const PLUGIN = /^[a-z][a-z0-9_]{0,23}$/;

type Fehler = { ok: false; fehler: string };
const nein = (fehler: string): Fehler => ({ ok: false, fehler });

/**
 * Voller Name eines App-Werkzeugs: `<plugin>_<name>`. Nennt die App das Präfix schon selbst, kommt es nicht doppelt.
 * null, wenn Plugin oder Name nicht passen (a–z, 0–9, _, Buchstabe vorn, Name höchstens 40 Zeichen).
 */
export function appWerkzeugName(plugin: string, name: string): string | null {
  if (!PLUGIN.test(plugin)) return null;
  const kurz = name.startsWith(`${plugin}_`) ? name.slice(plugin.length + 1) : name;
  return KURZ.test(kurz) ? `${plugin}_${kurz}` : null;
}

export type Angebot = { kurz: string; name: string; beschreibung: string; eingabe: Record<string, unknown>; lesend: boolean };

/** Prüft, was die App anmelden will (`fyos/werkzeug-anmelden` {name, beschreibung, eingabe?, lesend?}). */
export function angebotPruefen(plugin: string, p: unknown): { ok: true; angebot: Angebot } | Fehler {
  const x = (p && typeof p === 'object' && !Array.isArray(p) ? p : {}) as Record<string, unknown>;
  const roh = typeof x.name === 'string' ? x.name : '';
  const name = appWerkzeugName(plugin, roh);
  if (!name) return nein(tr('Ungültiger Werkzeugname „{0}“: a–z, 0–9 und _, ein Buchstabe vorn, höchstens 40 Zeichen.', roh.slice(0, 60)));
  const beschreibung = typeof x.beschreibung === 'string' ? x.beschreibung.replace(/\s+/g, ' ').trim() : '';
  if (!beschreibung) return nein(tr('{0}: Ein Werkzeug braucht eine Beschreibung (ein Satz, was es tut).', name));
  let eingabe: Record<string, unknown> = { type: 'object', properties: {} };
  if (x.eingabe != null) {
    if (typeof x.eingabe !== 'object' || Array.isArray(x.eingabe)) return nein(tr('{0}: Das Schema muss ein JSON-Schema-Objekt sein.', name));
    const s = x.eingabe as Record<string, unknown>;
    if (s.type !== undefined && s.type !== 'object') return nein(tr('{0}: Das Schema beschreibt ein Objekt (type: "object").', name));
    eingabe = { type: 'object', properties: {}, ...s };
    let bytes: number;
    try {
      bytes = new TextEncoder().encode(JSON.stringify(eingabe)).length;
    } catch {
      return nein(tr('{0}: Das Schema ist kein JSON.', name));
    }
    if (bytes > SCHEMA_MAX_BYTES) return nein(tr('{0}: Das Schema ist größer als {1} Bytes.', name, SCHEMA_MAX_BYTES));
  }
  return {
    ok: true,
    angebot: { kurz: name.slice(plugin.length + 1), name, beschreibung: beschreibung.slice(0, BESCHREIBUNG_MAX), eingabe, lesend: x.lesend === true },
  };
}

/** Was die App zurückgibt, in die Form eines MCP-Ergebnisses: nur Textblöcke, gekürzt; alles andere als Daten. */
export function ergebnisSauber(r: unknown): WerkzeugErgebnis {
  if (r && typeof r === 'object' && Array.isArray((r as { content?: unknown }).content)) {
    const x = r as { content: unknown[]; isError?: unknown; structuredContent?: unknown };
    const content = x.content
      .filter((c): c is { type: 'text'; text: unknown } => !!c && typeof c === 'object' && (c as { type?: unknown }).type === 'text')
      .map((c) => ({ type: 'text' as const, text: String(c.text ?? '').slice(0, ERGEBNIS_MAX_ZEICHEN) }));
    const sc = x.structuredContent;
    return {
      content,
      ...(x.isError === true ? { isError: true } : {}),
      ...(sc && typeof sc === 'object' && !Array.isArray(sc) ? { structuredContent: sc } : {}),
    };
  }
  return ergebnis(r ?? null);
}

export interface AppWerkzeugOrt {
  /** Plugin der App (Präfix der Namen) */
  plugin: string;
  /** ID des Fensters (= Fläche, z. B. `app:notizen__liste`) */
  fenster: string;
  /** Ruft das Werkzeug in der App auf (`fyos/werkzeug-rufen` {name, voll, arguments}), mit Frist; wirft bei Zeitüberschreitung */
  rufen: (aufruf: { name: string; voll: string; arguments: Record<string, unknown> }) => Promise<unknown>;
  jetzt?: () => number;
}

export interface AppWerkzeuge {
  anmelden: (p: unknown) => { ok: true; name: string } | Fehler;
  abmelden: (name: unknown) => boolean;
  alleAbmelden: () => void;
  /** Darf die App jetzt einen nicht lesenden Hub-Aufruf machen? (mit Geste immer; sonst nicht während und kurz nach einem Agentenaufruf) */
  schreibenErlaubt: (geste: boolean) => boolean;
  namen: () => string[];
}

/** Die App-Werkzeuge EINES Fensters. Der Host legt das beim Einhängen an und ruft beim Abbau `alleAbmelden`. */
export function appWerkzeugeFuer(ort: AppWerkzeugOrt): AppWerkzeuge {
  const jetzt = ort.jetzt ?? Date.now;
  const eigene = new Map<string, { w: Werkzeug; ab: () => void }>();
  let offen = 0;
  let zuletztEnde = Number.NEGATIVE_INFINITY;

  async function ausfuehren(a: Angebot, args: Record<string, unknown>): Promise<WerkzeugErgebnis> {
    offen++;
    try {
      return ergebnisSauber(await ort.rufen({ name: a.kurz, voll: a.name, arguments: args ?? {} }));
    } finally {
      offen--;
      zuletztEnde = jetzt();
    }
  }

  return {
    anmelden(p) {
      const g = angebotPruefen(ort.plugin, p);
      if (!g.ok) return g;
      const a = g.angebot;
      const vorher = eigene.get(a.name);
      if (!vorher && eigene.size >= APP_WERKZEUGE_MAX) return nein(tr('Höchstens {0} Werkzeuge je Fenster.', APP_WERKZEUGE_MAX));
      if (!vorher && liste().some((w) => w.name === a.name)) {
        return nein(tr('Den Namen {0} trägt schon ein anderes Werkzeug (dieselbe App in einem zweiten Fenster?).', a.name));
      }
      const w: Werkzeug = {
        name: a.name,
        beschreibung: a.beschreibung,
        eingabe: a.eingabe,
        lesend: a.lesend,
        fenster: ort.fenster,
        app: ort.plugin,
        ausfuehren: (args) => ausfuehren(a, args),
      };
      // Neu angemeldet ersetzt (neue Beschreibung, neues Schema); die alte Abmeldung greift danach ins Leere.
      eigene.set(a.name, { w, ab: registriereWerkzeuge([w], { dauerhaft: true }) });
      return { ok: true, name: a.name };
    },
    abmelden(name) {
      const voll = typeof name === 'string' ? appWerkzeugName(ort.plugin, name) : null;
      const e = voll ? eigene.get(voll) : undefined;
      if (!e) return false;
      eigene.delete(voll!);
      e.ab();
      return true;
    },
    alleAbmelden() {
      for (const e of eigene.values()) e.ab();
      eigene.clear();
    },
    schreibenErlaubt: (geste) => geste || (offen === 0 && jetzt() - zuletztEnde > NACHLAUF_MS),
    namen: () => [...eigene.keys()].sort(),
  };
}
