"""agenteneingang — der Ereignisstrom, den der Runner betrachtet (POST/GET /hub/agent/eingang), ohne Netz."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_hub.plugins import agent
from mcp_hub.plugins import _agenteneingang as eingang

JETZT_MS = 1_792_270_000_000
JSON = {"content-type": "application/json"}


class FakeRedis:
    def __init__(self, ausfall=False):
        self.eintraege: list[tuple[str, dict]] = []
        self.ausfall = ausfall
        self.n = 0
        self.block = "ungesetzt"

    def xadd(self, name, felder, maxlen=None, approximate=True):
        if self.ausfall:
            raise OSError("Redis weg")
        assert name == eingang.STROM and maxlen == eingang.MAXLEN
        self.n += 1
        sid = f"{JETZT_MS}-{self.n}"
        self.eintraege.append((sid, dict(felder)))
        return sid

    def xrevrange(self, name, count=None):
        return list(reversed(self.eintraege))[:count]

    @staticmethod
    def _schluessel(sid):
        a, b = sid.split("-") if "-" in sid else (sid, "0")
        return int(a), int(b)

    def xread(self, stroeme, count=None, block=None):
        if self.ausfall:
            raise OSError("Redis weg")
        self.block = block
        ((name, nach),) = stroeme.items()
        grenze = self._schluessel(nach)
        neu = [(s, f) for s, f in self.eintraege if self._schluessel(s) > grenze][:count]
        return [[name, neu]] if neu else []


@pytest.fixture
def r():
    fake = FakeRedis()
    yield fake


@pytest.fixture
def client(r):
    return TestClient(Starlette(routes=agent.AgentPlugin({}, redis=r).routen()))


def test_eintrag_klasse_folgt_quelle():
    assert eingang.eintrag({"quelle": "web", "text": "Hallo"}, JETZT_MS)["klasse"] == "max"
    assert eingang.eintrag({"quelle": "matrix", "text": "x"}, JETZT_MS)["klasse"] == "max"
    e = eingang.eintrag({"quelle": "syl", "text": "Warnung"}, JETZT_MS)
    assert e["klasse"] == "hintergrund" and e["a"] == "agent" and e["v"] == "1"


def test_alarm_traegt_schwere_und_bleibt_hintergrund():
    e = eingang.eintrag({"quelle": "alarm", "text": "Rauchmelder Flur", "schwere": "hoch"}, JETZT_MS)
    assert e["klasse"] == "hintergrund" and e["schwere"] == "hoch"
    assert "schwere" not in eingang.eintrag({"quelle": "syl", "text": "x"}, JETZT_MS)


def test_hintergrund_darf_sich_nicht_hochstufen():
    with pytest.raises(ValueError, match="nicht max"):
        eingang.eintrag({"quelle": "zeitplan", "text": "tick", "klasse": "max"}, JETZT_MS)
    # Herabstufen ist erlaubt
    e = eingang.eintrag({"quelle": "web", "text": "später", "klasse": "hintergrund"}, JETZT_MS)
    assert e["klasse"] == "hintergrund"


@pytest.mark.parametrize(
    "roh, meldung",
    [
        ({"quelle": "irgendwo", "text": "x"}, "quelle"),
        ({"quelle": "web", "text": "   "}, "text fehlt"),
        ({"quelle": "web", "text": "x" * (eingang.TEXT_MAX + 1)}, "höchstens"),
        ({"quelle": "web", "text": "x", "agent": "Agent!"}, "agent"),
        ([1, 2], "Objekt"),
        ({"quelle": "alarm", "text": "Rauch", "schwere": "katastrophal"}, "schwere"),
        ({"quelle": "alarm", "text": "Rauch", "klasse": "max"}, "nicht max"),
    ],
)
def test_eintrag_prueft_streng(roh, meldung):
    with pytest.raises(ValueError, match=meldung):
        eingang.eintrag(roh, JETZT_MS)


def test_eintrag_saeubert_text_und_kuerzt_bezug():
    e = eingang.eintrag(
        {"quelle": "itsm", "text": "Zeile 1\nZeile 2\x07", "bezug": "V" * 100, "von": "itsm\n"},
        JETZT_MS,
    )
    assert e["text"] == "Zeile 1\nZeile 2"
    assert len(e["bezug"]) == eingang.BEZUG_MAX and e["bezug"].endswith("…")
    assert e["von"] == "itsm"


def test_einwerfen_und_lesen_ueber_http(client, r):
    antwort = client.post("/hub/agent/eingang", json={"quelle": "web", "text": "Wie ist die Lage?"})
    assert antwort.status_code == 200 and antwort.json() == {"ok": True, "id": f"{JETZT_MS}-1"}
    client.post("/hub/agent/eingang", json={"quelle": "syl", "text": "Platte voll", "agent": "andere"})
    gelesen = client.get("/hub/agent/eingang", params={"nach": "0", "warte": 0}).json()
    assert gelesen["ok"] is True
    assert [e["text"] for e in gelesen["eintraege"]] == ["Wie ist die Lage?"]
    # Der fremde Eintrag wird übersprungen, die Position rückt trotzdem vor
    assert gelesen["letzte"] == f"{JETZT_MS}-2"
    weiter = client.get("/hub/agent/eingang", params={"nach": gelesen["letzte"]}).json()
    assert weiter["eintraege"] == [] and weiter["letzte"] == f"{JETZT_MS}-2"


def test_lesen_ab_spitze_verpasst_nichts(r):
    eingang.einwerfen(r, {"quelle": "web", "text": "alt"}, JETZT_MS)
    ergebnis = eingang.lesen(r, "$", 0, 10)
    assert ergebnis == {"eintraege": [], "letzte": f"{JETZT_MS}-1"}
    eingang.einwerfen(r, {"quelle": "web", "text": "neu"}, JETZT_MS)
    assert [e["text"] for e in eingang.lesen(r, ergebnis["letzte"], 0, 10)["eintraege"]] == ["neu"]


def test_warten_ist_gedeckelt(r):
    eingang.lesen(r, "0", 999, 10)
    assert r.block == eingang.WARTE_MAX_S * 1000
    eingang.lesen(r, "0", 0, 10)
    assert r.block is None  # 0 heißt nicht blockieren, nicht „ewig“ (redis-py: block=0)


def test_fehlerwege(client, r):
    assert client.post("/hub/agent/eingang", content=b"{kaputt", headers=JSON).status_code == 400
    assert client.post("/hub/agent/eingang", json={"quelle": "web"}).status_code == 400
    assert client.get("/hub/agent/eingang", params={"nach": "abc"}).status_code == 400
    r.ausfall = True
    antwort = client.post("/hub/agent/eingang", json={"quelle": "web", "text": "x"})
    assert antwort.status_code == 503 and antwort.json()["kind"] == "redis"
    assert client.get("/hub/agent/eingang", params={"nach": "0"}).status_code == 503


def test_stimme_ist_kanal_des_benutzers():
    # Gesprochene Sätze (Sprach-Pipeline, Raum-Mikros) haben Vorfahrt wie der Web-Chat.
    e = eingang.eintrag({"quelle": "stimme", "text": "Mach das Licht an", "von": "ha-assist"}, JETZT_MS)
    assert e["quelle"] == "stimme" and e["klasse"] == "max"
