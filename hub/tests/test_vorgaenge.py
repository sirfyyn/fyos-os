"""Vorgänge für Plugins (``mcp_hub.vorgaenge``): Dienst, Ablage eines Plugins oder keine Quelle — ohne Netz."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_hub import vorgaenge as VG
from mcp_hub.vorgaenge import NichtEingerichtet, QuelleFehler, VorgangFehlt, VorgangKonflikt


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


class Ablage:
    """Eine Ablage im Speicher, wie ein Plugin sie mit ``ablage_anmelden`` anbietet."""

    def __init__(self) -> None:
        self.vorgaenge: dict[str, dict[str, Any]] = {}
        self.kommentare: dict[str, list[dict[str, Any]]] = {}
        self.kaputt = False

    def _pruefe(self) -> None:
        if self.kaputt:
            raise RuntimeError("Ablage nicht erreichbar")

    def ablage_liste(self, status: str = "", grenze: int = 50) -> list[dict[str, Any]]:
        self._pruefe()
        return list(self.vorgaenge.values())[:grenze]

    def ablage_holen(self, vid: str) -> dict[str, Any] | None:
        self._pruefe()
        return self.vorgaenge.get(vid)

    def ablage_anlegen(self, koerper: dict[str, Any]) -> dict[str, Any]:
        vid = f"AB-{len(self.vorgaenge) + 1}"
        self.vorgaenge[vid] = {"id": vid, **koerper}
        return self.vorgaenge[vid]

    def ablage_kommentieren(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        if vid not in self.vorgaenge:
            raise VorgangFehlt(vid)
        self.kommentare.setdefault(vid, []).insert(0, {"event": "comment", "actor": koerper["actor"], "detail": koerper["text"]})
        return {"ok": True}

    def ablage_aendern(self, vid: str, koerper: dict[str, Any]) -> dict[str, Any]:
        v = self.vorgaenge.get(vid)
        if v is None:
            raise VorgangFehlt(vid)
        if koerper.get("expected_status") and koerper["expected_status"] != v["status"]:
            raise VorgangKonflikt("status_conflict", v)
        v.update({k: w for k, w in koerper.items() if k in ("status", "title")})
        return v

    def ablage_verlauf(self, vid: str, grenze: int = 20) -> list[dict[str, Any]]:
        return self.kommentare.get(vid, [])[:grenze]


def test_eine_angemeldete_ablage_ist_die_quelle_und_ein_dienst_hat_vorrang():
    ablage = Ablage()
    VG.ablage_anmelden(ablage)
    q = VG.quelle()
    assert q.art == "ablage" and q.eingerichtet
    assert VG.quelle(url="http://tickets.example").art == "dienst"
    VG.dienst_anmelden("http://tickets.example/api/", {"X-Innen": "ja"})
    q = VG.quelle()
    assert (q.art, q.url, q.kopf) == ("dienst", "http://tickets.example/api", {"X-Innen": "ja"})
    VG.dienst_anmelden(None)
    VG.ablage_anmelden(None)
    assert VG.quelle().art == "keine"


def test_ablage_traegt_den_vertrag():
    VG.ablage_anmelden(Ablage())
    q = VG.quelle()
    t = q.anlegen("Backup prüfen", "nachts", status="waiting_approval", actor="agent")
    q.anlegen("Neues Gerät", status="new")
    assert [x["id"] for x in q.freigaben()] == [t["id"]]
    assert {x["status"] for x in q.offen()} == {"waiting_approval", "new"}
    q.kommentieren(t["id"], "ja, aber nach 22 Uhr", actor="besitzer")
    with pytest.raises(VorgangKonflikt):
        q.aendern(t["id"], status="in_progress", expected_status="triage")
    assert q.aendern(t["id"], status="in_progress", expected_status="waiting_approval")["status"] == "in_progress"
    assert q.verlauf(t["id"])[0]["detail"] == "ja, aber nach 22 Uhr"
    with pytest.raises(VorgangFehlt):
        q.holen("AB-99")
    with pytest.raises(ValueError):
        q.kommentieren(t["id"], "  ")
    status, d = q.roh("GET", "/tickets?status=new&limit=5")
    assert status == 200 and d["quelle"] == "ablage" and d["tickets"][0]["title"] == "Neues Gerät"
    status, d = q.roh("GET", "/waiting")
    assert status == 501 and "Ablage" in d["detail"]


def test_fehler_der_ablage_werden_quellfehler():
    ablage = Ablage()
    ablage.kaputt = True
    VG.ablage_anmelden(ablage)
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
