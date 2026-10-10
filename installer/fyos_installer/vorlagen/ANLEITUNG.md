# FYOS — Anleitung für diese Installation

Erzeugt vom FYOS-Installer. Ziel: **{{ziel_text}}**

Agent: **{{agent_name}}**, Besitzer: **{{besitzer_name}}**, Sprache: {{sprache}}.

## Gewählte Bausteine

{{bausteine}}

## Nächste Schritte

{{schritte}}

## Dateien in diesem Ordner

{{dateien}}

## Wichtig

- Geheimnisse stehen nur in `{{geheimdatei}}` (Rechte 0600). Die Datei gehört nicht ins Git und nicht in Nachrichten; eine `.gitignore` ist angelegt.
- Der Hub wird als eigenes Bild gebaut (`hub/Dockerfile`): Hub der Distribution plus die gewählten Plugin-Pakete. Pakete aus Git-Adressen brauchen im Basisbild `git` und Zugriff auf das Repository.
- Die Plugin-Pakete installiert `uv` statt `pip`. Ein eigener Paketindex (Umgebungsvariable `FYOS_PAKETINDEX`, beim Bauen als Bau-Argument `FYOS_INDEX_URL`) steht vor PyPI, und `uv` nimmt ein Paket nur aus dem ersten Index, der es führt: Ein Paket gleichen Namens auf PyPI kann das eigene nicht verdrängen.
- Persona und Grenzen des Agenten stehen in `fyos.yaml` (Schema: `fyos-agent/fyos.example.yaml`); nach Änderungen den Agenten neu starten.
- Läuft etwas nicht, zeigt `{{protokoll_befehl}}` die Meldungen.
{{hinweise}}
