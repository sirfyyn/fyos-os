"""Skills-Plugin: Katalog aus mehreren Quellen, Suche (alle Wörter / Teiltreffer), Lesen, Grenzen."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hub.plugins.skills import SkillsPlugin, front_matter


def _skill(quelle: Path, ordner: str, kopf: str, rumpf: str = "", refs: dict[str, str] | None = None) -> None:
    d = quelle / ordner
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{kopf}\n---\n\n{rumpf}\n", encoding="utf-8")
    for name, text in (refs or {}).items():
        (d / "references").mkdir(exist_ok=True)
        (d / "references" / name).write_text(text, encoding="utf-8")


@pytest.fixture
def plugin(tmp_path: Path) -> SkillsPlugin:
    eigene = tmp_path / "eigene"
    fremde = tmp_path / "fremde"
    _skill(
        eigene,
        "server",
        "name: server\ndescription: Arbeit am Server, Lagebild zuerst.\nwerkstatt: [ops/server/status]\nfuer: [agent, claude]",
        "Warten per Monitor mit until-Schleife.",
        {"fallen.md": "pkill -f trifft die eigene Shell."},
    )
    _skill(eigene, "rollout", "name: rollout\ndescription: Ausrollen und prüfen.", "Abgleich abwarten.")
    _skill(fremde, "tdd", "name: tdd\ndescription: Test first.", "Red, green, refactor.")
    # gleicher Name wie in der ersten Quelle: die erste hat Vorrang
    _skill(fremde, "server", "name: server\ndescription: fremd.", "")
    (fremde / "leer").mkdir(parents=True)
    # Ohne die Skills installierter Pakete (z. B. generative-ui aus dem Kern): hier zählen nur die beiden Quellen
    return SkillsPlugin({"quellen": [str(eigene), str(fremde)], "scan_ttl_s": 0, "plugin_skills": False})


def test_front_matter_ohne_kopf():
    assert front_matter("# nur Text") == ({}, "# nur Text")


def test_verzeichnis_ohne_q(plugin: SkillsPlugin):
    r = plugin.call("suchen", {})
    assert r["art"] == "verzeichnis"
    assert [s["name"] for s in r["skills"]] == ["rollout", "server", "tdd"]
    server = r["skills"][1]
    assert server["quelle"] == "eigene" and server["werkstatt"] == ["ops/server/status"]
    assert plugin.health()["skills"] == 3


def test_suche_alle_woerter_im_rumpf(plugin: SkillsPlugin):
    r = plugin.call("suchen", {"q": "server monitor"})
    assert r["art"] == "alle_woerter"
    assert [s["name"] for s in r["skills"]] == ["server"]


def test_suche_teiltreffer_und_quelle(plugin: SkillsPlugin):
    r = plugin.call("suchen", {"q": "abgleich zauberei"})
    assert r["art"] == "teiltreffer" and r["skills"][0]["name"] == "rollout"
    assert plugin.call("suchen", {"q": "test", "quelle": "eigene"})["anzahl"] == 0
    assert plugin.call("suchen", {"q": "nichtda"})["anzahl"] == 0


def test_lesen_und_referenz(plugin: SkillsPlugin):
    r = plugin.call("lesen", {"name": "server"})
    assert "until-Schleife" in r["text"] and r["dateien"] == ["fallen.md"]
    assert r["fuer"] == ["agent", "claude"] and r["quelle"] == "eigene"
    f = plugin.call("lesen", {"name": "server", "datei": "fallen.md"})
    assert "pkill" in f["text"]


def test_quellen_aus_der_umgebung(tmp_path: Path, monkeypatch):
    _skill(tmp_path / "q", "a", "name: a\ndescription: x.", "")
    monkeypatch.setenv("FYOS_SKILLS_PATH", str(tmp_path / "q"))
    assert SkillsPlugin({"plugin_skills": False}).health()["skills"] == 1


def test_lesen_grenzen(plugin: SkillsPlugin):
    with pytest.raises(ValueError):
        plugin.call("lesen", {"name": "gibtsnicht"})
    with pytest.raises(ValueError):
        plugin.call("lesen", {"name": "server", "datei": "../../../etc/passwd"})
    with pytest.raises(ValueError):
        plugin.call("unbekannt", {})


def test_skills_aus_plugin_paketen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ein installiertes Plugin bringt seine Skills über die Entry-Point-Gruppe `fyos.skills` mit."""
    import sys
    from importlib import metadata

    paket = tmp_path / "pakete" / "fyos_plugin_wetter"
    paket.mkdir(parents=True)
    (paket / "__init__.py").write_text("", encoding="utf-8")
    _skill(paket / "skills", "wetter", "name: wetter\ndescription: Wetterlage holen.", "")
    _skill(paket / "skills", "rollout", "name: rollout\ndescription: aus dem Plugin.", "")
    eigene = tmp_path / "eigene"
    _skill(eigene, "rollout", "name: rollout\ndescription: Ausrollen und prüfen.", "")
    monkeypatch.syspath_prepend(str(tmp_path / "pakete"))
    sys.modules.pop("fyos_plugin_wetter", None)

    ep = metadata.EntryPoint(name="wetter", value="fyos_plugin_wetter", group="fyos.skills")
    echt = metadata.entry_points

    def entry_points(**kw):
        return metadata.EntryPoints([ep]) if kw.get("group") == "fyos.skills" else echt(**kw)

    monkeypatch.setattr(metadata, "entry_points", entry_points)

    r = SkillsPlugin({"quellen": [str(eigene)], "scan_ttl_s": 0}).call("suchen", {})
    nach_name = {s["name"]: s for s in r["skills"]}
    assert nach_name["wetter"]["quelle"] == "wetter"
    assert nach_name["rollout"]["quelle"] == "eigene"  # konfigurierte Quelle hat Vorrang

    aus = SkillsPlugin({"quellen": [str(eigene)], "scan_ttl_s": 0, "plugin_skills": False}).call("suchen", {})
    assert [s["name"] for s in aus["skills"]] == ["rollout"]
