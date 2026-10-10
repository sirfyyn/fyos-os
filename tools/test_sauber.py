"""sauber.py: Dateien und Git-Historie. Laeuft in der CI als Werkzeug-Test (pytest tools)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import sauber

WORT = "zaunkoenigweg"  # steht im Test-Repo auf der Verbotsliste, nicht in der echten


def _git(repo: Path, *args: str, name: str = "FYOS", mail: str = "fyos@noreply.invalid") -> None:
    umgebung = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail, "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": mail, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                "HOME": str(repo), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", *args], cwd=repo, env=umgebung, check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".sauber").mkdir()
    (tmp_path / ".sauber" / "verboten.sha256").write_text(sauber._h(WORT) + "\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def test_saubere_historie_hat_keine_befunde(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("hallo\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Anfang\n\nCo-Authored-By: Helfer <" + "noreply@" + "helfer.example.org>")
    assert sauber.historie_pruefen(repo) == []
    assert sauber.main(["--historie", str(repo)]) == 0


def test_rechnername_und_wort_in_der_historie_fallen_auf(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("hallo\n")
    _git(repo, "add", "-A")
    # Wie ein Commit ohne eingestellte Identitaet: Git nimmt Benutzer und Rechnernamen.
    _git(repo, "commit", "-q", "-m", f"Erster Stand\n\nnotiert auf {WORT}", name="Erika Muster",
         mail="erika@" + "rechner-von-erika.local")
    befunde = sauber.historie_pruefen(repo)
    assert any("Autor-Adresse ist kein Platzhalter" in b for b in befunde)
    assert any("Committer-Adresse ist kein Platzhalter" in b for b in befunde)
    assert any("Text Zeile 3: verbotenes Wort" in b for b in befunde)
    assert sauber.main(["--historie", str(repo)]) == 1
    # Die Dateien selbst sind sauber: nur die Historie verraet etwas.
    assert sauber.pruefen(repo) == []


def test_platzhalter_adressen_sind_erlaubt():
    for mail in ("fyos@noreply.invalid", "noreply@helfer.example.org", "a@example.com", "x@users.noreply.example"):
        assert sauber.EMAIL_ERLAUBT.search(mail), mail
    assert not sauber.EMAIL_ERLAUBT.search("erika@" + "rechner-von-erika.local")
