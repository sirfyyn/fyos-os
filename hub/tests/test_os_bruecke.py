"""OS-Bruecke (Protokoll v1): Meldungen, Befehle, Antworten und die drei HTTP-Wege."""

from __future__ import annotations

import pytest

from mcp_hub import os_bruecke as ob
from mcp_hub.os_bruecke import Bruecke

fakeredis = pytest.importorskip("fakeredis")


def meldung(sitzung="s-abc12345", **extra):
    return {"sitzung": sitzung, "geraet": "Laptop", "art": "computer", "version": 1, **extra}


@pytest.fixture
def bruecke() -> Bruecke:
    return Bruecke(redis=fakeredis.FakeRedis(decode_responses=True), basis_url="https://hub.example")


# ── reine Hilfen ────────────────────────────────────────────────────────────
def test_meldung_wird_bereinigt():
    m = ob.meldung_bereinigen(meldung(agent_vorne=True, art="unfug", seite="x" * 500))
    assert m["art"] == "computer" and m["agent_vorne"] is True and len(m["seite"]) <= 200


def test_meldung_ohne_objekt_oder_sitzung_scheitert():
    with pytest.raises(ValueError):
        ob.meldung_bereinigen([1])
    with pytest.raises(ValueError):
        ob.meldung_bereinigen({"geraet": "x"})


def test_ziele():
    assert ob.ziel_normalisieren("App:Meine_App.zeigen") == "app:meine_app__zeigen"
    assert ob.ziel_normalisieren("Agent") == "agent"
    assert ob.ziel_normalisieren("Uebersicht") == "Uebersicht"
    assert ob.ziel_normalisieren("meine_app.zeigen", lambda f: f == "meine_app.zeigen") == "app:meine_app__zeigen"
    with pytest.raises(ValueError):
        ob.ziel_normalisieren("  ")


def test_deeplink():
    assert ob.deeplink("app:x__y", basis="https://hub.example") == "https://hub.example/os?offen=app:x__y"
    assert ob.deeplink("Uebersicht", basis="https://hub.example") is None
    assert "eingabe=" in ob.deeplink("app:x__y", {"a": 1}, basis="https://hub.example")


def test_sse_ereignis():
    assert ob.sse_ereignis("befehl", {"a": 1}, "5-0") == 'id: 5-0\nevent: befehl\ndata: {"a":1}\n\n'


def test_agent_erkennung(bruecke):
    assert bruecke.ist_agent("agent") and bruecke.ist_agent("agent-2")
    assert not bruecke.ist_agent("shell") and not bruecke.ist_agent("mcp:codex")


# ── Sitzungen, Befehle, Antworten ───────────────────────────────────────────
def test_melden_und_lage(bruecke):
    erg = bruecke.melden(meldung())
    assert erg["ok"] and erg["ablauf_s"] == 90 and erg["sitzungen"] == 1
    assert [s["sitzung"] for s in bruecke.sitzungen()] == ["s-abc12345"]
    bruecke.melden({"sitzung": "s-abc12345", "ende": True})
    assert bruecke.sitzungen() == []


def test_befehl_hin_antwort_zurueck(bruecke):
    bruecke.melden(meldung())
    befehl = {"art": "zeigen", "id": "b-1a2b3c4d5e6f", "ziel": "app:x__y"}
    eid = bruecke.senden("s-abc12345", befehl)
    befehle, nach = bruecke.abholen("s-abc12345")
    assert [b["id"] for b in befehle] == ["b-1a2b3c4d5e6f"] and nach == eid
    assert bruecke.antwort_ablegen({"sitzung": "s-abc12345", "befehl": "b-1a2b3c4d5e6f", "ok": True, "ergebnis": {"x": 1}}) == {"ok": True}
    assert bruecke.warten("b-1a2b3c4d5e6f", 1)["ok"] is True


def test_fremde_sitzung_darf_nicht_antworten(bruecke):
    bruecke.melden(meldung())
    bruecke.senden("s-abc12345", {"art": "zeigen", "id": "b-1a2b3c4d5e6f", "ziel": "agent"})
    with pytest.raises(ValueError, match="anderen Sitzung"):
        bruecke.antwort_ablegen({"sitzung": "s-fremd9999", "befehl": "b-1a2b3c4d5e6f", "ok": True})
    with pytest.raises(ValueError, match="unbekannt"):
        bruecke.antwort_ablegen({"sitzung": "s-abc12345", "befehl": "b-000000000000", "ok": True})


# ── HTTP ────────────────────────────────────────────────────────────────────
def test_http_wege(bruecke):
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    ob.setze_standard(bruecke)
    try:
        client = TestClient(Starlette(routes=ob.os_routen()))
        assert client.post("/hub/os/melden", json=meldung()).json()["ok"] is True
        assert client.post("/hub/os/melden", content="kein json").status_code == 400
        assert client.post("/hub/os/antwort", json={"sitzung": "s-abc12345", "befehl": "b-000000000000"}).status_code == 400
        assert client.get("/hub/os/strom").status_code == 400  # ohne Sitzung
        assert client.get("/hub/os/melden").status_code == 405
    finally:
        ob.setze_standard(None)
