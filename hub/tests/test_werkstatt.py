"""Werkstatt-Plugin: Kopfblock, argparse-Ableitung, Pruefung, Sicherheitsregeln, Lauf, Bus."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from mcp_hub.plugins import werkstatt as ws
from mcp_hub.plugins.werkstatt import WerkstattPlugin

KOPF = 'WERKSTATT = {{"titel": "{titel}", "zweck": "Test.", "ort": "{ort}", "wirkung": "{wirkung}", "trockenlauf": {tl}, "zeitlimit_s": {zeit}}}\n'


def _py(repo: Path, rel: str, *, wirkung="lesen", ort="hub", tl=None, zeit=30, rumpf="", titel="T") -> Path:
    p = repo / "scripts" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    kopf = KOPF.format(titel=titel, ort=ort, wirkung=wirkung, tl=repr(tl), zeit=zeit)
    p.write_text("from __future__ import annotations\nimport argparse, json, sys, time\n" + kopf + textwrap.dedent(rumpf))
    return p


LESEN = """
p = argparse.ArgumentParser()
p.add_argument("name", help="wer")
p.add_argument("--zahl", type=int, default=3, help="wie oft")
p.add_argument("--faktor", type=float)
p.add_argument("--modus", choices=["kurz", "lang"], default="kurz")
p.add_argument("--laut", action="store_true")
p.add_argument("--liste", nargs="+")
p.add_argument("--selbstprobe", action="store_true")
a = p.parse_args()
print(json.dumps([{"name": a.name, "zahl": a.zahl, "laut": a.laut, "liste": a.liste, "modus": a.modus}]))
"""

SCHREIB = """
p = argparse.ArgumentParser()
p.add_argument("--ziel", required=True)
p.add_argument("--trocken", action="store_true")
a = p.parse_args()
print(("TROCKEN " if a.trocken else "ECHT ") + a.ziel)
"""


class FakeRedis:
    def __init__(self):
        self.eintraege: list[tuple[str, dict]] = []

    def xadd(self, strom, felder, **_kw):
        self.eintraege.append((strom, felder))
        return "1-0"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _py(tmp_path, "ops/lesen.py", rumpf=LESEN, titel="Lesen")
    _py(tmp_path, "ops/schreib.py", wirkung="schreiben", tl="--trocken", rumpf=SCHREIB)
    _py(tmp_path, "ops/system_ohne.py", wirkung="system", rumpf='print("LIEF")')
    _py(tmp_path, "ops/weg.py", wirkung="loeschen", tl="--trocken", rumpf=SCHREIB)
    _py(tmp_path, "ops/weg_ohne.py", wirkung="loeschen", rumpf='print("GELOESCHT")')
    _py(tmp_path, "fle/extern.py", ort="extern", rumpf='print("GPU")')
    _py(tmp_path, "ops/langsam.py", zeit=1, rumpf="time.sleep(30)")
    _py(tmp_path, "ops/viel.py", rumpf="sys.stdout.write('x' * 300000)")
    (tmp_path / "scripts/ops/plain.py").write_text("print('nicht angemeldet')\n")
    (tmp_path / "scripts/ops/kaputt.py").write_text("WERKSTATT = dict(titel='x')\n")
    (tmp_path / "scripts/ops/unter.py").write_text(
        'WERKSTATT = {"titel": "U", "zweck": "z", "ort": "egal", "wirkung": "lesen"}\n'
        "import argparse\np = argparse.ArgumentParser()\ns = p.add_subparsers()\n"
    )
    sh = tmp_path / "scripts/sh/probe.sh"
    sh.parent.mkdir(parents=True)
    sh.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        # werkstatt:
        #   titel: Probe
        #   zweck: Shell-Probe.
        #   ort: egal
        #   wirkung: lesen
        #   zeitlimit_s: 20
        #   argumente:
        #     - {name: wort, typ: text, pflicht: true}
        #     - {name: laut, typ: schalter, flag: --laut}
        # Ende des Blocks
        echo "wort=$1 zwei=$2"
        """))
    return tmp_path


@pytest.fixture
def plugin(repo: Path, monkeypatch) -> WerkstattPlugin:
    monkeypatch.setattr(ws, "_redis", lambda: FakeRedis())
    return WerkstattPlugin(config={"repo": str(repo), "scan_ttl_s": 0})


# ── Kopfblock ───────────────────────────────────────────────────────────────
def test_py_kopf_per_ast_ohne_import(repo):
    e = ws.eintrag_lesen(repo / "scripts/ops/lesen.py", repo / "scripts")
    assert e["id"] == "ops/lesen" and e["titel"] == "Lesen" and e["ort"] == "hub"
    assert e["wirkung"] == "lesen" and e["zeitlimit_s"] == 30 and e["gesperrt"] is None


def test_nicht_angemeldet_und_kaputt(repo):
    assert ws.eintrag_lesen(repo / "scripts/ops/plain.py", repo / "scripts") is None
    e = ws.eintrag_lesen(repo / "scripts/ops/kaputt.py", repo / "scripts")
    assert e["fehler"] and e["gesperrt"].startswith("Kopfblock fehlerhaft")


def test_sh_kopf_yaml(repo):
    e = ws.eintrag_lesen(repo / "scripts/sh/probe.sh", repo / "scripts")
    assert e["titel"] == "Probe" and e["sprache"] == "bash" and e["zeitlimit_s"] == 20
    assert [a["name"] for a in e["argumente"]] == ["wort", "laut"]
    assert e["argumente"][0]["pflicht"] is True and e["argumente"][0]["flag"] is None


def test_unterbefehle_ohne_argumente_geben_hinweis(repo):
    e = ws.eintrag_lesen(repo / "scripts/ops/unter.py", repo / "scripts")
    assert e["argumente"] == [] and "add_subparsers" in e["hinweise"][0]


# ── argparse-Ableitung + Schema ─────────────────────────────────────────────
def test_argparse_ableitung_und_schema(repo):
    e = ws.eintrag_lesen(repo / "scripts/ops/lesen.py", repo / "scripts")
    namen = [a["name"] for a in e["argumente"]]
    # --selbstprobe steht nicht im Kopfblock → bleibt sichtbar (test_selbstprobe_… blendet es aus)
    assert namen == ["name", "zahl", "faktor", "modus", "laut", "liste", "selbstprobe"]
    s = ws.schema_bauen(e["argumente"])
    p = s["properties"]
    assert s["required"] == ["name"] and s["additionalProperties"] is False
    assert p["zahl"]["type"] == "integer" and p["zahl"]["default"] == 3 and p["zahl"]["description"] == "wie oft"
    assert p["faktor"]["type"] == "number"
    assert p["modus"]["enum"] == ["kurz", "lang"]
    assert p["laut"]["type"] == "boolean"
    assert p["liste"]["type"] == "array"


def test_selbstprobe_und_trockenlauf_nicht_im_formular(repo):
    _py(repo, "ops/sp.py", wirkung="schreiben", tl="--trocken", rumpf=SCHREIB + 'p.add_argument("--selbstprobe", action="store_true")\n')
    p = repo / "scripts/ops/sp.py"
    p.write_text(p.read_text().replace('"zeitlimit_s": 30', '"zeitlimit_s": 30, "selbstprobe": "--selbstprobe"'))
    e = ws.eintrag_lesen(p, repo / "scripts")
    assert [a["name"] for a in e["argumente"]] == ["ziel"]


# ── Pruefung ────────────────────────────────────────────────────────────────
def test_validierung_streng(repo):
    e = ws.eintrag_lesen(repo / "scripts/ops/lesen.py", repo / "scripts")
    assert ws.argv_bauen(e, {"name": "anna", "zahl": 2, "laut": True, "liste": ["a", "b"], "modus": "lang"}, False) == [
        "anna", "--zahl", "2", "--modus", "lang", "--laut", "--liste", "a", "b"]
    for falsch, text in [
        ({"name": "anna", "gibts": 1}, "unbekannte"),
        ({}, "Pflicht"),
        ({"name": "anna", "zahl": "zwei"}, "ganze Zahl"),
        ({"name": "anna", "zahl": True}, "ganze Zahl"),
        ({"name": "anna", "modus": "mittel"}, "nicht erlaubt"),
        ({"name": "--rm"}, "nicht mit -"),
        ({"name": "anna", "laut": "ja"}, "true/false"),
        ({"name": "anna", "liste": ["ok", "-x"]}, "nicht mit -"),
    ]:
        with pytest.raises(ValueError, match=text):
            ws.argv_bauen(e, falsch, False)
    with pytest.raises(ValueError, match="Objekt"):
        ws.argv_bauen(e, ["anna"], False)


# ── Sicherheitsregeln ───────────────────────────────────────────────────────
def test_lesen_laeuft_direkt_mit_json_daten(plugin):
    r = plugin.call("ausfuehren", {"id": "ops/lesen", "argumente": {"name": "anna; rm -rf /", "laut": True}})
    assert r["ausgefuehrt"] and r["rc"] == 0 and r["trocken"] is False
    assert r["daten"][0]["name"] == "anna; rm -rf /"  # keine Shell: der Text kommt als ein Argument an
    assert r["form"] == "tabelle"


def test_schreiben_standard_trocken_echt_nur_mit_bestaetigt(plugin):
    r = plugin.call("ausfuehren", {"id": "ops/schreib", "argumente": {"ziel": "a"}})
    assert r["ausgefuehrt"] and r["trocken"] and r["stdout"].strip() == "TROCKEN a"
    r = plugin.call("ausfuehren", {"id": "ops/schreib", "argumente": {"ziel": "a"}, "trocken": False})
    assert r["ausgefuehrt"] is False and "bestaetigt" in r["grund"]
    r = plugin.call("ausfuehren", {"id": "ops/schreib", "argumente": {"ziel": "a"}, "trocken": False, "bestaetigt": True})
    assert r["ausgefuehrt"] and r["stdout"].strip() == "ECHT a"


def test_system_ohne_trockenlauf_gesperrt(plugin):
    r = plugin.call("ausfuehren", {"id": "ops/system_ohne", "trocken": False, "bestaetigt": True})
    assert r["ausgefuehrt"] is False and "ohne Trockenlauf" in r["grund"]
    assert "stdout" not in r


def test_loeschen_nie_ausfuehren(plugin):
    for extra in ({"trocken": False}, {"trocken": False, "bestaetigt": True}):
        r = plugin.call("ausfuehren", {"id": "ops/weg", "argumente": {"ziel": "x"}, **extra})
        assert r["ausgefuehrt"] is False and "stdout" not in r
        assert r["hinweis"] == "Löschen führst du selbst aus"
        assert r["befehl"] == "python3 scripts/ops/weg.py --ziel x"  # fertiger Befehl, ohne --trocken
    # Trockenlauf darf laufen
    r = plugin.call("ausfuehren", {"id": "ops/weg", "argumente": {"ziel": "x"}, "trocken": True})
    assert r["ausgefuehrt"] and r["stdout"].strip() == "TROCKEN x"
    # ohne Trockenlauf: auch trocken=true liefert nur den Befehl
    r = plugin.call("ausfuehren", {"id": "ops/weg_ohne", "trocken": True})
    assert r["ausgefuehrt"] is False and r["befehl"] == "python3 scripts/ops/weg_ohne.py"


def test_ort_extern_nicht_ausgefuehrt(plugin):
    r = plugin.call("ausfuehren", {"id": "fle/extern"})
    assert r["ausgefuehrt"] is False and r["grund"] == "läuft auf extern — Job-Weg folgt"
    assert r["befehl"] == "python3 scripts/fle/extern.py"


def test_kaputter_kopf_nie_ausfuehren(plugin):
    r = plugin.call("ausfuehren", {"id": "ops/kaputt"})
    assert r["ausgefuehrt"] is False and "fehlerhaft" in r["grund"]


def test_unbekannte_id(plugin):
    with pytest.raises(ValueError, match="kein angemeldetes"):
        plugin.call("ausfuehren", {"id": "ops/plain"})


# ── Lauf ────────────────────────────────────────────────────────────────────
def test_shell_skript_im_repo(plugin, repo):
    r = plugin.call("ausfuehren", {"id": "sh/probe", "argumente": {"wort": "hallo welt", "laut": True}})
    assert r["rc"] == 0 and r["stdout"].strip() == "wort=hallo welt zwei=--laut"


def test_zeitlimit_und_kappung(plugin):
    r = plugin.call("ausfuehren", {"id": "ops/langsam"})
    assert r["zeitueberschreitung"] and r["rc"] != 0 and r["dauer_s"] < 10
    r = plugin.call("ausfuehren", {"id": "ops/viel"})
    assert len(r["stdout"]) == ws.AUSGABE_MAX and r["gekappt"]["stdout"] == 100_000


def test_env_repo_und_keine_geheimnisse(plugin, repo, monkeypatch):
    monkeypatch.setenv("FYOS_SECRET_TESTWERT", "geheim")
    _py(repo, "ops/env.py", rumpf='import os\nprint(json.dumps({"repo": os.environ["FYOS_REPO"], "cwd": os.getcwd(), "vw": os.getenv("FYOS_SECRET_TESTWERT")}))')
    r = plugin.call("ausfuehren", {"id": "ops/env"})
    assert Path(r["daten"]["repo"]) == repo and Path(r["daten"]["cwd"]).resolve() == repo.resolve()
    assert r["daten"]["vw"] is None and r["form"] == "json"


# ── Bus ─────────────────────────────────────────────────────────────────────
def test_bus_ereignis_je_lauf(repo, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(ws, "_redis", lambda: fake)
    p = WerkstattPlugin(config={"repo": str(repo), "scan_ttl_s": 0})
    p.call("ausfuehren", {"id": "ops/schreib", "argumente": {"ziel": "a"}, "wer": "agent"})
    p.call("ausfuehren", {"id": "fle/extern"})  # nicht gelaufen → kein Ereignis
    assert len(fake.eintraege) == 1
    strom, felder = fake.eintraege[0]
    assert strom == "fyos:events:werkstatt.lauf" and felder["source"] == "fyos-hub/werkstatt"
    data = json.loads(felder["data"])
    assert data["id"] == "ops/schreib" and data["trocken"] is True and data["rc"] == 0 and data["wer"] == "agent"
    assert "dauer_s" in data


def test_bus_weg_verhindert_lauf_nicht(repo, monkeypatch):
    def kaputt():
        raise ConnectionError("redis weg")

    monkeypatch.setattr(ws, "_redis", kaputt)
    p = WerkstattPlugin(config={"repo": str(repo), "scan_ttl_s": 0})
    assert p.call("ausfuehren", {"id": "ops/lesen", "argumente": {"name": "a"}})["rc"] == 0


# ── Suchen / Beschreiben / Zeigen / Beschreibung ────────────────────────────
def test_suchen_filter(plugin):
    alle = plugin.call("suchen", {})
    ids = {s["id"] for s in alle["skripte"]}
    assert {"ops/lesen", "ops/schreib", "sh/probe", "fle/extern"} <= ids and "ops/plain" not in ids
    assert alle["satz"].startswith(f"{alle['anzahl']} Skripte, davon ") and "lesend" in alle["satz"]
    assert plugin.call("suchen", {"q": "ops/lesen"})["satz"].endswith("zu „ops/lesen“.")
    assert [s["id"] for s in plugin.call("suchen", {"ort": "extern"})["skripte"]] == ["fle/extern"]
    assert {s["id"] for s in plugin.call("suchen", {"wirkung": "loeschen"})["skripte"]} == {"ops/weg", "ops/weg_ohne"}
    t = plugin.call("suchen", {"q": "LESEN"})["skripte"]
    assert t[0]["id"] == "ops/lesen" and t[0]["trockenlauf"] is False and t[0]["im_hub"] is True


def test_cache_sieht_aenderung(plugin, repo):
    assert "ops/neu" not in {s["id"] for s in plugin.call("suchen", {})["skripte"]}
    _py(repo, "ops/neu.py", rumpf='print("neu")')
    assert "ops/neu" in {s["id"] for s in plugin.call("suchen", {})["skripte"]}


def test_beschreiben(plugin):
    d = plugin.call("beschreiben", {"id": "ops/schreib"})
    assert d["art"] == "skript" and d["trockenlauf"] == "--trocken"
    assert list(d["schema"]["properties"]) == ["ziel"] and d["schema"]["required"] == ["ziel"]
    assert plugin.call("beschreiben", {"id": "scripts/ops/schreib.py"})["id"] == "ops/schreib"


def test_zeigen_formen(plugin):
    assert plugin.call("zeigen", {"titel": "t", "daten": "hallo"})["form"] == "text"
    assert plugin.call("zeigen", {"titel": "t", "daten": [{"a": 1}]})["form"] == "tabelle"
    assert plugin.call("zeigen", {"titel": "t", "daten": [{"x": 1, "y": 2}]})["form"] == "kurve"
    assert plugin.call("zeigen", {"titel": "t", "daten": {"a": [{"x": 1, "y": 2}]}})["form"] == "kurve"
    assert plugin.call("zeigen", {"titel": "t", "daten": {"k": 1}})["form"] == "json"
    with pytest.raises(ValueError):
        plugin.call("zeigen", {"titel": "", "daten": 1})


def test_werkzeuge_und_app(plugin):
    tools = {t.name: t for t in plugin.describe_tools()}
    assert set(tools) == {"suchen", "beschreiben", "ausfuehren", "zeigen", "favoriten", "favoriten_setzen"}
    for t in tools.values():
        assert "flaeche" in t.tags and "werkstatt" in t.tags
        if not t.name.startswith("favoriten"):  # Favoriten der Zentrale: Daten ohne Oberflaeche
            assert t.meta["ui"]["resourceUri"] == ws.UI_WERKSTATT
        assert t.input_schema["additionalProperties"] is False
    assert "write" in tools["ausfuehren"].tags and "read" in tools["suchen"].tags
    [res] = plugin.describe_resources()
    html = res.read()
    assert res.uri == ws.UI_WERKSTATT and res.mime_type == "text/html;profile=mcp-app"
    assert "/*BRUECKE*/" not in html and "appInfo" in html and "werkstatt__ausfuehren" not in html.split("werkstatt__")[0]
    for name in ("suchen", "beschreiben", "ausfuehren"):
        assert '"' + name + '"' in html  # die App ruft die Werkzeuge ueber tools/call (werkstatt__<name>)


def test_health(plugin, tmp_path):
    h = plugin.health()
    assert h["ok"] and h["angemeldet"] >= 8
    # Ohne Repo (frische Installation) ist die Werkstatt aus, nicht krank.
    aus = WerkstattPlugin(config={"repo": str(tmp_path / "fehlt")}).health()
    assert aus["ok"] is True and aus["status"] == "aus" and "werkstatt.repo" in aus["reason"]
    # Ein Repo ohne scripts/ ist dagegen falsch eingerichtet.
    (tmp_path / "leer").mkdir()
    assert WerkstattPlugin(config={"repo": str(tmp_path / "leer")}).health()["ok"] is False
