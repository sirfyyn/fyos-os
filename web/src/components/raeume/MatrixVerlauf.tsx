/**
 * Kanal-Verlauf im Raum Gespräch: die letzten Nachrichten eines erlaubten Matrix-Raums aus `chat.matrix_lesen`, ältere
 * oben wie in einem Chat. Nur lesen: geschrieben wird über den Agenten.
 *
 * Das Werkzeug liefert ein Plugin; fehlt es oder lässt der Hub den Browser nicht daran (403/404), steht
 * „Noch nicht eingerichtet.“ da. Warum nicht die Hub-App: ein Verlauf ist eine kleine Ansicht, keine eigene Oberfläche.
 */
import { For, Show, createResource, type JSX } from 'solid-js';
import { NichtEingerichtet } from '~/components/raeume/Huelle';
import { gesperrt } from '~/components/raeume/freigabe';
import { agentName } from '~/lib/config';
import { hub } from '~/lib/hub';

export interface MatrixNachricht {
  sender: string;
  ts: number;
  text: string;
}
interface Antwort {
  raum?: string;
  nachrichten?: MatrixNachricht[];
}

/** `@name:server.example` → `name` */
export const kurzName = (sender: string): string => sender.replace(/^@/, '').split(':')[0] || sender;

/** Älteste zuerst; ohne Text fliegt raus. */
export function ordne(n: MatrixNachricht[] | undefined): MatrixNachricht[] {
  return (n ?? []).filter((x) => x && typeof x.text === 'string' && x.text.trim()).sort((a, b) => a.ts - b.ts);
}

const zeit = (ts: number) =>
  new Date(ts).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

export default function MatrixVerlauf(): JSX.Element {
  const [daten, { refetch }] = createResource(() => hub<Antwort>('chat.matrix_lesen', { limit: 50 }));
  // Eine fehlgeschlagene Ressource wirft beim Lesen: nur lesen, wenn es etwas gibt
  const wert = () => (daten.state === 'ready' || daten.state === 'refreshing' ? daten() : undefined);
  const liste = () => ordne(wert()?.nachrichten);
  const zu = () => daten.state === 'errored' && gesperrt(daten.error);

  return (
    <div class="flex min-h-0 flex-1 flex-col" data-matrix-verlauf>
      <div class="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3">
        <h1 class="m-0 flex-1 text-base font-semibold text-(--color-fg)">Matrix{wert()?.raum ? ` · ${wert()?.raum}` : ''}</h1>
        <button type="button" class="os-knopf" aria-label="Neu laden" title="Neu laden" onClick={() => void refetch()}>
          ↻
        </button>
      </div>
      <div class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-3">
        <Show when={!zu()} fallback={<NichtEingerichtet detail="Das Werkzeug chat.matrix_lesen fehlt im Hub oder ist für den Browser nicht freigegeben." data-matrix-gesperrt />}>
          <Show when={!daten.error} fallback={<p role="status" class="text-sm text-(--color-warn)">Matrix ist gerade nicht erreichbar.</p>}>
            <Show when={wert()} fallback={<p role="status" class="text-sm text-(--color-fg-muted)">Lade …</p>}>
              <Show when={liste().length} fallback={<p class="text-sm text-(--color-fg-muted)">Noch keine Nachrichten.</p>}>
                <ol class="m-0 flex list-none flex-col gap-3 p-0">
                  <For each={liste()}>
                    {(n) => (
                      <li class="flex flex-col gap-0.5" data-matrix-nachricht>
                        <span class="text-[11px] text-(--color-fg-muted)">
                          <b class="font-semibold text-(--color-fg)">{kurzName(n.sender)}</b> · {zeit(n.ts)}
                        </span>
                        <span class="text-sm leading-relaxed whitespace-pre-wrap text-(--color-fg)">{n.text}</span>
                      </li>
                    )}
                  </For>
                </ol>
                <div ref={(el) => queueMicrotask(() => el.scrollIntoView?.({ block: 'end' }))} />
              </Show>
            </Show>
          </Show>
        </Show>
      </div>
      <p class="m-0 shrink-0 border-t border-(--color-border) px-4 py-2 text-[11px] text-(--color-fg-muted)">
        Nur lesen. Schreiben geht über {agentName()}.
      </p>
    </div>
  );
}
