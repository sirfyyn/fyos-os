/**
 * Plugins der Shell: jede Datei `src/plugins/*.ts` (außer dieser) wird beim Laden der Shell ausgeführt und
 * darf `registriereFlaechen({ … })` aufrufen (lib/os/register.ts). So bringt ein Plugin seine Seiten, Symbole,
 * Gruppen und Vorlagen mit, ohne die Shell anzufassen. Hub-Apps brauchen das nicht: sie erscheinen von selbst.
 *
 * Beispiel `src/plugins/notizen.ts`:
 *
 *     import { registriereFlaechen } from '~/lib/os/register';
 *     registriereFlaechen({
 *       flaechen: [{ id: 'seite:notizen', titel: 'Notizen', gruppe: 'Arbeit', art: 'seite', kuerzel: 'No', pfad: '/notizen/' }],
 *       symbole: { 'seite:notizen': ['file-text', 200] },
 *     });
 */
import.meta.glob(['./*.ts', '!./index.ts'], { eager: true });
