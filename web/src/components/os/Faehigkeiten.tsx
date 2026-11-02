/**
 * Faehigkeiten — feste Schalter rechts in der Menüleiste: der Agent, Voice (die Stimme) und Eyes
 * (Erkennung über Kameras). Wie die Statussymbole am Mac: das Symbol zeigt auf einen Blick, was an ist (Voice an =
 * oranger Punkt wie das Mikrofon-Zeichen, Eyes an = grün); ein Klick öffnet ein kleines Panel mit allen Schaltern.
 * Zustand: lib/os/faehigkeiten.ts. Was ein Plugin nicht liefert, steht ehrlich als „Noch nicht eingerichtet.“ da.
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { Portal } from 'solid-js/web';
import { agentName } from '~/lib/config';
import { anstossen, laden, schalten, type Faehigkeit, type FaehigkeitId } from '~/lib/os/faehigkeiten';
import { TON_HILFE, TON_MODI, TON_NAMEN, tonModusLesen, tonModusSchreiben, type TonModus } from '~/lib/os/ton-modus';
import { tr } from '~/lib/i18n';

const REIHE: FaehigkeitId[] = ['agent', 'stimme', 'augen'];
const TAKT_MS = 60_000;

// Funktionen statt fertiger Knoten: dasselbe Symbol steht in Leiste und Panel.
const SYMBOL: Record<FaehigkeitId, () => JSX.Element> = {
  agent: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M9.94 14.06 4 20M14 4l1.5 4.5L20 10l-4.5 1.5L14 16l-1.5-4.5L8 10l4.5-1.5z" />
    </svg>
  ),
  stimme: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4" />
    </svg>
  ),
  augen: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
};

const NAME: Record<FaehigkeitId, () => string> = { agent: () => agentName(), stimme: () => 'Stimme', augen: () => 'Augen' };

export default function Faehigkeiten(p: { oeffne: (flaeche: string) => void }): JSX.Element {
  const [stand, setStand] = createSignal<Partial<Record<FaehigkeitId, Faehigkeit>>>({});
  // `wurzel`: die Shell — dort hängt das Panel (die Menüleiste schneidet ab, wie beim Kontrollzentrum)
  const [offen, setOffen] = createSignal<{ id: FaehigkeitId; rechts: number; wurzel: HTMLElement } | null>(null);
  const [laeuft, setLaeuft] = createSignal<string | null>(null);
  const [fehler, setFehler] = createSignal('');
  // Ton gilt je Gerät; nichts gewählt = „Ton“ (mit Kopfhörern meldet der Hub dann „zurückhaltend“)
  const [ton, setTon] = createSignal<TonModus>(tonModusLesen() ?? 'ton');
  const tonWaehlen = (m: TonModus) => {
    setTon(m);
    tonModusSchreiben(m);
  };
  let panel: HTMLDivElement | undefined;

  const neu = async (id: FaehigkeitId) => {
    const f = await laden(id);
    setStand((s) => ({ ...s, [id]: f }));
  };
  const alle = () => Promise.all(REIHE.map(neu));

  onMount(() => {
    void alle();
    const takt = setInterval(() => { if (document.visibilityState === 'visible') void alle(); }, TAKT_MS);
    const zu = (e: Event) => {
      if (!offen()) return;
      if (e instanceof KeyboardEvent) {
        if (e.key === 'Escape') setOffen(null);
        return;
      }
      const t = e.target as Element;
      if (panel?.contains(t) || t.closest?.('[data-faehigkeit-knopf]')) return;
      setOffen(null);
    };
    window.addEventListener('pointerdown', zu, true);
    window.addEventListener('keydown', zu);
    onCleanup(() => {
      clearInterval(takt);
      window.removeEventListener('pointerdown', zu, true);
      window.removeEventListener('keydown', zu);
    });
  });

  const umschalten = (id: FaehigkeitId, e: MouseEvent) => {
    if (offen()?.id === id) return setOffen(null);
    const knopf = e.currentTarget as HTMLElement;
    const r = knopf.getBoundingClientRect();
    setFehler('');
    setOffen({ id, rechts: Math.max(8, window.innerWidth - r.right - 6), wurzel: knopf.closest<HTMLElement>('[data-shell]') ?? document.body });
    void neu(id);
  };

  const kippen = async (id: FaehigkeitId, ziel: string, an: boolean) => {
    setLaeuft(`${id}:${ziel}`);
    setFehler('');
    try {
      const f = await schalten(id, ziel, an);
      setStand((s) => ({ ...s, [id]: f }));
    } catch (e) {
      setFehler(e instanceof Error ? e.message : String(e));
    } finally {
      setLaeuft(null);
    }
  };

  const anstoss = async (schleife: string) => {
    setLaeuft(`agent:anstoss:${schleife}`);
    setFehler('');
    try {
      const f = await anstossen(schleife);
      setStand((s) => ({ ...s, agent: f }));
    } catch (e) {
      setFehler(e instanceof Error ? e.message : String(e));
    } finally {
      setLaeuft(null);
    }
  };

  const f = () => (offen() ? stand()[offen()!.id] : undefined);

  return (
    <>
      <For each={REIHE}>
        {(id) => {
          const s = () => stand()[id];
          const text = () => {
            const x = s();
            if (!x) return x;
            const zustand = x.aktiv == null ? tr('nicht eingerichtet') : x.aktiv ? 'an' : 'aus';
            return `${x.name}: ${zustand}`;
          };
          return (
            <button
              type="button"
              data-faehigkeit-knopf
              class="os-leiste-punkt os-faehigkeit"
              classList={{
                'os-leiste-an': offen()?.id === id,
                'os-faehigkeit-an': s()?.aktiv === true,
                'os-faehigkeit-weg': s()?.aktiv == null,
              }}
              data-faehigkeit={id}
              aria-label={text() ?? NAME[id]()}
              aria-expanded={offen()?.id === id}
              title={s()?.satz || text() || undefined}
              onClick={(e) => umschalten(id, e)}
            >
              {SYMBOL[id]()}
              <Show when={id === 'agent'}>
                <span class="max-lg:hidden">{s()?.aktiv == null ? agentName() : s()?.aktiv ? agentName() : `${agentName()} aus`}</span>
              </Show>
            </button>
          );
        }}
      </For>

      <Show when={offen() && f()}>
        <Portal mount={offen()!.wurzel}>
        <div ref={panel} role="dialog" aria-label={f()!.name} class="os-kz os-menue os-faehigkeit-panel" style={{ right: `${offen()!.rechts}px` }}>
          <header class="os-faehigkeit-kopf">
            <span class="os-faehigkeit-symbol" data-faehigkeit={f()!.id} classList={{ 'os-faehigkeit-an': f()!.aktiv === true }}>{SYMBOL[f()!.id]()}</span>
            <div class="min-w-0 flex-1">
              <p class="m-0 font-semibold">{f()!.name}</p>
              <p class="m-0 text-(--color-fg-muted)">{f()!.satz || (f()!.aktiv ? 'An' : tr('Aus'))}</p>
            </div>
            <Show when={f()!.schalter.length > 1}>
              <label class="os-kipper" title={tr('Alle')}>
                <input
                  type="checkbox"
                  aria-label={`${f()!.name}: alle`}
                  checked={f()!.schalter.some((x) => x.an)}
                  disabled={laeuft() != null}
                  onChange={(e) => void kippen(f()!.id, 'alle', e.currentTarget.checked)}
                />
                <span />
              </label>
            </Show>
          </header>
          <Show when={f()!.schalter.length}>
            <ul class="os-faehigkeit-liste">
              <For each={f()!.schalter}>
                {(x) => (
                  <li>
                    <div class="min-w-0 flex-1">
                      <span>{x.text}</span>
                      <Show when={x.hinweis}><small class="block line-clamp-2 break-words text-(--color-fg-muted)" title={x.hinweis}>{x.hinweis}</small></Show>
                      <Show when={x.anstoss === 'laeuft'}><small class="block text-(--color-fg-muted)">{tr('Angestoßen')}</small></Show>
                      <Show when={x.anstoss === 'moeglich'}>
                        <button
                          type="button"
                          class="mt-1 block text-xs underline underline-offset-2 disabled:opacity-50"
                          data-agent-anstossen={x.id}
                          title={tr('{0} sofort einen Durchgang machen lassen', x.text)}
                          disabled={laeuft() != null}
                          onClick={() => void anstoss(x.id)}
                        >
                          {laeuft() === `agent:anstoss:${x.id}` ? tr('Wird angestoßen …') : tr('Jetzt anstoßen')}
                        </button>
                      </Show>
                    </div>
                    <label class="os-kipper">
                      <input
                        type="checkbox"
                        aria-label={`${f()!.name}: ${x.text}`}
                        checked={x.an}
                        disabled={laeuft() != null}
                        onChange={(e) => void kippen(f()!.id, x.id, e.currentTarget.checked)}
                      />
                      <span />
                    </label>
                  </li>
                )}
              </For>
            </ul>
          </Show>
          <Show when={fehler()}><p role="alert" class="m-0 px-1 text-xs text-(--color-error)">{fehler()}</p></Show>
          <Show when={f()!.id === 'agent'}>
            <div class="px-1" role="radiogroup" aria-label={tr('Ton an diesem Gerät')} data-agent-ton>
              <p class="m-0 mb-1 text-xs text-(--color-fg-muted)">{tr('Ton an diesem Gerät')}</p>
              <div class="flex gap-1">
                <For each={TON_MODI}>
                  {(m) => (
                    <button
                      type="button"
                      role="radio"
                      aria-checked={ton() === m}
                      data-ton={m}
                      title={tr(TON_HILFE[m])}
                      class="flex-1 rounded px-1 py-0.5 text-xs"
                      classList={{ 'bg-(--color-accent-soft) font-semibold': ton() === m, 'underline-offset-2 hover:underline': ton() !== m }}
                      onClick={() => tonWaehlen(m)}
                    >
                      {tr(TON_NAMEN[m])}
                    </button>
                  )}
                </For>
              </div>
              <p class="m-0 mt-1 text-xs text-(--color-fg-muted)">{tr(TON_HILFE[ton()])}</p>
            </div>
          </Show>
          <Show when={f()!.oeffnen}>
            <button type="button" class="os-faehigkeit-mehr" onClick={() => { p.oeffne(f()!.oeffnen!); setOffen(null); }}>
              {f()!.name}-Einstellungen …
            </button>
          </Show>
        </div>
        </Portal>
      </Show>
    </>
  );
}
