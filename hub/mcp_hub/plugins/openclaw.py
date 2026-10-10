"""openclaw — FYOS und OpenClaw greifen ineinander, statt doppelt zu führen.

OpenClaw bringt Gegenstücke zu FYOS-Bausteinen mit: das Workboard (zu den Vorgängen), Skills und Plugins, eigene
Nutzungs- und Aktivitätsdaten, Zustandssonden und Diagnose, Cron. Dieses Plugin koppelt sie über die Brücke
``fyos-bruecke`` (OpenClaw-Plugin in fyos-agent). Vertrag: ``docs/KOPPLUNG-OPENCLAW.md``.

Zwei Richtungen:

* **OpenClaw → Hub (Ereignisse):** Die Brücke hört die Hooks des Gateways und schickt sie gebündelt an
  ``POST /hub/openclaw/ereignisse``: Werkzeugaufrufe, Modellaufrufe, Sitzungen, Cron-Läufe, Skill-Änderungen, Hinweise.
  Nur Namen, Dauer und Ergebnis, nie Argumente, Ergebnisse oder Texte; Sitzungsschlüssel kommen gehasht. Werkzeugaufrufe
  laufen durch dieselben Haken wie Hub-Aufrufe (Audit, Ereignisbus, Sammelstrom ``fyos:live``), alles landet zusätzlich
  im Strom ``fyos:openclaw:aktivitaet``. Ist ``FYOS_AGENT_TOKEN`` gesetzt, muss jede Lieferung mit diesem Token
  signiert sein (HMAC-SHA256 über ``<zeit>.<körper>``, Köpfe ``X-FYOS-Zeit`` und ``X-FYOS-Signatur``); das Token selbst
  verlässt den Agenten nie.
* **Hub → OpenClaw (Abfragen):** Der Hub ruft die Brücken-Route ``POST <gateway>/plugins/fyos-bruecke/v1/rpc`` mit
  dem Gateway-Token; die Brücke reicht nur eine feste Liste von Gateway-Methoden weiter (Workboard, Skills, Cron,
  Nutzung, Zustand). Dazu die anmeldefreien Sonden ``/healthz`` und ``/readyz``.

Vorgänge und Workboard (``_vorgaenge``): mit Vorgangs-Dienst (``FYOS_VORGAENGE_URL``) spiegelt der Takt dessen offene
Vorgänge als Karten auf das Board ``fyos`` und trägt Änderungen aus OpenClaw zurück; ohne Dienst ist das Workboard die
Ablage, und ``/hub/vorgaenge/tickets…`` bietet den Vorgangs-Vertrag auf Basis der Karten an (so arbeitet etwa die
Freigabe im Chat mit dem Workboard).

Beiträge zu den gemeinsamen Ansichten: ``zeitplan()`` (Cron des Agenten neben den Takten des Hubs, ``mcp.zeitplan``),
``skills_beitrag()`` (Skills des Agenten in ``skills.suchen``), ``metrics()`` (``/metrics``), ``health()``.

Konfiguration (alles optional, sonst Umgebung):
    gateway_url       FYOS_AGENT_URL, z. B. http://agent:18789 (leer: Plugin ist aus)
    token             FYOS_AGENT_TOKEN, das Gateway-Token (Abfragen und Prüfung der Signatur)
    vorgaenge_url     FYOS_VORGAENGE_URL (leer: Workboard ist die Ablage)
    vorgang_link      FYOS_VORGANG_LINK, Verweis je Vorgang mit {id}, z. B. https://fyos.example/vorgaenge/{id}
    board             Board der Vorgänge (Vorgabe: fyos im Spiegel, default als Ablage)
    abgleich_s        Takt des Abgleichs (Vorgabe 60, 0 = nur auf Abruf)
    takt_grenzen      Grenzen je Takt (cron, skills, abgleich, karten): ``{abgleich: {max_pro_tag: 500, fenster: "06:00-23:00"}}``;
                      außerhalb des Fensters oder über dem Tageslimit läuft der Takt nicht (``mcp_hub.takt``). Die Sonde
                      und der Abgleich auf Abruf (``openclaw.abgleichen``) laufen immer.
    werkzeug_auslassen  Namensanfänge, die nicht gemeldet werden (Hub-Werkzeuge über MCP protokolliert der Hub selbst)
    fyos_skill_pfade  Skill-Verzeichnisse von fyos-agent im Agenten (Quelle „fyos-agent“ statt „openclaw“)
    akteur            Name im Vorgangs-Dienst für Änderungen aus OpenClaw (Vorgabe openclaw)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import kv
from .. import takt as _takt
from ..audit_log import AuditEvent, schwaerzen
from ..plugin import HubPlugin, ToolDescriptor
from . import _vorgaenge as V

logger = logging.getLogger(__name__)

BRUECKE_PFAD = "/plugins/fyos-bruecke/v1"
AUDIT_PLUGIN = "openclaw-agent"
STROM = "fyos:openclaw:aktivitaet"
STROM_MAX = 5000
TAG_SCHLUESSEL = "fyos:openclaw:tag:"
TAG_TTL_S = 40 * 86400
KARTEN_STAND = "fyos:openclaw:karten"
KOERPER_MAX = 512 * 1024
EREIGNISSE_MAX = 500
ZEIT_TOLERANZ_S = 300
SCHRITTE_MAX = 60
STILL_S = 300
ARTEN = ("werkzeug", "modell", "lauf", "sitzung", "cron", "skill", "skill_vorschlag", "hinweis")
TAKTE = ("cron", "skills", "abgleich", "karten")  # Takte mit Grenzen (`takt_grenzen`); die Sonde läuft immer
VORGABE_AUSLASSEN = ("hub__", "mcp__hub__", "mcp-hub__")
VORGABE_SKILL_PFADE = ("/opt/fyos/skills",)
_TAGS_LESEN = ["openclaw", "agent", "read"]


class BrueckeFehler(RuntimeError):
    """Die Brücke oder das Gateway antworteten nicht wie vereinbart."""


def _wort(wert: Any, grenze: int = 60) -> str:
    """Kurzer Name ohne Steuerzeichen (Werkzeug, Modell, Agent)."""
    t = "".join(ch for ch in str(wert or "") if ch.isprintable()).strip()
    return t[:grenze]


def _zahl(wert: Any) -> float:
    try:
        z = float(wert)
    except (TypeError, ValueError):
        return 0.0
    return z if z == z and abs(z) != float("inf") else 0.0


def _kurz(text: Any, grenze: int = 200) -> str:
    t = " ".join(str(text or "").split())
    return schwaerzen(t)[:grenze] if t else ""


def signatur(token: str, zeit: str, koerper: bytes) -> str:
    """Signatur einer Lieferung: ``sha256=<hex>`` von HMAC-SHA256(token, ``<zeit>.<körper>``)."""
    mac = hmac.new(token.encode(), zeit.encode() + b"." + koerper, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def _takt_text(plan: Any) -> str:
    if not isinstance(plan, dict):
        return str(plan or "")
    art = plan.get("kind")
    if art == "cron":
        zone = f" ({plan['tz']})" if plan.get("tz") else ""
        return f"{plan.get('expr') or plan.get('expression') or ''}{zone}".strip()
    if art == "every":
        ms = _zahl(plan.get("everyMs") or plan.get("intervalMs"))
        if ms >= 3_600_000:
            return f"alle {ms / 3_600_000:g} h"
        if ms >= 60_000:
            return f"alle {ms / 60_000:g} min"
        return f"alle {ms / 1000:g} s" if ms else "regelmäßig"
    if art == "at":
        return f"einmal {plan.get('at') or ''}".strip()
    return str(art or "")


class OpenClawPlugin(HubPlugin):
    name = "openclaw"
    description = (
        "Kopplung an OpenClaw (Brücke fyos-bruecke): Zustand, Nutzung, Aktivität, Skills und Plugins, Workboard und "
        "Cron des Agenten zusammen mit den FYOS-Gegenstücken."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        cfg = config or {}
        self.gateway_url = str(cfg.get("gateway_url") or os.getenv("FYOS_AGENT_URL") or "").strip().rstrip("/")
        self._token = str(cfg.get("token") or os.getenv("FYOS_AGENT_TOKEN") or "").strip()
        self.vorgaenge_url = str(cfg.get("vorgaenge_url") or os.getenv("FYOS_VORGAENGE_URL") or "").strip().rstrip("/")
        if self.vorgaenge_url.endswith("/hub/vorgaenge"):
            # Die eigene Ablage als Vorgangs-Dienst hieße: das Workboard auf sich selbst spiegeln.
            logger.warning("openclaw: FYOS_VORGAENGE_URL zeigt auf die Ablage des Hubs, das Workboard bleibt die Ablage")
            self.vorgaenge_url = ""
        self.vorgang_link = str(cfg.get("vorgang_link") or os.getenv("FYOS_VORGANG_LINK") or "").strip()
        self.board = str(cfg.get("board") or ("fyos" if self.vorgaenge_url else "default"))
        self.abgleich_s = max(0.0, _zahl(cfg.get("abgleich_s", 60)))
        self.auslassen = tuple(str(x) for x in (cfg.get("werkzeug_auslassen") or VORGABE_AUSLASSEN))
        self.fyos_skill_pfade = tuple(str(x).rstrip("/") + "/" for x in (cfg.get("fyos_skill_pfade") or VORGABE_SKILL_PFADE))
        self.akteur = str(cfg.get("akteur") or "openclaw")
        self.audit = bool(cfg.get("audit", True))
        # Austauschbare Wege (Tests): rpc(methode, params) -> payload, vorgaenge(methode, pfad, koerper) -> dict,
        # http_get(url) -> (status, dict)
        self._rpc_aufruf: Callable[[str, dict[str, Any]], Any] | None = cfg.get("rpc_aufruf")
        self._vd_aufruf: Callable[[str, str, Any], Any] | None = cfg.get("vorgaenge_aufruf")
        self._http_get: Callable[[str], tuple[int, dict[str, Any]]] | None = cfg.get("http_get")
        self._kv_fabrik: Callable[[], Any] | None = cfg.get("kv_fabrik")
        self._kv: Any = None
        self._waechter = _takt.Waechter(self.name, cfg.get("takt_grenzen"), speicher=self._speicher, takte=TAKTE)
        self._registry: Any = None
        self._sperre = threading.RLock()
        self._abgleich_sperre = threading.Lock()
        self._halt = threading.Event()
        self._faden: threading.Thread | None = None
        self._ablage: dict[str, tuple[float, Any]] = {}
        self._bruecke: dict[str, Any] = {}
        self._zaehler: dict[str, Any] = {"ereignisse": {}, "werkzeug": {}, "modell": {}, "lauf": {}, "sitzung": {},
                                         "cron": {}, "ausgelassen": 0, "abgewiesen": 0}
        self._rpc_stand = {"ok": 0, "fehler": 0, "letzter_fehler": ""}
        self._laeufe: dict[str, dict[str, Any]] = {}
        self._karten_stand: dict[str, dict[str, Any]] | None = None
        self._board_bereit = False
        self._letzte_schritte: list[dict[str, Any]] = []
        self._gestartet = time.time()

    # ── Lebenslauf ─────────────────────────────────────────────────────────────────────────────

    @property
    def modus(self) -> str:
        if not self.gateway_url:
            return "aus"
        return "spiegel" if self.vorgaenge_url else "ablage"

    def register(self) -> None:
        if not self.gateway_url:
            logger.info("openclaw: FYOS_AGENT_URL nicht gesetzt — Kopplung aus")
        elif not self._token:
            logger.warning("openclaw: FYOS_AGENT_TOKEN fehlt — Ereignisse ohne Signatur, keine Abfragen am Gateway")

    def registry_anbinden(self, registry: Any) -> None:
        """Vom Server gerufen: Register für die Audit-Haken; startet den Takt, wenn ein Gateway eingetragen ist."""
        self._registry = registry
        if self.gateway_url and self._faden is None:
            self._faden = threading.Thread(target=self._takt, name="openclaw-takt", daemon=True)
            self._faden.start()

    def shutdown(self) -> None:
        self._halt.set()

    def _speicher(self) -> Any:
        if self._kv is None:
            self._kv = self._kv_fabrik() if self._kv_fabrik else kv.klient()
        return self._kv

    # ── Wege zum Gateway und zum Vorgangs-Dienst ──────────────────────────────────────────────

    def _get(self, url: str, zeit_s: float = 4.0) -> tuple[int, dict[str, Any]]:
        if self._http_get is not None:
            return self._http_get(url)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=zeit_s) as r:  # noqa: S310 — Adresse aus der Konfiguration
                status, roh = r.status, r.read(65536)
        except urllib.error.HTTPError as e:
            status, roh = e.code, e.read(65536) if e.fp else b""
        try:
            daten = json.loads(roh.decode() or "{}")
        except ValueError:
            daten = {}
        return status, daten if isinstance(daten, dict) else {}

    def rpc(self, methode: str, params: dict[str, Any] | None = None, zeit_s: float = 10.0) -> Any:
        """Eine Gateway-Methode über die Brücke (nur die Methoden ihrer festen Liste)."""
        try:
            if self._rpc_aufruf is not None:
                antwort = self._rpc_aufruf(methode, dict(params or {}))
            else:
                if not self.gateway_url:
                    raise BrueckeFehler("FYOS_AGENT_URL nicht gesetzt")
                if not self._token:
                    raise BrueckeFehler("FYOS_AGENT_TOKEN fehlt: Abfragen am Gateway brauchen das Gateway-Token")
                koerper = json.dumps({"method": methode, "params": params or {}}).encode()
                req = urllib.request.Request(
                    self.gateway_url + BRUECKE_PFAD + "/rpc", data=koerper, method="POST",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=zeit_s) as r:  # noqa: S310
                        roh = r.read(8 * 1024 * 1024)
                except urllib.error.HTTPError as e:
                    text = (e.read(600) if e.fp else b"").decode(errors="replace")
                    raise BrueckeFehler(f"Brücke HTTP {e.code} auf {methode}: {_kurz(text, 300)}") from e
                except (urllib.error.URLError, OSError) as e:
                    raise BrueckeFehler(f"Brücke nicht erreichbar ({type(e).__name__})") from e
                daten = json.loads(roh.decode() or "{}")
                if not isinstance(daten, dict) or not daten.get("ok"):
                    fehler = (daten or {}).get("error") if isinstance(daten, dict) else None
                    text = fehler.get("message") if isinstance(fehler, dict) else fehler
                    raise BrueckeFehler(f"{methode}: {_kurz(text or 'ohne Antwort', 300)}")
                antwort = daten.get("payload")
        except Exception as exc:
            with self._sperre:
                self._rpc_stand["fehler"] += 1
                self._rpc_stand["letzter_fehler"] = _kurz(f"{methode}: {exc}", 300)
            raise
        with self._sperre:
            self._rpc_stand["ok"] += 1
        return antwort

    def _vd(self, methode: str, pfad: str, koerper: Any = None, zeit_s: float = 8.0) -> Any:
        """Ein Aufruf beim Vorgangs-Dienst (Vertrag wie fyos-agent/plugins/fyos-freigabe-chat/board.mjs)."""
        if self._vd_aufruf is not None:
            return self._vd_aufruf(methode, pfad, koerper)
        if not self.vorgaenge_url:
            raise BrueckeFehler("FYOS_VORGAENGE_URL nicht gesetzt")
        daten = json.dumps(koerper).encode() if koerper is not None else None
        req = urllib.request.Request(self.vorgaenge_url + pfad, data=daten, method=methode,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=zeit_s) as r:  # noqa: S310
                roh = r.read(4 * 1024 * 1024)
        except urllib.error.HTTPError as e:
            text = (e.read(400) if e.fp else b"").decode(errors="replace")
            fehler = BrueckeFehler(f"Vorgangs-Dienst HTTP {e.code} auf {methode} {pfad}: {_kurz(text, 200)}")
            fehler.status = e.code  # type: ignore[attr-defined]
            raise fehler from e
        return json.loads(roh.decode() or "{}")

    def _zwischen(self, name: str, ttl_s: float, holen: Callable[[], Any], frisch: bool = False) -> Any:
        """Zwischenablage je Name; scheitert ``holen``, bleibt der alte Wert (und der Fehler wird gemerkt)."""
        jetzt = time.monotonic()
        with self._sperre:
            alt = self._ablage.get(name)
        if alt is not None and not frisch and jetzt - alt[0] < ttl_s:
            return alt[1]
        try:
            wert = holen()
        except Exception as exc:  # noqa: BLE001
            self._lauf(name, "fehler", str(exc))
            if alt is not None:
                return alt[1]
            raise
        with self._sperre:
            self._ablage[name] = (time.monotonic(), wert)
        self._lauf(name, "ok")
        return wert

    def _gemerkt(self, name: str) -> Any:
        with self._sperre:
            alt = self._ablage.get(name)
        return alt[1] if alt is not None else None

    def _lauf(self, name: str, status: str, fehler: str = "") -> None:
        with self._sperre:
            self._laeufe[name] = {"letzter": time.time(), "status": status, "fehler": _kurz(fehler, 300) or None}

    # ── Sonden und Abfragen ───────────────────────────────────────────────────────────────────

    def sonde(self, frisch: bool = False) -> dict[str, Any]:
        """``/healthz`` und ``/readyz`` des Gateways (anmeldefrei), 15 s zwischengespeichert."""
        if not self.gateway_url:
            return {"gesetzt": False, "lebt": False, "bereit": False}

        def holen() -> dict[str, Any]:
            try:
                s1, lebt = self._get(self.gateway_url + "/healthz")
            except Exception as exc:  # noqa: BLE001
                return {"gesetzt": True, "lebt": False, "bereit": False, "fehler": f"{type(exc).__name__}: {exc}"[:200]}
            try:
                s2, bereit = self._get(self.gateway_url + "/readyz")
            except Exception as exc:  # noqa: BLE001
                s2, bereit = 0, {"fehler": type(exc).__name__}
            return {
                "gesetzt": True,
                "lebt": s1 == 200,
                "bereit": s2 == 200,
                "version": lebt.get("version") or bereit.get("version"),
                "laufzeit_s": round(_zahl(lebt.get("uptimeMs")) / 1000) or None,
                "fehlt": [str(x) for x in (bereit.get("failing") or [])][:10],
                "stand": time.time(),
            }

        return self._zwischen("sonde", 15.0, holen, frisch)

    def karten(self, frisch: bool = False, ttl_s: float = 5.0) -> list[dict[str, Any]]:
        def holen() -> list[dict[str, Any]]:
            antwort = self.rpc("workboard.cards.list", {"boardId": self.board}) or {}
            liste = antwort.get("cards") if isinstance(antwort, dict) else antwort
            return [k for k in (liste or []) if isinstance(k, dict)]

        return self._zwischen("karten", ttl_s, holen, frisch)

    def cron_auftraege(self, frisch: bool = False) -> list[dict[str, Any]]:
        def holen() -> list[dict[str, Any]]:
            antwort = self.rpc("cron.list", {"includeDisabled": True, "compact": True, "limit": 200}) or {}
            return [j for j in (antwort.get("jobs") or []) if isinstance(j, dict)]

        return self._zwischen("cron", 60.0, holen, frisch)

    def agent_skills(self, frisch: bool = False) -> list[dict[str, Any]]:
        def holen() -> list[dict[str, Any]]:
            antwort = self.rpc("skills.status", {}) or {}
            return [s for s in (antwort.get("skills") or []) if isinstance(s, dict)]

        return self._zwischen("skills", 300.0, holen, frisch)

    def _skill_text(self, name: str) -> str:
        antwort = self.rpc("fyos.skill.lesen", {"name": name}) or {}
        return str(antwort.get("text") or "")

    # ── Ereignisse der Brücke ─────────────────────────────────────────────────────────────────

    def annehmen(self, daten: Any) -> int:
        """Eine Lieferung der Brücke verarbeiten; gibt die Zahl der angenommenen Ereignisse zurück."""
        if not isinstance(daten, dict):
            raise ValueError("Lieferung muss ein Objekt sein")
        b = daten.get("bruecke") if isinstance(daten.get("bruecke"), dict) else {}
        plugins = []
        for p in (b.get("plugins") or [])[:200]:
            if isinstance(p, dict) and p.get("id"):
                plugins.append({"id": _wort(p["id"], 80), "an": bool(p.get("an", True))})
        with self._sperre:
            self._bruecke = {
                "version": _wort(b.get("version"), 40),
                "instanz": _wort(b.get("instanz"), 80),
                "gestartet": _zahl(b.get("gestartet")) / 1000 or None,
                "verworfen": int(_zahl(b.get("verworfen"))),
                "warteschlange": int(_zahl(b.get("warteschlange"))),
                "plugins": plugins or self._bruecke.get("plugins") or [],
                "zuletzt": time.time(),
            }
        n = 0
        for roh in (daten.get("ereignisse") or [])[:EREIGNISSE_MAX]:
            try:
                n += bool(self._eines(roh))
            except Exception as exc:  # noqa: BLE001 — ein kaputtes Ereignis kostet nur sich selbst
                logger.debug("openclaw: Ereignis verworfen: %s", exc)
        return n

    def _zaehle(self, gruppe: str, schluessel: str, n: int = 1) -> None:
        with self._sperre:
            g = self._zaehler[gruppe]
            g[schluessel] = g.get(schluessel, 0) + n

    def _tag(self, zeit_s: float, felder: dict[str, int]) -> None:
        try:
            c = self._speicher()
            name = TAG_SCHLUESSEL + time.strftime("%Y-%m-%d", time.localtime(zeit_s))
            for feld, n in felder.items():
                c.hincrby(name, feld, n)
            c.expire(name, TAG_TTL_S)
        except Exception as exc:  # noqa: BLE001
            logger.debug("openclaw: Tageszähler: %s", exc)

    def _strom(self, eintrag: dict[str, Any]) -> None:
        try:
            self._speicher().xadd(STROM, {k: str(v) for k, v in eintrag.items() if v not in (None, "")},
                                  maxlen=STROM_MAX, approximate=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("openclaw: Strom: %s", exc)

    def _audit(self, zeit_s: float, werkzeug: str, ok: bool, dauer_ms: float, fehler: str, agent: str, sitzung: str) -> None:
        reg = self._registry
        haken = list(getattr(reg, "on_call_hooks", None) or [])
        if not self.audit or not haken:
            return
        ev = AuditEvent(
            timestamp=zeit_s,
            session_id=sitzung or "openclaw",
            caller=f"agent:{agent or 'openclaw'}",
            tool_name=f"{AUDIT_PLUGIN}.{werkzeug}",
            plugin_name=AUDIT_PLUGIN,
            arguments="{}",
            result_status="ok" if ok else "tool_failed",
            latency_ms=dauer_ms,
            error=fehler or None,
            art="bewusst",
        )
        for h in haken:
            try:
                h(ev)
            except Exception as exc:  # noqa: BLE001
                logger.debug("openclaw: Audit-Haken: %s", exc)

    def _eines(self, roh: Any) -> bool:
        if not isinstance(roh, dict):
            return False
        art = str(roh.get("art") or "")
        if art not in ARTEN:
            return False
        zeit_ms = _zahl(roh.get("zeit")) or time.time() * 1000
        if abs(zeit_ms / 1000 - time.time()) > 7 * 86400:
            zeit_ms = time.time() * 1000
        zeit_s = zeit_ms / 1000
        agent = _wort(roh.get("agent"), 40)
        sitzung = _wort(roh.get("sitzung"), 24)
        dauer = max(0.0, _zahl(roh.get("dauer_ms")))
        fehler = _kurz(roh.get("fehler"), 200)
        eintrag: dict[str, Any] = {"t": int(zeit_ms), "a": art, "g": agent, "d": int(dauer), "k": _wort(roh.get("kanal"), 30)}
        if art == "werkzeug":
            name = _wort(roh.get("werkzeug"), 80)
            if not name:
                return False
            if name.startswith(self.auslassen):
                with self._sperre:
                    self._zaehler["ausgelassen"] += 1
                return False
            ok = bool(roh.get("ok", True))
            self._audit(zeit_s, name, ok, dauer, fehler, agent, sitzung)
            self._zaehle("werkzeug", "ok" if ok else "fehler")
            self._tag(zeit_s, {f"werkzeug:{name}": 1, **({"werkzeug_fehler": 1} if not ok else {}), "werkzeuge": 1})
            eintrag.update(n=name, s="ok" if ok else "fail", x=fehler)
        elif art == "modell":
            modell = "/".join(t for t in (_wort(roh.get("anbieter"), 40), _wort(roh.get("modell"), 80)) if t) or "?"
            ergebnis = "ok" if str(roh.get("ergebnis") or "completed") in ("completed", "ok") else "fehler"
            self._zaehle("modell", f"{modell}|{ergebnis}")
            self._tag(zeit_s, {f"modell:{modell}": 1, "modellaufrufe": 1, "modell_ms": int(dauer)})
            eintrag.update(n=modell, s="ok" if ergebnis == "ok" else "fail", x=_kurz(roh.get("fehlerart"), 60))
        elif art == "lauf":
            ok = bool(roh.get("ok", True))
            self._zaehle("lauf", "ok" if ok else "fehler")
            self._tag(zeit_s, {"laeufe": 1, **({"lauf_fehler": 1} if not ok else {})})
            eintrag.update(n=agent or "lauf", s="ok" if ok else "fail", x=fehler)
        elif art == "sitzung":
            phase = "ende" if str(roh.get("phase")) == "ende" else "beginn"
            self._zaehle("sitzung", phase)
            if phase == "beginn":
                self._tag(zeit_s, {"sitzungen": 1})
            eintrag.update(n=sitzung or "sitzung", s=phase, x=_kurz(roh.get("grund"), 40))
        elif art == "cron":
            job = _wort(roh.get("job"), 80)
            aktion = _wort(roh.get("aktion"), 20)
            status = str(roh.get("status") or "")
            if aktion == "finished":
                ok = status in ("ok", "success", "completed")
                self._zaehle("cron", "ok" if ok else "fehler")
                self._tag(zeit_s, {"cron_laeufe": 1, **({"cron_fehler": 1} if not ok else {})})
            with self._sperre:
                self._ablage.pop("cron", None)  # nächster Blick holt den frischen Stand
            eintrag.update(n=_wort(roh.get("name"), 80) or job, s=aktion or status, x=fehler)
        elif art in ("skill", "skill_vorschlag"):
            with self._sperre:
                self._ablage.pop("skills", None)
            eintrag.update(n=_wort(roh.get("name"), 80), s=_wort(roh.get("aktion") or roh.get("status"), 30))
        elif art == "hinweis":
            eintrag.update(n=_wort(roh.get("stufe"), 20) or "hinweis", s="hinweis", x=_kurz(roh.get("text"), 200))
        self._zaehle("ereignisse", art)
        self._strom(eintrag)
        return True

    # ── HTTP-Wege ─────────────────────────────────────────────────────────────────────────────

    def routen(self) -> list[Any]:
        wege = [
            Route("/hub/openclaw/ereignisse", self._weg_ereignisse, methods=["POST"]),
            Route("/hub/openclaw/zustand", self._weg_zustand, methods=["GET"]),
        ]
        if self.modus == "ablage":
            wege += [
                Route("/hub/vorgaenge/tickets", self._weg_tickets, methods=["GET", "POST"]),
                Route("/hub/vorgaenge/tickets/{vid}", self._weg_ticket, methods=["GET", "PATCH"]),
                Route("/hub/vorgaenge/tickets/{vid}/comments", self._weg_kommentar, methods=["POST"]),
            ]
        return wege

    @staticmethod
    def _json_verlangt(request: Request) -> JSONResponse | None:
        typ = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if typ != "application/json":
            return JSONResponse({"ok": False, "error": "Content-Type: application/json verlangt"}, status_code=415)
        return None

    async def _koerper(self, request: Request) -> bytes | None:
        roh = b""
        async for teil in request.stream():
            roh += teil
            if len(roh) > KOERPER_MAX:
                return None
        return roh

    async def _weg_ereignisse(self, request: Request) -> JSONResponse:
        falsch = self._json_verlangt(request)
        if falsch is not None:
            return falsch
        roh = await self._koerper(request)
        if roh is None:
            return JSONResponse({"ok": False, "error": "Lieferung zu groß"}, status_code=413)
        if self._token:
            zeit = request.headers.get("x-fyos-zeit") or ""
            gesendet = request.headers.get("x-fyos-signatur") or ""
            try:
                alt = abs(time.time() - int(zeit) / 1000)
            except ValueError:
                alt = float("inf")
            if alt > ZEIT_TOLERANZ_S or not hmac.compare_digest(gesendet, signatur(self._token, zeit, roh)):
                with self._sperre:
                    self._zaehler["abgewiesen"] += 1
                return JSONResponse({"ok": False, "error": "Signatur fehlt oder passt nicht"}, status_code=401)
        try:
            daten = json.loads(roh.decode() or "{}")
        except ValueError:
            return JSONResponse({"ok": False, "error": "kein JSON"}, status_code=400)
        try:
            n = await asyncio.to_thread(self.annehmen, daten)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "angenommen": n})

    async def _weg_zustand(self, request: Request) -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(self.zustand, False))

    # Ablage: der Vorgangs-Vertrag auf Basis der Karten

    async def _weg_tickets(self, request: Request) -> JSONResponse:
        if request.method == "POST":
            falsch = self._json_verlangt(request)
            if falsch is not None:
                return falsch
            try:
                koerper = json.loads((await request.body()).decode() or "{}")
            except ValueError:
                return JSONResponse({"error": "kein JSON"}, status_code=400)
            return await asyncio.to_thread(self._ticket_anlegen, koerper)
        status = request.query_params.get("status") or ""
        try:
            grenze = max(1, min(int(request.query_params.get("limit") or 50), 500))
        except ValueError:
            grenze = 50
        return await asyncio.to_thread(self._tickets_liste, status, grenze)

    async def _weg_ticket(self, request: Request) -> JSONResponse:
        vid = request.path_params["vid"]
        if request.method == "PATCH":
            falsch = self._json_verlangt(request)
            if falsch is not None:
                return falsch
            try:
                koerper = json.loads((await request.body()).decode() or "{}")
            except ValueError:
                return JSONResponse({"error": "kein JSON"}, status_code=400)
            return await asyncio.to_thread(self._ticket_aendern, vid, koerper)
        return await asyncio.to_thread(self._ticket_holen, vid)

    async def _weg_kommentar(self, request: Request) -> JSONResponse:
        falsch = self._json_verlangt(request)
        if falsch is not None:
            return falsch
        try:
            koerper = json.loads((await request.body()).decode() or "{}")
        except ValueError:
            return JSONResponse({"error": "kein JSON"}, status_code=400)
        return await asyncio.to_thread(self._ticket_kommentieren, request.path_params["vid"], koerper)

    @staticmethod
    def _gescheitert(exc: Exception) -> JSONResponse:
        text = str(exc)
        status = 409 if "workboard_conflict" in text or "conflict" in text.lower() else 502
        return JSONResponse({"error": _kurz(text, 300)}, status_code=status)

    def _tickets_liste(self, status: str, grenze: int) -> JSONResponse:
        try:
            karten = self.karten()
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        tickets = [V.vorgang_aus_karte(k) for k in karten]
        if status:
            tickets = [t for t in tickets if t["status"] == status]
        tickets.sort(key=lambda t: -_zahl(t.get("updated_at")))
        return JSONResponse({"tickets": tickets[:grenze], "quelle": "workboard", "board": self.board})

    def _ticket_holen(self, vid: str) -> JSONResponse:
        try:
            karte = V.karte_zur_id(self.karten(), vid)
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        if karte is None:
            return JSONResponse({"error": f"kein Vorgang {vid}"}, status_code=404)
        return JSONResponse(V.vorgang_aus_karte(karte))

    def _ticket_anlegen(self, koerper: Any) -> JSONResponse:
        if not isinstance(koerper, dict) or not str(koerper.get("title") or "").strip():
            return JSONResponse({"error": "title fehlt"}, status_code=400)
        status = str(koerper.get("status") or "new")
        params: dict[str, Any] = {
            "title": V._kurz(" ".join(str(koerper["title"]).split()), V.TITEL_MAX),
            "notes": V._kurz(str(koerper.get("description") or ""), V.NOTIZ_MAX),
            "status": V.KARTE_FUER.get(status, "triage"),
            "priority": V.prioritaet(koerper.get("priority")),
            "labels": [f"typ:{V.typ(koerper)}"] if koerper.get("type") else [],
            "boardId": self.board,
        }
        if koerper.get("source_url"):
            params["sourceUrl"] = str(koerper["source_url"])[:2000]
        try:
            antwort = self.rpc("workboard.cards.create", params) or {}
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        with self._sperre:
            self._ablage.pop("karten", None)
        karte = antwort.get("card") if isinstance(antwort, dict) else None
        return JSONResponse(V.vorgang_aus_karte(karte or {}), status_code=201)

    def _ticket_kommentieren(self, vid: str, koerper: Any) -> JSONResponse:
        text = str((koerper or {}).get("text") or "").strip() if isinstance(koerper, dict) else ""
        if not text:
            return JSONResponse({"error": "text fehlt"}, status_code=400)
        akteur = _wort((koerper or {}).get("actor"), 40)
        try:
            karte = V.karte_zur_id(self.karten(), vid)
            if karte is None:
                return JSONResponse({"error": f"kein Vorgang {vid}"}, status_code=404)
            self.rpc("workboard.cards.comment", {"id": karte["id"], "body": V._kurz(f"{akteur}: {text}" if akteur else text, 2000)})
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        with self._sperre:
            self._ablage.pop("karten", None)
        return JSONResponse({"ok": True, "id": vid})

    def _ticket_aendern(self, vid: str, koerper: Any) -> JSONResponse:
        if not isinstance(koerper, dict):
            return JSONResponse({"error": "Objekt erwartet"}, status_code=400)
        try:
            karte = V.karte_zur_id(self.karten(frisch=True), vid)
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        if karte is None:
            return JSONResponse({"error": f"kein Vorgang {vid}"}, status_code=404)
        jetzt = V.vorgang_aus_karte(karte)
        erwartet = str(koerper.get("expected_status") or "")
        if erwartet and jetzt["status"] != erwartet:
            return JSONResponse({"error": "status_conflict", "ticket": jetzt}, status_code=409)
        try:
            ziel = str(koerper.get("status") or "")
            if ziel:
                if ziel not in V.KARTE_FUER:
                    return JSONResponse({"error": f"unbekannter Status {ziel}"}, status_code=400)
                antwort = self.rpc("workboard.cards.move", {"id": karte["id"], "status": V.KARTE_FUER[ziel],
                                                            "expectedUpdatedAt": karte.get("updatedAt")}) or {}
                karte = antwort.get("card") or karte
                if ziel == "closed":
                    antwort = self.rpc("workboard.cards.archive", {"id": karte["id"], "archived": True}) or {}
                    karte = antwort.get("card") or karte
            patch: dict[str, Any] = {}
            if koerper.get("title"):
                patch["title"] = V._kurz(" ".join(str(koerper["title"]).split()), V.TITEL_MAX)
            if "description" in koerper:
                patch["notes"] = V._kurz(str(koerper.get("description") or ""), V.NOTIZ_MAX)
            if koerper.get("priority"):
                patch["priority"] = V.prioritaet(koerper["priority"])
            if patch:
                antwort = self.rpc("workboard.cards.update", {"id": karte["id"], "patch": patch}) or {}
                karte = antwort.get("card") or karte
            akteur = _wort(koerper.get("actor"), 40)
            if ziel and akteur:
                self.rpc("workboard.cards.comment", {"id": karte["id"], "body": f"{akteur}: Status {jetzt['status']} → {ziel}"})
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)
        with self._sperre:
            self._ablage.pop("karten", None)
        return JSONResponse(V.vorgang_aus_karte(karte))

    # ── Spiegel: Vorgangs-Dienst → Workboard und zurück ───────────────────────────────────────

    def _stand_laden(self) -> dict[str, dict[str, Any]]:
        if self._karten_stand is None:
            stand: dict[str, dict[str, Any]] = {}
            try:
                for kid, roh in (self._speicher().hgetall(KARTEN_STAND) or {}).items():
                    try:
                        stand[kid] = json.loads(roh)
                    except ValueError:
                        continue
            except Exception as exc:  # noqa: BLE001
                logger.debug("openclaw: Kartenstand nicht lesbar: %s", exc)
            self._karten_stand = stand
        return self._karten_stand

    def _stand_sichern(self, stand: dict[str, dict[str, Any]], weg: set[str]) -> None:
        try:
            c = self._speicher()
            if stand:
                c.hset(KARTEN_STAND, mapping={k: json.dumps(v) for k, v in stand.items()})
            if weg:
                c.hdel(KARTEN_STAND, *weg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("openclaw: Kartenstand nicht gesichert: %s", exc)

    def _board_sicherstellen(self) -> None:
        if self._board_bereit:
            return
        # Ohne automationJobId, orchestration und defaultWorkspace bleibt das Board passiv (kein Dispatch).
        self.rpc("workboard.boards.upsert", {
            "id": self.board,
            "name": "FYOS-Vorgänge",
            "description": "Spiegel der offenen FYOS-Vorgänge. Quelle ist der Vorgangs-Dienst; Verschieben einer Karte "
                           "trägt den Status zurück, Freigaben entscheidet der Freigabeweg.",
            "icon": "inbox",
        })
        self._board_bereit = True

    def abgleichen(self) -> dict[str, Any]:
        """Ein Abgleich Vorgangs-Dienst ↔ Workboard (nur im Spiegel)."""
        if self.modus != "spiegel":
            return {"ok": True, "modus": self.modus, "schritte": 0,
                    "satz": "Kein Vorgangs-Dienst eingetragen: das Workboard ist selbst die Ablage, nichts zu spiegeln."
                    if self.modus == "ablage" else "Kopplung aus (FYOS_AGENT_URL fehlt)."}
        if not self._abgleich_sperre.acquire(blocking=False):
            return {"ok": False, "modus": self.modus, "laeuft": True, "satz": "Ein Abgleich läuft gerade."}
        try:
            return self._abgleich_einmal()
        except Exception as exc:  # noqa: BLE001
            self._lauf("abgleich", "fehler", str(exc))
            return {"ok": False, "modus": self.modus, "satz": f"Abgleich gescheitert: {_kurz(exc, 300)}"}
        finally:
            self._abgleich_sperre.release()

    def _abgleich_einmal(self) -> dict[str, Any]:
        self._board_sicherstellen()
        vorgaenge: dict[str, dict[str, Any]] = {}
        for status in V.OFFEN:
            antwort = self._vd("GET", f"/tickets?status={status}&limit=200") or {}
            for t in antwort.get("tickets") or []:
                if isinstance(t, dict) and t.get("id"):
                    vorgaenge[str(t["id"])] = t
        karten = self.karten(frisch=True)
        stand = self._stand_laden()
        erledigt: dict[str, str] = {}
        for k in karten:
            vid = V.vorgang_id_der_karte(k)
            if vid and vid not in vorgaenge and k.get("status") != "done":
                try:
                    t = self._vd("GET", f"/tickets/{urllib.parse.quote(vid, safe='')}") or {}
                    erledigt[vid] = str(t.get("status") or "unbekannt")
                except Exception as exc:  # noqa: BLE001 — nur ein sicheres „gibt es nicht“ (404) schließt die Karte
                    if getattr(exc, "status", 0) == 404:
                        erledigt[vid] = "unbekannt"
        schritte = V.plan(vorgaenge, karten, stand, self.board, self.vorgang_link, erledigt)
        nach_id = {str(k.get("id")): k for k in karten}
        protokoll: list[dict[str, Any]] = []
        fehler = 0
        for s in schritte[:SCHRITTE_MAX]:
            eintrag = {"art": s.art, "vorgang": s.vorgang, "grund": s.grund}
            try:
                karte = self._schritt(s)
                if karte:
                    nach_id[str(karte.get("id"))] = karte
                    stand[str(karte.get("id"))] = {"u": karte.get("updatedAt"), "s": karte.get("status"),
                                                    "e": karte.get("updatedAt"), "v": s.vorgang}
                eintrag["ok"] = True
            except Exception as exc:  # noqa: BLE001
                fehler += 1
                eintrag.update(ok=False, fehler=_kurz(exc, 200))
                if s.art == "zurueck" and s.karte and s.karte in nach_id:
                    # Rückweg abgelehnt (z. B. Konflikt): die Änderung gilt als gesehen, der Vorgang bleibt führend.
                    k = nach_id[s.karte]
                    stand[s.karte] = {**stand.get(s.karte, {}), "u": k.get("updatedAt")}
            protokoll.append(eintrag)
        # Alles Gesehene merken; Kommentare aus OpenClaw an den Vorgang geben.
        weg = set(stand) - set(nach_id)
        for kid, k in nach_id.items():
            alt = stand.get(kid) or {}
            vid = V.vorgang_id_der_karte(k) or alt.get("v")
            kommentare = [c for c in ((k.get("metadata") or {}).get("comments") or []) if isinstance(c, dict) and c.get("id")]
            gesehen = set(alt.get("c") or [])
            if alt and vid and vid in vorgaenge:
                for c in kommentare:
                    if c["id"] not in gesehen:
                        try:
                            self._vd("POST", f"/tickets/{urllib.parse.quote(vid, safe='')}/comments",
                                     {"actor": self.akteur, "text": V._kurz(f"Kommentar in OpenClaw: {c.get('body') or ''}", 2000)})
                            protokoll.append({"art": "kommentar_zurueck", "vorgang": vid, "ok": True})
                        except Exception as exc:  # noqa: BLE001
                            fehler += 1
                            protokoll.append({"art": "kommentar_zurueck", "vorgang": vid, "ok": False, "fehler": _kurz(exc, 200)})
            stand[kid] = {**alt, "u": k.get("updatedAt"), "s": k.get("status"), "v": vid,
                          "c": [c["id"] for c in kommentare][-50:]}
        for kid in weg:
            stand.pop(kid, None)
        self._stand_sichern(stand, weg)
        with self._sperre:
            self._ablage["karten"] = (time.monotonic(), list(nach_id.values()))
            self._letzte_schritte = protokoll[-30:]
        self._lauf("abgleich", "fehler" if fehler else "ok", f"{fehler} Schritt(e) gescheitert" if fehler else "")
        satz = (f"{len(vorgaenge)} offene Vorgänge, {len(nach_id)} Karten auf „{self.board}“; "
                f"{len(protokoll)} Schritt(e), {fehler} gescheitert.")
        return {"ok": fehler == 0, "modus": "spiegel", "satz": satz, "schritte": len(protokoll), "fehler": fehler,
                "protokoll": protokoll[-30:], "uebersprungen": max(0, len(schritte) - SCHRITTE_MAX)}

    def _schritt(self, s: V.Schritt) -> dict[str, Any] | None:
        if s.art == "anlegen":
            return (self.rpc("workboard.cards.create", s.daten) or {}).get("card")
        if s.art == "verschieben":
            return (self.rpc("workboard.cards.move", {"id": s.karte, "status": s.daten["status"]}) or {}).get("card")
        if s.art == "aendern":
            return (self.rpc("workboard.cards.update", {"id": s.karte, "patch": s.daten}) or {}).get("card")
        vid = urllib.parse.quote(s.vorgang, safe="")
        if s.art == "kommentar":
            self._vd("POST", f"/tickets/{vid}/comments", {"actor": self.akteur, "text": s.daten["text"]})
            return None
        if s.art == "zurueck":
            self._vd("POST", f"/tickets/{vid}/comments", {
                "actor": self.akteur,
                "text": f"In OpenClaw verschoben: {s.daten.get('von') or '?'} → {s.daten.get('nach')}; Status wird {s.daten['status']}."})
            koerper: dict[str, Any] = {"actor": self.akteur, "status": s.daten["status"], "expected_status": s.daten["erwartet"]}
            if s.daten["erwartet"] == "waiting_approval":
                koerper["waiting_for"] = ""
            self._vd("PATCH", f"/tickets/{vid}", koerper)
            return None
        raise ValueError(f"unbekannter Schritt {s.art}")

    # ── Takt ──────────────────────────────────────────────────────────────────────────────────

    def _takt(self) -> None:
        letzte: dict[str, float] = {}
        while not self._halt.is_set():
            try:
                self.takt_schritt(letzte)
            except Exception as exc:  # noqa: BLE001
                logger.debug("openclaw: Takt: %s", exc)
            self._halt.wait(15.0)

    def takt_schritt(self, letzte: dict[str, float], jetzt: float | None = None) -> None:
        """Ein Schlag des Takts: Sonde immer, Cron/Skills/Karten und Abgleich nach ihren Abständen.

        Diese vier laufen über den Wächter (``takt_grenzen``): außerhalb des Fensters oder über dem Tageslimit
        werden sie übersprungen und gezählt; ohne Grenzen laufen sie wie immer.
        """
        jetzt = time.monotonic() if jetzt is None else jetzt

        def faellig(name: str, abstand: float) -> bool:
            if abstand <= 0 or jetzt - letzte.get(name, -1e18) < abstand:
                return False
            letzte[name] = jetzt
            return True

        self.sonde(frisch=True)
        if not self._token and self._rpc_aufruf is None:
            return
        for name, abstand, tun in (
            ("cron", 60.0, lambda: self.cron_auftraege(frisch=True)),
            ("skills", 300.0, lambda: self.agent_skills(frisch=True)),
        ):
            if faellig(name, abstand):
                try:
                    self._waechter.ausfuehren(name, tun)
                except Exception:  # noqa: BLE001 — Fehler steht in _laeufe und im Laufprotokoll
                    pass
        if self.modus == "spiegel" and faellig("abgleich", self.abgleich_s):
            self._waechter.ausfuehren("abgleich", self.abgleichen)
        elif self.modus == "ablage" and faellig("karten", 60.0):
            try:
                self._waechter.ausfuehren("karten", lambda: self.karten(frisch=True))
            except Exception:  # noqa: BLE001
                pass

    # ── Beiträge zu gemeinsamen Ansichten ─────────────────────────────────────────────────────

    def zeitplan(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for j in self._gemerkt("cron") or []:
            status = str(j.get("lastRunStatus") or "").lower()
            out.append({
                "id": f"cron:{j.get('id')}",
                "name": _wort(j.get("displayName") or j.get("name") or j.get("id"), 120),
                "beschreibung": f"Cron des Agenten {j.get('effectiveAgentId') or j.get('agentId') or ''}".strip(),
                "takt": _takt_text(j.get("schedule")) or str(j.get("scheduleKind") or ""),
                "an": bool(j.get("enabled", True)),
                "naechster": _zahl(j.get("nextRunAtMs")) / 1000 or None,
                "letzter": _zahl(j.get("lastRunAtMs")) / 1000 or None,
                "letzter_status": "ok" if status in ("ok", "success", "completed") else ("fehler" if status in ("error", "failed", "timeout") else None),
                "letzter_fehler": _kurz(j.get("lastRunError"), 200) or None,
                "quelle": "openclaw",
            })
        if self.modus != "aus":
            reihen = [
                ("sonde", "Zustand des Agenten prüfen", "alle 15 s"),
                ("abgleich" if self.modus == "spiegel" else "karten",
                 "Vorgänge ↔ Workboard abgleichen" if self.modus == "spiegel" else "Workboard-Karten lesen",
                 f"alle {self.abgleich_s:g} s" if self.modus == "spiegel" else "alle 60 s"),
            ]
            # Cron- und Skill-Liste des Agenten liest der Hub im Hintergrund; in der Ansicht erscheinen sie,
            # sobald ihnen Grenzen gesetzt sind (dann will man sehen, was sie tun).
            for name, titel_, takt_text in (("cron", "Cron-Aufträge des Agenten abfragen", "alle 60 s"),
                                            ("skills", "Skills des Agenten abfragen", "alle 5 min")):
                if not self._waechter.grenzen(name).leer:
                    reihen.append((name, titel_, takt_text))
            for name, titel_, takt_text in reihen:
                lauf = self._laeufe.get(name) or {}
                out.append({"id": name, "name": titel_, "takt": takt_text, "an": True,
                            "letzter": lauf.get("letzter"), "letzter_status": lauf.get("status"),
                            "letzter_fehler": lauf.get("fehler"),
                            **({} if name == "sonde" else self._waechter.felder(name))})
        return out

    @staticmethod
    def _plugin_skill(skill: dict[str, Any]) -> bool:
        """Skill eines OpenClaw-Plugins: verlinkt nach ~/.openclaw/plugin-skills/, die Quelle bleibt openclaw-extra."""
        return any("/plugin-skills/" in str(skill.get(k) or "") for k in ("filePath", "baseDir"))

    @classmethod
    def _mitgeliefert(cls, skill: dict[str, Any]) -> bool:
        return skill.get("bundled") is True or "bundled" in str(skill.get("source") or "") or cls._plugin_skill(skill)

    def skills_beitrag(self) -> list[dict[str, Any]]:
        """Skills des Agenten für ``skills.suchen``: eigene, gelernte und die aus fyos-agent.

        Nicht dabei: die mit OpenClaw mitgelieferten, gebündelt oder von seinen Plugins (sie beschreiben Werkzeuge,
        die nur der Agent hat), und abgeschaltete. Gleichnamige Skills des Hubs gewinnen; das Plugin skills ergänzt
        Beiträge nach seinen Dateien.
        """
        out: list[dict[str, Any]] = []
        for s in self._gemerkt("skills") or []:
            name = str(s.get("name") or "")
            if not name or self._mitgeliefert(s) or s.get("disabled") or s.get("eligible") is False:
                continue
            pfad = str(s.get("filePath") or "")
            out.append({
                "name": name,
                "beschreibung": str(s.get("description") or ""),
                "quelle": "fyos-agent" if any(pfad.startswith(p) for p in self.fyos_skill_pfade) else "openclaw",
                "ausloeser": "",
                "lesen": (lambda n=name: self._skill_text(n)),
            })
        return out

    def metrics(self) -> dict[str, Any]:
        sonde = self._gemerkt("sonde") or {}
        with self._sperre:
            z = json.loads(json.dumps(self._zaehler))
            b = dict(self._bruecke)
            rpc = dict(self._rpc_stand)
        proben: list[dict[str, Any]] = [
            {"name": "fyos_openclaw_gateway_lebt", "wert": bool(sonde.get("lebt")), "hilfe": "Gateway antwortet auf /healthz"},
            {"name": "fyos_openclaw_gateway_bereit", "wert": bool(sonde.get("bereit")), "hilfe": "Gateway antwortet auf /readyz mit 200"},
            {"name": "fyos_openclaw_rpc_fehler_total", "wert": rpc["fehler"], "typ": "counter", "hilfe": "Gescheiterte Abfragen über die Brücke"},
            {"name": "fyos_openclaw_abgewiesen_total", "wert": z["abgewiesen"], "typ": "counter", "hilfe": "Lieferungen mit falscher Signatur"},
        ]
        if b.get("zuletzt"):
            proben.append({"name": "fyos_openclaw_bruecke_alter_s", "wert": round(time.time() - b["zuletzt"], 1),
                           "hilfe": "Sekunden seit der letzten Lieferung der Brücke"})
            proben.append({"name": "fyos_openclaw_bruecke_verworfen", "wert": b.get("verworfen", 0),
                           "hilfe": "Von der Brücke verworfene Ereignisse (volle Warteschlange)"})
        for art, n in z["ereignisse"].items():
            proben.append({"name": "fyos_openclaw_ereignisse_total", "wert": n, "labels": {"art": art}, "typ": "counter",
                           "hilfe": "Angenommene Ereignisse der Brücke"})
        for ergebnis, n in z["werkzeug"].items():
            proben.append({"name": "fyos_openclaw_werkzeugaufrufe_total", "wert": n, "labels": {"ergebnis": ergebnis},
                           "typ": "counter", "hilfe": "Werkzeugaufrufe des Agenten (ohne Hub-Werkzeuge)"})
        for schluessel, n in z["modell"].items():
            modell, _, ergebnis = schluessel.rpartition("|")
            proben.append({"name": "fyos_openclaw_modellaufrufe_total", "wert": n, "typ": "counter",
                           "labels": {"modell": modell, "ergebnis": ergebnis}, "hilfe": "Modellaufrufe des Agenten"})
        for ergebnis, n in z["lauf"].items():
            proben.append({"name": "fyos_openclaw_laeufe_total", "wert": n, "labels": {"ergebnis": ergebnis},
                           "typ": "counter", "hilfe": "Agentenläufe"})
        for phase, n in z["sitzung"].items():
            proben.append({"name": "fyos_openclaw_sitzungen_total", "wert": n, "labels": {"phase": phase},
                           "typ": "counter", "hilfe": "Beginn und Ende von Sitzungen"})
        for ergebnis, n in z["cron"].items():
            proben.append({"name": "fyos_openclaw_cron_laeufe_total", "wert": n, "labels": {"ergebnis": ergebnis},
                           "typ": "counter", "hilfe": "Beendete Cron-Läufe des Agenten"})
        je_status: dict[str, int] = {}
        for k in self._gemerkt("karten") or []:
            je_status[str(k.get("status"))] = je_status.get(str(k.get("status")), 0) + 1
        for status, n in je_status.items():
            proben.append({"name": "fyos_openclaw_karten", "wert": n, "labels": {"board": self.board, "status": status},
                           "hilfe": "Karten auf dem Board der Vorgänge"})
        return {"_proben": proben}

    def health(self) -> dict[str, Any]:
        if not self.gateway_url:
            return {"ok": True, "status": "aus", "reason": "FYOS_AGENT_URL nicht gesetzt: keine Kopplung an OpenClaw"}
        s = self.sonde()
        if not s.get("lebt"):
            return {"ok": False, "status": "unreachable", "reason": s.get("fehler") or "Gateway antwortet nicht auf /healthz"}
        hinweise = []
        with self._sperre:
            zuletzt = self._bruecke.get("zuletzt")
        if zuletzt is None:
            hinweise.append("Brücke hat sich noch nicht gemeldet")
        elif time.time() - zuletzt > STILL_S:
            return {"ok": False, "status": "degraded", "reason": f"Brücke still seit {int(time.time() - zuletzt)} s"}
        if not s.get("bereit"):
            return {"ok": False, "status": "degraded", "reason": "Gateway nicht bereit: " + (", ".join(s.get("fehlt") or []) or "/readyz")}
        if not self._token:
            hinweise.append("FYOS_AGENT_TOKEN fehlt: Workboard, Skills und Cron bleiben unsichtbar")
        return {"ok": True, "status": "healthy", "modus": self.modus, "hinweise": hinweise}

    # ── Werkzeuge ─────────────────────────────────────────────────────────────────────────────

    def zustand(self, frisch: bool = False) -> dict[str, Any]:
        s = self.sonde(frisch)
        with self._sperre:
            b = dict(self._bruecke)
            rpc = dict(self._rpc_stand)
            z = json.loads(json.dumps(self._zaehler))
            laeufe = dict(self._laeufe)
        alter = round(time.time() - b["zuletzt"]) if b.get("zuletzt") else None
        teile = []
        if self.modus == "aus":
            teile.append("Kopplung aus (FYOS_AGENT_URL fehlt)")
        else:
            teile.append("Gateway " + ("bereit" if s.get("bereit") else ("lebt, nicht bereit" if s.get("lebt") else "nicht erreichbar")))
            teile.append(f"Brücke vor {alter} s" if alter is not None else "Brücke noch ohne Meldung")
            teile.append({"spiegel": "Vorgänge gespiegelt", "ablage": "Workboard ist die Ablage"}[self.modus])
        return {
            "satz": "; ".join(teile) + ".",
            "modus": self.modus,
            "gateway": {k: v for k, v in s.items() if k != "stand"},
            "bruecke": {**{k: v for k, v in b.items() if k != "plugins"}, "alter_s": alter, "plugins": len(b.get("plugins") or [])},
            "rpc": rpc,
            "token": bool(self._token),
            "vorgaenge": {"dienst": bool(self.vorgaenge_url), "board": self.board},
            "zaehler": z,
            "laeufe": laeufe,
        }

    def nutzung(self, tage: int = 7) -> dict[str, Any]:
        tage = max(1, min(int(tage), 31))
        heute = time.time()
        tage_liste = []
        summe: dict[str, int] = {}
        werkzeuge: dict[str, int] = {}
        modelle: dict[str, int] = {}
        for i in range(tage):
            tag = time.strftime("%Y-%m-%d", time.localtime(heute - i * 86400))
            try:
                roh = self._speicher().hgetall(TAG_SCHLUESSEL + tag) or {}
            except Exception:  # noqa: BLE001
                roh = {}
            zeile = {"tag": tag}
            for feld, wert in roh.items():
                n = int(_zahl(wert))
                if feld.startswith("werkzeug:"):
                    werkzeuge[feld[9:]] = werkzeuge.get(feld[9:], 0) + n
                elif feld.startswith("modell:"):
                    modelle[feld[7:]] = modelle.get(feld[7:], 0) + n
                else:
                    zeile[feld] = n
                    summe[feld] = summe.get(feld, 0) + n
            tage_liste.append(zeile)
        laut_openclaw: Any = None
        fehler = None
        if self.modus != "aus":
            von = time.strftime("%Y-%m-%d", time.localtime(heute - (tage - 1) * 86400))
            bis = time.strftime("%Y-%m-%d", time.localtime(heute))
            try:
                laut_openclaw = self._zwischen(f"kosten:{tage}", 300.0, lambda: self.rpc(
                    "usage.cost", {"startDate": von, "endDate": bis, "agentScope": "all"}))
            except Exception as exc:  # noqa: BLE001
                fehler = _kurz(exc, 200)
        oben = sorted(werkzeuge.items(), key=lambda x: -x[1])[:15]
        satz = (f"{tage} Tage: {summe.get('werkzeuge', 0)} Werkzeugaufrufe, {summe.get('modellaufrufe', 0)} Modellaufrufe, "
                f"{summe.get('laeufe', 0)} Läufe, {summe.get('sitzungen', 0)} Sitzungen (von der Brücke gezählt).")
        return {
            "satz": satz,
            "tage": tage_liste,
            "summe": summe,
            "werkzeuge": [{"werkzeug": w, "aufrufe": n} for w, n in oben],
            "modelle": [{"modell": m, "aufrufe": n} for m, n in sorted(modelle.items(), key=lambda x: -x[1])],
            "laut_openclaw": laut_openclaw,
            "laut_openclaw_fehler": fehler,
            "hinweis": "Token und Kosten zählt OpenClaw selbst (usage.cost); die Brücke zählt Aufrufe, nicht Inhalte. "
                       "Hub-Werkzeuge, die der Agent über MCP ruft, stehen im Audit des Hubs (audit.nutzung).",
        }

    def aktivitaet(self, grenze: int = 50, art: str = "") -> dict[str, Any]:
        grenze = max(1, min(int(grenze), 500))
        try:
            roh = self._speicher().xrevrange(STROM, count=grenze * (4 if art else 1)) or []
        except Exception as exc:  # noqa: BLE001
            return {"satz": f"Aktivität nicht lesbar: {_kurz(exc, 120)}", "eintraege": []}
        eintraege = []
        for _id, f in roh:
            if art and f.get("a") != art:
                continue
            eintraege.append({
                "zeit": int(_zahl(f.get("t"))) / 1000,
                "art": f.get("a"),
                "name": f.get("n"),
                "status": f.get("s"),
                "dauer_ms": int(_zahl(f.get("d"))),
                "agent": f.get("g"),
                "kanal": f.get("k"),
                "hinweis": f.get("x"),
            })
            if len(eintraege) >= grenze:
                break
        return {"satz": f"{len(eintraege)} Ereignisse aus OpenClaw (neueste zuerst).", "eintraege": eintraege}

    def erweiterungen(self) -> dict[str, Any]:
        fehler: dict[str, str] = {}
        try:
            agent_skills = self.agent_skills() if self.modus != "aus" else []
        except Exception as exc:  # noqa: BLE001
            agent_skills, fehler["skills"] = [], _kurz(exc, 200)
        reg = self._registry
        hub_skills: dict[str, str] = {}
        skills_plugin = (getattr(reg, "plugins", None) or {}).get("skills")
        if skills_plugin is not None and hasattr(skills_plugin, "katalog"):
            try:
                # Ohne die Beiträge dieses Plugins (Pfad "openclaw:<name>"): das sind die Skills des Agenten selbst.
                hub_skills = {n: e.get("quelle", "") for n, e in skills_plugin.katalog().items()
                              if not str(e.get("pfad") or "").startswith(f"{self.name}:")}
            except Exception as exc:  # noqa: BLE001
                fehler["hub_skills"] = _kurz(exc, 200)
        zeilen = []
        for s in agent_skills:
            pfad = str(s.get("filePath") or "")
            von_fyos = any(pfad.startswith(p) for p in self.fyos_skill_pfade)
            quelle = "openclaw-plugin" if self._plugin_skill(s) else str(s.get("source") or "")
            zeilen.append({
                "name": s.get("name"),
                "quelle": "fyos" if von_fyos else quelle,
                "nutzbar": bool(s.get("eligible", True)) and not s.get("disabled"),
                "modell_sieht_ihn": bool(s.get("modelVisible", True)),
                "auch_im_hub": s.get("name") in hub_skills,
            })
        with self._sperre:
            agent_plugins = list(self._bruecke.get("plugins") or [])
        hub_plugins = [{"name": n, "version": getattr(p, "version", ""),
                        "werkzeuge": sum(1 for t in (getattr(reg, "tools", None) or {}).values() if getattr(t, "plugin_name", "") == n)}
                       for n, p in sorted((getattr(reg, "plugins", None) or {}).items())]
        im_agent = {z["name"] for z in zeilen}
        nur_hub = sorted(n for n in hub_skills if n not in im_agent)
        satz = (f"Agent: {len(zeilen)} Skills ({sum(1 for z in zeilen if z['quelle'] == 'fyos')} aus FYOS), "
                f"{len(agent_plugins)} Plugins; Hub: {len(hub_plugins)} Plugins, {len(hub_skills)} Skills "
                f"({len(nur_hub)} davon sieht der Agent nicht als Skill, nur über skills.lesen).")
        return {"satz": satz, "agent_skills": zeilen, "agent_plugins": agent_plugins, "hub_plugins": hub_plugins,
                "hub_skills_nur_im_hub": nur_hub[:100], "fehler": fehler}

    def arbeit(self) -> dict[str, Any]:
        if self.modus == "aus":
            return {"satz": "Kopplung aus (FYOS_AGENT_URL fehlt).", "modus": "aus", "karten": []}
        try:
            karten = self.karten()
        except Exception as exc:  # noqa: BLE001
            return {"satz": f"Workboard nicht lesbar: {_kurz(exc, 200)}", "modus": self.modus, "karten": []}
        je_status: dict[str, int] = {}
        for k in karten:
            je_status[str(k.get("status"))] = je_status.get(str(k.get("status")), 0) + 1
        offen = [k for k in karten if k.get("status") != "done"]
        offen.sort(key=lambda k: (V.KARTEN_STATUS.index(k["status"]) if k.get("status") in V.KARTEN_STATUS else 99,
                                  -_zahl(k.get("updatedAt"))))
        zeilen = [{"id": V.vorgang_id_der_karte(k) or V.ablage_id(k), "titel": k.get("title"), "status": k.get("status"),
                   "prioritaet": k.get("priority"), "vorgang": V.vorgang_id_der_karte(k)} for k in offen[:50]]
        with self._sperre:
            schritte = list(self._letzte_schritte)
        lauf = self._laeufe.get("abgleich") or {}
        satz = (f"Board „{self.board}“: {len(offen)} offene von {len(karten)} Karten "
                + ("(Spiegel der Vorgänge)." if self.modus == "spiegel" else "(Workboard ist die Ablage)."))
        return {"satz": satz, "modus": self.modus, "board": self.board, "je_status": je_status, "karten": zeilen,
                "abgleich": lauf, "letzte_schritte": schritte}

    def describe_tools(self) -> list[ToolDescriptor]:
        leer = {"type": "object", "properties": {}, "additionalProperties": False}
        return [
            ToolDescriptor(
                name="zustand",
                title="OpenClaw — Zustand",
                description=(
                    "Zustand des Agenten-Gateways (OpenClaw) aus FYOS-Sicht: Sonden /healthz und /readyz, wann die Brücke "
                    "zuletzt meldete, Betriebsart der Vorgänge (Spiegel oder Workboard als Ablage), Zähler und Takte."
                ),
                input_schema={"type": "object", "properties": {"frisch": {"type": "boolean", "default": False}},
                              "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="nutzung",
                title="OpenClaw — Nutzung",
                description=(
                    "Nutzung des Agenten je Tag: Werkzeug- und Modellaufrufe, Läufe, Sitzungen (von der Brücke gezählt) und "
                    "Token und Kosten laut OpenClaw selbst (usage.cost). `tage` 1–31, Vorgabe 7."
                ),
                input_schema={"type": "object", "properties": {"tage": {"type": "integer", "minimum": 1, "maximum": 31}},
                              "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="aktivitaet",
                title="OpenClaw — Aktivität",
                description=(
                    "Was der Agent zuletzt tat, neueste zuerst: Werkzeug- und Modellaufrufe, Läufe, Sitzungen, Cron-Läufe, "
                    "Skill-Änderungen, Hinweise. Nur Namen, Dauer und Ergebnis. `art` filtert (werkzeug, modell, lauf, "
                    "sitzung, cron, skill, skill_vorschlag, hinweis)."
                ),
                input_schema={"type": "object", "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "art": {"type": "string", "enum": list(ARTEN)},
                }, "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="erweiterungen",
                title="OpenClaw — Erweiterungen",
                description=(
                    "Skills und Plugins beider Seiten nebeneinander: welche Skills der Agent hat (und welche davon aus FYOS "
                    "stammen), welche Plugins im Gateway geladen sind, welche Hub-Plugins und -Skills es gibt."
                ),
                input_schema=leer,
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="arbeit",
                title="OpenClaw — Workboard",
                description=(
                    "Das Workboard des Agenten aus FYOS-Sicht: offene Karten des Vorgangs-Boards je Status, ihr Vorgang, "
                    "der letzte Abgleich mit dem Vorgangs-Dienst und seine Schritte."
                ),
                input_schema=leer,
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="abgleichen",
                title="OpenClaw — Vorgänge abgleichen",
                description=(
                    "Vorgangs-Dienst und Workboard jetzt abgleichen (sonst im Takt): offene Vorgänge als Karten anlegen "
                    "oder nachführen, Verschiebungen aus OpenClaw in den Vorgang tragen. Freigaben entscheidet nie das "
                    "Workboard."
                ),
                input_schema=leer,
                tags=["openclaw", "agent", "write"],
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "zustand":
            return self.zustand(bool(args.get("frisch")))
        if method == "nutzung":
            return self.nutzung(int(args.get("tage") or 7))
        if method == "aktivitaet":
            return self.aktivitaet(int(args.get("limit") or 50), str(args.get("art") or ""))
        if method == "erweiterungen":
            return self.erweiterungen()
        if method == "arbeit":
            return self.arbeit()
        if method == "abgleichen":
            return self.abgleichen()
        raise ValueError(f"openclaw hat kein Werkzeug {method!r}")
