/**
 * Die Apps-Seite des OS (28.10.2026, „den app launcher als eigenen room button anlegen, aber er öffnet keinen room
 * sondern die app auf eine eigene seite“). Der Launcher hat eine eigene Adresse, `/os/apps`, mit Weg zurück (Zurück-Taste
 * des Browsers, Esc, „Zurück“ im Kopf). Die Shell bleibt dieselbe: der Raum darunter bleibt erhalten.
 *
 * Reine Funktionen für die Adresse; die Shell schiebt sie mit pushState in den Verlauf.
 */

export const OS_PFAD = '/os/';
export const APPS_PFAD = '/os/apps/';

/** Ist `pfad` die Apps-Seite (mit oder ohne Schrägstrich am Ende)? */
export const istAppsPfad = (pfad: string): boolean => /^\/os\/apps\/?$/.test(pfad);

/** Adresse der Apps-Seite; die Abfrage (z. B. ?raeume=0) bleibt, ein Deeplink `offen=` nicht (er gehört dem OS selbst). */
export function appsAdresse(suche = ''): string {
  const p = new URLSearchParams(suche);
  p.delete('offen');
  p.delete('eingabe');
  const rest = p.toString();
  return APPS_PFAD + (rest ? `?${rest}` : '');
}

/** Adresse des OS ohne Apps-Seite (zurück). */
export function osAdresse(suche = ''): string {
  return OS_PFAD + (suche && suche !== '?' ? suche : '');
}
