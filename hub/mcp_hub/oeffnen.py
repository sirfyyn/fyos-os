"""„Öffnen mit“: die Gegenstelle auf dem Rechner mit den Programmen (``fyos-oeffnen`` auf dem Desktop-Rechner).

Die App „Dateien“ zeigt zu einer Datei die Programme, die sie öffnen können (PDF in Papers, Text in WordCraft, Tabellen
in GridCraft). Der Hub spricht dazu mit einem kleinen Dienst auf dem Rechner, auf dem die Fenster erscheinen:

    GET  /programme   {"ok": true, "programme": [{"id", "name", "endungen": [".pdf"]}]}
    POST /oeffnen     {"pfad", "programm"} → der Dienst lädt die Datei aus der Dateiablage und startet das Programm

Der Hub schickt nur Pfad und Programmkennung; Adresse der Ablage und Programmbefehle stehen allein im Dienst. Das
Bearer-Token kommt aus der Umgebung (Name in ``token_env``), steht nie in der Konfiguration, in Antworten oder im Protokoll.
Umleitungen werden nicht verfolgt, damit die Kopfzeile nur an die eingetragene Adresse geht.

Konfiguration (Plugin ``dateien``)::

    config:
      oeffnen:
        gegenstelle: "http://rechner:18445"
        token_env: FYOS_OEFFNEN_TOKEN      # Vorgabe
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

ENV_GEGENSTELLE = "FYOS_OEFFNEN_GEGENSTELLE"
ENV_TOKEN = "FYOS_OEFFNEN_TOKEN"
CACHE_S = 60.0
FRIST_LESEN_S = 5.0
FRIST_OEFFNEN_S = 70.0  # der Dienst lädt die Datei (bis 25 MB) und startet erst dann
ANTWORT_MAX = 64 * 1024


class OeffnenFehler(Exception):
    """Die Gegenstelle ist nicht erreichbar oder lehnt ab. Der Text darf dem Menschen gezeigt werden (ohne Token)."""

    def __init__(self, text: str, status: int | None = None) -> None:
        super().__init__(text)
        self.status = status


class NichtEingerichtet(Exception):
    """Es gibt keine Gegenstelle oder kein Token dazu."""


class _KeineUmleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_OFFEN = urllib.request.build_opener(_KeineUmleitung)


def _netzfehler(e: BaseException) -> str:
    ursache = e.reason if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException) else e
    if isinstance(ursache, TimeoutError):
        return "Zeitüberschreitung"
    if isinstance(ursache, ConnectionRefusedError):
        return "Verbindung abgelehnt"
    if isinstance(ursache, socket.gaierror):
        return "Name nicht aufgelöst"
    if isinstance(ursache, ssl.SSLError):
        return "TLS-Fehler"
    return type(ursache).__name__


def endung(pfad: str) -> str:
    name = pfad.rsplit("/", 1)[-1]
    return name[name.rfind("."):].lower() if "." in name.strip(".") else ""


class Gegenstelle:
    """Eine Gegenstelle (``fyos-oeffnen``). ``aufruf(methode, pfad, koerper, frist)`` ersetzt das Netz (Tests)."""

    def __init__(self, url: str, token: str, aufruf: Callable[..., tuple[int, Any]] | None = None, cache_s: float = CACHE_S) -> None:
        teile = urllib.parse.urlsplit(url or "")
        if teile.scheme not in ("http", "https") or not teile.hostname or teile.username or teile.password:
            raise NichtEingerichtet("Die Gegenstelle für „Öffnen mit“ hat keine gültige Adresse (http://rechner:port, ohne Zugangsdaten).")
        self.url = url.rstrip("/")
        self._host = teile.hostname + (f":{teile.port}" if teile.port else "")
        self._token = token
        self._aufruf = aufruf
        self._cache_s = cache_s
        self._cache: tuple[float, list[dict[str, Any]]] | None = None
        self._sperre = threading.Lock()

    @property
    def schluessel(self) -> tuple[str, str]:
        """Woran der Zwischenspeicher erkennt, dass sich Adresse oder Token geändert haben (nie ausgeben)."""
        return (self.url, self._token)

    def beschreibung(self) -> str:
        return f"Gegenstelle {self._host}"

    def _roh(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S, grenze: int = ANTWORT_MAX) -> tuple[int, Any]:
        if self._aufruf is not None:
            return self._aufruf(methode, pfad, koerper, frist)
        daten = json.dumps(koerper).encode() if koerper is not None else None
        kopf = {"Accept": "application/json", "User-Agent": "fyos-hub", "Authorization": f"Bearer {self._token}"}
        if daten is not None:
            kopf["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + pfad, data=daten, method=methode, headers=kopf)
        try:
            with _OFFEN.open(req, timeout=frist) as r:  # noqa: S310 — Adresse aus der Konfiguration
                roh, status = r.read(grenze + 1), r.status
        except urllib.error.HTTPError as e:
            roh, status = (e.read(min(grenze, ANTWORT_MAX)) if e.fp else b""), e.code
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise OeffnenFehler(f"{self.beschreibung()} ist nicht erreichbar ({_netzfehler(e)}).") from None
        if len(roh) > grenze:
            raise OeffnenFehler(f"{self.beschreibung()}: die Antwort ist zu groß.")
        try:
            return status, json.loads(roh.decode() or "{}")
        except ValueError:
            return status, None

    def _grund(self, status: int, d: Any) -> OeffnenFehler:
        if status in (401, 403):
            return OeffnenFehler(f"{self.beschreibung()} lehnt den Zugang ab ({status}); das Token stimmt nicht.", status)
        text = d.get("error") if isinstance(d, dict) else None
        if isinstance(text, str) and text.strip():
            return OeffnenFehler(f"{self.beschreibung()}: {' '.join(text.split())[:300]}", status)
        return OeffnenFehler(f"{self.beschreibung()} antwortet mit {status}.", status)

    def anfrage(self, methode: str, pfad: str, koerper: Any = None, frist: float = FRIST_LESEN_S, grenze: int = ANTWORT_MAX) -> dict[str, Any]:
        """Ein Weg der Desktop-Brücke (``/fenster``, ``/lage``, ``/fokus`` …): die Antwort als Objekt, sonst ``OeffnenFehler``."""
        status, d = self._roh(methode, pfad, koerper, frist, grenze)
        if status != 200 or not isinstance(d, dict) or d.get("ok") is not True:
            raise self._grund(status, d)
        return d

    def programme(self) -> list[dict[str, Any]]:
        """Die Programme der Gegenstelle als ``[{id, name, endungen}]``; eine Minute im Zwischenspeicher."""
        with self._sperre:
            if self._cache and time.monotonic() - self._cache[0] < self._cache_s:
                return self._cache[1]
        status, d = self._roh("GET", "/programme")
        if status != 200 or not isinstance(d, dict) or not isinstance(d.get("programme"), list):
            raise self._grund(status, d) if status != 200 else OeffnenFehler(f"{self.beschreibung()} liefert keine Programmliste.")
        liste = []
        for p in d["programme"]:
            if isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("endungen"), list):
                liste.append({
                    "id": p["id"], "name": str(p.get("name") or p["id"])[:60],
                    "endungen": [str(e).lower() for e in p["endungen"] if isinstance(e, str)],
                })
        with self._sperre:
            self._cache = (time.monotonic(), liste)
        return liste

    def programme_fuer(self, pfad: str) -> list[dict[str, Any]]:
        e = endung(pfad)
        return [p for p in self.programme() if e and e in p["endungen"]]

    def oeffnen(self, pfad: str, programm: str) -> dict[str, Any]:
        status, d = self._roh("POST", "/oeffnen", {"pfad": pfad, "programm": programm}, FRIST_OEFFNEN_S)
        if status != 200 or not isinstance(d, dict) or d.get("ok") is not True:
            raise self._grund(status, d)
        return {"programm": str(d.get("programm") or programm)[:60], "groesse": d.get("groesse") if isinstance(d.get("groesse"), int) else None}


def aus_konfiguration(konf: dict[str, Any] | None, umgebung: dict[str, str] | None = None) -> Gegenstelle:
    """Gegenstelle aus ``config.oeffnen`` (oder ``FYOS_OEFFNEN_GEGENSTELLE``) und dem Token aus der Umgebung."""
    umg = os.environ if umgebung is None else umgebung
    konf = konf if isinstance(konf, dict) else {}
    url = str(konf.get("gegenstelle") or umg.get(ENV_GEGENSTELLE) or "").strip()
    if not url:
        raise NichtEingerichtet("„Öffnen mit“ ist nicht eingerichtet: im Plugin dateien fehlt oeffnen.gegenstelle (oder FYOS_OEFFNEN_GEGENSTELLE).")
    name = str(konf.get("token_env") or ENV_TOKEN).strip()
    token = (umg.get(name) or "").strip()
    if not token:
        raise NichtEingerichtet(f"„Öffnen mit“ ist nicht eingerichtet: die Umgebungsvariable {name} (Token der Gegenstelle) fehlt.")
    return Gegenstelle(url, token)
