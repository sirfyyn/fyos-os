"""Postfach für Plugins (``mcp_hub.postfach``): Mail-Dienst, Mail-Plugin oder keine Quelle.

Der Dienst ist ein kleiner HTTP-Server im Thread (kein Netz nach außen); das Mail-Plugin eine Attrappe im Speicher.
Echte Postfächer und echte Mails kommen nirgends vor.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mcp_hub import postfach as P
from mcp_hub import vorgaenge
from mcp_hub.postfach import NichtEingerichtet, QuelleFehler

ID1 = "18f3a9c2b4d5e6f7"


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_POSTFACH_URL", "FYOS_POSTFACH_KOPF"):
        monkeypatch.delenv(name, raising=False)
    # Die Attrappe läuft auf 127.0.0.1; ein Proxy der Umgebung soll sie nicht umleiten.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    P.ablage_anmelden(None)
    P.dienst_anmelden(None)
    yield
    P.ablage_anmelden(None)
    P.dienst_anmelden(None)


# ── Attrappen ───────────────────────────────────────────────────────────────────────────────────────────
class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:  # abgebrochene Anfragen sind hier gewollt
        return None


class Attrappe:
    """Ein HTTP-Dienst im Thread. ``routen`` bildet ``(Methode, Pfad)`` auf eine Antwort ab: ``(Status, Inhalt)``,
    ``(Status, Inhalt, Kopfzeilen)`` oder eine Funktion, die den Aufruf bekommt und so etwas liefert. Inhalt: ``dict`` oder
    ``list`` (JSON) oder ``str`` (roh). Jede Anfrage, gleich mit welcher Methode, landet in ``aufrufe``."""

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
                    "roh": self.path,
                    "abfrage": dict(urllib.parse.parse_qsl(teile.query)),
                    "kopf": {k.lower(): v for k, v in self.headers.items()},
                    "rumpf": rumpf,
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

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _bedienen

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
        # Der Mail-Dienst ist lesend: gleich, was ein Test tut, nie eine andere Methode als GET.
        assert {x["methode"] for x in a.aufrufe} <= {"GET"}


def _nachricht(**felder: Any) -> dict[str, Any]:
    return {"id": ID1, "thread_id": ID1, "subject": "Rechnung Oktober", "from": "Alex Muster <alex@example.org>",
            "to": "ich@example.org", "date": "Tue, 06 Oct 2026 10:09:09 +0000 (UTC)", "snippet": "Hallo   Welt " * 40,
            "label_ids": ["INBOX", "UNREAD", "Label_31"], "unread": True, **felder}


def _liste(*nachrichten: Any, **rest: Any) -> tuple[int, dict[str, Any]]:
    return 200, {"service": "mail-inbox", "status": "live", "query": "in:inbox", "total": len(nachrichten),
                 "messages": list(nachrichten), "_stub": False, **rest}


def _detail(**felder: Any) -> dict[str, Any]:
    return {"id": ID1, "thread_id": ID1, "label_ids": ["INBOX", "CATEGORY_PERSONAL"], "snippet": "x",
            "subject": "Hallo", "from": "Alex Muster <alex@example.org>", "to": "ich@example.org", "cc": "",
            "date": "Tue, 06 Oct 2026 10:09:09 +0000", "body_plain": "Zeile 1\nZeile 2", "body_html": "<p>x</p>",
            "attachments": [{"attachment_id": "a1", "filename": "rechnung.pdf", "mime_type": "application/pdf",
                             "size": 1234}],
            "unread": True, "starred": False, **felder}


class Mailablage:
    """Ein Mail-Plugin im Speicher."""

    name = "mail"

    def __init__(self, mails: list[Any] | None = None, ungelesen: Any = 7) -> None:
        self.mails = mails if mails is not None else []
        self.ungelesen = ungelesen
        self.aufrufe: list[tuple[str, int, str | None]] = []
        self.gelesen: list[str] = []
        self.fehler: Exception | None = None

    def ablage_konten(self) -> list[Any]:
        if self.fehler:
            raise self.fehler
        return [{"name": "privat", "art": "imap", "adresse": "imap.example.org:993", "nutzer": "ich@example.org"},
                {"name": "arbeit", "art": "gmail", "adresse": "imap.example.net:993", "fehler": "Passwort fehlt"},
                {"art": "imap"}, "kein Objekt"]

    def ablage_liste(self, abfrage: str, anzahl: int, konto: str | None = None) -> Any:
        self.aufrufe.append((abfrage, anzahl, konto))
        if self.fehler:
            raise self.fehler
        return {"mails": list(self.mails), "ungelesen": self.ungelesen}

    def ablage_lesen(self, id: str) -> Any:  # noqa: A002
        self.gelesen.append(id)
        if self.fehler:
            raise self.fehler
        return {"id": "andere-kennung", "konto": "privat", "von": "Alex <alex@example.org>", "betreff": "Hallo",
                "datum": "2026-10-06T12:09:09+02:00", "gelesen": False, "labels": ["Posteingang"],
                "text": "Zeile 1\r\nZeile 2\x00\r\n", "gekuerzt": False,
                "anhaenge": [{"name": "rechnung.pdf", "typ": "application/pdf", "groesse": 1234}, {"name": ""}, "x"]}


def _m(**felder: Any) -> dict[str, Any]:
    return {"id": "privat.inbox.1699999999.4711", "konto": "privat", "von": "Alex <alex@example.org>",
            "an": "ich@example.org", "betreff": "Rechnung", "datum": "2026-10-06T10:09:09+00:00", "gelesen": False,
            "labels": ["Posteingang"], "ausschnitt": "Hallo", **felder}


# ── Auswahl der Quelle ──────────────────────────────────────────────────────────────────────────────────
def test_ohne_dienst_und_ohne_ablage_ist_nichts_eingerichtet():
    q = P.quelle()
    assert q.art == "keine" and not q.eingerichtet
    assert q.als_dict()["eingerichtet"] is False
    # Wie bei den Terminen gibt es hier keine leere Liste: „keine Quelle“ darf nie wie „keine Mails“ aussehen.
    for aufruf in (q.konten, lambda: q.liste(), lambda: q.liste("is:unread", 5), lambda: q.lesen(ID1)):
        with pytest.raises(NichtEingerichtet) as e:
            aufruf()
        assert e.value.status == 501
        assert "FYOS_POSTFACH_URL" in str(e.value) and "fyos-plugin-mail" in str(e.value)


def test_falsche_eingabe_ist_auch_ohne_quelle_falsche_eingabe():
    q = P.quelle()
    with pytest.raises(ValueError, match="id"):
        q.lesen("../x")
    with pytest.raises(ValueError, match="anzahl"):
        q.liste("in:inbox", 0)


def test_die_fehlerklassen_haengen_so_zusammen():
    assert issubclass(QuelleFehler, vorgaenge.QuelleFehler)
    assert issubclass(NichtEingerichtet, QuelleFehler)
    # „keine Vorgangs-Quelle“ fangen heißt nicht „kein Postfach“
    assert not issubclass(NichtEingerichtet, vorgaenge.NichtEingerichtet)


def test_reihenfolge_adresse_angemeldeter_dienst_umgebung_ablage(monkeypatch):
    ablage = Mailablage()
    P.ablage_anmelden(ablage)
    assert P.angemeldete_ablage() is ablage
    q = P.quelle()
    assert q.art == "ablage" and q.eingerichtet and q.ablage is ablage and "mail" in q.beschreibung()

    # die Umgebung schlägt die Ablage; die Kopfzeile kommt aus FYOS_POSTFACH_KOPF
    monkeypatch.setenv("FYOS_POSTFACH_URL", "http://umgebung.example:8080/")
    monkeypatch.setenv("FYOS_POSTFACH_KOPF", "X-Innen: ja")
    q = P.quelle()
    assert (q.art, q.url, q.kopf) == ("dienst", "http://umgebung.example:8080", {"X-Innen": "ja"})
    assert "umgebung.example:8080" in q.beschreibung()

    # ein angemeldeter Dienst schlägt die Umgebung, ein Argument schlägt alles
    P.dienst_anmelden("http://angemeldet.example/api/", {"X-A": "1"})
    assert P.angemeldeter_dienst() == ("http://angemeldet.example/api", {"X-A": "1"})
    q = P.quelle()
    assert (q.url, q.kopf) == ("http://angemeldet.example/api", {"X-A": "1"})
    assert P.quelle(kopf="X-B: 2").kopf == {"X-B": "2"}
    assert P.quelle(url="http://direkt.example").url == "http://direkt.example"
    # eine leere Adresse zählt als nicht angegeben (die Umgebung bleibt gültig)
    assert P.quelle(url="").url == "http://angemeldet.example/api"
    assert P.quelle(url="   ").art == "dienst"

    P.dienst_anmelden(None)
    assert P.quelle().url == "http://umgebung.example:8080"
    monkeypatch.delenv("FYOS_POSTFACH_URL")
    assert P.quelle().art == "ablage"
    P.ablage_anmelden(None)
    assert P.quelle().art == "keine"


def test_kaputte_kopfzeilen_werden_nicht_gesendet():
    assert P.quelle(url="http://x.example", kopf="ohne doppelpunkt").kopf == {}
    assert P.quelle(url="http://x.example", kopf="Name mit Leerzeichen: x").kopf == {}


def test_die_beschreibung_nennt_nie_zugangsdaten():
    d = P.Dienst("http://nutzer:geheim@example.com:8080/pfad")
    assert d.beschreibung() == "Mail-Dienst example.com:8080"
    assert "geheim" not in d.beschreibung() and "nutzer" not in d.beschreibung()
    assert d.konten() == [{"name": "dienst", "art": "dienst", "adresse": "example.com:8080"}]
    assert P.Dienst("kein-schema").beschreibung() == "Mail-Dienst"
    assert P.Dienst("http://[::1]:9000").beschreibung() == "Mail-Dienst [::1]:9000"


# ── Mail-Dienst: Liste ──────────────────────────────────────────────────────────────────────────────────
def test_der_dienst_liefert_mails_im_mailformat(dienst, monkeypatch):
    monkeypatch.setenv("FYOS_POSTFACH_URL", dienst.url)
    dienst.routen[("GET", "/api/inbox/list")] = _liste(
        _nachricht(),
        _nachricht(id="m00002abc", subject="Angebot", label_ids=["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
                   **{"from": "Shop <noreply@shop.example>"}),
        _nachricht(id="m00003abc", subject="", unread=False, label_ids=["INBOX", "CATEGORY_UPDATES", "IMPORTANT"],
                   date="Wed, 07 Oct 2026 09:00:00 +0200", snippet="  Zeile\none \n zwei ", **{"from": None}),
        _nachricht(id="m00004abc", date="kein Datum", subject="Betreff\nin\tzwei Zeilen"),
        {"subject": "ohne Kennung"},
        _nachricht(id="../etc/passwd"),
        _nachricht(id=5),
        "kein Objekt",
    )
    dienst.routen[("GET", "/api/inbox/unread-count")] = (200, {"inbox_unread": 12, "unread": 13, "inbox_total": 900})
    ergebnis = P.quelle().liste()

    assert ergebnis["ungelesen"] == 12
    mails = ergebnis["mails"]
    assert [m["id"] for m in mails] == [ID1, "m00002abc", "m00003abc", "m00004abc"]  # Reihenfolge des Dienstes
    alex, shop, bob, rest = mails
    assert list(alex) == ["id", "konto", "von", "an", "betreff", "datum", "gelesen", "labels", "ausschnitt"]
    assert (alex["konto"], alex["von"], alex["an"], alex["betreff"]) == (
        "dienst", "Alex Muster <alex@example.org>", "ich@example.org", "Rechnung Oktober")
    # Datum im Mail-Format wird ISO 8601 mit Versatz, der Gelesen-Status umgekehrt, Labels deutsch (UNREAD und
    # eigene Labels fallen weg), der Ausschnitt einzeilig und höchstens 200 Zeichen
    assert alex["datum"] == "2026-10-06T10:09:09+00:00" and alex["gelesen"] is False
    assert alex["labels"] == ["Posteingang"]
    assert len(alex["ausschnitt"]) == 200 and alex["ausschnitt"].endswith("…")
    assert alex["ausschnitt"].startswith("Hallo Welt Hallo Welt ")
    assert shop["labels"] == ["Posteingang", "Werbung"]
    # ohne Betreff, ohne Absender, ein Datum mit Versatz, gelesen
    assert bob["betreff"] == "(kein Betreff)" and bob["von"] == "" and bob["gelesen"] is True
    assert bob["labels"] == ["Posteingang", "Aktualisierungen", "Wichtig"]
    assert bob["datum"] == "2026-10-07T09:00:00+02:00" and bob["ausschnitt"] == "Zeile one zwei"
    assert rest["datum"] == "" and rest["betreff"] == "Betreff in zwei Zeilen"


def test_was_der_dienst_zu_sehen_bekommt(dienst, monkeypatch):
    monkeypatch.setenv("FYOS_POSTFACH_URL", dienst.url)
    monkeypatch.setenv("FYOS_POSTFACH_KOPF", "X-Innen: ja")
    dienst.routen[("GET", "/api/inbox/list")] = _liste(_nachricht())
    dienst.routen[("GET", "/api/inbox/unread-count")] = (200, {"inbox_unread": 3})
    ergebnis = P.quelle().liste("from:alex is:unread", 5)
    assert ergebnis["ungelesen"] == 3 and len(ergebnis["mails"]) == 1
    liste, zaehler = dienst.aufrufe
    assert (liste["methode"], liste["pfad"]) == ("GET", "/api/inbox/list")
    assert liste["abfrage"] == {"q": "from:alex is:unread", "limit": "5"}
    assert liste["roh"] == "/api/inbox/list?q=from%3Aalex%20is%3Aunread&limit=5"
    assert liste["kopf"]["x-innen"] == "ja" and liste["kopf"]["accept"] == "application/json"
    assert (zaehler["methode"], zaehler["pfad"]) == ("GET", "/api/inbox/unread-count")
    assert zaehler["kopf"]["x-innen"] == "ja" and liste["rumpf"] == b"" and zaehler["rumpf"] == b""


def test_die_abfrage_geht_unveraendert_und_richtig_kodiert_an_den_dienst(dienst):
    dienst.routen[("GET", "/api/inbox/list")] = _liste()
    q = P.Dienst(dienst.url)
    q.liste('subject:"Käse & Brot" -category:social  newer_than:2d ', 3, zaehlen=False)
    q.liste("", 3, zaehlen=False)
    q.liste(None, 3, zaehlen=False)
    assert [a["abfrage"]["q"] for a in dienst.aufrufe] == ['subject:"Käse & Brot" -category:social newer_than:2d',
                                                            "in:inbox", "in:inbox"]


def test_ohne_zaehlen_wird_nicht_gezaehlt(dienst):
    dienst.routen[("GET", "/api/inbox/list")] = _liste(_nachricht())
    dienst.routen[("GET", "/api/inbox/unread-count")] = (200, {"inbox_unread": 3})
    ergebnis = P.Dienst(dienst.url).liste("in:inbox", 10, zaehlen=False)
    assert ergebnis["ungelesen"] is None and len(ergebnis["mails"]) == 1
    assert [a["pfad"] for a in dienst.aufrufe] == ["/api/inbox/list"]


@pytest.mark.parametrize("antwort", [
    (503, {"detail": "Zähler nicht bereit"}), (200, {"unread": 13}), (200, {"inbox_unread": "viele"}),
    (200, {"inbox_unread": -1}), (200, {"inbox_unread": True}), (200, "<html>kaputt</html>"), (404, "weg"),
])
def test_ohne_brauchbaren_zaehler_bleibt_die_liste_gueltig(dienst, antwort):
    dienst.routen[("GET", "/api/inbox/list")] = _liste(_nachricht())
    dienst.routen[("GET", "/api/inbox/unread-count")] = antwort
    ergebnis = P.Dienst(dienst.url).liste()
    assert ergebnis["ungelesen"] is None and len(ergebnis["mails"]) == 1


def test_der_dienst_ohne_zugang_ist_ein_fehler_und_nie_keine_mails(dienst):
    dienst.routen[("GET", "/api/inbox/list")] = (200, {
        "status": "auth-pending", "total": 0, "messages": [], "_stub": True,
        "_message": "token.json fehlt oder kein refresh_token.",
    })
    with pytest.raises(QuelleFehler) as e:
        P.Dienst(dienst.url).liste()
    assert e.value.status == 503
    assert "keinen Zugang" in str(e.value) and "token.json fehlt" in str(e.value)
    # ohne Angabe nennt der Fehler wenigstens den Status
    dienst.routen[("GET", "/api/inbox/list")] = (200, {"status": "refresh-failed", "messages": [], "_stub": True})
    with pytest.raises(QuelleFehler, match="refresh-failed"):
        P.Dienst(dienst.url).liste()
    # auch ohne _stub: ein Status außer live und refreshed ist kein leerer Posteingang
    dienst.routen[("GET", "/api/inbox/list")] = (200, {"status": "revoked", "messages": []})
    with pytest.raises(QuelleFehler, match="revoked") as e:
        P.Dienst(dienst.url).liste()
    assert e.value.status == 503
    # der Zähler wird nach einem Fehler gar nicht erst gefragt
    assert "/api/inbox/unread-count" not in [a["pfad"] for a in dienst.aufrufe]


@pytest.mark.parametrize("status", ["live", "refreshed"])
def test_ein_leerer_aber_zugaenglicher_posteingang_ist_keine_mails(dienst, status):
    dienst.routen[("GET", "/api/inbox/list")] = _liste(status=status)
    dienst.routen[("GET", "/api/inbox/unread-count")] = (200, {"inbox_unread": 0})
    assert P.Dienst(dienst.url).liste() == {"mails": [], "ungelesen": 0}


@pytest.mark.parametrize("antwort, status, text", [
    ((401, {"detail": "nope"}), 401, "lehnt die Anfrage ab (401)"),
    ((403, "verboten"), 403, "FYOS_POSTFACH_KOPF"),
    ((404, {"detail": "nicht gefunden"}), 404, "antwortet mit 404: nicht gefunden"),
    ((500, {"detail": "Mail wackelt"}), 500, "Mail wackelt"),
    ((502, "<html>Bad Gateway</html>"), 502, "HTTP 502"),
    ((200, "<html>keine Daten</html>"), 502, "nicht mit lesbaren Daten"),
    ((200, [1, 2]), 502, "nicht mit lesbaren Daten"),
    ((200, {"status": "live"}), 502, "ohne Mailliste"),
    ((200, {"messages": "viele"}), 502, "ohne Mailliste"),
    ((204, ""), 502, "ohne Mailliste"),
])
def test_fehler_des_dienstes_sind_fehler_mit_grund(dienst, antwort, status, text):
    dienst.routen[("GET", "/api/inbox/list")] = antwort
    with pytest.raises(QuelleFehler, match="Mail-Dienst 127.0.0.1") as e:
        P.Dienst(dienst.url).liste()
    assert e.value.status == status and text in str(e.value)


def test_umleitungen_werden_nicht_verfolgt(dienst):
    # die Kopfzeile des Dienstes darf nicht an eine andere Adresse gehen
    dienst.routen[("GET", "/api/inbox/list")] = (302, "", {"Location": dienst.url + "/woanders"})
    dienst.routen[("GET", "/woanders")] = _liste(_nachricht())
    with pytest.raises(QuelleFehler, match="Umleitungen werden nicht verfolgt") as e:
        P.Dienst(dienst.url, {"X-Geheim": "1"}).liste()
    assert e.value.status == 302
    assert [a["pfad"] for a in dienst.aufrufe] == ["/api/inbox/list"]


def test_ein_dienst_der_nicht_antwortet_ist_ein_fehler():
    with Attrappe() as a:
        url = a.url
    with pytest.raises(QuelleFehler, match="nicht erreichbar"):
        P.Dienst(url).liste()
    with pytest.raises(QuelleFehler, match="keine gültige URL"):
        P.Dienst("mail.example").liste()


def test_zeitueberschreitung_wird_benannt(dienst, monkeypatch):
    monkeypatch.setattr(P, "FRIST_LESEN_S", 0.3)
    dienst.routen[("GET", "/api/inbox/list")] = lambda a: (time.sleep(1.5), _liste())[1]
    with pytest.raises(QuelleFehler, match=r"nicht erreichbar \(Zeitüberschreitung\)"):
        P.Dienst(dienst.url).liste()


def test_zu_grosse_antworten_werden_abgelehnt(dienst, monkeypatch):
    monkeypatch.setattr(P, "ANTWORT_MAX", 200)
    dienst.routen[("GET", "/api/inbox/list")] = _liste(*[_nachricht(id=f"m{i:08d}") for i in range(10)])
    with pytest.raises(QuelleFehler, match="zu groß"):
        P.Dienst(dienst.url).liste()


def test_der_haken_ersetzt_das_netz():
    gesehen: list[tuple[str, float]] = []

    def aufruf(pfad: str, frist: float) -> tuple[int, Any]:
        gesehen.append((pfad, frist))
        return _liste(_nachricht())[1] and (200, _liste(_nachricht())[1]) if pfad.startswith("/api/inbox/list") \
            else (200, {"inbox_unread": 4})

    ergebnis = P.Dienst("http://egal.example", aufruf=aufruf).liste("in:inbox", 2)
    assert [m["id"] for m in ergebnis["mails"]] == [ID1] and ergebnis["ungelesen"] == 4
    assert gesehen[0][0] == "/api/inbox/list?q=in%3Ainbox&limit=2"
    assert gesehen[1][0] == "/api/inbox/unread-count"
    assert gesehen[0][1] == P.FRIST_LESEN_S


def test_der_dienst_hat_ein_konto(dienst):
    q = P.Dienst(dienst.url)
    assert q.konten() == [{"name": "dienst", "art": "dienst", "adresse": dienst.url.removeprefix("http://")}]
    dienst.routen[("GET", "/api/inbox/list")] = _liste(_nachricht())
    assert len(q.liste(konto="dienst", zaehlen=False)["mails"]) == 1
    assert len(q.liste(konto="DIENST", zaehlen=False)["mails"]) == 1
    assert len(q.liste(konto="", zaehlen=False)["mails"]) == 1
    n = len(dienst.aufrufe)
    with pytest.raises(ValueError, match="privat"):
        q.liste(konto="privat")
    assert len(dienst.aufrufe) == n  # ein unbekanntes Konto erreicht den Dienst nicht
    with pytest.raises(ValueError, match="konto"):
        q.liste(konto=5)
    with pytest.raises(ValueError, match="konto"):
        q.liste(konto="x" * 61)


def test_eingaben_werden_geprueft_bevor_der_dienst_etwas_sieht(dienst):
    q = P.Dienst(dienst.url)
    for schlecht in (0, 101, -1, "x", None, 2.5, True, [3]):
        with pytest.raises(ValueError, match="anzahl"):
            q.liste("in:inbox", schlecht)
    assert len(dienst.routen) == 0 and q.liste.__name__ == "liste"
    for schlecht in (5, ["in:inbox"], b"x"):
        with pytest.raises(ValueError, match="abfrage"):
            q.liste(schlecht)
    with pytest.raises(ValueError, match="abfrage"):
        q.liste("x" * 301)
    assert dienst.aufrufe == []
    dienst.routen[("GET", "/api/inbox/list")] = _liste()
    assert q.liste("in:inbox", "100", zaehlen=False)["mails"] == []  # eine Zahl als Text geht
    assert dienst.aufrufe[0]["abfrage"]["limit"] == "100"


def test_der_dienst_liefert_nie_mehr_als_verlangt(dienst):
    dienst.routen[("GET", "/api/inbox/list")] = _liste(*[_nachricht(id=f"m{i:08d}") for i in range(5)])
    assert len(P.Dienst(dienst.url).liste("in:inbox", 3, zaehlen=False)["mails"]) == 3


# ── Mail-Dienst: eine Mail lesen ────────────────────────────────────────────────────────────────────────
def test_der_dienst_liefert_eine_volle_mail(dienst):
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (200, _detail())
    mail = P.Dienst(dienst.url, {"X-Innen": "ja"}).lesen(ID1)
    assert list(mail) == ["id", "konto", "von", "an", "betreff", "datum", "gelesen", "labels", "ausschnitt", "text",
                          "gekuerzt", "anhaenge"]
    assert mail == {
        "id": ID1, "konto": "dienst", "von": "Alex Muster <alex@example.org>", "an": "ich@example.org",
        "betreff": "Hallo", "datum": "2026-10-06T10:09:09+00:00", "gelesen": False,
        "labels": ["Posteingang", "Privat"], "ausschnitt": "x", "text": "Zeile 1\nZeile 2", "gekuerzt": False,
        "anhaenge": [{"name": "rechnung.pdf", "typ": "application/pdf", "groesse": 1234}],
    }
    aufruf = dienst.aufrufe[0]
    assert (aufruf["methode"], aufruf["pfad"]) == ("GET", f"/api/inbox/message/{ID1}")
    assert aufruf["kopf"]["x-innen"] == "ja"


def test_nur_html_wird_zu_text(dienst):
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (200, _detail(
        body_plain="  \n", body_html="<style>x{}</style><p>Hallo&nbsp;<b>Welt</b></p><br>Ende", attachments=None))
    mail = P.Dienst(dienst.url).lesen(ID1)
    assert mail["text"] == "Hallo Welt\n\nEnde" and mail["anhaenge"] == [] and mail["gekuerzt"] is False


def test_zu_langer_text_wird_gekuerzt_und_gemeldet(dienst):
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (200, _detail(body_plain="Zeile\n" * 20000))
    mail = P.Dienst(dienst.url).lesen(ID1)
    assert len(mail["text"]) == P.TEXT_MAX and mail["gekuerzt"] is True
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (200, _detail(body_plain="x" * P.TEXT_MAX))
    mail = P.Dienst(dienst.url).lesen(ID1)
    assert len(mail["text"]) == P.TEXT_MAX and mail["gekuerzt"] is False


def test_die_kennung_geht_unveraendert_in_den_pfad(dienst):
    kennung = "privat.inbox.1699999999.4711~a=b-c_d"
    dienst.routen[("GET", f"/api/inbox/message/{kennung}")] = (200, _detail(id=kennung))
    assert P.Dienst(dienst.url).lesen(kennung)["id"] == kennung
    assert dienst.aufrufe[0]["roh"] == f"/api/inbox/message/{kennung}"


def test_eine_unbekannte_mail_ist_ein_fehler_mit_status_404(dienst):
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (404, {"detail": "Not Found"})
    with pytest.raises(QuelleFehler, match="kennt diese Mail nicht") as e:
        P.Dienst(dienst.url).lesen(ID1)
    assert e.value.status == 404


@pytest.mark.parametrize("antwort, status, text", [
    ((503, {"detail": "Gmail wackelt"}), 503, "Gmail wackelt"),
    ((502, "<html>"), 502, "HTTP 502"),
    ((401, "nein"), 401, "FYOS_POSTFACH_KOPF"),
    ((200, "<html>"), 502, "nicht mit lesbaren Daten"),
])
def test_fehler_beim_lesen_sind_fehler_mit_grund(dienst, antwort, status, text):
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = antwort
    with pytest.raises(QuelleFehler) as e:
        P.Dienst(dienst.url).lesen(ID1)
    assert e.value.status == status and text in str(e.value)


@pytest.mark.parametrize("schlecht", ["", ".", "..", "-x", ".x", "a/b", "../x", "a b", "a?b=1", "a" * 201, "ä", "a\n",
                                      "a%2Fb", None, 5, b"abc", ["a"]])
def test_ungueltige_kennungen_erreichen_die_quelle_nie(dienst, schlecht):
    with pytest.raises(ValueError, match="id"):
        P.Dienst(dienst.url).lesen(schlecht)
    ablage = Mailablage()
    P.ablage_anmelden(ablage)
    with pytest.raises(ValueError, match="id"):
        P.quelle().lesen(schlecht)
    assert dienst.aufrufe == [] and ablage.gelesen == []


@pytest.mark.parametrize("gut", ["a", ID1, "privat.inbox.1699999999.4711", "k-1.SU5CT1g~x.12.345", "AAMkAGI2=", "a" * 200])
def test_gueltige_kennungen(gut):
    assert P.ID_MUSTER.fullmatch(gut)


# ── Mail-Plugin als Ablage ──────────────────────────────────────────────────────────────────────────────
def test_die_ablage_liefert_mails_im_mailformat():
    ablage = Mailablage([
        _m(),
        {"id": "roh.1", "betreff": "  Nur\nein Betreff ", "datum": datetime(2026, 10, 6, 9, 0), "gelesen": True,
         "labels": ["Wichtig", "Wichtig", "", 5, None, "x" * 100], "ausschnitt": "y" * 300, "von": 5},
        {"betreff": "ohne Kennung"},
        _m(id="../etc/passwd"),
        _m(id=7),
        "kein Objekt",
    ])
    P.ablage_anmelden(ablage)
    q = P.quelle()
    ergebnis = q.liste("from:alex is:unread", 5, "privat")
    assert ablage.aufrufe == [("from:alex is:unread", 5, "privat")]
    assert ergebnis["ungelesen"] == 7
    erste, zweite = ergebnis["mails"]
    assert erste == _m()
    assert list(zweite) == list(erste)
    assert zweite["id"] == "roh.1" and zweite["betreff"] == "Nur ein Betreff"
    assert zweite["konto"] == "" and zweite["an"] == "" and zweite["von"] == "5"
    assert zweite["datum"] == "2026-10-06T09:00:00+00:00" and zweite["gelesen"] is True
    assert zweite["labels"] == ["Wichtig", "x" * 60] and len(zweite["ausschnitt"]) == 200
    # die Anzahl begrenzt auch, was ein Plugin zu viel liefert; ohne Konto fragt der Kern alle
    ablage.mails = [_m(id=f"m{i:05d}") for i in range(10)]
    assert len(q.liste("in:inbox", 4)["mails"]) == 4
    assert ablage.aufrufe[-1] == ("in:inbox", 4, None)


def test_die_ablage_zaehlt_nur_wenn_gefragt():
    ablage = Mailablage([_m()])
    P.ablage_anmelden(ablage)
    q = P.quelle()
    assert q.liste()["ungelesen"] == 7
    assert q.liste(zaehlen=False)["ungelesen"] is None
    for roh in (None, "7", -1, True, 2.0):
        ablage.ungelesen = roh
        assert q.liste()["ungelesen"] is None


def test_die_ablage_nennt_ihre_konten():
    P.ablage_anmelden(Mailablage())
    assert P.quelle().konten() == [
        {"name": "privat", "art": "imap", "adresse": "imap.example.org:993", "nutzer": "ich@example.org"},
        {"name": "arbeit", "art": "gmail", "adresse": "imap.example.net:993", "fehler": "Passwort fehlt"},
    ]


def test_die_ablage_liest_eine_mail():
    ablage = Mailablage()
    P.ablage_anmelden(ablage)
    mail = P.quelle().lesen("privat.inbox.1699999999.4711")
    assert ablage.gelesen == ["privat.inbox.1699999999.4711"]
    # die Kennung ist die angefragte, auch wenn das Plugin eine andere nennt; Text bereinigt, Anhänge geprüft
    assert mail["id"] == "privat.inbox.1699999999.4711"
    assert mail["text"] == "Zeile 1\nZeile 2" and mail["gekuerzt"] is False
    assert mail["anhaenge"] == [{"name": "rechnung.pdf", "typ": "application/pdf", "groesse": 1234},
                                {"name": "(ohne Namen)", "typ": "", "groesse": None}]
    assert (mail["konto"], mail["betreff"], mail["datum"], mail["gelesen"]) == (
        "privat", "Hallo", "2026-10-06T12:09:09+02:00", False)


def test_die_ablage_kann_gekuerzt_melden():
    class Gekuerzt(Mailablage):
        def ablage_lesen(self, id: str) -> Any:  # noqa: A002
            return {"text": "x" * (P.TEXT_MAX + 5), "anhaenge": [{"name": f"a{i}"} for i in range(80)]}

    P.ablage_anmelden(Gekuerzt())
    mail = P.quelle().lesen(ID1)
    assert len(mail["text"]) == P.TEXT_MAX and mail["gekuerzt"] is True and len(mail["anhaenge"]) == P.ANHAENGE_MAX

    class Selbst(Mailablage):
        def ablage_lesen(self, id: str) -> Any:  # noqa: A002
            return {"text": "kurz", "gekuerzt": True}

    P.ablage_anmelden(Selbst())
    mail = P.quelle().lesen(ID1)
    assert (mail["text"], mail["gekuerzt"], mail["anhaenge"], mail["betreff"]) == ("kurz", True, [], "(kein Betreff)")


def test_fehler_der_ablage_zeigen_nie_den_text_fremder_ausnahmen():
    ablage = Mailablage([_m()])
    P.ablage_anmelden(ablage)
    q = P.quelle()

    ablage.fehler = RuntimeError("Anmeldung mit Passwort hunter2 abgelehnt")
    for aufruf in (q.konten, lambda: q.liste(), lambda: q.lesen(ID1)):
        with pytest.raises(QuelleFehler) as e:
            aufruf()
        assert "RuntimeError" in str(e.value) and "hunter2" not in str(e.value) and e.value.status == 502

    # eigene Fehler des Plugins mit verständlichem Text gehen durch
    ablage.fehler = QuelleFehler("Anmeldung abgelehnt (App-Passwort prüfen)", 401)
    with pytest.raises(QuelleFehler, match="App-Passwort prüfen") as e:
        q.liste()
    assert e.value.status == 401
    # auch die Fehlerklasse der Vorgänge wird zu einem Fehler des Postfachs
    ablage.fehler = vorgaenge.QuelleFehler("Postfach spinnt", 503)
    with pytest.raises(QuelleFehler, match="Postfach spinnt") as e:
        q.liste()
    assert type(e.value) is QuelleFehler and e.value.status == 503
    # „nicht eingerichtet“ vom Plugin bleibt „nicht eingerichtet“ (ein Plugin ohne Konto)
    ablage.fehler = NichtEingerichtet("Kein Konto eingetragen")
    with pytest.raises(NichtEingerichtet, match="Kein Konto"):
        q.liste()
    # falsche Eingabe bleibt falsche Eingabe
    ablage.fehler = ValueError("konto 'x' gibt es nicht")
    with pytest.raises(ValueError, match="gibt es nicht"):
        q.liste("in:inbox", 5, "x")
    ablage.fehler = NotImplementedError()
    with pytest.raises(QuelleFehler, match="kann das nicht") as e:
        q.lesen(ID1)
    assert e.value.status == 501


def test_eine_ablage_mit_unbrauchbaren_antworten():
    class Unbrauchbar:
        def ablage_konten(self) -> Any:
            return "viele"

        def ablage_liste(self, abfrage: str, anzahl: int, konto: str | None = None) -> Any:
            return [1, 2]

        def ablage_lesen(self, id: str) -> Any:  # noqa: A002
            return None

    P.ablage_anmelden(Unbrauchbar())  # type: ignore[arg-type]
    q = P.quelle()
    assert q.beschreibung() == "Mail-Plugin"
    with pytest.raises(QuelleFehler, match="ohne Kontenliste"):
        q.konten()
    with pytest.raises(QuelleFehler, match="ohne Mailliste"):
        q.liste()
    with pytest.raises(QuelleFehler, match="nicht geliefert"):
        q.lesen(ID1)

    class OhneMails(Unbrauchbar):
        def ablage_liste(self, abfrage: str, anzahl: int, konto: str | None = None) -> Any:
            return {"ungelesen": 3}

    P.ablage_anmelden(OhneMails())  # type: ignore[arg-type]
    with pytest.raises(QuelleFehler, match="ohne Mailliste"):
        P.quelle().liste()


def test_die_ablage_meldet_sich_ab():
    ablage = Mailablage()
    P.ablage_anmelden(ablage)
    assert P.angemeldete_ablage() is ablage
    P.ablage_anmelden(None)
    assert P.angemeldete_ablage() is None and P.quelle().art == "keine"


# ── nur lesen ───────────────────────────────────────────────────────────────────────────────────────────
def test_die_quellen_haben_nur_lesende_methoden():
    erlaubt = {"art", "eingerichtet", "beschreibung", "konten", "liste", "lesen", "als_dict", "roh", "ablage", "url", "kopf"}
    for klasse in (P.Quelle, P.AblageQuelle, P.Dienst):
        oeffentlich = {n for n in dir(klasse) if not n.startswith("_")}
        assert oeffentlich <= erlaubt, oeffentlich - erlaubt
    # ein Mail-Plugin bietet als Ablage genau drei lesende Methoden an
    assert {n for n in vars(P.Ablage) if n.startswith("ablage_")} == {"ablage_konten", "ablage_liste", "ablage_lesen"}


def test_der_dienst_kennt_nur_drei_routen(dienst):
    dienst.routen[("GET", "/api/inbox/list")] = _liste(_nachricht())
    dienst.routen[("GET", "/api/inbox/unread-count")] = (200, {"inbox_unread": 1})
    dienst.routen[("GET", f"/api/inbox/message/{ID1}")] = (200, _detail())
    q = P.Dienst(dienst.url)
    q.konten()
    q.liste()
    q.lesen(ID1)
    muster = ("/api/inbox/list", "/api/inbox/unread-count", f"/api/inbox/message/{ID1}")
    assert [a["pfad"] for a in dienst.aufrufe] == list(muster)
    verboten = ("send", "reply", "forward", "labels", "drafts", "extract", "modify", "trash")
    assert not [a for a in dienst.aufrufe if any(v in a["pfad"] for v in verboten)]


# ── Abfragesprache ──────────────────────────────────────────────────────────────────────────────────────
def test_die_abfrage_teilmenge_ist_dokumentiert():
    for baustein in ("from:", "to:", "subject:", "is:unread", "newer_than:", "older_than:", "in:inbox", "freie Wörter",
                     "-category:promotions", "nie als Fehler"):
        assert baustein in P.__doc__, baustein


# ── Hilfen ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("roh, erwartet", [
    ("Tue, 06 Oct 2026 10:09:09 +0000 (UTC)", "2026-10-06T10:09:09+00:00"),
    ("Wed, 07 Oct 2026 09:00:00 +0200", "2026-10-07T09:00:00+02:00"),
    ("Wed, 07 Oct 2026 09:00:00 -0000", "2026-10-07T09:00:00+00:00"),
    ("Wed, 07 Oct 2026 09:00:00 GMT", "2026-10-07T09:00:00+00:00"),
    ("2026-10-07T09:00:00+02:00", "2026-10-07T09:00:00+02:00"),
    ("2026-10-07T09:00:00Z", "2026-10-07T09:00:00+00:00"),
    ("2026-10-07 09:00", "2026-10-07T09:00:00+00:00"),
    (datetime(2026, 10, 7, 9, 0, tzinfo=timezone(timedelta(hours=2))), "2026-10-07T09:00:00+02:00"),
    (datetime(2026, 10, 7, 9, 0), "2026-10-07T09:00:00+00:00"),
    ("", ""), ("   ", ""), (None, ""), ("gestern", ""), (5, ""), ("Wed, 99 Foo 2026 25:61:61 +0200", ""),
])
def test_datum_aus(roh, erwartet):
    assert P.datum_aus(roh) == erwartet


def test_html_wird_zu_text():
    html = ("<html><head><title>Titel</title><style>p{color:red}</style></head><body><p>Hallo&nbsp;<b>Welt</b></p>"
            "<script>alert(1)</script><br>Zeile<br/>Ende<table><tr><td>a</td><td>b</td></tr></table>"
            "<ul><li>eins</li><li>zwei &amp; drei</li></ul></body></html>")
    assert P.text_aus_html(html) == "Hallo Welt\n\nZeile\nEnde\n\na b\n\neins\nzwei & drei"
    assert P.text_aus_html("") == "" and P.text_aus_html(None) == ""
    # ein ungeschlossenes <head> verschluckt den Text nicht, ein ungeschlossenes <style> nur den Rest
    assert P.text_aus_html("<head><title>T</title><body>Text") == "Text"
    assert P.text_aus_html("Vorher<style>p{}") == "Vorher"
    assert P.text_aus_html("Text mit < kleiner und &gt; größer") == "Text mit < kleiner und > größer"


def test_boesartiges_html_braucht_keine_quadratische_zeit():
    start = time.perf_counter()
    for boese in ("<script>" * 40000, "<p>" * 60000, "&amp;" * 200000, "<a " * 30000 + "x" * 200000,
                  "<!-- " * 200 + "x" * 200000):
        P.text_aus_html(boese)
    assert time.perf_counter() - start < 10


def test_labels_de():
    assert P.labels_de(["INBOX", "UNREAD", "Label_31", "CATEGORY_PROMOTIONS", "INBOX", 5, None]) == ["Posteingang", "Werbung"]
    assert P.labels_de(None) == [] and P.labels_de("INBOX") == []


def test_mail_aus_raeumt_auf():
    m = P.mail_aus({"id": "abc", "betreff": "Hallo\x00Welt\n zwei", "von": "A\x07B", "gelesen": 1})
    assert m is not None
    assert (m["betreff"], m["von"], m["gelesen"], m["labels"], m["datum"]) == ("HalloWelt zwei", "AB", True, [], "")
    assert P.mail_aus({"id": ""}) is None and P.mail_aus({}) is None
