"""Laufprofile: Listen, Erkennen an der Nutzlast, Vorlage für Cron-Aufträge, Werkzeuge ``profile`` und ``auftrag_vorlage``."""

from __future__ import annotations

import shlex

import pytest

from mcp_hub.plugins import _laufprofile as LP
from tests.test_openclaw import Werkbrett, _plugin


def test_profile_wachsen_vom_kleinen_zum_grossen():
    lesen, reflexion, melden = (set(LP.werkzeugliste(n)) for n in LP.REIHENFOLGE)
    assert lesen < reflexion < melden
    assert "message" in melden and "message" not in reflexion
    assert {"workboard_comment", "hub__hub__call_tool", "hub__gui__bauen"} <= reflexion
    assert not ({"workboard_comment", "hub__hub__call_tool"} & lesen)


def test_kein_profil_enthaelt_schreibende_dateiwege_oder_platzhalter():
    for n in LP.REIHENFOLGE:
        liste = LP.werkzeugliste(n)
        assert len(liste) == len(set(liste)), "doppelte Namen"
        assert not set(liste) & set(LP.VERBOTEN_IN_PROFILEN)
        assert all(isinstance(x, str) and x and " " not in x for x in liste)


def test_jedes_profil_kann_dateien_lesen_und_den_hub_erkunden():
    for n in LP.REIHENFOLGE:
        liste = LP.werkzeugliste(n)
        assert {"read", "dir_list", "file_fetch", "memory_search", "hub__hub__search_tools", "hub__hub__schema"} <= set(liste)


def test_unbekanntes_profil():
    with pytest.raises(LP.ProfilFehler):
        LP.werkzeugliste("alles")


def test_erkennen_an_der_nutzlast():
    assert LP.erkenne(None) == "alle"
    assert LP.erkenne(["*"]) == "alle"
    assert LP.erkenne([]) == "keine"
    assert LP.erkenne(["read", "exec"]) == "eigene"
    assert LP.erkenne("read") == "eigene"
    for n in LP.REIHENFOLGE:
        assert LP.erkenne(list(reversed(LP.werkzeugliste(n)))) == n


def _job(name, nutz, **extra):
    return {"id": f"id-{name}", "name": name, "enabled": True, "payload": nutz, **extra}


def test_pruefen_ordnet_auftraege_und_verraet_keine_nachricht():
    jobs = [
        _job("wache", {"kind": "agentTurn", "message": "GEHEIMER TEXT", "toolsAllow": []}),
        _job("rueckblick", {"kind": "agentTurn", "message": "x", "toolsAllow": LP.werkzeugliste("reflexion")}),
        _job("frei", {"kind": "agentTurn", "message": "x"}),
        _job("traum", {"kind": "agentTurn", "message": "x", "toolsAllow": ["*"]}, declarationKey="memory-core:dreaming"),
        _job("herzschlag", {}, declarationKey="heartbeat:main", enabled=False),
        _job("skript", {"kind": "systemEvent", "text": "x"}),
        _job("eigen", {"kind": "agentTurn", "message": "x", "toolsAllow": ["read", "exec"]}),
        _job("eigen-aus", {"kind": "agentTurn", "message": "x", "toolsAllow": ["exec"]}, enabled=False),
    ]
    s = LP.pruefen(jobs)
    assert {z["name"]: z["profil"] for z in s["auftraege"]} == {
        "wache": "keine", "rueckblick": "reflexion", "frei": "alle", "traum": "verwaltet",
        "herzschlag": "verwaltet", "skript": "ohne Modell", "eigen": "eigene", "eigen-aus": "eigene"}
    assert s["je_profil"]["eigene"] == 2
    assert s["ohne_profil"] == ["frei", "eigen"], "nur eingeschaltete Aufträge ohne Profil"
    assert "GEHEIMER" not in repr(s)


def test_vorlage_baut_befehl_und_nutzlast():
    v = LP.vorlage("lesen", "Wochenblick", "Liste den Ordner 'berichte'; fasse zusammen.", {"cron": "0 7 * * 1", "zeitzone": "Europe/Berlin"})
    teile = shlex.split(v["befehl"])
    assert teile[:3] == ["openclaw", "cron", "add"]
    assert teile[teile.index("--name") + 1] == "Wochenblick"
    assert teile[teile.index("--cron") + 1] == "0 7 * * 1"
    assert teile[teile.index("--tz") + 1] == "Europe/Berlin"
    assert teile[teile.index("--session") + 1] == "isolated"
    assert teile[teile.index("--tools") + 1].split(",") == LP.werkzeugliste("lesen")
    assert teile[teile.index("--message") + 1] == "Liste den Ordner 'berichte'; fasse zusammen."
    assert "--no-deliver" in teile and "--light-context" in teile and "--agent" not in teile
    assert v["auftrag"]["payload"]["toolsAllow"] == LP.werkzeugliste("lesen")
    assert v["auftrag"]["delivery"] == {"mode": "none"}


def test_vorlage_mit_agent_und_fester_sitzung():
    v = LP.vorlage("melden", "Nachsehen", "Sieh nach.", {"alle": "6h"}, agent="wache", sitzung="agent:wache:vorgang:INC-1")
    teile = shlex.split(v["befehl"])
    assert teile[teile.index("--agent") + 1] == "wache"
    assert teile[teile.index("--session-key") + 1] == "agent:wache:vorgang:INC-1" and "--session" not in teile
    assert teile[teile.index("--every") + 1] == "6h"
    assert v["auftrag"]["sessionKey"] == "agent:wache:vorgang:INC-1" and "sessionTarget" not in v["auftrag"]


@pytest.mark.parametrize("plan", [
    {}, {"cron": "0 7 * * *", "alle": "1h"}, {"cron": "0 7 * * *; rm -rf /"}, {"alle": "$(x)"}, {"alle": "x" * 90},
    {"alle": "1h", "zeitzone": "Europe/Berlin; x"}, "taeglich",
])
def test_vorlage_weist_schlechte_plaene_ab(plan):
    with pytest.raises(LP.ProfilFehler):
        LP.vorlage("lesen", "x", "y", plan)


@pytest.mark.parametrize("name,text", [("", "y"), ("x" * 81, "y"), ("x", ""), ("x", "y" * 8001)])
def test_vorlage_weist_schlechte_angaben_ab(name, text):
    with pytest.raises(LP.ProfilFehler):
        LP.vorlage("lesen", name, text, {"alle": "1h"})


def test_nachricht_bleibt_ein_einziges_argument():
    v = LP.vorlage("lesen", "n", 'a" ; echo böse $(x) `y` \n zweite Zeile', {"alle": "1h"})
    teile = shlex.split(v["befehl"])
    assert teile[teile.index("--message") + 1] == 'a" ; echo böse $(x) `y` \n zweite Zeile'


def test_werkzeug_profile_liest_die_auftraege_des_agenten():
    brett = Werkbrett()
    brett.cron = [_job("wache", {"kind": "agentTurn", "message": "x", "toolsAllow": []}),
                  _job("frei", {"kind": "agentTurn", "message": "x"})]
    p = _plugin(rpc_aufruf=brett)
    e = p.call("profile", {})
    assert [x["name"] for x in e["profile"]] == ["lesen", "reflexion", "melden"]
    assert e["ohne_profil"] == ["frei"] and e["je_profil"] == {"keine": 1, "alle": 1}
    assert "1 laufende Aufträge ohne Profil: frei" in e["satz"]


def test_werkzeug_profile_ohne_gateway_zeigt_trotzdem_die_profile():
    p = _plugin(rpc_aufruf=lambda m, params: (_ for _ in ()).throw(RuntimeError("Brücke nicht erreichbar")))
    e = p.call("profile", {})
    assert len(e["profile"]) == 3 and e["auftraege"] == [] and "nicht erreichbar" in e["fehler"]


def test_werkzeug_auftrag_vorlage_und_fehler():
    p = _plugin()
    v = p.call("auftrag_vorlage", {"profil": "reflexion", "name": "Rückblick", "text": "Blicke zurück.",
                                   "plan": {"cron": "0 21 * * *"}})
    assert v["profil"] == "reflexion" and "--tools" in shlex.split(v["befehl"])
    with pytest.raises(ValueError, match="plan"):
        p.call("auftrag_vorlage", {"profil": "lesen", "name": "n", "text": "t", "plan": {}})
    with pytest.raises(ValueError, match="Laufprofil"):
        p.call("auftrag_vorlage", {"profil": "voll", "name": "n", "text": "t", "plan": {"alle": "1h"}})
