"""Ausführen (nur Ziel Docker Compose): bauen, starten, Gesundheit prüfen. Alle Aufrufe ohne Shell."""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import abnahme as abn
from .erzeugen import Plan

Protokoll = Callable[[str], None]

HUB_PRUEFUNG = "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3)"

HINWEISE = (
    ("already allocated", "Der Port ist schon belegt. Wähle einen anderen Port (Feld »port« beim Kern) und starte neu."),
    ("address already in use", "Der Port ist schon belegt. Wähle einen anderen Port (Feld »port« beim Kern) und starte neu."),
    ("pull access denied", "Ein Bild lässt sich nicht laden. Bei privaten Registries vorher `docker login <registry>` ausführen."),
    ("unauthorized", "Ein Bild lässt sich nicht laden. Bei privaten Registries vorher `docker login <registry>` ausführen."),
    ("could not read username", "Die Plugin-Quelle verlangt Zugangsdaten. Hinterlege Git-Zugang (Token in der Quelle oder Credential Helper)."),
    ("repository not found", "Die Plugin-Quelle wurde nicht gefunden. Prüfe FYOS_PLUGIN_QUELLE und deinen Zugang."),
    ("no space left", "Auf dem Datenträger ist kein Platz mehr. `docker system prune` kann helfen."),
)


@dataclass
class Ergebnis:
    ok: bool  # FYOS läuft; die Abnahme steht daneben und ändert das nicht
    meldung: str
    url: str | None = None
    abnahme: abn.Abnahme | None = None  # nur nach einem erfolgreichen Start

    @property
    def nicht_abgenommen(self) -> bool:
        """FYOS läuft, aber die Abnahme ist nicht bestanden (eine Abnahme, die gar nicht lief, zählt hier nicht)."""
        return self.ok and self.abnahme is not None and not self.abnahme.bestanden


def docker_pruefen(
    which: Callable[[str], str | None] = shutil.which, lauf: Callable = subprocess.run
) -> tuple[bool, str]:
    """(bereit, Meldung): ist docker mit Compose vorhanden und läuft der Dienst?"""
    if not which("docker"):
        return False, "Docker wurde nicht gefunden. Installiere Docker (Desktop oder Engine) mit Compose und starte neu."
    try:
        r = lauf(["docker", "compose", "version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"`docker compose` lässt sich nicht starten ({e})."
    if r.returncode != 0:
        return False, "Das Compose-Plugin fehlt (`docker compose version` schlägt fehl). Installiere Docker Compose v2."
    try:
        r = lauf(["docker", "info"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"`docker info` lässt sich nicht ausführen ({e})."
    if r.returncode != 0:
        return False, "Docker läuft nicht. Starte Docker Desktop bzw. den Docker-Dienst und versuche es erneut."
    return True, "Docker mit Compose ist bereit."


def _lauf(argv: list[str], cwd: Path, log: Protokoll, popen: Callable = subprocess.Popen) -> tuple[int, str]:
    log("$ " + " ".join(argv))
    try:
        p = popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as e:
        log(f"Start nicht möglich: {e}")
        return 127, str(e)
    gesammelt: list[str] = []
    for zeile in p.stdout or []:
        zeile = zeile.rstrip("\n")
        gesammelt.append(zeile)
        log(zeile)
    return p.wait(), "\n".join(gesammelt[-60:])


def _hinweis(ausgabe: str) -> str:
    klein = ausgabe.lower()
    for schluessel, text in HINWEISE:
        if schluessel in klein:
            return text
    return ""


def _web_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310 - eigene lokale Adresse
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except (OSError, ValueError):
        return False


def standard_pruefer(plan: Plan, popen: Callable = subprocess.Popen) -> Callable[[], dict[str, bool]]:
    """Prüft web (`/` auf dem Host-Port) und hub (`/health` im Container)."""

    def pruefen() -> dict[str, bool]:
        hub = False
        try:
            r = subprocess.run(
                ["docker", "compose", "exec", "-T", "hub", "python", "-c", HUB_PRUEFUNG],
                cwd=plan.verzeichnis, capture_output=True, text=True, timeout=30,
            )
            hub = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            hub = False
        return {"web": _web_ok(f"http://127.0.0.1:{plan.port}/"), "hub": hub}

    return pruefen


def _abnahme(
    plan: Plan, log: Protokoll, pruefen: Callable[[str], abn.Abnahme],
    kanaele: Callable[[Plan], list[abn.Befund]] | None = None,
) -> abn.Abnahme | None:
    """Die Abnahme gegen die gerade gestartete Shell (lokaler Port), bei gewählten Chat-Kanälen dazu die Frage an den
    Agenten, ob sie aktiv sind. Sie darf den Start nie kippen."""
    try:
        ergebnis = pruefen(f"http://127.0.0.1:{plan.port}")
        if plan.kanaele:
            if kanaele is None:
                def kanaele(p: Plan) -> list[abn.Befund]:
                    return abn.kanal_proben(p.kanaele, abn.kanal_abfrage_compose(p.verzeichnis))
            ergebnis.kanaele = kanaele(plan)
    except Exception as e:  # noqa: BLE001 - ein Fehler hier ist eine Meldung, kein Abbruch der Installation
        log(f"Die Abnahme konnte nicht laufen: {e}")
        return None
    for zeile in ergebnis.zeilen():
        log(zeile)
    return ergebnis


def ausfuehren(
    plan: Plan,
    log: Protokoll,
    *,
    zeitlimit: float = 240.0,
    pruefer: Callable[[], dict[str, bool]] | None = None,
    docker: Callable[[], tuple[bool, str]] = docker_pruefen,
    popen: Callable = subprocess.Popen,
    schlaf: Callable[[float], None] = time.sleep,
    uhr: Callable[[], float] = time.monotonic,
    abnahme: Callable[[str], abn.Abnahme] | None = None,
    kanal_abnahme: Callable[[Plan], list[abn.Befund]] | None = None,
) -> Ergebnis:
    if not plan.ausfuehrbar:
        return Ergebnis(False, "Dieses Ziel wird vom Installer nicht gestartet.")
    bereit, meldung = docker()
    log(meldung)
    if not bereit:
        return Ergebnis(False, meldung)
    verz = Path(plan.verzeichnis)
    for titel, argv in (
        ("Hub-Bild bauen (kann beim ersten Mal einige Minuten dauern)", ["docker", "compose", "build"]),
        ("Dienste starten", ["docker", "compose", "up", "-d"]),
    ):
        log(f"== {titel}")
        code, ausgabe = _lauf(argv, verz, log, popen)
        if code != 0:
            hinweis = _hinweis(ausgabe)
            text = f"`{' '.join(argv)}` ist mit Code {code} fehlgeschlagen." + (f" {hinweis}" if hinweis else "")
            log(text)
            return Ergebnis(False, text)
    log("== Gesundheit prüfen")
    pruefer = pruefer or standard_pruefer(plan, popen)
    ende = uhr() + zeitlimit
    letzter: dict[str, bool] = {}
    while True:
        letzter = pruefer()
        log("web: " + ("ok" if letzter.get("web") else "noch nicht bereit") + ", hub: " + ("ok" if letzter.get("hub") else "noch nicht bereit"))
        if letzter.get("web") and letzter.get("hub"):
            text = f"FYOS läuft: {plan.url}"
            log(text)
            ab = _abnahme(plan, log, abnahme or abn.pruefen, kanal_abnahme)
            if ab is not None:
                text += f". {ab.zusammenfassung()}"
            return Ergebnis(True, text, plan.url, ab)
        if uhr() >= ende:
            break
        schlaf(3)
    fehlt = ", ".join(k for k in ("web", "hub") if not letzter.get(k))
    text = (
        f"Zeitlimit erreicht: {fehlt} antwortet nicht. Die Dienste laufen vielleicht noch an; "
        "`docker compose logs` im Zielordner zeigt die Meldungen."
    )
    log(text)
    return Ergebnis(False, text)
