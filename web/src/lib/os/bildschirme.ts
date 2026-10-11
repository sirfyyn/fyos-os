/**
 * Bildschirme des OS: nach links und rechts wischen.
 *
 * Bildschirm 0 ist immer der Start: der Startbildschirm, ohne Fenster — so bleibt die Übersicht
 * immer einen Wisch entfernt. Dahinter folgen beliebig viele Arbeitsbildschirme mit
 * je eigener Anordnung (lib/os/anordnung.ts). Wird auf dem Start eine Fläche geöffnet, landet sie
 * auf dem zuletzt benutzten Arbeitsbildschirm (gibt es keinen, entsteht „Bildschirm 1“).
 *
 * Reine Funktionen; gespeichert im Browser, gemeldet an den Hub (Plugin shell).
 */
import { listePruefen, oeffnen as fensterOeffnen, ohneMax, type Fenster, type StartZustand } from './anordnung';

export interface Bildschirm {
  id: string;
  name: string;
  fenster: Fenster[];
  /**
   * Vollbild-Bildschirm einer Anwendung (wie das Vollbild am Mac): ein eigener Arbeitsbildschirm, auf dem genau diese eine
   * Anwendung maximiert ist. Wischen und ⌥⌘←/→ wechseln zu ihm und von ihm weg wie zwischen allen Bildschirmen. Es kommen
   * keine anderen Fenster dazu.
   */
  vollbild?: boolean;
  /** Vollbild-Bildschirm: der Bildschirm, von dem die Anwendung kam und auf den sie beim Verlassen zurückkehrt. */
  vollbildVon?: string;
}

export interface Arbeitsplatz {
  bildschirme: Bildschirm[];
  /** 0 = Startbildschirm, 1… = bildschirme[aktiv - 1] */
  aktiv: number;
  /** Zuletzt benutzter Arbeitsbildschirm (1…), Ziel für Flächen, die auf dem Start geöffnet werden */
  zuletzt: number;
}

export const START = 0;
export const BILDSCHIRME_MAX = 9;
const SCHLUESSEL = 'fyos:os:bildschirme:v1';
const NAME_MAX = 30;

export const leer = (): Arbeitsplatz => ({ bildschirme: [], aktiv: START, zuletzt: 1 });

let zaehler = 0;
const neueId = (): string => `b${Date.now().toString(36)}${(zaehler++).toString(36)}`;

export const anzahl = (ap: Arbeitsplatz): number => ap.bildschirme.length + 1;

/** Der Arbeitsbildschirm zu Index `i` (1…), sonst undefined (Start oder ungültig). */
export const bildschirmBei = (ap: Arbeitsplatz, i: number): Bildschirm | undefined =>
  i >= 1 ? ap.bildschirme[i - 1] : undefined;

export const aktueller = (ap: Arbeitsplatz): Bildschirm | undefined => bildschirmBei(ap, ap.aktiv);

const grenzeIndex = (ap: Arbeitsplatz, i: number): number => Math.max(0, Math.min(ap.bildschirme.length, i));

/** Zu Bildschirm `i` wechseln (0 = Start); außerhalb wird begrenzt. */
export function wechseln(ap: Arbeitsplatz, i: number): Arbeitsplatz {
  const ziel = grenzeIndex(ap, i);
  if (ziel === ap.aktiv) return ap;
  return { ...ap, aktiv: ziel, zuletzt: ziel >= 1 ? ziel : ap.zuletzt };
}

export const nachLinks = (ap: Arbeitsplatz): Arbeitsplatz => wechseln(ap, ap.aktiv - 1);
export const nachRechts = (ap: Arbeitsplatz): Arbeitsplatz => wechseln(ap, ap.aktiv + 1);

/** Neuer, leerer Arbeitsbildschirm hinten; wechselt dorthin. Höchstens BILDSCHIRME_MAX. */
export function neuerBildschirm(ap: Arbeitsplatz, name?: string, fenster: Fenster[] = []): Arbeitsplatz {
  if (ap.bildschirme.length >= BILDSCHIRME_MAX) return ap;
  const n = ap.bildschirme.length + 1;
  const b: Bildschirm = { id: neueId(), name: (name ?? `Bildschirm ${n}`).trim().slice(0, NAME_MAX) || `Bildschirm ${n}`, fenster };
  const bildschirme = [...ap.bildschirme, b];
  return { bildschirme, aktiv: bildschirme.length, zuletzt: bildschirme.length };
}

/** Umbenennen; ein leerer Name gibt den Bildschirm wieder der Automatik (er heißt dann nach seinen Fenstern). */
export function umbenennen(ap: Arbeitsplatz, i: number, name: string): Arbeitsplatz {
  const b = bildschirmBei(ap, i);
  if (!b) return ap;
  const sauber = name.trim().slice(0, NAME_MAX) || `Bildschirm ${i}`;
  if (sauber === b.name) return ap;
  return { ...ap, bildschirme: ap.bildschirme.map((x, j) => (j === i - 1 ? { ...x, name: sauber } : x)) };
}

const AUTOMATISCH = /^Bildschirm \d+$/;

/** Hat niemand den Namen vergeben? „Bildschirm 2“ entsteht beim Anlegen und steht so in alten Speicherständen. */
export const automatischBenannt = (name: string): boolean => !name.trim() || AUTOMATISCH.test(name.trim());

/**
 * Was ein Bildschirm heißt: sein eigener Name, sonst das, was
 * auf ihm offen ist — „Notizen“, „Notizen & Kalender“, „Notizen, Kalender +2“. Vorn stehen die sichtbaren
 * Fenster, minimierte zählen erst danach. Ohne Fenster heißt er nach seinem Punkt (`i` = 1… Arbeitsbildschirm, der
 * Start ist der erste Punkt, also „Bildschirm 3“ = dritter Punkt). Früher sagte „Bildschirm 2“ nichts und zählte
 * gegen die Punkte.
 */
export function anzeigeName(b: Bildschirm, i: number, titel: (id: string) => string | undefined): string {
  if (!automatischBenannt(b.name)) return b.name;
  const offen = [...b.fenster.filter((w) => !w.min), ...b.fenster.filter((w) => w.min)]
    .map((w) => titel(w.id))
    .filter((t): t is string => !!t);
  // Leer: nach der Stelle in der Punktreihe (der Start ist der erste Punkt), damit zwei leere unterscheidbar bleiben
  if (offen.length === 0) return `Bildschirm ${i + 1}`;
  const [erster, zweiter] = offen;
  if (offen.length === 1) return erster!;
  if (offen.length === 2) return `${erster} & ${zweiter}`;
  return `${erster}, ${zweiter} +${offen.length - 2}`;
}

/** Arbeitsbildschirm `i` entfernen (seine Fenster schließen mit). Der Start bleibt immer. */
export function entfernen(ap: Arbeitsplatz, i: number): Arbeitsplatz {
  if (!bildschirmBei(ap, i)) return ap;
  const bildschirme = ap.bildschirme.filter((_, j) => j !== i - 1);
  const anpassen = (k: number): number => (k > i ? k - 1 : k === i ? Math.min(i, bildschirme.length) : k);
  return {
    bildschirme,
    aktiv: Math.max(0, Math.min(bildschirme.length, anpassen(ap.aktiv))),
    zuletzt: Math.max(1, Math.min(Math.max(1, bildschirme.length), anpassen(ap.zuletzt))),
  };
}

/** Fenster eines Arbeitsbildschirms ersetzen (`fn` bekommt die alte Liste). */
export function fensterAendern(ap: Arbeitsplatz, i: number, fn: (l: Fenster[]) => Fenster[]): Arbeitsplatz {
  const b = bildschirmBei(ap, i);
  if (!b) return ap;
  const neu = fn(b.fenster);
  if (neu === b.fenster) return ap;
  // Ein Vollbild-Bildschirm ohne seine eine Anwendung (geschlossen) ist wieder ein gewöhnlicher Bildschirm
  const { vollbild: _v, vollbildVon: _von, ...gewoehnlich } = b;
  const x: Bildschirm = b.vollbild && neu.length !== 1 ? { ...gewoehnlich, fenster: neu } : { ...b, fenster: neu };
  return { ...ap, bildschirme: ap.bildschirme.map((y, j) => (j === i - 1 ? x : y)) };
}

/** Wo ist die Fläche offen? Index des Bildschirms oder -1. */
export const wo = (ap: Arbeitsplatz, id: string): number => {
  const j = ap.bildschirme.findIndex((b) => b.fenster.some((w) => w.id === id));
  return j >= 0 ? j + 1 : -1;
};

/**
 * Fläche öffnen. Ist sie schon offen, wird dorthin gewechselt (und sie aus der Minimierung geholt).
 * Sonst auf dem aktuellen Arbeitsbildschirm, vom Start aus auf dem zuletzt benutzten (oder einem
 * neuen). Gibt `voll: true` zurück, wenn dort schon MAX_OFFEN Fenster offen sind.
 */
export function flaecheOeffnen(
  ap: Arbeitsplatz,
  id: string,
  opt: { vor?: string | null; breit?: boolean; start?: StartZustand; sonstNeu?: boolean; gross?: number } = {},
): { ap: Arbeitsplatz; voll: boolean } {
  const da = wo(ap, id);
  if (da >= 1) {
    // Schon offen: nach vorn holen; kommt ein neuer Startzustand mit (Link mit Eingabe), übernimmt ihn das Fenster.
    // Eine Maximierung anderer Fenster auf diesem Bildschirm endet (anordnung.ts `oeffnen`).
    const ap2 = fensterAendern(wechseln(ap, da), da, (l) => fensterOeffnen(l, id, opt.start ? { start: opt.start } : {}));
    return { ap: ap2, voll: false };
  }
  let basis = ap;
  let ziel = ap.aktiv >= 1 ? ap.aktiv : ap.zuletzt;
  // Ein Vollbild-Bildschirm gehört seiner Anwendung: was neu aufgeht, kommt auf einen anderen Arbeitsbildschirm
  if (bildschirmBei(basis, ziel)?.vollbild) {
    const frei = ap.bildschirme.map((b, j) => ({ b, j: j + 1 })).filter((x) => !x.b.vollbild).map((x) => x.j);
    const zuletzt = frei.includes(ap.zuletzt) ? ap.zuletzt : frei[frei.length - 1];
    if (zuletzt != null) {
      ziel = zuletzt;
    } else {
      const neu = neuerBildschirm(basis);
      if (neu === basis) return { ap: wechseln(basis, ziel), voll: true };
      basis = neu;
      ziel = basis.aktiv;
    }
  }
  if (!bildschirmBei(basis, ziel)) {
    basis = neuerBildschirm(basis);
    ziel = basis.aktiv;
  }
  const vorher = bildschirmBei(basis, ziel)!.fenster;
  const nachher = fensterOeffnen(vorher, id, opt);
  if (nachher === vorher) {
    // Links („In FYOS öffnen“, ?offen=, Links aus Apps) zeigen die App immer: ist der Bildschirm voll, auf einem neuen.
    // Live 04.10.: ein Link auf die MCP-App öffnete auf einem Bildschirm mit 9 Fenstern schweigend nichts.
    const frisch = opt.sonstNeu ? neuerBildschirm(basis) : basis;
    if (frisch === basis) return { ap: wechseln(basis, ziel), voll: true };
    const dort = fensterOeffnen([], id, opt);
    return { ap: fensterAendern(frisch, frisch.aktiv, () => dort), voll: false };
  }
  return { ap: wechseln(fensterAendern(basis, ziel, () => nachher), ziel), voll: false };
}

/** Fenster auf einen anderen Arbeitsbildschirm verschieben (behält Größe und Zustand). */
export function verschiebenNach(ap: Arbeitsplatz, id: string, ziel: number): Arbeitsplatz {
  const von = wo(ap, id);
  if (von < 1 || von === ziel || !bildschirmBei(ap, ziel)) return ap;
  // Ein Vollbild-Bildschirm nimmt nichts auf und gibt seine Anwendung nur über `vollbildAus` her
  if (bildschirmBei(ap, von)!.vollbild || bildschirmBei(ap, ziel)!.vollbild) return ap;
  const { max: _max, ...w } = bildschirmBei(ap, von)!.fenster.find((x) => x.id === id)!;
  const ohne = fensterAendern(ap, von, (l) => l.filter((x) => x.id !== id));
  return wechseln(fensterAendern(ohne, ziel, (l) => [...l.map((x) => (x.max ? ohneMax(x) : x)), { ...w, min: false }]), ziel);
}

export const istVollbild = (ap: Arbeitsplatz, i: number): boolean => !!bildschirmBei(ap, i)?.vollbild;

/**
 * Eine Anwendung in den Vollbild-Bildschirm schicken (wie das Vollbild am Mac): sie bekommt einen eigenen Arbeitsbildschirm
 * direkt hinter dem, auf dem sie war, und ist dort maximiert; der Ansicht wird dorthin gewechselt. Ist sie das einzige Fenster
 * ihres Bildschirms, wird dieser Bildschirm selbst zum Vollbild-Bildschirm (kein leerer bleibt zurück). Sind schon alle
 * BILDSCHIRME_MAX belegt, kommt derselbe Arbeitsplatz zurück. Ein Fenster, das schon im Vollbild ist, bleibt, wo es ist.
 */
export function vollbildAn(ap: Arbeitsplatz, id: string): Arbeitsplatz {
  const i = wo(ap, id);
  const b = bildschirmBei(ap, i);
  if (!b || b.vollbild) return ap;
  const w = b.fenster.find((x) => x.id === id)!;
  const gross: Fenster = { ...w, min: false, max: true, fest: true };
  if (b.fenster.length === 1) {
    const bildschirme = ap.bildschirme.map((x, j) => (j === i - 1 ? { ...x, fenster: [gross], vollbild: true } : x));
    return { ...ap, bildschirme, aktiv: i, zuletzt: i };
  }
  if (ap.bildschirme.length >= BILDSCHIRME_MAX) return ap;
  const rest = b.fenster.filter((x) => x.id !== id);
  const neu: Bildschirm = { id: neueId(), name: `Bildschirm ${ap.bildschirme.length + 1}`, fenster: [gross], vollbild: true, vollbildVon: b.id };
  const bildschirme = ap.bildschirme.map((x, j) => (j === i - 1 ? { ...x, fenster: rest } : x));
  bildschirme.splice(i, 0, neu); // direkt hinter den Bildschirm, von dem sie kam
  return { bildschirme, aktiv: i + 1, zuletzt: i + 1 };
}

/**
 * Den Vollbild-Bildschirm `i` verlassen: die Anwendung kehrt auf ihren Bildschirm zurück (und ist nicht mehr maximiert), der
 * Vollbild-Bildschirm verschwindet und die Ansicht wechselt dorthin. War sie allein auf ihrem Bildschirm oder gibt es den
 * alten nicht mehr, bleibt der Bildschirm und ist ein gewöhnlicher Arbeitsbildschirm.
 */
export function vollbildAus(ap: Arbeitsplatz, i: number): Arbeitsplatz {
  const b = bildschirmBei(ap, i);
  if (!b?.vollbild) return ap;
  const { vollbild: _v, vollbildVon: von, ...gewoehnlich } = b;
  const fenster = b.fenster.map(ohneMax);
  const heim = von ? ap.bildschirme.findIndex((x) => x.id === von && !x.vollbild) + 1 : 0;
  if (heim < 1) {
    return { ...ap, bildschirme: ap.bildschirme.map((x, j) => (j === i - 1 ? { ...gewoehnlich, fenster } : x)), aktiv: i, zuletzt: i };
  }
  const bildschirme = ap.bildschirme
    .map((x, j) => (j + 1 === heim ? { ...x, fenster: [...x.fenster, ...fenster.map((w) => ({ ...w, min: false }))] } : x))
    .filter((_, j) => j !== i - 1);
  const ziel = heim > i ? heim - 1 : heim;
  return { bildschirme, aktiv: ziel, zuletzt: ziel };
}

/** Alle Fenster aller Bildschirme (für Hub und Bereinigung). */
export const alleFenster = (ap: Arbeitsplatz): Fenster[] => ap.bildschirme.flatMap((b) => b.fenster);

/**
 * Fenster unter anderer ID führen (`neu` bekommt die alte ID): so wird aus einem Link auf ein Werkzeug einer App mit
 * mehreren (`app:werkstatt__ausfuehren`) das Fenster der App selbst. Gibt es die neue ID schon auf dem Bildschirm,
 * bleibt das erste Fenster. Ohne Änderung kommt derselbe Arbeitsplatz zurück.
 */
export function idsUmbenennen(ap: Arbeitsplatz, neu: (id: string) => string): Arbeitsplatz {
  let geaendert = false;
  const bildschirme = ap.bildschirme.map((b) => {
    const gesehen = new Set<string>();
    const fenster: Fenster[] = [];
    for (const w of b.fenster) {
      const id = neu(w.id);
      if (id !== w.id) geaendert = true;
      if (gesehen.has(id)) continue;
      gesehen.add(id);
      fenster.push(id === w.id ? w : { ...w, id });
    }
    return fenster.length === b.fenster.length && fenster.every((w, i) => w === b.fenster[i]) ? b : { ...b, fenster };
  });
  return geaendert ? { ...ap, bildschirme } : ap;
}

/** Fenster entfernen, deren Fläche es nicht mehr gibt. */
export const bereinigen = (ap: Arbeitsplatz, bekannt: (id: string) => boolean): Arbeitsplatz => {
  let geaendert = false;
  const bildschirme = ap.bildschirme.map((b) => {
    const f = b.fenster.filter((w) => bekannt(w.id));
    if (f.length !== b.fenster.length) geaendert = true;
    return f.length === b.fenster.length ? b : { ...b, fenster: f };
  });
  return geaendert ? { ...ap, bildschirme } : ap;
};

/** Aus Speicher oder Hub: gültige Bildschirme, jede Fläche höchstens einmal über alle. */
export function pruefen(roh: unknown): Arbeitsplatz {
  const r = (roh && typeof roh === 'object' ? roh : {}) as Partial<Arbeitsplatz>;
  const gesehen = new Set<string>();
  const bildschirme: Bildschirm[] = [];
  for (const b of Array.isArray(r.bildschirme) ? r.bildschirme : []) {
    if (!b || typeof b !== 'object' || bildschirme.length >= BILDSCHIRME_MAX) continue;
    const fenster = listePruefen((b as Bildschirm).fenster).filter((w) => !gesehen.has(w.id) && !!gesehen.add(w.id));
    const name = typeof (b as Bildschirm).name === 'string' ? (b as Bildschirm).name.trim().slice(0, NAME_MAX) : '';
    const id = typeof (b as Bildschirm).id === 'string' && (b as Bildschirm).id ? (b as Bildschirm).id : neueId();
    const neu: Bildschirm = { id, name: name || `Bildschirm ${bildschirme.length + 1}`, fenster };
    // Vollbild-Bildschirm: genau eine Anwendung, maximiert. Mit mehr oder keinem Fenster ist es ein gewöhnlicher Bildschirm.
    if ((b as Bildschirm).vollbild === true && fenster.length === 1) {
      neu.fenster = [{ ...fenster[0]!, max: true }];
      neu.vollbild = true;
      const von = (b as Bildschirm).vollbildVon;
      if (typeof von === 'string' && von && von.length <= 60) neu.vollbildVon = von;
    }
    bildschirme.push(neu);
  }
  const zahl = (x: unknown, std: number) => (typeof x === 'number' && Number.isInteger(x) ? x : std);
  const ap: Arbeitsplatz = { bildschirme, aktiv: 0, zuletzt: 1 };
  ap.aktiv = grenzeIndex(ap, zahl(r.aktiv, 0));
  ap.zuletzt = Math.max(1, Math.min(Math.max(1, bildschirme.length), zahl(r.zuletzt, 1)));
  return ap;
}

/** Laden; ohne Bildschirme wird die alte Anordnung (eine Liste) zu „Bildschirm 1“. */
export function laden(alt: () => Fenster[] = () => []): Arbeitsplatz {
  try {
    const roh = localStorage.getItem(SCHLUESSEL);
    if (roh) return pruefen(JSON.parse(roh));
  } catch {
    /* kaputt oder gesperrt: wie neu */
  }
  const liste = alt();
  if (liste.length) {
    const ap = neuerBildschirm(leer(), 'Bildschirm 1', liste);
    return { ...ap, aktiv: START };
  }
  return leer();
}

/**
 * Ein anderer Tab hat gespeichert (das storage-Ereignis kommt nur in den übrigen Tabs an): dessen Anordnung übernehmen.
 * Ohne das überschrieb der zuletzt speichernde Tab still die Fenster des anderen. Gibt die Abmeldung zurück.
 */
export function fremdesSpeichern(fn: (ap: Arbeitsplatz) => void): () => void {
  const hoerer = (e: StorageEvent) => {
    if (e.key !== SCHLUESSEL || !e.newValue) return;
    try {
      fn(pruefen(JSON.parse(e.newValue)));
    } catch {
      /* kaputt: ignorieren */
    }
  };
  window.addEventListener('storage', hoerer);
  return () => window.removeEventListener('storage', hoerer);
}

export function speichern(ap: Arbeitsplatz): void {
  try {
    localStorage.setItem(SCHLUESSEL, JSON.stringify(ap));
  } catch {
    /* Speicher gesperrt — gilt dann nur für diese Sitzung */
  }
}
