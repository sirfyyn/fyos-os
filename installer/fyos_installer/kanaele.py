"""Chat-Kanäle des Agenten (Matrix, Telegram, WhatsApp): was der Installer daraus macht.

Ein Kanal ist ein Baustein der Art `kanal` (`katalog_kanaele.yaml`). Er hat kein Hub-Plugin; er schaltet einen Kanal
des Agenten ein. Das heißt dreierlei:

    fyos.yaml          `kanaele.<name>: true`, dazu `besitzer.matrix_id` (Matrix) und `whatsapp.eigene_nummer`.
    Umgebung           Token, Kennungen und Nummern gehen an den Agenten, nie an den Hub (`FYOS_APPROVER_*`,
                       `OPENCLAW_*_TOKEN`; Namen wie in fyos-agent/README.md). Im Agenten stehen sie in der Umgebung
                       des Containers, nie in einer Datei außer der Geheimnisdatei des Installers (.env, secrets.yaml).
    Bild               Telegram steckt im Basisbild von OpenClaw. Matrix und WhatsApp sind Pakete (`@openclaw/matrix`,
                       `@openclaw/whatsapp`), die das Bild zusätzlich braucht: Der Installer erzeugt dafür ein
                       abgeleitetes Bild (`agent/Dockerfile`), das auf dem Bild des Agenten aufsetzt.

Fehlt einem gewählten Kanal ein Wert, schreibt der Installer den Kanal trotzdem (Platzhalter in der Umgebung, Paket im
Bild), lässt ihn aber aus (`kanaele.<name>: false`) und sagt, was noch einzutragen ist. Ein Agent, dessen Kanal ohne
Token an wäre, bräche beim Start ab; so läuft FYOS, und der Kanal ist eine Zeile Arbeit entfernt.

Die Abnahme (`abnahme.py`) fragt den laufenden Agenten, ob die gewählten Kanäle wirklich aktiv sind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

#: Version der Kanal-Pakete: dieselbe wie das Basisbild des Agenten (fyos-agent/openclaw/Dockerfile).
OPENCLAW_VERSION = "2026.9.7"
#: Name des abgeleiteten Agent-Bildes bei Docker Compose (nur lokal gebaut, nie geschoben).
BILD_AGENT_EIGEN_LOKAL = "fyos-agent-eigen:lokal"
#: Umgebungsvariablen, die nur in fyos.yaml gehören und nicht in die Umgebung des Agenten.
NUR_KONFIG = frozenset({"FYOS_WHATSAPP_EIGENE_NUMMER"})

_TELEGRAM_TOKEN = re.compile(r"\d+:[A-Za-z0-9_-]+")
_TELEGRAM_ID = re.compile(r"[1-9]\d{0,15}")
_MATRIX_KENNUNG = re.compile(r"@[^:\s@]+:[^\s@]+")
_WHATSAPP_NUMMER = re.compile(r"\+[1-9]\d{6,14}")


@dataclass(frozen=True)
class Kanal:
    id: str  # Name in fyos.yaml unter `kanaele`
    baustein: str  # id im Katalog
    titel: str
    paket: str | None  # Paket, das das Bild zusätzlich braucht (None: im Basisbild)
    noetig: tuple[str, ...]  # Umgebungsvariablen, ohne die der Kanal im Agenten nicht starten kann


KANAELE: dict[str, Kanal] = {
    k.baustein: k
    for k in (
        Kanal("matrix", "kanal_matrix", "Matrix", "@openclaw/matrix",
              ("FYOS_MATRIX_HOMESERVER", "FYOS_MATRIX_BENUTZER", "OPENCLAW_MATRIX_TOKEN", "FYOS_APPROVER_MATRIX_ID")),
        Kanal("telegram", "kanal_telegram", "Telegram", None,
              ("OPENCLAW_TELEGRAM_TOKEN", "FYOS_APPROVER_TELEGRAM_ID")),
        Kanal("whatsapp", "kanal_whatsapp", "WhatsApp", "@openclaw/whatsapp",
              ("FYOS_APPROVER_WHATSAPP_NUMBER",)),
    )
}


def gewaehlt(auswahl: Iterable[str]) -> list[Kanal]:
    """Die gewählten Kanäle in Katalogreihenfolge der Auswahl."""
    return [KANAELE[i] for i in auswahl if i in KANAELE]


def fehlend(kanal: Kanal, werte: Mapping[str, str]) -> list[str]:
    """Umgebungsvariablen, die dem Kanal noch fehlen."""
    return [e for e in kanal.noetig if not werte.get(e, "").strip()]


def aktiv(kanal: Kanal, werte: Mapping[str, str]) -> bool:
    return not fehlend(kanal, werte)


def pruefe_werte(kanaele: Iterable[Kanal], werte: Mapping[str, str]) -> list[str]:
    """Fehler für Werte, die gesetzt sind, aber nicht die Form haben, die der Agent beim Start verlangt.
    Die Fehler nennen den Namen der Variable, nie ihren Wert."""
    fehler: list[str] = []

    def pruef(var: str, muster: re.Pattern[str], soll: str) -> None:
        wert = werte.get(var, "").strip()
        if wert and not muster.fullmatch(wert):
            fehler.append(f"Kanal: {var} {soll}")

    ids = {k.id for k in kanaele}
    if "telegram" in ids:
        pruef("OPENCLAW_TELEGRAM_TOKEN", _TELEGRAM_TOKEN, "hat nicht die Form eines Bot-Tokens (Zahl:Zeichen)")
        pruef("FYOS_APPROVER_TELEGRAM_ID", _TELEGRAM_ID, "muss die numerische Telegram-ID sein")
    if "matrix" in ids:
        pruef("FYOS_MATRIX_BENUTZER", _MATRIX_KENNUNG, "muss die Form @name:server haben")
        pruef("FYOS_APPROVER_MATRIX_ID", _MATRIX_KENNUNG, "muss die Form @name:server haben")
    if "whatsapp" in ids:
        pruef("FYOS_APPROVER_WHATSAPP_NUMBER", _WHATSAPP_NUMMER,
              "muss eine Nummer in internationaler Schreibweise sein (+, Landesvorwahl, nur Ziffern)")
    return fehler


def fyos_teil(kanaele: list[Kanal], werte: Mapping[str, str]) -> dict:
    """Die Teile von fyos.yaml, die Kanäle betreffen: `kanaele`, `besitzer.matrix_id`, `whatsapp`."""
    if not kanaele:
        return {}
    teil: dict = {"kanaele": {k.id: aktiv(k, werte) for k in kanaele}}
    if any(k.id == "matrix" for k in kanaele) and werte.get("FYOS_APPROVER_MATRIX_ID", "").strip():
        teil["besitzer"] = {"matrix_id": werte["FYOS_APPROVER_MATRIX_ID"].strip()}
    if any(k.id == "whatsapp" for k in kanaele):
        teil["whatsapp"] = {"eigene_nummer": werte.get("FYOS_WHATSAPP_EIGENE_NUMMER", "").strip().lower() == "ja"}
    return teil


def pakete(kanaele: Iterable[Kanal]) -> list[str]:
    """Pakete, die das Bild des Agenten zusätzlich braucht."""
    return [f"{k.paket}@{OPENCLAW_VERSION}" for k in kanaele if k.paket]


def agent_dockerfile(kanaele: Iterable[Kanal]) -> str:
    """Abgeleitetes Bild des Agenten mit den Paketen der gewählten Kanäle. Das Basisbild kommt als Bau-Argument;
    es legt `/opt/openclaw-npm` für den Benutzer node an, von dort holt der Einstieg die Pakete bei jedem Start."""
    installieren = " \\\n    && ".join(f"openclaw plugins install {p}" for p in pakete(kanaele))
    return (
        "# Agent mit Kanal-Paketen (vom FYOS-Installer erzeugt). Baut auf dem Bild des Agenten auf.\n"
        "ARG FYOS_BILD_AGENT\n"
        "FROM ${FYOS_BILD_AGENT}\n"
        "USER node\n"
        f"RUN {installieren} \\\n"
        "    && cp -a /home/node/.openclaw/npm/. /opt/openclaw-npm/\n"
    )


def hinweise(kanaele: Iterable[Kanal], werte: Mapping[str, str], ziel: str, beginn: str) -> list[str]:
    """Sätze für die Zusammenfassung und die Anleitung. `beginn` ist der Befehl, der in den Agenten führt."""
    saetze: list[str] = []
    for k in kanaele:
        fehlt = fehlend(k, werte)
        if fehlt:
            wohin = ".env" if ziel != "k8s" else "kustomization.yaml (Kennungen) und secrets.yaml (Token)"
            saetze.append(
                f"Kanal {k.titel} ist vorbereitet, aber aus: es fehlt {', '.join(fehlt)}. Trage "
                f"{'den Wert' if len(fehlt) == 1 else 'die Werte'} in {wohin} ein "
                f"und setze in fyos.yaml kanaele.{k.id} auf true; danach den Agenten neu starten."
            )
        if k.id == "whatsapp":
            saetze.append(
                "Kanal WhatsApp: Gekoppelt wird einmal per QR-Code, und das machst du selbst am Telefon: "
                f"`{beginn} openclaw channels login --channel whatsapp`, den QR-Code in WhatsApp unter "
                "»Verknüpfte Geräte« einlesen. Der Zustandsordner des Agenten muss erhalten bleiben."
            )
    return saetze
