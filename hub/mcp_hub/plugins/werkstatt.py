"""werkstatt — angemeldete Skripte eines Repos ortsunabhaengig ausfuehren.

Nicht jedes Skript wird eine eigene App. Stattdessen EIN Plugin und EINE Vorlage-App (`ui://fyos/werkstatt.html`), die
jedes angemeldete Skript dynamisch darstellt. Das Repo mit den Skripten liegt unter `FYOS_REPO_PATH` (Plugin-Config
`repo`); gesucht wird unter `<repo>/scripts/`.

Angemeldet ist ein Skript durch seinen Kopfblock — Python: Literal `WERKSTATT = {...}` auf
Modulebene (per AST gelesen, das Skript wird NICHT importiert), Shell: `# werkstatt:` mit
YAML nach der Shebang. Argumente leitet der Hub bei argparse aus `add_argument` ab. Beispiel:

    WERKSTATT = {"titel": "Plattenplatz", "zweck": "Zeigt freien Speicher", "ort": "hub", "wirkung": "lesen"}

Werkzeuge:
    werkstatt.suchen       angemeldete Skripte finden
    werkstatt.beschreiben  Kopfblock + Argumente als JSON-Schema (Formular der App)
    werkstatt.ausfuehren   im Hub ausfuehren (ort hub/egal), sonst „Job-Weg folgt"
    werkstatt.zeigen       beliebiges Ergebnis (Text, Tabelle, Kurve) in der App zeigen
    werkstatt.favoriten    die Favoriten + die letzten Laeufe
    werkstatt.favoriten_setzen  Favoriten festlegen (nur IDs, die es im Katalog gibt)

Sicherheitsregeln:
    lesen            laeuft direkt
    schreiben/system ohne Trockenlauf im Kopfblock gesperrt; Standard ist der Trockenlauf,
                     echter Lauf nur mit `bestaetigt: true`
    loeschen         NIE ausfuehren — nur den fertigen Befehl zurueckgeben; Trockenlauf darf
    Argumente        strikt gegen das Schema, subprocess mit Liste (keine Shell), Textwerte
                     duerfen nicht mit `-` beginnen (kein Unterschieben von Flags)

Jeder Lauf → Strom `fyos:events:werkstatt.lauf` (data = {id, trocken, rc, dauer_s, wer}) über `mcp_hub.kv`
(Redis, sonst Speicher des Prozesses).
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .. import suchrang
from .. import kv
from ..hybrid import Hybrid
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor
from ._identitaet import identitaet
from ._oberflaeche import oberflaeche

UI_DIR = Path(__file__).with_name("ui")
UI_WERKSTATT = "ui://fyos/werkstatt.html"

STROM = "fyos:events:werkstatt.lauf"
#: Favoriten (JSON-Liste von Werkstatt-IDs). Ohne eigene Liste gibt es keine; eine Installation kann
#: Vorbelegungen über die Plugin-Config `favoriten` mitgeben.
K_FAVORITEN = "fyos:werkstatt:favoriten"
FAVORITEN_VORBELEGUNG: tuple[str, ...] = ()
FAVORITEN_MAX = 12

#: Wo ein Skript laufen soll. `hub` und `egal` fuehrt der Hub selbst aus; alle anderen Orte (eigene Rechner,
#: Jobs) bekommen vorerst nur den fertigen Befehl zurueck.
ORTE = ("hub", "extern", "egal")
IM_HUB = ("hub", "egal")
WIRKUNGEN = ("lesen", "schreiben", "loeschen", "system")
TYPEN = ("text", "zahl", "ganzzahl", "schalter", "auswahl")

AUSGABE_MAX = 200_000  # Bytes je Strom
ZEIT_VORGABE = 120
ZEIT_MAX = 1800
TEXT_MAX = 4000
LISTE_MAX = 100
ZEIGEN_MAX = 1_000_000
_OHNE = {"__pycache__", "node_modules", ".venv", "venv", ".git"}
# Hub-Geheimnisse, die kein Skript braucht: nicht an Kindprozesse weiterreichen.
_ENV_WEG = ("FYOS_SECRET_", "FYOS_EMBED_KEY", "FYOS_OIDC_")


# ── Kopfblock lesen ─────────────────────────────────────────────────────────
def _literal(node: ast.AST | None) -> tuple[bool, Any]:
    if node is None:
        return False, None
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _py_kopf(text: str) -> tuple[dict[str, Any] | None, ast.Module | None, str | None]:
    """(Kopfblock, AST, Fehler) eines Python-Skripts — ohne es zu importieren."""
    try:
        baum = ast.parse(text)
    except SyntaxError as e:
        return None, None, f"Syntaxfehler Zeile {e.lineno}"
    for knoten in baum.body:
        ziel = None
        if isinstance(knoten, ast.Assign) and len(knoten.targets) == 1:
            ziel, wert = knoten.targets[0], knoten.value
        elif isinstance(knoten, ast.AnnAssign):
            ziel, wert = knoten.target, knoten.value
        if isinstance(ziel, ast.Name) and ziel.id == "WERKSTATT":
            ok, kopf = _literal(wert)
            if not ok or not isinstance(kopf, dict):
                return None, baum, "WERKSTATT ist kein reines Dict-Literal"
            return kopf, baum, None
    return None, baum, None


def _sh_kopf(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """`# werkstatt:`-Block nach der Shebang (YAML, eingerueckte Kommentarzeilen)."""
    import yaml  # pyyaml

    zeilen = text.splitlines()[:80]
    start = next((i for i, z in enumerate(zeilen) if z.strip() == "# werkstatt:"), None)
    if start is None:
        return None, None
    block: list[str] = []
    for z in zeilen[start + 1 :]:
        if not z.startswith("#"):
            break
        rest = z[1:]
        if rest.strip() and not rest.startswith("  "):
            break  # Kommentar ohne Einrueckung beendet den Block
        block.append(rest)
    try:
        kopf = yaml.safe_load("\n".join(block)) or {}
    except yaml.YAMLError as e:
        return None, f"YAML im werkstatt-Block: {str(e).splitlines()[0]}"
    if not isinstance(kopf, dict):
        return None, "werkstatt-Block ist keine Zuordnung"
    return kopf, None


def _dest(flag: str) -> str:
    return flag.lstrip("-").replace("-", "_")


def argparse_ableiten(baum: ast.Module) -> tuple[list[dict[str, Any]], list[str]]:
    """Argumente aus `add_argument`-Aufrufen (Reihenfolge wie im Quelltext) + Hinweise."""
    hinweise: list[str] = []
    aufrufe = [
        n for n in ast.walk(baum)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument"
    ]
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_subparsers"
           for n in ast.walk(baum)):
        return [], ["Unterbefehle (add_subparsers) — Argumente im Kopfblock unter `argumente` angeben"]
    aufrufe.sort(key=lambda n: (n.lineno, n.col_offset))
    args: list[dict[str, Any]] = []
    for c in aufrufe:
        namen = [v for ok, v in (_literal(a) for a in c.args) if ok and isinstance(v, str)]
        if not namen:
            continue
        kw = {k.arg: k.value for k in c.keywords if k.arg}
        aktion = _literal(kw.get("action"))[1]
        if aktion in ("help", "version"):
            continue
        flags = [n for n in namen if n.startswith("-")]
        if flags:
            lang = next((f for f in flags if f.startswith("--")), flags[0])
            ok, dest = _literal(kw.get("dest"))
            name = dest if ok and isinstance(dest, str) else _dest(lang)
            flag: str | None = lang
        else:
            name, flag = namen[0], None
        a: dict[str, Any] = {"name": name, "flag": flag, "alle_flags": flags}
        ok, hilfe = _literal(kw.get("help"))
        if ok and isinstance(hilfe, str) and hilfe != "==SUPPRESS==":
            a["hilfe"] = hilfe.replace("%(default)s", "Vorgabe").replace("%%", "%")
        if aktion in ("store_true", "store_false", "store_const", "count"):
            a["typ"] = "schalter"
            args.append(a)
            continue
        typ = kw.get("type")
        a["typ"] = {"int": "ganzzahl", "float": "zahl"}.get(typ.id if isinstance(typ, ast.Name) else "", "text")
        ok, auswahl = _literal(kw.get("choices"))
        if ok and isinstance(auswahl, (list, tuple, set, range)):
            a["auswahl"] = [x for x in auswahl if isinstance(x, (str, int, float))]
            if a["typ"] == "text":
                a["typ"] = "auswahl"
        ok, nargs = _literal(kw.get("nargs"))
        if aktion == "append" or (ok and (nargs in ("*", "+") or (isinstance(nargs, int) and nargs > 1))):
            a["mehrfach"] = True
            a["wiederholt"] = aktion == "append"
        ok, req = _literal(kw.get("required"))
        if flag is None:
            a["pflicht"] = not (ok and nargs in ("?", "*"))
        elif ok and req is True:
            a["pflicht"] = True
        if "default" in kw:
            ok, vorgabe = _literal(kw["default"])
            if ok and vorgabe is not None and isinstance(vorgabe, (str, int, float, list)):
                a["vorgabe"] = vorgabe
            elif not ok:
                a["vorgabe_im_skript"] = True
        args.append(a)
    return args, hinweise


def _argumente_normalisieren(roh: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """`argumente` aus dem Kopfblock pruefen und in die interne Form bringen."""
    if not isinstance(roh, list):
        return [], ["`argumente` ist keine Liste"]
    out: list[dict[str, Any]] = []
    fehler: list[str] = []
    for i, e in enumerate(roh):
        if not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"]:
            fehler.append(f"argumente[{i}]: `name` fehlt")
            continue
        typ = e.get("typ") or ("auswahl" if e.get("auswahl") else "text")
        if typ not in TYPEN:
            fehler.append(f"argumente[{i}]: typ {typ!r} unbekannt")
            continue
        flag = e.get("flag")
        if flag is not None and (not isinstance(flag, str) or not flag.startswith("-")):
            fehler.append(f"argumente[{i}]: flag {flag!r} muss mit - beginnen")
            continue
        a = {"name": e["name"], "flag": flag, "typ": typ}
        for k in ("hilfe", "vorgabe"):
            if e.get(k) is not None:
                a[k] = e[k]
        if e.get("auswahl"):
            a["auswahl"] = list(e["auswahl"])
        if e.get("mehrfach"):
            a["mehrfach"] = True
            a["wiederholt"] = bool(e.get("wiederholt"))
        if "pflicht" in e:
            a["pflicht"] = bool(e["pflicht"])
        elif flag is None and typ != "schalter":
            a["pflicht"] = True
        out.append(a)
    return out, fehler


def eintrag_lesen(pfad: Path, scripts_dir: Path) -> dict[str, Any] | None:
    """Kopfblock + Argumente eines Skripts, oder None wenn nicht angemeldet."""
    try:
        text = pfad.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    baum = None
    if pfad.suffix == ".py":
        if "WERKSTATT" not in text:
            return None
        kopf, baum, fehler = _py_kopf(text)
    else:
        if "# werkstatt:" not in text:
            return None
        kopf, fehler = _sh_kopf(text)
    if kopf is None and fehler is None:
        return None
    rel = pfad.relative_to(scripts_dir)
    e: dict[str, Any] = {
        "id": str(rel.with_suffix("")),
        "pfad": f"scripts/{rel}",
        "sprache": "python" if pfad.suffix == ".py" else "bash",
        "fehler": [fehler] if fehler else [],
        "hinweise": [],
    }
    kopf = kopf or {}
    e["titel"] = str(kopf.get("titel") or e["id"])
    e["zweck"] = str(kopf.get("zweck") or "")
    e["ort"] = kopf.get("ort")
    e["wirkung"] = kopf.get("wirkung")
    e["trockenlauf"] = kopf.get("trockenlauf") or None
    e["selbstprobe"] = kopf.get("selbstprobe") or None
    e["json_schalter"] = kopf.get("json_schalter") or None
    e["braucht"] = [str(b) for b in (kopf.get("braucht") or [])] if isinstance(kopf.get("braucht"), list) else []
    try:
        e["zeitlimit_s"] = max(1, min(int(kopf.get("zeitlimit_s") or ZEIT_VORGABE), ZEIT_MAX))
    except (TypeError, ValueError):
        e["zeitlimit_s"] = ZEIT_VORGABE
        e["fehler"].append("zeitlimit_s ist keine Zahl")
    if not kopf.get("titel") or not kopf.get("zweck"):
        e["fehler"].append("titel und zweck sind Pflicht")
    if e["ort"] not in ORTE:
        e["fehler"].append(f"ort muss eines sein von {list(ORTE)}")
    if e["wirkung"] not in WIRKUNGEN:
        e["fehler"].append(f"wirkung muss eines sein von {list(WIRKUNGEN)}")
    for k in ("trockenlauf", "selbstprobe", "json_schalter"):
        if e[k] is not None and (not isinstance(e[k], str) or not e[k].startswith("-")):
            e["fehler"].append(f"{k} muss ein Flag sein (beginnt mit -)")
            e[k] = None

    if "argumente" in kopf:
        args, f = _argumente_normalisieren(kopf["argumente"])
        e["fehler"].extend(f)
    elif baum is not None:
        args, h = argparse_ableiten(baum)
        e["hinweise"].extend(h)
    else:
        args = []
    versteckt = {"-h", "--help"} | {x for x in (e["trockenlauf"], e["selbstprobe"], e["json_schalter"]) if x}
    versteckt |= {str(x) for x in (kopf.get("ausblenden") or []) if isinstance(x, (str,))}
    sichtbar, namen = [], set()
    for a in args:
        flags = set(a.pop("alle_flags", None) or [a.get("flag")])
        if a["name"] in versteckt or flags & versteckt:
            continue
        if a["name"] in namen:
            e["hinweise"].append(f"Argument {a['name']!r} doppelt — nur das erste gilt")
            continue
        namen.add(a["name"])
        sichtbar.append(a)
    e["argumente"] = sichtbar
    e["gesperrt"] = sperre(e)
    return e


def sperre(e: dict[str, Any]) -> str | None:
    """Warum die Werkstatt dieses Skript nicht (echt) ausfuehrt — oder None."""
    if e["fehler"]:
        return "Kopfblock fehlerhaft: " + "; ".join(e["fehler"])
    if e["wirkung"] in ("schreiben", "system") and not e["trockenlauf"]:
        return f"wirkung {e['wirkung']} ohne Trockenlauf im Kopfblock — in der Werkstatt gesperrt"
    return None


# ── Schema und Pruefung ─────────────────────────────────────────────────────
def _item_schema(a: dict[str, Any]) -> dict[str, Any]:
    s: dict[str, Any] = {"type": {"zahl": "number", "ganzzahl": "integer"}.get(a["typ"], "string")}
    if a.get("auswahl"):
        s["enum"] = a["auswahl"]
        if all(isinstance(x, int) and not isinstance(x, bool) for x in a["auswahl"]):
            s["type"] = "integer"
    return s


def schema_bauen(args: list[dict[str, Any]]) -> dict[str, Any]:
    """JSON-Schema fuer das Formular (und die Pruefung beim Ausfuehren)."""
    props: dict[str, Any] = {}
    pflicht: list[str] = []
    for a in args:
        if a["typ"] == "schalter":
            s: dict[str, Any] = {"type": "boolean", "default": False}
        elif a.get("mehrfach"):
            s = {"type": "array", "items": _item_schema(a), "maxItems": LISTE_MAX}
        else:
            s = _item_schema(a)
        if a.get("hilfe"):
            s["description"] = a["hilfe"]
        if "vorgabe" in a and a["typ"] != "schalter":
            s["default"] = a["vorgabe"]
        s["x-flag"] = a.get("flag")
        props[a["name"]] = s
        if a.get("pflicht"):
            pflicht.append(a["name"])
    schema: dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    if pflicht:
        schema["required"] = pflicht
    return schema


def _wert(a: dict[str, Any], v: Any) -> str:
    """Einen Einzelwert pruefen und als argv-Text liefern."""
    typ, n = a["typ"], a["name"]
    if typ == "ganzzahl" or (typ == "auswahl" and a.get("auswahl") and all(isinstance(x, int) for x in a["auswahl"])):
        if isinstance(v, bool) or not isinstance(v, (int, str)):
            raise ValueError(f"{n}: ganze Zahl erwartet")
        try:
            v = int(v)
        except ValueError as e:
            raise ValueError(f"{n}: ganze Zahl erwartet") from e
    elif typ == "zahl":
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValueError(f"{n}: Zahl erwartet")
        try:
            v = float(v) if not isinstance(v, int) else v
        except ValueError as e:
            raise ValueError(f"{n}: Zahl erwartet") from e
    elif not isinstance(v, str):
        raise ValueError(f"{n}: Text erwartet")
    if a.get("auswahl") and v not in a["auswahl"] and str(v) not in [str(x) for x in a["auswahl"]]:
        raise ValueError(f"{n}: {v!r} nicht erlaubt, erlaubt: {a['auswahl']}")
    if isinstance(v, str):
        if len(v) > TEXT_MAX:
            raise ValueError(f"{n}: laenger als {TEXT_MAX} Zeichen")
        if "\x00" in v:
            raise ValueError(f"{n}: enthaelt ein Nullzeichen")
        if v.startswith("-"):
            raise ValueError(f"{n}: Textwerte duerfen nicht mit - beginnen")
    return str(v)


def argv_bauen(e: dict[str, Any], werte: dict[str, Any] | None, trocken: bool) -> list[str]:
    """Werte strikt gegen die Argumente pruefen und die Argumentliste bauen (ohne Interpreter)."""
    if werte is None:
        werte = {}
    if not isinstance(werte, dict):
        raise ValueError("argumente muss ein Objekt sein")
    bekannt = {a["name"] for a in e["argumente"]}
    fremd = sorted(set(werte) - bekannt)
    if fremd:
        raise ValueError(f"unbekannte Argumente {fremd} — erlaubt: {sorted(bekannt)}")
    out: list[str] = []
    for a in e["argumente"]:
        v = werte.get(a["name"])
        if v is None or v == "" or v == []:
            if a.get("pflicht") and "vorgabe" not in a:
                raise ValueError(f"{a['name']} ist Pflicht")
            continue
        flag = a.get("flag")
        if a["typ"] == "schalter":
            if not isinstance(v, bool):
                raise ValueError(f"{a['name']}: true/false erwartet")
            if v and flag:
                out.append(flag)
            continue
        if a.get("mehrfach"):
            if not isinstance(v, list):
                v = [v]
            if len(v) > LISTE_MAX:
                raise ValueError(f"{a['name']}: hoechstens {LISTE_MAX} Werte")
            texte = [_wert(a, x) for x in v]
            if flag is None:
                out.extend(texte)
            elif a.get("wiederholt"):
                for t in texte:
                    out += [flag, t]
            else:
                out += [flag, *texte]
            continue
        t = _wert(a, v)
        out += [flag, t] if flag else [t]
    if trocken and e["trockenlauf"]:
        out += shlex.split(e["trockenlauf"])
    if e.get("json_schalter"):
        out += shlex.split(e["json_schalter"])
    return out


# ── Ausfuehren ──────────────────────────────────────────────────────────────
def _lesen(strom: Any, puffer: bytearray, zaehler: list[int], cap: int) -> None:
    while True:
        stueck = strom.read(8192)
        if not stueck:
            break
        rest = cap - len(puffer)
        if rest > 0:
            puffer.extend(stueck[:rest])
        zaehler[0] += max(0, len(stueck) - max(rest, 0))


def lauf(argv: list[str], cwd: str, env: dict[str, str], zeitlimit: float, cap: int = AUSGABE_MAX) -> dict[str, Any]:
    """Prozess ohne Shell starten, Ausgabe gekappt mitlesen, bei Zeitueberschreitung Gruppe beenden."""
    t0 = time.monotonic()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    aus, err = bytearray(), bytearray()
    weg_aus, weg_err = [0], [0]
    leser = [threading.Thread(target=_lesen, args=(p.stdout, aus, weg_aus, cap), daemon=True),
             threading.Thread(target=_lesen, args=(p.stderr, err, weg_err, cap), daemon=True)]
    for t in leser:
        t.start()
    zeit_um = False
    try:
        rc = p.wait(timeout=zeitlimit)
    except subprocess.TimeoutExpired:
        zeit_um = True
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            p.kill()
        # SIGKILL laesst sich nicht abfangen, aber ein Prozess im Zustand D (haengender NFS-Zugriff) stirbt erst
        # mit dem Aufruf. Ohne Frist haengte `wait()` den Hub-Faden genauso, wie das Limit es verhindern sollte.
        try:
            rc = p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            rc = -signal.SIGKILL
    for t in leser:
        t.join(timeout=5)
    return {
        "rc": rc,
        "dauer_s": round(time.monotonic() - t0, 3),
        "stdout": aus.decode("utf-8", errors="replace"),
        "stderr": err.decode("utf-8", errors="replace"),
        "gekappt": {"stdout": weg_aus[0], "stderr": weg_err[0]} if (weg_aus[0] or weg_err[0]) else None,
        "zeitueberschreitung": zeit_um,
    }


def _redis():
    return kv.klient()


def _form(daten: Any) -> str:
    """Wie die App die Daten zeigt: text | tabelle | kurve | json."""
    def punkte(x: Any) -> bool:
        return isinstance(x, list) and bool(x) and all(isinstance(p, dict) and "x" in p and "y" in p for p in x)

    if isinstance(daten, str):
        return "text"
    if punkte(daten) or (isinstance(daten, dict) and daten and all(punkte(v) for v in daten.values())):
        return "kurve"
    if isinstance(daten, list) and daten and all(isinstance(r, dict) for r in daten):
        return "tabelle"
    return "json"


def _ui(sichtbar: list[str] | None = None) -> dict[str, Any]:
    ui: dict[str, Any] = {"resourceUri": UI_WERKSTATT}
    if sichtbar:
        ui["visibility"] = sichtbar
    return {"ui": ui, "app": identitaet("werkstatt")}


class WerkstattPlugin(HubPlugin):
    name = "werkstatt"
    description = (
        "Werkstatt: angemeldete Repo-Skripte (Kopfblock WERKSTATT) finden, als Formular "
        "beschreiben und im Hub ausfuehren — mit Trockenlauf-Pflicht fuer schreibende "
        "Skripte; loeschen nie. Eine Vorlage-App zeigt Ergebnisse als Text, Tabelle oder Kurve."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        cfg = config or {}
        self.repo = Path(cfg.get("repo") or os.getenv("FYOS_REPO_PATH") or os.getenv("FYOS_REPO") or "/opt/fyos/repo")
        self._favoriten_vorbelegung = tuple(str(x) for x in (cfg.get("favoriten") or FAVORITEN_VORBELEGUNG))
        self.ttl = float(cfg.get("scan_ttl_s", 15))
        self._cache: dict[Path, tuple[float, dict[str, Any] | None]] = {}
        self._stand = 0.0
        self._lock = threading.Lock()
        self._r = None  # Tests setzen eine Attrappe
        # Dichtesuche (Embeddings) fuer werkstatt.suchen; ohne HUB_SUCHE_EMBED_URL nur die Wortsuche
        self._hybrid = Hybrid()

    def redis(self):
        return self._r if self._r is not None else _redis()  # Redis oder Speicher-Attrappe (mcp_hub.kv)

    # ── Lebenszyklus ────────────────────────────────────────────────────────
    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        if not self.repo.is_dir():
            # Frische Installation ohne Repo: nichts kaputt, die Werkstatt ist nur nicht eingerichtet.
            return {"ok": True, "status": "aus", "repo": str(self.repo), "angemeldet": 0,
                    "reason": f"kein Repo unter {self.repo} (werkstatt.repo oder FYOS_REPO_PATH setzen)"}
        ok = (self.repo / "scripts").is_dir()
        n = len(self.katalog()) if ok else 0
        return {"ok": ok, "status": "ok" if ok else "unhealthy", "repo": str(self.repo), "angemeldet": n}

    # ── Katalog (Scan mit mtime-Cache) ──────────────────────────────────────
    def katalog(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if time.monotonic() - self._stand < self.ttl and self._cache:
                return self._index()
            wurzel = self.repo / "scripts"
            gesehen: set[Path] = set()
            for dirpath, dirnames, dateien in os.walk(wurzel):
                dirnames[:] = [d for d in dirnames if d not in _OHNE and not d.startswith(".")]
                for f in dateien:
                    if not (f.endswith(".py") or f.endswith(".sh")):
                        continue
                    p = Path(dirpath) / f
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    gesehen.add(p)
                    alt = self._cache.get(p)
                    if alt is None or alt[0] != mtime:
                        self._cache[p] = (mtime, eintrag_lesen(p, wurzel))
            for p in set(self._cache) - gesehen:
                del self._cache[p]
            self._stand = time.monotonic()
            return self._index()

    def _index(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for p in sorted(self._cache):
            e = self._cache[p][1]
            if e is None:
                continue
            key = e["id"] if e["id"] not in out else e["pfad"].removeprefix("scripts/")
            out[key] = {**e, "id": key}
        return out

    def _eintrag(self, id_: Any) -> dict[str, Any]:
        if not isinstance(id_, str) or not id_:
            raise ValueError("id fehlt")
        e = self.katalog().get(id_.removeprefix("scripts/").removesuffix(".py").removesuffix(".sh"))
        if e is None:
            raise ValueError(f"kein angemeldetes Skript {id_!r} — werkstatt.suchen zeigt alle")
        return e

    # ── Beschreibung ────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        nur_lesen = ["werkstatt", "flaeche", "read"]
        return [
            ToolDescriptor(
                name="suchen",
                title="Werkstatt",
                description=(
                    "Angemeldete Repo-Skripte finden (Kopfblock WERKSTATT). `q` = Suchwoerter (ganze Woerter, Name > "
                    "Titel > Zweck gewichtet; Umschreibungen findet die Aehnlichkeitssuche); die besten 10 mit Rangwert, "
                    "`voll: true` liefert alle Treffer. Ohne q alle Skripte. `ort` und `wirkung` filtern. Liefert id, "
                    "Titel, Zweck, Ort, Wirkung und ob ein Trockenlauf da ist; der Host zeigt dazu die Werkstatt."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "Suchwoerter, z. B. 'speicher platz' oder 'backup'"},
                        "ort": {"type": "string", "enum": list(ORTE)},
                        "wirkung": {"type": "string", "enum": list(WIRKUNGEN)},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "hoechstens so viele Treffer (Vorgabe 10 mit q)"},
                        "voll": {"type": "boolean", "description": "alle Treffer statt der besten 10"},
                    },
                    "additionalProperties": False,
                },
                tags=nur_lesen,
                meta=_ui(),
            ),
            ToolDescriptor(
                name="beschreiben",
                title="Werkstatt — Skript",
                description=(
                    "Ein angemeldetes Skript beschreiben: Kopfblock, Sperren und die Argumente als "
                    "JSON-Schema (daraus baut die App das Formular). id wie aus werkstatt.suchen."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string", "description": "z. B. ops/plattenplatz"}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                tags=nur_lesen,
                meta=_ui(),
            ),
            ToolDescriptor(
                name="ausfuehren",
                title="Werkstatt — ausführen",
                description=(
                    "Ein angemeldetes Skript im Hub ausfuehren (nur ort hub/egal; sonst "
                    "„Job-Weg folgt“). lesen laeuft direkt. schreiben/system: Standard Trockenlauf, "
                    "echter Lauf nur mit trocken=false UND bestaetigt=true. loeschen wird nie "
                    "ausgefuehrt — es kommt der fertige Befehl zum Selbstausfuehren zurueck. `argumente` streng "
                    "nach dem Schema aus werkstatt.beschreiben. Liefert rc, Dauer, stdout/stderr "
                    "und bei JSON-Ausgabe `daten`."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "argumente": {"type": "object", "description": "Werte nach dem Schema aus werkstatt.beschreiben"},
                        "trocken": {"type": "boolean", "description": "Trockenlauf (Standard bei schreiben/system/loeschen)"},
                        "bestaetigt": {"type": "boolean", "description": "echter Lauf eines schreibenden Skripts"},
                        "wer": {"type": "string", "description": "wer ruft (fuer das Bus-Ereignis), z. B. ein Benutzer- oder Agentenname"},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                tags=["werkstatt", "flaeche", "write"],
                # Skript bis ZEIT_MAX (30 min) plus Luft; das Skript hat sein eigenes Zeitlimit, der Hub-Rahmen darueber.
                zeitlimit_s=ZEIT_MAX + 30,
                meta=_ui(),
            ),
            ToolDescriptor(
                name="zeigen",
                title="Werkstatt — Ergebnis",
                description=(
                    "Beliebige Ergebnisse in der Werkstatt-App zeigen: `daten` als Text (String), "
                    "Tabelle (Liste von Objekten), Kurve (Liste von {x, y} oder {name: [{x, y}]}) "
                    "oder sonst als JSON. Veraendert nichts."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "titel": {"type": "string"},
                        "daten": {"description": "Text, Liste von Objekten, [{x,y}] oder beliebiges JSON"},
                        "notiz": {"type": "string"},
                    },
                    "required": ["titel", "daten"],
                    "additionalProperties": False,
                },
                tags=nur_lesen,
                meta=_ui(),
            ),
            ToolDescriptor(
                name="favoriten",
                title="Werkstatt-Favoriten",
                description=(
                    "Die Werkstatt-Favoriten (id, Titel, Wirkung) und die letzten "
                    "Laeufe aus dem Bus (id, rc, wann)."
                ),
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                tags=nur_lesen,
            ),
            ToolDescriptor(
                name="favoriten_setzen",
                title="Werkstatt-Favoriten festlegen",
                description=(
                    f"Legt die Werkstatt-Favoriten fest (hoechstens {FAVORITEN_MAX} "
                    "IDs aus werkstatt.suchen; unbekannte IDs werden abgelehnt)."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "ids": {"type": "array", "items": {"type": "string"}, "maxItems": FAVORITEN_MAX}
                    },
                    "required": ["ids"],
                    "additionalProperties": False,
                },
                tags=["werkstatt", "flaeche", "write"],
            ),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_WERKSTATT,
                name="Werkstatt",
                description="Vorlage-App fuer angemeldete Skripte und Agenten-Ergebnisse",
                read=lambda: oberflaeche("werkstatt.html"),
                meta={"ui": {"prefersBorder": True}},
            )
        ]

    # ── Aufrufe ─────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "suchen":
            return self.suchen(args.get("q") or "", args.get("ort") or "", args.get("wirkung") or "", args.get("limit"), args.get("voll") is True)
        if method == "beschreiben":
            return self.beschreiben(args.get("id"))
        if method == "ausfuehren":
            return self.ausfuehren(args)
        if method == "zeigen":
            return self.zeigen(args)
        if method == "favoriten":
            return self.favoriten()
        if method == "favoriten_setzen":
            return self.favoriten_setzen(args)
        raise ValueError(f"werkstatt hat kein Werkzeug {method!r}")

    LIMIT_SUCHE = 10

    def suchen(self, q: str, ort: str, wirkung: str, limit: Any = None, voll: bool = False) -> dict[str, Any]:
        q = q.strip()
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100):
            raise ValueError("limit muss eine ganze Zahl von 1 bis 100 sein")
        eintraege = [
            e for e in self.katalog().values() if (not ort or e["ort"] == ort) and (not wirkung or e["wirkung"] == wirkung)
        ]
        # Rangfolge: BM25F ueber id > Titel > Zweck mit Wortgrenzen, dazu die Aehnlichkeitssuche (Embeddings).
        rang: list[tuple[dict[str, Any], float | None, str]] = []
        teil = False
        if q:
            if self._hybrid.an:
                self._hybrid.vorwaermen([suchrang.skript_dokument(e) for e in eintraege])
            rang, teil = suchrang.skripte_rang(eintraege, q, self._hybrid)
        else:
            rang = [(e, None, "") for e in eintraege]
        gesamt = len(rang)
        # ohne q (Verzeichnis, die App) und mit voll alle; mit q die besten 10 (oder limit)
        grenze = None if voll else (limit or (self.LIMIT_SUCHE if q else None))
        gezeigt = rang if grenze is None else rang[:grenze]
        treffer = []
        for e, wert, art in gezeigt:
            t = {
                "id": e["id"], "titel": e["titel"], "zweck": e["zweck"], "ort": e["ort"],
                "wirkung": e["wirkung"], "trockenlauf": bool(e["trockenlauf"]),
                "im_hub": e["ort"] in IM_HUB, "gesperrt": e["gesperrt"],
            }
            if wert is not None:
                t["wert"] = wert
                if art == "aehnlich":
                    t["aehnlich"] = True
            treffer.append(t)
        namen = {"lesen": "lesend", "schreiben": "schreibend", "system": "System", "loeschen": "löschend"}
        teile = [f"{n} {namen[w]}" for w in namen if (n := sum(1 for t in treffer if t["wirkung"] == w))]
        satz = (f"{len(treffer)} {'Skript' if len(treffer) == 1 else 'Skripte'}" + (f", davon {', '.join(teile)}" if teile else "")
                + (f" zu „{q}“" if q else "") + ".")
        antwort: dict[str, Any] = {"satz": satz, "art": "liste", "anzahl": len(treffer), "skripte": treffer}
        if q:
            antwort["gesamt"] = gesamt
            if teil and treffer:
                antwort["teiltreffer"] = True
            if not treffer:
                antwort["hinweis"] = "Kein Skript passt — werkstatt.suchen ohne q zeigt alle."
            elif gesamt > len(treffer):
                antwort["hinweis"] = f"{gesamt - len(treffer)} weitere — voll: true oder limit erhoehen."
            if any(t.get("aehnlich") for t in treffer):
                antwort["aehnlich_hinweis"] = "aehnlich: true = nur dem Sinn nach verwandt, kein Suchwort kommt vor."
        return antwort

    def beschreiben(self, id_: Any) -> dict[str, Any]:
        e = self._eintrag(id_)
        return {
            "art": "skript",
            **{k: e[k] for k in ("id", "pfad", "sprache", "titel", "zweck", "ort", "wirkung", "trockenlauf",
                                 "selbstprobe", "braucht", "zeitlimit_s", "gesperrt", "hinweise", "fehler")},
            "im_hub": e["ort"] in IM_HUB,
            "schema": schema_bauen(e["argumente"]),
        }

    def _befehl(self, e: dict[str, Any], rest: list[str]) -> list[str]:
        return ["python3" if e["sprache"] == "python" else "bash", e["pfad"], *rest]

    def ausfuehren(self, args: dict[str, Any]) -> dict[str, Any]:
        e = self._eintrag(args.get("id"))
        wirkung = e["wirkung"]
        trocken_arg = args.get("trocken")
        bestaetigt = args.get("bestaetigt") is True
        if trocken_arg is not None and not isinstance(trocken_arg, bool):
            raise ValueError("trocken muss true/false sein")
        # Standard: lesen echt, alles andere trocken.
        trocken = (wirkung != "lesen") if trocken_arg is None else trocken_arg
        if wirkung == "lesen" and not e["trockenlauf"]:
            trocken = False
        rest = argv_bauen(e, args.get("argumente"), trocken)
        befehl = self._befehl(e, rest)
        antwort: dict[str, Any] = {"art": "lauf", "id": e["id"], "titel": e["titel"], "wirkung": wirkung,
                                   "trocken": trocken, "befehl": shlex.join(befehl), "ausgefuehrt": False}
        if e["fehler"]:
            return {**antwort, "grund": e["gesperrt"]}
        if wirkung == "loeschen" and not (trocken and e["trockenlauf"]):
            return {**antwort, "trocken": False, "befehl": shlex.join(self._befehl(e, argv_bauen(e, args.get("argumente"), False))),
                    "hinweis": "Löschen führst du selbst aus"}
        if wirkung in ("schreiben", "system"):
            if not e["trockenlauf"]:
                return {**antwort, "grund": e["gesperrt"]}
            if not trocken and not bestaetigt:
                return {**antwort, "grund": "echter Lauf eines schreibenden Skripts braucht bestaetigt: true — erst den Trockenlauf ansehen"}
        if e["ort"] not in IM_HUB:
            return {**antwort, "grund": f"läuft auf {e['ort']} — Job-Weg folgt"}

        interpreter = sys.executable if e["sprache"] == "python" else "bash"
        env = {k: v for k, v in os.environ.items() if not k.startswith(_ENV_WEG)}
        env.update({"FYOS_REPO": str(self.repo), "FYOS_REPO_PATH": str(self.repo), "PYTHONUNBUFFERED": "1",
                    "PYTHONDONTWRITEBYTECODE": "1", "WERKSTATT_LAUF": "1"})
        r = lauf([interpreter, str(self.repo / e["pfad"]), *rest], str(self.repo), env, e["zeitlimit_s"])
        antwort.update(r, ausgefuehrt=True)
        text = r["stdout"].strip()
        if text[:1] in ("{", "[") and not r["gekappt"]:
            try:
                antwort["daten"] = json.loads(text)
                antwort["form"] = _form(antwort["daten"])
            except ValueError:
                pass
        self._melden(e["id"], trocken, r["rc"], r["dauer_s"], str(args.get("wer") or "hub")[:40])
        return antwort

    def _melden(self, id_: str, trocken: bool, rc: int, dauer_s: float, wer: str) -> None:
        data = {"id": id_, "trocken": trocken, "rc": rc, "dauer_s": dauer_s, "wer": wer}
        try:
            self.redis().xadd(STROM, {"data": json.dumps(data, ensure_ascii=False), "source": "fyos-hub/werkstatt",
                                  "ts": str(int(time.time()))}, maxlen=1000, approximate=True)
        except Exception:  # noqa: BLE001 — der Bus darf den Lauf nie verhindern
            pass

    def zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        titel = args.get("titel")
        if not isinstance(titel, str) or not titel.strip():
            raise ValueError("titel fehlt")
        if "daten" not in args:
            raise ValueError("daten fehlt")
        daten = args["daten"]
        if len(json.dumps(daten, ensure_ascii=False, default=str)) > ZEIGEN_MAX:
            raise ValueError(f"daten groesser als {ZEIGEN_MAX} Zeichen — bitte kuerzen")
        out = {"art": "zeigen", "titel": titel[:200], "daten": daten, "form": _form(daten)}
        if isinstance(args.get("notiz"), str):
            out["notiz"] = args["notiz"][:2000]
        return out

    # ── Favoriten ──────────────────────────────────────────────
    def favoriten_ids(self) -> tuple[list[str], str]:
        """Wirksame Favoriten (nur IDs, die es im Katalog gibt) und woher sie kommen."""
        katalog = self.katalog()
        roh = None
        try:
            roh = self.redis().get(K_FAVORITEN)
        except Exception:  # noqa: BLE001 — ohne Redis gilt die Vorbelegung
            roh = None
        if roh:
            try:
                ids = [i for i in json.loads(roh) if isinstance(i, str)]
                return [i for i in ids if i in katalog], "gespeichert"
            except ValueError:
                pass
        return [i for i in self._favoriten_vorbelegung if i in katalog], "vorbelegung"

    def letzte_laeufe(self, n: int = 10) -> list[dict[str, Any]]:
        out = []
        for eid, f in self.redis().xrevrange(STROM, count=n):
            try:
                d = json.loads(f.get("data") or "{}")
            except ValueError:
                continue
            ts = f.get("ts") or str(eid).split("-")[0][:10]
            try:
                wann = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(float(ts))))
            except (TypeError, ValueError):
                wann = None
            out.append({"id": d.get("id"), "rc": d.get("rc"), "trocken": bool(d.get("trocken")),
                        "wer": d.get("wer"), "wann": wann})
        return out

    def favoriten(self) -> dict[str, Any]:
        katalog = self.katalog()
        ids, herkunft = self.favoriten_ids()
        try:
            zuletzt: list[dict[str, Any]] | None = self.letzte_laeufe()
        except Exception:  # noqa: BLE001 — Verlauf unbekannt ist nicht „keine Laeufe"
            zuletzt = None
        return {
            "favoriten": [{"id": i, "titel": katalog[i]["titel"], "wirkung": katalog[i]["wirkung"]} for i in ids],
            "herkunft": herkunft,
            "zuletzt": zuletzt,
        }

    def favoriten_setzen(self, args: dict[str, Any]) -> dict[str, Any]:
        ids = args.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("ids muss eine Liste von Werkstatt-IDs sein")
        if len(ids) > FAVORITEN_MAX:
            raise ValueError(f"hoechstens {FAVORITEN_MAX} Favoriten")
        katalog = self.katalog()
        fehlt = [i for i in ids if i not in katalog]
        if fehlt:
            raise ValueError(f"gibt es nicht in der Werkstatt: {', '.join(fehlt)} — werkstatt.suchen zeigt alle")
        sauber = list(dict.fromkeys(ids))
        self.redis().set(K_FAVORITEN, json.dumps(sauber))
        return {"ok": True, "favoriten": sauber}
