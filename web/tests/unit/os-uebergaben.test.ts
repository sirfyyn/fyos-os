/**
 * Übergaben zwischen Apps (Dinge ziehen, auf Fenster ablegen):
 *  - das Register nimmt Dinge und Übergaben der Hub-Apps auf und verwirft Ungültiges (lib/os/register.ts)
 *  - aus Ding und Übergabe werden die Argumente des Zielwerkzeugs (lib/os/uebergaben.ts)
 *  - das Fenster einer Hub-App sagt vor dem Loslassen, was passiert (ablageAufApp), und kennt auch den Zug aus dem iframe
 *  - der Host nimmt `fyos/zug` nur für Dinge des eigenen Plugins an und stellt `fyos/uebergabe` zu (lib/mcp-apps/host.ts)
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _zuruecksetzen, WARTEN_MS, anApp, appLaeuft, kanalAnmelden, kanalBereit } from '~/lib/mcp-apps/eingehaengt';
import { appEinhaengen, apps, uebergabeStarten, type McpApp } from '~/lib/mcp-apps/host';
import { registerZuruecksetzen, registriereFlaechen, registrierteDinge, registrierteUebergabe, type DingArt, type Uebergabe } from '~/lib/os/register';
import { ARGUMENTE_MAX, TEXT_MAX, ausfuellen, brauchtLesen, platzhalterIn, uebergabeVorbereiten } from '~/lib/os/uebergaben';
import { _wartend, ablageAufApp, aktuellerZug, frageUebergabe, gutArt, gutLesen, gutSetzen, wasPassiert, zugBeginnt, zugEndet, zustellen } from '~/lib/os/ziehen';

const DATEIEN = 'app:dateien__liste';
const ZETTEL = 'app:beispiel_app__zeigen';

const NOTIZ: DingArt = { name: 'Notiz', flaeche: ZETTEL, lesen: 'beispiel_app__lesen', idArgument: 'id', felder: ['text', 'titel', 'dateiname'] };
const DATEI: DingArt = { name: 'Datei', flaeche: DATEIEN, lesen: 'dateien__lesen', idArgument: 'pfad', felder: [] };
const NOTIZ_ZU_DATEI: Uebergabe = {
  quelle: 'notiz', ziel: DATEIEN, werkzeug: 'dateien__schreiben',
  abbildung: { pfad: 'Notizen/{dateiname}.md', inhalt: '{text}\n' }, wirkung: 'Als Markdown-Datei in „Dateien“ ablegen',
};
const DATEI_ZU_NOTIZ: Uebergabe = {
  quelle: 'datei', ziel: ZETTEL, werkzeug: 'beispiel_app__hinzufuegen', abbildung: { text: 'Datei {id}' }, wirkung: 'Als Notiz auf dem Zettel merken',
};

/** jsdom hat kein DataTransfer: ein schlichtes Gegenstück. */
class Zug {
  daten = new Map<string, string>();
  get types(): string[] {
    return [...this.daten.keys()];
  }
  setData(t: string, v: string) {
    this.daten.set(t.toLowerCase(), v);
  }
  getData(t: string) {
    return this.daten.get(t.toLowerCase()) ?? '';
  }
}
const dt = () => new Zug() as unknown as DataTransfer;

beforeEach(() => {
  registriereFlaechen({ dinge: { notiz: NOTIZ, datei: DATEI }, uebergaben: [NOTIZ_ZU_DATEI, DATEI_ZU_NOTIZ] });
});
afterEach(() => {
  registerZuruecksetzen();
  zugEndet();
  _wartend.clear();
  _zuruecksetzen();
  vi.useRealTimers();
});

// ── Register ────────────────────────────────────────────────────────────────────────────────────────

describe('Register', () => {
  it('nimmt Dinge einer Hub-App mit Fläche, Lesewerkzeug und Feldern auf', () => {
    expect(registrierteDinge('notiz')).toEqual(NOTIZ);
    expect(registrierteDinge('datei')).toMatchObject({ flaeche: DATEIEN, idArgument: 'pfad' });
    expect(registrierteUebergabe('notiz', DATEIEN)).toEqual(NOTIZ_ZU_DATEI);
    expect(registrierteUebergabe('notiz', ZETTEL)).toBeUndefined();
    expect(registrierteUebergabe('datei', DATEIEN)).toBeUndefined();
  });

  it('verwirft Ungültiges, statt es einzulassen', () => {
    registerZuruecksetzen();
    registriereFlaechen({
      dinge: {
        ohneFlaeche: { name: 'Nichts' },
        'böse typ': { name: 'x', flaeche: ZETTEL },
        __proto__: { name: 'x', flaeche: ZETTEL },
        falscheFlaeche: { name: 'x', flaeche: 'seite:wiki' },
        ok: { name: 'Gut', flaeche: ZETTEL, lesen: 'kein-werkzeug', idArgument: 'Pfad Art', felder: ['text', 'Gross', 3 as unknown as string] },
      } as unknown as Record<string, DingArt>,
      uebergaben: [
        { quelle: 'ok', ziel: 'seite:wiki', werkzeug: 'a__b', abbildung: {}, wirkung: 'x' },
        { quelle: 'ok', ziel: DATEIEN, werkzeug: 'a.b', abbildung: {}, wirkung: 'x' },
        { quelle: 'ok', ziel: DATEIEN, werkzeug: 'a__b', abbildung: {}, wirkung: '' },
        { quelle: 'ok', ziel: DATEIEN, werkzeug: 'a__b', abbildung: [] as never, wirkung: 'x' },
        { quelle: 'ok', ziel: DATEIEN, werkzeug: 'a__b', abbildung: { text: 'x', Gross: 'y', liste: [1] as never, __proto__: 'z' as never, ja: true, n: 3 }, wirkung: 'w'.repeat(500) },
      ] as Uebergabe[],
    });
    expect(registrierteDinge('ohneFlaeche')).toBeUndefined();
    expect(registrierteDinge('böse typ')).toBeUndefined();
    expect(registrierteDinge('falscheFlaeche')).toBeUndefined();
    // Ohne gültiges Lesewerkzeug, Kennungsargument und Feldnamen bleibt nur, was gültig ist
    expect(registrierteDinge('ok')).toEqual({ name: 'Gut', flaeche: ZETTEL, felder: ['text'] });
    const u = registrierteUebergabe('ok', DATEIEN)!;
    expect(u.abbildung).toEqual({ text: 'x', ja: true, n: 3 });
    expect(u.wirkung.length).toBe(160);
  });

  it('eine Seite meldet weiter nur ihren Pfad', () => {
    registriereFlaechen({ dinge: { termin: { name: 'Termin', pfad: '/kalender/' } } });
    expect(registrierteDinge('termin')).toEqual({ name: 'Termin', pfad: '/kalender/' });
  });
});

// ── Argumente aus Ding und Übergabe ────────────────────────────────────────────────────────────────

describe('Übergabe vorbereiten', () => {
  it('findet die Platzhalter und weiß, ob das Ding erst gelesen werden muss', () => {
    expect([...platzhalterIn(NOTIZ_ZU_DATEI.abbildung)].sort()).toEqual(['dateiname', 'text']);
    expect(brauchtLesen(NOTIZ_ZU_DATEI)).toBe(true);
    expect(brauchtLesen(DATEI_ZU_NOTIZ)).toBe(false);
    expect(brauchtLesen({ ...DATEI_ZU_NOTIZ, abbildung: { text: '{label}', n: 3 } })).toBe(false);
  });

  it('setzt ein, lässt andere Werte stehen und ersetzt Eingesetztes nicht noch einmal', () => {
    expect(ausfuellen({ a: '{id}: {label}', b: 3, c: false }, { id: '7', label: 'Milch' })).toEqual({ a: '7: Milch', b: 3, c: false });
    expect(ausfuellen({ inhalt: '{text}' }, { id: 'GEHEIM', label: 'l', text: '{id}' })).toEqual({ inhalt: '{id}' });
  });

  it('wirft bei fehlendem Feld und bei zu Großem', () => {
    expect(() => ausfuellen({ a: '{text}' }, { id: '1', label: 'x' })).toThrow('Das Feld „text“ fehlt.');
    expect(() => ausfuellen({ a: '{text}' }, { id: '1', label: 'x', text: 'x'.repeat(TEXT_MAX + 1) })).toThrow(/zu groß/);
    const viele = Object.fromEntries(Array.from({ length: 5 }, (_, i) => [`a${i}`, '{text}']));
    expect(() => ausfuellen(viele, { id: '1', label: 'x', text: 'x'.repeat(ARGUMENTE_MAX / 4) })).toThrow(/zu groß/);
  });

  it('liest die Notiz über ihr Lesewerkzeug und füllt das Zielwerkzeug', async () => {
    const lesen = vi.fn(async () => ({ id: 'n-1', text: 'Milch kaufen\nund Brot', titel: 'Milch kaufen', dateiname: 'Milch kaufen', zeit: 5, geheim: 'nicht angemeldet' }));
    const v = await uebergabeVorbereiten(NOTIZ_ZU_DATEI, NOTIZ, { typ: 'notiz', id: 'n-1', label: 'Milch kaufen' }, lesen);
    expect(lesen).toHaveBeenCalledWith('beispiel_app__lesen', { id: 'n-1' });
    expect(v).toEqual({
      typ: 'notiz', id: 'n-1', label: 'Milch kaufen', werkzeug: 'dateien__schreiben',
      argumente: { pfad: 'Notizen/Milch kaufen.md', inhalt: 'Milch kaufen\nund Brot\n' }, wirkung: NOTIZ_ZU_DATEI.wirkung,
    });
  });

  it('liest nicht, wenn Kennung und Name genügen, und nennt das Kennungsargument des Typs', async () => {
    const lesen = vi.fn(async () => ({}));
    const v = await uebergabeVorbereiten(DATEI_ZU_NOTIZ, DATEI, { typ: 'datei', id: 'Projekt/Plan.md' }, lesen);
    expect(lesen).not.toHaveBeenCalled();
    expect(v.argumente).toEqual({ text: 'Datei Projekt/Plan.md' });
    expect(v.label).toBe('Projekt/Plan.md');
    const mitFeld = { ...DATEI_ZU_NOTIZ, abbildung: { text: '{inhalt}' } };
    await uebergabeVorbereiten(mitFeld, { ...DATEI, felder: ['inhalt'] }, { typ: 'datei', id: 'a.md' }, async (w, a) => {
      expect(w).toBe('dateien__lesen');
      expect(a).toEqual({ pfad: 'a.md' });
      return { inhalt: 'Text' };
    });
  });

  it('sagt in einem Satz, warum es nicht geht', async () => {
    const nein = async () => {
      throw new Error('keine Notiz „n-9“');
    };
    await expect(uebergabeVorbereiten(NOTIZ_ZU_DATEI, NOTIZ, { typ: 'notiz', id: 'n-9' }, nein)).rejects.toThrow('Notiz „n-9“ lässt sich nicht lesen: keine Notiz „n-9“');
    await expect(uebergabeVorbereiten(NOTIZ_ZU_DATEI, { name: 'Notiz', flaeche: ZETTEL }, { typ: 'notiz', id: 'n-1' }, nein)).rejects.toThrow('Notiz lässt sich nicht lesen.');
    // Ein Feld, das das Ergebnis nicht hat (oder das keine Zahl und kein Text ist), fehlt
    await expect(uebergabeVorbereiten(NOTIZ_ZU_DATEI, NOTIZ, { typ: 'notiz', id: 'n-1', label: 'x' }, async () => ({ text: 'a', dateiname: { x: 1 } }))).rejects.toThrow(
      'Notiz „x“ lässt sich hier nicht ablegen: Das Feld „dateiname“ fehlt.',
    );
  });
});

// ── Fenster einer Hub-App als Ziel ──────────────────────────────────────────────────────────────────

describe('Ablage auf dem Fenster einer Hub-App', () => {
  it('mit Übergabe sagt der Hinweis, was passiert', () => {
    expect(ablageAufApp('notiz', DATEIEN)).toEqual({ modus: 'uebergabe', text: 'Als Markdown-Datei in „Dateien“ ablegen', uebergabe: NOTIZ_ZU_DATEI });
    expect(ablageAufApp('datei', ZETTEL)).toMatchObject({ modus: 'uebergabe', text: 'Als Notiz auf dem Zettel merken' });
  });

  it('ohne Übergabe bleibt nur, den Agenten zu fragen', () => {
    registriereFlaechen({ dinge: { vorgang: { name: 'Vorgang', flaeche: 'app:vorgaenge__zeigen' } } });
    expect(ablageAufApp('vorgang', DATEIEN)).toEqual({ modus: 'agent', text: 'Agent dazu fragen' });
    expect(ablageAufApp('notiz', 'app:haus__favoriten')).toEqual({ modus: 'agent', text: 'Agent dazu fragen' });
  });

  it('auf dem Fenster der eigenen App und bei Fenstern und Flächen gilt die allgemeine Regel', () => {
    expect(ablageAufApp('notiz', ZETTEL)).toBeNull();
    expect(ablageAufApp('datei', DATEIEN)).toBeNull();
    expect(ablageAufApp('fenster', DATEIEN)).toBeNull();
    expect(ablageAufApp('flaeche', DATEIEN)).toBeNull();
    expect(ablageAufApp(null, DATEIEN)).toBeNull();
    expect(ablageAufApp('unbekannt', DATEIEN)).toBeNull();
  });

  it('formuliert die Frage an den Agenten mit Ding und App', () => {
    const f = frageUebergabe({ art: 'ding', typ: 'notiz', id: 'n-1', label: 'Milch' }, 'Haus');
    expect(f).toContain('Notiz n-1 („Milch“)');
    expect(f).toContain('„Haus“');
  });

  it('Hub-Dinge gehen auch zum Agenten und auf den Schreibtisch', () => {
    expect(wasPassiert('notiz', 'agent')).toBe('Agent dazu fragen');
    expect(wasPassiert('datei', 'schreibtisch')).toBe('Datei öffnen');
  });
});

describe('Zug aus dem iframe einer Hub-App', () => {
  it('erkennt das Ding auch, wenn der Browser den eigenen Schlüssel nicht über die Fenstergrenze reicht', () => {
    const d = dt();
    d.setData('text/plain', 'fyos://datei/Projekt/Plan.md'); // nur das kommt an
    expect(gutArt(d)).toBeNull();
    const quelle = { postMessage() {} } as unknown as MessageEventSource;
    zugBeginnt({ art: 'datei', quelle });
    expect(gutArt(d)).toBe('datei');
    expect(gutLesen(d)).toEqual({ art: 'ding', typ: 'datei', id: 'Projekt/Plan.md' });
    // Kein Zug der Shell selbst (ohne quelle) und kein fremder Text darf das erfinden
    zugEndet();
    zugBeginnt({ art: 'datei' });
    expect(gutArt(d)).toBeNull();
    zugEndet();
    zugBeginnt({ art: 'datei', quelle });
    expect(gutArt(dt())).toBeNull();
  });

  it('der Zug trägt Kennung mit Schrägstrichen und Leerzeichen unversehrt', () => {
    const d = dt();
    gutSetzen(d, { art: 'ding', typ: 'datei', id: 'Projekt/Notizen & mehr/heute früh.md', label: 'heute früh.md' });
    expect(gutLesen(d)).toEqual({ art: 'ding', typ: 'datei', id: 'Projekt/Notizen & mehr/heute früh.md', label: 'heute früh.md' });
  });
});

// ── Zustellen an Hub-Apps ───────────────────────────────────────────────────────────────────────────

describe('Zustellen an eine App im Fenster', () => {
  it('„zeig dieses Ding“ geht als fyos/oeffne an die laufende App', () => {
    const melden = vi.fn();
    kanalAnmelden(DATEIEN, { melden });
    kanalBereit(DATEIEN);
    zustellen(DATEIEN, { fyosOeffne: { typ: 'datei', id: 'a/b.md' } });
    expect(melden).toHaveBeenCalledWith('fyos/oeffne', { typ: 'datei', id: 'a/b.md' });
    // nichts bleibt für später liegen, und die Seiten-Warteschlange bleibt leer
    expect(_wartend.size).toBe(0);
  });

  it('wartet, bis die App sich gemeldet hat, aber nicht ewig', () => {
    vi.useFakeTimers();
    const melden = vi.fn();
    kanalAnmelden(DATEIEN, { melden });
    anApp(DATEIEN, 'fyos/oeffne', { typ: 'datei', id: 'a.md' });
    expect(melden).not.toHaveBeenCalled();
    kanalBereit(DATEIEN);
    expect(melden).toHaveBeenCalledTimes(1);
    melden.mockClear();
    anApp(ZETTEL, 'fyos/oeffne', { typ: 'notiz', id: 'n' }); // die App läuft noch nicht
    vi.advanceTimersByTime(WARTEN_MS + 1000);
    kanalAnmelden(ZETTEL, { melden });
    kanalBereit(ZETTEL);
    expect(melden).not.toHaveBeenCalled(); // zu alt
  });

  it('eine neuere Einbettung bleibt, wenn die alte sich abmeldet', () => {
    const alt = vi.fn();
    const neu = vi.fn();
    const abAlt = kanalAnmelden(DATEIEN, { melden: alt });
    kanalAnmelden(DATEIEN, { melden: neu });
    abAlt();
    expect(appLaeuft(DATEIEN)).toBe(true);
    kanalBereit(DATEIEN);
    anApp(DATEIEN, 'x', {});
    expect(neu).toHaveBeenCalledTimes(1);
    expect(alt).not.toHaveBeenCalled();
  });

  it('ignoriert eine Nachricht ohne gültiges Ding und Seiten-Flächen gehen den alten Weg', () => {
    const melden = vi.fn();
    kanalAnmelden(DATEIEN, { melden });
    kanalBereit(DATEIEN);
    zustellen(DATEIEN, { fyosOeffne: { typ: 3 } });
    zustellen(DATEIEN, 'text');
    zustellen('seite:notizen', { fyosOeffne: { typ: 'notiz', id: 'n' } });
    expect(melden).not.toHaveBeenCalled();
    expect(_wartend.has('seite:notizen')).toBe(true);
  });
});

// ── Host ────────────────────────────────────────────────────────────────────────────────────────────

const app = (name: string): McpApp =>
  ({ tool: name.replace('__', '.'), name, description: 'x', inputSchema: {}, _meta: { ui: { resourceUri: 'ui://fyos/x.html' } }, scope: 'READ' }) as McpApp;

type Nachricht = { id?: number; method?: string; params?: Record<string, unknown>; result?: Record<string, unknown>; error?: { message: string } };
const abmeldungen: (() => void)[] = [];
let aufrufe: { name: string; args: Record<string, unknown> }[];

beforeEach(() => {
  aufrufe = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      const json = (o: unknown) => new Response(JSON.stringify(o), { headers: { 'content-type': 'application/json' } });
      if (u.includes('/hub-api/resource')) return json({ ok: true, text: '<p>x</p>' });
      if (u.includes('/hub-api/apps')) {
        return json({ ok: true, apps: [], dinge: { notiz: NOTIZ, datei: DATEI }, uebergaben: [NOTIZ_ZU_DATEI] });
      }
      if (u.includes('/hub-api/app-call')) {
        const b = JSON.parse(String(init?.body)) as { name: string; arguments: Record<string, unknown> };
        aufrufe.push({ name: b.name, args: b.arguments });
        if (b.arguments.id === 'weg') return json({ ok: false, error: 'keine Notiz „weg“' });
        return json({ ok: true, result: { id: b.arguments.id, text: 'Milch kaufen', titel: 'Milch kaufen', dateiname: 'Milch kaufen' } });
      }
      return new Response('{}', { status: 404 });
    }),
  );
});
afterEach(() => {
  while (abmeldungen.length) abmeldungen.pop()!();
  document.body.innerHTML = '';
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function einhaengen(a: McpApp, schluessel?: string) {
  const f = document.createElement('iframe');
  document.body.appendChild(f);
  const nachrichten: Nachricht[] = [];
  abmeldungen.push(await appEinhaengen(f, { app: a, args: {}, ergebnis: { content: [] }, theme: () => 'dark', ...(schluessel ? { schluessel } : {}) }));
  vi.spyOn(f.contentWindow!, 'postMessage').mockImplementation((m: unknown) => {
    nachrichten.push(m as Nachricht);
  });
  const sprechen = (method: string, params: unknown, id?: number) =>
    window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: { jsonrpc: '2.0', ...(id != null ? { id } : {}), method, params } }));
  const auf = (id: number) => vi.waitFor(() => expect(nachrichten.find((x) => x.id === id)).toBeTruthy()).then(() => nachrichten.find((x) => x.id === id)!);
  return { f, sprechen, auf, nachrichten };
}

describe('Host: Dinge und Übergaben aus dem Hub', () => {
  it('nimmt Dinge und Übergaben mit der Liste der Apps ins Register', async () => {
    registerZuruecksetzen();
    await apps(false);
    expect(registrierteDinge('notiz')).toMatchObject({ flaeche: ZETTEL, lesen: 'beispiel_app__lesen' });
    expect(registrierteUebergabe('notiz', DATEIEN)?.werkzeug).toBe('dateien__schreiben');
  });

  it('meldet jeder App die Fähigkeit fyosUebergaben', async () => {
    const h = await einhaengen(app('haus__favoriten'));
    h.sprechen('ui/initialize', { protocolVersion: '2026-01-26' }, 1);
    expect(((await h.auf(1)).result as { hostCapabilities: object }).hostCapabilities).toHaveProperty('fyosUebergaben');
  });
});

describe('Host: fyos/zug', () => {
  it('die App zieht ein Ding ihres Plugins: Zug beginnt mit ihr als Quelle, am Ende endet er', async () => {
    const d = await einhaengen(app('dateien__liste'), DATEIEN);
    d.sprechen('fyos/zug', { typ: 'datei', id: 'a.md', label: 'a.md' });
    expect(aktuellerZug()).toMatchObject({ art: 'datei' });
    expect(aktuellerZug()?.quelle).toBe(d.f.contentWindow);
    d.sprechen('fyos/zug', { typ: null });
    expect(aktuellerZug()).toBeNull();
  });

  it('eine App kann keine fremden oder unbekannten Dinge melden', async () => {
    const d = await einhaengen(app('dateien__liste'), DATEIEN);
    d.sprechen('fyos/zug', { typ: 'notiz' }); // gehört dem Notizzettel
    expect(aktuellerZug()).toBeNull();
    d.sprechen('fyos/zug', { typ: 'gibtsnicht' });
    d.sprechen('fyos/zug', { typ: 7 });
    d.sprechen('fyos/zug', {});
    expect(aktuellerZug()).toBeNull();
  });

  it('das Ende kommt nur von der App, aus der gezogen wird', async () => {
    const d = await einhaengen(app('dateien__liste'), DATEIEN);
    const z = await einhaengen(app('beispiel_app__zeigen'), ZETTEL);
    d.sprechen('fyos/zug', { typ: 'datei' });
    z.sprechen('fyos/zug', { typ: null });
    expect(aktuellerZug()).not.toBeNull();
    d.sprechen('fyos/zug', { typ: null });
    expect(aktuellerZug()).toBeNull();
  });

  it('verschwindet die App mitten im Ziehen, bleibt kein Zug hängen', async () => {
    const f = document.createElement('iframe');
    document.body.appendChild(f);
    const ab = await appEinhaengen(f, { app: app('dateien__liste'), args: {}, ergebnis: { content: [] }, theme: () => 'dark', schluessel: DATEIEN });
    window.dispatchEvent(new MessageEvent('message', { source: f.contentWindow, data: { jsonrpc: '2.0', method: 'fyos/zug', params: { typ: 'datei' } } }));
    expect(aktuellerZug()).not.toBeNull();
    ab();
    expect(aktuellerZug()).toBeNull();
    expect(appLaeuft(DATEIEN)).toBe(false);
  });
});

describe('Host: Übergabe zustellen', () => {
  it('liest die Notiz, setzt ein und stellt der Ziel-App das fertige Zielwerkzeug zu — sobald sie bereit ist', async () => {
    const d = await einhaengen(app('dateien__liste'), DATEIEN);
    await uebergabeStarten(DATEIEN, NOTIZ_ZU_DATEI, { typ: 'notiz', id: 'n-1', label: 'Milch kaufen' });
    expect(aufrufe).toEqual([{ name: 'beispiel_app__lesen', args: { id: 'n-1' } }]);
    expect(d.nachrichten.find((n) => n.method === 'fyos/uebergabe')).toBeUndefined(); // die App hat sich noch nicht gemeldet
    d.sprechen('ui/notifications/initialized', {});
    const u = d.nachrichten.find((n) => n.method === 'fyos/uebergabe');
    expect(u?.params).toEqual({
      typ: 'notiz', id: 'n-1', label: 'Milch kaufen', werkzeug: 'dateien__schreiben',
      argumente: { pfad: 'Notizen/Milch kaufen.md', inhalt: 'Milch kaufen\n' }, wirkung: NOTIZ_ZU_DATEI.wirkung,
    });
    // Nur zugestellt: nichts angelegt (kein Aufruf des Zielwerkzeugs durch den Host)
    expect(aufrufe.some((a) => a.name === 'dateien__schreiben')).toBe(false);
  });

  it('ein Ding, das sich nicht lesen lässt, wirft einen Satz für Menschen und stellt nichts zu', async () => {
    const d = await einhaengen(app('dateien__liste'), DATEIEN);
    d.sprechen('ui/notifications/initialized', {});
    await expect(uebergabeStarten(DATEIEN, NOTIZ_ZU_DATEI, { typ: 'notiz', id: 'weg', label: 'weg' })).rejects.toThrow(/lässt sich nicht lesen: keine Notiz „weg“/);
    expect(d.nachrichten.find((n) => n.method === 'fyos/uebergabe')).toBeUndefined();
  });

  it('Datei zu Notiz braucht keinen Lesezugriff', async () => {
    const z = await einhaengen(app('beispiel_app__zeigen'), ZETTEL);
    z.sprechen('ui/notifications/initialized', {});
    await uebergabeStarten(ZETTEL, DATEI_ZU_NOTIZ, { typ: 'datei', id: 'Projekt/Plan.md', label: 'Plan.md' });
    expect(aufrufe).toEqual([]);
    expect(z.nachrichten.find((n) => n.method === 'fyos/uebergabe')?.params).toMatchObject({ werkzeug: 'beispiel_app__hinzufuegen', argumente: { text: 'Datei Projekt/Plan.md' } });
  });
});
