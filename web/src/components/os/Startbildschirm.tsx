/**
 * Startbildschirm — Bildschirm 0 des OS: ein App-Launcher mit allen Flächen und Hub-Apps.
 *
 * Oben der Name des Systems, darunter die angehefteten Apps („An den Start heften“ im Kachelmenü),
 * dann alle Flächen nach Gruppen. Ein Klick öffnet die Fläche; Rechtsklick und Ziehen laufen über
 * dieselben Mechanismen wie im Start-Panel (`data-kontext="flaeche:<id>"`, lib/os/ziehen.ts).
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { systemName } from '~/lib/config';
import { pins as lesePins, pinsBeobachten } from '~/lib/mcp-apps/pins';
import type { Flaeche } from '~/lib/os/flaechen';
import { gutSetzen, zugBeginnt, zugBild } from '~/lib/os/ziehen';
import Symbol from './Symbol';

export interface StartbildschirmProps {
  gruppen: { gruppe: string; flaechen: Flaeche[] }[];
  offen: (id: string) => boolean;
  onOeffnen: (id: string) => void;
  onZiehEnde?: () => void;
}

export default function Startbildschirm(p: StartbildschirmProps): JSX.Element {
  const [geheftet, setGeheftet] = createSignal<string[]>([]);
  onMount(() => {
    setGeheftet(lesePins());
    onCleanup(pinsBeobachten(setGeheftet));
  });
  const alle = () => p.gruppen.flatMap((g) => g.flaechen);
  const angeheftet = () => {
    const namen = geheftet();
    return alle().filter((f) => f.appName && namen.includes(f.appName));
  };

  const Kachel = (k: { f: Flaeche }): JSX.Element => (
    <button
      type="button"
      draggable="true"
      data-kontext={`flaeche:${k.f.id}`}
      class="os-kachel"
      title={k.f.untertitel || undefined}
      onClick={() => p.onOeffnen(k.f.id)}
      onDragStart={(e) => {
        gutSetzen(e.dataTransfer, { art: 'flaeche', id: k.f.id }, k.f.titel);
        zugBild(e.dataTransfer, k.f.titel);
        zugBeginnt({ art: 'flaeche', id: k.f.id });
      }}
      onDragEnd={() => p.onZiehEnde?.()}
    >
      <span class="os-kachel-bild">
        <Symbol id={k.f.id} gruppe={k.f.gruppe} />
      </span>
      <span class="leading-tight">{k.f.titel}</span>
      <Show when={p.offen(k.f.id)}>
        <span class="text-[11px] text-(--color-fg-muted)">offen</span>
      </Show>
    </button>
  );

  return (
    <div class="mx-auto flex min-h-full w-full max-w-5xl flex-col gap-8 px-6 py-10 max-sm:px-4" data-startbildschirm>
      <header>
        <h1 class="m-0 text-3xl font-semibold tracking-tight">{systemName()}</h1>
        <p class="mt-1 text-sm text-(--color-fg-muted)">Alle Flächen und Apps. Mit ⌘K suchst du, mit ⌘J fragst du den Agenten.</p>
      </header>
      <Show when={angeheftet().length}>
        <section aria-label="Angeheftet">
          <h2 class="os-titel mb-2.5">Angeheftet</h2>
          <div class="grid grid-cols-[repeat(auto-fill,minmax(5.75rem,1fr))] gap-x-1 gap-y-3">
            <For each={angeheftet()}>{(f) => <Kachel f={f} />}</For>
          </div>
        </section>
      </Show>
      <For each={p.gruppen}>
        {(g) => (
          <section aria-label={g.gruppe}>
            <h2 class="os-titel mb-2.5">{g.gruppe}</h2>
            <div class="grid grid-cols-[repeat(auto-fill,minmax(5.75rem,1fr))] gap-x-1 gap-y-3">
              <For each={g.flaechen}>{(f) => <Kachel f={f} />}</For>
            </div>
          </section>
        )}
      </For>
    </div>
  );
}
