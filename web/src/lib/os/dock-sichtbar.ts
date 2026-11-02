/**
 * Sichtbarkeit des Docks (28.10.2026, „wie das macOS-Dock ausblenden … drüberfahren oder ein Pfeilbutton nach oben
 * holen sie für 30 Sekunden hoch“).
 *
 * Reine Logik ohne Oberfläche: Die Zonen und Knöpfe melden nur, was sie erleben (Zeiger am unteren Rand, Zeiger auf dem
 * Dock, Fokus im Dock, Pfeil gedrückt), und bekommen zurück, ob das Dock gezeigt wird. Alle Zeiten laufen über
 * setTimeout, damit Tests mit falschen Uhren arbeiten können.
 *
 *   - Zeiger am unteren Rand (Zone, ~8 px): das Dock kommt erst nach `einblendenNach` (gegen Zufallsberührung).
 *   - Zeiger auf dem Dock oder Fokus darin: sofort sichtbar und bleibt es; Zeiger weg → nach `ausblendenNach` zu.
 *   - Pfeil: sichtbar für `pfeilDauer` (30 s). Der Zähler steht still, solange der Zeiger auf dem Dock ist oder der
 *     Fokus darin liegt, und läuft danach von vorn.
 *   - Ohne offene Anwendungen (`leer`) gibt es nichts zu zeigen: nie sichtbar.
 */

import { createSignal, type Accessor } from 'solid-js';

export interface DockSichtbarOptionen {
  /** Verzögerung, bis das Dock nach Berühren des unteren Rands erscheint (ms) */
  einblendenNach?: number;
  /** Verzögerung, bis es nach Verlassen des Docks verschwindet (ms) */
  ausblendenNach?: number;
  /** Wie lange der Pfeil das Dock hält (ms) */
  pfeilDauer?: number;
}

export const DOCK_EINBLENDEN_MS = 180;
export const DOCK_AUSBLENDEN_MS = 450;
export const DOCK_PFEIL_MS = 30_000;

export interface DockSichtbar {
  /** Wird das Dock gerade gezeigt? */
  sichtbar(): boolean;
  /** Zeiger am unteren Rand (Zone oder Pfeil-Knopf) */
  zone(an: boolean): void;
  /** Zeiger auf dem Dock */
  dock(an: boolean): void;
  /** Fokus liegt im Dock */
  fokus(an: boolean): void;
  /** Pfeil gedrückt (oder Kurzbefehl, Wischen von unten): Dock für `pfeilDauer` zeigen */
  pfeil(): void;
  /** Sofort zu (Esc) */
  verbergen(): void;
  /** Keine offene Anwendung: nichts zu zeigen (und alles Wartende vergessen) */
  leer(leer: boolean): void;
  /** Verbleibende Zeit des Pfeil-Zählers in ms (null = Pfeil nicht aktiv oder angehalten) */
  pfeilRest(): number | null;
  /** Timer aufräumen */
  aufraeumen(): void;
}

/** Die Steuerung mit einem Solid-Signal für `sichtbar` (Dock und Shell teilen sie). */
export type DockSicht = Omit<DockSichtbar, 'sichtbar'> & { sichtbar: Accessor<boolean> };

export function dockSicht(opt: DockSichtbarOptionen = {}): DockSicht {
  const [sichtbar, setSichtbar] = createSignal(false);
  const k = dockSichtbarkeit(setSichtbar, opt);
  return { ...k, sichtbar };
}

export function dockSichtbarkeit(onAendert: (sichtbar: boolean) => void, opt: DockSichtbarOptionen = {}): DockSichtbar {
  const einblenden = opt.einblendenNach ?? DOCK_EINBLENDEN_MS;
  const ausblenden = opt.ausblendenNach ?? DOCK_AUSBLENDEN_MS;
  const pfeilDauer = opt.pfeilDauer ?? DOCK_PFEIL_MS;

  let istLeer = false;
  let zeigerZone = false;
  let zeigerDock = false;
  let hatFokus = false;
  /** Zeiger ist lang genug am Rand gewesen (nach der Verzögerung) */
  let zoneWirkt = false;
  let pfeilAn = false;
  let pfeilBis: number | null = null;
  let zuletzt = false;

  let zeigTimer: ReturnType<typeof setTimeout> | undefined;
  let weichTimer: ReturnType<typeof setTimeout> | undefined;
  let pfeilTimer: ReturnType<typeof setTimeout> | undefined;

  const drin = () => zeigerDock || hatFokus;
  const berechne = () => !istLeer && (pfeilAn || zoneWirkt || drin());
  const melde = () => {
    const jetzt = berechne();
    if (jetzt === zuletzt) return;
    zuletzt = jetzt;
    onAendert(jetzt);
  };

  const pfeilStarten = () => {
    clearTimeout(pfeilTimer);
    pfeilTimer = undefined;
    pfeilBis = null;
    if (!pfeilAn || drin()) return; // angehalten, solange jemand am Dock ist
    pfeilBis = Date.now() + pfeilDauer;
    pfeilTimer = setTimeout(() => {
      pfeilAn = false;
      pfeilBis = null;
      pfeilTimer = undefined;
      melde();
    }, pfeilDauer);
  };
  const weichStarten = () => {
    clearTimeout(weichTimer);
    weichTimer = undefined;
    if (drin() || zeigerZone) return;
    if (!zoneWirkt) return;
    weichTimer = setTimeout(() => {
      weichTimer = undefined;
      if (drin() || zeigerZone) return;
      zoneWirkt = false;
      melde();
    }, ausblenden);
  };
  const innenGeaendert = () => {
    // Zeiger oder Fokus im Dock hält es offen und stoppt den Pfeil-Zähler; danach beginnt er neu.
    if (drin()) {
      clearTimeout(weichTimer);
      weichTimer = undefined;
      clearTimeout(zeigTimer);
      zeigTimer = undefined;
      if (!istLeer) zoneWirkt = true;
    } else weichStarten();
    pfeilStarten();
    melde();
  };

  return {
    sichtbar: () => zuletzt,
    zone(an) {
      zeigerZone = an;
      if (an) {
        clearTimeout(weichTimer);
        weichTimer = undefined;
        if (istLeer || zoneWirkt || zeigTimer) return;
        zeigTimer = setTimeout(() => {
          zeigTimer = undefined;
          if (!zeigerZone || istLeer) return;
          zoneWirkt = true;
          melde();
        }, einblenden);
      } else {
        clearTimeout(zeigTimer);
        zeigTimer = undefined;
        weichStarten();
      }
    },
    dock(an) {
      if (zeigerDock === an) return;
      zeigerDock = an;
      innenGeaendert();
    },
    fokus(an) {
      if (hatFokus === an) return;
      hatFokus = an;
      innenGeaendert();
    },
    pfeil() {
      if (istLeer) return;
      pfeilAn = true;
      pfeilStarten();
      melde();
    },
    verbergen() {
      pfeilAn = false;
      zoneWirkt = false;
      zeigerZone = false;
      clearTimeout(zeigTimer);
      clearTimeout(weichTimer);
      clearTimeout(pfeilTimer);
      zeigTimer = weichTimer = pfeilTimer = undefined;
      pfeilBis = null;
      // Zeiger und Fokus im Dock bleiben wahr, bis sie sich melden; sichtbar() bleibt dann wahr, solange sie da sind.
      melde();
    },
    leer(neu) {
      if (neu === istLeer) return;
      istLeer = neu;
      if (neu) {
        pfeilAn = false;
        zoneWirkt = false;
        clearTimeout(zeigTimer);
        clearTimeout(weichTimer);
        clearTimeout(pfeilTimer);
        zeigTimer = weichTimer = pfeilTimer = undefined;
        pfeilBis = null;
      }
      melde();
    },
    pfeilRest: () => (pfeilAn && pfeilBis != null ? Math.max(0, pfeilBis - Date.now()) : null),
    aufraeumen() {
      clearTimeout(zeigTimer);
      clearTimeout(weichTimer);
      clearTimeout(pfeilTimer);
    },
  };
}
