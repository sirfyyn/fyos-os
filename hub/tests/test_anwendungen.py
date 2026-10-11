"""Widget oder Anwendung: `registriere_app(..., art=)` und was die Shell davon bekommt (GET /hub/apps, meta.app.art)."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mcp_hub import dateien as store
from mcp_hub import server as hub_server
from mcp_hub.plugins import _identitaet, beispiel_app, dateien, gui, mcp_kasten, werkstatt  # noqa: F401  (melden ihre Apps an)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config_example.yaml"
EIGEN = {"Origin": "http://localhost"}
EINTRAG = {"titel": "Probe", "untertitel": "x", "symbol": "package", "ton": 120, "kategorie": "Beispiele"}


@pytest.fixture
def probe(monkeypatch):
    """Die App-Tabelle gehört dem Test; nichts Echtes wird verändert."""
    monkeypatch.setattr(_identitaet, "APPS", {})
    monkeypatch.setattr(_identitaet, "DATEIEN", {})
    monkeypatch.setattr(_identitaet, "HAUPTWERKZEUG", {})


def test_ohne_angabe_ist_eine_app_ein_widget(probe):
    _identitaet.registriere_app("probe", EINTRAG, hauptwerkzeug="probe__zeigen")
    assert _identitaet.identitaet("probe")["art"] == "widget"


def test_anwendung_wird_angemeldet(probe):
    _identitaet.registriere_app("probe", EINTRAG, hauptwerkzeug="probe__zeigen", art="anwendung")
    assert _identitaet.identitaet("probe")["art"] == "anwendung"


def test_art_im_eintrag_gilt_und_das_argument_geht_vor(probe):
    _identitaet.registriere_app("a", {**EINTRAG, "art": "anwendung"})
    _identitaet.registriere_app("b", {**EINTRAG, "art": "anwendung"}, art="widget")
    assert _identitaet.identitaet("a")["art"] == "anwendung"
    assert _identitaet.identitaet("b")["art"] == "widget"


@pytest.mark.parametrize("art", ["Widget", "fenster", "", "anwendung ", 1])
def test_unbekannte_art_wird_abgelehnt(probe, art):
    with pytest.raises(ValueError, match="art"):
        _identitaet.registriere_app("probe", EINTRAG, art=art)
    assert "probe" not in _identitaet.APPS


def test_eine_app_ohne_art_im_register_ist_ein_widget(probe):
    # Eingetragen an `registriere_app` vorbei (ältere Plugins schreiben in APPS): identitaet() ergänzt die Vorgabe
    _identitaet.APPS["alt"] = dict(EINTRAG)
    assert _identitaet.identitaet("alt")["art"] == "widget"
    assert "art" not in _identitaet.APPS["alt"]


def test_mitgelieferte_apps_art():
    assert _identitaet.identitaet("dateien")["art"] == "anwendung"
    for schluessel in ("beispiel_app", "werkstatt", "mcp", "gui"):
        assert _identitaet.identitaet(schluessel)["art"] == "widget", schluessel


@pytest.fixture
def client(tmp_path, monkeypatch):
    ablage = tmp_path / "ablage"
    ablage.mkdir()
    monkeypatch.setenv("FYOS_DATEIEN", str(ablage))
    store.verzeichnis_anmelden(None)
    c = TestClient(hub_server.build_app(str(CONFIG_PATH)))
    yield c
    store.verzeichnis_anmelden(None)


def test_apps_tragen_die_art_oben_und_in_meta(client):
    apps = {a["name"]: a for a in client.get("/hub/apps", headers=EIGEN).json()["apps"]}
    assert apps["dateien__liste"]["art"] == "anwendung"
    assert apps["dateien__liste"]["_meta"]["app"]["art"] == "anwendung"
    assert apps["beispiel_app__zeigen"]["art"] == "widget"
    # Jede App mit Identität sagt, was sie ist
    for name, a in apps.items():
        if "titel" in a:
            assert a["art"] in ("widget", "anwendung"), name
