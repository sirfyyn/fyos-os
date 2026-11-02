/**
 * AmpelPunkt — die Lage-Ampel in der Menüleiste.
 *
 * Ein farbiger Punkt aus `lage.ampel` (gruen, blau, gelb, rot, dev/debug), der Grund steht im Tooltip und für
 * Bildschirmleser im Namen; ein Klick öffnet das Lagebild. Fragt jede Minute; ohne Antwort verschwindet der Punkt
 * (keine falsche Farbe), also auch ohne ein Plugin, das `lage.ampel` anbietet.
 */
import { Show, createResource, onCleanup, type JSX } from 'solid-js';
import { hub } from '~/lib/hub';
import { tr } from '~/lib/i18n';

export interface Ampel {
  zustand?: string;
  warum?: string[];
}

export const AMPEL_TEXT: Record<string, string> = {
  gruen: 'Alles in Ordnung',
  blau: 'Online, mit kleinen Problemen',
  gelb: 'Warnung',
  rot: 'Störung',
  dev: 'Entwicklungsfenster offen',
  debug: 'Fehlersuche läuft',
};

export function ampelSatz(a: Ampel | undefined): string {
  if (!a?.zustand) return '';
  const kopf = AMPEL_TEXT[a.zustand] ? tr(AMPEL_TEXT[a.zustand]!) : a.zustand;
  const warum = (a.warum ?? []).slice(0, 3).join(' · ');
  return warum ? `${kopf}: ${warum}` : kopf;
}

export default function AmpelPunkt(p: { oeffne: (ziel: string) => void }): JSX.Element {
  // Ohne solid-query: die Leiste steht auch dort, wo kein QueryClientProvider liegt (Shell-Tests, Fenster)
  const [ampel, { refetch }] = createResource(() => hub<Ampel>('lage.ampel').catch(() => undefined));
  const takt = setInterval(() => void refetch(), 60_000);
  onCleanup(() => clearInterval(takt));
  const daten = () => (ampel.state === 'ready' || ampel.state === 'refreshing' ? ampel() : undefined);
  return (
    <Show when={daten()?.zustand}>
      <button
        type="button"
        class="os-leiste-punkt os-ampel"
        data-ampel={daten()!.zustand}
        aria-label={tr('Lage: {0}', ampelSatz(daten()))}
        title={ampelSatz(daten())}
        onClick={() => p.oeffne('app:leitstand__lagebild')}
      >
        <span class="os-ampel-punkt" aria-hidden="true" />
      </button>
    </Show>
  );
}
