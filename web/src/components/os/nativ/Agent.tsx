/**
 * Agent — die native Fläche `nativ:agent`: die Oberfläche des Agenten-Runners.
 *
 * Gespräche und Chat mit Strom, Live (die autonome Arbeit über alle Gespräche, Voreinstellung an), Freigaben als Karten,
 * Läufe, geteilter Zustand. Spricht nur den Runner (`/api/agent`, nginx setzt das Token). Die Logik steht in
 * lib/agent-runner/, die Teile in agent/. Keine eigenen Stile: Tailwind-Klassen mit den Farben des Systems und die
 * Bausteine der Einstellungen und der Zentrale.
 *
 * Breite (Container, nicht Fenster): ab 42rem steht die Gesprächsliste links, ab 56rem Live als Spalte rechts; darunter
 * ist Live ein Streifen über dem Chat und die Liste klappt aus. `schmal` (Handy) lässt Erklärtexte weg.
 */
import { Match, Show, Switch, createEffect, createSignal, on, onCleanup, onMount, type JSX } from 'solid-js';
import { Wahl } from '~/components/einstellungen/bausteine';
import { istOffen, offeneZahl } from '~/lib/agent-runner/freigaben';
import { laufendeZahl } from '~/lib/agent-runner/laeufe';
import { AgentSitzung } from '~/lib/agent-runner/sitzung';
import { modellName, zugFlaute } from '~/lib/agent-runner/status';
import type { NativProps } from '~/lib/os/nativ';
import { Eingabe } from './agent/Eingabe';
import { Freigaben } from './agent/Freigaben';
import { Gespraechsliste } from './agent/Gespraechsliste';
import { KNOPF, Laedt, Zugangsfehler } from './agent/gemeinsam';
import { Kopf } from './agent/Kopf';
import { Laeufe } from './agent/Laeufe';
import { LiveSpalte, LiveStreifen } from './agent/LiveStrom';
import { Verlauf } from './agent/Verlauf';
import { Zustand } from './agent/Zustand';

type Reiter = 'gespraech' | 'freigaben' | 'laeufe' | 'zustand';

/** Ereignis für Shell und Start: wie viele Freigaben und Läufe gerade auf dich warten bzw. laufen. */
export const AGENT_OFFEN_EREIGNIS = 'fyos:agent-offen';

const Zahl = (p: { n: number; label: string }): JSX.Element => (
  <span class="os-zahl" role="img" aria-label={`${p.n} ${p.label}`}>
    {p.n}
  </span>
);

export default function Agent(
  p: NativProps & {
    fuellen?: boolean;
    /** Eine Frage von außen ("Den Agenten fragen"): jedes neue Objekt kommt einmal als Entwurf ins Eingabefeld. */
    entwurf?: { text: string } | null;
  },
): JSX.Element {
  const sitzung = new AgentSitzung();
  const [stand, setStand] = createSignal(sitzung.stand);
  const [reiter, setReiter] = createSignal<Reiter>('gespraech');
  const [listeOffen, setListeOffen] = createSignal(false);
  const [meldung, setMeldung] = createSignal('');
  /** Freigaben, die du im Verlauf mit „Später“ zurückgestellt hat (sie bleiben offen und in der Liste). */
  const [zurueck, setZurueck] = createSignal<ReadonlySet<string>>(new Set());
  /** Grobe Uhr, damit ein Zug ohne Meldung nach 15 min auffällt, ohne dass etwas passiert. */
  const [uhr, setUhr] = createSignal(Date.now());

  onMount(() => {
    const ab = sitzung.abonniere(setStand);
    void sitzung.starte();
    const takt = setInterval(() => setUhr(Date.now()), 30_000);
    onCleanup(() => {
      ab();
      clearInterval(takt);
      sitzung.beende();
    });
  });

  // Kurze Meldung (Freigabe erteilt, neuer Lauf …) unten, verschwindet nach ein paar Sekunden.
  createEffect(
    on(
      () => stand().hinweis?.id,
      () => {
        const h = stand().hinweis;
        if (!h) return;
        setMeldung(h.text);
        const t = setTimeout(() => setMeldung(''), h.fehler ? 7000 : 4500);
        onCleanup(() => clearTimeout(t));
      },
      { defer: true },
    ),
  );

  const offen = () => offeneZahl(stand().freigaben);
  const laufend = () => laufendeZahl(stand().laeufe);

  // Die Zahl für Fenster und Start: als Ereignis, damit die Shell sie zeigen kann, ohne diese Fläche zu kennen.
  createEffect(
    on(
      () => [offen(), laufend()] as const,
      ([freigaben, laeufe]) => {
        try {
          window.dispatchEvent(new CustomEvent(AGENT_OFFEN_EREIGNIS, { detail: { freigaben, laeufe } }));
        } catch {
          /* ohne CustomEvent keine Zahl außerhalb der Fläche */
        }
      },
    ),
  );

  // Verlangt ein Proxy vor der Shell eine Anmeldung, zeigt er sie beim neuen Laden der Seite; danach verbindet die Fläche neu.
  const anmelden = () => {
    window.location.reload();
  };

  const waehle = (id: number) => {
    setReiter('gespraech');
    setListeOffen(false);
    void sitzung.oeffneGespraech(id);
  };

  const tabs = () =>
    [
      { wert: 'gespraech' as const, text: 'Gespräch' },
      { wert: 'freigaben' as const, text: 'Freigaben', symbol: offen() > 0 ? <Zahl n={offen()} label="offene Freigaben" /> : undefined },
      { wert: 'laeufe' as const, text: 'Läufe', symbol: laufend() > 0 ? <Zahl n={laufend()} label="laufende Läufe" /> : undefined },
      { wert: 'zustand' as const, text: 'Zustand' },
    ] as const;

  const verbunden = () => stand().gespraechStrom === 'offen';
  const fokusTitel = () => (stand().fokus === null ? '' : sitzung.titelVon(stand().fokus!));
  // Freigaben, auf die der Agent in DIESEM Gespräch wartet, stehen als Karte im Verlauf; alle anderen in der Liste.
  // Im schmalen Dock-Panel nur die erste (sonst bleibt vom Gespräch nichts übrig); der Rest steht hinter „weitere“.
  const imVerlauf = () =>
    stand()
      .freigaben.filter((f) => istOffen(f) && f.conversationId === stand().fokus && !zurueck().has(f.id))
      .slice(0, p.schmal ? 1 : 3);
  const weitere = () => Math.max(0, offen() - imVerlauf().length);
  const modell = () => modellName(stand().gespraech, stand().gespraeche.find((g) => g.id === stand().fokus));
  const flaute = () => zugFlaute({ busy: stand().gespraech.busy, letzteRegung: stand().letzteRegung, jetzt: uhr() });
  const getrennt = () => stand().gespraech.geladen && !verbunden();
  const zurListe = () => setReiter('freigaben');
  const stelleZurueck = (id: string) => setZurueck((s) => new Set([...s, id]));

  return (
    <div
      class="@container flex w-full min-w-0 flex-col gap-2 p-2 @2xl:p-3"
      classList={{ 'h-full min-h-0': !!p.fuellen, 'h-[min(46rem,calc(100dvh-8rem))] min-h-[26rem]': !p.fuellen }}
      data-agent
      data-offene-freigaben={offen()}
      onKeyDown={(e) => {
        // Alt+1…4 wechselt den Reiter (nur wenn kein Eingabefeld getippt wird)
        if (!e.altKey || e.ctrlKey || e.metaKey) return;
        const i = Number(e.key) - 1;
        const r = (['gespraech', 'freigaben', 'laeufe', 'zustand'] as const)[i];
        if (r) {
          e.preventDefault();
          setReiter(r);
        }
      }}
    >
      <Switch>
        <Match when={stand().start === 'laedt'}>
          <Laedt text="Verbinde mit Agent" />
        </Match>
        <Match when={stand().start === 'fehler' && stand().fehler}>
          <Zugangsfehler fehler={stand().fehler!} erneut={() => void sitzung.erneut()} anmelden={anmelden} />
        </Match>
        <Match when={stand().start === 'bereit'}>
          <Kopf
            agentName={stand().agentName}
            geraet={stand().geraet}
            schmal={p.schmal}
            busy={stand().gespraech.busy}
            offeneFreigaben={offen()}
            spielmodus={stand().spielmodus}
            modell={modell()}
            live={stand().live}
            getrennt={getrennt()}
            setzeLive={(an) => sitzung.setzeLive(an)}
            zurFreigabenListe={zurListe}
          />
          <div class="min-w-[15rem] @2xl:max-w-md">
            <Wahl name="Bereich" optionen={tabs()} wert={reiter()} onWahl={setReiter} klein />
          </div>

          <Show when={reiter() === 'gespraech'}>
            <div class="flex min-h-0 flex-1 flex-col gap-2 @2xl:grid @2xl:grid-cols-[12rem_minmax(0,1fr)] @2xl:gap-3 @4xl:grid-cols-[12rem_minmax(0,1fr)_17rem]" data-tab="gespraech">
              <div class="hidden min-h-0 @2xl:flex @2xl:flex-col">
                <Gespraechsliste gespraeche={stand().gespraeche} fokus={stand().fokus} waehle={waehle} neu={() => sitzung.neuesGespraech()} />
              </div>

              <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
                {/* Mit nur einem Gespräch gibt es nichts zu wählen (/neu legt ein weiteres an); die Zeile spart schmal Platz. */}
                <Show when={stand().gespraeche.length > 1 || listeOffen()}>
                  <div class="flex items-center gap-2 @2xl:hidden">
                    <button type="button" class={`${KNOPF} min-h-9! min-w-0 flex-1 justify-between`} aria-expanded={listeOffen()} onClick={() => setListeOffen((o) => !o)}>
                      <span class="min-w-0 truncate">{fokusTitel() || 'Gespräche'}</span>
                      <span aria-hidden="true">{listeOffen() ? '▴' : '▾'}</span>
                    </button>
                  </div>
                </Show>
                <Show when={listeOffen()}>
                  <div class="max-h-56 overflow-y-auto rounded-2xl border border-(--os-glas-rand) p-1.5 @2xl:hidden">
                    <Gespraechsliste gespraeche={stand().gespraeche} fokus={stand().fokus} waehle={waehle} neu={() => sitzung.neuesGespraech()} />
                  </div>
                </Show>
                <div class="@4xl:hidden">
                  <LiveStreifen
                    strom={stand().strom}
                    live={stand().live}
                    status={stand().stromStatus}
                    fokus={stand().fokus}
                    agentName={stand().agentName}
                    setze={(an) => sitzung.setzeLive(an)}
                    waehle={waehle}
                  />
                </div>
                <Verlauf
                  z={stand().gespraech}
                  agentName={stand().agentName}
                  fehler={stand().gespraechFehler}
                  verbunden={verbunden()}
                  live={stand().live}
                  fokus={stand().fokus}
                  freigaben={imVerlauf()}
                  weitere={weitere()}
                  entscheide={(id, e) => sitzung.entscheideFreigabe(id, e)}
                  spaeter={stelleZurueck}
                  zurFreigabenListe={zurListe}
                  letzteRegung={stand().letzteRegung}
                  flaute={flaute()}
                  nachfassen={() => sitzung.nachfassen()}
                  abbrechen={() => sitzung.abbrechen()}
                />
                <Eingabe
                  agentName={stand().agentName}
                  busy={stand().gespraech.busy}
                  gespraechId={stand().fokus}
                  gesperrt={stand().fokus === null}
                  sende={(t, a) => sitzung.sende(t, a)}
                  abbrechen={() => sitzung.abbrechen()}
                  anmelden={anmelden}
                  schmal={p.schmal}
                  vorschlag={p.entwurf ?? null}
                />
              </div>

              <div class="hidden min-h-0 @4xl:flex @4xl:flex-col">
                <LiveSpalte
                  strom={stand().strom}
                  live={stand().live}
                  status={stand().stromStatus}
                  fokus={stand().fokus}
                  agentName={stand().agentName}
                  setze={(an) => sitzung.setzeLive(an)}
                  waehle={waehle}
                />
              </div>
            </div>
          </Show>

          <Show when={reiter() === 'freigaben'}>
            <Freigaben
              freigaben={stand().freigaben}
              geladen
              fehler={stand().freigabenFehler}
              entscheide={(id, e) => sitzung.entscheideFreigabe(id, e)}
              erneut={() => void sitzung.auffrischen('freigaben')}
            />
          </Show>

          <Show when={reiter() === 'laeufe'}>
            <Laeufe
              laeufe={stand().laeufe}
              geladen
              fehler={stand().laeufeFehler}
              erneut={() => void sitzung.auffrischen('laeufe')}
              oeffneKind={waehle}
              abbrechen={(id) => sitzung.laufAbbrechen(id)}
              neu={(t, a) => sitzung.neuerLauf(t, a)}
              zurFreigabe={() => setReiter('freigaben')}
            />
          </Show>

          <Show when={reiter() === 'zustand'}>
            <Zustand
              zustand={stand().zustand}
              fehler={stand().zustandFehler}
              erneut={() => void sitzung.auffrischen('zustand')}
              setze={(k, w) => sitzung.zustandSetzen(k, w)}
              loesche={(k) => sitzung.zustandLoeschen(k)}
            />
          </Show>

          <p role="status" aria-live="polite" class="m-0 min-h-5 px-1 text-xs text-(--color-fg-muted)">
            {meldung()}
          </p>
        </Match>
      </Switch>
    </div>
  );
}
