/**
 * Läufe — langes Arbeiten mit Phasen und eigenem Kindgespräch. Liste, Kindgespräch öffnen, abbrechen, neuer Lauf.
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { laeuft, laufTon, statusText } from '~/lib/agent-runner/laeufe';
import { fehlerText, vor } from '~/lib/agent-runner/text';
import type { Lauf } from '~/lib/agent-runner/typen';
import { FELD, Fehler, KARTE_ZEILE, KNOPF, KNOPF_VOLL, Laedt, Leer, Marke } from './gemeinsam';
import { tr } from '~/lib/i18n';

const MARKEN_TON = { laeuft: 'warn', fertig: 'ok', fehler: 'fehler', offen: 'leise' } as const;

function LaufKarte(p: {
  l: Lauf;
  oeffneKind: (id: number) => void;
  abbrechen: (id: string) => Promise<void>;
  zurFreigabe: () => void;
}): JSX.Element {
  const [arbeitet, setArbeitet] = createSignal(false);
  const [fehler, setFehler] = createSignal('');
  const abbrechen = async () => {
    setArbeitet(true);
    setFehler('');
    try {
      await p.abbrechen(p.l.id);
    } catch (f) {
      setFehler(fehlerText(f));
    } finally {
      setArbeitet(false);
    }
  };
  const ergebnis = () => p.l.antwort || p.l.fehler || p.l.notiz || '';
  return (
    <article class={KARTE_ZEILE} data-lauf={p.l.id} data-status={p.l.status} aria-label={tr('Lauf: {0}', p.l.titel ?? p.l.id)}>
      <div class="flex flex-wrap items-start justify-between gap-2">
        <h3 class="m-0 min-w-0 flex-[1_1_12rem] text-[0.95rem] font-semibold">{p.l.titel || tr('Lauf')}</h3>
        <div class="flex flex-wrap items-center gap-1.5">
          <Marke ton={MARKEN_TON[laufTon(p.l)]}>{statusText(p.l)}</Marke>
          <Show when={p.l.phase}>
            <Marke>{p.l.phase}</Marke>
          </Show>
          <Show when={p.l.quelle}>
            <Marke>{p.l.quelle}</Marke>
          </Show>
        </div>
      </div>
      <Show when={p.l.auftrag}>
        <p class="m-0 mt-1.5 text-sm text-(--color-fg-muted) whitespace-pre-wrap break-words">{p.l.auftrag}</p>
      </Show>
      <Show when={ergebnis()}>
        <p class="m-0 mt-1.5 text-sm whitespace-pre-wrap break-words">{ergebnis()}</p>
      </Show>
      <p class="m-0 mt-2 text-xs text-(--color-fg-subtle)">
        #{p.l.id}
        <Show when={p.l.erstellt}> · gestartet {vor(p.l.erstellt)}</Show>
        <Show when={p.l.taskStatus}> · {p.l.taskStatus}</Show>
      </p>
      <div class="mt-3 flex flex-wrap gap-2">
        <Show when={p.l.kindId}>
          <button type="button" class={KNOPF} onClick={() => p.oeffneKind(p.l.kindId!)}>
            {tr('Kindgespräch öffnen')}
          </button>
        </Show>
        <Show when={p.l.freigabeId && laeuft(p.l)}>
          <button type="button" class={KNOPF} onClick={p.zurFreigabe}>
            {tr('Wartet auf Freigabe')}
          </button>
        </Show>
        <Show when={laeuft(p.l)}>
          <button type="button" class={KNOPF} disabled={arbeitet()} aria-busy={arbeitet()} onClick={() => void abbrechen()}>
            {arbeitet() ? tr('Breche ab …') : tr('Abbrechen')}
          </button>
        </Show>
      </div>
      <Show when={fehler()}>
        <div class="mt-2">
          <Fehler text={fehler()} />
        </div>
      </Show>
    </article>
  );
}

export function Laeufe(p: {
  laeufe: Lauf[];
  geladen: boolean;
  fehler: string | null;
  erneut: () => void;
  oeffneKind: (id: number) => void;
  abbrechen: (id: string) => Promise<void>;
  neu: (titel: string, auftrag: string) => Promise<unknown>;
  zurFreigabe: () => void;
}): JSX.Element {
  const [formular, setFormular] = createSignal(false);
  const [titel, setTitel] = createSignal('');
  const [auftrag, setAuftrag] = createSignal('');
  const [sendet, setSendet] = createSignal(false);
  const [fehler, setFehler] = createSignal('');
  const absenden = async (e: Event) => {
    e.preventDefault();
    if (!titel().trim() || !auftrag().trim() || sendet()) return;
    setSendet(true);
    setFehler('');
    try {
      await p.neu(titel(), auftrag());
      setTitel('');
      setAuftrag('');
      setFormular(false);
    } catch (f) {
      setFehler(fehlerText(f));
    } finally {
      setSendet(false);
    }
  };
  return (
    <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain p-0.5" data-tab="laeufe">
      <div class="flex items-center justify-between gap-2 px-1">
        <h2 class="os-titel m-0">{tr('Läufe')}</h2>
        <button type="button" class={KNOPF} aria-expanded={formular()} onClick={() => setFormular((f) => !f)}>
          {formular() ? tr('Schließen') : tr('Neuer Lauf')}
        </button>
      </div>
      <Show when={formular()}>
        <form class={`${KARTE_ZEILE} flex flex-col gap-2`} onSubmit={(e) => void absenden(e)} aria-label={tr('Neuer Lauf')}>
          <label class="flex flex-col gap-1 text-xs font-semibold text-(--color-fg-muted)">
            {tr('Titel')}
            <input class={FELD} value={titel()} onInput={(e) => setTitel(e.currentTarget.value)} placeholder={tr('z. B. Cluster prüfen')} maxLength={120} required />
          </label>
          <label class="flex flex-col gap-1 text-xs font-semibold text-(--color-fg-muted)">
            {tr('Auftrag')}
            <textarea class={`${FELD} min-h-20`} value={auftrag()} onInput={(e) => setAuftrag(e.currentTarget.value)} placeholder={tr('Was soll der Lauf tun?')} required />
          </label>
          <p class="m-0 text-xs text-(--color-fg-subtle)">{tr('Der Lauf bekommt ein eigenes Kindgespräch und überlebt Abstürze. Er startet vom offenen Gespräch aus.')}</p>
          <Show when={fehler()}>
            <Fehler text={fehler()} />
          </Show>
          <div>
            <button type="submit" class={KNOPF_VOLL} disabled={sendet() || !titel().trim() || !auftrag().trim()}>
              {sendet() ? tr('Starte …') : tr('Lauf starten')}
            </button>
          </div>
        </form>
      </Show>
      <Show when={p.fehler}>
        <Fehler text={tr('Läufe nicht abrufbar: {0}', p.fehler)} nochmal={p.erneut} />
      </Show>
      <Show when={p.geladen || p.fehler} fallback={<Laedt text={tr('Läufe werden geladen')} />}>
        <Show when={p.laeufe.length} fallback={<Leer>{tr('Noch kein Lauf. Ein Lauf ist ein dauerhafter Auftrag mit Phasen und eigenem Kindgespräch.')}</Leer>}>
          <For each={p.laeufe}>
            {(l) => <LaufKarte l={l} oeffneKind={p.oeffneKind} abbrechen={p.abbrechen} zurFreigabe={p.zurFreigabe} />}
          </For>
        </Show>
      </Show>
    </div>
  );
}
