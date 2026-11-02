/**
 * Raum Betrieb: wie es dem Cluster, den Agenten und den Rechnern geht. Rechts die Leiste nach Bereich: Lage, Cluster,
 * Agenten und Modelle, Werkzeuge, Rechner.
 *
 * Aufgenommen statt verdoppelt: alles kommt als die Hub-App, die ein eingerichtetes Plugin liefert (Lagebild, Steuerpult,
 * Repos, Vorgänge, Modelle, Werkstatt, Plugins, Desktop); fehlt sie, steht „Noch nicht eingerichtet.“ da. Braucht dich und
 * Lagebild können zusätzlich auf dem Startbildschirm stehen.
 */
import { Match, Switch, createSignal, type JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { EintragLeiste, Geplant, HubApp, SeitenFlaeche, gemerkteWahl, wahlMerken } from '~/components/raeume/Huelle';
import { tr } from '~/lib/i18n';

type Art = { art: 'app'; name: string } | { art: 'seite'; id: string } | { art: 'geplant'; quelle: string };
export interface Eintrag {
  id: string;
  titel: string;
  zeile: string;
  gruppe: 'Lage' | 'Cluster' | 'Agenten und Modelle' | 'Werkzeuge' | 'Rechner';
  inhalt: Art;
}

export const EINTRAEGE: readonly Eintrag[] = [
  { id: 'lagebild', titel: 'Lagebild', zeile: 'Ampel, Fristen, Chronik', gruppe: 'Lage', inhalt: { art: 'app', name: 'leitstand__lagebild' } },
  { id: 'steuerpult', titel: 'Steuerpult', zeile: 'Knoten, Workloads, Flux', gruppe: 'Cluster', inhalt: { art: 'app', name: 'cluster__knoten' } },
  { id: 'repos', titel: 'Repos und CI', zeile: 'Zweige, Läufe, Stand', gruppe: 'Cluster', inhalt: { art: 'app', name: 'repos__uebersicht' } },
  { id: 'vorgaenge', titel: 'Vorgänge', zeile: 'wer arbeitet woran', gruppe: 'Agenten und Modelle', inhalt: { art: 'app', name: 'vorgaenge__zeigen' } },
  { id: 'modelle', titel: 'Modelle', zeile: 'was geladen ist, was passt', gruppe: 'Agenten und Modelle', inhalt: { art: 'app', name: 'modelle__zustand' } },
  { id: 'werkstatt', titel: 'Werkstatt', zeile: 'Skripte ausführen', gruppe: 'Werkzeuge', inhalt: { art: 'app', name: 'werkstatt__suchen' } },
  { id: 'plugins', titel: 'Plugins', zeile: 'Werkzeuge und Gesundheit im Hub', gruppe: 'Werkzeuge', inhalt: { art: 'app', name: 'mcp__uebersicht' } },
  { id: 'desktop', titel: 'Desktop', zeile: 'Bildschirm des Arbeitsrechners', gruppe: 'Rechner', inhalt: { art: 'app', name: 'desktop__zeigen' } },
];

const GRUPPEN = ['Lage', 'Cluster', 'Agenten und Modelle', 'Werkzeuge', 'Rechner'] as const;
const SCHLUESSEL = 'fyos.raum.betrieb';

export default function RaumBetrieb(p: RaumProps): JSX.Element {
  const [gewaehlt, setGewaehlt] = createSignal(gemerkteWahl(SCHLUESSEL, (id) => EINTRAEGE.some((e) => e.id === id), 'lagebild'));
  const waehle = (id: string) => {
    setGewaehlt(id);
    wahlMerken(SCHLUESSEL, id);
  };
  const aktuell = () => EINTRAEGE.find((e) => e.id === gewaehlt()) ?? EINTRAEGE[0]!;
  const leistenEintraege = () => EINTRAEGE.map((e) => ({ ...e, geplant: e.inhalt.art === 'geplant' }));

  return (
    <RaumRahmen
      titel={tr('Betrieb')}
      leiste={<EintragLeiste eintraege={leistenEintraege()} gruppen={GRUPPEN} gewaehlt={gewaehlt()} waehle={waehle} schmal={p.schmal} kennung="betrieb" />}
      leisteName={tr('Bereiche des Betriebs')}
      schmal={p.schmal}
      heim={p.heim}
      fuellen={aktuell().inhalt.art !== 'geplant'}
    >
      <div class="flex min-h-0 flex-1 flex-col" data-betrieb-mitte={aktuell().id}>
        <Switch>
          {/* keyed: HubApp und die Seite lesen ihr Ziel nur beim Einhängen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => <HubApp name={(a as { name: string }).name} titel={aktuell().titel} ohneKopf fuellen schluessel={`raum-betrieb:${aktuell().id}`} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'seite' && aktuell().inhalt} keyed>
            {(s) => <SeitenFlaeche id={(s as { id: string }).id} oeffne={p.oeffne} schmal={p.schmal} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'geplant' && aktuell().inhalt} keyed>
            {(g) => (
              <div class="px-4 py-5">
                <Geplant titel={aktuell().titel} quelle={(g as { quelle: string }).quelle} />
              </div>
            )}
          </Match>
        </Switch>
      </div>
    </RaumRahmen>
  );
}
