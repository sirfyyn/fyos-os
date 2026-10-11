"""kv (Speicher-Ersatz fuer Redis), Identitaets-Register, Beispiel-App und UI-Verzeichnis-Mechanismus."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mcp_hub import kv
from mcp_hub.plugins import _identitaet, beispiel_app
from mcp_hub.plugins._oberflaeche import oberflaeche
from mcp_hub.plugins.beispiel_app import BeispielAppPlugin


# ── kv ──────────────────────────────────────────────────────────────────────
def test_kv_ohne_url_ist_der_speicher(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    c = kv.klient()
    assert kv.ist_speicher(c) and c.ping()


def test_kv_zeichenketten_mit_ablauf():
    zeit = [100.0]
    c = kv.SpeicherKv(uhr=lambda: zeit[0])
    assert c.set("a", "1", ex=10) is True
    assert c.set("a", "2", nx=True) is None and c.get("a") == "1"
    zeit[0] = 111.0
    assert c.get("a") is None and c.exists("a") == 0


def test_kv_listen_hashes_streams():
    c = kv.SpeicherKv()
    c.rpush("l", "a", "b", "c")
    assert c.lrange("l", 0, -1) == ["a", "b", "c"]
    c.ltrim("l", 1, -1)
    assert c.lrange("l", 0, -1) == ["b", "c"]
    c.hset("h", "k", "v")
    assert c.hgetall("h") == {"k": "v"} and c.hexists("h", "k")
    c.hdel("h", "k")
    assert not c.hexists("h", "k")
    c.xadd("s", {"x": "1"})
    c.xadd("s", {"x": "2"})
    assert [f["x"] for _, f in c.xrevrange("s", count=1)] == ["2"]
    assert c.incr("n") == 1 and c.incr("n") == 2


# ── Identitaet ──────────────────────────────────────────────────────────────
def test_kern_register_kennt_nur_die_mitgelieferten_apps():
    assert set(_identitaet.APPS) >= {"werkstatt", "mcp", "gui", "beispiel_app"}
    for eintrag in _identitaet.APPS.values():
        assert eintrag["kategorie"] in _identitaet.KATEGORIEN


def test_registriere_app_fuer_ein_externes_plugin():
    try:
        _identitaet.registriere_app(
            "probe_app",
            {"titel": "Probe", "untertitel": "x", "symbol": "package", "ton": 120, "kategorie": "Beispiele"},
            datei="probe.html",
            hauptwerkzeug="probe_app__zeigen",
        )
        assert _identitaet.identitaet("probe_app")["titel"] == "Probe"
        assert _identitaet.fuer_datei("probe.html")["titel"] == "Probe"
    finally:
        _identitaet.APPS.pop("probe_app", None)
        _identitaet.DATEIEN.pop("probe.html", None)
        _identitaet.HAUPTWERKZEUG.pop("probe_app", None)


# ── Beispiel-App ────────────────────────────────────────────────────────────
@pytest.fixture
def zettel() -> BeispielAppPlugin:
    p = BeispielAppPlugin()
    p._r = kv.SpeicherKv()
    return p


def test_zettel_hinzufuegen_zeigen_loeschen(zettel):
    assert zettel.call("zeigen", {})["anzahl"] == 0
    erste = zettel.call("hinzufuegen", {"text": "  Milch  "})["notizen"][0]
    assert erste["text"] == "Milch"
    assert zettel.call("zeigen", {})["anzahl"] == 1
    assert zettel.call("loeschen", {"id": erste["id"]})["anzahl"] == 0


def test_zettel_grenzen(zettel):
    with pytest.raises(ValueError):
        zettel.call("hinzufuegen", {"text": "  "})
    with pytest.raises(ValueError):
        zettel.call("loeschen", {"id": "gibtsnicht"})
    for i in range(beispiel_app.NOTIZEN_MAX):
        zettel.call("hinzufuegen", {"text": f"n{i}"})
    with pytest.raises(ValueError, match="voll"):
        zettel.call("hinzufuegen", {"text": "zu viel"})


def test_zettel_werkzeuge_schreibend_nur_fuer_die_oberflaeche(zettel):
    werkzeuge = {t.name: t for t in zettel.describe_tools()}
    assert "read" in werkzeuge["zeigen"].tags and "flaeche" in werkzeuge["zeigen"].tags
    for name in ("hinzufuegen", "loeschen"):
        assert "write" in werkzeuge[name].tags
        assert werkzeuge[name].meta["ui"]["visibility"] == ["app"]
    assert werkzeuge["zeigen"].meta["ui"]["resourceUri"] == beispiel_app.UI_URI


def test_der_nachtauftrag_liest_ein_werkzeug_das_der_agent_sehen_und_rufen_darf(zettel):
    """tools/nachtauftrag.py schickt den Agenten zu `beispiel_app.zeigen`: Es muss das Werkzeug geben, es darf nicht
    „nur für die Oberfläche“ sein, und es liefert `anzahl` und `notizen` mit Text (das nennt der Auftragstext)."""
    import importlib.util

    pfad = Path(__file__).resolve().parents[2] / "tools" / "nachtauftrag.py"
    spec = importlib.util.spec_from_file_location("nachtauftrag_aus_tools", pfad)
    assert spec and spec.loader
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)

    plugin, werkzeug = modul.LESE_WERKZEUG.split(".")
    assert plugin == zettel.name
    beschreibung = {t.name: t for t in zettel.describe_tools()}[werkzeug]
    assert "visibility" not in beschreibung.meta["ui"] and "read" in beschreibung.tags
    zettel.call("hinzufuegen", {"text": "Milch kaufen"})
    antwort = zettel.call(werkzeug, {})
    assert antwort["anzahl"] == 1 and antwort["notizen"][0]["text"] == "Milch kaufen"
    assert {"id", "text", "zeit"} <= set(antwort["notizen"][0])


def test_zettel_oberflaeche_ist_aufgeloest(zettel):
    [res] = zettel.describe_resources()
    html = res.read()
    assert res.uri == beispiel_app.UI_URI and res.mime_type == "text/html;profile=mcp-app"
    assert "/*BRUECKE*/" not in html


# ── UI-Verzeichnis pro Plugin ───────────────────────────────────────────────
def test_oberflaeche_aus_einem_pfad(tmp_path: Path):
    (tmp_path / "meine.html").write_text("<html><head><!--STIL--></head><body>Pfad</body></html>")
    assert "Pfad" in oberflaeche("meine.html", tmp_path)


def test_oberflaeche_aus_einem_python_paket(tmp_path: Path, monkeypatch):
    (tmp_path / "meinplugin" / "ui").mkdir(parents=True)
    (tmp_path / "meinplugin" / "__init__.py").write_text("")
    (tmp_path / "meinplugin" / "ui" / "meine.html").write_text("<html><head></head><body>Paket</body></html>")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        assert "Paket" in oberflaeche("meine.html", "meinplugin")
    finally:
        for m in [m for m in sys.modules if m.startswith("meinplugin")]:
            sys.modules.pop(m, None)


def test_plugin_config_ui_verzeichnis(tmp_path: Path):
    (tmp_path / "beispiel-app.html").write_text("<html><head></head><body>Eigene Oberflaeche</body></html>")
    p = BeispielAppPlugin({"ui_verzeichnis": str(tmp_path)})
    assert "Eigene Oberflaeche" in p.describe_resources()[0].read()
