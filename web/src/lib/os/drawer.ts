/**
 * drawer.ts — Stand je App und „Zuletzt“ für den App-Drawer (OS-Neubau P7).
 *
 * die alten Chips zeigten „so wenig infos auf so viel raum“. Im Drawer trägt jede App eine Zeile Stand, z. B.
 * „Oktober 2.044 von 2.044 € bezahlt“ oder „2 warten auf dich“. Quelle ist EIN gebündelter Abruf: die Kurzsätze der
 * Zentrale (`zentrale.zustand`, dieselben Kacheln) und die eine Zahl aus „Wartet auf dich“ (lib/os/wartet.ts). Keine
 * Einzelabrufe je App.
 *
 * „Zuletzt“: die zuletzt geöffneten Flächen je Gerät (localStorage), höchstens zwölf.
 */
import type { Flaeche } from './flaechen';
import type { ZentraleZustand } from '~/lib/zentrale';
import { tr } from '~/lib/i18n';

export type DrawerAnsicht = 'raum' | 'az' | 'zuletzt';

export interface StandQuellen {
  zustand?: ZentraleZustand | null;
  wartet?: number | null;
}

/** Welche Kachel der Zentrale den Stand einer Fläche trägt: Muster über Kennung, App-Name und Titel. */
const ZUORDNUNG: { muster: RegExp; kachel: string }[] = [
  { muster: /finan|geld|money|konto/i, kachel: 'geld' },
  { muster: /kalender|termin/i, kachel: 'heute' },
  { muster: /haus|smarthome|licht|zuhause/i, kachel: 'haus' },
  { muster: /cluster|steuerpult|k8s/i, kachel: 'cluster' },
  { muster: /modell/i, kachel: 'modelle' },
  { muster: /werkstatt/i, kachel: 'werkstatt' },
  { muster: /bestand/i, kachel: 'bestand' },
  { muster: /hardware|bildschirm/i, kachel: 'hardware' },
  { muster: /lagebild|leitstand|betrieb|repos|ci\b/i, kachel: 'betrieb' },
  { muster: /woche|vorhaben/i, kachel: 'woche' },
  { muster: /belegung/i, kachel: 'belegung' },
];

const VORGAENGE = /vorgaenge|vorgänge|itsm|aufgaben|wartet/i;

/** Eine Zeile Stand für eine Fläche, oder null (dann zeigt der Drawer den Untertitel). */
export function standFuer(f: Pick<Flaeche, 'id' | 'titel' | 'appName'>, q: StandQuellen): string | null {
  const text = `${f.id} ${f.appName ?? ''} ${f.titel}`;
  if (VORGAENGE.test(text) && typeof q.wartet === 'number') {
    return q.wartet === 0 ? tr('nichts wartet auf dich') : q.wartet === 1 ? tr('1 wartet auf dich') : tr('{0} warten auf dich', q.wartet);
  }
  const kacheln = q.zustand?.kacheln ?? [];
  // Native Kachel-Flächen tragen die Kachel im Namen (nativ:<kachel-id>)
  const direkt = f.id.startsWith('nativ:') ? kacheln.find((k) => `nativ:${k.id}` === f.id) : undefined;
  const ziel = direkt ?? kacheln.find((k) => ZUORDNUNG.some((z) => z.kachel === k.id && z.muster.test(text)));
  if (!ziel) return null;
  if (ziel.fehler) return tr('nicht abrufbar');
  const s = (ziel.kurz || '').replace(/\*\*/g, '').trim();
  return s ? kuerzen(s, 60) : null;
}

/** Ein Stand ist eine Abweichung, wenn seine Kachel ab Dringlichkeit 30 liegt oder ausgefallen ist. */
export function standTon(f: Pick<Flaeche, 'id' | 'titel' | 'appName'>, q: StandQuellen): 'gelb' | 'rot' | null {
  const text = `${f.id} ${f.appName ?? ''} ${f.titel}`;
  if (VORGAENGE.test(text)) return (q.wartet ?? 0) > 0 ? 'gelb' : null;
  const k = (q.zustand?.kacheln ?? []).find(
    (k) => `nativ:${k.id}` === f.id || ZUORDNUNG.some((z) => z.kachel === k.id && z.muster.test(text)),
  );
  if (!k) return null;
  if (k.fehler || k.dringlichkeit >= 60) return 'rot';
  return k.dringlichkeit >= 30 ? 'gelb' : null;
}

/** A–Z über alle Gruppen, ohne Doppelte. */
export function alphabetisch(gruppen: { flaechen: Flaeche[] }[]): Flaeche[] {
  const gesehen = new Set<string>();
  return gruppen
    .flatMap((g) => g.flaechen)
    .filter((f) => (gesehen.has(f.id) ? false : (gesehen.add(f.id), true)))
    .sort((a, b) => a.titel.localeCompare(b.titel, 'de'));
}

// ── Zuletzt ──────────────────────────────────────────────────────────────────────────────────

const SCHLUESSEL = 'fyos:drawer:zuletzt:v1';
export const ZULETZT_MAX = 12;

export function zuletztLesen(speicher: Pick<Storage, 'getItem'> | undefined = sicher()): string[] {
  try {
    const roh = JSON.parse(speicher?.getItem(SCHLUESSEL) ?? '[]');
    return Array.isArray(roh) ? roh.filter((x): x is string => typeof x === 'string').slice(0, ZULETZT_MAX) : [];
  } catch {
    return [];
  }
}

/** Merkt eine geöffnete Fläche vorn; Doppelte rücken nach vorn. */
export function zuletztMerken(id: string, speicher: Pick<Storage, 'getItem' | 'setItem'> | undefined = sicher()): string[] {
  const neu = [id, ...zuletztLesen(speicher).filter((x) => x !== id)].slice(0, ZULETZT_MAX);
  try {
    speicher?.setItem(SCHLUESSEL, JSON.stringify(neu));
  } catch {
    /* privates Fenster */
  }
  return neu;
}

/** Die Flächen in der Reihenfolge von „Zuletzt“ (unbekannte Kennungen fallen weg). */
export function zuletztFlaechen(ids: string[], gruppen: { flaechen: Flaeche[] }[]): Flaeche[] {
  const alle = new Map(gruppen.flatMap((g) => g.flaechen).map((f) => [f.id, f]));
  return ids.map((id) => alle.get(id)).filter((f): f is Flaeche => !!f);
}

function sicher(): Storage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

const kuerzen = (t: string, n: number) => (t.length <= n ? t : `${t.slice(0, n - 1).trimEnd()}…`);
