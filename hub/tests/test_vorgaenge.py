"""Vorgänge für Plugins (``mcp_hub.vorgaenge``): Dienst, Workboard oder keine Quelle — ohne Netz."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_hub import vorgaenge as VG
from mcp_hub.vorgaenge import NichtEingerichtet, QuelleFehler, VorgangFehlt, VorgangKonflikt

from .test_openclaw import Werkbrett, _plugin, _Registry


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    monkeypatch.delenv("FYOS_VORGAENGE_URL", raising=False)
    monkeypatch.delenv("FYOS_VORGAENGE_KOPF", raising=False)
    VG.ablage_anmelden(None)
    VG.dienst_anmelden(None)
    yield
    VG.ablage_anmelden(None)
    VG.dienst_anmelden(None)


class Dienst:
    """Vorgangs-Dienst im Speicher; antwortet wie ein Ticketdienst, der Einzelvorgänge verpackt."""

    def __init__(self) -> None:
        self.tickets = {
            "INC-1": {"id": "INC-1", "title": "Platte voll", "status": "new", "waiting_for": "besitzer"},
            "CHG-2": {"id": "CHG-2", "title": "Update", "status": "waiting_approval"},
        }
        self.aufrufe: list[tuple[str, str, Any]] = []
        self.kaputt = 0

    def __call__(self, methode: str, pfad: str, koerper: Any, frist: float) -> tuple[int, Any]:
        self.aufrufe.append((methode, pfad, koerper))
        if self.kaputt:
            return self.kaputt, {"detail": "Dienst wackelt"}
        if methode == "GET" and pfad.startswith("/tickets?"):
            status = pfad.split("status=")[1].split("&")[0] if "status=" in pfad else ""
            return 200, {"tickets": [t for t in self.tickets.values() if not status or t["status"] == status]}
        teile = pfad.split("?")[0].split("/")
        vid = teile[2] if len(teile) > 2 else ""
        if methode == "GET" and len(teile) == 4 and teile[3] == "history":
            return 200, {"history": [{"event": "comment", "actor": "besitzer", "detail": "ok"}]}
        if vid and vid not in self.tickets:
            return 404, {"detail": f"{vid} not found"}
        if methode == "GET":
            return 200, {"ok": True, "ticket": self.tickets[vid]}
        if methode == "POST" and pfad.endswith("/comments"):
            return 200, {"ok": True}
        if methode == "PATCH":
            t = self.tickets[vid]
            if koerper.get("expected_status") and koerper["expected_status"] != t["status"]:
                return 409, {"detail": "status_conflict"}
            t.update({k: v for k, v in koerper.items() if k in ("status", "title")})
            return 200, {"ok": True, "ticket": t}
        if methode == "POST" and pfad == "/tickets":
            t = {"id": "INC-3", **koerper}
            self.tickets["INC-3"] = t
            return 201, {"ok": True, "ticket": t}
        return 500, {"detail": "unerwartet"}


# ── Auswahl der Quelle ──────────────────────────────────────────────────────────────────────────


def test_ohne_dienst_und_ohne_ablage_ist_nichts_eingerichtet():
    q = VG.quelle()
    assert q.art == "keine" and not q.eingerichtet
    assert q.liste() == [] and q.freigaben() == []
    with pytest.raises(NichtEingerichtet):
        q.holen("INC-1")
    with pytest.raises(NichtEingerichtet):
        q.kommentieren("INC-1", "hallo")
    with pytest.raises(NichtEingerichtet):
        q.verlauf("INC-1")
    status, d = q.roh("GET", "/tickets/INC-1")
    assert status == 501 and "Keine Ablage" in d["detail"]
    assert q.roh("GET", "/tickets?status=new") == (200, {"tickets": [], "quelle": "keine"})


def test_eine_adresse_macht_den_dienst_zur_quelle(monkeypatch):
    monkeypatch.setenv("FYOS_VORGAENGE_URL", "http://tickets.example:8080/api/")
    monkeypatch.setenv("FYOS_VORGAENGE_KOPF", "X-Innen: ja")
    q = VG.quelle()
    assert q.art == "dienst" and q.url == "http://tickets.example:8080/api" and q.kopf == {"X-Innen": "ja"}
    assert "tickets.example:8080" in q.beschreibung()
    # die eigene Ablage zählt nicht als Dienst
    assert VG.quelle(url="http://hub:8080/hub/vorgaenge/").art == "keine"
    # kaputte Kopfzeilen werden nicht gesendet
    assert VG.quelle(kopf="ohne doppelpunkt").kopf == {}
    assert VG.quelle(kopf="Name mit Leerzeichen: x").kopf == {}


def _ohne_takt(p: Any) -> Any:
    p._faden = object()  # registry_anbinden startet sonst den Takt-Faden (mit echten Abfragen)
    return p


def test_das_workboard_meldet_sich_als_ablage_an_und_ab():
    p = _ohne_takt(_plugin(rpc_aufruf=Werkbrett()))
    assert VG.quelle().art == "keine"
    p.registry_anbinden(_Registry(p))
    try:
        assert VG.quelle().art == "workboard"
        # ein Dienst hat Vorrang vor der Ablage
        assert VG.quelle(url="http://tickets.example").art == "dienst"
    finally:
        p.shutdown()
    assert VG.quelle().art == "keine"


def test_im_spiegel_gilt_der_gespiegelte_dienst_samt_kopfzeile(monkeypatch):
    # Adresse und Kopfzeile nur in der config des Plugins: die anderen Plugins fragen trotzdem denselben Dienst
    p = _ohne_takt(_plugin(rpc_aufruf=Werkbrett(), vorgaenge_url="http://tickets.example/api/",
                           vorgaenge_kopf="X-Innen: ja"))
    monkeypatch.setenv("FYOS_VORGAENGE_URL", "http://anderswo.example")
    p.registry_anbinden(_Registry(p))
    try:
        assert VG.angemeldete_ablage() is None
        q = VG.quelle()
        assert (q.art, q.url, q.kopf) == ("dienst", "http://tickets.example/api", {"X-Innen": "ja"})
        assert VG.quelle(kopf="X-Anders: 1").kopf == {"X-Anders": "1"}
        assert VG.quelle(url="http://direkt.example").url == "http://direkt.example"
    finally:
        p.shutdown()
    assert VG.angemeldeter_dienst() is None and VG.quelle().url == "http://anderswo.example"


def test_ein_eingetragener_dienst_gilt_auch_ohne_gateway(monkeypatch):
    # Die Kopplung ruht (kein FYOS_AGENT_URL), der Vorgangs-Dienst steht aber in der config: die anderen Plugins
    # (Leitstand, Zentrale) lesen ihn trotzdem. Eine Ablage gibt es ohne Gateway nicht.
    monkeypatch.delenv("FYOS_AGENT_URL", raising=False)
    p = _plugin(gateway_url="", vorgaenge_url="http://tickets.example/api")
    assert p.modus == "aus"
    p.registry_anbinden(_Registry(p))
    try:
        assert VG.angemeldete_ablage() is None and p._faden is None
        assert (VG.quelle().art, VG.quelle().url) == ("dienst", "http://tickets.example/api")
    finally:
        p.shutdown()
    assert VG.angemeldeter_dienst() is None and VG.quelle().art == "keine"
    ohne = _plugin(gateway_url="")
    ohne.registry_anbinden(_Registry(ohne))
    try:
        assert VG.quelle().art == "keine"
    finally:
        ohne.shutdown()


def test_der_spiegel_schickt_die_kopfzeile_mit(monkeypatch):
    gesehen: list[dict[str, str]] = []

    class Antwort:
        status = 200

        def __enter__(self) -> "Antwort":
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def read(self, n: int = -1) -> bytes:
            return b'{"tickets": []}'

    def urlopen(req: Any, timeout: float = 0) -> Antwort:
        gesehen.append(dict(req.header_items()))
        return Antwort()

    monkeypatch.setenv("FYOS_VORGAENGE_KOPF", "X-FYOS-Pane-Auth: innen")
    p = _plugin(vorgaenge_url="http://tickets.example/api")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert p._vd("GET", "/tickets?limit=1") == {"tickets": []}
    assert gesehen[0]["X-fyos-pane-auth"] == "innen"


# ── Workboard ───────────────────────────────────────────────────────────────────────────────────


def test_workboard_als_quelle_traegt_den_vertrag():
    brett = Werkbrett()
    p = _plugin(rpc_aufruf=brett)
    VG.ablage_anmelden(p)
    q = VG.quelle()
    t = q.anlegen("Backup prüfen", "nachts", status="waiting_approval", priority="p1", actor="agent")
    assert t["id"].startswith("WB-") and t["status"] == "waiting_approval" and t["priority"] == "urgent"
    q.anlegen("Neues Gerät", status="new")
    assert [x["id"] for x in q.freigaben()] == [t["id"]]
    assert {x["status"] for x in q.offen()} == {"waiting_approval", "new"}
    assert len(q.liste("new,waiting_approval", grenze=1)) == 2  # Grenze je Status
    q.kommentieren(t["id"], "ja, aber nach 22 Uhr", actor="besitzer")
    with pytest.raises(VorgangKonflikt) as konflikt:
        q.aendern(t["id"], status="in_progress", expected_status="triage")
    assert konflikt.value.vorgang["status"] == "waiting_approval"
    neu = q.aendern(t["id"], status="in_progress", expected_status="waiting_approval", actor="besitzer",
                    waiting_for="", assignee="agent")  # was das Workboard nicht kennt, fällt weg
    assert neu["status"] == "in_progress" and q.holen(t["id"])["status"] == "in_progress"
    karte = brett.karten[t["karte"]]
    assert [c["body"] for c in karte["metadata"]["comments"]] == [
        "besitzer: ja, aber nach 22 Uhr", "besitzer: Status waiting_approval → in_progress"]
    # der Verlauf sind die Kommentare, neueste zuerst, Akteur und Text getrennt
    verlauf = q.verlauf(t["id"])
    assert [(e["event"], e["actor"], e["detail"]) for e in verlauf] == [
        ("comment", "besitzer", "Status waiting_approval → in_progress"), ("comment", "besitzer", "ja, aber nach 22 Uhr")]
    assert len(q.verlauf(t["id"], grenze=1)) == 1
    with pytest.raises(VorgangFehlt):
        q.verlauf("WB-00000000")
    with pytest.raises(VorgangFehlt):
        q.holen("WB-00000000")
    with pytest.raises(ValueError):
        q.liste("erledigt")
    with pytest.raises(ValueError):
        q.kommentieren(t["id"], "  ")


def test_workboard_roh_bildet_den_vertrag_nach_und_sagt_was_fehlt():
    p = _plugin(rpc_aufruf=Werkbrett())
    VG.ablage_anmelden(p)
    q = VG.quelle()
    status, d = q.roh("POST", "/tickets", {"title": "Druckerpapier", "status": "new"})
    assert status == 201 and d["ticket"]["status"] == "new"
    vid = d["ticket"]["id"]
    assert q.roh("GET", f"/tickets/{vid}")[1]["ticket"]["title"] == "Druckerpapier"
    assert q.roh("GET", "/tickets?status=new&limit=5")[1]["tickets"][0]["id"] == vid
    assert q.roh("POST", f"/tickets/{vid}/comments", {"actor": "agent", "text": "bestellt"})[0] == 200
    assert q.roh("PATCH", f"/tickets/{vid}", {"status": "resolved"})[1]["ticket"]["status"] == "resolved"
    assert q.roh("GET", "/tickets/WB-00000000")[0] == 404
    assert q.roh("PATCH", f"/tickets/{vid}", {"status": "erledigt"})[0] == 400
    status, d = q.roh("GET", f"/tickets/{vid}/history?limit=5")
    assert status == 200 and [(e["actor"], e["detail"]) for e in d["history"]] == [("agent", "bestellt")]
    status, d = q.roh("GET", "/waiting")
    assert status == 501 and "Workboard" in d["detail"]


def test_workboard_fehler_der_bruecke_werden_quellfehler():
    def kaputt(methode: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("Brücke nicht erreichbar (URLError)")

    VG.ablage_anmelden(_plugin(rpc_aufruf=kaputt))
    q = VG.quelle()
    with pytest.raises(QuelleFehler):
        q.liste()
    assert q.roh("GET", "/tickets")[0] == 502


# ── Dienst ──────────────────────────────────────────────────────────────────────────────────────


def test_dienst_liest_entpackt_und_schreibt_nur_vertragsfelder():
    d = Dienst()
    q = VG.Dienst("http://tickets.example/api", aufruf=d)
    assert [t["id"] for t in q.liste(["new", "waiting_approval"])] == ["INC-1", "CHG-2"]
    assert [t["id"] for t in q.freigaben()] == ["CHG-2"]
    assert q.holen("INC-1")["waiting_for"] == "besitzer"
    q.kommentieren("INC-1", "erledige ich", actor="besitzer")
    assert d.aufrufe[-1] == ("POST", "/tickets/INC-1/comments", {"actor": "besitzer", "text": "erledige ich"})
    neu = q.aendern("INC-1", status="in_progress", expected_status="new", actor="besitzer", waiting_for="")
    assert neu["status"] == "in_progress"
    assert d.aufrufe[-1][2] == {"status": "in_progress", "expected_status": "new", "actor": "besitzer"}
    assert q.anlegen("Neu", typ="INC")["id"] == "INC-3"
    assert q.verlauf("INC-1", grenze=5)[0]["actor"] == "besitzer"
    assert d.aufrufe[-1][:2] == ("GET", "/tickets/INC-1/history?limit=5")
    # was der Dienst über den Vertrag hinaus kann, reicht roh() durch
    assert q.roh("GET", "/tickets/INC-1/history")[1]["history"][0]["actor"] == "besitzer"


def test_dienst_fehler_werden_zu_klaren_ausnahmen():
    d = Dienst()
    q = VG.Dienst("http://tickets.example/api", aufruf=d)
    with pytest.raises(VorgangFehlt):
        q.holen("INC-99")
    with pytest.raises(VorgangKonflikt):
        q.aendern("INC-1", status="resolved", expected_status="triage")
    with pytest.raises(ValueError):
        q.holen("../geheim")
    d.kaputt = 503
    with pytest.raises(QuelleFehler) as fehler:
        q.liste()
    assert fehler.value.status == 503 and "wackelt" in str(fehler.value)


def test_dienst_ohne_netz_meldet_unerreichbar():
    q = VG.Dienst("http://127.0.0.1:9")  # Port 9 (discard) nimmt nichts an
    with pytest.raises(QuelleFehler) as fehler:
        q.liste()
    assert "nicht erreichbar" in str(fehler.value)
