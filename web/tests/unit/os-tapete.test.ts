import { describe, expect, it } from 'vitest';
import { leer, neuerBildschirm, entfernen, pruefen, tapeteSetzen, tapetenUebernehmen, tapeteVon, START } from '~/lib/os/bildschirme';
import { TAPETEN, pfadGueltig, tapeteHintergrund, tapetePruefen, tapetenPfad, urlGueltig } from '~/lib/os/tapete';

describe('tapetePruefen', () => {
  it('nimmt eingebaute Verläufe, Ablagepfade und https-Adressen', () => {
    expect(tapetePruefen({ art: 'auswahl', wert: 'tiefsee', dunkel: 30, weich: 4 })).toEqual({ art: 'auswahl', wert: 'tiefsee', dunkel: 30, weich: 4 });
    expect(tapetePruefen({ art: 'datei', wert: 'FYOS/Tapeten/a.jpg' })?.dunkel).toBe(20);
    expect(tapetePruefen({ art: 'url', wert: 'https://bilder.example/x.jpg' })?.art).toBe('url');
  });

  it('weist Unbekanntes, Data-URLs, http und Pfade aus der Ablage hinaus ab', () => {
    expect(tapetePruefen({ art: 'auswahl', wert: 'gibtsnicht' })).toBeUndefined();
    expect(tapetePruefen({ art: 'url', wert: 'data:image/png;base64,AAAA' })).toBeUndefined();
    expect(tapetePruefen({ art: 'url', wert: 'http://x.example/a.jpg' })).toBeUndefined();
    expect(tapetePruefen({ art: 'url', wert: 'javascript:alert(1)' })).toBeUndefined();
    expect(tapetePruefen({ art: 'datei', wert: '../geheim.jpg' })).toBeUndefined();
    expect(tapetePruefen({ art: 'datei', wert: '/etc/passwd' })).toBeUndefined();
    expect(tapetePruefen(null)).toBeUndefined();
  });

  it('begrenzt Abdunkeln und Weichzeichnen', () => {
    const t = tapetePruefen({ art: 'auswahl', wert: 'glut', dunkel: 500, weich: -3 })!;
    expect(t.dunkel).toBe(80);
    expect(t.weich).toBe(0);
  });
});

describe('Pfade und Adressen', () => {
  it('pfadGueltig und urlGueltig', () => {
    expect(pfadGueltig('a/b.jpg')).toBe(true);
    expect(pfadGueltig('a//b.jpg')).toBe(false);
    expect(urlGueltig('/os/bild.jpg')).toBe(true);
    expect(urlGueltig('//fremd.example/x.jpg')).toBe(false);
  });

  it('tapetenPfad liegt im Tapeten-Ordner und nimmt nur sichere Zeichen', () => {
    expect(tapetenPfad('b1x/../', 36)).toBe('FYOS/Tapeten/b1x-10.jpg');
    expect(tapetenPfad('', 1)).toBe('FYOS/Tapeten/start-1.jpg');
  });

  it('tapeteHintergrund: Verlauf direkt, Bild erst mit geladener Adresse, ohne CSS-Ausbruch', () => {
    expect(tapeteHintergrund({ art: 'auswahl', wert: TAPETEN[0]!.id, dunkel: 0, weich: 0 })).toBe(TAPETEN[0]!.hintergrund);
    expect(tapeteHintergrund({ art: 'datei', wert: 'a.jpg', dunkel: 0, weich: 0 })).toBeUndefined();
    const css = tapeteHintergrund({ art: 'url', wert: 'x', dunkel: 0, weich: 0 }, 'https://a.example/b"); background: red; (x')!;
    expect(css.match(/"/g)).toHaveLength(2);
    expect(css).not.toContain('; background');
    expect(css.startsWith('center / cover no-repeat url("')).toBe(true);
  });
});

describe('Tapete im Arbeitsplatz', () => {
  const t = { art: 'auswahl' as const, wert: 'polar', dunkel: 10, weich: 0 };

  it('setzt und entfernt je Bildschirm, der Start eigens', () => {
    let ap = neuerBildschirm(neuerBildschirm(leer()));
    ap = tapeteSetzen(ap, 2, t);
    ap = tapeteSetzen(ap, START, { ...t, wert: 'glut' });
    expect(tapeteVon(ap, 1)).toBeUndefined();
    expect(tapeteVon(ap, 2)?.wert).toBe('polar');
    expect(tapeteVon(ap, START)?.wert).toBe('glut');
    ap = tapeteSetzen(ap, 2, undefined);
    expect(tapeteVon(ap, 2)).toBeUndefined();
    expect('tapete' in ap.bildschirme[1]!).toBe(false);
  });

  it('Start-Tapete übersteht neue und entfernte Bildschirme', () => {
    let ap = tapeteSetzen(leer(), START, t);
    ap = neuerBildschirm(ap);
    ap = entfernen(ap, 1);
    expect(tapeteVon(ap, START)?.wert).toBe('polar');
  });

  it('pruefen behält gültige Tapeten und wirft ungültige weg', () => {
    const roh = {
      bildschirme: [
        { id: 'a', name: 'Eins', fenster: [], tapete: t },
        { id: 'b', name: 'Zwei', fenster: [], tapete: { art: 'url', wert: 'data:x' } },
      ],
      aktiv: 1,
      zuletzt: 1,
      startTapete: { art: 'datei', wert: 'FYOS/Tapeten/s.jpg' },
    };
    const ap = pruefen(JSON.parse(JSON.stringify(roh)));
    expect(ap.bildschirme[0]!.tapete?.wert).toBe('polar');
    expect(ap.bildschirme[1]!.tapete).toBeUndefined();
    expect(ap.startTapete?.wert).toBe('FYOS/Tapeten/s.jpg');
  });
});

describe('tapetenUebernehmen (Hub, geräteübergreifend)', () => {
  const zwei = () => neuerBildschirm(neuerBildschirm(leer(), 'Eins'), 'Zwei');
  it('füllt nur Bildschirme ohne Tapete, über die Kennung', () => {
    let ap = tapeteSetzen(zwei(), 1, { art: 'auswahl', wert: 'glut', dunkel: 20, weich: 0 });
    const [a, b] = ap.bildschirme;
    const neu = tapetenUebernehmen(ap, {
      bildschirme: [
        { id: a!.id, tapete: { art: 'auswahl', wert: 'tiefsee', dunkel: 10, weich: 0 } },
        { id: b!.id, tapete: { art: 'datei', wert: 'FYOS/Tapeten/b.jpg', dunkel: 40, weich: 6 } },
        { id: 'fremd', tapete: { art: 'auswahl', wert: 'polar', dunkel: 0, weich: 0 } },
      ],
      startTapete: { art: 'url', wert: 'https://bild.example/x.jpg' },
    });
    expect(neu.bildschirme[0]!.tapete?.wert).toBe('glut'); // eigene Wahl bleibt
    expect(neu.bildschirme[1]!.tapete).toEqual({ art: 'datei', wert: 'FYOS/Tapeten/b.jpg', dunkel: 40, weich: 6 });
    expect(neu.startTapete?.wert).toBe('https://bild.example/x.jpg');
    ap = tapeteSetzen(neu, START, { art: 'auswahl', wert: 'morgen', dunkel: 0, weich: 0 });
    expect(tapetenUebernehmen(ap, { startTapete: { art: 'auswahl', wert: 'abend' } }).startTapete?.wert).toBe('morgen');
  });
  it('gibt ohne Änderung denselben Arbeitsplatz zurück und verwirft Ungültiges', () => {
    const ap = zwei();
    expect(tapetenUebernehmen(ap, {})).toBe(ap);
    expect(tapetenUebernehmen(ap, { bildschirme: 'x', startTapete: { art: 'url', wert: 'javascript:alert(1)' } })).toBe(ap);
    expect(tapetenUebernehmen(ap, { bildschirme: [{ id: ap.bildschirme[0]!.id, tapete: { art: 'auswahl', wert: 'gibtsnicht' } }] })).toBe(ap);
  });
  it('pruefen übernimmt startTapete aus der Hub-Meldung (neues Gerät)', () => {
    const ap = pruefen({ bildschirme: [{ id: 'b1', name: 'A', fenster: [] }], aktiv: 0, startTapete: { art: 'auswahl', wert: 'tiefsee' } });
    expect(ap.startTapete?.wert).toBe('tiefsee');
  });
});
