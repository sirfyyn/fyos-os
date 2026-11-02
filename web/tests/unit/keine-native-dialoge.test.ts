/**
 * Wächter (28.10.2026): keine nativen Browser-Dialoge in fyos-web.
 *
 * Der System-WebView der Desktop-App „FYOS OS“ (WKWebView/WebView2) zeigt window.confirm/alert/prompt nicht an:
 * confirm liefert sofort false, alert und prompt bleiben stumm — ein „Markierte closen“ brach still ab. Statt dessen
 * lib/ui/dialoge.ts (bestaetigen, meldung, eingabe). Der Dienst selbst hat keinen nativen Rückfall, die Ausnahmeliste
 * ist daher leer; wer einen Eintrag braucht, schreibt hier den Grund dazu.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

const WURZEL = resolve(__dirname, '../..');
const SUCHE = ['src', 'public'];
const ENDUNGEN = /\.(ts|tsx|js|mjs|jsx|astro)$/;
/** Pfad (relativ zu fyos-web) → Grund. Bewusst leer. */
const AUSNAHMEN: Record<string, string> = {};

// Bare Namen nur mit Argument (sonst trifft es Signale wie `const [prompt, setPrompt]` → `prompt()`); mit
// window./globalThis./self./top./parent. immer.
const MIT_PRAEFIX = /(?<![\w$.])(?:window|globalThis|self|top|parent)\s*(?:\.\s*|\?\.\s*)(?:confirm|alert|prompt)\s*\(/;
const MIT_KLAMMER = /(?<![\w$])(?:window|globalThis|self|top|parent)\s*\[\s*['"`](?:confirm|alert|prompt)['"`]\s*\]/;
const BARE = /(?<![\w$.])(?:confirm|alert|prompt)\s*\(\s*[^)\s]/;

function ohneKommentare(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '));
}

export function nativeDialogStellen(text: string): { zeile: number; text: string }[] {
  const treffer: { zeile: number; text: string }[] = [];
  ohneKommentare(text).split('\n').forEach((z, i) => {
    if (MIT_PRAEFIX.test(z) || MIT_KLAMMER.test(z) || BARE.test(z)) treffer.push({ zeile: i + 1, text: z.trim() });
  });
  return treffer;
}

function dateien(ordner: string): string[] {
  let namen: string[];
  try { namen = readdirSync(ordner); } catch { return []; }
  return namen.flatMap((n) => {
    const p = join(ordner, n);
    if (n === 'node_modules' || n === 'dist' || n === '.astro') return [];
    if (statSync(p).isDirectory()) return dateien(p);
    return ENDUNGEN.test(n) && !/\.(test|spec)\.[a-z]+$/.test(n) ? [p] : [];
  });
}

describe('keine nativen Browser-Dialoge', () => {
  it('der Erkenner trifft echte Aufrufe und lässt Signale und Kommentare in Ruhe', () => {
    expect(nativeDialogStellen("if (!window.confirm('x')) return;")).toHaveLength(1);
    expect(nativeDialogStellen("if (!confirm('x')) return;")).toHaveLength(1);
    expect(nativeDialogStellen("alert(`a ${b}`);")).toHaveLength(1);
    expect(nativeDialogStellen("const u = prompt('Link', 'https://');")).toHaveLength(1);
    expect(nativeDialogStellen("window.prompt('x')")).toHaveLength(1);
    expect(nativeDialogStellen("globalThis.alert('x')")).toHaveLength(1);
    expect(nativeDialogStellen("window['confirm']('x')")).toHaveLength(1);
    expect(nativeDialogStellen('const text = prompt().trim(); <input value={prompt()} />')).toHaveLength(0);
    expect(nativeDialogStellen("// window.confirm('x') war früher")).toHaveLength(0);
    expect(nativeDialogStellen("/* alert('x') */ const a = 1;")).toHaveLength(0);
    expect(nativeDialogStellen("showAlert('x'); toast.alert('y'); role=\"alert\"")).toHaveLength(0);
    expect(nativeDialogStellen("await bestaetigen({ titel: 'x' })")).toHaveLength(0);
  });

  it('fyos-web/src und public enthalten keine nativen confirm/alert/prompt-Aufrufe', () => {
    const funde: string[] = [];
    let geprueft = 0;
    for (const sub of SUCHE) {
      for (const datei of dateien(join(WURZEL, sub))) {
        geprueft++;
        const rel = relative(WURZEL, datei);
        if (rel in AUSNAHMEN) continue;
        for (const t of nativeDialogStellen(readFileSync(datei, 'utf8'))) funde.push(`${rel}:${t.zeile}  ${t.text}`);
      }
    }
    expect(geprueft).toBeGreaterThan(100);
    expect(funde, `Native Dialoge zeigt der System-WebView der Desktop-App nicht an. Statt dessen lib/ui/dialoge.ts:\n${funde.join('\n')}`).toEqual([]);
  });
});
