"""MCP Tasks im Hub (docs/current/MCP-TASKS.md): Kern, REST und — mit mcp 2.x — der MCP-Weg 2026-07-28.

Kein Backend, kein Cluster: Attrappe-Werkzeuge mit Ereignissen statt Wartezeiten, Speicher im Prozess statt Redis.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time

import pytest

pytest.importorskip("starlette.testclient")

from starlette.testclient import TestClient  # noqa: E402

from mcp_hub import aufgaben as A  # noqa: E402
from mcp_hub import registry as hub_registry  # noqa: E402
from mcp_hub import server as hub_server  # noqa: E402
from mcp_hub.ansicht import Ablage  # noqa: E402
from mcp_hub.plugin import HubPlugin, ToolDescriptor  # noqa: E402
from mcp_hub.protokolle import VERSION_SCHLUESSEL  # noqa: E402

V2 = hub_server._SDK_V2
nur_v2 = pytest.mark.skipif(not V2, reason="2026-07-28 und die Erweiterungsschnittstelle kennt erst mcp 2.x")


class _Speicher(Ablage):
    """Ablage ohne Redis: alles im Prozess."""

    def redis(self):
        return None


def warten(bedingung, frist=20.0):
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture()
def aufgaben():
    return A.Aufgaben(_Speicher(), instanz="test")


# ═══ Kern ═══════════════════════════════════════════════════════════════════════════════════════════


def test_erklaert_huelle_und_kurzform():
    assert A.erklaert({"aufgabe": True})
    assert A.erklaert({"_meta": {A.HUELLE_FAEHIGKEITEN: {"extensions": {A.ERWEITERUNG: {}}}}})
    assert A.erklaert({A.HUELLE_FAEHIGKEITEN: {"extensions": {A.ERWEITERUNG: {}}}})
    assert not A.erklaert({"aufgabe": False})
    assert not A.erklaert({"_meta": {A.HUELLE_FAEHIGKEITEN: {"extensions": {"anderes/x": {}}}}})
    assert not A.erklaert({"_meta": {A.HUELLE_FAEHIGKEITEN: {}}})
    assert not A.erklaert(None) and not A.erklaert("aufgabe")


def test_anlegen_und_abholen(aufgaben):
    los = threading.Event()

    def lauf():
        los.wait(5)
        return {"content": [{"type": "text", "text": "fertig"}]}

    t = aufgaben.start("medien.bild", lauf, "ich")
    assert t["resultType"] == "task" and t["status"] == "working"
    assert len(t["taskId"]) >= 24 and t["pollIntervalMs"] == A.POLL_MS and t["ttlMs"] == A.TTL_VORGABE_MS
    assert t["createdAt"].endswith("Z")
    erst = aufgaben.lesen(t["taskId"], "ich")
    assert erst["resultType"] == "complete" and erst["status"] == "working" and "result" not in erst
    los.set()
    assert warten(lambda: aufgaben.lesen(t["taskId"], "ich")["status"] == "completed")
    fertig = aufgaben.lesen(t["taskId"], "ich")
    assert fertig["result"]["content"][0]["text"] == "fertig"


def test_ausnahme_wird_failed_mit_jsonrpc_fehler(aufgaben):
    def lauf():
        raise RuntimeError("kaputt")

    t = aufgaben.start("x.y", lauf, "ich")
    assert warten(lambda: aufgaben.lesen(t["taskId"], "ich")["status"] == "failed")
    d = aufgaben.lesen(t["taskId"], "ich")
    assert d["error"]["code"] == A.FEHLER_INTERN and "kaputt" in d["error"]["message"] and "result" not in d


def test_nur_der_anleger_darf_und_fremde_kennung_ist_unbekannt(aufgaben):
    los = threading.Event()
    t = aufgaben.start("x.y", lambda: (los.wait(5), {})[1], "alice")
    for fn in (
        lambda: aufgaben.lesen(t["taskId"], "bob"),
        lambda: aufgaben.abbrechen(t["taskId"], "bob"),
        lambda: aufgaben.aktualisieren(t["taskId"], "bob", {}),
    ):
        with pytest.raises(A.AufgabenFehler) as e:
            fn()
        assert e.value.code == A.FEHLER_UNBEKANNT and e.value.status == 404
    with pytest.raises(A.AufgabenFehler) as e2:  # echt unbekannt: gleiche Antwort wie fremd
        aufgaben.lesen("gibt-es-nicht", "alice")
    assert e2.value.message == e.value.message
    assert aufgaben.lesen(t["taskId"], "alice")["status"] == "working"
    los.set()


def test_obergrenze_je_akteur_und_gesamt(aufgaben, monkeypatch):
    los = threading.Event()
    kennungen = [aufgaben.start("x.y", lambda: (los.wait(5), {})[1], "alice")["taskId"] for _ in range(A.MAX_OFFEN_AKTEUR)]
    with pytest.raises(A.AufgabenFehler) as e:
        aufgaben.start("x.y", lambda: {}, "alice")
    assert e.value.code == A.FEHLER_ZU_VIELE and e.value.status == 429
    aufgaben.start("x.y", lambda: (los.wait(5), {})[1], "bob")  # anderer Akteur: frei
    aufgaben.abbrechen(kennungen[0], "alice")  # abgebrochen zaehlt nicht mehr als offen
    aufgaben.start("x.y", lambda: {}, "alice")
    monkeypatch.setattr(A, "MAX_OFFEN_GESAMT", 5)  # alice 4 + bob 1 offen
    with pytest.raises(A.AufgabenFehler):
        aufgaben.start("x.y", lambda: {}, "carol")
    los.set()


def test_ttl_wird_begrenzt(aufgaben):
    assert aufgaben.start("x.y", lambda: {}, "a", ttl_ms=10**12)["ttlMs"] == A.TTL_MAX_MS
    assert aufgaben.start("x.y", lambda: {}, "a", ttl_ms=5)["ttlMs"] == 1000


def test_abbruch_ist_kooperativ_und_ein_spaetes_ergebnis_zaehlt_nicht(aufgaben):
    los = threading.Event()
    gesehen = {}

    def lauf():
        h = A.aktuelle()
        los.wait(5)
        gesehen["abgebrochen"] = h.abgebrochen()
        return {"content": [{"type": "text", "text": "zu spaet"}]}

    t = aufgaben.start("x.y", lauf, "a")
    assert aufgaben.abbrechen(t["taskId"], "a") == {"resultType": "complete"}
    assert aufgaben.lesen(t["taskId"], "a")["status"] == "cancelled"
    los.set()
    assert warten(lambda: "abgebrochen" in gesehen)
    time.sleep(0.05)
    d = aufgaben.lesen(t["taskId"], "a")
    assert gesehen["abgebrochen"] is True and d["status"] == "cancelled" and "result" not in d
    assert aufgaben.abbrechen(t["taskId"], "a") == {"resultType": "complete"}  # nochmal: leere Antwort, kein Fehler


def test_endgueltig_bleibt_endgueltig(aufgaben):
    t = aufgaben.start("x.y", lambda: {"ok": True}, "a")
    assert warten(lambda: aufgaben.lesen(t["taskId"], "a")["status"] == "completed")
    aufgaben.abbrechen(t["taskId"], "a")
    assert aufgaben.lesen(t["taskId"], "a")["status"] == "completed"


def test_eingabe_input_required_und_update(aufgaben):
    def lauf():
        antwort = A.aktuelle().eingabe(
            "bestaetigung",
            {"message": "Wirklich?", "requestedSchema": {"type": "object", "properties": {"ja": {"type": "boolean"}}}},
        )
        return {"content": [{"type": "text", "text": json.dumps(antwort)}]}

    t = aufgaben.start("x.frage", lauf, "a")
    assert warten(lambda: aufgaben.lesen(t["taskId"], "a")["status"] == "input_required")
    d = aufgaben.lesen(t["taskId"], "a")
    req = d["inputRequests"]["bestaetigung"]
    assert req["method"] == "elicitation/create" and req["params"]["message"] == "Wirklich?"
    assert req["params"]["requestedSchema"]["properties"]["ja"]["type"] == "boolean"
    # Unbekannte Schluessel werden uebergangen, die Aufgabe bleibt wartend
    aufgaben.aktualisieren(t["taskId"], "a", {"anderes": {"action": "accept"}})
    assert aufgaben.lesen(t["taskId"], "a")["status"] == "input_required"
    aufgaben.aktualisieren(t["taskId"], "a", {"bestaetigung": {"action": "accept", "content": {"ja": True}}})
    assert warten(lambda: aufgaben.lesen(t["taskId"], "a")["status"] == "completed")
    text = aufgaben.lesen(t["taskId"], "a")["result"]["content"][0]["text"]
    assert json.loads(text) == {"action": "accept", "content": {"ja": True}}
    with pytest.raises(A.AufgabenFehler):  # keine Karte
        aufgaben.aktualisieren(t["taskId"], "a", ["x"])


def test_eingabe_frist_wird_failed(aufgaben):
    def lauf():
        A.aktuelle().eingabe("k", {"message": "?"}, frist_s=0.2)

    t = aufgaben.start("x.frage", lauf, "a")
    assert warten(lambda: aufgaben.lesen(t["taskId"], "a")["status"] == "failed")
    assert "Frist" in aufgaben.lesen(t["taskId"], "a")["error"]["message"]


def test_abbruch_waehrend_der_eingabe_weckt_den_faden(aufgaben):
    ende = threading.Event()

    def lauf():
        try:
            A.aktuelle().eingabe("k", {"message": "?"})
        finally:
            ende.set()

    t = aufgaben.start("x.frage", lauf, "a")
    assert warten(lambda: aufgaben.lesen(t["taskId"], "a")["status"] == "input_required")
    aufgaben.abbrechen(t["taskId"], "a")
    assert ende.wait(5)


def test_verwaiste_aufgabe_nach_neustart_wird_failed():
    speicher = _Speicher()
    alt = A.Aufgaben(speicher, instanz="alt")
    los = threading.Event()
    t = alt.start("x.y", lambda: (los.wait(5), {})[1], "a")
    neu = A.Aufgaben(speicher, instanz="neu")  # anderer Pod, Lebenszeichen von „alt“ vorhanden
    assert neu.lesen(t["taskId"], "a")["status"] == "working"
    speicher.setzen("hub:aufgaben:lebt:alt", "x", 1)
    speicher._speicher["hub:aufgaben:lebt:alt"] = (0.0, "x")  # abgelaufen
    d = neu.lesen(t["taskId"], "a")
    assert d["status"] == "failed" and "neu gestartet" in d["error"]["message"]
    los.set()


def test_liste_zeigt_nur_eigene_ohne_ergebnis(aufgaben):
    a = aufgaben.start("m.bild", lambda: {"x": 1}, "alice")
    aufgaben.start("m.bild", lambda: {"x": 2}, "bob")
    assert warten(lambda: aufgaben.lesen(a["taskId"], "alice")["status"] == "completed")
    liste = aufgaben.liste("alice")
    assert [x["taskId"] for x in liste] == [a["taskId"]] and "result" not in liste[0]


def test_ergebnis_als_aufruf_kennzeichnet_fehler():
    ok = A.ergebnis_als_aufruf({"ok": True, "a": 1})
    assert ok["structuredContent"] == {"ok": True, "a": 1} and "isError" not in ok
    assert A.ergebnis_als_aufruf({"ok": False, "error": "x"})["isError"] is True


# ═══ Hub: REST und MCP ════════════════════════════════════════════════════════════════════════════


_FREI = threading.Event()


class _Att(HubPlugin):
    """Attrappe: ein langes, ein fragendes, ein kaputtes und ein schnelles Werkzeug."""

    name = "att"

    def register(self) -> None:
        pass

    def describe_tools(self):
        leer = {"type": "object", "properties": {"n": {"type": "integer"}}}
        return [
            ToolDescriptor(name="lang", description="lang", input_schema=leer, tags=["read"], aufgabe=True),
            ToolDescriptor(name="frage", description="fragt", input_schema=leer, tags=["read"], aufgabe=True),
            ToolDescriptor(name="kaputt", description="kaputt", input_schema=leer, tags=["read"], aufgabe=True),
            ToolDescriptor(name="schnell", description="schnell", input_schema=leer, tags=["read"]),
        ]

    def call(self, method, args):
        if method == "lang":
            _FREI.wait(10)
            return {"ok": True, "fertig": True, "n": args.get("n")}
        if method == "frage":
            a = A.aktuelle()
            antwort = a.eingabe("ok", {"message": "Weiter?", "requestedSchema": {"type": "object"}}) if a else {"action": "sync"}
            return {"ok": True, "antwort": antwort}
        if method == "kaputt":
            raise RuntimeError("Backend weg")
        return {"ok": True, "schnell": True}


_KONFIG = str(pathlib.Path(__file__).resolve().parents[1] / "config_example.yaml")
_KOPF = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture()
def hub(monkeypatch):
    from mcp_hub import ansicht

    monkeypatch.setattr(A.AUFGABEN, "ablage", _Speicher())
    monkeypatch.setattr(ansicht, "ABLAGE", _Speicher())  # die kurze Ansicht misst ueber Redis
    A.AUFGABEN._laufend.clear()
    _FREI.clear()
    if hasattr(hub_server.mcp, "_session_manager"):
        hub_server.mcp._session_manager = None  # noqa: SLF001
    app = hub_server.build_app(_KONFIG)
    hub_registry._register_one(hub_server._REGISTRY, "att", _Att())
    with TestClient(app, follow_redirects=False) as c:
        c.mount = (hub_server._CONFIG.path if hub_server._CONFIG else "/mcp") + "/"
        yield c
    _FREI.set()
    time.sleep(0.05)
    # Der Sitzungsverwalter des SDK darf pro Instanz nur einmal laufen; der nächste Test (test_betriebsprobe) bekommt einen frischen.
    if hasattr(hub_server.mcp, "_session_manager"):
        hub_server.mcp._session_manager = None  # noqa: SLF001


def rest(hub, pfad, koerper, akteur="rest-test"):
    return hub.post(pfad, json=koerper, headers={"X-Hub-Caller": akteur})


def test_rest_ohne_erklaerung_bleibt_synchron(hub):
    _FREI.set()
    r = rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {"n": 3}})
    assert r.status_code == 200 and r.json()["result"]["fertig"] is True


def test_rest_mit_erklaerung_liefert_kennung_und_ergebnis(hub):
    r = rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {"n": 7}, "aufgabe": True, "ansicht": "kurz"})
    assert r.status_code == 202, r.text
    t = r.json()
    assert t["ok"] and t["resultType"] == "task" and t["status"] == "working" and t["taskId"]
    g = rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()
    assert g["status"] == "working" and g["resultType"] == "complete"
    _FREI.set()
    assert warten(lambda: rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()["status"] != "working"), rest(
        hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}
    ).text
    g = rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()
    assert g["status"] == "completed", g
    assert g["result"]["ok"] is True and g["result"]["result"]["n"] == 7  # die Gestalt von /hub/call
    liste = hub.get("/hub/aufgaben/liste", headers={"X-Hub-Caller": "rest-test"}).json()
    assert [x["taskId"] for x in liste["aufgaben"]] == [t["taskId"]]


def test_rest_nicht_taskfaehig_bleibt_synchron_auch_mit_erklaerung(hub):
    r = rest(hub, "/hub/call", {"tool": "att.schnell", "arguments": {}, "aufgabe": True})
    assert r.status_code == 200 and r.json()["result"]["schnell"] is True


def test_rest_dry_run_bleibt_synchron(hub):
    _FREI.set()
    r = rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {"__dry_run__": True}, "aufgabe": True})
    assert r.status_code != 202


def test_rest_fremder_akteur_und_unbekannt_gleich_404(hub):
    t = rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {}, "aufgabe": True}, akteur="alice").json()
    fremd = rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}, akteur="bob")
    unbek = rest(hub, "/hub/aufgaben/get", {"taskId": "nein"}, akteur="bob")
    assert fremd.status_code == unbek.status_code == 404 and fremd.json()["error"] == unbek.json()["error"]
    assert rest(hub, "/hub/aufgaben/cancel", {"taskId": t["taskId"]}, akteur="bob").status_code == 404
    assert rest(hub, "/hub/aufgaben/cancel", {"taskId": t["taskId"]}, akteur="alice").json()["ok"] is True
    assert rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}, akteur="alice").json()["status"] == "cancelled"
    assert rest(hub, "/hub/aufgaben/get", {}, akteur="alice").status_code == 400


def test_rest_input_required_und_antwort(hub):
    t = rest(hub, "/hub/call", {"tool": "att.frage", "arguments": {}, "aufgabe": True}).json()
    assert warten(lambda: rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()["status"] == "input_required")
    g = rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()
    assert g["inputRequests"]["ok"]["params"]["message"] == "Weiter?"
    u = rest(hub, "/hub/aufgaben/update", {"taskId": t["taskId"], "inputResponses": {"ok": {"action": "accept"}}})
    assert u.status_code == 200 and u.json()["ok"]
    assert warten(lambda: rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()["status"] == "completed")
    assert rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()["result"]["result"]["antwort"]["action"] == "accept"


def test_rest_werkzeugfehler_ist_completed_mit_ok_false(hub):
    t = rest(hub, "/hub/call", {"tool": "att.kaputt", "arguments": {}, "aufgabe": True}).json()
    assert warten(lambda: rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()["status"] == "completed")
    g = rest(hub, "/hub/aufgaben/get", {"taskId": t["taskId"]}).json()
    assert g["result"]["ok"] is False and "Backend weg" in g["result"]["error"]


def test_rest_zu_viele_offene_gibt_429(hub):
    for _ in range(A.MAX_OFFEN_AKTEUR):
        assert rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {}, "aufgabe": True}).status_code == 202
    r = rest(hub, "/hub/call", {"tool": "att.lang", "arguments": {}, "aufgabe": True})
    assert r.status_code == 429 and r.json()["code"] == A.FEHLER_ZU_VIELE


def test_schema_und_suche_nennen_den_hinweis(hub):
    assert hub_registry.tool_schema(hub_server._REGISTRY, "att.lang")["aufgabe"] is True
    assert "aufgabe" not in hub_registry.tool_schema(hub_server._REGISTRY, "att.schnell")
    # Vorgabe: ohne ausdruecklichen Hinweis gibt es nie eine Aufgabe; die mitgelieferten Plugins melden ihn nicht.
    assert ToolDescriptor(name="x", description="d", input_schema={}).aufgabe is False
    from mcp_hub.plugins.werkstatt import WerkstattPlugin
    assert not any(d.aufgabe for d in WerkstattPlugin().describe_tools())


# ── MCP 2026-07-28 ─────────────────────────────────────────────────────────────────────────────────


def modern(methode, params=None, mit_erweiterung=True, name=None, version="2026-07-28"):
    par = dict(params or {})
    faehig = {"extensions": {A.ERWEITERUNG: {}}} if mit_erweiterung else {}
    par["_meta"] = {
        VERSION_SCHLUESSEL: version,
        A.HUELLE_FAEHIGKEITEN: faehig,
        "io.modelcontextprotocol/clientInfo": {"name": "aufgabenprobe", "version": "1"},
    }
    kopf = {**_KOPF, "MCP-Protocol-Version": version, "Mcp-Method": methode, "X-Hub-Caller": "mcp-test"}
    if name:
        kopf["Mcp-Name"] = name
    return {"jsonrpc": "2.0", "id": 1, "method": methode, "params": par}, kopf


def senden(hub, bauteil):
    body, kopf = bauteil
    r = hub.post(hub.mount, json=body, headers=kopf)
    text = r.text.strip()
    if text.startswith(("event:", "data:")):
        text = next(z[6:] for z in text.splitlines() if z.startswith("data: "))
    return r, (json.loads(text) if text else None)


def aufruf(hub, tool, arguments=None, **kw):
    return senden(
        hub,
        modern(
            "tools/call",
            {"name": "hub__call_tool", "arguments": {"tool": tool, "arguments": arguments or {}}},
            name="hub__call_tool",
            **kw,
        ),
    )


@nur_v2
def test_discover_meldet_die_erweiterung(hub):
    r, d = senden(hub, modern("server/discover", mit_erweiterung=False))
    assert r.status_code == 200, r.text
    assert A.ERWEITERUNG in d["result"]["capabilities"]["extensions"]


@nur_v2
def test_mcp_mit_erweiterung_liefert_createtaskresult_und_ergebnis(hub):
    r, d = aufruf(hub, "att.lang", {"n": 5})
    assert r.status_code == 200, r.text
    t = d["result"]
    assert t["resultType"] == "task" and t["status"] == "working" and t["taskId"] and t["ttlMs"] and t["pollIntervalMs"]
    r, g = senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))
    assert r.status_code == 200, r.text
    assert g["result"]["status"] == "working" and g["result"]["resultType"] == "complete"
    _FREI.set()

    def fertig():
        return senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))[1]["result"]["status"] == "completed"

    assert warten(fertig)
    res = senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))[1]["result"]["result"]
    inhalt = res["structuredContent"]
    assert inhalt["ok"] is True and inhalt["result"]["n"] == 5  # dasselbe, was hub__call_tool synchron geliefert haette


@nur_v2
def test_mcp_ohne_erweiterung_bleibt_synchron(hub):
    _FREI.set()
    r, d = aufruf(hub, "att.lang", {"n": 1}, mit_erweiterung=False)
    assert r.status_code == 200, r.text
    assert d["result"].get("resultType") != "task" and d["result"]["structuredContent"]["result"]["fertig"] is True


@nur_v2
def test_mcp_nicht_taskfaehiges_werkzeug_bleibt_synchron(hub):
    r, d = aufruf(hub, "att.schnell")
    assert d["result"].get("resultType") != "task" and d["result"]["structuredContent"]["result"]["schnell"] is True


@nur_v2
def test_mcp_handshake_zeitalter_bekommt_nie_eine_aufgabe(hub):
    _FREI.set()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "hub__call_tool", "arguments": {"tool": "att.lang", "arguments": {}}},
    }
    kopf = {**_KOPF, "MCP-Protocol-Version": "2025-11-25"}
    r = hub.post(hub.mount, json=body, headers=kopf)
    assert r.status_code == 200, r.text
    text = r.text.strip()
    if text.startswith(("event:", "data:")):
        text = next(z[6:] for z in text.splitlines() if z.startswith("data: "))
    assert json.loads(text)["result"]["structuredContent"]["result"]["fertig"] is True


@nur_v2
def test_mcp_tasks_methoden_gibt_es_im_handshake_zeitalter_nicht(hub):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"taskId": "x"}}
    r = hub.post(hub.mount, json=body, headers={**_KOPF, "MCP-Protocol-Version": "2025-11-25"})
    assert r.status_code in (200, 400, 404)
    assert "error" in r.text and "-32601" in r.text or "Method not found" in r.text


@nur_v2
def test_mcp_cancel_update_und_rechte(hub):
    t = aufruf(hub, "att.frage")[1]["result"]
    assert warten(lambda: senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))[1]["result"]["status"] == "input_required")
    g = senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))[1]["result"]
    assert g["inputRequests"]["ok"]["method"] == "elicitation/create"
    # fremder Akteur: gleiche Antwort wie unbekannt
    body, kopf = modern("tasks/get", {"taskId": t["taskId"]})
    kopf["X-Hub-Caller"] = "fremd"
    r = hub.post(hub.mount, json=body, headers=kopf)
    assert "nicht gefunden" in r.text
    u = senden(hub, modern("tasks/update", {"taskId": t["taskId"], "inputResponses": {"ok": {"action": "decline"}}}))[1]
    assert u["result"]["resultType"] == "complete"
    assert warten(lambda: senden(hub, modern("tasks/get", {"taskId": t["taskId"]}))[1]["result"]["status"] == "completed")
    zwei = aufruf(hub, "att.lang")[1]["result"]
    c = senden(hub, modern("tasks/cancel", {"taskId": zwei["taskId"]}))[1]
    assert c["result"]["resultType"] == "complete"
    assert senden(hub, modern("tasks/get", {"taskId": zwei["taskId"]}))[1]["result"]["status"] == "cancelled"
