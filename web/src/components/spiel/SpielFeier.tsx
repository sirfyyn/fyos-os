/**
 * SpielFeier — die kleine Feier, wenn du Punkte bekommt (OS-Neubau P9). Unten rechts steigt „+25“ mit Funken auf und
 * verschwindet; bei einem Levelaufstieg springt die Pixel-Katze herein und zeigt, was sie freigeschaltet hat. Unterbricht
 * nie: kein Fokus, kein Ton von selbst, keine Rolle „alert“, prefers-reduced-motion ohne Bewegung.
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import PixelKatze from '~/components/ui/PixelKatze';
import { SPIEL_EREIGNIS, type SpielFeierDetail } from '~/lib/spiel';
import './spiel.css';
import { tr } from '~/lib/i18n';

const FREI_TEXT: Record<string, string> = {
  halsband: 'ein Halsband',
  brille: 'eine Brille',
  kissen: 'ein Kissen im Wohnzimmer',
  schal: 'einen Schal',
  laterne: 'eine Laterne',
  krone: 'eine Krone',
  dachboden: 'ein Zimmer auf dem Dachboden',
};

interface Feier extends SpielFeierDetail {
  id: number;
}

export default function SpielFeier(): JSX.Element {
  const [feiern, setFeiern] = createSignal<Feier[]>([]);
  let n = 0;
  onMount(() => {
    const neu = (e: Event) => {
      const d = (e as CustomEvent<SpielFeierDetail>).detail;
      if (!d) return;
      const id = ++n;
      setFeiern((f) => [...f.slice(-2), { ...d, id }]);
      setTimeout(() => setFeiern((f) => f.filter((x) => x.id !== id)), d.levelAuf ? 6500 : 2600);
    };
    window.addEventListener(SPIEL_EREIGNIS, neu);
    onCleanup(() => window.removeEventListener(SPIEL_EREIGNIS, neu));
  });
  return (
    <div class="spiel-feier" aria-live="polite" data-spiel-feier>
      <For each={feiern()}>
        {(f) => (
          <Show
            when={f.levelAuf}
            fallback={
              <div class="spiel-punkte">
                <span class="spiel-funken" aria-hidden="true"><i /><i /><i /><i /><i /></span>
                <b>+{f.punkte}</b>
                <span>{f.satz.replace(/^\+\d+ · /, '')}</span>
              </div>
            }
          >
            <div class="spiel-level">
              <PixelKatze taetigkeit="bereit" groesse={6} zubehoer={f.stand.freigeschaltet} />
              <div>
                <div class="spiel-level-titel">{tr('Level')}{' '}{f.stand.level} · {f.stand.name}</div>
                <div class="spiel-level-text">
                  +{f.punkte} · {f.freigeschaltet ? tr('Agent hat jetzt {0}.', FREI_TEXT[f.freigeschaltet] ? tr(FREI_TEXT[f.freigeschaltet]!) : f.freigeschaltet) : tr('Weiter so.')}
                </div>
                <Show when={f.abzeichen.length}>
                  <div class="spiel-level-text">{tr('Abzeichen:')}{' '}{f.abzeichen.map((a) => a.text).join(', ')}</div>
                </Show>
              </div>
            </div>
          </Show>
        )}
      </For>
    </div>
  );
}
