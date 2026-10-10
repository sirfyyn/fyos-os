import asyncio

import pytest

pytest.importorskip("textual")

from fyos_installer import ausfuehren as ausf  # noqa: E402
from fyos_installer import erzeugen, reife, tui  # noqa: E402


def test_tui_durchlauf(katalog, tmp_path, monkeypatch):
    monkeypatch.setattr(ausf, "docker_pruefen", lambda *a, **k: (True, "bereit"))

    async def lauf():
        app = tui.InstallerApp(katalog, tmp_path / "t")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("n", "n")  # Willkommen -> Ziel -> Bausteine
            assert app.schritt == 2
            liste = app.query_one("#liste")
            liste.select("finanzen")
            await pilot.pause()
            assert {"kern", "agent", "finanzen"} <= set(app.gewaehlt())
            await pilot.press("n")
            assert app.schritt == 3
            app.query_one("#in-optionen-paketindex").value = "https://git.example.com/api/packages/org/pypi/simple"
            await app.action_weiter()
            assert app.schritt == 4 and app.plan and app.plan.ok
            await app.action_weiter()
            assert app.schritt == 5

    asyncio.run(lauf())


def test_tui_zusammenfassung_zeigt_den_reifegrad(katalog, tmp_path):
    plan = erzeugen.erstelle_plan(katalog, ["beispiel_app"], "compose", {}, tmp_path / "o")
    assert plan.ok, plan.fehler
    text = tui.InstallerApp(katalog, tmp_path / "t")._zusammenfassung(plan)
    assert text.index("### Reifegrad") < text.index("### Dateien")
    assert "- **Gedächtnis**: Stufe 1 von 3 (Persona). Erkennbar: " + reife.LEITER["gedaechtnis"][0].erkennbar in text
    assert "- **Agent**: Stufe 2 von 3 (Werkzeuge). Erkennbar: " + reife.LEITER["agent"][1].erkennbar in text
    assert "  Nächste Stufe: " + reife.LEITER["agent"][2].erkennbar in text
    assert text.count("Nächste Stufe:") == 4
    assert any(z.startswith("- Abnahme: Nach dem Start stellt der Installer 3 verbotene Anfragen") for z in text.splitlines())
    # ohne Reifegrad (leerer Plan) bleibt die Zusammenfassung wie früher
    plan.reife = []
    assert "Reifegrad" not in tui.InstallerApp(katalog, tmp_path / "t")._zusammenfassung(plan)


def test_tui_abschlusszeile(abnahme_von):
    assert tui.abschlusszeile(ausf.Ergebnis(False, "Docker fehlt")) == "FEHLER: Docker fehlt"
    assert tui.abschlusszeile(ausf.Ergebnis(True, "FYOS läuft", None, abnahme_von(True))) == "FERTIG: FYOS läuft"
    assert tui.abschlusszeile(ausf.Ergebnis(True, "FYOS läuft")) == "FERTIG: FYOS läuft"
    zeile = tui.abschlusszeile(ausf.Ergebnis(True, "FYOS läuft", None, abnahme_von(False)))
    assert zeile == "GESTARTET, ABER NICHT ABGENOMMEN: FYOS läuft"
