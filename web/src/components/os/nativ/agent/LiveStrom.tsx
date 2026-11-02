/**
 * LiveStrom — die eigenständige Arbeit des Agenten über alle Gespräche (GET api/strom). Live ist die Voreinstellung; der Ruhe-Schalter
 * im Kopf und `/live` blenden nur die ANZEIGE aus, der Agent merkt nichts. Ein Klick auf eine Zeile verschiebt den Fokus
 * (welches Gespräch groß ist).
 *
 * Breit eine Spalte neben dem Gespräch, schmal (Dock-Panel, Handy) eine dezente Aktivitätsleiste („Agent arbeitet an … “),
 * die sich zur ganzen Liste aufklappen lässt.
 */
import { For, Show, createEffect, createSignal, on, onCleanup, onMount, type JSX } from 'solid-js';
import type { StromZustand } from '~/lib/agent-runner/strom';
import { aktivitaet, stromAktiv, stromKlartext } from '~/lib/agent-runner/strom';
import { uhrzeitKurz, vor } from '~/lib/agent-runner/text';
import type { StromZeile } from '~/lib/agent-runner/typen';
import { FOKUS, KNOPF, Punkt } from './gemeinsam';
import { tr } from '~/lib/i18n';

const ton = (typ: string): 'ok' | 'warn' | 'fehler' | 'aus' => (typ === 'fehler' ? 'fehler' : typ === 'freigabe' ? 'warn' : typ === 'fertig' ? 'ok' : 'aus');
const ART: Record<string, string> = {
  eingang: 'Eingang',
  mensch: 'du',
  sagt: 'Agent',
  werkzeug: 'Werkzeug',
  fehler: 'Fehler',
  freigabe: 'Freigabe',
  lauf: 'Lauf',
  schritt: 'Schritt',
  fertig: 'Fertig',
};

function Zeilen(p: { strom: StromZustand; fokus: number | null; waehle: (id: number) => void; hoehe?: string }): JSX.Element {
  let liste: HTMLOListElement | undefined;
  let unten = true;
  createEffect(
    on(
      () => p.strom.zeilen.length,
      () => queueMicrotask(() => unten && liste?.scrollTo({ top: liste.scrollHeight })),
    ),
  );
  return (
    <ol
      ref={liste}
      role="log"
      aria-label={tr('Autonome Arbeit')}
      class={`m-0 flex min-h-0 list-none flex-col gap-0.5 overflow-y-auto overscroll-contain p-0 ${p.hoehe ?? 'flex-1'}`}
      onScroll={(e) => (unten = e.currentTarget.scrollHeight - e.currentTarget.scrollTop - e.currentTarget.clientHeight < 60)}
    >
      <For
        each={p.strom.zeilen}
        fallback={<li class="px-2 py-6 text-center text-sm text-(--color-fg-muted)">{tr('Gerade ruhig. Neue Arbeit erscheint hier von selbst.')}</li>}
      >
        {(z: StromZeile) => (
          <li>
            <button
              type="button"
              class={`flex min-h-9 w-full items-start gap-2 rounded-lg px-2 py-1 text-left text-[0.8rem] leading-snug hover:bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] ${FOKUS}`}
              classList={{ 'bg-[color-mix(in_oklab,var(--color-accent)_14%,transparent)]': z.gespraech === p.fokus }}
              aria-current={z.gespraech === p.fokus ? 'true' : undefined}
              title={tr('{0} · Klick: Fokus hierher', z.titel ?? tr('Gespräch {0}', z.gespraech))}
              data-typ={z.typ}
              onClick={() => p.waehle(z.gespraech)}
            >
              <span class="mt-1.5 shrink-0">
                <Punkt ton={ton(z.typ)} />
              </span>
              <span class="shrink-0 pt-px text-[0.72rem] text-(--color-fg-subtle) tabular-nums">{uhrzeitKurz(z.t)}</span>
              <span class="min-w-0 flex-1 break-words">
                <Show when={z.gespraech !== p.fokus && z.titel}>
                  <span class="text-(--color-fg-muted)">{z.titel} · </span>
                </Show>
                <span class="text-(--color-fg-subtle)">{ART[z.typ] ?? z.typ} · </span>
                {stromKlartext(z)}
              </span>
            </button>
          </li>
        )}
      </For>
    </ol>
  );
}

function useJetzt(): () => number {
  const [jetzt, setJetzt] = createSignal(Date.now());
  onMount(() => {
    const t = setInterval(() => setJetzt(Date.now()), 10_000);
    onCleanup(() => clearInterval(t));
  });
  return jetzt;
}

interface Gemeinsam {
  strom: StromZustand;
  live: boolean;
  status: string;
  fokus: number | null;
  agentName: string;
  setze: (an: boolean) => void;
  waehle: (id: number) => void;
}

export function LiveSpalte(p: Gemeinsam): JSX.Element {
  const jetzt = useJetzt();
  return (
    <section aria-label={tr('Live')} class="flex min-h-0 flex-col gap-2 rounded-2xl border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_3.5%,transparent)] p-2" data-live-spalte>
      <header class="flex flex-wrap items-center justify-between gap-2 px-1">
        <h2 class="os-titel m-0">{tr('Autonome Arbeit')}</h2>
      </header>
      <Show
        when={p.live}
        fallback={
          <div class="flex flex-col items-center gap-2 px-2 py-6 text-center">
            <p class="m-0 text-sm text-(--color-fg-muted)">
              Ruhe: {p.agentName}s eigenständige Arbeit ist ausgeblendet. Sie arbeitet unverändert weiter.
            </p>
            <button type="button" class={KNOPF} onClick={() => p.setze(true)}>
              {tr('Einblenden')}
            </button>
          </div>
        }
      >
        <Zeilen strom={p.strom} fokus={p.fokus} waehle={p.waehle} />
        <p class="m-0 px-1 text-xs text-(--color-fg-subtle)" role="status">
          {p.status === 'offen' ? (p.strom.letzte ? tr('zuletzt {0}', vor(p.strom.letzte, jetzt())) + (stromAktiv(p.strom, jetzt()) ? tr(' · aktiv') : '') : tr('verbunden')) : p.status === 'aus' ? '' : tr('verbinde …')}
        </p>
      </Show>
    </section>
  );
}

/** Die dezente Leiste über dem Gespräch: eine Zeile „Agent arbeitet an … “, aufklappbar zur Liste. */
export function LiveStreifen(p: Gemeinsam): JSX.Element {
  const [offen, setOffen] = createSignal(false);
  const jetzt = useJetzt();
  const akt = () => aktivitaet(p.strom, p.agentName, jetzt());
  return (
    <Show
      when={p.live}
      fallback={
        <div class="flex items-center gap-2 px-2 text-xs text-(--color-fg-subtle)" data-live-streifen="ruhe">
          <span class="min-w-0 flex-1 truncate">{tr('Ruhe: eigenständige Arbeit ausgeblendet')}</span>
          <button type="button" class={`rounded-md px-1.5 py-0.5 text-(--color-accent) hover:underline ${FOKUS}`} onClick={() => p.setze(true)}>
            {tr('Einblenden')}
          </button>
        </div>
      }
    >
      <section aria-label={tr('Live')} class="flex flex-col gap-1 rounded-xl border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_3%,transparent)] p-0.5" data-live-streifen>
        <button
          type="button"
          class={`flex min-h-7 min-w-0 items-center gap-2 rounded-lg px-2 text-left text-xs text-(--color-fg-muted) ${FOKUS}`}
          aria-expanded={offen()}
          onClick={() => setOffen((o) => !o)}
        >
          <Punkt ton={akt().aktiv ? 'ok' : 'aus'} />
          <span class="min-w-0 flex-1 truncate" role="status" data-aktivitaet>
            {p.status === 'verbinde' && !p.strom.letzte ? 'verbinde …' : akt().text}
          </span>
          <Show when={akt().zeile}>
            <span class="shrink-0 text-(--color-fg-subtle)">{vor(akt().zeile!.t, jetzt())}</span>
          </Show>
          <span aria-hidden="true">{offen() ? '▴' : '▾'}</span>
        </button>
        <Show when={offen()}>
          <Zeilen
            strom={p.strom}
            fokus={p.fokus}
            waehle={(id) => {
              setOffen(false);
              p.waehle(id);
            }}
            hoehe="max-h-44"
          />
        </Show>
      </section>
    </Show>
  );
}
