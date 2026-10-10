/**
 * Raster — ein Arbeitsbildschirm des OS.
 *
 * 12 Spalten. Solange nichts von Hand gesetzt wird, verteilt die Automatik die Fenster gleichmäßig
 * und füllt die Höhe (1 groß, 2 nebeneinander, 3 in einer Zeile, 4 als 2×2 …). Der erste Eingriff
 * (Größe ziehen, Breite/Höhe im Menü) friert die aktuelle Verteilung ein; ab dann gilt seine.
 * Umordnen, Größe und „neue Zeile“ gleiten weich an ihren Platz (FLIP, nur Verschiebung — Inhalte
 * werden nie verzerrt). Auf dem Handy steht immer genau ein Fenster da.
 */
import { For, Show, createMemo, createSignal, type JSX } from 'solid-js';
import { systemName } from '~/lib/config';
import FensterRahmen, { NEU_LADEN, type RasterMass } from './Fenster';
import {
  NEU_SPALTEN, NEU_ZEILEN, SPALTEN, ZEILEN_MAX, ZEILEN_MIN, autoReihen, autoSpalten, automatisch, davorSetzen, festSetzen, groesseSetzen, minimieren,
  neueZeileUmschalten, schliessen, verschieben, vonHand, type Fenster,
} from '~/lib/os/anordnung';
import { aktionsPunkte } from '~/lib/os/app-aktionen';
import { automatischBenannt, type Bildschirm } from '~/lib/os/bildschirme';
import { inNeuemTab } from '~/lib/os/allein';
import { deeplink } from '~/lib/os/oeffnen';
import type { Flaeche } from '~/lib/os/flaechen';
import { altUmschalt, type MenuePunkt } from '~/lib/os/menue';
import { ausklingen, insDock } from '~/lib/os/uebergang';
import { gutArt, gutLesen, hinweisWeg, hinweisZeigen, wasPassiert, zugEndet, type Gut } from '~/lib/os/ziehen';

/** Höhe einer Rasterzeile (CSS); 10 Zeilen ≈ 50 rem. */
const ZEILE_REM = 2.5;

function mitUebergang(behaelter: HTMLElement | undefined, aendern: () => void): void {
  const ruhig = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!behaelter || ruhig || typeof (behaelter as HTMLElement & { animate?: unknown }).animate !== 'function') {
    aendern();
    return;
  }
  const vorher = new Map<string, DOMRect>();
  behaelter.querySelectorAll<HTMLElement>(':scope > [data-fenster]').forEach((el) => vorher.set(el.dataset.fenster!, el.getBoundingClientRect()));
  aendern();
  requestAnimationFrame(() => {
    behaelter.querySelectorAll<HTMLElement>(':scope > [data-fenster]').forEach((el) => {
      const a = vorher.get(el.dataset.fenster!);
      if (!a) return;
      const b = el.getBoundingClientRect();
      const dx = a.left - b.left;
      const dy = a.top - b.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], {
        duration: 340,
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
      });
    });
  });
}

export interface RasterProps {
  index: number;
  b: Bildschirm;
  /** Wie der Bildschirm heißt (eigener Name oder nach seinen Fenstern, lib/os/bildschirme.ts `anzeigeName`) */
  name: string;
  flaeche: (id: string) => Flaeche | undefined;
  aktiv: string | null;
  setAktiv: (id: string) => void;
  setze: (l: Fenster[]) => void;
  ziehen: boolean;
  setZiehen: (z: boolean) => void;
  schmal: boolean;
  bildschirme: { index: number; name: string }[];
  onAufBildschirm: (fensterId: string, index: number) => void;
  onNeuerBildschirmMit: (fensterId: string) => void;
  onOeffnen: (id: string, vor: string | null) => void;
  /** Ein Fenster von einem anderen Bildschirm hierher gezogen */
  onHerholen?: (id: string, vor: string | null) => void;
  /** Ein Ding (Notiz, Termin …) hierher gezogen */
  onDing?: (g: Extract<Gut, { art: 'ding' }>, vor: string | null) => void;
  oeffne: (id: string) => void;
  onUmbenennen: (name: string) => void;
  /** Von außen (Menü, Dock) angestoßen: Namensfeld öffnen */
  umbenennen?: boolean;
  onUmbenennenFertig?: () => void;
  /** Gibt der Shell das Fenstermenü (Menüleiste „Fenster“, Rechtsklick im Dock) */
  onPunkte?: (bau: (id: string) => MenuePunkt[]) => void;
  /** Gibt der Shell „Neu verteilen“ (mit Übergang) */
  onVerteilen?: (fn: () => void) => void;
  /** Pfeil oben: zurück zum Startbildschirm */
  onStart?: () => void;
}

const BREITEN: [string, number][] = [
  ['Ein Viertel', 3], ['Ein Drittel', 4], ['Halbe Breite', 6], ['Zwei Drittel', 8], ['Drei Viertel', 9], ['Volle Breite', SPALTEN],
];
const HOEHEN: [string, number][] = [['Klein', 7], ['Mittel', 10], ['Groß', 14], ['Hoch', 20]];

export default function Raster(p: RasterProps): JSX.Element {
  let behaelter: HTMLDivElement | undefined;
  /** Zeilen, die genau in den sichtbaren Bereich der Fläche passen (Zeile 2,5 rem + Abstand 0,75 rem, Rand 0,75/1,25 rem). */
  const bildschirmZeilen = (): number => {
    const sc = behaelter?.closest<HTMLElement>('.os-bildschirm');
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const h = (sc?.clientHeight || window.innerHeight) / rem;
    return Math.min(ZEILEN_MAX, Math.max(ZEILEN_MIN, Math.floor((h - 1.25) / (ZEILE_REM + 0.75))));
  };
  const [umbenennenLokal, setUmbenennen] = createSignal(false);
  const umbenennen = () => umbenennenLokal() || !!p.umbenennen;
  /** Esc beim Umbenennen gedrückt: der alte Name bleibt */
  let verworfen = false;
  const umbenennenEnde = () => {
    setUmbenennen(false);
    p.onUmbenennenFertig?.();
  };

  const sichtbar = createMemo(() => p.b.fenster.filter((w) => !w.min));
  const hand = createMemo(() => vonHand(p.b.fenster));
  const auto = createMemo(() => autoSpalten(sichtbar().length));

  /** Auf dem Handy genau ein Fenster: das aktive, sonst das letzte. */
  const gezeigt = createMemo(() => {
    if (!p.schmal) return sichtbar();
    const a = sichtbar().find((w) => w.id === p.aktiv) ?? sichtbar()[sichtbar().length - 1];
    return a ? [a] : [];
  });

  /**
   * Reihenfolge im Dokument bleibt fest (alphabetisch nach ID), die sichtbare Anordnung macht
   * CSS `order`: Ein iframe, das im Dokument verschoben wird, lädt neu — Umordnen soll das nie.
   */
  const reihe = createMemo(() => gezeigt().map((w) => w.id).sort());
  const platz = createMemo(() => new Map(gezeigt().map((w, i) => [w.id, i])));
  const fenster = (id: string) => p.b.fenster.find((w) => w.id === id);

  const mass = (): RasterMass | null => {
    if (!behaelter) return null;
    const st = getComputedStyle(behaelter);
    const luecke = parseFloat(st.columnGap) || 12;
    const innen = behaelter.clientWidth - (parseFloat(st.paddingLeft) || 0) - (parseFloat(st.paddingRight) || 0);
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    return { spalte: (innen - luecke * (SPALTEN - 1)) / SPALTEN, zeile: ZEILE_REM * rem, luecke };
  };

  /** Aktuelle Größe jedes sichtbaren Fensters in Rastereinheiten (für das Einfrieren der Automatik). */
  const automatikJetzt = (): Map<string, { spalten: number; zeilen: number }> => {
    const m = mass();
    const out = new Map<string, { spalten: number; zeilen: number }>();
    if (!m || !behaelter) return out;
    behaelter.querySelectorAll<HTMLElement>(':scope > [data-fenster]').forEach((el) => {
      const h = el.getBoundingClientRect().height;
      out.set(el.dataset.fenster!, { spalten: auto(), zeilen: Math.round((h + m.luecke) / (m.zeile + m.luecke)) });
    });
    return out;
  };

  const aendern = (neu: Fenster[]) => mitUebergang(behaelter, () => p.setze(neu));

  const lage = (w: Fenster): JSX.CSSProperties => {
    const order = platz().get(w.id) ?? 0;
    if (p.schmal) return { order };
    if (!hand()) return { order, 'grid-column': `span ${auto()}` };
    const s = w.spalten ?? NEU_SPALTEN;
    return {
      order,
      'grid-column': `${w.neueZeile ? '1 / ' : ''}span ${s}`,
      'grid-row': `span ${w.zeilen ?? NEU_ZEILEN}`,
    };
  };
  const groesseVon = (w: Fenster) => ({
    spalten: hand() ? (w.spalten ?? NEU_SPALTEN) : auto(),
    zeilen: hand() ? (w.zeilen ?? NEU_ZEILEN) : 0,
  });

  /**
   * Abgelegt auf dem Schreibtisch (vor = null) oder einem Fenster (vor = dessen ID), lib/os/ziehen.ts:
   * Fenster dieses Bildschirms ordnen sich ein, Fenster von anderswo ziehen her; Flächen öffnen hier; Dinge
   * (Notiz, Termin …) öffnen ihre Fläche — die Shell weiß, welche.
   */
  const ablegen = (g: Gut | null, vor: string | null) => {
    if (!g) return;
    if (g.art === 'fenster') {
      if (p.b.fenster.some((w) => w.id === g.id)) aendern(davorSetzen(p.b.fenster, g.id, vor));
      else p.onHerholen?.(g.id, vor);
    } else if (g.art === 'flaeche') {
      p.onOeffnen(g.id, vor);
    } else {
      p.onDing?.(g, vor);
    }
  };
  /** Schreibtisch als Ziel: alles vom OS annehmen; über der Leerfläche und „Platz für mehr" mit Hinweis. */
  const annehmen = (e: DragEvent) => {
    const art = gutArt(e.dataTransfer);
    if (!art) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = art === 'fenster' ? 'move' : 'copy';
    const el = e.currentTarget as HTMLElement;
    if (el !== behaelter) hinweisZeigen(el, wasPassiert(art, 'schreibtisch'));
  };
  const ablage = (e: DragEvent) => {
    const g = gutLesen(e.dataTransfer);
    hinweisWeg();
    if (!g) return;
    e.preventDefault();
    e.stopPropagation();
    zugEndet();
    ablegen(g, null);
  };

  /** Das Menü eines Fensters: ⋯, Rechtsklick auf den Kopf (und die Menüleiste über die Shell). */
  const punkte = (id: string): MenuePunkt[] => {
    const w = fenster(id);
    const f = p.flaeche(id);
    if (!w || !f) return [];
    const g = groesseVon(w);
    const groesse = (x: { spalten?: number; zeilen?: number; fest?: boolean }) => p.setze(groesseSetzen(p.b.fenster, id, x, hand() ? undefined : automatikJetzt()));
    const wachsend = f.art === 'hubapp' || f.art === 'nativ';
    const pos = platz().get(id) ?? 0;
    const andere = sichtbar().filter((x) => x.id !== id);
    const app = f.art === 'hubapp';
    return [
      // Apps: dieselben Aktionen wie im Fensterkopf, zuerst (Agent fragen, Link kopieren, An den Start heften)
      ...(app ? [...aktionsPunkte(f, w.start), { art: 'trenner' as const }] : []),
      { text: 'Minimieren', symbol: 'minus', tun: () => insDock(id, () => aendern(minimieren(p.b.fenster, id))) },
      {
        text: g.spalten >= SPALTEN ? 'Halbe Breite' : 'Volle Breite',
        symbol: g.spalten >= SPALTEN ? 'minimize-2' : 'maximize-2',
        aus: p.schmal,
        tun: () => groesse({ spalten: g.spalten >= SPALTEN ? 6 : SPALTEN }),
      },
      { art: 'trenner' },
      { art: 'unter', text: 'Breite', symbol: 'move-horizontal', aus: p.schmal, punkte: BREITEN.map(([text, sp]) => ({ text, an: g.spalten === sp, tun: () => groesse({ spalten: sp }) })) },
      {
        art: 'unter',
        text: 'Höhe',
        symbol: 'move-vertical',
        aus: p.schmal,
        // Apps und native Flächen wachsen mit ihrem Inhalt; eine gewählte Höhe hält das Fenster fest (Inhalt scrollt
        // darin), „Mit Inhalt wachsen“ lässt es wieder los. Seiten haben immer ihre gewählte Höhe.
        // „Bildschirmhoch“: genau der sichtbare Bereich der Fläche — für Seiten mit eigenen Spalten,
        // die nicht wachsen können: ganz im Blick scrollt dann nur noch die Seite selbst.
        punkte: [
          ...(wachsend ? [{ text: 'Mit Inhalt wachsen', an: !w.fest, tun: () => aendern(festSetzen(p.b.fenster, id, false)) }, { art: 'trenner' as const }] : []),
          ...[...HOEHEN, ['Bildschirmhoch', bildschirmZeilen()] as [string, number]].map(([text, z]) => ({
            text,
            an: (!wachsend || !!w.fest) && g.zeilen === z,
            tun: () => groesse(wachsend ? { zeilen: z, fest: true } : { zeilen: z }),
          })),
        ],
      },
      { text: 'In neuer Zeile beginnen', symbol: 'corner-down-left', an: !!w.neueZeile, aus: p.schmal, tun: () => aendern(neueZeileUmschalten(hand() ? p.b.fenster : groesseSetzen(p.b.fenster, id, {}, automatikJetzt()), id)) },
      { text: 'Nach links rücken', symbol: 'arrow-left', kuerzel: altUmschalt('←'), aus: pos === 0, tun: () => aendern(verschieben(p.b.fenster, id, -1)) },
      { text: 'Nach rechts rücken', symbol: 'arrow-right', kuerzel: altUmschalt('→'), aus: pos >= sichtbar().length - 1, tun: () => aendern(verschieben(p.b.fenster, id, 1)) },
      { art: 'trenner' },
      {
        art: 'unter',
        text: 'Auf Bildschirm',
        symbol: 'monitor-up',
        punkte: [
          ...p.bildschirme.filter((b) => b.index !== p.index).map((b) => ({ text: b.name, tun: () => p.onAufBildschirm(id, b.index) })),
          { art: 'trenner' as const },
          { text: 'Neuer Bildschirm', symbol: 'plus', tun: () => p.onNeuerBildschirmMit(id) },
        ],
      },
      { art: 'trenner' },
      { text: 'Neu laden', symbol: 'rotate-cw', tun: () => window.dispatchEvent(new CustomEvent(NEU_LADEN, { detail: id })) },
      { text: 'In neuem Tab öffnen', symbol: 'external-link', tun: () => inNeuemTab(f, w.start) },
      // Bei Apps steht „Link kopieren" (mit der aktuellen Eingabe) schon oben
      ...(app ? [] : [{ text: 'Link kopieren', symbol: 'link', tun: () => void navigator.clipboard?.writeText(deeplink(id)).catch(() => {}) }]),
      { art: 'trenner' },
      { text: 'Andere schließen', symbol: 'copy-x', aus: andere.length === 0, tun: () => aendern(p.b.fenster.filter((x) => x.id === id || x.min)) },
      { text: 'Schließen', symbol: 'x', tun: () => ausklingen(id, () => aendern(schliessen(p.b.fenster, id))) },
    ];
  };

  p.onPunkte?.(punkte);
  p.onVerteilen?.(() => aendern(automatisch(p.b.fenster)));

  /**
   * Eine Scrollebene: Zeilen sind nach oben offen (`auto`), Fenster wachsen mit ihrer App und nur die
   * Fläche scrollt. Die gewählte Höhe (Zeilen von Hand, 22rem in der Automatik) ist die Mindesthöhe. Von Hand
   * dehnen sich die Zeilen nicht über den Bildschirm (`align-content: start`); in der Automatik und auf dem Handy
   * füllen kurze Fenster weiter die Fläche (`auto`-Zeilen dehnen sich bis zur Mindesthöhe des Rasters).
   */
  const rasterStil = (): JSX.CSSProperties => {
    if (p.schmal) return { 'grid-template-rows': 'auto' };
    if (hand()) return { 'grid-auto-rows': `minmax(${ZEILE_REM}rem, auto)`, 'align-content': 'start' };
    return { 'grid-template-rows': `repeat(${autoReihen(sichtbar().length)}, minmax(22rem, auto))` };
  };

  // Pfeil zum Startbildschirm: blendet sich ein, wenn der Zeiger an den oberen Rand kommt
  const [nahOben, setNahOben] = createSignal(false);
  const zeigerNah = (e: PointerEvent) => {
    if (e.pointerType === 'touch') return;
    const oben = (e.currentTarget as HTMLElement).parentElement?.getBoundingClientRect().top ?? 0;
    setNahOben(e.clientY - oben < 64);
  };

  return (
    <div
      class="os-schreibtisch flex min-h-full flex-col"
      data-kontext="schreibtisch"
      onPointerMove={zeigerNah}
      onPointerLeave={() => setNahOben(false)}
    >
      <Show when={p.onStart && !p.schmal}>
        <button
          type="button"
          class="os-hoch"
          classList={{ 'os-hoch-da': nahOben() }}
          aria-label="Zum Startbildschirm"
          title="Zum Startbildschirm (⌥⌘1)"
          onClick={() => p.onStart?.()}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6" /></svg>
          <span>Start</span>
        </button>
      </Show>
      {/* Kopf des Bildschirms: Name links, Lage rechts — eine ruhige Zeile */}
      <div class="flex min-h-10 shrink-0 items-center gap-3 px-5 pt-3 text-sm max-md:px-3">
        <Show
          when={umbenennen()}
          fallback={
            <button
              type="button"
              data-kontext={`bildschirm:${p.index}`}
              class="os-bildschirmname"
              title={automatischBenannt(p.b.name) ? 'Heißt nach seinen Fenstern. Klicken, um einen eigenen Namen zu geben' : 'Umbenennen'}
              onClick={() => setUmbenennen(true)}
            >
              {p.name}
            </button>
          }
        >
          <form onSubmit={(e) => { e.preventDefault(); umbenennenEnde(); }}>
            <input
              value={automatischBenannt(p.b.name) ? '' : p.b.name}
              placeholder={p.name}
              title="Leer lassen: der Bildschirm heißt nach seinen Fenstern"
              maxLength={30}
              aria-label="Name des Bildschirms"
              class="os-titel w-48 rounded-md border border-(--os-glas-rand) bg-transparent px-2 py-1 outline-none focus:border-(--os-neon-1)"
              ref={(el) => { verworfen = false; queueMicrotask(() => el.select()); }}
              // Esc verwirft: das Blur, das beim Ausblenden folgt, darf den Text nicht mehr übernehmen
              onBlur={(e) => { if (!verworfen) p.onUmbenennen(e.currentTarget.value); umbenennenEnde(); }}
              onKeyDown={(e) => {
                if (e.key === 'Escape') { e.stopPropagation(); verworfen = true; umbenennenEnde(); }
                if (e.key === 'Enter') p.onUmbenennen(e.currentTarget.value);
              }}
            />
          </form>
        </Show>
        <Show when={!p.schmal && hand() && sichtbar().length > 1}>
          <button type="button" class="os-knopf px-2 text-xs" title="Alle Fenster wieder gleichmäßig verteilen" onClick={() => aendern(automatisch(p.b.fenster))}>
            Gleichmäßig verteilen
          </button>
        </Show>
      </div>

      <Show
        when={gezeigt().length}
        fallback={
          <div
            class="m-3 flex flex-1 flex-col items-center justify-center gap-3 rounded-[var(--os-radius)] border border-dashed border-(--os-glas-rand) text-center text-(--color-fg-muted)"
            onDragOver={annehmen}
            onDragLeave={(e) => hinweisWeg(e.currentTarget)}
            onDrop={ablage}
          >
            <p class="m-0 text-base text-(--color-fg)">Dieser Bildschirm ist leer.</p>
            <p class="m-0 text-sm">Öffne eine Fläche über <b>{systemName()}</b> oder ziehe eine Fläche, ein Fenster oder ein Objekt hierher.</p>
          </div>
        }
      >
        <div
          ref={behaelter}
          class="os-raster-flaeche grid gap-3 p-3 max-md:grid-cols-1 md:grid-cols-12 md:px-5 md:pb-5"
          style={rasterStil()}
          onDragOver={annehmen}
          onDrop={ablage}
        >
          <For each={reihe()}>
            {(id) => {
              const f = () => p.flaeche(id);
              const w = () => fenster(id);
              return (
                <Show when={f() && w()}>
                  {(_) => (
                    <FensterRahmen
                      f={f()!}
                      w={w()!}
                      lage={lage(w()!)}
                      spalten={groesseVon(w()!).spalten}
                      zeilen={groesseVon(w()!).zeilen}
                      fokus={p.aktiv === id}
                      ziehen={p.ziehen}
                      schmal={p.schmal}
                      mass={mass}
                      punkte={() => punkte(id)}
                      onFokus={() => p.setAktiv(id)}
                      onSchliessen={() => ausklingen(id, () => aendern(schliessen(p.b.fenster, id)))}
                      onMinimieren={() => insDock(id, () => aendern(minimieren(p.b.fenster, id)))}
                      onGroesse={(g) => p.setze(groesseSetzen(p.b.fenster, id, g, hand() ? undefined : automatikJetzt()))}
                      onZiehStart={() => p.setZiehen(true)}
                      onZiehEnde={() => p.setZiehen(false)}
                      onAblegen={(g) => ablegen(g, id)}
                      onVerschieben={(r) => aendern(verschieben(p.b.fenster, id, r))}
                      oeffne={p.oeffne}
                    />
                  )}
                </Show>
              );
            }}
          </For>
        </div>
        {/* Endlos: unter dem letzten Fenster ist immer Platz — hierher ziehen legt ans Ende */}
        <Show when={!p.schmal}>
          <div
            class="os-weiter"
            aria-hidden="true"
            onDragOver={annehmen}
            onDragLeave={(e) => hinweisWeg(e.currentTarget)}
            onDrop={ablage}
          >
            <span>Platz für mehr — Fläche, Fenster oder Objekt hierher ziehen</span>
          </div>
        </Show>
      </Show>
    </div>
  );
}
