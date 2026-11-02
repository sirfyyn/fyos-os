/**
 * WartetKarte — ein Eintrag aus `wartet.eingang` als Karte (Schublade „Wartet auf dich“, OS-Neubau P2).
 *
 * Oben Quelle und Alter, rechts umkehrbar/zerstörerisch; dann der Satz, Warum und Wirkung, dann die Knöpfe, die der
 * Eintrag anbietet. Runner-Freigaben zeigt die Schublade mit der bestehenden `FreigabeKarte`; diese Karte ist für
 * Vorgänge, Entscheidungen und Kalendervorschläge. Nicht Umkehrbares erlaubt nur Halten (`WartetHalten`).
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { KNOPF, KNOPF_VOLL } from '~/components/zentrale/bausteine';
import { Marke } from '~/components/os/nativ/agent/gemeinsam';
import { QUELLE_NAME, seitText, type WartetAktion, type WartetEintrag } from '~/lib/os/wartet';
import { WartetHalten } from './WartetHalten';
import { tr } from '~/lib/i18n';

const KARTE =
  'min-w-0 rounded-2xl border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_4.5%,transparent)] p-4 flex flex-col gap-2.5 transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none';
const KARTE_ROT = 'border-(--color-error)/45 bg-[color-mix(in_oklab,var(--color-error)_7%,transparent)]';
const CHIP =
  'rounded-md border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_6%,transparent)] px-1.5 py-px font-mono text-[0.7rem] text-(--color-fg-muted)';

export function knopfText(e: WartetEintrag, a: WartetAktion): string {
  if (a === 'ja') {
    if (e.quelle === 'kalender') return 'Eintragen';
    return e.art === 'freigabe' ? (e.zerstoererisch ? tr('Halten zum Erlauben') : tr('Erlauben')) : 'Ja';
  }
  if (a === 'nein') {
    if (e.quelle === 'wache') return 'Erledigt';
    return e.quelle === 'kalender' ? tr('Verwerfen') : e.art === 'freigabe' ? tr('Ablehnen') : tr('Nein');
  }
  return { immer: 'Immer erlauben', spaeter: 'Später', oeffnen: 'Öffnen' }[a];
}

export function WartetKarte(p: {
  e: WartetEintrag;
  antworte: (e: WartetEintrag, a: WartetAktion, mehr?: { bestaetigt?: boolean }) => Promise<void>;
}): JSX.Element {
  const [arbeitet, setArbeitet] = createSignal<WartetAktion | null>(null);
  const [fehler, setFehler] = createSignal('');
  const los = async (a: WartetAktion, mehr?: { bestaetigt?: boolean }) => {
    setArbeitet(a);
    setFehler('');
    try {
      await p.antworte(p.e, a, mehr);
    } catch (f) {
      setFehler(f instanceof Error ? f.message : String(f));
    } finally {
      setArbeitet(null);
    }
  };
  const herkunft = () => {
    const teile = [p.e.gespraech ? tr('Gespräch „{0}“', p.e.gespraech) : '', seitText(p.e.seit)].filter(Boolean);
    return teile.join(' · ');
  };
  const knoepfe = () => p.e.aktionen;
  return (
    <article
      class={`${KARTE} ${p.e.zerstoererisch ? KARTE_ROT : ''}`}
      classList={{ 'opacity-60': arbeitet() != null }}
      data-wartet={p.e.id}
      aria-label={p.e.satz}
    >
      <div class="flex items-center justify-between gap-2 text-[0.72rem] text-(--color-fg-muted)">
        <span class="flex min-w-0 items-center gap-1.5 truncate">
          <span class={CHIP}>{QUELLE_NAME[p.e.quelle]}</span>
          <Show when={herkunft()}>
            <span class="truncate">· {herkunft()}</span>
          </Show>
        </span>
        <Show when={p.e.zerstoererisch} fallback={<span>{tr('umkehrbar')}</span>}>
          <Marke ton="fehler">{tr('zerstörerisch')}</Marke>
        </Show>
      </div>
      <h3 class="m-0 text-[0.98rem] font-semibold leading-snug text-(--color-fg)">{p.e.satz}</h3>
      <dl class="m-0 grid grid-cols-[4.5rem_1fr] gap-x-3 gap-y-1 text-[0.82rem] leading-snug">
        <Show when={p.e.warum}>
          <dt class="text-(--color-fg-muted)">{tr('Warum')}</dt>
          <dd class="m-0 text-(--color-fg)">{p.e.warum}</dd>
        </Show>
        <Show when={p.e.wirkung}>
          <dt class="text-(--color-fg-muted)">{tr('Wirkung')}</dt>
          <dd class="m-0" classList={{ 'text-(--color-error)': p.e.zerstoererisch, 'text-(--color-fg)': !p.e.zerstoererisch }}>
            {p.e.wirkung}
          </dd>
        </Show>
      </dl>
      <Show when={p.e.regel}>
        <p class="m-0 text-xs text-(--color-fg-muted)">{tr('Stehende Regel:')}{' '}{p.e.regel?.satz ?? 'immer ja'}</p>
      </Show>
      <div class="flex flex-wrap gap-2 pt-0.5">
        <For each={knoepfe()}>
          {(a) => (
            <Show
              when={a === 'ja' && p.e.zerstoererisch}
              fallback={
                <button
                  type="button"
                  class={a === 'ja' ? KNOPF_VOLL : KNOPF}
                  disabled={arbeitet() != null}
                  aria-busy={arbeitet() === a}
                  onClick={() => void los(a)}
                >
                  {knopfText(p.e, a)}
                </button>
              }
            >
              <WartetHalten
                class={`${KNOPF} border-(--color-error)/60`}
                disabled={arbeitet() != null}
                onFertig={() => void los('ja', { bestaetigt: true })}
              >
                {knopfText(p.e, a)}
              </WartetHalten>
            </Show>
          )}
        </For>
      </div>
      <Show when={fehler()}>
        <p role="alert" class="m-0 rounded-lg bg-(--color-warn-soft) px-2.5 py-1.5 text-xs text-(--color-fg)">
          {fehler()}
        </p>
      </Show>
    </article>
  );
}
