import { expect, test } from 'claude-code/testing'
import { ansichtAus, ergebnisText, hintergrund, hubAdresse, istAus } from '../hooks/register.js'

const GEBAUT = '{"satz": "Ansicht „Lage“ gebaut (g-4a0a210a33a7).", "id": "g-4a0a210a33a7", "abgelegt": true}'
const GEZEIGT = '{"satz":"Ansicht „Lage“.","id":"g-4a0a210a33a7","dokument":{"titel":"Lage","html":"<p/>"}}'
// Über hub__call_tool: das Ergebnis steckt als Text im JSON des Verteilers
const UEBER_HUB = JSON.stringify({ ok: true, result: JSON.parse(GEZEIGT) })
const LISTE = '{"satz":"2 Ansichten.","ansichten":[{"id":"g-4a0a210a33a7","titel":"Lage"}]}'
const NUR_DATEN = '{"satz":"Daten für „Lage“.","id":"g-4a0a210a33a7","daten":{}}'

test('erkennt gebaute und gezeigte Ansichten, auch über den Hub-Verteiler', () => {
  expect(ansichtAus(GEBAUT)).toBe('g-4a0a210a33a7')
  expect(ansichtAus(GEZEIGT)).toBe('g-4a0a210a33a7')
  expect(ansichtAus(UEBER_HUB)).toBe('g-4a0a210a33a7')
  expect(ansichtAus(JSON.stringify(UEBER_HUB))).toBe('g-4a0a210a33a7')
})

test('öffnet nichts für Listen, nur_daten, Fehler und fremde Ergebnisse', () => {
  expect(ansichtAus(LISTE)).toBe(null)
  expect(ansichtAus(NUR_DATEN)).toBe(null)
  expect(ansichtAus('')).toBe(null)
  expect(ansichtAus(undefined)).toBe(null)
  expect(ansichtAus('{"id": "g-zzzz", "dokument": {}}')).toBe(null)
  expect(ergebnisText({ deny: 'nein' })).toBe('')
  expect(ergebnisText({ isError: true, text: GEBAUT })).toBe('')
  expect(ergebnisText({ text: GEBAUT })).toBe(GEBAUT)
  expect(ergebnisText({ result: { content: [{ type: 'text', text: 'x' }] } })).toContain('"x"')
})

test('Hub-Adresse: Standardport des Hubs, FYOS_HUB_URL mit oder ohne /mcp', () => {
  expect(hubAdresse(undefined)).toBe('http://localhost:8080')
  expect(hubAdresse('')).toBe('http://localhost:8080')
  expect(hubAdresse('http://hub:8080/mcp')).toBe('http://hub:8080')
  expect(hubAdresse('http://hub:8080/mcp/')).toBe('http://hub:8080')
  expect(hubAdresse('http://127.0.0.1:8081')).toBe('http://127.0.0.1:8081')
  expect(hubAdresse('https://fyos.example/')).toBe('https://fyos.example')
  expect(hubAdresse('https://fyos.example/hub/mcp')).toBe('https://fyos.example/hub')
  // Ein Rechnername „mcp“ ist kein Pfad
  expect(hubAdresse('http://mcp')).toBe('http://mcp')
  expect(hubAdresse('http://mcp:8080/mcp')).toBe('http://mcp:8080')
})

test('Hub-Adresse: nur http und https, nichts anderes wird zur Seite', () => {
  expect(hubAdresse('javascript:alert(1)')).toBe('http://localhost:8080')
  expect(hubAdresse('file:///etc/hosts')).toBe('http://localhost:8080')
  expect(hubAdresse('ftp://hub.example')).toBe('http://localhost:8080')
  expect(hubAdresse('hub:8080')).toBe('http://localhost:8080')
  expect(hubAdresse(42)).toBe('http://localhost:8080')
})

test('Schalter FYOS_ANSICHT_AUTO', () => {
  expect(istAus('0')).toBe(true)
  expect(istAus('Aus')).toBe(true)
  expect(istAus(undefined)).toBe(false)
  expect(istAus('1')).toBe(false)
})

test('Hintergrund-Sitzung erkennt sich am Job-Ordner', () => {
  expect(hintergrund('/home/x/.claude/jobs/4dbf5d47')).toBe(true)
  expect(hintergrund(undefined)).toBe(false)
  expect(hintergrund('')).toBe(false)
})
