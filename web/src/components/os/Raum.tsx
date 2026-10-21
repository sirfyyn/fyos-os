/**
 * Ein Raum der Shell: liegt als ganze Seite über den Arbeitsbildschirmen (die bleiben geladen) und hat eine feste
 * Aufteilung: Mitte, Leiste des Raums rechts. Details kommen als Schublade, nicht als dauerhaftes Panel. Jeder Raum lädt
 * seinen Inhalt erst, wenn er zum ersten Mal vorn ist.
 *
 * Die Zentrale hat hier keinen Eintrag: sie ist die Shell selbst (Startbildschirm und Arbeitsbildschirme), die Shell
 * legt nur die anderen Räume darüber.
 *
 * Vertrag für einen neuen Raum: Eintrag in lib/os/raeume.ts (gebaut: true) und hier in INHALT; die Komponente
 * bekommt RaumProps und benutzt RaumRahmen. Ein Raum ist eine leere Hülle: er zeigt nur, was eingerichtete Plugins
 * liefern (components/raeume/Huelle.tsx), sonst „Noch nicht eingerichtet.“.
 */
import { Show, Suspense, lazy, type Component, type JSX } from 'solid-js';
import { Dynamic } from 'solid-js/web';
import type { NativProps } from '~/lib/os/nativ';
import { raumZu, type RaumId } from '~/lib/os/raeume';
import { Laedt } from '~/components/einstellungen/bausteine';

export type RaumProps = NativProps & {
  /** Zurück in die Zentrale (im schmalen Fenster gibt es keine Räume-Leiste) */
  heim: () => void;
};

const INHALT: Partial<Record<RaumId, Component<RaumProps>>> = {
  atelier: lazy(() => import('~/components/raeume/RaumAtelier')),
  betrieb: lazy(() => import('~/components/raeume/RaumBetrieb')),
  buero: lazy(() => import('~/components/raeume/RaumBuero')),
  einstellungen: lazy(() => import('~/components/raeume/RaumEinstellungen')),
  gespraech: lazy(() => import('~/components/raeume/RaumGespraech')),
  sammlung: lazy(() => import('~/components/raeume/RaumSammlung')),
  vorhaben: lazy(() => import('~/components/raeume/RaumVorhaben')),
  zuhause: lazy(() => import('~/components/raeume/RaumZuhause')),
};

export const raumHatInhalt = (id: RaumId): boolean => !!INHALT[id];

/** Feste Aufteilung eines Raums: Kopf, Mitte, rechts die Leiste des Raums (im schmalen Fenster oben). */
export function RaumRahmen(p: {
  titel: string;
  /** Leiste des Raums (rechts) */
  leiste?: JSX.Element;
  leisteName?: string;
  schmal: boolean;
  heim: () => void;
  /** Mitte ohne eigenes Scrollen (füllt selbst, z. B. eingebettete App) */
  fuellen?: boolean;
  children: JSX.Element;
}): JSX.Element {
  return (
    <div class="flex h-full min-h-0 w-full" classList={{ 'flex-col': p.schmal }} data-raum-rahmen>
      <Show when={p.schmal}>
        <div class="flex shrink-0 items-center gap-2 px-3 pt-3">
          <button type="button" class="os-knopf" aria-label="Zur Zentrale" onClick={() => p.heim()}>
            ‹
          </button>
          <h1 class="os-titel m-0 truncate">{p.titel}</h1>
        </div>
        <Show when={p.leiste}>
          <nav aria-label={p.leisteName ?? `Leiste ${p.titel}`} class="shrink-0 overflow-x-auto px-3 pt-2" data-raum-leiste>
            {p.leiste}
          </nav>
        </Show>
      </Show>
      <main
        class="flex min-h-0 min-w-0 flex-1 flex-col"
        classList={{ 'overflow-y-auto': !p.fuellen, 'overflow-hidden': !!p.fuellen }}
        aria-label={p.titel}
        data-raum-mitte
      >
        {p.children}
      </main>
      <Show when={!p.schmal && p.leiste}>
        <aside
          aria-label={p.leisteName ?? `Leiste ${p.titel}`}
          class="flex w-[17.5rem] shrink-0 flex-col gap-0.5 overflow-y-auto border-l border-(--color-border) px-3.5 py-4"
          data-raum-leiste
        >
          {p.leiste}
        </aside>
      </Show>
    </div>
  );
}

/** Der Raum vorn: legt sich über den Bereich der Arbeitsbildschirme. */
export default function Raum(p: { id: RaumId } & RaumProps): JSX.Element {
  const inhalt = () => INHALT[p.id];
  return (
    <section
      class="os-glas absolute inset-0 z-[6] flex min-h-0 overflow-hidden"
      // Deckend: ein Raum ist eine ganze Seite, die Fenster darunter sollen nicht durchscheinen (os-glas ist durchsichtig,
      // große Schrift und Uhr der Zentrale schimmerten sonst noch durch)
      style={{ background: 'var(--color-bg-opaque)' }}
      classList={{ 'm-3': !p.schmal, 'rounded-none': p.schmal }}
      aria-label={`Raum ${raumZu(p.id)?.name ?? ''}`}
      data-raum={p.id}
    >
      <Show
        when={inhalt()}
        fallback={<p class="m-auto text-sm text-(--color-fg-muted)">Dieser Raum ist noch nicht gebaut.</p>}
      >
        {(k) => (
          <Suspense fallback={<div class="m-auto"><Laedt /></div>}>
            <Dynamic component={k()} oeffne={p.oeffne} schmal={p.schmal} heim={p.heim} />
          </Suspense>
        )}
      </Show>
    </section>
  );
}
