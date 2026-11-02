/**
 * Räume (lib/os/raeume.ts, components/os/RaeumeLeiste.tsx, components/einstellungen/RaeumeEinstellen.tsx):
 * Raumliste, Wechsel im Kreis, Ordnen, Speicher und die Leiste links.
 */
import { cleanup, fireEvent, render, screen } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RaeumeEinstellen from '~/components/einstellungen/RaeumeEinstellen';
import RaeumeLeiste from '~/components/os/RaeumeLeiste';
import { raumHatInhalt } from '~/components/os/Raum';
import { verfuegbarSetzen } from '~/lib/os/raeume-inhalt';
import { NichtEingerichtet } from '~/components/raeume/Huelle';
import {
  RAEUME,
  ausblendGrund,
  ausblenden,
  leereAusblenden,
  raumHatPlugin,
  einschalten,
  laden,
  leiste,
  ordnungZuruecksetzen,
  pruefen,
  raeume,
  raeumeSetzen,
  raeumeZuruecksetzen,
  schritt,
  standard,
  verschieben,
  wechseln,
  type RaeumeZustand,
} from '~/lib/os/raeume';

const an = (z: Partial<RaeumeZustand> = {}): RaeumeZustand => ({ ...standard(), an: true, ...z });
const ids = (z: RaeumeZustand) => leiste(z).map((r) => r.id);
/** Alle neun sind gebaut; die Regeln für Räume im Bau prüft ein Raum, der kurz wieder im Bau ist. */
const imBau = <T,>(id: string, fn: () => T): T => {
  const r = RAEUME.find((x) => x.id === id)! as { gebaut: boolean };
  r.gebaut = false;
  try {
    return fn();
  } finally {
    r.gebaut = true;
  }
};

beforeEach(() => {
  localStorage.clear();
  raeumeZuruecksetzen();
});
afterEach(() => cleanup());

describe('Raumliste', () => {
  it('kennt genau die neun Räume, Zentrale oben und Einstellungen unten fest', () => {
    expect(RAEUME.map((r) => r.id)).toEqual(['zentrale', 'gespraech', 'sammlung', 'atelier', 'vorhaben', 'buero', 'zuhause', 'betrieb', 'einstellungen']);
    expect(RAEUME.find((r) => r.fest === 'oben')?.id).toBe('zentrale');
    expect(RAEUME.find((r) => r.fest === 'unten')?.id).toBe('einstellungen');
  });

  it('zeigt in der Leiste nur gebaute Räume, und jeder gebaute Raum außer der Zentrale hat Inhalt', () => {
    expect(ids(an())).toEqual(['zentrale', 'gespraech', 'sammlung', 'atelier', 'vorhaben', 'buero', 'zuhause', 'betrieb', 'einstellungen']);
    expect(imBau('betrieb', () => ids(an()))).not.toContain('betrieb');
    for (const r of RAEUME.filter((x) => x.gebaut && x.id !== 'zentrale')) expect(raumHatInhalt(r.id)).toBe(true);
  });

  it('ist von selbst an und beginnt in der Zentrale', () => {
    expect(standard()).toMatchObject({ an: true, aktiv: 'zentrale' });
  });
});

describe('Wechseln', () => {
  it('wechselt nur zu gebauten Räumen', () => {
    expect(wechseln(an(), 'einstellungen').aktiv).toBe('einstellungen');
    const z = an();
    imBau('betrieb', () => expect(wechseln(z, 'betrieb')).toBe(z));
    expect(wechseln(z, 'gibtsnicht')).toBe(z);
  });

  it('geht im Kreis: nach den Einstellungen kommt die Zentrale, davor zurück', () => {
    expect(schritt(an({ aktiv: 'zentrale' }), 1).aktiv).toBe('gespraech');
    expect(schritt(an({ aktiv: 'gespraech' }), 1).aktiv).toBe('sammlung');
    expect(schritt(an({ aktiv: 'sammlung' }), 1).aktiv).toBe('atelier');
    expect(schritt(an({ aktiv: 'atelier' }), 1).aktiv).toBe('vorhaben');
    expect(schritt(an({ aktiv: 'vorhaben' }), 1).aktiv).toBe('buero');
    expect(schritt(an({ aktiv: 'buero' }), 1).aktiv).toBe('zuhause');
    expect(schritt(an({ aktiv: 'zuhause' }), 1).aktiv).toBe('betrieb');
    expect(schritt(an({ aktiv: 'betrieb' }), 1).aktiv).toBe('einstellungen');
    expect(schritt(an({ aktiv: 'einstellungen' }), 1).aktiv).toBe('zentrale');
    expect(schritt(an({ aktiv: 'zentrale' }), -1).aktiv).toBe('einstellungen');
  });

  it('ausschalten führt zurück in die Zentrale', () => {
    expect(einschalten(an({ aktiv: 'zuhause' }), false)).toMatchObject({ an: false, aktiv: 'zentrale' });
  });
});

describe('Ordnen', () => {
  it('tauscht mit dem nächsten gebauten Nachbarn und lässt die festen Plätze in Ruhe', () => {
    const z = an({ reihenfolge: ['zuhause', 'betrieb', 'sammlung', 'gespraech', 'atelier', 'vorhaben', 'buero'] });
    // Nach unten tauscht Zuhause mit der Sammlung (Betrieb ist im Bau und wird übersprungen), nach oben gibt es keinen Nachbarn
    imBau('betrieb', () => {
      expect(ids(verschieben(z, 'zuhause', 1))).toEqual(['zentrale', 'sammlung', 'zuhause', 'gespraech', 'atelier', 'vorhaben', 'buero', 'einstellungen']);
      expect(verschieben(z, 'zuhause', -1)).toBe(z);
      expect(ids(z)).toEqual(['zentrale', 'zuhause', 'sammlung', 'gespraech', 'atelier', 'vorhaben', 'buero', 'einstellungen']);
    });
    expect(ids(verschieben(z, 'zuhause', 1)).slice(0, 3)).toEqual(['zentrale', 'betrieb', 'zuhause']);
  });

  it('Grundordnung stellt die Reihenfolge wieder her', () => {
    const z = an({ reihenfolge: ['betrieb', 'buero', 'vorhaben', 'atelier', 'sammlung', 'gespraech', 'zuhause'] });
    expect(ordnungZuruecksetzen(z).reihenfolge).toEqual(standard().reihenfolge);
  });
});

describe('Speicher', () => {
  it('prüft fremde Stände: Unbekanntes fliegt, Fehlendes kommt hinten dazu, nicht gebaute Räume sind nie vorn', () => {
    const z = imBau('betrieb', () => pruefen({ an: true, aktiv: 'betrieb', reihenfolge: ['zuhause', 'zuhause', 'quatsch', 'zentrale'] }));
    expect(z.aktiv).toBe('zentrale');
    expect(z.reihenfolge[0]).toBe('zuhause');
    expect(new Set(z.reihenfolge).size).toBe(7);
    expect(z.reihenfolge).not.toContain('zentrale');
    expect(pruefen('kaputt')).toEqual(standard());
  });

  it('merkt sich den Zustand im Browser und lädt ihn wieder', () => {
    raeumeSetzen(an({ aktiv: 'zuhause' }));
    raeumeZuruecksetzen();
    expect(raeume()).toMatchObject({ an: true, aktiv: 'zuhause' });
  });

  it('aus v1 kommt nur die eigene Ordnung mit, ein ausdrückliches Aus in v2 bleibt aus', () => {
    localStorage.setItem('fyos:os:raeume:v1', JSON.stringify({ an: false, aktiv: 'zentrale', reihenfolge: ['zuhause', 'sammlung'] }));
    const z = laden();
    expect(z.an).toBe(true);
    expect(z.reihenfolge.slice(0, 2)).toEqual(['zuhause', 'sammlung']);
    localStorage.setItem('fyos:os:raeume:v2', JSON.stringify({ an: false }));
    expect(laden().an).toBe(false);
  });

  it('?raeume=1 schaltet ein, ?raeume=0 aus', () => {
    const vorher = location.href;
    history.replaceState(null, '', '/os?raeume=1');
    expect(laden().an).toBe(true);
    history.replaceState(null, '', '/os?raeume=0');
    expect(laden().an).toBe(false);
    history.replaceState(null, '', vorher);
  });
});

describe('Räume-Leiste', () => {
  it('zeigt Zentrale, Zuhause, den Agenten und Einstellungen; der Raum vorn ist markiert', () => {
    const onRaum = vi.fn();
    const onAgent = vi.fn();
    render(() => <RaeumeLeiste zustand={an({ aktiv: 'zuhause' })} onRaum={onRaum} agentAn={false} onAgent={onAgent} />);
    const nav = screen.getByRole('navigation', { name: 'Räume' });
    expect(nav).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Zuhause' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('button', { name: 'Zentrale' }).getAttribute('aria-current')).toBeNull();
    expect(screen.getByRole('button', { name: 'Betrieb' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Einstellungen' }));
    expect(onRaum).toHaveBeenCalledWith('einstellungen');
    fireEvent.click(screen.getByRole('button', { name: /Agent fragen/ }));
    expect(onAgent).toHaveBeenCalledOnce();
  });

  it('der Knopf des Agenten zeigt, ob das Dock offen ist', () => {
    render(() => <RaeumeLeiste zustand={an()} onRaum={vi.fn()} agentAn={true} onAgent={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Agent fragen/ }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('Räume einstellen', () => {
  it('nennt Räume im Bau, solange es welche gibt', () => {
    imBau('betrieb', () => {
      render(() => <RaeumeEinstellen />);
      expect(screen.getByText('Noch im Bau')).toBeTruthy();
      expect(screen.getByText('Betrieb')).toBeTruthy();
    });
  });

  it('der Schalter schaltet die Räume ein und aus; sind alle gebaut, fehlt „Noch im Bau“', () => {
    render(() => <RaeumeEinstellen />);
    const schalter = screen.getByRole('switch', { name: /^Räume/ });
    expect(schalter.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(schalter);
    expect(raeume().an).toBe(false);
    expect(screen.getByRole('switch', { name: /^Räume/ }).getAttribute('aria-checked')).toBe('false');
    expect(screen.queryByText('Noch im Bau')).toBeNull();
  });
});

describe('Räume ausblenden', () => {
  const nurOeffentlich = ['vorgaenge__zeigen', 'werkstatt__suchen', 'mcp__uebersicht', 'termine__zeigen', 'posteingang__zeigen', 'desktop__zeigen'];

  it('ohne Wissen über den Hub bleiben alle Räume in der Leiste', () => {
    expect(ids(an())).toEqual(['zentrale', 'gespraech', 'sammlung', 'atelier', 'vorhaben', 'buero', 'zuhause', 'betrieb', 'einstellungen']);
    expect(leiste(an(), null).length).toBe(9);
    expect(raumHatPlugin('zuhause', null)).toBe(true);
  });

  it('blendet Räume ohne Plugin von selbst aus, Zentrale, Gespräch, Sammlung und Einstellungen nie', () => {
    const verf = new Set(nurOeffentlich);
    expect(leiste(an(), verf).map((r) => r.id)).toEqual(['zentrale', 'gespraech', 'sammlung', 'vorhaben', 'buero', 'betrieb', 'einstellungen']);
    expect(ausblendGrund(an(), 'zuhause', verf)).toBe('leer');
    expect(ausblendGrund(an(), 'atelier', verf)).toBe('leer');
    expect(ausblendGrund(an(), 'buero', verf)).toBeNull();
    for (const fest of ['zentrale', 'gespraech', 'sammlung', 'einstellungen'] as const) expect(ausblendGrund(an(), fest, new Set())).toBeNull();
  });

  it('ein Plugin holt den Raum zurück, auch eine registrierte Seite', () => {
    expect(leiste(an(), new Set([...nurOeffentlich, 'haus__geraete'])).map((r) => r.id)).toContain('zuhause');
    expect(raumHatPlugin('buero', new Set(['seite:finanzen']))).toBe(true);
    expect(raumHatPlugin('atelier', new Set(['medien__bild']))).toBe(true);
  });

  it('„Leere Räume ausblenden“ aus: alle Räume bleiben, auch ohne Plugin', () => {
    const z = leereAusblenden(an(), false);
    expect(z.leereAus).toBe(false);
    expect(leiste(z, new Set()).length).toBe(9);
    expect(leereAusblenden(z, false)).toBe(z);
  });

  it('von Hand ausblenden und einblenden; ist der Raum vorn, geht es in die Zentrale', () => {
    const z = ausblenden(an({ aktiv: 'betrieb' }), 'betrieb', true);
    expect(z.ausgeblendet).toEqual(['betrieb']);
    expect(z.aktiv).toBe('zentrale');
    expect(ids(z)).not.toContain('betrieb');
    expect(ausblendGrund(z, 'betrieb', new Set(['vorgaenge__zeigen']))).toBe('hand');
    expect(ausblenden(z, 'betrieb', true)).toBe(z);
    expect(ids(ausblenden(z, 'betrieb', false))).toContain('betrieb');
  });

  it('feste Plätze lassen sich nicht ausblenden', () => {
    const z = an();
    expect(ausblenden(z, 'zentrale', true)).toBe(z);
    expect(ausblenden(z, 'einstellungen', true)).toBe(z);
  });

  it('das Kreisen über die Räume überspringt ausgeblendete', () => {
    const verf = new Set(nurOeffentlich);
    expect(schritt(an({ aktiv: 'sammlung' }), 1, verf).aktiv).toBe('vorhaben');
    expect(schritt(ausblenden(an({ aktiv: 'sammlung' }), 'vorhaben', true), 1, verf).aktiv).toBe('buero');
  });

  it('prüft Fremdstände: Unbekanntes und feste Plätze fliegen aus „ausgeblendet“, ohne Angabe ist leereAus an', () => {
    const z = pruefen({ ausgeblendet: ['zuhause', 'zuhause', 'zentrale', 'quatsch', 'einstellungen'] });
    expect(z.ausgeblendet).toEqual(['zuhause']);
    expect(z.leereAus).toBe(true);
    expect(pruefen({ leereAus: false }).leereAus).toBe(false);
  });

  it('die Leiste folgt dem Hub, die Einstellungen zeigen den Grund und schalten', () => {
    verfuegbarSetzen(nurOeffentlich);
    render(() => <RaeumeEinstellen />);
    expect(document.querySelector('[data-raum-zeile="zuhause"] [data-raum-grund="leer"]')).toBeTruthy();
    expect(document.querySelector('[data-raum-zeile="betrieb"] [data-raum-grund]')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Betrieb ausblenden' }));
    expect(raeume().ausgeblendet).toEqual(['betrieb']);
    expect(document.querySelector('[data-raum-zeile="betrieb"] [data-raum-grund="hand"]')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Betrieb einblenden' }));
    expect(raeume().ausgeblendet).toEqual([]);
    fireEvent.click(screen.getByRole('switch', { name: /Leere Räume ausblenden/ }));
    expect(raeume().leereAus).toBe(false);
    expect(document.querySelector('[data-raum-zeile="zuhause"] [data-raum-grund]')).toBeNull();
    verfuegbarSetzen(null);
  });

  it('die Räume-Leiste zeigt nur Räume mit Plugin, sobald der Hub bekannt ist', () => {
    render(() => <RaeumeLeiste zustand={an()} verfuegbar={new Set(nurOeffentlich)} onRaum={vi.fn()} agentAn={false} onAgent={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Zuhause' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Atelier' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Betrieb' })).toBeTruthy();
  });
});

describe('Hinweis bei fehlendem Plugin', () => {
  it('nennt neben dem Satz den Weg: Plugin-Vorlage und die Anleitung ERWEITERN.md', () => {
    render(() => <NichtEingerichtet detail="Im Hub fehlt das Werkzeug haus__geraete." />);
    expect(screen.getByText('Noch nicht eingerichtet.')).toBeTruthy();
    const weg = document.querySelector('[data-nicht-eingerichtet-weg]')!;
    expect(weg.textContent).toContain('Plugin');
    const links = [...weg.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(links).toEqual(['https://pypi.org/project/fyos-plugin-vorlage/']);
    expect(weg.querySelector('code')!.textContent).toBe('docs/ERWEITERN.md');
  });
});
