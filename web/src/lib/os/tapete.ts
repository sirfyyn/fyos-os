/**
 * tapete.ts — eigener Hintergrund je Bildschirm.
 *
 * Jeder Bildschirm (auch der Start mit der Zentrale) trägt optional eine Tapete. Ohne Tapete zeigt er die Kulisse.
 * Arten:
 *  - `auswahl`: ein eingebauter Verlauf (reines CSS, kein Bild, kostet nichts);
 *  - `datei`: ein eigenes Bild aus der Dateiablage (Hub, `dateien.*`). Im Zustand steht nur der Pfad, nie die Bilddaten:
 *    der Zustand geht an den Hub und in den Browser-Speicher, ein Data-URL darin wäre Megabytes groß;
 *  - `url`: ein Bild von einer Adresse (https).
 * `dunkel` (0–80 %) legt Schwarz darüber, damit Fenster und Schrift lesbar bleiben; `weich` (0–24 px) zeichnet das Bild
 * unscharf. Das Bild steht still, die Unschärfe rechnet der Browser also nur einmal.
 *
 * Reine Funktionen; das Laden der Datei (Blob-URL) übernimmt `tapeteAdresse`.
 */

export type TapeteArt = 'auswahl' | 'datei' | 'url';

export interface Tapete {
  art: TapeteArt;
  /** auswahl: Kennung aus TAPETEN; datei: Pfad in der Ablage; url: https-Adresse */
  wert: string;
  /** 0–80, Abdunkeln in Prozent */
  dunkel: number;
  /** 0–24, Unschärfe in px */
  weich: number;
}

export interface TapeteVorlage {
  id: string;
  name: string;
  /** CSS-Hintergrund (nur Verläufe, keine Bilder) */
  hintergrund: string;
}

/** Eingebaute Auswahl: ruhige Verläufe, die zu Glas und Neon passen. */
export const TAPETEN: readonly TapeteVorlage[] = [
  { id: 'abend', name: 'Abend', hintergrund: 'radial-gradient(120% 90% at 20% 10%, #4c1d95 0%, transparent 60%), radial-gradient(100% 80% at 90% 100%, #be185d 0%, transparent 55%), #0f0a1e' },
  { id: 'tiefsee', name: 'Tiefsee', hintergrund: 'radial-gradient(110% 90% at 80% 0%, #0e7490 0%, transparent 58%), radial-gradient(120% 90% at 0% 100%, #1e3a8a 0%, transparent 60%), #05101c' },
  { id: 'polar', name: 'Polarlicht', hintergrund: 'radial-gradient(90% 60% at 30% 20%, #059669 0%, transparent 60%), radial-gradient(80% 70% at 75% 35%, #6366f1 0%, transparent 60%), #06121a' },
  { id: 'glut', name: 'Glut', hintergrund: 'radial-gradient(110% 80% at 50% 110%, #c2410c 0%, transparent 60%), radial-gradient(80% 60% at 85% 10%, #9f1239 0%, transparent 60%), #140806' },
  { id: 'morgen', name: 'Morgen', hintergrund: 'linear-gradient(160deg, #fde68a 0%, #fca5a5 45%, #a5b4fc 100%)' },
  { id: 'graphit', name: 'Graphit', hintergrund: 'radial-gradient(120% 100% at 50% 0%, #3f3f46 0%, transparent 65%), #111113' },
];

export const DUNKEL_STANDARD = 20;
export const WEICH_STANDARD = 0;
export const DUNKEL_MAX = 80;
export const WEICH_MAX = 24;
const WERT_MAX = 400;

const zahl = (w: unknown, max: number, std: number): number =>
  typeof w === 'number' && Number.isFinite(w) ? Math.round(Math.min(max, Math.max(0, w))) : std;

/** Nur Pfade innerhalb der Ablage: relativ, ohne `..`, ohne Steuerzeichen. */
export const pfadGueltig = (p: string): boolean =>
  !!p && p.length <= WERT_MAX && !p.startsWith('/') && !p.split('/').some((t) => t === '..' || t === '') && !/[\u0000-\u001f]/.test(p);

/** Nur https (oder eine Adresse derselben Herkunft, beginnend mit `/`), keine data:-, javascript:- oder http-Adressen. */
export function urlGueltig(u: string): boolean {
  if (!u || u.length > WERT_MAX) return false;
  if (u.startsWith('/') && !u.startsWith('//')) return true;
  try {
    return new URL(u).protocol === 'https:';
  } catch {
    return false;
  }
}

/** Aus Speicher oder Hub: eine gültige Tapete oder undefined (dann Kulisse). */
export function tapetePruefen(roh: unknown): Tapete | undefined {
  if (!roh || typeof roh !== 'object') return undefined;
  const r = roh as Partial<Tapete>;
  const wert = typeof r.wert === 'string' ? r.wert.trim() : '';
  const art = r.art;
  const ok =
    (art === 'auswahl' && TAPETEN.some((t) => t.id === wert)) ||
    (art === 'datei' && pfadGueltig(wert)) ||
    (art === 'url' && urlGueltig(wert));
  if (!ok) return undefined;
  return { art: art as TapeteArt, wert, dunkel: zahl(r.dunkel, DUNKEL_MAX, DUNKEL_STANDARD), weich: zahl(r.weich, WEICH_MAX, WEICH_STANDARD) };
}

export const vorlage = (id: string): TapeteVorlage | undefined => TAPETEN.find((t) => t.id === id);

/** CSS-Wert für `background` einer Tapete; `bildAdresse` ist die geladene Adresse (Blob-URL oder https). */
export function tapeteHintergrund(t: Tapete, bildAdresse?: string): string | undefined {
  if (t.art === 'auswahl') return vorlage(t.wert)?.hintergrund;
  if (!bildAdresse) return undefined;
  // CSS-String sicher: keine Anführungszeichen, Klammern oder Zeilenumbrüche aus der Adresse
  const sauber = bildAdresse.replace(/["'()\\\s]/g, (z) => encodeURIComponent(z));
  return `center / cover no-repeat url("${sauber}")`;
}

/** Größte Kante beim Hochladen eines eigenen Bildes (kleiner = schneller, die Ablage-Vorschau nimmt bis 6 MB). */
export const HOCHLADEN_KANTE = 2560;
/** Ordner in der Dateiablage für eigene Tapeten. */
export const TAPETEN_ORDNER = 'FYOS/Tapeten';

/** Dateiname in der Ablage: Bildschirm-Kennung und Zeit, damit nichts überschrieben wird. */
export const tapetenPfad = (bildschirm: string, jetzt = Date.now()): string =>
  `${TAPETEN_ORDNER}/${bildschirm.replace(/[^a-z0-9_-]/gi, '') || 'start'}-${jetzt.toString(36)}.jpg`;

/** Ereignis an die Shell: Tapeten-Dialog für den aktuellen Bildschirm öffnen (aus den Einstellungen). */
export const TAPETE_EREIGNIS = 'fyos:tapete-dialog';
