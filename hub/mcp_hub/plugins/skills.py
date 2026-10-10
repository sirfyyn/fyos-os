"""skills — Arbeitsanleitungen als durchsuchbares Verzeichnis im Hub.

Skills sind Wissen (wann, in welcher Reihenfolge, welche Fallen); die Werkstatt liefert die Handgriffe
(angemeldete Skripte). Ein Skill nennt die Werkstatt-IDs, die er benutzt.

Quellen: ein oder mehrere Verzeichnisse mit dem Aufbau

    <quelle>/<name>/SKILL.md          die Anleitung
    <quelle>/<name>/references/...    optionale Zusatzdateien

Welche Verzeichnisse gelten, bestimmt (in dieser Reihenfolge) die Plugin-Config `quellen` (Liste von Pfaden oder
`{pfad, name}`), die Umgebungsvariable `FYOS_SKILLS_PATH` (Pfade mit `:` getrennt) und zuletzt die Vorgabe
`/opt/fyos/skills`. Dahinter kommen die Skill-Ordner installierter Plugin-Pakete (Entry-Point-Gruppe
`fyos.skills`, abschaltbar mit `plugin_skills: false`). Die Quelle heisst nach ihrem Verzeichnisnamen bzw. dem
Entry-Point; bei gleichem Skill-Namen gewinnt die zuerst genannte. Zuletzt kommen Skills, die andere Plugins beitragen
(``HubPlugin.skills_beitrag``, etwa die des Agenten über das Plugin ``openclaw``; abschaltbar mit `beitraege: false`).
Jede SKILL.md beginnt mit Front-Matter (`name`, `description`; optional `werkstatt: [ids]`,
`ausloeser`, `fuer: [agent, …]`).

Werkzeuge:
    skills.suchen   Verzeichnis durchsuchen (alle Wörter; sonst beste Teiltreffer). Ohne q: alles, kompakt.
    skills.lesen    eine SKILL.md (oder eine Datei aus references/) lesen
Nur lesend; der Hub liest die Dateien, nichts wird ausgeführt.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..plugin import HubPlugin, ToolDescriptor

VORGABE_QUELLE = "/opt/fyos/skills"
TEXT_MAX = 60_000
BESCHREIBUNG_MAX = 220
TREFFER_MAX = 25
_WORT = re.compile(r"[\wäöüß-]+", re.IGNORECASE)


def front_matter(text: str) -> tuple[dict[str, Any], str]:
    """(Front-Matter, Rumpf). Ohne Front-Matter: ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    ende = text.find("\n---", 3)
    if ende < 0:
        return {}, text
    import yaml  # pyyaml

    try:
        kopf = yaml.safe_load(text[3:ende]) or {}
    except yaml.YAMLError:
        kopf = {}
    rumpf = text[ende + 4 :].lstrip("\n")
    return (kopf if isinstance(kopf, dict) else {}), rumpf


def _liste(wert: Any) -> list[str]:
    if isinstance(wert, str):
        return [w.strip() for w in wert.split(",") if w.strip()]
    if isinstance(wert, list):
        return [str(w) for w in wert if str(w).strip()]
    return []


PLUGIN_GRUPPE = "fyos.skills"


def _plugin_quellen() -> list[tuple[Path, str]]:
    """Skill-Ordner installierter Plugin-Pakete (Entry-Point-Gruppe `fyos.skills`).

    Wert eines Eintrags ist ein importierbares Paket; gilt dessen Unterordner `skills/`, sonst das Paket selbst.
    Beispiel im pyproject eines Plugins:  [project.entry-points."fyos.skills"]  wetter = "fyos_plugin_wetter"
    Die Quelle heisst nach dem Entry-Point. Konfigurierte Quellen haben Vorrang (sie stehen davor).
    """
    from importlib import metadata, resources

    out: list[tuple[Path, str]] = []
    try:
        eintraege = metadata.entry_points(group=PLUGIN_GRUPPE)
    except Exception:  # noqa: BLE001 - ein kaputtes Paket darf den Hub nicht stoppen
        return out
    for ep in eintraege:
        try:
            basis = Path(str(resources.files(ep.value.split(":", 1)[0])))
        except Exception:  # noqa: BLE001
            continue
        ordner = basis / "skills" if (basis / "skills").is_dir() else basis
        out.append((ordner, ep.name))
    return out


def eintrag_lesen(ordner: Path, quelle: str) -> dict[str, Any] | None:
    datei = ordner / "SKILL.md"
    try:
        text = datei.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    kopf, rumpf = front_matter(text)
    name = str(kopf.get("name") or ordner.name)
    beschreibung = " ".join(str(kopf.get("description") or "").split())
    ref = ordner / "references"
    dateien = sorted(p.name for p in ref.iterdir() if p.is_file()) if ref.is_dir() else []
    return {
        "name": name,
        "quelle": quelle,
        "beschreibung": beschreibung,
        "ausloeser": " ".join(str(kopf.get("ausloeser") or "").split()),
        "werkstatt": _liste(kopf.get("werkstatt")),
        "fuer": _liste(kopf.get("fuer")),
        "dateien": dateien,
        "pfad": str(datei),
        "_rumpf": rumpf.lower(),
        "_kopf": f"{name} {beschreibung} {kopf.get('ausloeser') or ''}".lower(),
    }


class SkillsPlugin(HubPlugin):
    name = "skills"
    description = (
        "Skills: Arbeitsanleitungen als durchsuchbares Verzeichnis (SKILL.md je Ordner); "
        "jeder Skill nennt die Werkstatt-Skripte, die er nutzt."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        cfg = config or {}
        self.quellen = self._quellen_bestimmen(cfg)
        self.repo = self.quellen[0][0] if self.quellen else Path(VORGABE_QUELLE)
        self.ttl = float(cfg.get("scan_ttl_s", 30))
        self._beitraege = bool(cfg.get("beitraege", True))
        self._registry: Any = None
        self._katalog: dict[str, dict[str, Any]] = {}
        self._stand = 0.0
        self._lock = threading.Lock()

    def registry_anbinden(self, registry: Any) -> None:
        """Vom Server gerufen: die anderen Plugins, deren ``skills_beitrag()`` das Verzeichnis ergänzt."""
        self._registry = registry

    def _beitraege_lesen(self) -> list[dict[str, Any]]:
        """Einträge aus ``HubPlugin.skills_beitrag`` der anderen Plugins (in Katalog-Form, Text oder Leser statt Pfad)."""
        out: list[dict[str, Any]] = []
        if not self._beitraege or self._registry is None:
            return out
        for pname, plugin in sorted((getattr(self._registry, "plugins", None) or {}).items()):
            holen = getattr(plugin, "skills_beitrag", None)
            if plugin is self or not callable(holen):
                continue
            try:
                roh = list(holen() or [])
            except Exception:  # noqa: BLE001 — ein Plugin kostet nur seine eigenen Skills
                continue
            for b in roh:
                if not isinstance(b, dict) or not str(b.get("name") or "").strip():
                    continue
                name = str(b["name"]).strip()
                text = b.get("text")
                leser = b.get("lesen")
                if not isinstance(text, str) and not callable(leser):
                    continue
                beschreibung = " ".join(str(b.get("beschreibung") or "").split())
                out.append({
                    "name": name,
                    "quelle": str(b.get("quelle") or pname),
                    "beschreibung": beschreibung,
                    "ausloeser": " ".join(str(b.get("ausloeser") or "").split()),
                    "werkstatt": _liste(b.get("werkstatt")),
                    "fuer": _liste(b.get("fuer")),
                    "dateien": [],
                    "pfad": f"{pname}:{name}",
                    "_text": text if isinstance(text, str) else None,
                    "_lesen": leser if callable(leser) else None,
                    "_rumpf": (text or "").lower() if isinstance(text, str) else "",
                    "_kopf": f"{name} {beschreibung} {b.get('ausloeser') or ''}".lower(),
                })
        return out

    @staticmethod
    def _quellen_bestimmen(cfg: dict[str, Any]) -> list[tuple[Path, str]]:
        roh: list[Any] = []
        if isinstance(cfg.get("quellen"), list):
            roh = list(cfg["quellen"])
        elif os.getenv("FYOS_SKILLS_PATH"):
            roh = [s for s in os.environ["FYOS_SKILLS_PATH"].split(os.pathsep) if s.strip()]
        if not roh:
            roh = [VORGABE_QUELLE]
        out: list[tuple[Path, str]] = []
        for q in roh:
            if isinstance(q, dict):
                pfad, name = Path(str(q.get("pfad") or "")), str(q.get("name") or "")
            else:
                pfad, name = Path(str(q)), ""
            if str(pfad) in ("", "."):
                continue
            out.append((pfad, name or pfad.name or "skills"))
        if cfg.get("plugin_skills", True):
            out.extend(_plugin_quellen())
        return out

    def register(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        n = len(self.katalog())
        return {"ok": True, "status": "ok" if n else "leer", "quellen": [str(p) for p, _ in self.quellen], "skills": n}

    # ── Katalog ─────────────────────────────────────────────────────────────
    def katalog(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self._katalog and time.monotonic() - self._stand < self.ttl:
                return self._katalog
            neu: dict[str, dict[str, Any]] = {}
            for wurzel, quelle in self.quellen:
                if not wurzel.is_dir():
                    continue
                for ordner in sorted(wurzel.iterdir()):
                    if not ordner.is_dir() or ordner.name.startswith("."):
                        continue
                    e = eintrag_lesen(ordner, quelle)
                    if e is None:
                        continue
                    # die zuerst genannte Quelle hat Vorrang bei gleichem Namen
                    if e["name"] in neu:
                        continue
                    neu[e["name"]] = e
            for e in self._beitraege_lesen():
                neu.setdefault(e["name"], e)
            self._katalog = neu
            self._stand = time.monotonic()
            return neu

    def _rang_quelle(self, quelle: str) -> int:
        namen = [n for _, n in self.quellen]
        return namen.index(quelle) if quelle in namen else len(namen)

    @staticmethod
    def _oeffentlich(e: dict[str, Any], kurz: bool) -> dict[str, Any]:
        b = e["beschreibung"]
        if kurz and len(b) > BESCHREIBUNG_MAX:
            b = b[: BESCHREIBUNG_MAX - 1] + "…"
        out = {"name": e["name"], "quelle": e["quelle"], "beschreibung": b}
        if e["werkstatt"]:
            out["werkstatt"] = e["werkstatt"]
        if not kurz:
            out.update({"ausloeser": e["ausloeser"], "fuer": e["fuer"], "dateien": e["dateien"]})
        return out

    # ── Werkzeuge ───────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="suchen",
                title="Skills",
                description=(
                    "Skills (Arbeitsanleitungen) aller Agenten durchsuchen: `q` = Wörter (alle müssen in Name, "
                    "Beschreibung oder Text vorkommen; sonst die besten Teiltreffer). Ohne q das ganze Verzeichnis "
                    "kompakt. Liefert Name, Quelle (Verzeichnisname), Beschreibung und die Werkstatt-IDs, die der "
                    "Skill nutzt. Danach skills.lesen."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "Suchwörter, z. B. 'deploy' oder 'backup'"},
                        "quelle": {"type": "string", "description": "Nur diese Quelle (Verzeichnisname)"},
                    },
                    "additionalProperties": False,
                },
                tags=["skills", "verzeichnis", "read"],
            ),
            ToolDescriptor(
                name="lesen",
                title="Skill lesen",
                description=(
                    "Einen Skill lesen: die SKILL.md (Front-Matter + Text) und die Liste seiner Zusatzdateien; mit "
                    "`datei` eine Datei aus references/. Name wie aus skills.suchen."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "datei": {"type": "string", "description": "Dateiname aus references/ (optional)"},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                tags=["skills", "read"],
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "suchen":
            return self.suchen(str(args.get("q") or ""), str(args.get("quelle") or ""))
        if method == "lesen":
            return self.lesen(args.get("name"), args.get("datei"))
        raise ValueError(f"skills hat kein Werkzeug {method!r}")

    def suchen(self, q: str, quelle: str = "") -> dict[str, Any]:
        alle = [e for e in self.katalog().values() if not quelle or e["quelle"] == quelle]
        woerter = [w.lower() for w in _WORT.findall(q)]
        if not woerter:
            liste = [self._oeffentlich(e, kurz=True) for e in sorted(alle, key=lambda e: (self._rang_quelle(e["quelle"]), e["name"]))]
            return {"satz": f"{len(liste)} Skills im Verzeichnis.", "art": "verzeichnis", "anzahl": len(liste), "skills": liste}
        bewertet = []
        for e in alle:
            punkte, getroffen = 0, 0
            for w in woerter:
                p = 3 * (w in e["name"].lower()) + 2 * (w in e["_kopf"]) + (w in e["_rumpf"])
                punkte += p
                getroffen += p > 0
            if getroffen:
                bewertet.append((getroffen == len(woerter), punkte, e))
        voll = [b for b in bewertet if b[0]]
        art = "alle_woerter" if voll else "teiltreffer"
        auswahl = sorted(voll or bewertet, key=lambda b: (-b[1], b[2]["name"]))[:TREFFER_MAX]
        liste = [self._oeffentlich(b[2], kurz=True) for b in auswahl]
        satz = (f"{len(liste)} Skills zu „{q}“." if liste else f"Kein Skill zu „{q}“ — skills.suchen ohne q zeigt alle.")
        return {"satz": satz, "art": art, "anzahl": len(liste), "skills": liste}

    def lesen(self, name: Any, datei: Any = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name:
            raise ValueError("name fehlt")
        e = self.katalog().get(name)
        if e is None:
            raise ValueError(f"kein Skill {name!r} — skills.suchen zeigt alle")
        if e.get("_text") is not None or e.get("_lesen") is not None:
            # Beitrag eines Plugins: der Text kommt aus dem Speicher oder vom angebundenen Dienst.
            if datei:
                raise ValueError(f"{name} hat keine Zusatzdateien")
            text = e["_text"] if e.get("_text") is not None else str(e["_lesen"]() or "")
            return {
                **self._oeffentlich(e, kurz=False),
                "datei": "SKILL.md",
                "text": text[:TEXT_MAX],
                "gekuerzt": len(text) > TEXT_MAX,
                "pfad": e["pfad"],
            }
        pfad = Path(e["pfad"])
        if datei:
            if not isinstance(datei, str) or datei not in e["dateien"]:
                raise ValueError(f"{name} hat keine Datei {datei!r}; vorhanden: {', '.join(e['dateien']) or 'keine'}")
            pfad = pfad.parent / "references" / datei
        text = pfad.read_text(encoding="utf-8", errors="replace")
        gekuerzt = len(text) > TEXT_MAX
        return {
            **self._oeffentlich(e, kurz=False),
            "datei": datei or "SKILL.md",
            "text": text[:TEXT_MAX],
            "gekuerzt": gekuerzt,
            "pfad": str(pfad),
        }
