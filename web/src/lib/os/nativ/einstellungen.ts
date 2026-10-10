/**
 * Native Fläche „Einstellungen": Erscheinungsbild (Farbschema, Kulisse). Die Bedienelemente stehen in
 * components/einstellungen/, die Logik in lib/einstellungen/.
 */
import type { NativEintrag } from '../nativ';

export const EINSTELLUNGEN: NativEintrag[] = [
  {
    id: 'nativ:einstellungen',
    titel: 'Einstellungen',
    gruppe: 'System',
    kuerzel: 'Ei',
    laden: () => import('~/components/einstellungen/Einstellungen'),
  },
];
