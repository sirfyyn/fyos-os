"""doku_pruefen.py: Links, Anker, Pfade in Inline-Code, feste Abschnitte der READMEs.

Laeuft in der CI als Werkzeug-Test (pytest tools) gegen kleine Repos in einem Temporaerordner, nicht gegen dieses Repo:
Ob die Doku dieses Repos stimmt, prueft der naechtliche Lauf (.gitea/workflows/doku-nachts.yml).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import doku_pruefen as d

# Eine Wurzel-README, die alle festen Abschnitte hat; _readme(zusatz) haengt Text dahinter an.
README = """# Titel

Was das hier ist.

## Was hier liegt

## Loslegen

## Erweitern

## Entwickeln

Tests laufen mit pytest.
"""
ZEILE0 = README.count("\n") + 2  # Zeile, in der der angehaengte Text beginnt
# Eine README in einem Unterordner braucht nur Titel, Einleitung und den Abschnitt zum Pruefen.
UNTER = "# Titel\n\nWas das hier ist.\n\n## Tests\n"


@pytest.fixture(autouse=True)
def _kein_umgebendes_repo(tmp_path, monkeypatch):
    # Die Temporaerordner liegen nie in einem Git-Repo; so bleibt es, auch wenn jemand TMPDIR verbiegt.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def _repo(tmp_path: Path, dateien: dict[str, str] | None = None) -> Path:
    alle = {"README.md": README, **(dateien or {})}
    for pfad, inhalt in alle.items():
        p = tmp_path / pfad
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inhalt, encoding="utf-8")
    return tmp_path


def _readme(zusatz: str) -> str:
    return README + "\n" + zusatz


def _befunde(tmp_path: Path, dateien: dict[str, str] | None = None) -> list[str]:
    return [str(b) for b in d.pruefen(_repo(tmp_path, dateien))]


def _regeln(tmp_path: Path, dateien: dict[str, str] | None = None) -> list[tuple[str, int, str]]:
    return [(b.datei, b.zeile, b.regel) for b in d.pruefen(_repo(tmp_path, dateien))]


# ---------------------------------------------------------------- Ganzes Repo


def test_sauberes_repo_hat_keine_befunde(tmp_path):
    repo = _repo(tmp_path, {
        "README.md": _readme("Siehe [die Doku](docs/A.md#abschnitt-eins) und `src/x.py` in `src/`."),
        "docs/A.md": "# A\n\n## Abschnitt eins\n\nZurueck zur [README](../README.md).\n",
        "src/x.py": "pass\n",
    })
    assert d.pruefen(repo) == []
    assert d.main([str(repo)]) == 0


def test_exitcodes_und_json(tmp_path, capsys):
    repo = _repo(tmp_path, {"README.md": _readme("[tot](fehlt.md)")})
    assert d.main([str(repo)]) == 1
    assert f"README.md:{ZEILE0}: [link] toter Link `fehlt.md`" in capsys.readouterr().out
    assert d.main([str(repo), "--json"]) == 1
    daten = json.loads(capsys.readouterr().out)
    assert daten["wurzel"] == repo.name
    assert daten["befunde"] == [{"datei": "README.md", "zeile": ZEILE0, "regel": "link", "text": daten["befunde"][0]["text"]}]
    assert d.main([str(tmp_path / "gibt-es-nicht")]) == 2


def test_nur_markdown_wird_geprueft_und_vorlagen_nicht(tmp_path):
    assert _befunde(tmp_path, {
        "notiz.txt": "[tot](fehlt.md) `nix/fehlt.py`",
        "installer/fyos_installer/vorlagen/ANLEITUNG.md": "# {{titel}}\n\n[tot](fehlt.md) `{{x}}/fehlt.py`\n",
    }) == []


# ---------------------------------------------------------------- Links


def test_toter_link_nennt_die_zeile(tmp_path):
    assert _regeln(tmp_path, {"README.md": _readme("Text\n\n[a](docs/fehlt.md)")}) == [("README.md", ZEILE0 + 2, "link")]


def test_links_sind_relativ_zum_ordner_der_datei(tmp_path):
    dateien = {
        "docs/A.md": "# A\n\nText.\n\n## Tests\n\n[b](B.md) [w](../README.md) [o](./B.md) [u](../docs/B.md)\n",
        "docs/B.md": "# B\n",
    }
    assert _befunde(tmp_path, dateien) == []
    dateien["docs/A.md"] += "[raus](../../aussen.md) [fehlt](sub/B.md)\n"
    befunde = _befunde(tmp_path, dateien)
    assert any("`../../aussen.md` zeigt aus dem Repo hinaus" in b for b in befunde)
    assert any("`sub/B.md`: docs/sub/B.md gibt es nicht" in b for b in befunde)


def test_bilder_referenzen_und_html(tmp_path):
    text = _readme(
        "![Bild](bilder/da.png) ![fehlt](bilder/fehlt.png)\n\n"
        "[da]: docs/A.md\n[weg]: docs/weg.md\n\n"
        '<img src="bilder/da.png"> <img src="bilder/nix.svg"> <a href="docs/A.md">a</a> <a href=\'docs/zu.md\'>z</a>\n'
    )
    befunde = _befunde(tmp_path, {"README.md": text, "docs/A.md": "# A\n", "bilder/da.png": ""})
    assert len(befunde) == 4, befunde
    for gesucht in ("bilder/fehlt.png", "docs/weg.md", "bilder/nix.svg", "docs/zu.md"):
        assert any(f"`{gesucht}`" in b for b in befunde), gesucht


def test_links_mit_titel_ecken_und_klammern(tmp_path):
    text = _readme('[a](docs/A.md "Titel") [b](<docs/mit leer.md>) [c](docs/a_(b).md) [d](docs/A.md#top)')
    dateien = {"README.md": text, "docs/A.md": "# A\n\n<a id=\"top\"></a>\n", "docs/mit leer.md": "", "docs/a_(b).md": ""}
    assert _befunde(tmp_path, dateien) == []


def test_links_ins_verzeichnis_und_mit_prozentzeichen(tmp_path):
    text = _readme("[o](docs/) [p](docs) [q](docs/mit%20leer.md) [r](docs/A.md?ansicht=roh)")
    assert _befunde(tmp_path, {"README.md": text, "docs/A.md": "# A\n", "docs/mit leer.md": ""}) == []
    assert _befunde(tmp_path, {"README.md": _readme("[x](fehlt/)")}) != []


def test_was_sich_vom_dateibaum_aus_nicht_pruefen_laesst(tmp_path):
    text = _readme(
        "[a](https://example.com/x) [b](mailto:a@example.com) [c](/server/pfad) [d](//example.com/x) [e]({{ziel}}) "
        "[f]($ziel) [g](#) [h](javascript:void(0)) <https://example.com/y> [i]()"
    )
    assert _befunde(tmp_path, {"README.md": text}) == []


def test_fussnoten_sind_keine_referenzdefinitionen(tmp_path):
    text = _readme("Ein Satz mit Fussnote[^1].\n\n[^1]: Erklaerung ohne Link, nur Text.\n")
    assert _befunde(tmp_path, {"README.md": text}) == []


def test_links_in_code_und_kommentaren_zaehlen_nicht(tmp_path):
    text = _readme(
        "`[a](fehlt.md)` und ``[b](fehlt.md)``\n\n```md\n[c](fehlt.md)\n```\n\n~~~\n[d](fehlt.md)\n~~~\n\n"
        "<!-- [e](fehlt.md) `nix/fehlt.py` -->\n\n<!--\n[f](fehlt.md)\n-->\n"
    )
    assert _befunde(tmp_path, {"README.md": text}) == []


def test_anker_nach_github_und_gitea_schreibweise(tmp_path):
    dateien = {
        "README.md": _readme(
            "[a](#entwickeln) [b](docs/A.md#ueber-uns) [c](docs/A.md#über-uns) [d](docs/A.md#ber-uns) "
            "[e](docs/A.md#die-datei-plan) [f](docs/A.md#doppelt-1) [g](docs/A.md#ENTWICKELN-2)"
        ),
        "docs/A.md": "# A\n\n## Ueber uns\n\n## Über uns\n\n## Die Datei `plan`\n\n## Doppelt\n\n## Doppelt\n\n"
                     "## Entwickeln 2\n",
    }
    # GitHub (über-uns) und Gitea (ber-uns), Code in der Ueberschrift, doppelte Ueberschriften (-1), Gross/Klein egal
    assert _befunde(tmp_path, dateien) == []
    dateien["README.md"] = _readme("[h](docs/A.md#doppelt-2) [i](docs/A.md#entwickeln)")
    befunde = _befunde(tmp_path, dateien)
    assert len(befunde) == 2, befunde


def test_toter_anker_in_der_eigenen_und_in_fremder_datei(tmp_path):
    text = _readme("[a](#gibt-es-nicht) [b](docs/A.md#nope) [c](docs/B.txt#zeile-3) [d](docs/A.md#a)")
    befunde = _befunde(tmp_path, {"README.md": text, "docs/A.md": "# A\n", "docs/B.txt": "x\n"})
    assert len(befunde) == 2, befunde
    assert any("`#gibt-es-nicht` gibt es in README.md nicht" in b for b in befunde)
    assert any("`#nope` gibt es in docs/A.md nicht" in b for b in befunde)


def test_ueberschriften_im_codezaun_sind_keine_anker(tmp_path):
    text = _readme("[a](#im-zaun)\n\n```sh\n# Im Zaun\n```\n")
    assert len(_befunde(tmp_path, {"README.md": text})) == 1


def test_slugs():
    assert d.slug_github("FYOS — For Your Own Sake") == "fyos--for-your-own-sake"
    assert d.slug_github("`registriereFlaechen`") == "registriereflaechen"
    assert d.slug_github("2.1 Paketstruktur") == "21-paketstruktur"
    assert d.slug_github("Über [uns](x.md) & **mehr**") == "über-uns--mehr"
    assert d.slug_goldmark("Über uns") == "ber-uns"
    assert d.slug_goldmark("Was entsteht") == "was-entsteht"
    assert d.slug_goldmark("mcp_hub (optional)") == "mcp-hub-optional"


# ---------------------------------------------------------------- Pfade in Inline-Code


def test_pfad_im_inline_code_muss_es_geben(tmp_path):
    text = _readme("Die Datei `src/x.py` gibt es, `src/fehlt.py` nicht.\nAuch `docker-compose.yml` und `Dockerfile` nicht.")
    dateien = {"README.md": text, "src/x.py": "", "src/y.py": ""}
    befunde = _befunde(tmp_path, dateien)
    assert len(befunde) == 3, befunde
    for gesucht in ("src/fehlt.py", "docker-compose.yml", "Dockerfile"):
        assert any(f"`{gesucht}` gibt es im Repo nicht" in b for b in befunde), gesucht
    assert d.main([str(tmp_path)]) == 1


def test_pfade_vom_wurzelordner_vom_dateiordner_und_als_endstueck(tmp_path):
    dateien = {
        "docs/A.md": "# A\n\n`B.md` `docs/B.md` `./B.md` `../src/x.py` `mod/plugins/p.py` `plugins/p.py` `p.py` `sub/`\n",
        "docs/B.md": "",
        "src/x.py": "",
        "hub/mod/plugins/p.py": "",
        "docs/sub/z.txt": "",
    }
    assert _befunde(tmp_path, dateien) == []
    dateien["docs/A.md"] = "# A\n\n`plugins/gone.py` `./nur-hier.py` `../src/fehlt.py` `sub/z.md`\n"
    befunde = _befunde(tmp_path, dateien)
    assert len(befunde) == 4, befunde


def test_repo_name_vor_dem_pfad_und_glob_und_ordner(tmp_path):
    text = _readme("`fyos-os/src/x.py` `fyos-os/src` `src/*.py` `src/` `fyos-os/`")
    assert _befunde(tmp_path, {"README.md": text, "src/x.py": ""}) == []
    text = _readme("`nix/*.py` `fehlt/` `src/x.py/` `src/x.py/y`")
    assert len(_befunde(tmp_path, {"README.md": text, "src/x.py": ""})) == 4


def test_die_wurzel_selbst_ist_ein_gueltiger_pfad(tmp_path):
    dateien = {"README.md": _readme("`./` `fyos-os/` `.`"), "docs/A.md": "# A\n\n`../` `./` `..`\n"}
    assert _befunde(tmp_path, dateien) == []


def test_was_kein_pfad_dieses_repos_ist(tmp_path):
    uebersprungen: list[str] = []
    text = _readme(
        "`python3 tools/fehlt.py` `<registry>/fehlt/web` `{{agent.name}}` `$HOME/fehlt` `/hub/call` `/opt/fyos/` "
        "`https://example.com/fehlt` `ui://fehlt` `Europe/Berlin` `text/event-stream` `.env` `.png` `.datum` "
        "`registry.example.com/org` `fyos-agent/fehlt.py` `fyos-plugin-foo/fehlt.py` `fyos-privat/fehlt` `a/.../b` "
        "`--tui` `FYOS_X=1` `3.11` `fyos-hub` `mcp.zeitplan` `Vorlage: fehlt.py` `~/fehlt.py` `x@example.com` "
        "`localhost:8080` `a|b` `fehlt()` `` ` `` `   `"
    )
    repo = _repo(tmp_path, {"README.md": text})
    assert d.pruefen(repo, uebersprungen) == []
    zusammen = "\n".join(uebersprungen)
    for grund in ("Leerzeichen", "Sonderzeichen", "URL-Pfad", "Bezeichner", "Dotfile", "Server", "anderen Repos", "Auslassung"):
        assert grund in zusammen, grund


def test_ein_wort_ohne_schraegstrich_braucht_eine_endung(tmp_path):
    text = _readme("`fehlt.py` `fehlt.example` `fehlt` `mcp_hub` `fehlt.zeitplan` `Makefile`")
    befunde = _befunde(tmp_path, {"README.md": text})
    assert len(befunde) == 3, befunde  # fehlt.py, fehlt.example, Makefile


def test_codezaeune_werden_nie_geprueft(tmp_path):
    text = _readme(
        "```sh\ncat nix/fehlt.py   # `nix/fehlt.py` und [x](fehlt.md)\n```\n\n"
        "````md\n```\n`nix/fehlt.py`\n```\n````\n\n~~~python\n`nix/fehlt.py`\n~~~\n"
    )
    assert _befunde(tmp_path, {"README.md": text}) == []


def test_inline_code_ueber_mehrere_zeilen_und_mit_mehreren_backticks(tmp_path):
    text = _readme("Ein Span `nix/\nfehlt.py` ueber zwei Zeilen, ``src/fehlt.py`` mit zwei Backticks, ``a`b`` und `src/x.py`.")
    befunde = _befunde(tmp_path, {"README.md": text, "src/x.py": ""})
    assert len(befunde) == 1 and "`src/fehlt.py`" in befunde[0], befunde  # der Span ueber zwei Zeilen hat ein Leerzeichen


def test_ausserhalb_txt_nimmt_namen_aus_der_pruefung(tmp_path):
    ausnahmen = (
        "# Kommentarzeile\n\n"
        "mac/            # Ordner und alles darin\n"
        "SOUL.md         # Name\n"
        "*.test.mjs      # Muster\n"
    )
    text = _readme("`mac/` `mac/install.sh` `SOUL.md` `a.test.mjs` `./SOUL.md` `fyos-os/SOUL.md` `nix.py`")
    befunde = _befunde(tmp_path, {"README.md": text, ".doku/ausserhalb.txt": ausnahmen})
    assert len(befunde) == 1 and "`nix.py`" in befunde[0], befunde


def test_ueberfluessige_ausnahmen_werden_gemeldet(tmp_path):
    ausnahmen = "SOUL.md   # steht in der Doku\nnix.py    # steht nicht mehr drin\nsrc/x.py  # gibt es inzwischen\n"
    text = _readme("`SOUL.md` `src/x.py`")
    befunde = d.pruefen(_repo(tmp_path, {"README.md": text, "src/x.py": "", ".doku/ausserhalb.txt": ausnahmen}))
    assert [(b.datei, b.zeile, b.regel) for b in befunde] == [
        (".doku/ausserhalb.txt", 2, "ausnahme"), (".doku/ausserhalb.txt", 3, "ausnahme"),
    ]


def test_nur_was_ein_frischer_checkout_enthaelt_zaehlt(tmp_path):
    def git(*args: str) -> None:
        umgebung = {"GIT_AUTHOR_NAME": "FYOS", "GIT_AUTHOR_EMAIL": "fyos@noreply.invalid", "GIT_COMMITTER_NAME": "FYOS",
                    "GIT_COMMITTER_EMAIL": "fyos@noreply.invalid", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        subprocess.run(["git", *args], cwd=tmp_path, env=umgebung, check=True, capture_output=True)

    text = _readme("`erzeugt/out.py` `src/x.py` `src/neu.py` `src/geloescht.py`")
    repo = _repo(tmp_path, {"README.md": text, ".gitignore": "erzeugt/\n", "erzeugt/out.py": "", "src/x.py": "",
                            "src/geloescht.py": ""})
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "Anfang")
    (repo / "src" / "geloescht.py").unlink()
    (repo / "src" / "neu.py").write_text("", encoding="utf-8")  # noch nicht versioniert, aber auch nicht ignoriert
    befunde = [str(b) for b in d.pruefen(repo)]
    assert len(befunde) == 2, befunde
    assert any("`erzeugt/out.py`" in b for b in befunde) and any("`src/geloescht.py`" in b for b in befunde)


# ---------------------------------------------------------------- README


def test_readme_ohne_feste_abschnitte(tmp_path):
    kaputt = {
        "a/README.md": "# Eins\n\n# Zwei\n\nText\n\n## Tests\n",
        "b/README.md": "## Zuerst\n\n# Titel\n\nText\n\n## Tests\n",
        "c/README.md": "# Titel\n\n## Tests\n\nText erst nach der Ueberschrift.\n",
        "d/README.md": "# Titel\n\nText.\n\n## Installieren\n",
        "e/README.md": "Nur Text ohne Ueberschrift.\n",
        "f/README.md": "# Nur ein Titel\n",
    }
    gefunden: dict[str, str] = {}
    for b in d.pruefen(_repo(tmp_path, kaputt)):
        assert b.regel == "readme"
        gefunden[b.datei] = gefunden.get(b.datei, "") + b.text + "\n"
    assert set(gefunden) == {f"{x}/README.md" for x in "abcdef"}
    assert gefunden["a/README.md"].count("\n") == 1 and "gefunden: 2" in gefunden["a/README.md"]
    assert gefunden["b/README.md"].count("\n") == 1 and "erste Ueberschrift" in gefunden["b/README.md"]
    assert gefunden["c/README.md"].count("\n") == 1 and "Einleitungstext" in gefunden["c/README.md"]
    assert gefunden["d/README.md"].count("\n") == 1 and 'Abschnitt "Tests" oder "Entwickeln"' in gefunden["d/README.md"]
    assert "gefunden: 0" in gefunden["e/README.md"] and 'Abschnitt "Tests"' in gefunden["e/README.md"]
    assert "Einleitungstext" in gefunden["f/README.md"] and 'Abschnitt "Tests"' in gefunden["f/README.md"]


def test_readme_abschnitt_tests_oder_entwickeln_in_jeder_schreibweise(tmp_path):
    for nr, titel in enumerate(["Tests", "tests", "Tests und Werkzeuge", "Entwickeln", "Entwickeln und prüfen", "`Tests`"]):
        _repo(tmp_path, {f"r{nr}/README.md": f"# T\n\nText.\n\n## {titel}\n"})
    assert d.pruefen(tmp_path) == []
    _repo(tmp_path, {"x/README.md": "# T\n\nText.\n\n### Tests\n\n## Wie testet man?\n"})
    assert [b.datei for b in d.pruefen(tmp_path)] == ["x/README.md"]


def test_wurzel_readme_braucht_den_wegweiser(tmp_path):
    text = "# Titel\n\nText.\n\n## Was hier liegt\n\n## Entwickeln\n"
    befunde = d.pruefen(_repo(tmp_path, {"README.md": text}))
    assert sorted(b.text for b in befunde) == [
        'Abschnitt "Erweitern" (H2) fehlt in der Wurzel-README', 'Abschnitt "Loslegen" (H2) fehlt in der Wurzel-README',
    ]
    voll = "# Titel\n\nText.\n\n## Was hier liegt\n\n## Loslegen\n\n## Erweitern\n\n## Entwickeln\n"
    assert d.pruefen(_repo(tmp_path, {"README.md": voll})) == []
    # in einem Unterordner gilt der Wegweiser nicht
    assert d.pruefen(_repo(tmp_path, {"README.md": voll, "hub/README.md": UNTER})) == []


def test_readme_ueberschriften_im_codezaun_und_im_kommentar_zaehlen_nicht(tmp_path):
    text = "# Titel\n\nText.\n\n```sh\n# Noch ein Titel\n## Tests\n```\n\n<!--\n# Kommentar\n## Tests\n-->\n"
    befunde = d.pruefen(_repo(tmp_path, {"sub/README.md": text}))
    # weder eine zweite H1 noch der Abschnitt "Tests" zaehlt: es bleibt der fehlende Abschnitt
    assert [(b.datei, b.regel) for b in befunde] == [("sub/README.md", "readme")] and "Abschnitt" in befunde[0].text


def test_andere_markdown_dateien_brauchen_keine_festen_abschnitte(tmp_path):
    assert _befunde(tmp_path, {"docs/A.md": "# Eins\n\n# Zwei\n"}) == []


def test_front_matter_ist_kein_markdown(tmp_path):
    text = "---\ntitel: x\n# kein Titel\n---\n\n# Echter Titel\n\nText.\n\n## Tests\n"
    assert d.pruefen(_repo(tmp_path, {"sub/README.md": text})) == []
    # ohne Schluessel in der ersten Zeile ist --- nur eine Trennlinie
    text = "---\n\n# Titel\n\nText.\n\n## Tests\n\n---\n"
    assert d.pruefen(_repo(tmp_path, {"sub/README.md": text})) == []


# ---------------------------------------------------------------- Zaeune


def test_ungeschlossener_zaun_wird_gemeldet(tmp_path):
    text = _readme("Text\n\n```sh\nbefehl\n\nund hier endet die Datei nie\n")
    befunde = d.pruefen(_repo(tmp_path, {"README.md": text}))
    assert [(b.regel, b.zeile) for b in befunde] == [("zaun", ZEILE0 + 2)]
    assert d.main([str(tmp_path)]) == 1


def test_zaun_schliesst_nur_mit_gleichem_zeichen_und_mindestens_gleicher_laenge(tmp_path):
    ok = _readme("````md\n```\ninnen\n```\n````\n\n~~~\n```\n~~~\n\n```sh\n``\n```\n")
    assert d.pruefen(_repo(tmp_path, {"README.md": ok})) == []
    offen = _readme("````md\n```\ninnen\n```\n")
    assert [b.regel for b in d.pruefen(_repo(tmp_path, {"README.md": offen}))] == ["zaun"]
    mit_info = _readme("```sh extra\nx\n``` nicht zu\n```\n")
    assert d.pruefen(_repo(tmp_path, {"README.md": mit_info})) == []


def test_nicht_utf8_wird_gemeldet(tmp_path):
    repo = _repo(tmp_path)
    (repo / "kaputt.md").write_bytes(b"# Titel \xff\xfe\n")
    assert [(b.datei, b.regel) for b in d.pruefen(repo)] == [("kaputt.md", "lesen")]
