/**
 * „Den Agenten fragen“ (lib/os/agent-fragen.ts): das Ereignis `fyos:agent-fragen` und die Nachricht
 * `fyosAgentFragen` erreichen den Empfänger der Shell; ohne Shell öffnet sich der Chat mit dem Entwurf.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { agentName, konfigurationSetzen, konfigurationZuruecksetzen } from '~/lib/config';
import {
  FRAGEN_EREIGNIS, FRAGEN_NACHRICHT, agentFragen, agentFragenAnbinden, entwurfAdresse, mitKontext, type AgentFrage,
} from '~/lib/os/agent-fragen';

afterEach(() => konfigurationZuruecksetzen());

describe('mitKontext / entwurfAdresse', () => {
  it('hängt Titel, Werkzeug und Eingabe als knappen Kontext an', () => {
    const t = mitKontext('Was heißt das?', { titel: 'Szenen', app: 'haus__szenen', eingabe: { raum: 'Küche' } });
    expect(t).toContain('Was heißt das?');
    expect(t).toContain('Szenen');
    expect(t).toContain('haus__szenen');
    expect(t).toContain('Küche');
    expect(mitKontext('Nur Text')).toBe('Nur Text');
  });

  it('kürzt einen langen Kontext', () => {
    const t = mitKontext('Frage', { titel: 'x'.repeat(2000) });
    expect(t.length).toBeLessThan(600);
    expect(t.endsWith(' …]')).toBe(true);
  });

  it('die Adresse des Entwurfs liegt im Agentpfad aus der Konfiguration und bleibt unter dem Limit', () => {
    expect(entwurfAdresse({ text: 'Hallo' })).toBe('/agent/?draft=Hallo');
    konfigurationSetzen({ agent: { pfad: '/chat/' } });
    expect(entwurfAdresse({ text: 'Hallo' }).startsWith('/chat/?draft=')).toBe(true);
    const lang = entwurfAdresse({ text: 'ä'.repeat(5000) });
    expect(lang.length).toBeLessThan(5100);
  });
});

describe('Empfänger der Shell', () => {
  it('nimmt das Ereignis an, öffnet den Chat mit dem Entwurf und übernimmt es (preventDefault)', () => {
    const zeigen = vi.fn();
    const ab = agentFragenAnbinden({ zeigen });
    try {
      const ev = new CustomEvent(FRAGEN_EREIGNIS, { detail: { text: 'Was fällt auf?', kontext: { titel: 'Haus' } }, cancelable: true });
      window.dispatchEvent(ev);
      expect(ev.defaultPrevented).toBe(true);
      expect(zeigen).toHaveBeenCalledTimes(1);
      const adresse = zeigen.mock.calls[0]![0] as string;
      expect(adresse.startsWith('/agent/?draft=')).toBe(true);
      expect(decodeURIComponent(adresse.split('?draft=')[1]!)).toContain('Was fällt auf?');
      expect(decodeURIComponent(adresse.split('?draft=')[1]!)).toContain('Haus');
    } finally {
      ab();
    }
  });

  it('übergeht Unbrauchbares', () => {
    const zeigen = vi.fn();
    const ab = agentFragenAnbinden({ zeigen });
    try {
      for (const detail of [null, 'text', { text: '   ' }, { text: 5 }, [1]]) {
        const ev = new CustomEvent(FRAGEN_EREIGNIS, { detail, cancelable: true });
        window.dispatchEvent(ev);
        expect(ev.defaultPrevented).toBe(false);
      }
      expect(zeigen).not.toHaveBeenCalled();
    } finally {
      ab();
    }
  });

  it('nimmt die Nachricht eines Fensters mit gleichem Ursprung an, die anderer Ursprünge nicht', () => {
    const zeigen = vi.fn();
    const ab = agentFragenAnbinden({ zeigen });
    try {
      window.dispatchEvent(new MessageEvent('message', { origin: location.origin, data: { [FRAGEN_NACHRICHT]: { text: 'Aus dem Fenster' } } }));
      expect(zeigen).toHaveBeenCalledTimes(1);
      window.dispatchEvent(new MessageEvent('message', { origin: 'https://fremd.example', data: { [FRAGEN_NACHRICHT]: { text: 'Fremd' } } }));
      window.dispatchEvent(new MessageEvent('message', { origin: location.origin, data: { anderes: 1 } }));
      expect(zeigen).toHaveBeenCalledTimes(1);
    } finally {
      ab();
    }
  });

  it('nach dem Abmelden hört niemand mehr zu', () => {
    const zeigen = vi.fn();
    agentFragenAnbinden({ zeigen })();
    window.dispatchEvent(new CustomEvent(FRAGEN_EREIGNIS, { detail: { text: 'x' }, cancelable: true }));
    expect(zeigen).not.toHaveBeenCalled();
  });
});

describe('agentFragen', () => {
  const fenster = (extra: Record<string, unknown> = {}) => {
    const w = new EventTarget() as EventTarget & Record<string, unknown>;
    Object.assign(w, { CustomEvent, location: { origin: 'https://fyos.test' }, open: vi.fn(), ...extra });
    w.self = w;
    w.top ??= w;
    return w as unknown as Window & { open: ReturnType<typeof vi.fn> };
  };

  it('mit Shell im selben Fenster: Ereignis, kein neuer Tab', () => {
    const w = fenster();
    w.addEventListener(FRAGEN_EREIGNIS, (e) => e.preventDefault());
    agentFragen({ text: 'Frage' }, { fenster: w });
    expect(w.open).not.toHaveBeenCalled();
  });

  it('ohne Shell: der Chat mit dem Entwurf in einem neuen Tab', () => {
    const w = fenster();
    agentFragen({ text: 'Frage' }, { fenster: w });
    expect(w.open).toHaveBeenCalledWith('/agent/?draft=Frage', '_blank', 'noopener');
  });

  it('in einem Fenster der Shell (iframe): per postMessage an die Shell', () => {
    const eltern = fenster();
    const postMessage = vi.fn();
    (eltern as unknown as { postMessage: unknown }).postMessage = postMessage;
    const w = fenster({ parent: eltern, top: eltern });
    agentFragen({ text: 'Frage', kontext: { titel: 'Seite' } }, { fenster: w });
    expect(postMessage).toHaveBeenCalledWith({ [FRAGEN_NACHRICHT]: { text: 'Frage', kontext: { titel: 'Seite' } } }, 'https://fyos.test');
    expect(w.open).not.toHaveBeenCalled();
  });

  it('eine leere Frage tut nichts', () => {
    const w = fenster();
    agentFragen({ text: ' ' } as AgentFrage, { fenster: w });
    expect(w.open).not.toHaveBeenCalled();
  });

  it('der Agent heißt ohne Konfiguration „Agent“', () => {
    expect(agentName()).toBe('Agent');
  });
});
