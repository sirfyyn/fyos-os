/**
 * text.ts — kleine Textwerkzeuge für Gespräche: Inhalte lesen, Zeiten sagen, einfaches Markdown zerlegen.
 * Reine Logik (der Runner-Client app.js nutzt dieselben Wege). Nichts hier erzeugt HTML: die Oberfläche setzt Text.
 */
import type { Eintrag } from './typen';

export function wertText(wert: unknown): string {
  if (wert === undefined || wert === null) return '';
  if (typeof wert === 'string') return wert;
  try {
    return JSON.stringify(wert, null, 2);
  } catch {
    return String(wert);
  }
}

/** Text einer Nachricht: Zeichenkette oder Liste von Blöcken (Gedanken zählen nicht zum Text). */
export function inhaltText(inhalt: unknown): string {
  if (typeof inhalt === 'string') return inhalt;
  if (!Array.isArray(inhalt)) return wertText(inhalt);
  return inhalt
    .map((block: unknown) => {
      if (!block || typeof block !== 'object') return String(block ?? '');
      const b = block as { type?: string; text?: string; name?: string };
      if (b.type === 'text') return b.text ?? '';
      if (b.type === 'thinking') return '';
      if (b.type === 'image') return '[Bild]';
      if (b.type === 'toolCall') return `[Werkzeug ${b.name ?? '?'}]`;
      return wertText(block);
    })
    .filter(Boolean)
    .join('\n');
}

/** Ausgabe eines Werkzeugergebnisses aus den verschiedenen Formen, in denen der Runner sie liefert. */
export function ergebnisText(wert: unknown): string {
  if (!wert) return '';
  if (typeof wert === 'string') return wert;
  const w = wert as { model?: unknown[]; result?: unknown; output?: unknown; content?: unknown; role?: string };
  const msg = (w.model?.[0] ?? w) as { role?: string; content?: unknown };
  if (msg && msg.role === 'toolResult') return inhaltText(msg.content);
  if (w.result !== undefined) return typeof w.result === 'string' ? w.result : wertText(w.result);
  if (w.output !== undefined) return typeof w.output === 'string' ? w.output : wertText(w.output);
  if (w.content !== undefined) return inhaltText(w.content);
  return wertText(wert);
}

export function eintragZeit(e: Eintrag | undefined): number | null {
  if (!e) return null;
  const rohe = [e.createdAt, e.created, e.time, (e.data as { zeit?: unknown } | undefined)?.zeit, firstModel(e)?.timestamp];
  for (const r of rohe) if (typeof r === 'number' && Number.isFinite(r)) return r;
  return null;
}

export function firstModel(e: Eintrag): { timestamp?: number } | undefined {
  const m = Array.isArray(e.model) ? e.model[0] : e.model;
  return m as { timestamp?: number } | undefined;
}

/** Uhrzeit hh:mm:ss (24 h). */
export function uhrzeit(ts: number | null | undefined): string {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  return new Date(ts).toLocaleTimeString('de-DE', { hour12: false });
}

/** hh:mm. */
export function uhrzeitKurz(ts: number | null | undefined): string {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  return new Date(ts).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

/** „vor 3 min“, „gerade eben“. */
export function vor(ts: number | null | undefined, jetzt: number = Date.now()): string {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return '';
  const s = Math.max(0, Math.round((jetzt - ts) / 1000));
  if (s < 10) return 'gerade eben';
  if (s < 60) return `vor ${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `vor ${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `vor ${h} h`;
  return `vor ${Math.round(h / 24)} Tagen`;
}

export function fehlerText(fehler: unknown): string {
  if (!fehler) return 'Unbekannter Fehler';
  const text = String((fehler as { message?: unknown }).message ?? fehler);
  return text.length > 500 ? `${text.slice(0, 499)}…` : text;
}

// ── Markdown, klein ─────────────────────────────────────────────────────────

export type TextTeil =
  | { art: 'absatz'; teile: InlineTeil[] }
  | { art: 'code'; sprache: string; text: string }
  | { art: 'ueberschrift'; stufe: number; teile: InlineTeil[] }
  | { art: 'liste'; geordnet: boolean; punkte: InlineTeil[][] };

export type InlineTeil =
  | { art: 'text'; text: string }
  | { art: 'code'; text: string }
  | { art: 'fett'; text: string }
  | { art: 'kursiv'; text: string }
  | { art: 'link'; text: string; url: string };

/** Nur diese Ziele werden zu Links; alles andere (javascript:, data: …) bleibt Text. */
export const sicheresZiel = (url: string): boolean => /^(https?:\/\/|mailto:)[^\s]+$/i.test(url);

/** `code`, **fett**, *kursiv*, [Text](https://…) und nackte https-Adressen in einer Zeile. Alles andere bleibt Text. */
export function inlineTeile(zeile: string): InlineTeil[] {
  const aus: InlineTeil[] = [];
  const muster = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()[\]]+)|(?<![*\w])\*([^*\s][^*\n]*?)\*(?![*\w])/g;
  let letzte = 0;
  for (let m = muster.exec(zeile); m; m = muster.exec(zeile)) {
    let laenge = m[0].length;
    let teil: InlineTeil;
    if (m[1] !== undefined) teil = { art: 'code', text: m[1] };
    else if (m[2] !== undefined) teil = { art: 'fett', text: m[2] };
    else if (m[3] !== undefined) teil = sicheresZiel(m[4] ?? '') ? { art: 'link', text: m[3], url: m[4] ?? '' } : { art: 'text', text: m[3] };
    else if (m[5] !== undefined) {
      // Satzzeichen am Ende gehören nicht zur Adresse.
      const url = m[5].replace(/[.,;:!?]+$/, '');
      laenge = url.length;
      teil = { art: 'link', text: url, url };
    } else teil = { art: 'kursiv', text: m[6] ?? '' };
    if (m.index > letzte) aus.push({ art: 'text', text: zeile.slice(letzte, m.index) });
    aus.push(teil);
    letzte = m.index + laenge;
    muster.lastIndex = letzte;
  }
  if (letzte < zeile.length) aus.push({ art: 'text', text: zeile.slice(letzte) });
  return aus;
}

/** Zerlegt Markdown in Absätze, Überschriften, Listen und Codeblöcke. Kein HTML, nur Daten. */
export function textTeile(text: string): TextTeil[] {
  const zeilen = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const aus: TextTeil[] = [];
  let absatz: string[] = [];
  let liste: { geordnet: boolean; punkte: InlineTeil[][] } | null = null;
  const absatzEnde = () => {
    if (absatz.length) aus.push({ art: 'absatz', teile: inlineTeile(absatz.join('\n')) });
    absatz = [];
  };
  const listeEnde = () => {
    if (liste) aus.push({ art: 'liste', ...liste });
    liste = null;
  };
  for (let i = 0; i < zeilen.length; i++) {
    const z = zeilen[i] ?? '';
    const zaun = /^```\s*([\w+-]*)\s*$/.exec(z);
    if (zaun) {
      absatzEnde();
      listeEnde();
      const code: string[] = [];
      i++;
      while (i < zeilen.length && !/^```\s*$/.test(zeilen[i] ?? '')) code.push(zeilen[i++] ?? '');
      aus.push({ art: 'code', sprache: zaun[1] ?? '', text: code.join('\n') });
      continue;
    }
    const kopf = /^(#{1,4})\s+(.*)$/.exec(z);
    if (kopf) {
      absatzEnde();
      listeEnde();
      aus.push({ art: 'ueberschrift', stufe: (kopf[1] ?? '#').length, teile: inlineTeile(kopf[2] ?? '') });
      continue;
    }
    const punkt = /^\s*(?:([-*])|(\d+)[.)])\s+(.*)$/.exec(z);
    if (punkt) {
      absatzEnde();
      const geordnet = punkt[2] !== undefined;
      if (liste && liste.geordnet !== geordnet) listeEnde();
      if (!liste) liste = { geordnet, punkte: [] };
      liste.punkte.push(inlineTeile(punkt[3] ?? ''));
      continue;
    }
    if (!z.trim()) {
      absatzEnde();
      listeEnde();
      continue;
    }
    listeEnde();
    absatz.push(z);
  }
  absatzEnde();
  listeEnde();
  return aus;
}
