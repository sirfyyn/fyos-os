"""Dinge und Übergaben (plugins/_dinge.py): Anmeldung, Prüfung, das Register für die Shell und die zwei echten Paare.

Die Paare Notiz → Dateien und Datei → Notizzettel laufen hier über den echten Hub-Stapel: lesen, Felder einsetzen,
Trockenlauf des Zielwerkzeugs, Bestätigung, Wirkung.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcp_hub import dateien as store
from mcp_hub import server as hub_server
from mcp_hub.plugins import _dinge, _identitaet, beispiel_app, dateien  # noqa: F401  (melden Typen und Paare an)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"
EIGEN = {"Origin": "http://localhost"}


@pytest.fixture
def leer(monkeypatch):
    """Ein leeres Register (und die App-Tabelle mit zwei Apps), damit eigene Fälle nichts Echtes berühren."""
    monkeypatch.setattr(_dinge, "DINGE", {})
    monkeypatch.setattr(_dinge, "UEBERGABEN", {})
    monkeypatch.setattr(_identitaet, "APPS", {
        "quelle": {"titel": "Quelle", "untertitel": "", "symbol": "package", "ton": 10, "kategorie": "Beispiele"},
        "ziel": {"titel": "Ziel", "untertitel": "", "symbol": "package", "ton": 20, "kategorie": "Beispiele"},
    })
    monkeypatch.setattr(_identitaet, "HAUPTWERKZEUG", {"quelle": "quelle__zeigen", "ziel": "ziel__zeigen"})


def ding(**kw):
    args = dict(typ="karte", name="Karte", flaeche="quelle", lesen="quelle.lesen", id_argument="id", felder=("text",))
    args.update(kw)
    _dinge.registriere_ding(**args)


def paar(**kw):
    args = dict(quelltyp="karte", ziel_app="ziel", werkzeug="ziel.anlegen", abbildung={"text": "{label}: {text}"}, wirkung="Als Eintrag anlegen")
    args.update(kw)
    _dinge.registriere_uebergabe(**args)


# ── Anmelden ────────────────────────────────────────────────────────────────────────────────────────


def test_ding_anmelden_und_ueberschreiben(leer):
    ding()
    ding(name="Karte neu")
    assert _dinge.DINGE["karte"]["name"] == "Karte neu"
    assert _dinge.DINGE["karte"]["felder"] == ["text"]


@pytest.mark.parametrize(
    "kw",
    [
        {"typ": "Karte"},  # Großbuchstaben
        {"typ": "ka rte"},
        {"typ": "x" * 40},
        {"typ": "../x"},
        {"name": ""},
        {"name": "n" * 41},
        {"flaeche": "gibtsnicht"},
        {"lesen": "ohne-punkt"},
        {"lesen": "a.b.c"},
        {"id_argument": "Pfad Art"},
        {"felder": ("id",)},  # id und label gibt es immer
        {"felder": ("label",)},
        {"felder": ("Gross",)},
    ],
)
def test_ding_mit_ungueltigen_angaben_wird_abgelehnt(leer, kw):
    with pytest.raises(ValueError):
        ding(**kw)
    assert _dinge.DINGE == {}


@pytest.mark.parametrize(
    "kw",
    [
        {"quelltyp": "Karte"},
        {"ziel_app": ""},
        {"werkzeug": "ziel__anlegen"},  # Punkt statt zwei Unterstriche
        {"wirkung": ""},
        {"wirkung": "w" * 121},
        {"abbildung": {"text": "{label"}},  # offene Klammer
        {"abbildung": {"text": "{{label}}x}"}},
        {"abbildung": {"Text": "x"}},
        {"abbildung": {"text": ["liste"]}},
        {"abbildung": {"text": "x" * 2001}},
        {"abbildung": {f"a{i}": "x" for i in range(13)}},
    ],
)
def test_uebergabe_mit_ungueltigen_angaben_wird_abgelehnt(leer, kw):
    with pytest.raises(ValueError):
        paar(**kw)
    assert _dinge.UEBERGABEN == {}


def test_uebergabe_darf_vor_dem_typ_angemeldet_werden(leer):
    paar()  # Plugins laden in beliebiger Reihenfolge
    assert _dinge.fuer_shell() == {"dinge": {}, "uebergaben": []}
    ding()
    assert len(_dinge.fuer_shell()["uebergaben"]) == 1


# ── Einsetzen ───────────────────────────────────────────────────────────────────────────────────────


def test_ausfuellen_setzt_felder_ein_und_laesst_andere_werte_stehen():
    ab = {"pfad": "Notizen/{dateiname}.md", "inhalt": "{text}\n", "ueberschreiben": False, "frist": 3}
    r = _dinge.ausfuellen(ab, {"id": "7", "label": "Milch", "dateiname": "Milch", "text": "Milch kaufen"})
    assert r == {"pfad": "Notizen/Milch.md", "inhalt": "Milch kaufen\n", "ueberschreiben": False, "frist": 3}


def test_ausfuellen_ohne_wert_wirft_statt_ein_loch_zu_lassen():
    with pytest.raises(ValueError, match="text"):
        _dinge.ausfuellen({"inhalt": "{text}"}, {"id": "7", "label": "x"})
    with pytest.raises(ValueError):
        _dinge.ausfuellen({"inhalt": "{text}"}, {"id": "7", "label": "x", "text": {"a": 1}})


def test_ausfuellen_setzt_keine_eingesetzten_werte_erneut_ein():
    # Ein Feld, das selbst „{id}“ enthält, wird nicht ein zweites Mal ersetzt (kein Einschleusen über den Inhalt)
    r = _dinge.ausfuellen({"inhalt": "{text}"}, {"id": "GEHEIM", "label": "l", "text": "{id}"})
    assert r["inhalt"] == "{id}"


# ── Das Register für die Shell ──────────────────────────────────────────────────────────────────────


def test_register_fuer_die_shell_hat_flaechen_und_werkzeugnamen(leer):
    ding()
    paar()
    r = _dinge.fuer_shell()
    assert r["dinge"] == {"karte": {"name": "Karte", "flaeche": "app:quelle__zeigen", "idArgument": "id", "felder": ["text"], "lesen": "quelle__lesen"}}
    assert r["uebergaben"] == [
        {"quelle": "karte", "ziel": "app:ziel__zeigen", "werkzeug": "ziel__anlegen", "abbildung": {"text": "{label}: {text}"}, "wirkung": "Als Eintrag anlegen"}
    ]


def test_ding_ohne_lesewerkzeug_hat_kein_lesen_und_nur_grundfelder(leer):
    ding(lesen=None, felder=())
    paar(abbildung={"text": "{id}"})
    r = _dinge.fuer_shell()
    assert "lesen" not in r["dinge"]["karte"] and len(r["uebergaben"]) == 1
    paar(abbildung={"text": "{text}"})  # ein Feld, das der Typ nicht liefert
    assert _dinge.fuer_shell()["uebergaben"] == []


def test_uebergabe_faellt_weg_wenn_etwas_nicht_passt(leer, caplog):
    ding()
    paar(werkzeug="fremd.anlegen")  # gehört nicht zum Plugin der Ziel-App
    assert _dinge.fuer_shell()["uebergaben"] == []
    assert "gehört nicht zum Plugin" in caplog.text
    paar()
    assert len(_dinge.fuer_shell()["uebergaben"]) == 1
    assert _dinge.fuer_shell(lambda fqtn: fqtn != "ziel.anlegen")["uebergaben"] == []  # kein Flächen-Werkzeug
    assert _dinge.fuer_shell(lambda fqtn: fqtn != "quelle.lesen")["dinge"] == {}  # Lesewerkzeug unbekannt
    assert _dinge.fuer_shell(lambda fqtn: fqtn != "quelle.lesen")["uebergaben"] == []  # und damit auch die Paare des Typs


def test_ding_einer_app_ohne_hauptwerkzeug_bleibt_weg(leer, monkeypatch):
    monkeypatch.setattr(_identitaet, "HAUPTWERKZEUG", {"ziel": "ziel__zeigen"})
    ding()
    assert _dinge.fuer_shell()["dinge"] == {}


# ── Die echten Typen und Paare ──────────────────────────────────────────────────────────────────────


def test_notiz_und_datei_sind_angemeldet():
    r = _dinge.fuer_shell()
    assert r["dinge"]["notiz"]["flaeche"] == "app:beispiel_app__zeigen"
    assert r["dinge"]["notiz"]["lesen"] == "beispiel_app__lesen"
    assert r["dinge"]["datei"] == {"name": "Datei", "flaeche": "app:dateien__liste", "idArgument": "pfad", "felder": [], "lesen": "dateien__lesen"}
    paare = {(u["quelle"], u["ziel"]): u for u in r["uebergaben"]}
    assert set(paare) >= {("notiz", "app:dateien__liste"), ("datei", "app:beispiel_app__zeigen")}
    assert paare[("notiz", "app:dateien__liste")]["werkzeug"] == "dateien__schreiben"
    assert paare[("datei", "app:beispiel_app__zeigen")]["werkzeug"] == "beispiel_app__hinzufuegen"


@pytest.fixture
def client(tmp_path, monkeypatch):
    ablage = tmp_path / "ablage"
    ablage.mkdir()
    monkeypatch.setenv("FYOS_DATEIEN", str(ablage))
    store.verzeichnis_anmelden(None)
    c = TestClient(hub_server.build_app(str(CONFIG_PATH)))
    c.ablage = ablage
    yield c
    store.verzeichnis_anmelden(None)


def rufen(client, tool, **args):
    r = client.post("/hub/app-call", json={"tool": tool, "arguments": args}, headers=EIGEN)
    return r.status_code, r.json()


def test_apps_liefert_dinge_und_uebergaben_mit_etag(client):
    r = client.get("/hub/apps", headers=EIGEN)
    d = r.json()
    assert d["ok"] and "notiz" in d["dinge"] and "datei" in d["dinge"]
    assert any(u["quelle"] == "notiz" and u["ziel"] == "app:dateien__liste" for u in d["uebergaben"])
    assert r.headers["etag"]
    assert client.get("/hub/apps", headers={**EIGEN, "If-None-Match": r.headers["etag"]}).status_code == 304
    # Die Apps selbst sind unverändert da
    assert any(a["name"] == "dateien__liste" for a in d["apps"])


def notiz_anlegen(client, text):
    status, d = rufen(client, "beispiel_app.hinzufuegen", text=text)
    assert status == 200, d
    return d["result"]["notizen"][-1]["id"]


def test_notiz_wird_zur_markdown_datei_erst_nach_plan_und_bestaetigung(client):
    nid = notiz_anlegen(client, "Milch kaufen / Brot\nund Eier")
    status, gelesen = rufen(client, "beispiel_app.lesen", id=nid)
    assert status == 200 and gelesen["result"]["titel"] == "Milch kaufen / Brot"
    werte = {"id": nid, "label": gelesen["result"]["titel"], **gelesen["result"]}
    u = next(u for u in _dinge.fuer_shell()["uebergaben"] if (u["quelle"], u["ziel"]) == ("notiz", "app:dateien__liste"))
    argumente = _dinge.ausfuellen(u["abbildung"], werte)
    assert argumente["pfad"] == "Notizen/Milch kaufen Brot.md" and argumente["inhalt"] == "Milch kaufen / Brot\nund Eier\n"
    # Trockenlauf: der Plan, nichts geschrieben
    status, plan = rufen(client, "dateien.schreiben", **argumente, __dry_run__=True)
    assert status == 200 and plan["result"]["dry_run"] is True
    assert not (client.ablage / "Notizen").exists()
    # Ohne Bestätigung läuft nichts
    status, _ = rufen(client, "dateien.schreiben", **argumente)
    assert status == 400 and not (client.ablage / "Notizen").exists()
    # Mit Bestätigung: die Datei liegt da, im neuen Ordner
    status, echt = rufen(client, "dateien.schreiben", **argumente, bestaetigt=True)
    assert status == 200 and echt["result"]["ok"] is True
    assert (client.ablage / "Notizen" / "Milch kaufen Brot.md").read_text(encoding="utf-8") == "Milch kaufen / Brot\nund Eier\n"


def test_datei_wird_zur_notiz_mit_verweis(client):
    u = next(u for u in _dinge.fuer_shell()["uebergaben"] if (u["quelle"], u["ziel"]) == ("datei", "app:beispiel_app__zeigen"))
    argumente = _dinge.ausfuellen(u["abbildung"], {"id": "Projekt/Plan.md", "label": "Plan.md"})
    assert argumente == {"text": "Datei Projekt/Plan.md"}
    status, plan = rufen(client, "beispiel_app.hinzufuegen", **argumente, __dry_run__=True)
    assert status == 200 and plan["result"]["dry_run"] is True and "Projekt/Plan.md" in plan["result"]["would_execute"]
    _, vorher = rufen(client, "beispiel_app.zeigen")
    anzahl = vorher["result"]["anzahl"]
    status, echt = rufen(client, "beispiel_app.hinzufuegen", **argumente, bestaetigt=True)
    assert status == 200 and echt["result"]["anzahl"] == anzahl + 1
    assert echt["result"]["notizen"][-1]["text"] == "Datei Projekt/Plan.md"


def test_trockenlauf_des_zettels_aendert_nichts(client):
    _, vorher = rufen(client, "beispiel_app.zeigen")
    rufen(client, "beispiel_app.hinzufuegen", text="nur ein Plan", __dry_run__=True)
    _, nachher = rufen(client, "beispiel_app.zeigen")
    assert nachher["result"]["anzahl"] == vorher["result"]["anzahl"]


def test_lesen_einer_unbekannten_notiz_ist_ein_fehler(client):
    status, d = rufen(client, "beispiel_app.lesen", id="gibtsnicht")
    assert status == 400 and "gibtsnicht" in d["error"]


@pytest.mark.parametrize(
    "text,erwartet",
    [
        ("Milch kaufen", "Milch kaufen"),
        ("  Einkauf: Brot/Käse?\nzweite Zeile", "Einkauf Brot Käse"),
        ("../../etc/passwd", "etc passwd"),
        ("...", "Notiz"),
        ("", "Notiz"),
        ("a" * 200, "a" * 50),
        (".fyos geheim", "fyos geheim"),
    ],
)
def test_dateiname_der_notiz_ist_immer_ein_harmloser_name(text, erwartet):
    name = beispiel_app.dateiname_der(text)
    assert name == erwartet
    assert not name.startswith(".") and "/" not in name and "\\" not in name and ".." not in name
    # und die Ablage nimmt ihn an
    assert store.normalisiere(f"Notizen/{name}.md") == f"Notizen/{name}.md"


def test_titel_wird_gekuerzt():
    assert beispiel_app.titel_der("x" * 100).endswith("…") and len(beispiel_app.titel_der("x" * 100)) == beispiel_app.TITEL_MAX
    assert beispiel_app.titel_der("eins\nzwei") == "eins"
