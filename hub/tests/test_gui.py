"""gui — gebaute Ansichten: Prüfen, Ablage in mcp_hub.kv, Link-Umlenkung, Vorlagen und Skill als Paketdaten,
die Seiten unter /hub/gui/{id} und die Sandbox der Oberfläche."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import tomllib
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from mcp_hub import kv
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.plugin import HubPlugin, ToolDescriptor
from mcp_hub.plugins import gui as gui_mod
from mcp_hub.plugins.gui import GuiPlugin, dokument_id, dokument_pruefen
from mcp_hub.plugins.skills import SkillsPlugin

VORLAGEN = {"ablauf", "balken", "kennzahlen", "status", "tabelle", "vergleich", "verlauf", "zeitleiste"}


@pytest.fixture()
def plugin():
    """Das Plugin mit eigener Ablage im Speicher: kein Test sieht die Ansichten eines anderen."""
    p = GuiPlugin()
    p._r = kv.SpeicherKv()
    return p


def _eingabe(link: str) -> tuple[str, dict]:
    q = parse_qs(urlparse(link).query)
    roh = q["eingabe"][0]
    return q["offen"][0], json.loads(base64.urlsafe_b64decode(roh + "=" * (-len(roh) % 4)))


class _AblageDefekt:
    """Eine Ablage, die bei jedem Zugriff scheitert (Redis nicht erreichbar)."""

    def __getattr__(self, name):
        raise ConnectionError("weg")


# ── Prüfen und Ablegen ──────────────────────────────────────────────────────────────────────────────────

def test_pruefen_verlangt_titel_und_html():
    with pytest.raises(ValueError, match="titel"):
        dokument_pruefen({"html": "<p>x</p>"})
    with pytest.raises(ValueError, match="html"):
        dokument_pruefen({"titel": "T", "html": "  "})
    with pytest.raises(ValueError, match="css muss Text"):
        dokument_pruefen({"titel": "T", "html": "<p/>", "css": 3})
    with pytest.raises(ValueError, match="zu groß"):
        dokument_pruefen({"titel": "T", "html": "x" * (gui_mod.GRENZEN["html"] + 1)})


def test_pruefen_saeubert_und_begrenzt_hoehe():
    d = dokument_pruefen({"titel": "Kosten\x07 je Platz", "html": "<svg/>", "hoehe": 99999})
    assert d["titel"] == "Kosten je Platz" and d["css"] == "" and d["js"] == "" and d["hoehe"] == gui_mod.HOEHE_MAX
    with pytest.raises(ValueError, match="hoehe"):
        dokument_pruefen({"titel": "T", "html": "<p/>", "hoehe": True})


def test_id_folgt_aus_dem_inhalt():
    a = dokument_pruefen({"titel": "T", "html": "<p>1</p>"})
    b = dokument_pruefen({"titel": "T", "html": "<p>1</p>", "hoehe": 300})
    c = dokument_pruefen({"titel": "T", "html": "<p>2</p>"})
    assert dokument_id(a) == dokument_id(b) != dokument_id(c)
    assert gui_mod.ID_MUSTER.fullmatch(dokument_id(a))


def test_bauen_legt_ab_und_verlinkt_zeigen(plugin):
    r = plugin.call("bauen", {"titel": "Rechner", "beschreibung": "Teilt die Rechnung.", "html": "<p>x</p>", "js": "1"})
    assert r["abgelegt"] is True and r["id"].startswith("g-")
    # Die Ansicht liegt in mcp_hub.kv unter einem Schlüssel des Plugins, nicht in einer Datei
    abgelegt = json.loads(plugin._r.get(gui_mod.SCHLUESSEL_DOKUMENT + r["id"]))
    assert abgelegt["titel"] == "Rechner" and abgelegt["id"] == r["id"] and abgelegt["angelegt"]
    offen, eingabe = _eingabe(r["link"])
    assert offen == "app:gui__zeigen" and eingabe == {"id": r["id"]}
    # Die Antwort fürs Modell trägt das Dokument NICHT noch einmal
    assert "html" not in json.dumps(r)


def test_bauen_zweimal_legt_nichts_doppelt_ab(plugin):
    a = plugin.bauen({"titel": "T", "html": "<p>1</p>"})
    b = plugin.bauen({"titel": "T", "html": "<p>1</p>"})
    assert a["id"] == b["id"] and list(plugin._r.hgetall(gui_mod.SCHLUESSEL_INDEX)) == [a["id"]]


def test_bauen_ohne_ablage_zeigt_trotzdem(plugin):
    plugin._r = _AblageDefekt()
    r = plugin.call("bauen", {"titel": "T", "html": "<p/>"})
    assert r["abgelegt"] is False and "Nicht abgelegt" in r["satz"]
    # Lesen meldet die fehlende Ablage verständlich, statt einen Stapel zu zeigen
    with pytest.raises(ValueError, match="nicht erreichbar"):
        plugin.call("zeigen", {})
    with pytest.raises(ValueError, match="nicht erreichbar"):
        plugin.call("zeigen", {"id": r["id"]})
    h = plugin.health()
    assert h["ok"] is False and h["status"] == "unhealthy"


def test_health_nennt_die_ablage(plugin):
    assert plugin.health() == {"ok": True, "status": "healthy", "ansichten": 0, "ablage": "speicher"}
    plugin.bauen({"titel": "T", "html": "<p/>"})
    assert plugin.health()["ansichten"] == 1


def test_zeigen_mit_id_und_liste(plugin):
    r = plugin.call("bauen", {"titel": "Ablauf", "html": "<svg/>", "css": "svg{}", "hoehe": 400})
    d = plugin.call("zeigen", {"id": r["id"]})
    assert d["dokument"] == {"titel": "Ablauf", "beschreibung": "", "html": "<svg/>", "css": "svg{}", "js": "", "hoehe": 400}
    liste = plugin.call("zeigen", {})
    assert [a["id"] for a in liste["ansichten"]] == [r["id"]]
    with pytest.raises(ValueError, match="ungültig"):
        plugin.call("zeigen", {"id": "../etc"})
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.call("zeigen", {"id": "g-000000000000"})


def test_ablage_haelt_nur_die_letzten_und_neu_gebaute_ruecken_nach(plugin, monkeypatch):
    monkeypatch.setattr(gui_mod, "ABLAGE_MAX", 3)
    ids = [plugin.bauen({"titel": f"T{i}", "html": f"<p>{i}</p>"})["id"] for i in range(3)]
    plugin.bauen({"titel": "T0", "html": "<p>0</p>"})   # dieselbe Ansicht noch einmal: gilt als benutzt
    neu = plugin.bauen({"titel": "T3", "html": "<p>3</p>"})["id"]
    assert sorted(plugin._r.hgetall(gui_mod.SCHLUESSEL_INDEX)) == sorted([ids[0], ids[2], neu])   # T1 am längsten unbenutzt
    assert plugin._r.exists(gui_mod.SCHLUESSEL_DOKUMENT + ids[1]) == 0
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.zeigen({"id": ids[1]})
    # Die Liste zeigt die zuletzt gebauten zuerst
    assert [a["id"] for a in plugin.zeigen({})["ansichten"]] == [neu, ids[0], ids[2]]


def test_oeffnen_ziel_lenkt_bauen_um(plugin):
    args = {"titel": "T", "html": "<p/>"}
    assert plugin.oeffnen_ziel("bauen", args) == ("gui.zeigen", {"id": dokument_id(dokument_pruefen(args))})
    assert plugin.oeffnen_ziel("zeigen", {"id": "g-000000000000"}) is None


@pytest.fixture()
def reg(plugin):
    r = hub_registry.PluginRegistry()
    hub_registry._register_one(r, "gui", plugin)
    return r


def test_registry_und_link_zentral(reg):
    args = {"titel": "T", "html": "<p>" + "x" * 6000 + "</p>"}   # zu groß für einen Link mit Eingabe
    ziel, ziel_args = reg.oeffnen_ziel("gui.bauen", args)
    assert ziel == "gui.zeigen" and set(ziel_args) == {"id"}
    link = hub_server.oeffnen_link_fuer(reg, "gui.bauen", args)
    assert _eingabe(link) == ("app:gui__zeigen", ziel_args)
    # Kaputte Eingabe: der Link fällt auf die Vorgabe zurück, nie ein Fehler
    assert reg.oeffnen_ziel("gui.bauen", {"titel": ""}) == ("gui.bauen", {"titel": ""})
    # Andere Plugins ohne Haken bleiben, wie sie sind
    assert reg.oeffnen_ziel("gibt.es_nicht", {"a": 1}) == ("gibt.es_nicht", {"a": 1})


def test_werkzeuge_sind_lesende_apps(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert set(tools) == {"bauen", "zeigen", "vorlagen"}
    for t in tools.values():
        assert hub_registry.scope_from_tags(t.tags) == "READ"
    for name in ("bauen", "zeigen"):
        assert tools[name].meta["ui"]["resourceUri"] == gui_mod.UI_GUI
        assert tools[name].meta["app"]["symbol"] == "wand-sparkles"
        assert tools[name].meta["app"]["kategorie"] == "System"
    assert not tools["vorlagen"].meta   # reines Modell-Werkzeug, keine App


def test_oberflaeche_isoliert_das_fragment(plugin):
    (res,) = plugin.describe_resources()
    assert res.meta["ui"]["csp"]["resourceDomains"] == gui_mod.CDN
    assert "connectDomains" not in res.meta["ui"]["csp"]   # erzeugte Ansichten holen nichts nach
    html = res.read()
    assert "/*STIL*/" not in html and "/*BRUECKE*/" not in html and "<!--KOPF-->" not in html
    rahmen = re.search(r'<iframe id="rahmen"[^>]*>', html).group(0)
    assert 'sandbox="allow-scripts"' in rahmen and "allow-same-origin" not in rahmen
    # Nachrichten aus dem Rahmen nur von unserem Rahmen, Links nur https, ins Gespräch nur mit Fähigkeit
    assert "e.source !== rahmen.contentWindow" in html
    assert 'App.kann("message")' in html and "^https:" in html


def test_eigenstaendig_bettet_die_app_mit_derselben_sandbox_ein():
    doc = dokument_pruefen({"titel": "A <b>&", "html": "<p>x</p><script>1</script>", "js": "'</script><script>'"})
    seite = gui_mod.eigenstaendig(doc, "https://fyos.example/os?offen=app:gui__zeigen")
    assert seite.startswith("<!doctype html>")
    assert "<title>A &lt;b&gt;&amp;</title>" in seite
    app = re.search(r'<iframe id="app"[^>]*>', seite).group(0)
    attribute = app.split(" srcdoc=", 1)[0]
    assert 'sandbox="allow-scripts"' in attribute and "allow-same-origin" not in attribute
    # CSP der App wie in der Shell (web/src/lib/mcp-apps/host.ts): nichts nach außen, keine fremden Rahmen
    assert "connect-src &#x27;none&#x27;" in app and "https://esm.sh" in app
    # Das Dokument steht als JSON im Host-Skript und kann das Skript nicht schließen
    host = seite.split("<script>", 1)[1]
    assert "</script>" not in host.split("const ANSICHT = ", 1)[1].split(";\n", 1)[0]
    assert "e.source !== f.contentWindow" in seite and "^https:" in seite


def test_eigenstaendig_nimmt_nur_https_links():
    doc = dokument_pruefen({"titel": "T", "html": "<p/>"})
    assert 'const LINK = "";' in gui_mod.eigenstaendig(doc, "javascript:alert(1)")


# ── Vorlagen und Skill als Paketdaten ───────────────────────────────────────────────────────────────────

def test_vorlagen_und_skill_sind_paketdaten_des_kerns():
    """Alles liegt unter mcp_hub/skills/generative-ui und wird über importlib.resources gelesen (nie über einen festen Pfad)."""
    basis = resources.files("mcp_hub") / "skills" / "generative-ui"
    assert (basis / "SKILL.md").is_file() and (basis / "references" / "svg-diagramme.md").is_file()
    assert {p.name for p in (basis / "vorlagen").iterdir() if p.is_dir()} == VORLAGEN
    for name in VORLAGEN:
        for datei in ("vorlage.json", "ansicht.html", "ansicht.css", "ansicht.js"):
            assert (basis / "vorlagen" / name / datei).is_file(), (name, datei)


def test_pyproject_liefert_skill_und_vorlagen_mit():
    """Rad und Quellpaket brauchen die Paketdaten und den Entry-Point; unabhängig davon, was gerade installiert ist."""
    pyproject = Path(gui_mod.__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("kein Quellbaum (installiertes Paket)")
    daten = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert "skills/**/*" in daten["tool"]["setuptools"]["package-data"]["mcp_hub"]
    assert daten["project"]["entry-points"]["fyos.skills"]["kern"] == "mcp_hub"
    assert daten["project"]["entry-points"]["mcp_hub.plugins"]["gui"] == "mcp_hub.plugins.gui:GuiPlugin"


def test_skill_kommt_ueber_den_entry_point_des_kerns(tmp_path):
    """skills.suchen findet generative-ui ohne jede Konfiguration, allein über die Gruppe fyos.skills."""
    skills = SkillsPlugin({"quellen": [str(tmp_path / "leer")], "scan_ttl_s": 0})
    treffer = [s for s in skills.call("suchen", {"q": "generative-ui"})["skills"] if s["name"] == "generative-ui"]
    assert treffer, "Entry-Point fyos.skills fehlt: Paket neu installieren (pip install -e hub)"
    assert treffer[0]["quelle"] == "kern"
    gelesen = skills.call("lesen", {"name": "generative-ui"})
    assert "gui.bauen" in gelesen["text"] and gelesen["dateien"] == ["svg-diagramme.md"]
    assert "<svg" in skills.call("lesen", {"name": "generative-ui", "datei": "svg-diagramme.md"})["text"]


def test_skill_ist_frei_von_wegen_ausserhalb_des_pakets():
    """Der Skill verweist nur auf Werkzeuge und Dateien, die es in der Distribution gibt."""
    text = (resources.files("mcp_hub") / "skills" / "generative-ui" / "SKILL.md").read_text(encoding="utf-8")
    kopf = text.split("---", 2)[1]
    assert re.search(r"^name:\s*generative-ui\s*$", kopf, re.M) and re.search(r"^description:", kopf, re.M)
    for verboten in ("scripts/ops", "/daten/", "FYOS_REPO_PATH", "docs/current"):
        assert verboten not in text, verboten


def test_jede_vorlage_ist_vollstaendig_und_ihr_beispiel_passt(plugin):
    """Jede Vorlage: vorlage.json mit titel/zweck/schema/beispiel, html und js; das Beispiel besteht die Prüfung."""
    liste = plugin.vorlagen_zeigen({})["vorlagen"]
    namen = {v["name"] for v in liste}
    assert namen == VORLAGEN
    for name in namen:
        v = gui_mod.vorlage_laden(plugin.vorlagen, name)
        assert v["titel"] and v["zweck"] and isinstance(v["schema"], dict) and v["beispiel"], name
        assert v["html"].strip() and "GUI.beiDaten" in v["js"], name
        assert gui_mod.daten_pruefen(v["beispiel"], v["schema"]) == [], name
        # Kein Hex für Text oder Flächen in Vorlagen-CSS außer Kategorienfarben von Linien (verlauf)
        if name != "verlauf":
            assert not re.search(r"#[0-9a-fA-F]{3,6}\b", v["css"]), name


def test_vorlagen_beispiele_sind_ausdruecklich_beispielwerte(plugin):
    """Ein Beispiel darf nie wie Messwerte aussehen: jede Vorlage mit `herkunft` nennt sie Beispielwerte."""
    for v in plugin.vorlagen_zeigen({})["vorlagen"]:
        beispiel = plugin.vorlagen_zeigen({"name": v["name"]})["beispiel"]
        if "herkunft" in beispiel:
            assert beispiel["herkunft"] == "Beispielwerte", v["name"]


def test_eigener_vorlagenordner_ersetzt_die_des_kerns(tmp_path):
    ordner = tmp_path / "meine"
    (ordner / "karte").mkdir(parents=True)
    (ordner / "karte" / "vorlage.json").write_text(
        json.dumps({"titel": "Karte", "zweck": "Eine Zahl.", "schema": {"type": "object"}, "beispiel": {}}), encoding="utf-8")
    (ordner / "karte" / "ansicht.html").write_text("<p>Karte</p>", encoding="utf-8")
    p = GuiPlugin({"vorlagen": str(ordner)})
    p._r = kv.SpeicherKv()
    assert [v["name"] for v in p.vorlagen_zeigen({})["vorlagen"]] == ["karte"]
    assert p.bauen({"titel": "K", "vorlage": "karte", "daten": {}})["abgelegt"] is True
    with pytest.raises(ValueError, match="gibt es nicht"):
        p.vorlagen_zeigen({"name": "balken"})


def test_vorlagenname_kommt_nicht_aus_dem_pfad(plugin):
    for name in ("../balken", "balken/..", "..", "/etc", "Balken", "b"):
        assert gui_mod.vorlage_laden(plugin.vorlagen, name) is None, name


def test_bauen_mit_vorlage_bettet_daten_ein(plugin):
    r = plugin.bauen({"titel": "Zahlen", "vorlage": "kennzahlen", "daten": {"kacheln": [{"titel": "A", "wert": 1, "hinweis": "</script><b>"}]}})
    doc = plugin.zeigen({"id": r["id"]})["dokument"]
    assert doc["vorlage"] == "kennzahlen"
    block = re.search(r'<script type="application/json" id="gui-daten">(.*?)</script>', doc["html"], re.S).group(1)
    assert "</" not in block and json.loads(block)["kacheln"][0]["hinweis"] == "</script><b>"
    assert "GUI.beiDaten" in doc["js"]


def test_bauen_mit_vorlage_prueft_die_daten(plugin):
    with pytest.raises(ValueError, match="daten fehlen"):
        plugin.bauen({"titel": "T", "vorlage": "kennzahlen"})
    with pytest.raises(ValueError, match=r"daten\.kacheln fehlt"):
        plugin.bauen({"titel": "T", "vorlage": "kennzahlen", "daten": {}})
    with pytest.raises(ValueError, match=r"ton: erlaubt"):
        plugin.bauen({"titel": "T", "vorlage": "kennzahlen", "daten": {"kacheln": [{"titel": "A", "wert": 1, "ton": "lila"}]}})
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.bauen({"titel": "T", "vorlage": "gibtsnicht", "daten": {}})
    with pytest.raises(ValueError, match="nicht beides"):
        plugin.bauen({"titel": "T", "vorlage": "kennzahlen", "html": "<p/>", "daten": {"kacheln": []}})
    # umformen: Rohdaten statt Vorlagenform — die Prüfung übernimmt die Ansicht, die Funktion steht vor dem Vorlagen-js
    r = plugin.bauen({"titel": "T", "vorlage": "kennzahlen", "daten": {"n": 3}, "umformen": "d => ({kacheln: [{titel: 'n', wert: d.n}]})"})
    js = plugin.zeigen({"id": r["id"]})["dokument"]["js"]
    assert js.startswith("GUI.umformen = (d => ({kacheln:")


def test_vorlagen_werkzeug_liefert_form_und_beispiel(plugin):
    v = plugin.vorlagen_zeigen({"name": "balken"})
    assert v["schema"]["required"] == ["reihen"] and v["beispiel"]["reihen"]
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.vorlagen_zeigen({"name": "nix"})


# ── Live-Quellen ────────────────────────────────────────────────────────────────────────────────────────

class _Quelle(HubPlugin):
    name = "probe"
    version = "1"
    description = "Testquelle"

    def __init__(self):
        super().__init__()
        self.n = 0

    def register(self) -> None:
        pass

    def describe_tools(self):
        offen = {"type": "object", "additionalProperties": True}
        return [
            ToolDescriptor(name="lesen", description="liest", input_schema=offen, tags=["probe", "read"]),
            ToolDescriptor(name="schreiben", description="schreibt", input_schema=offen, tags=["probe", "write"]),
        ]

    def call(self, _method, _args):
        self.n += 1
        return {"lage": {"kacheln": [{"titel": "Aufrufe", "wert": self.n}]}}


@pytest.fixture()
def mit_quelle(plugin):
    r = hub_registry.PluginRegistry()
    q = _Quelle()
    hub_registry._register_one(r, "gui", plugin)
    hub_registry._register_one(r, "probe", q)
    plugin.registry_anbinden(r)
    return plugin, q


def test_quelle_nur_lesend_und_vorhanden(mit_quelle):
    plugin, _ = mit_quelle
    basis = {"titel": "Live", "vorlage": "kennzahlen"}
    with pytest.raises(ValueError, match="nicht nur lesend"):
        plugin.bauen({**basis, "quelle": {"werkzeug": "probe.schreiben"}})
    with pytest.raises(ValueError, match="gibt es nicht"):
        plugin.bauen({**basis, "quelle": {"werkzeug": "probe.fehlt"}})
    with pytest.raises(ValueError, match="gui selbst"):
        plugin.bauen({**basis, "quelle": {"werkzeug": "gui.zeigen"}})
    with pytest.raises(ValueError, match="plugin.werkzeug"):
        plugin.bauen({**basis, "quelle": {"werkzeug": "rm -rf"}})


def test_quelle_liefert_frische_daten_bei_jedem_zeigen(mit_quelle):
    plugin, q = mit_quelle
    args = {"titel": "Live", "vorlage": "kennzahlen", "quelle": {"werkzeug": "probe.lesen", "pfad": "lage", "takt": 5}}
    r = plugin.bauen(args)
    assert q.n == 1
    # Die Id hängt nicht an den Daten: dieselbe Ansicht derselben Quelle, auch für den Link (ohne Abruf)
    assert plugin.oeffnen_ziel("bauen", args) == ("gui.zeigen", {"id": r["id"]}) and q.n == 1
    z = plugin.zeigen({"id": r["id"]})
    assert z["dokument"]["quelle"] == {"werkzeug": "probe.lesen", "argumente": {}, "pfad": "lage", "takt": gui_mod.TAKT_MIN}
    assert '"wert": 2' in z["dokument"]["html"] and z["stand"]
    nur = plugin.zeigen({"id": r["id"], "nur_daten": True})
    assert nur["daten"] == {"kacheln": [{"titel": "Aufrufe", "wert": 3}]} and "dokument" not in nur


def test_quelle_faellt_auf_den_abgelegten_stand_zurueck(mit_quelle, monkeypatch):
    plugin, q = mit_quelle
    r = plugin.bauen({"titel": "Live", "vorlage": "kennzahlen", "quelle": {"werkzeug": "probe.lesen", "pfad": "lage"}})
    monkeypatch.setattr(q, "call", lambda _m, _a: (_ for _ in ()).throw(RuntimeError("weg")))
    z = plugin.zeigen({"id": r["id"]})
    assert "Nicht aktualisiert" in z["hinweis"] and '"wert": 1' in z["dokument"]["html"]
    with pytest.raises(ValueError):
        plugin.zeigen({"id": r["id"], "nur_daten": True})


def test_eigenstaendig_mit_daten_url_bleibt_live():
    doc = dokument_pruefen({"titel": "T", "html": "<p/>"})
    ohne = gui_mod.eigenstaendig(doc)
    assert 'DATEN = ""' in ohne and 'const ERGEBNIS = {}' in ohne
    mit = gui_mod.eigenstaendig(doc, "", ergebnis={"id": "g-0123456789ab", "stand": "s", "dokument": {"html": "x"}},
                                daten_url="/hub/gui/g-0123456789ab/daten")
    assert 'DATEN = "/hub/gui/g-0123456789ab/daten"' in mit and "serverTools" in mit
    # Das Dokument steht einmal (ANSICHT), nicht noch einmal im Ergebnis
    assert 'const ERGEBNIS = {"id": "g-0123456789ab", "stand": "s"}' in mit
    # Nur Pfade auf dem eigenen Ursprung
    assert 'DATEN = ""' in gui_mod.eigenstaendig(doc, daten_url="https://fremd.example/x")


def test_oberflaeche_kennt_vorlagen_und_live(plugin):
    (res,) = plugin.describe_resources()
    html = res.read()
    for stelle in ("window.GUI = {", "beiDaten(fn)", 'typ !== "gui-daten"', "gui__zeigen\", { id: liveId, nur_daten: true }",
                   'App.kann("serverTools")', "!bekommen && !erwartet"):
        assert stelle in html, stelle


# ── Die Wege des Hubs: GET /hub/gui/{id} und /hub/gui/{id}/daten ────────────────────────────────────────

@pytest.fixture()
def hub(monkeypatch, tmp_path):
    """Der echte Hub (build_app) mit dem Plugin gui aus den Einstiegspunkten; seine Ablage gehört diesem Test."""
    monkeypatch.setattr(hub_server, "_REGISTRY", None)   # build_app setzt es neu, monkeypatch stellt es wieder her
    app = hub_server.build_app(str(tmp_path / "keine-config.yaml"))
    gui = hub_server._REGISTRY.plugins["gui"]
    gui._r = kv.SpeicherKv()
    return TestClient(app), gui, hub_server._REGISTRY


def test_hub_mountet_die_wege_nur_lesend(hub):
    client, _, _ = hub
    wege = {r.path: set(r.methods) for r in client.app.routes if getattr(r, "path", "").startswith("/hub/gui/")}
    assert wege == {"/hub/gui/{id}": {"GET", "HEAD"}, "/hub/gui/{id}/daten": {"GET", "HEAD"}}
    assert client.post("/hub/gui/g-0123456789ab").status_code == 405


def test_hub_liefert_die_ansicht_als_seite(hub):
    client, gui, reg = hub
    hub_registry._register_one(reg, "probe", _Quelle())
    r = gui.bauen({"titel": "Live <x>", "vorlage": "kennzahlen", "quelle": {"werkzeug": "probe.lesen", "pfad": "lage"}})
    s = client.get(f"/hub/gui/{r['id']}")
    assert s.status_code == 200 and s.headers["content-type"].startswith("text/html")
    assert s.headers["cache-control"] == "no-store"
    assert "<title>Live &lt;x&gt;</title>" in s.text and f'DATEN = "/hub/gui/{r["id"]}/daten"' in s.text
    assert '\\"wert\\": 2' in s.text or '"wert": 2' in s.text   # frische Daten beim Laden
    d = client.get(f"/hub/gui/{r['id']}/daten")
    assert d.status_code == 200 and d.json()["result"]["daten"] == {"kacheln": [{"titel": "Aufrufe", "wert": 3}]}
    assert d.headers["cache-control"] == "no-store"


def test_hub_liefert_eine_feste_ansicht_ohne_quelle(hub):
    client, gui, _ = hub
    r = gui.bauen({"titel": "Fest", "html": "<p>hallo</p>"})
    s = client.get(f"/hub/gui/{r['id']}")
    assert s.status_code == 200 and "<title>Fest</title>" in s.text and "hallo" in s.text


def test_hub_kennt_unbekannte_ansichten_nicht(hub):
    client, _, _ = hub
    fehlt = client.get("/hub/gui/g-000000000000")
    assert fehlt.status_code == 404 and fehlt.headers["content-type"].startswith("text/html")
    assert "gibt es nicht" in fehlt.text and fehlt.headers["cache-control"] == "no-store"
    assert client.get("/hub/gui/g-000000000000/daten").status_code in (400, 404)


@pytest.mark.parametrize("i", [
    "..", "../etc/passwd", "..%2f..%2fetc", "%2e%2e", "g-ZZZZZZZZZZZZ", "g-0123456789ABCDEF", "g-0123456789abc", "g-0123456789a",
    "<script>alert(1)</script>", "g-0123456789ab/../x", "g-0123456789ab\n", "", " ", "G-0123456789ab", "x" * 5000,
])
def test_hub_prueft_die_id_bevor_ein_plugin_gefragt_wird(hub, monkeypatch, i):
    """Nur `g-` und zwölf Kleinbuchstaben/Ziffern in Hex kommen durch; alles andere ist 404, ohne dass etwas gelesen wird."""
    _, gui, _ = hub

    def nie(*_a, **_k):
        raise AssertionError("die Ablage darf bei einer ungültigen Id nicht gefragt werden")

    monkeypatch.setattr(gui, "_lesen", nie)
    monkeypatch.setattr(hub_server, "dispatch_im_thread", nie)
    anfrage = Request({"type": "http", "method": "GET", "path": "/hub/gui/x", "headers": [], "path_params": {"id": i}})
    seite = asyncio.run(hub_server.rest_gui_seite(anfrage))
    daten = asyncio.run(hub_server.rest_gui_daten(anfrage))
    assert seite.status_code == 404 and daten.status_code == 404
    # Die Antwort ist immer dieselbe feste Meldung: nichts aus der Anfrage wird zurückgespiegelt
    assert b"Ansicht nicht gefunden" in seite.body and len(seite.body) < 600
    assert json.loads(daten.body)["error"] == "Ansicht nicht gefunden"


def test_hub_antwortet_vor_dem_start_mit_503(monkeypatch):
    monkeypatch.setattr(hub_server, "_REGISTRY", None)
    anfrage = Request({"type": "http", "method": "GET", "path": "/hub/gui/x", "headers": [], "path_params": {"id": "g-0123456789ab"}})
    assert asyncio.run(hub_server.rest_gui_seite(anfrage)).status_code == 503
    assert asyncio.run(hub_server.rest_gui_daten(anfrage)).status_code == 503
