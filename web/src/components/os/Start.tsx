/**
 * Start — der Launcher des OS: ein gerahmtes Glas-Panel über dem Dock, etwa 2/5
 * der Breite, der Schreibtisch bleibt sichtbar. Oben die Suche, darunter
 * Bildschirme (wechseln, neu), Vorlagen (als eigenen Bildschirm öffnen, speichern) und alle Flächen
 * nach Gruppen. Flächen lassen sich auch direkt auf einen Bildschirm ziehen — auf den Schreibtisch, einen
 * Bildschirm-Punkt, „+" oder den Agent (lib/os/ziehen.ts).
 */
import { For, Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { systemName } from '~/lib/config';
import { pins as lesePins, pinsBeobachten } from '~/lib/mcp-apps/pins';
import type { Fenster } from '~/lib/os/anordnung';
import type { Flaeche } from '~/lib/os/flaechen';
import { gutSetzen, zugBeginnt, zugBild } from '~/lib/os/ziehen';
import Symbol, { Glyphe } from './Symbol';

export interface Vorlage {
  name: string;
  fenster: Fenster[];
  eigene: boolean;
}

export interface StartProps {
  suche: string;
  setSuche: (s: string) => void;
  gruppen: { gruppe: string; flaechen: Flaeche[] }[];
  offen: (id: string) => boolean;
  onOeffnen: (id: string) => void;
  onZiehStart?: () => void;
  onZiehEnde: () => void;
  bildschirme: { index: number; name: string; anzahl: number }[];
  aktiv: number;
  onWechseln: (i: number) => void;
  onNeuerBildschirm: () => void;
  vorlagen: Vorlage[];
  onVorlage: (v: Vorlage) => void;
  vorlageName: string;
  setVorlageName: (s: string) => void;
  onVorlageSpeichern: () => void;
  onVorlageEntfernen: (name: string) => void;
  vorlageFehler: string;
  kannSpeichern: boolean;
  onSchliessen: () => void;
  feld: (el: HTMLInputElement) => void;
}

export default function Start(p: StartProps): JSX.Element {
  // Apps, die an den Startbildschirm geheftet sind, tragen ein kleines Zeichen am Symbol
  const [geheftet, setGeheftet] = createSignal<string[]>([]);
  onMount(() => {
    setGeheftet(lesePins());
    onCleanup(pinsBeobachten(setGeheftet));
  });
  return (
    <div
      class="os-start absolute inset-0 z-30"
      onClick={(e) => { if (e.target === e.currentTarget) p.onSchliessen(); }}
    >
      <div class="os-start-panel" role="dialog" aria-label={systemName()}>
      <input
        ref={p.feld}
        type="search"
        value={p.suche}
        onInput={(e) => p.setSuche(e.currentTarget.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') { const erste = p.gruppen[0]?.flaechen[0]; if (erste) p.onOeffnen(erste.id); } }}
        placeholder="Fläche suchen"
        aria-label="Fläche suchen"
        class="os-start-suche"
      />
      <div class="os-start-inhalt">
        <Show when={!p.suche}>
          <section aria-label="Bildschirme">
            <h3 class="os-titel mb-2.5">Bildschirme</h3>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="os-chip" classList={{ 'os-chip-fokus': p.aktiv === 0 }} onClick={() => p.onWechseln(0)}>Start</button>
              <For each={p.bildschirme}>
                {(b) => (
                  <button type="button" class="os-chip" classList={{ 'os-chip-fokus': p.aktiv === b.index }} onClick={() => p.onWechseln(b.index)}>
                    {b.name}
                    <span class="text-(--color-fg-muted) tabular-nums">{b.anzahl}</span>
                  </button>
                )}
              </For>
              <button type="button" class="os-chip" onClick={() => p.onNeuerBildschirm()}>+ Neuer Bildschirm</button>
            </div>
          </section>
          <Show when={true}>
            <section aria-label="Vorlagen">
              <h3 class="os-titel mb-2.5">Vorlagen</h3>
              <div class="flex flex-wrap items-center gap-2">
                <For each={p.vorlagen}>
                  {(v) => (
                    <span class="inline-flex overflow-hidden rounded-[0.8rem] border border-(--os-glas-rand)">
                      <button type="button" class="min-h-10 px-3.5 text-sm hover:bg-(--color-fg)/8" onClick={() => p.onVorlage(v)} title={`Als Bildschirm öffnen (${v.fenster.length} Flächen)`}>{v.name}</button>
                      <Show when={v.eigene}>
                        <button type="button" class="min-h-10 border-l border-(--os-glas-rand) px-2.5 text-(--color-fg-muted) hover:text-(--color-error)" aria-label={`Vorlage ${v.name} entfernen`} onClick={() => p.onVorlageEntfernen(v.name)}>✕</button>
                      </Show>
                    </span>
                  )}
                </For>
                <form class="flex w-full items-center gap-2" onSubmit={(e) => { e.preventDefault(); p.onVorlageSpeichern(); }}>
                  <input
                    value={p.vorlageName}
                    onInput={(e) => p.setVorlageName(e.currentTarget.value)}
                    placeholder="Diesen Bildschirm speichern als …"
                    aria-label="Name für die Vorlage"
                    maxLength={30}
                    class="min-h-10 w-44 min-w-0 flex-1 rounded-[0.8rem] border border-(--os-glas-rand) bg-transparent px-3 text-sm outline-none focus:border-(--os-neon-1)"
                  />
                  <button type="submit" disabled={p.vorlageName.trim().length < 2 || !p.kannSpeichern} class="os-chip disabled:opacity-40">Speichern</button>
                </form>
              </div>
              <Show when={p.vorlageFehler}><p role="alert" class="mt-2 text-xs text-(--color-error)">{p.vorlageFehler}</p></Show>
            </section>
          </Show>
        </Show>
        <Show when={p.gruppen.length} fallback={<p class="text-center text-sm text-(--color-fg-muted)">Nichts gefunden.</p>}>
          <For each={p.gruppen}>
            {(g) => (
              <section>
                <h3 class="os-titel mb-2.5">{g.gruppe}</h3>
                <div class="grid grid-cols-[repeat(auto-fill,minmax(5.75rem,1fr))] gap-x-1 gap-y-3">
                  <For each={g.flaechen}>
                    {(f) => (
                      <button
                        type="button"
                        draggable="true"
                        data-kontext={`flaeche:${f.id}`}
                        class="os-kachel"
                        title={f.untertitel || undefined}
                        onClick={() => p.onOeffnen(f.id)}
                        onDragStart={(e) => {
                          gutSetzen(e.dataTransfer, { art: 'flaeche', id: f.id }, f.titel);
                          zugBild(e.dataTransfer, f.titel);
                          zugBeginnt({ art: 'flaeche', id: f.id });
                          p.onZiehStart?.();
                          // Der Start geht aus dem Weg: Schreibtisch, Bildschirm-Punkte und Agent liegen darunter
                          setTimeout(() => p.onSchliessen(), 0);
                        }}
                        onDragEnd={() => p.onZiehEnde()}
                      >
                        <span class="os-kachel-bild">
                          <Symbol id={f.id} gruppe={f.gruppe} />
                          <Show when={f.appName && geheftet().includes(f.appName)}>
                            <span class="os-kachel-pin" aria-hidden="true"><Glyphe name="pin" gefuellt /></span>
                          </Show>
                        </span>
                        <span class="leading-tight">{f.titel}</span>
                        <Show when={p.offen(f.id)}><span class="text-[11px] text-(--color-fg-muted)">offen</span></Show>
                      </button>
                    )}
                  </For>
                </div>
              </section>
            )}
          </For>
        </Show>
      </div>
      </div>
    </div>
  );
}
