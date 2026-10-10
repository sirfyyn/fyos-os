/**
 * gesten.ts — Trackpad- und Touch-Gesten des OS, ohne DOM.
 *
 * Was ein Browser vom Trackpad bekommt:
 *   - Zwei Finger waagrecht → `wheel` mit deltaX (auch der Nachlauf nach dem Loslassen).
 *   - Zwei Finger kneifen → `wheel` mit ctrlKey (Chrome, Firefox, Edge) bzw. `gesturechange`
 *     mit `scale` (Safari). Ohne preventDefault zoomt der Browser die Seite.
 *   - Zwei Finger tippen → `contextmenu` (Rechtsklick).
 * Drei und vier Finger behält macOS für sich.
 *
 * Bildschirme wechseln folgt dem Finger: das Band bewegt sich mit, am Rand mit Widerstand
 * (Gummiband), und rastet beim Loslassen auf den nächsten ein, wenn genug gezogen wurde.
 */

/** Am Rand gibt das Band nach, wird aber immer zäher (wie iOS). */
export function gummiband(versatz: number, breite: number, kannLinks: boolean, kannRechts: boolean): number {
  const zaeh = (d: number) => {
    const c = 0.55;
    const b = Math.max(1, breite);
    return (1 - 1 / ((Math.abs(d) * c) / b + 1)) * b * Math.sign(d);
  };
  // Positiver Versatz = Band nach rechts = zum linken Nachbarn.
  if (versatz > 0 && !kannLinks) return zaeh(versatz);
  if (versatz < 0 && !kannRechts) return zaeh(versatz);
  return Math.max(-breite, Math.min(breite, versatz));
}

/**
 * Wohin nach dem Loslassen? -1 = nach links (vorheriger), 1 = nach rechts (nächster), 0 = zurück.
 * Genug gezogen (Anteil der Breite) oder schnell genug geschnippt (px/ms).
 */
export function wischZiel(versatz: number, breite: number, tempo: number, kannLinks: boolean, kannRechts: boolean): -1 | 0 | 1 {
  const anteil = versatz / Math.max(1, breite);
  const weit = Math.abs(anteil) > 0.18;
  const schnell = Math.abs(tempo) > 0.45 && Math.abs(anteil) > 0.04;
  if (!(weit || schnell)) return 0;
  if (versatz > 0) return kannLinks ? -1 : 0;
  return kannRechts ? 1 : 0;
}

/**
 * Kneifen sammeln. `delta` > 0 heißt zusammenkneifen (herauszoomen). Liefert 'zu' (Übersicht
 * öffnen), 'auf' (Übersicht schließen) oder null, sobald genug zusammengekommen ist.
 */
export function kneifen(summe: number, schwelle = 70): 'zu' | 'auf' | null {
  if (summe > schwelle) return 'zu';
  if (summe < -schwelle) return 'auf';
  return null;
}

/** Abstand zweier Finger. */
export const abstand = (a: { x: number; y: number }, b: { x: number; y: number }): number => Math.hypot(a.x - b.x, a.y - b.y);
