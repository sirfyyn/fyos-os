"""agent — Eingang und Ausgang eines Agenten-Runners über den Hub (HTTP-Wege, keine Werkzeuge).

Ein Agenten-Runner (ein Modell-Agent im RPC-Modus, etwa als Systemdienst auf einem Rechenknoten) braucht zwei
Ströme, ohne selbst an Redis zu kommen:

* **Eingang** `fyos:agent:eingang` (Vertrag `_agenteneingang.py`): Quellen werfen Ereignisse ein (Web-Chat, Matrix,
  Vorgangssystem, Zeitplan, Beobachtungen, Alarme), der Runner liest per Long-Poll.
* **Ausgang** `fyos:agent` (Vertrag `_agentenstrom.py`): der Runner meldet gebündelt, was in seiner Sitzung geschieht
  (Text in Stücken, Werkzeugläufe, Pläne, Vorschläge, Verbrauch, Fehler); Oberflächen und Brücken lesen nur diesen
  Strom.

Wege:
    POST /hub/agent/eingang   ein Ereignis einwerfen {"quelle", "text", "klasse"?, "bezug"?, "von"?, "schwere"?,
                              "agent"?} → {"ok": true, "id"}
    GET  /hub/agent/eingang   ?nach=<id>&warte=<s>&anzahl=<n>&agent=<id> → {"ok": true, "eintraege", "letzte"}
    POST /hub/agent/melden    {"ereignisse": […]} → {"ok": true, "angenommen": n}
    POST /hub/agent/alarm     Alertmanager-Webhook (v4) → Alarme im Eingang, entprellt (`_agentenalarm.py`)
                              → {"ok": true, "eingeworfen": [{id, bezug}], "uebersprungen": n}
    GET  /hub/agent/strom     den Ausgang mitlesen: ?nach=<id>&warte=<s>&anzahl=<n>&agent=<id>&sitzung=<id>
                              → {"ok": true, "eintraege", "letzte"} (Long-Poll); mit `Accept: text/event-stream`
                              als SSE (`id:` = Strom-ID `sid`, `event: ereignis`, `data:` = Eintrag; `Last-Event-ID`
                              setzt fort). Für Oberflächen und den Terminal-Anschluss (Web-Chat, pi-Erweiterung).

Warum Wege und keine Werkzeuge: Meldungen und Long-Poll sind Telemetrie des Runner-Prozesses; als Werkzeug stünden
sie in der Werkzeugliste jedes Modells und im Audit.

## Quellen-Tokens

Ohne Tokens ist das Plugin innen offen wie der übrige Hub, und `quelle` kommt aus dem Rumpf. Mit Tokens
(`tokens` in der Konfiguration, besser Umgebung `FYOS_AGENT_TOKENS` oder Geheimnis gleichen Namens) gehört jedes
Token genau einer Rolle:

    <quelle>  eine aus `_agenteneingang.QUELLEN`: darf nur `POST /hub/agent/eingang`, und `quelle` ist dann die Rolle
              des Tokens — was im Rumpf steht, zählt nicht (eine Hintergrundquelle kann sich nicht als Benutzer
              ausgeben)
    alarm     zusätzlich `POST /hub/agent/alarm`
    runner    `POST /hub/agent/melden` und `GET /hub/agent/eingang`
    max, web  zusätzlich `GET /hub/agent/strom` (Mitlesen: Terminal-Anschluss des Benutzers, Web-Oberfläche)

Format: `rolle=token`, getrennt durch Komma oder Zeilenumbruch; mehrere Tokens je Rolle erlauben den Wechsel ohne
Ausfall. Ein Token unter 24 Zeichen oder mit unbekannter Rolle zählt nicht, ein Token für zwei Rollen zählt für keine.
Vorgelegt wird es als `Authorization: Bearer <token>` (Alertmanager: `http_config.authorization`) oder
`X-Agent-Token: <token>`; verglichen in konstanter Zeit, das Token steht nie im Protokoll. Ohne passendes Token: 401.

`streng: true` (Umgebung `FYOS_AGENT_STRENG=1`) verlangt Tokens auch dann, wenn keines brauchbar ist — dann antwortet
jeder Weg 401. So öffnet ein fehlendes Geheimnis nichts.

Den gemeinsamen Hub-Schlüssel (`FYOS_HUB_SCHLUESSEL_PFADE`) nicht auf `/hub/agent` legen: er verlangt einen Schlüssel
für alle und entfernt `Authorization`, die Quellen-Tokens kämen nie an.

Konfiguration (alles optional):
    agent        Agenten-ID für Ereignisse ohne eigene (Vorgabe `agent`)
    tokens       wie FYOS_AGENT_TOKENS (nur für Tests; Geheimnisse gehören in die Umgebung)
    streng       wie FYOS_AGENT_STRENG
    redis_url    sonst `REDIS_URL`
    sse_dauer_s  Höchstdauer einer SSE-Verbindung (Vorgabe 600 s)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from mcp_hub.plugin import HubPlugin, ToolDescriptor
from mcp_hub.plugins import _agentenalarm as alarm
from mcp_hub.plugins import _agenteneingang as eingang
from mcp_hub.plugins import _agentenstrom as strom
from mcp_hub.plugins import _arbeitsbereiche as bereiche

logger = logging.getLogger(__name__)

REDIS_URL_VORGABE = "redis://localhost:6379"
TOKEN_MINDESTLAENGE = 24
ROLLE_RUNNER = "runner"
ROLLEN = (*eingang.QUELLEN, ROLLE_RUNNER)
#: Wer den Ausgang mitlesen darf (mit Tokens); der Strom enthält Werkzeugargumente und Ergebnisse.
ROLLEN_LESEN = ("max", "web")
#: SSE: so lange blockiert ein Abruf, danach geht ein Kommentar `: da` als Lebenszeichen.
SSE_WARTE_S = 15
#: SSE: eine Verbindung endet nach so vielen Sekunden; der Client verbindet neu (`retry`) und setzt mit
#: `Last-Event-ID` fort. So hängt kein Faden ewig an einer toten Verbindung, und Proxys schneiden nicht mitten hinein.
SSE_DAUER_S = 600
_WAHR = ("1", "an", "ja", "true", "yes", "on")
_AGENT = re.compile(r"^[a-z0-9_-]{1,32}$")


def _jetzt_ms() -> int:
    return int(time.time() * 1000)


def _fehler(status: int, nachricht: str, kind: str) -> JSONResponse:
    kopf = {"WWW-Authenticate": 'Bearer realm="fyos-agent"'} if status == 401 else None
    return JSONResponse(status_code=status, content={"ok": False, "error": nachricht, "kind": kind}, headers=kopf)


@dataclass(frozen=True)
class Tokens:
    """Quellen-Tokens: Token → Rolle. `an` heißt: jeder Weg verlangt ein passendes Token."""

    rollen: tuple[tuple[str, str], ...] = ()
    streng: bool = False
    verworfen: int = 0

    @classmethod
    def aus(cls, roh: Any, streng: bool = False) -> "Tokens":
        if isinstance(roh, (list, tuple)):
            teile = [str(t) for t in roh]
        else:
            teile = str(roh or "").replace("\n", ",").split(",")
        paare: list[tuple[str, str]] = []
        verworfen = 0
        for teil in (t.strip() for t in teile):
            if not teil:
                continue
            rolle, _, token = teil.partition("=")
            rolle, token = rolle.strip(), token.strip()
            if rolle not in ROLLEN or len(token) < TOKEN_MINDESTLAENGE:
                verworfen += 1
                continue
            paare.append((token, rolle))
        zaehl: dict[str, set[str]] = {}
        for token, rolle in paare:
            zaehl.setdefault(token, set()).add(rolle)
        doppelt = {t for t, r in zaehl.items() if len(r) > 1}
        verworfen += sum(1 for t, _ in paare if t in doppelt)
        rollen = tuple(dict.fromkeys((t, r) for t, r in paare if t not in doppelt))
        return cls(rollen=rollen, streng=streng, verworfen=verworfen)

    @property
    def an(self) -> bool:
        return bool(self.rollen) or self.streng

    def rolle(self, vorgelegt: str) -> str | None:
        """Rolle zum Token; konstante Zeit je Eintrag, kein Abbruch beim ersten Treffer."""
        treffer: str | None = None
        kandidat = vorgelegt.encode("utf-8", "replace")
        for token, rolle in self.rollen:
            if hmac.compare_digest(kandidat, token.encode("utf-8")):
                treffer = rolle
        return treffer

    def zaehlen(self) -> dict[str, int]:
        z: dict[str, int] = {}
        for _, rolle in self.rollen:
            z[rolle] = z.get(rolle, 0) + 1
        return z


def _vorgelegt(request: Request) -> str:
    eigen = (request.headers.get("x-agent-token") or "").strip()
    if eigen:
        return eigen
    schema, _, rest = (request.headers.get("authorization") or "").partition(" ")
    return rest.strip() if schema.lower() == "bearer" else ""


class AgentPlugin(HubPlugin):
    name = "agent"
    description = (
        "Eingang und Ausgang eines Agenten-Runners: Quellen werfen Ereignisse ein, der Runner liest sie per Long-Poll "
        "und meldet seine Sitzung in den Strom fyos:agent. Nur HTTP-Wege unter /hub/agent, keine Werkzeuge."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None, redis: Any = None, redis_lang: Any = None):
        super().__init__()
        cfg = dict(config or {})
        self.agent = str(cfg.get("agent") or os.getenv("FYOS_AGENT_ID") or eingang.VORGABE_AGENT)
        if not _AGENT.match(self.agent):
            raise ValueError("agent: ^[a-z0-9_-]{1,32}$")
        streng = cfg.get("streng")
        if streng is None:
            streng = (os.getenv("FYOS_AGENT_STRENG") or "").strip().lower() in _WAHR
        self.tokens = Tokens.aus(cfg.get("tokens") or os.getenv("FYOS_AGENT_TOKENS") or "", bool(streng))
        self.redis_url = str(cfg.get("redis_url") or os.getenv("REDIS_URL") or REDIS_URL_VORGABE)
        self.sse_dauer_s = float(cfg.get("sse_dauer_s", SSE_DAUER_S))
        #: Tests setzen Attrappen
        self._redis = redis
        self._redis_lang = redis_lang if redis_lang is not None else redis
        self._zaehler = {"eingang": 0, "gelesen": 0, "gemeldet": 0, "alarme": 0, "abgewiesen": 0,
                         "mitgelesen": 0, "sse_offen": 0}

    # ── Lebenslauf ──────────────────────────────────────────────────────────────────────────

    def register(self) -> None:
        if self.tokens.verworfen:
            logger.warning(
                "agent: %d Einträge in FYOS_AGENT_TOKENS zählen nicht (Rolle unbekannt, Token unter %d Zeichen "
                "oder für zwei Rollen)",
                self.tokens.verworfen,
                TOKEN_MINDESTLAENGE,
            )
        if self.tokens.streng and not self.tokens.rollen:
            logger.warning("agent: streng ohne brauchbares Token — alle Wege unter /hub/agent antworten 401")
        logger.info(
            "agent: Quellen-Tokens %s, Agent-Vorgabe %s",
            "an " + json.dumps(self.tokens.zaehlen(), sort_keys=True) if self.tokens.an else "aus (innen offen)",
            self.agent,
        )

    def describe_tools(self) -> list[ToolDescriptor]:
        return []

    def call(self, method: str, args: dict[str, Any]) -> Any:
        raise ValueError(f"agent hat keine Werkzeuge: {method}")

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "healthy",
            "tokens": "an" if self.tokens.an else "aus",
            "rollen": self.tokens.zaehlen(),
            "agent": self.agent,
        }

    def metrics(self) -> dict[str, Any]:
        return {**self._zaehler, "tokens_an": self.tokens.an}

    # ── Redis ───────────────────────────────────────────────────────────────────────────────

    def redis(self) -> Any:
        if self._redis is None:
            import redis as _redis_mod  # im Hub-Image vorhanden

            self._redis = _redis_mod.Redis.from_url(
                self.redis_url, socket_timeout=3, socket_connect_timeout=3, decode_responses=True
            )
        return self._redis

    def redis_lang(self) -> Any:
        """Eigene Verbindung für den Long-Poll: ein blockierendes XREAD hält bis zu `WARTE_MAX_S` offen."""
        if self._redis_lang is None:
            import redis as _redis_mod

            self._redis_lang = _redis_mod.Redis.from_url(
                self.redis_url,
                socket_timeout=eingang.WARTE_MAX_S + 5,
                socket_connect_timeout=3,
                decode_responses=True,
            )
        return self._redis_lang

    # ── Wege ────────────────────────────────────────────────────────────────────────────────

    def routen(self) -> list[Any]:
        return [
            Route("/hub/agent/eingang", self._weg_eingang, methods=["GET", "POST"]),
            Route("/hub/agent/melden", self._weg_melden, methods=["POST"]),
            Route("/hub/agent/alarm", self._weg_alarm, methods=["POST"]),
            Route("/hub/agent/strom", self._weg_strom, methods=["GET"]),
            Route("/hub/agent/arbeitsbereiche", self._weg_bereiche, methods=["GET", "POST"]),
        ]

    def _pruefen(self, request: Request, erlaubt: tuple[str, ...]) -> tuple[str | None, JSONResponse | None]:
        """(Rolle oder None ohne Tokens, Fehlerantwort oder None)."""
        if not self.tokens.an:
            return None, None
        rolle = self.tokens.rolle(_vorgelegt(request))
        if rolle is None or rolle not in erlaubt:
            self._zaehler["abgewiesen"] += 1
            logger.info("agent: abgewiesen: %s %s", request.method, request.url.path)
            return None, _fehler(401, "unauthorized", "unauthorized")
        return rolle, None

    @staticmethod
    async def _json(request: Request) -> tuple[Any, JSONResponse | None]:
        typ = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if typ != "application/json":
            return None, _fehler(415, "Content-Type: application/json verlangt", "content_type")
        roh = await request.body()
        if len(roh) > strom.BODY_MAX_BYTES:
            return None, _fehler(413, "Anfrage zu groß", "zu_gross")
        try:
            return json.loads(roh or b"null"), None
        except ValueError:
            return None, _fehler(400, "ungültiges JSON", "bad_request")

    async def _weg_eingang(self, request: Request) -> JSONResponse:
        if request.method == "GET":
            return await self._eingang_lesen(request)
        return await self._eingang_einwerfen(request)

    async def _eingang_einwerfen(self, request: Request) -> JSONResponse:
        rolle, falsch = self._pruefen(request, eingang.QUELLEN)
        if falsch is not None:
            return falsch
        daten, falsch = await self._json(request)
        if falsch is not None:
            return falsch
        if rolle is not None and isinstance(daten, dict):
            daten = {**daten, "quelle": rolle}  # die Quelle folgt dem Token, nicht dem Rumpf
        try:
            sid = await asyncio.to_thread(eingang.einwerfen, self.redis(), daten, _jetzt_ms(), self.agent)
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        except Exception as exc:  # noqa: BLE001 — Redis weg: ehrlich 503, die Quelle versucht es erneut
            logger.warning("agent: eingang: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        self._zaehler["eingang"] += 1
        return JSONResponse({"ok": True, "id": sid})

    async def _eingang_lesen(self, request: Request) -> JSONResponse:
        _, falsch = self._pruefen(request, (ROLLE_RUNNER,))
        if falsch is not None:
            return falsch
        q = request.query_params
        try:
            nach = eingang.strom_id(q.get("nach") or "$")
            warte = float(q.get("warte") or 0)
            anzahl = int(q.get("anzahl") or 20)
            agent = str(q.get("agent") or self.agent)
            if not _AGENT.match(agent):
                raise ValueError("agent: ^[a-z0-9_-]{1,32}$")
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        try:
            ergebnis = await asyncio.to_thread(eingang.lesen, self.redis_lang(), nach, warte, anzahl, agent)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent: eingang lesen: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        self._zaehler["gelesen"] += len(ergebnis["eintraege"])
        return JSONResponse({"ok": True, **ergebnis})

    async def _weg_melden(self, request: Request) -> JSONResponse:
        _, falsch = self._pruefen(request, (ROLLE_RUNNER,))
        if falsch is not None:
            return falsch
        daten, falsch = await self._json(request)
        if falsch is not None:
            return falsch
        try:
            angenommen = await asyncio.to_thread(self._melden, daten)
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        except Exception as exc:  # noqa: BLE001 — der Runner hebt auf und versucht es erneut
            logger.warning("agent: melden: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        self._zaehler["gemeldet"] += angenommen
        return JSONResponse({"ok": True, "angenommen": angenommen})

    def _melden(self, roh: Any) -> int:
        if not isinstance(roh, dict):
            raise ValueError("Anfrage muss ein Objekt sein")
        ereignisse = roh.get("ereignisse")
        if not isinstance(ereignisse, list) or not ereignisse:
            raise ValueError("ereignisse: nichtleere Liste erwartet")
        if len(ereignisse) > strom.EREIGNISSE_MAX:
            raise ValueError(f"ereignisse: höchstens {strom.EREIGNISSE_MAX} Einträge je Meldung")
        return strom.senden_viele(self.redis(), ereignisse, _jetzt_ms())

    async def _weg_alarm(self, request: Request) -> JSONResponse:
        _, falsch = self._pruefen(request, ("alarm",))
        if falsch is not None:
            return falsch
        daten, falsch = await self._json(request)
        if falsch is not None:
            return falsch
        try:
            ergebnis = await asyncio.to_thread(alarm.aus_alertmanager, self.redis(), daten, _jetzt_ms(), self.agent)
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        except Exception as exc:  # noqa: BLE001 — 503, damit Alertmanager es erneut versucht
            logger.warning("agent: alarm: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        if ergebnis["eingeworfen"]:
            logger.info(
                "agent: alarm: %d eingeworfen, %d übersprungen", len(ergebnis["eingeworfen"]), ergebnis["uebersprungen"]
            )
        self._zaehler["alarme"] += len(ergebnis["eingeworfen"])
        return JSONResponse({"ok": True, **ergebnis})

    async def _weg_bereiche(self, request: Request) -> JSONResponse:
        """Arbeitsbereiche: der Runner meldet Namen und Titel (POST), Chatfenster lesen die Auswahl (GET)."""
        schreiben = request.method == "POST"
        _, falsch = self._pruefen(request, (ROLLE_RUNNER,) if schreiben else ROLLEN_LESEN)
        if falsch is not None:
            return falsch
        if not schreiben:
            try:
                agent = bereiche.agent_pruefen(request.query_params.get("agent"), self.agent)
                liste = await asyncio.to_thread(bereiche.lesen, self.redis(), agent, self.agent)
            except ValueError as exc:
                return _fehler(400, str(exc), "bad_request")
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent: arbeitsbereiche lesen: %s", exc)
                return _fehler(503, "Redis nicht erreichbar", "redis")
            return JSONResponse({"ok": True, "bereiche": liste})
        daten, falsch = await self._json(request)
        if falsch is not None:
            return falsch
        try:
            if not isinstance(daten, dict):
                raise ValueError("Anfrage muss ein Objekt sein")
            liste = await asyncio.to_thread(
                bereiche.setzen, self.redis(), daten.get("agent"), daten.get("bereiche"), self.agent
            )
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent: arbeitsbereiche melden: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        return JSONResponse({"ok": True, "bereiche": liste})

    async def _weg_strom(self, request: Request) -> Response:
        _, falsch = self._pruefen(request, ROLLEN_LESEN)
        if falsch is not None:
            return falsch
        q = request.query_params
        sse = "text/event-stream" in (request.headers.get("accept") or "")
        try:
            nach = strom.lese_id(request.headers.get("last-event-id") or q.get("nach") or "$")
            warte = float(q.get("warte") or 0)
            anzahl = int(q.get("anzahl") or 200)
            agent = str(q.get("agent") or self.agent)
            if not _AGENT.match(agent):
                raise ValueError("agent: ^[a-z0-9_-]{1,32}$")
            sitzung = q.get("sitzung") or None
            if sitzung is not None and not re.match(r"^[A-Za-z0-9_.:-]{1,64}$", sitzung):
                raise ValueError("sitzung: höchstens 64 Zeichen aus A-Z a-z 0-9 _ . : -")
        except ValueError as exc:
            return _fehler(400, str(exc), "bad_request")
        if sse:
            return StreamingResponse(
                self._sse(request, nach, agent, sitzung),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            ergebnis = await asyncio.to_thread(strom.lesen, self.redis_lang(), nach, warte, anzahl, agent, sitzung)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent: strom lesen: %s", exc)
            return _fehler(503, "Redis nicht erreichbar", "redis")
        self._zaehler["mitgelesen"] += len(ergebnis["eintraege"])
        return JSONResponse({"ok": True, **ergebnis})

    async def _sse(self, request: Request, nach: str, agent: str, sitzung: str | None):
        """SSE-Projektion des Ausgangs: blockierende Abrufe in Folge, bis die Gegenseite geht."""
        self._zaehler["sse_offen"] += 1
        try:
            yield "retry: 3000\n\n"
            ende = time.monotonic() + self.sse_dauer_s
            erste = True
            while erste or (time.monotonic() < ende and not await request.is_disconnected()):
                erste = False
                try:
                    ergebnis = await asyncio.to_thread(
                        strom.lesen, self.redis_lang(), nach, SSE_WARTE_S, strom.LESEN_ANZAHL_MAX, agent, sitzung
                    )
                except Exception as exc:  # noqa: BLE001 — Redis weg: melden, kurz warten, weiter
                    logger.warning("agent: strom sse: %s", exc)
                    yield 'event: fehler\ndata: {"kind": "redis"}\n\n'
                    await asyncio.sleep(3)
                    continue
                nach = ergebnis["letzte"]
                for e in ergebnis["eintraege"]:
                    yield f"id: {e['sid']}\nevent: ereignis\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                self._zaehler["mitgelesen"] += len(ergebnis["eintraege"])
                if not ergebnis["eintraege"]:
                    yield ": da\n\n"
                    await asyncio.sleep(0)
        finally:
            self._zaehler["sse_offen"] -= 1

