/**
 * Freigaben — die Liste: offene zuerst („Wartet auf dich“), darunter die zuletzt entschiedenen.
 * Nur Destruktives geht durch eine Freigabe, und sie liegt im Runner, nicht im ITSM.
 * Die Karte selbst ist FreigabeKarte (dieselbe steht auch im Verlauf).
 */
import { For, Show, type JSX } from 'solid-js';
import { istOffen } from '~/lib/agent-runner/freigaben';
import type { Freigabe } from '~/lib/agent-runner/typen';
import { FreigabeKarte } from './FreigabeKarte';
import { Fehler, Laedt, Leer } from './gemeinsam';

export function Freigaben(p: {
  freigaben: Freigabe[];
  geladen: boolean;
  fehler: string | null;
  entscheide: (id: string, e: 'erteilt' | 'abgelehnt') => Promise<void>;
  erneut: () => void;
}): JSX.Element {
  const offen = () => p.freigaben.filter(istOffen);
  const erledigt = () => p.freigaben.filter((f) => !istOffen(f)).slice(0, 10);
  return (
    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-0.5" data-tab="freigaben">
      <Show when={p.fehler}>
        <Fehler text={`Freigaben nicht abrufbar: ${p.fehler}`} nochmal={p.erneut} />
      </Show>
      <Show when={p.geladen || p.fehler} fallback={<Laedt text="Freigaben werden geladen" />}>
        <Show when={offen().length} fallback={<Leer>Keine offene Freigabe. Was zerstören könnte, fragt hier zuerst.</Leer>}>
          <section aria-label="Offene Freigaben" class="flex flex-col gap-2">
            <h2 class="os-titel m-0 px-1">Wartet auf dich ({offen().length})</h2>
            <For each={offen()}>{(f) => <FreigabeKarte f={f} entscheide={p.entscheide} />}</For>
          </section>
        </Show>
        <Show when={erledigt().length}>
          <section aria-label="Entschiedene Freigaben" class="flex flex-col gap-2">
            <h2 class="os-titel m-0 px-1">Zuletzt entschieden</h2>
            <For each={erledigt()}>{(f) => <FreigabeKarte f={f} entscheide={p.entscheide} />}</For>
          </section>
        </Show>
      </Show>
    </div>
  );
}
