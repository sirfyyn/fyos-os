"""Die Abnahme (abnahme.py): verbotene Anfragen müssen abgelehnt werden.

Drei Ebenen: die Urteile mit einem Sender ohne Netz, `senden` gegen einen echten lokalen Server, und die ganze Kette
gegen den echten Hub hinter einer Weiche, die aus der nginx-Vorlage der Shell gebaut ist. Zu jeder Ablehnung gehört ein
Sabotagetest: Lässt die Weiche etwas durch, muss die Abnahme es merken.
"""

import http.server
import json
import re
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from fyos_installer import abnahme as abn
from fyos_installer import erzeugen
from fyos_installer import katalog as kat

BASIS = "http://127.0.0.1:8080"
PROBE_IDS = ["aufruf_endpunkt", "fremde_herkunft", "kein_flaechenwerkzeug"]
DURCHGELASSEN = abn.Antwort(200, {"ok": True, "result": {"zahl": 1}})


# ---------------------------------------------------------------- Adresse


@pytest.mark.parametrize(
    "roh, soll",
    [
        ("http://localhost:8080", "http://localhost:8080"),
        ("https://fyos.example.com", "https://fyos.example.com"),
        ("http://127.0.0.1:8080/", "http://127.0.0.1:8080"),
        ("  http://localhost:8080//  ", "http://localhost:8080"),
        ("http://[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_basis_url(roh, soll):
    assert abn.basis_url(roh) == soll


@pytest.mark.parametrize(
    "roh",
    [
        "", None, "localhost:8080", "ftp://localhost", "file:///etc/passwd", "javascript:alert(1)",
        "http://user:pw@localhost", "http://localhost/pfad", "http://localhost?x=1", "http://local host",
        "http://localhost#x", "http://", "//localhost",
    ],
)
def test_basis_url_lehnt_ab(roh):
    with pytest.raises(ValueError, match="Adresse"):
        abn.basis_url(roh)


def test_unbrauchbare_adresse_stellt_keine_anfrage(sender_fabrik):
    sender = sender_fabrik()
    with pytest.raises(ValueError):
        abn.pruefen("kaputt", sender)
    assert sender.gesehen == []


# ---------------------------------------------------------------- Die Anfragen


def test_die_anfragen_der_abnahme(sender_fabrik):
    sender = sender_fabrik()
    abn.pruefen(BASIS + "/", sender)
    assert [(a["methode"], a["pfad"]) for a in sender.gesehen] == [
        ("POST", "/hub-api/app-call"), ("POST", "/hub-api/call"), ("POST", "/hub-api/app-call"), ("POST", "/hub-api/app-call"),
    ]
    assert all(a["url"] == BASIS + a["pfad"] for a in sender.gesehen)
    gegen, voll, fremd, ohne_ui = sender.gesehen
    # nur die Probe mit fremder Herkunft trägt die Köpfe einer fremden Webseite, und die Domain ist eine Beispieldomain
    assert gegen["kopf"] == voll["kopf"] == ohne_ui["kopf"] == {}
    assert fremd["kopf"] == {"Origin": "https://fremd.example.com", "Sec-Fetch-Site": "cross-site"}
    assert (gegen["daten"]["tool"], voll["daten"]["tool"], fremd["daten"]["tool"], ohne_ui["daten"]["tool"]) == (
        "werkstatt.suchen", "audit.stats", "werkstatt.suchen", "audit.stats",
    )


def test_die_anfragen_sind_harmlos():
    """Nichts, was eine durchgelassene Probe auslösen könnte, ändert etwas: zwei lesende Werkzeuge, nichts sonst."""
    lesend = {"audit.stats", "werkstatt.suchen"}
    for p in (abn.GEGENPROBE, *abn.PROBEN):
        assert p.methode == "POST" and p.pfad.startswith("/hub-api/")
        assert p.daten["tool"] in lesend, p.id
        assert set(p.daten["arguments"]) <= {"q"}, p.id  # kein Argument außer einem Suchwort
        assert p.wirkung.startswith("Durchgegangen wäre nur eine Lesung") or p is abn.GEGENPROBE, p.id
    assert [p.id for p in abn.PROBEN] == PROBE_IDS
    assert len({p.id for p in abn.PROBEN}) == len(abn.PROBEN)
    assert all(p.status and p.hilfe and p.titel for p in abn.PROBEN)


# ---------------------------------------------------------------- Urteile


def test_bestanden(sender_fabrik):
    a = abn.pruefen(BASIS, sender_fabrik())
    assert a.bestanden and a.abgelehnt == 3
    assert [b.id for b in [a.gegenprobe, *a.proben]] == ["gegenprobe", *PROBE_IDS]
    assert [b.urteil for b in [a.gegenprobe, *a.proben]] == ["beantwortet", "abgelehnt", "abgelehnt", "abgelehnt"]
    assert a.zusammenfassung() == "Abnahme bestanden: alle 3 verbotenen Anfragen wurden abgelehnt."
    zeilen = a.zeilen()
    assert zeilen[0].startswith("== Abnahme") and BASIS in zeilen[0]
    assert "Probe 1: Voller Aufruf-Endpunkt über den Browser-Weg: abgelehnt (404)" in zeilen
    assert "Probe 2: Schreibender Aufruf von einer fremden Webseite: abgelehnt (403, fremde_herkunft)" in zeilen
    assert "Probe 3: Werkzeug ohne Oberfläche über den Browser-Weg: abgelehnt (403, not_an_app)" in zeilen
    assert zeilen[-1] == a.zusammenfassung()  # nichts zu beanstanden: keine Detailzeilen
    d = a.als_dict()
    assert json.loads(json.dumps(d)) == d and d["bestanden"] is True and d["basis"] == BASIS
    assert [b["id"] for b in d["befunde"]] == ["gegenprobe", *PROBE_IDS]


def test_aufruf_endpunkt_darf_auch_403_sein(sender_fabrik):
    assert abn.pruefen(BASIS, sender_fabrik(aufruf_endpunkt=abn.Antwort(403, {"ok": False, "kind": "forbidden"}))).bestanden
    assert abn.pruefen(BASIS, sender_fabrik(aufruf_endpunkt=abn.Antwort(403, None))).bestanden


@pytest.mark.parametrize("probe", PROBE_IDS)
def test_erfolg_auf_verbotene_anfrage_besteht_nicht(sender_fabrik, probe):
    a = abn.pruefen(BASIS, sender_fabrik(**{probe: DURCHGELASSEN}))
    befund = next(b for b in a.proben if b.id == probe)
    assert not a.bestanden and a.abgelehnt == 2
    assert (befund.urteil, befund.ok) == ("durchgelassen", False)
    assert "NICHT abgelehnt (Antwort 200)" in befund.text
    assert befund.wirkung.startswith("Durchgegangen wäre nur eine Lesung") and befund.hilfe
    assert a.zusammenfassung() == "Abnahme NICHT bestanden: 2 von 3 verbotenen Anfragen wurden abgelehnt."
    zeilen = a.zeilen()
    assert f"  - {befund.titel}: {befund.text}" in zeilen and "    " + befund.wirkung in zeilen and "    Prüfen: " + befund.hilfe in zeilen
    assert sum(1 for z in zeilen if z.startswith("  - ")) == 1  # nur der durchgefallene Befund steht in den Details


@pytest.mark.parametrize("status", [201, 204, 299])
def test_jeder_erfolgsstatus_ist_durchgelassen(sender_fabrik, status):
    a = abn.pruefen(BASIS, sender_fabrik(aufruf_endpunkt=abn.Antwort(status, None)))
    assert a.proben[0].urteil == "durchgelassen" and not a.bestanden


@pytest.mark.parametrize(
    "probe, antwort",
    [
        ("fremde_herkunft", abn.Antwort(403, {"ok": False, "kind": "not_an_app"})),  # abgelehnt, aber aus dem falschen Grund
        ("fremde_herkunft", abn.Antwort(403, None)),  # irgendeine 403 ohne Begründung (Proxy, WAF)
        ("fremde_herkunft", abn.Antwort(403, "fremde_herkunft")),  # JSON, aber kein Objekt
        ("fremde_herkunft", abn.Antwort(403, {"kind": 5})),
        ("fremde_herkunft", abn.Antwort(404, {"ok": False, "kind": "fremde_herkunft"})),  # falscher Status
        ("fremde_herkunft", abn.Antwort(500, None)),
        ("fremde_herkunft", abn.Antwort(415, {"ok": False, "kind": "bad_content_type"})),
        ("kein_flaechenwerkzeug", abn.Antwort(403, {"ok": False, "kind": "fremde_herkunft"})),
        ("kein_flaechenwerkzeug", abn.Antwort(404, {"ok": False, "kind": "not_found"})),
        ("kein_flaechenwerkzeug", abn.Antwort(502, None)),
        ("aufruf_endpunkt", abn.Antwort(500, None)),
        ("aufruf_endpunkt", abn.Antwort(502, None)),  # die Shell hat keinen Hub erreicht: nicht abgelehnt, sondern defekt
        ("aufruf_endpunkt", abn.Antwort(302, None)),  # eine Weiterleitung ist keine Ablehnung
        ("aufruf_endpunkt", abn.Antwort(401, None)),
    ],
)
def test_andere_antworten_sind_nicht_nachgewiesen(sender_fabrik, probe, antwort):
    a = abn.pruefen(BASIS, sender_fabrik(**{probe: antwort}))
    befund = next(b for b in a.proben if b.id == probe)
    assert (befund.urteil, befund.ok) == ("unklar", False)
    assert "anders als erwartet" in befund.text and befund.hilfe and not befund.wirkung
    assert not a.bestanden


def test_keine_antwort_ist_nicht_nachgewiesen(sender_fabrik):
    stumm = abn.Antwort(None, None, "ConnectionRefusedError: [Errno 61] Connection refused")
    for probe in PROBE_IDS:
        a = abn.pruefen(BASIS, sender_fabrik(**{probe: stumm}))
        befund = next(b for b in a.proben if b.id == probe)
        assert befund.urteil == "unklar" and "keine Antwort" in befund.text and "ConnectionRefusedError" in befund.text
        assert not a.bestanden


@pytest.mark.parametrize(
    "antwort",
    [
        abn.Antwort(404, None),  # falsche Adresse: ein Server, aber nicht die Shell
        abn.Antwort(200, None),  # irgendeine Seite statt JSON
        abn.Antwort(200, {"ok": False, "error": "x"}),
        abn.Antwort(200, {"result": {}}),
        abn.Antwort(200, ["ok"]),
        abn.Antwort(502, {"ok": False, "kind": "hub_weg"}),
        abn.Antwort(None, None, "TimeoutError: timed out"),
    ],
)
def test_ohne_gegenprobe_zaehlen_ablehnungen_nichts(sender_fabrik, antwort):
    a = abn.pruefen(BASIS, sender_fabrik(gegenprobe=antwort))
    assert [b.urteil for b in a.proben] == ["abgelehnt"] * 3  # die Ablehnungen allein sähen gut aus
    assert a.gegenprobe.urteil == "unklar" and not a.gegenprobe.ok
    assert not a.bestanden
    assert a.zusammenfassung().startswith("Abnahme NICHT bestanden: Die erlaubte Gegenprobe scheiterte (")
    assert "nicht aussagekräftig" in a.zusammenfassung()
    assert any(z.startswith("    Prüfen: Die Adresse zeigt nicht auf die Shell") for z in a.zeilen())


def test_alles_schief(sender_fabrik):
    a = abn.pruefen(BASIS, sender_fabrik(
        gegenprobe=abn.Antwort(404, None), aufruf_endpunkt=DURCHGELASSEN, fremde_herkunft=DURCHGELASSEN,
        kein_flaechenwerkzeug=abn.Antwort(None, None, "OSError: weg"),
    ))
    assert not a.bestanden and a.abgelehnt == 0
    assert sum(1 for z in a.zeilen() if z.startswith("  - ")) == 4
    json.dumps(a.als_dict())


# ---------------------------------------------------------------- Hinweis für Plan und Anleitung


def test_hinweis_je_ziel():
    compose = abn.hinweis(8080, "compose")
    assert "Nach dem Start stellt der Installer 3 verbotene Anfragen" in compose and "`fyos-install --abnahme http://localhost:8080`" in compose
    k8s = abn.hinweis(9000, "k8s")
    assert "Mit laufendem Port-Forward" in k8s and "http://localhost:9000" in k8s
    dateien = abn.hinweis(8081, "dateien")
    assert "Ist FYOS gestartet" in dateien and "http://localhost:8081" in dateien
    assert all("ändern nichts" in h for h in (compose, k8s, dateien))


def test_der_hinweis_steht_im_plan_und_in_der_anleitung(katalog, tmp_path):
    for ziel in ("compose", "k8s", "dateien"):
        plan = erzeugen.erstelle_plan(katalog, [], ziel, {}, tmp_path / ziel)
        assert plan.ok, plan.fehler
        hinweis = abn.hinweis(plan.port, ziel)
        assert hinweis in plan.hinweise, ziel
        anleitung = next(d for d in plan.dateien if d.pfad == "ANLEITUNG.md")
        assert hinweis in anleitung.inhalt, ziel
    plan = erzeugen.erstelle_plan(katalog, [], "compose", {"felder": {"kern": {"port": 9123}}}, tmp_path / "p")
    assert "http://localhost:9123" in " ".join(plan.hinweise)


# ---------------------------------------------------------------- senden: gegen einen echten lokalen Server


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_a):
        pass

    def _antwort(self, status, koerper=b"", typ="application/json", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(koerper)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(koerper)

    def do_POST(self):  # noqa: N802
        roh = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/echo":
            kopf = {k.lower(): v for k, v in self.headers.items()}
            self._antwort(200, json.dumps({"ok": True, "kopf": kopf, "daten": json.loads(roh)}).encode())
        elif self.path == "/weiter":
            self._antwort(302, b"", extra={"Location": "/echo"})
        elif self.path == "/verboten":
            self._antwort(403, json.dumps({"ok": False, "kind": "not_an_app"}).encode())
        elif self.path == "/text":
            self._antwort(200, b"<html>kein JSON</html>", "text/html")
        elif self.path == "/gross":
            self._antwort(200, b'{"ok": true, "x": "' + b"a" * (abn.MAX_ANTWORT * 2) + b'"}')
        else:
            self._antwort(404, b"nichts")


@pytest.fixture(scope="module")
def lokal():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_senden_schickt_json_und_koepfe(lokal):
    a = abn.senden("POST", lokal + "/echo", {"Origin": "https://fremd.example.com", "Sec-Fetch-Site": "cross-site"}, {"tool": "x.y"})
    assert a.status == 200 and a.fehler == ""
    assert a.inhalt["daten"] == {"tool": "x.y"}
    assert a.inhalt["kopf"]["content-type"] == "application/json"
    assert a.inhalt["kopf"]["origin"] == "https://fremd.example.com" and a.inhalt["kopf"]["sec-fetch-site"] == "cross-site"


def test_senden_folgt_keiner_weiterleitung(lokal):
    a = abn.senden("POST", lokal + "/weiter", {}, {"tool": "x.y"})
    assert (a.status, a.inhalt) == (302, None)


def test_senden_liefert_auch_fehlerantworten(lokal):
    assert abn.senden("POST", lokal + "/verboten", {}, {}) == abn.Antwort(403, {"ok": False, "kind": "not_an_app"})
    assert abn.senden("POST", lokal + "/gibtsnicht", {}, {}) == abn.Antwort(404, None)
    assert abn.senden("POST", lokal + "/text", {}, {}) == abn.Antwort(200, None)


def test_senden_liest_nur_begrenzt(lokal):
    a = abn.senden("POST", lokal + "/gross", {}, {})
    assert a.status == 200 and a.inhalt is None  # abgeschnitten, also kein gültiges JSON mehr


def test_senden_ignoriert_proxy_einstellungen(lokal, monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    assert abn.senden("POST", lokal + "/echo", {}, {}).status == 200


def test_senden_ohne_server_ist_eine_antwort_ohne_status():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nichts lauscht mehr
    a = abn.senden("POST", f"http://127.0.0.1:{port}/echo", {}, {})
    assert a.status is None and a.inhalt is None and a.fehler
    assert len(a.fehler) <= 200


def test_senden_wirft_nie_und_spricht_nur_http(tmp_path):
    datei = tmp_path / "geheim.txt"
    datei.write_text("nicht lesen")
    for url in ("http://127.0.0.1:1/x", "kaputt", "ftp://127.0.0.1/x", datei.as_uri(), "data:text/plain,hallo"):
        a = abn.senden("POST", url, {}, {})
        assert a.status is None and a.inhalt is None and a.fehler, url


def test_pruefen_mit_dem_echten_sender_ohne_server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    a = abn.pruefen(f"http://127.0.0.1:{port}")
    assert not a.bestanden and a.abgelehnt == 0
    assert all("keine Antwort" in b.text for b in [a.gegenprobe, *a.proben])


# ---------------------------------------------------------------- Die nginx-Vorlage der Shell

NGINX = Path(__file__).resolve().parents[2] / "web" / "nginx" / "default.conf.template"
ROUTEN = {
    "/hub-api/apps": "/hub/apps",
    "/hub-api/resource": "/hub/resource",
    "/hub-api/app-call": "/hub/app-call",
    "/hub-api/os/strom": "/hub/os/strom",
    "/hub-api/os/melden": "/hub/os/melden",
    "/hub-api/os/antwort": "/hub/os/antwort",
}

nginx_noetig = pytest.mark.skipif(not NGINX.is_file(), reason="web/nginx/default.conf.template liegt nicht neben dem Installer")


def routen_aus_vorlage() -> dict[str, str]:
    """Aus der Vorlage gelesen: welche Pfade unter /hub-api/ die Shell an welchen Hub-Pfad weiterreicht."""
    text = NGINX.read_text(encoding="utf-8")
    routen = {}
    for m in re.finditer(r"^    location = (/hub-api/\S+) \{\n(.*?)^    \}", text, re.S | re.M):
        ziel = re.search(r"proxy_pass \$\{FYOS_HUB_UPSTREAM\}(/hub/[^\s;$]+)", m.group(2))
        assert ziel, m.group(1)
        routen[m.group(1)] = ziel.group(1)
    return routen


@nginx_noetig
def test_vorlage_reicht_nur_den_browser_weg_durch():
    assert routen_aus_vorlage() == ROUTEN
    text = NGINX.read_text(encoding="utf-8")
    assert re.search(r"^    location \^~ /hub-api/ \{ return 404; \}$", text, re.M)  # alles andere unter /hub-api/ gibt es nicht
    assert "/hub-api/call" not in routen_aus_vorlage()
    # die Köpfe, auf die die Abnahme setzt, werden nicht umgeschrieben oder entfernt
    for name in ("origin", "sec-fetch-site", "content-type"):
        assert not re.search(rf'proxy_set_header\s+{name}\b', text, re.I), name
        assert not re.search(rf'proxy_hide_header\s+{name}\b', text, re.I), name


# ---------------------------------------------------------------- Der echte Hub hinter einer Weiche aus der Vorlage


@pytest.fixture(scope="module")
def hub(tmp_path_factory):
    """Der echte Hub mit der Konfiguration, die der Installer für den Kern erzeugt (Starlette-Testclient, ohne Netz)."""
    pytest.importorskip("mcp_hub")
    pytest.importorskip("httpx")
    from mcp_hub import server as hub_server
    from starlette.testclient import TestClient

    ordner = tmp_path_factory.mktemp("hub")
    plan = erzeugen.erstelle_plan(kat.lade_standard(plugins=False), [], "dateien", {}, ordner / "out")
    assert plan.ok, plan.fehler
    (ordner / "hub-config.yaml").write_text(next(d.inhalt for d in plan.dateien if d.pfad == "hub-config.yaml"))
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("MCP_HUB_AUDIT_SKIP_QDRANT", "1")
        for name in ("REDIS_URL", "QDRANT_URL", "FYOS_EMBED_URL", "HUB_SUCHE_EMBED_URL", "FYOS_OIDC_ISSUER",
                     "FYOS_ERLAUBTE_HOSTS", "FYOS_OEFFENTLICH_URL"):
            mp.delenv(name, raising=False)
        app = hub_server.build_app(str(ordner / "hub-config.yaml"))
        with TestClient(app) as client:
            yield client, hub_server


def weiche(client, routen, *, ohne_koepfe=(), umleiten=None):
    """Ein Sender, der den Hub so erreicht wie die Shell: nur die Pfade in `routen`, sonst 404. Wie nginx gibt er die
    Köpfe weiter (außer denen in `ohne_koepfe`) und lässt Statuscode und Körper des Hubs unverändert."""
    gesperrt = {k.lower() for k in ohne_koepfe}

    def sender(methode, url, kopf, daten):
        pfad = urlsplit(url).path
        ziel = (umleiten or {}).get(pfad) or routen.get(pfad)
        if ziel is None:
            return abn.Antwort(404, None)
        kopf = {k: v for k, v in kopf.items() if k.lower() not in gesperrt}
        r = client.request(methode, ziel, json=daten, headers=kopf)
        try:
            inhalt = r.json()
        except ValueError:
            inhalt = None
        return abn.Antwort(r.status_code, inhalt)

    return sender


@nginx_noetig
def test_echter_hub_besteht_die_abnahme(hub):
    client, _ = hub
    a = abn.pruefen(BASIS, weiche(client, routen_aus_vorlage()))
    assert a.bestanden, "\n".join(a.zeilen())
    assert [b.urteil for b in [a.gegenprobe, *a.proben]] == ["beantwortet", "abgelehnt", "abgelehnt", "abgelehnt"]
    assert [b.text for b in a.proben] == ["abgelehnt (404)", "abgelehnt (403, fremde_herkunft)", "abgelehnt (403, not_an_app)"]


def test_die_probewerkzeuge_sind_im_hub_lesend(hub):
    _, hub_server = hub
    from mcp_hub.registry import ist_flaechen_werkzeug

    for p in (abn.GEGENPROBE, *abn.PROBEN):
        rt = hub_server._REGISTRY.tools[p.daten["tool"]]
        assert "read" in rt.descriptor.tags, p.id
        assert not set(rt.descriptor.tags) & {"write", "schreibend", "destructive", "admin"}, p.id
    # die Gegenprobe trifft ein Flächenwerkzeug, die Proben 1 und 3 ein Werkzeug ohne Oberfläche
    assert ist_flaechen_werkzeug(hub_server._REGISTRY.tools[abn.GEGENPROBE.daten["tool"]].descriptor)
    assert not ist_flaechen_werkzeug(hub_server._REGISTRY.tools["audit.stats"].descriptor)


@nginx_noetig
def test_sabotage_weiche_laesst_den_vollen_endpunkt_durch(hub):
    client, _ = hub
    a = abn.pruefen(BASIS, weiche(client, {**routen_aus_vorlage(), "/hub-api/call": "/hub/call"}))
    assert not a.bestanden
    assert [b.urteil for b in a.proben] == ["durchgelassen", "abgelehnt", "abgelehnt"]
    assert "NICHT abgelehnt (Antwort 200)" in a.proben[0].text  # und die Anfrage war nur eine Lesung (audit.stats)


@nginx_noetig
def test_sabotage_weiche_entfernt_die_herkunftskoepfe(hub):
    client, _ = hub
    a = abn.pruefen(BASIS, weiche(client, routen_aus_vorlage(), ohne_koepfe=("Origin", "Sec-Fetch-Site")))
    assert not a.bestanden
    assert [b.urteil for b in a.proben] == ["abgelehnt", "durchgelassen", "abgelehnt"]


@nginx_noetig
def test_sabotage_browser_weg_ruft_jedes_werkzeug(hub):
    client, _ = hub
    a = abn.pruefen(BASIS, weiche(client, routen_aus_vorlage(), umleiten={"/hub-api/app-call": "/hub/call"}))
    assert not a.bestanden
    assert a.proben[2].urteil == "durchgelassen"  # audit.stats lief, obwohl es keine Oberfläche hat


@nginx_noetig
def test_falsche_adresse_besteht_nicht(hub):
    client, _ = hub
    a = abn.pruefen(BASIS, weiche(client, {}))  # ein Server, der überall 404 sagt
    assert [b.urteil for b in a.proben] == ["abgelehnt", "unklar", "unklar"]
    assert a.gegenprobe.urteil == "unklar" and not a.bestanden
