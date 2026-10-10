/**
 * Symbol — App-Symbol einer Fläche: Glyphe auf einer Kachel in der Farbe ihres Bereichs
 * (lib/os/symbole.ts). Größe kommt vom Aufrufer (CSS-Klasse), die Glyphe skaliert mit.
 * `Glyphe` ist die nackte Glyphe (Strich über currentColor) für Knöpfe, Menüpunkte und Überschriften —
 * der einzige Ort, an dem eine Glyphe als Markup eingesetzt wird.
 */
import { Show, type JSX } from 'solid-js';
import { farbton, glyphe, glypheSvg, symbolBild } from '~/lib/os/symbole';

/** Eine Lucide-Glyphe aus symbole-daten.ts; `gefuellt` malt die Fläche aus (Stern, Pin). */
export function Glyphe(p: { name: string; class?: string; gefuellt?: boolean }): JSX.Element {
  return (
    <svg
      class={p.class}
      viewBox="0 0 24 24"
      fill={p.gefuellt ? 'currentColor' : 'none'}
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      // eslint-disable-next-line solid/no-innerhtml -- feste Glyphen aus symbole-daten.ts, keine Eingaben
      innerHTML={glypheSvg(p.name)}
    />
  );
}

export default function Symbol(p: { id: string; gruppe?: string; class?: string }): JSX.Element {
  const ton = () => farbton(p.id);
  // Kennt der Hub eine Glyphe, die wir nicht zeichnen können, bringt er das fertige Bild mit.
  const bild = () => symbolBild(p.id);
  return (
    <span
      class={`os-symbol ${p.class ?? ''}`}
      classList={{ 'os-symbol-grafit': ton() === -1, 'os-symbol-agent': ton() === -2, 'os-symbol-fertig': !!bild() }}
      style={ton() >= 0 ? { '--h': String(ton()) } : undefined}
      aria-hidden="true"
    >
      <Show when={bild()} fallback={<Glyphe name={glyphe(p.id)} />}>
        {(src) => <img src={src()} alt="" draggable={false} class="os-symbol-bild" />}
      </Show>
    </span>
  );
}
