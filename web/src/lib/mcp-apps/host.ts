/**
 * MCP-Apps-Host der Shell.
 *
 * Die Shell zeigt die Oberflächen der Hub-Werkzeuge (MCP Apps, Spezifikation
 * 2026-01-26) selbst an — damit sie auch mit dem Agenten und lokalen Modellen laufen,
 * nicht nur in Claude/ChatGPT. Der Browser spricht dafür NICHT den ganzen Hub,
 * sondern nur `/hub-api/` (nginx → mcp-hub): Liste der Apps, Ressource lesen,
 * App-Werkzeug aufrufen. Hinter dem vollen /hub/call lägen exec & Co.
 *
 * Ablauf je App:
 *   1. Werkzeug aufrufen (`appCall`) → Ergebnis
 *   2. `ui://`-Ressource holen (`resource`) → HTML
 *   3. HTML in ein Sandbox-iframe (allow-scripts und allow-forms, eigener Ursprung „null", dazu Inhaltsregeln: `appCsp`)
 *   4. JSON-RPC über postMessage: ui/initialize beantworten, dann tool-input und
 *      tool-result schicken (ohne Ergebnis nur tool-input); tools/call der App an `/hub-api/app-call`
 *      weiterreichen — nur Werkzeuge ihres Plugins, deren Sichtbarkeit „app“ enthält.
 *
 * Aussehen: die Apps sind durchsichtig und liegen auf dem Glas der OS-Fenster. Der Host
 * gibt ihnen im hostContext Thema und Gestaltungswerte mit (`styles.variables`, nur Schlüssel der
 * Spezifikation — das offizielle SDK prüft sie), abgeleitet aus den Farben der Shell; ändern sich
 * Thema oder OS-Farben, folgt `ui/notifications/host-context-changed`. Das iframe bekommt dasselbe
 * Farbschema wie die App, sonst malt der Browser ihr einen deckenden Grund.
 *
 * Übergänge: `ui/open-link` mit einer
 * Adresse von fyos öffnet im OS ein Fenster (Ereignis `fyos:oeffnen`, lib/os/oeffnen.ts) statt eines Tabs;
 * fremde Adressen und Seiten ohne OS öffnen wie bisher einen Tab. Für den App-Rahmen im Fensterkopf merkt
 * sich der Host je Einbettung (`schluessel`), mit welcher Eingabe die Ansicht entstanden ist und was die
 * App dem Modell meldet (lib/mcp-apps/zustand.ts). Die App sieht uns als `hostInfo.name === HOST_NAME`.
 *
 */
import { meldeSitzungAbgelaufen } from '~/lib/api/transport';
import { imOsOeffnen, osZielAus } from '~/lib/os/oeffnen';
import { gesichterMerken } from './gesicht';
import { zustandMerken } from './zustand';

export const HUB_API = '/hub-api';
export const PROTOKOLL = '2026-01-26';
/** Name, unter dem sich die Shell den Apps vorstellt (`ui/initialize` → hostInfo). Apps zeigen „In FYOS öffnen" nur bei anderen Hosts. */
export const HOST_NAME = 'fyos-web';

export type McpApp = {
  tool: string; // <plugin>.<name>
  name: string; // <plugin>__<name> (MCP-Werkzeugname)
  title?: string | null;
  description: string;
  inputSchema: { properties?: Record<string, { type?: string; description?: string; enum?: string[] }>; required?: string[] };
  /** Bei Flaechen-Werkzeugen ohne Oberflaeche (Tag `flaeche`) fehlt `ui`. */
  _meta: { ui: { resourceUri: string; visibility?: string[] } };
  scope: string;
  /** false = Flaechen-Werkzeug ohne ui://-Oberflaeche (Lage, Betrieb, …). */
  hatUi?: boolean;
  /**
   * Gesicht der App (Vertrag 1), sobald der Hub es mitliefert: `GET /hub/apps` hat die Felder auf oberster
   * Ebene, das Werkzeug zusätzlich in `_meta.app`. Fehlen sie, leitet lib/mcp-apps/gesicht.ts sie ab.
   */
  titel?: string;
  untertitel?: string;
  symbol?: string;
  /** Farbton 0–359 */
  ton?: number;
  kategorie?: string;
  /** Fertiges SVG-Symbol (data:image/svg+xml) für Glyphen, die fyos-web nicht selbst zeichnen kann */
  icon?: string;
};

export type CallToolResult = {
  content: { type: 'text'; text: string }[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
};

/**
 * Eine Anfrage an `/hub-api`. Ohne Anmeldung antwortet Authentik nicht mit JSON: ein Sprung zur Anmeldeseite
 * (`redirect: 'manual'` macht daraus `opaqueredirect`), eine 401 oder eine HTML-Seite mit 200. Früher wurde
 * der Text zu `{}` und die App zeigte „Ressource nicht lesbar“; jetzt löst es dasselbe Ereignis aus wie überall
 * (`fyos:sitzung-abgelaufen`, Banner oben) und wirft einen Fehler, der den Grund nennt.
 */
export const SITZUNG_FEHLER = 'Anmeldung abgelaufen — bitte neu anmelden';

async function hubAnfrage<T>(pfad: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${HUB_API}${pfad}`, { credentials: 'include', redirect: 'manual', ...init });
  const typ = r.headers?.get?.('content-type') ?? '';
  if (r.type === 'opaqueredirect' || r.status === 401 || typ.includes('text/html')) {
    meldeSitzungAbgelaufen();
    throw new Error(SITZUNG_FEHLER);
  }
  const d = await r.json().catch(() => undefined);
  if (d === undefined) throw new Error(r.ok ? 'Antwort des Hubs ist kein JSON' : `HTTP ${r.status}`);
  if (!r.ok && !(d && typeof d === 'object' && 'ok' in d)) throw new Error(`HTTP ${r.status}`);
  return d as T;
}

/**
 * Apps mit Oberflaeche; `nurModell` blendet reine App-Werkzeuge (visibility ["app"]) aus.
 * Nur Werkzeuge mit echter `ui://`-Ressource: Stimme und Augen melden `ui: {}` (Menueleisten-Faehigkeit, keine
 * Oberflaeche) — als Karte wuerde `appEinhaengen` mit `ressourceLesen(undefined)` scheitern.
 */
export async function apps(nurModell = true): Promise<McpApp[]> {
  const alle = (await werkzeugeImHub()).filter((a) => typeof a._meta?.ui?.resourceUri === 'string' && a._meta.ui.resourceUri !== '');
  return nurModell ? alle.filter(fuerModellSichtbar) : alle;
}

/** Zuletzt gelesene Werkzeuge des Hubs nach Name — damit der Host weiß, ob ein Aufruf der App lesend ist. */
const bekannt = new Map<string, McpApp>();

/** `_meta.ui.visibility` der Spezifikation; ohne Angabe sehen Modell und App das Werkzeug. */
const sichtbarkeit = (a: McpApp): string[] => a._meta?.ui?.visibility ?? ['model', 'app'];
const fuerModellSichtbar = (a: McpApp): boolean => sichtbarkeit(a).includes('model');
const fuerAppSichtbar = (a: McpApp): boolean => sichtbarkeit(a).includes('app');

/** Laufender Abruf der Liste: Shell, WebMCP und Werkzeug-Register fragen beim Laden gleichzeitig. */
let laufend: Promise<McpApp[]> | null = null;

/** Alle Flaechen-Werkzeuge des Hubs (mit und ohne Oberflaeche), fuer WebMCP und Panes. Gleichzeitige Aufrufe teilen sich einen Abruf. */
export function werkzeugeImHub(): Promise<McpApp[]> {
  laufend ??= hubAnfrage<{ apps?: McpApp[] }>('/apps')
    .then((d) => {
      const liste = d.apps ?? [];
      for (const a of liste) bekannt.set(a.name, a);
      // Symbol und Farbe aus dem Hub gelten ab jetzt überall (Dock, Start, Fensterkopf, Katalog)
      gesichterMerken(liste);
      return liste;
    })
    .finally(() => {
      laufend = null;
    });
  return laufend;
}

/** Inhalt einer `ui://`-Ressource samt `_meta` (dort steht nach der Spezifikation `ui.csp`). */
export async function ressourceLesen(uri: string): Promise<{ text: string; meta?: unknown }> {
  const d = await hubAnfrage<{ ok: boolean; text?: string; error?: string; _meta?: unknown }>(`/resource?uri=${encodeURIComponent(uri)}`);
  if (!d.ok || d.text == null) throw new Error(d.error || 'Ressource nicht lesbar');
  return { text: d.text, meta: d._meta };
}

export async function resource(uri: string): Promise<string> {
  return (await ressourceLesen(uri)).text;
}

/**
 * Ein App-Werkzeug aufrufen; Ergebnis im Format von MCP `CallToolResult`. Was der Hub unter `_meta` ins Ergebnis
 * legt (`fyos/oeffnen`, der Link „In FYOS öffnen“, Vertrag 2) steht danach im `_meta` des Ergebnisses — dort sucht es
 * die Brücke der App —, nicht mehr in den Daten.
 */
export async function appCall(name: string, args: Record<string, unknown>, art: 'bewusst' | 'abfrage' = 'bewusst'): Promise<CallToolResult> {
  const d = await hubAnfrage<{ ok: boolean; result?: unknown; error?: string }>('/app-call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Hub-Art': art },
    body: JSON.stringify({ name, arguments: args }),
  });
  if (!d.ok) return { content: [{ type: 'text', text: d.error || 'Fehler' }], isError: true };
  const roh = d.result && typeof d.result === 'object' && !Array.isArray(d.result) ? (d.result as Record<string, unknown>) : { result: d.result };
  const { _meta: meta, ...struktur } = roh;
  const nachricht = meta && typeof meta === 'object' && !Array.isArray(meta) ? (meta as Record<string, unknown>) : undefined;
  return {
    content: [{ type: 'text', text: JSON.stringify(struktur) }],
    structuredContent: struktur,
    ...(nachricht ? { _meta: nachricht } : {}),
  };
}

/**
 * Inhaltsregeln (CSP) für das Sandbox-iframe der App. Die Apps des Hubs holen nichts von
 * selbst: alle Daten kommen über die Brücke (postMessage), Skript und Stil stehen im Dokument. Darum gilt
 * `default-src 'none'`, und nur was die Apps tatsächlich brauchen, ist offen:
 *   script-src/style-src 'unsafe-inline'   eigenes Skript und Stil im Dokument (keine Dateien, kein eval)
 *   img-src data: blob: https:             Symbole als data:; Konten zeigt das Profilbild des Anbieters
 *                                          (Google, GitHub … — Adressen sind nicht vorab bekannt)
 *   media-src blob: https:, font-src data:
 *   connect-src, frame-src, base-uri       geschlossen — wer mehr braucht, nennt es in `_meta.ui.csp` der
 *                                          Ressource (connectDomains, resourceDomains, frameDomains, baseUriDomains)
 *   form-action 'none'                     kein Absenden an Fremde (die Sandbox erlaubt Formulare, damit submit-Handler
 *                                          laufen; abgeschickt wird nichts)
 */
export type UiCsp = { connectDomains?: unknown; resourceDomains?: unknown; frameDomains?: unknown; baseUriDomains?: unknown };

/** Eine Quelle aus `_meta.ui.csp`: Ursprung mit optionalem Platzhalter vorn, nichts, was die Regel verlassen könnte. */
const CSP_QUELLE = /^(https?|wss?):\/\/(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$/i;
const quellen = (l: unknown): string[] =>
  Array.isArray(l) ? [...new Set(l.filter((x): x is string => typeof x === 'string' && CSP_QUELLE.test(x)))].slice(0, 24) : [];

export function appCsp(meta?: unknown): string {
  const ui = (meta && typeof meta === 'object' ? (meta as { ui?: unknown }).ui : undefined) as { csp?: UiCsp } | undefined;
  const c = ui?.csp && typeof ui.csp === 'object' ? ui.csp : {};
  const res = quellen(c.resourceDomains);
  const mit = (...basis: string[]) => [...basis, ...res].join(' ');
  const oder = (liste: string[]) => (liste.length ? liste.join(' ') : "'none'");
  return [
    "default-src 'none'",
    `script-src ${mit("'unsafe-inline'")}`,
    `style-src ${mit("'unsafe-inline'")}`,
    `img-src ${mit('data:', 'blob:', 'https:')}`,
    `media-src ${mit('blob:', 'https:')}`,
    `font-src ${mit('data:')}`,
    `frame-src ${oder(quellen(c.frameDomains))}`,
    `connect-src ${oder(quellen(c.connectDomains))}`,
    `base-uri ${oder(quellen(c.baseUriDomains))}`,
    "form-action 'none'",
  ].join('; ');
}

/** Setzt die Inhaltsregeln als erstes Element in den `<head>` (nach dem Doctype, nach `<html>`); eine Regel gilt nur für das, was nach ihr steht. */
export function htmlMitCsp(html: string, csp: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`;
  const kopf = /<head(?:\s[^>]*)?>/i.exec(html);
  if (kopf) return html.slice(0, kopf.index + kopf[0].length) + meta + html.slice(kopf.index + kopf[0].length);
  const huelle = /^\s*(?:<!doctype[^>]*>\s*)?(?:<html(?:\s[^>]*)?>\s*)?/i.exec(html);
  const ab = huelle ? huelle[0].length : 0;
  return `${html.slice(0, ab)}<head>${meta}</head>${html.slice(ab)}`;
}

/** Gestaltungswerte der Spezifikation (McpUiStyles) — nur diese Schlüssel lässt das offizielle SDK zu. */
export type HostStile = { variables: Record<string, string> };

/**
 * Gestaltungswerte für die Apps aus den Farben dieser Seite (global.css, os.css): durchsichtiger Grund,
 * Karten als helles Glas, Neon für Fokus und Akzente. Fehlt ein Wert (Test, fremde Seite), gilt die
 * Vorgabe von fyos-web.
 */
export function hostStile(theme: 'light' | 'dark', wurzel: HTMLElement = document.documentElement): HostStile {
  const cs = getComputedStyle(wurzel);
  const wert = (name: string, vorgabe: string) => cs.getPropertyValue(name).trim() || vorgabe;
  const hell = theme === 'light';
  const fg = wert('--color-fg', hell ? 'oklch(15% 0.02 240)' : 'oklch(95% 0.008 240)');
  const bg = wert('--color-bg', hell ? 'oklch(99% 0.006 240)' : 'oklch(17% 0.026 240)');
  const mut = wert('--color-fg-muted', hell ? 'oklch(40% 0.018 240)' : 'oklch(68% 0.015 240)');
  const leise = wert('--color-fg-subtle', hell ? 'oklch(54% 0.014 240)' : 'oklch(50% 0.012 240)');
  const akz = wert('--color-accent', hell ? '#2c7ab8' : '#5ba3d4');
  const gut = wert('--color-success', hell ? '#4d8a6a' : '#6fa888');
  const warn = wert('--color-warn', hell ? '#b07f3e' : '#c89a5e');
  const schlecht = wert('--color-error', hell ? '#a14545' : '#c77575');
  const neon1 = wert('--os-neon-1', hell ? '#06b6d4' : '#22d3ee');
  const neon2 = wert('--os-neon-2', hell ? '#d946ef' : '#e879f9');
  const mix = (farbe: string, anteil: number, mit = 'transparent') => `color-mix(in oklab, ${farbe} ${anteil}%, ${mit})`;
  // Auf hellem Glas tragen die Statusfarben als Schrift etwas dunkler (Lesbarkeit), auf dunklem wie sie sind.
  const text = (farbe: string) => (hell ? mix(farbe, 84, '#000') : farbe);
  const linie = (anteil: number) => mix(fg, anteil);
  return {
    variables: {
      '--color-background-primary': 'transparent',
      '--color-background-secondary': hell ? mix('#ffffff', 58) : mix(fg, 5),
      '--color-background-tertiary': hell ? mix('#ffffff', 82) : mix(fg, 9),
      '--color-background-inverse': fg,
      '--color-background-ghost': 'transparent',
      '--color-background-info': mix(akz, hell ? 12 : 16),
      '--color-background-success': mix(gut, hell ? 12 : 16),
      '--color-background-warning': mix(warn, hell ? 13 : 16),
      '--color-background-danger': mix(schlecht, hell ? 11 : 16),
      '--color-background-disabled': linie(hell ? 4 : 3),
      '--color-text-primary': fg,
      '--color-text-secondary': mut,
      '--color-text-tertiary': leise,
      '--color-text-inverse': bg,
      '--color-text-ghost': mut,
      '--color-text-info': text(akz),
      '--color-text-danger': text(schlecht),
      '--color-text-success': text(gut),
      '--color-text-warning': text(warn),
      '--color-text-disabled': leise,
      '--color-border-primary': linie(18),
      '--color-border-secondary': linie(11),
      '--color-border-tertiary': linie(hell ? 8 : 7),
      '--color-border-inverse': bg,
      '--color-border-ghost': 'transparent',
      '--color-border-info': mix(akz, hell ? 40 : 45),
      '--color-border-danger': mix(schlecht, hell ? 40 : 45),
      '--color-border-success': mix(gut, hell ? 40 : 45),
      '--color-border-warning': mix(warn, hell ? 40 : 45),
      '--color-border-disabled': linie(6),
      '--color-ring-primary': hell ? mix(neon1, 82, '#000') : neon1,
      '--color-ring-secondary': hell ? mix(neon2, 85, '#000') : neon2,
      '--color-ring-inverse': bg,
      '--color-ring-info': akz,
      '--color-ring-danger': schlecht,
      '--color-ring-success': gut,
      '--color-ring-warning': warn,
      '--font-sans': wert('--font-sans', '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'),
      '--font-mono': wert('--font-mono', 'ui-monospace, "SF Mono", Menlo, Consolas, monospace'),
      '--border-radius-xs': '6px',
      '--border-radius-sm': '10px',
      '--border-radius-md': '14px',
      '--border-radius-lg': '18px',
      '--border-radius-xl': '22px',
      '--border-radius-full': '9999px',
      '--border-width-regular': '1px',
    },
  };
}

/** `hostContext.containerDimensions` (MCP Apps 2026-01-26): feste Höhe ODER Obergrenze, Breite immer. */
export type ContainerMasse = { width: number; height?: number; maxHeight?: number };

/**
 * Höchste Höhe, die eine App selbst melden darf. Im OS wachsen Fenster mit ihrer App und nur die Fläche scrollt
 *; bei 4000 px scrollten lange Listen (lange Tabellen) wieder innen.
 */
export const HOEHE_MAX = 16000;

/** Maße für die App: im festen Rahmen Breite und Höhe, sonst Breite und die Obergrenze, die size-changed zulässt. */
export function containerMasse(breite: number, hoehe: number, fuellen: boolean): ContainerMasse {
  const width = Math.max(0, Math.round(breite));
  return fuellen && hoehe > 0 ? { width, height: Math.round(hoehe) } : { width, maxHeight: HOEHE_MAX };
}

/** Nächster Vorfahr, der senkrecht scrollt (im OS `.os-bildschirm`, allein `main`); null = das Dokument. */
export function scrollVorfahr(el: Element): HTMLElement | null {
  for (let e = el.parentElement; e; e = e.parentElement) {
    const o = getComputedStyle(e).overflowY;
    if (o === 'auto' || o === 'scroll') return e;
  }
  return null;
}

/**
 * Oberkante des sichtbaren Bereichs für ein App-iframe (Bildschirmkoordinaten): Rand des Scrollbereichs oder, wenn
 * tiefer, die Unterkante des klebenden Kopfs darüber (Fensterkopf im OS, Kopf der Allein-Ansicht).
 */
export function kanteOben(iframe: HTMLElement, scroller: HTMLElement | null): number {
  let k = scroller ? scroller.getBoundingClientRect().top : 0;
  const kopf = iframe.closest('[data-fenster]')?.querySelector(':scope > .os-kopf') ?? iframe.ownerDocument.querySelector('.os-allein-kopf');
  if (kopf) k = Math.max(k, kopf.getBoundingClientRect().bottom);
  return k;
}

/** Wie viele Pixel der App oben verdeckt sind (0 = ihr Anfang ist zu sehen), höchstens ihre Höhe. */
export function obenVerdeckt(iframe: HTMLElement, scroller: HTMLElement | null): number {
  const r = iframe.getBoundingClientRect();
  return Math.round(Math.min(Math.max(0, kanteOben(iframe, scroller) - r.top), Math.max(0, r.height)));
}

/**
 * Hat der Mensch gerade geklickt oder getippt? Eine Geste im iframe zählt nach HTML-Standard auch für die Seite
 * darüber. Ohne die Schnittstelle (ältere Browser, Test) lassen wir es gelten — dann entscheidet der Browser selbst.
 */
export function nutzergeste(): boolean {
  const a = (typeof navigator === 'undefined' ? undefined : navigator) as (Navigator & { userActivation?: { isActive: boolean } }) | undefined;
  return !a?.userActivation || a.userActivation.isActive;
}

/** Text einer `ui/message` (`content`: ein Block oder eine Liste von Blöcken der Form {type:'text', text}); höchstens 4000 Zeichen. */
export function nachrichtText(content: unknown): string {
  const bloecke = Array.isArray(content) ? content : [content];
  const text = bloecke
    .map((b) => (b && typeof b === 'object' && (b as { type?: unknown }).type === 'text' ? String((b as { text?: unknown }).text ?? '') : ''))
    .filter(Boolean)
    .join('\n')
    .trim();
  return text.slice(0, 4000);
}

type HostOptionen = {
  app: McpApp;
  args: Record<string, unknown>;
  /**
   * Ergebnis des Aufrufs, mit dem die App gestartet wurde. Fehlt es (ein Werkzeug mit Pflichtfeldern oder ein
   * schreibendes läuft nie von selbst), bekommt die App nur `tool-input` und holt ihre Daten selbst.
   */
  ergebnis?: CallToolResult;
  theme: () => 'light' | 'dark';
  /**
   * Die App möchte etwas ins Gespräch schreiben (ui/message). Nur wer das weitergeben kann (im OS: an den Agenten), setzt
   * es; ohne meldet der Host die Fähigkeit `message` gar nicht und lehnt die Anfrage ab.
   */
  onMessage?: (text: string) => void;
  onHeight?: (px: number) => void;
  /**
   * Das iframe füllt einen Rahmen mit fester Höhe (OS-Fenster, Kachel). Dann meldet der Host die Höhe in
   * `containerDimensions.height` und die App richtet ihren Inhalt danach (Stufen in mcp_hub/plugins/ui/_bruecke.js);
   * sonst nur die Breite und `maxHeight` — die App bestimmt ihre Höhe selbst (size-changed).
   */
  fuellen?: boolean;
  /**
   * Die App wächst mit ihrem Inhalt und die Fläche darum scrollt (OS-Fenster, Allein-Ansicht). Dann meldet der
   * Host bei jedem Bildlauf `fyos/sichtbar` {oben}: wie viel der App oben verdeckt ist. Die Brücke lässt damit
   * Kopfzeilen (`data-klebt`) und Tabellenköpfe an der sichtbaren Kante kleben (_stil.css Abschnitt 13).
   */
  sichtbar?: boolean;
  /**
   * Wer die App einbettet, vergibt einen Schlüssel (im OS die ID der Fläche, `app:<name>`); dann merkt sich der
   * Host unter ihm die Eingabe der aktuellen Ansicht und den Modellkontext (lib/mcp-apps/zustand.ts) — Grundlage
   * für „Link kopieren" und „Agent fragen" im Fensterkopf.
   */
  schluessel?: string;
};

/** Sandbox-Rechte des App-Rahmens: Skript und Formulare, sonst nichts (kein `allow-same-origin`, keine Navigation, keine Popups). */
export const APP_SANDBOX = 'allow-scripts allow-forms';

/**
 * Hängt eine App in `iframe` ein. Gibt eine Abmeldefunktion zurück.
 *
 * Sandbox: `allow-scripts` und `allow-forms` — die App bekommt den Ursprung „null", sieht weder
 * Cookies noch Speicher von fyos-web und kann nur über postMessage mit uns reden. Dazu kommen Inhaltsregeln
 * (`appCsp`): die App darf nichts nachladen und keine Verbindung aufbauen.
 * `allow-forms` braucht, wer ein `<form>` mit eigenem submit-Handler hat (Notizzettel: Eingabe + Enter). Ohne
 * das Recht blockiert der Browser schon das submit-Ereignis („Blocked form submission … sandboxed"). Ein echtes
 * Absenden bleibt gesperrt: `form-action 'none'` in `appCsp` lässt kein Ziel zu, nur per Skript behandelte
 * Formulare laufen.
 */
export async function appEinhaengen(iframe: HTMLIFrameElement, o: HostOptionen): Promise<() => void> {
  const { text: html, meta } = await ressourceLesen(o.app._meta.ui.resourceUri);
  iframe.setAttribute('sandbox', APP_SANDBOX);
  // Zwischenablage nur schreibend (Werkstatt: „Ausgabe kopieren"); lesen bleibt der App verwehrt.
  iframe.setAttribute('allow', 'clipboard-write');
  // Farbschema des Rahmens = Thema der App: weichen sie ab, gibt der Browser der App einen deckenden
  // Grund, und das Glas des Fensters scheint nicht mehr durch.
  iframe.style.colorScheme = o.theme();
  iframe.srcdoc = htmlMitCsp(html, appCsp(meta));

  const senden = (msg: unknown) => iframe.contentWindow?.postMessage(msg, '*');
  const antworten = (id: number | string, result: unknown) => senden({ jsonrpc: '2.0', id, result });
  const fehler = (id: number | string, message: string) => senden({ jsonrpc: '2.0', id, error: { code: -32000, message } });
  const melden = (method: string, params: unknown) => senden({ jsonrpc: '2.0', method, params });

  // Größe des Rahmens (MCP Apps: hostContext.containerDimensions). Kachelgrößen ändern sich, daher passt
  // sich der Inhalt an. Gemeldet wird bei jeder Änderung, je Bild höchstens einmal.
  const masse = (): ContainerMasse => containerMasse(iframe.clientWidth, iframe.clientHeight, !!o.fuellen);
  let masseZuletzt = '';
  let masseGeplant = 0;
  const masseMelden = () => {
    masseGeplant = 0;
    const m = masse();
    const neu = JSON.stringify(m);
    if (neu === masseZuletzt || !m.width) return;
    masseZuletzt = neu;
    melden('ui/notifications/host-context-changed', { containerDimensions: m });
  };
  let sichtbarZuletzt = -1;
  let sichtbarGeplant = 0;
  const scroller = o.sichtbar ? scrollVorfahr(iframe) : null;
  const sichtbarMelden = () => {
    sichtbarGeplant = 0;
    const oben = obenVerdeckt(iframe, scroller);
    if (oben === sichtbarZuletzt) return;
    sichtbarZuletzt = oben;
    melden('fyos/sichtbar', { oben });
  };
  function sichtbarPlanen() {
    if (o.sichtbar && !sichtbarGeplant) sichtbarGeplant = requestAnimationFrame(sichtbarMelden);
  }
  const groessenBeobachter = typeof ResizeObserver === 'undefined'
    ? undefined
    : new ResizeObserver(() => {
        if (!masseGeplant) masseGeplant = requestAnimationFrame(masseMelden);
      });

  // Nur Werkzeuge desselben Plugins dürfen aus der App gerufen werden.
  const plugin = o.app.name.split('__')[0];

  // Eingabe der aktuellen Ansicht: der erste Aufruf (nur lesend — schreibende gehören nie in einen Link) und danach
  // jeder lesende, für Modelle sichtbare Aufruf der App an ein Werkzeug mit derselben Oberfläche.
  if (o.schluessel) {
    zustandMerken(o.schluessel, {
      werkzeug: o.app.scope === 'READ' ? o.app.name : undefined,
      eingabe: o.app.scope === 'READ' ? o.args : undefined,
      modellKontext: undefined,
    });
  }

  const hoerer = async (e: MessageEvent) => {
    if (e.source !== iframe.contentWindow) return;
    const m = e.data as { jsonrpc?: string; id?: number | string; method?: string; params?: Record<string, unknown> };
    if (!m || m.jsonrpc !== '2.0' || !m.method) return;
    const p = m.params ?? {};
    // Eine Benachrichtigung hat keine `id` und bekommt keine Antwort (JSON-RPC); ein Aufruf, der etwas auslöst,
    // gilt ohne `id` nicht — niemand könnte das Ergebnis lesen.
    const id = m.id;
    const anfrage = id != null;
    const antwort = (result: unknown) => { if (anfrage) antworten(id, result); };
    const abgelehnt = (message: string) => { if (anfrage) fehler(id, message); };
    switch (m.method) {
      case 'ui/initialize': {
        if (!anfrage) return;
        const dims = masse();
        masseZuletzt = JSON.stringify(dims);
        groessenBeobachter?.observe(iframe);
        // Versionen: wir sprechen nur PROTOKOLL. Nach der Spezifikation antwortet der Host mit der Version, die er
        // beherrscht, auch wenn die App eine andere nannte; ob sie damit leben kann, entscheidet die App.
        antworten(id, {
          protocolVersion: PROTOKOLL,
          hostInfo: { name: HOST_NAME, version: '1' },
          // Schluessel nach dem offiziellen Schema:
          // serverTools statt tools; toolInfo.tool ist ein vollstaendiges MCP-Tool.
          // `message` nur, wo der Einbetter Nachrichten wirklich weitergibt (im OS an den Agenten).
          hostCapabilities: { serverTools: {}, openLinks: {}, ...(o.onMessage ? { message: {} } : {}), updateModelContext: {} },
          hostContext: {
            toolInfo: { tool: { name: o.app.name, description: o.app.description, inputSchema: { type: 'object', ...o.app.inputSchema } } },
            theme: o.theme(),
            styles: hostStile(o.theme()),
            locale: 'de-DE',
            timeZone: 'Europe/Berlin',
            displayMode: 'inline',
            availableDisplayModes: ['inline'],
            platform: 'web',
            ...(dims.width ? { containerDimensions: dims } : {}),
          },
        });
        return;
      }
      case 'ui/notifications/initialized':
        melden('ui/notifications/tool-input', { arguments: o.args });
        if (o.ergebnis) melden('ui/notifications/tool-result', o.ergebnis);
        sichtbarZuletzt = -1; // die App hört jetzt zu: Ausschnitt einmal frisch melden
        sichtbarPlanen();
        return;
      case 'ui/notifications/size-changed':
        // NaN und Unendlich kämen sonst als NaN durch min/max bis in die Fensterhöhe
        if (typeof p.height === 'number' && Number.isFinite(p.height)) o.onHeight?.(Math.min(Math.max(p.height, 120), HOEHE_MAX));
        sichtbarPlanen();
        return;
      case 'tools/call': {
        if (!anfrage) return;
        const name = String(p.name ?? '');
        if (!name.startsWith(`${plugin}__`)) return abgelehnt(`Werkzeug ${name} gehört nicht zu dieser App`);
        const args = (p.arguments as Record<string, unknown>) ?? {};
        try {
          // Spezifikation: der Host lässt eine App nur Werkzeuge rufen, deren `_meta.ui.visibility` „app“ enthält.
          // Ein Werkzeug, das wir noch nicht kennen (neues Plugin, alte Liste), holt die Liste einmal neu.
          let t = bekannt.get(name);
          if (!t) {
            await werkzeugeImHub().catch(() => []);
            t = bekannt.get(name);
          }
          if (!t) return abgelehnt(`Werkzeug ${name} kennt der Hub nicht`);
          if (!fuerAppSichtbar(t)) return abgelehnt(`Werkzeug ${name} ist nur für das Modell gedacht, nicht für die App`);
          // Art für die Nutzungsmessung: ein Aufruf aus der App kurz nach Klick oder Tastendruck ist bewusst,
          // ein Zeitgeber der App (Auffrischung) eine Abfrage.
          const ergebnis = await appCall(name, args, nutzergeste() ? 'bewusst' : 'abfrage');
          antworten(id, ergebnis);
          if (
            o.schluessel && !ergebnis.isError && t.scope === 'READ' && fuerModellSichtbar(t) &&
            t._meta?.ui?.resourceUri === o.app._meta.ui.resourceUri
          ) {
            zustandMerken(o.schluessel, { werkzeug: name, eingabe: args });
          }
        } catch (err) {
          abgelehnt(String((err as Error).message || err));
        }
        return;
      }
      case 'ui/open-link': {
        if (!anfrage) return;
        const url = String(p.url ?? '');
        if (!/^https?:\/\//i.test(url)) return antwort({ isError: true });
        // Eine Adresse von fyos (gleicher Ursprung, auch https://fyos.example/os?offen=…) öffnet ein Fenster im OS.
        // Fremde Adressen und Seiten ohne OS (allein im Tab) öffnen wie bisher einen Tab — aber nur nach einer
        // Geste in der App: ein Klick im iframe zählt als Nutzergeste auch für diese Seite, ohne Geste (Zeitgeber,
        // Skript) gäbe es sonst ein Tab-Aufpoppen, das der Browser ohnehin als Werbung behandelt.
        const ziel = osZielAus(url);
        if (ziel && imOsOeffnen(ziel)) return antwort({});
        if (!nutzergeste()) return antwort({ isError: true });
        window.open(url, '_blank', 'noopener');
        return antwort({});
      }
      case 'ui/message': {
        if (!anfrage) return;
        // Im OS gibt der Einbetter die Nachricht an den Agenten; sonst (oder ohne Geste, oder leer) lehnt der Host ab.
        const text = nachrichtText(p.content);
        if (!o.onMessage || !text || !nutzergeste()) return antwort({ isError: true });
        o.onMessage(text);
        return antwort({});
      }
      case 'ui/update-model-context':
        if (o.schluessel) zustandMerken(o.schluessel, { modellKontext: p });
        return antwort({});
      case 'ui/request-display-mode':
        return antwort({ mode: 'inline' });
      default:
        abgelehnt(`nicht unterstützt: ${m.method}`);
    }
  };
  window.addEventListener('message', hoerer);

  // Sichtbarer Ausschnitt (o.sichtbar): beim Bildlauf der Fläche, je Bild höchstens einmal und nur bei Änderung
  const scrollZiel: EventTarget = scroller ?? window;
  if (o.sichtbar) {
    scrollZiel.addEventListener('scroll', sichtbarPlanen, { passive: true });
    window.addEventListener('resize', sichtbarPlanen);
  }

  // Thema, OS-Farben oder Kulisse geändert → neue Gestaltungswerte, gebündelt je Bild und nur bei Änderung.
  let zuletzt = '';
  let geplant = 0;
  const kontextMelden = () => {
    geplant = 0;
    const theme = o.theme();
    const styles = hostStile(theme);
    const neu = JSON.stringify([theme, styles]);
    if (neu === zuletzt) return;
    zuletzt = neu;
    iframe.style.colorScheme = theme;
    melden('ui/notifications/host-context-changed', { theme, styles });
  };
  zuletzt = JSON.stringify([o.theme(), hostStile(o.theme())]);
  const beobachter = new MutationObserver(() => {
    if (!geplant) geplant = requestAnimationFrame(kontextMelden);
  });
  beobachter.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme', 'data-os-farben', 'style', 'class'],
  });

  return () => {
    // Die Spezifikation lässt den Host die App vor dem Abbau fragen (`ui/resource-teardown`), damit sie Zustand
    // sichern kann. Wir schicken die Anfrage und warten nicht: das iframe geht gleich, die Antwort braucht niemand.
    try { senden({ jsonrpc: '2.0', id: 'abbau', method: 'ui/resource-teardown', params: {} }); } catch { /* iframe schon weg */ }
    window.removeEventListener('message', hoerer);
    beobachter.disconnect();
    groessenBeobachter?.disconnect();
    if (geplant) cancelAnimationFrame(geplant);
    if (masseGeplant) cancelAnimationFrame(masseGeplant);
    if (o.sichtbar) {
      scrollZiel.removeEventListener('scroll', sichtbarPlanen);
      window.removeEventListener('resize', sichtbarPlanen);
    }
    if (sichtbarGeplant) cancelAnimationFrame(sichtbarGeplant);
  };
}

export function aktuellesTheme(): 'light' | 'dark' {
  const t = document.documentElement.dataset.theme;
  if (t === 'light' || t === 'dark') return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
