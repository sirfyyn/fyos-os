"""Gedächtnis: Recall-Weg ``erinnern`` (Gedächtnis des Agenten + Dokumente, gemischt, gemessen) und Stand ``gedaechtnis``."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_hub import dokumente
from mcp_hub.plugins import _gedaechtnis as G
from tests.test_openclaw import _plugin

SUCHE = {
    "agentId": "main", "provider": "none", "searchMode": "fts-only",
    "results": [
        {"path": "memory/dreaming/light/2026-10-10.md", "startLine": 1, "endLine": 34, "score": 0.9651,
         "snippet": "# Light Sleep\n\n- Candidate: Öffne bitte den Notizzettel.", "source": "memory"},
        {"path": "memory/notizen.md", "startLine": 3, "endLine": 5, "score": 0.5, "snippet": "Einkaufsliste", "source": "memory"},
    ],
}
STATUS = {
    "agentId": "main", "provider": "openai",
    "embedding": {"ok": False, "checked": False, "error": "nicht geprüft"},
    "dreaming": {
        "enabled": True, "shortTermCount": 11, "totalSignalCount": 11, "promotedTotal": 2, "promotedToday": 1,
        "shortTermEntries": [{"snippet": "GEHEIMER AUSZUG"}], "signalEntries": [{"snippet": "GEHEIMER AUSZUG"}],
        "phases": {"light": {"enabled": True, "cron": "0 3 * * *", "nextRunAtMs": 1791774000000, "managedCronPresent": True},
                   "deep": {"enabled": False, "cron": "0 4 * * *"}},
    },
}


def test_treffer_aus_dem_gedaechtnis_tragen_verweis_und_kurzen_auszug():
    treffer, kopf = G.treffer_aus_gedaechtnis(SUCHE)
    assert kopf == {"anbieter": "none", "modus": "fts-only"}
    assert treffer[0]["verweis"] == "memory/dreaming/light/2026-10-10.md:1-34"
    assert treffer[0]["titel"] == "2026-10-10.md" and treffer[0]["quelle"] == "gedaechtnis"
    assert "\n" not in treffer[0]["auszug"] and treffer[0]["punkte"] == 0.9651
    lang = G.treffer_aus_gedaechtnis({"results": [{"path": "a.md", "snippet": "x" * 1000}]})[0][0]
    assert len(lang["auszug"]) <= G.AUSZUG_MAX


@pytest.mark.parametrize("roh", [None, "text", [], {"results": "x"}, {"results": [None, 3, "x"]}])
def test_gedaechtnis_antwort_ohne_treffer_ist_leer(roh):
    assert G.treffer_aus_gedaechtnis(roh)[0] == []


def test_treffer_aus_dokumenten():
    antwort = {"gesamt": 2, "dokumente": [{"id": 7, "titel": "Rechnung März", "auszug": "Betrag", "typ": "Rechnung", "link": "http://d/7"},
                                          {"titel": "ohne Kennung"}]}
    t = G.treffer_aus_dokumenten(antwort)
    assert t == [{"quelle": "dokumente", "verweis": "dokument:7", "titel": "Rechnung März", "auszug": "Betrag",
                  "link": "http://d/7", "punkte": None, "art": "Rechnung"}]


def test_mischen_nach_rang_und_gleiche_treffer_zaehlen_einmal():
    a = [{"quelle": "gedaechtnis", "verweis": "a"}, {"quelle": "gedaechtnis", "verweis": "b"}]
    b = [{"quelle": "dokumente", "verweis": "d1"}, {"quelle": "gedaechtnis", "verweis": "b"}]
    m = G.mischen([a, b], 10)
    # b steht in beiden Listen und gewinnt; a und d1 sind Rang 1 und gleichauf (dann entscheidet der Schlüssel)
    assert [t["verweis"] for t in m] == ["b", "d1", "a"]
    assert len(m) == 3 and m[0]["rang_punkte"] > m[1]["rang_punkte"]
    assert len(G.mischen([a, b], 2)) == 2


def test_erinnern_misst_jeden_weg_und_vermerkt_ausfaelle():
    def kaputt(f, n):
        raise RuntimeError("Dienst weg")

    e = G.erinnern("Notizzettel", 5, {"gedaechtnis": lambda f, n: SUCHE, "dokumente": kaputt})
    assert e["messung"]["gedaechtnis"]["ok"] and e["messung"]["gedaechtnis"]["anzahl"] == 2
    assert e["messung"]["gedaechtnis"]["modus"] == "fts-only"
    assert e["messung"]["dokumente"]["ok"] is False and "Dienst weg" in e["messung"]["dokumente"]["grund"]
    assert "gesamt_ms" in e["messung"] and e["satz"] == "2 Treffer aus gedaechtnis."


def test_erinnern_ohne_wege_und_ohne_frage():
    e = G.erinnern("x", 5, {})
    assert e["treffer"] == [] and e["satz"] == "Kein Weg des Gedächtnisses erreichbar."
    assert all(m["grund"] == "nicht eingerichtet" for n, m in e["messung"].items() if n != "gesamt_ms")
    with pytest.raises(ValueError, match="frage"):
        G.erinnern("  ", 5, {})


def test_limit_wird_begrenzt():
    gesehen: list[int] = []
    G.erinnern("x", 999, {"gedaechtnis": lambda f, n: gesehen.append(n) or {}})
    G.erinnern("x", 0, {"gedaechtnis": lambda f, n: gesehen.append(n) or {}})
    assert gesehen == [G.LIMIT_MAX, 8]


def test_stand_ohne_die_auszuege():
    s = G.stand_aus(STATUS)
    assert s["anbieter"] == "openai" and s["embedding"] == {"ok": False, "geprueft": False, "fehler": "nicht geprüft"}
    assert s["dreaming"]["kurzzeit"] == 11 and s["dreaming"]["uebernommen"] == 2
    assert s["dreaming"]["phasen"]["light"] == {"an": True, "zeitplan": "0 3 * * *", "naechster_lauf_ms": 1791774000000, "verwaltet": True}
    assert s["dreaming"]["phasen"]["deep"]["an"] is False
    assert "GEHEIMER" not in repr(s)
    assert G.stand_aus(None) == {}


class _Ablage:
    name = "probe"

    def ablage_neueste(self, anzahl):
        return {"dokumente": []}

    def ablage_suchen(self, abfrage, anzahl):
        return {"gesamt": 1, "dokumente": [{"id": 3, "titel": f"Treffer zu {abfrage}", "auszug": "Auszug"}]}

    def ablage_holen(self, id):  # noqa: A002
        return {}


@pytest.fixture
def mit_dokumenten():
    dokumente.ablage_anmelden(_Ablage())
    yield
    dokumente.ablage_anmelden(None)


def _rufe_aus(brett: dict[str, Any]):
    def rpc(methode: str, params: dict[str, Any]) -> Any:
        brett.setdefault("aufrufe", []).append((methode, params))
        if methode == "memory.search":
            return SUCHE
        if methode == "doctor.memory.status":
            return STATUS
        raise RuntimeError(f"unbekannt {methode}")
    return rpc


def test_werkzeug_erinnern_mischt_gedaechtnis_und_dokumente(mit_dokumenten):
    brett: dict[str, Any] = {}
    p = _plugin(rpc_aufruf=_rufe_aus(brett))
    e = p.call("erinnern", {"frage": "Notizzettel", "limit": 3})
    assert {t["quelle"] for t in e["treffer"]} == {"gedaechtnis", "dokumente"}
    assert brett["aufrufe"] == [("memory.search", {"query": "Notizzettel", "maxResults": 3})]
    assert e["messung"]["dokumente"]["anzahl"] == 1 and e["messung"]["gedaechtnis"]["anbieter"] == "none"


def test_erinnern_ohne_dokumentenquelle_nur_gedaechtnis():
    brett: dict[str, Any] = {}
    e = _plugin(rpc_aufruf=_rufe_aus(brett)).call("erinnern", {"frage": "Notizzettel"})
    assert e["messung"]["dokumente"]["grund"] == "nicht eingerichtet" and len(e["treffer"]) == 2


def test_erinnern_traegt_die_agentenkennung_mit():
    brett: dict[str, Any] = {}
    _plugin(rpc_aufruf=_rufe_aus(brett), agent="wache").call("erinnern", {"frage": "x"})
    assert brett["aufrufe"][0][1]["agentId"] == "wache"


def test_erinnern_zaehlt_und_misst_in_den_kennzahlen(mit_dokumenten):
    p = _plugin(rpc_aufruf=_rufe_aus({}))
    p.call("erinnern", {"frage": "Rechnung"})
    p.call("erinnern", {"frage": "Notizzettel"})
    proben = {(x["name"], tuple(sorted((x.get("labels") or {}).items()))): x["wert"] for x in p.metrics()["_proben"]}
    assert proben[("fyos_openclaw_erinnern_total", (("ergebnis", "ok"), ("weg", "gedaechtnis")))] == 2
    assert proben[("fyos_openclaw_erinnern_total", (("ergebnis", "fehler"), ("weg", "dokumente")))] == 0
    assert proben[("fyos_openclaw_erinnern_treffer_total", (("weg", "gedaechtnis"),))] == 4
    assert ("fyos_openclaw_erinnern_dauer_ms", (("weg", "dokumente"),)) in proben


def test_werkzeug_gedaechtnis_zeigt_stand_und_messung():
    p = _plugin(rpc_aufruf=_rufe_aus({}))
    p.call("erinnern", {"frage": "a"})
    g = p.call("gedaechtnis", {})
    assert g["anbieter"] == "openai" and g["dreaming"]["an"] is True
    assert g["gemessen"]["gedaechtnis"]["anfragen"] == 1 and g["gemessen"]["gedaechtnis"]["ms_mittel"] is not None
    assert "Dreaming an" in g["satz"] and "GEHEIMER" not in repr(g)


def test_gedaechtnis_ohne_gateway():
    g = _plugin(rpc_aufruf=lambda m, p: (_ for _ in ()).throw(RuntimeError("Brücke nicht erreichbar"))).call("gedaechtnis", {})
    assert g["satz"] == "Gedächtnis nicht lesbar." and "nicht erreichbar" in g["fehler"]
