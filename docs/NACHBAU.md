# Nachbau: jede Fähigkeit selbst betreiben

FYOS ist aus einem privaten System entstanden. Das Ziel der Distribution: Wer will, kann jede Fähigkeit dieses
Systems nachbauen, mit eigenen Konten und eigenen Diensten und ohne etwas Persönliches zu übernehmen. Dieses Dokument
hält fest, wie weit das ist und in welcher Reihenfolge es weitergeht. Es ist ein Plan und wird mit jeder Stufe
nachgezogen.

## Das Muster

Jede Fähigkeit besteht aus einem Hub-Plugin und einer **Quelle**. Das Plugin trägt keine Adresse fest ein, sondern fragt
die Quelle bei jedem Aufruf neu. Die Quelle sucht in fester Reihenfolge:

1. eine Adresse: als Argument, von einem Plugin angemeldet oder aus der Umgebung (`FYOS_<FÄHIGKEIT>_URL`, dazu eine
   Kopfzeile `FYOS_<FÄHIGKEIT>_KOPF` im Format `Name: Wert`);
2. eine Ablage, die ein Plugin anmeldet (etwa das Workboard des Agenten oder ein Konto, das ein Plugin direkt liest);
3. sonst: nicht eingerichtet (`NichtEingerichtet`, HTTP 501) mit einem Hinweis, wie man es einrichtet.

Daraus folgen drei Zustände, die jede Oberfläche getrennt zeigt: **Daten** (auch eine leere Liste), **Fehler** (Dienst
aus oder Anmeldung abgelehnt, nie als „leer“ getarnt) und **nicht eingerichtet** (weder rot noch leer, mit dem Weg zum
Einrichten). Vorgaben gibt es nur für Allgemeines; eine leere Umgebung heißt „nicht eingerichtet“, nie „irgendein
Rechner im Netz“. Das Vorbild steht in [`ERWEITERN.md`](ERWEITERN.md) §2.13 (`mcp_hub.vorgaenge.quelle()`).

## Grundstufe und Ausbaustufe

- **Grundstufe:** was der Agent selbst mitbringt (Workboard, Cron, Skills) und was sich ohne eigenen Dienst direkt
  anbinden lässt (ein CalDAV-Kalender, ein IMAP-Postfach). Wenig zu betreiben, gut für Compose auf einem Rechner.
- **Ausbaustufe:** eigene Dienste wie im Ursprungssystem (ein Ticketdienst, ein Kalender- und ein Postfach-Dienst,
  Paperless-ngx, Listmonk …). Mehr zu betreiben, dafür Verlauf, Wartelisten, mehrere Konten in einem Dienst.
- Beide sprechen denselben Vertrag; die Wahl gilt je Fähigkeit. Die Plugins, die Quellen und die Doku sind in beiden
  Stufen gleich und entstehen zuerst.

**Entschieden:** Die Stufe ist **je Fähigkeit wählbar**, im Assistenten und in der Textoberfläche mit einer Auswahl
je Fähigkeit, ohne Oberfläche mit `--stufe termine=ausbau` oder `stufen:` in der Antwortdatei. Dazu kommt, wo es sinnvoll
ist, die Wahl **aus**: nichts einrichten, die Fähigkeit meldet dann ehrlich „nicht eingerichtet“. Ohne Wahl gilt die
**Vorgabe nach Bauart**: Kubernetes nimmt die Ausbaustufe, Docker Compose (und „nur Dateien“) die Grundstufe. Wo es keine
Grundstufe gibt (Post senden, heute auch Dokumente), bleiben Ausbau und aus, und die Vorgabe ist der Ausbau.

Was die Wahl bewirkt: Bei der **Grundstufe** rendert der Installer keinen Dienst und setzt keine Dienstadresse; das Plugin
nimmt den direkten Weg (CalDAV, IMAP, Workboard). Bei der **Ausbaustufe** steht die Adresse des Dienstes in der Umgebung
des Hubs (`FYOS_TERMINE_URL` und so weiter). Einen Dienst dazu rendert der Installer, **sobald es dafür einen Baustein
gibt**; bis dahin liefert er die Dienste der Ausbaustufe nicht mit, schreibt die Zeile zum Ausfüllen und sagt im Plan
ehrlich, welche Variable du selbst eintragen musst. Siehe `installer/README.md`, Abschnitt Stufe je Fähigkeit, und
`ERWEITERN.md` §7.3.

## Stand je Fähigkeit

Die Spalte „Vorgabe“ nennt die Stufe, die der Installer ohne Wahl nimmt (Compose / Kubernetes).

| Fähigkeit | Plugin (Paket) | Grundstufe | Ausbaustufe | Vorgabe | Stand |
|---|---|---|---|---|---|
| Vorgänge | `vorgaenge` (Kern), `vorgangsquelle` (fyos-plugin-leitstand) | Workboard des Agenten | Vorgangs-Dienst (`FYOS_VORGAENGE_URL`) | Grund / Ausbau | Grundstufe fertig (0.1.0); Stufenwahl im Installer; Dienst der Ausbaustufe liefert der Installer noch nicht mit |
| Termine | `termine` (Kern), `kalender` (fyos-plugin-kalender), Leitstand | CalDAV- und ICS-Konten direkt | Termin-Dienst (`FYOS_TERMINE_URL`) | Grund / Ausbau | Grundstufe fertig, erscheint mit 0.1.1; Stufenwahl im Installer; Dienst der Ausbaustufe fehlt noch als Baustein |
| Postfach lesen | `postfach` (Kern), `mail` (fyos-plugin-mail), Wache im Leitstand | IMAP direkt, nur lesend | Postfach-Dienst (`FYOS_POSTFACH_URL`) | Grund / Ausbau | Grundstufe fertig, erscheint mit 0.1.1; Stufenwahl im Installer; Dienst der Ausbaustufe fehlt noch als Baustein |
| Post senden | `post` (fyos-plugin-mail) | — | Listmonk (`FYOS_POST_URL`) | Ausbau / Ausbau | Plugin fertig (fyos-plugin-mail 0.2.0); nur Ausbau oder aus; Listmonk als Baustein im Installer fehlt noch (`FYOS_POST_URL` trägst du selbst ein) |
| Dokumente | `dokumente` (Kern), `dokumente` (fyos-plugin-leitstand) | Ordner-Ablage (geplant) | Paperless-ngx (`FYOS_DOKUMENTE_URL`, Token in `FYOS_DOKUMENTE_KOPF`) | Ausbau / Ausbau, bis die Ordner-Ablage da ist | Quelle und Leitstand fertig (Ausbaustufe), erscheint mit 0.1.1; Grundstufe offen, Paperless-ngx als Baustein fehlt noch |
| Dateien | `dateien` (Kern, mit App „Dateien“) | Ordner auf einem Volume (`FYOS_DATEIEN`) mit Papierkorb und früheren Fassungen | — | fertig, erscheint mit 0.1.1; Ablage des Kerns, kein Dienst nötig (`ERWEITERN.md` §2.17) |
| Ansichten | `gui` (Kern) | im Hub; mit Redis überstehen sie einen Neustart | — | fertig; ab 0.1.1 auch über die Shell |
| Agent | fyos-agent | OpenClaw-Mod mit Verhaltensvertrag | — | fertig |
| Nachtarbeit | `os` (Kern), [`tools/nachtauftrag.py`](../tools/nachtauftrag.py) | Cron des Agenten; Meldung wartet in Redis bis zu 24 h | — | fertig, siehe [`NACHTARBEIT.md`](NACHTARBEIT.md) |
| Haus | fyos-plugin-haus | denkbar: Home Assistant direkt | Haus-Dienst vor Home Assistant, Kameras über Frigate und MQTT | Paket da; braucht heute den Haus-Dienst |
| Konten | fyos-plugin-konten | denkbar: ein Zugang je Konto direkt | Konten-Dienst als Tresor für Zugänge; Fotos über Immich | aufgeräumt (0.2.0); braucht heute den Konten-Dienst |
| Finanzen | fyos-plugin-finanzen | — | Finanz-Dienst (Monatsplan, Kontodaten) | aufgeräumt (0.2.0); braucht heute den Finanz-Dienst |
| Betrieb | fyos-plugin-betrieb | — | Kubernetes, Gitea, Prometheus, Postgres für den Betriebsgraphen | aufgeräumt (0.3.1) |
| Modell | fyos-plugin-modell | das Modell, das der Agent nutzt | eigener Modellserver mit Steuerpult | aufgeräumt (0.2.0) |
| Leitstand | fyos-plugin-leitstand | Redis | Postgres (Entscheidungen), Qdrant (Wissen), weitere Dienste | Paket da; Quellen kommen Fähigkeit für Fähigkeit |

„Paket da“ heißt: das Plugin ist aus dem Ursprungssystem übernommen und läuft, wenn die Dienste dahinter da sind. In
Haus und Leitstand zeigen einige Vorgaben noch auf Dienstnamen eines bestimmten Clusters, und einige
Umgebungsvariablen tragen noch Eigennamen; beides kommt beim Aufräumen (Schritt 6) heraus. „Aufgeräumt“ heißt: keine
Vorgabe zeigt auf einen Rechner oder Dienst (ohne Einstellung „nicht eingerichtet“), Variablen haben neutrale Namen,
die alten wirken als Alias weiter; die Tabelle der Einstellungen steht in der README des Pakets.

## Reihenfolge

1. Vorgänge, Grundstufe — fertig.
2. Plugins aus dem Ursprungssystem in die Pakete umziehen — fertig.
3. Termine: Quelle im Kern, CalDAV- und ICS-Plugin, Leitstand liest über die Quelle — fertig.
4. Postfach und Post: Quelle im Kern, IMAP-Plugin nur lesend, Wache über die Quelle — fertig; danach das Plugin `post`
   für Listmonk mit einem Einrichtungs-Kommando für die Vorlage — fertig.
5. Dokumente: Quelle im Kern mit Paperless-ngx als Dienst, Leitstand liest über die Quelle — fertig; die Ablage ohne
   eigenen Dienst (Grundstufe, ein Ordner) ist noch zu bauen.
6. Aufräumen in Haus, Konten, Finanzen, Betrieb, Modell und Leitstand: keine Vorgabe auf interne Dienstnamen (leer =
   nicht eingerichtet), neutrale Namen für Umgebungsvariablen mit Eigennamen (die alten bleiben eine Weile als Alias),
   und wo es eine Grundstufe gibt, eine Quelle nach dem Muster oben — Konten, Finanzen, Betrieb und Modell fertig;
   Haus und Leitstand folgen. Der Agenten-Dienst in Betrieb heißt dabei `FYOS_AGENTDIENST_URL`, weil
   `FYOS_AGENT_URL` das OpenClaw-Gateway der Kopplung meint.
7. Die Stufe je Fähigkeit im Installer (Auswahl, Vorgabe nach Bauart, Wirkung auf die erzeugten Dateien) — fertig.
8. Noch offen: die Dienste der Ausbaustufe als Bausteine im Installer (Ticketdienst, Termin-Dienst, Postfach-Dienst,
   Listmonk, Paperless-ngx; bis dahin trägst du ihre Adresse selbst ein) und die Grundstufen-Ablage für Dokumente
   (ein Ordner) im Kern.

Jeder Schritt ist erst fertig, wenn `tools/sauber.py` für das Repo 0 Befunde meldet, die Tests grün sind und die drei
Zustände in der Oberfläche zu sehen sind.
