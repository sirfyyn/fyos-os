/**
 * config.ts — Laufzeit-Konfiguration der Shell.
 *
 * Zwei Quellen, beide ohne persönliche Werte im Code:
 *
 *   Bauzeit    `PUBLIC_FYOS_NAME` (Vorgabe „FYOS"): der Name im Menü und im Seitentitel.
 *   Laufzeit   `/fyos.config.json`, von nginx als Datei ausgeliefert (Beispiel:
 *              `public/fyos.config.example.json`). Sie nennt den Agenten und die externen
 *              Dienste (Links, die in einem neuen Tab öffnen). Fehlt die Datei, läuft die Shell
 *              mit den Vorgaben.
 *
 * Der Ursprung ist immer `window.location.origin` — es gibt keine feste Adresse im Code.
 */
import { createSignal } from 'solid-js';
import { oeffentlicherUrsprungSetzen } from './os/oeffnen';
import { registriereFlaechen } from './os/register';
import { kuerzelVon } from './os/kuerzel';
import type { Flaeche } from './os/flaechen';

export const EXTERN_GRUPPE = 'Extern';

/** Ein Dienst mit eigener Oberfläche, der in einem neuen Tab öffnet (z. B. ein Git-Server oder Grafana). */
export interface ExternerDienst {
  slug: string;
  titel: string;
  url: string;
}

export interface FyosKonfiguration {
  /** Name des Systems; überschreibt `PUBLIC_FYOS_NAME` */
  name?: string;
  /** Zusätzlicher Ursprung, dessen Links im OS öffnen (hinter einem Proxy); Vorgabe: nur der eigene */
  oeffentlicheUrl?: string;
  agent?: {
    /** Anzeigename des Agenten (Dock, Fensterkopf) */
    name?: string;
    /** Adresse des Chats; Vorgabe `/agent/` (nginx leitet an das Gateway) */
    pfad?: string;
  };
  extern?: ExternerDienst[];
}

const VORGABE_NAME = 'FYOS';
const VORGABE_AGENT = 'Agent';
const VORGABE_AGENT_PFAD = '/agent/';

const bau = (import.meta.env?.PUBLIC_FYOS_NAME as string | undefined)?.trim();

const [konfig, setKonfig] = createSignal<FyosKonfiguration>({});

/** Name des Systems. */
export const systemName = (): string => konfig().name?.trim() || bau || VORGABE_NAME;

/** Anzeigename des Agenten. */
export const agentName = (): string => konfig().agent?.name?.trim() || VORGABE_AGENT;

/** Adresse des Agent-Chats (gleicher Ursprung, von nginx weitergereicht). */
export const agentPfad = (): string => {
  const p = konfig().agent?.pfad?.trim();
  return p && p.startsWith('/') ? p : VORGABE_AGENT_PFAD;
};

/** Ursprung dieser Seite — nie eine feste Adresse. */
export const ursprung = (): string => (typeof location !== 'undefined' ? location.origin : '');

const istHttp = (u: string): boolean => {
  try {
    const p = new URL(u).protocol;
    return p === 'https:' || p === 'http:';
  } catch {
    return false;
  }
};

/** Externe Dienste als Flächen (nur http/https, mit Kennung und Titel). */
export function externeFlaechen(liste: ExternerDienst[] | undefined): Flaeche[] {
  const out: Flaeche[] = [];
  for (const d of liste ?? []) {
    if (!d || typeof d.slug !== 'string' || typeof d.titel !== 'string' || typeof d.url !== 'string') continue;
    if (!/^[a-z0-9][a-z0-9_-]*$/i.test(d.slug) || !istHttp(d.url)) continue;
    out.push({
      id: `extern:${d.slug}`,
      titel: d.titel,
      gruppe: EXTERN_GRUPPE,
      art: 'seite',
      kuerzel: kuerzelVon(d.titel),
      extern: d.url,
    });
  }
  return out;
}

/** Konfiguration übernehmen: Name, Agent und externe Dienste (als Flächen registriert). */
export function konfigurationSetzen(k: FyosKonfiguration): void {
  setKonfig(k ?? {});
  oeffentlicherUrsprungSetzen(k?.oeffentlicheUrl);
  registriereFlaechen({ flaechen: externeFlaechen(k?.extern), quelle: 'konfiguration' });
}

/** Nur für Tests. */
export function konfigurationZuruecksetzen(): void {
  setKonfig({});
}

let lauf: Promise<FyosKonfiguration> | undefined;

/** `/fyos.config.json` laden (einmal je Seite). Fehlt sie oder ist sie ungültig, gelten die Vorgaben. */
export function konfigurationLaden(holen: typeof fetch = fetch): Promise<FyosKonfiguration> {
  lauf ??= (async () => {
    try {
      const r = await holen('/fyos.config.json', { headers: { Accept: 'application/json' }, cache: 'no-cache' });
      if (!r.ok) return {};
      const typ = r.headers?.get?.('content-type') ?? '';
      if (typ.includes('text/html')) return {};
      const k = (await r.json()) as FyosKonfiguration;
      if (!k || typeof k !== 'object' || Array.isArray(k)) return {};
      konfigurationSetzen(k);
      return k;
    } catch {
      return {};
    }
  })();
  return lauf;
}

/** Nur für Tests. */
export function konfigurationLadenZuruecksetzen(): void {
  lauf = undefined;
}
