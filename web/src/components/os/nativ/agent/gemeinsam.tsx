/**
 * gemeinsam.tsx — kleine Bausteine der Agenten-Fläche. Keine eigenen Stile: Tailwind-Klassen mit den Farben des Systems
 * und die Bausteine der Einstellungen und der Zentrale (KNOPF, KARTE, Laedt, Fehler, Punkt, Wahl).
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { Dynamic } from 'solid-js/web';
import { FOKUS, KNOPF, Punkt } from '~/components/einstellungen/bausteine';
import { KNOPF_VOLL } from '~/components/zentrale/bausteine';
import { textTeile, type InlineTeil } from '~/lib/agent-runner/text';
import type { RunnerFehler } from '~/lib/agent-runner/verbindung';
import { tr } from '~/lib/i18n';

export { KNOPF, KNOPF_VOLL, Punkt };
export { Fehler, Laedt, FOKUS } from '~/components/einstellungen/bausteine';

/** Ein Textfeld im Stil der Fläche. */
export const FELD =
  'w-full min-w-0 rounded-xl border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_5%,transparent)] px-3 py-2 text-sm text-(--color-fg) placeholder:text-(--color-fg-subtle) focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-(--color-accent)';

/** Eine Zeile auf einer Karte mit Rand: Freigabe, Lauf, Zustandswert. */
export const KARTE_ZEILE =
  'min-w-0 rounded-2xl border border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-fg)_4.5%,transparent)] light:bg-[color-mix(in_oklab,#ffffff_62%,transparent)] p-3 @2xl:p-4';

/** Kleines Etikett (Risiko, Status, Phase). */
export function Marke(p: { ton?: 'ok' | 'warn' | 'fehler' | 'leise'; children: JSX.Element }): JSX.Element {
  return (
    <span
      class="inline-flex min-h-5 items-center rounded-full px-2 text-[0.72rem] font-semibold leading-none"
      classList={{
        'bg-(--color-success-soft) text-(--color-success)': p.ton === 'ok',
        'bg-(--color-warn-soft) text-(--color-warn)': p.ton === 'warn',
        'bg-(--color-error-soft) text-(--color-error)': p.ton === 'fehler',
        'bg-[color-mix(in_oklab,var(--color-fg)_9%,transparent)] text-(--color-fg-muted)': !p.ton || p.ton === 'leise',
      }}
    >
      {p.children}
    </span>
  );
}

export function Leer(p: { children: JSX.Element }): JSX.Element {
  return <p class="m-0 px-2 py-8 text-center text-sm text-(--color-fg-muted)">{p.children}</p>;
}

function Inline(p: { teile: InlineTeil[] }): JSX.Element {
  return (
    <For each={p.teile}>
      {(t) =>
        t.art === 'code' ? (
          <code class="rounded-md bg-[color-mix(in_oklab,var(--color-fg)_10%,transparent)] px-1 py-px font-mono text-[0.85em]">{t.text}</code>
        ) : t.art === 'fett' ? (
          <strong>{t.text}</strong>
        ) : t.art === 'kursiv' ? (
          <em>{t.text}</em>
        ) : t.art === 'link' ? (
          <a href={t.url} target="_blank" rel="noopener noreferrer" class={`rounded-sm break-all text-(--color-accent) underline underline-offset-2 hover:no-underline ${FOKUS}`}>
            {t.text}
          </a>
        ) : (
          <>{t.text}</>
        )
      }
    </For>
  );
}

/** Ein Codeblock für sich: Monospace, eigener Rahmen, Sprache und Kopieren oben. */
function Codeblock(p: { sprache: string; text: string }): JSX.Element {
  const [kopiert, setKopiert] = createSignal(false);
  const kopiere = () => {
    try {
      void navigator.clipboard?.writeText(p.text).then(() => {
        setKopiert(true);
        setTimeout(() => setKopiert(false), 1500);
      });
    } catch {
      /* ohne Zwischenablage bleibt der Text markierbar */
    }
  };
  return (
    <div class="overflow-hidden rounded-xl border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)]" data-codeblock>
      <div class="flex min-h-7 items-center justify-between gap-2 border-b border-(--color-border) px-2.5 text-[0.7rem] text-(--color-fg-muted)">
        <span class="font-mono">{p.sprache || 'text'}</span>
        <button type="button" class={`rounded-md px-1.5 py-0.5 hover:text-(--color-fg) ${FOKUS}`} onClick={kopiere}>
          {kopiert() ? tr('Kopiert') : tr('Kopieren')}
        </button>
      </div>
      <pre class="m-0 max-h-80 overflow-auto p-2.5 font-mono text-[0.8rem] leading-snug whitespace-pre" data-sprache={p.sprache || undefined}>
        {p.text}
      </pre>
    </div>
  );
}

/** Markdown in klein (Absätze, Listen, Überschriften, Code, Links) — als Elemente, nie als HTML-Text. */
export function Text(p: { text: string }): JSX.Element {
  return (
    <div class="min-w-0 break-words text-[0.92rem] leading-[1.5] [&>*+*]:mt-2">
      <For each={textTeile(p.text)}>
        {(t) => {
          if (t.art === 'code') return <Codeblock sprache={t.sprache} text={t.text} />;
          if (t.art === 'ueberschrift')
            return (
              <p class="m-0 font-semibold">
                <Inline teile={t.teile} />
              </p>
            );
          if (t.art === 'liste') {
            return (
              <Dynamic component={t.geordnet ? 'ol' : 'ul'} class="m-0 pl-5" classList={{ 'list-decimal': t.geordnet, 'list-disc': !t.geordnet }}>
                <For each={t.punkte}>
                  {(punkt) => (
                    <li>
                      <Inline teile={punkt} />
                    </li>
                  )}
                </For>
              </Dynamic>
            );
          }
          return (
            <p class="m-0 whitespace-pre-wrap">
              <Inline teile={t.teile} />
            </p>
          );
        }}
      </For>
    </div>
  );
}

const ZUGANG_HILFE: Record<string, string> = {
  anmeldung: 'Vor dem Agenten steht eine Anmeldung. Einmal anmelden, dann geht es hier weiter.',
  token: 'Der Runner nimmt das Token nicht an: FYOS_AGENT_TOKEN der Shell (nginx) muss zum Token des Runners passen; danach die Shell neu starten.',
  'nicht-freigegeben': ('Der Weg /api/agent ist zu: die Shell leitet ihn nicht weiter (FYOS_AGENT_UPSTREAM?) oder der Kopf X-FYOS-Agent fehlt.'),
  'nicht-erreichbar': ('Der Runner antwortet nicht. Läuft der Dienst, und stimmt FYOS_AGENT_UPSTREAM?'),
  netz: 'Der Browser kommt nicht durch. Netz oder VPN prüfen.',
  server: 'Der Runner hat einen Fehler gemeldet.',
  anfrage: 'Der Runner hat die Anfrage abgelehnt.',
};

/** Wenn der Zugang zum Runner nicht klappt: sagt ehrlich, woran es liegt, und bietet den nächsten Schritt an. */
export function Zugangsfehler(p: { fehler: RunnerFehler; erneut: () => void; anmelden: () => void }): JSX.Element {
  return (
    <div role="alert" class="mx-auto flex max-w-lg flex-col items-start gap-3 py-8">
      <div class="flex items-center gap-2">
        <Punkt ton="fehler" />
        <h2 class="m-0 text-base font-semibold">{p.fehler.titel}</h2>
      </div>
      <p class="m-0 text-sm text-(--color-fg-muted)">{tr(ZUGANG_HILFE[p.fehler.art] ?? '')}</p>
      <Show when={p.fehler.message && p.fehler.message !== p.fehler.titel}>
        <p class="m-0 text-xs text-(--color-fg-subtle)">{p.fehler.message}</p>
      </Show>
      <div class="flex flex-wrap gap-2">
        <Show when={p.fehler.art === 'anmeldung'}>
          <button type="button" class={KNOPF_VOLL} onClick={p.anmelden}>
            {tr('Anmelden')}
          </button>
        </Show>
        <button type="button" class={KNOPF} onClick={p.erneut}>
          {tr('Erneut versuchen')}
        </button>
      </div>
    </div>
  );
}
