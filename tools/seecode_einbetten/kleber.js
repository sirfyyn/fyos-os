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
