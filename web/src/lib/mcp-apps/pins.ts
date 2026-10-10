/**
 * Angepinnte Hub-Apps: welche Apps auf der Startseite zusätzlich erscheinen.
 *
 * Nur im Browser gespeichert (je Betrachter, wie der Anzeigemodus) — eine Auswahl ohne
 * Server, die jederzeit leer sein darf. Gespeichert wird der MCP-Werkzeugname
 * (`<plugin>__<werkzeug>`); gibt es das Werkzeug im Hub nicht mehr, wird der Pin still übergangen.
 */
import type { McpApp } from './host';

const SCHLUESSEL = 'fyos:app-pins';
const EREIGNIS = 'fyos:app-pins-geaendert';
export const MAX_PINS = 3;

/**
 * Darf die App angeheftet werden? Sie läuft dann beim Laden des Startbildschirms von selbst — also nur lesend
 * (Scope READ) und ohne Pflichtfelder; beim Laden darf nichts ausgelöst werden.
 */
export function startbar(app: Pick<McpApp, 'scope' | 'inputSchema'>): boolean {
  return aufrufbar(app, {});
}

/**
 * Darf der Host die App mit diesen Argumenten von selbst aufrufen (beim Öffnen, aus einem Link)? Nur wenn sie lesend
 * ist (Scope READ) und die Argumente alle Pflichtfelder belegen — sonst käme ein Aufruf ins Leere oder, schlimmer,
 * etwas, das niemand bestellt hat (ein Link löst nie Schreibendes aus).
 */
export function aufrufbar(app: Pick<McpApp, 'scope' | 'inputSchema'>, args: Record<string, unknown>): boolean {
  return app.scope === 'READ' && (app.inputSchema?.required ?? []).every((feld) => args?.[feld] !== undefined && args[feld] !== null);
}

function lesen(): string[] {
  try {
    const roh = JSON.parse(localStorage.getItem(SCHLUESSEL) ?? '[]');
    return Array.isArray(roh) ? roh.filter((x): x is string => typeof x === 'string').slice(0, MAX_PINS) : [];
  } catch {
    return [];
  }
}

export function pins(): string[] {
  return typeof localStorage === 'undefined' ? [] : lesen();
}

export function istAngepinnt(name: string): boolean {
  return pins().includes(name);
}

/** Schaltet um; gibt den neuen Zustand zurück (false auch, wenn schon MAX_PINS Pins da sind). */
export function pinUmschalten(name: string): boolean {
  const alt = lesen();
  const neu = alt.includes(name) ? alt.filter((x) => x !== name) : [...alt, name].slice(0, MAX_PINS);
  try {
    localStorage.setItem(SCHLUESSEL, JSON.stringify(neu));
  } catch {
    return alt.includes(name);
  }
  window.dispatchEvent(new Event(EREIGNIS));
  return neu.includes(name);
}

/** Meldet Änderungen (auch aus anderen Tabs); gibt die Abmeldefunktion zurück. */
export function pinsBeobachten(f: (liste: string[]) => void): () => void {
  const los = () => f(lesen());
  window.addEventListener(EREIGNIS, los);
  window.addEventListener('storage', los);
  return () => {
    window.removeEventListener(EREIGNIS, los);
    window.removeEventListener('storage', los);
  };
}
