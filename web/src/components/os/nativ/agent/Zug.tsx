/**
 * Zug — des Agenten Antwort auf eine Nachricht: oben die Arbeitszeile (einklappbar), darunter die Antwort als Sprechblase.
 * Die Antwort ist der Text nach der Arbeit und das Auffälligste am Zug. `AutonomZeile` ist dasselbe für des Agenten
 * eigenständige Arbeit (Eingang, Takt, Lauf): eine dezente Zeile, die sich aufklappen lässt.
 */
import { Show, createUniqueId, type JSX } from 'solid-js';
import { uhrzeitKurz } from '~/lib/agent-runner/text';
import { dauerText, hatArbeit, schrittWort, zugDauer, type VerlaufsPunkt, type Zug } from '~/lib/agent-runner/verlauf';
import type { Aufklapp } from './aufklappen';
import { Arbeitszeile } from './Arbeitszeile';
import { FOKUS, Text } from './gemeinsam';

export function ZugBlock(p: { z: Zug; jetzt: number; offen: Aufklapp; kompakt?: boolean }): JSX.Element {
  const leer = () => !hatArbeit(p.z) && !p.z.antwort;
  return (
    <Show when={!leer()}>
      <div
        class="flex min-w-0 max-w-full flex-col items-start gap-1.5 self-start"
        data-art="zug"
        data-laeuft={p.z.laeuft || undefined}
        aria-busy={p.z.laeuft || undefined}
      >
        <Show when={!p.kompakt}>
          <span class="px-1 text-[0.7rem] font-semibold text-(--color-fg-muted)">
            {p.z.name}
            <Show when={p.z.zeit}> · {uhrzeitKurz(p.z.zeit)}</Show>
            <Show when={p.z.schreibt && p.z.antwort}> · schreibt …</Show>
          </span>
        </Show>
        <Show when={hatArbeit(p.z)}>
          <Arbeitszeile z={p.z} jetzt={p.jetzt} offen={p.offen} />
        </Show>
        <Show when={p.z.antwort}>
          <div
            class="min-w-0 max-w-[min(46rem,100%)] rounded-[18px] rounded-bl-md bg-[color-mix(in_oklab,var(--color-fg)_9%,transparent)] px-4 py-3 select-text"
            data-antwort
          >
            <Text text={p.z.antwort} />
            <Show when={p.z.verbrauch && !p.kompakt}>
              <span class="mt-1.5 block text-[0.68rem] text-(--color-fg-subtle)">Token: {p.z.verbrauch}</span>
            </Show>
          </div>
        </Show>
      </div>
    </Show>
  );
}

type Autonom = Extract<VerlaufsPunkt, { art: 'autonom' }>;

/** die eigenständige Arbeit des Agenten: eine dezente Zeile, kein Gespräch. Aufgeklappt: der Anlass und der Zug dazu. */
export function AutonomZeile(p: { a: Autonom; jetzt: number; offen: Aufklapp }): JSX.Element {
  const key = () => `${p.a.schluessel}:autonom`;
  const auf = () => p.offen.ist(key());
  const id = createUniqueId();
  const zusammen = () => {
    const z = p.a.zug;
    if (!z) return 'wartet auf Agent';
    if (z.laeuft) return 'Agent arbeitet …';
    const teile = [z.schrittZahl ? schrittWort(z.schrittZahl) : 'erledigt', dauerText(zugDauer(z, p.jetzt))];
    if (z.fehlerZahl) teile.push(z.fehlerZahl === 1 ? '1 Fehler' : `${z.fehlerZahl} Fehler`);
    return teile.filter(Boolean).join(' · ');
  };
  return (
    <div class="min-w-0 self-stretch text-(--color-fg-muted)" data-art="autonom" data-laeuft={p.a.zug?.laeuft || undefined}>
      <button
        type="button"
        aria-expanded={auf()}
        aria-controls={id}
        class={`flex min-h-8 w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-xs hover:bg-[color-mix(in_oklab,var(--color-fg)_6%,transparent)] ${FOKUS}`}
        onClick={() => p.offen.umschalten(key())}
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5 shrink-0 opacity-70" classList={{ 'motion-safe:animate-spin': !!p.a.zug?.laeuft }}>
          <path d="M13 8a5 5 0 1 1-1.5-3.55M13 2.5v2.5h-2.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span class="shrink-0 font-semibold">{p.a.quelle}</span>
        <span class="min-w-0 flex-1 truncate">{p.a.text}</span>
        <span class="shrink-0 tabular-nums text-(--color-fg-subtle)">{zusammen()}</span>
        <Show when={p.a.zeit}>
          <span class="hidden shrink-0 tabular-nums text-(--color-fg-subtle) @lg:inline">{uhrzeitKurz(p.a.zeit)}</span>
        </Show>
      </button>
      <Show when={auf()}>
        <div id={id} class="mt-1 ml-3.5 flex flex-col gap-2 border-l border-(--color-border) pl-3">
          <p class="m-0 text-xs leading-snug whitespace-pre-wrap break-words">{p.a.text}</p>
          <Show when={p.a.zug}>{(z) => <ZugBlock z={z()} jetzt={p.jetzt} offen={p.offen} kompakt />}</Show>
        </div>
      </Show>
    </div>
  );
}
