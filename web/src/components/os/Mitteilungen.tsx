/**
 * Mitteilungen — „Der Agent zeigt dir …“ oben rechts im OS, wie eine Mitteilung am Mac.
 *
 * Eine Quelle (z. B. der Agent) übergibt eine Mitteilung (lib/os/mitteilungen.ts). Hier steht sie: das Symbol der
 * Fläche, „Zeigt dir“, der Name der Fläche, ein, zwei Sätze
 * Vorschau, „Öffnen“. Bis zu drei stehen übereinander (die neueste oben), nach ~10 s gehen sie von selbst,
 * außer man fährt darüber oder hat den Fokus darin — dann bleiben sie. Ein Klick (oder Enter) auf die Karte
 * öffnet die App, Esc schließt die Karte, in der der Fokus steht. ⋯ bietet: Öffnen, Schließen, Link kopieren,
 * eine Stunde stumm, Mitteilungen ausschalten.
 *
 * Die Stapel- und Zeitlogik
 * steht in lib/os/mitteilungen.ts, die Gestaltung in styles/os-mitteilung.css.
 */
import { For, Show, createEffect, createMemo, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import '~/styles/os-mitteilung.css';
import type { Flaeche } from '~/lib/os/flaechen';
import { ANZEIGE_MS, ANZEIGE_NACHGEHOLT_MS, nachholZeit, zeitText, type Mitteilung } from '~/lib/os/mitteilungen';
import { agentName } from '~/lib/config';
import { menue, menueOeffnen, type MenuePunkt } from '~/lib/os/menue';
import { deeplink } from '~/lib/os/oeffnen';
import Symbol, { Glyphe } from './Symbol';

/** So lange spielt die Ausblend-Bewegung (CSS: os-mitteilung-aus) — danach wird die Karte entfernt. */
const AUS_MS = 200;
/** Mindestens so lange bleibt eine Karte noch stehen, wenn man die Maus wieder wegnimmt. */
const REST_MIN_MS = 4_000;

/** Eine kurze Rückmeldung mit „Rückgängig“ — nach „stumm“ oder „ausschalten“, damit das nicht ohne Rückweg bleibt. */
export interface Hinweis {
  text: string;
  zurueck: () => void;
}
const HINWEIS_MS = 8_000;

export interface MitteilungenProps {
  liste: () => Mitteilung[];
  flaeche: (id: string) => Flaeche | undefined;
  /** Die App der Mitteilung öffnen; ein Text, wenn es nicht ging (die Karte bleibt dann stehen) */
  onOeffnen: (m: Mitteilung) => Promise<string | null>;
  /** Die Karte ist ausgeblendet und kann aus dem Stapel */
  onWeg: (id: number) => void;
  onStumm: (minuten: number) => void;
  onAus: () => void;
  hinweis?: () => Hinweis | null;
  onHinweisWeg?: () => void;
}

function HinweisKarte(p: { h: Hinweis; onWeg: () => void }): JSX.Element {
  const [ueber, setUeber] = createSignal(false);
  const [weg, setWeg] = createSignal(false);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const schliessen = () => {
    if (weg()) return;
    setWeg(true);
    setTimeout(p.onWeg, AUS_MS);
  };
  createEffect(() => {
    clearTimeout(timer);
    if (!ueber() && !weg()) timer = setTimeout(schliessen, HINWEIS_MS);
  });
  onCleanup(() => clearTimeout(timer));
  return (
    <div
      class="os-mitteilung os-mitteilung-hinweis"
      classList={{ 'os-mitteilung-weg': weg() }}
      onPointerEnter={() => setUeber(true)}
      onPointerLeave={() => setUeber(false)}
      onFocusIn={() => setUeber(true)}
      onFocusOut={() => setUeber(false)}
    >
      <Glyphe name="bell-off" class="os-mitteilung-hinweis-symbol" />
      <span class="os-mitteilung-hinweis-text">{p.h.text}</span>
      <button
        type="button"
        class="os-mitteilung-rueckgaengig"
        onClick={() => {
          p.h.zurueck();
          schliessen();
        }}
      >
        Rückgängig
      </button>
    </div>
  );
}

function Karte(p: { m: Mitteilung; stufe: number; jetzt: () => number; sichtbar: () => boolean } & Omit<MitteilungenProps, 'liste' | 'hinweis' | 'onHinweisWeg'>): JSX.Element {
  const z = p.m.zeigt;
  const [weg, setWeg] = createSignal(false);
  const [ueber, setUeber] = createSignal(false);
  const [fehler, setFehler] = createSignal('');
  const [laeuft, setLaeuft] = createSignal(false);
  const flaeche = () => p.flaeche(z.ziel);
  const menueQuelle = `mitteilung:${p.m.id}`;
  const menueOffen = () => menue()?.quelle === menueQuelle;
  const pausiert = () => ueber() || menueOffen() || laeuft() || !!fehler() || !p.sichtbar();

  // ── Von selbst ausblenden (pausiert beim Darüberfahren, im Hintergrund-Tab, bei offenem Menü) ──
  let rest = z.nachgeholt ? ANZEIGE_NACHGEHOLT_MS : ANZEIGE_MS;
  let seit = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const schliessen = () => {
    if (weg()) return;
    clearTimeout(timer);
    setWeg(true);
    setTimeout(() => p.onWeg(p.m.id), AUS_MS);
  };
  const anhalten = () => {
    if (timer === undefined) return;
    clearTimeout(timer);
    timer = undefined;
    rest = Math.max(REST_MIN_MS, rest - (Date.now() - seit));
  };
  const laufen = () => {
    clearTimeout(timer);
    seit = Date.now();
    timer = setTimeout(schliessen, rest);
  };
  createEffect(() => {
    if (weg()) return;
    if (pausiert()) anhalten();
    else laufen();
  });
  onCleanup(() => clearTimeout(timer));

  const oeffnen = async () => {
    if (laeuft() || weg()) return;
    setLaeuft(true);
    setFehler('');
    const f = await p.onOeffnen(p.m).catch((e: unknown) => (e instanceof Error ? e.message : String(e)));
    setLaeuft(false);
    if (f) setFehler(f);
    else schliessen();
  };

  const punkte = (): MenuePunkt[] => [
    { text: 'Öffnen', symbol: 'arrow-up-right', tun: () => void oeffnen() },
    // Ältere Karten stehen kompakt da (ohne Knopf „Schließen“, os-mitteilung.css): hier bleibt der Weg
    // für Tastatur und Screenreader, auch am Handy ohne Escape-Taste.
    { text: 'Schließen', symbol: 'x', tun: schliessen },
    {
      text: 'Link kopieren',
      symbol: 'link',
      tun: () => void navigator.clipboard?.writeText(z.link ?? deeplink(z.ziel, z.eingabe)).catch(() => {}),
    },
    { art: 'trenner' },
    { text: 'Eine Stunde stumm', symbol: 'moon', tun: () => { p.onStumm(60); schliessen(); } },
    { text: 'Mitteilungen ausschalten', symbol: 'bell-off', tun: () => { p.onAus(); schliessen(); } },
  ];
  const menueAuf = (e: MouseEvent) => {
    e.stopPropagation();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    menueOeffnen({ x: r.right - 248, y: r.bottom + 4, punkte: punkte(), quelle: menueQuelle, tastatur: e.detail === 0 });
  };

  const titel = () => z.titel || flaeche()?.titel || 'App';
  /** „Agent meldet sich“ bei eigenen Meldungen (os.mitteilen), „Agent zeigt dir“ beim Ergebnis einer App */
  const meldet = () => z.art === 'mitteilung';
  /** Nachgeholt: wann es entstanden ist („heute Nacht, 03:12“), sonst wie lange her */
  const zeit = () => (z.nachgeholt && z.entstanden ? nachholZeit(z.entstanden, p.jetzt()) : zeitText(p.m.seit, p.jetzt()));

  return (
    <article
      class="os-mitteilung"
      classList={{ 'os-mitteilung-weg': weg() }}
      style={{ '--stufe': String(p.stufe) }}
      data-mitteilung={p.m.id}
      data-kontext="inhalt"
      tabindex="0"
      role="group"
      aria-label={`${agentName()} ${meldet() ? 'meldet sich' : 'zeigt dir'} ${titel()}. Enter öffnet, Escape schließt.`}
      onPointerEnter={() => setUeber(true)}
      onPointerLeave={() => setUeber(false)}
      onFocusIn={() => setUeber(true)}
      onFocusOut={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setUeber(false);
      }}
      onClick={(e) => {
        if ((e.target as Element).closest('button')) return;
        void oeffnen();
      }}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          void oeffnen();
        }
      }}
    >
      <Symbol id={z.ziel} gruppe={flaeche()?.gruppe} class="os-mitteilung-symbol" />
      <div class="os-mitteilung-text">
        <div class="os-mitteilung-kopf">
          <span class="os-mitteilung-ueber">{agentName()} {meldet() ? 'meldet sich' : 'zeigt dir'}</span>
          <time class="os-mitteilung-zeit" classList={{ 'os-mitteilung-nachgeholt': !!z.nachgeholt }}>{zeit()}</time>
          <span class="os-mitteilung-knoepfe">
            <button type="button" class="os-mitteilung-knopf" aria-label="Weitere Aktionen" aria-haspopup="menu" title="Weitere Aktionen" onClick={menueAuf}>
              <Glyphe name="ellipsis" />
            </button>
            {/* Das × ist für die Maus; der Knopf „Schließen“ unten ist derselbe Weg für Tastatur und Screenreader. */}
            <button type="button" class="os-mitteilung-knopf" aria-hidden="true" title="Schließen" tabindex="-1" onClick={schliessen}>
              <Glyphe name="x" />
            </button>
          </span>
        </div>
        <p class="os-mitteilung-titel">
          <strong>{titel()}</strong>
          <Show when={z.untertitel}>
            <span class="os-mitteilung-unter"> {z.untertitel}</span>
          </Show>
        </p>
        <Show when={z.vorschau}>
          <p class="os-mitteilung-vorschau">{z.vorschau}</p>
        </Show>
        <Show when={fehler()}>
          <p role="alert" class="os-mitteilung-fehler">{fehler()}</p>
        </Show>
        <div class="os-mitteilung-aktionen">
          <button type="button" class="os-mitteilung-oeffnen" disabled={laeuft()} onClick={() => void oeffnen()}>
            Öffnen
            <Glyphe name="arrow-up-right" />
          </button>
          <button type="button" class="os-mitteilung-schliessen" onClick={schliessen}>Schließen</button>
        </div>
      </div>
    </article>
  );
}

export default function Mitteilungen(p: MitteilungenProps): JSX.Element {
  const [jetzt, setJetzt] = createSignal(Date.now());
  const [sichtbar, setSichtbar] = createSignal(true);
  onMount(() => {
    const takt = setInterval(() => setJetzt(Date.now()), 20_000);
    const v = () => setSichtbar(document.visibilityState === 'visible');
    v();
    document.addEventListener('visibilitychange', v);
    onCleanup(() => {
      clearInterval(takt);
      document.removeEventListener('visibilitychange', v);
    });
  });
  createEffect(() => {
    if (p.liste().length) setJetzt(Date.now());
  });
  const liste = createMemo(() => p.liste());

  const taste = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return;
    const karte = (e.target as Element).closest<HTMLElement>('[data-mitteilung]');
    if (!karte) return;
    e.preventDefault();
    e.stopPropagation();
    karte.querySelector<HTMLButtonElement>('.os-mitteilung-schliessen')?.click();
    // Der Fokus soll nicht ins Leere fallen: auf die nächste Karte, wenn es eine gibt.
    const andere = [...(karte.parentElement?.querySelectorAll<HTMLElement>('[data-mitteilung]') ?? [])].filter((x) => x !== karte);
    andere[0]?.focus();
  };

  return (
    <div class="os-mitteilungen" role="status" aria-live="polite" aria-label={`Mitteilungen von ${agentName()}`} onKeyDown={taste}>
      <For each={liste()}>
        {(m, i) => (
          <Karte
            m={m}
            stufe={i()}
            jetzt={jetzt}
            sichtbar={sichtbar}
            flaeche={p.flaeche}
            onOeffnen={p.onOeffnen}
            onWeg={p.onWeg}
            onStumm={p.onStumm}
            onAus={p.onAus}
          />
        )}
      </For>
      <Show when={p.hinweis?.()} keyed>
        {(h) => <HinweisKarte h={h} onWeg={() => p.onHinweisWeg?.()} />}
      </Show>
    </div>
  );
}
