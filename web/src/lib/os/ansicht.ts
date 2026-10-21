/**
 * ansicht.ts — die OS-Ansicht gerade halten und gerade rücken.
 *
 * Beobachtung: „manchmal verschiebt sich die OS-Ansicht und verkeilt sich dann.“ Ursache: Die Bildschirme liegen als
 * Band (Shell.tsx `.os-band`, `translateX(-aktiv × 100 %)`) in einem Bereich mit `overflow: hidden`. Auch ein
 * Bereich ohne Scrollleiste lässt sich per Skript scrollen — und `scrollIntoView` (uebergang.ts `inDenBlick`,
 * `ausHerkunft`) tut genau das: Es rollt standardmäßig auch waagrecht („inline: nearest“) alle Vorfahren, bis
 * das Fenster im Blick ist. Springt ein Fenster auf einem anderen Bildschirm in den Blick, solange das Band noch
 * gleitet (480 ms), liegt es seitlich außerhalb: der Bereich rollt um bis zu eine Bildschirmbreite. Voraussetzung
 * ist, dass das Fenster senkrecht außerhalb liegt (`inDenBlick` holt nur dann) — also wenn auf einem langen
 * Bildschirm gescrollt wurde und dann per Dock, Fenstermenü oder Deeplink zu ihm gewechselt wird (`gehe(i)` + `setFokus`).
 * Das Mausrad selbst kann den Bereich nicht verschieben (hidden ist für Nutzer nicht scrollbar). Das Band
 * landet danach zwar richtig, der Bereich bleibt aber verrutscht — ohne Scrollleiste, ohne Wischen, das den
 * Versatz je wieder gerade zöge. Die Ansicht „verkeilt“ sich.
 *
 * Die Ansicht wird deshalb an drei Stellen gerade gehalten (Shell.tsx): `overflow: clip` (kein Scrollen mehr),
 * jedes Scroll-Ereignis des Bereichs rückt zurück, und beim Bildschirmwechsel, bei Größenänderung und auf Wunsch
 * (Doppelklick auf die Menüleiste, Menü Darstellung) wird alles auf null gesetzt. Dieses Modul ist ohne DOM
 * prüfbar; `osAnsichtRuecken` ist der einzige Teil mit Dokumentzugriff.
 */

/** Alles, was sich scrollen lässt (Element, `document.scrollingElement`). */
export interface Rollbar {
  scrollLeft: number;
  scrollTop: number;
}

/**
 * Setzt jede Rollposition auf null. Liefert, wie viele verrutscht waren (0 = alles gerade).
 * Nur Felder anfassen, die wirklich abweichen: ein Schreibzugriff löst sonst unnötig Layout und Scroll-Ereignisse aus.
 */
export function geradeRuecken(ziele: Iterable<Rollbar | null | undefined>): number {
  let n = 0;
  for (const z of ziele) {
    if (!z) continue;
    let weg = false;
    if (z.scrollLeft !== 0) {
      z.scrollLeft = 0;
      weg = true;
    }
    if (z.scrollTop !== 0) {
      z.scrollTop = 0;
      weg = true;
    }
    if (weg) n += 1;
  }
  return n;
}

/**
 * Hängt das Band noch am Finger, obwohl keiner mehr da ist? Dann ist der Versatz (`zug`) verwaist: ein
 * `pointerup` ging verloren (Element verschwand mitten im Wischen). Das Wischen selbst meldet sich alle paar
 * Millisekunden; ohne Finger ist es nach `frist` ms Stille vorbei. Ein Finger, der noch als aufliegend gilt, darf
 * länger ruhen (`fingerFrist`) — er kann wirklich noch halten, ein verlorenes `pointerup` lässt ihn aber ewig stehen.
 */
export function zugFestgefahren(zug: number, finger: number, stilleMs: number, frist = 700, fingerFrist = 5000): boolean {
  if (zug === 0) return false;
  return stilleMs > (finger === 0 ? frist : fingerFrist);
}

/**
 * Ist der Bereich der Bildschirme (`data-os-bereich`), die Shell (`data-shell`) oder die Seite selbst verrutscht,
 * wird er zurückgesetzt. Liefert die Zahl der korrigierten Ziele.
 */
export function osAnsichtRuecken(): number {
  if (typeof document === 'undefined') return 0;
  const ziele: Rollbar[] = [...document.querySelectorAll<HTMLElement>('[data-os-bereich], [data-shell]')];
  if (document.scrollingElement) ziele.push(document.scrollingElement);
  return geradeRuecken(ziele);
}
