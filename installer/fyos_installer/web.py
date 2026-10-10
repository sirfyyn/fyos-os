"""Web-Assistent: lokaler Server nur mit der Standardbibliothek.

Bindet an 127.0.0.1 auf einem zufälligen Port. Ohne das einmalige Zugangstoken aus der URL
antwortet er nicht. API: GET /api/katalog, POST /api/plan, POST /api/installieren, GET /api/protokoll (SSE).
Das Ereignis `ende` trägt `ok`, `meldung`, `url` und beim Ziel Docker Compose die `abnahme` (abnahme.py).
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from . import ausfuehren as ausf
from . import erzeugen
from .katalog import BILD_TYPEN, Katalog, bilder_von

WEB = Path(__file__).resolve().parent / "web"
STATISCH = {
    "app.js": "text/javascript; charset=utf-8", "stil.css": "text/css; charset=utf-8",
    "favicon.svg": "image/svg+xml",
}
MAX_BODY = 1_000_000
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class Zustand:
    """Gemeinsamer Zustand des Assistenten: Katalog, Token, Installationsprotokoll."""

    def __init__(
        self,
        katalog: Katalog,
        token: str | None = None,
        verzeichnis: str | Path = "fyos",
        docker: Callable[[], tuple[bool, str]] | None = None,
        umgebung: dict[str, str] | None = None,
    ):
        self.katalog = katalog
        self.token = token or secrets.token_urlsafe(24)
        self.verzeichnis = Path(verzeichnis)
        self._docker = docker or ausf.docker_pruefen
        self.umgebung = os.environ if umgebung is None else umgebung
        self.port = 0
        self.zeilen: list[dict[str, str]] = []
        self.ende: dict[str, Any] | None = None
        self.laeuft = False
        self.bedingung = threading.Condition()
        self.beenden = threading.Event()

    # -- Protokoll
    def log(self, text: str, art: str = "info") -> None:
        with self.bedingung:
            self.zeilen.append({"art": art, "text": text})
            self.bedingung.notify_all()

    def abschliessen(self, ok: bool, meldung: str, url: str | None = None, abnahme: dict[str, Any] | None = None) -> None:
        with self.bedingung:
            self.ende = {"ok": ok, "meldung": meldung, "url": url, "abnahme": abnahme}
            self.laeuft = False
            self.bedingung.notify_all()

    # -- Daten
    def katalog_json(self) -> dict[str, Any]:
        bereit, meldung = self._docker()
        bausteine = []
        for b in self.katalog:
            bausteine.append({
                "id": b.id, "titel": b.titel, "kurz": b.kurz, "was_daraus_wird": b.was_daraus_wird, "art": b.art,
                "pflicht": b.pflicht, "abhaengig_von": b.abhaengig_von, "voraussetzungen": b.voraussetzungen,
                "braucht_quelle": bool(b.paket),
                "bilder": [f"/bild/{b.id}/{i}" for i, _ in enumerate(bilder_von(b))],
                "konfiguration": [
                    {"name": f.name, "typ": f.typ, "titel": f.titel, "beschreibung": f.beschreibung, "standard": f.standard,
                     "pflicht": f.pflicht, "optionen": f.optionen}
                    for f in b.konfiguration
                ],
                "herkunft": b.herkunft,
            })
        optionen = erzeugen.vorgaben_optionen(self.umgebung, bezug_aufloesen=True)
        return {
            "bausteine": bausteine,
            "ziele": erzeugen.ZIELE,
            "vorgaben": {"persona": erzeugen.VORGABE_PERSONA, "modell": erzeugen.VORGABE_MODELL, "optionen": optionen},
            "docker": {"bereit": bereit, "meldung": meldung},
            "verzeichnis": str(self.verzeichnis.resolve()),
            "plugin_quelle_beispiel": self.katalog.plugin_quelle_beispiel,
        }

    def plan_aus(self, daten: dict[str, Any]) -> erzeugen.Plan:
        auswahl = daten.get("auswahl") or []
        if not isinstance(auswahl, list) or not all(isinstance(a, str) for a in auswahl):
            plan = erzeugen.Plan(ziel=str(daten.get("ziel")), verzeichnis=self.verzeichnis)
            plan.fehler.append("auswahl muss eine Liste von Baustein-ids sein")
            return plan
        antworten = daten.get("antworten") or {}
        if not isinstance(antworten, dict):
            antworten = {}
        verz = daten.get("verzeichnis") or str(self.verzeichnis)
        return erzeugen.erstelle_plan(
            self.katalog, auswahl, str(daten.get("ziel", "")), antworten,
            Path(str(verz)).expanduser().resolve(), umgebung=self.umgebung,
        )

    def installieren(self, plan: erzeugen.Plan) -> bool:
        with self.bedingung:
            if self.laeuft:
                return False
            self.laeuft = True
            self.zeilen.clear()
            self.ende = None
        threading.Thread(target=self._arbeit, args=(plan,), daemon=True).start()
        return True

    def _arbeit(self, plan: erzeugen.Plan) -> None:
        try:
            self.log(f"== Dateien nach {plan.verzeichnis} schreiben")
            for pfad in erzeugen.schreiben(plan):
                self.log(f"geschrieben: {pfad}")
            if plan.ausfuehrbar:
                erg = ausf.ausfuehren(plan, self.log)
                self.abschliessen(erg.ok, erg.meldung, erg.url, erg.abnahme.als_dict() if erg.abnahme else None)
            else:
                self.log("Dateien sind fertig. Die nächsten Schritte stehen in ANLEITUNG.md.")
                self.abschliessen(True, "Dateien erzeugt. Weiter mit ANLEITUNG.md im Zielordner.", None)
        except Exception as e:  # noqa: BLE001 - Fehler gehören ins Protokoll, nicht in den Thread
            self.log(f"Fehler: {e}", "fehler")
            self.abschliessen(False, f"Fehler: {e}")


class Handler(BaseHTTPRequestHandler):
    server_version = "FyosInstaller/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def z(self) -> Zustand:
        return self.server.zustand  # type: ignore[attr-defined]

    def log_message(self, *_a: Any) -> None:  # still
        pass

    # -- Hilfen
    def _kopf(self, status: int, typ: str, laenge: int | None = None, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", typ)
        if laenge is not None:
            self.send_header("Content-Length", str(laenge))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _senden(self, status: int, daten: bytes, typ: str, extra: dict[str, str] | None = None) -> None:
        self._kopf(status, typ, len(daten), extra)
        self.wfile.write(daten)

    def _json(self, status: int, objekt: Any) -> None:
        self._senden(status, json.dumps(objekt, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _fehler(self, status: int, text: str) -> None:
        self._senden(status, text.encode(), "text/plain; charset=utf-8")

    def _host_ok(self) -> bool:
        erlaubt = {f"127.0.0.1:{self.z.port}", f"localhost:{self.z.port}"}
        if self.headers.get("Host", "") not in erlaubt:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin.removeprefix("http://") in erlaubt

    def _cookiename(self) -> str:
        return f"fyos_installer_{self.z.port}"

    def _token_aus(self, query: dict[str, list[str]]) -> str:
        if (t := self.headers.get("X-Fyos-Token")):
            return t
        if (c := self.headers.get("Cookie")):
            jar = SimpleCookie()
            try:
                jar.load(c)
            except Exception:  # noqa: BLE001
                return ""
            if self._cookiename() in jar:
                return jar[self._cookiename()].value
        return (query.get("t") or [""])[0]

    def _token_ok(self, query: dict[str, list[str]]) -> bool:
        return hmac.compare_digest(self._token_aus(query).encode(), self.z.token.encode())

    def _body(self) -> dict[str, Any] | None:
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            return None
        try:
            daten = json.loads(self.rfile.read(n))
        except (ValueError, UnicodeDecodeError):
            return None
        return daten if isinstance(daten, dict) else None

    # -- Anfragen
    def do_GET(self) -> None:  # noqa: N802
        self._bearbeite("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._bearbeite("POST")

    def _bearbeite(self, methode: str) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self._host_ok():
            return self._fehler(HTTPStatus.FORBIDDEN, "Host nicht erlaubt.")
        if not self._token_ok(query):
            return self._fehler(HTTPStatus.FORBIDDEN, "Zugang nur mit dem Link, den fyos-install ausgibt.")
        pfad = url.path
        if methode == "GET":
            if pfad == "/":
                if "t" in query:  # Token in Cookie umsetzen und aus der Adresszeile entfernen
                    cookie = f"{self._cookiename()}={self.z.token}; Path=/; HttpOnly; SameSite=Strict"
                    return self._senden(HTTPStatus.FOUND, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
                return self._senden(HTTPStatus.OK, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if pfad.startswith("/static/") and pfad[8:] in STATISCH:
                return self._senden(HTTPStatus.OK, (WEB / pfad[8:]).read_bytes(), STATISCH[pfad[8:]])
            if pfad in ("/favicon.ico", "/favicon.svg"):
                return self._senden(HTTPStatus.OK, (WEB / "favicon.svg").read_bytes(), "image/svg+xml")
            if pfad == "/api/katalog":
                return self._json(HTTPStatus.OK, self.z.katalog_json())
            if pfad == "/api/protokoll":
                return self._protokoll()
            if pfad.startswith("/bild/"):
                return self._bild(pfad)
        else:
            if pfad in ("/api/plan", "/api/installieren"):
                daten = self._body()
                if daten is None:
                    return self._json(HTTPStatus.BAD_REQUEST, {"fehler": ["Erwartet wird ein JSON-Objekt."]})
                plan = self.z.plan_aus(daten)
                if pfad == "/api/plan":
                    return self._json(HTTPStatus.OK, plan.als_dict())
                if not plan.ok:
                    return self._json(HTTPStatus.UNPROCESSABLE_ENTITY, plan.als_dict())
                if not self.z.installieren(plan):
                    return self._json(HTTPStatus.CONFLICT, {"fehler": ["Es läuft bereits eine Installation."]})
                return self._json(HTTPStatus.ACCEPTED, {"gestartet": True})
            if pfad == "/api/beenden":
                self.z.beenden.set()
                return self._json(HTTPStatus.OK, {"beendet": True})
        self._fehler(HTTPStatus.NOT_FOUND, "Nicht gefunden.")

    def _bild(self, pfad: str) -> None:
        teile = pfad.split("/")
        try:
            baustein = self.z.katalog[teile[2]]
            datei = bilder_von(baustein)[int(teile[3])]
        except Exception:  # noqa: BLE001 - alles hier heißt: nicht gefunden
            return self._fehler(HTTPStatus.NOT_FOUND, "Kein solches Bild.")
        typ = BILD_TYPEN.get(datei.suffix.lower()) or mimetypes.guess_type(datei.name)[0] or "application/octet-stream"
        self._senden(HTTPStatus.OK, datei.read_bytes(), typ)

    def _protokoll(self) -> None:
        """Server-Sent Events: jede Zeile als Ereignis `zeile`, am Ende `ende`."""
        self.close_connection = True
        self._kopf(HTTPStatus.OK, "text/event-stream; charset=utf-8", None, {"Connection": "close"})
        nr = 0
        try:
            while not self.z.beenden.is_set():
                with self.z.bedingung:
                    self.z.bedingung.wait_for(
                        lambda: len(self.z.zeilen) > nr or self.z.ende is not None, timeout=10
                    )
                    neu = self.z.zeilen[nr:]
                    ende = self.z.ende
                if not neu and ende is None:
                    self.wfile.write(b": weiter\n\n")
                    self.wfile.flush()
                    continue
                for zeile in neu:
                    nr += 1
                    self.wfile.write(
                        f"id: {nr}\nevent: zeile\ndata: {json.dumps(zeile, ensure_ascii=False)}\n\n".encode()
                    )
                if ende is not None:
                    self.wfile.write(f"event: ende\ndata: {json.dumps(ende, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                    return
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, zustand: Zustand, port: int = 0):
        super().__init__(("127.0.0.1", port), Handler)
        self.zustand = zustand
        zustand.port = self.server_address[1]

    def url(self) -> str:
        return f"http://127.0.0.1:{self.zustand.port}/?t={self.zustand.token}"


def starte(
    katalog: Katalog,
    *,
    port: int = 0,
    browser: bool = True,
    verzeichnis: str | Path = "fyos",
    ausgabe: Callable[[str], None] = lambda text: print(text, flush=True),
) -> int:
    server = Server(Zustand(katalog, verzeichnis=verzeichnis), port)
    ausgabe("FYOS-Installer läuft. Öffne diesen Link (gilt nur für diese Sitzung):")
    ausgabe(server.url())
    ausgabe("Beenden mit Strg+C.")
    if browser:
        try:
            webbrowser.open(server.url())
        except Exception:  # noqa: BLE001 - Link steht oben
            pass
    threading.Thread(target=lambda: (server.zustand.beenden.wait(), server.shutdown()), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        ausgabe("Beendet.")
    finally:
        server.server_close()
    return 0
