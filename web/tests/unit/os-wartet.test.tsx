import { cleanup, fireEvent, render, screen, waitFor, within } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/hub', () => ({ hub: vi.fn() }));
vi.mock('~/lib/live', () => ({ hoereStand: () => () => {} }));

import { hub } from '~/lib/hub';
import {
  EREIGNIS,
  buendelIds,
  gruppiere,
  neueIds,
  seitText,
  wartetAnhaengen,
  wartetEingang,
  wartetLaden,
  wartetZahl,
  wartetZuruecksetzen,
  zahlText,
  type WartetEintrag,
} from '~/lib/os/wartet';
import { WartetSchublade, alsFreigabe } from '~/components/os/WartetSchublade';
import { knopfText } from '~/components/os/WartetKarte';

const e = (id: string, mehr: Partial<WartetEintrag> = {}): WartetEintrag => ({
  id,
  quelle: 'kalender',
  satz: `Satz ${id}?`,
  warum: 'Weil.',
  wirkung: 'Wirkt.',
  umkehrbar: true,
  zerstoererisch: false,
  buendelbar: true,
  seit: '2026-10-30T10:00:00Z',
  aktionen: ['ja', 'nein', 'spaeter', 'immer', 'oeffnen'],
  ziel: 'app:leitstand__braucht_dich',
  ...mehr,
});
const ZERSTOERT = e('itsm:PRB-1', {
  quelle: 'itsm', art: 'freigabe', umkehrbar: false, zerstoererisch: true, buendelbar: false, aktionen: ['ja', 'nein', 'spaeter', 'oeffnen'],
});
const RUNNER = e('runner:f-1', { quelle: 'runner', art: 'freigabe', risiko: 'low', kontext: 'Agent will pushen.', gespraech: 'Bau' });
const EINGANG = {
  zahl: 3, satz: '3 Sachen warten auf dich.', gruppen: { freigabe: 1, fragen: 2, buendelbar: 2 },
  eintraege: [RUNNER, ZERSTOERT, e('kalender:2')], zurueckgestellt: [], ausfall: {}, vollstaendig: true, stand: '',
};
const mockHub = vi.mocked(hub);

beforeEach(() => {
  wartetZuruecksetzen();
  mockHub.mockReset();
  mockHub.mockImplementation(async (tool: string) => (tool === 'wartet.eingang' ? structuredClone(EINGANG) : { ok: true, text: 'ok' }));
});
afterEach(cleanup);

describe('wartet.ts: reine Helfer', () => {
  it('gruppiert in nicht umkehrbar und umkehrbar', () => {
    const g = gruppiere(EINGANG.eintraege);
    expect(g.freigaben.map((x) => x.id)).toEqual(['itsm:PRB-1']);
    expect(g.fragen.map((x) => x.id)).toEqual(['runner:f-1', 'kalender:2']);
  });

  it('bündelt nie Zerstörerisches, auch wenn der Hub es falsch markierte', () => {
    const falsch = { ...ZERSTOERT, buendelbar: true };
    expect(buendelIds([...EINGANG.eintraege, falsch])).toEqual(['runner:f-1', 'kalender:2']);
  });

  it('Texte', () => {
    expect(zahlText(0)).toBe('Nichts wartet auf dich');
    expect(zahlText(1)).toBe('Eins wartet auf dich');
    const jetzt = Date.parse('2026-11-02T10:00:00Z');
    expect(seitText('2026-10-30T10:00:00Z', jetzt)).toBe('seit 3 Tagen');
    expect(seitText('2026-11-01T09:00:00Z', jetzt)).toBe('seit gestern');
    expect(seitText('2026-11-02T09:30:00Z', jetzt)).toBe('vor 30 Min.');
    expect(seitText(null, jetzt)).toBe('');
    expect(neueIds(null, EINGANG.eintraege)).toEqual([]);
    expect(neueIds([RUNNER], EINGANG.eintraege)).toEqual(['itsm:PRB-1', 'kalender:2']);
  });

  it('Knopftexte je Quelle', () => {
    expect(knopfText(e('kalender:1'), 'ja')).toBe('Eintragen');
    expect(knopfText(ZERSTOERT, 'ja')).toBe('Halten zum Erlauben');
    expect(knopfText(ZERSTOERT, 'nein')).toBe('Ablehnen');
    expect(knopfText(e('entscheidung:1', { quelle: 'entscheidung' }), 'immer')).toBe('Immer erlauben');
    expect(knopfText(e('wache:w1', { quelle: 'wache', art: 'hinweis' }), 'nein')).toBe('Erledigt');
  });

  it('Runner-Eintrag wird zur FreigabeKarte ohne Rohkennung im Text', () => {
    const f = alsFreigabe(RUNNER);
    expect(f.aktion).toBe('Satz runner:f-1?');
    expect(f.status).toBe('offen');
    expect(f.befehl).toBeUndefined();
  });
});

describe('wartet.ts: ein Abruf, eine Zahl', () => {
  it('teilt laufende Abrufe und meldet die Zahl am window', async () => {
    const gehoert = vi.fn();
    window.addEventListener(EREIGNIS, gehoert);
    await Promise.all([wartetLaden(), wartetLaden()]);
    expect(mockHub).toHaveBeenCalledTimes(1);
    expect(wartetZahl()).toBe(3);
    expect(gehoert.mock.calls[0][0].detail.zahl).toBe(3);
    window.removeEventListener(EREIGNIS, gehoert);
  });

  it('Beobachter teilen sich eine Schleife; Fehler lassen den letzten Stand stehen', async () => {
    const ab1 = wartetAnhaengen();
    const ab2 = wartetAnhaengen();
    await waitFor(() => expect(wartetZahl()).toBe(3));
    expect(mockHub.mock.calls.filter(([t]) => t === 'wartet.eingang')).toHaveLength(1);
    mockHub.mockRejectedValueOnce(new Error('weg'));
    await wartetLaden(true);
    expect(wartetZahl()).toBe(3);
    ab1();
    ab2();
  });
});

describe('WartetSchublade', () => {
  const zeigen = async () => {
    const oeffne = vi.fn();
    const schliessen = vi.fn();
    render(() => <WartetSchublade offen schliessen={schliessen} oeffne={oeffne} />);
    await waitFor(() => expect(wartetEingang()).not.toBeNull());
    return { oeffne, schliessen, d: screen.getByRole('dialog', { name: 'Wartet auf dich' }) };
  };

  it('zeigt Gruppen, Filter und den Bündel-Knopf', async () => {
    const { d } = await zeigen();
    expect(within(d).getByText('Freigabe · nicht umkehrbar')).toBeTruthy();
    expect(within(d).getByText('Fragen · umkehrbar')).toBeTruthy();
    expect(within(d).getByRole('button', { name: 'Alle 3' })).toBeTruthy();
    fireEvent.click(within(d).getByRole('button', { name: 'Freigaben 1' }));
    expect(within(d).queryByText('Fragen · umkehrbar')).toBeNull();
  });

  it('„Alle 2 umkehrbaren erlauben“ schickt nur die Bündelbaren', async () => {
    const { d } = await zeigen();
    fireEvent.click(within(d).getByRole('button', { name: 'Alle 2 umkehrbaren erlauben' }));
    await waitFor(() =>
      expect(mockHub).toHaveBeenCalledWith('wartet.antworten', { ids: ['runner:f-1', 'kalender:2'], aktion: 'ja' }, expect.anything()),
    );
  });

  it('Zerstörerisches löst ein Klick nicht aus', async () => {
    const { d } = await zeigen();
    const karte = d.querySelector('[data-wartet="itsm:PRB-1"]') as HTMLElement;
    fireEvent.click(within(karte).getByRole('button', { name: 'Halten zum Erlauben' }));
    expect(mockHub.mock.calls.some(([t]) => t === 'wartet.antworten')).toBe(false);
  });

  it('Eintragen beantwortet; Öffnen schließt und öffnet das Ziel ohne Hub-Aufruf', async () => {
    const { d, oeffne, schliessen } = await zeigen();
    const karte = () => d.querySelector('[data-wartet="kalender:2"]') as HTMLElement;
    fireEvent.click(within(karte()).getByRole('button', { name: 'Öffnen' }));
    await waitFor(() => expect(oeffne).toHaveBeenCalledWith('app:leitstand__braucht_dich'));
    expect(schliessen).toHaveBeenCalled();
    expect(mockHub.mock.calls.some(([t]) => t === 'wartet.antworten')).toBe(false);
    fireEvent.click(within(karte()).getByRole('button', { name: 'Eintragen' }));
    await waitFor(() =>
      expect(mockHub).toHaveBeenCalledWith('wartet.antworten', { id: 'kalender:2', aktion: 'ja' }, expect.anything()),
    );
  });

  it('Esc schließt', async () => {
    const { d, schliessen } = await zeigen();
    fireEvent.keyDown(d, { key: 'Escape' });
    expect(schliessen).toHaveBeenCalled();
  });
});
