/**
 * Bild erzeugen im Raum Atelier: eine Beschreibung → `medien.bild`, das Ergebnis über `medien.datei`. Ein Medien-Plugin
 * im Hub liefert die drei Werkzeuge (`medien.status`, `medien.bild`, `medien.datei`).
 *
 * Die Werkzeuge brauchen im Hub den Tag `flaeche`, sonst weist /hub-api/app-call sie ab (403/404); fehlt das Plugin,
 * ist es dasselbe. Dann steht „Noch nicht eingerichtet.“ da, statt eines toten Knopfs.
 */
import { For, Show, createResource, createSignal, type JSX } from 'solid-js';
import { NichtEingerichtet } from '~/components/raeume/Huelle';
import { hub } from '~/lib/hub';
import { gesperrt } from './freigabe';

export { gesperrt };

interface Status {
  erreichbar?: boolean;
  satz?: string;
}
interface BildAntwort {
  ok?: boolean;
  nicht_jetzt?: boolean;
  satz?: string;
  id?: string;
  datei?: string;
  sekunden?: number;
}
interface Datei {
  base64?: string;
  mime?: string;
}
export interface Bild {
  id: string;
  prompt: string;
  src: string;
  satz: string;
}

/** Wählbare Modelle des Medien-Plugins; `standard` lässt es selbst wählen. Mit nur einer Wahl entfällt die Auswahl. */
export const MODELLE = [{ id: 'standard', titel: 'Standardmodell' }] as const;

export default function BildWerkstatt(): JSX.Element {
  const [status, { refetch }] = createResource(() => hub<Status>('medien.status'));
  const [prompt, setPrompt] = createSignal('');
  const [modell, setModell] = createSignal<string>(MODELLE[0].id);
  const [laeuft, setLaeuft] = createSignal(false);
  const [meldung, setMeldung] = createSignal('');
  const [bilder, setBilder] = createSignal<Bild[]>([]);
  const statusWert = () => (status.state === 'ready' || status.state === 'refreshing' ? status() : undefined);
  const zu = () => status.state === 'errored' && gesperrt(status.error);

  async function erzeugen(e: Event) {
    e.preventDefault();
    const text = prompt().trim();
    if (text.length < 3 || laeuft()) return;
    setLaeuft(true);
    setMeldung('Erzeuge … Der erste Auftrag kann etwas länger dauern.');
    try {
      const args: Record<string, unknown> = { prompt: text };
      if (modell() !== 'standard') args.modell = modell();
      const r = await hub<BildAntwort>('medien.bild', args, { zeitMs: 420_000, art: 'bewusst' });
      if (!r.ok || !r.datei) {
        setMeldung(r.satz ?? 'Gerade kein Bild.');
        return;
      }
      const d = await hub<Datei>('medien.datei', { datei: r.datei }, { zeitMs: 60_000, art: 'bewusst' });
      if (!d.base64) throw new Error('Bild nicht geholt');
      setBilder((b) => [{ id: r.id ?? r.datei!, prompt: text, src: `data:${d.mime ?? 'image/png'};base64,${d.base64}`, satz: r.satz ?? '' }, ...b].slice(0, 12));
      setMeldung(r.satz ?? '');
      void refetch();
    } catch (err) {
      setMeldung(gesperrt(err) ? 'Noch nicht eingerichtet: Bilder erzeugen.' : `Fehlgeschlagen: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-5" data-bild-werkstatt>
      <div class="flex items-baseline gap-3">
        <h1 class="m-0 flex-1 text-2xl font-bold text-(--color-fg)">Bild erzeugen</h1>
        <span class="text-xs text-(--color-fg-muted)" role="status" data-medien-status>
          <Show when={!zu()} fallback="noch nicht eingerichtet">
            {status.loading && !statusWert() ? 'frage den Medien-Dienst …' : (statusWert()?.satz ?? (status.error ? 'Medien-Dienst nicht erreichbar' : ''))}
          </Show>
        </span>
      </div>
      <Show
        when={!zu()}
        fallback={
          <NichtEingerichtet
            detail="Die Medien-Werkzeuge (medien.status, medien.bild, medien.datei) fehlen im Hub oder sind für den Browser nicht freigegeben (Tag „flaeche“). Sobald ein Plugin sie liefert, erzeugt dieser Bereich Bilder."
            data-medien-gesperrt
          />
        }
      >
        <form class="flex flex-col gap-2" onSubmit={erzeugen}>
          <textarea
            aria-label="Beschreibung des Bildes"
            placeholder="Was soll auf dem Bild sein?"
            rows={3}
            maxLength={2000}
            value={prompt()}
            onInput={(e) => setPrompt(e.currentTarget.value)}
            class="w-full resize-y rounded-[10px] border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_5%,transparent)] px-3 py-2 text-sm text-(--color-fg) placeholder:text-(--color-fg-muted) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
          />
          <div class="flex flex-wrap items-center gap-2">
            <Show when={MODELLE.length > 1}>
              <select
                aria-label="Modell"
                value={modell()}
                onChange={(e) => setModell(e.currentTarget.value)}
                class="h-9 rounded-[10px] border border-(--color-border) bg-(--color-card) px-2 text-sm text-(--color-fg)"
              >
                <For each={MODELLE}>{(m) => <option value={m.id}>{m.titel}</option>}</For>
              </select>
            </Show>
            <button type="submit" class="os-knopf h-9 px-4" disabled={laeuft() || prompt().trim().length < 3}>
              {laeuft() ? 'Erzeuge …' : 'Erzeugen'}
            </button>
            <span class="text-xs text-(--color-fg-muted)" aria-live="polite" data-bild-meldung>{meldung()}</span>
          </div>
        </form>
        <Show when={bilder().length} fallback={<p class="m-0 text-sm text-(--color-fg-muted)">Hier erscheinen die Bilder dieser Sitzung.</p>}>
          <ul class="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3 p-0">
            <For each={bilder()}>
              {(b) => (
                <li class="flex flex-col gap-1.5" data-bild={b.id}>
                  <img src={b.src} alt={b.prompt} class="aspect-square w-full rounded-xl border border-(--color-border) object-cover" />
                  <span class="line-clamp-2 text-xs text-(--color-fg-muted)">{b.prompt}</span>
                </li>
              )}
            </For>
          </ul>
        </Show>
      </Show>
    </div>
  );
}
