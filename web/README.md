# FYOS Shell (`web/`)

Die Desktop-Shell von FYOS — For Your Own Sake: Startbildschirm, Arbeitsbildschirme aus Fenstern, Dock,
Menüleiste, Agent-Dock, Mitteilungen. Sie enthält keine eigenen Inhalte: Flächen kommen vom Hub (Apps),
von Plugins (`registriereFlaechen`) und aus der Laufzeit-Konfiguration (externe Dienste).

Technik: Astro 5 (statisch) mit SolidJS (nicht React), Tailwind 4, Kobalte. Ausgeliefert von nginx auf Port 8080.

## Wie die Shell spricht

Der Browser spricht nur mit diesem Server:

| Pfad | geht an | Zweck |
| --- | --- | --- |
| `/hub-api/apps`, `/hub-api/resource`, `/hub-api/app-call` | `${FYOS_HUB_UPSTREAM}/hub/…` | Hub-Apps listen, Oberflächen laden, Werkzeuge aufrufen |
| `/hub-api/os/*` | `${FYOS_HUB_UPSTREAM}/hub/os/…` | OS-Brücke: die Shell meldet sich (`lib/os/bruecke.ts`) und holt Mitteilungen des Agenten ab, auch vorgemerkte der Nacht |
| `/hub-api/dateien/datei` | `${FYOS_HUB_UPSTREAM}/hub/dateien/datei` | Dateien der Ablage herunterladen (GET) und hochladen (PUT, ohne Zwischenspeicher; Größe begrenzt der Hub); hochgeladen wird aus der Shell (`lib/mcp-apps/host.ts`), nicht aus der App |
| `/hub/gui/<id>`, `/hub/gui/<id>/daten` | `${FYOS_HUB_UPSTREAM}/hub/gui/…` | gebaute Ansichten als ganze Seite für einen Link (nur GET, Pfad bleibt; Begründung in `docs/HUB-VERTRAG.md`) |
| `/api/agent/*` | `${FYOS_AGENT_UPSTREAM}/…` (Präfix ab) | Agenten-Runner für die native Agent-App (Dock und Fläche `nativ:agent`): Gespräche, Live-Strom (SSE), Freigaben, Läufe. Nur mit Kopf `X-FYOS-Agent: 1`, sonst 404; nginx setzt `Authorization: Bearer ${FYOS_AGENT_TOKEN}` und streicht Cookie und Authorization des Browsers; ohne Puffer, Lesefenster 1 h |
| `/fyos.config.json` | Datei `/etc/fyos/fyos.config.json` | Laufzeit-Konfiguration |
| `/healthz` | nginx | Gesundheitsabfrage |

Die Vorlage `nginx/default.conf.template` ist eine envsubst-Vorlage (`NGINX_ENVSUBST_FILTER=FYOS_`). Umgebung:

| Variable | Vorgabe im Image | Zweck |
| --- | --- | --- |
| `FYOS_HUB_UPSTREAM` | `http://hub:8080` | Hub |
| `FYOS_AGENT_UPSTREAM` | `http://agent:18438` | der Agent (Runner), ohne Pfad |
| `FYOS_AGENT_TOKEN` | leer | Token des Runners; nginx setzt es als `Authorization: Bearer …`. Leer lehnt der Runner jede Anfrage ab (401). |

Es gibt keinen festen Resolver; die Upstreams sind Namen, die nginx beim Start auflöst.

**Runner-Zugang:** Der Browser kennt das Runner-Token nie, nginx setzt es. Damit spricht jeder, der `/api/agent/`
erreicht, mit den Rechten des Runners. Wer die Shell über das eigene Netz hinaus erreichbar macht, setzt eine Anmeldung
davor (Proxy mit Login); die Agent-App erkennt eine Umleitung zur Anmeldung und bietet „Anmelden“ an. Der Pflicht-Kopf
`X-FYOS-Agent: 1` hält fremde Seiten ab: ein Browser schickt ihn quer zur Herkunft nur nach einer Vorabfrage, die
nginx nicht beantwortet. Im Dev-Server: `FYOS_DEV_RUNNER=http://localhost:18438 FYOS_DEV_RUNNER_TOKEN=… npm run dev`.

## Aufbau

```
src/
  pages/            index (leitet nach /os/), os (die Shell), os/allein (eine Fläche allein im Tab), 404
  components/os/    Shell, Startbildschirm, Start (Suche), Dock, Menüleiste, Fenster, Raster, Menü,
                    Mitteilungen, Kontrollzentrum, Hilfe, AppRahmen, Symbol
  components/apps/  AppEingebettet (zeigt eine Hub-App im Fenster)
  lib/os/           Modell: Flächen, Anordnung, Bildschirme, Menüs, Ziehen, Öffnen (Deeplinks), Mitteilungen,
                    Symbole, register.ts (die Schnittstelle für Plugins)
  lib/mcp-apps/     Host für MCP-Apps (ui://-Oberflächen im iframe, Härtung, Zustand, Pins)
  lib/config.ts     Namen, Agent und externe Dienste aus Bauzeit und Laufzeit
  plugins/          Dateien hier werden beim Start der Shell ausgeführt (siehe unten)
  styles/           Theme und OS-Stile
tests/unit/         Vitest (jsdom)
nginx/              Vorlage und Standard-Konfiguration
Dockerfile          node:22-alpine baut, nginx:1.27-alpine liefert aus
```

## `registriereFlaechen`

`lib/os/register.ts` ist die eine Schnittstelle, über die Plugins Flächen in die Shell bringen. Der Aufruf ist
wiederholbar und darf jederzeit geschehen; die Shell zeichnet sich neu.

```ts
import { registriereFlaechen } from '~/lib/os/register';

registriereFlaechen({
  flaechen: [{ id: 'seite:notizen', titel: 'Notizen', gruppe: 'Arbeit', art: 'seite', kuerzel: 'No', pfad: '/notizen/' }],
  symbole: { 'seite:notizen': ['file-text', 200] },            // Glyphe (Lucide-Name) und Farbton 0–359
  gruppen: { reihenfolge: ['Arbeit'], plugin: { notizen: 'Arbeit' }, app: { notizen__liste: 'Arbeit' } },
  standardPlaetze: [{ name: 'Schreiben', ids: ['seite:notizen', 'app:kalender__heute'] }],
  alias: { 'seite:alt': 'seite:notizen' },
  dinge: { notiz: { name: 'Notiz', pfad: '/notizen/' } },     // optional: ziehbare Dinge (fyos://notiz/<id>)
  quelle: 'mein-plugin',                                       // optional: ersetzt frühere Einträge derselben Quelle
});
```

| Feld | Bedeutung |
| --- | --- |
| `flaechen` | Seiten (`art: 'seite'` mit `pfad`, läuft in einem Fenster), externe Dienste (`extern: <url>`, neuer Tab) und native Flächen (`art: 'nativ'` mit `laden`, eine Solid-Komponente im Fenster) |
| `symbole` | Glyphe und Farbton je Fläche; Hub-Apps bringen ihr Gesicht selbst mit |
| `gruppen` | Reihenfolge der Gruppen im Start und Zuordnung von Hub-Apps zu einer Gruppe (erst ganzer Werkzeugname, dann Plugin-Präfix vor `__`, sonst „Apps“) |
| `standardPlaetze` | Vorlagen, die der Start anbietet; fehlende Flächen werden übergangen |
| `alias` | alte Kennungen führen auf die heutige Fläche (gespeicherte Anordnungen, Lesezeichen, `?offen=`) |
| `dinge` | Typen ziehbarer Dinge: die Shell öffnet die Fläche mit dem angegebenen Pfad und sagt ihr, welches Ding gemeint ist |
| `quelle` | Eine neue Registrierung derselben Quelle ersetzt die alte |

Wohin der Aufruf gehört: Jede Datei `src/plugins/*.ts` wird beim Laden der Shell ausgeführt. Ein Plugin legt
dort eine Datei ab, die `registriereFlaechen` aufruft; die Shell selbst bleibt unverändert.

## Wie ein Plugin mit Hub-App erscheint

Ein Hub-Plugin, dessen Werkzeug eine Oberfläche (`_meta.ui.resourceUri`) hat, erscheint ohne Eintrag in der Shell:
Die Shell fragt `/hub-api/apps` ab (beim Start, alle zwei Minuten und beim Zurückkehren in den Tab). Daraus entstehen
Fläche, Dock-Eintrag und Katalogkachel.

- Titel, Untertitel, Kategorie, Symbol und Farbe nimmt die Shell vom Hub (oberste Ebene von `/hub/apps` oder
  `_meta.app` am Werkzeug: `titel`, `untertitel`, `symbol`, `ton`, `kategorie`, `icon`); fehlt etwas, leitet sie es
  aus Name und Beschreibung ab, die Farbe aus dem Namen.
- Die Gruppe im Start kommt aus `gruppen.app` / `gruppen.plugin`; ohne Eintrag steht die App in „Apps“.
- Werkzeuge mit derselben Oberfläche sind eine Fläche. Nur lesende Werkzeuge ohne Pflichtfelder lassen sich an den
  Startbildschirm heften.
- Deeplink: `/os/?offen=app:<plugin>__<werkzeug>[&eingabe=<base64url(JSON)>]` öffnet die App, die Eingabe nur für
  lesende Werkzeuge.

Seiten, die ein Plugin selbst ausliefert, laufen als `art: 'seite'` in einem Fenster (iframe, gleicher Ursprung).

## Laufzeit-Konfiguration

Der Name kommt aus der Bauzeit (`PUBLIC_FYOS_NAME`, Vorgabe „FYOS“), alles Weitere aus `/fyos.config.json`
(Beispiel: `public/fyos.config.example.json`). Fehlt die Datei, läuft die Shell mit den Vorgaben. Der Ursprung ist
immer `window.location.origin`.

```json
{
  "name": "FYOS",
  "oeffentlicheUrl": "https://os.example.org",
  "agent": { "name": "Agent" },
  "extern": [{ "slug": "git", "titel": "Git", "url": "https://git.example.org/" }]
}
```

- `name`: Name im Menü, Start und Seitentitel (überschreibt `PUBLIC_FYOS_NAME`).
- `oeffentlicheUrl`: zusätzlicher Ursprung, dessen Links im OS öffnen (hinter einem Proxy).
- `agent.name`: Anzeigename des Agenten (Dock, Fensterkopf, Raum Gespräch).
- `extern`: Dienste mit eigener Oberfläche; sie öffnen in einem neuen Tab (nur `http`/`https`).

Im Image liegt eine leere Standarddatei `{}` unter `/etc/fyos/fyos.config.json`; wer eigene Werte will, bindet eine
Datei dort ein.

## Mitteilungen und Agent-Fragen

Eine Quelle (zum Beispiel der Agent) zeigt eine Mitteilung oben rechts mit einem Fensterereignis; ein Klick öffnet
die Fläche. Gestapelt werden höchstens drei, gleiche binnen einer Minute ersetzen einander; „stumm“ und „aus“ lassen
sich zurücknehmen.

```js
window.dispatchEvent(new CustomEvent('fyos:zeigt', {
  detail: { ziel: 'app:notizen__liste', titel: 'Notizen', untertitel: 'Heute', vorschau: 'Drei neue Einträge.', eingabe: { tag: 'heute' } },
}));
```

Den Agenten fragen (aus Apps, Seiten und Objekten): `fyos:agent-fragen` mit `detail: { text, kontext, quelle }` am
Fenster, aus einer Seite im Fenster per `postMessage({ fyosAgentFragen: { … } })`. Die Shell öffnet das Agent-Dock
(native Agent-App gegen den Runner) mit der Frage samt Kontext als Entwurf im Eingabefeld; gesendet wird mit Enter.

Flächen öffnen: `fyos:oeffnen` mit `detail: { ziel, eingabe }` (`ziel` ist eine Fläche oder ein Pfad); die Shell
setzt `preventDefault()`, wenn sie übernimmt.

## Entwickeln und prüfen

```
npm install
npm run dev          # http://localhost:4321/os/
npx vitest run       # Unit-Tests (jsdom)
npx astro build      # statische Seiten nach dist/
```

Für `npm run dev` leitet der Entwicklungs-Proxy an laufende Dienste, wenn gesetzt:

```
FYOS_DEV_HUB=http://localhost:8080 FYOS_DEV_RUNNER=http://localhost:18438 FYOS_DEV_RUNNER_TOKEN=… npm run dev
```

Er verhält sich wie die Auslieferung: `/hub-api/*` wird zu `/hub/*`, `/api/agent/*` geht ohne Präfix und mit dem
Token als `Authorization: Bearer` an den Runner (nur mit `X-FYOS-Agent: 1`).

Der Typ-Check der Quellen: `npx tsc --noEmit -p .` (die Tests sind davon ausgenommen).

## Image

```
docker build -t fyos-web .
docker run -p 8080:8080 -e FYOS_HUB_UPSTREAM=http://hub:8080 -e FYOS_AGENT_UPSTREAM=http://agent:18438 -e FYOS_AGENT_TOKEN=… fyos-web
```

Gesundheit: `GET /healthz`.

## Hinweise

- Der Host-Name, mit dem sich die Shell gegenüber Hub-Apps vorstellt (`fyos-web`), ist bewusst unverändert; Apps
  prüfen ihn.
- Die Hub-Werkzeuge `shell.plaetze`, `shell.platz_speichern`, `shell.platz_entfernen`, `shell.abholen`,
  `shell.merken` und `shell.zustand` ruft die Shell nach bestem Wissen auf (Vorlagen, Anordnung melden, Befehle des
  Agenten abholen). Antwortet der Hub nicht, läuft die Shell ohne sie weiter.
