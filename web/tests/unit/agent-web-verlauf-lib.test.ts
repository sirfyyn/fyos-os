import { describe, expect, it } from 'vitest';
import { liesBefehl, passendeBefehle } from '~/lib/agent-runner/befehle';
import { ENTWURF_PREFIX, liesEntwurf, schreibeEntwurf } from '~/lib/agent-runner/entwurf';
import { FLAUTE_MS, flauteText, kopfStatus, kopfText, modellName, zugFlaute } from '~/lib/agent-runner/status';
import { aktivitaet, leerStrom, mitZeile, stromKlartext } from '~/lib/agent-runner/strom';
import { inlineTeile, textTeile } from '~/lib/agent-runner/text';
import {
  SEITE,
  arbeitsZeile,
  begrenze,
  dauerText,
  kuerzeAusgabe,
  ohneAutonomes,
  tagText,
  werkzeugTitel,
  type VerlaufsPunkt,
} from '~/lib/agent-runner/verlauf';
import { T0, assistent, aufruf, eingang, mensch, schreibenStapel, verlaufAus, werkzeugErgebnis, zugEintraege, zustand } from './agent-web-fixtures';

describe('werkzeugTitel: Klartext aus Name und Kernargument', () => {
  it('Hub-Werkzeuge', () => {
    expect(werkzeugTitel('hub_aufrufen', { werkzeug: 'vorgaenge.zeigen', argumente: { id: 'INC-4905' } })).toBe('Vorgang INC-4905 gelesen');
    expect(werkzeugTitel('hub_aufrufen', { werkzeug: 'cluster.lage' })).toBe('Cluster lage');
    expect(werkzeugTitel('hub_suchen', { suche: 'vorgang anlegen' })).toBe('Werkzeuge gesucht: vorgang anlegen');
    expect(werkzeugTitel('vorgaenge.zeigen', { id: 'INC-1' })).toBe('Vorgang INC-1 gelesen');
  });
  it('Shell ohne cd-Vorspann, Dateien mit Namen', () => {
    expect(werkzeugTitel('bash', { command: 'cd /Users/x/repo && git push origin main' })).toBe('Shell: git push origin main');
    expect(werkzeugTitel('bash', { command: 'ls\nrm x' })).toBe('Shell: ls');
    expect(werkzeugTitel('read', { path: '/a/b/c.md' })).toBe('Datei gelesen: c.md');
    expect(werkzeugTitel('edit', { path: '/a/b/c.md' })).toBe('Datei geändert: c.md');
    expect(werkzeugTitel('web_holen', { url: 'https://docs.example.org/x?y=1' })).toBe('Seite geladen: docs.example.org');
  });
  it('Unbekanntes bleibt lesbar', () => {
    expect(werkzeugTitel('neues_ding', { titel: 'Etwas' })).toBe('neues ding: Etwas');
    expect(werkzeugTitel('desktop_klick', {})).toBe('Desktop: klick');
    expect(werkzeugTitel('bash', {})).toBe('Shell: Befehl');
  });
});

describe('Ausgaben und Zeiten', () => {
  it('kürzt lange Ausgaben mit Anfang und Ende', () => {
    expect(kuerzeAusgabe('kurz')).toEqual({ text: 'kurz', gekuerzt: false });
    const lang = `${'a'.repeat(3000)}ENDE`;
    const k = kuerzeAusgabe(lang, 1000);
    expect(k.gekuerzt).toBe(true);
    expect(k.text.endsWith('ENDE')).toBe(true);
    expect(k.text).toContain('Zeichen gekürzt');
    expect(k.text.length).toBeLessThan(1100);
  });
  it('sagt Dauer', () => {
    expect(dauerText(400)).toBe('');
    expect(dauerText(38_000)).toBe('38 s');
    expect(dauerText(125_000)).toBe('2 min 5 s');
    expect(dauerText(180_000)).toBe('3 min');
    expect(dauerText(3_780_000)).toBe('1 h 3 min');
    expect(dauerText(null)).toBe('');
  });
  it('Tagestext', () => {
    const jetzt = Date.UTC(2026, 9, 25, 12);
    expect(tagText(jetzt, jetzt)).toBe('Heute');
    expect(tagText(jetzt - 86_400_000, jetzt)).toBe('Gestern');
    expect(tagText(Date.UTC(2026, 9, 20, 12), jetzt)).toBe('Dienstag, 20.10.');
  });
});

describe('Verlauf aus echten Ereignisformen', () => {
  const z = () => zustand([mensch(1, 'Wie steht INC-4905?'), ...zugEintraege(1)]);

  it('du, dann EIN Zug: Arbeit gebündelt, Antwort ist der Text nach der Arbeit', () => {
    const v = verlaufAus(z());
    expect(v.map((p) => p.art)).toEqual(['mensch', 'zug']);
    const zug = v[1];
    if (zug?.art !== 'zug') throw new Error('Zug erwartet');
    expect(zug.antwort).toBe('INC-4905 ist **offen**. Siehe [Vorgang](https://itsm.example/INC-4905).');
    expect(zug.schrittZahl).toBe(2);
    expect(zug.fehlerZahl).toBe(0);
    // Gedanken, Zwischentext und beide Werkzeuge liegen in der Arbeit, nicht in der Antwort
    expect(zug.schritte.map((s) => s.art)).toEqual(['gedanken', 'notiz', 'werkzeug', 'werkzeug']);
    expect(zug.antwort).not.toContain('Ich schaue kurz nach');
    const titel = zug.schritte.filter((s) => s.art === 'werkzeug').map((s) => (s.art === 'werkzeug' ? s.titel : ''));
    expect(titel).toEqual(['Vorgang INC-4905 gelesen', 'Shell: git push origin main']);
    expect(arbeitsZeile(zug, T0 + 60_000)).toBe('Gearbeitet · 2 Schritte · 38 s');
    expect(zug.laeuft).toBe(false);
  });

  it('ein Fehler eines Werkzeugs ist ein markierter Schritt, kein Chat-Text', () => {
    const v = verlaufAus(zustand([mensch(1, 'Pushe es'), ...zugEintraege(1, { fehler: true })]));
    const zug = v[1];
    if (zug?.art !== 'zug') throw new Error('Zug erwartet');
    const fehlerSchritt = zug.schritte.find((s) => s.art === 'werkzeug' && s.status === 'fehler');
    expect(fehlerSchritt).toMatchObject({ titel: 'Shell: python3 nach_main.py', fehlerZeile: 'usage: nach_main.py [-h] --vorgang V' });
    expect(zug.fehlerZahl).toBe(1);
    expect(arbeitsZeile(zug, T0 + 60_000)).toContain('1 Fehler');
    expect(zug.antwort).not.toContain('usage:');
  });

  it('laufender Zug: Text wird geschrieben, die Arbeit läuft, frühere Züge nie', () => {
    const z2 = zustand([mensch(1, 'Frage'), ...zugEintraege(1), mensch(10, 'Noch eine', T0 + 50_000)], [schreibenStapel('Gleich')], true);
    const v = verlaufAus(z2, { jetzt: T0 + 75_000 });
    expect(v.map((p) => p.art)).toEqual(['mensch', 'zug', 'mensch', 'zug']);
    const [, alt, , neu] = v;
    if (alt?.art !== 'zug' || neu?.art !== 'zug') throw new Error('Züge erwartet');
    expect(alt.laeuft).toBe(false);
    expect(neu.laeuft).toBe(true);
    expect(neu.schreibt).toBe(true);
    expect(neu.antwort).toBe('Gleich');
    expect(arbeitsZeile(neu, T0 + 75_000)).toMatch(/^Arbeitet … · 25 s$/);
  });

  it('du hast geschrieben, es kommt noch nichts: ein leerer Zug trägt „Arbeitet …“', () => {
    const v = verlaufAus(zustand([mensch(1, 'Hallo', T0)], [[{ type: 'run_start' }]], true), { jetzt: T0 + 5_000 });
    expect(v.map((p) => p.art)).toEqual(['mensch', 'zug']);
    const zug = v[1];
    if (zug?.art !== 'zug') throw new Error('Zug erwartet');
    expect(zug.laeuft).toBe(true);
    expect(zug.antwort).toBe('');
    expect(arbeitsZeile(zug, T0 + 5_000)).toBe('Arbeitet … · 5 s');
  });

  it('laufendes Werkzeug aus tool_execution_*: Titel, Dauer und Ende', () => {
    const z2 = zustand([mensch(1, 'Los')], [
      [
        { type: 'turn_start' },
        { type: 'tool_execution_start', toolCallId: 'x1', toolName: 'bash', args: { command: 'kubectl get pods' } },
        { type: 'tool_execution_update', toolCallId: 'x1', output: { append: 'NAME READY' } },
      ],
    ], true);
    const lauf = verlaufAus(z2);
    const zug = lauf[1];
    if (zug?.art !== 'zug') throw new Error('Zug erwartet');
    expect(zug.schritte[0]).toMatchObject({ art: 'werkzeug', titel: 'Shell: kubectl get pods', status: 'laeuft', ausgabe: 'NAME READY' });
    const fertig = zustand([mensch(1, 'Los')], [
      [
        { type: 'tool_execution_start', toolCallId: 'x1', toolName: 'bash', args: { command: 'kubectl get pods' } },
        { type: 'tool_execution_end', toolCallId: 'x1', result: { isError: true, output: 'Fehler: Zugriff verweigert' } },
      ],
    ]);
    const z3 = verlaufAus(fertig)[1];
    if (z3?.art !== 'zug') throw new Error('Zug erwartet');
    expect(z3.schritte[0]).toMatchObject({ status: 'fehler', fehlerZeile: 'Fehler: Zugriff verweigert' });
  });

  it('Eingang aus dem Hub ist des Agenten eigene Arbeit (autonom); ein Eingang von du ist seine Nachricht', () => {
    const z2 = zustand([
      eingang(1, 'zeitplan', 'Takt Morgen', 'system', T0),
      assistent(2, [aufruf('a', 'hub_aufrufen', { werkzeug: 'cluster.lage' })], T0 + 1_000),
      werkzeugErgebnis(3, 'a', 'hub_aufrufen', 'grün', false, T0 + 2_000),
      assistent(4, [{ type: 'text', text: 'Alles ruhig.' }], T0 + 3_000),
      eingang(5, 'matrix', 'Wie steht der Cluster?', 'max', T0 + 10_000),
      assistent(6, [{ type: 'text', text: 'Grün.' }], T0 + 12_000),
    ]);
    const v = verlaufAus(z2);
    expect(v.map((p) => p.art)).toEqual(['autonom', 'mensch', 'zug']);
    const [a, m] = v;
    if (a?.art !== 'autonom' || m?.art !== 'mensch') throw new Error('erwartet');
    expect(a).toMatchObject({ quelle: 'zeitplan', text: 'Takt Morgen' });
    expect(a.zug?.antwort).toBe('Alles ruhig.');
    expect(a.zug?.schrittZahl).toBe(1);
    expect(m).toMatchObject({ text: 'Wie steht der Cluster?', quelle: 'matrix' });

    const ruhe = ohneAutonomes(v);
    expect(ruhe.ausgeblendet).toBe(1);
    expect(ruhe.punkte.map((p) => p.art)).toEqual(['mensch', 'zug']);
  });

  it('Freigabe-Entscheidung bleibt eine Systemzeile, der Zug danach gehört zu du', () => {
    const z2 = zustand([
      mensch(1, 'Lösch das'),
      { id: 2, kind: 'fyos.freigabe-entscheidung', data: { id: 'fr-1', entscheidung: 'erteilt' }, model: [] },
      assistent(3, [{ type: 'text', text: 'Erledigt.' }], T0 + 5_000),
    ]);
    expect(verlaufAus(z2).map((p) => p.art)).toEqual(['mensch', 'system', 'zug']);
  });

  it('Zug-Schlüssel bleibt gleich, wenn aus dem Schreiben der fertige Eintrag wird', () => {
    const schreibt = zustand([mensch(1, 'Frage')], [schreibenStapel('Antw')], true);
    const fertig = zustand([mensch(1, 'Frage'), assistent(2, [{ type: 'text', text: 'Antwort' }], T0 + 70_000)]);
    const a = verlaufAus(schreibt).at(-1);
    const b = verlaufAus(fertig).at(-1);
    expect(a?.schluessel).toBe(b?.schluessel);
  });

  it('Tagestrenner erst bei mehr als einem Tag', () => {
    const gestern = T0 - 86_400_000;
    const z2 = zustand([mensch(1, 'alt', gestern), assistent(2, [{ type: 'text', text: 'ok' }], gestern + 1_000), mensch(3, 'neu', T0)]);
    const v = verlaufAus(z2, { jetzt: T0 + 1000 });
    expect(v.map((p) => p.art)).toEqual(['tag', 'mensch', 'zug', 'tag', 'mensch']);
    expect(v[0]).toMatchObject({ text: 'Gestern' });
    expect(v[3]).toMatchObject({ text: 'Heute' });
  });
});

describe('begrenze', () => {
  const viele = (n: number): VerlaufsPunkt[] =>
    Array.from({ length: n }, (_, i) => ({ art: 'mensch', schluessel: `m${i}`, text: String(i), zeit: T0, steuern: false, quelle: '' }));
  it('zeigt die letzten Punkte und sagt, wie viele davor fehlen', () => {
    const r = begrenze(viele(200), SEITE);
    expect(r.sichtbar).toHaveLength(SEITE);
    expect(r.rest).toBe(140);
    expect(r.sichtbar[0]?.schluessel).toBe('m140');
    expect(begrenze(viele(10), SEITE)).toMatchObject({ rest: 0 });
  });
});

describe('Kopf, Befehle, Entwurf, Flaute', () => {
  it('Kopfzustand: pausiert vor wartet vor arbeitet vor bereit', () => {
    expect(kopfStatus({ busy: true, offeneFreigaben: 2, spielmodus: 'spielmodus.nachhut' })).toBe('pausiert');
    expect(kopfStatus({ busy: true, offeneFreigaben: 2, spielmodus: null })).toBe('wartet');
    expect(kopfStatus({ busy: true, offeneFreigaben: 0, spielmodus: null })).toBe('arbeitet');
    expect(kopfStatus({ busy: false, offeneFreigaben: 0, spielmodus: null })).toBe('bereit');
    expect(kopfText('pausiert', 'spielmodus.nachhut')).toBe('Pausiert (Spielmodus)');
    expect(kopfText('bereit', null)).toBe('Bereit');
  });
  it('Modellname aus Agent oder Meta, ohne Anbieter-Präfix', () => {
    expect(modellName({ agent: { model: 'anthropic/claude-sonnet-4' }, meta: null })).toBe('claude-sonnet-4');
    expect(modellName({ agent: null, meta: { modell: 'qwen3' } })).toBe('qwen3');
    expect(modellName({ agent: { model: { id: 'gpt-x' } }, meta: null })).toBe('gpt-x');
    expect(modellName({ agent: null, meta: null }, { modell: 'm1' })).toBe('m1');
    expect(modellName({ agent: null, meta: null })).toBe('');
  });
  it('Flaute: nur bei laufendem Zug und nach 15 min', () => {
    expect(zugFlaute({ busy: true, letzteRegung: 1000, jetzt: 1000 + FLAUTE_MS })).toBe(true);
    expect(zugFlaute({ busy: true, letzteRegung: 1000, jetzt: 1000 + FLAUTE_MS - 1 })).toBe(false);
    expect(zugFlaute({ busy: false, letzteRegung: 1000, jetzt: 1000 + FLAUTE_MS * 2 })).toBe(false);
    expect(flauteText({ letzteRegung: 0, jetzt: 15 * 60_000 })).toBe('Keine fertige Antwort nach 15 min.');
  });
  it('Befehle: erkannt, Aliase, Unbekanntes bleibt Text', () => {
    expect(liesBefehl('/neu')).toEqual({ name: 'neu', rest: '' });
    expect(liesBefehl('/PAUSE')).toEqual({ name: 'stopp', rest: '' });
    expect(liesBefehl('/ruhe jetzt')).toEqual({ name: 'ruhe', rest: 'jetzt' });
    expect(liesBefehl('/etc/hosts lesen')).toBeNull();
    expect(liesBefehl('hallo /neu')).toBeNull();
    expect(passendeBefehle('/').map((b) => b.name)).toEqual(['live', 'ruhe', 'neu', 'stopp']);
    expect(passendeBefehle('/n').map((b) => b.name)).toEqual(['neu']);
    expect(passendeBefehle('/pa').map((b) => b.name)).toEqual(['stopp']);
    expect(passendeBefehle('/neu ')).toEqual([]);
    expect(passendeBefehle('neu')).toEqual([]);
  });
  it('Entwurf je Gespräch; leer löscht', () => {
    const m = new Map<string, string>();
    const sp = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
    schreibeEntwurf(3, 'halber Satz', sp);
    expect(m.get(`${ENTWURF_PREFIX}3`)).toBe('halber Satz');
    expect(liesEntwurf(3, sp)).toBe('halber Satz');
    expect(liesEntwurf(4, sp)).toBe('');
    schreibeEntwurf(3, '  ', sp);
    expect(liesEntwurf(3, sp)).toBe('');
    expect(liesEntwurf(null, sp)).toBe('');
  });
});

describe('Aktivitätszeile des Stroms', () => {
  const z = (t: number, rest: Record<string, unknown>) => ({ t, gespraech: 14, titel: 'Lauf 13: INC-4905 prüfen', art: 'lauf', text: '', typ: 'werkzeug', ...rest });
  it('„Agent arbeitet an INC-4905 prüfen: Shell: git push“ solange es frisch ist', () => {
    const s = mitZeile(leerStrom(), z(T0, { wz: 'bash', text: 'bash git push origin main' }));
    expect(aktivitaet(s, 'Agent', T0 + 10_000)).toMatchObject({ aktiv: true, text: 'Agent arbeitet an INC-4905 prüfen: Shell: git push origin main' });
  });
  it('ruhig nach zwei Minuten oder nach „fertig“; du-Zeilen zählen nicht', () => {
    const s = mitZeile(leerStrom(), z(T0, { wz: 'bash', text: 'bash ls' }));
    expect(aktivitaet(s, 'Agent', T0 + 3 * 60_000)).toMatchObject({ aktiv: false, text: 'Agent ist ruhig' });
    const fertig = mitZeile(s, z(T0 + 1000, { typ: 'fertig', text: 'Zug fertig' }));
    expect(aktivitaet(fertig, 'Agent', T0 + 2000).aktiv).toBe(false);
    const mitMax = mitZeile(s, z(T0 + 1000, { typ: 'mensch', text: 'hi', art: 'root' }));
    expect(aktivitaet(mitMax, 'Agent', T0 + 2000).text).toContain('Shell: ls');
    const eing = mitZeile(leerStrom(), z(T0, { typ: 'eingang', art: 'root', titel: 'Hauptgespräch', text: 'matrix (du): hi' }));
    expect(aktivitaet(eing, 'Agent', T0 + 1000).text).toBe('Agent arbeitet: liest Eingang matrix (du): hi');
    expect(stromKlartext(z(T0, { typ: 'eingang', text: 'matrix (du): hi' }) as never)).toBe('matrix (du): hi');
  });
});

describe('Markdown: Links, Kursiv, Code', () => {
  it('Links nur mit sicherem Ziel, Satzzeichen bleiben draußen', () => {
    expect(inlineTeile('siehe [Doku](https://a.example/x) und https://b.example/y.')).toEqual([
      { art: 'text', text: 'siehe ' },
      { art: 'link', text: 'Doku', url: 'https://a.example/x' },
      { art: 'text', text: ' und ' },
      { art: 'link', text: 'https://b.example/y', url: 'https://b.example/y' },
      { art: 'text', text: '.' },
    ]);
    expect(inlineTeile('[böse](javascript:alert(1))')).toEqual([{ art: 'text', text: 'böse' }, { art: 'text', text: ')' }]);
  });
  it('kursiv, fett, Code; snake_case und Malzeichen bleiben Text', () => {
    expect(inlineTeile('*leise* **laut** `x`').map((t) => t.art)).toEqual(['kursiv', 'text', 'fett', 'text', 'code']);
    expect(inlineTeile('a * b * c und nach_main.py')).toEqual([{ art: 'text', text: 'a * b * c und nach_main.py' }]);
  });
  it('Codeblöcke stehen einzeln', () => {
    const t = textTeile('Vorher\n```bash\nls -la\n```\nNachher');
    expect(t.map((x) => x.art)).toEqual(['absatz', 'code', 'absatz']);
    expect(t[1]).toMatchObject({ sprache: 'bash', text: 'ls -la' });
  });
});
