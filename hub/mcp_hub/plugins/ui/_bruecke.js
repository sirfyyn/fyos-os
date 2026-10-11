// Gemeinsame MCP-Apps-Bruecke fuer alle ui://-Oberflaechen des Hubs.
// Pruefstand gegen das offizielle SDK: scripts/mcp-apps-pruefstand/.
// mcp_hub/plugins/_oberflaeche.py setzt sie beim Ausliefern an die Stelle der Markierung BRUECKE im Skript
// (und ui/_stil.css an die Markierung STIL im <style>, den Kopf an die Kopf-Marke, Symbole an data-symbol).
//
// Schnittstelle fuer die Apps — alles hängt an `App`:
//   Protokoll   start(name) · anfrage(methode, params, fristMs) (Frist 15 s, Werkzeugaufruf 120 s) · melden(methode, params) ·
//               auf(methode, fn) (mehrere Hörer je Methode; gibt eine Abmeldefunktion zurück)
//               werkzeug(name, args) → Roh-Ergebnis · rufen(name, args) → Daten (wirft bei Fehlern)
//   Daten       daten(ergebnis) · fehlertext(fehler)
//   Zeit/Zahl   zeit.uhr(t) · zeit.tag(t, mit_uhr) · zeit.datum(t) · zeit.dauer(min) · zahl(x, stellen)
//               zeit.vor(t) „vor 5 Min.“ · zeit.seit(t) „seit 3 Std.“ · zeit.voll(t) „Sa., 3. Okt. 2026, 14:32“
//               zeit.stempel(t, {seit}) → <time> mit relativer Anzeige, voller Zeit im title, rückt alle 30 s nach
//   Bausteine   esc(text) · symbol(name, klasse) · kachel(name, ton, groesse) · marke(text, ton, symbolname)
//               zustand({symbol, ton, titel, text, knopf: {text, aktion, symbol, klasse}}) · satz(text, ton)
//   Aktionen    knoepfe([{text, symbol, klasse, aktion, attr, busy, busyText, disabled, rechts, frei}], {klasse, label, beschaeftigt})
//               bestaetigung({frage | frageHtml, ja: {…}, nein: {…}, beschaeftigt, umgekehrt}) · knopf({…}) — ein einzelner
//   Frische     frische(t, {schwelleMin, text, klasse}) → <time class="frische"> „Stand vor 5 Min.“, ab der Schwelle (Vorgabe 15 Min.) „· veraltet“,
//               rückt von selbst nach · veraltet(t, schwelleMin) → true, wenn zu alt oder ohne Zeitpunkt.
//               t ist der Stand der DATEN (was die Quelle meldet), nicht der des Abrufs: scheitert das Neuladen, altert die Anzeige weiter.
//   Anfrage     beantragen({werkzeug, args, ort, ja, nein, symbol, klasse}) → Promise: ein Knopf löst nie direkt etwas Schreibendes aus.
//               Erst Trockenlauf (__dry_run__), der Plan erscheint in `ort`; erst nach „Ja“ läuft das Werkzeug wirklich (bestaetigt: true).
//               Ergebnis des echten Laufs, null bei „Abbrechen“ · plan(trockenlaufErgebnis) → HTML: was geschähe, die Wirkungen als Liste
//   Aufklappen  aufklapper({id, symbol, titel, anzahl, rechts, offen, inhalt}) (details/summary) · offenMerken(wurzel) → Set der offenen ids
//               aufklappen(zeile, ist) — setzt aria-expanded an einer `button.zeile`, deren Pfeil `.weiter` sich per CSS dreht
//   Ereignisse  bei(aktion, fn) — Klick auf ein Element mit data-aktion="…" (auch auf spaeter eingesetzte)
//   Host        host ("fyos" im OS, "fremd" in Chat-Clients u. a., "" bis der Host geantwortet hat) · link()
//               kann(fähigkeit) · nachricht(text) (ui/message, nur nach Klick) · modellKontext({text, daten}) (still)
//   Dateien     oeffnen(url) — Adresse im Browser öffnen (ui/open-link, wirft bei Ablehnung) · hochladen(pfad, datei, {ueberschreiben}) —
//               Datei über den Host in die Dateiablage legen (nur Plugin dateien in der FYOS-Shell; kann("fyosDateien"))
//   Übergaben   ziehbar(el, {typ, id, label, selektor}) — macht ein Ding (Typ aus plugins/_dinge.py) ziehbar, auch aus dem Fenster
//               heraus bis zu Dock, Agent, Schreibtisch und anderen Apps; mit selektor gilt es für alle passenden Elemente unter el
//               (typ, id, label: Text oder Funktion(Element); ohne Angabe data-typ, data-id, data-label) · gibt „lösen“ zurück
//               ablage(ort, {nimmt, danach, ja, bei}) — nimmt Dinge der Typen in nimmt an, die auf dieses Fenster fallen: Plan und Rückfrage
//               (beantragen) erscheinen in ort, erst „Ja“ führt das Werkzeug der Übergabe aus; danach(ergebnis, ding) · gibt „lösen“ zurück
//               kann("fyosUebergaben"): nur in der FYOS-Shell. Auf Dinge, die man dir zeigt (fyos/oeffne): auf("fyos/oeffne", ({typ, id}) => …)
//   Takt        takt(ms, fn) — fn regelmäßig, nur solange sichtbar, beim Wiederauftauchen sofort; gibt „anhalten“ zurück
//   Größe       stufe ("blick" · "kompakt" · "normal" · "weit", aus containerDimensions; Ereignis „app-stufe“) ·
//               anzahl({blick, kompakt, normal, weit}) → wie viele Einträge in dieser Stufe
const App = (() => {
  const KONFIG = /*KONFIG*/{};   // vom Hub eingesetzt: app, titel, symbol, ton, werkzeug (Hauptwerkzeug), os (Adresse)
  const SYMBOLE = /*SYMBOLE*/{}; // vom Hub eingesetzt: Glyphe → inneres SVG, nur was diese App nennt
  let n = 0; const offen = new Map(); const hoerer = {}; const aktionen = {};
  const wurzel = document.documentElement;
  let hostName = "", hostFaehig = {}, werkzeugName = "", eingabeArgs = {}, hubLink = "", fyosKnopf = null;

  // ── Protokoll ──────────────────────────────────────────────────────────────
  // Frist für eine Anfrage an den Host: Antwortet er nicht (Host hängt, Anfrage ging verloren), bliebe „Lädt …“ für immer
  // stehen. Anfragen wie der Start und „Link öffnen“ beantwortet ein Host sofort, darum 15 s; ein Werkzeugaufruf darf
  // länger dauern (Cluster, Ausführen in der Werkstatt) und hat 120 s. Eine späte Antwort wird danach verworfen.
  const FRIST_MS = 15000, FRIST_WERKZEUG_MS = 120000, FRIST_HOCHLADEN_MS = 600000;
  function senden(msg) { window.parent.postMessage(msg, "*"); }
  function anfrage(method, params, frist) {
    const id = ++n; senden({ jsonrpc: "2.0", id, method, params });
    return new Promise((ok, fail) => {
      const t = setTimeout(() => { offen.delete(id); fail(new Error(`Keine Antwort vom Host auf ${method} (nach ${Math.round((frist || FRIST_MS) / 1000)} s)`)); }, frist || FRIST_MS);
      offen.set(id, { ok: (r) => { clearTimeout(t); ok(r); }, fail: (e) => { clearTimeout(t); fail(e); } });
    });
  }
  function melden(method, params) { senden({ jsonrpc: "2.0", method, params }); }

  // Aussehen vom Host (hostContext): Thema und Gestaltungsvariablen wie applyDocumentTheme,
  // applyHostStyleVariables und applyHostFonts im offiziellen SDK. Die Variablen landen inline auf
  // <html> und schlagen damit die Vorgaben aus _stil.css; ein neuer Satz ersetzt den alten ganz.
  // Bis der Host antwortet, gilt das Farbschema, das der Rahmen dem iframe gibt (prefers-color-scheme).
  try { if (window.matchMedia("(prefers-color-scheme: light)").matches) wurzel.dataset.theme = "light"; } catch {}
  let gesetzt = [];
  // Größenstufe aus dem Rahmen des Hosts (hostContext.containerDimensions; ändert sich die Kachelgröße,
  // soll sich auch der Inhalt anpassen). Nur ein Rahmen mit fester Höhe (OS-Fenster, Kachel) macht die App kompakt —
  // bestimmt die App ihre Höhe selbst (Chat), gäbe das eine Rückkopplung. _stil.css (Abschnitt 12) setzt die Stufen um:
  //   blick    sehr klein: nur das Wichtigste, Zustandstexte und Fußzeilen weg, Aktionen als runde Knöpfe
  //   kompakt  klein: engere Abstände, kleinere Zahlen
  //   normal   wie gebaut
  //   weit     sehr breit: Inhalt auf eine lesbare Breite in der Mitte (Apps mit <body class="breit"> nutzen alles)
  // Apps fragen App.stufe oder hören auf das Ereignis „app-stufe“ (z. B. weniger Zeilen im Blick).
  function stufeAus(b, h) {
    if (h && (h < 300 || (b < 360 && h < 420))) return "blick";
    if (h && (h < 480 || b < 420)) return "kompakt";
    return b >= 1100 ? "weit" : "normal";
  }
  function rahmen(d) {
    const b = Number(d.width) || window.innerWidth;
    const h = typeof d.height === "number" ? d.height : 0;
    wurzel.dataset.rahmen = h ? "fest" : "frei";
    if (h) wurzel.style.setProperty("--rahmen-h", `${h}px`); else wurzel.style.removeProperty("--rahmen-h");
    const neu = stufeAus(b, h);
    if (wurzel.dataset.stufe === neu) return;
    wurzel.dataset.stufe = neu;
    window.dispatchEvent(new CustomEvent("app-stufe", { detail: neu }));
  }
  // Klebende Köpfe in der Shell: die App wächst mit ihrem Inhalt, gescrollt wird die Fläche des OS — ein
  // position: sticky im Dokument der App greift dann nie. Der Host meldet „fyos/sichtbar“ {oben}: so viele Pixel der
  // App sind oben verdeckt. `--blick-oben` setzt damit Leisten mit `data-klebt` an die sichtbare Kante (_stil.css
  // Abschnitt 13); Tabellenköpfe in .tabwrap (scrollen waagerecht, sticky dort wirkungslos) schiebt `kleben` nach.
  let blickOben = 0;
  function kleben() {
    if (wurzel.dataset.rahmen !== "frei") return;
    // Kante unter einer klebenden Leiste, die gerade oben anliegt: Tabellenköpfe docken darunter an, nicht dahinter.
    let kante = blickOben;
    document.querySelectorAll("[data-klebt]").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.height && r.top <= blickOben + 1 && r.bottom > kante) kante = r.bottom;
    });
    document.querySelectorAll(".tabwrap").forEach((wrap) => {
      const kopf = wrap.querySelector(":scope > table > thead");
      if (!kopf) return;
      const zellen = kopf.querySelectorAll("th");
      zellen.forEach((th) => { th.style.transform = ""; });
      const r = wrap.getBoundingClientRect();
      const weg = Math.min(Math.max(0, kante - r.top), Math.max(0, r.height - kopf.getBoundingClientRect().height));
      if (weg > 0) zellen.forEach((th) => { th.style.transform = `translateY(${Math.round(weg)}px)`; });
    });
  }
  function sichtbar(p) {
    const oben = p && typeof p.oben === "number" && isFinite(p.oben) ? Math.max(0, p.oben) : 0;
    blickOben = oben;
    wurzel.style.setProperty("--blick-oben", `${oben}px`);
    kleben();
  }
  function kontext(k) {
    if (!k || typeof k !== "object") return;
    if (k.containerDimensions && typeof k.containerDimensions === "object") rahmen(k.containerDimensions);
    if (k.theme === "light" || k.theme === "dark") wurzel.dataset.theme = k.theme;
    if (k.toolInfo && k.toolInfo.tool && typeof k.toolInfo.tool.name === "string") werkzeugName = k.toolInfo.tool.name;
    const s = k.styles;
    if (s && typeof s === "object") {
      const v = s.variables;
      if (v && typeof v === "object") {
        for (const name of gesetzt) wurzel.style.removeProperty(name);
        gesetzt = [];
        for (const [name, wert] of Object.entries(v)) {
          if (!name.startsWith("--") || wert == null || wert === "") continue;
          wurzel.style.setProperty(name, String(wert)); gesetzt.push(name);
        }
      }
      const schriften = s.css && s.css.fonts;
      if (typeof schriften === "string" && schriften && !document.getElementById("host-schriften")) {
        const el = document.createElement("style"); el.id = "host-schriften"; el.textContent = schriften;
        document.head.appendChild(el);
      }
    }
  }

  window.addEventListener("message", (e) => {
    if (e.source !== window.parent) return; // nur der Host darf uns schreiben
    const m = e.data; if (!m || m.jsonrpc !== "2.0") return;
    // Antwort auf eine Anfrage der App (hat kein `method`; die Ids des Hosts und der App zählen getrennt)
    if (m.id != null && !m.method && offen.has(m.id)) {
      const p = offen.get(m.id); offen.delete(m.id);
      m.error ? p.fail(m.error) : p.ok(m.result); return;
    }
    if (m.method === "ui/notifications/host-context-changed") kontext(m.params);
    if (m.method === "fyos/sichtbar") sichtbar(m.params);
    if (m.method === "ui/notifications/tool-input") eingabeArgs = (m.params && m.params.arguments) || {};
    if (m.method === "ui/notifications/tool-result") linkMerken(m.params);
    if (!m.method) return;
    const fns = (hoerer[m.method] || []).slice();
    if (m.id == null) { // Benachrichtigung
      for (const fn of fns) {
        try { fn(m.params || {}); } catch (err) { queueMicrotask(() => { throw err; }); } // ein Fehler stoppt die anderen Hörer nicht, bleibt aber sichtbar
      }
      return;
    }
    // Anfrage des Hosts: sie wartet auf eine Antwort. `ping` und `ui/resource-teardown` beantwortet die App mit {} —
    // vor dem Abbau dürfen Hörer Zustand sichern (höchstens eine halbe Sekunde); alles andere kennen wir nicht.
    const antwort = (result, error) => senden({ jsonrpc: "2.0", id: m.id, ...(error ? { error } : { result }) });
    if (m.method === "ping") return antwort({});
    if (m.method === "ui/resource-teardown") {
      const fertig = Promise.all(fns.map((fn) => Promise.resolve().then(() => fn(m.params || {})).catch(() => {})));
      return void Promise.race([fertig, new Promise((ok) => setTimeout(ok, 500))]).then(() => antwort({}));
    }
    antwort(null, { code: -32601, message: "nicht unterstützt: " + m.method });
  });

  // Hoehe wie im offiziellen SDK (App.setupSizeChangedNotifications) messen: mit max-content, erst
  // nach der Initialisierung, je Bild hoechstens einmal, nur bei Aenderung. Das fruehere scrollHeight wird
  // nie kleiner als der Rahmen — eine App, die einmal lang war (Auswahl, grosses Ergebnis), blieb
  // danach mit leerem Platz so hoch .
  let zuletzt = "", bereit = false, geplant = false;
  function groesse() {
    if (!bereit || geplant) return;
    geplant = true;
    requestAnimationFrame(() => {
      geplant = false;
      if (blickOben) kleben(); // neu gezeichnete Tabellen bekommen ihren Kopf wieder an die Kante
      const el = wurzel, vorher = el.style.height;
      el.style.height = "max-content";
      const height = Math.ceil(el.getBoundingClientRect().height);
      el.style.height = vorher;
      const width = Math.ceil(window.innerWidth);
      if (`${width}x${height}` === zuletzt) return;
      zuletzt = `${width}x${height}`;
      melden("ui/notifications/size-changed", { width, height });
    });
  }
  const beobachter = new ResizeObserver(groesse);
  beobachter.observe(wurzel);
  if (document.body) beobachter.observe(document.body);

  async function start(name) {
    // Feldnamen nach dem offiziellen Schema (@modelcontextprotocol/ext-apps 2.0.3): appInfo, nicht clientInfo.
    let r;
    // Antwortet der Host nicht binnen der Frist, steht sonst „Lädt …“ für immer da: die Fehleranzeige der Brücke übernimmt.
    try { r = await anfrage("ui/initialize", { protocolVersion: "2026-01-26", appCapabilities: {}, appInfo: { name, version: "0.1.0" } }); }
    catch (e) { abgestuerzt(e); throw e; }
    hostName = String((r && r.hostInfo && r.hostInfo.name) || "");
    hostFaehig = (r && r.hostCapabilities) || {};
    wurzel.dataset.host = hostName === "fyos-web" ? "fyos" : "fremd";
    kontext(r && r.hostContext);
    melden("ui/notifications/initialized", {}); bereit = true; groesse();
    fyosKnopfPruefen();
    return r;
  }

  // ── Werkzeuge und Daten ────────────────────────────────────────────────────
  const werkzeug = (name, args) => anfrage("tools/call", { name, arguments: args || {} }, FRIST_WERKZEUG_MS).then((r) => { linkMerken(r); return r; });
  function daten(r) {
    if (!r) return null;
    if (r.structuredContent) return r.structuredContent;
    const t = (r.content || []).find((c) => c.type === "text");
    if (!t) return null;
    // Die letzte Zeile „In FYOS öffnen: …“ gehört nicht zum JSON.
    try { return JSON.parse(String(t.text).replace(/\s*In FYOS öffnen: \S+\s*$/, "")); } catch { return null; }
  }
  function fehlertext(e) {
    return String((e && e.message) || e || "Fehler").replace(/^(ValueError|RuntimeError|KeyError|TypeError|Exception|Error):\s*/, "");
  }
  async function rufen(name, args) {
    let r;
    try { r = await werkzeug(name, args || {}); }
    catch (e) { throw new Error(fehlertext(e)); }
    if (r && r.isError) throw new Error(fehlertext(((r.content || [])[0] || {}).text || "Fehler"));
    return daten(r);
  }

  // ── Zeit und Zahlen: deutsch, Berliner Zeit ──────────────────────────────────
  const MS = (t) => { if (t == null || t === "") return null; const d = t instanceof Date ? t : new Date(typeof t === "number" && t < 1e11 ? t * 1000 : typeof t === "string" ? t.replace(/(\.\d{3})\d+/, "$1") : t); return isNaN(d) ? null : d; };
  const BERLIN = { timeZone: "Europe/Berlin" };
  const zeit = {
    /** „14:32“ — t: ISO-Text, Millisekunden, Sekunden (Unix) oder Date */
    uhr: (t) => { const d = MS(t); return d ? d.toLocaleTimeString("de-DE", { ...BERLIN, hour: "2-digit", minute: "2-digit" }) : "—"; },
    /** „3. Okt.“, mit mit_uhr „3. Okt., 14:32“ */
    tag: (t, mit_uhr) => { const d = MS(t); return d ? d.toLocaleString("de-DE", { ...BERLIN, day: "numeric", month: "short", ...(mit_uhr ? { hour: "2-digit", minute: "2-digit" } : {}) }) : "—"; },
    /** „03.10.2026“ */
    datum: (t) => { const d = MS(t); return d ? d.toLocaleDateString("de-DE", { ...BERLIN, day: "2-digit", month: "2-digit", year: "numeric" }) : "—"; },
    /** „gerade eben“, „vor 5 Min.“, „vor 3 Std.“, „vor 2 Tagen“ — oder „in 5 Min.“ */
    vor: (t) => {
      const d = MS(t); if (!d) return "—";
      const s = (Date.now() - d.getTime()) / 1000, a = Math.abs(s), v = s < 0 ? "in " : "vor ";
      if (a < 90) return s < 0 ? "gleich" : "gerade eben";
      if (a < 5400) return `${v}${Math.round(a / 60)} Min.`;
      if (a < 129600) return `${v}${Math.round(a / 3600)} Std.`;
      return `${v}${Math.round(a / 86400)} Tagen`;
    },
    /** Minuten als Dauer: „5 Min.“, „3 Std.“, „2 Tage“ */
    dauer: (min) => min == null ? "—" : min < 60 ? `${Math.round(min)} Min.` : min < 2880 ? `${Math.round(min / 60)} Std.` : `${Math.round(min / 1440)} Tage`,
    /** „seit eben“, „seit 5 Min.“, „seit 3 Std.“, „seit 2 Tagen“ — wie `vor`, für Zustände, die noch andauern. */
    seit: (t) => { const v = zeit.vor(t); return v === "gerade eben" ? "seit eben" : v.replace(/^vor /, "seit "); },
    /** Volle Zeit für den title: „Sa., 3. Okt. 2026, 14:32“ */
    voll: (t) => { const d = MS(t); return d ? d.toLocaleString("de-DE", { ...BERLIN, weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : ""; },
    /** HTML: relative Zeit als <time>, die volle Zeit steht im title und die Anzeige rückt von selbst nach (alle 30 s).
     *  o.seit: „seit 3 Std.“ statt „vor 3 Std.“; o.gross: erster Buchstabe groß (am Satzanfang); o.klasse: weitere Klassen.
     *  Fehlt die Zeit, steht ein Strich da. */
    stempel: (t, o = {}) => {
      const d = MS(t); if (!d) return '<span class="zeit leise">—</span>';
      return `<time class="zeit${o.klasse ? " " + esc(o.klasse) : ""}" datetime="${esc(d.toISOString())}" data-t="${d.getTime()}"${o.seit ? ' data-seit="1"' : ""}${o.gross ? ' data-gross="1"' : ""} title="${esc(zeit.voll(d))}">${esc(relativText(d.getTime(), !!o.seit, !!o.gross))}</time>`;
    },
  };
  const relativText = (t, seit, gross) => { const s = seit ? zeit.seit(t) : zeit.vor(t); return gross ? s.charAt(0).toUpperCase() + s.slice(1) : s; };

  // ── Frische: wie alt sind die Daten eines Panels? ────────────────────────────────────────────────────
  // Jedes Panel, das Daten zeigt, trägt einen Stempel mit dem Stand seiner Daten. Ab der Schwelle steht „veraltet“ dabei
  // (Text und Farbe, nie nur Farbe). Der Zeitpunkt ist der Stand der Daten, nicht der Moment des Abrufs; eine App, die bei einem
  // gescheiterten Neuladen die alten Daten stehen lässt, zeigt so ehrlich, wie alt sie sind.
  const FRISCHE_MIN = 15; // Schwelle in Minuten, wenn das Panel keine nennt
  const schwelleVon = (min) => { const z = Number(min); return z > 0 ? z : FRISCHE_MIN; };
  const alterMin = (t) => (Date.now() - t) / 60000;
  const frischeText = (t, vor, alt) => `${vor} ${zeit.vor(Math.min(t, Date.now()))}${alt ? " · veraltet" : ""}`;
  /** true, wenn die Daten von `t` älter sind als `schwelleMin` Minuten (Vorgabe 15) oder gar keinen Zeitpunkt haben. */
  function veraltet(t, schwelleMin) { const d = MS(t); return !d || alterMin(d.getTime()) >= schwelleVon(schwelleMin); }
  /** HTML: Frische-Stempel „Stand vor 5 Min.“ (volle Zeit im title), ab `schwelleMin` Minuten (Vorgabe 15) „Stand vor 3 Std. · veraltet“ in
   *  Warnfarbe. t: Zeitpunkt der Daten (ISO-Text, Millisekunden, Unix-Sekunden, Date). Ohne Zeitpunkt: „Stand unbekannt · veraltet“.
   *  o: schwelleMin · text (statt „Stand“, z. B. „Gemessen“) · klasse. Die Anzeige rückt alle 30 s nach und kippt von selbst auf „veraltet“. */
  function frische(t, o = {}) {
    const d = MS(t), vor = o.text || "Stand", klasse = o.klasse ? " " + esc(o.klasse) : "";
    if (!d) return `<span class="frische veraltet${klasse}" title="Zu diesen Daten gibt es keinen Zeitpunkt">${esc(vor)} unbekannt · veraltet</span>`;
    const schwelle = schwelleVon(o.schwelleMin), alt = alterMin(d.getTime()) >= schwelle;
    return `<time class="frische${alt ? " veraltet" : ""}${klasse}" datetime="${esc(d.toISOString())}" data-t="${d.getTime()}" data-schwelle="${schwelle}" data-vor="${esc(vor)}"`
      + ` title="${esc(vor)}: ${esc(zeit.voll(d))}">${esc(frischeText(d.getTime(), vor, alt))}</time>`;
  }

  // Relative Zeiten und Frische-Stempel nachführen: „vor 5 Min.“ bleibt nicht stehen, solange die App offen ist.
  setInterval(() => {
    if (document.visibilityState === "hidden") return;
    for (const el of document.querySelectorAll("time.zeit[data-t]")) {
      const neu = relativText(Number(el.dataset.t), !!el.dataset.seit, !!el.dataset.gross);
      if (el.textContent !== neu) el.textContent = neu;
    }
    for (const el of document.querySelectorAll("time.frische[data-t]")) {
      const t = Number(el.dataset.t), alt = alterMin(t) >= schwelleVon(el.dataset.schwelle);
      const neu = frischeText(t, el.dataset.vor || "Stand", alt);
      el.classList.toggle("veraltet", alt);
      if (el.textContent !== neu) el.textContent = neu;
    }
  }, 30000);
  /** Zahl mit deutschem Komma; fehlt der Wert, steht ein Strich da. */
  const zahl = (x, stellen = 1) => x == null || x === "" || isNaN(Number(x)) ? "—" : Number(x).toLocaleString("de-DE", { maximumFractionDigits: stellen });

  // ── Bausteine: HTML als Text, alles Eingesetzte wird maskiert ─────────────────
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  /** Symbol als <svg class="ico">. Unbekannte Namen zeigen ein Fenster-Symbol, nie nichts. */
  function symbol(name, klasse) {
    const g = SYMBOLE[name] || SYMBOLE["app-window"] || "";
    return `<svg class="ico${klasse ? " " + klasse : ""}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${g}</svg>`;
  }
  /** Getoente Kachel mit Symbol. ton: gut | warn | schlecht | akz | grau; groesse: klein | gross | riesig. */
  function kachel(name, ton, groesse) {
    return `<span class="kachel${ton ? " " + ton : ""}${groesse ? " " + groesse : ""}">${symbol(name)}</span>`;
  }
  /** Kleine Pille, auf Wunsch mit Symbol. */
  function marke(text, ton, name) {
    return `<span class="marke${ton ? " " + ton : ""}">${name ? symbol(name) : ""}${esc(text)}</span>`;
  }
  /** Leer-, Fehler- und Hinweisansicht: Kachel, Ueberschrift, ein Satz, auf Wunsch ein Knopf (Klick → App.bei(aktion)). */
  function zustand(o) {
    const k = o.knopf;
    return `<div class="zustand${o.klein ? " klein" : ""}" role="${o.ton === "schlecht" ? "alert" : "status"}">`
      + kachel(o.symbol || "circle-help", o.ton || "grau", "gross")
      + `<h3>${esc(o.titel)}</h3>` + (o.text ? `<p>${esc(o.text)}</p>` : "")
      + (k ? `<div class="knoepfe"><button type="button" class="${esc(k.klasse || "")}" data-aktion="${esc(k.aktion)}">${k.symbol ? symbol(k.symbol) : ""}${esc(k.text)}</button></div>` : "")
      + "</div>";
  }
  /** Der eine Satz im Kopf der App (was gerade der Fall ist), auf Wunsch mit Statuspunkt (ton: gut | warn | schlecht | akz). */
  function satz(text, ton) {
    const el = document.getElementById("kopf-satz"); if (!el) return;
    el.replaceChildren();
    if (ton) { const p = document.createElement("span"); p.className = "punkt " + ton; el.append(p); }
    el.append(document.createTextNode(text || ""));
  }

  // ── Aktionsblock: Knopfreihe mit Rückfrage und „beschäftigt“-Zustand ─────────────────────────────────
  /** ` name="wert"` für eine Attribut-Tabelle: Namen nur aus a–z, 0–9 und „-“ (nie `on…`), Werte maskiert; true/"" ergibt ein bloßes Attribut. */
  function attribute(a) {
    return Object.entries(a || {})
      .filter(([k, v]) => /^[a-z][a-z0-9-]*$/.test(k) && !/^on/.test(k) && v != null && v !== false)
      .map(([k, v]) => (v === true || v === "" ? ` ${k}` : ` ${k}="${esc(v)}"`)).join("");
  }
  /** Ein Knopf als HTML. o: text · symbol · klasse („haupt“, „leise“, „gefahr” …) · aktion (→ data-aktion) · attr {name: wert}
   *  · titel · aria · rechts (schiebt ihn ans Ende der Reihe) · disabled · busy (dreht das Symbol, sperrt ihn; busyText ersetzt den Text)
   *  · frei (bleibt auch bedienbar, wenn die Reihe beschäftigt ist, etwa ein Link). */
  function knopf(o, sperre) {
    const busy = !!o.busy, aus = !!(o.disabled || busy || (sperre && !o.frei));
    const klasse = [o.klasse, o.rechts && "rechts", busy && "drehen"].filter(Boolean).join(" ");
    const sym = busy ? "loader-circle" : o.symbol;
    return `<button type="button"${klasse ? ` class="${esc(klasse)}"` : ""}${o.aktion ? ` data-aktion="${esc(o.aktion)}"` : ""}`
      + `${o.titel ? ` title="${esc(o.titel)}"` : ""}${o.aria ? ` aria-label="${esc(o.aria)}"` : ""}${attribute(o.attr)}${aus ? " disabled" : ""}>`
      + `${sym ? symbol(sym) : ""}${esc(busy && o.busyText ? o.busyText : o.text)}</button>`;
  }
  /** Reihe von Knöpfen (`.knoepfe`). o: klasse (zusätzlich, für das Layout der App) · label (Name der Gruppe für Screenreader)
   *  · beschaeftigt (sperrt alle Knöpfe außer denen mit `frei`). Leere Einträge (null, false) werden übersprungen. */
  function knoepfe(liste, o = {}) {
    const klasse = ["knoepfe", o.klasse].filter(Boolean).join(" ");
    return `<div class="${esc(klasse)}"${o.label ? ` role="group" aria-label="${esc(o.label)}"` : ""}${o.beschaeftigt ? ' aria-busy="true"' : ""}>`
      + (liste || []).filter(Boolean).map((k) => knopf(k, !!o.beschaeftigt)).join("") + "</div>";
  }
  /** Rückfrage vor einer Wirkung: auf Wunsch ein Hinweis (frage als Text, frageHtml als schon maskiertes HTML), dann „Ja“ und „Abbrechen“.
   *  o: ja {text, symbol, klasse (Vorgabe „haupt“), attr, aktion, busyText, busy} · nein {text (Vorgabe „Abbrechen“), klasse, attr, aktion} oder false
   *  · beschaeftigt (ja dreht, beide gesperrt) · umgekehrt (Abbrechen zuerst) · ton (Hinweis: info, fehler, gut oder leer = Warnung) · klasse · label. */
  function bestaetigung(o) {
    const text = o.frageHtml != null ? o.frageHtml : o.frage != null ? esc(o.frage) : "";
    const hinweis = text ? `<div class="hinweis${o.ton === undefined ? " info" : o.ton ? " " + o.ton : ""}" role="status">${symbol(o.symbol || "info")}<span>${text}</span></div>` : "";
    const ja = { klasse: "haupt", symbol: "check", busy: !!o.beschaeftigt, ...o.ja };
    const nein = o.nein === false ? null : { text: "Abbrechen", klasse: "leise", ...o.nein };
    return hinweis + knoepfe(o.umgekehrt ? [nein, ja] : [ja, nein], { klasse: o.klasse, label: o.label, beschaeftigt: o.beschaeftigt });
  }

  // ── Anfrage statt Aktion ─────────────────────────────────────────────────────────────────────────────
  // Ein Knopf löst nie direkt etwas Schreibendes aus. Er stellt eine Anfrage: das Werkzeug läuft zuerst als Trockenlauf
  // (`__dry_run__`, ändert nichts), die App zeigt den Plan, und erst nach „Ja“ läuft es wirklich — mit `bestaetigt: true`, das
  // schreibende Werkzeuge für den echten Lauf verlangen (docs/ERWEITERN.md §3.6). Lesen, Aktualisieren, Filtern und Trockenläufe
  // brauchen das nicht.
  /** HTML (nur Fließtext, passt in `bestaetigung({frageHtml})`): was geschähe, danach die Wirkungen als Zeilen. Eingabe ist die Antwort
   *  eines Trockenlaufs (Form von `build_dry_run_result` im Hub: would_execute, expected_side_effects); alles wird maskiert. */
  function plan(r) {
    const p = r && typeof r === "object" ? r : {};
    const wirkungen = (Array.isArray(p.expected_side_effects) ? p.expected_side_effects : []).filter((w) => w != null && w !== "");
    return `<strong>${esc(p.would_execute || "Die Aktion ausführen")}</strong>`
      + (wirkungen.length ? `<span class="wirkungen">${wirkungen.map((w) => `<span>${esc(w)}</span>`).join("")}</span>` : "");
  }
  let antrag = null, antragNr = 0; // der eine offene Antrag { ort, werkzeug, args, o, trocken, laeuft, fertig, fehler }; Zähler für „ein neuerer war schneller“
  function antragZeichnen(a, beschaeftigt) {
    const ja = { text: a.o.ja || "Ausführen", aktion: "antrag-ja" };
    if (a.o.symbol) ja.symbol = a.o.symbol;
    if (a.o.klasse) ja.klasse = a.o.klasse;
    a.ort.innerHTML = '<div class="antrag">'
      + bestaetigung({ frageHtml: plan(a.trocken), ja, nein: { text: a.o.nein || "Abbrechen", aktion: "antrag-nein" }, beschaeftigt: !!beschaeftigt, label: "Rückfrage" })
      + "</div>";
  }
  function antragSchliessen(ergebnis) {
    const a = antrag; if (!a) return;
    antrag = null; a.ort.replaceChildren(); a.fertig(ergebnis);
  }
  aktionen["antrag-nein"] = () => { if (antrag && !antrag.laeuft) antragSchliessen(null); };
  aktionen["antrag-ja"] = async () => {
    const a = antrag; if (!a || a.laeuft) return;
    a.laeuft = true; antragZeichnen(a, true);
    let r;
    try { r = await rufen(a.werkzeug, { ...a.args, bestaetigt: true }); }
    catch (e) { if (antrag === a) { antrag = null; a.ort.replaceChildren(); } a.fehler(e); return; }
    if (antrag === a) antragSchliessen(r); else a.fertig(r);
  };
  /** Anfrage stellen (siehe oben). o: werkzeug (<plugin>__<werkzeug>) · args · ort (Element, in dem die Rückfrage erscheint) · ja (Text des
   *  Ja-Knopfs, Vorgabe „Ausführen“) · nein (Vorgabe „Abbrechen“) · symbol (des Ja-Knopfs) · klasse (des Ja-Knopfs, Vorgabe „haupt“, bei
   *  Löschen „gefahr“). Gibt ein Promise: das Ergebnis des echten Laufs, oder null bei „Abbrechen“ (auch wenn ein neuer Antrag den alten
   *  ablöst). Wirft mit lesbarem Text, wenn der Trockenlauf oder der Lauf scheitert oder das Werkzeug gar keinen Plan liefert (dann fragt
   *  die Oberfläche nicht). Es gibt nur einen offenen Antrag; sein Platz `ort` bleibt leer, sobald er erledigt ist. */
  async function beantragen(o) {
    const ort = o && o.ort, werkzeug = o && o.werkzeug;
    if (!ort || !werkzeug) throw new Error("beantragen: werkzeug und ort sind nötig");
    if (antrag && antrag.laeuft) throw new Error("Es läuft noch eine Ausführung — bitte kurz warten.");
    const nr = ++antragNr;
    antragSchliessen(null); // ein älterer Antrag verfällt, sein Promise ergibt null
    const args = { ...(o.args || {}) };
    const trocken = await rufen(werkzeug, { ...args, __dry_run__: true });
    // Ein Werkzeug ohne Trockenlauf meldet {ok: false, error: "dry_run_unsupported"} als gewöhnliches Ergebnis, kein Fehler: ohne echten Plan
    // (dry_run: true) fragt die Oberfläche nicht, denn der Mensch könnte nichts bestätigen, was er nicht gesehen hat.
    if (!trocken || trocken.dry_run !== true || trocken.ok === false) {
      const grund = trocken && typeof trocken.error === "string" ? trocken.error : "";
      throw new Error(grund && grund !== "dry_run_unsupported" ? fehlertext(grund)
        : "Dieses Werkzeug kann nicht vorab zeigen, was es tut — die Oberfläche löst es darum nicht aus.");
    }
    if (nr !== antragNr) return null; // währenddessen hat jemand einen neueren Antrag gestellt
    return new Promise((fertig, fehler) => {
      const a = antrag = { ort, werkzeug, args, o, trocken, laeuft: false, fertig, fehler };
      antragZeichnen(a, false);
    });
  }

  // ── Aufklappbares: Bereich (details/summary) und Zeile mit Pfeil ───────────────────────────────────
  /** Aufklappbarer Bereich mit Symbol, Titel, Zahl und Pfeil rechts. o: id · symbol · titel · anzahl · rechts (Text neben dem Pfeil)
   *  · offen · klasse · inhalt (HTML, schon maskiert). Mit `offenMerken` bleibt er beim Neuzeichnen, wie er war. */
  function aufklapper(o) {
    return `<details class="sektion${o.klasse ? " " + esc(o.klasse) : ""}"${o.id ? ` id="${esc(o.id)}"` : ""}${o.offen ? " open" : ""}>`
      + `<summary>${o.symbol ? symbol(o.symbol) : ""}${esc(o.titel)}${o.anzahl != null && o.anzahl !== "" && o.anzahl !== 0 ? `<span class="anzahl">${esc(o.anzahl)}</span>` : ""}`
      + `${o.rechts ? `<span class="rechts">${esc(o.rechts)}</span>` : ""}</summary>${o.inhalt || ""}</details>`;
  }
  /** Merkt, welche <details> mit einer id unter `wurzel` offen sind (Set der ids), damit sie ein Neuzeichnen überstehen. */
  function offenMerken(wurzel) {
    const set = new Set();
    wurzel.addEventListener("toggle", (e) => { const el = e.target; if (el && el.id) (el.open ? set.add(el.id) : set.delete(el.id)); }, true);
    return set;
  }
  /** Zeile (`button.zeile`) auf- oder zuklappen: setzt aria-expanded und `.an`; der Pfeil (`.weiter`, ein „chevron-right“) dreht sich per CSS. */
  function aufklappen(zeile, ist) {
    if (!zeile) return;
    zeile.setAttribute("aria-expanded", String(!!ist)); zeile.classList.toggle("an", !!ist);
  }

  document.addEventListener("click", (e) => {
    const reiter = e.target && e.target.closest && e.target.closest(".reiter button");
    if (reiter && reiter.scrollIntoView) { try { reiter.scrollIntoView({ block: "nearest", inline: "nearest" }); } catch {} } // am Handy läuft die Leiste über: den Gewählten ins Bild holen
    const el = e.target && e.target.closest && e.target.closest("[data-aktion]");
    if (!el || el.disabled) return;
    const fn = aktionen[el.dataset.aktion];
    if (fn) fn(el, e);
  });

  // ── „In FYOS öffnen“  ──────────────────────────────────────
  // Nur ausserhalb von FYOS und nur, wenn der Host Links oeffnen kann. Die Adresse kommt vom Hub
  // (`_meta["fyos/oeffnen"]` im Ergebnis, mit den Argumenten dieses Aufrufs); fehlt sie, bauen wir sie aus dem
  // Werkzeug, das der Host nennt (toolInfo), sonst aus dem Hauptwerkzeug der App, und den Argumenten der Anfrage.
  function linkMerken(ergebnis) {
    const l = ergebnis && ergebnis._meta && ergebnis._meta["fyos/oeffnen"];
    if (typeof l === "string" && l) { hubLink = l; fyosKnopfPruefen(); }
  }
  function stabil(w) {
    if (Array.isArray(w)) return w.map(stabil);
    if (w && typeof w === "object") return Object.fromEntries(Object.keys(w).sort().map((k) => [k, stabil(w[k])]));
    return w;
  }
  function b64url(text) {
    let s = ""; for (const b of new TextEncoder().encode(text)) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function link() {
    if (hubLink) return hubLink;
    const name = werkzeugName || KONFIG.werkzeug; if (!name || !KONFIG.os) return "";
    const hat = eingabeArgs && Object.keys(eingabeArgs).length;
    const json = hat ? JSON.stringify(stabil(eingabeArgs)) : "";
    // Größer als EINGABE_MAX (4000 Zeichen, wie _identitaet.EINGABE_MAX im Hub und in der Shell): ohne Eingabe,
    // denn das OS liest eine größere nicht.
    return `${KONFIG.os}?offen=app:${name}` + (json && json.length <= 4000 ? "&eingabe=" + b64url(json) : "");
  }
  function fyosKnopfPruefen() {
    const ort = document.getElementById("aktionen");
    if (!ort || wurzel.dataset.host !== "fremd" || !hostFaehig.openLinks) return;
    if (!fyosKnopf) {
      fyosKnopf = document.createElement("button");
      fyosKnopf.type = "button"; fyosKnopf.className = "zweit klein knopf-sym"; fyosKnopf.id = "fyos-oeffnen";
      fyosKnopf.title = "In FYOS öffnen"; fyosKnopf.setAttribute("aria-label", "In FYOS öffnen");
      fyosKnopf.innerHTML = symbol("square-arrow-out-up-right") + '<span class="beschriftung">In FYOS öffnen</span>';
      fyosKnopf.addEventListener("click", () => { const url = link(); if (url) anfrage("ui/open-link", { url }).catch(() => {}); });
      ort.append(fyosKnopf);
    }
    fyosKnopf.hidden = !link();
  }

  // ── Absturz sichtbar machen ────────────────────────────────────────────────
  // Wirft das Skript einer App, bleibt sonst der Ladezustand fuer immer stehen — das liest sich wie „es dauert“.
  function abgestuerzt(e) {
    const orte = document.querySelectorAll(".laedt");
    if (!orte.length) return;
    const html = zustand({ symbol: "circle-alert", ton: "schlecht", klein: true, titel: "Die Ansicht lässt sich nicht aufbauen", text: fehlertext(e && (e.error || e.reason || e.message) || e) });
    for (const el of orte) el.outerHTML = html;
  }
  window.addEventListener("error", abgestuerzt);
  window.addEventListener("unhandledrejection", abgestuerzt);

  // ── Gespräch und Takt ──────────────────────────────────────────────────
  /** Kann der Host das? Name wie in hostCapabilities des SDK: message · updateModelContext · openLinks · serverTools. */
  const kann = (name) => !!(hostFaehig && hostFaehig[name]);
  /** Text ins Gespräch schreiben (ui/message, als Benutzer). Nur nach einem Klick: Hosts verlangen eine Nutzergeste. Wirft, wenn
   *  der Host es nicht kann oder ablehnt — die App zeigt den Knopf deshalb nur mit `kann("message")`. */
  async function nachricht(text) {
    if (!kann("message")) throw new Error("Dieser Host nimmt keine Nachrichten der App an.");
    const r = await anfrage("ui/message", { role: "user", content: [{ type: "text", text: String(text || "").slice(0, 4000) }] });
    if (r && r.isError) throw new Error("Der Host hat die Nachricht nicht angenommen.");
    return r;
  }
  /** Stillen Kontext für das Modell hinterlegen (ui/update-model-context): ersetzt den vorigen, löst keine Antwort aus.
   *  o: {text, daten}. Ohne die Fähigkeit oder bei Fehler passiert nichts — Kontext ist Zugabe, nie Bedingung. */
  function modellKontext(o) {
    if (!kann("updateModelContext") || !o) return;
    const p = {};
    if (o.text) p.content = [{ type: "text", text: String(o.text).slice(0, 4000) }];
    if (o.daten && typeof o.daten === "object") p.structuredContent = o.daten;
    anfrage("ui/update-model-context", p).catch(() => {});
  }
  /** Adresse im Browser öffnen (ui/open-link): wirft, wenn der Host sie ablehnt. Wie ein Klick auf einen Link: nur nach einer Geste. */
  async function oeffnen(url) {
    const r = await anfrage("ui/open-link", { url: String(url || "") });
    if (r && r.isError) throw new Error("Der Host hat die Adresse nicht geöffnet.");
  }
  /** Datei in die Dateiablage legen — nur in der App „Dateien“ in der FYOS-Shell: die App selbst darf nicht zum Hub (Sandbox ohne Ursprung),
   *  darum nimmt der Host die Datei entgegen und schickt sie. datei: File oder Blob; o.ueberschreiben ersetzt eine vorhandene.
   *  Antwort `{ok: true, result}` oder `{ok: false, kind, error}` (kind: existiert · zu_gross · …); wirft nur, wenn der Host ausfällt. */
  async function hochladen(pfad, datei, o = {}) {
    if (!kann("fyosDateien")) throw new Error("Hochladen geht hier nicht — nur in der FYOS-Shell.");
    return anfrage("fyos/datei-hochladen", { pfad: String(pfad || ""), datei, ueberschreiben: !!o.ueberschreiben }, FRIST_HOCHLADEN_MS);
  }
  // ── Übergaben: Dinge ziehen und annehmen ──────────────────────────────────────────────────────────
  // Die Ziehsprache der Shell (web/src/lib/os/ziehen.ts): ein Ding ist `fyos://<typ>/<id>` im Zug, dazu der Schlüssel
  // `application/x-fyos-<typ>` (damit ein Ziel schon beim Darüberfahren weiß, was kommt) und der Name zum Anzeigen. Zieht die
  // App heraus, sagt sie es dem Host (`fyos/zug`): die Fenster darunter geben ihre Zeiger frei und die Ziele zeigen ihren Hinweis.
  // Fällt ein Ding auf das Fenster dieser App, schickt der Host `fyos/uebergabe` mit dem fertigen Zielwerkzeug und seinen
  // Argumenten (Felder des Dings schon eingesetzt) — `ablage` stellt daraus eine Anfrage, nichts läuft ohne Plan und „Ja“.
  const TYP_MUSTER = /^[a-z][a-z0-9-]{0,31}$/;
  function auf(method, fn) { (hoerer[method] || (hoerer[method] = [])).push(fn); return () => { hoerer[method] = hoerer[method].filter((f) => f !== fn); }; }
  function ziehbar(wurzel, o = {}) {
    if (!wurzel || !wurzel.addEventListener) throw new Error("ziehbar: ein Element wird gebraucht");
    const wert = (v, el, vorgabe) => String((typeof v === "function" ? v(el) : v) ?? vorgabe ?? "");
    const wo = (ziel) => {
      const el = ziel && ziel.closest ? (o.selektor ? ziel.closest(o.selektor) : wurzel) : null;
      return el && wurzel.contains(el) ? el : null;
    };
    const ding = (el) => {
      const typ = wert(o.typ, el, el.dataset.typ), id = wert(o.id, el, el.dataset.id);
      if (!TYP_MUSTER.test(typ) || !id || id.includes("\n")) return null;
      return { typ, id, label: wert(o.label, el, el.dataset.label) || id };
    };
    // Ein Element zieht nur, wenn es beim Anfassen schon `draggable` ist: bei Delegation setzen wir das, sobald der Zeiger darüber fährt.
    const anfassen = (e) => { const el = wo(e.target); if (el && ding(el) && !el.draggable) el.draggable = true; };
    const start = (e) => {
      const el = wo(e.target), d = el && ding(el), dt = e.dataTransfer;
      if (!d || !dt) return;
      const uri = `fyos://${d.typ}/${d.id}`;
      dt.setData("text/plain", uri); dt.setData("text/uri-list", uri);
      dt.setData("application/x-fyos-" + d.typ, d.id); dt.setData("text/x-fyos-label", d.label);
      dt.effectAllowed = "copyMove";
      if (kann("fyosUebergaben")) melden("fyos/zug", { typ: d.typ, id: d.id, label: d.label });
    };
    const ende = () => { if (kann("fyosUebergaben")) melden("fyos/zug", { typ: null }); };
    wurzel.addEventListener("mouseover", anfassen); wurzel.addEventListener("focusin", anfassen);
    wurzel.addEventListener("dragstart", start); wurzel.addEventListener("dragend", ende);
    if (!o.selektor) anfassen({ target: wurzel });
    return () => {
      wurzel.removeEventListener("mouseover", anfassen); wurzel.removeEventListener("focusin", anfassen);
      wurzel.removeEventListener("dragstart", start); wurzel.removeEventListener("dragend", ende);
    };
  }
  function ablage(ort, o = {}) {
    if (!ort || !ort.replaceChildren) throw new Error("ablage: ein Element für die Rückfrage wird gebraucht");
    const nimmt = Array.isArray(o.nimmt) ? o.nimmt : [];
    return auf("fyos/uebergabe", async (u) => {
      if (!u || typeof u.typ !== "string" || (nimmt.length && !nimmt.includes(u.typ))) return;
      if (o.bei) return o.bei(u);
      if (typeof u.werkzeug !== "string" || !u.werkzeug) return;
      try {
        const r = beantragen({ werkzeug: u.werkzeug, args: u.argumente || {}, ort, ja: o.ja || "Übernehmen", symbol: "check" });
        setTimeout(() => { try { ort.scrollIntoView({ block: "nearest" }); } catch {} }, 80);
        const ergebnis = await r;
        if (ergebnis != null && o.danach) await o.danach(ergebnis, u);
      } catch (e) { if (o.fehler) o.fehler(e, u); else satz(fehlertext(e), "schlecht"); }
    });
  }
  /** fn alle `ms` aufrufen, aber nur, solange die App zu sehen ist; wird sie wieder sichtbar und ist der letzte Lauf älter
   *  als `ms`, sofort. Ein Lauf zur Zeit (fn darf ein Promise liefern). Gibt eine Funktion zum Anhalten zurück. */
  function takt(ms, fn) {
    let zuletzt = Date.now(), laeuft = false, aus = false;
    const lauf = async () => {
      if (aus || laeuft || document.visibilityState === "hidden") return;
      laeuft = true; zuletzt = Date.now();
      try { await fn(); } catch {} finally { laeuft = false; }
    };
    const t = setInterval(() => { if (Date.now() - zuletzt >= ms - 50) lauf(); }, Math.min(ms, 15000));
    const sicht = () => { if (document.visibilityState === "visible" && Date.now() - zuletzt >= ms) lauf(); };
    document.addEventListener("visibilitychange", sicht);
    return () => { aus = true; clearInterval(t); document.removeEventListener("visibilitychange", sicht); };
  }

  return {
    kann, nachricht, modellKontext, takt, oeffnen, hochladen, ziehbar, ablage,
    start, anfrage, melden, werkzeug, rufen, daten, fehlertext,
    // mehrere Hörer je Methode (alle werden gerufen); gibt eine Funktion zurück, die den Hörer wieder abmeldet
    auf,
    bei: (aktion, fn) => { aktionen[aktion] = fn; },
    esc, symbol, kachel, marke, zustand, satz, link, zeit, zahl,
    knopf: (o) => knopf(o, false), knoepfe, bestaetigung, aufklapper, offenMerken, aufklappen,
    frische, veraltet, plan, beantragen,
    get host() { return wurzel.dataset.host || ""; },
    /** Größenstufe des Rahmens: "blick" · "kompakt" · "normal" · "weit" (Ereignis „app-stufe“ bei Wechsel) */
    get stufe() { return wurzel.dataset.stufe || "normal"; },
    /** Wie viele Einträge passen? je Stufe ein Wert, z. B. App.anzahl({blick: 2, kompakt: 4, normal: 8, weit: 12}) */
    anzahl: (je) => { const s = wurzel.dataset.stufe || "normal"; return (je && je[s]) ?? (je && je.normal) ?? Infinity; },
  };
})();
