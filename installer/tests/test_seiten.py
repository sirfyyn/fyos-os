import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fyos_installer import erzeugen, web

TESTS = Path(__file__).resolve().parent
APP = Path(web.__file__).resolve().parent / "web" / "app.js"


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
def test_seiten_rendern(katalog, tmp_path, abnahme_von):
    z = web.Zustand(katalog, docker=lambda: (True, "bereit"), umgebung={})
    datei = tmp_path / "katalog.json"
    datei.write_text(json.dumps(z.katalog_json()))
    # Echte Antworten des Servers (Plan mit Reifegrad, Abnahme bestanden und durchgefallen), damit die Seiten gegen die
    # Formen gerendert werden, die der Server wirklich schickt.
    plan = erzeugen.erstelle_plan(katalog, ["beispiel_app"], "compose", {}, tmp_path / "ziel")
    assert plan.ok, plan.fehler
    # Ein Plan mit Stufen je Fähigkeit: Kubernetes nimmt den Ausbau vor, Termine sind auf die Grundstufe umgestellt.
    mit_stufen = erzeugen.erstelle_plan(
        katalog, ["kalender", "leitstand", "post"], "k8s",
        {"stufen": {"termine": "grund"}, "optionen": {"paketindex": "https://pypi.example.com/simple"},
         "felder": {"leitstand": {"vorgaenge_url": "http://vorgaenge.example.com"}}},
        tmp_path / "ziel2", umgebung={},
    )
    assert mit_stufen.ok, mit_stufen.fehler
    beispiele = tmp_path / "beispiele.json"
    beispiele.write_text(json.dumps({
        "plan": plan.als_dict(),
        "plan_stufen": mit_stufen.als_dict(),
        "abnahme_ok": abnahme_von(True).als_dict(),
        "abnahme_nein": abnahme_von(False).als_dict(),
    }))
    r = subprocess.run(
        ["node", str(TESTS / "seiten_test.mjs"), str(APP), str(datei), str(beispiele)],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr + r.stdout
