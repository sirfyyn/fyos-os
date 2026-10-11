"""nachtauftrag.py: der Nachtauftrag als nativer Cron-Auftrag des Agenten (OpenClaw), ohne den Agenten selbst zu rufen."""

from __future__ import annotations

import json
import subprocess

import pytest

import nachtauftrag as n


class Agent:
    """Ein Agent, der `openclaw cron list|add|run|rm` kennt und die Aufrufe merkt."""

    def __init__(self, vorhanden: bool = False, scheitert: str = "", text: str | None = None):
        self.jobs: list[dict] = [{"id": "x1", "declarationKey": "memory-core:traeumen", "name": "Fremd"}]
        if vorhanden:
            self.jobs.append({
                "id": "j7", "declarationKey": n.SCHLUESSEL, "name": n.NAME,
                "payload": {"kind": "agentTurn", "message": n.AUFTRAG if text is None else text},
            })
        self.aufrufe: list[list[str]] = []
        self.scheitert = scheitert

    def __call__(self, befehl: list[str]):
        self.aufrufe.append(befehl)
        i = befehl.index("openclaw")
        art = befehl[i + 2]
        if art == self.scheitert:
            return subprocess.CompletedProcess(befehl, 3, "", "Gateway nicht erreichbar")
        if art == "list":
            return subprocess.CompletedProcess(befehl, 0, "OpenClaw 2026.9.7\n" + json.dumps({"jobs": self.jobs}), "")
        if art == "add":
            self.jobs.append({"id": "j7", "declarationKey": n.SCHLUESSEL, "name": n.NAME})
        if art == "edit":
            for j in self.jobs:
                if j["id"] == befehl[i + 3]:
                    j["payload"]["message"] = befehl[befehl.index("--message") + 1]
        if art == "rm":
            self.jobs = [j for j in self.jobs if j["id"] != befehl[i + 3]]
        return subprocess.CompletedProcess(befehl, 0, "{}", "")

    def arten(self) -> list[str]:
        return [a[a.index("openclaw") + 2] for a in self.aufrufe]


def lauf(agent: Agent, *argv: str) -> tuple[int, list[str]]:
    zeilen: list[str] = []
    code = n.machen(
        vorsatz=["docker", "compose", "exec", "-T", "agent"], uhr="03:00", zeitzone="", jetzt="--jetzt" in argv,
        entfernen="--entfernen" in argv, trocken="--trocken" in argv, lauf=agent, ausgabe=zeilen.append,
    )
    return code, zeilen


def test_cron_ausdruck():
    assert n.cron_ausdruck("03:00") == "0 3 * * *"
    assert n.cron_ausdruck("2:30") == "30 2 * * *"
    assert n.cron_ausdruck("23:59") == "59 23 * * *"
    for schlecht in ("24:00", "3", "03:60", "nachts", ""):
        with pytest.raises(ValueError):
            n.cron_ausdruck(schlecht)


def test_der_auftrag_meldet_ueber_os_mitteilen_und_ruft_keinen_chat():
    assert "os.mitteilen" in n.AUFTRAG and "keinen Chat" in n.AUFTRAG
    args = n.add_argumente("03:00", "Europe/Berlin")
    assert args[:3] == ["openclaw", "cron", "add"]
    assert args[args.index("--declaration-key") + 1] == n.SCHLUESSEL
    assert args[args.index("--cron") + 1] == "0 3 * * *"
    assert args[args.index("--session") + 1] == "isolated" and "--no-deliver" in args and "--exact" in args
    assert args[args.index("--tz") + 1] == "Europe/Berlin"
    assert "--tz" not in n.add_argumente("03:00")
    # neutral: der Auftrag spricht vom Besitzer, nicht von einer bestimmten Person (tools/sauber.py prüft die Namen)
    assert "Besitzers" in n.AUFTRAG


def test_der_auftrag_liest_den_notizzettel_im_hub_und_nicht_den_workspace():
    # Befund Testserver 11.10.: Die Cron-Sitzung hat kein Werkzeug, das einen Ordner auflistet (`read` lehnt Verzeichnisse ab),
    # und hielt den vollen Workspace-Ordner notizen/ deshalb für leer. Die Notizen stehen auf dem Notizzettel im Hub.
    a = n.AUFTRAG
    assert n.LESE_WERKZEUG == "beispiel_app.zeigen" and f'tool "{n.LESE_WERKZEUG}"' in a and "hub__call_tool" in a
    assert "notizen/" not in a and "Ordner" not in a and "nicht in MEMORY.md" in a and "memory/" not in a
    # leer melden darf er nur bei leerem Zettel (anzahl 0), bei einem Fehler des Aufrufs ausdrücklich nicht
    assert 'Nur wenn der Notizzettel leer ist (anzahl 0)' in a and a.count("Keine neuen Notizen") == 1
    assert "Notizzettel nicht erreichbar" in a and "nie, der Notizzettel sei leer" in a
    # es bleibt bei genau einer Mitteilung ohne Chat
    assert a.count("os.mitteilen") == 1 and "genau einmal" in a and "keinen Chat" in a


def test_legt_den_auftrag_an_und_fragt_danach_nach_der_id():
    agent = Agent()
    code, zeilen = lauf(agent)
    assert code == 0 and agent.arten() == ["list", "add", "list"]
    assert agent.aufrufe[0][:5] == ["docker", "compose", "exec", "-T", "agent"]  # alles läuft im Agenten-Container
    assert "Angelegt" in zeilen[0]


def test_ist_er_schon_da_wird_nichts_doppelt_angelegt():
    agent = Agent(vorhanden=True)
    code, zeilen = lauf(agent)
    assert code == 0 and agent.arten() == ["list"] and "Schon angelegt" in zeilen[0]


def test_ein_aelterer_auftragstext_wird_nachgezogen_ohne_neu_anzulegen():
    agent = Agent(vorhanden=True, text="Nachtauftrag Notizen. Sieh den Ordner notizen/ im Workspace durch.")
    code, zeilen = lauf(agent)
    assert code == 0 and agent.arten() == ["list", "edit"] and "Auftragstext aktualisiert" in zeilen[0]
    edit = agent.aufrufe[-1]
    assert edit[edit.index("edit") + 1] == "j7" and edit[edit.index("--message") + 1] == n.AUFTRAG
    assert agent.jobs[-1]["payload"]["message"] == n.AUFTRAG and len(agent.jobs) == 2
    # beim zweiten Aufruf ist nichts mehr zu tun
    agent.aufrufe.clear()
    code, zeilen = lauf(agent)
    assert code == 0 and agent.arten() == ["list"] and "nichts geändert" in zeilen[0]


def test_jetzt_laesst_ihn_einmal_laufen_und_wartet():
    agent = Agent()
    code, _ = lauf(agent, "--jetzt")
    assert code == 0 and agent.arten() == ["list", "add", "list", "run"]
    lauf_befehl = agent.aufrufe[-1]
    assert lauf_befehl[lauf_befehl.index("run") + 1] == "j7" and "--wait" in lauf_befehl


def test_entfernen():
    agent = Agent(vorhanden=True)
    code, _ = lauf(agent, "--entfernen")
    assert code == 0 and agent.arten() == ["list", "rm"] and [j["id"] for j in agent.jobs] == ["x1"]
    code, zeilen = lauf(agent, "--entfernen")
    assert code == 0 and "nicht angelegt" in zeilen[0] and agent.arten() == ["list", "rm", "list"]


def test_ein_fehler_des_agenten_ist_exitcode_1_mit_dem_grund():
    agent = Agent(scheitert="add")
    code, zeilen = lauf(agent)
    assert code == 1 and "Gateway nicht erreichbar" in zeilen[-1]


def test_trocken_ruft_nichts():
    agent = Agent()
    code, zeilen = lauf(agent, "--trocken")
    assert code == 0 and agent.aufrufe == []
    assert any("cron add" in z for z in zeilen) and any("docker compose exec -T agent openclaw" in z for z in zeilen)


def test_main_prueft_die_aufrufargumente(capsys):
    assert n.main(["--um", "abends"], lauf=Agent()) == 2
    assert n.main(["--in", ""], lauf=Agent()) == 2
    agent = Agent()
    assert n.main(["--in", "kubectl -n fyos exec agent-0 --", "--um", "02:30", "--zeitzone", "Europe/Berlin"], lauf=agent) == 0
    assert agent.aufrufe[0][:5] == ["kubectl", "-n", "fyos", "exec", "agent-0"]
    add = next(a for a in agent.aufrufe if "add" in a)
    assert add[add.index("--cron") + 1] == "30 2 * * *"
