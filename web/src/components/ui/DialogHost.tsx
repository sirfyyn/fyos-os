/**
 * DialogHost.tsx — der eine Host für bestaetigen/meldung/eingabe (lib/ui/dialoge.ts).
 *
 * Sitzt in BaseLayout (jede Seite, jedes Fenster des OS, auch /os selbst). Zeigt die vorderste Anfrage der
 * Warteschlange. Tastatur: Esc = abbrechen, Enter = OK (nicht auf Knöpfen, nicht in gefährlichen Rückfragen),
 * Tab bleibt im Dialog. Beim Schließen geht der Fokus dorthin zurück, wo er vorher war.
 */
import { For, Show, createSignal, onCleanup, onMount, type Component } from 'solid-js';
import { Portal } from 'solid-js/web';
import { Button } from './Button';
import { aktiverDialog, type DialogAnfrage, type MeldungsArt } from '~/lib/ui/dialoge';
import { tr } from '~/lib/i18n';

const FOKUSBAR = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

let kartenZaehler = 0;

const ART_ZEICHEN: Record<MeldungsArt, string> = { info: 'ℹ', erfolg: '✓', warnung: '⚠', fehler: '⚠' };
const ART_FARBE: Record<MeldungsArt, string> = {
  info: 'text-(--color-info)',
  erfolg: 'text-(--color-success)',
  warnung: 'text-(--color-warn)',
  fehler: 'text-(--color-error)',
};

const DialogKarte: Component<{ a: DialogAnfrage }> = (props) => {
  const a = props.a;
  const nr = ++kartenZaehler;
  const titelId = `fyos-dialog-titel-${nr}`;
  const textId = `fyos-dialog-text-${nr}`;
  const opt = a.opt;
  const gefaehrlich = a.typ === 'bestaetigen' && !!a.opt.gefaehrlich;
  const art: MeldungsArt | undefined = a.typ === 'meldung' ? (a.opt.art ?? 'info') : undefined;
  const alarm = gefaehrlich || art === 'fehler' || art === 'warnung';
  const [wert, setWert] = createSignal(a.typ === 'eingabe' ? (a.opt.wert ?? '') : '');
  const [fehler, setFehler] = createSignal<string | null>(null);
  let karte: HTMLDivElement | undefined;
  let feld: HTMLInputElement | undefined;
  let abbrechenKnopf: HTMLButtonElement | undefined;
  let okKnopf: HTMLButtonElement | undefined;
  const davor = typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null;

  const abbrechen = () => {
    if (a.typ === 'bestaetigen') a.antwort(false);
    else if (a.typ === 'eingabe') a.antwort(null);
    else a.antwort();
  };
  const ok = () => {
    if (a.typ === 'bestaetigen') a.antwort(true);
    else if (a.typ === 'eingabe') {
      const f = a.opt.pruefen?.(wert());
      if (f) { setFehler(f); feld?.focus(); return; }
      a.antwort(wert());
    } else a.antwort();
  };

  const taste = (e: KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); abbrechen(); return; }
    if (e.key === 'Tab' && karte) {
      const liste = [...karte.querySelectorAll<HTMLElement>(FOKUSBAR)];
      if (!liste.length) { e.preventDefault(); return; }
      const erstes = liste[0]!;
      const letztes = liste[liste.length - 1]!;
      const innen = karte.contains(document.activeElement);
      if (!innen) { e.preventDefault(); (e.shiftKey ? letztes : erstes).focus(); }
      else if (e.shiftKey && document.activeElement === erstes) { e.preventDefault(); letztes.focus(); }
      else if (!e.shiftKey && document.activeElement === letztes) { e.preventDefault(); erstes.focus(); }
      e.stopPropagation();
      return;
    }
    if (e.key === 'Enter' && !e.isComposing) {
      const ziel = e.target as HTMLElement | null;
      // Auf einem Knopf löst Enter dessen eigene Aktion aus; in gefährlichen Rückfragen nie „blind“ bestätigen.
      if (ziel?.tagName === 'BUTTON' || ziel?.tagName === 'TEXTAREA' || ziel?.tagName === 'A') return;
      e.preventDefault(); e.stopPropagation();
      if (gefaehrlich) return;
      ok();
    }
  };

  onMount(() => {
    document.addEventListener('keydown', taste, true);
    if (a.typ === 'eingabe') { feld?.focus(); feld?.select(); }
    else if (gefaehrlich) abbrechenKnopf?.focus();
    else (okKnopf ?? karte)?.focus();
  });
  onCleanup(() => {
    document.removeEventListener('keydown', taste, true);
    if (davor && davor.isConnected && typeof davor.focus === 'function') davor.focus();
  });

  return (
    <Portal>
      <div
        data-fyos-dialog={a.typ}
        class="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 p-4"
        onMouseDown={(e) => { if (e.target === e.currentTarget) abbrechen(); }}
      >
        <div
          ref={karte}
          data-dialog-karte
          role={alarm ? 'alertdialog' : 'dialog'}
          aria-modal="true"
          aria-labelledby={titelId}
          aria-describedby={opt.text || opt.details?.length ? textId : undefined}
          tabindex="-1"
          class="flex max-h-[85vh] w-full max-w-md flex-col rounded-xl border border-(--color-border) bg-(--color-bg-elevated) p-5 shadow-2xl outline-none"
        >
          <h2 id={titelId} class={`mb-2 text-lg font-semibold ${gefaehrlich ? 'text-(--color-error)' : art ? ART_FARBE[art] : ''}`}>
            <Show when={gefaehrlich || art}><span aria-hidden="true">{gefaehrlich ? '⚠' : ART_ZEICHEN[art!]} </span></Show>
            {opt.titel}
          </h2>
          <div id={textId} class="min-h-0 flex-1 overflow-y-auto text-sm text-(--color-fg-muted)" data-dialog-inhalt>
            <Show when={opt.text}>
              <p class="mb-3 whitespace-pre-wrap break-words">{opt.text}</p>
            </Show>
            <Show when={opt.details?.length}>
              <Show when={opt.detailsTitel}><p class="mb-1 text-xs font-medium text-(--color-fg)">{opt.detailsTitel}</p></Show>
              <ul
                class="mb-3 max-h-56 overflow-y-auto rounded-md border border-(--color-border) p-2 font-mono text-xs"
                classList={{
                  'bg-(--color-warn-soft)': opt.detailsTon === 'warn',
                  'bg-(--color-error-soft)': opt.detailsTon === 'fehler',
                  'bg-(--color-card)': !opt.detailsTon,
                }}
                data-dialog-details
                tabindex="0"
              >
                <For each={opt.details}>{(z) => <li class="break-words py-0.5">{z}</li>}</For>
              </ul>
            </Show>
          </div>
          <Show when={a.typ === 'eingabe'}>
            <input
              ref={feld}
              type="text"
              value={wert()}
              placeholder={a.typ === 'eingabe' ? a.opt.platzhalter : undefined}
              aria-labelledby={titelId}
              aria-invalid={fehler() ? 'true' : undefined}
              aria-describedby={fehler() ? `${textId}-fehler` : undefined}
              onInput={(e) => { setWert(e.currentTarget.value); setFehler(null); }}
              class="mb-1 w-full rounded-md border border-(--color-border-strong) bg-(--color-bg) px-3 py-2 text-sm text-(--color-fg) outline-none focus:border-(--color-accent) focus:ring-2 focus:ring-(--color-accent)"
            />
            <Show when={fehler()}>
              <p id={`${textId}-fehler`} role="alert" class="mb-1 text-xs text-(--color-error)">{fehler()}</p>
            </Show>
          </Show>
          <div class="mt-3 flex justify-end gap-2">
            <Show when={a.typ !== 'meldung'}>
              <Button ref={abbrechenKnopf} variant="ghost" onClick={abbrechen}>
                {(a.typ === 'bestaetigen' || a.typ === 'eingabe') ? (a.opt.abbrechen ?? tr('Abbrechen')) : ''}
              </Button>
            </Show>
            <Button ref={okKnopf} variant={gefaehrlich ? 'destructive' : 'default'} onClick={ok}>
              {opt.ok ?? (gefaehrlich ? tr('Löschen') : a.typ === 'bestaetigen' ? tr('Bestätigen') : 'OK')}
            </Button>
          </div>
        </div>
      </div>
    </Portal>
  );
};

export const DialogHost: Component = () => (
  <Show when={aktiverDialog()} keyed>
    {(a) => <DialogKarte a={a} />}
  </Show>
);

export default DialogHost;
