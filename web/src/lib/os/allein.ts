/**
 * allein.ts — eine Fläche allein im Tab, mit Weg zurück ins OS.
 *
 * Eine Fläche in einem eigenen Tab zeigt sich auf der Kulisse des OS, ohne weiteres Beiwerk, und hat einen
 * Zurück-Knopf: auch aus anderen Tabs heraus kommt man zum ursprünglichen Tab zurück.
 *
 *   alleinAdresse(ziel)   /os/allein/?ziel=… — die Fläche mit der Kulisse des OS, ohne Seitenleiste
 *   zielAufloesen         Fläche (`app:…`, `seite:…`), Werkzeug einer App oder Pfad → Fläche und Startzustand;
 *                         dieselbe Regel für die Shell (fyos:oeffnen) und die Allein-Ansicht
 *   osTabMelden           die Shell gibt ihrem Tab den Namen `fyos-os` und antwortet auf „wer ist da?“
 *   zurueckZumOs          Zurück-Knopf: zum Tab, aus dem die Fläche kam (opener); sonst zum offenen OS-Tab
 *                         (per Name); gibt es keinen, wird dieser Tab das OS mit der Fläche im Fenster.
 *
 * Browsergrenze: Ein Tab kann einen anderen nur nach vorn holen, wenn er ihn kennt — als opener oder über den
 * Fensternamen (Chrome findet Namen nur unter verwandten Tabs). Für einen ganz fremden Tab (Lesezeichen, Link aus
 * dem Chat) bleibt der dritte Weg; das OS stellt seine Anordnung dabei aus dem Speicher wieder her.
 */
const NIE = 'http://fyos.invalid';
import { appFlaecheZu, flaecheZu, type Flaeche } from './flaechen';
import { startPruefen, type StartZustand } from './anordnung';
import { eingabeKodieren, eingabeSauber, pfadSchluessel } from './oeffnen';

/** Name des OS-Tabs (window.name) und des Kanals, über den Tabs einander finden. */
export const OS_NAME = 'fyos-os';

/** Adresse der Allein-Ansicht für ein Ziel (Fläche, Werkzeug einer App oder Pfad einer Seite). */
export function alleinAdresse(ziel: string, eingabe?: Record<string, unknown>): string {
  const q = new URLSearchParams({ ziel });
  const e = eingabeKodieren(eingabe);
  if (e) q.set('eingabe', e);
  return `/os/allein/?${q}`;
}

/**
 * „In neuem Tab öffnen“ aus dem OS: die Allein-Ansicht, ausdrücklich MIT opener — über ihn findet der Zurück-Knopf
 * genau diesen OS-Tab wieder (früher `noopener` auf die alte Seite mit Seitenleiste, ohne Weg zurück).
 */
export function inNeuemTab(f: Pick<Flaeche, 'id' | 'extern'>, start?: StartZustand, w: Window = window): void {
  // Fremder Dienst (Gruppe „Extern“): direkt dorthin, ohne opener — es gibt keinen Weg zurück ins OS zu bauen.
  if (f.extern) {
    w.open(f.extern, '_blank', 'noopener');
    return;
  }
  w.open(alleinAdresse(start?.werkzeug ? `app:${start.werkzeug}` : f.id, start?.eingabe), '_blank');
}

/** Adresse des OS mit diesem Ziel im Fenster (Deeplink). */
export function osAdresse(ziel?: string): string {
  return ziel && !ziel.startsWith('/') ? `/os/?offen=${encodeURIComponent(ziel)}` : '/os/';
}

/**
 * Ziel → Fläche. `ziel` ist eine Fläche (`app:…`, `seite:…`, `nativ:…`), bei Apps auch ein Werkzeug mit derselben
 * Oberfläche, oder der Pfad einer Seite. Mit `eingabe` startet die App genau so (nur lesende Werkzeuge — das prüft
 * AppEingebettet). null = dafür gibt es keine Fläche.
 */
export function zielAufloesen(
  liste: Flaeche[],
  ziel: string,
  eingabe?: Record<string, unknown>,
): { f: Flaeche; start?: StartZustand } | null {
  if (ziel.startsWith('/')) {
    const f = pfadFlaeche(liste, ziel);
    return f ? { f } : null;
  }
  if (ziel.startsWith('app:')) {
    const name = ziel.slice(4);
    const f = appFlaecheZu(liste, name);
    if (!f) return null;
    const e = eingabeSauber(eingabe);
    // Ohne Eingabe und ohne anderes Werkzeug als die App selbst gibt es nichts Besonderes zu starten
    const start = e && (Object.keys(e).length > 0 || f.appName !== name) ? startPruefen({ werkzeug: name, eingabe: e }) : undefined;
    return { f, start };
  }
  const f = flaecheZu(liste, ziel);
  return f ? { f } : null;
}

/**
 * Die Fläche zum Pfad einer Seite: gleicher Pfad, und alle Parameter der Fläche stecken auch in der Adresse
 * (`/notizen/?ansicht=liste&id=7` → die Fläche mit `/notizen/?ansicht=liste`). Bei mehreren gewinnt die genaueste.
 */
export function pfadFlaeche(liste: Flaeche[], ziel: string): Flaeche | undefined {
  let u: URL;
  try {
    u = new URL(ziel, NIE);
  } catch {
    return undefined;
  }
  const pfad = pfadSchluessel(u.pathname);
  let beste: Flaeche | undefined;
  let genau = -1;
  for (const f of liste) {
    if (!f.pfad) continue;
    const v = new URL(f.pfad, NIE);
    if (pfadSchluessel(v.pathname) !== pfad) continue;
    const paare = [...v.searchParams];
    if (paare.every(([k, w]) => u.searchParams.getAll(k).includes(w)) && paare.length > genau) {
      beste = f;
      genau = paare.length;
    }
  }
  return beste;
}

type Nachricht = { art: 'wer' } | { art: 'hier'; href: string };

const kanal = (): BroadcastChannel | null => (typeof BroadcastChannel === 'function' ? new BroadcastChannel(OS_NAME) : null);

/** Von der Shell gerufen: Tab benennen und auf „wer ist da?“ antworten. Gibt das Abmelden zurück. */
export function osTabMelden(w: Window = window): () => void {
  try {
    w.name = OS_NAME;
  } catch {
    /* fremdes Fenster */
  }
  const k = kanal();
  if (!k) return () => {};
  k.onmessage = (e: MessageEvent<Nachricht>) => {
    if (e.data?.art === 'wer') k.postMessage({ art: 'hier', href: w.location.href } satisfies Nachricht);
  };
  return () => k.close();
}

/** Ist irgendwo ein OS-Tab offen? Antwort binnen `ms`. */
export function osTabDa(ms = 300): Promise<boolean> {
  const k = kanal();
  if (!k) return Promise.resolve(false);
  return new Promise((fertig) => {
    const uhr = setTimeout(() => {
      k.close();
      fertig(false);
    }, ms);
    k.onmessage = (e: MessageEvent<Nachricht>) => {
      if (e.data?.art !== 'hier') return;
      clearTimeout(uhr);
      k.close();
      fertig(true);
    };
    k.postMessage({ art: 'wer' } satisfies Nachricht);
  });
}

/** Ein Fenster desselben Ursprungs, das das OS zeigt (oder in dem es läuft), sonst null. */
function osFenster(w: Window | null | undefined, ich: Window): Window | null {
  try {
    if (!w || w === ich || w.closed) return null;
    const oben = w.top ?? w;
    return oben.location.origin === ich.location.origin && oben.location.pathname.replace(/\/+$/, '') === '/os' ? oben : null;
  } catch {
    return null;
  }
}

export type Rueckweg = 'opener' | 'name' | 'hier';

/**
 * Zurück ins OS (Klick auf den Zurück-Knopf — nur mit Nutzergeste darf ein Tab einen anderen nach vorn holen).
 *  1. Kam die Fläche aus dem OS („In neuem Tab öffnen“): jenen Tab nach vorn, diesen schließen.
 *  2. Läuft woanders ein OS-Tab, den dieser Tab über den Namen erreicht: nach vorn holen, diesen schließen
 *     (geht nur bei Tabs, die ein Skript geöffnet hat — sonst bleibt dieser im Hintergrund stehen).
 *  3. Sonst wird dieser Tab das OS, mit der Fläche im Fenster.
 */
export async function zurueckZumOs(ziel: string | undefined, ich: Window = window): Promise<Rueckweg> {
  const herkunft = osFenster(ich.opener as Window | null, ich);
  if (herkunft) {
    herkunft.focus();
    ich.close();
    return 'opener';
  }
  if (await osTabDa()) {
    const t = ich.open('', OS_NAME);
    const os = osFenster(t, ich);
    if (os) {
      os.focus();
      ich.close();
      return 'name';
    }
    // Den Namen kennt dieser Tab nicht (fremder Tab): der Browser hat ein leeres Fenster angelegt — gleich wieder zu
    try {
      if (t && t !== ich) t.close();
    } catch {
      /* egal */
    }
  }
  ich.location.assign(osAdresse(ziel));
  return 'hier';
}
