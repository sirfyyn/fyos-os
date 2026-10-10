import json
from pathlib import Path

import pytest
import yaml

from fyos_installer import abnahme as abn
from fyos_installer import erzeugen as e
from fyos_installer import katalog as kat
from fyos_installer import reife

README = Path(__file__).resolve().parents[1] / "README.md"


def _stufen(katalog, auswahl):
    return {r.schicht: r.stufe for r in reife.bestimme([katalog[i] for i in kat.aufloesen(katalog, auswahl)])}


def test_leiter_ist_vollstaendig():
    assert set(reife.LEITER) == set(reife.SCHICHTEN) == set(reife.TITEL) == set(reife.FRAGE)
    saetze = []
    for schicht, leiter in reife.LEITER.items():
        assert len(leiter) == reife.MAX_STUFE, schicht
        for stufe in leiter:
            assert stufe.name.strip() and stufe.erkennbar.strip().endswith("."), (schicht, stufe)
            assert "\n" not in stufe.erkennbar
            saetze.append(stufe.erkennbar)
    assert len(set(saetze)) == len(saetze)


def test_kern_und_agent_sind_stufe_1(katalog):
    assert _stufen(katalog, []) == {"gedaechtnis": 1, "agent": 1, "takte": 1, "oberflaeche": 1}


def test_bausteine_heben_ihre_schichten(katalog):
    assert _stufen(katalog, ["beispiel_app"]) == {"gedaechtnis": 1, "agent": 2, "takte": 1, "oberflaeche": 2}
    assert _stufen(katalog, ["haus"]) == {"gedaechtnis": 2, "agent": 2, "takte": 1, "oberflaeche": 2}
    assert _stufen(katalog, ["leitstand"]) == {"gedaechtnis": 3, "agent": 3, "takte": 2, "oberflaeche": 3}


def test_die_hoechste_stufe_zaehlt(katalog):
    assert _stufen(katalog, ["haus", "leitstand", "finanzen"]) == _stufen(katalog, ["leitstand"])
    assert _stufen(katalog, ["haus", "konten"]) == _stufen(katalog, ["haus"])


def test_jede_schicht_reicht_im_standardkatalog_ueber_stufe_1(katalog):
    # Takte Stufe 3 gibt es nur über die Konfiguration (takt_grenzen), nicht über einen Baustein des Katalogs.
    erreichbar = {s: max([b.reife.get(s, 1) for b in katalog]) for s in reife.SCHICHTEN}
    assert erreichbar == {"gedaechtnis": 3, "agent": 3, "takte": 2, "oberflaeche": 3}


def test_antwort_pro_schicht(katalog):
    r = reife.bestimme([katalog["kern"], katalog["agent"], katalog["haus"]])
    assert [x.schicht for x in r] == list(reife.SCHICHTEN)
    gedaechtnis = r[0]
    assert (gedaechtnis.titel, gedaechtnis.stufe, gedaechtnis.name) == ("Gedächtnis", 2, "Wissen aus Bausteinen")
    assert gedaechtnis.erkennbar == reife.LEITER["gedaechtnis"][1].erkennbar
    assert gedaechtnis.naechste == reife.LEITER["gedaechtnis"][2].erkennbar
    d = gedaechtnis.als_dict()
    assert d["stufe"] == 2 and d["von"] == 3 and d["schicht"] == "gedaechtnis"
    assert gedaechtnis.zeile() == "Gedächtnis: Stufe 2 von 3 (Wissen aus Bausteinen)"
    oben = reife.bestimme([katalog["leitstand"]])[0]
    assert oben.stufe == 3 and oben.naechste == ""  # auf der obersten Stufe gibt es keine nächste


def _mit_grenzen(katalog, **plugin):
    b = kat.Baustein(**{**katalog["beispiel_app"].__dict__, "id": "eigen", "reife": {}, "hub_plugins": [plugin]})
    return reife.stufen_von([katalog["kern"], b])


def test_takt_grenzen_in_der_hub_konfiguration_heben_auf_stufe_3(katalog):
    ohne = _mit_grenzen(katalog, name="openclaw", config={"modus": "an"})
    assert ohne["takte"] == 1
    mit = _mit_grenzen(katalog, name="openclaw", config={"takt_grenzen": {"cron": {"max_pro_tag": 4, "fenster": "07:00-22:00"}}})
    assert mit["takte"] == 3
    # abgeschaltet zählt nicht, leer auch nicht
    assert _mit_grenzen(katalog, name="openclaw", enabled=False, config={"takt_grenzen": {"cron": {"max_pro_tag": 4}}})["takte"] == 1
    assert _mit_grenzen(katalog, name="openclaw", config={"takt_grenzen": {}})["takte"] == 1
    assert _mit_grenzen(katalog, name="openclaw", config="kaputt")["takte"] == 1


def test_plan_traegt_den_reifegrad(katalog, tmp_path):
    plan = e.erstelle_plan(katalog, ["beispiel_app"], "dateien", {}, tmp_path / "o")
    assert plan.ok, plan.fehler
    assert {r.schicht: r.stufe for r in plan.reife} == {"gedaechtnis": 1, "agent": 2, "takte": 1, "oberflaeche": 2}
    d = plan.als_dict()
    assert [r["schicht"] for r in d["reife"]] == list(reife.SCHICHTEN)
    json.dumps(d)  # nur JSON-Typen: der Web-Assistent schickt es so
    # auch ein Plan mit Fehlern nennt den Reifegrad der Auswahl; ein unbekannter Baustein bricht vorher ab
    kaputt = e.erstelle_plan(katalog, ["haus"], "compose", {}, tmp_path / "k")
    assert not kaputt.ok and kaputt.reife
    assert e.erstelle_plan(katalog, ["nix"], "compose", {}, tmp_path / "n").reife == []


def test_reifegrad_steht_in_der_kommandozeile(katalog, tmp_path):
    from fyos_installer import cli

    plan = e.erstelle_plan(katalog, [], "dateien", {}, tmp_path / "o")
    zeilen = []
    cli.zeige_plan(plan, zeilen.append)
    text = "\n".join(zeilen)
    assert "Reifegrad" in text and "Gedächtnis: Stufe 1 von 3 (Persona)" in text
    assert "Erkennbar: " + reife.LEITER["takte"][0].erkennbar in text
    assert "Nächste Stufe: " + reife.LEITER["oberflaeche"][1].erkennbar in text


# ---------------------------------------------------------------- Die README sagt dasselbe wie der Code


def test_readme_nennt_die_leiter():
    zellen_je_zeile = [[c.strip() for c in z.strip().strip("|").split("|")] for z in README.read_text(encoding="utf-8").splitlines() if z.startswith("| ")]
    tabelle = {z[0]: z[1:] for z in zellen_je_zeile if len(z) == 4 and z[0] in reife.TITEL.values()}
    assert tabelle == {reife.TITEL[s]: [st.name for st in reife.LEITER[s]] for s in reife.SCHICHTEN}


def test_readme_nennt_die_proben_der_abnahme():
    text = README.read_text(encoding="utf-8")
    for p in (abn.GEGENPROBE, *abn.PROBEN):
        assert f"`{p.methode} {p.pfad}`" in text, p.id
        assert f"`{p.daten['tool']}`" in text, p.id
        if p.art:
            assert f"`kind: {p.art}`" in text, p.id
    assert "Origin" in text and "Sec-Fetch-Site: cross-site" in text
    assert "--abnahme" in text and "`3`" in text


# ---------------------------------------------------------------- Katalog-Schema


def _roh():
    return yaml.safe_load(kat.STANDARD_KATALOG.read_text())


def test_standardkatalog_nennt_nur_gueltige_schichten(katalog):
    for b in katalog:
        assert set(b.reife) <= set(reife.SCHICHTEN), b.id
        assert all(1 <= n <= reife.MAX_STUFE for n in b.reife.values()), b.id
    assert katalog["kern"].reife == {} and katalog["agent"].reife == {}  # sie sind die Stufe 1


@pytest.mark.parametrize(
    "wert",
    [{"zukunft": 2}, {"agent": 0}, {"agent": 4}, {"agent": "2"}, {"agent": True}, {"agent": 1.5}, ["agent"], "agent"],
)
def test_reife_im_katalog_wird_geprueft(wert):
    d = _roh()
    d["bausteine"][2]["reife"] = wert
    with pytest.raises(kat.KatalogFehler, match="reife"):
        kat.parse(d, "test")


def test_reife_im_katalog_ist_optional():
    d = _roh()
    for b in d["bausteine"]:
        b.pop("reife", None)
    assert all(b.reife == {} for b in kat.parse(d, "test"))
    d["bausteine"][2]["reife"] = None
    assert kat.parse(d, "test")[2].reife == {}


def _plugin_katalog(tmp_path, **extra):
    f = tmp_path / "fyos-katalog.yaml"
    f.write_text(yaml.safe_dump({"bausteine": [{
        "id": "haus", "titel": "Fremd", "kurz": "k", "was_daraus_wird": "Eins. Zwei. Drei.", "art": "plugin",
        "abhaengig_von": ["kern"], **extra,
    }]}))
    return f


def test_ersetzter_baustein_behaelt_den_reifegrad(tmp_path):
    k = kat.lade_standard([str(_plugin_katalog(tmp_path))], plugins=False)
    assert k["haus"].titel == "Fremd" and k["haus"].reife == {"oberflaeche": 2, "agent": 2, "gedaechtnis": 2}


def test_ersetzender_baustein_darf_seinen_eigenen_nennen(tmp_path):
    k = kat.lade_standard([str(_plugin_katalog(tmp_path, reife={"agent": 3}))], plugins=False)
    assert k["haus"].reife == {"agent": 3}


def test_neuer_baustein_ohne_reife_zaehlt_nicht_mit(katalog, tmp_path):
    f = tmp_path / "fyos-katalog.yaml"
    f.write_text(yaml.safe_dump({"bausteine": [{
        "id": "fremd", "titel": "Fremd", "kurz": "k", "was_daraus_wird": "Eins. Zwei. Drei.", "art": "plugin",
        "abhaengig_von": ["kern"],
    }]}))
    k = kat.lade_standard([str(f)], plugins=False)
    assert _stufen(k, ["fremd"]) == _stufen(k, [])
