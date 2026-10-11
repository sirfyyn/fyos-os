/**
 * ziehen.ts — eine Ziehsprache für das ganze OS.
 *
 * Jede Stelle verstand früher nur ihr eigenes Format; hier gibt es eine gemeinsame Sprache. Was gezogen wird,
 * heißt ein Gut:
 *
 *   fw:<fläche>          ein Fenster (Kopf im Raster oder Symbol im Dock)
 *   fl:<fläche>          eine Fläche aus dem Start
 *   fyos://<typ>/<id>    ein Ding aus einer Fläche: Notiz, Termin, Aufgabe … Die Typen registrieren Plugins
 *                        (`registriereFlaechen({ dinge })`, lib/os/register.ts)
 *
 * und jedes Ziel der Shell versteht jedes Gut:
 *
 *   Schreibtisch, Fenster   Fenster: umordnen · Fläche: hier öffnen · Ding: seine Fläche öffnen und ihr sagen,
 *                           welches (Nachricht `fyosOeffne` an die Seite)
 *   Bildschirm-Punkt        Fenster: dorthin verschieben · Fläche/Ding: dort öffnen. Verweilen wechselt hin
 *                           (wie ein Ordner am Mac, der beim Darüberhalten aufspringt)
 *   „+“                     dasselbe auf einem neuen Bildschirm
 *   Agent                   den Agenten dazu fragen
 *   Fenster einer Hub-App   Ding mit Übergabe: Hinweis nennt die Wirkung, die App zeigt Plan und fragt (`ablageAufApp`);
 *                           ohne Übergabe nur: den Agenten dazu fragen
 *
 * Aus einer Hub-App heraus zieht `App.ziehbar` (mcp_hub/plugins/ui/_bruecke.js): die App meldet dem Host `fyos/zug`, der
 * Host ruft `zugBeginnt` — danach ist es für die Ziele ein Zug wie jeder andere.
 *
 * Während des Ziehens gibt der Browser nur `types` heraus, nicht den Inhalt. Darum trägt jedes Gut einen
 * zusätzlichen Schlüssel `application/x-fyos-<art>`: Ein Ziel weiß schon beim Darüberfahren, was kommt, und
 * sagt, was beim Loslassen passiert (`wasPassiert`).
 */
import { createSignal } from 'solid-js';
import { agentName } from '~/lib/config';
import { anApp } from '~/lib/mcp-apps/eingehaengt';
import { registrierteDinge, registrierteUebergabe, type Uebergabe } from './register';

/** Typ eines ziehbaren Dings (`fyos://<typ>/<id>`); bekannt sind die registrierten. */
export type DingTyp = string;

export type Gut =
  | { art: 'fenster'; id: string }
  | { art: 'flaeche'; id: string }
  | { art: 'ding'; typ: DingTyp; id: string; label?: string };

/** Woran ein Ziel ein Gut schon während des Ziehens erkennt: `fenster`, `flaeche` oder der Typ eines Dings. */
export type GutArt = 'fenster' | 'flaeche' | DingTyp;

export type ZielArt = 'schreibtisch' | 'bildschirm' | 'start' | 'neu' | 'agent';

const SCHLUESSEL = 'application/x-fyos-';
const LABEL = 'text/x-fyos-label';

/** Nachricht einer Seite im Fenster an die Shell: es wird gezogen (`art`) bzw. nicht mehr (null). */
export const ZUG_NACHRICHT = 'fyosZug';
/** Nachricht der Shell an eine Seite im Fenster: zeig dieses Ding (`{ typ, id }`). */
export const OEFFNE_NACHRICHT = 'fyosOeffne';

/** Ist das ein registrierter Typ? */
export const istDingTyp = (t: string): boolean => !!registrierteDinge(t);

/** Menschlicher Name eines Dings (Einzahl); unbekannte Typen heißen „Objekt“. */
export const dingName = (typ: DingTyp): string => registrierteDinge(typ)?.name ?? 'Objekt';

/** `fyos://<typ>/<id>` → Typ und Kennung; nur registrierte Typen. */
export function dingAusUri(uri: string): { typ: DingTyp; id: string } | null {
  const m = uri.match(/^fyos:\/\/([\w-]+)\/(.+)$/);
  if (!m || !istDingTyp(m[1] ?? '') || m[2] === undefined) return null;
  return { typ: m[1]!, id: m[2] };
}

/** Ein Gut in den Zug legen (dragstart). `label` ist der Titel für Menschen (Hinweis, Frage an den Agenten). */
export function gutSetzen(dt: DataTransfer | null | undefined, gut: Gut, label?: string): void {
  if (!dt) return;
  if (gut.art === 'fenster') {
    dt.setData('text/plain', `fw:${gut.id}`);
    dt.setData(`${SCHLUESSEL}fenster`, gut.id);
    dt.effectAllowed = 'move';
  } else if (gut.art === 'flaeche') {
    dt.setData('text/plain', `fl:${gut.id}`);
    dt.setData(`${SCHLUESSEL}flaeche`, gut.id);
    dt.effectAllowed = 'copyMove';
  } else {
    const uri = `fyos://${gut.typ}/${gut.id}`;
    dt.setData('text/plain', uri);
    dt.setData('text/uri-list', uri);
    dt.setData(`${SCHLUESSEL}${gut.typ}`, gut.id);
    dt.effectAllowed = 'copyMove';
  }
  const l = label ?? (gut.art === 'ding' ? gut.label : undefined);
  if (l) dt.setData(LABEL, l);
}

/** Das Gut beim Loslassen (drop) — oder null, wenn es keines der OS ist (Text, Dateien, Fremdes). */
export function gutLesen(dt: DataTransfer | null | undefined): Gut | null {
  if (!dt) return null;
  const roh = (dt.getData('text/plain') || dt.getData('text/uri-list') || '').trim().split('\n')[0]!.trim();
  if (roh.startsWith('fw:') && roh.length > 3) return { art: 'fenster', id: roh.slice(3) };
  if (roh.startsWith('fl:') && roh.length > 3) return { art: 'flaeche', id: roh.slice(3) };
  const ref = dingAusUri(roh);
  if (!ref) return null;
  const label = dt.getData(LABEL) || undefined;
  return { art: 'ding', typ: ref.typ, id: ref.id, ...(label ? { label } : {}) };
}

/** Was gerade gezogen wird, nur aus `types` (dragenter/dragover). null = nichts vom OS. */
export function gutArt(dt: DataTransfer | null | undefined): GutArt | null {
  if (!dt) return null;
  for (const t of Array.from(dt.types ?? [])) {
    if (!t.startsWith(SCHLUESSEL)) continue;
    const art = t.slice(SCHLUESSEL.length);
    if (art === 'fenster' || art === 'flaeche') return art;
    if (istDingTyp(art)) return art;
  }
  // Zieht eine Hub-App (Sandbox ohne eigenen Ursprung) etwas heraus, hat sie es der Shell gemeldet (`fyos/zug`). Mancher Browser
  // reicht eigene Schlüssel nicht über Fenstergrenzen weiter, `text/plain` mit der Adresse des Dings kommt immer an: dann
  // gilt, was die Shell vom Zug weiß.
  const z = zug();
  if (z?.quelle && z.art !== 'fenster' && z.art !== 'flaeche' && istDingTyp(z.art) && Array.from(dt.types ?? []).includes('text/plain')) return z.art;
  return null;
}

/**
 * Was beim Loslassen passiert — als kurzer Satz für den Hinweis am Ziel. null = dieses Ziel nimmt das nicht an.
 * `name` ist der Name des Ziels (Bildschirm).
 */
export function wasPassiert(art: GutArt | null, ziel: ZielArt, name?: string): string | null {
  if (!art) return null;
  const wen = art !== 'fenster' && art !== 'flaeche' ? dingName(art) : null;
  const dort = name ? `„${name}“` : 'diesen Bildschirm';
  switch (ziel) {
    case 'schreibtisch':
      if (art === 'fenster') return 'Hier einordnen';
      if (art === 'flaeche') return 'Hier öffnen';
      return `${wen} öffnen`;
    case 'bildschirm':
      if (art === 'fenster') return `Auf ${dort} verschieben`;
      return `Auf ${dort} öffnen`;
    case 'start':
      // Der Startbildschirm ist ein Launcher: dort liegen keine Fenster. Verweilen wechselt trotzdem hin.
      return null;
    case 'neu':
      if (art === 'fenster') return 'Auf neuen Bildschirm';
      return 'Auf neuem Bildschirm öffnen';
    case 'agent':
      return `${agentName()} dazu fragen`;
  }
}

/**
 * Was beim Loslassen auf dem Fenster einer Hub-App passiert, wenn dort mehr gilt als „Ding öffnen“:
 *   Es gibt eine Übergabe für dieses Ding und diese App   → ihr Satz (`wirkung`); die App zeigt Plan und fragt.
 *   Es gibt keine (das Ding gehört einer anderen App)      → nur der Agent: „dazu fragen“.
 * null = hier gilt die allgemeine Regel (Fenster ordnen sich ein, Flächen öffnen, ein Ding der eigenen App wird gezeigt).
 */
export type AppAblage = { modus: 'uebergabe'; text: string; uebergabe: Uebergabe } | { modus: 'agent'; text: string };
export function ablageAufApp(art: GutArt | null, flaecheId: string): AppAblage | null {
  if (!art || art === 'fenster' || art === 'flaeche' || !istDingTyp(art)) return null;
  if (registrierteDinge(art)?.flaeche === flaecheId) return null;
  const u = registrierteUebergabe(art, flaecheId);
  if (u) return { modus: 'uebergabe', text: u.wirkung, uebergabe: u };
  return { modus: 'agent', text: `${agentName()} dazu fragen` };
}

/** Die Frage an den Agenten, wenn ein Ding auf eine App fällt, die es nicht von selbst annimmt. */
export function frageUebergabe(gut: Extract<Gut, { art: 'ding' }>, appTitel: string): string {
  const was = `${dingName(gut.typ)} ${gut.id}${gut.label ? ` („${gut.label}“)` : ''}`;
  return `Ich habe ${was} auf „${appTitel}“ gezogen. Was lässt sich damit dort tun, und wie legst du es an?`;
}

/** Die Frage an den Agenten zu einem Gut (Entwurf; der Mensch kann sie ändern, bevor sie rausgeht). */
export function frageZu(gut: Gut, titel?: string): string {
  if (gut.art === 'ding') {
    const was = `${dingName(gut.typ)} ${gut.id}${gut.label ? ` („${gut.label}“)` : ''}`;
    return `Schau dir ${was} an: Worum geht es, und was ist zu tun?`;
  }
  return `Was fällt dir an „${titel ?? gut.id}“ gerade auf?`;
}

/** Die Seite, auf der ein Ding lebt (für die Suche nach der passenden Fläche). */
export const dingPfad = (typ: DingTyp): string | undefined => registrierteDinge(typ)?.pfad;

// ── Zug-Zustand (eine Quelle für Shell, Fenster und Dock) ────────────────────────────────────────

export interface Zug {
  art: GutArt;
  /** Fläche, wenn ein Fenster oder eine Fläche aus der Shell selbst gezogen wird (ein Fenster nimmt sich nicht selbst an) */
  id?: string;
  /** Fenster (iframe) der Seite, aus der gezogen wird — deren Zeiger bleiben an, damit sie selbst ablegen kann */
  quelle?: MessageEventSource | null;
}
const [zug, setZug] = createSignal<Zug | null>(null);
/** Was gerade gezogen wird (null = nichts). */
export const aktuellerZug = zug;
export const zugBeginnt = (z: Zug): void => {
  setZug(z);
};
export const zugEndet = (): void => {
  setZug(null);
};

// ── Hinweis am Ziel („Auf „Notizen“ verschieben") ────────────────────────────────────────────────

export interface ZugHinweis {
  text: string;
  /** Mitte oben des Ziels (Bildschirmkoordinaten) — der Hinweis steht darüber */
  x: number;
  y: number;
}
const [hinweis, setHinweis] = createSignal<ZugHinweis | null>(null);
export const zugHinweis = hinweis;
let hinweisVon: Element | null = null;
export function hinweisZeigen(el: Element, text: string | null): void {
  if (!text) return hinweisWeg(el);
  const r = el.getBoundingClientRect();
  hinweisVon = el;
  const alt = hinweis();
  const x = r.left + r.width / 2;
  const y = r.top;
  if (alt && alt.text === text && Math.abs(alt.x - x) < 1 && Math.abs(alt.y - y) < 1) return;
  setHinweis({ text, x, y });
}
/** Hinweis weg — mit `el` nur, wenn er noch zu diesem Ziel gehört (dragleave des alten nach dragenter des neuen). */
export function hinweisWeg(el?: Element): void {
  if (el && hinweisVon && el !== hinweisVon) return;
  hinweisVon = null;
  setHinweis(null);
}

// ── Ein Ablageziel: dieselben vier Handgriffe für Dock-Punkt, „+“, Agent, Übersicht ───────────────

/** So lange über einem Ziel verweilen, bis es aufspringt (Bildschirm wechseln, Agent öffnen). */
export const VERWEILEN_MS = 650;

export interface ZielOptionen {
  ziel: ZielArt | (() => ZielArt);
  /** Name des Ziels für den Hinweis (Bildschirm) */
  name?: () => string | undefined;
  /** Nimmt das Ziel diese Art an? Ohne: wenn `wasPassiert` etwas zu sagen hat. */
  annehmen?: (art: GutArt) => boolean;
  ablegen: (g: Gut) => void;
  /** Hervorhebung des Ziels an/aus */
  an?: (ja: boolean) => void;
  /** Nach `VERWEILEN_MS` über dem Ziel: aufspringen */
  verweilen?: () => void;
}

export interface ZielHandler {
  onDragEnter: (e: DragEvent) => void;
  onDragOver: (e: DragEvent) => void;
  onDragLeave: (e: DragEvent) => void;
  onDrop: (e: DragEvent) => void;
}

export function ablageZiel(o: ZielOptionen): ZielHandler {
  let uhr: ReturnType<typeof setTimeout> | undefined;
  const zielArt = () => (typeof o.ziel === 'function' ? o.ziel() : o.ziel);
  const aus = (el?: Element) => {
    clearTimeout(uhr);
    uhr = undefined;
    o.an?.(false);
    hinweisWeg(el);
  };
  return {
    onDragEnter: (e) => {
      if (!gutArt(e.dataTransfer) || !o.verweilen || uhr !== undefined) return;
      uhr = setTimeout(() => {
        uhr = undefined;
        o.verweilen?.();
      }, VERWEILEN_MS);
    },
    onDragOver: (e) => {
      const art = gutArt(e.dataTransfer);
      if (!art) return;
      const text = wasPassiert(art, zielArt(), o.name?.());
      if (!(o.annehmen ? o.annehmen(art) : !!text)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = art === 'fenster' ? 'move' : 'copy';
      o.an?.(true);
      hinweisZeigen(e.currentTarget as Element, text);
    },
    onDragLeave: (e) => {
      const el = e.currentTarget as Element;
      if (e.relatedTarget instanceof Node && el.contains(e.relatedTarget)) return;
      aus(el);
    },
    onDrop: (e) => {
      const el = e.currentTarget as Element;
      aus(el);
      const art = gutArt(e.dataTransfer);
      // Nur, was das Ziel auch beim Darüberfahren angenommen hat (ein Kind, das abgelegt hat, reicht nicht durch)
      if (!art || !(o.annehmen ? o.annehmen(art) : !!wasPassiert(art, zielArt(), o.name?.()))) return;
      const g = gutLesen(e.dataTransfer);
      if (!g) return;
      e.preventDefault();
      e.stopPropagation();
      zugEndet();
      o.ablegen(g);
    },
  };
}

// ── Zugbild: eine kleine Pille statt eines Bildschirmfotos des Fensterkopfs ──────────────────────

/** Setzt ein ruhiges Zugbild (Titel in einer Glaspille). Ohne DOM (Tests) passiert nichts. */
export function zugBild(dt: DataTransfer | null | undefined, titel: string): void {
  if (!dt || typeof document === 'undefined' || typeof dt.setDragImage !== 'function') return;
  const el = document.createElement('div');
  el.className = 'os-zugbild';
  el.textContent = titel;
  document.body.appendChild(el);
  dt.setDragImage(el, 18, 18);
  // Der Browser fotografiert das Element sofort; danach darf es weg
  setTimeout(() => el.remove(), 0);
}

// ── Seiten in Fenstern: Ding zeigen ──────────────────────────────────────────────────────────────

/**
 * Nachrichten, die auf eine Seite warten, deren Fenster gerade erst aufgeht (Fläche → Nachricht, Zeitpunkt).
 * Mit Ablauf: Ging das Fenster nicht auf, sprang sonst Stunden später beim Öffnen ein altes Objekt auf.
 */
const wartend = new Map<string, { n: unknown; t: number }>();
export const WARTEN_MS = 30_000;

/**
 * Schickt einer Seite im OS-Fenster eine Nachricht (z. B. „zeig Objekt X“). Ist das Fenster schon geladen,
 * geht sie sofort hin; sonst holt sie das Fenster nach dem Laden ab (`zustellungAbholen`).
 */
export function zustellen(flaecheId: string, nachricht: unknown): void {
  // Hub-Apps leben im Sandbox-iframe (Ursprung „null“): sie hört der Host (lib/mcp-apps/host.ts), nicht die Seite selbst
  if (flaecheId.startsWith('app:')) {
    const o = (nachricht as { [OEFFNE_NACHRICHT]?: { typ?: unknown; id?: unknown } } | null)?.[OEFFNE_NACHRICHT];
    if (o && typeof o.typ === 'string' && typeof o.id === 'string') anApp(flaecheId, 'fyos/oeffne', { typ: o.typ, id: o.id });
    return;
  }
  if (typeof document !== 'undefined') {
    const ifr = document.querySelector<HTMLIFrameElement>(`[data-fenster="${CSS.escape(flaecheId)}"] iframe[data-geladen]`);
    if (ifr?.contentWindow) {
      ifr.contentWindow.postMessage(nachricht, location.origin);
      return;
    }
  }
  wartend.set(flaecheId, { n: nachricht, t: Date.now() });
}

/** Vom Fenster nach dem Laden seiner Seite gerufen. */
export function zustellungAbholen(flaecheId: string, ziel: Window | null): void {
  const w = wartend.get(flaecheId);
  if (!ziel || !w) return;
  wartend.delete(flaecheId);
  if (Date.now() - w.t <= WARTEN_MS) ziel.postMessage(w.n, location.origin);
}

/** Für Tests: offene Zustellungen. */
export const _wartend = wartend;
