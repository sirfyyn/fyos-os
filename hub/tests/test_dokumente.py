"""Dokumente für Plugins (``mcp_hub.dokumente``): Dokumenten-Dienst (Paperless-ngx), Ablage oder keine Quelle.

Paperless ist ein kleiner HTTP-Server im Thread (kein Netz nach außen); die Ablage eine Attrappe im Speicher. Echte
Dokumente, echte Zugänge und ein echtes Paperless kommen nirgends vor.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from mcp_hub import dokumente as D
from mcp_hub import vorgaenge
from mcp_hub.dokumente import NichtEingerichtet, QuelleFehler

TOKEN = "testwert-nur-fuer-die-pruefung"
KOPF = f"Authorization: Token {TOKEN}"


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    for name in ("FYOS_DOKUMENTE_URL", "FYOS_DOKUMENTE_KOPF", "FYOS_DOKUMENTE_LINK"):
        monkeypatch.delenv(name, raising=False)
    # Die Attrappe läuft auf 127.0.0.1; ein Proxy der Umgebung soll sie nicht umleiten.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    D.ablage_anmelden(None)
    D.dienst_anmelden(None)
    D.namen_vergessen()
    yield
    D.ablage_anmelden(None)
    D.dienst_anmelden(None)
    D.namen_vergessen()


# ── Attrappen ───────────────────────────────────────────────────────────────────────────────────────────
class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:  # abgebrochene Anfragen sind hier gewollt
        return None


class Attrappe:
    """Ein HTTP-Dienst im Thread. ``routen`` bildet ``(Methode, Pfad)`` auf eine Antwort ab: ``(Status, Inhalt)``,
    ``(Status, Inhalt, Kopfzeilen)`` oder eine Funktion, die den Aufruf bekommt und so etwas liefert. Jede Anfrage landet
    in ``aufrufe``."""

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
                route = attrappe.routen.get((self.command, teile.path), (404, {"detail": "Not found."}))
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

    def methoden(self) -> set[str]:
        return {x["methode"] for x in self.aufrufe}

    def an(self, pfad: str, methode: str = "GET") -> list[dict[str, Any]]:
        return [x for x in self.aufrufe if x["pfad"] == pfad and x["methode"] == methode]


DOC_NEU = {
    "id": 40, "title": "scan_0001.pdf", "created": "2026-10-01", "added": "2026-10-09T18:00:00+02:00",
    "tags": [2], "correspondent": None, "document_type": None, "original_file_name": "scan_0001.pdf",
    "page_count": 2, "content": "Stadtwerke Beispielstadt\nRechnung Nr. 117\nBitte den Betrag überweisen.",
}
DOC_ALT = {
    "id": 41, "title": "Steuerbescheid 2025", "created": "2026-05-02T00:00:00+02:00", "added": "2026-10-01T09:30:00+02:00",
    "tags": [1, 2], "correspondent": 5, "document_type": 7, "original_file_name": "bescheid.pdf", "page_count": 3,
    "content": "Ihr Bescheid für 2025 liegt vor.",
}


class Paperless:
    """Ein Paperless-ngx im Speicher auf der Attrappe: Dokumente, Schlagworte, Korrespondenten, Typen; lesen, suchen,
    zählen, anlegen, ändern."""

    def __init__(self, a: Attrappe, *, token: str | None = TOKEN) -> None:
        self.a = a
        self.token = token
        self.docs = {d["id"]: copy.deepcopy(d) for d in (DOC_NEU, DOC_ALT)}
        self.listen = {
            "tags": {1: "Steuer", 2: "Eingang"},
            "correspondents": {5: "Finanzamt"},
            "document_types": {7: "Bescheid"},
        }
        self.naechste = 100
        a.routen[("GET", "/api/documents/")] = self._dokumente
        for art in self.listen:
            a.routen[("GET", f"/api/{art}/")] = lambda x, art=art: self._namen(x, art)
            a.routen[("POST", f"/api/{art}/")] = lambda x, art=art: self._anlegen(x, art)
        for kennung in self.docs:
            a.routen[("GET", f"/api/documents/{kennung}/")] = lambda x, k=kennung: self._geschuetzt(x, (200, self.docs[k]))
            a.routen[("PATCH", f"/api/documents/{kennung}/")] = lambda x, k=kennung: self._aendern(x, k)

    def _geschuetzt(self, x: dict[str, Any], antwort: tuple[int, Any]) -> tuple[int, Any]:
        if self.token is not None and x["kopf"].get("authorization") != f"Token {self.token}":
            return 401, {"detail": "Invalid token."}
        return antwort

    def _dokumente(self, x: dict[str, Any]) -> tuple[int, Any]:
        q = x["abfrage"]
        n = int(q.get("page_size", 25))
        if self.token is not None and x["kopf"].get("authorization") != f"Token {self.token}":
            return 401, {"detail": "Invalid token."}
        if "correspondent__isnull" in q:
            ohne = [d for d in self.docs.values() if not d["correspondent"] and not d["document_type"]]
            return 200, {"count": len(ohne), "results": [{"id": d["id"]} for d in ohne][:n]}
        if "query" in q:
            worte = q["query"].casefold().split()
            treffer = [d for d in self.docs.values() if all(w in (d["title"] + " " + d["content"]).casefold() for w in worte)]
            ergebnis = []
            for d in treffer[:n]:
                zeile = copy.deepcopy(d)
                zeile["__search_hit__"] = {"score": 1.0, "highlights": f"Ihr <b>{q['query']}</b> &amp; mehr\n<i>fett</i>", "rank": 0}
                ergebnis.append(zeile)
            return 200, {"count": len(treffer), "results": ergebnis}
        neueste = sorted(self.docs.values(), key=lambda d: d["added"], reverse=True)
        felder = q["fields"].split(",") if "fields" in q else None
        ergebnis = [{k: v for k, v in d.items() if felder is None or k in felder} for d in neueste[:n]]
        return 200, {"count": len(self.docs), "results": ergebnis}

    def _namen(self, x: dict[str, Any], art: str) -> tuple[int, Any]:
        if self.token is not None and x["kopf"].get("authorization") != f"Token {self.token}":
            return 401, {"detail": "Invalid token."}
        eintraege = [{"id": k, "name": v} for k, v in self.listen[art].items()]
        return 200, {"count": len(eintraege), "next": None, "previous": None, "results": eintraege}

    def _anlegen(self, x: dict[str, Any], art: str) -> tuple[int, Any]:
        name = json.loads(x["rumpf"])["name"]
        self.naechste += 1
        self.listen[art][self.naechste] = name
        return 201, {"id": self.naechste, "name": name}

    def _aendern(self, x: dict[str, Any], kennung: int) -> tuple[int, Any]:
        self.docs[kennung].update(json.loads(x["rumpf"]))
        return 200, self.docs[kennung]


@pytest.fixture
def paperless():
    with Attrappe() as a:
        a.pl = Paperless(a)
        yield a


def _dienst(a: Attrappe, **kw: Any) -> D.Dienst:
    return D.Dienst(a.url, D.kopf_aus(KOPF), **kw)


class Ablage:
    """Eine Ablage im Speicher (ein Plugin, das Dokumente liefert)."""

    name = "ordner"

    def __init__(self) -> None:
        self.aufrufe: list[tuple[Any, ...]] = []
        self.docs = [
            {"id": 3, "titel": "Notiz\tvom   Montag", "erstellt": "2026-10-05", "hinzugefuegt": "2026-10-06T08:00:00",
             "schlagworte": ["Notiz", "Notiz", ""], "datei": "notiz.txt", "seiten": 1, "auszug": "ein  Treffer",
             "link": "https://dok.example.org/3", "text": "Hallo\r\nWelt"},
            {"id": 2, "titel": "Alt", "text": "x" * 25_000},
            {"id": "kaputt", "titel": "ohne Kennung"},
        ]

    def ablage_neueste(self, anzahl: int) -> dict[str, Any]:
        self.aufrufe.append(("neueste", anzahl))
        return {"gesamt": 7, "dokumente": self.docs}

    def ablage_suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        self.aufrufe.append(("suchen", abfrage, anzahl))
        return {"gesamt": 1, "dokumente": self.docs[:1]}

    def ablage_holen(self, id: int) -> dict[str, Any]:  # noqa: A002
        self.aufrufe.append(("holen", id))
        return next(d for d in self.docs if d["id"] == id)

    def ablage_unsortiert(self) -> int | None:
        return 4

    def ablage_namen(self) -> dict[str, list[str]]:
        return {"schlagworte": ["b", "A"], "korrespondenten": ["Z"], "typen": []}

    def ablage_zuordnen(self, id: int, aenderung: dict[str, Any], vorschau: bool) -> dict[str, Any]:  # noqa: A002
        self.aufrufe.append(("zuordnen", id, aenderung, vorschau))
        vorher = {"id": id, "titel": "Alt"}
        if vorschau:
            return {"vorher": vorher, "aendert": aenderung, "wird_angelegt": ["Typ X"]}
        return {"vorher": vorher, "nachher": {"id": id, "titel": aenderung.get("titel", "Alt")}, "angelegt": []}


class NurLesen:
    """Eine Ablage ohne die optionalen Methoden."""

    def ablage_neueste(self, anzahl: int) -> dict[str, Any]:
        return {"gesamt": 0, "dokumente": []}

    def ablage_suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        return {"gesamt": 0, "dokumente": []}

    def ablage_holen(self, id: int) -> dict[str, Any]:  # noqa: A002
        return {}

    def ablage_unsortiert(self) -> int | None:
        return None


# ── Keine Quelle, Fehlerklassen, Reihenfolge ────────────────────────────────────────────────────────────
def test_ohne_dienst_und_ohne_ablage_ist_nichts_eingerichtet():
    q = D.quelle()
    assert (q.art, q.eingerichtet) == ("keine", False)
    for aufruf in (q.neueste, lambda: q.suchen("steuer"), lambda: q.holen(1), q.unsortiert, q.namen,
                   lambda: q.zuordnen(1, {"titel": "Neu"})):
        with pytest.raises(NichtEingerichtet) as e:
            aufruf()
        assert e.value.status == 501
        assert "FYOS_DOKUMENTE_URL" in str(e.value) and "Paperless" in str(e.value)
    assert q.als_dict() == {"art": "keine", "eingerichtet": False, "beschreibung": q.beschreibung()}


def test_falsche_eingabe_ist_auch_ohne_quelle_falsche_eingabe():
    q = D.quelle()
    for aufruf in (lambda: q.neueste(0), lambda: q.neueste(51), lambda: q.suchen("x"), lambda: q.holen("abc"),
                   lambda: q.zuordnen(1, {})):
        with pytest.raises(ValueError):
            aufruf()


def test_die_fehlerklassen_haengen_so_zusammen():
    assert issubclass(QuelleFehler, vorgaenge.QuelleFehler)
    assert issubclass(NichtEingerichtet, QuelleFehler)
    assert not issubclass(NichtEingerichtet, vorgaenge.NichtEingerichtet)
    assert QuelleFehler("x", 503).status == 503


def test_reihenfolge_adresse_angemeldeter_dienst_umgebung_ablage(monkeypatch):
    ablage = Ablage()
    D.ablage_anmelden(ablage)
    assert D.quelle().art == "ablage" and D.angemeldete_ablage() is ablage
    monkeypatch.setenv("FYOS_DOKUMENTE_URL", "http://umgebung.example.org/")
    monkeypatch.setenv("FYOS_DOKUMENTE_KOPF", "Authorization: Token aus-der-umgebung")
    monkeypatch.setenv("FYOS_DOKUMENTE_LINK", "https://dok.example.org/")
    q = D.quelle()
    assert (q.art, q.url, q.kopf, q.link) == (
        "dienst", "http://umgebung.example.org", {"Authorization": "Token aus-der-umgebung"}, "https://dok.example.org")
    D.dienst_anmelden("http://angemeldet.example.org/", {"X-Test": "1"}, "https://angemeldet.example.org/")
    q = D.quelle()
    assert (q.url, q.kopf, q.link) == ("http://angemeldet.example.org", {"X-Test": "1"}, "https://angemeldet.example.org")
    assert D.angemeldeter_dienst() == ("http://angemeldet.example.org", {"X-Test": "1"}, "https://angemeldet.example.org/")
    q = D.quelle(url="http://argument.example.org", kopf="X-Andere: 2", link="")
    assert (q.url, q.kopf, q.link) == ("http://argument.example.org", {"X-Andere": "2"}, None)
    assert D.quelle(url="  ").url == "http://angemeldet.example.org"  # leer zählt als nicht angegeben
    D.dienst_anmelden(None)
    assert D.quelle().url == "http://umgebung.example.org"
    monkeypatch.delenv("FYOS_DOKUMENTE_URL")
    assert D.quelle().art == "ablage"
    D.ablage_anmelden(None)
    assert D.quelle().art == "keine"


def test_kaputte_kopfzeilen_werden_nicht_gesendet():
    for kaputt in ("", "ohne doppelpunkt", ":nur-wert", "Name:", "Na me: x", "Name: a\nb"):
        assert D.Dienst("http://x.example.org", D.kopf_aus(kaputt)).kopf == {}


def test_die_beschreibung_nennt_nie_zugangsdaten():
    d = D.Dienst("http://nutzer:geheimwort" + "@" + "dok.example.org:8000/pfad", D.kopf_aus(KOPF))  # Zugang in der Adresse
    text = d.beschreibung() + str(d.als_dict())
    assert "dok.example.org:8000" in text
    assert "geheimwort" not in text and TOKEN not in text and "nutzer" not in text
    assert D.Dienst("kein-url").beschreibung() == "Paperless"


# ── Dienst: Listen, Suche, Zähler ───────────────────────────────────────────────────────────────────────
def test_der_dienst_liefert_dokumente_im_dokumentformat(paperless):
    q = _dienst(paperless, link="https://dok.example.org/")
    antwort = q.neueste(5)
    assert antwort["gesamt"] == 2
    neu, alt = antwort["dokumente"]  # neueste zuerst
    assert neu == {
        "id": 40, "titel": "scan_0001.pdf", "erstellt": "2026-10-01", "hinzugefuegt": "2026-10-09T18:00:00+02:00",
        "schlagworte": ["Eingang"], "korrespondent": None, "typ": None, "datei": "scan_0001.pdf", "seiten": 2,
        "auszug": None, "link": "https://dok.example.org/documents/40/details",
    }
    assert alt["erstellt"] == "2026-05-02"  # Zeitstempel und Datum landen im selben Format
    assert (alt["korrespondent"], alt["typ"], alt["schlagworte"]) == ("Finanzamt", "Bescheid", ["Steuer", "Eingang"])
    assert set(neu) == set(alt)
    abfrage = paperless.an("/api/documents/")[0]["abfrage"]
    assert abfrage["ordering"] == "-added" and abfrage["page_size"] == "5" and "original_file_name" in abfrage["fields"]
    assert paperless.methoden() == {"GET"}


def test_ohne_browser_adresse_gibt_es_keine_links(paperless):
    assert [d["link"] for d in _dienst(paperless).neueste()["dokumente"]] == [None, None]
    for schlecht in ("javascript:alert(1)", "ftp://x.example.org", "kein link"):
        assert _dienst(paperless, link=schlecht).neueste(1)["dokumente"][0]["link"] is None


def test_der_dienst_liefert_nie_mehr_als_verlangt(paperless):
    antwort = _dienst(paperless).neueste(1)
    assert len(antwort["dokumente"]) == 1 and antwort["gesamt"] == 2


def test_suche_liefert_den_treffer_auszug(paperless):
    antwort = _dienst(paperless).suchen("Bescheid")
    assert antwort["gesamt"] == 1
    treffer = antwort["dokumente"][0]
    assert treffer["id"] == 41 and treffer["titel"] == "Steuerbescheid 2025"
    assert treffer["auszug"] == "Ihr «Bescheid» & mehr fett"  # Markierung, entschlüsselt, übriges HTML weg, eine Zeile
    assert paperless.an("/api/documents/")[0]["abfrage"] == {"query": "Bescheid", "page_size": "10"}


def test_die_suchabfrage_geht_unveraendert_und_richtig_kodiert_an_den_dienst(paperless):
    _dienst(paperless).suchen('tag:eingang "zwei Wörter" &x=1')
    assert paperless.an("/api/documents/")[0]["abfrage"]["query"] == 'tag:eingang "zwei Wörter" &x=1'


def test_suche_ohne_treffer_ist_eine_leere_liste_und_kein_fehler(paperless):
    assert _dienst(paperless).suchen("gibtesnicht") == {"gesamt": 0, "dokumente": []}


def test_die_unsortierten_werden_gezaehlt(paperless):
    q = _dienst(paperless)
    assert q.unsortiert() == 1  # nur das erste Dokument hat weder Korrespondent noch Typ
    abfrage = paperless.an("/api/documents/")[0]["abfrage"]
    assert abfrage["correspondent__isnull"] == "1" and abfrage["document_type__isnull"] == "1" and abfrage["page_size"] == "1"
    paperless.pl.docs[40]["correspondent"] = 5
    assert q.unsortiert() == 0


@pytest.mark.parametrize("antwort", [(500, {"detail": "kaputt"}), (200, {"keinzaehler": 1}), (200, {"count": "viele"})])
def test_ohne_brauchbaren_zaehler_bleibt_die_liste_gueltig(paperless, antwort):
    normal = paperless.routen[("GET", "/api/documents/")]
    paperless.routen[("GET", "/api/documents/")] = lambda x: antwort if "correspondent__isnull" in x["abfrage"] else normal(x)
    q = _dienst(paperless)
    assert q.unsortiert() is None
    assert len(q.neueste()["dokumente"]) == 2


# ── Dienst: Fehler ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", [401, 403])
def test_eine_abgelehnte_anmeldung_ist_ein_fehler_und_nie_keine_dokumente(paperless, status, caplog):
    paperless.pl.token = "ein-anderes-token"
    paperless.routen[("GET", "/api/documents/40/")] = (status, {"detail": "Invalid token."})
    q = _dienst(paperless)
    caplog.set_level(logging.DEBUG)
    for aufruf in (q.neueste, lambda: q.suchen("steuer"), lambda: q.holen(40), q.namen,
                   lambda: q.zuordnen(40, {"titel": "Neu"})):
        with pytest.raises(QuelleFehler) as e:
            aufruf()
        assert e.value.status in (401, 403) and not isinstance(e.value, NichtEingerichtet)
        assert "lehnt die Anmeldung ab" in str(e.value) and "Token prüfen" in str(e.value)
    # nie das Token, nie die Kopfzeile: nicht in Meldungen, nicht im Log
    alles = " ".join([caplog.text, str(e.value), repr(e.value), q.beschreibung(), str(q.als_dict())])
    assert TOKEN not in alles and "ein-anderes-token" not in alles and "Authorization" not in caplog.text
    # ein leeres Ergebnis ist das nicht: das ist der Fall, in dem Paperless antwortet
    assert paperless.methoden() == {"GET"}


def test_unsortiert_verschluckt_eine_abgelehnte_anmeldung_nicht_als_zahl(paperless):
    paperless.pl.token = "ein-anderes-token"
    assert _dienst(paperless).unsortiert() is None  # ohne Zähler; die Listen melden den Fehler (siehe oben)


def test_das_token_geht_als_kopfzeile_an_jede_anfrage(paperless):
    q = _dienst(paperless)
    q.neueste()
    q.suchen("Bescheid")
    q.holen(41)
    q.unsortiert()
    assert paperless.aufrufe and all(x["kopf"].get("authorization") == f"Token {TOKEN}" for x in paperless.aufrufe)
    assert all(x["kopf"].get("user-agent") == "fyos-hub" for x in paperless.aufrufe)


def test_ein_remote_user_kopf_geht_genauso_durch(paperless):
    paperless.pl.token = None
    D.Dienst(paperless.url, D.kopf_aus("Remote-User: dienstkonto")).neueste()
    assert all(x["kopf"].get("remote-user") == "dienstkonto" for x in paperless.aufrufe)


@pytest.mark.parametrize("antwort, status, text", [
    ((500, {"detail": "Datenbank weg"}), 500, "Datenbank weg"),
    ((503, "Bad Gateway"), 503, "HTTP 503"),
    ((404, {"detail": "Not found."}), 404, "Not found."),
    ((200, "kein json"), None, "nicht mit lesbaren Daten"),
    ((200, [1, 2]), None, "nicht mit lesbaren Daten"),
    ((200, {"count": 1}), None, "ohne Dokumentliste"),
])
def test_fehler_des_dienstes_sind_fehler_mit_grund(paperless, antwort, status, text):
    paperless.routen[("GET", "/api/documents/")] = antwort
    with pytest.raises(QuelleFehler) as e:
        _dienst(paperless).neueste()
    assert text in str(e.value) and (status is None or e.value.status == status)


def test_umleitungen_werden_nicht_verfolgt_und_die_kopfzeile_geht_nicht_weiter(paperless):
    with Attrappe() as ziel:
        ziel.routen[("GET", "/api/documents/")] = (200, {"count": 0, "results": []})
        paperless.routen[("GET", "/api/documents/")] = (302, "", {"Location": ziel.url + "/api/documents/"})
        with pytest.raises(QuelleFehler, match="Umleitungen") as e:
            _dienst(paperless).neueste()
        assert e.value.status == 302
        assert ziel.aufrufe == []


def test_ein_dienst_der_nicht_antwortet_ist_ein_fehler():
    with Attrappe() as a:
        url = a.url
    with pytest.raises(QuelleFehler, match="nicht erreichbar") as e:
        D.Dienst(url).neueste()
    assert TOKEN not in str(e.value)
    with pytest.raises(QuelleFehler, match="keine gültige URL"):
        D.Dienst("keine-url").neueste()


def test_zeitueberschreitung_wird_benannt(paperless, monkeypatch):
    monkeypatch.setattr(D, "FRIST_LESEN_S", 0.2)
    paperless.routen[("GET", "/api/documents/")] = lambda x: (time.sleep(1) or (200, {}))
    with pytest.raises(QuelleFehler, match="Zeitüberschreitung"):
        _dienst(paperless).neueste()


def test_zu_grosse_antworten_werden_abgelehnt(paperless, monkeypatch):
    monkeypatch.setattr(D, "ANTWORT_MAX", 200)
    paperless.routen[("GET", "/api/documents/")] = (200, {"count": 0, "results": [], "x": "y" * 500})
    with pytest.raises(QuelleFehler, match="zu groß"):
        _dienst(paperless).neueste()


def test_der_haken_ersetzt_das_netz():
    gesehen: list[tuple[Any, ...]] = []

    def aufruf(pfad: str, frist: float, methode: str = "GET", koerper: Any = None) -> tuple[int, Any]:
        gesehen.append((pfad, frist, methode))
        return 200, {"count": 0, "results": [], "next": None}

    assert D.Dienst("http://x.example.org", aufruf=aufruf).neueste() == {"gesamt": 0, "dokumente": []}
    assert gesehen[0][2] == "GET"


def test_der_dienst_schreibt_nur_mit_post_und_patch():
    q = D.Dienst("http://x.example.org")
    for methode in ("DELETE", "PUT", "HEAD", "get"):
        with pytest.raises(ValueError):
            q.roh("/api/documents/1/", methode=methode)


# ── Dienst: ein Dokument lesen ──────────────────────────────────────────────────────────────────────────
def test_der_dienst_liefert_ein_volles_dokument(paperless):
    d = _dienst(paperless, link="https://dok.example.org").holen(40)
    assert d["id"] == 40 and d["titel"] == "scan_0001.pdf" and d["text_gekuerzt"] is False
    assert d["text"].startswith("Stadtwerke Beispielstadt\nRechnung Nr. 117")
    assert d["link"] == "https://dok.example.org/documents/40/details"
    assert paperless.an("/api/documents/40/")


def test_zu_langer_text_wird_gekuerzt_und_gemeldet(paperless):
    paperless.pl.docs[40]["content"] = "x" * 25_000
    d = _dienst(paperless).holen("40")  # auch als Ziffernfolge
    assert len(d["text"]) == D.TEXT_MAX == 20_000 and d["text_gekuerzt"] is True


def test_steuerzeichen_im_text_fallen_weg_zeilenumbrueche_bleiben(paperless):
    paperless.pl.docs[40]["content"] = "a\x00b\r\nc\x1bd\te"
    assert _dienst(paperless).holen(40)["text"] == "ab\ncd\te"


def test_ein_unbekanntes_dokument_ist_ein_fehler_mit_status_404(paperless):
    with pytest.raises(QuelleFehler, match="kennt dieses Dokument nicht") as e:
        _dienst(paperless).holen(999)
    assert e.value.status == 404


@pytest.mark.parametrize("schlecht", [0, -1, "", "abc", "1/2", "../x", "1 2", 1.5, True, None, 10**12, "١٢"])
def test_ungueltige_kennungen_erreichen_die_quelle_nie(paperless, schlecht):
    with pytest.raises(ValueError, match="Kennung"):
        _dienst(paperless).holen(schlecht)
    assert paperless.aufrufe == []


# ── Dienst: Namen ───────────────────────────────────────────────────────────────────────────────────────
def test_die_namen_kommen_sortiert_und_werden_gemerkt(paperless):
    q = _dienst(paperless)
    assert q.namen() == {"schlagworte": ["Eingang", "Steuer"], "korrespondenten": ["Finanzamt"], "typen": ["Bescheid"]}
    q.neueste()
    q.suchen("Bescheid")
    assert len(paperless.an("/api/tags/")) == 1  # einmal gelesen, danach aus dem Speicher
    paperless.pl.listen["tags"][3] = "Neu"
    assert "Neu" not in _dienst(paperless).namen()["schlagworte"]
    D.namen_vergessen()
    assert "Neu" in _dienst(paperless).namen()["schlagworte"]
    assert len(paperless.an("/api/tags/")) == 2


def test_die_namen_gelten_je_dienst_und_zugang(paperless):
    _dienst(paperless).namen()
    with Attrappe() as zweiter:
        Paperless(zweiter).listen["tags"] = {9: "Fremd"}
        assert D.Dienst(zweiter.url, D.kopf_aus(KOPF)).namen()["schlagworte"] == ["Fremd"]


def test_namen_ueber_mehrere_seiten(paperless):
    seiten = {"1": {"next": "ignoriert", "results": [{"id": 1, "name": "Eins"}]}, "2": {"next": None, "results": [{"id": 2, "name": "Zwei"}]}}
    paperless.routen[("GET", "/api/tags/")] = lambda x: (200, {"count": 2, **seiten[x["abfrage"]["page"]]})
    assert _dienst(paperless).namen()["schlagworte"] == ["Eins", "Zwei"]
    assert [x["abfrage"]["page"] for x in paperless.an("/api/tags/")] == ["1", "2"]  # die Adresse aus "next" wird nie benutzt


def test_ein_unbekanntes_schlagwort_zeigt_seine_kennung(paperless):
    paperless.pl.docs[40]["tags"] = [2, 77]
    assert _dienst(paperless).holen(40)["schlagworte"] == ["Eingang", "77"]


# ── Dienst: Zuordnen ────────────────────────────────────────────────────────────────────────────────────
def test_zuordnen_als_vorschau_aendert_und_legt_nichts_an(paperless):
    antwort = _dienst(paperless).zuordnen(
        40, {"titel": "Stromrechnung", "korrespondent": "Stadtwerke", "typ": "rechnung", "schlagworte_hinzu": ["Strom", "eingang"]},
        vorschau=True)
    assert antwort["vorschau"] is True and antwort["id"] == 40
    assert antwort["vorher"]["titel"] == "scan_0001.pdf" and "nachher" not in antwort
    assert antwort["wird_angelegt"] == ["Korrespondent Stadtwerke", "Typ rechnung", "Schlagwort Strom"]
    assert antwort["aendert"]["titel"] == "Stromrechnung"
    assert paperless.methoden() == {"GET"}  # kein POST, kein PATCH
    assert paperless.pl.docs[40]["title"] == "scan_0001.pdf"


def test_zuordnen_ohne_vorschau_setzt_die_metadaten_und_legt_fehlendes_an(paperless):
    antwort = _dienst(paperless).zuordnen(40, {
        "titel": "Steuerbescheid 2025", "korrespondent": "finanzamt", "typ": "Rechnung",
        "schlagworte_hinzu": ["Steuer", "Eingang", "Neu"],
    })
    assert antwort["vorschau"] is False and antwort["vorher"]["titel"] == "scan_0001.pdf"
    patch = json.loads(paperless.an("/api/documents/40/", "PATCH")[0]["rumpf"])
    assert patch["title"] == "Steuerbescheid 2025"
    assert patch["correspondent"] == 5  # der vorhandene, ohne Groß-/Kleinschreibung gefunden
    assert patch["document_type"] > 100  # neu angelegt
    assert patch["tags"][0] == 2 and 1 in patch["tags"] and len(patch["tags"]) == 3  # Eingang bleibt und steht nicht doppelt
    posts = [(x["pfad"], json.loads(x["rumpf"])) for x in paperless.aufrufe if x["methode"] == "POST"]
    assert posts == [("/api/document_types/", {"name": "Rechnung"}), ("/api/tags/", {"name": "Neu"})]
    assert antwort["angelegt"] == ["Typ Rechnung", "Schlagwort Neu"]
    n = antwort["nachher"]
    assert (n["titel"], n["korrespondent"], n["typ"]) == ("Steuerbescheid 2025", "Finanzamt", "Rechnung")
    assert sorted(n["schlagworte"]) == ["Eingang", "Neu", "Steuer"]
    assert paperless.methoden() <= {"GET", "POST", "PATCH"}  # nie ein DELETE


def test_zuordnen_nur_titel_fasst_den_rest_nicht_an(paperless):
    _dienst(paperless).zuordnen(41, {"titel": "Neuer Titel"})
    assert json.loads(paperless.an("/api/documents/41/", "PATCH")[0]["rumpf"]) == {"title": "Neuer Titel"}
    assert [x for x in paperless.aufrufe if x["methode"] == "POST"] == []


def test_zuordnen_liest_die_namen_frisch(paperless):
    q = _dienst(paperless)
    q.namen()
    paperless.pl.listen["tags"][50] = "Frisch"  # inzwischen woanders angelegt
    q.zuordnen(40, {"schlagworte_hinzu": ["Frisch"]})
    assert [x for x in paperless.aufrufe if x["methode"] == "POST"] == []  # nicht doppelt angelegt
    assert 50 in json.loads(paperless.an("/api/documents/40/", "PATCH")[0]["rumpf"])["tags"]


def test_zuordnen_nach_dem_anlegen_stimmt_der_namensspeicher(paperless):
    q = _dienst(paperless)
    q.zuordnen(40, {"schlagworte_hinzu": ["Neu"]})
    assert "Neu" in q.namen()["schlagworte"]


@pytest.mark.parametrize("aenderung", [
    {}, None, "titel", [], {"titel": ""}, {"titel": " "}, {"titel": "x"}, {"titel": 5}, {"titel": "t" * 301},
    {"korrespondent": "k" * 101}, {"typ": ["Rechnung"]}, {"unbekannt": "x"}, {"titel": "Ok", "loeschen": True},
    {"schlagworte_hinzu": "Strom"}, {"schlagworte_hinzu": [5]}, {"schlagworte_hinzu": ["a"]},
    {"schlagworte_hinzu": ["Schlagwort %d" % i for i in range(9)]}, {"schlagworte_hinzu": []},
])
def test_zuordnen_prueft_die_eingabe_bevor_der_dienst_etwas_sieht(paperless, aenderung):
    with pytest.raises(ValueError):
        _dienst(paperless).zuordnen(40, aenderung)
    assert paperless.aufrufe == []


def test_zuordnen_bereinigt_und_ordnet_die_schlagworte():
    assert D.pruefe_aenderung({"titel": "  Ein \n Titel ", "schlagworte_hinzu": ["Strom", "strom", " Gas  "]}) == {
        "titel": "Ein Titel", "schlagworte_hinzu": ["Strom", "Gas"]}


def test_zuordnen_eines_unbekannten_dokuments_ist_404(paperless):
    with pytest.raises(QuelleFehler) as e:
        _dienst(paperless).zuordnen(999, {"titel": "Neu"})
    assert e.value.status == 404


def test_zuordnen_wenn_paperless_die_aenderung_ablehnt_ist_eingabefehler(paperless):
    paperless.routen[("PATCH", "/api/documents/40/")] = (400, {"title": ["Zu lang."]})
    with pytest.raises(ValueError, match="lehnt die Änderung ab"):
        _dienst(paperless).zuordnen(40, {"titel": "Neu"})
    paperless.routen[("PATCH", "/api/documents/40/")] = (400, {"detail": "Ungültig."})
    with pytest.raises(ValueError, match="Ungültig"):
        _dienst(paperless).zuordnen(40, {"titel": "Neu"})


def test_zuordnen_schreiben_ohne_recht_ist_ein_fehler_ohne_token(paperless):
    paperless.routen[("PATCH", "/api/documents/40/")] = (403, {"detail": "Sie haben keine Berechtigung."})
    with pytest.raises(QuelleFehler) as e:
        _dienst(paperless).zuordnen(40, {"titel": "Neu"})
    assert e.value.status == 403 and TOKEN not in str(e.value)


# ── Ablage ──────────────────────────────────────────────────────────────────────────────────────────────
def test_die_ablage_liefert_dokumente_im_dokumentformat():
    ablage = Ablage()
    D.ablage_anmelden(ablage)
    q = D.quelle()
    assert (q.art, q.eingerichtet) == ("ablage", True) and "ordner" in q.beschreibung()
    antwort = q.neueste(3)
    assert ablage.aufrufe == [("neueste", 3)]
    assert antwort["gesamt"] == 7 and [d["id"] for d in antwort["dokumente"]] == [3, 2]  # ohne brauchbare Kennung: weg
    d = antwort["dokumente"][0]
    assert d == {
        "id": 3, "titel": "Notiz vom Montag", "erstellt": "2026-10-05", "hinzugefuegt": "2026-10-06T08:00:00+00:00",
        "schlagworte": ["Notiz"], "korrespondent": None, "typ": None, "datei": "notiz.txt", "seiten": 1,
        "auszug": "ein Treffer", "link": "https://dok.example.org/3",
    }
    assert set(antwort["dokumente"][1]) == set(d)
    assert antwort["dokumente"][1]["titel"] == "Alt" and antwort["dokumente"][1]["seiten"] is None


def test_die_ablage_sucht_zaehlt_und_liest():
    ablage = Ablage()
    D.ablage_anmelden(ablage)
    q = D.quelle()
    assert q.suchen("  Montag  ", 5)["gesamt"] == 1 and ablage.aufrufe[-1] == ("suchen", "Montag", 5)
    assert q.unsortiert() == 4
    voll = q.holen(3)
    assert voll["text"] == "Hallo\nWelt" and voll["text_gekuerzt"] is False and voll["id"] == 3
    lang = q.holen(2)
    assert len(lang["text"]) == D.TEXT_MAX and lang["text_gekuerzt"] is True
    assert q.namen() == {"schlagworte": ["A", "b"], "korrespondenten": ["Z"], "typen": []}


def test_die_ablage_kann_zuordnen_mit_und_ohne_vorschau():
    ablage = Ablage()
    D.ablage_anmelden(ablage)
    q = D.quelle()
    vorschau = q.zuordnen(3, {"titel": "Neu", "typ": "  Rechnung "}, vorschau=True)
    assert ablage.aufrufe[-1] == ("zuordnen", 3, {"titel": "Neu", "typ": "Rechnung"}, True)
    assert vorschau["vorschau"] is True and vorschau["wird_angelegt"] == ["Typ X"] and vorschau["vorher"]["id"] == 3
    assert vorschau["aendert"] == {"titel": "Neu", "typ": "Rechnung"} and "nachher" not in vorschau
    echt = q.zuordnen("3", {"titel": "Neu"})
    assert ablage.aufrufe[-1] == ("zuordnen", 3, {"titel": "Neu"}, False)
    assert echt["vorschau"] is False and echt["nachher"]["titel"] == "Neu" and echt["angelegt"] == []


def test_eine_ablage_ohne_die_optionalen_methoden_sagt_das_klar():
    D.ablage_anmelden(NurLesen())
    q = D.quelle()
    assert q.neueste() == {"gesamt": 0, "dokumente": []}  # leer, aber geantwortet
    assert q.unsortiert() is None
    for aufruf in (q.namen, lambda: q.zuordnen(1, {"titel": "Neu"})):
        with pytest.raises(QuelleFehler, match="kann das nicht") as e:
            aufruf()
        assert e.value.status == 501 and not isinstance(e.value, NichtEingerichtet)


def test_fehler_der_ablage_zeigen_nie_den_text_fremder_ausnahmen(caplog):
    class Kaputt(Ablage):
        def ablage_neueste(self, anzahl):
            raise KeyError(f"geheim {TOKEN}")

        def ablage_suchen(self, abfrage, anzahl):
            raise vorgaenge.QuelleFehler("Ordner nicht lesbar", 503)

        def ablage_holen(self, id):
            raise NotImplementedError

        def ablage_zuordnen(self, id, aenderung, vorschau):
            raise ValueError("Titel schon vergeben")

        def ablage_namen(self):
            return "keine Namen"

    D.ablage_anmelden(Kaputt())
    q = D.quelle()
    with pytest.raises(QuelleFehler) as e:
        q.neueste()
    assert "KeyError" in str(e.value) and TOKEN not in str(e.value) and TOKEN not in caplog.text
    with pytest.raises(QuelleFehler, match="Ordner nicht lesbar") as e:
        q.suchen("steuer")
    assert e.value.status == 503 and isinstance(e.value, D.QuelleFehler)
    with pytest.raises(QuelleFehler, match="kann das nicht") as e:
        q.holen(1)
    assert e.value.status == 501
    with pytest.raises(ValueError, match="schon vergeben"):
        q.zuordnen(1, {"titel": "Neu"})
    with pytest.raises(QuelleFehler, match="ohne Namen"):
        q.namen()


def test_eine_ablage_mit_unbrauchbaren_antworten():
    class Schlecht(NurLesen):
        def ablage_neueste(self, anzahl):
            return {"dokumente": "keine Liste"}

        def ablage_suchen(self, abfrage, anzahl):
            return ["falsch"]

        def ablage_holen(self, id):
            return "falsch"

        def ablage_unsortiert(self):
            return "viele"

    D.ablage_anmelden(Schlecht())
    q = D.quelle()
    with pytest.raises(QuelleFehler, match="ohne Dokumentliste"):
        q.neueste()
    with pytest.raises(QuelleFehler, match="ohne Dokumentliste"):
        q.suchen("steuer")
    with pytest.raises(QuelleFehler, match="nicht geliefert"):
        q.holen(1)
    assert q.unsortiert() is None


def test_ein_unbrauchbarer_zaehler_der_ablage_ist_kein_fehler():
    class OhneZaehler(NurLesen):
        def ablage_unsortiert(self):
            raise OSError("nein")

    D.ablage_anmelden(OhneZaehler())
    assert D.quelle().unsortiert() is None


def test_gesamt_ist_nie_kleiner_als_die_gelieferten_dokumente():
    class Knapp(NurLesen):
        def ablage_neueste(self, anzahl):
            return {"gesamt": 0, "dokumente": [{"id": 1}, {"id": 2}]}

    D.ablage_anmelden(Knapp())
    assert D.quelle().neueste()["gesamt"] == 2


def test_die_ablage_meldet_sich_ab():
    ablage = Ablage()
    D.ablage_anmelden(ablage)
    assert D.angemeldete_ablage() is ablage
    D.ablage_anmelden(None)
    assert D.angemeldete_ablage() is None and D.quelle().art == "keine"


# ── Format-Hilfen ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("roh, erwartet", [
    ("das <b>BIOS</b>\n\n update", "das «BIOS» update"),
    ('<span class="match">x</span>', "«x»"),
    ('<span class="match term0">x</span> und <span class="match term1">y</span>', "«x» und «y»"),
    ("<b>a</b> <i>fett</i> <span>ohne Treffer</span>", "«a» fett ohne Treffer"),
    ("Soll &amp; Haben &lt;3", "Soll & Haben <3"),
    ("", None), (None, None), ("   ", None), (5, None),
])
def test_auszug_aus(roh, erwartet):
    assert D.auszug_aus(roh) == erwartet


def test_ein_langer_auszug_wird_gekuerzt():
    text = D.auszug_aus("wort " * 400)
    assert len(text) <= D.AUSZUG_MAX and text.endswith("…")


def test_boesartiger_auszug_braucht_keine_quadratische_zeit():
    start = time.monotonic()
    D.auszug_aus("<" * 200_000)
    D.auszug_aus("<b>" * 100_000)
    D.auszug_aus('<span class="match' + 'x' * 100_000)
    assert time.monotonic() - start < 3


def test_dokument_aus_raeumt_auf():
    d = D.dokument_aus({"id": "12", "titel": None, "erstellt": "kein Datum", "hinzugefuegt": "Mitternacht", "schlagworte": "Steuer",
                        "korrespondent": " ", "typ": 5, "seiten": -1, "auszug": "", "link": "javascript:x"})
    assert d == {"id": 12, "titel": D.OHNE_TITEL, "erstellt": None, "hinzugefuegt": None, "schlagworte": [],
                 "korrespondent": None, "typ": "5", "datei": None, "seiten": None, "auszug": None, "link": None}
    assert D.dokument_aus({"titel": "ohne Kennung"}) is None and D.dokument_aus({"id": 0}) is None
    assert D.dokument_aus({"id": 5, "titel": "a\x00b\nc" + "d" * 400})["titel"] == "ab c" + "d" * (D.TITEL_MAX - 4)


def test_die_quellen_haben_fuer_leser_keine_loeschmethoden():
    for klasse in (D.Quelle, D.AblageQuelle, D.Dienst):
        assert not [n for n in dir(klasse) if any(w in n for w in ("loeschen", "delete", "entfernen", "senden"))]
