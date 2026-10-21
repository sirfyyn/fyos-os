/**
 * Raum Gespräch: ein Ort für alles, was gesprochen wird.
 *
 * Mitte ist das Gespräch mit dem Agenten: der Chat des Gateways (`agentPfad()`, gleicher Ursprung) als iframe, derselbe
 * wie im Agent-Dock der Shell. Rechts die Leiste mit Gesprächen, Vorgängen und Kanälen; was ein Plugin als Hub-App liefert
 * (Vorgänge), kommt als App in die Mitte, ein Kanal-Verlauf als eigener Verlauf (MatrixVerlauf), was fehlt, steht ehrlich
 * als „geplant“ oder „Noch nicht eingerichtet.“ da.
 */
import { Match, Switch, createSignal, type JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { EintragLeiste, Geplant, HubApp, gemerkteWahl, wahlMerken } from '~/components/raeume/Huelle';
import MatrixVerlauf from '~/components/raeume/MatrixVerlauf';
import { agentName, agentPfad } from '~/lib/config';
import { fremdesThemaAnwenden } from '~/lib/os/thema';

type Inhalt = { art: 'agent' } | { art: 'matrix' } | { art: 'app'; name: string } | { art: 'geplant'; quelle: string };
export interface Eintrag {
  id: string;
  titel: string;
  /** Eine Zeile unter dem Titel in der Leiste */
  zeile: string;
  gruppe: 'Gespräche' | 'Agenten-Sitzungen' | 'Kanäle';
  inhalt: Inhalt;
}

export const EINTRAEGE: readonly Eintrag[] = [
  { id: 'agent', titel: 'Agent', zeile: 'das Gespräch mit dem Agenten', gruppe: 'Gespräche', inhalt: { art: 'agent' } },
  { id: 'vorgaenge', titel: 'Vorgänge', zeile: 'wer arbeitet woran', gruppe: 'Agenten-Sitzungen', inhalt: { art: 'app', name: 'vorgaenge__zeigen' } },
  { id: 'matrix', titel: 'Matrix', zeile: 'Verlauf eines Kanals, nur lesen', gruppe: 'Kanäle', inhalt: { art: 'matrix' } },
  { id: 'telegram', titel: 'Telegram', zeile: 'über den Agenten', gruppe: 'Kanäle', inhalt: { art: 'geplant', quelle: 'die Kanäle des Agenten, wie Telegram' } },
];

const GRUPPEN = ['Gespräche', 'Agenten-Sitzungen', 'Kanäle'] as const;
const SCHLUESSEL = 'fyos.raum.gespraech';

export default function RaumGespraech(p: RaumProps): JSX.Element {
  const [gewaehlt, setGewaehlt] = createSignal(gemerkteWahl(SCHLUESSEL, (id) => EINTRAEGE.some((e) => e.id === id), 'agent'));
  const waehle = (id: string) => {
    setGewaehlt(id);
    wahlMerken(SCHLUESSEL, id);
  };
  const aktuell = () => EINTRAEGE.find((e) => e.id === gewaehlt()) ?? EINTRAEGE[0]!;
  // Der Agent heißt, wie die Konfiguration ihn nennt
  const eintraege = () => EINTRAEGE.map((e) => (e.inhalt.art === 'agent' ? { ...e, titel: agentName() } : e));
  const leistenEintraege = () => eintraege().map((e) => ({ ...e, geplant: e.inhalt.art === 'geplant' }));

  return (
    <RaumRahmen
      titel="Gespräch"
      leiste={<EintragLeiste eintraege={leistenEintraege()} gruppen={GRUPPEN} gewaehlt={gewaehlt()} waehle={waehle} schmal={p.schmal} kennung="gespraech" />}
      leisteName="Gespräche und Kanäle"
      schmal={p.schmal}
      heim={p.heim}
      fuellen={aktuell().inhalt.art !== 'geplant'}
    >
      <div class="flex min-h-0 flex-1 flex-col" data-gespraech-mitte={aktuell().id}>
        <Switch>
          <Match when={aktuell().inhalt.art === 'agent'}>
            <iframe
              src={agentPfad()}
              title={`${agentName()}-Chat`}
              class="min-h-0 flex-1 border-0 bg-(--color-bg)"
              style={{ 'color-scheme': 'dark light' }}
              onLoad={(e) => fremdesThemaAnwenden(e.currentTarget)}
            />
          </Match>
          <Match when={aktuell().inhalt.art === 'matrix'}>
            <MatrixVerlauf />
          </Match>
          {/* keyed: HubApp liest den Namen nur beim Einhängen, ohne keyed bliebe beim Wechsel zwischen zwei Apps die erste stehen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => <HubApp name={(a as { name: string }).name} titel={aktuell().titel} ohneKopf fuellen schluessel={`raum-gespraech:${aktuell().id}`} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'geplant' && aktuell().inhalt}>
            {(g) => (
              <div class="px-4 py-5">
                <Geplant titel={aktuell().titel} quelle={(g() as { quelle: string }).quelle} />
              </div>
            )}
          </Match>
        </Switch>
      </div>
    </RaumRahmen>
  );
}
