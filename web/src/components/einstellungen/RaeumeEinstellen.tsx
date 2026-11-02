/**
 * Räume ein- und ausschalten und ordnen. Steht im Raum Einstellungen unter „Räume und Dock“
 * und im Fenster nativ:einstellungen, damit sich die Räume auch ohne sie einschalten lassen.
 */
import { For, Show, type JSX } from 'solid-js';
import { agentName } from '~/lib/config';
import {
  RAEUME,
  ausblendGrund,
  ausblenden,
  einschalten,
  leereAusblenden,
  ordnungZuruecksetzen,
  raeume,
  raeumeSetzen,
  raumZu,
  verschieben,
  type RaumId,
} from '~/lib/os/raeume';
import { verfuegbar } from '~/lib/os/raeume-inhalt';
import { KNOPF_LEISE, SchalterZeile, Zeile } from './bausteine';
import { tr } from '~/lib/i18n';

const GEDAEMPFT = 'text-sm leading-snug text-(--color-fg-muted)';

export default function RaeumeEinstellen(): JSX.Element {
  const z = () => raeume();
  const gebaute = () => z().reihenfolge.filter((id) => raumZu(id)?.gebaut);
  const geplante = () => RAEUME.filter((r) => !r.gebaut);
  const pfeil = (id: RaumId, richtung: 1 | -1, text: string) => {
    const l = gebaute();
    const i = l.indexOf(id);
    const aus = richtung === -1 ? i <= 0 : i >= l.length - 1;
    return (
      <button
        type="button"
        class={KNOPF_LEISE}
        disabled={aus}
        aria-label={`${raumZu(id)?.name} ${text}`}
        onClick={() => raeumeSetzen(verschieben(z(), id, richtung))}
      >
        {richtung === -1 ? '↑' : '↓'}
      </button>
    );
  };
  return (
    <div data-raeume-einstellen>
      <SchalterZeile
        name="Räume"
        unter={tr('Links die Räume-Leiste: Zentrale als Heimat, darunter die Räume, unten {0} und Einstellungen. Von selbst an; wer sie ausschaltet, hat in diesem Browser wieder die Arbeitsbildschirme allein.', agentName())}
        an={z().an}
        onKlick={() => raeumeSetzen(einschalten(z(), !z().an))}
      />
      <Show when={z().an}>
        <SchalterZeile
          name={tr('Leere Räume ausblenden')}
          unter={tr('Ein Raum, für den kein Plugin im Hub etwas liefert (etwa Zuhause ohne Haus-Plugin), steht dann nicht in der Leiste. Kommt das Plugin dazu, erscheint er wieder.')}
          an={z().leereAus}
          onKlick={() => raeumeSetzen(leereAusblenden(z(), !z().leereAus))}
        />
        <Zeile titel={tr('Reihenfolge')} unter={tr('Zentrale bleibt oben, Einstellungen unten. Im Raum wechselt ⌥⌘← und ⌥⌘→, ⌘0 führt heim. Einzelne Räume lassen sich ausblenden.')} darunter>
          <ol class="m-0 flex list-none flex-col gap-1 p-0">
            <For each={gebaute()}>
              {(id) => {
                const grund = () => ausblendGrund(z(), id, verfuegbar());
                return (
                  <li class="flex items-center gap-2 rounded-lg px-2 py-1 text-sm" data-raum-zeile={id} classList={{ 'opacity-60': grund() !== null }}>
                    <span class="flex-1">
                      {raumZu(id)?.name}
                      <Show when={grund()}>
                        {(g) => (
                          <span class={`ml-2 ${GEDAEMPFT}`} data-raum-grund={g()}>
                            {g() === 'hand' ? 'ausgeblendet' : tr('kein Plugin dafür')}
                          </span>
                        )}
                      </Show>
                    </span>
                    <button
                      type="button"
                      class={KNOPF_LEISE}
                      aria-label={`${raumZu(id)?.name} ${z().ausgeblendet.includes(id) ? 'einblenden' : 'ausblenden'}`}
                      onClick={() => raeumeSetzen(ausblenden(z(), id, !z().ausgeblendet.includes(id)))}
                    >
                      {z().ausgeblendet.includes(id) ? tr('Einblenden') : tr('Ausblenden')}
                    </button>
                    {pfeil(id, -1, 'nach oben')}
                    {pfeil(id, 1, 'nach unten')}
                  </li>
                );
              }}
            </For>
          </ol>
          <button type="button" class={`${KNOPF_LEISE} mt-1`} onClick={() => raeumeSetzen(ordnungZuruecksetzen(z()))}>
            {tr('Grundordnung')}
          </button>
          <Show when={z().ausgeblendet.length > 0}>
            <button type="button" class={`${KNOPF_LEISE} mt-1 ml-2`} onClick={() => raeumeSetzen({ ...z(), ausgeblendet: [] })}>
              {tr('Alle einblenden')}
            </button>
          </Show>
        </Zeile>
      </Show>
      {/* Sind alle Räume gebaut, fehlt die Zeile; sie kommt wieder, sobald ein neuer Raum im Bau ist */}
      <Show when={geplante().length > 0}>
        <Zeile titel={tr('Noch im Bau')} unter={tr('Diese Räume kommen mit ihrem Bau in die Leiste.')}>
          <p class={`m-0 ${GEDAEMPFT}`}>{geplante().map((r) => r.name).join(', ')}</p>
        </Zeile>
      </Show>
    </div>
  );
}
