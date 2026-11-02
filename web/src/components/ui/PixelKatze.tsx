/**
 * PixelKatze — Agent als kleine Pixel-Katze für Zentrale, Menüleiste und Meldungen (OS-Neubau P1, Nr. 707:
 * „3d pixelcat character“). Die 3D-Voxel-Fassung im HomeTwin baut P3; diese hier ist das flache Gesicht dazu.
 *
 * Ein Raster aus Pixeln (CSS-Grid), dazu je Tätigkeit eine kleine Bewegung: tippen (baut), Gedankenpunkte (denkt), Zeitung
 * (liest), Ohren hoch (schaut), Karte in der Pfote (wartet), Zzz (schlaeft). Blinzeln und Schwanzwedeln laufen nur, solange
 * sie sichtbar ist; prefers-reduced-motion hält alles still.
 */
import { For, Show, type JSX } from 'solid-js';
import './pixel-katze.css';

export type Taetigkeit = 'baut' | 'denkt' | 'liest' | 'schaut' | 'wartet' | 'schlaeft' | 'bereit';

// 12 × 11 Pixel. f = Fell, d = dunkles Fell (Schatten), h = hell (Brust), a = Auge, n = Nase, o = Ohr innen, . = leer
const KOERPER = [
  '.ff......ff.',
  '.fof....fof.',
  '.ffffffffffd',
  'ffffffffffdd',
  'ffaffffaffdd',
  'ffffnnffffdd',
  '.ffffffffdd.',
  '..fhhhhhfd..',
  '..fhhhhhfd..',
  '..ffffffdd..',
  '..d.d..d.d..',
];

const FARBE: Record<string, string> = {
  f: 'var(--katze-fell)',
  d: 'var(--katze-schatten)',
  h: 'var(--katze-brust)',
  a: 'var(--katze-auge)',
  n: 'var(--katze-nase)',
  o: 'var(--katze-nase)',
};

export default function PixelKatze(p: {
  taetigkeit?: Taetigkeit;
  groesse?: number;
  class?: string;
  label?: string;
  /** Freischaltungen aus dem Spiel (P9): halsband, brille, schal, krone … */
  zubehoer?: readonly string[];
}): JSX.Element {
  const hat = (z: string) => !!p.zubehoer?.includes(z);
  const t = () => p.taetigkeit ?? 'bereit';
  const px = () => p.groesse ?? 4;
  const zellen = KOERPER.flatMap((zeile, y) => [...zeile].map((c, x) => ({ c, x, y })).filter((z) => z.c !== '.'));
  return (
    <span
      class={`pixel-katze ${p.class ?? ''}`}
      data-taetigkeit={t()}
      role="img"
      aria-label={p.label ?? `Agent ${TEXT[t()]}`}
      style={{ '--px': `${px()}px` }}
    >
      <span class="pk-koerper">
        <For each={zellen}>
          {(z) => (
            <span
              class="pk-pixel"
              classList={{ 'pk-auge': z.c === 'a' }}
              style={{ '--x': String(z.x), '--y': String(z.y), background: FARBE[z.c] }}
            />
          )}
        </For>
        <span class="pk-schwanz" />
        <Show when={hat('halsband')}>
          <span class="pk-halsband" aria-hidden="true"><i /></span>
        </Show>
        <Show when={hat('schal')}>
          <span class="pk-schal" aria-hidden="true" />
        </Show>
        <Show when={hat('brille')}>
          <span class="pk-brille" aria-hidden="true" />
        </Show>
        <Show when={hat('krone')}>
          <span class="pk-krone" aria-hidden="true" />
        </Show>
      </span>
      <Show when={t() === 'baut'}>
        <span class="pk-laptop" />
      </Show>
      <Show when={t() === 'liest'}>
        <span class="pk-zeitung" />
      </Show>
      <Show when={t() === 'wartet'}>
        <span class="pk-karte">?</span>
      </Show>
      <Show when={t() === 'denkt'}>
        <span class="pk-gedanke"><i /><i /><i /></span>
      </Show>
      <Show when={t() === 'schlaeft'}>
        <span class="pk-zzz">z<small>z</small></span>
      </Show>
    </span>
  );
}

export const TEXT: Record<Taetigkeit, string> = {
  baut: 'baut',
  denkt: 'denkt nach',
  liest: 'liest',
  schaut: 'schaut nach',
  wartet: 'wartet auf dich',
  schlaeft: 'schläft',
  bereit: 'ist bereit',
};
