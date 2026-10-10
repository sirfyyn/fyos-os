/**
 * Verzeichnis aller Flächen der Shell.
 *
 * Eine Fläche ist alles, was in einem Fenster der Arbeitsfläche laufen kann:
 *   - `seite`   eine Seite desselben Ursprungs (läuft eingebettet in einem iframe) oder, mit `extern`,
 *               ein fremder Dienst, der in einem neuen Tab öffnet
 *   - `hubapp`  eine MCP-App aus dem Hub (Werkzeug mit ui://-Oberfläche), taucht von selbst auf
 *   - `agent`   der Agent-Chat (Gateway unter `/agent/`), auch als eigenes Fenster
 *   - `nativ`   eine native Fläche (Solid-Komponente direkt im Fenster, lib/os/nativ.ts)
 *
 * Was nicht eingebaut ist, kommt über `registriereFlaechen()` (lib/os/register.ts) von Plugins und aus der
 * Laufzeit-Konfiguration — hier steht keine Liste, die auseinanderlaufen könnte.
 */
import type { Component } from 'solid-js';
import type { McpApp } from '~/lib/mcp-apps/host';
import { appsGruppieren } from '~/components/apps/gruppen';
import { startbar } from '~/lib/mcp-apps/pins';
import { agentPfad } from '~/lib/config';
import { kuerzelVon } from './kuerzel';
import { nativeFlaechen, type NativProps } from './nativ';
import { gruppeFuerApp, registrierteAlias, registrierteFlaechen, registrierteReihenfolge, registrierteStandardPlaetze } from './register';

export { kuerzelVon, gruppeFuerApp };

export type FlaechenArt = 'seite' | 'hubapp' | 'agent' | 'nativ';

export interface Flaeche {
  /** Stabiler Schlüssel: `seite:<slug>`, `app:<mcp-name>`, `agent`, `nativ:<name>`, `extern:<slug>` */
  id: string;
  titel: string;
  gruppe: string;
  art: FlaechenArt;
  /** Zwei Buchstaben für das Symbol im Start */
  kuerzel: string;
  /** Seite: Adresse; Agent: Adresse des Chats */
  pfad?: string;
  /** Hub-App: MCP-Werkzeugname */
  appName?: string;
  /** Beim Öffnen gleich über die ganze Breite */
  breit?: boolean;
  /** Hub-App: eine Zeile, was man damit tut (vom Hub oder aus der Beschreibung abgeleitet) */
  untertitel?: string;
  /** Hub-App: Kategorie im Katalog */
  kategorie?: string;
  /** Hub-App: alle Werkzeuge mit derselben Oberfläche — ein Deeplink darf auch eines von ihnen nennen */
  mitglieder?: string[];
  /** Hub-App: darf an den Startbildschirm geheftet werden (nur lesend, ohne Pflichtfelder, ein Werkzeug) */
  startbar?: boolean;
  /**
   * Fremde Weboberfläche: öffnet in einem neuen Tab statt in einem Fenster — viele Dienste erlauben kein
   * Einbetten (eigene Anmeldung, eigene Kopfzeilen). Hat keinen `pfad`.
   */
  extern?: string;
  /** Native Fläche (`art: 'nativ'`): lädt die Komponente erst, wenn das Fenster aufgeht */
  laden?: () => Promise<{ default: Component<NativProps> }>;
}

export const AGENT_ID = 'agent';

export { EXTERN_GRUPPE } from '~/lib/config';

/** Reihenfolge der eingebauten Gruppen im Start; registrierte Gruppen stehen davor. */
export const GRUPPEN_REIHENFOLGE = ['Agent', 'Apps', 'System', 'Extern'];

export function hubFlaechen(liste: McpApp[]): Flaeche[] {
  // Werkzeuge mit derselben Oberfläche sind EINE Fläche
  return appsGruppieren(liste).map((g) => ({
    id: `app:${g.app.name}`,
    titel: g.gesicht.titel,
    gruppe: gruppeFuerApp(g.app.name),
    art: 'hubapp' as const,
    kuerzel: kuerzelVon(g.gesicht.titel),
    appName: g.app.name,
    untertitel: g.gesicht.untertitel,
    kategorie: g.gesicht.kategorie,
    mitglieder: g.mitglieder.map((m) => m.name),
    startbar: g.mitglieder.length === 1 && startbar(g.app),
  }));
}

/**
 * Die Fläche zu einem Werkzeugnamen: der Name der App selbst oder eines Werkzeugs mit derselben
 * Oberfläche. Ein Deeplink darf beides nennen.
 */
export function appFlaecheZu(flaechen: Flaeche[], werkzeug: string): Flaeche | undefined {
  return flaechen.find((f) => f.art === 'hubapp' && (f.appName === werkzeug || f.mitglieder?.includes(werkzeug)));
}

/** Die Agent-Fläche; Adresse und Titel folgen der Konfiguration. */
export const agentFlaeche = (titel = 'Agent-Chat'): Flaeche => ({
  id: AGENT_ID,
  titel,
  gruppe: 'Agent',
  art: 'agent',
  kuerzel: 'Ag',
  pfad: agentPfad(),
  breit: true,
});

/** Alles, was der Start zeigt: eingebaute Flächen, registrierte, Agent, Hub-Apps; nach Gruppen geordnet. */
export function alleFlaechen(apps: McpApp[] = []): Flaeche[] {
  const alle = [...nativeFlaechen(), ...registrierteFlaechen(), agentFlaeche(), ...hubFlaechen(apps)];
  const reihenfolge = [...registrierteReihenfolge(), ...GRUPPEN_REIHENFOLGE];
  const rang = (g: string) => {
    const i = reihenfolge.indexOf(g);
    return i < 0 ? 99 : i;
  };
  return alle.map((f, i) => ({ f, i })).sort((a, b) => rang(a.f.gruppe) - rang(b.f.gruppe) || a.i - b.i).map((x) => x.f);
}

export function gruppiert(liste: Flaeche[], suche = ''): { gruppe: string; flaechen: Flaeche[] }[] {
  const q = suche.trim().toLowerCase();
  const reihenfolge: string[] = [];
  const map = new Map<string, Flaeche[]>();
  for (const f of liste) {
    // Apps lassen sich auch über ihre Zeile (Untertitel) und Kategorie finden
    if (q && !`${f.titel} ${f.gruppe} ${f.untertitel ?? ''} ${f.kategorie ?? ''}`.toLowerCase().includes(q)) continue;
    if (!map.has(f.gruppe)) {
      map.set(f.gruppe, []);
      reihenfolge.push(f.gruppe);
    }
    map.get(f.gruppe)!.push(f);
  }
  return reihenfolge.map((gruppe) => ({ gruppe, flaechen: map.get(gruppe)! }));
}

/**
 * Die Fläche zu einer Kennung. Alte Kennungen führen über die registrierten Aliasse auf die heutige Fläche
 * (gespeicherte Anordnungen, Lesezeichen und `?offen=…` laufen so weiter, statt ins Leere zu gehen).
 */
export const flaecheZu = (liste: Flaeche[], id: string): Flaeche | undefined => {
  const direkt = liste.find((f) => f.id === id);
  if (direkt) return direkt;
  const ziel = registrierteAlias(id);
  return ziel ? liste.find((f) => f.id === ziel) : undefined;
};

/** Vorgegebene Vorlagen (Namen → Flächen), wie Plugins sie registriert haben. */
export const standardPlaetze = (): { name: string; ids: string[] }[] => registrierteStandardPlaetze();
