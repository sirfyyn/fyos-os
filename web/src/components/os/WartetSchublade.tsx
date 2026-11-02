/**
 * WartetSchublade — „Wartet auf dich“ als Schublade von rechts aus der Menüleiste (OS-Neubau P2, 31.10.2026).
 *
 * Vorlage: Artboard „Wartet auf dich“ der Mockup-Leinwand (claude.ai/artifact/NM5ji3eSVLPKBs1CtvSCqy). Eine Liste aus
 * `wartet.eingang` (lib/os/wartet.ts), gruppiert in „Freigabe · nicht umkehrbar“ (einzeln, Halten) und „Fragen ·
 * umkehrbar“; unten „Alle n umkehrbaren erlauben“. Runner-Freigaben zeigt die bestehende `FreigabeKarte`.
 * Die Schublade bleibt im DOM (inert, wenn zu), damit Öffnen und Schließen gleitet; Esc und Klick daneben schließen.
 */
import { For, Show, createEffect, createMemo, createSignal, on, type JSX } from 'solid-js';
import { Portal } from 'solid-js/web';
import { FreigabeKarte } from '~/components/os/nativ/agent/FreigabeKarte';
import { KNOPF, KNOPF_VOLL } from '~/components/zentrale/bausteine';
import type { Freigabe } from '~/lib/agent-runner/typen';
import {
  buendelIds,
  gruppiere,
  wartetAntworten,
  wartetBuendel,
  wartetEingang,
  wartetFehler,
  wartetLaden,
  zahlText,
  type WartetAktion,
  type WartetEintrag,
} from '~/lib/os/wartet';
import { WartetKarte } from './WartetKarte';
import { tr } from '~/lib/i18n';

type Filter = 'alle' | 'fragen' | 'freigaben';

const ABSCHNITT = 'm-0 font-mono text-[0.7rem] font-semibold uppercase tracking-[0.12em]';
const FILTER = 'min-h-8 rounded-lg border px-3 text-[0.8rem] font-medium transition-colors duration-150';

/** Runner-Eintrag → Form der `FreigabeKarte` (Satz als Aktion; den rohen Befehl zeigt die Schublade nicht). */
export function alsFreigabe(e: WartetEintrag): Freigabe {
  return {
    id: e.id,
    aktion: e.satz,
    risiko: e.risiko ?? undefined,
    kontext: e.kontext ?? e.warum,
    zerstoererisch: e.zerstoererisch,
    werkzeug: e.werkzeug ?? undefined,
    status: 'offen',
    erstellt: e.seit ? Date.parse(e.seit) : undefined,
    gespraechTitel: e.gespraech ?? undefined,
  };
}

export function WartetSchublade(p: { offen: boolean; schliessen: () => void; oeffne: (ziel: string) => void }): JSX.Element {
  const [filter, setFilter] = createSignal<Filter>('alle');
  const [buendelLaeuft, setBuendelLaeuft] = createSignal(false);
  const [hinweis, setHinweis] = createSignal('');
  let flaeche: HTMLElement | undefined;
  let vorher: Element | null = null;

  const eintraege = () => wartetEingang()?.eintraege ?? [];
  const gruppen = createMemo(() => gruppiere(eintraege()));
  const buendel = createMemo(() => buendelIds(eintraege()));
  const zeigeFreigaben = () => filter() !== 'fragen';
  const zeigeFragen = () => filter() !== 'freigaben';

  createEffect(
    on(
      () => p.offen,
      (offen, war) => {
        if (offen && !war) {
          vorher = document.activeElement;
          setHinweis('');
          void wartetLaden(true);
          queueMicrotask(() => flaeche?.querySelector<HTMLElement>('[data-wartet-zu]')?.focus());
        } else if (!offen && war && vorher instanceof HTMLElement) {
          vorher.focus();
          vorher = null;
        }
      },
    ),
  );

  const antworte = async (e: WartetEintrag, a: WartetAktion, mehr: { bestaetigt?: boolean } = {}) => {
    if (a === 'oeffnen') {
      // Das Ziel steht im Eintrag; dafür braucht es keinen Weg zum Hub.
      p.schliessen();
      p.oeffne(e.ziel);
      return;
    }
    const r = await wartetAntworten(e.id, a, mehr);
    if (r.warnungen?.length) setHinweis(r.warnungen.join(' '));
  };
  const runnerEntscheide = async (id: string, e: 'erteilt' | 'abgelehnt') => {
    const eintrag = eintraege().find((x) => x.id === id);
    if (!eintrag) return;
    await antworte(eintrag, e === 'erteilt' ? 'ja' : 'nein', e === 'erteilt' && eintrag.zerstoererisch ? { bestaetigt: true } : {});
  };
  const alleErlauben = async () => {
    setBuendelLaeuft(true);
    setHinweis('');
    try {
      const r = await wartetBuendel(buendel());
      setHinweis(r.text ?? '');
    } catch (f) {
      setHinweis(f instanceof Error ? f.message : String(f));
    } finally {
      setBuendelLaeuft(false);
    }
  };

  const karte = (e: WartetEintrag): JSX.Element =>
    e.quelle === 'runner' ? (
      <FreigabeKarte f={alsFreigabe(e)} entscheide={runnerEntscheide} spaeter={() => void antworte(e, 'spaeter')} halten />
    ) : (
      <WartetKarte e={e} antworte={antworte} />
    );

  const filterKnopf = (f: Filter, text: string, n: number) => (
    <button
      type="button"
      class={FILTER}
      classList={{
        'border-(--color-fg) bg-(--color-fg) text-(--color-bg)': filter() === f,
        'border-(--os-glas-rand) text-(--color-fg)': filter() !== f,
      }}
      aria-pressed={filter() === f}
      onClick={() => setFilter(f)}
    >
      {text} {n}
    </button>
  );

  // Als Portal an <body>: die Shell skaliert ihren Inhalt (transform), darin wäre `fixed` nicht der Bildschirm.
  return (
    <Portal>
    <div class="fixed inset-0 z-[900]" classList={{ 'pointer-events-none': !p.offen }} inert={!p.offen} aria-hidden={!p.offen}>
      <div
        class="absolute inset-0 bg-black/40 transition-opacity duration-200 ease-out motion-reduce:transition-none"
        classList={{ 'opacity-0': !p.offen, 'opacity-100': p.offen }}
        onClick={() => p.schliessen()}
      />
      <aside
        ref={flaeche}
        role="dialog"
        aria-modal="true"
        aria-label={tr('Wartet auf dich')}
        data-wartet-schublade
        class="absolute top-0 right-0 bottom-0 flex w-[min(520px,100vw)] flex-col border-l border-(--os-glas-rand) bg-(--os-menue-bg) shadow-[-24px_0_60px_rgba(0,0,0,0.45)] backdrop-blur-xl transition-transform duration-[260ms] ease-[cubic-bezier(0.22,1.2,0.36,1)] motion-reduce:transition-none"
        classList={{ 'translate-x-full': !p.offen, 'translate-x-0': p.offen }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            p.schliessen();
          }
        }}
      >
        <header class="flex flex-col gap-3 border-b border-(--os-glas-rand) px-6 pt-5 pb-3.5">
          <div class="flex items-center justify-between gap-3">
            <h2 class="m-0 text-[1.35rem] font-bold text-(--color-fg)">{tr('Wartet auf dich')}</h2>
            <button type="button" data-wartet-zu class={`${KNOPF} w-10 justify-center px-0`} aria-label={tr('Schließen')} onClick={() => p.schliessen()}>
              <svg aria-hidden="true" viewBox="0 0 16 16" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
              </svg>
            </button>
          </div>
          <p class="m-0 text-[0.84rem] leading-snug text-(--color-fg-muted)">{wartetEingang()?.satz ?? tr('Lädt …')}</p>
          <div role="group" aria-label={tr('Filter')} class="flex flex-wrap gap-1.5">
            {filterKnopf('alle', 'Alle', eintraege().length)}
            {filterKnopf('fragen', 'Fragen', gruppen().fragen.length)}
            {filterKnopf('freigaben', 'Freigaben', gruppen().freigaben.length)}
          </div>
        </header>

        <div class="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto overscroll-contain px-6 py-4">
          <Show when={wartetFehler() && !wartetEingang()}>
            <p role="alert" class="m-0 rounded-xl bg-(--color-warn-soft) px-3 py-2 text-sm">{tr('Nicht erreichbar:')}{' '}{wartetFehler()}</p>
          </Show>
          <Show when={wartetEingang() && eintraege().length === 0}>
            <p class="m-0 py-10 text-center text-sm text-(--color-fg-muted)">{zahlText(0)}.</p>
          </Show>
          <Show when={zeigeFreigaben() && gruppen().freigaben.length > 0}>
            <h3 class={`${ABSCHNITT} text-(--color-error)`}>{tr('Freigabe · nicht umkehrbar')}</h3>
            <For each={gruppen().freigaben}>{karte}</For>
          </Show>
          <Show when={zeigeFragen() && gruppen().fragen.length > 0}>
            <h3 class={`${ABSCHNITT} mt-1.5 text-(--color-fg-muted)`}>{tr('Fragen · umkehrbar')}</h3>
            <For each={gruppen().fragen}>{karte}</For>
          </Show>
        </div>

        <footer class="flex items-center gap-3 border-t border-(--os-glas-rand) bg-[color-mix(in_oklab,var(--color-bg)_40%,transparent)] px-6 py-4">
          <Show
            when={buendel().length > 0}
            fallback={<span class="text-[0.8rem] text-(--color-fg-muted)">{hinweis() || tr('Nichts zum Bündeln.')}</span>}
          >
            <button type="button" class={`${KNOPF_VOLL} min-h-10`} disabled={buendelLaeuft()} aria-busy={buendelLaeuft()} onClick={() => void alleErlauben()}>
              {buendelLaeuft() ? tr('Erlaube …') : tr('Alle {0} umkehrbaren erlauben', buendel().length)}
            </button>
            <span class="text-[0.8rem] leading-snug text-(--color-fg-muted)" aria-live="polite">
              {hinweis() || (gruppen().freigaben.length ? tr('Nicht Umkehrbares bleibt außen vor.') : tr('Umkehrbar, du kannst es zurücknehmen.'))}
            </span>
          </Show>
        </footer>
      </aside>
    </div>
    </Portal>
  );
}
