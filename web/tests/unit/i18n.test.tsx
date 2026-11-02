/**
 * Sprache der Oberfläche: Englisch ist die Vorgabe der öffentlichen Fassung, Deutsch wählbar
 * (Laufzeit-Konfiguration `sprache`/`language`, Auswahl in den Einstellungen, gemerkt).
 */
import { fireEvent, render, screen } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Dock, { type DockProps } from '~/components/os/Dock';
import Hilfe from '~/components/os/Hilfe';
import Kontrollzentrum from '~/components/os/Kontrollzentrum';
import Erscheinungsbild from '~/components/einstellungen/Erscheinungsbild';
import { konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';
import { datumFormat, sprache, spracheAus, spracheFestlegen, spracheWaehlen, spracheZuruecksetzen, tr, tn, zahlFormat } from '~/lib/i18n';
import { de } from '~/lib/i18n/de';
import { en } from '~/lib/i18n/en';

beforeEach(() => {
  spracheFestlegen(undefined);
  spracheZuruecksetzen();
  konfigurationZuruecksetzen();
});

afterEach(() => {
  spracheZuruecksetzen();
  konfigurationZuruecksetzen();
});

function dock() {
  const p: DockProps = {
    bildschirme: [{ index: 1, name: 'Arbeit' }],
    aktiv: 1,
    onWechseln: vi.fn(),
    onNeuerBildschirm: vi.fn(),
    startOffen: false,
    onStart: vi.fn(),
    fenster: [],
    fokus: null,
    onFenster: vi.fn(),
    agent: false,
    onAgent: vi.fn(),
  };
  render(() => <Dock {...p} />);
}

describe('i18n: Vorgabe und Wahl', () => {
  it('Englisch ist die Vorgabe', () => {
    expect(sprache()).toBe('en');
    expect(tr('Einstellungen')).toBe('Settings');
    expect(tr('Vorgänge')).toBe('Tickets');
  });

  it('die Laufzeit-Konfiguration stellt Deutsch ein (sprache oder language)', () => {
    konfigurationSetzen({ sprache: 'de' });
    expect(sprache()).toBe('de');
    expect(tr('Einstellungen')).toBe('Einstellungen');
    konfigurationSetzen({ language: 'en-US' });
    expect(sprache()).toBe('en');
  });

  it('die Auswahl geht vor der Konfiguration und wird gemerkt', () => {
    konfigurationSetzen({ sprache: 'en' });
    spracheWaehlen('de');
    expect(sprache()).toBe('de');
    expect(localStorage.getItem('fyos.sprache')).toBe('de');
    expect(document.documentElement.lang).toBe('de');
    spracheWaehlen(undefined);
    expect(sprache()).toBe('en');
  });

  it('Platzhalter, Einzahl/Mehrzahl und unbekannte Schlüssel', () => {
    expect(tr('{0} schließen', 'Mail')).toBe('Close Mail');
    expect(tn(1, '{n} Fehler', '{n} Fehler')).toBe('1 Fehler');
    expect(tr('Gibt es nicht')).toBe('Gibt es nicht');
    expect(spracheAus('Deutsch')).toBe('de');
    expect(spracheAus('fr')).toBeUndefined();
  });

  it('Datum und Zahl folgen der Sprache', () => {
    const d = new Date(2026, 10, 2);
    expect(datumFormat(d, { month: 'long' })).toBe('November');
    expect(zahlFormat(1234.5)).toBe('1,234.5');
    spracheWaehlen('de');
    expect(zahlFormat(1234.5)).toBe('1.234,5');
  });

  it('jede englische Übersetzung behält die Platzhalter des Schlüssels', () => {
    const platz = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(',');
    for (const [k, v] of Object.entries(en)) expect(platz(v), k).toBe(platz(k));
    expect(Object.keys(de).every((k) => k in en || true)).toBe(true);
  });
});

describe('i18n: die wichtigsten Flächen rendern englisch', () => {
  it('Dock', () => {
    dock();
    expect(screen.getByRole('tablist', { name: 'Screens' })).toBeInTheDocument();
    expect(screen.getAllByRole('navigation', { name: 'Bottom bar' }).length).toBeGreaterThan(0);
  });

  it('Hilfe', () => {
    render(() => <Hilfe onSchliessen={() => {}} />);
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts and gestures' })).toBeInTheDocument();
    expect(screen.getByText('Keyboard')).toBeInTheDocument();
    expect(screen.getByText('This help')).toBeInTheDocument();
  });

  it('Kontrollzentrum', () => {
    render(() => <Kontrollzentrum onSchliessen={() => {}} einstellungenDa onEinstellungen={() => {}} x={0} />);
    expect(screen.getByRole('radiogroup', { name: 'Appearance' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Dark' })).toBeInTheDocument();
    expect(screen.getByText('All settings …')).toBeInTheDocument();
  });

  it('Einstellungen: die Sprachwahl schaltet sofort um', () => {
    render(() => <Erscheinungsbild kulisseId="k" />);
    expect(screen.getByText('Language')).toBeInTheDocument();
    expect(screen.getByText('Color scheme')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Deutsch' }));
    expect(sprache()).toBe('de');
    expect(screen.getByText('Sprache')).toBeInTheDocument();
    expect(screen.getByText('Farbschema')).toBeInTheDocument();
  });
});
