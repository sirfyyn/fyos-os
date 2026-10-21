"""S1: Suche über alles — Vorgänge, Mail, Dateien, Notizen und Quellen, die Plugins anmelden.

Die Quellen des Kerns laufen über Attrappen (Vorgangs-Ablage, Mail-Plugin, Dateiordner); die Notizen über den echten
Notizzettel im Hub. Geprüft wird auch, was nicht geschehen darf: eine Quelle, die fehlt oder kaputt ist, bricht die Suche
nicht ab und wird auch nicht als „nichts gefunden“ ausgegeben.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp_hub import dateien as store
from mcp_hub import postfach, suche_alles, termine, vorgaenge
from mcp_hub import server as hub_server

from .test_arbeit_uebergaben import EIGEN, KONFIG, Postablage, Vorgangsablage


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_VORGAENGE_URL", "FYOS_POSTFACH_URL", "FYOS_TERMINE_URL", "FYOS_DATEIEN"):
        monkeypatch.delenv(name, raising=False)
    vorher = dict(suche_alles._QUELLEN)
    for modul in (vorgaenge, postfach, termine):
        modul.ablage_anmelden(None)
        modul.dienst_anmelden(None)
    store.verzeichnis_anmelden(None)
    yield
    suche_alles._QUELLEN.clear()
    suche_alles._QUELLEN.update(vorher)
    for modul in (vorgaenge, postfach, termine):
        modul.ablage_anmelden(None)
        modul.dienst_anmelden(None)
    store.verzeichnis_anmelden(None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    ablage = tmp_path / "ablage"
    (ablage / "Projekt").mkdir(parents=True)
    (ablage / "Projekt" / "Quartalszahlen.md").write_text("Umsatz im Quartal: gut\n", encoding="utf-8")
    (ablage / "Einkauf.txt").write_text("Milch, Brot, Quartalsbericht\n", encoding="utf-8")
    monkeypatch.setenv("FYOS_DATEIEN", str(ablage))
    konfig = tmp_path / "hub.yaml"
    konfig.write_text(KONFIG, encoding="utf-8")
    c = TestClient(hub_server.build_app(str(konfig)))
    vorgaenge.ablage_anmelden(Vorgangsablage())
    postfach.ablage_anmelden(Postablage())
    return c


def rufen(client, tool, **args):
    r = client.post("/hub/app-call", json={"tool": tool, "arguments": args}, headers=EIGEN)
    return r.status_code, r.json()


def suchen(client, abfrage, **args):
    status, d = rufen(client, "suche.alles", abfrage=abfrage, **args)
    assert status == 200, d
    return d["result"]


# ── Alle vier Quellen des Kerns ─────────────────────────────────────────────────────────────────────


def test_findet_vorgang_mail_datei_und_notiz(client):
    rufen(client, "beispiel_app.hinzufuegen", text="Quartal planen\nmit dem Team", bestaetigt=True)
    r = suchen(client, "quartal")
    nach_quelle = {t["quelle"]: t for t in r["treffer"]}
    assert set(nach_quelle) == {"vorgaenge", "postfach", "dateien", "notizen"}
    assert nach_quelle["vorgaenge"]["typ"] == "vorgang" and nach_quelle["vorgaenge"]["id"] == "WB-0001"
    assert nach_quelle["postfach"]["typ"] == "mail" and nach_quelle["postfach"]["id"] == "m1" and nach_quelle["postfach"]["titel"] == "Zahlen fürs Quartal"
    assert nach_quelle["dateien"]["typ"] == "datei"
    assert nach_quelle["notizen"]["typ"] == "notiz" and nach_quelle["notizen"]["titel"] == "Quartal planen"
    assert all(q["zustand"] == "ok" for q in r["quellen"])
    assert "Fremdinhalt" in r["hinweis"]


def test_treffer_sind_gemischt_und_jede_quelle_kommt_zu_wort(client):
    r = suchen(client, "quartal", anzahl=4)
    assert len(r["treffer"]) == 4
    assert len({t["quelle"] for t in r["treffer"]}) >= 3  # nicht eine Quelle füllt alles


def test_alle_woerter_muessen_vorkommen_und_gross_klein_gilt_nicht(client):
    assert {t["id"] for t in suchen(client, "SERVER patchen")["treffer"] if t["quelle"] == "vorgaenge"} == {"WB-0002"}
    r = suchen(client, "server zuckerwatte")
    assert r["treffer"] == [] and r["satz"].startswith("Nichts gefunden")


def test_dateien_treffer_tragen_den_pfad_als_kennung(client):
    ids = {t["id"] for t in suchen(client, "quartal")["treffer"] if t["quelle"] == "dateien"}
    assert ids <= {"Projekt/Quartalszahlen.md", "Einkauf.txt"} and ids


def test_zu_kurze_oder_fehlende_abfrage_ist_ein_fehler(client):
    for abfrage in ("a", " ", ""):
        status, d = rufen(client, "suche.alles", abfrage=abfrage)
        assert status == 400, abfrage


# ── Fehlende und kaputte Quellen ────────────────────────────────────────────────────────────────────


def test_fehlende_quelle_bricht_die_suche_nicht_ab_und_wird_genannt(client):
    postfach.ablage_anmelden(None)
    vorgaenge.ablage_anmelden(None)
    r = suchen(client, "quartal")
    zustand = {q["quelle"]: q["zustand"] for q in r["quellen"]}
    assert zustand["postfach"] == "nicht eingerichtet" and zustand["vorgaenge"] == "nicht eingerichtet"
    assert zustand["dateien"] == "ok" and zustand["notizen"] == "ok"
    assert {"dateien"} <= {t["quelle"] for t in r["treffer"]} <= {"dateien", "notizen"}
    assert "Mail" in r["satz"] and "Vorgänge" in r["satz"]  # nicht still „nichts gefunden“


def test_dateiablage_ohne_ordner_ist_nicht_eingerichtet(client, monkeypatch):
    monkeypatch.delenv("FYOS_DATEIEN")
    store.verzeichnis_anmelden(None)
    r = suchen(client, "quartal")
    assert {q["quelle"]: q["zustand"] for q in r["quellen"]}["dateien"] == "nicht eingerichtet"
    assert {t["quelle"] for t in r["treffer"]} >= {"vorgaenge", "postfach"}


def test_kaputte_quelle_wird_uebersprungen_ihr_text_bleibt_im_protokoll_aus(client, caplog):
    def kaputt(abfrage, anzahl):
        raise RuntimeError("Zugang geheim-123 abgelehnt")

    suche_alles.registriere_quelle("wiki", "Wiki", kaputt)
    r = suchen(client, "quartal")
    wiki = next(q for q in r["quellen"] if q["quelle"] == "wiki")
    assert wiki["zustand"] == "fehler" and "fehler" not in wiki
    assert "geheim-123" not in str(r) and "geheim-123" not in caplog.text
    assert {t["quelle"] for t in r["treffer"]} >= {"vorgaenge", "postfach"}


def test_quelle_die_nicht_antwortet_nennt_den_grund(client):
    def aus(abfrage, anzahl):
        raise vorgaenge.QuelleFehler("Wiki antwortet nicht")

    suche_alles.registriere_quelle("wiki", "Wiki", aus)
    wiki = next(q for q in suchen(client, "quartal")["quellen"] if q["quelle"] == "wiki")
    assert wiki["zustand"] == "fehler" and wiki["fehler"] == "Wiki antwortet nicht"


# ── Die Schnittstelle für Plugins ───────────────────────────────────────────────────────────────────


def test_ein_plugin_meldet_eine_weitere_quelle_an(client):
    def wiki(abfrage, anzahl):
        return [{"id": "seite-7", "titel": "Quartalsplanung", "auszug": "Teil des Wikis"}, {"id": "seite-8", "titel": "Anderes"}]

    suche_alles.registriere_quelle("wiki", "Wiki", wiki, typ="seite")
    r = suchen(client, "quartal")
    treffer = next(t for t in r["treffer"] if t["quelle"] == "wiki" and t["id"] == "seite-7")
    assert treffer["typ"] == "seite" and treffer["quelle_titel"] == "Wiki" and treffer["auszug"] == "Teil des Wikis"
    nur = suchen(client, "quartal", quellen=["wiki"])
    assert {t["quelle"] for t in nur["treffer"]} == {"wiki"} and [q["quelle"] for q in nur["quellen"]] == ["wiki"]


def test_quelle_ohne_typ_zeigt_nur_an(client):
    suche_alles.registriere_quelle("lexikon", "Lexikon", lambda a, n: [{"id": "q", "titel": "Quartal"}])
    t = next(t for t in suchen(client, "quartal")["treffer"] if t["quelle"] == "lexikon")
    assert "typ" not in t


def test_treffer_werden_gesaeubert_und_gekuerzt():
    suche_alles.registriere_quelle("grob", "Grob", lambda a, n: [
        "kein Objekt", {"titel": "ohne Kennung"}, {"id": "", "titel": "leer"}, {"id": "a\nb", "titel": "Zeilenumbruch"},
        {"id": 7, "titel": "x" * 500, "auszug": "y" * 500}, {"id": "ok", "titel": None, "auszug": "Zeile 1\n  Zeile 2"},
    ])
    treffer = suche_alles.suchen("quartal", 20, nur=["grob"])["treffer"]
    assert [t["id"] for t in treffer] == ["7", "ok"]
    assert len(treffer[0]["titel"]) <= suche_alles.TITEL_MAX and len(treffer[0]["auszug"]) <= suche_alles.AUSZUG_MAX
    assert treffer[1]["titel"] == "ok" and treffer[1]["auszug"] == "Zeile 1 Zeile 2"


@pytest.mark.parametrize("kw", [
    {"schluessel": "Wiki"}, {"schluessel": "1wiki"}, {"schluessel": "w" * 40}, {"titel": ""}, {"titel": "T" * 41},
    {"suchen": "keine Funktion"}, {"typ": "Seite"}, {"typ": "ein typ"},
])
def test_ungueltige_quellen_werden_abgelehnt(kw):
    args = dict(schluessel="wiki", titel="Wiki", suchen=lambda a, n: [], typ=None)
    args.update(kw)
    with pytest.raises(ValueError):
        suche_alles.registriere_quelle(**args)


def test_abmelden_nur_wenn_es_noch_dieselbe_funktion_ist():
    erste, zweite = (lambda a, n: []), (lambda a, n: [])
    suche_alles.registriere_quelle("wiki", "Wiki", erste)
    suche_alles.registriere_quelle("wiki", "Wiki", zweite)  # ein Neustart des Plugins hat die Quelle ersetzt
    suche_alles.entferne_quelle("wiki", erste)
    assert "wiki" in {q.schluessel for q in suche_alles.quellen()}
    suche_alles.entferne_quelle("wiki", zweite)
    assert "wiki" not in {q.schluessel for q in suche_alles.quellen()}


def test_das_werkzeug_ist_lesend_und_fuer_die_shell_freigegeben(client):
    from mcp_hub.plugins.suche import SuchePlugin

    (t,) = SuchePlugin().describe_tools()
    assert t.name == "alles" and "read" in t.tags and "flaeche" in t.tags
    apps = client.get("/hub/apps", headers=EIGEN).json()["apps"]
    assert any(a["name"] == "suche__alles" for a in apps)
