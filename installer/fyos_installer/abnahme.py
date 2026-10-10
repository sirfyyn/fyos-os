"""Abnahme nach der Installation: verbotene Anfragen müssen abgelehnt werden.

Ein System, das läuft, ist noch kein abgenommenes. Die Abnahme stellt über die Adresse der Shell (dort, wo auch der
Browser anklopft) drei Anfragen, die FYOS ablehnen muss, und eine, die es beantworten muss:

    Gegenprobe   erlaubt: ein Werkzeug mit Oberfläche über `/hub-api/app-call`, ohne fremde Herkunft.
                 Antwortet das nicht, sind die Ablehnungen nichts wert (falsche Adresse, Hub nicht erreichbar).
    Probe 1      der volle Aufruf-Endpunkt (`/hub-api/call`) gehört nicht zum Browser-Weg: die Shell reicht ihn nicht durch.
    Probe 2      ein schreibender Aufruf mit fremder Herkunft (Origin einer fremden Webseite): der Hub lehnt ihn ab
                 (`kind: fremde_herkunft`, `hub/mcp_hub/herkunft.py`).
    Probe 3      ein Werkzeug ohne Oberfläche über den Browser-Weg: der Hub lehnt es ab (`kind: not_an_app`).

Nur Ablehnungen gelten. Antwortet FYOS auf eine verbotene Anfrage mit Erfolg, ist die Abnahme nicht bestanden; eine
andere Ablehnung als erwartet, eine Antwort ohne `kind` oder gar keine Antwort gilt als nicht nachgewiesen.

Die Probeanfragen sind harmlos, auch wenn die Ablehnung ausbleibt: Sie rufen nur lesende Werkzeuge (`audit.stats`
liefert Zahlen, `werkstatt.suchen` liest die Liste der angemeldeten Skripte), schreiben nichts und lösen nichts aus. Ein
Test (`test_abnahme.py`) hält fest, dass beide im Hub als `read` ausgezeichnet sind.

Die Abnahme braucht keine Anmeldung und keinen Docker: Es sind HTTP-Anfragen an die Adresse der Shell, ohne Proxy und
ohne Weiterleitungen zu folgen. Der Installer führt sie beim Ziel Docker Compose nach dem Start aus; für jedes andere Ziel
und zum Wiederholen gibt es `fyos-install --abnahme <Adresse>`.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

ZEITLIMIT_S = 5.0
MAX_ANTWORT = 64_000  # Bytes, die von einer Antwort gelesen werden
FREMDE_HERKUNFT = "https://fremd.example.com"  # nie eine eigene Adresse (Beispieldomain)

_BASIS = re.compile(r"^https?://[^\s/@?#]+$")


@dataclass(frozen=True)
class Probe:
    id: str
    titel: str
    methode: str
    pfad: str
    daten: dict[str, Any] | None = None
    kopf: dict[str, str] = field(default_factory=dict)
    status: tuple[int, ...] = ()  # Statuscodes, die als Ablehnung gelten
    art: str | None = None  # erwartetes `kind` in der Antwort des Hubs; None: der Statuscode genügt
    wirkung: str = ""  # was geschähe, wenn die Anfrage durchginge (immer harmlos)
    hilfe: str = ""  # was dann zu prüfen ist


GEGENPROBE = Probe(
    id="gegenprobe",
    titel="Erlaubte Anfrage über den Browser-Weg",
    methode="POST",
    pfad="/hub-api/app-call",
    daten={"tool": "werkstatt.suchen", "arguments": {"q": "abnahme"}},
    hilfe="Die Adresse zeigt nicht auf die Shell dieser Installation, oder der Hub ist hinter ihr nicht erreichbar.",
)

PROBEN: tuple[Probe, ...] = (
    Probe(
        id="aufruf_endpunkt",
        titel="Voller Aufruf-Endpunkt über den Browser-Weg",
        methode="POST",
        pfad="/hub-api/call",
        daten={"tool": "audit.stats", "arguments": {}},
        status=(403, 404),
        wirkung="Durchgegangen wäre nur eine Lesung: audit.stats liefert Zahlen über das Audit-Log.",
        hilfe="Die Shell reicht nur apps, resource, app-call und os/* an den Hub weiter (web/nginx/default.conf.template); "
        "ein Proxy davor darf nicht mehr durchlassen.",
    ),
    Probe(
        id="fremde_herkunft",
        titel="Schreibender Aufruf von einer fremden Webseite",
        methode="POST",
        pfad="/hub-api/app-call",
        daten={"tool": "werkstatt.suchen", "arguments": {"q": "abnahme"}},
        kopf={"Origin": FREMDE_HERKUNFT, "Sec-Fetch-Site": "cross-site"},
        status=(403,),
        art="fremde_herkunft",
        wirkung="Durchgegangen wäre nur eine Lesung: werkstatt.suchen listet die angemeldeten Skripte.",
        hilfe="Der Hub lehnt Anfragen mit fremdem Origin ab (hub/mcp_hub/herkunft.py); prüfe, ob ein Proxy davor die Köpfe "
        "Origin und Sec-Fetch-Site entfernt, und FYOS_ERLAUBTE_HOSTS.",
    ),
    Probe(
        id="kein_flaechenwerkzeug",
        titel="Werkzeug ohne Oberfläche über den Browser-Weg",
        methode="POST",
        pfad="/hub-api/app-call",
        daten={"tool": "audit.stats", "arguments": {}},
        status=(403,),
        art="not_an_app",
        wirkung="Durchgegangen wäre nur eine Lesung: audit.stats liefert Zahlen über das Audit-Log.",
        hilfe="Über den Browser-Weg dürfen nur Werkzeuge mit Oberfläche laufen (hub/mcp_hub/registry.py, "
        "ist_flaechen_werkzeug).",
    ),
)


@dataclass
class Antwort:
    status: int | None  # None: keine Antwort bekommen
    inhalt: Any = None  # der Körper als JSON, sonst None
    fehler: str = ""


Sender = Callable[[str, str, dict[str, str], dict[str, Any] | None], Antwort]


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a: Any, **_k: Any) -> None:  # eine Weiterleitung ist eine Antwort, kein Ziel
        return None


def senden(methode: str, url: str, kopf: dict[str, str], daten: dict[str, Any] | None = None) -> Antwort:
    """Eine Anfrage ohne Proxy und ohne Weiterleitungen; Fehler werden zur Antwort ohne Status, nie zur Ausnahme."""
    try:
        if not url.lower().startswith(("http://", "https://")):  # kein file:, ftp:, data: (urllib spräche sie alle)
            raise ValueError("nur http und https")
        koerper = None if daten is None else json.dumps(daten).encode()
        kopfzeilen = {**({"Content-Type": "application/json"} if koerper is not None else {}), **kopf}
        anfrage = urllib.request.Request(url, data=koerper, headers=kopfzeilen, method=methode)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _KeineWeiterleitung)
        with opener.open(anfrage, timeout=ZEITLIMIT_S) as r:  # noqa: S310 - Schema oben geprüft
            status, roh = r.status, r.read(MAX_ANTWORT)
    except urllib.error.HTTPError as e:  # 3xx ohne Weiterleitung, 4xx, 5xx: eine Antwort wie jede andere
        status, roh = e.code, e.read(MAX_ANTWORT)
    except (OSError, ValueError, http.client.HTTPException) as e:
        return Antwort(None, None, f"{type(e).__name__}: {e}"[:200])
    try:
        inhalt = json.loads(roh.decode("utf-8", errors="replace"))
    except ValueError:
        inhalt = None
    return Antwort(status, inhalt)


def basis_url(adresse: str) -> str:
    """`http(s)://host[:port]` ohne Pfad und Zugangsdaten; sonst ValueError."""
    basis = (adresse or "").strip().rstrip("/")
    if not _BASIS.match(basis):
        raise ValueError(f"'{adresse}' ist keine Adresse der Form http://host:port")
    return basis


@dataclass
class Befund:
    id: str
    titel: str
    ok: bool
    urteil: str  # abgelehnt | beantwortet | durchgelassen | unklar
    text: str
    wirkung: str = ""  # nur bei `durchgelassen`
    hilfe: str = ""  # nur bei ok == False

    def als_dict(self) -> dict[str, Any]:
        return {"id": self.id, "titel": self.titel, "ok": self.ok, "urteil": self.urteil, "text": self.text,
                "wirkung": self.wirkung, "hilfe": self.hilfe}


def _art(a: Antwort) -> str | None:
    art = a.inhalt.get("kind") if isinstance(a.inhalt, dict) else None
    return art if isinstance(art, str) else None


def urteil_gegenprobe(p: Probe, a: Antwort) -> Befund:
    if a.status is None:
        return Befund(p.id, p.titel, False, "unklar", f"keine Antwort ({a.fehler})", hilfe=p.hilfe)
    if a.status == 200 and isinstance(a.inhalt, dict) and a.inhalt.get("ok") is True:
        return Befund(p.id, p.titel, True, "beantwortet", "beantwortet (200)")
    art = _art(a)
    return Befund(p.id, p.titel, False, "unklar",
                  f"nicht beantwortet (Status {a.status}" + (f", {art}" if art else "") + ")", hilfe=p.hilfe)


def urteil_probe(p: Probe, a: Antwort) -> Befund:
    """Nur eine Ablehnung wie erwartet besteht; Erfolg ist durchgefallen, alles andere nicht nachgewiesen."""
    if a.status is None:
        return Befund(p.id, p.titel, False, "unklar", f"keine Antwort ({a.fehler})", hilfe=p.hilfe)
    art = _art(a)
    gesehen = f"{a.status}" + (f", {art}" if art else "")
    if 200 <= a.status < 300:
        return Befund(p.id, p.titel, False, "durchgelassen", f"NICHT abgelehnt (Antwort {a.status})",
                      wirkung=p.wirkung, hilfe=p.hilfe)
    if a.status in p.status and (p.art is None or art == p.art):
        return Befund(p.id, p.titel, True, "abgelehnt", f"abgelehnt ({gesehen})")
    erwartet = " oder ".join(str(s) for s in p.status) + (f" mit {p.art}" if p.art else "")
    return Befund(p.id, p.titel, False, "unklar", f"anders als erwartet ({gesehen} statt {erwartet})", hilfe=p.hilfe)


@dataclass
class Abnahme:
    basis: str
    gegenprobe: Befund
    proben: list[Befund]

    @property
    def bestanden(self) -> bool:
        return self.gegenprobe.ok and all(b.ok for b in self.proben)

    @property
    def abgelehnt(self) -> int:
        return sum(1 for b in self.proben if b.ok)

    def zusammenfassung(self) -> str:
        n = len(self.proben)
        if self.bestanden:
            return f"Abnahme bestanden: alle {n} verbotenen Anfragen wurden abgelehnt."
        if not self.gegenprobe.ok:
            return (f"Abnahme NICHT bestanden: Die erlaubte Gegenprobe scheiterte ({self.gegenprobe.text}); "
                    "die Ablehnungen sind so nicht aussagekräftig.")
        return f"Abnahme NICHT bestanden: {self.abgelehnt} von {n} verbotenen Anfragen wurden abgelehnt."

    def zeilen(self) -> list[str]:
        z = [f"== Abnahme: verbotene Anfragen an {self.basis} müssen abgelehnt werden",
             f"Gegenprobe: {self.gegenprobe.titel}: {self.gegenprobe.text}"]
        z += [f"Probe {i}: {b.titel}: {b.text}" for i, b in enumerate(self.proben, 1)]
        z.append(self.zusammenfassung())
        for b in [self.gegenprobe, *self.proben]:
            if not b.ok:
                z.append(f"  - {b.titel}: {b.text}")
                if b.wirkung:
                    z.append(f"    {b.wirkung}")
                if b.hilfe:
                    z.append(f"    Prüfen: {b.hilfe}")
        return z

    def als_dict(self) -> dict[str, Any]:
        return {
            "bestanden": self.bestanden, "basis": self.basis, "zusammenfassung": self.zusammenfassung(),
            "befunde": [self.gegenprobe.als_dict(), *[b.als_dict() for b in self.proben]],
        }


def pruefen(adresse: str, sender: Sender = senden) -> Abnahme:
    """Führt Gegenprobe und Proben gegen die Shell unter `adresse` aus. Wirft nur bei einer unbrauchbaren Adresse
    (ValueError); Fehler der Anfragen werden Befunde."""
    basis = basis_url(adresse)

    def stelle(p: Probe) -> Antwort:
        return sender(p.methode, basis + p.pfad, dict(p.kopf), p.daten)

    return Abnahme(
        basis=basis,
        gegenprobe=urteil_gegenprobe(GEGENPROBE, stelle(GEGENPROBE)),
        proben=[urteil_probe(p, stelle(p)) for p in PROBEN],
    )


def hinweis(port: int, ziel: str) -> str:
    """Satz für Zusammenfassung und Anleitung: was die Abnahme tut und wie man sie (wieder)holt."""
    n = len(PROBEN)
    befehl = f"fyos-install --abnahme http://localhost:{port}"
    harmlos = "Die Anfragen lesen nur und ändern nichts."
    if ziel == "compose":
        return (f"Abnahme: Nach dem Start stellt der Installer {n} verbotene Anfragen an die Shell; FYOS muss sie "
                f"ablehnen. {harmlos} Wiederholen: `{befehl}`.")
    wann = "Mit laufendem Port-Forward" if ziel == "k8s" else "Ist FYOS gestartet"
    return f"Abnahme: {wann}, prüft `{befehl}`, ob FYOS {n} verbotene Anfragen ablehnt. {harmlos}"
