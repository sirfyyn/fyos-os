/**
 * Erscheinungsbild — Farbschema (Hell, Dunkel, System) und die Kulisse mit Live-Vorschau.
 *
 * Beides liegt in diesem Browser (lib/einstellungen/farbschema.ts, lib/os/kulisse.ts) und wirkt
 * sofort: das Farbschema auf alle Fenster (auch eingebettete Seiten), die Kulisse auf den
 * Hintergrund und die Vorschau.
 */
import { For, Show, createMemo, createSignal, createUniqueId, onCleanup, onMount, type JSX } from 'solid-js';
import {
  KULISSE_EREIGNIS,
  kulisseVon,
  KULISSE_STANDARD,
  kulisseLaden,
  kulissePruefen,
  kulisseSpeichern,
  type KulisseEinstellung,
  type KulisseFarben,
  type KulisseStil,
} from '~/lib/os/kulisse';
import { aufloesen, farbschemaLaden, farbschemaSetzen, hoereFarbschema, type Aufgeloest, type Farbschema } from '~/lib/einstellungen/farbschema';
import { FOKUS, KNOPF_LEISE, Regler, SchalterZeile, Wahl, Zeile, radioTaste } from './bausteine';
import KulisseVorschau from './KulisseVorschau';

// ── Farbschema ──────────────────────────────────────────────────────────────

/** Kleines Bild eines Bildschirms im jeweiligen Schema (feste Farben: es zeigt ja das Schema). */
function SchemaBild(p: { art: 'hell' | 'dunkel' }): JSX.Element {
  const hell = p.art === 'hell';
  return (
    <span
      class="absolute inset-0"
      style={{
        background: hell
          ? 'radial-gradient(70% 90% at 12% 0%, #f5d0fe 0%, transparent 60%), radial-gradient(60% 80% at 100% 30%, #a5f3fc 0%, transparent 60%), #eef2f7'
          : 'radial-gradient(70% 90% at 12% 0%, #6b21a8 0%, transparent 62%), radial-gradient(60% 80% at 100% 30%, #0e7490 0%, transparent 60%), #0d1320',
      }}
    >
      <span
        class="absolute top-[16%] left-[10%] h-[56%] w-[58%] rounded-[5px] border"
        style={{
          background: hell ? 'rgb(255 255 255 / 0.78)' : 'rgb(30 39 52 / 0.78)',
          'border-color': hell ? 'rgb(15 23 42 / 0.08)' : 'rgb(255 255 255 / 0.09)',
        }}
      >
        <span class="absolute top-[18%] left-[12%] h-[9%] w-[46%] rounded-full" style={{ background: hell ? '#1e293b' : '#e2e8f0', opacity: 0.55 }} />
        <span class="absolute top-[38%] left-[12%] h-[7%] w-[70%] rounded-full" style={{ background: hell ? '#1e293b' : '#e2e8f0', opacity: 0.22 }} />
        <span class="absolute top-[54%] left-[12%] h-[7%] w-[56%] rounded-full" style={{ background: hell ? '#1e293b' : '#e2e8f0', opacity: 0.22 }} />
      </span>
      <span
        class="absolute top-[28%] right-[8%] h-[44%] w-[22%] rounded-[5px] border"
        style={{
          background: hell ? 'rgb(255 255 255 / 0.62)' : 'rgb(30 39 52 / 0.62)',
          'border-color': hell ? 'rgb(15 23 42 / 0.08)' : 'rgb(255 255 255 / 0.09)',
        }}
      />
      <span
        class="absolute right-[6%] bottom-[7%] left-[6%] h-[11%] rounded-[4px]"
        style={{ background: hell ? 'rgb(255 255 255 / 0.7)' : 'rgb(30 39 52 / 0.7)' }}
      >
        <span class="absolute top-[22%] bottom-[22%] left-[3%] w-[12%] rounded-[3px] bg-[#5ba3d4]" />
      </span>
    </span>
  );
}

const SCHEMATA: { wert: Farbschema; text: string }[] = [
  { wert: 'hell', text: 'Hell' },
  { wert: 'dunkel', text: 'Dunkel' },
  { wert: 'system', text: 'System' },
];

export function FarbschemaWahl(p: { beschriftetVon: string }): JSX.Element {
  const [wahl, setWahl] = createSignal<Farbschema>(farbschemaLaden());
  const knoepfe: HTMLButtonElement[] = [];
  onMount(() => {
    setWahl(farbschemaLaden());
    onCleanup(hoereFarbschema((w) => setWahl(w)));
  });
  const waehle = (j: number) => {
    const s = SCHEMATA[j];
    if (!s) return;
    if (s.wert !== wahl()) {
      farbschemaSetzen(s.wert);
      setWahl(s.wert);
    }
    knoepfe[j]?.focus();
  };
  return (
    <div role="radiogroup" aria-labelledby={p.beschriftetVon} class="grid grid-cols-[repeat(3,minmax(0,1fr))] gap-3 @md:gap-5">
      <For each={SCHEMATA}>
        {(s, i) => {
          const an = () => wahl() === s.wert;
          return (
            <button
              type="button"
              role="radio"
              ref={(el) => (knoepfe[i()] = el)}
              aria-checked={an()}
              tabindex={an() ? 0 : -1}
              onClick={() => waehle(i())}
              onKeyDown={(e) => radioTaste(e, i(), SCHEMATA.length, waehle)}
              class={`group flex min-w-0 flex-col items-center gap-2 rounded-2xl p-1 ${FOKUS}`}
            >
              <span
                class="relative block aspect-[16/11] w-full max-w-40 overflow-hidden rounded-[11px] shadow-[0_6px_18px_-10px_rgb(0_0_0/0.55)] ring-offset-2 ring-offset-transparent transition-[box-shadow,transform] duration-200 ease-out group-hover:-translate-y-px motion-reduce:transition-none"
                classList={{
                  'ring-2 ring-(--color-accent)': an(),
                  'ring-1 ring-[color-mix(in_oklab,var(--color-fg)_14%,transparent)]': !an(),
                }}
              >
                <Show when={s.wert !== 'system'} fallback={<><SchemaBild art="hell" /><span class="absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]"><SchemaBild art="dunkel" /></span></>}>
                  <SchemaBild art={s.wert as 'hell' | 'dunkel'} />
                </Show>
              </span>
              <span class="text-sm transition-colors duration-200" classList={{ 'font-semibold text-(--color-fg)': an(), 'text-(--color-fg-muted)': !an() }}>
                {s.text}
              </span>
            </button>
          );
        }}
      </For>
    </div>
  );
}

function FarbschemaZeile(): JSX.Element {
  const id = createUniqueId();
  const [wahl, setWahl] = createSignal<Farbschema>(farbschemaLaden());
  const [aufgeloest, setAufgeloest] = createSignal<Aufgeloest>(aufloesen(farbschemaLaden()));
  onMount(() => {
    const w = farbschemaLaden();
    setWahl(w);
    setAufgeloest(aufloesen(w));
    onCleanup(
      hoereFarbschema((neu, a) => {
        setWahl(neu);
        setAufgeloest(a);
      }),
    );
  });
  const unter = () =>
    wahl() === 'system'
      ? `Folgt deinem Gerät — gerade ${aufgeloest() === 'light' ? 'hell' : 'dunkel'}.`
      : 'Gilt für alle Fenster, auch eingebettete Seiten.';
  return (
    <Zeile id={`${id}-schema`} titel="Farbschema" unter={unter()} darunter>
      <FarbschemaWahl beschriftetVon={`${id}-schema`} />
    </Zeile>
  );
}

// ── Kulisse ─────────────────────────────────────────────────────────────────

const STILE: { wert: KulisseStil; text: string; satz: string }[] = [
  { wert: 'lava', text: 'Lavalampe', satz: 'Farben treiben langsam ineinander.' },
  { wert: 'ruhig', text: 'Ruhig', satz: 'Die Farben stehen still.' },
  { wert: 'aus', text: 'Aus', satz: 'Nur die Grundfarbe — Flecken, Raster und Linien sind aus.' },
];

/** Farben je Welt für die Knöpfe (dieselben Werte wie styles/os.css, dort für die Kulisse). */
const WELTEN: { wert: KulisseFarben; text: string; farben: [string, string, string, string] }[] = [
  { wert: 'neon', text: 'Neon', farben: ['#22d3ee', '#e879f9', '#8b5cf6', '#fb923c'] },
  { wert: 'aurora', text: 'Aurora', farben: ['#34d399', '#22d3ee', '#6366f1', '#a3e635'] },
  { wert: 'glut', text: 'Glut', farben: ['#fb7185', '#f59e0b', '#ef4444', '#e879f9'] },
];

const TEMPI: { wert: string; text: string; tempo: number }[] = [
  { wert: 'langsam', text: 'Langsam', tempo: 2 },
  { wert: 'normal', text: 'Normal', tempo: 1 },
  { wert: 'schnell', text: 'Schnell', tempo: 0.5 },
];
/** Gespeichert ist ein Faktor der Dauer (1 = normal, 2 = halb so schnell); angezeigt die nächste Stufe. */
export const tempoStufe = (t: number): string =>
  TEMPI.reduce((a, b) => (Math.abs(Math.log(b.tempo) - Math.log(t)) < Math.abs(Math.log(a.tempo) - Math.log(t)) ? b : a)).wert;

function FarbenWahl(p: { beschriftetVon: string; wert: KulisseFarben; onWahl: (f: KulisseFarben) => void }): JSX.Element {
  const knoepfe: HTMLButtonElement[] = [];
  const waehle = (j: number) => {
    const w = WELTEN[j];
    if (!w) return;
    if (w.wert !== p.wert) p.onWahl(w.wert);
    knoepfe[j]?.focus();
  };
  return (
    <div role="radiogroup" aria-labelledby={p.beschriftetVon} class="flex flex-wrap gap-2">
      <For each={WELTEN}>
        {(w, i) => {
          const an = () => p.wert === w.wert;
          return (
            <button
              type="button"
              role="radio"
              ref={(el) => (knoepfe[i()] = el)}
              aria-checked={an()}
              tabindex={an() ? 0 : -1}
              onClick={() => waehle(i())}
              onKeyDown={(e) => radioTaste(e, i(), WELTEN.length, waehle)}
              class={`flex min-h-11 items-center gap-2.5 rounded-full border py-1.5 pr-4 pl-1.5 text-sm transition-[border-color,background-color,color] duration-200 ease-out md:min-h-10 ${FOKUS}`}
              classList={{
                'border-(--color-accent) bg-[color-mix(in_oklab,var(--color-accent)_12%,transparent)] font-semibold text-(--color-fg)': an(),
                'border-(--color-border) text-(--color-fg-muted) hover:text-(--color-fg)': !an(),
              }}
            >
              <span
                aria-hidden="true"
                class="size-7 shrink-0 rounded-full shadow-[inset_0_0_0_1px_rgb(255_255_255/0.18)]"
                style={{ background: `conic-gradient(from 210deg, ${w.farben[0]}, ${w.farben[1]}, ${w.farben[2]}, ${w.farben[3]}, ${w.farben[0]})` }}
              />
              {w.text}
            </button>
          );
        }}
      </For>
    </div>
  );
}

const gleich = (a: KulisseEinstellung, b: KulisseEinstellung) =>
  (Object.keys(b) as (keyof KulisseEinstellung)[]).every((k) => a[k] === b[k]);

function KulisseRegler(p: { titelId: string }): JSX.Element {
  const id = createUniqueId();
  const [k, setK] = createSignal<KulisseEinstellung>(kulisseLaden());
  const [wenigBewegung, setWenigBewegung] = createSignal(false);
  onMount(() => {
    setK(kulisseLaden());
    const neu = (e: Event) => setK(kulisseVon(e));
    window.addEventListener(KULISSE_EREIGNIS, neu);
    window.addEventListener('storage', neu);
    const mq = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
    setWenigBewegung(!!mq?.matches);
    const mqNeu = () => setWenigBewegung(!!mq?.matches);
    mq?.addEventListener?.('change', mqNeu);
    onCleanup(() => {
      window.removeEventListener(KULISSE_EREIGNIS, neu);
      window.removeEventListener('storage', neu);
      mq?.removeEventListener?.('change', mqNeu);
    });
  });
  const aendern = (teil: Partial<KulisseEinstellung>) => {
    const neu = kulissePruefen({ ...k(), ...teil });
    setK(neu);
    kulisseSpeichern(neu);
  };
  const aus = () => k().stil === 'aus';
  const still = () => k().stil !== 'lava';
  const stilSatz = createMemo(() => STILE.find((s) => s.wert === k().stil)?.satz ?? '');
  const prozent = (w: number) => `${Math.round(w)} %`;

  return (
    <div>
      <div class="mb-1 flex flex-wrap items-end justify-between gap-x-4 gap-y-1 border-t border-(--color-border) pt-5">
        <div>
          <h3 id={p.titelId} class="m-0 text-[1.05rem] font-semibold tracking-tight text-(--color-fg)">
            Kulisse
          </h3>
          <p class="m-0 mt-0.5 text-sm text-(--color-fg-muted)">Der Hintergrund hinter den Fenstern.</p>
        </div>
        <button type="button" class={KNOPF_LEISE} disabled={gleich(k(), KULISSE_STANDARD)} onClick={() => aendern({ ...KULISSE_STANDARD })}>
          Zurücksetzen
        </button>
      </div>
      <div class="py-4">
        <KulisseVorschau />
      </div>
      <Zeile id={`${id}-stil`} titel="Stil" unter={stilSatz()}>
        <Wahl beschriftetVon={`${id}-stil`} optionen={STILE} wert={k().stil} onWahl={(stil) => aendern({ stil })} />
      </Zeile>
      <Zeile id={`${id}-farben`} titel="Farben" unter="Färben Kulisse und Leuchtkanten." darunter>
        <FarbenWahl beschriftetVon={`${id}-farben`} wert={k().farben} onWahl={(farben) => aendern({ farben })} />
      </Zeile>
      <Zeile id={`${id}-lava`} titel="Farbflecken" unter="Wie kräftig die Farben leuchten." gesperrt={aus()}>
        <Regler beschriftetVon={`${id}-lava`} wert={k().lava} min={0} max={100} onWert={(lava) => aendern({ lava })} anzeige={prozent} gesperrt={aus()} />
      </Zeile>
      <Zeile id={`${id}-raster`} titel="Neon-Raster" unter="Boden aus Neonlinien mit Horizont." gesperrt={aus()}>
        <Regler beschriftetVon={`${id}-raster`} wert={k().raster} min={0} max={100} onWert={(raster) => aendern({ raster })} anzeige={prozent} gesperrt={aus()} />
      </Zeile>
      <div class="border-t border-(--color-border)">
        <SchalterZeile
          name="Scanlines"
          unter="Feine Zeilen wie auf einem alten Bildschirm."
          an={k().scan}
          gesperrt={aus()}
          onKlick={() => aendern({ scan: !k().scan })}
        />
      </div>
      <Zeile
        id={`${id}-tempo`}
        titel="Tempo"
        unter={wenigBewegung() ? 'Dein Gerät wünscht weniger Bewegung — die Kulisse steht still.' : still() ? 'Nur beim Stil „Lavalampe".' : 'Wie schnell die Farben treiben.'}
        gesperrt={still() || wenigBewegung()}
      >
        <Wahl
          beschriftetVon={`${id}-tempo`}
          optionen={TEMPI}
          wert={tempoStufe(k().tempo)}
          gesperrt={still() || wenigBewegung()}
          onWahl={(w) => aendern({ tempo: TEMPI.find((t) => t.wert === w)?.tempo ?? 1 })}
        />
      </Zeile>
      <Zeile id={`${id}-glas`} titel="Glas" unter="Unschärfe hinter Fenstern und Leisten.">
        <Regler beschriftetVon={`${id}-glas`} wert={k().glas} min={0} max={40} onWert={(glas) => aendern({ glas })} anzeige={(w) => `${Math.round(w)} px`} links="klar" rechts="milchig" />
      </Zeile>
    </div>
  );
}

export default function Erscheinungsbild(p: { kulisseId: string }): JSX.Element {
  return (
    <>
      <FarbschemaZeile />
      <div id={p.kulisseId} class="scroll-mt-24 pt-2">
        <KulisseRegler titelId={`${p.kulisseId}-titel`} />
      </div>
    </>
  );
}
