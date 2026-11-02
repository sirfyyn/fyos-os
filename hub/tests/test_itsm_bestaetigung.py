"""Bestätigung der schreibenden ITSM-Werkzeuge ist einstellbar (Entscheidung Nr. 740)."""
import pytest

from mcp_hub.plugins import _itsm_wege as wege
from mcp_hub.plugins._arbeit import NICHT_BESTAETIGT
from mcp_hub.plugins.itsm import ItsmPlugin

DIENST = object.__new__(wege.DienstWeg)
ABLAGE = object()


def test_vorgaben():
    p = ItsmPlugin({})
    assert p.braucht_bestaetigung("anlegen", ABLAGE) is True
    assert p.braucht_bestaetigung("kommentieren", ABLAGE) is True
    assert p.braucht_bestaetigung("anlegen", DIENST) is False
    assert p.braucht_bestaetigung("notiz", ABLAGE) is False


def test_fuer_alle_einstellbar():
    assert ItsmPlugin({"bestaetigung": False}).braucht_bestaetigung("status_setzen", ABLAGE) is False
    assert ItsmPlugin({"bestaetigung": True}).braucht_bestaetigung("anlegen", DIENST) is True


def test_je_werkzeug_einstellbar():
    p = ItsmPlugin({"bestaetigung": {"kommentieren": False, "status_setzen": True}})
    assert p.braucht_bestaetigung("kommentieren", ABLAGE) is False
    assert p.braucht_bestaetigung("status_setzen", DIENST) is True
    assert p.braucht_bestaetigung("anlegen", ABLAGE) is True  # nicht genannt: Vorgabe


def test_anwenden():
    p = ItsmPlugin({"bestaetigung": {"anlegen": True}})
    with pytest.raises(ValueError, match="bestaetigt"):
        p._bestaetigung_anwenden("anlegen", DIENST, {"titel": "x"})
    assert p._bestaetigung_anwenden("anlegen", DIENST, {"titel": "x", "__dry_run__": True}) == {"titel": "x", "__dry_run__": True}
    frei = ItsmPlugin({"bestaetigung": False})._bestaetigung_anwenden("anlegen", ABLAGE, {"titel": "x"})
    assert frei["bestaetigt"] is True
    assert NICHT_BESTAETIGT
