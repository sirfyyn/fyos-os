# FYOS erweitern

Eine Anleitung für alle, die FYOS — For Your Own Sake um eigene Fähigkeiten, Oberflächen, Wissen oder Verhalten
ergänzen wollen, ohne die Distribution zu verändern. Die Beispiele sind gegen den Code dieses Standes geprüft; wo ein
Weg noch nicht fertig ist, steht **(im Aufbau)** dabei.

Zu dieser Anleitung gehört ein lauffähiges Muster: das Repo **`fyos-plugin-vorlage`**. Es macht genau das, was hier
beschrieben ist (Werkzeuge, App, Skill, Katalogeintrag, Tests, CI), und lässt sich mit `python3 umbenennen.py <name>` in
ein eigenes Plugin verwandeln. Wer lieber abschreibt als liest, beginnt dort.

Inhalt: 1 Überblick · 2 Hub-Plugin · 3 Oberfläche · 4 Wissen für den Agenten · 5 Agentenverhalten · 6 Shell ·
7 Installer-Katalog · 8 Begleitdienste · 9 Testen · 10 Ausliefern · 11 Checkliste

---

## 1. Überblick

FYOS besteht aus Schichten (siehe `ARCHITEKTUR.md`). Jede hat einen eigenen, kleinen Erweiterungspunkt:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ dein Plugin-Repo     fyos-plugin-<name>                                     │
│   Python-Paket       Hub-Plugin (Werkzeuge) + ui://-Oberfläche + Skills     │  §2 §3 §4
│   fyos-katalog.yaml  Eintrag im Installer                                   │  §7
│   begleiter/, dienst/  Skripte auf anderen Geräten, eigene Container        │  §8
│   shell/*.ts         Flächen für die Shell                                  │  §6
├────────────────────────────────────────────────────────────────────────────┤
│ fyos-os              hub/   MCP-Hub, lädt Plugins über Entry-Points         │
│                      web/   Shell: Apps vom Hub, registriereFlaechen,       │  §6
│                             fyos.config.json                                │
│                      installer/  Katalog, Bilder, Erzeugung der Dateien     │  §7
├────────────────────────────────────────────────────────────────────────────┤
│ fyos-agent           Verhaltensvertrag, Workspace-Vorlagen, fyos.yaml,      │  §4 §5
│                      OpenClaw-Verhaltens-Plugins                            │
└────────────────────────────────────────────────────────────────────────────┘
```

Die Grundregel: **Was ein bestimmtes Zuhause, ein Konto oder eine Person braucht, ist ein Plugin in einem eigenen Repo.**
Die Distribution bleibt allgemein. Ein Plugin muss deshalb weder `hub/`, `web/` noch `fyos-agent` ändern.

### Ich will … → nimm …

| Ich will … | nimm … | siehe |
|---|---|---|
| dass der Agent und die Apps etwas Neues **können** (Daten holen, ein Gerät schalten, einen Dienst fragen) | ein **Hub-Plugin** mit Werkzeugen | §2 |
| ein **Fenster oder eine Kachel** dazu in der Shell | eine **Hub-App** (`ui://`-Oberfläche am Werkzeug) | §3 |
| dass die App zeigt, **wie frisch ihre Daten sind**, und ein Knopf **nichts Schreibendes ohne Rückfrage** auslöst | `App.frische` und `App.beantragen` der Brücke; Schweres nur als Bitte an Agent oder Mensch | §3.6 |
| dem Agenten beibringen, **wann und in welcher Reihenfolge** er die Werkzeuge nutzt | einen **Skill** (`SKILL.md`) im Plugin | §4 |
| eine Regel, die für **jedes** Gespräch gilt („immer erst fragen, wenn …“) | **Verhaltensvertrag und Workspace-Vorlagen** in `fyos-agent` | §4, §5 |
| eine Regel, die ein Prompt **nicht überreden** kann (Budget, Ruhezeit, Sperre) | ein **OpenClaw-Verhaltens-Plugin** | §5 |
| Name, Wesen, Sprache, Grenzen des Agenten ändern | **`fyos.yaml`** | §5 |
| eine vorhandene Webseite oder einen Dienst (Git, Grafana) im OS erreichen | **`fyos.config.json`** (`extern`) | §6 |
| eine eigene Seite oder Solid-Komponente als Fläche in der Shell | **`registriereFlaechen`** in `web/src/plugins/` | §6 |
| dass mein Baustein im **Installer** wählbar ist, mit Bild und Erklärung | **`fyos-katalog.yaml`** | §7 |
| ein Programm auf dem **Mac** oder einem anderen Gerät, das Daten liefert | **Begleitskript** | §8 |
| einen **eigenen Dienst** mit Datenbank oder Rechenlast | **Container** neben dem Hub, das Plugin spricht ihn an | §8 |
| etwas **regelmäßig** tun lassen, das Daten holt oder abgleicht | einen **Takt im Hub-Plugin**, gemeldet über `zeitplan()`; mit Tageslimit und Zeitfenster über den Wächter | §2.4, §2.12 |
| etwas regelmäßig tun lassen, das das **Modell** braucht (zusammenfassen, schreiben) | einen **Cron-Auftrag in OpenClaw**; er erscheint in `mcp.zeitplan` neben den Takten | `KOPPLUNG-OPENCLAW.md` |
| Arbeit **verfolgen**, die über ein Gespräch hinausgeht | **Vorgänge**; ohne Vorgangs-Dienst das Workboard von OpenClaw, das der Hub als Vorgänge zeigt | `KOPPLUNG-OPENCLAW.md` |

Ein typisches Vorhaben nutzt mehrere Punkte zugleich. „Wetter“ zum Beispiel: Hub-Plugin `wetter` (§2) mit einer App
(§3), einem Skill (§4) und einem Katalogeintrag (§7) in einem Repo `fyos-plugin-wetter`.

---

## 2. Hub-Plugin Schritt für Schritt

Ein Hub-Plugin ist eine Python-Klasse, die `mcp_hub.plugin.HubPlugin` erweitert. Der Hub lädt sie im eigenen Prozess
(kein Netzaufruf zwischen Hub und Plugin) und bietet ihre Werkzeuge dem Agenten (MCP unter `/mcp`), der Shell
(`/hub/app-call`) und Skripten (`/hub/call`) an. Die Wege stehen in `HUB-VERTRAG.md`.

### 2.1 Paketstruktur

```text
fyos-plugin-wetter/
├── pyproject.toml                  Paket + Entry-Point
├── fyos_plugin_wetter/
│   ├── __init__.py
│   ├── plugin.py                   die Klasse WetterPlugin
│   ├── ui/wetter.html              (optional) die Oberfläche, siehe §3
│   └── skills/wetter/SKILL.md      (optional) Wissen für den Agenten, siehe §4
├── tests/test_plugin.py
└── tools/sauber.py, .sauber/       Sauberkeits-Prüfung, siehe §9
```

Der Paketname beginnt mit `fyos-plugin-` (der Installer erkennt Plugin-Pakete daran, §7), das Python-Paket mit
`fyos_plugin_`. Das Muster `fyos-plugin-vorlage` hat genau diese Gestalt.

### 2.2 pyproject.toml mit Entry-Point

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "fyos-plugin-wetter"
version = "0.1.0"
description = "Wetter für FYOS"
requires-python = ">=3.11"
dependencies = ["fyos-hub"]

[project.optional-dependencies]
test = ["pytest>=8"]

# Der Hub lädt jedes installierte Paket dieser Gruppe von selbst, ohne Eintrag in seiner Konfiguration.
[project.entry-points."mcp_hub.plugins"]
wetter = "fyos_plugin_wetter.plugin:WetterPlugin"

# (optional) Skills im Unterordner skills/ des Pakets, siehe §4.2
[project.entry-points."fyos.skills"]
wetter = "fyos_plugin_wetter"

[tool.setuptools]
packages = ["fyos_plugin_wetter"]

[tool.setuptools.package-data]
fyos_plugin_wetter = ["ui/*", "skills/*/*.md"]   # Oberflächen und Skills gehören ins Paket

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Der Name links vom `=` ist der Entry-Point-Name; er soll dem `name` der Klasse entsprechen. Wegen
`package-data` landen die HTML-Dateien im installierten Paket.

### 2.3 Das kleinste Plugin

```python
# fyos_plugin_uhr/plugin.py
from datetime import datetime, timezone

from mcp_hub.plugin import HubPlugin, ToolDescriptor


class UhrPlugin(HubPlugin):
    name = "uhr"                      # Präfix aller Werkzeug-IDs: uhr.jetzt
    description = "Sagt die Uhrzeit."
    version = "0.1.0"

    def register(self) -> None:
        pass                          # einmal beim Start: Verbindungen aufbauen, Zugangsdaten lesen

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="jetzt",
                description="Aktuelle Uhrzeit (UTC). Nur lesend.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                tags=["uhr", "read"],
            )
        ]

    def call(self, method: str, args: dict) -> dict:
        if method == "jetzt":
            return {"zeit": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        raise ValueError(f"uhr hat kein Werkzeug {method!r}")
```

Das reicht: `uv pip install -e .` (warum uv statt pip: §10.3), Hub starten, `uhr.jetzt` ist da.

### 2.4 Die Methoden von `HubPlugin`

| Methode | Pflicht | Wann und wozu |
|---|---|---|
| `register()` | ja | einmal beim Start, zuerst. Verbindungen aufbauen, Zugangsdaten lesen. Wirft sie, wird **dieses** Plugin nicht geladen; der Hub läuft weiter, der Grund steht unter „nicht geladen“ (`/hub/health`, App „MCP“). |
| `init()` | nein | danach, für Aufsetzen, das von anderen Plugins abhängt. Gleiche Folgen bei einem Fehler. |
| `describe_tools()` | ja | alle Werkzeuge als `ToolDescriptor`. Wird einmal aufgerufen und zwischengespeichert, muss stabil sein. |
| `describe_resources()` | nein | die `ui://`-Oberflächen (§3). |
| `call(method, args)` | ja | führt das Werkzeug aus. `method` ist der Name **ohne** Plugin-Präfix, `args` das Argument-Objekt. Die Rückgabe muss JSON-fähig sein. |
| `health()` | nein | `{"ok": bool, …}`; fragt der Hub bei jeder Karte ab. Nicht im Sekundentakt Fremddienste treffen: `mcp_hub.plugin.tiefe_health` hält ein Ergebnis eine Zeit lang. |
| `metrics()` | nein | Kennzahlen für `/metrics` (Prometheus). Zahlen im Dict erscheinen als `fyos_plugin_wert{plugin, schluessel}`; eigene Reihen mit Labels unter `"_proben"`: `[{"name": "fyos_wetter_abrufe_total", "wert": 3, "labels": {"ort": "x"}, "typ": "counter", "hilfe": "…"}]`. Wird oft gerufen: nur Gemerktes zurückgeben. |
| `zeitplan()` | nein | wiederkehrende Aufgaben des Plugins, etwa `[{"id": "abruf", "name": "Wetter holen", "takt": "alle 15 min", "letzter": 1760000000.0, "letzter_status": "ok"}]`. Sie erscheinen in `mcp.zeitplan` neben den Cron-Aufträgen des Agenten und in `/metrics`. Wer einen Takt hat, meldet ihn hier. Tageslimit, Zeitfenster und Laufprotokoll für einen Takt: §2.12. |
| `skills_beitrag()` | nein | Skills, die nicht als Datei im Paket liegen (etwa von einem angebundenen Dienst): `[{"name", "beschreibung", "text"}]` oder statt `text` ein Aufruf `lesen`. Skills als Dateien im Paket (§4.2) brauchen das nicht. |
| `registry_anbinden(registry)` | nein | einmal nach dem Laden aller Plugins: das Register, falls das Plugin andere Plugins oder die Aufruf-Haken (`registry.on_call_hooks`) braucht. Selten nötig. |
| `shutdown()` | nein | beim Beenden: Verbindungen schließen. Fehler werden geschluckt. |
| `routen()` | nein | eigene HTTP-Wege als Liste von Starlette-`Route`, nur unter `/hub/`, zum Beispiel `Route("/hub/meins/melden", fn, methods=["POST"])`. Für Dinge, die kein Werkzeug sein sollen (Telemetrie eines Clients); ein schon belegter Weg wird abgelehnt (Hub-Vertrag §4). |

Klassenattribute: `name` (eindeutig im Hub, kleingeschrieben, Ziffern und Unterstriche, nie zwei Unterstriche in Folge),
`description` (ein Satz, erscheint in der Werkzeugkarte), `version` (SemVer) und `argumente_vertraulich` (Vorgabe
`False`). Setze es auf `True`, wenn Argumente deiner Werkzeuge Zugangsdaten oder Persönliches tragen können, etwa
Namen von Tresor-Einträgen oder Notizen: Der Ereignisbus (`event_bus_publisher`, Ströme `bus.tool.*`) veröffentlicht
sie dann nur als `{"redacted": true}`, egal welche Konfiguration der Betreiber zusammengestellt hat.

Der Aufruf von `call` läuft in einem eigenen Faden mit Zeitlimit. Schreibe deshalb **synchronen**, thread-sicheren
Code und setze bei Netzaufrufen eigene Timeouts (das Limit des Hubs ist das Netz darunter, kein Ersatz).

### 2.5 Werkzeug-IDs und Namen

- Die ID ist `<plugin>.<werkzeug>` (`wetter.vorhersage`). Der Agent und Skripte nutzen sie so.
- Als MCP-App heißt dasselbe Werkzeug `<plugin>__<werkzeug>` (`wetter__vorhersage`); so stehen Namen in Deeplinks (§3).
- Werkzeugnamen: kleingeschrieben, Unterstriche, kein Punkt, kein doppelter Unterstrich.
- **Die IDs sind deine Schnittstelle.** Skills, Deeplinks und gespeicherte Anordnungen der Shell verweisen auf sie.
  Benenne ein veröffentlichtes Werkzeug nicht um; füge ein neues hinzu und behalte das alte eine Version lang.
- Zwei Werkzeuge gleicher ID oder zwei Plugins gleichen Namens sind ein Fehler.

### 2.6 `ToolDescriptor`: Beschreibung, Schema, Tags

```python
ToolDescriptor(
    name="notiz_setzen",
    title="Notiz setzen",                      # Anzeigename (optional)
    description="Speichert eine kurze Notiz … Mit `__dry_run__: true` kommt nur der Plan zurück.",
    input_schema={                             # JSON Schema (MCP inputSchema)
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1, "description": "Die Notiz"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    tags=["vorlage", "write", "flaeche"],
    meta=None,                                 # Oberfläche und Identität, siehe §3
    zeitlimit_s=None,                          # None = 120 s des Hubs, 0 = kein Limit
)
```

- **`description`** ist die wichtigste Zeile. Der Agent findet dein Werkzeug über sie (Suche nach Alltagswörtern). Schreibe,
  was es tut, was es liefert und was es **nicht** tut, mit den Wörtern, die jemand benutzt („Notiz“, nicht „Entität“).
- **`input_schema`**: Beschreibe jedes Feld (`description`), nenne Pflichtfelder (`required`). Mit
  `"additionalProperties": False` prüft der Hub zentral, dass kein unbekanntes Argument durchrutscht (sonst bekäme der
  Aufrufer ein Ergebnis für eine Frage, die er nie gestellt hat). **Typen, Grenzen und Pflichtfelder prüft der Hub
  nicht; das tut dein Plugin in `call`.**
- **Tags** legen den *Scope* fest, genau einer davon: `read` (liest nur), `write` (ändert, umkehrbar), `destructive`
  (löscht oder ist nicht umkehrbar), `exec` (startet Prozesse). Dazu `extern`, wenn das Werkzeug nach außen ruft
  (Internet, Fremddienst), und `flaeche`, wenn die Shell es über `/hub/app-call` rufen darf. Ohne Scope-Tag steht
  das Werkzeug in der Karte als `UNKNOWN`. Mehrere Scope-Tags: das schärfste gilt (`destructive` > `extern` > `exec` >
  `write` > `read`).
- Eigene Tags (`"wetter"`) sind frei und helfen bei der Suche.

### 2.7 Lesend und schreibend

- Ein **lesendes** Werkzeug ändert nichts, auch nicht „nebenbei“ (kein Zähler, kein Cache, der Folgen hat). Nur lesende
  Werkzeuge bekommen einen Deeplink „In FYOS öffnen“ und dürfen von der Shell beim Öffnen einer App von selbst gerufen
  werden. Ein Link löst nie etwas Schreibendes aus.
- Ein **schreibendes** Werkzeug bekommt `write` oder `destructive`. Der Hub erzwingt keine Freigabe; die Grenze zieht der
  Agent nach seinem Betriebskonzept („Schweres entscheidet der Besitzer“) und die Rechte, die dein Plugin selbst hat.
  Gib dem Plugin darum nur die Rechte, die es braucht (ein Token mit Leserecht, wo Lesen genügt), und zerlege Gefährliches
  in kleine, gut benannte Werkzeuge statt in eines mit einem `modus`-Argument.
- Soll ein schreibendes Werkzeug nur die Oberfläche rufen, nicht das Modell, setze `visibility` (§3).

### 2.8 Trockenlauf

Schreibende Werkzeuge sollen vorab zeigen, was sie täten. Der Hub kennt dafür ein Argument: `__dry_run__: true`.

```python
from mcp_hub.plugin import build_dry_run_result, is_dry_run


def call(self, method, args):
    if method == "notiz_setzen":
        return self.notiz_setzen(args.get("text"), trocken=is_dry_run(args))
    raise ValueError(f"vorlage hat kein Werkzeug {method!r}")


def notiz_setzen(self, text, trocken=False):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text fehlt")
    if trocken:
        return build_dry_run_result(
            would_execute=f"Notiz mit {len(text.strip())} Zeichen speichern",
            expected_side_effects=["fyos:vorlage:notiz: ersetzt"],     # "<Ressource>: <Änderung>"
            estimated_cost=1,                                          # frei wählbare Einheit, sonst None
            plugin=self.name,
            method="notiz_setzen",
            args_preview={"text": text.strip()[:40]},                  # ohne Geheimnisse und große Blöcke
        )
    ...  # wirklich schreiben
```

- Im Trockenlauf **nichts** ändern, auch kein Protokoll, keinen Zähler.
- Ein Plugin, das keinen Trockenlauf kann, antwortet `build_dry_run_unsupported(self.name, method)` statt zu schreiben.
- `__dry_run__` ist auch bei `additionalProperties: False` erlaubt. Der Trockenlauf gehört in jedes `write`, `destructive`
  und `exec`-Werkzeug; erst das macht es für den Agenten und für „Nur prüfen“-Knöpfe in der Oberfläche sicher.
- Ruft eine Oberfläche das Werkzeug, verlangt es für den **echten Lauf** zusätzlich `bestaetigt: true` (ein Feld im
  Schema, Wahrheitswert) und lehnt sonst mit `ValueError` ab: erst der Plan, dann die Bestätigung, wie bei
  `werkstatt.ausfuehren`. Die Oberfläche macht das mit `App.beantragen` von selbst (§3.6).

### 2.9 Konfiguration und Geheimnisse

**Konfiguration.** Der Hub reicht den Block `config:` des Plugins an den Konstruktor weiter, wenn er einen Parameter
`config` hat:

```python
def __init__(self, config: dict | None = None):
    super().__init__()
    self.config = dict(config or {})

def _wert(self, schluessel: str, umgebung: str, vorgabe: str) -> str:
    # Reihenfolge: Plugin-config vor Umgebung vor Vorgabe
    return str(self.config.get(schluessel) or os.getenv(umgebung) or vorgabe)
```

Vorgaben im Code sollen neutral und ohne Fremdadressen sein; was zu einer Installation gehört, kommt aus `config:` oder
der Umgebung. Der Installer (§7) schreibt Katalogfelder als Umgebungsvariablen, darum liest ein Plugin dieselben Werte
auch aus der Umgebung (`FYOS_<NAME>_<FELD>`).

```yaml
# config.yaml des Hubs (MCP_HUB_CONFIG_PATH); ein Eintrag ist nur für Konfiguration/Geheimnisse/Abschalten nötig
plugins:
  - name: wetter
    config:
      ort: Musterstadt
    secrets:
      - { name: wetter-token, env: FYOS_WETTER_TOKEN }
    # enabled: false        # schaltet ein installiertes Plugin ab
```

**Geheimnisse.** Unter `secrets:` steht nur der **Name**. Der Hub löst ihn auf (der Reihe nach: die Variable `env`, die
Variable mit dem Namen, dessen Umgebungsform `WETTER_TOKEN`, die Datei `/run/secrets/<name>`) und legt den Wert als
Umgebungsvariable ab, wo dein Plugin ihn mit `os.getenv` liest (eine schon gesetzte Variable gewinnt). Regeln:

- Das Geheimnis steht nie im Code, nie in `config:`, nie im Repo, nie in einem Werkzeugergebnis und nie im Log.
- `health()` meldet höchstens `{"token": true}`, nie den Wert.
- Gib Fehlermeldungen von Fremddiensten nur gekürzt weiter; sie enthalten manchmal die Anfrage samt Kopfzeile.

### 2.10 Fehlerbehandlung

Der Hub fängt jede Ausnahme und macht daraus eine Antwort; ein Plugin kann den Hub nicht umwerfen.

| Du tust … | Der Hub meldet … | HTTP | Schutzschalter |
|---|---|---|---|
| `raise ValueError("limit muss …")` | `kind: bad_arguments` | 400 | zählt **nicht** |
| andere Ausnahme (`RuntimeError`, Netzfehler, …) | `kind: plugin_error` | 502 | zählt |
| `return {"ok": False, "error": "…"}` oder `{"error": "…"}` ohne `ok` | `kind: tool_failed`, dein Ergebnis hängt an | 502 | zählt nicht |
| läuft länger als das Zeitlimit | `kind: timeout` | 504 | zählt |
| `raise KontoFehlt(anbieter, name, link)` | `kind: konto_fehlt` mit dem Link zum Verbinden | 502 | zählt nicht |
| unbekanntes Argument bei `additionalProperties: False` | `kind: bad_arguments` | 400 | zählt nicht |

Folgerungen:

- **Eingabefehler sind `ValueError`** mit einem Satz, den der Agent versteht (`"text ist zu lang (400 Zeichen, höchstens 280)"`).
  Zu viele echte Ausfälle sperren das Plugin vorübergehend (fünf Fehler in Folge, 30 s `circuit_open`, 503); falsche
  Eingaben dürfen das nie auslösen.
- Ein Lesefehler vom Upstream (`json.JSONDecodeError`, `UnicodeError`) ist ein Ausfall, kein Eingabefehler, auch wenn
  es ein `ValueError` ist.
- Ein *erwartbares* „geht nicht“ (Gerät aus, kein Treffer) kann ein normales Ergebnis sein (`{"gefunden": False}`) oder
  `{"ok": False, "error": "…"}`; wähle, was dem Aufrufer hilft.
- Meldet ein Dienst, dass der Mensch erst ein Konto verbinden muss, wirf `mcp_hub.plugin.KontoFehlt`. Der Mensch bekommt
  den Link; Token landen nie im Chat.
- Liefere **kleine** Ergebnisse. Große Antworten kürzt der Hub und gibt eine `ergebnis_id` zurück (`hub__mehr` vertieft).
  Ein Satz `"satz": "3 Termine heute."` in jedem Ergebnis hilft dem Agenten und den Oberflächen.

### 2.11 Daten ablegen

Für wenig Zustand gibt es `mcp_hub.kv.klient()`: Redis, wenn `REDIS_URL` gesetzt ist, sonst eine Attrappe im Speicher des
Prozesses (überlebt keinen Neustart, gilt nur für einen Hub-Prozess). Nutze Schlüssel mit eigenem Präfix
(`fyos:<plugin>:…`). Für Daten, die bleiben sollen, brauchst du Redis oder einen eigenen Dienst (§8).

### 2.12 Takte begrenzen und protokollieren

Der Hub hat keinen zentralen Zeitplaner: Ein Plugin fährt seine Takte selbst (ein Faden, der wartet und arbeitet) und
meldet sie über `zeitplan()`. Damit eine Routine nachts nicht läuft und nicht ohne Ende, gibt es einen kleinen Wächter,
`mcp_hub.takt.Waechter`. Er kennt zwei Grenzen je Takt, beide optional:

| Grenze | Bedeutung |
|---|---|
| `max_pro_tag` | höchstens so viele Läufe je Kalendertag (ganze Zahl ab 1) |
| `fenster` | nur zwischen diesen Uhrzeiten, `"07:00-22:00"` (Anfang eingeschlossen, Ende ausgeschlossen); über Mitternacht geht auch (`"22:00-06:00"`), als Ende ist `"24:00"` erlaubt |

Ein Lauf außerhalb des Fensters oder über dem Limit **findet nicht statt**: Der Wächter ruft die Aufgabe nicht und zählt
den Grund (`fenster` oder `limit`). Das Fenster wird zuerst geprüft; was außerhalb liegt, verbraucht nichts vom
Tageslimit. Tag und Uhrzeit gelten in der Zeitzone des Hub-Prozesses (Umgebungsvariable `TZ`, ohne Angabe UTC; in
Compose setzt die `.env` sie, in Kubernetes ein `env`-Eintrag am Hub). Ohne Grenzen läuft jeder Lauf wie vorher.

```python
from mcp_hub import takt

class WetterPlugin(HubPlugin):
    def __init__(self, config: dict | None = None):
        super().__init__()
        # config:  takt_grenzen: { abruf: { max_pro_tag: 48, fenster: "06:00-23:00" } }
        # takte=… fängt Tippfehler beim Start ab: ein falscher Name oder eine unlesbare Uhrzeit verhindert das Laden
        self._waechter = takt.Waechter(self.name, (config or {}).get("takt_grenzen"), takte=("abruf",))
        self._halt = threading.Event()

    def _schleife(self) -> None:                      # läuft im eigenen Faden
        while not self._halt.wait(900):
            try:
                self._waechter.ausfuehren("abruf", self._abrufen)   # übersprungen: Lauf(gelaufen=False, grund="fenster"|"limit")
            except Exception:
                pass                                  # der Fehler steht schon im Laufprotokoll

    def zeitplan(self) -> list[dict]:
        return [{"id": "abruf", "name": "Wetter holen", "takt": "alle 15 min", **self._waechter.felder("abruf")}]
```

`ausfuehren(takt, tun)` gibt `Lauf(gelaufen, grund, wert)` zurück. Wirft `tun`, geht die Ausnahme unverändert weiter,
nachdem sie im Protokoll steht; ein Ergebnis `{"ok": False, …}` gilt dort als Fehler. Ein Aufruf auf Abruf (ein
Werkzeug, das jemand ruft) ist kein Takt und läuft ohne den Wächter.

**Laufprotokoll.** Jeder Lauf trägt Start, Dauer und Ergebnis in den Hub-Speicher ein (`mcp_hub.kv`, §2.11): eine Liste
der letzten 20 Läufe je Takt (läuft nach einer Woche ohne Lauf ab) und einen Tageszähler (läuft nach drei Tagen ab).
Fehlertexte stehen gekürzt und ohne Zugangsdaten darin. Der Speicher ist nur Zubehör: Antwortet er nicht, läuft der Takt
trotzdem; der Wächter zählt den Tag dann im Prozess weiter und lässt den Speicher 30 s in Ruhe. Ohne `REDIS_URL`
gelten die Zähler nur bis zum Neustart des Hubs.

**Was man sieht.** `felder(takt)` hängt an den Eintrag von `zeitplan()`: `max_pro_tag`, `fenster`, `ruht` (`fenster`
oder `limit`, wenn der Takt jetzt nicht laufen dürfte), `laeufe_heute`, `uebersprungen` (heute, je Grund) und `protokoll`
(die letzten fünf Läufe). `mcp.zeitplan` zeigt sie, `/metrics` führt sie als `fyos_zeitplan_laeufe_heute{takt}`,
`fyos_zeitplan_max_pro_tag{takt}` und `fyos_zeitplan_uebersprungen_total{takt, grund}` (`takt` ist die Kennung
`<plugin>:<id>` aus `mcp.zeitplan`). Das eingebaute Plugin `openclaw` macht es vor: `takt_grenzen` in seiner `config`
(`KOPPLUNG-OPENCLAW.md` §5).

Die Cron-Aufträge des Agenten laufen in OpenClaw; ihre Zeiten stellt man dort ein, im Hub erscheinen sie nur. Fenster und
Tageslimit gelten für Takte, die der Hub selbst fährt.

---

## 3. Oberfläche (MCP-App, `ui://`)

Eine Oberfläche ist eine HTML-Datei, die ein Werkzeug „mitbringt“. Die Shell zeigt sie als Fenster (iframe), jeder
MCP-Client mit Unterstützung für MCP-Apps im Gespräch. Du schreibst nur die HTML-Datei und ein paar Zeilen im Plugin;
Fenster, Dock-Eintrag, Kachel, Suche und Deeplink entstehen von selbst.

### 3.1 Ressource und Werkzeug verbinden

```python
from mcp_hub.plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from mcp_hub.plugins import _identitaet
from mcp_hub.plugins._identitaet import identitaet
from mcp_hub.plugins._oberflaeche import oberflaeche

UI_URI = "ui://wetter/wetter.html"
UI_DATEI = "wetter.html"

# Titel, Untertitel, Symbol (Lucide-Name aus mcp_hub/plugins/ui/_symbole.json), Farbton 0–359, Kategorie
_identitaet.registriere_app(
    "wetter",
    {"titel": "Wetter", "untertitel": "Vorhersage für heute", "symbol": "sun", "ton": 200, "kategorie": "Wissen"},
    datei=UI_DATEI,
    hauptwerkzeug="wetter__vorhersage",       # das Werkzeug, das die App öffnet
)


class WetterPlugin(HubPlugin):
    ...
    def describe_tools(self):
        meta = {"ui": {"resourceUri": UI_URI}, "app": identitaet("wetter")}
        return [ToolDescriptor(name="vorhersage", description="…", tags=["wetter", "read", "flaeche"], meta=meta)]

    def describe_resources(self):
        return [
            ResourceDescriptor(
                uri=UI_URI,
                name="Wetter",
                description="Vorhersage für heute",
                read=lambda: oberflaeche(UI_DATEI, __package__),     # liest <paket>/ui/wetter.html
                meta={"ui": {"prefersBorder": True}},
            )
        ]
```

- `meta["ui"]["resourceUri"]` macht aus dem Werkzeug eine App. Mehrere Werkzeuge mit **derselben** `resourceUri` sind
  *eine* Fläche in der Shell (ein Fenster, ein Dock-Eintrag).
- `oberflaeche(datei, ui_verzeichnis)` liest die Datei aus `<paket>/ui/` (zweites Argument: Paketname als Text;
  `__package__` überlebt ein Umbenennen) oder aus einem `Path`. Es setzt Stil, Brücke, Kopf und Symbole ein (3.3).
- `registriere_app` muss beim Import laufen (Modulebene in `plugin.py`). Die Kategorien `System`, `Betrieb`, `Wissen`,
  `Beispiele` sind vorhanden; eine neue Kategorie wird mit angelegt.
- Der Hauptwerkzeug-Name ist die Grundlage des Deeplinks, wenn der Host sonst nichts liefert.

### 3.2 Sichtbarkeit

```python
meta = {"ui": {"resourceUri": UI_URI, "visibility": ["app"]}, "app": identitaet("wetter")}
```

- ohne `visibility` oder `["model","app"]`: Modell **und** Oberfläche sehen das Werkzeug;
- `["app"]`: nur die Oberfläche. `/hub/call` und `/mcp` lehnen es mit 403 `nur_oberflaeche` ab (gut für „Löschen“-Knöpfe,
  die der Agent nicht von selbst drücken soll);
- `["model"]`: nur das Modell.

Die Shell ruft Werkzeuge nur über `/hub/app-call`, und das nimmt nur Werkzeuge mit `meta.ui` oder dem Tag `flaeche`.

### 3.3 Die HTML-Datei

Eine Oberfläche ist normales HTML mit drei Markierungen, die der Hub beim Ausliefern ersetzt:

| Markierung | wird ersetzt durch |
|---|---|
| `<style>/*STIL*/ … </style>` | das gemeinsame Aussehen (`_stil.css`); dahinter folgt dein eigenes CSS für das Layout |
| `<script>/*BRUECKE*/ … </script>` | die Brücke zum Host (`App`) und danach dein Skript |
| `<!--KOPF-->…<!--/KOPF-->` | der Kopf der App (Kachel, Titel, Satz) aus der Identität; dazwischen deine Aktionsknöpfe |
| `<svg class="ico" data-symbol="plus"></svg>` | das Symbol (Lucide-Name) mit seinen Linien |

Gerüst (gekürzt aus `fyos-plugin-vorlage/fyos_plugin_vorlage/ui/vorlage.html`):

```html
<!doctype html>
<html lang="de" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wetter</title>
<style>/*STIL*/
  .tafel { padding: 14px 16px; margin: 0 0 14px; }
</style>
</head>
<body>
<!--KOPF-->
  <button id="neu" class="rund drehen" title="Aktualisieren" aria-label="Aktualisieren"><svg class="ico" data-symbol="refresh-cw"></svg></button>
<!--/KOPF-->
<main>
  <div id="inhalt"><div class="laedt">Lädt …</div></div>
</main>
<script>
/*BRUECKE*/
const $ = (id) => document.getElementById(id);
const { esc, zustand, satz } = App;
const rufen = (name, args) => App.rufen("wetter__" + name, args);     // <plugin>__<werkzeug>

async function laden() {
  try {
    const d = await rufen("vorhersage");
    satz(d.satz, "gut");                                               // Zeile im Kopf; Ton: "gut" | "schlecht" | ""
    $("inhalt").innerHTML = `<div class="karte tafel">${esc(d.satz)}</div>`;
  } catch (e) {
    $("inhalt").innerHTML = '<div class="karte">' + zustand({ symbol: "circle-alert", ton: "schlecht", titel: "Fehler", text: App.fehlertext(e), klein: true }) + "</div>";
  }
}

$("neu").addEventListener("click", laden);
// Öffnet der Host die App mit einem Werkzeugergebnis (Shell, Chat), kommt es hier an:
App.auf("ui/notifications/tool-result", (r) => { const d = App.daten(r); if (d && d.satz) { /* anzeigen */ } });
App.start("fyos-wetter").then(() => setTimeout(laden, 1500)).catch(() => {});
</script>
</body>
</html>
```

Die wichtigsten Bausteine der Brücke `App` (vollständige Liste im Kopf von `hub/mcp_hub/plugins/ui/_bruecke.js`):

| Gebiet | Bausteine |
|---|---|
| Aufrufen | `App.rufen(name, args)` → Daten (wirft bei Fehlern), `App.werkzeug(name, args)` → Rohergebnis, `App.daten(ergebnis)`, `App.fehlertext(e)` |
| Start und Ereignisse | `App.start(name)`, `App.auf(methode, fn)`, `App.bei(aktion, fn)` (Klick auf `data-aktion="…"`), `App.takt(ms, fn)` (regelmäßig, nur solange sichtbar) |
| Bausteine | `App.esc`, `App.symbol(name)`, `App.kachel`, `App.marke`, `App.zustand({…})`, `App.satz(text, ton)`, `App.knoepfe`, `App.bestaetigung`, `App.aufklapper` |
| Zeit und Zahl | `App.zeit.vor(ms)`, `.uhr`, `.tag`, `.datum`, `.dauer`, `.voll`, `.stempel`; `App.zahl(x, stellen)` |
| Frische und Anfrage | `App.frische(t, {schwelleMin, text, klasse})`, `App.veraltet(t, schwelleMin)`, `App.beantragen({werkzeug, args, ort, ja, nein, symbol, klasse})`, `App.plan(trockenlauf)` (§3.6) |
| Host | `App.host` (`"fyos"` in der Shell), `App.link(url)`, `App.nachricht(text)` (nur nach Klick), `App.modellKontext({text, daten})` |

Regeln, die der Hub-Test für alle Oberflächen prüft:

- **Kein eigenes Farbschema.** Nutze die Variablen und Klassen des gemeinsamen Stils (`var(--mut)`, `var(--fg)`,
  `.karte`, `.haupt`, `.leise`, `.gefahr`, `.rund`, `.laedt`); dann passt die App in Hell und Dunkel zur Shell.
- **Keine Modaldialoge** (`alert`, `confirm`, `prompt`): das iframe läuft ohne `allow-modals`. Bestätigen geht mit
  `App.bestaetigung(…)`.
- **Formulare nur mit eigenem Handler.** Das iframe erlaubt `allow-forms`, damit das `submit`-Ereignis eines `<form>`
  feuert (Eingabe und Enter); der Handler endet mit `e.preventDefault()`. Ein echtes Absenden gibt es nicht: Die
  Inhaltsregeln der Shell setzen `form-action 'none'`.
- **Alles Eingefügte mit `esc()` maskieren.** Werkzeugergebnisse sind fremder Text.
- **Symbole**: nur Namen aus `mcp_hub/plugins/ui/_symbole.json` (Lucide). Ein Wort in Anführungszeichen im Skript, das
  ein Symbolname ist (`"trash-2"`), wird automatisch mitgeliefert. Ein unbekannter Name wird ein Fenster-Symbol, kein Fehler.
- Rufe in der Oberfläche **nur Werkzeuge deines eigenen Plugins** und nur solche mit `meta.ui` oder `flaeche`.

Zwei weitere Gewohnheiten prüft kein Test, aber jede App der Distribution hat sie: einen **Frische-Stempel** an jedem
Panel mit Daten und eine **Anfrage statt einer direkten Aktion** an jedem Knopf, der etwas schreibt (§3.6).

### 3.4 Größenstufen

Die Shell meldet der App die Größe ihres Rahmens. Daraus bildet die Brücke vier Stufen, die du abfragen kannst:

| Stufe | wann | Gedanke |
|---|---|---|
| `blick` | Höhe < 300 px, oder Breite < 360 px bei Höhe < 420 px | nur das Wichtigste (Kachel auf dem Startbildschirm) |
| `kompakt` | Höhe < 480 px oder Breite < 420 px | enger, kleinere Zahlen |
| `normal` | sonst | wie gebaut |
| `weit` | Breite ≥ 1100 px | Inhalt auf lesbarer Breite (`<body class="breit">` nutzt alles) |

`App.stufe` liefert die aktuelle Stufe, das Fensterereignis `app-stufe` meldet Wechsel,
`App.anzahl({ blick: 2, kompakt: 4, normal: 8, weit: 12 })` sagt, wie viele Einträge passen. Der gemeinsame Stil setzt
die Stufen schon für Abstände und Schriftgrößen um; du musst nur die Länge von Listen anpassen.
In einem Rahmen ohne feste Höhe (Chat) bestimmt die App ihre Höhe selbst und bleibt auf `normal`.

### 3.5 Wie die App in der Shell erscheint

Du registrierst **nichts** in der Shell. Sie fragt `/hub-api/apps` ab (beim Start, alle zwei Minuten, beim Zurückkehren
in den Tab) und bildet daraus Fläche, Dock-Eintrag, Startkachel und Suchtreffer.

- Titel, Untertitel, Symbol, Farbton, Kategorie kommen aus `meta["app"]`.
- Die **Gruppe** im Start ist „Apps“, wenn niemand etwas anderes sagt. Eine Gruppe wählt die Shell über
  `registriereFlaechen({ gruppen: { plugin: { wetter: 'Wissen' } } })` (§6).
- **Heften** an den Startbildschirm geht nur für lesende Werkzeuge ohne Pflichtfelder, die als einzige ihre Oberfläche haben.
- **Deeplink:** `https://<deine-adresse>/os?offen=app:<plugin>__<werkzeug>` öffnet die App,
  `&eingabe=<base64url(JSON der Argumente)>` startet sie mit Argumenten (höchstens 4000 Zeichen JSON; die Shell übernimmt
  sie nur für lesende Werkzeuge). Lesende App-Werkzeuge hängen den Link als letzte Zeile „In FYOS öffnen: …“ an ihr Ergebnis;
  `FYOS_OEFFENTLICH_URL` bestimmt den Ursprung. Beispiel: `/os?offen=app:vorlage__hallo`.
- Ein Agent kann dieselbe App im offenen OS zeigen (OS-Brücke, Befehl `zeigen` mit Ziel `app:<plugin>__<werkzeug>`,
  siehe `HUB-VERTRAG.md` §3).

### 3.6 Frische und Anfrage statt Aktion

Zwei Gewohnheiten, die jede App der Distribution hat. Kein Test erzwingt sie; die Brücke gibt dir beides fertig, und die
Beispiel-App in `fyos-plugin-vorlage` zeigt, wie sie zusammenpassen.

**Frische: jedes Panel sagt, wie alt seine Daten sind.** Eine Zahl ohne Alter lügt, sobald die Quelle stockt. Jedes Panel,
das Daten zeigt, trägt darum einen Stempel mit dem Stand *der Daten* (was die Quelle meldet, nicht der Moment des
Abrufs). Ab einer Schwelle steht „veraltet“ dabei, als Text und in Warnfarbe, nie nur als Farbe:

```js
const stempel = App.frische(d.zeit * 1000, { schwelleMin: 5 });      // d.zeit: Unix-Sekunden aus dem Werkzeugergebnis
$("gruss").innerHTML = `<div class="karte">…<div class="gruss-zeit">${stempel}</div></div>`;
// „Stand vor 2 Min.“  →  nach 5 Minuten ohne neue Daten: „Stand vor 6 Min. · veraltet“
```

- `App.frische(t, {schwelleMin, text, klasse})` liefert ein `<time class="frische">`. `t` ist ISO-Text, Millisekunden,
  Unix-Sekunden oder `Date`. Ohne `schwelleMin` gelten 15 Minuten, `text` ersetzt „Stand“ („Gemessen“). Ohne Zeitpunkt
  steht „Stand unbekannt · veraltet“. Die volle Zeit steht im `title`; die Anzeige rückt alle 30 s von selbst nach und
  kippt allein auf „veraltet“.
- `App.veraltet(t, schwelleMin)` gibt `true` oder `false`, wenn die App selbst etwas daran knüpft.
- Das Werkzeug liefert den Zeitpunkt der Daten mit (`zeit`, `gemessen_am` …). Nennt die Quelle keinen, ist es der Moment
  des Abrufs im Plugin, nicht der im Browser.
- Scheitert ein Neuladen, bleiben die alten Daten mit ihrem **alten** Stempel stehen, und der Satz im Kopf sagt, dass das
  Neuladen nicht klappte. Nicht leeren, den Stempel nicht auf „jetzt“ setzen.

**Anfrage statt Aktion: ein Knopf löst nie direkt etwas Schreibendes aus.** Drei Stufen, je nach Gewicht der Wirkung:

| Stufe | Was der Knopf tut | Beispiele |
|---|---|---|
| 1 Lesen | ruft das Werkzeug direkt, auch als Trockenlauf (`__dry_run__`) | Aktualisieren, Filtern, „Nur prüfen“ |
| 2 Kleines, Umkehrbares | stellt eine **Anfrage**: Trockenlauf, Plan anzeigen, erst nach „Ja“ der echte Lauf | Notiz speichern, Eintrag umbenennen |
| 3 Schweres | löst nichts aus, sondern **bittet**; der Agent oder der Mensch entscheidet im Freigabeweg | Geld, Löschen, Nachrichten nach außen, Prozesse starten |

Stufe 2 steckt in der Brücke. Die App ruft `App.beantragen`, die Brücke macht den Rest:

```js
// im HTML ein Platz für die Rückfrage:  <div id="antrag"></div>
$("formular").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const r = await App.beantragen({ werkzeug: "vorlage__notiz_setzen", args: { text: $("text").value.trim() }, ort: $("antrag"), ja: "Speichern" });
    if (r) { $("text").value = ""; await laden(); }       // null: abgebrochen oder von einem neuen Antrag abgelöst
  } catch (e) { satz(App.fehlertext(e), "schlecht"); }
});
```

1. Die Brücke ruft das Werkzeug mit `__dry_run__: true`. Es ändert nichts und liefert den Plan (`would_execute`,
   `expected_side_effects`, §2.8).
2. Die Rückfrage erscheint in `ort`: der Plan als Satz, die Wirkungen darunter (`App.plan(…)` baut den Text), dazu „Ja“
   (Beschriftung aus `ja`, Vorgabe „Ausführen“; `symbol` und `klasse` gelten für diesen Knopf, bei Löschen `"gefahr"`) und
   „Abbrechen“ (Beschriftung aus `nein`).
3. Erst nach „Ja“ ruft sie das Werkzeug wirklich, mit `bestaetigt: true` und ohne `__dry_run__`. Das Versprechen ergibt das
   Ergebnis des echten Laufs, bei „Abbrechen“ `null`. Fehler kommen als lesbarer Text (`App.fehlertext`).
4. Es gibt nur einen offenen Antrag: ein neuer löst den offenen ab (dessen Versprechen ergibt `null`); solange eine
   Ausführung läuft, weist die Brücke einen neuen ab.
5. Liefert das Werkzeug keinen Plan (es meldet `dry_run_unsupported` oder ignoriert das Signal), wirft `beantragen` und
   die Oberfläche fragt gar nicht erst: Ein Mensch kann nichts bestätigen, was er nicht gesehen hat. Ein Werkzeug, das das
   Signal ignoriert und gleich schreibt, bricht den Vertrag aus §2.8; das fängt keine Brücke ab.

Die Gegenseite hält das Werkzeug: Es ändert nur mit `bestaetigt: true` etwas und lehnt sonst mit `ValueError` ab (das Muster
von `werkstatt.ausfuehren`):

```python
input_schema = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1, "description": "Die Notiz"},
        "bestaetigt": {"type": "boolean", "description": "Echter Lauf: vorher den Plan (`__dry_run__`) ansehen und bestätigen lassen"},
    },
    "required": ["text"],
    "additionalProperties": False,
}

def notiz_setzen(self, text, trocken=False, bestaetigt=False):
    ...                                    # Eingaben prüfen wie bisher
    if trocken:
        return build_dry_run_result(...)   # der Plan, ohne etwas zu ändern
    if not bestaetigt:
        raise ValueError("Nichts geändert: ein echter Lauf braucht bestaetigt: true — erst mit __dry_run__ den Plan ansehen und bestätigen lassen.")
    ...                                    # wirklich schreiben
```

In `call` kommt der Wert mit `args.get("bestaetigt") is True` an. Das schützt vor Versehen, es ist keine Berechtigung:
Wer Werkzeuge direkt aufrufen darf, kann `bestaetigt: true` selbst setzen; die Grenze zieht weiter §2.7. Der Gewinn: Die
Oberfläche schreibt nie „nebenbei“, und Skripte (`begleiter/`) müssen die Bestätigung ausdrücklich geben.

Stufe 3 löst die App nicht aus. Sie schreibt die Bitte ins Gespräch (`App.nachricht("Bitte … löschen")`, nur nach einem
Klick und nur, wenn `App.kann("message")`), oder ein Werkzeug des Plugins legt einen **Vorgang** an, der auf Freigabe wartet
(Status `waiting_approval`, Vorgangs-Vertrag in `KOPPLUNG-OPENCLAW.md` §4). Entscheiden tut der Mensch im Freigabeweg des
Agenten (Chat oder Vorgang), nie die Oberfläche. Die Vorlage baut Stufe 3 nicht nach, weil sie einen Vorgangs-Dienst
voraussetzt.

---

## 4. Wissen für den Agenten: Skills

Ein **Skill** ist eine Arbeitsanleitung: *wann* man welche Werkzeuge nimmt, in welcher Reihenfolge, wo die Fallen liegen.
Die Werkzeuge beschreibt der Hub; der Skill erklärt den Umgang. Der Agent findet Skills über das Hub-Plugin `skills`.

### 4.1 Aufbau

```text
fyos_plugin_wetter/skills/wetter/SKILL.md                die Anleitung
fyos_plugin_wetter/skills/wetter/references/*.md         (optional) lange Zusatzdateien, einzeln lesbar
```

```markdown
---
name: wetter
description: Laden, wenn der Besitzer nach Wetter, Regen oder Temperatur fragt. Welches Werkzeug wann, was nie getan wird.
ausloeser: Wetter, Regen, Temperatur, Vorhersage
werkstatt: []              # IDs angemeldeter Werkstatt-Skripte, die der Skill benutzt (optional)
fuer: [agent]
---

# Wetter

## Wann
…
## Ablauf
1. …
## Regeln
- …
```

- Der Kopf hat mindestens `name` und `description`. Die `description` ist der Suchtext: schreibe „Laden, wenn …“ und die
  Wörter, mit denen jemand fragt.
- Der Text ist knapp und im Imperativ: Ablauf in Schritten, Regeln, was nie geschieht. Nenne Werkzeuge mit ihrer ID.
- Schreibe keine Geheimnisse und keine echten Adressen hinein.

### 4.2 Auffindbar machen

**Skills reisen mit dem Paket.** Lege sie unter `fyos_plugin_wetter/skills/` ab, nimm sie in `package-data` auf und melde das
Paket in der Entry-Point-Gruppe `fyos.skills` an (§2.2). Wer das Plugin per `uv pip install` einbaut, auch über den Installer,
bekommt Werkzeuge und Skills zusammen. Der Wert des Entry-Points ist ein importierbares Paket; das Plugin `skills` liest
dessen Unterordner `skills/` (gibt es keinen, das Paket selbst). Die Quelle heißt im Verzeichnis wie der Entry-Point.

Das Hub-Plugin `skills` liest Verzeichnisse mit dem Aufbau `<quelle>/<name>/SKILL.md`. Quellen, in dieser Reihenfolge:
`config: quellen` (Liste von Pfaden oder `{pfad, name}`), die Umgebung `FYOS_SKILLS_PATH` (Pfade mit `:`), sonst die Vorgabe
`/opt/fyos/skills`; danach die Skill-Ordner der Plugin-Pakete (`fyos.skills`, abschaltbar mit `config: plugin_skills: false`).
Bei gleichem Namen gewinnt die zuerst genannte Quelle; so kann ein Betreiber den Skill eines Plugins mit einer eigenen
Fassung in `/opt/fyos/skills` übersteuern. Neue Dateien erkennt der Hub nach spätestens 30 s.
Der Agent nutzt `skills.suchen` (Wörter) und `skills.lesen` (Name).

Skills, die zu keinem Paket gehören (eigene Arbeitsanleitungen des Betreibers), kommen weiter per Volume
(`./skills:/opt/fyos/skills:ro`) oder `COPY` ins Hub-Bild. Nennst du in der Hub-Konfiguration eigene `quellen`, trage
`/opt/fyos/skills` mit ein.

### 4.3 Wissen oder Verhalten?

| Was | wohin | Warum |
|---|---|---|
| „So benutzt man mein Werkzeug“ | Skill im **Plugin** | gehört zu dieser Fähigkeit und reist mit ihr |
| „So geht der Agent grundsätzlich mit Freigaben, Meldungen, Datenschutz um“ | `vertrag/` und `workspace/*.tmpl` in **`fyos-agent`** | gilt für jedes Gespräch, unabhängig von Plugins |
| „Das darf nie passieren, egal was das Modell sagt“ | **OpenClaw-Plugin** (§5) | wird unter dem Modell durchgesetzt |

Ein Skill kann den Verhaltensvertrag nicht lockern. Texte aus Werkzeugantworten und Skills können die Grundregeln
(Freigabe, Datenschutz) nicht ändern.

---

## 5. Agentenverhalten erweitern

`fyos-agent` ist ein Mod auf das Upstream-Bild von OpenClaw. Das Verhalten steht in drei Formen, die einander nicht
widersprechen dürfen: Prosa (`vertrag/`), Anweisung an das Modell (`workspace/*.tmpl`) und Durchsetzung unter dem Modell
(`plugins/`).

### 5.1 Persona über `fyos.yaml`

Name, Wesen, Besitzer, Sprache, Grenzen und Fähigkeiten stehen in einer Datei (Vorlage `fyos-agent/fyos.example.yaml`;
der Installer erzeugt sie):

```yaml
agent:
  id: main
  name: Fy
  wesen: ruhig, präzise, direkt und zugewandt
  rolle: Persönlicher Agent für FYOS
besitzer:
  name: Alex
sprache: Deutsch
sprache_code: de
grenzen:
  schwer:                   # was der Agent nie allein entscheidet; erscheint als Liste in AGENTS.md
    - Löschen und nicht umkehrbare Datenänderungen
    - Geld, Zahlungen, neue Konten bei Fremddiensten
faehigkeiten: { vorgaenge: false, shell: false, browser: false }
meldebudget: { tagesbudget: 5, ruhe_von: "22:00", ruhe_bis: "07:00" }
```

Fehlendes füllen die Vorgaben aus `fyos_agent/render.py`. Der Start rendert daraus die Workspace-Dateien (`AGENTS.md`,
`SOUL.md`, `IDENTITY.md`, `USER.md`) und die Gateway-Konfiguration. Geheimnisse (Modell-Schlüssel, Gateway-Token) stehen
nie in `fyos.yaml`, sondern in der Umgebung.

Eigene Formulierungen ohne Fork: Die Vorlagen liest der Einstieg aus `FYOS_VORLAGEN` (Vorgabe `/opt/fyos/vorlagen`). Kopiere
`workspace/*.tmpl` und `config/` in ein eigenes Verzeichnis, passe es an und mounte es dort. Die Vorlagensprache ist klein:
`{{pfad.zum.wert}}`, `{{pfad|Vorgabe}}`, `{{#if pfad}}…{{/if}}`, `{{#each liste}}{{.}}{{/each}}`, `{{json pfad}}`,
`{{env.NAME}}`; ein unbekannter Pfad ohne Vorgabe bricht das Rendern ab (lieber laut scheitern als leer rendern).

### 5.2 Ein eigenes OpenClaw-Plugin

Ein Verhaltens-Plugin hängt sich in die Hooks des Gateways. Es ist nötig, wenn eine Regel **nicht** vom Modell abhängen darf.
Vorbilder in `fyos-agent/plugins/`: `fyos-meldebudget` (Tagesbudget und Ruhezeiten im Hook `message_sending`),
`fyos-prioritaet` (Zustand je Gespräch), `fyos-freigabe-chat`, `fyos-bruecke` (Hooks ohne Inhalte, Dienst mit Takt,
HTTP-Route mit Gateway-Anmeldung, die Gateway-Methoden einer festen Liste weiterreicht; `KOPPLUNG-OPENCLAW.md`).

Ein vollständiges kleines Beispiel, **`fyos-laufzaehler`**: zählt abgeschlossene Läufe je Auslöser und stellt den Stand als
Gateway-Methode bereit.

```text
plugins/fyos-laufzaehler/
├── openclaw.plugin.json      Manifest
├── package.json              Einstieg für OpenClaw
├── index.mjs                 Anmeldung
├── zaehler.mjs               die Logik (rein, ohne Gateway testbar)
└── zaehler.test.mjs          node --test
```

`openclaw.plugin.json` (die `id` ist der Ordnername und beginnt mit `fyos-`; `configSchema` listet jede Einstellung,
`additionalProperties: false` fängt Tippfehler ab):

```json
{
  "id": "fyos-laufzaehler",
  "name": "FYOS Laufzähler",
  "version": "0.1.0",
  "description": "Zählt abgeschlossene Agentenläufe je Auslöser; Stand über die Gateway-Methode fyos.laufzaehler.stand.",
  "activation": { "onStartup": true },
  "configSchema": { "type": "object", "properties": {}, "additionalProperties": false }
}
```

`package.json`:

```json
{
  "name": "@fyos/laufzaehler",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "openclaw": { "extensions": ["./index.mjs"] },
  "scripts": { "test": "node --test *.test.mjs" }
}
```

`index.mjs`:

```js
import {definePluginEntry} from 'openclaw/plugin-sdk/plugin-entry';
import {PLUGIN_ID, registerLaufzaehler} from './zaehler.mjs';

export default definePluginEntry({
  id: PLUGIN_ID,
  name: 'FYOS Laufzähler',
  description: 'Zählt abgeschlossene Agentenläufe je Auslöser und stellt den Stand als Gateway-Methode bereit.',
  register: registerLaufzaehler,
});
```

`zaehler.mjs`:

```js
export const PLUGIN_ID = 'fyos-laufzaehler';

export function erzeugeZaehler({uhr = () => Date.now()} = {}) {
  const laufend = new Map(); // runId -> {trigger, t}
  const summe = {};          // trigger -> {anzahl, ms}
  return {
    beginn(runId, trigger) {
      if (typeof runId === 'string' && runId && !laufend.has(runId)) {
        laufend.set(runId, {trigger: typeof trigger === 'string' && trigger ? trigger : 'unbekannt', t: uhr()});
      }
    },
    ende(runId) {
      const lauf = laufend.get(runId);
      if (!lauf) return;
      laufend.delete(runId);
      const s = (summe[lauf.trigger] ??= {anzahl: 0, ms: 0});
      s.anzahl += 1;
      s.ms += uhr() - lauf.t;
    },
    stand() {
      return {laufend: laufend.size, summe: structuredClone(summe)};
    },
  };
}

export function registerLaufzaehler(api, abhaengigkeiten = {}) {
  const zaehler = abhaengigkeiten.zaehler ?? erzeugeZaehler();
  api.on('before_agent_run', (_event, ctx) => { zaehler.beginn(ctx?.runId, ctx?.trigger); });
  api.on('agent_end', (event, ctx) => { zaehler.ende(ctx?.runId ?? event?.runId); });
  api.registerGatewayMethod?.('fyos.laufzaehler.stand', () => zaehler.stand(), {scope: 'operator.read'});
  api.logger?.info?.(`${PLUGIN_ID}: bereit`);
  return zaehler;
}
```

`zaehler.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import {erzeugeZaehler, registerLaufzaehler} from './zaehler.mjs';

test('zählt abgeschlossene Läufe je Auslöser und misst die Dauer', () => {
  let jetzt = 1000;
  const z = erzeugeZaehler({uhr: () => jetzt});
  z.beginn('r1', 'user');
  jetzt += 250;
  z.ende('r1');
  z.ende('r1'); // doppeltes Ende zählt nicht noch einmal
  assert.deepEqual(z.stand(), {laufend: 0, summe: {user: {anzahl: 1, ms: 250}}});
});

test('Hooks und Gateway-Methode werden angemeldet', () => {
  const hooks = {}, methoden = {};
  const api = {
    on: (name, fn) => { hooks[name] = fn; },
    registerGatewayMethod: (name, fn, opt) => { methoden[name] = {fn, opt}; },
    logger: {info() {}},
  };
  const z = registerLaufzaehler(api);
  hooks.before_agent_run({}, {runId: 'a', trigger: 'cron'});
  hooks.agent_end({runId: 'a'}, {});
  assert.equal(z.stand().summe.cron.anzahl, 1);
  assert.equal(methoden['fyos.laufzaehler.stand'].opt.scope, 'operator.read');
});
```

Merkregeln aus den vorhandenen Plugins:

- **Logik und Anmeldung trennen.** `register…(api, abhaengigkeiten)` nimmt Abhängigkeiten (Uhr, Speicher, Logger) als
  Parameter, damit die Tests ohne Gateway laufen: `node --test "plugins/**/*.test.mjs"` (die CI ruft genau das auf).
- Hooks (Auswahl, die in den Plugins vorkommen): `message_received`, `message_sending` (Rückgabe
  `{cancel: true, cancelReason: '…'}` verwirft die Sendung), `before_agent_run`, `agent_end`, `before_tool_call`,
  `after_tool_call`, `before_model_resolve`, `before_prompt_build`, `before_agent_reply`, `gateway_start`; ohne
  Einblick ins Gespräch nutzbar sind `after_tool_call`, `model_call_ended`, `session_start`, `session_end`,
  `cron_changed`, `skill_changed` und das Lebenszyklus-Abo `api.agent.events.registerAgentEventSubscription`
  (`fyos-bruecke`). Hooks, die Gesprächsinhalt sehen (`agent_end`, `llm_output`, `before_agent_run` …), brauchen
  `hooks.allowConversationAccess: true` im Eintrag.
- Fail-closed bei Regeln, die schützen: scheitert die Entscheidung, wird gesperrt, nicht durchgelassen.
- Speichere nur Zähler und Entscheidungen, **nie Inhalte** von Gesprächen. Logge keine Modelltexte und keine Werkzeugparameter.
- Konfiguration liest das Plugin aus `api.pluginConfig`; sie kommt aus `plugins.entries."<id>".config` der gerenderten
  Gateway-Konfiguration.

**Einbau in `fyos-agent`.** Drei Stellen, dann ist das Plugin im Bild:

1. Den Ordner nach `fyos-agent/plugins/fyos-laufzaehler/` legen. Das Dockerfile kopiert `plugins/` nach `/opt/fyos/` und
   verlinkt jedem Ordner `fyos-*` das SDK; `*.test.mjs` werden aus dem Bild gelöscht.
2. In `fyos_agent/render.py` die Kennung zu `PLUGIN_IDS` ergänzen (daraus entstehen die Ladepfade
   `/opt/fyos/<id>`; das Gateway startet nicht, wenn ein Pfad fehlt). Der Test `test_plugins_stimmen_mit_den_ordnern_ueberein`
   verlangt, dass Ordner, `PLUGIN_IDS` und `id` im Manifest übereinstimmen.
3. In `config/openclaw.json5.tmpl` einen Eintrag unter `plugins.entries` anlegen:

   ```json5
   "fyos-laufzaehler": {
     enabled: true,
     hooks: { allowConversationAccess: false, allowPromptInjection: false },
     config: {},
   },
   ```

   Die beiden `hooks`-Schalter geben dem Plugin Einblick in Gesprächsinhalt beziehungsweise das Recht, den Prompt zu ändern.
   Lass beide aus, wenn das Plugin sie nicht braucht; `allowPromptInjection: true` hat im Bestand nur der Tempo-Router.
   Soll das Plugin aus `fyos.yaml` einstellbar sein, ergänze einen Abschnitt in `VORGABEN` (`render.py`) und im Beispiel
   `fyos.example.yaml` und verweise im Template mit `{{json abschnitt.feld}}` darauf; der Test verlangt, dass das Beispiel
   nichts enthält, was die Vorgaben nicht kennen.

Danach: `python3 -m pytest tests -q`, `node --test "plugins/**/*.test.mjs"`, `python3 tools/sauber.py .` und das Bild bauen
(`docker build -f openclaw/Dockerfile -t fyos-agent .`). Diesen Ablauf haben wir mit dem Beispiel oben durchgespielt:
Tests und Sauberkeit bleiben grün.

#### Ohne Fork: Zusatz-Plugins

Gehört das Plugin nicht in `fyos-agent` selbst, lege es in den Zusatzordner `/opt/fyos-extra` (anderer Ort:
`FYOS_AGENT_PLUGINS`). Jeder Unterordner mit `openclaw.plugin.json` wird beim Start geladen, ohne Eintrag in
`PLUGIN_IDS` und ohne eigene Vorlage:

```dockerfile
# abgeleitetes Agent-Bild
FROM registry.example.com/fyos/fyos-agent/openclaw:main
COPY --chown=node:node fyos-laufzaehler/ /opt/fyos-extra/fyos-laufzaehler/
```

Im Compose-Betrieb genügt ein Volume (`./agent-plugins:/opt/fyos-extra`), in Kubernetes ein ConfigMap- oder
PVC-Mount. Der Einstieg legt dem Ordner `node_modules/openclaw` → `/app` an (das SDK); ist der Ordner schreibgeschützt,
lege den Verweis vorher selbst an und lies die Warnung im Log.

Ein Zusatz-Plugin ist **an**, aber **ohne Rechte**: kein Einblick ins Gespräch, kein Eingriff in den Prompt. Rechte und
Einstellungen gibt der Betreiber in `fyos.yaml`:

```yaml
zusatz_plugins:
  fyos-laufzaehler:
    aktiv: true
    rechte: { gespraech: true, prompt: false }   # → hooks.allowConversationAccess / allowPromptInjection
    config: { grenze: 3 }                         # → plugins.entries.<id>.config
```

Das Rendern scheitert laut, wenn die `id` im Manifest fehlt, ungültig ist oder es sie schon gibt (eingebaut oder doppelt).
Eine Einstellung für ein Plugin, das nicht im Ordner liegt, ergibt nur eine Warnung. Den Weg prüfen die Tests
`test_zusatz_plugins_*` in `fyos-agent/tests/test_render.py`.

---

## 6. Shell erweitern

Die Shell (`web/`, Astro und SolidJS) enthält keine eigenen Inhalte. Hub-Apps erscheinen von selbst (§3); für alles andere
gibt es `registriereFlaechen` und die Laufzeit-Konfiguration.

### 6.1 `registriereFlaechen`

`web/src/lib/os/register.ts` ist die eine Schnittstelle, über die Plugins Flächen, Symbole, Gruppen und Vorlagen in die
Shell bringen. Jede Datei `web/src/plugins/*.ts` (außer `index.ts`) wird beim Laden der Shell ausgeführt:

```ts
// web/src/plugins/wetter.ts
import { registriereFlaechen } from '~/lib/os/register';

registriereFlaechen({
  flaechen: [
    // eine Seite desselben Ursprungs, läuft in einem Fenster
    { id: 'seite:radar', titel: 'Regenradar', gruppe: 'Wissen', art: 'seite', kuerzel: 'Ra', pfad: '/radar/' },
    // ein fremder Dienst, öffnet in einem neuen Tab
    { id: 'extern:amt', titel: 'Wetteramt', gruppe: 'Extern', art: 'seite', kuerzel: 'Wa', extern: 'https://wetter.example.org/' },
  ],
  symbole: { 'seite:radar': ['cloud', 210] },                         // Lucide-Name aus lib/os/symbole-daten.ts, Farbton
  gruppen: { reihenfolge: ['Wissen'], plugin: { wetter: 'Wissen' }, app: {} },   // Hub-App wetter__* in die Gruppe „Wissen“
  standardPlaetze: [{ name: 'Morgen', ids: ['seite:radar', 'app:wetter__vorhersage'] }],
  alias: { 'seite:regen': 'seite:radar' },                            // alte Kennungen führen auf die heutige Fläche
  quelle: 'wetter',                                                   // eine neue Registrierung derselben Quelle ersetzt die alte
});
```

| Feld | Bedeutung |
|---|---|
| `flaechen` | `art: 'seite'` mit `pfad` (Fenster, gleicher Ursprung) oder mit `extern` (neuer Tab); `art: 'nativ'` mit `laden` (Solid-Komponente im Fenster, `NativProps`: `oeffne`, `schmal`) |
| `symbole` | Glyphe und Farbton je Fläche; Hub-Apps bringen ihr Gesicht selbst mit |
| `gruppen` | Reihenfolge der Gruppen und Zuordnung von Hub-Apps: erst ganzer Werkzeugname (`app`), dann Plugin-Präfix vor `__` (`plugin`), sonst „Apps“ |
| `standardPlaetze` | Vorlagen für Arbeitsbildschirme, die der Start anbietet; fehlende Flächen werden übergangen |
| `alias` | alte Kennungen → heutige Fläche (Lesezeichen, gespeicherte Anordnungen, `?offen=`) |
| `dinge` | ziehbare Dinge (`fyos://<typ>/<id>`) und die Seite, auf der sie leben |

Flächen-Kennungen: `seite:<name>`, `app:<plugin>__<werkzeug>`, `nativ:<name>`, `extern:<slug>`, `agent`.

**Wie kommt die Datei in die Shell?** Die Dateien aus `web/src/plugins/` werden beim **Bauen** eingelesen
(`import.meta.glob`). Ein eigenes Plugin-Repo legt darum eine Datei `shell/wetter.ts` ab und baut ein eigenes Web-Bild, das sie
vor dem Bau nach `src/plugins/` kopiert. Rezept mit BuildKit-Kontexten (Kontext `web` = der Ordner `fyos-os/web`):

```dockerfile
# Dockerfile.web, Aufruf:  docker build --build-context web=../fyos-os/web -f Dockerfile.web -t mein-web:main .
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=web package.json package-lock.json ./
RUN npm ci
COPY --from=web . .
COPY shell/ src/plugins/
ARG PUBLIC_FYOS_NAME=FYOS
ENV PUBLIC_FYOS_NAME=$PUBLIC_FYOS_NAME
RUN npm run build

FROM nginx:1.27-alpine
ENV NGINX_ENVSUBST_FILTER=FYOS_
ENV FYOS_HUB_UPSTREAM=http://hub:8080
ENV FYOS_AGENT_UPSTREAM=http://agent:18789
COPY --from=web nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=web nginx/fyos.config.default.json /etc/fyos/fyos.config.json
EXPOSE 8080
```

(Das Rezept folgt `web/Dockerfile`; halte es synchron, wenn sich jenes ändert. Es wird in der Distribution nicht
automatisch geprüft.) Danach das Bild in der Compose-Datei als `FYOS_BILD_WEB` oder im Kustomize-Overlay eintragen
(`images`, `name: registry.example.com/fyos/fyos-os/web`; warum der volle Name, steht in `deploy/k8s/base/kustomization.yaml`).
Prüfe vorher mit `npx tsc --noEmit -p .` und `npx vitest run` im Ordner `web/`.

> **(im Aufbau)** Eine Auslieferung von Shell-Dateien *ohne* eigenes Web-Bild (etwa ein gemounteter Ordner, den die Shell
> zur Laufzeit lädt) gibt es noch nicht. Für Hub-Apps ist sie nicht nötig; nur Seiten, externe Flächen und native Flächen
> aus Plugins brauchen den Bau.

### 6.2 Laufzeit-Konfiguration `fyos.config.json`

Die Shell lädt beim Start `/fyos.config.json` (nginx liefert die Datei aus `/etc/fyos/fyos.config.json`). Fehlt sie, gelten
die Vorgaben. Hier gehören Dinge hin, die zu einer Installation gehören und kein Code sind:

```json
{
  "name": "FYOS",
  "oeffentlicheUrl": "https://os.example.org",
  "agent": { "name": "Fy", "pfad": "/agent/" },
  "extern": [
    { "slug": "git", "titel": "Git", "url": "https://git.example.org/" },
    { "slug": "grafana", "titel": "Grafana", "url": "https://grafana.example.org/" }
  ]
}
```

- `name`: Name im Menü und Seitentitel (überschreibt `PUBLIC_FYOS_NAME`).
- `oeffentlicheUrl`: zusätzlicher Ursprung, dessen Links im OS öffnen (hinter einem Proxy).
- `agent.name` und `agent.pfad` (beginnt mit `/`).
- `extern`: Dienste mit eigener Oberfläche, öffnen in einem neuen Tab. `slug` (Buchstaben, Ziffern, `_`, `-`), `titel`,
  `url` (nur `http` und `https`). Sie erscheinen als Flächen `extern:<slug>` in der Gruppe „Extern“. Das ist der Weg für
  „ich will mein Git im Dock“ ohne Code.

Einbinden: in Compose `volumes: ["./fyos.config.json:/etc/fyos/fyos.config.json:ro"]` am Dienst `web`, in Kubernetes eine
ConfigMap an derselben Stelle. Das Image bringt eine leere Standarddatei `{}` mit.

---

## 7. Installer-Katalog

Der Installer (`fyos-install`) zeigt Bausteine mit Bild und einer Erklärung „Was daraus wird“ und erzeugt daraus Compose-
oder Kubernetes-Dateien. Dein Plugin wird ein Baustein, indem es einen Katalogeintrag mitbringt.

> **Stand:** Der Installer ist in dieser Version noch im Bau (Web-Assistent, Textoberfläche, Zielarten). Das Katalogformat
> unten ist das aus `installer/fyos_installer/katalog.py` und durch Tests abgesichert; Einzelheiten der Oberflächen können
> sich noch ändern.

### 7.1 Die Datei `fyos-katalog.yaml`

Sie liegt **im Python-Paket** (`fyos_plugin_wetter/fyos-katalog.yaml`), Bilder daneben im Ordner `bilder/`:

```yaml
version: 1
bausteine:
  - id: wetter                      # a-z, 0-9, _ ; beginnt mit einem Buchstaben; eindeutig
    titel: Wetter
    kurz: Vorhersage für heute als App; der Agent kennt das Wetter.      # genau eine Zeile
    was_daraus_wird: |
      Im Desktop erscheint ein Fenster mit der Vorhersage für deinen Ort.
      Der Agent beantwortet Fragen wie »Brauche ich heute einen Schirm?«.
      Die Daten kommen von einem Wetterdienst deiner Wahl; es wird nur gelesen.
    bilder: [wetter-1.svg]          # Dateien in bilder/ neben dieser Datei (png, jpg, webp oder svg)
    art: plugin                     # kern | agent | plugin
    pflicht: false
    abhaengig_von: [kern, agent]    # ids aus diesem oder dem Installer-Katalog
    voraussetzungen:                # erscheinen als Hinweise
      - Ein Konto beim Wetterdienst
    quelle: { paket: fyos-plugin-wetter, repo: fyos-plugin-wetter }
    hub_plugins:                    # Einträge für die Hub-Konfiguration (name, optional config, secrets, enabled)
      - { name: wetter }
    reife:                          # optional: Stufe (1 bis 3), auf die der Baustein eine Schicht hebt
      oberflaeche: 2                # gedaechtnis | agent | takte | oberflaeche
      agent: 2
    konfiguration:                  # Felder, die der Installer abfragt
      - name: ort
        titel: Ort                  # Beschriftung des Feldes (Pflicht)
        typ: text                   # text | geheim | url | zahl | wahl
        beschreibung: Ort der Vorhersage
        standard: ""
        pflicht: false
        umgebung: FYOS_WETTER_ORT   # Name der Umgebungsvariable im Hub; ohne Angabe FYOS_<ID>_<NAME>
      - name: token
        titel: Zugriffsschlüssel
        typ: geheim
        beschreibung: Zugriffsschlüssel des Wetterdienstes
        umgebung: FYOS_WETTER_TOKEN
```

Was daraus wird:

- **`quelle`** sagt, woher das Paket kommt: `paket` ist der Name im Paketindex, `repo` der Name des Git-Repos. Der Installer
  macht daraus die Zeile im erzeugten `hub/Dockerfile`, je nach Bezug: aus einem Paketindex (`FYOS_PAKETINDEX`, beim Bauen als
  `FYOS_INDEX_URL`; der Index steht vor PyPI, §10.3) `uv pip install fyos-plugin-wetter`, per Git (`FYOS_PLUGIN_QUELLE`)
  `uv pip install "fyos-plugin-wetter @ git+<plugin_quelle>/fyos-plugin-wetter.git"`. Ohne `quelle` ist nichts zu installieren
  (so die Bausteine des Kerns).
- **`konfiguration`**: jedes Feld wird eine Umgebungsvariable. Im Compose-Ziel stehen Werte in der `.env` (Geheimnisse
  nur dort, Rechte 600) und werden an den Hub durchgereicht; im Kubernetes-Ziel landen offene Werte in einer ConfigMap und
  `geheim` in einem Secret. **Dein Plugin liest darum dieselben Variablen** (§2.9). `FYOS_PORT` und `FYOS_OEFFENTLICH_URL` sind
  reserviert.
- **`hub_plugins`** erscheinen in der erzeugten `hub-config.yaml`. Wählt jemand den Baustein *nicht* ab, bleibt das Plugin
  ohnehin aus; Bausteine des Installers selbst schaltet er ausdrücklich ab.
- **`reife`** (optional) sagt dem Installer, auf welche Stufe dein Baustein welche der vier Schichten hebt. Der Installer
  zeigt vor dem Schreiben den **Reifegrad** der Auswahl: je Schicht die Stufe, einen Satz, woran man sie im laufenden
  System erkennt, und die nächste Stufe (Leiter und Herleitung: `installer/README.md`, Abschnitt Reifegrad). Es zählt die
  höchste Stufe unter den gewählten Bausteinen; was du nicht nennst, bleibt auf 1 (Kern und Agent sind Stufe 1).
  Faustregel: Dein Plugin bringt eine App → `oberflaeche: 2`. Der Agent ruft seine Werkzeuge → `agent: 2`. Es liefert Wissen
  über die Umgebung → `gedaechtnis: 2`. Es richtet Routinen ein → `takte: 2`. Die Stufe 3 der Takte setzt der Installer
  selbst, sobald ein gewähltes Hub-Plugin in seiner `config` `takt_grenzen` trägt (§2.12). Die Stufen 3 der übrigen
  Schichten (Verlauf und Vorgänge, Vorgänge, Zentrale) gehören dem Leitstand. Ersetzt dein Katalog einen Eintrag des
  Installers (gleiche `id`) und nennt kein `reife`, behält er das des ersetzten Eintrags.
- **`bilder`**: Dateinamen, Schema `<id>-<n>.svg`. Gibt es zum Namen ein `.png`, nimmt der Installer das (Screenshot vor Skizze).
  Eine SVG-Skizze mit `<title>` und `<desc>` dient zugleich als Textvorschau; schreibe beides, und beschreibe in `<desc>`, was man
  sieht. Muster: `fyos-plugin-vorlage/fyos_plugin_vorlage/bilder/vorlage-1.svg`.
- Texte zum **Erklären** an Menschen, nicht an Techniker: was erscheint, was kann der Agent, was passiert mit Daten, was
  wird nie getan. Schreibe 4 bis 6 kurze Sätze.

### 7.2 Wie der Installer die Datei findet

1. Über den **Entry-Point `fyos.katalog`**: Das Muster macht das so und ist damit auch bei `uv pip install -e` auffindbar.

   ```toml
   [project.entry-points."fyos.katalog"]
   wetter = "fyos_plugin_wetter:katalog_pfad"       # ruft die Funktion; sie liefert den Pfad der Datei
   ```

   ```python
   # fyos_plugin_wetter/__init__.py
   from pathlib import Path
   def katalog_pfad() -> Path:
       return Path(__file__).resolve().parent / "fyos-katalog.yaml"
   ```

   (Der Entry-Point darf auch den Pfad selbst oder das geladene Katalog-Objekt liefern.)
2. Ohne Entry-Point: eine Datei namens `fyos-katalog.yaml` im installierten Paket einer Distribution, deren Name mit
   `fyos-plugin-` beginnt. Dafür muss sie über `package-data` ins Paket (siehe §2.2).
3. Von Hand: `fyos-install --katalog pfad/oder/url.yaml` (mehrfach möglich). Aus einer URL kommen keine Bilder mit.
   `--ohne-plugin-kataloge` ignoriert die Kataloge installierter Pakete.

Prüfen: `fyos-install --liste` zeigt alle Bausteine samt deinem. Eine fehlerhafte Datei meldet das Schema-Prüfen mit jedem
Befund (Katalog darf höchstens 1 MB haben). Eine gleiche `id` in einem späteren Katalog ersetzt die frühere (mit Hinweis);
innerhalb eines Katalogs ist sie ein Fehler. Mit `fyos-install --auswahl wetter --ziel dateien --verzeichnis /tmp/probe`
siehst du die erzeugten Dateien, ohne etwas zu starten (`--trocken` schreibt nichts), dazu den Reifegrad der Auswahl.

Nach dem Start eines Compose-Ziels nimmt der Installer das System ab: Er stellt drei verbotene Anfragen an die Shell, die
FYOS ablehnen muss (den vollen Aufruf-Endpunkt, einen Aufruf mit fremder Herkunft, ein Werkzeug ohne Oberfläche über den
Browser-Weg), und eine erlaubte als Gegenprobe. Für dein Plugin heißt das nur: Ein Werkzeug ohne Oberfläche (ohne `ui` in
`meta`, ohne Tag `flaeche`) ist über den Browser nicht erreichbar, und das soll so bleiben (§3.2). Wiederholen:
`fyos-install --abnahme http://localhost:8080` (Einzelheiten: `installer/README.md`, Abschnitt Abnahme).

---

## 8. Begleitdienste und Begleitskripte

Nicht alles läuft im Hub. Zwei Arten von Begleitern:

### 8.1 Begleitskripte auf anderen Geräten

Manche Daten gibt es nur auf einem bestimmten Gerät (ein Programm auf dem Mac, ein Sensor, ein NAS). Das Muster steht im
Finanz-Plugin (`fyos-plugin-finanzen/mac/`): Ein Skript läuft dort zeitgesteuert, liest lokal und **schiebt** die Daten
an einen Webhook; das Hub-Plugin liest sie später von dort. So braucht das Gerät keinen offenen Port.

Regeln:

- **Schieben statt Öffnen.** Das Gerät ruft den Dienst an, nicht umgekehrt.
- **Adresse und Token stehen nicht im Skript.** Lies sie aus einer Datei außerhalb des Repos (`~/.config/fyos/…`, Rechte
  600) oder der Umgebung, so wie `mac/moneymoney_konten.py` es mit `finance_base_url` und `finance_token` tut.
- **Nur Nötiges senden** (von einer IBAN die letzten vier Stellen, keine Inhaber). Das Skript entscheidet, was das Gerät
  verlässt.
- **Nur lesen**, wo es genügt (kein Auslösen von Überweisungen, keine Schreibzugriffe).
- **Zeitplan als Teil des Repos:** unter macOS ein LaunchAgent (`*.plist`) mit dem Platzhalter `__MAC_DIR__` und ein
  `install.sh`, der ihn durch den Ordner ersetzt und nach `~/Library/LaunchAgents` legt; unter Linux ein systemd-Timer oder Cron.
- Ein Skript, das der **Agent** starten soll, gehört in die Werkstatt (Hub-Plugin `werkstatt`: angemeldete Skripte mit
  Kopfblock `WERKSTATT`, Trockenlauf und Protokoll), nicht in ein eigenes Werkzeug mit Shell-Zugriff.

Das Muster-Repo enthält `begleiter/hallo_per_rest.py`: ein Skript, das ein Hub-Werkzeug über `/hub/call` ruft (nur im
eigenen Netz; `/hub/call` gehört nie ins Internet).

Ausliefern: Begleiter liegen im Plugin-Repo (`mac/`, `begleiter/`), nicht im Python-Paket; sie werden dort installiert, wo das
Gerät steht (`git clone`, `mac/install.sh`). Beschreibe die Einrichtung im README des Plugins als nummerierte Schritte mit
einem Testbefehl am Ende.

### 8.2 Ein eigener Dienst als Container

Braucht dein Plugin eine Datenbank, schwere Rechnung oder eine eigene API, lagere sie in einen kleinen Dienst aus. Das Plugin
bleibt dünn und spricht ihn über HTTP an:

```yaml
# docker-compose.override.yml neben der Compose-Datei von FYOS
services:
  wetterdienst:
    image: registry.example.com/fyos/wetterdienst:main
    restart: unless-stopped
    environment:
      WETTER_TOKEN: ${FYOS_WETTER_TOKEN}
```

```yaml
# hub-config.yaml
plugins:
  - name: wetter
    config:
      dienst_url: http://wetterdienst:8000
```

```python
# im Plugin: Adresse aus config, Timeout immer setzen, Fehler als Ausfall melden
def _holen(self, pfad: str) -> dict:
    req = urllib.request.Request(f"{self.dienst_url}{pfad}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode() or "{}")
```

- Der Dienst ist **innen**: kein Port nach außen, keine Anmeldung nötig, solange nur der Hub ihn erreicht. Soll er
  von außen erreichbar sein, gehört er hinter dieselbe Anmeldung wie die Shell.
- Die Standardwerte der Adressen im Plugin sind neutral; die echte Adresse steht in `config:`.
- Das Plugin bleibt der einzige Ort mit Werkzeugnamen und Scopes; der Dienst weiß nichts von MCP.
- Der Dienst bekommt ein eigenes Repo (`fyos-dienst-<name>`) oder einen Ordner `dienst/` im Plugin-Repo mit Dockerfile und README;
  der Katalogeintrag (§7) nennt ihn unter `voraussetzungen`. (Das Finanz-Plugin legt den Datendienst vorerst noch in `dienst/README.md`
  beschrieben ab; der Dienst selbst zieht später in ein eigenes Repo.)

---

## 9. Testen

### 9.1 Lokal: Hub mit dem eigenen Plugin

```sh
uv venv && . .venv/bin/activate
uv pip install -e /pfad/zu/fyos-os/hub        # Paket fyos-hub (oder aus dem Paketindex, siehe unten)
uv pip install -e ".[test]"                   # dein Plugin; der Entry-Point wird sofort sichtbar

MCP_HUB_PORT=8080 python3 -m mcp_hub.server   # ohne config.yaml laden nur Entry-Point-Plugins
```

Installiert wird mit [uv](https://docs.astral.sh/uv/) statt mit pip; der Grund steht in §10.3. Liegt `fyos-hub` in einem
Paketindex (Entwicklungsstände tragen die Endung `.devN`), kommt dessen Adresse mit `--index` und steht damit vor PyPI:
`uv pip install --prerelease allow --index-strategy first-index --index <Index-Adresse> fyos-hub`.

```sh
curl -s localhost:8080/health
curl -s "localhost:8080/hub/search?query=wetter"
curl -s localhost:8080/hub/call -H 'Content-Type: application/json' \
  -d '{"tool":"vorlage.hallo","arguments":{"name":"Alex"}}'
curl -s localhost:8080/hub/call -H 'Content-Type: application/json' \
  -d '{"tool":"vorlage.notiz_setzen","arguments":{"text":"Milch","__dry_run__":true}}'
curl -s localhost:8080/hub/health             # Zustand je Plugin; ein nicht geladenes steht mit Grund da
```

- Ein MCP-Client deiner Wahl erreicht dasselbe unter `http://localhost:8080/mcp` (Werkzeuge `hub__search_tools`,
  `hub__schema`, `hub__call_tool`; App-Werkzeuge zusätzlich als `<plugin>__<werkzeug>`).
- Mit Eintrag: `MCP_HUB_CONFIG_PATH=./config.yaml` (siehe `hub/config.example.yaml`).
- Die Oberfläche siehst du in der Shell: `web/` mit `FYOS_DEV_HUB=http://localhost:8080 npm run dev`, dann
  `http://localhost:4321/os/?offen=app:vorlage__hallo`. Ohne Shell zeigt `curl "localhost:8080/hub/resource?uri=ui://vorlage/vorlage.html"`
  das fertig eingesetzte HTML.
- Läuft das Plugin ohne Installation (Entwicklung), trägt `module:` den Modulpfad statt des Entry-Points:
  `- name: wetter, module: fyos_plugin_wetter.plugin` mit `PYTHONPATH` auf das Repo.

### 9.2 Unit-Tests

pytest gegen den **echten Hub-Kern** (der Hub ist ein Python-Paket, kein Dienst). Drei Schichten, alle im Muster
(`tests/test_plugin.py`):

```python
from mcp_hub import registry as hub_registry
from mcp_hub.kv import SpeicherKv
from fyos_plugin_vorlage.plugin import VorlagePlugin

def test_trockenlauf_aendert_nichts():
    p = VorlagePlugin(); p._r = SpeicherKv()                      # eigener Speicher je Test
    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "vorlage", p)                 # genau wie der Hub beim Laden
    r = hub_registry.dispatch(reg, "vorlage.notiz_setzen", {"text": "Plan", "__dry_run__": True})
    assert r["ok"] is True and r["result"]["dry_run"] is True
    assert p._r.get("fyos:vorlage:notiz") is None
```

1. **Werkzeuge** über `hub_registry.dispatch(reg, "<plugin>.<werkzeug>", args)`: Ergebnis, Trockenlauf, Fehlerarten
   (`kind: bad_arguments` bei falschen Eingaben, Eingabefehler sperren nicht).
2. **Laden:** `build_registry(HubConfig(plugins=[PluginConfig(name=…, module=…)]))` und, wenn installiert, der Entry-Point.
   Dazu ein Test, der `pyproject.toml` liest und prüft, dass der Entry-Point auf eine `HubPlugin`-Klasse zeigt.
3. **REST-Wege:** ein kleines Starlette-App mit `hub_server.rest_call`, `rest_app_call`, `rest_apps`, `rest_resource` und dem
   `TestClient`; so prüfst du, was die Shell erlebt (`/hub/app-call` mit `vorlage__notiz_setzen`, die Oberfläche unter
   `/hub/resource`, 400 bei falschen Eingaben).

Dazu: die Oberfläche ist vollständig eingesetzt (keine Markierung `/*STIL*/`, `/*BRUECKE*/`, `<!--KOPF-->` übrig),
der Katalogeintrag ist gültig (`fyos_installer.katalog.lade_datei`, wenn der Installer installiert ist), der Skill ist über das
Plugin `skills` auffindbar. Tests brauchen weder Redis noch Netz; Fremddienste ersetzt du durch Attrappen (wie das Finanz-Plugin
mit `p._holen = …`).

Für Oberflächen gibt es keinen Browsertest im Muster. Prüfe sie einmal von Hand in der Shell in allen vier Größen (Fenster
verkleinern) und in Hell und Dunkel.

### 9.3 Sauberkeits-Prüfung

```sh
python3 tools/sauber.py .
```

`tools/sauber.py` und `.sauber/verboten.sha256` stammen aus `fyos-os` (Kopie). Das Werkzeug prüft jede versionierte Textdatei
und ihren Pfad auf private Netze (RFC 1918, CGNAT), echte E-Mail-Adressen, Geheimnis-Muster (private Schlüssel, bekannte
Token-Präfixe) und verbotene Wörter (nur als Hash gespeichert). Ausnahmen: `.sauber/erlaubt.txt` (Pfad-Präfixe) und der Kommentar
`sauber: ok` in einer Zeile. Neutrale Beispiele nutzen: Besitzer „Alex“, Agent „Fy“, Domains `example.com`/`example.org`,
Adressen aus den Dokumentationsnetzen (RFC 5737). Die Prüfung muss still sein, bevor du committest.

### 9.4 CI

Vorlage `.gitea/workflows/ci.yml` im Muster:

```yaml
name: ci
on: { push: , pull_request: }
jobs:
  pruefen:
    runs-on: ${{ vars.FYOS_RUNNER }}
    steps:
      - uses: actions/checkout@v4
      - name: Sauberkeit
        run: python3 tools/sauber.py .
      - name: Tests
        env:
          FYOS_HUB_QUELLE: ${{ vars.FYOS_HUB_QUELLE }}
          FYOS_PIP_INDEX: ${{ vars.FYOS_PIP_INDEX }}
        run: |
          python3 -m venv /tmp/venv
          /tmp/venv/bin/pip install -q uv==0.12.8
          if [ -n "$FYOS_HUB_QUELLE" ]; then
            /tmp/venv/bin/uv pip install -q --python /tmp/venv/bin/python "$FYOS_HUB_QUELLE"
          else
            /tmp/venv/bin/uv pip install -q --python /tmp/venv/bin/python --prerelease allow \
              --index-strategy first-index --index "$FYOS_PIP_INDEX" fyos-hub
          fi
          /tmp/venv/bin/uv pip install -q --python /tmp/venv/bin/python -e ".[test]"
          /tmp/venv/bin/python -m pytest -q
```

Repo-Variablen: `FYOS_RUNNER` (Etikett des Runners), und `FYOS_HUB_QUELLE` (zum Beispiel
`git+https://git.example.com/fyos/fyos-os.git#subdirectory=hub`) oder `FYOS_PIP_INDEX` (Paketindex mit `fyos-hub`).
Hat dein Plugin OpenClaw-Anteile (§5), kommt `node --test "plugins/**/*.test.mjs"` dazu.

Auch hier installiert uv: Der Paketindex steht per `--index` vor PyPI, und `--index-strategy first-index` nimmt ein Paket nur
aus dem ersten Index, der es kennt (§10.3). Das Beispiel holt uv in fester Version in die Umgebung; wer uv schon auf dem
Runner hat, lässt die Zeile weg.

Soll die CI dein Paket in den Paketindex des Git-Servers hochladen (Job `paket` wie in `fyos-os`), braucht dieser Job ein
Token mit dem Recht `write:package`, hinterlegt als Secrets `REGISTRY_USER` und `REGISTRY_TOKEN`. Gitea gibt dem Laufzeit-Token
eines Laufs (`GITEA_TOKEN`) keine Paketrechte (Stand 1.27); auf Plattformen, deren Laufzeit-Token Pakete schreiben darf, reicht
`permissions: { packages: write }` am Job, die Workflows von `fyos-os` fallen dann von selbst darauf zurück.

---

## 10. Ausliefern

### 10.1 Ins Hub-Bild: `FROM fyos-os/hub` + `uv pip install`

Der Hub ist ein Bild. Dein Plugin kommt hinein, indem du ein abgeleitetes Bild baust. Das Dockerfile des Musters:

```dockerfile
ARG HUB_BILD=registry.example.com/fyos/fyos-os/hub:main
FROM ${HUB_BILD}

ARG FYOS_INDEX_URL=""

USER root
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/
COPY . /tmp/plugin
# Werkzeuge, App, Katalog und Skills reisen im Paket; ein eigener Paketindex (falls gesetzt) steht vor PyPI
RUN uv pip install --system --no-cache --index-strategy first-index \
      ${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} /tmp/plugin && rm -rf /tmp/plugin

USER fyos
```

```sh
docker build --build-arg HUB_BILD=registry.example.com/mein/fyos-os/hub:main -t registry.example.com/mein/hub:main .
```

Die Vorgabe von `HUB_BILD` zeigt auf eine Beispieladresse, die sich nie auflösen lässt; ohne `--build-arg` bricht der Bau
deshalb sichtbar ab, statt ein fremdes Bild gleichen Namens zu ziehen.

Braucht dein Paket weitere Pakete aus einem eigenen Paketindex (zum Beispiel der PyPI-Registry deines Git-Servers), übergib
dessen Adresse als `--build-arg FYOS_INDEX_URL=https://registry.example.com/api/packages/org/pypi/simple`. Sie steht dann vor
PyPI (§10.3). uv kommt aus dem offiziellen Bild in fester Version; dieselbe Version steht im Dockerfile des Hubs.

Dann das Bild eintragen: in Compose `FYOS_BILD_HUB=registry.example.com/mein/hub:main` (`.env`), in Kubernetes im
Kustomize-Overlay unter `images` mit `name: registry.example.com/fyos/fyos-os/hub` (so gibt die Basis das Bild aus; ein
kurzer Name wie `fyos-os/hub` greift im Overlay nicht mehr). Eine Konfiguration (`config:`, `secrets:`) ändert sich ohne neues Bild: sie liegt in `hub-config.yaml`.
Der Hub lädt installierte Plugins auch ohne Eintrag; ein Eintrag ist nur für Konfiguration nötig.

Der Hub baut sein Bild auch mit `--build-arg EXTRA_PIP="fyos-plugin-wetter"` (und `FYOS_INDEX_URL` für einen privaten
Paketindex, der vor PyPI steht) selbst; Skills kommen dabei mit (§4.2).

### 10.2 Über den Installer

Mit dem Katalogeintrag (§7) erscheint das Plugin im Installer. Der erzeugte Ordner enthält ein `hub/Dockerfile` mit
`RUN uv pip install …` (aus dem Paketindex oder per Git, §7.1) und die Umgebungswerte. Mit dem Paket kommen Werkzeuge, App,
Katalogeintrag und Skills.

Grenzen: Der Installer liefert nicht deine Begleitskripte (§8.1) und kennt keine Zugangsdaten für private Quellen. Liegt dein Plugin in einem privaten Repo, baue das Hub-Bild selbst
(10.1) oder veröffentliche das Paket in einen Index, den das Bild erreicht.

### 10.3 Paket und Versionen

- **SemVer.** `version` in `pyproject.toml` und im Klassenattribut `version` gleichhalten (der Hub zeigt sie in der
  Werkzeugkarte). Kleine, kompatible Änderungen erhöhen die dritte Zahl, neue Werkzeuge die zweite, entfernte oder umbenannte
  Werkzeuge und geänderte Pflichtfelder die erste.
- **Die Werkzeug-IDs und ihre Eingaben sind die Schnittstelle.** Neue Felder sind optional; bestehende bleiben bedeutungsgleich.
- **Entwicklungsstände** gehen mit `X.Y.Z.devN` in einen Paketindex (so macht es die CI von `fyos-os` für `fyos-hub` über die
  PyPI-Schnittstelle der Paket-Registry des Git-Servers), Veröffentlichungen mit Tag und Release.
- Das Bild bekommt zwei Tags: `main` (läuft jetzt) und den Commit (zurückrollbar).
- **Paketnamen sind ein Angriffsweg (Dependency Confusion).** Mit `--extra-index-url` nimmt pip die höchste Version aus
  *allen* Indizes. Lädt jemand ein Paket mit deinem Namen und höherer Version auf PyPI, installiert pip im Zweifel dieses
  fremde Paket. Deshalb installiert FYOS mit [uv](https://docs.astral.sh/uv/) statt mit pip: Der eigene Index steht per
  `--index` vor PyPI, und `--index-strategy first-index` (in uv die Vorgabe, in unseren Befehlen ausdrücklich gesetzt) nimmt
  ein Paket nur aus dem ersten Index, der den Namen kennt. Ein gleichnamiges Paket auf PyPI verdrängt das eigene so nicht.
  `--index-strategy unsafe-best-match` (die höchste Version über alle Indizes, also das Verhalten von pip) gehört nirgends hin.
  Ist der eigene Index nicht erreichbar, bricht uv ab, statt auf PyPI auszuweichen. Dazu bleibt: eindeutige Namen
  (`fyos-plugin-…`) und den Namen vor einer Veröffentlichung auf PyPI selbst belegen; das schützt auch alle, die dein Paket ohne
  den eigenen Index installieren.

### 10.4 Privat oder öffentlich

Ein Plugin-Repo darf **persönliche Konfiguration** enthalten (Beispiele mit deinen Geräten, Texte für dein Zuhause). Dann
bleibt es privat. Willst du es öffentlich machen, räume vorher auf; das ist auch der Grund, warum die Distribution selbst nur
Allgemeines enthält.

**Nie ins Repo** (weder privat noch öffentlich):

- Tokens, Passwörter, Schlüssel, Zertifikate, `.env`- und `secrets.yaml`-Dateien; ein Geheimnis nennt das Repo nur beim Namen;
- Zugangsdaten in Beispielen, Tests oder Logs (auch „zum Ausprobieren“);
- echte Daten: Exporte aus Konten, Umsätze, Fotos, Mitschnitte, Gesundheitsdaten, auch nicht als Testdaten;
- Adressen privater Netze und Geräte, Namen interner Domains, Namen echter Personen;
- Ordner mit Zustand (`.venv`, Datenbanken, Zwischenspeicher).

Stattdessen: neutrale Beispiele (Alex, Fy, `example.com`), Vorlagen mit Platzhaltern (`secrets.example.yaml`), echte Werte nur
in der Umgebung des Hubs, in `/run/secrets` oder im Secret des Clusters. `tools/sauber.py` läuft lokal vor jedem Commit und in
der CI und fängt die gröbsten Fehler ab; er ersetzt kein Nachdenken. Ein einmal veröffentlichtes Geheimnis gilt als verbrannt:
Schlüssel tauschen, nicht nur das Repo ändern.

---

## 11. Checkliste: „Mein Plugin ist fertig“

**Paket**
- [ ] Name `fyos-plugin-<name>`, Python-Paket `fyos_plugin_<name>`; Entry-Point `mcp_hub.plugins` zeigt auf die Klasse
- [ ] `uv pip install -e ".[test]"` und `python3 -m mcp_hub.server`: das Plugin steht in `/hub/health` ohne Fehler
- [ ] `version` in `pyproject.toml` und Klasse stimmen überein; Oberfläche und Katalog stehen in `package-data`

**Werkzeuge**
- [ ] Jedes Werkzeug hat `description` mit den Wörtern, mit denen jemand fragt; `input_schema` beschreibt jedes Feld und nennt `required`
- [ ] Genau ein Scope-Tag (`read`, `write`, `destructive`, `exec`); `extern`, wenn es nach außen ruft; `flaeche`, wenn die Shell es rufen darf
- [ ] Eingaben prüft das Plugin selbst und wirft `ValueError` mit einem verständlichen Satz
- [ ] Jedes schreibende Werkzeug kann `__dry_run__` und ändert dabei nichts
- [ ] Ein schreibendes Werkzeug, das eine Oberfläche ruft, verlangt für den echten Lauf `bestaetigt: true` (§3.6)
- [ ] Netzaufrufe mit Timeout; Ergebnisse klein, mit einem `satz`
- [ ] Geheimnisse nur aus Umgebung oder `secrets:`; nie im Ergebnis, im Log, in `health()`
- [ ] `argumente_vertraulich = True`, wenn Argumente Zugangsdaten oder Persönliches tragen können (§2.4)

**Oberfläche (falls vorhanden)**
- [ ] `ui://`-Ressource, `registriere_app` beim Import, `meta.ui.resourceUri` an den Werkzeugen
- [ ] Nur gemeinsamer Stil und Brücke; keine Modaldialoge; alles Eingefügte mit `esc()`
- [ ] Jedes Panel mit Daten trägt einen Frische-Stempel (`App.frische`); ein gescheitertes Neuladen lässt die alten Daten mit altem Stempel stehen
- [ ] Kein Knopf schreibt direkt: Kleines über `App.beantragen` (Plan, „Ja“, `bestaetigt: true`), Schweres nur als Bitte an Agent oder Mensch (§3.6)
- [ ] In allen vier Größenstufen geprüft, in Hell und Dunkel
- [ ] Deeplink `/os?offen=app:<plugin>__<werkzeug>` öffnet die App

**Wissen und Verhalten**
- [ ] `fyos_plugin_<name>/skills/<name>/SKILL.md` mit `name` und aussagekräftiger `description`; in `package-data` und Entry-Point `fyos.skills`
- [ ] Regeln für jedes Gespräch stehen nicht im Skill, sondern in `fyos-agent` (Vertrag, Vorlagen); Durchzusetzendes als OpenClaw-Plugin mit Tests

**Installer**
- [ ] `fyos-katalog.yaml` mit `kurz`, `was_daraus_wird`, Bild, `quelle`, Feldern; Entry-Point `fyos.katalog`
- [ ] `fyos-install --liste` zeigt den Baustein; `--auswahl <id> --ziel dateien --trocken` erzeugt sinnvolle Dateien

**Tests und Sauberkeit**
- [ ] pytest grün: Werkzeuge, Trockenlauf, Fehlerarten, Laden, REST-Wege, Oberfläche, Katalog, Skill
- [ ] `python3 tools/sauber.py .` ohne Befund
- [ ] CI-Lauf grün (`.gitea/workflows/ci.yml`)

**Ausliefern**
- [ ] Hub-Bild gebaut und gestartet (`docker build …`), Werkzeuge sind über `/hub/call` erreichbar
- [ ] README des Plugins: Zweck, Werkzeuge mit Scope, Konfiguration (Tabelle `config`/Umgebung/Bedeutung), Einrichtung der Begleiter, Tests
- [ ] Nichts Persönliches im Repo, oder das Repo ist privat

---

*Das Muster:* `fyos-plugin-vorlage` (Hub-Plugin mit zwei Werkzeugen, App, Skill, Katalogeintrag, Tests, CI,
`umbenennen.py`). Fragen und Verbesserungen an dieser Anleitung gehören in dasselbe Repo wie die Änderung, die sie nötig macht.
