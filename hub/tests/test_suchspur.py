"""Suchspur: Suche → gewähltes Werkzeug wird als Label festgehalten (08.10.2026).

## Wann diese Prüfung nein sagt
- wenn ein Aufruf nach einer Suche keinen Datensatz mit Anfrage, Kandidaten und Rang erzeugt
- wenn ein Meta-Werkzeug (hub.*, skills.suchen) die Suche schon „verbraucht“
- wenn ein Aufruf ohne vorherige Suche einen Datensatz erzeugt
- wenn ein Redis-Fehler bis zum Aufrufer durchschlägt (muss fail-open sein)
"""

from __future__ import annotations

import json

from mcp_hub import suchspur


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.liste: list[str] = []

    def set(self, k, v, ex=None):  # noqa: ARG002
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)

    def delete(self, k):
        self.kv.pop(k, None)

    def lpush(self, k, v):  # noqa: ARG002
        self.liste.insert(0, v)

    def ltrim(self, k, a, b):  # noqa: ARG002
        self.liste = self.liste[a : b + 1]


def test_suche_dann_aufruf_ergibt_label():
    r = FakeRedis()
    suchspur.merke_suche("mcp:claude-code", "geld konto", ["finance.konten", "konten.uebersicht"], r=r)
    satz = suchspur.schliesse_ab("mcp:claude-code", "konten.uebersicht", r=r)
    assert satz is not None
    assert satz["anfrage"] == "geld konto" and satz["gewaehlt"] == "konten.uebersicht" and satz["rang"] == 1
    assert json.loads(r.liste[0])["kandidaten"] == ["finance.konten", "konten.uebersicht"]
    # einmal abgeschlossen: der nächste Aufruf erzeugt keinen zweiten Datensatz
    assert suchspur.schliesse_ab("mcp:claude-code", "finance.konten", r=r) is None


def test_nicht_unter_den_kandidaten_ist_rang_minus_1():
    r = FakeRedis()
    suchspur.merke_suche("mcp:agent", "wetter", ["haus.geraete"], r=r)
    assert suchspur.schliesse_ab("mcp:agent", "wetter.jetzt", r=r)["rang"] == -1


def test_meta_werkzeug_verbraucht_die_suche_nicht():
    r = FakeRedis()
    suchspur.merke_suche("mcp:agent", "server", ["modell.zustand"], r=r)
    assert suchspur.schliesse_ab("mcp:agent", "hub.schema", r=r) is None
    assert suchspur.schliesse_ab("mcp:agent", "skills.suchen", r=r) is None
    assert suchspur.schliesse_ab("mcp:agent", "modell.zustand", r=r)["rang"] == 0


def test_ohne_suche_kein_datensatz_und_aufrufer_getrennt():
    r = FakeRedis()
    suchspur.merke_suche("mcp:agent", "server", ["modell.zustand"], r=r)
    assert suchspur.schliesse_ab("mcp:claude-code", "modell.zustand", r=r) is None
    assert r.liste == []


def test_leere_anfrage_wird_nicht_gemerkt():
    r = FakeRedis()
    suchspur.merke_suche("mcp:agent", "  ", ["a.b"], r=r)
    assert r.kv == {}


def test_redis_fehler_ist_fail_open():
    class Kaputt:
        def set(self, *a, **k):
            raise ConnectionError("weg")

        get = set

    suchspur.merke_suche("x", "server", ["a.b"], r=Kaputt())
    assert suchspur.schliesse_ab("x", "a.b", r=Kaputt()) is None
