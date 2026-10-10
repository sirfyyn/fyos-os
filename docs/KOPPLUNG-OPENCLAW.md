# Kopplung an OpenClaw

FYOS und OpenClaw bringen Gegenstücke mit: Vorgänge und Workboard, Hub-Plugins mit Skills und OpenClaw-Plugins mit
Skills, Nutzung und Aktivität auf beiden Seiten, Zustandsprüfung und Kennzahlen, Takte der Hub-Plugins und Cron. Statt
doppelt zu führen, greifen sie ineinander: Je Paar führt eine Seite, die andere zeigt an oder reicht weiter.

Zwei Teile tragen die Kopplung:

| Teil | Ort | Aufgabe |
|---|---|---|
| Hub-Plugin `openclaw` | `fyos-os/hub/mcp_hub/plugins/openclaw.py` (mit `_vorgaenge.py`) | nimmt Ereignisse an, fragt das Gateway ab, spiegelt Vorgänge, trägt zu Zeitplan, Skills und `/metrics` bei |
| OpenClaw-Plugin `fyos-bruecke` | `fyos-agent/plugins/fyos-bruecke/` | übersetzt Hooks in Ereignisse ohne Inhalte, beantwortet Abfragen einer festen Methodenliste |

Beide sind in der Grundausstattung an. Ohne `FYOS_AGENT_URL` ist das Hub-Plugin aus, ohne Hub-Adresse bleibt die
Brücke still; keine der beiden Seiten braucht die andere, um zu laufen.

## 1. Die Paare

| FYOS | OpenClaw | Führt | Wie sie ineinandergreifen |
|---|---|---|---|
| Vorgänge (Vorgangs-Dienst, ITSM) | Workboard | der Vorgangs-Dienst, wenn es einen gibt; sonst das Workboard | **Spiegel**: offene Vorgänge erscheinen als Karten auf dem Board `fyos`; Verschieben und Kommentieren in OpenClaw gehen in den Vorgang zurück. **Ablage**: ohne Vorgangs-Dienst sind die Karten die Vorgänge, der Hub bietet den Vorgangs-Vertrag auf ihrer Basis an (Abschnitt 4). |
| Hub-Plugins und ihre Skills (`skills.suchen`) | Plugins und Skills des Gateways | jede Seite für ihre eigenen | Der Agent lädt die Skills aus fyos-agent nativ (`skills.load.extraDirs`), Hub-Skills holt er bei Bedarf über `skills.suchen`. Der Hub zeigt die eigenen Skills des Agenten in `skills.suchen` (Quelle `openclaw` oder `fyos-agent`, gleichnamige Hub-Skills gewinnen). Nicht dabei sind die mit OpenClaw mitgelieferten, gebündelt oder von seinen Plugins (Verweise unter `~/.openclaw/plugin-skills/`): Sie beschreiben Werkzeuge, die nur der Agent hat. `openclaw.erweiterungen` legt beide Seiten nebeneinander (Plugin-Skills mit Quelle `openclaw-plugin`). |
| Nutzung und Aktivität (Audit, Ereignisbus, Sammelstrom `fyos:live`) | Werkzeug- und Modellaufrufe, Läufe, Sitzungen; `usage.cost` | Aufrufe zählt der Hub, Token und Kosten zählt OpenClaw | Die Brücke meldet jeden Aufruf; Werkzeugaufrufe des Agenten laufen durch dieselben Haken wie Aufrufe im Hub (Audit als `openclaw-agent.<werkzeug>`). Hub-Werkzeuge, die der Agent über MCP ruft, meldet die Brücke nicht, der Hub hat sie schon. `openclaw.nutzung` legt die Zählung der Brücke und `usage.cost` zusammen. |
| Zustand und Kennzahlen (`/hub/health`, `/metrics`) | `/healthz`, `/readyz`, `health` | jede Seite für sich, der Hub sammelt | Der Hub prüft die Sonden alle 15 s; `health()` des Plugins wird „unreachable“, wenn das Gateway schweigt, und „degraded“, wenn es nicht bereit ist oder die Brücke länger als 300 s still bleibt. `/metrics` trägt die Reihen `fyos_openclaw_*`. |
| Telemetrie | `diagnostics`, `telemetry` | der Hub | Die Telemetrie von OpenClaw bleibt aus (Vorlage in fyos-agent); Ereignisse gehen nur an den eigenen Hub. |
| Takte der Hub-Plugins (`zeitplan()`) | Cron | Aufgaben mit Modell: Cron in OpenClaw. Aufgaben ohne Modell: Takt im Hub-Plugin | `mcp.zeitplan` zeigt beide in einer Liste (Quelle `openclaw` für Cron), `/metrics` beide als `fyos_zeitplan_*`; jeder Cron-Lauf kommt als Ereignis. Takte des Hubs können ein Tageslimit und ein Zeitfenster tragen (`takt_grenzen`, §5), ihr Laufprotokoll steht in `mcp.zeitplan`. |

Die Faustregel für neue Arbeit: Braucht eine wiederkehrende Aufgabe das Modell (zusammenfassen, entscheiden, schreiben),
gehört sie als Cron-Auftrag in OpenClaw. Holt sie nur Daten oder gleicht Zustände ab, gehört sie als Takt in ein
Hub-Plugin und meldet sich über `zeitplan()`.

## 2. Ereignisse: OpenClaw → Hub

`POST <hub>/hub/openclaw/ereignisse` mit `Content-Type: application/json`, höchstens 512 KiB; der Hub verarbeitet
höchstens 500 Ereignisse je Lieferung. Die Brücke sammelt Ereignisse in einer Warteschlange (Vorgabe 1000, volle Schlange verwirft die ältesten
und zählt sie), schickt alle 5 s bis zu 200 Stück und meldet sich ohne Ereignisse spätestens alle 60 s
(Lebenszeichen). Nach einem Fehler wartet sie 2, 4, 8 … höchstens 60 s; lehnt der Hub ab (4xx außer 408 und 429),
fällt das Paket weg und wird gezählt.

**Signatur.** Ist im Hub `FYOS_AGENT_TOKEN` gesetzt, muss jede Lieferung signiert sein:

```
X-FYOS-Zeit:     <Unix-Millisekunden>
X-FYOS-Signatur: sha256=<hex von HMAC-SHA256(Gateway-Token, "<X-FYOS-Zeit>.<Körper>")>
```

Der Hub prüft in konstanter Zeit und weist Lieferungen ab, die älter oder jünger als 300 s sind (401). Das Token
selbst verlässt das Gateway nie. Ohne Token im Hub nimmt er Lieferungen ungeprüft an (innen offen, wie der Rest des
Hubs).

**Körper:**

```json
{
  "bruecke": {"version": "0.1.0", "instanz": "agent-0", "gestartet": 1760000000000,
              "verworfen": 0, "warteschlange": 3, "plugins": [{"id": "workboard", "an": true}]},
  "ereignisse": [{"art": "werkzeug", "zeit": 1760000001234, "werkzeug": "web_fetch", "ok": true, "dauer_ms": 420,
                  "agent": "main", "sitzung": "3f9a0c2b71de", "kanal": "matrix"}]
}
```

Antwort: `{"ok": true, "angenommen": <n>}`; 400 bei kaputtem JSON, 401 bei falscher Signatur, 413 bei zu großer
Lieferung, 415 bei falschem Inhaltstyp.

| `art` | Hook in OpenClaw | Felder (außer `zeit`) |
|---|---|---|
| `werkzeug` | `after_tool_call` | `werkzeug`, `ok`, `dauer_ms`, `fehler`, `agent`, `sitzung`, `kanal` |
| `modell` | `model_call_ended` | `anbieter`, `modell`, `ergebnis` (`completed` oder `error`), `dauer_ms`, `fehlerart`, `agent`, `sitzung` |
| `lauf` | Lebenszyklus-Abo (`lifecycle`: `start`, `end`, `error`) | `ok`, `dauer_ms`, `fehler`, `agent`, `sitzung` |
| `sitzung` | `session_start`, `session_end` | `phase` (`beginn` oder `ende`), `sitzung`, `agent`, `grund`, `dauer_ms` |
| `cron` | `cron_changed` | `aktion` (`added updated removed started finished scheduled`), `job`, `name`, `status`, `dauer_ms`, `fehler`, `naechster_ms`, `agent` |
| `skill` | `skill_changed` | `aktion`, `name`, `quelle` |
| `skill_vorschlag` | `skill_proposal_changed` | `aktion`, `name`, `status` |
| `hinweis` | die Brücke selbst | `stufe`, `text` (etwa „Brücke gestartet“) |

**Werkzeuge hinter `tool_call`:** Nachgeladene Werkzeuge (MCP, Plugins) ruft das Modell über das Steuer-Werkzeug
`tool_call`. OpenClaw meldet dann zwei `after_tool_call`: zuerst den inneren Aufruf unter dem echten Namen
(Aufruf-ID `tool_call:<Hüllen-ID>:<Name>:<n>`), danach die Hülle. Die Brücke zählt den Aufruf einmal unter dem
echten Namen. Die Hülle zählt nur, wenn kein innerer Aufruf kam; dann gilt der Name aus `params.id` (Katalog-ID
`<quelle>:<herkunft>:<name>` oder der Name selbst). `werkzeug_auslassen` gilt für den echten Namen, also zählt auch
ein Hub-Werkzeug hinter der Hülle nicht.

**Was nie hinausgeht:** Argumente und Ergebnisse von Werkzeugen, Texte von Nachrichten und Modellantworten,
Dateipfade, Zusammenfassungen von Cron-Läufen. Sitzungsschlüssel kommen nur als die ersten 12 Zeichen ihres
SHA-256. Ein Fehler kommt als Code und erste Zeile seiner Meldung, höchstens 120 Zeichen; der Hub schwärzt sie noch
einmal. Die Brücke braucht keinen Einblick ins Gespräch (`allowConversationAccess: false`): sie hört nur Hooks, die
ohne Inhalte auskommen.

**Was der Hub daraus macht:** Werkzeugaufrufe gehen durch `registry.on_call_hooks` (Audit, Ereignisbus, Sammelstrom),
als Aufrufer `agent:<id>` und mit Argumenten `{}`. Alles landet im Strom `fyos:openclaw:aktivitaet` (höchstens 5000
Einträge) und in Tageszählern `fyos:openclaw:tag:<YYYY-MM-DD>` (40 Tage), die `openclaw.nutzung` liest.

## 3. Abfragen: Hub → OpenClaw

`POST <gateway>/plugins/fyos-bruecke/v1/rpc` mit `Authorization: Bearer <Gateway-Token>` und
`{"id"?: "…", "method": "<name>", "params": {…}}`. Die Route verlangt die Anmeldung des Gateways (`auth: "gateway"`);
ein Shared-Secret-Token bekommt dort nur `operator.write`, nie `operator.admin`. Die Brücke reicht die Methode mit
`dispatchGatewayMethod` weiter, also mit den Rechten des Aufrufers und nur, wenn sie auf der Liste steht:

| Methoden | Zweck |
|---|---|
| `workboard.boards.list`, `workboard.boards.upsert` | Board `fyos` anlegen (ohne Automation, also passiv) |
| `workboard.cards.list`, `.create`, `.update`, `.move`, `.comment`, `.archive` | Karten lesen und pflegen |
| `skills.status` | Skills des Agenten |
| `cron.list`, `cron.runs`, `cron.status` | Cron-Aufträge und Läufe |
| `usage.cost`, `usage.status` | Token, Kosten, Kontingente laut OpenClaw |
| `health` | Zustand des Gateways |
| `fyos.skill.lesen` `{name}` → `{name, text, quelle}` | Text eines Skills; nur Dateien, die `skills.status` selbst nennt, höchstens 512 KiB |
| `fyos.bruecke.status` | Stand der Brücke (Warteschlange, gesendet, Fehler); auch als Gateway-Methode (`operator.read`) |

Alles andere beantwortet die Route mit 403 `FORBIDDEN`, ohne das Gateway zu fragen; insbesondere startet der Hub keine
Läufe, keine Worker (`workboard.cards.dispatch`, `claim`) und ändert keine Konfiguration oder Cron-Aufträge.

Antwort: `{"id", "ok": true, "payload"}` oder `{"id", "ok": false, "error": {"code", "message"}}`. HTTP-Status: 200,
400 `INVALID_REQUEST`, 403, 404 `NOT_FOUND`, 405, 409 bei einem Konflikt (`workboard_conflict`), 413, 503
`UNAVAILABLE`, 504 `AGENT_TIMEOUT`, sonst 500.

Dazu fragt der Hub die anmeldefreien Sonden `GET <gateway>/healthz` und `/readyz` (alle 15 s).

## 4. Vorgänge und Workboard

Der Vorgangs-Vertrag ist der des Vorgangs-Dienstes (`fyos-agent/plugins/fyos-freigabe-chat/board.mjs`):
`GET /tickets?status=&limit=`, `GET /tickets/{id}`, `POST /tickets`, `POST /tickets/{id}/comments` `{actor, text}`,
`PATCH /tickets/{id}` `{status, expected_status?, actor?, title?, description?, priority?}`.

| Vorgang | Karte (der Abgleich setzt) | Karten-Status, die als gleich gelten |
|---|---|---|
| `new` | `triage` | `triage` |
| `triage` | `backlog` | `triage backlog todo scheduled ready` |
| `in_progress` | `running` | `running blocked` |
| `waiting_approval` | `review` | `review` |
| `resolved`, `closed` | `done` | `done` |

**Spiegel** (`FYOS_VORGAENGE_URL` gesetzt): Im Takt (Vorgabe 60 s, `openclaw.abgleichen` sofort) legt der Hub für
jeden offenen Vorgang eine Karte an (Label `vorgang:<ID>`, Idempotenzschlüssel `vorgang:<ID>`, keine Doppelkarte),
führt Titel, Priorität und Notizen nach und verschiebt die Karte, wenn sich der Vorgang ändert. Verschiebt jemand
eine Karte in OpenClaw, geht der Status in den Vorgang zurück (`zurueck`, mit `expected_status` gegen gleichzeitige
Änderungen), Kommentare an der Karte kommen als Kommentar an den Vorgang. Zwei Riegel:

- Eine Freigabe entscheidet nie das Workboard. Verlässt eine Karte `review`, solange der Vorgang auf Freigabe wartet,
  kommentiert der Hub das am Vorgang und schiebt die Karte zurück; entschieden wird über den Freigabeweg (Chat oder
  Vorgang).
- `closed` setzt nur der Vorgangs-Dienst. `ready` setzt der Abgleich nie: das ist der Status, den ein Dispatch-Durchgang
  des Workboards abholen würde. Das Board `fyos` hat keine Automation und startet nichts.

Ist ein Vorgang nicht mehr offen, schließt der Hub die Karte (`done`), wenn der Dienst ihn als erledigt meldet oder
sicher nicht mehr kennt (404).

**Ablage** (kein Vorgangs-Dienst): Das Workboard ist die Ablage, Board `default`. Der Hub bietet denselben Vertrag
unter `/hub/vorgaenge/tickets…` auf Basis der Karten an; eine Karte heißt dort `WB-<erste acht Zeichen ihrer ID>` oder,
wenn sie ein Label `vorgang:<ID>` trägt, so. Wer im **Agenten** `FYOS_VORGAENGE_URL=http://hub:8080/hub/vorgaenge`
setzt, gibt etwa der Freigabe im Chat das Workboard als Vorgangs-Dienst. Im Hub selbst ignoriert das Plugin eine
Adresse, die auf `/hub/vorgaenge` endet (sonst spiegelte es das Workboard auf sich selbst).

## 5. Einrichten

**Agent** (`fyos.yaml`, Vorlage in fyos-agent):

```yaml
kopplung:
  aktiv: true        # fyos-bruecke an
  hub_url: ""        # leer: FYOS_HUB_URL ohne /mcp, z. B. http://hub:8080
  workboard: true    # Workboard an; der Agent liest, legt an, kommentiert und verschiebt Karten
```

Umgebung: `FYOS_HUB_URL` (MCP-Endpunkt des Hubs) und `OPENCLAW_GATEWAY_TOKEN`. Unabhängig von `kopplung` lädt die
Vorlage die Skills aus fyos-agent (`skills.load.extraDirs: ["/opt/fyos/skills"]`).

**Hub** (Umgebung oder `config` des Eintrags `openclaw`):

| Umgebung | `config` | Bedeutung |
|---|---|---|
| `FYOS_AGENT_URL` | `gateway_url` | Gateway, z. B. `http://agent:18789`; leer = Kopplung aus |
| `FYOS_AGENT_TOKEN` | `token` | das Gateway-Token: Abfragen und Prüfung der Signatur |
| `FYOS_VORGAENGE_URL` | `vorgaenge_url` | Vorgangs-Dienst; leer = Workboard ist die Ablage |
| `FYOS_VORGANG_LINK` | `vorgang_link` | Verweis je Vorgang mit `{id}`, erscheint in Notizen und `sourceUrl` der Karte |
| | `board` | Board der Vorgänge (Vorgabe `fyos` im Spiegel, `default` als Ablage) |
| | `abgleich_s` | Takt des Abgleichs (Vorgabe 60, 0 = nur auf Abruf) |
| | `takt_grenzen` | Grenzen je Takt (`cron`, `skills`, `abgleich`, `karten`): `{abgleich: {max_pro_tag: 500, fenster: "06:00-23:00"}}`. Außerhalb des Fensters oder über dem Tageslimit läuft der Takt nicht (Zeitzone des Hubs, `TZ`); `openclaw.abgleichen` auf Abruf und die Sonde laufen immer. Ein Tippfehler im Namen oder in der Uhrzeit verhindert das Laden des Plugins. |
| | `werkzeug_auslassen` | Namensanfänge, die der Hub nicht zählt (Vorgabe `hub__`, `mcp__hub__`, `mcp-hub__`) |
| | `fyos_skill_pfade` | Skill-Verzeichnisse von fyos-agent im Agenten (Vorgabe `/opt/fyos/skills`) |
| | `akteur` | Name für Änderungen aus OpenClaw im Vorgangs-Dienst (Vorgabe `openclaw`) |
| | `audit` | Werkzeugaufrufe des Agenten ins Audit (Vorgabe an) |

Compose (`deploy/compose/docker-compose.yml`) und Kubernetes (`deploy/k8s/base/hub.yaml`) setzen `FYOS_AGENT_URL`
und `FYOS_AGENT_TOKEN` schon; in Kubernetes kommt das Token aus dem Secret `fyos-agent-gateway` (Schlüssel `token`),
dasselbe, das der Agent als `OPENCLAW_GATEWAY_TOKEN` liest.

## 6. Werkzeuge und Kennzahlen im Hub

| Werkzeug | Inhalt |
|---|---|
| `openclaw.zustand` | Sonden, letzte Meldung der Brücke, Betriebsart, Zähler, Takte |
| `openclaw.nutzung` `{tage}` | Aufrufe je Tag (Werkzeuge, Modelle, Läufe, Sitzungen) und `usage.cost` laut OpenClaw |
| `openclaw.aktivitaet` `{limit, art}` | was der Agent zuletzt tat, neueste zuerst |
| `openclaw.erweiterungen` | Skills und Plugins beider Seiten nebeneinander |
| `openclaw.arbeit` | offene Karten des Vorgangs-Boards, letzter Abgleich |
| `openclaw.abgleichen` | Abgleich jetzt (schreibend) |
| `mcp.zeitplan` `{quelle}` | Takte aller Hub-Plugins und die Cron-Aufträge des Agenten |

`/metrics` (Prometheus-Text): `fyos_openclaw_gateway_lebt`, `fyos_openclaw_gateway_bereit`,
`fyos_openclaw_bruecke_alter_s`, `fyos_openclaw_bruecke_verworfen`, `fyos_openclaw_ereignisse_total{art}`,
`fyos_openclaw_werkzeugaufrufe_total{ergebnis}`, `fyos_openclaw_modellaufrufe_total{modell, ergebnis}`,
`fyos_openclaw_laeufe_total{ergebnis}`, `fyos_openclaw_sitzungen_total{phase}`,
`fyos_openclaw_cron_laeufe_total{ergebnis}`, `fyos_openclaw_karten{board, status}`, `fyos_openclaw_rpc_fehler_total`,
`fyos_openclaw_abgewiesen_total`, dazu `fyos_zeitplan_*{plugin="openclaw", quelle="openclaw"}` je Cron-Auftrag. Takte mit
Grenzen (`takt_grenzen`) führen außerdem `fyos_zeitplan_laeufe_heute{takt}`, `fyos_zeitplan_max_pro_tag{takt}` und
`fyos_zeitplan_uebersprungen_total{takt, grund}` (`grund` ist `fenster` oder `limit`, `takt` die Kennung
`openclaw:<takt>` aus `mcp.zeitplan`). Die Cron-Aufträge des Agenten laufen in OpenClaw und haben dort ihre eigenen
Zeiten; Fenster und Tageslimit des Hubs gelten für die Takte, die der Hub selbst fährt.

## 7. Prüfen

1. `openclaw.zustand`: „Gateway bereit; Brücke vor n s“. Bleibt „Brücke noch ohne Meldung“, fehlt im Agenten
   `FYOS_HUB_URL` oder die Brücke ist aus (`kopplung.aktiv`); 401 im Log des Agenten heißt, die Tokens beider Seiten
   unterscheiden sich.
2. `openclaw.arbeit`: Board und Karten; im Spiegel nach höchstens 60 s die offenen Vorgänge.
3. Ein Werkzeugaufruf im Agenten erscheint in `openclaw.aktivitaet` und im Audit als `openclaw-agent.<werkzeug>`.
4. `curl -s http://hub:8080/metrics | grep fyos_openclaw_` zeigt die Reihen.
5. Gegenprobe der Grenze: `POST /plugins/fyos-bruecke/v1/rpc {"method": "cron.add"}` antwortet 403.

## 8. Grenzen

- Ein stiller oder kaputter Hub stört das Gateway nicht: Die Warteschlange ist begrenzt, Hooks fangen ihre Fehler, die
  Brücke meldet sich nicht als gestörter Dienst des Gateways (das würde `/readyz` des Agenten an den Hub ketten).
- Umgekehrt hält ein stilles Gateway den Hub nicht auf: Abfragen haben Zeitlimits, gemerkte Stände bleiben stehen,
  `health()` meldet den Grund.
- `plugin.workboard.changed` gibt es nur über die WebSocket-Verbindung des Gateways; der Hub liest Karten deshalb im
  Takt (60 s) statt auf Zuruf.
- Token- und Kostenzahlen kommen nur aus `usage.cost`; die Brücke zählt Aufrufe, keine Token (dafür bräuchte sie
  `llm_output` und damit Einblick ins Gespräch).
