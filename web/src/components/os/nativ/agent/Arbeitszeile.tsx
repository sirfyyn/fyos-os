/**
 * Arbeitszeile — die EINE schlanke Zeile je Zug: „Arbeitet … · 4 Schritte · 38 s“, aufklappbar.
 * Darunter (aufgeklappt) die Schritte: Werkzeuge mit Klartext-Titel, Status und Dauer, Zwischentexte, Gedanken.
 * Gedanken und Rohausgaben sind ein weiteres Aufklappen tiefer: nichts davon steht je im Fließtext.
 */
import { Index, Match, Show, Switch, createUniqueId, type JSX } from 'solid-js';
import { arbeitsZeile, aktuellerSchritt, dauerText, kuerzeAusgabe, type Schritt, type Zug } from '~/lib/agent-runner/verlauf';
import type { Aufklapp } from './aufklappen';
import { FOKUS, Text } from './gemeinsam';
import { tr } from '~/lib/i18n';

const PRE =
  'm-0 overflow-auto rounded-lg bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] p-2 font-mono text-xs leading-snug whitespace-pre-wrap break-words';

function Pfeil(p: { offen: boolean }): JSX.Element {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      class="size-3.5 shrink-0 text-(--color-fg-subtle) transition-transform duration-150 motion-reduce:transition-none"
      classList={{ 'rotate-90': p.offen }}
    >
      <path d="M7.5 4.5 13 10l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  );
}

/** Status eines Schritts als Zeichen: läuft (pulsiert), ok (Haken), Fehler (Kreuz). */
function Zeichen(p: { status: 'laeuft' | 'fertig' | 'fehler' | 'offen' }): JSX.Element {
  return (
    <span class="inline-flex size-4 shrink-0 items-center justify-center" data-status={p.status}>
      <Switch fallback={<span aria-hidden="true" class="size-1.5 rounded-full bg-(--color-fg-subtle)" />}>
        <Match when={p.status === 'laeuft'}>
          <span aria-hidden="true" class="size-2 rounded-full bg-(--color-warn) motion-safe:animate-pulse" />
        </Match>
        <Match when={p.status === 'fertig'}>
          <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5 text-(--color-success)">
            <path d="m3.5 8.5 3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </Match>
        <Match when={p.status === 'fehler'}>
          <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5 text-(--color-error)">
            <path d="m4 4 8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
        </Match>
      </Switch>
    </span>
  );
}

const STATUS_WORT = { laeuft: 'läuft', fertig: 'ok', fehler: 'Fehler', offen: 'offen' } as const;

function Eingabe(p: { text: string }): JSX.Element {
  const k = () => kuerzeAusgabe(p.text, 900);
  return <pre class={`${PRE} max-h-40`}>{k().text}</pre>;
}

function WerkzeugSchritt(p: { s: Extract<Schritt, { art: 'werkzeug' }>; jetzt: number; offen: Aufklapp; kopf: string }): JSX.Element {
  const key = () => `${p.kopf}:${p.s.schluessel}`;
  const auf = () => p.offen.ist(key());
  const id = createUniqueId();
  const dauer = () => dauerText(p.s.status === 'laeuft' && p.s.seit ? p.jetzt - p.s.seit : p.s.dauerMs);
  return (
    <li data-schritt="werkzeug" data-status={p.s.status} data-werkzeug={p.s.name}>
      <button
        type="button"
        aria-expanded={auf()}
        aria-controls={id}
        class={`flex min-h-8 w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left text-[0.8rem] hover:bg-[color-mix(in_oklab,var(--color-fg)_6%,transparent)] ${FOKUS}`}
        classList={{ 'text-(--color-error)': p.s.status === 'fehler' }}
        onClick={() => p.offen.umschalten(key())}
      >
        <Zeichen status={p.s.status} />
        <span class="min-w-0 flex-1 truncate">
          {p.s.titel}
          <span class="sr-only"> — {STATUS_WORT[p.s.status]}</span>
        </span>
        <Show when={p.s.status === 'fehler' && p.s.fehlerZeile && !auf()}>
          <span class="hidden max-w-[45%] truncate text-xs opacity-80 @lg:inline">{p.s.fehlerZeile}</span>
        </Show>
        <Show when={dauer()}>
          <span class="shrink-0 text-xs tabular-nums text-(--color-fg-subtle)">{dauer()}</span>
        </Show>
        <Pfeil offen={auf()} />
      </button>
      <Show when={auf()}>
        <div id={id} class="mb-1 ml-6 flex flex-col gap-2 border-l border-(--color-border) pl-3">
          <Show when={p.s.eingabe}>
            <div>
              <p class="m-0 mb-1 text-[0.7rem] font-semibold text-(--color-fg-muted)">{tr('Eingabe')}</p>
              <Eingabe text={p.s.eingabe} />
            </div>
          </Show>
          <Show when={p.s.ausgabe} fallback={<p class="m-0 text-xs text-(--color-fg-muted)">{p.s.status === 'laeuft' ? tr('Noch keine Ausgabe.') : tr('Keine Ausgabe.')}</p>}>
            <div>
              <p class="m-0 mb-1 text-[0.7rem] font-semibold text-(--color-fg-muted)">
                {p.s.status === 'fehler' ? tr('Fehlermeldung') : tr('Ausgabe')}
                <Show when={p.s.gekuerzt}>{' '}{tr('(gekürzt)')}</Show>
              </p>
              <pre class={`${PRE} max-h-64`} classList={{ 'bg-(--color-error-soft)': p.s.status === 'fehler' }}>
                {p.s.ausgabe}
              </pre>
            </div>
          </Show>
          <Show when={p.s.diagnose}>
            <pre class={`${PRE} max-h-32 bg-(--color-warn-soft)`}>{p.s.diagnose}</pre>
          </Show>
        </div>
      </Show>
    </li>
  );
}

function GedankenSchritt(p: { s: Extract<Schritt, { art: 'gedanken' }>; offen: Aufklapp; kopf: string }): JSX.Element {
  const key = () => `${p.kopf}:${p.s.schluessel}`;
  const auf = () => p.offen.ist(key());
  const id = createUniqueId();
  return (
    <li data-schritt="gedanken">
      <button
        type="button"
        aria-expanded={auf()}
        aria-controls={id}
        class={`flex min-h-8 w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left text-[0.8rem] text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_6%,transparent)] ${FOKUS}`}
        onClick={() => p.offen.umschalten(key())}
      >
        <span aria-hidden="true" class="inline-flex size-4 shrink-0 items-center justify-center">
          <span class="size-1.5 rounded-full border border-(--color-fg-subtle)" />
        </span>
        <span class="min-w-0 flex-1 truncate">{tr('Gedanken ·')}{' '}{p.s.woerter} {p.s.woerter === 1 ? tr('Wort') : tr('Wörter')}</span>
        <Pfeil offen={auf()} />
      </button>
      <Show when={auf()}>
        <p id={id} class="m-0 mb-1 ml-6 border-l-2 border-(--color-border-strong) pl-3 text-[0.8rem] leading-snug whitespace-pre-wrap text-(--color-fg-muted)">
          {p.s.text}
        </p>
      </Show>
    </li>
  );
}

export function Arbeitszeile(p: { z: Zug; jetzt: number; offen: Aufklapp }): JSX.Element {
  const key = () => `${p.z.schluessel}:arbeit`;
  const auf = () => p.offen.ist(key());
  const id = createUniqueId();
  const aktuell = () => (p.z.laeuft ? aktuellerSchritt(p.z) : '');
  return (
    <div class="min-w-0 max-w-full self-stretch @2xl:max-w-[44rem]" data-arbeit data-laeuft={p.z.laeuft || undefined} data-fehler={p.z.fehlerZahl > 0 || undefined}>
      <button
        type="button"
        aria-expanded={auf()}
        aria-controls={id}
        class={`flex min-h-9 max-w-full items-center gap-2 rounded-full border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_4%,transparent)] py-1 pr-2.5 pl-3 text-left text-xs text-(--color-fg-muted) transition-colors hover:border-(--color-border-strong) hover:text-(--color-fg) ${FOKUS}`}
        classList={{ 'border-(--color-error)/50': p.z.fehlerZahl > 0 && !p.z.laeuft }}
        onClick={() => p.offen.umschalten(key())}
      >
        <Show
          when={p.z.laeuft}
          fallback={
            <Show when={p.z.fehlerZahl > 0} fallback={<span aria-hidden="true" class="size-1.5 shrink-0 rounded-full bg-(--color-fg-subtle)" />}>
              <span aria-hidden="true" class="size-1.5 shrink-0 rounded-full bg-(--color-error)" />
            </Show>
          }
        >
          <span aria-hidden="true" class="size-2 shrink-0 rounded-full bg-(--color-success) motion-safe:animate-pulse" />
        </Show>
        <span class="shrink-0 font-medium" role={p.z.laeuft ? 'status' : undefined}>
          {arbeitsZeile(p.z, p.jetzt)}
        </span>
        <Show when={aktuell()}>
          <span class="min-w-0 truncate text-(--color-fg-subtle)">· {aktuell()}</span>
        </Show>
        <Pfeil offen={auf()} />
      </button>
      <Show when={auf()}>
        <ol id={id} class="m-0 mt-1.5 flex list-none flex-col gap-0.5 p-0" data-schritte>
          <Index each={p.z.schritte} fallback={<li class="px-2 py-1 text-xs text-(--color-fg-muted)">{p.z.laeuft ? tr('Noch kein Schritt.') : tr('Keine Schritte.')}</li>}>
            {(s) => (
              <Switch>
                <Match when={s().art === 'werkzeug' && (s() as Extract<Schritt, { art: 'werkzeug' }>)}>
                  {(w) => <WerkzeugSchritt s={w()} jetzt={p.jetzt} offen={p.offen} kopf={p.z.schluessel} />}
                </Match>
                <Match when={s().art === 'gedanken' && (s() as Extract<Schritt, { art: 'gedanken' }>)}>
                  {(g) => <GedankenSchritt s={g()} offen={p.offen} kopf={p.z.schluessel} />}
                </Match>
                <Match when={s().art === 'notiz' && (s() as Extract<Schritt, { art: 'notiz' }>)}>
                  {(n) => (
                    <li data-schritt="notiz" class="px-1.5 py-1 text-[0.82rem] text-(--color-fg-muted)">
                      <Text text={n().text} />
                    </li>
                  )}
                </Match>
              </Switch>
            )}
          </Index>
        </ol>
      </Show>
    </div>
  );
}
