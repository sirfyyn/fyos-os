/**
 * oeffnen.ts — Übergänge ins OS: Deeplinks mit Zustand und das Ereignis „öffne im OS".
 *
 * Deeplink-Form:
 *   <Ursprung>/os?offen=app:<plugin>__<werkzeug>&eingabe=<base64url(JSON-Argumente)>
 * Das OS öffnet die App mit genau diesen Argumenten. Der Ursprung ist der der laufenden Seite
 * (`location.origin`); hinter einem Proxy kann `oeffentlicheUrl` in /fyos.config.json eine zweite, öffentliche
 * Adresse nennen (`oeffentlicherUrsprung`), deren Links ebenfalls im OS öffnen. Hier steht alles, was
 * Browser-seitig dazugehört:
 *
 *   eingabeKodieren / eingabeLesen   die Argumente in der Adresse (UTF-8, base64url, höchstens 4000 Zeichen)
 *   deeplink                         die Adresse bauen (Link kopieren, Agent fragen)
 *   osZielAus                        eine Adresse von fyos als Ziel im OS lesen (ui/open-link im Host)
 *   imOsOeffnen                      das Ereignis `fyos:oeffnen` an die Shell schicken; true = sie hat es übernommen
 *
 * Sicherheit: Die Eingabe kommt aus einer Adresse, also von außen. Sie wird nur gelesen, wenn sie ein
 * JSON-Objekt unter der Größengrenze ist; die Shell ruft damit ausschließlich lesende Werkzeuge der App
 * auf (nie schreibende) — das prüft AppEingebettet, nicht diese Datei.
 */

/** Ereignis an `window`: `detail` ist ein `OsZiel`. Die Shell setzt `preventDefault()`, wenn sie öffnet. */
export const OEFFNEN = 'fyos:oeffnen';

/**
 * Zusätzlicher Ursprung, dessen Links im OS öffnen (Entwicklung, LAN, Proxy). Leer = nur der eigene.
 * Gesetzt wird er aus der Laufzeit-Konfiguration (`oeffentlicheUrl`).
 */
let oeffentlich = '';

export function oeffentlicherUrsprungSetzen(url: string | undefined | null): void {
  try {
    oeffentlich = url ? new URL(url).origin : '';
  } catch {
    oeffentlich = '';
  }
}

export const oeffentlicherUrsprung = (): string => oeffentlich;

/** Größte Eingabe (JSON-Zeichen), die in einer Adresse und im Fenster mitgeführt wird. */
export const EINGABE_MAX = 4000;

export interface OsZiel {
  /** Fläche (`app:…`, `seite:…`, `nativ:…`, `agent`) oder Pfad einer Seite des Systems (`/wiki/`). */
  ziel: string;
  /** Argumente, mit denen die App starten soll. */
  eingabe?: Record<string, unknown>;
}

const GEFAEHRLICH = new Set(['__proto__', 'constructor', 'prototype']);

/** Ein JSON-Objekt unter der Größengrenze, tief kopiert und ohne gefährliche Schlüssel; sonst undefined. */
export function eingabeSauber(x: unknown): Record<string, unknown> | undefined {
  if (!x || typeof x !== 'object' || Array.isArray(x)) return undefined;
  let json: string | undefined;
  try {
    json = JSON.stringify(x);
  } catch {
    return undefined;
  }
  if (!json || json.length > EINGABE_MAX) return undefined;
  try {
    return JSON.parse(json, (k, v) => (GEFAEHRLICH.has(k) ? undefined : v)) as Record<string, unknown>;
  } catch {
    return undefined;
  }
}

/** base64url der UTF-8-Bytes des JSON; leer/zu groß → undefined. */
export function eingabeKodieren(eingabe: Record<string, unknown> | undefined | null): string | undefined {
  const e = eingabe ? eingabeSauber(eingabe) : undefined;
  if (!e || !Object.keys(e).length) return undefined;
  const bytes = new TextEncoder().encode(JSON.stringify(e));
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Gegenstück zu eingabeKodieren; mit und ohne Auffüllzeichen, bei allem Ungültigen undefined. */
export function eingabeLesen(roh: string | null | undefined): Record<string, unknown> | undefined {
  // 4000 Zeichen JSON sind höchstens 12000 Bytes (UTF-8), das sind 16000 Zeichen base64
  if (!roh || roh.length > 16_400 || !/^[A-Za-z0-9_-]+={0,2}$/.test(roh)) return undefined;
  try {
    const b64 = roh.replace(/-/g, '+').replace(/_/g, '/');
    const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return eingabeSauber(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)));
  } catch {
    return undefined;
  }
}

/** Adresse, die `ziel` (mit Eingabe) im OS öffnet. Doppelpunkte und Kommas bleiben lesbar. */
export function deeplink(ziel: string, eingabe?: Record<string, unknown> | null, ursprung?: string): string {
  const basis = ursprung ?? (typeof location !== 'undefined' ? location.origin : oeffentlich);
  const offen = encodeURIComponent(ziel).replace(/%3A/gi, ':').replace(/%2C/gi, ',');
  const e = eingabeKodieren(eingabe);
  return `${basis}/os/?offen=${offen}${e ? `&eingabe=${e}` : ''}`;
}

/** Pfad einer Seite für den Vergleich: ohne Schrägstrich am Ende und ohne #…, mit Abfrage. */
export function pfadSchluessel(p: string): string {
  try {
    const u = new URL(p, 'http://fyos.invalid');
    return (u.pathname.replace(/\/+$/, '') || '/') + u.search;
  } catch {
    return p;
  }
}

/**
 * Eine Adresse von fyos als Ziel im OS lesen. Fremde Adressen (anderer Ursprung) und alles, was nicht
 * nach einer Fläche aussieht, geben null zurück — der Aufrufer öffnet dann wie bisher einen Tab.
 *
 *   /os?offen=<id>[&eingabe=…]      die Fläche (bei mehreren: die erste)
 *   /apps/mcp?app=<name>[&args=…]   die App (älterer Weg, nur noch gelesen: Lesezeichen und alte Links;
 *                                   WebMCP `fyos_zeigen` erzeugt seit jetzt `/os?offen=app:<name>`)
 *   jede andere Seite dieses Ursprungs   als Pfad; die Shell sucht eine Fläche dazu
 */
export function osZielAus(url: string, hier?: { origin: string; href: string }): OsZiel | null {
  if (!url.trim()) return null; // eine leere Adresse wäre „diese Seite"
  const ort = hier ?? (typeof location !== 'undefined' ? location : { origin: oeffentlich, href: `${oeffentlich}/` });
  let u: URL;
  try {
    u = new URL(url, ort.href);
  } catch {
    return null;
  }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return null;
  if (u.origin !== ort.origin && !(oeffentlich && u.origin === oeffentlich)) return null;
  const pfad = u.pathname.replace(/\/+$/, '') || '/';
  if (pfad === '/os') {
    const erste = (u.searchParams.get('offen') ?? '').split(',').map((s) => s.trim()).filter(Boolean)[0];
    if (!erste) return null;
    const eingabe = eingabeLesen(u.searchParams.get('eingabe'));
    return eingabe ? { ziel: erste, eingabe } : { ziel: erste };
  }
  if (pfad === '/apps/mcp') {
    const app = u.searchParams.get('app');
    if (app) {
      let eingabe: Record<string, unknown> | undefined;
      try {
        const roh = u.searchParams.get('args');
        eingabe = roh ? eingabeSauber(JSON.parse(roh)) : undefined;
      } catch {
        eingabe = undefined;
      }
      return eingabe ? { ziel: `app:${app}`, eingabe } : { ziel: `app:${app}` };
    }
  }
  return { ziel: pfad + u.search };
}

/** Das Fenster über `w` (wenn es dasselbe Ursprung hat), sonst null. */
function elternFenster(w: Window): Window | null {
  try {
    const p = w.parent;
    return p && p !== w && p.location.origin === w.location.origin ? p : null;
  } catch {
    return null;
  }
}

/**
 * Schickt „öffne `z` im OS" an die Shell: erst an dieses Fenster (Apps laufen im OS im selben Fenster wie
 * die Shell), dann an das darüber (Seiten im OS laufen in einem iframe). true = die Shell hat es übernommen;
 * false = hier läuft kein OS (Seite allein im Tab) — dann öffnet der Aufrufer selbst.
 */
export function imOsOeffnen(z: OsZiel, fenster: Window = window): boolean {
  for (const w of [fenster, elternFenster(fenster)]) {
    if (!w) continue;
    const e = new (w as Window & typeof globalThis).CustomEvent(OEFFNEN, { detail: z, cancelable: true });
    w.dispatchEvent(e);
    if (e.defaultPrevented) return true;
  }
  return false;
}
