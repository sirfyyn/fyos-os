/**
 * bruecke-werkzeuge.ts — die Seitenwerkzeuge des OS.
 *
 * Das offene /os bietet Werkzeuge an, die der Agent (über die OS-Brücke, `os.ausfuehren`) und
 * Browser-Agenten (WebMCP, `document.modelContext`, mcp-playwright) gleichermaßen nutzen — aus
 * EINEM Register (lib/werkzeuge.ts):
 *
 *   os_oeffnen       Fläche öffnen (ID oder Name), optional mit Eingabe
 *   os_fenster       lesen: aktiver Bildschirm, Bildschirme, Fenster, Agent-Dock, Anruf
 *   os_schliessen    ein offenes Fenster schließen
 *   os_zentrale      lesen: Lage-Satz, Ampel, Kacheln (zentrale.zustand, kompakt)
 *   seite_lesen      lesen: sichtbarer Text des vordersten (oder benannten) Fensters
 *   os_mitteilungen  „Der Agent zeigt dir …“-Mitteilungen lesen / ein- und ausschalten / stummschalten
 *
 * Alles hängt an einem `OsKontext`, den die Shell-Komponente (components/os/Bruecke.tsx) aus ihren
 * Zugriffsfunktionen baut — so lassen sich die Werkzeuge ohne Shell testen. Fehlerfälle sind ehrlich:
 * eine unbekannte Fläche, ein voller Bildschirm, ein abgelaufene Sitzung, ein Hub, der nicht antwortet,
 * eine Seite, die noch lädt — jeweils mit einem Satz, nie eine leere Antwort, die nach Wahrheit aussieht.
 */
import { ApiError } from '~/lib/api/client';
import { hub } from '~/lib/hub';
import { ergebnis, fehler, type Werkzeug, type WerkzeugErgebnis } from '~/lib/werkzeuge';
import { MAX_OFFEN } from './anordnung';
import { zielAufloesen } from './allein';
import { bildschirmBei, wo } from './bildschirme';
import { istSichtbarOffen, lageBauen, loeseAuf, loeseFensterAuf, type LageFenster, type LageQuelle } from './bruecke-lage';
import { einstellungLesen, einstellungSchreiben, istStumm, type ZeigtEinstellung } from './agent-zeigt';

/** Das Ereignis, mit dem das OS „öffne diese Fläche (mit dieser Eingabe)“ weitergibt. Siehe `oeffnenMitPruefung`. */
export const OEFFNEN_EREIGNIS = 'fyos:oeffnen';

export interface OsKontext {
  /** Der Zustand der Shell im Augenblick der Frage (frisch gelesen, nicht gemerkt) */
  quelle: () => LageQuelle;
  /** Shell: Fläche öffnen (holt sie nach vorn) */
  oeffne: (id: string) => void;
  /** Shell: Fenster schließen; true, wenn es das Fenster gab */
  schliesse: (id: string) => boolean;
  einstellung?: { lesen: () => ZeigtEinstellung; schreiben: (e: ZeigtEinstellung) => void };
  /** Quelle der Zentrale (Vorgabe: Hub-Werkzeug `zentrale.zustand`) */
  zentrale?: () => Promise<unknown>;
  /** Wo `fyos:oeffnen` ausgelöst wird (Vorgabe: window) */
  ereignisse?: Pick<EventTarget, 'dispatchEvent'>;
  /** Wo die Fenster im DOM stehen (Vorgabe: document) */
  wurzel?: ParentNode;
  jetzt?: () => number;
}

async function warteBis(f: () => boolean, maxMs: number, schritt = 40): Promise<boolean> {
  if (f()) return true;
  const ende = Date.now() + maxMs;
  while (Date.now() < ende) {
    await new Promise<void>((r) => setTimeout(r, schritt));
    if (f()) return true;
  }
  return f();
}

// ── Öffnen und Schließen ──────────────────────────────────────────────────────────────────────

export type OeffnenErgebnis = { ok: true; ergebnis: Record<string, unknown> } | { ok: false; fehler: string };

const VOLL = `Auf dem Bildschirm sind schon ${MAX_OFFEN} Flächen offen. Schließ eines oder öffne einen neuen Bildschirm.`;

/**
 * Eine Fläche öffnen. `ziel` ist eine ID oder ein Name; unbekannt ist ein Fehler mit den Kandidaten.
 *
 * Das OS gibt `fyos:oeffnen` als abbrechbares Ereignis (`detail: {ziel, eingabe, quelle: 'bruecke'}`)
 * an alle Zuhörer: Wer die Eingabe versteht (Deeplink- und App-Rahmen-Strang), öffnet die Fläche damit
 * und ruft `event.preventDefault()`. Hat niemand das Ereignis behandelt, öffnet der Rückruf der Shell
 * die Fläche ohne Eingabe — die Antwort sagt dann `eingabe_uebernommen: false`.
 * Danach wird geprüft, ob die Fläche wirklich offen ist (höchstens 1,5 s Geduld).
 */
export async function oeffnenMitPruefung(k: OsKontext, ziel: unknown, eingabe: Record<string, unknown> | null = null): Promise<OeffnenErgebnis> {
  const a = loeseAuf(ziel, k.quelle().flaechen);
  if (!a.ok) return { ok: false, fehler: a.fehler };
  const hatEingabe = !!eingabe && Object.keys(eingabe).length > 0;

  if (a.id === 'agent' && k.quelle().agent) {
    return { ok: true, ergebnis: { gezeigt: true, ziel: a.id, titel: a.flaeche.titel, bildschirm: null, ort: 'dock' } };
  }

  const ev = new CustomEvent(OEFFNEN_EREIGNIS, { detail: { ziel: a.id, eingabe: hatEingabe ? eingabe : null, quelle: 'bruecke' }, cancelable: true });
  const ereignisse = k.ereignisse ?? window;
  const unbehandelt = ereignisse.dispatchEvent(ev); // false: ein Zuhörer hat es übernommen
  if (unbehandelt) k.oeffne(a.id);

  const offen = await warteBis(() => istSichtbarOffen(k.quelle(), a.id), 1_500);
  if (!offen) {
    const q = k.quelle();
    const zielBildschirm = bildschirmBei(q.ap, q.ap.aktiv >= 1 ? q.ap.aktiv : q.ap.zuletzt);
    const voll = !!zielBildschirm && zielBildschirm.fenster.filter((w) => !w.min).length >= MAX_OFFEN;
    return { ok: false, fehler: voll ? VOLL : `„${a.flaeche.titel}“ ließ sich nicht öffnen.` };
  }

  const q = k.quelle();
  const i = wo(q.ap, a.id);
  const r: Record<string, unknown> = {
    gezeigt: true,
    ziel: a.id,
    titel: a.flaeche.titel,
    bildschirm: i >= 1 ? i : null,
    ...(i >= 1 ? { bildschirm_name: bildschirmBei(q.ap, i)!.name } : {}),
  };
  if (hatEingabe) {
    // „Ein Zuhörer hat das Ereignis angenommen“ heißt noch nicht, dass die Eingabe ankam: die Shell nimmt es an und
    // wirft die Eingabe weg, wenn sie zu groß oder kein Objekt ist, oder wenn die Fläche keine App ist (Seiten kennen
    // keine Eingabe). Darum prüfen wir mit denselben Regeln wie die Shell (allein.ts `zielAufloesen` → `startPruefen`),
    // ob ein Startzustand daraus würde.
    const uebernommen = !unbehandelt && !!zielAufloesen(q.flaechen, a.id, eingabe ?? undefined)?.start;
    r.eingabe_uebernommen = uebernommen;
    if (!uebernommen) {
      r.hinweis = unbehandelt
        ? 'Die Fläche ist offen, aber dieses OS konnte ihr die Eingabe nicht übergeben.'
        : 'Die Fläche ist offen, aber ohne die Eingabe: sie war zu groß, ungültig oder die Fläche nimmt keine Eingabe an (nur Apps tun das).';
    }
  }
  return { ok: true, ergebnis: r };
}

export async function schliessenMitPruefung(k: OsKontext, ziel: unknown): Promise<OeffnenErgebnis> {
  const q = k.quelle();
  const lage = lageBauen(q);
  const t = loeseFensterAuf(ziel, lage.fenster);
  if (!t.ok) {
    const meintAgent = typeof ziel === 'string' && /^agent(\b|-)/i.test(ziel.trim());
    if (meintAgent && q.agent) return { ok: false, fehler: 'Der Agent ist als Dock offen, nicht als Fenster — den schließt der Benutzer über die Menüleiste oder ⌘J.' };
    return { ok: false, fehler: t.fehler };
  }
  const w = t.fenster;
  if (!k.schliesse(w.id)) return { ok: false, fehler: `„${w.titel}“ ließ sich nicht schließen (nicht mehr offen?).` };
  const noch = wo(k.quelle().ap, w.id) >= 1;
  if (noch) return { ok: false, fehler: `„${w.titel}“ ist noch offen.` };
  return { ok: true, ergebnis: { geschlossen: true, id: w.id, titel: w.titel, bildschirm: w.bildschirm } };
}

// ── Lesen ─────────────────────────────────────────────────────────────────────────────────────

export function fensterUebersicht(q: LageQuelle) {
  const lage = lageBauen(q);
  const aktiv = lage.bildschirme.find((b) => b.index === lage.bildschirm);
  return {
    bildschirm: lage.bildschirm,
    bildschirm_name: aktiv?.name ?? 'Start',
    bildschirme: lage.bildschirme,
    fenster: lage.fenster,
    agent_offen: q.agent,
    anruf_offen: lage.anruf,
    agent_vorne: lage.agent_vorne,
    hinweis: lage.fenster.length ? undefined : 'Es ist kein Fenster offen.',
  };
}

type Kachel = { id?: unknown; titel?: unknown; dringlichkeit?: unknown; kurz?: unknown; quelle_ok?: unknown };

/** zentrale.zustand, auf das Nötige verdichtet: Lage-Satz, Ampel, die Kacheln nach Dringlichkeit. */
export function zentraleKompakt(z: unknown): Record<string, unknown> {
  const r = (z && typeof z === 'object' ? z : {}) as { lage_satz?: unknown; ampel?: unknown; gruss?: unknown; kacheln?: unknown };
  const kacheln = (Array.isArray(r.kacheln) ? (r.kacheln as Kachel[]) : [])
    .filter((k) => k && typeof k === 'object')
    .map((k) => ({
      id: String(k.id ?? ''),
      titel: String(k.titel ?? k.id ?? ''),
      dringlichkeit: typeof k.dringlichkeit === 'number' ? k.dringlichkeit : 0,
      kurz: typeof k.kurz === 'string' ? k.kurz : '',
      ...(k.quelle_ok === false ? { quelle_ok: false } : {}),
    }))
    .sort((a, b) => b.dringlichkeit - a.dringlichkeit)
    .slice(0, 12);
  return {
    lage_satz: typeof r.lage_satz === 'string' ? r.lage_satz : '',
    ampel: typeof r.ampel === 'string' ? r.ampel : null,
    kacheln,
    ...(kacheln.length ? {} : { leer: true, hinweis: 'Die Zentrale hat gerade keine Kacheln geliefert.' }),
  };
}

function hubFehler(e: unknown): WerkzeugErgebnis {
  if (e instanceof ApiError) {
    // 403/404: das Werkzeug gibt es nicht oder ist nicht freigegeben — kein Plugin eingerichtet
    if (e.status === 403 || e.status === 404) return fehler('Noch nicht eingerichtet.');
    if (e.status === 401) return fehler('Sitzung abgelaufen — neu anmelden.');
    if (e.status === 0) return fehler(`Der Hub ist nicht erreichbar (${e.message}).`);
    if (e.status === 408) return fehler('Der Hub hat nicht rechtzeitig geantwortet.');
    return fehler(`Der Hub meldet einen Fehler: ${e.message}`);
  }
  return fehler(`Der Hub ist nicht erreichbar (${e instanceof Error ? e.message : String(e)}).`);
}

const zeichenLimit = (x: unknown): number => {
  const n = typeof x === 'number' && Number.isFinite(x) ? Math.round(x) : 6_000;
  return Math.min(20_000, Math.max(500, n));
};

const kuerzen = (text: string, max: number) => ({ text: text.length > max ? text.slice(0, max) : text, gekuerzt: text.length > max, zeichen_gesamt: text.length });

const sichtText = (el: Element): string => {
  const t = (el as HTMLElement).innerText ?? el.textContent ?? '';
  return t.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
};

function fensterElement(wurzel: ParentNode, id: string): HTMLElement | null {
  for (const el of wurzel.querySelectorAll<HTMLElement>('[data-fenster]')) if (el.getAttribute('data-fenster') === id) return el;
  return null;
}

/**
 * Sichtbarer Inhalt eines Fensters, knapp. Seiten und der Agent laufen als gleichnamige iframes: deren
 * eigenes `fyos_seite_lesen` (mit den Zuständen laden/leer/fehler) wird genutzt, sonst der Text von
 * `<main>`. Native Flächen: der Text des Fensterinhalts. Hub-Apps: ehrlich „abgeschirmt“.
 */
export async function seiteLesen(k: OsKontext, args: Record<string, unknown>): Promise<WerkzeugErgebnis> {
  const zeichen = zeichenLimit(args.zeichen);
  const lage = lageBauen(k.quelle());
  let ziel: LageFenster | undefined;
  if (args.fenster !== undefined && args.fenster !== null && args.fenster !== '') {
    const t = loeseFensterAuf(args.fenster, lage.fenster);
    if (!t.ok) return fehler(t.fehler);
    ziel = t.fenster;
  } else {
    ziel = lage.fenster.find((w) => w.vorne);
  }
  if (!ziel) {
    return ergebnis({
      leer: true,
      bildschirm: lage.bildschirm,
      hinweis:
        lage.bildschirm === 0
          ? 'Auf dem Start ist kein Fenster offen. Die Zentrale zeigt die Lage — lies sie mit os_zentrale.'
          : 'Auf diesem Bildschirm ist kein Fenster offen. Öffne eines mit os_oeffnen.',
    });
  }
  const info = { id: ziel.id, titel: ziel.titel, art: ziel.art };
  if (ziel.min) return fehler(`„${ziel.titel}“ ist minimiert und zeigt nichts. Hol es mit os_oeffnen nach vorn.`);
  if (ziel.art === 'hubapp') {
    return ergebnis({
      fenster: info,
      text: null,
      hinweis: `Hub-Apps zeigen ihren Inhalt in einer abgeschirmten Fläche, die sich hier nicht lesen lässt. Lies „${ziel.titel}“ über ihr Hub-Werkzeug (z. B. ${ziel.id.replace(/^app:/, '')}).`,
    });
  }
  const el = fensterElement(k.wurzel ?? document, ziel.id);
  if (!el) return fehler(`„${ziel.titel}“ ist offen, aber noch nicht geladen (anderer Bildschirm, der noch nie gezeigt wurde?). Wechsle dorthin und versuch es nochmal.`);

  if (ziel.art === 'nativ') {
    const inhalt = el.querySelector('[data-kontext="inhalt"]') ?? el;
    const t = kuerzen(sichtText(inhalt), zeichen);
    return ergebnis({ fenster: info, ...t, ...(t.text ? {} : { hinweis: 'Das Fenster zeigt gerade keinen Text (lädt noch oder ist leer).' }) });
  }

  // Seite oder Agent: same-origin iframe
  const rahmen = el.querySelector('iframe');
  if (!rahmen) return fehler(`„${ziel.titel}“ hat noch keinen Inhalt geladen.`);
  let fenster: Window | null = null;
  let dok: Document | null = null;
  try {
    fenster = rahmen.contentWindow;
    dok = rahmen.contentDocument;
  } catch {
    /* anderer Ursprung */
  }
  if (!fenster || !dok) return fehler(`Der Inhalt von „${ziel.titel}“ liegt nicht auf diesem Ursprung und lässt sich nicht lesen.`);
  if (dok.readyState === 'loading' || dok.location?.href === 'about:blank') return fehler(`„${ziel.titel}“ lädt noch — gleich nochmal versuchen.`);

  const eigenes = fenster.fyos?.werkzeuge;
  if (eigenes?.rufen) {
    const r = await eigenes.rufen('fyos_seite_lesen', {}).catch(() => null);
    if (r && !r.isError) {
      try {
        const j = JSON.parse(r.content[0]?.text ?? '{}') as { titel?: string; pfad?: string; text?: string; zustaende?: Record<string, number>; sitzung_abgelaufen?: boolean };
        const t = kuerzen(String(j.text ?? ''), zeichen);
        return ergebnis({
          fenster: info,
          seite: { titel: j.titel ?? null, pfad: j.pfad ?? null },
          ...(j.zustaende && Object.keys(j.zustaende).length ? { zustaende: j.zustaende } : {}),
          ...(j.sitzung_abgelaufen ? { sitzung_abgelaufen: true } : {}),
          ...t,
          ...(t.text ? {} : { hinweis: 'Die Seite zeigt gerade keinen Text (lädt noch oder ist leer).' }),
        });
      } catch {
        /* kein JSON: Rückfall unten */
      }
    }
  }
  const haupt = dok.querySelector('main') ?? dok.body;
  if (!haupt) return fehler(`„${ziel.titel}“ lädt noch — gleich nochmal versuchen.`);
  const t = kuerzen(sichtText(haupt), zeichen);
  return ergebnis({
    fenster: info,
    seite: { titel: dok.title || null, pfad: fenster.location?.pathname ?? null },
    ...t,
    ...(t.text ? {} : { hinweis: 'Die Seite zeigt gerade keinen Text (lädt noch oder ist leer).' }),
  });
}

// ── Die Werkzeuge ─────────────────────────────────────────────────────────────────────────────

export function osWerkzeuge(k: OsKontext): Werkzeug[] {
  const einst = k.einstellung ?? { lesen: () => einstellungLesen(), schreiben: (e: ZeigtEinstellung) => einstellungSchreiben(e) };
  const jetzt = k.jetzt ?? Date.now;
  return [
    {
      name: 'os_oeffnen',
      beschreibung:
        'Öffnet eine Fläche im OS (Seite, Hub-App, Anruf, Agent) in einem Fenster und holt sie nach vorn — für „zeig mir …“ und „mach … auf“. ziel: ID wie seite:berichte oder app:notizen__liste, oder der Name (Berichte, Notizen).',
      eingabe: {
        properties: {
          ziel: { type: 'string', description: 'Fläche: ID („seite:berichte“, „app:notizen__liste“, „nativ:anruf“, „agent“) oder Name („Berichte“, „Notizen“)' },
          eingabe: { type: 'object', additionalProperties: true, description: 'Eingabe für die Fläche, bei Hub-Apps die Argumente ihres Werkzeugs; nur wirksam, wenn die Fläche sie annimmt (die Antwort sagt es: eingabe_uebernommen)' },
        },
        required: ['ziel'],
        additionalProperties: false,
      },
      ausfuehren: async (args) => {
        const eingabe = args.eingabe && typeof args.eingabe === 'object' && !Array.isArray(args.eingabe) ? (args.eingabe as Record<string, unknown>) : null;
        const r = await oeffnenMitPruefung(k, args.ziel, eingabe);
        return r.ok ? ergebnis(r.ergebnis) : fehler(r.fehler);
      },
    },
    {
      name: 'os_fenster',
      beschreibung:
        'Liest, was im OS offen ist: aktiver Bildschirm, alle Bildschirme, jedes Fenster (Titel, Art, Bildschirm, vorn, minimiert), ob Agent-Dock und Anruf offen sind. Zum Nachsehen, bevor du etwas öffnest oder schließt.',
      lesend: true,
      eingabe: { properties: {}, additionalProperties: false },
      ausfuehren: async () => ergebnis(fensterUebersicht(k.quelle())),
    },
    {
      name: 'os_schliessen',
      beschreibung: 'Schließt ein offenes Fenster im OS. ziel: ID oder Name wie in os_fenster. Der Agent-Dock ist kein Fenster und bleibt.',
      eingabe: {
        properties: { ziel: { type: 'string', description: 'ID („seite:berichte“) oder Name („Berichte“) eines offenen Fensters' } },
        required: ['ziel'],
        additionalProperties: false,
      },
      ausfuehren: async (args) => {
        const r = await schliessenMitPruefung(k, args.ziel);
        return r.ok ? ergebnis(r.ergebnis) : fehler(r.fehler);
      },
    },
    {
      name: 'os_zentrale',
      beschreibung: 'Liest die Zentrale des Startbildschirms, wenn ein Plugin sie liefert: Lage-Satz, Ampel und die Kacheln nach Dringlichkeit, je mit Kurzwert. Sonst: „Noch nicht eingerichtet.“',
      lesend: true,
      eingabe: { properties: {}, additionalProperties: false },
      ausfuehren: async () => {
        try {
          return ergebnis(zentraleKompakt(await (k.zentrale ?? (() => hub('zentrale.zustand')))()));
        } catch (e) {
          return hubFehler(e);
        }
      },
    },
    {
      name: 'seite_lesen',
      beschreibung:
        'Liest den sichtbaren Text des vordersten Fensters (oder des mit fenster benannten): Titel, Pfad, Zustände (laden/leer/fehler) und Text, gekürzt auf zeichen. Hub-Apps lassen sich so nicht lesen, dafür gibt es ihr Hub-Werkzeug.',
      lesend: true,
      eingabe: {
        properties: {
          fenster: { type: 'string', description: 'ID oder Name eines offenen Fensters; weglassen = das vorderste' },
          zeichen: { type: 'integer', minimum: 500, maximum: 20000, description: 'Höchstens so viele Zeichen Text (Vorgabe 6000)' },
        },
        additionalProperties: false,
      },
      ausfuehren: (args) => seiteLesen(k, args),
    },
    {
      name: 'os_mitteilungen',
      beschreibung:
        '„Der Agent zeigt dir …“-Mitteilungen im OS: lesen, ein- oder ausschalten (an) oder für stumm_minuten still stellen (0 hebt auf). Ohne Angaben nur lesen. Einschalten (an: true) nur auf ausdrücklichen Wunsch des Benutzers.',
      eingabe: {
        properties: {
          an: { type: 'boolean', description: 'true = Mitteilungen des Agenten an, false = aus, bis sie wieder eingeschaltet werden' },
          stumm_minuten: { type: 'integer', minimum: 0, maximum: 1440, description: 'Stumm für so viele Minuten; 0 hebt auf' },
        },
        additionalProperties: false,
      },
      ausfuehren: async (args) => {
        const e = { ...einst.lesen() };
        if (args.an !== undefined) {
          if (typeof args.an !== 'boolean') return fehler('an muss true oder false sein.');
          e.aus = !args.an;
          if (args.an) e.stumm_bis = 0;
        }
        if (args.stumm_minuten !== undefined) {
          const m = Number(args.stumm_minuten);
          if (!Number.isFinite(m) || m < 0) return fehler('stumm_minuten muss eine Zahl von 0 bis 1440 sein.');
          e.stumm_bis = m === 0 ? 0 : jetzt() + Math.min(m, 1440) * 60_000;
        }
        if (args.an !== undefined || args.stumm_minuten !== undefined) einst.schreiben(e);
        const stumm = istStumm(e, jetzt());
        return ergebnis({
          an: !e.aus,
          stumm: !e.aus && stumm,
          stumm_bis: e.stumm_bis > jetzt() ? new Date(e.stumm_bis).toISOString() : null,
          satz: e.aus ? 'Mitteilungen des Agenten sind aus.' : stumm ? 'Mitteilungen des Agenten sind stumm.' : 'Mitteilungen des Agenten sind an.',
        });
      },
    },
  ];
}
