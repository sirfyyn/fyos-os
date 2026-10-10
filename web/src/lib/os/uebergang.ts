/**
 * uebergang.ts — Fenster gehen nicht einfach weg, sie gehen irgendwohin.
 *
 * Am Mac fliegt ein minimiertes Fenster in sein Symbol
 * im Dock und kommt beim Klick von dort zurück; ein geschlossenes klingt kurz aus. Bisher sprang das Fenster
 * im OS einfach weg — man sah nicht, wo es hin ist.
 *
 *   insDock(id)       Fenster schrumpft auf sein Dock-Symbol zu, danach erst ändert sich der Zustand
 *   herkunftMerken    vor dem Wiederherstellen: woher es kommt (Dock-Symbol); das Fenster holt es beim
 *                     Erscheinen ab (`ausHerkunft`) und wächst von dort auf
 *   ausklingen(id)    Schließen: kurz kleiner und durchsichtig
 *
 * Ohne Animation (prefers-reduced-motion, jsdom, kein Element) passiert die Änderung sofort.
 */

const DAUER_DOCK = 300;
const DAUER_AUS = 170;

const ruhig = (): boolean =>
  typeof window === 'undefined' ||
  (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

const fensterEl = (id: string): HTMLElement | null =>
  typeof document === 'undefined' ? null : document.querySelector<HTMLElement>(`.os-platz-an [data-fenster="${CSS.escape(id)}"]`);
const dockEl = (id: string): HTMLElement | null =>
  typeof document === 'undefined' ? null : document.querySelector<HTMLElement>(`[data-kontext="dock-fenster:${CSS.escape(id)}"]`);

const kannAnimieren = (el: HTMLElement | null): el is HTMLElement =>
  !!el && !ruhig() && typeof (el as HTMLElement & { animate?: unknown }).animate === 'function';

/** Verschiebung und Maßstab, die `von` auf `nach` legen (Mitte auf Mitte). */
function hin(von: DOMRect, nach: DOMRect): string {
  const s = Math.max(0.04, Math.min(nach.width / Math.max(1, von.width), nach.height / Math.max(1, von.height)));
  const dx = nach.left + nach.width / 2 - (von.left + von.width / 2);
  const dy = nach.top + nach.height / 2 - (von.top + von.height / 2);
  return `translate(${dx}px, ${dy}px) scale(${s})`;
}

/** Minimieren: das Fenster fliegt in sein Dock-Symbol, dann `danach()` (der eigentliche Zustand). */
export function insDock(id: string, danach: () => void): void {
  const el = fensterEl(id);
  const ziel = dockEl(id);
  if (!kannAnimieren(el) || !ziel) return danach();
  const a = el.animate(
    [
      { transform: 'none', opacity: 1, transformOrigin: 'center' },
      { transform: hin(el.getBoundingClientRect(), ziel.getBoundingClientRect()), opacity: 0.15, transformOrigin: 'center' },
    ],
    { duration: DAUER_DOCK, easing: 'cubic-bezier(0.5, 0, 0.75, 0.2)', fill: 'forwards' },
  );
  let fertig = false;
  const weiter = () => {
    if (fertig) return;
    fertig = true;
    danach();
  };
  a.onfinish = weiter;
  a.oncancel = weiter;
  // Falls der Browser die Animation verschluckt (Tab im Hintergrund): spätestens dann
  setTimeout(weiter, DAUER_DOCK + 150);
}

/** Schließen: kurz kleiner und durchsichtig, dann `danach()`. */
export function ausklingen(id: string, danach: () => void): void {
  const el = fensterEl(id);
  if (!kannAnimieren(el)) return danach();
  const a = el.animate([{ transform: 'none', opacity: 1 }, { transform: 'scale(0.94)', opacity: 0 }], {
    duration: DAUER_AUS,
    easing: 'cubic-bezier(0.4, 0, 1, 1)',
    fill: 'forwards',
  });
  let fertig = false;
  const weiter = () => {
    if (fertig) return;
    fertig = true;
    danach();
  };
  a.onfinish = weiter;
  a.oncancel = weiter;
  setTimeout(weiter, DAUER_AUS + 150);
}

// ── Wiederherstellen: Herkunft merken, beim Erscheinen von dort aufwachsen ──────────────────────

const herkunft = new Map<string, DOMRect>();

/** Vor dem Wiederherstellen aus dem Dock: das Symbol als Herkunft merken. */
export function herkunftMerken(id: string): void {
  const d = dockEl(id);
  if (d) herkunft.set(id, d.getBoundingClientRect());
}

/**
 * Ein Fenster, das ganz außerhalb des Sichtbaren liegt, in den Blick holen (lange Bildschirme scrollen).
 * Für jeden Fokuswechsel (Dock, Deeplink, Menü): live gesehen 04.10. — Verlauf bekam den Fokus, lag aber
 * 4200 px tiefer, sichtbar blieb die Liste. Teilweise sichtbare Fenster bleiben, wo sie sind.
 */
export function inDenBlick(id: string): void {
  const el = fensterEl(id);
  if (!el || typeof el.scrollIntoView !== 'function') return;
  const r = el.getBoundingClientRect();
  const draussen = r.height > 0 && (r.top > innerHeight - 80 || r.bottom < 80);
  // Weich nur kurze Wege im sichtbaren Tab: live 04.10. 22:55 bewegte `smooth` in einem Hintergrund-Tab gar nichts
  // (Chrome hält dort die Animationsbilder an), und 4000 px weich wären ohnehin zäh.
  const weit = Math.abs(r.top) > 2 * innerHeight;
  const weich = !ruhig() && !weit && document.visibilityState !== 'hidden';
  if (draussen) el.scrollIntoView({ block: 'nearest', behavior: weich ? 'smooth' : 'auto' });
}

/** Zeitpunkte (ms), zu denen `imBlickHalten` nachsieht: so lange laden die Apps darüber nach und wachsen. */
export const BLICK_NACH_MS = [0, 300, 900, 1800, 3000];

/**
 * `inDenBlick`, bis die Fläche steht: der Sprung läuft, danach laden Tabellen und
 * Listen darüber nach und schieben den Inhalt wieder weg. Sobald der Nutzer selbst scrollt, tippt oder
 * klickt, hört es auf. Gibt das Abbrechen zurück (neuer Fokus).
 */
export function imBlickHalten(id: string): () => void {
  const uhren: ReturnType<typeof setTimeout>[] = [];
  const ereignisse = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const;
  const aus = () => {
    uhren.forEach(clearTimeout);
    ereignisse.forEach((e) => removeEventListener(e, aus, true));
  };
  ereignisse.forEach((e) => addEventListener(e, aus, { capture: true, passive: true }));
  BLICK_NACH_MS.forEach((ms, i) => uhren.push(setTimeout(() => {
    inDenBlick(id);
    if (i === BLICK_NACH_MS.length - 1) aus();
  }, ms)));
  return aus;
}

/** Vom Fenster beim Erscheinen gerufen: wächst aus seiner Herkunft auf (falls es eine gibt). */
export function ausHerkunft(id: string, el: HTMLElement): void {
  const von = herkunft.get(id);
  herkunft.delete(id);
  if (!von) return;
  // Ein wiederhergestelltes Fenster unterhalb des Sichtbaren (lange Bildschirme scrollen) erst in den Blick holen —
  // sonst wächst es aus dem Dock ins Unsichtbare
  const vorher = el.getBoundingClientRect();
  const draussen = vorher.height > 0 && (vorher.top > innerHeight - 80 || vorher.bottom < 80);
  if (draussen && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
  if (!kannAnimieren(el)) return;
  // Gleich beim Einhängen messen, damit kein Bild am Zielort aufblitzt; ersetzt den normalen Auftritt (os.css)
  const r = el.getBoundingClientRect();
  if (r.width < 1) return;
  el.style.animation = 'none';
  el.animate(
    [
      { transform: hin(r, von), opacity: 0.15 },
      { transform: 'none', opacity: 1 },
    ],
    { duration: 340, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
  ).onfinish = () => el.style.removeProperty('animation');
}

/** Für Tests */
export const _herkunft = herkunft;
