/**
 * Fenster — der Rahmen einer Fläche im OS.
 *
 * Glas, ein Kopf wie am Mac (Ampel links: Schließen, Minimieren, Zoomen; Titel in der Mitte;
 * ⋯ rechts) und eine Ecke zum Ziehen der Größe, die am 12er-Raster einrastet. ⋯, Rechtsklick auf
 * den Kopf und Umschalt+F10 öffnen dasselbe Menü (Größe, Platz, Bildschirm, neu laden, im Tab
 * öffnen, schließen) — gebaut vom Raster, gezeichnet von components/os/Menue.tsx.
 *
 * Widget oder Anwendung (Flaeche.anwendung): Ein Widget ist eine Kachel, sein grüner Knopf zoomt zwischen voller und halber
 * Breite. Eine Anwendung öffnet groß; ihr grüner Knopf schickt sie in den Vollbild-Bildschirm (lib/os/bildschirme.ts),
 * ⌥-Klick und Doppelklick auf den Kopf maximieren sie (`Fenster.max`, das Raster legt sie über den ganzen Bildschirm).
 */
import { Show, createSignal, lazy, onCleanup, onMount, type JSX } from 'solid-js';
import { Dynamic } from 'solid-js/web';
import AppEingebettet from '~/components/apps/AppEingebettet';
import { SPALTEN, SPALTEN_MIN, ZEILEN_MAX, ZEILEN_MIN, type Fenster, type StartZustand } from '~/lib/os/anordnung';
import type { Flaeche } from '~/lib/os/flaechen';
import { menueOeffnen, type MenuePunkt } from '~/lib/os/menue';
import { nativZu, type NativProps } from '~/lib/os/nativ';
import { fremdesThemaAnwenden } from '~/lib/os/thema';
import { ausHerkunft } from '~/lib/os/uebergang';
import {
  ablageAufApp, aktuellerZug, gutArt, gutLesen, gutSetzen, hinweisWeg, hinweisZeigen, wasPassiert, zugBeginnt, zugBild, zugEndet,
  zustellungAbholen, type Gut,
} from '~/lib/os/ziehen';
import { AppAktionen, AppTitel } from './AppRahmen';

/**
 * Was eine eingebettete Seite darf: Ohne `allow` sperrt der Browser im iframe Zwischenablage, Vollbild,
 * Pointer-Lock und Gamepad. Ein Bildschirm-Stream (Remote-Desktop) braucht genau das, sonst lässt sich
 * weder kopieren noch die Maus im Spiel oder Desktop fangen.
 */
const SEITE_DARF = 'clipboard-read; clipboard-write; fullscreen; gamepad; autoplay; keyboard-map';

/** Native Komponenten werden einmal geladen und dann wiederverwendet. */
const NATIV = new Map<string, ReturnType<typeof lazy<(p: NativProps) => JSX.Element>>>();
function nativKomponente(id: string) {
  const e = nativZu(id);
  if (!e) return null;
  if (!NATIV.has(id)) NATIV.set(id, lazy(e.laden));
  return NATIV.get(id)!;
}

/**
 * Inhalt eines Fensters je Art der Fläche. Beim Ziehen bekommen eingebettete Seiten keine Zeiger — sonst schluckt
 * jedes iframe, über das der Zug fährt, die Ereignisse. Ausnahme: die Seite, aus der gezogen wird (sie legt z. B.
 * eine Karte in eine andere Spalte).
 *
 * Eine Scrollebene: Hub-Apps und native Flächen haben ihre natürliche Höhe, das Fenster wächst mit und
 * nur die Fläche scrollt — nicht jede App für sich. Seiten (eigene Dokumente fremder Höhe) füllen das Fenster
 * weiter und scrollen für sich.
 */
export function Inhalt(p: { f: Flaeche; ziehen: boolean; oeffne: (id: string) => void; schmal: boolean; start?: StartZustand; fest?: boolean }): JSX.Element {
  const zeiger = () => ({ 'pointer-events': p.ziehen ? ('none' as const) : ('auto' as const) });
  let seite: HTMLIFrameElement | undefined;
  const seiteZeiger = () => {
    const quelle = aktuellerZug()?.quelle;
    const eigen = !!quelle && !!seite && quelle === seite.contentWindow;
    return { 'pointer-events': p.ziehen && !eigen ? ('none' as const) : ('auto' as const) };
  };
  // Höhe festgehalten (Fenster.fest): der Inhalt füllt das Fenster und scrollt in ihm.
  // Gelesen beim Aufbau — ein Wechsel baut den Inhalt über `inhaltSchluessel` neu.
  const fest = p.fest;
  if (p.f.art === 'nativ') {
    const k = nativKomponente(p.f.id);
    return (
      <div class={fest ? 'h-full overflow-auto' : 'flex flex-1 flex-col'} style={zeiger()}>
        <Show when={k} fallback={<p class="p-5 text-sm text-(--color-fg-muted)">Diese Fläche gibt es nicht mehr.</p>}>
          <Dynamic component={k!} oeffne={p.oeffne} schmal={p.schmal} />
        </Show>
      </div>
    );
  }
  if (p.f.art === 'hubapp') {
    // Zieht die App selbst (App.ziehbar), bleibt ihr Zeiger an: sonst bricht der Browser den Zug in ihr ab, sobald sie ihn meldet
    let appBox: HTMLDivElement | undefined;
    const appZeiger = () => {
      const quelle = aktuellerZug()?.quelle;
      const eigen = !!quelle && !!appBox && quelle === appBox.querySelector('iframe')?.contentWindow;
      return { 'pointer-events': p.ziehen && !eigen ? ('none' as const) : ('auto' as const) };
    };
    return (
      <div ref={appBox} class={fest ? 'h-full overflow-auto' : 'flex-1'} style={appZeiger()}>
        <AppEingebettet name={p.f.appName!} wachsen={!fest} fuellen={fest} start={p.start} schluessel={p.f.id} />
      </div>
    );
  }
  // Ladezustand: bis zum ersten Bild steht „Lädt …“ da. Seiten sind alle von hier; landet eine anderswo
  // (fremder Ursprung, contentDocument null), hat die Anmeldung zu einem Anmeldedienst umgeleitet.
  const [stand, setStand] = createSignal<'laedt' | 'da' | 'anmelden'>('laedt');
  return (
    <div class="relative h-full w-full">
      <iframe
        ref={seite}
        src={p.f.pfad}
        title={p.f.titel}
        loading="lazy"
        allow={SEITE_DARF}
        class="h-full w-full border-0 bg-transparent"
        style={seiteZeiger()}
        // Geladen: Nachrichten, die schon auf die Seite warten (Ding auf den Schreibtisch gezogen), abholen
        onLoad={(e) => {
          const fremd = !e.currentTarget.contentDocument;
          setStand(fremd ? 'anmelden' : 'da');
          if (fremd) return;
          if (p.f.art === 'agent') fremdesThemaAnwenden(e.currentTarget);
          e.currentTarget.dataset.geladen = '';
          zustellungAbholen(p.f.id, e.currentTarget.contentWindow);
        }}
      />
      <Show when={stand() !== 'da'}>
        <div class="absolute inset-0 grid place-items-center bg-(--os-glas-tief) text-sm text-(--color-fg-muted)" role="status">
          <Show when={stand() === 'anmelden'} fallback={<span>Lädt …</span>}>
            <div class="text-center">
              <p class="m-0">Die Anmeldung ist abgelaufen.</p>
              <button type="button" class="os-knopf mt-3 px-3" onClick={() => location.reload()}>Neu anmelden</button>
            </div>
          </Show>
        </div>
      </Show>
    </div>
  );
}

/** Maße des Rasters, um eine Zeigerposition in Spalten und Zeilen umzurechnen. */
export interface RasterMass {
  spalte: number; // Breite einer Spalte in px
  zeile: number; // Höhe einer Rasterzeile in px
  luecke: number; // Abstand in px
}

export interface FensterProps {
  f: Flaeche;
  w: Fenster;
  /** CSS für die Lage im Raster (grid-column / grid-row) */
  lage: JSX.CSSProperties;
  /** Aktuelle Größe in Rastereinheiten (aus Hand oder Automatik) */
  spalten: number;
  zeilen: number;
  fokus: boolean;
  ziehen: boolean;
  schmal: boolean;
  mass: () => RasterMass | null;
  /** Das Menü des Fensters (⋯-Knopf, Rechtsklick auf den Kopf) — baut das Raster. */
  punkte: () => MenuePunkt[];
  onFokus: () => void;
  onSchliessen: () => void;
  onMinimieren: () => void;
  /** `fest`: die Höhe wurde von Hand gezogen — das Fenster hält sie, statt mit dem Inhalt zu wachsen */
  onGroesse: (g: { spalten?: number; zeilen?: number; fest?: boolean }) => void;
  onZiehStart: () => void;
  onZiehEnde: () => void;
  /** Etwas auf dieses Fenster gelegt (Fenster: davor einordnen; Fläche, Ding: öffnen) */
  onAblegen: (g: Gut) => void;
  onVerschieben: (richtung: -1 | 1) => void;
  oeffne: (id: string) => void;
  /** Anwendungen: maximieren (ganzer Arbeitsbereich) oder die Maximierung beenden — ⌥-Klick auf den grünen Knopf, Doppelklick auf den Kopf */
  onMaximieren?: () => void;
  /** Anwendungen: in den Vollbild-Bildschirm wechseln oder ihn verlassen — grüner Knopf, ⌃⌘F */
  onVollbild?: () => void;
  /** Dieses Fenster steht auf einem Vollbild-Bildschirm */
  vollbild?: boolean;
}

/** Ereignis „Fenster neu laden“ (aus Menüs): `detail` ist die ID der Fläche. */
export const NEU_LADEN = 'fyos:fenster-neu-laden';

export default function FensterRahmen(p: FensterProps): JSX.Element {
  const [ueber, setUeber] = createSignal(false);
  const [groesseZiehen, setGroesseZiehen] = createSignal(false);
  const [stand, setStand] = createSignal(0);
  let ich: HTMLElement | undefined;
  let menueKnopf: HTMLButtonElement | undefined;

  const neuLaden = (e: Event) => {
    if ((e as CustomEvent<string>).detail === p.f.id) setStand((n) => n + 1);
  };
  window.addEventListener(NEU_LADEN, neuLaden);
  onCleanup(() => window.removeEventListener(NEU_LADEN, neuLaden));
  // Aus dem Dock wiederhergestellt: wächst aus dem Symbol auf (lib/os/uebergang.ts)
  onMount(() => { if (ich) ausHerkunft(p.f.id, ich); });

  const taste = (e: KeyboardEvent) => {
    if ((e.shiftKey && e.key === 'F10') || e.key === 'ContextMenu') {
      e.preventDefault();
      menueAmKnopf(true);
    } else if (e.altKey && e.shiftKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      p.onVerschieben(e.key === 'ArrowLeft' ? -1 : 1);
    }
  };

  /** Höhe in Rasterzeilen, wie das Fenster gerade dasteht (in der Automatik ist `p.zeilen` 0). */
  const zeilenJetzt = (): number => {
    const m = p.mass();
    if (!m || !ich) return 10;
    return Math.round((ich.getBoundingClientRect().height + m.luecke) / (m.zeile + m.luecke));
  };
  /** Widget: grüner Knopf und Doppelklick auf den Kopf schalten volle Breite ↔ halbe (wie „Zoomen“ am Mac). */
  const zoomen = () => p.onGroesse({ spalten: p.spalten >= SPALTEN ? 6 : SPALTEN });
  /** Anwendung (nicht auf dem Handy, dort steht ohnehin ein Fenster da): Vollbild-Bildschirm, maximieren. */
  const anwendung = () => !!p.f.anwendung && !p.schmal;
  /** Grüner Knopf einer Anwendung: Vollbild-Bildschirm; mit ⌥ maximieren (auf dem Vollbild-Bildschirm verlässt jeder Klick ihn). */
  const gruenKlick = (e: MouseEvent) => {
    if (!anwendung()) return zoomen();
    if (e.altKey && !p.vollbild) p.onMaximieren?.();
    else p.onVollbild?.();
  };
  const gruenTitel = (): string => {
    if (!anwendung()) return p.spalten >= SPALTEN ? 'Halbe Breite' : 'Volle Breite';
    if (p.vollbild) return 'Vollbild verlassen (⌃⌘F)';
    return p.w.max ? 'Vollbild-Bildschirm (⌃⌘F) — ⌥-Klick: Maximierung beenden' : 'Vollbild-Bildschirm (⌃⌘F) — ⌥-Klick: maximieren';
  };

  // Größe ziehen: Zeigerposition → Spalten/Zeilen, rastet live ein. Die Ecke ändert beides, die rechte Kante nur die
  // Breite, die untere nur die Höhe (wie am Mac).
  /** Läuft gerade ein Größe-Ziehen, beendet dies es; auch wenn das Fenster mittendrin verschwindet (Schließen per Kürzel). */
  let ziehenBeenden: (() => void) | undefined;
  onCleanup(() => ziehenBeenden?.());
  const groesseStart = (e: PointerEvent, richtung: 'beide' | 'breite' | 'hoehe' = 'beide') => {
    const m = p.mass();
    if (!m || !ich) return;
    ziehenBeenden?.();
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const r = ich.getBoundingClientRect();
    const spaltenVorher = p.spalten;
    const zeilenVorher = p.zeilen || zeilenJetzt();
    setGroesseZiehen(true);
    p.onZiehStart();
    const bewegen = (ev: PointerEvent) => {
      const spalten = richtung === 'hoehe' ? spaltenVorher : Math.round((ev.clientX - r.left + m.luecke) / (m.spalte + m.luecke));
      const zeilen = richtung === 'breite' ? zeilenVorher : Math.round((ev.clientY - r.top + m.luecke) / (m.zeile + m.luecke));
      const s = Math.min(SPALTEN, Math.max(SPALTEN_MIN, spalten));
      const z = Math.min(ZEILEN_MAX, Math.max(ZEILEN_MIN, zeilen));
      // Wer die Höhe zieht, will genau diese Höhe: das Fenster hält sie (sonst wüchse es gleich wieder mit dem Inhalt)
      if (s !== p.spalten || z !== p.zeilen) p.onGroesse({ spalten: s, zeilen: z, ...(z !== zeilenVorher ? { fest: true } : {}) });
    };
    const ende = () => {
      ziehenBeenden = undefined;
      window.removeEventListener('pointermove', bewegen);
      window.removeEventListener('pointerup', ende);
      window.removeEventListener('pointercancel', ende);
      setGroesseZiehen(false);
      p.onZiehEnde();
    };
    ziehenBeenden = ende;
    window.addEventListener('pointermove', bewegen);
    window.addEventListener('pointerup', ende);
    window.addEventListener('pointercancel', ende);
  };

  const menueAm = (x: number, y: number, tastatur = false) => menueOeffnen({ x, y, punkte: p.punkte(), tastatur });
  function menueAmKnopf(tastatur = false) {
    const r = menueKnopf?.getBoundingClientRect();
    if (r) menueAm(r.right - 240, r.bottom + 4, tastatur);
  }
  /** Hub-Apps tragen ihr Gesicht im Kopf und bieten Agent fragen, Link kopieren, Heften an (AppRahmen.tsx). */
  const istApp = () => p.f.art === 'hubapp';
  /** Ändert sich der Startzustand (neuer Link mit Eingabe auf eine offene App), lädt die App neu. */
  // `fest` wechselt füllen ↔ wachsen und baut den Inhalt neu — nur bei Apps und nativen Flächen (Seiten füllen immer)
  const wachsend = () => p.f.art === 'hubapp' || p.f.art === 'nativ';
  const inhaltSchluessel = () => `${stand()}:${p.w.start ? JSON.stringify(p.w.start) : ''}:${wachsend() && (p.w.fest || p.w.max) ? 'fest' : ''}`;
  const menueKnopfBau = (): JSX.Element => (
    <button
      ref={menueKnopf}
      type="button"
      class="os-knopf"
      aria-label={`${p.f.titel}: Größe und Platz`}
      aria-haspopup="menu"
      title="Optionen"
      onClick={(e) => menueAmKnopf(e.detail === 0)}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="8" r="1.3" fill="currentColor" /><circle cx="8" cy="8" r="1.3" fill="currentColor" /><circle cx="13" cy="8" r="1.3" fill="currentColor" /></svg>
    </button>
  );

  return (
    <section
      ref={ich}
      aria-label={p.f.titel}
      data-fenster={p.f.id}
      data-art={p.f.anwendung ? 'anwendung' : undefined}
      data-max={p.w.max ? '' : undefined}
      class="os-glas os-fenster relative flex min-w-0 flex-col overflow-clip"
      classList={{ 'os-fokus': p.fokus || ueber(), 'select-none': groesseZiehen(), 'os-max': !!p.w.max && !p.schmal }}
      style={p.lage}
      onPointerDown={() => p.onFokus()}
      onDragOver={(e) => {
        const art = gutArt(e.dataTransfer);
        if (!art || aktuellerZug()?.id === p.f.id) return;
        e.preventDefault();
        e.stopPropagation(); // der Schreibtisch darunter soll seinen Hinweis nicht drüberlegen
        if (e.dataTransfer) e.dataTransfer.dropEffect = art === 'fenster' ? 'move' : 'copy';
        setUeber(true);
        // Fenster einer Hub-App: nimmt sie das Ding per Übergabe an, steht ihre Wirkung da; sonst nur „Agent fragen“
        const app = istApp() ? ablageAufApp(art, p.f.id) : null;
        if (ich) hinweisZeigen(ich, art === 'fenster' ? 'Davor einordnen' : app ? app.text : wasPassiert(art, 'schreibtisch'));
      }}
      onDragLeave={(e) => {
        if (e.relatedTarget instanceof Node && ich?.contains(e.relatedTarget)) return;
        setUeber(false);
        hinweisWeg(ich);
      }}
      onDrop={(e) => {
        const g = gutLesen(e.dataTransfer);
        setUeber(false);
        hinweisWeg();
        if (!g) return;
        e.preventDefault();
        e.stopPropagation();
        zugEndet();
        p.onAblegen(g);
      }}
    >
      <header
        class="os-kopf cursor-grab select-none"
        classList={{ 'os-kopf-app': istApp() }}
        draggable="true"
        tabindex="0"
        data-kontext={`fenster:${p.f.id}`}
        aria-label={`${p.f.titel} — Titelleiste. Ziehen ordnet um, Alt+Umschalt+Pfeil verschiebt, Umschalt+F10 öffnet das Menü.`}
        onKeyDown={taste}
        onDblClick={(e) => {
          if ((e.target as Element).closest('button')) return;
          if (anwendung() && !p.vollbild) p.onMaximieren?.();
          else if (!anwendung()) zoomen();
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          p.onFokus();
          menueAm(e.clientX, e.clientY);
        }}
        onDragStart={(e) => {
          gutSetzen(e.dataTransfer, { art: 'fenster', id: p.f.id }, p.f.titel);
          zugBild(e.dataTransfer, p.f.titel);
          zugBeginnt({ art: 'fenster', id: p.f.id });
        }}
        onDragEnd={() => { zugEndet(); hinweisWeg(); }}
      >
        {/* Ampel wie am Mac: Schließen, Minimieren, Zoomen — die Zeichen erscheinen beim Darüberfahren */}
        <div class="os-ampel" role="group" aria-label="Fenster">
          <button type="button" class="os-ampel-rot no-touch" aria-label={`${p.f.titel} schließen`} title="Schließen" onClick={() => p.onSchliessen()}>
            <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3.8 3.8l4.4 4.4M8.2 3.8l-4.4 4.4" /></svg>
          </button>
          <button type="button" class="os-ampel-gelb no-touch" aria-label={`${p.f.titel} minimieren`} title="Minimieren" onClick={() => p.onMinimieren()}>
            <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 6h6" /></svg>
          </button>
          <Show when={!p.schmal}>
            <button
              type="button"
              class="os-ampel-gruen no-touch"
              aria-label={anwendung() ? `${p.f.titel} ${p.vollbild ? 'Vollbild verlassen' : 'im Vollbild'}` : `${p.f.titel} zoomen`}
              title={gruenTitel()}
              onClick={gruenKlick}
            >
              <svg viewBox="0 0 12 12" aria-hidden="true"><path class="voll" d="M3.6 8.4V4.8l3.6 3.6zM8.4 3.6v3.6L4.8 3.6z" /></svg>
            </button>
          </Show>
        </div>
        <Show
          when={istApp()}
          fallback={
            <>
              {/* Seiten und native Flächen: Symbol und Titel in der Mitte (wie das Dokumentsymbol am Mac) — jedes Fenster trägt sein Gesicht */}
              <AppTitel f={p.f} />
              {menueKnopfBau()}
            </>
          }
        >
          <AppTitel f={p.f} />
          <div class="os-app-aktionen" role="group" aria-label={`${p.f.titel}: Aktionen`}>
            <AppAktionen f={p.f} start={p.w.start} />
            {menueKnopfBau()}
          </div>
        </Show>
      </header>

      {/* Inhalt: Rechtsklick hier gehört der Fläche (Text kopieren usw.), nicht dem OS */}
      <div class="flex min-h-0 flex-1 flex-col" data-kontext="inhalt">
        <Show when={inhaltSchluessel()} keyed>
          {(_) => <Inhalt f={p.f} ziehen={p.ziehen} oeffne={p.oeffne} schmal={p.schmal} start={p.w.start} fest={!!p.w.fest || !!p.w.max} />}
        </Show>
      </div>

      <Show when={!p.schmal && !p.w.max}>
        <button
          type="button"
          class="os-griff"
          aria-label={`${p.f.titel}: Größe ziehen`}
          title="Ziehen ändert die Größe"
          onPointerDown={(e) => groesseStart(e, 'beide')}
          onKeyDown={(e) => {
            const s = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
            const z = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0;
            if (s || z) { e.preventDefault(); p.onGroesse({ spalten: p.spalten + s, zeilen: (p.zeilen || zeilenJetzt()) + z, ...(z ? { fest: true } : {}) }); }
          }}
        />
        {/* Kanten: nur für den Zeiger (die Tastatur nimmt die Ecke mit Pfeiltasten) */}
        <div class="os-kante os-kante-r" aria-hidden="true" onPointerDown={(e) => groesseStart(e, 'breite')} />
        <div class="os-kante os-kante-u" aria-hidden="true" onPointerDown={(e) => groesseStart(e, 'hoehe')} />
      </Show>
    </section>
  );
}
