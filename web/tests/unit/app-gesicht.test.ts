/**
 * Gesicht einer Hub-App: Titel, Untertitel, Symbol, Farbe,
 * Kategorie — vom Hub, solange er sie liefert; sonst aus Name und Beschreibung abgeleitet.
 * Menschen sehen nie Agenten-Text („(App):", Backticks, Werkzeug-Kennungen).
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { appsGruppieren } from '~/components/apps/gruppen';
import {
  KATEGORIEN, KATEGORIE_REST, gesichtVon, gesichterMerken, kategorieFuer, kategorieRang, titelKopf, untertitelAus,
} from '~/lib/mcp-apps/gesicht';
import type { McpApp } from '~/lib/mcp-apps/host';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { farbton, glyphe, symbolBild, symboleZuruecksetzen } from '~/lib/os/symbole';

const app = (name: string, extra: Partial<McpApp> & Record<string, unknown> = {}): McpApp =>
  ({
    tool: name.replace('__', '.'),
    name,
    description: '',
    inputSchema: {},
    _meta: { ui: { resourceUri: `ui://fyos/${name}.html` } },
    scope: 'READ',
    ...extra,
  }) as McpApp;

// Plugins bringen ihre Symbole über registriereFlaechen mit; ohne sie bleibt das Fenster-Symbol.
beforeEach(() => {
  registriereFlaechen({
    symbole: {
      'app:haus__favoriten': ['house', 26],
      'app:haus__x': ['house', 26],
      'app:haus__szenen': ['house', 26],
      'app:experiment__zeigen': ['test-tubes', 270],
      'app:modelle__zustand': ['cpu', 285],
      'app:werkstatt__suchen': ['square-terminal', 150],
      'app:werkstatt__ausfuehren': ['square-terminal', 150],
    },
  });
});

afterEach(() => {
  symboleZuruecksetzen();
  registerZuruecksetzen();
});

describe('untertitelAus — erster Satz der Beschreibung, für Menschen', () => {
  it('entfernt „(App):" vorn und mitten im Satz', () => {
    expect(untertitelAus('Haus (App): Szenen und Lieblingsgeräte schalten.')).toBe('Szenen und Lieblingsgeräte schalten');
    expect(untertitelAus('Zeigt (App) die zuletzt eingegangenen Dokumente.')).toBe('Zeigt die zuletzt eingegangenen Dokumente');
    expect(untertitelAus('Das Lagebild auf einen Blick (App): Ampel, Fristen und Chronik.')).toBe('Ampel, Fristen und Chronik');
  });

  it('lässt Backticks weg, behält aber die Wörter', () => {
    const t = untertitelAus('Zeigt `eintraege` mit Antwort-Knöpfen.');
    expect(t).not.toContain('`');
    expect(t).toBe('Zeigt eintraege mit Antwort-Knöpfen');
  });

  it('entfernt Klammerreste, auch eine halbe Klammer am Ende', () => {
    expect(untertitelAus('Wie viele sind noch unsortiert (ohne Korrespondent und Typ) und die Suche.')).toBe('Wie viele sind noch unsortiert und die Suche');
    expect(untertitelAus('Kurve einer Kennzahl (bis zu 24 Punkte')).toBe('Kurve einer Kennzahl');
    expect(untertitelAus('Pods (davon (kaputte) mit Fehlern) im Blick.')).toBe('Pods im Blick');
  });

  it('endet beim ersten Satz, aber nicht bei einem Kürzel wie „z. B."', () => {
    expect(untertitelAus('Zeigt Licht und Lüfter. Danach kommt mehr Text.')).toBe('Zeigt Licht und Lüfter');
    expect(untertitelAus('Zeigt z. B. Licht und Lüfter. Danach kommt mehr.')).toBe('Zeigt z. B. Licht und Lüfter');
    expect(untertitelAus('Schaltet ggf. mehrere Räume. Weiteres steht im Schema.')).toBe('Schaltet ggf. mehrere Räume');
  });

  it('trennt am Gedankenstrich und Semikolon, wenn davor schon genug steht', () => {
    expect(untertitelAus('Alles im Blick — mit Chronik und Fristen und mehr')).toBe('Alles im Blick');
    expect(untertitelAus('Ampel und Fristen; dazu die Chronik der letzten Stunden')).toBe('Ampel und Fristen');
    // zu kurz davor: nicht abschneiden
    expect(untertitelAus('Ein — sehr langer Rest')).toBe('Ein — sehr langer Rest');
  });

  it('kürzt lange Sätze an einer Wortgrenze mit „…" und beginnt groß', () => {
    const lang = untertitelAus('je Knoten Rollen, Labels, Taints, Kapazität und vergebbar, Summe der Requests und Limits, Auslastung jetzt');
    expect(lang.length).toBeLessThanOrEqual(73);
    expect(lang.endsWith('…')).toBe(true);
    expect(lang.charAt(0)).toBe('J');
    // nicht mitten im Wort: der Rest vor der Auslassung ist eine ganze Wortfolge aus dem Text
    expect('Je Knoten Rollen, Labels, Taints, Kapazität und vergebbar, Summe der Requests und Limits').toContain(lang.slice(0, -1).trim());
    expect(untertitelAus('Kurz und bündig.', 72)).toBe('Kurz und bündig');
    expect(untertitelAus('x'.repeat(200), 40).length).toBe(40);
  });

  it('gibt bei Leerem und Unbrauchbarem einen leeren Text', () => {
    expect(untertitelAus('')).toBe('');
    expect(untertitelAus(undefined)).toBe('');
    expect(untertitelAus(null)).toBe('');
    expect(untertitelAus('(App):')).toBe('');
    expect(untertitelAus('   \n  ')).toBe('');
  });
});

describe('gesichtVon — Felder vom Hub haben Vorrang', () => {
  it('nimmt Titel, Untertitel, Symbol, Ton und Kategorie von oberster Ebene', () => {
    const g = gesichtVon(app('haus__favoriten', { titel: 'Haus', untertitel: 'Szenen und Geräte schalten', symbol: 'house', ton: 26, kategorie: 'Zuhause' }));
    expect(g).toMatchObject({ titel: 'Haus', untertitel: 'Szenen und Geräte schalten', symbol: 'house', ton: 26, kategorie: 'Zuhause', vomHub: true });
  });

  it('liest sonst _meta.app; die oberste Ebene gewinnt gegen _meta.app', () => {
    const meta = { ui: { resourceUri: 'ui://x' }, app: { titel: 'Aus Meta', untertitel: 'Meta-Zeile', symbol: 'bell', ton: 352, kategorie: 'Agent' } };
    const nurMeta = gesichtVon(app('leitstand__braucht_dich', { _meta: meta as McpApp['_meta'] }));
    expect(nurMeta).toMatchObject({ titel: 'Aus Meta', untertitel: 'Meta-Zeile', symbol: 'bell', ton: 352, kategorie: 'Agent', vomHub: true });
    const beides = gesichtVon(app('leitstand__braucht_dich', { _meta: meta as McpApp['_meta'], titel: 'Oben' }));
    expect(beides.titel).toBe('Oben');
    expect(beides.untertitel).toBe('Meta-Zeile');
  });

  it('kennt der Hub eine Glyphe, die wir nicht zeichnen, bleibt unsere Tabelle und das Bild des Hubs geht mit', () => {
    const svg = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg"/>';
    const g = gesichtVon(app('haus__favoriten', { symbol: 'gibt-es-nicht', icon: svg }));
    expect(g.symbol).toBe('house'); // Rückfall: Tabelle
    expect(g.icon).toBe(svg);
    expect(g.vomHub).toBe(false); // ohne Titel/Untertitel/Ton nie „vom Hub"
  });

  it('nimmt als Bild nur ein SVG als data:-Adresse', () => {
    expect(gesichtVon(app('haus__x', { icon: 'https://boese.example/x.svg' })).icon).toBeUndefined();
    expect(gesichtVon(app('haus__x', { icon: 'javascript:alert(1)' })).icon).toBeUndefined();
    expect(gesichtVon(app('haus__x', { icon: 'data:text/html,<script>1</script>' })).icon).toBeUndefined();
    expect(gesichtVon(app('haus__x', { icon: 'data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=' })).icon).toMatch(/^data:image\/svg\+xml/);
    // ein bekanntes Symbol braucht kein Bild
    expect(gesichtVon(app('haus__x', { symbol: 'house', icon: 'data:image/svg+xml;utf8,<svg/>' })).icon).toBeUndefined();
  });

  it('normalisiert den Ton auf 0–359 und verwirft Unbrauchbares', () => {
    expect(gesichtVon(app('haus__x', { ton: 400 })).ton).toBe(40);
    expect(gesichtVon(app('haus__x', { ton: -10 })).ton).toBe(350);
    expect(gesichtVon(app('haus__x', { ton: 26.4 })).ton).toBe(26);
    // NaN/Text/Unendlich: Rückfall auf die Farbe der Tabelle
    expect(gesichtVon(app('haus__x', { ton: Number.NaN })).ton).toBe(26);
    expect(gesichtVon(app('haus__x', { ton: '26' as unknown as number })).ton).toBe(26);
    expect(gesichtVon(app('haus__x', { ton: Number.POSITIVE_INFINITY })).ton).toBe(26);
  });

  it('ignoriert überlange oder falsch getypte Texte vom Hub', () => {
    const g = gesichtVon(app('haus__favoriten', { title: 'Haus', titel: 'x'.repeat(200), untertitel: 42 as unknown as string, kategorie: 7 as unknown as string }));
    expect(g.titel).toBe('Haus');
    expect(g.kategorie).toBe(KATEGORIE_REST);
  });
});

describe('gesichtVon — Rückfall ohne Felder vom Hub', () => {
  it('Titel: Titel des Werkzeugs, in einer Gruppe nur der App-Name; ohne Titel aus dem Namen', () => {
    expect(gesichtVon(app('leitstand__lagebild', { title: 'Lagebild' })).titel).toBe('Lagebild');
    expect(gesichtVon(app('werkstatt__ausfuehren', { title: 'Werkstatt — ausführen' }), { gruppe: true }).titel).toBe('Werkstatt');
    expect(gesichtVon(app('werkstatt__ausfuehren', { title: 'Werkstatt — ausführen' })).titel).toBe('Werkstatt — ausführen');
    expect(gesichtVon(app('leitstand__braucht_dich')).titel).toBe('Braucht dich');
    expect(titelKopf('Steuerpult — Knoten')).toBe('Steuerpult');
    expect(titelKopf('Lagebild')).toBe('Lagebild');
  });

  it('Untertitel: fester Text für bekannte Oberflächen, sonst erster Satz der Beschreibung', () => {
    const a = app('dokumente__eingang', { description: 'Zeigt (App) die zuletzt eingegangenen Dokumente und erlaubt die Suche. Mit `q`: Volltext.' });
    expect(gesichtVon(a).untertitel).toBe('Zeigt die zuletzt eingegangenen Dokumente und erlaubt die Suche');
    expect(gesichtVon(a, { info: 'Neue Dokumente sortieren' }).untertitel).toBe('Neue Dokumente sortieren');
    // der Hub schlägt beides
    expect(gesichtVon({ ...a, untertitel: 'Vom Hub' } as McpApp, { info: 'Neue Dokumente sortieren' }).untertitel).toBe('Vom Hub');
  });

  it('Symbol und Ton kommen aus der Tabelle (lib/os/symbole.ts), unbekannte bekommen ein Fenster-Symbol', () => {
    expect(gesichtVon(app('haus__favoriten'))).toMatchObject({ symbol: 'house', ton: 26, vomHub: false });
    expect(gesichtVon(app('experiment__zeigen'))).toMatchObject({ symbol: 'test-tubes', ton: 270 });
    const unbekannt = gesichtVon(app('neu__ding'));
    expect(unbekannt.symbol).toBe('app-window');
    expect(unbekannt.ton).toBeGreaterThanOrEqual(0);
    expect(unbekannt.ton).toBeLessThan(360);
  });

  it('Kategorie: die des Hubs, sonst „Weitere"', () => {
    expect(kategorieFuer(app('haus__szenen', { kategorie: 'Zuhause' }))).toBe('Zuhause');
    expect(kategorieFuer(app('neu__ding'))).toBe(KATEGORIE_REST);
    expect(kategorieFuer(app('haus__x', { kategorie: 'Eigene' }))).toBe('Eigene');
  });

  it('die Reihenfolge der Kategorien ist fest; Unbekanntes steht davor „Weitere"', () => {
    expect([...KATEGORIEN]).toEqual(['Zuhause', 'System', 'Betrieb', 'Wissen', 'Messen']);
    const sortiert = ['Weitere', 'Eigene', 'Messen', 'Zuhause', 'Wissen'].sort((a, b) => kategorieRang(a) - kategorieRang(b));
    expect(sortiert).toEqual(['Zuhause', 'Wissen', 'Messen', 'Eigene', 'Weitere']);
  });
});

describe('Gruppen tragen das Gesicht', () => {
  it('eine Gruppe mit mehreren Werkzeugen heißt wie die App und zeigt keinen Agenten-Text', () => {
    const werkstatt = ['suchen', 'beschreiben', 'ausfuehren', 'zeigen'].map((w) =>
      app(`werkstatt__${w}`, {
        title: `Werkstatt — ${w}`,
        description: 'Ein angemeldetes Skript im Hub-Pod ausfuehren (App). `lesen` laeuft direkt.',
        _meta: { ui: { resourceUri: 'ui://fyos/werkstatt.html' } } as McpApp['_meta'],
      }),
    );
    const [g] = appsGruppieren(werkstatt);
    expect(g!.mitglieder).toHaveLength(4);
    expect(g!.gesicht.titel).toBe('Werkstatt');
    expect(g!.gesicht.untertitel).toBe('Skripte ausführen, Befehle kopieren');
    expect(g!.gesicht.kategorie).toBe(KATEGORIE_REST);
    expect(g!.gesicht.symbol).toBe('square-terminal');
    for (const feld of [g!.gesicht.titel, g!.gesicht.untertitel]) {
      expect(feld).not.toMatch(/`|\(App\)|__|ausfuehren/);
    }
  });
});

describe('gesichterMerken — Symbol und Farbe des Hubs gelten überall', () => {
  it('übernimmt Glyphe und Ton in lib/os/symbole.ts (Dock, Start, Fensterkopf, Katalog)', () => {
    expect(glyphe('app:haus__favoriten')).toBe('house');
    gesichterMerken([app('haus__favoriten', { symbol: 'star', ton: 300 })]);
    expect(glyphe('app:haus__favoriten')).toBe('star');
    expect(farbton('app:haus__favoriten')).toBe(300);
    symboleZuruecksetzen();
    expect(glyphe('app:haus__favoriten')).toBe('house');
  });

  it('übergeht Werkzeuge ohne Oberfläche und Apps ohne Felder', () => {
    const ohneUi = { ...app('lage__ampel', { symbol: 'bell', ton: 1 }), _meta: undefined } as unknown as McpApp;
    gesichterMerken([ohneUi, app('modelle__zustand')]);
    expect(glyphe('app:lage__ampel')).toBe('app-window');
    expect(glyphe('app:modelle__zustand')).toBe('cpu');
  });

  it('ein Bild des Hubs ersetzt die Glyphe nur, wenn wir sie nicht kennen', () => {
    const svg = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg"/>';
    gesichterMerken([app('neu__ding', { symbol: 'gibt-es-nicht', icon: svg }), app('haus__szenen', { symbol: 'house', icon: svg })]);
    expect(symbolBild('app:neu__ding')).toBe(svg);
    expect(symbolBild('app:haus__szenen')).toBeUndefined();
  });
});
