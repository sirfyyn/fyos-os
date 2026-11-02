"""ITSM des Kerns (Plugin ``itsm``): Ablage im Redis, Werkzeuge, Freigaben und die Form, die der Runner liest.

Redis ist ``fakeredis``. Die Felder von ``itsm.vorgang`` und ``itsm.wartend`` sind die, die die ITSM-Wache des Runners
(fyos-agent, ``itsm-wache.js``) auswertet: ``verlauf[{ts, ereignis, wer, text}]``, ``tickets[{id, zustaendig}]``, ein
Statuswechsel als ``waiting_approval→…`` vom Besitzer.
"""

from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")

from mcp_hub import vorgaenge as VG  # noqa: E402
from mcp_hub.plugins import vorgaenge_app  # noqa: E402
from mcp_hub.plugins.itsm import ItsmPlugin  # noqa: E402
from mcp_hub.registry import AUFRUFER  # noqa: E402

JA = {"bestaetigt": True}


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_VORGAENGE_URL", "FYOS_VORGAENGE_KOPF", "FYOS_BESITZER_AKTEUR", "FYOS_AGENT_ID", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    VG.ablage_anmelden(None)
    VG.dienst_anmelden(None)
    yield
    VG.ablage_anmelden(None)
    VG.dienst_anmelden(None)


@pytest.fixture()
def itsm():
    p = ItsmPlugin({"agent": "agent"}, redis=fakeredis.FakeRedis(decode_responses=True))
    p.register()
    return p


@pytest.fixture()
def oberflaeche():
    """Aufrufe wie über /hub/app-call (fyos-web): es schreibt der Besitzer."""
    marke = AUFRUFER.set("fyos-web")
    yield
    AUFRUFER.reset(marke)


def _antrag(itsm, titel="Platte tauschen"):
    t = itsm.call("anlegen", {"titel": titel, "art": "CHG", "beschreibung": "sdb ist müde", **JA})
    itsm.call("kommentieren", {"id": t["id"], "text": "Antrag: Platte heute Nacht tauschen", **JA})
    itsm.call("status_setzen", {"id": t["id"], "status": "waiting_approval", **JA})
    return t["id"]


# ── Einrichtung ─────────────────────────────────────────────────────────────────────────────────────


def test_ohne_redis_nicht_eingerichtet():
    p = ItsmPlugin()
    p.register()
    assert VG.angemeldete_ablage() is None
    assert p.health()["status"] == "nicht eingerichtet"
    r = p.call("wartend", {})
    assert r["ok"] is False and r["zustand"] == "nicht eingerichtet" and "REDIS_URL" in r["error"]


def test_meldet_sich_als_ablage_an_und_ab(itsm):
    q = VG.quelle()
    assert q.art == "ablage"
    assert itsm.health()["status"] == "healthy"
    itsm.shutdown()
    assert VG.quelle().art == "keine"


def test_ein_vorgangs_dienst_hat_vorrang(itsm, monkeypatch):
    """Mit Dienst reicht das Plugin durch (test_itsm_dienst.py); die Ablage bleibt angemeldet, aber nachrangig."""
    monkeypatch.setenv("FYOS_VORGAENGE_URL", "http://tickets.example:8080")
    h = itsm.health()
    assert h["status"] == "healthy" and h["weg"] == "dienst" and "tickets.example" in h["quelle"]
    assert VG.quelle().art == "dienst" and VG.angemeldete_ablage() is not None


def test_werkzeuge_und_kennzeichnung(itsm):
    d = {t.name: t for t in itsm.describe_tools()}
    assert set(d) == {"liste", "vorgang", "wartend", "anlegen", "kommentieren", "notiz", "status_setzen",
                      "freigabe_beantragen", "status", "freigeben", "ablehnen"}
    for name in ("liste", "vorgang", "wartend"):
        assert "read" in d[name].tags
    for name in ("anlegen", "kommentieren", "status_setzen", "freigeben", "ablehnen"):
        assert "write" in d[name].tags and "bestaetigt" in d[name].input_schema["properties"]
    for name in ("notiz", "freigabe_beantragen", "status"):
        assert "write" in d[name].tags and "bestaetigt" not in d[name].input_schema["properties"]
    for name in ("freigeben", "ablehnen", "status"):
        assert d[name].meta == {"ui": {"visibility": ["app"]}}
    for name in ("notiz", "freigabe_beantragen"):
        assert d[name].meta is None  # Werkzeuge des Agenten


# ── Anlegen, Lesen, Kommentieren ───────────────────────────────────────────────────────────────────


def test_schreiben_braucht_bestaetigung_und_zeigt_einen_plan(itsm):
    plan = itsm.call("anlegen", {"titel": "Backup prüfen", "__dry_run__": True})
    assert plan["dry_run"] is True and "Backup prüfen" in plan["would_execute"]
    with pytest.raises(ValueError, match="bestaetigt"):
        itsm.call("anlegen", {"titel": "Backup prüfen"})
    assert itsm.call("liste", {"status": "alle"})["anzahl"] == 0


def test_anlegen_liste_und_vorgang(itsm):
    a = itsm.call("anlegen", {"titel": "Drucker offline", **JA})
    b = itsm.call("anlegen", {"titel": "Router tauschen", "typ": "CHG", "prioritaet": "hoch", **JA})
    assert a["id"] == "INC-1" and b["id"] == "CHG-2"
    liste = itsm.call("liste", {})
    assert [v["id"] for v in liste["vorgaenge"]] == ["CHG-2", "INC-1"]  # zuletzt geändert zuerst
    assert itsm.call("liste", {"art": "CHG"})["anzahl"] == 1
    v = itsm.call("vorgang", {"id": "CHG-2"})
    assert v["titel"] == "Router tauschen" and v["art"] == "CHG" and v["prioritaet"] == "hoch"
    assert v["zustaendig"] == "agent" and v["melder"] == "agent" and v["status"] == "new"
    assert v["verlauf"][0]["ereignis"] == "created" and v["verlauf"][0]["wer"] == "agent"
    assert "in_progress" in v["folge_status"] and v["antwort"] is None


def test_kommentar_steht_im_verlauf_neueste_zuerst(itsm):
    t = itsm.call("anlegen", {"titel": "Mail kommt nicht an", **JA})
    itsm.call("kommentieren", {"id": t["id"], "text": "DNS geprüft", **JA})
    itsm.call("kommentieren", {"id": t["id"], "text": "MX fehlt", "wer": "helfer", **JA})
    v = itsm.call("vorgang", {"id": t["id"], "verlauf": 2})
    assert [(e["ereignis"], e["wer"], e["text"]) for e in v["verlauf"]] == [
        ("comment", "helfer", "MX fehlt"), ("comment", "agent", "DNS geprüft")]
    assert v["verlauf"][0]["ts"] > v["verlauf"][1]["ts"]


def test_unbekannter_vorgang_und_kaputte_kennung(itsm):
    with pytest.raises(ValueError, match="kein Vorgang"):
        itsm.call("vorgang", {"id": "INC-99"})
    with pytest.raises(ValueError, match="id"):
        itsm.call("vorgang", {"id": "../INC-1"})


# ── Freigaben ──────────────────────────────────────────────────────────────────────────────────────


def test_wartend_listet_freigaben_und_danach_nicht_mehr(itsm, oberflaeche):
    marke = AUFRUFER.set("mcp:runner")
    vid = _antrag(itsm)
    AUFRUFER.reset(marke)
    w = itsm.call("wartend", {})
    assert w["anzahl"] == 1 and w["tickets"][0]["id"] == vid and w["tickets"][0]["zustaendig"] == "agent"
    assert w["tickets"][0]["worauf"] == "freigabe" and w["andere_wartende"] == 0
    r = itsm.call("freigeben", {"id": vid, "begruendung": "ja, nach 22 Uhr", **JA})
    assert r["ok"] and r["status"] == "in_progress"
    assert itsm.call("wartend", {})["anzahl"] == 0
    v = itsm.call("vorgang", {"id": vid})
    neueste = v["verlauf"][0]
    assert neueste["ereignis"] == "updated" and neueste["wer"] == "besitzer"
    assert "waiting_approval→in_progress" in neueste["text"]
    assert v["verlauf"][1]["ereignis"] == "comment" and v["verlauf"][1]["wer"] == "besitzer"


def test_ablehnen_setzt_triage_und_zweite_antwort_ist_konflikt(itsm, oberflaeche):
    marke = AUFRUFER.set("mcp:runner")
    vid = _antrag(itsm)
    AUFRUFER.reset(marke)
    assert itsm.call("ablehnen", {"id": vid, **JA})["status"] == "triage"
    zweite = itsm.call("freigeben", {"id": vid, **JA})
    assert zweite["ok"] is False and zweite["zustand"] == "konflikt" and "bereits entschieden" in zweite["error"]


def test_agent_kann_nicht_als_besitzer_schreiben(itsm):
    vid = _antrag(itsm)
    with pytest.raises(ValueError, match="Besitzer"):
        itsm.call("kommentieren", {"id": vid, "text": "freigegeben", "wer": "besitzer", **JA})
    # selbst setzt der Agent den Status, aber nicht als Besitzer: der Runner erkennt darin keine Freigabe
    itsm.call("status_setzen", {"id": vid, "status": "in_progress", **JA})
    v = itsm.call("vorgang", {"id": vid})
    assert v["verlauf"][0]["wer"] == "agent"


def test_closed_nur_vom_besitzer(itsm):
    t = itsm.call("anlegen", {"titel": "Altlast", **JA})
    with pytest.raises(ValueError, match="closed"):
        itsm.call("status_setzen", {"id": t["id"], "status": "closed", **JA})
    marke = AUFRUFER.set("fyos-web")
    try:
        assert itsm.call("status_setzen", {"id": t["id"], "status": "closed", **JA})["status"] == "closed"
    finally:
        AUFRUFER.reset(marke)
    with pytest.raises(ValueError, match="closed"):
        itsm.call("status_setzen", {"id": t["id"], "status": "in_progress", **JA})


def test_expected_status_schuetzt_vor_veraltetem_stand(itsm):
    t = itsm.call("anlegen", {"titel": "Zertifikat", **JA})
    r = itsm.call("status_setzen", {"id": t["id"], "status": "resolved", "expected_status": "in_progress", "text": "fertig", **JA})
    assert r["ok"] is False and r["zustand"] == "konflikt" and r["status"] == "new"
    v = itsm.call("vorgang", {"id": t["id"]})
    assert [e["ereignis"] for e in v["verlauf"]] == ["created"]  # kein Kommentar an einem verworfenen Wechsel


def test_wartet_auf_besitzer_ohne_freigabe(itsm):
    itsm.call("anlegen", {"titel": "Welche Farbe?", "worauf": "besitzer", **JA})
    itsm.call("anlegen", {"titel": "Wartet auf Lieferung", "wartet_auf": "lieferant", **JA})
    w = itsm.call("wartend", {})
    assert [t["titel"] for t in w["tickets"]] == ["Welche Farbe?"] and w["andere_wartende"] == 1


def test_besitzer_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("FYOS_BESITZER_AKTEUR", "alex")
    p = ItsmPlugin(redis=fakeredis.FakeRedis(decode_responses=True))
    p.register()
    marke = AUFRUFER.set("fyos-web")
    try:
        t = p.call("anlegen", {"titel": "Frage", **JA})
        p.call("kommentieren", {"id": t["id"], "text": "Notiz", **JA})
    finally:
        AUFRUFER.reset(marke)
    assert p.call("vorgang", {"id": t["id"]})["verlauf"][0]["wer"] == "alex"
    assert p.call("vorgang", {"id": t["id"]})["zustaendig"] is None


# ── Werkzeuge, die es auf beiden Wegen gibt (hier: Ablage) ─────────────────────────────────────────


VORHABEN = {"vorhaben": "Platte sdb im Pool tank tauschen und Resilver abwarten", "wirkung": "Pool 6 h langsamer",
            "ziel": "nas", "rueckweg": "alte Platte wieder einsetzen"}


def test_notiz_ohne_bestaetigung_als_agent(itsm):
    t = itsm.call("anlegen", {"titel": "Backup langsam", **JA})
    r = itsm.call("notiz", {"id": t["id"], "text": "Durchsatz gemessen: 40 MB/s"})
    assert r["ok"] and r["von"] == "agent" and r["vorgang"] == t["id"]
    v = itsm.call("vorgang", {"id": t["id"]})
    assert (v["verlauf"][0]["ereignis"], v["verlauf"][0]["wer"]) == ("comment", "agent")
    assert itsm.call("notiz", {"id": t["id"], "text": "x", "__dry_run__": True})["dry_run"] is True
    with pytest.raises(ValueError, match="Besitzer"):
        itsm.call("notiz", {"id": t["id"], "text": "x", "wer": "besitzer"})


def test_freigabe_beantragen_auf_der_ablage(itsm):
    t = itsm.call("anlegen", {"titel": "Platte tauschen", "art": "CHG", "beschreibung": "sdb müde", **JA})
    with pytest.raises(ValueError, match="in_progress"):
        itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN})
    itsm.call("status_setzen", {"id": t["id"], "status": "in_progress", **JA})
    r = itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN})
    assert r["ok"] and r["status"] == "waiting_approval" and len(r["pruefsumme"]) == 12
    v = itsm.call("vorgang", {"id": t["id"]})
    assert v["status"] == "waiting_approval" and v["wartet_auf"] == "besitzer"
    assert v["beschreibung"].startswith(f"## Freigabe angefragt (Prüfsumme {r['pruefsumme']})")
    assert v["beschreibung"].endswith("sdb müde")
    assert v["verlauf"][0]["ereignis"] == "comment" and v["verlauf"][1]["ereignis"] == "updated"
    assert itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN})["idempotent"] is True
    with pytest.raises(ValueError, match="andere Freigabe"):
        itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN, "beleg": "SMART-Werte"})
    assert [x["id"] for x in itsm.call("wartend", {})["tickets"]] == [t["id"]]


def test_freigabe_beantragen_nur_am_eigenen_vorgang_und_mit_allen_angaben(itsm):
    t = itsm.call("anlegen", {"titel": "Fremd", "zustaendig": "helfer", "status": "in_progress", **JA})
    with pytest.raises(ValueError, match="gehört nicht agent"):
        itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN})
    with pytest.raises(ValueError, match="kommen zusammen"):
        itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN, "risiko": "high"})
    with pytest.raises(ValueError, match="Sätze"):
        itsm.call("freigabe_beantragen", {"id": t["id"], **VORHABEN, "risiko": "high", "zerstoererisch": True,
                                          "kontext": "Nur ein Satz."})


def test_status_des_besitzers_mit_trockenlauf(itsm, oberflaeche):
    marke = AUFRUFER.set("mcp:runner")
    t = itsm.call("anlegen", {"titel": "Frage an dich", "worauf": "besitzer", **JA})
    AUFRUFER.reset(marke)
    plan = itsm.call("status", {"id": t["id"], "status": "resolved"})
    assert plan["trockenlauf"] is True and plan["erlaubt"] is True and plan["von"] == "new"
    assert "nicht mehr auf dich" in " ".join(plan["wirkung"])
    with pytest.raises(ValueError, match="expected_status"):
        itsm.call("status", {"id": t["id"], "status": "resolved", "ausfuehren": True})
    r = itsm.call("status", plan["ausfuehren_mit"])
    assert r["ergebnis"] == "gesetzt" and r["bestaetigt"] is True
    v = itsm.call("vorgang", {"id": t["id"]})
    assert v["status"] == "resolved" and v["wartet_auf"] is None and v["verlauf"][0]["wer"] == "besitzer"
    with pytest.raises(ValueError, match="inzwischen"):
        itsm.call("status", plan["ausfuehren_mit"])


# ── Über den Vertrag (vorgaenge.quelle) und die App „Vorgänge“ ─────────────────────────────────────


def test_vertrag_ueber_die_ablage(itsm):
    q = VG.quelle()
    t = q.anlegen("Backup prüfen", "nachts", status="waiting_approval", actor="agent")
    assert t["id"] == "INC-1" and t["status"] == "waiting_approval" and t["waiting_for"] == "besitzer"
    assert [x["id"] for x in q.freigaben()] == ["INC-1"]
    q.kommentieren("INC-1", "ja", actor="besitzer")
    with pytest.raises(VG.VorgangKonflikt):
        q.aendern("INC-1", status="in_progress", expected_status="new", actor="besitzer")
    neu = q.aendern("INC-1", status="in_progress", expected_status="waiting_approval", actor="besitzer")
    assert neu["status"] == "in_progress" and neu["waiting_for"] == ""
    assert q.verlauf("INC-1", grenze=1)[0]["detail"] == "status waiting_approval→in_progress"
    with pytest.raises(VG.VorgangFehlt):
        q.holen("INC-42")
    status, d = q.roh("GET", "/tickets?status=in_progress")
    assert status == 200 and [x["id"] for x in d["tickets"]] == ["INC-1"]


def test_app_vorgaenge_zeigt_und_beantwortet_freigaben(itsm):
    vid = _antrag(itsm)
    app = vorgaenge_app.VorgaengePlugin()
    zeilen = app.call("zeigen", {})["vorgaenge"]
    assert [z["id"] for z in zeilen] == [vid] and zeilen[0]["status"] == "waiting_approval"
    d = app.call("lesen", {"id": vid})
    assert d["antwort"] == "freigabe" and d["art"] == "CHG" and d["folge_status"] == []
    assert d["verlauf"][0]["ereignis"] == "updated"
    plan = app.call("entscheiden", {"id": vid, "entscheidung": "erteilt", "__dry_run__": True})
    assert plan["dry_run"] is True
    r = app.call("entscheiden", {"id": vid, "entscheidung": "erteilt", "begruendung": "passt", **JA})
    assert r["ok"] and r["vorgang"]["status"] == "in_progress"
    v = itsm.call("vorgang", {"id": vid})
    assert v["verlauf"][0]["wer"] == "besitzer" and "waiting_approval→in_progress" in v["verlauf"][0]["text"]
    assert app.call("entscheiden", {"id": vid, "entscheidung": "abgelehnt", **JA})["zustand"] == "konflikt"
    r = app.call("status", {"id": vid, "status": "resolved", "expected_status": "in_progress", **JA})
    assert r["ok"] and itsm.call("vorgang", {"id": vid})["status"] == "resolved"
    app.call("kommentieren", {"id": vid, "text": "danke", **JA})
    assert itsm.call("vorgang", {"id": vid})["verlauf"][0]["wer"] == "besitzer"
