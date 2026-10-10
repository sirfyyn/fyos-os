/**
 * gruppen.ts — Hub-Apps mit derselben `ui://`-Oberfläche als EINE Karte.
 *
 * Die Werkstatt hat vier Werkzeuge (suchen, beschreiben, ausfuehren, zeigen), alle mit
 * `ui://fyos/werkstatt.html` — im Launcher waren das vier Karten für eine App. Hier wird
 * nach `resourceUri` zusammengefasst; die Karte öffnet das Mitglied, das sich ohne
 * Pflichtargument starten lässt (sonst das erste).
 */
import type { McpApp } from '~/lib/mcp-apps/host';
import { gesichtVon, type AppGesicht } from '~/lib/mcp-apps/gesicht';

export type AppGruppe = {
  /** Mitglied, das die Karte öffnet. */
  app: McpApp;
  /** Alle Mitglieder (mindestens das Hauptmitglied). */
  mitglieder: McpApp[];
  title: string;
  /** Beschreibung des Werkzeugs (für Agenten geschrieben — Menschen sehen `gesicht.untertitel`). */
  info: string;
  /** Titel, Untertitel, Symbol, Farbe und Kategorie für Menschen (Vertrag 1; Hub oder abgeleitet). */
  gesicht: AppGesicht;
};

/**
 * Kurzbeschreibung für bekannte Oberflächen — sonst gilt die des Hauptmitglieds. Seit Vertrag 1 liefert der
 * Hub eine Zeile je App (`untertitel`) und hat Vorrang; diese hier tragen nur, solange er sie nicht liefert, und für
 * Oberflächen, deren Beschreibung für Agenten geschrieben ist und als Untertitel nach Werkzeug-Jargon klänge.
 */
const INFO: Record<string, string> = {
  'ui://fyos/werkstatt.html': 'Skripte ausführen, Befehle kopieren',
};

const hatPflicht = (a: McpApp) => (a.inputSchema?.required ?? []).length > 0;

/** „Werkstatt — ausführen" → „Werkstatt"; ohne Trenner bleibt der Titel. */
const kopf = (t: string) => (t.split(' — ')[0] ?? t).trim();

export function appsGruppieren(liste: McpApp[]): AppGruppe[] {
  const nachUri = new Map<string, McpApp[]>();
  const reihenfolge: (string | McpApp)[] = [];
  for (const a of liste) {
    const uri = a._meta?.ui?.resourceUri;
    if (!uri) {
      reihenfolge.push(a); // ohne Oberfläche: nie zusammenfassen
      continue;
    }
    if (!nachUri.has(uri)) {
      nachUri.set(uri, []);
      reihenfolge.push(uri);
    }
    nachUri.get(uri)!.push(a);
  }
  const out: AppGruppe[] = [];
  for (const r of reihenfolge) {
    const mitglieder = typeof r === 'string' ? (nachUri.get(r) ?? []) : [r];
    const app = mitglieder.find((m) => !hatPflicht(m)) ?? mitglieder[0];
    if (!app) continue;
    const uri = typeof r === 'string' ? r : '';
    const titel = mitglieder.length > 1 ? kopf(app.title || app.name) : app.title || app.name;
    const gesicht = gesichtVon(app, { gruppe: mitglieder.length > 1, info: INFO[uri] });
    out.push({ app, mitglieder, title: titel, info: INFO[uri] ?? app.description, gesicht });
  }
  return out;
}

/** Werkstatt zuerst, sonst Reihenfolge des Hubs. */
export function werkstattZuerst(gruppen: AppGruppe[]): AppGruppe[] {
  const w = (g: AppGruppe) => g.mitglieder.some((m) => m.name.startsWith('werkstatt__'));
  return [...gruppen.filter(w), ...gruppen.filter((g) => !w(g))];
}
