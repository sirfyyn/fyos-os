"""Brücke der Hub-Apps (ui/_bruecke.js) im Node-Lauf: Frische-Stempel, Plan-Text, Anfrage statt Aktion.

`bruecke_test.mjs` lädt die Brücke gegen eine Mini-Attrappe von Fenster, Dokument und Host (wie
`installer/tests/seiten_test.mjs` den Web-Assistenten). Ohne `node` entfällt der Test.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
BRUECKE = TESTS.parent / "mcp_hub" / "plugins" / "ui" / "_bruecke.js"


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
def test_bruecke_frische_plan_und_anfrage():
    r = subprocess.run(
        ["node", str(TESTS / "bruecke_test.mjs"), str(BRUECKE)], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert r.stdout.strip() == "ok"
