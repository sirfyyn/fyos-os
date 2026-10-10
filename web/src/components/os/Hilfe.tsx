/**
 * Hilfe — Tastenkürzel, Gesten und Ziehen und Ablegen des OS auf einen Blick (Menüleiste › Hilfe, ⌘/).
 */
import { For, onCleanup, onMount, type JSX } from 'solid-js';
import { IST_MAC, altUmschalt, mod, modAlt } from '~/lib/os/menue';

const KUERZEL: [string, string][] = [
  [mod('K'), 'Alle Flächen (Start) öffnen und suchen'],
  [mod('J'), 'Agent ein- und ausblenden'],
  [modAlt('↑'), 'Übersicht aller Bildschirme'],
  [`${modAlt('←')}  ${modAlt('→')}`, 'Vorheriger / nächster Bildschirm'],
  [modAlt('1–9'), 'Zum Bildschirm springen'],
  [mod(','), 'Einstellungen'],
  [`${altUmschalt('←')}  ${altUmschalt('→')}`, 'Fenster im Kopf: nach links / rechts rücken'],
  [IST_MAC ? '⇧F10' : 'Umschalt+F10', 'Menü des Fensters (Kopf mit Fokus)'],
  [mod('/'), 'Diese Hilfe'],
  ['Esc', 'Menü, Start oder Übersicht schließen'],
];

const GESTEN: [string, string][] = [
  [IST_MAC ? 'Zwei Finger wischen' : 'Waagrecht scrollen', 'Bildschirm wechseln — folgt den Fingern'],
  ['Zwei Finger zusammenkneifen', 'Übersicht öffnen (auseinander: schließen)'],
  [IST_MAC ? 'Mit zwei Fingern tippen' : 'Rechtsklick', 'Menü an dieser Stelle'],
  ['Doppelklick auf den Fensterkopf', 'Volle ↔ halbe Breite'],
  ['Ecke unten rechts ziehen', 'Größe, rastet am Raster ein'],
  ['Touch: wischen / lange drücken', 'Bildschirm wechseln / Menü'],
];

/** Ziehen und Ablegen (lib/os/ziehen.ts): was sich ziehen lässt und was jedes Ziel daraus macht. */
const ZIEHEN: [string, string][] = [
  ['Fensterkopf oder Dock-Symbol', 'Ein Fenster. Auf ein anderes Fenster: davor einordnen'],
  ['Fläche im Startmenü', 'Öffnet sie dort, wo du sie loslässt'],
  ['Objekte aus Listen (Notiz, Termin …)', 'Öffnet das Objekt in seiner Fläche, gleich aufgeschlagen'],
  ['… auf einen Bildschirm-Punkt', 'Dorthin verschieben bzw. dort öffnen. Kurz verweilen wechselt den Bildschirm'],
  ['… auf „+“', 'Auf einem neuen Bildschirm'],
  ['… auf den Agent', 'Den Agenten dazu fragen'],
  ['Übersicht', 'Dock-Symbol auf eine Karte ziehen: Fenster dorthin'],
];

export default function Hilfe(p: { onSchliessen: () => void }): JSX.Element {
  let el: HTMLDivElement | undefined;
  onMount(() => {
    const zu = (e: KeyboardEvent) => {
      if (e.key === 'Escape') p.onSchliessen();
    };
    window.addEventListener('keydown', zu);
    // Fokus zurück, wo er vorher war (Tastatur-Nutzer landeten nach dem Schließen am Seitenanfang)
    const vorher = document.activeElement as HTMLElement | null;
    el?.querySelector<HTMLElement>('button')?.focus();
    onCleanup(() => {
      window.removeEventListener('keydown', zu);
      if (vorher?.isConnected) vorher.focus();
    });
  });
  return (
    <div class="os-start absolute inset-0 z-40 flex items-center justify-center bg-black/25 p-4" onClick={(e) => { if (e.target === e.currentTarget) p.onSchliessen(); }}>
      <div ref={el} role="dialog" aria-modal="true" aria-label="Tastenkürzel und Gesten" class="os-glas os-glas-blur os-menue max-h-full w-[min(40rem,100%)] overflow-auto p-6">
        <div class="mb-4 flex items-center">
          <h2 class="m-0 flex-1 text-lg font-semibold">Tastenkürzel und Gesten</h2>
          <button type="button" class="os-knopf" aria-label="Schließen" onClick={() => p.onSchliessen()}>✕</button>
        </div>
        <For each={[['Tastatur', KUERZEL], ['Trackpad und Touch', GESTEN], ['Ziehen und Ablegen', ZIEHEN]] as const}>
          {([titel, liste]) => (
            <section class="mb-5 last:mb-0">
              <p class="os-kz-titel mb-2">{titel}</p>
              <dl class="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
                <For each={liste}>
                  {([k, t]) => (
                    <>
                      <dt class="font-medium whitespace-nowrap"><kbd class="os-taste">{k}</kbd></dt>
                      <dd class="m-0 text-(--color-fg-muted)">{t}</dd>
                    </>
                  )}
                </For>
              </dl>
            </section>
          )}
        </For>
      </div>
    </div>
  );
}
