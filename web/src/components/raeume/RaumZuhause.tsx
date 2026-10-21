/**
 * Raum Zuhause: die Geräte-App eines Haus-Plugins (haus.geraete) als Mitte des Raums. Die Leiste rechts (Räume je Stockwerk,
 * Ebenen, nicht platzierte Geräte) bringt die App selbst mit. Ohne ein solches Plugin steht „Noch nicht eingerichtet.“ da.
 */
import type { JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { HubApp } from '~/components/raeume/Huelle';

export default function RaumZuhause(p: RaumProps): JSX.Element {
  return (
    <RaumRahmen titel="Zuhause" schmal={p.schmal} heim={p.heim} fuellen>
      <div class="flex min-h-0 flex-1 flex-col" data-raum-zuhause>
        <HubApp name="haus__geraete" titel="Zuhause" ohneKopf fuellen schluessel="raum-zuhause" />
      </div>
    </RaumRahmen>
  );
}
