import copy
import re
from types import SimpleNamespace

import pytest
import yaml

from fyos_installer import katalog as kat

ERWARTET = {
    "kern", "agent", "beispiel_app", "finanzen", "haus", "konten", "kalender", "mail", "betrieb", "eigenes_modell",
    "leitstand",
}


def test_standardkatalog_gueltig(katalog):
    assert ERWARTET <= set(katalog.bausteine)
    assert katalog["kern"].pflicht and katalog["agent"].pflicht
    assert katalog["eigenes_modell"].paket == "fyos-plugin-modell"
    assert katalog["leitstand"].repo == "fyos-plugin-leitstand"
    for b in katalog:
        for f in b.konfiguration:
            assert f.titel and f.titel != f.name, (b.id, f.name)


def test_kalender_baustein(katalog):
    k = katalog["kalender"]
    assert (k.paket, k.repo, k.art) == ("fyos-plugin-kalender", "fyos-plugin-kalender", "plugin")
    # die Namen, die das Plugin liest; das Passwort ist ein Geheimnis und steht nie im Klartext in der Oberfläche
    assert {f.name: (k.umgebungsname(f), f.typ) for f in k.konfiguration} == {
        "url": ("FYOS_KALENDER_URL", "url"),
        "nutzer": ("FYOS_KALENDER_NUTZER", "text"),
        "passwort": ("FYOS_KALENDER_PASSWORT", "geheim"),
    }
    assert k.abhaengig_von == ["kern", "agent"] and not k.pflicht


def test_mail_baustein(katalog):
    m = katalog["mail"]
    assert (m.paket, m.repo, m.art) == ("fyos-plugin-mail", "fyos-plugin-mail", "plugin")
    # die Namen, die das Plugin liest; das Passwort ist ein Geheimnis und steht nie im Klartext in der Oberfläche
    assert {f.name: (m.umgebungsname(f), f.typ) for f in m.konfiguration} == {
        "host": ("FYOS_MAIL_HOST", "text"),
        "port": ("FYOS_MAIL_PORT", "zahl"),
        "nutzer": ("FYOS_MAIL_NUTZER", "text"),
        "passwort": ("FYOS_MAIL_PASSWORT", "geheim"),
    }
    assert {f.name: f.standard for f in m.konfiguration}["port"] == 993  # IMAPS
    assert m.abhaengig_von == ["kern", "agent"] and not m.pflicht


def test_leitstand_nennt_die_dokumente_quelle(katalog):
    b = katalog["leitstand"]
    felder = {f.name: (b.umgebungsname(f), f.typ, f.pflicht) for f in b.konfiguration}
    # das Token (oder eine andere Anmeldung) ist ein Geheimnis und steht nie im Klartext in der Oberfläche
    assert felder["dokumente_url"] == ("FYOS_DOKUMENTE_URL", "url", False)
    assert felder["dokumente_kopf"] == ("FYOS_DOKUMENTE_KOPF", "geheim", False)
    assert felder["dokumente_link"] == ("FYOS_DOKUMENTE_LINK", "url", False)
    assert any("Paperless" in v for v in b.voraussetzungen)


def test_texte_und_bilder(katalog):
    for b in katalog:
        saetze = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])", b.was_daraus_wird)
        assert 3 <= len(saetze) <= 8, b.id
        assert "\n" not in b.kurz
        assert b.bilder and len(kat.bilder_von(b)) == len(b.bilder), b.id
        for p in kat.bilder_von(b):
            assert "<title" in p.read_text() and "Skizze" in p.read_text()


def test_aufloesen_ordnung(katalog):
    ids = kat.aufloesen(katalog, ["finanzen"])
    assert ids.index("kern") < ids.index("agent") < ids.index("finanzen")
    assert kat.aufloesen(katalog, []) == ["kern", "agent"]
    with pytest.raises(kat.KatalogFehler):
        kat.aufloesen(katalog, ["gibtsnicht"])
    assert "finanzen" in kat.abhaengige_von(katalog, "agent")


def _roh():
    return copy.deepcopy(yaml.safe_load(kat.STANDARD_KATALOG.read_text()))


@pytest.mark.parametrize(
    "aendern",
    [
        lambda d: d["bausteine"][0].pop("id"),
        lambda d: d["bausteine"][0].update(art="weltall"),
        lambda d: d["bausteine"][0].update(kurz="a\nb"),
        lambda d: d["bausteine"][3]["konfiguration"][0].update(typ="zauber"),
        lambda d: d["bausteine"][3]["konfiguration"][0].update(typ="wahl"),
        lambda d: d["bausteine"][0].update(bilder=["../x.svg"]),
        lambda d: d["bausteine"][0]["konfiguration"][0].pop("titel"),
        lambda d: d["bausteine"][3].update(quelle={"repo": "nur-repo"}),
        lambda d: d["bausteine"][3].update(quelle="name mit leerzeichen"),
        lambda d: d["bausteine"][1].update(pflicht="ja"),
        lambda d: d["bausteine"].append(copy.deepcopy(d["bausteine"][0])),
    ],
)
def test_schema_verstoesse(aendern):
    d = _roh()
    aendern(d)
    with pytest.raises(kat.KatalogFehler):
        kat.parse(d, "test")


def test_unbekannte_abhaengigkeit_und_zyklus():
    d = _roh()
    d["bausteine"][2]["abhaengig_von"] = ["nix"]
    with pytest.raises(kat.KatalogFehler):
        kat.Katalog(kat.parse(d, "t"))
    d = _roh()
    d["bausteine"][0]["abhaengig_von"] = ["agent"]
    with pytest.raises(kat.KatalogFehler, match="Zyklus"):
        kat.Katalog(kat.parse(d, "t"))


def _fremd(tmp_path, id_="fremd"):
    f = tmp_path / "fyos-katalog.yaml"
    f.write_text(yaml.safe_dump({"bausteine": [{
        "id": id_, "titel": "Fremd", "kurz": "k", "was_daraus_wird": "Eins. Zwei. Drei.", "art": "plugin",
        "abhaengig_von": ["kern"],
    }]}))
    return f


def test_katalog_option_fuehrt_zusammen(tmp_path):
    k = kat.lade_standard([str(_fremd(tmp_path))], plugins=False)
    assert "fremd" in k and kat.aufloesen(k, ["fremd"])[-1] == "fremd"


def test_gleiche_id_anderer_katalog_ersetzt(tmp_path):
    k = kat.lade_standard([str(_fremd(tmp_path, "haus"))], plugins=False)
    assert k["haus"].titel == "Fremd" and k.hinweise


def test_entry_point_katalog(tmp_path, monkeypatch):
    f = _fremd(tmp_path, "viaep")
    ep = SimpleNamespace(name="x", dist=SimpleNamespace(name="fyos-plugin-x"), load=lambda: (lambda: f))
    monkeypatch.setattr(kat.metadata, "entry_points", lambda group: [ep] if group == "fyos.katalog" else [])
    monkeypatch.setattr(kat.metadata, "distributions", lambda: [])
    assert "viaep" in kat.lade_standard().bausteine


def test_bilder_png_vor_svg(tmp_path, katalog):
    (tmp_path / "x-1.svg").write_text("<svg/>")
    (tmp_path / "x-1.png").write_bytes(b"png")
    b = katalog["kern"]
    b2 = kat.Baustein(**{**b.__dict__, "bilder": ["x-1.svg"], "bilder_verzeichnis": tmp_path})
    assert kat.bilder_von(b2)[0].suffix == ".png"


def test_quelle(katalog):
    with pytest.raises(kat.KatalogFehler, match="FYOS_PLUGIN_QUELLE"):
        kat.quelle_aufloesen(katalog["haus"], "git", "")
    with pytest.raises(kat.KatalogFehler, match="FYOS_PAKETINDEX"):
        kat.quelle_aufloesen(katalog["haus"], "index", "", "")
    spec = kat.quelle_aufloesen(katalog["haus"], "git", "https://g.example.com/f/")
    assert spec == "fyos-plugin-haus @ git+https://g.example.com/f/fyos-plugin-haus.git"
    assert kat.quelle_aufloesen(katalog["haus"], "index", "", "https://i.example.com/simple") == "fyos-plugin-haus"
    assert kat.quelle_aufloesen(katalog["kern"], "git", "") is None


def test_textvorschau(katalog):
    t = kat.textvorschau(katalog["kern"])
    assert "Skizze" in t and "kern-1.svg" in t
