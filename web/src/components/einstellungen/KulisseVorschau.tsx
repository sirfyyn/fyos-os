/**
 * KulisseVorschau — der Bildschirm im Kleinen: die echte Kulisse (components/os/Kulisse), zwei
 * Fenster und die Bodenleiste aus demselben Glas wie das OS.
 *
 * Gerendert wird in voller Bildschirmgröße und dann verkleinert. So stimmen Größen in vmax/vw/vh,
 * die Unschärfe der Farbflecken und die des Glases genau — jede Einstellung wirkt hier sofort, weil
 * die Vorschau dieselben Variablen am <html> liest wie die große Kulisse. Auf dem Handy ist die
 * Vorschau hochkant wie das Handy. Läuft nur, solange sie zu sehen ist.
 */
import { Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import Kulisse from '~/components/os/Kulisse';

/** Höchstens so hoch, damit die Regler darunter im Blick bleiben. */
const MAX_HOEHE = 300;

function Fenster(p: { stil: JSX.CSSProperties; fokus?: boolean; kacheln?: boolean }): JSX.Element {
  return (
    <div class="os-glas absolute flex flex-col overflow-hidden" classList={{ 'os-fokus': !!p.fokus }} style={p.stil}>
      <div class="os-kopf">
        <span class="h-3 w-32 rounded-full bg-[color-mix(in_oklab,var(--color-fg)_28%,transparent)]" />
      </div>
      <div class="flex min-h-0 flex-1 flex-col gap-4 p-8">
        <span class="h-7 w-3/5 rounded-full bg-[color-mix(in_oklab,var(--color-fg)_22%,transparent)]" />
        <span class="h-4 w-full rounded-full bg-[color-mix(in_oklab,var(--color-fg)_11%,transparent)]" />
        <span class="h-4 w-11/12 rounded-full bg-[color-mix(in_oklab,var(--color-fg)_11%,transparent)]" />
        <span class="h-4 w-3/4 rounded-full bg-[color-mix(in_oklab,var(--color-fg)_11%,transparent)]" />
        <Show when={p.kacheln}>
          <div class="mt-auto grid grid-cols-[repeat(3,minmax(0,1fr))] gap-4">
            <span class="h-28 rounded-2xl bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)]" />
            <span class="h-28 rounded-2xl bg-[color-mix(in_oklab,var(--color-accent)_30%,transparent)]" />
            <span class="h-28 rounded-2xl bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)]" />
          </div>
        </Show>
      </div>
    </div>
  );
}

export default function KulisseVorschau(): JSX.Element {
  let rahmen: HTMLDivElement | undefined;
  const [mass, setMass] = createSignal({ b: 1440, h: 900, s: 0.2, rb: 288, rh: 180 });
  const [sichtbar, setSichtbar] = createSignal(false);

  onMount(() => {
    const neu = () => {
      const b = Math.max(320, window.innerWidth);
      const h = Math.max(320, window.innerHeight);
      const verfuegbar = rahmen?.parentElement?.clientWidth ?? 320;
      // So breit wie möglich, aber nicht höher als MAX_HOEHE — das Seitenverhältnis bleibt das des Bildschirms
      const rb = Math.min(verfuegbar, (MAX_HOEHE * b) / h);
      setMass({ b, h, s: rb / b, rb, rh: (rb * h) / b });
    };
    neu();
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(neu) : null;
    if (rahmen?.parentElement) ro?.observe(rahmen.parentElement);
    window.addEventListener('resize', neu);
    const io =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver((e) => setSichtbar(e.some((x) => x.isIntersecting)), { rootMargin: '120px' })
        : null;
    if (rahmen && io) io.observe(rahmen);
    else setSichtbar(true);
    onCleanup(() => {
      ro?.disconnect();
      io?.disconnect();
      window.removeEventListener('resize', neu);
    });
  });

  const handy = () => mass().b < 768;

  return (
    <div class="flex w-full justify-center">
      <div
        ref={rahmen}
        aria-hidden="true"
        data-kulisse-vorschau
        class="relative shrink-0 overflow-hidden border border-(--os-glas-rand) bg-(--color-bg) shadow-[0_12px_40px_-18px_rgb(0_0_0/0.6)]"
        classList={{ 'rounded-[18px]': !handy(), 'rounded-[26px]': handy() }}
        style={{ width: `${mass().rb}px`, height: `${mass().rh}px` }}
      >
        <div
          class="pointer-events-none absolute top-0 left-0 origin-top-left"
          style={{ width: `${mass().b}px`, height: `${mass().h}px`, transform: `scale(${mass().s})` }}
        >
          <Show when={sichtbar()}>
            <Kulisse />
            <Show
              when={!handy()}
              fallback={<Fenster fokus kacheln stil={{ left: '3%', right: '3%', top: '4%', bottom: '12%' }} />}
            >
              <Fenster stil={{ left: '1.5%', top: '2.5%', width: '47.75%', bottom: '12%' }} kacheln />
              <Fenster fokus stil={{ left: '50.75%', top: '2.5%', right: '1.5%', bottom: '12%' }} />
            </Show>
            <div class="os-glas absolute flex items-center gap-3 px-3" style={{ left: '1.5%', right: '1.5%', bottom: '2%', height: '7.5%' }}>
              <span class="h-[62%] w-[9%] min-w-16 rounded-xl bg-(--color-accent)" />
              <span class="h-[52%] w-[12%] rounded-xl border border-(--color-border-strong) bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)]" />
              <span class="h-[52%] w-[9%] rounded-xl border border-(--color-border-strong) bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)]" />
              <span class="ml-auto h-[30%] w-[6%] rounded-full bg-[color-mix(in_oklab,var(--color-fg)_25%,transparent)]" />
            </div>
          </Show>
        </div>
      </div>
    </div>
  );
}
