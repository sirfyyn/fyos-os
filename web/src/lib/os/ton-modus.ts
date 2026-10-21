/**
 * ton-modus.ts — Ton je Gerät: stumm mit Ton-Modus, wenn keine Kopfhörer eingesteckt sind, oder
 * stumm mit nur Benachrichtigungen, aber mit Kopfhörern richtig interaktiv oder zurückhaltend.
 *
 * Der Modus gehört dem Gerät (localStorage), nicht dem Konto: am einen Gerät kann „interaktiv“ gelten, am anderen
 * „stumm“. Die Brücke meldet ihn mit (`audio: {modus, kopfhoerer}`, lib/os/bruecke.ts); den wirksamen Modus
 * rechnet der Hub (ohne Kopfhörer höchstens „ton“) und schreibt in jede Mitteilung, ob das Gerät einen
 * Hinweiston spielt (`klang`) und ob es vorliest (`sprechen`).
 *
 * Kopfhörer erkennt der Browser nur nach bestem Wissen: Chrome nennt den Standard-Ausgang beim Namen
 * („Standard - Kopfhörer“), sobald die Seite einmal das Mikrofon durfte (Anruf). Sonst: null = unbekannt,
 * und unbekannt zählt wie „keine“ — der Agent spricht nie in einen Raum.
 */

export type TonModus = 'stumm' | 'ton' | 'zurueckhaltend' | 'interaktiv';
export const TON_MODI: readonly TonModus[] = ['stumm', 'ton', 'zurueckhaltend', 'interaktiv'];
export const TON_NAMEN: Record<TonModus, string> = {
  stumm: 'Stumm',
  ton: 'Ton',
  zurueckhaltend: 'Zurückhaltend',
  interaktiv: 'Interaktiv',
};
export const TON_HILFE: Record<TonModus, string> = {
  stumm: 'Nur Mitteilungen, kein Ton',
  ton: 'Mitteilung mit Hinweiston, der Agent spricht nicht',
  zurueckhaltend: 'Mit Kopfhörern: spricht nur, wenn es dringend ist',
  interaktiv: 'Mit Kopfhörern: spricht von selbst',
};

export const TON_SCHLUESSEL = 'fyos:os:ton-modus';
/** Geht an window, wenn der Modus geändert wird — die Brücke meldet dann sofort. */
export const TON_EREIGNIS = 'fyos:ton-modus';

export interface AudioMeldung {
  modus: TonModus | null;
  kopfhoerer: boolean | null;
}

const istModus = (x: unknown): x is TonModus => typeof x === 'string' && (TON_MODI as readonly string[]).includes(x);

const standardSpeicher = (): Storage | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
};

export function tonModusLesen(speicher: Pick<Storage, 'getItem'> | null = standardSpeicher()): TonModus | null {
  try {
    const roh = speicher?.getItem(TON_SCHLUESSEL);
    return istModus(roh) ? roh : null;
  } catch {
    return null;
  }
}

export function tonModusSchreiben(
  modus: TonModus,
  speicher: Pick<Storage, 'setItem'> | null = standardSpeicher(),
  ziel: Pick<Window, 'dispatchEvent'> | null = typeof window === 'undefined' ? null : window,
): void {
  try {
    speicher?.setItem(TON_SCHLUESSEL, modus);
  } catch {
    /* gilt dann nur bis zum Neuladen */
  }
  try {
    ziel?.dispatchEvent(new CustomEvent(TON_EREIGNIS, { detail: modus }));
  } catch {
    /* ohne Ereignis meldet die Brücke beim nächsten Takt */
  }
}

const KOPFHOERER = /airpods|beats|kopfh|headphone|headset|earbud|buds/i;
const LAUTSPRECHER = /lautsprecher|speaker|macbook|display|hdmi|monitor/i;

/**
 * Kopfhörer am Standard-Ausgang? true / false, oder null, wenn der Browser es nicht verrät (keine Namen ohne
 * Mikrofon-Erlaubnis, Safari ohne Ausgabegeräte).
 */
export function kopfhoererAus(geraete: ReadonlyArray<Pick<MediaDeviceInfo, 'kind' | 'deviceId' | 'label'>>): boolean | null {
  const ausgaenge = geraete.filter((g) => g.kind === 'audiooutput');
  const standard = ausgaenge.find((g) => g.deviceId === 'default') ?? ausgaenge[0];
  const name = standard?.label ?? '';
  if (!name) return null;
  if (KOPFHOERER.test(name)) return true;
  if (LAUTSPRECHER.test(name)) return false;
  return null;
}

export async function kopfhoererErkennen(md: Pick<MediaDevices, 'enumerateDevices'> | null | undefined): Promise<boolean | null> {
  if (!md?.enumerateDevices) return null;
  try {
    return kopfhoererAus(await md.enumerateDevices());
  } catch {
    return null;
  }
}

/** Kurzer, leiser Hinweiston (zwei Sinustöne). Ohne vorherige Eingabe darf der Browser ihn verweigern. */
export function hinweistonSpielen(): void {
  try {
    const Ctx = (window as unknown as { AudioContext?: typeof AudioContext }).AudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const t0 = ctx.currentTime;
    for (const [frequenz, start] of [
      [880, 0],
      [1320, 0.12],
    ] as const) {
      const osz = ctx.createOscillator();
      const laut = ctx.createGain();
      osz.type = 'sine';
      osz.frequency.value = frequenz;
      laut.gain.setValueAtTime(0, t0 + start);
      laut.gain.linearRampToValueAtTime(0.08, t0 + start + 0.02);
      laut.gain.exponentialRampToValueAtTime(0.0001, t0 + start + 0.25);
      osz.connect(laut).connect(ctx.destination);
      osz.start(t0 + start);
      osz.stop(t0 + start + 0.3);
    }
    setTimeout(() => void ctx.close().catch(() => undefined), 800);
  } catch {
    /* kein Ton ist kein Fehler */
  }
}
