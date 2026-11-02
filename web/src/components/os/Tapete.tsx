/**
 * Tapete — eigener Hintergrund je Bildschirm.
 *
 * Die Ebene im Bildschirm zeichnet TapeteEbene.tsx (im ersten Bündel); dieser Dialog lädt erst auf Abruf.
 * `TapeteDialog` wählt die Tapete: Kulisse, eingebaute Verläufe, eigenes Bild (wird verkleinert und in die Ablage
 * gelegt) oder eine Adresse, dazu Abdunkeln und Weichzeichnen. Jede Änderung gilt sofort (Vorschau am Bildschirm selbst).
 */
import { For, Show, createEffect, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { ApiError } from '~/lib/api/client';
import { hub } from '~/lib/hub';
import {
  DUNKEL_MAX, DUNKEL_STANDARD, HOCHLADEN_KANTE, TAPETEN, WEICH_MAX, WEICH_STANDARD,
  tapetenPfad, urlGueltig, type Tapete,
} from '~/lib/os/tapete';
import { tr } from '~/lib/i18n';

// ── Eigenes Bild verkleinern (JPEG) — unter der 1-MB-Grenze von /hub-api/app-call ─────────────────
const GRENZE_BASE64 = 900_000;
async function verkleinern(datei: File): Promise<string> {
  const bmp = await createImageBitmap(datei);
  try {
    for (const [kante, guete] of [[HOCHLADEN_KANTE, 0.85], [1920, 0.82], [1600, 0.78], [1280, 0.72]] as const) {
      const f = Math.min(1, kante / Math.max(bmp.width, bmp.height));
      const c = document.createElement('canvas');
      c.width = Math.round(bmp.width * f);
      c.height = Math.round(bmp.height * f);
      c.getContext('2d')!.drawImage(bmp, 0, 0, c.width, c.height);
      const b64 = c.toDataURL('image/jpeg', guete).split(',', 2)[1] ?? '';
      if (b64.length <= GRENZE_BASE64) return b64;
    }
  } finally {
    bmp.close();
  }
  throw new Error(tr('Das Bild ist auch verkleinert zu groß.'));
}

export interface TapeteZiel {
  index: number;
  name: string;
}

export default function TapeteDialog(p: {
  ziele: TapeteZiel[];
  start: number;
  /** Bildschirm-Kennung für den Dateinamen in der Ablage */
  kennung: (index: number) => string;
  tapete: (index: number) => Tapete | undefined;
  setzen: (index: number, t: Tapete | undefined) => void;
  onSchliessen: () => void;
}): JSX.Element {
  let el: HTMLDivElement | undefined;
  let dateiFeld: HTMLInputElement | undefined;
  const [ziel, setZiel] = createSignal(p.start);
  const [adresse, setAdresse] = createSignal('');
  const [meldung, setMeldung] = createSignal('');
  const [laedt, setLaedt] = createSignal(false);
  const jetzt = () => p.tapete(ziel());
  createEffect(() => setAdresse(jetzt()?.art === 'url' ? jetzt()!.wert : ''));

  const regler = () => ({ dunkel: jetzt()?.dunkel ?? DUNKEL_STANDARD, weich: jetzt()?.weich ?? WEICH_STANDARD });
  const setze = (t: Tapete | undefined) => {
    setMeldung('');
    p.setzen(ziel(), t);
  };
  const waehle = (art: Tapete['art'], wert: string) => setze({ art, wert, ...regler() });

  const hochladen = async (datei: File | undefined) => {
    if (!datei) return;
    if (!datei.type.startsWith('image/')) {
      setMeldung(tr('Das ist kein Bild.'));
      return;
    }
    setLaedt(true);
    setMeldung(tr('Bild wird verkleinert und abgelegt …'));
    try {
      const b64 = await verkleinern(datei);
      const pfad = tapetenPfad(p.kennung(ziel()));
      const r = await hub<{ ok?: boolean; error?: string }>('dateien.schreiben', { pfad, inhalt_base64: b64, bestaetigt: true }, { art: 'bewusst', zeitMs: 60_000 });
      if (r && r.ok === false) throw new Error(r.error ?? tr('Ablegen fehlgeschlagen'));
      setze({ art: 'datei', wert: pfad, ...regler(), dunkel: Math.max(regler().dunkel, DUNKEL_STANDARD) });
      setMeldung(tr('Abgelegt in der Dateiablage: {0}', pfad));
    } catch (e) {
      // Kein Dateiablage-Plugin (404) oder nicht freigegeben (403): ein Satz, der Dialog bleibt benutzbar (Verläufe, Adresse)
      if (e instanceof ApiError && (e.status === 404 || e.status === 503)) setMeldung(tr('Noch nicht eingerichtet.'));
      else if (e instanceof ApiError && e.status === 403) setMeldung(tr('Noch nicht freigegeben.'));
      else setMeldung(e instanceof Error ? e.message : String(e));
    } finally {
      setLaedt(false);
      if (dateiFeld) dateiFeld.value = '';
    }
  };

  const adresseUebernehmen = () => {
    const u = adresse().trim();
    if (!urlGueltig(u)) {
      setMeldung(tr('Nur Adressen mit https:// (oder ein Pfad auf diesem Server).'));
      return;
    }
    waehle('url', u);
  };

  onMount(() => {
    const zu = (e: KeyboardEvent) => {
      if (e.key === 'Escape') p.onSchliessen();
    };
    window.addEventListener('keydown', zu);
    const vorher = document.activeElement as HTMLElement | null;
    el?.querySelector<HTMLElement>('select, button')?.focus();
    onCleanup(() => {
      window.removeEventListener('keydown', zu);
      if (vorher?.isConnected) vorher.focus();
    });
  });

  const muster = (hintergrund: string | undefined, an: boolean, text: string, tun: () => void) => (
    <button type="button" class="os-tapete-muster" classList={{ 'os-tapete-an': an }} aria-pressed={an} onClick={tun}>
      <span class="os-tapete-flaeche" style={{ background: hintergrund ?? 'var(--color-bg)' }} />
      <span class="os-tapete-name">{text}</span>
    </button>
  );

  return (
    <div class="os-start absolute inset-0 z-40 flex items-center justify-center bg-black/25 p-4" onClick={(e) => { if (e.target === e.currentTarget) p.onSchliessen(); }}>
      <div ref={el} role="dialog" aria-modal="true" aria-label={tr('Tapete')} class="os-glas os-glas-blur os-menue max-h-full w-[min(36rem,100%)] overflow-auto p-5">
        <div class="mb-3 flex items-center gap-3">
          <h2 class="m-0 flex-1 text-lg font-semibold">{tr('Tapete')}</h2>
          <button type="button" class="os-knopf" aria-label={tr('Schließen')} onClick={() => p.onSchliessen()}>✕</button>
        </div>
        <label class="mb-3 flex items-center gap-3 text-sm">
          <span class="text-(--color-fg-muted)">{tr('Bildschirm')}</span>
          <select class="os-tapete-feld min-w-0 flex-1" value={String(ziel())} onChange={(e) => setZiel(Number(e.currentTarget.value))}>
            <For each={p.ziele}>{(z) => <option value={String(z.index)}>{z.name}</option>}</For>
          </select>
        </label>

        <div class="os-tapete-raster">
          {muster('var(--os-tapete-kulisse)', !jetzt(), 'Kulisse', () => setze(undefined))}
          <For each={TAPETEN}>{(t) => muster(t.hintergrund, jetzt()?.art === 'auswahl' && jetzt()!.wert === t.id, t.name, () => waehle('auswahl', t.id))}</For>
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <button type="button" class="os-chip" disabled={laedt()} onClick={() => dateiFeld?.click()}>Eigenes Bild …</button>
          <input ref={dateiFeld} type="file" accept="image/*" class="hidden" onChange={(e) => void hochladen(e.currentTarget.files?.[0])} />
          <Show when={jetzt()?.art === 'datei'}>
            <span class="min-w-0 truncate text-(--color-fg-muted)" title={jetzt()!.wert}>{jetzt()!.wert.split('/').pop()}</span>
          </Show>
        </div>
        <form class="mt-2 flex gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); adresseUebernehmen(); }}>
          <input class="os-tapete-feld min-w-0 flex-1" type="url" inputmode="url" placeholder="https://… (Bildadresse)" value={adresse()} onInput={(e) => setAdresse(e.currentTarget.value)} />
          <button type="submit" class="os-chip">{tr('Übernehmen')}</button>
        </form>

        <Show when={jetzt()}>
          <div class="mt-4 grid grid-cols-[auto_minmax(0,1fr)_3rem] items-center gap-x-3 gap-y-2 text-sm">
            <span>{tr('Abdunkeln')}</span>
            <input type="range" min="0" max={DUNKEL_MAX} value={jetzt()!.dunkel} onInput={(e) => setze({ ...jetzt()!, dunkel: Number(e.currentTarget.value) })} />
            <span class="text-right tabular-nums text-(--color-fg-muted)">{jetzt()!.dunkel} %</span>
            <span>{tr('Weichzeichnen')}</span>
            <input type="range" min="0" max={WEICH_MAX} value={jetzt()!.weich} onInput={(e) => setze({ ...jetzt()!, weich: Number(e.currentTarget.value) })} />
            <span class="text-right tabular-nums text-(--color-fg-muted)">{jetzt()!.weich} px</span>
          </div>
        </Show>
        <Show when={meldung()}>
          <p role="status" class="mt-3 mb-0 text-sm text-(--color-fg-muted)">{meldung()}</p>
        </Show>
      </div>
    </div>
  );
}
