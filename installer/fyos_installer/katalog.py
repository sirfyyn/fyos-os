"""Katalog der Bausteine: Laden, Schema-Prüfung, Zusammenführen, Abhängigkeiten, Bilder.

Ein Katalog ist eine YAML-Datei mit `bausteine: [...]`. Der Katalog des Installers liegt als
`katalog.yaml` im Paket; Plugin-Pakete bringen eine `fyos-katalog.yaml` mit (Entry-Point-Gruppe
`fyos.katalog` oder Datei im Paket), fremde Kataloge kommen per `--katalog URL|DATEI`.
"""

from __future__ import annotations

import os
import re
import urllib.request
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from .reife import MAX_STUFE, SCHICHTEN

PAKET = Path(__file__).resolve().parent
BILDER = PAKET / "bilder"
STANDARD_KATALOG = PAKET / "katalog.yaml"
KANAL_KATALOG = PAKET / "katalog_kanaele.yaml"  # Chat-Kanäle des Agenten (Art `kanal`, kanaele.py)
STUFEN_KATALOG = PAKET / "katalog_stufen.yaml"  # Stufe je Fähigkeit: Grundstufe, Ausbaustufe, aus (stufen.py)
KATALOG_DATEINAME = "fyos-katalog.yaml"
ENTRY_POINT_GRUPPE = "fyos.katalog"

ARTEN = ("kern", "agent", "plugin", "kanal")
FELD_TYPEN = ("text", "geheim", "url", "zahl", "wahl")
BILD_ENDUNGEN = (".png", ".webp", ".jpg", ".jpeg", ".svg")  # Rangfolge: Screenshot vor Skizze
BILD_TYPEN = {
    ".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}
MAX_KATALOG_BYTES = 1_000_000

_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_FELDNAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_UMGEBUNG = re.compile(r"^[A-Z][A-Z0-9_]{0,60}$")
_PAKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_BILDNAME =re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class KatalogFehler(ValueError):
    """Der Katalog verstößt gegen das Schema oder ist nicht lesbar."""


@dataclass
class Feld:
    name: str
    typ: str
    titel: str = ""
    beschreibung: str = ""
    standard: Any = ""
    pflicht: bool = False
    optionen: list[str] = field(default_factory=list)
    umgebung: str = ""


@dataclass
class Baustein:
    id: str
    titel: str
    kurz: str
    was_daraus_wird: str
    art: str
    pflicht: bool = False
    bilder: list[str] = field(default_factory=list)
    abhaengig_von: list[str] = field(default_factory=list)
    voraussetzungen: list[str] = field(default_factory=list)
    paket: str | None = None  # Paketname im Paketindex (zum Beispiel fyos-plugin-finanzen)
    repo: str | None = None  # Name des Git-Repos unter der Plugin-Quelle
    konfiguration: list[Feld] = field(default_factory=list)
    hub_plugins: list[dict[str, Any]] = field(default_factory=list)  # Einträge der hub-config: name, config, secrets, enabled
    reife: dict[str, int] = field(default_factory=dict)  # Schicht -> Stufe, die der Baustein erreicht (reife.py)
    herkunft: str = "installer"
    bilder_verzeichnis: Path | None = None

    def umgebungsname(self, f: Feld) -> str:
        return f.umgebung or f"FYOS_{self.id.upper()}_{f.name.upper()}"


class Katalog:
    def __init__(self, bausteine: list[Baustein], plugin_quelle_beispiel: str = ""):
        """Gleiche id in verschiedenen Katalogen: der spätere gewinnt (Plugin mit eigenen Bildern, `--katalog`),
        in `hinweise` vermerkt. Gleiche id im selben Katalog ist ein Fehler."""
        self.bausteine: dict[str, Baustein] = {}
        self.hinweise: list[str] = []
        self.faehigkeiten: dict[str, Any] = {}  # id -> stufen.Faehigkeit; füllt stufen.verbinde (lade_standard)
        for b in bausteine:
            alt = self.bausteine.get(b.id)
            if alt is not None:
                if alt.herkunft == b.herkunft:
                    raise KatalogFehler(f"Baustein '{b.id}' kommt doppelt vor ({b.herkunft})")
                self.hinweise.append(f"Baustein '{b.id}' aus {alt.herkunft} wird durch den aus {b.herkunft} ersetzt")
                if alt.reife and not b.reife:  # nennt der Ersatz keinen Reifegrad, gilt der des Ersetzten weiter
                    b.reife = dict(alt.reife)
            self.bausteine[b.id] = b
        self.plugin_quelle_beispiel = plugin_quelle_beispiel
        _pruefe_verweise(self)

    def __iter__(self):
        return iter(self.bausteine.values())

    def __getitem__(self, id_: str) -> Baustein:
        try:
            return self.bausteine[id_]
        except KeyError:
            raise KatalogFehler(f"Unbekannter Baustein: '{id_}'") from None

    def __contains__(self, id_: str) -> bool:
        return id_ in self.bausteine


# ---------------------------------------------------------------- Schema


def _text(d: dict, key: str, ort: str, fehler: list[str], leer_ok: bool = False) -> str:
    wert = d.get(key)
    if not isinstance(wert, str) or (not leer_ok and not wert.strip()):
        fehler.append(f"{ort}: '{key}' muss ein nichtleerer Text sein")
        return ""
    return wert


def _liste_text(d: dict, key: str, ort: str, fehler: list[str]) -> list[str]:
    wert = d.get(key, [])
    if wert is None:
        return []
    if not isinstance(wert, list) or not all(isinstance(x, str) and x.strip() for x in wert):
        fehler.append(f"{ort}: '{key}' muss eine Liste von Texten sein")
        return []
    return list(wert)


def _feld(roh: Any, ort: str, fehler: list[str]) -> Feld | None:
    if not isinstance(roh, dict):
        fehler.append(f"{ort}: Feld muss ein Objekt sein")
        return None
    name = roh.get("name")
    if not isinstance(name, str) or not _FELDNAME.match(name):
        fehler.append(f"{ort}: Feldname fehlt oder ist ungültig ({name!r})")
        return None
    ort = f"{ort}.{name}"
    typ = roh.get("typ", "text")
    if typ not in FELD_TYPEN:
        fehler.append(f"{ort}: typ muss einer von {', '.join(FELD_TYPEN)} sein")
        return None
    optionen = roh.get("optionen", [])
    if typ == "wahl" and (not isinstance(optionen, list) or not optionen or not all(isinstance(o, str) for o in optionen)):
        fehler.append(f"{ort}: Typ 'wahl' braucht eine Liste 'optionen'")
        optionen = []
    pflicht = roh.get("pflicht", False)
    if not isinstance(pflicht, bool):
        fehler.append(f"{ort}: 'pflicht' muss wahr oder falsch sein")
        pflicht = False
    umgebung = roh.get("umgebung", "") or ""
    if umgebung and not _UMGEBUNG.match(str(umgebung)):
        fehler.append(f"{ort}: 'umgebung' muss ein Umgebungsvariablenname in Großbuchstaben sein")
        umgebung = ""
    standard = roh.get("standard", "")
    if standard is None:
        standard = ""
    if typ == "zahl" and standard != "" and (isinstance(standard, bool) or not isinstance(standard, (int, float))):
        fehler.append(f"{ort}: 'standard' muss bei Typ 'zahl' eine Zahl sein")
    titel = roh.get("titel")
    if not isinstance(titel, str) or not titel.strip():
        fehler.append(f"{ort}: 'titel' (Beschriftung des Feldes) fehlt")
        return None
    return Feld(
        name=name, typ=typ, titel=titel.strip(), beschreibung=str(roh.get("beschreibung", "") or ""), standard=standard,
        pflicht=pflicht, optionen=[str(o) for o in optionen], umgebung=str(umgebung),
    )


def _reife(roh: Any, ort: str, fehler: list[str]) -> dict[str, int]:
    """`reife: {schicht: stufe}`: welche Stufe der Baustein in welcher Schicht erreicht (reife.py). Optional."""
    if roh is None:
        return {}
    if not isinstance(roh, dict):
        fehler.append(f"{ort}: 'reife' muss ein Objekt aus Schicht und Stufe sein")
        return {}
    erg: dict[str, int] = {}
    for schicht, stufe in roh.items():
        if schicht not in SCHICHTEN:
            fehler.append(f"{ort}: reife.{schicht}: unbekannte Schicht (erlaubt: {', '.join(SCHICHTEN)})")
        elif isinstance(stufe, bool) or not isinstance(stufe, int) or not 1 <= stufe <= MAX_STUFE:
            fehler.append(f"{ort}: reife.{schicht} muss eine ganze Zahl von 1 bis {MAX_STUFE} sein")
        else:
            erg[schicht] = stufe
    return erg


def _bildname_ok(name: str) -> bool:
    return bool(_BILDNAME.match(name)) and ".." not in name and Path(name).suffix.lower() in BILD_TYPEN


def _baustein(roh: Any, nr: int, herkunft: str, basis: Path | None, fehler: list[str]) -> Baustein | None:
    if not isinstance(roh, dict):
        fehler.append(f"{herkunft}: Eintrag {nr} muss ein Objekt sein")
        return None
    id_ = roh.get("id")
    if not isinstance(id_, str) or not _ID.match(id_):
        fehler.append(f"{herkunft}: Eintrag {nr}: 'id' fehlt oder ist ungültig ({id_!r})")
        return None
    ort = f"{herkunft}: {id_}"
    n0 = len(fehler)
    titel = _text(roh, "titel", ort, fehler)
    kurz = _text(roh, "kurz", ort, fehler)
    if "\n" in kurz.strip():
        fehler.append(f"{ort}: 'kurz' darf nur eine Zeile sein")
    was = _text(roh, "was_daraus_wird", ort, fehler)
    art = roh.get("art")
    if art not in ARTEN:
        fehler.append(f"{ort}: 'art' muss einer von {', '.join(ARTEN)} sein")
    pflicht = roh.get("pflicht", False)
    if not isinstance(pflicht, bool):
        fehler.append(f"{ort}: 'pflicht' muss wahr oder falsch sein")
        pflicht = False
    bilder = _liste_text(roh, "bilder", ort, fehler)
    for b in bilder:
        if not _bildname_ok(b):
            fehler.append(f"{ort}: Bildname '{b}' ist ungültig (nur Dateiname mit .svg/.png/.jpg/.webp)")
    abh = _liste_text(roh, "abhaengig_von", ort, fehler)
    voraus = _liste_text(roh, "voraussetzungen", ort, fehler)
    paket = repo = None
    quelle = roh.get("quelle")
    if isinstance(quelle, str):
        quelle = {"paket": quelle}
    if quelle is not None:
        if not isinstance(quelle, dict) or not _PAKET.match(str(quelle.get("paket", ""))) \
                or not _PAKET.match(str(quelle.get("repo", quelle.get("paket", "")))):
            fehler.append(f"{ort}: 'quelle' braucht paket (Paketname) und optional repo (Git-Repo-Name)")
        else:
            paket = str(quelle["paket"])
            repo = str(quelle.get("repo", paket))
    felder_roh = roh.get("konfiguration", []) or []
    felder: list[Feld] = []
    if not isinstance(felder_roh, list):
        fehler.append(f"{ort}: 'konfiguration' muss eine Liste sein")
        felder_roh = []
    for f in felder_roh:
        feld = _feld(f, ort, fehler)
        if feld:
            felder.append(feld)
    namen = [f.name for f in felder]
    if len(set(namen)) != len(namen):
        fehler.append(f"{ort}: Feldnamen kommen doppelt vor")
    hub = roh.get("hub_plugins", []) or []
    if not isinstance(hub, list) or not all(
        isinstance(h, dict) and isinstance(h.get("name"), str) and h["name"]
        and isinstance(h.get("config", {}), dict) and isinstance(h.get("secrets", []), list)
        and isinstance(h.get("enabled", True), bool)
        for h in hub
    ):
        fehler.append(f"{ort}: 'hub_plugins' braucht je Eintrag name (optional config, secrets, enabled)")
        hub = []
    reife = _reife(roh.get("reife"), ort, fehler)
    if len(fehler) > n0:
        return None
    return Baustein(
        id=id_, titel=titel.strip(), kurz=kurz.strip(), was_daraus_wird=was.strip(), art=art, pflicht=pflicht,
        bilder=bilder, abhaengig_von=abh, voraussetzungen=voraus, paket=paket, repo=repo,
        konfiguration=felder, hub_plugins=[{k: h[k] for k in ("name", "config", "secrets", "enabled") if k in h} for h in hub],
        reife=reife, herkunft=herkunft, bilder_verzeichnis=basis,
    )


def parse(daten: Any, herkunft: str = "katalog", bilder_verzeichnis: Path | None = None) -> list[Baustein]:
    """Prüft ein geladenes YAML-Objekt und liefert die Bausteine. Wirft KatalogFehler mit allen Befunden."""
    fehler: list[str] = []
    if not isinstance(daten, dict):
        raise KatalogFehler(f"{herkunft}: Katalog muss ein Objekt mit 'bausteine' sein")
    roh = daten.get("bausteine")
    if not isinstance(roh, list) or not roh:
        raise KatalogFehler(f"{herkunft}: 'bausteine' muss eine nichtleere Liste sein")
    ergebnis = []
    for nr, eintrag in enumerate(roh, 1):
        b = _baustein(eintrag, nr, herkunft, bilder_verzeichnis, fehler)
        if b:
            ergebnis.append(b)
    ids = [b.id for b in ergebnis]
    for i in {x for x in ids if ids.count(x) > 1}:
        fehler.append(f"{herkunft}: id '{i}' kommt doppelt vor")
    if fehler:
        raise KatalogFehler("\n".join(fehler))
    return ergebnis


def _pruefe_verweise(katalog: Katalog) -> None:
    fehler = []
    for b in katalog:
        for a in b.abhaengig_von:
            if a not in katalog.bausteine:
                fehler.append(f"{b.id}: abhaengig_von verweist auf unbekannten Baustein '{a}'")
            if a == b.id:
                fehler.append(f"{b.id}: hängt von sich selbst ab")
    if fehler:
        raise KatalogFehler("\n".join(fehler))
    # Zyklen: aufloesen() über alle Bausteine wirft bei einem Kreis.
    aufloesen(katalog, list(katalog.bausteine), mit_pflicht=False)


# ---------------------------------------------------------------- Laden


def lade_datei(pfad: str | Path, herkunft: str | None = None) -> list[Baustein]:
    pfad = Path(pfad)
    try:
        if pfad.stat().st_size > MAX_KATALOG_BYTES:
            raise KatalogFehler(f"{pfad}: Katalog ist zu groß")
        daten = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise KatalogFehler(f"{pfad}: nicht lesbar ({e})") from e
    ordner = pfad.resolve().parent
    bilder = ordner / "bilder" if (ordner / "bilder").is_dir() else ordner
    return parse(daten, herkunft or str(pfad), bilder)


def lade_url(url: str) -> list[Baustein]:
    if not url.startswith(("https://", "http://")):
        raise KatalogFehler(f"{url}: nur http(s)-Adressen")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310 - Schema oben geprüft
            roh = r.read(MAX_KATALOG_BYTES + 1)
        if len(roh) > MAX_KATALOG_BYTES:
            raise KatalogFehler(f"{url}: Katalog ist zu groß")
        daten = yaml.safe_load(roh.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise KatalogFehler(f"{url}: nicht ladbar ({e})") from e
    return parse(daten, url, None)  # entfernte Kataloge bringen keine Bilder mit


def lade_quelle(quelle: str) -> list[Baustein]:
    """`--katalog`: URL oder Datei."""
    if quelle.startswith(("https://", "http://")):
        return lade_url(quelle)
    return lade_datei(quelle)


def _ep_inhalt(wert: Any, herkunft: str) -> list[Baustein]:
    if callable(wert):
        wert = wert()
    if isinstance(wert, (str, os.PathLike)):
        return lade_datei(wert, herkunft)
    if isinstance(wert, dict):
        return parse(wert, herkunft, None)
    raise KatalogFehler(f"{herkunft}: Entry-Point liefert weder Pfad noch Katalog")


def plugin_kataloge() -> list[Baustein]:
    """Kataloge installierter Pakete: Entry-Point-Gruppe `fyos.katalog`, sonst Datei `fyos-katalog.yaml` im Paket."""
    gefunden: list[Baustein] = []
    gesehen: set[str] = set()
    for ep in metadata.entry_points(group=ENTRY_POINT_GRUPPE):
        herkunft = f"{ep.dist.name if ep.dist else '?'}:{ep.name}"
        gefunden += _ep_inhalt(ep.load(), herkunft)
        if ep.dist:
            gesehen.add(ep.dist.name)
    for dist in metadata.distributions():
        name = dist.metadata["Name"] or ""
        if name in gesehen or not name.startswith("fyos-plugin-"):
            continue
        for datei in dist.files or []:
            if datei.name == KATALOG_DATEINAME:
                gefunden += lade_datei(Path(str(dist.locate_file(datei))), name)
                break
    return gefunden


def lade_standard(extra: list[str] | None = None, plugins: bool = True) -> Katalog:
    """Katalog des Installers, dazu Kataloge installierter Plugins und die Quellen aus `--katalog`."""
    daten = yaml.safe_load(STANDARD_KATALOG.read_text(encoding="utf-8"))
    bausteine = parse(daten, "installer", BILDER)
    bausteine += parse(yaml.safe_load(KANAL_KATALOG.read_text(encoding="utf-8")), "installer", BILDER)
    if plugins:
        bausteine += plugin_kataloge()
    for q in extra or []:
        bausteine += lade_quelle(q)
    katalog = Katalog(bausteine, str(daten.get("plugin_quelle_beispiel", "")))
    from . import stufen  # erst hier: stufen.py baut auf diesem Modul auf

    stufen.verbinde(katalog, stufen.lade_datei(STUFEN_KATALOG))
    return katalog


# ---------------------------------------------------------------- Auflösung


def aufloesen(katalog: Katalog, auswahl: list[str], mit_pflicht: bool = True) -> list[str]:
    """Auswahl samt Pflichtbausteinen und Abhängigkeiten, Abhängigkeiten zuerst (Katalogreihenfolge sonst)."""
    gewuenscht = list(auswahl)
    if mit_pflicht:
        gewuenscht = [b.id for b in katalog if b.pflicht] + gewuenscht
    for g in gewuenscht:
        katalog[g]  # unbekannte ids melden
    ergebnis: list[str] = []
    zustand: dict[str, int] = {}  # 1 = in Arbeit, 2 = fertig

    def besuche(id_: str, pfad: list[str]) -> None:
        if zustand.get(id_) == 2:
            return
        if zustand.get(id_) == 1:
            raise KatalogFehler("Zyklus in abhaengig_von: " + " -> ".join(pfad + [id_]))
        zustand[id_] = 1
        for a in katalog[id_].abhaengig_von:
            besuche(a, pfad + [id_])
        zustand[id_] = 2
        ergebnis.append(id_)

    reihenfolge = {b.id: i for i, b in enumerate(katalog)}
    for g in sorted(set(gewuenscht), key=lambda x: reihenfolge[x]):
        besuche(g, [])
    return ergebnis


def abhaengige_von(katalog: Katalog, id_: str) -> list[str]:
    """Alle Bausteine, die (auch indirekt) von `id_` abhängen; nützlich beim Abwählen."""
    ergebnis = []
    for b in katalog:
        if b.id != id_ and id_ in aufloesen(katalog, [b.id], mit_pflicht=False):
            ergebnis.append(b.id)
    return ergebnis


# ---------------------------------------------------------------- Bilder, Quellen


def bilder_von(baustein: Baustein) -> list[Path]:
    """Vorhandene Bilddateien: je gelisteter Name der beste vorhandene Bruder (png vor svg)."""
    basis = baustein.bilder_verzeichnis
    if basis is None:
        return []
    ergebnis: list[Path] = []
    for name in baustein.bilder:
        stamm = Path(name).stem
        for endung in BILD_ENDUNGEN:
            p = basis / (stamm + endung)
            if p.is_file():
                ergebnis.append(p)
                break
    return ergebnis


def svg_beschreibung(pfad: Path) -> tuple[str, str, list[str]]:
    """(Titel, Beschreibung, sichtbare Texte) einer SVG-Skizze für die Textvorschau."""
    try:
        text = Path(pfad).read_text(encoding="utf-8")
    except OSError:
        return ("", "", [])

    def tag(name: str) -> str:
        m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", text, re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    texte = [re.sub(r"\s+", " ", t).strip() for t in re.findall(r"<text[^>]*>(.*?)</text>", text, re.S)]
    return tag("title"), tag("desc"), [t for t in texte if t]


def textvorschau(baustein: Baustein) -> str:
    """Textersatz für das erste Bild (TUI ohne Bildwidget): Beschreibung der Skizze samt Pfad."""
    bilder = bilder_von(baustein)
    if not bilder:
        return "(kein Bild vorhanden)"
    bild = bilder[0]
    zeilen = []
    if bild.suffix.lower() == ".svg":
        titel, beschreibung, texte = svg_beschreibung(bild)
        zeilen.append(titel or f"Skizze zu {baustein.titel}")
        if beschreibung:
            zeilen.append(beschreibung)
        if texte:
            zeilen.append("Beschriftungen: " + " · ".join(texte[:12]))
    else:
        zeilen.append(f"Bild zu {baustein.titel}")
    zeilen.append(f"Datei: {bild}")
    if len(bilder) > 1:
        zeilen.append(f"(+{len(bilder) - 1} weitere Bilder im selben Ordner)")
    return "\n".join(zeilen)


def quelle_aufloesen(baustein: Baustein, bezug: str = "git", plugin_quelle: str = "", paketindex: str = "") -> str | None:
    """Paketangabe des Bausteins für `uv pip install` (Schreibweise wie bei pip). `bezug` = "index" (Paketname,
    Index kommt als Bau-Argument und steht vor PyPI) oder "git" (Name @ git+<Plugin-Quelle>/<Repo>.git).
    Fehlt die nötige Angabe, wirft sie KatalogFehler."""
    if not baustein.paket:
        return None
    if bezug == "index":
        if not paketindex:
            raise KatalogFehler(
                f"Baustein '{baustein.id}' braucht einen Paketindex: Umgebungsvariable FYOS_PAKETINDEX "
                "setzen oder in den Antworten unter optionen.paketindex eintragen"
            )
        return baustein.paket
    if bezug != "git":
        raise KatalogFehler(f"Unbekannter Bezug '{bezug}' (index oder git)")
    if not plugin_quelle:
        raise KatalogFehler(
            f"Baustein '{baustein.id}' braucht eine Plugin-Quelle: Umgebungsvariable FYOS_PLUGIN_QUELLE "
            "setzen oder in den Antworten unter optionen.plugin_quelle eintragen"
        )
    return f"{baustein.paket} @ git+{plugin_quelle.rstrip('/')}/{baustein.repo}.git"
