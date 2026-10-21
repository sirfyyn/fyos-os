/**
 * Räume ein- und ausschalten und ordnen. Steht im Raum Einstellungen unter „Räume und Dock“
 * und im Fenster nativ:einstellungen, damit sich die Räume auch ohne sie einschalten lassen.
 */
import { For, Show, type JSX } from 'solid-js';
import { agentName } from '~/lib/config';
import { RAEUME, einschalten, ordnungZuruecksetzen, raeume, raeumeSetzen, raumZu, verschieben, type RaumId } from '~/lib/os/raeume';
import { KNOPF_LEISE, SchalterZeile, Zeile } from './bausteine';

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
        unter={`Links die Räume-Leiste: Zentrale als Heimat, darunter die Räume, unten ${agentName()} und Einstellungen. Von selbst an; wer sie ausschaltet, hat in diesem Browser wieder die Arbeitsbildschirme allein.`}
        an={z().an}
        onKlick={() => raeumeSetzen(einschalten(z(), !z().an))}
      />
      <Show when={z().an}>
        <Zeile titel="Reihenfolge" unter="Zentrale bleibt oben, Einstellungen unten. Im Raum wechselt ⌥⌘← und ⌥⌘→, ⌘0 führt heim." darunter>
          <ol class="m-0 flex list-none flex-col gap-1 p-0">
            <For each={gebaute()}>
              {(id) => (
                <li class="flex items-center gap-2 rounded-lg px-2 py-1 text-sm">
                  <span class="flex-1">{raumZu(id)?.name}</span>
                  {pfeil(id, -1, 'nach oben')}
                  {pfeil(id, 1, 'nach unten')}
                </li>
              )}
            </For>
          </ol>
          <button type="button" class={`${KNOPF_LEISE} mt-1`} onClick={() => raeumeSetzen(ordnungZuruecksetzen(z()))}>
            Grundordnung
          </button>
        </Zeile>
      </Show>
      {/* Sind alle Räume gebaut, fehlt die Zeile; sie kommt wieder, sobald ein neuer Raum im Bau ist */}
      <Show when={geplante().length > 0}>
        <Zeile titel="Noch im Bau" unter="Diese Räume kommen mit ihrem Bau in die Leiste.">
          <p class={`m-0 ${GEDAEMPFT}`}>{geplante().map((r) => r.name).join(', ')}</p>
        </Zeile>
      </Show>
    </div>
  );
}
