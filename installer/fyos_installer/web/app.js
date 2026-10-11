'use strict';
// Web-Assistent des FYOS-Installers. Kein Framework, keine fremden Ressourcen (läuft offline).

const SCHRITTE = ['Willkommen', 'Ziel', 'Bausteine', 'Einrichten', 'Zusammenfassung', 'Installieren'];
const ZIEL_TEXTE = {
  compose: ['Docker Compose auf diesem Rechner', 'Der Installer erzeugt die Dateien, baut das Hub-Bild und startet FYOS auf diesem Rechner.'],
  k8s: ['Kubernetes', 'Der Installer erzeugt ein Kustomize-Overlay für deinen Cluster. Angewendet wird es mit kubectl, von dir.'],
  dateien: ['Nur Dateien erzeugen', 'Der Installer schreibt Dateien und eine Anleitung. Gestartet wird später von dir.'],
};
const SPRACHEN = ['Deutsch', 'English', 'Français', 'Español', 'Italiano', 'Nederlands'];

const S = {
  katalog: null, schritt: 0, ziel: 'compose', gewaehlt: new Set(), persona: {}, modell: {}, optionen: {},
  felder: {}, verzeichnis: '', plan: null, planFehler: [], galerie: {}, vorschau: false, urlBeruehrt: false,
  beruehrt: new Set(), versucht: false,
  stufen: {}, // ausdrücklich gewählte Stufen je Fähigkeit; was fehlt, bekommt die Vorgabe der Bauart
  inst: { laeuft: false, gestartet: false, pre: null, ende: null },
};

// ---------------------------------------------------------------- Hilfen

function h(tag, attrs, ...kinder) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  const anhaengen = (x) => {
    if (x == null || x === false) return;
    if (Array.isArray(x)) x.forEach(anhaengen);
    else el.append(x instanceof Node ? x : document.createTextNode(String(x)));
  };
  kinder.forEach(anhaengen);
  return el;
}

async function api(pfad, daten) {
  const opt = daten === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(daten),
  };
  const r = await fetch(pfad, { credentials: 'same-origin', ...opt });
  let json = null;
  try { json = await r.json(); } catch (e) { /* kein JSON */ }
  return { status: r.status, json };
}

function inline(text) {
  const teile = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let letzter = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > letzter) teile.push(text.slice(letzter, m.index));
    const t = m[0];
    if (t.startsWith('**')) teile.push(h('strong', null, t.slice(2, -2)));
    else if (t.startsWith('`')) teile.push(h('code', null, t.slice(1, -1)));
    else teile.push(h('em', null, t.slice(1, -1)));
    letzter = m.index + t.length;
  }
  if (letzter < text.length) teile.push(text.slice(letzter));
  return teile;
}

function markdown(text) {
  const wurzel = h('div', { class: 'erklaerung' });
  text.split(/\n\s*\n/).forEach((block) => {
    const zeilen = block.split('\n').map((z) => z.trim()).filter(Boolean);
    if (!zeilen.length) return;
    if (zeilen.every((z) => /^[-*] /.test(z))) wurzel.append(h('ul', null, zeilen.map((z) => h('li', null, inline(z.slice(2))))));
    else wurzel.append(h('p', null, inline(zeilen.join(' '))));
  });
  return wurzel;
}

const B = (id) => S.katalog.bausteine.find((b) => b.id === id);

function transitiv(id, menge = new Set()) {
  for (const a of B(id).abhaengig_von) if (!menge.has(a)) { menge.add(a); transitiv(a, menge); }
  return menge;
}

function setzeWahl(id, an) {
  if (an) {
    S.gewaehlt.add(id);
    transitiv(id).forEach((a) => S.gewaehlt.add(a));
  } else {
    S.katalog.bausteine.forEach((b) => { if (b.id !== id && transitiv(b.id).has(id)) S.gewaehlt.delete(b.id); });
    S.gewaehlt.delete(id);
  }
  S.katalog.bausteine.filter((b) => b.pflicht).forEach((b) => S.gewaehlt.add(b.id));
}

const gewaehlteBausteine = () => S.katalog.bausteine.filter((b) => S.gewaehlt.has(b.id));

// Stufe je Fähigkeit: Grundstufe, Ausbaustufe oder aus. Gewählt ist, was der Nutzer angeklickt hat, sonst die Vorgabe der Bauart.
const faehigkeitenVon = (b) => (S.katalog.faehigkeiten || []).filter((f) => f.baustein === b.id);
const stufeVon = (f) => S.stufen[f.id] || f.vorgabe[S.ziel] || f.moegliche[0];

// Ein Feld, das nur zu einer Stufe gehört, die nicht gilt, wird weder gezeigt noch geschickt.
function feldGilt(b, name) {
  for (const f of faehigkeitenVon(b)) {
    for (const s of f.stufen) if (s.felder.includes(name)) return s.id === stufeVon(f);
  }
  return true;
}

function nutzlast() {
  const felder = {}, stufen = {};
  gewaehlteBausteine().forEach((b) => {
    if (b.konfiguration.length) {
      felder[b.id] = Object.fromEntries(Object.entries(S.felder[b.id] || {}).filter(([name]) => feldGilt(b, name)));
    }
    faehigkeitenVon(b).forEach((f) => { if (S.stufen[f.id]) stufen[f.id] = S.stufen[f.id]; });
  });
  return {
    auswahl: [...S.gewaehlt], ziel: S.ziel, verzeichnis: S.verzeichnis,
    antworten: { persona: S.persona, modell: S.modell, optionen: S.optionen, felder, stufen },
  };
}

// ---------------------------------------------------------------- Bausteinkarte mit Galerie

function galerie(b) {
  if (!b.bilder.length) return h('div', { class: 'galerie' }, h('div', { class: 'platz' }, 'Kein Bild vorhanden'));
  const nr = S.galerie[b.id] || 0;
  const bild = h('img', { src: b.bilder[nr], alt: `Beispielbild zu ${b.titel} (${nr + 1} von ${b.bilder.length})`, loading: 'lazy' });
  const gehe = (d) => { S.galerie[b.id] = (nr + d + b.bilder.length) % b.bilder.length; zeigeInhalt(); };
  const steuer = b.bilder.length > 1 ? h('div', { class: 'steuer' },
    h('button', { type: 'button', 'aria-label': 'Vorheriges Bild', onclick: () => gehe(-1) }, '‹'),
    h('span', { class: 'zahl', 'aria-live': 'polite' }, `${nr + 1} / ${b.bilder.length}`),
    h('button', { type: 'button', 'aria-label': 'Nächstes Bild', onclick: () => gehe(1) }, '›')) : null;
  return h('div', {
    class: 'galerie', tabindex: b.bilder.length > 1 ? '0' : null,
    onkeydown: (e) => { if (e.key === 'ArrowLeft') { gehe(-1); e.preventDefault(); } if (e.key === 'ArrowRight') { gehe(1); e.preventDefault(); } },
  }, bild, steuer);
}

function karte(b) {
  const an = S.gewaehlt.has(b.id);
  const mit = [...transitiv(b.id)].map((id) => B(id).titel);
  return h('article', { class: 'karte' + (an ? ' an' : ''), 'aria-labelledby': 'k-' + b.id },
    galerie(b),
    h('div', null,
      h('div', { class: 'kopfzeile' },
        h('input', {
          type: 'checkbox', id: 'c-' + b.id, checked: an, disabled: b.pflicht,
          'aria-describedby': 'kurz-' + b.id,
          onchange: (e) => { setzeWahl(b.id, e.target.checked); zeigeInhalt(); document.getElementById('c-' + b.id)?.focus(); },
        }),
        h('div', null,
          h('h3', { id: 'k-' + b.id }, h('label', { for: 'c-' + b.id }, b.titel)),
          h('div', { class: 'leise', id: 'kurz-' + b.id }, b.kurz))),
      h('div', { class: 'marken' },
        b.pflicht ? h('span', { class: 'marke-klein pflicht' }, 'immer dabei') : null,
        h('span', { class: 'marke-klein' }, b.art),
        mit.length && !b.pflicht ? h('span', { class: 'marke-klein' }, 'nimmt mit: ' + mit.join(', ')) : null,
        b.herkunft !== 'installer' ? h('span', { class: 'marke-klein' }, 'aus ' + b.herkunft) : null),
      h('h4', { class: 'leise' }, 'Was daraus wird'),
      markdown(b.was_daraus_wird),
      b.voraussetzungen.length ? h('div', { class: 'voraus' }, h('strong', null, 'Voraussetzungen'),
        h('ul', null, b.voraussetzungen.map((v) => h('li', null, v)))) : null));
}

// ---------------------------------------------------------------- Schritte

function seiteWillkommen() {
  const kern = S.katalog.bausteine.find((b) => b.id === 'kern');
  const bild = kern && kern.bilder[0];
  return [
    h('div', { class: 'willkommen' },
      h('div', null,
        h('h1', { tabindex: '-1', id: 'titel' }, 'Willkommen bei FYOS'),
        h('p', { class: 'einleitung' }, 'FYOS ist dein persönliches Betriebssystem im Browser, aufgebaut auf einem eigenen Agenten. Du wählst, was du brauchst, und siehst vorher, was daraus wird.'),
        h('p', { class: 'leise' }, 'Das dauert wenige Minuten. Nichts wird geschrieben oder gestartet, bevor du es ausdrücklich bestätigst. Alle Eingaben bleiben auf diesem Rechner.')),
      bild ? h('img', { src: bild, alt: 'Skizze eines FYOS-Desktops mit Fenstern und Dock' }) : null),
  ];
}

function seiteZiel() {
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, 'Wohin soll FYOS?'),
    h('p', { class: 'leise' }, 'Das Ziel bestimmt, welche Dateien entstehen. Du kannst den Assistenten jederzeit mit einem anderen Ziel wiederholen.'),
    h('div', { class: 'auswahl-gitter', role: 'radiogroup', 'aria-label': 'Ziel' },
      Object.entries(ZIEL_TEXTE).map(([id, [titel, text]]) => h('label', { class: 'wahl' },
        h('input', { type: 'radio', name: 'ziel', value: id, checked: S.ziel === id, onchange: () => { S.ziel = id; zeigeInhalt(); document.querySelector(`input[value="${id}"]`)?.focus(); } }),
        ' ', h('span', { class: 'titel' }, titel), h('span', { class: 'kurz' }, text)))),
    S.ziel === 'compose' && !S.katalog.docker.bereit
      ? h('div', { class: 'meldung fehler' }, h('strong', null, 'Hinweis: '), S.katalog.docker.meldung, ' Du kannst trotzdem Dateien erzeugen und später selbst starten.') : null,
    S.ziel === 'compose' && S.katalog.docker.bereit ? h('div', { class: 'meldung ok' }, S.katalog.docker.meldung) : null,
  ];
}

function seiteBausteine() {
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, 'Was soll FYOS können?'),
    h('p', { class: 'leise' }, 'Wähle Bausteine aus. Rechts steht, was daraus wird; die Bilder sind Skizzen und zeigen die Richtung. Abhängigkeiten werden automatisch mitgewählt.'),
    S.katalog.bausteine.map(karte),
  ];
}

function feld(gruppe, f, werte, bei) {
  const id = `f-${gruppe}-${f.name}`;
  const typ = { geheim: 'password', url: 'url', zahl: 'number', text: 'text' }[f.typ];
  // Fehlertext erst nach Verlassen des Feldes oder nach dem ersten »Weiter«
  const meldung = h('span', { class: 'fehlertext', id: id + '-f', role: 'alert' });
  const pruefe = () => {
    const leer = f.pflicht && !String(werte[f.name] ?? '').trim();
    meldung.textContent = leer && (S.beruehrt.has(id) || S.versucht) ? 'Bitte ausfüllen.' : '';
  };
  pruefe();
  const eingabe = f.typ === 'wahl'
    ? h('select', { id, onchange: (e) => bei(e.target.value) }, f.optionen.map((o) => {
      const [wert, text] = Array.isArray(o) ? o : [o, o];
      return h('option', { value: wert, selected: String(werte[f.name]) === wert }, text);
    }))
    : h('input', {
      id, type: typ, value: werte[f.name] ?? '', autocomplete: 'off', spellcheck: 'false',
      oninput: (e) => { bei(e.target.value); pruefe(); }, onblur: () => { S.beruehrt.add(id); pruefe(); },
      list: f.liste || null,
    });
  return h('div', { class: 'feld' },
    h('label', { for: id }, f.titel || f.name, f.pflicht ? h('span', { class: 'pflichtstern', 'aria-label': ' (Pflicht)' }, ' *') : null),
    eingabe, f.beschreibung ? h('span', { class: 'hilfe' }, f.beschreibung) : null, meldung);
}

// Eine Auswahl je Fähigkeit: Grundstufe, Ausbaustufe, falls erlaubt aus. Nicht vorhandene Stufen sind sichtbar gesperrt.
function stufenWahl(f) {
  const aktiv = stufeVon(f);
  const optionen = f.stufen.map((s) => ({ id: s.id, name: s.name, titel: s.titel, text: s.text, frei: s.verfuegbar }));
  if (f.aus) {
    optionen.push({ id: 'aus', name: 'aus', titel: 'nicht einrichten', frei: true,
      text: `${f.titel} bleibt nicht eingerichtet; der Agent sagt das ehrlich, statt etwas zu erfinden.` });
  }
  const vorgabe = f.vorgabe[S.ziel];
  return h('div', { class: 'stufen', role: 'radiogroup', 'aria-label': `Stufe: ${f.titel}` },
    h('div', null, h('strong', null, f.titel), ' ', h('span', { class: 'leise' }, f.kurz)),
    h('div', { class: 'stufen-wahl' }, optionen.map((o) => h('label', { class: 'wahl' + (o.frei ? '' : ' gesperrt') },
      h('input', {
        type: 'radio', name: 'stufe-' + f.id, value: o.id, checked: aktiv === o.id, disabled: !o.frei,
        onchange: () => {
          S.stufen[f.id] = o.id; zeigeInhalt();
          document.querySelector(`input[name="stufe-${f.id}"][value="${o.id}"]`)?.focus();
        },
      }),
      ' ', h('span', { class: 'titel' }, `${o.name}: ${o.titel}` + (o.id === vorgabe ? ' (Vorgabe)' : '')),
      h('span', { class: 'kurz' }, o.text)))));
}

function seiteEinrichten() {
  const quelleNoetig = gewaehlteBausteine().some((b) => b.braucht_quelle);
  const p = S.persona, m = S.modell, o = S.optionen;
  const gruppen = gewaehlteBausteine().filter((b) => b.konfiguration.length).map((b) => {
    S.felder[b.id] = S.felder[b.id] || {};
    b.konfiguration.forEach((f) => { if (!(f.name in S.felder[b.id])) S.felder[b.id][f.name] = f.standard; });
    return h('fieldset', null, h('legend', null, b.titel),
      faehigkeitenVon(b).map(stufenWahl),
      b.konfiguration.filter((f) => feldGilt(b, f.name)).map((f) => feld(b.id, f, S.felder[b.id], (v) => {
        S.felder[b.id][f.name] = v;
        if (b.id === 'kern' && f.name === 'oeffentliche_url') S.urlBeruehrt = true;
        if (b.id === 'kern' && f.name === 'port' && !S.urlBeruehrt && S.felder.kern.oeffentliche_url !== undefined) {
          S.felder.kern.oeffentliche_url = `http://localhost:${v}`;
          const el = document.getElementById('f-kern-oeffentliche_url');
          if (el) el.value = S.felder.kern.oeffentliche_url;
        }
      })));
  });
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, 'Einrichten'),
    S.planFehler.length ? h('div', { class: 'meldung fehler', role: 'alert' }, h('strong', null, 'Bitte prüfen:'), h('ul', null, S.planFehler.map((f) => h('li', null, f)))) : null,
    h('datalist', { id: 'sprachen' }, SPRACHEN.map((s) => h('option', { value: s }))),
    h('fieldset', null, h('legend', null, 'Dein Agent'),
      feld('persona', { name: 'agent_name', titel: 'Name des Agenten', beschreibung: 'So meldet sich dein Agent.', pflicht: true, typ: 'text' }, p, (v) => { p.agent_name = v; }),
      feld('persona', { name: 'wesen', titel: 'Wesen', beschreibung: 'Ein paar Worte zum Ton, zum Beispiel ruhig, direkt, humorvoll.', typ: 'text' }, p, (v) => { p.wesen = v; }),
      feld('persona', { name: 'besitzer_name', titel: 'Dein Name', beschreibung: 'Wie der Agent dich anspricht.', pflicht: true, typ: 'text' }, p, (v) => { p.besitzer_name = v; }),
      feld('persona', { name: 'sprache', titel: 'Sprache', pflicht: true, typ: 'text', liste: 'sprachen' }, p, (v) => { p.sprache = v; })),
    h('fieldset', null, h('legend', null, 'Sprachmodell'),
      h('p', { class: 'leise' }, 'Jeder OpenAI-kompatible Anbieter geht: lokal (zum Beispiel Ollama oder llama.cpp) oder gehostet.'),
      feld('modell', { name: 'basis_url', titel: 'Basis-Adresse', beschreibung: 'Zum Beispiel http://host.docker.internal:11434/v1 für Ollama auf diesem Rechner.', pflicht: true, typ: 'url' }, m, (v) => { m.basis_url = v; }),
      feld('modell', { name: 'name', titel: 'Modellname', pflicht: true, typ: 'text' }, m, (v) => { m.name = v; }),
      feld('modell', { name: 'schluessel', titel: 'Schlüssel', beschreibung: 'Leer lassen, wenn der Anbieter keinen verlangt. Wird nur in der Geheimnisdatei gespeichert.', typ: 'geheim' }, m, (v) => { m.schluessel = v; })),
    gruppen,
    h('fieldset', null, h('legend', null, 'Bezug der Pakete'),
      quelleNoetig ? [
        feld('optionen', { name: 'bezug', titel: 'Woher kommen die Plugin-Pakete?', typ: 'wahl', optionen: [['index', 'Paketindex'], ['git', 'Git-Adresse']] }, o, (v) => { o.bezug = v; zeigeInhalt(); }),
        o.bezug === 'git'
          ? feld('optionen', { name: 'plugin_quelle', titel: 'Plugin-Quelle', beschreibung: `Git-Adresse, unter der die Plugin-Repos liegen, zum Beispiel ${S.katalog.plugin_quelle_beispiel || 'https://git.example.com/fyos'}.`, pflicht: true, typ: 'url' }, o, (v) => { o.plugin_quelle = v; })
          : feld('optionen', { name: 'paketindex', titel: 'Index-URL', beschreibung: 'Python-Paketindex (PyPI-kompatibel), zum Beispiel https://git.example.com/api/packages/org/pypi/simple. Wird beim Bauen als FYOS_INDEX_URL übergeben; uv fragt ihn vor PyPI.', pflicht: true, typ: 'url' }, o, (v) => { o.paketindex = v; }),
      ] : h('p', { class: 'leise' }, 'Die gewählten Bausteine brauchen keine zusätzlichen Pakete.'),
      S.ziel === 'k8s' ? [
        feld('optionen', { name: 'hub_bild_k8s', titel: 'Hub-Bild in deiner Registry', beschreibung: 'Dorthin schiebst du das gebaute Bild.', pflicht: true, typ: 'text' }, o, (v) => { o.hub_bild_k8s = v; }),
        gewaehlteBausteine().some((b) => b.id === 'kanal_matrix' || b.id === 'kanal_whatsapp')
          ? feld('optionen', { name: 'agent_bild_k8s', titel: 'Agent-Bild mit Kanal-Paketen in deiner Registry', beschreibung: 'Matrix und WhatsApp brauchen zusätzliche Pakete im Bild des Agenten; dorthin schiebst du das gebaute Bild.', pflicht: true, typ: 'text' }, o, (v) => { o.agent_bild_k8s = v; })
          : null,
        feld('optionen', { name: 'namespace', titel: 'Namespace', pflicht: true, typ: 'text' }, o, (v) => { o.namespace = v; }),
      ] : null,
      h('details', null, h('summary', null, 'Bilder der Dienste'),
        feld('optionen', { name: 'bild_web', titel: 'Bild der Oberfläche', beschreibung: 'Vorgabe aus FYOS_REGISTRY, falls gesetzt.', pflicht: true, typ: 'text' }, o, (v) => { o.bild_web = v; }),
        feld('optionen', { name: 'hub_bild', titel: 'Basisbild des Hubs', pflicht: true, typ: 'text' }, o, (v) => { o.hub_bild = v; }),
        feld('optionen', { name: 'bild_agent', titel: 'Bild des Agenten', pflicht: true, typ: 'text' }, o, (v) => { o.bild_agent = v; }))),
  ];
}

// Reifegrad je Schicht (vom Server aus der Auswahl abgeleitet): Stufe, Satz »woran erkennbar« und die nächste Stufe.
function reifeTabelle(reife) {
  if (!Array.isArray(reife) || !reife.length) return null;
  return [
    h('h2', null, 'Reifegrad'),
    h('p', { class: 'leise' }, 'Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet. Der Satz sagt, woran du die Stufe im laufenden System erkennst.'),
    h('table', { class: 'dateien reife' },
      h('thead', null, h('tr', null, h('th', null, 'Schicht'), h('th', null, 'Stufe'), h('th', null, 'Woran erkennbar'))),
      h('tbody', null, reife.map((r) => h('tr', null,
        h('td', null, r.titel),
        h('td', null, `${r.stufe} von ${r.von}`, h('div', { class: 'leise' }, r.name)),
        h('td', null, r.erkennbar, r.naechste ? h('div', { class: 'leise' }, 'Nächste Stufe: ' + r.naechste) : null))))),
  ];
}

// Stufe je Fähigkeit (vom Server berechnet): welche Stufe gilt, ob Vorgabe oder Wahl, und bei Ausbau die Variable mit der Adresse.
function stufenTabelle(stufen) {
  if (!Array.isArray(stufen) || !stufen.length) return null;
  return [
    h('h2', null, 'Stufe je Fähigkeit'),
    h('p', { class: 'leise' }, 'Die Grundstufe braucht keinen eigenen Dienst, die Ausbaustufe einen. Die Vorgabe richtet sich nach dem Ziel; du kannst jede Fähigkeit unter »Einrichten« umstellen.'),
    h('table', { class: 'dateien stufen-tabelle' },
      h('thead', null, h('tr', null, h('th', null, 'Fähigkeit'), h('th', null, 'Stufe'), h('th', null, 'Was das heißt'))),
      h('tbody', null, stufen.map((s) => h('tr', null,
        h('td', null, s.titel),
        h('td', null, s.stufe_titel, h('div', { class: 'leise' }, s.vorgabe ? 'Vorgabe' : 'von dir gewählt')),
        h('td', null, s.was, s.umgebung ? h('div', { class: 'leise' }, [h('code', null, s.umgebung), s.adresse_gesetzt ? ' ist gesetzt' : ' ist noch leer: trage die Adresse selbst ein, den Dienst liefert der Installer noch nicht mit'] ) : null))))),
  ];
}

function seiteZusammenfassung() {
  const plan = S.plan;
  const kopf = [h('h1', { tabindex: '-1', id: 'titel' }, 'Zusammenfassung')];
  if (!plan) return [...kopf, h('p', null, 'Berechne …')];
  if (!plan.ok) {
    return [...kopf, h('div', { class: 'meldung fehler', role: 'alert' }, h('strong', null, 'Das geht so noch nicht:'),
      h('ul', null, plan.fehler.map((f) => h('li', null, f)))), h('button', { type: 'button', onclick: () => gehe(3) }, 'Zurück zum Einrichten')];
  }
  const mitBild = gewaehlteBausteine().filter((b) => b.bilder.length);
  return [
    ...kopf,
    h('p', null, 'Ziel: ', h('strong', null, ZIEL_TEXTE[S.ziel][0]), '. Bausteine: ', gewaehlteBausteine().map((b) => b.titel).join(', '), '.'),
    h('div', { class: 'feld' }, h('label', { for: 'verz' }, 'Zielordner'),
      h('input', { id: 'verz', type: 'text', value: S.verzeichnis, oninput: (e) => { S.verzeichnis = e.target.value; }, onchange: () => { planNeu(); } }),
      h('span', { class: 'hilfe' }, 'Vorhandene Dateien werden nicht gelöscht, sondern als .vorher gesichert.')),
    h('button', { type: 'button', 'aria-expanded': String(S.vorschau), onclick: () => { S.vorschau = !S.vorschau; zeigeInhalt(); } }, S.vorschau ? 'Vorschau ausblenden' : 'Vorschau: Was entsteht?'),
    S.vorschau ? h('div', { class: 'collage' }, mitBild.map((b) => h('figure', null, h('img', { src: b.bilder[0], alt: `Skizze: ${b.titel}` }), h('figcaption', null, b.titel)))) : null,
    stufenTabelle(plan.stufen),
    reifeTabelle(plan.reife),
    h('h2', null, 'Dateien'),
    h('table', { class: 'dateien' }, h('thead', null, h('tr', null, h('th', null, 'Datei'), h('th', null, 'Inhalt'))),
      h('tbody', null, plan.dateien.map((d) => h('tr', null, h('td', null, h('code', null, d.pfad), d.geheim ? ' (enthält Geheimnisse, Rechte 0600)' : ''), h('td', null, d.beschreibung))))),
    h('details', null, h('summary', null, 'Inhalte ansehen (Geheimnisse sind verdeckt)'),
      plan.dateien.map((d) => h('details', null, h('summary', null, d.pfad), h('pre', null, d.vorschau)))),
    h('h2', null, 'Befehle, die danach laufen oder von dir auszuführen sind'),
    h('pre', null, plan.befehle.join('\n')),
    plan.hinweise.length ? [h('h2', null, 'Hinweise'), h('ul', null, plan.hinweise.map((x) => h('li', null, x)))] : null,
  ];
}

function seiteInstallieren() {
  const i = S.inst;
  const text = S.ziel === 'compose' ? 'Jetzt installieren' : 'Dateien erzeugen';
  if (!i.pre) i.pre = h('pre', { class: 'protokoll', 'aria-live': 'polite', 'aria-label': 'Protokoll' });
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, 'Installieren'),
    !i.gestartet ? h('p', null, S.ziel === 'compose'
      ? 'Der Installer schreibt die Dateien, baut das Hub-Bild und startet FYOS. Das erste Bauen kann einige Minuten dauern.'
      : 'Der Installer schreibt die Dateien und die Anleitung. Gestartet wird danach von dir.') : null,
    !i.gestartet ? h('button', { type: 'button', class: 'haupt', id: 'los', onclick: installieren }, text) : null,
    i.gestartet ? h('h2', null, 'Protokoll') : null,
    i.gestartet ? i.pre : null,
    i.ende ? ergebnisBox(i.ende) : null,
  ];
}

// Die Abnahme im Einzelnen (nur beim Ziel Docker Compose): jede Probe mit ihrem Ausgang. Das Urteil steht in der Meldung.
function abnahmeBox(a) {
  if (!a || !Array.isArray(a.befunde)) return null;
  return h('div', { class: 'abnahme' + (a.bestanden ? '' : ' durchgefallen') },
    h('strong', null, a.bestanden ? 'Abnahme im Einzelnen:' : 'Abnahme nicht bestanden, im Einzelnen:'),
    h('ul', null, a.befunde.map((b) => h('li', { class: b.ok ? null : 'zeile-fehler' },
      `${b.titel}: ${b.text}.`, !b.ok && b.hilfe ? ` Prüfen: ${b.hilfe}` : ''))));
}

function ergebnisBox(e) {
  const nichtAbgenommen = e.ok && e.abnahme && !e.abnahme.bestanden;
  return h('div', { class: 'meldung ' + (!e.ok ? 'fehler' : (nichtAbgenommen ? 'warnung' : 'ok')), role: 'status' },
    h('strong', null, !e.ok ? 'Das hat nicht geklappt. ' : (nichtAbgenommen ? 'Gestartet, aber nicht abgenommen. ' : 'Fertig. ')), e.meldung,
    abnahmeBox(e.abnahme),
    h('div', { class: 'marken' },
      e.ok && e.url ? h('a', { class: 'knopf haupt', href: e.url, target: '_blank', rel: 'noopener' }, 'FYOS öffnen') : null,
      !e.ok ? h('button', { type: 'button', onclick: () => { S.inst = { laeuft: false, gestartet: false, pre: null, ende: null }; zeigeInhalt(); } }, 'Erneut versuchen') : null,
      h('button', { type: 'button', onclick: beenden }, 'Installer beenden')));
}

async function beenden() {
  await api('/api/beenden', {});
  document.getElementById('inhalt').replaceChildren(h('h1', { tabindex: '-1', id: 'titel' }, 'Installer beendet'), h('p', null, 'Du kannst dieses Fenster schließen.'));
  document.getElementById('fuss').replaceChildren();
}

async function installieren() {
  const i = S.inst;
  i.gestartet = true; i.laeuft = true; i.ende = null;
  i.pre = h('pre', { class: 'protokoll', 'aria-live': 'polite', 'aria-label': 'Protokoll' });
  zeigeInhalt();
  const r = await api('/api/installieren', nutzlast());
  if (r.status !== 202) {
    i.laeuft = false;
    i.ende = { ok: false, meldung: ((r.json && r.json.fehler) || ['Start nicht möglich.']).join(' ') };
    zeigeInhalt();
    return;
  }
  const es = new EventSource('/api/protokoll');
  es.addEventListener('zeile', (ev) => {
    const z = JSON.parse(ev.data);
    const zeile = h('div', { class: z.art === 'fehler' ? 'zeile-fehler' : null }, z.text);
    i.pre.append(zeile);
    i.pre.scrollTop = i.pre.scrollHeight;
  });
  es.addEventListener('ende', (ev) => {
    es.close();
    i.laeuft = false; i.ende = JSON.parse(ev.data);
    zeigeInhalt();
  });
  es.onerror = () => { if (i.laeuft && es.readyState === EventSource.CLOSED) { i.laeuft = false; i.ende = { ok: false, meldung: 'Die Verbindung zum Installer ist abgerissen.' }; zeigeInhalt(); } };
}

// ---------------------------------------------------------------- Rahmen, Navigation

function kopfzeile() {
  document.getElementById('schritte').replaceChildren(...SCHRITTE.map((s, i) =>
    h('li', { class: i === S.schritt ? 'aktiv' : (i < S.schritt ? 'fertig' : ''), 'aria-current': i === S.schritt ? 'step' : null }, s)));
}

function fuss() {
  const knoepfe = [];
  const laeuft = S.inst.laeuft;
  if (S.schritt > 0 && !laeuft && !(S.schritt === 5 && S.inst.gestartet && S.inst.ende && S.inst.ende.ok)) {
    knoepfe.push(h('button', { type: 'button', onclick: () => gehe(S.schritt - 1) }, 'Zurück'));
  }
  knoepfe.push(h('span', { class: 'abstand' }, S.schritt === 2 ? `${S.gewaehlt.size} Bausteine gewählt` : ''));
  if (S.schritt < 5) {
    const gesperrt = S.schritt === 4 && !(S.plan && S.plan.ok);
    knoepfe.push(h('button', { type: 'button', class: 'haupt', id: 'weiter', disabled: gesperrt, onclick: weiter },
      S.schritt === 0 ? 'Los geht’s' : (S.schritt === 4 ? 'Weiter zum Installieren' : 'Weiter')));
  }
  document.getElementById('fuss').replaceChildren(h('div', { class: 'innen' }, knoepfe));
}

const SEITEN = [seiteWillkommen, seiteZiel, seiteBausteine, seiteEinrichten, seiteZusammenfassung, seiteInstallieren];

function zeigeInhalt() {
  const scroll = window.scrollY;
  const aktiv = document.activeElement && document.activeElement.id;
  document.getElementById('inhalt').replaceChildren(...[].concat(SEITEN[S.schritt]()).flat(Infinity).filter((x) => x != null && x !== false));
  kopfzeile(); fuss();
  window.scrollTo(0, scroll);
  if (aktiv) document.getElementById(aktiv)?.focus({ preventScroll: true });
}

async function gehe(n) {
  S.schritt = n;
  if (n === 3) S.planFehler = []; // Fehler erst nach einem Weiter-Versuch zeigen
  if (n === 4) { S.plan = null; zeigeInhalt(); await planNeu(); }
  else zeigeInhalt();
  if (n !== 4) {
    window.scrollTo(0, 0);
    document.getElementById('titel')?.focus({ preventScroll: true });
  }
}

async function planNeu() {
  const r = await api('/api/plan', nutzlast());
  S.plan = r.json;
  if (S.schritt === 4) zeigeInhalt();
  return S.plan;
}

async function weiter() {
  if (S.schritt === 3) {
    S.versucht = true;
    const plan = await api('/api/plan', nutzlast());
    S.planFehler = plan.json && !plan.json.ok ? plan.json.fehler : [];
    if (S.planFehler.length) { zeigeInhalt(); window.scrollTo(0, 0); return; }
    S.plan = plan.json;
  }
  if (S.schritt < 5) await gehe(S.schritt + 1);
}

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.target.closest('input, textarea, select, button, a, summary, [role="button"]')) return;
  const w = document.getElementById('weiter') || document.getElementById('los');
  if (w && !w.disabled) { e.preventDefault(); w.click(); }
});

async function start() {
  const r = await api('/api/katalog');
  if (!r.json) {
    document.getElementById('inhalt').replaceChildren(h('p', { class: 'meldung fehler' }, 'Der Katalog ließ sich nicht laden. Starte fyos-install neu und nutze den ausgegebenen Link.'));
    return;
  }
  S.katalog = r.json;
  S.verzeichnis = r.json.verzeichnis;
  S.persona = { ...r.json.vorgaben.persona };
  S.modell = { ...r.json.vorgaben.modell };
  S.optionen = { ...r.json.vorgaben.optionen };
  S.katalog.bausteine.filter((b) => b.pflicht).forEach((b) => S.gewaehlt.add(b.id));
  S.ziel = r.json.docker.bereit ? 'compose' : 'dateien';
  zeigeInhalt();
}

start();
