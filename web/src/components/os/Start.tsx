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
import { hub } from '~/lib/hub';
import { wartetBeobachten } from '~/lib/os/wartet';
import {
  alphabetisch,
  standFuer,
  standTon,
  zuletztFlaechen,
  zuletztLesen,
  zuletztMerken,
  type DrawerAnsicht,
} from '~/lib/os/drawer';
import { ZUSTAND_ARGUMENTE, ZUSTAND_WERKZEUG, type ZentraleZustand } from '~/lib/zentrale';
import Symbol, { Glyphe } from './Symbol';
import './app-drawer.css';
import { tr } from '~/lib/i18n';

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
  /** Als eigene Seite (Apps-Seite, 28.10.2026) statt als Panel über dem Dock; Favoriten und ein Weg zurück kommen dazu */
  seite?: boolean;
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
    if (erste) return oeffnen(erste.id);
    if (griffe()[0]) return griffWaehlen(griffe()[0]!);
    const t = treffer().find((x) => trefferWeg(x));
    if (t) p.onTreffer?.(t);
  };
  /** Favoriten der Apps-Seite: die an die Zentrale angehefteten Apps (Pins), ohne Suche */
  const favoriten = (): Flaeche[] => {
    const ids = geheftet();
    if (!p.seite || p.suche || !ids.length) return [];
    return p.gruppen.flatMap((g) => g.flaechen).filter((f) => f.appName && ids.includes(f.appName));
  };
  // ── App-Drawer (OS-Neubau P7): Stand je App aus EINEM gebündelten Abruf, Ansichten Raum / A–Z / Zuletzt ──
  const [ansicht, setAnsicht] = createSignal<DrawerAnsicht>('raum');
  const [zustand, setZustand] = createSignal<ZentraleZustand | null>(null);
  const [zuletzt, setZuletzt] = createSignal<string[]>(zuletztLesen());
  const wartet = wartetBeobachten();
  onMount(() => {
    hub<ZentraleZustand>(ZUSTAND_WERKZEUG, ZUSTAND_ARGUMENTE)
      .then((z) => z && Array.isArray(z.kacheln) && setZustand(z))
      .catch(() => undefined);
  });
  const quellen = () => ({ zustand: zustand(), wartet: wartet() });
  const oeffnen = (id: string) => {
    setZuletzt(zuletztMerken(id));
    p.onOeffnen(id);
  };
  // Texte sind Schlüssel für tr(): beim Zeichnen übersetzt, damit ein Sprachwechsel sofort greift
  const ANSICHTEN: { id: DrawerAnsicht; text: string }[] = [
    { id: 'raum', text: 'Nach Raum' },
    { id: 'az', text: 'A–Z' },
    { id: 'zuletzt', text: 'Zuletzt' },
  ];

  const kachel = (f: Flaeche): JSX.Element => (
    <button
      type="button"
      draggable="true"
      data-privat={f.privat}
      data-kontext={`flaeche:${f.id}`}
      class="os-kachel ad-zeile"
      aria-label={f.titel}
      title={f.untertitel || undefined}
      onClick={() => oeffnen(f.id)}
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
      <span class="ad-text">
        <span class="ad-name">
          {f.titel}
          <Show when={p.offen(f.id)}><span class="ad-offen">{tr('offen')}</span></Show>
        </span>
        <span class="ad-stand" data-ton={standTon(f, quellen()) ?? undefined}>
          {standFuer(f, quellen()) ?? f.untertitel ?? ''}
        </span>
      </span>
    </button>
  );
  const raster = (liste: Flaeche[]) => <div class="ad-raster"><For each={liste}>{kachel}</For></div>;
  return (
    <div
      class={p.seite ? 'os-apps-seite' : 'os-start absolute inset-0 z-30'}
      data-apps-seite={p.seite ? '' : undefined}
      onClick={(e) => { if (!p.seite && e.target === e.currentTarget) p.onSchliessen(); }}
    >
      <div
        class={p.seite ? 'os-apps-panel' : 'os-start-panel'}
        role={p.seite ? 'region' : 'dialog'}
        aria-label={p.seite ? tr('Apps') : systemName()}
      >
      <Show when={p.seite}>
        <header class="os-apps-kopf">
          <button type="button" class="os-knopf" aria-label={tr('Zurück')} title={tr('Zurück (Esc)')} onClick={() => p.onSchliessen()}>‹ {tr('Zurück')}</button>
          <h1 class="os-titel m-0">{tr('Apps')}</h1>
        </header>
      </Show>
      <input
        ref={p.feld}
        type="search"
        value={p.suche}
        onInput={(e) => p.setSuche(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') eingabeTaste();
          else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') griffTaste(e, griffe().length, griffWahl, setGriffWahl, () => setGriffWahl(-1));
        }}
        placeholder={tr('Suchen: Flächen, Vorgänge, Mail, Dateien, Notizen')}
        aria-label={tr('Alles durchsuchen')}
        class="os-start-suche"
      />
      <div class="os-start-inhalt">
        <Show when={p.suche && griffe().length}>
          <section aria-label={tr('Schalten')}>
            <h3 class="os-titel mb-1.5">{tr('Schalten')}</h3>
            <Show when={griffFrage()} fallback={<GriffListe griffe={griffe()} aktiv={griffWahl()} onWahl={griffWaehlen} class="!p-0" />}>
              {(g) => <GriffFrage g={g()} onJa={() => p.onGriff?.(g())} onNein={() => setGriffFrage(null)} />}
            </Show>
          </section>
        </Show>
        <Show when={!p.suche}>
          <div class="ad-ansicht f2-seg" role="group" aria-label={tr('Ansicht')}
            data-modus="normal"
            style={{ '--f2-seg-i': String(ANSICHTEN.findIndex((a) => a.id === ansicht())), '--f2-seg-n': '3' }}>
            <span class="f2-seg-marke" aria-hidden="true" />
            <For each={ANSICHTEN}>
              {(a) => <button type="button" aria-pressed={ansicht() === a.id} onClick={() => setAnsicht(a.id)}>{tr(a.text)}</button>}
            </For>
          </div>
        </Show>
        <Show when={favoriten().length && ansicht() === 'raum'}>
          <section aria-label={tr('Favoriten')}>
            <h3 class="os-titel mb-2.5">{tr('Favoriten')}</h3>
            {raster(favoriten())}
          </section>
        </Show>
        <Show when={!p.suche && ansicht() === 'zuletzt'}>
          <section aria-label={tr('Zuletzt')}>
            <Show when={zuletztFlaechen(zuletzt(), p.gruppen).length} fallback={<p class="ad-leer">{tr('Noch nichts geöffnet. Was du öffnest, steht hier zuerst.')}</p>}>
              {raster(zuletztFlaechen(zuletzt(), p.gruppen))}
            </Show>
          </section>
        </Show>
        <Show when={!p.suche && ansicht() === 'az'}>
          <section aria-label={tr('A bis Z')}>{raster(alphabetisch(p.gruppen))}</section>
        </Show>
        <Show when={p.suche || ansicht() === 'raum'}>
          <Show when={p.gruppen.length} fallback={<Show when={!sucht() || !p.suchstand}><p class="text-center text-sm text-(--color-fg-muted)">{tr('Nichts gefunden.')}</p></Show>}>
            <For each={p.gruppen}>
              {(g) => (
                <section>
                  <h3 class="os-titel mb-2.5">{tr(g.gruppe)}</h3>
                  {raster(g.flaechen)}
                </section>
              )}
            </For>
          </Show>
        </Show>
        <Show when={!p.suche}>
          <section aria-label={tr('Bildschirme')}>
            <h3 class="os-titel mb-2.5">{tr('Bildschirme')}</h3>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="os-chip" classList={{ 'os-chip-fokus': p.aktiv === 0 }} onClick={() => p.onWechseln(0)}>{tr('Start')}</button>
              <For each={p.bildschirme}>
                {(b) => (
                  <button type="button" class="os-chip" classList={{ 'os-chip-fokus': p.aktiv === b.index }} onClick={() => p.onWechseln(b.index)}>
                    {b.name}
                    <span class="text-(--color-fg-muted) tabular-nums">{b.anzahl}</span>
                  </button>
                )}
              </For>
              <button type="button" class="os-chip" onClick={() => p.onNeuerBildschirm()}>{tr('+ Neuer Bildschirm')}</button>
            </div>
          </section>
          <Show when={true}>
            <section aria-label={tr('Vorlagen')}>
              <h3 class="os-titel mb-2.5">{tr('Vorlagen')}</h3>
              <div class="flex flex-wrap items-center gap-2">
                <For each={p.vorlagen}>
                  {(v) => (
                    <span class="inline-flex overflow-hidden rounded-[0.8rem] border border-(--os-glas-rand)">
                      <button type="button" class="min-h-10 px-3.5 text-sm hover:bg-(--color-fg)/8" onClick={() => p.onVorlage(v)} title={tr('Als Bildschirm öffnen ({0} Flächen)', v.fenster.length)}>{v.name}</button>
                      <Show when={v.eigene}>
                        <button type="button" class="min-h-10 border-l border-(--os-glas-rand) px-2.5 text-(--color-fg-muted) hover:text-(--color-error)" aria-label={tr('Vorlage {0} entfernen', v.name)} onClick={() => p.onVorlageEntfernen(v.name)}>✕</button>
                      </Show>
                    </span>
                  )}
                </For>
                <form class="flex w-full items-center gap-2" onSubmit={(e) => { e.preventDefault(); p.onVorlageSpeichern(); }}>
                  <input
                    value={p.vorlageName}
                    onInput={(e) => p.setVorlageName(e.currentTarget.value)}
                    placeholder={tr('Diesen Bildschirm speichern als …')}
                    aria-label={tr('Name für die Vorlage')}
                    maxLength={30}
                    class="min-h-10 w-44 min-w-0 flex-1 rounded-[0.8rem] border border-(--os-glas-rand) bg-transparent px-3 text-sm outline-none focus:border-(--os-neon-1)"
                  />
                  <button type="submit" disabled={p.vorlageName.trim().length < 2 || !p.kannSpeichern} class="os-chip disabled:opacity-40">{tr('Speichern')}</button>
                </form>
              </div>
              <Show when={p.vorlageFehler}><p role="alert" class="mt-2 text-xs text-(--color-error)">{p.vorlageFehler}</p></Show>
            </section>
          </Show>
        </Show>
        {/* Suche über alles: Treffer aus Vorgängen, Mail, Dateien, Notizen … (Fremdinhalt, nur als Text gezeigt) */}
        <Show when={sucht() && p.suchstand}>
          <section aria-label={tr('Treffer')} aria-live="polite">
            <Show when={stand().art === 'laeuft'}><p class="text-center text-sm text-(--color-fg-muted)">{tr('Sucht …')}</p></Show>
            <Show when={stand().art === 'fehler'}>
              <p role="alert" class="text-center text-xs text-(--color-error)">
                {tr('Die Suche über alles ging nicht')}{(() => { const s = stand(); return s.art === 'fehler' ? `: ${s.text}` : ''; })()}
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
              <Show when={!treffer().length && !p.gruppen.length}><p class="text-center text-sm text-(--color-fg-muted)">{tr('Nichts gefunden.')}</p></Show>
              <Show when={(() => { const s = stand(); return s.art === 'fertig' && s.fehlend.length > 0; })()}>
                <p class="text-xs text-(--color-fg-muted)">
                  {tr('Nicht durchsucht: {0} (nicht eingerichtet oder nicht erreichbar).', (() => { const s = stand(); return s.art === 'fertig' ? s.fehlend.join(', ') : ''; })())}
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
