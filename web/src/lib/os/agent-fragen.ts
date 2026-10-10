/**
 * agent-fragen.ts — „Den Agenten fragen" von überall im OS.
 *
 * Wer dem Agenten etwas zu einer App, einer Seite oder einem Objekt fragen will, ruft `agentFragen()` —
 * oder löst direkt das Fenster-Ereignis `fyos:agent-fragen` aus:
 *
 *   window.dispatchEvent(new CustomEvent('fyos:agent-fragen', {
 *     detail: { text, kontext: { app, titel, eingabe, modellKontext }, quelle },
 *   }));
 *
 * Die Shell hängt EINEN Empfänger an (`agentFragenAnbinden`). Er öffnet das Agent-Dock und lenkt den Chat
 * (Gateway unter `/agent/`) mit der Frage als Entwurf (`?draft=`) in dessen Eingabefeld: der Mensch ändert sie
 * und sendet mit Enter.
 *
 * Seiten in OS-Fenstern laufen in iframes: dort geht die Frage per postMessage an die Shell. Eine Seite allein im
 * Browser ohne Shell öffnet den Chat mit dem Entwurf in einem neuen Tab.
 */
import { agentPfad } from '~/lib/config';

export const FRAGEN_EREIGNIS = 'fyos:agent-fragen';
/** Schlüssel der postMessage-Nachricht (iframe → Shell) */
export const FRAGEN_NACHRICHT = 'fyosAgentFragen';
/** Länge des kodierten Entwurfs in der Adresse (ein Umlaut kostet kodiert 6 Zeichen): weit unter jedem Adresslimit */
const ENTWURF_KODIERT_MAX = 5000;
/** Zeichen des Kontexts, die dem Entwurf angehängt werden */
const KONTEXT_MAX = 400;

export interface FragenKontext {
  /** Werkzeug, dessen Aufruf die Ansicht ergibt (`<plugin>__<werkzeug>`) */
  app?: string;
  /** Name der App oder Seite für Menschen */
  titel?: string;
  /** Argumente der aktuellen Ansicht */
  eingabe?: Record<string, unknown>;
  /** Letzter Inhalt aus `ui/update-model-context` */
  modellKontext?: unknown;
}

export interface AgentFrage {
  /** Die Frage, vollständig formuliert */
  text: string;
  /** Worum es geht: App-Fenster oder Objekt */
  kontext?: FragenKontext;
  /** Wer fragt (z. B. `app-rahmen`); nur für Meldungen */
  quelle?: string;
}

/** Frage samt knappem Kontext als ein Text. */
export function mitKontext(text: string, k?: FragenKontext): string {
  if (!k) return text;
  const teile: string[] = [];
  if (k.titel) teile.push(k.titel);
  if (k.app) teile.push(`(${k.app})`);
  let rest = '';
  try {
    const j = k.eingabe && Object.keys(k.eingabe).length ? JSON.stringify(k.eingabe) : '';
    const m = k.modellKontext != null ? JSON.stringify(k.modellKontext) : '';
    rest = [j, m].filter(Boolean).join(' ');
  } catch {
    rest = '';
  }
  const kopf = teile.join(' ');
  const zusatz = `${kopf}${rest ? ` ${rest}` : ''}`.trim();
  if (!zusatz) return text;
  return `${text}\n\n[Kontext: ${zusatz.length > KONTEXT_MAX ? `${zusatz.slice(0, KONTEXT_MAX)} …` : zusatz}]`;
}

/** Frage und Kontext als Eingabefeld-Entwurf im Chat. */
export function entwurfAdresse(f: AgentFrage): string {
  const voll = mitKontext(f.text, f.kontext);
  let kurz = voll;
  while (encodeURIComponent(kurz).length > ENTWURF_KODIERT_MAX) kurz = kurz.slice(0, Math.floor(kurz.length * 0.9));
  return `${agentPfad()}?draft=${encodeURIComponent(kurz === voll ? voll : `${kurz} …`)}`;
}

const istObjekt = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

/** Eingang prüfen und auf bekannte Felder zurechtstutzen (kommt auch aus Nachrichten fremder Fenster). */
function pruefen(roh: unknown): AgentFrage | null {
  if (!istObjekt(roh) || typeof roh.text !== 'string' || !roh.text.trim()) return null;
  const f: AgentFrage = { text: roh.text.trim() };
  if (istObjekt(roh.kontext)) f.kontext = roh.kontext as FragenKontext;
  if (typeof roh.quelle === 'string') f.quelle = roh.quelle;
  return f;
}

const eingebettet = (w: Window): boolean => {
  try {
    return w.self !== w.top;
  } catch {
    return true;
  }
};

/** Etwas, das postMessage übersteht (keine Funktionen, keine Zyklen); sonst ohne Kontext. */
function uebertragbar(f: AgentFrage): AgentFrage {
  try {
    return JSON.parse(JSON.stringify(f)) as AgentFrage;
  } catch {
    return { text: f.text, quelle: f.quelle };
  }
}

/** Den Agenten etwas fragen — aus einer Seite im OS-Fenster, einer Shell-Fläche oder einer Seite allein im Browser. */
export function agentFragen(frage: AgentFrage, d: { fenster?: Window } = {}): void {
  const w = d.fenster ?? window;
  const f = pruefen(frage);
  if (!f) return;
  if (eingebettet(w)) {
    try {
      w.parent.postMessage({ [FRAGEN_NACHRICHT]: uebertragbar(f) }, w.location.origin);
      return;
    } catch {
      /* Eltern nicht erreichbar: wie allein im Browser */
    }
  }
  const ev = new CustomEvent<AgentFrage>(FRAGEN_EREIGNIS, { detail: f, cancelable: true });
  w.dispatchEvent(ev);
  // Niemand in diesem Fenster nimmt sie an (keine Shell): Chat mit dem Entwurf in einem neuen Tab
  if (!ev.defaultPrevented) w.open(entwurfAdresse(f), '_blank', 'noopener');
}

export interface Anbindung {
  /** Agent-Dock öffnen bzw. nach vorn holen; mit `adresse` den Chat dorthin lenken (Entwurf) */
  zeigen: (adresse?: string) => void;
}

/** Empfänger anhängen (einmal, in der Shell). Gibt die Abmeldung zurück. */
export function agentFragenAnbinden(a: Anbindung, d: { fenster?: Window } = {}): () => void {
  const w = d.fenster ?? window;
  const annehmen = (roh: unknown): boolean => {
    const f = pruefen(roh);
    if (f) a.zeigen(entwurfAdresse(f));
    return !!f;
  };
  const imEreignis = (e: Event): void => {
    if (annehmen((e as CustomEvent).detail)) e.preventDefault();
  };
  const imKanal = (e: MessageEvent): void => {
    if (e.origin !== w.location.origin) return;
    const roh = istObjekt(e.data) ? e.data[FRAGEN_NACHRICHT] : undefined;
    if (roh !== undefined) annehmen(roh);
  };
  w.addEventListener(FRAGEN_EREIGNIS, imEreignis);
  w.addEventListener('message', imKanal);
  return () => {
    w.removeEventListener(FRAGEN_EREIGNIS, imEreignis);
    w.removeEventListener('message', imKanal);
  };
}
