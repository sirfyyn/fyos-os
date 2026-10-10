/**
 * Toast.tsx — Notification-Cards.
 *
 * Problem-Befund: Varianten waren halbtransparente *-soft-Tints → über Inhalt
 * unlesbar; actionable Toasts verschwanden nach 4s, bevor man entscheiden konnte.
 * LÖSUNG: IMMER solide Oberfläche (opak), Variante über
 * farbigen Akzent-Streifen + Icon (nie über Hintergrund-Tint). Actionable Toasts
 * (mit `action`) bleiben STEHEN bis Klick/Schließen — entscheidbar, nicht flüchtig.
 *
 * Usage:
 *   showToast({ title: 'Saved', description: '…', variant: 'success' });
 *   showToast({ title: 'Konflikt', variant: 'warn', action: { label: 'Lösen', onClick } });
 */
import { Show, createSignal, type Component } from 'solid-js';
import { Toast as KToast, toaster } from '@kobalte/core/toast';
import { Portal } from 'solid-js/web';
import { cn } from '~/lib/cn';

type ToastVariant = 'default' | 'success' | 'warn' | 'error' | 'info';

// ── Notification-Historie — nichts geht verloren ────────────────────
// Jeder Toast landet zusätzlich im persistenten Verlauf (localStorage, 100).
// Eine Glocke in der Oberfläche kann unreadCount + history lesen.
export interface ToastRecord {
  id: number;
  ts: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}
const HIST_KEY = 'fyos.notifications.v1';
const READ_KEY = 'fyos.notifications.lastRead.v1';
// Robust gegen Umgebungen wo `window` existiert aber localStorage fehlt/wirft
// (SSR, jsdom-Tests, Sandbox-iframes, Privacy-Mode) — sonst wirft der Modul-Import.
function safeLocalGet(key: string): string | null {
  try { return globalThis.localStorage?.getItem(key) ?? null; } catch { return null; }
}
function loadHist(): ToastRecord[] {
  try { return JSON.parse(safeLocalGet(HIST_KEY) || '[]'); } catch { return []; }
}
const [history, setHistory] = createSignal<ToastRecord[]>(loadHist());
const [lastRead, setLastRead] = createSignal<number>(Number(safeLocalGet(READ_KEY) || 0));
let _recId = Date.now();
function record(opts: { title: string; description?: string; variant?: ToastVariant }) {
  const rec: ToastRecord = {
    id: ++_recId, ts: Date.now(), title: opts.title,
    description: opts.description, variant: opts.variant ?? 'default',
  };
  const next = [rec, ...history()].slice(0, 100);
  setHistory(next);
  try { localStorage.setItem(HIST_KEY, JSON.stringify(next)); } catch { /* voll */ }
}
export const toastHistory = history;
export const unreadCount = () => history().filter((r) => r.ts > lastRead()).length;
export function markAllRead(): void {
  setLastRead(Date.now());
  try { localStorage.setItem(READ_KEY, String(Date.now())); } catch { /* egal */ }
}
export function clearToastHistory(): void {
  setHistory([]);
  try { localStorage.removeItem(HIST_KEY); } catch { /* egal */ }
}

export interface ShowToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** ms (0 = manuell schließen). Default: 5000 — MIT action: 0 (bleibt stehen). */
  duration?: number;
  action?: { label: string; onClick: () => void };
  /** Zweiter, leiser Knopf neben `action` (z. B. „Nicht mehr zeigen"). */
  secondaryAction?: { label: string; onClick: () => void };
}

// Variante NUR über Akzent-Streifen + Icon-Farbe — NIE über Hintergrund.
// Hintergrund ist immer solide/opak (--color-card), darum immer lesbar.
const ACCENT: Record<ToastVariant, string> = {
  default: 'var(--color-fg-subtle)',
  success: 'var(--color-success)',
  warn: 'var(--color-warn)',
  error: 'var(--color-error)',
  info: 'var(--color-info)',
};
const ICON: Record<ToastVariant, string> = {
  default: '•', success: '✓', warn: '⚠', error: '✕', info: 'ℹ',
};

export function showToast(opts: ShowToastOptions): number {
  const variant = opts.variant ?? 'default';
  record(opts); // in die Historie, bevor er wegtimen kann
  // Entscheidbarkeit: actionable Toasts dürfen NICHT wegtimen.
  const duration = opts.duration ?? (opts.action ? 0 : 5000);
  return toaster.show((props) => (
    <KToast toastId={props.toastId} duration={duration === 0 ? undefined : duration} persistent={duration === 0}>
      <div
        class="pointer-events-auto flex w-full max-w-sm items-start gap-3 overflow-hidden rounded-lg border border-(--color-border) shadow-xl ring-1 ring-black/10"
        style={{
          // SOLID, opak — explizit, damit nie durchscheinend
          'background-color': 'var(--color-card, var(--color-bg-elevated))',
          'border-left': `3px solid ${ACCENT[variant]}`,
        }}
      >
        <span class="select-none pl-3 pt-3 text-base leading-none" style={{ color: ACCENT[variant] }}>
          {ICON[variant]}
        </span>
        <div class="min-w-0 flex-1 py-3">
          <KToast.Title class="text-sm font-semibold text-(--color-fg)">{opts.title}</KToast.Title>
          <Show when={opts.description}>
            <KToast.Description class="mt-0.5 text-xs leading-snug text-(--color-fg)/80">
              {opts.description}
            </KToast.Description>
          </Show>
          <Show when={opts.action}>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => { opts.action!.onClick(); toaster.dismiss(props.toastId); }}
                class="inline-flex items-center gap-1 rounded-md bg-(--color-accent) px-3 py-1 text-xs font-semibold text-(--color-bg) shadow-sm hover:opacity-90 active:scale-95"
              >
                {opts.action!.label} →
              </button>
              <Show when={opts.secondaryAction}>
                <button
                  type="button"
                  onClick={() => { opts.secondaryAction!.onClick(); toaster.dismiss(props.toastId); }}
                  class="inline-flex items-center rounded-md px-2 py-1 text-xs text-(--color-fg-muted) underline-offset-2 hover:text-(--color-fg) hover:underline"
                >
                  {opts.secondaryAction!.label}
                </button>
              </Show>
            </div>
          </Show>
        </div>
        <KToast.CloseButton
          class="m-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-(--color-fg-muted) hover:bg-(--color-bg) hover:text-(--color-fg)"
          aria-label="Schließen"
        >
          ✕
        </KToast.CloseButton>
      </div>
    </KToast>
  ));
}

export function dismissToast(id: number): void {
  toaster.dismiss(id);
}

/** showUndoToast — Toast mit Rückgängig. Resolve true=Undo, false=Timeout. */
export function showUndoToast(opts: { title: string; description?: string; durationMs?: number }): Promise<boolean> {
  const duration = opts.durationMs ?? 8000;
  return new Promise<boolean>((resolve) => {
    let resolved = false;
    const timer = setTimeout(() => { if (!resolved) { resolved = true; resolve(false); } }, duration);
    toaster.show((props) => (
      <KToast toastId={props.toastId} duration={duration}>
        <div
          class="pointer-events-auto flex w-full max-w-sm items-start gap-3 overflow-hidden rounded-lg border border-(--color-border) shadow-xl ring-1 ring-black/10"
          style={{ 'background-color': 'var(--color-card, var(--color-bg-elevated))', 'border-left': `3px solid ${ACCENT.warn}` }}
        >
          <span class="select-none pl-3 pt-3 text-base leading-none" style={{ color: ACCENT.warn }}>↻</span>
          <div class="min-w-0 flex-1 py-3">
            <KToast.Title class="text-sm font-semibold text-(--color-fg)">{opts.title}</KToast.Title>
            <Show when={opts.description}>
              <KToast.Description class="mt-0.5 text-xs text-(--color-fg)/80">{opts.description}</KToast.Description>
            </Show>
          </div>
          <button
            onClick={() => { if (!resolved) { resolved = true; clearTimeout(timer); resolve(true); } toaster.dismiss(props.toastId); }}
            class="m-2 rounded-md bg-(--color-fg) px-3 py-1 text-xs font-semibold text-(--color-bg) hover:opacity-80"
          >
            Rückgängig
          </button>
        </div>
      </KToast>
    ));
  });
}

/** <ToastRegion/> — einmal nahe der App-Root mounten (Portal-Ziel). */
export const ToastRegion: Component = () => {
  return (
    <Portal>
      <KToast.Region pauseOnInteraction pauseOnPageIdle>
        {/* top-24: Toasts liegen unter Menüleiste und Fensterköpfen. */}
        <KToast.List class="pointer-events-none fixed top-24 right-4 z-[100] flex max-h-screen w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2 overflow-hidden" />
      </KToast.Region>
    </Portal>
  );
};
