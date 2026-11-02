/**
 * Kopf — wer da ist und wie es ihm geht: Name, Zustand (bereit / arbeitet / wartet auf dich / pausiert), Modell,
 * der Ruhe-Schalter (blendet die eigenständige Arbeit des Agenten aus, wie /live aus) und die Zahl der Freigaben, die warten.
 */
import { Show, type JSX } from 'solid-js';
import { KOPF_TON, kopfStatus, kopfText } from '~/lib/agent-runner/status';
import { Punkt } from './gemeinsam';

export function Kopf(p: {
  agentName: string;
  geraet: string;
  schmal?: boolean;
  busy: boolean;
  offeneFreigaben: number;
  spielmodus: string | null;
  modell: string;
  live: boolean;
  /** Der Strom des offenen Gesprächs ist abgerissen und verbindet neu (erst nach dem ersten Laden). */
  getrennt: boolean;
  setzeLive: (an: boolean) => void;
  zurFreigabenListe: () => void;
}): JSX.Element {
  const status = () => kopfStatus({ busy: p.busy, offeneFreigaben: p.offeneFreigaben, spielmodus: p.spielmodus });
  const getrennt = () => p.getrennt;
  return (
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1" data-agent-kopf data-status={status()}>
      <div class="flex min-w-0 items-center gap-2">
        <Punkt ton={getrennt() ? 'fehler' : KOPF_TON[status()]} />
        <h1 class="m-0 min-w-0 truncate text-[0.98rem] font-semibold">
          {p.agentName}
          <Show when={p.geraet && !p.schmal}>
            <span class="font-normal text-(--color-fg-muted)"> · {p.geraet}</span>
          </Show>
        </h1>
        <span class="shrink-0 text-xs text-(--color-fg-muted)" role="status" data-kopf-status>
          {getrennt() ? 'Verbindung verloren' : kopfText(status(), p.spielmodus)}
        </span>
      </div>
      <div class="ml-auto flex min-w-0 flex-wrap items-center gap-1.5">
        <Show when={p.modell}>
          <span class="max-w-[12rem] truncate rounded-full bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] px-2.5 py-0.5 font-mono text-[0.7rem] text-(--color-fg-muted)" title={`Modell: ${p.modell}`} data-modell>
            {p.modell}
          </span>
        </Show>
        <Show when={p.offeneFreigaben > 0}>
          <button
            type="button"
            class="os-chip os-chip-fokus"
            onClick={() => p.zurFreigabenListe()}
            aria-label={`${p.offeneFreigaben} ${p.offeneFreigaben === 1 ? 'Freigabe' : 'Freigaben'} von Agent offen. Liste öffnen`}
            data-freigaben-badge
          >
            {/* Nur des Agenten eigene Freigaben; „wartet auf dich“ zählt allein die Menüleiste (wartet.eingang, OS-Neubau P2). */}
            <span aria-hidden="true">⚑</span> {p.offeneFreigaben} {p.offeneFreigaben === 1 ? 'Freigabe' : 'Freigaben'}
          </button>
        </Show>
        <button
          type="button"
          class={`os-chip ${p.live ? '' : 'os-chip-fokus'}`}
          aria-pressed={!p.live}
          title="Ruhe blendet die eigenständige Arbeit des Agenten (Takt, Eingänge, Läufe) aus. Sie arbeitet unverändert weiter (/live blendet wieder ein)."
          onClick={() => p.setzeLive(!p.live)}
          data-ruhe
        >
          <Punkt ton={p.live ? 'aus' : 'ok'} />
          Ruhe
        </button>
      </div>
    </header>
  );
}
