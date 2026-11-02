# Extending FYOS

A guide for everyone who wants to add capabilities, interfaces, knowledge or behaviour of their own to FYOS — For Your
Own Sake without changing the distribution. The examples are checked against the code of this version; where a route
is not finished yet, it says **(in progress)**.

A working sample belongs to this guide: the repo **`fyos-plugin-vorlage`**. It does exactly what is described here
(tools, app, skill, catalog entry, tests, CI) and turns into a plugin of your own with `python3 umbenennen.py <name>`.
If you prefer copying to reading, start there.

Contents: 1 Overview · 2 Hub plugin · 3 Interface · 4 Knowledge for the agent · 5 Agent behaviour · 6 Shell ·
7 Installer catalog · 8 Companion services · 9 Testing · 10 Delivery · 11 Checklist

---

## 1. Overview

FYOS consists of layers (see `ARCHITECTURE.md`). Each has a small extension point of its own:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ your plugin repo     fyos-plugin-<name>                                     │
│   Python package     Hub plugin (tools) + ui:// interface + skills          │  §2 §3 §4
│   fyos-katalog.yaml  entry in the installer                                 │  §7
│   begleiter/, dienst/  scripts on other devices, containers of your own     │  §8
│   shell/*.ts         surfaces for the shell                                 │  §6
├────────────────────────────────────────────────────────────────────────────┤
│ fyos-os              hub/   MCP hub, loads plugins through entry points     │
│                      web/   shell: apps from the Hub, registriereFlaechen,  │  §6
│                             fyos.config.json                                │
│                      installer/  catalog, pictures, file generation         │  §7
├────────────────────────────────────────────────────────────────────────────┤
│ fyos-agent           the agent: runner on pi-durable, agent-runner.json     │  §5
│                      (schedules, approvals, message routes)                 │
└────────────────────────────────────────────────────────────────────────────┘
```

The ground rule: **whatever a particular home, account or person needs is a plugin in a repo of its own.** The
distribution stays general. A plugin therefore never has to change `hub/`, `web/` or `fyos-agent`.

### I want … → use …

| I want … | use … | see |
|---|---|---|
| the agent and the apps to be **able** to do something new (fetch data, switch a device, ask a service) | a **Hub plugin** with tools | §2 |
| a **window or a tile** for it in the shell | a **hub app** (`ui://` interface on the tool) | §3 |
| the app to show **how fresh its data is**, and a button to trigger **nothing that writes without asking** | `App.frische` and `App.beantragen` of the bridge; heavy steps only as a request to the agent or a person | §3.6 |
| to teach the agent **when and in which order** it uses the tools | a **skill** (`SKILL.md`) in the plugin | §4 |
| a rule that applies to **every** conversation ("always ask first when …") | the behaviour of the **runner** in `fyos-agent` | §5 |
| a rule that a prompt **cannot talk its way around** (budget, quiet hours, lock) | **approvals in the Hub** (tool with `write` scope, ticket `waiting_approval`) and the runner's limits | §2, §5 |
| to change the agent's name, schedules, message routes | **`agent-runner.json`** | §5 |
| to reach an existing web page or service (Git, Grafana) in the OS | **`fyos.config.json`** (`extern`) | §6 |
| a page or Solid component of my own as a surface in the shell | **`registriereFlaechen`** in `web/src/plugins/` | §6 |
| my building block to be selectable in the **installer**, with a picture and an explanation | **`fyos-katalog.yaml`** | §7 |
| a program on the **Mac** or another device that delivers data | a **companion script** | §8 |
| a **service of my own** with a database or compute load | a **container** next to the Hub; the plugin talks to it | §8 |
| to have something done **regularly** that fetches or syncs data | a **schedule in the Hub plugin**, reported through `zeitplan()`; with a daily limit and time window through the guard | §2.4, §2.12 |
| to have something done regularly that needs the **model** (summarise, write) | a **runner schedule** (`takt.eintraege` in `agent-runner.json`) | §5, `NIGHT-WORK.md` |
| to **track** work that goes beyond one conversation | **tickets**: a ticket service (`FYOS_VORGAENGE_URL`) or a plugin that registers as the store | §2.13 |
| to show or create **appointments** without speaking CalDAV myself | the **appointment source** `mcp_hub.termine`; whoever delivers appointments registers as the store (for example `fyos-plugin-kalender`) | §2.14 |
| to read **mail** (read only) without speaking IMAP myself | the **mailbox source** `mcp_hub.postfach`; whoever delivers mail registers as the store (for example `fyos-plugin-mail`) | §2.15 |
| to search, read and file **documents** without speaking Paperless myself | the **document source** `mcp_hub.dokumente`; a Paperless-ngx as the service (`FYOS_DOKUMENTE_URL`) or a plugin that registers as the store | §2.16 |
| to store, read and search **files** (notes, pictures, PDFs), with trash and earlier versions | the **file source** `mcp_hub.dateien` and the app "Files"; a folder (volume) through `FYOS_DATEIEN` | §2.17 |
| that something can be **dragged from my app into another one** (a note into the files, a file onto the notepad) | `registriere_ding` and `registriere_uebergabe` in the plugin, `App.ziehbar` and `App.ablage` in the interface | §3.7 |

A typical project uses several of these at once. "Weather", for example: the Hub plugin `wetter` (§2) with an app (§3),
a skill (§4) and a catalog entry (§7) in a repo `fyos-plugin-wetter`.

---

## 2. Hub plugin step by step

A Hub plugin is a Python class that extends `mcp_hub.plugin.HubPlugin`. The Hub loads it in its own process (no network
call between Hub and plugin) and offers its tools to the agent (MCP at `/mcp`), to the shell (`/hub/app-call`) and to
scripts (`/hub/call`). The routes are described in `HUB-CONTRACT.md`.

### 2.1 Package structure

```text
fyos-plugin-wetter/
├── pyproject.toml                  package + entry point
├── fyos_plugin_wetter/
│   ├── __init__.py
│   ├── plugin.py                   the class WetterPlugin
│   ├── ui/wetter.html              (optional) the interface, see §3
│   └── skills/wetter/SKILL.md      (optional) knowledge for the agent, see §4
├── tests/test_plugin.py
└── tools/sauber.py, .sauber/       cleanliness check, see §9
```

The package name starts with `fyos-plugin-` (the installer recognises plugin packages by it, §7), the Python package
with `fyos_plugin_`. The sample `fyos-plugin-vorlage` has exactly this shape.

### 2.2 pyproject.toml with an entry point

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "fyos-plugin-wetter"
version = "0.1.0"
description = "Weather for FYOS"
requires-python = ">=3.11"
dependencies = ["fyos-hub"]

[project.optional-dependencies]
test = ["pytest>=8"]

# The Hub loads every installed package of this group on its own, without an entry in its configuration.
[project.entry-points."mcp_hub.plugins"]
wetter = "fyos_plugin_wetter.plugin:WetterPlugin"

# (optional) skills in the package's subfolder skills/, see §4.2
[project.entry-points."fyos.skills"]
wetter = "fyos_plugin_wetter"

[tool.setuptools]
packages = ["fyos_plugin_wetter"]

[tool.setuptools.package-data]
fyos_plugin_wetter = ["ui/*", "skills/*/*.md"]   # interfaces and skills belong in the package

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

The name left of the `=` is the entry point name; it should match the class's `name`. Because of `package-data` the
HTML files end up in the installed package.

### 2.3 The smallest plugin

```python
# fyos_plugin_uhr/plugin.py
from datetime import datetime, timezone

from mcp_hub.plugin import HubPlugin, ToolDescriptor


class UhrPlugin(HubPlugin):
    name = "uhr"                      # prefix of all tool ids: uhr.jetzt
    description = "Tells the time."
    version = "0.1.0"

    def register(self) -> None:
        pass                          # once at startup: open connections, read credentials

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="jetzt",
                description="Current time (UTC). Read-only.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                tags=["uhr", "read"],
            )
        ]

    def call(self, method: str, args: dict) -> dict:
        if method == "jetzt":
            return {"zeit": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        raise ValueError(f"uhr has no tool {method!r}")
```

That is enough: `uv pip install -e .` (why uv instead of pip: §10.3), start the Hub, and `uhr.jetzt` is there.

### 2.4 The methods of `HubPlugin`

| Method | Required | When and what for |
|---|---|---|
| `register()` | yes | once at startup, first. Open connections, read credentials. If it raises, **this** plugin is not loaded; the Hub keeps running, and the reason appears under "not loaded" (`/hub/health`, app "MCP"). |
| `init()` | no | afterwards, for setup that depends on other plugins. Same consequences on an error. |
| `describe_tools()` | yes | all tools as `ToolDescriptor`. Called once and cached; must be stable. |
| `describe_resources()` | no | the `ui://` interfaces (§3). |
| `call(method, args)` | yes | runs the tool. `method` is the name **without** the plugin prefix, `args` the argument object. The return value must be JSON-serialisable. |
| `health()` | no | `{"ok": bool, …}`; the Hub asks for it on every map. Do not hit foreign services every second: `mcp_hub.plugin.tiefe_health` keeps a result for a while. |
| `metrics()` | no | metrics for `/metrics` (Prometheus). Numbers in the dict appear as `fyos_plugin_wert{plugin, schluessel}`; own series with labels under `"_proben"`: `[{"name": "fyos_wetter_abrufe_total", "wert": 3, "labels": {"ort": "x"}, "typ": "counter", "hilfe": "…"}]`. Called often: return only what you have already remembered. |
| `zeitplan()` | no | the plugin's recurring jobs, for example `[{"id": "abruf", "name": "Wetter holen", "takt": "alle 15 min", "letzter": 1760000000.0, "letzter_status": "ok"}]`. They appear in `mcp.zeitplan` next to the agent's cron jobs and in `/metrics`. If you have a schedule, report it here. Daily limit, time window and run log for a schedule: §2.12. |
| `skills_beitrag()` | no | skills that are not files in the package (for example from a connected service): `[{"name", "beschreibung", "text"}]` or, instead of `text`, a call `lesen`. Skills as files in the package (§4.2) do not need this. |
| `registry_anbinden(registry)` | no | once after all plugins have loaded: the registry, if the plugin needs other plugins or the call hooks (`registry.on_call_hooks`). Rarely needed. |
| `shutdown()` | no | on exit: close connections. Errors are swallowed. |
| `routen()` | no | own HTTP routes as a list of Starlette `Route`, only under `/hub/`, for example `Route("/hub/meins/melden", fn, methods=["POST"])`. For things that should not be a tool (a client's telemetry); a route that is already taken is rejected (Hub contract §4). |

Class attributes: `name` (unique in the Hub, lower case, digits and underscores, never two underscores in a row),
`description` (one sentence, appears in the tool map), `version` (SemVer) and `argumente_vertraulich` (default
`False`). Set it to `True` if your tools' arguments can carry credentials or personal data, for example names of vault
entries or notes: the event bus (`event_bus_publisher`, streams `bus.tool.*`) then publishes them only as
`{"redacted": true}`, whatever configuration the operator has put together.

The call to `call` runs in a thread of its own with a time limit. So write **synchronous**, thread-safe code and set
your own timeouts on network calls (the Hub's limit is the safety net underneath, not a replacement).

### 2.5 Tool ids and names

- The id is `<plugin>.<tool>` (`wetter.vorhersage`). The agent and scripts use it like that.
- As an MCP app the same tool is called `<plugin>__<tool>` (`wetter__vorhersage`); names in deep links look like this
  (§3).
- Tool names: lower case, underscores, no dot, no double underscore.
- **The ids are your interface.** Skills, deep links and saved shell layouts refer to them. Do not rename a published
  tool; add a new one and keep the old one for one version.
- Two tools with the same id or two plugins with the same name are an error.

### 2.6 `ToolDescriptor`: description, schema, tags

```python
ToolDescriptor(
    name="notiz_setzen",
    title="Set note",                          # display name (optional)
    description="Stores a short note … With `__dry_run__: true` only the plan comes back.",
    input_schema={                             # JSON Schema (MCP inputSchema)
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1, "description": "The note"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    tags=["vorlage", "write", "flaeche"],
    meta=None,                                 # interface and identity, see §3
    zeitlimit_s=None,                          # None = the Hub's 120 s, 0 = no limit
)
```

- **`description`** is the most important line. The agent finds your tool through it (search with everyday words).
  Write what it does, what it returns and what it does **not** do, with the words people use ("note", not "entity").
- **`input_schema`**: describe every field (`description`), name the required fields (`required`). With
  `"additionalProperties": False` the Hub checks centrally that no unknown argument slips through (otherwise the caller
  would get a result for a question it never asked). **The Hub does not check types, limits and required fields; your
  plugin does that in `call`.**
- **Tags** set the *scope*, exactly one of: `read` (only reads), `write` (changes, reversible), `destructive` (deletes
  or is not reversible), `exec` (starts processes). Plus `extern` when the tool calls the outside (internet, a foreign
  service), and `flaeche` when the shell may call it through `/hub/app-call`. Without a scope tag the tool appears in
  the map as `UNKNOWN`. Several scope tags: the strictest applies (`destructive` > `extern` > `exec` > `write` >
  `read`).
- Tags of your own (`"wetter"`) are free and help the search.

### 2.7 Reading and writing

- A **reading** tool changes nothing, not even "on the side" (no counter, no cache with consequences). Only reading
  tools get an "Open in FYOS" deep link and may be called by the shell on its own when an app opens. A link never
  triggers anything that writes.
- A **writing** tool gets `write` or `destructive`. The Hub does not enforce an approval; the agent draws the line
  according to its operating concept ("the owner decides heavy steps"), together with the permissions your plugin
  itself has. So give the plugin only the permissions it needs (a read-only token where reading is enough), and split
  dangerous things into small, well-named tools instead of one with a `modus` argument.
- If a writing tool should be called only by the interface, not by the model, set `visibility` (§3).

### 2.8 Dry run

Writing tools should show in advance what they would do. The Hub has an argument for this: `__dry_run__: true`.

```python
from mcp_hub.plugin import build_dry_run_result, is_dry_run


def call(self, method, args):
    if method == "notiz_setzen":
        return self.notiz_setzen(args.get("text"), trocken=is_dry_run(args))
    raise ValueError(f"vorlage has no tool {method!r}")


def notiz_setzen(self, text, trocken=False):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text is missing")
    if trocken:
        return build_dry_run_result(
            would_execute=f"store a note with {len(text.strip())} characters",
            expected_side_effects=["fyos:vorlage:notiz: replaced"],    # "<resource>: <change>"
            estimated_cost=1,                                          # any unit you like, otherwise None
            plugin=self.name,
            method="notiz_setzen",
            args_preview={"text": text.strip()[:40]},                  # no secrets, no large blocks
        )
    ...  # really write
```

- In a dry run change **nothing**, not even a log or a counter.
- A plugin that cannot do a dry run answers `build_dry_run_unsupported(self.name, method)` instead of writing.
- `__dry_run__` is allowed even with `additionalProperties: False`. The dry run belongs in every `write`, `destructive`
  and `exec` tool; only that makes it safe for the agent and for "check only" buttons in the interface.
- If an interface calls the tool, it requires `bestaetigt: true` (a boolean field in the schema) in addition for the
  **real run** and otherwise rejects with `ValueError`: first the plan, then the confirmation, as with
  `werkstatt.ausfuehren`. The interface does this on its own with `App.beantragen` (§3.6).

### 2.9 Configuration and secrets

**Configuration.** The Hub passes the plugin's `config:` block to the constructor if it has a `config` parameter:

```python
def __init__(self, config: dict | None = None):
    super().__init__()
    self.config = dict(config or {})

def _wert(self, schluessel: str, umgebung: str, vorgabe: str) -> str:
    # order: plugin config before environment before default
    return str(self.config.get(schluessel) or os.getenv(umgebung) or vorgabe)
```

Defaults in the code should be neutral and free of foreign addresses; whatever belongs to an installation comes from
`config:` or the environment. The installer (§7) writes catalog fields as environment variables, so a plugin reads the
same values from the environment too (`FYOS_<NAME>_<FIELD>`).

```yaml
# the Hub's config.yaml (MCP_HUB_CONFIG_PATH); an entry is only needed for configuration/secrets/turning off
plugins:
  - name: wetter
    config:
      ort: Musterstadt
    secrets:
      - { name: wetter-token, env: FYOS_WETTER_TOKEN }
    # enabled: false        # turns off an installed plugin
```

**Secrets.** Under `secrets:` only the **name** appears. The Hub resolves it (in order: the variable `env`, the
variable with that name, its environment form `WETTER_TOKEN`, the file `/run/secrets/<name>`) and puts the value into
an environment variable, where your plugin reads it with `os.getenv` (a variable that is already set wins). Rules:

- The secret never appears in the code, never in `config:`, never in the repo, never in a tool result and never in the
  log.
- `health()` reports at most `{"token": true}`, never the value.
- Pass on error messages from foreign services only shortened; they sometimes contain the request including headers.

### 2.10 Error handling

The Hub catches every exception and turns it into an answer; a plugin cannot knock the Hub over.

| You do … | The Hub reports … | HTTP | Circuit breaker |
|---|---|---|---|
| `raise ValueError("limit muss …")` | `kind: bad_arguments` | 400 | does **not** count |
| another exception (`RuntimeError`, network error, …) | `kind: plugin_error` | 502 | counts |
| `return {"ok": False, "error": "…"}` or `{"error": "…"}` without `ok` | `kind: tool_failed`, your result is attached | 502 | does not count |
| runs longer than the time limit | `kind: timeout` | 504 | counts |
| `raise KontoFehlt(anbieter, name, link)` | `kind: konto_fehlt` with the link for connecting | 502 | does not count |
| unknown argument with `additionalProperties: False` | `kind: bad_arguments` | 400 | does not count |

Consequences:

- **Input errors are `ValueError`** with a sentence the agent understands (`"text is too long (400 characters, at most
  280)"`). Too many real failures lock the plugin temporarily (five errors in a row, 30 s `circuit_open`, 503); wrong
  input must never trigger that.
- A read error from upstream (`json.JSONDecodeError`, `UnicodeError`) is a failure, not an input error, even though it
  is a `ValueError`.
- An *expected* "does not work" (device off, no match) can be a normal result (`{"gefunden": False}`) or
  `{"ok": False, "error": "…"}`; choose what helps the caller.
- If a service reports that the person first has to connect an account, raise `mcp_hub.plugin.KontoFehlt`. The person
  gets the link; tokens never end up in the chat.
- Return **small** results. The Hub shortens large answers and returns an `ergebnis_id` (`hub__mehr` drills in). A
  sentence such as `"satz": "3 appointments today."` in every result helps the agent and the interfaces.

### 2.11 Storing data

For a little state there is `mcp_hub.kv.klient()`: Redis if `REDIS_URL` is set, otherwise an in-memory stand-in in the
process (does not survive a restart, applies to one Hub process only). Use keys with a prefix of your own
(`fyos:<plugin>:…`). For data that should last you need Redis or a service of your own (§8).

### 2.12 Limiting and logging schedules

The Hub has no central scheduler: a plugin runs its schedules itself (a thread that waits and works) and reports them
through `zeitplan()`. So that a routine does not run at night and does not run endlessly, there is a small guard,
`mcp_hub.takt.Waechter`. It knows two limits per schedule, both optional:

| Limit | Meaning |
|---|---|
| `max_pro_tag` | at most this many runs per calendar day (integer from 1) |
| `fenster` | only between these times, `"07:00-22:00"` (start included, end excluded); across midnight works too (`"22:00-06:00"`), `"24:00"` is allowed as the end |

A run outside the window or above the limit **does not take place**: the guard does not call the job and counts the
reason (`fenster` or `limit`). The window is checked first; whatever lies outside it uses up nothing of the daily
limit. Day and time apply in the time zone of the Hub process (environment variable `TZ`, UTC if unset; in Compose the
`.env` sets it, in Kubernetes an `env` entry on the Hub). Without limits every run works as before.

```python
from mcp_hub import takt

class WetterPlugin(HubPlugin):
    def __init__(self, config: dict | None = None):
        super().__init__()
        # config:  takt_grenzen: { abruf: { max_pro_tag: 48, fenster: "06:00-23:00" } }
        # takte=… catches typos at startup: a wrong name or an unreadable time prevents loading
        self._waechter = takt.Waechter(self.name, (config or {}).get("takt_grenzen"), takte=("abruf",))
        self._halt = threading.Event()

    def _schleife(self) -> None:                      # runs in its own thread
        while not self._halt.wait(900):
            try:
                self._waechter.ausfuehren("abruf", self._abrufen)   # skipped: Lauf(gelaufen=False, grund="fenster"|"limit")
            except Exception:
                pass                                  # the error is already in the run log

    def zeitplan(self) -> list[dict]:
        return [{"id": "abruf", "name": "Wetter holen", "takt": "alle 15 min", **self._waechter.felder("abruf")}]
```

`ausfuehren(takt, tun)` returns `Lauf(gelaufen, grund, wert)`. If `tun` raises, the exception is passed on unchanged
after it has been logged; a result `{"ok": False, …}` counts as an error there. A call on demand (a tool someone calls)
is not a schedule and runs without the guard.

**Run log.** Every run records start, duration and result in the Hub's storage (`mcp_hub.kv`, §2.11): a list of the
last 20 runs per schedule (expires after a week without a run) and a daily counter (expires after three days). Error
texts are stored shortened and without credentials. The storage is only an accessory: if it does not answer, the
schedule runs anyway; the guard then keeps counting the day in the process and leaves the storage alone for 30 s.
Without `REDIS_URL` the counters only last until the Hub restarts.

**What you see.** `felder(takt)` adds to the `zeitplan()` entry: `max_pro_tag`, `fenster`, `ruht` (`fenster` or
`limit` if the schedule may not run right now), `laeufe_heute`, `uebersprungen` (today, per reason) and `protokoll`
(the last five runs). `mcp.zeitplan` shows them; `/metrics` carries them as `fyos_zeitplan_laeufe_heute{takt}`,
`fyos_zeitplan_max_pro_tag{takt}` and `fyos_zeitplan_uebersprungen_total{takt, grund}` (`takt` is the id
`<plugin>:<id>` from `mcp.zeitplan`). The usual way is a key `takt_grenzen` in the plugin's `config`, which it passes
to the guard.

The agent's schedules are in its own configuration (`agent-runner.json`). Window and daily limit here apply to schedules
the Hub runs itself.

### 2.13 Reading and answering tickets

A plugin that shows or answers tickets (approvals, questions, tasks) does not hard-code an address; it asks
`mcp_hub.vorgaenge.quelle()`. Depending on the installation, the source is one of three:

| `art` | when | what you get |
|---|---|---|
| `dienst` | a ticket service is configured (`FYOS_VORGAENGE_URL`, header line `FYOS_VORGAENGE_KOPF`; extended tier, a ticket service of its own) | the whole ticket contract; whatever else the service can do (history, waiting lists) `roh()` passes through |
| `ablage` | no service, but a plugin has registered as the store (`vorgaenge.ablage_anmelden`, protocol `vorgaenge.Ablage`); since 0.3.0 that is the ITSM in the core (plugin `itsm`, the Hub's Redis, docs/ITSM.md) | the contract as far as the store knows it; assignees and `waiting_for` only if it keeps them (the ITSM keeps both) |
| `keine` | neither | empty lists; fetching a single ticket and writing report `NichtEingerichtet` |

```python
from mcp_hub import vorgaenge

def braucht_dich(self) -> dict:
    q = vorgaenge.quelle()                       # ask anew on every call, it is cheap
    if not q.eingerichtet:
        return {"satz": "No store for tickets set up.", "eintraege": []}
    offen = q.freigaben()                        # waiting_approval
    return {"satz": f"{len(offen)} approvals waiting.", "quelle": q.art, "eintraege": offen}

# Answering: first the comment, then the status with the state the interface saw
q.kommentieren(vid, "Yes, after 10 pm.", actor="besitzer")
q.aendern(vid, status="in_progress", expected_status="waiting_approval", actor="besitzer")
q.verlauf(vid, grenze=5)                         # newest first: {ts, event, actor, detail}
```

Errors: `VorgangFehlt` (does not exist), `VorgangKonflikt` (has changed in the meantime, with the current state in
`.vorgang`), `ValueError` (input), `QuelleFehler` (service or store does not answer), `NichtEingerichtet`. Fields the
contract does not know are not sent by `aendern()`. Status: `new triage in_progress waiting_approval resolved closed`.

The ticket contract (service over HTTP): `GET /tickets?status=&limit=`, `GET /tickets/{id}`, `POST /tickets`,
`POST /tickets/{id}/comments` `{actor, text}`, `PATCH /tickets/{id}` `{status, expected_status?, actor?, title?,
description?, priority?}`; `409` with the current state if `expected_status` no longer matches.

### 2.14 Reading and creating appointments

A plugin that shows appointments (start page, daily brief, control room) or creates them does not hard-code an address
and does not speak CalDAV; it asks `mcp_hub.termine.quelle()`. Depending on the installation, the source is one of
three:

| `art` | when | what you get |
|---|---|---|
| `dienst` | an appointment service is configured (`FYOS_TERMINE_URL`, header line `FYOS_TERMINE_KOPF`; extended tier, a calendar service of its own) | appointments, calendars and creating over HTTP (contract below) |
| `ablage` | no service, but a calendar plugin has registered as the store, for example `fyos-plugin-kalender` (basic tier: CalDAV and ICS accounts, nothing else to run) | the same, in-process |
| `keine` | neither | `termine()`, `kalender()` and `anlegen()` report `NichtEingerichtet` |

Unlike with tickets (§2.13), the source "keine" does **not** return an empty list; it raises. Whoever shows
appointments has to keep three states apart, and none may look like another:

```python
from mcp_hub import termine

def heute(self) -> dict:
    try:
        liste = termine.quelle().anstehende(1)          # ask anew on every call, it is cheap
    except termine.NichtEingerichtet:
        return {"zustand": "nicht eingerichtet"}        # own hint with the way to set it up; neither red nor "no appointments"
    except termine.QuelleFehler as e:
        return {"zustand": "fehler", "fehler": str(e)}  # source down or no access: never "no appointments"
    return {"zustand": "ok", "termine": liste}          # empty too: the source answered, there are no appointments

q = termine.quelle()
q.termine("2026-10-12", "2026-10-19", kalender="Privat")   # window [from, to); datetime, date or ISO text
q.kalender()                                               # [{id, name, konto, schreibbar}]
q.anlegen({"titel": "Zahnarzt", "start": "2026-10-15T09:00", "ort": "Praxis"})
```

**Appointment format.** Every appointment is a `dict` with exactly these fields; service and store deliver it the same
way, the list is sorted by start (all-day ones of a day first), at most 1000 entries:

| Field | Content |
|---|---|
| `id` | id in the source, never empty |
| `titel` | title on one line (`(ohne Titel)` if the source names none) |
| `start` | all-day: the date `YYYY-MM-DD`, otherwise an ISO 8601 timestamp, with an offset if the source names one |
| `ende` | like `start`; for all-day appointments the day **after** the last day (as in iCalendar and Google) |
| `ganztaegig` | `true` or `false` |
| `ort` | location on one line, otherwise `""` |
| `kalender` | name of the calendar, otherwise `""` |
| `konto` | name of the account or the source behind it, otherwise `""` |

An appointment's description is not part of it; `anlegen()` accepts it only when someone passes it explicitly. Input
for `anlegen()`: `titel`, `start`, optionally `ende`, `ganztaegig`, `ort`, `beschreibung`, `kalender`. For all-day
appointments `start` and `ende` are days (if `ende` is missing, it is one day); otherwise they have a time (if `ende`
is missing, the appointment lasts one hour). `pruefe_neu()` rejects unknown fields and appointments longer than 366
days before the source sees anything. There is no changing or deleting.

**Who delivers appointments.** A plugin registers as the store and fulfils the protocol `termine.Ablage` (three
methods, data instead of HTTP). If `mcp_hub.termine` is missing (fyos-hub 0.1.0), the plugin still runs, only without
registering:

```python
from mcp_hub.plugin import HubPlugin

try:
    from mcp_hub import termine
except ImportError:                                  # core without an appointment source
    termine = None

class KalenderPlugin(HubPlugin):
    name = "kalender"

    def registry_anbinden(self, registry) -> None:
        if termine is not None:
            termine.ablage_anmelden(self)

    def shutdown(self) -> None:
        if termine is not None and termine.angemeldete_ablage() is self:
            termine.ablage_anmelden(None)

    def ablage_kalender(self) -> list[dict]:                      # {id, name, konto, schreibbar}
        ...

    def ablage_termine(self, von, bis, kalender=None) -> list[dict]:   # appointments in the appointment format; from and to with an offset
        ...

    def ablage_anlegen(self, termin: dict) -> dict:               # already checked; returns the appointment in the appointment format
        ...
```

The plugin raises its own errors as `termine.QuelleFehler` with a text that can be shown to readers (without
credentials). Every other exception the core passes on only as its type ("The calendar plugin reports an error
(KeyError)"), never as text.

**Appointment service.** The extended tier is an HTTP service at `FYOS_TERMINE_URL`; the header line from
`FYOS_TERMINE_KOPF` (`Name: Value`) goes with every request, redirects are not followed. The contract is that of the
calendar service FYOS has run so far:

* `GET /api/calendar/events?who=all&days=N&start=<ISO>&end=<ISO>` answers with `{"events": [{id, title, start, end,
  all_day, location, calendar_id, calendar_name, source}], "_stub": false}`. A service that only understands `days`
  delivers the window from now. `"_stub": true` means "no access to the calendars" (`_message` says why); that is a
  `QuelleFehler` with status 503, never an empty list.
* `GET /api/calendar/calendars` answers with `{"calendars": [{id, summary, access_role}], "status": "live"}`.
* `POST /api/calendar/events` with `{title, start, end, all_day, location, description, calendar_id}` creates the
  appointment and answers with `{"id": …}`. If the service does not have the route (404, 405, 501), `anlegen()` says so
  clearly.

**Environment** (read on every call):

| Variable | Effect |
|---|---|
| `FYOS_TERMINE_URL` | address of the appointment service; when set, it takes precedence over the calendar plugin |
| `FYOS_TERMINE_KOPF` | one header line for the service, `Name: Value` |
| `FYOS_ZEITZONE` | the Hub's time zone (IANA name such as `Europe/Berlin`, or `UTC`); if unset, the machine's. It applies to all-day appointments and to times without an offset |

Errors: `QuelleFehler` (service or plugin down, without access or not answering as agreed; inherits from
`vorgaenge.QuelleFehler` so that one `except` catches both sources), `NichtEingerichtet` (a `QuelleFehler`, but not
from `vorgaenge.NichtEingerichtet`: whoever catches "no ticket source" should not catch "no calendar") and `ValueError`
(input, for example a window with `bis` before `von` or longer than 366 days).

### 2.15 Reading mail

A plugin that shows mail (control room, daily brief, start page) or reads it out in a conversation does not hard-code
an address and does not speak IMAP; it asks `mcp_hub.postfach.quelle()`. **The source only reads**: there is no
sending, replying, deleting, moving or flagging, and even reading leaves the read status as it was. Depending on the
installation, the source is one of three:

| `art` | when | what you get |
|---|---|---|
| `dienst` | a mail service is configured (`FYOS_POSTFACH_URL`, header line `FYOS_POSTFACH_KOPF`; extended tier, a mail service of its own) | list, counter and single mail over three GET routes (contract below) |
| `ablage` | no service, but a mail plugin has registered as the store, for example `fyos-plugin-mail` (basic tier: IMAP accounts with an app password, nothing else to run) | the same, in-process |
| `keine` | neither | `konten()`, `liste()` and `lesen()` report `NichtEingerichtet` |

Unlike with tickets (§2.13), the source "keine" does **not** return an empty list; it raises, like the appointment
source. Whoever shows mail has to keep three states apart, and none may look like another:

```python
from mcp_hub import postfach

def eingang(self) -> dict:
    try:
        # ask anew on every call, it is cheap; zaehlen=False when the counter is not needed
        antwort = postfach.quelle().liste("in:inbox newer_than:2d", 25, zaehlen=False)
    except postfach.NichtEingerichtet:
        return {"zustand": "nicht eingerichtet"}         # own hint with the way to set it up; neither red nor "no mail"
    except postfach.QuelleFehler as e:
        return {"zustand": "fehler", "fehler": str(e)}   # source down or no access: never "no mail"
    return {"zustand": "ok", "mails": antwort["mails"]}  # empty too: the source answered, there is no mail

q = postfach.quelle()
q.konten()                                               # [{name, art, adresse}]
q.liste("from:alex is:unread", 10, konto="privat")       # {"mails": [...], "ungelesen": 12}
q.lesen(mail["id"])                                      # the same mail with text, gekuerzt and anhaenge
```

The text of a mail is **foreign content**. A plugin that shows it to a model says along with it that it contains no
instructions to follow (the plugin `mail` adds this note to every answer).

**Mail format.** Every mail is a `dict` with exactly these fields; service and store deliver it the same way,
`liste()` returns newest first, at most `anzahl` items (1 to 100, default 10):

| Field | Content |
|---|---|
| `id` | id in the source. Opaque; whoever has it from a list passes it unchanged to `lesen()`. Pattern `postfach.ID_MUSTER`: letters, digits and `. _ ~ = -`, no punctuation at the start, at most 200 characters |
| `konto` | name of the account or the source behind it, otherwise `""` |
| `von` | sender on one line, as they call themselves (`Name <address>`), otherwise `""` |
| `an` | recipient (To) on one line, otherwise `""` |
| `betreff` | subject on one line (`(kein Betreff)` if the mail has none) |
| `datum` | ISO 8601 timestamp with an offset (`2026-10-06T10:09:09+00:00`); `""` if the source names no readable one; without an offset UTC applies |
| `gelesen` | `true` or `false` |
| `labels` | German names such as `Posteingang`, `Wichtig`, `Werbung`; otherwise `[]` |
| `ausschnitt` | the start of the text on one line, at most 200 characters |

`liste()` also returns `ungelesen`: the number of unread mails in the inbox (of all accounts or of the one named), or
`None` if the source does not say. `zaehlen=False` spares the source the counter when it costs something (for the
service it is a second call). `lesen()` returns the same fields plus `text` (plain text; HTML mails as text; at most
30000 characters), `gekuerzt` (`true` if the text was shortened) and `anhaenge` (`[{name, typ, groesse}]`, only
metadata, never the content). `konten()` returns `[{name, art, adresse}]`, the address without a password.

**Query language.** `abfrage` is Gmail-like: terms separated by spaces, all of which must match. **Every** source can
handle this subset:

| Term | Meaning |
|---|---|
| `from:value` | sender contains `value` (name or address) |
| `to:value` | recipient contains `value` |
| `subject:value` | subject contains `value` |
| `is:unread` | only unread mail |
| `newer_than:Nd` / `older_than:Nd` | at most / at least `N` days old (`N` an integer, unit `d`) |
| `in:inbox` | only the inbox |
| free words | every word occurs in the mail: in the subject or the text, depending on the source also in the addresses |

`value` is a word or an expression in quotes (`subject:"two words"`); case does not matter; an empty query means
`in:inbox`. Anything beyond that (`-category:promotions`, `label:`, `has:attachment`, `in:sent`, `OR`) a source may
evaluate or ignore, but never reject as an error. The service passes the query unchanged to its Gmail. The mail plugin
does the same for a Gmail account; for every other account it translates the subset into IMAP SEARCH and also
understands `in:sent` (and `drafts`, `trash`, `spam`), `is:read`, `after:` and `before:`, the units `w`, `m` and `y`
and a minus in front of a term. What it does not understand, including `OR` and brackets, it does not read as "and"
(that would find less than intended); it skips it and names it in its answer (`ignoriert`). Without `in:` the source
decides where to search; the mail plugin searches the folders configured for the account (by default the inbox).
Whoever relies on more than the subset ties themselves to sources that can do it.

**Who delivers mail.** A plugin registers as the store and fulfils the protocol `postfach.Ablage` (three reading
methods, data instead of HTTP). If `mcp_hub.postfach` is missing (fyos-hub before 0.1.1), the plugin still runs, only
without registering:

```python
from mcp_hub.plugin import HubPlugin

try:
    from mcp_hub import postfach
except ImportError:                                  # core without a mailbox source
    postfach = None

class MailPlugin(HubPlugin):
    name = "mail"

    def registry_anbinden(self, registry) -> None:
        if postfach is not None:
            postfach.ablage_anmelden(self)

    def shutdown(self) -> None:
        if postfach is not None and postfach.angemeldete_ablage() is self:
            postfach.ablage_anmelden(None)

    def ablage_konten(self) -> list[dict]:                        # {name, art, adresse}, the address without a password
        ...

    def ablage_liste(self, abfrage, anzahl, konto=None) -> dict:  # {"mails": [...], "ungelesen": number or None}
        ...

    def ablage_lesen(self, id) -> dict:                           # the mail in the mail format with text, gekuerzt, anhaenge
        ...
```

The plugin raises its own errors as `postfach.QuelleFehler` with a text that can be shown to readers (without
credentials), an unknown account as `ValueError`. Every other exception the core passes on only as its type ("The mail
plugin reports an error (KeyError)"), never as text. A plugin without a configured account does not register at all or
raises `postfach.NichtEingerichtet`; that keeps "no mailbox" distinguishable from "mailbox empty".

**Mail service.** The extended tier is an HTTP service at `FYOS_POSTFACH_URL`; the header line from
`FYOS_POSTFACH_KOPF` (`Name: Value`) goes with every request, redirects are not followed, **only GET is used**. The
contract is that of the mail service FYOS has run so far:

* `GET /api/inbox/list?q=<query>&limit=N` answers with `{"status": "live", "messages": [{id, subject, from, to, date,
  snippet, label_ids, unread}], "_stub": false}`. `q` is the query unchanged. `"_stub": true` or a `status` other than
  `live` and `refreshed` means "no access to the mailbox" (`_message` says why); that is a `QuelleFehler` with status
  503, never an empty list.
* `GET /api/inbox/unread-count` answers with `{"inbox_unread": N, …}`. If the counter is missing, the list stays valid
  and `ungelesen` is `None`.
* `GET /api/inbox/message/<id>` answers with `{id, subject, from, to, date, label_ids, unread, body_plain, body_html,
  attachments: [{filename, mime_type, size}]}`; the core takes `body_plain`, otherwise the text from `body_html`.

The service has one account, `dienst`. `date` may be in mail format; `label_ids` are Gmail's system labels (`INBOX`,
`IMPORTANT`, `CATEGORY_PROMOTIONS` …); the core turns them into the German names.

**Environment** (read on every call):

| Variable | Effect |
|---|---|
| `FYOS_POSTFACH_URL` | address of the mail service; when set, it takes precedence over the mail plugin |
| `FYOS_POSTFACH_KOPF` | one header line for the service, `Name: Value` |

Errors: `QuelleFehler` (service or plugin down, without access or not answering as agreed; inherits from
`vorgaenge.QuelleFehler` so that one `except` catches the sources together), `NichtEingerichtet` (a `QuelleFehler`,
but not from `vorgaenge.NichtEingerichtet`: whoever catches "no ticket source" should not catch "no mailbox") and
`ValueError` (input, for example an invalid id, a count outside 1 to 100 or an unknown account).

### 2.16 Searching, reading and filing documents

A plugin that shows documents (control room, daily brief, start page) does not hard-code an address and does not speak
Paperless; it asks `mcp_hub.dokumente.quelle()`. Depending on the installation, the source is one of three:

| `art` | when | what you get |
|---|---|---|
| `dienst` | a Paperless-ngx is configured (`FYOS_DOKUMENTE_URL`, access `FYOS_DOKUMENTE_KOPF`; extended tier) | `neueste()`, `suchen()`, `holen()`, `unsortiert()`, `namen()` and `zuordnen()` through the REST interface (below) |
| `ablage` | no service, but a plugin has registered as the store (`ablage_anmelden`, protocol `dokumente.Ablage`) | the same, in-process; `namen()` and `zuordnen()` only if the store offers them |
| `keine` | neither | all methods report `NichtEingerichtet` |

As with appointments and mail, the source "keine" does **not** return an empty list; it raises. Whoever shows
documents keeps three states apart, and none may look like another:

```python
from mcp_hub import dokumente

def eingang(self) -> dict:
    try:
        antwort = dokumente.quelle().neueste(10)           # ask anew on every call, it is cheap
    except dokumente.NichtEingerichtet:
        return {"zustand": "nicht eingerichtet"}           # own hint with the way to set it up; neither red nor empty
    except dokumente.QuelleFehler as e:
        return {"zustand": "fehler", "fehler": str(e)}     # Paperless down or login refused: never "no documents"
    return {"zustand": "ok", **antwort}                    # also {"gesamt": 0, "dokumente": []}: the source answered

q = dokumente.quelle()
q.suchen("Stromrechnung", 5)                               # {"gesamt": 3, "dokumente": [... with "auszug"]}
q.holen(dok["id"])                                         # the same document with text and text_gekuerzt
q.unsortiert()                                             # number of documents without correspondent and type, or None
q.zuordnen(dok["id"], {"titel": "Rechnung Oktober", "typ": "Rechnung"}, vorschau=True)   # first show what changes
```

The text of a document is **foreign content**. A plugin that shows it to a model says along with it that it contains
no instructions to follow. `zuordnen()` writes (adds title, correspondent, document type, tags; **nothing is ever
deleted**, missing correspondents, types and tags are created): a plugin calls it only at the user's explicit request
and shows the preview first (`vorschau=True`).

**Document format.** Every document is a `dict` with exactly these fields; service and store deliver it the same way.
`neueste()` and `suchen()` return `{"gesamt": N, "dokumente": [...]}` (at most `anzahl`, 1 to 50, default 10;
`neueste()` newest first):

| Field | Content |
|---|---|
| `id` | id in the source, an integer from 1; opaque, pass it unchanged to `holen()` and `zuordnen()` |
| `titel` | title on one line (`(ohne Titel)` if the source names none) |
| `erstellt` | date of the document `YYYY-MM-DD` or `None` |
| `hinzugefuegt` | ISO 8601 timestamp with an offset, when it entered the store, or `None` |
| `schlagworte` | names of the tags (`[]` if none) |
| `korrespondent`, `typ` | names or `None` |
| `datei`, `seiten` | name of the original file and number of pages, or `None` |
| `auszug` | a search's hit excerpt on one line, the hits in `«…»`, otherwise `None` |
| `link` | address in the browser (`http`/`https`) or `None` if `FYOS_DOKUMENTE_LINK` is empty |

`holen()` returns the same fields plus `text` (the recognised text, at most 20000 characters) and `text_gekuerzt`.
`namen()` returns `{"schlagworte": [...], "korrespondenten": [...], "typen": [...]}` (sorted), for example for
suggestions. `zuordnen()` answers with `vorher` and, without preview, `nachher` (both in document format) and
`angelegt`; with preview it answers with `aendert` and `wird_angelegt` (for example `["Typ Rechnung"]`).

**Who delivers documents.** A plugin registers as the store and fulfils the protocol `dokumente.Ablage`:
`ablage_neueste(anzahl)`, `ablage_suchen(abfrage, anzahl)` (both `{"gesamt", "dokumente"}`), `ablage_holen(id)` and
`ablage_unsortiert()`; optionally also `ablage_namen()` and `ablage_zuordnen(id, aenderung, vorschau)`. If an optional
method is missing, the source says clearly "this store cannot do that" (status 501) instead of guessing. Registering
and unregistering as in §2.15 (`dokumente.ablage_anmelden(self)` and, on exit, `dokumente.ablage_anmelden(None)`). If
`mcp_hub.dokumente` is missing (fyos-hub before 0.1.1), a plugin still runs, only without registering.

**Paperless-ngx as the service.** The extended tier is a Paperless-ngx at `FYOS_DOKUMENTE_URL` (only the root, without
`/api`). The core uses these routes:

* `GET /api/documents/` with `ordering=-added`, `page_size`, `fields` (newest) or `query` (full-text search; the text
  goes unchanged to Paperless, where field searches such as `tag:rechnung` work too). It reads `count` and `results`
  with `id`, `title`, `created` (date or timestamp), `added`, `tags`, `correspondent`, `document_type`,
  `original_file_name`, `page_count` and, for a search, `__search_hit__.highlights` (marked with `<b>` or
  `<span class="match">`).
* `GET /api/documents/<id>/` for the full document (`content` is the recognised text).
* `GET /api/documents/?correspondent__isnull=1&document_type__isnull=1&page_size=1&fields=id` counts the unsorted ones.
  If the counter fails, the list stays valid and `unsortiert()` is `None`.
* `GET /api/tags/`, `/api/correspondents/` and `/api/document_types/` with `page_size=1000` deliver the names for the
  ids; the core remembers them for five minutes.
* only from `zuordnen()`: `POST /api/tags/` (and `correspondents`, `document_types`) with `{"name": …}` for new ones and
  `PATCH /api/documents/<id>/` with `title`, `correspondent`, `document_type`, `tags`.

Redirects are not followed (the header line goes only to the configured address). A refused login (401/403) is a
`QuelleFehler`: "Paperless … refuses the login (check the token: FYOS_DOKUMENTE_KOPF)", never "no documents". The
token appears in no message, no log and no result.

*Paperless version.* The interface of Paperless-ngx is stable; its documentation names no introduction version for the
parameters used. The core reads both forms of `created` (a date since API version 9, a timestamp before) and both hit
markings, and is checked **against stand-ins**, not against a running Paperless. Paperless-ngx 2.0 or newer is
assumed; if you run an older version, try `neueste()` and `suchen()` first.

*Creating a token.* Best for an account of its own in Paperless that may view documents and (for `zuordnen()`) change
them and create tags, correspondents and types. In the web interface: open the account at the top right, **My
Profile**, press the button for generating the **Auth token** and copy the token. On the server,
`python3 manage.py drf_create_token <username>` in the Paperless container also works. It is entered as a header line:
`FYOS_DOKUMENTE_KOPF=Authorization: Token <token>`. Behind a proxy that logs the user in itself (remote user), use
instead the header line that Paperless reads for that (`PAPERLESS_ENABLE_HTTP_REMOTE_USER`, the default is
`Remote-User: konto`); the Hub must then be reachable in such a way that only it can set this header.

**Environment** (read on every call):

| Variable | Effect |
|---|---|
| `FYOS_DOKUMENTE_URL` | address of the Paperless-ngx; when set, it takes precedence over any store |
| `FYOS_DOKUMENTE_KOPF` | one header line for the service, `Name: Value` (secret), usually `Authorization: Token …` |
| `FYOS_DOKUMENTE_LINK` | address of the same Paperless in the browser (may differ from the one above, for example a name instead of the network address); empty = no links |

Errors: `QuelleFehler` (service or plugin down, without access or not answering as agreed; inherits from
`vorgaenge.QuelleFehler`), `NichtEingerichtet` (a `QuelleFehler`, but not from `vorgaenge.NichtEingerichtet`) and
`ValueError` (input: a query under two characters, an invalid id, a change without content, a name too long or
rejected by Paperless).

### 2.17 Storing, reading and searching files

Files (notes, pictures, PDFs, spreadsheets) belong in one shared store in which the person, the apps and the agent see
the same things. The core provides it as the source `mcp_hub.dateien` and as the plugin `dateien` with the app
"Files". A plugin of your own that needs files (a report, an export, an attachment) stores them there instead of
looking for a folder of its own, and asks `dateien.quelle()`; as with appointments, mail and documents, the source
without setup returns **no empty folder**, it raises `NichtEingerichtet`.

The store is a **folder** (a volume in the container): `FYOS_DATEIEN` points to it; with Compose and Kubernetes it
lives on a volume of its own (`/data/dateien`). There is nothing special inside: the files are ordinary files and can
be backed up with any tool or opened by hand. Only the subfolder `.fyos` belongs to the source (earlier versions,
trash, unfinished writes) and stays invisible to paths.

```python
from mcp_hub import dateien

def bericht_ablegen(self, text: str) -> dict:
    try:
        verz = dateien.quelle()                                   # ask anew on every call, it is cheap
    except dateien.NichtEingerichtet:
        return {"zustand": "nicht eingerichtet"}                  # own hint; neither red nor empty
    plan = verz.schreiben("Berichte/oktober.md", text.encode(), trocken=True)   # first show what would happen
    r = verz.schreiben("Berichte/oktober.md", text.encode(), ueberschreiben=True)
    return {"zustand": "ok", **r}                                 # {pfad, groesse, neu, ersetzt, version_gesichert}

verz.liste("Berichte")        # {pfad, eltern, auswahl, eintraege[{name, pfad, art, groesse, geaendert, typ}], gesamt, gekuerzt}
verz.lesen("Berichte/oktober.md")        # text (art "text") or only metadata (art "binaer"); version= reads an earlier version
verz.suchen("strom rechnung")            # name, for text also the content; all words must occur
verz.loeschen("Berichte/oktober.md")     # moves to the trash, never deletes at once
```

**Paths.** A path is relative to the store, separated by `/`, at most 400 characters, each name at most 200. `..`,
control characters, backslashes and `.fyos` at the start are rejected (`.` and double slashes simply drop out); an
absolute path counts from the root of the store, never from the root of the machine. A **link** (symlink) is not
followed anywhere in the path, not even inwards: whatever does not explicitly live in the store cannot be reached
through it. Writing is atomic (first into a temporary folder inside the store, then renamed); free space is checked
first.

**Size, versions, trash.** A file may be at most `FYOS_DATEIEN_MAX_MB` large (default 25). Whoever replaces a file
(`ueberschreiben=True`) keeps the old version: per file the last `FYOS_DATEIEN_VERSIONEN` (default 10). Deleting moves
to the trash, which keeps things for `FYOS_DATEIEN_PAPIERKORB_TAGE` days (default 30); `wiederherstellen()` and
`version_zurueck()` bring things back, and none of this silently overwrites anything. The source cleans up the rest on
the side when deleting, without a schedule of its own.

**The tools** `dateien.liste`, `.lesen`, `.suchen`, `.papierkorb`, `.versionen` (reading) and `.schreiben`,
`.verschieben`, `.ordner_anlegen`, `.wiederherstellen`, `.version_zurueck`, `.loeschen` (writing, `loeschen` as
`destructive`) follow the contract from §2.8 and §3.6: `__dry_run__` shows the plan, a real run requires
`bestaetigt: true`. The content of a file is **foreign content**; `lesen` and `suchen` say so in the result (`hinweis`),
and a plugin that shows it to a model does the same. Binary content never comes as text but as metadata with a
download address (`url`); uploading and downloading go through `GET`/`PUT /hub/dateien/datei` (`HUB-CONTRACT.md`), not
through tool answers.

**Open with.** For a file, the app can offer programs on a machine on which windows appear (PDF in Papers, documents in
WordCraft, spreadsheets in GridCraft). For this the plugin talks to a small service there (the counterpart,
`mcp_hub/oeffnen.py`): `GET /programme` names programs and file extensions, `POST /oeffnen {pfad, programm}` loads the
file from the store and starts the program. The Hub sends only the path and the program id; the store's address and the
commands live only in the service. The tools `dateien.oeffnen_programme` (reading, programs by extension, cached for a
minute) and `dateien.oeffnen_mit` (`exec`, plan and `bestaetigt: true`) first check that the file lives in the store.
It is set up with `config: {oeffnen: {gegenstelle: "http://rechner:18445", token_env: FYOS_OEFFNEN_TOKEN}}` (or
`FYOS_OEFFNEN_GEGENSTELLE`); the bearer token comes from the environment and never appears in the configuration, in
answers or in the log; redirects are not followed. Without a counterpart both tools answer "not set up" and the app
shows no buttons.

**Environment** (read on every call):

| Variable | Effect |
|---|---|
| `FYOS_OEFFNEN_GEGENSTELLE`, `FYOS_OEFFNEN_TOKEN` | address of the counterpart for "Open with" (also as `config: {oeffnen: {gegenstelle: …}}`) and its bearer token (name changeable with `oeffnen.token_env`) |
| `FYOS_DATEIEN` | folder of the store; without it the plugin is "not set up". Also as `config: {verzeichnis: …}` in the plugin's entry |
| `FYOS_DATEIEN_MAX_MB` | largest file in MB (default 25) |
| `FYOS_DATEIEN_VERSIONEN` | this many earlier versions per file (default 10; 0 = none) |
| `FYOS_DATEIEN_PAPIERKORB_TAGE` | how long deleted files stay in the trash (default 30) |

Errors: `QuelleFehler` (the folder is not readable or writable, little space), `NichtEingerichtet` (a
`QuelleFehler`), and as `ValueError` the input errors: `Fehler` (invalid path, not a folder), `NichtGefunden` (404),
`Existiert` (409, avoidable with `ueberschreiben=True`) and `ZuGross` (413). Each carries `status` and `kind` for the
REST route.

**The app.** "Files" shows folders and a preview (text, Markdown, pictures; PDFs open in a browser tab), accepts files
dragged from the desktop and creates, renames, deletes and restores earlier versions only after asking
(`App.beantragen`). Because an app in the sandbox iframe may not send anything writing to the Hub, the shell accepts
uploaded files itself (`App.hochladen(pfad, datei, {ueberschreiben})`, only in this app and only in the FYOS shell).
Every file in the app carries `data-typ="datei"` and `data-id="<path>"`, so that the shell can recognise it as a thing.

### 2.18 Search across everything (⌘K)

The shell's start field (⌘K) searches surfaces and, with the tool `suche.alles`, everything a source registers. The
core ships four sources: tickets, mail (`postfach`, read-only), files and the notes of the notepad. A plugin that makes
more searchable (a wiki, contacts, a knowledge store) registers another one (`mcp_hub/suche_alles.py`):

```python
from mcp_hub import suche_alles

def finden(abfrage: str, anzahl: int) -> list[dict]:
    return [{"id": "seite-7", "titel": "Rhabarberkuchen", "auszug": "…Teig, dann…"}]   # auszug may be missing

def register(self):   # in HubPlugin.register()
    suche_alles.registriere_quelle("wiki", "Wiki", finden, typ="seite")   # typ: a thing type (§3.7) or None

def shutdown(self):
    suche_alles.entferne_quelle("wiki", finden)
```

- The source receives the query (at least two characters) and the maximum count and returns `{id, titel, auszug}`. If
  it has a `typ` the shell knows as a thing, a click opens the app that shows it, and the hit can be dragged onto
  windows and the agent. Without `typ` the hit is only displayed.
- The search mixes in turn (at most 8 per source) and reports `zustand` per source: `ok`, `nicht eingerichtet` or
  `fehler`. If a source raises `NichtEingerichtet` or `QuelleFehler`, the search continues with the others, and the
  shell says what was not searched. On any other exception the source stays silent; the log records only the type of
  the error.
- Hits are **foreign content**; the result carries `hinweis` for that. The tool is reading (tags `suche`, `flaeche`,
  `read`).
- The shell asks only once the input has rested briefly, and discards outdated answers.

### 2.19 Controlling a machine's desktop (`desktop`)

The plugin `desktop` turns the Hyprland desktop on a machine into tools (the service `fyos-oeffnen`, port 18445; the
same counterpart as "Open with", §2.17). Routes of the service, all with `Authorization: Bearer`:

| Route | Effect |
|---|---|
| `GET /lage`, `/fenster`, `/starter`, `/bild?skala=0.1…1` | read: workspace, screen, mode (`mac`/`gross`), open windows, allowed launchers, PNG in base 64 |
| `POST /starten {starter}` | start exactly one entry from `starter` in the service configuration |
| `POST /fokus {adresse}`, `POST /schliessen {adresse}` | bring a window to the front or ask it to close (only addresses of open windows, `0x…`) |

Tools: `desktop.lage`, `fenster`, `starter`, `bild` (reading); `starten` (`exec`), `fokus` (`write`), `schliessen`
(`destructive`), all with a plan (`__dry_run__`) and `bestaetigt: true`. The Hub never sends a command, only the id of
a launcher or a window address; commands live only in the service's configuration. Window titles and pictures are
foreign content and can show private things. It is set up with `config: {gegenstelle: "http://rechner:18445",
token_env: FYOS_OEFFNEN_TOKEN}` (or the environment variables from §2.17); without them every tool reports "not set
up".

**App "Desktop".** `desktop.zeigen` (situation, windows, launchers in one call) opens the surface `ui/desktop.html`; it
refreshes every ten seconds while it is visible and shows the screenshot only at the press of a button. An open window
is a thing of the type `desktop-fenster` (id = window address, `lesen` = `desktop.fenster_lesen`, fields `klasse` and
`titel`). The type is not called `fenster`, because the shell already uses that name for dragging an app window. There
is no handover for the type yet: dragged onto another app, the shell offers to ask the agent. The surface requests
bringing to the front, closing and starting through `App.beantragen` (plan, then "Yes"); it never triggers anything
directly.

**Input (computer use).** `desktop.klick`, `tippen`, `taste` and `scrollen` act on the window with the focus; click
points are measured in a screenshot of the same `skala`. The service carries them out on the person's desktop only
while an approval is in force there that only the person at the machine can set (ten minutes, shown in the bar);
otherwise the tool answers "locked" (HTTP 423 from the service). No tool grants it. Keys: only `ctrl` and `shift` as
modifiers. The service rejects typing and keys with 409 while a menu holds the keyboard or someone has moved the mouse.

**Target.** Every tool takes `ziel`: `mensch` (default) is the person's desktop, `agent` the agent's own headless
desktop (a second compositor under a user of its own, input only through Wayland protocols, never through uinput). No
approval applies there; the person watches (app "Desktop", toggle "Agent's desktop", a picture every few seconds) and
can take over with `desktop.uebernehmen {an: true}`: the agent rests, and each of its inputs gets "locked" until it is
handed back with `{an: false}` (real run with plan and `bestaetigt`). Window addresses there are called `g5`; whoever
names only the address hits the right target. The service keeps a log (`ziel`, action, never the typed text).

---

## 3. Interface (MCP app, `ui://`)

An interface is an HTML file that a tool "brings along". The shell shows it as a window (iframe), and every MCP client
that supports MCP apps shows it in the conversation. You write only the HTML file and a few lines in the plugin;
window, dock entry, tile, search and deep link come by themselves.

### 3.1 Connecting resource and tool

```python
from mcp_hub.plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from mcp_hub.plugins import _identitaet
from mcp_hub.plugins._identitaet import identitaet
from mcp_hub.plugins._oberflaeche import oberflaeche

UI_URI = "ui://wetter/wetter.html"
UI_DATEI = "wetter.html"

# title, subtitle, symbol (Lucide name from mcp_hub/plugins/ui/_symbole.json), colour tone 0–359, category.
# For a German title with an English header add "titel_en" and "untertitel_en": the bridge shows them when the app
# runs in English (App.sprache), the German ones otherwise.
_identitaet.registriere_app(
    "wetter",
    {"titel": "Weather", "untertitel": "Forecast for today", "symbol": "sun", "ton": 200, "kategorie": "Wissen"},
    datei=UI_DATEI,
    hauptwerkzeug="wetter__vorhersage",       # the tool that opens the app
    art="widget",                             # "widget" (default) or "anwendung", see 3.5
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
                name="Weather",
                description="Forecast for today",
                read=lambda: oberflaeche(UI_DATEI, __package__),     # reads <package>/ui/wetter.html
                meta={"ui": {"prefersBorder": True}},
            )
        ]
```

- `meta["ui"]["resourceUri"]` turns the tool into an app. Several tools with the **same** `resourceUri` are *one*
  surface in the shell (one window, one dock entry).
- `oberflaeche(datei, ui_verzeichnis)` reads the file from `<package>/ui/` (second argument: the package name as text;
  `__package__` survives a rename) or from a `Path`. It fills in style, bridge, header and symbols (3.3).
- `registriere_app` must run at import time (module level in `plugin.py`). The categories `System`, `Betrieb`,
  `Wissen`, `Beispiele` exist; a new category is created along the way.
- The main tool name is the basis of the deep link when the host provides nothing else.

### 3.2 Visibility

```python
meta = {"ui": {"resourceUri": UI_URI, "visibility": ["app"]}, "app": identitaet("wetter")}
```

- without `visibility` or `["model","app"]`: model **and** interface see the tool;
- `["app"]`: only the interface. `/hub/call` and `/mcp` reject it with 403 `nur_oberflaeche` (good for "delete"
  buttons the agent should not press on its own);
- `["model"]`: only the model.

The shell calls tools only through `/hub/app-call`, and that accepts only tools with `meta.ui` or the tag `flaeche`.

### 3.3 The HTML file

An interface is normal HTML with three markers that the Hub replaces on delivery:

| Marker | is replaced by |
|---|---|
| `<style>/*STIL*/ … </style>` | the shared look (`_stil.css`); your own CSS for the layout follows after it |
| `<script>/*BRUECKE*/ … </script>` | the bridge to the host (`App`), followed by your script |
| `<!--KOPF-->…<!--/KOPF-->` | the app's header (tile, title, sentence) from the identity; your action buttons go in between |
| `<svg class="ico" data-symbol="plus"></svg>` | the symbol (Lucide name) with its lines |

Skeleton (shortened from `fyos-plugin-vorlage/fyos_plugin_vorlage/ui/vorlage.html`):

```html
<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weather</title>
<style>/*STIL*/
  .tafel { padding: 14px 16px; margin: 0 0 14px; }
</style>
</head>
<body>
<!--KOPF-->
  <button id="neu" class="rund drehen" title="Refresh" aria-label="Refresh"><svg class="ico" data-symbol="refresh-cw"></svg></button>
<!--/KOPF-->
<main>
  <div id="inhalt"><div class="laedt">Loading …</div></div>
</main>
<script>
/*BRUECKE*/
const $ = (id) => document.getElementById(id);
const { esc, zustand, satz } = App;
const rufen = (name, args) => App.rufen("wetter__" + name, args);     // <plugin>__<tool>

async function laden() {
  try {
    const d = await rufen("vorhersage");
    satz(d.satz, "gut");                                               // line in the header; tone: "gut" | "schlecht" | ""
    $("inhalt").innerHTML = `<div class="karte tafel">${esc(d.satz)}</div>`;
  } catch (e) {
    $("inhalt").innerHTML = '<div class="karte">' + zustand({ symbol: "circle-alert", ton: "schlecht", titel: "Error", text: App.fehlertext(e), klein: true }) + "</div>";
  }
}

$("neu").addEventListener("click", laden);
// If the host opens the app with a tool result (shell, chat), it arrives here:
App.auf("ui/notifications/tool-result", (r) => { const d = App.daten(r); if (d && d.satz) { /* show */ } });
App.start("fyos-wetter").then(() => setTimeout(laden, 1500)).catch(() => {});
</script>
</body>
</html>
```

The most important building blocks of the bridge `App` (full list at the top of `hub/mcp_hub/plugins/ui/_bruecke.js`):

| Area | Building blocks |
|---|---|
| Calling | `App.rufen(name, args)` → data (raises on errors), `App.werkzeug(name, args)` → raw result, `App.daten(ergebnis)`, `App.fehlertext(e)` |
| Start and events | `App.start(name)`, `App.auf(methode, fn)`, `App.bei(aktion, fn)` (click on `data-aktion="…"`), `App.takt(ms, fn)` (regularly, only while visible) |
| Building blocks | `App.esc`, `App.symbol(name)`, `App.kachel`, `App.marke`, `App.zustand({…})`, `App.satz(text, ton)`, `App.knoepfe`, `App.bestaetigung`, `App.aufklapper` |
| Time and number | `App.zeit.vor(ms)`, `.uhr`, `.tag`, `.datum`, `.dauer`, `.voll`, `.stempel`; `App.zahl(x, stellen)` |
| Freshness and request | `App.frische(t, {schwelleMin, text, klasse})`, `App.veraltet(t, schwelleMin)`, `App.beantragen({werkzeug, args, ort, ja, nein, symbol, klasse})`, `App.plan(trockenlauf)` (§3.6) |
| Host | `App.host` (`"fyos"` in the shell), `App.link(url)`, `App.nachricht(text)` (only after a click), `App.modellKontext({text, daten})` |

Rules that the Hub test checks for all interfaces:

- **No colour scheme of your own.** Use the variables and classes of the shared style (`var(--mut)`, `var(--fg)`,
  `.karte`, `.haupt`, `.leise`, `.gefahr`, `.rund`, `.laedt`); then the app matches the shell in light and dark.
- **No modal dialogs** (`alert`, `confirm`, `prompt`): the iframe runs without `allow-modals`. Confirm with
  `App.bestaetigung(…)`.
- **Forms only with your own handler.** The iframe allows `allow-forms` so that the `submit` event of a `<form>` fires
  (input and Enter); the handler ends with `e.preventDefault()`. There is no real submission: the shell's content rules
  set `form-action 'none'`.
- **Escape everything you insert with `esc()`.** Tool results are foreign text.
- **Symbols**: only names from `mcp_hub/plugins/ui/_symbole.json` (Lucide). A word in quotes in the script that is a
  symbol name (`"trash-2"`) is shipped automatically. An unknown name becomes a window symbol, not an error.
- In the interface, call **only tools of your own plugin** and only those with `meta.ui` or `flaeche`.

No test checks two further habits, but every app of the distribution has them: a **freshness stamp** on every panel
with data and a **request instead of a direct action** on every button that writes something (§3.6).

### 3.4 Size levels

The shell tells the app the size of its frame. From it the bridge forms four levels you can query:

| Level | when | Idea |
|---|---|---|
| `blick` | height < 300 px, or width < 360 px at height < 420 px | only the essentials (tile on the home screen) |
| `kompakt` | height < 480 px or width < 420 px | tighter, smaller numbers |
| `normal` | otherwise | as built |
| `weit` | width ≥ 1100 px | content at a readable width (`<body class="breit">` uses everything) |

`App.stufe` returns the current level, the window event `app-stufe` reports changes,
`App.anzahl({ blick: 2, kompakt: 4, normal: 8, weit: 12 })` says how many entries fit. The shared style already
applies the levels to spacing and font sizes; you only have to adjust the length of lists. In a frame without a fixed
height (chat) the app sets its own height and stays at `normal`.

### 3.5 How the app appears in the shell

You register **nothing** in the shell. It queries `/hub-api/apps` (at startup, every two minutes, when you return to
the tab) and builds surface, dock entry, start tile and search hit from it.

- Title, subtitle, symbol, colour tone, category and **kind** come from `meta["app"]`.
- **Widget or application?** You state the kind in `registriere_app(…, art="widget" | "anwendung")`; without it the app
  is a widget (see below).
- The **group** in Start is "Apps" unless someone says otherwise. The shell chooses a group through
  `registriereFlaechen({ gruppen: { plugin: { wetter: 'Wissen' } } })` (§6).
- **Pinning** to the home screen works only for reading tools without required fields that are the only ones with
  their interface.
- **Deep link:** `https://<your-address>/os?offen=app:<plugin>__<tool>` opens the app,
  `&eingabe=<base64url(JSON of the arguments)>` starts it with arguments (at most 4000 characters of JSON; the shell
  accepts them only for reading tools). Reading app tools append the link as the last line "Open in FYOS: …" to their
  result; `FYOS_OEFFENTLICH_URL` determines the origin. Example: `/os?offen=app:vorlage__hallo`.
- An agent can show the same app in the open OS (OS bridge, command `zeigen` with target `app:<plugin>__<tool>`, see
  `HUB-CONTRACT.md` §3).

**Widget or application.** The shell knows two kinds of surfaces, and the app chooses what it is:

| | Widget (default) | Application |
|---|---|---|
| Idea | something to keep alongside: a status, a tile, a counter | something you work in: files, an editor, a mailbox |
| Opens | as a tile in the 12-column grid, many side by side | large: full width, as tall as the screen below the menu bar |
| Green button | "Zoom": full ↔ half width | **full-screen screen** |
| ⌥-click on the green button, double-click on the header | (double-click: zoom) | **maximise** |
| ⌃⌘F (Windows and Linux: Ctrl+Alt+F) | – | full-screen screen on and off |
| Examples in the distribution | Notepad, Workshop, MCP, Built view | Files |

- **Maximise** puts the application over the screen's whole work area: the dock hides, the menu bar stays, the other
  windows rest invisibly (their apps do not reload). If someone opens something else, the maximisation ends.
- The **full-screen screen** is a work screen of its own, like full screen on the Mac: directly behind the screen the
  application came from, with exactly this one application, maximised. Swiping and ⌥⌘←/→ switch to it and away from it
  as between all screens. For this the shell asks the browser for full screen (`requestFullscreen`; Esc ends it and the
  full-screen screen). You go back with the green button, ⌃⌘F or Esc: the application returns to its screen. If it was
  alone on its screen, that screen itself becomes the full-screen screen and afterwards an ordinary one again. New
  surfaces never open in a full-screen screen, always on another one.
- An app that looks like **work** (its own list and preview, needs a lot of space) is an application. An app you want
  to keep in view **next to others** is a widget. When in doubt: widget.
- The kind changes nothing in the app's interface; it only gets more or less space (size level `weit`, §3.4).
- It has no effect on the phone: there is always exactly one window there.
- Your own pages and native surfaces from `registriereFlaechen` set the same with `anwendung: true` on the surface
  (§6.1).

### 3.6 Freshness, and a request instead of an action

Two habits that every app of the distribution has. No test enforces them; the bridge gives you both ready-made, and the
sample app in `fyos-plugin-vorlage` shows how they fit together.

**Freshness: every panel says how old its data is.** A number without an age lies as soon as the source stalls. Every
panel that shows data therefore carries a stamp with the state *of the data* (what the source reports, not the moment
of fetching). From a threshold on it says "outdated", as text and in a warning colour, never only as a colour:

```js
const stempel = App.frische(d.zeit * 1000, { schwelleMin: 5 });      // d.zeit: Unix seconds from the tool result
$("gruss").innerHTML = `<div class="karte">…<div class="gruss-zeit">${stempel}</div></div>`;
// "As of 2 min ago"  →  after 5 minutes without new data: "As of 6 min ago · outdated"
```

- `App.frische(t, {schwelleMin, text, klasse})` returns a `<time class="frische">`. `t` is ISO text, milliseconds,
  Unix seconds or a `Date`. Without `schwelleMin`, 15 minutes apply; `text` replaces "As of" ("Measured"). Without a
  point in time it says "As of unknown · outdated". The full time is in the `title`; the display moves on by itself
  every 30 s and switches to "outdated" on its own.
- `App.veraltet(t, schwelleMin)` returns `true` or `false`, if the app itself wants to act on it.
- The tool delivers the point in time of the data (`zeit`, `gemessen_am` …). If the source names none, it is the moment
  of fetching in the plugin, not the one in the browser.
- If a reload fails, the old data stays with its **old** stamp, and the sentence in the header says that reloading did
  not work. Do not empty it, do not set the stamp to "now".

**A request instead of an action: a button never directly triggers anything that writes.** Three levels, depending on
the weight of the effect:

| Level | What the button does | Examples |
|---|---|---|
| 1 Reading | calls the tool directly, also as a dry run (`__dry_run__`) | Refresh, filter, "check only" |
| 2 Small, reversible | makes a **request**: dry run, show the plan, the real run only after "Yes" | Save a note, rename an entry |
| 3 Heavy | triggers nothing but **asks**; the agent or the person decides on the approval route | Money, deleting, messages to the outside, starting processes |

Level 2 is built into the bridge. The app calls `App.beantragen`, and the bridge does the rest:

```js
// in the HTML a place for the question:  <div id="antrag"></div>
$("formular").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const r = await App.beantragen({ werkzeug: "vorlage__notiz_setzen", args: { text: $("text").value.trim() }, ort: $("antrag"), ja: "Save" });
    if (r) { $("text").value = ""; await laden(); }       // null: cancelled or replaced by a new request
  } catch (e) { satz(App.fehlertext(e), "schlecht"); }
});
```

1. The bridge calls the tool with `__dry_run__: true`. It changes nothing and returns the plan (`would_execute`,
   `expected_side_effects`, §2.8).
2. The question appears in `ort`: the plan as a sentence, the effects below it (`App.plan(…)` builds the text), plus
   "Yes" (label from `ja`, default "Run"; `symbol` and `klasse` apply to this button, `"gefahr"` for deleting) and
   "Cancel" (label from `nein`).
3. Only after "Yes" does it really call the tool, with `bestaetigt: true` and without `__dry_run__`. The promise
   resolves to the result of the real run, to `null` on "Cancel". Errors come as readable text (`App.fehlertext`).
4. There is only one open request: a new one replaces the open one (whose promise resolves to `null`); while an
   execution is running, the bridge rejects a new one.
5. If the tool delivers no plan (it reports `dry_run_unsupported` or ignores the signal), `beantragen` raises and the
   interface does not ask at all: a person cannot confirm what they have not seen. A tool that ignores the signal and
   writes right away breaks the contract from §2.8; no bridge catches that.

The tool holds the other side: it changes something only with `bestaetigt: true` and otherwise rejects with
`ValueError` (the pattern of `werkstatt.ausfuehren`):

```python
input_schema = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "minLength": 1, "description": "The note"},
        "bestaetigt": {"type": "boolean", "description": "Real run: first show the plan (`__dry_run__`) and have it confirmed"},
    },
    "required": ["text"],
    "additionalProperties": False,
}

def notiz_setzen(self, text, trocken=False, bestaetigt=False):
    ...                                    # check input as before
    if trocken:
        return build_dry_run_result(...)   # the plan, without changing anything
    if not bestaetigt:
        raise ValueError("Nothing changed: a real run needs bestaetigt: true — first look at the plan with __dry_run__ and have it confirmed.")
    ...                                    # really write
```

In `call` the value arrives as `args.get("bestaetigt") is True`. This protects against accidents; it is not a
permission: whoever may call tools directly can set `bestaetigt: true` themselves; §2.7 still draws the line. The gain:
the interface never writes "on the side", and scripts (`begleiter/`) have to give the confirmation explicitly.

The app does not trigger level 3. It writes the request into the conversation (`App.nachricht("Please delete …")`,
only after a click and only if `App.kann("message")`), or a tool of the plugin creates a **ticket** that waits for
approval (status `waiting_approval`, ticket contract in §2.13). The person decides on the agent's approval route (chat
or ticket), never the interface. The template does not reproduce level 3, because it requires a ticket service.

**Opening addresses and uploading files.** The app in the sandbox iframe has the origin `null` and can neither navigate
by itself nor write to the Hub. It opens an address with `await App.oeffnen(url)` (link request to the host; raises if
the host refuses; only `http(s)`). The shell accepts files for the app "Files": `await App.hochladen(pfad, datei,
{ueberschreiben})` sends a `File` or `Blob` by message to the host, which uploads it from its own origin
(`fyos/datei-hochladen`, capability `App.kann("fyosDateien")`, only there and only in the FYOS shell). The result is
`{ok: true, result}` or `{ok: false, kind, error}` (`existiert`, `zu_gross` …); it raises only when the host fails.

### 3.7 Handovers: dragging things between apps

You drag a **thing** (a note, a file, a ticket) from one app's window onto another app's window, onto the dock or onto
the agent. What happens at the target the plugin states beforehand, in three steps. Nothing is ever dropped without a
plan and "Yes" (§3.6).

**1. Register the type** (in the plugin, after `registriere_app`; see `mcp_hub/plugins/_dinge.py`):

```python
from mcp_hub.plugins._dinge import registriere_ding, registriere_uebergabe

registriere_ding(
    "notiz", "Notiz",                    # type (lower case, digits, "-") and a name for people
    flaeche="vorlage",                   # the app that shows it (key as in registriere_app)
    lesen="vorlage.lesen",               # reading tool with tag `flaeche`: id in, the thing out
    id_argument="id",                    # name of its id argument
    felder=("text", "dateiname"),        # fields of the result that handovers may fill in
)
```

The shell receives the register with `GET /hub/apps` (fields `dinge` and `uebergaben`). Types whose app or reading
tool does not exist (any more) are left out by the Hub, with a warning in the log. Without `lesen` the thing can be
dragged but passed on only with `{id}` and `{label}`. The tool of a handover must belong to the target app's plugin and
be a surface tool (tag `flaeche`, reachable on the route `/hub/app-call`); a handover that fills in a placeholder the
type does not deliver is dropped as well.

**2. Register a handover** when thing and target fit together:

```python
registriere_uebergabe(
    "notiz",                             # source type
    "dateien",                           # the target app
    "dateien.schreiben",                 # surface tool of the target plugin, ideally with dry run and `bestaetigt` (§3.6)
    {"pfad": "Notizen/{dateiname}.md", "inhalt": "{text}\n"},   # argument -> value; text may carry {id}, {label} and {field}
    "Save as a Markdown file in \"Files\"",                    # the sentence on the window before you let go
)
```

`abbildung` knows no loops and no computation: whatever a field has to compute (a safe file name, a title) the type's
reading tool computes. At most 12 arguments, 2000 characters each; `wirkung` at most 120. One handover applies per pair
(source type, target app); registering it again overwrites it. At import time the type does not have to exist yet
(plugins load in any order); it is checked when `/hub/apps` is delivered. The distribution ships two pairs: a note on
"Files" creates a `.md` file, a file on the notepad remembers a reference.

**3. In the interface** (`ui/<name>.html`): source and target are two lines.

```js
// Source: every element with data-typ and data-id is draggable (data-label is the name in the hint)
App.ziehbar(document.body, { selektor: "[data-typ]" });
// Target: accepts things of the named types; puts plan and question into #antrag and calls danach(…) after "Yes"
App.ablage($("antrag"), { nimmt: ["notiz"], ja: "Create file", danach: (r) => laden(), fehler: (e) => satz(App.fehlertext(e), "schlecht") });
```

- `App.ziehbar(wurzel, {typ, id, label, selektor})` sets `draggable` on elements under `wurzel` (with `selektor` by
  delegation) and fills the drag in the shell's drag language: `fyos://<typ>/<id>` as `text/plain`, plus
  `application/x-fyos-<typ>` and `text/x-fyos-label`. `typ`, `id` and `label` may be functions of the element. It
  returns a function for unregistering.
- `App.ablage(ort, {nimmt, ja, danach, fehler, bei})` listens for `fyos/uebergabe`. The default is `App.beantragen`
  with the completely filled-in tool; `bei(u)` replaces that if the app wants to do something else with the handover.
- The target tool must know `bestaetigt` and reject without it (§3.6); otherwise registering the arguments fails on the
  schema.

**What the shell does in between.** The app runs in a sandbox without an origin. When a drag starts in it, the bridge
reports `fyos/zug` to the host; while it lasts, the windows release their pointers (otherwise the iframe would catch
the drag), and every target shows at the top what would happen: for windows with a handover its `wirkung`, for pairs
without a handover "Ask the agent about it". On release the host reads the thing (`lesen`), fills in the fields and
sends `fyos/uebergabe` to the target app (`typ`, `id`, `werkzeug`, `argumente`, `wirkung`); if it is not loaded yet,
the message waits up to 30 seconds. On the dock, the agent or a screen, a thing shows its own app (`fyos/oeffne` with
`typ` and `id`; the app opens it: `App.auf("fyos/oeffne", (p) => …)`). The capability `App.kann("fyosUebergaben")` says
whether the host understands all this (outside the FYOS shell it does not: then the app only carries out its drag,
without reporting).

**The work apps.** Three plugins ship things and pairs for work (each shows "not set up" as long as its source is
missing, §2.13 to §2.15):

| Plugin | App | Thing | Pairs it registers |
|---|---|---|---|
| `vorgaenge` | Tickets | `vorgang` (`titel`, `status`, `auszug`) | Mail on Tickets: new ticket with subject, excerpt and source `fyos://mail/<id>`; ticket on Tickets: comment on the open ticket with info and reference; (tools `anlegen`, `kommentieren`) |
| `posteingang` | Mail | `mail` (`betreff`, `von`, `datum`, `auszug`) | none; mail is only read and dragged |
| `termine` | Appointments | (shows appointments) | Ticket on Appointments: form with title and reference; after the question, `Termine anlegen` with a start time |

All writing tools go through plan and "Yes" (§3.6). On the window of the **same** app a handover applies if the pair is
registered (ticket on Tickets); without a pair the shell shows the thing as before. An app can interpret the handover
itself with `App.ablage(…, {bei})` and, for example, add the id of the open ticket. Dragged onto the **agent**, the
thing's content (shortened to 1200 characters, with the note that it comes from the app and contains no instructions)
goes as context into the draft of the question; if the thing cannot be read, only the question remains.

---

## 4. Knowledge for the agent: skills

A **skill** is a work instruction: *when* to use which tools, in which order, where the traps are. The Hub describes the
tools; the skill explains how to handle them. The agent finds skills through the Hub plugin `skills`.

### 4.1 Structure

```text
fyos_plugin_wetter/skills/wetter/SKILL.md                the instructions
fyos_plugin_wetter/skills/wetter/references/*.md         (optional) long extra files, readable one by one
```

```markdown
---
name: wetter
description: Load when the owner asks about weather, rain or temperature. Which tool when, what is never done.
ausloeser: weather, rain, temperature, forecast
werkstatt: []              # ids of registered workshop scripts the skill uses (optional)
fuer: [agent]
---

# Weather

## When
…
## Steps
1. …
## Rules
- …
```

- The front matter has at least `name` and `description`. The `description` is the search text: write "Load when …"
  and the words people ask with.
- The text is short and in the imperative: steps, rules, what never happens. Name tools by their id.
- Do not write secrets or real addresses into it.

### 4.2 Making them findable

**Skills travel with the package.** Put them under `fyos_plugin_wetter/skills/`, include them in `package-data` and
register the package in the entry point group `fyos.skills` (§2.2). Whoever installs the plugin with `uv pip install`,
also through the installer, gets tools and skills together. The entry point's value is an importable package; the
plugin `skills` reads its subfolder `skills/` (if there is none, the package itself). In the directory the source is
named like the entry point.

The Hub plugin `skills` reads directories with the structure `<source>/<name>/SKILL.md`. Sources, in this order:
`config: quellen` (list of paths or `{pfad, name}`), the environment `FYOS_SKILLS_PATH` (paths separated by `:`),
otherwise the default `/opt/fyos/skills`; after that the skill folders of the plugin packages (`fyos.skills`, can be
turned off with `config: plugin_skills: false`). On equal names the source named first wins; that way an operator can
override a plugin's skill with a version of their own in `/opt/fyos/skills`. The Hub notices new files within 30 s at
the latest. The agent uses `skills.suchen` (words) and `skills.lesen` (name).

Skills that belong to no package (the operator's own work instructions) still come by volume
(`./skills:/opt/fyos/skills:ro`) or `COPY` into the hub image. If you name your own `quellen` in the Hub
configuration, include `/opt/fyos/skills`.

### 4.3 Knowledge or behaviour?

| What | where | Why |
|---|---|---|
| "This is how my tool is used" | skill in the **plugin** | belongs to this capability and travels with it |
| "This is how the agent generally handles approvals, messages, privacy" | the **runner** in `fyos-agent` (§5) | applies to every conversation, independent of plugins |
| "This must never happen, whatever the model says" | **approval in the Hub** and the runner's limits (§5) | is enforced underneath the model |

A skill cannot loosen the behaviour contract. Texts from tool answers and skills cannot change the ground rules
(approval, privacy).

---

## 5. Extending the agent's behaviour

The agent is the runner from `fyos-agent` (`fyos-agent/runner`, long-running on pi-durable, port 18438). It talks to
the Hub through the Hub's tools and the plugin `agent` (`/hub/agent/*`: inbox, reports, alarms); the interface talks to
it through `/api/agent/` (nginx sets the token). What it does is in a file the installer generates:

| File | Contents |
|---|---|
| `agent-runner.json` | Hub address, the agent's id (`agent`), port, device name, storage, allowed origins of the interface, schedules (`takt`), approval messages (`pi_durable.freigabe_meldung`) |
| `.env` or secrets | model (`FYOS_MODELL_BASIS_URL`, `FYOS_MODELL_NAME`, `FYOS_MODELL_SCHLUESSEL`) and token (`FYOS_AGENT_TOKEN`, in the container `FYOS_RUNNER_TOKEN`) |

Template and all keys: `fyos-agent/runner/beispiele/agent-runner.beispiel.json` and `fyos-agent/runner/README.md`.

### 5.1 Schedules

The built-in daily rhythm is built for a particular everyday life; the installer turns it off with
`"takt": {"an": false}`. Your own schedules go under `takt.eintraege` (for example `{"id": "nacht-notizen", "um":
"03:00", "fenster_min": 120, "text": "…"}`); an example with a report in the morning is in `NIGHT-WORK.md`.

### 5.2 Message routes

The runner reports open approvals itself, over the channels in `pi_durable.freigabe_meldung.kanaele` (for example
`matrix`). The distribution no longer ships a chat channel of its own; there is no Telegram and no WhatsApp. Without a
configured channel, approvals appear only in the shell.

---

## 6. Extending the shell

The shell (`web/`, Astro and SolidJS) contains no content of its own. Hub apps appear by themselves (§3); for everything
else there is `registriereFlaechen` and the runtime configuration.

### 6.1 `registriereFlaechen`

`web/src/lib/os/register.ts` is the one interface through which plugins bring surfaces, symbols, groups and templates
into the shell. Every file `web/src/plugins/*.ts` (except `index.ts`) is executed when the shell loads:

```ts
// web/src/plugins/wetter.ts
import { registriereFlaechen } from '~/lib/os/register';

registriereFlaechen({
  flaechen: [
    // a page of the same origin, runs in a window
    { id: 'seite:radar', titel: 'Rain radar', gruppe: 'Wissen', art: 'seite', kuerzel: 'Ra', pfad: '/radar/' },
    // a foreign service, opens in a new tab
    { id: 'extern:amt', titel: 'Weather office', gruppe: 'Extern', art: 'seite', kuerzel: 'Wa', extern: 'https://wetter.example.org/' },
  ],
  symbole: { 'seite:radar': ['cloud', 210] },                         // Lucide name from lib/os/symbole-daten.ts, colour tone
  gruppen: { reihenfolge: ['Wissen'], plugin: { wetter: 'Wissen' }, app: {} },   // hub app wetter__* into the group "Wissen"
  standardPlaetze: [{ name: 'Morning', ids: ['seite:radar', 'app:wetter__vorhersage'] }],
  alias: { 'seite:regen': 'seite:radar' },                            // old ids lead to today's surface
  quelle: 'wetter',                                                   // a new registration from the same source replaces the old one
});
```

| Field | Meaning |
|---|---|
| `flaechen` | `art: 'seite'` with `pfad` (window, same origin) or with `extern` (new tab); `art: 'nativ'` with `laden` (Solid component in the window, `NativProps`: `oeffne`, `schmal`). With `anwendung: true` the surface opens large, can be maximised and gets a full-screen screen (§3.5); without it, it is a widget |
| `symbole` | glyph and colour tone per surface; hub apps bring their own face |
| `gruppen` | order of the groups and assignment of hub apps: first the full tool name (`app`), then the plugin prefix before `__` (`plugin`), otherwise "Apps" |
| `standardPlaetze` | templates for work screens that Start offers; missing surfaces are skipped |
| `alias` | old ids → today's surface (bookmarks, saved layouts, `?offen=`) |
| `dinge` | draggable things (`fyos://<typ>/<id>`) and the page they live on; for things of hub apps also `flaeche`, `lesen`, `idArgument`, `felder` (comes from `registriere_ding`, §3.7, and is delivered by the Hub) |
| `uebergaben` | what happens when a thing is dropped on an app's window (`quelle`, `ziel`, `werkzeug`, `abbildung`, `wirkung`); Hub plugins register them with `registriere_uebergabe` (§3.7) |

Surface ids: `seite:<name>`, `app:<plugin>__<tool>`, `nativ:<name>`, `extern:<slug>`, `agent`.

**How does the file get into the shell?** The files from `web/src/plugins/` are read at **build** time
(`import.meta.glob`). A plugin repo of your own therefore puts a file `shell/wetter.ts` in place and builds a web image
of its own that copies it to `src/plugins/` before the build. Recipe with BuildKit contexts (context `web` = the folder
`fyos-os/web`):

```dockerfile
# Dockerfile.web, call:  docker build --build-context web=../fyos-os/web -f Dockerfile.web -t mein-web:main .
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

(The recipe follows `web/Dockerfile`; keep it in sync when that one changes. It is not checked automatically in the
distribution.) Then enter the image in the Compose file as `FYOS_BILD_WEB` or in the Kustomize overlay (`images`,
`name: registry.example.com/fyos/fyos-os/web`; why the full name is needed is explained in
`deploy/k8s/base/kustomization.yaml`). Check first with `npx tsc --noEmit -p .` and `npx vitest run` in the folder
`web/`.

> **(in progress)** Delivering shell files *without* a web image of your own (for example a mounted folder that the
> shell loads at runtime) does not exist yet. Hub apps do not need it; only pages, external surfaces and native
> surfaces from plugins need the build.

### 6.2 Runtime configuration `fyos.config.json`

At startup the shell loads `/fyos.config.json` (nginx serves the file from `/etc/fyos/fyos.config.json`). If it is
missing, the defaults apply. This is the place for things that belong to an installation and are not code:

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

- `name`: name in the menu and the page title (overrides `PUBLIC_FYOS_NAME`).
- `oeffentlicheUrl`: an additional origin whose links open in the OS (behind a proxy).
- `agent.name` and `agent.pfad` (starts with `/`).
- `extern`: services with an interface of their own; they open in a new tab. `slug` (letters, digits, `_`, `-`),
  `titel`, `url` (only `http` and `https`). They appear as surfaces `extern:<slug>` in the group "Extern". This is the
  route for "I want my Git in the dock" without code.

Mounting: in Compose `volumes: ["./fyos.config.json:/etc/fyos/fyos.config.json:ro"]` on the service `web`, in
Kubernetes a ConfigMap at the same place. The image ships an empty default file `{}`.

---

## 7. Installer catalog

The installer (`fyos-install`) shows building blocks with a picture and an explanation "What it turns into" and
generates Compose or Kubernetes files from them. Your plugin becomes a building block by shipping a catalog entry.

> **Status:** in this version the installer is still being built (web assistant, text interface, target kinds). The
> catalog format below is the one from `installer/fyos_installer/katalog.py` and is covered by tests; details of the
> interfaces may still change.

### 7.1 The file `fyos-katalog.yaml`

It lives **in the Python package** (`fyos_plugin_wetter/fyos-katalog.yaml`), pictures next to it in the folder
`bilder/`:

```yaml
version: 1
bausteine:
  - id: wetter                      # a-z, 0-9, _ ; starts with a letter; unique
    titel: Weather
    kurz: Today's forecast as an app; the agent knows the weather.      # exactly one line
    was_daraus_wird: |
      A window with the forecast for your location appears on the desktop.
      The agent answers questions such as "Do I need an umbrella today?".
      The data comes from a weather service of your choice; it is only read.
    bilder: [wetter-1.svg]          # files in bilder/ next to this file (png, jpg, webp or svg)
    art: plugin                     # kern | agent | plugin
    pflicht: false
    abhaengig_von: [kern, agent]    # ids from this catalog or the installer's
    voraussetzungen:                # appear as hints
      - An account with the weather service
    quelle: { paket: fyos-plugin-wetter, repo: fyos-plugin-wetter }
    hub_plugins:                    # entries for the Hub configuration (name, optionally config, secrets, enabled)
      - { name: wetter }
    reife:                          # optional: level (1 to 3) to which the building block raises a layer
      oberflaeche: 2                # gedaechtnis | agent | takte | oberflaeche
      agent: 2
    konfiguration:                  # fields the installer asks for
      - name: ort
        titel: Location             # label of the field (required)
        typ: text                   # text | geheim | url | zahl | wahl
        beschreibung: Location of the forecast
        standard: ""
        pflicht: false
        umgebung: FYOS_WETTER_ORT   # name of the environment variable in the Hub; if unset FYOS_<ID>_<NAME>
      - name: token
        titel: Access key
        typ: geheim
        beschreibung: Access key of the weather service
        umgebung: FYOS_WETTER_TOKEN
```

What it turns into:

- **`quelle`** says where the package comes from: `paket` is the name in the package index, `repo` the name of the Git
  repo. The installer turns it into the line in the generated `hub/Dockerfile`, depending on the source: from a package
  index (`FYOS_PAKETINDEX`, at build time `FYOS_INDEX_URL`; the index comes before PyPI, §10.3)
  `uv pip install fyos-plugin-wetter`, by Git (`FYOS_PLUGIN_QUELLE`)
  `uv pip install "fyos-plugin-wetter @ git+<plugin_quelle>/fyos-plugin-wetter.git"`. Without `quelle` there is nothing
  to install (as with the core's building blocks).
- **`konfiguration`**: every field becomes an environment variable. In the Compose target the values are in the `.env`
  (secrets only there, permissions 600) and are passed through to the Hub; in the Kubernetes target open values end up
  in a ConfigMap and `geheim` in a Secret. **So your plugin reads the same variables** (§2.9). `FYOS_PORT` and
  `FYOS_OEFFENTLICH_URL` are reserved.
- **`hub_plugins`** appear in the generated `hub-config.yaml`. If someone does *not* choose the building block, the
  plugin stays off anyway; the installer's own building blocks it turns off explicitly.
- **`reife`** (optional) tells the installer to which level your building block raises which of the four layers.
  Before writing, the installer shows the **maturity** of the selection: per layer the level, a sentence on how to
  recognise it in the running system, and the next level (ladder and derivation: `installer/README.md`, section
  "Maturity"). The highest level among the chosen building blocks counts; whatever you do not name stays at 1 (core and
  agent are level 1). Rule of thumb: your plugin brings an app → `oberflaeche: 2`. The agent calls its tools →
  `agent: 2`. It delivers knowledge about the environment → `gedaechtnis: 2`. It sets up routines → `takte: 2`. The
  installer itself sets level 3 of the schedules as soon as a chosen Hub plugin carries `takt_grenzen` in its `config`
  (§2.12). Level 3 of the other layers (history and tickets, tickets, control center) belongs to the control room. If
  your catalog replaces an entry of the installer (same `id`) and names no `reife`, the one of the replaced entry is
  kept.
- **`bilder`**: file names, scheme `<id>-<n>.svg`. If there is a `.png` for the name, the installer takes that
  (screenshot before sketch). An SVG sketch with `<title>` and `<desc>` also serves as a text preview; write both, and
  describe in `<desc>` what can be seen. Sample: `fyos-plugin-vorlage/fyos_plugin_vorlage/bilder/vorlage-1.svg`.
- Texts **explain** to people, not to technicians: what appears, what the agent can do, what happens to data, what is
  never done. Write 4 to 6 short sentences.

### 7.2 How the installer finds the file

1. Through the **entry point `fyos.katalog`**: the sample does it this way and is therefore also found with
   `uv pip install -e`.

   ```toml
   [project.entry-points."fyos.katalog"]
   wetter = "fyos_plugin_wetter:katalog_pfad"       # calls the function; it returns the path of the file
   ```

   ```python
   # fyos_plugin_wetter/__init__.py
   from pathlib import Path
   def katalog_pfad() -> Path:
       return Path(__file__).resolve().parent / "fyos-katalog.yaml"
   ```

   (The entry point may also return the path itself or the loaded catalog object.)
2. Without an entry point: a file named `fyos-katalog.yaml` in the installed package of a distribution whose name starts
   with `fyos-plugin-`. For that it has to get into the package through `package-data` (see §2.2).
3. By hand: `fyos-install --katalog path/or/url.yaml` (can be repeated). No pictures come from a URL.
   `--ohne-plugin-kataloge` ignores the catalogs of installed packages.

Checking: `fyos-install --liste` shows all building blocks including yours. A faulty file is reported by the schema
check with every finding (a catalog may be at most 1 MB). The same `id` in a later catalog replaces the earlier one
(with a hint); within one catalog it is an error. With `fyos-install --auswahl wetter --ziel dateien --verzeichnis
/tmp/probe` you see the generated files without starting anything (`--trocken` writes nothing), plus the maturity of
the selection.

After starting a Compose target, the installer runs an acceptance check on the system: it sends three forbidden
requests to the shell, which FYOS must reject (the full call endpoint, a call with a foreign origin, a tool without an
interface over the browser route), and one allowed request as a counter-check. For your plugin this only means: a tool
without an interface (without `ui` in `meta`, without the tag `flaeche`) cannot be reached from the browser, and it
should stay that way (§3.2). To repeat: `fyos-install --abnahme http://localhost:8080` (details: `installer/README.md`,
section "Acceptance check").

### 7.3 Tier per capability: basic tier, extended tier, off

If your plugin depends on a source of the core (§2.13 tickets, §2.14 appointments, §2.15 mailbox, §2.16 documents), it
knows two routes: the **basic tier** (without a service of its own: a CalDAV account, an IMAP mailbox, a store in the
Hub) and the **extended tier** (a service of its own that the Hub reaches through an address in the environment, for
example `FYOS_TERMINE_URL`). The installer lets the user choose the tier **per capability**. The default depends on the
deployment type: Kubernetes takes the extended tier, Docker Compose the basic tier, and where there is no basic tier
(for example sending mail), the extended tier remains.

The capabilities are in `installer/fyos_installer/katalog_stufen.yaml`, not in your plugin's catalog entry. There is a
reason for that: if your catalog entry replaces the installer's (same `id`, §7.2), the capability keeps its tiers, and
the installer adds the extended tier's fields to your building block itself if needed. An entry looks like this:

```yaml
faehigkeiten:
  - id: termine
    titel: Appointments
    kurz: Read your appointments and add a new one on request.
    baustein: kalender              # id of the building block the capability belongs to
    aus: true                       # may the user turn it off completely?
    stufen:
      grund:                        # if grund is missing (or verfuegbar: false), extended and off remain
        titel: CalDAV and ICS directly
        text: The plugin reads your calendar itself, without a service of its own.
        felder: [url, nutzer, passwort]          # fields of the building block that apply only in this tier
      ausbau:
        titel: your own appointment service
        text: A service bundles the appointments; the Hub asks it through FYOS_TERMINE_URL.
        felder:
          - { name: termine_url, typ: url, titel: Address of the appointment service, umgebung: FYOS_TERMINE_URL }
        url: termine_url                          # the field with the service's address
```

What the installer makes of it (details and examples: `installer/README.md`, section "Tier per capability"):

- The choice is made in the assistant and in the text interface (one choice per capability), without an interface with
  `--stufe termine=ausbau` or `stufen: {termine: ausbau}` in the answers file. `fyos-install --liste` shows the
  capabilities with their tiers and the default per deployment type.
- Only the fields of the chosen tier are asked for and written. With the basic tier no service address is set, so your
  plugin takes the direct route. With the extended tier the address is in the Hub's environment.
- An extended tier without a configured address is **not set up**, and your plugin must say so (§2.13:
  `NichtEingerichtet` with a hint, never "empty", see "The pattern" in `REBUILD.md`). Today the installer does not ship
  the extended-tier services yet; it writes the line `FYOS_TERMINE_URL=` for you to fill in and explains this in the
  plan instead of inventing a service.

---

## 8. Companion services and companion scripts

Not everything runs in the Hub. Two kinds of companions:

### 8.1 Companion scripts on other devices

Some data exists only on a particular device (a program on the Mac, a sensor, a NAS). The pattern is in the finance
plugin (`fyos-plugin-finanzen/mac/`): a script runs there on a schedule, reads locally and **pushes** the data to a
webhook; the Hub plugin reads it from there later. That way the device needs no open port.

Rules:

- **Push instead of opening.** The device calls the service, not the other way round.
- **Address and token are not in the script.** Read them from a file outside the repo (`~/.config/fyos/…`, permissions
  600) or from the environment, as `mac/moneymoney_konten.py` does with `finance_base_url` and `finance_token`.
- **Send only what is needed** (of an IBAN the last four digits, no holders). The script decides what leaves the
  device.
- **Only read** where that is enough (no triggering of transfers, no write access).
- **Schedule as part of the repo:** on macOS a LaunchAgent (`*.plist`) with the placeholder `__MAC_DIR__` and an
  `install.sh` that replaces it with the folder and puts it into `~/Library/LaunchAgents`; on Linux a systemd timer or
  cron.
- A script the **agent** should start belongs in the workshop (Hub plugin `werkstatt`: registered scripts with a header
  block `WERKSTATT`, dry run and log), not in a tool of its own with shell access.

The sample repo contains `begleiter/hallo_per_rest.py`: a script that calls a Hub tool through `/hub/call` (only on
your own network; `/hub/call` never belongs on the internet).

Delivery: companions live in the plugin repo (`mac/`, `begleiter/`), not in the Python package; they are installed
where the device is (`git clone`, `mac/install.sh`). Describe the setup in the plugin's README as numbered steps with a
test command at the end.

### 8.2 A service of your own as a container

If your plugin needs a database, heavy computation or an API of its own, move it into a small service. The plugin stays
thin and talks to it over HTTP:

```yaml
# docker-compose.override.yml next to the FYOS Compose file
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
# in the plugin: address from config, always set a timeout, report errors as a failure
def _holen(self, pfad: str) -> dict:
    req = urllib.request.Request(f"{self.dienst_url}{pfad}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode() or "{}")
```

- The service is **internal**: no port to the outside, no login needed as long as only the Hub reaches it. If it should
  be reachable from outside, it belongs behind the same login as the shell.
- The plugin's default addresses are neutral; the real address is in `config:`.
- The plugin stays the only place with tool names and scopes; the service knows nothing about MCP.
- The service gets a repo of its own (`fyos-dienst-<name>`) or a folder `dienst/` in the plugin repo with a Dockerfile
  and a README; the catalog entry (§7) names it under `voraussetzungen`. (For now the finance plugin still keeps the
  data service described in `dienst/README.md`; the service itself moves into a repo of its own later.)

---

## 9. Testing

### 9.1 Locally: the Hub with your own plugin

```sh
uv venv && . .venv/bin/activate
uv pip install -e /path/to/fyos-os/hub        # package fyos-hub (or from the package index, see below)
uv pip install -e ".[test]"                   # your plugin; the entry point is visible at once

MCP_HUB_PORT=8080 python3 -m mcp_hub.server   # without config.yaml only entry point plugins load
```

Installation uses [uv](https://docs.astral.sh/uv/) instead of pip; the reason is in §10.3. If `fyos-hub` lives in a
package index (development builds carry the suffix `.devN`), its address comes with `--index` and thereby before PyPI:
`uv pip install --prerelease allow --index-strategy first-index --index <index address> fyos-hub`.

```sh
curl -s localhost:8080/health
curl -s "localhost:8080/hub/search?query=wetter"
curl -s localhost:8080/hub/call -H 'Content-Type: application/json' \
  -d '{"tool":"vorlage.hallo","arguments":{"name":"Alex"}}'
curl -s localhost:8080/hub/call -H 'Content-Type: application/json' \
  -d '{"tool":"vorlage.notiz_setzen","arguments":{"text":"Milch","__dry_run__":true}}'
curl -s localhost:8080/hub/health             # state per plugin; one that did not load appears with the reason
```

- An MCP client of your choice reaches the same at `http://localhost:8080/mcp` (tools `hub__search_tools`,
  `hub__schema`, `hub__call_tool`; app tools also as `<plugin>__<tool>`).
- With an entry: `MCP_HUB_CONFIG_PATH=./config.yaml` (see `hub/config.example.yaml`).
- You see the interface in the shell: `web/` with `FYOS_DEV_HUB=http://localhost:8080 npm run dev`, then
  `http://localhost:4321/os/?offen=app:vorlage__hallo`. Without a shell,
  `curl "localhost:8080/hub/resource?uri=ui://vorlage/vorlage.html"` shows the HTML with everything filled in.
- If the plugin runs without installation (development), `module:` carries the module path instead of the entry point:
  `- name: wetter, module: fyos_plugin_wetter.plugin` with `PYTHONPATH` pointing to the repo.

### 9.2 Unit tests

pytest against the **real Hub core** (the Hub is a Python package, not a service). Three layers, all in the sample
(`tests/test_plugin.py`):

```python
from mcp_hub import registry as hub_registry
from mcp_hub.kv import SpeicherKv
from fyos_plugin_vorlage.plugin import VorlagePlugin

def test_trockenlauf_aendert_nichts():
    p = VorlagePlugin(); p._r = SpeicherKv()                      # own storage per test
    reg = hub_registry.PluginRegistry()
    hub_registry._register_one(reg, "vorlage", p)                 # exactly like the Hub when loading
    r = hub_registry.dispatch(reg, "vorlage.notiz_setzen", {"text": "Plan", "__dry_run__": True})
    assert r["ok"] is True and r["result"]["dry_run"] is True
    assert p._r.get("fyos:vorlage:notiz") is None
```

1. **Tools** through `hub_registry.dispatch(reg, "<plugin>.<tool>", args)`: result, dry run, error kinds
   (`kind: bad_arguments` for wrong input; input errors do not lock).
2. **Loading:** `build_registry(HubConfig(plugins=[PluginConfig(name=…, module=…)]))` and, when installed, the entry
   point. Plus a test that reads `pyproject.toml` and checks that the entry point points to a `HubPlugin` class.
3. **REST routes:** a small Starlette app with `hub_server.rest_call`, `rest_app_call`, `rest_apps`, `rest_resource`
   and the `TestClient`; this is how you check what the shell experiences (`/hub/app-call` with
   `vorlage__notiz_setzen`, the interface under `/hub/resource`, 400 for wrong input).

Also: the interface is completely filled in (no marker `/*STIL*/`, `/*BRUECKE*/`, `<!--KOPF-->` left), the catalog
entry is valid (`fyos_installer.katalog.lade_datei`, if the installer is installed), the skill can be found through
the plugin `skills`. Tests need neither Redis nor network; replace foreign services with stand-ins (as the finance
plugin does with `p._holen = …`).

There is no browser test for interfaces in the sample. Check them once by hand in the shell at all four sizes (shrink
the window) and in light and dark.

### 9.3 Cleanliness check

```sh
python3 tools/sauber.py .
```

`tools/sauber.py` and `.sauber/verboten.sha256` come from `fyos-os` (a copy). The tool checks every versioned text file
and its path for private networks (RFC 1918, CGNAT), real e-mail addresses, secret patterns (private keys, known token
prefixes) and forbidden words (stored only as hashes). Exceptions: `.sauber/erlaubt.txt` (path prefixes) and the
comment `sauber: ok` on a line. Use neutral examples: owner "Alex", agent "Fy", domains `example.com`/`example.org`,
addresses from the documentation networks (RFC 5737). The check must be silent before you commit.

### 9.4 CI

Template `.gitea/workflows/ci.yml` in the sample:

```yaml
name: ci
on: { push: , pull_request: }
jobs:
  pruefen:
    runs-on: ${{ vars.FYOS_RUNNER }}
    steps:
      - uses: actions/checkout@v4
      - name: Cleanliness
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

Repo variables: `FYOS_RUNNER` (label of the CI runner), and `FYOS_HUB_QUELLE` (for example
`git+https://git.example.com/fyos/fyos-os.git#subdirectory=hub`) or `FYOS_PIP_INDEX` (package index with `fyos-hub`).

Here too uv installs: the package index comes before PyPI through `--index`, and `--index-strategy first-index` takes a
package only from the first index that knows it (§10.3). The example fetches uv at a fixed version into the
environment; if uv is already on the CI runner, leave the line out.

If the CI should upload your package to the Git server's package index (job `paket` as in `fyos-os`), this job needs a
token with the permission `write:package`, stored as the secrets `REGISTRY_USER` and `REGISTRY_TOKEN`. Gitea gives the
runtime token of a run (`GITEA_TOKEN`) no package permissions (as of 1.27); on platforms whose runtime token may write
packages, `permissions: { packages: write }` on the job is enough, and the workflows of `fyos-os` then fall back to it
by themselves.

---

## 10. Delivery

### 10.1 Into the hub image: `FROM fyos-os/hub` + `uv pip install`

The Hub is an image. Your plugin gets into it by building a derived image. The sample's Dockerfile:

```dockerfile
ARG HUB_BILD=registry.example.com/fyos/fyos-os/hub:main
FROM ${HUB_BILD}

ARG FYOS_INDEX_URL=""

USER root
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/
COPY . /tmp/plugin
# tools, app, catalog and skills travel in the package; a package index of your own (if set) comes before PyPI
RUN uv pip install --system --no-cache --index-strategy first-index \
      ${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} /tmp/plugin && rm -rf /tmp/plugin

USER fyos
```

```sh
docker build --build-arg HUB_BILD=registry.example.com/mein/fyos-os/hub:main -t registry.example.com/mein/hub:main .
```

The default of `HUB_BILD` points to an example address that can never be resolved; without `--build-arg` the build
therefore fails visibly instead of pulling a foreign image of the same name.

If your package needs further packages from a package index of your own (for example your Git server's PyPI registry),
pass its address as `--build-arg FYOS_INDEX_URL=https://registry.example.com/api/packages/org/pypi/simple`. It then
comes before PyPI (§10.3). uv comes from the official image at a fixed version; the same version is in the Hub's
Dockerfile.

Then enter the image: in Compose `FYOS_BILD_HUB=registry.example.com/mein/hub:main` (`.env`), in Kubernetes in the
Kustomize overlay under `images` with `name: registry.example.com/fyos/fyos-os/hub` (that is how the base names the
image; a short name such as `fyos-os/hub` no longer takes effect in the overlay). A configuration (`config:`,
`secrets:`) changes without a new image: it lives in `hub-config.yaml`. The Hub loads installed plugins even without an
entry; an entry is only needed for configuration.

The Hub also builds its image itself with `--build-arg EXTRA_PIP="fyos-plugin-wetter"` (and `FYOS_INDEX_URL` for a
private package index that comes before PyPI); skills come along (§4.2).

### 10.2 Through the installer

With the catalog entry (§7) the plugin appears in the installer. The generated folder contains a `hub/Dockerfile` with
`RUN uv pip install …` (from the package index or by Git, §7.1) and the environment values. The package brings tools,
app, catalog entry and skills.

Limits: the installer does not deliver your companion scripts (§8.1) and knows no credentials for private sources. If
your plugin lives in a private repo, build the hub image yourself (10.1) or publish the package to an index the image
can reach.

### 10.3 Package and versions

- **SemVer.** Keep `version` in `pyproject.toml` and in the class attribute `version` the same (the Hub shows it in the
  tool map). Small, compatible changes raise the third number, new tools the second, removed or renamed tools and
  changed required fields the first.
- **The tool ids and their inputs are the interface.** New fields are optional; existing ones keep their meaning.
- **Development builds** go into a package index as `X.Y.Z.devN` (that is what the CI of `fyos-os` does for
  `fyos-hub`, through the PyPI interface of the Git server's package registry), releases with a tag and a release.
- The image gets two tags: `main` (running now) and the commit (for rolling back).
- **Package names are an attack route (dependency confusion).** With `--extra-index-url` pip takes the highest version
  from *all* indexes. If someone uploads a package with your name and a higher version to PyPI, pip may install that
  foreign package. That is why FYOS installs with [uv](https://docs.astral.sh/uv/) instead of pip: your own index comes
  before PyPI through `--index`, and `--index-strategy first-index` (the default in uv, set explicitly in our commands)
  takes a package only from the first index that knows the name. A package of the same name on PyPI therefore cannot
  displace your own. `--index-strategy unsafe-best-match` (the highest version across all indexes, i.e. pip's
  behaviour) belongs nowhere. If your own index is unreachable, uv fails instead of falling back to PyPI. On top of
  that: unique names (`fyos-plugin-…`), and claim the name on PyPI yourself before publishing; that also protects
  everyone who installs your package without your own index.

### 10.4 Private or public

A plugin repo may contain **personal configuration** (examples with your devices, texts for your home). Then it stays
private. If you want to make it public, clean up first; that is also why the distribution itself contains only
general-purpose things.

**Never into the repo** (neither private nor public):

- tokens, passwords, keys, certificates, `.env` and `secrets.yaml` files; the repo names a secret only by its name;
- credentials in examples, tests or logs (not even "for trying out");
- real data: exports from accounts, transactions, photos, recordings, health data, not even as test data;
- addresses of private networks and devices, names of internal domains, names of real people;
- folders with state (`.venv`, databases, caches).

Instead: neutral examples (Alex, Fy, `example.com`), templates with placeholders (`secrets.example.yaml`), real values
only in the Hub's environment, in `/run/secrets` or in the cluster's Secret. `tools/sauber.py` runs locally before
every commit and in the CI and catches the worst mistakes; it does not replace thinking. A secret that has been
published once counts as burnt: rotate the key, do not just change the repo.

### 10.5 Reloading plugins live (without a new image)

Otherwise a new version of a plugin comes with a new image. If you want to shorten that for your own installation, turn
on live loading in the Hub configuration and name directories with source code, usually a checkout that a companion
service keeps pulling:

```yaml
plugins_live: true
plugins_live_takt_s: 30                  # interval of the check
plugins_live_quellen: [/workspace/mein-plugin-repo]   # or environment FYOS_PLUGINS_LIVE_QUELLEN (separated by :)
liste_melden: true                       # open clients learn that the tool list has changed
mcp_sitzungen: false                     # true only with one Hub replica or sticky routing
```

- **Mapping:** the plugin module `a.b.c` comes from `<source>/a/b/c.py` if that file differs from the one in the image
  (for a package, therefore, `<repo>/mein_paket/plugin.py`). Applies to modules of plugins with an entry in the
  configuration, of entry point plugins and, with `plugins_von_selbst`, to new files under
  `<source>/mcp_hub/plugins/`. An entry with `enabled: false` stays off.
- **When:** at startup (if a file differs, the source wins; if it does not build, the image's version stays), then on
  every new commit of the source (`.git` is read directly) and immediately with `POST /hub/plugins/neu-laden`
  (`{"plugin": "name"}` for one, `{"erzwingen": true}` for a new attempt with a file that failed last time).
- **Atomic:** the new module is loaded, the new plugin built and registered; only when all of that succeeds does it
  replace the old one (the old one's `shutdown()` runs afterwards). An error leaves the old plugin in place and appears
  in `/hub/health` under `live` and in the log.
- **Limits:** the core, `_` helper modules, new pip dependencies and the configuration still need a new image.
  Interfaces (`<package>/ui/<file>`) also come from the source. Modules that import another plugin module with
  `from .x import y` keep its old version until the restart.
- **Way back:** `plugins_live: false` (or no source).

`liste_melden` reports a changed tool list through `subscriptions/listen` (MCP SDK 2 or newer); clients with the old
handshake learn about it only with `mcp_sitzungen: true`, in which case the Hub keeps stateful sessions in one
process's memory.

---

## 11. Checklist: "My plugin is done"

**Package**
- [ ] Name `fyos-plugin-<name>`, Python package `fyos_plugin_<name>`; entry point `mcp_hub.plugins` points to the class
- [ ] `uv pip install -e ".[test]"` and `python3 -m mcp_hub.server`: the plugin appears in `/hub/health` without errors
- [ ] `version` in `pyproject.toml` and the class match; interface and catalog are in `package-data`

**Tools**
- [ ] Every tool has a `description` with the words people ask with; `input_schema` describes every field and names `required`
- [ ] Exactly one scope tag (`read`, `write`, `destructive`, `exec`); `extern` if it calls the outside; `flaeche` if the shell may call it
- [ ] The plugin checks input itself and raises `ValueError` with an understandable sentence
- [ ] Every writing tool can do `__dry_run__` and changes nothing while doing so
- [ ] A writing tool that an interface calls requires `bestaetigt: true` for the real run (§3.6)
- [ ] Network calls with a timeout; small results with a `satz`
- [ ] Secrets only from the environment or `secrets:`; never in the result, the log, `health()`
- [ ] `argumente_vertraulich = True` if arguments can carry credentials or personal data (§2.4)

**Interface (if any)**
- [ ] `ui://` resource, `registriere_app` at import time, `meta.ui.resourceUri` on the tools
- [ ] Only the shared style and bridge; no modal dialogs; everything inserted escaped with `esc()`
- [ ] Every panel with data carries a freshness stamp (`App.frische`); a failed reload leaves the old data with the old stamp
- [ ] No button writes directly: small things through `App.beantragen` (plan, "Yes", `bestaetigt: true`), heavy things only as a request to the agent or a person (§3.6)
- [ ] Checked at all four size levels, in light and dark
- [ ] Deep link `/os?offen=app:<plugin>__<tool>` opens the app

**Knowledge and behaviour**
- [ ] `fyos_plugin_<name>/skills/<name>/SKILL.md` with `name` and a meaningful `description`; in `package-data` and entry point `fyos.skills`
- [ ] Rules for every conversation are not in the skill but in the runner (`fyos-agent`); what must be enforced is an approval in the Hub, with tests

**Installer**
- [ ] `fyos-katalog.yaml` with `kurz`, `was_daraus_wird`, picture, `quelle`, fields; entry point `fyos.katalog`
- [ ] `fyos-install --liste` shows the building block; `--auswahl <id> --ziel dateien --trocken` generates sensible files

**Tests and cleanliness**
- [ ] pytest green: tools, dry run, error kinds, loading, REST routes, interface, catalog, skill
- [ ] `python3 tools/sauber.py .` without findings
- [ ] CI run green (`.gitea/workflows/ci.yml`)

**Delivery**
- [ ] Hub image built and started (`docker build …`), tools reachable through `/hub/call`
- [ ] The plugin's README: purpose, tools with scope, configuration (table `config`/environment/meaning), setup of the companions, tests
- [ ] Nothing personal in the repo, or the repo is private

---

*The sample:* `fyos-plugin-vorlage` (Hub plugin with two tools, app, skill, catalog entry, tests, CI,
`umbenennen.py`). Questions and improvements to this guide belong in the same repo as the change that makes them
necessary.
