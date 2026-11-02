"""Sprache des Installers: Englisch als Vorgabe, Deutsch mit --sprache de; die Wahl wird zur Sprache der Oberfläche."""

import json

from fyos_installer import cli, erzeugen
from fyos_installer import sprache as spr


def test_englisch_ist_vorgabe():
    spr.setze(None)
    assert spr.aktiv() == "en"
    assert spr._("Abgebrochen.") == "Cancelled."
    assert spr._("Ziel: {0}", "x") == "Target: x"
    assert spr.normalisiere("Deutsch") == "de" and spr.normalisiere("fr") is None


def test_platzhalter_bleiben_erhalten():
    import re

    platz = lambda s: sorted(re.findall(r"\{(\w*)\}", s))  # noqa: E731
    for k, v in spr.EN.items():
        assert platz(k) == platz(v), k


def test_cli_trocken_englisch_und_deutsch(capsys, tmp_path):
    spr.setze(spr.VORGABE)  # wie ein frischer Aufruf ohne --sprache
    assert cli.main(["--auswahl", "kern,agent", "--ziel", "compose", "--verzeichnis", str(tmp_path / "f"), "--trocken"]) == 0
    aus = capsys.readouterr().out
    assert "Target: Docker Compose on this computer" in aus and "Dry run: nothing was written or started." in aus
    assert cli.main(["--sprache", "de", "--auswahl", "kern,agent", "--ziel", "compose", "--verzeichnis", str(tmp_path / "g"), "--trocken"]) == 0
    aus = capsys.readouterr().out
    assert "Ziel: Docker Compose auf diesem Rechner" in aus and "Trocken: nichts wurde geschrieben" in aus


def _datei(plan, pfad):
    return next(d for d in plan.dateien if d.pfad == pfad)


def test_gewaehlte_sprache_wird_sprache_der_oberflaeche(katalog, tmp_path):
    spr.setze("en")
    plan = erzeugen.erstelle_plan(katalog, ["kern", "agent"], "compose", {}, tmp_path / "en")
    assert plan.ok and plan.sprache == "en"
    assert json.loads(_datei(plan, "fyos.config.json").inhalt)["sprache"] == "en"
    assert "Next steps" in _datei(plan, "ANLEITUNG.md").inhalt
    assert "./fyos.config.json:/etc/fyos/fyos.config.json:ro" in _datei(plan, "docker-compose.yml").inhalt

    plan = erzeugen.erstelle_plan(katalog, ["kern", "agent"], "compose", {"sprache": "de"}, tmp_path / "de")
    assert json.loads(_datei(plan, "fyos.config.json").inhalt)["sprache"] == "de"
    assert "Nächste Schritte" in _datei(plan, "ANLEITUNG.md").inhalt
    # Der Plan spricht die Sprache der Oberfläche, auch wenn der Installer eine andere spricht
    assert any("docker compose build" in z and "baut" in z for z in _datei(plan, "ANLEITUNG.md").inhalt.splitlines())
    assert spr.aktiv() == "en"


def test_kubernetes_bekommt_die_sprache_als_configmap(katalog, tmp_path):
    spr.setze("en")
    plan = erzeugen.erstelle_plan(
        katalog, ["kern", "agent"], "k8s", {"sprache": "de"}, tmp_path / "k8s", umgebung={},
    )
    assert plan.ok, plan.fehler
    assert json.loads(_datei(plan, "fyos.config.json").inhalt)["sprache"] == "de"
    kust = _datei(plan, "kustomization.yaml").inhalt
    assert "name: fyos-web-config" in kust and "- fyos.config.json" in kust
    assert "mountPath: /etc/fyos/fyos.config.json" in kust and "subPath: fyos.config.json" in kust


def test_name_des_agenten_steht_in_der_oberflaeche(katalog, tmp_path):
    """Die Oberfläche zeigt den Namen aus der Persona, nicht die Kennung des Runners (agent-runner.json: "main")."""
    spr.setze("en")
    plan = erzeugen.erstelle_plan(katalog, ["kern", "agent"], "compose", {}, tmp_path / "vorgabe")
    assert plan.ok, plan.fehler
    assert json.loads(_datei(plan, "fyos.config.json").inhalt) == {"sprache": "en", "agent": {"name": "Fy"}}
    assert json.loads(_datei(plan, "agent-runner.json").inhalt)["agent"] == "main"

    for ziel in ("compose", "k8s"):
        plan = erzeugen.erstelle_plan(
            katalog, ["kern", "agent"], ziel, {"persona": {"agent_name": " Jörn "}}, tmp_path / ziel, umgebung={},
        )
        assert plan.ok, plan.fehler
        inhalt = _datei(plan, "fyos.config.json").inhalt
        assert json.loads(inhalt)["agent"] == {"name": "Jörn"}
        assert "Jörn" in inhalt  # lesbar, nicht als \\u-Folge


def test_katalog_englisch_aus_dem_block_en(katalog, tmp_path):
    spr.setze("en")
    assert spr.katalog_text(katalog["kern"].titel) == "FYOS interface and Hub"
    assert spr.katalog_text(katalog["kalender"].konfiguration[0].titel) == "Calendar address"
    # jeder Text des eigenen Katalogs und der Stufen hat eine englische Fassung
    texte = [x for b in katalog for x in (b.titel, b.kurz, b.was_daraus_wird, *b.voraussetzungen)]
    texte += [x for b in katalog for f in b.konfiguration for x in (f.titel, f.beschreibung) if x]
    texte += [x for f in katalog.faehigkeiten.values() for x in (f.titel, f.kurz, *(t for s in f.stufen.values() for t in (s.titel, s.text)))]
    assert [t for t in texte if t.strip() not in spr.KATALOG_EN] == []
    plan = erzeugen.erstelle_plan(katalog, ["kern", "agent", "kalender"], "compose",
                                  {"optionen": {"paketindex": "https://pypi.example.com/simple"}}, tmp_path / "p")
    assert plan.ok, plan.fehler
    w = next(w for w in plan.stufen if w.faehigkeit.id == "termine")
    assert w.zeile() == "Appointments: basic tier (default), CalDAV and ICS directly"
    assert any(r["titel"] == "Memory" for r in plan.als_dict()["reife"])
    spr.setze("de")
    assert spr.katalog_text(katalog["kern"].titel) == "FYOS-Oberfläche und Hub"


def test_web_assistent_wechselt_die_sprache(katalog):
    from fyos_installer import web

    spr.setze("en")
    z = web.Zustand(katalog, docker=lambda: (True, "ready"), umgebung={})
    k = z.katalog_json()
    assert k["sprache"] == "en" and k["sprachen"] == ["en", "de"]
    assert k["bausteine"][0]["titel"] == "FYOS interface and Hub"
    assert k["vorgaben"]["persona"]["sprache"] == "English"
    assert k["vorgaben"]["persona"]["wesen"] == "Calm, precise and attentive"
    assert k["ziele"]["compose"] == "Docker Compose on this computer"
    spr.setze("de")
    k = z.katalog_json()
    assert k["sprache"] == "de" and k["bausteine"][0]["titel"] == "FYOS-Oberfläche und Hub"
    assert k["vorgaben"]["persona"]["sprache"] == "Deutsch"
    assert k["vorgaben"]["persona"]["wesen"] == "Ruhig, präzise und zugewandt"


def test_skizzen_sind_englisch():
    """Die Skizzen der Bausteine (bilder/*.svg) sind englisch; vorher stand auch im englischen Installer Deutsch."""
    import re
    from pathlib import Path

    deutsch = re.compile(r"[äöüÄÖÜß]|\b(Skizze|Heute|Zentrale|Notizen|Freigeben|Ablehnen|und|nur)\b")
    for p in (Path(erzeugen.__file__).parent / "bilder").glob("*.svg"):
        texte = re.findall(r">([^<>]+)</(?:text|tspan)>", p.read_text())
        assert not [t for t in texte if deutsch.search(t)], p.name
