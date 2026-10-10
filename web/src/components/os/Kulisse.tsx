/**
 * Kulisse — der Hintergrund des OS: unscharfe Lavalampe mit leisen
 * Cyberpunk-Elementen (Neon-Raster, Horizont, Scanlines). Reine CSS-Ebenen (styles/os.css);
 * hier werden nur die Einstellungen angewendet und auf Änderungen gehört.
 */
import { onCleanup, onMount, type JSX } from 'solid-js';
import { KULISSE_EREIGNIS, kulisseAnwenden, kulisseLaden, kulisseVon } from '~/lib/os/kulisse';

/** `ruhe`: alles anhalten (Kulisse verdeckt, niemand am Rechner, Tab im Hintergrund). */
export default function Kulisse(p: { ruhe?: boolean } = {}): JSX.Element {
  onMount(() => {
    kulisseAnwenden(kulisseLaden());
    // Andere Tabs (Einstellungen dort geändert) ziehen über `storage` nach, dieser über das Ereignis.
    const neu = (e: Event) => kulisseAnwenden(kulisseVon(e));
    window.addEventListener(KULISSE_EREIGNIS, neu);
    window.addEventListener('storage', neu);
    onCleanup(() => {
      window.removeEventListener(KULISSE_EREIGNIS, neu);
      window.removeEventListener('storage', neu);
    });
  });
  return (
    <div class="os-kulisse" aria-hidden="true" data-kulisse data-ruhe={p.ruhe ? '' : undefined}>
      <div class="os-blob b1" />
      <div class="os-blob b2" />
      <div class="os-blob b3" />
      <div class="os-blob b4" />
      <div class="os-raster" />
      <div class="os-horizont" />
      <div class="os-scan" />
      <div class="os-vignette" />
    </div>
  );
}
