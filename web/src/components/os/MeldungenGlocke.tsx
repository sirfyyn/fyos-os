/**
 * MeldungenGlocke — die Glocke in der Menüleiste und der Verlauf des Meldungsdienstes (28.10.2026, lib/os/meldungen.ts).
 *
 * Die Zahl am Symbol sind die ungelesenen Meldungen. Der Verlauf listet die letzten 100 (neueste oben); ein Eintrag öffnet sein Ziel und gilt
 * als gelesen. „Alle gelesen“ und „Leeren“ stehen oben, daneben der Schalter „Nicht stören“ (von Hand; Zeitfenster und Quellen:
 * Einstellungen › Meldungen). Esc und ein Klick daneben schließen; der Fokus kehrt zur Glocke zurück.
 */
import { For, Show, createSignal, onCleanup, type JSX } from 'solid-js';
import { Portal } from 'solid-js/web';
import '~/styles/os-meldungen.css';
import { QUELLEN_NAME, nichtStoerenAktiv } from '~/lib/os/meldungen-einstellungen';
import { aendereEinstellungen, dienst, einstellungen, meldungOeffnen, zustand } from '~/lib/os/meldungen-produktiv';
import type { Meldung } from '~/lib/os/meldungen';
import { Glyphe } from './Symbol';
import { tr } from '~/lib/i18n';

export function zeitKurz(zeit: number, jetzt: number): string {
  const s = Math.max(0, Math.round((jetzt - zeit) / 1000));
  if (s < 60) return 'gerade eben';
  const m = Math.round(s / 60);
  if (m < 60) return `vor ${m} Min`;
  const h = Math.round(m / 60);
  if (h < 24) return `vor ${h} Std`;
  return `vor ${Math.round(h / 24)} Tg`;
}

export default function MeldungenGlocke(p: { onEinstellungen?: () => void }): JSX.Element {
  const [offen, setOffen] = createSignal(false);
  let knopf: HTMLButtonElement | undefined;
  let tafel: HTMLElement | undefined;
  // Die Tafel hängt an der Shell, nicht an der Glocke: .os-glocke ist ein winziges Bezugsfeld, in dem width: 100% auf wenige Pixel schrumpfte.
  const wurzel = () => knopf?.closest<HTMLElement>('[data-shell]') ?? document.body;
  const stumm = () => nichtStoerenAktiv(einstellungen(), new Date());

  const zu = (fokus = true) => {
    setOffen(false);
    document.removeEventListener('pointerdown', daneben, true);
    if (fokus) knopf?.focus();
  };
  const daneben = (e: PointerEvent) => {
    const t = e.target as Node;
    if (tafel?.contains(t) || knopf?.contains(t)) return;
    zu(false);
  };
  const umschalten = () => {
    if (offen()) return zu();
    setOffen(true);
    document.addEventListener('pointerdown', daneben, true);
    queueMicrotask(() => tafel?.querySelector<HTMLElement>('button, [tabindex]')?.focus());
  };
  onCleanup(() => document.removeEventListener('pointerdown', daneben, true));

  const eintrag = (m: Meldung) => {
    if (m.ziel) meldungOeffnen(m);
    else dienst.lies(m.id);
    zu(false);
  };

  return (
    <span class="os-glocke">
      <button
        ref={knopf}
        type="button"
        class="os-leiste-punkt"
        classList={{ 'os-leiste-an': offen() }}
        aria-label={`Meldungen${zustand().ungelesen ? `, ${zustand().ungelesen} ungelesen` : ''}${stumm() ? tr(', Nicht stören ist an') : ''}`}
        aria-haspopup="dialog"
        aria-expanded={offen()}
        title={tr('Meldungen')}
        onClick={umschalten}
      >
        <Glyphe name={stumm() ? 'bell-off' : 'bell'} class="size-4" />
        <Show when={zustand().ungelesen > 0}>
          <span class="os-glocke-zahl" aria-hidden="true">{zustand().ungelesen > 99 ? '99+' : zustand().ungelesen}</span>
        </Show>
      </button>
      <Show when={offen()}>
        <Portal mount={wurzel()}>
        <section
          ref={tafel}
          class="os-verlauf"
          role="dialog"
          aria-label={tr('Verlauf der Meldungen')}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              zu();
            }
          }}
        >
          <div class="os-verlauf-kopf">
            <h2>{tr('Meldungen')}</h2>
            <button
              type="button"
              class="os-verlauf-knopf"
              aria-pressed={einstellungen().nichtStoeren.manuell}
              onClick={() => aendereEinstellungen((e) => ({ ...e, nichtStoeren: { ...e.nichtStoeren, manuell: !e.nichtStoeren.manuell } }))}
            >
              {tr('Nicht stören')}
            </button>
            <button type="button" class="os-verlauf-knopf" disabled={zustand().ungelesen === 0} onClick={() => dienst.alleGelesen()}>
              {tr('Alle gelesen')}
            </button>
          </div>
          <Show
            when={zustand().verlauf.length > 0}
            fallback={<p class="os-verlauf-leer" role="status">{tr('Keine Meldungen. Agent, Freigaben, Störungen, Termine und Mail erscheinen hier.')}</p>}
          >
            <ul class="os-verlauf-liste">
              <For each={zustand().verlauf}>
                {(m) => (
                  <li>
                    <button type="button" class="os-verlauf-eintrag" data-stufe={m.stufe} data-gelesen={m.gelesen ? 'ja' : 'nein'} onClick={() => eintrag(m)}>
                      <strong>{m.gelesen ? '' : '● '}{tr(m.titel)}</strong>
                      <Show when={m.text}>
                        <span data-privat={m.quelle === 'mail' || m.quelle === 'agent' ? 'privat' : undefined}>{m.text}</span>
                      </Show>
                      <span class="os-verlauf-meta">{QUELLEN_NAME[m.quelle]} · {zeitKurz(m.zeit, Date.now())}{m.stufe === 'kritisch' ? ' · kritisch' : m.stufe === 'hoch' ? ' · wichtig' : ''}</span>
                    </button>
                  </li>
                )}
              </For>
            </ul>
            <div class="os-verlauf-kopf">
              <button type="button" class="os-verlauf-knopf" onClick={() => dienst.verlaufLeeren()}>{tr('Leeren')}</button>
              <Show when={p.onEinstellungen}>
                <button type="button" class="os-verlauf-knopf" onClick={() => { zu(false); p.onEinstellungen?.(); }}>{tr('Einstellungen')}</button>
              </Show>
            </div>
          </Show>
        </section>
        </Portal>
      </Show>
    </span>
  );
}
