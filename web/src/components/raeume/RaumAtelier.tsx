/**
 * Raum Atelier: wo etwas gemacht wird. Bilder erzeugen, Schreiben, Bearbeiten. Rechts die Leiste nach Tätigkeit.
 *
 * Aufgenommen statt verdoppelt: Geschichten öffnen ihre App, wenn ein Plugin sie liefert. Was keine Fläche hat (Dokumente,
 * Foto, Vektor, Video), steht ehrlich als „geplant“ da, mit dem, woraus es kommen wird.
 */
import { Match, Switch, createSignal, type JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import BildWerkstatt from '~/components/raeume/BildWerkstatt';
import { EintragLeiste, Geplant, HubApp, gemerkteWahl, wahlMerken } from '~/components/raeume/Huelle';

type Inhalt =
  | { art: 'bild' }
  | { art: 'app'; name: string }
  | { art: 'oeffnen'; ziel: string; text: string }
  | { art: 'geplant'; quelle: string };
export interface Eintrag {
  id: string;
  titel: string;
  zeile: string;
  gruppe: 'Erzeugen' | 'Schreiben' | 'Bearbeiten';
  inhalt: Inhalt;
}

export const EINTRAEGE: readonly Eintrag[] = [
  { id: 'bild', titel: 'Bild', zeile: 'Beschreibung → Bild', gruppe: 'Erzeugen', inhalt: { art: 'bild' } },
  { id: 'video', titel: 'Video', zeile: 'Bewegtbild', gruppe: 'Erzeugen', inhalt: { art: 'geplant', quelle: 'ein Medien-Dienst für Bewegtbild (heute nur Bilder)' } },
  {
    id: 'geschichten',
    titel: 'Geschichten',
    zeile: 'Kapitel und Entwürfe',
    gruppe: 'Schreiben',
    inhalt: { art: 'oeffnen', ziel: 'app:geschichten__liste', text: 'Die Geschichten haben ihre eigene Schreibfläche mit Kapiteln und Entwürfen. Sie öffnet als Fenster, sobald ein Plugin sie liefert.' },
  },
  { id: 'dokumente', titel: 'Dokumente', zeile: 'Text, Tabelle und PDF', gruppe: 'Schreiben', inhalt: { art: 'geplant', quelle: 'Werkzeuge für Text, Tabellen und PDF (heute nur als Werkzeuge für Agenten)' } },
  { id: 'photo', titel: 'Foto bearbeiten', zeile: 'Bildbearbeitung', gruppe: 'Bearbeiten', inhalt: { art: 'geplant', quelle: 'ein Werkzeug zur Bildbearbeitung' } },
  { id: 'vektor', titel: 'Vektor', zeile: 'Formen und Logos', gruppe: 'Bearbeiten', inhalt: { art: 'geplant', quelle: 'eine Vektor-Fläche, die es noch nicht gibt' } },
];

const GRUPPEN = ['Erzeugen', 'Schreiben', 'Bearbeiten'] as const;
const SCHLUESSEL = 'fyos.raum.atelier';

export default function RaumAtelier(p: RaumProps): JSX.Element {
  const [gewaehlt, setGewaehlt] = createSignal(gemerkteWahl(SCHLUESSEL, (id) => EINTRAEGE.some((e) => e.id === id), 'bild'));
  const waehle = (id: string) => {
    setGewaehlt(id);
    wahlMerken(SCHLUESSEL, id);
  };
  const aktuell = () => EINTRAEGE.find((e) => e.id === gewaehlt()) ?? EINTRAEGE[0]!;
  const leistenEintraege = () => EINTRAEGE.map((e) => ({ ...e, geplant: e.inhalt.art === 'geplant' }));

  return (
    <RaumRahmen
      titel="Atelier"
      leiste={<EintragLeiste eintraege={leistenEintraege()} gruppen={GRUPPEN} gewaehlt={gewaehlt()} waehle={waehle} schmal={p.schmal} kennung="atelier" />}
      leisteName="Bereiche des Ateliers"
      schmal={p.schmal}
      heim={p.heim}
      fuellen={aktuell().inhalt.art === 'app'}
    >
      <div class="flex min-h-0 flex-1 flex-col" data-atelier-mitte={aktuell().id}>
        <Switch>
          <Match when={aktuell().inhalt.art === 'bild'}>
            <BildWerkstatt />
          </Match>
          {/* keyed: HubApp liest den Namen nur beim Einhängen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => <HubApp name={(a as { name: string }).name} titel={aktuell().titel} ohneKopf fuellen schluessel={`raum-atelier:${aktuell().id}`} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'oeffnen' && aktuell().inhalt} keyed>
            {(o) => {
              const z = o as { ziel: string; text: string };
              return (
                <div class="mx-auto flex w-full max-w-3xl flex-col items-start gap-3 px-4 py-5">
                  <h1 class="m-0 text-2xl font-bold text-(--color-fg)">{aktuell().titel}</h1>
                  <p class="m-0 max-w-prose text-sm leading-relaxed text-(--color-fg-muted)">{z.text}</p>
                  <button type="button" class="os-knopf h-9 px-4" data-atelier-oeffnen={z.ziel} onClick={() => p.oeffne(z.ziel)}>
                    {aktuell().titel} öffnen
                  </button>
                </div>
              );
            }}
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
