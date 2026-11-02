/**
 * Dock — unten im OS, wie am Mac: ein schwebendes Glas-Dock in der Mitte.
 *
 * Darüber die Bildschirme als Punkte (wie die Seitenanzeige am iPhone; der aktive ist eine Pille,
 * „+“ legt einen neuen an). Im Dock: FYOS (Start), die Fenster des aktuellen Bildschirms als
 * Symbole mit Punkt darunter (offen) bzw. halb durchsichtig (minimiert), rechts der Agent.
 * Rechtsklick auf ein Symbol oder einen Punkt öffnet dessen Menü (die Shell baut es, über
 * `data-kontext`). Status, Kontrollzentrum und Uhr stehen in der Menüleiste oben.
 *
 * Ziehen (lib/os/ziehen.ts): Fenstersymbole lassen sich ziehen. Punkte, „+“ und der Agent sind
 * Ablageziele — beim Ziehen blühen die Punkte zu Schildern mit Namen auf, Verweilen auf einem Punkt wechselt
 * dorthin, auf dem Agent öffnet es das Gespräch.
 */
import { For, Index, Show, createEffect, createSignal, onCleanup, type JSX } from 'solid-js';
import { dockSicht, type DockSicht } from '~/lib/os/dock-sichtbar';
import { agentName, systemName } from '~/lib/config';
import { ablageZiel, gutSetzen, zugBeginnt, zugBild, zugEndet, type Gut } from '~/lib/os/ziehen';
import Symbol from './Symbol';
import { tr } from '~/lib/i18n';

export interface DockProps {
  bildschirme: { index: number; name: string }[];
  aktiv: number;
  onWechseln: (i: number) => void;
  onNeuerBildschirm: () => void;
  startOffen: boolean;
  onStart: () => void;
  fenster: { id: string; titel: string; gruppe?: string; min: boolean; privat?: string }[];
  fokus: string | null;
  onFenster: (id: string) => void;
  agent: boolean;
  onAgent: () => void;
  /** Ein Gut auf einen Bildschirm-Punkt gelegt */
  onAblegen?: (index: number, g: Gut) => void;
  /** … auf „+“ (neuer Bildschirm) */
  onAblegenNeu?: (g: Gut) => void;
  /** … auf den Agent */
  onAgentAblegen?: (g: Gut) => void;
  /** Punkt, der gerade bestätigt (kurzes Aufleuchten nach dem Ablegen) */
  puls?: number | null;
  /** Fenster, dessen Symbol gerade hüpft (eben geöffnet) */
  huepf?: string | null;
  /**
   * `klassisch`: Punkte, FYOS, Fenster, Agent, immer sichtbar (schmale Fenster, Räume aus).
   * `offene` (28.10.2026): nur die geöffneten Anwendungen, blendet sich aus wie das macOS-Dock; FYOS (Apps-Seite),
   * Bildschirm-Punkte und Agent leben dann in der Räume-Leiste links bzw. in Übersicht und Menüs.
   */
  modus?: 'klassisch' | 'offene';
  /** Sichtbarkeits-Steuerung (Zeiger, Fokus, Pfeil); ohne Angabe legt das Dock eine eigene an */
  sicht?: DockSicht;
}

export default function Dock(p: DockProps): JSX.Element {
  const sicht = p.sicht ?? dockSicht();
  onCleanup(() => { if (!p.sicht) sicht.aufraeumen(); });
  createEffect(() => sicht.leer(p.fenster.length === 0));
  return (
    <Show when={(p.modus ?? 'klassisch') === 'offene'} fallback={klassischeLeiste(p)}>
      {offeneLeiste(p, sicht)}
    </Show>
  );
}

/** Ein Symbol je offener Anwendung (gemeinsam für beide Modi). */
function fensterSymbole(p: DockProps): JSX.Element {
  return (
    <For each={p.fenster}>
      {(f) => (
        <button
          type="button"
          data-privat={f.privat}
          data-kontext={`dock-fenster:${f.id}`}
          aria-label={f.titel}
          title={f.min ? tr('{0} — minimiert', f.titel) : f.titel}
          class="os-dock-symbol"
          classList={{ 'os-dock-min': f.min, 'os-dock-fokus': !f.min && p.fokus === f.id, 'os-dock-huepf': p.huepf === f.id }}
          onClick={() => p.onFenster(f.id)}
          // Das Symbol ist das Fenster: auf einen Punkt ziehen verschiebt es, auf den Agent fragt der Agent
          draggable="true"
          onDragStart={(e) => {
            gutSetzen(e.dataTransfer, { art: 'fenster', id: f.id }, f.titel);
            zugBild(e.dataTransfer, f.titel);
            zugBeginnt({ art: 'fenster' });
          }}
          onDragEnd={() => zugEndet()}
        >
          <Symbol id={f.id} gruppe={f.gruppe} />
          <span class="os-dock-name" aria-hidden="true">{f.titel}</span>
          <span class="os-dock-licht" aria-hidden="true" />
        </button>
      )}
    </For>
  );
}

/** Fokus per Tastatur (nicht der Rest eines Mausklicks): nur dieser hält das Dock offen. */
function tastaturFokus(el: EventTarget | null): boolean {
  try {
    return !(el instanceof Element) || el.matches(':focus-visible');
  } catch {
    return true; // Umgebung ohne :focus-visible (jsdom): wie Tastatur
  }
}

/**
 * Das Dock nur mit geöffneten Anwendungen. Ohne offene Anwendung steht nichts da, auch kein Pfeil. Sonst: unsichtbar unter
 * dem unteren Rand, bis der Zeiger den Rand berührt (Zone, 8 px, mit kleiner Verzögerung), der Pfeil gedrückt wird (30 s)
 * oder der Fokus per Tastatur hineinkommt. Das Dock überlagert den Inhalt; nichts rückt.
 */
function offeneLeiste(p: DockProps, sicht: DockSicht): JSX.Element {
  let nav: HTMLElement | undefined;
  const schliesst = (e: KeyboardEvent) => {
    if (e.key !== 'Escape' || !sicht.sichtbar()) return;
    e.stopPropagation();
    (document.activeElement as HTMLElement | null)?.blur?.();
    sicht.fokus(false);
    sicht.verbergen();
  };
  return (
    <Show when={p.fenster.length > 0}>
      <div class="os-dock-huelle" data-dock="offene" data-sichtbar={sicht.sichtbar() ? 'ja' : 'nein'}>
        <div
          class="os-dock-zone"
          aria-hidden="true"
          data-dock-zone
          onPointerEnter={() => sicht.zone(true)}
          onPointerLeave={() => sicht.zone(false)}
        />
        <button
          type="button"
          class="os-dock-pfeil"
          classList={{ 'os-dock-pfeil-weg': sicht.sichtbar() }}
          tabIndex={sicht.sichtbar() ? -1 : 0}
          aria-label={tr('Dock einblenden')}
          aria-expanded={sicht.sichtbar()}
          title={tr('Offene Anwendungen zeigen (30 Sekunden)')}
          onPointerEnter={() => sicht.zone(true)}
          onPointerLeave={() => sicht.zone(false)}
          onClick={(e) => {
            sicht.pfeil();
            // Mit der Tastatur geklickt: der Fokus folgt ins Dock, sonst bliebe er auf dem verschwundenen Pfeil
            if (e.detail === 0) queueMicrotask(() => nav?.querySelector<HTMLButtonElement>('.os-dock-symbol')?.focus());
          }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 10.5 8 6l4.5 4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </button>
        <nav
          ref={nav}
          aria-label={tr('Bodenleiste')}
          class="os-dock-bereich os-dock-offene"
          data-kontext="dock"
          onKeyDown={schliesst}
          onFocusIn={(e) => { if (tastaturFokus(e.target)) sicht.fokus(true); }}
          onFocusOut={(e) => { if (!nav?.contains(e.relatedTarget as Node | null)) sicht.fokus(false); }}
        >
          <div
            class="os-glas os-dock"
            onPointerEnter={() => sicht.dock(true)}
            onPointerLeave={() => sicht.dock(false)}
          >
            <div class="os-dock-fenster" aria-label={tr('Offene Anwendungen')}>
              {fensterSymbole(p)}
            </div>
          </div>
        </nav>
      </div>
    </Show>
  );
}

function klassischeLeiste(p: DockProps): JSX.Element {
  const alle = () => [{ index: 0, name: 'Start' }, ...p.bildschirme];
  let punkte: HTMLDivElement | undefined;
  const [zielPunkt, setZielPunkt] = createSignal<number | null>(null);
  const [zielNeu, setZielNeu] = createSignal(false);
  const [zielAgent, setZielAgent] = createSignal(false);
  const agentZiel = ablageZiel({
    ziel: 'agent',
    ablegen: (g) => p.onAgentAblegen?.(g),
    an: setZielAgent,
    verweilen: () => { if (!p.agent) p.onAgent(); },
  });
  const neuZiel = ablageZiel({ ziel: 'neu', ablegen: (g) => p.onAblegenNeu?.(g), an: setZielNeu });

  /** Reiter-Muster: nur der aktive Punkt ist im Tab-Weg, Pfeiltasten/Pos1/Ende wechseln den Bildschirm (wie ⌃← / ⌃→ am Mac). */
  const taste = (e: KeyboardEvent) => {
    const liste = alle().map((b) => b.index);
    const i = liste.indexOf(p.aktiv);
    const ziel =
      e.key === 'ArrowRight' ? liste[Math.min(liste.length - 1, i + 1)]
      : e.key === 'ArrowLeft' ? liste[Math.max(0, i - 1)]
      : e.key === 'Home' ? liste[0]
      : e.key === 'End' ? liste[liste.length - 1]
      : undefined;
    if (ziel == null) return;
    e.preventDefault();
    if (ziel !== p.aktiv) p.onWechseln(ziel);
    queueMicrotask(() => punkte?.querySelector<HTMLButtonElement>(`[data-kontext="bildschirm:${ziel}"]`)?.focus());
  };

  return (
    <nav aria-label={tr('Bodenleiste')} class="os-dock-bereich" data-kontext="dock">
      {/* Bildschirme */}
      <div class="os-punkte" role="tablist" aria-label={tr('Bildschirme')} ref={punkte} onKeyDown={taste}>
        {/* Index statt For: die Namen folgen den Fenstern und ändern sich oft; die Knöpfe bleiben dabei dieselben (Fokus, Hover) */}
        <Index each={alle()}>
          {(b) => {
            // Ablageziel: Fenster dorthin, Fläche/Ding dort öffnen; Verweilen wechselt (auch zum Start)
            const ziel = ablageZiel({
              ziel: () => (b().index === 0 ? 'start' : 'bildschirm'),
              name: () => b().name,
              ablegen: (g) => p.onAblegen?.(b().index, g),
              an: (ja) => setZielPunkt((z) => (ja ? b().index : z === b().index ? null : z)),
              verweilen: () => { if (p.aktiv !== b().index) p.onWechseln(b().index); },
            });
            return (
              <button
                type="button"
                role="tab"
                aria-selected={p.aktiv === b().index}
                tabIndex={p.aktiv === b().index ? 0 : -1}
                aria-label={b().name}
                data-kontext={`bildschirm:${b().index}`}
                title={b().index === 0 ? tr('Startbildschirm') : b().name}
                class="os-punkt no-touch"
                classList={{
                  'os-punkt-an': p.aktiv === b().index,
                  'os-punkt-start': b().index === 0,
                  'os-ziel-an': zielPunkt() === b().index,
                  'os-puls': p.puls === b().index,
                }}
                onClick={() => p.onWechseln(b().index)}
                {...ziel}
              >
                {/* Start ist der Heimweg zum Startbildschirm: ein Knopf mit Haus statt eines Punkts, größer als die Punkte */}
                <Show when={b().index === 0}>
                  <svg class="os-punkt-haus" viewBox="0 0 20 20" aria-hidden="true">
                    <path d="M3.5 9.2 10 3.8l6.5 5.4V16a.8.8 0 0 1-.8.8h-3.4v-4.6H7.7v4.6H4.3a.8.8 0 0 1-.8-.8z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
                  </svg>
                </Show>
                {/* Sofort sichtbares Namensschild über dem Punkt (der title-Tooltip kommt erst nach einer Sekunde) */}
                <span class="os-punkt-name" aria-hidden="true">{b().name}</span>
              </button>
            );
          }}
        </Index>
        <Show when={p.bildschirme.length < 9}>
          <button
            type="button"
            class="os-punkt-neu no-touch"
            classList={{ 'os-ziel-an': zielNeu() }}
            aria-label={tr('Neuer Bildschirm')}
            title={tr('Neuer Bildschirm — oder etwas hierher ziehen')}
            onClick={() => p.onNeuerBildschirm()}
            {...neuZiel}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1.5v7M1.5 5h7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
          </button>
        </Show>
      </div>

      <div class="os-glas os-dock">
        <button type="button" aria-expanded={p.startOffen} aria-label={systemName()} title={tr('{0} — alle Flächen (⌘K)', systemName())} class="os-dock-symbol os-dock-fyos" onClick={() => p.onStart()}>
          <span class="os-logo os-logo-gross" aria-hidden="true" />
        </button>

        <Show when={p.fenster.length}>
          <span class="os-dock-trenner" aria-hidden="true" />
        </Show>
        <div class="os-dock-fenster" aria-label={tr('Offene Flächen')}>
          {fensterSymbole(p)}
        </div>

        <span class="os-dock-trenner" aria-hidden="true" />
        <button
          type="button"
          aria-pressed={p.agent}
          aria-label={agentName()}
          title={tr('{0} (⌘J) — Objekt, Fenster oder Fläche hierher ziehen, um dazu zu fragen', agentName())}
          class="os-dock-symbol"
          classList={{ 'os-dock-fokus': p.agent, 'os-ziel-an': zielAgent() }}
          onClick={() => p.onAgent()}
          {...agentZiel}
        >
          <Symbol id="agent" />
          <span class="os-dock-name" aria-hidden="true">{agentName()}</span>
          <Show when={p.agent}><span class="os-dock-licht" aria-hidden="true" /></Show>
        </button>
      </div>
    </nav>
  );
}
