/**
 * Apps-Seite: Adressen (lib/os/apps-seite.ts) und die Knöpfe Apps und Agent der Räume-Leiste (28.10.2026).
 */
import { cleanup, fireEvent, render, screen } from '@solidjs/testing-library';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RaeumeLeiste from '~/components/os/RaeumeLeiste';
import { APPS_PFAD, appsAdresse, istAppsPfad, osAdresse } from '~/lib/os/apps-seite';
import { standard } from '~/lib/os/raeume';
import { gutSetzen } from '~/lib/os/ziehen';

afterEach(() => cleanup());

describe('Adressen der Apps-Seite', () => {
  it('erkennt /os/apps mit und ohne Schrägstrich, sonst nichts', () => {
    expect(istAppsPfad('/os/apps')).toBe(true);
    expect(istAppsPfad('/os/apps/')).toBe(true);
    expect(istAppsPfad('/os/')).toBe(false);
    expect(istAppsPfad('/os/apps/x')).toBe(false);
    expect(istAppsPfad('/apps')).toBe(false); // alter Launcher, leitet nach /os/ um
  });

  it('behält die Abfrage, lässt aber einen Deeplink (offen, eingabe) weg', () => {
    expect(appsAdresse('')).toBe(APPS_PFAD);
    expect(appsAdresse('?raeume=0')).toBe('/os/apps/?raeume=0');
    expect(appsAdresse('?offen=seite:finance&eingabe=abc&raeume=1')).toBe('/os/apps/?raeume=1');
  });

  it('osAdresse führt zurück auf /os/', () => {
    expect(osAdresse('')).toBe('/os/');
    expect(osAdresse('?raeume=0')).toBe('/os/?raeume=0');
  });
});

describe('Räume-Leiste: Apps und Agent', () => {
  const z = () => ({ ...standard(), an: true });

  it('Apps ist ein Knopf, kein Raum, und meldet den Klick; offen trägt er die Markierung, der Raum nicht', () => {
    const onApps = vi.fn();
    const onRaum = vi.fn();
    render(() => <RaeumeLeiste zustand={z()} onRaum={onRaum} agentAn={false} onAgent={vi.fn()} appsOffen onApps={onApps} />);
    const apps = screen.getByRole('button', { name: 'Apps' });
    expect(apps.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Zentrale' }).getAttribute('aria-current')).toBeNull();
    fireEvent.click(apps);
    expect(onApps).toHaveBeenCalledOnce();
    expect(onRaum).not.toHaveBeenCalled();
  });

  it('der Agent nimmt gezogene Dinge an wie früher im Dock: Ablegen fragt Agent dazu', () => {
    const onAblegen = vi.fn();
    render(() => <RaeumeLeiste zustand={z()} onRaum={vi.fn()} agentAn={false} onAgent={vi.fn()} onAgentAblegen={onAblegen} />);
    const agent = screen.getByRole('button', { name: /Agent fragen/ });
    const daten = new Map<string, string>();
    const dt = {
      effectAllowed: 'all', dropEffect: 'none',
      get types() { return [...daten.keys()]; },
      setData: (t: string, v: string) => void daten.set(t.toLowerCase(), v),
      getData: (t: string) => daten.get(t.toLowerCase()) ?? '',
      setDragImage: () => {},
    } as unknown as DataTransfer;
    gutSetzen(dt, { art: 'flaeche', id: 'seite:finance' }, 'Finance');
    fireEvent.dragOver(agent, { dataTransfer: dt });
    fireEvent.drop(agent, { dataTransfer: dt });
    expect(onAblegen).toHaveBeenCalledWith({ art: 'flaeche', id: 'seite:finance' });
  });
});
