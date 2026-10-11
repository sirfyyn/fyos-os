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
    agent             Kennung des Agenten, den der Hub weckt (FYOS_AGENT, sonst main)
    wecken            Wecker (``_wecker``): ``{aktiv: true, intervall_s: 15, vorlauf_min: 10, max_pro_minute: 10,
                      max_alter_s: 900, quellen: {vorgaenge, termine, postfach, dokumente: true}, strome: [], regeln: []}``;
                      ohne ``regeln`` gelten ``_wecker.vorgaben_regeln``. ``strome`` nennt Ereignisströme (Redis-Streams),
                      aus denen jeder neue Eintrag ein Umschlag wird. Eine Regel mit ``weiche: true`` fragt vor dem
                      Wecken die Weiche (``_dienste``).
    dienste           optionale Dienste ``{weiche_url, rerank_url, mund_url, ohr_url}`` (sonst FYOS_WEICHE_URL,
                      FYOS_RERANK_URL, FYOS_MUND_URL, FYOS_OHR_URL); jeder fehlende oder ausfallende Dienst ist
                      folgenlos (``_dienste``, Werkzeug ``dienste``)
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

from .. import dokumente as _dokumente
from .. import kv
from .. import postfach as _postfach
from .. import takt as _takt
from .. import termine as _termine
from .. import umschlag as U
from .. import vorgaenge as _vorgangsquellen
from ..audit_log import AuditEvent, schwaerzen
from ..plugin import HubPlugin, ToolDescriptor
from ..vorgaenge import (
    VorgangFehlt,
    VorgangKonflikt,
    ablage_anmelden,
    angemeldete_ablage,
    angemeldeter_dienst,
    dienst_anmelden,
    kopf_aus,
)
from . import _dienste as D
from . import _gedaechtnis as G
from . import _laufprofile as LP
from . import _lebendig as L
from . import _vorgaenge as V
from . import _wecker as W

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
TAKTE = ("cron", "skills", "abgleich", "karten", "wecken")  # Takte mit Grenzen (`takt_grenzen`); die Sonde läuft immer
KANAELE = ("telegram", "whatsapp", "matrix")  # Chat-Kanäle des Agenten (Brücke: kanaele im Kopf)
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
        # Kopfzeile für den Vorgangs-Dienst („Name: Wert“), dieselbe, die mcp_hub.vorgaenge für alle Plugins sendet
        self.vorgaenge_kopf = kopf_aus(str(cfg.get("vorgaenge_kopf") or os.getenv("FYOS_VORGAENGE_KOPF") or ""))
        self.vorgang_link = str(cfg.get("vorgang_link") or os.getenv("FYOS_VORGANG_LINK") or "").strip()
        self.board = str(cfg.get("board") or ("fyos" if self.vorgaenge_url else "default"))
        self.abgleich_s = max(0.0, _zahl(cfg.get("abgleich_s", 60)))
        self.auslassen = tuple(str(x) for x in (cfg.get("werkzeug_auslassen") or VORGABE_AUSLASSEN))
        self.fyos_skill_pfade = tuple(str(x).rstrip("/") + "/" for x in (cfg.get("fyos_skill_pfade") or VORGABE_SKILL_PFADE))
        self.akteur = str(cfg.get("akteur") or "openclaw")
        self.audit = bool(cfg.get("audit", True))
        self.agent = str(cfg.get("agent") or os.getenv("FYOS_AGENT") or U.AGENT_VORGABE).strip()
        wk = cfg.get("wecken") if isinstance(cfg.get("wecken"), dict) else {}
        self._wecken_cfg: dict[str, Any] = wk
        self._wecken_aktiv = bool(wk.get("aktiv", True))
        self._wecken_intervall = max(5.0, _zahl(wk.get("intervall_s", 15)) or 15.0)
        self._wecker: W.Wecker | None = None
        # Optionale Dienste (Weiche, Reranker, Mund, Ohr); fehlen sie, arbeitet alles wie ohne sie
        self._dienste = D.Dienste(cfg.get("dienste") if isinstance(cfg.get("dienste"), dict) else None,
                                  post=cfg.get("dienste_post"), get=cfg.get("dienste_get"))
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
        # Recall je Weg: Anfragen, Fehler, Treffer, Dauer (Summe und zuletzt) in Millisekunden
        self._erinnert: dict[str, dict[str, float]] = {}
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
        """Vom Server gerufen: Register für die Audit-Haken; startet den Takt, wenn ein Gateway eingetragen ist. Bei
        ``mcp_hub.vorgaenge`` meldet das Plugin den eingetragenen Vorgangs-Dienst an, auch solange die Kopplung ruht
        (ohne Gateway lesen die anderen Plugins ihn trotzdem), sonst sich selbst als Ablage (andere Plugins lesen und
        beantworten Vorgänge dann im Workboard, ohne eine Adresse zu kennen)."""
        self._registry = registry
        if self.gateway_url and (self._token or self._rpc_aufruf is not None):
            # Dringende Mitteilungen ohne offene Shell gehen über den Agenten in den Chat-Kanal des Besitzers.
            from .. import os_bruecke

            os_bruecke.kanal_anmelden(self.kanal_mitteilen)
        if self.vorgaenge_url:
            dienst_anmelden(self.vorgaenge_url, self.vorgaenge_kopf)
        elif self.modus == "ablage":
            ablage_anmelden(self)
        if self.gateway_url and self._faden is None:
            self._faden = threading.Thread(target=self._takt, name="openclaw-takt", daemon=True)
            self._faden.start()

    def shutdown(self) -> None:
        self._halt.set()
        from .. import os_bruecke

        if os_bruecke.angemeldeter_kanal() == self.kanal_mitteilen:
            os_bruecke.kanal_anmelden(None)
        if angemeldete_ablage() is self:
            ablage_anmelden(None)
        if self.vorgaenge_url and angemeldeter_dienst() == (self.vorgaenge_url, self.vorgaenge_kopf):
            dienst_anmelden(None)

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

    def kanal_mitteilen(self, text: str, kanal: str = "") -> dict[str, Any]:
        """Eine dringende Mitteilung an den Besitzer, über den Chat-Kanal, den der Agent eingerichtet hat (die Brücke
        versucht Telegram, WhatsApp, Matrix; die Methode ``fyos.kanal.mitteilen``). Fehler, wenn nichts zugestellt wurde."""
        params: dict[str, Any] = {"text": _kurz(text, 4000)}
        if kanal:
            params["kanal"] = kanal
        antwort = self.rpc("fyos.kanal.mitteilen", params)
        return antwort if isinstance(antwort, dict) else {}

    # ── Wecken: der Hub weckt den Agenten (Brücke: fyos.wecken, fyos.vorgang.senden) ─────────────

    def wecken(self, text: str, vorgang: str = "", sitzung: str = "", modus: str = "jetzt") -> dict[str, Any]:
        """Den Agenten wecken: mit ``vorgang`` in der Sitzung dieses Vorgangs, sonst in seiner Hauptsitzung."""
        params: dict[str, Any] = {"text": _kurz(text, 4000), "modus": modus if modus in ("jetzt", "naechster") else "jetzt"}
        if vorgang:
            params["vorgang"] = str(vorgang).strip()
        elif sitzung:
            params["sitzung"] = str(sitzung).strip()
        if self.agent != U.AGENT_VORGABE:
            params["agent"] = self.agent
        antwort = self.rpc("fyos.wecken", params)
        return antwort if isinstance(antwort, dict) else {}

    def vorgang_senden(self, vorgang: str, text: str, schluessel: str = "") -> dict[str, Any]:
        """Eine Nachricht in die Sitzung eines Vorgangs; der Agent antwortet dort (nichts geht an einen Chat-Kanal)."""
        params: dict[str, Any] = {"vorgang": str(vorgang).strip(), "text": _kurz(text, 4000)}
        if schluessel:
            params["schluessel"] = str(schluessel).strip()
        if self.agent != U.AGENT_VORGABE:
            params["agent"] = self.agent
        antwort = self.rpc("fyos.vorgang.senden", params)
        return antwort if isinstance(antwort, dict) else {}

    def wecker(self) -> W.Wecker:
        """Der Wecker dieses Plugins (wird beim ersten Gebrauch gebaut)."""
        with self._sperre:
            if self._wecker is None:
                wk = self._wecken_cfg
                quellen_an = wk.get("quellen") if isinstance(wk.get("quellen"), dict) else {}
                vorlauf = max(1.0, _zahl(wk.get("vorlauf_min", 10)) or 10.0)
                quellen: list[Any] = []
                if quellen_an.get("vorgaenge", True):
                    quellen.append(W.VorgangsQuelle(_vorgangsquellen.quelle))
                if quellen_an.get("termine", True):
                    quellen.append(W.TerminQuelle(_termine.quelle, vorlauf))
                if quellen_an.get("postfach", True):
                    quellen.append(W.PostfachQuelle(_postfach.quelle))
                if quellen_an.get("dokumente", True):
                    quellen.append(W.DokumentQuelle(_dokumente.quelle))
                for strom in wk.get("strome") or []:
                    if str(strom).strip():
                        quellen.append(W.StromQuelle(self._speicher, str(strom).strip()))
                self._wecker = W.Wecker(
                    quellen=list(wk.get("quellen_objekte") or quellen),
                    regeln=W.regeln_pruefen(wk.get("regeln"), (self.agent, self.akteur)),
                    schicken=lambda params: self.rpc("fyos.wecken", {**params, **({"agent": self.agent} if self.agent != U.AGENT_VORGABE else {})}),
                    speicher=self._speicher, agent=self.agent,
                    max_pro_minute=int(_zahl(wk.get("max_pro_minute", 10)) or 10),
                    max_alter_s=_zahl(wk.get("max_alter_s", 900)) or 900.0,
                    weiche=self._dienste.weiche if self._dienste.eingerichtet("weiche") else None,
                )
            return self._wecker

    def wecker_schlag(self) -> dict[str, Any]:
        """Ein Schlag des Weckers (sonst im Takt)."""
        ergebnis = self.wecker().schlag()
        w = self.wecker()
        self._lauf("wecken", "fehler" if w.letzter_fehler and ergebnis.get("wartend") else "ok", w.letzter_fehler if ergebnis.get("wartend") else "")
        return ergebnis

    def _vd(self, methode: str, pfad: str, koerper: Any = None, zeit_s: float = 8.0) -> Any:
        """Ein Aufruf beim Vorgangs-Dienst (Vertrag wie fyos-agent/plugins/fyos-freigabe-chat/board.mjs)."""
        if self._vd_aufruf is not None:
            return self._vd_aufruf(methode, pfad, koerper)
        if not self.vorgaenge_url:
            raise BrueckeFehler("FYOS_VORGAENGE_URL nicht gesetzt")
        daten = json.dumps(koerper).encode() if koerper is not None else None
        req = urllib.request.Request(self.vorgaenge_url + pfad, data=daten, method=methode,
                                     headers={"Content-Type": "application/json", "Accept": "application/json",
                                              **self.vorgaenge_kopf})
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

    # ── Gedächtnis: ein Recall-Weg über das Gedächtnis des Agenten und die Dokumente des Hubs ─────────

    def erinnern(self, frage: str, limit: int = 8) -> dict[str, Any]:
        """Die Frage an das Gedächtnis des Agenten (``memory.search``) und die Dokumentenquelle, gemischt und gemessen."""
        wege: dict[str, Callable[[str, int], Any]] = {}
        if self.modus != "aus":
            def gedaechtnis(f: str, n: int) -> Any:
                params: dict[str, Any] = {"query": f, "maxResults": n}
                if self.agent != U.AGENT_VORGABE:
                    params["agentId"] = self.agent
                return self.rpc("memory.search", params)

            wege["gedaechtnis"] = gedaechtnis
        try:
            dok = _dokumente.quelle()
            if dok.eingerichtet:
                wege["dokumente"] = lambda f, n: dok.suchen(f, n)
        except Exception:  # noqa: BLE001 -- ohne Dokumentenquelle bleibt es beim Gedächtnis
            pass
        ergebnis = G.erinnern(frage, limit, wege)
        if self._dienste.eingerichtet("rerank") and ergebnis["treffer"]:
            # Reranker (optional): ordnet die gemischten Treffer nach Bedeutung neu; bei Ausfall bleibt das Rangmischen
            ergebnis["treffer"], m = self._dienste.rerank(ergebnis["frage"], ergebnis["treffer"])
            ergebnis["messung"]["rerank"] = {**m, "anzahl": len(ergebnis["treffer"])}
            if m["ok"]:
                ergebnis["satz"] += " Neu geordnet durch den Reranker."
        with self._sperre:
            for weg, m in ergebnis["messung"].items():
                if weg == "gesamt_ms" or m.get("grund") == "nicht eingerichtet":
                    continue
                z = self._erinnert.setdefault(weg, {"anfragen": 0, "fehler": 0, "treffer": 0, "ms_summe": 0, "ms_zuletzt": 0})
                z["anfragen"] += 1
                z["fehler"] += 0 if m["ok"] else 1
                z["treffer"] += m["anzahl"]
                z["ms_summe"] += m["ms"]
                z["ms_zuletzt"] = m["ms"]
        return ergebnis

    def gedaechtnis(self, frisch: bool = False) -> dict[str, Any]:
        """Stand des Gedächtnisses: Anbieter (Vektor oder Text), Dreaming, und was ``erinnern`` bisher gemessen hat."""
        stand: dict[str, Any] = {}
        fehler = None
        if self.modus != "aus":
            try:
                stand = G.stand_aus(self._zwischen("gedaechtnis", 120.0, lambda: self.rpc("doctor.memory.status", {}) or {}, frisch))
            except Exception as exc:  # noqa: BLE001
                fehler = _kurz(f"{type(exc).__name__}: {exc}", 200)
        with self._sperre:
            gemessen = {w: {**z, "ms_mittel": round(z["ms_summe"] / z["anfragen"]) if z["anfragen"] else None}
                        for w, z in self._erinnert.items()}
        traum = stand.get("dreaming") or {}
        satz = ("Gedächtnis nicht lesbar." if not stand else
                f"Anbieter {stand.get('anbieter') or '?'}; Dreaming {'an' if traum.get('an') else 'aus'}, "
                f"{traum.get('kurzzeit', 0)} Kurzzeiteinträge, {traum.get('uebernommen', 0)} übernommen.")
        return {"satz": satz, **stand, "gemessen": gemessen, "fehler": fehler}

    # ── Optionale Dienste: Weiche, Reranker, Mund, Ohr ─────────────────────────────────────────────

    def dienste(self, probe: bool = True, frisch: bool = False) -> dict[str, Any]:
        """Welche optionalen Dienste eingerichtet und erreichbar sind, was sie bisher taten, und was das Gateway zu
        Sprachausgabe (``tts.status``) und Weckwort-Weiterleitung (``voicewake.routing.get``) sagt."""
        dienste = self._dienste.pruefen(probe)
        gateway: dict[str, Any] = {}
        fehler: list[str] = []
        if self.modus != "aus":
            for name, methode in (("mund", "tts.status"), ("weckwort", "voicewake.routing.get")):
                try:
                    gateway[name] = self._zwischen(f"dienst:{methode}", 60.0, lambda m=methode: self.rpc(m, {}) or {}, frisch)
                except Exception as exc:  # noqa: BLE001
                    fehler.append(_kurz(f"{methode}: {type(exc).__name__}: {exc}", 160))
        tts = gateway.get("mund") or {}
        weg = gateway.get("weckwort") or {}
        gateway_mund = {"an": bool(tts.get("enabled")), "anbieter": tts.get("provider") or None,
                        "eingerichtet": [p.get("id") for p in (tts.get("providerStates") or [])
                                         if isinstance(p, dict) and p.get("configured")]} if tts else None
        routen = ((weg.get("config") or {}).get("routes") or []) if isinstance(weg, dict) else []
        gateway_weckwort = {"routen": len(routen)} if weg else None
        da = [n for n, d in dienste.items() if d["eingerichtet"]]
        weg_ab = [n for n, d in dienste.items() if d["erreichbar"] is False]
        satz = ("Keine optionalen Dienste eingerichtet; alles arbeitet ohne sie." if not da else
                f"Eingerichtet: {', '.join(da)}" + (f"; nicht erreichbar: {', '.join(weg_ab)}." if weg_ab else "; alle erreichbar."))
        return {"satz": satz, "dienste": dienste, "weiche_urteile": dict(self._dienste.weiche_urteile),
                "gateway": {"mund": gateway_mund, "weckwort": gateway_weckwort}, "fehler": fehler}

    # ── Lebendigkeit: Herzschlag, Sitzungen, Fortschrittskarten je Vorgang ───────────────────────

    def lebt(self, vorgang: str = "", frisch: bool = False) -> dict[str, Any]:
        """„Lebt der Agent?“: Urteil (gestoert, laeuft, bereit) mit Gründen, letzter Herzschlag, Vorgangssitzungen samt
        Fortschrittskarte. Mit ``vorgang`` nur die Sitzung dieses Vorgangs."""
        vorgang = str(vorgang or "").strip().upper()
        if vorgang and not U.vorgang_gueltig(vorgang):
            raise ValueError(f"{vorgang!r} ist keine Vorgangsnummer")
        if self.modus == "aus":
            return {"satz": "Kopplung aus (FYOS_AGENT_URL fehlt).", "zustand": "aus", "gruende": []}
        s = self.sonde(frisch)
        fehler: list[str] = []
        herz = None
        try:
            herz = L.herzschlag_aus(self._zwischen("herzschlag", 15.0, lambda: self.rpc("last-heartbeat", {}), frisch))
        except Exception as exc:  # noqa: BLE001
            fehler.append(_kurz(f"Herzschlag: {type(exc).__name__}: {exc}", 160))
        sitzungen: list[dict[str, Any]] = []
        try:
            roh = self._zwischen("sitzungen", 15.0, lambda: self.rpc("sessions.list", {"limit": 100}) or {}, frisch)
            sitzungen = [x for x in (L.sitzung_aus(r) for r in (roh.get("sessions") or [])) if x]
        except Exception as exc:  # noqa: BLE001
            fehler.append(_kurz(f"Sitzungen: {type(exc).__name__}: {exc}", 160))
        zustand, gruende = L.urteil(s.get("bereit") if s.get("gesetzt") else None, sitzungen)
        je_vorgang = [x for x in sitzungen if x["vorgang"] and (not vorgang or x["vorgang"] == vorgang)]
        je_vorgang.sort(key=lambda x: -(x["aktualisiert_ms"] or 0))
        for x in je_vorgang[:10]:
            try:
                x["karte"] = L.karte_aus(self._zwischen(f"karte:{x['schluessel']}", 15.0, lambda k=x["schluessel"]: self.rpc(
                    "progressCard.get", {"sessionKey": k}), frisch))
            except Exception as exc:  # noqa: BLE001
                x["karte"] = None
                fehler.append(_kurz(f"Karte {x['vorgang']}: {type(exc).__name__}: {exc}", 160))
        wz = self._wecker.zustand(1)["zaehler"] if self._wecker is not None else None
        satz = {"gestoert": "Agent gestört: " + "; ".join(gruende), "laeuft": "Agent läuft gerade.",
                "bereit": "Agent bereit, kein Lauf aktiv."}[zustand]
        if vorgang and not je_vorgang:
            satz += f" Keine Sitzung zu {vorgang}."
        return {"satz": satz, "zustand": zustand, "gruende": gruende, "herzschlag": herz,
                "sitzungen_gesamt": len(sitzungen), "aktiv": sum(1 for x in sitzungen if x["aktiv"]),
                "vorgaenge": je_vorgang[:10], "wecker": ({"geweckt": wz["geweckt"], "fehler": wz["fehler"]} if wz else None),
                "fehler": fehler}

    def cron_profile(self, frisch: bool = False) -> dict[str, Any]:
        """Cron-Aufträge nach Laufprofil geordnet (mit Nutzlast gelesen, ausgegeben werden nur Namen und Zählungen)."""
        def holen() -> dict[str, Any]:
            antwort = self.rpc("cron.list", {"includeDisabled": True, "limit": 200}) or {}
            return LP.pruefen([j for j in (antwort.get("jobs") or []) if isinstance(j, dict)])

        return self._zwischen("cron_profile", 120.0, holen, frisch)

    def profile(self, frisch: bool = False) -> dict[str, Any]:
        """Die Laufprofile samt Werkzeuglisten und der Stand der Aufträge des Agenten gegen sie."""
        stand: dict[str, Any] = {}
        fehler = None
        if self.modus != "aus":
            try:
                stand = self.cron_profile(frisch)
            except Exception as exc:  # noqa: BLE001
                fehler = _kurz(f"{type(exc).__name__}: {exc}", 200)
        offen = stand.get("ohne_profil") or []
        satz = ("Drei Laufprofile (lesen, reflexion, melden). "
                + (f"{len(offen)} laufende Aufträge ohne Profil: {', '.join(offen[:5])}." if offen
                   else ("Alle Aufträge folgen einem Profil oder laufen verwaltet." if stand else "Aufträge nicht lesbar.")))
        return {"satz": satz, "profile": LP.profile(), "auftraege": stand.get("auftraege") or [],
                "je_profil": stand.get("je_profil") or {}, "ohne_profil": offen, "fehler": fehler}

    def agent_skills(self, frisch: bool = False) -> list[dict[str, Any]]:
        def holen() -> list[dict[str, Any]]:
            antwort = self.rpc("skills.status", {}) or {}
            return [s for s in (antwort.get("skills") or []) if isinstance(s, dict)]

        return self._zwischen("skills", 300.0, holen, frisch)

    def _skill_text(self, name: str) -> str:
        antwort = self.rpc("fyos.skill.lesen", {"name": name}) or {}
        return str(antwort.get("text") or "")

    # ── Ereignisse der Brücke ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _kanaele(roh: Any) -> dict[str, dict[str, bool]]:
        """Chat-Kanäle des Agenten aus dem Kopf der Brücke: je bekanntem Kanal an/ziel/bereit, nur Wahrheitswerte."""
        if not isinstance(roh, dict):
            return {}
        aus: dict[str, dict[str, bool]] = {}
        for name in KANAELE:
            e = roh.get(name)
            if isinstance(e, dict):
                an, ziel = bool(e.get("an")), bool(e.get("ziel"))
                aus[name] = {"an": an, "ziel": ziel, "bereit": an and ziel}
        return aus

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
                "kanaele": self._kanaele(b.get("kanaele")) or self._bruecke.get("kanaele") or {},
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
        eintrag: dict[str, Any] = {"t": int(zeit_ms), "a": art, "g": agent, "d": int(dauer), "k": _wort(roh.get("kanal"), 30),
                                   "v": _wort(roh.get("vorgang"), 24)}
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

    def _antwort(self, holen: Callable[[], Any], status: int = 200) -> JSONResponse:
        """Ergebnis einer Daten-Methode als HTTP-Antwort; ihre Fehler als Status (404, 409, 400, sonst 409/502)."""
        try:
            return JSONResponse(holen(), status_code=status)
        except VorgangFehlt as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except VorgangKonflikt as exc:
            return JSONResponse({"error": str(exc), "ticket": exc.vorgang}, status_code=409)
        except json.JSONDecodeError as exc:  # kaputte Antwort der Brücke, kein Eingabefehler
            return self._gescheitert(exc)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return self._gescheitert(exc)

    def _tickets_liste(self, status: str, grenze: int) -> JSONResponse:
        return self._antwort(lambda: {"tickets": self.ablage_liste(status, grenze), "quelle": "workboard",
                                      "board": self.board})

    def _ticket_holen(self, vid: str) -> JSONResponse:
        def holen() -> dict[str, Any]:
            vorgang = self.ablage_holen(vid)
            if vorgang is None:
                raise VorgangFehlt(f"kein Vorgang {vid}")
            return vorgang
        return self._antwort(holen)

    def _ticket_anlegen(self, koerper: Any) -> JSONResponse:
        return self._antwort(lambda: self.ablage_anlegen(koerper), 201)

    def _ticket_kommentieren(self, vid: str, koerper: Any) -> JSONResponse:
        return self._antwort(lambda: self.ablage_kommentieren(vid, koerper))

    def _ticket_aendern(self, vid: str, koerper: Any) -> JSONResponse:
        return self._antwort(lambda: self.ablage_aendern(vid, koerper))

    # Daten-Methoden der Ablage (auch prozessintern für ``mcp_hub.vorgaenge``)

    def ablage_liste(self, status: str = "", grenze: int = 50) -> list[dict[str, Any]]:
        tickets = [V.vorgang_aus_karte(k) for k in self.karten()]
        if status:
            tickets = [t for t in tickets if t["status"] == status]
        tickets.sort(key=lambda t: -_zahl(t.get("updated_at")))
        return tickets[:grenze]

    def ablage_holen(self, vid: str) -> dict[str, Any] | None:
        karte = V.karte_zur_id(self.karten(), vid)
        return V.vorgang_aus_karte(karte) if karte is not None else None

    def ablage_verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        karte = V.karte_zur_id(self.karten(), vid)
        if karte is None:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        return V.verlauf_aus_karte(karte, grenze)

    def ablage_anlegen(self, koerper: Any) -> dict[str, Any]:
        if not isinstance(koerper, dict) or not str(koerper.get("title") or "").strip():
            raise ValueError("title fehlt")
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
        antwort = self.rpc("workboard.cards.create", params) or {}
        with self._sperre:
            self._ablage.pop("karten", None)
        karte = antwort.get("card") if isinstance(antwort, dict) else None
        return V.vorgang_aus_karte(karte or {})

    def ablage_kommentieren(self, vid: str, koerper: Any) -> dict[str, Any]:
        text = str((koerper or {}).get("text") or "").strip() if isinstance(koerper, dict) else ""
        if not text:
            raise ValueError("text fehlt")
        akteur = _wort((koerper or {}).get("actor"), 40)
        karte = V.karte_zur_id(self.karten(), vid)
        if karte is None:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        self.rpc("workboard.cards.comment", {"id": karte["id"], "body": V._kurz(f"{akteur}: {text}" if akteur else text, 2000)})
        with self._sperre:
            self._ablage.pop("karten", None)
        return {"ok": True, "id": vid}

    def ablage_aendern(self, vid: str, koerper: Any) -> dict[str, Any]:
        if not isinstance(koerper, dict):
            raise ValueError("Objekt erwartet")
        karte = V.karte_zur_id(self.karten(frisch=True), vid)
        if karte is None:
            raise VorgangFehlt(f"kein Vorgang {vid}")
        jetzt = V.vorgang_aus_karte(karte)
        erwartet = str(koerper.get("expected_status") or "")
        if erwartet and jetzt["status"] != erwartet:
            raise VorgangKonflikt("status_conflict", jetzt)
        ziel = str(koerper.get("status") or "")
        if ziel and ziel not in V.KARTE_FUER:
            raise ValueError(f"unbekannter Status {ziel}")
        if ziel:
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
        with self._sperre:
            self._ablage.pop("karten", None)
        return V.vorgang_aus_karte(karte)

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
        if self._wecken_aktiv and faellig("wecken", max(1.0, self._wecken_intervall - 2.0)):
            try:
                self._waechter.ausfuehren("wecken", self.wecker_schlag)
            except Exception:  # noqa: BLE001 — der Wecker wirft nie; das Laufprotokoll des Wächters nennt den Rest
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
            if self._wecken_aktiv:
                reihen.append(("wecken", "Agenten bei Vorgängen, Terminen und Eingang wecken",
                               f"alle {self._wecken_intervall:g} s"))
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
        with self._sperre:
            erinnert = {w: dict(z) for w, z in self._erinnert.items()}
        for weg, z in erinnert.items():
            proben.append({"name": "fyos_openclaw_erinnern_total", "wert": z["anfragen"], "typ": "counter",
                           "labels": {"weg": weg, "ergebnis": "ok"}, "hilfe": "Anfragen an den Recall-Weg (erinnern)"})
            proben.append({"name": "fyos_openclaw_erinnern_total", "wert": z["fehler"], "typ": "counter",
                           "labels": {"weg": weg, "ergebnis": "fehler"}, "hilfe": "Anfragen an den Recall-Weg (erinnern)"})
            proben.append({"name": "fyos_openclaw_erinnern_treffer_total", "wert": z["treffer"], "typ": "counter",
                           "labels": {"weg": weg}, "hilfe": "Treffer des Recall-Wegs"})
            proben.append({"name": "fyos_openclaw_erinnern_dauer_ms", "wert": z["ms_zuletzt"], "labels": {"weg": weg},
                           "hilfe": "Dauer der letzten Anfrage an den Recall-Weg in Millisekunden"})
        if self._wecker is not None:
            wz = self._wecker.zustand(1)
            for ergebnis in ("geweckt", "fehler", "verworfen"):
                proben.append({"name": "fyos_openclaw_wecken_total", "wert": wz["zaehler"][ergebnis], "typ": "counter",
                               "labels": {"ergebnis": ergebnis}, "hilfe": "Weckrufe des Hubs an den Agenten"})
            proben.append({"name": "fyos_openclaw_wecken_wartend", "wert": wz["wartend"],
                           "hilfe": "Ereignisse, die auf einen Weckruf warten (Flussschutz oder Fehler)"})
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
            "bruecke": {**{k: v for k, v in b.items() if k not in ("plugins", "kanaele")}, "alter_s": alter, "plugins": len(b.get("plugins") or [])},
            "rpc": rpc,
            "token": bool(self._token),
            "kanaele": dict(b.get("kanaele") or {}),
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
                "vorgang": f.get("v") or None,
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
            ToolDescriptor(
                name="wecken",
                title="OpenClaw — Agent wecken",
                description=(
                    "Den Agenten jetzt (oder zum nächsten Herzschlag) wecken: er bekommt `text` als Hinweis und läuft. Mit "
                    "`vorgang` (z. B. INC-1234) landet der Hinweis in der Sitzung dieses Vorgangs "
                    "(agent:<id>:vorgang:<ID>), sonst in der Hauptsitzung. Der Text trägt Namen und Nummern, keine Inhalte."
                ),
                input_schema={"type": "object", "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "vorgang": {"type": "string"},
                    "modus": {"type": "string", "enum": ["jetzt", "naechster"]},
                }, "required": ["text"], "additionalProperties": False},
                tags=["openclaw", "agent", "write"],
            ),
            ToolDescriptor(
                name="vorgang_senden",
                title="OpenClaw — Nachricht in die Vorgangssitzung",
                description=(
                    "Eine Nachricht in die Sitzung eines Vorgangs schreiben; der Agent antwortet dort, nichts geht an einen "
                    "Chat-Kanal. `schluessel` macht die Zustellung wiederholbar (derselbe Schlüssel läuft nur einmal)."
                ),
                input_schema={"type": "object", "properties": {
                    "vorgang": {"type": "string"},
                    "text": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "schluessel": {"type": "string"},
                }, "required": ["vorgang", "text"], "additionalProperties": False},
                tags=["openclaw", "agent", "write"],
            ),
            ToolDescriptor(
                name="lebt",
                title="OpenClaw — Lebt der Agent?",
                description=(
                    "Urteil (bereit, läuft, gestört) mit Gründen, das Ergebnis des letzten Herzschlags und die Sitzungen "
                    "der Vorgänge samt Fortschrittskarte (Schritte, aktueller Schritt, Notiz) des Agenten. Mit `vorgang` "
                    "(z. B. INC-1234) nur die Sitzung dieses Vorgangs. Gestört heißt: das Gateway ist nicht bereit oder der "
                    "jüngste beendete Lauf scheiterte (oft: das Modell antwortet nicht)."
                ),
                input_schema={"type": "object", "properties": {
                    "vorgang": {"type": "string"}, "frisch": {"type": "boolean", "default": False},
                }, "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="erinnern",
                title="OpenClaw — Erinnern",
                description=(
                    "Ein Recall-Weg: die Frage an das Gedächtnis des Agenten (Notizen, Gesprächsauszüge, Traumbericht; "
                    "Vektorsuche, wenn ein Embedding-Dienst eingerichtet ist, sonst Textsuche) und an die Dokumente des "
                    "Hubs, gemischt (Reciprocal Rank Fusion). Je Weg ein Messwert (Dauer, Anzahl, Modus); ein ausfallender "
                    "Weg ist ein Vermerk. `limit` 1–20, Vorgabe 8."
                ),
                input_schema={"type": "object", "properties": {
                    "frage": {"type": "string", "minLength": 1, "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                }, "required": ["frage"], "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="gedaechtnis",
                title="OpenClaw — Gedächtnis",
                description=(
                    "Stand des Gedächtnisses des Agenten: Anbieter (Vektor oder Text), Dreaming mit Phasen, nächstem Lauf "
                    "und Zahlen (ohne die Auszüge), dazu was `erinnern` bisher je Weg gemessen hat."
                ),
                input_schema={"type": "object", "properties": {"frisch": {"type": "boolean", "default": False}},
                              "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="dienste",
                title="OpenClaw — Optionale Dienste",
                description=(
                    "Weiche (entscheidet vor dem Wecken), Reranker (ordnet `erinnern` neu), Mund und Ohr: je Dienst "
                    "eingerichtet, erreichbar (kurze Probe ohne Nutzdaten, `probe` false lässt sie aus), Zähler; dazu "
                    "was das Gateway zu Sprachausgabe und Weckwort-Weiterleitung meldet. Fehlt ein Dienst, arbeitet alles "
                    "wie ohne ihn."
                ),
                input_schema={"type": "object", "properties": {
                    "probe": {"type": "boolean", "default": True}, "frisch": {"type": "boolean", "default": False},
                }, "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="profile",
                title="OpenClaw — Laufprofile",
                description=(
                    "Welche Werkzeuge ein isolierter Lauf des Agenten bekommt: die Profile lesen, reflexion, melden mit "
                    "Zweck und Werkzeugliste, und welche Cron-Aufträge des Agenten einem Profil folgen, offen (alle "
                    "Werkzeuge), ohne Werkzeuge oder eigen sind. Trägt Namen, nie Nachrichten."
                ),
                input_schema={"type": "object", "properties": {"frisch": {"type": "boolean", "default": False}},
                              "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="auftrag_vorlage",
                title="OpenClaw — Auftrag mit Profil vorbereiten",
                description=(
                    "Baut den Aufruf für einen Cron-Auftrag mit einem Laufprofil (Befehl `openclaw cron add …` und "
                    "Nutzlast), legt aber nichts an. `plan`: genau eines von cron (Ausdruck), alle (z. B. 6h), um "
                    "(Zeitpunkt oder Dauer), optional zeitzone. `sitzung` bindet den Lauf an eine feste Sitzung."
                ),
                input_schema={"type": "object", "properties": {
                    "profil": {"type": "string", "enum": list(LP.REIHENFOLGE)},
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "text": {"type": "string", "minLength": 1, "maxLength": 8000},
                    "plan": {"type": "object", "properties": {
                        "cron": {"type": "string"}, "alle": {"type": "string"}, "um": {"type": "string"},
                        "zeitzone": {"type": "string"}}, "additionalProperties": False},
                    "sitzung": {"type": "string"},
                }, "required": ["profil", "name", "text", "plan"], "additionalProperties": False},
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="ereignisse",
                title="OpenClaw — Wecker",
                description=(
                    "Der Wecker des Hubs: welche Quellen er liest, welche Regeln gelten, Zähler (geweckt, Fehler, "
                    "verworfen), was wartet und die letzten Weckrufe mit Ziel (Sitzung) und Ergebnis. `limit` 1–100."
                ),
                input_schema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                              "additionalProperties": False},
                tags=_TAGS_LESEN,
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
        if method == "wecken":
            return self.wecken(str(args.get("text") or ""), str(args.get("vorgang") or ""), "", str(args.get("modus") or "jetzt"))
        if method == "vorgang_senden":
            return self.vorgang_senden(str(args.get("vorgang") or ""), str(args.get("text") or ""), str(args.get("schluessel") or ""))
        if method == "lebt":
            return self.lebt(str(args.get("vorgang") or ""), bool(args.get("frisch")))
        if method == "erinnern":
            return self.erinnern(str(args.get("frage") or ""), int(args.get("limit") or 8))
        if method == "gedaechtnis":
            return self.gedaechtnis(bool(args.get("frisch")))
        if method == "dienste":
            return self.dienste(bool(args.get("probe", True)), bool(args.get("frisch")))
        if method == "profile":
            return self.profile(bool(args.get("frisch")))
        if method == "auftrag_vorlage":
            try:
                return LP.vorlage(str(args.get("profil") or ""), str(args.get("name") or ""), str(args.get("text") or ""),
                                  args.get("plan") or {}, self.agent if self.agent != U.AGENT_VORGABE else "",
                                  str(args.get("sitzung") or ""))
            except LP.ProfilFehler as exc:
                raise ValueError(str(exc)) from exc
        if method == "ereignisse":
            if not self._wecken_aktiv:
                return {"aktiv": False, "satz": "Der Wecker ist ausgeschaltet (wecken.aktiv)."}
            z = self.wecker().zustand(int(args.get("limit") or 20))
            return {"aktiv": True, "satz": f"Wecker: {z['zaehler']['geweckt']} Weckrufe, {z['zaehler']['fehler']} Fehler, "
                                           f"{z['wartend']} warten.", **z}
        raise ValueError(f"openclaw hat kein Werkzeug {method!r}")
