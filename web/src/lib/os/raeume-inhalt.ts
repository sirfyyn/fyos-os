/**
 * Was der Hub gerade für die Räume liefert: die Namen seiner Flächen-Werkzeuge (`<plugin>__<werkzeug>`) und die
 * Seiten, die Plugins registriert haben. Daraus entscheidet `lib/os/raeume.ts` (RAUM_BRAUCHT), welche Räume etwas zu
 * zeigen haben. Solange der Hub nicht geantwortet hat (oder gar nicht antwortet), ist die Lage unbekannt (`null`) und
 * die Leiste zeigt alle Räume.
 */
import { createSignal } from 'solid-js';
import { werkzeugeImHub } from '~/lib/mcp-apps/host';
import { registrierteFlaechen } from '~/lib/os/register';
import type { Verfuegbar } from '~/lib/os/raeume';

const [hubNamen, setHubNamen] = createSignal<ReadonlySet<string> | null>(null);

/** Der Hub und die registrierten Seiten zusammen; `null`, solange der Hub nicht gelesen ist. */
export function verfuegbar(): Verfuegbar {
  const namen = hubNamen();
  if (!namen) return null;
  return new Set([...namen, ...registrierteFlaechen().map((f) => f.id)]);
}

/** Den Hub neu lesen (beim Start der Shell). Fehler lassen die Lage unbekannt, es wird nichts versteckt. */
export async function inhaltPruefen(): Promise<void> {
  try {
    const liste = await werkzeugeImHub();
    setHubNamen(new Set(liste.map((a) => a.name)));
  } catch {
    setHubNamen(null);
  }
}

/** Nur für Tests: Lage setzen oder auf unbekannt zurück. */
export function verfuegbarSetzen(namen: Iterable<string> | null): void {
  setHubNamen(namen ? new Set(namen) : null);
}
