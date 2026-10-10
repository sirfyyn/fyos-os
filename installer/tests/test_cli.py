import socket
import sys

import yaml

from fyos_installer import abnahme as abn
from fyos_installer import ausfuehren as ausf
from fyos_installer import cli


def test_trocken_schreibt_nichts(tmp_path, capsys):
    ziel = tmp_path / "fyos"
    rc = cli.main(["--auswahl", "kern,agent", "--ziel", "compose", "--verzeichnis", str(ziel), "--trocken"])
    assert rc == 0 and not ziel.exists()
    assert "docker-compose.yml" in capsys.readouterr().out


def test_unbekannter_baustein(tmp_path, capsys):
    assert cli.main(["--auswahl", "nix", "--verzeichnis", str(tmp_path), "--trocken"]) == 2
    assert "Unbekannter Baustein" in capsys.readouterr().err


def test_ohne_ja_ohne_terminal(tmp_path):
    assert cli.main(["--auswahl", "kern", "--verzeichnis", str(tmp_path / "x")]) == 2
    assert not (tmp_path / "x").exists()


def test_ja_dateien_mit_antworten(tmp_path):
    a = tmp_path / "a.yaml"
    a.write_text(yaml.safe_dump({"persona": {"agent_name": "Nova", "besitzer_name": "Sam"}}))
    ziel = tmp_path / "x"
    assert cli.main(["--auswahl", "kern,agent", "--ziel", "dateien", "--antworten", str(a), "--verzeichnis", str(ziel), "--ja"]) == 0
    assert "Nova" in (ziel / "fyos.yaml").read_text()


def test_compose_startet_gemockt(tmp_path, monkeypatch):
    aufrufe = []
    monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log, **k: aufrufe.append(plan) or ausf.Ergebnis(True, "ok", plan.url))
    assert cli.main(["--auswahl", "kern", "--ziel", "compose", "--verzeichnis", str(tmp_path / "x"), "--ja"]) == 0
    assert len(aufrufe) == 1
    monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log, **k: ausf.Ergebnis(False, "kaputt"))
    assert cli.main(["--auswahl", "kern", "--verzeichnis", str(tmp_path / "y"), "--ja"]) == 1


def test_liste(capsys):
    assert cli.main(["--liste", "--ohne-plugin-kataloge"]) == 0
    assert "finanzen" in capsys.readouterr().out


def test_tui_ohne_textual(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "fyos_installer.tui", None)
    assert cli.main(["--tui", "--ohne-plugin-kataloge"]) == 2
    assert 'pip install "fyos-installer[tui]"' in capsys.readouterr().err


def test_trocken_zeigt_reifegrad_und_abnahme(tmp_path, capsys):
    rc = cli.main(["--auswahl", "kern,agent,beispiel_app", "--ziel", "compose", "--verzeichnis", str(tmp_path / "x"),
                   "--trocken", "--ohne-plugin-kataloge"])
    out = capsys.readouterr().out
    assert rc == 0 and not (tmp_path / "x").exists()
    assert "Reifegrad (je Schicht Stufe 1 bis 3, aus der Auswahl abgeleitet):" in out
    assert "Gedächtnis: Stufe 1 von 3 (Persona)" in out
    assert "Agent: Stufe 2 von 3 (Werkzeuge)" in out
    assert "Oberfläche: Stufe 2 von 3 (Apps)" in out
    assert "Takte: Stufe 1 von 3 (Von Hand)" in out
    assert out.index("Zielordner") < out.index("Reifegrad") < out.index("Dateien:")
    assert "Hinweis: Abnahme: Nach dem Start stellt der Installer 3 verbotene Anfragen an die Shell" in out


def test_abnahme_allein(monkeypatch, capsys, abnahme_von):
    adressen = []
    monkeypatch.setattr(abn, "pruefen", lambda adresse: adressen.append(adresse) or abnahme_von(True))
    assert cli.main(["--abnahme", "http://localhost:8080"]) == 0
    assert "Abnahme bestanden" in capsys.readouterr().out and adressen == ["http://localhost:8080"]
    monkeypatch.setattr(abn, "pruefen", lambda adresse: abnahme_von(False))
    assert cli.main(["--abnahme", "http://localhost:8080"]) == 3
    out = capsys.readouterr().out
    assert "Abnahme NICHT bestanden" in out and "NICHT abgelehnt (Antwort 200)" in out and "Prüfen:" in out


def test_abnahme_falsche_adresse(capsys):
    assert cli.main(["--abnahme", "localhost:8080"]) == 2
    assert "keine Adresse" in capsys.readouterr().err


def test_abnahme_braucht_weder_katalog_noch_dateien(monkeypatch, tmp_path, abnahme_von):
    monkeypatch.setattr(abn, "pruefen", lambda adresse: abnahme_von(True))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--abnahme", "http://localhost:8080", "--katalog", str(tmp_path / "gibt-es-nicht.yaml")]) == 0
    assert list(tmp_path.iterdir()) == []


def test_abnahme_ohne_laufende_installation(capsys):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nichts lauscht mehr
    assert cli.main(["--abnahme", f"http://127.0.0.1:{port}"]) == 3
    out = capsys.readouterr().out
    assert "Abnahme NICHT bestanden" in out and "keine Antwort" in out


def test_start_mit_abnahme_bestimmt_den_rueckgabewert(tmp_path, monkeypatch, abnahme_von):
    def lauf(name, ergebnis):
        monkeypatch.setattr(ausf, "ausfuehren", lambda plan, log, **k: ergebnis(plan))
        return cli.main(["--auswahl", "kern", "--ziel", "compose", "--verzeichnis", str(tmp_path / name), "--ja"])

    assert lauf("a", lambda p: ausf.Ergebnis(True, "ok", p.url, abnahme_von(True))) == 0
    assert lauf("b", lambda p: ausf.Ergebnis(True, "ok", p.url, abnahme_von(False))) == 3  # läuft, aber nicht abgenommen
    assert lauf("c", lambda p: ausf.Ergebnis(True, "ok", p.url, None)) == 0  # Abnahme nicht gelaufen: der Start zählt
    assert lauf("d", lambda p: ausf.Ergebnis(False, "kaputt")) == 1


class _Docker:
    """Ein `docker`, das alles gelingen lässt: für den Ablauf in `ausfuehren`."""

    def __init__(self):
        self.aufrufe = []

    def __call__(self, argv, **k):
        self.aufrufe.append(argv)
        return self

    stdout = ["zeile\n"]

    def wait(self):
        return 0


def _gesund(plan, log, **k):
    return ausf.ausfuehren(plan, log.append, docker=lambda: (True, "bereit"), popen=_Docker(),
                           pruefer=lambda: {"web": True, "hub": True}, schlaf=lambda s: None, **k)


def test_ausfuehren_ablauf(katalog, tmp_path, abnahme_von):
    from fyos_installer import erzeugen as e

    plan = e.erstelle_plan(katalog, [], "compose", {}, tmp_path)
    log = []
    docker = _Docker()
    abnahmen = []

    def abnahme(adresse):
        abnahmen.append(adresse)
        return abnahme_von(True)

    zustand = iter([{"web": False, "hub": True}, {"web": True, "hub": True}])
    erg = ausf.ausfuehren(plan, log.append, docker=lambda: (True, "bereit"), popen=docker,
                          pruefer=lambda: next(zustand), schlaf=lambda s: None, abnahme=abnahme)
    assert erg.ok and erg.url == plan.url
    assert docker.aufrufe == [["docker", "compose", "build"], ["docker", "compose", "up", "-d"]]
    assert abnahmen == ["http://127.0.0.1:8080"]  # nach der Gesundheitsprüfung, gegen den Port des Plans
    erg = ausf.ausfuehren(plan, log.append, docker=lambda: (False, "Docker fehlt"), popen=docker, abnahme=abnahme)
    assert not erg.ok and erg.meldung == "Docker fehlt" and erg.abnahme is None
    zeit = iter(range(0, 1000, 100))
    erg = ausf.ausfuehren(plan, log.append, docker=lambda: (True, ""), popen=docker, zeitlimit=150, abnahme=abnahme,
                          pruefer=lambda: {"web": True, "hub": False}, schlaf=lambda s: None, uhr=lambda: next(zeit))
    assert not erg.ok and "hub" in erg.meldung and erg.abnahme is None
    assert abnahmen == ["http://127.0.0.1:8080"]  # ohne laufendes FYOS wird nichts abgenommen


def test_abnahme_bestanden_steht_im_ergebnis_und_im_protokoll(katalog, tmp_path, abnahme_von):
    from fyos_installer import erzeugen as e

    plan = e.erstelle_plan(katalog, [], "compose", {}, tmp_path)
    log = []
    erg = _gesund(plan, log, abnahme=lambda adresse: abnahme_von(True))
    assert erg.ok and erg.abnahme.bestanden and not erg.nicht_abgenommen
    assert erg.meldung == "FYOS läuft: http://localhost:8080. Abnahme bestanden: alle 3 verbotenen Anfragen wurden abgelehnt."
    assert "== Abnahme: verbotene Anfragen an http://127.0.0.1:8080 müssen abgelehnt werden" in log
    assert log.index("FYOS läuft: http://localhost:8080") < log.index("Abnahme bestanden: alle 3 verbotenen Anfragen wurden abgelehnt.")


def test_abnahme_nicht_bestanden_laesst_den_start_gelten(katalog, tmp_path, abnahme_von):
    from fyos_installer import erzeugen as e

    plan = e.erstelle_plan(katalog, [], "compose", {"felder": {"kern": {"port": 9000}}}, tmp_path)
    log = []
    gesehen = []
    erg = _gesund(plan, log, abnahme=lambda adresse: gesehen.append(adresse) or abnahme_von(False))
    assert gesehen == ["http://127.0.0.1:9000"]
    assert erg.ok and erg.url == "http://localhost:9000" and erg.nicht_abgenommen
    assert "Abnahme NICHT bestanden: 2 von 3 verbotenen Anfragen wurden abgelehnt." in erg.meldung
    assert any(z.startswith("  - Voller Aufruf-Endpunkt") for z in log)


def test_abnahme_die_scheitert_kippt_den_start_nicht(katalog, tmp_path):
    from fyos_installer import erzeugen as e

    plan = e.erstelle_plan(katalog, [], "compose", {}, tmp_path)
    log = []

    def kaputt(adresse):
        raise RuntimeError("boom")

    erg = _gesund(plan, log, abnahme=kaputt)
    assert erg.ok and erg.abnahme is None and not erg.nicht_abgenommen
    assert erg.meldung == "FYOS läuft: http://localhost:8080"
    assert "Die Abnahme konnte nicht laufen: boom" in log


def test_ergebnis_nicht_abgenommen_nur_bei_laufendem_fyos(abnahme_von):
    nein = abnahme_von(False)
    assert ausf.Ergebnis(True, "ok", None, nein).nicht_abgenommen
    assert not ausf.Ergebnis(False, "kaputt", None, nein).nicht_abgenommen
    assert not ausf.Ergebnis(True, "ok", None, abnahme_von(True)).nicht_abgenommen
    assert not ausf.Ergebnis(True, "ok").nicht_abgenommen


def test_docker_pruefen():
    nein = ausf.docker_pruefen(which=lambda n: None)
    assert not nein[0] and "Docker" in nein[1]
