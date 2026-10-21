/**
 * Ton je Gerät: Modus speichern und melden, Kopfhörer erkennen.
 */
import { describe, expect, it, vi } from 'vitest';
import { kopfhoererAus, kopfhoererErkennen, TON_EREIGNIS, TON_SCHLUESSEL, tonModusLesen, tonModusSchreiben } from '~/lib/os/ton-modus';

const ausgang = (label: string, deviceId = 'default') => ({ kind: 'audiooutput' as MediaDeviceKind, deviceId, label });

describe('Ton-Modus', () => {
  it('liest nur gültige Modi, schreibt und sagt der Brücke Bescheid', () => {
    const speicher = new Map<string, string>();
    const s = { getItem: (k: string) => speicher.get(k) ?? null, setItem: (k: string, v: string) => void speicher.set(k, v) };
    expect(tonModusLesen(s)).toBeNull();
    speicher.set(TON_SCHLUESSEL, 'laut');
    expect(tonModusLesen(s)).toBeNull();
    const ziel = { dispatchEvent: vi.fn(() => true) };
    tonModusSchreiben('interaktiv', s, ziel);
    expect(tonModusLesen(s)).toBe('interaktiv');
    expect(ziel.dispatchEvent).toHaveBeenCalledOnce();
    expect((ziel.dispatchEvent.mock.calls[0] as unknown[])[0]).toMatchObject({ type: TON_EREIGNIS, detail: 'interaktiv' });
    expect(tonModusLesen(null)).toBeNull();
  });

  it('erkennt Kopfhörer am Standard-Ausgang, sonst unbekannt', async () => {
    expect(kopfhoererAus([ausgang('Standard - Headphones (Bluetooth)')])).toBe(true);
    expect(kopfhoererAus([ausgang('Standard - Built-in Speakers')])).toBe(false);
    expect(kopfhoererAus([ausgang('')])).toBeNull(); // ohne Mikrofon-Erlaubnis keine Namen
    expect(kopfhoererAus([])).toBeNull(); // Safari: keine Ausgabegeräte
    expect(kopfhoererAus([ausgang('External Display', 'abc'), ausgang('Wireless Headset', 'xyz')])).toBe(false);
    expect(await kopfhoererErkennen(null)).toBeNull();
    expect(await kopfhoererErkennen({ enumerateDevices: () => Promise.reject(new Error('nein')) })).toBeNull();
    expect(await kopfhoererErkennen({ enumerateDevices: async () => [ausgang('Default - Earbuds Pro') as MediaDeviceInfo] })).toBe(true);
  });
});
