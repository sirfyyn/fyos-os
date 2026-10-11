"""Stufe je Fähigkeit: Vorgaben je Bauart, einzelnes Umstellen, Fähigkeiten ohne Grundstufe, Wirkung auf die erzeugten
Dateien und die Darstellung (Kommandozeile, Textoberfläche, Web-Assistent, Anleitung)."""

import asyncio
import copy

import pytest
import yaml

from fyos_installer import cli, erzeugen, stufen, web
from fyos_installer import katalog as kat

INDEX = {"optionen": {"paketindex": "https://pypi.example.com/simple"}}
ALLE = ["kern", "agent", "leitstand", "kalender", "mail", "post"]
FAEHIGKEITEN = {"vorgaenge", "termine", "postfach", "post", "dokumente"}
# Die Adressen der Ausbaustufe, wie die Quellen im Hub sie lesen (hub/mcp_hub/*.py)
ADRESSE = {
    "vorgaenge": "FYOS_VORGAENGE_URL", "termine": "FYOS_TERMINE_URL", "postfach": "FYOS_POSTFACH_URL",
    "post": "FYOS_POST_URL", "dokumente": "FYOS_DOKUMENTE_URL",
}


def antworten(**mehr):
    return {**copy.deepcopy(INDEX), **mehr}


def plan_von(katalog, tmp_path, ziel="compose", auswahl=None, **mehr):
    plan = erzeugen.erstelle_plan(katalog, auswahl or ALLE, ziel, antworten(**mehr), tmp_path / "ziel", umgebung={})
    return plan


def stufe_von(plan):
    return {w.faehigkeit.id: w.stufe for w in plan.stufen}


def datei(plan, name):
    return next(d for d in plan.dateien if d.pfad == name).inhalt


def umgebung(plan):
    """Alles, was der Hub an Umgebung bekommt: bei Compose die .env, bei Kubernetes ConfigMap und Secret."""
    return "\n".join(datei(plan, n) for n in ("kustomization.yaml", "secrets.yaml") if any(d.pfad == n for d in plan.dateien)) \
        if plan.ziel == "k8s" else datei(plan, ".env")


# ---------------------------------------------------------------- der Katalog der Stufen


def test_katalog_kennt_die_fuenf_faehigkeiten(katalog):
    assert set(katalog.faehigkeiten) == FAEHIGKEITEN
    for f in katalog.faehigkeiten.values():
        assert f.baustein in katalog, f.id
        assert f.moegliche() and f.vorgabe("compose") in f.moegliche() and f.vorgabe("k8s") in f.moegliche()
        for s in f.stufen.values():  # jedes Feld einer Stufe gibt es am Baustein
            assert set(s.felder) <= {x.name for x in katalog[f.baustein].konfiguration}, (f.id, s.id)
        ausbau = f.stufen["ausbau"]
        feld = next(x for x in katalog[f.baustein].konfiguration if x.name == ausbau.url)
        assert katalog[f.baustein].umgebungsname(feld) == ADRESSE[f.id]


def test_vorgaben_je_bauart(katalog):
    """k8s wählt die Ausbaustufe vor, Compose die Grundstufe, wo es eine gibt (Nr. 114)."""
    compose = {i: f.vorgabe("compose") for i, f in katalog.faehigkeiten.items()}
    k8s = {i: f.vorgabe("k8s") for i, f in katalog.faehigkeiten.items()}
    assert k8s == dict.fromkeys(FAEHIGKEITEN, "ausbau")
    assert compose == {
        "vorgaenge": "grund", "termine": "grund", "postfach": "grund",
        "post": "ausbau",  # keine Grundstufe: es bleibt der Ausbau
        "dokumente": "ausbau",  # die Ordner-Ablage gibt es noch nicht
    }
    assert {i: f.vorgabe("dateien") for i, f in katalog.faehigkeiten.items()} == compose  # Layout von Compose


def test_post_hat_keine_grundstufe_dokumente_noch_keine(katalog):
    post, dok = katalog.faehigkeiten["post"], katalog.faehigkeiten["dokumente"]
    assert "grund" not in post.stufen and post.moegliche() == ["ausbau", "aus"]
    assert not dok.stufen["grund"].verfuegbar and dok.moegliche() == ["ausbau", "aus"]
    assert katalog.faehigkeiten["vorgaenge"].moegliche() == ["grund", "ausbau"]  # das Workboard lässt sich nicht abschalten


# ---------------------------------------------------------------- Vorgabe im Plan


def test_compose_nimmt_die_grundstufe_und_rendert_keinen_dienst(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", felder={
        "kalender": {"url": "https://caldav.example.com", "nutzer": "ich", "passwort": "geheimes-passwort"},
        "mail": {"host": "imap.example.com", "nutzer": "ich", "passwort": "anderes-passwort"},
    })
    assert plan.ok, plan.fehler
    assert stufe_von(plan) == {
        "vorgaenge": "grund", "termine": "grund", "postfach": "grund", "post": "ausbau", "dokumente": "ausbau",
    }
    assert all(w.vorgabe for w in plan.stufen)
    env = datei(plan, ".env")
    # der direkte Weg: CalDAV und IMAP stehen in der Umgebung, die Adressen der Dienste nicht
    for soll in ("FYOS_KALENDER_URL=https://caldav.example.com", "FYOS_MAIL_HOST=imap.example.com", "FYOS_MAIL_PORT=993"):
        assert soll in env
    for nicht in ("FYOS_TERMINE_URL", "FYOS_POSTFACH_URL", "FYOS_VORGAENGE_URL", "FYOS_TERMINE_KOPF"):
        assert nicht not in env
    assert "docker-compose" in "".join(d.pfad for d in plan.dateien)
    # der Plan nennt keinen Dienst, den er nicht liefert: keine neuen Dienste im Compose-Layout
    assert "termin" not in datei(plan, "docker-compose.yml").lower()


def test_kubernetes_nimmt_die_ausbaustufe_und_sagt_ehrlich_was_fehlt(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "k8s")
    assert plan.ok, plan.fehler
    assert stufe_von(plan) == dict.fromkeys(FAEHIGKEITEN, "ausbau") and all(w.vorgabe for w in plan.stufen)
    kust = datei(plan, "kustomization.yaml")
    for variable in ADRESSE.values():  # die Zeile steht da, leer, zum Eintragen
        assert f"{variable}=" in kust
    for w in plan.stufen:
        assert w.url_umgebung == ADRESSE[w.faehigkeit.id] and not w.url_gesetzt
        satz = [h for h in plan.hinweise if h.startswith(f"{w.faehigkeit.titel}, Ausbaustufe:")]
        assert len(satz) == 1
        assert "liefert der Installer noch nicht mit" in satz[0] and f"trage {w.url_umgebung} selbst ein" in satz[0]
        assert "kustomization.yaml" in satz[0]
    # kein erfundener Dienst: kein Deployment, kein Image für Termine oder Postfach im Overlay
    assert "listmonk" not in kust.lower() and "paperless" not in kust.lower()


def test_ausbau_mit_adresse_setzt_die_variable_und_die_kopfzeile_bleibt_geheim(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "k8s", felder={
        "kalender": {"termine_url": "http://termine.example.com:8000", "termine_kopf": "Authorization: Bearer abc123"},
    })
    assert plan.ok, plan.fehler
    w = next(w for w in plan.stufen if w.faehigkeit.id == "termine")
    assert w.url_gesetzt and w.url_umgebung == "FYOS_TERMINE_URL"
    assert "FYOS_TERMINE_URL=http://termine.example.com:8000" in datei(plan, "kustomization.yaml")
    assert "abc123" in datei(plan, "secrets.yaml") and "abc123" not in datei(plan, "kustomization.yaml")
    assert "abc123" not in next(d for d in plan.dateien if d.pfad == "secrets.yaml").vorschau()  # Vorschau ohne Geheimnisse
    satz = next(h for h in plan.hinweise if h.startswith("Termine, Ausbaustufe:"))
    assert "FYOS_TERMINE_URL" in satz and "trage" not in satz and "liefert der Installer noch nicht mit" in satz


# ---------------------------------------------------------------- einzeln umstellen


def test_einzelne_faehigkeit_umstellen_die_anderen_behalten_die_vorgabe(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"termine": "ausbau"}, felder={
        "kalender": {"termine_url": "http://termine.example.com:8000", "url": "https://caldav.example.com"},
        "mail": {"host": "imap.example.com"},
    })
    assert plan.ok, plan.fehler
    assert stufe_von(plan)["termine"] == "ausbau" and stufe_von(plan)["postfach"] == "grund"
    gewaehlt = {w.faehigkeit.id: w.vorgabe for w in plan.stufen}
    assert gewaehlt == {"vorgaenge": True, "termine": False, "postfach": True, "post": True, "dokumente": True}
    env = datei(plan, ".env")
    assert "FYOS_TERMINE_URL=http://termine.example.com:8000" in env
    assert "FYOS_KALENDER_URL" not in env  # die CalDAV-Adresse gehört zur Grundstufe und gilt hier nicht
    assert "FYOS_MAIL_HOST=imap.example.com" in env
    assert any("»Adresse des Kalenders« gehört zur Grundstufe" in h for h in plan.hinweise)


def test_kubernetes_einzeln_auf_grundstufe(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "k8s", stufen={"postfach": "grund"}, felder={
        "mail": {"host": "imap.example.com", "nutzer": "ich", "passwort": "app-passwort-1"},
    })
    assert plan.ok, plan.fehler
    assert stufe_von(plan) == {**dict.fromkeys(FAEHIGKEITEN, "ausbau"), "postfach": "grund"}
    kust = datei(plan, "kustomization.yaml")
    assert "FYOS_MAIL_HOST=imap.example.com" in kust and "FYOS_POSTFACH_URL" not in kust
    assert "app-passwort-1" in datei(plan, "secrets.yaml") and "app-passwort-1" not in kust


def test_aus_schreibt_nichts_und_meldet_nicht_eingerichtet(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "k8s", stufen={"termine": "aus", "post": "AUS"}, felder={
        "kalender": {"url": "https://caldav.example.com", "termine_url": "http://termine.example.com"},
        "post": {"url": "http://listmonk.example.com:9000"},
    })
    assert plan.ok, plan.fehler
    assert stufe_von(plan)["termine"] == "aus" and stufe_von(plan)["post"] == "aus"
    env = umgebung(plan)
    for nicht in ("FYOS_TERMINE_URL", "FYOS_KALENDER_URL", "FYOS_POST_URL", "FYOS_POST_ZUGAENGE", "FYOS_POST_TAGESGRENZE"):
        assert nicht not in env
    assert "FYOS_POSTFACH_URL=" in env  # die übrigen bleiben auf der Vorgabe der Bauart
    w = next(w for w in plan.stufen if w.faehigkeit.id == "termine")
    assert (w.stufe_titel, w.was, w.url_umgebung) == ("aus", "nicht eingerichtet", "")


def test_stufen_beim_gleichen_wunsch_wie_die_vorgabe_zaehlen_als_gewaehlt(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"termine": "grund"})
    assert not next(w for w in plan.stufen if w.faehigkeit.id == "termine").vorgabe


# ---------------------------------------------------------------- Fähigkeit ohne Grundstufe


def test_post_hat_nur_ausbau_oder_aus(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"post": "grund"})
    assert not plan.ok
    assert plan.fehler == ["Post senden: hat keine Grundstufe; wähle ausbau oder aus"]


def test_dokumente_grundstufe_gibt_es_noch_nicht(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"dokumente": "grund"})
    assert not plan.ok
    (fehler,) = plan.fehler
    assert fehler.startswith("Dokumente: die Grundstufe (Ordner-Ablage) gibt es noch nicht; wähle ausbau oder aus")


def test_vorgaenge_lassen_sich_nicht_ausschalten(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"vorgaenge": "aus"})
    assert plan.fehler == ["Vorgänge: lässt sich nicht ausschalten; wähle grund oder ausbau"]


def test_post_ohne_grundstufe_hinweis_nennt_den_weg(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose")
    satz = next(h for h in plan.hinweise if h.startswith("Post senden, Ausbaustufe:"))
    assert "FYOS_POST_URL" in satz and "Eine Grundstufe ohne Dienst gibt es hier nicht." in satz and ".env" in satz
    assert "FYOS_POST_URL=" in datei(plan, ".env")  # die Zeile steht leer zum Eintragen da
    satz = next(h for h in plan.hinweise if h.startswith("Dokumente, Ausbaustufe:"))
    assert "Ohne eigenen Dienst wähle die Grundstufe." not in satz  # sie gibt es nicht, also kein Rat dazu


# ---------------------------------------------------------------- Fehleingaben


@pytest.mark.parametrize("stufen_wert, teil", [
    ({"termine": "zauber"}, "die Stufe 'zauber' gibt es nicht (erlaubt: grund, ausbau, aus)"),
    ({"termin": "grund"}, "Unbekannte Fähigkeit 'termin' bei den Stufen"),
    ("grund", "'stufen' muss ein Objekt"),
])
def test_ungueltige_stufen(katalog, tmp_path, stufen_wert, teil):
    plan = plan_von(katalog, tmp_path, "compose", stufen=stufen_wert)
    assert not plan.ok and any(teil in f for f in plan.fehler), plan.fehler


def test_stufe_eines_nicht_gewaehlten_bausteins_wird_ignoriert(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", auswahl=["kern", "agent"], stufen={"termine": "ausbau"})
    assert plan.ok and plan.stufen == []
    assert "Die Stufe für Termine wird ignoriert: der Baustein 'kalender' ist nicht gewählt." in plan.hinweise


def test_ohne_faehigkeiten_im_plan_bleibt_alles_wie_vorher(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", auswahl=["kern", "agent"])
    assert plan.ok and plan.stufen == [] and plan.als_dict()["stufen"] == []
    assert "Stufe" not in datei(plan, "ANLEITUNG.md")


# ---------------------------------------------------------------- Darstellung des Ergebnisses


def test_plan_als_dict_traegt_die_stufen(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"termine": "ausbau"})
    daten = {s["id"]: s for s in plan.als_dict()["stufen"]}
    assert set(daten) == FAEHIGKEITEN
    assert daten["termine"] == {
        "id": "termine", "titel": "Termine", "baustein": "kalender", "stufe": "ausbau", "stufe_titel": "Ausbaustufe",
        "vorgabe": False, "was": "eigener Termin-Dienst", "umgebung": "FYOS_TERMINE_URL", "adresse_gesetzt": False,
    }
    assert daten["postfach"]["stufe_titel"] == "Grundstufe" and daten["postfach"]["vorgabe"] is True
    assert daten["postfach"]["umgebung"] == "" and daten["postfach"]["was"] == "IMAP direkt"


def test_zeilen_sagen_stufe_herkunft_und_inhalt(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "compose", stufen={"termine": "ausbau", "post": "aus"})
    zeilen = stufen.zeilen(plan.stufen)
    assert "Termine: Ausbaustufe (von dir gewählt), eigener Termin-Dienst" in zeilen
    assert "Postfach lesen: Grundstufe (Vorgabe), IMAP direkt" in zeilen
    assert "Post senden: aus (von dir gewählt), nicht eingerichtet" in zeilen
    assert "Vorgänge: Grundstufe (Vorgabe), Workboard des Agenten" in zeilen


def test_anleitung_nennt_die_stufe_unter_dem_baustein(katalog, tmp_path):
    plan = plan_von(katalog, tmp_path, "k8s", auswahl=["kern", "agent", "kalender"])
    text = datei(plan, "ANLEITUNG.md")
    assert "- **Kalender mit CalDAV und ICS-Abo**: " in text
    assert "  - Termine: Ausbaustufe (Vorgabe), eigener Termin-Dienst" in text
    assert "FYOS_TERMINE_URL" in text  # der Hinweis steht in der Anleitung


def test_trocken_zeigt_die_stufen(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FYOS_PAKETINDEX", "https://pypi.example.com/simple")
    rc = cli.main(["--auswahl", "kern,agent,kalender,mail", "--ziel", "k8s", "--verzeichnis", str(tmp_path / "x"),
                   "--trocken", "--ohne-plugin-kataloge", "--stufe", "termine=grund"])
    out = capsys.readouterr().out
    assert rc == 0 and not (tmp_path / "x").exists()
    assert "Stufe je Fähigkeit (Vorgabe nach Bauart, umstellbar mit --stufe FÄHIGKEIT=grund|ausbau|aus):" in out
    assert "  Termine: Grundstufe (von dir gewählt), CalDAV und ICS direkt" in out
    assert "  Postfach lesen: Ausbaustufe (Vorgabe), eigener Postfach-Dienst" in out
    assert out.index("Zielordner") < out.index("Stufe je Fähigkeit") < out.index("Reifegrad") < out.index("Dateien:")
    assert "Hinweis: Postfach lesen, Ausbaustufe: Den Dienst (eigener Postfach-Dienst) liefert der Installer noch nicht mit" in out


def test_cli_stufe_aus_datei_und_option(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FYOS_PAKETINDEX", "https://pypi.example.com/simple")
    a = tmp_path / "a.yaml"
    a.write_text(yaml.safe_dump({"stufen": {"termine": "ausbau", "postfach": "aus"}}))
    rc = cli.main(["--auswahl", "kern,agent,kalender,mail", "--ziel", "compose", "--antworten", str(a),
                   "--stufe", "postfach=grund", "--verzeichnis", str(tmp_path / "x"), "--trocken", "--ohne-plugin-kataloge"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Termine: Ausbaustufe (von dir gewählt)" in out  # aus der Datei
    assert "Postfach lesen: Grundstufe (von dir gewählt)" in out  # die Option gewinnt gegen die Datei


@pytest.mark.parametrize("angabe, teil", [
    (["--stufe", "termine"], "erwartet FÄHIGKEIT=STUFE"),
    (["--stufe", "termine="], "erwartet FÄHIGKEIT=STUFE"),
])
def test_cli_stufe_falsche_form(tmp_path, capsys, angabe, teil):
    rc = cli.main(["--auswahl", "kern,agent,kalender", "--verzeichnis", str(tmp_path / "x"), "--trocken", *angabe])
    assert rc == 2 and teil in capsys.readouterr().err


def test_cli_stufe_nicht_moeglich_ist_ein_fehler(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FYOS_PAKETINDEX", "https://pypi.example.com/simple")
    rc =cli.main(["--auswahl", "kern,agent,post", "--verzeichnis", str(tmp_path / "x"), "--trocken",
                   "--ohne-plugin-kataloge", "--stufe", "post=grund"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "Post senden: hat keine Grundstufe; wähle ausbau oder aus" in err


def test_liste_nennt_faehigkeiten_stufen_und_vorgaben(capsys):
    assert cli.main(["--liste", "--ohne-plugin-kataloge"]) == 0
    out = capsys.readouterr().out
    assert "Fähigkeiten (Stufe wählen mit --stufe FÄHIGKEIT=grund|ausbau|aus):" in out
    zeile = next(z for z in out.splitlines() if z.strip().startswith("termine"))
    assert "grund: CalDAV und ICS direkt" in zeile and "ausbau: eigener Termin-Dienst" in zeile
    assert "Vorgabe Compose grund, Kubernetes ausbau" in zeile
    post = next(z for z in out.splitlines() if "Post senden:" in z)
    assert "grund" not in post.split("Vorgabe")[0] and "Vorgabe Compose ausbau, Kubernetes ausbau" in post


def test_web_katalog_und_plan(katalog, tmp_path):
    z = web.Zustand(katalog, docker=lambda: (True, "bereit"), umgebung={}, verzeichnis=tmp_path / "w")
    daten = z.katalog_json()
    termine = next(f for f in daten["faehigkeiten"] if f["id"] == "termine")
    assert termine["baustein"] == "kalender" and termine["moegliche"] == ["grund", "ausbau", "aus"]
    assert termine["vorgabe"] == {"compose": "grund", "dateien": "grund", "k8s": "ausbau"}
    assert [s["id"] for s in termine["stufen"]] == ["grund", "ausbau"]
    assert termine["stufen"][1]["felder"] == ["termine_url", "termine_kopf"]
    dok = next(f for f in daten["faehigkeiten"] if f["id"] == "dokumente")
    assert dok["stufen"][0]["verfuegbar"] is False and dok["moegliche"] == ["ausbau", "aus"]
    plan = z.plan_aus({"auswahl": ["kalender"], "ziel": "k8s", "verzeichnis": str(tmp_path / "w"),
                       "antworten": {**INDEX, "stufen": {"termine": "grund"}}})
    assert plan.ok, plan.fehler
    assert plan.als_dict()["stufen"][0]["stufe"] == "grund"


def test_tui_zusammenfassung_und_auswahl(katalog, tmp_path):
    pytest.importorskip("textual")
    from fyos_installer import tui

    plan = plan_von(katalog, tmp_path, "k8s", auswahl=["kern", "agent", "kalender"], stufen={"termine": "grund"})
    text = tui.InstallerApp(katalog, tmp_path / "t")._zusammenfassung(plan)
    assert text.index("### Stufe je Fähigkeit") < text.index("### Reifegrad") < text.index("### Dateien")
    assert "- Termine: Grundstufe (von dir gewählt), CalDAV und ICS direkt" in text
    plan = plan_von(katalog, tmp_path, "k8s", auswahl=["kern", "agent", "kalender"])
    text = tui.InstallerApp(katalog, tmp_path / "t")._zusammenfassung(plan)
    assert "- Termine: Ausbaustufe (Vorgabe), eigener Termin-Dienst" in text
    assert "Adresse in `FYOS_TERMINE_URL`: noch leer, trage sie selbst ein; den Dienst liefert der Installer noch nicht mit." in text
    plan = plan_von(katalog, tmp_path, "compose", auswahl=["kern", "agent"])
    assert "Stufe je Fähigkeit" not in tui.InstallerApp(katalog, tmp_path / "t")._zusammenfassung(plan)


@pytest.mark.parametrize("ziel, vorgewaehlt", [("compose", 0), ("k8s", 1)])
def test_tui_eine_auswahl_je_faehigkeit(katalog, tmp_path, monkeypatch, ziel, vorgewaehlt):
    pytest.importorskip("textual")
    from textual.widgets import RadioButton, RadioSet

    from fyos_installer import ausfuehren as ausf
    from fyos_installer import tui

    monkeypatch.setattr(ausf, "docker_pruefen", lambda *a, **k: (True, "bereit"))

    async def lauf():
        app = tui.InstallerApp(katalog, tmp_path / "t")
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.press("n", "n")
            app.ziel = ziel
            app.query_one("#liste").select("kalender")
            app.query_one("#liste").select("post")
            await pilot.pause()
            await pilot.press("n")
            assert app.schritt == 3
            termine = app.query_one("#stufe-termine", RadioSet)
            assert termine.pressed_index == vorgewaehlt  # grund bei Compose, ausbau bei Kubernetes
            assert [str(b.label) for b in termine.query(RadioButton)] == [
                "Grundstufe: CalDAV und ICS direkt", "Ausbaustufe: eigener Termin-Dienst", "aus: nicht einrichten"]
            post = app.query_one("#stufe-post", RadioSet)
            assert [str(b.label) for b in post.query(RadioButton)][0].startswith("Ausbaustufe: Listmonk")
            assert post.pressed_index == 0  # es gibt nur Ausbau oder aus
            assert app._stufen_gewaehlt()["termine"] == ("grund", "ausbau")[vorgewaehlt]
            # umstellen: die Auswahl landet in den Antworten und im Plan
            umstellen = "ausbau" if ziel == "compose" else "grund"
            termine.query(RadioButton)[1 if umstellen == "ausbau" else 0].value = True
            await pilot.pause()
            assert app._antworten()["stufen"]["termine"] == umstellen
            app.query_one("#in-optionen-paketindex").value = "https://pypi.example.com/simple"
            plan = app._plan()
            assert plan.ok, plan.fehler
            assert stufe_von(plan)["termine"] == umstellen and not next(
                w for w in plan.stufen if w.faehigkeit.id == "termine").vorgabe

    asyncio.run(lauf())


# ---------------------------------------------------------------- Schema und ersetzte Bausteine


def _roh():
    return copy.deepcopy(yaml.safe_load(kat.STUFEN_KATALOG.read_text(encoding="utf-8")))


@pytest.mark.parametrize("aendern, teil", [
    (lambda d: d["faehigkeiten"][0].pop("titel"), "'titel' muss ein nichtleerer Text sein"),
    (lambda d: d["faehigkeiten"][0].update(stufen={}), "braucht mindestens grund oder ausbau"),
    (lambda d: d["faehigkeiten"][0]["stufen"].update(aus={"titel": "x", "text": "y"}), "unbekannte Stufe 'aus'"),
    (lambda d: d["faehigkeiten"][0]["stufen"]["grund"].update(url="x"), "'url' gibt es nur bei der Ausbaustufe"),
    (lambda d: d["faehigkeiten"][0]["stufen"]["ausbau"].update(url="gibtsnicht"), "muss eines ihrer Felder sein"),
    (lambda d: d["faehigkeiten"][0].update(aus="ja"), "'aus' muss wahr oder falsch sein"),
    (lambda d: d["faehigkeiten"][0]["stufen"]["grund"].update(verfuegbar="nein"), "'verfuegbar' muss wahr oder falsch sein"),
    (lambda d: d["faehigkeiten"].append(copy.deepcopy(d["faehigkeiten"][0])), "kommt doppelt vor"),
    (lambda d: d["faehigkeiten"][4]["stufen"]["ausbau"].update(verfuegbar=False), "mindestens eine Stufe muss verfügbar sein"),
])
def test_schema_verstoesse(aendern, teil):
    d = _roh()
    aendern(d)
    with pytest.raises(kat.KatalogFehler, match=teil):
        stufen.parse(d, "test")


def test_ersetzter_baustein_verliert_die_stufen_nicht(tmp_path):
    """Ein Plugin-Paket bringt einen eigenen Katalogeintrag mit (ohne die Felder der Ausbaustufe) und ersetzt den
    des Installers: die Ausbau-Felder legt der Katalog der Stufen wieder an, fehlende Grund-Felder meldet er."""
    f = tmp_path / "fyos-katalog.yaml"
    f.write_text(yaml.safe_dump({"bausteine": [{
        "id": "kalender", "titel": "Kalender aus dem Paket", "kurz": "k", "was_daraus_wird": "Eins. Zwei. Drei.",
        "art": "plugin", "abhaengig_von": ["kern", "agent"],
        "konfiguration": [{"name": "url", "titel": "Adresse", "typ": "url"}],
    }]}))
    k = kat.lade_standard([str(f)], plugins=False)
    assert k["kalender"].titel == "Kalender aus dem Paket"
    assert {x.name for x in k["kalender"].konfiguration} == {"url", "termine_url", "termine_kopf"}
    assert any("dem Baustein 'kalender'" in h and "nutzer, passwort" in h and "Grundstufe" in h for h in k.hinweise)
    assert k.faehigkeiten["termine"].stufen["grund"].felder == ("url",)
    assert k.faehigkeiten["termine"].stufen["ausbau"].url == "termine_url"
    plan = erzeugen.erstelle_plan(k, ["kalender"], "compose", antworten(), tmp_path / "z", umgebung={})
    assert plan.ok, plan.fehler
    assert stufe_von(plan) == {"termine": "grund"}


def test_fehlender_baustein_laesst_die_faehigkeit_entfallen():
    k = kat.Katalog(kat.parse(yaml.safe_load(kat.STANDARD_KATALOG.read_text(encoding="utf-8")), "t"))
    stufen.verbinde(k, [stufen.Faehigkeit("x", "X", "k", "gibtsnicht", {"grund": stufen.Stufe("grund", "t", "t")})])
    assert k.faehigkeiten == {} and any("Fähigkeit 'x' entfällt" in h for h in k.hinweise)
