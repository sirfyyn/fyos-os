"""anmeldung — der Hub als OAuth-Ressourcenserver (MCP-Autorisierung, RFC 9728), optional.

Ein Client (Chat-Konnektor, Code-Agent, eigener Client) liest `WWW-Authenticate` und die Protected Resource
Metadata, meldet sich bei einem beliebigen OpenID-Connect-Anbieter an (Authentik, Keycloak, Zitadel, Auth0 …)
und ruft den Hub mit `Authorization: Bearer …` auf. Der Hub prüft das Token selbst.

## Wer gilt als „außen“

Innen ist der Hub offen (Einzelplatz im eigenen Netz): Browser-Shell, Skripte und Agenten im selben Netz rufen
`/hub/*` und `/mcp` ohne Token. Die Anmeldung betrifft nur den **MCP-Endpunkt** (`/mcp`) und die Metadaten:

* Anfrage mit `X-FYOS-Zugang: extern` an `/mcp` — diese Kennung setzt der Reverse-Proxy auf jede Anfrage aus dem
  Internet: außen.
* Anfrage an einen **Außenhost** (`FYOS_OIDC_HOSTS`, Vorgabe: keiner): gilt immer als außen. Dort sind nur `/mcp`,
  die Metadaten und die REST-Wege aus `FYOS_OIDC_REST` (Vorgabe `/hub/app-call`) erreichbar, alles andere
  antwortet 404.
* Alles andere ist innen und bleibt offen. Ein `Authorization`-Kopf wird innen nicht ausgewertet.

## Schalter `FYOS_OIDC_MODUS`

* `aus`: Außen-Anfragen an `/mcp` und die Metadaten antworten 403 (nichts wird ungeprüft nach außen gegeben).
  Das ist die Vorgabe, solange `FYOS_OIDC_ISSUER` fehlt: Anmeldung ist abgeschaltet.
* `an`: Anfragen von außen verlangen ein gültiges Token. Vorgabe, sobald `FYOS_OIDC_ISSUER` gesetzt ist.
* `streng`: jede Anfrage an `/mcp` verlangt ein Token, auch von innen (Hub ohne Reverse-Proxy im Internet).

Fehlt der Aussteller oder gibt es weder Client-Liste noch öffentliche URL als Zielgruppe, gilt `aus`
(Fehlkonfiguration öffnet nichts).

## Token-Prüfung

JWT: Signatur gegen die JWKS des Ausstellers (nur RS256/ES256/EdDSA, nie HS256 oder `none`), Aussteller
aus `FYOS_OIDC_ISSUER` (genau gleich), Ablauf, Zielgruppe. Die JWKS-Adresse kommt aus der Discovery
(`<aussteller>/.well-known/openid-configuration`, `jwks_uri`); `FYOS_OIDC_JWKS_URL` setzt sie fest (nur bei einem
Aussteller). Erlaubt ist jede Client-ID aus `FYOS_OIDC_CLIENTS`; die Adresse der Ressource (`<öffentliche URL>/mcp`)
gilt zusätzlich als Zielgruppe. Optional nur bestimmte Benutzer (`FYOS_OIDC_BENUTZER`, Vorgabe `*` = jeder, der sich
beim Anbieter für diese Anwendung anmelden darf). Das Token wird nicht weitergereicht: der `Authorization`-Kopf wird
entfernt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import jwt

logger = logging.getLogger("mcp_hub.anmeldung")

MODI = ("aus", "an", "streng")
#: Nur asymmetrische Verfahren. Ein Anbieter ohne Signaturschlüssel signiert mit HS256 (Client-Secret) -- das lehnen wir ab.
ALGORITHMEN = ["RS256", "ES256", "EdDSA"]
WELL_KNOWN_PRM = "/.well-known/oauth-protected-resource"
KENNUNG_KOPF = "x-fyos-zugang"
JWKS_LEBENSDAUER_S = 600.0
JWKS_MINDESTABSTAND_S = 30.0
JWKS_NOTFALL_S = 86400.0  # ist der Anbieter kurz weg, gelten bekannte Schlüssel noch einen Tag
JWKS_PAUSE_NACH_FEHLER_S = 10.0


def _liste(wert: str | None, vorgabe: tuple[str, ...] = ()) -> tuple[str, ...]:
    if wert is None:
        return vorgabe
    return tuple(t.strip() for t in wert.replace("\n", ",").split(",") if t.strip())


@dataclass(frozen=True)
class Konfig:
    modus: str = "aus"
    #: Außenhosts: Anfragen an diese Namen gelten immer als außen (leer = nur die Kennung `X-FYOS-Zugang: extern`).
    hosts: tuple[str, ...] = ()
    #: REST-Wege, die auf den Außenhosts mit Token erreichbar sind. Nie /hub/call.
    rest: tuple[str, ...] = ("/hub/app-call",)
    issuer: tuple[str, ...] = ()
    clients: tuple[str, ...] = ()
    #: Öffentliche URL der Installation (FYOS_OEFFENTLICH_URL): ihre `/mcp`-Adresse gilt als Zielgruppe.
    oeffentlich: str = ""
    benutzer: tuple[str, ...] = ("*",)
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    jwks_url: str = ""
    leeway_s: int = 10

    @classmethod
    def aus_umgebung(cls, env: dict[str, str] | None = None) -> "Konfig":
        e = os.environ if env is None else env
        issuer = _liste(e.get("FYOS_OIDC_ISSUER"))
        vorgabe_modus = "an" if issuer else "aus"
        modus = (e.get("FYOS_OIDC_MODUS") or vorgabe_modus).strip().lower()
        if modus not in MODI:
            logger.warning("FYOS_OIDC_MODUS=%r unbekannt -- gilt als 'aus'", modus)
            modus = "aus"
        try:
            leeway = int(e.get("FYOS_OIDC_LEEWAY_S") or 10)
        except ValueError:
            leeway = 10
        return cls(
            modus=modus,
            hosts=tuple(h.lower() for h in _liste(e.get("FYOS_OIDC_HOSTS"), cls.hosts)),
            # /hub/call bleibt draußen, auch wenn jemand es einträgt: dahinter liegen alle Werkzeuge
            rest=tuple(p for p in _liste(e.get("FYOS_OIDC_REST"), cls.rest) if p.startswith("/") and p != "/hub/call"),
            issuer=issuer,
            clients=_liste(e.get("FYOS_OIDC_CLIENTS")),
            oeffentlich=(e.get("FYOS_OEFFENTLICH_URL") or "").strip().rstrip("/"),
            benutzer=_liste(e.get("FYOS_OIDC_BENUTZER"), cls.benutzer),
            scopes=_liste(e.get("FYOS_OIDC_SCOPES"), cls.scopes),
            jwks_url=(e.get("FYOS_OIDC_JWKS_URL") or "").strip(),
            leeway_s=max(0, min(leeway, 120)),
        )

    @property
    def bereit(self) -> bool:
        return bool(self.issuer and (self.clients or self.oeffentlich))

    @property
    def wirksam(self) -> str:
        """Der Modus, der tatsächlich gilt: ohne Aussteller und Zielgruppe immer `aus`."""
        return self.modus if self.bereit else "aus"

    def benutzer_erlaubt(self, name: str) -> bool:
        return not self.benutzer or "*" in self.benutzer or name in self.benutzer


class TokenAbgelehnt(Exception):
    """Das Token taugt nicht (401). `grund` ist ein kurzes, unbedenkliches Stichwort."""

    def __init__(self, grund: str) -> None:
        super().__init__(grund)
        self.grund = grund


class PruefungUnmoeglich(Exception):
    """Aussteller nicht erreichbar und keine bekannten Schlüssel (503, nicht 401: der Client soll nicht neu anmelden)."""


def json_laden(url: str) -> dict[str, Any]:
    """Standard-Lader: JSON per HTTP (höchstens 1 MB)."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("nur http(s)")
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 -- Adresse kommt aus der Konfiguration
        roh = r.read(1_000_001)
    if len(roh) > 1_000_000:
        raise ValueError("Antwort zu groß")
    return json.loads(roh.decode())


# Alter Name, falls jemand den Lader per Namen einsetzt.
jwks_laden = json_laden


@dataclass
class _Schluessel:
    zeit: float = 0.0
    keys: dict[str, Any] = field(default_factory=dict)


class TokenPruefer:
    """Prüft OIDC-Token: Signatur (JWKS-Zwischenspeicher je Aussteller), Aussteller, Ablauf, Zielgruppe."""

    def __init__(
        self,
        konfig: Konfig,
        lader: Callable[[str], dict[str, Any]] = json_laden,
        uhr: Callable[[], float] = time.monotonic,
    ) -> None:
        self.konfig = konfig
        self._lader = lader
        self._uhr = uhr
        self._cache: dict[str, _Schluessel] = {}
        self._sperren: dict[str, asyncio.Lock] = {}
        self._fehlversuch: dict[str, float] = {}

    def _jwks_holen(self, issuer: str) -> dict[str, Any]:
        """JWKS des Ausstellers (läuft im Arbeitsthread): feste Adresse, sonst über die Discovery."""
        if self.konfig.jwks_url and len(self.konfig.issuer) == 1:
            return self._lader(self.konfig.jwks_url)
        entdeckung = self._lader(issuer.rstrip("/") + "/.well-known/openid-configuration")
        if isinstance(entdeckung, dict) and "keys" in entdeckung:
            return entdeckung  # der Lader hat gleich die Schlüsselliste geliefert
        adresse = entdeckung.get("jwks_uri") if isinstance(entdeckung, dict) else None
        if not isinstance(adresse, str) or not adresse:
            raise ValueError("Discovery ohne jwks_uri")
        return self._lader(adresse)

    async def _schluessel(self, issuer: str, kid: str | None) -> Any:
        """Öffentlicher Schlüssel zu `kid`.

        Die Liste gilt 10 Minuten. Kennt sie die `kid` nicht, wird sie höchstens alle 30 Sekunden neu geholt (Schlüsseltausch
        beim Anbieter, aber kein Abruf-Hagel durch erfundene `kid`). Ist der Anbieter nicht erreichbar, gelten bekannte
        Schlüssel bis zu einem Tag weiter; ein fehlgeschlagener Abruf wird frühestens nach 10 Sekunden wiederholt.
        """
        eintrag = self._cache.get(issuer)
        jetzt = self._uhr()
        if eintrag is not None and kid in eintrag.keys and jetzt - eintrag.zeit <= JWKS_LEBENSDAUER_S:
            return eintrag.keys[kid]
        if eintrag is not None and kid not in eintrag.keys and jetzt - eintrag.zeit <= JWKS_MINDESTABSTAND_S:
            raise TokenAbgelehnt("unknown key")
        async with self._sperren.setdefault(issuer, asyncio.Lock()):
            eintrag = self._cache.get(issuer)  # ein gleichzeitiger Aufruf kann inzwischen geladen haben
            jetzt = self._uhr()
            if eintrag is not None and jetzt - eintrag.zeit <= JWKS_MINDESTABSTAND_S:
                if kid in eintrag.keys:
                    return eintrag.keys[kid]
                raise TokenAbgelehnt("unknown key")
            if jetzt - self._fehlversuch.get(issuer, -1e9) > JWKS_PAUSE_NACH_FEHLER_S:
                try:
                    roh = await asyncio.to_thread(self._jwks_holen, issuer)
                    keys: dict[str, Any] = {}
                    for k in roh.get("keys", []):
                        if not isinstance(k, dict) or "kid" not in k:
                            continue
                        try:
                            keys[k["kid"]] = jwt.PyJWK(k).key
                        except Exception:  # noqa: BLE001 -- ein unbrauchbarer Eintrag verwirft nicht die ganze Liste
                            continue
                    if not keys:
                        raise ValueError("JWKS ohne brauchbare Schlüssel")
                    eintrag = _Schluessel(self._uhr(), keys)
                    self._cache[issuer] = eintrag
                    self._fehlversuch.pop(issuer, None)
                except Exception as e:  # noqa: BLE001
                    self._fehlversuch[issuer] = self._uhr()
                    logger.warning("JWKS von %s nicht ladbar: %s", issuer, type(e).__name__)
            if eintrag is None or self._uhr() - eintrag.zeit > JWKS_NOTFALL_S:
                raise PruefungUnmoeglich("jwks")
            if kid in eintrag.keys:
                return eintrag.keys[kid]
            if self._uhr() - eintrag.zeit > JWKS_MINDESTABSTAND_S:
                raise PruefungUnmoeglich("jwks")  # Abruf misslungen: nicht als „Token ungültig“ ausgeben
            raise TokenAbgelehnt("unknown key")

    async def pruefe(self, token: str, ressourcen: list[str]) -> dict[str, Any]:
        """Gibt die Ansprüche zurück oder wirft TokenAbgelehnt / PruefungUnmoeglich."""
        try:
            kopf = jwt.get_unverified_header(token)
            ungeprueft = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            raise TokenAbgelehnt("malformed token") from e
        if kopf.get("alg") not in ALGORITHMEN:
            raise TokenAbgelehnt("unsupported algorithm")
        issuer = ungeprueft.get("iss")
        # Erst jetzt wird irgendetwas geladen: ein fremder Aussteller löst keinen Abruf aus.
        if not isinstance(issuer, str) or issuer not in self.konfig.issuer:
            raise TokenAbgelehnt("unknown issuer")
        schluessel = await self._schluessel(issuer, kopf.get("kid"))
        try:
            return jwt.decode(
                token,
                key=schluessel,
                algorithms=ALGORITHMEN,
                audience=list(self.konfig.clients) + list(ressourcen),
                issuer=issuer,
                leeway=self.konfig.leeway_s,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenAbgelehnt("token expired") from e
        except jwt.InvalidAudienceError as e:
            raise TokenAbgelehnt("wrong audience") from e
        except jwt.InvalidSignatureError as e:
            raise TokenAbgelehnt("bad signature") from e
        except Exception as e:  # noqa: BLE001 -- auch TypeError/ValueError (Algorithmus passt nicht zum Schlüssel): 401, nie 500
            raise TokenAbgelehnt("invalid token") from e


def _kopf_dict(scope: Any) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}


def _hostname(wert: str) -> str:
    """Rechnername ohne Port und ohne Liste (`X-Forwarded-Host` kann mehrere nennen), klein geschrieben."""
    erster = wert.split(",")[0].strip().lower()
    return erster if erster.startswith("[") else erster.split(":")[0]


class AnmeldungMiddleware:
    """Reine ASGI-Middleware: schützt `/mcp` für Anfragen von außen und liefert die Metadaten (RFC 9728)."""

    def __init__(
        self,
        app: Any,
        mcp_pfad: str = "/mcp",
        konfig: Konfig | None = None,
        pruefer: TokenPruefer | None = None,
    ) -> None:
        self.app = app
        self.mcp_pfad = "/" + mcp_pfad.strip("/")
        self.konfig = konfig or Konfig.aus_umgebung()
        self.pruefer = pruefer or TokenPruefer(self.konfig)
        if self.konfig.modus != "aus" and not self.konfig.bereit:
            logger.warning(
                "FYOS_OIDC_MODUS=%s, aber FYOS_OIDC_ISSUER und FYOS_OIDC_CLIENTS (oder FYOS_OEFFENTLICH_URL) fehlen -- es gilt 'aus'",
                self.konfig.modus,
            )
        logger.info(
            "Hub-Anmeldung: modus=%s (eingestellt %s), hosts=%s, aussteller=%d, clients=%d",
            self.konfig.wirksam,
            self.konfig.modus,
            ",".join(self.konfig.hosts) or "-",
            len(self.konfig.issuer),
            len(self.konfig.clients),
        )

    # -- Hilfen ---------------------------------------------------------------
    def _ressource(self, basis: str) -> str:
        return f"{basis}{self.mcp_pfad}"

    def _prm_adresse(self, basis: str) -> str:
        return f"{basis}{WELL_KNOWN_PRM}{self.mcp_pfad}"

    def prm_dokument(self, basis: str) -> dict[str, Any]:
        return {
            "resource": self._ressource(basis),
            "authorization_servers": list(self.konfig.issuer),
            "scopes_supported": list(self.konfig.scopes),
            "bearer_methods_supported": ["header"],
            "resource_name": "FYOS MCP-Hub",
        }

    def _herausforderung(self, basis: str, fehler: str | None = None, beschreibung: str | None = None) -> str:
        teile = ['Bearer realm="fyos-hub"']
        if fehler:
            teile.append(f'error="{fehler}"')
        if beschreibung:
            teile.append(f'error_description="{beschreibung}"')
        teile.append(f'resource_metadata="{self._prm_adresse(basis)}"')
        if self.konfig.scopes:
            teile.append(f'scope="{" ".join(self.konfig.scopes)}"')
        return ", ".join(teile)

    @staticmethod
    async def _antwort(
        send: Any, status: int, koerper: dict[str, Any], kopf: dict[str, str] | None = None
    ) -> None:
        roh = json.dumps(koerper, ensure_ascii=False).encode()
        header = [(b"content-type", b"application/json"), (b"content-length", str(len(roh)).encode())]
        for k, v in (kopf or {}).items():
            header.append((k.lower().encode("latin-1"), v.encode("latin-1")))
        await send({"type": "http.response.start", "status": status, "headers": header})
        await send({"type": "http.response.body", "body": roh})

    def _oeffentlicher_host(self) -> str:
        return (urlparse(self.konfig.oeffentlich).hostname or "").lower() if self.konfig.oeffentlich else ""

    # -- Ablauf ---------------------------------------------------------------
    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        modus = self.konfig.wirksam
        kopf = _kopf_dict(scope)
        pfad = str(scope.get("path") or "")
        host = _hostname(kopf.get("host", ""))
        weitergeleitet = _hostname(kopf.get("x-forwarded-host", ""))
        aussenhost = host in self.konfig.hosts or weitergeleitet in self.konfig.hosts
        kennung = kopf.get(KENNUNG_KOPF, "").strip().lower() == "extern"
        ist_mcp = pfad == self.mcp_pfad or pfad.startswith(self.mcp_pfad + "/")
        ist_prm = pfad == WELL_KNOWN_PRM or pfad.startswith(WELL_KNOWN_PRM + "/")
        ist_rest = aussenhost and pfad in self.konfig.rest
        streng = modus == "streng" and (ist_mcp or ist_prm)

        if not aussenhost and not streng and not (kennung and (ist_mcp or ist_prm)):
            await self.app(scope, receive, send)  # innen (oder /hub/* mit weitergereichter Kennung): unverändert
            return
        if aussenhost and not (ist_mcp or ist_prm or ist_rest):
            await self._antwort(send, 404, {"error": "not_found"})
            return

        zugelassen = modus in ("an", "streng")
        if not zugelassen:
            await self._antwort(send, 403, {"error": "forbidden"})
            return
        # Adresse der Ressource: so, wie der Client uns gerufen hat (der Proxy reicht Host und X-Forwarded-Proto durch).
        name = host if host in self.konfig.hosts or weitergeleitet not in self.konfig.hosts else weitergeleitet
        if not name:
            await self._antwort(send, 400, {"error": "host fehlt"})
            return
        roh = kopf.get("host", "") if name == host else kopf.get("x-forwarded-host", "").split(",")[0]
        vorgabe = "http" if name in ("127.0.0.1", "localhost", "[::1]") else "https"
        schema = kopf.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        basis = f"{schema if schema in ('http', 'https') else vorgabe}://{roh.strip().lower()}"
        # Die Ressourcenadresse zählt nur auf unserem eigenen Namen als Zielgruppe (der Host-Kopf ist nicht vertrauenswürdig):
        # auf einem Außenhost oder auf dem Host der öffentlichen URL.
        eigene = set(self.konfig.hosts) | ({self._oeffentlicher_host()} - {""})
        ressourcen = [self._ressource(basis)] if name in eigene else []
        if self.konfig.oeffentlich:
            ressourcen.append(self._ressource(self.konfig.oeffentlich))

        if ist_prm:
            if scope.get("method") not in ("GET", "HEAD"):
                await self._antwort(send, 405, {"error": "method_not_allowed"}, {"Allow": "GET, HEAD"})
                return
            await self._antwort(send, 200, self.prm_dokument(basis), {"Cache-Control": "public, max-age=300"})
            return

        await self._geschuetzt(scope, receive, send, kopf, basis, ressourcen)

    async def _geschuetzt(
        self, scope: Any, receive: Any, send: Any, kopf: dict[str, str], basis: str, ressourcen: list[str]
    ) -> None:
        auth = kopf.get("authorization", "")
        if not auth:
            await self._antwort(
                send, 401, {"error": "unauthorized"}, {"WWW-Authenticate": self._herausforderung(basis)}
            )
            return
        schema, _, token = auth.partition(" ")
        if schema.lower() != "bearer" or not token.strip():
            await self._antwort(
                send,
                401,
                {"error": "invalid_request"},
                {"WWW-Authenticate": self._herausforderung(basis, "invalid_request", "bearer token required")},
            )
            return
        try:
            anspruch = await self.pruefer.pruefe(token.strip(), ressourcen)
        except TokenAbgelehnt as e:
            logger.info("abgelehnt: %s", e.grund)
            await self._antwort(
                send,
                401,
                {"error": "invalid_token", "error_description": e.grund},
                {"WWW-Authenticate": self._herausforderung(basis, "invalid_token", e.grund)},
            )
            return
        except PruefungUnmoeglich:
            await self._antwort(send, 503, {"error": "temporarily_unavailable"}, {"Retry-After": "10"})
            return
        name = str(anspruch.get("preferred_username") or anspruch.get("email") or anspruch.get("sub") or "")
        if not self.konfig.benutzer_erlaubt(name):
            logger.info("abgelehnt: Benutzer nicht erlaubt")
            await self._antwort(send, 403, {"error": "forbidden", "error_description": "user not allowed"})
            return
        ziel = anspruch.get("aud")
        ziel = ziel[0] if isinstance(ziel, list) and ziel else ziel
        logger.info("angemeldet: %s (%s)", name or "?", ziel)
        # Das Token endet hier (kein Durchreichen); den Aufrufer setzen wir selbst, ein mitgeschickter zählt nicht.
        neu = [
            (k, v)
            for k, v in scope.get("headers") or []
            if k.lower() not in (b"authorization", b"x-hub-caller")
        ]
        neu.append((b"x-hub-caller", f"oauth:{str(ziel)[:40]}".encode("latin-1", "replace")))
        await self.app({**scope, "headers": neu}, receive, send)
