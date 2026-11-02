/**
 * Raum Büro: Post, Zeit und Geld an einem Ort. Rechts die Leiste nach Thema: Post (Mail, Bestellungen, Serienmails),
 * Zeit (Termine, Kalender, Tagesbrief), Geld (Finanzen, Dokumente, Eingang).
 *
 * Aufgenommen statt verdoppelt: die kompakten Hub-Apps (Mail, Termine, Dokument-Eingang) kommen als Apps, die großen
 * Seiten (Kalender, Finanzen, Dokumente) als dieselbe eingebettete Seite wie im Fenster, sobald ein Plugin sie über
 * `registriereFlaechen` einbringt. Bestellungen, Serienmails und Tagesbrief haben keine Hub-App, aber eine klare Antwort:
 * kleine native Ansichten (BueroAnsichten.tsx). Was kein Plugin liefert, zeigt „Noch nicht eingerichtet.“.
 */
import { Match, Switch, createSignal, type JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { Bestellungen, Post, Tagesbrief } from '~/components/raeume/BueroAnsichten';
import { EintragLeiste, Geplant, HubApp, SeitenFlaeche, gemerkteWahl, wahlMerken } from '~/components/raeume/Huelle';
import { tr } from '~/lib/i18n';

type Art =
  | { art: 'app'; name: string }
  | { art: 'seite'; id: string }
  | { art: 'nativ'; was: 'bestellungen' | 'post' | 'tagesbrief' }
  | { art: 'geplant'; quelle: string };
export interface Eintrag {
  id: string;
  titel: string;
  zeile: string;
  gruppe: 'Post' | 'Zeit' | 'Geld';
  inhalt: Art;
}

export const EINTRAEGE: readonly Eintrag[] = [
  { id: 'mail', titel: 'Mail', zeile: 'Posteingang, neueste zuerst', gruppe: 'Post', inhalt: { art: 'app', name: 'posteingang__zeigen' } },
  { id: 'bestellungen', titel: 'Bestellungen', zeile: 'Shop, Status, kommt heute', gruppe: 'Post', inhalt: { art: 'nativ', was: 'bestellungen' } },
  { id: 'kampagnen', titel: 'Serienmails', zeile: 'Kampagnen und Listen', gruppe: 'Post', inhalt: { art: 'nativ', was: 'post' } },
  { id: 'termine', titel: 'Termine', zeile: 'heute und die nächsten Tage', gruppe: 'Zeit', inhalt: { art: 'app', name: 'termine__zeigen' } },
  { id: 'kalender', titel: 'Kalender', zeile: 'Woche und Monat', gruppe: 'Zeit', inhalt: { art: 'seite', id: 'seite:kalender' } },
  { id: 'tagesbrief', titel: 'Tagesbrief', zeile: 'der Morgen auf einer Seite', gruppe: 'Zeit', inhalt: { art: 'nativ', was: 'tagesbrief' } },
  { id: 'finanzen', titel: 'Finanzen', zeile: 'Monatsplan, Posten, Konten', gruppe: 'Geld', inhalt: { art: 'seite', id: 'seite:finanzen' } },
  { id: 'dokumente', titel: 'Dokumente', zeile: 'Briefe, Rechnungen, Belege', gruppe: 'Geld', inhalt: { art: 'seite', id: 'seite:dokumente' } },
  { id: 'eingang', titel: 'Eingang', zeile: 'neu und unsortiert', gruppe: 'Geld', inhalt: { art: 'app', name: 'dokumente__eingang' } },
];

const GRUPPEN = ['Post', 'Zeit', 'Geld'] as const;
const SCHLUESSEL = 'fyos.raum.buero';

export default function RaumBuero(p: RaumProps): JSX.Element {
  const [gewaehlt, setGewaehlt] = createSignal(gemerkteWahl(SCHLUESSEL, (id) => EINTRAEGE.some((e) => e.id === id), 'mail'));
  const waehle = (id: string) => {
    setGewaehlt(id);
    wahlMerken(SCHLUESSEL, id);
  };
  const aktuell = () => EINTRAEGE.find((e) => e.id === gewaehlt()) ?? EINTRAEGE[0]!;
  const leistenEintraege = () => EINTRAEGE.map((e) => ({ ...e, geplant: e.inhalt.art === 'geplant' }));

  return (
    <RaumRahmen
      titel={tr('Büro')}
      leiste={<EintragLeiste eintraege={leistenEintraege()} gruppen={GRUPPEN} gewaehlt={gewaehlt()} waehle={waehle} schmal={p.schmal} kennung="buero" />}
      leisteName={tr('Bereiche des Büros')}
      schmal={p.schmal}
      heim={p.heim}
      fuellen={aktuell().inhalt.art === 'app' || aktuell().inhalt.art === 'seite'}
    >
      <div class="flex min-h-0 flex-1 flex-col" data-buero-mitte={aktuell().id}>
        <Switch>
          {/* keyed: HubApp und die Seite lesen ihr Ziel nur beim Einhängen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => <HubApp name={(a as { name: string }).name} titel={aktuell().titel} ohneKopf fuellen schluessel={`raum-buero:${aktuell().id}`} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'seite' && aktuell().inhalt} keyed>
            {(s) => <SeitenFlaeche id={(s as { id: string }).id} oeffne={p.oeffne} schmal={p.schmal} />}
          </Match>
          <Match when={aktuell().inhalt.art === 'nativ' && aktuell().inhalt} keyed>
            {(n) => {
              const was = (n as { was: string }).was;
              return was === 'bestellungen' ? <Bestellungen /> : was === 'post' ? <Post /> : <Tagesbrief />;
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
