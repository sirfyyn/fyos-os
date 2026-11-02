/**
 * Bruecke — hängt das offene OS an den Hub: der Agent wirkt auf das, was der Benutzer vor sich hat.
 *
 * Dies ist der Übergang vom Hub ins offene OS:
 *
 *   Agent → os.lage / os.zeigen / os.ausfuehren → Hub → Brücke (lib/os/bruecke-neu.ts) → diese Komponente
 *
 * Sie hat kein eigenes Layout. Sie
 *   - baut aus dem Zustand der Shell die Lage (Fenster, Flächen …; lib/os/bruecke-lage.ts) und meldet
 *     sie dem Hub, sobald sich etwas ändert,
 *   - meldet die Seitenwerkzeuge des OS an (lib/os/bruecke-werkzeuge.ts) — dieselben für den Agenten und für
 *     Browser-Agenten über WebMCP, aus EINEM Register (lib/werkzeuge.ts),
 *   - öffnet auf Befehl Flächen und führt Seitenwerkzeuge aus,
 *   - zeigt „Der Agent zeigt dir …“ als Mitteilung oben rechts (components/os/Mitteilungen.tsx); ist gerade
 *     ein Anruf offen oder die Fläche des Agenten vorn, öffnet sie die App gleich,
 *   - meldet den Ton-Modus dieses Geräts samt Kopfhörern (lib/os/ton-modus.ts) und spielt den
 *     Hinweiston, wenn der Hub ihn in der Mitteilung verlangt (`audio.klang`), und liest sie vor, wenn er
 *     `audio.sprechen` setzt (nur mit Kopfhörern; nie während eines Anrufs; lib/os/vorlesen.ts).
 *
 * Öffnen läuft über das abbrechbare Ereignis `fyos:oeffnen` ({ ziel, eingabe, quelle: 'bruecke' }): wer die
 * Eingabe versteht (Deeplink-/App-Rahmen-Strang), öffnet damit und ruft `event.preventDefault()`. Sonst
 * öffnet der Rückruf `oeffne` der Shell die Fläche ohne Eingabe.
 *
 * Aus: localStorage `fyos:os:bruecke` = `aus`. Ferngesteuerte Browser (navigator.webdriver) melden sich
 * nicht, außer dort steht `an`.
 */
import { createEffect, createMemo, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { aktivitaetBeobachten, erzeugeBruecke, type BrueckeLauf, type BrueckeOptionen } from '~/lib/os/bruecke-neu';
import { lageBauen, type LageQuelle } from '~/lib/os/bruecke-lage';
import { oeffnenMitPruefung, osWerkzeuge, type OsKontext } from '~/lib/os/bruecke-werkzeuge';
import type { Arbeitsplatz } from '~/lib/os/bildschirme';
import type { Flaeche } from '~/lib/os/flaechen';
import { agentName } from '~/lib/config';
import { einstellungLesen, einstellungSchreiben, hinzufuegen, istStumm, type Mitteilung, type ZeigtDaten } from '~/lib/os/agent-zeigt';
import { hinweistonSpielen, kopfhoererErkennen, TON_EREIGNIS, tonModusLesen } from '~/lib/os/ton-modus';
import { vorlesen, vorlesenStoppen, vorlesetext } from '~/lib/os/vorlesen';
import { beiAenderung, fuerBruecke, registriereWerkzeuge, rufenFuerBruecke } from '~/lib/werkzeuge';
import { rueckgaengigAnbieten, rueckHinweis } from '~/lib/os/rueckgaengig';
import Mitteilungen, { type Hinweis } from './Mitteilungen';
import { tr } from '~/lib/i18n';

export interface BrueckeProps {
  ap: () => Arbeitsplatz;
  fokus: () => string | null;
  /** Agent-Dock offen */
  agent: () => boolean;
  flaeche: (id: string) => Flaeche | undefined;
  flaechen: () => Flaeche[];
  oeffne: (id: string) => void;
  /** Fenster schließen; true, wenn es das Fenster gab */
  schliesse: (id: string) => boolean;
  /** Nur für Tests: statt der echten Brücke */
  erzeuge?: (opt: BrueckeOptionen) => BrueckeLauf;
}

export default function Bruecke(p: BrueckeProps): JSX.Element {
  const quelle = (): LageQuelle => ({ ap: p.ap(), fokus: p.fokus(), agent: p.agent(), flaeche: p.flaeche, flaechen: p.flaechen() });
  const lage = createMemo(() => lageBauen(quelle()));
  const kontext: OsKontext = { quelle, oeffne: (id) => p.oeffne(id), schliesse: (id) => p.schliesse(id) };
  const [stapel, setStapel] = createSignal<Mitteilung[]>([]);
  // Eine Karte für alle: „Rückgängig“ nach stumm/aus (hier) und nach dem Schließen (Shell), lib/os/rueckgaengig.ts
  const hinweis = rueckHinweis;
  const setHinweis = (h: Hinweis | null) => rueckgaengigAnbieten(h);
  let bruecke: BrueckeLauf | undefined;

  /** „Der Agent zeigt dir …“ kam an. */
  const zeigtEmpfangen = (z: ZeigtDaten) => {
    if (istStumm(einstellungLesen(), Date.now())) return;
    if (z.audio?.sprechen && !lage().anruf) {
      // Mit Kopfhörern wird vorgelesen (der Hub entscheidet); geht die Stimme nicht, wenigstens der Hinweiston.
      void vorlesen(vorlesetext(z.titel, z.vorschau)).then((ok) => {
        if (!ok && z.audio?.klang) hinweistonSpielen();
      });
    } else if (z.audio?.klang) hinweistonSpielen();
    if (lage().agent_vorne) {
      // Im Anruf oder im Gespräch mit dem Agenten würde eine Mitteilung nur stören: gleich öffnen.
      void oeffnenMitPruefung(kontext, z.ziel, z.eingabe).then((r) => {
        if (!r.ok) setStapel((s) => hinzufuegen(s, z, Date.now())); // ging nicht: wenigstens zeigen
      });
      return;
    }
    setStapel((s) => hinzufuegen(s, z, Date.now()));
  };

  /** Klick auf die Mitteilung: die App öffnen; ein Satz zurück, wenn es nicht ging. */
  const mitteilungOeffnen = async (m: Mitteilung): Promise<string | null> => {
    const r = await oeffnenMitPruefung(kontext, m.zeigt.ziel, m.zeigt.eingabe);
    return r.ok ? null : r.fehler;
  };

  const stumm = (minuten: number) => {
    const vorher = einstellungLesen();
    einstellungSchreiben({ ...vorher, stumm_bis: Date.now() + minuten * 60_000 });
    setHinweis({ text: minuten === 60 ? tr('{0} zeigt dir eine Stunde lang nichts.', agentName()) : tr('{0} zeigt dir {1} Minuten lang nichts.', agentName(), minuten), zurueck: () => einstellungSchreiben(vorher) });
  };
  const aus = () => {
    const vorher = einstellungLesen();
    einstellungSchreiben({ ...vorher, aus: true });
    setHinweis({ text: tr('Mitteilungen von {0} sind aus.', agentName()), zurueck: () => einstellungSchreiben(vorher) });
  };

  onMount(() => {
    const aktiv = aktivitaetBeobachten(window);
    // Kopfhörer: beim Start und bei jedem Wechsel des Ausgabegeräts (Kopfhörer rein/raus) neu bestimmen.
    let kopfhoerer: boolean | null = null;
    const md = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices;
    const kopfhoererNeu = () =>
      void kopfhoererErkennen(md).then((k) => {
        if (k === kopfhoerer) return;
        kopfhoerer = k;
        bruecke?.aendern();
      });
    const b = (p.erzeuge ?? erzeugeBruecke)({
      lage: () => lage(),
      werkzeuge: fuerBruecke,
      zeigen: (ziel, eingabe) => oeffnenMitPruefung(kontext, ziel, eingabe),
      ausfuehren: (name, args) => rufenFuerBruecke(name, args),
      zeigt: zeigtEmpfangen,
      audio: () => ({ modus: tonModusLesen(), kopfhoerer }),
      onStatus: (s) => {
        document.documentElement.dataset.osBruecke = s; // zum Nachsehen und für Tests
      },
      umgebung: { aktivitaet: aktiv.vorSekunden },
    });
    bruecke = b;
    const abWerkzeuge = registriereWerkzeuge(osWerkzeuge(kontext), { dauerhaft: true });
    const abLauscher = beiAenderung(() => b.aendern());
    const tonGeaendert = () => void b.melden();
    window.addEventListener(TON_EREIGNIS, tonGeaendert);
    md?.addEventListener?.('devicechange', kopfhoererNeu);
    kopfhoererNeu();
    b.start();
    onCleanup(() => {
      window.removeEventListener(TON_EREIGNIS, tonGeaendert);
      md?.removeEventListener?.('devicechange', kopfhoererNeu);
      abLauscher();
      abWerkzeuge();
      b.stop();
      aktiv.stop();
      bruecke = undefined;
      delete document.documentElement.dataset.osBruecke;
    });
  });

  // Die Lage hat sich geändert (Fenster, Fokus, Bildschirm, Agent, Flächen): gebündelt melden.
  createEffect(() => {
    lage();
    bruecke?.aendern();
  });

  // Beginnt der Benutzer einen Anruf, hört das Vorlesen sofort auf.
  createEffect(() => {
    if (lage().anruf) vorlesenStoppen();
  });

  return (
    <Mitteilungen
      liste={stapel}
      flaeche={p.flaeche}
      onOeffnen={mitteilungOeffnen}
      onWeg={(id) => setStapel((s) => s.filter((x) => x.id !== id))}
      onStumm={stumm}
      onAus={aus}
      hinweis={hinweis}
      onHinweisWeg={() => setHinweis(null)}
    />
  );
}
