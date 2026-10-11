"""Plugin ``dateien``: Werkzeuge, Bestätigungspflicht, Trockenlauf, die REST-Wege zum Herunter- und Hochladen und die App.

Die Dateiablage selbst (Pfadsicherheit, Versionen, Papierkorb, Suche) prüft ``test_dateien.py``. Hier steht, was das
Plugin daraus macht: welche Werkzeuge es anbietet, dass nichts Schreibendes ohne Plan und Bestätigung läuft, dass
heruntergeladener Fremdinhalt nie als Seite im Ursprung der Shell läuft, und dass die App nur Werkzeuge ruft, die es gibt.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcp_hub import dateien as store
from mcp_hub import registry as hub_registry
from mcp_hub import server as hub_server
from mcp_hub.plugins import _identitaet
from mcp_hub.plugins.dateien import DateienPlugin, auslieferung
from mcp_hub.plugins._oberflaeche import UI_DIR

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"
SCOPES = {"read", "write", "destructive", "exec"}


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    monkeypatch.delenv("FYOS_DATEIEN", raising=False)
    store.verzeichnis_anmelden(None)
    yield
    store.verzeichnis_anmelden(None)


@pytest.fixture
def plugin(tmp_path):
    p = DateienPlugin({"verzeichnis": str(tmp_path / "ablage")})
    (tmp_path / "ablage").mkdir()
    p.register()
    yield p
    p.shutdown()


def ausfuehren(p, name, **args):
    """Echter Lauf eines schreibenden Werkzeugs: mit Bestätigung."""
    return p.call(name, {**args, "bestaetigt": True})


# ── Beschreibung ────────────────────────────────────────────────────────────────────────────────────


def test_werkzeuge_haben_genau_einen_scope_und_sind_fuer_apps_freigegeben(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert set(tools) == {
        "liste", "lesen", "suchen", "schreiben", "verschieben", "loeschen", "ordner_anlegen",
        "papierkorb", "wiederherstellen", "versionen", "version_zurueck", "vorschau",
    }
    for t in tools.values():
        assert len(SCOPES & set(t.tags)) == 1, t.name
        assert "flaeche" in t.tags, f"{t.name}: ohne Tag flaeche kann die App es nicht rufen"
    assert "destructive" in tools["loeschen"].tags
    for name in ("schreiben", "verschieben", "ordner_anlegen", "wiederherstellen", "version_zurueck", "loeschen"):
        assert "bestaetigt" in tools[name].input_schema["properties"], name
    assert all(t.input_schema.get("additionalProperties") is False for t in tools.values())


def test_nur_liste_oeffnet_die_app_und_vorschau_ist_nur_fuer_die_app(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert tools["liste"].meta["ui"] == {"resourceUri": "ui://fyos/dateien.html"}
    assert tools["vorschau"].meta["ui"]["visibility"] == ["app"]
    for name, t in tools.items():
        if name not in ("liste", "vorschau"):
            assert not (t.meta or {}).get("ui"), name
    res = plugin.describe_resources()
    assert [r.uri for r in res] == ["ui://fyos/dateien.html"]
    assert "const App" in res[0].read()


def test_identitaet_der_app():
    app = _identitaet.fuer_datei("dateien.html")
    assert app and app["titel"] == "Dateien" and app["kategorie"] == "System"
    assert _identitaet.bruecken_konfig("dateien.html")["werkzeug"] == "dateien__liste"


def test_ding_typ_fuer_spaeter_steht_fest():
    from mcp_hub.plugins import dateien as modul

    assert modul.DING_TYP == "datei"


# ── Nicht eingerichtet ──────────────────────────────────────────────────────────────────────────────


def test_ohne_ablage_antwortet_das_plugin_mit_einem_klaren_zustand():
    p = DateienPlugin()
    p.register()
    r = p.call("liste", {})
    assert r["zustand"] == "nicht eingerichtet" and r["eintraege"] == [] and "FYOS_DATEIEN" in r["hinweis"]
    r = p.call("lesen", {"pfad": "a.md"})
    assert r["ok"] is False and r["zustand"] == "nicht eingerichtet"
    assert p.call("schreiben", {"pfad": "a.md", "inhalt": "x", "bestaetigt": True})["ok"] is False
    h = p.health()
    assert h["ok"] is True and h["eingerichtet"] is False


def test_umgebungsvariable_richtet_die_ablage_ein(tmp_path, monkeypatch):
    monkeypatch.setenv("FYOS_DATEIEN", str(tmp_path))
    p = DateienPlugin()
    p.register()
    assert p.call("liste", {})["zustand"] == "ok"
    assert p.health()["eingerichtet"] is True


# ── Lesen ───────────────────────────────────────────────────────────────────────────────────────────


def test_schreiben_lesen_liste_suchen(plugin):
    ausfuehren(plugin, "schreiben", pfad="Projekt/Notizen/heute.md", inhalt="# Heute\nStrom prüfen")
    l1 = plugin.call("liste", {})
    assert l1["zustand"] == "ok" and [e["name"] for e in l1["eintraege"]] == ["Projekt"]
    assert "1 Einträge" in l1["satz"] or "1 Eintrag" in l1["satz"]
    l2 = plugin.call("liste", {"pfad": "Projekt/Notizen/heute.md"})  # eine Datei zeigt ihren Ordner und wählt sie aus
    assert l2["pfad"] == "Projekt/Notizen" and l2["auswahl"] == "Projekt/Notizen/heute.md"
    r = plugin.call("lesen", {"pfad": "Projekt/Notizen/heute.md"})
    assert r["art"] == "text" and r["text"].startswith("# Heute") and "Fremdinhalt" in r["hinweis"]
    assert r["url"].endswith("/hub-api/dateien/datei?pfad=Projekt/Notizen/heute.md")
    s = plugin.call("suchen", {"abfrage": "strom"})
    assert [t["pfad"] for t in s["treffer"]] == ["Projekt/Notizen/heute.md"] and s["treffer"][0]["treffer"] == "inhalt"
    assert "Fremdinhalt" in s["hinweis"]


def test_binaeres_kommt_als_angaben_mit_adresse(plugin):
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
    ausfuehren(plugin, "schreiben", pfad="bild.png", inhalt_base64=base64.b64encode(png).decode())
    r = plugin.call("lesen", {"pfad": "bild.png"})
    assert r["art"] == "binaer" and r["text"] is None and r["groesse"] == len(png) and "url" in r
    v = plugin.call("vorschau", {"pfad": "bild.png"})
    assert base64.b64decode(v["daten_base64"]) == png and v["typ"] == "image/png"


def test_lesen_einer_fruehren_fassung(plugin):
    ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="eins")
    ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="zwei", ueberschreiben=True)
    v = plugin.call("versionen", {"pfad": "a.md"})["versionen"]
    assert len(v) == 1
    assert plugin.call("lesen", {"pfad": "a.md", "version": v[0]["version"]})["text"] == "eins"
    assert plugin.call("lesen", {"pfad": "a.md"})["text"] == "zwei"


# ── Schreiben: Plan und Bestätigung ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,args",
    [
        ("schreiben", {"pfad": "x.md", "inhalt": "a"}),
        ("ordner_anlegen", {"pfad": "neu"}),
        ("verschieben", {"von": "x.md", "nach": "y.md"}),
        ("loeschen", {"pfad": "x.md"}),
        ("wiederherstellen", {"id": "1-abc"}),
        ("version_zurueck", {"pfad": "x.md", "version": "1"}),
    ],
)
def test_ein_echter_lauf_braucht_die_bestaetigung(plugin, name, args):
    plugin.call("schreiben", {"pfad": "x.md", "inhalt": "a", "bestaetigt": True})
    for ohne in ({**args}, {**args, "bestaetigt": False}, {**args, "bestaetigt": "ja"}):
        with pytest.raises(ValueError, match="bestaetigt"):
            plugin.call(name, ohne)


def test_ohne_bestaetigung_aendert_sich_nichts(plugin, tmp_path):
    with pytest.raises(ValueError):
        plugin.call("schreiben", {"pfad": "x.md", "inhalt": "a"})
    assert plugin.call("liste", {})["eintraege"] == []


def test_trockenlauf_zeigt_den_plan_und_aendert_nichts(plugin):
    plugin.call("schreiben", {"pfad": "alt.md", "inhalt": "a", "bestaetigt": True})
    faelle = [
        ("schreiben", {"pfad": "neu.md", "inhalt": "x"}, "anlegen"),
        ("schreiben", {"pfad": "alt.md", "inhalt": "y", "ueberschreiben": True}, "ersetzen"),
        ("ordner_anlegen", {"pfad": "Ordner/Unter"}, "Ordner"),
        ("verschieben", {"von": "alt.md", "nach": "neu/alt.md"}, "verschieben"),
        ("loeschen", {"pfad": "alt.md"}, "Papierkorb"),
    ]
    for name, args, wort in faelle:
        r = plugin.call(name, {**args, "__dry_run__": True})
        assert r["dry_run"] is True and r["ok"] is True, name
        assert wort in r["would_execute"], (name, r["would_execute"])
        assert r["expected_side_effects"], name
    # nichts davon ist passiert
    assert [e["name"] for e in plugin.call("liste", {})["eintraege"]] == ["alt.md"]
    assert plugin.call("lesen", {"pfad": "alt.md"})["text"] == "a"
    assert plugin.call("papierkorb", {})["eintraege"] == []


def test_trockenlauf_gibt_den_inhalt_nicht_weiter(plugin):
    r = plugin.call("schreiben", {"pfad": "g.md", "inhalt": "GEHEIMER-INHALT", "__dry_run__": True})
    assert "GEHEIMER-INHALT" not in str(r)


def test_vorhandene_datei_wird_nur_mit_ueberschreiben_ersetzt(plugin):
    ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="eins")
    with pytest.raises(ValueError, match="gibt es schon|existiert|vorhanden"):
        ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="zwei")
    assert plugin.call("lesen", {"pfad": "a.md"})["text"] == "eins"
    r = ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="zwei", ueberschreiben=True)
    assert r["ok"] is True and r["ersetzt"] is True


def test_schreiben_prueft_die_eingabe(plugin):
    with pytest.raises(ValueError, match="Genau eines"):
        ausfuehren(plugin, "schreiben", pfad="a.md")
    with pytest.raises(ValueError, match="Genau eines"):
        ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="x", inhalt_base64="eA==")
    with pytest.raises(ValueError, match="Basis-64"):
        ausfuehren(plugin, "schreiben", pfad="a.md", inhalt_base64="kein base64 !!")
    with pytest.raises(ValueError):
        ausfuehren(plugin, "schreiben", pfad="a.md", inhalt=5)
    with pytest.raises(ValueError):
        ausfuehren(plugin, "schreiben", pfad="../draussen.md", inhalt="x")
    with pytest.raises(ValueError):
        plugin.call("gibt_es_nicht", {})


def test_zu_grosser_inhalt_wird_vor_dem_dekodieren_abgelehnt(tmp_path, monkeypatch):
    monkeypatch.setenv("FYOS_DATEIEN_MAX_MB", "1")
    p = DateienPlugin({"verzeichnis": str(tmp_path)})
    p.register()
    zu_gross = base64.b64encode(b"x" * (2 * 1024 * 1024)).decode()
    with pytest.raises(ValueError, match="zu groß"):
        p.call("schreiben", {"pfad": "gross.bin", "inhalt_base64": zu_gross, "bestaetigt": True})
    assert p.call("liste", {})["eintraege"] == []


def test_leere_datei_anlegen(plugin):
    r = ausfuehren(plugin, "schreiben", pfad="leer.md", inhalt="")
    assert r["groesse"] == 0
    assert plugin.call("lesen", {"pfad": "leer.md"})["text"] == ""


def test_papierkorb_und_wiederherstellen(plugin):
    ausfuehren(plugin, "schreiben", pfad="Ordner/a.md", inhalt="a")
    r = ausfuehren(plugin, "loeschen", pfad="Ordner/a.md")
    assert r["ok"] is True and "Papierkorb" in r["satz"]
    assert plugin.call("liste", {"pfad": "Ordner"})["eintraege"] == []
    korb = plugin.call("papierkorb", {})["eintraege"]
    assert [k["pfad"] for k in korb] == ["Ordner/a.md"]
    plan = plugin.call("wiederherstellen", {"id": korb[0]["id"], "__dry_run__": True})
    assert plan["dry_run"] is True and plugin.call("papierkorb", {})["eintraege"]
    ausfuehren(plugin, "wiederherstellen", id=korb[0]["id"])
    assert plugin.call("lesen", {"pfad": "Ordner/a.md"})["text"] == "a"
    assert plugin.call("papierkorb", {})["eintraege"] == []


def test_version_zurueck(plugin):
    ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="eins")
    ausfuehren(plugin, "schreiben", pfad="a.md", inhalt="zwei", ueberschreiben=True)
    v = plugin.call("versionen", {"pfad": "a.md"})["versionen"][0]["version"]
    plan = plugin.call("version_zurueck", {"pfad": "a.md", "version": v, "__dry_run__": True})
    assert plan["dry_run"] is True and plugin.call("lesen", {"pfad": "a.md"})["text"] == "zwei"
    ausfuehren(plugin, "version_zurueck", pfad="a.md", version=v)
    assert plugin.call("lesen", {"pfad": "a.md"})["text"] == "eins"


def test_verschieben_und_ordner_anlegen(plugin):
    ausfuehren(plugin, "ordner_anlegen", pfad="A/B")
    ausfuehren(plugin, "schreiben", pfad="x.md", inhalt="x")
    ausfuehren(plugin, "verschieben", von="x.md", nach="A/B/y.md")
    assert plugin.call("lesen", {"pfad": "A/B/y.md"})["text"] == "x"
    with pytest.raises(ValueError):
        ausfuehren(plugin, "verschieben", von="A/B/y.md", nach="A")  # Ziel gibt es schon


# ── Auslieferung: Fremdinhalt läuft nie als Seite ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,laden,typ,art",
    [
        ("notiz.md", False, "text/plain", "inline"),
        ("daten.json", False, "text/plain", "inline"),
        ("seite.html", False, "application/octet-stream", "attachment"),
        ("seite.htm", False, "application/octet-stream", "attachment"),
        ("bild.png", False, "image/png", "inline"),
        ("zeichnung.svg", False, "image/svg+xml", "inline"),
        ("bericht.pdf", False, "application/pdf", "inline"),
        ("lied.mp3", False, "audio/mpeg", "inline"),
        ("archiv.zip", False, "application/octet-stream", "attachment"),
        ("programm.exe", False, "application/octet-stream", "attachment"),
        ("notiz.md", True, "text/markdown", "attachment"),
        ("seite.html", True, "application/octet-stream", "attachment"),
    ],
)
def test_auslieferung(name, laden, typ, art):
    t, a, kopf = auslieferung(name, laden)
    assert (t, a) == (typ, art)
    assert kopf["X-Content-Type-Options"] == "nosniff"


def test_bilder_und_svg_tragen_eine_sandbox_nur_pdf_nicht():
    assert auslieferung("z.svg", False)[2]["Content-Security-Policy"] == "sandbox"
    assert auslieferung("b.png", False)[2]["Content-Security-Policy"] == "sandbox"
    assert "Content-Security-Policy" not in auslieferung("b.pdf", False)[2]


# ── REST über den echten Hub-Stapel (Herkunftsschutz inklusive) ─────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Der Hub findet das Plugin selbst über seinen Einstiegspunkt; die Ablage kommt aus der Umgebung
    ablage = tmp_path / "rest-ablage"
    ablage.mkdir()
    monkeypatch.setenv("FYOS_DATEIEN", str(ablage))
    c = TestClient(hub_server.build_app(str(CONFIG_PATH)))
    c.ablage = ablage
    return c


EIGEN = {"Origin": "http://localhost"}


def test_hochladen_und_laden(client):
    r = client.put("/hub/dateien/datei", params={"pfad": "Ordner/a.md"}, content=b"# hallo", headers=EIGEN)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["result"]["pfad"] == "Ordner/a.md" and r.json()["result"]["groesse"] == 7
    assert (client.ablage / "Ordner" / "a.md").read_bytes() == b"# hallo"
    g = client.get("/hub/dateien/datei", params={"pfad": "Ordner/a.md"})
    assert g.status_code == 200 and g.content == b"# hallo"
    assert g.headers["content-type"].startswith("text/plain")
    assert g.headers["x-content-type-options"] == "nosniff"
    assert g.headers["content-disposition"].startswith("inline")


def test_laden_zum_herunterladen_und_html_nie_als_seite(client):
    (client.ablage / "s.html").write_text("<script>1</script>", encoding="utf-8")
    g = client.get("/hub/dateien/datei", params={"pfad": "s.html"})
    assert g.headers["content-type"].startswith("application/octet-stream")
    assert g.headers["content-disposition"].startswith("attachment")
    (client.ablage / "n.md").write_text("x", encoding="utf-8")
    g = client.get("/hub/dateien/datei", params={"pfad": "n.md", "laden": "1"})
    assert g.headers["content-disposition"].startswith("attachment") and "n.md" in g.headers["content-disposition"]


def test_umlaute_im_namen(client):
    r = client.put("/hub/dateien/datei", params={"pfad": "Rechnung März.txt"}, content="Größe".encode(), headers=EIGEN)
    assert r.status_code == 200
    g = client.get("/hub/dateien/datei", params={"pfad": "Rechnung März.txt", "laden": "1"})
    assert g.content == "Größe".encode() and "filename*=" in g.headers["content-disposition"]


def test_vorhandene_datei_wird_nur_mit_ueberschreiben_ersetzt_rest(client):
    client.put("/hub/dateien/datei", params={"pfad": "a.md"}, content=b"eins", headers=EIGEN)
    r = client.put("/hub/dateien/datei", params={"pfad": "a.md"}, content=b"zwei", headers=EIGEN)
    assert r.status_code == 409 and r.json()["kind"] == "existiert" and r.json()["ok"] is False
    assert (client.ablage / "a.md").read_bytes() == b"eins"
    r = client.put("/hub/dateien/datei", params={"pfad": "a.md", "ueberschreiben": "1"}, content=b"zwei", headers=EIGEN)
    assert r.status_code == 200 and r.json()["result"]["ersetzt"] is True
    assert (client.ablage / "a.md").read_bytes() == b"zwei"


def test_pfade_ausserhalb_werden_abgewiesen(client, tmp_path):
    (tmp_path / "geheim.txt").write_text("geheim", encoding="utf-8")
    for pfad in ("../geheim.txt", "a/../../geheim.txt", "..", "", ".fyos/tmp/x", "a\x00b"):
        g = client.get("/hub/dateien/datei", params={"pfad": pfad})
        assert g.status_code in (400, 404), (pfad, g.status_code)
        assert "geheim" not in g.text
        p = client.put("/hub/dateien/datei", params={"pfad": pfad}, content=b"x", headers=EIGEN)
        assert p.status_code in (400, 404), (pfad, p.status_code)
    assert not (tmp_path / "x").exists()


def test_absoluter_pfad_gilt_nur_innerhalb_der_ablage(client):
    r = client.put("/hub/dateien/datei", params={"pfad": "/etc/passwd"}, content=b"x", headers=EIGEN)
    assert r.status_code == 200 and r.json()["result"]["pfad"] == "etc/passwd"
    assert (client.ablage / "etc" / "passwd").read_bytes() == b"x"


def test_symlink_nach_draussen_wird_nicht_ausgeliefert(client, tmp_path):
    (tmp_path / "geheim.txt").write_text("geheim", encoding="utf-8")
    (client.ablage / "link.txt").symlink_to(tmp_path / "geheim.txt")
    g = client.get("/hub/dateien/datei", params={"pfad": "link.txt"})
    assert g.status_code in (400, 404) and "geheim" not in g.text


def test_fehlende_datei_ist_404_ein_ordner_ist_kein_download(client):
    assert client.get("/hub/dateien/datei", params={"pfad": "gibt-es-nicht.md"}).status_code == 404
    (client.ablage / "Ordner").mkdir()
    assert client.get("/hub/dateien/datei", params={"pfad": "Ordner"}).status_code in (400, 404)


def test_zu_grosse_datei_wird_abgelehnt_und_nicht_geschrieben(client, monkeypatch):
    monkeypatch.setenv("FYOS_DATEIEN_MAX_MB", "1")
    # die Ablage ist beim ersten Zugriff im Cache; ein neuer Wert gilt, weil `quelle()` die Umgebung jedes Mal liest
    r = client.put("/hub/dateien/datei", params={"pfad": "gross.bin"}, content=b"x" * (2 * 1024 * 1024), headers=EIGEN)
    assert r.status_code == 413 and r.json()["kind"] == "zu_gross"
    assert not (client.ablage / "gross.bin").exists()
    # auch ohne Längenangabe (Stücke) wird abgebrochen, sobald es zu viel wird
    def stuecke():
        for _ in range(40):
            yield b"x" * (64 * 1024)

    r = client.put("/hub/dateien/datei", params={"pfad": "gross2.bin"}, content=stuecke(), headers=EIGEN)
    assert r.status_code == 413
    assert not (client.ablage / "gross2.bin").exists()


def test_fremde_herkunft_darf_nicht_hochladen(client):
    for kopf in ({"Origin": "null"}, {"Origin": "https://boese.example"}, {"Sec-Fetch-Site": "cross-site"}):
        r = client.put("/hub/dateien/datei", params={"pfad": "x.md"}, content=b"x", headers=kopf)
        assert r.status_code == 403, kopf
    assert not (client.ablage / "x.md").exists()


def test_nur_get_und_put(client):
    for methode in ("post", "delete", "patch"):
        r = getattr(client, methode)("/hub/dateien/datei", params={"pfad": "a.md"}, headers=EIGEN)
        assert r.status_code == 405, methode


def test_ohne_ablage_antwortet_rest_mit_501():
    c = TestClient(hub_server.build_app(str(CONFIG_PATH)))
    assert c.get("/hub/dateien/datei", params={"pfad": "a.md"}).status_code == 501
    assert c.put("/hub/dateien/datei", params={"pfad": "a.md"}, content=b"x", headers=EIGEN).status_code == 501


def test_unerwarteter_fehler_nennt_keine_pfade(client, monkeypatch):
    def kaputt(*a, **k):
        raise RuntimeError("/Users/geheim/pfad kaputt")

    monkeypatch.setattr(store.Verzeichnis, "datei_pfad", kaputt)
    g = client.get("/hub/dateien/datei", params={"pfad": "a.md"})
    assert g.status_code == 500 and "geheim" not in g.text


def test_app_call_ruft_die_werkzeuge_der_oberflaeche(client):
    r = client.post("/hub/app-call", json={"tool": "dateien.liste", "arguments": {}}, headers=EIGEN)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["result"]["zustand"] == "ok"
    # schreibend nur mit Plan: der Trockenlauf geht, der echte Lauf ohne Bestätigung nicht
    plan = client.post("/hub/app-call", json={"tool": "dateien.schreiben", "arguments": {"pfad": "a.md", "inhalt": "x", "__dry_run__": True}}, headers=EIGEN)
    assert plan.status_code == 200 and plan.json()["result"]["dry_run"] is True
    echt = client.post("/hub/app-call", json={"tool": "dateien.schreiben", "arguments": {"pfad": "a.md", "inhalt": "x"}}, headers=EIGEN)
    assert echt.status_code == 400
    assert not (client.ablage / "a.md").exists()


def test_apps_liste_fuehrt_die_oberflaeche(client):
    r = client.get("/hub/apps")
    assert r.status_code == 200
    namen = {a["name"]: a for a in r.json()["apps"]}
    assert "dateien__liste" in namen and namen["dateien__liste"]["_meta"]["ui"]["resourceUri"] == "ui://fyos/dateien.html"
    assert namen["dateien__vorschau"]["_meta"]["ui"]["visibility"] == ["app"]


# ── Die App ruft nur, was es gibt ───────────────────────────────────────────────────────────────────


def test_app_ruft_nur_vorhandene_werkzeuge(plugin):
    html = (UI_DIR / "dateien.html").read_text(encoding="utf-8")
    tools = {t.name for t in plugin.describe_tools()}
    gerufen = set(re.findall(r'rufen\("([a-z_]+)"\s*[,)]', html)) | set(re.findall(r'werkzeug:\s*"dateien__([a-z_]+)"', html))
    assert gerufen, "die App ruft gar nichts?"
    assert gerufen <= tools, f"die App ruft unbekannte Werkzeuge: {sorted(gerufen - tools)}"
    # alle schreibenden Aufrufe der App gehen über App.beantragen (Plan, dann Ja), nie direkt über rufen()
    for schreibend in ("schreiben", "verschieben", "loeschen", "ordner_anlegen", "wiederherstellen", "version_zurueck"):
        assert f'rufen("{schreibend}"' not in html, f"{schreibend} darf nur über App.beantragen laufen"


def test_zeilen_der_app_tragen_das_ding_fuer_spaeter():
    html = (UI_DIR / "dateien.html").read_text(encoding="utf-8")
    assert 'data-typ="datei"' in html and "data-id=" in html


def test_app_hat_kein_eigenes_netz():
    html = (UI_DIR / "dateien.html").read_text(encoding="utf-8")
    for verboten in ("fetch(", "XMLHttpRequest", "WebSocket", "innerHTML = " + "location", "eval(", "new Function"):
        assert verboten not in html, verboten
