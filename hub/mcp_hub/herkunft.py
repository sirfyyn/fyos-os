"""herkunft — schreibende Hub-Wege gegen fremde Webseiten im Browser absichern.

Im eigenen Netz ist der Hub offen: wer `/hub-api/app-call` erreicht, braucht keine Anmeldung. Ein Browser macht
daraus eine Lücke: eine beliebige Webseite im Browser des Besitzers kann einen *einfachen* POST
(`Content-Type: text/plain`, kein Preflight) an die Adresse der Installation schicken, und dieser Browser sitzt im
Heimnetz. Antwort lesen kann die Seite nicht (kein CORS) — auslösen schon. Ein Reverse-Proxy, der beim Weiterreichen
`Content-Type: application/json` erzwingt, würde aus dem text/plain-Text zudem einen JSON-Aufruf machen.

Zwei Riegel, beide ohne Anmeldung (keine neue Berechtigungsschicht):

1. **Herkunft.** Schreibende Methoden (POST/PUT/PATCH/DELETE) unter `/hub/` lehnen Anfragen ab (403), wenn
   `Sec-Fetch-Site: cross-site` gesetzt ist ODER ein `Origin`-Kopf da ist, dessen Host nicht in der Liste steht.
   Anfragen ohne `Origin` (curl, Server-zu-Server, Agenten im selben Netz) bleiben erlaubt: einen
   Browser erkennt man an diesen Köpfen, und er kann sie von einer Webseite aus nicht weglassen oder fälschen
   (verbotene Kopfnamen). `Origin: null` (Sandbox-iframe, Weiterleitungen) gilt als fremd.
   Der Host der Anfrage (`Host`) zählt NICHT als eigene Herkunft: DNS-Rebinding ließe eine fremde Domain sonst
   auf die LAN-Adresse zeigen, mit gleichem `Host` und `Origin`.
2. **Inhaltstyp.** Die JSON-Wege (`/hub/call`, `/hub/mehr`, `/hub/app-call`, `/hub/os/melden`, `/hub/os/antwort`)
   verlangen `application/json` (415 sonst). Ein Formular oder `text/plain` ohne Preflight kann das nicht senden;
   `application/json` cross-origin löst einen Preflight aus, den der Hub nie beantwortet.

Erlaubte Hosts (der Port zählt nicht): die Hosts aus `FYOS_ERLAUBTE_HOSTS` (kommagetrennt, Host oder volle Herkunft)
und der Host von `FYOS_OEFFENTLICH_URL`, dazu immer `localhost` und `127.0.0.1` (Entwicklung).
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

# Immer erlaubt: lokale Entwicklung.
ERLAUBTE_VORGABE = ("localhost", "127.0.0.1")

SCHREIBEND = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Wege, die einen JSON-Körper lesen.
JSON_WEGE = frozenset({"/hub/call", "/hub/mehr", "/hub/app-call", "/hub/os/melden", "/hub/os/antwort"})


def erlaubte_hosts(roh: str | None = None) -> frozenset[str]:
    """Erlaubte Hosts: `FYOS_ERLAUBTE_HOSTS`, Host von `FYOS_OEFFENTLICH_URL` und die lokalen Vorgaben.

    ``roh`` ersetzt die Liste aus der Umgebung (Tests); Einträge dürfen volle Herkünfte sein.
    """
    wert = os.getenv("FYOS_ERLAUBTE_HOSTS", "") if roh is None else roh
    eintraege = [e.strip() for e in wert.split(",") if e.strip()]
    if roh is None:
        eintraege.append(os.getenv("FYOS_OEFFENTLICH_URL", "").strip())
    eintraege.extend(ERLAUBTE_VORGABE)
    hosts: set[str] = set()
    for e in eintraege:
        if not e:
            continue
        host = urlparse(e if "://" in e else f"//{e}").hostname
        if host:
            hosts.add(host.lower())
    return frozenset(hosts)


def herkunft_host(origin: str) -> str | None:
    """Host aus einem Origin-Kopf; `null` und Unlesbares ergeben None (= fremd)."""
    if not origin or origin.strip().lower() == "null":
        return None
    try:
        teile = urlparse(origin.strip())
    except ValueError:
        return None
    if teile.scheme not in ("http", "https"):
        return None
    return (teile.hostname or "").lower() or None


def ablehnung(methode: str, pfad: str, kopf: dict[str, str], hosts: frozenset[str]) -> tuple[int, str, str] | None:
    """`(status, kind, meldung)`, wenn die Anfrage abzulehnen ist, sonst None. `kopf`: kleingeschriebene Namen."""
    if not pfad.startswith("/hub/") or methode.upper() not in SCHREIBEND:
        return None
    if (kopf.get("sec-fetch-site") or "").strip().lower() == "cross-site":
        return (
            403,
            "fremde_herkunft",
            "Schreibende Hub-Wege lehnen Anfragen von fremden Webseiten ab (Sec-Fetch-Site: cross-site).",
        )
    origin = kopf.get("origin")
    if origin is not None and herkunft_host(origin) not in hosts:
        return (
            403,
            "fremde_herkunft",
            f"Schreibende Hub-Wege lehnen Anfragen mit fremdem Origin ab ({origin[:80]!r}); "
            "erlaubt sind die eigenen Hosts (FYOS_ERLAUBTE_HOSTS, FYOS_OEFFENTLICH_URL).",
        )
    if pfad in JSON_WEGE:
        typ = (kopf.get("content-type") or "").split(";", 1)[0].strip().lower()
        if typ != "application/json":
            return (415, "bad_content_type", "Dieser Weg verlangt Content-Type: application/json.")
    return None


class HerkunftMiddleware:
    """Reine ASGI-Middleware: lehnt fremde Browser-Herkunft und falschen Inhaltstyp ab, bevor irgendetwas läuft."""

    def __init__(self, app: Any, hosts: frozenset[str] | None = None) -> None:
        self.app = app
        self.hosts = hosts if hosts is not None else erlaubte_hosts()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            kopf = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            urteil = ablehnung(str(scope.get("method") or ""), str(scope.get("path") or ""), kopf, self.hosts)
            if urteil is not None:
                status, kind, meldung = urteil
                koerper = json.dumps({"ok": False, "error": meldung, "kind": kind}, ensure_ascii=False).encode()
                await send({
                    "type": "http.response.start",
                    "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(koerper)).encode())],
                })
                await send({"type": "http.response.body", "body": koerper})
                return
        await self.app(scope, receive, send)
