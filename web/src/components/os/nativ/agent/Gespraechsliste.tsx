/**
 * Gespraechsliste — die Gespräche des Runners; ein Klick macht eines zum Fokus. Pfeiltasten gehen durch die Liste.
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { fehlerText } from '~/lib/agent-runner/text';
import type { Gespraech } from '~/lib/agent-runner/typen';
import { Fehler, FOKUS, KNOPF, Leer } from './gemeinsam';
import { tr } from '~/lib/i18n';

const ART: Record<string, string> = { root: 'Haupt', mensch: '', zweig: 'Zweig', lauf: 'Lauf' };

export function Gespraechsliste(p: {
  gespraeche: Gespraech[];
  fokus: number | null;
  waehle: (id: number) => void;
  neu: () => Promise<unknown>;
}): JSX.Element {
  const [fehler, setFehler] = createSignal('');
  const [arbeitet, setArbeitet] = createSignal(false);
  let liste: HTMLUListElement | undefined;

  const sichtbar = () => p.gespraeche.filter((g) => !g.archiviert);

  const taste = (e: KeyboardEvent) => {
    const knoepfe = [...(liste?.querySelectorAll<HTMLButtonElement>('button[data-gespraech]') ?? [])];
    const i = knoepfe.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0) return;
    const ziel = e.key === 'ArrowDown' ? i + 1 : e.key === 'ArrowUp' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? knoepfe.length - 1 : -1;
    if (ziel < 0) return;
    e.preventDefault();
    knoepfe[Math.max(0, Math.min(knoepfe.length - 1, ziel))]?.focus();
  };

  const neu = async () => {
    setArbeitet(true);
    setFehler('');
    try {
      await p.neu();
    } catch (f) {
      setFehler(fehlerText(f));
    } finally {
      setArbeitet(false);
    }
  };

  return (
    <nav aria-label={tr('Gespräche')} class="flex min-h-0 flex-col gap-2">
      <button type="button" class={KNOPF} disabled={arbeitet()} aria-busy={arbeitet()} onClick={() => void neu()}>
        {arbeitet() ? tr('Lege an …') : tr('Neues Gespräch')}
      </button>
      <Show when={fehler()}>
        <Fehler text={fehler()} />
      </Show>
      <ul ref={liste} class="m-0 flex min-h-0 list-none flex-col gap-0.5 overflow-y-auto overscroll-contain p-0" onKeyDown={taste}>
        <For each={sichtbar()} fallback={<li><Leer>{tr('Noch kein Gespräch.')}</Leer></li>}>
          {(g) => (
            <li>
              <button
                type="button"
                data-gespraech={g.id}
                class={`flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-left text-sm hover:bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] ${FOKUS}`}
                classList={{ 'bg-[color-mix(in_oklab,var(--color-accent)_16%,transparent)] font-semibold': g.id === p.fokus }}
                aria-current={g.id === p.fokus ? 'true' : undefined}
                onClick={() => p.waehle(g.id)}
              >
                <span class="min-w-0 flex-1 truncate">{g.titel || tr('Gespräch {0}', g.id)}</span>
                <Show when={ART[g.art]}>
                  <span class="shrink-0 text-[0.7rem] text-(--color-fg-subtle)">{ART[g.art]}</span>
                </Show>
              </button>
            </li>
          )}
        </For>
      </ul>
    </nav>
  );
}
