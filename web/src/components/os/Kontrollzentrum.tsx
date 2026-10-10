/**
 * Kontrollzentrum — rechts oben in der Menüleiste, wie am Mac: Kacheln aus Glas für
 * Erscheinungsbild, Hintergrund, Farben, Stärke und Tempo der Kulisse, dazu „Alle
 * Einstellungen“. Alles wirkt sofort und bleibt gespeichert (lib/os/kulisse.ts, lib/os/thema.ts).
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { KULISSE_EREIGNIS, kulisseLaden, kulisseSpeichern, kulisseVon, type KulisseEinstellung, type KulisseFarben, type KulisseStil } from '~/lib/os/kulisse';
import { themaSetzen, themaWahl, type ThemaWahl } from '~/lib/os/thema';

const THEMEN: [ThemaWahl, string][] = [['light', 'Hell'], ['dark', 'Dunkel'], ['auto', 'Automatisch']];
const STILE: [KulisseStil, string][] = [['lava', 'Lava'], ['ruhig', 'Ruhig'], ['aus', 'Aus']];
const FARBEN: [KulisseFarben, string, string][] = [
  ['neon', 'Neon', 'linear-gradient(135deg,#22d3ee,#e879f9)'],
  ['aurora', 'Aurora', 'linear-gradient(135deg,#34d399,#6366f1)'],
  ['glut', 'Glut', 'linear-gradient(135deg,#fb7185,#f59e0b)'],
];

export default function Kontrollzentrum(p: { onSchliessen: () => void; einstellungenDa: boolean; onEinstellungen: () => void; x: number }): JSX.Element {
  const [k, setK] = createSignal<KulisseEinstellung>(kulisseLaden());
  const [thema, setThema] = createSignal<ThemaWahl>(themaWahl());
  let el: HTMLDivElement | undefined;

  /** Regler: beim Ziehen nur Vorschau (`vorschau`), gespeichert wird bei `change` (Loslassen) */
  const aendern = (teil: Partial<KulisseEinstellung>, vorschau = false) => {
    const neu = { ...k(), ...teil };
    setK(neu);
    kulisseSpeichern(neu, vorschau);
  };

  onMount(() => {
    const zu = (e: Event) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === 'Escape') p.onSchliessen();
        return;
      }
      const t = e.target as Element;
      if (el?.contains(t) || t.closest?.('[data-kz-knopf]')) return;
      p.onSchliessen();
    };
    const nach = (e: Event) => setK(kulisseVon(e));
    window.addEventListener('pointerdown', zu, true);
    window.addEventListener('keydown', zu);
    window.addEventListener(KULISSE_EREIGNIS, nach);
    queueMicrotask(() => el?.querySelector<HTMLElement>('button')?.focus());
    onCleanup(() => {
      window.removeEventListener('pointerdown', zu, true);
      window.removeEventListener('keydown', zu);
      window.removeEventListener(KULISSE_EREIGNIS, nach);
    });
  });

  return (
    <div
      ref={el}
      role="dialog"
      aria-label="Kontrollzentrum"
      class="os-kz os-menue"
      style={{ right: `${Math.max(8, p.x)}px` }}
    >
      <section class="os-kz-kachel">
        <p class="os-kz-titel">Erscheinungsbild</p>
        <div class="os-segment" role="radiogroup" aria-label="Erscheinungsbild">
          <For each={THEMEN}>
            {([w, text]) => (
              <button type="button" role="radio" aria-checked={thema() === w} classList={{ 'os-segment-an': thema() === w }} onClick={() => { themaSetzen(w); setThema(w); }}>
                {text}
              </button>
            )}
          </For>
        </div>
      </section>

      <section class="os-kz-kachel">
        <p class="os-kz-titel">Hintergrund</p>
        <div class="os-segment mb-3" role="radiogroup" aria-label="Hintergrund">
          <For each={STILE}>
            {([w, text]) => (
              <button type="button" role="radio" aria-checked={k().stil === w} classList={{ 'os-segment-an': k().stil === w }} onClick={() => aendern({ stil: w })}>
                {text}
              </button>
            )}
          </For>
        </div>
        <div class="flex items-center gap-3" role="radiogroup" aria-label="Farben">
          <For each={FARBEN}>
            {([w, text, verlauf]) => (
              <button type="button" role="radio" aria-checked={k().farben === w} aria-label={text} title={text} class="os-farbe" classList={{ 'os-farbe-an': k().farben === w }} style={{ background: verlauf }} onClick={() => aendern({ farben: w })} />
            )}
          </For>
          <span class="ml-auto text-xs text-(--color-fg-muted)">{FARBEN.find((f) => f[0] === k().farben)?.[1]}</span>
        </div>
      </section>

      <Show when={k().stil !== 'aus'}>
        <section class="os-kz-kachel space-y-2.5">
          <label class="os-regler">
            <span>Farbe</span>
            <input type="range" min="0" max="100" value={k().lava} onInput={(e) => aendern({ lava: Number(e.currentTarget.value) }, true)} onChange={(e) => aendern({ lava: Number(e.currentTarget.value) })} />
          </label>
          <label class="os-regler">
            <span>Raster</span>
            <input type="range" min="0" max="100" value={k().raster} onInput={(e) => aendern({ raster: Number(e.currentTarget.value) }, true)} onChange={(e) => aendern({ raster: Number(e.currentTarget.value) })} />
          </label>
          <label class="os-regler">
            <span>Glas</span>
            <input type="range" min="0" max="40" value={k().glas} onInput={(e) => aendern({ glas: Number(e.currentTarget.value) }, true)} onChange={(e) => aendern({ glas: Number(e.currentTarget.value) })} />
          </label>
        </section>
      </Show>

      <Show when={p.einstellungenDa}>
        <button type="button" class="os-menuepunkt px-3" onClick={() => { p.onSchliessen(); p.onEinstellungen(); }}>
          <span class="flex-1">Alle Einstellungen …</span>
          <span aria-hidden="true" class="text-(--color-fg-muted)">⌘,</span>
        </button>
      </Show>
    </div>
  );
}
