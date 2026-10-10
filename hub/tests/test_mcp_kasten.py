"""mcp (Werkzeugkasten): Übersicht, Detail, „Ausprobieren“ und was dabei nie durchgehen darf.

Die Quelle ist eine echte `PluginRegistry` mit ein paar Attrappen-Plugins; nichts geht ins Netz. Geprüft wird:

  * die Übersicht trägt Plugins mit Gesundheit, Werkzeuge mit Scope/Sichtbarkeit/App, Apps, Ressourcen, Zugänge,
  * das Detail macht aus dem Schema lesbare Felder und einen Beispielaufruf,
  * „Ausprobieren“ lässt NUR lesende, für das Modell sichtbare Flächen-Werkzeuge außerhalb privater Plugins zu und
    schwärzt Felder, die nach Geheimnis heißen,
  * keine Geheimnisse in der Übersicht (Gesundheitsgrund entschärft),
  * die Identität „MCP“, die Ressource, der Eintrag in der ConfigMap.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from mcp_hub import registry as hub_registry
from mcp_hub.plugin import HubPlugin, ToolDescriptor
from mcp_hub.plugins import _identitaet as ident
from mcp_hub.plugins import mcp_kasten
from mcp_hub.plugins.mcp_kasten import (
    McpPlugin,
    beispiel_aus_felder,
    entschaerfen,
    felder_aus_schema,
    schwaerzen,
)

WURZEL = pathlib.Path(__file__).resolve().parents[2]


# ── Attrappen ────────────────────────────────────────────────────────────────────────────────────


class _Attrappe(HubPlugin):
    """Ein Plugin mit frei wählbaren Werkzeugen und festem Rückgabewert je Werkzeug."""

    def __init__(self, name: str, werkzeuge: list[ToolDescriptor], ergebnisse: dict[str, Any] | None = None, health: dict | None = None):
        super().__init__()
        self.name = name
        self.version = "1.2.3"
        self.description = f"Attrappe {name}\nzweite Zeile"
        self._w = werkzeuge
        self._e = ergebnisse or {}
        self._h = health if health is not None else {"ok": True}
        self.gerufen: list[tuple[str, dict]] = []

    def register(self) -> None:
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return self._w

    def health(self) -> dict[str, Any]:
        return self._h

    def call(self, method: str, args: dict[str, Any]) -> Any:
        self.gerufen.append((method, args))
        r = self._e.get(method, {"ok": True})
        if isinstance(r, Exception):
            raise r
        return r


def _wz(name: str, tags: list[str], meta: dict | None = None, schema: dict | None = None, beschreibung: str = "Zeile eins\nZeile zwei") -> ToolDescriptor:
    return ToolDescriptor(name=name, description=beschreibung, input_schema=schema or {"type": "object", "properties": {}}, tags=tags, meta=meta)


SCHEMA = {
    "type": "object",
    "properties": {
        "raum": {"type": "string", "description": "Raum", "enum": ["bad", "flur"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        "nur_an": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "bis": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "Ende"},
        "name": {"type": "string", "description": "Pflicht"},
    },
    "required": ["name", "raum"],
}


@pytest.fixture()
def kasten():
    reg = hub_registry.PluginRegistry()
    demo = _Attrappe(
        "demo",
        [
            _wz("lesen", ["read", "flaeche"], schema=SCHEMA),
            _wz("app_lesen", ["read"], meta={"ui": {"resourceUri": "ui://fyos/demo.html", "visibility": ["app"]}}),
            _wz("mit_app", ["read"], meta={"ui": {"resourceUri": "ui://fyos/demo.html"}, "app": {"titel": "Demo", "untertitel": "Satz", "symbol": "sparkles", "ton": 200, "kategorie": "Test"}}),
            _wz("schreiben", ["write", "flaeche"]),
            _wz("nur_mcp", ["read"]),
            _wz("geheim", ["read", "flaeche"]),
            _wz("kaputt", ["read", "flaeche"]),
            _wz("gross", ["read", "flaeche"]),
        ],
        {
            "lesen": {"zeilen": [1, 2], "api_token": "abc", "leer_token": "", "nested": {"Password": "p", "ok": "gut"}},
            "geheim": {"Authorization": "Bearer xyz", "url": "https://u:pw@host/x"},
            "kaputt": RuntimeError("Fehler mit token=SUPERGEHEIM123 im Text"),
            "gross": {f"schluessel_{i}": f"wert {i}" for i in range(6000)},
        },
    )
    privat = _Attrappe("finance", [_wz("konten", ["read", "flaeche"])])
    krank = _Attrappe("krank", [_wz("x", ["read", "flaeche"])], health={"ok": False, "reason": "connect failed https://nutzer:geheim@db.example/x token=ABC123 " + "A" * 60})  # sauber: ok
    aus = _Attrappe("schlaf", [_wz("y", ["read"])], health={"ok": False, "status": "disabled", "reason": "default-off"})
    kasten = McpPlugin()
    for p in (demo, privat, krank, aus, kasten):
        hub_registry._register_one(reg, p.name, p)
    kasten.registry_anbinden(reg)
    reg.nicht_geladen["fehlt"] = "ImportError: kein Modul"
    kasten._demo = demo  # type: ignore[attr-defined]
    kasten._reg_ = reg  # type: ignore[attr-defined]
    return kasten


def _zeile(u: dict, wid: str) -> dict:
    return next(w for w in u["werkzeuge"] if w["id"] == wid)


# ── Übersicht ────────────────────────────────────────────────────────────────────────────────────


def test_uebersicht_traegt_plugins_mit_gesundheit(kasten):
    u = kasten.call("uebersicht", {"voll": True})
    st = {p["name"]: p["status"] for p in u["plugins"]}
    assert st == {"demo": "ok", "finance": "ok", "krank": "krank", "schlaf": "aus", "mcp": "ok", "fehlt": "nicht_geladen"}
    assert u["zaehler"]["ok"] == 3 and u["zaehler"]["krank"] == 1 and u["zaehler"]["aus"] == 1 and u["zaehler"]["nicht_geladen"] == 1
    assert u["zaehler"]["plugins"] == 6
    assert u["zaehler"]["werkzeuge"] == len(u["werkzeuge"])
    assert [p["name"] for p in u["plugins"]] == sorted(p["name"] for p in u["plugins"])


def test_uebersicht_werkzeuge_mit_scope_sichtbarkeit_und_app(kasten):
    u = kasten.call("uebersicht", {"voll": True})
    assert _zeile(u, "demo.lesen")["scope"] == "READ" and _zeile(u, "demo.lesen")["sicht"] == "modell"
    assert _zeile(u, "demo.schreiben")["scope"] == "WRITE"
    assert _zeile(u, "demo.app_lesen")["sicht"] == "app"
    m = _zeile(u, "demo.mit_app")
    assert m["sicht"] == "beide" and m["oberflaeche"] == "ui://fyos/demo.html" and m["app"] == "Demo"
    assert m["mcp_name"] == "demo__mit_app" and m["flaeche"] is True
    assert _zeile(u, "demo.nur_mcp")["flaeche"] is False
    assert _zeile(u, "demo.lesen")["kurz"] == "Zeile eins"
    assert (_zeile(u, "demo.lesen")["felder"], _zeile(u, "demo.lesen")["pflicht"]) == (6, 2)










def test_uebersicht_zeigt_aufrufer_seit_dem_start(kasten):
    hub_registry.flaeche_vermerken("kasten-test-client", "mcp", "2026-07-28")
    u = kasten.call("uebersicht", {"voll": True})
    e = next(f for f in u["flaechen"] if f["aufrufer"] == "kasten-test-client")
    assert e["weg"] == "mcp" and e["protokolle"] == {"2026-07-28": 1} and e["anzahl"] >= 1


def test_gesundheit_wird_kurz_zwischengespeichert_und_frisch_neu_geprueft(kasten):
    reg = kasten._reg_
    zaehler = {"n": 0}
    echt = reg.health_check_all

    def zaehlen():
        zaehler["n"] += 1
        return echt()

    reg.health_check_all = zaehlen
    kasten.call("uebersicht", {"voll": True})
    kasten.call("uebersicht", {"voll": True})
    assert zaehler["n"] == 1
    kasten.call("uebersicht", {"frisch": True})
    assert zaehler["n"] == 2


def test_keine_geheimnisse_in_der_uebersicht(kasten):
    text = json.dumps(kasten.call("uebersicht", {"voll": True}), ensure_ascii=False)
    for geheim in ("geheim@", "admin:geheim", "ABC123", "A" * 60):
        assert geheim not in text
    krank = next(p for p in kasten.call("uebersicht", {"voll": True})["plugins"] if p["name"] == "krank")
    assert "«entfernt»" in krank["grund"] and len(krank["grund"]) <= mcp_kasten.ZEICHEN_GRUND


def test_uebersicht_ohne_register_ist_ein_klarer_fehler():
    with pytest.raises(RuntimeError, match="Register"):
        McpPlugin().call("uebersicht", {"voll": True})


def test_uebersicht_knapp_ist_der_standard_ohne_werkzeugkatalog(kasten):
    k = kasten.call("uebersicht", {})
    assert k["knapp"] is True and "werkzeuge" not in k and "apps" not in k and "ressourcen" not in k
    assert "nicht gesund" in k["satz"]
    assert k["zaehler"]["plugins"] == 6 and k["zaehler"]["werkzeuge"] == kasten.call("uebersicht", {"voll": True})["zaehler"]["werkzeuge"]
    assert {p["name"] for p in k["plugins"]} == {"demo", "finance", "krank", "schlaf", "mcp", "fehlt"}
    assert next(p for p in k["plugins"] if p["name"] == "krank")["grund"]
    assert len(json.dumps(k, ensure_ascii=False)) < 10_000


def test_uebersicht_knapp_mit_plugin_liefert_dessen_werkzeuge(kasten):
    k = kasten.call("uebersicht", {"plugin": "demo"})
    assert k["werkzeuge"] and all(w["id"].startswith("demo.") for w in k["werkzeuge"])
    with pytest.raises(ValueError, match="unbekanntes Plugin"):
        kasten.call("uebersicht", {"plugin": "gibtsnicht"})


def test_uebersicht_voll_hat_den_satz_und_den_katalog(kasten):
    u = kasten.call("uebersicht", {"voll": True})
    assert u["satz"] and "knapp" not in u and u["werkzeuge"]


# ── Detail ───────────────────────────────────────────────────────────────────────────────────────


def test_felder_aus_schema_liest_typen_pflicht_auswahl_und_grenzen():
    f = {x["name"]: x for x in felder_aus_schema(SCHEMA)}
    assert [x["name"] for x in felder_aus_schema(SCHEMA)][:2] in (["name", "raum"], ["raum", "name"])
    assert f["raum"]["auswahl"] == ["bad", "flur"] and f["raum"]["pflicht"] is True
    assert (f["limit"]["typ"], f["limit"]["von"], f["limit"]["bis"], f["limit"]["standard"]) == ("integer", 1, 50, 10)
    assert f["nur_an"]["typ"] == "boolean" and f["nur_an"]["typ_text"] == "Ja/Nein"
    assert f["tags"]["liste_von"] == "Text"
    assert f["bis"]["typ"] == "string" and f["bis"]["leer_erlaubt"] is True
    assert felder_aus_schema(None) == [] and felder_aus_schema({"type": "object"}) == []


def test_beispielaufruf_hat_nur_pflichtfelder():
    assert beispiel_aus_felder(felder_aus_schema(SCHEMA)) == {"name": "", "raum": "bad"}


def test_detail_traegt_felder_schema_beispiel_und_link(kasten):
    d = kasten.call("werkzeug", {"name": "demo.lesen"})
    assert d["ok"] and d["id"] == "demo.lesen" and len(d["eingabefelder"]) == 6
    assert d["schema"] == SCHEMA and d["beispiel"] == {"name": "", "raum": "bad"}
    assert d["beschreibung"].splitlines() == ["Zeile eins", "Zeile zwei"]
    assert d["oeffnen"] is None  # Pflichtfeld → kein Link
    mit = kasten.call("werkzeug", {"name": "demo.mit_app"})
    assert mit["oeffnen"] == ident.oeffnen_link("demo.mit_app")
    assert kasten.call("werkzeug", {"name": "mcp.uebersicht"})["oeffnen"]


def test_detail_zeigt_die_kurze_ansicht_fuer_modelle(kasten, monkeypatch):
    from mcp_hub import ansicht

    monkeypatch.setattr(ansicht, "ABLAGE", ansicht.Ablage(redis=None))
    ansicht.ABLAGE._redis_versucht = True  # noqa: SLF001 — kein Redis im Test
    assert kasten.call("werkzeug", {"name": "demo.lesen"})["kurze_ansicht"]["felder"] == []
    ansicht.merken("demo.lesen", "eintraege", ["raum"])
    k = kasten.call("werkzeug", {"name": "demo.lesen"})["kurze_ansicht"]
    assert k["felder"] == [{"pfad": "eintraege", "feld": "raum", "herkunft": "gelernt", "nachfragen": ansicht.LERN_SCHWELLE}]


def test_detail_unbekannt_und_leer(kasten):
    with pytest.raises(ValueError, match="unbekanntes Werkzeug"):
        kasten.call("werkzeug", {"name": "demo.gibtsnicht"})
    with pytest.raises(ValueError, match="erforderlich"):
        kasten.call("werkzeug", {"name": "  "})
    with pytest.raises(ValueError, match="hat kein Werkzeug"):
        kasten.call("loeschen", {})


# ── Ausprobieren ─────────────────────────────────────────────────────────────────────────────────










def test_ausprobieren_lesend_und_schwaerzt_geheimnisse(kasten):
    r = kasten.call("ausprobieren", {"werkzeug": "demo.lesen", "arguments": {"name": "a", "raum": "bad"}})
    assert r["ok"] and r["ms"] >= 0 and r["gekuerzt"] is False
    antwort = json.loads(r["text"])
    assert antwort["zeilen"] == [1, 2]
    assert antwort["api_token"] == "«entfernt»" and antwort["nested"]["Password"] == "«entfernt»"
    assert antwort["leer_token"] == "" and antwort["nested"]["ok"] == "gut"
    assert "abc" not in r["text"]
    assert kasten._demo.gerufen == [("lesen", {"name": "a", "raum": "bad"})]


def test_ausprobieren_entschaerft_auch_texte_und_adressen(kasten):
    r = kasten.call("ausprobieren", {"werkzeug": "demo.geheim", "arguments": {}})
    assert r["ok"] and "Bearer xyz" not in r["text"] and "u:pw@" not in r["text"] and "«entfernt»" in r["text"]


def test_ausprobieren_fehler_ohne_geheimnis(kasten):
    r = kasten.call("ausprobieren", {"werkzeug": "demo.kaputt", "arguments": {}})
    assert r["ok"] is False and "SUPERGEHEIM123" not in r["error"] and r["ms"] >= 0


def test_ausprobieren_kuerzt_grosse_ergebnisse(kasten):
    r = kasten.call("ausprobieren", {"werkzeug": "demo.gross", "arguments": {}})
    assert r["ok"] and r["gekuerzt"] is True and len(r["text"]) == mcp_kasten.ERGEBNIS_MAX_ZEICHEN and r["zeichen"] > len(r["text"])


def test_ausprobieren_unbekannt_und_falsche_argumente(kasten):
    with pytest.raises(ValueError, match="unbekanntes Werkzeug"):
        kasten.call("ausprobieren", {"werkzeug": "demo.nix"})
    with pytest.raises(ValueError, match="erforderlich"):
        kasten.call("ausprobieren", {})
    with pytest.raises(ValueError, match="Objekt"):
        kasten.call("ausprobieren", {"werkzeug": "demo.lesen", "arguments": [1]})




# ── Entschärfen und Schwärzen ────────────────────────────────────────────────────────────────────


def test_entschaerfen():
    assert entschaerfen("postgres://u:pw@host/db") == "postgres://«entfernt»@host/db"
    assert "hunter2" not in entschaerfen('password: "hunter2" und mehr')
    assert "x" * 50 not in entschaerfen("Schluessel " + "x" * 50)
    lang = entschaerfen("a " * 400)
    assert len(lang) <= mcp_kasten.ZEICHEN_GRUND and lang.endswith("…")
    assert entschaerfen(None) == ""


def test_schwaerzen_laesst_leere_und_normale_werte():
    assert schwaerzen({"token": None, "secret": "", "ok": 1, "liste": [{"cookie": "c"}]}) == {
        "token": None,
        "secret": "",
        "ok": 1,
        "liste": [{"cookie": "«entfernt»"}],
    }
    tief: Any = "blatt"
    for _ in range(20):
        tief = {"a": tief}
    assert "«zu tief»" in json.dumps(schwaerzen(tief), ensure_ascii=False)


# ── Identität, Ressource, Verdrahtung ────────────────────────────────────────────────────────────


def test_identitaet_ressource_und_oberflaeche():
    assert ident.APPS["mcp"]["titel"] == "MCP" and ident.DATEIEN["mcp.html"] == "mcp"
    assert ident.HAUPTWERKZEUG["mcp"] == "mcp__uebersicht"
    res = McpPlugin().describe_resources()
    assert [r.uri for r in res] == ["ui://fyos/mcp.html"]
    html = res[0].read()
    assert "<title>MCP</title>" in html and "/*STIL*/" not in html and "/*BRUECKE*/" not in html


def test_werkzeuge_tragen_die_app_und_sind_lesend():
    tools = McpPlugin().describe_tools()
    assert [t.name for t in tools] == ["uebersicht", "werkzeug", "ausprobieren", "zeitplan"]
    for t in tools:
        assert hub_registry.scope_from_tags(t.tags) == "READ" and hub_registry.ist_flaechen_werkzeug(t)
        if t.name != "zeitplan":  # der Zeitplan ist ein reines Datenwerkzeug ohne Oberfläche
            assert t.meta["ui"]["resourceUri"] == "ui://fyos/mcp.html" and t.meta["app"]["titel"] == "MCP"


def test_zeitplan_sammelt_die_plugins_und_uebersteht_fehler():
    from types import SimpleNamespace

    class _MitTakt(_Attrappe):
        def zeitplan(self):
            return [
                {"id": "a", "name": "Aufräumen", "takt": "alle 60 s", "letzter": 100.0, "letzter_status": "ok",
                 "naechster": 200.0},
                {"id": "b", "name": "Brief", "takt": "0 6 * * *", "quelle": "openclaw", "letzter_status": "fehler",
                 "letzter_fehler": "Zeitlimit"},
                {"name": "ohne id"},
            ]

    class _Kaputt(_Attrappe):
        def zeitplan(self):
            raise RuntimeError("weg")

    reg = SimpleNamespace(plugins={"takt": _MitTakt("takt", []), "kaputt": _Kaputt("kaputt", [])})
    plugin = McpPlugin()
    plugin.registry_anbinden(reg)
    alles = plugin.call("zeitplan", {})
    assert [e["id"] for e in alles["eintraege"]] == ["takt:a", "takt:b"]
    assert alles["eintraege"][1]["quelle"] == "openclaw" and alles["eintraege"][1]["letzter_status"] == "fehler"
    assert "kaputt" in alles["fehler"] and "Brief" in alles["satz"]
    nur = plugin.call("zeitplan", {"quelle": "openclaw"})
    assert [e["name"] for e in nur["eintraege"]] == ["Brief"]
    # Ohne Grenzen tragen die Einträge die Felder leer.
    a = alles["eintraege"][0]
    assert (a["max_pro_tag"], a["fenster"], a["ruht"], a["laeufe_heute"], a["uebersprungen"], a["protokoll"]) == \
           (None, None, None, None, {}, [])


def test_zeitplan_zeigt_grenzen_uebersprungene_und_protokoll():
    from types import SimpleNamespace

    class _MitGrenzen(_Attrappe):
        def zeitplan(self):
            return [{"id": "abgleich", "name": "Abgleich", "takt": "alle 60 s", "max_pro_tag": 500,
                     "fenster": "07:00-22:00", "ruht": "fenster", "laeufe_heute": 12,
                     "uebersprungen": {"fenster": 40, "limit": 0},
                     "protokoll": [{"start": 1_790_000_000, "dauer_s": 0.4, "ergebnis": "ok"}]}]

    plugin = McpPlugin()
    plugin.registry_anbinden(SimpleNamespace(plugins={"takt": _MitGrenzen("takt", [])}))
    ergebnis = plugin.call("zeitplan", {})
    (e,) = ergebnis["eintraege"]
    assert (e["max_pro_tag"], e["fenster"], e["ruht"], e["laeufe_heute"]) == (500, "07:00-22:00", "fenster", 12)
    assert e["uebersprungen"] == {"fenster": 40, "limit": 0}
    assert e["protokoll"] == [{"start": 1_790_000_000.0, "dauer_s": 0.4, "ergebnis": "ok"}]
    assert "ruhen gerade" in ergebnis["satz"] and "Abgleich" in ergebnis["satz"]




