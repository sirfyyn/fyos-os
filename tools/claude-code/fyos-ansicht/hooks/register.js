// fyos-ansicht — vom Agenten gebaute Ansichten (gui.bauen / gui.zeigen über den FYOS-Hub) im Panel von Claude Code.
//
// Claude Code im Terminal ist kein MCP-Apps-Host. Der Hub liefert eine gebaute Ansicht deshalb als ganze Seite
// (GET /hub/gui/<id>; Live-Quellen laden über /hub/gui/<id>/daten nach), und terminal-browser zeichnet sie als Bild in
// sein Panel (kitty-Grafikprotokoll). Dieser Mod verbindet beides:
//
// - Ruft Claude gui.bauen oder gui.zeigen {id} (direkt oder über hub__call_tool), öffnet er die Ansicht im Panel, ohne
//   dir den Fokus zu nehmen (FYOS_ANSICHT_AUTO=0 schaltet das ab).
// - /ansicht [id] öffnet eine Ansicht von Hand (ohne id die letzte), /ansicht zu schließt das Panel.
//
// Nur in der Terminal-Oberfläche: Desktop-App, claude.ai und Handy zeigen die MCP-App selbst. Braucht den Mod
// terminal-browser; ohne ihn tut dieser Mod nichts. Schickt nichts ins Modell und liest keine Dateien.

const HUB_STANDARD = 'http://localhost:8080' // der Standardport des Hubs
const PANEL = 'browser' // das Panel von terminal-browser
const WERKZEUG = /^mcp__.+__(gui__bauen|gui__zeigen|hub__call_tool)$/

/**
 * Adresse des Hubs ohne Schrägstrich und ohne `/mcp` am Ende. `FYOS_HUB_URL` ist in FYOS die MCP-Adresse des Hubs
 * (`http://hub:8080/mcp`); hier zählt der Hub selbst, denn die Seite liegt unter `/hub/gui/<id>`. Was nicht mit
 * http:// oder https:// beginnt, fällt auf die Vorgabe zurück.
 */
export function hubAdresse(wert) {
  try {
    const u = new URL(typeof wert === 'string' ? wert.trim() : '')
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return HUB_STANDARD
    return u.origin + u.pathname.replace(/\/+$/, '').replace(/\/mcp$/, '')
  } catch {
    return HUB_STANDARD
  }
}

/**
 * Die Ansicht-Id aus einem Werkzeugergebnis, wenn es eine gebaute oder gezeigte Ansicht ist, sonst null.
 * gui.bauen: „Ansicht „…“ gebaut (g-…).“; gui.zeigen {id}: Ergebnis mit `dokument`. Nicht: die Liste aller Ansichten,
 * nur_daten, ein Fehler.
 */
export function ansichtAus(text) {
  if (typeof text !== 'string' || text === '') return null
  const gebaut = /gebaut \((g-[0-9a-f]{12})\)/.exec(text)
  if (gebaut) return gebaut[1]
  if (!/\\?"dokument\\?"\s*:/.test(text)) return null
  const id = /\\?"id\\?"\s*:\s*\\?"(g-[0-9a-f]{12})\\?"/.exec(text)
  return id ? id[1] : null
}

/** Text eines Werkzeugergebnisses, wie `next(e)` es liefert (`text` aus core, sonst das Ergebnis selbst). */
export function ergebnisText(r) {
  if (!r || r.deny || r.isError) return ''
  if (typeof r.text === 'string' && r.text) return r.text
  try {
    return JSON.stringify(r.result ?? '')
  } catch {
    return ''
  }
}

export function istAus(wert) {
  return typeof wert === 'string' && ['0', 'aus', 'nein', 'false', 'off'].includes(wert.trim().toLowerCase())
}

let letzte = null
let ohneFokus = false

const OHNE_BROWSER = 'Der Mod terminal-browser fehlt oder antwortet nicht (siehe README von fyos-ansicht, Voraussetzungen).'

async function zeigen($, id, vonHand) {
  letzte = id
  const url = `${hubAdresse($.env.get('FYOS_HUB_URL'))}/hub/gui/${id}`
  ohneFokus = !vonHand
  try {
    // Ohne terminal-browser gibt es $.browser nicht: der Aufruf wirft, und es bleibt bei der Meldung
    return await $.browser.open({ url })
  } catch (err) {
    return { ok: false, error: `${OHNE_BROWSER} ${err}` }
  } finally {
    ohneFokus = false
  }
}

/**
 * Eine Hintergrund-Sitzung (Job, nur angehängt) zeichnet das Panel, aber nicht das Bild darin: kitty bekommt die Pixel
 * per Shared Memory (`t=s`) und zeigt dort nur eine graue Fläche. Eine normale Sitzung zeigt es.
 */
export function hintergrund(jobDir) {
  return typeof jobDir === 'string' && jobDir.trim() !== ''
}

const NUR_VORDERGRUND = (id) => `Ansicht ${id}: in Hintergrund-Sitzungen bleibt das Panel leer — in einer normalen Sitzung /ansicht ${id}`

async function nachDemAufruf($, r) {
  if (istAus($.env.get('FYOS_ANSICHT_AUTO'))) return
  const id = ansichtAus(ergebnisText(r))
  if (!id || !(await imTerminal($))) return
  if (hintergrund($.env.get('CLAUDE_JOB_DIR'))) {
    letzte = id
    $.ui.toast(NUR_VORDERGRUND(id))
    return
  }
  const offen = await zeigen($, id, false)
  if (!offen.ok) $.ui.log(`fyos-ansicht: ${offen.error}`)
}

async function imTerminal($) {
  try {
    return (await $.session.surfaces()).includes('terminal')
  } catch {
    return false
  }
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    if (!(await imTerminal($))) return r
    await $.command
      .register({
        name: 'ansicht',
        description: 'Gebaute FYOS-Ansicht rechts im Panel zeigen (ohne id die letzte, „zu“ schließt)',
        argumentHint: '[g-… | zu]',
        immediate: true,
      })
      .catch((err) => $.ui.log(`fyos-ansicht: /ansicht nicht angemeldet: ${err}`))
    return r
  })

  on('command.run', { command: 'ansicht' }, async ($, e) => {
    const arg = String(e.args || '').trim()
    if (arg === 'zu') {
      const zu = await $.browser.close({}).catch(() => false)
      return { text: zu ? 'Ansicht geschlossen' : 'Kein Panel offen' }
    }
    const id = arg || letzte
    if (!id) return { text: 'Noch keine Ansicht in dieser Sitzung — /ansicht g-… (id aus gui.bauen)' }
    if (!/^g-[0-9a-f]{12}$/.test(id)) return { text: `Keine Ansicht-Id: ${id} (Form g- und 12 Hex-Zeichen)` }
    if (hintergrund($.env.get('CLAUDE_JOB_DIR'))) return { text: NUR_VORDERGRUND(id) }
    const offen = await zeigen($, id, true)
    return { text: offen.ok ? `Ansicht ${id} rechts geöffnet` : offen.error }
  })

  // Nach gui.bauen / gui.zeigen: die Ansicht im Panel öffnen. Das Ergebnis geht unverändert an Claude.
  // Nicht abgewartet: das Ergebnis geht sofort weiter, ein Fehler hier erreicht den Aufruf nie.
  on('tool.call', { tool: WERKZEUG }, async ($, e, next) => {
    const r = await next(e)
    nachDemAufruf($, r).catch(() => {})
    return r
  })

  // Von selbst geöffnet: du tippst weiter, das Panel bekommt die Tastatur nicht (ein Klick hinein gibt sie ihm)
  on('ui.open', { id: PANEL }, ($, e, next) => (ohneFokus ? next({ ...e, focus: undefined }) : next(e)))
}
