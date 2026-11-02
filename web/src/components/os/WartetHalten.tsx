/**
 * WartetHalten — Knopf, der erst nach Halten auslöst (Nicht-Umkehrbares, OS-Neubau P2).
 *
 * Maus, Finger und Tastatur (Leertaste/Eingabe gedrückt halten) gleich: HALTE_MS lang halten, die Füllung zeigt den
 * Fortschritt; früher loslassen bricht ab. Ein einfacher Klick löst nie aus.
 */
import { createSignal, onCleanup, type JSX } from 'solid-js';
import { tr } from '~/lib/i18n';

export const HALTE_MS = 900;

export function WartetHalten(p: {
  onFertig: () => void;
  disabled?: boolean;
  class?: string;
  children: JSX.Element;
  'aria-label'?: string;
}): JSX.Element {
  const [anteil, setAnteil] = createSignal(0);
  let start = 0;
  let bild = 0;
  const halt = () => {
    cancelAnimationFrame(bild);
    bild = 0;
    start = 0;
    setAnteil(0);
  };
  const schritt = () => {
    const a = Math.min(1, (performance.now() - start) / HALTE_MS);
    setAnteil(a);
    if (a >= 1) {
      halt();
      p.onFertig();
      return;
    }
    bild = requestAnimationFrame(schritt);
  };
  const los = () => {
    if (p.disabled || start) return;
    start = performance.now();
    bild = requestAnimationFrame(schritt);
  };
  onCleanup(halt);
  return (
    <button
      type="button"
      class={`relative overflow-hidden select-none touch-none ${p.class ?? ''}`}
      disabled={p.disabled}
      aria-label={p['aria-label']}
      aria-description={tr('Gedrückt halten zum Bestätigen')}
      title={tr('Gedrückt halten')}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture?.(e.pointerId);
        los();
      }}
      onPointerUp={halt}
      onPointerCancel={halt}
      onPointerLeave={halt}
      onKeyDown={(e) => {
        if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) {
          e.preventDefault();
          los();
        }
      }}
      onKeyUp={(e) => {
        if (e.key === ' ' || e.key === 'Enter') halt();
      }}
      onClick={(e) => e.preventDefault()}
    >
      <span
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 left-0 bg-[color-mix(in_oklab,var(--color-error)_32%,transparent)]"
        style={{ width: `${anteil() * 100}%` }}
      />
      <span class="relative">{p.children}</span>
    </button>
  );
}
