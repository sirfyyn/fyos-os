/**
 * Die Seitenwerkzeuge des OS (lib/os/bruecke-werkzeuge.ts): os_oeffnen, os_fenster, os_schliessen,
 * os_zentrale, seite_lesen, os_mitteilungen. Gegen eine nachgestellte Shell: ein Arbeitsplatz, in dem
 * die Rückrufe `oeffne` und `schliesse` wirklich Fenster öffnen und schließen, wie es Shell.tsx tut.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../src/lib/api/client';
import { MAX_OFFEN, schliessen as fensterSchliessen } from '../../src/lib/os/anordnung';
import { fensterAendern, flaecheOeffnen, leer, wechseln, wo, type Arbeitsplatz } from '../../src/lib/os/bildschirme';
import { OEFFNEN_EREIGNIS, oeffnenMitPruefung, osWerkzeuge, zentraleKompakt, type OsKontext } from '../../src/lib/os/bruecke-werkzeuge';
import type { Flaeche, FlaechenArt } from '../../src/lib/os/flaechen';
import type { ZeigtEinstellung } from '../../src/lib/os/agent-zeigt';
import type { WerkzeugErgebnis } from '../../src/lib/werkzeuge';

const F = (id: string, titel: string, gruppe = 'Allgemein', art: FlaechenArt = 'seite'): Flaeche => ({ id, titel, gruppe, art, kuerzel: titel.slice(0, 2).toUpperCase() });
const FLAECHEN: Flaeche[] = [
  F('seite:berichte', 'Berichte', 'Auswertung'),
  F('seite:berichte-archiv', 'Berichte Archiv', 'Auswertung'),
  { ...F('app:notizen__liste', 'Notizen', 'Notizen', 'hubapp'), appName: 'notizen__liste' },
  F('seite:uebersicht', 'Übersicht'),
  F('nativ:anruf', 'Anruf', 'Agent', 'nativ'),
  F('agent', 'Agent', 'Agent', 'agent'),
];

/** Eine Shell im Kleinen: dieselben Zustandsübergänge wie Shell.tsx (oeffne → flaecheOeffnen, schliesse → schliessen). */
function shell() {
  const s = {
    ap: leer() as Arbeitsplatz,
    fokus: null as string | null,
    agent: false,
    einst: { aus: false, stumm_bis: 0 } as ZeigtEinstellung,
    zentrale: {} as unknown,
    jetzt: 1_000_000,
    oeffneAufrufe: [] as string[],
    schliesseAufrufe: [] as string[],
    ziel: new EventTarget(),
    wurzel: document.createElement('div'),
  };
  const k: OsKontext = {
    quelle: () => ({ ap: s.ap, fokus: s.fokus, agent: s.agent, flaeche: (id) => FLAECHEN.find((f) => f.id === id), flaechen: FLAECHEN }),
    oeffne: (id) => {
      s.oeffneAufrufe.push(id);
      const r = flaecheOeffnen(s.ap, id);
      s.ap = r.ap;
      if (!r.voll) s.fokus = id;
    },
    schliesse: (id) => {
      s.schliesseAufrufe.push(id);
      const i = wo(s.ap, id);
      if (i < 1) return false;
      s.ap = fensterAendern(s.ap, i, (l) => fensterSchliessen(l, id));
      return true;
    },
    einstellung: { lesen: () => s.einst, schreiben: (e) => void (s.einst = e) },
    zentrale: async () => s.zentrale,
    ereignisse: s.ziel,
    wurzel: s.wurzel,
    jetzt: () => s.jetzt,
  };
  const werkzeuge = osWerkzeuge(k);
  const rufe = async (name: string, args: Record<string, unknown> = {}): Promise<WerkzeugErgebnis> => {
    const w = werkzeuge.find((x) => x.name === name);
    if (!w) throw new Error(`kein Werkzeug ${name}`);
    return (await w.ausfuehren(args)) as WerkzeugErgebnis;
  };
  return { s, k, werkzeuge, rufe };
}

const text = (r: WerkzeugErgebnis): string => r.content[0]!.text;
const daten = (r: WerkzeugErgebnis): Record<string, unknown> => JSON.parse(text(r)) as Record<string, unknown>;

afterEach(() => {
  vi.useRealTimers();
});

describe('Werkzeug-Beschreibungen', () => {
  const { werkzeuge } = shell();

  it('es gibt genau diese sechs', () => {
    expect(werkzeuge.map((w) => w.name)).toEqual(['os_oeffnen', 'os_fenster', 'os_schliessen', 'os_zentrale', 'seite_lesen', 'os_mitteilungen']);
  });

  it('jedes hat eine deutsche Beschreibung, die in die Brücke passt (höchstens 300 Zeichen), und ein kleines Schema', () => {
    for (const w of werkzeuge) {
      expect(w.beschreibung.length, w.name).toBeGreaterThan(30);
      expect(w.beschreibung.length, w.name).toBeLessThanOrEqual(300);
      expect(w.eingabe, w.name).toBeTruthy();
      expect(new TextEncoder().encode(JSON.stringify(w.eingabe)).length, w.name).toBeLessThan(2048);
      expect((w.eingabe as { additionalProperties?: boolean }).additionalProperties, w.name).toBe(false);
    }
  });

  it('Lesen ist als lesend markiert, Verändern nicht', () => {
    const lesend = Object.fromEntries(werkzeuge.map((w) => [w.name, !!w.lesend]));
    expect(lesend).toEqual({ os_oeffnen: false, os_fenster: true, os_schliessen: false, os_zentrale: true, seite_lesen: true, os_mitteilungen: false });
  });

  it('ziel ist Pflicht beim Öffnen und Schließen', () => {
    for (const n of ['os_oeffnen', 'os_schliessen']) {
      expect((werkzeuge.find((w) => w.name === n)!.eingabe as { required: string[] }).required).toEqual(['ziel']);
    }
  });

  it('os_mitteilungen sagt dem Agenten, dass Einschalten nur auf ausdrücklichen Wunsch des Benutzers geschieht', () => {
    const beschreibung = werkzeuge.find((w) => w.name === 'os_mitteilungen')!.beschreibung;
    expect(beschreibung).toContain('Einschalten (an: true) nur auf ausdrücklichen Wunsch des Benutzers.');
  });

  it('seite_lesen nennt die Grenzen von zeichen im Schema', () => {
    const p = (werkzeuge.find((w) => w.name === 'seite_lesen')!.eingabe as { properties: { zeichen: { minimum: number; maximum: number } } }).properties;
    expect(p.zeichen).toMatchObject({ minimum: 500, maximum: 20000 });
  });
});

describe('os_oeffnen', () => {
  it('öffnet eine Fläche per ID und sagt, wo sie jetzt liegt', async () => {
    const { s, rufe } = shell();
    const r = await rufe('os_oeffnen', { ziel: 'seite:berichte' });
    expect(r.isError).toBeFalsy();
    expect(daten(r)).toEqual({ gezeigt: true, ziel: 'seite:berichte', titel: 'Berichte', bildschirm: 1, bildschirm_name: 'Bildschirm 1' });
    expect(r.structuredContent).toEqual(daten(r));
    expect(s.oeffneAufrufe).toEqual(['seite:berichte']);
    expect(wo(s.ap, 'seite:berichte')).toBe(1);
  });

  it('versteht Namen mit Umlaut-Schreibweisen und Groß-/Kleinschreibung', async () => {
    const { rufe } = shell();
    expect(daten(await rufe('os_oeffnen', { ziel: 'uebersicht' })).ziel).toBe('seite:uebersicht');
    expect(daten(await rufe('os_oeffnen', { ziel: 'NOTIZEN' })).ziel).toBe('app:notizen__liste');
  });

  it('holt eine schon offene Fläche nach vorn und holt sie aus der Minimierung', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'seite:berichte' });
    s.ap = fensterAendern(s.ap, 1, (l) => l.map((w) => ({ ...w, min: true })));
    const r = await rufe('os_oeffnen', { ziel: 'Berichte' });
    expect(r.isError).toBeFalsy();
    expect(s.ap.bildschirme[0]!.fenster[0]!.min).toBe(false);
  });

  it('sagt bei einer unbekannten Fläche, was es gibt, und öffnet nichts', async () => {
    const { s, rufe } = shell();
    const r = await rufe('os_oeffnen', { ziel: 'Quantenküche' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/Keine Fläche passt zu „Quantenküche“.*Berichte \(seite:berichte\)/s);
    expect(s.oeffneAufrufe).toEqual([]);
  });

  it('nennt bei einem mehrdeutigen Namen die Kandidaten', async () => {
    const { rufe } = shell();
    const r = await rufe('os_oeffnen', { ziel: 'Beri' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/mehrere Flächen.*Berichte \(seite:berichte\).*Berichte Archiv/s);
  });

  it('verlangt ein Ziel', async () => {
    const { rufe } = shell();
    for (const a of [{}, { ziel: '' }, { ziel: 7 }]) {
      const r = await rufe('os_oeffnen', a);
      expect(r.isError, JSON.stringify(a)).toBe(true);
      expect(text(r)).toMatch(/ziel fehlt/);
    }
  });

  describe('das Ereignis fyos:oeffnen', () => {
    it('geht an alle Zuhörer, abbrechbar, mit Ziel, Eingabe und Quelle', async () => {
      const { s, rufe } = shell();
      const gesehen: CustomEvent[] = [];
      s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => gesehen.push(e as CustomEvent));
      await rufe('os_oeffnen', { ziel: 'berichte', eingabe: { jahr: 2026 } });
      expect(OEFFNEN_EREIGNIS).toBe('fyos:oeffnen');
      expect(gesehen).toHaveLength(1);
      expect(gesehen[0]!.cancelable).toBe(true);
      expect(gesehen[0]!.detail).toEqual({ ziel: 'seite:berichte', eingabe: { jahr: 2026 }, quelle: 'bruecke' });
    });

    it('hat ohne Eingabe null als Eingabe (nie ein leeres Objekt)', async () => {
      const { s, rufe } = shell();
      const gesehen: CustomEvent[] = [];
      s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => gesehen.push(e as CustomEvent));
      await rufe('os_oeffnen', { ziel: 'berichte' });
      await rufe('os_oeffnen', { ziel: 'uebersicht', eingabe: {} });
      await rufe('os_oeffnen', { ziel: 'agent', eingabe: ['x'] });
      expect(gesehen.map((e) => e.detail.eingabe)).toEqual([null, null, null]);
    });

    it('geht auch an window, wenn die Shell keinen eigenen Empfänger vorgibt', async () => {
      const { k } = shell();
      const gesehen: CustomEvent[] = [];
      const h = (e: Event) => gesehen.push(e as CustomEvent);
      window.addEventListener(OEFFNEN_EREIGNIS, h);
      try {
        const r = await oeffnenMitPruefung({ ...k, ereignisse: undefined }, 'seite:berichte', { a: 1 });
        expect(r.ok).toBe(true);
        expect(gesehen).toHaveLength(1);
        expect(gesehen[0]!.detail).toEqual({ ziel: 'seite:berichte', eingabe: { a: 1 }, quelle: 'bruecke' });
      } finally {
        window.removeEventListener(OEFFNEN_EREIGNIS, h);
      }
    });

    it('unbehandelt öffnet die Shell die Fläche ohne Eingabe — und die Antwort sagt es', async () => {
      const { s, rufe } = shell();
      const r = await rufe('os_oeffnen', { ziel: 'berichte', eingabe: { jahr: 2026 } });
      expect(r.isError).toBeFalsy();
      expect(s.oeffneAufrufe).toEqual(['seite:berichte']);
      expect(daten(r)).toMatchObject({ gezeigt: true, eingabe_uebernommen: false });
      expect(daten(r).hinweis).toMatch(/nicht übergeben/);
    });

    it('behandelt ein Zuhörer das Ereignis (preventDefault), öffnet die Shell nicht selbst', async () => {
      const { s, k, rufe } = shell();
      s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => {
        e.preventDefault();
        // der Deeplink-/App-Rahmen-Strang öffnet die Fläche selbst, mit der Eingabe
        const r = flaecheOeffnen(s.ap, (e as CustomEvent).detail.ziel);
        s.ap = r.ap;
        s.fokus = (e as CustomEvent).detail.ziel;
      });
      const r = await rufe('os_oeffnen', { ziel: 'berichte', eingabe: { jahr: 2026 } });
      expect(r.isError).toBeFalsy();
      expect(s.oeffneAufrufe).toEqual([]);
      // Eine Seite kennt keine Eingabe: angenommen heißt hier nicht übernommen (Befund 10)
      expect(daten(r)).toMatchObject({ gezeigt: true, ziel: 'seite:berichte', eingabe_uebernommen: false });
      expect(daten(r).hinweis).toMatch(/nur Apps/);
      expect(k.quelle().ap.bildschirme).toHaveLength(1);
    });

    describe('eingabe_uebernommen sagt, ob die Eingabe wirklich ankam (Befund 10)', () => {
      /** Ein Zuhörer wie die Shell: nimmt das Ereignis an und öffnet die Fläche. */
      const wieShell = (s: ReturnType<typeof shell>['s']) =>
        s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => {
          e.preventDefault();
          const id = (e as CustomEvent).detail.ziel as string;
          s.ap = flaecheOeffnen(s.ap, id).ap;
          s.fokus = id;
        });

      it('einer App mit brauchbarer Eingabe: ja', async () => {
        const { s, rufe } = shell();
        wieShell(s);
        const r = daten(await rufe('os_oeffnen', { ziel: 'app:notizen__liste', eingabe: { eintrag: 'Entwurf' } }));
        expect(r).toMatchObject({ gezeigt: true, eingabe_uebernommen: true });
        expect(r.hinweis).toBeUndefined();
      });

      it('einer App mit zu großer Eingabe: nein — die Shell verwirft sie', async () => {
        const { s, rufe } = shell();
        wieShell(s);
        const r = daten(await rufe('os_oeffnen', { ziel: 'app:notizen__liste', eingabe: { text: 'x'.repeat(5_000) } }));
        expect(r).toMatchObject({ gezeigt: true, eingabe_uebernommen: false });
        expect(r.hinweis).toMatch(/zu groß/);
      });

      it('einer Seite: nein', async () => {
        const { s, rufe } = shell();
        wieShell(s);
        expect(daten(await rufe('os_oeffnen', { ziel: 'berichte', eingabe: { jahr: 2026 } }))).toMatchObject({ eingabe_uebernommen: false });
      });
    });

    it('ohne Eingabe gibt es kein Feld eingabe_uebernommen', async () => {
      const { rufe } = shell();
      expect(daten(await rufe('os_oeffnen', { ziel: 'berichte' }))).not.toHaveProperty('eingabe_uebernommen');
    });

    it('übernimmt ein Zuhörer, öffnet aber nichts, meldet das Werkzeug nach 1,5 s den Fehlschlag', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
      const { s, rufe } = shell();
      s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => e.preventDefault());
      const p = rufe('os_oeffnen', { ziel: 'berichte' });
      await vi.advanceTimersByTimeAsync(1_400);
      let fertig = false;
      void p.then(() => (fertig = true));
      await vi.advanceTimersByTimeAsync(0);
      expect(fertig).toBe(false); // wartet noch
      await vi.advanceTimersByTimeAsync(300);
      const r = await p;
      expect(r.isError).toBe(true);
      expect(text(r)).toMatch(/„Berichte“ ließ sich nicht öffnen/);
    });

    it('wartet, bis ein Zuhörer, der asynchron arbeitet, die Fläche geöffnet hat', async () => {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
      const { s, rufe } = shell();
      s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => {
        e.preventDefault();
        setTimeout(() => {
          s.ap = flaecheOeffnen(s.ap, 'seite:berichte').ap;
        }, 600);
      });
      const p = rufe('os_oeffnen', { ziel: 'berichte' });
      await vi.advanceTimersByTimeAsync(700);
      const r = await p;
      expect(r.isError).toBeFalsy();
      expect(daten(r)).toMatchObject({ gezeigt: true, bildschirm: 1 });
    });
  });

  it('sagt ehrlich, dass der Bildschirm voll ist', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const { s, rufe } = shell();
    let ap = flaecheOeffnen(leer(), 'seite:a0').ap;
    for (let i = 1; i < MAX_OFFEN; i++) ap = flaecheOeffnen(ap, `seite:a${i}`).ap;
    s.ap = wechseln(ap, 1);
    expect(s.ap.bildschirme[0]!.fenster).toHaveLength(MAX_OFFEN);
    const p = rufe('os_oeffnen', { ziel: 'berichte' });
    await vi.advanceTimersByTimeAsync(1_600);
    const r = await p;
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(new RegExp(`schon ${MAX_OFFEN} Flächen offen`));
  });

  it('der Agent-Dock gilt als offen: nichts wird geöffnet, die Antwort sagt „Dock“', async () => {
    const { s, rufe } = shell();
    s.agent = true;
    const gesehen: Event[] = [];
    s.ziel.addEventListener(OEFFNEN_EREIGNIS, (e) => gesehen.push(e));
    const r = await rufe('os_oeffnen', { ziel: 'agent' });
    expect(daten(r)).toEqual({ gezeigt: true, ziel: 'agent', titel: 'Agent', bildschirm: null, ort: 'dock' });
    expect(s.oeffneAufrufe).toEqual([]);
    expect(gesehen).toHaveLength(0);
  });

  it('ist der Agent-Dock zu, öffnet „agent“ ein Fenster', async () => {
    const { s, rufe } = shell();
    const r = await rufe('os_oeffnen', { ziel: 'agent' });
    expect(daten(r)).toMatchObject({ gezeigt: true, ziel: 'agent', bildschirm: 1 });
    expect(s.oeffneAufrufe).toEqual(['agent']);
  });
});

describe('os_fenster', () => {
  it('sagt bei leerem Start: nichts offen', async () => {
    const { rufe } = shell();
    const d = daten(await rufe('os_fenster'));
    expect(d).toMatchObject({ bildschirm: 0, bildschirm_name: 'Start', fenster: [], agent_offen: false, anruf_offen: false, agent_vorne: false });
    expect(d.hinweis).toBe('Es ist kein Fenster offen.');
    expect(d.bildschirme).toEqual([{ index: 0, name: 'Start' }]);
  });

  it('zählt die Fenster aller Bildschirme mit Titel, Art, vorn und minimiert', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    await rufe('os_oeffnen', { ziel: 'notizen' });
    s.ap = fensterAendern(s.ap, 1, (l) => l.map((w) => (w.id === 'app:notizen__liste' ? { ...w, min: true } : w)));
    const d = daten(await rufe('os_fenster'));
    expect(d).toMatchObject({ bildschirm: 1, bildschirm_name: 'Bildschirm 1', agent_offen: false, anruf_offen: false });
    expect(d.hinweis).toBeUndefined();
    expect(d.fenster).toEqual([
      { id: 'seite:berichte', titel: 'Berichte', art: 'seite', bildschirm: 1, bildschirm_name: 'Bildschirm 1', vorne: false, min: false },
      { id: 'app:notizen__liste', titel: 'Notizen', art: 'hubapp', bildschirm: 1, bildschirm_name: 'Bildschirm 1', vorne: false, min: true },
    ].map((w) => (w.id === 'seite:berichte' ? { ...w, vorne: true } : w)));
  });

  it('weiß von Anruf und Agent-Dock', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'nativ:anruf' });
    s.agent = true;
    expect(daten(await rufe('os_fenster'))).toMatchObject({ anruf_offen: true, agent_offen: true, agent_vorne: true });
  });
});

describe('os_schliessen', () => {
  it('schließt per ID und per Name — nur dieses Fenster', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    await rufe('os_oeffnen', { ziel: 'uebersicht' });
    await rufe('os_oeffnen', { ziel: 'notizen' });
    const r = await rufe('os_schliessen', { ziel: 'seite:berichte' });
    expect(daten(r)).toEqual({ geschlossen: true, id: 'seite:berichte', titel: 'Berichte', bildschirm: 1 });
    const r2 = await rufe('os_schliessen', { ziel: 'Übersicht' });
    expect(daten(r2)).toMatchObject({ geschlossen: true, id: 'seite:uebersicht' });
    expect(s.ap.bildschirme[0]!.fenster.map((w) => w.id)).toEqual(['app:notizen__liste']);
  });

  it('zählt auf, was offen ist, wenn nichts passt', async () => {
    const { rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    const r = await rufe('os_schliessen', { ziel: 'Notizen' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/Kein offenes Fenster passt zu „Notizen“.*Offen: Berichte \(seite:berichte\)/);
  });

  it('verlangt ein Ziel und kennt Mehrdeutigkeit', async () => {
    const { rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    await rufe('os_oeffnen', { ziel: 'seite:berichte-archiv' });
    expect(text(await rufe('os_schliessen', {}))).toMatch(/ziel fehlt/);
    const r = await rufe('os_schliessen', { ziel: 'Beri' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/mehrere offene Fenster/);
  });

  it('erklärt, dass der Agent-Dock kein Fenster ist', async () => {
    const { s, rufe } = shell();
    s.agent = true;
    const r = await rufe('os_schliessen', { ziel: 'agent' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/Dock offen, nicht als Fenster/);
  });

  it('meldet, wenn die Shell das Fenster nicht schließen konnte', async () => {
    const { s, k, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    const ohneErfolg = osWerkzeuge({ ...k, schliesse: () => false });
    const r = (await ohneErfolg.find((w) => w.name === 'os_schliessen')!.ausfuehren({ ziel: 'berichte' })) as WerkzeugErgebnis;
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/ließ sich nicht schließen/);
    expect(s.ap.bildschirme[0]!.fenster).toHaveLength(1);
  });

  it('meldet, wenn das Fenster nach dem Schließen noch da ist', async () => {
    const { k, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    const luegner = osWerkzeuge({ ...k, schliesse: () => true });
    const r = (await luegner.find((w) => w.name === 'os_schliessen')!.ausfuehren({ ziel: 'berichte' })) as WerkzeugErgebnis;
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/noch offen/);
  });
});

describe('os_zentrale', () => {
  const kachel = (i: number, extra: object = {}) => ({ id: `k${i}`, titel: `Kachel ${i}`, dringlichkeit: i, kurz: `Wert ${i}`, daten: { gross: 'egal' }, ...extra });

  it('verdichtet die Zentrale: Lage-Satz, Ampel, die dringlichsten zwölf Kacheln', async () => {
    const { s, rufe } = shell();
    s.zentrale = { lage_satz: 'Alles ruhig.', ampel: 'gruen', gruss: 'Moin', kacheln: Array.from({ length: 15 }, (_, i) => kachel(i)) };
    const d = daten(await rufe('os_zentrale'));
    expect(d.lage_satz).toBe('Alles ruhig.');
    expect(d.ampel).toBe('gruen');
    const k = d.kacheln as { id: string; dringlichkeit: number; kurz: string }[];
    expect(k).toHaveLength(12);
    expect(k.map((x) => x.id)).toEqual(['k14', 'k13', 'k12', 'k11', 'k10', 'k9', 'k8', 'k7', 'k6', 'k5', 'k4', 'k3']);
    expect(k[0]).toEqual({ id: 'k14', titel: 'Kachel 14', dringlichkeit: 14, kurz: 'Wert 14' });
    expect(d).not.toHaveProperty('leer');
  });

  it('behält „Quelle nicht erreichbar“ bei der Kachel', async () => {
    const { s, rufe } = shell();
    s.zentrale = { lage_satz: 'x', kacheln: [kachel(1, { quelle_ok: false }), kachel(2, { quelle_ok: true })] };
    const k = daten(await rufe('os_zentrale')).kacheln as Record<string, unknown>[];
    expect(k.find((x) => x.id === 'k1')).toHaveProperty('quelle_ok', false);
    expect(k.find((x) => x.id === 'k2')).not.toHaveProperty('quelle_ok');
  });

  it('sagt ehrlich, wenn keine Kacheln kommen', async () => {
    const { s, rufe } = shell();
    s.zentrale = { lage_satz: '', kacheln: [] };
    const d = daten(await rufe('os_zentrale'));
    expect(d).toMatchObject({ leer: true, kacheln: [] });
    expect(d.hinweis).toMatch(/keine Kacheln/);
    expect(zentraleKompakt(null)).toMatchObject({ leer: true, lage_satz: '', ampel: null });
    expect(zentraleKompakt({ kacheln: 'kaputt' })).toMatchObject({ leer: true });
  });

  it('übersetzt Hub-Fehler in einen Satz', async () => {
    const { k } = shell();
    const mit = async (f: () => Promise<unknown>) => {
      const w = osWerkzeuge({ ...k, zentrale: f }).find((x) => x.name === 'os_zentrale')!;
      return (await w.ausfuehren({})) as WerkzeugErgebnis;
    };
    const abgelaufen = await mit(async () => {
      throw new ApiError(401, undefined, 'Unauthorized');
    });
    expect(abgelaufen).toMatchObject({ isError: true });
    expect(text(abgelaufen)).toBe('Sitzung abgelaufen — neu anmelden.');
    expect(text(await mit(async () => {
      throw new ApiError(0, undefined, 'Failed to fetch');
    }))).toMatch(/Hub ist nicht erreichbar \(Failed to fetch\)/);
    expect(text(await mit(async () => {
      throw new ApiError(408, undefined, 'Zeit')
    }))).toMatch(/nicht rechtzeitig/);
    expect(text(await mit(async () => {
      throw new ApiError(502, undefined, 'Bad Gateway');
    }))).toMatch(/Hub meldet einen Fehler: Bad Gateway/);
    for (const status of [403, 404]) {
      const nicht = await mit(async () => {
        throw new ApiError(status, undefined, 'Nicht da');
      });
      expect(nicht).toMatchObject({ isError: true });
      expect(text(nicht)).toBe('Noch nicht eingerichtet.');
    }
    expect(text(await mit(async () => {
      throw new Error('kaputt');
    }))).toMatch(/nicht erreichbar \(kaputt\)/);
  });
});

describe('seite_lesen', () => {
  /** Ein Fenster im DOM nachstellen, so wie Fenster.tsx es zeichnet: [data-fenster="<id>"] mit dem Inhalt darin. */
  const fensterImDom = (wurzel: HTMLElement, id: string, innen: (el: HTMLElement) => void): HTMLElement => {
    const el = document.createElement('section');
    el.setAttribute('data-fenster', id);
    innen(el);
    wurzel.appendChild(el);
    return el;
  };
  const nativ = (t: string) => (el: HTMLElement) => {
    const inhalt = document.createElement('div');
    inhalt.setAttribute('data-kontext', 'inhalt');
    inhalt.textContent = t;
    el.appendChild(inhalt);
  };

  it('sagt auf dem leeren Start, dass kein Fenster offen ist, und verweist auf die Zentrale', async () => {
    const { rufe } = shell();
    const d = daten(await rufe('seite_lesen'));
    expect(d.leer).toBe(true);
    expect(d.hinweis).toMatch(/Start.*os_zentrale/);
  });

  it('sagt auf einem leeren Arbeitsbildschirm, was zu tun ist', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'berichte' });
    s.ap = fensterAendern(s.ap, 1, () => []);
    expect(daten(await rufe('seite_lesen')).hinweis).toMatch(/Auf diesem Bildschirm ist kein Fenster offen.*os_oeffnen/);
  });

  it('liest den Text einer nativen Fläche (der Fensterinhalt)', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'nativ:anruf' });
    fensterImDom(s.wurzel, 'nativ:anruf', nativ('Der Agent hört zu.\nSag etwas.'));
    const d = daten(await rufe('seite_lesen'));
    expect(d.fenster).toEqual({ id: 'nativ:anruf', titel: 'Anruf', art: 'nativ' });
    expect(d).toMatchObject({ text: 'Der Agent hört zu.\nSag etwas.', gekuerzt: false, zeichen_gesamt: 29 });
  });

  it('liest das benannte Fenster statt des vordersten', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'nativ:anruf' });
    await rufe('os_oeffnen', { ziel: 'uebersicht' });
    fensterImDom(s.wurzel, 'nativ:anruf', nativ('Anruftext'));
    fensterImDom(s.wurzel, 'seite:uebersicht', nativ('wird nicht gelesen'));
    const d = daten(await rufe('seite_lesen', { fenster: 'Anruf' }));
    expect(d.fenster).toMatchObject({ id: 'nativ:anruf' });
    expect(d.text).toBe('Anruftext');
    const unbekannt = await rufe('seite_lesen', { fenster: 'Berichte' });
    expect(unbekannt.isError).toBe(true);
    expect(text(unbekannt)).toMatch(/Kein offenes Fenster passt/);
  });

  it('kürzt auf zeichen, mit den Grenzen 500 bis 20000', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'nativ:anruf' });
    fensterImDom(s.wurzel, 'nativ:anruf', nativ('x'.repeat(30_000)));
    const knapp = daten(await rufe('seite_lesen', { zeichen: 800 }));
    expect(knapp).toMatchObject({ gekuerzt: true, zeichen_gesamt: 30_000 });
    expect((knapp.text as string).length).toBe(800);
    expect(((daten(await rufe('seite_lesen', { zeichen: 10 }))).text as string).length).toBe(500);
    expect(((daten(await rufe('seite_lesen', { zeichen: 99_999 }))).text as string).length).toBe(20_000);
    expect(((daten(await rufe('seite_lesen', {}))).text as string).length).toBe(6_000);
    expect(((daten(await rufe('seite_lesen', { zeichen: 'viel' }))).text as string).length).toBe(6_000);
  });

  it('sagt es, wenn das Fenster nichts zeigt, noch lädt oder minimiert ist', async () => {
    const { s, rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'nativ:anruf' });
    expect(text(await rufe('seite_lesen'))).toMatch(/offen, aber noch nicht geladen/); // nicht im DOM
    fensterImDom(s.wurzel, 'nativ:anruf', nativ('  '));
    expect(daten(await rufe('seite_lesen')).hinweis).toMatch(/keinen Text/);
    s.ap = fensterAendern(s.ap, 1, (l) => l.map((w) => ({ ...w, min: true })));
    const r = await rufe('seite_lesen', { fenster: 'nativ:anruf' });
    expect(r.isError).toBe(true);
    expect(text(r)).toMatch(/minimiert/);
  });

  it('Hub-Apps lassen sich nicht lesen — das Werkzeug sagt ehrlich warum und wohin man stattdessen geht', async () => {
    const { rufe } = shell();
    await rufe('os_oeffnen', { ziel: 'notizen' });
    const d = daten(await rufe('seite_lesen'));
    expect(d.text).toBeNull();
    expect(d.hinweis).toMatch(/abgeschirmt.*notizen__liste/);
  });

  describe('Seiten (same-origin iframe)', () => {
    const mitRahmen = (el: HTMLElement, rahmenFenster: unknown, rahmenDok: unknown) => {
      const rahmen = document.createElement('iframe');
      Object.defineProperty(rahmen, 'contentWindow', { get: () => rahmenFenster });
      Object.defineProperty(rahmen, 'contentDocument', { get: () => rahmenDok });
      el.appendChild(rahmen);
    };
    const dokument = (opt: { haupt?: string; body?: string; titel?: string; readyState?: string; href?: string }) => {
      const haupt = opt.haupt === undefined ? null : Object.assign(document.createElement('main'), { textContent: opt.haupt });
      const body = Object.assign(document.createElement('body'), { textContent: opt.body ?? '' });
      return { readyState: opt.readyState ?? 'complete', location: { href: opt.href ?? 'https://fyos.test/berichte' }, title: opt.titel ?? 'Berichte', querySelector: (sel: string) => (sel === 'main' ? haupt : null), body };
    };

    it('nimmt das eigene fyos_seite_lesen der Seite, mit Titel, Pfad und Zuständen', async () => {
      const { s, rufe } = shell();
      await rufe('os_oeffnen', { ziel: 'berichte' });
      const rufen = vi.fn(async () => ({ content: [{ type: 'text', text: JSON.stringify({ titel: 'Berichte', pfad: '/berichte', text: 'Kontostand 12.000 €', zustaende: { leer: 1 }, sitzung_abgelaufen: false }) }] }));
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, { fyos: { werkzeuge: { rufen } }, location: { pathname: '/berichte' } }, dokument({ haupt: 'Rückfall' })));
      const d = daten(await rufe('seite_lesen'));
      expect(rufen).toHaveBeenCalledWith('fyos_seite_lesen', {});
      expect(d).toMatchObject({
        fenster: { id: 'seite:berichte', titel: 'Berichte', art: 'seite' },
        seite: { titel: 'Berichte', pfad: '/berichte' },
        zustaende: { leer: 1 },
        text: 'Kontostand 12.000 €',
        gekuerzt: false,
      });
      expect(d).not.toHaveProperty('sitzung_abgelaufen');
    });

    it('reicht „Sitzung abgelaufen“ der Seite weiter', async () => {
      const { s, rufe } = shell();
      await rufe('os_oeffnen', { ziel: 'berichte' });
      const rufen = async () => ({ content: [{ type: 'text', text: JSON.stringify({ titel: 'Berichte', pfad: '/berichte', text: 'Bitte anmelden', sitzung_abgelaufen: true }) }] });
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, { fyos: { werkzeuge: { rufen } } }, dokument({})));
      expect(daten(await rufe('seite_lesen'))).toMatchObject({ sitzung_abgelaufen: true });
    });

    it('fällt auf <main> zurück, wenn die Seite kein eigenes Werkzeug hat oder es scheitert', async () => {
      const { s, rufe } = shell();
      await rufe('os_oeffnen', { ziel: 'berichte' });
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, { location: { pathname: '/berichte' } }, dokument({ haupt: 'Haupttext der Seite', body: 'Rahmen' })));
      expect(daten(await rufe('seite_lesen'))).toMatchObject({ text: 'Haupttext der Seite', seite: { titel: 'Berichte', pfad: '/berichte' } });

      s.wurzel.innerHTML = '';
      const kaputt = async () => ({ content: [{ type: 'text', text: 'Fehler' }], isError: true });
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, { fyos: { werkzeuge: { rufen: kaputt } }, location: { pathname: '/berichte' } }, dokument({ body: 'Nur der Rumpf' })));
      expect(daten(await rufe('seite_lesen')).text).toBe('Nur der Rumpf');
    });

    it('sagt „lädt noch“, wenn das Dokument lädt oder leer ist', async () => {
      const { s, rufe } = shell();
      await rufe('os_oeffnen', { ziel: 'berichte' });
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, {}, dokument({ readyState: 'loading' })));
      expect(text(await rufe('seite_lesen'))).toMatch(/lädt noch/);
      s.wurzel.innerHTML = '';
      fensterImDom(s.wurzel, 'seite:berichte', (el) => mitRahmen(el, {}, dokument({ href: 'about:blank' })));
      expect(text(await rufe('seite_lesen'))).toMatch(/lädt noch/);
    });

    it('sagt es, wenn der Rahmen noch fehlt oder von einem anderen Ursprung kommt', async () => {
      const { s, rufe } = shell();
      await rufe('os_oeffnen', { ziel: 'berichte' });
      fensterImDom(s.wurzel, 'seite:berichte', () => {});
      expect(text(await rufe('seite_lesen'))).toMatch(/noch keinen Inhalt geladen/);
      s.wurzel.innerHTML = '';
      fensterImDom(s.wurzel, 'seite:berichte', (el) => {
        const rahmen = document.createElement('iframe');
        Object.defineProperty(rahmen, 'contentWindow', {
          get: () => {
            throw new DOMException('Blocked a frame', 'SecurityError');
          },
        });
        el.appendChild(rahmen);
      });
      const r = await rufe('seite_lesen');
      expect(r.isError).toBe(true);
      expect(text(r)).toMatch(/nicht auf diesem Ursprung/);
    });
  });
});

describe('os_mitteilungen', () => {
  it('liest ohne Angaben nur', async () => {
    const { s, rufe } = shell();
    const d = daten(await rufe('os_mitteilungen'));
    expect(d).toEqual({ an: true, stumm: false, stumm_bis: null, satz: 'Mitteilungen des Agenten sind an.' });
    expect(s.einst).toEqual({ aus: false, stumm_bis: 0 });
  });

  it('schaltet aus und wieder an (und hebt dabei „stumm“ auf)', async () => {
    const { s, rufe } = shell();
    expect(daten(await rufe('os_mitteilungen', { an: false }))).toMatchObject({ an: false, stumm: false, satz: 'Mitteilungen des Agenten sind aus.' });
    expect(s.einst.aus).toBe(true);
    s.einst = { aus: false, stumm_bis: s.jetzt + 60_000 };
    expect(daten(await rufe('os_mitteilungen', { an: true }))).toMatchObject({ an: true, stumm: false });
    expect(s.einst).toEqual({ aus: false, stumm_bis: 0 });
  });

  it('stellt für Minuten stumm, deckelt auf einen Tag und hebt mit 0 auf', async () => {
    const { s, rufe } = shell();
    const d = daten(await rufe('os_mitteilungen', { stumm_minuten: 30 }));
    expect(d).toMatchObject({ an: true, stumm: true, satz: 'Mitteilungen des Agenten sind stumm.' });
    expect(s.einst.stumm_bis).toBe(s.jetzt + 30 * 60_000);
    expect(d.stumm_bis).toBe(new Date(s.jetzt + 30 * 60_000).toISOString());
    await rufe('os_mitteilungen', { stumm_minuten: 99_999 });
    expect(s.einst.stumm_bis).toBe(s.jetzt + 1440 * 60_000);
    const frei = daten(await rufe('os_mitteilungen', { stumm_minuten: 0 }));
    expect(frei).toMatchObject({ stumm: false, stumm_bis: null });
    expect(s.einst.stumm_bis).toBe(0);
  });

  it('„aus“ sagt nicht zugleich „stumm“', async () => {
    const { rufe } = shell();
    expect(daten(await rufe('os_mitteilungen', { an: false, stumm_minuten: 10 }))).toMatchObject({ an: false, stumm: false });
  });

  it('weist falsche Angaben ab, ohne etwas zu ändern', async () => {
    const { s, rufe } = shell();
    const vorher = { ...s.einst };
    for (const a of [{ an: 'nein' }, { an: 1 }, { stumm_minuten: -5 }, { stumm_minuten: 'bald' }]) {
      const r = await rufe('os_mitteilungen', a);
      expect(r.isError, JSON.stringify(a)).toBe(true);
    }
    expect(s.einst).toEqual(vorher);
  });
});

describe('Übergabe an den Rahmen', () => {
  it('ein Zuhörer, der nur zuschaut (kein preventDefault), ändert nichts: die Shell öffnet selbst', async () => {
    const { s, k } = shell();
    let gesehen = 0;
    s.ziel.addEventListener(OEFFNEN_EREIGNIS, () => gesehen++);
    const r = await oeffnenMitPruefung({ ...k, ereignisse: s.ziel }, 'seite:berichte', { a: 1 });
    expect(gesehen).toBe(1);
    expect(r).toMatchObject({ ok: true, ergebnis: { gezeigt: true, eingabe_uebernommen: false } });
    expect(s.oeffneAufrufe).toEqual(['seite:berichte']);
  });
});
