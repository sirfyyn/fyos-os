/**
 * hub.ts — ein Hub-Werkzeug aus einer Pane rufen.
 *
 * Leitbild „eine Fähigkeit, alle Flächen": Was eine Pane zeigt oder tut, ist ein Werkzeug im
 * MCP-Hub — dasselbe, das Agenten, MCP-Apps und WebMCP nutzen. Der Browser erreicht nur
 * Flächen-Werkzeuge (Oberfläche oder Tag `flaeche`) über /hub-api/app-call.
 *
 *     const ampel = useQuery(() => ({ queryKey: ['lage', 'ampel'], queryFn: () => hub<Ampel>('lage.ampel') }));
 *
 * Läuft über die gemeinsame Strecke (transport.ts): Sitzung, Zeitgrenze, Fehler als ApiError.
 *
 * Art des Aufrufs: jeder Aufruf trägt `X-Hub-Art` — `abfrage` (Vorgabe: Kachel,
 * Auffrischung, Polling) oder `bewusst` (Klick, Eingabe, Schreiben). Der Hub zählt beides getrennt; so sieht
 * man, welche Werkzeuge jemand gezielt nutzt und welche sich nur selbst auffrischen. Wer auf eine Eingabe
 * hin ruft, übergibt `{ art: 'bewusst' }`.
 */
import { ApiError, fetchJson } from './api/client';

export type HubArt = 'bewusst' | 'abfrage';

export async function hub<T = unknown>(tool: string, args: Record<string, unknown> = {}, opt: { zeitMs?: number; art?: HubArt } = {}): Promise<T> {
  const d = await fetchJson<{ ok: boolean; result?: unknown; error?: string; kind?: string }>('/hub-api/app-call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Hub-Art': opt.art ?? 'abfrage' },
    body: JSON.stringify({ tool, arguments: args }),
    zeitMs: opt.zeitMs,
  }).catch((e: unknown) => {
    // Hub-Antwort im Körper: der Hub hat geantwortet, das Werkzeug ist gescheitert. Status nach Art:
    // 400 Eingabe, 403 verboten/fremde Herkunft, 404 unbekannt, 503 Plugin gesperrt, 504 Zeitlimit, 502 sonst.
    if (e instanceof ApiError && e.problem && typeof (e.problem as unknown as { error?: string }).error === 'string') {
      throw new ApiError(e.status, e.problem, (e.problem as unknown as { error: string }).error);
    }
    throw e;
  });
  if (!d.ok) throw new ApiError(502, undefined, d.error ?? `${tool} fehlgeschlagen`);
  return d.result as T;
}

/**
 * Wie `hub()`, aber mit der Rückgabeform von `hole()` (daten / leer / nicht_erreichbar) —
 * für Komponenten, die schon auf `Abruf<T>` gebaut sind. Eine Zeile Umbau je Aufrufstelle.
 */
export async function holeHub<T>(tool: string, args: Record<string, unknown> = {}, opt: { zeitMs?: number; art?: HubArt } = {}): Promise<import('./api/abruf').Abruf<T>> {
  try {
    const d = await hub<T>(tool, args, opt);
    const leer = d === null || d === undefined || (Array.isArray(d) && d.length === 0);
    return leer ? { zustand: 'leer' } : { zustand: 'daten', daten: d };
  } catch (e) {
    const status = e instanceof ApiError ? e.status : undefined;
    return {
      zustand: 'nicht_erreichbar',
      grund: e instanceof Error ? e.message : String(e),
      status,
      sitzung: status === 401,
    };
  }
}
