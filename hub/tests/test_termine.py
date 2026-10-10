"""Termine für Plugins (``mcp_hub.termine``): Termin-Dienst, Kalender-Plugin oder keine Quelle.

Der Dienst ist ein kleiner HTTP-Server im Thread (kein Netz nach außen); das Kalender-Plugin eine Attrappe im Speicher.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mcp_hub import termine as T
from mcp_hub import vorgaenge
from mcp_hub.termine import NichtEingerichtet, QuelleFehler

UTC = timezone.utc
VON = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
BIS = VON + timedelta(days=2)  # der 12. und der 13. Oktober


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_TERMINE_URL", "FYOS_TERMINE_KOPF"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FYOS_ZEITZONE", "UTC")  # ganztägige Termine und Zeiten ohne Versatz: unabhängig vom Rechner
    # Die Attrappe läuft auf 127.0.0.1; ein Proxy der Umgebung soll sie nicht umleiten.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    T.ablage_anmelden(None)
    T.dienst_anmelden(None)
    yield
    T.ablage_anmelden(None)
    T.dienst_anmelden(None)


# ── Attrappen ───────────────────────────────────────────────────────────────────────────────────────────
class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:  # abgebrochene Anfragen sind hier gewollt
        return None


class Attrappe:
    """Ein HTTP-Dienst im Thread. ``routen`` bildet ``(Methode, Pfad)`` auf eine Antwort ab: ``(Status, Inhalt)``,
    ``(Status, Inhalt, Kopfzeilen)`` oder eine Funktion, die den Aufruf bekommt und so etwas liefert. Inhalt: ``dict`` oder
    ``list`` (JSON) oder ``str`` (roh)."""

    def __init__(self) -> None:
        self.routen: dict[tuple[str, str], Any] = {}
        self.aufrufe: list[dict[str, Any]] = []
        attrappe = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return None

            def _bedienen(self) -> None:
                teile = urllib.parse.urlsplit(self.path)
                laenge = int(self.headers.get("Content-Length") or 0)
                rumpf = self.rfile.read(laenge) if laenge else b""
                aufruf = {
                    "methode": self.command,
                    "pfad": teile.path,
                    "abfrage": dict(urllib.parse.parse_qsl(teile.query)),
                    "kopf": {k.lower(): v for k, v in self.headers.items()},
                    "rumpf": json.loads(rumpf) if rumpf else None,
                }
                attrappe.aufrufe.append(aufruf)
                route = attrappe.routen.get((self.command, teile.path), (404, {"detail": "nicht gefunden"}))
                antwort = route(aufruf) if callable(route) else route
                status, inhalt, *rest = antwort
                kopf = rest[0] if rest else {}
                daten = (json.dumps(inhalt) if isinstance(inhalt, (dict, list)) else str(inhalt)).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(daten)))
                for k, v in kopf.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(daten)

            do_GET = do_POST = do_PATCH = do_DELETE = _bedienen

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._faden = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)

    def __enter__(self) -> "Attrappe":
        self._faden.start()
        return self

    def __exit__(self, *a: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def dienst():
    with Attrappe() as a:
        yield a


def _ereignis(**felder: Any) -> dict[str, Any]:
    return {"id": "e1", "title": "Zahnarzt", "start": "2026-10-12T09:00:00+00:00", "end": "2026-10-12T10:00:00+00:00",
            "all_day": False, "location": "Praxis", "calendar_id": "primary", "calendar_name": "Privat",
            "source": "google", **felder}


def _ereignisse(*liste: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {"service": "kalender", "status": "live", "events": list(liste), "_stub": False}


class Kalenderablage:
    """Ein Kalender-Plugin im Speicher."""

    name = "kalender"

    def __init__(self, termine: list[dict[str, Any]] | None = None) -> None:
        self.termine = termine or []
        self.aufrufe: list[tuple[datetime, datetime, str | None]] = []
        self.angelegt: list[dict[str, Any]] = []
        self.fehler: Exception | None = None

    def ablage_kalender(self) -> list[dict[str, Any]]:
        if self.fehler:
            raise self.fehler
        return [{"id": "privat", "name": "Privat", "konto": "icloud", "schreibbar": True},
                {"id": "feiertage", "konto": "ics"}, {"name": "ohne Kennung"}]

    def ablage_termine(self, von: datetime, bis: datetime, kalender: str | None = None) -> list[dict[str, Any]]:
        self.aufrufe.append((von, bis, kalender))
        if self.fehler:
            raise self.fehler
        return list(self.termine)

    def ablage_anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
        if self.fehler:
            raise self.fehler
        self.angelegt.append(termin)
        return {"id": "neu-1", "titel": termin["titel"], "start": termin["start"], "ende": termin["ende"],
                "ganztaegig": termin["ganztaegig"], "ort": termin["ort"], "kalender": "Privat", "konto": "icloud"}


def _t(**felder: Any) -> dict[str, Any]:
    return {"id": "t1", "titel": "Zahnarzt", "start": "2026-10-12T09:00:00+00:00", "ende": "2026-10-12T10:00:00+00:00",
            "ganztaegig": False, "ort": "", "kalender": "Privat", "konto": "icloud", **felder}


# ── Auswahl der Quelle ──────────────────────────────────────────────────────────────────────────────────
def test_ohne_dienst_und_ohne_ablage_ist_nichts_eingerichtet():
    q = T.quelle()
    assert q.art == "keine" and not q.eingerichtet
    assert q.als_dict()["eingerichtet"] is False
    # Anders als bei den Vorgängen gibt es hier keine leere Liste: „keine Quelle“ darf nie wie „keine Termine“ aussehen.
    for aufruf in (lambda: q.termine(VON, BIS), lambda: q.anstehende(1), q.kalender, lambda: q.anlegen({"titel": "x"})):
        with pytest.raises(NichtEingerichtet) as e:
            aufruf()
        assert e.value.status == 501 and "FYOS_TERMINE_URL" in str(e.value) and "kalender" in str(e.value)


def test_die_fehlerklassen_haengen_so_zusammen():
    assert issubclass(QuelleFehler, vorgaenge.QuelleFehler)
    assert issubclass(NichtEingerichtet, QuelleFehler)
    # „keine Vorgangs-Quelle“ fangen heißt nicht „kein Kalender“
    assert not issubclass(NichtEingerichtet, vorgaenge.NichtEingerichtet)


def test_reihenfolge_adresse_angemeldeter_dienst_umgebung_ablage(monkeypatch):
    ablage = Kalenderablage()
    T.ablage_anmelden(ablage)
    assert T.angemeldete_ablage() is ablage
    q = T.quelle()
    assert q.art == "ablage" and q.eingerichtet and q.ablage is ablage and "kalender" in q.beschreibung()

    # die Umgebung schlägt die Ablage; die Kopfzeile kommt aus FYOS_TERMINE_KOPF
    monkeypatch.setenv("FYOS_TERMINE_URL", "http://umgebung.example:8080/")
    monkeypatch.setenv("FYOS_TERMINE_KOPF", "X-Innen: ja")
    q = T.quelle()
    assert (q.art, q.url, q.kopf) == ("dienst", "http://umgebung.example:8080", {"X-Innen": "ja"})
    assert "umgebung.example:8080" in q.beschreibung()

    # ein angemeldeter Dienst schlägt die Umgebung, ein Argument schlägt alles
    T.dienst_anmelden("http://angemeldet.example/api/", {"X-A": "1"})
    assert T.angemeldeter_dienst() == ("http://angemeldet.example/api", {"X-A": "1"})
    q = T.quelle()
    assert (q.url, q.kopf) == ("http://angemeldet.example/api", {"X-A": "1"})
    assert T.quelle(kopf="X-B: 2").kopf == {"X-B": "2"}
    assert T.quelle(url="http://direkt.example").url == "http://direkt.example"
    # eine leere Adresse zählt als nicht angegeben (die Umgebung bleibt gültig)
    assert T.quelle(url="").url == "http://angemeldet.example/api"
    assert T.quelle(url="   ").art == "dienst"

    T.dienst_anmelden(None)
    assert T.quelle().url == "http://umgebung.example:8080"
    monkeypatch.delenv("FYOS_TERMINE_URL")
    assert T.quelle().art == "ablage"
    T.ablage_anmelden(None)
    assert T.quelle().art == "keine"


def test_kaputte_kopfzeilen_werden_nicht_gesendet():
    assert T.quelle(url="http://x.example", kopf="ohne doppelpunkt").kopf == {}
    assert T.quelle(url="http://x.example", kopf="Name mit Leerzeichen: x").kopf == {}


def test_die_beschreibung_nennt_nie_zugangsdaten():
    d = T.Dienst("http://nutzer:geheim@example.com:8080/pfad")
    assert d.beschreibung() == "Kalender-Dienst example.com:8080"
    assert "geheim" not in d.beschreibung() and "nutzer" not in d.beschreibung()
    assert T.Dienst("kein-schema").beschreibung() == "Kalender-Dienst"


# ── Termin-Dienst ───────────────────────────────────────────────────────────────────────────────────────
def test_der_dienst_liefert_termine_im_terminformat_nach_beginn_sortiert(dienst, monkeypatch):
    monkeypatch.setenv("FYOS_TERMINE_KOPF", "X-Innen: ja")
    monkeypatch.setenv("FYOS_TERMINE_URL", dienst.url)
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse(
        _ereignis(id="roh", title="Gruppe", start={"dateTime": "2026-10-13T15:00:00+00:00"},
                  end={"dateTime": "2026-10-13T16:00:00+00:00"}),
        {"title": "", "start": "2026-10-13T12:00:00Z", "calendar_name": None, "calendar_id": "primary"},
        _ereignis(id="frueh", title="Frühstück", start="2026-10-12T08:00:00+02:00", end="2026-10-12T09:00:00+02:00",
                  location="Café\nam Eck"),
        _ereignis(id="feiertag", title="Feiertag", start="2026-10-13", end="2026-10-14", all_day=True, location=None),
        _ereignis(id="apple", title="Geburtstag", start="2026-10-12", end="2026-10-13", all_day=False, source="apple"),
        _ereignis(id="zahn", title="Zahnarzt", start="2026-10-12T06:30:00+00:00", end="2026-10-12T07:30:00+00:00"),
        _ereignis(id="ohne-start", title="kaputt", start=None),
        _ereignis(id="spaeter", title="Zu spät", start="2026-10-14T09:00:00+00:00", end="2026-10-14T10:00:00+00:00"),
        "kein Objekt",
    )
    q = T.quelle()
    assert q.art == "dienst"
    termine = q.termine(VON, BIS)

    # nach Zeitpunkt sortiert (nicht nach Text: 08:00+02:00 ist früher als 06:30+00:00), ganztägige eines Tages zuerst
    assert [t["id"] for t in termine] == ["apple", "frueh", "zahn", "feiertag", termine[4]["id"], "roh"]
    apple, frueh, zahn, feiertag, ohne_id, roh = termine
    assert list(zahn) == ["id", "titel", "start", "ende", "ganztaegig", "ort", "kalender", "konto"]
    assert zahn == {"id": "zahn", "titel": "Zahnarzt", "start": "2026-10-12T06:30:00+00:00",
                    "ende": "2026-10-12T07:30:00+00:00", "ganztaegig": False, "ort": "Praxis", "kalender": "Privat",
                    "konto": "google"}
    # ganztägig: Datum statt Zeitstempel, auch wenn der Dienst das Kennzeichen nicht setzt (iCloud)
    assert (apple["start"], apple["ende"], apple["ganztaegig"], apple["konto"]) == ("2026-10-12", "2026-10-13", True, "apple")
    assert (feiertag["start"], feiertag["ende"], feiertag["ganztaegig"], feiertag["ort"]) == ("2026-10-13", "2026-10-14", True, "")
    assert frueh["ort"] == "Café am Eck"  # eine Zeile
    # ohne Titel, ohne Kennung, ohne Kalendername: ergänzt, nie leer
    assert ohne_id["titel"] == "(ohne Titel)" and ohne_id["id"].startswith("t-") and ohne_id["kalender"] == "primary"
    assert ohne_id["start"] == "2026-10-13T12:00:00+00:00" and ohne_id["ende"] == ohne_id["start"]
    assert roh["start"] == "2026-10-13T15:00:00+00:00" and roh["ende"] == "2026-10-13T16:00:00+00:00"

    # was der Dienst zu sehen bekam
    aufruf = dienst.aufrufe[0]
    assert aufruf["methode"] == "GET" and aufruf["pfad"] == "/api/calendar/events"
    assert aufruf["abfrage"] == {"who": "all", "days": "2", "start": "2026-10-12T00:00:00+00:00",
                                 "end": "2026-10-14T00:00:00+00:00"}
    assert aufruf["kopf"]["x-innen"] == "ja" and aufruf["kopf"]["accept"] == "application/json"


def test_die_tage_der_abfrage_folgen_dem_fenster(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse()
    q = T.Dienst(dienst.url)
    q.termine(VON, VON + timedelta(hours=1))
    q.termine(VON, VON + timedelta(days=3, hours=1))
    q.termine(VON, VON + timedelta(days=200))
    assert [a["abfrage"]["days"] for a in dienst.aufrufe] == ["1", "4", "90"]
    assert dienst.aufrufe[2]["abfrage"]["end"] == (VON + timedelta(days=200)).isoformat()


def test_zeitfenster_halboffen_ein_termin_gehoert_hinein_wenn_er_es_beruehrt(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse(
        _ereignis(id="endet-zum-beginn", start="2026-10-11T22:00:00+00:00", end="2026-10-12T00:00:00+00:00"),
        _ereignis(id="ragt-hinein", start="2026-10-11T23:00:00+00:00", end="2026-10-12T00:30:00+00:00"),
        _ereignis(id="punkt-am-beginn", start="2026-10-12T00:00:00+00:00", end="2026-10-12T00:00:00+00:00"),
        _ereignis(id="beginnt-am-ende", start="2026-10-14T00:00:00+00:00", end="2026-10-14T01:00:00+00:00"),
        _ereignis(id="punkt-am-ende", start="2026-10-14T00:00:00+00:00", end="2026-10-14T00:00:00+00:00"),
        _ereignis(id="mehrtaegig", start="2026-10-09", end="2026-10-13", all_day=True),
        _ereignis(id="vortag", start="2026-10-11", end="2026-10-12", all_day=True),
        _ereignis(id="nachtag", start="2026-10-14", end="2026-10-15", all_day=True),
    )
    ids = [t["id"] for t in T.Dienst(dienst.url).termine(VON, BIS)]
    assert sorted(ids) == ["mehrtaegig", "punkt-am-beginn", "ragt-hinein"]


def test_der_dienst_ohne_zugang_ist_ein_fehler_und_nie_keine_termine(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = (200, {
        "status": "auth-pending", "total": 0, "events": [], "_stub": True,
        "_message": "token.json fehlt oder kein refresh_token.",
    })
    with pytest.raises(QuelleFehler) as e:
        T.Dienst(dienst.url).termine(VON, BIS)
    assert e.value.status == 503
    assert "keinen Zugang" in str(e.value) and "token.json fehlt" in str(e.value)
    # ohne Angabe nennt der Fehler wenigstens den Status
    dienst.routen[("GET", "/api/calendar/events")] = (200, {"status": "refresh-failed", "events": [], "_stub": True})
    with pytest.raises(QuelleFehler, match="refresh-failed"):
        T.Dienst(dienst.url).anstehende(1)


def test_ein_leerer_aber_zugaenglicher_kalender_ist_keine_termine(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse()
    q = T.Dienst(dienst.url)
    assert q.termine(VON, BIS) == []
    assert q.anstehende(1) == []


@pytest.mark.parametrize("antwort, status, text", [
    ((401, {"detail": "nope"}), 401, "lehnt die Anfrage ab (401)"),
    ((403, "verboten"), 403, "FYOS_TERMINE_KOPF"),
    ((404, {"detail": "nicht gefunden"}), 404, "antwortet mit 404: nicht gefunden"),
    ((500, {"detail": "Kalender wackelt"}), 500, "Kalender wackelt"),
    ((502, "<html>Bad Gateway</html>"), 502, "HTTP 502"),
    ((200, "<html>keine Daten</html>"), 502, "nicht mit lesbaren Daten"),
    ((200, [1, 2]), 502, "nicht mit lesbaren Daten"),
    ((200, {"status": "live"}), 502, "ohne Terminliste"),
    ((200, {"events": "viele"}), 502, "ohne Terminliste"),
    ((204, ""), 502, "ohne Terminliste"),
])
def test_fehler_des_dienstes_sind_fehler_mit_grund(dienst, antwort, status, text):
    dienst.routen[("GET", "/api/calendar/events")] = antwort
    with pytest.raises(QuelleFehler, match="Kalender-Dienst 127.0.0.1") as e:
        T.Dienst(dienst.url).termine(VON, BIS)
    assert e.value.status == status and text in str(e.value)


def test_umleitungen_werden_nicht_verfolgt(dienst):
    # die Kopfzeile des Dienstes darf nicht an eine andere Adresse gehen
    dienst.routen[("GET", "/api/calendar/events")] = (302, "", {"Location": dienst.url + "/woanders"})
    dienst.routen[("GET", "/woanders")] = _ereignisse(_ereignis())
    with pytest.raises(QuelleFehler, match="Umleitungen werden nicht verfolgt") as e:
        T.Dienst(dienst.url, {"X-Geheim": "1"}).termine(VON, BIS)
    assert e.value.status == 302
    assert [a["pfad"] for a in dienst.aufrufe] == ["/api/calendar/events"]


def test_ein_dienst_der_nicht_antwortet_ist_ein_fehler():
    with Attrappe() as a:
        url = a.url
    with pytest.raises(QuelleFehler, match="nicht erreichbar"):
        T.Dienst(url).termine(VON, BIS)
    with pytest.raises(QuelleFehler, match="keine gültige URL"):
        T.Dienst("kalender.example").termine(VON, BIS)


def test_zeitueberschreitung_wird_benannt(dienst, monkeypatch):
    monkeypatch.setattr(T, "FRIST_LESEN_S", 0.3)
    dienst.routen[("GET", "/api/calendar/events")] = lambda a: (time.sleep(1.5), _ereignisse())[1]
    with pytest.raises(QuelleFehler, match=r"nicht erreichbar \(Zeitüberschreitung\)"):
        T.Dienst(dienst.url).termine(VON, BIS)


def test_nach_kalender_filtern(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse(
        _ereignis(id="a", calendar_name="Privat", calendar_id="priv@x"),
        _ereignis(id="b", calendar_name="Arbeit", calendar_id="arbeit@x"),
    )
    q = T.Dienst(dienst.url)
    assert [t["id"] for t in q.termine(VON, BIS, "privat")] == ["a"]
    assert [t["id"] for t in q.termine(VON, BIS, "ARBEIT@x")] == ["b"]
    assert q.termine(VON, BIS, "Familie") == []
    assert len(q.termine(VON, BIS, "")) == 2
    with pytest.raises(ValueError, match="kalender"):
        q.termine(VON, BIS, "x" * 300)


def test_anstehende_fragt_ab_jetzt(dienst):
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse()
    vor = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=2)
    T.Dienst(dienst.url).anstehende(2)
    ab = datetime.fromisoformat(dienst.aufrufe[0]["abfrage"]["start"])
    bis = datetime.fromisoformat(dienst.aufrufe[0]["abfrage"]["end"])
    assert vor <= ab <= datetime.now(UTC) and bis - ab == timedelta(days=2)
    assert dienst.aufrufe[0]["abfrage"]["days"] == "2"
    for schlecht in (0, 367, "x", None):
        with pytest.raises(ValueError, match="tage"):
            T.Dienst(dienst.url).anstehende(schlecht)


def test_der_haken_ersetzt_das_netz():
    gesehen: list[tuple[str, str, Any, float]] = []

    def aufruf(methode: str, pfad: str, koerper: Any, frist: float) -> tuple[int, Any]:
        gesehen.append((methode, pfad, koerper, frist))
        return _ereignisse(_ereignis())

    termine = T.Dienst("http://egal.example", aufruf=aufruf).termine(VON, BIS)
    assert [t["id"] for t in termine] == ["e1"]
    assert gesehen[0][0] == "GET" and gesehen[0][1].startswith("/api/calendar/events?who=all&days=2&start=")
    assert gesehen[0][3] == T.FRIST_LESEN_S


def test_kalender_des_dienstes(dienst):
    dienst.routen[("GET", "/api/calendar/calendars")] = (200, {"status": "live", "calendars": [
        {"id": "primary", "summary": "Privat", "access_role": "owner"},
        {"id": "feiertage@x", "summary": "Feiertage", "access_role": "reader"},
        {"id": "", "summary": "ohne Kennung"},
        "kein Objekt",
    ]})
    assert T.Dienst(dienst.url).kalender() == [
        {"id": "primary", "name": "Privat", "konto": "", "schreibbar": True},
        {"id": "feiertage@x", "name": "Feiertage", "konto": "", "schreibbar": False},
    ]
    dienst.routen[("GET", "/api/calendar/calendars")] = (200, {"calendars": [], "status": "auth-pending"})
    with pytest.raises(QuelleFehler, match="keinen Zugang.*auth-pending") as e:
        T.Dienst(dienst.url).kalender()
    assert e.value.status == 503
    dienst.routen[("GET", "/api/calendar/calendars")] = (200, {"calendars": [], "status": "live"})
    assert T.Dienst(dienst.url).kalender() == []
    dienst.routen[("GET", "/api/calendar/calendars")] = (200, {"status": "live"})
    with pytest.raises(QuelleFehler, match="ohne Kalenderliste"):
        T.Dienst(dienst.url).kalender()


def test_der_dienst_legt_termine_an(dienst):
    dienst.routen[("POST", "/api/calendar/events")] = (200, {"id": "neu-7", "summary": "Zahnarzt", "status": "created"})
    t = T.Dienst(dienst.url).anlegen({"titel": "  Zahnarzt ", "start": "2026-10-15T09:00:00+02:00",
                                      "ort": "Praxis", "beschreibung": "nur auf Wunsch", "kalender": "primary"})
    assert t == {"id": "neu-7", "titel": "Zahnarzt", "start": "2026-10-15T09:00:00+02:00",
                 "ende": "2026-10-15T10:00:00+02:00", "ganztaegig": False, "ort": "Praxis", "kalender": "primary",
                 "konto": ""}
    assert dienst.aufrufe[0]["rumpf"] == {
        "title": "Zahnarzt", "start": "2026-10-15T09:00:00+02:00", "end": "2026-10-15T10:00:00+02:00",
        "all_day": False, "location": "Praxis", "description": "nur auf Wunsch", "calendar_id": "primary"}
    assert dienst.aufrufe[0]["kopf"]["content-type"] == "application/json"
    # ganztägig, ohne Kalender: kein calendar_id
    T.Dienst(dienst.url).anlegen({"titel": "Urlaub", "start": "2026-10-20", "ende": "2026-10-23"})
    assert dienst.aufrufe[1]["rumpf"] == {"title": "Urlaub", "start": "2026-10-20", "end": "2026-10-23", "all_day": True,
                                          "location": "", "description": ""}


def test_der_dienst_ohne_anlegen_sagt_das_klar(dienst):
    for status in (404, 405, 501):
        dienst.routen[("POST", "/api/calendar/events")] = (status, {"detail": "gibt es nicht"})
        with pytest.raises(QuelleFehler, match="kann keine Termine anlegen") as e:
            T.Dienst(dienst.url).anlegen({"titel": "x", "start": "2026-10-15"})
        assert e.value.status == 501
    dienst.routen[("POST", "/api/calendar/events")] = (503, {"detail": "Google-Calendar not ready: auth-pending"})
    with pytest.raises(QuelleFehler, match="not ready") as e:
        T.Dienst(dienst.url).anlegen({"titel": "x", "start": "2026-10-15"})
    assert e.value.status == 503
    dienst.routen[("POST", "/api/calendar/events")] = (200, {"status": "created"})
    with pytest.raises(QuelleFehler, match="nicht bestätigt"):
        T.Dienst(dienst.url).anlegen({"titel": "x", "start": "2026-10-15"})


def test_falsche_eingabe_erreicht_den_dienst_nie(dienst):
    with pytest.raises(ValueError, match="titel fehlt"):
        T.Dienst(dienst.url).anlegen({"start": "2026-10-15"})
    assert dienst.aufrufe == []


# ── Kalender-Plugin als Ablage ──────────────────────────────────────────────────────────────────────────
def test_die_ablage_liefert_termine_im_terminformat():
    ablage = Kalenderablage([
        _t(id="spaet", titel="Zu spät", start="2026-10-14T09:00:00+00:00", ende="2026-10-14T10:00:00+00:00"),
        _t(id="zahn", start="2026-10-12T09:00:00+02:00", ende="2026-10-12T10:00:00+02:00", ort="  Praxis\n3 "),
        _t(id="tag", titel="Feiertag", start="2026-10-13", ende="", ganztaegig=True),
        {"id": "ohne-start", "titel": "kaputt"},
        {"titel": "Roh", "start": "2026-10-12T05:00:00+00:00"},
        "kein Objekt",
    ])
    T.ablage_anmelden(ablage)
    q = T.quelle()
    termine = q.termine(VON, BIS, "Privat")
    assert [t["titel"] for t in termine] == ["Roh", "Zahnarzt", "Feiertag"]
    roh, zahn, tag = termine
    assert roh["id"].startswith("t-") and roh["ende"] == roh["start"] and roh["ganztaegig"] is False
    assert zahn["ort"] == "Praxis 3"
    assert (tag["start"], tag["ende"], tag["ganztaegig"]) == ("2026-10-13", "2026-10-14", True)
    # das Plugin bekommt ein Fenster mit Versatz und den Kalender
    von, bis, kalender = ablage.aufrufe[0]
    assert (von, bis, kalender) == (VON, BIS, "Privat") and von.tzinfo is not None and bis.tzinfo is not None
    assert ablage.aufrufe[0][2] == "Privat"
    q.termine("2026-10-12", datetime(2026, 10, 13, 12, 0))
    assert ablage.aufrufe[1][2] is None  # alle Kalender
    assert ablage.aufrufe[1][0] == VON and ablage.aufrufe[1][1] == datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_die_ablage_nennt_ihre_kalender():
    T.ablage_anmelden(Kalenderablage())
    assert T.quelle().kalender() == [
        {"id": "privat", "name": "Privat", "konto": "icloud", "schreibbar": True},
        {"id": "feiertage", "name": "feiertage", "konto": "ics", "schreibbar": False},
    ]


def test_die_ablage_legt_termine_an():
    ablage = Kalenderablage()
    T.ablage_anmelden(ablage)
    t = T.quelle().anlegen({"titel": "Zahnarzt", "start": "2026-10-15T09:00:00", "ort": "Praxis"})
    # das Plugin bekommt die geprüfte Fassung, Zeiten ohne Versatz unverändert (es kennt die Zeitzone des Hubs nicht besser)
    assert ablage.angelegt == [{"titel": "Zahnarzt", "start": "2026-10-15T09:00:00", "ende": "2026-10-15T10:00:00",
                                "ganztaegig": False, "ort": "Praxis", "beschreibung": "", "kalender": ""}]
    assert t["id"] == "neu-1" and t["kalender"] == "Privat" and t["konto"] == "icloud"
    with pytest.raises(ValueError, match="ende muss nach start liegen"):
        T.quelle().anlegen({"titel": "x", "start": "2026-10-15T09:00", "ende": "2026-10-15T08:00"})
    assert len(ablage.angelegt) == 1


def test_fehler_der_ablage_zeigen_nie_den_text_fremder_ausnahmen():
    ablage = Kalenderablage()
    T.ablage_anmelden(ablage)
    q = T.quelle()

    ablage.fehler = RuntimeError("Anmeldung mit Passwort hunter2 abgelehnt")
    for aufruf in (lambda: q.termine(VON, BIS), q.kalender, lambda: q.anlegen({"titel": "x", "start": "2026-10-15"})):
        with pytest.raises(QuelleFehler) as e:
            aufruf()
        assert "RuntimeError" in str(e.value) and "hunter2" not in str(e.value) and e.value.status == 502

    # eigene Fehler des Plugins mit verständlichem Text gehen durch
    ablage.fehler = QuelleFehler("Anmeldung abgelehnt (App-Passwort prüfen)", 401)
    with pytest.raises(QuelleFehler, match="App-Passwort prüfen") as e:
        q.termine(VON, BIS)
    assert e.value.status == 401
    # auch die Fehlerklasse der Vorgänge wird zu einem Fehler der Termine
    ablage.fehler = vorgaenge.QuelleFehler("Kalender spinnt", 503)
    with pytest.raises(QuelleFehler, match="Kalender spinnt") as e:
        q.termine(VON, BIS)
    assert type(e.value) is QuelleFehler and e.value.status == 503
    # falsche Eingabe bleibt falsche Eingabe
    ablage.fehler = ValueError("kalender 'x' gibt es nicht")
    with pytest.raises(ValueError, match="gibt es nicht"):
        q.termine(VON, BIS, "x")
    ablage.fehler = NotImplementedError()
    with pytest.raises(QuelleFehler, match="kann das nicht") as e:
        q.anlegen({"titel": "x", "start": "2026-10-15"})
    assert e.value.status == 501


def test_eine_ablage_ohne_anlegen_und_mit_unbrauchbaren_antworten():
    class NurLesen:
        def ablage_kalender(self) -> Any:
            return "viele"

        def ablage_termine(self, von: datetime, bis: datetime, kalender: str | None = None) -> Any:
            return {"termine": []}

    T.ablage_anmelden(NurLesen())  # type: ignore[arg-type]
    q = T.quelle()
    assert q.beschreibung() == "Kalender-Plugin"
    with pytest.raises(QuelleFehler, match="kann keine Termine anlegen") as e:
        q.anlegen({"titel": "x", "start": "2026-10-15"})
    assert e.value.status == 501
    with pytest.raises(QuelleFehler, match="ohne Terminliste"):
        q.termine(VON, BIS)
    with pytest.raises(QuelleFehler, match="ohne Kalenderliste"):
        q.kalender()

    class Stumm(Kalenderablage):
        def ablage_anlegen(self, termin: dict[str, Any]) -> dict[str, Any]:
            return {"id": "x"}  # kein Beginn: nicht bestätigt

    T.ablage_anmelden(Stumm())
    with pytest.raises(QuelleFehler, match="nicht bestätigt"):
        T.quelle().anlegen({"titel": "x", "start": "2026-10-15"})


def test_die_ablage_meldet_sich_ab():
    ablage = Kalenderablage()
    T.ablage_anmelden(ablage)
    assert T.angemeldete_ablage() is ablage
    T.ablage_anmelden(None)
    assert T.angemeldete_ablage() is None and T.quelle().art == "keine"


# ── Zeit ────────────────────────────────────────────────────────────────────────────────────────────────
def test_ganztaegige_termine_gelten_in_der_zeitzone_des_hubs(monkeypatch):
    try:
        ZoneInfo("Europe/Berlin")
    except Exception:  # noqa: BLE001
        pytest.skip("keine Zeitzonen-Datenbank auf diesem Rechner")
    monkeypatch.setenv("FYOS_ZEITZONE", "Europe/Berlin")
    T.ablage_anmelden(Kalenderablage([_t(id="tag", titel="Feiertag", start="2026-10-13", ende="2026-10-14",
                                         ganztaegig=True)]))
    q = T.quelle()
    # der 13. Oktober beginnt in Berlin um 22:00 Uhr UTC des 12.
    assert q.termine(datetime(2026, 10, 12, 21, 0, tzinfo=UTC), datetime(2026, 10, 12, 21, 59, tzinfo=UTC)) == []
    assert len(q.termine(datetime(2026, 10, 12, 21, 0, tzinfo=UTC), datetime(2026, 10, 12, 22, 1, tzinfo=UTC))) == 1
    # und endet um 22:00 Uhr UTC des 13.
    assert len(q.termine(datetime(2026, 10, 13, 21, 0, tzinfo=UTC), datetime(2026, 10, 13, 22, 30, tzinfo=UTC))) == 1
    assert q.termine(datetime(2026, 10, 13, 22, 0, tzinfo=UTC), datetime(2026, 10, 13, 23, 0, tzinfo=UTC)) == []
    # eine Zeit ohne Versatz ist Berliner Zeit
    assert T.lokalisiere(datetime(2026, 10, 13, 9, 0)).utcoffset() == timedelta(hours=2)
    assert T.lokalisiere(datetime(2026, 12, 13, 9, 0)).utcoffset() == timedelta(hours=1)


def test_unbekannte_zeitzone_faellt_auf_die_des_rechners_zurueck(monkeypatch, caplog):
    monkeypatch.setenv("FYOS_ZEITZONE", "Nirgendwo/Gibtsnicht")
    monkeypatch.setattr(T, "_gewarnt", set())
    with caplog.at_level(logging.WARNING, logger="mcp_hub.termine"):
        assert T.lokale_zone() is None
        assert T.lokale_zone() is None
    assert len([r for r in caplog.records if "Nirgendwo" in r.getMessage()]) == 1  # nur einmal gemeldet
    assert T.lokalisiere(datetime(2026, 10, 13, 9, 0)).utcoffset() is not None
    monkeypatch.delenv("FYOS_ZEITZONE")
    assert T.lokale_zone() is None
    monkeypatch.setenv("FYOS_ZEITZONE", "utc")
    assert T.lokale_zone() is timezone.utc


def test_fenster_wird_geprueft():
    q = T.quelle(url="http://egal.example")
    with pytest.raises(ValueError, match="bis muss nach von liegen"):
        q.termine(BIS, VON)
    with pytest.raises(ValueError, match="bis muss nach von liegen"):
        q.termine(VON, VON)
    with pytest.raises(ValueError, match="länger als 366 Tage"):
        q.termine(VON, VON + timedelta(days=367))
    with pytest.raises(ValueError, match="von: keine gültige Zeit"):
        q.termine("morgen", BIS)
    with pytest.raises(ValueError, match="bis: keine gültige Zeit"):
        q.termine(VON, None)


# ── Eingabe für anlegen() ───────────────────────────────────────────────────────────────────────────────
def test_pruefe_neu_ganztaegig_und_mit_uhrzeit():
    # ganztägig, ohne Ende: ein Tag; ein Ende am selben Tag zählt auch als ein Tag
    assert T.pruefe_neu({"titel": "Urlaub", "start": "2026-10-20"}) == {
        "titel": "Urlaub", "start": "2026-10-20", "ende": "2026-10-21", "ganztaegig": True, "ort": "",
        "beschreibung": "", "kalender": ""}
    assert T.pruefe_neu({"titel": "x", "start": "2026-10-20", "ende": "2026-10-20"})["ende"] == "2026-10-21"
    assert T.pruefe_neu({"titel": "x", "start": "2026-10-20", "ende": "2026-10-23"})["ende"] == "2026-10-23"
    # ausdrücklich ganztägig mit Zeitstempeln: nur die Tage zählen
    t = T.pruefe_neu({"titel": "x", "start": "2026-10-20T00:00:00", "ende": "2026-10-22T00:00:00", "ganztaegig": True})
    assert (t["start"], t["ende"], t["ganztaegig"]) == ("2026-10-20", "2026-10-22", True)
    # mit Uhrzeit, ohne Ende: eine Stunde
    t = T.pruefe_neu({"titel": "x", "start": "2026-10-20T09:30:00+02:00"})
    assert (t["start"], t["ende"], t["ganztaegig"]) == ("2026-10-20T09:30:00+02:00", "2026-10-20T10:30:00+02:00", False)
    t = T.pruefe_neu({"titel": "x", "start": "2026-10-20T09:30", "ende": "2026-10-20T11:00", "ganztaegig": False})
    assert (t["start"], t["ende"]) == ("2026-10-20T09:30:00", "2026-10-20T11:00:00")


def test_pruefe_neu_bereinigt_texte():
    t = T.pruefe_neu({"titel": "  Zahn\narzt \t heute ", "start": "2026-10-20", "ort": "Praxis\r\nStraße 1",
                      "beschreibung": " Zeile 1\r\nZeile 2\x00\x07 ", "kalender": " Privat "})
    assert t["titel"] == "Zahn arzt heute" and t["ort"] == "Praxis Straße 1" and t["kalender"] == "Privat"
    assert t["beschreibung"] == "Zeile 1\nZeile 2"


@pytest.mark.parametrize("termin, text", [
    ("Zahnarzt", "ein Objekt"),
    ({"start": "2026-10-20"}, "titel fehlt"),
    ({"titel": "   ", "start": "2026-10-20"}, "titel fehlt"),
    ({"titel": "x" * 201, "start": "2026-10-20"}, "titel ist länger als 200"),
    ({"titel": "x"}, "start fehlt"),
    ({"titel": "x", "start": "morgen"}, "start fehlt oder ist keine gültige Zeit"),
    ({"titel": "x", "start": "2026-10-20", "ende": "bald"}, "ende ist keine gültige Zeit"),
    ({"titel": "x", "start": "2026-10-20", "ende": "2026-10-19"}, "ende liegt vor start"),
    ({"titel": "x", "start": "2026-10-20", "ende": "2028-10-20"}, "länger als 366 Tage"),
    ({"titel": "x", "start": "2026-10-20", "ganztaegig": False}, "start braucht eine Uhrzeit"),
    ({"titel": "x", "start": "2026-10-20T09:00", "ende": "2026-10-21"}, "ende braucht eine Uhrzeit"),
    ({"titel": "x", "start": "2026-10-20T09:00", "ende": "2026-10-20T09:00"}, "ende muss nach start liegen"),
    ({"titel": "x", "start": "2026-10-20T09:00", "ende": "2026-10-20T08:00"}, "ende muss nach start liegen"),
    ({"titel": "x", "start": "2026-10-20T09:00", "ende": "2028-10-20T08:00"}, "länger als 366 Tage"),
    ({"titel": "x", "start": "2026-10-20", "ganztaegig": "ja"}, "true oder false"),
    ({"titel": "x", "start": "2026-10-20", "ort": "o" * 201}, "ort ist länger als 200"),
    ({"titel": "x", "start": "2026-10-20", "kalender": "k" * 201}, "kalender ist länger als 200"),
    ({"titel": "x", "start": "2026-10-20", "beschreibung": "b" * 2001}, "beschreibung ist länger als 2000"),
    ({"titel": "x", "start": "2026-10-20", "teilnehmer": ["a@b"], "erinnerung": 5}, "unbekannte Felder erinnerung, teilnehmer"),
])
def test_pruefe_neu_lehnt_falsche_eingabe_ab(termin, text):
    with pytest.raises(ValueError, match=text):
        T.pruefe_neu(termin)


def test_termin_aus_vereinheitlicht_zeiten():
    t = T.termin_aus({"id": 7, "titel": "x", "start": "2026-10-12T12:00:00Z", "ende": "2026-10-12T11:00:00Z"})
    assert t is not None and (t["id"], t["start"], t["ende"]) == ("7", "2026-10-12T12:00:00+00:00", "2026-10-12T11:00:00+00:00")
    # ohne lesbaren Beginn ist ein Termin nicht einzuordnen
    assert T.termin_aus({"titel": "x"}) is None and T.termin_aus({"titel": "x", "start": "bald"}) is None
    g = T.termin_aus({"titel": "x", "start": "2026-10-12", "ende": "2026-10-12", "ganztaegig": False})
    assert g is not None and (g["start"], g["ende"], g["ganztaegig"]) == ("2026-10-12", "2026-10-13", True)
    # dieselbe Eingabe, dieselbe erfundene Kennung
    a = T.termin_aus({"titel": "x", "start": "2026-10-12", "kalender": "k"})
    b = T.termin_aus({"titel": "x", "start": "2026-10-12", "kalender": "k"})
    assert a is not None and b is not None and a["id"] == b["id"] and a["id"] != T.termin_aus(
        {"titel": "y", "start": "2026-10-12", "kalender": "k"})["id"]  # type: ignore[index]


def test_die_obergrenze_der_termine(monkeypatch, dienst):
    monkeypatch.setattr(T, "TERMINE_MAX", 3)
    dienst.routen[("GET", "/api/calendar/events")] = _ereignisse(*[
        _ereignis(id=f"e{i}", start=f"2026-10-12T{i:02d}:00:00+00:00", end=f"2026-10-12T{i:02d}:30:00+00:00")
        for i in range(10)
    ])
    assert [t["id"] for t in T.Dienst(dienst.url).termine(VON, BIS)] == ["e0", "e1", "e2"]
