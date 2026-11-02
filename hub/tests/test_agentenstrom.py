"""Agentenstrom `fyos:agent` — der Ereignisvertrag aus ADR-216, M1 (Felder, Kürzung, Schreiben), ohne Netz.

Der Runner schreibt, alle Betrachter lesen; hier steht nur die Form des Eintrags.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from mcp_hub.plugins import _agentenstrom as a

JETZT_MS = 1_791_100_000_000


def _e(**kw):
    felder = dict(agent="agent", sitzung="sitz-1", q=1, typ="session.idle")
    felder.update(kw)
    return a.eintrag(felder, jetzt_ms=JETZT_MS)


def test_grundgeruest_traegt_nur_den_vertrag():
    assert _e() == {
        "t": str(JETZT_MS),
        "v": "1",
        "typ": "session.idle",
        "a": "agent",
        "s": "sitz-1",
        "q": "1",
    }


def test_zeit_kommt_aus_dem_ereignis_wenn_gesetzt():
    assert _e(t=123)["t"] == "123"
    assert _e(t=123.7)["t"] == "123"


def test_unbekannter_typ_wirft():
    with pytest.raises(ValueError):
        _e(typ="chat")
    # `connected` ist der SSE-Rahmen, kein Stromereignis.
    assert "connected" not in a.ARTEN


def test_agenten_id_wird_normiert_und_bleibt_pflicht():
    assert _e(agent="Agent TV!")["a"] == "agenttv"
    assert _e(agent="Agent")["a"] == "agent"
    assert _e(agent="x" * 60)["a"] == "x" * 32
    with pytest.raises(ValueError):
        _e(agent="")
    with pytest.raises(ValueError):
        _e(agent="!!!")


def test_sitzung_und_sequenz_sind_pflicht():
    with pytest.raises(ValueError):
        _e(sitzung="")
    with pytest.raises(ValueError):
        _e(sitzung="hat leerzeichen")
    for q in (0, -1, "1", True, None):
        with pytest.raises(ValueError):
            _e(q=q)


def test_fremde_felder_fallen_weg():
    e = _e(boese="nicht in den Strom", arguments="{geheim}")
    assert "boese" not in e and "arguments" not in e


@pytest.mark.parametrize("pt", ["text", "reasoning"])
def test_text_deltas_behalten_ihre_form(pt):
    e = _e(typ="part.updated", id="p1", pt=pt, delta="\n\nHallo ")
    assert e["id"] == "p1" and e["pt"] == pt
    assert e["delta"] == "\n\nHallo "
    with pytest.raises(ValueError):
        _e(typ="part.updated", id="p1", pt=pt, delta="")


def test_steuerzeichen_fallen_weg_zeilenumbruch_bleibt():
    e = _e(typ="part.updated", id="p1", pt="text", delta="a\x00b\nc\rd")
    assert e["delta"] == "ab\ncd"


def test_werkzeug_start_mit_gekuerzten_entschaerften_argumenten():
    e = _e(
        typ="part.updated",
        id="t1",
        pt="tool",
        wz="chat.senden",
        st="running",
        args={"text": "hi", "token": "geheim-123"},
    )
    assert e["wz"] == "chat.senden" and e["st"] == "running"
    assert '"token":"…"' in e["args"] and "geheim-123" not in e["args"]


def test_werkzeug_ende_kuerzt_ergebnis_und_markiert_ungeprueft():
    e = _e(typ="part.updated", id="t1", pt="tool", st="completed", ergebnis="x" * 1500, vertr=False)
    assert len(e["ergebnis"]) == a.ERGEBNIS_MAX and e["ergebnis"].endswith(a.KUERZUNG)
    assert e["vertr"] == "0"
    assert "vertr" not in _e(
        typ="part.updated", id="t1", pt="tool", st="completed", ergebnis="ok", vertr=True
    )


def test_werkzeug_ohne_inhalt_und_mit_falschem_zustand_wirft():
    with pytest.raises(ValueError):
        _e(typ="part.updated", id="t1", pt="tool")
    with pytest.raises(ValueError):
        _e(typ="part.updated", id="t1", pt="tool", wz="chat.senden", st="laeuft")


def test_schritt_pruefen_und_kuerzen():
    e = _e(typ="part.updated", id="s1", pt="step", label="x" * 300, phase="start")
    assert len(e["label"]) == a.LABEL_MAX and e["label"].endswith(a.KUERZUNG)
    assert e["phase"] == "start"
    with pytest.raises(ValueError):
        _e(typ="part.updated", id="s1", pt="step", label="X", phase="mitte")
    with pytest.raises(ValueError):
        _e(typ="part.updated", id="s1", pt="step", label="", phase="start")


def test_part_done_traegt_nur_die_kennung():
    e = _e(typ="part.done", id="p1")
    assert e["id"] == "p1" and "delta" not in e
    with pytest.raises(ValueError):
        _e(typ="part.done")


def test_plan_update_hoechstens_zwanzig_schritte():
    schritte = [{"id": f"s{i}", "label": f"Schritt {i}", "state": "pending"} for i in range(25)]
    e = _e(typ="plan.update", schritte=schritte)
    gelesen = json.loads(e["schritte"])
    assert len(gelesen) == a.SCHRITTE_MAX and gelesen[0] == {
        "id": "s0",
        "label": "Schritt 0",
        "state": "pending",
    }
    with pytest.raises(ValueError):
        _e(typ="plan.update", schritte=[])
    with pytest.raises(ValueError):
        _e(typ="plan.update", schritte=[{"id": "s1", "label": "X", "state": "halb"}])


def test_proposal_prueft_risiko_zerstoerung_und_optionen():
    e = _e(
        typ="proposal",
        id="v1",
        aktion="main mergen",
        risiko="medium",
        kontext="Branch grün",
        zerstoererisch=True,
        optionen=["once", "deny"],
    )
    assert (
        e["aktion"] == "main mergen" and e["optionen"] == "once,deny" and e["zerstoererisch"] == "1"
    )
    assert "zerstoererisch" not in _e(typ="proposal", id="v1", aktion="X", risiko="low")
    with pytest.raises(ValueError):
        _e(typ="proposal", id="v1", aktion="X", risiko="extrem")
    with pytest.raises(ValueError):
        _e(typ="proposal", aktion="X", risiko="low")
    with pytest.raises(ValueError):
        _e(typ="proposal", id="v1", aktion="X", risiko="low", optionen=["vielleicht"])


def test_ui_request_methode_und_entschaerfte_nutzlast():
    e = _e(
        typ="ui_request",
        id="u1",
        methode="confirm",
        nutzlast={"frage": "Mergen?", "api_key": "xyz"},
    )
    assert e["methode"] == "confirm"
    assert "xyz" not in e["nutzlast"] and '"api_key":"…"' in e["nutzlast"]
    without = _e(typ="ui_request", id="u1", methode="select")
    assert "nutzlast" not in without
    with pytest.raises(ValueError):
        _e(typ="ui_request", id="u1", methode="tanzen")


def test_usage_mit_tier_kontext_und_kosten():
    e = _e(
        typ="usage", modell="modell-70b", tier="normal", ctx=1234, ctx_max=32768, kosten_micro_eur=42
    )
    assert e["modell"] == "modell-70b" and e["tier"] == "normal"
    assert e["ctx"] == "1234" and e["ctx_max"] == "32768" and e["kosten_micro_eur"] == "42"
    assert "kosten_micro_eur" not in _e(typ="usage", modell="modell-70b", tier="heavy")
    with pytest.raises(ValueError):
        _e(typ="usage", modell="modell-70b", tier="riesig")
    with pytest.raises(ValueError):
        _e(typ="usage", modell="", tier="light")
    with pytest.raises(ValueError):
        _e(typ="usage", modell="modell-70b", tier="light", ctx=-1)


def test_error_kuerzt_nachricht_und_art():
    e = _e(typ="error", nachricht="x" * 900, art="rpc")
    assert len(e["nachricht"]) == a.NACHRICHT_MAX and e["nachricht"].endswith(a.KUERZUNG)
    assert e["art"] == "rpc"
    with pytest.raises(ValueError):
        _e(typ="error")


def test_ruhe_traegt_schalter_stufe_und_herkunft():
    """Der Ruhe-Schalter eines Runners: Form des Eintrags mit allen Feldern."""
    e = _e(
        typ="ruhe",
        an="1",
        pausiert="1",
        stufe="tief",
        quelle="schalter",
        grund="Feier\nabend",
        bis="2026-10-26T05:00:00.000Z",
        von="app",
    )
    assert e["typ"] == "ruhe"
    assert (e["an"], e["pausiert"], e["stufe"], e["quelle"], e["von"]) == ("1", "1", "tief", "schalter", "app")
    assert e["grund"] == "Feier abend"
    assert e["bis"] == "2026-10-26T05:00:00.000Z"
    assert all(isinstance(w, str) for w in e.values())


def test_ruhe_mit_wenig_angaben_nimmt_vorgaben():
    aus = _e(typ="ruhe", an=False, pausiert=False)
    assert (aus["an"], aus["pausiert"], aus["stufe"]) == ("0", "0", "normal")
    for fehlt in ("quelle", "grund", "bis", "von"):
        assert fehlt not in aus
    # Wahrheitswerte in jeder Schreibweise des Vertrags
    for wahr in (True, "1", 1):
        assert _e(typ="ruhe", an=wahr, pausiert=wahr)["an"] == "1"
    for falsch in (False, "0", 0):
        assert _e(typ="ruhe", an=falsch, pausiert=falsch)["pausiert"] == "0"


def test_ruhe_kuerzt_textfelder():
    e = _e(typ="ruhe", an="1", pausiert="1", grund="g" * 900, quelle="q" * 90, bis="b" * 90, von="v" * 90)
    assert len(e["grund"]) == a.GRUND_MAX and e["grund"].endswith(a.KUERZUNG)
    assert len(e["quelle"]) == 20 and len(e["bis"]) == 40 and len(e["von"]) == 40


def test_ruhe_lehnt_falsche_felder_ab():
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="1", pausiert="1", stufe="laut")
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="vielleicht", pausiert="0")
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="1", pausiert=None)
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="1", pausiert=2)
    with pytest.raises(ValueError):
        _e(typ="ruhe")
    # die allgemeinen Pflichtfelder gelten auch hier
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="1", pausiert="1", agent="!!!")
    with pytest.raises(ValueError):
        _e(typ="ruhe", an="1", pausiert="1", q=0)


def test_ruhe_ist_eine_bekannte_art_und_nur_diese():
    assert "ruhe" in a.ARTEN
    assert a.RUHE_STUFEN == ("normal", "tief")
    with pytest.raises(ValueError):
        _e(typ="Ruhe", an="1", pausiert="1")
    with pytest.raises(ValueError):
        _e(typ="ruhe.gesetzt", an="1", pausiert="1")


def test_alle_werte_sind_zeichenketten():
    beispiele = [
        _e(),
        _e(typ="part.updated", id="p1", pt="text", delta="Hallo"),
        _e(typ="usage", modell="modell", tier="light", ctx=1, ctx_max=2),
        _e(typ="error", nachricht="kaputt"),
    ]
    for e in beispiele:
        assert all(isinstance(w, str) for w in e.values())


def test_passen_kappt_den_ganzen_eintrag():
    e = {
        "t": "1",
        "v": "1",
        "typ": "plan.update",
        "a": "x",
        "s": "y",
        "q": "1",
        "schritte": "z" * 30_000,
    }
    r = a._passen(dict(e))
    assert sum(len(w) for w in r.values()) <= a.GESAMT_MAX
    assert r["schritte"].endswith(a.KUERZUNG) and len(r["schritte"]) < 30_000


def test_senden_schreibt_mit_obergrenze():
    r = MagicMock()
    r.xadd.return_value = "1719100000000-0"
    assert a.senden(
        r, {"agent": "agent", "sitzung": "sitz-1", "q": 1, "typ": "session.idle"}, jetzt_ms=JETZT_MS
    ) == ("1719100000000-0")
    r.xadd.assert_called_once()
    (strom, eintrag), kwargs = r.xadd.call_args
    assert strom == a.STROM
    assert eintrag["typ"] == "session.idle" and eintrag["t"] == str(JETZT_MS)
    assert kwargs == {"maxlen": a.MAXLEN, "approximate": True}


def test_senden_viele_nutzt_eine_pipeline():
    r = MagicMock()
    pipe = MagicMock()
    r.pipeline.return_value = pipe
    ereignisse = [
        {
            "agent": "agent",
            "sitzung": "sitz-1",
            "q": 1,
            "typ": "part.updated",
            "id": "p1",
            "pt": "text",
            "delta": "a",
        },
        {"agent": "agent", "sitzung": "sitz-1", "q": 2, "typ": "part.done", "id": "p1"},
    ]
    assert a.senden_viele(r, ereignisse, jetzt_ms=JETZT_MS) == 2
    assert pipe.xadd.call_count == 2
    pipe.execute.assert_called_once()

    leer = MagicMock()
    assert a.senden_viele(leer, []) == 0
    leer.pipeline.assert_not_called()


def test_senden_viele_prueft_vor_dem_schreiben():
    r = MagicMock()
    with pytest.raises(ValueError):
        a.senden_viele(
            r,
            [
                {"agent": "agent", "sitzung": "sitz-1", "q": 1, "typ": "session.idle"},
                {"agent": "agent", "sitzung": "sitz-1", "q": 2, "typ": "gibtsnicht"},
            ],
        )
    r.pipeline.assert_not_called()
