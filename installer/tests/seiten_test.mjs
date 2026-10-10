// Rendert jeden Schritt des Web-Assistenten gegen eine Mini-DOM-Attrappe und prüft den sichtbaren Text.
// Aufruf: node seiten_test.mjs <app.js> <katalog.json> [<beispiele.json>]
// beispiele.json trägt echte Serverantworten: { plan, abnahme_ok, abnahme_nein }.
import fs from 'node:fs';
import vm from 'node:vm';

const [, , appPfad, katalogPfad, beispielePfad] = process.argv;
const katalog = JSON.parse(fs.readFileSync(katalogPfad, 'utf8'));
const beispiele = beispielePfad ? JSON.parse(fs.readFileSync(beispielePfad, 'utf8')) : null;

class Node {}
class Text extends Node {
  constructor(t) { super(); this.textContent = t; }
}
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.kinder = []; this.attrs = {}; this.style = {}; }
  append(...a) { for (const x of a) this.kinder.push(x instanceof Node ? x : new Text(String(x))); }
  replaceChildren(...a) { this.kinder = []; this.append(...a); }
  addEventListener() {}
  setAttribute(k, v) { this.attrs[k] = v; }
  focus() {}
  click() {}
  closest() { return null; }
  get textContent() { return this.kinder.map((k) => k.textContent).join(' '); }
  set textContent(t) { this.kinder = t ? [new Text(t)] : []; }
}
const statisch = { inhalt: new El('main'), schritte: new El('ol'), fuss: new El('footer') };
const document = {
  createElement: (t) => new El(t),
  createTextNode: (t) => new Text(t),
  getElementById: (id) => statisch[id] || null,
  addEventListener() {},
  activeElement: null,
};
const antwort = (json, status = 200) => ({ status, json: async () => json });
const ctx = vm.createContext({
  document, window: { scrollY: 0, scrollTo() {} }, Node, console, setTimeout, EventSource: class {},
  fetch: async (pfad) => antwort(pfad === '/api/katalog' ? katalog : {}),
});
vm.runInContext(fs.readFileSync(appPfad, 'utf8'), ctx);
await new Promise((r) => setTimeout(r, 50));

const fehler = [];
const text = (n) => statisch.inhalt.textContent;
for (let n = 0; n < 6; n++) {
  vm.runInContext(`S.schritt = ${n}; S.plan = {ok: true, dateien: [], befehle: [], hinweise: [], fehler: []}; zeigeInhalt();`, ctx);
  const t = text();
  if (/\bnull\b|undefined/.test(t)) fehler.push(`Schritt ${n}: sichtbares null/undefined: ${t.slice(0, 200)}`);
  if (n === 3) {
    for (const soll of ['Port', 'Öffentliche Adresse', 'Bezug der Pakete']) if (!t.includes(soll)) fehler.push(`Schritt 3 ohne "${soll}"`);
    for (const nicht of ['oeffentliche_url', 'Bitte prüfen', 'Bitte ausfüllen']) if (t.includes(nicht)) fehler.push(`Schritt 3 zeigt "${nicht}" sofort`);
  }
}
// Finanz-Felder mit Titel statt Rohnamen
vm.runInContext("setzeWahl('finanzen', true); S.schritt = 3; zeigeInhalt();", ctx);
const t3 = text();
for (const soll of ['Adresse des Monatsplan-Dienstes', 'Zugangs-Kopfzeile', 'Index-URL']) if (!t3.includes(soll)) fehler.push(`Finanzen-Einrichten ohne "${soll}"`);
for (const nicht of ['finanzen_url', 'life_url', 'auth_header']) if (t3.includes(nicht)) fehler.push(`Rohname "${nicht}" sichtbar`);
// Fehlerkasten erst nach Weiter-Versuch
vm.runInContext("S.planFehler = ['x kaputt']; gehe(3);", ctx);
await new Promise((r) => setTimeout(r, 20));
if (text().includes('x kaputt')) fehler.push('planFehler nach Betreten noch sichtbar');

// Klassen aller Knoten unter dem Inhalt (die Attrappe hält `className` als Eigenschaft)
const klassen = (n, ziel = []) => {
  if (n.className) ziel.push(n.className);
  (n.kinder || []).forEach((k) => klassen(k, ziel));
  return ziel;
};
const zeigeSchritt = (n, plan) => {
  ctx.testPlan = plan;
  vm.runInContext(`S.schritt = ${n}; S.plan = testPlan; zeigeInhalt();`, ctx);
};
const zeigeEnde = (ende) => {
  ctx.testEnde = ende;
  vm.runInContext('S.schritt = 5; S.inst = { laeuft: false, gestartet: true, pre: null, ende: testEnde }; zeigeInhalt();', ctx);
  return text();
};
const pruefeText = (wo, t, soll = [], nicht = []) => {
  if (/\bnull\b|undefined/.test(t)) fehler.push(`${wo}: sichtbares null/undefined: ${t.slice(0, 200)}`);
  for (const s of soll) if (!t.includes(s)) fehler.push(`${wo} ohne "${s}"`);
  for (const s of nicht) if (t.includes(s)) fehler.push(`${wo} zeigt "${s}"`);
};

if (beispiele) {
  // Zusammenfassung: der Reifegrad je Schicht mit Stufe, Satz »woran erkennbar« und nächster Stufe
  const reife = beispiele.plan.reife;
  if (!Array.isArray(reife) || reife.length !== 4) fehler.push('Plan der Beispiele ohne vier Reifegrade');
  zeigeSchritt(4, beispiele.plan);
  const tz = text();
  pruefeText('Zusammenfassung', tz, ['Reifegrad', 'Schicht', 'Woran erkennbar']);
  for (const r of reife) {
    pruefeText(`Reifegrad ${r.schicht}`, tz, [r.titel, `${r.stufe} von ${r.von}`, r.name, r.erkennbar]);
    if (r.naechste) pruefeText(`Reifegrad ${r.schicht}`, tz, ['Nächste Stufe: ' + r.naechste]);
  }
  const gezaehlt = (tz.match(/Nächste Stufe:/g) || []).length;
  const erwartet = reife.filter((r) => r.naechste).length;
  if (gezaehlt !== erwartet) fehler.push(`Zusammenfassung zeigt ${gezaehlt} nächste Stufen statt ${erwartet}`);
  // ein Plan eines älteren Servers ohne `reife` zeigt keine leere Tabelle
  zeigeSchritt(4, { ...beispiele.plan, reife: undefined });
  pruefeText('Zusammenfassung ohne reife', text(), ['Dateien'], ['Reifegrad', 'Woran erkennbar']);

  // Ergebnis der Installation: Abnahme bestanden
  const url = 'http://localhost:8080';
  const gut = zeigeEnde({ ok: true, meldung: `FYOS läuft: ${url}. ${beispiele.abnahme_ok.zusammenfassung}`, url, abnahme: beispiele.abnahme_ok });
  pruefeText('Ergebnis, Abnahme bestanden', gut,
    ['Fertig.', 'Abnahme bestanden: alle 3 verbotenen Anfragen wurden abgelehnt.', 'Abnahme im Einzelnen:', 'FYOS öffnen', ...beispiele.abnahme_ok.befunde.map((b) => b.titel)],
    ['Gestartet, aber nicht abgenommen', 'nicht bestanden', 'Erneut versuchen']);
  const kg = klassen(statisch.inhalt);
  if (!kg.includes('meldung ok') || !kg.includes('abnahme')) fehler.push(`Ergebnis, Abnahme bestanden: Klassen ${kg.join(' | ')}`);
  if (kg.some((k) => k.includes('durchgefallen') || k.includes('warnung'))) fehler.push('Ergebnis, Abnahme bestanden: zeigt Warnklassen');

  // Ergebnis der Installation: gestartet, aber nicht abgenommen
  const nein = beispiele.abnahme_nein;
  const durchgefallen = nein.befunde.filter((b) => !b.ok);
  if (!durchgefallen.length) fehler.push('abnahme_nein hat keinen durchgefallenen Befund');
  const schlecht = zeigeEnde({ ok: true, meldung: `FYOS läuft: ${url}. ${nein.zusammenfassung}`, url, abnahme: nein });
  pruefeText('Ergebnis, Abnahme nicht bestanden', schlecht,
    ['Gestartet, aber nicht abgenommen.', 'Abnahme NICHT bestanden', 'Abnahme nicht bestanden, im Einzelnen:', 'FYOS öffnen',
      ...durchgefallen.flatMap((b) => [b.titel, b.text, 'Prüfen: ' + b.hilfe])],
    ['Fertig.', 'Erneut versuchen']);
  const ks = klassen(statisch.inhalt);
  for (const k of ['meldung warnung', 'abnahme durchgefallen', 'zeile-fehler']) if (!ks.includes(k)) fehler.push(`Ergebnis, Abnahme nicht bestanden ohne Klasse "${k}": ${ks.join(' | ')}`);

  // Ohne Abnahme (Ziel Dateien, ältere Server, Abnahme nicht gelaufen): wie bisher
  pruefeText('Ergebnis ohne Abnahme', zeigeEnde({ ok: true, meldung: 'Dateien erzeugt.', url: null, abnahme: null }),
    ['Fertig.', 'Dateien erzeugt.'], ['Abnahme', 'FYOS öffnen']);
  pruefeText('Ergebnis eines älteren Servers', zeigeEnde({ ok: true, meldung: 'Dateien erzeugt.', url: null }),
    ['Fertig.'], ['Abnahme']);
  const kaputt = zeigeEnde({ ok: false, meldung: 'Docker fehlt', url: null, abnahme: null });
  pruefeText('Ergebnis, Start gescheitert', kaputt, ['Das hat nicht geklappt.', 'Docker fehlt', 'Erneut versuchen'], ['Abnahme', 'Fertig.']);
  if (!klassen(statisch.inhalt).includes('meldung fehler')) fehler.push('Ergebnis, Start gescheitert ohne Klasse "meldung fehler"');
}

if (fehler.length) { console.error(fehler.join('\n')); process.exit(1); }
console.log('ok');
