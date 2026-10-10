/**
 * kulisse.ts — Einstellungen der OS-Kulisse: Lavalampe, Neon-Raster, Scanlines, Glas.
 *
 * Gespeichert im Browser (wie Theme und Akzent). Angewendet als Attribute/Variablen auf <html>,
 * die styles/os.css liest. Die Einstellungen-App ruft `kulisseSpeichern`; alle offenen Kulissen
 * ziehen über das Ereignis `fyos:kulisse` sofort nach.
 */

export type KulisseStil = 'lava' | 'ruhig' | 'aus';
export type KulisseFarben = 'neon' | 'aurora' | 'glut';

export interface KulisseEinstellung {
  /** lava = treibend, ruhig = steht still, aus = nur Grundfarbe */
  stil: KulisseStil;
  farben: KulisseFarben;
  /** Stärke der Farbflecken, 0–100 */
  lava: number;
  /** Neon-Raster und Horizont, 0–100 */
  raster: number;
  scan: boolean;
  /** 1 = normal, 2 = halb so schnell, 0.5 = doppelt so schnell */
  tempo: number;
  /** Unschärfe des Glases in px */
  glas: number;
}

export const KULISSE_STANDARD: KulisseEinstellung = {
  stil: 'lava',
  farben: 'neon',
  lava: 55,
  raster: 50,
  scan: true,
  tempo: 1,
  glas: 22,
};

export const KULISSE_SCHLUESSEL = 'fyos.os.kulisse.v1';
export const KULISSE_EREIGNIS = 'fyos:kulisse';

const zahl = (w: unknown, min: number, max: number, std: number): number =>
  typeof w === 'number' && Number.isFinite(w) ? Math.min(max, Math.max(min, w)) : std;

/** Gespeicherte Einstellung, auf gültige Werte begrenzt; ohne Speicher die Vorgabe. */
export function kulissePruefen(roh: unknown): KulisseEinstellung {
  const r = (roh && typeof roh === 'object' ? roh : {}) as Partial<KulisseEinstellung>;
  const s = KULISSE_STANDARD;
  return {
    stil: r.stil === 'ruhig' || r.stil === 'aus' || r.stil === 'lava' ? r.stil : s.stil,
    farben: r.farben === 'aurora' || r.farben === 'glut' || r.farben === 'neon' ? r.farben : s.farben,
    lava: zahl(r.lava, 0, 100, s.lava),
    raster: zahl(r.raster, 0, 100, s.raster),
    scan: typeof r.scan === 'boolean' ? r.scan : s.scan,
    tempo: zahl(r.tempo, 0.5, 3, s.tempo),
    glas: zahl(r.glas, 0, 40, s.glas),
  };
}

export function kulisseLaden(): KulisseEinstellung {
  try {
    const roh = localStorage.getItem(KULISSE_SCHLUESSEL);
    return kulissePruefen(roh ? JSON.parse(roh) : null);
  } catch {
    return { ...KULISSE_STANDARD };
  }
}

export function kulisseAnwenden(k: KulisseEinstellung, wurzel: HTMLElement = document.documentElement): void {
  wurzel.dataset.osStil = k.stil;
  wurzel.dataset.osFarben = k.farben;
  wurzel.style.setProperty('--os-lava', String(k.lava / 100));
  wurzel.style.setProperty('--os-raster', String(k.raster / 100));
  wurzel.style.setProperty('--os-scan', k.scan ? '1' : '0');
  wurzel.style.setProperty('--os-tempo', String(k.tempo));
  wurzel.style.setProperty('--os-glas-blur', `${k.glas}px`);
}

/** Einstellung zu einem Ereignis: der mitgeschickte Stand (auch eine Vorschau), sonst der gespeicherte (`storage`). */
export const kulisseVon = (e?: Event): KulisseEinstellung =>
  e instanceof CustomEvent && e.detail ? kulissePruefen(e.detail) : kulisseLaden();

/** `vorschau`: nur anwenden (Regler wird noch gezogen), gespeichert wird beim Loslassen. */
export function kulisseSpeichern(k: KulisseEinstellung, vorschau = false): void {
  const sauber = kulissePruefen(k);
  try {
    if (!vorschau) localStorage.setItem(KULISSE_SCHLUESSEL, JSON.stringify(sauber));
  } catch {
    /* privater Modus: gilt nur bis zum Neuladen */
  }
  kulisseAnwenden(sauber);
  window.dispatchEvent(new CustomEvent(KULISSE_EREIGNIS, { detail: sauber }));
}
