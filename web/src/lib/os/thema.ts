/**
 * thema.ts — Hell/Dunkel/System für Menü und Kontrollzentrum des OS.
 *
 * Nur eine dünne Hülle um lib/einstellungen/farbschema.ts (die eine Stelle für das Farbschema): dieselben Schlüssel,
 * dieselbe Vorgabe („System“, folgt prefers-color-scheme), dasselbe Ereignis. Offene Seiten in Fenstern ziehen über
 * das `storage`-Ereignis nach (BaseLayout, eingebettet). Das frühere „Automatisch“ nach Uhrzeit gibt es nicht mehr;
 * ein gespeichertes `auto` gilt als „System“.
 */
import { farbschemaLaden, farbschemaSetzen, type Farbschema } from '~/lib/einstellungen/farbschema';

export type ThemaWahl = 'dark' | 'light' | 'system';

const ZU_SCHEMA: Record<ThemaWahl, Farbschema> = { light: 'hell', dark: 'dunkel', system: 'system' };
const ZU_WAHL: Record<Farbschema, ThemaWahl> = { hell: 'light', dunkel: 'dark', system: 'system' };

export function themaWahl(): ThemaWahl {
  return ZU_WAHL[farbschemaLaden()];
}

export function themaSetzen(w: ThemaWahl): void {
  farbschemaSetzen(ZU_SCHEMA[w]);
}
