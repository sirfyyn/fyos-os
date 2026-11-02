/**
 * sitzung.ts — der Zustand der Agenten-Fläche: Gespräche, das offene Gespräch mit seinem Strom, Live, Freigaben, Läufe,
 * geteilter Zustand. Ohne UI: eine Oberfläche abonniert `stand` und ruft die Methoden auf.
 *
 * Ströme (alle über `haltStrom`, verbinden von selbst neu):
 *   - Gespräch   `GET api/gespraech/:id/ereignisse`  (Snapshot, danach Stapel von Ereignissen)
 *   - Live       `GET api/strom`                      (nur solange Live an ist; Voreinstellung an)
 *   - Dokumente  `GET api/dokumente`                  (meldet, wenn sich Freigaben, Läufe oder Zustand geändert haben;
 *                                                      die Sitzung holt dann die Liste neu, statt das Dokument zu deuten)
 */
import { AgentApi, type SendeArt } from './api';
import { leerGespraech, mitAnsicht, mitEreignissen, mitSnapshot } from './gespraech';
import { offeneZahl, ordneFreigaben, type Entscheidung } from './freigaben';
import { ordneLaeufe } from './laeufe';
import { haltStrom, type SseNachricht, type StromStatus } from './sse';
import { leerStrom, liesLive, liveBefehl, mitHallo, mitZeile, schreibeLive, stromTitel, type StromZustand } from './strom';
import { liesBefehl } from './befehle';
import { NACHFASS_TEXT } from './status';
import { fehlerText } from './text';
import type { Freigabe, GeteilterZustand, Gespraech, GespraechId, GespraechsZustand, Hinweis, Lauf } from './typen';
import { AgentVerbindung, RunnerFehler } from './verbindung';
import { tr } from '~/lib/i18n';

export const FOKUS_SPEICHER = 'fyos:agent:fokus';

export interface SitzungsStand {
  /** Erster Kontakt zum Runner. */
  start: 'laedt' | 'bereit' | 'fehler';
  /** Warum der Zugang nicht klappt (nur bei start = fehler). */
  fehler: RunnerFehler | null;
  /**
   * Kennung des Agenten beim Runner (`agent` aus /api/health, z. B. „main“), leer bis zur ersten Antwort. Das ist kein
   * Name: angezeigt wird `agentName()` aus der Laufzeit-Konfiguration (lib/config.ts), die Kennung höchstens als Nebeninfo.
   */
  agentKennung: string;
  geraet: string;
  gespraeche: Gespraech[];
  fokus: GespraechId | null;
  gespraech: GespraechsZustand;
  gespraechStrom: StromStatus | 'leer';
  gespraechFehler: string | null;
  strom: StromZustand;
  stromStatus: StromStatus | 'aus';
  live: boolean;
  freigaben: Freigabe[];
  freigabenFehler: string | null;
  laeufe: Lauf[];
  laeufeFehler: string | null;
  zustand: GeteilterZustand | null;
  zustandFehler: string | null;
  /** Zuletzt gemeldet (läuft auf, `id` zählt hoch, damit gleiche Texte neu auffallen). */
  hinweis: (Hinweis & { id: number }) | null;
  /** Name der Spielmodus-Marke, solange der Runner pausiert (aus /api/health), sonst `null`. */
  spielmodus: string | null;
  /** Wann das offene Gespräch zuletzt etwas gemeldet hat (ms); 0 = noch nie. Daraus erkennt die Fläche einen hängenden Zug. */
  letzteRegung: number;
}

export interface SitzungsOptionen {
  verbindung?: AgentVerbindung;
  api?: AgentApi;
  speicher?: Pick<Storage, 'getItem' | 'setItem'> | null;
  /** Wartezeit des Wiederverbindens und Auffrischens; für Tests. */
  verzoegerungMs?: number;
  zufall?: () => string;
  /** Wird für Ströme benutzt; in Tests ersetzbar. */
  warte?: (ms: number, signal: AbortSignal) => Promise<void>;
  /** Wie oft der Zustand des Runners (Spielmodus) neu gefragt wird; 0 = nie. Standard 30 s. */
  gesundheitMs?: number;
}

type Abonnent = (s: SitzungsStand) => void;
type Auffrischen = 'gespraeche' | 'freigaben' | 'laeufe' | 'zustand';

const leereSeite = (): GespraechsZustand => leerGespraech();

function standardSpeicher(): Pick<Storage, 'getItem' | 'setItem'> | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export class AgentSitzung {
  private s: SitzungsStand;
  private readonly abo = new Set<Abonnent>();
  private readonly api: AgentApi;
  private readonly speicher: Pick<Storage, 'getItem' | 'setItem'> | null;
  private readonly verz: number;
  private readonly zufall: () => string;
  private readonly warte: SitzungsOptionen['warte'];
  private gespraechsHalter: { schliessen: () => void } | null = null;
  private stromHalter: { schliessen: () => void } | null = null;
  private dokumenteHalter: { schliessen: () => void } | null = null;
  private readonly gesundheitMs: number;
  private gesundheitZeit: ReturnType<typeof setInterval> | null = null;
  private auffrischZeit: ReturnType<typeof setTimeout> | null = null;
  private auffrischListe = new Set<Auffrischen>();
  private laeuft = false;
  private offeneIds: Set<string> | null = null;
  private hinweisNummer = 0;
  /** Zählt Gespräch-Wechsel: spät eintreffende Antworten eines früheren Gesprächs werden verworfen. */
  private runde = 0;

  constructor(opt: SitzungsOptionen = {}) {
    this.api = opt.api ?? new AgentApi(opt.verbindung ?? new AgentVerbindung());
    this.speicher = opt.speicher === undefined ? standardSpeicher() : opt.speicher;
    this.verz = opt.verzoegerungMs ?? 300;
    this.zufall = opt.zufall ?? (() => globalThis.crypto?.randomUUID?.() ?? String(Date.now()));
    this.warte = opt.warte;
    this.s = {
      start: 'laedt',
      fehler: null,
      agentKennung: '',
      geraet: '',
      gespraeche: [],
      fokus: null,
      gespraech: leereSeite(),
      gespraechStrom: 'leer',
      gespraechFehler: null,
      strom: leerStrom(),
      stromStatus: 'aus',
      live: liesLive(this.speicher),
      freigaben: [],
      freigabenFehler: null,
      laeufe: [],
      laeufeFehler: null,
      zustand: null,
      zustandFehler: null,
      hinweis: null,
      spielmodus: null,
      letzteRegung: 0,
    };
    this.gesundheitMs = opt.gesundheitMs ?? 30_000;
  }

  get stand(): SitzungsStand {
    return this.s;
  }

  abonniere(f: Abonnent): () => void {
    this.abo.add(f);
    return () => this.abo.delete(f);
  }

  private setze(t: Partial<SitzungsStand>): void {
    this.s = { ...this.s, ...t };
    for (const f of this.abo) f(this.s);
  }

  private melde(h: Hinweis): void {
    this.setze({ hinweis: { ...h, id: ++this.hinweisNummer } });
  }

  // ── Start und Ende ─────────────────────────────────────────────────────────

  /** Erster Kontakt: Gesundheit, Gespräche, Freigaben, Läufe, Zustand; dann Ströme. */
  async starte(): Promise<void> {
    this.laeuft = true;
    this.setze({ start: 'laedt', fehler: null });
    const [gesund, gespraeche, freigaben, laeufe, zustand] = await Promise.allSettled([
      this.api.health(),
      this.api.gespraeche(),
      this.api.freigaben(),
      this.api.laeufe(),
      this.api.zustand(),
    ]);
    if (!this.laeuft) return;

    // Scheitert schon die Liste der Gespräche am Zugang, hilft kein weiterer Versuch: die Fläche zeigt den Grund.
    if (gespraeche.status === 'rejected') {
      const f = gespraeche.reason;
      this.setze({ start: 'fehler', fehler: f instanceof RunnerFehler ? f : new RunnerFehler('netz', 0, fehlerText(f)) });
      return;
    }
    const gez: Partial<SitzungsStand> = { start: 'bereit', gespraeche: gespraeche.value };
    if (gesund.status === 'fulfilled') {
      gez.agentKennung = String(gesund.value.agent ?? '').trim();
      gez.geraet = gesund.value.geraet?.name ?? '';
      gez.spielmodus = gesund.value.spielmodus || null;
    }
    if (freigaben.status === 'fulfilled') {
      gez.freigaben = ordneFreigaben(freigaben.value);
      gez.freigabenFehler = null;
      this.offeneIds = new Set(freigaben.value.filter((f) => f.status === 'offen').map((f) => f.id));
    } else gez.freigabenFehler = fehlerText(freigaben.reason);
    if (laeufe.status === 'fulfilled') {
      gez.laeufe = ordneLaeufe(laeufe.value);
      gez.laeufeFehler = null;
    } else gez.laeufeFehler = fehlerText(laeufe.reason);
    if (zustand.status === 'fulfilled') {
      gez.zustand = zustand.value;
      gez.zustandFehler = null;
    } else gez.zustandFehler = fehlerText(zustand.reason);
    this.setze(gez);

    this.starteDokumente();
    if (this.s.live) this.starteStrom();
    this.starteGesundheit();

    const gemerkt = this.gemerkterFokus();
    const root = gespraeche.value.find((g) => g.art === 'root') ?? gespraeche.value[0];
    const ziel = this.s.fokus ?? gemerkt ?? root?.id ?? null;
    if (ziel !== null) await this.oeffneGespraech(ziel);
  }

  /** Alles schließen (Fläche zu). */
  beende(): void {
    this.laeuft = false;
    this.runde++;
    this.gespraechsHalter?.schliessen();
    this.stromHalter?.schliessen();
    this.dokumenteHalter?.schliessen();
    this.gespraechsHalter = this.stromHalter = this.dokumenteHalter = null;
    if (this.auffrischZeit) clearTimeout(this.auffrischZeit);
    this.auffrischZeit = null;
    if (this.gesundheitZeit) clearInterval(this.gesundheitZeit);
    this.gesundheitZeit = null;
  }

  /** Fragt den Runner regelmäßig nach seinem Zustand: so erscheint „Pausiert (Spielmodus)“, ohne dass du neu lädt. */
  private starteGesundheit(): void {
    if (this.gesundheitZeit) clearInterval(this.gesundheitZeit);
    this.gesundheitZeit = null;
    if (this.gesundheitMs <= 0) return;
    this.gesundheitZeit = setInterval(() => {
      void this.api
        .health()
        .then((g) => {
          const neu = g.spielmodus || null;
          if (this.laeuft && neu !== this.s.spielmodus) this.setze({ spielmodus: neu });
        })
        .catch(() => {
          /* der nächste Versuch zeigt es; die Verbindungsanzeige kommt aus dem Strom */
        });
    }, this.gesundheitMs);
  }

  /** „Erneut versuchen“ nach einem Fehler oder nach der Anmeldung. */
  async erneut(): Promise<void> {
    this.beende();
    this.offeneIds = null;
    await this.starte();
  }

  private gemerkterFokus(): GespraechId | null {
    try {
      const roh = this.speicher?.getItem(FOKUS_SPEICHER);
      return roh && /^\d+$/.test(roh) ? Number(roh) : null;
    } catch {
      return null;
    }
  }

  // ── Gespräch ──────────────────────────────────────────────────────────────

  /** Macht ein Gespräch zum Fokus (groß): lädt den Verlauf und folgt seinem Strom. */
  async oeffneGespraech(id: GespraechId): Promise<void> {
    if (this.s.fokus === id && this.gespraechsHalter) return;
    this.gespraechsHalter?.schliessen();
    const runde = ++this.runde;
    try {
      this.speicher?.setItem(FOKUS_SPEICHER, String(id));
    } catch {
      /* ohne Speicher bleibt der Fokus nur für diese Sitzung */
    }
    this.setze({ fokus: id, gespraech: leereSeite(), gespraechStrom: 'verbinde', gespraechFehler: null, letzteRegung: Date.now() });

    this.gespraechsHalter = haltStrom({
      oeffnen: (signal) => this.api.gespraechsStrom(id, signal),
      beiNachricht: (n) => {
        if (runde === this.runde) this.beiGespraechsNachricht(n);
      },
      beiStatus: (st) => {
        if (runde === this.runde) this.setze({ gespraechStrom: st });
      },
      beiFehler: (f, endgueltig) => {
        if (runde !== this.runde) return;
        // Unbekanntes Gespräch oder fehlender Zugang: nicht still weiterversuchen, sondern sagen, was los ist.
        if (endgueltig) this.setze({ gespraechFehler: f instanceof RunnerFehler ? `${f.titel}: ${f.message}` : fehlerText(f) });
      },
      warte: this.warte,
      minMs: this.verz * 3,
    });

    // Der Verlauf kommt sofort per Ansicht; der Snapshot des Stroms ersetzt ihn, sobald er da ist.
    try {
      const a = await this.api.ansicht(id);
      if (runde === this.runde && !this.s.gespraech.geladen) this.setze({ gespraech: mitAnsicht(this.s.gespraech, a) });
    } catch (f) {
      if (runde === this.runde && !this.s.gespraech.geladen) this.setze({ gespraechFehler: f instanceof RunnerFehler ? `${f.titel}: ${f.message}` : fehlerText(f) });
    }
  }

  private beiGespraechsNachricht(n: SseNachricht): void {
    let daten: unknown;
    try {
      daten = JSON.parse(n.data);
    } catch {
      return;
    }
    if (n.event === 'snapshot') {
      this.setze({ gespraech: mitSnapshot(this.s.gespraech, (daten ?? {}) as Parameters<typeof mitSnapshot>[1]), gespraechFehler: null, letzteRegung: Date.now() });
    } else if (n.event === 'ereignisse' && Array.isArray(daten)) {
      const r = mitEreignissen(this.s.gespraech, daten);
      this.setze({ gespraech: r.zustand, letzteRegung: Date.now() });
      for (const h of r.hinweise) this.melde(h);
      if (r.fertig) {
        this.planeAuffrischen('gespraeche');
        this.planeAuffrischen('laeufe');
        this.planeAuffrischen('freigaben');
      }
    }
  }

  /**
   * Text an den offenen Agenten. `/live` ist ein Befehl an die Fläche, kein Text an den Agenten.
   * Gibt zurück, ob es ein Befehl war. Fehler wirft `RunnerFehler` (die Eingabe bleibt dann stehen).
   */
  async sende(text: string, art: SendeArt = 'folgen'): Promise<{ befehl: boolean }> {
    const t = text.trim();
    if (!t) return { befehl: false };
    const b = liveBefehl(t);
    if (b) {
      this.setzeLive(b === 'wechseln' ? !this.s.live : b === 'an');
      this.melde({ text: this.s.live ? tr('Live an: du siehst die autonome Arbeit.') : tr('Live aus: Strom ausgeblendet. /live blendet ihn wieder ein.') });
      return { befehl: true };
    }
    const c = liesBefehl(t);
    if (c?.name === 'ruhe') {
      this.setzeLive(false);
      this.melde({ text: tr('Ruhe: die eigenständige Arbeit des Agenten ist ausgeblendet. /live blendet sie wieder ein.') });
      return { befehl: true };
    }
    if (c?.name === 'neu') {
      await this.neuesGespraech(c.rest || undefined);
      this.melde({ text: tr('Neues Gespräch.') });
      return { befehl: true };
    }
    if (c?.name === 'stopp') {
      await this.abbrechen();
      this.melde({ text: tr('Zug angehalten.') });
      return { befehl: true };
    }
    if (this.s.fokus === null) throw new RunnerFehler('anfrage', 0, tr('Es ist kein Gespräch offen.'));
    await this.api.sende(this.s.fokus, t, art, `web:${this.zufall()}`);
    return { befehl: false };
  }

  /** „Nachfassen“ bei einem hängenden Zug: eine Rückfrage, die in den laufenden Zug eingreift. */
  async nachfassen(): Promise<void> {
    if (this.s.fokus === null) return;
    await this.api.sende(this.s.fokus, tr(NACHFASS_TEXT), 'steuern', `web:${this.zufall()}`);
    this.setze({ letzteRegung: Date.now() });
    this.melde({ text: 'Nachgefasst.' });
  }

  async abbrechen(): Promise<void> {
    if (this.s.fokus === null) return;
    await this.api.abbrechen(this.s.fokus);
  }

  async neuesGespraech(titel?: string): Promise<GespraechId> {
    const g = await this.api.neuesGespraech(titel?.trim() || undefined);
    this.setze({ gespraeche: [...this.s.gespraeche.filter((x) => x.id !== g.id), g] });
    await this.oeffneGespraech(g.id);
    this.planeAuffrischen('gespraeche');
    return g.id;
  }

  // ── Live ──────────────────────────────────────────────────────────────────

  setzeLive(an: boolean): void {
    schreibeLive(this.speicher, an);
    this.setze({ live: an });
    if (an) this.starteStrom();
    else {
      this.stromHalter?.schliessen();
      this.stromHalter = null;
      this.setze({ stromStatus: 'aus' });
    }
  }

  private starteStrom(): void {
    this.stromHalter?.schliessen();
    this.stromHalter = haltStrom({
      oeffnen: (signal) => this.api.wirkenStrom(signal),
      beiNachricht: (n) => {
        let daten: unknown;
        try {
          daten = JSON.parse(n.data);
        } catch {
          return;
        }
        if (n.event === 'hallo') this.setze({ strom: mitHallo(this.s.strom, daten as { gespraeche?: [] }) });
        else if (n.event === 'zeile') {
          const neu = mitZeile(this.s.strom, daten);
          // Ein Gespräch, das die Liste noch nicht kennt (z. B. ein Mensch- oder Zweiggespräch), nachholen; Läufe haben
          // eigene Kindgespräche, die nicht in der Liste stehen.
          const z = daten as { gespraech?: number; art?: string };
          if (z.gespraech && z.art !== 'lauf' && !this.s.gespraeche.some((g) => g.id === z.gespraech)) this.planeAuffrischen('gespraeche');
          this.setze({ strom: neu });
        }
      },
      beiStatus: (st) => this.setze({ stromStatus: st }),
      warte: this.warte,
      minMs: this.verz * 3,
    });
  }

  /** Name eines Gesprächs für Anzeige (aus Liste oder Strom). */
  titelVon(id: GespraechId): string {
    return this.s.gespraeche.find((g) => g.id === id)?.titel ?? stromTitel(this.s.strom, id) ?? tr('Gespräch {0}', id);
  }

  // ── Dokumente: Freigaben, Läufe, Zustand ──────────────────────────────────

  private starteDokumente(): void {
    this.dokumenteHalter?.schliessen();
    this.dokumenteHalter = haltStrom({
      oeffnen: (signal) => this.api.dokumenteStrom(signal),
      beiNachricht: (n) => {
        if (n.event === 'dokument') {
          try {
            const d = JSON.parse(n.data) as { name?: string };
            if (d.name === 'freigaben') this.planeAuffrischen('freigaben');
            else if (d.name === 'laeufe') this.planeAuffrischen('laeufe');
            else if (d.name === 'zustand') this.planeAuffrischen('zustand');
            else if (d.name === 'register') this.planeAuffrischen('gespraeche');
          } catch {
            /* unlesbar: der nächste Stapel bringt es */
          }
        }
      },
      warte: this.warte,
      minMs: this.verz * 3,
    });
  }

  /** Sammelt Auffrisch-Wünsche und holt sie gemeinsam (Stapel von Ereignissen lösen viele aus). */
  planeAuffrischen(was: Auffrischen): void {
    this.auffrischListe.add(was);
    if (this.auffrischZeit) return;
    this.auffrischZeit = setTimeout(() => {
      this.auffrischZeit = null;
      const liste = [...this.auffrischListe];
      this.auffrischListe.clear();
      for (const w of liste) void this.auffrischen(w);
    }, this.verz);
  }

  async auffrischen(was: Auffrischen): Promise<void> {
    try {
      if (was === 'gespraeche') this.setze({ gespraeche: await this.api.gespraeche() });
      else if (was === 'freigaben') this.setzeFreigaben(await this.api.freigaben());
      else if (was === 'laeufe') this.setze({ laeufe: ordneLaeufe(await this.api.laeufe()), laeufeFehler: null });
      else this.setze({ zustand: await this.api.zustand(), zustandFehler: null });
    } catch (f) {
      const text = fehlerText(f);
      if (was === 'freigaben') this.setze({ freigabenFehler: text });
      else if (was === 'laeufe') this.setze({ laeufeFehler: text });
      else if (was === 'zustand') this.setze({ zustandFehler: text });
    }
  }

  private setzeFreigaben(liste: Freigabe[]): void {
    const offen = liste.filter((f) => f.status === 'offen');
    if (this.offeneIds) {
      const bekannt = this.offeneIds;
      const neu = offen.filter((f) => !bekannt.has(f.id));
      if (neu.length) this.melde({ text: neu.length === 1 ? `Neue Freigabe: ${neu[0]?.aktion ?? 'Aktion'}` : `${neu.length} neue Freigaben warten.` });
    }
    this.offeneIds = new Set(offen.map((f) => f.id));
    this.setze({ freigaben: ordneFreigaben(liste), freigabenFehler: null });
  }

  get offeneFreigaben(): number {
    return offeneZahl(this.s.freigaben);
  }

  /** Erteilen oder Ablehnen. Die Antwort des Runners ist die neue Liste. */
  async entscheideFreigabe(id: string, entscheidung: Entscheidung, notiz?: string): Promise<void> {
    const liste = await this.api.entscheideFreigabe(id, entscheidung, notiz);
    this.setzeFreigaben(liste);
    this.melde({ text: entscheidung === 'erteilt' ? tr('Freigabe erteilt.') : tr('Freigabe abgelehnt.') });
  }

  async neuerLauf(titel: string, auftrag: string): Promise<Lauf> {
    if (this.s.fokus === null) throw new RunnerFehler('anfrage', 0, tr('Es ist kein Gespräch offen, von dem aus der Lauf startet.'));
    const lauf = await this.api.neuerLauf(this.s.fokus, { titel: titel.trim(), auftrag: auftrag.trim() });
    this.planeAuffrischen('laeufe');
    this.melde({ text: tr('Lauf „{0}“ gestartet.', lauf.titel ?? titel) });
    return lauf;
  }

  async laufAbbrechen(id: string): Promise<void> {
    await this.api.laufAbbrechen(id);
    this.planeAuffrischen('laeufe');
    this.melde({ text: tr('Lauf abgebrochen.') });
  }

  /** Wert setzen: JSON, wenn es welches ist, sonst Text. */
  async zustandSetzen(schluessel: string, eingabe: string): Promise<void> {
    await this.api.zustandSetzen(schluessel.trim(), werteAusEingabe(eingabe));
    await this.auffrischen('zustand');
  }

  async zustandLoeschen(schluessel: string): Promise<void> {
    await this.api.zustandLoeschen(schluessel);
    await this.auffrischen('zustand');
  }
}

/** Eingabe eines Zustandswerts: gültiges JSON (Zahl, Objekt, Liste, true/false/null, „Text“) wird JSON, alles andere Text. */
export function werteAusEingabe(eingabe: string): unknown {
  const t = eingabe.trim();
  if (!t) return '';
  if (/^[{["]|^(true|false|null)$|^-?\d+(\.\d+)?$/.test(t)) {
    try {
      return JSON.parse(t);
    } catch {
      return eingabe;
    }
  }
  return eingabe;
}
