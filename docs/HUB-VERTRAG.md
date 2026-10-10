# Hub-Vertrag

Was der Hub (`hub/`, Paket `mcp_hub`) nach außen zusagt: HTTP-Wege, Formate, Plugin-Schnittstelle. Die Shell
(`web/`) und eigene Plugin-Pakete bauen darauf. Der Hub lauscht auf **Port 8080**.

## 1. Wege im Überblick

| Weg | Methode | Zweck |
|---|---|---|
| `/mcp` | MCP (Streamable HTTP) | Agenten, Chat-Clients; Pfad aus `path` der Konfiguration |
| `/health` | GET | Lebenszeichen für Container-Prüfung |
| `/metrics` | GET | Kennzahlen als Prometheus-Text (Kern, `metrics()` und `zeitplan()` der Plugins, bei Takten mit Grenzen auch `fyos_zeitplan_laeufe_heute`, `fyos_zeitplan_max_pro_tag` und `fyos_zeitplan_uebersprungen_total{takt, grund}`); innen offen, von außen 404 |
| `/hub/search?query=&limit=&voll=` | GET | Werkzeuge suchen (wie `hub__search_tools`) |
| `/hub/map` | GET | Werkzeugkarte: Bereiche, Werkzeuge, Scope, Kurztext |
| `/hub/health` | GET | Zustand je Plugin |
| `/hub/servers` | GET | geladene Plugins mit Werkzeugzahl |
| `/hub/call` | POST | beliebiges Werkzeug rufen (nur innen, nie nach außen) |
| `/hub/mehr` | POST | gekürztes Ergebnis vertiefen (`ergebnis_id`, `pfad`, `felder`, `filter`, `suche`, `limit`, `cursor`) |
| `/hub/apps` | GET | Flächen-Werkzeuge für die Shell (mit ETag) |
| `/hub/resource?uri=ui://…` | GET | Oberfläche eines Plugins (mit ETag) |
| `/hub/app-call` | POST | Flächen-Werkzeug rufen (der Weg des Browsers) |
| `/hub/gui/<id>` | GET | eine gebaute Ansicht (Plugin `gui`) als ganze, eigenständige Seite für Flächen ohne MCP-Apps-Host; nur lesend, auch über die Shell; ungültige oder unbekannte Id: 404 |
| `/hub/gui/<id>/daten` | GET | frische Daten der Live-Quelle dieser Ansicht (JSON wie bei `/hub/call`); nur lesend, auch über die Shell |
| `/hub/os/strom?sitzung=&geraet=&nach=` | GET | OS-Brücke: Befehle als Server-Sent Events |
| `/hub/os/melden` | POST | OS-Brücke: Zustand der Sitzung melden |
| `/hub/os/antwort` | POST | OS-Brücke: Antwort auf einen Befehl |
| `/hub/<eigener Weg>` | je Plugin | Wege aus Plugins (`routen()`, Abschnitt 4), nach denen des Kerns; etwa `/hub/openclaw/ereignisse` und `/hub/vorgaenge/tickets…` (KOPPLUNG-OPENCLAW.md) |

### nginx der Shell

Der Browser spricht nur mit der Shell. Sie reicht genau diese Wege durch; unter `/hub-api` entfernt sie das Präfix,
die gebauten Ansichten behalten ihren Pfad:

```
/hub-api/apps          -> http://hub:8080/hub/apps
/hub-api/resource      -> http://hub:8080/hub/resource
/hub-api/app-call      -> http://hub:8080/hub/app-call
/hub-api/os/strom      -> http://hub:8080/hub/os/strom     (proxy_buffering off, proxy_read_timeout >= 700s, HTTP/1.1)
/hub-api/os/melden     -> http://hub:8080/hub/os/melden
/hub-api/os/antwort    -> http://hub:8080/hub/os/antwort
/hub/gui/<id>          -> http://hub:8080/hub/gui/<id>         (nur GET; Id g- plus 12 Hex-Zeichen)
/hub/gui/<id>/daten    -> http://hub:8080/hub/gui/<id>/daten
```

`/hub/call`, `/hub/mehr`, `/hub/search`, `/hub/map`, `/hub/health`, `/hub/servers`, `/metrics` und `/mcp` gehören
**nicht** in den Browser-Weg: hinter `/hub/call` liegen alle Werkzeuge. Die Antwort von `/hub/os/strom` setzt
`X-Accel-Buffering: no` und `Cache-Control: no-cache, no-transform`; der Proxy darf nichts puffern.

Die gebauten Ansichten gehen seit 0.1.1 durch die Shell, damit ein Ansichts-Link im Browser oder im Panel einer
Entwicklungsumgebung (Mod `fyos-ansicht`) hinter derselben Anmeldung aufgeht wie die Shell. Der Pfad bleibt, denn die
Seite lädt ihre Daten unter `/hub/gui/<id>/daten` nach. Die Shell schreibt jede passende Anfrage auf genau eine der zwei
Formen um (ohne Abfrageteil), bevor sie sie weiterreicht; andere Wege unter `/hub/` erreicht über sie nichts, auch nicht
mit `..` oder Prozent-Kodierung im Pfad. Einen neuen Zugang öffnet das nicht: Dieselben Daten liefert `gui.zeigen`
schon über `/hub-api/app-call`. Das erzeugte Skript läuft in einem iframe mit `sandbox="allow-scripts"` (ohne
same-origin) und eigener CSP und erreicht weder die Shell noch das Netz.

## 2. Aufruf und Antwort

`POST /hub/call {"tool": "<plugin>.<werkzeug>", "arguments": {…}, "ansicht": "kurz"}` und
`POST /hub/app-call {"tool": "<plugin>.<werkzeug>" | "name": "<plugin>__<werkzeug>", "arguments": {…}}`.

Antwort (JSON): `{"ok": true, "result": …}` oder `{"ok": false, "error": "…", "kind": "…"}`. Ein App-Werkzeug mit
Oberfläche trägt im Ergebnis zusätzlich den Link „In FYOS öffnen“.

`/hub/app-call` akzeptiert nur Werkzeuge mit `meta.ui` oder dem Tag `flaeche`; jedes andere antwortet 403
`not_an_app`. Ein Werkzeug mit `meta.ui.visibility == ["app"]` ist nur für Oberflächen: `/hub/call` und `/mcp`
lehnen es mit 403 `nur_oberflaeche` ab.

### Statuscodes

| `kind` | HTTP |
|---|---|
| (ok) | 200 |
| `bad_arguments`, `bad_request` | 400 |
| `forbidden`, `verboten`, `nur_oberflaeche`, `not_an_app` | 403 |
| `not_found` | 404 |
| `circuit_open` | 503 |
| `timeout` | 504 |
| alles andere (Plugin hat geworfen, Werkzeug meldet `ok=false`) | 502 |

Dazu: 400 bei kaputtem JSON oder wenn der Körper kein Objekt ist, 413 bei zu großer Meldung, 415 bei
falschem Inhaltstyp, 503 `not_initialized` solange der Hub startet.

### Herkunft und Inhaltstyp

- Schreibende Methoden unter `/hub/` antworten 403, wenn `Sec-Fetch-Site: cross-site` gesetzt ist oder ein
  `Origin` da ist, dessen Host nicht erlaubt ist. Anfragen ohne `Origin` (Skripte, Agenten) bleiben erlaubt.
- Erlaubte Hosts: `FYOS_ERLAUBTE_HOSTS` (Komma), der Host von `FYOS_OEFFENTLICH_URL`, immer `localhost` und
  `127.0.0.1`. Der Port zählt nicht. Der `Host`-Kopf zählt nicht.
- `/hub/call`, `/hub/mehr`, `/hub/app-call`, `/hub/os/melden`, `/hub/os/antwort` verlangen
  `Content-Type: application/json` (415 sonst).

### ETag

`/hub/apps` und `/hub/resource` senden `ETag` und `Cache-Control: private, no-cache`; `If-None-Match` führt zu 304.

### Aufrufer

Der Hub merkt, wer ruft: `X-Hub-Caller` gewinnt; sonst `/hub/app-call|apps|resource` = `fyos-web` (die Shell),
andere `/hub/*` = `rest:<User-Agent-Produkt>`, `/mcp` = `mcp:<Produkt>`; nach der Anmeldung `oauth:<Zielgruppe>`.

## 3. OS-Brücke, Wire-Protokoll v1

Ein Agent sieht und steuert die offene Shell. Zustand liegt in Redis (`REDIS_URL`).

**`GET /hub/os/strom?sitzung=<id>&geraet=<name>[&nach=<stream-id>]`**, Kopf `Last-Event-ID` hat Vorrang.
`text/event-stream`. Erste Zeile `retry: 3000`, dann `event: hallo` (`{"sitzung", "ablauf_s": 90, "bekannt": bool}`;
`bekannt: false` heißt sofort `melden`). Dann `event: befehl` mit `id:` = Stream-ID, `data:` = Befehl als JSON.
Alle 15 s `: ping`. Nach 10 min endet der Strom sauber; der Browser verbindet mit `Last-Event-ID` neu und verliert
nichts. Redis-Ausfall: `event: abbruch` `{"grund": "redis"}`.

**`POST /hub/os/melden`** `{sitzung, geraet, art, seite, sichtbar, aktiv_vor_s, anruf, agent_vorne, bildschirm,
bildschirme[], fenster[], flaechen[], werkzeuge[], audio?, version: 1, gesendet}` antwortet
`{ok: true, ablauf_s: 90, sitzungen: n}`; alle 30 s und bei Änderungen. `{sitzung, ende: true, gesendet}` beendet
die Sitzung. Sitzungen ohne Strom melden `abholen: true` (+ `nach`) und bekommen Befehle in der Antwort.

**`POST /hub/os/antwort`** `{sitzung, befehl, ok, ergebnis?, fehler?}` antwortet `{ok: true}`. Nur die Sitzung, an die
der Befehl ging, darf antworten (sonst 400).

Befehle (`data` von `event: befehl`):

```
{"id": "b-…", "art": "zeigen",     "ziel": "app:<plugin>__<werkzeug>", "eingabe": {…}|null, "von": "agent"}
{"id": "b-…", "art": "ausfuehren", "werkzeug": "<name>", "argumente": {…}, "von": "agent"}
{"id": "b-…", "art": "zeigt",      "zeigt": {ziel, app, titel, untertitel, symbol, ton, vorschau, eingabe, link,
                                               audio: {modus, klang, sprechen}, [art: "mitteilung", dringlichkeit]},
                                    "von": "agent"}              (keine Antwort)
```

Flächen-IDs: `agent`, `seite:<name>`, `app:<plugin>__<werkzeug>`, `nativ:<name>`. Aufrufer-Namen, die als Agent
gelten, stehen in `OS_AGENT_AUFRUFER` (Komma, `name*` = Präfix; Vorgabe `agent*`); `OS_AGENT_ZEIGT=aus` schaltet
„Agent zeigt“ ab.

## 4. Plugin-Schnittstelle

Ein Plugin ist eine Klasse `mcp_hub.plugin.HubPlugin`:

| Methode | Pflicht | Zweck |
|---|---|---|
| `register()` | ja | einmal beim Start: Verbindungen, Zugangsdaten |
| `init()` | nein | erweitertes Aufsetzen nach `register` |
| `describe_tools()` | ja | Liste von `ToolDescriptor` |
| `describe_resources()` | nein | Liste von `ResourceDescriptor` (`ui://`-Oberflächen) |
| `call(method, args)` | ja | führt das Werkzeug `method` aus; Rückgabe JSON-fähig |
| `health()` | nein | `{"ok": bool, …}` |
| `routen()` | nein | eigene HTTP-Wege (Starlette-`Route`) für Dinge, die kein Werkzeug sein sollen, etwa Telemetrie eines Clients |
| `registry_anbinden(registry)` | nein | einmal nach dem Laden aller Plugins: das Register (andere Plugins, `on_call_hooks` für Audit und Bus) |
| `oeffnen_ziel(werkzeug, args)` | nein | lenkt den Link „In FYOS öffnen“ eines Werkzeugs um: `("<plugin>.<werkzeug>", argumente)` des Werkzeugs, das den Zustand zeigt, sonst `None`. Nötig, wenn die Eingabe nicht in einen Link passt (über 4000 Zeichen JSON); `gui.bauen` verweist so auf `gui.zeigen {id}`. Das Ziel muss selbst lesend und für das Modell sichtbar sein; bei jedem Fehler bleibt es beim eigenen Werkzeug |
| `metrics()` | nein | Kennzahlen für `/metrics`: Zahlen der obersten und nächsten Ebene als `fyos_plugin_wert{plugin, schluessel}`, eigene Reihen unter `"_proben"` (`[{name, wert, labels?, typ? gauge\|counter, hilfe?}]`, Namen ohne `fyos_` bekommen `fyos_<plugin>_`); 30 s zwischengespeichert, also ohne teure Abfragen |
| `zeitplan()` | nein | wiederkehrende Aufgaben für `mcp.zeitplan` und `/metrics` (`fyos_zeitplan_*`): `[{id, name, takt, beschreibung?, an?, naechster?, letzter?, letzter_status? ok\|fehler, letzter_fehler?, quelle?, max_pro_tag?, fenster?, ruht?, laeufe_heute?, uebersprungen?, protokoll?}]`, Zeiten in Unix-Sekunden, aus dem Speicher; die letzten sechs Felder liefert der Wächter `mcp_hub.takt` für Takte mit Tageslimit und Zeitfenster (`ERWEITERN.md` §2.12) |
| `skills_beitrag()` | nein | Skills für `skills.suchen`/`skills.lesen`: `[{name, beschreibung, text \| lesen, quelle?, ausloeser?}]`; Datei-Quellen gewinnen bei gleichem Namen |
| `shutdown()` | nein | Aufräumen |

Wege aus `routen()` müssen unter `/hub/` liegen, damit Herkunfts- und Anmeldeschutz greifen (Abschnitt 2 und 5). Der
Kern hängt sie nach seinen eigenen ein und lehnt einen schon belegten Weg mit einer Warnung im Log ab; scheitert
`routen()`, fehlen nur die Wege dieses Plugins. Ein Weg erscheint weder in `hub__map` noch im Audit der Werkzeuge.

Klassenattribute: `name`, `description`, `version`, `argumente_vertraulich` (`True`: Argumente erscheinen auf dem
Ereignisbus nur als `{"redacted": true}`, unabhängig von `event_bus_publisher.skip_arg_publish`).

`ToolDescriptor`: `name`, `description`, `input_schema`, `tags`, `meta`, `title`, `zeitlimit_s`. Die Werkzeug-ID ist
`<plugin>.<name>`. Tags: genau eines von `read`, `write`, `destructive`, `exec` (Scope), `extern` für Aufrufe nach
außen; `flaeche` erlaubt den Aufruf über `/hub/app-call`. `meta.ui.resourceUri` verbindet das Werkzeug mit einer
Oberfläche, `meta.ui.visibility = ["app"]` macht es nur für die Oberfläche sichtbar, `meta.app` trägt die Identität
(`titel`, `untertitel`, `symbol`, `ton`, `kategorie`), `meta.kurz` einen Einzeiler für die Kurzansicht.
`ResourceDescriptor`: `uri`, `name`, `read` (liefert HTML), `description`, `mime_type`
(`text/html;profile=mcp-app`), `meta`.

### Anmelden

1. **Entry-Point** im Paket des Plugins (der Hub lädt es ohne Konfiguration):

   ```
   [project.entry-points."mcp_hub.plugins"]
   meins = "mein_paket.plugin:MeinPlugin"
   ```

2. **Konfiguration** in `config.yaml`: Eintrag mit `name` und optional `config`, `secrets`, `enabled`. Ohne `module`
   gilt der Entry-Point gleichen Namens; mit `module` (+ `class`) wird das Modul direkt importiert. `enabled: false`
   schaltet auch ein per Entry-Point installiertes Plugin ab. Eine Klasse mit Parameter `config` bekommt die
   Plugin-Konfiguration im Konstruktor.

Ein Plugin, das nicht lädt, reißt den Hub nicht mit; `/hub/health` nennt den Grund.

### Oberfläche

`_oberflaeche.oberflaeche(datei, ui_verzeichnis)` liest die HTML-Datei aus einem Pfad oder aus `<paket>/ui/`
(Paketname als Text). Platzhalter für Stil, Brücke und Kopf der App werden eingesetzt.
`_identitaet.registriere_app(schluessel, eintrag, datei=, hauptwerkzeug=)` trägt Titel, Symbol, Farbton und Kategorie
(`System`, `Betrieb`, `Wissen`, `Beispiele`) ein; die Shell zeigt die App dann in Dock und Kacheln.

## 5. Anmeldung

Optional. Ohne `FYOS_OIDC_ISSUER` ist der Hub innen offen und antwortet auf Anfragen von außen (Kopf
`X-FYOS-Zugang: extern` oder ein Host aus `FYOS_OIDC_HOSTS`) an `/mcp` mit 403. Mit Aussteller verlangt `/mcp` für
Anfragen von außen ein Bearer-Token (JWT, RS256/ES256/EdDSA, Schlüssel per Discovery); ohne Token 401 mit
`WWW-Authenticate: Bearer … resource_metadata="<url>/.well-known/oauth-protected-resource/mcp"`, Schlüssel nicht
ladbar 503. Variablen: `FYOS_OIDC_ISSUER`, `FYOS_OIDC_CLIENTS`, `FYOS_OIDC_MODUS` (`aus|an|streng`),
`FYOS_OIDC_HOSTS`, `FYOS_OIDC_REST` (Vorgabe `/hub/app-call`, nie `/hub/call`), `FYOS_OIDC_BENUTZER` (Vorgabe `*`),
`FYOS_OIDC_SCOPES`, `FYOS_OIDC_JWKS_URL`, `FYOS_OIDC_LEEWAY_S`. Der `Authorization`-Kopf wird nicht weitergereicht.
