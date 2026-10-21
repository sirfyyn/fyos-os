/**
 * faehigkeiten.ts — was der Agent gerade kann und tut: Schleifen (Arbeitsabläufe), Stimme (Voice), Augen (Eyes).
 * Ein fester Schalter je Fähigkeit rechts in der Menüleiste (components/os/Faehigkeiten.tsx), Zustand und
 * Schalten über den Hub:
 *   schleifen.zustand / schleifen.schalten {schleife, an, von} / schleifen.anstossen {schleife, von}
 *   stimme.zustand    / stimme.lauscher   {raum | "alle", an, von}
 *   augen.zustand     / augen.schalten    {kamera | "alle", an, von}
 * Die Werkzeuge liefern eingerichtete Plugins. Fehlt eines (nicht eingerichtet, 403/404) oder antwortet der Dienst
 * nicht, zeigt der Schalter das ehrlich („Noch nicht eingerichtet.“) statt eines falschen Zustands.
 */
import { agentName } from '~/lib/config';
import { hub } from '~/lib/hub';

export type FaehigkeitId = 'agent' | 'stimme' | 'augen';

/** Wer schaltet: geht als `von` an die Werkzeuge, die es protokollieren. */
const VON = 'nutzer';

export interface Schalter {
  /** stabiler Schlüssel (Schleife, Raum, Kamera) */
  id: string;
  text: string;
  an: boolean;
  hinweis?: string;
  /** Nur Agent: „moeglich“ = Knopf „Jetzt anstoßen“, „laeuft“ = schon angestoßen */
  anstoss?: 'moeglich' | 'laeuft';
}

export interface Faehigkeit {
  id: FaehigkeitId;
  name: string;
  /** null = unbekannt / nicht eingerichtet */
  aktiv: boolean | null;
  satz: string;
  schalter: Schalter[];
  /** Fläche, die mehr zeigt */
  oeffnen?: string;
}

interface SchleifenStand {
  satz?: string;
  schalter?: { arbeit?: boolean; gedaechtnis?: boolean; erkunden?: boolean };
  schleifen?: { id: string; name: string; an: boolean; darf_jetzt: boolean; warum?: string; angestossen?: { seit: string } | null }[];
}
interface StimmeStand {
  erreichbar: boolean;
  satz?: string;
  lauscher?: { raum: string; an: boolean }[];
}
interface AugenStand {
  erreichbar: boolean;
  satz?: string;
  kameras?: { name: string; erkennung: boolean }[];
}

/** Anzeigename: der Agent heißt so, wie die Konfiguration ihn nennt. */
const name = (id: FaehigkeitId): string => (id === 'agent' ? agentName() : id === 'stimme' ? 'Stimme' : 'Augen');

export const agentAus = (s: SchleifenStand): Faehigkeit => {
  const liste = s.schleifen ?? [];
  return {
    id: 'agent',
    name: name('agent'),
    aktiv: liste.some((x) => x.an),
    satz: s.satz ?? '',
    schalter: liste.map((x) => ({
      id: x.id,
      text: x.name,
      an: x.an,
      hinweis: x.an && !x.darf_jetzt ? x.warum : undefined,
      anstoss: x.an ? (x.angestossen ? 'laeuft' : 'moeglich') : undefined,
    })),
    oeffnen: 'app:schleifen__zustand',
  };
};

/** „buero“ → „Büro“, „kueche“ → „Küche“, „ess_zimmer“ → „Ess zimmer“ (Schlüssel sind ASCII). */
const raumName = (r: string) => {
  const t = r.replace(/_/g, ' ').replace(/(?<!q)ue/g, 'ü').replace(/ae/g, 'ä').replace(/oe/g, 'ö');
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const stimmeAus = (s: StimmeStand): Faehigkeit => ({
  id: 'stimme',
  name: name('stimme'),
  aktiv: s.erreichbar ? (s.lauscher ?? []).some((l) => l.an) : null,
  satz: s.satz ?? (s.erreichbar ? '' : 'Die Stimme ist nicht erreichbar.'),
  schalter: (s.lauscher ?? []).map((l) => ({ id: l.raum, text: raumName(l.raum), an: l.an })),
});

export const augenAus = (s: AugenStand): Faehigkeit => ({
  id: 'augen',
  name: name('augen'),
  aktiv: s.erreichbar ? (s.kameras ?? []).some((k) => k.erkennung) : null,
  satz: s.satz ?? (s.erreichbar ? '' : 'Die Kameras sind nicht erreichbar.'),
  schalter: (s.kameras ?? []).map((k) => ({ id: k.name, text: raumName(k.name), an: k.erkennung })),
});

const nichtVerbunden = (id: FaehigkeitId, grund: string): Faehigkeit => ({
  id,
  name: name(id),
  aktiv: null,
  satz: grund,
  schalter: [],
  oeffnen: id === 'agent' ? 'app:schleifen__zustand' : undefined,
});

const grundVon = (e: unknown) => {
  const t = e instanceof Error ? e.message : String(e);
  // 403/404 und „Werkzeug unbekannt“: das Plugin ist nicht eingerichtet
  return /not.?found|unbekannt|unknown|nicht freigegeben|forbidden|\b40[34]\b/i.test(t) ? 'Noch nicht eingerichtet.' : 'Gerade nicht erreichbar.';
};

export async function laden(id: FaehigkeitId): Promise<Faehigkeit> {
  try {
    if (id === 'agent') return agentAus(await hub<SchleifenStand>('schleifen.zustand'));
    if (id === 'stimme') return stimmeAus(await hub<StimmeStand>('stimme.zustand'));
    return augenAus(await hub<AugenStand>('augen.zustand'));
  } catch (e) {
    return nichtVerbunden(id, grundVon(e));
  }
}

/** Eine Schleife des Agenten sofort einen Durchgang machen lassen (schleifen.anstossen). Liefert den neuen Stand. */
export async function anstossen(schleife: string): Promise<Faehigkeit> {
  const r = await hub<{ ok?: boolean; warum?: string }>('schleifen.anstossen', { schleife, von: VON });
  if (r?.ok === false) throw new Error(r.warum || 'Anstoßen ging nicht.');
  return laden('agent');
}

/** Schalten; `ziel` = Schalter-ID oder "alle". Liefert den neuen Stand. */
export async function schalten(id: FaehigkeitId, ziel: string, an: boolean): Promise<Faehigkeit> {
  if (id === 'agent') {
    await hub('schleifen.schalten', { schleife: ziel, an, von: VON });
    return laden('agent');
  }
  if (id === 'stimme') return stimmeAus(await hub<StimmeStand>('stimme.lauscher', { raum: ziel, an, von: VON }));
  return augenAus(await hub<AugenStand>('augen.schalten', { kamera: ziel, an, von: VON }));
}
