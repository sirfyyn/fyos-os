'use strict';
// Web-Assistent des FYOS-Installers. Kein Framework, keine fremden Ressourcen (läuft offline).
// Sprache: Englisch als Vorgabe, Deutsch wählbar (Auswahl oben rechts). Der Server meldet die Sprache in /api/katalog
// (`sprache`) und liefert die Katalogtexte schon übersetzt; die Texte dieser Datei laufen über t() mit dem deutschen
// Ausgangstext als Schlüssel (wie fyos_installer/sprache.py und web/src/lib/i18n).

const EN = {
  'Willkommen': 'Welcome', 'Ziel': 'Target', 'Bausteine': 'Building blocks', 'Einrichten': 'Set up',
  'Zusammenfassung': 'Summary', 'Installieren': 'Install',
  'Docker Compose auf diesem Rechner': 'Docker Compose on this computer',
  'Der Installer erzeugt die Dateien, baut das Hub-Bild und startet FYOS auf diesem Rechner.':
    'The installer generates the files, builds the Hub image and starts FYOS on this computer.',
  'Kubernetes': 'Kubernetes',
  'Der Installer erzeugt ein Kustomize-Overlay für deinen Cluster. Angewendet wird es mit kubectl, von dir.':
    'The installer generates a Kustomize overlay for your cluster. You apply it yourself with kubectl.',
  'Nur Dateien erzeugen': 'Only generate files',
  'Der Installer schreibt Dateien und eine Anleitung. Gestartet wird später von dir.':
    'The installer writes files and a guide. You start FYOS yourself later.',
  'Sprache': 'Language',
  'Kein Bild vorhanden': 'No image available',
  'Beispielbild zu {0} ({1} von {2})': 'Example image for {0} ({1} of {2})',
  'Vorheriges Bild': 'Previous image', 'Nächstes Bild': 'Next image',
  'immer dabei': 'always included', 'nimmt mit: ': 'brings along: ', 'aus ': 'from ',
  'Was daraus wird': 'What you get', 'Voraussetzungen': 'Requirements',
  'Willkommen bei FYOS': 'Welcome to FYOS',
  'FYOS ist dein persönliches Betriebssystem im Browser, aufgebaut auf einem eigenen Agenten. Du wählst, was du brauchst, und siehst vorher, was daraus wird.':
    'FYOS is your personal operating system in the browser, built around an agent of your own. You choose what you need and see beforehand what you get.',
  'Das dauert wenige Minuten. Nichts wird geschrieben oder gestartet, bevor du es ausdrücklich bestätigst. Alle Eingaben bleiben auf diesem Rechner.':
    'This takes a few minutes. Nothing is written or started before you explicitly confirm it. All input stays on this computer.',
  'Skizze eines FYOS-Desktops mit Fenstern und Dock': 'Sketch of a FYOS desktop with windows and dock',
  'Wohin soll FYOS?': 'Where should FYOS go?',
  'Das Ziel bestimmt, welche Dateien entstehen. Du kannst den Assistenten jederzeit mit einem anderen Ziel wiederholen.':
    'The target determines which files are created. You can repeat the wizard with another target at any time.',
  'Hinweis: ': 'Note: ',
  ' Du kannst trotzdem Dateien erzeugen und später selbst starten.': ' You can still generate files and start FYOS yourself later.',
  'Was soll FYOS können?': 'What should FYOS be able to do?',
  'Wähle Bausteine aus. Rechts steht, was daraus wird; die Bilder sind Skizzen und zeigen die Richtung. Abhängigkeiten werden automatisch mitgewählt.':
    'Choose building blocks. On the right you see what you get; the images are sketches and show the direction. Dependencies are selected automatically.',
  'Bitte ausfüllen.': 'Please fill in.', ' (Pflicht)': ' (required)',
  'nicht einrichten': 'do not set up',
  '{0} bleibt nicht eingerichtet; der Agent sagt das ehrlich, statt etwas zu erfinden.':
    '{0} stays not set up; the agent says so honestly instead of making something up.',
  'Stufe: {0}': 'Tier: {0}', ' (Vorgabe)': ' (default)',
  'Bitte prüfen:': 'Please check:',
  'Dein Agent': 'Your agent', 'Name des Agenten': 'Name of the agent', 'So meldet sich dein Agent.': 'How your agent introduces itself.',
  'Wesen': 'Character', 'Ein paar Worte zum Ton, zum Beispiel ruhig, direkt, humorvoll.': 'A few words about the tone, for example calm, direct, humorous.',
  'Dein Name': 'Your name', 'Wie der Agent dich anspricht.': 'How the agent addresses you.',
  'Sprachmodell': 'Language model',
  'Jeder OpenAI-kompatible Anbieter geht: lokal (zum Beispiel Ollama oder llama.cpp) oder gehostet.':
    'Any OpenAI-compatible provider works: local (for example Ollama or llama.cpp) or hosted.',
  'Basis-Adresse': 'Base address',
  'Zum Beispiel http://host.docker.internal:11434/v1 für Ollama auf diesem Rechner.':
    'For example http://host.docker.internal:11434/v1 for Ollama on this computer.',
  'Modellname': 'Model name', 'Schlüssel': 'Key',
  'Leer lassen, wenn der Anbieter keinen verlangt. Wird nur in der Geheimnisdatei gespeichert.':
    'Leave empty if the provider does not require one. It is only stored in the secrets file.',
  'Bezug der Pakete': 'Package source',
  'Woher kommen die Plugin-Pakete?': 'Where do the plugin packages come from?',
  'Paketindex': 'Package index', 'Git-Adresse': 'Git address', 'Plugin-Quelle': 'Plugin source',
  'Git-Adresse, unter der die Plugin-Repos liegen, zum Beispiel {0}.': 'Git address where the plugin repos live, for example {0}.',
  'Index-URL': 'Index URL',
  'Python-Paketindex (PyPI-kompatibel), zum Beispiel https://git.example.com/api/packages/org/pypi/simple. Wird beim Bauen als FYOS_INDEX_URL übergeben; uv fragt ihn vor PyPI.':
    'Python package index (PyPI-compatible), for example https://git.example.com/api/packages/org/pypi/simple. It is passed as FYOS_INDEX_URL when building; uv asks it before PyPI.',
  'Die gewählten Bausteine brauchen keine zusätzlichen Pakete.': 'The chosen building blocks need no additional packages.',
  'Hub-Bild in deiner Registry': 'Hub image in your registry', 'Dorthin schiebst du das gebaute Bild.': 'You push the built image there.',
  'Namespace': 'Namespace', 'Bilder der Dienste': 'Images of the services', 'Bild der Oberfläche': 'Interface image',
  'Vorgabe aus FYOS_REGISTRY, falls gesetzt.': 'Default from FYOS_REGISTRY, if set.',
  'Basisbild des Hubs': 'Base image of the Hub', 'Bild des Agenten (Runner)': 'Image of the agent (runner)',
  'Reifegrad': 'Maturity',
  'Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet. Der Satz sagt, woran du die Stufe im laufenden System erkennst.':
    'Four layers with three levels each, derived from your choice. The sentence says how you recognise the level in the running system.',
  'Schicht': 'Layer', 'Stufe': 'Level', 'Woran erkennbar': 'How to recognise it',
  '{0} von {1}': '{0} of {1}', 'Nächste Stufe: ': 'Next level: ',
  'Stufe je Fähigkeit': 'Tier per capability',
  'Die Grundstufe braucht keinen eigenen Dienst, die Ausbaustufe einen. Die Vorgabe richtet sich nach dem Ziel; du kannst jede Fähigkeit unter »Einrichten« umstellen.':
    'The basic tier needs no service of its own, the extended tier does. The default depends on the target; you can change each capability under »Set up«.',
  'Fähigkeit': 'Capability', 'Was das heißt': 'What it means', 'Vorgabe': 'default', 'von dir gewählt': 'chosen by you',
  ' ist gesetzt': ' is set',
  ' ist noch leer: trage die Adresse selbst ein, den Dienst liefert der Installer noch nicht mit':
    ' is still empty: enter the address yourself, the installer does not ship the service yet',
  'Berechne …': 'Calculating …', 'Das geht so noch nicht:': 'This does not work yet:', 'Zurück zum Einrichten': 'Back to setup',
  'Ziel: ': 'Target: ', '. Bausteine: ': '. Building blocks: ', 'Zielordner': 'Target folder',
  'Vorhandene Dateien werden nicht gelöscht, sondern als .vorher gesichert.': 'Existing files are not deleted but kept as .vorher.',
  'Vorschau ausblenden': 'Hide preview', 'Vorschau: Was entsteht?': 'Preview: what is created?', 'Skizze: {0}': 'Sketch: {0}',
  'Dateien': 'Files', 'Datei': 'File', 'Inhalt': 'Content', ' (enthält Geheimnisse, Rechte 0600)': ' (contains secrets, mode 0600)',
  'Inhalte ansehen (Geheimnisse sind verdeckt)': 'View contents (secrets are hidden)',
  'Befehle, die danach laufen oder von dir auszuführen sind': 'Commands that run afterwards or that you run yourself',
  'Hinweise': 'Notes', 'Jetzt installieren': 'Install now', 'Dateien erzeugen': 'Generate files', 'Protokoll': 'Log',
  'Der Installer schreibt die Dateien, baut das Hub-Bild und startet FYOS. Das erste Bauen kann einige Minuten dauern.':
    'The installer writes the files, builds the Hub image and starts FYOS. The first build can take a few minutes.',
  'Der Installer schreibt die Dateien und die Anleitung. Gestartet wird danach von dir.':
    'The installer writes the files and the guide. You start FYOS yourself afterwards.',
  'Abnahme im Einzelnen:': 'Acceptance check in detail:',
  'Abnahme nicht bestanden, im Einzelnen:': 'Acceptance check not passed, in detail:', ' Prüfen: ': ' Check: ',
  'Das hat nicht geklappt. ': 'That did not work. ', 'Gestartet, aber nicht abgenommen. ': 'Started, but not accepted. ',
  'Fertig. ': 'Done. ', 'FYOS öffnen': 'Open FYOS', 'Erneut versuchen': 'Try again', 'Installer beenden': 'Quit installer',
  'Installer beendet': 'Installer stopped', 'Du kannst dieses Fenster schließen.': 'You can close this window.',
  'Start nicht möglich.': 'Cannot start.', 'Die Verbindung zum Installer ist abgerissen.': 'The connection to the installer was lost.',
  'Zurück': 'Back', '{0} Bausteine gewählt': '{0} building blocks chosen', 'Los geht’s': 'Let’s go',
  'Weiter zum Installieren': 'Continue to install', 'Weiter': 'Next',
  'Der Katalog ließ sich nicht laden. Starte fyos-install neu und nutze den ausgegebenen Link.':
    'The catalog could not be loaded. Restart fyos-install and use the link it prints.',
  'FYOS einrichten': 'Set up FYOS', 'Zum Inhalt springen': 'Skip to content', 'Schritte': 'Steps',
};

let SPRACHE = 'en';
function t(text, ...werte) {
  const aus = SPRACHE === 'en' && Object.prototype.hasOwnProperty.call(EN, text) ? EN[text] : text;
  return werte.length ? aus.replace(/\{(\d+)\}/g, (m, i) => (werte[i] === undefined ? m : String(werte[i]))) : aus;
}

const SCHRITTE = ['Willkommen', 'Ziel', 'Bausteine', 'Einrichten', 'Zusammenfassung', 'Installieren'];
const ZIEL_TEXTE = {
  compose: ['Docker Compose auf diesem Rechner', 'Der Installer erzeugt die Dateien, baut das Hub-Bild und startet FYOS auf diesem Rechner.'],
  k8s: ['Kubernetes', 'Der Installer erzeugt ein Kustomize-Overlay für deinen Cluster. Angewendet wird es mit kubectl, von dir.'],
  dateien: ['Nur Dateien erzeugen', 'Der Installer schreibt Dateien und eine Anleitung. Gestartet wird später von dir.'],
};
const SPRACHEN = ['English', 'Deutsch', 'Français', 'Español', 'Italiano', 'Nederlands'];
const SPRACH_NAMEN = { en: 'English', de: 'Deutsch' };

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
    // `sprache`: Sprache der erzeugten Oberfläche (fyos.config.json) und der Anleitung, wie der Assistent
    antworten: { persona: S.persona, modell: S.modell, optionen: S.optionen, felder, stufen, sprache: SPRACHE },
  };
}

// ---------------------------------------------------------------- Bausteinkarte mit Galerie

function galerie(b) {
  if (!b.bilder.length) return h('div', { class: 'galerie' }, h('div', { class: 'platz' }, t('Kein Bild vorhanden')));
  const nr = S.galerie[b.id] || 0;
  const bild = h('img', { src: b.bilder[nr], alt: t('Beispielbild zu {0} ({1} von {2})', b.titel, nr + 1, b.bilder.length), loading: 'lazy' });
  const gehe = (d) => { S.galerie[b.id] = (nr + d + b.bilder.length) % b.bilder.length; zeigeInhalt(); };
  const steuer = b.bilder.length > 1 ? h('div', { class: 'steuer' },
    h('button', { type: 'button', 'aria-label': t('Vorheriges Bild'), onclick: () => gehe(-1) }, '‹'),
    h('span', { class: 'zahl', 'aria-live': 'polite' }, `${nr + 1} / ${b.bilder.length}`),
    h('button', { type: 'button', 'aria-label': t('Nächstes Bild'), onclick: () => gehe(1) }, '›')) : null;
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
        b.pflicht ? h('span', { class: 'marke-klein pflicht' }, t('immer dabei')) : null,
        h('span', { class: 'marke-klein' }, b.art),
        mit.length && !b.pflicht ? h('span', { class: 'marke-klein' }, t('nimmt mit: ') + mit.join(', ')) : null,
        b.herkunft !== 'installer' ? h('span', { class: 'marke-klein' }, t('aus ') + b.herkunft) : null),
      h('h4', { class: 'leise' }, t('Was daraus wird')),
      markdown(b.was_daraus_wird),
      b.voraussetzungen.length ? h('div', { class: 'voraus' }, h('strong', null, t('Voraussetzungen')),
        h('ul', null, b.voraussetzungen.map((v) => h('li', null, v)))) : null));
}

// ---------------------------------------------------------------- Schritte

function seiteWillkommen() {
  const kern = S.katalog.bausteine.find((b) => b.id === 'kern');
  const bild = kern && kern.bilder[0];
  return [
    h('div', { class: 'willkommen' },
      h('div', null,
        h('h1', { tabindex: '-1', id: 'titel' }, t('Willkommen bei FYOS')),
        h('p', { class: 'einleitung' }, t('FYOS ist dein persönliches Betriebssystem im Browser, aufgebaut auf einem eigenen Agenten. Du wählst, was du brauchst, und siehst vorher, was daraus wird.')),
        h('p', { class: 'leise' }, t('Das dauert wenige Minuten. Nichts wird geschrieben oder gestartet, bevor du es ausdrücklich bestätigst. Alle Eingaben bleiben auf diesem Rechner.'))),
      bild ? h('img', { src: bild, alt: t('Skizze eines FYOS-Desktops mit Fenstern und Dock') }) : null),
  ];
}

function seiteZiel() {
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, t('Wohin soll FYOS?')),
    h('p', { class: 'leise' }, t('Das Ziel bestimmt, welche Dateien entstehen. Du kannst den Assistenten jederzeit mit einem anderen Ziel wiederholen.')),
    h('div', { class: 'auswahl-gitter', role: 'radiogroup', 'aria-label': t('Ziel') },
      Object.entries(ZIEL_TEXTE).map(([id, [titel, text]]) => h('label', { class: 'wahl' },
        h('input', { type: 'radio', name: 'ziel', value: id, checked: S.ziel === id, onchange: () => { S.ziel = id; zeigeInhalt(); document.querySelector(`input[value="${id}"]`)?.focus(); } }),
        ' ', h('span', { class: 'titel' }, t(titel)), h('span', { class: 'kurz' }, t(text))))),
    S.ziel === 'compose' && !S.katalog.docker.bereit
      ? h('div', { class: 'meldung fehler' }, h('strong', null, t('Hinweis: ')), S.katalog.docker.meldung, t(' Du kannst trotzdem Dateien erzeugen und später selbst starten.')) : null,
    S.ziel === 'compose' && S.katalog.docker.bereit ? h('div', { class: 'meldung ok' }, S.katalog.docker.meldung) : null,
  ];
}

function seiteBausteine() {
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, t('Was soll FYOS können?')),
    h('p', { class: 'leise' }, t('Wähle Bausteine aus. Rechts steht, was daraus wird; die Bilder sind Skizzen und zeigen die Richtung. Abhängigkeiten werden automatisch mitgewählt.')),
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
    meldung.textContent = leer && (S.beruehrt.has(id) || S.versucht) ? t('Bitte ausfüllen.') : '';
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
    h('label', { for: id }, f.titel || f.name, f.pflicht ? h('span', { class: 'pflichtstern', 'aria-label': t(' (Pflicht)') }, ' *') : null),
    eingabe, f.beschreibung ? h('span', { class: 'hilfe' }, f.beschreibung) : null, meldung);
}

// Eine Auswahl je Fähigkeit: Grundstufe, Ausbaustufe, falls erlaubt aus. Nicht vorhandene Stufen sind sichtbar gesperrt.
function stufenWahl(f) {
  const aktiv = stufeVon(f);
  const optionen = f.stufen.map((s) => ({ id: s.id, name: s.name, titel: s.titel, text: s.text, frei: s.verfuegbar }));
  if (f.aus) {
    optionen.push({ id: 'aus', name: SPRACHE === 'en' ? 'off' : 'aus', titel: t('nicht einrichten'), frei: true,
      text: t('{0} bleibt nicht eingerichtet; der Agent sagt das ehrlich, statt etwas zu erfinden.', f.titel) });
  }
  const vorgabe = f.vorgabe[S.ziel];
  return h('div', { class: 'stufen', role: 'radiogroup', 'aria-label': t('Stufe: {0}', f.titel) },
    h('div', null, h('strong', null, f.titel), ' ', h('span', { class: 'leise' }, f.kurz)),
    h('div', { class: 'stufen-wahl' }, optionen.map((o) => h('label', { class: 'wahl' + (o.frei ? '' : ' gesperrt') },
      h('input', {
        type: 'radio', name: 'stufe-' + f.id, value: o.id, checked: aktiv === o.id, disabled: !o.frei,
        onchange: () => {
          S.stufen[f.id] = o.id; zeigeInhalt();
          document.querySelector(`input[name="stufe-${f.id}"][value="${o.id}"]`)?.focus();
        },
      }),
      ' ', h('span', { class: 'titel' }, `${o.name}: ${o.titel}` + (o.id === vorgabe ? t(' (Vorgabe)') : '')),
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
    h('h1', { tabindex: '-1', id: 'titel' }, t('Einrichten')),
    S.planFehler.length ? h('div', { class: 'meldung fehler', role: 'alert' }, h('strong', null, t('Bitte prüfen:')), h('ul', null, S.planFehler.map((f) => h('li', null, f)))) : null,
    h('datalist', { id: 'sprachen' }, SPRACHEN.map((s) => h('option', { value: s }))),
    h('fieldset', null, h('legend', null, t('Dein Agent')),
      feld('persona', { name: 'agent_name', titel: t('Name des Agenten'), beschreibung: t('So meldet sich dein Agent.'), pflicht: true, typ: 'text' }, p, (v) => { p.agent_name = v; }),
      feld('persona', { name: 'wesen', titel: t('Wesen'), beschreibung: t('Ein paar Worte zum Ton, zum Beispiel ruhig, direkt, humorvoll.'), typ: 'text' }, p, (v) => { p.wesen = v; }),
      feld('persona', { name: 'besitzer_name', titel: t('Dein Name'), beschreibung: t('Wie der Agent dich anspricht.'), pflicht: true, typ: 'text' }, p, (v) => { p.besitzer_name = v; }),
      feld('persona', { name: 'sprache', titel: t('Sprache'), pflicht: true, typ: 'text', liste: 'sprachen' }, p, (v) => { p.sprache = v; })),
    h('fieldset', null, h('legend', null, t('Sprachmodell')),
      h('p', { class: 'leise' }, t('Jeder OpenAI-kompatible Anbieter geht: lokal (zum Beispiel Ollama oder llama.cpp) oder gehostet.')),
      feld('modell', { name: 'basis_url', titel: t('Basis-Adresse'), beschreibung: t('Zum Beispiel http://host.docker.internal:11434/v1 für Ollama auf diesem Rechner.'), pflicht: true, typ: 'url' }, m, (v) => { m.basis_url = v; }),
      feld('modell', { name: 'name', titel: t('Modellname'), pflicht: true, typ: 'text' }, m, (v) => { m.name = v; }),
      feld('modell', { name: 'schluessel', titel: t('Schlüssel'), beschreibung: t('Leer lassen, wenn der Anbieter keinen verlangt. Wird nur in der Geheimnisdatei gespeichert.'), typ: 'geheim' }, m, (v) => { m.schluessel = v; })),
    gruppen,
    h('fieldset', null, h('legend', null, t('Bezug der Pakete')),
      quelleNoetig ? [
        feld('optionen', { name: 'bezug', titel: t('Woher kommen die Plugin-Pakete?'), typ: 'wahl', optionen: [['index', t('Paketindex')], ['git', t('Git-Adresse')]] }, o, (v) => { o.bezug = v; zeigeInhalt(); }),
        o.bezug === 'git'
          ? feld('optionen', { name: 'plugin_quelle', titel: t('Plugin-Quelle'), beschreibung: t('Git-Adresse, unter der die Plugin-Repos liegen, zum Beispiel {0}.', S.katalog.plugin_quelle_beispiel || 'https://git.example.com/fyos'), pflicht: true, typ: 'url' }, o, (v) => { o.plugin_quelle = v; })
          : feld('optionen', { name: 'paketindex', titel: t('Index-URL'), beschreibung: t('Python-Paketindex (PyPI-kompatibel), zum Beispiel https://git.example.com/api/packages/org/pypi/simple. Wird beim Bauen als FYOS_INDEX_URL übergeben; uv fragt ihn vor PyPI.'), pflicht: true, typ: 'url' }, o, (v) => { o.paketindex = v; }),
      ] : h('p', { class: 'leise' }, t('Die gewählten Bausteine brauchen keine zusätzlichen Pakete.')),
      S.ziel === 'k8s' ? [
        feld('optionen', { name: 'hub_bild_k8s', titel: t('Hub-Bild in deiner Registry'), beschreibung: t('Dorthin schiebst du das gebaute Bild.'), pflicht: true, typ: 'text' }, o, (v) => { o.hub_bild_k8s = v; }),
        feld('optionen', { name: 'namespace', titel: t('Namespace'), pflicht: true, typ: 'text' }, o, (v) => { o.namespace = v; }),
      ] : null,
      h('details', null, h('summary', null, t('Bilder der Dienste')),
        feld('optionen', { name: 'bild_web', titel: t('Bild der Oberfläche'), beschreibung: t('Vorgabe aus FYOS_REGISTRY, falls gesetzt.'), pflicht: true, typ: 'text' }, o, (v) => { o.bild_web = v; }),
        feld('optionen', { name: 'hub_bild', titel: t('Basisbild des Hubs'), pflicht: true, typ: 'text' }, o, (v) => { o.hub_bild = v; }),
        feld('optionen', { name: 'bild_agent', titel: t('Bild des Agenten (Runner)'), pflicht: true, typ: 'text' }, o, (v) => { o.bild_agent = v; }))),
  ];
}

// Reifegrad je Schicht (vom Server aus der Auswahl abgeleitet): Stufe, Satz »woran erkennbar« und die nächste Stufe.
function reifeTabelle(reife) {
  if (!Array.isArray(reife) || !reife.length) return null;
  return [
    h('h2', null, t('Reifegrad')),
    h('p', { class: 'leise' }, t('Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet. Der Satz sagt, woran du die Stufe im laufenden System erkennst.')),
    h('table', { class: 'dateien reife' },
      h('thead', null, h('tr', null, h('th', null, t('Schicht')), h('th', null, t('Stufe')), h('th', null, t('Woran erkennbar')))),
      h('tbody', null, reife.map((r) => h('tr', null,
        h('td', null, r.titel),
        h('td', null, t('{0} von {1}', r.stufe, r.von), h('div', { class: 'leise' }, r.name)),
        h('td', null, r.erkennbar, r.naechste ? h('div', { class: 'leise' }, t('Nächste Stufe: ') + r.naechste) : null))))),
  ];
}

// Stufe je Fähigkeit (vom Server berechnet): welche Stufe gilt, ob Vorgabe oder Wahl, und bei Ausbau die Variable mit der Adresse.
function stufenTabelle(stufen) {
  if (!Array.isArray(stufen) || !stufen.length) return null;
  return [
    h('h2', null, t('Stufe je Fähigkeit')),
    h('p', { class: 'leise' }, t('Die Grundstufe braucht keinen eigenen Dienst, die Ausbaustufe einen. Die Vorgabe richtet sich nach dem Ziel; du kannst jede Fähigkeit unter »Einrichten« umstellen.')),
    h('table', { class: 'dateien stufen-tabelle' },
      h('thead', null, h('tr', null, h('th', null, t('Fähigkeit')), h('th', null, t('Stufe')), h('th', null, t('Was das heißt')))),
      h('tbody', null, stufen.map((s) => h('tr', null,
        h('td', null, s.titel),
        h('td', null, s.stufe_titel, h('div', { class: 'leise' }, s.vorgabe ? t('Vorgabe') : t('von dir gewählt'))),
        h('td', null, s.was, s.umgebung ? h('div', { class: 'leise' }, [h('code', null, s.umgebung), s.adresse_gesetzt ? t(' ist gesetzt') : t(' ist noch leer: trage die Adresse selbst ein, den Dienst liefert der Installer noch nicht mit')] ) : null))))),
  ];
}

function seiteZusammenfassung() {
  const plan = S.plan;
  const kopf = [h('h1', { tabindex: '-1', id: 'titel' }, t('Zusammenfassung'))];
  if (!plan) return [...kopf, h('p', null, t('Berechne …'))];
  if (!plan.ok) {
    return [...kopf, h('div', { class: 'meldung fehler', role: 'alert' }, h('strong', null, t('Das geht so noch nicht:')),
      h('ul', null, plan.fehler.map((f) => h('li', null, f)))), h('button', { type: 'button', onclick: () => gehe(3) }, t('Zurück zum Einrichten'))];
  }
  const mitBild = gewaehlteBausteine().filter((b) => b.bilder.length);
  return [
    ...kopf,
    h('p', null, t('Ziel: '), h('strong', null, t(ZIEL_TEXTE[S.ziel][0])), t('. Bausteine: '), gewaehlteBausteine().map((b) => b.titel).join(', '), '.'),
    h('div', { class: 'feld' }, h('label', { for: 'verz' }, t('Zielordner')),
      h('input', { id: 'verz', type: 'text', value: S.verzeichnis, oninput: (e) => { S.verzeichnis = e.target.value; }, onchange: () => { planNeu(); } }),
      h('span', { class: 'hilfe' }, t('Vorhandene Dateien werden nicht gelöscht, sondern als .vorher gesichert.'))),
    h('button', { type: 'button', 'aria-expanded': String(S.vorschau), onclick: () => { S.vorschau = !S.vorschau; zeigeInhalt(); } }, S.vorschau ? t('Vorschau ausblenden') : t('Vorschau: Was entsteht?')),
    S.vorschau ? h('div', { class: 'collage' }, mitBild.map((b) => h('figure', null, h('img', { src: b.bilder[0], alt: t('Skizze: {0}', b.titel) }), h('figcaption', null, b.titel)))) : null,
    stufenTabelle(plan.stufen),
    reifeTabelle(plan.reife),
    h('h2', null, t('Dateien')),
    h('table', { class: 'dateien' }, h('thead', null, h('tr', null, h('th', null, t('Datei')), h('th', null, t('Inhalt')))),
      h('tbody', null, plan.dateien.map((d) => h('tr', null, h('td', null, h('code', null, d.pfad), d.geheim ? t(' (enthält Geheimnisse, Rechte 0600)') : ''), h('td', null, d.beschreibung))))),
    h('details', null, h('summary', null, t('Inhalte ansehen (Geheimnisse sind verdeckt)')),
      plan.dateien.map((d) => h('details', null, h('summary', null, d.pfad), h('pre', null, d.vorschau)))),
    h('h2', null, t('Befehle, die danach laufen oder von dir auszuführen sind')),
    h('pre', null, plan.befehle.join('\n')),
    plan.hinweise.length ? [h('h2', null, t('Hinweise')), h('ul', null, plan.hinweise.map((x) => h('li', null, x)))] : null,
  ];
}

function seiteInstallieren() {
  const i = S.inst;
  const text = S.ziel === 'compose' ? t('Jetzt installieren') : t('Dateien erzeugen');
  if (!i.pre) i.pre = h('pre', { class: 'protokoll', 'aria-live': 'polite', 'aria-label': t('Protokoll') });
  return [
    h('h1', { tabindex: '-1', id: 'titel' }, t('Installieren')),
    !i.gestartet ? h('p', null, S.ziel === 'compose'
      ? t('Der Installer schreibt die Dateien, baut das Hub-Bild und startet FYOS. Das erste Bauen kann einige Minuten dauern.')
      : t('Der Installer schreibt die Dateien und die Anleitung. Gestartet wird danach von dir.')) : null,
    !i.gestartet ? h('button', { type: 'button', class: 'haupt', id: 'los', onclick: installieren }, text) : null,
    i.gestartet ? h('h2', null, t('Protokoll')) : null,
    i.gestartet ? i.pre : null,
    i.ende ? ergebnisBox(i.ende) : null,
  ];
}

// Die Abnahme im Einzelnen (nur beim Ziel Docker Compose): jede Probe mit ihrem Ausgang. Das Urteil steht in der Meldung.
function abnahmeBox(a) {
  if (!a || !Array.isArray(a.befunde)) return null;
  return h('div', { class: 'abnahme' + (a.bestanden ? '' : ' durchgefallen') },
    h('strong', null, a.bestanden ? t('Abnahme im Einzelnen:') : t('Abnahme nicht bestanden, im Einzelnen:')),
    h('ul', null, a.befunde.map((b) => h('li', { class: b.ok ? null : 'zeile-fehler' },
      `${b.titel}: ${b.text}.`, !b.ok && b.hilfe ? t(' Prüfen: ') + b.hilfe : ''))));
}

function ergebnisBox(e) {
  const nichtAbgenommen = e.ok && e.abnahme && !e.abnahme.bestanden;
  return h('div', { class: 'meldung ' + (!e.ok ? 'fehler' : (nichtAbgenommen ? 'warnung' : 'ok')), role: 'status' },
    h('strong', null, !e.ok ? t('Das hat nicht geklappt. ') : (nichtAbgenommen ? t('Gestartet, aber nicht abgenommen. ') : t('Fertig. '))), e.meldung,
    abnahmeBox(e.abnahme),
    h('div', { class: 'marken' },
      e.ok && e.url ? h('a', { class: 'knopf haupt', href: e.url, target: '_blank', rel: 'noopener' }, t('FYOS öffnen')) : null,
      !e.ok ? h('button', { type: 'button', onclick: () => { S.inst = { laeuft: false, gestartet: false, pre: null, ende: null }; zeigeInhalt(); } }, t('Erneut versuchen')) : null,
      h('button', { type: 'button', onclick: beenden }, t('Installer beenden'))));
}

async function beenden() {
  await api('/api/beenden', {});
  document.getElementById('inhalt').replaceChildren(h('h1', { tabindex: '-1', id: 'titel' }, t('Installer beendet')), h('p', null, t('Du kannst dieses Fenster schließen.')));
  document.getElementById('fuss').replaceChildren();
}

async function installieren() {
  const i = S.inst;
  i.gestartet = true; i.laeuft = true; i.ende = null;
  i.pre = h('pre', { class: 'protokoll', 'aria-live': 'polite', 'aria-label': t('Protokoll') });
  zeigeInhalt();
  const r = await api('/api/installieren', nutzlast());
  if (r.status !== 202) {
    i.laeuft = false;
    i.ende = { ok: false, meldung: ((r.json && r.json.fehler) || [t('Start nicht möglich.')]).join(' ') };
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
  es.onerror = () => { if (i.laeuft && es.readyState === EventSource.CLOSED) { i.laeuft = false; i.ende = { ok: false, meldung: t('Die Verbindung zum Installer ist abgerissen.') }; zeigeInhalt(); } };
}

// ---------------------------------------------------------------- Rahmen, Navigation, Sprache

function kopfzeile() {
  document.getElementById('schritte').replaceChildren(...SCHRITTE.map((s, i) =>
    h('li', { class: i === S.schritt ? 'aktiv' : (i < S.schritt ? 'fertig' : ''), 'aria-current': i === S.schritt ? 'step' : null }, t(s))));
  const wahl = document.getElementById('sprachwahl');
  if (wahl && !S.inst.gestartet) {
    const sprachen = (S.katalog && S.katalog.sprachen) || ['en', 'de'];
    wahl.replaceChildren(h('label', { for: 'sprache-wahl' }, t('Sprache')),
      h('select', { id: 'sprache-wahl', onchange: (e) => spracheWechseln(e.target.value) },
        sprachen.map((s) => h('option', { value: s, selected: s === SPRACHE }, SPRACH_NAMEN[s] || s))));
  } else if (wahl) {
    wahl.replaceChildren();
  }
}

// Texte außerhalb des Inhalts (Titel, Sprunglink, Beschriftung der Schritte) folgen der Sprache.
function rahmenTexte() {
  if (document.documentElement) document.documentElement.lang = SPRACHE;
  if ('title' in document) document.title = t('FYOS einrichten');
  const sprung = document.getElementById('sprung');
  if (sprung) sprung.textContent = t('Zum Inhalt springen');
  const nav = document.getElementById('schritte-nav');
  if (nav) nav.setAttribute('aria-label', t('Schritte'));
}

// Sprachwahl: der Server stellt um (Katalogtexte, Meldungen, Vorgabe der erzeugten Oberfläche), dann neu laden.
async function spracheWechseln(neu) {
  if (neu === SPRACHE) return;
  const r = await api('/api/sprache', { sprache: neu });
  if (r.status !== 200 || !r.json) return;
  const alteVorgabe = S.katalog.vorgaben.persona.sprache;
  const k = await api('/api/katalog');
  if (!k.json) return;
  uebernehmeKatalog(k.json);
  // Die Sprache des Agenten folgt, solange sie nicht von Hand geändert wurde
  if (S.persona.sprache === alteVorgabe) S.persona.sprache = k.json.vorgaben.persona.sprache;
  if (S.schritt === 4) { S.plan = null; zeigeInhalt(); await planNeu(); } else zeigeInhalt();
  document.getElementById('sprache-wahl')?.focus();
}

function uebernehmeKatalog(json) {
  S.katalog = json;
  SPRACHE = json.sprache === 'de' ? 'de' : 'en';
  rahmenTexte();
}

function fuss() {
  const knoepfe = [];
  const laeuft = S.inst.laeuft;
  if (S.schritt > 0 && !laeuft && !(S.schritt === 5 && S.inst.gestartet && S.inst.ende && S.inst.ende.ok)) {
    knoepfe.push(h('button', { type: 'button', onclick: () => gehe(S.schritt - 1) }, t('Zurück')));
  }
  knoepfe.push(h('span', { class: 'abstand' }, S.schritt === 2 ? t('{0} Bausteine gewählt', S.gewaehlt.size) : ''));
  if (S.schritt < 5) {
    const gesperrt = S.schritt === 4 && !(S.plan && S.plan.ok);
    knoepfe.push(h('button', { type: 'button', class: 'haupt', id: 'weiter', disabled: gesperrt, onclick: weiter },
      S.schritt === 0 ? t('Los geht’s') : (S.schritt === 4 ? t('Weiter zum Installieren') : t('Weiter'))));
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
    document.getElementById('inhalt').replaceChildren(h('p', { class: 'meldung fehler' }, t('Der Katalog ließ sich nicht laden. Starte fyos-install neu und nutze den ausgegebenen Link.')));
    return;
  }
  uebernehmeKatalog(r.json);
  S.verzeichnis = r.json.verzeichnis;
  S.persona = { ...r.json.vorgaben.persona };
  S.modell = { ...r.json.vorgaben.modell };
  S.optionen = { ...r.json.vorgaben.optionen };
  S.katalog.bausteine.filter((b) => b.pflicht).forEach((b) => S.gewaehlt.add(b.id));
  S.ziel = r.json.docker.bereit ? 'compose' : 'dateien';
  zeigeInhalt();
}

start();
