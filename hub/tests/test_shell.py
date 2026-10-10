"""shell — Anordnung und Befehle der FYOS-Shell. Redis ist eine Attrappe."""

from __future__ import annotations

import json

import pytest

from mcp_hub.plugins import shell


class Redis:
    def __init__(self):
        self.k: dict = {}
        self.l: dict = {}
        self.ex: dict = {}
        self.hh: dict = {}

    def ping(self):
        return True

    def get(self, k):
        return self.k.get(k)

    def set(self, k, v, ex=None):
        self.k[k] = v
        self.ex[k] = ex

    def rpush(self, k, v):
        self.l.setdefault(k, []).append(v)

    def ltrim(self, k, a, b):
        self.l[k] = self.l[k][a:] if a < 0 else self.l[k][a : b + 1]

    def expire(self, k, s):
        self.ex[k] = s

    def lrange(self, k, a, b):
        return list(self.l.get(k, []))

    def delete(self, k):
        self.l.pop(k, None)

    h: dict = {}

    def hgetall(self, k):
        return dict(self.hh.get(k, {}))

    def hset(self, k, f, v):
        self.hh.setdefault(k, {})[f] = v

    def hdel(self, k, f):
        return 1 if self.hh.get(k, {}).pop(f, None) is not None else 0

    def hexists(self, k, f):
        return f in self.hh.get(k, {})


@pytest.fixture()
def plugin():
    p = shell.ShellPlugin()
    p._r = Redis()
    return p


def test_zustand_ohne_meldung_sagt_es(plugin):
    z = plugin.call("zustand", {})
    assert z["bekannt"] is False and z["fenster"] == [] and "noch nicht gemeldet" in z["hinweis"]


def test_merken_und_zustand_rundlauf(plugin):
    plugin.call(
        "merken",
        {
            "fenster": [
                {"id": "seite:finance", "min": False, "breit": True},
                {"id": "app:leitstand__lagebild", "min": True},
            ],
            "agent": True,
            "verfuegbar": [
                {"id": "seite:finance", "titel": "Finance"},
                {"id": "geklaut; DROP", "titel": "x"},
            ],
        },
    )
    z = plugin.call("zustand", {})
    assert z["bekannt"] and z["agent"] is True
    assert [w["id"] for w in z["fenster"]] == ["seite:finance", "app:leitstand__lagebild"]
    assert z["fenster"][1]["min"] is True and z["verfuegbar"] == [
        {"id": "seite:finance", "titel": "Finance"}
    ]
    assert plugin._r.ex[shell.SCHLUESSEL_ANORDNUNG] == shell.ANORDNUNG_TTL_S


def test_merken_verwirft_ungueltiges_und_doppeltes(plugin):
    plugin.call(
        "merken",
        {
            "fenster": [
                {"id": "agent"},
                {"id": "agent"},
                {"id": "../etc"},
                "x",
                {"id": "seite:Gross"},
                {"id": "seite:ok"},
            ]
        },
    )
    assert [w["id"] for w in plugin.call("zustand", {})["fenster"]] == ["agent", "seite:ok"]
    plugin.call("merken", {"fenster": [{"id": f"seite:s{i}"} for i in range(40)]})
    assert len(plugin.call("zustand", {})["fenster"]) == shell.FENSTER_MAX


@pytest.mark.parametrize("flaeche", ["seite:finance", "app:leitstand__lagebild", "agent"])
def test_befehl_wird_vorgemerkt_und_von_der_shell_abgeholt(plugin, flaeche):
    r = plugin.call("befehl", {"aktion": "oeffnen", "flaeche": flaeche})
    assert r["ok"] and r["shell_gemeldet"] is False and "10 Minuten" in r["hinweis"]
    assert plugin._r.ex[shell.SCHLUESSEL_BEFEHLE] == shell.BEFEHLE_TTL_S
    assert plugin.call("abholen", {})["befehle"] == [{"aktion": "oeffnen", "flaeche": flaeche}]
    assert plugin.call("abholen", {})["befehle"] == []  # Warteschlange ist leer


@pytest.mark.parametrize(
    "args",
    [
        {"aktion": "loeschen", "flaeche": "seite:finance"},
        {"aktion": "oeffnen", "flaeche": "http://boese.example"},
        {"aktion": "oeffnen", "flaeche": "seite:../../etc/passwd"},
        {"aktion": "oeffnen", "flaeche": ""},
        {"aktion": "oeffnen", "flaeche": 5},
    ],
)
def test_befehl_lehnt_fremdes_ab(plugin, args):
    with pytest.raises(ValueError):
        plugin.call("befehl", args)
    assert plugin._r.l == {}


def test_abholen_ignoriert_manipulierte_eintraege(plugin):
    plugin._r.l[shell.SCHLUESSEL_BEFEHLE] = [
        json.dumps({"aktion": "oeffnen", "flaeche": "seite:ok"}),
        json.dumps({"aktion": "rm -rf", "flaeche": "seite:ok"}),
        json.dumps({"aktion": "oeffnen", "flaeche": "javascript:alert(1)"}),
        "kein json",
    ]
    assert plugin.call("abholen", {})["befehle"] == [{"aktion": "oeffnen", "flaeche": "seite:ok"}]


def test_bildschirm_befehl_kommt_an(plugin):
    """Bis 05.10. verlangte abholen eine Fläche — „bildschirm“ hat keine und ging verloren."""
    plugin.call("befehl", {"aktion": "bildschirm", "index": 2})
    plugin.call("befehl", {"aktion": "bildschirm", "name": "Geld und Post"})
    plugin._r.l[shell.SCHLUESSEL_BEFEHLE].append(json.dumps({"aktion": "bildschirm", "index": 99}))
    assert plugin.call("abholen", {})["befehle"] == [
        {"aktion": "bildschirm", "index": 2},
        {"aktion": "bildschirm", "name": "Geld und Post"},
    ]


def test_nur_zustand_ist_lesend_und_alle_haben_flaeche():
    t = {x.name: x for x in shell.ShellPlugin().describe_tools()}
    assert "write" not in t["zustand"].tags and "read" in t["zustand"].tags
    assert all("flaeche" in x.tags for x in t.values())
    assert "write" in t["befehl"].tags


def test_health_meldet_redis_ausfall(plugin):
    plugin._r.ping = lambda: (_ for _ in ()).throw(ConnectionError("weg"))
    assert plugin.health()["ok"] is False


# ── Arbeitsplaetze ───────────────────────────────────────────────────────────
def test_platz_speichern_aus_der_aktuellen_anordnung_und_laden(plugin):
    plugin.call(
        "merken",
        {"fenster": [{"id": "seite:finance"}, {"id": "app:leitstand__lagebild", "min": True}]},
    )
    r = plugin.call("platz_speichern", {"name": "Geld und Post"})
    assert r["ok"] and r["fenster"] == 2 and r["ueberschrieben"] is False
    assert plugin.call("plaetze", {})["plaetze"][0]["name"] == "Geld und Post"
    plugin.call("platz_laden", {"name": "Geld und Post"})
    assert plugin.call("abholen", {})["befehle"] == [{"aktion": "platz", "name": "Geld und Post"}]


def test_platz_speichern_ueberschreibt_und_hat_eine_obergrenze(plugin):
    f = [{"id": "agent"}]
    for i in range(shell.PLAETZE_MAX):
        plugin.call("platz_speichern", {"name": f"Platz {i}", "fenster": f})
    with pytest.raises(ValueError, match="Schon 12"):
        plugin.call("platz_speichern", {"name": "Einer zu viel", "fenster": f})
    assert (
        plugin.call("platz_speichern", {"name": "Platz 3", "fenster": f})["ueberschrieben"] is True
    )


@pytest.mark.parametrize(
    "args,teil",
    [
        ({"name": "x"}, "name"),
        ({"name": "böse;DROP"}, "name"),
        ({"name": "Gut", "fenster": []}, "Keine Flaechen"),
        ({"name": "Gut"}, "noch nicht gemeldet"),
    ],
)
def test_platz_speichern_lehnt_ab(plugin, args, teil):
    with pytest.raises(ValueError, match=teil):
        plugin.call("platz_speichern", args)


def test_platz_laden_unbekannt_und_entfernen(plugin):
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.call("platz_laden", {"name": "Nix da"})
    plugin.call("platz_speichern", {"name": "Haus", "fenster": [{"id": "seite:smarthome"}]})
    assert plugin.call("platz_entfernen", {"name": "Haus"})["entfernt"] is True
    assert plugin.call("platz_entfernen", {"name": "Haus"})["entfernt"] is False
    assert plugin.call("plaetze", {})["plaetze"] == []


def test_abholen_ignoriert_platz_mit_boesem_namen(plugin):
    plugin._r.l[shell.SCHLUESSEL_BEFEHLE] = [
        json.dumps({"aktion": "platz", "name": "x; rm"}),
        json.dumps({"aktion": "platz", "name": "Haus"}),
    ]
    assert plugin.call("abholen", {})["befehle"] == [{"aktion": "platz", "name": "Haus"}]


# ── Bildschirme und Raster ─────────────────────────────────────────────────────
def _neu():
    s = shell.ShellPlugin()
    s._r = Redis()
    return s


def test_raster_felder_und_native_flaechen():
    s = _neu()
    r = s.call(
        "merken",
        {
            "fenster": [
                {"id": "nativ:geld", "min": False, "spalten": 40, "zeilen": 1, "neueZeile": True},
                {"id": "seite:finance", "min": False, "breit": True},
                {"id": "kaputt:x"},
            ]
        },
    )
    assert r["fenster"] == 2
    z = s.call("zustand", {})
    assert z["fenster"] == [
        {"id": "nativ:geld", "min": False, "spalten": 12, "zeilen": 4, "neueZeile": True},
        {"id": "seite:finance", "min": False, "spalten": 12, "zeilen": 10},
    ]


def test_bildschirme_werden_gemerkt_jede_flaeche_nur_einmal():
    s = _neu()
    s.call(
        "merken",
        {
            "fenster": [],
            "bildschirme": [
                {"id": "b1", "name": "Geld", "fenster": [{"id": "nativ:geld", "min": False}]},
                {"id": "b2", "name": "", "fenster": [{"id": "nativ:geld"}, {"id": "app:haus__favoriten"}]},
            ],
            "aktiv": 2,
        },
    )
    z = s.call("zustand", {})
    assert [b["name"] for b in z["bildschirme"]] == ["Geld", "Bildschirm 2"]
    assert [[w["id"] for w in b["fenster"]] for b in z["bildschirme"]] == [["nativ:geld"], ["app:haus__favoriten"]]
    assert z["aktiv"] == 2


def test_befehl_bildschirm_mit_name_oder_index():
    s = _neu()
    assert s.call("befehl", {"aktion": "bildschirm", "name": "Geld"})["vorgemerkt"] == "bildschirm Geld"
    assert s.call("befehl", {"aktion": "bildschirm", "index": 0})["vorgemerkt"] == "bildschirm 0"
    with pytest.raises(ValueError):
        s.call("befehl", {"aktion": "bildschirm"})
    with pytest.raises(ValueError):
        s.call("befehl", {"aktion": "oeffnen", "flaeche": "kaputt:x"})
    befehle = [json.loads(b) for b in s._r.l[shell.SCHLUESSEL_BEFEHLE]]
    assert befehle[0]["name"] == "Geld" and befehle[1]["index"] == 0
