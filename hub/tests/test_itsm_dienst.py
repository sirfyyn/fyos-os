"""ITSM des Kerns beim Vorgangs-Dienst: die Werkzeuge reichen an den Dienst durch (HTTP-Attrappe im selben Prozess).

Die Attrappe spricht den Vorgangs-Vertrag unter ``/api/itsm`` (``/tickets…``, ``/tickets/{id}/history``, ``/waiting``),
prüft ``expected_status`` (409) und merkt sich jeden Aufruf. Geprüft wird, dass die Werkzeuge, die ein Agent beim Dienst
nutzt (vorgang, wartend, notiz, anlegen, status_setzen, freigabe_beantragen; kommentieren und status von der
Oberfläche), dort ankommen, mit den Feldern, die der Dienst erwartet, und ohne Redis.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mcp_hub import vorgaenge as VG
from mcp_hub.plugins.itsm import ItsmPlugin
from mcp_hub.registry import AUFRUFER


class Dienst:
    """Ein Ticketdienst im Speicher; ``waiting`` schaltet ``/waiting`` ab (dann 404)."""

    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self.verlauf: dict[str, list[dict[str, Any]]] = {}
        self.aufrufe: list[tuple[str, str, Any]] = []
        self.waiting = True
        self.nr = 0

    def neu(self, **felder: Any) -> dict[str, Any]:
        self.nr += 1
        t = {"id": f"{felder.pop('type', 'INC')}-{self.nr}", "status": "new", "title": "", "description": "",
             "assignee": "", "waiting_for": "", "severity": "medium", "created_at": "2026-10-01T08:00:00+00:00",
             "updated_at": "2026-10-01T08:00:00+00:00", **felder}
        t["type"] = t["id"].split("-")[0]
        self.tickets[t["id"]] = t
        self.verlauf[t["id"]] = [{"ts": t["created_at"], "event": "created", "actor": t.get("reporter") or "x", "detail": ""}]
        return t

    def antwort(self, methode: str, pfad: str, koerper: Any) -> tuple[int, Any]:
        self.aufrufe.append((methode, pfad, koerper))
        teile = urllib.parse.urlsplit(pfad)
        assert teile.path.startswith("/api/itsm/")
        stuecke = [urllib.parse.unquote(s) for s in teile.path[len("/api/itsm/"):].split("/") if s]
        q = dict(urllib.parse.parse_qsl(teile.query))
        if stuecke == ["waiting"]:
            if not self.waiting:
                return 404, {"detail": "Not Found"}
            gruppen: dict[str, list[dict[str, Any]]] = {}
            for t in self.tickets.values():
                if t["waiting_for"] and t["status"] not in ("resolved", "closed"):
                    gruppen.setdefault(t["waiting_for"], []).append({k: t[k] for k in ("id", "title", "type", "status", "severity")})
            return 200, {"gruppen": gruppen, "wartende": sum(len(g) for g in gruppen.values())}
        if stuecke == ["tickets"] and methode == "GET":
            ts = [t for t in self.tickets.values() if not q.get("status") or t["status"] == q["status"]]
            return 200, {"tickets": ts[: int(q.get("limit") or 50)]}
        if stuecke == ["tickets"] and methode == "POST":
            fp = koerper.get("fingerprint")
            for t in self.tickets.values():
                if fp and t.get("fingerprint") == fp and t["status"] not in ("resolved", "closed"):
                    return 200, {"angelegt": False, "entdupliziert": True, "entdupliziert_auf": t["id"], "ticket": t}
            felder = {k: v for k, v in koerper.items() if k not in ("actor", "source")}
            return 201, {"ok": True, "ticket": self.neu(**felder)}
        if not stuecke or stuecke[0] != "tickets" or stuecke[1] not in self.tickets:
            return 404, {"detail": "Ticket nicht gefunden"}
        t = self.tickets[stuecke[1]]
        if len(stuecke) == 2 and methode == "GET":
            return 200, {"ok": True, "ticket": t}
        if len(stuecke) == 3 and stuecke[2] == "history":
            return 200, {"history": list(reversed(self.verlauf[t["id"]]))[: int(q.get("limit") or 20)]}
        if len(stuecke) == 3 and stuecke[2] == "comments" and methode == "POST":
            self.verlauf[t["id"]].append({"ts": "2026-10-02T09:00:00+00:00", "event": "comment",
                                          "actor": koerper["actor"], "detail": koerper["text"]})
            return 200, {"ok": True}
        if len(stuecke) == 2 and methode == "PATCH":
            if koerper.get("expected_status") and koerper["expected_status"] != t["status"]:
                return 409, {"detail": f"status ist {t['status']}", "ticket": t}
            alt = t["status"]
            for k, v in koerper.items():
                if k not in ("actor", "expected_status"):
                    t[k] = v
            self.verlauf[t["id"]].append({"ts": "2026-10-02T10:00:00+00:00", "event": "updated", "actor": koerper.get("actor"),
                                          "detail": f"status {alt}→{t['status']}"})
            return 200, {"ok": True, "ticket": t}
        return 405, {"detail": "nein"}


@pytest.fixture()
def dienst(monkeypatch):
    d = Dienst()

    class Handler(BaseHTTPRequestHandler):
        def _antworten(self, methode: str) -> None:
            laenge = int(self.headers.get("Content-Length") or 0)
            koerper = json.loads(self.rfile.read(laenge)) if laenge else None
            status, daten = d.antwort(methode, self.path, koerper)
            roh = json.dumps(daten).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

        def do_GET(self) -> None:  # noqa: N802
            self._antworten("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._antworten("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._antworten("PATCH")

        def log_message(self, *a: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    faden = threading.Thread(target=server.serve_forever, daemon=True)
    faden.start()
    for name in ("FYOS_VORGAENGE_KOPF", "FYOS_BESITZER_NAMEN", "FYOS_AGENT_ID", "FYOS_AGENTEN", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FYOS_VORGAENGE_URL", f"http://127.0.0.1:{server.server_address[1]}/api/itsm")
    monkeypatch.setenv("FYOS_BESITZER_AKTEUR", "chefin")
    VG.ablage_anmelden(None)
    VG.dienst_anmelden(None)
    yield d
    server.shutdown()
    server.server_close()
    VG.ablage_anmelden(None)


@pytest.fixture()
def itsm(monkeypatch):
    monkeypatch.setenv("FYOS_AGENTEN", "helferin,zweite")
    p = ItsmPlugin()  # ohne Redis: beim Dienst braucht es keins
    p.register()
    return p


@pytest.fixture()
def oberflaeche():
    marke = AUFRUFER.set("fyos-web")
    yield
    AUFRUFER.reset(marke)


VORHABEN = {"vorhaben": "Dienst neu starten und den Zwischenspeicher leeren", "wirkung": "20 s nicht erreichbar",
            "ziel": "hub", "rueckweg": "nichts zu tun, startet von selbst"}


def test_ohne_redis_aber_mit_dienst_ist_es_eingerichtet(dienst, itsm):
    assert itsm.agent == "helferin" and itsm.besitzer == "chefin"
    h = itsm.health()
    assert h["ok"] and h["weg"] == "dienst" and "127.0.0.1" in h["quelle"]
    dienst.neu(title="Offen", status="triage")
    dienst.neu(title="Erledigt", status="resolved")
    r = itsm.call("liste", {})
    assert [z["titel"] for z in r["vorgaenge"]] == ["Offen"] and r["quelle"] == "dienst"
    assert [p for _, p, _ in dienst.aufrufe] == [f"/api/itsm/tickets?status={s}&limit=50" for s in VG.OFFEN]
    assert VG.angemeldete_ablage() is None


def test_vorgang_mit_verlauf_und_antwortform(dienst, itsm):
    t = dienst.neu(type="PRB", title="Speicher läuft voll", assignee="helferin", waiting_for="chefin: welche Grenze?",
                   status="triage", description="<!-- intern -->Seit Montag", reporter="helferin")
    v = itsm.call("vorgang", {"id": t["id"].lower(), "verlauf": 50})
    assert v["id"] == t["id"] and v["art"] == "PRB" and v["schwere"] == "medium" and v["zustaendig"] == "helferin"
    assert v["beschreibung"] == "Seit Montag" and v["antwort"] == "text" and "closed" in v["folge_status"]
    assert v["verlauf"] == [{"ts": "2026-10-01T08:00:00+00:00", "ereignis": "created", "wer": "helferin", "text": None}]
    with pytest.raises(ValueError, match="Ticket nicht gefunden"):
        itsm.call("vorgang", {"id": "INC-999"})


def test_wartend_ueber_waiting_und_ohne(dienst, itsm):
    dienst.neu(title="Freigabe Neustart", status="waiting_approval", waiting_for="chefin: Freigabe — Neustart",
               assignee="helferin", severity="high")
    dienst.neu(title="Wartet auf Lieferung", status="triage", waiting_for="lieferant")
    w = itsm.call("wartend", {})
    assert w["art"] == "waiting" and w["anzahl"] == 1 and w["andere_wartende"] == 1
    t = w["tickets"][0]
    assert t["zustaendig"] == "helferin" and t["schwere"] == "hoch" and t["alter_tage"] >= 0 and t["typ"] == "INC"
    # zwischengespeichert: kein zweiter Weg zum Dienst
    n = len(dienst.aufrufe)
    assert itsm.call("wartend", {}) == w and len(dienst.aufrufe) == n
    # ein Dienst ohne /waiting: die Freigaben
    dienst.waiting = False
    itsm._wartend_frisch = None
    w = itsm.call("wartend", {})
    assert w["art"] == "freigaben" and [x["titel"] for x in w["tickets"]] == ["Freigabe Neustart"]


def test_notiz_und_kommentar_mit_dem_richtigen_akteur(dienst, itsm, oberflaeche):
    t = dienst.neu(title="Backup")
    marke = AUFRUFER.set("mcp:runner")
    try:
        r = itsm.call("notiz", {"id": t["id"], "text": "Befund: Platte voll"})
        assert r["ok"] and r["von"] == "helferin"
    finally:
        AUFRUFER.reset(marke)
    r = itsm.call("kommentieren", {"id": t["id"], "text": "Danke, passt"})  # ohne bestaetigt, wie bisher beim Dienst
    assert r["ok"] and r["von"] == "chefin"
    kommentare = [k for m, p, k in dienst.aufrufe if m == "POST" and p.endswith("/comments")]
    assert kommentare == [{"actor": "helferin", "text": "Befund: Platte voll"}, {"actor": "chefin", "text": "Danke, passt"}]


def test_anlegen_mit_fingerprint_und_entdoppelung(dienst, itsm):
    args = {"titel": "Platte fast voll", "typ": "PRB", "schwere": "high", "fingerprint": "agent:nas:platte-voll",
            "verweise": ["inc-7"], "beschreibung": "92 %"}
    r = itsm.call("anlegen", args)
    assert r["ok"] and r["angelegt"] and r["id"].startswith("PRB-") and r["zustaendig"] == "helferin"
    koerper = dienst.aufrufe[-1][2]
    assert koerper["severity"] == "high" and koerper["links"] == ["INC-7"] and koerper["reporter"] == "helferin"
    assert koerper["actor"] == "helferin" and koerper["fingerprint"] == "agent:nas:platte-voll" and "status" not in koerper
    zweit = itsm.call("anlegen", args)
    assert zweit["angelegt"] is False and zweit["entdupliziert"] and zweit["id"] == r["id"]
    assert itsm.call("anlegen", {"titel": "x", "__dry_run__": True})["dry_run"] is True


def test_status_setzen_als_agent(dienst, itsm):
    t = dienst.neu(title="Zertifikat", status="in_progress", assignee="helferin")
    with pytest.raises(ValueError, match="expected_status"):
        itsm.call("status_setzen", {"id": t["id"], "status": "resolved"})
    with pytest.raises(ValueError, match="closed"):
        itsm.call("status_setzen", {"id": t["id"], "status": "closed", "expected_status": "in_progress"})
    with pytest.raises(ValueError, match="freigabe_beantragen"):
        itsm.call("status_setzen", {"id": t["id"], "status": "waiting_approval", "expected_status": "in_progress"})
    alt = itsm.call("status_setzen", {"id": t["id"], "status": "resolved", "expected_status": "triage"})
    assert alt["ok"] is False and alt["zustand"] == "konflikt"
    r = itsm.call("status_setzen", {"id": t["id"], "status": "resolved", "expected_status": "in_progress",
                                    "begruendung": "erneuert"})
    assert r == {"ok": True, "id": t["id"], "vorgang": t["id"], "von": "in_progress", "status": "resolved",
                 "geaendert": True, "satz": f"{t['id']}: in_progress → resolved."}
    assert dienst.aufrufe[-1] == ("PATCH", f"/api/itsm/tickets/{t['id']}",
                                  {"actor": "helferin", "status": "resolved", "expected_status": "in_progress"})
    assert dienst.aufrufe[-2][2] == {"actor": "helferin", "text": "erneuert"}


def test_freigabe_beantragen_beim_dienst(dienst, itsm):
    t = dienst.neu(title="Neustart", status="in_progress", assignee="helferin", description="Alter Text")
    angaben = {"risiko": "mittel", "zerstoererisch": False,
               "kontext": "Der Hub startet neu. Er ist 20 s weg. Danach läuft er wie vorher, token=geheim123 bleibt."}
    r = itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN, **angaben})
    assert r["ok"] and r["risiko"] == "medium" and r["zerstoererisch"] is False
    patch = [k for m, p, k in dienst.aufrufe if m == "PATCH"][-1]
    assert patch["status"] == "waiting_approval" and patch["expected_status"] == "in_progress"
    assert patch["waiting_for"].startswith("chefin: Freigabe — Dienst neu starten")
    assert patch["description"].startswith(f"## Freigabe angefragt (Prüfsumme {r['pruefsumme']})")
    assert patch["description"].endswith("Alter Text") and "geheim123" not in patch["kontext"]
    letzter = dienst.aufrufe[-1]
    assert letzter[0] == "POST" and letzter[2]["text"].startswith("## Freigabe angefragt")
    assert itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN, **angaben})["idempotent"] is True


def test_freigeben_und_status_von_der_oberflaeche(dienst, itsm, oberflaeche):
    t = dienst.neu(title="Neustart", status="waiting_approval", waiting_for="chefin: Freigabe")
    with pytest.raises(ValueError, match="bestaetigt"):
        itsm.call("freigeben", {"id": t["id"]})
    r = itsm.call("freigeben", {"id": t["id"], "begruendung": "ja", "bestaetigt": True})
    assert r["status"] == "in_progress" and dienst.aufrufe[-1][2]["actor"] == "chefin"
    plan = itsm.call("status", {"id": t["id"], "status": "closed"})
    assert plan["trockenlauf"] and plan["erlaubt"] and "nicht mehr auf dich" in " ".join(plan["wirkung"])
    r = itsm.call("status", plan["ausfuehren_mit"])
    assert r["bestaetigt"] is True and dienst.tickets[t["id"]]["status"] == "closed"
    assert dienst.aufrufe[-2][2] == {"actor": "chefin", "status": "closed", "expected_status": "in_progress", "waiting_for": ""}


def test_dienst_nicht_erreichbar_ist_ein_fehler(itsm, monkeypatch):
    monkeypatch.setenv("FYOS_VORGAENGE_URL", "http://127.0.0.1:9/api/itsm")
    with pytest.raises(VG.QuelleFehler, match="nicht erreichbar"):
        itsm.call("vorgang", {"id": "INC-1"})
