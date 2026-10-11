"""„Lebt der Agent?“: Herzschlag, Sitzungen, Fortschrittskarten je Vorgang, Urteil."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_hub.plugins import _lebendig as L
from tests.test_openclaw import _plugin, _sonde

JETZT = 1791718400.0


def _sitzung(schluessel: str, **extra: Any) -> dict[str, Any]:
    return {"key": schluessel, "classification": "direct", "updatedAt": 1791718300000, **extra}


def test_herzschlag_alter_und_felder():
    h = L.herzschlag_aus({"ts": 1791718383920, "status": "ok-empty", "reason": "wake", "silent": True, "durationMs": 9407}, JETZT)
    assert h == {"zeit_ms": 1791718383920, "alter_s": 16, "status": "ok-empty", "grund": "wake", "still": True, "dauer_ms": 9407}
    assert L.herzschlag_aus({}, JETZT) is None and L.herzschlag_aus(None, JETZT) is None


def test_sitzung_erkennt_den_vorgang_am_schluessel():
    s = L.sitzung_aus(_sitzung("agent:main:vorgang:wb-1a2b3c4d", status="done", endedAt=1791718350000))
    assert s["vorgang"] == "WB-1A2B3C4D" and s["status"] == "done" and s["beendet_ms"] == 1791718350000
    assert L.sitzung_aus(_sitzung("agent:main:main"))["vorgang"] is None
    assert L.sitzung_aus({"status": "x"}) is None and L.sitzung_aus("x") is None


def test_fehler_der_sitzung_wird_gekuerzt():
    s = L.sitzung_aus(_sitzung("agent:main:main", status="failed", lastRunError="x " * 400))
    assert len(s["fehler"]) <= L.FEHLER_MAX


def test_karte_mit_schritten_notiz_und_aktuellem_schritt():
    k = L.karte_aus({"card": {"revision": 4, "updatedAt": 1791718300000, "markdown": "Zweiter Schritt\n\nläuft",
                              "plan": [{"step": "Prüfen", "status": "completed"}, {"step": "Ändern", "status": "in_progress"},
                                       {"step": "Testen", "status": "pending"}]}})
    assert k == {"revision": 4, "aktualisiert_ms": 1791718300000, "schritte": {"fertig": 1, "gesamt": 3}, "aktuell": "Ändern",
                 "notiz": "Zweiter Schritt läuft"}


@pytest.mark.parametrize("roh", [None, {"card": None}, {"card": {}}, {}, "x", []])
def test_ohne_karte_none(roh):
    assert L.karte_aus(roh) is None


def test_karte_nur_notiz_ohne_plan():
    k = L.karte_aus({"card": {"markdown": "nur eine Notiz"}})
    assert k["schritte"] is None and k["aktuell"] is None and k["notiz"] == "nur eine Notiz"


def test_urteil_gestoert_laeuft_bereit():
    fertig = {"schluessel": "agent:main:main", "status": "done", "beendet_ms": 5, "aktiv": False}
    kaputt = {"schluessel": "agent:main:vorgang:INC-1", "status": "failed", "beendet_ms": 9, "aktiv": False, "fehler": "HTTP 500"}
    assert L.urteil(True, [fertig]) == ("bereit", [])
    assert L.urteil(True, [{**fertig, "aktiv": True}])[0] == "laeuft"
    z, g = L.urteil(True, [fertig, kaputt])
    assert z == "gestoert" and "INC-1" in g[0] and "HTTP 500" in g[0]
    assert L.urteil(False, [fertig]) == ("gestoert", ["Gateway nicht bereit"])
    assert L.urteil(None, []) == ("bereit", [])


def test_alter_fehler_haelt_nicht_fuer_immer_gestoert():
    alt = {"schluessel": "agent:main:main", "status": "failed", "beendet_ms": 5, "aktiv": False}
    neu = {"schluessel": "agent:main:vorgang:INC-2", "status": "done", "beendet_ms": 9, "aktiv": False}
    assert L.urteil(True, [alt, neu])[0] == "bereit"


def _rpc(sitzungen: list[dict[str, Any]], karten: dict[str, Any], aufrufe: list[tuple[str, Any]] | None = None):
    def rpc(methode: str, params: dict[str, Any]) -> Any:
        if aufrufe is not None:
            aufrufe.append((methode, params))
        if methode == "last-heartbeat":
            return {"ts": 1791718383920, "status": "ok-empty", "reason": "wake", "silent": True, "durationMs": 100}
        if methode == "sessions.list":
            return {"sessions": sitzungen}
        if methode == "progressCard.get":
            return {"card": karten.get(params["sessionKey"])}
        raise RuntimeError(f"unbekannt {methode}")
    return rpc


SITZUNGEN = [
    _sitzung("agent:main:main", status="done", endedAt=1791718000000),
    _sitzung("agent:main:vorgang:inc-1", status="done", endedAt=1791718350000, updatedAt=1791718350000),
    _sitzung("agent:main:vorgang:inc-2", status="running", hasActiveRun=True, updatedAt=1791718390000),
]
KARTEN = {"agent:main:vorgang:inc-2": {"revision": 2, "plan": [{"step": "Lesen", "status": "completed"}, {"step": "Antworten", "status": "in_progress"}],
                                      "markdown": "bald fertig"}}


def test_lebt_zeigt_vorgangssitzungen_mit_karte():
    aufrufe: list[tuple[str, Any]] = []
    e = _plugin(rpc_aufruf=_rpc(SITZUNGEN, KARTEN, aufrufe)).call("lebt", {})
    assert e["zustand"] == "laeuft" and e["aktiv"] == 1 and e["sitzungen_gesamt"] == 3
    assert [v["vorgang"] for v in e["vorgaenge"]] == ["INC-2", "INC-1"], "jüngste zuerst"
    assert e["vorgaenge"][0]["karte"]["aktuell"] == "Antworten" and e["vorgaenge"][1]["karte"] is None
    assert e["herzschlag"]["status"] == "ok-empty" and e["fehler"] == []
    assert ("progressCard.get", {"sessionKey": "agent:main:vorgang:inc-2"}) in aufrufe, "Schlüssel wie OpenClaw ihn führt"


def test_lebt_mit_vorgang_filtert_und_meldet_fehlende_sitzung():
    p = _plugin(rpc_aufruf=_rpc(SITZUNGEN, KARTEN))
    e = p.call("lebt", {"vorgang": "inc-2"})
    assert [v["vorgang"] for v in e["vorgaenge"]] == ["INC-2"]
    leer = p.call("lebt", {"vorgang": "INC-9"})
    assert leer["vorgaenge"] == [] and "Keine Sitzung zu INC-9" in leer["satz"]
    with pytest.raises(ValueError, match="Vorgangsnummer"):
        p.call("lebt", {"vorgang": "bitte alles"})


def test_lebt_meldet_stoerung_mit_grund_und_haelt_den_rest():
    kaputt = [_sitzung("agent:main:main", status="failed", endedAt=1791718000000, lastRunError="modell/gross request failed (HTTP 500)")]
    e = _plugin(rpc_aufruf=_rpc(kaputt, {})).call("lebt", {})
    assert e["zustand"] == "gestoert" and "HTTP 500" in e["satz"]


def test_lebt_bei_gateway_nicht_bereit():
    e = _plugin(rpc_aufruf=_rpc([], {}), http_get=_sonde(bereit=False)).call("lebt", {})
    assert e["zustand"] == "gestoert" and e["gruende"] == ["Gateway nicht bereit"]


def test_lebt_ueberlebt_ausfall_einzelner_abfragen():
    def rpc(methode: str, params: dict[str, Any]) -> Any:
        if methode == "sessions.list":
            return {"sessions": SITZUNGEN}
        raise RuntimeError("Brücke nicht erreichbar")

    e = _plugin(rpc_aufruf=rpc).call("lebt", {})
    assert e["herzschlag"] is None and e["zustand"] == "laeuft"
    assert any("Herzschlag" in f for f in e["fehler"]) and any("Karte INC-2" in f for f in e["fehler"])


def test_lebt_ohne_kopplung():
    e = _plugin(gateway_url="", rpc_aufruf=None).call("lebt", {})
    assert e["zustand"] == "aus"
