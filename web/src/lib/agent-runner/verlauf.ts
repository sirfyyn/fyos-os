/**
 * verlauf.ts — aus der flachen Anzeige (anzeige.ts) den Verlauf, den ein Mensch lesen will.
 *
 * Ein Gespräch mit Agent ist kein Terminal: du schreibst, Agent antwortet. Was dazwischen passiert (Gedanken,
 * Werkzeugaufrufe, Zwischentexte) ist ARBEIT und gehört in eine Zeile je Zug, aufklappbar. Die Antwort ist der Text,
 * der nach der letzten Arbeit kommt. die eigenständige Arbeit des Agenten (Eingänge aus dem Hub, Takt, Läufe) ist ein eigener,
 * dezenter Punkt (`autonom`), den `/live aus` ausblendet.
 *
 * Reine Logik ohne DOM, damit sie sich mit echten Ereignisformen des Runners testen lässt.
 */
import type { Anzeige, AnzeigeBlock, KartenStatus, WerkzeugKarte } from './anzeige';
import { tr } from '~/lib/i18n';

// ── Werkzeugtitel in Klartext ────────────────────────────────────────────────

const WORTE: Record<string, string> = {
  vorgaenge: 'Vorgänge',
  vorgang: 'Vorgang',
  laeufe: 'Läufe',
  repos: 'Repos',
  cluster: 'Cluster',
  haus: 'Haus',
  wissen: 'Wissen',
  skills: 'Skills',
  werkstatt: 'Werkstatt',
  chat: 'Chat',
  agenten: 'Agenten',
  zeigen: 'gezeigt',
  lesen: 'gelesen',
  suchen: 'gesucht',
  anlegen: 'angelegt',
  senden: 'gesendet',
  ablegen: 'abgelegt',
  eintragen: 'eingetragen',
  ausfuehren: 'ausgeführt',
};

const KERN_ARGUMENTE = ['id', 'vorgang', 'nummer', 'name', 'q', 'suche', 'titel', 'raum', 'text', 'befehl', 'pfad', 'url'];

function kuerzeZeile(wert: unknown, n: number): string {
  const t = String(wert ?? '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
}

function erstes(args: Record<string, unknown>, namen: string[]): string {
  for (const n of namen) {
    const w = args[n];
    if (typeof w === 'string' && w.trim()) return w;
    if (typeof w === 'number') return String(w);
  }
  return '';
}

function dateiname(pfad: string): string {
  const teile = pfad.split(/[\\/]/).filter(Boolean);
  return teile[teile.length - 1] ?? pfad;
}

/** Der Befehl ohne `cd … &&`-Vorspann, auf das Wesentliche gekürzt: „git push“, „kubectl get pods“. */
export function befehlKern(befehl: string): string {
  let b = befehl.trim();
  b = b.replace(/^(?:cd\s+\S+\s*(?:&&|;)\s*)+/, '');
  const erste = b.split('\n')[0] ?? b;
  return kuerzeZeile(erste, 64);
}

/** „vorgaenge.zeigen“ → { ns: 'Vorgänge', verb: 'gezeigt' }; unbekannte Namen bleiben, wie sie sind. */
function hubName(name: string): { ns: string; verb: string } {
  const [ns = '', ...rest] = name.split('.');
  const verb = rest.join('.');
  return { ns: WORTE[ns] ? tr(WORTE[ns]) : ns, verb: WORTE[verb] ? tr(WORTE[verb]) : verb };
}

/**
 * Titel einer Werkzeugkarte in Klartext aus Werkzeugname und Kernargument.
 * „vorgaenge.zeigen“ mit id INC-4905 → „Vorgang INC-4905 gelesen“; bash → „Shell: git push“.
 */
export function werkzeugTitel(name: string, args: Record<string, unknown> = {}): string {
  const a = args && typeof args === 'object' ? args : {};
  switch (name) {
    case 'bash':
      return tr('Shell: {0}', befehlKern(erstes(a, ['command', 'befehl'])) || tr('Befehl'));
    case 'read':
      return tr('Datei gelesen: {0}', dateiname(erstes(a, ['path', 'pfad', 'file'])) || '?');
    case 'write':
      return tr('Datei geschrieben: {0}', dateiname(erstes(a, ['path', 'pfad', 'file'])) || '?');
    case 'edit':
      return tr('Datei geändert: {0}', dateiname(erstes(a, ['path', 'pfad', 'file'])) || '?');
    case 'hub_suchen':
      return tr('Werkzeuge gesucht: {0}', kuerzeZeile(erstes(a, ['suche']), 50) || tr('Verzeichnis'));
    case 'hub_schema':
      return tr('Schema gelesen: {0}', erstes(a, ['werkzeug']) || '?');
    case 'hub_aufrufen': {
      const werkzeug = erstes(a, ['werkzeug']);
      const argumente = (a.argumente && typeof a.argumente === 'object' ? a.argumente : {}) as Record<string, unknown>;
      return hubTitel(werkzeug, argumente);
    }
    case 'freigabe_bitten':
      return tr('Freigabe erbeten: {0}', kuerzeZeile(erstes(a, ['aktion']), 70) || '?');
    case 'zustand_lesen':
      return tr('Zustand gelesen') + (erstes(a, ['schluessel']) ? `: ${erstes(a, ['schluessel'])}` : '');
    case 'zustand_schreiben':
      return tr('Zustand gesetzt') + (erstes(a, ['schluessel']) ? `: ${erstes(a, ['schluessel'])}` : '');
    case 'aufgabe_starten':
      return tr('Aufgabe gestartet: {0}', kuerzeZeile(erstes(a, ['titel', 'auftrag']), 60) || '?');
    case 'aufgaben_liste':
      return tr('Aufgaben angesehen');
    case 'web_suchen':
      return tr('Web gesucht: {0}', kuerzeZeile(erstes(a, ['suche', 'q', 'query']), 60) || '?');
    case 'web_holen':
      return tr('Seite geladen: {0}', hostVon(erstes(a, ['url'])) || '?');
    case 'knoten_liste':
      return tr('Knoten angesehen');
    case 'knoten_befehl':
      return tr('Befehl auf {0}: {1}', erstes(a, ['knoten', 'id']) || tr('Knoten'), befehlKern(erstes(a, ['befehl', 'command'])) || '?');
    case 'unteragent':
      return tr('Unteragent: {0}', kuerzeZeile(erstes(a, ['auftrag', 'aufgabe', 'titel']), 60) || tr('beauftragt'));
    case 'matrix_senden':
      return tr('Matrix-Nachricht gesendet');
    case 'agent_bericht':
      return tr('Bericht abgelegt');
    case 'kontextbuch_lesen':
      return tr('Kontextbuch gelesen');
    case 'kontextbuch_schreiben':
      return tr('Kontextbuch ergänzt');
    case 'browser':
      return tr('Browser: {0}', kuerzeZeile(erstes(a, ['aktion', 'url']), 60) || tr('Seite'));
    default:
      break;
  }
  if (name.startsWith('desktop_')) return `Desktop: ${name.slice(8).replace(/_/g, ' ')}`;
  if (name.startsWith('hintergrund_')) return tr('Hintergrundjob: {0}', name.slice(12).replace(/_/g, ' '));
  if (name.includes('.')) return hubTitel(name, a);
  const arg = kuerzeZeile(erstes(a, KERN_ARGUMENTE), 50);
  return `${name.replace(/_/g, ' ')}${arg ? `: ${arg}` : ''}`;
}

function hostVon(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return kuerzeZeile(url, 40);
  }
}

function hubTitel(werkzeug: string, argumente: Record<string, unknown>): string {
  if (!werkzeug) return tr('Hub-Werkzeug aufgerufen');
  const arg = kuerzeZeile(erstes(argumente, KERN_ARGUMENTE), 50);
  if (werkzeug === 'vorgaenge.zeigen' && arg) return tr('Vorgang {0} gelesen', arg);
  const { ns, verb } = hubName(werkzeug);
  return `${ns}${verb ? ` ${verb}` : ''}${arg ? `: ${arg}` : ''}`;
}

// ── Ausgaben kürzen, Zeiten sagen ────────────────────────────────────────────

export const AUSGABE_MAX = 1600;

/** Kürzt eine lange Rohausgabe: Anfang und Ende bleiben (Fehler stehen meist am Ende). */
export function kuerzeAusgabe(text: string, max: number = AUSGABE_MAX): { text: string; gekuerzt: boolean } {
  if (text.length <= max) return { text, gekuerzt: false };
  const kopf = Math.floor(max * 0.55);
  const fuss = max - kopf;
  return { text: `${text.slice(0, kopf)}\n… ${tr('{0} Zeichen gekürzt', text.length - max)} …\n${text.slice(text.length - fuss)}`, gekuerzt: true };
}

/** „38 s“, „2 min 5 s“, „1 h 3 min“; unter einer Sekunde leer. */
export function dauerText(ms: number | null | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 1000) return '';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const min = Math.floor(s / 60);
  if (min < 60) return s % 60 ? `${min} min ${s % 60} s` : `${min} min`;
  const h = Math.floor(min / 60);
  return min % 60 ? `${h} h ${min % 60} min` : `${h} h`;
}

// ── Schritte und Züge ────────────────────────────────────────────────────────

export type Schritt =
  | {
      art: 'werkzeug';
      schluessel: string;
      titel: string;
      name: string;
      status: KartenStatus;
      dauerMs: number | null;
      seit: number | null;
      eingabe: string;
      ausgabe: string;
      gekuerzt: boolean;
      diagnose: string;
      /** Erste Zeile der Ausgabe bei einem Fehler, für die Zeile im geschlossenen Zustand. */
      fehlerZeile: string;
    }
  | { art: 'gedanken'; schluessel: string; text: string; woerter: number }
  | { art: 'notiz'; schluessel: string; text: string };

export interface Zug {
  art: 'zug';
  schluessel: string;
  name: string;
  zeit: number | null;
  /** Erster und letzter Zeitstempel des Zugs (ms), für die Dauer. */
  start: number | null;
  ende: number | null;
  /** Der Agent arbeitet gerade an diesem Zug. */
  laeuft: boolean;
  /** Der Text wird gerade geschrieben. */
  schreibt: boolean;
  schritte: Schritt[];
  /** Die Antwort: Text nach der letzten Arbeit. */
  antwort: string;
  /** Anzahl Werkzeugschritte (ohne Gedanken und Notizen). */
  schrittZahl: number;
  fehlerZahl: number;
  verbrauch: string;
}

export type VerlaufsPunkt =
  | { art: 'tag'; schluessel: string; text: string }
  | { art: 'mensch'; schluessel: string; text: string; zeit: number | null; steuern: boolean; quelle: string }
  | { art: 'system'; schluessel: string; titel: string; text: string; zeit: number | null }
  | { art: 'autonom'; schluessel: string; quelle: string; text: string; zeit: number | null; lauf: boolean; zug: Zug | null }
  | Zug;

function schrittAusKarte(k: WerkzeugKarte, schluessel: string): Schritt {
  const roh = k.ausgabe ?? '';
  const g = kuerzeAusgabe(roh);
  const fehler = k.status === 'fehler';
  return {
    art: 'werkzeug',
    schluessel,
    titel: werkzeugTitel(k.name, argsAusEingabe(k.eingabe)),
    name: k.name,
    status: k.status,
    dauerMs: k.dauerMs ?? null,
    seit: k.seit ?? null,
    eingabe: k.eingabe,
    ausgabe: g.text,
    gekuerzt: g.gekuerzt,
    diagnose: k.diagnose,
    fehlerZeile: fehler ? kuerzeZeile(roh.split('\n').find((z) => z.trim()) ?? roh, 140) : '',
  };
}

function argsAusEingabe(eingabe: string): Record<string, unknown> {
  if (!eingabe) return {};
  try {
    const w = JSON.parse(eingabe) as unknown;
    return w && typeof w === 'object' && !Array.isArray(w) ? (w as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function neuerZug(schluessel: string, name: string): Zug {
  return { art: 'zug', schluessel, name, zeit: null, start: null, ende: null, laeuft: false, schreibt: false, schritte: [], antwort: '', schrittZahl: 0, fehlerZahl: 0, verbrauch: '' };
}

/** Hängt die Blöcke einer Nachricht an einen Zug (noch ohne zu entscheiden, was Antwort ist). */
function ordneBloecke(bloecke: AnzeigeBlock[], schluessel: string): Schritt[] {
  const aus: Schritt[] = [];
  bloecke.forEach((b, i) => {
    const s = `${schluessel}.${i}`;
    if (b.art === 'text') aus.push({ art: 'notiz', schluessel: s, text: b.text });
    else if (b.art === 'gedanken') aus.push({ art: 'gedanken', schluessel: s, text: b.text, woerter: b.text.split(/\s+/).filter(Boolean).length });
    else aus.push(schrittAusKarte(b.karte, `${s}.${b.karte.id ?? b.karte.name}`));
  });
  return aus;
}

/** Trennt die Schritte eines Zugs in Arbeit (alles bis zur letzten Nicht-Text-Stelle) und Antwort (der Text danach). */
function schliesse(z: Zug): Zug {
  const s = z.schritte;
  let letzteArbeit = -1;
  s.forEach((x, i) => {
    if (x.art !== 'notiz') letzteArbeit = i;
  });
  const antworten = s.slice(letzteArbeit + 1).flatMap((x) => (x.art === 'notiz' ? [x.text] : []));
  z.antwort = antworten.join('\n\n').trim();
  z.schritte = s.slice(0, letzteArbeit + 1);
  z.schrittZahl = z.schritte.filter((x) => x.art === 'werkzeug').length;
  z.fehlerZahl = z.schritte.filter((x) => x.art === 'werkzeug' && x.status === 'fehler').length;
  return z;
}

const TAGE = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];

/** „Heute“, „Gestern“, sonst „Montag, 20.10.“ */
export function tagText(ts: number, jetzt: number = Date.now()): string {
  const d = new Date(ts);
  const j = new Date(jetzt);
  const tag = (x: Date) => Date.UTC(x.getFullYear(), x.getMonth(), x.getDate());
  const diff = Math.round((tag(j) - tag(d)) / 86_400_000);
  if (diff === 0) return 'Heute';
  if (diff === 1) return 'Gestern';
  return `${TAGE[d.getDay()]}, ${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.`;
}

export interface VerlaufOptionen {
  jetzt?: number;
  /** Tagestrenner einfügen (Standard: ja). */
  tage?: boolean;
  /** Name unter dem Zug, solange noch keine Nachricht von ihm da ist. */
  agentName?: string;
}

/** Baut den Verlauf aus der Anzeige-Liste. */
export function baueVerlauf(anzeige: Anzeige[], opt: VerlaufOptionen = {}): VerlaufsPunkt[] {
  const jetzt = opt.jetzt ?? Date.now();
  const agentName = opt.agentName ?? 'Agent';
  const aus: VerlaufsPunkt[] = [];
  /** Der Zug erbt seinen Schlüssel vom Punkt davor: er bleibt gleich, wenn aus „schreibt“ der fertige Eintrag wird. */
  let anker = 'anfang';
  /** Wann der Punkt davor war: ab da zählt die Arbeit des Zugs (auch die Zeit, bis das Modell antwortet). */
  let ankerZeit: number | null = null;
  let zug: Zug | null = null;
  let rohe: Schritt[] = [];
  /** Ein Eingang, auf den der nächste Zug antwortet: wird zusammen mit ihm ein autonomer Punkt. */
  let eingang: Extract<VerlaufsPunkt, { art: 'autonom' }> | null = null;

  const beendeZug = () => {
    if (!zug) return;
    zug.schritte = rohe;
    const fertig = schliesse(zug);
    if (eingang) {
      eingang.zug = fertig;
      eingang = null;
    } else aus.push(fertig);
    zug = null;
    rohe = [];
  };
  const stempel = (z: Zug, t: number | null) => {
    if (t === null || t === undefined) return;
    z.start = z.start === null ? t : Math.min(z.start, t);
    z.ende = z.ende === null ? t : Math.max(z.ende, t);
  };

  for (const a of anzeige) {
    if (a.art === 'agent' || a.art === 'werkzeug' || a.art === 'arbeitet') {
      if (!zug) {
        zug = neuerZug(`zug-${anker}`, a.art === 'agent' ? a.name : agentName);
        stempel(zug, ankerZeit);
      }
      if (a.art === 'agent') {
        zug.name = a.name;
        zug.zeit = a.zeit ?? zug.zeit;
        stempel(zug, a.zeit);
        if (a.live) {
          zug.laeuft = true;
          zug.schreibt = true;
        }
        if (a.verbrauch) zug.verbrauch = a.verbrauch;
        rohe.push(...ordneBloecke(a.bloecke, a.schluessel));
      } else if (a.art === 'werkzeug') {
        stempel(zug, a.zeit);
        rohe.push(schrittAusKarte(a.karte, `${a.schluessel}.${a.karte.id ?? a.karte.name}`));
      } else zug.laeuft = true;
      continue;
    }
    beendeZug();
    anker = a.schluessel;
    ankerZeit = a.art === 'mensch' || a.art === 'system' ? a.zeit : null;
    eingang = null;

    if (a.art === 'mensch') {
      aus.push({ art: 'mensch', schluessel: a.schluessel, text: a.text, zeit: a.zeit, steuern: a.steuern, quelle: '' });
    } else if (a.art === 'system') {
      if (a.eingang?.klasse === 'max') {
        // du hast über einen anderen Kanal geschrieben (z. B. Matrix): für ihn ist das sein Gespräch.
        aus.push({ art: 'mensch', schluessel: a.schluessel, text: a.text, zeit: a.zeit, steuern: false, quelle: a.eingang.quelle });
      } else if (a.eingang || a.lauf) {
        const punkt: Extract<VerlaufsPunkt, { art: 'autonom' }> = {
          art: 'autonom',
          schluessel: a.schluessel,
          quelle: a.eingang ? a.eingang.quelle : 'Lauf',
          text: a.text,
          zeit: a.zeit,
          lauf: !!a.lauf,
          zug: null,
        };
        aus.push(punkt);
        eingang = punkt;
      } else {
        aus.push({ art: 'system', schluessel: a.schluessel, titel: a.titel, text: a.text, zeit: a.zeit });
      }
    }
  }
  beendeZug();

  // Der letzte Zug läuft, solange der Agent arbeitet; frühere Züge nie.
  const letzter = aus[aus.length - 1];
  const letzterZug = letzter?.art === 'zug' ? letzter : letzter?.art === 'autonom' ? letzter.zug : null;
  for (const p of aus) {
    const z = p.art === 'zug' ? p : p.art === 'autonom' ? p.zug : null;
    if (z && z !== letzterZug) {
      z.laeuft = false;
      z.schreibt = false;
    }
  }
  // Dauer-Anker: ein laufender Zug zählt bis jetzt (die Oberfläche tickt selbst weiter).
  for (const p of aus) {
    const z = p.art === 'zug' ? p : p.art === 'autonom' ? p.zug : null;
    if (z?.laeuft && z.start !== null) z.ende = Math.max(z.ende ?? z.start, jetzt);
  }

  return opt.tage === false ? aus : mitTagen(aus, jetzt);
}

function zeitVon(p: VerlaufsPunkt): number | null {
  if (p.art === 'zug') return p.start ?? p.zeit;
  if (p.art === 'tag') return null;
  return p.zeit;
}

/** Fügt vor dem ersten Punkt eines Tages einen Trenner ein, sobald der Verlauf mehr als einen Tag umfasst. */
function mitTagen(punkte: VerlaufsPunkt[], jetzt: number): VerlaufsPunkt[] {
  const zeiten = punkte.map(zeitVon);
  const tage = new Set(zeiten.filter((t): t is number => t !== null).map((t) => new Date(t).toDateString()));
  if (tage.size < 2) return punkte;
  const aus: VerlaufsPunkt[] = [];
  let letzterTag = '';
  punkte.forEach((p, i) => {
    const t = zeiten[i];
    if (t !== null && t !== undefined) {
      const tag = new Date(t).toDateString();
      if (tag !== letzterTag) {
        aus.push({ art: 'tag', schluessel: `tag-${tag}`, text: tagText(t, jetzt) });
        letzterTag = tag;
      }
    }
    aus.push(p);
  });
  return aus;
}

// ── Zusammenfassung der Arbeit ───────────────────────────────────────────────

export const schrittWort = (n: number): string => (n === 1 ? tr('1 Schritt') : tr('{0} Schritte', n));

/** Dauer eines Zugs in ms; ein laufender Zug zählt bis `jetzt`. */
export function zugDauer(z: Zug, jetzt: number = Date.now()): number | null {
  if (z.start === null) return null;
  const ende = z.laeuft ? Math.max(jetzt, z.ende ?? z.start) : (z.ende ?? z.start);
  return Math.max(0, ende - z.start);
}

/** Ob ein Zug überhaupt etwas zu zeigen hat, das Arbeit ist. */
export const hatArbeit = (z: Zug): boolean => z.schritte.length > 0 || z.laeuft;

/**
 * Die eine Zeile je Zug: „Arbeitet … · 4 Schritte · 38 s“ oder „Gearbeitet · 4 Schritte · 38 s · 1 Fehler“.
 * Nur Gedanken: „Gedacht · 12 s“.
 */
export function arbeitsZeile(z: Zug, jetzt: number = Date.now()): string {
  const teile: string[] = [];
  const nurGedanken = z.schrittZahl === 0 && z.schritte.some((s) => s.art === 'gedanken');
  teile.push(z.laeuft ? tr('Arbeitet …') : nurGedanken ? tr('Gedacht') : tr('Gearbeitet'));
  if (z.schrittZahl > 0) teile.push(schrittWort(z.schrittZahl));
  const d = dauerText(zugDauer(z, jetzt));
  if (d) teile.push(d);
  if (z.fehlerZahl > 0) teile.push(z.fehlerZahl === 1 ? tr('1 Fehler') : tr('{0} Fehler', z.fehlerZahl));
  return teile.join(' · ');
}

/** Das Werkzeug, das gerade läuft (für die Arbeitszeile im geschlossenen Zustand). */
export function aktuellerSchritt(z: Zug): string {
  for (let i = z.schritte.length - 1; i >= 0; i--) {
    const s = z.schritte[i];
    if (s?.art === 'werkzeug' && s.status === 'laeuft') return s.titel;
  }
  return '';
}

/** Alle Texte eines Verlaufs (für Tests und die Suche): Eingabe, Antwort, Autonomes. */
export function verlaufsTexte(punkte: VerlaufsPunkt[]): string[] {
  return punkte.flatMap((p) => (p.art === 'zug' ? [p.antwort] : p.art === 'autonom' ? [p.text, p.zug?.antwort ?? ''] : p.art === 'tag' ? [] : [p.text])).filter(Boolean);
}

// ── Begrenzen ────────────────────────────────────────────────────────────────

export const SEITE = 60;

/**
 * Zeigt nur die letzten `max` Punkte (lange Verläufe bleiben flüssig); `rest` sagt, wie viele davor verborgen sind.
 * Tagestrenner zählen nicht mit.
 */
export function begrenze(punkte: VerlaufsPunkt[], max: number): { sichtbar: VerlaufsPunkt[]; rest: number } {
  const inhalt = punkte.filter((p) => p.art !== 'tag');
  if (inhalt.length <= max) return { sichtbar: punkte, rest: 0 };
  const erster = inhalt[inhalt.length - max];
  const ab = erster ? punkte.indexOf(erster) : 0;
  return { sichtbar: punkte.slice(ab), rest: inhalt.length - max };
}

/** Der Verlauf ohne die autonomen Punkte (Live aus); `ausgeblendet` zählt, was fehlt. */
export function ohneAutonomes(punkte: VerlaufsPunkt[]): { punkte: VerlaufsPunkt[]; ausgeblendet: number } {
  let n = 0;
  const rest = punkte.filter((p) => {
    if (p.art === 'autonom') {
      n++;
      return false;
    }
    return true;
  });
  return { punkte: rest, ausgeblendet: n };
}
