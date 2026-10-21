"""Konfiguration fuer eigene Installationen: skills `nur_sichtbar`, werkstatt `orte`/`im_hub`/`env_weg`/`favoriten_schluessel`."""

from __future__ import annotations

from pathlib import Path

from mcp_hub.plugins.skills import SkillsPlugin
from mcp_hub.plugins.werkstatt import WerkstattPlugin


def _skill(quelle: Path, name: str) -> None:
    d = quelle / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name}.\n---\n\nText.\n", encoding="utf-8")


def test_skills_nur_sichtbar_blendet_aus_bleibt_lesbar(tmp_path: Path):
    eigen, fremd = tmp_path / "eigen", tmp_path / "fremd"
    _skill(eigen, "arbeitsrechner")
    _skill(fremd, "tdd")
    _skill(fremd, "qa")
    cfg = {"quellen": [{"pfad": str(eigen), "name": "fyos"}, {"pfad": str(fremd), "name": "allgemein"}],
           "scan_ttl_s": 0, "plugin_skills": False, "beitraege": False}
    p = SkillsPlugin({**cfg, "nur_sichtbar": {"allgemein": ["tdd"]}})
    assert [s["name"] for s in p.call("suchen", {})["skills"]] == ["arbeitsrechner", "tdd"]
    assert p.call("suchen", {"q": "qa"})["anzahl"] == 0
    r = p.call("lesen", {"name": "qa"})
    assert r["ausgeblendet"] is True and "Text" in r["text"]
    # ohne Einstellung ist alles sichtbar
    alle = SkillsPlugin(cfg)
    assert {s["name"] for s in alle.call("suchen", {})["skills"]} == {"arbeitsrechner", "tdd", "qa"}


def _skript(repo: Path, ort: str) -> None:
    d = repo / "scripts" / "ops"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hallo.py").write_text(
        "#!/usr/bin/env python3\n"
        f"WERKSTATT = {{'titel': 'Hallo', 'zweck': 'Sagt hallo', 'ort': '{ort}', 'wirkung': 'lesen'}}\n"
        "print('hallo')\n",
        encoding="utf-8",
    )


def test_werkstatt_eigene_orte(tmp_path: Path):
    _skript(tmp_path, "cluster")
    kern = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0})
    assert kern.beschreiben("ops/hallo")["fehler"]  # "cluster" kennt der Kern nicht
    eigen = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0,
                                    "orte": ["cluster", "arbeitsrechner", "egal"], "im_hub": ["cluster", "egal"]})
    b = eigen.beschreiben("ops/hallo")
    assert not b["fehler"] and b["im_hub"] is True
    r = eigen.call("ausfuehren", {"id": "ops/hallo"})
    assert r["ausgefuehrt"] is True and "hallo" in r["stdout"]


def test_werkstatt_ort_ausserhalb_nicht_im_hub(tmp_path: Path):
    _skript(tmp_path, "arbeitsrechner")
    p = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0,
                                "orte": ["cluster", "arbeitsrechner", "egal"], "im_hub": ["cluster", "egal"]})
    assert p.beschreiben("ops/hallo")["im_hub"] is False
    assert p.call("ausfuehren", {"id": "ops/hallo"})["ausgefuehrt"] is False


def test_werkstatt_env_weg_und_favoriten_schluessel(tmp_path: Path, monkeypatch):
    d = tmp_path / "scripts" / "ops"
    d.mkdir(parents=True)
    (d / "umgebung.py").write_text(
        "#!/usr/bin/env python3\n"
        "WERKSTATT = {'titel': 'U', 'zweck': 'zeigt Umgebung', 'ort': 'hub', 'wirkung': 'lesen'}\n"
        "import os\nprint('da' if os.getenv('GEHEIM_TEST') else 'weg')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEHEIM_TEST", "x")
    offen = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0})
    assert offen.call("ausfuehren", {"id": "ops/umgebung"})["stdout"].strip() == "da"
    zu = WerkstattPlugin(config={"repo": str(tmp_path), "scan_ttl_s": 0, "env_weg": ["GEHEIM_"],
                                 "favoriten_schluessel": "test:favoriten"})
    assert zu.call("ausfuehren", {"id": "ops/umgebung"})["stdout"].strip() == "weg"
    assert zu._k_favoriten == "test:favoriten"
