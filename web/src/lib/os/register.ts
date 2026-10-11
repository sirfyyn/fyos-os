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
 *       uebergaben: [...],                                           // was beim Ablegen eines Dings auf eine App geschieht (Hub-Apps)
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
 *   dinge             (optional) Typen ziehbarer Dinge zwischen Flächen (lib/os/ziehen.ts). Hub-Apps melden ihre Dinge und
 *                     Übergaben im Hub an (`registriere_ding`, `registriere_uebergabe`, docs/ERWEITERN.md); die Shell nimmt sie
 *                     mit der Liste der Apps selbst auf.
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

/**
 * Ein Ding, das sich zwischen Flächen ziehen lässt (z. B. eine Notiz): menschlicher Name und die Fläche, auf der es lebt —
 * entweder eine Seite (`pfad`, die Shell sucht die Fläche mit diesem Pfad) oder eine Hub-App (`flaeche`, ihre Kennung
 * `app:<plugin>__<werkzeug>`). Hub-Apps melden ihre Dinge selbst (`registriere_ding` im Hub, `GET /hub-api/apps`) und
 * sagen dazu, wie ein einzelnes Ding gelesen wird (`lesen`: Werkzeug, `idArgument`: sein Kennungsargument) und welche
 * Felder des Ergebnisses Übergaben einsetzen dürfen (`felder`).
 */
export interface DingArt {
  name: string;
  /** Pfad der Seite, die das Ding zeigt; die Shell sucht die Fläche mit diesem Pfad */
  pfad?: string;
  /** Kennung der Hub-App-Fläche, die das Ding zeigt (`app:<plugin>__<werkzeug>`) */
  flaeche?: string;
  /** Lesendes Werkzeug (`<plugin>__<name>`), das ein Ding zu seiner Kennung liefert */
  lesen?: string;
  /** Name des Kennungsarguments von `lesen` (Vorgabe `id`) */
  idArgument?: string;
  /** Felder des Ergebnisses von `lesen`, die eine Übergabe einsetzen darf */
  felder?: string[];
}

/**
 * Was geschieht, wenn ein Ding vom Typ `quelle` auf das Fenster der App `ziel` fällt: das Werkzeug der Ziel-App, wie die Felder
 * des Dings seine Argumente füllen (`abbildung`: Texte mit `{id}`, `{label}`, `{feld}`) und der Satz für den Hinweis am Fenster.
 * Angelegt oder geändert wird erst nach Plan und „Ja“ (App.beantragen in der Ziel-App).
 */
export interface Uebergabe {
  quelle: string;
  /** Kennung der Ziel-Fläche (`app:<plugin>__<werkzeug>`) */
  ziel: string;
  /** Werkzeug der Ziel-App (`<plugin>__<name>`) */
  werkzeug: string;
  abbildung: Record<string, string | number | boolean>;
  wirkung: string;
}

export interface Registrierung {
  flaechen?: Flaeche[];
  /** Ziehbare Dinge: Typ (`fyos://<typ>/<id>`) → Name und Fläche */
  dinge?: Record<string, DingArt>;
  /** Übergaben zwischen Dingen und Apps (der Hub liefert sie mit seinen Apps) */
  uebergaben?: Uebergabe[];
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
  uebergaben: Map<string, Uebergabe>;
}

const neu = (): Stand => ({
  dinge: new Map(),
  uebergaben: new Map(),
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
    if (!sauber(typ) || !/^[\w-]+$/.test(typ) || !d || typeof d.name !== 'string') continue;
    const art: DingArt = { name: d.name };
    if (typeof d.pfad === 'string') art.pfad = d.pfad;
    if (typeof d.flaeche === 'string' && d.flaeche.startsWith('app:')) art.flaeche = d.flaeche;
    if (!art.pfad && !art.flaeche) continue; // ohne Fläche gäbe es nichts zu zeigen
    if (typeof d.lesen === 'string' && /^[\w]+__[\w]+$/.test(d.lesen)) art.lesen = d.lesen;
    if (typeof d.idArgument === 'string' && /^[a-z][a-z0-9_]*$/.test(d.idArgument)) art.idArgument = d.idArgument;
    if (Array.isArray(d.felder)) art.felder = d.felder.filter((f): f is string => typeof f === 'string' && /^[a-z][a-z0-9_]*$/.test(f));
    stand.dinge.set(typ, art);
  }
  for (const u of r.uebergaben ?? []) {
    if (!u || typeof u.quelle !== 'string' || !/^[\w-]+$/.test(u.quelle) || typeof u.ziel !== 'string' || !u.ziel.startsWith('app:')) continue;
    if (typeof u.werkzeug !== 'string' || !/^[\w]+__[\w]+$/.test(u.werkzeug) || typeof u.wirkung !== 'string' || !u.wirkung) continue;
    if (!u.abbildung || typeof u.abbildung !== 'object' || Array.isArray(u.abbildung)) continue;
    const abbildung: Uebergabe['abbildung'] = {};
    for (const [arg, wert] of Object.entries(u.abbildung)) {
      if (sauber(arg) && /^[a-z][a-z0-9_]*$/.test(arg) && ['string', 'number', 'boolean'].includes(typeof wert)) abbildung[arg] = wert;
    }
    stand.uebergaben.set(`${u.quelle}>${u.ziel}`, { quelle: u.quelle, ziel: u.ziel, werkzeug: u.werkzeug, abbildung, wirkung: u.wirkung.slice(0, 160) });
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
/** Die Übergabe für ein Ding dieses Typs auf dem Fenster dieser Fläche (`app:…`); undefined = es gibt keine. */
export const registrierteUebergabe = (typ: string, zielFlaeche: string): Uebergabe | undefined => lesen((s) => s.uebergaben.get(`${typ}>${zielFlaeche}`));

/** Gruppe einer Hub-App: ganzer Name, dann Plugin-Präfix; sonst „Apps". */
export const gruppeFuerApp = (name: string): string =>
  lesen((s) => s.app.get(name) ?? s.plugin.get(name.split('__')[0] ?? '') ?? 'Apps');
