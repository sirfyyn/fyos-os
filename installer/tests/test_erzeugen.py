import shutil
import subprocess

import pytest
import yaml

from fyos_installer import erzeugen as e

QUELLE = {"optionen": {"plugin_quelle": "https://git.example.com/fyos"}}
HAUS = {"felder": {"haus": {"ha_url": "http://ha.example.com:8123", "ha_token": "geheim$wert"}}}


def _plan(katalog, auswahl, ziel, tmp_path, **antworten):
    return e.erstelle_plan(katalog, auswahl, ziel, antworten, tmp_path / "out", zufall=lambda n: "ab" * n)


def _keine_reste(plan):
    for d in plan.dateien:
        assert "{{" not in d.inhalt, d.pfad


def test_compose(katalog, tmp_path):
    plan = _plan(katalog, ["haus"], "compose", tmp_path, **QUELLE, **HAUS)
    assert plan.ok, plan.fehler
    e.schreiben(plan)
    out = tmp_path / "out"
    for n in ["docker-compose.yml", ".env", "fyos.yaml", "hub-config.yaml", "hub/Dockerfile", "ANLEITUNG.md", ".gitignore"]:
        assert (out / n).is_file(), n
    _keine_reste(plan)
    assert (out / ".env").stat().st_mode & 0o777 == 0o600
    env = (out / ".env").read_text()
    assert "FYOS_AGENT_TOKEN=" + "ab" * 24 in env and "FYOS_HAUS_HA_TOKEN='geheim$wert'" in env
    compose = yaml.safe_load((out / "docker-compose.yml").read_text())
    assert compose["services"]["hub"]["build"]["context"] == "./hub"
    assert "FYOS_HAUS_HA_URL" in compose["services"]["hub"]["environment"]
    assert "geheim" not in (out / "docker-compose.yml").read_text()
    df = (out / "hub/Dockerfile").read_text()
    assert f"FROM {e.OFFIZIELLE_REGISTRY}/fyos-os/hub:{e.BILD_TAG}" in df
    assert "fyos-plugin-haus @ git+https://git.example.com/fyos/fyos-plugin-haus.git" in df
    fyos = yaml.safe_load((out / "fyos.yaml").read_text())
    assert fyos["agent"]["name"] == "Fy" and fyos["besitzer"]["name"] == "Alex" and fyos["sprache_code"] == "de"
    namen = {p["name"]: p for p in yaml.safe_load((out / "hub-config.yaml").read_text())["plugins"]}
    assert namen["audit"] and namen["echo"]["enabled"] is False
    assert "module" not in namen["audit"]
    assert namen["beispiel_app"]["enabled"] is False  # nicht gewählt: ausdrücklich aus
    assert plan.ausfuehrbar and plan.url == "http://localhost:8080"


def test_vorschau_ohne_geheimnisse(katalog, tmp_path):
    plan = _plan(katalog, ["haus"], "compose", tmp_path, **QUELLE, **HAUS)
    env = next(d for d in plan.dateien if d.pfad == ".env")
    assert env.geheim and "ab" * 24 not in env.vorschau() and "geheim$wert" not in env.vorschau()
    zeug = str(plan.als_dict())
    assert "ab" * 24 not in zeug and "geheim$wert" not in zeug


def test_ohne_plugin_quelle_fehler(katalog, tmp_path):
    plan = _plan(katalog, ["finanzen"], "compose", tmp_path)
    assert not plan.ok and any("FYOS_PAKETINDEX" in f for f in plan.fehler)  # Vorgabe ist der Paketindex
    assert not plan.dateien
    plan = _plan(katalog, ["finanzen", "haus"], "compose", tmp_path, optionen={"bezug": "git"})
    assert sum("FYOS_PLUGIN_QUELLE" in f for f in plan.fehler) == 1  # nur einmal gemeldet


INDEX = "https://git.example.com/api/packages/org/pypi/simple"


def test_paketindex(katalog, tmp_path):
    plan = _plan(katalog, ["haus"], "compose", tmp_path, optionen={"paketindex": INDEX}, felder=HAUS["felder"])
    assert plan.ok, plan.fehler
    assert plan.hub_quellen == ["fyos-plugin-haus"]
    e.schreiben(plan)
    out = tmp_path / "out"
    df = (out / "hub/Dockerfile").read_text()
    # uv statt pip; der eigene Index steht per --index vor PyPI, die Strategie first-index steht ausdrücklich im Befehl
    assert 'ARG FYOS_INDEX_URL=""' in df
    assert (
        'uv pip install --system --no-cache --index-strategy first-index '
        '${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} "fyos-plugin-haus"'
    ) in df
    assert f"COPY --from={e.UV_BILD} /uv /uvx /bin/" in df
    # nie die unsicheren Wege: kein pip, kein Zusatzindex mit Höchste-Version-gewinnt, kein altes Bau-Argument
    assert "--extra-index-url" not in df and "unsafe" not in df and "PIP_EXTRA_INDEX_URL" not in df
    assert "pip install" not in df.replace("uv pip install", "")
    assert "git+" not in df
    assert df.index("USER root") < df.index("COPY --from=") < df.index("uv pip install") < df.index("USER fyos")
    assert f"FYOS_PAKETINDEX={INDEX}" in (out / ".env").read_text()
    build = yaml.safe_load((out / "docker-compose.yml").read_text())["services"]["hub"]["build"]
    assert build == {"context": "./hub", "args": {"FYOS_INDEX_URL": "${FYOS_PAKETINDEX:-}"}}


def test_paketindex_aus_umgebung_und_k8s_befehl(katalog, tmp_path):
    plan = e.erstelle_plan(katalog, ["haus"], "k8s", {"felder": HAUS["felder"]}, tmp_path / "k",
                           umgebung={"FYOS_PAKETINDEX": INDEX})
    assert plan.ok, plan.fehler
    assert any(f"--build-arg FYOS_INDEX_URL={INDEX}" in b for b in plan.befehle)
    assert not any("PIP_EXTRA_INDEX_URL" in b for b in plan.befehle)


def test_git_bezug_bleibt_moeglich(katalog, tmp_path):
    plan = _plan(katalog, ["haus"], "compose", tmp_path, optionen={"bezug": "git", "plugin_quelle": "https://g.example.com/f"}, felder=HAUS["felder"])
    assert plan.ok and plan.hub_quellen == ["fyos-plugin-haus @ git+https://g.example.com/f/fyos-plugin-haus.git"]
    assert "FYOS_PAKETINDEX=\n" in next(d for d in plan.dateien if d.pfad == ".env").inhalt
    df = next(d for d in plan.dateien if d.pfad == "hub/Dockerfile").inhalt
    assert "apt-get install" in df
    # auch der Git-Bezug läuft über uv, mit derselben Strategie
    assert (
        'uv pip install --system --no-cache --index-strategy first-index '
        '${FYOS_INDEX_URL:+--index "$FYOS_INDEX_URL"} "fyos-plugin-haus @ git+https://g.example.com/f/fyos-plugin-haus.git"'
    ) in df
    assert "pip install" not in df.replace("uv pip install", "")


def test_ohne_plugin_pakete_kein_uv(katalog, tmp_path):
    plan = _plan(katalog, [], "compose", tmp_path)
    assert plan.ok, plan.fehler
    df = next(d for d in plan.dateien if d.pfad == "hub/Dockerfile").inhalt
    assert "Keine Plugin-Pakete gewählt" in df and "uv" not in df and "USER root" not in df


def test_uv_version_wie_im_hub_dockerfile():
    """Eine feste uv-Version für alle Bilder: das Hub-Dockerfile der Distribution und das erzeugte ziehen dasselbe."""
    hub = e.PAKET.parent.parent / "hub" / "Dockerfile"
    if not hub.is_file():
        pytest.skip("kein Checkout")
    assert f"COPY --from={e.UV_BILD} /uv /uvx /bin/" in hub.read_text(encoding="utf-8")


def test_ungueltiger_index(katalog, tmp_path):
    assert not _plan(katalog, [], "compose", tmp_path, optionen={"paketindex": "ftp://x"}).ok
    assert not _plan(katalog, [], "compose", tmp_path, optionen={"paketindex": "https://x/$(boese)"}).ok


def test_registry_vorgaben(katalog, tmp_path):
    o = e.vorgaben_optionen({"FYOS_REGISTRY": "registry.example.com/org/"})
    assert o["bild_web"] == "registry.example.com/org/fyos-os/web:main"
    assert o["hub_bild"] == "registry.example.com/org/fyos-os/hub:main"
    assert o["bild_agent"] == "registry.example.com/org/fyos-agent/openclaw:main"
    assert o["hub_bild_k8s"] == "registry.example.com/org/fyos-os/hub-eigen:main"
    # Ohne Registry die veröffentlichten Bilder im Stand der Installer-Version; nur hub-eigen braucht eine eigene.
    v = e.vorgaben_optionen({})
    assert e.BILD_TAG == f"v{e.__version__}"
    assert e.AGENT_TAG == "v0.1.1"  # fyos-agent trägt für 0.1.1 denselben Tag (RELEASE.md)
    assert v["bild_web"] == f"ghcr.io/sirfyyn/fyos-os/web:{e.BILD_TAG}"  # sauber: ok
    assert v["hub_bild"] == f"ghcr.io/sirfyyn/fyos-os/hub:{e.BILD_TAG}"  # sauber: ok
    assert v["bild_agent"] == f"ghcr.io/sirfyyn/fyos-agent/openclaw:{e.AGENT_TAG}"  # sauber: ok
    assert v["hub_bild_k8s"] == f"{e.BEISPIEL_REGISTRY}/fyos-os/hub-eigen:{e.BILD_TAG}"
    ohne = e.erstelle_plan(katalog, [], "compose", {}, tmp_path / "o", umgebung={})
    assert ohne.ok and not any("Beispieladresse" in h for h in ohne.hinweise)
    k8s = e.erstelle_plan(katalog, [], "k8s", {}, tmp_path / "k", umgebung={})
    hinweis = [h for h in k8s.hinweise if "Beispieladresse" in h]
    assert k8s.ok and len(hinweis) == 1 and "hub_bild_k8s" in hinweis[0] and "bild_web" not in hinweis[0]
    plan = e.erstelle_plan(katalog, [], "k8s", {}, tmp_path / "r", umgebung={"FYOS_REGISTRY": "registry.example.com/org"})
    assert plan.ok
    assert not any("Beispieladresse" in h for h in plan.hinweise)
    kust = next(d for d in plan.dateien if d.pfad == "kustomization.yaml").inhalt
    assert "registry.example.com/org/fyos-os/web" in kust and "registry.example.com/org/fyos-agent/openclaw" in kust
    plan = e.erstelle_plan(katalog, [], "compose", {"optionen": {"bild_web": "eigen.example.com/w:1"}}, tmp_path / "c",
                           umgebung={"FYOS_REGISTRY": "registry.example.com/org"})
    env = next(d for d in plan.dateien if d.pfad == ".env").inhalt
    assert "FYOS_BILD_WEB=eigen.example.com/w:1" in env and "FYOS_BILD_AGENT=registry.example.com/org/fyos-agent/openclaw:main" in env


def test_bild_tag(katalog, tmp_path):
    # FYOS_BILD_TAG setzt den Tag aller Bilder, mit und ohne eigene Registry.
    o = e.vorgaben_optionen({"FYOS_BILD_TAG": "latest"})
    assert o["bild_web"] == f"{e.OFFIZIELLE_REGISTRY}/fyos-os/web:latest"
    assert o["bild_agent"] == f"{e.OFFIZIELLE_REGISTRY}/fyos-agent/openclaw:latest"
    assert o["hub_bild_k8s"] == f"{e.BEISPIEL_REGISTRY}/fyos-os/hub-eigen:latest"
    o = e.vorgaben_optionen({"FYOS_REGISTRY": "registry.example.com/org", "FYOS_BILD_TAG": "v9"})
    assert o["hub_bild"] == "registry.example.com/org/fyos-os/hub:v9"
    assert o["hub_bild_k8s"] == "registry.example.com/org/fyos-os/hub-eigen:v9"
    plan = e.erstelle_plan(katalog, [], "k8s", {}, tmp_path / "k", umgebung={"FYOS_BILD_TAG": "latest"})
    kust = yaml.safe_load(next(d.inhalt for d in plan.dateien if d.pfad == "kustomization.yaml"))
    bilder = {b["newName"]: b["newTag"] for b in kust["images"]}
    assert bilder[f"{e.OFFIZIELLE_REGISTRY}/fyos-os/web"] == "latest"
    assert bilder[f"{e.OFFIZIELLE_REGISTRY}/fyos-agent/openclaw"] == "latest"


def test_plugin_quelle_aus_umgebung(katalog, tmp_path):
    plan = e.erstelle_plan(katalog, ["finanzen"], "compose", {}, tmp_path, umgebung={"FYOS_PLUGIN_QUELLE": "https://g.example.com/x"})
    assert plan.ok and "g.example.com/x/fyos-plugin-finanzen" in plan.hub_quellen[0]


def test_k8s(katalog, tmp_path):
    plan = _plan(katalog, ["haus"], "k8s", tmp_path, **QUELLE, **HAUS)
    assert plan.ok, plan.fehler
    e.schreiben(plan)
    out = tmp_path / "out"
    for n in ["kustomization.yaml", "fyos.yaml", "hub-config.yaml", "secrets.yaml", "secrets.example.yaml", "hub/Dockerfile", "ANLEITUNG.md"]:
        assert (out / n).is_file(), n
    _keine_reste(plan)
    assert (out / "secrets.yaml").stat().st_mode & 0o777 == 0o600
    assert "geheim$wert" not in (out / "secrets.example.yaml").read_text()
    assert "geheim$wert" in (out / "secrets.yaml").read_text()
    kust = yaml.safe_load((out / "kustomization.yaml").read_text())
    assert kust["kind"] == "Kustomization" and kust["namespace"] == "fyos"
    assert list(yaml.safe_load_all((out / "secrets.yaml").read_text()))[2]["metadata"]["name"] == "fyos-plugin"
    assert not plan.ausfuehrbar and plan.url is None


BASIS = e.PAKET.parent.parent / "deploy/k8s/base"
EIGENE_BILDER = {
    "bild_web": "registry.test.example/team/fyos-os/web:v2",
    "bild_agent": "registry.test.example/team/fyos-agent/openclaw:v2",
    "hub_bild_k8s": "registry.test.example/team/fyos-os/hub-eigen:v2",
}


@pytest.mark.skipif(not shutil.which("kubectl"), reason="kubectl fehlt")
def test_k8s_kustomize_baut(katalog, tmp_path):
    if not BASIS.is_dir():
        pytest.skip("kein Checkout")
    optionen = {**QUELLE["optionen"], **EIGENE_BILDER, "k8s_basis": str(BASIS.resolve())}
    plan = _plan(katalog, ["haus"], "k8s", tmp_path, optionen=optionen, **HAUS)
    assert plan.ok, plan.fehler
    e.schreiben(plan)
    r = subprocess.run(["kubectl", "kustomize", str(tmp_path / "out")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "name: Fy" in r.stdout and "envFrom" in r.stdout
    # Die eigenen Bilder kommen an; nichts zeigt mehr auf die Beispieladresse der Basis.
    bilder = {z.split("image:", 1)[1].strip() for z in r.stdout.splitlines() if "image:" in z}
    assert set(EIGENE_BILDER.values()) <= bilder, bilder
    assert e.BEISPIEL_REGISTRY not in r.stdout


def test_k8s_basis_absolut_wird_relativ(katalog, tmp_path):
    optionen = {**QUELLE["optionen"], "k8s_basis": str(tmp_path / "irgendwo" / "base")}
    plan = _plan(katalog, [], "k8s", tmp_path, optionen=optionen)
    assert plan.ok, plan.fehler
    kust = yaml.safe_load(next(d.inhalt for d in plan.dateien if d.pfad == "kustomization.yaml"))
    assert kust["resources"] == ["../irgendwo/base"]


def test_k8s_basisnamen_wie_die_basis():
    """Das Overlay ersetzt die Namen, die die Basis ausgibt; beide Seiten müssen übereinstimmen."""
    if not BASIS.is_dir():
        pytest.skip("kein Checkout")
    basis = yaml.safe_load((BASIS / "kustomization.yaml").read_text(encoding="utf-8"))
    assert {b["newName"] for b in basis["images"]} == set(e.BASIS_BILDNAMEN.values())


def test_dateien_ziel_wie_compose(katalog, tmp_path):
    plan = _plan(katalog, [], "dateien", tmp_path)
    assert plan.ok and not plan.ausfuehrbar and any(d.pfad == "docker-compose.yml" for d in plan.dateien)


def test_port_leitet_url_ab(katalog, tmp_path):
    plan = _plan(katalog, [], "compose", tmp_path, felder={"kern": {"port": 9000}})
    assert plan.ok and plan.url == "http://localhost:9000" and plan.port == 9000


def test_eingaben_geprueft(katalog, tmp_path):
    assert not _plan(katalog, [], "compose", tmp_path, persona={"agent_name": "a\nb"}).ok
    assert not _plan(katalog, ["haus"], "compose", tmp_path, **QUELLE, felder={"haus": {"ha_url": "ftp://x"}}).ok
    assert not _plan(katalog, [], "compose", tmp_path, felder={"kern": {"port": "abc"}}).ok
    assert not _plan(katalog, [], "ufo", tmp_path).ok
    assert not _plan(katalog, ["nix"], "compose", tmp_path).ok
    assert not _plan(katalog, [], "compose", tmp_path, optionen={"hub_bild": "x; rm -rf"}).ok


def test_vorhandene_dateien_gesichert(katalog, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / ".env").write_text("alt")
    e.schreiben(_plan(katalog, [], "compose", tmp_path))
    assert (out / ".env.vorher").read_text() == "alt" and (out / ".env").read_text() != "alt"


def test_render_reste():
    with pytest.raises(KeyError):
        e.render("{{a}}", {})
    with pytest.raises(ValueError):
        e.render("{{a}}", {"a": "{{b"})
