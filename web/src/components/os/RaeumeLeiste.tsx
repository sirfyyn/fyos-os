/**
 * Räume-Leiste: links allein, Zentrale oben als Heimat (⌘0), die gebauten Räume darunter, unten Apps, der Agent (⌘J)
 * und die Einstellungen. Die Leiste des Raums selbst steht rechts (components/os/Raum.tsx).
 *   - Apps öffnet keinen Raum, sondern die Apps-Seite (lib/os/apps-seite.ts). Der Raum bleibt im Hintergrund erhalten;
 *     solange die Seite offen ist, trägt der Apps-Knopf die Markierung und kein Raum.
 *   - Der runde Agent-Knopf ist ein Ablageziel: ein Ticket, Fenster oder eine Fläche daraufziehen fragt den Agenten
 *     dazu; Verweilen öffnet ihn. Den Namen setzt agentName() (lib/config.ts).
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { agentName } from '~/lib/config';
import { leiste, type RaeumeZustand, type RaumId, type Verfuegbar } from '~/lib/os/raeume';
import { mod } from '~/lib/os/menue';
import { ablageZiel, type Gut } from '~/lib/os/ziehen';

const KNOPF =
  'flex size-11 items-center justify-center rounded-xl transition-colors duration-150 ease-out focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)';
const AN = 'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)';
const AUS = 'text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_8%,transparent)] hover:text-(--color-fg)';

export default function RaeumeLeiste(p: {
  zustand: RaeumeZustand;
  /** Was der Hub liefert (lib/os/raeume-inhalt.ts); ohne Angabe oder unbekannt zeigt die Leiste alle Räume */
  verfuegbar?: Verfuegbar;
  onRaum: (id: RaumId) => void;
  agentAn: boolean;
  onAgent: () => void;
  /** Ist die Apps-Seite offen? Dann trägt Apps die Markierung (der Raum darunter nicht). */
  appsOffen?: boolean;
  /** Apps-Knopf gedrückt: Seite öffnen oder, wenn sie offen ist, zurück */
  onApps?: () => void;
  /** Etwas auf den Agent-Knopf gelegt (Ticket, Fenster, Fläche): den Agenten dazu fragen */
  onAgentAblegen?: (g: Gut) => void;
}): JSX.Element {
  const eintraege = () => leiste(p.zustand, p.verfuegbar ?? null);
  const oben = () => eintraege().filter((r) => r.fest !== 'unten');
  const unten = () => eintraege().filter((r) => r.fest === 'unten');
  const anfangsbuchstabe = () => agentName().trim().charAt(0).toUpperCase() || 'A';
  const [agentZiel, setAgentZiel] = createSignal(false);
  const agentAblage = ablageZiel({
    ziel: 'agent',
    ablegen: (g) => p.onAgentAblegen?.(g),
    an: setAgentZiel,
    verweilen: () => { if (!p.agentAn) p.onAgent(); },
  });
  const knopf = (r: ReturnType<typeof eintraege>[number]) => {
    const an = () => p.zustand.aktiv === r.id && !p.appsOffen;
    const taste = r.id === 'zentrale' ? ` (${mod('0')})` : r.id === 'einstellungen' ? ` (${mod(',')})` : '';
    return (
      <button
        type="button"
        data-raum={r.id}
        aria-label={r.name}
        aria-current={an() ? 'page' : undefined}
        title={`${r.name}${taste}: ${r.zweck}`}
        class={KNOPF}
        classList={{ [AN]: an(), [AUS]: !an() }}
        onClick={() => p.onRaum(r.id)}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d={r.d} />
        </svg>
      </button>
    );
  };
  return (
    <nav
      aria-label="Räume"
      data-raeume-leiste
      class="os-glas os-glas-tief z-[7] my-3 ml-3 flex w-16 shrink-0 flex-col items-center gap-1.5 overflow-y-auto py-3"
    >
      <For each={oben()}>
        {(r, i) => (
          <>
            {knopf(r)}
            <Show when={i() === 0 && oben().length > 1}>
              <span aria-hidden="true" class="my-1 h-px w-7 bg-(--color-border)" />
            </Show>
          </>
        )}
      </For>
      <span aria-hidden="true" class="flex-1" />
      {/* Apps: kein Raum, sondern die Apps-Seite (Launcher mit Suche, Favoriten, Bildschirmen, Vorlagen, allen Flächen) */}
      <button
        type="button"
        data-raum-apps
        aria-label="Apps"
        aria-pressed={!!p.appsOffen}
        title={`Apps (${mod('K')}): alle Flächen suchen und öffnen — auf eigener Seite`}
        class={KNOPF}
        classList={{ [AN]: !!p.appsOffen, [AUS]: !p.appsOffen }}
        onClick={() => p.onApps?.()}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <For each={[5, 12, 19]}>{(y) => <For each={[5, 12, 19]}>{(x) => <circle cx={x} cy={y} r="1.9" />}</For>}</For>
        </svg>
      </button>
      <button
        type="button"
        data-raum-agent
        aria-label={`${agentName()} fragen (${mod('J')})`}
        aria-pressed={p.agentAn}
        title={`${agentName()} (${mod('J')}): sieht Raum, Auswahl und offene Fenster — Ticket, Fenster oder Fläche hierher ziehen, um dazu zu fragen`}
        class="flex size-10 items-center justify-center rounded-full bg-(--color-accent) text-[15px] font-bold text-(--color-bg) shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-accent)_25%,transparent)] transition-shadow duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)"
        classList={{ 'shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-accent)_60%,transparent)]': p.agentAn, 'os-ziel-an': agentZiel() }}
        onClick={() => p.onAgent()}
        {...agentAblage}
      >
        {anfangsbuchstabe()}
      </button>
      <span aria-hidden="true" class="my-1 h-px w-7 bg-(--color-border)" />
      <For each={unten()}>{(r) => knopf(r)}</For>
    </nav>
  );
}
