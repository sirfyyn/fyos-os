/**
 * Zustand — Werte, die Mensch und Agent teilen (GET api/zustand): lesen, setzen, löschen.
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { fehlerText, vor, wertText } from '~/lib/agent-runner/text';
import type { GeteilterZustand } from '~/lib/agent-runner/typen';
import { FELD, Fehler, KARTE_ZEILE, KNOPF, KNOPF_VOLL, Laedt, Leer } from './gemeinsam';

export function Zustand(p: {
  zustand: GeteilterZustand | null;
  fehler: string | null;
  erneut: () => void;
  setze: (schluessel: string, eingabe: string) => Promise<void>;
  loesche: (schluessel: string) => Promise<void>;
}): JSX.Element {
  const [schluessel, setSchluessel] = createSignal('');
  const [wert, setWert] = createSignal('');
  const [bearbeitet, setBearbeitet] = createSignal<string | null>(null);
  const [sendet, setSendet] = createSignal(false);
  const [fehler, setFehler] = createSignal('');
  let schluesselFeld: HTMLInputElement | undefined;

  const eintraege = () => Object.entries(p.zustand?.werte ?? {}).sort(([a], [b]) => a.localeCompare(b, 'de'));

  const speichern = async (e: Event) => {
    e.preventDefault();
    if (!schluessel().trim() || sendet()) return;
    setSendet(true);
    setFehler('');
    try {
      await p.setze(schluessel(), wert());
      setSchluessel('');
      setWert('');
      setBearbeitet(null);
    } catch (f) {
      setFehler(fehlerText(f));
    } finally {
      setSendet(false);
    }
  };

  const bearbeiten = (k: string, v: unknown) => {
    setBearbeitet(k);
    setSchluessel(k);
    setWert(typeof v === 'string' ? v : wertText(v));
    schluesselFeld?.scrollIntoView({ block: 'nearest' });
    queueMicrotask(() => schluesselFeld?.focus());
  };

  const loeschen = async (k: string) => {
    setFehler('');
    try {
      await p.loesche(k);
      if (bearbeitet() === k) {
        setBearbeitet(null);
        setSchluessel('');
        setWert('');
      }
    } catch (f) {
      setFehler(fehlerText(f));
    }
  };

  return (
    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-0.5" data-tab="zustand">
      <div class="px-1">
        <h2 class="os-titel m-0">Geteilter Zustand</h2>
        <p class="m-0 mt-0.5 text-xs text-(--color-fg-subtle)">Werte, die {`Agent`} und du gemeinsam sehen. Zahlen, true/false, Listen und Objekte als JSON, alles andere als Text.</p>
      </div>
      <form class={`${KARTE_ZEILE} flex flex-col gap-2`} onSubmit={(e) => void speichern(e)} aria-label={bearbeitet() ? `Wert ${bearbeitet()} ändern` : 'Wert setzen'}>
        <label class="flex flex-col gap-1 text-xs font-semibold text-(--color-fg-muted)">
          Schlüssel
          <input ref={schluesselFeld} class={FELD} value={schluessel()} readOnly={bearbeitet() !== null} onInput={(e) => setSchluessel(e.currentTarget.value)} placeholder="z. B. fokus-projekt" maxLength={120} required />
        </label>
        <label class="flex flex-col gap-1 text-xs font-semibold text-(--color-fg-muted)">
          Wert
          <textarea class={`${FELD} min-h-16 font-mono`} value={wert()} onInput={(e) => setWert(e.currentTarget.value)} placeholder="Text oder JSON" />
        </label>
        <div class="flex flex-wrap gap-2">
          <button type="submit" class={KNOPF_VOLL} disabled={sendet() || !schluessel().trim()}>
            {sendet() ? 'Speichere …' : bearbeitet() ? 'Ändern' : 'Setzen'}
          </button>
          <Show when={bearbeitet() !== null}>
            <button
              type="button"
              class={KNOPF}
              onClick={() => {
                setBearbeitet(null);
                setSchluessel('');
                setWert('');
              }}
            >
              Abbrechen
            </button>
          </Show>
        </div>
      </form>
      <Show when={fehler()}>
        <Fehler text={fehler()} />
      </Show>
      <Show when={p.fehler}>
        <Fehler text={`Zustand nicht abrufbar: ${p.fehler}`} nochmal={p.erneut} />
      </Show>
      <Show when={p.zustand || p.fehler} fallback={<Laedt text="Zustand wird geladen" />}>
        <Show when={eintraege().length} fallback={<Leer>Noch kein geteilter Wert. Der Agent kann hier Werte ablegen; du kannst sie auch selbst setzen.</Leer>}>
          <ul class="m-0 flex list-none flex-col gap-2 p-0">
            <For each={eintraege()}>
              {([k, v]) => (
                <li class={KARTE_ZEILE} data-zustand-schluessel={k}>
                  <div class="flex flex-wrap items-baseline justify-between gap-2">
                    <span class="min-w-0 break-all font-mono text-sm font-semibold">{k}</span>
                    <div class="flex gap-1.5">
                      <button type="button" class={KNOPF} aria-label={`${k} bearbeiten`} onClick={() => bearbeiten(k, v)}>
                        Bearbeiten
                      </button>
                      <button type="button" class={KNOPF} aria-label={`${k} löschen`} onClick={() => void loeschen(k)}>
                        Löschen
                      </button>
                    </div>
                  </div>
                  <pre class="m-0 mt-1.5 max-h-48 overflow-auto rounded-lg bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] p-2 font-mono text-xs leading-snug whitespace-pre-wrap break-words">{typeof v === 'string' ? v : wertText(v)}</pre>
                </li>
              )}
            </For>
          </ul>
        </Show>
        <Show when={p.zustand?.geaendert}>
          <p class="m-0 px-1 text-xs text-(--color-fg-subtle)">
            zuletzt geändert {vor(p.zustand?.geaendert)}
            <Show when={p.zustand?.von}> von {p.zustand?.von}</Show>
          </p>
        </Show>
      </Show>
    </div>
  );
}
