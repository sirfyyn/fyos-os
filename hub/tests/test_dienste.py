"""Optionale Dienste: Weiche vor dem Wecken, Reranker für `erinnern`, Prüfung von Mund und Ohr (Attrappen, ohne Netz)."""

from __future__ import annotations

from typing import Any

import pytest

from mcp_hub.plugins import _dienste as D
from mcp_hub.plugins import _wecker as W
from tests.test_gedaechtnis import SUCHE, _rufe_aus
from tests.test_openclaw import _plugin
from tests.test_wecker import Uhr, Vorgaenge, bauen, ticket


class Dienst:
    """Ein Dienst im Speicher: merkt sich Anfragen, antwortet mit `antwort` oder wirft `fehler`."""

    def __init__(self, antwort: Any = None, fehler: Exception | None = None) -> None:
        self.antwort, self.fehler, self.anfragen = antwort, fehler, []

    def __call__(self, url: str, koerper: dict[str, Any], zeit_s: float) -> Any:
        self.anfragen.append((url, koerper, zeit_s))
        if self.fehler:
            raise self.fehler
        return self.antwort(koerper) if callable(self.antwort) else self.antwort


UMSCHLAG = {"id": "x1", "strom": "itsm", "thema": "itsm.kommentar", "zeit": "2026-10-11T10:00:00Z", "zeit_unix": 1.0,
            "schwere": "normal", "quelle": "itsm", "verweis": "INC-1", "von": "berta", "daten": {"geheim": "TEXT"}}


# ── Adressen ────────────────────────────────────────────────────────────────────────────────────

def test_adressen_aus_konfiguration_vor_umgebung(monkeypatch):
    monkeypatch.setenv("FYOS_WEICHE_URL", "http://aus-umgebung:1/")
    monkeypatch.setenv("FYOS_RERANK_URL", "http://rerank:2/")
    monkeypatch.delenv("FYOS_MUND_URL", raising=False)
    monkeypatch.delenv("FYOS_OHR_URL", raising=False)
    assert D.adressen({"weiche_url": "http://konfig:3/"}) == {"weiche": "http://konfig:3", "rerank": "http://rerank:2"}
    assert D.adressen(None) == {"weiche": "http://aus-umgebung:1", "rerank": "http://rerank:2"}


@pytest.fixture(autouse=True)
def _ohne_umgebung(monkeypatch):
    for name in D.UMGEBUNG.values():
        monkeypatch.delenv(name, raising=False)


# ── Weiche ──────────────────────────────────────────────────────────────────────────────────────

def test_ohne_weiche_wird_geweckt():
    assert D.Dienste().weiche(UMSCHLAG) == (True, "keine Weiche")


def test_weiche_entscheidet_und_sieht_nie_die_daten():
    post = Dienst({"wecken": False, "grund": "  schon   erledigt "})
    d = D.Dienste({"weiche_url": "http://weiche:9"}, post=post)
    assert d.weiche(UMSCHLAG) == (False, "schon erledigt")
    url, koerper, _ = post.anfragen[0]
    assert url == "http://weiche:9/entscheiden" and "daten" not in koerper["umschlag"]
    assert koerper["umschlag"]["thema"] == "itsm.kommentar" and koerper["umschlag"]["verweis"] == "INC-1"
    assert d.weiche_urteile == {"wecken": 0, "ruhig": 1, "offen": 0}


@pytest.mark.parametrize("antwort,fehler", [(None, OSError("keine Verbindung")), ({"wecken": "ja"}, None), ("quatsch", None)])
def test_ausfall_der_weiche_laesst_den_weckruf_durch(antwort, fehler):
    d = D.Dienste({"weiche_url": "http://weiche:9"}, post=Dienst(antwort, fehler))
    wecken, grund = d.weiche(UMSCHLAG)
    assert wecken is True and "offen" in grund
    assert d.zaehler["weiche"]["fehler"] == 1 and d.weiche_urteile["offen"] == 1


# ── Weiche im Wecker ────────────────────────────────────────────────────────────────────────────

def _wecker_mit_weiche(weiche, regeln):
    uhr, q = Uhr(), Vorgaenge()
    w, weck, _ = bauen([W.VorgangsQuelle(lambda: q)], uhr, regeln=W.regeln_pruefen(regeln), weiche=weiche)
    w.schlag()
    uhr.t += 20
    q.tickets["INC-7"] = ticket("INC-7")
    return w, weck


def test_regel_mit_weiche_fragt_die_weiche_und_haelt_ruhig():
    gefragt: list[str] = []

    def weiche(u):
        gefragt.append(u["thema"])
        return False, "nicht nötig"

    w, weck = _wecker_mit_weiche(weiche, [{"name": "v", "thema": ["itsm.neu"], "weiche": True}])
    assert w.schlag()["geweckt"] == 0 and weck.aufrufe == []
    assert gefragt == ["itsm.neu"] and w.zaehler["ruhig"] == 1
    assert w.verlauf[-1]["ergebnis"] == "ruhig" and w.verlauf[-1]["fehler"] == "nicht nötig"


def test_regel_mit_weiche_weckt_bei_ja():
    w, weck = _wecker_mit_weiche(lambda u: (True, ""), [{"name": "v", "thema": ["itsm.neu"], "weiche": True}])
    assert w.schlag()["geweckt"] == 1 and len(weck.aufrufe) == 1


def test_regel_ohne_weiche_fragt_nicht():
    def weiche(u):
        raise AssertionError("darf nicht gefragt werden")

    w, weck = _wecker_mit_weiche(weiche, [{"name": "v", "thema": ["itsm.neu"]}])
    assert w.schlag()["geweckt"] == 1


def test_werfende_weiche_haelt_den_wecker_nicht_auf():
    def weiche(u):
        raise RuntimeError("kaputt")

    w, weck = _wecker_mit_weiche(weiche, [{"name": "v", "thema": ["itsm.neu"], "weiche": True}])
    assert w.schlag()["geweckt"] == 1


def test_plugin_gibt_die_weiche_nur_mit_adresse_weiter():
    assert _plugin().wecker()._weiche is None
    p = _plugin(dienste={"weiche_url": "http://weiche:9"}, dienste_post=Dienst({"wecken": True}))
    assert p.wecker()._weiche is not None


# ── Reranker ────────────────────────────────────────────────────────────────────────────────────

TREFFER = [{"titel": "a", "auszug": "eins"}, {"titel": "b", "auszug": "zwei"}, {"titel": "c", "auszug": "drei"}]


def test_reranker_ordnet_nach_punkten_neu():
    post = Dienst({"results": [{"index": 0, "score": 0.1}, {"index": 1, "score": 0.9}, {"index": 2, "score": 0.5}]})
    aus, m = D.Dienste({"rerank_url": "http://r:1"}, post=post).rerank("frage", TREFFER)
    assert [t["titel"] for t in aus] == ["b", "c", "a"] and aus[0]["rerank_punkte"] == 0.9 and m["ok"]
    url, koerper, _ = post.anfragen[0]
    assert url == "http://r:1/rerank" and koerper["query"] == "frage" and len(koerper["documents"]) == 3


def test_reranker_versteht_nackte_liste_und_relevance_score():
    post = Dienst([{"index": 2, "relevance_score": 0.7}, {"index": 0, "relevance_score": 0.2}])
    aus, _ = D.Dienste({"rerank_url": "http://r:1"}, post=post).rerank("f", TREFFER)
    assert [t["titel"] for t in aus] == ["c", "a", "b"], "ohne Punkte ans Ende, in alter Reihenfolge"
    assert aus[2]["rerank_punkte"] is None


@pytest.mark.parametrize("antwort,fehler", [(None, OSError("aus")), ({"results": []}, None), ({"results": [{"x": 1}]}, None)])
def test_reranker_ausfall_laesst_die_reihenfolge(antwort, fehler):
    aus, m = D.Dienste({"rerank_url": "http://r:1"}, post=Dienst(antwort, fehler)).rerank("f", TREFFER)
    assert aus == TREFFER and m["ok"] is False and m["grund"]


def test_reranker_ohne_adresse_oder_mit_einem_treffer_fragt_nicht():
    post = Dienst({"results": []})
    assert D.Dienste(post=post).rerank("f", TREFFER)[0] == TREFFER
    assert D.Dienste({"rerank_url": "http://r:1"}, post=post).rerank("f", TREFFER[:1])[0] == TREFFER[:1]
    assert post.anfragen == []


def test_erinnern_nutzt_den_reranker_und_misst_ihn():
    brett: dict[str, Any] = {}
    gesamt = len(SUCHE["results"])
    assert gesamt >= 2

    def antwort(koerper):
        n = len(koerper["documents"])
        return {"results": [{"index": i, "score": float(i)} for i in range(n)]}

    p = _plugin(rpc_aufruf=_rufe_aus(brett), dienste={"rerank_url": "http://r:1"}, dienste_post=Dienst(antwort))
    e = p.call("erinnern", {"frage": "Notizzettel"})
    assert e["messung"]["rerank"]["ok"] and e["messung"]["rerank"]["anzahl"] == gesamt
    assert e["treffer"][0]["rerank_punkte"] == float(gesamt - 1) and "Reranker" in e["satz"]
    assert p._erinnert["rerank"]["anfragen"] == 1


def test_erinnern_bei_ausfall_des_rerankers_wie_ohne():
    brett: dict[str, Any] = {}
    ohne = _plugin(rpc_aufruf=_rufe_aus(brett)).call("erinnern", {"frage": "Notizzettel"})
    mit = _plugin(rpc_aufruf=_rufe_aus(brett), dienste={"rerank_url": "http://r:1"},
                  dienste_post=Dienst(fehler=OSError("aus"))).call("erinnern", {"frage": "Notizzettel"})
    assert [t["verweis"] for t in mit["treffer"]] == [t["verweis"] for t in ohne["treffer"]]
    assert mit["messung"]["rerank"]["ok"] is False and "Reranker" not in mit["satz"]


# ── Prüfung ─────────────────────────────────────────────────────────────────────────────────────

def _gateway(methode: str, params: dict[str, Any]) -> Any:
    if methode == "tts.status":
        return {"enabled": True, "provider": "openai", "providerStates": [{"id": "openai", "configured": True},
                                                                         {"id": "xai", "configured": False}]}
    if methode == "voicewake.routing.get":
        return {"config": {"routes": [{"x": 1}, {"x": 2}]}}
    raise RuntimeError(methode)


def test_dienste_ohne_adressen_sagt_es_ehrlich():
    e = _plugin(rpc_aufruf=_gateway).call("dienste", {})
    assert "Keine optionalen Dienste" in e["satz"] and all(not d["eingerichtet"] for d in e["dienste"].values())
    assert e["gateway"]["mund"] == {"an": True, "anbieter": "openai", "eingerichtet": ["openai"]}
    assert e["gateway"]["weckwort"] == {"routen": 2}


def test_dienste_prueft_erreichbarkeit_ohne_nutzdaten():
    proben: list[str] = []

    def get(url: str, zeit_s: float) -> int:
        proben.append(url)
        if "ohr" in url:
            raise OSError("keine Verbindung")
        return 404  # erreicht, nur ohne diese Seite

    p = _plugin(rpc_aufruf=_gateway, dienste={"mund_url": "http://mund:1", "ohr_url": "http://ohr:2"}, dienste_get=get)
    e = p.call("dienste", {})
    assert e["dienste"]["mund"]["erreichbar"] is True and e["dienste"]["mund"]["status"] == 404
    assert e["dienste"]["ohr"]["erreichbar"] is False and "OSError" in e["dienste"]["ohr"]["fehler"]
    assert e["dienste"]["weiche"]["erreichbar"] is None
    assert "nicht erreichbar: ohr" in e["satz"] and proben == ["http://mund:1", "http://ohr:2"]
    assert p.call("dienste", {"probe": False})["dienste"]["ohr"]["erreichbar"] is None


def test_dienste_ueberlebt_ausfall_des_gateways():
    def rpc(methode: str, params: dict[str, Any]) -> Any:
        raise RuntimeError("Brücke nicht erreichbar")

    e = _plugin(rpc_aufruf=rpc).call("dienste", {})
    assert e["gateway"] == {"mund": None, "weckwort": None} and len(e["fehler"]) == 2
