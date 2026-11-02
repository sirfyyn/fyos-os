/**
 * api.ts — die Wege des Runners als Funktionen. Nichts hier ist erfunden: jeder Weg steht in
 * im Client-Protokoll und in runner/src/server.js des Runners (fyos-agent).
 */
import type { AgentVerbindung } from './verbindung';
import type { Eintrag, Freigabe, GeteilterZustand, Gespraech, GespraechId, Lauf, Verbrauch } from './typen';

export type SendeArt = 'folgen' | 'steuern' | 'abweisen';

export interface Gesundheit {
  ok: boolean;
  agent?: string;
  geraet?: { id?: string; name?: string; kind?: string };
  knoten?: unknown[];
  gespraeche?: number;
  hub?: string;
  /** Name der Spielmodus-Marke, solange der Runner pausiert; sonst `null`. */
  spielmodus?: string | null;
  zeit?: number;
  [rest: string]: unknown;
}

export interface Ansicht {
  id: GespraechId;
  meta?: Record<string, unknown> | null;
  entries?: Eintrag[];
  messages?: number;
  usage?: Verbrauch | null;
}

export class AgentApi {
  constructor(private readonly v: AgentVerbindung) {}

  health(signal?: AbortSignal): Promise<Gesundheit> {
    return this.v.anfrage<Gesundheit>('api/health', { signal });
  }

  async gespraeche(): Promise<Gespraech[]> {
    const d = await this.v.anfrage<{ gespraeche?: Gespraech[] }>('api/gespraeche');
    return Array.isArray(d.gespraeche) ? d.gespraeche : [];
  }

  async neuesGespraech(titel?: string): Promise<Gespraech> {
    const d = await this.v.anfrage<{ gespraech: Gespraech }>('api/gespraeche', { methode: 'POST', koerper: titel ? { titel } : {} });
    return d.gespraech;
  }

  ansicht(id: GespraechId, signal?: AbortSignal): Promise<Ansicht> {
    return this.v.anfrage<Ansicht>(`api/gespraech/${encodeURIComponent(String(id))}/ansicht`, { signal });
  }

  /** `folgen` wartet auf das Ende des laufenden Zugs, `steuern` greift hinein. */
  sende(id: GespraechId, text: string, art: SendeArt, requestId: string): Promise<{ id?: unknown; art?: string }> {
    return this.v.anfrage(`api/gespraech/${encodeURIComponent(String(id))}/nachricht`, { methode: 'POST', koerper: { text, art, requestId } });
  }

  abbrechen(id: GespraechId): Promise<unknown> {
    return this.v.anfrage(`api/gespraech/${encodeURIComponent(String(id))}/abbrechen`, { methode: 'POST', koerper: {} });
  }

  async freigaben(): Promise<Freigabe[]> {
    const d = await this.v.anfrage<{ freigaben?: Freigabe[] }>('api/freigaben');
    return Array.isArray(d.freigaben) ? d.freigaben : [];
  }

  /** Antwort ist die neue Liste. Schon entschieden: 400. */
  async entscheideFreigabe(id: string, entscheidung: 'erteilt' | 'abgelehnt', notiz?: string): Promise<Freigabe[]> {
    const d = await this.v.anfrage<{ freigaben?: Freigabe[] }>(`api/freigaben/${encodeURIComponent(id)}`, {
      methode: 'POST',
      koerper: { entscheidung, ...(notiz ? { notiz } : {}), von: 'mensch' },
    });
    return Array.isArray(d.freigaben) ? d.freigaben : [];
  }

  async laeufe(): Promise<Lauf[]> {
    const d = await this.v.anfrage<{ laeufe?: Lauf[] }>('api/laeufe');
    return Array.isArray(d.laeufe) ? d.laeufe : [];
  }

  async neuerLauf(vonGespraech: GespraechId, lauf: { titel: string; auftrag: string; freigabe?: boolean }): Promise<Lauf> {
    const d = await this.v.anfrage<{ lauf: Lauf }>(`api/gespraech/${encodeURIComponent(String(vonGespraech))}/laeufe`, {
      methode: 'POST',
      koerper: lauf,
    });
    return d.lauf;
  }

  laufAbbrechen(id: string): Promise<unknown> {
    return this.v.anfrage(`api/laeufe/${encodeURIComponent(id)}/abbrechen`, { methode: 'POST', koerper: {} });
  }

  async zustand(): Promise<GeteilterZustand> {
    const d = await this.v.anfrage<{ zustand?: GeteilterZustand }>('api/zustand');
    return d.zustand ?? { werte: {} };
  }

  zustandSetzen(schluessel: string, wert: unknown): Promise<unknown> {
    return this.v.anfrage(`api/zustand/${encodeURIComponent(schluessel)}`, { methode: 'PUT', koerper: { wert } });
  }

  zustandLoeschen(schluessel: string): Promise<unknown> {
    return this.v.anfrage(`api/zustand/${encodeURIComponent(schluessel)}`, { methode: 'DELETE' });
  }

  // SSE
  gespraechsStrom(id: GespraechId, signal: AbortSignal): Promise<Response> {
    return this.v.oeffneStrom(`api/gespraech/${encodeURIComponent(String(id))}/ereignisse`, signal);
  }
  wirkenStrom(signal: AbortSignal): Promise<Response> {
    return this.v.oeffneStrom('api/strom', signal);
  }
  dokumenteStrom(signal: AbortSignal): Promise<Response> {
    return this.v.oeffneStrom('api/dokumente', signal);
  }
}
