"""ansicht — knappe und ausführliche Ansicht für Modelle."""

from __future__ import annotations

import json

import pytest

from mcp_hub import ansicht
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.plugin import HubPlugin, ToolDescriptor


@pytest.fixture(autouse=True)
def _ablage_im_speicher(monkeypatch):
    """Kein Redis im Test: die Ablage lebt im Speicher."""
    monkeypatch.setattr(ansicht, "ABLAGE", ansicht.Ablage(redis=None))
    ansicht.ABLAGE._redis_versucht = True  # noqa: SLF001
    yield


def _pods(n: int) -> dict:
    return {
        "ok": True,
        "satz": f"{n} Pods",
        "pods": [
            {"name": f"pod-{i}", "namespace": "fyos", "status": "Running" if i % 7 else "Failed",
             "neustarts": i % 3, "bild": "registry.local/x:" + "a" * 60, "labels": {"app": f"a{i}", "team": "fyos"},
             "beschreibung": "lang " * 80}
            for i in range(n)
        ],
    }


def test_kleine_ergebnisse_bleiben_unveraendert():
    voll = {"ok": True, "wert": 3}
    assert ansicht.kurz("x.y", {}, voll) == (voll, None)


def test_grosse_liste_wird_gekuerzt_und_bleibt_abrufbar():
    voll = _pods(120)
    gekuerzt, info = ansicht.kurz("cluster.pods", {}, voll, budget=3000)
    assert info and info["ansicht"] == "kurz"
    assert len(json.dumps(gekuerzt)) + len(json.dumps(info["listen"])) <= 3000
    assert gekuerzt["satz"] == "120 Pods"  # Skalare oben bleiben
    erster = gekuerzt["pods"][0]
    assert set(erster) <= {"name", "namespace", "status"}  # Kernfelder, keine Labels/Bilder
    assert gekuerzt["pods"][-1].startswith("… +")
    assert info["listen"]["pods"]["anzahl"] == 120
    assert "neustarts" in info["listen"]["pods"]["felder"]  # das Modell sieht, was es nachholen kann
    assert ansicht.abgelegt(info["ergebnis_id"])["voll"] == voll


def test_gleiche_feldlisten_nur_einmal():
    """verlauf.zustand nannte je Gruppe dieselben Felder (04.10.) — jetzt einmal, danach Verweis."""
    voll = {"gruppen": [{"name": f"g{i}", "kurven": _pods(12)["pods"]} for i in range(6)]}
    _, info = ansicht.kurz("verlauf.zustand", {}, voll, budget=4000, plugin_sicht={"gruppen": ["name", "kurven"]})
    kurven = {p: e for p, e in info["listen"].items() if p.endswith(".kurven")}
    listen_mit_feldern = [e for e in kurven.values() if isinstance(e["felder"], list)]
    assert len(listen_mit_feldern) == 1
    assert all(e["felder"] == "wie gruppen.0.kurven" for p, e in kurven.items() if p != "gruppen.0.kurven")


def test_mehr_filtert_projiziert_blaettert_und_lernt():
    voll = _pods(120)
    _, info = ansicht.kurz("cluster.pods", {}, voll, budget=3000)
    eintrag = ansicht.abgelegt(info["ergebnis_id"])
    r = ansicht.mehr(eintrag, pfad="pods", felder=["name", "neustarts"], filter_={"status": "fail"}, limit=5)
    assert r["treffer"] == len([p for p in voll["pods"] if p["status"] == "Failed"])
    assert r["eintraege"][0] == {"name": "pod-0", "neustarts": 0}
    assert r["weiter"] == 5
    # Zweite Nachfrage nach `neustarts` → ab jetzt Teil der kurzen Ansicht
    ansicht.mehr(eintrag, pfad="pods", felder=["neustarts"])
    gekuerzt, _ = ansicht.kurz("cluster.pods", {}, voll, budget=3000)
    assert "neustarts" in gekuerzt["pods"][0]


def test_merken_wirkt_sofort_und_pfad_mit_index_zaehlt_als_liste():
    assert ansicht.merken("cluster.pods", "pods.4", ["bild"])["pfad"] == "pods"
    gekuerzt, _ = ansicht.kurz("cluster.pods", {}, _pods(60), budget=4000)
    assert "bild" in gekuerzt["pods"][0]


def test_sicht_bericht_zeigt_herkunft_und_nachfragen():
    """04.10.: die MCP-App zeigt, was Modelle in der kurzen Ansicht sehen — mitgeliefert, gelernt, auf dem Weg."""
    leer = ansicht.sicht_bericht("cluster.pods")
    assert leer["felder"] == [] and "name" in leer["kern"] and leer["schwelle"] == ansicht.LERN_SCHWELLE
    ansicht.merken("cluster.pods", "pods.4", ["bild"])
    ansicht.lernen("cluster.pods", "pods", ["labels"])
    ansicht.lernen("cluster.pods", "pods", ["status"], gewicht=5)
    b = ansicht.sicht_bericht("cluster.pods", {"pods": ["status"]})
    assert [(e["feld"], e["herkunft"], e["nachfragen"]) for e in b["felder"]] == [
        ("status", "plugin", 5), ("bild", "gelernt", ansicht.LERN_SCHWELLE), ("labels", "lernt", 1)]
    assert b["budget"]["standard"] == ansicht.BUDGET and b["verfall_tage"] == 30


def test_messung_zaehlt_voll_kurz_und_nachgeholt_je_aufrufer():
    """Kritik 04.10.: die Ersparnis war ungemessen. Ohne Aufrufer (Tests, interne Wege) zählt nichts."""
    ansicht.kurz("cluster.pods", {}, _pods(80), budget=2000)
    assert ansicht.messung()["aufrufer"] == []
    _, info = ansicht.kurz("cluster.pods", {}, _pods(80), budget=2000, aufrufer="mcp:kleinmodell")
    ansicht.kurz("t.klein", {}, {"ok": True}, budget=2000, aufrufer="mcp:kleinmodell")
    ansicht.messen("mcp:kleinmodell", nachgeholt=500)
    m = ansicht.messung()
    z = m["aufrufer"][0]
    assert z["aufrufer"] == "mcp:kleinmodell" and z["aufrufe"] == 2 and z["gekuerzt"] == 1 and z["mehr"] == 1
    assert z["zeichen_voll"] == info["zeichen_voll"] + len('{"ok":true}') and z["zeichen_nachgeholt"] == 500
    assert 0 < z["zeichen_kurz"] < z["zeichen_voll"] and 50 < z["gespart_prozent"] < 100
    assert m["gesamt"]["aufrufe"] == 2 and m["gesamt"]["aufrufer"] == "alle"


def test_mehr_mit_falschem_pfad_sagt_es():
    _, info = ansicht.kurz("t.t", {}, _pods(80), budget=2000)
    r = ansicht.mehr(ansicht.abgelegt(info["ergebnis_id"]), pfad="gibtsnicht")
    assert r["ok"] is False and r["kind"] == "bad_request"


def test_budget_je_aufrufer(monkeypatch):
    monkeypatch.setattr(ansicht, "BUDGET_JE_AUFRUFER", {"kleinmodell": 3000, "claude": 6000})
    assert ansicht.budget_fuer("mcp:kleinmodell/1.2") == 3000
    assert ansicht.budget_fuer("mcp:claude-code") == 6000
    assert ansicht.budget_fuer("rest:unbekannt") == ansicht.BUDGET


def test_ohne_eintraege_gilt_ueberall_das_standardbudget():
    assert ansicht.BUDGET_JE_AUFRUFER == {}
    assert ansicht.budget_fuer("mcp:irgendwer") == ansicht.BUDGET


class _Gross(HubPlugin):
    name = "gross"
    version = "1"
    description = "liefert viel"

    def register(self):
        return None

    def describe_tools(self):
        return [ToolDescriptor(name="liste", description="Große Liste. Mehr Text.", input_schema={"type": "object"},
                               tags=["read"], meta={"kurz": {"pods": ["bild"]}})]

    def call(self, method, args):
        return _pods(150)

    def health(self):
        return {"status": "ok"}


@pytest.fixture
def reg(monkeypatch):
    r = hub_registry.PluginRegistry()
    hub_registry._register_one(r, "gross", _Gross())
    monkeypatch.setattr(hub_server, "get_registry", lambda: r)
    return r


def test_hub_call_tool_kurz_und_voll(reg):
    kurz = hub_server.hub__call_tool("gross.liste", {})
    assert kurz["ok"] and kurz["ansicht"]["ansicht"] == "kurz"
    assert "bild" in kurz["result"]["pods"][0]  # Sicht des Plugins (meta["kurz"])
    voll = hub_server.hub__call_tool("gross.liste", {}, ansicht="voll")
    assert len(voll["result"]["pods"]) == 150 and "ansicht" not in voll
    mehr = hub_server.hub__mehr(kurz["ansicht"]["ergebnis_id"], pfad="pods", suche="pod-149")
    assert mehr["treffer"] == 1
    assert hub_server.hub__mehr("0" * 16)["kind"] == "abgelaufen"


def test_hub_ansicht_merken_kennt_nur_echte_werkzeuge(reg):
    assert hub_server.hub__ansicht_merken("gibt.esnicht", ["a"])["kind"] == "not_found"
    assert hub_server.hub__ansicht_merken("gross.liste", ["neustarts"], "pods")["ok"]


def test_suche_kurz_rangiert_und_begrenzt(reg):
    r = hub_server.hub__search_tools("gross liste")
    assert r["tools"] == [{"name": "gross.liste", "kurz": "Große Liste.", "pflicht": [], "scope": "READ", "wert": 1.0}]
    teil = hub_server.hub__search_tools("gross nichtda")
    assert teil["teiltreffer"] is True and [t["name"] for t in teil["tools"]] == ["gross.liste"]
    assert hub_server.hub__search_tools("nichtda garnix")["count"] == 0
    assert "teiltreffer" not in r
    assert "inputSchema" in hub_server.hub__search_tools("gross", ansicht="voll")["tools"][0]


def test_suche_kennt_alltagswoerter_und_umlaute():
    # Alltagswörter führen über die Synonymtabelle auf die Wörter in den Werkzeugnamen.
    assert ansicht.treffer_wert("werkstatt.suchen", "Skripte finden", ["skript"]) == 3
    assert ansicht.treffer_wert("werkstatt.suchen", "", ["programm"]) == 3
    assert ansicht.treffer_wert("werkstatt.suchen", "", ["programm", "wetter"]) == 0
    assert ansicht.treffer_wert("werkstatt.suchen", "Grüße", ["grüße"]) == 1
    # Plugins ergänzen die Tabelle
    ansicht.SYNONYME["geld"] = ("kasse",)
    try:
        assert ansicht.treffer_wert("kasse.buchen", "", ["geld"]) == 3
    finally:
        del ansicht.SYNONYME["geld"]
    # Teiltreffer: mehr getroffene Wörter vor einem einzelnen Namenstreffer
    zwei = ansicht.treffer_wert("x.y", "Geld und Wetter", ["geld", "wetter", "mond"], teil=True)
    eins = ansicht.treffer_wert("kasse.y", "", ["kasse", "wetter", "mond"], teil=True)
    assert zwei > eins > 0
    assert ansicht.treffer_wert("x.y", "", ["mond"], teil=True) == 0
    # Füllwörter ganzer Fragen fallen weg — außer die Frage besteht nur aus ihnen
    assert ansicht.suchwoerter("Wo ist mein Skript") == ["skript"]
    assert ansicht.suchwoerter("wo ist") == ["wo", "ist"]


def test_rangliste_gilt_auch_fuer_rest(reg):
    treffer, teil = hub_server.rangliste(reg, "zeig mir die große liste")
    assert [t["name"] for t in treffer] == ["gross.liste"] and teil is False
    treffer, teil = hub_server.rangliste(reg, "liste mond")
    assert [t["name"] for t in treffer] == ["gross.liste"] and teil is True


class _Pflicht(HubPlugin):
    name = "pflicht"
    version = "1"
    description = "braucht ein Argument"

    def register(self):
        return None

    def describe_tools(self):
        return [ToolDescriptor(name="aufrufen", description="Ruft auf.", tags=["read"], input_schema={
            "type": "object", "properties": {"werkzeug": {"type": "string"}}, "required": ["werkzeug"]})]

    def call(self, method, args):
        return {"bekommen": args}

    def health(self):
        return {"status": "ok"}


def test_call_ohne_pflichtargumente_nennt_den_schluessel(reg):
    # Testreihe hb4 (06.10.): `args` statt `arguments` — das Plugin bekam {} und meldete Unsinn.
    hub_registry._register_one(reg, "pflicht", _Pflicht())
    r = hub_server.hub__call_tool("pflicht.aufrufen")
    assert r["ok"] is False and r["kind"] == "bad_arguments" and "arguments" in r["error"]
    assert hub_server.hub__call_tool("pflicht.aufrufen", {"werkzeug": "a"})["ok"] is True
