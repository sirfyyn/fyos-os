/*
 * Vorlage „diagramm“: Diagramme aus einer kurzen JSON-Spezifikation (Graph, Sequenz, Baum).
 *
 * Herkunft: SeeCode 0.6.1, https://github.com/Aryanutkarsh/SeeCode
 * Gepinnter Stand: Commit 82c33b68be60578aeb21f429de5662a7d892a99f (übernommen am 2026-10-11).
 * Lizenz: MIT, Copyright (c) 2026 Aryanutkarsh. Der Lizenztext steht unten und gilt für die aus SeeCode
 * übernommenen Teile dieser Datei (alles zwischen „SeeCode-Anfang“ und „SeeCode-Ende“).
 *
 * Übernommen (wörtlich, Dateien gegen SHA-256 geprüft): lib/svg, lib/text, lib/schema, render/shared/{icons,nodes,
 * edges,legend}, render/graph/{graph,route}, render/lanes/sequence, render/structure/tree und die Schemas
 * {common,graph,stages,sequence,tree}.
 *
 * Geändert:
 *  - Aus Node-Modulen (import/export) wurden Funktionen in einer Datei; Kommentarzeilen und Leerzeilen entfernt.
 *  - Entfernt: Seite, Betrachter, Export, Marke (Wasserzeichen), Google-Fonts-Verweise, Schrift- und Marken-Import,
 *    Bewegung (Animation, wandernde Marke), Dateizugriff, Wegprüfung (verify), alle anderen Diagrammarten.
 *  - Beschriftungen der Legende, Status und Änderungsmarken ins Deutsche (nur Texte).
 *  - Farben und Schriften kommen vom Host (ansicht.css, --color-*, --font-*); von SeeCode bleibt nur die Maßrechnung
 *    (Plex-Breiten, deshalb Breitenfaktor 1,08 für die Systemschrift).
 *  - Schemas ohne Titel und Beschreibungen; Prüfung und Darstellung im Kleber (eigener Code, ab „FYOS-Kleber“).
 *
 * Keine Abrufe: kein fetch, XHR, WebSocket, import(), eval, new Function, innerHTML. Das erzeugte SVG wird vor dem
 * Einsetzen streng geprüft (nur bekannte Elemente und Attribute, keine Verweise, keine Ereignisse).
 *
 * Neu erzeugen: python3 -I tools/seecode_einbetten/einbetten.py <SeeCode-Checkout>
 *
 * MIT License
 *
 * MIT License
 *
 * Copyright (c) 2026 Aryanutkarsh
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
(() => {
"use strict";
const M = {};
/* ── SeeCode-Anfang ── */
M.tokens = (() => {
const TYPE = { label: 12, sub: 9, tag: 7, edge: 8, axis: 8, legend: 9, title: 13 };
return { TYPE };
})();
M.svg = (() => {
function esc(v) {
  return String(v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
const r2 = (n) => (Number.isInteger(n) ? n : Math.round(n * 100) / 100 || 0);
const GEOMETRY = new Set(['d', 'points', 'transform']);
const NUM = /-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/gi;
const roundGeometry = (str) => String(str).replace(NUM, (m) => String(r2(Number(m))));
function attrs(a) {
  let out = '';
  for (const [k, v] of Object.entries(a)) {
    if (v === undefined || v === null || v === false) continue;
    out += ` ${k}="${esc(typeof v === 'number' ? r2(v) : GEOMETRY.has(k) ? roundGeometry(v) : v)}"`;
  }
  return out;
}
function el(tag, a = {}, children) {
  if (children === undefined || children === null) return `<${tag}${attrs(a)}/>`;
  const body = Array.isArray(children) ? children.join('') : children;
  return `<${tag}${attrs(a)}>${body}</${tag}>`;
}
const text = (a, content) => el('text', a, esc(content));
function pathD(points) {
  return points.map((p, i) => `${i ? 'L' : 'M'}${r2(p.x)},${r2(p.y)}`).join(' ');
}
function roundedPath(points, r = 6) {
  if (points.length < 3) return pathD(points);
  let d = `M${r2(points[0].x)},${r2(points[0].y)}`;
  for (let i = 1; i < points.length - 1; i++) {
    const p0 = points[i - 1];
    const p = points[i];
    const p1 = points[i + 1];
    const l0 = Math.hypot(p.x - p0.x, p.y - p0.y);
    const l1 = Math.hypot(p1.x - p.x, p1.y - p.y);
    const rr = Math.min(r, l0 / 2, l1 / 2);
    if (rr < 0.5) {
      d += ` L${r2(p.x)},${r2(p.y)}`;
      continue;
    }
    const a = { x: p.x - ((p.x - p0.x) / l0) * rr, y: p.y - ((p.y - p0.y) / l0) * rr };
    const b = { x: p.x + ((p1.x - p.x) / l1) * rr, y: p.y + ((p1.y - p.y) / l1) * rr };
    d += ` L${r2(a.x)},${r2(a.y)} Q${r2(p.x)},${r2(p.y)} ${r2(b.x)},${r2(b.y)}`;
  }
  const last = points[points.length - 1];
  return `${d} L${r2(last.x)},${r2(last.y)}`;
}
function markers() {
  const m = (id, cls) =>
    el('marker', { id, viewBox: '0 0 8 6', markerWidth: 8, markerHeight: 6, refX: 7, refY: 3, orient: 'auto-start-reverse', markerUnits: 'userSpaceOnUse' },
      el('path', { d: 'M0,0 L8,3 L0,6 Z', class: cls }));
  return el('defs', {}, [
    m('sc-arrow', 'm-default'),
    m('sc-arrow-primary', 'm-primary'),
    m('sc-arrow-link', 'm-link'),
    m('sc-arrow-muted', 'm-muted'),
  ]);
}
const MARKER_FOR = { default: 'sc-arrow', primary: 'sc-arrow-primary', link: 'sc-arrow-link', async: 'sc-arrow', return: 'sc-arrow', muted: 'sc-arrow-muted' };
function rectsOverlap(a, b, pad = 0) {
  return a.x < b.x + b.w + pad && a.x + a.w + pad > b.x && a.y < b.y + b.h + pad && a.y + a.h + pad > b.y;
}
return { esc, roundGeometry, el, text, pathD, roundedPath, markers, MARKER_FOR, rectsOverlap };
})();
M.text = (() => {
const PLEX_400 = [236,284,419,713,598,927,694,242,335,335,450,600,272,399,272,383,600,600,600,600,600,600,600,600,600,600,292,292,600,600,600,477,881,641,653,621,671,583,542,695,707,400,510,634,501,812,707,708,606,708,640,568,572,678,614,891,613,593,580,317,383,317,600,565,600,534,580,497,580,549,319,528,568,250,250,527,272,873,568,560,580,580,367,480,351,568,492,768,507,499,464,343,314,343,600];
const PLEX_600 = [236,309,471,656,600,960,713,260,337,337,556,600,299,402,299,437,600,600,600,600,600,600,600,600,600,600,319,319,600,600,600,493,882,672,663,642,689,600,551,712,719,423,545,678,521,817,719,712,641,712,664,591,580,689,642,949,655,632,599,329,437,329,600,559,600,559,600,508,600,558,346,545,588,275,275,562,294,888,588,563,600,600,393,491,374,588,524,819,544,521,502,363,376,363,600];
const MARGIN = 1.03;
const NARROW = new Set([...`il.,:;'|!\`ijlrtf()[]{}`]);
const WIDE_UPPER = new Set([...'MWQOGDCH@%&']);
function isWide(cp) {
  return (
    (cp >= 0x1100 && cp <= 0x115f) || (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) || (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) || (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) || (cp >= 0x1f300 && cp <= 0x1faff) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
  );
}
function isMark(cp) {
  return (cp >= 0x0300 && cp <= 0x036f) || (cp >= 0x20d0 && cp <= 0x20ff) || cp === 0x200d || (cp >= 0xfe00 && cp <= 0xfe0f);
}
function advance(ch, mono, bold = false) {
  const cp = ch.codePointAt(0);
  if (isMark(cp)) return 0;
  if (isWide(cp)) return 1;
  if (mono) return 0.6;
  if (cp >= 32 && cp <= 126) return ((bold ? PLEX_600 : PLEX_400)[cp - 32] / 1000) * MARGIN;
  const k = bold ? 1.04 : 1;
  return heuristic(ch) * k;
}
function heuristic(ch) {
  if (ch === ' ') return 0.28;
  if (NARROW.has(ch)) return 0.3;
  if (WIDE_UPPER.has(ch)) return 0.74;
  if (ch >= 'A' && ch <= 'Z') return 0.64;
  if (ch >= '0' && ch <= '9') return 0.58;
  if (ch === 'm' || ch === 'w') return 0.84;
  return 0.54;
}
let widthScale = 1;
function setWidthScale(k) { const prev = widthScale; widthScale = k; return prev; }
function textWidth(str, { size = 12, mono = false, tracking = 0, upper = false, weight = 400 } = {}) {
  const s = upper ? String(str).toUpperCase() : String(str);
  let em = 0;
  let n = 0;
  const bold = !mono && weight >= 600;
  for (const ch of s) {
    em += advance(ch, mono, bold);
    n++;
  }
  return (em * size + Math.max(0, n - 1) * tracking * size) * widthScale;
}
const snap = (v, g = 4) => Math.round(v / g) * g;
const ceil4 = (v) => Math.ceil(v / 4) * 4;
const NO_START = new Set([...'、。，．：；！？）」』】〕〉》｝］〙〗’”…‥ー々ゝゞヽヾぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ']);
const NO_END = new Set([...'（「『【〔〈《｛［〘〖‘“']);
function units(str) {
  const out = [];
  for (const m of String(str).matchAll(/(\s*)(\S+)/g)) {
    const space = m[1].length > 0 && out.length > 0;
    let word = '';
    let first = true;
    const flush = (glue) => {
      if (!word) return;
      out.push({ text: word, space: first ? space : false, glue });
      word = '';
      first = false;
    };
    for (const ch of m[2]) {
      const cp = ch.codePointAt(0);
      if (NO_START.has(ch) && (word || out.length)) {
        if (word) word += ch;
        else out[out.length - 1].text += ch;
        continue;
      }
      if (isWide(cp) || NO_END.has(ch)) {
        if (word && !NO_END.has([...word].pop())) flush();
        word += ch;
        if (!NO_END.has(ch)) flush();
      } else {
        if (word && isWide([...word].pop().codePointAt(0))) flush();
        word += ch;
      }
    }
    flush();
  }
  return out;
}
function wrap(str, maxWidth, opts) {
  const lines = [];
  let cur = '';
  for (const u of units(str)) {
    const next = cur ? `${cur}${u.space ? ' ' : ''}${u.text}` : u.text;
    if (cur && textWidth(next, opts) > maxWidth) {
      lines.push(cur);
      cur = u.text;
    } else cur = next;
  }
  if (cur) lines.push(cur);
  return lines.length ? lines : [''];
}
return { advance, setWidthScale, textWidth, snap, ceil4, wrap };
})();
M.motion = (() => {
const MAX_STEPS = 12;
const PRESETS = ['none', 'reveal', 'trace', 'step', 'loop'];
const FAMILY_DEFAULT = { graph: 'trace', lanes: 'trace', structure: 'reveal', chart: 'reveal' };
function resolvePreset(motion, family) {
  if (!motion || motion === 'auto') return FAMILY_DEFAULT[family] || 'reveal';
  return motion;
}
function compressSteps(depths) {
  const uniq = [...new Set(depths)].sort((a, b) => a - b);
  const n = uniq.length;
  const map = new Map();
  uniq.forEach((d, i) => {
    map.set(d, n <= MAX_STEPS ? i + 1 : 1 + Math.round((i * (MAX_STEPS - 1)) / (n - 1)));
  });
  return depths.map((d) => map.get(d));
}
return { MAX_STEPS, PRESETS, FAMILY_DEFAULT, resolvePreset, compressSteps };
})();
M.icons = (() => {
const { el } = M.svg;
const P = (d) => ['path', { d }];
const C = (cx, cy, r) => ['circle', { cx, cy, r }];
const R = (x, y, width, height, rx = 2) => ['rect', { x, y, width, height, rx }];
const ICONS = {
  calendar: [R(3, 5, 18, 16), P('M3 10h18M8 3v4M16 3v4')],
  clock: [C(12, 12, 9), P('M12 7v5l3 2')],
  person: [C(12, 8, 4), P('M4 21c0-4 3.6-6 8-6s8 2 8 6')],
  people: [C(9, 8, 3.5), C(17, 9, 2.5), P('M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5M16.5 14.5c3 0 5.5 1.6 5.5 4.5')],
  briefcase: [R(3, 7, 18, 13), P('M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3 13h18')],
  home: [P('M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z')],
  money: [R(2, 6, 20, 12), C(12, 12, 3), P('M6 9v.01M18 15v.01')],
  card: [R(2, 5, 20, 14), P('M2 10h20M6 15h4')],
  cart: [P('M3 4h2l2.5 11h11L21 8H7'), C(9, 19.5, 1.5), C(17, 19.5, 1.5)],
  document: [P('M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7')],
  flag: [P('M5 21V4h12l-2 4 2 4H5')],
  check: [C(12, 12, 9), P('M8 12.5l3 3 5-6')],
  mail: [R(3, 5, 18, 14), P('M3 7l9 6 9-6')],
  phone: [R(7, 2, 10, 20), P('M11 18h2')],
  chat: [P('M4 5h16v11H9l-5 4z')],
  plane: [P('M22 2L11 13M22 2l-7 20-4-9-9-4z')],
  car: [P('M5 15l1.6-4.7A2 2 0 0 1 8.5 9h7a2 2 0 0 1 1.9 1.3L19 15'), R(3, 15, 18, 4, 1), C(7.5, 19.5, 1.5), C(16.5, 19.5, 1.5)],
  heart: [P('M12 20s-8-4.6-8-10.2A4.3 4.3 0 0 1 12 7a4.3 4.3 0 0 1 8 2.8C20 15.4 12 20 12 20z')],
  star: [P('M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z')],
  moon: [P('M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z')],
  sun: [C(12, 12, 4), P('M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4')],
  gift: [R(3, 8, 18, 4, 1), R(5, 12, 14, 9, 1), P('M12 8v13M12 8c-2-4-6-4-6-1.5S10 8 12 8zM12 8c2-4 6-4 6-1.5S14 8 12 8z')],
  pin: [P('M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z'), C(12, 9.5, 2.5)],
  key: [C(8, 15, 4), P('M11 12l9-9M16 7l3 3')],
  server: [R(3, 4, 18, 7, 1.5), R(3, 13, 18, 7, 1.5), P('M7 7.5v.01M7 16.5v.01')],
  database: [['ellipse', { cx: 12, cy: 6, rx: 8, ry: 3 }], P('M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3')],
  cloud: [P('M7 18a5 5 0 1 1 .9-9.9A6 6 0 0 1 19 10a4 4 0 0 1-1 8z')],
  lock: [R(5, 11, 14, 10), P('M8 11V7a4 4 0 0 1 8 0v4')],
  code: [P('M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16')],
  gear: [C(12, 12, 3), P('M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1')],
};
const ICON_NAMES = Object.keys(ICONS);
const ICON_SIZE = 14;
const ICON_ROOM = 20;
const ICON_SHAPES = new Set(['box', 'state', 'terminal', 'io']);
const hasIcon = (n) => Boolean(n.icon && ICONS[n.icon] && ICON_SHAPES.has(n.shape || 'box'));
function drawIcon(name, x, y) {
  const s = ICON_SIZE / 24;
  return el('g', { class: 'n-icon', transform: `translate(${x} ${y}) scale(${s})`, 'aria-hidden': 'true' },
    ICONS[name].map(([tag, attrs]) => el(tag, attrs)));
}
return { ICONS, ICON_NAMES, ICON_SIZE, ICON_ROOM, ICON_SHAPES, hasIcon, drawIcon };
})();
M.nodes = (() => {
const { el, text } = M.svg;
const { textWidth, ceil4, wrap } = M.text;
const { TYPE } = M.tokens;
const { hasIcon, drawIcon, ICON_ROOM, ICON_SIZE } = M.icons;
const LABEL = { size: TYPE.label, weight: 600 };
const SUB = { size: TYPE.sub, mono: true };
const TAG = { size: TYPE.tag, mono: true, tracking: 0.12, upper: true };
const FIELD = { size: 10 };
const FTYPE = { size: 9, mono: true };
const ROW_H = 18;
const HEAD_H = 30;
const MIN_W = 112;
const MAX_W = 220;
const POINT_SHAPES = new Set(['decision', 'start', 'end']);
function normalizeKind(n) {
  if (n.focal) return 'focal';
  return n.kind || 'backend';
}
function parseField(f) {
  if (Array.isArray(f)) return { name: String(f[0]), type: f[1] ? String(f[1]) : '', key: f[2] ? String(f[2]).toUpperCase() : '' };
  const toks = String(f).replace(':', ' ').split(/\s+/).filter(Boolean);
  const keys = toks.filter((t) => /^(PK|FK|UQ|NN|IDX)$/i.test(t)).map((t) => t.toUpperCase());
  const rest = toks.filter((t) => !/^(PK|FK|UQ|NN|IDX)$/i.test(t));
  return { name: rest[0] || '', type: rest.slice(1).join(' '), key: keys.join(' ') };
}
function tableRows(n) {
  if (n.shape === 'class') {
    const attrs = (n.attrs || []).map((a) => ({ text: String(a) }));
    const methods = (n.methods || []).map((m) => ({ text: String(m) }));
    return { sections: [attrs, methods] };
  }
  return { sections: [(n.fields || []).map(parseField)] };
}
function sizeNode(n, { minW = MIN_W, maxW = MAX_W } = {}) {
  const shape = n.shape || 'box';
  if (shape === 'start' || shape === 'end') {
    n.w = n.h = shape === 'start' ? 20 : 24;
    n.lines = [];
    return n;
  }
  if (shape === 'entity' || shape === 'class') {
    const { sections } = tableRows(n);
    n.sections = sections;
    let inner = textWidth(n.label, LABEL) + (n.tag ? textWidth(n.tag, TAG) + 24 : 0);
    for (const s of sections) {
      for (const r of s) {
        const w = r.text !== undefined
          ? textWidth(r.text, FTYPE)
          : (r.key ? 24 : 0) + textWidth(r.name, FIELD) + (r.type ? textWidth(r.type, FTYPE) + 18 : 0);
        inner = Math.max(inner, w);
      }
    }
    n.headH = shape === 'class' && n.tag ? 42 : HEAD_H;
    if (shape === 'class') inner = Math.max(textWidth(n.label, LABEL), n.tag ? textWidth(n.tag, TAG) : 0, inner - (n.tag ? textWidth(n.tag, TAG) + 24 : 0));
    n.w = ceil4(Math.max(minW + 16, inner + 28));
    const rows = sections.reduce((s, sec) => s + Math.max(sec.length, shape === 'class' ? 1 : 0), 0);
    n.h = n.headH + rows * ROW_H + (sections.length - 1) * 6 + (rows ? 8 : 0);
    n.lines = [n.label];
    return n;
  }
  const room = hasIcon(n) ? ICON_ROOM : 0; // an icon sits left of the label
  const lw = textWidth(n.label, LABEL);
  let lines = [n.label];
  let inner = lw;
  if (lw > maxW - 32 - room) {
    lines = wrap(n.label, maxW - 32 - room, LABEL).slice(0, 2);
    inner = Math.max(...lines.map((l) => textWidth(l, LABEL)));
  }
  const sw = n.sub ? textWidth(n.sub, SUB) : 0;
  const tw = n.tag ? textWidth(n.tag, TAG) + 10 : 0;
  inner = Math.max(inner + room, sw + room, tw ? tw * 2 + 8 : 0);
  let w = ceil4(Math.max(minW, inner + 32));
  const extra = (lines.length - 1) * 15;
  let h = (n.tag ? 64 : n.sub ? 52 : 40) + extra;
  if (shape === 'decision') {
    w = ceil4(Math.max(128, inner * 1.5 + 40));
    h = ceil4(Math.max(72, w * 0.5)) + extra;
  } else if (shape === 'terminal') {
    w = ceil4(Math.max(96, inner + 40));
    h = n.sub ? 48 : 36;
  } else if (shape === 'io') {
    w = ceil4(Math.max(minW, inner + 48));
  } else if (shape === 'state') {
    w = ceil4(Math.max(96, inner + 36));
  }
  n.w = w;
  n.h = h;
  n.lines = lines;
  return n;
}
function fieldY(n, name) {
  if (!n.sections) return null;
  let y = n.y + n.headH + 4;
  for (const sec of n.sections) {
    for (const r of sec) {
      if ((r.name || r.text) === name || (r.text && r.text.split(/[\s:(]/)[0] === name)) return y + ROW_H / 2;
      y += ROW_H;
    }
    y += 6;
  }
  return null;
}
function outline(n, cls) {
  const { x, y, w, h } = n;
  switch (n.shape) {
    case 'decision':
      return el('path', { class: cls, d: `M${x + w / 2},${y} L${x + w},${y + h / 2} L${x + w / 2},${y + h} L${x},${y + h / 2} Z` });
    case 'terminal':
      return el('rect', { class: cls, x, y, width: w, height: h, rx: h / 2 });
    case 'io':
      return el('path', { class: cls, d: `M${x + 10},${y} L${x + w},${y} L${x + w - 10},${y + h} L${x},${y + h} Z` });
    case 'state':
      return el('rect', { class: cls, x, y, width: w, height: h, rx: 14 });
    case 'start':
    case 'end':
      return el('circle', { class: cls, cx: x + w / 2, cy: y + h / 2, r: w / 2 });
    default:
      return el('rect', { class: cls, x, y, width: w, height: h, rx: 6 });
  }
}
function drawTable(n, parts) {
  const { x, y, w } = n;
  const H = n.headH;
  parts.push(el('rect', { class: 'n-head', x: x + 0.5, y: y + 0.5, width: w - 1, height: H - 0.5, rx: 5.5 }));
  parts.push(el('line', { class: 'n-rule', x1: x, y1: y + H, x2: x + w, y2: y + H }));
  if (n.shape === 'class') {
    if (n.tag) parts.push(text({ class: 'n-tag', x: x + w / 2, y: y + 15, 'text-anchor': 'middle', style: 'text-transform:none' }, n.tag));
    parts.push(text({ class: 'n-label', x: x + w / 2, y: y + H - 10.5, 'text-anchor': 'middle' }, n.label));
  } else {
    if (n.tag) parts.push(text({ class: 'n-tag', x: x + 10, y: y + 18 }, n.tag));
    const tagW = n.tag ? textWidth(n.tag, TAG) + 16 : 0;
    parts.push(text({ class: 'n-label', x: x + 10 + tagW, y: y + 19.5 }, n.label));
  }
  let ry = y + H + 4;
  n.sections.forEach((sec, si) => {
    if (si > 0) {
      parts.push(el('line', { class: 'n-rule', x1: x, y1: ry + 2, x2: x + w, y2: ry + 2 }));
      ry += 6;
    }
    if (!sec.length && n.shape === 'class') ry += ROW_H;
    for (const r of sec) {
      const base = ry + 12.5;
      if (r.text !== undefined) {
        parts.push(text({ class: 'n-field-t', x: x + 10, y: base }, r.text));
      } else {
        let fx = x + 10;
        if (r.key) {
          const k = r.key.split(' ')[0];
          parts.push(text({ class: `n-key n-key-${k.toLowerCase()}`, x: fx, y: base }, k));
          fx += 24;
        }
        parts.push(text({ class: 'n-field', x: fx, y: base }, r.name));
        if (r.type) parts.push(text({ class: 'n-field-t', x: x + w - 10, y: base, 'text-anchor': 'end' }, r.type));
      }
      ry += ROW_H;
    }
  });
}
function drawNode(n, { step, extraClass = '', attrs = {} } = {}) {
  const kind = normalizeKind(n);
  const parts = [];
  if (n.shape !== 'start' && n.shape !== 'end') parts.push(outline(n, 'n-mask'));
  parts.push(outline(n, 'n-box'));
  const cx = n.x + n.w / 2;
  if (n.shape === 'end') parts.push(el('circle', { class: 'n-dot', cx, cy: n.y + n.h / 2, r: 6 }));
  else if (n.shape === 'start') {
    /* filled via .sh-start */
  } else if (n.shape === 'entity' || n.shape === 'class') {
    drawTable(n, parts);
  } else {
    let top = n.y;
    if (n.tag) {
      const tw = textWidth(n.tag, TAG) + 10;
      parts.push(el('rect', { class: 'n-tag-box', x: n.x + 8, y: n.y + 8, width: tw, height: 12, rx: 2 }));
      parts.push(text({ class: 'n-tag', x: n.x + 8 + tw / 2, y: n.y + 17, 'text-anchor': 'middle' }, n.tag));
      top += 16;
    }
    const lines = n.lines || [n.label];
    const block = lines.length * 15 + (n.sub ? 14 : 0) - 3;
    const mid = top + (n.y + n.h - top) / 2;
    let y = mid - block / 2 + 11;
    let tx = cx;
    if (hasIcon(n)) {
      const inner = Math.max(...lines.map((l) => textWidth(l, LABEL)), n.sub ? textWidth(n.sub, SUB) : 0);
      const left = cx - (ICON_ROOM + inner) / 2;
      parts.push(drawIcon(n.icon, left, mid - ICON_SIZE / 2));
      tx = left + ICON_ROOM + inner / 2;
    }
    for (const line of lines) {
      parts.push(text({ class: 'n-label', x: tx, y, 'text-anchor': 'middle' }, line));
      y += 15;
    }
    if (n.sub) parts.push(text({ class: 'n-sub', x: tx, y: y + 0.5, 'text-anchor': 'middle' }, n.sub));
  }
  if (n.status) parts.push(el('circle', { class: `n-status st-${n.status}`, cx: n.x + n.w - 9, cy: n.y + 9, r: 3.5 }));
  if (n.change === 'added') parts.push(text({ class: 'n-change', x: n.x + n.w - 8, y: n.y - 5, 'text-anchor': 'end' }, '+ NEU'));
  if (n.change === 'removed') parts.push(text({ class: 'n-change', x: n.x + n.w - 8, y: n.y - 5, 'text-anchor': 'end' }, '− ENTFERNT'));
  if (n.change === 'changed') parts.push(text({ class: 'n-change', x: n.x + n.w - 8, y: n.y - 5, 'text-anchor': 'end' }, '~ GEÄNDERT'));
  const cls = ['sc-node', `k-${kind}`, `sh-${n.shape || 'box'}`, n.change ? `k-change ch-${n.change}` : '', extraClass].filter(Boolean).join(' ');
  return el('g', {
    class: cls,
    'data-sc-node': n.id,
    'data-sc-step': step,
    style: step !== undefined ? `--step:${step}` : undefined,
    tabindex: 0,
    role: 'group',
    'aria-label': [n.label || n.shape, n.sub].filter(Boolean).join(', '),
    ...attrs,
  }, parts);
}
return { MIN_W, MAX_W, POINT_SHAPES, normalizeKind, parseField, sizeNode, fieldY, drawNode };
})();
M.edges = (() => {
const { el, text, roundedPath, esc } = M.svg;
const { textWidth, ceil4 } = M.text;
const { rectsOverlap } = M.svg;
const EDGE_LABEL = { size: 8, mono: true, tracking: 0.06, upper: true };
const HEAD = 8;
function labelBox(label) {
  return { w: ceil4(textWidth(label, EDGE_LABEL) + 10), h: 12 };
}
function unit(a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const l = Math.hypot(dx, dy) || 1;
  return { x: dx / l, y: dy / l };
}
function headAt(tip, d) {
  const bx = tip.x - d.x * HEAD, by = tip.y - d.y * HEAD;
  const px = -d.y * 3.2, py = d.x * 3.2;
  return `M${tip.x},${tip.y} L${bx + px},${by + py} L${bx - px},${by - py} Z`;
}
function placeLabel(route, label, obstacles, placed, others = []) {
  const { w, h } = labelBox(label);
  const segs = [];
  for (let i = 1; i < route.length; i++) {
    const a = route[i - 1], b = route[i];
    const len = Math.abs(b.x - a.x) + Math.abs(b.y - a.y);
    const horiz = a.y === b.y;
    const fits = horiz ? len >= w + 12 : len >= h + 16;
    const stub = i === 1 || i === route.length - 1;
    segs.push({ a, b, len, horiz, score: (fits ? 0 : 1000) + (horiz ? 0 : 60) + (stub && route.length > 2 ? 40 : 0) - len * 0.5 });
  }
  segs.sort((s1, s2) => s1.score - s2.score);
  for (const s of segs) {
    let offsets = s.horiz ? [[0, 0], [0, -10], [0, 10]] : [[0, 0], [-(w / 2 + 5), 0], [w / 2 + 5, 0]];
    if (!s.horiz) {
      const lo = Math.min(s.a.y, s.b.y), hi = Math.max(s.a.y, s.b.y);
      const near = others.flatMap((r) => r.slice(1).map((q, i) => [r[i], q]))
        .find(([p, q]) => p.x === q.x && p.x !== s.a.x && Math.abs(p.x - s.a.x) < 30 && Math.max(p.y, q.y) > lo && Math.min(p.y, q.y) < hi);
      if (near) offsets = near[0].x > s.a.x ? [[-(w / 2 + 5), 0], [0, 0]] : [[w / 2 + 5, 0], [0, 0]];
    }
    for (const [dx, dy] of offsets) {
      for (const t of [0.5, 0.35, 0.65, 0.25, 0.75]) {
        const cx = s.a.x + (s.b.x - s.a.x) * t + dx, cy = s.a.y + (s.b.y - s.a.y) * t + dy;
        const box = { x: cx - w / 2, y: cy - h / 2, w, h };
        if (obstacles.some((o) => rectsOverlap(box, o, 2))) continue;
        if (placed.some((o) => rectsOverlap(box, o, 3))) continue;
        return box;
      }
    }
  }
  return null;
}
const KIND_ENDS = {
  default: { end: 'arrow' }, primary: { end: 'arrow' }, link: { end: 'arrow' }, muted: { end: 'arrow' },
  async: { end: 'arrow', dashed: true }, return: { end: 'arrow', dashed: true },
  'one-one': { start: 'one', end: 'one', rel: true }, 'one-many': { start: 'one', end: 'many', rel: true },
  'many-one': { start: 'many', end: 'one', rel: true }, 'many-many': { start: 'many', end: 'many', rel: true },
  'zero-many': { start: 'one', end: 'zero-many', rel: true }, 'one-zero': { start: 'one', end: 'zero-one', rel: true },
  extends: { end: 'triangle', rel: true }, implements: { end: 'triangle', dashed: true, rel: true },
  composes: { start: 'diamond-filled', rel: true }, aggregates: { start: 'diamond', rel: true },
  depends: { end: 'open', dashed: true, rel: true }, assoc: { rel: true }, line: {},
};
const GLYPH_LEN = { arrow: HEAD - 1, triangle: 12, diamond: 16, 'diamond-filled': 16, open: 0, one: 0, many: 0, 'zero-many': 0, 'zero-one': 0 };
function glyph(type, p, d, kind) {
  const px = -d.y, py = d.x;
  const at = (back, side) => ({ x: p.x - d.x * back + px * side, y: p.y - d.y * back + py * side });
  const P = (pts) => pts.map((q, i) => `${i ? 'L' : 'M'}${q.x},${q.y}`).join(' ');
  switch (type) {
    case 'arrow':
      return el('path', { class: `e-head m-${['async', 'return'].includes(kind) ? 'default' : kind}`, d: headAt(p, d) });
    case 'triangle':
      return el('path', { class: 'e-glyph hollow', d: `${P([p, at(12, 7), at(12, -7)])} Z` });
    case 'diamond':
    case 'diamond-filled':
      return el('path', { class: `e-glyph ${type === 'diamond' ? 'hollow' : 'filled'}`, d: `${P([p, at(8, 5), at(16, 0), at(8, -5)])} Z` });
    case 'open':
      return el('path', { class: 'e-glyph stroke', d: P([at(9, 5), p, at(9, -5)]) });
    case 'one':
      return el('path', { class: 'e-glyph stroke', d: `${P([at(7, 6), at(7, -6)])} ${P([at(11, 6), at(11, -6)])}` });
    case 'many':
    case 'zero-many':
      return el('path', { class: 'e-glyph stroke', d: `${P([at(12, 0), at(0, 6)])} ${P([at(12, 0), at(0, -6)])} ${P([at(12, 0), at(0, 0)])} ${type === 'many' ? P([at(15, 6), at(15, -6)]) : ''}` })
        + (type === 'zero-many' ? el('circle', { class: 'e-glyph hollow', cx: at(18, 0).x, cy: at(18, 0).y, r: 3.5 }) : '');
    case 'zero-one':
      return el('path', { class: 'e-glyph stroke', d: P([at(8, 6), at(8, -6)]) }) + el('circle', { class: 'e-glyph hollow', cx: at(15, 0).x, cy: at(15, 0).y, r: 3.5 });
    default:
      return '';
  }
}
function drawEdge(e, { step, labelBoxAt } = {}) {
  const kind = e.kind || 'default';
  const ends = KIND_ENDS[kind] || KIND_ENDS.default;
  const endG = ends.end || (e.both ? 'arrow' : null);
  const startG = ends.start || (e.both ? 'arrow' : null);
  const pts = e.route.map((p) => ({ ...p }));
  const n = pts.length;
  const dEnd = unit(pts[n - 2], pts[n - 1]);
  const dStart = unit(pts[1], pts[0]);
  const tip = { ...e.route[n - 1] };
  const tail = { ...e.route[0] };
  if (endG) pts[n - 1] = { x: tip.x - dEnd.x * GLYPH_LEN[endG], y: tip.y - dEnd.y * GLYPH_LEN[endG] };
  if (startG) pts[0] = { x: tail.x - dStart.x * GLYPH_LEN[startG], y: tail.y - dStart.y * GLYPH_LEN[startG] };
  const d = roundedPath(pts, 7);
  const dashed = !!ends.dashed;
  const parts = [el('path', { class: `e-line${dashed ? ' dashed' : ' sc-draw'}`, d, pathLength: dashed ? undefined : 1 })];
  if (endG) parts.push(glyph(endG, tip, dEnd, kind));
  if (startG) parts.push(glyph(startG, tail, dStart, kind));
  if (e.label && labelBoxAt) {
    const b = labelBoxAt;
    parts.push(el('g', { class: 'e-label-g' }, [
      el('rect', { class: 'e-label-bg', x: b.x, y: b.y, width: b.w, height: b.h, rx: 2 }),
      text({ class: 'e-label', x: b.x + b.w / 2, y: b.y + 8.6, 'text-anchor': 'middle' }, e.label),
    ]));
  }
  return el('g', {
    class: `sc-edge ek-${ends.rel ? 'rel' : kind}${e.change ? ` ch-${e.change}` : ''}`,
    'data-sc-edge': e.id,
    'data-from': e.from,
    'data-to': e.to,
    'data-sc-step': step,
    style: step ? `--step:${step}` : undefined,
  }, parts);
}
return { EDGE_LABEL, labelBox, placeLabel, KIND_ENDS, drawEdge, esc };
})();
M.legend = (() => {
const { el, text } = M.svg;
const { textWidth } = M.text;
const NODE_NAMES = { focal: 'Fokus', backend: 'Dienst', store: 'Speicher', external: 'Extern', input: 'Eingang', optional: 'Optional', security: 'Sicherheit', muted: 'Kontext' };
const EDGE_NAMES = { default: 'Aufruf / Fluss', primary: 'Hauptweg', link: 'HTTP / API', async: 'Asynchron', return: 'Rückgabe', muted: 'Nebenweg' };
function legendOptions(spec) {
  const l = spec && spec.legend;
  return l && typeof l === 'object' ? { title: l.title, entries: l.entries || {} } : { entries: {} };
}
function legendLabels(spec) {
  const { entries } = legendOptions(spec);
  return Object.fromEntries(Object.entries(entries).filter(([, e]) => e && e.label).map(([k, e]) => [k, e.label]));
}
function legend({ nodeKinds = [], edgeKinds = [], x, y, w, extra = [], custom = { entries: {} } }) {
  const entries = custom.entries || {};
  const all = [
    ...nodeKinds.map((k) => ({ type: 'node', k, key: k, label: NODE_NAMES[k] || k })),
    ...edgeKinds.map((k) => ({ type: 'edge', k, key: k, label: EDGE_NAMES[k] || k })),
    ...extra,
  ];
  const keys = all.map((it) => it.key).filter(Boolean);
  const items = all
    .filter((it) => !(it.key && entries[it.key] && entries[it.key].visible === false))
    .map((it) => (it.key && entries[it.key] && entries[it.key].label ? { ...it, label: entries[it.key].label } : it));
  if (items.length < 2) return { svg: '', h: 0, keys };
  const parts = [
    el('line', { class: 'lg-rule', x1: x, y1: y, x2: x + w, y2: y }),
    text({ class: 'lg-title', x, y: y + 16 }, (custom.title || 'Legende').toUpperCase()),
  ];
  let cx = x;
  let cy = y + 34;
  for (const it of items) {
    const tw = textWidth(it.label, { size: 9 }) + (it.type === 'text' ? 24 : 44);
    if (cx + tw > x + w && cx > x) {
      cx = x;
      cy += 18;
    }
    const hit = it.type === 'node' ? { 'data-sc-kind': it.k } : it.type === 'edge' ? { 'data-sc-ekind': it.k } : {};
    const start = parts.length;
    if (it.type === 'node') {
      parts.push(el('g', { class: `k-${it.k}` }, el('rect', { class: 'n-box', x: cx, y: cy - 8, width: 14, height: 10, rx: 2 })));
    } else if (it.type === 'edge') {
      const dashed = it.k === 'async' || it.k === 'return';
      parts.push(el('g', { class: `ek-${it.k}` }, [
        el('path', { class: `e-line${dashed ? ' dashed' : ''}`, d: `M${cx},${cy - 3} L${cx + 20},${cy - 3}` }),
        el('path', { class: `e-head m-${dashed ? 'default' : it.k}`, d: `M${cx + 26},${cy - 3} L${cx + 19},${cy - 6} L${cx + 19},${cy} Z` }),
      ]));
    } else if (it.swatch) {
      parts.push(el('rect', { class: it.swatch, x: cx, y: cy - 8, width: 14, height: 10, rx: 2 }));
    }
    parts.push(text({ class: 'lg-text', x: cx + (it.type === 'edge' ? 32 : it.type === 'text' ? 0 : 20), y: cy }, it.label));
    if (hit['data-sc-kind'] || hit['data-sc-ekind']) parts.splice(start, parts.length - start, el('g', hit, [el('rect', { x: cx - 2, y: cy - 11, width: tw - 6, height: 15, fill: 'transparent' }), ...parts.slice(start)]));
    cx += tw;
  }
  return { svg: el('g', { class: 'sc-legend' }, parts), h: cy - y + 10, keys };
}
return { legendOptions, legendLabels, legend };
})();
M.route = (() => {
const STUB = 18; // straight run out of a port before the first bend (arrowhead room)
const PAD = 8; // clearance around node boxes
const DIRS = { L: { x: -1, y: 0 }, R: { x: 1, y: 0 }, T: { x: 0, y: -1 }, B: { x: 0, y: 1 } };
const SIDES = ['L', 'R', 'T', 'B'];
const POINT = new Set(['decision', 'start', 'end']);
function sidePoint(n, side, t = 0.5) {
  switch (side) {
    case 'L': return { x: n.x, y: n.y + n.h * t };
    case 'R': return { x: n.x + n.w, y: n.y + n.h * t };
    case 'T': return { x: n.x + n.w * t, y: n.y };
    default: return { x: n.x + n.w * t, y: n.y + n.h };
  }
}
function allowedSides() {
  return SIDES;
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function segHitsBox(a, b, r) {
  if (a.x === b.x) {
    const y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
    return a.x > r.x && a.x < r.x + r.w && y1 > r.y && y0 < r.y + r.h;
  }
  const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x);
  return a.y > r.y && a.y < r.y + r.h && x1 > r.x && x0 < r.x + r.w;
}
function simplify(pts) {
  const out = [];
  for (const p of pts) {
    const q = { x: Math.round(p.x * 2) / 2, y: Math.round(p.y * 2) / 2 };
    const last = out[out.length - 1];
    if (last && last.x === q.x && last.y === q.y) continue;
    out.push(q);
  }
  for (let i = out.length - 2; i > 0; i--) {
    const a = out[i - 1], b = out[i], c = out[i + 1];
    if ((a.x === b.x && b.x === c.x) || (a.y === b.y && b.y === c.y)) out.splice(i, 1);
  }
  return out;
}
function length(pts) {
  let l = 0;
  for (let i = 1; i < pts.length; i++) l += Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
  return l;
}
function isOrthogonal(pts) {
  for (let i = 1; i < pts.length; i++) if (pts[i].x !== pts[i - 1].x && pts[i].y !== pts[i - 1].y) return false;
  return true;
}
function backtracks(pts) {
  for (let i = 2; i < pts.length; i++) {
    const d1 = { x: Math.sign(pts[i - 1].x - pts[i - 2].x), y: Math.sign(pts[i - 1].y - pts[i - 2].y) };
    const d2 = { x: Math.sign(pts[i].x - pts[i - 1].x), y: Math.sign(pts[i].y - pts[i - 1].y) };
    if (d1.x === -d2.x && d1.y === -d2.y && (d1.x || d1.y)) return true;
  }
  return false;
}
function nearest(values, v, k) {
  return [...values].sort((a, b) => Math.abs(a - v) - Math.abs(b - v)).slice(0, k);
}
function candidates(pS, sS, pT, sT, ch) {
  const dS = DIRS[sS], dT = DIRS[sT];
  const a = { x: pS.x + dS.x * STUB, y: pS.y + dS.y * STUB };
  const b = { x: pT.x + dT.x * STUB, y: pT.y + dT.y * STUB };
  const mids = [];
  if (a.x === b.x || a.y === b.y) mids.push([]);
  mids.push([{ x: b.x, y: a.y }], [{ x: a.x, y: b.y }]);
  const xs = new Set([...nearest(ch.xs, (a.x + b.x) / 2, 4), (a.x + b.x) / 2]);
  const ys = new Set([...nearest(ch.ys, (a.y + b.y) / 2, 4), (a.y + b.y) / 2]);
  for (const x of xs) mids.push([{ x, y: a.y }, { x, y: b.y }]);
  for (const y of ys) mids.push([{ x: a.x, y }, { x: b.x, y }]);
  const x1s = nearest(ch.xs, a.x, 2), x2s = nearest(ch.xs, b.x, 2);
  const y1s = nearest(ch.ys, a.y, 2), y2s = nearest(ch.ys, b.y, 2);
  for (const y of nearest(ch.ys, (a.y + b.y) / 2, 3)) {
    for (const x1 of x1s) for (const x2 of x2s) mids.push([{ x: x1, y: a.y }, { x: x1, y }, { x: x2, y }, { x: x2, y: b.y }]);
  }
  for (const x of nearest(ch.xs, (a.x + b.x) / 2, 3)) {
    for (const y1 of y1s) for (const y2 of y2s) mids.push([{ x: a.x, y: y1 }, { x, y: y1 }, { x, y: y2 }, { x: b.x, y: y2 }]);
  }
  return mids.map((m) => ({ pts: simplify([pS, a, ...m, b, pT]), raw: [pS, a, ...m, b, pT] }));
}
function clearOf(pts, boxes) {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    for (const r of boxes) {
      const own = (i === 1 && r.id === pts.src) || (i === pts.length - 1 && r.id === pts.dst);
      const box = own ? r : { x: r.x - PAD, y: r.y - PAD, w: r.w + 2 * PAD, h: r.h + 2 * PAD, id: r.id };
      if (!own && segHitsBox(a, b, box)) return false;
      if (own && i !== 1 && i !== pts.length - 1 && segHitsBox(a, b, r)) return false;
    }
  }
  return true;
}
function crossings(pts, routes) {
  let n = 0;
  for (const r of routes) {
    for (let i = 1; i < pts.length; i++) {
      for (let j = 1; j < r.length; j++) {
        const a = pts[i - 1], b = pts[i], c = r[j - 1], d = r[j];
        const h1 = a.y === b.y, h2 = c.y === d.y;
        if (h1 === h2) continue;
        const [hA, hB, vA, vB] = h1 ? [a, b, c, d] : [c, d, a, b];
        const x = vA.x, y = hA.y;
        if (x > Math.min(hA.x, hB.x) && x < Math.max(hA.x, hB.x) && y > Math.min(vA.y, vB.y) && y < Math.max(vA.y, vB.y)) n++;
      }
    }
  }
  return n;
}
function bestRoute(S, T, pS, sS, pT, sT, ctx) {
  let best = null;
  for (const c of candidates(pS, sS, pT, sT, ctx.channels)) {
    const pts = c.pts;
    if (pts.length < 2 || !isOrthogonal(pts) || backtracks(pts)) continue;
    pts.src = S.id;
    pts.dst = T.id;
    if (!clearOf(pts, ctx.boxes)) continue;
    const last = pts[pts.length - 1], prev = pts[pts.length - 2];
    const dT = DIRS[sT];
    const into = { x: Math.sign(last.x - prev.x), y: Math.sign(last.y - prev.y) };
    if (into.x !== -dT.x || into.y !== -dT.y) continue;
    const first = pts[1];
    const out = { x: Math.sign(first.x - pts[0].x), y: Math.sign(first.y - pts[0].y) };
    const dS = DIRS[sS];
    if (out.x !== dS.x || out.y !== dS.y) continue;
    const score = length(pts) + 36 * (pts.length - 2) + 60 * crossings(pts, ctx.routes);
    if (!best || score < best.score) best = { pts, score };
  }
  return best;
}
const AXIS_SIDES = { LR: ['L', 'R'], TB: ['T', 'B'] };
function routeEdges(nodes, edges, { dir = 'LR', channels }) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const boxes = nodes.map((n) => ({ x: n.x, y: n.y, w: n.w, h: n.h, id: n.id }));
  const ctx = { boxes, channels, routes: [] };
  const problems = [];
  const primary = AXIS_SIDES[dir] || AXIS_SIDES.LR;
  const order = [...edges].sort((e1, e2) => (e2.kind === 'primary') - (e1.kind === 'primary'));
  for (const e of order) {
    const S = byId.get(e.from), T = byId.get(e.to);
    let best = null;
    for (const sS of e.fieldYS != null ? ['L', 'R'] : allowedSides(S)) {
      for (const sT of e.fieldYT != null ? ['L', 'R'] : allowedSides(T)) {
        const r = bestRoute(S, T, endPoint(S, sS, e.fieldYS), sS, endPoint(T, sT, e.fieldYT), sT, ctx);
        if (!r) continue;
        const pen = (primary.includes(sS) ? 0 : 14) + (primary.includes(sT) ? 0 : 14);
        if (!best || r.score + pen < best.score) best = { ...r, score: r.score + pen, sS, sT };
      }
    }
    if (!best) {
      problems.push({ code: 'E_ROUTE', at: `edges.${e.id}`, msg: `no clear path ${e.from}→${e.to}`, fix: 'move one endpoint to a free row/col so the path does not pass behind other nodes' });
      e.route = null;
      continue;
    }
    e.sS = best.sS;
    e.sT = best.sT;
    ctx.routes.push(best.pts);
  }
  const ends = new Map();
  for (const e of edges) {
    if (!e.sS) continue;
    if (e.fieldYS != null) e.tS = e.fieldYS;
    if (e.fieldYT != null) e.tT = e.fieldYT;
    for (const [nodeId, side, otherId, role] of [[e.from, e.sS, e.to, 'S'], [e.to, e.sT, e.from, 'T']]) {
      if ((role === 'S' ? e.fieldYS : e.fieldYT) != null) continue;
      const key = `${nodeId}:${side}`;
      if (!ends.has(key)) ends.set(key, []);
      const other = byId.get(otherId);
      const pref = side === 'L' || side === 'R' ? other.y + other.h / 2 : other.x + other.w / 2;
      ends.get(key).push({ e, role, pref });
    }
  }
  for (const [key, list] of ends) {
    const [nodeId, side] = key.split(':');
    const n = byId.get(nodeId);
    const vertical = side === 'L' || side === 'R';
    const lo = vertical ? n.y : n.x;
    const span = vertical ? n.h : n.w;
    if (POINT.has(n.shape) || list.length === 1) {
      for (const it of list) {
        setPort(it, lo + span / 2);
        if (!POINT.has(n.shape)) it.e[it.role === 'S' ? 'singleS' : 'singleT'] = true;
      }
      continue;
    }
    const min = lo + span * 0.18, max = lo + span * 0.82;
    const gap = Math.min(14, (max - min) / Math.max(1, list.length - 1));
    list.sort((a, b) => a.pref - b.pref);
    const pos = list.map((it) => clamp(it.pref, min, max));
    for (let i = 1; i < pos.length; i++) pos[i] = Math.max(pos[i], pos[i - 1] + gap);
    const over = pos[pos.length - 1] - max;
    if (over > 0) for (let i = pos.length - 1; i >= 0; i--) pos[i] = i === pos.length - 1 ? max : Math.min(pos[i], pos[i + 1] - gap);
    list.forEach((it, i) => setPort(it, pos[i]));
  }
  for (const e of edges) {
    if (!e.sS || e.singleS === e.singleT) continue;
    const horiz = 'LR'.includes(e.sS) && 'LR'.includes(e.sT);
    const vert = 'TB'.includes(e.sS) && 'TB'.includes(e.sT);
    if (!horiz && !vert) continue;
    const single = byId.get(e.singleS ? e.from : e.to);
    const v = e.singleS ? e.tT : e.tS;
    const [a0, a1] = horiz ? [single.y, single.y + single.h] : [single.x, single.x + single.w];
    if (v >= a0 + 8 && v <= a1 - 8) {
      if (e.singleS) e.tS = v;
      else e.tT = v;
    }
  }
  for (const e of edges) {
    if (!e.singleS || !e.singleT) continue;
    const S = byId.get(e.from), T = byId.get(e.to);
    const horiz = 'LR'.includes(e.sS) && 'LR'.includes(e.sT);
    const vert = 'TB'.includes(e.sS) && 'TB'.includes(e.sT);
    if (!horiz && !vert) continue;
    const [a0, a1, b0, b1] = horiz ? [S.y, S.y + S.h, T.y, T.y + T.h] : [S.x, S.x + S.w, T.x, T.x + T.w];
    const lo = Math.max(a0, b0) + 10, hi = Math.min(a1, b1) - 10;
    if (lo > hi) continue;
    const v = clamp(((a0 + a1) / 2 + (b0 + b1) / 2) / 2, lo, hi);
    e.tS = v;
    e.tT = v;
  }
  function setPort(it, v) {
    if (it.role === 'S') it.e.tS = v;
    else it.e.tT = v;
  }
  ctx.routes = [];
  for (const e of order) {
    if (!e.sS) continue;
    const S = byId.get(e.from), T = byId.get(e.to);
    const pS = portAt(S, e.sS, e.tS), pT = portAt(T, e.sT, e.tT);
    let r = bestRoute(S, T, pS, e.sS, pT, e.sT, ctx);
    if (!r) r = bestRoute(S, T, endPoint(S, e.sS, e.fieldYS), e.sS, endPoint(T, e.sT, e.fieldYT), e.sT, ctx);
    if (!r) {
      problems.push({ code: 'E_ROUTE', at: `edges.${e.id}`, msg: `no clear path ${e.from}→${e.to}`, fix: 'move one endpoint to a free row/col' });
      continue;
    }
    e.route = r.pts;
    ctx.routes.push(r.pts);
  }
  separateTracks(edges.filter((e) => e.route));
  return problems;
}
function endPoint(n, side, fieldY) {
  if (fieldY == null) return sidePoint(n, side);
  return { x: side === 'L' ? n.x : n.x + n.w, y: fieldY };
}
function portAt(n, side, v) {
  if (side === 'L') return { x: n.x, y: v };
  if (side === 'R') return { x: n.x + n.w, y: v };
  if (side === 'T') return { x: v, y: n.y };
  return { x: v, y: n.y + n.h };
}
function separateTracks(edges) {
  for (const axis of ['x', 'y']) {
    const other = axis === 'x' ? 'y' : 'x';
    const buckets = new Map();
    for (const e of edges) {
      const p = e.route;
      for (let i = 1; i < p.length - 2; i++) {
        const a = p[i], b = p[i + 1];
        if (!b || a[axis] !== b[axis]) continue;
        const key = a[axis];
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push({ e, i, lo: Math.min(a[other], b[other]), hi: Math.max(a[other], b[other]) });
      }
    }
    for (const segs of buckets.values()) {
      if (segs.length < 2) continue;
      segs.sort((s1, s2) => s1.lo - s2.lo);
      const tracks = [];
      for (const s of segs) {
        let t = tracks.findIndex((tr) => tr.every((o) => o.hi <= s.lo || o.lo >= s.hi || o.e.from === s.e.from));
        if (t < 0) {
          tracks.push([]);
          t = tracks.length - 1;
        }
        tracks[t].push(s);
        s.track = t;
      }
      if (tracks.length < 2) continue;
      for (const s of segs) {
        const off = (s.track - (tracks.length - 1) / 2) * 8;
        s.e.route[s.i] = { ...s.e.route[s.i], [axis]: s.e.route[s.i][axis] + off };
        s.e.route[s.i + 1] = { ...s.e.route[s.i + 1], [axis]: s.e.route[s.i + 1][axis] + off };
      }
    }
  }
}
return { routeEdges, sidePoint };
})();
M.graph = (() => {
const { el, text, roundedPath } = M.svg;
const { textWidth, ceil4 } = M.text;
const { sizeNode, drawNode, normalizeKind, fieldY } = M.nodes;
const { drawEdge, placeLabel, labelBox } = M.edges;
const { legend, legendOptions } = M.legend;
const { routeEdges } = M.route;
const { compressSteps } = M.motion;
const family = 'graph';
const BUDGET = { strict: [7, 9], balanced: [9, 12], wide: [16, 20], faithful: [24, 36], off: [1e9, 1e9] };
const TYPE_BUDGET = { medallion: 'wide', 'dp-integration': 'wide', er: 'wide', 'db-schema': 'wide', 'it-state': 'wide', swimlane: 'wide' };
const GROUP_PAD = 16;
const GROUP_TOP = 22;
const DEFAULT_SHAPE = { er: 'entity', 'db-schema': 'entity', 'uml-class': 'class', state: 'state' };
const NO_LEGEND = new Set(['er', 'db-schema', 'uml-class', 'state', 'flowchart']);
const STATUS_NAMES = { ok: 'Gesund', risk: 'Gefährdet', legacy: 'Altbestand', retire: 'Ablösen' };
function fromStages(spec) {
  const nodes = [];
  const groups = [];
  const edges = spec.edges ? [...spec.edges] : [];
  spec.stages.forEach((st, c) => {
    const gid = `stage${c}`;
    groups.push({ id: gid, label: st.label, style: st.style });
    (st.items || []).forEach((it, r) => {
      const o = typeof it === 'string' ? { label: it } : { ...it };
      o.id = o.id || `${gid}_${r}`;
      nodes.push({ ...o, row: o.row ?? r, col: c, group: st.plain ? undefined : gid, kind: o.kind || st.kind });
    });
  });
  if (!spec.edges) {
    for (let c = 0; c + 1 < spec.stages.length; c++) {
      const a = nodes.filter((n) => n.col === c), b = nodes.filter((n) => n.col === c + 1);
      a.forEach((n, i) => b.length && edges.push([n.id, b[Math.min(i, b.length - 1)].id, '', c === 0 ? 'default' : 'primary']));
    }
  }
  const out = { ...spec, nodes, edges, groups: groups.filter((g) => nodes.some((n) => n.group === g.id)) };
  delete out.stages;
  return out;
}
function normEdges(spec, ids, problems) {
  const seen = new Map();
  return (spec.edges || []).map((raw, i) => {
    const e = Array.isArray(raw) ? { from: raw[0], to: raw[1], label: raw[2] || undefined, kind: raw[3] } : { ...raw };
    e.kind = e.kind || 'default';
    for (const end of ['from', 'to']) {
      if (!ids.has(e[end]) && String(e[end]).includes('.')) {
        const str = String(e[end]);
        for (let k = str.lastIndexOf('.'); k > 0; k = str.lastIndexOf('.', k - 1)) {
          if (ids.has(str.slice(0, k))) {
            e[end === 'from' ? 'fieldS' : 'fieldT'] = str.slice(k + 1);
            e[end] = str.slice(0, k);
            break;
          }
        }
      }
      if (!ids.has(e[end])) {
        const near = [...ids].filter((id) => id.toLowerCase().startsWith(String(e[end]).toLowerCase().slice(0, 2))).slice(0, 3);
        problems.push({ code: 'E_EDGE_NODE', at: `edges[${i}]`, msg: `unknown node "${e[end]}"`, fix: near.length ? `use one of: ${near.join(', ')}` : 'add the node or fix the id' });
      }
    }
    if (e.from === e.to) e.self = true;
    let id = e.id || `${e.from}-${e.to}`;
    if (seen.has(id)) id = `${id}-${seen.get(id) + 1}`;
    seen.set(id, (seen.get(id) || 0) + 1);
    e.id = id;
    return e;
  });
}
function ranks(nodes, edges) {
  const out = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) out.get(e.from)?.push(e.to);
  const state = new Map();
  const back = new Set();
  const visit = (id) => {
    state.set(id, 1);
    for (const t of out.get(id) || []) {
      if (state.get(t) === 1) back.add(`${id}>${t}`);
      else if (!state.get(t)) visit(t);
    }
    state.set(id, 2);
  };
  nodes.forEach((n) => !state.get(n.id) && visit(n.id));
  const rank = new Map(nodes.map((n) => [n.id, 0]));
  let changed = true;
  for (let iter = 0; changed && iter < nodes.length + 1; iter++) {
    changed = false;
    for (const e of edges) {
      if (back.has(`${e.from}>${e.to}`) || !rank.has(e.to) || !rank.has(e.from)) continue;
      if (rank.get(e.to) < rank.get(e.from) + 1) {
        rank.set(e.to, rank.get(e.from) + 1);
        changed = true;
      }
    }
  }
  return { rank, back };
}
function autoPlace(nodes, edges, dir, info) {
  const missing = nodes.filter((n) => n.row === undefined || n.col === undefined);
  if (!missing.length) return;
  const { rank } = ranks(nodes, edges);
  const main = dir === 'TB' ? 'row' : 'col';
  const cross = dir === 'TB' ? 'col' : 'row';
  const taken = new Set(nodes.filter((n) => !missing.includes(n)).map((n) => `${n.row},${n.col}`));
  const preds = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) preds.get(e.to)?.push(e.from);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  missing.sort((a, b) => rank.get(a.id) - rank.get(b.id));
  for (const n of missing) {
    n[main] = n[main] ?? rank.get(n.id);
    const ps = preds.get(n.id).map((p) => byId.get(p)).filter((p) => p[cross] !== undefined);
    let want = n[cross] ?? (ps.length ? Math.round(ps.reduce((s, p) => s + p[cross], 0) / ps.length) : 0);
    for (let d = 0; d < 60; d++) {
      const cands = d === 0 ? [want] : [want + d, want - d].filter((v) => v >= 0);
      const hit = cands.find((c) => !taken.has(dir === 'TB' ? `${n.row},${c}` : `${c},${n.col}`));
      if (hit !== undefined) {
        n[cross] = hit;
        break;
      }
    }
    taken.add(`${n.row},${n.col}`);
  }
  info.push({ code: 'I_AUTOPLACED', msg: `auto-placed ${missing.length} node(s)`, fix: 'add row/col to control layout' });
}
function render(input) {
  const spec = input.stages ? fromStages(input) : input;
  const problems = [];
  const info = [];
  const dir = spec.dir || (spec.type === 'flowchart' || spec.variant === 'vertical' ? 'TB' : 'LR');
  const laneIdx = new Map((spec.lanes || []).map((l, i) => [typeof l === 'string' ? l : l.id, i]));
  const nodes = spec.nodes.map((n) => {
    const o = { ...n, kind: normalizeKind(n), shape: n.shape || DEFAULT_SHAPE[spec.type] || 'box' };
    if (o.lane !== undefined && o.row === undefined) o.row = laneIdx.get(o.lane) ?? 0;
    return o;
  });
  nodes.forEach((n, i) => {
    if (n.label === undefined) {
      if (n.shape === 'start' || n.shape === 'end') n.label = n.shape === 'start' ? 'Start' : 'End';
      else problems.push({ code: 'E_SPEC', at: `nodes[${i}].label`, msg: 'is required', fix: 'add a label (only start/end shapes may omit it)' });
    }
    if (n.lane !== undefined && !laneIdx.has(n.lane)) problems.push({ code: 'E_LANE', at: `nodes[${i}]`, msg: `unknown lane "${n.lane}"`, fix: `use one of: ${[...laneIdx.keys()].join(', ')}` });
  });
  const ids = new Set();
  nodes.forEach((n, i) => {
    if (ids.has(n.id)) problems.push({ code: 'E_DUP_ID', at: `nodes[${i}]`, msg: `duplicate id "${n.id}"`, fix: 'ids must be unique' });
    ids.add(n.id);
  });
  const allEdges = normEdges(spec, ids, problems).filter((e) => ids.has(e.from) && ids.has(e.to));
  const selfEdges = allEdges.filter((e) => e.self);
  const edges = allEdges.filter((e) => !e.self);
  if (problems.some((p) => p.code.startsWith('E_'))) return { problems };
  autoPlace(nodes, edges, dir, info);
  const cells = new Map();
  for (const n of nodes) {
    const key = `${n.row},${n.col}`;
    if (cells.has(key)) problems.push({ code: 'E_CELL_TAKEN', at: `nodes.${n.id}`, msg: `row ${n.row} col ${n.col} already holds "${cells.get(key)}"`, fix: 'give each node its own row/col' });
    cells.set(key, n.id);
  }
  if (problems.length) return { problems };
  const focal = nodes.filter((n) => n.kind === 'focal');
  if (focal.length > 2) problems.push({ code: 'W_FOCAL', at: 'nodes', msg: `${focal.length} focal nodes`, fix: 'keep the accent on 1–2 nodes; demote the rest to backend' });
  const budget = spec.budget || TYPE_BUDGET[spec.type] || 'balanced';
  const [maxN, maxE] = BUDGET[budget];
  if (nodes.length > maxN || edges.length > maxE) {
    problems.push({ code: 'W_BUDGET', at: '(root)', msg: `${nodes.length} nodes / ${edges.length} edges over the ${budget} budget (${maxN}/${maxE})`, fix: 'merge nodes that travel together, split into overview + detail, or set budget:"faithful"' });
  }
  nodes.forEach((n) => sizeNode(n));
  const colIdx = [...new Set(nodes.map((n) => n.col))].sort((a, b) => a - b);
  const rowIdx = [...new Set(nodes.map((n) => n.row))].sort((a, b) => a - b);
  const ci = new Map(colIdx.map((c, i) => [c, i]));
  const ri = new Map(rowIdx.map((r, i) => [r, i]));
  nodes.forEach((n) => { n.c = ci.get(n.col); n.r = ri.get(n.row); });
  const colW = colIdx.map((_, i) => Math.max(...nodes.filter((n) => n.c === i).map((n) => n.w)));
  const rowH = rowIdx.map((_, i) => Math.max(...nodes.filter((n) => n.r === i).map((n) => n.h)));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const grouped = (spec.groups && spec.groups.length) || nodes.some((n) => n.group);
  const extra = grouped ? GROUP_PAD * 2 : 0;
  const gapX = colIdx.slice(1).map(() => (dir === 'TB' ? 64 : 72) + extra);
  const gapY = rowIdx.slice(1).map(() => (dir === 'TB' ? 64 : 52) + extra);
  for (const e of edges) {
    if (!e.label) continue;
    const a = byId.get(e.from), b = byId.get(e.to);
    const need = labelBox(e.label).w + 28 + extra;
    if (a.c !== b.c) {
      const g = Math.min(a.c, b.c);
      gapX[g] = Math.min(220, Math.max(gapX[g], need));
    } else {
      const g = Math.min(a.r, b.r);
      gapY[g] = Math.max(gapY[g], 40 + extra);
    }
  }
  const colX = [];
  let acc = 0;
  colW.forEach((w, i) => { colX.push(acc); acc += w + (gapX[i] || 0); });
  const rowY = [];
  acc = 0;
  rowH.forEach((h, i) => { rowY.push(acc); acc += h + (gapY[i] || 0); });
  for (const n of nodes) {
    n.x = colX[n.c] + (colW[n.c] - n.w) / 2;
    n.y = rowY[n.r] + (rowH[n.r] - n.h) / 2;
  }
  const lastX = colX[colX.length - 1] + colW[colW.length - 1];
  const lastY = rowY[rowY.length - 1] + rowH[rowH.length - 1];
  const channels = {
    xs: [-28 - extra / 2, ...gapX.map((g, i) => colX[i] + colW[i] + g / 2), lastX + 28 + extra / 2],
    ys: [-28 - extra / 2, ...gapY.map((g, i) => rowY[i] + rowH[i] + g / 2), lastY + 28 + extra / 2],
  };
  for (const e of edges) {
    for (const [end, fk, yk] of [['from', 'fieldS', 'fieldYS'], ['to', 'fieldT', 'fieldYT']]) {
      if (!e[fk]) continue;
      const y = fieldY(byId.get(e[end]), e[fk]);
      if (y == null) problems.push({ code: 'W_FIELD', at: `edges.${e.id}`, msg: `"${e[end]}" has no field "${e[fk]}"`, fix: 'use a field name listed in that entity' });
      else e[yk] = y;
    }
  }
  problems.push(...routeEdges(nodes, edges, { dir, channels }));
  for (const e of selfEdges) {
    const n = byId.get(e.from);
    const x0 = n.x + n.w * 0.7, y0 = n.y, x1 = n.x + n.w, y1 = n.y + Math.min(n.h * 0.4, 18);
    e.route = [{ x: x0, y: y0 }, { x: x0, y: y0 - 18 }, { x: x1 + 22, y: y0 - 18 }, { x: x1 + 22, y: y1 }, { x: x1, y: y1 }];
    edges.push(e);
  }
  const groupDefs = new Map((spec.groups || []).map((g) => [g.id, { ...g, members: new Set(g.nodes || []) }]));
  for (const n of nodes) {
    if (!n.group) continue;
    if (!groupDefs.has(n.group)) groupDefs.set(n.group, { id: n.group, label: n.group, members: new Set() });
    groupDefs.get(n.group).members.add(n.id);
  }
  const groups = [];
  for (const g of groupDefs.values()) {
    const ms = [...g.members].map((id) => byId.get(id)).filter(Boolean);
    if (!ms.length) continue;
    const x0 = Math.min(...ms.map((n) => n.x)) - GROUP_PAD;
    const y0 = Math.min(...ms.map((n) => n.y)) - GROUP_TOP;
    const x1 = Math.max(...ms.map((n) => n.x + n.w)) + GROUP_PAD;
    const y1 = Math.max(...ms.map((n) => n.y + n.h)) + GROUP_PAD;
    const box = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    for (const n of nodes) {
      if (g.members.has(n.id)) continue;
      if (n.x < box.x + box.w && n.x + n.w > box.x && n.y < box.y + box.h && n.y + n.h > box.y) {
        problems.push({ code: 'W_GROUP_OVERLAP', at: `groups.${g.id}`, msg: `"${n.id}" sits inside group "${g.id}"`, fix: `add "${n.id}" to the group or move it outside the group's rows/cols` });
      }
    }
    const label = (g.label || g.id).toUpperCase();
    const lw = ceil4(textWidth(label, { size: 7, mono: true, tracking: 0.16 }) + 12);
    groups.push({ ...g, box, label, labelBox: { x: box.x + 12, y: box.y - 6, w: lw, h: 12 } });
  }
  const obstacles = [...nodes.map((n) => ({ x: n.x, y: n.y, w: n.w, h: n.h })), ...groups.map((g) => g.labelBox)];
  const placed = [];
  for (const e of edges) {
    if (!e.label || !e.route) continue;
    const box = placeLabel(e.route, e.label, obstacles, placed, edges.filter((o) => o !== e && o.route).map((o) => o.route));
    if (box) {
      e.labelBox = box;
      placed.push(box);
    } else {
      problems.push({ code: 'W_LABEL', at: `edges.${e.id}`, msg: `label "${e.label}" has no clear spot`, fix: 'shorten the label or move the nodes one row/col apart' });
    }
  }
  const { back } = ranks(nodes, edges);
  const depth = new Map();
  if (spec.order && spec.order.length) {
    spec.order.forEach((id, i) => depth.set(id, i));
  }
  const fwd = edges.filter((e) => !back.has(`${e.from}>${e.to}`));
  const indeg = new Map(nodes.map((n) => [n.id, 0]));
  fwd.forEach((e) => indeg.set(e.to, indeg.get(e.to) + 1));
  const queue = nodes.filter((n) => indeg.get(n.id) === 0 && !depth.has(n.id)).map((n) => n.id);
  queue.forEach((id) => depth.set(id, depth.get(id) ?? 0));
  for (let qi = 0; qi < queue.length; qi++) {
    const id = queue[qi];
    for (const e of fwd.filter((f) => f.from === id)) {
      if (!depth.has(e.to)) {
        depth.set(e.to, depth.get(id) + 1);
        queue.push(e.to);
      }
    }
  }
  nodes.forEach((n) => !depth.has(n.id) && depth.set(n.id, 0));
  const keys = [...nodes.map((n) => depth.get(n.id) * 2), ...edges.map((e) => depth.get(e.from) * 2 + 1)];
  const steps = compressSteps(keys);
  nodes.forEach((n, i) => (n.step = steps[i]));
  edges.forEach((e, i) => (e.step = steps[nodes.length + i]));
  const maxStep = Math.max(1, ...steps);
  const chain = null;
  const lanes = (spec.lanes || []).map((l, i) => {
    const id = typeof l === 'string' ? l : l.id;
    const label = (typeof l === 'string' ? l : l.label || l.id).toUpperCase();
    const ms = nodes.filter((n) => (n.lane !== undefined ? n.lane === id : n.row === i));
    if (!ms.length) return null;
    const r0 = Math.min(...ms.map((n) => n.r)), r1 = Math.max(...ms.map((n) => n.r));
    const above = r0 > 0 ? (gapY[r0 - 1] || 52) / 2 : 28;
    const below = r1 < rowH.length - 1 ? (gapY[r1] || 52) / 2 : 28;
    return { id, label, y0: rowY[r0] - above, y1: rowY[r1] + rowH[r1] + below, i };
  }).filter(Boolean);
  const laneGutter = lanes.length ? Math.max(...lanes.map((l) => textWidth(l.label, { size: 8, mono: true, tracking: 0.16 }))) + 48 : 0;
  const pts = [];
  lanes.forEach((l) => pts.push([-laneGutter - 8, l.y0], [lastX + 24, l.y1]));
  nodes.forEach((n) => pts.push([n.x, n.y], [n.x + n.w, n.y + n.h]));
  groups.forEach((g) => pts.push([g.box.x, g.labelBox.y], [g.box.x + g.box.w, g.box.y + g.box.h]));
  edges.forEach((e) => (e.route || []).forEach((p) => pts.push([p.x, p.y])));
  placed.forEach((b) => pts.push([b.x, b.y], [b.x + b.w, b.y + b.h]));
  const minX = Math.min(...pts.map((p) => p[0])) - 24;
  const minY = Math.min(...pts.map((p) => p[1])) - 24;
  const maxX = Math.max(...pts.map((p) => p[0])) + 24;
  let maxY = Math.max(...pts.map((p) => p[1])) + 16;
  let legendSvg = '';
  const statuses = [...new Set(nodes.map((n) => n.status).filter(Boolean))];
  const changes = [...new Set(nodes.map((n) => n.change).filter(Boolean))];
  const forced = spec.legend === true || (spec.legend && typeof spec.legend === 'object');
  if (spec.legend !== false && (!NO_LEGEND.has(spec.type) || forced)) {
    const nk = [...new Set(nodes.map((n) => n.kind))];
    const ek = [...new Set(edges.map((e) => e.kind))];
    if (nk.length + ek.length > 2 || forced) {
      const extra = [
        ...statuses.map((st) => ({ type: 'swatch', swatch: `st-${st}`, key: st, label: STATUS_NAMES[st] || st })),
        ...changes.map((c) => ({ type: 'text', key: c, label: { added: '+ Neu', removed: '− Entfernt', changed: '~ Geändert' }[c] })),
      ];
      const custom = legendOptions(spec);
      const lg = legend({ nodeKinds: nk, edgeKinds: (ek.length > 1 || ek[0] !== 'default') ? ek.filter((k) => !['one-one', 'one-many', 'many-one', 'many-many', 'zero-many', 'one-zero', 'extends', 'implements', 'composes', 'aggregates', 'depends', 'assoc', 'line'].includes(k)) : [], extra, custom, x: minX + 24, y: maxY + 8, w: maxX - minX - 48 });
      legendSvg = lg.svg;
      maxY += lg.h + 8;
      const unknown = Object.keys(custom.entries).filter((k) => !lg.keys.includes(k));
      if (unknown.length) problems.push({ code: 'W_LEGEND_KEY', at: 'legend.entries', msg: `no ${unknown.map((k) => `"${k}"`).join(', ')} in this diagram's legend`, fix: `use one of: ${lg.keys.join(', ')}` });
    }
  }
  maxY += 24;
  const laneSvg = lanes.length ? el('g', { class: 'sc-lanes' }, lanes.map((l) => el('g', { class: 'sc-fade', 'data-sc-step': 1, style: '--step:0' }, [
    el('rect', { class: `lane-band${l.i % 2 ? ' alt' : ''}`, x: minX + 16, y: l.y0, width: maxX - minX - 32, height: l.y1 - l.y0 }),
    el('line', { class: 'lane-rule', x1: minX + 16, y1: l.y1, x2: maxX - 16, y2: l.y1 }),
    l.i === 0 ? el('line', { class: 'lane-rule', x1: minX + 16, y1: l.y0, x2: maxX - 16, y2: l.y0 }) : '',
    text({ class: 'lane-label', x: minX + 28, y: (l.y0 + l.y1) / 2 + 3 }, l.label),
  ]))) : '';
  const body = [
    laneSvg,
    el('g', { class: 'sc-groups' }, groups.map((g) => el('g', { class: 'sc-group sc-fade', 'data-sc-group': g.id, 'data-sc-step': 1, style: '--step:0' }, [
      el('rect', { class: `g-box${g.style === 'dashed' ? ' g-dashed' : ''}`, x: g.box.x, y: g.box.y, width: g.box.w, height: g.box.h, rx: 8 }),
      el('rect', { class: 'g-label-bg', x: g.labelBox.x, y: g.labelBox.y, width: g.labelBox.w, height: 12 }),
      text({ class: 'g-label', x: g.labelBox.x + 6, y: g.labelBox.y + 9 }, g.label),
    ]))),
    el('g', { class: 'sc-edges' }, edges.filter((e) => e.route).map((e) => drawEdge(e, { step: e.step, labelBoxAt: e.labelBox }))),
    chain ? el('circle', { class: 'e-token', r: 3.2, 'data-sc-step': maxStep, style: `--step:${maxStep};offset-path:path('${chain.d}');--tok-dur:${chain.dur}ms` }) : '',
    el('g', { class: 'sc-nodes' }, nodes.map((n) => drawNode(n, { step: n.step }))),
    legendSvg,
  ].join('');
  return {
    body,
    viewBox: [minX, minY, maxX - minX, maxY - minY],
    steps: maxStep,
    problems: [...problems, ...info],
    graph: { nodes: nodes.map((n) => ({ id: n.id, label: n.label, ...(n.group ? { group: (groups.find((g) => g.id === n.group) || {}).label } : {}) })), edges: edges.map((e) => ({ id: e.id, from: e.from, to: e.to })) },
  };
}
return { family, fromStages, render };
})();
M.sequence = (() => {
const { el, text, roundedPath } = M.svg;
const { textWidth, ceil4 } = M.text;
const { sizeNode, drawNode, normalizeKind } = M.nodes;
const family = 'lanes';
const LBL = { size: 9, mono: true };
const ROW = 40;
const SELF_ROW = 56;
const KIND = { sync: 'default', reply: 'return', async: 'link', self: 'default', primary: 'primary' };
function headPath(tip, dir) {
  return `M${tip.x},${tip.y} L${tip.x - dir * 8},${tip.y - 3.2} L${tip.x - dir * 8},${tip.y + 3.2} Z`;
}
function render(spec) {
  const problems = [];
  const parts = spec.participants.map((p) => ({ ...p, kind: normalizeKind(p) }));
  const index = new Map(parts.map((p, i) => [p.id, i]));
  if (index.size !== parts.length) problems.push({ code: 'E_DUP_ID', at: 'participants', msg: 'duplicate participant id', fix: 'ids must be unique' });
  const msgs = spec.messages.map((m, i) => {
    const o = Array.isArray(m) ? { from: m[0], to: m[1], label: m[2], kind: m[3] } : { ...m };
    for (const end of ['from', 'to']) {
      if (!index.has(o[end])) problems.push({ code: 'E_MSG_PARTICIPANT', at: `messages[${i}]`, msg: `unknown participant "${o[end]}"`, fix: `use one of: ${[...index.keys()].join(', ')}` });
    }
    o.kind = o.from === o.to ? 'self' : o.kind || 'sync';
    if (o.focal) o.kind = 'primary';
    o.i = i;
    return o;
  });
  if (problems.length) return { problems };
  if (msgs.length > 16) problems.push({ code: 'W_BUDGET', at: 'messages', msg: `${msgs.length} messages`, fix: 'keep sequences ≤ 16 messages; split by phase' });
  parts.forEach((p) => sizeNode(p, { minW: 104, maxW: 180 }));
  const xs = [];
  parts.forEach((p, i) => {
    xs.push(i === 0 ? p.w / 2 : xs[i - 1] + Math.max(132, (parts[i - 1].w + p.w) / 2 + 36));
  });
  for (let pass = 0; pass < 3; pass++) {
    for (const m of msgs) {
      const a = index.get(m.from), b = index.get(m.to);
      const lw = m.label ? textWidth(m.label, LBL) + 32 : 0;
      if (a === b) {
        if (a + 1 < xs.length) {
          const need = lw + 44 - (xs[a + 1] - xs[a]);
          if (need > 0) for (let k = a + 1; k < xs.length; k++) xs[k] += need;
        }
        continue;
      }
      const lo = Math.min(a, b), hi = Math.max(a, b);
      const need = lw - (xs[hi] - xs[lo]);
      if (need > 0) for (let k = hi; k < xs.length; k++) xs[k] += Math.ceil(need);
    }
  }
  const headH = Math.max(...parts.map((p) => p.h));
  parts.forEach((p, i) => { p.x = Math.round(xs[i] - p.w / 2); p.y = 0; p.cx = xs[i]; });
  const frags = (spec.fragments || []).filter((f) => f.from <= f.to && f.to < msgs.length);
  const notes = spec.notes || [];
  let y = headH + 36;
  const rowY = [];
  msgs.forEach((m, i) => {
    const opens = frags.filter((f) => f.from === i).length;
    const elseHere = frags.some((f) => f.else === i);
    y += opens * 26 + (elseHere ? 20 : 0);
    for (const n of notes.filter((n) => n.at === i)) { n.y = y - 6; y += 34; }
    rowY.push(y);
    y += m.kind === 'self' ? SELF_ROW : ROW;
    const closes = frags.filter((f) => f.to === i).length;
    y += closes * 10;
  });
  for (const n of notes.filter((n) => n.at >= msgs.length)) { n.y = y - 6; y += 34; }
  const bottom = y;
  const out = [];
  out.push(el('g', { class: 'sc-lifelines' }, parts.map((p) => el('line', { class: 'q-life', x1: p.cx, y1: headH, x2: p.cx, y2: bottom }))));
  const fragSvg = frags.map((f) => {
    const involved = msgs.slice(f.from, f.to + 1).flatMap((m) => [index.get(m.from), index.get(m.to)]);
    const lo = Math.min(...involved), hi = Math.max(...involved);
    const selfRight = msgs.slice(f.from, f.to + 1).some((m) => m.kind === 'self' && index.get(m.from) === hi) ? 52 : 0;
    const x0 = xs[lo] - 28, x1 = xs[hi] + 28 + selfRight;
    const y0 = rowY[f.from] - 30, y1 = rowY[f.to] + (msgs[f.to].kind === 'self' ? 30 : 14);
    const tag = f.kind.toUpperCase();
    const tw = ceil4(textWidth(tag, { size: 8, mono: true, tracking: 0.1 }) + 12);
    const g = [
      el('rect', { class: 'q-frag', x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 4 }),
      el('path', { class: 'q-frag-tag', d: `M${x0},${y0 + 4} Q${x0},${y0} ${x0 + 4},${y0} L${x0 + tw},${y0} L${x0 + tw},${y0 + 10} L${x0 + tw - 6},${y0 + 16} L${x0},${y0 + 16} Z` }),
      text({ class: 'q-frag-text', x: x0 + 6, y: y0 + 11 }, tag),
    ];
    if (f.label) g.push(text({ class: 'q-frag-text', x: x0 + tw + 8, y: y0 + 11, style: 'text-transform:none;letter-spacing:0' }, `[${f.label}]`));
    if (f.else !== undefined && f.else > f.from && f.else <= f.to) {
      const ey = rowY[f.else] - 26;
      g.push(el('line', { class: 'q-frag', x1: x0, y1: ey, x2: x1, y2: ey, 'stroke-dasharray': '4 3' }));
      g.push(text({ class: 'q-frag-text', x: x0 + 8, y: ey + 11, style: 'text-transform:none;letter-spacing:0' }, `[${f.elseLabel || 'else'}]`));
    }
    return el('g', { class: 'sc-frag sc-fade', 'data-sc-step': Math.min(12, f.from + 1), style: `--step:${Math.min(12, f.from + 1)}` }, g);
  });
  out.push(el('g', { class: 'sc-frags' }, fragSvg));
  const stepOf = (i) => Math.min(12, 1 + Math.floor((i * 12) / Math.max(12, msgs.length)));
  const msgSvg = msgs.map((m, i) => {
    const a = index.get(m.from), b = index.get(m.to);
    const y0 = rowY[i];
    const kind = KIND[m.kind] || 'default';
    const g = [];
    let lineD, head, lx, ly;
    if (a === b) {
      const x = xs[a];
      const pts = [{ x, y: y0 }, { x: x + 36, y: y0 }, { x: x + 36, y: y0 + 18 }, { x: x + 8, y: y0 + 18 }];
      lineD = roundedPath(pts, 5);
      head = headPath({ x: x + 1, y: y0 + 18 }, -1);
      lx = x + 44;
      ly = y0 + 12;
    } else {
      const dir = b > a ? 1 : -1;
      const x0 = xs[a], x1 = xs[b] - dir * 1;
      lineD = `M${x0},${y0} L${x1 - dir * 7},${y0}`;
      head = headPath({ x: x1, y: y0 }, dir);
      lx = (x0 + x1) / 2;
      ly = y0 - 7;
    }
    const dashed = m.kind === 'reply';
    g.push(el('path', { class: `e-line${dashed ? '' : ' sc-draw'}`, d: lineD, pathLength: dashed ? undefined : 1 }));
    g.push(el('path', { class: `e-head m-${dashed ? 'default' : kind}`, d: head }));
    if (m.label) {
      g.push(el('g', { class: 'e-label-g' }, text({ class: 'e-label q-label', x: lx, y: ly, 'text-anchor': a === b ? 'start' : 'middle', style: 'text-transform:none;letter-spacing:0;font-size:9px' }, m.label)));
    }
    if (spec.numbered) {
      g.push(text({ class: 'q-num', x: a === b ? xs[a] - 6 : xs[a] + (b > a ? 6 : -6), y: y0 - 7, 'text-anchor': a === b || b < a ? 'end' : 'start' }, `${i + 1}`));
    }
    return el('g', { class: `sc-edge ek-${kind}`, 'data-sc-edge': `m${i}`, 'data-from': m.from, 'data-to': m.to, 'data-sc-step': stepOf(i), style: `--step:${stepOf(i)}` }, g);
  });
  out.push(el('g', { class: 'sc-edges' }, msgSvg));
  out.push(el('g', { class: 'sc-notes' }, notes.filter((n) => n.y !== undefined).map((n) => {
    const idx = n.over.map((id) => index.get(id)).filter((v) => v !== undefined);
    if (!idx.length) return '';
    const tw = textWidth(n.text, { size: 10 }) + 20;
    const cx = (xs[Math.min(...idx)] + xs[Math.max(...idx)]) / 2;
    const w = Math.max(tw, idx.length > 1 ? Math.abs(xs[idx[1]] - xs[idx[0]]) + 48 : 0);
    return el('g', { class: 'sc-enter', 'data-sc-step': stepOf(Math.min(n.at, msgs.length - 1)), style: `--step:${stepOf(Math.min(n.at, msgs.length - 1))}` }, [
      el('rect', { class: 'q-note', x: cx - w / 2, y: n.y - 16, width: w, height: 24, rx: 3 }),
      text({ class: 'q-note-text', x: cx, y: n.y, 'text-anchor': 'middle' }, n.text),
    ]);
  })));
  out.push(el('g', { class: 'sc-nodes' }, parts.map((p) => drawNode(p, { step: 0 }))));
  const maxX = Math.max(...parts.map((p) => p.x + p.w), ...xs.map((x) => x + 90));
  const minX = Math.min(...parts.map((p) => p.x)) - 24;
  return {
    body: out.join(''),
    viewBox: [minX - 8, -24, maxX - minX + 32, bottom + 40],
    steps: Math.max(...msgs.map((_, i) => stepOf(i))),
    problems,
    graph: { nodes: parts.map((p) => ({ id: p.id, label: p.label })), edges: msgs.map((m, i) => ({ id: `m${i}`, from: m.from, to: m.to })) },
  };
}
return { family, render };
})();
M.tree = (() => {
const { el, roundedPath } = M.svg;
const { sizeNode, drawNode, normalizeKind } = M.nodes;
const { compressSteps } = M.motion;
const family = 'structure';
const SIB_GAP = 20;
const LEVEL_GAP = 56;
function render(spec) {
  const problems = [];
  const dir = spec.dir || (spec.variant === 'block' ? 'LR' : 'TB');
  const all = [];
  const ids = new Set();
  let auto = 0;
  function build(n, depth, parent) {
    const id = n.id || `n${auto++}`;
    if (ids.has(id)) problems.push({ code: 'E_DUP_ID', at: id, msg: `duplicate id "${id}"`, fix: 'ids must be unique' });
    ids.add(id);
    const node = { ...n, id, depth, parent, kind: normalizeKind(n), children: [] };
    all.push(node);
    node.children = (n.children || []).map((c) => build(c, depth + 1, node));
    return node;
  }
  const root = build(spec.root, 0, null);
  if (spec.variant === 'block') {
    const num = (n, prefix) => n.children.forEach((c, i) => { c.tag = c.tag || `${prefix}${i + 1}`; num(c, `${prefix}${i + 1}.`); });
    root.tag = root.tag || '0';
    num(root, '');
  }
  if (problems.length) return { problems };
  if (all.length > 24) problems.push({ code: 'W_BUDGET', at: 'root', msg: `${all.length} nodes`, fix: 'collapse deep branches into a "+N more" leaf or split the tree' });
  const maxKids = Math.max(...all.map((n) => n.children.length));
  if (maxKids > 6) problems.push({ code: 'W_FANOUT', at: 'root', msg: `a node has ${maxKids} children`, fix: 'group siblings under an intermediate node (≤ 6 per parent)' });
  all.forEach((n) => sizeNode(n, { minW: 104, maxW: 180 }));
  const horiz = dir === 'LR';
  const along = (n) => (horiz ? n.h : n.w); // extent along the sibling axis
  const levels = [];
  for (const n of all) levels[n.depth] = Math.max(levels[n.depth] || 0, horiz ? n.w : n.h);
  function measure(n) {
    if (!n.children.length) return (n.span = along(n));
    const kids = n.children.reduce((s, c) => s + measure(c), 0) + SIB_GAP * (n.children.length - 1);
    return (n.span = Math.max(along(n), kids));
  }
  measure(root);
  const levelPos = [];
  let acc = 0;
  levels.forEach((size, d) => { levelPos[d] = acc; acc += size + (horiz ? LEVEL_GAP + 24 : LEVEL_GAP); });
  function place(n, start) {
    const center = start + n.span / 2;
    if (horiz) {
      n.x = levelPos[n.depth];
      n.y = Math.round(center - n.h / 2);
    } else {
      n.x = Math.round(center - n.w / 2);
      n.y = levelPos[n.depth];
    }
    const kids = n.children.reduce((s, c) => s + c.span, 0) + SIB_GAP * (n.children.length - 1);
    let cur = center - kids / 2;
    for (const c of n.children) {
      place(c, cur);
      cur += c.span + SIB_GAP;
    }
  }
  place(root, 0);
  const steps = compressSteps(all.flatMap((n) => [n.depth * 2]).concat(all.filter((n) => n.parent).map((n) => n.depth * 2 - 1)));
  all.forEach((n, i) => (n.step = steps[i]));
  const edgeNodes = all.filter((n) => n.parent);
  edgeNodes.forEach((n, i) => (n.edgeStep = steps[all.length + i]));
  const edges = edgeNodes.map((n) => {
    const p = n.parent;
    let pts;
    if (horiz) {
      const x0 = p.x + p.w, y0 = p.y + p.h / 2, x1 = n.x, y1 = n.y + n.h / 2;
      const mx = x0 + Math.round((levelPos[n.depth] - x0) / 2);
      pts = y0 === y1 ? [{ x: x0, y: y0 }, { x: x1, y: y1 }] : [{ x: x0, y: y0 }, { x: mx, y: y0 }, { x: mx, y: y1 }, { x: x1, y: y1 }];
    } else {
      const x0 = p.x + p.w / 2, y0 = p.y + p.h, x1 = n.x + n.w / 2, y1 = n.y;
      const my = y0 + Math.round((levelPos[n.depth] - y0) / 2);
      pts = x0 === x1 ? [{ x: x0, y: y0 }, { x: x1, y: y1 }] : [{ x: x0, y: y0 }, { x: x0, y: my }, { x: x1, y: my }, { x: x1, y: y1 }];
    }
    return el('g', { class: `sc-edge ek-${n.kind === 'focal' ? 'primary' : 'muted'}`, 'data-sc-edge': `${p.id}-${n.id}`, 'data-from': p.id, 'data-to': n.id, 'data-sc-step': n.edgeStep, style: `--step:${n.edgeStep}` },
      el('path', { class: 'e-line sc-draw', d: roundedPath(pts, 6), pathLength: 1 }));
  });
  const minX = Math.min(...all.map((n) => n.x)) - 32;
  const minY = Math.min(...all.map((n) => n.y)) - 32;
  const maxX = Math.max(...all.map((n) => n.x + n.w)) + 32;
  const maxY = Math.max(...all.map((n) => n.y + n.h)) + 32;
  return {
    body: el('g', { class: 'sc-edges' }, edges) + el('g', { class: 'sc-nodes' }, all.map((n) => drawNode(n, { step: n.step }))),
    viewBox: [minX, minY, maxX - minX, maxY - minY],
    steps: Math.max(...steps),
    problems,
    graph: { nodes: all.map((n) => ({ id: n.id, label: n.label })), edges: edgeNodes.map((n) => ({ id: `${n.parent.id}-${n.id}`, from: n.parent.id, to: n.id })) },
  };
}
return { family, render };
})();
M.schema = (() => {
function typeOf(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  if (Number.isInteger(v)) return 'integer';
  return typeof v;
}
function typeMatches(v, t) {
  const actual = typeOf(v);
  if (t === 'number') return actual === 'number' || actual === 'integer';
  return actual === t;
}
function resolve(root, ref) {
  if (!ref.startsWith('#/')) throw new Error(`unsupported $ref ${ref}`);
  return ref.slice(2).split('/').reduce((o, k) => o?.[k], root);
}
function validate(schema, value, root = schema, path = '', out = []) {
  if (schema.$ref) return validate(resolve(root, schema.$ref), value, root, path, out);
  const at = path || '(root)';
  if (schema.type) {
    const types = [].concat(schema.type);
    if (!types.some((t) => typeMatches(value, t))) {
      out.push({ at, msg: `expected ${types.join('|')}, got ${typeOf(value)}` });
      return out;
    }
  }
  if (schema.const !== undefined && value !== schema.const) out.push({ at, msg: `must be ${JSON.stringify(schema.const)}` });
  if (schema.enum && !schema.enum.includes(value)) out.push({ at, msg: `must be one of ${schema.enum.join(', ')}` });
  if (typeof value === 'string') {
    if (schema.minLength !== undefined && value.length < schema.minLength) out.push({ at, msg: `too short (min ${schema.minLength})` });
    if (schema.maxLength !== undefined && value.length > schema.maxLength) out.push({ at, msg: `too long (max ${schema.maxLength} chars)` });
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) out.push({ at, msg: `must match ${schema.pattern}` });
  }
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) out.push({ at, msg: `must be >= ${schema.minimum}` });
    if (schema.maximum !== undefined && value > schema.maximum) out.push({ at, msg: `must be <= ${schema.maximum}` });
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) out.push({ at, msg: `needs at least ${schema.minItems} items` });
    if (schema.maxItems !== undefined && value.length > schema.maxItems) out.push({ at, msg: `allows at most ${schema.maxItems} items` });
    if (Array.isArray(schema.items)) {
      schema.items.forEach((s, i) => {
        if (i < value.length) validate(s, value[i], root, `${path}[${i}]`, out);
      });
    } else if (schema.items) {
      value.forEach((v, i) => validate(schema.items, v, root, `${path}[${i}]`, out));
    }
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const k of schema.required || []) {
      if (value[k] === undefined) out.push({ at: path ? `${path}.${k}` : k, msg: 'is required' });
    }
    const props = schema.properties || {};
    for (const [k, v] of Object.entries(value)) {
      const p = path ? `${path}.${k}` : k;
      if (props[k]) validate(props[k], v, root, p, out);
      else if (schema.additionalProperties === false) out.push({ at: p, msg: 'unknown field' });
      else if (typeof schema.additionalProperties === 'object') validate(schema.additionalProperties, v, root, p, out);
    }
  }
  for (const key of ['anyOf', 'oneOf']) {
    if (!schema[key]) continue;
    const results = schema[key].map((s) => validate(s, value, root, path, []));
    const ok = results.filter((r) => r.length === 0).length;
    if (key === 'anyOf' ? ok === 0 : ok !== 1) {
      const typed = results.filter((r) => !r.some((e) => e.at === at && e.msg.startsWith('expected ')));
      const best = (typed.length ? typed : results).reduce((a, b) => (b.length < a.length ? b : a));
      out.push(...(best.length ? best : [{ at, msg: `must match exactly one allowed shape` }]));
    }
  }
  return out;
}
return { validate };
})();
const SCHEMAS = {"graph":{"required":["nodes"],"additionalProperties":false,"properties":{"$schema":{"type":"string"},"type":{"type":"string"},"variant":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":90},"subtitle":{"type":"string","maxLength":160},"eyebrow":{"type":"string","maxLength":40},"caption":{"type":"string","maxLength":280},"motion":{"enum":["auto","none","reveal","trace","step","loop"]},"order":{"type":"array","items":{"type":"string"}},"skin":{"enum":["light","dark","terminal"]},"size":{"enum":["auto","wide","slide","square"]},"budget":{"enum":["strict","balanced","faithful","off"]},"legend":{"anyOf":[{"type":"boolean"},{"type":"object","additionalProperties":false,"properties":{"title":{"type":"string","maxLength":24},"entries":{"type":"object","additionalProperties":{"type":"object","additionalProperties":false,"properties":{"label":{"type":"string","minLength":1,"maxLength":32},"visible":{"type":"boolean"}}}}}}]},"notes":{"type":"string"},"out":{"type":"string"},"evidence":{"type":"array","items":{"type":"object","required":["id","file"],"properties":{"id":{"type":"string"},"file":{"type":"string"},"line":{"type":"integer","minimum":1},"note":{"type":"string"}},"additionalProperties":false}},"style":{"enum":["clean","sketchy"]},"watermark":{"type":"boolean"},"lang":{"type":"string","pattern":"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$","maxLength":35},"dir":{"enum":["LR","TB"]},"nodes":{"type":"array","minItems":1,"items":{"$ref":"#/$defs/node"}},"edges":{"type":"array","items":{"$ref":"#/$defs/edge"}},"groups":{"type":"array","items":{"type":"object","required":["id"],"additionalProperties":false,"properties":{"id":{"type":"string"},"label":{"type":"string","maxLength":32},"style":{"enum":["solid","dashed"]},"nodes":{"type":"array","items":{"type":"string"}}}}},"lanes":{"type":"array","maxItems":8,"items":{"anyOf":[{"type":"string"},{"type":"object","required":["id"],"additionalProperties":false,"properties":{"id":{"type":"string"},"label":{"type":"string","maxLength":28}}}]}}},"$defs":{"node":{"type":"object","required":["id"],"additionalProperties":false,"properties":{"icon":{"enum":["calendar","clock","person","people","briefcase","home","money","card","cart","document","flag","check","mail","phone","chat","plane","car","heart","star","moon","sun","gift","pin","key","server","database","cloud","lock","code","gear"]},"id":{"type":"string","pattern":"^[A-Za-z_][A-Za-z0-9_.-]*$"},"label":{"type":"string","maxLength":40},"sub":{"type":"string","maxLength":48},"tag":{"type":"string","maxLength":14},"kind":{"enum":["backend","focal","store","external","input","optional","security","muted"]},"focal":{"type":"boolean"},"shape":{"enum":["box","decision","terminal","io","store","state","start","end","entity","class"]},"row":{"type":"integer","minimum":0,"maximum":40},"col":{"type":"integer","minimum":0,"maximum":40},"group":{"type":"string"},"change":{"enum":["added","removed","changed"]},"fields":{"type":"array","maxItems":16,"items":{"anyOf":[{"type":"string","maxLength":48},{"type":"array","minItems":1,"maxItems":3,"items":{"type":"string"}}]}},"attrs":{"type":"array","maxItems":10,"items":{"type":"string","maxLength":48}},"methods":{"type":"array","maxItems":10,"items":{"type":"string","maxLength":48}},"status":{"enum":["ok","risk","legacy","retire"]},"lane":{"type":"string"}}},"edgeKind":{"enum":["default","primary","link","async","return","muted","one-one","one-many","many-one","many-many","zero-many","one-zero","extends","implements","composes","aggregates","depends","assoc","line"]},"edge":{"anyOf":[{"type":"array","minItems":2,"maxItems":4,"items":[{"type":"string"},{"type":"string"},{"type":"string"},{"$ref":"#/$defs/edgeKind"}]},{"type":"object","required":["from","to"],"additionalProperties":false,"properties":{"id":{"type":"string"},"from":{"type":"string"},"to":{"type":"string"},"label":{"type":"string","maxLength":28},"kind":{"$ref":"#/$defs/edgeKind"},"both":{"type":"boolean"},"change":{"enum":["added","removed","changed"]}}}]}}},"stages":{"required":["stages"],"additionalProperties":false,"properties":{"$schema":{"type":"string"},"type":{"type":"string"},"variant":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":90},"subtitle":{"type":"string","maxLength":160},"eyebrow":{"type":"string","maxLength":40},"caption":{"type":"string","maxLength":280},"motion":{"enum":["auto","none","reveal","trace","step","loop"]},"order":{"type":"array","items":{"type":"string"}},"skin":{"enum":["light","dark","terminal"]},"size":{"enum":["auto","wide","slide","square"]},"budget":{"enum":["strict","balanced","faithful","off"]},"legend":{"anyOf":[{"type":"boolean"},{"type":"object","additionalProperties":false,"properties":{"title":{"type":"string","maxLength":24},"entries":{"type":"object","additionalProperties":{"type":"object","additionalProperties":false,"properties":{"label":{"type":"string","minLength":1,"maxLength":32},"visible":{"type":"boolean"}}}}}}]},"notes":{"type":"string"},"out":{"type":"string"},"evidence":{"type":"array","items":{"type":"object","required":["id","file"],"properties":{"id":{"type":"string"},"file":{"type":"string"},"line":{"type":"integer","minimum":1},"note":{"type":"string"}},"additionalProperties":false}},"style":{"enum":["clean","sketchy"]},"watermark":{"type":"boolean"},"lang":{"type":"string","pattern":"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$","maxLength":35},"dir":{"enum":["LR","TB"]},"stages":{"type":"array","minItems":2,"maxItems":6,"items":{"type":"object","required":["label","items"],"additionalProperties":false,"properties":{"label":{"type":"string","maxLength":28},"style":{"enum":["solid","dashed"]},"plain":{"type":"boolean"},"kind":{"enum":["backend","focal","store","external","input","optional","security","muted"]},"items":{"type":"array","minItems":1,"maxItems":6,"items":{"anyOf":[{"type":"string","maxLength":40},{"type":"object","required":["label"],"additionalProperties":false,"properties":{"id":{"type":"string"},"label":{"type":"string","maxLength":40},"sub":{"type":"string","maxLength":48},"tag":{"type":"string","maxLength":8},"kind":{"type":"string"},"focal":{"type":"boolean"},"row":{"type":"integer"}}}]}}}}},"edges":{"type":"array","items":{"$ref":"#/$defs/edge"}}},"$defs":{"node":{"type":"object","required":["id"],"additionalProperties":false,"properties":{"id":{"type":"string","pattern":"^[A-Za-z_][A-Za-z0-9_.-]*$"},"label":{"type":"string","maxLength":40},"sub":{"type":"string","maxLength":48},"tag":{"type":"string","maxLength":8},"kind":{"enum":["backend","focal","store","external","input","optional","security","muted"]},"focal":{"type":"boolean"},"shape":{"enum":["box","decision","terminal","io","store","state","start","end","entity","class"]},"row":{"type":"integer","minimum":0,"maximum":40},"col":{"type":"integer","minimum":0,"maximum":40},"group":{"type":"string"},"change":{"enum":["added","removed","changed"]},"fields":{"type":"array","maxItems":16,"items":{"anyOf":[{"type":"string","maxLength":48},{"type":"array","minItems":1,"maxItems":3,"items":{"type":"string"}}]}},"attrs":{"type":"array","maxItems":10,"items":{"type":"string","maxLength":48}},"methods":{"type":"array","maxItems":10,"items":{"type":"string","maxLength":48}},"status":{"enum":["ok","risk","legacy","retire"]},"lane":{"type":"string"}}},"edgeKind":{"enum":["default","primary","link","async","return","muted","one-one","one-many","many-one","many-many","zero-many","one-zero","extends","implements","composes","aggregates","depends","assoc","line"]},"edge":{"anyOf":[{"type":"array","minItems":2,"maxItems":4,"items":[{"type":"string"},{"type":"string"},{"type":"string"},{"$ref":"#/$defs/edgeKind"}]},{"type":"object","required":["from","to"],"additionalProperties":false,"properties":{"id":{"type":"string"},"from":{"type":"string"},"to":{"type":"string"},"label":{"type":"string","maxLength":28},"kind":{"$ref":"#/$defs/edgeKind"},"both":{"type":"boolean"},"change":{"enum":["added","removed","changed"]}}}]}}},"sequence":{"required":["participants","messages"],"additionalProperties":false,"properties":{"$schema":{"type":"string"},"type":{"type":"string"},"variant":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":90},"subtitle":{"type":"string","maxLength":160},"eyebrow":{"type":"string","maxLength":40},"caption":{"type":"string","maxLength":280},"motion":{"enum":["auto","none","reveal","trace","step","loop"]},"order":{"type":"array","items":{"type":"string"}},"skin":{"enum":["light","dark","terminal"]},"size":{"enum":["auto","wide","slide","square"]},"budget":{"enum":["strict","balanced","faithful","off"]},"legend":{"anyOf":[{"type":"boolean"},{"type":"object","additionalProperties":false,"properties":{"title":{"type":"string","maxLength":24},"entries":{"type":"object","additionalProperties":{"type":"object","additionalProperties":false,"properties":{"label":{"type":"string","minLength":1,"maxLength":32},"visible":{"type":"boolean"}}}}}}]},"notes":{"type":"array","items":{"type":"object","required":["at","over","text"],"additionalProperties":false,"properties":{"at":{"type":"integer","minimum":0},"over":{"type":"array","minItems":1,"maxItems":2,"items":{"type":"string"}},"text":{"type":"string","maxLength":80}}}},"out":{"type":"string"},"evidence":{"type":"array","items":{"type":"object","required":["id","file"],"properties":{"id":{"type":"string"},"file":{"type":"string"},"line":{"type":"integer","minimum":1},"note":{"type":"string"}},"additionalProperties":false}},"style":{"enum":["clean","sketchy"]},"watermark":{"type":"boolean"},"lang":{"type":"string","pattern":"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$","maxLength":35},"participants":{"type":"array","minItems":2,"items":{"type":"object","required":["id","label"],"additionalProperties":false,"properties":{"icon":{"enum":["calendar","clock","person","people","briefcase","home","money","card","cart","document","flag","check","mail","phone","chat","plane","car","heart","star","moon","sun","gift","pin","key","server","database","cloud","lock","code","gear"]},"id":{"type":"string","pattern":"^[A-Za-z_][A-Za-z0-9_.-]*$"},"label":{"type":"string","maxLength":32},"sub":{"type":"string","maxLength":40},"kind":{"enum":["backend","focal","store","external","input","security","muted"]},"focal":{"type":"boolean"}}}},"messages":{"type":"array","minItems":1,"items":{"anyOf":[{"type":"array","minItems":2,"maxItems":4,"items":[{"type":"string"},{"type":"string"},{"type":"string"},{"$ref":"#/$defs/msgKind"}]},{"type":"object","required":["from","to"],"additionalProperties":false,"properties":{"from":{"type":"string"},"to":{"type":"string"},"label":{"type":"string","maxLength":44},"kind":{"$ref":"#/$defs/msgKind"},"focal":{"type":"boolean"}}}]}},"fragments":{"type":"array","items":{"type":"object","required":["kind","from","to"],"additionalProperties":false,"properties":{"kind":{"enum":["alt","opt","loop","par","critical","break"]},"label":{"type":"string","maxLength":40},"from":{"type":"integer","minimum":0},"to":{"type":"integer","minimum":0},"else":{"type":"integer","minimum":0},"elseLabel":{"type":"string","maxLength":40}}}},"numbered":{"type":"boolean"}},"$defs":{"msgKind":{"enum":["sync","reply","async","self","primary"]}}},"tree":{"required":["root"],"additionalProperties":false,"properties":{"$schema":{"type":"string"},"type":{"type":"string"},"variant":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":90},"subtitle":{"type":"string","maxLength":160},"eyebrow":{"type":"string","maxLength":40},"caption":{"type":"string","maxLength":280},"motion":{"enum":["auto","none","reveal","trace","step","loop"]},"order":{"type":"array","items":{"type":"string"}},"skin":{"enum":["light","dark","terminal"]},"size":{"enum":["auto","wide","slide","square"]},"budget":{"enum":["strict","balanced","faithful","off"]},"legend":{"anyOf":[{"type":"boolean"},{"type":"object","additionalProperties":false,"properties":{"title":{"type":"string","maxLength":24},"entries":{"type":"object","additionalProperties":{"type":"object","additionalProperties":false,"properties":{"label":{"type":"string","minLength":1,"maxLength":32},"visible":{"type":"boolean"}}}}}}]},"notes":{"type":"string"},"out":{"type":"string"},"evidence":{"type":"array","items":{"type":"object","required":["id","file"],"properties":{"id":{"type":"string"},"file":{"type":"string"},"line":{"type":"integer","minimum":1},"note":{"type":"string"}},"additionalProperties":false}},"style":{"enum":["clean","sketchy"]},"watermark":{"type":"boolean"},"lang":{"type":"string","pattern":"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$","maxLength":35},"dir":{"enum":["TB","LR"]},"root":{"$ref":"#/$defs/tnode"}},"$defs":{"tnode":{"type":"object","required":["label"],"additionalProperties":false,"properties":{"icon":{"enum":["calendar","clock","person","people","briefcase","home","money","card","cart","document","flag","check","mail","phone","chat","plane","car","heart","star","moon","sun","gift","pin","key","server","database","cloud","lock","code","gear"]},"id":{"type":"string","pattern":"^[A-Za-z_][A-Za-z0-9_.-]*$"},"label":{"type":"string","maxLength":36},"sub":{"type":"string","maxLength":40},"tag":{"type":"string","maxLength":8},"kind":{"enum":["backend","focal","store","external","input","optional","security","muted"]},"focal":{"type":"boolean"},"children":{"type":"array","items":{"$ref":"#/$defs/tnode"}}}}}}};
/* ── SeeCode-Ende ── */
/* ── FYOS-Kleber (eigener Code, nicht aus SeeCode) ───────────────────────────────────────────────────────── */
// Diagrammarten, die diese Vorlage zeichnet: Art der Schemas und Renderer je Spezifikations-Typ.
const ART = {
  architecture: "graph", flowchart: "graph", "data-flow": "graph", dependency: "graph", deployment: "graph",
  "high-level": "graph", state: "graph", er: "graph", "db-schema": "graph", "uml-class": "graph", swimlane: "graph",
  "architecture-delta": "graph", "it-state": "graph", medallion: "stages", "dp-integration": "stages",
  sequence: "sequence", tree: "tree", "org-chart": "tree",
};
// Kurznamen von SeeCode für Abwandlungen: Name → [Grundtyp, variant].
const ALIASE = {
  "high-level-vertical": ["high-level", "vertical"], "sequence-oauth": ["sequence", "oauth"],
  "state-lifecycle": ["state", "lifecycle"], "tree-block-decomposition": ["tree", "block"],
};
const RENDERER = { graph: M.graph, stages: M.graph, sequence: M.sequence, tree: M.tree };
const ZEICHEN_SYSTEMSCHRIFT = 1.08; // SeeCode misst IBM Plex; die Systemschrift fällt etwas breiter aus
const STEUER = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f￾￿]/g;

// Obergrenzen, damit eine Spezifikation das Zeichnen nicht lahmlegt (die Wegsuche wächst mit Knoten × Kanten).
const GRENZE = { nodes: 48, edges: 96, participants: 12, messages: 40, baum: 80 };

function bereinigen(wert, tiefe = 0) {
  if (tiefe > 14) throw new Error("Die Spezifikation ist zu tief verschachtelt");
  if (typeof wert === "string") {
    const s = wert.replace(STEUER, "");
    return typeof s.toWellFormed === "function" ? s.toWellFormed() : s;
  }
  if (Array.isArray(wert)) return wert.map((x) => bereinigen(x, tiefe + 1));
  if (wert && typeof wert === "object") {
    const aus = {};
    for (const k of Object.keys(wert)) if (k !== "__proto__") aus[k] = bereinigen(wert[k], tiefe + 1);
    return aus;
  }
  return wert;
}

function baumGroesse(n, tiefe = 0) {
  if (!n || typeof n !== "object" || tiefe > 14) return 0;
  return 1 + (Array.isArray(n.children) ? n.children.reduce((s, k) => s + baumGroesse(k, tiefe + 1), 0) : 0);
}

function groessenFehler(spec, art) {
  const pruefen = (name, anzahl, max) => (anzahl > max ? [{ code: "E_GROESSE", at: name, msg: `${anzahl} Einträge, erlaubt sind höchstens ${max}`, fix: "das Diagramm aufteilen: Überblick plus Detail" }] : []);
  if (art === "graph") return [...pruefen("nodes", (spec.nodes || []).length, GRENZE.nodes), ...pruefen("edges", (spec.edges || []).length, GRENZE.edges)];
  if (art === "stages") return pruefen("edges", (spec.edges || []).length, GRENZE.edges);
  if (art === "sequence") return [...pruefen("participants", (spec.participants || []).length, GRENZE.participants), ...pruefen("messages", (spec.messages || []).length, GRENZE.messages)];
  return pruefen("root", baumGroesse(spec.root), GRENZE.baum);
}

// ── Strenge Prüfung des erzeugten SVG-Textes ────────────────────────────────────────────────────────────
// Alle Texte und Attributwerte hat SeeCode mit esc() maskiert (& < > "). Hier wird zusätzlich geprüft, dass der Text nur
// aus bekannten Elementen und Attributen besteht, ohne Verweise (href, url(), Ereignisse) und ohne fremde Entitäten.
const TAGS = new Set(["svg", "g", "path", "rect", "circle", "ellipse", "line", "polygon", "polyline", "text", "tspan", "title", "desc"]);
const ATTRIBUTE = new Set(["class", "id", "d", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "width", "height", "viewBox",
  "transform", "points", "fill", "stroke-dasharray", "stroke-width", "text-anchor", "style", "tabindex", "role", "pathLength", "xml:space"]);
const ATTR_PRAEFIX = ["data-", "aria-"];
const STYLE_OK = /^(?:[a-z-]+:[-a-z0-9.% ]+;?)+$/;

function pruefenSvg(s) {
  const fehler = [];
  const stapel = [];
  const melden = (t) => { if (fehler.length < 8) fehler.push(t); };
  if (!s.startsWith("<svg ") || !s.endsWith("</svg>")) melden("Wurzel ist kein svg");
  for (const m of s.matchAll(/<[^<>]*>|[^<>]+|[<>]/g)) {
    const t = m[0];
    if (t === "<" || t === ">") { melden("loses Zeichen < oder >"); continue; }
    if (t[0] !== "<") {
      if (/&(?!(?:amp|lt|gt|quot);)/.test(t)) melden("unbekannte Entität im Text");
      continue;
    }
    const k = /^<(\/?)([A-Za-z][A-Za-z0-9]*)((?:\s+[A-Za-z][A-Za-z0-9:-]*="[^"<>]*")*)\s*(\/?)>$/.exec(t);
    if (!k) { melden(`ungültiges Element: ${t.slice(0, 40)}`); continue; }
    const [, zu, name, attr, selbst] = k;
    if (!TAGS.has(name)) { melden(`Element nicht erlaubt: ${name}`); continue; }
    if (zu) {
      if (attr.trim() || selbst || stapel.pop() !== name) melden(`Schließen passt nicht: ${name}`);
      continue;
    }
    for (const a of attr.matchAll(/\s+([A-Za-z][A-Za-z0-9:-]*)="([^"<>]*)"/g)) {
      const [, an, wert] = a;
      if (!ATTRIBUTE.has(an) && !ATTR_PRAEFIX.some((p) => an.startsWith(p))) melden(`Attribut nicht erlaubt: ${an}`);
      // aria-* und data-* tragen nur Text (Beschriftungen, Kennungen), keine Adressen; dort zählt nur die Entitätenprüfung
      const nurText = ATTR_PRAEFIX.some((p) => an.startsWith(p));
      if (/&(?!(?:amp|lt|gt|quot);)/.test(wert) || (!nurText && /url\(|javascript:|data:|expression/i.test(wert))) melden(`Wert nicht erlaubt in ${an}`);
      if (an === "style" && !STYLE_OK.test(wert)) melden("style nicht erlaubt");
    }
    if (!selbst) stapel.push(name);
  }
  if (stapel.length) melden("Elemente nicht geschlossen");
  return fehler;
}

// ── Rechnen: Spezifikation → SVG-Text ───────────────────────────────────────────────────────────────────
function fehlerErgebnis(probleme) {
  return { ok: false, probleme };
}

function rendern(roh) {
  let d;
  try { d = bereinigen(roh); } catch (e) { return fehlerErgebnis([{ code: "E_SPEC", at: "(root)", msg: e.message }]); }
  if (!d || typeof d !== "object" || Array.isArray(d)) return fehlerErgebnis([{ code: "E_SPEC", at: "(root)", msg: "Die Spezifikation muss ein Objekt sein" }]);
  // Felder der Vorlage gehören nicht zur SeeCode-Spezifikation
  const { ueberschrift, text, herkunft, ...eingabe } = d;
  const alias = ALIASE[eingabe.type];
  const spec = alias ? { ...eingabe, type: alias[0], variant: eingabe.variant || alias[1] } : eingabe;
  const art = ART[spec.type];
  if (!art) {
    return fehlerErgebnis([{ code: "E_TYPE", at: "type", msg: `Unbekannter Typ „${String(spec.type)}“`, fix: `erlaubt: ${[...Object.keys(ART), ...Object.keys(ALIASE)].join(", ")}` }]);
  }
  const schema = M.schema.validate(SCHEMAS[art], spec).map((p) => ({ code: "E_SPEC", at: p.at, msg: p.msg }));
  if (schema.length) return fehlerErgebnis(schema.slice(0, 12));
  const gross = groessenFehler(spec, art);
  if (gross.length) return fehlerErgebnis(gross);
  const vorher = M.text.setWidthScale(ZEICHEN_SYSTEMSCHRIFT);
  let r;
  try {
    r = RENDERER[art].render(spec, {});
  } catch (e) {
    return fehlerErgebnis([{ code: "E_RENDER", at: "(root)", msg: e.message }]);
  } finally {
    M.text.setWidthScale(vorher);
  }
  if (!r.body) return fehlerErgebnis((r.problems || []).filter((p) => p.code.startsWith("E_")).slice(0, 12));
  const vb = r.viewBox.map(Math.round);
  if (vb.length !== 4 || !vb.every(Number.isFinite) || vb[2] <= 0 || vb[3] <= 0) return fehlerErgebnis([{ code: "E_RENDER", at: "viewBox", msg: "Maße nicht berechenbar" }]);
  const titel = ueberschrift || spec.title || "Diagramm";
  const knoten = r.graph.nodes.length;
  const beschreibung = spec.subtitle || `Diagramm (${spec.type}) mit ${knoten} Elementen und ${r.graph.edges.length} Verbindungen.`;
  const esc = M.svg.esc;
  const svg = `<svg class="dg-svg" viewBox="${vb.join(" ")}" role="img" aria-labelledby="dg-t dg-b" data-dg-art="${esc(art)}">`
    + `<title id="dg-t">${esc(titel)}</title><desc id="dg-b">${esc(beschreibung)}</desc>${r.body}</svg>`;
  const verstoesse = pruefenSvg(svg);
  if (verstoesse.length) return fehlerErgebnis([{ code: "E_SVG", at: "(svg)", msg: `Die Zeichnung wurde nicht eingesetzt: ${verstoesse.join("; ")}` }]);
  const hinweise = (r.problems || []).filter((p) => p.code.startsWith("W_"));
  return { ok: true, art, spec, svg, breite: vb[2], titel, beschreibung, hinweise, graph: r.graph, liste: listeVon(spec, art, r.graph) };
}

// Text-Alternative: Elemente und Verbindungen als Zeilen (nur Text, ohne Markup).
function listeVon(spec, art, graph) {
  const name = new Map(graph.nodes.map((n) => [n.id, n.label]));
  const wie = (id) => name.get(id) || id;
  const elemente = graph.nodes.map((n) => (n.group ? `${n.label} (${n.group})` : n.label));
  const verbindungen = [];
  if (art === "sequence") {
    spec.messages.forEach((m, i) => {
      const o = Array.isArray(m) ? { from: m[0], to: m[1], label: m[2] } : m;
      verbindungen.push(`${i + 1}. ${wie(o.from)} → ${wie(o.to)}${o.label ? `: ${o.label}` : ""}`);
    });
  } else {
    const beschriftung = new Map();
    for (const e of Array.isArray(spec.edges) ? spec.edges : []) {
      const o = Array.isArray(e) ? { from: e[0], to: e[1], label: e[2] } : e;
      if (o && o.label && !beschriftung.has(`${o.from}>${o.to}`)) beschriftung.set(`${o.from}>${o.to}`, o.label);
    }
    for (const e of graph.edges) {
      const b = beschriftung.get(`${e.from}>${e.to}`);
      verbindungen.push(`${wie(e.from)} → ${wie(e.to)}${b ? `: ${b}` : ""}`);
    }
  }
  return { elemente, verbindungen };
}

// ── Darstellung (nur im Rahmen der App, wo GUI da ist) ─────────────────────────────────────────────────
function einsetzen(svgText) {
  const doc = new DOMParser().parseFromString(svgText, "text/html");
  return document.importNode(doc.body.firstElementChild, true);
}

// Hervorheben beim Überfahren oder Fokussieren: ein Element mit seinen Verbindungen und Nachbarn, der Rest tritt zurück.
function verdrahten(svg) {
  const knoten = new Map();
  svg.querySelectorAll("[data-sc-node]").forEach((g) => knoten.set(g.getAttribute("data-sc-node"), g));
  const kanten = [...svg.querySelectorAll("[data-sc-edge]")];
  const an = (id) => {
    const nahe = new Set([id]);
    const aktiv = new Set();
    for (const k of kanten) {
      const von = k.getAttribute("data-from"), nach = k.getAttribute("data-to");
      if (von === id || nach === id) { aktiv.add(k); nahe.add(von); nahe.add(nach); }
    }
    svg.classList.add("dg-fokus");
    knoten.forEach((g, i) => g.classList.toggle("dg-an", nahe.has(i)));
    kanten.forEach((k) => k.classList.toggle("dg-an", aktiv.has(k)));
  };
  const aus = () => {
    svg.classList.remove("dg-fokus");
    knoten.forEach((g) => g.classList.remove("dg-an"));
    kanten.forEach((k) => k.classList.remove("dg-an"));
  };
  knoten.forEach((g, id) => {
    g.addEventListener("mouseenter", () => an(id));
    g.addEventListener("focus", () => an(id));
    g.addEventListener("mouseleave", aus);
    g.addEventListener("blur", aus);
  });
}

function fehlerBox(probleme) {
  const { el } = GUI;
  return el("div", { class: "gui-karte dg-fehler", role: "alert" },
    el("h3", { text: "Das Diagramm konnte nicht gezeichnet werden" }),
    el("ul", {}, ...probleme.map((p) => el("li", {}, el("code", { text: p.at || "" }), ` ${p.msg}`, p.fix ? ` — ${p.fix}` : ""))),
    el("p", { class: "gui-text", text: "Form und Beispiel: gui.vorlagen {name: \"diagramm\"}" }));
}

function zeichnen(wurzel, d) {
  const { el } = GUI;
  const e = rendern(d);
  const kopf = GUI.kopf({ ueberschrift: d.ueberschrift || d.title, text: d.text || d.subtitle });
  if (!e.ok) { wurzel.replaceChildren(...kopf, fehlerBox(e.probleme), ...GUI.fuss(d)); return; }
  const svg = einsetzen(e.svg);
  svg.style.maxWidth = `${Math.round(e.breite * 1.25)}px`;
  verdrahten(svg);
  const teile = [...kopf, el("div", { class: "dg-bild" }, svg)];
  if (e.spec.caption) teile.push(el("p", { class: "gui-text", text: e.spec.caption }));
  teile.push(el("details", { class: "dg-liste" },
    el("summary", { text: "Als Liste lesen" }),
    el("h3", { text: "Elemente" }), el("ul", {}, ...e.liste.elemente.map((t) => el("li", { text: t }))),
    el("h3", { text: "Verbindungen" }), el("ol", {}, ...e.liste.verbindungen.map((t) => el("li", { text: t })))));
  if (e.hinweise.length) {
    teile.push(el("details", { class: "dg-liste" },
      el("summary", { text: `Hinweise zum Layout (${e.hinweise.length})` }),
      el("ul", {}, ...e.hinweise.map((p) => el("li", { text: `${p.msg}${p.fix ? ` — ${p.fix}` : ""}` })))));
  }
  teile.push(...GUI.fuss(d));
  wurzel.replaceChildren(...teile);
}

if (typeof GUI !== "undefined" && typeof document !== "undefined") {
  const wurzel = document.getElementById("v");
  GUI.beiDaten((d) => zeichnen(wurzel, d && typeof d === "object" ? d : {}));
}
// Unter Node (Prüfstand der Tests) gibt es keinen GUI-Rahmen; dort stehen nur die Rechenfunktionen bereit.
if (typeof module !== "undefined" && module.exports) module.exports = { rendern, pruefenSvg, bereinigen, ART, ALIASE, GRENZE };
})();
