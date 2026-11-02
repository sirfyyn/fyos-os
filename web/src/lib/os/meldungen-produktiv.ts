/**
 * meldungen-produktiv.ts — der Meldungsdienst, verdrahtet für das laufende OS (28.10.2026): Einstellungen als Solid-Signal (gespeichert
 * in localStorage), der Dienst selbst, die Systemmitteilungen, die echten Anschlüsse der Quellen und das Öffnen eines Ziels.
 * Die Logik steht in meldungen.ts, meldungen-quellen.ts und meldungen-system.ts; hier ist nur Verdrahtung ohne eigene Regeln.
 */
import { createSignal } from 'solid-js';
import { AgentApi, AgentVerbindung, haltStrom, type StromZeile } from '~/lib/agent-runner';
import { hub } from '~/lib/hub';
import { hoere } from '~/lib/live';
import { Meldungsdienst, type Meldung, type MeldungAktion, type MeldungenZustand } from './meldungen';
import { lesen, schreiben, type MeldungenEinstellungen } from './meldungen-einstellungen';
import { quellenStarten, speicherMerker, type Anschluesse, type WartetMeldbar } from './meldungen-quellen';
import { SystemMitteilungen } from './meldungen-system';
import { meldebudget, modiStarten, modusZustand } from './modi';
import { imOsOeffnen, type OsZiel } from './oeffnen';
import { EREIGNIS as WARTET_EREIGNIS, wartetAnhaengen, wartetEingang } from './wartet';

const [einstellungen, setzeEinstellungen] = createSignal<MeldungenEinstellungen>(lesen());
export { einstellungen };

/** Einstellungen ändern und speichern. */
export function aendereEinstellungen(f: (alt: MeldungenEinstellungen) => MeldungenEinstellungen): void {
  const neu = f(einstellungen());
  setzeEinstellungen(neu);
  schreiben(neu);
}

/** „Wartet auf dich“ (lib/os/wartet.ts, P2) als Quelle der Freigabe-Meldungen: derselbe Abruf und dieselbe Zahl wie die Menüleiste. */
function wartetQuelle(): Anschluesse['wartet'] {
  return (f) => {
    const abhaengen = wartetAnhaengen();
    const neu = () => {
      const d = wartetEingang();
      if (d) f(d.eintraege as WartetMeldbar[]);
    };
    window.addEventListener(WARTET_EREIGNIS, neu);
    neu();
    return () => {
      abhaengen();
      window.removeEventListener(WARTET_EREIGNIS, neu);
    };
  };
}

/** Ruht Agent (Ruhe-Schalter oder Spielmodus)? Aus `agenten.ruhe`, nur lesend; unbekannt = nein. */
let ruheStand = false;
export const ruht = (): boolean => ruheStand;

export const dienst = new Meldungsdienst({
  einstellungen,
  ruhe: ruht,
  // Ohne Antwort von modus.zustand (Plugin nicht ausgerollt, Hub weg) gilt das alte Verhalten ohne Budget
  modus: () => modusZustand()?.modus,
  budget: meldebudget,
  budgetSpeicher: typeof localStorage === 'undefined' ? null : localStorage,
});

const [zustand, setzeZustand] = createSignal<MeldungenZustand>(dienst.zustand);
dienst.abonniere(setzeZustand);
export { zustand };

/** Ziel einer Meldung (oder Aktion) im OS öffnen: richtiges Fenster nach vorn. */
export function zielOeffnen(z: OsZiel | undefined): boolean {
  return z ? imOsOeffnen({ ...z, vorn: true }) : false;
}

export function meldungOeffnen(m: Meldung, aktion?: MeldungAktion): void {
  zielOeffnen(aktion?.ziel ?? m.ziel);
  dienst.lies(m.id);
}

export const system = new SystemMitteilungen({
  einstellungen,
  oeffne: (m) => zielOeffnen(m.ziel),
  gelesen: (id) => dienst.lies(id),
});
dienst.beiNeu((a) => void system.beiNeu(a));

async function ruheLesen(): Promise<void> {
  try {
    const r = await hub<{ ruhe?: boolean; spielmodus?: string | null }>('agenten.ruhe');
    ruheStand = !!(r?.ruhe || r?.spielmodus);
  } catch {
    ruheStand = false;
  }
}

/** Startet die Quellen (und die Ruhe-Abfrage alle 5 min); `agentVorn`: des Agenten Fenster vorn. Rückgabe beendet alles. */
export function meldungenStarten(agentVorn: () => boolean): () => void {
  const api = new AgentApi(new AgentVerbindung());
  const parsen = <T>(daten: string): T | null => {
    try {
      return JSON.parse(daten) as T;
    } catch {
      return null;
    }
  };
  const a: Anschluesse = {
    einstellungen,
    melde: (e) => dienst.melde(e),
    jetzt: () => Date.now(),
    setInterval: (f, ms) => setInterval(f, ms),
    clearInterval: (h) => clearInterval(h as ReturnType<typeof setInterval>),
    setTimeout: (f, ms) => setTimeout(f, ms),
    clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
    bus: (f) => hoere(f),
    freigaben: () => api.freigaben(),
    freigabenAenderung: (f) => {
      const h = haltStrom({
        oeffnen: (signal) => api.dokumenteStrom(signal),
        beiNachricht: (n) => {
          if (n.event !== 'dokument') return;
          if (parsen<{ name?: string }>(n.data)?.name === 'freigaben') f();
        },
        minMs: 3000,
        maxMs: 60_000,
      });
      return () => h.schliessen();
    },
    stromZeilen: (f) => {
      const h = haltStrom({
        oeffnen: (signal) => api.wirkenStrom(signal),
        beiNachricht: (n) => {
          if (n.event !== 'zeile') return;
          const z = parsen<StromZeile>(n.data);
          if (z && typeof z.text === 'string' && typeof z.typ === 'string') f(z);
        },
        minMs: 3000,
        maxMs: 60_000,
      });
      return () => h.schliessen();
    },
    agentVorn,
    wartet: wartetQuelle(),
    merker: speicherMerker(typeof localStorage === 'undefined' ? null : localStorage),
    kalender: async () => {
      const r = await fetch('/api/calendar/events?who=all&days=1', { credentials: 'include' });
      if (!r.ok) throw new Error(`Kalender ${r.status}`);
      return r.json();
    },
    mail: async (abfrage) => {
      const r = await fetch(`/api/inbox/list?limit=10&q=${encodeURIComponent(abfrage)}`, { credentials: 'include' });
      if (!r.ok) throw new Error(`Mail ${r.status}`);
      return r.json();
    },
  };
  const stopp = quellenStarten(a);
  void ruheLesen();
  const ruheTakt = setInterval(() => void ruheLesen(), 5 * 60_000);
  // Modus (Ruhe/Normal/Bereit, lib/os/modi.ts): der Dienst liest ihn bei jeder Meldung
  const modiStopp = modiStarten();
  return () => {
    stopp();
    clearInterval(ruheTakt);
    modiStopp();
  };
}
