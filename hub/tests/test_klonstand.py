"""Stand des Repo-Klons: Commit und Datum, Zwischenspeicher, Fehler ergeben None; skills und werkstatt nennen ihn."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mcp_hub.plugins import _klonstand
from mcp_hub.plugins.skills import SkillsPlugin
from mcp_hub.plugins.werkstatt import WerkstattPlugin


@pytest.fixture(autouse=True)
def _frisch():
    _klonstand.vergessen()
    yield
    _klonstand.vergessen()


def _git(repo: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   check=True, capture_output=True)


def _skill(repo: Path, name: str) -> None:
    d = repo / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}.\n---\n\nText.\n", encoding="utf-8")


def test_stand_commit_und_datum(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    _skill(tmp_path, "eins")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "eins")
    s = _klonstand.stand(tmp_path)
    assert s is not None and set(s) == {"commit", "datum"} and len(s["commit"]) >= 7
    assert "T" in s["datum"]
    assert _klonstand.commit(tmp_path) == s["commit"]


def test_ohne_git_oder_ohne_verzeichnis_none(tmp_path: Path):
    assert _klonstand.stand(tmp_path) is None
    assert _klonstand.stand(tmp_path / "fehlt") is None
    assert _klonstand.commit(tmp_path / "fehlt") is None


def test_zwischenspeicher_und_frist_aus_umgebung(tmp_path: Path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _skill(tmp_path, "eins")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "eins")
    alt = _klonstand.commit(tmp_path)
    _skill(tmp_path, "zwei")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "zwei")
    assert _klonstand.commit(tmp_path) == alt  # noch im Zwischenspeicher
    monkeypatch.setenv("FYOS_KLONSTAND_TTL_S", "0")
    assert _klonstand.commit(tmp_path) != alt


def test_frist_unsinn_faellt_auf_vorgabe(monkeypatch):
    monkeypatch.setenv("FYOS_KLONSTAND_TTL_S", "viel")
    assert _klonstand._frist() == _klonstand.CACHE_S


def test_skills_katalog_folgt_dem_commit(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FYOS_KLONSTAND_TTL_S", "0")
    _git(tmp_path, "init", "-q")
    _skill(tmp_path, "eins")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "eins")
    p = SkillsPlugin({"quellen": [str(tmp_path / "skills")], "scan_ttl_s": 3600, "plugin_skills": False,
                      "beitraege": False})  # Frist hoch: nur der Commit darf erneuern
    r = p.call("suchen", {})
    assert set(r["stand"]) == {"commit", "datum"}
    assert p.call("lesen", {"name": "eins"})["stand"] == r["stand"]
    _skill(tmp_path, "zwei")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "zwei")
    r2 = p.call("suchen", {})
    assert r2["stand"]["commit"] != r["stand"]["commit"]
    assert {s["name"] for s in r2["skills"]} == {"eins", "zwei"}


def test_skills_ohne_git_stand_null(tmp_path: Path):
    _skill(tmp_path, "eins")
    p = SkillsPlugin({"quellen": [str(tmp_path / "skills")], "scan_ttl_s": 0, "plugin_skills": False,
                      "beitraege": False})
    assert p.call("suchen", {})["stand"] is None
    assert p.call("lesen", {"name": "eins"})["stand"] is None


def test_werkstatt_suchen_nennt_stand(tmp_path: Path):
    (tmp_path / "scripts" / "ops").mkdir(parents=True)
    p = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0})
    assert p.call("suchen", {"q": ""})["stand"] is None
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "leer")
    _klonstand.vergessen()
    assert set(p.call("suchen", {"q": ""})["stand"]) == {"commit", "datum"}
