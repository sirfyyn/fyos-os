/**
 * MeldungenHost — die Toasts des Meldungsdienstes (28.10.2026, lib/os/meldungen.ts) und die Verdrahtung der Quellen.
 *
 * Unten rechts im OS (am Handy oben), damit sie nicht auf „Agent zeigt dir …“ oben rechts (components/os/Mitteilungen.tsx) liegen und das
 * Dock (mittig) frei bleibt. Höchstens 3 gleichzeitig. Stufen: kritisch bleibt stehen bis „Verstanden“; hoch 30 s; normal 6 s; niedrig 3 s.
 * Darüberfahren oder Fokus hält offen; ein verborgener Tab zählt die Zeit nicht (die Meldung wartet, bis man zurück ist).
 * Klick (oder Enter) auf den Text öffnet das Ziel; Esc schließt die Meldung, in der der Fokus steht.
 * ARIA: kritisch und hoch `role="alert"`, sonst `role="status"`. Bewegung: nur Einblenden/Ausblenden, mit prefers-reduced-motion ohne Gleiten.
 * Die Glocke mit dem Verlauf steht in der Menüleiste (components/os/MeldungenGlocke.tsx).
 */
import { Portal } from 'solid-js/web';
import { For, Show, createEffect, createMemo, createSignal, on, onCleanup, onMount, type JSX } from 'solid-js';
import '~/styles/os-meldungen.css';
import { DAUER_MS, type Meldung, type MeldungAktion } from '~/lib/os/meldungen';
import { dienst, einstellungen, meldungOeffnen, meldungenStarten, system, zustand } from '~/lib/os/meldungen-produktiv';
import { QUELLEN_NAME } from '~/lib/os/meldungen-einstellungen';
import { Glyphe } from './Symbol';

/** So lange spielt die Ausblend-Bewegung, danach verlässt die Karte den Speicher. */
export const AUS_MS = 180;

const STUFE_NAME = { kritisch: 'Kritisch', hoch: 'Wichtig', normal: '', niedrig: '' } as const;

function Toast(p: { id: string; sichtbarSeite: () => boolean }): JSX.Element {
  const m = createMemo<Meldung | undefined>(() => zustand().sichtbar.find((x) => x.id === p.id));
  const [ueber, setUeber] = createSignal(false);
  const [weg, setWeg] = createSignal(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  let rest = 0;
  let seit = 0;
  let letzterStand = -1;

  const schliessen = (gelesen: boolean) => {
    if (weg()) return;
    clearTimeout(timer);
    timer = undefined;
    setWeg(true);
    setTimeout(() => dienst.schliesse(p.id, gelesen), AUS_MS);
  };
  const anhalten = () => {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    rest = Math.max(1000, rest - (Date.now() - seit));
  };
  // Eine Uhr je Toast: läuft nur, wenn nichts darüber fährt, nichts den Fokus hat und der Tab sichtbar ist. Eine Auffrischung
  // (Zusammenfassung) startet sie von vorn; kritische Toasts haben keine.
  createEffect(() => {
    const mm = m();
    if (!mm || weg()) return;
    const dauer = DAUER_MS[mm.stufe];
    const pausiert = ueber() || !p.sichtbarSeite();
    if (mm.stand !== letzterStand) {
      letzterStand = mm.stand;
      clearTimeout(timer);
      timer = undefined;
      rest = dauer ?? 0;
    }
    if (dauer === null) return;
    if (pausiert) anhalten();
    else if (timer === undefined) {
      if (rest <= 0) rest = dauer;
      seit = Date.now();
      timer = setTimeout(() => schliessen(false), rest);
    }
  });
  onCleanup(() => clearTimeout(timer));

  const aktion = (a: MeldungAktion) => {
    const mm = m();
    if (!mm) return;
    if (a.ziel) meldungOeffnen(mm, a);
    else dienst.lies(mm.id);
  };

  return (
    <Show when={m()}>
      {(mm) => (
        <article
          class="os-meldung"
          classList={{ 'os-meldung-weg': weg() }}
          data-stufe={mm().stufe}
          data-quelle={mm().quelle}
          data-meldung={mm().id}
          role={mm().stufe === 'kritisch' || mm().stufe === 'hoch' ? 'alert' : 'status'}
          aria-label={`${QUELLEN_NAME[mm().quelle]}: ${mm().titel}`}
          onPointerEnter={() => setUeber(true)}
          onPointerLeave={() => setUeber(false)}
          onFocusIn={() => setUeber(true)}
          onFocusOut={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setUeber(false);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              schliessen(false);
            }
          }}
        >
          <div class="os-meldung-kopf">
            <span class="os-meldung-quelle">
              {QUELLEN_NAME[mm().quelle]}
              <Show when={STUFE_NAME[mm().stufe]}>
                <span class="os-meldung-stufe"> · {STUFE_NAME[mm().stufe]}</span>
              </Show>
            </span>
            <button type="button" class="os-meldung-zu" aria-label="Meldung schließen" onClick={() => schliessen(true)}>
              <Glyphe name="x" />
            </button>
          </div>
          <button type="button" class="os-meldung-haupt" onClick={() => (mm().ziel ? meldungOeffnen(mm()) : schliessen(true))}>
            <strong class="os-meldung-titel">{mm().titel}</strong>
            <Show when={mm().text}>
              <span class="os-meldung-text" data-privat={mm().quelle === 'mail' || mm().quelle === 'agent' ? 'privat' : undefined}>{mm().text}</span>
            </Show>
          </button>
          <div class="os-meldung-aktionen">
            <For each={mm().aktionen}>
              {(a) => (
                <button type="button" class="os-meldung-knopf" onClick={() => aktion(a)}>
                  {a.text}
                </button>
              )}
            </For>
            <Show when={mm().stufe === 'kritisch'}>
              <button type="button" class="os-meldung-knopf os-meldung-leise" onClick={() => schliessen(true)}>
                Verstanden
              </button>
            </Show>
          </div>
        </article>
      )}
    </Show>
  );
}

export interface MeldungenHostProps {
  /** Ist des Agenten Fenster (Agent) gerade vorn? Dann kommen keine Agent-Meldungen. */
  agentVorn: () => boolean;
  /** Nur für Tests: statt der echten Quellen (Ströme, Abfragen) */
  starten?: (agentVorn: () => boolean) => () => void;
}

export default function MeldungenHost(p: MeldungenHostProps): JSX.Element {
  const [sichtbarSeite, setSichtbarSeite] = createSignal(true);
  const ids = createMemo(() => zustand().sichtbar.map((m) => m.id), [], { equals: (a, b) => a.length === b.length && a.every((x, i) => x === b[i]) });

  onMount(() => {
    const v = () => setSichtbarSeite(document.visibilityState === 'visible');
    v();
    // Rückkehr in den Vordergrund nach einer Systemmitteilung: deren Ziel öffnen (lib/os/meldungen-system.ts)
    const fokus = () => {
      v();
      if (document.visibilityState === 'visible') system.beiFokus();
    };
    document.addEventListener('visibilitychange', fokus);
    window.addEventListener('focus', fokus);
    // Quellen neu starten, wenn sich Quellen oder Mail-Ordner ändern
    const schluessel = createMemo(() => JSON.stringify([einstellungen().quellen, einstellungen().mailOrdner]));
    let stopp: (() => void) | undefined;
    createEffect(on(schluessel, () => {
      stopp?.();
      stopp = (p.starten ?? meldungenStarten)(p.agentVorn);
    }));
    onCleanup(() => {
      document.removeEventListener('visibilitychange', fokus);
      window.removeEventListener('focus', fokus);
      stopp?.();
    });
  });

  const inhalt = (
    <div class="os-meldungen" role="group" aria-label="Meldungen">
      <For each={ids()}>{(id) => <Toast id={id} sichtbarSeite={sichtbarSeite} />}</For>
      <Show when={zustand().wartend > 0}>
        <p class="os-meldungen-mehr" role="status">+{zustand().wartend} weitere in der Glocke</p>
      </Show>
    </div>
  );
  // Am Handy ein gemeinsamer Stapel mit „Agent zeigt dir …“: unsere Toasts stehen im selben Container, oben (CSS order). Ohne Container (Test) wie am Desktop.
  const [schmal, setSchmal] = createSignal(false);
  onMount(() => {
    const mq = window.matchMedia?.('(max-width: 767px)');
    if (!mq) return;
    const f = () => setSchmal(mq.matches);
    f();
    mq.addEventListener?.('change', f);
    onCleanup(() => mq.removeEventListener?.('change', f));
  });
  const stapel = () => (schmal() ? document.querySelector<HTMLElement>('.os-mitteilungen') : null);
  return (
    <Show when={stapel()} fallback={inhalt}>
      {(mount) => <Portal mount={mount()}>{inhalt}</Portal>}
    </Show>
  );
}
