/**
 * Übergänge ins OS :
 *   https://fyos.example/os?offen=app:<plugin>__<werkzeug>&eingabe=<base64url(JSON)>
 * Die Eingabe kommt aus einer Adresse, also von außen: sie wird nur gelesen, wenn sie ein JSON-Objekt unter
 * der Größengrenze ist, und gefährliche Schlüssel fallen heraus.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  EINGABE_MAX, OEFFNEN, oeffentlicherUrsprungSetzen, deeplink, eingabeKodieren, eingabeLesen, eingabeSauber, imOsOeffnen, osZielAus, pfadSchluessel,
  type OsZiel,
} from '~/lib/os/oeffnen';

const base64url = (text: string): string => {
  const bytes = new TextEncoder().encode(text);
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const HIER = { origin: 'http://127.0.0.1:4431', href: 'http://127.0.0.1:4431/os/' };
const OEFFENTLICH = 'https://fyos.example';

beforeEach(() => oeffentlicherUrsprungSetzen(OEFFENTLICH));
afterEach(() => oeffentlicherUrsprungSetzen(null));

describe('eingabeSauber', () => {
  it('lässt ein JSON-Objekt als tiefe Kopie durch', () => {
    const roh = { raum: 'Küche', liste: [1, 2], tief: { a: true } };
    const sauber = eingabeSauber(roh);
    expect(sauber).toEqual(roh);
    expect(sauber).not.toBe(roh);
    expect(sauber!.tief).not.toBe(roh.tief);
  });

  it('weist Arrays, Zahlen, Text und Leeres ab', () => {
    for (const x of [[1, 2], 42, 'text', null, undefined, true]) expect(eingabeSauber(x)).toBeUndefined();
  });

  it('entfernt __proto__, constructor und prototype auf jeder Ebene', () => {
    const roh = JSON.parse('{"a":1,"__proto__":{"boese":1},"tief":{"constructor":{"x":1},"prototype":2,"ok":3}}');
    const sauber = eingabeSauber(roh)!;
    expect(Object.prototype.hasOwnProperty.call(sauber, '__proto__')).toBe(false);
    expect(Object.getPrototypeOf(sauber)).toBe(Object.prototype);
    expect(({} as Record<string, unknown>).boese).toBeUndefined();
    expect(sauber.tief).toEqual({ ok: 3 });
    expect(sauber.a).toBe(1);
  });

  it('weist zu große Eingaben ab (mehr als 4000 JSON-Zeichen)', () => {
    expect(eingabeSauber({ text: 'x'.repeat(EINGABE_MAX - 12) })).toBeDefined();
    expect(eingabeSauber({ text: 'x'.repeat(EINGABE_MAX) })).toBeUndefined();
  });

  it('weist Zirkuläres ab, statt zu werfen', () => {
    const a: Record<string, unknown> = {};
    a.selbst = a;
    expect(eingabeSauber(a)).toBeUndefined();
  });
});

describe('eingabeKodieren und eingabeLesen', () => {
  it('geben dieselben Argumente zurück, auch mit Umlauten, Emoji und Sonderzeichen', () => {
    const eingabe = { raum: 'Küche', zeichen: '«ß€» 🌡️ ?&=/+', zahl: 3.5, liste: ['a', { b: null }] };
    const k = eingabeKodieren(eingabe)!;
    expect(k).toMatch(/^[A-Za-z0-9_-]+$/); // base64url: kein +, /, = (taugt für die Adresse)
    expect(eingabeLesen(k)).toEqual(eingabe);
  });

  it('kodiert den Vertrag wörtlich: base64url der UTF-8-Bytes des JSON', () => {
    expect(eingabeKodieren({ raum: 'Küche' })).toBe(base64url('{"raum":"Küche"}'));
    expect(eingabeLesen(base64url('{"q":"≥"}'))).toEqual({ q: '≥' });
  });

  it('nimmt auch Auffüllzeichen und Standard-Alphabet-Reste an', () => {
    const mitFuell = btoa('{"a":1}'); // eKFhIjoxfQ==
    expect(mitFuell.endsWith('=')).toBe(true);
    expect(eingabeLesen(mitFuell)).toEqual({ a: 1 });
    expect(eingabeLesen(base64url('{"a":1}'))).toEqual({ a: 1 });
  });

  it('kodiert Leeres und Zu-Großes nicht', () => {
    expect(eingabeKodieren({})).toBeUndefined();
    expect(eingabeKodieren(undefined)).toBeUndefined();
    expect(eingabeKodieren(null)).toBeUndefined();
    expect(eingabeKodieren({ text: 'x'.repeat(EINGABE_MAX) })).toBeUndefined();
  });

  it('liest nichts aus Ungültigem', () => {
    expect(eingabeLesen(undefined)).toBeUndefined();
    expect(eingabeLesen(null)).toBeUndefined();
    expect(eingabeLesen('')).toBeUndefined();
    expect(eingabeLesen('kein base64!')).toBeUndefined();
    expect(eingabeLesen('a=b=')).toBeUndefined();
    expect(eingabeLesen(base64url('kein json'))).toBeUndefined();
    expect(eingabeLesen(base64url('[1,2,3]'))).toBeUndefined(); // Array, kein Objekt
    expect(eingabeLesen(base64url('"text"'))).toBeUndefined();
    expect(eingabeLesen('x'.repeat(16_401))).toBeUndefined();
  });

  it('weist ungültiges UTF-8 ab, statt es zu „reparieren"', () => {
    const kaputt = btoa(String.fromCharCode(0x7b, 0x22, 0xff, 0xfe, 0x22, 0x7d)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    expect(eingabeLesen(kaputt)).toBeUndefined();
  });

  it('entfernt auch beim Lesen gefährliche Schlüssel', () => {
    const e = eingabeLesen(base64url('{"__proto__":{"x":1},"ok":1}'))!;
    expect(e).toEqual({ ok: 1 });
    expect(Object.prototype.hasOwnProperty.call(e, '__proto__')).toBe(false);
  });
});

describe('deeplink', () => {
  it('baut die Adresse nach Vertrag 2: Doppelpunkt lesbar, Eingabe als base64url', () => {
    const link = deeplink('app:haus__favoriten', { raum: 'Küche' }, OEFFENTLICH);
    expect(link).toBe(`https://fyos.example/os/?offen=app:haus__favoriten&eingabe=${base64url('{"raum":"Küche"}')}`);
    const u = new URL(link);
    expect(u.searchParams.get('offen')).toBe('app:haus__favoriten');
    expect(eingabeLesen(u.searchParams.get('eingabe'))).toEqual({ raum: 'Küche' });
  });

  it('lässt „&eingabe" weg, wenn es nichts mitzugeben gibt', () => {
    expect(deeplink('app:haus__favoriten', {}, OEFFENTLICH)).toBe('https://fyos.example/os/?offen=app:haus__favoriten');
    expect(deeplink('seite:finance', undefined, OEFFENTLICH)).toBe('https://fyos.example/os/?offen=seite:finance');
    expect(deeplink('seite:finance', null, 'http://x.test')).toBe('http://x.test/os/?offen=seite:finance');
  });

  it('kodiert Sonderzeichen im Ziel und behält Kommas (mehrere Flächen)', () => {
    expect(deeplink('app:a b&c', undefined, 'http://x.test')).toBe('http://x.test/os/?offen=app:a%20b%26c');
    expect(deeplink('app:a,app:b', undefined, 'http://x.test')).toBe('http://x.test/os/?offen=app:a,app:b');
  });

  it('nimmt ohne Ursprung den der Seite (hier jsdom)', () => {
    expect(deeplink('seite:finance').startsWith(`${location.origin}/os/?offen=`)).toBe(true);
  });
});

describe('osZielAus — eine Adresse von fyos als Ziel im OS', () => {
  it('liest /os?offen=…&eingabe=… der öffentlichen Adresse auch auf einem anderen Ursprung (Entwicklung, LAN)', () => {
    const e = eingabeKodieren({ raum: 'Küche' });
    expect(osZielAus(`https://fyos.example/os?offen=app:haus__favoriten&eingabe=${e}`, HIER)).toEqual({
      ziel: 'app:haus__favoriten',
      eingabe: { raum: 'Küche' },
    });
    expect(osZielAus('http://127.0.0.1:4431/os/?offen=app:haus__favoriten', HIER)).toEqual({ ziel: 'app:haus__favoriten' });
    expect(osZielAus('/os/?offen=seite:finance', HIER)).toEqual({ ziel: 'seite:finance' });
  });

  it('nimmt bei mehreren Flächen die erste', () => {
    expect(osZielAus('/os/?offen=app:a__b,seite:finance', HIER)).toEqual({ ziel: 'app:a__b' });
  });

  it('ohne lesbares Ziel kein Ergebnis; eine kaputte Eingabe wird nur weggelassen', () => {
    expect(osZielAus('/os/', HIER)).toBeNull();
    expect(osZielAus('/os/?offen=', HIER)).toBeNull();
    expect(osZielAus('/os/?offen=app:haus__favoriten&eingabe=%%%', HIER)).toEqual({ ziel: 'app:haus__favoriten' });
  });

  it('fremde Ursprünge und fremde Schemata sind kein Ziel (dann öffnet der Aufrufer einen Tab)', () => {
    expect(osZielAus('https://example.com/os?offen=app:haus__favoriten', HIER)).toBeNull();
    expect(osZielAus('https://fyos.example.boese.example/os?offen=app:x', HIER)).toBeNull();
    expect(osZielAus('javascript:alert(1)', HIER)).toBeNull();
    expect(osZielAus('data:text/html,<script>1</script>', HIER)).toBeNull();
    expect(osZielAus('ftp://fyos.example/os?offen=app:x', HIER)).toBeNull();
    expect(osZielAus('', { origin: 'null', href: 'about:blank' })).toBeNull();
    expect(osZielAus('   ', HIER)).toBeNull(); // eine leere Adresse wäre „diese Seite"
  });

  it('liest den älteren Weg /apps/mcp?app=…&args=… (WebMCP fyos_zeigen)', () => {
    const args = encodeURIComponent(JSON.stringify({ laeufe: ['a'] }));
    expect(osZielAus(`/apps/mcp?app=fle__messungen&args=${args}`, HIER)).toEqual({ ziel: 'app:fle__messungen', eingabe: { laeufe: ['a'] } });
    expect(osZielAus('/apps/mcp/?app=fle__messungen', HIER)).toEqual({ ziel: 'app:fle__messungen' });
    expect(osZielAus('/apps/mcp?app=fle__messungen&args=kein-json', HIER)).toEqual({ ziel: 'app:fle__messungen' });
    expect(osZielAus('/apps/mcp', HIER)).toEqual({ ziel: '/apps/mcp' }); // ohne App: die Seite selbst
  });

  it('jede andere Seite von fyos ist ein Pfad (die Shell sucht dazu eine Fläche)', () => {
    expect(osZielAus('/finance/', HIER)).toEqual({ ziel: '/finance' });
    expect(osZielAus('https://fyos.example/agents/?tab=itsm', HIER)).toEqual({ ziel: '/agents?tab=itsm' });
    expect(osZielAus('/finance/#abschnitt', HIER)).toEqual({ ziel: '/finance' });
  });
});

describe('pfadSchluessel', () => {
  it('vergleicht Seiten ohne Schrägstrich am Ende und ohne #…, behält die Abfrage', () => {
    expect(pfadSchluessel('/finance/')).toBe('/finance');
    expect(pfadSchluessel('/finance')).toBe('/finance');
    expect(pfadSchluessel('/agents/?tab=itsm')).toBe('/agents?tab=itsm');
    expect(pfadSchluessel('/a/b/#x')).toBe('/a/b');
    expect(pfadSchluessel('/')).toBe('/');
  });
});

describe('imOsOeffnen — das Ereignis an die Shell', () => {
  it('liefert true, wenn die Shell es übernimmt (preventDefault), und reicht das Ziel unverändert durch', () => {
    const gesehen: OsZiel[] = [];
    const hoerer = (e: Event) => {
      gesehen.push((e as CustomEvent<OsZiel>).detail);
      e.preventDefault();
    };
    window.addEventListener(OEFFNEN, hoerer);
    try {
      expect(imOsOeffnen({ ziel: 'app:haus__favoriten', eingabe: { raum: 'Küche' } })).toBe(true);
      expect(gesehen).toEqual([{ ziel: 'app:haus__favoriten', eingabe: { raum: 'Küche' } }]);
    } finally {
      window.removeEventListener(OEFFNEN, hoerer);
    }
  });

  it('liefert false, wenn niemand zuhört (Seite läuft allein im Tab) oder die Shell das Ziel nicht kennt', () => {
    expect(imOsOeffnen({ ziel: 'app:haus__favoriten' })).toBe(false);
    const ablehner = vi.fn();
    window.addEventListener(OEFFNEN, ablehner); // hört, übernimmt aber nicht
    try {
      expect(imOsOeffnen({ ziel: 'seite:gibt-es-nicht' })).toBe(false);
      expect(ablehner).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(OEFFNEN, ablehner);
    }
  });

  it('versucht danach das Fenster darüber, wenn es denselben Ursprung hat (Seiten im OS laufen in einem iframe)', () => {
    const mach = (parent: unknown, origin: string) => {
      const w = new EventTarget() as EventTarget & Record<string, unknown>;
      Object.assign(w, { CustomEvent, parent, location: { origin } });
      return w;
    };
    const oben = mach(null, 'https://fyos.example');
    oben.parent = oben;
    const uebernommen = vi.fn((e: Event) => e.preventDefault());
    oben.addEventListener(OEFFNEN, uebernommen);
    const unten = mach(oben, 'https://fyos.example');
    expect(imOsOeffnen({ ziel: 'app:haus__favoriten' }, unten as unknown as Window)).toBe(true);
    expect(uebernommen).toHaveBeenCalledTimes(1);

    // anderer Ursprung (oder Zugriff verweigert): das Fenster darüber wird nicht angefasst
    const fremd = mach(oben, 'https://example.com');
    expect(imOsOeffnen({ ziel: 'app:haus__favoriten' }, fremd as unknown as Window)).toBe(false);
    expect(uebernommen).toHaveBeenCalledTimes(1);
    const gesperrt = mach(null, 'https://fyos.example');
    Object.defineProperty(gesperrt, 'parent', {
      get() {
        throw new DOMException('blocked', 'SecurityError');
      },
    });
    expect(imOsOeffnen({ ziel: 'app:haus__favoriten' }, gesperrt as unknown as Window)).toBe(false);
  });
});
