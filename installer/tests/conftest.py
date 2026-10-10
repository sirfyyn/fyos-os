import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fyos_installer import abnahme as abn  # noqa: E402
from fyos_installer import katalog as kat  # noqa: E402


@pytest.fixture
def katalog():
    return kat.lade_standard(plugins=False)


@pytest.fixture(autouse=True)
def _ohne_plugin_quelle(monkeypatch):
    monkeypatch.delenv("FYOS_PLUGIN_QUELLE", raising=False)


# Antworten einer richtig eingerichteten Installation auf die Anfragen der Abnahme (abnahme.py), je Probe.
GUTE_ANTWORTEN = {
    "gegenprobe": abn.Antwort(200, {"ok": True, "result": {"treffer": []}}),
    "aufruf_endpunkt": abn.Antwort(404, None),
    "fremde_herkunft": abn.Antwort(403, {"ok": False, "error": "fremd", "kind": "fremde_herkunft"}),
    "kein_flaechenwerkzeug": abn.Antwort(403, {"ok": False, "error": "kein Flaechen-Werkzeug", "kind": "not_an_app"}),
}


def probe_von(pfad, kopf, daten):
    """Zu welcher Probe gehört eine Anfrage? (die Proben unterscheiden sich in Pfad, Origin und Werkzeug)"""
    if pfad == "/hub-api/call":
        return "aufruf_endpunkt"
    if "Origin" in kopf:
        return "fremde_herkunft"
    return "kein_flaechenwerkzeug" if daten["tool"] == "audit.stats" else "gegenprobe"


@pytest.fixture
def sender_fabrik():
    """Fabrik für einen Sender ohne Netz: antwortet wie eine gute Installation, einzelne Proben lassen sich ersetzen
    (`sender_fabrik(fremde_herkunft=Antwort(200, ...))`). `sender.gesehen` hält jede Anfrage fest."""

    def fabrik(**abweichung):
        antworten = {**GUTE_ANTWORTEN, **abweichung}
        gesehen = []

        def sender(methode, url, kopf, daten):
            pfad = "/" + url.split("://", 1)[1].split("/", 1)[1]
            gesehen.append({"methode": methode, "url": url, "pfad": pfad, "kopf": dict(kopf), "daten": daten})
            return antworten[probe_von(pfad, kopf, daten)]

        sender.gesehen = gesehen
        return sender

    return fabrik


_PRUEFEN = abn.pruefen  # die echte Abnahme, auch wenn ein Test `abn.pruefen` ersetzt


@pytest.fixture
def abnahme_von(sender_fabrik):
    """Fabrik für eine fertige Abnahme ohne Netz: bestanden, oder durchgefallen (eine Probe wird durchgelassen)."""

    def fabrik(bestanden=True):
        sender = sender_fabrik() if bestanden else sender_fabrik(aufruf_endpunkt=abn.Antwort(200, {"ok": True, "result": {}}))
        return _PRUEFEN("http://127.0.0.1:8080", sender)

    return fabrik
