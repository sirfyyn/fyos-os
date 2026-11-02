/**
 * meldungen-quellen.ts — woher die Meldungen kommen (28.10.2026). Keine neuen Backends: nur Ströme und Abfragen, die das OS schon nutzt.
 *
 *   Störung    Bus (`/api/smarthome/live`, lib/live.ts): node.critical, services.service_down, cluster.degraded (kritisch), *.alert (hoch)
 *   Freigabe   „Wartet auf dich“ (lib/os/wartet.ts, P2), sobald es da ist; sonst Runner: `api/freigaben` bei jeder Änderung des
 *              Dokuments `freigaben` (SSE `api/dokumente`); Risiko hoch oder zerstörerisch = kritisch
 *   Agent      Runner: Strom `api/strom`, Zeilen `sagt` aus Gesprächen (nicht aus Läufen), gesammelt; nicht, solange des Agenten Fenster vorn ist
 *   Termin     `/api/calendar/events?who=all&days=1`, alle 10 min; ein Takt von 30 s vergleicht nur lokal (10 Min vorher, jetzt)
 *   Mail       `/api/inbox/list?limit=10&q=… is:unread` alle 3 min (bei Fehlern länger); nur neue, nur die gewählten Ordner
 *
 * Alles hängt an Anschlüssen (`Anschluesse`), damit Tests ohne Netz auskommen. Jede Quelle läuft nur, solange sie in den Einstellungen
 * an ist. Nach dem Start gemeldet wird nur, was NEU ist; was beim ersten Abruf schon da war, kommt nur in den Verlauf (Freigaben) oder
 * gar nicht (Mail), damit ein Neuladen keinen Toast-Regen auslöst.
 */
import type { Freigabe, StromZeile } from '~/lib/agent-runner/typen';
import { ordnerAbfrage } from '~/lib/mail-abfrage';
import type { BusEreignis } from '~/lib/live';
import type { MeldungEingabe } from './meldungen';
import type { MeldungenEinstellungen, Quelle } from './meldungen-einstellungen';
import { tr } from '~/lib/i18n';

export const TERMIN_ABRUF_MS = 10 * 60_000;
export const TERMIN_TAKT_MS = 30_000;
export const MAIL_ABRUF_MS = 3 * 60_000;
export const MAIL_ABRUF_MAX_MS = 15 * 60_000;
export const AGENT_SAMMEL_MS = 1_500;
export const TERMIN_VORLAUF_MS = 10 * 60_000;

// ── Reine Umsetzer ──────────────────────────────────────────────────────────────────────────────

const STOERUNG_KRITISCH = new Set(['node.critical', 'services.service_down', 'cluster.degraded']);

function text(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/** Störung aus einem Bus-Ereignis; null, wenn es keine ist. */
export function stoerungAus(e: BusEreignis): MeldungEingabe | null {
  const kritisch = STOERUNG_KRITISCH.has(e.thema);
  if (!kritisch && !e.thema.endsWith('.alert')) return null;
  const d = e.daten ?? {};
  const was = text(d.name) || text(d.service) || text(d.node) || text(d.title) || text(d.titel) || text(d.entity_id);
  const titelDe = (
    {
      'node.critical': 'Knoten kritisch',
      'services.service_down': 'Dienst ausgefallen',
      'cluster.degraded': 'Cluster eingeschränkt',
    } as Record<string, string>
  )[e.thema];
  const titel = titelDe ? tr(titelDe) : tr('Warnung {0}', e.thema.replace(/\.alert$/, ''));
  const detail = was || text(d.message).split('\n').slice(-1)[0] || '';
  return {
    quelle: 'stoerung',
    schluessel: `${e.thema}|${was}`,
    stufe: kritisch ? 'kritisch' : 'hoch',
    titel: was && !detail.startsWith(titel) ? `${titel}: ${was}`.slice(0, 80) : titel,
    text: detail && detail !== was ? detail.slice(0, 140) : '',
    ziel: { ziel: 'app:leitstand__lagebild' },
    aktionen: [{ id: 'oeffnen', text: tr('Lagebild öffnen'), ziel: { ziel: 'app:leitstand__lagebild' } }],
    entdoppelnMs: 30 * 60_000,
  };
}

const RISIKO: Record<string, string> = { low: 'niedrig', medium: 'mittel', high: 'hoch' };

/**
 * Freigabe → Meldung. Nur offene. Risiko hoch (oder zerstörerisch) = kritisch, sonst hoch. Knöpfe: nur „Öffnen“ — Erteilen und
 * Ablehnen bleiben in des Agenten Fenster, wo Aktion, Risiko, Kontext und Befehl zu sehen sind (ein Toast zeigt den Befehl nicht).
 */
export function freigabeAus(f: Freigabe, nurVerlauf = false): MeldungEingabe | null {
  if (f.status !== 'offen') return null;
  const risiko = tr(RISIKO[f.risiko ?? ''] ?? (f.risiko || 'mittel'));
  const hoch = f.risiko === 'high' || f.zerstoererisch === true;
  const ziel = { ziel: 'nativ:agent' };
  return {
    quelle: 'freigabe',
    schluessel: f.id,
    stufe: hoch ? 'kritisch' : 'hoch',
    titel: tr('Freigabe: {0}', text(f.aktion) || text(f.werkzeug) || tr('Aktion')).slice(0, 80),
    text: (tr('Risiko {0}', risiko) + (f.gespraechTitel ? ` · ${f.gespraechTitel}` : '')).slice(0, 140),
    ziel,
    aktionen: [{ id: 'oeffnen', text: tr('Freigabe öffnen'), ziel }],
    ...(nurVerlauf ? { nurVerlauf: true } : {}),
  };
}

/**
 * Ein Eintrag aus „Wartet auf dich“ (`wartet.eingang`, lib/os/wartet.ts, OS-Neubau P2), nur die Felder, die eine Meldung braucht.
 * Hier ohne Import, damit der Meldungsdienst auch ohne P2 baut.
 */
export interface WartetMeldbar {
  id: string;
  quelle: string;
  satz: string;
  warum?: string;
  umkehrbar: boolean;
  zerstoererisch: boolean;
  risiko?: 'low' | 'medium' | 'high' | null;
  ziel?: string;
}

const OS_ZIEL = /^(app:|nativ:|seite:|agent$)/;

/**
 * Wartet-Eintrag → Meldung (statt eines zweiten Runner-Abrufs, P2/P4 31.10.2026). Nicht Umkehrbares einzeln: zerstörerisch oder Risiko
 * hoch = kritisch, sonst hoch. Umkehrbares (Fragen) normal und gesammelt („3 Fragen warten“). Die Zahl selbst zeigt nur `zahl` aus P2.
 */
export function wartetAus(e: WartetMeldbar, nurVerlauf = false): MeldungEingabe {
  const kritisch = e.zerstoererisch || e.risiko === 'high';
  const ziel = e.quelle === 'runner' ? { ziel: 'nativ:agent' } : e.ziel && OS_ZIEL.test(e.ziel) ? { ziel: e.ziel } : undefined;
  const einzeln = !e.umkehrbar;
  return {
    quelle: 'freigabe',
    schluessel: `wartet:${e.id}`,
    stufe: kritisch ? 'kritisch' : einzeln ? 'hoch' : 'normal',
    titel: tr(einzeln ? 'Freigabe: {0}' : 'Frage: {0}', text(e.satz) || tr('wartet auf dich')).slice(0, 80),
    text: text(e.warum).slice(0, 140),
    ...(ziel ? { ziel, aktionen: [{ id: 'oeffnen', text: tr('Ansehen'), ziel }] } : {}),
    ...(einzeln ? {} : { sammeln: (n: number) => tr('{0} Fragen warten auf dich', n) }),
    sicher: { titel: tr('Etwas wartet auf dich'), sammeln: (n: number) => tr('{0} Dinge warten auf dich', n) },
    ...(nurVerlauf ? { nurVerlauf: true } : {}),
  };
}

/** Neue offene Freigaben gegenüber `bekannt` (null = erster Abruf: alle sind „schon da“). */
export function neueFreigaben(bekannt: Set<string> | null, liste: Freigabe[]): { neu: Freigabe[]; ids: Set<string>; erster: boolean } {
  const offen = liste.filter((f) => f.status === 'offen');
  const ids = new Set(offen.map((f) => f.id));
  if (bekannt === null) return { neu: offen, ids, erster: true };
  return { neu: offen.filter((f) => !bekannt.has(f.id)), ids, erster: false };
}

export interface Termin {
  id: string;
  titel: string;
  start: number;
}

/** Termine aus der Antwort von /api/calendar/events (`{events:[{id,title|summary,start}]}`); ganztägige (nur Datum) entfallen. */
export function termineAus(d: unknown): Termin[] {
  const events = (d as { events?: unknown[] } | null)?.events;
  if (!Array.isArray(events)) return [];
  const aus: Termin[] = [];
  for (const raw of events) {
    const e = raw as { id?: unknown; title?: unknown; summary?: unknown; start?: unknown };
    const start = typeof e.start === 'string' ? e.start : typeof (e.start as { dateTime?: string } | undefined)?.dateTime === 'string' ? (e.start as { dateTime: string }).dateTime : '';
    if (start.length <= 10) continue; // ohne Uhrzeit
    const t = Date.parse(start);
    if (!Number.isFinite(t)) continue;
    const titel = text(e.title) || text(e.summary) || tr('Termin');
    aus.push({ id: text(e.id) || `${titel}|${start}`, titel, start: t });
  }
  return aus;
}

/** Termine, die jetzt eine Meldung brauchen: Beginn in höchstens 10 Min („vor10“) oder gerade begonnen (bis 2 Min danach, „jetzt“). */
export function terminMeldungen(termine: Termin[], jetzt: number): MeldungEingabe[] {
  const aus: MeldungEingabe[] = [];
  for (const t of termine) {
    const bis = t.start - jetzt;
    const ziel = { ziel: 'seite:kalender' };
    const aktionen = [{ id: 'oeffnen', text: tr('Kalender öffnen'), ziel }];
    if (bis <= 0 && bis > -2 * 60_000) {
      aus.push({ quelle: 'termin', schluessel: `${t.id}|jetzt`, stufe: 'hoch', titel: tr('Jetzt: {0}', t.titel).slice(0, 80), text: '', ziel, aktionen });
    } else if (bis > 0 && bis <= TERMIN_VORLAUF_MS) {
      const min = Math.max(1, Math.round(bis / 60_000));
      aus.push({ quelle: 'termin', schluessel: `${t.id}|vor10`, stufe: 'hoch', titel: tr('In {0} Min: {1}', min, t.titel).slice(0, 80), text: '', ziel, aktionen });
    }
  }
  return aus;
}

export interface MailEintrag {
  id: string;
  absender: string;
  betreff: string;
}

/** Ungelesene Mails aus /api/inbox/list. Nur Absendername und Betreff — nie ein Textauszug. */
export function mailsAus(d: unknown): MailEintrag[] {
  const liste = (d as { messages?: unknown[] } | null)?.messages;
  if (!Array.isArray(liste)) return [];
  const aus: MailEintrag[] = [];
  for (const raw of liste) {
    const m = raw as { id?: unknown; from?: unknown; subject?: unknown; unread?: unknown };
    const id = text(m.id);
    if (!id) continue;
    if (m.unread === false) continue;
    const von = text(m.from);
    const teil = /^(.+?)\s*<(.+)>$/.exec(von);
    const absender = (teil ? teil[1]!.replace(/^["']|["']$/g, '') : von.split('@')[0] || von).trim() || tr('Unbekannt');
    aus.push({ id, absender: absender.slice(0, 40), betreff: (text(m.subject) || tr('(ohne Betreff)')).slice(0, 120) });
  }
  return aus;
}

export function mailMeldung(m: MailEintrag): MeldungEingabe {
  const ziel = { ziel: 'seite:mail-inbox' };
  return {
    quelle: 'mail',
    schluessel: m.id,
    stufe: 'normal',
    titel: tr('Neue Mail von {0}', m.absender).slice(0, 80),
    text: m.betreff,
    ziel,
    aktionen: [{ id: 'oeffnen', text: tr('Mail öffnen'), ziel }],
    sammeln: (n) => tr('{0} neue Mails', n),
    sicher: { titel: tr('Neue Mail'), sammeln: (n) => tr('{0} neue Mails', n) },
  };
}

/** Die Gmail-Abfrage für ungelesene Mails in den gewählten Ordnern. */
export function mailAbfrage(ordner: string[]): string {
  const teile = ordner.map(ordnerAbfrage);
  return `${teile.length > 1 ? `(${teile.join(' OR ')})` : teile[0] ?? 'in:inbox'} is:unread`;
}

export function agentMeldung(titel: string, textStueck: string, gespraech: number, n: number): MeldungEingabe {
  const ziel = { ziel: 'nativ:agent' };
  return {
    quelle: 'agent',
    schluessel: `${gespraech}|${n}`,
    stufe: 'normal',
    titel: (titel ? tr('Agent: {0}', titel) : tr('Agent')).slice(0, 80),
    text: textStueck.replace(/\s+/g, ' ').trim().slice(0, 140),
    ziel,
    aktionen: [{ id: 'oeffnen', text: tr('Öffnen'), ziel }],
    sammeln: (k) => tr('{0} neue Nachrichten von Agent', k),
    sicher: { titel: tr('Agent hat geschrieben'), sammeln: (k) => tr('Agent hat {0}-mal geschrieben', k) },
  };
}

// ── Anschlüsse und Verdrahtung ──────────────────────────────────────────────────────────────────

export interface FreigabenMerker {
  gesehen(id: string): boolean;
  merke(id: string): void;
}

export const MERKER_SCHLUESSEL = 'fyos:os:meldungen:freigaben';
export const MERKER_MS = 24 * 60 * 60_000;

/** Merker in localStorage (Id → Zeit), Einträge älter als 24 h verfallen. Ein gesperrter Speicher heißt: nur bis zum Neuladen merken. */
export function speicherMerker(speicher: Pick<Storage, 'getItem' | 'setItem'> | null, jetzt: () => number = Date.now): FreigabenMerker {
  const lesen = (): Record<string, number> => {
    try {
      const roh = JSON.parse(speicher?.getItem(MERKER_SCHLUESSEL) ?? '{}') as Record<string, unknown>;
      return Object.fromEntries(Object.entries(roh).filter(([, t]) => typeof t === 'number' && jetzt() - t < MERKER_MS)) as Record<string, number>;
    } catch {
      return {};
    }
  };
  const speicherInRam: Record<string, number> = {};
  return {
    gesehen: (id) => id in lesen() || (speicherInRam[id] !== undefined && jetzt() - speicherInRam[id] < MERKER_MS),
    merke: (id) => {
      speicherInRam[id] = jetzt();
      try {
        speicher?.setItem(MERKER_SCHLUESSEL, JSON.stringify({ ...lesen(), [id]: jetzt() }));
      } catch {
        /* nur im Speicher */
      }
    },
  };
}

export interface Anschluesse {
  einstellungen: () => MeldungenEinstellungen;
  melde: (e: MeldungEingabe) => unknown;
  jetzt: () => number;
  /** Zeitgeber (Tests: gefälscht) */
  setInterval: (f: () => void, ms: number) => unknown;
  clearInterval: (h: unknown) => void;
  setTimeout: (f: () => void, ms: number) => unknown;
  clearTimeout: (h: unknown) => void;
  /** Bus abonnieren (lib/live.ts `hoere`); Rückgabe beendet */
  bus: (f: (e: BusEreignis) => void) => () => void;
  /** Runner: offene Freigaben lesen */
  freigaben: () => Promise<Freigabe[]>;
  /** Runner: Dokumente-Strom (`freigaben` geändert → Aufruf) */
  freigabenAenderung: (f: () => void) => () => void;
  /**
   * „Wartet auf dich“ (P2): ruft `f` mit allen Einträgen bei jedem neuen Stand; Rückgabe beendet. Ist es da, ersetzt es den
   * Runner-Abruf (`freigaben`/`freigabenAenderung`) für die Quelle `freigabe`.
   */
  wartet?: (f: (eintraege: readonly WartetMeldbar[]) => void) => () => void;
  /** Runner: Strom der Zeilen */
  stromZeilen: (f: (z: StromZeile) => void) => () => void;
  /** Läuft des Agenten Fenster vorn (und die Seite sichtbar)? Dann keine Agent-Meldung. */
  agentVorn: () => boolean;
  /** Merker für kritische Freigaben, die schon als Toast gezeigt wurden (auch nach Neuladen; Ablauf 24 h) */
  merker?: FreigabenMerker;
  kalender: () => Promise<unknown>;
  mail: (abfrage: string) => Promise<unknown>;
}

/** Startet alle Quellen; die Rückgabe beendet sie. Eine Quelle, die ausgeschaltet ist, tut nichts (auch später eingeschaltet: nächster Takt). */
export function quellenStarten(a: Anschluesse): () => void {
  const aufraeumen: Array<() => void> = [];
  const an = (q: Quelle): boolean => a.einstellungen().quellen[q];
  const start = a.jetzt();

  // Störung (Bus)
  if (an('stoerung')) {
    aufraeumen.push(
      a.bus((e) => {
        if (Date.parse(e.ts) < start - 1000) return;
        const m = stoerungAus(e);
        if (m) a.melde(m);
      }),
    );
  }

  // Freigabe (Runner)
  let bekannt: Set<string> | null = null;
  let freigabenLaeuft = false;
  const freigabenPruefen = async () => {
    if (!an('freigabe') || freigabenLaeuft) return;
    freigabenLaeuft = true;
    try {
      const r = neueFreigaben(bekannt, await a.freigaben());
      bekannt = r.ids;
      for (const f of r.neu) {
        // Beim ersten Abruf: nur KRITISCHE als Toast, je Id genau einmal (Merker); die übrigen nur in den Verlauf
        const kritisch = f.risiko === 'high' || f.zerstoererisch === true;
        const schon = kritisch && a.merker ? a.merker.gesehen(f.id) : false;
        const m = freigabeAus(f, r.erster && (!kritisch || schon));
        if (m) {
          if (kritisch && !m.nurVerlauf) a.merker?.merke(f.id);
          a.melde(m);
        }
      }
    } catch {
      /* Runner nicht erreichbar: der Strom verbindet von selbst neu, der nächste Hinweis holt nach */
    } finally {
      freigabenLaeuft = false;
    }
  };
  if (an('freigabe') && a.wartet) {
    // Eine Quelle für alles, was wartet (P2): Neues gegenüber dem letzten Stand; beim ersten Stand nur Kritisches (einmal je Id)
    let vorher: Set<string> | null = null;
    aufraeumen.push(
      a.wartet((eintraege) => {
        if (!an('freigabe')) return;
        const erster = vorher === null;
        const alt = vorher ?? new Set<string>();
        vorher = new Set(eintraege.map((e) => e.id));
        for (const e of eintraege) {
          if (alt.has(e.id)) continue;
          const kritisch = e.zerstoererisch || e.risiko === 'high';
          const schon = kritisch && a.merker ? a.merker.gesehen(e.id) : false;
          const m = wartetAus(e, erster && (!kritisch || schon));
          if (kritisch && !m.nurVerlauf) a.merker?.merke(e.id);
          a.melde(m);
        }
      }),
    );
  } else if (an('freigabe')) {
    aufraeumen.push(a.freigabenAenderung(() => void freigabenPruefen()));
    void freigabenPruefen();
  }

  // Agent (Runner-Strom), je Gespräch gesammelt
  const sammel = new Map<number, { titel: string; text: string; n: number; timer: unknown }>();
  let agentZaehler = 0;
  if (an('agent')) aufraeumen.push(
    a.stromZeilen((z) => {
      if ( z.typ !== 'sagt' || z.art === 'lauf' || !z.text) return;
      const alt = sammel.get(z.gespraech);
      if (alt) a.clearTimeout(alt.timer);
      const n = (alt?.n ?? 0) + 1;
      const timer = a.setTimeout(() => {
        const s = sammel.get(z.gespraech);
        sammel.delete(z.gespraech);
        if (!s || a.agentVorn() || !an('agent')) return;
        a.melde(agentMeldung(s.titel, s.text, z.gespraech, ++agentZaehler));
      }, AGENT_SAMMEL_MS);
      sammel.set(z.gespraech, { titel: z.titel ?? '', text: z.text, n, timer });
    }),
  );

  // Termin: Abruf alle 10 min, Vergleich lokal alle 30 s
  let termine: Termin[] = [];
  const termineHolen = async () => {
    if (!an('termin')) return;
    try {
      termine = termineAus(await a.kalender());
    } catch {
      /* Kalender nicht erreichbar: die alten Termine bleiben für den lokalen Takt */
    }
  };
  const terminTakt = () => {
    if (!an('termin')) return;
    for (const m of terminMeldungen(termine, a.jetzt())) a.melde(m);
  };
  void termineHolen().then(terminTakt);
  const h1 = a.setInterval(() => void termineHolen(), TERMIN_ABRUF_MS);
  const h2 = a.setInterval(terminTakt, TERMIN_TAKT_MS);

  // Mail: Abruf mit Rücknahme bei Fehlern
  let gesehen: Set<string> | null = null;
  let mailPause = MAIL_ABRUF_MS;
  let mailTimer: unknown;
  let beendet = false;
  const mailHolen = async () => {
    if (beendet) return;
    if (an('mail')) {
      try {
        const e = a.einstellungen();
        const neu = mailsAus(await a.mail(mailAbfrage(e.mailOrdner)));
        const erster = gesehen === null;
        gesehen ??= new Set();
        for (const m of neu) {
          if (gesehen.has(m.id)) continue;
          gesehen.add(m.id);
          if (!erster) a.melde(mailMeldung(m));
        }
        mailPause = MAIL_ABRUF_MS;
      } catch {
        mailPause = Math.min(MAIL_ABRUF_MAX_MS, mailPause * 2);
      }
    }
    if (!beendet) mailTimer = a.setTimeout(() => void mailHolen(), mailPause);
  };
  void mailHolen();

  return () => {
    beendet = true;
    for (const f of aufraeumen) f();
    a.clearInterval(h1);
    a.clearInterval(h2);
    a.clearTimeout(mailTimer);
    for (const s of sammel.values()) a.clearTimeout(s.timer);
    sammel.clear();
  };
}
