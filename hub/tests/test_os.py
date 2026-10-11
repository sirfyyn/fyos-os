"""os — das Kern-Plugin der OS-Brücke: Werkzeuge, „Agent zeigt“ und das Nachholen von Mitteilungen über Nacht.

Redis ist `fakeredis`; die Uhr der Brücke ist von Hand gestellt (`Uhr`), damit „24 Stunden später“ ein Satz ist.
Der Browser-Kanal selbst (Sitzungen, Befehle, Antworten, REST) steht in `test_os_bruecke.py`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

fakeredis = pytest.importorskip("fakeredis")

from mcp_hub import os_bruecke  # noqa: E402
from mcp_hub import registry as hub_registry  # noqa: E402
from mcp_hub.plugin import HubPlugin, ToolDescriptor  # noqa: E402
from mcp_hub.plugins import os as os_plugin  # noqa: E402
from mcp_hub.registry import AUFRUFER, PluginRegistry, _register_one  # noqa: E402


class Uhr:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def vor(self, s: float) -> None:
        self.t += s


def _meldung(sitzung: str = "s-mac00001", geraet: str = "MacBook", **mehr: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        "sitzung": sitzung,
        "geraet": geraet,
        "art": "computer",
        "seite": "/os",
        "sichtbar": True,
        "aktiv_vor_s": 3,
        "version": 1,
    }
    m.update(mehr)
    return m


@pytest.fixture()
def uhr() -> Uhr:
    return Uhr()


@pytest.fixture()
def server():
    return fakeredis.FakeServer()


@pytest.fixture()
def redis(server):
    return fakeredis.FakeRedis(server=server, decode_responses=True)


@pytest.fixture()
def bruecke(redis, server, uhr):
    b = os_bruecke.Bruecke(
        redis=redis,
        redis_async=lambda: fakeredis.FakeAsyncRedis(server=server, decode_responses=True),
        zeit=uhr,
    )
    os_bruecke.setze_standard(b)
    yield b
    os_bruecke.setze_standard(None)


@pytest.fixture()
def plugin(bruecke):
    p = os_plugin.OsPlugin()
    p._b = bruecke
    return p


@pytest.fixture()
def als_agent():
    marke = AUFRUFER.set("agent-0")
    yield
    AUFRUFER.reset(marke)


def _befehle(redis, sitzung: str = "s-mac00001") -> list[dict[str, Any]]:
    return [
        json.loads(felder["d"])
        for _eid, felder in redis.xrange(os_bruecke.SCHL_BEFEHLE + sitzung)
    ]


def _mitteilungen(redis, sitzung: str = "s-mac00001") -> list[dict[str, Any]]:
    return [b["zeigt"] for b in _befehle(redis, sitzung) if b["art"] == "zeigt"]


# ── Werkzeuge ───────────────────────────────────────────────────────────────────────────────
def test_werkzeuge_haben_schemas_scope_und_keine_flaechen_markierung(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert set(tools) == {"lage", "zeigen", "ausfuehren", "mitteilen"}
    assert "read" in tools["lage"].tags
    assert all("write" in tools[n].tags for n in ("zeigen", "ausfuehren", "mitteilen"))
    assert tools["mitteilen"].input_schema["required"] == ["titel"]
    for t in tools.values():
        assert "flaeche" not in t.tags and t.meta is None  # gehört dem Agenten, nicht dem Browser
        assert t.input_schema["type"] == "object" and t.input_schema["additionalProperties"] is False
        assert len(t.description) > 200


def test_das_kernplugin_spricht_vom_agenten_und_vom_benutzer_nicht_von_namen(plugin):
    # Dass kein Name einer Person oder Installation im Repo steht, prüft tools/sauber.py für alle Dateien.
    text = json.dumps([t.description + t.title + json.dumps(t.input_schema) for t in plugin.describe_tools()])
    text += plugin.description + (os_plugin.__doc__ or "")
    assert "Agent" in text and "Benutzer" in text


def test_der_skill_nachtarbeit_kommt_mit_dem_kern(tmp_path):
    from mcp_hub.plugins.skills import SkillsPlugin

    skills = SkillsPlugin({"quellen": [str(tmp_path / "leer")], "scan_ttl_s": 0})
    treffer = [s for s in skills.call("suchen", {"q": "nachtarbeit"})["skills"] if s["name"] == "nachtarbeit"]
    assert treffer, "Skill nachtarbeit fehlt (Entry-Point fyos.skills, Ordner mcp_hub/skills/nachtarbeit)"
    gelesen = skills.call("lesen", {"name": "nachtarbeit"})
    assert "os.mitteilen" in json.dumps(gelesen) and "tools/nachtauftrag.py" in json.dumps(gelesen)


def test_lage_und_zeigen_ohne_offenes_os(plugin):
    erg = plugin.call("lage", {})
    assert erg["offen"] is False and "nirgends offen" in erg["satz"]
    z = plugin.call("zeigen", {"ziel": "app:meine_app__zeigen", "eingabe": {"x": 1}})
    assert z["gezeigt"] is False and z["grund"] == "kein_os_offen" and z["link"].startswith("/os?offen=app:meine_app__zeigen")


@pytest.mark.parametrize(
    "methode,args",
    [("zeigen", {}), ("zeigen", {"ziel": ""}), ("ausfuehren", {"werkzeug": "mit leerzeichen"}), ("mitteilen", {})],
)
def test_validiert_argumente(plugin, bruecke, methode, args):
    bruecke.melden(_meldung())
    with pytest.raises(ValueError):
        plugin.call(methode, args)


def test_unbekanntes_werkzeug(plugin):
    with pytest.raises(ValueError, match="kein Werkzeug"):
        plugin.call("tanzen", {})


def test_redis_ausfall_ist_ein_satz_kein_absturz(plugin, redis, monkeypatch):
    def kaputt(*_a, **_k):
        raise ConnectionError("Redis weg")

    for name in ("zrangebyscore", "ping"):
        monkeypatch.setattr(redis, name, kaputt)
    erg = plugin.call("lage", {})
    assert erg["ok"] is False and erg["kind"] == "redis"
    assert plugin.health()["ok"] is False


def test_health_zaehlt_sitzungen_und_wartende(plugin, bruecke):
    h = plugin.health()
    assert h["ok"] is True and h["sitzungen"] == 0 and h["ausstehend"] == 0 and h["nachholen"] is True
    plugin.call("mitteilen", {"titel": "Nachts fertig"})
    assert plugin.health()["ausstehend"] == 1


# ── Mitteilen: jemand ist da ────────────────────────────────────────────────────────────────
def test_mitteilen_stellt_dem_geraet_vor_dem_benutzer_zu(plugin, bruecke, redis, als_agent):
    bruecke.melden(_meldung(audio={"modus": "zurueckhaltend", "kopfhoerer": True}))
    bruecke.melden(_meldung("s-iphone01", "iPhone", aktiv_vor_s=100))
    erg = plugin.call(
        "mitteilen",
        {"titel": "Notizen geordnet", "text": "Zwölf Notizen, drei Themen.", "dringlichkeit": "hoch", "quelle": "Nacht"},
    )
    assert erg["zugestellt"] is True and erg["geraet"] == "MacBook" and erg["sprechen"] is True
    (z,) = _mitteilungen(redis)
    assert z["art"] == "mitteilung" and z["ziel"] == "agent" and z["titel"] == "Notizen geordnet"
    assert z["vorschau"] == "Zwölf Notizen, drei Themen." and z["untertitel"] == "Nacht"
    assert "nachgeholt" not in z
    assert _befehle(redis, "s-iphone01") == []
    assert _befehle(redis)[0]["von"] == "agent"


# ── Nachholen: niemand ist da ───────────────────────────────────────────────────────────────
def test_ohne_geraet_wird_die_mitteilung_vorgemerkt_mit_ttl(plugin, redis, uhr):
    erg = plugin.call("mitteilen", {"titel": "Notizen geordnet", "text": "Zwölf Notizen.", "ziel": "seite:notizen"})
    assert erg["zugestellt"] is False and erg["grund"] == "nicht_da"
    assert erg["vorgemerkt"] is True and erg["rueckfall"] == "vorgemerkt" and erg["ausstehend"] == 1
    assert erg["link"] == os_bruecke.deeplink("seite:notizen")
    assert "nichts weiter tun" in erg["satz"]
    (roh,) = redis.lrange(os_bruecke.SCHL_AUSSTEHEND, 0, -1)
    eintrag = json.loads(roh)
    assert eintrag["t"] == uhr() and eintrag["zeigt"]["titel"] == "Notizen geordnet"
    assert "audio" not in eintrag["zeigt"]  # den Ton entscheidet erst das Gerät, an dem sie ankommt
    ttl = redis.ttl(os_bruecke.SCHL_AUSSTEHEND)
    assert 0 < ttl <= os_bruecke.AUSSTEHEND_TTL_S == 24 * 3600


def test_dieselbe_vorgemerkte_mitteilung_steht_nur_einmal_da(plugin, redis):
    plugin.call("mitteilen", {"titel": "A"})
    doppelt = plugin.call("mitteilen", {"titel": "A"})
    assert doppelt["zugestellt"] is False and doppelt["grund"] == "doppelt" and doppelt["vorgemerkt"] is True
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 1


def test_die_liste_ist_gedeckelt_und_behaelt_die_neuesten(plugin, bruecke, redis):
    n = os_bruecke.AUSSTEHEND_MAX
    for i in range(n + 5):
        plugin.call("mitteilen", {"titel": f"Nacht {i:02d}"})
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == n
    bruecke.melden(_meldung())
    titel = [z["titel"] for z in _mitteilungen(redis)]
    assert titel == [f"Nacht {i:02d}" for i in range(5, n + 5)]


def test_morgens_kommt_alles_an_aelteste_zuerst_still_und_mit_entstehungszeit(plugin, bruecke, redis, uhr):
    plugin.call("mitteilen", {"titel": "Erste", "text": "03:12", "dringlichkeit": "hoch"})
    uhr.vor(600)
    plugin.call("mitteilen", {"titel": "Zweite"})
    uhr.vor(6 * 3600)
    erg = bruecke.melden(_meldung(audio={"modus": "interaktiv", "kopfhoerer": True}))
    assert erg["ok"] is True
    a, b = _mitteilungen(redis)
    assert (a["titel"], b["titel"]) == ("Erste", "Zweite")
    assert a["nachgeholt"] is True and b["nachgeholt"] is True
    assert a["entstanden"] == 1_800_000_000.0 and b["entstanden"] == 1_800_000_600.0
    # nachgeholt ist still, auch bei „hoch“ und mit Kopfhörern
    assert a["audio"] == {"modus": "interaktiv", "klang": False, "sprechen": False}
    assert a["art"] == "mitteilung" and a["dringlichkeit"] == "hoch"
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


def test_jede_mitteilung_kommt_genau_einmal(plugin, bruecke, redis):
    plugin.call("mitteilen", {"titel": "Einmal"})
    bruecke.melden(_meldung())
    bruecke.melden(_meldung())  # die nächste Meldung 30 s später
    bruecke.melden(_meldung("s-iphone01", "iPhone"))  # ein zweites Gerät, ebenfalls da
    assert [z["titel"] for z in _mitteilungen(redis)] == ["Einmal"]
    assert _befehle(redis, "s-iphone01") == []


def test_zwei_geraete_teilen_sich_die_liste_nie_dieselbe_mitteilung(plugin, bruecke, redis):
    for i in range(4):
        plugin.call("mitteilen", {"titel": f"M{i}"})
    bruecke.nachholen({**_meldung(), "sitzung": "s-mac00001", "zuletzt_aktiv": bruecke._zeit()})
    bruecke.nachholen({**_meldung("s-iphone01", "iPhone"), "zuletzt_aktiv": bruecke._zeit()})
    alle = [z["titel"] for z in _mitteilungen(redis)] + [z["titel"] for z in _mitteilungen(redis, "s-iphone01")]
    assert sorted(alle) == ["M0", "M1", "M2", "M3"]


@pytest.mark.parametrize(
    "mehr",
    [{"sichtbar": False}, {"aktiv_vor_s": os_bruecke.AGENT_ZEIGT_AKTIV_S + 5}],
    ids=["tab_im_hintergrund", "seit_ueber_10_min_unbenutzt"],
)
def test_nur_vor_einem_menschen_wird_ausgeliefert(plugin, bruecke, redis, mehr):
    plugin.call("mitteilen", {"titel": "Wartet"})
    bruecke.melden(_meldung(**mehr))
    assert _mitteilungen(redis) == [] and redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 1
    bruecke.melden(_meldung())  # jetzt sitzt jemand davor
    assert [z["titel"] for z in _mitteilungen(redis)] == ["Wartet"]


def test_nach_24_stunden_ist_nichts_mehr_zu_liefern(plugin, bruecke, redis, uhr):
    plugin.call("mitteilen", {"titel": "Alt"})
    uhr.vor(os_bruecke.AUSSTEHEND_TTL_S + 60)
    plugin.call("mitteilen", {"titel": "Frisch"})
    bruecke.melden(_meldung())
    assert [z["titel"] for z in _mitteilungen(redis)] == ["Frisch"]
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


def test_eine_sitzung_ohne_strom_bekommt_sie_in_der_antwort(plugin, bruecke, uhr):
    plugin.call("mitteilen", {"titel": "Für das Telefon"})
    uhr.vor(3600)
    app = {"sitzung": "app-iphone01", "geraet": "iPhone", "art": "telefon", "sichtbar": True, "aktiv_vor_s": 0, "abholen": True}
    erg = bruecke.melden(app)
    (b,) = erg["befehle"]
    assert b["art"] == "zeigt" and b["zeigt"]["titel"] == "Für das Telefon" and b["zeigt"]["nachgeholt"] is True


def test_scheitert_das_ausliefern_geht_nichts_verloren_und_die_meldung_laeuft(plugin, bruecke, redis, monkeypatch):
    plugin.call("mitteilen", {"titel": "Erste"})
    plugin.call("mitteilen", {"titel": "Zweite"})
    echt = bruecke.senden

    def kaputt(*_a, **_k):
        raise ConnectionError("Redis weg")

    monkeypatch.setattr(bruecke, "senden", kaputt)
    assert bruecke.melden(_meldung())["ok"] is True  # die Meldung selbst scheitert nicht
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 2
    monkeypatch.setattr(bruecke, "senden", echt)
    bruecke.melden(_meldung())
    assert [z["titel"] for z in _mitteilungen(redis)] == ["Erste", "Zweite"]  # Reihenfolge bleibt


def test_nachholen_laesst_sich_abschalten(redis, uhr):
    b = os_bruecke.Bruecke(redis=redis, zeit=uhr, nachholen=False)
    erg = b.mitteilen("Nachts fertig")
    assert erg["rueckfall"] == "kanal" and "vorgemerkt" not in erg
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


def test_nachholen_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("OS_NACHHOLEN", "aus")
    assert os_bruecke.Bruecke.aus_umgebung({}).nachholen_an is False
    monkeypatch.delenv("OS_NACHHOLEN")
    assert os_bruecke.Bruecke.aus_umgebung({}).nachholen_an is True
    assert os_bruecke.Bruecke.aus_umgebung({"nachholen": False}).nachholen_an is False


# ── Kanal: dringend und niemand da ──────────────────────────────────────────────────────────
class KanalAttrappe:
    """Der Weg zum Chat-Kanal des Besitzers: merkt sich die Texte, kann scheitern."""

    def __init__(self, kanal: str = "telegram") -> None:
        self.kanal = kanal
        self.texte: list[str] = []
        self.fehler: Exception | None = None

    def __call__(self, text: str) -> dict[str, Any]:
        if self.fehler is not None:
            raise self.fehler
        self.texte.append(text)
        return {"gesendet": True, "kanal": self.kanal, "gescheitert": []}


@pytest.fixture()
def kanal(bruecke):
    k = KanalAttrappe()
    bruecke._kanal_weg = k
    return k


def test_dringend_ohne_geraet_geht_sofort_in_den_chat_und_wird_nicht_vorgemerkt(plugin, redis, kanal):
    erg = plugin.call(
        "mitteilen", {"titel": "Platte voll", "text": "Der Speicher ist bei 98 %.", "dringlichkeit": "hoch"}
    )
    assert erg["zugestellt"] is True and erg["weg"] == "kanal" and erg["kanal"] == "telegram"
    assert "nichts weiter tun" in erg["satz"]
    assert kanal.texte == ["Platte voll\nDer Speicher ist bei 98 %."]
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


def test_nicht_dringend_wartet_weiter_auf_die_shell(plugin, redis, kanal):
    for d in ("niedrig", "normal", None):
        erg = plugin.call("mitteilen", {"titel": f"Fertig {d}", **({"dringlichkeit": d} if d else {})})
        assert erg["vorgemerkt"] is True and erg["rueckfall"] == "vorgemerkt" and "kanal_fehler" not in erg
    assert kanal.texte == []
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 3


def test_ist_jemand_da_bleibt_der_chat_still_auch_bei_hoch(plugin, bruecke, redis, kanal):
    bruecke.melden(_meldung())
    erg = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    assert erg["zugestellt"] is True and erg["geraet"] == "MacBook" and "weg" not in erg
    assert kanal.texte == []


def test_der_chat_text_traegt_titel_vorschau_und_nur_einen_absoluten_link(redis, uhr):
    k = KanalAttrappe("whatsapp")
    b = os_bruecke.Bruecke(redis=redis, zeit=uhr, basis_url="https://fyos.example", kanal_weg=k)
    erg = b.mitteilen("Frist läuft ab", "Morgen 12 Uhr.", "seite:notizen", dringlichkeit="hoch")
    assert erg["kanal"] == "whatsapp"
    assert k.texte[0].splitlines()[:2] == ["Frist läuft ab", "Morgen 12 Uhr."]
    assert k.texte[0].splitlines()[2].startswith("https://fyos.example/")
    k2 = KanalAttrappe()
    ohne_basis = os_bruecke.Bruecke(redis=redis, zeit=uhr, basis_url="", kanal_weg=k2)
    ohne_basis.mitteilen("Anderes", "Text", dringlichkeit="hoch")
    assert k2.texte == ["Anderes\nText"]


def test_dieselbe_dringende_mitteilung_geht_nur_einmal_in_den_chat(plugin, redis, kanal):
    erste = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    zweite = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    assert erste["zugestellt"] is True
    assert zweite["zugestellt"] is False and zweite["grund"] == "doppelt" and zweite["weg"] == "kanal"
    assert len(kanal.texte) == 1 and redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


def test_zu_viele_dringende_in_kurzer_zeit_werden_vorgemerkt(plugin, redis, kanal):
    for i in range(os_bruecke.KANAL_RATE_MAX):
        assert plugin.call("mitteilen", {"titel": f"Dringend {i}", "dringlichkeit": "hoch"})["weg"] == "kanal"
    erg = plugin.call("mitteilen", {"titel": "Dringend zu viel", "dringlichkeit": "hoch"})
    assert erg["vorgemerkt"] is True and erg["kanal_fehler"] == "zu_viele"
    assert len(kanal.texte) == os_bruecke.KANAL_RATE_MAX


def test_scheitert_der_kanal_wird_vorgemerkt_und_ein_neuer_versuch_ist_moeglich(plugin, redis, kanal):
    kanal.fehler = RuntimeError("Brücke nicht erreichbar")
    erg = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    assert erg["zugestellt"] is False and erg["vorgemerkt"] is True and erg["kanal_fehler"] == "nicht_zugestellt"
    assert "Chat-Kanal" in erg["satz"] and redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 1
    kanal.fehler = None
    wieder = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    assert wieder["weg"] == "kanal" and len(kanal.texte) == 1  # die Sperre gegen Doppeltes fiel mit dem Fehler


def test_ohne_weg_oder_mit_abgeschaltetem_kanal_bleibt_es_beim_vormerken(plugin, redis, bruecke, kanal):
    bruecke._kanal_weg = None
    erg = plugin.call("mitteilen", {"titel": "Eins", "dringlichkeit": "hoch"})
    assert erg["vorgemerkt"] is True and "kanal_fehler" not in erg
    bruecke._kanal_weg = kanal
    bruecke.kanal_an = False
    erg = plugin.call("mitteilen", {"titel": "Zwei", "dringlichkeit": "hoch"})
    assert erg["vorgemerkt"] is True and kanal.texte == []


def test_der_angemeldete_weg_gilt_fuer_die_standard_bruecke(plugin, redis):
    k = KanalAttrappe("matrix")
    os_bruecke.kanal_anmelden(k)
    assert plugin.health()["kanal"] is True
    erg = plugin.call("mitteilen", {"titel": "Platte voll", "dringlichkeit": "hoch"})
    assert erg["kanal"] == "matrix" and k.texte
    os_bruecke.kanal_anmelden(None)
    assert plugin.health()["kanal"] is False


def test_kanal_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("OS_KANAL", "aus")
    assert os_bruecke.Bruecke.aus_umgebung({}).kanal_an is False
    monkeypatch.delenv("OS_KANAL")
    assert os_bruecke.Bruecke.aus_umgebung({}).kanal_an is True
    assert os_bruecke.Bruecke.aus_umgebung({"kanal": False}).kanal_an is False


async def _erster_befehl(bruecke, sitzung: str) -> dict[str, Any]:
    """Verbindet den Strom einer Sitzung und liest bis zum ersten Befehl."""
    os_bruecke.HERUNTER.clear()
    client = bruecke.async_client()
    try:
        async for stueck in bruecke.strom(client, sitzung, None, True):
            if "event: befehl" in stueck:
                return json.loads(stueck.split("data: ", 1)[1].split("\n", 1)[0])
    finally:
        await client.aclose()
    raise AssertionError("der Strom endete ohne Befehl")


def test_beim_oeffnen_der_shell_kommt_es_ueber_den_strom(plugin, bruecke, redis, uhr):
    plugin.call("mitteilen", {"titel": "Über Nacht erledigt", "text": "Alles sortiert."})
    uhr.vor(7 * 3600)
    # Der Hub kennt den Tab (er hat sich gemeldet), die Verbindung des Stroms kommt vor der nächsten Meldung.
    sitzung = {**os_bruecke.meldung_bereinigen(_meldung()), "zuletzt_aktiv": uhr(), "gemeldet": uhr()}
    redis.set(os_bruecke.SCHL_SITZUNG + "s-mac00001", json.dumps(sitzung), ex=90)
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 1
    befehl = asyncio.run(_erster_befehl(bruecke, "s-mac00001"))
    assert befehl["art"] == "zeigt" and befehl["zeigt"]["titel"] == "Über Nacht erledigt"
    assert befehl["zeigt"]["nachgeholt"] is True
    assert redis.llen(os_bruecke.SCHL_AUSSTEHEND) == 0


# ── Agent zeigt (Ergebnis-Hook der Registry) ────────────────────────────────────────────────
class DemoApp(HubPlugin):
    name = "demo"
    version = "1"
    description = "Test-App"

    def register(self) -> None:
        pass

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="lagebild",
                description="Lagebild",
                input_schema={"type": "object"},
                tags=["demo", "read"],
                title="Lagebild",
                meta={"ui": {"resourceUri": "ui://demo/lage"}, "app": {"titel": "Übersicht"}},
            )
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        return {"satz": "Alles ruhig."}


@pytest.fixture()
def reg(plugin):
    r = PluginRegistry()
    _register_one(r, "demo", DemoApp())
    _register_one(r, "os", plugin)
    plugin.registry_anbinden(r)
    return r


def test_agent_zeigt_nutzt_den_neutralen_aufrufer(reg, bruecke, redis, als_agent):
    bruecke.melden(_meldung())
    assert hub_registry.call(reg, "demo.lagebild", {}).status == "ok"
    (z,) = _mitteilungen(redis)
    assert z["ziel"] == "app:demo__lagebild" and z["vorschau"] == "Alles ruhig."


def test_andere_aufrufer_loesen_agent_zeigt_nicht_aus(reg, bruecke, redis):
    marke = AUFRUFER.set("mcp:claude-code")
    try:
        bruecke.melden(_meldung())
        hub_registry.call(reg, "demo.lagebild", {})
    finally:
        AUFRUFER.reset(marke)
    assert _befehle(redis) == []


def test_os_ist_ein_entry_point_des_kerns():
    from mcp_hub.registry import _discover_entry_points

    assert "os" in {n for n, _ in _discover_entry_points()}
