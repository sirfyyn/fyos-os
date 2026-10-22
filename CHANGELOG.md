# Änderungen

Alle nennenswerten Änderungen an FYOS stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/). Die Zahlen in Klammern sind die Nummern der Pull Requests.

Eine Version gilt für das ganze Paket: Oberfläche (`web`), Hub (`fyos-hub`) und Installer (`fyos-install`) tragen
dieselbe Nummer. Der Agent (OpenClaw mit den FYOS-Plugins) kommt aus dem Schwester-Repo
`fyos-agent` und wird mit demselben Tag veröffentlicht; dessen Änderungen
stehen in dessen `CHANGELOG.md`.

## [Unveröffentlicht]

## [0.1.3] – 2026-10-22

### Behoben
- „Rückgängig“ nach dem Schließen: Die Karte oben rechts erschien in 0.1.2 nicht, weil die Shell der Mitteilungsliste ein eigenes
  Signal statt der geteilten Karte gab. Sie liest jetzt dieselbe Karte wie die Brücke.

## [0.1.2] – 2026-10-22

### Neu

- **Räume in der Shell.** Eine Räume-Leiste mit acht Räumen (Gespräch, Sammlung, Atelier, Vorhaben, Büro, Zuhause,
  Betrieb, Einstellungen). Jeder Raum zeigt nur, was die eingerichteten Plugins über den Hub liefern; ohne Plugin steht
  dort „Noch nicht eingerichtet.“ (#62).
- **Tapeten, Rückgängig, Einrasten.** Eigene Tapete je Bildschirm, „Rückgängig“ nach dem Schließen eines Fensters oder
  Bildschirms, Fenster einrasten (Tasten, Randzonen mit Vorschau), Vollbild-Bildschirm, ein Bildschirm hoch statt endlos
  und „Ansicht gerade rücken“ (#62).
- **Griffe, Fähigkeiten, Werkzeuge.** Griffe im Start (das Hub-Tool `griffe.liste`), Fähigkeiten-Schalter in der
  Menüleiste, App-Werkzeuge (`App.werkzeug`) mit einem gemeinsamen Werkzeug-Register, Ton-Modus und Vorlesen, die
  Brücke zum Agenten mit Lage und Werkzeugen (#62).
- **Nachrichten in FYOS lesen.** `lesen.artikel` und die Ansichtsvorlage `artikel` (`gui.bauen`) zeigen einen Artikel
  zum Lesen in der Shell (#58).
- **Tapeten im Hub merken.** Die gewählte Tapete der Shell folgt dem Nutzer über Geräte hinweg (#57).
- **Eine Ansicht je Kachelgröße.** Hub-Apps und Kern-Apps zeigen in kleinen und großen Kacheln jeweils eine eigene,
  passende Ansicht (`blick`, `kompakt`, `normal`, `weit`) (#59, #60).
- **Agenten-Runner: Arbeitsbereiche und Quelle `stimme`.** Das Plugin `agent` meldet und liest Arbeitsbereiche und trägt ein
  Feld im Eingang; neue Quelle `stimme` (#51, #52).

- **Desktop: eigener Desktop für den Agenten (`ziel`).** Jedes Werkzeug des Plugins `desktop` nimmt `ziel: mensch|agent`.
  `agent` ist ein zweiter, kopfloser Desktop des Agenten: dort braucht er keine Freigabe, der Mensch sieht in der App „Desktop“
  zu (Umschalter, Live-Ansicht mit JPEG, etwa drei Bilder je Sekunde; `desktop.bild` nimmt dafür `format` und `qualitaet`) und kann mit `desktop.uebernehmen` übernehmen, dann ruht der Agent. Fensteradressen
  dort heißen `g5`. Neu auch die Werkzeuge der Eingabe (`klick`, `tippen`, `taste`, `scrollen`); auf dem Desktop des Menschen
  gelten sie nur während einer Freigabe, die allein er am Rechner setzt (`docs/ERWEITERN.md` §2.19).
- **App „Desktop“ in der Shell (Plugin `desktop`).** `desktop.zeigen` öffnet eine Fläche mit Lage, offenen Fenstern und
  Startern des Rechners, alle zehn Sekunden frisch, auf Wunsch mit Bildschirmfoto. Jedes offene Fenster ist ein Ding vom Typ
  `desktop-fenster` (Kennung = Fensteradresse, lesendes Werkzeug `desktop.fenster_lesen`): man zieht es auf eine andere App
  oder auf den Agenten. „Nach vorn“, „Schließen“ und Starten laufen wie überall über Plan und „Ja“.
- **Agenten-Runner über den Hub (Plugin `agent`).** `POST|GET /hub/agent/eingang`, `POST /hub/agent/melden` und
  `POST /hub/agent/alarm` (Alertmanager, entprellt) verbinden einen Agenten-Runner ohne Redis-Zugang mit Eingang
  und Ausgang. Optional mit Quellen-Tokens (`FYOS_AGENT_TOKENS`): die Quelle folgt dem Token, `FYOS_AGENT_STRENG`
  schließt ohne Token alles (`docs/HUB-VERTRAG.md`, Abschnitt „Agenten-Runner“).
- **Plugin `desktop`: der Desktop eines Rechners als Werkzeuge.** `desktop.lage`, `desktop.fenster`, `desktop.starter` und
  `desktop.bild` (Bildschirmfoto) lesen; `desktop.starten`, `desktop.fokus` und `desktop.schliessen` ändern und brauchen
  Plan und `bestaetigt: true`. Gestartet wird nur, was der Dienst auf dem Desktop unter `starter` freigibt, nie ein freier
  Befehl; Fenster werden nur mit der Adresse eines offenen Fensters angesprochen. Dieselbe Gegenstelle wie „Öffnen mit“
  (`config: {gegenstelle, token_env}` oder `FYOS_OEFFNEN_GEGENSTELLE`/`FYOS_OEFFNEN_TOKEN`); ohne sie „nicht eingerichtet“
  (`docs/ERWEITERN.md` §2.19).
- **Dateien: „Öffnen mit“.** Zu einer PDF-, Dokument- oder Tabellendatei zeigt die Vorschau Knöpfe für Programme auf einem
  Rechner mit Bildschirm (Papers, WordCraft, GridCraft auf dem Desktop-Rechner); ein Klick fragt nach und lädt die Datei dorthin und
  startet das Programm im Fenster. Neu: `dateien.oeffnen_programme` und `dateien.oeffnen_mit`, eingerichtet mit
  `oeffnen: {gegenstelle, token_env}` am Plugin (`docs/ERWEITERN.md` §2.17); ohne Gegenstelle bleibt alles wie bisher.
- Hub: `FYOS_AGENT_CA` (Pfad zu einer CA-/Zertifikatsdatei) und `FYOS_AGENT_TLS_PRUEFEN=false` für ein Gateway mit
  selbstsigniertem Zertifikat (Konfig `agent_ca`, `agent_tls_pruefen`); Vorgabe bleibt prüfen. Gilt für Gateway-Aufrufe
  und den gespiegelten Vorgangs-Dienst.

- **Plugins live nachladen.** Mit `plugins_live: true` und `plugins_live_quellen` (oder `FYOS_PLUGINS_LIVE_QUELLEN`) ersetzen
  geänderte Plugin-Dateien einer Quelle die im Bild: beim Start, bei jedem neuen Commit der Quelle und mit
  `POST /hub/plugins/neu-laden`, atomar und ohne Neustart. `/hub/health` zeigt je Plugin `live` (`docs/ERWEITERN.md` §10.5).
- **Offene Clients erfahren Änderungen der Werkzeugliste.** `liste_melden` meldet sie über `subscriptions/listen`;
  `mcp_sitzungen` bietet dasselbe Clients mit altem Handshake (zustandsbehaftete Sitzungen, nur mit einer Hub-Replika).
- **Gebaute Ansichten in einer Dateiablage.** Das Plugin `gui` legt mit der Config `daten` (oder `FYOS_GUI_DATEN`) jede
  Ansicht als `<daten>/gui/g-….json` ab, etwa auf einer gemeinsamen Netzfreigabe. Das Dateiformat blieb gleich, schon
  abgelegte Ansichten bleiben beim Umstieg erhalten. Ohne die Angabe gilt weiter `mcp_hub.kv`.
- **Suche über alles in ⌘K.** Das Startfeld findet neben Flächen auch Vorgänge, Mail, Dateien und Notizen, gruppiert
  nach Quelle, und sagt, welche Quelle nicht eingerichtet war. Plugins melden weitere Quellen mit
  `suche_alles.registriere_quelle` an (`docs/ERWEITERN.md` §2.18).
- **Arbeits-Apps „Vorgänge“, „Mail“ und „Termine“** mit den ersten Übergaben: Mail wird zum Vorgang (Betreff, Auszug,
  Quelle), ein Vorgang hängt Info mit Verweis als Kommentar an einen anderen, ein Vorgang wird zum Termin. Geschrieben
  wird nur nach Plan und Bestätigung. Ohne eingerichtete Quelle zeigen die Apps „nicht eingerichtet“.
- **Notiz an den Agenten ziehen** nimmt den Inhalt als Kontext mit (gekürzt, als Fremdinhalt gekennzeichnet).
- **Stand des Repo-Klons in Skills und Werkstatt.** `skills.suchen`/`lesen` und `werkstatt.suchen` nennen `stand`
  (Commit und Datum des Klons, sonst `null`); das Skill-Verzeichnis liest bei neuem Commit neu. Frist des
  Zwischenspeichers: `FYOS_KLONSTAND_TTL_S` (Vorgabe 60).
- **Eigene Installationen konfigurieren Skills und Werkstatt.** Skills: `nur_sichtbar` blendet Skills einer Quelle aus der
  Suche aus (lesbar bleiben sie). Werkstatt: `orte`, `im_hub`, `env_weg` und `favoriten_schluessel`.

### Geändert

- Shell und Werkstatt sind dichter: kompaktere Abstände in Fenstern, knapper Kopf und Dock, breitere Liste mit einzeiligem
  Zweck (#53, #56).
- App-Fenster melden zuerst „braucht länger“ und zeigen einen Fehler erst nach 30 Sekunden; das Fenster ist bereit beim
  Handschlag statt bei der ersten Höhe (#54, #55).
- Ein Ding mit angemeldeter Übergabe lässt sich auch auf das Fenster seiner eigenen App ziehen.

## [0.1.1] – 2026-10-11

Vorbereitet: Der Tag `v0.1.1` und die Veröffentlichung folgen nach dem Ablauf in [`RELEASE.md`](RELEASE.md).

### Neu

- **Installer nimmt veröffentlichte Bilder.** Ohne eigene Registry zieht `fyos-install` die fertigen Bilder von
  `ghcr.io/sirfyyn` im Stand seiner eigenen Version. Du musst nichts selbst bauen, um FYOS auszuprobieren (#6). <!-- sauber: ok -->
- **Stufe je Fähigkeit wählbar.** Vorgänge, Termine, Postfach, Post und Dokumente gibt es in einer Grundstufe (ohne
  eigenen Dienst, zum Beispiel direkt an einen CalDAV-Kalender oder ein IMAP-Postfach) und einer Ausbaustufe (mit eigenem
  Dienst). Du wählst im Assistenten, in der Textoberfläche oder mit `--stufe`, oder lässt die Vorgabe nach Bauart gelten:
  Docker Compose nimmt die Grundstufe, Kubernetes die Ausbaustufe (#34).
- **Chat-Kanäle im Installer.** Matrix, Telegram und WhatsApp lassen sich beim Installieren auswählen. Die Abnahme
  prüft danach, ob jeder eingeschaltete Kanal wirklich läuft. Fehlt ein Zugangswert, startet FYOS trotzdem, und der
  Installer sagt, was noch fehlt (#21).
- **Baustein FYOS Post im Installer-Katalog.** Mails senden gehört jetzt zur Auswahl (#13).
- **Termine, Postfach und Dokumente im Hub.** Drei neue Quellen für den Leitstand: Kalender über CalDAV oder ICS,
  Postfach lesen über IMAP, Dokumente aus Paperless-ngx oder einer Ablage. Ist nichts eingerichtet, sagt das ehrlich
  „nicht eingerichtet“, statt eine leere Liste zu zeigen (#7, #10, #14).
- **Vorgänge für Plugins.** Plugins greifen über `mcp_hub.vorgaenge` auf Vorgänge zu, der Verlauf eines Vorgangs kommt
  auch aus dem Workboard des Agenten (#3, #4).
- **Dateien.** Ein neues Hub-Plugin samt App „Dateien“: Ablage in einem Ordner, mit Papierkorb und früheren Fassungen
  (#20).
- **Gebaute Ansichten.** Das Plugin `gui` baut Ansichten aus Vorlagen (Kennzahlen, Balken, Verlauf, Tabelle, Ablauf und
  mehr), dazu kommt die Vorlage `diagramm` für Diagramme. Der Mod `fyos-ansicht` öffnet sie im Panel von Claude Code
  (#8, #17).
- **Ansichten in der Shell.** Die Shell reicht gebaute Ansichten unter `/hub/gui/<id>` durch, nur lesend. Ein Link
  zu einer Ansicht öffnet sich im Browser und im Panel (#9).
- **Übergaben zwischen Apps.** Dinge aus einer App lassen sich auf eine andere App ziehen und ablegen (#22).
- **Anwendungen statt Widgets.** Apps öffnen groß, lassen sich maximieren und füllen auf Wunsch den ganzen Bildschirm
  (#24).
- **Nachtarbeit.** Der Agent kann über `os.mitteilen` etwas für später vormerken; die Meldung wartet bis zu 24 Stunden
  und erscheint morgens in der Shell. Dazu gibt es einen Nachtauftrag „Notizen ordnen“, der den Notizzettel im Hub liest
  (#19, #25).
- **Dringende Mitteilung über den Chat-Kanal.** Der Agent erreicht den Besitzer bei Wichtigem direkt über den
  eingerichteten Kanal (#21).
- **Kopplung an den Agenten (OpenClaw).** Der Hub nimmt die Ereignisse des Agenten in einem festen Umschlag an und
  kennt jetzt:
  - Wecken und Vorgangssitzungen: der Hub kann den Agenten zu einem Vorgang wecken, jede Sitzung gehört zu genau einem
    Vorgang (#27, #28),
  - Laufprofile für abgeschottete Läufe (lesen, nachdenken, melden) (#29),
  - einen einzigen Weg zum Erinnern (`erinnern`) und den Stand des Gedächtnisses (#30),
  - `openclaw.lebt` mit Herzschlag, Sitzungen und Fortschrittskarte je Vorgang (#31),
  - optionale Dienste für Weiche, Reranker, Mund und Ohr (`openclaw.dienste`) (#32),
  - eine Abnahme am Testserver und eine Tabelle, welches Verhalten des Ursprungssystems nachgebaut ist (#26, #33).
- **Nachbau-Plan.** `docs/NACHBAU.md` zeigt je Fähigkeit, wie weit der Nachbau mit eigenen Konten und Diensten ist
  (#11, #12, #15).

### Geändert

- Installer 0.1.1 und Hub 0.1.1 tragen die Nummer des Pakets. Das Agent-Bild wird mit dem Tag `v0.1.1` gezogen
  (zuvor `v0.1.0`).
- Auf Kubernetes nimmt der Installer die Ausbaustufe als Vorgabe, auf Docker Compose die Grundstufe (#34).
- Die Gitea-CI läuft zusätzlich täglich nach Zeitplan gegen die neuesten Pakete aus dem Index, auch ohne neuen Commit
  (#16). Die Prüfung auf Geheimnisse (gitleaks) kennt eine eng gefasste Ausnahme für gepinnte Prüfsummen (#18).

### Behoben

- Kubernetes: Das Hub-Deployment mit Strategie `Recreate` setzt `rollingUpdate` jetzt ausdrücklich auf null, damit sich
  ein bestehendes Deployment ohne Fehlermeldung umstellen lässt (#23).
- Ein eingetragener Vorgangs-Dienst gilt jetzt auch, solange die Kopplung zum Agenten ruht (#5).

## [0.1.0] – 2026-10-10

Erste Veröffentlichung von FYOS (For Your Own Sake).

### Neu

- **Desktop-Shell** (`web`, Astro mit SolidJS): Fenster, Dock, Kacheln und Menüleiste im Browser. Sie zeigt Apps der
  Hub-Plugins ohne eigenen Code und hat den Agent-Chat im Fenster.
- **MCP-Hub** (`fyos-hub`): MCP unter `/mcp`, REST unter `/hub/*`, Plugins per Entry-Point, Anmeldung über OIDC,
  Takte mit Tageslimit und Zeitfenster, `/metrics`. Die Kopplung an OpenClaw ist ein eigenes Plugin.
- **Installer** (`fyos-install`): Web-Assistent, Textoberfläche und Kommandozeile. Er erklärt jeden Baustein mit Bildern,
  erzeugt Docker Compose oder Kubernetes und prüft nach der Installation, auf welcher Reifestufe jede Schicht steht.
- **Agent** (Schwester-Repo `fyos-agent`): OpenClaw mit Verhaltens-Plugins, Vorlagen und einem Vertrag für Freigaben.
- **Anleitung zum Erweitern** (`docs/ERWEITERN.md`): eigene Plugins, Oberflächen, Skills und Agentenverhalten.
- **Sauberkeitsprüfung** (`tools/sauber.py`): findet persönliche Angaben und Geheimnisse, auch in der Git-Historie
  (`--historie`).

### Geändert

- Lizenz Apache-2.0, englische README, `uv` mit eigenem Paketindex vor PyPI (#1).
- GitHub-Workflows für Tests, PyPI-Veröffentlichung und Bilder auf `ghcr.io` (#2).
