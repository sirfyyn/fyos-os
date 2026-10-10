/**
 * app-aktionen.ts — was man mit einer geöffneten App tun kann (App-Rahmen).
 *
 * Fensterkopf (components/os/AppRahmen.tsx) und Fenstermenü (Raster) bieten dasselbe an:
 *
 *   Agent fragen             löst `fyos:agent-fragen` aus: Vorschlag für die Frage, dazu Name, Eingabe und
 *                            Modellkontext der App (lib/os/agent-fragen.ts).
 *   Link kopieren            Deeplink mit der aktuellen Eingabe (lib/os/oeffnen.ts)
 *   An den Start heften      die bestehenden Pins (lib/mcp-apps/pins.ts); der Startbildschirm zeigt sie
 *
 * „Aktuelle Eingabe" = Argumente des letzten lesenden Werkzeugaufrufs der App (der Host schreibt sie nach
 * lib/mcp-apps/zustand.ts); ohne einen solchen Aufruf der Anfangszustand aus dem Link, sonst die App ohne Eingabe.
 */
import { createSignal } from 'solid-js';
import { agentName } from '~/lib/config';
import { MAX_PINS, istAngepinnt, pinUmschalten } from '~/lib/mcp-apps/pins';
import { zustandVon } from '~/lib/mcp-apps/zustand';
import { FRAGEN_EREIGNIS } from './agent-fragen';
import type { StartZustand } from './anordnung';
import type { Flaeche } from './flaechen';
import type { MenuePunkt } from './menue';
import { deeplink } from './oeffnen';

/** Ereignis an `window`; `detail` ist ein `AgentFragenDetail`. */
export const AGENT_FRAGEN = FRAGEN_EREIGNIS;

export interface AgentFragenDetail {
  /** Vorschlag für die Frage — der Empfänger setzt ihn als Entwurf ein, der Mensch kann ihn ändern. */
  text: string;
  kontext: {
    /** Werkzeug, dessen Aufruf die Ansicht ergibt (`<plugin>__<werkzeug>`); mit `eingabe` ein vollständiger Aufruf */
    app: string;
    /** Name der App für Menschen */
    titel: string;
    /** Argumente der aktuellen Ansicht (`{}` = Anfangsansicht) */
    eingabe: Record<string, unknown>;
    /** Letzter Inhalt aus `ui/update-model-context`; null, wenn die App nichts gemeldet hat */
    modellKontext: unknown;
  };
  quelle: 'app';
}

/** Größter Modellkontext (JSON-Zeichen), der mit der Frage mitgeht; Größeres wird abgeschnitten. */
export const KONTEXT_MAX = 8000;

export function kontextKuerzen(x: unknown): unknown {
  if (x === undefined || x === null) return null;
  let json: string | undefined;
  try {
    json = JSON.stringify(x);
  } catch {
    return null;
  }
  if (json === undefined || json.length <= KONTEXT_MAX) return x;
  return { gekuerzt: true, text: json.slice(0, KONTEXT_MAX) };
}

// ── Rückmeldung („Link kopiert") ─────────────────────────────────────────────────────────────────
export interface Rueckmeldung {
  /** Fläche, in deren Fensterkopf es erscheint */
  id: string;
  text: string;
  art: 'ok' | 'hinweis';
}
const [meldung, setMeldung] = createSignal<Rueckmeldung | null>(null);
export const rueckmeldung = meldung;
let meldungWeg: ReturnType<typeof setTimeout> | undefined;
export function melden(id: string, text: string, art: Rueckmeldung['art'] = 'ok'): void {
  setMeldung({ id, text, art });
  clearTimeout(meldungWeg);
  meldungWeg = setTimeout(() => setMeldung(null), 2200);
}

// ── Aktuelle Ansicht ─────────────────────────────────────────────────────────────────────────────
/** Werkzeug und Eingabe der Ansicht, die gerade im Fenster steht. */
export function ansicht(f: Flaeche, start?: StartZustand): { app: string; eingabe: Record<string, unknown> } {
  const z = zustandVon(f.id);
  if (z.werkzeug && z.eingabe) return { app: z.werkzeug, eingabe: z.eingabe };
  if (start) return { app: start.werkzeug, eingabe: start.eingabe };
  return { app: f.appName ?? f.id.replace(/^app:/, ''), eingabe: {} };
}

/** Deeplink, der genau diese Ansicht im OS öffnet. */
export function appLink(f: Flaeche, start?: StartZustand): string {
  const a = ansicht(f, start);
  return deeplink(`app:${a.app}`, a.eingabe);
}

/** In die Zwischenablage; ohne Clipboard-API (http im LAN) über ein verstecktes Textfeld. */
async function inZwischenablage(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* Erlaubnis verweigert oder unsicherer Kontext — der Umweg unten */
  }
  const feld = document.createElement('textarea');
  try {
    feld.value = text;
    feld.setAttribute('readonly', '');
    feld.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
    document.body.appendChild(feld);
    feld.select();
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    feld.remove(); // auch wenn das Kopieren scheitert, bleibt kein Textfeld im Dokument zurück
  }
}

// ── Die drei Aktionen ────────────────────────────────────────────────────────────────────────────
export function appFragen(f: Flaeche, start?: StartZustand): AgentFragenDetail {
  const a = ansicht(f, start);
  const detail: AgentFragenDetail = {
    text: `Was fällt dir an „${f.titel}“ gerade auf?`,
    kontext: { app: a.app, titel: f.titel, eingabe: a.eingabe, modellKontext: kontextKuerzen(zustandVon(f.id).modellKontext) },
    quelle: 'app',
  };
  window.dispatchEvent(new CustomEvent(AGENT_FRAGEN, { detail }));
  return detail;
}

export async function linkKopieren(f: Flaeche, start?: StartZustand): Promise<boolean> {
  const ok = await inZwischenablage(appLink(f, start));
  melden(f.id, ok ? 'Link kopiert' : 'Kopieren nicht möglich', ok ? 'ok' : 'hinweis');
  return ok;
}

/** Heftet an den Startbildschirm oder löst wieder; gibt zurück, ob die App danach geheftet ist. */
export function heften(f: Flaeche): boolean {
  if (!f.appName) return false;
  const vorher = istAngepinnt(f.appName);
  if (!vorher && !f.startbar) {
    melden(f.id, 'Diese App lässt sich nicht heften', 'hinweis');
    return false;
  }
  const jetzt = pinUmschalten(f.appName);
  if (!vorher && !jetzt) {
    melden(f.id, `Es sind schon ${MAX_PINS} Apps geheftet`, 'hinweis');
    return false;
  }
  melden(f.id, jetzt ? 'An den Start geheftet' : 'Vom Start gelöst');
  return jetzt;
}

/** Heften ist sinnvoll: die App ist startbar, oder sie ist schon geheftet (dann lässt sie sich lösen). */
export const kannHeften = (f: Flaeche): boolean => !!f.appName && (!!f.startbar || istAngepinnt(f.appName));

/** Die drei Aktionen als Menüpunkte (oben im Fenstermenü einer App). */
export function aktionsPunkte(f: Flaeche, start?: StartZustand): MenuePunkt[] {
  const geheftet = !!f.appName && istAngepinnt(f.appName);
  return [
    { text: `${agentName()} fragen`, symbol: 'sparkles', tun: () => void appFragen(f, start) },
    { text: 'Link kopieren', symbol: 'link', tun: () => void linkKopieren(f, start) },
    ...(kannHeften(f)
      ? [{ text: geheftet ? 'Vom Start lösen' : 'An den Start heften', symbol: geheftet ? 'pin-off' : 'pin', tun: () => void heften(f) } satisfies MenuePunkt]
      : []),
  ];
}
