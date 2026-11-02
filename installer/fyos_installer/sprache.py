"""Sprache des Installers und der erzeugten Oberfläche: Englisch als Vorgabe, Deutsch mit `--sprache de`.

Schlüssel sind die deutschen Ausgangstexte (wie gettext): `_("Fertig.")`. `EN` bildet sie auf Englisch ab; fehlt ein
Eintrag, bleibt der deutsche Text. Katalog-Texte (Titel, Kurztexte) laufen über `katalog_text()`, damit katalog.yaml
und seine Feldnamen unverändert bleiben (Vertrag mit Plugin-Katalogen).
"""

from __future__ import annotations

import os
from contextlib import contextmanager

SPRACHEN = ("en", "de")
VORGABE = "en"
_aktiv = os.environ.get("FYOS_INSTALLER_SPRACHE", "").strip().lower()[:2] or VORGABE
if _aktiv not in SPRACHEN:
    _aktiv = VORGABE


def setze(sprache: str | None) -> str:
    """Stellt die Sprache ein (`en` oder `de`, auch `de-DE`, `deutsch`); Unbekanntes fällt auf die Vorgabe."""
    global _aktiv
    s = (sprache or "").strip().lower()
    _aktiv = "de" if s.startswith("de") or s == "german" else "en" if s.startswith("en") else VORGABE
    return _aktiv


def normalisiere(x: object) -> str | None:
    """`de`, `de-DE`, `Deutsch` → `de`; `en`, `English` → `en`; sonst None (ohne die aktive Sprache zu ändern)."""
    s = str(x or "").strip().lower()
    if s.startswith("de") or s == "german":
        return "de"
    if s.startswith("en"):
        return "en"
    return None


def aktiv() -> str:
    return _aktiv


def _(text: str, *args: object, **werte: object) -> str:
    """Übersetzt `text` (deutscher Ausgangstext) in die aktive Sprache; `{0}`/`{name}` werden eingesetzt."""
    aus = EN.get(text, text) if _aktiv == "en" else text
    return aus.format(*args, **werte) if (args or werte) else aus


def katalog_text(text: str) -> str:
    """Titel und Kurztexte aus dem Katalog in der aktiven Sprache (unbekannte bleiben, wie sie sind)."""
    if _aktiv != "en" or not isinstance(text, str):
        return text
    return KATALOG_EN.get(text.strip(), text)


def lerne(de: object, en: object) -> None:
    """Merkt sich die englische Fassung eines Katalogtexts (Block `en:` in katalog.yaml und Plugin-Katalogen)."""
    if isinstance(de, str) and isinstance(en, str) and de.strip() and en.strip():
        KATALOG_EN[de.strip()] = en.strip()


def lerne_texte(roh_en: object, deutsch: dict[str, object]) -> None:
    """`roh_en` ist der Block `en:` eines Eintrags; `deutsch` nennt die deutschen Texte derselben Schlüssel (Listen
    paarweise). Falsch geformte Blöcke werden übergangen: Englisch ist eine Zugabe, kein Teil des Schemas."""
    if not isinstance(roh_en, dict):
        return
    for k, de in deutsch.items():
        en = roh_en.get(k)
        if isinstance(de, list) and isinstance(en, list):
            for a, b in zip(de, en):
                lerne(a, b)
        else:
            lerne(de, en)


@contextmanager
def sprache_von(sprache: str | None):
    """Stellt für die Dauer des Blocks eine andere Sprache ein (Plan in der Sprache der erzeugten Oberfläche)."""
    global _aktiv
    alt = _aktiv
    _aktiv = normalisiere(sprache) or alt
    try:
        yield _aktiv
    finally:
        _aktiv = alt


def persona_sprache() -> str:
    """Vorgabe der Agenten-Sprache passend zur Oberfläche."""
    return "English" if _aktiv == "en" else "Deutsch"


def persona_vorgabe(basis: dict[str, str]) -> dict[str, str]:
    """Vorgaben der Persona in der Sprache der Oberfläche: Sprache und Wesen (sonst stand das deutsche Wesen auch im
    englischen Installer)."""
    wesen = "Calm, precise and attentive" if _aktiv == "en" else basis["wesen"]
    return {**basis, "wesen": wesen, "sprache": persona_sprache()}


EN: dict[str, str] = {
    # cli.py
    "FYOS einrichten. Ohne Argumente startet ein Assistent im Browser (nur auf diesem Rechner erreichbar).":
        "Set up FYOS. Without arguments a wizard starts in the browser (reachable only on this computer).",
    "Beispiele:": "Examples:",
    "Web-Assistent": "Web wizard",
    "Stufe je Fähigkeit umstellen (Vorgabe: Kubernetes Ausbau, Compose Grund)":
        "Change the level per capability (default: Kubernetes full, Compose basic)",
    "Abnahme einer laufenden Installation": "Acceptance check of a running installation",
    "Rückgabewerte: 0 gut, 1 Installation oder Start gescheitert, 2 falsche Eingabe, 3 FYOS läuft, aber die Abnahme\nist nicht bestanden.":
        "Exit codes: 0 good, 1 installation or start failed, 2 wrong input, 3 FYOS runs, but the acceptance check\ndid not pass.",
    "Textoberfläche statt Browser (braucht Textual)": "Text interface instead of the browser (needs Textual)",
    "Bausteine, durch Komma getrennt (schaltet in den Modus ohne Oberfläche)": "Building blocks, comma-separated (switches to the mode without interface)",
    "compose, k8s oder dateien (Vorgabe ohne Oberfläche: compose)": "compose, k8s or dateien (files only; default without interface: compose)",
    "YAML mit persona, modell, felder, optionen, stufen": "YAML with persona, modell, felder, optionen, stufen",
    "Stufe einer Fähigkeit: grund, ausbau oder aus (mehrfach möglich; Fähigkeiten zeigt --liste). Ohne Angabe gilt die Vorgabe der Bauart: Kubernetes Ausbau, Compose Grund":
        "Level of a capability: grund (basic), ausbau (full) or aus (off) (repeatable; --liste shows capabilities). Without it the default of the target applies: Kubernetes full, Compose basic",
    "Zielordner (Vorgabe: ./fyos)": "Target folder (default: ./fyos)",
    "nur zeigen, was entstünde; nichts schreiben, nichts starten": "only show what would be created; write nothing, start nothing",
    "ohne Rückfrage ausführen": "run without asking",
    "zusätzlicher Katalog (mehrfach möglich)": "additional catalog (repeatable)",
    "Kataloge installierter Plugin-Pakete nicht einlesen": "do not read catalogs of installed plugin packages",
    "Bausteine auflisten und beenden": "list building blocks and exit",
    "nur die Abnahme gegen eine laufende Installation (Adresse der Shell, zum Beispiel http://localhost:8080)":
        "only the acceptance check against a running installation (address of the shell, for example http://localhost:8080)",
    "Port des Web-Assistenten (Vorgabe: zufällig)": "Port of the web wizard (default: random)",
    "Browser nicht automatisch öffnen": "do not open the browser automatically",
    "Sprache des Installers und der erzeugten Oberfläche: en (Vorgabe) oder de": "Language of the installer and of the generated interface: en (default) or de",
    "Pflicht": "required",
    "Fähigkeiten (Stufe wählen mit --stufe FÄHIGKEIT=grund|ausbau|aus):": "Capabilities (choose the level with --stufe CAPABILITY=grund|ausbau|aus):",
    "Ziel: {0}": "Target: {0}",
    "Bausteine: ": "Building blocks: ",
    "Zielordner: {0}": "Target folder: {0}",
    "Stufe je Fähigkeit (Vorgabe nach Bauart, umstellbar mit --stufe FÄHIGKEIT=grund|ausbau|aus):":
        "Level per capability (default by target, change with --stufe CAPABILITY=grund|ausbau|aus):",
    "Dateien:": "Files:",
    "Befehle:": "Commands:",
    "Hinweis: {0}": "Note: {0}",
    "--stufe {0}: erwartet FÄHIGKEIT=STUFE, zum Beispiel termine=grund": "--stufe {0}: expected CAPABILITY=LEVEL, for example termine=grund",
    "Fehler: {0}": "Error: {0}",
    "Das geht so nicht:": "This does not work:",
    "Trocken: nichts wurde geschrieben oder gestartet.": "Dry run: nothing was written or started.",
    "Ohne Terminal bitte --ja angeben (oder --trocken zum Ansehen).": "Without a terminal, pass --ja (or --trocken to look).",
    "Dateien schreiben": "Write files",
    " und starten": " and start",
    "? [j/N] ": "? [y/N] ",
    "Abgebrochen.": "Cancelled.",
    "geschrieben: {0}": "written: {0}",
    "Fertig. Die nächsten Schritte stehen in ANLEITUNG.md im Zielordner.": "Done. The next steps are in ANLEITUNG.md in the target folder.",
    "Katalog fehlerhaft:\n{0}": "Catalog invalid:\n{0}",
    "Die Textoberfläche braucht Textual. Installiere es mit:": "The text interface needs Textual. Install it with:",
    "Oder nutze den Web-Assistenten (fyos-install) bzw. --auswahl.": "Or use the web wizard (fyos-install) or --auswahl.",
    # erzeugen.py
    "Docker Compose auf diesem Rechner": "Docker Compose on this computer",
    "Kubernetes (Kustomize-Overlay)": "Kubernetes (Kustomize overlay)",
    "Nur Dateien erzeugen (Docker-Compose-Layout)": "Only generate files (Docker Compose layout)",
    "Laufzeit-Konfiguration der Oberfläche (Sprache, Name des Agenten)": "Runtime configuration of the interface (language, agent name)",
    "nächste Schritte": "next steps",
    "diese Datei": "this file",
    "Dienste web, hub (eigenes Bild), agent, redis": "Services web, hub (own image), agent, redis",
    "Port, Modell, Agent-Token und Plugin-Felder (Geheimnisse nur hier)": "Port, model, agent token and plugin fields (secrets only here)",
    "Konfiguration des Runners (ohne Geheimnisse)": "Configuration of the runner (without secrets)",
    "Kern-Plugins des Hubs": "Core plugins of the Hub",
    "Hub-Bild plus gewählte Plugin-Pakete": "Hub image plus chosen plugin packages",
    "hält .env aus dem Git": "keeps .env out of Git",
    "hält secrets.yaml aus dem Git": "keeps secrets.yaml out of Git",
    "Overlay: Basis, ConfigMaps, Bilder": "Overlay: base, ConfigMaps, images",
    "Laufzeit-Konfiguration der Oberfläche (Sprache, Name des Agenten, ConfigMap fyos-web-config)":
        "Runtime configuration of the interface (language, agent name, ConfigMap fyos-web-config)",
    "Konfiguration des Runners (ConfigMap fyos-agent-config)": "Configuration of the runner (ConfigMap fyos-agent-config)",
    "Kern-Plugins (ConfigMap fyos-hub-config)": "Core plugins (ConfigMap fyos-hub-config)",
    "Secrets mit Modellzugang, Agent-Token, Plugin-Geheimnissen": "Secrets with model access, agent token, plugin secrets",
    "dieselben Secrets als Vorlage ohne Werte": "the same secrets as a template without values",
    "Allgemein": "General",
    "Bilder und Paketbezug": "Images and package source",
    "Modell (jeder OpenAI-kompatible Anbieter)": "Model (any OpenAI-compatible provider)",
    "Agent": "Agent",
    "# Vom FYOS-Installer erzeugt. Enthält Geheimnisse: nicht weitergeben, nicht ins Git.":
        "# Generated by the FYOS installer. Contains secrets: do not share, do not commit to Git.",
    "2. `docker compose build` baut das Hub-Bild mit den gewählten Plugin-Paketen.":
        "2. `docker compose build` builds the Hub image with the chosen plugin packages.",
    "3. `docker compose up -d` startet FYOS.": "3. `docker compose up -d` starts FYOS.",
    "4. {0} im Browser öffnen.": "4. Open {0} in the browser.",
    "5. Beenden mit `docker compose down`.": "5. Stop with `docker compose down`.",
    "2. Hub-Bild bauen und in deine Registry schieben: `{0}` und `docker push {1}`.":
        "2. Build the Hub image and push it to your registry: `{0}` and `docker push {1}`.",
    "3. `kubectl create namespace {0}`, dann `kubectl apply -f secrets.yaml`.":
        "3. `kubectl create namespace {0}`, then `kubectl apply -f secrets.yaml`.",
    "4. `kubectl apply -k .` legt FYOS an (zur Kontrolle vorher `kubectl kustomize .`).":
        "4. `kubectl apply -k .` creates FYOS (to check first: `kubectl kustomize .`).",
    "5. Zugriff zum Ausprobieren: `kubectl -n {0} port-forward svc/web {1}:80`, dann {2} öffnen.":
        "5. Access for trying it out: `kubectl -n {0} port-forward svc/web {1}:80`, then open {2}.",
    "Kustomize-Basis: {0} (mit `k8s_basis` in den Antworten änderbar). Der Pfad ist relativ zum Zielordner.":
        "Kustomize base: {0} (change it with `k8s_basis` in the answers). The path is relative to the target folder.",
    "Die Modell-Adresse zeigt auf host.docker.internal; im Cluster ist sie so nicht erreichbar.":
        "The model address points to host.docker.internal; it is not reachable like that inside the cluster.",
    "Ziel »nur Dateien«: nichts wird gestartet; die Befehle stehen in ANLEITUNG.md.":
        "Target »files only«: nothing is started; the commands are in ANLEITUNG.md.",
    "Bilder ({0}) zeigen noch auf die Beispieladresse {1}: "
    "FYOS_REGISTRY auf die eigene Registry setzen (Form host/besitzer) oder die Bilder unter Optionen "
    "eintragen, sonst lässt sich nichts schieben oder ziehen.":
        "Images ({0}) still point to the example address {1}: set FYOS_REGISTRY to your own registry (form host/owner) "
        "or enter the images under options, otherwise nothing can be pushed or pulled.",
    "Voraussetzung ({0}): {1}": "Requirement ({0}): {1}",
    "Unbekanntes Ziel '{0}' (erlaubt: {1})": "Unknown target '{0}' (allowed: {1})",
    "Antworten: '{0}' muss ein Objekt sein": "Answers: '{0}' must be an object",
    "Antworten: felder.{0} muss ein Objekt sein": "Answers: felder.{0} must be an object",
    "Antworten: {0}.{1} enthält Steuerzeichen oder Zeilenumbrüche": "Answers: {0}.{1} contains control characters or line breaks",
    "{0}: Feld '{1}'": "{0}: field '{1}'",
    "{0} enthält Steuerzeichen oder Zeilenumbrüche": "{0} contains control characters or line breaks",
    "{0} fehlt ({1})": "{0} is missing ({1})",
    "{0} muss eine ganze Zahl sein": "{0} must be a whole number",
    "{0} muss eine Adresse mit http:// oder https:// sein": "{0} must be an address with http:// or https://",
    "{0} muss einer von {1} sein": "{0} must be one of {1}",
    "Persona: '{0}' darf nicht leer sein": "Persona: '{0}' must not be empty",
    "Modell: basis_url muss mit http:// oder https:// beginnen": "Model: basis_url must start with http:// or https://",
    "Modell: name darf nicht leer sein": "Model: name must not be empty",
    "Optionen: 'agent' gibt es seit 0.2.1 nicht mehr; der Agent ist immer der Runner.":
        "Options: 'agent' no longer exists since 0.2.1; the agent is always the runner.",
    "Optionen: {0} ist kein gültiger Bildname": "Options: {0} is not a valid image name",
    "Optionen: paketindex muss eine http(s)-Adresse ohne Leer- und Sonderzeichen sein":
        "Options: paketindex must be an http(s) address without spaces and special characters",
    "Optionen: namespace ist kein gültiger Kubernetes-Name": "Options: namespace is not a valid Kubernetes name",
    "{0}: Paketquelle enthält unzulässige Zeichen": "{0}: package source contains invalid characters",
    "Antworten für nicht gewählten Baustein '{0}' werden ignoriert.": "Answers for the unchosen building block '{0}' are ignored.",
    "Unbekanntes Feld '{0}' bei '{1}' wird ignoriert.": "Unknown field '{0}' at '{1}' is ignored.",
    "Umgebungsvariable {0} wird von mehreren Feldern belegt": "Environment variable {0} is used by several fields",
    "Kern: port muss zwischen 1 und 65535 liegen": "Core: port must be between 1 and 65535",
    # katalog.py
    "Unbekannter Baustein: '{0}'": "Unknown building block: '{0}'",
    "Baustein '{0}' kommt doppelt vor ({1})": "Building block '{0}' appears twice ({1})",
    "{0}: '{1}' muss ein nichtleerer Text sein": "{0}: '{1}' must be a non-empty text",
    "{0}: '{1}' muss eine Liste von Texten sein": "{0}: '{1}' must be a list of texts",
    "{0}: Feld muss ein Objekt sein": "{0}: field must be an object",
    "{0}: Feldname fehlt oder ist ungültig ({1})": "{0}: field name is missing or invalid ({1})",
    "{0}: typ muss einer von {1} sein": "{0}: typ must be one of {1}",
    "{0}: Typ 'wahl' braucht eine Liste 'optionen'": "{0}: type 'wahl' needs a list 'optionen'",
    "{0}: 'pflicht' muss wahr oder falsch sein": "{0}: 'pflicht' must be true or false",
    "{0}: 'umgebung' muss ein Umgebungsvariablenname in Großbuchstaben sein":
        "{0}: 'umgebung' must be an environment variable name in capital letters",
    "{0}: 'standard' muss bei Typ 'zahl' eine Zahl sein": "{0}: 'standard' must be a number for type 'zahl'",
    "{0}: 'titel' (Beschriftung des Feldes) fehlt": "{0}: 'titel' (label of the field) is missing",
    "{0}: 'reife' muss ein Objekt aus Schicht und Stufe sein": "{0}: 'reife' must be an object of layer and level",
    "{0}: reife.{1}: unbekannte Schicht (erlaubt: {2})": "{0}: reife.{1}: unknown layer (allowed: {2})",
    "{0}: reife.{1} muss eine ganze Zahl von 1 bis {2} sein": "{0}: reife.{1} must be a whole number from 1 to {2}",
    "{0}: Eintrag {1} muss ein Objekt sein": "{0}: entry {1} must be an object",
    "{0}: Eintrag {1}: 'id' fehlt oder ist ungültig ({2})": "{0}: entry {1}: 'id' is missing or invalid ({2})",
    "{0}: 'kurz' darf nur eine Zeile sein": "{0}: 'kurz' may only be one line",
    "{0}: 'art' muss einer von {1} sein": "{0}: 'art' must be one of {1}",
    "{0}: Bildname '{1}' ist ungültig (nur Dateiname mit .svg/.png/.jpg/.webp)":
        "{0}: image name '{1}' is invalid (only a file name with .svg/.png/.jpg/.webp)",
    "{0}: 'quelle' braucht paket (Paketname) und optional repo (Git-Repo-Name)":
        "{0}: 'quelle' needs paket (package name) and optionally repo (Git repo name)",
    "{0}: 'konfiguration' muss eine Liste sein": "{0}: 'konfiguration' must be a list",
    "{0}: Feldnamen kommen doppelt vor": "{0}: field names appear twice",
    "{0}: 'hub_plugins' braucht je Eintrag name (optional config, secrets, enabled)":
        "{0}: 'hub_plugins' needs a name per entry (optionally config, secrets, enabled)",
    "{0}: Katalog muss ein Objekt mit 'bausteine' sein": "{0}: catalog must be an object with 'bausteine'",
    "{0}: 'bausteine' muss eine nichtleere Liste sein": "{0}: 'bausteine' must be a non-empty list",
    "{0}: id '{1}' kommt doppelt vor": "{0}: id '{1}' appears twice",
    "{0}: abhaengig_von verweist auf unbekannten Baustein '{1}'": "{0}: abhaengig_von refers to the unknown building block '{1}'",
    "{0}: hängt von sich selbst ab": "{0}: depends on itself",
    "{0}: Katalog ist zu groß": "{0}: catalog is too large",
    "{0}: nicht lesbar ({1})": "{0}: not readable ({1})",
    "{0}: nur http(s)-Adressen": "{0}: only http(s) addresses",
    "{0}: nicht ladbar ({1})": "{0}: cannot be loaded ({1})",
    "{0}: Entry-Point liefert weder Pfad noch Katalog": "{0}: entry point returns neither a path nor a catalog",
    "Unbekannter Bezug '{0}' (index oder git)": "Unknown source '{0}' (index or git)",
    "Zyklus in abhaengig_von: {0}": "Cycle in abhaengig_von: {0}",
    "Baustein '{0}' braucht einen Paketindex: Umgebungsvariable FYOS_PAKETINDEX "
    "setzen oder in den Antworten unter optionen.paketindex eintragen":
        "Building block '{0}' needs a package index: set the environment variable FYOS_PAKETINDEX "
        "or enter it in the answers under optionen.paketindex",
    "Baustein '{0}' braucht eine Plugin-Quelle: Umgebungsvariable FYOS_PLUGIN_QUELLE "
    "setzen oder in den Antworten unter optionen.plugin_quelle eintragen":
        "Building block '{0}' needs a plugin source: set the environment variable FYOS_PLUGIN_QUELLE "
        "or enter it in the answers under optionen.plugin_quelle",
    "(kein Bild vorhanden)": "(no image available)",
    "Skizze zu {0}": "Sketch of {0}",
    "Beschriftungen: ": "Labels: ",
    "Bild zu {0}": "Image of {0}",
    "Datei: {0}": "File: {0}",
    "(+{0} weitere Bilder im selben Ordner)": "(+{0} more images in the same folder)",
    # stufen.py (Glossar: Grundstufe = basic tier, Ausbaustufe = extended tier, Fähigkeit = capability)
    "Grundstufe": "basic tier",
    "Ausbaustufe": "extended tier",
    "aus": "off",
    "nicht eingerichtet": "not set up",
    "Vorgabe": "default",
    "von dir gewählt": "chosen by you",
    "Antworten: 'stufen' muss ein Objekt aus Fähigkeit und Stufe sein": "Answers: 'stufen' must be an object of capability and tier",
    "Unbekannte Fähigkeit '{0}' bei den Stufen (bekannt: {1})": "Unknown capability '{0}' in the tiers (known: {1})",
    "Die Stufe für {0} wird ignoriert: der Baustein '{1}' ist nicht gewählt.":
        "The tier for {0} is ignored: the building block '{1}' is not chosen.",
    "die Stufe '{0}' gibt es nicht (erlaubt: {1})": "the tier '{0}' does not exist (allowed: {1})",
    " oder ": " or ",
    "lässt sich nicht ausschalten; wähle {0}": "cannot be switched off; choose {0}",
    "hat keine {0}; wähle {1}": "has no {0}; choose {1}",
    "die {0} ({1}) gibt es noch nicht; wähle {2}": "the {0} ({1}) does not exist yet; choose {2}",
    "{0}: Das Feld »{1}« gehört zur {2} und wird bei {3} nicht verwendet.":
        "{0}: the field »{1}« belongs to the {2} and is not used with {3}.",
    "der ": "the ",
    "{0}, Ausbaustufe: Der Hub fragt den Dienst unter {1}. Den Dienst selbst ({2}) "
    "liefert der Installer noch nicht mit; er muss laufen und erreichbar sein.":
        "{0}, extended tier: the Hub asks the service at {1}. The installer does not ship the service itself ({2}) "
        "yet; it must be running and reachable.",
    "Ohne eigenen Dienst wähle die Grundstufe.": "Without a service of your own, choose the basic tier.",
    "Eine Grundstufe ohne Dienst gibt es hier nicht.": "There is no basic tier without a service here.",
    "{0}, Ausbaustufe: Den Dienst ({1}) liefert der Installer noch nicht mit; trage "
    "{2} selbst ein, in {3}. Solange die Adresse fehlt, gilt »{4}« als nicht eingerichtet. {5}":
        "{0}, extended tier: the installer does not ship the service ({1}) yet; enter {2} yourself, in {3}. "
        "As long as the address is missing, »{4}« counts as not set up. {5}",
    "kustomization.yaml (Adresse) und secrets.yaml (Kopfzeile)": "kustomization.yaml (address) and secrets.yaml (header)",
    " (noch nicht vorhanden)": " (not available yet)",
    "Vorgabe Compose {0}, Kubernetes {1}": "default Compose {0}, Kubernetes {1}",
    # reife.py
    "Gedächtnis": "Memory",
    "Takte": "Schedules",
    "Oberfläche": "Interface",
    "Was der Agent über dich und deine Umgebung weiß.": "What the agent knows about you and your surroundings.",
    "Was der Agent selbst tut.": "What the agent does by itself.",
    "Was von selbst läuft und wie begrenzt.": "What runs by itself and how it is limited.",
    "Was du im Browser siehst.": "What you see in the browser.",
    "Persona": "Persona",
    "Wissen aus Bausteinen": "Knowledge from building blocks",
    "Verlauf und Vorgänge": "History and tickets",
    "Chat": "Chat",
    "Werkzeuge": "Tools",
    "Vorgänge": "Tickets",
    "Von Hand": "By hand",
    "Routinen": "Routines",
    "Routinen mit Grenzen": "Routines with limits",
    "Desktop": "Desktop",
    "Apps": "Apps",
    "Zentrale": "Control center",
    "Der Agent nennt auf Nachfrage seinen Namen und deinen aus der Einrichtung, auch nach einem Neustart des Agenten.":
        "When asked, the agent names itself and you as set up, even after a restart of the agent.",
    "Er beantwortet Fragen zu den gewählten Bausteinen mit Werten aus deren Werkzeugen.":
        "It answers questions about the chosen building blocks with values from their tools.",
    "Ein Verlauf zeigt, was der Agent getan hat und warum, und erledigte Vorgänge bleiben nachlesbar.":
        "A history shows what the agent did and why, and finished tickets stay readable.",
    "Das Chatfenster antwortet unter dem gewählten Namen und legt Schweres zuerst als Freigabe vor.":
        "The chat window answers under the chosen name and puts serious things before you as an approval first.",
    "Er ruft Werkzeuge der gewählten Bausteine auf und meldet das Ergebnis knapp im Chat.":
        "It calls tools of the chosen building blocks and reports the result briefly in the chat.",
    "Er legt Vorgänge an, arbeitet sie ab und meldet den Stand, und Freigaben stehen in einer Liste.":
        "It creates tickets, works through them and reports the state, and approvals are in a list.",
    "Nichts läuft von selbst: `mcp.zeitplan` ist leer, und der Agent handelt nur auf Zuruf.":
        "Nothing runs by itself: `mcp.zeitplan` is empty, and the agent only acts when asked.",
    "Routinen sind eingerichtet, und `mcp.zeitplan` oder die Fläche des Bausteins zeigt, was läuft und was gerade erlaubt ist.":
        "Routines are set up, and `mcp.zeitplan` or the building block's surface shows what runs and what is allowed right now.",
    "Jede Routine hat Tageslimit und Zeitfenster, und `mcp.zeitplan` zeigt beides samt Laufprotokoll.":
        "Every routine has a daily limit and a time window, and `mcp.zeitplan` shows both with the run log.",
    "Die Adresse öffnet den Desktop mit Dock und Chatfenster, aber noch ohne Fach-Apps.":
        "The address opens the desktop with dock and chat window, but still without specialist apps.",
    "Im Dock erscheint für jeden gewählten Baustein mit Oberfläche eine eigene App (Liste: `/hub-api/apps`).":
        "For every chosen building block with an interface, an app of its own appears in the dock (list: `/hub-api/apps`).",
    "Eine Zentrale zeigt die Lage in einem Satz und, was auf dich wartet, als Kacheln nach Dringlichkeit.":
        "A control center shows the situation in one sentence and what is waiting for you as tiles by urgency.",
    "{0}: Stufe {1} von {2} ({3})": "{0}: level {1} of {2} ({3})",
    "Reifegrad (je Schicht Stufe 1 bis {0}, aus der Auswahl abgeleitet):": "Maturity (per layer level 1 to {0}, derived from the choice):",
    "Erkennbar: {0}": "Recognisable: {0}",
    "Nächste Stufe: {0}": "Next level: {0}",
    # abnahme.py
    "Erlaubte Anfrage über den Browser-Weg": "Allowed request through the browser route",
    "Voller Aufruf-Endpunkt über den Browser-Weg": "Full call endpoint through the browser route",
    "Schreibender Aufruf von einer fremden Webseite": "Writing call from a foreign web page",
    "Werkzeug ohne Oberfläche über den Browser-Weg": "Tool without interface through the browser route",
    "Die Adresse zeigt nicht auf die Shell dieser Installation, oder der Hub ist hinter ihr nicht erreichbar.":
        "The address does not point to the shell of this installation, or the Hub behind it is not reachable.",
    "Durchgegangen wäre nur eine Lesung: audit.stats liefert Zahlen über das Audit-Log.":
        "Only a read would have gone through: audit.stats returns numbers about the audit log.",
    "Die Shell reicht nur apps, resource, app-call und os/* an den Hub weiter (web/nginx/default.conf.template); "
    "ein Proxy davor darf nicht mehr durchlassen.":
        "The shell only passes apps, resource, app-call and os/* to the Hub (web/nginx/default.conf.template); "
        "a proxy in front of it must not let more through.",
    "Durchgegangen wäre nur eine Lesung: werkstatt.suchen listet die angemeldeten Skripte.":
        "Only a read would have gone through: werkstatt.suchen lists the registered scripts.",
    "Der Hub lehnt Anfragen mit fremdem Origin ab (hub/mcp_hub/herkunft.py); prüfe, ob ein Proxy davor die Köpfe "
    "Origin und Sec-Fetch-Site entfernt, und FYOS_ERLAUBTE_HOSTS.":
        "The Hub rejects requests with a foreign Origin (hub/mcp_hub/herkunft.py); check whether a proxy in front of it "
        "removes the Origin and Sec-Fetch-Site headers, and FYOS_ERLAUBTE_HOSTS.",
    "Über den Browser-Weg dürfen nur Werkzeuge mit Oberfläche laufen (hub/mcp_hub/registry.py, "
    "ist_flaechen_werkzeug).":
        "Only tools with an interface may run through the browser route (hub/mcp_hub/registry.py, ist_flaechen_werkzeug).",
    "keine Antwort ({0})": "no answer ({0})",
    "beantwortet (200)": "answered (200)",
    "nicht beantwortet (Status {0})": "not answered (status {0})",
    "NICHT abgelehnt (Antwort {0})": "NOT rejected (answer {0})",
    "abgelehnt ({0})": "rejected ({0})",
    " mit {0}": " with {0}",
    "anders als erwartet ({0} statt {1})": "different than expected ({0} instead of {1})",
    "Abnahme NICHT bestanden: Die erlaubte Gegenprobe scheiterte ({0}); "
    "die Ablehnungen sind so nicht aussagekräftig.":
        "Acceptance check NOT passed: the allowed counter-check failed ({0}); the rejections are not meaningful like this.",
    "Abnahme NICHT bestanden: {0} von {1} verbotenen Anfragen wurden abgelehnt.":
        "Acceptance check NOT passed: {0} of {1} forbidden requests were rejected.",
    "Abnahme bestanden: alle {0} verbotenen Anfragen wurden abgelehnt.":
        "Acceptance check passed: all {0} forbidden requests were rejected.",
    "== Abnahme: verbotene Anfragen an {0} müssen abgelehnt werden": "== Acceptance check: forbidden requests to {0} must be rejected",
    "Gegenprobe: {0}: {1}": "Counter-check: {0}: {1}",
    "Probe {0}: {1}: {2}": "Probe {0}: {1}: {2}",
    "Prüfen: {0}": "Check: {0}",
    "Die Anfragen lesen nur und ändern nichts.": "The requests only read and change nothing.",
    "Abnahme: Nach dem Start stellt der Installer {0} verbotene Anfragen an die Shell; FYOS muss sie "
    "ablehnen. {1} Wiederholen: `{2}`.":
        "Acceptance check: after the start the installer sends {0} forbidden requests to the shell; FYOS must reject "
        "them. {1} Repeat: `{2}`.",
    "Mit laufendem Port-Forward": "With a running port-forward",
    "Ist FYOS gestartet": "Once FYOS is started",
    "Abnahme: {0}, prüft `{1}`, ob FYOS {2} verbotene Anfragen ablehnt. {3}":
        "Acceptance check: {0}, `{1}` checks whether FYOS rejects {2} forbidden requests. {3}",
    "'{0}' ist keine Adresse der Form http://host:port": "'{0}' is not an address of the form http://host:port",
    # ausfuehren.py
    "Der Port ist schon belegt. Wähle einen anderen Port (Feld »port« beim Kern) und starte neu.":
        "The port is already in use. Choose another port (field »port« at the core) and start again.",
    "Ein Bild lässt sich nicht laden. Bei privaten Registries vorher `docker login <registry>` ausführen.":
        "An image cannot be pulled. For private registries run `docker login <registry>` first.",
    "Die Plugin-Quelle verlangt Zugangsdaten. Hinterlege Git-Zugang (Token in der Quelle oder Credential Helper).":
        "The plugin source requires credentials. Provide Git access (token in the source or a credential helper).",
    "Die Plugin-Quelle wurde nicht gefunden. Prüfe FYOS_PLUGIN_QUELLE und deinen Zugang.":
        "The plugin source was not found. Check FYOS_PLUGIN_QUELLE and your access.",
    "Auf dem Datenträger ist kein Platz mehr. `docker system prune` kann helfen.":
        "There is no space left on the disk. `docker system prune` can help.",
    "Docker wurde nicht gefunden. Installiere Docker (Desktop oder Engine) mit Compose und starte neu.":
        "Docker was not found. Install Docker (Desktop or Engine) with Compose and start again.",
    "`docker compose` lässt sich nicht starten ({0}).": "`docker compose` cannot be started ({0}).",
    "Das Compose-Plugin fehlt (`docker compose version` schlägt fehl). Installiere Docker Compose v2.":
        "The Compose plugin is missing (`docker compose version` fails). Install Docker Compose v2.",
    "`docker info` lässt sich nicht ausführen ({0}).": "`docker info` cannot be run ({0}).",
    "Docker läuft nicht. Starte Docker Desktop bzw. den Docker-Dienst und versuche es erneut.":
        "Docker is not running. Start Docker Desktop or the Docker service and try again.",
    "Docker mit Compose ist bereit.": "Docker with Compose is ready.",
    "Start nicht möglich: {0}": "Cannot start: {0}",
    "Die Abnahme konnte nicht laufen: {0}": "The acceptance check could not run: {0}",
    "Dieses Ziel wird vom Installer nicht gestartet.": "The installer does not start this target.",
    "Hub-Bild bauen (kann beim ersten Mal einige Minuten dauern)": "Build the Hub image (can take a few minutes the first time)",
    "Dienste starten": "Start services",
    "`{0}` ist mit Code {1} fehlgeschlagen.": "`{0}` failed with code {1}.",
    "== Gesundheit prüfen": "== Check health",
    "noch nicht bereit": "not ready yet",
    "FYOS läuft: {0}": "FYOS is running: {0}",
    "Zeitlimit erreicht: {0} antwortet nicht. Die Dienste laufen vielleicht noch an; "
    "`docker compose logs` im Zielordner zeigt die Meldungen.":
        "Time limit reached: {0} does not answer. The services may still be starting; "
        "`docker compose logs` in the target folder shows the messages.",
    # web.py
    "auswahl muss eine Liste von Baustein-ids sein": "auswahl must be a list of building block ids",
    "== Dateien nach {0} schreiben": "== Write files to {0}",
    "Dateien sind fertig. Die nächsten Schritte stehen in ANLEITUNG.md.": "The files are ready. The next steps are in ANLEITUNG.md.",
    "Dateien erzeugt. Weiter mit ANLEITUNG.md im Zielordner.": "Files generated. Continue with ANLEITUNG.md in the target folder.",
    "Host nicht erlaubt.": "Host not allowed.",
    "Zugang nur mit dem Link, den fyos-install ausgibt.": "Access only with the link that fyos-install prints.",
    "Erwartet wird ein JSON-Objekt.": "A JSON object is expected.",
    "Es läuft bereits eine Installation.": "An installation is already running.",
    "Sprache: en oder de": "Language: en or de",
    "Nicht gefunden.": "Not found.",
    "Kein solches Bild.": "No such image.",
    "FYOS-Installer läuft. Öffne diesen Link (gilt nur für diese Sitzung):": "The FYOS installer is running. Open this link (valid for this session only):",
    "Beenden mit Strg+C.": "Stop with Ctrl+C.",
    "Beendet.": "Stopped.",
    # tui.py
    "Willkommen": "Welcome", "Ziel": "Target", "Bausteine": "Building blocks", "Einrichten": "Set up",
    "Zusammenfassung": "Summary", "Installieren": "Install",
    "FEHLER: ": "ERROR: ", "GESTARTET, ABER NICHT ABGENOMMEN: ": "STARTED, BUT NOT ACCEPTED: ", "FERTIG: ": "DONE: ",
    "Wohin soll FYOS?": "Where should FYOS go?",
    "Bausteine (Leertaste wählt)": "Building blocks (space selects)",
    "* = immer dabei": "* = always included",
    "Zielordner": "Target folder",
    "Zurück": "Back", "Weiter": "Next", "Beenden": "Quit",
    "Weiter (auch im Textfeld)": "Next (also in a text field)", "Zurück (auch im Textfeld)": "Back (also in a text field)",
    "Schritt {0} von {1}: {2}": "Step {0} of {1}: {2}",
    "Weiter zum Installieren": "Continue to install",
    " Du kannst trotzdem nur Dateien erzeugen.": " You can still generate files only.",
    "Erzeugt ein Kustomize-Overlay; angewendet wird mit kubectl, von dir.": "Generates a Kustomize overlay; you apply it yourself with kubectl.",
    "Schreibt Dateien und eine Anleitung; gestartet wird später von dir.": "Writes files and a guide; you start FYOS yourself later.",
    "Was daraus wird": "What you get",
    "Voraussetzungen:": "Requirements:",
    " (gibt es noch nicht)": " (does not exist yet)",
    "aus: nicht einrichten": "off: do not set up",
    "[b]{0}[/b]: welche Stufe? (Vorgabe für dieses Ziel: {1})": "[b]{0}[/b]: which tier? (default for this target: {1})",
    "Dein Agent": "Your agent", "Name des Agenten": "Name of the agent", "Wesen": "Character", "Dein Name": "Your name",
    "Sprache": "Language",
    "[b]Sprachmodell[/b] (OpenAI-kompatibel)": "[b]Language model[/b] (OpenAI-compatible)",
    "Basis-Adresse": "Base address", "Modellname": "Model name",
    "Schlüssel (leer, wenn keiner nötig)": "Key (empty if none is needed)",
    "[b]Bezug der Pakete und Bilder[/b] (Vorgaben aus FYOS_PAKETINDEX, FYOS_PLUGIN_QUELLE, FYOS_REGISTRY, FYOS_BILD_TAG)":
        "[b]Package source and images[/b] (defaults from FYOS_PAKETINDEX, FYOS_PLUGIN_QUELLE, FYOS_REGISTRY, FYOS_BILD_TAG)",
    "Bezug: index oder git": "Source: index or git",
    "Index-URL (bei Bezug index)": "Index URL (with source index)",
    "Zum Beispiel https://git.example.com/api/packages/org/pypi/simple (uv fragt ihn vor PyPI)":
        "For example https://git.example.com/api/packages/org/pypi/simple (uv asks it before PyPI)",
    "Plugin-Quelle (bei Bezug git)": "Plugin source (with source git)",
    "Bild der Oberfläche": "Interface image", "Basisbild des Hubs": "Base image of the Hub", "Bild des Agenten": "Image of the agent",
    "Hub-Bild in deiner Registry": "Hub image in your registry",
    " (gilt nur bei der {0})": " (only applies with the {0})",
    "Bitte prüfen:": "Please check:",
    "Dateien erzeugen": "Generate files",
    "**Ziel:** {0}": "**Target:** {0}", "**Bausteine:** ": "**Building blocks:** ",
    "Stufe je Fähigkeit": "Tier per capability",
    "Die Grundstufe braucht keinen eigenen Dienst, die Ausbaustufe einen:":
        "The basic tier needs no service of its own, the extended tier does:",
    "  Adresse in `{0}`: ": "  Address in `{0}`: ",
    "gesetzt.": "set.",
    "noch leer, trage sie selbst ein; den Dienst liefert der Installer noch nicht mit.":
        "still empty, enter it yourself; the installer does not ship the service yet.",
    "Reifegrad": "Maturity",
    "Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet:": "Four layers with three levels each, derived from your choice:",
    "- **{0}**: Stufe {1} von {2} ({3}). Erkennbar: {4}": "- **{0}**: level {1} of {2} ({3}). Recognisable: {4}",
    "Dateien": "Files", "Befehle": "Commands", "Hinweise": "Notes",
    (  # tui.WILLKOMMEN
        "# Willkommen bei FYOS\n\n"
        "FYOS ist dein persönliches Betriebssystem im Browser, aufgebaut auf einem eigenen Agenten.\n"
        "Du wählst, was du brauchst, und liest vorher, was daraus wird.\n\n"
        "Nichts wird geschrieben oder gestartet, bevor du es im letzten Schritt bestätigst.\n\n"
        "Bedienung: **n** weiter, **b** zurück, **q** beenden, Tab wechselt zwischen den Feldern.\n"
    ): (
        "# Welcome to FYOS\n\n"
        "FYOS is your personal operating system in the browser, built around an agent of your own.\n"
        "You choose what you need and read beforehand what you get.\n\n"
        "Nothing is written or started before you confirm it in the last step.\n\n"
        "Keys: **n** next, **b** back, **q** quit, Tab moves between the fields.\n"
    ),
}

# Titel und Kurztexte der Bausteine und Fähigkeiten (katalog.yaml, katalog_stufen.yaml).
KATALOG_EN: dict[str, str] = {}
