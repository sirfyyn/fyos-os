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
import subprocess
import time
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
    kanaele: list[Befund] = field(default_factory=list)  # nur wenn Kanäle gewählt sind (kanal_proben)

    @property
    def bestanden(self) -> bool:
        return self.gegenprobe.ok and all(b.ok for b in self.proben) and all(b.ok for b in self.kanaele)

    @property
    def abgelehnt(self) -> int:
        return sum(1 for b in self.proben if b.ok)

    def zusammenfassung(self) -> str:
        n = len(self.proben)
        if not self.gegenprobe.ok:
            return (f"Abnahme NICHT bestanden: Die erlaubte Gegenprobe scheiterte ({self.gegenprobe.text}); "
                    "die Ablehnungen sind so nicht aussagekräftig.")
        if self.abgelehnt < n:
            return f"Abnahme NICHT bestanden: {self.abgelehnt} von {n} verbotenen Anfragen wurden abgelehnt."
        satz = f"alle {n} verbotenen Anfragen wurden abgelehnt"
        if self.kanaele:
            aktiv = sum(1 for b in self.kanaele if b.urteil == "aktiv")
            aus = sum(1 for b in self.kanaele if b.urteil == "aus")
            if not all(b.ok for b in self.kanaele):
                return (f"Abnahme NICHT bestanden: {satz}, aber {sum(1 for b in self.kanaele if not b.ok)} von "
                        f"{len(self.kanaele)} gewählten Kanälen sind im Agenten nicht aktiv.")
            satz += f"; Kanäle: {aktiv} aktiv" + (f", {aus} vorbereitet und aus" if aus else "")
        return f"Abnahme bestanden: {satz}."

    def zeilen(self) -> list[str]:
        z = [f"== Abnahme: verbotene Anfragen an {self.basis} müssen abgelehnt werden",
             f"Gegenprobe: {self.gegenprobe.titel}: {self.gegenprobe.text}"]
        z += [f"Probe {i}: {b.titel}: {b.text}" for i, b in enumerate(self.proben, 1)]
        z += [f"Kanal: {b.titel}: {b.text}" for b in self.kanaele]
        z.append(self.zusammenfassung())
        for b in [self.gegenprobe, *self.proben, *self.kanaele]:
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
            "befunde": [self.gegenprobe.als_dict(), *[b.als_dict() for b in self.proben],
                        *[b.als_dict() for b in self.kanaele]],
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


# ---------------------------------------------------------------- Kanäle

KANAL_TITEL = {"matrix": "Matrix", "telegram": "Telegram", "whatsapp": "WhatsApp"}
# Läuft im Container des Agenten (Node ist dort): fragt die Brücke des Agenten nach ihrem Stand und gibt nur die
# Wahrheitswerte der Kanäle aus (an, ziel, bereit). Das Gateway-Token liest das Skript aus der eigenen Umgebung und
# gibt es nie aus.
KANAL_ABFRAGE_JS = (
    "const t=process.env.OPENCLAW_GATEWAY_TOKEN||'';const p=process.env.OPENCLAW_GATEWAY_PORT||18789;"
    "fetch('http://127.0.0.1:'+p+'/plugins/fyos-bruecke/v1/rpc',{method:'POST',"
    "headers:{'Authorization':'Bearer '+t,'Content-Type':'application/json'},"
    "body:JSON.stringify({method:'fyos.bruecke.status'})})"
    ".then((r)=>r.json()).then((j)=>console.log(JSON.stringify((j.payload||{}).kanaele??null)))"
    ".catch(()=>console.log('null'))"
)
KANAL_VERSUCHE = 12  # der Agent braucht nach dem Start einen Moment, bis das Gateway antwortet
KANAL_PAUSE_S = 5.0

KanalAbfrage = Callable[[], "dict[str, Any] | None"]


def kanal_abfrage_compose(verzeichnis: Any, lauf: Callable = subprocess.run) -> KanalAbfrage:
    """Fragt den laufenden Agenten (Docker Compose im `verzeichnis`) nach dem Stand seiner Kanäle; None: keine Antwort
    oder ein Agent, dessen Brücke noch keine Kanäle meldet."""

    def abfrage() -> dict[str, Any] | None:
        try:
            r = lauf(["docker", "compose", "exec", "-T", "agent", "node", "-e", KANAL_ABFRAGE_JS],
                     cwd=verzeichnis, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        zeilen = [z for z in (r.stdout or "").splitlines() if z.strip()]
        try:
            stand = json.loads(zeilen[-1]) if zeilen else None
        except ValueError:
            return None
        return stand if isinstance(stand, dict) else None

    return abfrage


def urteil_kanal(kanal: str, soll_aktiv: bool, stand: dict[str, Any] | None) -> Befund:
    """Ein Kanal im Urteil: `aktiv` (der Agent hat ihn an und die Adresse des Besitzers), `aus` (vorbereitet, noch
    nicht eingeschaltet; das ist gewollt, wenn Werte fehlen) oder nicht in Ordnung."""
    titel = f"Kanal {KANAL_TITEL.get(kanal, kanal)}"
    id_ = f"kanal_{kanal}"
    if not soll_aktiv:
        return Befund(id_, titel, True, "aus", "vorbereitet, aber aus: es fehlen noch Werte (siehe Hinweise des Installers)")
    hilfe = ("Im Zielordner `docker compose logs agent` lesen; der Kanal startet nur mit seinen Werten aus .env und dem "
             f"Paket im Bild (agent/Dockerfile), und in fyos.yaml muss kanaele.{kanal} true sein.")
    if stand is None:
        return Befund(id_, titel, False, "unklar",
                      "keine Auskunft vom Agenten (läuft er? ältere Bilder melden ihre Kanäle noch nicht)", hilfe=hilfe)
    e = stand.get(kanal)
    if not isinstance(e, dict):
        return Befund(id_, titel, False, "unklar", "der Agent kennt diesen Kanal nicht", hilfe=hilfe)
    if e.get("bereit") is True:
        return Befund(id_, titel, True, "aktiv", "aktiv im Agenten (eingeschaltet, Adresse des Besitzers gesetzt)")
    if e.get("an") is not True:
        return Befund(id_, titel, False, "unklar", "im Agenten nicht eingeschaltet", hilfe=hilfe)
    return Befund(id_, titel, False, "unklar",
                  "im Agenten eingeschaltet, aber die Adresse des Besitzers fehlt in seiner Umgebung", hilfe=hilfe)


def kanal_proben(
    kanaele: dict[str, bool], abfrage: KanalAbfrage, *, versuche: int = KANAL_VERSUCHE,
    pause_s: float = KANAL_PAUSE_S, schlaf: Callable[[float], None] = time.sleep,
) -> list[Befund]:
    """Je gewähltem Kanal ein Befund. `kanaele` ordnet den Namen zu, ob der Installer ihn eingeschaltet hat. Gefragt wird
    der Agent nur, wenn mindestens ein Kanal an sein soll; er bekommt einige Versuche, weil er nach dem Start noch
    hochfährt."""
    if not kanaele:
        return []
    stand: dict[str, Any] | None = None
    if any(kanaele.values()):
        for i in range(max(1, versuche)):
            stand = abfrage()
            if stand is not None:
                break
            if i + 1 < versuche:
                schlaf(pause_s)
    return [urteil_kanal(k, soll, stand) for k, soll in kanaele.items()]


def kanal_hinweis(ziel: str, kanaele: list[str]) -> str:
    """Satz für Zusammenfassung und Anleitung: die Abnahme prüft auch, ob die gewählten Kanäle im Agenten aktiv sind."""
    namen = ", ".join(KANAL_TITEL.get(k, k) for k in kanaele)
    if ziel == "compose":
        return (f"Abnahme der Kanäle ({namen}): Nach dem Start fragt der Installer den Agenten, ob sie aktiv sind. "
                "Wiederholen: `fyos-install --abnahme http://localhost:<Port> --kanaele "
                f"{','.join(kanaele)}` im Zielordner.")
    return (f"Abnahme der Kanäle ({namen}): läuft nur bei Docker Compose von selbst. Sonst zeigt das Protokoll des "
            "Agenten, ob ein Kanal startet (zum Beispiel `kubectl logs deploy/agent` bzw. `docker compose logs agent`).")


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
