/**
 * symbole.tsx — die wenigen Zeichen der Einstellungen als SVG (Text-Glyphen wie ☀ werden auf
 * manchen Geräten als bunte Emoji gezeichnet). Farbe kommt aus `currentColor`.
 */
import type { JSX } from 'solid-js';

const RAHMEN = {
  viewBox: '0 0 20 20',
  fill: 'none',
  stroke: 'currentColor',
  'stroke-width': 1.7,
  'stroke-linecap': 'round',
  'stroke-linejoin': 'round',
  'aria-hidden': true,
} as const;

export const Sonne = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.05em]">
    <circle cx="10" cy="10" r="3.4" />
    <path d="M10 2.2v1.6M10 16.2v1.6M2.2 10h1.6M16.2 10h1.6M4.5 4.5l1.1 1.1M14.4 14.4l1.1 1.1M4.5 15.5l1.1-1.1M14.4 5.6l1.1-1.1" />
  </svg>
);

export const Mond = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.05em]">
    <path d="M16.2 12.4A6.6 6.6 0 0 1 7.6 3.8a6.6 6.6 0 1 0 8.6 8.6Z" />
  </svg>
);

export const Halb = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.05em]">
    <circle cx="10" cy="10" r="7" />
    <path d="M10 3a7 7 0 0 1 0 14Z" fill="currentColor" stroke="none" />
  </svg>
);

export const Haken = (): JSX.Element => (
  <svg {...RAHMEN} class="size-4" stroke-width={2.2}>
    <path d="M4.5 10.5 8.2 14 15.5 6.5" />
  </svg>
);

export const Pfeil = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[0.95em]">
    <path d="M5 10h10M11 6l4 4-4 4" />
  </svg>
);

/** Auge: „alles sichtbar" (Modus Normal). */
export const Auge = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.15em]">
    <path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10Z" />
    <circle cx="10" cy="10" r="2.3" />
  </svg>
);

/** Aktentasche: Modus Arbeit. */
export const Tasche = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.15em]">
    <rect x="2.8" y="6.2" width="14.4" height="9.6" rx="2.2" />
    <path d="M7.4 6.2V5.1a1.2 1.2 0 0 1 1.2-1.2h2.8a1.2 1.2 0 0 1 1.2 1.2v1.1M2.8 10.8h14.4" />
  </svg>
);

/** Bildschirm mit Ständer: Modus Demo (zeigen, streamen, teilen). */
export const Bildschirm = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.15em]">
    <rect x="2.5" y="3.4" width="15" height="10.2" rx="2.2" />
    <path d="M7 16.6h6M10 13.6v3" />
  </svg>
);

/** Funke: Agent. */
export const Funke = (): JSX.Element => (
  <svg {...RAHMEN} class="size-[1.15em]">
    <path d="M10 2.8 11.7 8l5.3 1.7-5.3 1.7L10 16.6 8.3 11.4 3 9.7 8.3 8 10 2.8Z" />
  </svg>
);
