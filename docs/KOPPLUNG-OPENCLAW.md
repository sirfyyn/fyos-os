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
              "verworfen": 0, "warteschlange": 3, "plugins": [{"id": "workboard", "an": true}],
              "kanaele": {"telegram": {"an": true, "ziel": true, "bereit": true}}},
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
| `memory.search`, `sessions.list`, `sessions.describe`, `last-heartbeat`, `progressCard.get`, `tools.effective`, `doctor.memory.status`, `agents.list`, `voicewake.routing.get`, `tts.status` | nur lesend: Gedächtnissuche, Sitzungen, Herzschlag, Fortschrittskarte, Werkzeuge, Gedächtnisstand, Agenten, Sprachweckung, Sprachausgabe |
| `fyos.wecken` `{text, vorgang? \| sitzung?, agent?, modus?}` → `{geweckt, modus, agent, sitzung}` | den Agenten wecken: Systemhinweis und Lauf über `wake` (siehe „Wecken“) |
| `fyos.vorgang.senden` `{vorgang, text, agent?, schluessel?}` → `{gesendet, agent, sitzung, lauf, status}` | Nachricht in die Sitzung eines Vorgangs über `chat.send`, ohne Zustellung an einen Kanal |
| `fyos.skill.lesen` `{name}` → `{name, text, quelle}` | Text eines Skills; nur Dateien, die `skills.status` selbst nennt, höchstens 512 KiB |
| `fyos.bruecke.status` | Stand der Brücke (Warteschlange, gesendet, Fehler, Chat-Kanäle); auch als Gateway-Methode (`operator.read`) |
| `fyos.kanal.mitteilen` `{text, kanal?}` → `{gesendet, kanal, gescheitert}` | eine dringende Mitteilung an den Besitzer über seinen Chat-Kanal (siehe unten) |

Alles andere beantwortet die Route mit 403 `FORBIDDEN`, ohne das Gateway zu fragen; insbesondere startet der Hub keine
Läufe, keine Worker (`workboard.cards.dispatch`, `claim`) und ändert keine Konfiguration oder Cron-Aufträge.

Antwort: `{"id", "ok": true, "payload"}` oder `{"id", "ok": false, "error": {"code", "message"}}`. HTTP-Status: 200,
400 `INVALID_REQUEST`, 403, 404 `NOT_FOUND`, 405, 409 bei einem Konflikt (`workboard_conflict`), 413, 503
`UNAVAILABLE`, 504 `AGENT_TIMEOUT`, sonst 500.

Dazu fragt der Hub die anmeldefreien Sonden `GET <gateway>/healthz` und `/readyz` (alle 15 s).

**Chat-Kanäle (Telegram, WhatsApp, Matrix).** Der Agent hält die Sitzungen zu den Chat-Kanälen und ist der einzige
Absender; der Hub hat keine eigenen Zugänge. Zwei Dinge gehören dazu:

- Der Kopf jeder Lieferung (`bruecke.kanaele`) und `fyos.bruecke.status` nennen je Kanal `an` (in der Konfiguration des
  Gateways eingeschaltet), `ziel` (Adresse des Besitzers in der Umgebung gesetzt, `FYOS_APPROVER_*`) und `bereit`
  (beides). Nur Wahrheitswerte, nie die Adresse. Der Hub zeigt sie in `openclaw.zustand` (`kanaele`); die Abnahme des
  Installers prüft damit, ob der gewählte Kanal im Agenten aktiv ist.
- `fyos.kanal.mitteilen` sendet über die Werkzeug-Schnittstelle des Gateways (Schleife, Werkzeug `message`) an die
  bereiten Kanäle in der Reihenfolge Telegram, WhatsApp, Matrix; der erste, der zustellt, genügt (`kanal` wählt einen
  allein). Ohne bereiten Kanal oder wenn alle scheitern: 503 `UNAVAILABLE`. Aufrufer ist `os.mitteilen` mit
  `dringlichkeit: hoch`, wenn niemand an der Shell sitzt ([`NACHTARBEIT.md`](NACHTARBEIT.md)). Meldungen tragen weder
  Token noch Adresse.

**Wecken.** Ein Agent arbeitet von allein nur, wenn jemand mit ihm spricht oder ein Zeitplan läuft. Der **Wecker** im
Hub-Plugin (`mcp_hub/plugins/_wecker.py`) liest im Takt (Vorgabe 15 s) die Quellen des Hub und weckt ihn über die Brücke:

- Quellen: Vorgänge (neu, Zuständigkeit, Status, Kommentare; nur das Neue seit dem Ausgangsstand), Termine
  (`termin.gleich` in `vorlauf_min` Minuten, nur die Minuten), Postfach (`postfach.neu`, nur die Zahl), Dokumente
  (`dokumente.neu`, nur die Zahl) und frei benannte Ereignisströme (`wecken.strome`, jeder neue Eintrag wird ein
  Umschlag, `mcp_hub.umschlag`). Der Stand liegt im Hub-Speicher; die erste Runde einer Quelle weckt nie für Altes.
- Ziel: ein Vorgangsereignis weckt die **Sitzung dieses Vorgangs** (`agent:<id>:vorgang:<ID>`, OpenClaw legt sie beim
  ersten Mal an, alle Ereignisse eines Vorgangs landen im selben Verlauf), alles andere die Hauptsitzung
  (`agent:<id>:main`). Die Kennung `<id>` kommt aus der Konfiguration (`agent` im Plugin, `agentId` der Brücke, beide aus
  `fyos.yaml` gerendert), sonst aus `FYOS_AGENT`, sonst gilt `main`; kein fester Name im Code.
- Der Weckruf trägt Namen und Nummern, nie Inhalte; der Agent liest im Hub nach. Die Brücke weckt nur die Hauptsitzung
  und Vorgangssitzungen, nie Chat- oder Kanal-Sitzungen.
- Regeln (`wecken.regeln`, sonst die Vorgaben `vorgang`, `termin`, `eingang`, `dringend`): `thema`, `min_schwere`,
  `von`, `nicht_von` (eigene Spuren und der Akteur des Spiegels wecken nie: kein Echo), `ziel` (`vorgang` | `haupt`),
  `modus` (`jetzt` | `naechster`), `max_pro_stunde`. Flutschutz: `max_pro_minute` insgesamt (Vorgabe 10), Ereignisse
  desselben Ziels in einem Schlag werden ein Weckruf, Wartendes verfällt nach `max_alter_s` (Vorgabe 900) mit Vermerk,
  ein gescheiterter Weckruf wird dreimal wiederholt.
- `wecken: {aktiv: false}` schaltet den Wecker aus; `takt_grenzen.wecken` setzt Fenster und Tageslimit.

Ereignisse der Brücke zu einer Vorgangssitzung (Sitzung, Lauf, Modell, Werkzeug) tragen die Vorgangsnummer mit
(`vorgang`); der Sitzungsschlüssel bleibt gehasht.

### Laufprofile für isolierte Läufe

Ein Cron-Auftrag hat eine Werkzeugliste (`payload.toolsAllow`): fehlt sie oder steht `*` darin, darf der Lauf alles;
eine leere Liste heißt keine Werkzeuge (nur Antworten). Für Routinen ist beides selten richtig. Drei Profile
(`mcp_hub.plugins._laufprofile`, sichtbar mit `openclaw.profile`) geben jedem Lauftyp eine benannte Liste:

| Profil | Der Lauf darf | Zeitlimit |
|---|---|---|
| `lesen` | Arbeitsordner und Dateien lesen (`read`, `dir_list`, `file_fetch`), Gedächtnis, Workboard lesen, Web holen, im Hub suchen, erklären und Dateien listen | 300 s |
| `reflexion` | alles von `lesen`, dazu Hub-Werkzeuge (`hub__hub__call_tool`) und Ansichten (`hub__gui__*`, Apps), Karten anlegen, verknüpfen, kommentieren | 600 s |
| `melden` | alles von `reflexion`, dazu eine Nachricht senden (`message`) und Karten weiterbewegen | 600 s |

Schreibende Dateiwege (`write`, `edit`, `exec`, `file_write`) und `cron` stehen in keinem Profil; wer sie braucht, setzt
die Liste eines einzelnen Auftrags bewusst von Hand. Namen aus dem Hub tragen das Präfix `hub__` (Server) und dann den
Hub-Namen. `openclaw.auftrag_vorlage {profil, name, text, plan, sitzung?}` baut den Aufruf (`openclaw cron add … --tools …
--light-context --no-deliver`) und die Nutzlast; sie legt nichts an, denn die Brücke ruft `cron.add` nicht auf (siehe
Abschnitt 7, Gegenprobe). `openclaw.profile` zeigt zu den Profilen, welche Aufträge des Agenten welchem folgen
(`alle`, `keine`, `eigene`, `verwaltet`, `ohne Modell`) und nennt die eingeschalteten Aufträge ohne Profil.

### Gedächtnis

Der Agent erinnert sich auf zwei Wegen, und `openclaw.erinnern {frage, limit}` ist der eine Recall-Weg dafür: Die Frage
geht an das **Gedächtnis des Agenten** (OpenClaw `memory.search`: Notizen, Gesprächsauszüge, Traumbericht) und an die
**Dokumente des Hubs** (Dokumentenquelle, falls eingerichtet); die Ränge werden gemischt (Reciprocal Rank Fusion). Jeder
Treffer trägt Quelle, Verweis, Titel und einen kurzen Auszug. Zu jedem Weg gehört ein Messwert (`messung`: Dauer in
Millisekunden, Anzahl, Modus); ein ausfallender Weg ist ein Vermerk, kein Fehler. Kennzahlen:
`fyos_openclaw_erinnern_total{weg, ergebnis}`, `fyos_openclaw_erinnern_treffer_total{weg}`,
`fyos_openclaw_erinnern_dauer_ms{weg}`.

*Vektor oder Text.* Ohne Embedding-Dienst sucht das Gedächtnis im Text (`searchMode: fts-only`). Mit einem Dienst
(`FYOS_EMBED_URL`, `FYOS_EMBED_MODEL`, `FYOS_EMBED_KEY`; derselbe wie der des Hubs, OpenAI-kompatibel) rendert die Vorlage
von fyos-agent `memory.search.provider: openai-compatible`, und die Suche ist hybrid. Ohne Dienst setzt die Vorlage
ausdrücklich `provider: none`; sonst verlangte OpenClaw einen OpenAI-Schlüssel und hielte die Vektorsuche an
(„Vector search: paused“). Wechselt der Anbieter, baut OpenClaw den Index nicht von selbst neu auf:
`openclaw memory status --index --agent <id>`.

*Dreaming* (Kurzzeit-Einträge, Phasen light, rem, deep, Übernahme ins Langzeitgedächtnis) läuft in OpenClaw nachts;
`openclaw.gedaechtnis` zeigt Anbieter, Phasen mit nächstem Lauf, Zahlen und was `erinnern` gemessen hat, ohne die
Auszüge. *Active Memory* (ein Teilagent sucht vor jeder Antwort) schaltet `gedaechtnis.aktives_gedaechtnis` in `fyos.yaml`
ein; Vorgabe aus, weil es je Antwort einen Modellaufruf kostet.

### Lebt der Agent?

`openclaw.lebt {vorgang?}` beantwortet die Frage aus drei lesenden Gateway-Methoden: `last-heartbeat` (Ergebnis des
letzten Herzschlags), `sessions.list` (Sitzungen mit Lauf und Fehler) und `progressCard.get` (die Fortschrittskarte, die
der Agent in einer Sitzung pflegt). Das Urteil ist grob: **gestört**, wenn das Gateway nicht bereit ist oder der jüngste
beendete Lauf scheiterte (oft: das Modell antwortet nicht; ein älterer Fehler bleibt nicht stehen, sobald danach ein Lauf
gelang), **läuft**, wenn ein Lauf aktiv ist, sonst **bereit**; dazu die Gründe im Klartext. Zu jeder Vorgangssitzung
(`agent:<id>:vorgang:<ID>`, jüngste zuerst, höchstens zehn) kommt die Karte: Revision, Schrittzahlen, aktueller Schritt und
eine gekürzte Notiz; mit `vorgang` nur die Sitzung dieses Vorgangs. Die Vorlage von fyos-agent erlaubt dem Agenten
`progress_card`. Der Heartbeat der Vorlage ist aus (`every: 0m`): Ein Zeitimpuls erfindet keine Arbeit, der Agent
wacht durch den Wecker; der „Herzschlag“ in der Antwort ist deshalb das Ergebnis des letzten Weckrufs.

Zusagen und Standing Intents sind Vorgänge (Skill `zusagen` in fyos-agent): Zeit ist ein geplanter Auftrag mit
Laufprofil, ein Ereignis ein Standing Intent mit der Vorgangsnummer in der Beschreibung. OpenClaw leitet seit 2026.8
keine Zusagen mehr aus Gesprächen ab; es gibt keine zweite Tabelle.

### Optionale Dienste: Weiche, Reranker, Mund, Ohr

Vier Dienste sind nie Pflicht. Fehlt die Adresse oder fällt der Dienst aus, arbeitet alles wie ohne ihn (Fail-open);
`openclaw.dienste` zeigt je Dienst eingerichtet, erreichbar (kurze Probe ohne Nutzdaten), Zähler und letzten Fehler, dazu
was das Gateway über Sprachausgabe (`tts.status`) und Weckwort-Weiterleitung (`voicewake.routing.get`) meldet.

| Dienst | Adresse (Hub: `dienste.<name>_url` oder Umgebung) | Wirkung |
|---|---|---|
| Weiche | `FYOS_WEICHE_URL`: `POST /entscheiden` mit `{"umschlag": {...}}`, Antwort `{"wecken": bool, "grund": "..."}` | entscheidet vor dem Wecken, nur für Weckregeln mit `weiche: true`; sieht Thema, Schwere, `von`, Verweis, nie Inhalte; „ruhig“ steht im Weckverlauf (`ergebnis: ruhig`) und zählt in `zaehler.ruhig` |
| Reranker | `FYOS_RERANK_URL`: `POST /rerank` mit `{"query", "documents"}`, Antwort `{"results": [{"index", "score"}]}` (auch eine nackte Liste) | ordnet die Treffer von `openclaw.erinnern` neu (`rerank_punkte`), eigener Messwert `messung.rerank` |
| Mund | `FYOS_MUND_URL` (Agent: `mund.*` in `fyos.yaml`), OpenAI-kompatibel | Sprachausgabe des Agenten (`tts.providers.openai`); der Hub prüft nur die Erreichbarkeit |
| Ohr | `FYOS_OHR_URL` (Agent: `ohr.*` in `fyos.yaml`), OpenAI-kompatibel | Spracheingabe des Agenten (`tools.media.models`, Fähigkeit `audio`); der Hub prüft nur die Erreichbarkeit |

Eine Weiche zu fragen kostet eine Anfrage je Ereignis mit passender Regel (Zeitgrenze 2 s); sie kann das Wecken nur
unterdrücken, nie auslösen, und der Flussschutz des Weckers gilt unverändert. Mund und Ohr schreibt die Vorlage von
fyos-agent in die Konfiguration des Agenten; ohne Adresse bleibt die Sprachausgabe aus (`tts.auto: off`).

## 4. Vorgänge und Workboard

Der Vorgangs-Vertrag ist der des Vorgangs-Dienstes (`fyos-agent/plugins/fyos-freigabe-chat/board.mjs`):
`GET /tickets?status=&limit=`, `GET /tickets/{id}`, `POST /tickets`, `POST /tickets/{id}/comments` `{actor, text}`,
`PATCH /tickets/{id}` `{status, expected_status?, actor?, title?, description?, priority?}`. Wo vorhanden, dazu
`GET /tickets/{id}/history?limit=` (neueste zuerst, `{history: [{ts, event, actor, detail}]}`); im Workboard sind
das die Kommentare der Karte.

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

**Andere Plugins im Hub** (Leitstand, Zentrale, „Braucht dich“) tragen keine Adresse fest ein, sondern fragen
`mcp_hub.vorgaenge.quelle()` (Beispiel in `ERWEITERN.md` §2.13). Steht beim Plugin `openclaw` ein Vorgangs-Dienst,
meldet es ihn dort samt Kopfzeile an, und alle fragen denselben Dienst, auch wenn er nur in seiner `config` steht und
auch, solange die Kopplung ruht (ohne `FYOS_AGENT_URL`). Als Ablage
meldet es sich selbst an: Die Plugins lesen und beantworten Vorgänge dann prozessintern im Workboard, ohne Umweg über
HTTP. Ohne beides bleiben ihre Listen leer und Schreiben meldet „nicht eingerichtet“.

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
| `FYOS_VORGAENGE_KOPF` | `vorgaenge_kopf` | eine Kopfzeile `Name: Wert`, die jeder Aufruf beim Vorgangs-Dienst mitschickt (Spiegel und Plugins), z. B. für eine Anmeldung des Dienstes; leer = keine |
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
| `openclaw.wecken` `{text, vorgang?, modus?}` | den Agenten wecken, mit `vorgang` in der Sitzung dieses Vorgangs (schreibend) |
| `openclaw.vorgang_senden` `{vorgang, text, schluessel?}` | Nachricht in die Sitzung eines Vorgangs (schreibend) |
| `openclaw.ereignisse` `{limit}` | der Wecker: Quellen, Regeln, Zähler, Wartendes, letzte Weckrufe |
| `openclaw.lebt` `{vorgang?}` | Urteil (bereit, läuft, gestört) mit Gründen, letzter Herzschlag, Vorgangssitzungen mit Fortschrittskarte |
| `openclaw.erinnern` `{frage, limit?}` | ein Recall-Weg: Gedächtnis des Agenten und Dokumente des Hubs, gemischt, mit Messwert je Weg |
| `openclaw.gedaechtnis` | Anbieter (Vektor oder Text), Dreaming, bisherige Messung von `erinnern` |
| `openclaw.dienste` `{probe?}` | optionale Dienste (Weiche, Reranker, Mund, Ohr): eingerichtet, erreichbar, Zähler; Sprachausgabe und Weckwort laut Gateway |
| `openclaw.profile` | Laufprofile mit Werkzeuglisten und welche Cron-Aufträge welchem folgen |
| `openclaw.auftrag_vorlage` `{profil, name, text, plan, sitzung?}` | Befehl und Nutzlast für einen Auftrag mit Profil (legt nichts an) |
| `mcp.zeitplan` `{quelle}` | Takte aller Hub-Plugins und die Cron-Aufträge des Agenten |

`/metrics` (Prometheus-Text): `fyos_openclaw_gateway_lebt`, `fyos_openclaw_gateway_bereit`,
`fyos_openclaw_bruecke_alter_s`, `fyos_openclaw_bruecke_verworfen`, `fyos_openclaw_ereignisse_total{art}`,
`fyos_openclaw_werkzeugaufrufe_total{ergebnis}`, `fyos_openclaw_modellaufrufe_total{modell, ergebnis}`,
`fyos_openclaw_laeufe_total{ergebnis}`, `fyos_openclaw_sitzungen_total{phase}`,
`fyos_openclaw_cron_laeufe_total{ergebnis}`, `fyos_openclaw_karten{board, status}`, `fyos_openclaw_rpc_fehler_total`,
`fyos_openclaw_abgewiesen_total`, `fyos_openclaw_wecken_total{ergebnis}`, `fyos_openclaw_wecken_wartend`, dazu `fyos_zeitplan_*{plugin="openclaw", quelle="openclaw"}` je Cron-Auftrag. Takte mit
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

## 9. Soll: 100 % Brücke

Die Kopplung ist Kern des Produkts: Wer FYOS mit OpenClaw betreibt, soll jedes allgemeine Paar zwischen Backend und
Agent über die Brücke bekommen, ohne eigenen Zusatz. Persönliche Dienste (Haus, Kameras, Konten …) bleiben Plugins und
hängen sich an dieselben Anschlüsse. Stand dieser Zuordnung: 11.10.2026, gemessen am Testserver (OpenClaw 2026.9, ein
Agent `main`, Modell nicht erreichbar, kein Chat-Kanal, Vorgänge im Workboard).

**Klassen.** (a) allgemein, gehört in die Brücke; (b) persönlicher Dienst, gehört in ein Plugin; (c) bewusst nicht.
**Ist** am Testserver: `g` gekoppelt und am Testserver gelaufen, `ga` gekoppelt, aber der Dienst oder die Quelle fehlt am
Testserver (Anschluss und Vertrag gegen eine Attrappe geprüft), `t` teilweise, `f` fehlt. **Schritt** verweist auf die
Schrittliste unten. Stand der Spalte „Ist“: nach der Abnahme vom 11.10.2026 (Abschnitt 9.3); die Schritte in der letzten
Spalte sind die, die das Paar gekoppelt haben.

| Nr. | Paar (FYOS ↔ OpenClaw) | Klasse | Ist | Schritt |
|---|---|---|---|---|
| 1 | Ereignisbus → Agent (Hooks, Wake) | a | g | B3, B4 |
| 2 | Heartbeat: Konfiguration und Anlass | a | g | B3 |
| 3 | Wake-Ereignis mit Flutschutz | a | g | B3, B4 |
| 4 | Läufer, die auf Ströme warten (Cron `stream`) | b | – | ersetzt durch 1 |
| 5 | Modelllose Aufgaben (Takt im Hub statt Cron-Nutzlast) | a | g | – |
| 6 | Cron/Wake an eine feste Sitzung binden | a | g | B5 |
| 7 | Gesprächssitzung (Hauptsitzung, Kanäle) | a | g | – |
| 8 | Sitzung je Vorgang | a | g | B5 |
| 9 | Agenten und Team (Kennung aus der Konfiguration) | a | g | B5 |
| 10 | Vorgänge ↔ Workboard (Spiegel, Ablage) | a | g | – |
| 11 | `memory_search` ↔ Embedder | a | ga | B7 |
| 12 | Wissensspeicher des Hubs als Recall | a | ga | B7 |
| 13 | Dreaming: Stand sichtbar, Ergebnis nutzbar | a | g | B7 |
| 14 | Active Memory | a | g | B7 |
| 15 | Wiki ↔ `memory-wiki` | c | – | Doppelführung (Abschnitt 9.2) |
| 16 | Zusagen und Standing Intents an Vorgänge | a | g | B8 |
| 17 | Hub als MCP-Server des Agenten | a | g | – |
| 18 | Sidecar-Dienste des Besitzers (Schreibwege) | b | – | Plugin |
| 19 | MCP Apps (`ui://`) | a | ga | B6 |
| 20 | Laufprofile für isolierte Läufe | a | g | B6 |
| 21 | Freigaben im Chat | a | ga | B5 |
| 22 | Sandbox-Backends | c | – | Der Container ist der Käfig |
| 23 | Eigene OpenClaw-Plugins (Meldebudget, Priorität …) | a | g | – |
| 24 | Modelle und Ausweichweg | a | g | – |
| 25 | Reflexmodell als Weiche („wecken?“) | a | ga | B9 |
| 26 | Reranker | a | ga | B9 |
| 27 | Mund (Sprachausgabe) | a | ga | B9 |
| 28 | Ohr (Sprache → Agent) | a | ga | B9 |
| 29 | Voicewake-Routen (Raum → Agent) | a | g | B9 |
| 30 | Kameras und Erkennung | b | – | Plugin |
| 31 | Ereignisumschlag | a | g | B2 |
| 32 | Vorgangs-Push (Zuweisung weckt den Agenten) | a | g | B4 |
| 33 | Vorgangs-Ereignisse (neu, Kommentar, Zuweisung, Status) | a | g | B4 |
| 34 | Haus und Geräte | b | – | Plugin |
| 35 | Kalender: „Termin gleich“ | a | ga | B4 |
| 36 | Mail: neue Nachricht, stumme Quelle | a | ga | B4 |
| 37 | Dateien (`file-transfer`) | a | g | B6 |
| 38 | Craft-Anwendungen | b | – | Plugin |
| 39 | Dokumente: neues Dokument | a | ga | B4 |
| 40 | Kanal Matrix und Telegram | a | ga | B5 |
| 41 | Kanal WhatsApp | a | ga | B5 |
| 42 | „Lebt der Agent?“ (Heartbeat-Ergebnis, Fortschrittskarten) | a | g | B8 |
| 43 | Agentenkennung ohne feste Namen | a | g | B5 |

**Zahlen.** 43 Paare: 36 allgemein (a), 5 persönlich (b), 2 bewusst nicht (c). Vor der Arbeit waren von den 36
allgemeinen 6 gekoppelt, 11 teilweise, 19 fehlten; nach der Abnahme sind es 36 gekoppelt: 23 am Testserver gelaufen (`g`),
13 gegen eine Attrappe geprüft, weil der Dienst am Testserver fehlt (`ga`). „Gekoppelt“ heißt: Die Brücke bietet den
Anschluss, Tests sind grün, und eine Rundprobe am Testserver ist gelaufen. Wo ein Dienst fehlt (Reflexmodell,
Reranker, Stimme), gilt der Anschluss samt Vertrag und Probe gegen eine Attrappe als gekoppelt; der Dienst selbst ist
optional.

### 9.1 Schrittliste

| Nr. | Schritt | Prüfung | Fertig, wenn |
|---|---|---|---|
| B1 | Zuordnung (dieser Abschnitt) | Doku-Prüfung, Sauberkeitsprüfung | Abschnitt gemergt |
| B2 | Gemeinsamer Umschlag im Kern: `mcp_hub.umschlag` (Normalisierer, Ereignisarten, Weckregeln, Sitzungsschlüssel) | Tests je Familie, nur Standardbibliothek | Hub und Brücke sprechen dasselbe Format |
| B3 | Brücke: `fyos.wecken` (Systemereignis plus Heartbeat-Anforderung für eine Sitzung) und `fyos.bruecke.status` mit Agentenkennung; Erlaubnisliste um lesende Methoden erweitert | Tests der Brücke, Grenze bleibt 403 für alles andere | Ein Aufruf über die Route weckt eine Sitzung |
| B4 | Hub: Wecker. Leser für Ströme und Adapter (Vorgänge, Termine, Postfach, Dokumente) erzeugen Umschläge; Weckregeln aus der Konfiguration; Flutschutz; Werkzeuge `openclaw.wecken`, `openclaw.ereignisse` | Tests je Adapter, Flutschutz; am Testserver: Kommentar an einem Vorgang → Agent läuft, Zeit gemessen | Kommentar bis Laufbeginn unter 60 s |
| B5 | Sitzung je Vorgang: `agent:<id>:vorgang:<ID>`, `fyos.vorgang.senden`, Weckregel mit Vorgang, Agentenkennung aus der Konfiguration überall, Kanal-Stand im Zustand | Tests; am Testserver: zwei Vorgänge, zwei getrennte Sitzungen | Jeder Vorgang hat seine Sitzung, kein fester Agentenname im Code |
| B6 | Laufprofile (`lesen`, `reflexion`, `melden`) als Daten und Cron-Hilfe; Datei-Werkzeuge und Apps im Profil | Test der Profile; Probelauf eines isolierten Auftrags mit Ordnerliste | Jeder Lauftyp hat eine dokumentierte Werkzeugliste |
| B7 | Gedächtnis: Embedder-Weg in der Vorlage, `openclaw.erinnern` (Recall aus `memory.search` und Wissensspeicher), Dreaming-Stand, Active Memory schaltbar | Tests; `openclaw memory status` ohne „Vector search: paused“ | Genau ein Recall-Weg mit Messwert |
| B8 | Lebendigkeit: `openclaw.lebt` (Heartbeat-Ergebnis, Fortschrittskarten je Vorgangssitzung), Skill für Standing Intents an Vorgänge | Tests; Karte zu einem Vorgang sichtbar | Je Baustein „genutzt“ oder „aus“ mit Grund |
| B9 | Optionale Dienste: Weiche (`entscheiden`), Reranker, Mund und Ohr als angemeldete Dienste mit Vertrag; Voicewake-Routen lesbar | Tests gegen Attrappen | Anschluss und Vertrag stehen, ohne Dienst bleibt alles still |
| B10 | Abnahme: je Paar eine Rundprobe am Testserver; Zahlen vorher/nachher | Protokoll im Bericht | 36 von 36 gekoppelt |

### 9.2 Nicht gekoppelt

- **Wiki ↔ `memory-wiki` (15):** Der Hub hat ein Wissensmodell; ein zweites Wiki im Agenten wäre eine Doppelführung.
  Der Agent liest das Wiki des Hubs über `skills` und die Wissenswerkzeuge.
- **Sandbox (22):** Der Container ist der Käfig; die Grenze liegt in Rechten, Netz und Hub, nicht in einer Sandbox
  des Agenten.
- **Zusagen aus Gesprächen (Teil von 16):** OpenClaw hat die abgeleiteten Zusagen mit 2026.8.1 entfernt. Eine Zusage
  ist in FYOS ein Vorgang; es gibt keine zweite Tabelle dafür.


### 9.3 Abnahme am Testserver (11.10.2026)

Hub und Agent liefen mit den Ständen von B2 bis B9 (OpenClaw 2026.9.7, ein Agent `main`, kein Chat-Kanal, kein
Embedding-, Weichen-, Rerank-, Mund- oder Ohr-Dienst). Die Proben liefen durch die Brücken-Route und die Werkzeuge des
Hubs; Testdaten (Karten, Sitzungen, Cron-Auftrag) wurden danach entfernt.

| Probe | Ergebnis |
|---|---|
| Kommentar an einem Vorgang (Paare 1, 3, 6, 8, 31, 32, 33) | Weckruf nach rund 15 s in `agent:main:vorgang:<ID>`, zwei Vorgänge, zwei getrennte Sitzungen; der Agent las die Karte und kommentierte sie |
| `openclaw.lebt` (42) | Sitzung des Vorgangs „läuft“, danach „bereit“ oder „gestört“ mit Grund aus dem letzten Lauf; Herzschlag, Sitzungszahl, Wecker-Zähler |
| `openclaw.profile` und Auftrag mit Profil `lesen` (20) | `cron add --tools …` angelegt, Hub ordnet ihn dem Profil zu (22 Werkzeuge), danach entfernt |
| `openclaw memory status` (11, 13, 14) | Anbieter `none` ausdrücklich, kein „paused“; Dreaming sichtbar; Active Memory als Eintrag vorhanden, aus |
| `openclaw.erinnern` (12) | Treffer aus dem Gedächtnis (Textsuche), Messwert je Weg; Dokumentenweg „nicht eingerichtet“ |
| Skill `zusagen`, `progress_card`, `intent` (16) | Skill „ready“, beide Werkzeuge in der Erlaubnisliste des Agenten |
| `openclaw.dienste` (25 bis 29) | ohne Adressen „alles arbeitet ohne sie“; `tts.status` und `voicewake.routing.get` des Gateways gelesen (0 Routen) |
| Gerenderte Konfiguration mit Mund und Ohr | besteht `openclaw config validate` im Pod |

Nicht am Testserver gelaufen, sondern gegen Attrappen geprüft (`ga`): Vektorsuche (kein Embedding-Dienst), Dokumentenweg
von `erinnern`, Weiche, Reranker, Mund und Ohr (kein Dienst), Termin-, Postfach- und Dokumentenquelle des Weckers (keine
Quelle), Chat-Kanäle samt Freigabe im Chat (kein Kanal) und Apps im Agenten (`ui://`, keine Oberfläche). Ebenso
unbewiesen bleibt, dass ein Lauf mit Profil nur die erlaubten Werkzeuge sieht: OpenClaw setzt `toolsAllow` durch; der Hub
kann es nicht gegenprüfen. Die Fortschrittskarte (`progress_card`) war am Testserver noch nie gesetzt; gelesen wird sie
über `progressCard.get`.
