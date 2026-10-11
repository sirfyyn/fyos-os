# Änderungen

Alle nennenswerten Änderungen an FYOS stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionen folgen
[Semantic Versioning](https://semver.org/lang/de/). Die Zahlen in Klammern sind die Nummern der Pull Requests.

Eine Version gilt für das ganze Paket: Oberfläche (`web`), Hub (`fyos-hub`) und Installer (`fyos-install`) tragen
dieselbe Nummer. Der Agent (OpenClaw mit den FYOS-Plugins) kommt aus dem Schwester-Repo
`fyos-agent` und wird mit demselben Tag veröffentlicht; dessen Änderungen
stehen in dessen `CHANGELOG.md`.

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
