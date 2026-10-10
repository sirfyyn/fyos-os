"""Plan und Erzeugung der Auslieferung. Gemeinsam für Web-Assistent, TUI und Kommandozeile.

`erstelle_plan` berechnet rein im Speicher, was entstehen würde (Dateien, Befehle, Hinweise, Fehler);
`schreiben` legt die Dateien an. So zeigen alle Oberflächen dieselbe Vorschau und `--trocken` schreibt nichts.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import yaml

from . import abnahme
from .katalog import Baustein, Katalog, KatalogFehler, aufloesen, quelle_aufloesen
from .reife import Reife, bestimme as bestimme_reife

PAKET = Path(__file__).resolve().parent
VORLAGEN = PAKET / "vorlagen"

ZIELE = {
    "compose": "Docker Compose auf diesem Rechner",
    "k8s": "Kubernetes (Kustomize-Overlay)",
    "dateien": "Nur Dateien erzeugen (Docker-Compose-Layout)",
}

VORGABE_PERSONA = {
    "agent_name": "Fy",
    "wesen": "Ruhig, präzise und zugewandt",
    "besitzer_name": "Alex",
    "sprache": "Deutsch",
}
VORGABE_MODELL = {"basis_url": "http://host.docker.internal:11434/v1", "name": "qwen3:8b", "schluessel": ""}
# Ohne eigene Registry zeigen die Bilder auf eine Beispieladresse, die sich nie auflösen lässt: Ziehen schlägt
# sichtbar fehl, statt still ein fremdes Bild gleichen Namens zu holen.
BEISPIEL_REGISTRY = "registry.example.com/fyos"
# Bildnamen, wie deploy/k8s/base sie ausgibt (dort `images`: fyos-os/web → Beispieladresse). Kustomize wendet die
# Bild-Ersetzung der Basis vor der des Overlays an; ein Overlay muss deshalb diese Namen ersetzen, nicht die kurzen.
BASIS_BILDNAMEN = {
    "web": f"{BEISPIEL_REGISTRY}/fyos-os/web",
    "hub": f"{BEISPIEL_REGISTRY}/fyos-os/hub",
    "agent": f"{BEISPIEL_REGISTRY}/fyos-agent/openclaw",
}
# Das erzeugte Hub-Bild installiert Plugin-Pakete mit uv statt pip. uv fragt die Indizes der Reihe nach und nimmt ein
# Paket nur aus dem ersten Index, der es führt (--index-strategy first-index); der eigene Paketindex steht per --index
# vor PyPI. Mit `pip --extra-index-url` nähme pip die höchste Version aus allen Indizes, und ein fremdes Paket gleichen
# Namens auf PyPI gewänne (Dependency Confusion). Version von uv wie in hub/Dockerfile (test_erzeugen.py hält sie gleich).
UV_BILD = "ghcr.io/astral-sh/uv:0.12.8"


def _bilder(reg: str) -> dict[str, str]:
    return {
        "hub_bild": f"{reg}/fyos-os/hub:main", "bild_web": f"{reg}/fyos-os/web:main",
        "bild_agent": f"{reg}/fyos-agent/openclaw:main", "hub_bild_k8s": f"{reg}/fyos-os/hub-eigen:main",
    }


VORGABE_OPTIONEN = {  # ohne Umgebung; mit Umgebung siehe vorgaben_optionen()
    **_bilder(BEISPIEL_REGISTRY),
    "k8s_basis": "",
    "namespace": "fyos",
    "bezug": "",  # index | git; leer = automatisch
    "paketindex": "",
    "plugin_quelle": "",
}


def vorgaben_optionen(umgebung: Mapping[str, str] | None = None, bezug_aufloesen: bool = False) -> dict[str, str]:
    """Vorgaben der Optionen. `FYOS_REGISTRY` (zum Beispiel registry.example.com/org) bestimmt die Bildnamen,
    `FYOS_PAKETINDEX` und `FYOS_PLUGIN_QUELLE` den Bezug der Plugin-Pakete."""
    umgebung = os.environ if umgebung is None else umgebung
    o = dict(VORGABE_OPTIONEN)
    reg = umgebung.get("FYOS_REGISTRY", "").strip().strip("/")
    if reg:
        o.update(_bilder(reg))
    o["paketindex"] = umgebung.get("FYOS_PAKETINDEX", "").strip()
    o["plugin_quelle"] = umgebung.get("FYOS_PLUGIN_QUELLE", "").strip()
    if bezug_aufloesen:
        o["bezug"] = _auto_bezug(o)
    return o


def _auto_bezug(o: Mapping[str, str]) -> str:
    if o.get("bezug") in ("index", "git"):
        return o["bezug"]
    return "git" if (o.get("plugin_quelle") and not o.get("paketindex")) else "index"
SPRACHCODES = {
    "deutsch": "de", "english": "en", "englisch": "en", "français": "fr", "französisch": "fr",
    "español": "es", "spanisch": "es", "italiano": "it", "italienisch": "it", "nederlands": "nl",
}
RESERVIERT = {"FYOS_PORT", "FYOS_OEFFENTLICH_URL"}  # Compose liest sie selbst aus .env

_STEUER = re.compile(r"[\x00-\x1f\x7f]")
_SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\],=<>!~ @:/+?&%#]*$")
_BILD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:@]*$")
_INDEX = re.compile(r"""^https?://[^\s"'$`\\]+$""")
_NAMESPACE =re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_PLATZHALTER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_SICHER_ENV = re.compile(r"^[A-Za-z0-9_@%+=:,./-]*$")
STANDARD_URL = "http://localhost:8080"


@dataclass
class Datei:
    pfad: str
    inhalt: str
    modus: int = 0o644
    beschreibung: str = ""
    anzeige: str | None = None  # Vorschau ohne Geheimnisse; None = inhalt

    @property
    def geheim(self) -> bool:
        return self.anzeige is not None and self.anzeige != self.inhalt

    def vorschau(self) -> str:
        return self.inhalt if self.anzeige is None else self.anzeige


@dataclass
class Plan:
    ziel: str
    verzeichnis: Path
    auswahl: list[str] = field(default_factory=list)  # aufgelöst, Abhängigkeiten zuerst
    dateien: list[Datei] = field(default_factory=list)
    befehle: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)
    url: str | None = None
    port: int = 8080
    hub_quellen: list[str] = field(default_factory=list)
    reife: list[Reife] = field(default_factory=list)  # je Schicht die Stufe, aus der Auswahl abgeleitet (reife.py)

    @property
    def ok(self) -> bool:
        return not self.fehler

    @property
    def ausfuehrbar(self) -> bool:
        """Nur Docker Compose wird vom Installer selbst gestartet."""
        return self.ziel == "compose" and self.ok

    def als_dict(self) -> dict[str, Any]:
        return {
            "ziel": self.ziel, "verzeichnis": str(self.verzeichnis), "auswahl": self.auswahl,
            "dateien": [
                {"pfad": d.pfad, "modus": oct(d.modus)[2:], "beschreibung": d.beschreibung,
                 "geheim": d.geheim, "bytes": len(d.inhalt.encode()), "vorschau": d.vorschau()}
                for d in self.dateien
            ],
            "befehle": self.befehle, "hinweise": self.hinweise, "fehler": self.fehler, "url": self.url,
            "ok": self.ok, "ausfuehren": self.ausfuehrbar, "reife": [r.als_dict() for r in self.reife],
        }


# ---------------------------------------------------------------- Hilfen


def render(vorlage: str, werte: Mapping[str, str]) -> str:
    """Setzt {{name}} ein (ein Durchgang); fehlende Namen und Reste von {{ sind ein Fehler."""

    def ersetze(m: re.Match) -> str:
        if m.group(1) not in werte:
            raise KeyError(f"Vorlage verlangt unbekannten Platzhalter '{m.group(1)}'")
        return werte[m.group(1)]

    text = _PLATZHALTER.sub(ersetze, vorlage)
    if "{{" in text:
        raise ValueError("Nach dem Einsetzen bleibt '{{' im Text (Eingabe oder Vorlage enthält es)")
    return text


def _vorlage(name: str) -> str:
    return (VORLAGEN / name).read_text(encoding="utf-8")


def _yaml(daten: Any, kopf: str = "") -> str:
    return kopf + yaml.safe_dump(daten, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10**6)


def _einrueckung(text: str, n: int) -> str:
    return "\n".join(" " * n + z if z else z for z in text.rstrip("\n").splitlines())


def _literale(paare: list[tuple[str, str]], n: int) -> str:
    return _einrueckung(_yaml([f"{k}={v}" for k, v in paare]), n)


def _env_wert(wert: str) -> str:
    """Wert für eine Compose-.env: einfache Anführungszeichen schalten die Interpolation ab."""
    if _SICHER_ENV.match(wert):
        return wert
    if "'" not in wert:
        return f"'{wert}'"
    return '"' + wert.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def _bild_teilen(bild: str) -> tuple[str, str]:
    name, tag = bild, "latest"
    if ":" in bild.rsplit("/", 1)[-1]:
        name, tag = bild.rsplit(":", 1)
    return name, tag


def vorgabe_k8s_basis(verzeichnis: Path) -> str:
    """Relativer Pfad auf deploy/k8s/base, wenn der Installer aus einem Checkout läuft, sonst eine Git-Vorlage."""
    lokal = PAKET.parent.parent / "deploy" / "k8s" / "base"
    if lokal.is_dir():
        return Path(os.path.relpath(lokal, Path(verzeichnis).resolve())).as_posix()
    return "https://git.example.com/fyos/fyos-os//deploy/k8s/base?ref=main"


def lade_antworten(pfad: str | Path) -> dict[str, Any]:
    try:
        daten = yaml.safe_load(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"{pfad}: Antworten nicht lesbar ({e})") from e
    if daten is None:
        return {}
    if not isinstance(daten, dict):
        raise ValueError(f"{pfad}: Antworten müssen ein Objekt sein")
    return daten


# ---------------------------------------------------------------- Eingaben prüfen


def _abschnitt(antworten: Mapping, name: str, vorgabe: Mapping, fehler: list[str]) -> dict[str, str]:
    roh = antworten.get(name) or {}
    if not isinstance(roh, dict):
        fehler.append(f"Antworten: '{name}' muss ein Objekt sein")
        roh = {}
    erg = {}
    for k, v in {**vorgabe, **{k: v for k, v in roh.items() if v is not None}}.items():
        s = str(v).strip() if not isinstance(v, (dict, list)) else ""
        if _STEUER.search(s):
            fehler.append(f"Antworten: {name}.{k} enthält Steuerzeichen oder Zeilenumbrüche")
            s = ""
        erg[k] = s
    return erg


def _feldwert(b: Baustein, f, roh: Any, fehler: list[str]) -> str:
    wert = f.standard if roh is None else roh
    s = "" if wert is None or isinstance(wert, (dict, list)) else str(wert).strip()
    ort = f"{b.titel}: Feld '{f.name}'"
    if _STEUER.search(s):
        fehler.append(f"{ort} enthält Steuerzeichen oder Zeilenumbrüche")
        return ""
    if not s:
        if f.pflicht:
            fehler.append(f"{ort} fehlt ({f.beschreibung})")
        return ""
    if f.typ == "zahl":
        if not re.fullmatch(r"\d{1,6}", s):
            fehler.append(f"{ort} muss eine ganze Zahl sein")
    elif f.typ == "url":
        if not re.match(r"^https?://[^\s/]+", s):
            fehler.append(f"{ort} muss eine Adresse mit http:// oder https:// sein")
    elif f.typ == "wahl" and s not in f.optionen:
        fehler.append(f"{ort} muss einer von {', '.join(f.optionen)} sein")
    return s


# ---------------------------------------------------------------- Plan


def erstelle_plan(
    katalog: Katalog,
    auswahl: list[str],
    ziel: str,
    antworten: Mapping[str, Any] | None = None,
    verzeichnis: str | Path = "./fyos",
    *,
    umgebung: Mapping[str, str] | None = None,
    zufall: Callable[[int], str] = secrets.token_hex,
) -> Plan:
    umgebung = os.environ if umgebung is None else umgebung
    antworten = antworten or {}
    verz = Path(verzeichnis)
    plan = Plan(ziel=ziel, verzeichnis=verz)
    fehler = plan.fehler
    if ziel not in ZIELE:
        fehler.append(f"Unbekanntes Ziel '{ziel}' (erlaubt: {', '.join(ZIELE)})")
        return plan
    try:
        plan.auswahl = aufloesen(katalog, list(auswahl))
    except KatalogFehler as e:
        fehler.append(str(e))
        return plan
    bausteine = [katalog[i] for i in plan.auswahl]
    plan.reife = bestimme_reife(bausteine)

    persona = _abschnitt(antworten, "persona", VORGABE_PERSONA, fehler)
    modell = _abschnitt(antworten, "modell", VORGABE_MODELL, fehler)
    optionen = _abschnitt(antworten, "optionen", vorgaben_optionen(umgebung), fehler)
    optionen["bezug"] = _auto_bezug(optionen)
    geheimnisse = _abschnitt(antworten, "geheimnisse", {"agent_token": ""}, fehler)
    for k in ("agent_name", "besitzer_name", "sprache"):
        if not persona[k]:
            fehler.append(f"Persona: '{k}' darf nicht leer sein")
    if not modell["basis_url"] or not re.match(r"^https?://", modell["basis_url"]):
        fehler.append("Modell: basis_url muss mit http:// oder https:// beginnen")
    if not modell["name"]:
        fehler.append("Modell: name darf nicht leer sein")
    for k in ("hub_bild", "bild_web", "bild_agent"):
        if not _BILD.match(optionen[k]):
            fehler.append(f"Optionen: {k} ist kein gültiger Bildname")
    if optionen["paketindex"] and not _INDEX.match(optionen["paketindex"]):
        fehler.append("Optionen: paketindex muss eine http(s)-Adresse ohne Leer- und Sonderzeichen sein")
    if ziel == "k8s":
        if not _BILD.match(optionen["hub_bild_k8s"]):
            fehler.append("Optionen: hub_bild_k8s ist kein gültiger Bildname")
        if not _NAMESPACE.match(optionen["namespace"]):
            fehler.append("Optionen: namespace ist kein gültiger Kubernetes-Name")

    # Plugin-Pakete für das Hub-Bild
    for b in bausteine:
        try:
            spec = quelle_aufloesen(b, optionen["bezug"], optionen["plugin_quelle"], optionen["paketindex"])
        except KatalogFehler as e:
            if not any(str(e).split(":", 1)[-1] == x.split(":", 1)[-1] for x in fehler):
                fehler.append(str(e))
            continue
        if spec:
            if not _SPEC.match(spec):
                fehler.append(f"{b.titel}: Paketquelle enthält unzulässige Zeichen")
            else:
                plan.hub_quellen.append(spec)

    # Felder der Bausteine: ENV-Name -> (Wert, geheim, Baustein)
    felder_roh = antworten.get("felder") or {}
    if not isinstance(felder_roh, dict):
        fehler.append("Antworten: 'felder' muss ein Objekt sein")
        felder_roh = {}
    for bid in felder_roh:
        if bid not in plan.auswahl:
            plan.hinweise.append(f"Antworten für nicht gewählten Baustein '{bid}' werden ignoriert.")
    werte: dict[str, tuple[str, bool, Baustein]] = {}
    for b in bausteine:
        mein = felder_roh.get(b.id) or {}
        if not isinstance(mein, dict):
            fehler.append(f"Antworten: felder.{b.id} muss ein Objekt sein")
            mein = {}
        for name in mein:
            if name not in {f.name for f in b.konfiguration}:
                plan.hinweise.append(f"Unbekanntes Feld '{name}' bei '{b.id}' wird ignoriert.")
        for f in b.konfiguration:
            wert = _feldwert(b, f, mein.get(f.name), fehler)
            env = b.umgebungsname(f)
            if env in werte:
                fehler.append(f"Umgebungsvariable {env} wird von mehreren Feldern belegt")
            werte[env] = (wert, f.typ == "geheim", b)

    port = werte.get("FYOS_PORT", ("8080", False, None))[0] or "8080"
    oeff = werte.get("FYOS_OEFFENTLICH_URL", ("", False, None))[0]
    if not oeff or (oeff == STANDARD_URL and port != "8080"):
        oeff = f"http://localhost:{port}"
    if port.isdigit():
        plan.port = int(port)
        if not 1 <= plan.port <= 65535:
            fehler.append("Kern: port muss zwischen 1 und 65535 liegen")
    werte["FYOS_PORT"] = (port, False, werte.get("FYOS_PORT", (0, 0, None))[2])
    werte["FYOS_OEFFENTLICH_URL"] = (oeff, False, werte.get("FYOS_OEFFENTLICH_URL", (0, 0, None))[2])

    if fehler:
        return plan

    token = geheimnisse["agent_token"] or zufall(24)
    try:
        _dateien(katalog, plan, bausteine, persona, modell, optionen, werte, token, verz)
    except (KeyError, ValueError) as e:
        plan.dateien.clear()
        fehler.append(str(e))
    return plan


def _ziel_text(ziel: str) -> str:
    return ZIELE[ziel]


def _dateien(katalog, plan, bausteine, persona, modell, optionen, werte, token, verz) -> None:
    ziel = plan.ziel
    oeff = werte["FYOS_OEFFENTLICH_URL"][0]
    port = werte["FYOS_PORT"][0]
    plugin_paare = [(e, w, g, b) for e, (w, g, b) in werte.items() if w and e not in RESERVIERT]

    # fyos.yaml (Persona-Schema: fyos-agent/fyos.example.yaml)
    sprache_code = SPRACHCODES.get(persona["sprache"].lower(), "en")
    fyos = {
        "agent": {"id": "main", "name": persona["agent_name"], "wesen": persona["wesen"]},
        "besitzer": {"name": persona["besitzer_name"]},
        "sprache": persona["sprache"],
        "sprache_code": sprache_code,
    }
    kopf = "# Persona und Grenzen des Agenten (Schema: fyos-agent/fyos.example.yaml). Vom Installer erzeugt.\n"
    fyos_text = _yaml(fyos, kopf)

    # Format des Hubs (hub/config.example.yaml): Eintrag = Entry-Point-Name, optional config/secrets/enabled.
    # Nicht gewählte Bausteine des Installer-Katalogs mit Hub-Plugin werden ausdrücklich abgeschaltet.
    plugins = [dict(p) for b in bausteine for p in b.hub_plugins]
    gewaehlt_ids = {b.id for b in bausteine}
    for b in katalog.bausteine.values():
        if b.id not in gewaehlt_ids and b.herkunft == "installer":
            plugins += [{"name": p["name"], "enabled": False} for p in b.hub_plugins]
    hub_text = _yaml(
        {"plugins": plugins},
        "# Hub-Plugins (Format: hub/config.example.yaml). Installierte Plugin-Pakete laden auch ohne Eintrag.\n"
        "# Vom Installer erzeugt.\n",
    )

    paket_zeilen = ""
    if plan.hub_quellen:
        paket_zeilen += "# Das Hub-Bild läuft als Benutzer fyos; zum Installieren kurz root.\nUSER root\n"
        paket_zeilen += (
            "# uv statt pip: Es fragt die Indizes der Reihe nach und nimmt ein Paket nur aus dem ersten Index, der es führt.\n"
            f"COPY --from={UV_BILD} /uv /uvx /bin/\n"
        )
        if any("git+" in s for s in plan.hub_quellen):
            paket_zeilen += (
                "# Pakete aus Git-Adressen brauchen git im Bild.\n"
                "RUN command -v git >/dev/null 2>&1 || (apt-get update && "
                "apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*)\n"
            )
        paket_zeilen += (
            "# Der eigene Paketindex kommt als Bau-Argument und steht vor PyPI: --build-arg FYOS_INDEX_URL=<Index-URL>\n"
            "RUN uv pip install --system --no-cache --index-strategy first-index "
            '${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} '
            + " ".join(f'"{s}"' for s in plan.hub_quellen) + "\nUSER fyos\n"
        )
    else:
        paket_zeilen = "# Keine Plugin-Pakete gewählt: das Bild entspricht dem Hub der Distribution.\n"
    dockerfile = render(
        _vorlage("Dockerfile.hub"), {"hub_bild": optionen["hub_bild"], "paket_zeilen": paket_zeilen.rstrip("\n")}
    )

    gitignore = "# Geheimnisse und Sicherungen nie einchecken\n.env\nsecrets.yaml\n*.vorher\n"

    if ziel in ("compose", "dateien"):
        abschnitte: list[tuple[str, list[tuple[str, str, bool]]]] = [
            ("Allgemein", [("FYOS_PORT", port, False), ("FYOS_OEFFENTLICH_URL", oeff, False)]),
            ("Bilder und Paketbezug", [
                ("FYOS_BILD_WEB", optionen["bild_web"], False),
                ("FYOS_BILD_AGENT", optionen["bild_agent"], False),
                ("FYOS_PAKETINDEX", optionen["paketindex"] if optionen["bezug"] == "index" else "", False),
            ]),
            ("Modell (jeder OpenAI-kompatible Anbieter)", [
                ("FYOS_MODELL_BASIS_URL", modell["basis_url"], False),
                ("FYOS_MODELL_NAME", modell["name"], False),
                ("FYOS_MODELL_SCHLUESSEL", modell["schluessel"], True),
            ]),
            ("Agent-Gateway", [("FYOS_AGENT_TOKEN", token, True)]),
        ]
        for b in bausteine:
            felder = [(e, w, g) for e, w, g, bb in plugin_paare if bb is b]
            if felder:
                abschnitte.append((b.titel, felder))

        def env_text(maskiert: bool) -> str:
            zeilen = [
                "# Vom FYOS-Installer erzeugt. Enthält Geheimnisse: nicht weitergeben, nicht ins Git.",
            ]
            for titel, paare in abschnitte:
                zeilen += ["", f"# {titel}"]
                for k, v, g in paare:
                    zeilen.append(f"{k}={'***' if (g and maskiert and v) else _env_wert(v)}")
            return "\n".join(zeilen) + "\n"

        hub_umgebung = "\n".join(
            f"      {e}: ${{{e}:-}}" for e, _w, _g, _b in plugin_paare
        )
        compose = render(
            _vorlage("docker-compose.yml"), {"oeffentliche_url": oeff, "hub_umgebung": hub_umgebung}
        )
        plan.dateien += [
            Datei("docker-compose.yml", compose, beschreibung="Dienste web, hub (eigenes Bild), agent, redis"),
            Datei(".env", env_text(False), 0o600, "Port, Modell, Gateway-Token und Plugin-Felder (Geheimnisse nur hier)", env_text(True)),
            Datei("fyos.yaml", fyos_text, beschreibung="Persona des Agenten"),
            Datei("hub-config.yaml", hub_text, beschreibung="Kern-Plugins des Hubs"),
            Datei("hub/Dockerfile", dockerfile, beschreibung="Hub-Bild plus gewählte Plugin-Pakete"),
            Datei(".gitignore", gitignore, beschreibung="hält .env aus dem Git"),
        ]
        plan.url = oeff
        d = shlex.quote(str(plan.verzeichnis))
        plan.befehle = [f"cd {d}", "docker compose build", "docker compose up -d"]
        schritte = [
            f"1. `cd {d}`",
            "2. `docker compose build` baut das Hub-Bild mit den gewählten Plugin-Paketen.",
            "3. `docker compose up -d` startet FYOS.",
            f"4. {oeff} im Browser öffnen.",
            "5. Beenden mit `docker compose down`.",
        ]
        geheimdatei, protokoll = ".env", "docker compose logs"
    else:  # k8s
        basis = optionen["k8s_basis"] or vorgabe_k8s_basis(plan.verzeichnis)
        if Path(basis).is_absolute():  # kustomize nimmt nur relative Pfade oder Git-Adressen
            basis = Path(os.path.relpath(basis, Path(plan.verzeichnis).resolve())).as_posix()
        bild_name, bild_tag = _bild_teilen(optionen["hub_bild_k8s"])
        web_name, web_tag = _bild_teilen(optionen["bild_web"])
        agent_name, agent_tag = _bild_teilen(optionen["bild_agent"])
        host = urlparse(oeff).hostname or "localhost"
        ns = optionen["namespace"]
        literale = _literale(
            [("oeffentlich_url", oeff), ("erlaubte_hosts", host)], 6
        )
        plugin_lit = _literale(
            [("FYOS_PLUGIN_UMGEBUNG", "installer")] + [(e, w) for e, w, g, _b in plugin_paare if not g], 6
        )
        kust = render(_vorlage("kustomization.yaml"), {
            "namespace": ns, "k8s_basis": json.dumps(basis), "umgebung_literale": literale,
            "plugin_literale": plugin_lit, "hub_bild_name": json.dumps(bild_name), "hub_bild_tag": json.dumps(bild_tag),
            "web_name": json.dumps(web_name), "web_tag": json.dumps(web_tag),
            "agent_name": json.dumps(agent_name), "agent_tag": json.dumps(agent_tag),
            **{f"{k}_basis": json.dumps(v) for k, v in BASIS_BILDNAMEN.items()},
        })

        def secrets_text(echt: bool) -> str:
            def wert(v: str) -> str:
                return v if echt else "<ausfüllen>"

            dokumente = [
                {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "fyos-modell", "namespace": ns},
                 "type": "Opaque",
                 "stringData": {"basis_url": modell["basis_url"], "name": modell["name"],
                                "schluessel": wert(modell["schluessel"])}},
                {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "fyos-agent-gateway", "namespace": ns},
                 "type": "Opaque", "stringData": {"token": wert(token)}},
            ]
            geheim = {e: wert(w) for e, w, g, _b in plugin_paare if g}
            if geheim:
                dokumente.append({"apiVersion": "v1", "kind": "Secret",
                                  "metadata": {"name": "fyos-plugin", "namespace": ns},
                                  "type": "Opaque", "stringData": geheim})
            kopf = ("# Vom FYOS-Installer erzeugt.\n" + (
                "# ENTHÄLT GEHEIMNISSE: nicht ins Git, nicht weitergeben.\n" if echt else
                "# Vorlage ohne Werte. Als secrets.yaml kopieren und ausfüllen.\n"))
            return kopf + "---\n".join(_yaml(d) for d in dokumente)

        echt = secrets_text(True)
        plan.dateien += [
            Datei("kustomization.yaml", kust, beschreibung="Overlay: Basis, ConfigMaps, Hub-Bild"),
            Datei("fyos.yaml", fyos_text, beschreibung="Persona des Agenten (ConfigMap fyos-agent-config)"),
            Datei("hub-config.yaml", hub_text, beschreibung="Kern-Plugins (ConfigMap fyos-hub-config)"),
            Datei("secrets.yaml", echt, 0o600, "Secrets mit Modellzugang, Gateway-Token, Plugin-Geheimnissen", secrets_text(False).replace(
                "Vorlage ohne Werte. Als secrets.yaml kopieren und ausfüllen.", "Anzeige ohne Geheimnisse.")),
            Datei("secrets.example.yaml", secrets_text(False), beschreibung="dieselben Secrets als Vorlage ohne Werte"),
            Datei("hub/Dockerfile", dockerfile, beschreibung="Hub-Bild plus gewählte Plugin-Pakete"),
            Datei(".gitignore", gitignore, beschreibung="hält secrets.yaml aus dem Git"),
        ]
        d = shlex.quote(str(plan.verzeichnis))
        arg = ""
        if optionen["bezug"] == "index" and optionen["paketindex"]:
            arg = "--build-arg " + shlex.quote("FYOS_INDEX_URL=" + optionen["paketindex"]) + " "
        bau = f"docker build {arg}-t {optionen['hub_bild_k8s']} hub"
        plan.befehle = [
            f"cd {d}",
            bau,
            f"docker push {optionen['hub_bild_k8s']}",
            f"kubectl create namespace {ns}",
            "kubectl apply -f secrets.yaml",
            "kubectl apply -k .",
        ]
        schritte = [
            f"1. `cd {d}`",
            f"2. Hub-Bild bauen und in deine Registry schieben: `{bau}` und `docker push {optionen['hub_bild_k8s']}`.",
            f"3. `kubectl create namespace {ns}`, dann `kubectl apply -f secrets.yaml`.",
            "4. `kubectl apply -k .` legt FYOS an (zur Kontrolle vorher `kubectl kustomize .`).",
            f"5. Zugriff zum Ausprobieren: `kubectl -n {ns} port-forward svc/web {port}:80`, dann {oeff} öffnen.",
        ]
        plan.url = None
        geheimdatei, protokoll = "secrets.yaml", f"kubectl -n {ns} logs deploy/hub"
        plan.hinweise.append(
            f"Kustomize-Basis: {basis} (mit `k8s_basis` in den Antworten änderbar). Der Pfad ist relativ zum Zielordner."
        )
        if "host.docker.internal" in modell["basis_url"]:
            plan.hinweise.append("Die Modell-Adresse zeigt auf host.docker.internal; im Cluster ist sie so nicht erreichbar.")

    if ziel == "dateien":
        plan.hinweise.append("Ziel »nur Dateien«: nichts wird gestartet; die Befehle stehen in ANLEITUNG.md.")
    bild_felder = ("hub_bild", "bild_web", "bild_agent") + (("hub_bild_k8s",) if ziel == "k8s" else ())
    beispiel = [k for k in bild_felder if optionen[k].startswith(BEISPIEL_REGISTRY + "/")]
    if beispiel:
        plan.hinweise.append(
            f"Bilder ({', '.join(beispiel)}) zeigen noch auf die Beispieladresse {BEISPIEL_REGISTRY}: "
            "FYOS_REGISTRY auf die eigene Registry setzen (Form host/besitzer) oder die Bilder unter Optionen "
            "eintragen, sonst lässt sich nichts ziehen."
        )
    for b in bausteine:
        for v in b.voraussetzungen:
            plan.hinweise.append(f"Voraussetzung ({b.titel}): {v}")
    plan.hinweise.append(abnahme.hinweis(plan.port, ziel))

    anleitung = render(_vorlage("ANLEITUNG.md"), {
        "ziel_text": _ziel_text(ziel),
        "agent_name": persona["agent_name"], "besitzer_name": persona["besitzer_name"], "sprache": persona["sprache"],
        "bausteine": "\n".join(f"- **{b.titel}**: {b.kurz}" for b in bausteine),
        "schritte": "\n".join(schritte),
        "dateien": "\n".join(f"- `{x.pfad}`: {x.beschreibung}" for x in plan.dateien + [Datei("ANLEITUNG.md", "", beschreibung="diese Datei")]),
        "geheimdatei": geheimdatei, "protokoll_befehl": f"`{protokoll}`",
        "hinweise": "\n".join(f"- {h}" for h in plan.hinweise),
    })
    plan.dateien.append(Datei("ANLEITUNG.md", anleitung, beschreibung="nächste Schritte"))


# ---------------------------------------------------------------- Schreiben


def schreiben(plan: Plan) -> list[Path]:
    """Legt die Dateien an. Vorhandene Dateien wandern nach `<name>.vorher`. Rechte werden von Anfang an gesetzt."""
    if not plan.ok:
        raise ValueError("Plan hat Fehler: " + "; ".join(plan.fehler))
    wurzel = plan.verzeichnis
    wurzel.mkdir(parents=True, exist_ok=True)
    geschrieben = []
    for d in plan.dateien:
        ziel = wurzel / d.pfad
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if ziel.exists() or ziel.is_symlink():
            ziel.replace(ziel.with_name(ziel.name + ".vorher"))
        fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, d.modus)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(d.inhalt)
        os.chmod(ziel, d.modus)
        geschrieben.append(ziel)
    return geschrieben
