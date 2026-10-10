/**
 * Menueleiste — die Leiste oben im OS, wie unter macOS: links das Systemmenü,
 * der Name dessen, was gerade vorne ist, und die Menüs (Ablage, Darstellung, Fenster, Hilfe);
 * rechts Statussymbole, das Kontrollzentrum und Datum mit Uhr.
 *
 * Ist ein Menü offen, wechselt Darüberfahren zum Nachbarn (wie am Mac). Die Menüs selbst zeichnet
 * components/os/Menue.tsx; die Einträge baut die Shell, weil nur sie den Zustand kennt.
 */
import { For, Show, type JSX } from 'solid-js';
import { menue, menueOeffnen, menueZu, type MenuePunkt } from '~/lib/os/menue';

export interface LeistenMenue {
  id: string;
  text: string;
  punkte: () => MenuePunkt[];
}

export interface MenueleisteProps {
  menues: LeistenMenue[];
  /** Fett neben dem Systemmenü: das Fenster im Fokus oder der Bildschirm */
  vorne: string;
  rechts: JSX.Element;
}

export default function Menueleiste(p: MenueleisteProps): JSX.Element {
  const auf = (m: LeistenMenue, el: HTMLElement, tastatur = false) => {
    const r = el.getBoundingClientRect();
    menueOeffnen({ x: r.left, y: r.bottom + 4, punkte: m.punkte(), quelle: m.id, tastatur });
  };
  const offen = () => menue()?.quelle;
  // Mit offenem Menü auf einen anderen Titel klicken schloss ihn früher gleich wieder — das Darüberfahren
  // hatte ihn schon geöffnet, der Klick galt dann als „zu". Am Mac bleibt er offen. Darum: ein Menü, das gerade
  // durchs Darüberfahren aufging, schließt erst ein zweiter Klick.
  let perHover: string | null = null;

  return (
    <header class="os-leiste" aria-label="Menüleiste">
      {/* Links gibt nach (der Name kürzt sich, Menüs werden abgeschnitten), rechts behält seine Breite:
          sonst liefen die Statussymbole bei schmalen Fenstern über die Menütitel (390 px). */}
      <nav class="flex min-w-0 flex-1 items-center overflow-hidden" aria-label="Menüs">
        <For each={p.menues}>
          {(m, i) => (
            <button
              type="button"
              data-menueleiste-punkt
              aria-haspopup="menu"
              aria-expanded={offen() === m.id}
              class="os-leiste-punkt"
              classList={{ 'os-leiste-logo': i() === 0, 'os-leiste-an': offen() === m.id, 'max-md:hidden': i() > 1, 'max-sm:hidden': i() === 1 }}
              onPointerDown={(e) => {
                if (e.button > 0) return;
                e.preventDefault();
                if (offen() === m.id && perHover === m.id) perHover = null;
                else if (offen() === m.id) menueZu();
                else auf(m, e.currentTarget);
              }}
              onPointerEnter={(e) => {
                if (offen() && offen() !== m.id) {
                  auf(m, e.currentTarget);
                  perHover = m.id;
                }
              }}
              onPointerLeave={() => { perHover = null; }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
                  e.preventDefault();
                  auf(m, e.currentTarget, true);
                }
              }}
            >
              <Show when={i() === 0} fallback={m.text}>
                <span class="os-logo" aria-hidden="true" />
                <span class="sr-only">{m.text}</span>
              </Show>
            </button>
          )}
        </For>
        <span class="os-leiste-vorne" aria-live="polite">{p.vorne}</span>
      </nav>
      <div class="flex shrink-0 items-center justify-end gap-0.5">{p.rechts}</div>
    </header>
  );
}
