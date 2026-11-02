/**
 * Bausteine der Zentrale — von den Kacheln (Startseite) UND den nativen Flächen im OS benutzt.
 *
 * Eine Quelle für Knöpfe, Zeilen, Zahlen und Kippschalter: Kachel und Fläche sehen aus wie
 * ein Ding in zwei Größen. Hier steht nichts, was Daten holt; das tun `daten.ts` und die Flächen.
 */
import { Show, createContext, createSignal, onCleanup, onMount, useContext, type Accessor, type JSX } from 'solid-js';
import type { Ton } from '~/lib/zentrale';
import { gebietsschema, tr } from '~/lib/i18n';

export const KNOPF =
  'inline-flex min-h-11 md:min-h-10 items-center gap-2 rounded-xl border border-(--color-border) bg-(--color-card-hover)/40 px-3.5 text-sm font-medium text-(--color-fg) transition-colors hover:border-(--color-accent) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent) disabled:cursor-not-allowed disabled:opacity-55';
export const KNOPF_VOLL =
  'inline-flex min-h-11 md:min-h-10 items-center rounded-xl border border-(--color-accent) bg-(--color-accent) px-3.5 text-sm font-semibold text-(--color-accent-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent) disabled:cursor-not-allowed disabled:opacity-55';
export const ZEILE = 'flex min-w-0 items-baseline gap-2.5 border-t border-(--color-border) py-[7px] first:border-t-0';
/**
 * Große Zahl einer Kachel. Wächst mit der Kachel (cqi = Breite des Containers `kachel`, siehe
 * [data-kachelkarte] in os.css): im Viertel ~2,1rem, ab Halb 2,6rem. Ohne Container zählt die Seite.
 */
export const ZAHL = 'text-[clamp(1.7rem,14cqi,2.6rem)] font-semibold leading-none tracking-tight tabular-nums';
export const KLEIN_GEDAEMPFT = 'text-sm text-(--color-fg-muted)';

/** Farbe eines Textes nach Ton (Störung, Warnung, in Ordnung, leise). */
export const TON_TEXT: Record<Ton, string> = {
  error: 'text-(--color-error)',
  warn: 'text-(--color-warn)',
  ok: 'text-(--color-success)',
  leise: 'text-(--color-fg-muted)',
};

export const uhrzeit = (iso: string | null | undefined) => {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString(gebietsschema(), { hour: '2-digit', minute: '2-digit' });
};
export const tagKurz = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString(gebietsschema(), { weekday: 'short', day: '2-digit', month: '2-digit' });
};

/** Kachel ohne Daten: Grund und, wenn möglich, „Erneut versuchen“. */
export function Nichtabrufbar(p: { fehler: string | null | undefined; erneut?: () => void }) {
  return (
    <div role="status" class="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-(--color-warn)">
      <span class="min-w-0">{tr('nicht abrufbar —')}{' '}{p.fehler || tr('keine Daten')}</span>
      <Show when={p.erneut}>
        {(los) => (
          <button type="button" class={KNOPF} onClick={() => los()()}>
            {tr('Erneut versuchen')}
          </button>
        )}
      </Show>
    </div>
  );
}

export function Zahl(p: { wert: JSX.Element; unter: string; ton?: 'warn' | 'ok' | 'muted'; klein?: JSX.Element; gross?: boolean }) {
  return (
    <div>
      <div
        class={p.gross ? 'text-[clamp(2.2rem,5.5cqi,3.1rem)] font-semibold leading-none tracking-tight tabular-nums' : ZAHL}
        classList={{
          'text-(--color-warn)': p.ton === 'warn',
          'text-(--color-success)': p.ton === 'ok',
          'text-(--color-fg-muted)': p.ton === 'muted',
        }}
      >
        {p.wert}
        <Show when={p.klein}>
          <small class="text-base font-medium tracking-normal text-(--color-fg-muted)">{p.klein}</small>
        </Show>
      </div>
      <div class={KLEIN_GEDAEMPFT}>{p.unter}</div>
    </div>
  );
}

/** Kippschalter (Haus-Favoriten, Vorhaben). */
export function Kipp(p: {
  rolle: 'switch' | 'checkbox';
  an: boolean;
  name: string;
  unter?: string;
  gesperrt?: boolean;
  beschaeftigt?: boolean;
  onKlick: () => void;
}) {
  return (
    <button
      type="button"
      role={p.rolle}
      aria-checked={p.an}
      aria-disabled={p.gesperrt || undefined}
      aria-busy={p.beschaeftigt || undefined}
      onClick={() => !p.gesperrt && !p.beschaeftigt && p.onKlick()}
      class="flex min-h-[52px] w-full items-center gap-3 rounded-xl border border-(--color-border) bg-(--color-card-hover)/40 px-3 py-2.5 text-left text-(--color-fg) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
      classList={{ 'cursor-not-allowed opacity-55': !!p.gesperrt, 'cursor-wait opacity-75': !!p.beschaeftigt }}
    >
      <span class="min-w-0 flex-1">
        <span classList={{ 'line-through text-(--color-fg-muted)': p.rolle === 'checkbox' && p.an }}>{p.name}</span>
        <Show when={p.unter}>
          <small class="block text-xs text-(--color-fg-muted)">{p.unter}</small>
        </Show>
      </span>
      <span
        aria-hidden="true"
        class="relative h-6 w-[42px] shrink-0 rounded-full transition-colors"
        classList={{ 'bg-(--color-accent)': p.an, 'bg-(--color-border-strong)': !p.an }}
      >
        <span
          class="absolute top-[3px] left-[3px] size-[18px] rounded-full transition-transform"
          classList={{ 'translate-x-[18px] bg-(--color-accent-text)': p.an, 'bg-(--color-fg)': !p.an }}
        />
      </span>
    </button>
  );
}

// ── Schreibwege ─────────────────────────────────────────────────────────────

export interface Werkzeuge {
  /** Ruft ein Hub-Werkzeug, meldet das Ergebnis und frischt den Zustand auf. */
  rufe: (werkzeug: string, argumente: Record<string, unknown>, erfolg: string) => Promise<unknown>;
  melde: (text: string, ok?: boolean) => void;
  /** Zustand neu holen (Knopf „Erneut versuchen“ einer ausgefallenen Kachel). */
  erneut?: () => void;
}

// ── Stufen: der Inhalt folgt der Kachelgröße (04.10.) ───────────────────────────────────────
// Kachelgrößen ändern sich, daher passt sich auch der Inhalt an. Wie Widgets am Mac:
//   kompakt   Viertel (und schmaler): eine große Zahl, ein Satz, höchstens zwei Listenzeilen
//   standard  Halb und Handy: wie bisher
//   weit      Dreiviertel und Voll: doppelt so viele Zeilen, Zahlen und Liste nebeneinander
// Gemessen wird die Inhaltsbreite der Kachel (ResizeObserver), nicht das gewählte Maß — so stimmt
// die Stufe auch auf dem Tablet, im schmalen Fenster und aufgeklappt unter „Ruhig“. Dieselben
// Grenzen stehen in os.css (@container kachel), damit Anordnung und Zeilenzahl zusammen umschlagen.

export type Stufe = 'kompakt' | 'standard' | 'weit';
/** Inhaltsbreite in px, ab der eine Stufe gilt (os.css: 18.75rem und 37.5rem). */
export const STUFE_AB = { standard: 300, weit: 600 } as const;
/** 0 heißt „noch nicht gemessen“ — dann standard, damit nichts springt. */
export const stufeAusBreite = (px: number): Stufe =>
  px >= STUFE_AB.weit ? 'weit' : px >= STUFE_AB.standard || px <= 0 ? 'standard' : 'kompakt';
/** Wie viele Einträge eine Liste zeigt: kompakt höchstens 2, standard `normal`, weit doppelt so viele. */
export const wieViele = (stufe: Stufe, normal: number): number =>
  stufe === 'kompakt' ? Math.min(2, normal) : stufe === 'weit' ? normal * 2 : normal;

const KachelStufe = createContext<Accessor<Stufe>>((): Stufe => 'standard');
/** Stufe der umgebenden Kachel (außerhalb einer Kachel: standard). */
export const useStufe = (): Accessor<Stufe> => useContext(KachelStufe);
export const StufeAnbieter = KachelStufe.Provider;

/**
 * Misst ein Element (die Kachel, `data-kachelkarte`) und liefert seine Stufe. Ohne ResizeObserver
 * (Tests, alte Browser) bleibt es bei standard.
 */
export function stufeMessen(): { stufe: Accessor<Stufe>; ref: (el: HTMLElement) => void } {
  const [stufe, setStufe] = createSignal<Stufe>('standard');
  let el: HTMLElement | undefined;
  onMount(() => {
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((eintraege) => setStufe(stufeAusBreite(eintraege[0]?.contentRect.width ?? 0)));
    ro.observe(el);
    onCleanup(() => ro.disconnect());
  });
  return { stufe, ref: (e) => (el = e) };
}

// ── Die Zentrale im OS ──────────────────────────────────────────────────────

/**
 * Im OS (Shell) öffnet die Zentrale Flächen statt auf Seiten zu springen: `oeffneFlaeche` kommt von
 * der Shell und steht über `ZentraleImOs` allen Kacheln zur Verfügung. Ohne Shell (Startseite `/`)
 * ist es `undefined` — dann gelten die normalen Links.
 */
export const ZentraleImOs = createContext<((id: string) => void) | undefined>(undefined);
export const useZentraleImOs = () => useContext(ZentraleImOs);
