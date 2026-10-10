/**
 * Shell — das Betriebssystem im Browser (/os).
 *
 *   Menüleiste    oben wie am Mac: Systemmenü, was vorne ist, Ablage/Darstellung/Fenster/Hilfe,
 *                 rechts Kontrollzentrum, Datum und Uhr (components/os/Menueleiste.tsx).
 *   Menüs         ein Menü für alles (lib/os/menue.ts, components/os/Menue.tsx): Rechtsklick bzw.
 *                 Zwei-Finger-Tipp und Langdruck auf Schreibtisch, Fensterkopf, Dock-Symbol,
 *                 Bildschirm-Punkt und Kachel im Start; welches Menü, sagt `data-kontext` am Ziel.
 *                 Im Inhalt eines Fensters (`data-kontext="inhalt"`) bleibt das Menü des Browsers.
 *   Bildschirme   0 = Startbildschirm (App-Launcher), dahinter Arbeitsbildschirme (lib/os/bildschirme.ts).
 *                 Wechsel: Punkte über dem Dock, Wischen (folgt den Fingern), ⌥⌘←/→, ⌥⌘1–9.
 *   Übersicht     alle Bildschirme verkleinert nebeneinander (wie Mission Control): Kneifen,
 *                 ⌥⌘↑, Menü. Lebendig, nicht als Bild — die Bildschirme werden nur gezoomt.
 *   Raster        je Bildschirm 12 Spalten, Automatik bis zum ersten Eingriff (components/os/Raster.tsx).
 *   Dock          Start, Fenster als Symbole, Agent; darüber die Bildschirm-Punkte (components/os/Dock.tsx).
 *   Start         Launcher mit Suche, Bildschirmen, Vorlagen und allen Flächen (components/os/Start.tsx).
 *   Kulisse       ruht, wenn sie verdeckt ist (Arbeitsbildschirm), bei Untätigkeit und im Hintergrund.
 *   Hub           meldet die Anordnung (shell.merken), holt Befehle des Agenten (shell.abholen) —
 *                 seltener, wenn niemand arbeitet, gar nicht im Hintergrund-Tab. Fehlt das Werkzeug
 *                 im Hub, läuft die Shell allein weiter.
 *
 * Deep-Link: /os?offen=app:notizen__liste,seite:wiki öffnet diese Flächen.
 */
import { For, Show, createEffect, createMemo, createSignal, lazy, onCleanup, onMount, type JSX } from 'solid-js';
import Startbildschirm from './Startbildschirm';
import Mitteilungen, { type Hinweis } from './Mitteilungen';
import Dock from './Dock';
import { NEU_LADEN } from './Fenster';
import Kulisse from './Kulisse';
import Menue from './Menue';
import Menueleiste, { type LeistenMenue } from './Menueleiste';
import Raster from './Raster';
import type { Vorlage } from './Start';
import { hub } from '~/lib/hub';
import { apps as hubApps, type McpApp } from '~/lib/mcp-apps/host';
import { MAX_OFFEN, alleEinblenden, automatisch, laden as altLaden, minimieren, schliessen, startPruefen, type Fenster, type StartZustand } from '~/lib/os/anordnung';
import { appFragen, heften, kannHeften } from '~/lib/os/app-aktionen';
import {
  BILDSCHIRME_MAX, START, aktueller, alleFenster, anzeigeName, bereinigen, bildschirmBei, entfernen, fensterAendern, flaecheOeffnen, fremdesSpeichern, idsUmbenennen, laden as apLaden,
  leer, nachLinks, nachRechts, neuerBildschirm, pruefen, speichern as apSpeichern, umbenennen, verschiebenNach, wechseln, wo,
  type Arbeitsplatz, type Bildschirm,
} from '~/lib/os/bildschirme';
import { AGENT_ID, alleFlaechen, appFlaecheZu, flaecheZu, gruppiert, standardPlaetze, type Flaeche } from '~/lib/os/flaechen';
import { inNeuemTab, osTabMelden, zielAufloesen } from '~/lib/os/allein';
import { abstand, gummiband, kneifen, wischZiel } from '~/lib/os/gesten';
import { kulisseLaden, kulisseSpeichern, type KulisseFarben, type KulisseStil } from '~/lib/os/kulisse';
import { aufraeumen, menue, menueOeffnen, menueZu, mod, modAlt, type MenuePunkt } from '~/lib/os/menue';
import { nativZu } from '~/lib/os/nativ';
import { OEFFNEN, deeplink, eingabeLesen, pfadSchluessel, type OsZiel } from '~/lib/os/oeffnen';
import { fremdesThemaAnwenden, themaSetzen, themaWahl } from '~/lib/os/thema';
import { agentFragen, agentFragenAnbinden } from '~/lib/os/agent-fragen';
import { agentName, agentPfad, konfigurationLaden, systemName } from '~/lib/config';
import { ZEIGT_EREIGNIS, einstellungLesen, einstellungSchreiben, hinzufuegen, istStumm, zeigtPruefen, type Mitteilung } from '~/lib/os/mitteilungen';
import { ausklingen, herkunftMerken, imBlickHalten, insDock } from '~/lib/os/uebergang';
import '~/styles/os-handhabung.css';
import '~/plugins';
import {
  OEFFNE_NACHRICHT, ZUG_NACHRICHT, ablageZiel, aktuellerZug, dingName, dingPfad, frageZu, gutArt, hinweisWeg, istDingTyp, zugBeginnt,
  zugEndet, zugHinweis, zustellen, type Gut, type GutArt,
} from '~/lib/os/ziehen';
import { istAngepinnt } from '~/lib/mcp-apps/pins';

type Platz = { name: string; fenster: Fenster[] };
type Befehl = { aktion: string; flaeche?: string; name?: string; index?: number };

// Nur auf Abruf geladen (Start per ⌘K/Dock, Hilfe, Kontrollzentrum): nicht im ersten Bündel der Shell.
// Kurz nach dem Aufbau wird vorgeladen (onMount), damit das erste Öffnen nicht auf das Netz wartet.
const Start = lazy(() => import('./Start'));
const Hilfe = lazy(() => import('./Hilfe'));
const Kontrollzentrum = lazy(() => import('./Kontrollzentrum'));

const UNTAETIG_MS = 60_000;
const VOLL = `Auf diesem Bildschirm sind schon ${MAX_OFFEN} Flächen offen. Minimiere oder schließe eine, oder nimm einen neuen Bildschirm.`;
const ZU_VIELE = `Mehr als ${BILDSCHIRME_MAX} Bildschirme gehen nicht.`;
const LANGDRUCK_MS = 520;

/** Kann `el` (oder ein Vorfahr bis `bis`) quer scrollen? Dann gehört die Wischgeste ihm. */
function querScrollbar(el: Element | null, bis: Element): boolean {
  for (let e = el; e && e !== bis; e = e.parentElement) {
    const s = getComputedStyle(e);
    if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 1) return true;
  }
  return false;
}

/** Ziele, an denen das Menü des Browsers bleibt (Text bearbeiten, Links, markierter Text). */
function browserMenue(t: Element): boolean {
  if (t.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"], a[href]')) return true;
  const sel = window.getSelection?.();
  return !!sel && !sel.isCollapsed && sel.toString().trim().length > 0;
}

export default function Shell(): JSX.Element {
  const [ap, setAp] = createSignal<Arbeitsplatz>(leer());
  const [appListe, setAppListe] = createSignal<McpApp[]>([]);
  const [start, setStart] = createSignal(false);
  const [suche, setSuche] = createSignal('');
  const [agent, setAgent] = createSignal(false);
  const [agentGeladen, setAgentGeladen] = createSignal(false);
  // Adresse des Agent-Docks: der Chat; mit Entwurf (?draft=), wenn eine Frage ohne Gesprächsweg ankommt
  const [agentAdresse, setAgentAdresse] = createSignal(agentPfad());
  // Zeiger der eingebetteten Seiten aus: beim Größe-Ziehen (eigenes Signal) und solange etwas gezogen wird
  // (lib/os/ziehen.ts — Fenster, Flächen, Objekte; auch aus einer Seite im Fenster heraus).
  const [groesseZieht, setZiehen] = createSignal(false);
  const ziehen = () => groesseZieht() || aktuellerZug() != null;
  const [meldung, setMeldung] = createSignal('');
  /** Meldung, die von selbst wieder geht (vorher blieben Grenz-Meldungen stehen, bis wieder etwas aufging) */
  const kurzMelden = (t: string, ms = 2600) => {
    setMeldung(t);
    setTimeout(() => setMeldung((m) => (m === t ? '' : m)), ms);
  };
  /** Bildschirm-Punkt, der kurz aufleuchtet (etwas ist dort angekommen) */
  const [puls, setPuls] = createSignal<number | null>(null);
  const pulsen = (i: number) => {
    setPuls(i);
    setTimeout(() => setPuls((x) => (x === i ? null : x)), 900);
  };
  const [agentZiel, setAgentZiel] = createSignal(false);
  const [mitt, setMitt] = createSignal<Mitteilung[]>([]);
  const [mittEinst, setMittEinst] = createSignal(einstellungLesen());
  const [mittHinweis, setMittHinweis] = createSignal<Hinweis | null>(null);
  const mittEinstellen = (e: ReturnType<typeof einstellungLesen>) => {
    setMittEinst(e);
    einstellungSchreiben(e);
  };
  const [uhr, setUhr] = createSignal('');
  const [datum, setDatum] = createSignal('');
  const [bereit, setBereit] = createSignal(false);
  const [plaetze, setPlaetze] = createSignal<Platz[]>([]);
  const [vorlageName, setVorlageName] = createSignal('');
  const [vorlageFehler, setVorlageFehler] = createSignal('');
  const [schmal, setSchmal] = createSignal(false);
  const [fokus, setFokus] = createSignal<string | null>(null);
  const [untaetig, setUntaetig] = createSignal(false);
  const [versteckt, setVersteckt] = createSignal(false);
  const [uebersicht, setUebersicht] = createSignal(false);
  const [kz, setKz] = createSignal<number | null>(null);
  const [hilfe, setHilfe] = createSignal(false);
  const [benennen, setBenennen] = createSignal<number | null>(null);
  /** Versatz des Bands beim Wischen in px (0 = in Ruhe) */
  const [zug, setZug] = createSignal(0);
  const [zieht, setZieht] = createSignal(false);
  /** Größe des Bereichs der Bildschirme (für Übersicht und Wischen) */
  const [flaecheGr, setFlaecheGr] = createSignal({ b: 1200, h: 800 });
  // Nur besuchte Bildschirme laufen; ein nie gezeigter lädt keine Fenster.
  const [besucht, setBesucht] = createSignal<ReadonlySet<string>>(new Set());
  let sucheFeld: HTMLInputElement | undefined;
  let wurzel: HTMLDivElement | undefined;
  let bereich: HTMLDivElement | undefined;
  /** Fenstermenü und „Neu verteilen“ je Bildschirm — das Raster meldet sie (es kennt die Maße). */
  const rasterMenue = new Map<string, (id: string) => MenuePunkt[]>();
  const rasterVerteilen = new Map<string, () => void>();
  const bid = (i: number) => bildschirmBei(ap(), i)?.id ?? '';
  /**
   * Das Raster meldet sich an (läuft in seinem Besitz): Eintrag folgt der Bildschirm-ID und geht mit dem Raster.
   * Vorher blieb er unter der ID beim Aufbau stehen, auch wenn der Bildschirm wegging.
   */
  function anmelden<T>(karte: Map<string, T>, b: () => Bildschirm | undefined, wert: T) {
    createEffect(() => {
      const id = b()?.id;
      if (!id) return;
      karte.set(id, wert);
      onCleanup(() => { if (karte.get(id) === wert) karte.delete(id); });
    });
  }

  const flaechen = createMemo(() => alleFlaechen(appListe()));
  const gruppen = createMemo(() => gruppiert(flaechen(), suche()));
  const flaeche = (id: string): Flaeche | undefined =>
    flaecheZu(flaechen(), id) ?? (id === AGENT_ID ? flaechen().find((x) => x.id === AGENT_ID) : undefined);
  /** Name eines Bildschirms, eigener Name oder das, was darauf offen ist. */
  const nameVon = (b: Bildschirm): string => anzeigeName(b, ap().bildschirme.indexOf(b) + 1, (id) => flaeche(id)?.titel);

  const merkeBesucht = (a: Arbeitsplatz) => {
    const b = bildschirmBei(a, a.aktiv);
    if (b && !besucht().has(b.id)) setBesucht(new Set([...besucht(), b.id]));
  };
  const setze = (neu: Arbeitsplatz) => {
    setAp(neu);
    merkeBesucht(neu);
    if (bereit()) apSpeichern(neu);
  };
  const aktiv = () => ap().aktiv;
  const bildschirme = createMemo(() =>
    ap().bildschirme.map((b, i) => ({ index: i + 1, name: nameVon(b), anzahl: b.fenster.filter((w) => !w.min).length })),
  );
  const bildschirmNamen = createMemo(() => bildschirme().map(({ index, name }) => ({ index, name })));

  /** Dock-Symbol, das gerade hüpft (ein Fenster ist neu aufgegangen, wie am Mac beim Start einer App) */
  const [huepf, setHuepf] = createSignal<string | null>(null);
  const oeffne = (id: string, vor?: string | null, startZustand?: StartZustand, sonstNeu = false) => {
    const fl = flaeche(id);
    if (!fl) return;
    // Fremde Dienste (Gruppe „Extern“) haben kein Fenster: neuer Tab.
    if (fl.extern) {
      inNeuemTab(fl);
      setStart(false);
      setUebersicht(false);
      return;
    }
    const neu = wo(ap(), id) < 1;
    const r = flaecheOeffnen(ap(), id, { vor, breit: flaeche(id)?.breit, start: startZustand, sonstNeu });
    if (r.voll) kurzMelden(VOLL, 6000);
    else setMeldung('');
    setze(r.ap);
    if (!r.voll) setFokus(id);
    if (neu && !r.voll) {
      setHuepf(id);
      setTimeout(() => setHuepf((h) => (h === id ? null : h)), 900);
    }
    setStart(false);
    setUebersicht(false);
  };
  /** Minimieren, Schließen, Wiederherstellen mit Übergang (lib/os/uebergang.ts): ins Dock und von dort zurück. */
  const fensterMinimieren = (id: string) =>
    insDock(id, () => { const i = wo(ap(), id); if (i >= 1) setze(fensterAendern(ap(), i, (l) => minimieren(l, id))); });
  const fensterSchliessen = (id: string) =>
    ausklingen(id, () => { const i = wo(ap(), id); if (i >= 1) setze(fensterAendern(ap(), i, (l) => schliessen(l, id))); });
  const fensterHolen = (id: string) => {
    const i = wo(ap(), id);
    if (i < 1) return;
    herkunftMerken(id);
    setze(fensterAendern(ap(), i, (l) => l.map((x) => (x.id === id ? { ...x, min: false } : x))));
    setFokus(id);
  };
  /**
   * Übergänge ins OS (lib/os/oeffnen.ts): `ziel` ist eine Fläche (`app:…`, `seite:…`), bei Apps auch ein Werkzeug
   * mit derselben Oberfläche, oder der Pfad einer Seite. Mit `eingabe` startet die App genau so (nur lesende
   * Werkzeuge — das prüft AppEingebettet). true = geöffnet; false = dafür gibt es hier keine Fläche.
   */
  const oeffneZiel = (ziel: string, eingabe?: Record<string, unknown>): boolean => {
    const t = zielAufloesen(flaechen(), ziel, eingabe);
    if (!t) return false;
    oeffne(t.f.id, null, t.start, true);
    return true;
  };
  const neuerBildschirmAn = () => {
    const vorher = ap();
    const neu = neuerBildschirm(vorher);
    if (neu === vorher) {
      kurzMelden(ZU_VIELE);
      return;
    }
    setze(neu);
  };
  const fensterAufNeuenBildschirm = (fensterId: string) => {
    const mit = neuerBildschirm(ap());
    if (mit === ap()) return;
    setze(verschiebenNach(mit, fensterId, mit.aktiv));
  };
  const aufNeuemBildschirmOeffnen = (id: string) => {
    if (!flaeche(id)) return;
    if (flaeche(id)!.extern) return oeffne(id);
    const i = wo(ap(), id);
    let basis = ap();
    if (i >= 1) basis = fensterAendern(basis, i, (l) => l.filter((x) => x.id !== id));
    const neu = neuerBildschirm(basis, undefined, [{ id, min: false }]);
    if (neu === basis) {
      kurzMelden(ZU_VIELE);
      return;
    }
    setze(neu);
    setFokus(id);
    setStart(false);
  };
  const gehe = (i: number) => {
    setze(wechseln(ap(), i));
    setUebersicht(false);
  };

  // ── Ablegen (lib/os/ziehen.ts): jedes Ziel versteht Fenster, Flächen und Dinge ──────────────────
  /** Die Fläche, auf der ein Ding lebt (registriert über `dinge` in registriereFlaechen). */
  const dingFlaeche = (typ: string): Flaeche | undefined => {
    const pf = dingPfad(typ);
    return pf ? flaechen().find((x) => x.pfad && pfadSchluessel(x.pfad) === pfadSchluessel(pf)) : undefined;
  };
  /** Eine Fläche öffnen — auf dem aktuellen, einem bestimmten oder einem neuen Bildschirm. */
  const flaecheAuf = (id: string, ort: { index?: number | 'neu'; vor?: string | null } = {}) => {
    if (ort.index === 'neu') return aufNeuemBildschirmOeffnen(id);
    // Schon offen? Dann holt `oeffne` sie dort nach vorn; sonst erst auf den Zielbildschirm
    if (ort.index != null && ort.index >= 1 && ort.index !== aktiv() && wo(ap(), id) < 1) setze(wechseln(ap(), ort.index));
    oeffne(id, ort.vor ?? null);
    const i = wo(ap(), id);
    if (i >= 1 && ort.index != null) pulsen(i);
  };
  /** Ein Ding zeigen: seine Fläche öffnen und ihr sagen, welches (es springt dort auf). */
  const dingZeigen = (g: Extract<Gut, { art: 'ding' }>, ort: { index?: number | 'neu'; vor?: string | null } = {}) => {
    const f = dingFlaeche(g.typ);
    if (!f) {
      kurzMelden(`Für ${dingName(g.typ)} gibt es im OS keine Fläche.`);
      return;
    }
    flaecheAuf(f.id, ort);
    zustellen(f.id, { [OEFFNE_NACHRICHT]: { typ: g.typ, id: g.id } });
  };
  /** Abgelegt auf einem Bildschirm-Punkt, einer Karte der Übersicht oder „+" (neu). */
  const ablegenAuf = (index: number | 'neu', g: Gut) => {
    if (g.art === 'fenster') {
      if (index === 'neu') return fensterAufNeuenBildschirm(g.id);
      if (index < 1 || wo(ap(), g.id) === index) return;
      setze(verschiebenNach(ap(), g.id, index));
      setFokus(g.id);
      pulsen(index);
      return;
    }
    if (g.art === 'flaeche') flaecheAuf(g.id, { index });
    else dingZeigen(g, { index });
  };
  /** Abgelegt auf dem Agent: dazu fragen (Apps mit ihrer Ansicht als Kontext, wie „Agent fragen" im Kopf). */
  const fragenZuGut = (g: Gut) => {
    if (g.art !== 'ding') {
      const f = flaeche(g.id);
      const i = wo(ap(), g.id);
      const start = i >= 1 ? bildschirmBei(ap(), i)?.fenster.find((x) => x.id === g.id)?.start : undefined;
      if (f?.art === 'hubapp') appFragen(f, start);
      else agentFragen({ text: frageZu(g, f?.titel), quelle: 'ziehen' });
      return;
    }
    agentFragen({ text: frageZu(g), quelle: 'ziehen' });
  };
  const agentAblage = ablageZiel({ ziel: 'agent', ablegen: fragenZuGut, an: setAgentZiel });

  // ── Vorlagen (früher „Arbeitsplätze“): öffnen einen eigenen Bildschirm ────────────────────────
  const plaetzeLaden = async () => {
    try {
      setPlaetze((await hub<{ plaetze: Platz[] }>('shell.plaetze')).plaetze ?? []);
    } catch {
      /* Hub weg: nur die vorgegebenen */
    }
  };
  const vorlagen = createMemo<Vorlage[]>(
    () => [
      ...standardPlaetze().map((p) => ({
        name: p.name,
        fenster: p.ids.filter((id) => flaeche(id)).map((id) => ({ id, min: false })),
        eigene: false,
      })).filter((p) => !plaetze().some((x) => x.name === p.name) && p.fenster.length > 0),
      ...plaetze().map((p) => ({ ...p, eigene: true })),
    ],
    [],
    { equals: (a, b) => JSON.stringify(a) === JSON.stringify(b) },
  );
  const vorlageOeffnen = (v: { name: string; fenster: Fenster[] }) => {
    const da = ap().bildschirme.findIndex((b) => b.name === v.name);
    if (da >= 0) {
      gehe(da + 1);
      setStart(false);
      return;
    }
    const ok = v.fenster.filter((w) => flaeche(w.id));
    // Flächen, die schon anderswo offen sind, ziehen auf den neuen Bildschirm um.
    let basis = ap();
    for (const w of ok) {
      const i = wo(basis, w.id);
      if (i >= 1) basis = fensterAendern(basis, i, (l) => l.filter((x) => x.id !== w.id));
    }
    const neu = neuerBildschirm(basis, v.name, ok.map((w) => ({ ...w, min: false })));
    if (neu === basis) {
      kurzMelden(ZU_VIELE);
      return;
    }
    setze(neu);
    setFokus(ok[0]?.id ?? null);
    setStart(false);
    setUebersicht(false);
  };
  const vorlageSpeichern = async () => {
    setVorlageFehler('');
    const b = aktueller(ap());
    if (!b) return;
    try {
      await hub('shell.platz_speichern', { name: vorlageName().trim(), fenster: b.fenster }, { art: 'bewusst' });
      setVorlageName('');
      await plaetzeLaden();
    } catch (e) {
      setVorlageFehler(e instanceof Error ? e.message : String(e));
    }
  };
  const vorlageEntfernen = async (name: string) => {
    try {
      await hub('shell.platz_entfernen', { name }, { art: 'bewusst' });
      await plaetzeLaden();
    } catch {
      /* bleibt stehen */
    }
  };
  const oeffneStart = () => {
    setStart(true);
    setUebersicht(false);
    setSuche('');
    void plaetzeLaden();
    queueMicrotask(() => sucheFeld?.focus());
    // Start wird auf Abruf geladen: ist das Bündel beim ersten Öffnen noch nicht da, den Fokus nachholen.
    void Start.preload().then(() => setTimeout(() => { if (start() && sucheFeld && !(document.activeElement instanceof HTMLInputElement)) sucheFeld.focus(); }, 0));
  };
  const toggleAgent = () => {
    setAgent((a) => !a);
    setAgentGeladen(true);
  };
  const einstellungenDa = () => !!nativZu('nativ:einstellungen');
  const einstellungen = () => {
    if (einstellungenDa()) oeffne('nativ:einstellungen');
  };

  // ── Befehle des Agenten (Hub-Werkzeug shell.befehl) — nur, was die Shell sowieso darf ──────────
  const befehlAnwenden = (b: Befehl) => {
    if (b.aktion === 'platz' && b.name) {
      void hub<{ plaetze: Platz[] }>('shell.plaetze')
        .then((r) => {
          const eigen = (r.plaetze ?? []).find((x) => x.name === b.name);
          const v = eigen ?? vorlagen().find((x) => x.name === b.name);
          if (v) vorlageOeffnen(v);
        })
        .catch(() => {});
      return;
    }
    if (b.aktion === 'bildschirm') {
      const i = typeof b.index === 'number' ? b.index : ap().bildschirme.findIndex((x) => x.name === b.name) + 1;
      if (i === START || bildschirmBei(ap(), i)) setze(wechseln(ap(), i));
      return;
    }
    if (!b.flaeche) return;
    if (b.flaeche === AGENT_ID) {
      if (b.aktion === 'oeffnen' || b.aktion === 'wiederherstellen') {
        setAgent(true);
        setAgentGeladen(true);
      } else setAgent(false);
      return;
    }
    if (!flaeche(b.flaeche)) return; // gibt es nicht (mehr) — still übergehen
    const id = b.flaeche;
    const i = wo(ap(), id);
    if (b.aktion === 'oeffnen' || b.aktion === 'wiederherstellen') oeffne(id);
    else if (b.aktion === 'schliessen' && i >= 1) fensterSchliessen(id);
    else if (b.aktion === 'minimieren' && i >= 1) fensterMinimieren(id);
  };

  // ── Menüs: was wo angeboten wird ─────────────────────────────────────────────────────────────
  const erscheinungPunkte = (): MenuePunkt[] => {
    const w = themaWahl();
    return [
      { text: 'Hell', an: w === 'light', tun: () => themaSetzen('light') },
      { text: 'Dunkel', an: w === 'dark', tun: () => themaSetzen('dark') },
      { text: 'Automatisch', an: w === 'auto', tun: () => themaSetzen('auto') },
    ];
  };
  const hintergrundPunkte = (): MenuePunkt[] => {
    const k = kulisseLaden();
    const stil = (s: KulisseStil, text: string): MenuePunkt => ({ text, an: k.stil === s, tun: () => kulisseSpeichern({ ...kulisseLaden(), stil: s }) });
    const farbe = (f: KulisseFarben, text: string): MenuePunkt => ({ text, an: k.farben === f, tun: () => kulisseSpeichern({ ...kulisseLaden(), farben: f }) });
    return [stil('lava', 'Lava'), stil('ruhig', 'Ruhig'), stil('aus', 'Aus'), { art: 'trenner' }, farbe('neon', 'Neon'), farbe('aurora', 'Aurora'), farbe('glut', 'Glut')];
  };
  const fensterVon = (i: number) => bildschirmBei(ap(), i)?.fenster ?? [];
  const verteilen = (i: number) => {
    const fn = rasterVerteilen.get(bid(i));
    if (fn) fn();
    else setze(fensterAendern(ap(), i, automatisch));
  };
  const bildschirmLoeschen = (i: number) => setze(entfernen(ap(), i));
  const umbenennenAn = (i: number) => {
    if (i < 1) return;
    gehe(i);
    setBenennen(i);
  };

  /** Rechtsklick auf freie Fläche: was man mit dem Bildschirm und dem OS tun kann. */
  const schreibtischPunkte = (): MenuePunkt[] => {
    const i = aktiv();
    const l = fensterVon(i);
    return [
      { text: 'Neue Fläche …', kuerzel: mod('K'), tun: oeffneStart },
      { text: 'Neuer Bildschirm', tun: neuerBildschirmAn },
      { text: 'Übersicht', kuerzel: modAlt('↑'), tun: () => setUebersicht(true) },
      { art: 'trenner' },
      { text: 'Fenster neu verteilen', aus: i === START || l.filter((w) => !w.min).length < 2, tun: () => verteilen(i) },
      { text: 'Alle minimieren', aus: i === START || !l.some((w) => !w.min), tun: () => setze(fensterAendern(ap(), i, (x) => x.map((w) => ({ ...w, min: true })))) },
      { text: 'Alle einblenden', aus: i === START || !l.some((w) => w.min), tun: () => {
        const r = alleEinblenden(fensterVon(i));
        setze(fensterAendern(ap(), i, () => r.liste));
        if (r.rest) kurzMelden(`${MAX_OFFEN} Flächen sind offen, ${r.rest} ${r.rest === 1 ? 'bleibt' : 'bleiben'} im Dock.`, 4000);
      } },
      { art: 'trenner' },
      ...(i === START ? [] : bildschirmEigenePunkte(i)),
      { art: 'trenner' },
      { art: 'unter', text: 'Erscheinungsbild', punkte: erscheinungPunkte() },
      { art: 'unter', text: 'Hintergrund', punkte: hintergrundPunkte() },
      { text: 'Einstellungen …', kuerzel: mod(','), aus: !einstellungenDa(), tun: einstellungen },
    ];
  };
  const bildschirmEigenePunkte = (i: number): MenuePunkt[] => [
    { text: 'Bildschirm umbenennen …', tun: () => umbenennenAn(i) },
    { text: 'Als Vorlage sichern …', tun: () => { gehe(i); oeffneStart(); } },
    { text: 'Alle Fenster schließen', aus: !fensterVon(i).length, tun: () => setze(fensterAendern(ap(), i, () => [])) },
    { text: 'Bildschirm schließen', gefahr: true, tun: () => bildschirmLoeschen(i) },
  ];
  /** Rechtsklick auf einen Bildschirm-Punkt oder den Namen eines Bildschirms. */
  const bildschirmPunkte = (i: number): MenuePunkt[] => [
    // Überschrift = welcher Bildschirm (statt eines ausgegrauten „Angezeigt“); „Anzeigen“ nur für die anderen
    { art: 'titel', text: (i === START ? 'Start' : bildschirmNamen().find((b) => b.index === i)?.name ?? 'Bildschirm') + (i === aktiv() ? ' · hier' : '') },
    ...(i === aktiv() ? [] : [{ text: 'Anzeigen', tun: () => gehe(i) }]),
    { text: 'Übersicht', kuerzel: modAlt('↑'), tun: () => setUebersicht(true) },
    { art: 'trenner' },
    ...(i === START ? [{ text: 'Neuer Bildschirm', tun: neuerBildschirmAn }] : bildschirmEigenePunkte(i)),
  ];
  /** Menü eines Fensters auf dem aktuellen Bildschirm (vom Raster), sonst das Nötigste. */
  const fensterPunkte = (id: string): MenuePunkt[] => {
    const i = wo(ap(), id);
    const w = fensterVon(i).find((x) => x.id === id);
    const f = flaeche(id);
    if (!w || !f) return [];
    if (w.min) {
      return [
        { text: 'Wiederherstellen', symbol: 'maximize-2', tun: () => fensterHolen(id) },
        { art: 'trenner' },
        { text: 'In neuem Tab öffnen', symbol: 'external-link', tun: () => inNeuemTab(f, w.start) },
        { text: 'Schließen', symbol: 'x', tun: () => fensterSchliessen(id) },
      ];
    }
    const bau = rasterMenue.get(bid(i));
    if (bau) return bau(id);
    return [
      { text: 'Minimieren', symbol: 'minus', tun: () => fensterMinimieren(id) },
      { text: 'Neu laden', symbol: 'rotate-cw', tun: () => window.dispatchEvent(new CustomEvent(NEU_LADEN, { detail: id })) },
      { text: 'Schließen', symbol: 'x', tun: () => fensterSchliessen(id) },
    ];
  };
  /** Rechtsklick auf eine Kachel im Start. */
  const flaechePunkte = (id: string): MenuePunkt[] => {
    const f = flaeche(id);
    if (!f) return [];
    const offen = wo(ap(), id) >= 1;
    const geheftet = !!f.appName && istAngepinnt(f.appName);
    return [
      { text: offen ? 'Zeigen' : 'Öffnen', symbol: 'app-window', tun: () => oeffne(id) },
      { text: 'Auf neuem Bildschirm öffnen', symbol: 'monitor-up', tun: () => aufNeuemBildschirmOeffnen(id) },
      { text: 'In neuem Tab öffnen', symbol: 'external-link', tun: () => inNeuemTab(f) },
      { text: 'Link kopieren', symbol: 'link', tun: () => void navigator.clipboard?.writeText(deeplink(id)).catch(() => {}) },
      ...(kannHeften(f)
        ? [{ art: 'trenner' as const }, { text: geheftet ? 'Vom Start lösen' : 'An den Start heften', symbol: geheftet ? 'pin-off' : 'pin', tun: () => void heften(f) }]
        : []),
    ];
  };

  /** `data-kontext` des Ziels → Menü. null = das Menü des Browsers bleibt. */
  const kontextPunkte = (ziel: Element): MenuePunkt[] | null => {
    if (browserMenue(ziel)) return null;
    const k = ziel.closest<HTMLElement>('[data-kontext]')?.dataset.kontext;
    if (!k || k === 'inhalt') return null;
    const [art, ...rest] = k.split(':');
    const wert = rest.join(':');
    if (art === 'fenster' || art === 'dock-fenster') return fensterPunkte(wert);
    if (art === 'bildschirm') return bildschirmPunkte(Number(wert));
    if (art === 'flaeche') return flaechePunkte(wert);
    return schreibtischPunkte();
  };
  let zuletztMenue = 0;
  const kontextAn = (ziel: Element, x: number, y: number): boolean => {
    const punkte = kontextPunkte(ziel);
    if (!punkte) return false;
    zuletztMenue = Date.now();
    menueOeffnen({ x, y, punkte });
    return true;
  };

  /** Die Menüs der Menüleiste. */
  const leistenMenues: LeistenMenue[] = [
    {
      id: 'system',
      text: systemName(),
      punkte: () => [
        { text: 'Einstellungen …', kuerzel: mod(','), aus: !einstellungenDa(), tun: einstellungen },
        { text: 'Kontrollzentrum', tun: () => setKz(12) },
        { art: 'trenner' },
        { text: 'Alle Flächen …', kuerzel: mod('K'), tun: oeffneStart },
        { text: 'Übersicht', kuerzel: modAlt('↑'), tun: () => setUebersicht(true) },
        { art: 'trenner' },
        // Am Handy ist die Menüleiste auf das Systemmenü gekürzt (Menü „Hilfe" ist dort ausgeblendet): Hilfe hier erreichbar.
        { text: 'Hilfe: Tastenkürzel und Gesten', kuerzel: mod('/'), tun: () => setHilfe(true) },
        { art: 'trenner' },
        { text: 'OS neu laden', tun: () => location.reload() },
      ],
    },
    {
      id: 'ablage',
      text: 'Ablage',
      punkte: () => [
        { text: 'Neue Fläche …', kuerzel: mod('K'), tun: oeffneStart },
        { text: 'Neuer Bildschirm', tun: neuerBildschirmAn },
        { art: 'trenner' },
        { art: 'unter', text: 'Vorlage öffnen', punkte: vorlagen().map((v) => ({ text: v.name, tun: () => vorlageOeffnen(v) })) },
        { text: 'Bildschirm als Vorlage sichern …', aus: !aktueller(ap())?.fenster.length, tun: oeffneStart },
        { art: 'trenner' },
        { text: 'Fenster schließen', aus: !fokus() || wo(ap(), fokus()!) < 1, tun: () => fensterSchliessen(fokus()!) },
        { text: 'Bildschirm schließen', aus: aktiv() === START, gefahr: true, tun: () => bildschirmLoeschen(aktiv()) },
      ],
    },
    {
      id: 'darstellung',
      text: 'Darstellung',
      punkte: () => [
        { text: 'Übersicht', kuerzel: modAlt('↑'), an: uebersicht(), tun: () => setUebersicht((u) => !u) },
        { text: 'Vorheriger Bildschirm', kuerzel: modAlt('←'), aus: aktiv() === START, tun: () => setze(nachLinks(ap())) },
        { text: 'Nächster Bildschirm', kuerzel: modAlt('→'), aus: aktiv() >= ap().bildschirme.length, tun: () => setze(nachRechts(ap())) },
        {
          art: 'unter',
          text: 'Gehe zu',
          punkte: [{ index: 0, name: 'Start' }, ...bildschirmNamen()].map((b) => ({ text: b.name, an: aktiv() === b.index, kuerzel: b.index < 9 ? modAlt(String(b.index + 1)) : undefined, tun: () => gehe(b.index) })),
        },
        { art: 'trenner' },
        { text: 'Fenster neu verteilen', aus: aktiv() === START || fensterVon(aktiv()).filter((w) => !w.min).length < 2, tun: () => verteilen(aktiv()) },
        { text: agentName(), kuerzel: mod('J'), an: agent(), tun: toggleAgent },
        { art: 'trenner' },
        { art: 'unter', text: 'Erscheinungsbild', punkte: erscheinungPunkte() },
        { art: 'unter', text: 'Hintergrund', punkte: hintergrundPunkte() },
      ],
    },
    {
      id: 'fenster',
      text: 'Fenster',
      punkte: () => {
        const id = fokus();
        const eigen = id && wo(ap(), id) === aktiv() ? fensterPunkte(id) : [];
        // Je Bildschirm eine Überschrift, darunter seine Fenster; minimierte gedimmt benannt.
        const mehrere = ap().bildschirme.filter((b) => b.fenster.some((w) => flaeche(w.id))).length > 1;
        const alle: MenuePunkt[] = ap().bildschirme.flatMap((b, j): MenuePunkt[] => {
          const liste = b.fenster.filter((w) => flaeche(w.id));
          if (!liste.length) return [];
          return [
            ...(mehrere ? [{ art: 'titel' as const, text: j + 1 === aktiv() ? `${nameVon(b)} · hier` : nameVon(b) }] : []),
            ...liste.map((w) => ({
              text: w.min ? `${flaeche(w.id)!.titel} (minimiert)` : flaeche(w.id)!.titel,
              an: w.id === id && j + 1 === aktiv(),
              tun: () => {
                if (w.min) setze(fensterAendern(ap(), j + 1, (l) => l.map((x) => (x.id === w.id ? { ...x, min: false } : x))));
                gehe(j + 1);
                setFokus(w.id);
              },
            })),
          ];
        });
        return aufraeumen([...eigen, { art: 'trenner' }, ...(alle.length ? alle : [{ text: 'Keine Fenster offen', aus: true, tun: () => {} }])]);
      },
    },
    {
      id: 'hilfe',
      text: 'Hilfe',
      punkte: () => [
        { text: 'Tastenkürzel und Gesten', kuerzel: mod('/'), tun: () => setHilfe(true) },
        { text: 'Was lässt sich wohin ziehen?', tun: () => setHilfe(true) },
      ],
    },
  ];

  // ── Abfragen: sparsam (ein lange offenes OS soll nicht träge werden) ─────────────────────────
  const abholen = async () => {
    try {
      const r = await hub<{ befehle: Befehl[] }>('shell.abholen');
      for (const b of r.befehle ?? []) befehlAnwenden(b);
    } catch {
      /* Hub weg — die Shell läuft allein weiter */
    }
  };

  // ── Wischen: Trackpad und Finger, das Band folgt ─────────────────────────────────────────────
  let wisch = { an: false, versatz: 0, zeit: 0, tempo: 0 };
  let wischEnde: ReturnType<typeof setTimeout> | undefined;
  let wischSperre = 0;
  const kannLinks = () => aktiv() > START;
  const kannRechts = () => aktiv() < ap().bildschirme.length;
  const ziehenAuf = (versatz: number) => setZug(gummiband(versatz, flaecheGr().b, kannLinks(), kannRechts()));
  const loslassen = () => {
    const ziel = wischZiel(zug(), flaecheGr().b, wisch.tempo, kannLinks(), kannRechts());
    wisch = { an: false, versatz: 0, zeit: 0, tempo: 0 };
    setZieht(false);
    setZug(0);
    if (ziel === -1) setze(nachLinks(ap()));
    else if (ziel === 1) setze(nachRechts(ap()));
    if (ziel) wischSperre = Date.now() + 450;
  };
  let kneifSumme = 0;
  let kneifZeit = 0;
  let kneifSperre = 0;
  const kneifAnwenden = (r: 'zu' | 'auf' | null) => {
    if (!r) return;
    kneifSumme = 0;
    kneifSperre = Date.now() + 600;
    if (r === 'zu' && !uebersicht()) setUebersicht(true);
    else if (r === 'auf' && uebersicht()) setUebersicht(false);
  };
  /**
   * Ein Rad-Schritt vom Trackpad — direkt (`rad`) oder aus einem Fenster weitergereicht (BaseLayout,
   * `fyosRad`): dort hat die Seite schon geprüft, dass sie selbst nicht quer scrollt.
   */
  const radSchritt = (deltaX: number, deltaY: number, ctrl: boolean, ziel: Element | null, verhindern: () => void) => {
    if (!wurzel) return;
    const jetzt = Date.now();
    // Kneifen auf dem Trackpad (Chrome, Firefox, Edge): wheel mit ctrlKey — sonst zoomt die Seite.
    if (ctrl) {
      verhindern();
      if (jetzt < kneifSperre) return;
      if (jetzt - kneifZeit > 300) kneifSumme = 0;
      kneifZeit = jetzt;
      kneifSumme += deltaY;
      kneifAnwenden(kneifen(kneifSumme));
      return;
    }
    if (uebersicht() || start() || schmal()) return;
    const quer = Math.abs(deltaX) > Math.abs(deltaY);
    if (!wisch.an && (!quer || Math.abs(deltaX) < 1.5)) return;
    if (!wisch.an && ziel && querScrollbar(ziel, wurzel)) return;
    if (jetzt < wischSperre) {
      verhindern(); // Nachlauf des letzten Wischens schlucken
      return;
    }
    verhindern();
    const dt = Math.max(1, jetzt - (wisch.zeit || jetzt - 16));
    const dx = -deltaX;
    wisch = { an: true, versatz: wisch.versatz + dx, zeit: jetzt, tempo: dx / dt };
    setZieht(true);
    ziehenAuf(wisch.versatz);
    clearTimeout(wischEnde);
    wischEnde = setTimeout(loslassen, 110);
  };
  const rad = (e: WheelEvent) => radSchritt(e.deltaX, e.deltaY, e.ctrlKey && !e.metaKey, e.target as Element, () => e.preventDefault());
  const nachricht = (e: MessageEvent) => {
    // Nur Seiten in den eigenen Fenstern (gleicher Ursprung UND eines unserer iframes) dürfen ziehen, wischen, Kürzel geben
    if (e.origin !== location.origin || !e.source || ![...(wurzel?.querySelectorAll('iframe') ?? [])].some((f) => f.contentWindow === e.source)) return;
    // Eine Seite im Fenster zieht etwas (ZUG_NACHRICHT): Zeiger der anderen Fenster aus, Ziele an
    const z = (e.data as { [ZUG_NACHRICHT]?: unknown } | null)?.[ZUG_NACHRICHT];
    if (z === null) {
      zugEndet();
      hinweisWeg();
    } else if (typeof z === 'string' && (z === 'fenster' || z === 'flaeche' || istDingTyp(z))) {
      zugBeginnt({ art: z as GutArt, quelle: e.source });
    }
    const r = (e.data as { fyosRad?: { dx: number; dy: number; ctrl: boolean } } | null)?.fyosRad;
    if (r && typeof r.dx === 'number' && typeof r.dy === 'number') radSchritt(r.dx, r.dy, !!r.ctrl, null, () => {});
    // Kürzel des OS, während der Fokus in einem Fenster liegt (BaseLayout reicht nur die des OS weiter)
    const k = (e.data as { fyosTaste?: { key: string; code: string; meta: boolean; ctrl: boolean; alt: boolean; shift: boolean } } | null)?.fyosTaste;
    if (k && typeof k.key === 'string' && typeof k.code === 'string') {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: k.key, code: k.code, metaKey: !!k.meta, ctrlKey: !!k.ctrl, altKey: !!k.alt, shiftKey: !!k.shift, cancelable: true }));
    }
  };

  // Finger: ein Finger wischt (sobald klar waagrecht), zwei kneifen, lange drücken öffnet das Menü.
  const finger = new Map<number, { x: number; y: number; x0: number; y0: number; t0: number }>();
  let fingerAchse: 'quer' | 'hoch' | null = null;
  let fingerStart = 0;
  let langdruck: ReturnType<typeof setTimeout> | undefined;
  let klickSchlucken = false;
  const fingerRunter = (e: PointerEvent) => {
    if (e.pointerType !== 'touch' || !wurzel) return;
    finger.set(e.pointerId, { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, t0: Date.now() });
    clearTimeout(langdruck);
    if (finger.size === 1) {
      fingerAchse = querScrollbar(e.target as Element, wurzel) ? 'hoch' : null;
      const ziel = e.target as Element;
      const { clientX: x, clientY: y } = e;
      langdruck = setTimeout(() => {
        if (finger.size !== 1 || fingerAchse === 'quer' || Date.now() - zuletztMenue < 700) return;
        if (kontextAn(ziel, x, y)) {
          klickSchlucken = true;
          navigator.vibrate?.(8);
        }
      }, LANGDRUCK_MS);
    } else if (finger.size === 2) {
      const [a, b] = [...finger.values()];
      fingerStart = abstand(a!, b!);
      if (wisch.an) loslassen();
    }
  };
  const fingerBewegt = (e: PointerEvent) => {
    const f = finger.get(e.pointerId);
    if (!f) return;
    const jetzt = Date.now();
    const dt = Math.max(1, jetzt - (wisch.zeit || f.t0));
    const vorherX = f.x;
    f.x = e.clientX;
    f.y = e.clientY;
    if (Math.hypot(f.x - f.x0, f.y - f.y0) > 8) clearTimeout(langdruck);
    if (finger.size === 2) {
      const [a, b] = [...finger.values()];
      if (fingerStart > 0) {
        const v = abstand(a!, b!) / fingerStart;
        if (v < 0.72) kneifAnwenden('zu');
        else if (v > 1.35) kneifAnwenden('auf');
      }
      return;
    }
    if (finger.size !== 1 || uebersicht() || start()) return;
    const dx = f.x - f.x0;
    const dy = f.y - f.y0;
    if (!fingerAchse && Math.hypot(dx, dy) > 10) fingerAchse = Math.abs(dx) > Math.abs(dy) * 1.2 ? 'quer' : 'hoch';
    if (fingerAchse !== 'quer') return;
    wisch = { an: true, versatz: dx, zeit: jetzt, tempo: (f.x - vorherX) / dt };
    setZieht(true);
    ziehenAuf(dx);
  };
  const fingerHoch = (e: PointerEvent) => {
    if (!finger.has(e.pointerId)) return;
    finger.delete(e.pointerId);
    clearTimeout(langdruck);
    // Der Klick zum Loslassen kommt gleich danach; bleibt er aus, darf der nächste Tap nicht verschluckt werden
    if (klickSchlucken) setTimeout(() => (klickSchlucken = false), 400);
    if (finger.size === 0) {
      if (wisch.an && fingerAchse === 'quer') loslassen();
      fingerAchse = null;
      fingerStart = 0;
    }
  };

  onMount(() => {
    void konfigurationLaden();
    const vorladen = setTimeout(() => { void Start.preload(); void Hilfe.preload(); void Kontrollzentrum.preload(); }, 2500);
    onCleanup(() => clearTimeout(vorladen));
    const tick = () => {
      const d = new Date();
      setUhr(d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }));
      setDatum(d.toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' }));
    };
    tick();
    let letzte = Date.now();
    const aktivitaet = () => {
      letzte = Date.now();
      if (untaetig()) setUntaetig(false);
    };
    const sichtbarkeit = () => setVersteckt(document.visibilityState === 'hidden');
    sichtbarkeit();
    let takt = 0;
    const t1 = setInterval(() => {
      tick();
      setUntaetig(Date.now() - letzte > UNTAETIG_MS);
    }, 15_000);
    // Befehle: alle 3 s, untätig alle 15 s, im Hintergrund-Tab gar nicht.
    const t2 = setInterval(() => {
      if (versteckt()) return;
      takt += 1;
      if (untaetig() && takt % 5 !== 0) return;
      void abholen();
    }, 3_000);
    const ereignisse = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;
    for (const ev of ereignisse) window.addEventListener(ev, aktivitaet, { passive: true });
    let bewegt = 0;
    const zeiger = () => {
      const j = Date.now();
      if (j - bewegt > 2000) {
        bewegt = j;
        aktivitaet();
      }
    };
    window.addEventListener('pointermove', zeiger, { passive: true });
    document.addEventListener('visibilitychange', sichtbarkeit);

    const mq = typeof window.matchMedia === 'function' ? window.matchMedia('(max-width: 767px)') : null;
    if (mq) {
      setSchmal(mq.matches);
      const mqAendert = (e: MediaQueryListEvent) => setSchmal(e.matches);
      mq.addEventListener('change', mqAendert);
      onCleanup(() => mq.removeEventListener('change', mqAendert));
    }

    // Größe des Bereichs: Übersicht und Wischen rechnen damit.
    if (bereich && typeof ResizeObserver === 'function') {
      const ro = new ResizeObserver(([e]) => {
        const r = e!.contentRect;
        if (r.width > 0 && r.height > 0) setFlaecheGr({ b: r.width, h: r.height });
      });
      ro.observe(bereich);
      onCleanup(() => ro.disconnect());
    }
    // Rad und Kneifen brauchen preventDefault (sonst zoomt bzw. blättert der Browser zurück).
    wurzel?.addEventListener('wheel', rad, { passive: false });
    window.addEventListener('message', nachricht);
    onCleanup(() => window.removeEventListener('message', nachricht));
    // Ziehen: ein Zug von außen (App ohne Meldung) wird beim ersten Betreten erkannt; nach dem Ende (dragend, drop,
    // oder der erste Zeigerzug ohne Taste, falls die Quelle verschwand — der Start schließt sich beim Ziehen) aufräumen.
    const zugVonAussen = (e: DragEvent) => {
      if (aktuellerZug()) return;
      const art = gutArt(e.dataTransfer);
      if (art) zugBeginnt({ art });
    };
    const zugVorbei = () => {
      zugEndet();
      hinweisWeg();
    };
    const nachDemAblegen = () => setTimeout(zugVorbei, 0);
    const zeigerFrei = (e: PointerEvent) => {
      if (aktuellerZug() && e.buttons === 0) zugVorbei();
    };
    window.addEventListener('dragenter', zugVonAussen, true);
    window.addEventListener('dragend', zugVorbei, true);
    window.addEventListener('drop', nachDemAblegen, true);
    window.addEventListener('pointermove', zeigerFrei, true);
    onCleanup(() => {
      window.removeEventListener('dragenter', zugVonAussen, true);
      window.removeEventListener('dragend', zugVorbei, true);
      window.removeEventListener('drop', nachDemAblegen, true);
      window.removeEventListener('pointermove', zeigerFrei, true);
    });
    // Fragen aus Apps, Seiten und Objekten gehen ins gemeinsame Gespräch; das Dock zeigt es.
    onCleanup(agentFragenAnbinden({ zeigen: (adresse) => { setAgent(true); setAgentGeladen(true); if (adresse) setAgentAdresse(adresse); } }));
    // Mitteilungen: eine Quelle meldet sich mit dem Fensterereignis `fyos:zeigt` (lib/os/mitteilungen.ts).
    const zeigtHoerer = (e: Event) => {
      const z = zeigtPruefen((e as CustomEvent).detail);
      if (!z || istStumm(mittEinst(), Date.now()) || !flaeche(z.ziel)) return;
      setMitt((l) => hinzufuegen(l, z, Date.now()));
    };
    window.addEventListener(ZEIGT_EREIGNIS, zeigtHoerer);
    onCleanup(() => window.removeEventListener(ZEIGT_EREIGNIS, zeigtHoerer));
    // Safari kneift über eigene Ereignisse.
    let safariStart = 1;
    const gStart = (e: Event) => {
      e.preventDefault();
      safariStart = (e as Event & { scale?: number }).scale ?? 1;
    };
    const gAendert = (e: Event) => {
      e.preventDefault();
      const s = ((e as Event & { scale?: number }).scale ?? 1) / safariStart;
      if (Date.now() < kneifSperre) return;
      if (s < 0.8) kneifAnwenden('zu');
      else if (s > 1.25) kneifAnwenden('auf');
    };
    wurzel?.addEventListener('gesturestart', gStart);
    wurzel?.addEventListener('gesturechange', gAendert);
    // Nach einem Langdruck mit Menü: der Klick beim Loslassen öffnet nicht noch das Ziel.
    const klick = (e: MouseEvent) => {
      if (!klickSchlucken) return;
      klickSchlucken = false;
      e.preventDefault();
      e.stopPropagation();
    };
    wurzel?.addEventListener('click', klick, true);
    onCleanup(() => wurzel?.removeEventListener('click', klick, true));

    let a = apLaden(altLaden);
    // Deeplink: ?offen=<id>[,<id>…]; mit &eingabe=<base64url(JSON)> startet die erste App mit genau diesen Argumenten
    const suche = new URLSearchParams(location.search);
    const gewuenscht = suche.get('offen');
    const linkEingabe = eingabeLesen(suche.get('eingabe'));
    if (gewuenscht) {
      gewuenscht.split(',').filter(Boolean).forEach((id, i) => {
        const startZustand = i === 0 && linkEingabe && id.startsWith('app:') ? startPruefen({ werkzeug: id.slice(4), eingabe: linkEingabe }) : undefined;
        a = flaecheOeffnen(a, id, { start: startZustand, sonstNeu: true }).ap;
      });
    }
    // Aus Apps und Menüs: `fyos:oeffnen` (lib/os/oeffnen.ts) — ui/open-link mit einer Adresse von fyos, Links in Apps
    const oeffnenHoerer = (e: Event) => {
      const d = (e as CustomEvent<OsZiel | undefined>).detail;
      if (d && typeof d.ziel === 'string' && oeffneZiel(d.ziel, d.eingabe)) e.preventDefault();
    };
    window.addEventListener(OEFFNEN, oeffnenHoerer);
    onCleanup(() => window.removeEventListener(OEFFNEN, oeffnenHoerer));
    // Allein geöffnete Flächen finden über Namen und Kanal zu diesem Tab zurück (lib/os/allein.ts)
    onCleanup(osTabMelden());
    setAp(a);
    merkeBesucht(a);
    setBereit(true);
    // Zweiter Tab mit dem OS: dessen Fenster übernehmen, den eigenen Bildschirm behalten; nicht zurückschreiben (kein Hin und Her)
    onCleanup(fremdesSpeichern((fremd) => {
      const mein = bildschirmBei(ap(), aktiv())?.id;
      const i = fremd.bildschirme.findIndex((b) => b.id === mein);
      setAp(wechseln(fremd, aktiv() === START ? START : i >= 0 ? i + 1 : fremd.aktiv));
    }));
    // Die per Link gewünschte Fläche bekommt den Fokus (und damit den Blick), nicht das zuletzt benutzte Fenster.
    const erstesZiel = gewuenscht?.split(',').find(Boolean);
    if (erstesZiel && wo(a, erstesZiel) >= 1) setFokus(erstesZiel);
    apSpeichern(a);
    // Neues Gerät (nichts gespeichert): die zuletzt gemeldete Anordnung aus dem Hub übernehmen.
    if (alleFenster(a).length === 0 && !gewuenscht) {
      void hub<{ bekannt: boolean; fenster?: Fenster[]; bildschirme?: unknown; aktiv?: number; agent?: boolean }>('shell.zustand')
        .then((z) => {
          if (!z?.bekannt || alleFenster(ap()).length) return;
          if (Array.isArray(z.bildschirme) && z.bildschirme.length) setze(pruefen({ bildschirme: z.bildschirme, aktiv: z.aktiv ?? 0 }));
          // Alte Meldung (eine Liste): wird „Bildschirm 1“; man landet wie beim Übernehmen im Browser auf dem Start.
          else if (z.fenster?.length) setze({ ...neuerBildschirm(leer(), 'Bildschirm 1', z.fenster), aktiv: START });
          if (z.agent) {
            setAgent(true);
            setAgentGeladen(true);
          }
        })
        .catch(() => {});
    }
    // Hub-Apps nachladen; Fenster einer abgebauten App verschwinden still. Nicht nur beim Start:
    // alle 2 Minuten, solange sichtbar, und beim
    // Zurückkehren in den Tab — eine neue App steht dann im Dock und Katalog, ohne dass jemand neu lädt.
    let appStand = '';
    /** App-Fenster, deren App beim letzten Abruf fehlte */
    let appsFehlten = new Set<string>();
    const appsNachladen = () =>
      hubApps(true)
        .catch(() => [] as McpApp[])
        .then((liste) => {
          if (!liste.length) return; // Hub kurz weg: nichts abräumen
          const stand = liste.map((x) => x.name).sort().join(',');
          if (stand === appStand && !appsFehlten.size) return;
          appStand = stand;
          setAppListe(liste);
          // Ein Link auf ein Werkzeug einer App mit mehreren (werkstatt__ausfuehren) öffnet die App selbst
          const aufKopf = idsUmbenennen(ap(), (id) => (id.startsWith('app:') ? (appFlaecheZu(flaechen(), id.slice(4))?.id ?? id) : id));
          // Abgeräumt wird erst, was zweimal nacheinander fehlt: fällt ein Plugin kurz aus, ist die Liste unvollständig,
          // und seine Fenster wären sonst für immer weg.
          const fehlt = new Set(alleFenster(aufKopf).map((w) => w.id).filter((id) => id.startsWith('app:') && !liste.some((x) => `app:${x.name}` === id)));
          const weg = new Set([...fehlt].filter((id) => appsFehlten.has(id)));
          appsFehlten = fehlt;
          const neu = weg.size ? bereinigen(aufKopf, (id) => !weg.has(id)) : aufKopf;
          if (neu !== ap()) setze(neu);
        });
    void appsNachladen();
    const appTakt = setInterval(() => {
      if (document.visibilityState === 'visible') void appsNachladen();
    }, 120_000);
    const appSichtbar = () => {
      if (document.visibilityState === 'visible') void appsNachladen();
    };
    document.addEventListener('visibilitychange', appSichtbar);
    onCleanup(() => {
      clearInterval(appTakt);
      document.removeEventListener('visibilitychange', appSichtbar);
    });

    const taste = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      const wechsel = (e.metaKey && e.altKey) || (e.ctrlKey && e.altKey);
      if (wechsel && e.key === 'ArrowLeft') {
        e.preventDefault();
        setze(nachLinks(ap()));
      } else if (wechsel && e.key === 'ArrowRight') {
        e.preventDefault();
        setze(nachRechts(ap()));
      } else if ((wechsel && e.key === 'ArrowUp') || e.key === 'F3') {
        e.preventDefault();
        setUebersicht((u) => !u);
      } else if (wechsel && e.key === 'ArrowDown') {
        e.preventDefault();
        setUebersicht(false);
      } else if (wechsel && /^Digit[1-9]$/.test(e.code)) {
        // e.code: mit ⌥ liefert e.key auf dem Mac „¡“, „“ “ … statt der Ziffer
        e.preventDefault();
        gehe(Number(e.code.slice(5)) - 1);
      } else if (uebersicht() && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && !menue()) {
        e.preventDefault();
        setze(e.key === 'ArrowLeft' ? nachLinks(ap()) : nachRechts(ap()));
      } else if (uebersicht() && e.key === 'Enter' && !menue()) {
        e.preventDefault();
        setUebersicht(false);
      } else if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (start()) setStart(false);
        else oeffneStart();
      } else if (mod && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        toggleAgent();
      } else if (mod && e.key === ',') {
        e.preventDefault();
        einstellungen();
      } else if (mod && e.key === '/') {
        e.preventDefault();
        setHilfe((h) => !h);
      } else if (e.key === 'Escape' && !menue()) {
        setStart(false);
        setUebersicht(false);
      }
    };
    window.addEventListener('keydown', taste);
    onCleanup(() => {
      clearInterval(t1);
      clearInterval(t2);
      clearTimeout(wischEnde);
      clearTimeout(langdruck);
      window.removeEventListener('keydown', taste);
      for (const ev of ereignisse) window.removeEventListener(ev, aktivitaet);
      window.removeEventListener('pointermove', zeiger);
      document.removeEventListener('visibilitychange', sichtbarkeit);
      wurzel?.removeEventListener('wheel', rad);
      wurzel?.removeEventListener('gesturestart', gStart);
      wurzel?.removeEventListener('gesturechange', gAendert);
    });
  });

  // Wer den Fokus bekommt, kommt in den Blick (Dock, Deeplink, Menü) — und bleibt es, während darüber nachgeladen wird.
  // Als Memo: ap() ändert sich bei jedem Speichern, das Halten (Timer, Hörer, scrollIntoView) soll nur neu starten,
  // wenn sich wirklich ändert, welches Fenster im Blick sein soll.
  const imBlick = createMemo(() => {
    const f = fokus();
    return f && wo(ap(), f) === aktiv() && !uebersicht() ? f : null;
  });
  createEffect(() => {
    const f = imBlick();
    if (f) onCleanup(imBlickHalten(f));
  });

  // Übersicht zeigt alle Bildschirme lebendig: ab jetzt laufen sie (und laden nicht neu, wenn sie zugeht).
  createEffect(() => {
    if (uebersicht()) setBesucht(new Set(ap().bildschirme.map((b) => b.id)));
  });

  // Menüs schließen, wenn sich die Lage ändert (Bildschirm, Übersicht, Start).
  createEffect(() => {
    aktiv();
    uebersicht();
    start();
    menueZu();
  });

  // ── Anordnung dem Hub melden (kurz gebündelt): Agent sieht, was offen ist; Geräte gleichen ab ──
  let meldeZeit: ReturnType<typeof setTimeout> | undefined;
  createEffect(() => {
    const a = ap();
    const ag = agent();
    const v = flaechen();
    if (!bereit()) return;
    clearTimeout(meldeZeit);
    meldeZeit = setTimeout(() => {
      void hub('shell.merken', {
        fenster: alleFenster(a),
        bildschirme: a.bildschirme.map((b) => ({ id: b.id, name: b.name, fenster: b.fenster })),
        aktiv: a.aktiv,
        agent: ag,
        verfuegbar: v.map((f) => ({ id: f.id, titel: f.titel })),
      }).catch(() => {});
    }, 800);
  });
  onCleanup(() => clearTimeout(meldeZeit));

  const dockFenster = () => {
    const b = aktueller(ap());
    if (!b) return [];
    return b.fenster
      .filter((w) => flaeche(w.id))
      .map((w) => {
        const f = flaeche(w.id)!;
        return { id: w.id, titel: f.titel, gruppe: f.gruppe, min: w.min };
      });
  };
  const dockFensterKlick = (id: string) => {
    const i = wo(ap(), id);
    if (i < 1) return;
    const w = bildschirmBei(ap(), i)!.fenster.find((x) => x.id === id)!;
    if (w.min) fensterHolen(id);
    else if (fokus() === id && !schmal()) fensterMinimieren(id);
    else setFokus(id);
  };
  const ruhe = () => (aktiv() !== START && !uebersicht()) || untaetig() || versteckt() || start();
  const vorne = () => {
    if (uebersicht()) return 'Übersicht';
    const f = fokus();
    if (f && wo(ap(), f) === aktiv() && aktiv() !== START) return flaeche(f)?.titel ?? '';
    const b = bildschirmBei(ap(), aktiv());
    return aktiv() === START ? 'Start' : b ? nameVon(b) : '';
  };

  // Übersicht: Größe der Karten aus der Fläche und der Zahl der Bildschirme.
  const uebersichtMass = createMemo(() => {
    const n = ap().bildschirme.length + 1;
    const { b, h } = flaecheGr();
    const spalten = n <= 3 ? n : n === 4 ? 2 : n <= 6 ? 3 : 4;
    const reihen = Math.ceil(n / spalten);
    const s = Math.min(0.42, (b * 0.9 - (spalten - 1) * 28) / (spalten * b), (h * 0.84 - reihen * 44) / (reihen * h));
    return { s: Math.max(0.08, s), b, h };
  });
  const bandStil = (): JSX.CSSProperties => {
    const m = uebersichtMass();
    return {
      '--os-w': `${m.b}px`,
      '--os-h': `${m.h}px`,
      '--os-s': String(m.s),
      transform: uebersicht() ? 'none' : `translateX(calc(${-aktiv() * 100}% + ${zug()}px))`,
    };
  };

  const startInhalt = (): JSX.Element => (
    <div data-schreibtisch data-kontext="schreibtisch" class="min-h-full">
      <Startbildschirm gruppen={gruppen()} offen={(id) => wo(ap(), id) >= 1} onOeffnen={(id) => oeffne(id)} onZiehEnde={() => zugEndet()} />
    </div>
  );
  const arbeitsInhalt = (i: () => number): JSX.Element => {
    const b = () => bildschirmBei(ap(), i());
    return (
      <Show when={b()}>
        <Raster
          onStart={() => gehe(START)}
          index={i()}
          b={b()!}
          name={nameVon(b()!)}
          flaeche={flaeche}
          aktiv={fokus()}
          setAktiv={setFokus}
          setze={(l) => setze(fensterAendern(ap(), i(), () => l))}
          ziehen={ziehen()}
          setZiehen={setZiehen}
          schmal={schmal()}
          bildschirme={bildschirmNamen()}
          onAufBildschirm={(id, ziel) => setze(verschiebenNach(ap(), id, ziel))}
          onNeuerBildschirmMit={fensterAufNeuenBildschirm}
          onOeffnen={(id, vor) => oeffne(id, vor)}
          onHerholen={(id) => { setze(verschiebenNach(ap(), id, i())); setFokus(id); }}
          onDing={(g, vor) => dingZeigen(g, { vor })}
          oeffne={(id) => oeffne(id)}
          onUmbenennen={(name) => setze(umbenennen(ap(), i(), name))}
          umbenennen={benennen() === i()}
          onUmbenennenFertig={() => setBenennen(null)}
          onPunkte={(bau) => anmelden(rasterMenue, b, bau)}
          onVerteilen={(fn) => anmelden(rasterVerteilen, b, fn)}
        />
      </Show>
    );
  };
  /** Ein Bildschirm im Band. In der Übersicht ist er eine Karte, die beim Klick zu ihm wechselt. */
  const platz = (index: () => number, name: () => string, inhalt: () => JSX.Element) => {
    // In der Übersicht ist jede Karte ein Ablageziel (wie Mission Control): Fenster aus dem Dock darauf ziehen
    const [ziel, setZiel] = createSignal(false);
    const ablage = ablageZiel({
      ziel: 'bildschirm',
      name,
      annehmen: () => uebersicht() && index() >= 1,
      ablegen: (g) => ablegenAuf(index(), g),
      an: setZiel,
    });
    return (
    <div
      class="os-platz"
      classList={{ 'os-platz-an': aktiv() === index(), 'os-ziel-an': ziel() }}
      data-kontext={uebersicht() ? `bildschirm:${index()}` : undefined}
      onClick={() => { if (uebersicht()) gehe(index()); }}
      {...ablage}
    >
      <section
        class="os-bildschirm"
        aria-label={index() === START ? name() : `Bildschirm: ${name()}`}
        aria-hidden={uebersicht() || aktiv() !== index()}
        ref={(el) => createEffect(() => { el.inert = uebersicht() || aktiv() !== index(); })}
      >
        {inhalt()}
      </section>
      <Show when={uebersicht()}>
        <button type="button" class="os-platz-name" onClick={(e) => { e.stopPropagation(); gehe(index()); }}>
          {name()}
        </button>
      </Show>
    </div>
    );
  };

  return (
    <div
      ref={wurzel}
      class="relative flex h-full min-h-0 flex-col overflow-hidden"
      data-shell
      data-zieht={aktuellerZug() ? '' : undefined}
      onContextMenu={(e) => {
        if (kontextAn(e.target as Element, e.clientX, e.clientY)) e.preventDefault();
      }}
      onPointerDown={fingerRunter}
      onPointerMove={fingerBewegt}
      onPointerUp={fingerHoch}
      onPointerCancel={fingerHoch}
    >
      <Kulisse ruhe={ruhe()} />

      <Menueleiste
        menues={leistenMenues}
        vorne={vorne()}
        rechts={
          <>
            <button
              type="button"
              data-kz-knopf
              class="os-leiste-punkt"
              classList={{ 'os-leiste-an': kz() != null }}
              aria-label="Kontrollzentrum"
              aria-expanded={kz() != null}
              title="Kontrollzentrum"
              onClick={(e) => {
                if (kz() != null) setKz(null);
                else setKz(Math.max(8, window.innerWidth - e.currentTarget.getBoundingClientRect().right - 4));
              }}
            >
              <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true"><rect x="2" y="3" width="14" height="4.5" rx="2.25" fill="none" stroke="currentColor" stroke-width="1.5" /><circle cx="12.5" cy="5.25" r="1.4" fill="currentColor" /><rect x="2" y="10.5" width="14" height="4.5" rx="2.25" fill="none" stroke="currentColor" stroke-width="1.5" /><circle cx="5.5" cy="12.75" r="1.4" fill="currentColor" /></svg>
            </button>
            <span class="os-leiste-uhr"><span class="max-sm:hidden">{datum()}&nbsp;&nbsp;</span>{uhr()}</span>
          </>
        }
      />

      <div class="relative z-[1] flex min-h-0 flex-1">
        <div ref={bereich} class="relative min-w-0 flex-1 overflow-hidden" classList={{ 'os-uebersicht': uebersicht() }}>
          <Show when={meldung()}>
            <p role="status" class="os-glas os-glas-blur absolute top-3 left-1/2 z-[5] -translate-x-1/2 px-4 py-2 text-sm">{meldung()}</p>
          </Show>
          <Show
            when={!schmal()}
            fallback={
              <div class="os-bildschirm h-full overflow-auto">
                <Show when={aktiv() === START} fallback={arbeitsInhalt(aktiv)}>
                  {startInhalt()}
                </Show>
              </div>
            }
          >
            <div class="os-band" classList={{ 'os-band-zieht': zieht() }} style={bandStil()}>
              {platz(() => START, () => 'Start', startInhalt)}
              <For each={ap().bildschirme.map((b) => b.id)}>
                {(id) => {
                  const index = () => ap().bildschirme.findIndex((b) => b.id === id) + 1;
                  return platz(index, () => { const b = bildschirmBei(ap(), index()); return b ? nameVon(b) : 'Bildschirm'; }, () => (
                    <Show when={besucht().has(id)}>{arbeitsInhalt(index)}</Show>
                  ));
                }}
              </For>
              <Show when={uebersicht() && ap().bildschirme.length < 9}>
                <div class="os-platz os-platz-neu">
                  <button type="button" aria-label="Neuer Bildschirm" onClick={(e) => { e.stopPropagation(); neuerBildschirmAn(); }}>
                    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><path d="M14 6v16M6 14h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" /></svg>
                  </button>
                </div>
              </Show>
            </div>
            <Show when={!uebersicht() && aktiv() > START}>
              <button type="button" class="os-pfeil left-2" aria-label="Bildschirm links" onClick={() => setze(nachLinks(ap()))}>‹</button>
            </Show>
            <Show when={!uebersicht() && aktiv() < ap().bildschirme.length}>
              <button type="button" class="os-pfeil right-2" aria-label="Bildschirm rechts" onClick={() => setze(nachRechts(ap()))}>›</button>
            </Show>
          </Show>
        </div>

        {/* Agent-Dock: bleibt geladen, sobald er einmal offen war */}
        <aside
          aria-label={agentName()}
          class="os-glas os-glas-tief m-3 ml-0 flex shrink-0 flex-col overflow-hidden max-md:absolute max-md:inset-0 max-md:z-20 max-md:m-0 max-md:rounded-none"
          classList={{ 'w-[26rem] max-w-[42vw] max-md:max-w-none max-md:w-full': agent(), hidden: !agent(), 'os-ziel-an': agentZiel() }}
          {...agentAblage}
        >
          <header class="os-kopf">
            <h2 class="os-fenstertitel text-left">{agentName()}</h2>
            <button type="button" class="os-knopf" aria-label={`${agentName()} als Fläche lösen`} title="Als Fläche lösen" onClick={() => { oeffne(AGENT_ID); setAgent(false); }}>⧉</button>
            <button type="button" class="os-knopf" aria-label={`${agentName()} schließen`} onClick={() => setAgent(false)}>✕</button>
          </header>
          <Show when={agentGeladen()}>
            <iframe src={agentAdresse()} title={`${agentName()}-Chat`} class="min-h-0 flex-1 border-0 bg-(--color-bg)" style={{ 'pointer-events': ziehen() ? 'none' : 'auto', 'color-scheme': 'dark light' }} onLoad={(e) => fremdesThemaAnwenden(e.currentTarget)} />
          </Show>
        </aside>

        <Show when={start()}>
          <Start
            suche={suche()}
            setSuche={setSuche}
            gruppen={gruppen()}
            offen={(id) => wo(ap(), id) >= 1}
            onOeffnen={(id) => oeffne(id)}
            onZiehEnde={() => zugEndet()}
            bildschirme={bildschirme()}
            aktiv={aktiv()}
            onWechseln={(i) => { gehe(i); setStart(false); }}
            onNeuerBildschirm={() => { neuerBildschirmAn(); setStart(false); }}
            vorlagen={vorlagen()}
            onVorlage={vorlageOeffnen}
            vorlageName={vorlageName()}
            setVorlageName={setVorlageName}
            onVorlageSpeichern={() => void vorlageSpeichern()}
            onVorlageEntfernen={(n) => void vorlageEntfernen(n)}
            vorlageFehler={vorlageFehler()}
            kannSpeichern={!!aktueller(ap())?.fenster.length}
            onSchliessen={() => setStart(false)}
            feld={(el) => (sucheFeld = el)}
          />
        </Show>
        <Show when={hilfe()}>
          <Hilfe onSchliessen={() => setHilfe(false)} />
        </Show>
      </div>

      <Dock
        bildschirme={bildschirmNamen()}
        aktiv={aktiv()}
        onWechseln={gehe}
        onNeuerBildschirm={neuerBildschirmAn}
        startOffen={start()}
        onStart={() => (start() ? setStart(false) : oeffneStart())}
        fenster={dockFenster()}
        fokus={fokus()}
        onFenster={dockFensterKlick}
        agent={agent()}
        onAgent={toggleAgent}
        onAblegen={(i, g) => ablegenAuf(i, g)}
        onAblegenNeu={(g) => ablegenAuf('neu', g)}
        onAgentAblegen={fragenZuGut}
        puls={puls()}
        huepf={huepf()}
      />

      {/* Was beim Loslassen passiert — über dem Ziel, solange etwas gezogen wird (lib/os/ziehen.ts) */}
      <Show when={zugHinweis()}>
        {(h) => (
          <div class="os-zug-hinweis" role="status" style={{ left: `${h().x}px`, top: `${h().y}px` }}>
            {h().text}
          </div>
        )}
      </Show>

      <Show when={kz() != null}>
        <Kontrollzentrum x={kz()!} onSchliessen={() => setKz(null)} einstellungenDa={einstellungenDa()} onEinstellungen={einstellungen} />
      </Show>
      <Mitteilungen
        liste={mitt}
        flaeche={flaeche}
        onOeffnen={async (m) => (oeffneZiel(m.zeigt.ziel, m.zeigt.eingabe ?? undefined) ? null : 'Diese Fläche gibt es hier nicht.')}
        onWeg={(id) => setMitt((l) => l.filter((x) => x.id !== id))}
        onStumm={(minuten) => {
          const vorher = mittEinst();
          mittEinstellen({ ...vorher, stumm_bis: Date.now() + minuten * 60_000 });
          setMittHinweis({ text: 'Mitteilungen eine Stunde stumm.', zurueck: () => mittEinstellen(vorher) });
        }}
        onAus={() => {
          const vorher = mittEinst();
          mittEinstellen({ ...vorher, aus: true });
          setMittHinweis({ text: 'Mitteilungen sind aus.', zurueck: () => mittEinstellen(vorher) });
        }}
        hinweis={mittHinweis}
        onHinweisWeg={() => setMittHinweis(null)}
      />
      <Menue />
    </div>
  );
}
