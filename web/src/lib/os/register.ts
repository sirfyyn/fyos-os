/**
 * register.ts — die eine Schnittstelle, über die Plugins und die Konfiguration Flächen in die Shell bringen.
 *
 *     registriereFlaechen({
 *       flaechen: [{ id: 'seite:notizen', titel: 'Notizen', gruppe: 'Arbeit', art: 'seite', kuerzel: 'No', pfad: '/notizen/' }],
 *       symbole: { 'seite:notizen': ['file-text', 200] },         // Glyphe (Lucide-Name aus symbole-daten.ts) und Farbton
 *       gruppen: { reihenfolge: ['Arbeit'], plugin: { notizen: 'Arbeit' }, app: { notizen__liste: 'Arbeit' } },
 *       standardPlaetze: [{ name: 'Morgen', ids: ['seite:notizen', 'app:kalender__heute'] }],
 *       alias: { 'seite:alt': 'seite:notizen' },
 *       dinge: { notiz: { name: 'Notiz', pfad: '/notizen/' } },     // ziehbare Dinge (`fyos://notiz/<id>`)
 *     });
 *
 *   flaechen          Seiten (`art: 'seite'` mit `pfad`, läuft in einem Fenster), externe Dienste (`extern: <url>`,
 *                     öffnet in einem neuen Tab) und native Flächen (`art: 'nativ'` mit `laden`, eine Solid-Komponente
 *                     im Fenster). Hub-Apps brauchen keinen Eintrag: sie erscheinen von selbst aus /hub-api/apps.
 *   symbole           Glyphe und Farbton je Fläche. Hub-Apps bringen ihr Gesicht selbst mit (lib/mcp-apps/gesicht.ts).
 *   gruppen           Reihenfolge der Gruppen im Start und die Zuordnung von Hub-Apps zu einer Gruppe: zuerst der ganze
 *                     Werkzeugname (`app`), dann das Plugin-Präfix vor `__` (`plugin`); Unbekanntes bleibt „Apps".
 *   standardPlaetze   Vorlagen, die der Start anbietet (Name → Flächen). Fehlende Flächen werden übergangen.
 *   alias             alte Kennungen → heutige Fläche (gespeicherte Anordnungen, Lesezeichen, `?offen=`).
 *   dinge             (optional) Typen ziehbarer Dinge zwischen Flächen (lib/os/ziehen.ts).
 *
 * Eine Registrierung mit `quelle` ersetzt alle früheren derselben Quelle (die Konfiguration lädt so ihre externen
 * Dienste neu); ohne `quelle` gilt die Fläche, bis dieselbe Kennung erneut registriert wird. Der Aufruf ist
 * wiederholbar und darf jederzeit geschehen — die Shell zeichnet sich neu.
 */
import { createSignal } from 'solid-js';
import type { Flaeche } from './flaechen';

export interface GruppenRegistrierung {
  /** Gruppen, die im Start vor den eingebauten stehen (in dieser Reihenfolge) */
  reihenfolge?: string[];
  /** Plugin-Präfix (vor `__`) → Gruppe */
  plugin?: Record<string, string>;
  /** Ganzer App-Name → Gruppe (hat Vorrang vor `plugin`) */
  app?: Record<string, string>;
}

export interface StandardPlatz {
  name: string;
  ids: string[];
}

/** Ein Ding, das sich zwischen Flächen ziehen lässt (z. B. eine Notiz): menschlicher Name und die Seite, auf der es lebt. */
export interface DingArt {
  name: string;
  /** Pfad der Seite, die das Ding zeigt; die Shell sucht die Fläche mit diesem Pfad */
  pfad: string;
}

export interface Registrierung {
  flaechen?: Flaeche[];
  /** Ziehbare Dinge: Typ (`fyos://<typ>/<id>`) → Name und Seite */
  dinge?: Record<string, DingArt>;
  symbole?: Record<string, [glyphe: string, ton: number]>;
  gruppen?: GruppenRegistrierung;
  standardPlaetze?: StandardPlatz[];
  alias?: Record<string, string>;
  /** Wer registriert; eine neue Registrierung derselben Quelle ersetzt die alte */
  quelle?: string;
}

const GEFAEHRLICH = new Set(['__proto__', 'constructor', 'prototype']);

interface Stand {
  flaechen: Map<string, { f: Flaeche; quelle?: string }>;
  symbole: Map<string, [string, number]>;
  reihenfolge: Map<string, string[]>;
  plugin: Map<string, string>;
  app: Map<string, string>;
  plaetze: Map<string, StandardPlatz>;
  alias: Map<string, string>;
  dinge: Map<string, DingArt>;
}

const neu = (): Stand => ({
  dinge: new Map(),
  flaechen: new Map(),
  symbole: new Map(),
  reihenfolge: new Map(),
  plugin: new Map(),
  app: new Map(),
  plaetze: new Map(),
  alias: new Map(),
});

let stand = neu();
const [version, setVersion] = createSignal(0);

const sauber = (k: string): boolean => !GEFAEHRLICH.has(k);

export function registriereFlaechen(r: Registrierung): void {
  const q = r.quelle;
  if (q) {
    for (const [id, e] of stand.flaechen) if (e.quelle === q) stand.flaechen.delete(id);
    stand.reihenfolge.delete(q);
  }
  for (const f of r.flaechen ?? []) {
    if (!f || typeof f.id !== 'string' || !f.id || typeof f.titel !== 'string' || typeof f.gruppe !== 'string') continue;
    stand.flaechen.set(f.id, { f, quelle: q });
  }
  for (const [id, s] of Object.entries(r.symbole ?? {})) {
    if (sauber(id) && Array.isArray(s) && typeof s[0] === 'string' && typeof s[1] === 'number') stand.symbole.set(id, [s[0], s[1]]);
  }
  if (r.gruppen?.reihenfolge) stand.reihenfolge.set(q ?? '', r.gruppen.reihenfolge.filter((g) => typeof g === 'string'));
  for (const [k, g] of Object.entries(r.gruppen?.plugin ?? {})) if (sauber(k) && typeof g === 'string') stand.plugin.set(k, g);
  for (const [k, g] of Object.entries(r.gruppen?.app ?? {})) if (sauber(k) && typeof g === 'string') stand.app.set(k, g);
  for (const p of r.standardPlaetze ?? []) {
    if (p && typeof p.name === 'string' && Array.isArray(p.ids)) stand.plaetze.set(p.name, { name: p.name, ids: p.ids.filter((i) => typeof i === 'string') });
  }
  for (const [von, nach] of Object.entries(r.alias ?? {})) if (sauber(von) && typeof nach === 'string') stand.alias.set(von, nach);
  for (const [typ, d] of Object.entries(r.dinge ?? {})) {
    if (sauber(typ) && /^[\w-]+$/.test(typ) && d && typeof d.name === 'string' && typeof d.pfad === 'string') stand.dinge.set(typ, { name: d.name, pfad: d.pfad });
  }
  setVersion((n) => n + 1);
}

/** Nur für Tests: alles Registrierte vergessen. */
export function registerZuruecksetzen(): void {
  stand = neu();
  setVersion((n) => n + 1);
}

/** Lesen hängt Solid-Berechnungen an die Registrierung: sie laufen neu, wenn jemand registriert. */
const lesen = <T>(f: (s: Stand) => T): T => {
  version();
  return f(stand);
};

export const registrierteFlaechen = (): Flaeche[] => lesen((s) => [...s.flaechen.values()].map((e) => e.f));
export const registrierteSymbole = (id: string): [string, number] | undefined => lesen((s) => s.symbole.get(id));
export const registrierteReihenfolge = (): string[] => lesen((s) => [...s.reihenfolge.values()].flat());
export const registrierteStandardPlaetze = (): StandardPlatz[] => lesen((s) => [...s.plaetze.values()]);
export const registrierteAlias = (id: string): string | undefined => lesen((s) => s.alias.get(id));
export const registrierteDinge = (typ: string): DingArt | undefined => lesen((s) => s.dinge.get(typ));

/** Gruppe einer Hub-App: ganzer Name, dann Plugin-Präfix; sonst „Apps". */
export const gruppeFuerApp = (name: string): string =>
  lesen((s) => s.app.get(name) ?? s.plugin.get(name.split('__')[0] ?? '') ?? 'Apps');
