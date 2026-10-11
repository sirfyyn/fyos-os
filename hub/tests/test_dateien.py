"""Die Dateiquelle des Kerns (``mcp_hub.dateien``): Pfadsicherheit, Größendeckel, Versionen, Papierkorb, Suche."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from mcp_hub import dateien
from mcp_hub.dateien import Existiert, Fehler, NichtEingerichtet, NichtGefunden, QuelleFehler, Verzeichnis, ZuGross


@pytest.fixture
def ablage(tmp_path: Path) -> Verzeichnis:
    return Verzeichnis(tmp_path / "ablage", max_bytes=1024, versionen=3, papierkorb_tage=30)


# ── Pfade: nichts verlässt die Wurzel ──────────────────────────────────────────


@pytest.mark.parametrize(
    "pfad",
    ["../x", "a/../../x", "..", "a/..", "a\\b", "a\x00b", "a\nb", ".fyos/tmp/x", ".FYOS/x", "x" * 300 + "/" + "y" * 300],
)
def test_pfade_mit_ausbruch_oder_verwaltung_werden_abgelehnt(ablage, pfad):
    with pytest.raises(Fehler):
        dateien.normalisiere(pfad)
    with pytest.raises(Fehler):
        ablage.schreiben(pfad, b"x")
    with pytest.raises(Fehler):
        ablage.lesen(pfad)


def test_pfade_werden_gerade_gezogen():
    assert dateien.normalisiere("/a//b/./c.txt") == "a/b/c.txt"
    assert dateien.normalisiere("  ", wurzel_ok=True) == "  "  # ein Name aus Leerzeichen ist ein Name, aber kein Ausbruch
    assert dateien.normalisiere("", wurzel_ok=True) == ""
    assert dateien.normalisiere(None, wurzel_ok=True) == ""
    with pytest.raises(Fehler):
        dateien.normalisiere("")
    with pytest.raises(Fehler):
        dateien.normalisiere(5)


def test_absoluter_pfad_ist_relativ_zur_wurzel(ablage):
    """`/etc/passwd` heißt `etc/passwd` in der Ablage — nie die Datei des Rechners."""
    with pytest.raises(NichtGefunden):
        ablage.lesen("/etc/passwd")
    ablage.schreiben("/etc/passwd", b"meins")
    assert (ablage.wurzel / "etc" / "passwd").read_bytes() == b"meins"


def test_symlink_auf_eine_datei_ausserhalb_wird_nicht_gelesen(ablage, tmp_path):
    geheim = tmp_path / "geheim.txt"
    geheim.write_text("nicht für dich")
    (ablage.wurzel / "link.txt").symlink_to(geheim)
    with pytest.raises(Fehler, match="Symlink"):
        ablage.lesen("link.txt")
    with pytest.raises(Fehler, match="Symlink"):
        ablage.schreiben("link.txt", b"x", ueberschreiben=True)
    assert geheim.read_text() == "nicht für dich"
    assert [e["name"] for e in ablage.liste()["eintraege"]] == []
    assert ablage.suchen("geheim")["treffer"] == []


def test_symlink_auf_einen_ordner_ausserhalb_wird_nicht_betreten(ablage, tmp_path):
    draussen = tmp_path / "draussen"
    draussen.mkdir()
    (draussen / "x.txt").write_text("nicht für dich")
    (ablage.wurzel / "tor").symlink_to(draussen, target_is_directory=True)
    for aufruf in (
        lambda: ablage.liste("tor"),
        lambda: ablage.lesen("tor/x.txt"),
        lambda: ablage.schreiben("tor/neu.txt", b"x"),
        lambda: ablage.loeschen("tor/x.txt"),
        lambda: ablage.verschieben("tor/x.txt", "x.txt"),
        lambda: ablage.verschieben("x.txt", "tor/y.txt"),
    ):
        with pytest.raises(Fehler):
            aufruf()
    assert sorted(p.name for p in draussen.iterdir()) == ["x.txt"]
    assert ablage.suchen("nicht für dich")["treffer"] == []


def test_wurzel_darf_selbst_ein_symlink_sein(tmp_path):
    echt = tmp_path / "echt"
    echt.mkdir()
    (tmp_path / "wurzel").symlink_to(echt, target_is_directory=True)
    v = Verzeichnis(tmp_path / "wurzel")
    v.schreiben("a.txt", b"hallo")
    assert (echt / "a.txt").read_bytes() == b"hallo"
    assert v.lesen("a.txt")["text"] == "hallo"


def test_verwaltungsordner_ist_unsichtbar(ablage):
    ablage.schreiben("a.txt", b"1")
    ablage.schreiben("a.txt", b"2", ueberschreiben=True)  # legt .fyos an
    assert (ablage.wurzel / dateien.VERWALTUNG).is_dir()
    assert [e["name"] for e in ablage.liste()["eintraege"]] == ["a.txt"]
    assert ablage.suchen("fyos")["treffer"] == []
    with pytest.raises(Fehler):
        ablage.lesen(".fyos/versionen")


# ── Schreiben, Lesen, Liste ────────────────────────────────────────────────────


def test_schreiben_legt_ordner_an_und_liest_text(ablage):
    plan = ablage.schreiben("Projekt/Notizen/heute.md", "# Titel\nÄhre".encode())
    assert plan["neu"] and not plan["ersetzt"] and plan["groesse"] == len("# Titel\nÄhre".encode())
    r = ablage.lesen("Projekt/Notizen/heute.md")
    assert r["art"] == "text" and r["text"] == "# Titel\nÄhre" and r["typ"] == "text/markdown" and not r["gekuerzt"]


def test_vorhandene_datei_wird_nicht_still_ueberschrieben(ablage):
    ablage.schreiben("a.txt", b"eins")
    with pytest.raises(Existiert, match="ueberschreiben"):
        ablage.schreiben("a.txt", b"zwei")
    assert ablage.lesen("a.txt")["text"] == "eins"
    plan = ablage.schreiben("a.txt", b"zwei", ueberschreiben=True)
    assert plan["ersetzt"] and plan["version_gesichert"]
    assert ablage.lesen("a.txt")["text"] == "zwei"


def test_ordner_und_datei_verwechseln_geht_nicht(ablage):
    ablage.schreiben("d/x.txt", b"1")
    with pytest.raises(Fehler, match="Ordner"):
        ablage.schreiben("d", b"1", ueberschreiben=True)
    with pytest.raises(Fehler, match="Ordner"):
        ablage.lesen("d")
    with pytest.raises(Fehler, match="Datei"):
        ablage.schreiben("d/x.txt/y.txt", b"1")


def test_groessendeckel(ablage):
    ablage.schreiben("klein.bin", b"x" * 1024)
    with pytest.raises(ZuGross, match="zu groß"):
        ablage.schreiben("gross.bin", b"x" * 1025)
    assert not (ablage.wurzel / "gross.bin").exists()


def test_trockenlauf_aendert_nichts(ablage):
    ablage.schreiben("a.txt", b"1")
    stand = sorted(p.relative_to(ablage.wurzel).as_posix() for p in ablage.wurzel.rglob("*"))
    ablage.schreiben("neu/b.txt", b"2", trocken=True)
    ablage.schreiben("a.txt", b"2", ueberschreiben=True, trocken=True)
    ablage.verschieben("a.txt", "c.txt", trocken=True)
    ablage.loeschen("a.txt", trocken=True)
    ablage.ordner_anlegen("ordner", trocken=True)
    assert sorted(p.relative_to(ablage.wurzel).as_posix() for p in ablage.wurzel.rglob("*")) == stand
    assert ablage.lesen("a.txt")["text"] == "1"


def test_binaer_liefert_nur_angaben(ablage):
    ablage.schreiben("bild.png", b"\x89PNG\r\n\x1a\n\x00\x00")
    ablage.schreiben("roh.dat", b"\x00\x01\x02\xff")
    for name in ("bild.png", "roh.dat"):
        r = ablage.lesen(name)
        assert r["art"] == "binaer" and r["text"] is None
    assert ablage.lesen("bild.png")["typ"] == "image/png"


def test_text_ohne_endung_wird_am_inhalt_erkannt(ablage):
    ablage.schreiben("README", "Grüße".encode())
    ablage.schreiben("kaputt", b"\xff\xfe\xfd")
    assert ablage.lesen("README")["art"] == "text"
    assert ablage.lesen("kaputt")["art"] == "binaer"


def test_langer_text_wird_gekuerzt(tmp_path):
    v = Verzeichnis(tmp_path, max_bytes=10_000)
    v.schreiben("lang.txt", ("abcdefghij" * 100).encode())
    r = v.lesen("lang.txt", max_zeichen=250)
    assert len(r["text"]) == 250 and r["gekuerzt"]


def test_liste_ordner_zuerst_und_sortiert(ablage):
    for name in ("b.txt", "A.txt", "z/x.txt", "m/y.txt"):
        ablage.schreiben(name, b"1")
    r = ablage.liste()
    assert [(e["name"], e["art"]) for e in r["eintraege"]] == [("m", "ordner"), ("z", "ordner"), ("A.txt", "datei"), ("b.txt", "datei")]
    assert r["pfad"] == "" and r["eltern"] is None and r["gesamt"] == 4 and not r["gekuerzt"]
    unter = ablage.liste("z")
    assert unter["eltern"] == "" and unter["eintraege"][0]["pfad"] == "z/x.txt"


def test_liste_einer_datei_zeigt_ihren_ordner_mit_auswahl(ablage):
    ablage.schreiben("d/x.txt", b"1")
    ablage.schreiben("d/y.txt", b"1")
    r = ablage.liste("d/x.txt")
    assert r["pfad"] == "d" and r["auswahl"] == "d/x.txt" and len(r["eintraege"]) == 2


def test_liste_eines_fehlenden_ordners(ablage):
    with pytest.raises(NichtGefunden):
        ablage.liste("gibt/es/nicht")


def test_ordner_anlegen(ablage):
    assert ablage.ordner_anlegen("a/b/c")["neu"] is True
    assert ablage.ordner_anlegen("a/b/c")["neu"] is False
    ablage.schreiben("datei.txt", b"1")
    with pytest.raises(Existiert):
        ablage.ordner_anlegen("datei.txt")


def test_nicht_beschreibbarer_ort_ist_ein_quellfehler(tmp_path):
    datei = tmp_path / "datei"
    datei.write_text("x")
    with pytest.raises(QuelleFehler):
        Verzeichnis(datei / "unter")


# ── Verschieben ────────────────────────────────────────────────────────────────


def test_verschieben_und_umbenennen(ablage):
    ablage.schreiben("a.txt", b"1")
    assert ablage.verschieben("a.txt", "neu/ordner/b.txt") == {"von": "a.txt", "nach": "neu/ordner/b.txt", "art": "datei"}
    assert ablage.lesen("neu/ordner/b.txt")["text"] == "1"
    with pytest.raises(NichtGefunden):
        ablage.lesen("a.txt")


def test_verschieben_ueberschreibt_nichts(ablage):
    ablage.schreiben("a.txt", b"1")
    ablage.schreiben("b.txt", b"2")
    with pytest.raises(Existiert):
        ablage.verschieben("a.txt", "b.txt")
    with pytest.raises(Fehler):
        ablage.verschieben("a.txt", "a.txt")
    with pytest.raises(NichtGefunden):
        ablage.verschieben("nix.txt", "c.txt")
    assert ablage.lesen("b.txt")["text"] == "2"


def test_ordner_nicht_in_sich_selbst(ablage):
    ablage.schreiben("d/x.txt", b"1")
    with pytest.raises(Fehler, match="sich selbst"):
        ablage.verschieben("d", "d/e")
    assert ablage.verschieben("d", "dd")["art"] == "ordner"
    assert ablage.lesen("dd/x.txt")["text"] == "1"


# ── Versionen ──────────────────────────────────────────────────────────────────


def test_versionen_sichern_die_alte_fassung_und_bleiben_begrenzt(ablage):
    ablage.schreiben("a.txt", b"v0")
    for i in range(1, 6):
        ablage.schreiben("a.txt", f"v{i}".encode(), ueberschreiben=True)
    vs = ablage.versionen("a.txt")
    assert len(vs) == 3, "die letzten drei"
    assert [ablage.lesen("a.txt", version=v["version"])["text"] for v in vs] == ["v4", "v3", "v2"]
    assert ablage.lesen("a.txt")["text"] == "v5"


def test_version_zurueck_sichert_auch_die_jetzige(ablage):
    ablage.schreiben("a.txt", b"alt")
    ablage.schreiben("a.txt", b"neu", ueberschreiben=True)
    [v] = ablage.versionen("a.txt")
    plan = ablage.version_zurueck("a.txt", v["version"], trocken=True)
    assert plan["ersetzt"] and ablage.lesen("a.txt")["text"] == "neu"
    ablage.version_zurueck("a.txt", v["version"])
    assert ablage.lesen("a.txt")["text"] == "alt"
    assert [ablage.lesen("a.txt", version=x["version"])["text"] for x in ablage.versionen("a.txt")] == ["neu", "alt"]


def test_versionskennung_wird_geprueft(ablage):
    ablage.schreiben("a.txt", b"1")
    for kaputt in ("../../x", "abc", "1", "12345678901234567890123456"):
        with pytest.raises(Fehler):
            ablage.lesen("a.txt", version=kaputt)
    with pytest.raises(NichtGefunden):
        ablage.lesen("a.txt", version="1234567890123456")


def test_versionen_folgen_der_verschobenen_datei_und_dem_ordner(ablage):
    ablage.schreiben("d/a.txt", b"1")
    ablage.schreiben("d/a.txt", b"2", ueberschreiben=True)
    ablage.verschieben("d/a.txt", "d/b.txt")
    assert len(ablage.versionen("d/b.txt")) == 1 and ablage.versionen("d/a.txt") == []
    ablage.verschieben("d", "e")
    assert len(ablage.versionen("e/b.txt")) == 1


def test_ohne_versionen_bleibt_nichts_zurueck(tmp_path):
    v = Verzeichnis(tmp_path, versionen=0)
    v.schreiben("a.txt", b"1")
    assert not v.schreiben("a.txt", b"2", ueberschreiben=True)["version_gesichert"]
    assert v.versionen("a.txt") == []


# ── Papierkorb ─────────────────────────────────────────────────────────────────


def test_loeschen_geht_in_den_papierkorb_und_kommt_zurueck(ablage):
    ablage.schreiben("d/a.txt", b"inhalt")
    erg = ablage.loeschen("d/a.txt")
    assert erg["art"] == "datei" and erg["papierkorb_id"]
    with pytest.raises(NichtGefunden):
        ablage.lesen("d/a.txt")
    [eintrag] = ablage.papierkorb()
    assert eintrag["pfad"] == "d/a.txt" and eintrag["name"] == "a.txt" and eintrag["groesse"] == 6
    ablage.wiederherstellen(eintrag["id"])
    assert ablage.lesen("d/a.txt")["text"] == "inhalt" and ablage.papierkorb() == []


def test_ganzer_ordner_in_den_papierkorb(ablage):
    ablage.schreiben("d/a.txt", b"1")
    ablage.schreiben("d/u/b.txt", b"2")
    erg = ablage.loeschen("d")
    assert erg["art"] == "ordner" and erg["dateien"] == 2
    assert ablage.liste()["eintraege"] == []
    ablage.wiederherstellen(erg["papierkorb_id"])
    assert ablage.lesen("d/u/b.txt")["text"] == "2"


def test_wiederherstellen_belegten_platz_oder_woanders(ablage):
    ablage.schreiben("a.txt", b"alt")
    pid = ablage.loeschen("a.txt")["papierkorb_id"]
    ablage.schreiben("a.txt", b"neu")
    with pytest.raises(Existiert, match="nach"):
        ablage.wiederherstellen(pid)
    ablage.wiederherstellen(pid, "zurueck/a.txt")
    assert ablage.lesen("zurueck/a.txt")["text"] == "alt" and ablage.lesen("a.txt")["text"] == "neu"


def test_papierkorbkennung_wird_geprueft(ablage):
    for kaputt in ("../x", "abc", "", None, 5):
        with pytest.raises(Fehler):
            ablage.wiederherstellen(kaputt)
    with pytest.raises(NichtGefunden):
        ablage.wiederherstellen("1700000000-abcdef")


def test_alter_papierkorb_wird_beim_naechsten_loeschen_geleert(tmp_path):
    v = Verzeichnis(tmp_path, papierkorb_tage=1)
    v.schreiben("alt.txt", b"1")
    pid = v.loeschen("alt.txt")["papierkorb_id"]
    gestern = int(time.time()) - 3 * 86400
    korb = tmp_path / dateien.VERWALTUNG / "papierkorb"
    neu_name = f"{gestern}-{pid.split('-')[1]}"
    (korb / pid).rename(korb / neu_name)
    v.schreiben("neu.txt", b"2")
    v.loeschen("neu.txt")
    ids = [e["id"] for e in v.papierkorb()]
    assert neu_name not in ids and len(ids) == 1


def test_wurzel_selbst_laesst_sich_nicht_loeschen(ablage):
    with pytest.raises(Fehler):
        ablage.loeschen("")
    with pytest.raises(Fehler):
        ablage.loeschen(".")


# ── Suchen ─────────────────────────────────────────────────────────────────────


def test_suche_nach_name_und_inhalt(ablage):
    ablage.schreiben("Rechnungen/strom-2026.txt", "Betrag 42 Euro".encode())
    ablage.schreiben("Notizen/idee.md", "Heute: Stromanbieter vergleichen\nzweite Zeile".encode())
    ablage.schreiben("bild.png", b"\x89PNG\x00")
    r = ablage.suchen("strom")
    arten = {t["pfad"]: t["treffer"] for t in r["treffer"]}
    assert arten == {"Rechnungen/strom-2026.txt": "name", "Notizen/idee.md": "inhalt"}
    inhalt = next(t for t in r["treffer"] if t["treffer"] == "inhalt")
    assert inhalt["zeile"] == 1 and "Stromanbieter" in inhalt["auszug"]
    assert [t["pfad"] for t in ablage.suchen("strom", inhalt=False)["treffer"]] == ["Rechnungen/strom-2026.txt"]
    assert ablage.suchen("STROM 42")["treffer"][0]["pfad"] == "Rechnungen/strom-2026.txt"


def test_suche_in_einem_unterordner_und_grenzen(ablage):
    ablage.schreiben("a/x.txt", b"banane")
    ablage.schreiben("b/y.txt", b"banane")
    assert [t["pfad"] for t in ablage.suchen("banane", "a")["treffer"]] == ["a/x.txt"]
    with pytest.raises(Fehler, match="kurz"):
        ablage.suchen("a")
    with pytest.raises(Fehler):
        ablage.suchen("x" * 300)
    with pytest.raises(NichtGefunden):
        ablage.suchen("banane", "gibt/es/nicht")
    for i in range(5):
        ablage.schreiben(f"c/banane{i}.txt", b"1")
    r = ablage.suchen("banane", anzahl=2)
    assert len(r["treffer"]) == 2 and r["gekuerzt"]


# ── Quelle: Umgebung, Anmeldung ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_DATEIEN", "FYOS_DATEIEN_MAX_MB", "FYOS_DATEIEN_VERSIONEN", "FYOS_DATEIEN_PAPIERKORB_TAGE"):
        monkeypatch.delenv(name, raising=False)
    dateien.verzeichnis_anmelden(None)
    dateien._verzeichnisse.clear()
    yield
    dateien.verzeichnis_anmelden(None)
    dateien._verzeichnisse.clear()


def test_ohne_verzeichnis_ist_nichts_eingerichtet():
    with pytest.raises(NichtEingerichtet) as e:
        dateien.quelle()
    assert e.value.status == 501 and "FYOS_DATEIEN" in str(e.value)


def test_quelle_aus_der_umgebung_und_ihre_grenzen(monkeypatch, tmp_path):
    monkeypatch.setenv("FYOS_DATEIEN", str(tmp_path / "ablage"))
    monkeypatch.setenv("FYOS_DATEIEN_MAX_MB", "3")
    monkeypatch.setenv("FYOS_DATEIEN_VERSIONEN", "0")
    monkeypatch.setenv("FYOS_DATEIEN_PAPIERKORB_TAGE", "7")
    q = dateien.quelle()
    assert q.max_bytes == 3 * 1024 * 1024 and q.versionen_max == 0 and q.papierkorb_tage == 7
    assert q is dateien.quelle(), "dieselbe Ablage, damit die Sperre geteilt wird"
    assert (tmp_path / "ablage").is_dir()


def test_unsinnige_zahlen_fallen_auf_die_vorgabe(monkeypatch, tmp_path):
    monkeypatch.setenv("FYOS_DATEIEN", str(tmp_path))
    monkeypatch.setenv("FYOS_DATEIEN_MAX_MB", "viel")
    monkeypatch.setenv("FYOS_DATEIEN_VERSIONEN", "-4")
    q = dateien.quelle()
    assert q.max_bytes == dateien.VORGABE_MAX_MB * 1024 * 1024 and q.versionen_max == dateien.VORGABE_VERSIONEN


def test_angemeldetes_verzeichnis_geht_der_umgebung_vor(monkeypatch, tmp_path):
    monkeypatch.setenv("FYOS_DATEIEN", str(tmp_path / "env"))
    dateien.verzeichnis_anmelden(tmp_path / "config")
    assert dateien.quelle().wurzel == (tmp_path / "config").resolve()
    dateien.verzeichnis_anmelden(None)
    assert dateien.quelle().wurzel == (tmp_path / "env").resolve()


def test_zustand(ablage):
    z = ablage.zustand()
    assert z["beschreibbar"] and z["versionen"] == 3 and z["papierkorb_tage"] == 30 and z["max_mb"] >= 1
    assert isinstance(z["frei_mb"], int)


def test_zwischendateien_bleiben_nicht_liegen(ablage):
    ablage.schreiben("a.txt", b"1")
    tmp = ablage.wurzel / dateien.VERWALTUNG / "tmp"
    assert not any(tmp.iterdir())


def test_vorschau_nur_fuer_bilder_und_mit_deckel(ablage, monkeypatch):
    ablage.schreiben("b.png", b"\x89PNG....")
    ablage.schreiben("t.txt", b"text")
    r = ablage.vorschau("b.png")
    assert r["typ"] == "image/png" and r["daten_base64"] == "iVBORy4uLi4="
    with pytest.raises(Fehler, match="Bildvorschau"):
        ablage.vorschau("t.txt")
    monkeypatch.setattr(dateien, "VORSCHAU_MAX", 4)
    with pytest.raises(ZuGross):
        ablage.vorschau("b.png")


def test_platzmangel_bricht_vor_dem_schreiben_ab(ablage, monkeypatch):
    import shutil
    from collections import namedtuple

    Nutzung = namedtuple("Nutzung", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Nutzung(100, 100, 1))
    with pytest.raises(QuelleFehler, match="Platz"):
        ablage.schreiben("a.txt", b"1")
    assert not (ablage.wurzel / "a.txt").exists()


def test_unlesbare_datei_ist_ein_fehler_der_ablage(ablage):
    ablage.schreiben("a.txt", b"1")
    p = ablage.wurzel / "a.txt"
    p.chmod(0)
    try:
        if os.access(p, os.R_OK):
            pytest.skip("läuft als Benutzer, der alles lesen darf")
        with pytest.raises(QuelleFehler):
            ablage.lesen("a.txt")
    finally:
        p.chmod(0o644)
