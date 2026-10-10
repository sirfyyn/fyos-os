/**
 * Menue — das eine Menü des FYOS-OS, gezeichnet wie unter macOS: Glas mit echter
 * Unschärfe, kompakte Zeilen, Häkchen links, Kürzel rechts, Trenner, Untermenüs nach rechts.
 *
 * Bedienung: Maus (Darüberfahren wählt, Untermenü öffnet beim Darüberfahren), Tastatur (↑/↓,
 * → öffnet, ← schließt das Untermenü, Eingabe/Leertaste führt aus, Esc schließt, Anfangsbuchstabe
 * springt), Touch. Schließt bei Klick daneben, Fensterwechsel, Größenänderung und Scrollen.
 * Inhalt kommt aus lib/os/menue.ts (`menueOeffnen`).
 */
import { For, Show, createEffect, createSignal, onCleanup, type JSX } from 'solid-js';
import { Portal } from 'solid-js/web';
import { lage, menue, menueZu, naechster, waehlbar, type MenuePunkt } from '~/lib/os/menue';
import { Glyphe } from './Symbol';

function Liste(p: {
  punkte: MenuePunkt[];
  x: number;
  y: number;
  tastatur: boolean;
  tiefe: number;
  /** Untermenü: linke Kante des Elternpunkts — passt es rechts nicht, klappt es links davon auf */
  xLinks?: number;
  /** Untermenü: ← schließt es und gibt die Tastatur an die Eltern zurück */
  onZurueck?: () => void;
}): JSX.Element {
  let el: HTMLDivElement | undefined;
  const [wahl, setWahl] = createSignal(p.tastatur ? naechster(p.punkte, -1, 1) : -1);
  const [unter, setUnter] = createSignal<{ i: number; x: number; xl: number; y: number; tastatur: boolean } | null>(null);
  const [pos, setPos] = createSignal({ x: p.x, y: p.y });
  let unterZeit: ReturnType<typeof setTimeout> | undefined;

  createEffect(() => {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const passt = p.x + r.width <= window.innerWidth - 8;
    const x = !passt && p.xLinks != null ? Math.max(8, p.xLinks - r.width) : p.x;
    setPos(lage(x, p.y, r.width, r.height, window.innerWidth, window.innerHeight));
    queueMicrotask(() => el?.focus({ preventScroll: true }));
  });
  onCleanup(() => clearTimeout(unterZeit));

  const ausfuehren = (pt: MenuePunkt) => {
    if (pt.art === undefined || pt.art === 'punkt') {
      if (pt.aus) return;
      menueZu();
      // Nach dem Schließen: Fokus/Zeiger landen nicht im halb abgebauten Menü.
      queueMicrotask(pt.tun);
    }
  };
  const unterOeffnen = (i: number, zeile: HTMLElement | undefined, tastatur: boolean) => {
    const pt = p.punkte[i];
    if (!pt || pt.art !== 'unter' || pt.aus || !zeile) {
      setUnter(null);
      return;
    }
    const r = zeile.getBoundingClientRect();
    setUnter({ i, x: r.right - 4, xl: r.left + 4, y: r.top - 5, tastatur });
  };
  const zeileVon = (i: number) => el?.querySelector<HTMLElement>(`[data-i="${i}"]`) ?? undefined;

  const taste = (e: KeyboardEvent) => {
    if (unter()?.tastatur) return; // das Untermenü hat die Tastatur
    const n = p.punkte;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      setWahl(naechster(n, wahl() < 0 && e.key === 'ArrowUp' ? 0 : wahl(), e.key === 'ArrowDown' ? 1 : -1));
      setUnter(null);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      if (n[wahl()]?.art === 'unter') unterOeffnen(wahl(), zeileVon(wahl()), true);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      p.onZurueck?.();
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      const pt = n[wahl()];
      if (!pt) return;
      if (pt.art === 'unter') unterOeffnen(wahl(), zeileVon(wahl()), true);
      else ausfuehren(pt);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      if (p.onZurueck) p.onZurueck();
      else menueZu();
    } else if (e.key === 'Tab') {
      e.preventDefault();
    } else if (e.key.length === 1 && /\p{L}/u.test(e.key)) {
      const k = e.key.toLowerCase();
      const start = wahl();
      for (let j = 1; j <= n.length; j++) {
        const i = (start + j) % n.length;
        const pt = n[i]!;
        if (waehlbar(pt) && 'text' in pt && pt.text.toLowerCase().startsWith(k)) {
          setWahl(i);
          break;
        }
      }
    }
  };

  return (
    <>
      <div
        ref={el}
        role="menu"
        tabindex="-1"
        data-os-menue
        class="os-menue-liste"
        style={{ left: `${pos().x}px`, top: `${pos().y}px`, 'z-index': 100 + p.tiefe }}
        onKeyDown={taste}
        onContextMenu={(e) => e.preventDefault()}
      >
        <For each={p.punkte}>
          {(pt, i) => {
            if (pt.art === 'trenner') return <div role="separator" class="os-menue-trenner" />;
            if (pt.art === 'titel') return <div class="os-menue-titel">{pt.text}</div>;
            const istUnter = pt.art === 'unter';
            return (
              <div
                role={pt.art !== 'unter' && pt.an !== undefined ? 'menuitemcheckbox' : 'menuitem'}
                aria-checked={pt.art !== 'unter' && pt.an !== undefined ? pt.an : undefined}
                aria-disabled={pt.aus || undefined}
                aria-haspopup={istUnter ? 'menu' : undefined}
                aria-expanded={istUnter ? unter()?.i === i() : undefined}
                data-i={i()}
                class="os-menue-zeile"
                classList={{
                  'os-menue-gewaehlt': wahl() === i() || unter()?.i === i(),
                  'os-menue-aus': !!pt.aus,
                  'os-menue-gefahr': pt.art !== 'unter' && !!pt.gefahr,
                }}
                onPointerEnter={(e) => {
                  if (pt.aus) {
                    setWahl(-1);
                    return;
                  }
                  setWahl(i());
                  const zeile = e.currentTarget;
                  clearTimeout(unterZeit);
                  unterZeit = setTimeout(() => unterOeffnen(i(), zeile, false), istUnter ? 60 : 160);
                }}
                onPointerLeave={() => {
                  if (!unter()) setWahl(-1);
                }}
                onClick={(e) => {
                  if (istUnter) unterOeffnen(i(), e.currentTarget, false);
                  else ausfuehren(pt);
                }}
              >
                <span class="os-menue-haken" aria-hidden="true">
                  <Show when={pt.art !== 'unter' && pt.an} fallback={<Show when={pt.symbol}>{(s) => <Glyphe name={s()} class="os-menue-glyphe" />}</Show>}>
                    ✓
                  </Show>
                </span>
                <span class="min-w-0 flex-1 truncate">{pt.text}</span>
                <Show when={pt.art !== 'unter' && pt.kuerzel}>
                  <span class="os-menue-kuerzel">{(pt as { kuerzel: string }).kuerzel}</span>
                </Show>
                <Show when={istUnter}>
                  <svg class="os-menue-pfeil" width="8" height="10" viewBox="0 0 8 10" aria-hidden="true"><path d="M2 1l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>
                </Show>
              </div>
            );
          }}
        </For>
      </div>
      <Show when={unter()} keyed>
        {(u) => (
          <Liste
            punkte={(p.punkte[u.i] as { punkte: MenuePunkt[] }).punkte}
            x={u.x}
            xLinks={u.xl}
            y={u.y}
            tastatur={u.tastatur}
            tiefe={p.tiefe + 1}
            onZurueck={() => {
              setUnter(null);
              el?.focus({ preventScroll: true });
            }}
          />
        )}
      </Show>
    </>
  );
}

export default function Menue(): JSX.Element {
  createEffect(() => {
    if (!menue()) return;
    const daneben = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t?.closest?.('[data-os-menue]')) return;
      // Ein Klick auf denselben Eintrag der Menüleiste schließt (die Leiste macht das selbst).
      if (t?.closest?.('[data-menueleiste-punkt]')) return;
      menueZu();
    };
    const weg = () => menueZu();
    window.addEventListener('pointerdown', daneben, true);
    window.addEventListener('blur', weg);
    window.addEventListener('resize', weg);
    onCleanup(() => {
      window.removeEventListener('pointerdown', daneben, true);
      window.removeEventListener('blur', weg);
      window.removeEventListener('resize', weg);
    });
  });
  return (
    <Show when={menue()} keyed>
      {(m) => (
        <Portal>
          <Liste punkte={m.punkte} x={m.x} y={m.y} tastatur={!!m.tastatur} tiefe={0} />
        </Portal>
      )}
    </Show>
  );
}
