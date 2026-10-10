/**
 * cn — Tailwind class-merge helper.
 *
 * Combines clsx (conditional class composition) with tailwind-merge
 * (resolves conflicting utility classes, e.g. `px-2 px-4` → `px-4`).
 *
 * Standard pattern in shadcn-style component-libraries.
 */
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
