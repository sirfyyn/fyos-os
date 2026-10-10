/**
 * Symbole für alles: jede Glyphe, die der Code beim Namen nennt, gibt es im Satz
 * (lib/os/symbole-daten.ts). Eine fehlende würde still als Fenster-Symbol
 * erscheinen — hier fällt es auf. Dazu: die Komponenten Glyphe und Symbol.
 */
import { cleanup, render } from '@solidjs/testing-library';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import Symbol, { Glyphe } from '~/components/os/Symbol';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';
import { symboleSetzen, symboleZuruecksetzen } from '~/lib/os/symbole';
import { SYMBOLE } from '~/lib/os/symbole-daten';

const SRC = resolve(__dirname, '../../src');
const ORDNER = ['components/os', 'components/apps', 'lib/os', 'lib/mcp-apps'];

function dateien(ordner: string): string[] {
  return readdirSync(ordner).flatMap((n) => {
    const pfad = join(ordner, n);
    if (statSync(pfad).isDirectory()) return dateien(pfad);
    return /\.(tsx?|ts)$/.test(n) && n !== 'symbole-daten.ts' ? [pfad] : [];
  });
}

/** Alle Namen, die im Code als Glyphe auftauchen: <Glyphe name="x" />, name={a ? 'x' : 'y'}, symbol: 'x'. */
function genannteGlyphen(): { name: string; datei: string }[] {
  const out: { name: string; datei: string }[] = [];
  for (const o of ORDNER) {
    for (const d of dateien(join(SRC, o))) {
      const text = readFileSync(d, 'utf8');
      const kurz = d.slice(SRC.length + 1);
      for (const m of text.matchAll(/<Glyphe\s+name="([a-z0-9-]+)"/g)) out.push({ name: m[1]!, datei: kurz });
      for (const m of text.matchAll(/<Glyphe\s+name=\{([^}]*)\}/g)) {
        // nur Zweige eines ?:-Ausdrucks zählen, nicht die Wörter in der Bedingung (`art === 'ok' ? 'check' : 'info'`)
        for (const s of m[1]!.matchAll(/(?:^|[?:])\s*'([a-z0-9-]+)'/g)) out.push({ name: s[1]!, datei: kurz });
      }
      for (const m of text.matchAll(/\bsymbol:\s*(?:[a-zA-Z.()!]+\s*\?\s*)?'([a-z0-9-]+)'(?:\s*:\s*'([a-z0-9-]+)')?/g)) {
        out.push({ name: m[1]!, datei: kurz });
        if (m[2]) out.push({ name: m[2], datei: kurz });
      }
    }
  }
  return out;
}

/** Glyphen-Markup so, wie der Browser es nach dem Einsetzen wieder ausgibt (aus `<path/>` wird `<path></path>`). */
const normal = (markup: string): string => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.innerHTML = markup;
  return el.innerHTML;
};

afterEach(() => {
  cleanup();
  symboleZuruecksetzen();
  registerZuruecksetzen();
});

describe('Glyphen im Code', () => {
  it('findet überhaupt welche (die Suche ist nicht blind geworden)', () => {
    const namen = new Set(genannteGlyphen().map((g) => g.name));
    for (const n of ['sparkles', 'link', 'pin', 'external-link', 'rotate-cw', 'x']) expect(namen.has(n), n).toBe(true);
    expect(namen.size).toBeGreaterThan(15);
  });

  it('jede genannte Glyphe gibt es im Satz', () => {
    const fehlen = genannteGlyphen().filter((g) => !SYMBOLE[g.name]);
    expect(fehlen).toEqual([]);
  });
});

describe('Glyphe', () => {
  it('zeichnet die Pfade der Glyphe mit Strich über currentColor und ist für Screenreader unsichtbar', () => {
    const { container } = render(() => <Glyphe name="sparkles" class="x" />);
    const svg = container.querySelector('svg')!;
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    expect(svg.getAttribute('stroke')).toBe('currentColor');
    expect(svg.getAttribute('fill')).toBe('none');
    expect(svg.classList.contains('x')).toBe(true);
    expect(svg.innerHTML).toBe(normal(SYMBOLE.sparkles));
  });

  it('malt die Fläche aus, wenn `gefuellt` gesetzt ist (Stern, Pin)', () => {
    const { container } = render(() => <Glyphe name="pin" gefuellt />);
    expect(container.querySelector('svg')!.getAttribute('fill')).toBe('currentColor');
  });

  it('eine unbekannte Glyphe fällt auf das Fenster-Symbol zurück, statt leer zu bleiben', () => {
    const { container } = render(() => <Glyphe name="gibt-es-nicht" />);
    expect(container.querySelector('svg')!.innerHTML).toBe(normal(SYMBOLE['app-window']!));
  });
});

describe('Symbol — Glyphe auf farbiger Kachel', () => {
  it('nimmt Glyphe und Farbe aus der Tabelle', () => {
    registriereFlaechen({ symbole: { 'seite:notizen': ['house', 26] } });
    const { container } = render(() => <Symbol id="seite:notizen" />);
    const kachel = container.querySelector('.os-symbol') as HTMLElement;
    expect(kachel.style.getPropertyValue('--h')).toBe('26');
    expect(kachel.querySelector('svg')!.innerHTML).toBe(normal(SYMBOLE.house));
    expect(kachel.querySelector('img')).toBeNull();
  });

  it('übernimmt Glyphe und Farbe des Hubs, sobald er sie liefert, auch bei schon gezeichneten Symbolen', () => {
    const { container } = render(() => <Symbol id="app:haus__favoriten" />);
    symboleSetzen({ 'app:haus__favoriten': { glyphe: 'star', ton: 300 } });
    const kachel = container.querySelector('.os-symbol') as HTMLElement;
    expect(kachel.style.getPropertyValue('--h')).toBe('300');
    expect(kachel.querySelector('svg')!.innerHTML).toBe(normal(SYMBOLE.star));
  });

  it('zeigt das fertige Bild des Hubs, wenn er eine Glyphe kennt, die wir nicht zeichnen', () => {
    const svg = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2h20v20H2z"/></svg>';
    symboleSetzen({ 'app:neu__ding': { icon: svg, ton: 200 } });
    const { container } = render(() => <Symbol id="app:neu__ding" />);
    const kachel = container.querySelector('.os-symbol') as HTMLElement;
    expect(kachel.classList.contains('os-symbol-fertig')).toBe(true);
    const bild = kachel.querySelector('img.os-symbol-bild') as HTMLImageElement;
    expect(bild.getAttribute('src')).toBe(svg);
    expect(bild.getAttribute('alt')).toBe('');
    expect(kachel.querySelector('svg')).toBeNull();
  });

  it('Grafit und Agent haben eigene Kacheln', () => {
    const { container } = render(() => (
      <>
        <Symbol id="nativ:einstellungen" />
        <Symbol id="agent" />
      </>
    ));
    expect(container.querySelector('.os-symbol-grafit')).toBeTruthy();
    expect(container.querySelector('.os-symbol-agent')).toBeTruthy();
  });
});
