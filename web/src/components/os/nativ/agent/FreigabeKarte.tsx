/**
 * FreigabeKarte — eine Freigabe als Karte: Aktion, Risiko, Kontext (gekürzt), Befehl; Erlauben, Ablehnen, Später.
 * Dieselbe Karte steht direkt im Verlauf (wenn der Agent im offenen Gespräch auf dich wartet) und in der Liste der Freigaben.
 * „Später“ stellt die Karte nur im Verlauf zurück; sie bleibt offen und zählt weiter in der Liste und im Kopf.
 */
import { Show, createSignal, type JSX } from 'solid-js';
import { befehlsZeile, istOffen, risikoText } from '~/lib/agent-runner/freigaben';
import { fehlerText, vor } from '~/lib/agent-runner/text';
import type { Freigabe } from '~/lib/agent-runner/typen';
import { Fehler, KARTE_ZEILE, KNOPF, KNOPF_VOLL, Marke } from './gemeinsam';
import { WartetHalten } from '../../WartetHalten';
import { tr } from '~/lib/i18n';

export const KONTEXT_MAX = 280;

export function kuerzeKontext(t: string | null | undefined, max: number = KONTEXT_MAX): string {
  const s = String(t ?? '').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

export function FreigabeKarte(p: {
  f: Freigabe;
  entscheide: (id: string, e: 'erteilt' | 'abgelehnt') => Promise<void>;
  /** Stellt die Karte im Verlauf zurück (nur dort angeboten). */
  spaeter?: (id: string) => void;
  /** Im Verlauf: Kontext gekürzt, Gesprächstitel weglassen. */
  kompakt?: boolean;
  /** Zerstörerisches erst nach Halten erlauben (Schublade „Wartet auf dich“). */
  halten?: boolean;
}): JSX.Element {
  const [arbeitet, setArbeitet] = createSignal<'erteilt' | 'abgelehnt' | null>(null);
  const [fehler, setFehler] = createSignal('');
  const [ganz, setGanz] = createSignal(false);
  const los = async (e: 'erteilt' | 'abgelehnt') => {
    setArbeitet(e);
    setFehler('');
    try {
      await p.entscheide(p.f.id, e);
    } catch (f) {
      setFehler(fehlerText(f));
    } finally {
      setArbeitet(null);
    }
  };
  const risikoTon = () => (p.f.risiko === 'high' ? 'fehler' : p.f.risiko === 'low' ? 'ok' : 'warn');
  const kontext = () => (p.kompakt && !ganz() ? kuerzeKontext(p.f.kontext) : String(p.f.kontext ?? ''));
  const gekuerzt = () => !!p.kompakt && !ganz() && String(p.f.kontext ?? '').trim().length > KONTEXT_MAX;
  return (
    <article
      class={`${KARTE_ZEILE} ${istOffen(p.f) ? 'border-(--color-warn)/45' : ''}`}
      data-freigabe={p.f.id}
      data-status={p.f.status}
      aria-label={tr('Freigabe: {0}', p.f.aktion ?? tr('Aktion'))}
    >
      <div class="flex flex-wrap items-start justify-between gap-2">
        <h3 class="m-0 min-w-0 flex-[1_1_14rem] text-[0.95rem] font-semibold">{p.f.aktion ?? tr('Aktion')}</h3>
        <div class="flex flex-wrap items-center gap-1.5">
          <Marke ton={risikoTon()}>{tr('Risiko')}{' '}{risikoText(p.f.risiko)}</Marke>
          <Show when={p.f.zerstoererisch}>
            <Marke ton="fehler">{tr('zerstörerisch')}</Marke>
          </Show>
          <Show when={!istOffen(p.f)}>
            <Marke ton={p.f.status === 'erteilt' ? 'ok' : 'leise'}>{p.f.status}</Marke>
          </Show>
        </div>
      </div>
      <Show when={kontext()}>
        <p class="m-0 mt-1.5 text-sm text-(--color-fg-muted) whitespace-pre-wrap break-words">
          {kontext()}
          <Show when={gekuerzt()}>
            {' '}
            <button type="button" class="rounded-sm text-(--color-accent) underline underline-offset-2 hover:no-underline" onClick={() => setGanz(true)}>
              mehr
            </button>
          </Show>
        </p>
      </Show>
      <Show when={befehlsZeile(p.f)}>
        <pre class="m-0 mt-2 max-h-40 overflow-auto rounded-lg bg-[color-mix(in_oklab,var(--color-fg)_9%,transparent)] p-2 font-mono text-xs leading-snug whitespace-pre-wrap break-words" aria-label={tr('Befehl')}>
          {befehlsZeile(p.f)}
        </pre>
      </Show>
      <p class="m-0 mt-2 text-xs text-(--color-fg-subtle)">
        <Show when={p.f.gespraechTitel && !p.kompakt}>{p.f.gespraechTitel} · </Show>
        <Show when={p.f.erstellt}>angefragt {vor(p.f.erstellt)}</Show>
        <Show when={p.f.entschieden}>
          {' '}
          · entschieden {vor(p.f.entschieden)}
          <Show when={p.f.entschiedenVon}> von {p.f.entschiedenVon}</Show>
        </Show>
        <Show when={p.f.notiz}> · {p.f.notiz}</Show>
      </p>
      <Show when={istOffen(p.f)}>
        <div class="mt-3 flex flex-wrap gap-2">
          <Show
            when={p.halten && p.f.zerstoererisch}
            fallback={
              <button type="button" class={KNOPF_VOLL} disabled={!!arbeitet()} aria-busy={arbeitet() === 'erteilt'} onClick={() => void los('erteilt')}>
                {arbeitet() === 'erteilt' ? tr('Erlaube …') : tr('Erlauben')}
              </button>
            }
          >
            <WartetHalten class={KNOPF} disabled={!!arbeitet()} onFertig={() => void los('erteilt')}>
              {arbeitet() === 'erteilt' ? tr('Erlaube …') : tr('Halten zum Erlauben')}
            </WartetHalten>
          </Show>
          <button type="button" class={KNOPF} disabled={!!arbeitet()} aria-busy={arbeitet() === 'abgelehnt'} onClick={() => void los('abgelehnt')}>
            {arbeitet() === 'abgelehnt' ? tr('Lehne ab …') : tr('Ablehnen')}
          </button>
          <Show when={p.spaeter}>
            <button type="button" class={KNOPF} disabled={!!arbeitet()} onClick={() => p.spaeter!(p.f.id)} title={tr('Stellt die Karte hier zurück; sie bleibt in der Liste der Freigaben offen')}>
              {tr('Später')}
            </button>
          </Show>
        </div>
      </Show>
      <Show when={fehler()}>
        <div class="mt-2">
          <Fehler text={fehler()} />
        </div>
      </Show>
    </article>
  );
}
