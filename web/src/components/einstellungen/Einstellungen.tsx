/**
 * Einstellungen — die native Fläche `nativ:einstellungen` (vorläufiger Stand: nur Erscheinungsbild).
 */
import type { JSX } from 'solid-js';
import type { NativProps } from '~/lib/os/nativ';
import { Abschnitt } from './bausteine';
import Erscheinungsbild from './Erscheinungsbild';

export default function Einstellungen(_p: NativProps): JSX.Element {
  return (
    <div class="@container" data-einstellungen>
      <div class="mx-auto w-full max-w-3xl space-y-5 px-4 py-5 @2xl:px-8">
        <Abschnitt id="erscheinungsbild" titel="Erscheinungsbild" geltung="Gilt in diesem Browser">
          <Erscheinungsbild kulisseId="kulisse" />
        </Abschnitt>
      </div>
    </div>
  );
}
