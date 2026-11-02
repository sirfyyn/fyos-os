/**
 * Hilfe — Tastenkürzel, Gesten und Ziehen und Ablegen des OS auf einen Blick (Menüleiste › Hilfe, ⌘/).
 */
import { For, onCleanup, onMount, type JSX } from 'solid-js';
import { IST_MAC, altUmschalt, mod, modAlt, modAltUmschalt } from '~/lib/os/menue';
import { tr } from '~/lib/i18n';

const KUERZEL: [string, string][] = [
  [mod('K'), 'Apps-Seite öffnen und suchen (Esc oder Zurück schließt sie)'],
  [mod('J'), 'Agent ein- und ausblenden'],
  [modAlt('D'), 'Dock holen (blendet sich sonst aus; Esc blendet aus)'],
  [modAlt('↑'), 'Übersicht aller Bildschirme'],
  [`${modAlt('←')}  ${modAlt('→')}`, 'Vorheriger / nächster Bildschirm, im Raum: Raum'],
  [mod('0'), 'Heim in die Zentrale (mit Räumen)'],
  [modAlt('1–9'), 'Zum Bildschirm springen'],
  [mod(','), 'Einstellungen'],
  [`${altUmschalt('←')}  ${altUmschalt('→')}`, 'Fenster im Kopf: nach links / rechts rücken'],
  [`${modAltUmschalt('←')}  ${modAltUmschalt('→')}  ${modAltUmschalt('↑')}`, 'Fenster im Fokus einrasten: linke / rechte Hälfte / ganz'],
  [modAltUmschalt('U I J K'), 'Fenster im Fokus als Viertel: oben links, oben rechts, unten links, unten rechts'],
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
  ['Zeiger an den unteren Rand / Pfeil unten / von unten wischen', 'Dock mit den offenen Anwendungen einblenden (Pfeil: 30 Sekunden)'],
];

/** Ziehen und Ablegen (lib/os/ziehen.ts): was sich ziehen lässt und was jedes Ziel daraus macht. */
const ZIEHEN: [string, string][] = [
  ['Fensterkopf oder Dock-Symbol', 'Ein Fenster. Auf ein anderes Fenster: davor einordnen'],
  ['Fensterkopf an den linken oder rechten Rand', 'Einrasten als Hälfte, in den Ecken als Viertel (die Vorschau zeigt es)'],
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
      <div ref={el} role="dialog" aria-modal="true" aria-label={tr('Tastenkürzel und Gesten')} class="os-glas os-glas-blur os-menue max-h-full w-[min(40rem,100%)] overflow-auto p-6">
        <div class="mb-4 flex items-center">
          <h2 class="m-0 flex-1 text-lg font-semibold">{tr('Tastenkürzel und Gesten')}</h2>
          <button type="button" class="os-knopf" aria-label={tr('Schließen')} onClick={() => p.onSchliessen()}>✕</button>
        </div>
        <For each={[['Tastatur', KUERZEL], ['Trackpad und Touch', GESTEN], ['Ziehen und Ablegen', ZIEHEN]] as const}>
          {([titel, liste]) => (
            <section class="mb-5 last:mb-0">
              <p class="os-kz-titel mb-2">{tr(titel)}</p>
              <dl class="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-2 text-sm">
                <For each={liste}>
                  {([k, t]) => (
                    <>
                      <dt class="font-medium whitespace-nowrap"><kbd class="os-taste">{tr(k)}</kbd></dt>
                      <dd class="m-0 text-(--color-fg-muted)">{tr(t)}</dd>
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
