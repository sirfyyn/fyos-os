"""Chat-Kanäle im Installer: Katalog, erzeugte Dateien, Platzhalter, Abnahme.

Alle Zahlen, Token und Kennungen hier sind erfunden; kein Test fasst Netz, Docker oder einen echten Kanal an.
"""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from fyos_installer import abnahme as abn
from fyos_installer import ausfuehren as ausf
from fyos_installer import cli
from fyos_installer import erzeugen as e
from fyos_installer import kanaele as kn

TOKEN = "123456:ABCdef_ghiJKL-mno"  # erfunden
TELEGRAM = {"felder": {"kanal_telegram": {"bot_token": TOKEN, "besitzer_id": "4711"}}}
WHATSAPP = {"felder": {"kanal_whatsapp": {"besitzer_nummer": "+4915100000000", "eigene_nummer": "ja"}}}
MATRIX = {"felder": {"kanal_matrix": {
    "homeserver": "https://matrix.example.org", "benutzer": "@agent:example.org",
    "zugriffstoken": "syt_geheim_token", "besitzer_id": "@besitzer:example.org"}}}


def _felder(*teile):
    felder = {}
    for t in teile:
        felder.update(t["felder"])
    return {"felder": felder}


def _plan(katalog, auswahl, ziel, tmp_path, antworten=None, umgebung=None):
    return e.erstelle_plan(katalog, auswahl, ziel, antworten or {}, tmp_path / "out", zufall=lambda n: "ab" * n,
                           umgebung=umgebung or {})


def _datei(plan, pfad):
    return next(d for d in plan.dateien if d.pfad == pfad)


# ---------------------------------------------------------------- Katalog


def test_drei_kanaele_im_katalog(katalog):
    for bid, titel in (("kanal_matrix", "Matrix"), ("kanal_telegram", "Telegram"), ("kanal_whatsapp", "WhatsApp")):
        b = katalog[bid]
        assert b.art == "kanal" and not b.pflicht and b.abhaengig_von == ["kern", "agent"], bid
        assert titel in b.titel and b.paket is None and not b.hub_plugins  # kein Paket für den Hub, kein Hub-Plugin
    umgebung = {b.id: {b.umgebungsname(f): f.typ for f in b.konfiguration}
                for b in katalog if b.art == "kanal"}
    assert umgebung["kanal_telegram"] == {"OPENCLAW_TELEGRAM_TOKEN": "geheim", "FYOS_APPROVER_TELEGRAM_ID": "text"}
    assert umgebung["kanal_matrix"]["OPENCLAW_MATRIX_TOKEN"] == "geheim"
    assert umgebung["kanal_whatsapp"]["FYOS_APPROVER_WHATSAPP_NUMBER"] == "text"
    # was der Agent zum Starten braucht, steht im Katalog als Feld
    for k in kn.KANAELE.values():
        assert set(k.noetig) <= set(umgebung[k.baustein]), k.id


# ---------------------------------------------------------------- Docker Compose


def test_telegram_compose(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_telegram"], "compose", tmp_path, TELEGRAM)
    assert plan.ok, plan.fehler
    assert plan.kanaele == {"telegram": True}
    e.schreiben(plan)
    out = tmp_path / "out"
    fyos = yaml.safe_load((out / "fyos.yaml").read_text())
    assert fyos["kanaele"] == {"telegram": True}
    env = (out / ".env").read_text()
    assert f"OPENCLAW_TELEGRAM_TOKEN={TOKEN}" in env and "FYOS_APPROVER_TELEGRAM_ID=4711" in env
    compose = yaml.safe_load((out / "docker-compose.yml").read_text())
    agent = compose["services"]["agent"]
    # Die Werte gehen an den Agenten und nie an den Hub
    assert "OPENCLAW_TELEGRAM_TOKEN" in agent["environment"] and "FYOS_APPROVER_TELEGRAM_ID" in agent["environment"]
    assert not any("TELEGRAM" in k for k in compose["services"]["hub"]["environment"])
    assert not any("TELEGRAM" in k for k in compose["services"]["web"]["environment"])
    # Telegram steckt im Basisbild: kein abgeleitetes Bild
    assert "build" not in agent and agent["image"].startswith("${FYOS_BILD_AGENT:?")
    assert not (out / "agent").exists()
    assert TOKEN not in (out / "docker-compose.yml").read_text()
    # Das Token steht nirgends in der Vorschau
    assert TOKEN not in str(plan.als_dict()) and "***" in _datei(plan, ".env").vorschau()


def test_ohne_kanal_bleibt_alles_wie_vorher(katalog, tmp_path):
    plan = _plan(katalog, [], "compose", tmp_path)
    assert plan.ok and plan.kanaele == {}
    fyos = yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)
    assert "kanaele" not in fyos and "whatsapp" not in fyos and set(fyos["besitzer"]) == {"name"}
    agent = yaml.safe_load(_datei(plan, "docker-compose.yml").inhalt)["services"]["agent"]
    assert agent["image"].startswith("${FYOS_BILD_AGENT:?") and "build" not in agent
    assert not any(d.pfad == "agent/Dockerfile" for d in plan.dateien)


def test_matrix_und_whatsapp_bekommen_ein_abgeleitetes_agent_bild(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_matrix", "kanal_whatsapp"], "compose", tmp_path, _felder(MATRIX, WHATSAPP))
    assert plan.ok, plan.fehler
    assert plan.kanaele == {"matrix": True, "whatsapp": True}
    fyos = yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)
    assert fyos["kanaele"] == {"matrix": True, "whatsapp": True}
    assert fyos["besitzer"]["matrix_id"] == "@besitzer:example.org"  # der Renderer des Agenten liest sie von hier
    assert fyos["whatsapp"] == {"eigene_nummer": True}
    df = _datei(plan, "agent/Dockerfile").inhalt
    assert "ARG FYOS_BILD_AGENT\nFROM ${FYOS_BILD_AGENT}\nUSER node" in df
    assert f"openclaw plugins install @openclaw/matrix@{kn.OPENCLAW_VERSION}" in df
    assert f"openclaw plugins install @openclaw/whatsapp@{kn.OPENCLAW_VERSION}" in df
    assert df.rstrip().endswith("cp -a /home/node/.openclaw/npm/. /opt/openclaw-npm/")
    agent = yaml.safe_load(_datei(plan, "docker-compose.yml").inhalt)["services"]["agent"]
    assert agent["build"] == {"context": "./agent", "args": {"FYOS_BILD_AGENT": "${FYOS_BILD_AGENT:?FYOS_BILD_AGENT fehlt in .env}"}}
    assert agent["image"] == "${FYOS_BILD_AGENT_EIGEN:-" + kn.BILD_AGENT_EIGEN_LOKAL + "}"
    for name in ("FYOS_MATRIX_HOMESERVER", "FYOS_MATRIX_BENUTZER", "OPENCLAW_MATRIX_TOKEN", "FYOS_APPROVER_MATRIX_ID",
                 "FYOS_APPROVER_WHATSAPP_NUMBER"):
        assert name in agent["environment"], name
    # eigene_nummer gehört nur in fyos.yaml
    assert "FYOS_WHATSAPP_EIGENE_NUMMER" not in _datei(plan, ".env").inhalt
    assert "FYOS_WHATSAPP_EIGENE_NUMMER" not in _datei(plan, "docker-compose.yml").inhalt
    assert any("agent/Dockerfile" in x for x in _datei(plan, "ANLEITUNG.md").inhalt.splitlines())


def test_whatsapp_hinweis_sagt_dass_der_besitzer_selbst_koppelt(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_whatsapp"], "compose", tmp_path, WHATSAPP)
    saetze = [h for h in plan.hinweise if h.startswith("Kanal WhatsApp: Gekoppelt")]
    assert len(saetze) == 1 and "das machst du selbst" in saetze[0]
    assert "docker compose exec agent openclaw channels login --channel whatsapp" in saetze[0]
    assert "+4915100000000" not in "\n".join(plan.hinweise)
    assert yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)["whatsapp"] == {"eigene_nummer": True}
    leer = _plan(katalog, ["kanal_whatsapp"], "compose", tmp_path, {"felder": {"kanal_whatsapp": {"besitzer_nummer": "+4915100000000"}}})
    assert yaml.safe_load(_datei(leer, "fyos.yaml").inhalt)["whatsapp"] == {"eigene_nummer": False}


def test_fehlende_werte_sind_platzhalter_und_der_kanal_bleibt_aus(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_telegram", "kanal_matrix"], "compose", tmp_path)
    assert plan.ok, plan.fehler  # kein Fehler: FYOS läuft, der Kanal ist vorbereitet
    assert plan.kanaele == {"matrix": False, "telegram": False}
    fyos = yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)
    assert fyos["kanaele"] == {"matrix": False, "telegram": False}
    env = _datei(plan, ".env").inhalt
    assert "OPENCLAW_TELEGRAM_TOKEN=\n" in env and "FYOS_APPROVER_TELEGRAM_ID=\n" in env  # die Zeile zum Ausfüllen
    assert "# Kanal Telegram" in env
    hinweise = "\n".join(plan.hinweise)
    assert "Kanal Telegram ist vorbereitet, aber aus: es fehlt OPENCLAW_TELEGRAM_TOKEN, FYOS_APPROVER_TELEGRAM_ID" in hinweise
    assert "kanaele.telegram auf true" in hinweise and "FYOS_MATRIX_HOMESERVER" in hinweise
    # Matrix braucht das Paket auch dann schon im Bild
    assert any(d.pfad == "agent/Dockerfile" for d in plan.dateien)
    # teilweise gefüllt: auch dann aus, und der Hinweis nennt nur, was fehlt
    teil = _plan(katalog, ["kanal_telegram"], "compose", tmp_path, {"felder": {"kanal_telegram": {"bot_token": TOKEN}}})
    assert teil.kanaele == {"telegram": False}
    hinweis = next(h for h in teil.hinweise if h.startswith("Kanal Telegram"))
    assert "fehlt FYOS_APPROVER_TELEGRAM_ID." in hinweis and "OPENCLAW_TELEGRAM_TOKEN" not in hinweis


@pytest.mark.parametrize("baustein,feld,wert,name", [
    ("kanal_telegram", "bot_token", "kein-token", "OPENCLAW_TELEGRAM_TOKEN"),
    ("kanal_telegram", "besitzer_id", "@name", "FYOS_APPROVER_TELEGRAM_ID"),
    ("kanal_whatsapp", "besitzer_nummer", "0151 12345", "FYOS_APPROVER_WHATSAPP_NUMBER"),
    ("kanal_matrix", "besitzer_id", "besitzer", "FYOS_APPROVER_MATRIX_ID"),
    ("kanal_matrix", "benutzer", "agent", "FYOS_MATRIX_BENUTZER"),
])
def test_falsche_form_ist_ein_fehler_ohne_den_wert(katalog, tmp_path, baustein, feld, wert, name):
    plan = _plan(katalog, [baustein], "compose", tmp_path, {"felder": {baustein: {feld: wert}}})
    assert not plan.ok and any(name in f for f in plan.fehler), plan.fehler
    assert wert not in "\n".join(plan.fehler) and not plan.dateien


def test_nicht_gewaehlter_kanal_wird_ignoriert(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_telegram"], "compose", tmp_path, _felder(TELEGRAM, MATRIX))
    assert plan.ok and "kanaele" in yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)
    assert list(yaml.safe_load(_datei(plan, "fyos.yaml").inhalt)["kanaele"]) == ["telegram"]
    assert any("kanal_matrix" in h for h in plan.hinweise)


# ---------------------------------------------------------------- Kubernetes


def test_k8s_telegram(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_telegram"], "k8s", tmp_path, TELEGRAM)
    assert plan.ok, plan.fehler
    kust = yaml.safe_load(_datei(plan, "kustomization.yaml").inhalt)
    generatoren = {g["name"]: g for g in kust["configMapGenerator"]}
    assert generatoren["fyos-agent-kanaele"]["literals"] == ["FYOS_APPROVER_TELEGRAM_ID=4711"]
    patch = next(p for p in kust["patches"] if p["target"]["name"] == "agent")
    assert "fyos-agent-kanaele" in patch["patch"] and "envFrom" in patch["patch"]
    geheimnisse = {d["metadata"]["name"]: d for d in yaml.safe_load_all(_datei(plan, "secrets.yaml").inhalt)}
    assert geheimnisse["fyos-agent-kanaele"]["stringData"] == {"OPENCLAW_TELEGRAM_TOKEN": TOKEN}
    assert "fyos-plugin" not in geheimnisse  # nichts davon im Secret des Hubs
    beispiel = _datei(plan, "secrets.example.yaml").inhalt
    assert TOKEN not in beispiel and "<ausfüllen>" in beispiel
    assert TOKEN not in _datei(plan, "secrets.yaml").vorschau()
    assert not any(d.pfad == "agent/Dockerfile" for d in plan.dateien)
    assert not any("agent-eigen" in b for b in plan.befehle)
    hub = next(p for p in kust["patches"] if p["target"]["name"] == "hub")
    assert "fyos-agent-kanaele" not in hub["patch"]
    assert "TELEGRAM" not in "\n".join(yaml.safe_load(_datei(plan, "kustomization.yaml").inhalt)["configMapGenerator"][-2]["literals"])


def test_k8s_matrix_braucht_das_abgeleitete_bild_in_der_eigenen_registry(katalog, tmp_path):
    antworten = {**MATRIX, "optionen": {"agent_bild_k8s": "registry.test.example/team/agent-eigen:v2",
                                        "bild_agent": "registry.test.example/team/fyos-agent/openclaw:v2"}}
    plan = _plan(katalog, ["kanal_matrix"], "k8s", tmp_path, antworten)
    assert plan.ok, plan.fehler
    kust = yaml.safe_load(_datei(plan, "kustomization.yaml").inhalt)
    agent_bild = next(b for b in kust["images"] if b["newName"].endswith("agent-eigen"))
    assert agent_bild["newTag"] == "v2"
    assert any(b.startswith("docker build --build-arg FYOS_BILD_AGENT=registry.test.example/team/fyos-agent/openclaw:v2 "
                            "-t registry.test.example/team/agent-eigen:v2 agent") for b in plan.befehle)
    assert "docker push registry.test.example/team/agent-eigen:v2" in plan.befehle
    assert _datei(plan, "agent/Dockerfile").inhalt.count("openclaw plugins install") == 1
    ungueltig = _plan(katalog, ["kanal_matrix"], "k8s", tmp_path,
                      {**MATRIX, "optionen": {"agent_bild_k8s": "kein bild!"}})
    assert any("agent_bild_k8s" in f for f in ungueltig.fehler)


@pytest.mark.skipif(not shutil.which("kubectl"), reason="kubectl fehlt")
def test_k8s_kustomize_baut_mit_kanaelen(katalog, tmp_path):
    basis = e.PAKET.parent.parent / "deploy/k8s/base"
    if not basis.is_dir():
        pytest.skip("kein Checkout")
    antworten = {**_felder(TELEGRAM, MATRIX), "optionen": {"k8s_basis": str(basis.resolve())}}
    plan = _plan(katalog, ["kanal_telegram", "kanal_matrix"], "k8s", tmp_path, antworten)
    assert plan.ok, plan.fehler
    e.schreiben(plan)
    r = subprocess.run(["kubectl", "kustomize", str(tmp_path / "out")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "fyos-agent-kanaele" in r.stdout and "agent-eigen" in r.stdout


# ---------------------------------------------------------------- Abnahme


STAND_GUT = {"telegram": {"an": True, "ziel": True, "bereit": True}}


def test_urteil_kanal():
    assert abn.urteil_kanal("telegram", True, STAND_GUT).urteil == "aktiv"
    aus = abn.urteil_kanal("telegram", False, None)
    assert aus.ok and aus.urteil == "aus" and "vorbereitet" in aus.text  # gewollt aus: keine Frage an den Agenten nötig
    nicht_an = abn.urteil_kanal("telegram", True, {"telegram": {"an": False, "ziel": True, "bereit": False}})
    assert not nicht_an.ok and "nicht eingeschaltet" in nicht_an.text and nicht_an.hilfe
    ohne_ziel = abn.urteil_kanal("whatsapp", True, {"whatsapp": {"an": True, "ziel": False, "bereit": False}})
    assert not ohne_ziel.ok and "Adresse des Besitzers fehlt" in ohne_ziel.text
    assert "unbekannt" not in abn.urteil_kanal("matrix", True, STAND_GUT).text
    assert not abn.urteil_kanal("matrix", True, STAND_GUT).ok  # der Agent kennt ihn nicht
    keine = abn.urteil_kanal("telegram", True, None)
    assert not keine.ok and keine.urteil == "unklar" and "keine Auskunft" in keine.text


def test_kanal_proben_fragt_nur_wenn_ein_kanal_an_sein_soll():
    fragen = []

    def abfrage():
        fragen.append(1)
        return STAND_GUT

    assert abn.kanal_proben({}, abfrage) == [] and fragen == []
    nur_aus = abn.kanal_proben({"telegram": False}, abfrage)
    assert nur_aus[0].urteil == "aus" and fragen == []
    gut = abn.kanal_proben({"telegram": True}, abfrage)
    assert [b.urteil for b in gut] == ["aktiv"] and fragen == [1]


def test_kanal_proben_wartet_auf_den_hochfahrenden_agenten():
    antworten = iter([None, None, STAND_GUT])
    pausen = []
    erg = abn.kanal_proben({"telegram": True}, lambda: next(antworten), versuche=5, pause_s=2.0, schlaf=pausen.append)
    assert erg[0].urteil == "aktiv" and pausen == [2.0, 2.0]
    pausen.clear()
    nie = abn.kanal_proben({"telegram": True}, lambda: None, versuche=3, pause_s=1.0, schlaf=pausen.append)
    assert nie[0].urteil == "unklar" and pausen == [1.0, 1.0]  # nach dem letzten Versuch keine Pause mehr


def test_abfrage_im_agenten_gibt_nur_wahrheitswerte_aus_und_nie_das_token():
    assert "OPENCLAW_GATEWAY_TOKEN" in abn.KANAL_ABFRAGE_JS and "console.log(t" not in abn.KANAL_ABFRAGE_JS
    assert "fyos.bruecke.status" in abn.KANAL_ABFRAGE_JS and "/plugins/fyos-bruecke/v1/rpc" in abn.KANAL_ABFRAGE_JS
    aufrufe = []

    def lauf(argv, **k):
        aufrufe.append((argv, k))
        return SimpleNamespace(returncode=0, stdout="Rauschen\n" + json.dumps(STAND_GUT) + "\n")

    assert abn.kanal_abfrage_compose("/ordner", lauf)() == STAND_GUT
    argv, k = aufrufe[0]
    assert argv[:7] == ["docker", "compose", "exec", "-T", "agent", "node", "-e"] and k["cwd"] == "/ordner"
    for stdout, code in (("null\n", 0), ("kein json\n", 0), ("", 0), (json.dumps(STAND_GUT), 1)):
        assert abn.kanal_abfrage_compose(".", lambda a, **k: SimpleNamespace(returncode=code, stdout=stdout))() is None

    def kaputt(argv, **k):
        raise OSError("docker fehlt")

    assert abn.kanal_abfrage_compose(".", kaputt)() is None


def test_abnahme_mit_kanaelen(abnahme_von):
    a = abnahme_von(True)
    a.kanaele = [abn.urteil_kanal("telegram", True, STAND_GUT), abn.urteil_kanal("whatsapp", False, None)]
    assert a.bestanden
    assert a.zusammenfassung() == ("Abnahme bestanden: alle 3 verbotenen Anfragen wurden abgelehnt; "
                                   "Kanäle: 1 aktiv, 1 vorbereitet und aus.")
    assert [b["id"] for b in a.als_dict()["befunde"]][-2:] == ["kanal_telegram", "kanal_whatsapp"]
    assert any(z.startswith("Kanal: Kanal Telegram: aktiv") for z in a.zeilen())
    a.kanaele.append(abn.urteil_kanal("matrix", True, None))
    assert not a.bestanden and "1 von 3 gewählten Kanälen sind im Agenten nicht aktiv" in a.zusammenfassung()
    assert any("Prüfen:" in z for z in a.zeilen())
    # eine durchgefallene Probe bleibt die Hauptsache
    schlecht = abnahme_von(False)
    schlecht.kanaele = [abn.urteil_kanal("telegram", True, STAND_GUT)]
    assert "2 von 3 verbotenen Anfragen" in schlecht.zusammenfassung()


class _Docker:
    stdout = ["zeile\n"]

    def __call__(self, argv, **k):
        return self

    def wait(self):
        return 0


def _gesund(plan, log, **k):
    return ausf.ausfuehren(plan, log.append, docker=lambda: (True, "bereit"), popen=_Docker(),
                           pruefer=lambda: {"web": True, "hub": True}, schlaf=lambda s: None, **k)


def test_ausfuehren_prueft_die_gewaehlten_kanaele(katalog, tmp_path, abnahme_von):
    plan = e.erstelle_plan(katalog, ["kanal_telegram"], "compose", TELEGRAM, tmp_path)
    gesehen = []

    def kanal(p):
        gesehen.append(p.kanaele)
        return [abn.urteil_kanal("telegram", True, STAND_GUT)]

    log = []
    erg = _gesund(plan, log, abnahme=lambda adresse: abnahme_von(True), kanal_abnahme=kanal)
    assert gesehen == [{"telegram": True}]
    assert erg.ok and erg.abnahme.bestanden and "Kanäle: 1 aktiv" in erg.meldung
    assert "Kanal: Kanal Telegram: aktiv im Agenten (eingeschaltet, Adresse des Besitzers gesetzt)" in log
    # Kanal nicht aktiv: FYOS läuft, aber die Abnahme besteht nicht (Rückgabewert 3 in der Kommandozeile)
    erg = _gesund(plan, [], abnahme=lambda adresse: abnahme_von(True),
                  kanal_abnahme=lambda p: [abn.urteil_kanal("telegram", True, None)])
    assert erg.ok and erg.nicht_abgenommen
    # ein Fehler bei der Kanalfrage kippt den Start nicht
    def kaputt(p):
        raise RuntimeError("boom")

    log = []
    erg = _gesund(plan, log, abnahme=lambda adresse: abnahme_von(True), kanal_abnahme=kaputt)
    assert erg.ok and erg.abnahme is None and "Die Abnahme konnte nicht laufen: boom" in log


def test_ausfuehren_ohne_kanaele_fragt_den_agenten_nicht(katalog, tmp_path, abnahme_von):
    plan = e.erstelle_plan(katalog, [], "compose", {}, tmp_path)
    erg = _gesund(plan, [], abnahme=lambda adresse: abnahme_von(True),
                  kanal_abnahme=lambda p: pytest.fail("ohne Kanäle keine Kanalfrage"))
    assert erg.ok and erg.abnahme.kanaele == []


def test_abnahme_hinweis_nennt_die_kanaele(katalog, tmp_path):
    plan = _plan(katalog, ["kanal_telegram", "kanal_whatsapp"], "compose", tmp_path, _felder(TELEGRAM, WHATSAPP))
    satz = next(h for h in plan.hinweise if h.startswith("Abnahme der Kanäle"))
    assert "Telegram, WhatsApp" in satz and "--kanaele telegram,whatsapp" in satz
    k8s = _plan(katalog, ["kanal_telegram"], "k8s", tmp_path, TELEGRAM)
    assert any("läuft nur bei Docker Compose von selbst" in h for h in k8s.hinweise)


# ---------------------------------------------------------------- Kommandozeile


def test_abnahme_allein_mit_kanaelen(monkeypatch, capsys, abnahme_von):
    monkeypatch.setattr(abn, "pruefen", lambda adresse: abnahme_von(True))
    monkeypatch.setattr(abn, "kanal_abfrage_compose", lambda verzeichnis, *a: (lambda: STAND_GUT))
    assert cli.main(["--abnahme", "http://localhost:8080", "--kanaele", "telegram"]) == 0
    assert "Kanal: Kanal Telegram: aktiv" in capsys.readouterr().out
    assert cli.main(["--abnahme", "http://localhost:8080", "--kanaele", "telegram,whatsapp"]) == 3
    assert cli.main(["--abnahme", "http://localhost:8080", "--kanaele", "sms"]) == 2
    assert "unbekannter Kanal sms" in capsys.readouterr().err


def test_kanaele_stehen_in_dieser_reihenfolge_im_katalog(katalog):
    assert [b.id for b in katalog if b.art == "kanal"] == ["kanal_telegram", "kanal_whatsapp", "kanal_matrix"]
