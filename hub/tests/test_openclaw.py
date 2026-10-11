"""Kopplung an OpenClaw (Plugin ``openclaw``): Ereignisse, Ablage, Spiegel, Beiträge — ohne Netz.

Das Workboard und der Vorgangs-Dienst sind kleine Nachbauten im Speicher; sie folgen den Formen aus
docs/KOPPLUNG-OPENCLAW.md (Karten mit ``updatedAt``, ``cards.move``/``update``/``comment``, Idempotenzschlüssel).
"""

from __future__ import annotations

import itertools
import json
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub import kv
from mcp_hub import metriken
from mcp_hub.plugins import _vorgaenge as V
from mcp_hub.plugins.openclaw import OpenClawPlugin, signatur
from mcp_hub.plugins.skills import SkillsPlugin
from mcp_hub.takt import GrenzenFehler

# ── Nachbauten ──────────────────────────────────────────────────────────────────────────────────


class Werkbrett:
    """Workboard im Speicher: genug von workboard.* für die Kopplung."""

    def __init__(self) -> None:
        self.karten: dict[str, dict[str, Any]] = {}
        self.boards: dict[str, dict[str, Any]] = {"default": {"id": "default"}}
        self.uhr = itertools.count(1000)
        self.aufrufe: list[tuple[str, dict[str, Any]]] = []
        self.skills: list[dict[str, Any]] = []
        self.cron: list[dict[str, Any]] = []
        self.skill_texte: dict[str, str] = {}

    def __call__(self, methode: str, params: dict[str, Any]) -> Any:
        self.aufrufe.append((methode, params))
        if methode == "workboard.boards.upsert":
            self.boards[params["id"]] = dict(params)
            return {"board": self.boards[params["id"]]}
        if methode == "workboard.cards.list":
            board = params.get("boardId") or "default"
            return {"cards": [json.loads(json.dumps(k)) for k in self.karten.values()
                              if k["metadata"]["automation"]["boardId"] == board and not k["metadata"].get("archivedAt")]}
        if methode == "workboard.cards.create":
            for k in self.karten.values():
                auto = k["metadata"]["automation"]
                if params.get("idempotencyKey") and auto.get("idempotencyKey") == params["idempotencyKey"]:
                    return {"card": k}
            kid = str(uuid.uuid4())
            k = {"id": kid, "title": params["title"], "notes": params.get("notes", ""), "status": params.get("status", "todo"),
                 "priority": params.get("priority", "normal"), "labels": list(params.get("labels") or []),
                 "sourceUrl": params.get("sourceUrl"), "createdAt": next(self.uhr), "updatedAt": next(self.uhr),
                 "metadata": {"automation": {"boardId": params.get("boardId") or "default",
                                             "idempotencyKey": params.get("idempotencyKey")}, "comments": []}}
            self.karten[kid] = k
            return {"card": k}
        k = self.karten.get(params.get("id", ""))
        if methode.startswith("workboard.cards.") and k is None:
            raise RuntimeError("card not found")
        if methode == "workboard.cards.move":
            if params.get("expectedUpdatedAt") is not None and params["expectedUpdatedAt"] != k["updatedAt"]:
                raise RuntimeError("workboard_conflict")
            k["status"] = params["status"]
            k["updatedAt"] = next(self.uhr)
            return {"card": k}
        if methode == "workboard.cards.update":
            k.update(params["patch"])
            k["updatedAt"] = next(self.uhr)
            return {"card": k}
        if methode == "workboard.cards.comment":
            k["metadata"]["comments"].append({"id": str(uuid.uuid4()), "body": params["body"], "createdAt": next(self.uhr)})
            k["updatedAt"] = next(self.uhr)
            return {"card": k}
        if methode == "workboard.cards.archive":
            k["metadata"]["archivedAt"] = next(self.uhr)
            return {"card": k}
        if methode == "skills.status":
            return {"skills": self.skills}
        if methode == "cron.list":
            return {"jobs": self.cron}
        if methode == "fyos.skill.lesen":
            return {"text": self.skill_texte.get(params["name"], "")}
        if methode == "usage.cost":
            return {"totals": {"totalTokens": 1234}}
        raise RuntimeError(f"unbekannte Methode {methode}")

    # wie ein Mensch in OpenClaw
    def verschiebe(self, kid: str, status: str) -> None:
        self.karten[kid]["status"] = status
        self.karten[kid]["updatedAt"] = next(self.uhr)

    def kommentiere(self, kid: str, text: str) -> None:
        self.karten[kid]["metadata"]["comments"].append({"id": str(uuid.uuid4()), "body": text})
        self.karten[kid]["updatedAt"] = next(self.uhr)

    def zur_vorgang(self, vid: str) -> dict[str, Any]:
        return next(k for k in self.karten.values() if f"vorgang:{vid}" in k["labels"])


class Vorgangsdienst:
    """Vorgangs-Dienst im Speicher (Vertrag aus board.mjs plus GET /tickets/{id})."""

    def __init__(self, tickets: list[dict[str, Any]]) -> None:
        self.tickets = {t["id"]: dict(t) for t in tickets}
        self.kommentare: list[tuple[str, dict[str, Any]]] = []
        self.patches: list[tuple[str, dict[str, Any]]] = []
        self.kaputt = False

    def __call__(self, methode: str, pfad: str, koerper: Any) -> Any:
        if methode == "GET" and pfad.startswith("/tickets?"):
            status = pfad.split("status=")[1].split("&")[0]
            return {"tickets": [t for t in self.tickets.values() if t["status"] == status]}
        teile = pfad.split("/")
        vid = teile[2]
        if methode == "GET":
            if self.kaputt:
                raise RuntimeError("Dienst wackelt")
            if vid not in self.tickets:
                fehler = RuntimeError("HTTP 404")
                fehler.status = 404  # type: ignore[attr-defined]
                raise fehler
            return self.tickets[vid]
        if methode == "POST" and pfad.endswith("/comments"):
            self.kommentare.append((vid, koerper))
            return {"ok": True}
        if methode == "PATCH":
            t = self.tickets[vid]
            if koerper.get("expected_status") and koerper["expected_status"] != t["status"]:
                raise RuntimeError("409 status_conflict")
            self.patches.append((vid, koerper))
            t["status"] = koerper["status"]
            return t
        raise RuntimeError(f"unerwartet {methode} {pfad}")


def _sonde(lebt: bool = True, bereit: bool = True):
    def holen(url: str):
        if not lebt:
            raise OSError("verbindung abgelehnt")
        if url.endswith("/healthz"):
            return 200, {"ok": True, "version": "2026.9.7", "uptimeMs": 5000}
        return (200, {"ok": True}) if bereit else (503, {"ok": False, "failing": ["state-database"]})
    return holen


def _plugin(**cfg: Any) -> OpenClawPlugin:
    basis = {"gateway_url": "http://agent:18789", "token": "geheim", "http_get": _sonde(),
             "kv_fabrik": kv.SpeicherKv, "rpc_aufruf": Werkbrett()}
    basis.update(cfg)
    return OpenClawPlugin(config=basis)


class _Registry:
    def __init__(self, *plugins: Any) -> None:
        self.plugins = {p.name: p for p in plugins}
        self.tools: dict[str, Any] = {}
        self.on_call_hooks: list[Any] = []


def _app(plugin: OpenClawPlugin) -> TestClient:
    return TestClient(Starlette(routes=plugin.routen()))


# ── aus ─────────────────────────────────────────────────────────────────────────────────────────


def test_ohne_gateway_ist_das_plugin_aus(monkeypatch):
    monkeypatch.delenv("FYOS_AGENT_URL", raising=False)
    monkeypatch.delenv("FYOS_VORGAENGE_URL", raising=False)
    p = OpenClawPlugin()
    assert p.modus == "aus"
    assert p.health()["status"] == "aus"
    assert [r.path for r in p.routen()] == ["/hub/openclaw/ereignisse", "/hub/openclaw/zustand"]
    assert "aus" in p.call("zustand", {})["satz"]
    assert p.call("abgleichen", {})["schritte"] == 0
    assert p.zeitplan() == [] and p.skills_beitrag() == []


def test_die_eigene_ablage_ist_kein_vorgangs_dienst():
    p = _plugin(vorgaenge_url="http://hub:8080/hub/vorgaenge/")
    assert p.modus == "ablage" and p.board == "default"
    assert _plugin(vorgaenge_url="http://vorgaenge:8080/api").modus == "spiegel"


# ── Ereignisse ──────────────────────────────────────────────────────────────────────────────────


def test_werkzeugaufrufe_gehen_durch_die_audit_haken_ohne_inhalte():
    p = _plugin()
    reg = _Registry(p)
    gesehen: list[Any] = []
    reg.on_call_hooks.append(gesehen.append)
    p._registry = reg
    jetzt = int(time.time() * 1000)
    n = p.annehmen({"bruecke": {"version": "0.1.0", "plugins": [{"id": "workboard", "an": True}]}, "ereignisse": [
        {"art": "werkzeug", "zeit": jetzt, "werkzeug": "exec", "ok": False, "dauer_ms": 12, "agent": "fy",
         "sitzung": "ab12cd34ef56", "fehler": "Bearer abcdefghijklmnopqrstuvwxyz0123456789 abgelehnt"},
        {"art": "werkzeug", "zeit": jetzt, "werkzeug": "hub__hub__call_tool", "ok": True},
        {"art": "werkzeug", "zeit": jetzt, "werkzeug": "", "ok": True},
        {"art": "erfunden"},
        "kein objekt",
    ]})
    assert n == 1
    (ev,) = gesehen
    assert ev.tool_name == "openclaw-agent.exec" and ev.plugin_name == "openclaw-agent"
    assert ev.caller == "agent:fy" and ev.arguments == "{}" and ev.result_status == "tool_failed"
    assert ev.session_id == "ab12cd34ef56" and ev.art == "bewusst"
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in (ev.error or "")
    z = p.zustand()
    assert z["zaehler"]["ausgelassen"] == 1 and z["bruecke"]["version"] == "0.1.0"


def test_aktivitaet_und_nutzung_aus_den_ereignissen():
    p = _plugin()
    jetzt = int(time.time() * 1000)
    p.annehmen({"ereignisse": [
        {"art": "sitzung", "zeit": jetzt, "phase": "beginn", "agent": "fy", "sitzung": "s1"},
        {"art": "modell", "zeit": jetzt, "anbieter": "modell", "modell": "lokal-gross", "ergebnis": "completed", "dauer_ms": 900},
        {"art": "werkzeug", "zeit": jetzt, "werkzeug": "read", "ok": True},
        {"art": "werkzeug", "zeit": jetzt, "werkzeug": "read", "ok": True},
        {"art": "lauf", "zeit": jetzt, "ok": True, "dauer_ms": 5000, "agent": "fy"},
        {"art": "cron", "zeit": jetzt, "aktion": "finished", "job": "j1", "name": "Morgenbrief", "status": "error",
         "fehler": "Zeitlimit"},
        {"art": "hinweis", "zeit": jetzt, "stufe": "warnung", "text": "Plugin x lädt nicht"},
    ]})
    akt = p.call("aktivitaet", {"limit": 10})
    assert [e["art"] for e in akt["eintraege"]] == ["hinweis", "cron", "lauf", "werkzeug", "werkzeug", "modell", "sitzung"]
    assert akt["eintraege"][1]["name"] == "Morgenbrief" and akt["eintraege"][1]["hinweis"] == "Zeitlimit"
    assert [e["art"] for e in p.call("aktivitaet", {"art": "werkzeug"})["eintraege"]] == ["werkzeug", "werkzeug"]
    nutz = p.call("nutzung", {"tage": 2})
    assert nutz["summe"]["werkzeuge"] == 2 and nutz["summe"]["modellaufrufe"] == 1 and nutz["summe"]["sitzungen"] == 1
    assert nutz["summe"]["cron_fehler"] == 1
    assert nutz["werkzeuge"] == [{"werkzeug": "read", "aufrufe": 2}] and nutz["modelle"][0]["modell"] == "modell/lokal-gross"
    assert nutz["laut_openclaw"] == {"totals": {"totalTokens": 1234}}


def test_lieferung_braucht_signatur_wenn_ein_token_gesetzt_ist():
    p = _plugin()
    c = _app(p)
    koerper = json.dumps({"ereignisse": [{"art": "lauf", "ok": True}]}).encode()
    zeit = str(int(time.time() * 1000))
    kopf = {"Content-Type": "application/json"}
    assert c.post("/hub/openclaw/ereignisse", content=koerper, headers=kopf).status_code == 401
    falsch = {**kopf, "X-FYOS-Zeit": zeit, "X-FYOS-Signatur": signatur("anderes", zeit, koerper)}
    assert c.post("/hub/openclaw/ereignisse", content=koerper, headers=falsch).status_code == 401
    alt = str(int(time.time() * 1000) - 3_600_000)
    veraltet = {**kopf, "X-FYOS-Zeit": alt, "X-FYOS-Signatur": signatur("geheim", alt, koerper)}
    assert c.post("/hub/openclaw/ereignisse", content=koerper, headers=veraltet).status_code == 401
    gut = {**kopf, "X-FYOS-Zeit": zeit, "X-FYOS-Signatur": signatur("geheim", zeit, koerper)}
    r = c.post("/hub/openclaw/ereignisse", content=koerper, headers=gut)
    assert r.status_code == 200 and r.json() == {"ok": True, "angenommen": 1}
    assert c.post("/hub/openclaw/ereignisse", content=koerper, headers={"Content-Type": "text/plain"}).status_code == 415
    assert p.zustand()["zaehler"]["abgewiesen"] == 3


def test_ohne_token_ist_die_lieferung_innen_offen():
    p = _plugin(token="")
    p._token = ""
    r = _app(p).post("/hub/openclaw/ereignisse", json={"ereignisse": [{"art": "lauf", "ok": True}]})
    assert r.status_code == 200 and r.json()["angenommen"] == 1


# ── Ablage: Workboard als Vorgangs-Dienst ───────────────────────────────────────────────────────


def test_ablage_bietet_den_vorgangs_vertrag_auf_den_karten():
    brett = Werkbrett()
    p = _plugin(rpc_aufruf=brett)
    assert p.modus == "ablage" and p.board == "default"
    c = _app(p)
    r = c.post("/hub/vorgaenge/tickets", json={"title": "Backup prüfen", "description": "nachts", "status": "waiting_approval",
                                               "priority": "p1", "type": "VOR"})
    assert r.status_code == 201
    t = r.json()
    assert t["status"] == "waiting_approval" and t["priority"] == "urgent" and t["id"].startswith("WB-")
    offen = c.get("/hub/vorgaenge/tickets", params={"status": "waiting_approval"}).json()["tickets"]
    assert [x["id"] for x in offen] == [t["id"]]
    assert c.get("/hub/vorgaenge/tickets", params={"status": "new"}).json()["tickets"] == []
    # Freigabe wie fyos-freigabe-chat: Kommentar, dann Status mit expected_status
    assert c.post(f"/hub/vorgaenge/tickets/{t['id']}/comments", json={"actor": "besitzer", "text": "ja"}).status_code == 200
    konflikt = c.patch(f"/hub/vorgaenge/tickets/{t['id']}", json={"status": "in_progress", "expected_status": "triage"})
    assert konflikt.status_code == 409 and konflikt.json()["ticket"]["status"] == "waiting_approval"
    ok = c.patch(f"/hub/vorgaenge/tickets/{t['id']}", json={"actor": "besitzer", "status": "in_progress",
                                                           "expected_status": "waiting_approval", "waiting_for": ""})
    assert ok.status_code == 200 and ok.json()["status"] == "in_progress" and ok.json()["karten_status"] == "running"
    karte = brett.karten[t["karte"]]
    assert [c_["body"] for c_ in karte["metadata"]["comments"]] == ["besitzer: ja", "besitzer: Status waiting_approval → in_progress"]
    assert c.get("/hub/vorgaenge/tickets/WB-00000000").status_code == 404
    assert c.post(f"/hub/vorgaenge/tickets/{t['id']}/comments", content=b"ja",
                  headers={"Content-Type": "text/plain"}).status_code == 415
    geschlossen = c.patch(f"/hub/vorgaenge/tickets/{t['id']}", json={"status": "closed"})
    assert geschlossen.json()["status"] == "closed"


# ── Spiegel: Vorgangs-Dienst ↔ Workboard ────────────────────────────────────────────────────────


def _spiegel(tickets: list[dict[str, Any]]):
    brett = Werkbrett()
    dienst = Vorgangsdienst(tickets)
    p = _plugin(rpc_aufruf=brett, vorgaenge_aufruf=dienst, vorgaenge_url="http://vorgaenge/api",
                vorgang_link="https://fyos.example/vorgaenge/{id}")
    return p, brett, dienst


def test_spiegel_legt_karten_an_und_ist_danach_ruhig():
    p, brett, _dienst = _spiegel([
        {"id": "INC-1", "title": "Platte voll", "status": "new", "priority": "P2", "description": "pool"},
        {"id": "VOR-2", "title": "Update einspielen", "status": "waiting_approval"},
        {"id": "CHG-3", "title": "längst erledigt", "status": "resolved"},
    ])
    assert p.modus == "spiegel" and p.board == "fyos"
    erst = p.abgleichen()
    assert erst["ok"] and erst["schritte"] == 2
    assert brett.boards["fyos"]["name"] == "FYOS-Vorgänge" and "automationJobId" not in brett.boards["fyos"]
    inc = brett.zur_vorgang("INC-1")
    assert inc["status"] == "triage" and inc["priority"] == "high" and inc["title"] == "[INC-1] Platte voll"
    assert inc["sourceUrl"] == "https://fyos.example/vorgaenge/INC-1" and "typ:inc" in inc["labels"]
    assert brett.zur_vorgang("VOR-2")["status"] == "review"
    zweit = p.abgleichen()
    assert zweit["schritte"] == 0, zweit["protokoll"]
    # Doppelte Anlage gibt es nicht, auch nicht bei vergessenem Stand (Idempotenzschlüssel)
    p._karten_stand = {}
    p._speicher().delete("fyos:openclaw:karten")
    p.abgleichen()
    assert len(brett.karten) == 2


def test_spiegel_traegt_status_aus_dem_vorgang_und_aus_openclaw():
    p, brett, dienst = _spiegel([{"id": "INC-1", "title": "Platte voll", "status": "new"}])
    p.abgleichen()
    dienst.tickets["INC-1"]["status"] = "in_progress"
    p.abgleichen()
    karte = brett.zur_vorgang("INC-1")
    assert karte["status"] == "running"
    # Ein Mensch erledigt die Karte in OpenClaw: der Vorgang wird resolved (nie closed)
    brett.verschiebe(karte["id"], "done")
    r = p.abgleichen()
    assert dienst.patches == [("INC-1", {"actor": "openclaw", "status": "resolved", "expected_status": "in_progress"})]
    assert "running → done" in dienst.kommentare[-1][1]["text"]
    assert r["ok"]
    # Danach ist der Vorgang nicht mehr offen; die Karte bleibt erledigt, nichts pendelt
    assert p.abgleichen()["schritte"] == 0
    assert brett.zur_vorgang("INC-1")["status"] == "done"


def test_spiegel_riegel_freigabe_entscheidet_nicht_das_workboard():
    p, brett, dienst = _spiegel([{"id": "VOR-2", "title": "Update", "status": "waiting_approval"}])
    p.abgleichen()
    karte = brett.zur_vorgang("VOR-2")
    brett.verschiebe(karte["id"], "running")  # sähe aus wie „genehmigt“
    p.abgleichen()
    assert dienst.patches == []
    assert "Freigabe bleibt offen" in dienst.kommentare[-1][1]["text"]
    assert brett.zur_vorgang("VOR-2")["status"] == "review"


def test_spiegel_erledigte_vorgaenge_und_kommentare():
    p, brett, dienst = _spiegel([{"id": "INC-1", "title": "Platte voll", "status": "triage"}])
    p.abgleichen()
    karte = brett.zur_vorgang("INC-1")
    brett.kommentiere(karte["id"], "Pool ist wieder frei")
    p.abgleichen()
    assert dienst.kommentare[-1] == ("INC-1", {"actor": "openclaw", "text": "Kommentar in OpenClaw: Pool ist wieder frei"})
    dienst.tickets["INC-1"]["status"] = "closed"
    p.abgleichen()
    assert brett.zur_vorgang("INC-1")["status"] == "done"
    assert len([k for k in dienst.kommentare if "Pool" in k[1]["text"]]) == 1


def test_spiegel_schliesst_nur_bei_sicherem_404():
    p, brett, dienst = _spiegel([{"id": "INC-7", "title": "weg", "status": "triage"}])
    p.abgleichen()
    del dienst.tickets["INC-7"]
    dienst.kaputt = True  # Nachschlagen scheitert: keine Entscheidung, Abgleich läuft weiter
    assert p.abgleichen()["ok"]
    assert brett.zur_vorgang("INC-7")["status"] == "backlog"
    dienst.kaputt = False  # jetzt ein echtes 404: die Karte gilt als erledigt
    p.abgleichen()
    assert brett.zur_vorgang("INC-7")["status"] == "done"


def test_plan_aendert_titel_und_prioritaet_aus_dem_vorgang():
    karte = {"id": "k1", "status": "backlog", "title": "[INC-1] alt", "priority": "normal", "notes": "",
             "labels": ["vorgang:INC-1"], "updatedAt": 5}
    schritte = V.plan({"INC-1": {"id": "INC-1", "title": "neu", "status": "triage", "priority": "critical"}},
                      [karte], {"k1": {"u": 5, "s": "backlog", "e": 5}}, "fyos")
    (s,) = schritte
    assert s.art == "aendern" and s.daten["title"] == "[INC-1] neu" and s.daten["priority"] == "urgent"
    assert "notes" in s.daten


# ── Beiträge: Zeitplan, Skills, Metriken, Zustand ───────────────────────────────────────────────


def test_zeitplan_skills_und_metriken_aus_dem_agenten():
    brett = Werkbrett()
    brett.cron = [{"id": "j1", "name": "morgen", "displayName": "Morgenbrief", "enabled": True,
                   "schedule": {"kind": "cron", "expr": "0 6 * * *", "tz": "Europe/Berlin"},
                   "nextRunAtMs": 2_000_000_000_000, "lastRunAtMs": 1_900_000_000_000, "lastRunStatus": "error",
                   "lastRunError": "Zeitlimit", "effectiveAgentId": "fy"},
                  {"id": "j2", "name": "takt", "enabled": False, "schedule": {"kind": "every", "everyMs": 900_000}}]
    brett.skills = [{"name": "wetter", "description": "Wetter holen", "source": "workspace",
                     "filePath": "/home/node/.openclaw/workspace/skills/wetter/SKILL.md"},
                    {"name": "notizen", "description": "FYOS-Skill", "filePath": "/opt/fyos/skills/notizen/SKILL.md"},
                    {"name": "github", "description": "mitgeliefert", "filePath": "/app/skills/github/SKILL.md",
                     "source": "openclaw-bundled", "bundled": True},
                    {"name": "canvas", "description": "Skill eines OpenClaw-Plugins", "source": "openclaw-extra",
                     "bundled": False, "filePath": "/home/node/.openclaw/plugin-skills/canvas/SKILL.md"},
                    {"name": "aus", "description": "abgeschaltet", "filePath": "/x/aus/SKILL.md", "disabled": True},
                    {"name": "fehlt", "description": "Voraussetzung fehlt", "filePath": "/x/fehlt/SKILL.md", "eligible": False}]
    brett.skill_texte["wetter"] = "---\nname: wetter\n---\nSo holt man das Wetter."
    p = _plugin(rpc_aufruf=brett)
    p.takt_schritt({}, jetzt=0.0)
    plan = {e["id"]: e for e in p.zeitplan()}
    assert plan["cron:j1"]["takt"] == "0 6 * * * (Europe/Berlin)" and plan["cron:j1"]["letzter_status"] == "fehler"
    assert plan["cron:j1"]["name"] == "Morgenbrief" and plan["cron:j2"]["takt"] == "alle 15 min" and not plan["cron:j2"]["an"]
    assert plan["sonde"]["letzter_status"] == "ok"
    beitrag = p.skills_beitrag()
    # Eigene und FYOS-Skills des Agenten ja; mitgelieferte (auch die der Plugins), abgeschaltete und nicht nutzbare nein.
    assert {b["name"]: b["quelle"] for b in beitrag} == {"wetter": "openclaw", "notizen": "fyos-agent"}
    assert beitrag[0]["lesen"]().endswith("Wetter.")
    text = metriken.erzeugen(_Registry(p))
    assert 'fyos_zeitplan_letzter_ok{aufgabe="Morgenbrief",plugin="openclaw",quelle="openclaw"} 0' in text
    assert "fyos_openclaw_gateway_lebt 1" in text and "# TYPE fyos_openclaw_rpc_fehler_total counter" in text


# ── Takt-Grenzen (Fenster, Tageslimit) ──────────────────────────────────────────────────────────

T_TAKT = 1_791_100_000.0


def _fenster(t: float, drin: bool) -> str:
    """Ein Fenster, das die Zeit ``t`` enthält (drin) oder erst in einer Stunde beginnt (Zeitzone des Prozesses)."""
    lokal = time.localtime(t)
    m = lokal.tm_hour * 60 + lokal.tm_min
    von, bis = ((m - 30) % 1440, (m + 30) % 1440) if drin else ((m + 60) % 1440, (m + 120) % 1440)
    return f"{von // 60:02d}:{von % 60:02d}-{bis // 60:02d}:{bis % 60:02d}"


def _spiegel_mit(grenzen: dict[str, Any]):
    brett = Werkbrett()
    dienst = Vorgangsdienst([{"id": "INC-1", "title": "Platte voll", "status": "new"}])
    p = _plugin(rpc_aufruf=brett, vorgaenge_aufruf=dienst, vorgaenge_url="http://vorgaenge/api", takt_grenzen=grenzen)
    p._waechter._uhr = lambda: T_TAKT
    return p, brett


def _aufrufe(brett: Werkbrett) -> list[str]:
    return [methode for methode, _ in brett.aufrufe]


def test_takt_grenzen_halten_den_abgleich_ausserhalb_des_fensters_an():
    p, brett = _spiegel_mit({"abgleich": {"fenster": _fenster(T_TAKT, drin=False)}})
    p.takt_schritt({}, jetzt=0.0)
    assert not [m for m in _aufrufe(brett) if m.startswith("workboard.")]  # der Abgleich hat nicht stattgefunden
    assert {"cron.list", "skills.status"} <= set(_aufrufe(brett))  # Takte ohne Grenzen laufen weiter
    e = {x["id"]: x for x in p.zeitplan()}["abgleich"]
    assert (e["ruht"], e["uebersprungen"], e["laeufe_heute"]) == ("fenster", {"fenster": 1}, 0)
    assert e["fenster"] and e["max_pro_tag"] is None
    text = metriken.erzeugen(_Registry(p))
    assert 'fyos_zeitplan_uebersprungen_total{grund="fenster",takt="openclaw:abgleich"} 1' in text
    assert 'fyos_zeitplan_laeufe_heute{takt="openclaw:abgleich"} 0' in text
    # Auf Abruf (Werkzeug openclaw.abgleichen) läuft der Abgleich immer.
    assert p.call("abgleichen", {})["ok"] and len(brett.karten) == 1


def test_takt_grenzen_lassen_den_abgleich_im_fenster_laufen_und_protokollieren():
    p, brett = _spiegel_mit({"abgleich": {"fenster": _fenster(T_TAKT, drin=True), "max_pro_tag": 10}})
    p.takt_schritt({}, jetzt=0.0)
    assert len(brett.karten) == 1
    e = {x["id"]: x for x in p.zeitplan()}["abgleich"]
    assert (e["ruht"], e["laeufe_heute"], e["max_pro_tag"], e["uebersprungen"]) == (None, 1, 10, {"fenster": 0, "limit": 0})
    assert [(l["start"], l["ergebnis"]) for l in e["protokoll"]] == [(T_TAKT, "ok")]


def test_takt_grenzen_begrenzen_die_abfrage_der_cron_liste_pro_tag():
    brett = Werkbrett()
    p = _plugin(rpc_aufruf=brett, takt_grenzen={"cron": {"max_pro_tag": 1}})
    p._waechter._uhr = lambda: T_TAKT
    letzte: dict[str, float] = {}
    p.takt_schritt(letzte, jetzt=0.0)
    p.takt_schritt(letzte, jetzt=100.0)  # 60 s sind um: der Takt wäre wieder fällig
    assert _aufrufe(brett).count("cron.list") == 1 and _aufrufe(brett).count("skills.status") == 1
    plan = {x["id"]: x for x in p.zeitplan()}
    assert (plan["cron"]["laeufe_heute"], plan["cron"]["uebersprungen"], plan["cron"]["ruht"]) == (1, {"limit": 1}, "limit")
    assert "skills" not in plan  # ohne Grenzen erscheint der Takt nicht in der Ansicht


def test_ohne_takt_grenzen_aendert_sich_nichts_am_takt():
    p, brett, _dienst = _spiegel([{"id": "INC-1", "title": "Platte voll", "status": "new"}])
    letzte: dict[str, float] = {}
    for i in range(3):
        p.takt_schritt(letzte, jetzt=i * 100.0)
    assert _aufrufe(brett).count("cron.list") == 3 and len(brett.karten) == 1
    plan = {x["id"]: x for x in p.zeitplan()}
    assert set(plan) == {"sonde", "abgleich", "wecken"}
    e = plan["abgleich"]
    assert (e["max_pro_tag"], e["fenster"], e["ruht"], e["uebersprungen"], e["laeufe_heute"]) == (None, None, None, {}, 3)
    assert "ruht" not in plan["sonde"] and "laeufe_heute" not in plan["sonde"]  # die Sonde läuft ohne Wächter


def test_takt_grenzen_mit_tippfehler_verhindern_den_start():
    with pytest.raises(GrenzenFehler, match=r"'sonde'.*bekannt: cron, skills, abgleich, karten, wecken"):
        _plugin(takt_grenzen={"sonde": {"max_pro_tag": 5}})
    with pytest.raises(GrenzenFehler, match=r"openclaw\.abgleich: fenster 'abends'"):
        _plugin(takt_grenzen={"abgleich": {"fenster": "abends"}})


def test_skills_verzeichnis_nimmt_die_beitraege_auf(tmp_path):
    (tmp_path / "notizen").mkdir()
    (tmp_path / "notizen" / "SKILL.md").write_text("---\nname: notizen\ndescription: Datei gewinnt\n---\nText", encoding="utf-8")
    brett = Werkbrett()
    brett.skills = [{"name": "wetter", "description": "Wetter holen", "filePath": "/app/skills/wetter/SKILL.md"},
                    {"name": "notizen", "description": "gleichnamig im Agenten", "filePath": "/app/skills/notizen/SKILL.md"}]
    brett.skill_texte["wetter"] = "So holt man das Wetter."
    p = _plugin(rpc_aufruf=brett)
    p.agent_skills()
    skills = SkillsPlugin(config={"quellen": [str(tmp_path)], "plugin_skills": False})
    skills.registry_anbinden(_Registry(p, skills))
    treffer = skills.call("suchen", {"q": "wetter"})["skills"]
    assert treffer == [{"name": "wetter", "quelle": "openclaw", "beschreibung": "Wetter holen"}]
    assert skills.call("lesen", {"name": "wetter"})["text"] == "So holt man das Wetter."
    assert skills.call("lesen", {"name": "notizen"})["quelle"] == tmp_path.name
    with pytest.raises(ValueError):
        skills.call("lesen", {"name": "wetter", "datei": "x.md"})


def test_gesundheit_folgt_sonde_und_bruecke():
    assert _plugin(http_get=_sonde(lebt=False)).health()["status"] == "unreachable"
    assert _plugin(http_get=_sonde(bereit=False)).health()["status"] == "degraded"
    p = _plugin()
    gesund = p.health()
    assert gesund["ok"] and "Brücke hat sich noch nicht gemeldet" in gesund["hinweise"]
    p.annehmen({"ereignisse": []})
    assert p.health()["hinweise"] == []
    p._bruecke["zuletzt"] = time.time() - 3600
    assert p.health()["status"] == "degraded"


def test_werkzeuge_und_scopes():
    namen = {t.name: t.tags for t in _plugin().describe_tools()}
    assert list(namen) == ["zustand", "nutzung", "aktivitaet", "erweiterungen", "arbeit", "abgleichen", "wecken",
                           "vorgang_senden", "lebt", "erinnern", "gedaechtnis", "dienste", "profile", "auftrag_vorlage", "ereignisse"]
    schreibend = {"abgleichen", "wecken", "vorgang_senden"}
    assert all("write" in namen[n] for n in schreibend)
    assert all("read" in t for n, t in namen.items() if n not in schreibend)


def test_erweiterungen_zeigen_beide_seiten():
    brett = Werkbrett()
    brett.skills = [{"name": "notizen", "filePath": "/opt/fyos/skills/notizen/SKILL.md", "eligible": True},
                    {"name": "wetter", "filePath": "/app/skills/wetter/SKILL.md", "source": "openclaw-bundled"},
                    {"name": "canvas", "source": "openclaw-extra", "baseDir": "/home/node/.openclaw/plugin-skills/canvas"}]
    p = _plugin(rpc_aufruf=brett)
    p.annehmen({"bruecke": {"plugins": [{"id": "workboard"}, {"id": "fyos-bruecke"}]}, "ereignisse": []})
    skills = SimpleNamespace(name="skills", katalog=lambda: {
        "notizen": {"quelle": "fyos", "pfad": "/opt/fyos/skills/notizen"},
        "backup": {"quelle": "fyos", "pfad": "/opt/fyos/skills/backup"},
        "wetter": {"quelle": "openclaw", "pfad": "openclaw:wetter"},  # Beitrag des Agenten, kein Hub-Skill
    })
    p._registry = SimpleNamespace(plugins={"openclaw": p, "skills": skills}, tools={})
    e = p.call("erweiterungen", {})
    assert {z["name"]: z["quelle"] for z in e["agent_skills"]} == {"notizen": "fyos", "wetter": "openclaw-bundled",
                                                                   "canvas": "openclaw-plugin"}
    assert e["agent_plugins"] == [{"id": "workboard", "an": True}, {"id": "fyos-bruecke", "an": True}]
    assert e["hub_skills_nur_im_hub"] == ["backup"]


# ── Chat-Kanäle des Agenten ─────────────────────────────────────────────────────────────────────


def test_der_kopf_der_bruecke_nennt_die_kanaele_nur_als_wahrheitswerte():
    p = _plugin()
    p.annehmen({"bruecke": {"kanaele": {
        "telegram": {"an": True, "ziel": True, "bereit": False, "adresse": "4711"},
        "whatsapp": {"an": True, "ziel": False},
        "matrix": "kaputt", "signal": {"an": True, "ziel": True},
    }}, "ereignisse": []})
    erwartet = {"telegram": {"an": True, "ziel": True, "bereit": True},
                "whatsapp": {"an": True, "ziel": False, "bereit": False}}
    z = p.zustand()
    assert z["kanaele"] == erwartet and "kanaele" not in z["bruecke"]
    assert "4711" not in json.dumps(z)
    # eine Lieferung ohne Kanäle löscht den letzten Stand nicht
    p.annehmen({"bruecke": {"version": "0.1.0"}, "ereignisse": []})
    assert p.zustand()["kanaele"] == erwartet


def test_kanal_mitteilen_ruft_die_methode_der_bruecke():
    aufrufe: list[tuple[str, dict[str, Any]]] = []

    def rpc(methode: str, params: dict[str, Any]) -> Any:
        aufrufe.append((methode, params))
        return {"gesendet": True, "kanal": "telegram", "gescheitert": []}

    p = _plugin(rpc_aufruf=rpc)
    assert p.kanal_mitteilen("Platte voll")["kanal"] == "telegram"
    p.kanal_mitteilen("x" * 5000, "matrix")
    assert aufrufe[0] == ("fyos.kanal.mitteilen", {"text": "Platte voll"})
    assert aufrufe[1][1]["kanal"] == "matrix" and len(aufrufe[1][1]["text"]) <= 4000


def test_das_plugin_meldet_den_weg_zum_kanal_an_und_beim_beenden_ab():
    from mcp_hub import os_bruecke

    p = _plugin()
    p._faden = object()  # kein Takt-Faden im Test
    p.registry_anbinden(_Registry(p))
    assert os_bruecke.angemeldeter_kanal() == p.kanal_mitteilen
    p.shutdown()
    assert os_bruecke.angemeldeter_kanal() is None
    ohne_token = _plugin(token="", rpc_aufruf=None)
    ohne_token._faden = object()
    ohne_token.registry_anbinden(_Registry(ohne_token))
    assert os_bruecke.angemeldeter_kanal() is None
