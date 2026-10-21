/**
 * Räume-Leiste: links allein, Zentrale oben als Heimat (⌘0), die gebauten Räume darunter, unten der Agent (⌘J) und die
 * Einstellungen. Die Leiste des Raums selbst steht rechts (components/os/Raum.tsx).
 */
import { For, Show, type JSX } from 'solid-js';
import { agentName } from '~/lib/config';
import { leiste, type RaeumeZustand, type RaumId } from '~/lib/os/raeume';
import { mod } from '~/lib/os/menue';

const KNOPF =
  'flex size-11 items-center justify-center rounded-xl transition-colors duration-150 ease-out focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)';

export default function RaeumeLeiste(p: {
  zustand: RaeumeZustand;
  onRaum: (id: RaumId) => void;
  /** Das Agent-Dock ist offen */
  agentAn: boolean;
  onAgent: () => void;
}): JSX.Element {
  const eintraege = () => leiste(p.zustand);
  const oben = () => eintraege().filter((r) => r.fest !== 'unten');
  const unten = () => eintraege().filter((r) => r.fest === 'unten');
  const anfangsbuchstabe = () => agentName().trim().charAt(0).toUpperCase() || 'A';
  const knopf = (r: ReturnType<typeof eintraege>[number]) => {
    const an = () => p.zustand.aktiv === r.id;
    const taste = r.id === 'zentrale' ? ` (${mod('0')})` : r.id === 'einstellungen' ? ` (${mod(',')})` : '';
    return (
      <button
        type="button"
        data-raum={r.id}
        aria-label={r.name}
        aria-current={an() ? 'page' : undefined}
        title={`${r.name}${taste}: ${r.zweck}`}
        class={KNOPF}
        classList={{
          'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)': an(),
          'text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] hover:text-(--color-fg)': !an(),
        }}
        onClick={() => p.onRaum(r.id)}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d={r.d} />
        </svg>
      </button>
    );
  };
  return (
    <nav
      aria-label="Räume"
      data-raeume-leiste
      class="os-glas os-glas-tief z-[7] my-3 ml-3 flex w-16 shrink-0 flex-col items-center gap-1.5 overflow-y-auto py-3"
    >
      <For each={oben()}>
        {(r, i) => (
          <>
            {knopf(r)}
            <Show when={i() === 0 && oben().length > 1}>
              <span aria-hidden="true" class="my-1 h-px w-7 bg-(--color-border)" />
            </Show>
          </>
        )}
      </For>
      <span aria-hidden="true" class="flex-1" />
      <button
        type="button"
        data-raum-agent
        aria-label={`${agentName()} fragen (${mod('J')})`}
        aria-pressed={p.agentAn}
        title={`${agentName()} fragen (${mod('J')}): sieht Raum, Auswahl und offene Fenster`}
        class="flex size-10 items-center justify-center rounded-full bg-(--color-accent) text-[15px] font-bold text-(--color-bg) shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-accent)_25%,transparent)] transition-shadow duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
        classList={{ 'shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-accent)_60%,transparent)]': p.agentAn }}
        onClick={() => p.onAgent()}
      >
        {anfangsbuchstabe()}
      </button>
      <span aria-hidden="true" class="my-1 h-px w-7 bg-(--color-border)" />
      <For each={unten()}>{(r) => knopf(r)}</For>
    </nav>
  );
}
