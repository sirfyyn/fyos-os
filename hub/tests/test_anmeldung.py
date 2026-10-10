"""Anmeldung: der Hub als OAuth-Ressourcenserver (optional), geprueft gegen einen Ersatz-Aussteller."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mcp_hub.anmeldung import AnmeldungMiddleware, Konfig, TokenPruefer

ISSUER = "https://id.example/application/o/hub/"
OEFFENTLICH = "https://hub.example"
CLIENT = "client-123"

SCHLUESSEL = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ANDERER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key=SCHLUESSEL, kid="k1") -> dict[str, Any]:
    daten = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**daten, "kid": kid, "alg": "RS256", "use": "sig"}]}


class Lader:
    """Ersatz fuer den HTTP-Abruf: Discovery -> jwks_uri -> Schluessel."""

    def __init__(self) -> None:
        self.aufrufe: list[str] = []
        self.jwks = _jwks()

    def __call__(self, url: str) -> dict[str, Any]:
        self.aufrufe.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return {"issuer": ISSUER, "jwks_uri": "https://id.example/jwks"}
        if url == "https://id.example/jwks":
            return self.jwks
        raise OSError("nicht erreichbar")


def token(*, key=SCHLUESSEL, kid="k1", aud=CLIENT, iss=ISSUER, exp=None, alg="RS256", **rest) -> str:
    anspruch = {"iss": iss, "aud": aud, "exp": exp or int(time.time()) + 600, "sub": "u1", **rest}
    return jwt.encode(anspruch, key, algorithm=alg, headers={"kid": kid})


def konfig(**env: str) -> Konfig:
    basis = {"FYOS_OIDC_ISSUER": ISSUER, "FYOS_OIDC_CLIENTS": CLIENT, "FYOS_OEFFENTLICH_URL": OEFFENTLICH}
    basis.update(env)
    return Konfig.aus_umgebung(basis)


class App:
    """Innere ASGI-App: merkt sich, was durchkam."""

    def __init__(self) -> None:
        self.gesehen: list[dict[str, Any]] = []

    async def __call__(self, scope, receive, send):
        self.gesehen.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"innen"})


async def rufe(mw, pfad="/mcp", host="hub.example", methode="GET", **kopf: str):
    header = [(b"host", host.encode())] + [(k.replace("_", "-").encode(), v.encode()) for k, v in kopf.items()]
    scope = {"type": "http", "method": methode, "path": pfad, "headers": header}
    antworten: list[dict[str, Any]] = []

    async def empfang():
        return {"type": "http.request", "body": b""}

    async def senden(nachricht):
        antworten.append(nachricht)

    await mw(scope, empfang, senden)
    start = next(a for a in antworten if a["type"] == "http.response.start")
    koerper = b"".join(a.get("body", b"") for a in antworten if a["type"] == "http.response.body")
    kopfzeilen = {k.decode(): v.decode() for k, v in start["headers"]}
    return start["status"], kopfzeilen, koerper


def bauen(k: Konfig, lader: Lader | None = None) -> tuple[AnmeldungMiddleware, App, Lader]:
    lader = lader or Lader()
    app = App()
    return AnmeldungMiddleware(app, "/mcp", k, TokenPruefer(k, lader=lader)), app, lader


# ── Konfiguration ───────────────────────────────────────────────────────────
def test_ohne_aussteller_ist_die_anmeldung_aus():
    k = Konfig.aus_umgebung({})
    assert k.modus == "aus" and k.wirksam == "aus" and not k.bereit


def test_mit_aussteller_gilt_an():
    assert konfig().wirksam == "an"


def test_modus_ohne_zielgruppe_oeffnet_nichts():
    k = Konfig.aus_umgebung({"FYOS_OIDC_ISSUER": ISSUER, "FYOS_OIDC_MODUS": "an"})
    assert not k.bereit and k.wirksam == "aus"


def test_unbekannter_modus_gilt_als_aus():
    assert konfig(FYOS_OIDC_MODUS="irgendwas").wirksam == "aus"


def test_hub_call_bleibt_draussen():
    k = konfig(FYOS_OIDC_REST="/hub/call,/hub/app-call,ohne-schraegstrich")
    assert k.rest == ("/hub/app-call",)


def test_benutzerliste():
    assert konfig().benutzer_erlaubt("irgendwer")
    k = konfig(FYOS_OIDC_BENUTZER="anna,ben")
    assert k.benutzer_erlaubt("anna") and not k.benutzer_erlaubt("carl")


# ── Innen und aussen ────────────────────────────────────────────────────────
async def test_innen_bleibt_offen():
    mw, app, _ = bauen(konfig())
    status, _, koerper = await rufe(mw, "/mcp", host="hub.intern")
    assert status == 200 and koerper == b"innen" and len(app.gesehen) == 1
    status, _, _ = await rufe(mw, "/hub/call", host="hub.intern")
    assert status == 200


async def test_aussen_ohne_modus_ist_verboten():
    mw, app, _ = bauen(Konfig.aus_umgebung({}))
    status, _, _ = await rufe(mw, "/mcp", x_fyos_zugang="extern")
    assert status == 403 and not app.gesehen


async def test_aussen_ohne_token_bekommt_die_herausforderung():
    mw, app, _ = bauen(konfig())
    status, kopf, _ = await rufe(mw, "/mcp", x_fyos_zugang="extern")
    assert status == 401 and not app.gesehen
    assert 'resource_metadata="https://hub.example/.well-known/oauth-protected-resource/mcp"' in kopf["www-authenticate"]


async def test_metadaten_fuer_den_client():
    mw, _, _ = bauen(konfig())
    status, _, koerper = await rufe(mw, "/.well-known/oauth-protected-resource/mcp", x_fyos_zugang="extern")
    dok = json.loads(koerper)
    assert status == 200 and dok["resource"] == "https://hub.example/mcp"
    assert dok["authorization_servers"] == [ISSUER]


async def test_gueltiges_token_kommt_durch_ohne_token_weiterzureichen():
    mw, app, lader = bauen(konfig())
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(), x_fyos_zugang="extern", x_hub_caller="agent-vorgetaeuscht")
    assert status == 200
    kopf = dict(app.gesehen[0]["headers"])
    assert b"authorization" not in kopf
    assert kopf[b"x-hub-caller"] == f"oauth:{CLIENT}".encode()
    assert lader.aufrufe[0].endswith("/.well-known/openid-configuration")


async def test_zielgruppe_ist_auch_die_ressourcenadresse():
    mw, _, _ = bauen(konfig())
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(aud="https://hub.example/mcp"), x_fyos_zugang="extern")
    assert status == 200


@pytest.mark.parametrize(
    "fehler",
    [
        {"aud": "fremd"},
        {"iss": "https://boese.example/"},
        {"exp": 1},
        {"key": ANDERER},
    ],
)
async def test_falsche_token_werden_abgelehnt(fehler):
    mw, app, _ = bauen(konfig())
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(**fehler), x_fyos_zugang="extern")
    assert status == 401 and not app.gesehen


async def test_hs256_wird_nie_angenommen():
    mw, app, _ = bauen(konfig())
    t = jwt.encode({"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 60}, "x" * 40, algorithm="HS256", headers={"kid": "k1"})
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + t, x_fyos_zugang="extern")
    assert status == 401 and not app.gesehen


async def test_fremder_aussteller_loest_keinen_abruf_aus():
    mw, _, lader = bauen(konfig())
    await rufe(mw, "/mcp", authorization="Bearer " + token(iss="https://boese.example/"), x_fyos_zugang="extern")
    assert lader.aufrufe == []


async def test_schluessel_nicht_ladbar_gibt_503():
    class Tot(Lader):
        def __call__(self, url):
            raise OSError("weg")

    mw, _, _ = bauen(konfig(), Tot())
    status, kopf, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(), x_fyos_zugang="extern")
    assert status == 503 and kopf["retry-after"] == "10"


async def test_unerlaubter_benutzer_gibt_403():
    mw, _, _ = bauen(konfig(FYOS_OIDC_BENUTZER="anna"))
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(preferred_username="carl"), x_fyos_zugang="extern")
    assert status == 403
    status, _, _ = await rufe(mw, "/mcp", authorization="Bearer " + token(preferred_username="anna"), x_fyos_zugang="extern")
    assert status == 200


# ── Aussenhost ──────────────────────────────────────────────────────────────
async def test_aussenhost_zeigt_nur_mcp_und_app_weg():
    mw, app, _ = bauen(konfig(FYOS_OIDC_HOSTS="hub.example"))
    status, _, _ = await rufe(mw, "/hub/call", host="hub.example")
    assert status == 404 and not app.gesehen
    status, _, _ = await rufe(mw, "/hub/app-call", host="hub.example", methode="POST")
    assert status == 401  # erreichbar, aber nur mit Token
    status, _, _ = await rufe(mw, "/hub/app-call", host="hub.example", methode="POST", authorization="Bearer " + token())
    assert status == 200


# ── Streng ──────────────────────────────────────────────────────────────────
async def test_streng_verlangt_auch_innen_ein_token():
    mw, app, _ = bauen(konfig(FYOS_OIDC_MODUS="streng"))
    status, _, _ = await rufe(mw, "/mcp", host="hub.intern")
    assert status == 401 and not app.gesehen
    status, _, _ = await rufe(mw, "/hub/health", host="hub.intern")
    assert status == 200  # nur /mcp und die Metadaten sind geschuetzt
