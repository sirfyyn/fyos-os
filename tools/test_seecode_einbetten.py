"""Erzeuger der Vorlage „diagramm“ (tools/seecode_einbetten): gepinnte Quelle, Nachbau der eingebetteten Datei.

Der Nachbau braucht einen SeeCode-Checkout auf dem gepinnten Commit; ohne ihn (Umgebungsvariable SEECODE_QUELLE) wird
dieser Teil übersprungen.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
ERZEUGER = WURZEL / "tools" / "seecode_einbetten" / "einbetten.py"
ANSICHT = WURZEL / "hub" / "mcp_hub" / "skills" / "generative-ui" / "vorlagen" / "diagramm" / "ansicht.js"


def _laden():
    spec = importlib.util.spec_from_file_location("seecode_einbetten", ERZEUGER)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_stand_ist_gepinnt():
    e = _laden()
    assert len(e.SEECODE_COMMIT) == 40 and e.SEECODE_COMMIT in ANSICHT.read_text(encoding="utf-8")
    assert all(len(h) == 64 for h in e.SHA256.values()) and "LICENSE" in e.SHA256


def test_abweichende_quelle_wird_abgelehnt(tmp_path):
    e = _laden()
    (tmp_path / "LICENSE").write_text("etwas anderes", encoding="utf-8")
    with pytest.raises(SystemExit, match="gepinnten Stand"):
        e.lesen(tmp_path, "LICENSE")


def test_eingebettete_datei_ist_der_nachbau_der_gepinnten_quelle():
    quelle = os.environ.get("SEECODE_QUELLE")
    if not quelle:
        pytest.skip("SEECODE_QUELLE (Checkout von SeeCode auf dem gepinnten Commit) nicht gesetzt")
    assert _laden().bauen(Path(quelle)) == ANSICHT.read_text(encoding="utf-8")
