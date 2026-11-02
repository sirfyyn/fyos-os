/**
 * Eingabe — Nachricht an den Agenten.
 *
 * Mehrzeiliges Feld unten: Enter sendet, Umschalt+Enter macht eine neue Zeile. Der Entwurf bleibt je Gespräch erhalten
 * (auch nach Neuladen). Beginnt der Text mit „/“, erscheint ein kleines Menü der Schnellbefehle (/live, /ruhe, /neu, /stopp).
 * Während der Agent arbeitet, gibt es Stopp (Zug abbrechen) und die Wahl „Folgen“ (wartet auf das Ende des Zugs)
 * oder „Steuern“ (greift ein).
 *
 * Anhänge trägt das Protokoll nicht (`POST …/nachricht` nimmt nur Text), eine Spracheingabe gibt es in diesem Client nicht:
 * beides fehlt hier mit Absicht, statt etwas vorzutäuschen.
 */
import { For, Show, createEffect, createMemo, createSignal, createUniqueId, on, type JSX } from 'solid-js';
import { Wahl } from '~/components/einstellungen/bausteine';
import type { SendeArt } from '~/lib/agent-runner/api';
import { passendeBefehle } from '~/lib/agent-runner/befehle';
import { liesEntwurf, schreibeEntwurf } from '~/lib/agent-runner/entwurf';
import { fehlerText } from '~/lib/agent-runner/text';
import { RunnerFehler } from '~/lib/agent-runner/verbindung';
import { FELD, Fehler, KNOPF, KNOPF_VOLL } from './gemeinsam';
import { tr } from '~/lib/i18n';

const ARTEN = [
  { wert: 'folgen', text: 'Folgen', titel: 'Wartet, bis der laufende Zug zu Ende ist' },
  { wert: 'steuern', text: 'Steuern', titel: 'Greift in den laufenden Zug ein' },
] as const;

export function Eingabe(p: {
  agentName: string;
  busy: boolean;
  gesperrt: boolean;
  /** Welches Gespräch offen ist: der Entwurf gehört dazu. */
  gespraechId: number | null;
  sende: (text: string, art: SendeArt) => Promise<unknown>;
  abbrechen: () => Promise<void>;
  anmelden: () => void;
  schmal: boolean;
  /** Text von außen (Frage aus einer App): jedes neue Objekt ersetzt das Feld einmal, gesendet wird erst mit Enter. */
  vorschlag?: { text: string } | null;
}): JSX.Element {
  const [text, setText] = createSignal('');
  const [art, setArt] = createSignal<'folgen' | 'steuern'>('folgen');
  const [sendet, setSendet] = createSignal(false);
  const [fehler, setFehler] = createSignal<RunnerFehler | string | null>(null);
  const [auswahl, setAuswahl] = createSignal(0);
  const [menueZu, setMenueZu] = createSignal(false);
  const menueId = createUniqueId();
  let feld: HTMLTextAreaElement | undefined;
  let offenerVorschlag: string | null = null;

  const hoehe = () => {
    if (!feld) return;
    feld.style.height = 'auto';
    feld.style.height = `${Math.min(feld.scrollHeight, 168)}px`;
  };

  // Der Entwurf gehört zum Gespräch: beim Wechsel (und beim ersten Zeigen) wird er geholt, jede Änderung gespeichert.
  createEffect(
    on(
      () => p.gespraechId,
      (id) => {
        // Kam eine Frage von außen, bevor ein Gespräch offen war, gilt sie statt des gespeicherten Entwurfs.
        setText(offenerVorschlag ?? liesEntwurf(id));
        if (id !== null) offenerVorschlag = null;
        setFehler(null);
        queueMicrotask(hoehe);
      },
    ),
  );
  createEffect(on(text, (t) => schreibeEntwurf(p.gespraechId, t), { defer: true }));
  createEffect(
    on(
      () => p.vorschlag,
      (v) => {
        if (!v?.text) return;
        if (p.gespraechId === null) offenerVorschlag = v.text;
        setText(v.text);
        queueMicrotask(() => {
          hoehe();
          feld?.focus();
        });
      },
    ),
  );

  const vorschlaege = createMemo(() => passendeBefehle(text()));
  const menueOffen = () => vorschlaege().length > 0 && !menueZu();
  createEffect(on(text, () => { setAuswahl(0); setMenueZu(false); }));

  const waehleBefehl = (zeichen: string) => {
    setText(`${zeichen} `);
    queueMicrotask(() => {
      hoehe();
      feld?.focus();
    });
  };

  const senden = async () => {
    const t = text().trim();
    if (!t || sendet() || p.gesperrt) return;
    setSendet(true);
    setFehler(null);
    try {
      await p.sende(t, p.busy ? art() : 'folgen');
      setText('');
      setArt('folgen');
      queueMicrotask(hoehe);
    } catch (f) {
      // Der Text bleibt stehen: nichts geht verloren, wenn der Runner gerade nicht antwortet.
      setFehler(f instanceof RunnerFehler ? f : fehlerText(f));
    } finally {
      setSendet(false);
      feld?.focus();
    }
  };

  const abbrechen = async () => {
    setFehler(null);
    try {
      await p.abbrechen();
    } catch (f) {
      setFehler(f instanceof RunnerFehler ? f : fehlerText(f));
    }
  };

  const taste = (e: KeyboardEvent) => {
    if (e.isComposing) return;
    if (menueOffen()) {
      const n = vorschlaege().length;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setAuswahl((a) => (a + 1) % n);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setAuswahl((a) => (a - 1 + n) % n);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setMenueZu(true);
        return;
      }
      const gewaehlt = vorschlaege()[auswahl()];
      // Tab vervollständigt; Enter auch, solange der Befehl noch nicht ausgeschrieben ist.
      if (gewaehlt && (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && text().trim().toLowerCase() !== gewaehlt.zeichen))) {
        e.preventDefault();
        waehleBefehl(gewaehlt.zeichen);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void senden();
    }
  };

  return (
    <form
      class="flex flex-col gap-2"
      aria-label={tr('Nachricht schreiben')}
      data-eingabe
      onSubmit={(e) => {
        e.preventDefault();
        void senden();
      }}
    >
      <Show when={fehler()}>
        {(f) => (
          <Fehler
            text={typeof f() === 'string' ? (f() as string) : `${(f() as RunnerFehler).titel}: ${(f() as RunnerFehler).message}`}
            nochmal={() => void senden()}
          />
        )}
      </Show>
      <Show when={fehler() instanceof RunnerFehler && (fehler() as RunnerFehler).art === 'anmeldung'}>
        <button type="button" class={KNOPF_VOLL} onClick={() => p.anmelden()}>
          {tr('Anmelden')}
        </button>
      </Show>
      <div class="relative flex items-end gap-2">
        <Show when={menueOffen()}>
          <ul
            id={menueId}
            role="listbox"
            aria-label={tr('Schnellbefehle')}
            class="absolute bottom-full left-0 z-10 mb-1.5 m-0 flex w-[min(22rem,100%)] list-none flex-col gap-0.5 rounded-xl border border-(--os-glas-rand) bg-(--color-bg-opaque) p-1 shadow-[0_10px_30px_-12px_rgb(0_0_0/0.6)]"
            data-befehlsmenue
          >
            <For each={vorschlaege()}>
              {(b, i) => (
                <li
                  id={`${menueId}-${b.name}`}
                  role="option"
                  aria-selected={i() === auswahl()}
                  class="flex min-h-9 cursor-pointer items-baseline gap-3 rounded-lg px-2.5 py-1.5 text-sm"
                  classList={{ 'bg-[color-mix(in_oklab,var(--color-accent)_16%,transparent)]': i() === auswahl() }}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    waehleBefehl(b.zeichen);
                  }}
                  onMouseEnter={() => setAuswahl(i())}
                >
                  <span class="font-mono font-semibold">{b.zeichen}</span>
                  <span class="min-w-0 truncate text-xs text-(--color-fg-muted)">{tr(b.hilfe)}</span>
                </li>
              )}
            </For>
          </ul>
        </Show>
        <textarea
          ref={feld}
          rows={1}
          class={`${FELD} max-h-44 min-h-11 resize-none`}
          aria-label={tr('Nachricht an {0}', p.agentName)}
          aria-controls={menueOffen() ? menueId : undefined}
          aria-expanded={menueOffen()}
          aria-autocomplete="list"
          aria-activedescendant={menueOffen() && vorschlaege()[auswahl()] ? `${menueId}-${vorschlaege()[auswahl()]!.name}` : undefined}
          placeholder={p.busy ? tr('{0} arbeitet … Folgen wartet, Steuern greift ein', p.agentName) : tr('Schreib {0} …  ( / für Befehle )', p.agentName)}
          value={text()}
          disabled={p.gesperrt}
          onInput={(e) => {
            setText(e.currentTarget.value);
            hoehe();
          }}
          onKeyDown={taste}
        />
        <Show when={p.busy}>
          <button type="button" class={`${KNOPF} shrink-0`} onClick={() => void abbrechen()} title={tr('Stoppt den laufenden Zug')} aria-label={tr('Zug abbrechen')} data-stopp>
            <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5 fill-current">
              <rect x="3" y="3" width="10" height="10" rx="2" />
            </svg>
            <span class={p.schmal ? 'sr-only' : ''}>{tr('Stopp')}</span>
          </button>
        </Show>
        <button type="submit" class={`${KNOPF_VOLL} shrink-0`} disabled={!text().trim() || sendet() || p.gesperrt} aria-label={tr('Senden')}>
          <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5 fill-none stroke-current" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2.5 8h10M8.5 3.5 13 8l-4.5 4.5" />
          </svg>
          <span class={p.schmal ? 'sr-only' : ''}>{tr('Senden')}</span>
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Show when={p.busy}>
          <div class="w-44 max-w-full">
            <Wahl name={tr('Art der Nachricht')} optionen={ARTEN} wert={art()} onWahl={setArt} klein />
          </div>
        </Show>
        <Show when={!p.schmal}>
          <p class="m-0 text-xs text-(--color-fg-subtle)">{tr('Enter sendet · Umschalt+Enter neue Zeile · / öffnet die Befehle')}</p>
        </Show>
      </div>
    </form>
  );
}
