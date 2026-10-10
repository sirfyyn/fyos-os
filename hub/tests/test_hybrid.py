"""Hybrid-Stufe der Werkzeugsuche (Reflex R2, 08.10.2026): RRF aus Wortwertung, BM25 und Einbetter, Rueckfall."""
from __future__ import annotations

import pytest

from mcp_hub import hybrid
from mcp_hub import server as hub_server

KATALOG = [
    {"name": "finance.umsaetze", "description": "Kontobewegungen aus MoneyMoney."},
    {"name": "haus.licht", "description": "Lampen schalten."},
    {"name": "wetter.heute", "description": "Vorhersage fuer heute."},
]

# Spielzeug-Einbetter: ein Merkmal je Thema, damit „regnet es“ semantisch beim Wetter landet.
THEMEN = {"wetter": ("wetter", "regnet", "vorhersage"), "geld": ("konto", "geld", "finance"), "licht": ("lampe", "licht")}


def _vektor(text: str) -> list[float]:
    t = text.lower()
    return [float(sum(w in t for w in woerter)) + 0.01 for woerter in THEMEN.values()]


class _SofortThread:
    def __init__(self, target, args=(), **_):
        self._ziel, self._args = target, args

    def start(self):
        self._ziel(*self._args)


@pytest.fixture
def h(monkeypatch):
    aufrufe: list[list[str]] = []

    def einbetten(texte, timeout):
        aufrufe.append(list(texte))
        return [hybrid._norm(_vektor(x)) for x in texte]

    monkeypatch.setattr(hybrid, "EMBED_URL", "http://einbetter:8080")
    monkeypatch.setattr(hybrid, "_post_embeddings", einbetten)
    monkeypatch.setattr(hybrid.threading, "Thread", _SofortThread)
    obj = hybrid.Hybrid()
    obj.aufrufe = aufrufe
    return obj


def test_ohne_einbetter_bleibt_es_bei_der_wortwertung(monkeypatch):
    monkeypatch.setattr(hybrid, "EMBED_URL", "")
    assert hybrid.Hybrid().mische(KATALOG, "wetter", [KATALOG[2]]) is None




def test_worttreffer_bleiben_vorn_und_liste_waechst_begrenzt(h, monkeypatch):
    monkeypatch.setattr(hybrid, "ZUSATZ", 1)
    h.vorwaermen(KATALOG)
    gemischt = h.mische(KATALOG, "konto geld", [KATALOG[0]])
    namen = [t["name"] for t in gemischt]
    assert namen[0] == "finance.umsaetze"
    assert len(namen) <= 2  # Worttreffer + je bester Zusatz aus BM25/Einbetter


def test_timeout_faellt_zurueck_und_pausiert(h, monkeypatch):
    h.vorwaermen(KATALOG)
    zaehler = {"n": 0}

    def kaputt(texte, timeout):
        zaehler["n"] += 1
        raise TimeoutError("zu langsam")

    monkeypatch.setattr(hybrid, "_post_embeddings", kaputt)
    assert h.mische(KATALOG, "neue frage", []) is None
    assert h.mische(KATALOG, "noch eine frage", []) is None
    assert zaehler["n"] == 1  # Pause: die zweite Suche wartet nicht erneut auf den Timeout


def test_rrf_mischt_rangfolgen():
    assert hybrid.rrf(["a", "b"], ["b", "c"], ["b"]) == ["b", "a", "c"]


def test_rangliste_nutzt_hybrid_und_meldet_teiltreffer(monkeypatch):
    class _Reg:
        pass

    monkeypatch.setattr(hub_server, "search_tools", lambda reg, q: list(KATALOG))
    monkeypatch.setattr(hub_server._hybrid.HYBRID, "mische", lambda alle, q, wort: [KATALOG[2]])
    treffer, teil = hub_server.rangliste(_Reg(), "regnet es draussen")
    assert [t["name"] for t in treffer] == ["wetter.heute"] and teil is True
