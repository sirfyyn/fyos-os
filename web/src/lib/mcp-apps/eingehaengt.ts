/**
 * eingehaengt.ts — welche Hub-Apps gerade in einem Fenster laufen und wie man ihnen etwas zustellt.
 *
 * Eine App im Sandbox-iframe hat den Ursprung „null“: die Shell erreicht sie nur über den Host (host.ts) per postMessage.
 * Wer ihr etwas sagen will — „zeig dieses Ding“ (`fyos/oeffne`), „dieses Ding ist auf dich gefallen“ (`fyos/uebergabe`) —
 * ruft `anApp(schluessel, …)`; der Schlüssel ist die Kennung der Fläche (`app:<plugin>__<werkzeug>`). Läuft die App noch nicht
 * oder hat sie `ui/notifications/initialized` noch nicht gemeldet, wartet die Nachricht (höchstens `WARTEN_MS`) und geht
 * hin, sobald sie bereit ist. Das Modul hängt von nichts ab, damit ziehen.ts und host.ts es beide nutzen können.
 */

export interface AppKanal {
  /** Benachrichtigung an die App (JSON-RPC ohne `id`) */
  melden: (method: string, params: unknown) => void;
}

/** So lange wartet eine Nachricht auf eine App, die noch nicht bereit ist. */
export const WARTEN_MS = 30_000;

interface Eintrag {
  kanal: AppKanal;
  bereit: boolean;
}

const eintraege = new Map<string, Eintrag>();
const wartend = new Map<string, { method: string; params: unknown; t: number }[]>();

/** Der Host hängt eine App ein (noch nicht bereit). Gibt die Abmeldung zurück; eine neuere Einbettung desselben Schlüssels bleibt davon unberührt. */
export function kanalAnmelden(schluessel: string, kanal: AppKanal): () => void {
  const e: Eintrag = { kanal, bereit: false };
  eintraege.set(schluessel, e);
  return () => {
    if (eintraege.get(schluessel) === e) eintraege.delete(schluessel);
  };
}

/** Die App hat sich gemeldet (`ui/notifications/initialized`): wartende Nachrichten gehen jetzt hin. */
export function kanalBereit(schluessel: string): void {
  const e = eintraege.get(schluessel);
  if (!e) return;
  e.bereit = true;
  const liste = wartend.get(schluessel) ?? [];
  wartend.delete(schluessel);
  const jetzt = Date.now();
  for (const w of liste) if (jetzt - w.t <= WARTEN_MS) e.kanal.melden(w.method, w.params);
}

/** Einer App eine Benachrichtigung zustellen; ist sie noch nicht bereit, wartet sie. */
export function anApp(schluessel: string, method: string, params: unknown): void {
  const e = eintraege.get(schluessel);
  if (e?.bereit) {
    e.kanal.melden(method, params);
    return;
  }
  const liste = (wartend.get(schluessel) ?? []).filter((w) => Date.now() - w.t <= WARTEN_MS);
  liste.push({ method, params, t: Date.now() });
  wartend.set(schluessel, liste.slice(-8));
}

/** Läuft diese App gerade in einem Fenster (Kanal angemeldet)? */
export const appLaeuft = (schluessel: string): boolean => eintraege.has(schluessel);

/** Nur für Tests. */
export function _zuruecksetzen(): void {
  eintraege.clear();
  wartend.clear();
}
