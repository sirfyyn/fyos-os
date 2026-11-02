/**
 * Raum Einstellungen: rechts die Bereiche, in der Mitte der gewählte.
 *
 * Was es schon gibt, wird hier aufgenommen statt verdoppelt: das Erscheinungsbild, die Räume, die Konten-App
 * (konten.uebersicht), die MCP-App als „Plugins“, die Modellwahl und das Gedächtnis (verlauf.zustand). Eine App, die
 * kein Plugin liefert, zeigt „Noch nicht eingerichtet.“; Bereiche ohne Grundlage stehen ehrlich als „geplant“ da.
 */
import { For, Match, Show, Switch, createMemo, createSignal, type JSX } from 'solid-js';
import { Abschnitt } from '~/components/einstellungen/bausteine';
import Erscheinungsbild from '~/components/einstellungen/Erscheinungsbild';
import RaeumeEinstellen from '~/components/einstellungen/RaeumeEinstellen';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { Geplant, HubApp, gemerkteWahl, wahlMerken } from '~/components/raeume/Huelle';
import { tr } from '~/lib/i18n';

type Art = { art: 'nativ' } | { art: 'app'; name: string } | { art: 'geplant'; quelle: string };
interface Bereich {
  id: string;
  titel: string;
  /** Suchwörter neben dem Titel */
  stichworte: string;
  inhalt: Art;
}

export const BEREICHE: readonly Bereich[] = [
  { id: 'erscheinungsbild', titel: 'Erscheinungsbild', stichworte: 'thema hell dunkel kulisse tapete farbe', inhalt: { art: 'nativ' } },
  { id: 'raeume', titel: 'Räume und Dock', stichworte: 'räume leiste reihenfolge dock zentrale', inhalt: { art: 'nativ' } },
  { id: 'konten', titel: 'Konten und Zugänge', stichworte: 'konto anmeldung verbinden zugang', inhalt: { art: 'app', name: 'konten__uebersicht' } },
  { id: 'plugins', titel: 'Plugins', stichworte: 'mcp werkzeuge server hub', inhalt: { art: 'app', name: 'mcp__uebersicht' } },
  { id: 'modelle', titel: 'Modelle', stichworte: 'modell gpu wahl', inhalt: { art: 'app', name: 'modelle__zustand' } },
  { id: 'agenten', titel: 'Agenten und Grenzen', stichworte: 'agent rechte bestätigen grenzen', inhalt: { art: 'geplant', quelle: 'die Rechte und Grenzen des Agenten' } },
  { id: 'kanaele', titel: 'Kanäle', stichworte: 'matrix telegram nachrichten kanal', inhalt: { art: 'geplant', quelle: 'die Kanäle des Agenten' } },
  { id: 'zuhause', titel: 'Zuhause-Kopplung', stichworte: 'zuhause geräte zwilling', inhalt: { art: 'geplant', quelle: 'die Kopplung des Zuhauses (Raum Zuhause)' } },
  { id: 'stimme', titel: 'Stimme und Augen', stichworte: 'stt tts kamera stimme', inhalt: { art: 'geplant', quelle: 'Ein- und Ausgabe per Sprache und Kamera' } },
  { id: 'gedaechtnis', titel: 'Gedächtnis und Vergessen', stichworte: 'verlauf vergessen erinnerung', inhalt: { art: 'app', name: 'verlauf__zustand' } },
  { id: 'sicherungen', titel: 'Sicherungen', stichworte: 'backup sicherung', inhalt: { art: 'geplant', quelle: 'die Sicherungen dieser Installation' } },
];

const SCHLUESSEL = 'fyos.raum.einstellungen.bereich';

export default function RaumEinstellungen(p: RaumProps): JSX.Element {
  const [bereich, setBereich] = createSignal(gemerkteWahl(SCHLUESSEL, (id) => BEREICHE.some((b) => b.id === id), 'erscheinungsbild'));
  const [suche, setSuche] = createSignal('');
  const waehle = (id: string) => {
    setBereich(id);
    wahlMerken(SCHLUESSEL, id);
  };
  const treffer = createMemo(() => {
    const q = suche().trim().toLowerCase();
    if (!q) return BEREICHE;
    return BEREICHE.filter((b) => `${b.titel} ${b.stichworte}`.toLowerCase().includes(q));
  });
  const aktuell = () => BEREICHE.find((b) => b.id === bereich()) ?? BEREICHE[0]!;

  const leiste = (
    <>
      <input
        type="search"
        aria-label={tr('In allen Einstellungen suchen')}
        placeholder={tr('In allen Einstellungen suchen')}
        value={suche()}
        onInput={(e) => setSuche(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && treffer()[0]) waehle(treffer()[0]!.id);
        }}
        class="mb-2 h-9 w-full rounded-[10px] border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_5%,transparent)] px-3 text-sm text-(--color-fg) placeholder:text-(--color-fg-muted) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
        classList={{ 'max-w-xs': p.schmal }}
      />
      <Show when={!p.schmal}>
        <span class="px-2.5 pt-1 pb-2 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">{tr('Bereiche')}</span>
      </Show>
      <ul class="m-0 flex list-none gap-0.5 p-0" classList={{ 'flex-col': !p.schmal, 'flex-row whitespace-nowrap': p.schmal }}>
        <For each={treffer()} fallback={<li class="px-2.5 py-2 text-sm text-(--color-fg-muted)">{tr('Kein Bereich passt.')}</li>}>
          {(b) => (
            <li>
              <button
                type="button"
                data-bereich={b.id}
                aria-current={b.id === bereich() ? 'page' : undefined}
                onClick={() => waehle(b.id)}
                class="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-[0.85rem] transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-(--color-accent)"
                classList={{
                  'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)': b.id === bereich(),
                  'text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] hover:text-(--color-fg)': b.id !== bereich(),
                }}
              >
                <span class="flex-1">{b.titel}</span>
                <Show when={b.inhalt.art === 'geplant'}>
                  <span class="text-[11px] text-(--color-fg-muted)">geplant</span>
                </Show>
              </button>
            </li>
          )}
        </For>
      </ul>
    </>
  );

  return (
    <RaumRahmen titel={tr('Einstellungen')} leiste={leiste} leisteName={tr('Bereiche der Einstellungen')} schmal={p.schmal} heim={p.heim} fuellen={aktuell().inhalt.art === 'app'}>
      <div class="mx-auto flex w-full max-w-3xl min-h-0 flex-1 flex-col gap-4 px-4 py-5" data-einstellungen-bereich={aktuell().id}>
        <h1 class="m-0 text-2xl font-bold text-(--color-fg)">{aktuell().titel}</h1>
        <Switch>
          <Match when={aktuell().id === 'erscheinungsbild'}>
            <Abschnitt id="raum-erscheinungsbild" titel={tr('Erscheinungsbild')} geltung={tr('Gilt in diesem Browser')}>
              <Erscheinungsbild kulisseId="raum-kulisse" />
            </Abschnitt>
          </Match>
          <Match when={aktuell().id === 'raeume'}>
            <Abschnitt id="raum-raeume" titel={tr('Räume')} geltung={tr('Gilt in diesem Browser')}>
              <RaeumeEinstellen />
            </Abschnitt>
          </Match>
          {/* keyed: HubApp liest den Namen nur beim Einhängen, ohne keyed bliebe beim Wechsel zwischen zwei Apps die erste stehen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => (
              <div class="flex min-h-0 flex-1 flex-col">
                <HubApp name={(a as { name: string }).name} titel={aktuell().titel} fuellen schluessel={`raum-einstellungen:${aktuell().id}`} />
              </div>
            )}
          </Match>
          <Match when={aktuell().inhalt.art === 'geplant' && aktuell().inhalt}>
            {(g) => <Geplant quelle={(g() as { quelle: string }).quelle} />}
          </Match>
        </Switch>
      </div>
    </RaumRahmen>
  );
}
