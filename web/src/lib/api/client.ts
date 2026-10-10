/**
 * Werfender JSON-Abruf (`fetchJson`) und `ApiError`.
 *
 * Für `useQuery`-`queryFn`s: wirft `ApiError`, damit Query retryen und `error` setzen kann.
 * Wer den Fehler als Wert will, nimmt `hole()` (abruf.ts). Beide laufen über dieselbe
 * Strecke (transport.ts): Sitzungs-Erkennung, Zeitgrenze, HTML-statt-JSON.
 *
 * Auth: die Anmeldung übernimmt ein vorgeschalteter Proxy; Cookies gehen über `credentials: 'include'`.
 */
import { strecke } from './transport';

export { API_BASE } from './transport';

/** RFC 7807 Problem-Details. */
export interface ApiProblem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
}

/**
 * Fehler für nicht erfolgreiche Abrufe. `status` ist der HTTP-Status, oder:
 *   401  Sitzung abgelaufen (auch wenn Caddy mit 302 zur Anmeldung antwortete)
 *   0    Netz/keine Antwort, 408 Zeitgrenze, 499 abgebrochen, 502 Antwort war kein JSON
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly problem: ApiProblem | undefined,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get sitzungAbgelaufen(): boolean {
    return this.status === 401;
  }
}

/** JSON holen oder `ApiError` werfen. `init.zeitMs` setzt die Zeitgrenze (0 = keine). */
export async function fetchJson<T>(path: string, init?: RequestInit & { zeitMs?: number }): Promise<T> {
  const s = await strecke(path, init);
  switch (s.art) {
    case 'ok':
      return s.daten as T;
    case 'http': {
      const problem = s.koerper && typeof s.koerper === 'object' ? (s.koerper as ApiProblem) : undefined;
      throw new ApiError(s.status, problem, problem?.title ?? s.grund);
    }
    case 'sitzung':
      throw new ApiError(401, undefined, s.grund);
    case 'zeit':
      throw new ApiError(408, undefined, s.grund);
    case 'abgebrochen':
      throw new ApiError(499, undefined, s.grund);
    case 'kein_json':
      throw new ApiError(502, undefined, s.grund);
    case 'netz':
      throw new ApiError(0, undefined, `nicht erreichbar: ${s.grund}`);
  }
}
