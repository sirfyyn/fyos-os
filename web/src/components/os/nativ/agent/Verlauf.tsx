/**
 * Verlauf — die Nachrichtenliste des offenen Gesprächs.
 *
 * du steht rechts, Agent links; was Agent zwischendurch tut, ist je Zug EINE Arbeitszeile (Zug.tsx), die Antwort die
 * Sprechblase darunter. die eigenständige Arbeit des Agenten (Eingang, Takt, Läufe) ist eine dezente Zeile und mit Live aus
 * verschwunden. Freigaben, auf die der Agent in diesem Gespräch wartet, stehen als Karte am Ende des Verlaufs.
 *
 * Lange Verläufe bleiben flüssig: gezeichnet werden nur die letzten Punkte (Seite für Seite „Ältere anzeigen“).
 * Die Daten baut lib/agent-runner/verlauf.ts, hier wird nur gezeichnet.
 */
import { Index, Match, Show, Switch, createEffect, createMemo, createSignal, on, onCleanup, untrack, type JSX } from 'solid-js';
import { baueAnzeige, stabilisiere, type Anzeige } from '~/lib/agent-runner/anzeige';
import { flauteText } from '~/lib/agent-runner/status';
import { uhrzeitKurz } from '~/lib/agent-runner/text';
import type { Freigabe, GespraechsZustand } from '~/lib/agent-runner/typen';
import { SEITE, baueVerlauf, begrenze, ohneAutonomes, type VerlaufsPunkt } from '~/lib/agent-runner/verlauf';
import { aufklappen } from './aufklappen';
import { FreigabeKarte } from './FreigabeKarte';
import { FOKUS, Fehler, KNOPF, Laedt, Leer, Punkt, Text } from './gemeinsam';
import { AutonomZeile, ZugBlock } from './Zug';

type Mensch = Extract<VerlaufsPunkt, { art: 'mensch' }>;

function MenschBlase(p: { m: Mensch }): JSX.Element {
  return (
    <div class="flex max-w-full flex-col items-end gap-0.5 self-end" data-art="mensch">
      <span class="px-1 text-[0.7rem] font-semibold text-(--color-fg-muted)">
        Du{p.m.steuern ? ' · Steuerung' : ''}
        <Show when={p.m.quelle}> · über {p.m.quelle}</Show>
        <Show when={p.m.zeit}> · {uhrzeitKurz(p.m.zeit)}</Show>
      </span>
      <div class="max-w-[min(36rem,92%)] rounded-[18px] rounded-br-md bg-(--color-accent) px-4 py-2.5 text-(--color-accent-text) select-text">
        <p class="m-0 text-[0.95rem] leading-[1.45] whitespace-pre-wrap break-words">{p.m.text}</p>
      </div>
    </div>
  );
}

/** Behält von der alten Liste jedes Objekt, das sich nicht geändert hat: unveränderte Zeilen werden nicht neu gezeichnet. */
function stabilPunkte(alt: VerlaufsPunkt[], neu: VerlaufsPunkt[]): VerlaufsPunkt[] {
  if (!alt.length) return neu;
  const nach = new Map(alt.map((a) => [a.schluessel, a]));
  return neu.map((n) => {
    const a = nach.get(n.schluessel);
    return a && JSON.stringify(a) === JSON.stringify(n) ? a : n;
  });
}

export function Verlauf(p: {
  z: GespraechsZustand;
  agentName: string;
  fehler: string | null;
  verbunden: boolean;
  /** Live an: die eigenständige Arbeit des Agenten steht als dezente Zeile im Verlauf; aus: sie fehlt. */
  live: boolean;
  fokus: number | null;
  /** Offene Freigaben dieses Gesprächs, die nicht zurückgestellt sind. */
  freigaben: Freigabe[];
  /** Wie viele weitere warten (andere Gespräche, zurückgestellte). */
  weitere: number;
  entscheide: (id: string, e: 'erteilt' | 'abgelehnt') => Promise<void>;
  spaeter: (id: string) => void;
  zurFreigabenListe: () => void;
  /** Zeitpunkt der letzten Meldung des Gesprächs und ob der Zug zu lange schweigt. */
  letzteRegung: number;
  flaute: boolean;
  nachfassen: () => Promise<void>;
  abbrechen: () => Promise<void>;
}): JSX.Element {
  let liste: HTMLDivElement | undefined;
  const offen = aufklappen();
  const [unten, setUnten] = createSignal(true);
  const [anzahl, setAnzahl] = createSignal(SEITE);
  const [jetzt, setJetzt] = createSignal(Date.now());
  const [aktion, setAktion] = createSignal<'nachfassen' | 'abbrechen' | null>(null);
  const [aktionFehler, setAktionFehler] = createSignal('');

  // Eine Uhr für Dauer und Zeiten, aber nur solange etwas läuft.
  createEffect(() => {
    if (!p.z.busy) return;
    setJetzt(Date.now());
    const t = setInterval(() => setJetzt(Date.now()), 1000);
    onCleanup(() => clearInterval(t));
  });

  // Anderes Gespräch: wieder bei der letzten Seite anfangen.
  createEffect(on(() => p.fokus, () => setAnzahl(SEITE), { defer: true }));

  let vorherAnzeige: Anzeige[] = [];
  const anzeige = createMemo(() => {
    const neu = stabilisiere(vorherAnzeige, baueAnzeige(p.z, { agentName: p.agentName }));
    vorherAnzeige = neu;
    return neu;
  });

  let vorherPunkte: VerlaufsPunkt[] = [];
  const alle = createMemo(() => {
    const neu = stabilPunkte(vorherPunkte, baueVerlauf(anzeige(), { agentName: p.agentName }));
    vorherPunkte = neu;
    return neu;
  });
  const gefiltert = createMemo(() => (p.live ? { punkte: alle(), ausgeblendet: 0 } : ohneAutonomes(alle())));
  const seite = createMemo(() => begrenze(gefiltert().punkte, anzahl()));

  const nachUnten = (weich = false) => liste?.scrollTo({ top: liste.scrollHeight, behavior: weich ? 'smooth' : 'auto' });
  // Bleibt der Nutzer unten, wandert der Verlauf mit; liest er weiter oben, wird nichts verschoben.
  createEffect(
    on(
      [seite, () => p.freigaben.length, () => p.flaute],
      () => {
        const folgen = untrack(unten);
        queueMicrotask(() => folgen && nachUnten());
      },
      { defer: true },
    ),
  );
  createEffect(on(() => p.z.geladen, () => queueMicrotask(() => nachUnten()), { defer: true }));

  const aelteres = () => {
    const h = liste?.scrollHeight ?? 0;
    const t = liste?.scrollTop ?? 0;
    setAnzahl((a) => a + SEITE);
    // Das Gelesene bleibt, wo es war: die Höhe, die oben dazukommt, wird abgezogen.
    queueMicrotask(() => {
      if (liste) liste.scrollTop = t + (liste.scrollHeight - h);
    });
  };

  const tue = async (was: 'nachfassen' | 'abbrechen') => {
    setAktion(was);
    setAktionFehler('');
    try {
      await (was === 'nachfassen' ? p.nachfassen() : p.abbrechen());
    } catch (f) {
      setAktionFehler(f instanceof Error ? f.message : String(f));
    } finally {
      setAktion(null);
    }
  };

  const hatInhalt = () => seite().sichtbar.length > 0 || p.freigaben.length > 0;

  return (
    <div class="relative flex min-h-0 flex-1 flex-col" data-verlauf>
      <Show when={p.fehler}>
        <div class="mb-2">
          <Fehler text={p.fehler!} />
        </div>
      </Show>
      <div
        ref={liste}
        role="log"
        aria-label="Verlauf"
        tabindex="0"
        class={`flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto overscroll-contain rounded-2xl px-1 py-1 ${FOKUS}`}
        onScroll={(e) => setUnten(e.currentTarget.scrollHeight - e.currentTarget.scrollTop - e.currentTarget.clientHeight < 120)}
      >
        <Show when={p.z.geladen || p.fehler} fallback={<Laedt text="Gespräch wird geladen" />}>
          <Show when={seite().rest > 0}>
            <button type="button" class={`${KNOPF} self-center`} onClick={aelteres} data-aelteres>
              Ältere anzeigen ({seite().rest})
            </button>
          </Show>
          <Show when={hatInhalt()} fallback={<Leer>Noch nichts gesagt. Schreib unten los.</Leer>}>
            <Index each={seite().sichtbar}>
              {(punkt) => (
                <Switch>
                  <Match when={punkt().art === 'tag' && (punkt() as Extract<VerlaufsPunkt, { art: 'tag' }>)}>
                    {(t) => (
                      <p class="m-0 self-center rounded-full bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] px-3 py-0.5 text-[0.7rem] font-semibold text-(--color-fg-muted)" data-art="tag">
                        {t().text}
                      </p>
                    )}
                  </Match>
                  <Match when={punkt().art === 'mensch' && (punkt() as Mensch)}>{(m) => <MenschBlase m={m()} />}</Match>
                  <Match when={punkt().art === 'zug' && (punkt() as Extract<VerlaufsPunkt, { art: 'zug' }>)}>
                    {(z) => <ZugBlock z={z()} jetzt={jetzt()} offen={offen} />}
                  </Match>
                  <Match when={punkt().art === 'autonom' && (punkt() as Extract<VerlaufsPunkt, { art: 'autonom' }>)}>
                    {(a) => <AutonomZeile a={a()} jetzt={jetzt()} offen={offen} />}
                  </Match>
                  <Match when={punkt().art === 'system' && (punkt() as Extract<VerlaufsPunkt, { art: 'system' }>)}>
                    {(s) => (
                      <div class="mx-auto w-full max-w-[40rem] rounded-xl border border-(--color-border) px-3 py-1.5 text-xs text-(--color-fg-muted)" data-art="system">
                        <span class="font-semibold">{s().titel}</span>
                        <Show when={s().zeit}> · {uhrzeitKurz(s().zeit)}</Show>
                        <Show when={s().text}>
                          <div class="mt-0.5 break-words">
                            <Text text={s().text.length > 600 ? `${s().text.slice(0, 599)}…` : s().text} />
                          </div>
                        </Show>
                      </div>
                    )}
                  </Match>
                </Switch>
              )}
            </Index>
          </Show>

          <Show when={gefiltert().ausgeblendet > 0}>
            <p class="m-0 self-center text-xs text-(--color-fg-subtle)" data-ausgeblendet>
              {gefiltert().ausgeblendet} eigenständige {gefiltert().ausgeblendet === 1 ? 'Arbeit' : 'Arbeiten'} ausgeblendet (Ruhe). /live blendet sie ein.
            </p>
          </Show>

          <Show when={p.freigaben.length > 0 || p.weitere > 0}>
            <section aria-label="Wartet auf dich" class="flex max-h-[min(22rem,60vh)] shrink-0 flex-col gap-2 overflow-y-auto overscroll-contain" data-freigaben-im-verlauf>
              <Index each={p.freigaben}>{(f) => <FreigabeKarte f={f()} entscheide={p.entscheide} spaeter={p.spaeter} kompakt />}</Index>
              <Show when={p.weitere > 0}>
                <button type="button" class={`${KNOPF} self-start`} onClick={() => p.zurFreigabenListe()} data-zur-liste>
                  {p.weitere === 1 ? '1 weitere Freigabe wartet' : `${p.weitere} weitere Freigaben warten`} · Liste öffnen
                </button>
              </Show>
            </section>
          </Show>

          <Show when={p.flaute}>
            <div
              role="status"
              class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-(--color-warn)/35 bg-(--color-warn-soft) px-3.5 py-2.5 text-sm"
              data-statuszeile="flaute"
            >
              <Punkt ton="warn" />
              <span class="min-w-0 flex-1">{flauteText({ letzteRegung: p.letzteRegung, jetzt: jetzt() })}</span>
              <button type="button" class={KNOPF} disabled={aktion() !== null} aria-busy={aktion() === 'nachfassen'} onClick={() => void tue('nachfassen')}>
                Nachfassen
              </button>
              <button type="button" class={KNOPF} disabled={aktion() !== null} aria-busy={aktion() === 'abbrechen'} onClick={() => void tue('abbrechen')}>
                Abbrechen
              </button>
              <Show when={aktionFehler()}>
                <span class="basis-full text-xs text-(--color-error)">{aktionFehler()}</span>
              </Show>
            </div>
          </Show>
        </Show>
      </div>
      <Show when={!unten()}>
        <button
          type="button"
          class={`${KNOPF} absolute right-3 bottom-2 min-h-9 shadow-[0_6px_20px_-8px_rgb(0_0_0/0.6)]`}
          onClick={() => {
            setUnten(true);
            nachUnten(true);
          }}
        >
          Nach unten
        </button>
      </Show>
      <Show when={!p.verbunden && p.z.geladen}>
        <p role="status" class="m-0 mt-1 flex items-center gap-2 text-xs text-(--color-warn)" data-statuszeile="verbindung">
          <Punkt ton="warn" />
          Verbindung verloren – versuche erneut …
        </p>
      </Show>
    </div>
  );
}
