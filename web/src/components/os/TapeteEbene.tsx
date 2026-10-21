/**
 * TapeteEbene — liegt in jedem Bildschirm-Platz unter dem Inhalt und verdeckt dort die Kulisse. Ein eigenes Bild aus der Dateiablage wird einmal über `dateien.vorschau` geholt und als Blob-URL
 * gehalten (nie im Zustand gespeichert). Den Dialog dazu lädt die Shell auf Abruf (Tapete.tsx).
 */
import { Show, createResource, type JSX } from 'solid-js';
import { hub } from '~/lib/hub';
import { tapeteHintergrund, type Tapete } from '~/lib/os/tapete';

// ── Bild aus der Dateiablage: einmal laden, als Blob-URL behalten ─────────────────────────────────
const geladen = new Map<string, Promise<string>>();
function ablageBild(pfad: string): Promise<string> {
  let p = geladen.get(pfad);
  if (!p) {
    p = hub<{ typ?: string; daten_base64?: string; error?: string }>('dateien.vorschau', { pfad }, { zeitMs: 30_000 }).then((r) => {
      if (!r?.daten_base64) throw new Error(r?.error ?? 'Bild nicht lesbar');
      const roh = atob(r.daten_base64);
      const bytes = new Uint8Array(roh.length);
      for (let i = 0; i < roh.length; i++) bytes[i] = roh.charCodeAt(i);
      return URL.createObjectURL(new Blob([bytes], { type: r.typ || 'image/jpeg' }));
    });
    p.catch(() => geladen.delete(pfad)); // ein Fehler bleibt nicht hängen: beim nächsten Mal neu versuchen
    geladen.set(pfad, p);
  }
  return p;
}

/** Die Ebene unter dem Inhalt eines Bildschirms. Ohne Tapete: nichts (die Kulisse scheint durch). */
export default function TapeteEbene(p: { tapete?: Tapete }): JSX.Element {
  const [bild] = createResource(
    () => (p.tapete && p.tapete.art !== 'auswahl' ? p.tapete : undefined),
    (t) => (t.art === 'datei' ? ablageBild(t.wert) : Promise.resolve(t.wert)),
  );
  const hintergrund = () => (p.tapete ? tapeteHintergrund(p.tapete, bild.error ? undefined : bild()) : undefined);
  return (
    <Show when={p.tapete && hintergrund()}>
      <div class="os-tapete" aria-hidden="true">
        <div
          class="os-tapete-bild"
          style={{
            background: hintergrund(),
            filter: p.tapete!.weich ? `blur(${p.tapete!.weich}px)` : undefined,
            inset: p.tapete!.weich ? `${-2 * p.tapete!.weich}px` : undefined,
          }}
        />
        <div class="os-tapete-dunkel" style={{ opacity: String(p.tapete!.dunkel / 100) }} />
      </div>
    </Show>
  );
}
