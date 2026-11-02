import { describe, expect, it } from 'vitest';
import { befehlsZeile, offeneZahl, ordneFreigaben, risikoText } from '~/lib/agent-runner/freigaben';
import { laufTon, laufendeZahl, ordneLaeufe, statusText } from '~/lib/agent-runner/laeufe';
import { LIVE_SPEICHER, STROM_MAX, leerStrom, liesLive, liveBefehl, mitHallo, mitZeile, schreibeLive, stromAktiv, stromTitel } from '~/lib/agent-runner/strom';
import { inlineTeile, textTeile, vor } from '~/lib/agent-runner/text';
import type { Freigabe, Lauf } from '~/lib/agent-runner/typen';

describe('Strom (Live)', () => {
  it('Hallo setzt die Namensliste, Zeilen hängen an und ein neues Gespräch wird aufgenommen', () => {
    let s = mitHallo(leerStrom(), { gespraeche: [{ id: 1, titel: 'Hauptgespräch', art: 'root' }] });
    s = mitZeile(s, { t: 100, gespraech: 14, titel: 'Lauf 13', art: 'lauf', typ: 'schritt', text: 'arbeitet' });
    expect(s.zeilen).toHaveLength(1);
    expect(s.letzte).toBe(100);
    expect(s.gespraeche.map((g) => g.id)).toEqual([1, 14]);
    expect(stromTitel(s, 14)).toBe('Lauf 13');
    expect(stromTitel(s, 99)).toBeUndefined();
  });

  it('hält höchstens STROM_MAX Zeilen und wirft unbrauchbare weg', () => {
    let s = leerStrom();
    for (let i = 0; i < STROM_MAX + 25; i++) s = mitZeile(s, { t: i + 1, gespraech: 1, typ: 'sagt', text: `z${i}` });
    expect(s.zeilen).toHaveLength(STROM_MAX);
    expect(s.zeilen[0]?.text).toBe('z25');
    expect(mitZeile(s, { kaputt: true })).toBe(s);
    expect(mitZeile(s, null)).toBe(s);
  });

  it('aktiv ist ein Strom, der in den letzten 30 s etwas sagte', () => {
    const s = mitZeile(leerStrom(), { t: 1000, gespraech: 1, typ: 'sagt', text: 'x' });
    expect(stromAktiv(s, 20_000)).toBe(true);
    expect(stromAktiv(s, 40_000)).toBe(false);
    expect(stromAktiv(leerStrom(), 5)).toBe(false);
  });

  it('/live-Befehle', () => {
    expect(liveBefehl('/live')).toBe('wechseln');
    expect(liveBefehl('/live an')).toBe('an');
    expect(liveBefehl('/live ein')).toBe('an');
    expect(liveBefehl('/LIVE aus')).toBe('aus');
    expect(liveBefehl('  /live  ')).toBe('wechseln');
    expect(liveBefehl('/live bitte')).toBeNull();
    expect(liveBefehl('hallo /live')).toBeNull();
  });

  it('Live ist die Voreinstellung; nur ein gespeichertes „aus“ blendet aus', () => {
    const speicher = new Map<string, string>();
    const s = { getItem: (k: string) => speicher.get(k) ?? null, setItem: (k: string, v: string) => void speicher.set(k, v) };
    expect(liesLive(s)).toBe(true);
    schreibeLive(s, false);
    expect(speicher.get(LIVE_SPEICHER)).toBe('aus');
    expect(liesLive(s)).toBe(false);
    schreibeLive(s, true);
    expect(liesLive(s)).toBe(true);
    expect(liesLive(null)).toBe(true);
    expect(liesLive({ getItem: () => { throw new Error('gesperrt'); } })).toBe(true);
  });
});

describe('Freigaben', () => {
  const f = (id: string, status: string, risiko: string, erstellt: number): Freigabe => ({ id, status, risiko, erstellt });
  it('offene zuerst, hohes Risiko vor niedrigem, dann neueste', () => {
    const l = ordneFreigaben([f('a', 'erteilt', 'high', 9), f('b', 'offen', 'low', 5), f('c', 'offen', 'high', 1), f('d', 'offen', 'high', 3)]);
    expect(l.map((x) => x.id)).toEqual(['d', 'c', 'b', 'a']);
    expect(offeneZahl(l)).toBe(3);
  });
  it('Texte', () => {
    expect(risikoText('high')).toBe('hoch');
    expect(risikoText(undefined)).toBe('mittel');
    expect(befehlsZeile({ id: 'x', status: 'offen', werkzeug: 'bash', befehl: 'git branch -D x' })).toBe('bash: git branch -D x');
    expect(befehlsZeile({ id: 'x', status: 'offen' })).toBe('');
  });
});

describe('Läufe', () => {
  const l = (id: string, status: string, erstellt: number): Lauf => ({ id, status, erstellt });
  it('laufende zuerst; Ton und Text', () => {
    const liste = ordneLaeufe([l('1', 'abgeschlossen', 9), l('2', 'laeuft', 1), l('3', 'fehler', 5)]);
    expect(liste.map((x) => x.id)).toEqual(['2', '1', '3']);
    expect(laufendeZahl(liste)).toBe(1);
    expect(laufTon(l('x', 'laeuft', 0))).toBe('laeuft');
    expect(laufTon(l('x', 'abgebrochen', 0))).toBe('fehler');
    expect(laufTon(l('x', 'abgeschlossen', 0))).toBe('fertig');
    expect(statusText(l('x', 'laeuft', 0))).toBe('läuft');
  });
});

describe('Text', () => {
  it('zerlegt Markdown in Absätze, Code, Überschriften und Listen', () => {
    const t = textTeile('# Titel\n\nEin `Befehl` und **fett**.\nZweite Zeile.\n\n- eins\n- zwei\n\n```sh\nls -la\n```\n1. a\n2. b');
    expect(t.map((x) => x.art)).toEqual(['ueberschrift', 'absatz', 'liste', 'code', 'liste']);
    expect(t[3]).toEqual({ art: 'code', sprache: 'sh', text: 'ls -la' });
    expect(t[2]).toMatchObject({ geordnet: false });
    expect(t[4]).toMatchObject({ geordnet: true });
  });
  it('ein offener Codeblock bleibt Code bis zum Ende; HTML bleibt Text', () => {
    const t = textTeile('```\nnoch offen\n<script>x</script>');
    expect(t).toEqual([{ art: 'code', sprache: '', text: 'noch offen\n<script>x</script>' }]);
    expect(inlineTeile('<b>x</b>')).toEqual([{ art: 'text', text: '<b>x</b>' }]);
  });
  it('inline', () => {
    expect(inlineTeile('a `b` **c** d')).toEqual([
      { art: 'text', text: 'a ' },
      { art: 'code', text: 'b' },
      { art: 'text', text: ' ' },
      { art: 'fett', text: 'c' },
      { art: 'text', text: ' d' },
    ]);
  });
  it('vor', () => {
    expect(vor(1000, 3000)).toBe('gerade eben');
    expect(vor(0, 125_000)).toBe('vor 2 min');
    expect(vor(undefined)).toBe('');
  });
});
