// Prüft die gemeinsamen Bausteine der Hub-Brücke (ui/_bruecke.js) gegen eine Mini-Attrappe von Fenster, Dokument und Host:
// Frische-Stempel, Plan-Text und die Anfrage statt Aktion (App.beantragen).
// Aufruf: node bruecke_test.mjs <_bruecke.js>
import fs from 'node:fs';
import vm from 'node:vm';

const [, , brueckePfad] = process.argv;
const MIN = 60000;
const BASIS = Date.UTC(2026, 9, 9, 12, 0, 0);

// ── Attrappe: Uhr, Fenster, Dokument ────────────────────────────────────────────────────────────────
let jetzt = BASIS;
class Uhr extends Date {
  constructor(...a) { if (a.length) super(...a); else super(jetzt); }
  static now() { return jetzt; }
}
const fensterHoerer = {}, dokumentHoerer = {}, intervalle = [], elemente = {};
const eltern = { postMessage() {} };
const fenster = {
  parent: eltern, innerWidth: 800,
  addEventListener: (art, fn) => { (fensterHoerer[art] ||= []).push(fn); },
  removeEventListener() {}, dispatchEvent() {},
};
const dokument = {
  documentElement: { dataset: {}, style: { setProperty() {}, removeProperty() {}, height: '' }, getBoundingClientRect: () => ({ height: 100 }) },
  body: {}, visibilityState: 'visible',
  addEventListener: (art, fn) => { (dokumentHoerer[art] ||= []).push(fn); },
  removeEventListener() {},
  querySelectorAll: (selektor) => elemente[selektor] || [],
  getElementById: () => null,
};
const ctx = vm.createContext({
  window: fenster, document: dokument, Date: Uhr, console,
  ResizeObserver: class { observe() {} },
  requestAnimationFrame: () => 0,
  setInterval: (fn) => { intervalle.push(fn); return intervalle.length; },
  clearInterval() {},
  setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); if (t.unref) t.unref(); return t; },
  clearTimeout, queueMicrotask, TextEncoder, btoa,
  CustomEvent: class { constructor(name, o) { this.type = name; this.detail = o && o.detail; } },
});
vm.runInContext(fs.readFileSync(brueckePfad, 'utf8'), ctx);
const App = vm.runInContext('App', ctx);

// ── Attrappe: Host. Sammelt die Werkzeugaufrufe der App und antwortet, wie der Test es vorgibt ───────────
const aufrufe = [];
let werkzeugFn = async () => ({});
function antworten(id, result) {
  for (const fn of fensterHoerer.message || []) fn({ source: eltern, data: { jsonrpc: '2.0', id, result } });
}
eltern.postMessage = (m) => {
  if (m.method !== 'tools/call') return;
  const { name, arguments: args } = m.params;
  aufrufe.push({ name, args });
  Promise.resolve().then(() => werkzeugFn(name, args)).then(
    (daten) => antworten(m.id, { content: [{ type: 'text', text: JSON.stringify(daten) }], structuredContent: daten }),
    (e) => antworten(m.id, { isError: true, content: [{ type: 'text', text: String((e && e.message) || e) }] }),
  );
};
const klick = (aktion) => {
  const el = { disabled: false, dataset: { aktion } };
  const e = { target: { closest: (selektor) => (selektor === '[data-aktion]' ? el : null) } };
  for (const fn of dokumentHoerer.click || []) fn(e);
};
const tick = async () => { for (let i = 0; i < 5; i++) await new Promise((ok) => setImmediate(ok)); };
const schleuse = () => { const s = {}; s.p = new Promise((ok, nein) => { s.ok = ok; s.nein = nein; }); return s; };
const platz = () => ({ innerHTML: '', replaceChildren() { this.innerHTML = ''; } });

const fehler = [];
const pruefe = (name, bedingung, detail) => { if (!bedingung) fehler.push(detail === undefined ? name : `${name}: ${detail}`); };
const gleich = (name, ist, soll) => pruefe(name, ist === soll, `erwartet ${JSON.stringify(soll)}, war ${JSON.stringify(ist)}`);
const vor = (min) => BASIS - min * MIN;
const grund = async (versprechen) => { try { await versprechen; return null; } catch (e) { return String((e && e.message) || e); } };

try {
// ── Frische ────────────────────────────────────────────────────────────────────────────────────────
pruefe('veraltet: 5 Min. ist frisch', App.veraltet(vor(5)) === false);
pruefe('veraltet: 20 Min. ist veraltet', App.veraltet(vor(20)) === true);
pruefe('veraltet: genau die Schwelle zählt schon als veraltet', App.veraltet(vor(15)) === true);
pruefe('veraltet: eigene Schwelle', App.veraltet(vor(20), 30) === false && App.veraltet(vor(40), 30) === true);
pruefe('veraltet: ohne Zeitpunkt', App.veraltet(null) === true && App.veraltet('') === true && App.veraltet('kein Datum') === true);
pruefe('veraltet: Zukunft ist nicht veraltet', App.veraltet(vor(-10)) === false);
pruefe('veraltet: ungültige Schwelle fällt auf die Vorgabe zurück', App.veraltet(vor(20), 'x') === true && App.veraltet(vor(5), -3) === false);

let h = App.frische(vor(5));
pruefe('frische: frisch', /^<time class="frische" /.test(h) && h.endsWith('>Stand vor 5 Min.</time>') && !h.includes('veraltet'), h);
pruefe('frische: Zeitpunkt maschinenlesbar', h.includes(`datetime="${new Date(vor(5)).toISOString()}"`) && h.includes(`data-t="${vor(5)}"`), h);
h = App.frische(vor(3 * 60));
pruefe('frische: veraltet', h.includes('class="frische veraltet"') && h.endsWith('>Stand vor 3 Std. · veraltet</time>'), h);
h = App.frische(null);
pruefe('frische: ohne Zeitpunkt', h.includes('class="frische veraltet"') && h.includes('Stand unbekannt · veraltet'), h);
h = App.frische(vor(30), { text: 'Gemessen', schwelleMin: 60 });
pruefe('frische: eigener Text und eigene Schwelle', h.endsWith('>Gemessen vor 30 Min.</time>') && !h.includes('veraltet'), h);
h = App.frische(vor(-10));
pruefe('frische: Zeitpunkt in der Zukunft zeigt „gerade eben“', h.endsWith('>Stand gerade eben</time>') && !h.includes('veraltet'), h);
pruefe('frische: Unix-Sekunden', App.frische(Math.floor(vor(10) / 1000)).includes('Stand vor 10 Min.'));
pruefe('frische: ISO-Text', App.frische(new Date(vor(2)).toISOString()).includes('Stand vor 2 Min.'));
h = App.frische(vor(5), { text: '<b>"x"</b>', klasse: '"><script>x</script>' });
pruefe('frische: Eingesetztes ist maskiert', !h.includes('<b>') && !h.includes('<script>') && !h.includes('"><'), h);
pruefe('frische: nie null oder undefined sichtbar', ![null, undefined, '', 'x', 0].some((t) => /\bnull\b|undefined/.test(App.frische(t))));

// Nachführung: der Stempel rückt von selbst nach und kippt auf „veraltet“ (und zurück, wenn neue Daten kommen)
const stempel = {
  dataset: { t: String(vor(10)), schwelle: '15', vor: 'Stand' }, textContent: 'Stand vor 10 Min.', klassen: new Set(),
  classList: { toggle: (name, an) => { if (an) stempel.klassen.add(name); else stempel.klassen.delete(name); } },
};
elemente['time.frische[data-t]'] = [stempel];
jetzt = BASIS + 10 * MIN;
intervalle[0]();
gleich('Nachführung: Text nach 10 weiteren Minuten', stempel.textContent, 'Stand vor 20 Min. · veraltet');
pruefe('Nachführung: Klasse veraltet gesetzt', stempel.klassen.has('veraltet'));
stempel.dataset.t = String(jetzt - 5 * MIN);
intervalle[0]();
gleich('Nachführung: neuere Daten, frischer Text', stempel.textContent, 'Stand vor 5 Min.');
pruefe('Nachführung: Klasse veraltet wieder weg', !stempel.klassen.has('veraltet'));
jetzt = BASIS;
delete elemente['time.frische[data-t]'];

// ── Plan ───────────────────────────────────────────────────────────────────────────────────────────
let p = App.plan({ would_execute: 'Notiz speichern', expected_side_effects: ['k: neu', 'k2: ersetzt'] });
pruefe('plan: Satz und Wirkungen', p === '<strong>Notiz speichern</strong><span class="wirkungen"><span>k: neu</span><span>k2: ersetzt</span></span>', p);
p = App.plan({ would_execute: '<img src=x onerror=1>', expected_side_effects: ['<script>1</script>'] });
pruefe('plan: maskiert', !p.includes('<img') && !p.includes('<script>') && p.includes('&lt;img'), p);
for (const leer of [null, undefined, {}, 'text', 5, [], { expected_side_effects: 'x' }]) {
  gleich(`plan: robust bei ${JSON.stringify(leer)}`, App.plan(leer), '<strong>Die Aktion ausführen</strong>');
}
p = App.plan({ would_execute: 'x', expected_side_effects: ['', null, 'a: b'] });
pruefe('plan: leere Wirkungen fallen weg', p.includes('<span>a: b</span>') && (p.match(/<span>/g) || []).length === 1, p);

// ── Anfrage statt Aktion ────────────────────────────────────────────────────────────────────────────
const planDaten = (text) => ({
  ok: true, dry_run: true, would_execute: `Notiz mit ${text.length} Zeichen speichern`,
  expected_side_effects: ['notiz: neu angelegt'], estimated_cost: 1, plugin: 'vorlage', method: 'notiz_setzen', args_preview: null,
});
function standardHost() {
  aufrufe.length = 0;
  werkzeugFn = async (name, args) => {
    if (args.__dry_run__) return planDaten(args.text);
    if (args.bestaetigt !== true) throw new Error('ValueError: Nichts geändert: ein echter Lauf braucht bestaetigt: true');
    return { ok: true, satz: 'Notiz gespeichert.', notiz: args.text };
  };
}
const antrag = (ort, text = 'hallo', extra = {}) => App.beantragen({ werkzeug: 'vorlage__notiz_setzen', args: { text }, ort, ja: 'Speichern', ...extra });

{ // Ja: erst der Plan, nach dem Klick der echte Lauf
  standardHost();
  const ort = platz();
  const erg = antrag(ort);
  await tick();
  gleich('Antrag: vor dem Klick genau ein Aufruf', aufrufe.length, 1);
  pruefe('Antrag: der erste Aufruf ist der Trockenlauf', aufrufe[0].args.__dry_run__ === true && aufrufe[0].args.text === 'hallo' && !('bestaetigt' in aufrufe[0].args), JSON.stringify(aufrufe[0]));
  pruefe('Antrag: der Plan steht in der Rückfrage', ort.innerHTML.includes('Notiz mit 5 Zeichen speichern') && ort.innerHTML.includes('notiz: neu angelegt'), ort.innerHTML);
  pruefe('Antrag: Ja- und Nein-Knopf', ort.innerHTML.includes('data-aktion="antrag-ja"') && ort.innerHTML.includes('Speichern</button>')
    && ort.innerHTML.includes('data-aktion="antrag-nein"') && ort.innerHTML.includes('Abbrechen</button>') && ort.innerHTML.includes('class="antrag"'), ort.innerHTML);
  klick('antrag-ja');
  const r = await erg;
  gleich('Antrag: zwei Aufrufe nach „Ja“', aufrufe.length, 2);
  pruefe('Antrag: der echte Lauf trägt bestaetigt und kein __dry_run__', aufrufe[1].args.bestaetigt === true && !('__dry_run__' in aufrufe[1].args) && aufrufe[1].args.text === 'hallo', JSON.stringify(aufrufe[1]));
  pruefe('Antrag: Ergebnis des echten Laufs', r && r.satz === 'Notiz gespeichert.', JSON.stringify(r));
  gleich('Antrag: der Platz ist danach leer', ort.innerHTML, '');
}

{ // Abbrechen: kein echter Lauf
  standardHost();
  const ort = platz();
  const erg = antrag(ort);
  await tick();
  klick('antrag-nein');
  gleich('Antrag abbrechen: Ergebnis null', await erg, null);
  gleich('Antrag abbrechen: nur der Trockenlauf lief', aufrufe.length, 1);
  gleich('Antrag abbrechen: Platz leer', ort.innerHTML, '');
  klick('antrag-ja'); // nichts mehr offen: ein später Klick tut nichts
  await tick();
  gleich('Antrag abbrechen: ein später Klick löst nichts aus', aufrufe.length, 1);
}

{ // Ohne Klick passiert nichts Schreibendes
  standardHost();
  antrag(platz());
  await tick();
  pruefe('Antrag ohne Klick: kein Aufruf mit bestaetigt', aufrufe.every((a) => a.args.bestaetigt !== true));
  klick('antrag-nein');
}

{ // Ein neuer Antrag löst den offenen ab
  standardHost();
  const ort = platz();
  const eins = antrag(ort, 'eins');
  await tick();
  const zwei = antrag(ort, 'zwei!');
  await tick();
  gleich('Antrag ablösen: der alte ergibt null', await eins, null);
  pruefe('Antrag ablösen: der neue Plan steht da', ort.innerHTML.includes('Notiz mit 5 Zeichen speichern') && !ort.innerHTML.includes('Notiz mit 4 Zeichen'), ort.innerHTML);
  klick('antrag-ja');
  await zwei;
  const echt = aufrufe.filter((a) => a.args.bestaetigt === true);
  pruefe('Antrag ablösen: nur der neue Antrag lief wirklich', echt.length === 1 && echt[0].args.text === 'zwei!', JSON.stringify(echt));
}

{ // Ein überholter Trockenlauf zeichnet nichts mehr
  const warten = schleuse();
  let n = 0;
  aufrufe.length = 0;
  werkzeugFn = async (name, args) => {
    if (args.__dry_run__) { n += 1; if (n === 1) await warten.p; return planDaten(args.text); }
    return { ok: true, satz: 'Notiz gespeichert.' };
  };
  const ort = platz();
  const eins = antrag(ort, 'eins');
  const zwei = antrag(ort, 'zwei!');
  await tick();
  warten.ok();
  await tick();
  gleich('Antrag überholt: der erste ergibt null', await eins, null);
  pruefe('Antrag überholt: der Platz zeigt den zweiten Plan', ort.innerHTML.includes('Notiz mit 5 Zeichen speichern'), ort.innerHTML);
  klick('antrag-nein');
  gleich('Antrag überholt: der zweite lässt sich abbrechen', await zwei, null);
}

{ // Während der Ausführung: Knöpfe gesperrt, doppelter Klick löst einmal aus, ein neuer Antrag wird abgewiesen
  const lauf = schleuse();
  aufrufe.length = 0;
  werkzeugFn = async (name, args) => {
    if (args.__dry_run__) return planDaten(args.text);
    await lauf.p;
    return { ok: true, satz: 'Notiz gespeichert.' };
  };
  const ort = platz();
  const erg = antrag(ort);
  await tick();
  klick('antrag-ja'); klick('antrag-ja');
  await tick();
  gleich('Antrag läuft: der doppelte Klick löst einmal aus', aufrufe.filter((a) => a.args.bestaetigt === true).length, 1);
  pruefe('Antrag läuft: die Knöpfe sind gesperrt', ort.innerHTML.includes('aria-busy="true"') && ort.innerHTML.includes('disabled'), ort.innerHTML);
  klick('antrag-nein'); // während der Ausführung gibt es kein Abbrechen mehr
  const abgewiesen = await grund(antrag(ort, 'noch eins'));
  pruefe('Antrag läuft: ein neuer Antrag wird abgewiesen', /läuft noch/.test(abgewiesen || ''), String(abgewiesen));
  lauf.ok();
  const r = await erg;
  pruefe('Antrag läuft: das Ergebnis kommt trotzdem an', r && r.satz === 'Notiz gespeichert.', JSON.stringify(r));
}

{ // Fehler im Trockenlauf: lesbarer Text, kein echter Lauf, Platz leer
  aufrufe.length = 0;
  werkzeugFn = async () => { throw new Error('ValueError: text ist zu lang'); };
  const ort = platz();
  gleich('Antrag Fehler im Trockenlauf: Text', await grund(antrag(ort)), 'text ist zu lang');
  gleich('Antrag Fehler im Trockenlauf: nur ein Aufruf', aufrufe.length, 1);
  gleich('Antrag Fehler im Trockenlauf: Platz leer', ort.innerHTML, '');
}

{ // Werkzeug ohne Trockenlauf oder ohne Plan: die Oberfläche fragt gar nicht erst
  const stumm = /nicht vorab zeigen/;
  for (const [name, antwort] of [
    ['dry_run_unsupported', { ok: false, error: 'dry_run_unsupported', plugin: 'x', method: 'y' }],
    ['Ergebnis ohne dry_run', { ok: true, satz: 'Notiz gespeichert.' }],
    ['leeres Ergebnis', {}],
  ]) {
    aufrufe.length = 0;
    werkzeugFn = async () => antwort;
    const ort = platz();
    pruefe(`Antrag ohne Plan (${name}): Fehlertext`, stumm.test((await grund(antrag(ort))) || ''));
    gleich(`Antrag ohne Plan (${name}): nur ein Aufruf`, aufrufe.length, 1);
    gleich(`Antrag ohne Plan (${name}): Platz leer`, ort.innerHTML, '');
  }
  werkzeugFn = async () => ({ ok: false, error: 'Konto nicht verbunden' });
  gleich('Antrag: Fehlertext des Werkzeugs bleibt erhalten', await grund(antrag(platz())), 'Konto nicht verbunden');
}

{ // Fehler im echten Lauf: lesbarer Text, Platz leer, danach geht es wieder
  aufrufe.length = 0;
  werkzeugFn = async (name, args) => { if (args.__dry_run__) return planDaten(args.text); throw new Error('RuntimeError: Speicher nicht erreichbar'); };
  const ort = platz();
  const erg = antrag(ort);
  await tick();
  klick('antrag-ja');
  gleich('Antrag Fehler im Lauf: Text', await grund(erg), 'Speicher nicht erreichbar');
  gleich('Antrag Fehler im Lauf: Platz leer', ort.innerHTML, '');
  standardHost();
  const neu = antrag(ort);
  await tick();
  klick('antrag-ja');
  pruefe('Antrag nach einem Fehler: es geht wieder', (await neu).satz === 'Notiz gespeichert.');
}

{ // Eingaben prüfen und Texte maskieren
  standardHost();
  gleich('Antrag ohne ort: Fehlertext', await grund(App.beantragen({ werkzeug: 'x' })), 'beantragen: werkzeug und ort sind nötig');
  gleich('Antrag ohne Werkzeug: Fehlertext', await grund(App.beantragen({ ort: platz() })), 'beantragen: werkzeug und ort sind nötig');
  const ort = platz();
  const erg = antrag(ort, 'hallo', { ja: '<script>1</script>', nein: '<b>nein</b>' });
  await tick();
  pruefe('Antrag: Knopftexte sind maskiert', !ort.innerHTML.includes('<script>') && !ort.innerHTML.includes('<b>') && ort.innerHTML.includes('&lt;script&gt;'), ort.innerHTML);
  klick('antrag-nein');
  await erg;
}
} catch (e) { fehler.push(`Abbruch: ${(e && e.stack) || e}`); }

if (fehler.length) { console.error(fehler.join('\n')); process.exit(1); }
console.log('ok');
process.exit(0);
