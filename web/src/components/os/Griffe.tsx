/**
 * Griffe.tsx — die Vorschlagsliste „Schalten“: Befehlszeile des Startbildschirms und Suche im Start zeigen beim Tippen
 * passende Griffe (lib/griffe.ts). Ein Klick oder Enter schaltet, es öffnet sich kein Fenster.
 */
import { For, createEffect, createMemo, createResource, createSignal, on, type JSX } from 'solid-js';
import '~/styles/os-griffe.css';
import { griffeFinden, griffeHolen, type Griff } from '~/lib/griffe';
import { Glyphe } from './Symbol';
import { tr } from '~/lib/i18n';

/**
 * Passende Griffe zur Eingabe. Geholt wird erst, wenn jemand mindestens zwei Zeichen tippt (danach 60 s aus dem
 * Vorrat); ohne Hub oder ohne eingerichtete Plugins bleibt die Liste leer.
 */
export function useGriffe(eingabe: () => string, max = 6): () => Griff[] {
  // Der Vorrat ist 60 s gültig: jedes neue Tippen nach einer Pause holt frisch (Zustand nach dem Schalten)
  const [runde, setRunde] = createSignal(0);
  // Quelle false bis zum ersten Tippen: Solid holt bei jeder anderen Quelle, auch bei 0
  const [alle] = createResource(() => runde() || false, () => griffeHolen().catch(() => [] as Griff[]));
  createEffect(on(eingabe, (q, vorher) => {
    if (q.trim().length >= 2 && (vorher ?? '').trim().length < 2) setRunde((n) => n + 1);
  }));
  const treffer = createMemo(() => {
    const g = alle();
    return g ? griffeFinden(g, eingabe(), max) : [];
  });
  return treffer;
}

export function GriffListe(p: {
  griffe: readonly Griff[];
  /** Hervorgehobener Eintrag (Pfeiltasten), -1 = keiner */
  aktiv: number;
  onWahl: (g: Griff) => void;
  class?: string;
}): JSX.Element {
  return (
    <ul role="listbox" aria-label={tr('Schalten')} class={`griff-liste ${p.class ?? ''}`}>
      <For each={p.griffe}>
        {(g, i) => (
          <li role="option" aria-selected={i() === p.aktiv}>
            <button
              type="button"
              class="griff"
              classList={{ 'griff-aktiv': i() === p.aktiv, 'griff-schon': !!g.istSchon }}
              // Fokus bleibt im Feld: sonst schlösse das Verlassen des Felds die Liste vor dem Klick
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => p.onWahl(g)}
            >
              <Glyphe name={g.symbol} class="griff-symbol" />
              <span class="griff-titel">{g.titel}</span>
              <span class="griff-art">{g.istSchon ? tr('steht schon so') : g.nachfragen ? tr('{0} · fragt nach', g.gruppe) : g.gruppe}</span>
            </button>
          </li>
        )}
      </For>
    </ul>
  );
}

/** Nachfrage vor einem Griff, der etwas für Minuten unterbricht. */
export function GriffFrage(p: { g: Griff; onJa: () => void; onNein: () => void; class?: string }): JSX.Element {
  return (
    <div role="group" aria-label={tr('Bestätigung')} class={`griff-frage ${p.class ?? ''}`}>
      <span class="min-w-0 flex-1">
        {p.g.titel}?
      </span>
      <button type="button" class="griff-ja" onClick={() => p.onJa()}>{tr('Ja')}</button>
      <button type="button" class="griff-nein" onClick={() => p.onNein()}>{tr('Abbrechen')}</button>
    </div>
  );
}

/**
 * Tasten im Feld: ↑/↓ wählen, Esc schließt die Liste. Liefert true, wenn die Taste verbraucht wurde.
 * Enter bleibt beim Formular bzw. Feld (es fragt `aktiv` ab).
 */
export function griffTaste(e: KeyboardEvent, anzahl: number, aktiv: () => number, setAktiv: (n: number) => void, zu: () => void): boolean {
  if (!anzahl) return false;
  if (e.key === 'ArrowDown') setAktiv((aktiv() + 1) % anzahl);
  else if (e.key === 'ArrowUp') setAktiv((aktiv() - 1 + anzahl) % anzahl);
  else if (e.key === 'Escape') zu();
  else return false;
  e.preventDefault();
  return true;
}
