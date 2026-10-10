"""Rangfolge der Werkzeug- und Werkstattsuche (09.10.2026).

## Wann diese Prüfung nein sagt
- wenn ein kurzes Suchwort (»ci«) wieder mitten in einem Wort trifft (»cipher«, »Link-Training«)
- wenn ein Treffer im Namen/in der ID nicht vor einem Treffer nur im Zweck steht
- wenn mehrere Suchwörter wieder nur als ganzer Satz am Stück gesucht werden
- wenn werkstatt.suchen mit Suchwort mehr als 10 Treffer liefert (ohne voll) oder ohne Suchwort nicht alle Skripte
- wenn die Hub-Werkzeugsuche mit Suchwort mehr als 10 Treffer liefert (ohne voll/limit) oder ohne Suchwort das Verzeichnis kürzt
- wenn die Dichtesuche ein Skript ohne Wortbezug unmarkiert (kein »aehnlich«) zeigt oder ein einzelnes Wort ohne Wortbezug rät
"""

from __future__ import annotations

import pytest

from mcp_hub import suchrang
from mcp_hub.hybrid import Hybrid
from mcp_hub.plugins.werkstatt import WerkstattPlugin
from mcp_hub.server import SUCH_LIMIT, such_grenze

KATALOG = [
    {"id": "ops/server/fehlerbild", "titel": "Server-Fehlerbild", "zweck": "Was Server an Hardware-Fehlern meldet (Xid, PCIe, Link-Training)", "ort": "server", "wirkung": "lesen"},
    {"id": "ops/pods_kaputt", "titel": "Kaputte Pods", "zweck": "Findet kaputte Pods im Cluster", "ort": "cluster", "wirkung": "lesen"},
    {"id": "ops/itsm", "titel": "ITSM-Vorgaenge", "zweck": "Vorgaenge im ITSM lesen, suchen und aendern", "ort": "cluster", "wirkung": "schreiben"},
    {"id": "ops/ausrollen", "titel": "Ausrollen", "zweck": "Treibt einen Dienst durch die Flux-Kette, bis der Digest im Deployment liegt", "ort": "cluster", "wirkung": "schreiben"},
    {"id": "ops/cronjob_zwecke", "titel": "CronJobs nach Zweck", "zweck": "Gruppiert alle CronJobs nach Zweck", "ort": "cluster", "wirkung": "lesen"},
]


def ids(r):
    return [e["id"] for e, _, _ in r[0]]


def test_kurzes_wort_trifft_nur_ganze_woerter():
    assert suchrang.passt("ci", "ci") == 1.0
    assert suchrang.passt("ci", "cipher") == 0.0
    assert suchrang.passt("ci", "training") == 0.0
    assert suchrang.passt("log", "logs") > 0
    assert suchrang.passt("log", "login") == 0.0


def test_laengere_woerter_trifft_anfang_und_langes_wort():
    assert suchrang.passt("skripte", "skript") > 0
    assert suchrang.passt("skript", "skripte") > 0
    assert suchrang.passt("werkzeug", "anwendungswerkzeuge") > 0
    assert suchrang.passt("pod", "pods") > 0


def test_ci_findet_nicht_server_fehlerbild():
    # Fehlerbild: werkstatt.suchen {q:"ci"} fand »Server-Fehlerbild«, weil »ci« irgendwo im Text steckt
    assert ids(suchrang.skripte_rang(KATALOG, "ci")) == []


def test_id_vor_zweck_und_mehrere_woerter():
    r = suchrang.skripte_rang(KATALOG, "kaputte pods")
    assert ids(r)[0] == "ops/pods_kaputt"
    r = suchrang.skripte_rang(KATALOG, "pods cluster")
    assert ids(r)[0] == "ops/pods_kaputt"
    # Wertung: bester = 1,0
    assert r[0][0][1] == 1.0


def test_alle_woerter_zuerst_sonst_teiltreffer():
    liste, teil = suchrang.skripte_rang(KATALOG, "itsm vorgaenge")
    assert [e["id"] for e, _, _ in liste] == ["ops/itsm"] and teil is False
    liste, teil = suchrang.skripte_rang(KATALOG, "itsm mond")
    assert [e["id"] for e, _, _ in liste] == ["ops/itsm"] and teil is True


class _Dicht(Hybrid):
    """Hybrid-Attrappe: feste Dichte-Rangfolge, keine Einbetter-Anfrage."""

    def __init__(self, rang):
        super().__init__()
        self.rang = rang

    @property
    def an(self):
        return True

    def dicht_rang(self, tools, query):
        return self.rang


def test_dichtesuche_markiert_aehnliche_und_raet_nicht_bei_einem_wort():
    h = _Dicht(["ops/ausrollen", "ops/itsm", "ops/pods_kaputt", "ops/cronjob_zwecke", "ops/server/fehlerbild"])
    # ohne Wortbezug: drei aehnliche, gekennzeichnet
    liste, _ = suchrang.skripte_rang(KATALOG, "neue version bereitstellen", h)
    assert [a for _, _, a in liste] == ["aehnlich"] * 3 and liste[0][0]["id"] == "ops/ausrollen"
    # ein einzelnes Wort ohne Wortbezug: nichts
    assert suchrang.skripte_rang(KATALOG, "modell", h)[0] == []
    # mit Wortbezug: Dichte hebt das Passende, Wort-Treffer bleiben als »wort« gekennzeichnet
    liste, _ = suchrang.skripte_rang(KATALOG, "ausrollen digest", h)
    assert liste[0][0]["id"] == "ops/ausrollen" and liste[0][2] == "wort"


def test_ohne_einbetter_bleibt_die_wortsuche():
    class _Aus(_Dicht):
        def dicht_rang(self, tools, query):
            return None

    liste, _ = suchrang.skripte_rang(KATALOG, "kaputte pods", _Aus([]))
    assert liste[0][0]["id"] == "ops/pods_kaputt"
    assert suchrang.skripte_rang(KATALOG, "neue version bereitstellen", _Aus([]))[0] == []


# ── werkstatt.suchen ───────────────────────────────────────────────────────


@pytest.fixture
def werkstatt(monkeypatch):
    w = WerkstattPlugin({"repo": "/nicht/da"})
    voll = {}
    for i, e in enumerate(KATALOG):
        voll[e["id"]] = {**e, "pfad": f"scripts/{e['id']}.py", "trockenlauf": True, "gesperrt": "", "argumente": [], "sprache": "python"}
    for i in range(20):  # genug Skripte, damit die Obergrenze greift
        voll[f"ops/pod_hilfe_{i}"] = {
            "id": f"ops/pod_hilfe_{i}", "titel": f"Pod-Hilfe {i}", "zweck": "Hilft bei Pods", "ort": "cluster",
            "wirkung": "lesen", "pfad": f"scripts/ops/pod_hilfe_{i}.py", "trockenlauf": True, "gesperrt": "", "argumente": [], "sprache": "python",
        }
    monkeypatch.setattr(w, "katalog", lambda: voll)
    return w


def test_werkstatt_suchen_mit_wort_hoechstens_zehn_mit_rangwert(werkstatt):
    r = werkstatt.suchen("pods", "", "")
    assert r["anzahl"] == 10 and r["gesamt"] == 21 and "weitere" in r["hinweis"]
    assert all("wert" in s for s in r["skripte"]) and r["skripte"][0]["wert"] == 1.0
    voll = werkstatt.suchen("pods", "", "", None, True)
    assert voll["anzahl"] == 21
    assert werkstatt.suchen("pods", "", "", 3)["anzahl"] == 3


def test_werkstatt_suchen_ohne_wort_alle_skripte_ohne_rangwert(werkstatt):
    r = werkstatt.suchen("", "", "")
    assert r["anzahl"] == 25 and "wert" not in r["skripte"][0] and "gesamt" not in r


def test_werkstatt_suchen_filter_und_ci(werkstatt):
    assert werkstatt.suchen("", "server", "")["anzahl"] == 1
    assert werkstatt.suchen("ci", "", "")["anzahl"] == 0
    assert werkstatt.suchen("zzzz", "", "")["hinweis"].startswith("Kein Skript")


def test_werkstatt_suchen_limit_wird_geprueft(werkstatt):
    with pytest.raises(ValueError):
        werkstatt.suchen("pods", "", "", 0)
    with pytest.raises(ValueError):
        werkstatt.suchen("pods", "", "", True)


# ── hub__search_tools: Grenze ──────────────────────────────────────────────


def test_such_grenze():
    assert such_grenze("ci lauf log", None, False) == SUCH_LIMIT == 10
    assert such_grenze("ci", 0, True) == 200
    assert such_grenze("ci", 3, False) == 3
    assert such_grenze("ci", 999, False) == 200
    assert such_grenze("", None, False) == 25  # Verzeichnis aller Werkzeuge
    assert such_grenze("  ", 0, False) == 25


def test_rangliste_gibt_rangwert_und_haelt_den_besten_vorn():
    alle = [
        {"name": "betrieb.ci_laeufe", "description": "Letzte Commits und CI-Laeufe"},
        {"name": "tresor.get_cipher", "description": "Fetch a single cipher by id"},
        {"name": "git.log_unified", "description": "Letzte Commits"},
    ]
    liste, teil = suchrang.rangliste(alle, "ci laeufe")
    assert liste[0]["name"] == "betrieb.ci_laeufe" and liste[0]["wert"] == 1.0
    assert all(0.0 <= t["wert"] <= 1.0 for t in liste)
