/**
 * Raum Vorhaben: das Vorhaben-Brett (Hub-App vorhaben.brett) als Mitte des Raums. Spalten Idee, entschieden, in Arbeit,
 * „gebaut, nicht live geprüft“ und „live gesehen“ (nur mit Beleg). Die Leiste bringt die App selbst mit, darum hat der Raum
 * keine zweite. Liefert kein Plugin das Brett, zeigt der Raum die Vorgänge des Hubs (vorgaenge.zeigen); gibt es auch die
 * nicht, steht „Noch nicht eingerichtet.“ da.
 */
import type { JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { HubApp } from '~/components/raeume/Huelle';
import { tr } from '~/lib/i18n';

export default function RaumVorhaben(p: RaumProps): JSX.Element {
  return (
    <RaumRahmen titel={tr('Vorhaben')} schmal={p.schmal} heim={p.heim} fuellen>
      <div class="flex min-h-0 flex-1 flex-col" data-raum-vorhaben>
        <HubApp name="vorhaben__brett" oder="vorgaenge__zeigen" titel={tr('Vorhaben')} ohneKopf fuellen schluessel="raum-vorhaben" />
      </div>
    </RaumRahmen>
  );
}
