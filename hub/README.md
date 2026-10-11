# FYOS-Hub

Der Hub von FYOS (For Your Own Sake): ein MCP-Server, der viele Plugins unter einer Adresse anbietet.
Ein Plugin liefert Werkzeuge und, wenn es will, eine Oberfläche (`ui://`-HTML). Die Shell zeigt diese
Oberflächen als Fenster, jeder MCP-Client mit MCP-Apps-Unterstützung im Gespräch.

Der Hub spricht dreierlei:

- **MCP** unter `/mcp` (Streamable HTTP) für Agenten und Chat-Clients,
- **REST** unter `/hub/*` für die Shell und Skripte,
- **Gesundheit** unter `/health`.

Die genauen Wege und Formate stehen in [`docs/HUB-VERTRAG.md`](../docs/HUB-VERTRAG.md).

## Installieren und starten

```
pip install ".[suche]"          # Kern; [suche] bringt Qdrant-Client und numpy (optional)
fyos-hub                        # oder: python3 -m mcp_hub.server
```

Als Bild: `docker build -t fyos-hub hub/` (Build-Argument `EXTRA_PIP` installiert weitere Plugin-Pakete, z. B.
`--build-arg EXTRA_PIP="fyos-plugin-finanzen"`). Das Bild lauscht auf Port 8080.

Das Bild installiert Plugin-Pakete mit `uv` statt mit `pip`. Liegen sie in einem eigenen Paketindex, kommt dessen Adresse als
`--build-arg FYOS_INDEX_URL=<Index-URL>` und steht damit vor PyPI. `--index-strategy first-index` steht ausdrücklich im Befehl:
uv nimmt ein Paket nur aus dem ersten Index, der es führt, ein Paket gleichen Namens auf PyPI kann das eigene also nicht
verdrängen (Dependency Confusion; mit `pip --extra-index-url` wäre das möglich). Die Version von uv ist im Dockerfile fest.

Ohne Konfigurationsdatei lädt der Hub jedes installierte Plugin der Entry-Point-Gruppe `mcp_hub.plugins`
mit seinen Vorgaben. Eine Datei (`MCP_HUB_CONFIG_PATH`, Vorgabe `./config.yaml`) braucht es nur für
Plugin-Einstellungen, Geheimnisse oder `enabled: false`; siehe `config.example.yaml`.

## Mitgelieferte Plugins

| Plugin | Zweck |
|---|---|
| `skills` | Arbeitsanleitungen (`<quelle>/<name>/SKILL.md`) durchsuchen und lesen |
| `werkstatt` | angemeldete Skripte (Kopfblock `WERKSTATT`) finden und mit Trockenlauf ausführen |
| `mcp` | Werkzeugkasten: Plugins, Werkzeuge, Apps und Protokolle des Hubs ansehen |
| `shell` | Anordnung der offenen Shell (Fenster, Raster) als Werkzeuge |
| `os` | Verbindung zur Shell: `os.lage`, `os.zeigen`, `os.ausfuehren`, `os.mitteilen`; Mitteilungen ohne Gegenüber warten bis zu 24 h (docs/NACHTARBEIT.md) |
| `audit` | Protokoll aller Werkzeugaufrufe (Ringpuffer, mit Qdrant Vektorsuche) |
| `event_bus_publisher` | Ereignisse je Werkzeugaufruf auf Redis-Streams (sonst im Speicher) |
| `gui` | Ansichten bauen: Kennzahlen, Balken, Verlauf, Tabelle … aus Vorlagen oder frei, als App und als Seite (siehe unten) |
| `dateien` | gemeinsame Dateiablage mit der App „Dateien“: Ordner, Vorschau, Hochladen per Ziehen, Papierkorb, frühere Fassungen; Ordner per `FYOS_DATEIEN` (docs/ERWEITERN.md §2.17) |
| `beispiel_app` | Notizzettel mit Oberfläche, Vorlage für eigene Apps |
| `echo`, `math` | Referenz-Plugins, standardmäßig aus |

Alles Weitere (Finanzen, Haus, Betrieb …) sind eigene Pakete, die sich per Entry-Point melden.

## Ansichten bauen (`gui`)

Das Plugin `gui` lässt den Agenten für den Moment eine bedienbare Ansicht bauen, statt nur zu antworten. `gui.vorlagen`
listet neun Vorlagen (Kennzahlen, Balken, Verlauf, Tabelle, Vergleich, Ablauf, Zeitleiste, Status, Diagramm; die
Vorlage Diagramm bettet SeeCode ein, MIT, siehe `NOTICE`). `gui.bauen` zeigt eine
mit Daten (`vorlage` und `daten`), auf Wunsch live aus einem lesenden Werkzeug (`quelle`), oder eine frei gebaute
(`html`, `css`, `js`). Die Ansicht läuft in einer Sandbox ohne Netz; `gui.zeigen` holt eine gebaute wieder.

Die Anleitung (Skill `generative-ui`) und die Vorlagen sind Paketdaten des Kerns (`mcp_hub/skills/generative-ui/`).
Das Plugin `skills` findet den Skill ohne Einstellung über die Entry-Point-Gruppe `fyos.skills` (Quelle `kern`); eigene
Vorlagen kommen mit `config: {vorlagen: <Ordner>}` dazu. Abgelegt werden höchstens 300 Ansichten in `mcp_hub.kv`: mit
`REDIS_URL` in Redis (so lange wie dessen Persistenz), sonst im Speicher des Prozesses (dann bis zum Neustart des Hubs).

Für Flächen ohne MCP-Apps-Host liefert der Hub eine Ansicht als ganze Seite: `GET /hub/gui/<id>`, dazu
`GET /hub/gui/<id>/daten` für frische Daten einer Live-Quelle (Beschreibung in
[`docs/HUB-VERTRAG.md`](../docs/HUB-VERTRAG.md)). Der Mod [`fyos-ansicht`](../tools/claude-code/fyos-ansicht/README.md)
für Claude Code öffnet sie damit im Terminal-Panel.

## Ein eigenes Plugin

```
# pyproject.toml des Plugin-Pakets
[project.entry-points."mcp_hub.plugins"]
meins = "mein_paket.plugin:MeinPlugin"
```

```
uv pip install ./mein-plugin    # danach lädt der Hub es ohne Eintrag in config.yaml
```

Die Klasse erbt von `mcp_hub.plugin.HubPlugin` (`register`, `describe_tools`, `call`, optional `health`,
`describe_resources`). Hat das Plugin eine Oberfläche, liegen die HTML-Dateien in `<paket>/ui/`; das Plugin
übergibt den Paketnamen an `mcp_hub.plugins._oberflaeche.oberflaeche(datei, "mein_paket")`, und
`_identitaet.registriere_app(...)` gibt der App Titel, Symbol und Farbton. `plugins/beispiel_app.py` zeigt alles
in 200 Zeilen.

## Umgebungsvariablen

| Variable | Wirkung |
|---|---|
| `MCP_HUB_CONFIG_PATH` | Pfad der YAML-Datei |
| `MCP_HUB_HOST`, `MCP_HUB_PORT`, `MCP_HUB_PATH` | Adresse, Port (8080), MCP-Pfad (`/mcp`) |
| `FYOS_OEFFENTLICH_URL` | öffentliche Adresse der Installation (Links, erlaubter Origin, Zielgruppe der Anmeldung) |
| `FYOS_ERLAUBTE_HOSTS` | weitere erlaubte Hostnamen/Origins, mit Komma getrennt (Vorgabe: `localhost`, `127.0.0.1`) |
| `FYOS_OS_URL` | Adresse der Shell, falls nicht `<FYOS_OEFFENTLICH_URL>/os` |
| `TZ` | Zeitzone des Hubs (Tageszähler und Zeitfenster der Takte), z. B. `Europe/Berlin`; ohne Angabe UTC |
| `REDIS_URL` | Redis für Ansichten, Suchspur, Ereignisse, OS-Brücke; ohne: Speicher im Prozess |
| `QDRANT_URL` | Vektorsuche im Audit-Protokoll; ohne: Ringpuffer |
| `FYOS_EMBED_URL`, `FYOS_EMBED_MODEL`, `FYOS_EMBED_KEY` | OpenAI-kompatibler Einbettungsdienst (`/v1/embeddings`) für Audit und Werkzeugsuche |
| `FYOS_SKILLS_PATH` | Skill-Quellen, mit `:` getrennt (Vorgabe `/opt/fyos/skills`) |
| `FYOS_REPO_PATH` | Repo der Werkstatt (Vorgabe `/opt/fyos/repo`) |
| `FYOS_DATEIEN`, `FYOS_DATEIEN_MAX_MB`, `FYOS_DATEIEN_VERSIONEN`, `FYOS_DATEIEN_PAPIERKORB_TAGE` | Ordner der Dateiablage (im Bild `/data/dateien`), größte Datei in MB (25), frühere Fassungen je Datei (10), Tage im Papierkorb (30) |
| `FYOS_OIDC_ISSUER` | schaltet die Anmeldung ein (siehe unten) |

Die OS-Brücke braucht für mehrere Replikate Redis; ein einzelner Hub funktioniert nur mit `REDIS_URL`.

## Takte begrenzen

Wiederkehrende Aufgaben eines Plugins erscheinen in `mcp.zeitplan` und `/metrics`. Fährt das Plugin sie über den
Wächter `mcp_hub.takt`, können sie zwei Grenzen haben: `max_pro_tag` (Läufe je Tag) und `fenster` (Uhrzeiten wie
`"07:00-22:00"`, auch über Mitternacht). Außerhalb des Fensters oder über dem Limit läuft die Aufgabe nicht; der Hub
zählt die übersprungenen Läufe (`fyos_zeitplan_uebersprungen_total{takt, grund}`, dazu `fyos_zeitplan_laeufe_heute{takt}`)
und führt je Takt ein knappes Laufprotokoll (Start, Dauer, Ergebnis; die letzten 20 Läufe) im Hub-Speicher. Tag und
Uhrzeit gelten in der Zeitzone des Hubs (`TZ`). Ohne Grenzen läuft alles wie vorher. Die Takte des mitgelieferten
Plugins `openclaw` stellt `takt_grenzen` in seiner `config` ein (`config.example.yaml`); eigene Plugins binden den
Wächter nach [`docs/ERWEITERN.md`](../docs/ERWEITERN.md) §2.12 ein.

## Anmeldung (optional)

Innen, im eigenen Netz, ist der Hub offen. Soll er auch aus dem Internet erreichbar sein, genügt ein
OpenID-Connect-Anbieter: `FYOS_OIDC_ISSUER` und `FYOS_OIDC_CLIENTS` (Client-IDs, mit Komma) setzen, der Reverse-Proxy
setzt auf Anfragen aus dem Internet den Kopf `X-FYOS-Zugang: extern`. Dann verlangt `/mcp` für diese Anfragen ein
gültiges Token (RFC 9728, Discovery der Schlüssel, nur RS256/ES256/EdDSA). Weitere Schalter: `FYOS_OIDC_MODUS`
(`aus`, `an`, `streng`), `FYOS_OIDC_HOSTS`, `FYOS_OIDC_REST`, `FYOS_OIDC_BENUTZER`, `FYOS_OIDC_SCOPES`,
`FYOS_OIDC_JWKS_URL`. Ohne `FYOS_OIDC_ISSUER` antworten Anfragen von außen mit 403.

## Bewusst nicht enthalten

Aus dem Ursprung dieses Hubs sind nur die allgemeinen Teile übernommen. Nicht enthalten sind die Plugins
`wissen` und `gedaechtnis`, die Entwicklungsansicht (`entwicklung`, `lage`), das Chat-Tor (`chat_gateway`:
der Hub ist selbst ein OIDC-geschützter Ressourcenserver) und alles, was zu einer einzelnen Installation gehört.
Solche Plugins gehören in eigene Pakete.

## Tests

```
pip install -e ".[suche,test]"
python3 -m pytest hub/tests -q
```
