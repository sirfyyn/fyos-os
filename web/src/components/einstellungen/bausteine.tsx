/**
 * bausteine.tsx — Bedienelemente der Einstellungen und der Schnellregler.
 *
 * Maßstab ist styles/os.css (os-titel, Glas). Hier stehen
 * nur Tailwind-Klassen und die os.css-Klassen — kein eigenes Stylesheet. Alles ist bedienbar mit
 * Tastatur (Pfeiltasten in Auswahlgruppen), hat einen sichtbaren Fokus und Übergänge von 200 ms.
 */
import { ErrorBoundary, For, Show, Suspense, createSignal, createUniqueId, type JSX } from 'solid-js';

export const FOKUS = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)';

export const KNOPF = `inline-flex min-h-11 md:min-h-9 items-center justify-center gap-2 rounded-xl border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_5%,transparent)] px-3.5 text-sm font-medium text-(--color-fg) transition-[background-color,border-color,color,opacity] duration-200 ease-out hover:border-(--color-accent) hover:bg-[color-mix(in_oklab,var(--color-fg)_9%,transparent)] disabled:cursor-not-allowed disabled:opacity-50 ${FOKUS}`;

export const KNOPF_LEISE = `inline-flex min-h-11 md:min-h-8 items-center gap-1.5 rounded-lg px-2 text-sm font-medium text-(--color-accent) transition-colors duration-200 ease-out hover:bg-[color-mix(in_oklab,var(--color-accent)_12%,transparent)] disabled:cursor-not-allowed disabled:opacity-50 ${FOKUS}`;

/** Karte eines Abschnitts im Glasfenster: etwas heller (dunkel) bzw. weißer (hell) als das Fenster. */
export const KARTE =
  'rounded-[22px] border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_4.5%,transparent)] light:bg-[color-mix(in_oklab,#ffffff_62%,transparent)] p-5 @2xl:p-6';

const GEDAEMPFT = 'text-sm leading-snug text-(--color-fg-muted)';

/** Pfeiltasten, Pos1 und Ende in einer Auswahlgruppe (Rollen radiogroup/radio). */
export function radioTaste(e: KeyboardEvent, i: number, n: number, waehle: (j: number) => void): void {
  let j = -1;
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') j = (i + 1) % n;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') j = (i - 1 + n) % n;
  else if (e.key === 'Home') j = 0;
  else if (e.key === 'End') j = n - 1;
  if (j < 0) return;
  e.preventDefault();
  waehle(j);
}

// ── Abschnitt und Zeile ─────────────────────────────────────────────────────

export function Abschnitt(p: { id: string; titel: string; geltung?: string; children: JSX.Element; class?: string }): JSX.Element {
  return (
    <section id={p.id} aria-labelledby={`${p.id}-titel`} data-abschnitt={p.id} class={`@container scroll-mt-24 ${KARTE} ${p.class ?? ''}`}>
      <header class="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id={`${p.id}-titel`} tabindex="-1" class="os-titel m-0 outline-none">
          {p.titel}
        </h2>
        <Show when={p.geltung}>
          <p class="m-0 text-xs text-(--color-fg-subtle)">{p.geltung}</p>
        </Show>
      </header>
      {p.children}
    </section>
  );
}

/** Eine Zeile: links Name und Erklärung, rechts (im schmalen Fenster darunter) das Bedienelement. */
export function Zeile(p: {
  titel: JSX.Element;
  unter?: JSX.Element;
  children?: JSX.Element;
  /** id des Titels, damit das Bedienelement darauf verweisen kann (aria-labelledby) */
  id?: string;
  /** Bedienelement immer unter dem Text (breite Auswahl, Vorschau) */
  darunter?: boolean;
  privat?: string;
  gesperrt?: boolean;
}): JSX.Element {
  return (
    <div
      data-privat={p.privat}
      class="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-(--color-border) py-4 first:border-t-0 last:pb-1"
      classList={{ 'opacity-55': !!p.gesperrt }}
    >
      <div class="min-w-0 flex-[1_1_13rem]">
        <p id={p.id} class="m-0 text-[0.95rem] font-medium text-(--color-fg)">
          {p.titel}
        </p>
        <Show when={p.unter}>
          <p class={`m-0 mt-0.5 ${GEDAEMPFT}`}>{p.unter}</p>
        </Show>
      </div>
      <Show when={p.children}>
        <div class="min-w-0" classList={{ 'w-full': !!p.darunter, 'w-full @lg:w-[19rem] @lg:shrink-0': !p.darunter }}>
          {p.children}
        </div>
      </Show>
    </div>
  );
}

// ── Auswahl (Segmente mit gleitender Markierung) ─────────────────────────────

export interface WahlOption<T extends string> {
  wert: T;
  text: string;
  symbol?: JSX.Element;
  /** Tooltip, z. B. was der Modus ausblendet */
  titel?: string;
}

export function Wahl<T extends string>(p: {
  /** Name der Gruppe für Screenreader (oder `beschriftetVon`) */
  name?: string;
  beschriftetVon?: string;
  optionen: readonly WahlOption<T>[];
  wert: T | undefined;
  onWahl: (w: T) => void;
  gesperrt?: boolean;
  /** kompakt für Schnellregler */
  klein?: boolean;
}): JSX.Element {
  const knoepfe: HTMLButtonElement[] = [];
  const index = () => p.optionen.findIndex((o) => o.wert === p.wert);
  const waehle = (j: number) => {
    const o = p.optionen[j];
    if (!o || p.gesperrt) return;
    if (o.wert !== p.wert) p.onWahl(o.wert);
    knoepfe[j]?.focus();
  };
  return (
    <div
      role="radiogroup"
      aria-label={p.beschriftetVon ? undefined : p.name}
      aria-labelledby={p.beschriftetVon}
      aria-disabled={p.gesperrt || undefined}
      class="relative grid w-full rounded-[13px] bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] p-[3px]"
      classList={{ 'opacity-50': !!p.gesperrt }}
      style={{ 'grid-template-columns': `repeat(${p.optionen.length}, minmax(0, 1fr))` }}
    >
      <Show when={index() >= 0}>
        <span
          aria-hidden="true"
          class="pointer-events-none absolute inset-y-[3px] left-[3px] rounded-[10px] bg-white shadow-[0_1px_3px_rgb(0_0_0/0.16),0_0_0_0.5px_rgb(0_0_0/0.06)] transition-transform duration-200 ease-out motion-reduce:transition-none dark:bg-[color-mix(in_oklab,var(--color-fg)_17%,var(--color-bg-opaque))] dark:shadow-[0_1px_3px_rgb(0_0_0/0.4)]"
          style={{ width: `calc((100% - 6px) / ${p.optionen.length})`, transform: `translateX(${index() * 100}%)` }}
        />
      </Show>
      <For each={p.optionen}>
        {(o, i) => (
          <button
            type="button"
            role="radio"
            ref={(el) => (knoepfe[i()] = el)}
            aria-checked={o.wert === p.wert}
            tabindex={(index() < 0 ? i() === 0 : o.wert === p.wert) ? 0 : -1}
            disabled={p.gesperrt}
            title={o.titel}
            onClick={() => waehle(i())}
            onKeyDown={(e) => radioTaste(e, i(), p.optionen.length, waehle)}
            class="relative z-[1] flex min-w-0 items-center justify-center gap-1.5 rounded-[10px] px-2 transition-colors duration-200 ease-out focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-(--color-accent) disabled:cursor-not-allowed"
            classList={{
              'min-h-11 md:min-h-8 text-[0.8rem]': !!p.klein,
              'min-h-11 md:min-h-9 text-sm': !p.klein,
              'font-semibold text-(--color-fg)': o.wert === p.wert,
              'font-medium text-(--color-fg-muted) hover:text-(--color-fg)': o.wert !== p.wert,
            }}
          >
            <Show when={o.symbol}>
              <span aria-hidden="true" class="shrink-0 text-[0.95em] leading-none">
                {o.symbol}
              </span>
            </Show>
            <span class="truncate">{o.text}</span>
          </button>
        )}
      </For>
    </div>
  );
}

// ── Schalter ────────────────────────────────────────────────────────────────

/**
 * Nur das Bild des Schalters (Bahn und Knopf).
 * `teils`: „teilweise an" (Gesamtschalter über mehrere) — Knopf in der Mitte, Bahn halb gefärbt.
 */
export function SchalterBild(p: { an: boolean; teils?: boolean; beschaeftigt?: boolean }): JSX.Element {
  return (
    <span
      aria-hidden="true"
      class="relative inline-block h-[26px] w-[44px] shrink-0 rounded-full transition-colors duration-200 ease-out"
      classList={{
        'bg-(--color-accent)': p.an && !p.teils,
        'bg-[color-mix(in_oklab,var(--color-accent)_55%,transparent)]': !!p.teils,
        'bg-[color-mix(in_oklab,var(--color-fg)_20%,transparent)]': !p.an && !p.teils,
        'animate-pulse': !!p.beschaeftigt,
      }}
    >
      <span
        class="absolute top-[2px] left-[2px] size-[22px] rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.3)] transition-transform duration-200 ease-out motion-reduce:transition-none"
        classList={{ 'translate-x-[18px]': p.an && !p.teils, 'translate-x-[9px]': !!p.teils }}
      />
    </span>
  );
}

/** Ganze Zeile als Schalter (große Trefferfläche). */
export function SchalterZeile(p: {
  name: string;
  unter?: JSX.Element;
  an: boolean;
  /** teilweise an (Gesamtschalter): zählt für Screenreader als „aus", `beschreibung` sagt es dazu */
  teils?: boolean;
  onKlick: () => void;
  beschaeftigt?: boolean;
  gesperrt?: boolean;
  /** Zusatz für Screenreader, z. B. „teilweise an" */
  beschreibung?: string;
  kompakt?: boolean;
}): JSX.Element {
  const id = createUniqueId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={p.an && !p.teils}
      aria-describedby={p.unter || p.beschreibung ? `${id}-unter` : undefined}
      aria-disabled={p.gesperrt || undefined}
      aria-busy={p.beschaeftigt || undefined}
      onClick={() => !p.gesperrt && !p.beschaeftigt && p.onKlick()}
      class={`flex w-full min-w-0 items-center gap-4 rounded-xl text-left transition-colors duration-200 ease-out ${FOKUS}`}
      classList={{
        'min-h-[3.25rem] py-3': !p.kompakt,
        'min-h-11 py-2': !!p.kompakt,
        'cursor-not-allowed opacity-55': !!p.gesperrt,
        'cursor-wait': !!p.beschaeftigt,
      }}
    >
      <span class="min-w-0 flex-1">
        <span class="block text-[0.95rem] font-medium text-(--color-fg)">{p.name}</span>
        <Show when={p.unter || p.beschreibung}>
          <span id={`${id}-unter`} class={`mt-0.5 block ${GEDAEMPFT}`} classList={{ truncate: !!p.kompakt }}>
            {p.unter ?? p.beschreibung}
          </span>
        </Show>
      </span>
      <SchalterBild an={p.an} teils={p.teils} beschaeftigt={p.beschaeftigt} />
    </button>
  );
}

// ── Regler ──────────────────────────────────────────────────────────────────

/*
 * Bahn und Knopf über die Pseudo-Elemente des Range-Feldes (WebKit und Firefox). Der gefüllte Teil
 * kommt aus `--wert`. `no-touch` nimmt das Feld aus der globalen 44-px-Regel für Eingaben (die
 * würde die Bahn 44 px hoch machen); die Trefferfläche ist auf Touch trotzdem 44 px hoch.
 */
const REGLER = [
  'no-touch h-6 w-full min-w-0 flex-1 cursor-pointer appearance-none bg-transparent pointer-coarse:h-11 focus-visible:outline-none disabled:cursor-not-allowed',
  '[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full',
  '[&::-webkit-slider-runnable-track]:bg-[linear-gradient(to_right,var(--color-accent)_var(--wert),color-mix(in_oklab,var(--color-fg)_16%,transparent)_var(--wert))]',
  '[&::-webkit-slider-thumb]:-mt-[7px] [&::-webkit-slider-thumb]:size-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white',
  '[&::-webkit-slider-thumb]:shadow-[0_1px_3px_rgb(0_0_0/0.35),0_0_0_0.5px_rgb(0_0_0/0.15)] [&::-webkit-slider-thumb]:transition-transform [&::-webkit-slider-thumb]:duration-150 [&::-webkit-slider-thumb]:ease-out',
  'active:[&::-webkit-slider-thumb]:scale-110',
  'focus-visible:[&::-webkit-slider-thumb]:outline-2 focus-visible:[&::-webkit-slider-thumb]:outline-offset-2 focus-visible:[&::-webkit-slider-thumb]:outline-(--color-accent)',
  '[&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)]',
  '[&::-moz-range-progress]:h-1.5 [&::-moz-range-progress]:rounded-full [&::-moz-range-progress]:bg-(--color-accent)',
  '[&::-moz-range-thumb]:size-5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:shadow-[0_1px_3px_rgb(0_0_0/0.35)]',
  'focus-visible:[&::-moz-range-thumb]:outline-2 focus-visible:[&::-moz-range-thumb]:outline-offset-2 focus-visible:[&::-moz-range-thumb]:outline-(--color-accent)',
].join(' ');

export function Regler(p: {
  /** id des sichtbaren Namens (aria-labelledby) */
  beschriftetVon?: string;
  name?: string;
  wert: number;
  min: number;
  max: number;
  schritt?: number;
  onWert: (w: number) => void;
  /** Anzeige rechts und für Screenreader, z. B. „55 %" */
  anzeige: (w: number) => string;
  gesperrt?: boolean;
  /** leise Beschriftung der Enden, z. B. „klar" … „milchig" */
  links?: string;
  rechts?: string;
}): JSX.Element {
  const anteil = () => Math.min(100, Math.max(0, ((p.wert - p.min) / (p.max - p.min || 1)) * 100));
  return (
    <div class="flex w-full items-center gap-3">
      <Show when={p.links}>
        <span aria-hidden="true" class="shrink-0 text-xs text-(--color-fg-subtle)">
          {p.links}
        </span>
      </Show>
      <input
        type="range"
        min={p.min}
        max={p.max}
        step={p.schritt ?? 1}
        value={p.wert}
        disabled={p.gesperrt}
        aria-labelledby={p.beschriftetVon}
        aria-label={p.beschriftetVon ? undefined : p.name}
        aria-valuetext={p.anzeige(p.wert)}
        onInput={(e) => p.onWert(Number(e.currentTarget.value))}
        class={REGLER}
        style={{ '--wert': `${anteil()}%` }}
      />
      <Show when={p.rechts}>
        <span aria-hidden="true" class="shrink-0 text-xs text-(--color-fg-subtle)">
          {p.rechts}
        </span>
      </Show>
      <output aria-hidden="true" class="w-12 shrink-0 text-right font-mono text-xs text-(--color-fg-muted) tabular-nums">
        {p.anzeige(p.wert)}
      </output>
    </div>
  );
}

// ── Aufklappen (bestehende Ansichten an Ort und Stelle) ──────────────────────

export function Laedt(p: { text?: string }): JSX.Element {
  return (
    <div role="status" class="flex flex-col gap-2 py-2" aria-label={p.text ?? 'Wird geladen'}>
      <span class="h-3 w-2/5 animate-pulse rounded-full bg-[color-mix(in_oklab,var(--color-fg)_10%,transparent)]" />
      <span class="h-3 w-4/5 animate-pulse rounded-full bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)]" />
      <span class="h-3 w-3/5 animate-pulse rounded-full bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)]" />
    </div>
  );
}

export function Fehler(p: { text: string; nochmal?: () => void }): JSX.Element {
  return (
    <div role="alert" class="flex flex-wrap items-center gap-3 rounded-xl border border-(--color-warn)/35 bg-(--color-warn-soft) px-3.5 py-2.5 text-sm">
      <span class="min-w-0 flex-1">{p.text}</span>
      <Show when={p.nochmal}>
        <button type="button" class={KNOPF} onClick={() => p.nochmal!()}>
          Erneut versuchen
        </button>
      </Show>
    </div>
  );
}

/**
 * Eine Zeile, die eine bestehende Ansicht (z. B. „Meine Geräte") an Ort und Stelle aufklappt.
 * Der Inhalt wird erst beim Aufklappen geladen; ein Fehler bleibt in der Zeile.
 */
export function Aufklapper(p: { titel: string; unter?: JSX.Element; children: JSX.Element; privat?: string }): JSX.Element {
  const id = createUniqueId();
  const [offen, setOffen] = createSignal(false);
  return (
    <div data-privat={p.privat} class="border-t border-(--color-border) first:border-t-0">
      <button
        type="button"
        aria-expanded={offen()}
        aria-controls={`${id}-inhalt`}
        onClick={() => setOffen((o) => !o)}
        class={`flex min-h-[3.25rem] w-full items-center gap-4 rounded-xl py-3 text-left ${FOKUS}`}
      >
        <span class="min-w-0 flex-1">
          <span class="block text-[0.95rem] font-medium text-(--color-fg)">{p.titel}</span>
          <Show when={p.unter}>
            <span class={`mt-0.5 block ${GEDAEMPFT}`}>{p.unter}</span>
          </Show>
        </span>
        <svg
          aria-hidden="true"
          viewBox="0 0 20 20"
          class="size-4 shrink-0 text-(--color-fg-subtle) transition-transform duration-200 ease-out motion-reduce:transition-none"
          classList={{ 'rotate-90': offen() }}
        >
          <path d="M7.5 4.5 13 10l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <Show when={offen()}>
        <div id={`${id}-inhalt`} class="pb-4 [&_.luxe-title]:hidden" data-eingebettet>
          <ErrorBoundary fallback={(e, nochmal) => <Fehler text={`Konnte nicht geladen werden: ${e instanceof Error ? e.message : String(e)}`} nochmal={nochmal} />}>
            <Suspense fallback={<Laedt />}>{p.children}</Suspense>
          </ErrorBoundary>
        </div>
      </Show>
    </div>
  );
}

/** Punkt für Zustände (frei, wartet, aus, Fehler). */
export function Punkt(p: { ton: 'ok' | 'warn' | 'aus' | 'fehler' }): JSX.Element {
  return (
    <span
      aria-hidden="true"
      class="inline-block size-2 shrink-0 rounded-full"
      classList={{
        'bg-(--color-success) shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-success)_22%,transparent)]': p.ton === 'ok',
        'bg-(--color-warn) shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-warn)_22%,transparent)]': p.ton === 'warn',
        'bg-(--color-fg-subtle)': p.ton === 'aus',
        'bg-(--color-error) shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-error)_22%,transparent)]': p.ton === 'fehler',
      }}
    />
  );
}
