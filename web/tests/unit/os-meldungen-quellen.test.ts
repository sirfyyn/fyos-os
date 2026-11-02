/**
 * Quellen des Meldungsdienstes (lib/os/meldungen-quellen.ts) mit Attrappen: Störung aus dem Bus, Freigaben des Runners, Agent-Zeilen,
 * Termine, Mail. Keine Netzaufrufe; Zeitgeber gefälscht. Dazu: Datenschutz (Mail ohne Textauszug) und Abschalten je Quelle.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Freigabe, StromZeile } from '~/lib/agent-runner/typen';
import type { BusEreignis } from '~/lib/live';
import type { MeldungEingabe } from '~/lib/os/meldungen';
import { VORGABE, type MeldungenEinstellungen } from '~/lib/os/meldungen-einstellungen';
import {
  AGENT_SAMMEL_MS,
  MAIL_ABRUF_MAX_MS,
  MAIL_ABRUF_MS,
  TERMIN_TAKT_MS,
  freigabeAus,
  mailAbfrage,
  mailMeldung,
  mailsAus,
  neueFreigaben,
  quellenStarten,
  stoerungAus,
  termineAus,
  terminMeldungen,
  type Anschluesse,
} from '~/lib/os/meldungen-quellen';

const JETZT = Date.parse('2026-10-28T12:00:00Z');
const bus = (thema: string, daten: Record<string, unknown> = {}, ts = new Date(JETZT + 1000).toISOString()): BusEreignis => ({ thema, id: `${thema}-${Math.random()}`, ts, daten });
const fg = (id: string, extra: Partial<Freigabe> = {}): Freigabe => ({ id, status: 'offen', risiko: 'medium', aktion: 'Pod löschen', ...extra });

describe('Umsetzer', () => {
  it('Störung: kritische Themen sind kritisch, *.alert hoch, anderes nichts', () => {
    expect(stoerungAus(bus('services.service_down', { name: 'agent-itsm' }))).toMatchObject({ quelle: 'stoerung', stufe: 'kritisch', titel: 'Dienst ausgefallen: agent-itsm', schluessel: 'services.service_down|agent-itsm' });
    expect(stoerungAus(bus('node.critical', { node: 'knoten-1' }))).toMatchObject({ stufe: 'kritisch' });
    expect(stoerungAus(bus('grow.alert', { message: 'zu heiß' }))).toMatchObject({ stufe: 'hoch' });
    expect(stoerungAus(bus('freigabe.abgelehnt'))).toBeNull();
    expect(stoerungAus(bus('haus.zustand'))).toBeNull();
    expect(stoerungAus(bus('llm.availability.degraded'))).toBeNull();
  });

  it('Freigabe: nur offene; Risiko hoch oder zerstörerisch ist kritisch; nur „öffnen“, kein Erlauben/Ablehnen', () => {
    expect(freigabeAus(fg('1', { status: 'erteilt' }))).toBeNull();
    const m = freigabeAus(fg('2', { risiko: 'high' }))!;
    expect(m).toMatchObject({ quelle: 'freigabe', stufe: 'kritisch', schluessel: '2', titel: 'Freigabe: Pod löschen' });
    expect(m.text).toContain('Risiko hoch');
    expect(freigabeAus(fg('3', { zerstoererisch: true }))!.stufe).toBe('kritisch');
    expect(freigabeAus(fg('4'))!.stufe).toBe('hoch');
    expect(m.aktionen!.map((a) => a.text)).toEqual(['Freigabe öffnen']);
    expect(JSON.stringify(m)).not.toMatch(/erteilt|abgelehnt|erlauben/i);
    // der Befehl steht nicht im Toast
    expect(JSON.stringify(freigabeAus(fg('5', { befehl: 'rm -rf /' })))).not.toContain('rm -rf');
  });

  it('neueFreigaben: erster Abruf = alle schon da, danach nur Neue', () => {
    const a = neueFreigaben(null, [fg('1'), fg('2', { status: 'erteilt' })]);
    expect(a.erster).toBe(true);
    expect([...a.ids]).toEqual(['1']);
    const b = neueFreigaben(a.ids, [fg('1'), fg('3')]);
    expect(b.neu.map((f) => f.id)).toEqual(['3']);
    expect(b.erster).toBe(false);
  });

  it('Termine: ganztägige entfallen; zehn Minuten vorher und jetzt, je einmal pro Phase', () => {
    const t = termineAus({ events: [{ id: 'a', title: 'Zahnarzt', start: new Date(JETZT + 9 * 60_000).toISOString() }, { id: 'b', summary: 'Urlaub', start: '2026-10-28' }, { title: 'ohne Zeit' }, { id: 'c', title: 'Später', start: new Date(JETZT + 60 * 60_000).toISOString() }] });
    expect(t.map((x) => x.id)).toEqual(['a', 'c']);
    const m = terminMeldungen(t, JETZT);
    expect(m).toHaveLength(1);
    expect(m[0]).toMatchObject({ quelle: 'termin', stufe: 'hoch', schluessel: 'a|vor10', titel: 'In 9 Min: Zahnarzt' });
    const jetztM = terminMeldungen(t, JETZT + 9 * 60_000 + 30_000);
    expect(jetztM[0]).toMatchObject({ schluessel: 'a|jetzt', titel: 'Jetzt: Zahnarzt' });
    expect(terminMeldungen(t, JETZT + 9 * 60_000 + 3 * 60_000)).toHaveLength(0);
  });

  it('Mail: Absendername und Betreff, nie ein Textauszug; Sammeltitel', () => {
    const l = mailsAus({
      messages: [
        { id: 'm1', from: '"Alex Beispiel" <anna@example.org>', subject: 'Rechnung Oktober', snippet: 'Hallo du, anbei die geheime Summe', body_plain: 'GEHEIM', unread: true },
        { id: 'm2', from: 'bot@example.org', subject: '', unread: true },
        { id: 'm3', from: 'x@y.z', subject: 'gelesen', unread: false },
        { subject: 'ohne id' },
      ],
    });
    expect(l.map((m) => m.id)).toEqual(['m1', 'm2']);
    const m = mailMeldung(l[0]!);
    expect(m).toMatchObject({ quelle: 'mail', stufe: 'normal', titel: 'Neue Mail von Alex Beispiel', text: 'Rechnung Oktober' });
    expect(JSON.stringify(m)).not.toMatch(/geheim|snippet|body/i);
    expect(m.sammeln!(3)).toBe('3 neue Mails');
    expect(l[1]).toMatchObject({ absender: 'bot', betreff: '(ohne Betreff)' });
  });

  it('Mail-Abfrage nach gewählten Ordnern', () => {
    expect(mailAbfrage(['INBOX'])).toBe('in:inbox is:unread');
    expect(mailAbfrage(['INBOX', 'IMPORTANT'])).toBe('(in:inbox OR is:important) is:unread');
  });
});

// ── Verdrahtung mit Attrappen ───────────────────────────────────────────────────────────────────

describe('quellenStarten', () => {
  let einst: MeldungenEinstellungen;
  let gemeldet: MeldungEingabe[];
  let busHoerer: ((e: BusEreignis) => void) | undefined;
  let freigabenAenderung: (() => void) | undefined;
  let stromHoerer: ((z: StromZeile) => void) | undefined;
  let freigabenListe: Freigabe[];
  let agentVorn: boolean;
  let kalender: ReturnType<typeof vi.fn>;
  let mail: ReturnType<typeof vi.fn>;
  let aus: (() => void) | undefined;

  const anschluesse = (): Anschluesse => ({
    einstellungen: () => einst,
    melde: (e) => void gemeldet.push(e),
    jetzt: () => Date.now(),
    setInterval: (f, ms) => setInterval(f, ms),
    clearInterval: (h) => clearInterval(h as ReturnType<typeof setInterval>),
    setTimeout: (f, ms) => setTimeout(f, ms),
    clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    bus: (f) => {
      busHoerer = f;
      return () => (busHoerer = undefined);
    },
    freigaben: async () => freigabenListe,
    freigabenAenderung: (f) => {
      freigabenAenderung = f;
      return () => (freigabenAenderung = undefined);
    },
    stromZeilen: (f) => {
      stromHoerer = f;
      return () => (stromHoerer = undefined);
    },
    agentVorn: () => agentVorn,
    kalender: kalender as unknown as () => Promise<unknown>,
    mail: mail as unknown as (q: string) => Promise<unknown>,
  });

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(JETZT);
    einst = structuredClone(VORGABE);
    gemeldet = [];
    busHoerer = freigabenAenderung = stromHoerer = undefined;
    freigabenListe = [];
    agentVorn = false;
    kalender = vi.fn(async () => ({ events: [] }));
    mail = vi.fn(async () => ({ messages: [] }));
  });
  afterEach(() => {
    aus?.();
    aus = undefined;
    vi.useRealTimers();
  });
  const starte = async () => {
    aus = quellenStarten(anschluesse());
    await vi.advanceTimersByTimeAsync(0);
  };

  it('Störung aus dem Bus; Ereignisse aus dem Rückblick vor dem Start zählen nicht', async () => {
    await starte();
    busHoerer!(bus('services.service_down', { name: 'a' }, new Date(JETZT - 60_000).toISOString()));
    expect(gemeldet).toHaveLength(0);
    busHoerer!(bus('services.service_down', { name: 'a' }));
    expect(gemeldet).toHaveLength(1);
    expect(gemeldet[0]).toMatchObject({ quelle: 'stoerung', stufe: 'kritisch' });
  });

  it('Freigabe: beim ersten Abruf nur Verlauf, danach nach Änderung des Dokuments nur die neuen', async () => {
    freigabenListe = [fg('alt')];
    await starte();
    expect(gemeldet).toHaveLength(1);
    expect(gemeldet[0]).toMatchObject({ schluessel: 'alt', nurVerlauf: true });
    freigabenListe = [fg('alt'), fg('neu', { risiko: 'high' })];
    freigabenAenderung!();
    await vi.advanceTimersByTimeAsync(0);
    expect(gemeldet).toHaveLength(2);
    expect(gemeldet[1]).toMatchObject({ schluessel: 'neu', stufe: 'kritisch' });
    expect(gemeldet[1]!.nurVerlauf).toBeUndefined();
    // gleiche Liste noch einmal: nichts Neues
    freigabenAenderung!();
    await vi.advanceTimersByTimeAsync(0);
    expect(gemeldet).toHaveLength(2);
  });

  it('ein Fehler des Runners bricht nichts ab und holt beim nächsten Hinweis nach', async () => {
    let n = 0;
    const a = anschluesse();
    a.freigaben = async () => {
      if (++n === 1) throw new Error('weg');
      return [fg('x')];
    };
    aus = quellenStarten(a);
    await vi.advanceTimersByTimeAsync(0);
    expect(gemeldet).toHaveLength(0);
    freigabenAenderung!();
    await vi.advanceTimersByTimeAsync(0);
    expect(gemeldet).toHaveLength(1);
  });

  it('Agent: Zeilen eines Gesprächs werden gesammelt; Läufe und Werkzeuge zählen nicht; nicht bei vorn stehendem Fenster', async () => {
    await starte();
    const z = (extra: Partial<StromZeile>): StromZeile => ({ t: Date.now(), gespraech: 7, titel: 'Wohnung', art: 'mensch', typ: 'sagt', text: 'Das Licht ist an.', ...extra });
    stromHoerer!(z({ typ: 'werkzeug', text: 'bash ls' }));
    stromHoerer!(z({ art: 'lauf', text: 'Lauf sagt' }));
    stromHoerer!(z({}));
    stromHoerer!(z({ text: 'Und die Heizung auch.' }));
    expect(gemeldet).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(AGENT_SAMMEL_MS + 10);
    expect(gemeldet).toHaveLength(1);
    expect(gemeldet[0]).toMatchObject({ quelle: 'agent', stufe: 'normal', titel: 'Agent: Wohnung', text: 'Und die Heizung auch.' });
    agentVorn = true;
    stromHoerer!(z({ text: 'zweite' }));
    await vi.advanceTimersByTimeAsync(AGENT_SAMMEL_MS + 10);
    expect(gemeldet).toHaveLength(1);
  });

  it('Termin: ein Abruf, dann lokaler Takt; je Phase eine Meldung', async () => {
    kalender.mockResolvedValue({ events: [{ id: 'z', title: 'Zahnarzt', start: new Date(JETZT + 12 * 60_000).toISOString() }] });
    await starte();
    expect(kalender).toHaveBeenCalledTimes(1);
    expect(gemeldet).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(2 * 60_000 + TERMIN_TAKT_MS);
    expect(gemeldet.map((m) => m.schluessel)).toContain('z|vor10');
    expect(kalender).toHaveBeenCalledTimes(1);
  });

  it('Mail: der erste Abruf merkt nur, danach melden neue Mails; Fehler verlängern die Pause; kein Textauszug', async () => {
    mail.mockResolvedValueOnce({ messages: [{ id: 'a', from: 'x@y.z', subject: 'alt', unread: true }] });
    await starte();
    expect(gemeldet).toHaveLength(0);
    expect(mail).toHaveBeenCalledWith('in:inbox is:unread');
    mail.mockResolvedValueOnce({ messages: [{ id: 'a', from: 'x@y.z', subject: 'alt', unread: true }, { id: 'b', from: 'Bea <b@y.z>', subject: 'neu', snippet: 'GEHEIM', unread: true }] });
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MS + 10);
    expect(gemeldet).toHaveLength(1);
    expect(gemeldet[0]).toMatchObject({ quelle: 'mail', titel: 'Neue Mail von Bea', text: 'neu' });
    expect(JSON.stringify(gemeldet)).not.toContain('GEHEIM');
    // Fehler: Pause verdoppelt sich bis zur Obergrenze
    mail.mockRejectedValue(new Error('503'));
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MS + 10);
    const n1 = mail.mock.calls.length;
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MS + 10);
    expect(mail.mock.calls.length).toBe(n1);
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MAX_MS * 2);
    expect(mail.mock.calls.length).toBeGreaterThan(n1);
  });

  it('jede Quelle einzeln abschaltbar: ausgeschaltet heißt kein Strom, kein Abruf', async () => {
    einst.quellen = { agent: false, freigabe: false, stoerung: false, termin: false, mail: false };
    await starte();
    expect(busHoerer).toBeUndefined();
    expect(freigabenAenderung).toBeUndefined();
    expect(stromHoerer).toBeUndefined();
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MS * 3);
    expect(kalender).not.toHaveBeenCalled();
    expect(mail).not.toHaveBeenCalled();
    expect(gemeldet).toHaveLength(0);
  });

  it('Beenden räumt auf: keine Abrufe und keine Hörer mehr', async () => {
    await starte();
    aus!();
    aus = undefined;
    const n = mail.mock.calls.length;
    await vi.advanceTimersByTimeAsync(MAIL_ABRUF_MS * 4);
    expect(mail.mock.calls.length).toBe(n);
    expect(busHoerer).toBeUndefined();
  });
});
