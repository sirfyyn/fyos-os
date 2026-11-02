/**
 * Einstellungen — die native Fläche `nativ:einstellungen`: Erscheinungsbild und der Schalter für die Räume. Mit Räumen
 * öffnet ⌘, den Raum Einstellungen (components/raeume/RaumEinstellungen.tsx), der alle Bereiche trägt.
 */
import type { JSX } from 'solid-js';
import type { NativProps } from '~/lib/os/nativ';
import { Abschnitt } from './bausteine';
import Erscheinungsbild from './Erscheinungsbild';
import MeldungenEinstellen from './MeldungenEinstellen';
import RaeumeEinstellen from './RaeumeEinstellen';
import { tr } from '~/lib/i18n';

export default function Einstellungen(_p: NativProps): JSX.Element {
  return (
    <div class="@container" data-einstellungen>
      <div class="mx-auto w-full max-w-3xl space-y-5 px-4 py-5 @2xl:px-8">
        <Abschnitt id="erscheinungsbild" titel={tr('Erscheinungsbild')} geltung={tr('Gilt in diesem Browser')}>
          <Erscheinungsbild kulisseId="kulisse" />
        </Abschnitt>
        <Abschnitt id="meldungen" titel={tr('Meldungen')} geltung={tr('Gilt in diesem Browser')}>
          <MeldungenEinstellen />
        </Abschnitt>
        <Abschnitt id="raeume" titel={tr('Räume')} geltung={tr('Gilt in diesem Browser')}>
          <RaeumeEinstellen />
        </Abschnitt>
      </div>
    </div>
  );
}
