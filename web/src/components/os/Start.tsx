/**
 * Start — der Launcher des OS: ein gerahmtes Glas-Panel über dem Dock, etwa 2/5
 * der Breite, der Schreibtisch bleibt sichtbar. Oben die Suche, darunter
 * Bildschirme (wechseln, neu), Vorlagen (als eigenen Bildschirm öffnen, speichern) und alle Flächen
 * nach Gruppen. Flächen lassen sich auch direkt auf einen Bildschirm ziehen — auf den Schreibtisch, einen
 * Bildschirm-Punkt, „+" oder den Agent (lib/os/ziehen.ts).
 */
import { For, Show, createEffect, createSignal, on, onCleanup, onMount, type JSX } from 'solid-js';
import { systemName } from '~/lib/config';
import type { Griff } from '~/lib/griffe';
import { GriffFrage, GriffListe, griffTaste } from './Griffe';
import { pins as lesePins, pinsBeobachten } from '~/lib/mcp-apps/pins';
import type { Fenster } from '~/lib/os/anordnung';
import type { Flaeche } from '~/lib/os/flaechen';
import { gruppiert as trefferGruppen, sucheMoeglich, trefferWeg, type SucheZustand, type Treffer } from '~/lib/os/suche';
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
  /** Stand der Suche über alles (Vorgänge, Mail, Dateien, Notizen …); ohne Angabe sucht der Start nur Flächen */
  suchstand?: SucheZustand;
  /** Ein Treffer wurde angeklickt */
  onTreffer?: (t: Treffer) => void;
  /** Griffe zur Suche (lib/griffe.ts): schalten ohne Fenster */
  griffe?: readonly Griff[];
  onGriff?: (g: Griff) => void;
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
  const stand = (): SucheZustand => p.suchstand ?? { art: 'leer' };
  const sucht = () => sucheMoeglich(p.suche);
  const treffer = (): Treffer[] => {
    const s = stand();
    return s.art === 'fertig' ? s.treffer : [];
  };
  const griffe = () => p.griffe ?? [];
  const [griffWahl, setGriffWahl] = createSignal(-1);
  const [griffFrage, setGriffFrage] = createSignal<Griff | null>(null);
  createEffect(on(() => p.suche, () => { setGriffWahl(-1); setGriffFrage(null); }, { defer: true }));
  const griffWaehlen = (g: Griff) => (g.nachfragen ? setGriffFrage(g) : p.onGriff?.(g));
  /**
   * Enter: der mit ↑/↓ gewählte Griff; sonst die erste Fläche; gibt es keine, der erste Griff, dann der erste Treffer,
   * der sich öffnen lässt
   */
  const eingabeTaste = () => {
    const gewaehlt = griffe()[griffWahl()];
    if (gewaehlt) return griffWaehlen(gewaehlt);
    const erste = p.gruppen[0]?.flaechen[0];
    if (erste) return p.onOeffnen(erste.id);
    if (griffe()[0]) return griffWaehlen(griffe()[0]!);
    const t = treffer().find((x) => trefferWeg(x));
    if (t) p.onTreffer?.(t);
  };
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
        onKeyDown={(e) => {
          if (e.key === 'Enter') eingabeTaste();
          else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') griffTaste(e, griffe().length, griffWahl, setGriffWahl, () => setGriffWahl(-1));
        }}
        placeholder="Suchen: Flächen, Vorgänge, Mail, Dateien, Notizen"
        aria-label="Alles durchsuchen"
        class="os-start-suche"
      />
      <div class="os-start-inhalt">
        <Show when={p.suche && griffe().length}>
          <section aria-label="Schalten">
            <h3 class="os-titel mb-1.5">Schalten</h3>
            <Show when={griffFrage()} fallback={<GriffListe griffe={griffe()} aktiv={griffWahl()} onWahl={griffWaehlen} class="!p-0" />}>
              {(g) => <GriffFrage g={g()} onJa={() => p.onGriff?.(g())} onNein={() => setGriffFrage(null)} />}
            </Show>
          </section>
        </Show>
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
        <Show when={p.gruppen.length} fallback={<Show when={!sucht() || !p.suchstand}><p class="text-center text-sm text-(--color-fg-muted)">Nichts gefunden.</p></Show>}>
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
        {/* Suche über alles: Treffer aus Vorgängen, Mail, Dateien, Notizen … (Fremdinhalt, nur als Text gezeigt) */}
        <Show when={sucht() && p.suchstand}>
          <section aria-label="Treffer" aria-live="polite">
            <Show when={stand().art === 'laeuft'}><p class="text-center text-sm text-(--color-fg-muted)">Sucht …</p></Show>
            <Show when={stand().art === 'fehler'}>
              <p role="alert" class="text-center text-xs text-(--color-error)">
                Die Suche über alles ging nicht{(() => { const s = stand(); return s.art === 'fehler' ? `: ${s.text}` : ''; })()}
              </p>
            </Show>
            <Show when={stand().art === 'fertig'}>
              <For each={trefferGruppen(treffer())}>
                {(g) => (
                  <div class="mb-3">
                    <h3 class="os-titel mb-1.5">{g.titel}</h3>
                    <For each={g.treffer}>
                      {(t) => (
                        <button
                          type="button"
                          class="os-treffer"
                          disabled={!trefferWeg(t)}
                          draggable={trefferWeg(t) ? 'true' : undefined}
                          title={t.auszug || t.titel}
                          onClick={() => p.onTreffer?.(t)}
                          onDragStart={(e) => {
                            const w = trefferWeg(t);
                            if (!w) return;
                            gutSetzen(e.dataTransfer, { art: 'ding', typ: w.typ, id: w.id, label: w.label }, w.label);
                            zugBild(e.dataTransfer, w.label);
                            zugBeginnt({ art: w.typ });
                            p.onZiehStart?.();
                            setTimeout(() => p.onSchliessen(), 0);
                          }}
                          onDragEnd={() => p.onZiehEnde()}
                        >
                          <span class="os-treffer-titel">{t.titel}</span>
                          <Show when={t.auszug}><span class="os-treffer-auszug">{t.auszug}</span></Show>
                        </button>
                      )}
                    </For>
                  </div>
                )}
              </For>
              <Show when={!treffer().length && !p.gruppen.length}><p class="text-center text-sm text-(--color-fg-muted)">Nichts gefunden.</p></Show>
              <Show when={(() => { const s = stand(); return s.art === 'fertig' && s.fehlend.length > 0; })()}>
                <p class="text-xs text-(--color-fg-muted)">
                  Nicht durchsucht: {(() => { const s = stand(); return s.art === 'fertig' ? s.fehlend.join(', ') : ''; })()} (nicht eingerichtet oder nicht erreichbar).
                </p>
              </Show>
            </Show>
          </section>
        </Show>
      </div>
      </div>
    </div>
  );
}
