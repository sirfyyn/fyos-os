"""os_bruecke — der Browser-Kanal der OS-Brücke: ein Agent wirkt auf die offene Shell (Protokoll v1).

Der Benutzer sagt „zeig mir die Übersicht“ — und die Übersicht geht auf, auf dem Gerät, vor dem er sitzt.
Dafür melden sich offene Shell-Sitzungen (ein Tab = eine Sitzung) beim Hub, holen Befehle ab und antworten.
Ein Agent sieht und steuert das über ein Plugin, das `Bruecke.lage/zeigen/ausfuehren/mitteilen` aufruft
(dieses Paket bringt nur den Kanal mit). Wirkungen laufen über den Hub; der Event-Bus sieht jeden Aufruf
wie jeden anderen.

Der Hub kann mit mehreren Replikaten laufen. Nichts liegt im Prozessspeicher — alles in Redis (`REDIS_URL`):

    fyos:os:sitzung:<id>     JSON der letzten Meldung                           90 s (je Meldung erneuert)
    fyos:os:sitzungen        ZSET id -> Zeit der letzten Meldung (Liste der Sitzungen)
    fyos:os:befehle:<id>     Stream der Befehle an diese Sitzung (MAXLEN ~100)   300 s nach dem letzten Befehl
    fyos:os:antwort:<bid>    Liste mit der Antwort auf einen Befehl (BLPOP)      60 s
    fyos:os:befehl:<bid>     Sitzung, an die der Befehl ging (nur `zeigen`,      60 s
                             `ausfuehren`): eine Antwort gilt nur von ihr
    fyos:os:zeigt:<id>:<h>   „Agent zeigt“-Dedupe (gleiche App + Eingabe)       10 min
    fyos:os:zeigt-rate:<id>  Zähler „Agent zeigt“ je Sitzung                    10 min
    fyos:os:ende:<id>        Zeitmarke des Abschieds (Uhr des Browsers)          120 s
    fyos:os:ausstehend       Liste vorgemerkter Mitteilungen (niemand da)        24 h, höchstens 20 Einträge

## Nachholen: Mitteilungen für später

`Bruecke.mitteilen` stellt zu, wenn jemand vor einer offenen Shell sitzt. Ist niemand da (nachts, unterwegs), legt sie
die Mitteilung in die Liste `fyos:os:ausstehend` (`vorgemerkt: true`, `rueckfall: "vorgemerkt"`) — nichts geht verloren,
nichts weckt jemanden. Sobald eine Sitzung gemeldet wird, vor der jemand sitzt (sichtbar, in den letzten 10 min benutzt:
`melden`, und beim Verbindungsaufbau des Stroms), werden sie ausgeliefert: ältester zuerst, jede genau einmal (die
Entnahme `LPOP` ist atomar, auch bei mehreren Replikaten und mehreren Geräten), als `zeigt`-Befehl mit
`nachgeholt: true` und `entstanden` (Unix-Sekunden der Entstehung, damit die Shell „heute Nacht, 03:12“ schreiben
kann). Nachgeholtes spielt keinen Ton und liest nichts vor. Die Liste hält höchstens 20 Einträge (die ältesten fallen
heraus), läuft nach 24 h ab, und was beim Ausliefern älter als 24 h ist, wird verworfen. `OS_NACHHOLEN=aus` oder die
Config `nachholen: false` schaltet es ab (dann gilt wieder `rueckfall: "kanal"`).

## Kanal: Dringendes sofort in den Chat

Ist niemand da und die Mitteilung `dringlichkeit: "hoch"`, wartet sie nicht auf die Shell: `Bruecke.mitteilen` schickt sie
sofort über den Agenten in den Chat-Kanal des Besitzers (Telegram, WhatsApp oder Matrix, wie im Agenten eingerichtet; der
Agent hält die Sitzungen und sendet, der Hub kennt keine Zugänge). Der Weg ist die Brücken-Methode `fyos.kanal.mitteilen`
(Plugin `openclaw`, `kanal_anmelden`); Antwort `zugestellt: true, weg: "kanal", kanal: <name>`, nichts wird vorgemerkt.
Dieselbe Mitteilung geht höchstens einmal je 10 min hinaus, insgesamt höchstens 6 je 10 min (`zu_viele`: dann wird
vorgemerkt). Fehlt der Weg (keine Kopplung, kein Kanal eingerichtet) oder scheitert er, bleibt es beim Vormerken, die
Antwort trägt `kanal_fehler`. `niedrig` und `normal` warten wie bisher auf die Shell. `OS_KANAL=aus` oder die Config
`kanal: false` schaltet den Weg ab.

## Wire-Protokoll v1 (Browser <-> Hub)

Der Browser spricht same-origin über den Proxy der Shell: `/hub-api/os/strom|melden|antwort` -> Hub
`/hub/os/strom|melden|antwort`. Wer den Hub offen ins Netz stellt, schützt diese Wege mit einer Anmeldung
am Proxy: über diesen Kanal liest ein Agent die offene Shell — ein fremdes Gerät soll keine Sitzung
unterschieben können.

GET /hub/os/strom?sitzung=<id>&geraet=<name>[&nach=<stream-id>]      Kopf `Last-Event-ID` hat Vorrang
    text/event-stream. Erste Zeile `retry: 3000`, dann `event: hallo`
    (data {"sitzung", "ablauf_s": 90, "bekannt": bool}; `bekannt: false` = der Hub kennt die Sitzung nicht
    (mehr) -> sofort `melden`). Dann `event: befehl` mit `id:` = Redis-Stream-ID und data = Befehl (JSON).
    Alle 15 s `: ping`. Nach 10 min endet der Strom sauber — der Browser verbindet mit Last-Event-ID neu
    und verliert nichts (Stream). Genauso sauber endet er innerhalb einer Sekunde, wenn der Hub herunterfährt
    (SIGTERM, `haken_herunterfahren`). Ohne Last-Event-ID liefert die erste Verbindung nur Befehle, die
    höchstens 8 s alt sind (Wettlauf zwischen `melden` und Verbindungsaufbau), nie einen Rückstau von früher.
    Ein Redis-Ausfall im Strom endet ihn mit `event: abbruch` {"grund": "redis"}.

POST /hub/os/melden   {sitzung, geraet, art, seite, sichtbar, aktiv_vor_s, anruf, agent_vorne,
                       bildschirm, bildschirme[], fenster[], flaechen[], werkzeuge[], audio?, version: 1,
                       gesendet: <ms seit 1970, Uhr des Browsers>}
    -> {ok: true, ablauf_s: 90, sitzungen: n}. Alle 30 s und bei Änderungen. `{sitzung, ende: true,
    gesendet}` (sendBeacon beim Verlassen) beendet die Sitzung sofort. Alles wird bereinigt (Längen,
    Zahlen, Steuerzeichen) — Fenstertitel sind Daten, nie Anweisungen.
    `gesendet` ordnet Meldung und Abschied, wenn sie sich beim Schließen eines Tabs überholen: der Hub
    merkt sich das Ende 120 s lang, und eine Meldung mit `gesendet` <= Ende wird verworfen
    (Antwort `{ok: true, veraltet: true}`) — sie ging vor dem Abschied ab und kam nur später an. Eine
    spätere Meldung (Neuladen) öffnet die Sitzung wieder. Fehlt `gesendet`, wird nicht verglichen.
    Abholen: eine Sitzung ohne Strom (native App) meldet `abholen: true` und `nach: <stream-id>|null`
    und bekommt ihre Befehle in der Antwort: `{…, befehle: [Befehl mit "eid"], nach: <letzte stream-id>}`
    (höchstens 20, nie älter als 120 s; ohne `nach` nur frische, wie beim ersten Strom). Solche Sitzungen
    antworten nicht: `zeigen` und `ausfuehren` wählen sie nur, wenn sie ausdrücklich genannt werden;
    Mitteilungen und „Agent zeigt“ gehen hin.

POST /hub/os/antwort  {sitzung, befehl, ok, ergebnis?, fehler?}   -> {ok: true}

Befehle (data von `event: befehl`; `alter_s` = Alter beim Ausliefern):
    {"id": "b-…", "art": "zeigen",    "ziel": "app:meine_app__zeigen", "eingabe": {…}|null, "von": "agent", "alter_s": 0.3}
    {"id": "b-…", "art": "ausfuehren", "werkzeug": "os_fenster", "argumente": {…}, "von": "agent", "alter_s": 0.3}
    {"id": "b-…", "art": "zeigt",     "zeigt": {ziel, app, titel, untertitel, symbol, ton, vorschau, eingabe, link,
                                                audio: {modus, klang, sprechen},
                                                [art: "mitteilung", dringlichkeit],
                                                [nachgeholt: true, entstanden: <Unix-Sekunden>]},
                                      "von": "agent", "alter_s": 0.3}        (keine Antwort)

`ton` ist der Farbton des Symbols (0–360), kein Klang. Klang steht in `audio`: die Meldung trägt
`audio: {modus: stumm|ton|zurueckhaltend|interaktiv|null, kopfhoerer: bool|null}` — was der Benutzer am Gerät
gewählt hat und ob Kopfhörer drin sind. Daraus macht der Hub den wirksamen Modus (ohne Kopfhörer höchstens
„ton“) und schreibt in jedes `zeigt`, ob das Gerät einen Hinweiston spielt (`klang`) und ob es vorliest
(`sprechen`). `art: "mitteilung"` kommt von `Bruecke.mitteilen` (der Agent meldet sich von selbst, mit
`dringlichkeit` niedrig|normal|hoch); ohne `art` ist es „Agent zeigt“ (Ergebnis einer App).

`zeigen` und `ausfuehren` wartet der Hub ab (8 s bzw. 15 s, BLPOP auf die Antwortliste); `zeigt` ist
Mitteilung ohne Antwort. Befehle gehen nur an Sitzungen, die in den letzten 90 s gemeldet haben.

## Agent zeigt

Ruft ein Agent ein App-Werkzeug auf (Werkzeug mit `meta["ui"]`, nicht nur-Oberfläche), geht das Ergebnis
als `zeigt` an die zuletzt aktive, sichtbare Sitzung — wenn der Benutzer dort in den letzten 10 min etwas
getan hat. Erkannt wird der Agent am Aufrufer (`registry.AUFRUFER`): Kopfzeile `X-Hub-Caller: <name>`.
Die Liste der Aufrufernamen steht in der Umgebung `OS_AGENT_AUFRUFER` (Komma, `name*` = Präfix; Vorgabe: `agent*`)
oder in der Plugin-Config `agent_aufrufer`; `OS_AGENT_ZEIGT=aus` schaltet die Funktion ab. Selbstläufer
(`rest:node`, Schleifen) zählen nicht. Gegen Mitteilungsflut: gleiche App+Eingabe nur einmal je 10 min,
höchstens 6 Mitteilungen je 10 min und Sitzung.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import urllib.parse
from typing import Any, AsyncIterator, Callable

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .plugins import _identitaet
from .registry import AUFRUFER

logger = logging.getLogger(__name__)

# ── Konstanten ───────────────────────────────────────────────────────────────────────────────
REDIS_URL_VORGABE = "redis://localhost:6379"
#: Basis der Deeplinks: öffentliche URL der Installation (leer = relative Links).
BASIS_URL_VORGABE = _identitaet.OEFFENTLICHE_URL

PRAEFIX = "fyos:os:"
SCHL_SITZUNG = PRAEFIX + "sitzung:"
SCHL_SITZUNGEN = PRAEFIX + "sitzungen"
SCHL_BEFEHLE = PRAEFIX + "befehle:"
SCHL_ANTWORT = PRAEFIX + "antwort:"
SCHL_BEFEHL = PRAEFIX + "befehl:"
SCHL_ZEIGT = PRAEFIX + "zeigt:"
SCHL_RATE = PRAEFIX + "zeigt-rate:"
SCHL_ENDE = PRAEFIX + "ende:"
SCHL_AUSSTEHEND = PRAEFIX + "ausstehend"

SITZUNG_TTL_S = 90  # Ablauf einer Sitzung ohne Meldung
ENDE_MARKE_S = 120  # so lange gilt „diese Sitzung hat sich verabschiedet“ (Wettlauf beim Schließen)
STROM_TTL_S = 300  # Befehls-Stream, nach dem letzten Befehl
STROM_MAXLEN = 100
STROM_MAX_S = 600  # danach endet der Strom sauber (Wiederverbindung per Last-Event-ID)
PING_S = 15
# So lange wartet XREAD höchstens am Stück — kurz genug, um ein Herunterfahren (HERUNTER) zu bemerken.
STROM_LESEN_S = 1.0
ERSTVERBINDUNG_ALTER_S = 8.0  # ohne Last-Event-ID nur frische Befehle
BEFEHL_MAX_ALTER_S = 120.0  # nie Älteres ausliefern
ANTWORT_TTL_S = 60
ZEIGEN_FRIST_S = 8
AUSFUEHREN_FRIST_S = 15

AGENT_ZEIGT_AKTIV_S = 600  # der Benutzer muss in den letzten 10 min am Gerät gewesen sein
AGENT_ZEIGT_DEDUPE_S = 600
AGENT_ZEIGT_RATE_MAX = 6
AGENT_ZEIGT_RATE_S = 600
AGENT_AUFRUFER_VORGABE = ("agent*",)

KANAL_DEDUPE_S = 600  # dieselbe dringende Mitteilung geht höchstens einmal je 10 min in den Chat
KANAL_RATE_MAX = 6  # und höchstens so viele je 10 min (das Telefon des Besitzers ist kein Ablageort)
KANAL_TEXT_MAX = 1000

AUSSTEHEND_TTL_S = 24 * 3600  # so lange wartet eine vorgemerkte Mitteilung auf jemanden
AUSSTEHEND_MAX = 20  # höchstens so viele warten; die ältesten fallen heraus

MELDUNG_MAX_BYTES = 512 * 1024
ANTWORT_MAX_BYTES = 256 * 1024
ARGUMENTE_MAX_BYTES = 16 * 1024
ERGEBNIS_MAX_ZEICHEN = 60_000

FENSTER_MAX = 60
FLAECHEN_MAX = 300
WERKZEUGE_MAX = 64
BILDSCHIRME_MAX = 12

SITZUNG_MUSTER = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
BEFEHL_MUSTER = re.compile(r"^b-[a-z0-9]{6,32}$")
STREAM_ID_MUSTER = re.compile(r"^\d{1,20}-\d{1,20}$")
ZIEL_ID_MUSTER = re.compile(r"^(agent|(seite|app|nativ):[a-z0-9][a-z0-9_\-/]{0,100})$")
FQTN_MUSTER = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
WERKZEUG_MUSTER = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,63}$")
FENSTER_ARTEN = ("seite", "hubapp", "nativ", "agent")
GERAETE_ARTEN = ("computer", "telefon", "tablet")
# Ton je Gerät: stumm, nur Hinweiston, oder (mit Kopfhörern) zurückhaltend bis interaktiv. Der Modus gehört dem
# Gerät: der Tab meldet, was der Benutzer dort gewählt hat und ob Kopfhörer drin sind.
AUDIO_MODI = ("stumm", "ton", "zurueckhaltend", "interaktiv")
DRINGLICHKEITEN = ("niedrig", "normal", "hoch")

#: Der Weg einer dringenden Mitteilung in den Chat-Kanal des Besitzers: eine Funktion `(text) -> dict` (Antwort der
#: Brücke des Agenten, mit `kanal`). Das Plugin `openclaw` meldet sie an, solange die Kopplung an den Agenten steht.
_kanal_weg: Callable[[str], dict[str, Any]] | None = None


def kanal_anmelden(weg: Callable[[str], dict[str, Any]] | None) -> None:
    """Meldet den Weg zum Chat-Kanal an (None: abmelden)."""
    global _kanal_weg
    _kanal_weg = weg


def angemeldeter_kanal() -> Callable[[str], dict[str, Any]] | None:
    return _kanal_weg

_STEUERZEICHEN = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_LEERRAUM = re.compile(r"\s{2,}")


# ── Bereinigung (alles, was der Browser meldet, ist Eingabe von außen) ────────────────────────
def text(x: Any, n: int) -> str:
    """Text ohne Steuerzeichen, auf n Zeichen gekürzt (mit …). Kein String -> leer."""
    if not isinstance(x, str):
        return ""
    s = _LEERRAUM.sub(" ", _STEUERZEICHEN.sub(" ", x)).strip()
    return s if len(s) <= n else s[: max(1, n - 1)].rstrip() + "…"


def ganzzahl(x: Any, lo: int, hi: int, standard: int | None = None) -> int | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return standard
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return standard
    return max(lo, min(hi, int(x)))


def _fenster(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    fid = text(x.get("id"), 120)
    if not fid:
        return None
    art = x.get("art")
    return {
        "id": fid,
        "titel": text(x.get("titel"), 80) or fid,
        "art": art if art in FENSTER_ARTEN else "seite",
        "bildschirm": ganzzahl(x.get("bildschirm"), 0, 99, 1),
        "bildschirm_name": text(x.get("bildschirm_name"), 40),
        "vorne": bool(x.get("vorne")),
        "min": bool(x.get("min")),
    }


def _flaeche(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    fid = text(x.get("id"), 120)
    if not fid:
        return None
    return {
        "id": fid,
        "titel": text(x.get("titel"), 80) or fid,
        "gruppe": text(x.get("gruppe"), 40),
    }


def _werkzeug(x: Any) -> dict[str, Any] | None:
    if not isinstance(x, dict):
        return None
    name = x.get("name")
    if not isinstance(name, str) or not WERKZEUG_MUSTER.match(name):
        return None
    w: dict[str, Any] = {
        "name": name,
        "beschreibung": text(x.get("beschreibung"), 300),
        "lesend": bool(x.get("lesend")),
    }
    eingabe = x.get("eingabe")
    if isinstance(eingabe, dict):
        try:
            if len(json.dumps(eingabe, ensure_ascii=False)) <= 2048:
                w["eingabe"] = eingabe
        except (TypeError, ValueError):
            pass
    return w


def _liste(
    x: Any, wandler: Callable[[Any], dict[str, Any] | None], grenze: int
) -> list[dict[str, Any]]:
    if not isinstance(x, list):
        return []
    out: list[dict[str, Any]] = []
    for e in x[: grenze * 2]:
        v = wandler(e)
        if v is not None:
            out.append(v)
        if len(out) >= grenze:
            break
    return out


def zeitmarke(x: Any) -> int | None:
    """Zeitmarke des Browsers in ms seit 1970 (seine Uhr — nur zum Vergleichen untereinander). Sonst None."""
    if isinstance(x, str):
        try:
            x = float(x)
        except ValueError:
            return None
    return ganzzahl(x, 0, 4_102_444_800_000, None)


def sitzung_pruefen(x: Any) -> str:
    if not isinstance(x, str) or not SITZUNG_MUSTER.match(x):
        raise ValueError("sitzung fehlt oder ist ungültig (6–64 Zeichen aus A–Z a–z 0–9 _ -)")
    return x


def audio_bereinigen(x: Any) -> dict[str, Any]:
    """`{modus, kopfhoerer}` aus der Meldung; Unbekanntes wird None (= nicht gewählt / nicht bekannt)."""
    a = x if isinstance(x, dict) else {}
    modus = a.get("modus")
    kopfhoerer = a.get("kopfhoerer")
    return {
        "modus": modus if modus in AUDIO_MODI else None,
        "kopfhoerer": kopfhoerer if isinstance(kopfhoerer, bool) else None,
    }


def audio_wirksam(audio: Any) -> str:
    """Der Modus, der gerade gilt. Ohne Kopfhörer (oder unbekannt) höchstens „ton“: Hinweiston, keine
    Sprache — der Agent spricht nie in einen Raum, nur in Kopfhörer. „stumm“ gilt immer. Nichts gewählt:
    mit Kopfhörern „zurueckhaltend“, sonst „ton“."""
    a = audio if isinstance(audio, dict) else {}
    modus = a.get("modus")
    kopfhoerer = a.get("kopfhoerer") is True
    if modus in ("stumm", "ton"):
        return modus
    if modus in ("zurueckhaltend", "interaktiv"):
        return modus if kopfhoerer else "ton"
    return "zurueckhaltend" if kopfhoerer else "ton"


def ausgabe_fuer(wirksam: str, dringlichkeit: str) -> dict[str, bool]:
    """Was das Gerät mit einer Mitteilung tut: `klang` (Hinweiston), `sprechen` (vorlesen, nur mit Kopfhörern).

    stumm: nur die Karte. ton: Karte + Hinweiston (außer niedrig). zurueckhaltend: spricht nur bei hoch.
    interaktiv: spricht außer bei niedrig. Die Karte erscheint immer."""
    niedrig = dringlichkeit == "niedrig"
    if wirksam == "stumm":
        return {"klang": False, "sprechen": False}
    if wirksam == "zurueckhaltend":
        return {"klang": not niedrig, "sprechen": dringlichkeit == "hoch"}
    if wirksam == "interaktiv":
        return {"klang": True, "sprechen": not niedrig}
    return {"klang": not niedrig, "sprechen": False}


def meldung_bereinigen(roh: Any) -> dict[str, Any]:
    """Meldung des Browsers -> gespeicherte Form (ohne Hub-Zeiten). Wirft ValueError."""
    if not isinstance(roh, dict):
        raise ValueError("Die Meldung muss ein JSON-Objekt sein")
    sitzung = sitzung_pruefen(roh.get("sitzung"))
    art = roh.get("art")
    bildschirme = []
    for b in (roh.get("bildschirme") if isinstance(roh.get("bildschirme"), list) else [])[
        :BILDSCHIRME_MAX
    ]:
        if isinstance(b, dict):
            bildschirme.append(
                {"index": ganzzahl(b.get("index"), 0, 99, 0), "name": text(b.get("name"), 40)}
            )
    return {
        "sitzung": sitzung,
        "geraet": text(roh.get("geraet"), 40) or "Browser",
        "art": art if art in GERAETE_ARTEN else "computer",
        "seite": text(roh.get("seite"), 200),
        "sichtbar": bool(roh.get("sichtbar", True)),
        "aktiv_vor_s": ganzzahl(roh.get("aktiv_vor_s"), 0, 7 * 86400, None),
        "anruf": bool(roh.get("anruf")),
        "agent_vorne": bool(roh.get("agent_vorne")),
        "bildschirm": ganzzahl(roh.get("bildschirm"), 0, 99, 0),
        "bildschirme": bildschirme,
        "fenster": _liste(roh.get("fenster"), _fenster, FENSTER_MAX),
        "flaechen": _liste(roh.get("flaechen"), _flaeche, FLAECHEN_MAX),
        "werkzeuge": _liste(roh.get("werkzeuge"), _werkzeug, WERKZEUGE_MAX),
        "audio": audio_bereinigen(roh.get("audio")),
        "abholen": roh.get("abholen") is True,
        "version": ganzzahl(roh.get("version"), 0, 99, 1),
    }


# ── Hilfen: Ziele, Links, Vorschau ────────────────────────────────────────────────────────────
def neue_befehls_id() -> str:
    return "b-" + secrets.token_hex(6)


def ziel_normalisieren(ziel: Any, fqtn_bekannt: Callable[[str], bool] | None = None) -> str:
    """`ziel` eines Befehls: Flächen-ID (`app:`, `seite:`, `nativ:`, `agent`) oder ein Name wie im Dock.

    Kleingeschrieben und tolerant: `App:meine_app.zeigen` und `meine_app.zeigen` (Hub-Werkzeug-ID mit
    Oberfläche) werden zu `app:meine_app__zeigen`. Ein Name („Finanzen“) bleibt unverändert — die Shell
    löst ihn über seine Flächenliste auf.
    """
    if not isinstance(ziel, str) or not ziel.strip():
        raise ValueError('ziel fehlt — z. B. "app:meine_app__zeigen", "seite:uebersicht" oder "Uebersicht"')
    z = ziel.strip()
    if len(z) > 120 or _STEUERZEICHEN.search(z):
        raise ValueError("ziel ist zu lang oder enthält Steuerzeichen")
    kopf, sep, rest = z.partition(":")
    if sep and kopf.lower() in ("app", "seite", "nativ"):
        rest = rest.strip()
        if kopf.lower() == "app":
            rest = rest.replace(".", "__", 1) if "__" not in rest else rest
        z = f"{kopf.lower()}:{rest.lower()}"
    elif z.lower() == "agent":
        z = "agent"
    elif FQTN_MUSTER.match(z.lower()) and fqtn_bekannt is not None and fqtn_bekannt(z.lower()):
        z = "app:" + z.lower().replace(".", "__", 1)
    return z


def deeplink(
    ziel: str, eingabe: dict[str, Any] | None = None, basis: str | None = None
) -> str | None:
    """Deeplink — nur für Flächen-IDs (ein bloßer Name hat keinen Link).

    Eine Eingabe über `_identitaet.EINGABE_MAX` Zeichen JSON fehlt im Link — die EINE Grenze für `oeffnen_link`, diesen
    Link, den Befehl an die Shell und den Browser.
    """
    if not isinstance(ziel, str) or not ZIEL_ID_MUSTER.match(ziel):
        return None
    wurzel = (basis or BASIS_URL_VORGABE).rstrip("/")
    shell = f"{wurzel}/os" if wurzel else _identitaet.OS_ADRESSE
    url = f"{shell}?offen={urllib.parse.quote(ziel, safe=':/_-')}"
    kodiert = _identitaet.eingabe_kodiert(eingabe)
    if kodiert:
        url += "&eingabe=" + kodiert
    return url


def eingabe_kappen(eingabe: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """(Eingabe, gekappt): eine Eingabe über `_identitaet.EINGABE_MAX` Zeichen JSON wird weggelassen (None, True) —
    sonst käme sie nie an (die Shell liest nicht mehr) und die Antwort sähe nach Erfolg aus."""
    if eingabe and _identitaet.eingabe_zu_gross(eingabe):
        return None, True
    return eingabe, False


#: Satz für den Agenten, wenn eine zu große Eingabe weggelassen wurde.
EINGABE_GEKAPPT = (
    " Die Eingabe war zu groß (über 4000 Zeichen) und wurde weggelassen: die App öffnet ohne sie."
)


_VORSCHAU_SCHLUESSEL = (
    "satz",
    "lage_satz",
    "zusammenfassung",
    "summary",
    "hinweis",
    "kurz",
    "text",
)


def vorschau_aus(ergebnis: Any, n: int = 140) -> str | None:
    """Ein Satz aus einem Werkzeugergebnis für die Mitteilung — oder None, wenn keiner da ist."""
    if isinstance(ergebnis, str):
        return text(ergebnis, n) or None
    if not isinstance(ergebnis, dict):
        return None
    for ebene in (ergebnis, *[v for v in ergebnis.values() if isinstance(v, dict)]):
        for k in _VORSCHAU_SCHLUESSEL:
            v = ebene.get(k)
            if isinstance(v, str) and v.strip():
                return text(v, n)
    return None


def ergebnis_vereinfachen(e: Any) -> dict[str, Any]:
    """MCP-Ergebnis des Browser-Werkzeugs -> {text?, daten?, abgeschnitten?} für den Agenten."""
    out: dict[str, Any] = {}
    if isinstance(e, dict) and "content" in e:
        teile = [
            c.get("text")
            for c in (e.get("content") or [])
            if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str)
        ]
        if teile:
            out["text"] = "\n".join(teile)
        if e.get("structuredContent") is not None:
            out["daten"] = e["structuredContent"]
    elif e is not None:
        out["daten"] = e
    try:
        gesamt = json.dumps(out, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"text": str(e)[: ERGEBNIS_MAX_ZEICHEN - 1], "abgeschnitten": True}
    if len(gesamt) <= ERGEBNIS_MAX_ZEICHEN:
        return out
    # Zu groß für den Agentens Kontext: der Text bleibt (gekürzt), strukturierte Daten fallen weg.
    roh = out.get("text") or gesamt
    return {"text": roh[: ERGEBNIS_MAX_ZEICHEN - 1] + "…", "abgeschnitten": True}


def sse_ereignis(ereignis: str, daten: Any, eid: str | None = None) -> str:
    zeilen = []
    if eid:
        zeilen.append(f"id: {eid}")
    zeilen.append(f"event: {ereignis}")
    zeilen.append("data: " + json.dumps(daten, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(zeilen) + "\n\n"


def _eintraege(antwort: Any) -> list[tuple[str, dict[str, str]]]:
    """XREAD-Antwort (RESP2-Liste oder RESP3-Dict) -> [(id, felder)]."""
    out: list[tuple[str, dict[str, str]]] = []
    if not antwort:
        return out
    if isinstance(antwort, dict):
        gruppen = list(antwort.values())
    else:
        gruppen = [g[1] for g in antwort]
    for eintraege in gruppen:
        for e in eintraege:
            eid, felder = e[0], e[1]
            out.append((eid, felder if isinstance(felder, dict) else {}))
    return out


def _schluessel_hash(*teile: Any) -> str:
    return hashlib.sha1(
        json.dumps(teile, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()[:20]


# ── Die Brücke ───────────────────────────────────────────────────────────────────────────────
class Bruecke:
    """Sitzungen, Befehle, Antworten und „Agent zeigt“ — Zustand liegt in Redis, nicht hier."""

    def __init__(
        self,
        redis_url: str | None = None,
        basis_url: str | None = None,
        zeit: Callable[[], float] = time.time,
        agent_aufrufer: tuple[str, ...] | list[str] | None = None,
        agent_zeigt: bool = True,
        redis: Any = None,
        redis_async: Callable[[], Any] | None = None,
        nachholen: bool = True,
        kanal: bool = True,
        kanal_weg: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.redis_url = redis_url or os.getenv("REDIS_URL", REDIS_URL_VORGABE)
        #: Mitteilungen ohne Gerät vormerken und später ausliefern (Abschnitt „Nachholen“ oben)
        self.nachholen_an = nachholen
        #: Dringende Mitteilungen ohne Gerät sofort in den Chat-Kanal des Besitzers schicken (Abschnitt „Kanal“ oben)
        self.kanal_an = kanal
        self._kanal_weg = kanal_weg  # Tests; sonst der angemeldete Weg (kanal_anmelden)
        self.basis_url = (basis_url or os.getenv("OS_BASIS_URL") or BASIS_URL_VORGABE).rstrip("/")
        self._zeit = zeit
        self.agent_aufrufer = tuple(agent_aufrufer) if agent_aufrufer else AGENT_AUFRUFER_VORGABE
        self.agent_zeigt_an = agent_zeigt
        self._redis = redis  # Tests setzen eine Attrappe
        self._redis_eingesetzt = redis is not None
        self._redis_async = redis_async
        self._warte: dict[int, Any] = {}
        #: vom Plugin gesetzt (registry_anbinden): ist `plugin.werkzeug` ein Werkzeug mit Oberfläche?
        self.app_werkzeug_bekannt: Callable[[str], bool] | None = None

    @classmethod
    def aus_umgebung(cls, cfg: dict[str, Any] | None = None) -> "Bruecke":
        cfg = dict(cfg or {})
        env_liste = os.getenv("OS_AGENT_AUFRUFER")
        if env_liste is not None and env_liste.strip():
            aufrufer = [s.strip() for s in env_liste.split(",") if s.strip()]
        else:
            aufrufer = (
                cfg.get("agent_aufrufer") if isinstance(cfg.get("agent_aufrufer"), list) else None
            )
        aus = (os.getenv("OS_AGENT_ZEIGT") or "").strip().lower() in (
            "aus",
            "0",
            "false",
            "nein",
            "off",
        )
        nachholen_aus = (os.getenv("OS_NACHHOLEN") or "").strip().lower() in (
            "aus",
            "0",
            "false",
            "nein",
            "off",
        )
        kanal_aus = (os.getenv("OS_KANAL") or "").strip().lower() in (
            "aus",
            "0",
            "false",
            "nein",
            "off",
        )
        return cls(
            redis_url=cfg.get("redis_url") or None,
            basis_url=cfg.get("basis_url") or None,
            agent_aufrufer=aufrufer,
            agent_zeigt=bool(cfg.get("agent_zeigt", True)) and not aus,
            nachholen=bool(cfg.get("nachholen", True)) and not nachholen_aus,
            kanal=bool(cfg.get("kanal", True)) and not kanal_aus,
        )

    # ── Redis ───────────────────────────────────────────────────────────────────────────────
    def _r(self) -> Any:
        if self._redis is None:
            import redis  # im Hub-Image vorhanden

            self._redis = redis.Redis.from_url(
                self.redis_url, socket_timeout=3, socket_connect_timeout=3, decode_responses=True
            )
        return self._redis

    def _r_warten(self, frist_s: float) -> Any:
        """Client, dessen Lesezeit länger als das Blockieren ist (BLPOP)."""
        if self._redis_eingesetzt:
            return self._redis  # Attrappe in Tests
        sekunden = int(math.ceil(frist_s)) + 5
        if sekunden not in self._warte:
            import redis

            self._warte[sekunden] = redis.Redis.from_url(
                self.redis_url,
                socket_timeout=sekunden,
                socket_connect_timeout=3,
                decode_responses=True,
            )
        return self._warte[sekunden]

    def async_client(self) -> Any:
        """Frischer async-Client je Strom (XREAD BLOCK belegt die Verbindung). Der Aufrufer schließt ihn."""
        if self._redis_async is not None:
            return self._redis_async()
        import redis.asyncio as aioredis

        return aioredis.Redis.from_url(
            self.redis_url,
            socket_timeout=PING_S + 10,
            socket_connect_timeout=3,
            decode_responses=True,
        )

    def ping(self) -> bool:
        return bool(self._r().ping())

    # ── Sitzungen ───────────────────────────────────────────────────────────────────────────
    def melden(self, roh: Any) -> dict[str, Any]:
        """Meldung speichern (90 s). `{sitzung, ende: true}` beendet die Sitzung."""
        if isinstance(roh, dict) and roh.get("ende") is True:
            sitzung = sitzung_pruefen(roh.get("sitzung"))
            self.beenden(sitzung, gesendet=zeitmarke(roh.get("gesendet")))
            return {"ok": True, "beendet": True}
        meldung = meldung_bereinigen(roh)
        jetzt = self._zeit()
        r = self._r()
        sid = meldung["sitzung"]
        gesendet = zeitmarke(roh.get("gesendet"))
        if gesendet is not None:
            ende = zeitmarke(r.get(SCHL_ENDE + sid))
            if ende is not None:
                if gesendet <= ende:
                    # Wettlauf beim Schließen des Tabs: diese Meldung ging VOR dem Abschied ab und kam nur
                    # später an. Sie darf die beendete Sitzung nicht wieder aufmachen.
                    logger.info("os: Meldung von %s kam nach dem Ende an, verworfen", sid)
                    offen = int(r.zcount(SCHL_SITZUNGEN, jetzt - SITZUNG_TTL_S, "+inf"))
                    return {"ok": True, "veraltet": True, "ablauf_s": 0, "sitzungen": offen}
                r.delete(
                    SCHL_ENDE + sid
                )  # eine neuere Meldung (Neuladen, Seite zurück): die Sitzung lebt wieder
        alt = _json_laden(r.get(SCHL_SITZUNG + sid))
        if alt is None:
            logger.info("os: Sitzung %s offen (%s)", sid, meldung["geraet"])
        erste = alt.get("erste_meldung") if isinstance(alt, dict) else None
        meldung["erste_meldung"] = erste if isinstance(erste, (int, float)) else jetzt
        meldung["gemeldet"] = jetzt
        akt = meldung["aktiv_vor_s"]
        meldung["zuletzt_aktiv"] = jetzt - akt if akt is not None else meldung["erste_meldung"]
        r.set(
            SCHL_SITZUNG + sid,
            json.dumps(meldung, ensure_ascii=False, separators=(",", ":")),
            ex=SITZUNG_TTL_S,
        )
        r.zadd(SCHL_SITZUNGEN, {sid: jetzt})
        r.expire(SCHL_SITZUNGEN, 7200)
        offen = int(r.zcount(SCHL_SITZUNGEN, jetzt - SITZUNG_TTL_S, "+inf"))
        erg: dict[str, Any] = {"ok": True, "ablauf_s": SITZUNG_TTL_S, "sitzungen": offen}
        # Sitzt jemand davor, kommt jetzt nach, was in der Zwischenzeit vorgemerkt wurde (vor dem Abholen, damit
        # eine Sitzung ohne Strom es in derselben Antwort bekommt). Ein Fehler hier stört die Meldung nicht.
        try:
            self.nachholen(meldung)
        except Exception as exc:  # noqa: BLE001
            logger.warning("os: Nachholen für %s: %s", sid, exc)
        if meldung["abholen"]:
            befehle, nach = self.abholen(sid, roh.get("nach"))
            erg["befehle"] = befehle
            erg["nach"] = nach
        return erg

    def abholen(self, sitzung: str, nach: Any = None) -> tuple[list[dict[str, Any]], str]:
        """Befehle einer Sitzung ohne Strom (iPhone-App), dieselben Regeln wie `strom`: nie älter als 120 s,
        beim ersten Abholen (ohne `nach`) nur frische. Liefert die Befehle und die Stream-ID, ab der das
        nächste Abholen liest."""
        erst = not (isinstance(nach, str) and STREAM_ID_MUSTER.match(nach))
        letzte = "0-0" if erst else nach
        antwort = self._r().xread({SCHL_BEFEHLE + sitzung: letzte}, count=20)
        befehle: list[dict[str, Any]] = []
        for eid, felder in _eintraege(antwort):
            letzte = eid
            befehl = _json_laden(felder.get("d"))
            if not isinstance(befehl, dict):
                continue
            try:
                alter = max(0.0, self._zeit() - float(felder.get("t") or self._zeit()))
            except ValueError:
                alter = 0.0
            if alter > BEFEHL_MAX_ALTER_S or (erst and alter > ERSTVERBINDUNG_ALTER_S):
                continue
            befehl["alter_s"] = round(alter, 2)
            befehl["eid"] = eid
            befehle.append(befehl)
        return befehle, letzte

    def beenden(self, sitzung: str, gesendet: int | None = None) -> None:
        """Sitzung sofort beenden. Mit `gesendet` (Zeit des Abschieds auf der Uhr des Browsers) merkt sich der Hub
        das Ende 120 s lang: eine Meldung, die vor dem Abschied abgeschickt wurde und danach ankommt, zählt nicht."""
        logger.info("os: Sitzung %s beendet", sitzung)
        r = self._r()
        r.delete(SCHL_SITZUNG + sitzung)
        r.zrem(SCHL_SITZUNGEN, sitzung)
        r.delete(SCHL_BEFEHLE + sitzung)
        if gesendet is not None:
            r.set(SCHL_ENDE + sitzung, str(gesendet), ex=ENDE_MARKE_S)

    def sitzungen(self) -> list[dict[str, Any]]:
        """Offene Sitzungen, die zuerst genannte ist die zuletzt aktive (sichtbare vor verdeckten)."""
        jetzt = self._zeit()
        r = self._r()
        grenze = jetzt - SITZUNG_TTL_S
        ids = list(r.zrangebyscore(SCHL_SITZUNGEN, grenze, "+inf") or [])
        if not ids:
            return []
        roh = r.mget([SCHL_SITZUNG + i for i in ids])
        out: list[dict[str, Any]] = []
        for sid, wert in zip(ids, roh):
            s = _json_laden(wert)
            if isinstance(s, dict) and s.get("sitzung") == sid:
                out.append(s)
        try:
            r.zremrangebyscore(SCHL_SITZUNGEN, "-inf", grenze - 1)
        except Exception:  # noqa: BLE001 — Aufräumen ist nur Kür
            pass
        out.sort(
            key=lambda s: (
                1 if s.get("sichtbar") else 0,
                s.get("zuletzt_aktiv", 0.0),
                s.get("gemeldet", 0.0),
            ),
            reverse=True,
        )
        return out

    def waehle(
        self, sitzung: str | None = None, antwortet: bool = False
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """Die gemeinte Sitzung (ID oder Gerätename; sonst die zuletzt aktive) und alle offenen.
        `antwortet`: ohne Namen nur Sitzungen mit Strom (Abhol-Sitzungen beantworten zeigen/ausfuehren nicht)."""
        liste = self.sitzungen()
        if not liste:
            return None, liste
        if antwortet and not (sitzung and sitzung.strip()):
            mit_strom = [e for e in liste if not e.get("abholen")]
            return (mit_strom[0] if mit_strom else None), liste
        if sitzung and sitzung.strip():
            s = sitzung.strip()
            for e in liste:
                if e["sitzung"] == s:
                    return e, liste
            passend = [e for e in liste if e.get("geraet", "").lower() == s.lower()]
            return (passend[0] if passend else None), liste
        return liste[0], liste

    # ── Befehle und Antworten ───────────────────────────────────────────────────────────────
    def senden(self, sitzung: str, befehl: dict[str, Any]) -> str:
        """Befehl in den Stream der Sitzung legen; liefert die Stream-ID."""
        r = self._r()
        schluessel = SCHL_BEFEHLE + sitzung
        felder = {
            "d": json.dumps(befehl, ensure_ascii=False, separators=(",", ":")),
            "t": f"{self._zeit():.3f}",
        }
        # Wer antworten darf: nur die Sitzung, an die der Befehl ging (vor dem Versand merken, die Antwort kann sofort kommen)
        if befehl.get("art") in ("zeigen", "ausfuehren") and isinstance(befehl.get("id"), str):
            r.set(SCHL_BEFEHL + befehl["id"], sitzung, ex=ANTWORT_TTL_S)
        eid = r.xadd(schluessel, felder, maxlen=STROM_MAXLEN, approximate=True)
        r.expire(schluessel, STROM_TTL_S)
        return eid

    def antwort_ablegen(self, roh: Any) -> dict[str, Any]:
        if not isinstance(roh, dict):
            raise ValueError("Die Antwort muss ein JSON-Objekt sein")
        sitzung = sitzung_pruefen(roh.get("sitzung"))
        befehl = roh.get("befehl")
        if not isinstance(befehl, str) or not BEFEHL_MUSTER.match(befehl):
            raise ValueError("befehl fehlt oder ist ungültig")
        r = self._r()
        # Der Befehl gehört zu der Sitzung, an die er ging: eine andere Sitzung (anderer Tab, fremdes Gerät) darf ihn
        # nicht beantworten — sonst könnte sie Agent ein Ergebnis unterschieben. Ein unbekannter oder abgelaufener
        # Befehl (nach 60 s wartet niemand mehr) wird ebenso abgewiesen.
        gebunden = r.get(SCHL_BEFEHL + befehl)
        if gebunden != sitzung:
            if gebunden is None:
                raise ValueError("befehl unbekannt oder abgelaufen")
            logger.warning(
                "os: Antwort auf %s von Sitzung %s abgewiesen (gehört %s)",
                befehl,
                sitzung,
                gebunden,
            )
            raise ValueError("befehl gehört zu einer anderen Sitzung")
        ok = roh.get("ok") is True
        eintrag = {
            "sitzung": sitzung,
            "ok": ok,
            "ergebnis": roh.get("ergebnis"),
            "fehler": text(roh.get("fehler"), 2000) or None,
        }
        wert = json.dumps(eintrag, ensure_ascii=False, separators=(",", ":"))
        if len(wert.encode()) > ANTWORT_MAX_BYTES:
            eintrag["ergebnis"] = None
            eintrag["fehler"] = eintrag["fehler"] or "Antwort zu groß (über 256 KB) — verworfen"
            eintrag["ok"] = False
            wert = json.dumps(eintrag, ensure_ascii=False, separators=(",", ":"))
        r.rpush(SCHL_ANTWORT + befehl, wert)
        r.expire(SCHL_ANTWORT + befehl, ANTWORT_TTL_S)
        return {"ok": True}

    def warten(self, befehl_id: str, frist_s: float) -> dict[str, Any] | None:
        """Auf die Antwort zu einem Befehl warten (blockiert den Thread, nie die Ereignisschleife)."""
        r = self._r_warten(frist_s)
        treffer = r.blpop([SCHL_ANTWORT + befehl_id], timeout=int(math.ceil(frist_s)))
        if not treffer:
            return None
        antwort = _json_laden(treffer[1])
        return antwort if isinstance(antwort, dict) else None

    # ── Die Handgriffe des Agenten ───────────────────────────────────────────────────────
    def von_aus(self, aufrufer: str) -> str:
        return "agent" if self.ist_agent(aufrufer) else (text(aufrufer, 40) or "unbekannt")

    @staticmethod
    def _unbekannt(sitzung: str, liste: list[dict[str, Any]]) -> dict[str, Any]:
        namen = ", ".join(f"{e['sitzung']} ({e.get('geraet')})" for e in liste) or "keine"
        return {
            "ok": False,
            "error": f"Sitzung {sitzung!r} ist nicht offen. Offen: {namen}.",
            "kind": "sitzung_unbekannt",
        }

    def lage(self, sitzung: str | None = None, flaechen: bool = False) -> dict[str, Any]:
        """Offene Sitzungen (zuletzt aktive zuerst). Mit `sitzung` nur diese, samt Eingabe-Schemas."""
        jetzt = self._zeit()
        gewaehlt, liste = self.waehle(sitzung)
        if sitzung and sitzung.strip():
            if gewaehlt is None:
                return self._unbekannt(sitzung, liste)
            zeigen = [gewaehlt]
        else:
            zeigen = liste
        out = [
            _lage_eintrag(s, jetzt, mit_schema=i == 0 or bool(sitzung), flaechen=flaechen)
            for i, s in enumerate(zeigen)
        ]
        return {
            "offen": bool(liste),
            "anzahl": len(liste),
            "sitzungen": out,
            "satz": _lage_satz(liste[0] if liste else None, jetzt, len(liste)),
        }

    def ziel_normalisiert(self, ziel: Any) -> str:
        return ziel_normalisieren(ziel, self.app_werkzeug_bekannt)

    def zeigen(
        self, ziel: Any, eingabe: Any = None, sitzung: str | None = None, von: str = "agent"
    ) -> dict[str, Any]:
        z = self.ziel_normalisiert(ziel)
        if eingabe is not None and not isinstance(eingabe, dict):
            raise ValueError("eingabe muss ein Objekt sein (die Argumente der App)")
        if (
            eingabe is not None
            and len(json.dumps(eingabe, ensure_ascii=False)) > ARGUMENTE_MAX_BYTES
        ):
            raise ValueError("eingabe ist zu groß (über 16 KB)")
        # Über 4000 Zeichen kommt eine Eingabe nirgends an (Link und OS lesen nicht mehr): weglassen und sagen
        eingabe, gekappt = eingabe_kappen(eingabe)
        erg = self._zeigen(z, eingabe, sitzung, von)
        if gekappt and isinstance(erg.get("satz"), str):
            erg = {**erg, "eingabe_weggelassen": True, "satz": erg["satz"] + EINGABE_GEKAPPT}
        return erg

    def _zeigen(
        self, z: str, eingabe: dict[str, Any] | None, sitzung: str | None, von: str
    ) -> dict[str, Any]:
        s, liste = self.waehle(sitzung, antwortet=True)
        link = deeplink(z, eingabe or None, self.basis_url)
        if s is None:
            if sitzung and liste:
                return self._unbekannt(sitzung, liste)
            satz = "Die Shell ist gerade nirgends offen."
            satz += (
                f" Dieser Link öffnet es genau so: {link}"
                if link
                else " Ein Link geht nur mit einer Flächen-ID wie app:meine_app__zeigen."
            )
            return {
                "gezeigt": False,
                "grund": "kein_os_offen",
                "ziel": z,
                "link": link,
                "satz": satz,
            }
        befehl = {
            "id": neue_befehls_id(),
            "art": "zeigen",
            "ziel": z,
            "eingabe": eingabe or None,
            "von": von,
        }
        self.senden(s["sitzung"], befehl)
        antwort = self.warten(befehl["id"], ZEIGEN_FRIST_S)
        geraet = s.get("geraet") or "dem Gerät"
        if antwort is None:
            satz = f"Auf {geraet} kam keine Bestätigung (der Tab reagiert nicht)."
            if link:
                satz += f" Dieser Link öffnet es genau so: {link}"
            return {
                "gezeigt": False,
                "grund": "keine_antwort",
                "sitzung": s["sitzung"],
                "geraet": geraet,
                "ziel": z,
                "link": link,
                "satz": satz,
            }
        if not antwort.get("ok"):
            return {
                "ok": False,
                "error": antwort.get("fehler") or f"Das OS auf {geraet} konnte {z} nicht öffnen.",
                "kind": "abgelehnt",
                "sitzung": s["sitzung"],
                "geraet": geraet,
            }
        erg = antwort.get("ergebnis") if isinstance(antwort.get("ergebnis"), dict) else {}
        titel = text(erg.get("titel"), 80) or z
        satz = f"Ich habe {titel} auf {geraet} geöffnet."
        if not s.get("sichtbar"):
            satz += " Der Tab ist gerade im Hintergrund."
        ergebnis: dict[str, Any] = {
            "gezeigt": True,
            "sitzung": s["sitzung"],
            "geraet": geraet,
            "ziel": erg.get("ziel") if isinstance(erg.get("ziel"), str) else z,
            "titel": titel,
            "bildschirm": erg.get("bildschirm"),
            "link": link,
            "satz": satz,
        }
        # Hat das OS die Eingabe an die App weitergegeben? Nur sagen, was die Seite gemeldet hat.
        uebernommen = erg.get("eingabe_uebernommen")
        if eingabe and isinstance(uebernommen, bool):
            ergebnis["eingabe_uebernommen"] = uebernommen
            if not uebernommen:
                ergebnis["satz"] += (
                    " Die Eingabe konnte das OS der App nicht übergeben, sie ist ohne sie offen."
                )
        return ergebnis

    def ausfuehren(
        self, werkzeug: Any, argumente: Any = None, sitzung: str | None = None, von: str = "agent"
    ) -> dict[str, Any]:
        if not isinstance(werkzeug, str) or not WERKZEUG_MUSTER.match(werkzeug):
            raise ValueError(
                "werkzeug fehlt oder ist ungültig — nimm einen Namen aus der Lage (z. B. os_fenster)"
            )
        if argumente is not None and not isinstance(argumente, dict):
            raise ValueError("argumente muss ein Objekt sein")
        argumente = argumente or {}
        if len(json.dumps(argumente, ensure_ascii=False)) > ARGUMENTE_MAX_BYTES:
            raise ValueError("argumente sind zu groß (über 16 KB)")
        s, liste = self.waehle(sitzung, antwortet=True)
        if s is None:
            if sitzung and liste:
                return self._unbekannt(sitzung, liste)
            return {
                "ok": False,
                "error": "Die Shell ist gerade nirgends offen — es gibt kein Seitenwerkzeug, das antworten könnte.",
                "kind": "kein_os_offen",
            }
        angeboten = [w["name"] for w in s.get("werkzeuge", [])]
        if werkzeug not in angeboten:
            return {
                "ok": False,
                "error": f"{s.get('geraet')} bietet {werkzeug!r} nicht an. Angeboten: {', '.join(angeboten) or 'nichts'}.",
                "kind": "werkzeug_unbekannt",
            }
        befehl = {
            "id": neue_befehls_id(),
            "art": "ausfuehren",
            "werkzeug": werkzeug,
            "argumente": argumente,
            "von": von,
        }
        self.senden(s["sitzung"], befehl)
        antwort = self.warten(befehl["id"], AUSFUEHREN_FRIST_S)
        geraet = s.get("geraet") or "das Gerät"
        if antwort is None:
            return {
                "ok": False,
                "error": f"{geraet} hat nicht innerhalb von {AUSFUEHREN_FRIST_S} s geantwortet (Tab im Hintergrund oder eingefroren?).",
                "kind": "zeitueberschreitung",
                "sitzung": s["sitzung"],
            }
        if not antwort.get("ok"):
            return {
                "ok": False,
                "error": antwort.get("fehler") or f"{werkzeug} ist auf {geraet} fehlgeschlagen.",
                "kind": "werkzeug_fehler",
                "sitzung": s["sitzung"],
                "geraet": geraet,
            }
        return {
            "ausgefuehrt": True,
            "werkzeug": werkzeug,
            "sitzung": s["sitzung"],
            "geraet": geraet,
            **ergebnis_vereinfachen(antwort.get("ergebnis")),
        }

    # ── Agent zeigt ─────────────────────────────────────────────────────────────────────────
    def ist_agent(self, aufrufer: str) -> bool:
        a = (aufrufer or "").strip().lower()
        if not a:
            return False
        for muster in self.agent_aufrufer:
            m = str(muster).strip().lower()
            if not m:
                continue
            if m.endswith("*"):
                if a.startswith(m[:-1]):
                    return True
            elif a == m:
                return True
        return False

    def agent_zeigt(self, tool: Any, arguments: dict[str, Any], tir: Any) -> None:
        """Ergebnis-Hook der Registry: ruft ein Agent eine App auf, bekommt der Bildschirm des Benutzers eine Mitteilung.

        Nie ein Fehler nach außen — der Aufruf selbst ist längst gelungen (die Registry schluckt zudem).
        """
        if not self.agent_zeigt_an or getattr(tir, "status", "") != "ok":
            return
        desc = tool.descriptor
        meta = desc.meta if isinstance(desc.meta, dict) else {}
        ui = meta.get("ui")
        if not isinstance(ui, dict) or ui.get("visibility") == ["app"] or tool.plugin_name == "os":
            return
        aufrufer = AUFRUFER.get()
        if not self.ist_agent(aufrufer):
            return
        try:
            self._agent_zeigt_senden(tool, desc, meta, arguments or {}, tir.result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("os: Agent zeigt: %s", exc)

    def _agent_zeigt_senden(
        self, tool: Any, desc: Any, meta: dict[str, Any], arguments: dict[str, Any], ergebnis: Any
    ) -> None:
        ziel_sitzung = self.anwesend()
        if ziel_sitzung is None:
            return
        sid = ziel_sitzung["sitzung"]
        app = tool.fqtn.replace(".", "__", 1)
        ziel = "app:" + app
        r = self._r()
        if not r.set(
            SCHL_ZEIGT + sid + ":" + _schluessel_hash(ziel, arguments),
            "1",
            ex=AGENT_ZEIGT_DEDUPE_S,
            nx=True,
        ):
            return
        n = r.incr(SCHL_RATE + sid)
        if n == 1:
            r.expire(SCHL_RATE + sid, AGENT_ZEIGT_RATE_S)
        if n > AGENT_ZEIGT_RATE_MAX:
            return
        app_meta = meta.get("app") if isinstance(meta.get("app"), dict) else {}
        eingabe, _ = eingabe_kappen(
            arguments or None
        )  # zu groß: die Mitteilung öffnet die App ohne Eingabe
        wirksam = audio_wirksam(ziel_sitzung.get("audio"))
        zeigt = {
            "ziel": ziel,
            "app": app,
            "titel": text(
                app_meta.get("titel")
                or desc.title
                or tool.tool_name.replace("_", " ").capitalize(),
                80,
            ),
            "untertitel": text(app_meta.get("untertitel"), 120) or None,
            "symbol": text(app_meta.get("symbol"), 40) or None,
            "ton": ganzzahl(app_meta.get("ton"), 0, 360, None),
            "vorschau": vorschau_aus(ergebnis),
            "eingabe": eingabe,
            "link": deeplink(ziel, eingabe, self.basis_url),
            # Antwort auf die eigene Frage des Benutzers: der Agent antwortet ohnehin, also nie vorlesen
            "audio": {"modus": wirksam, "klang": wirksam != "stumm", "sprechen": False},
        }
        self.senden(sid, {"id": neue_befehls_id(), "art": "zeigt", "zeigt": zeigt, "von": "agent"})

    def anwesend(self) -> dict[str, Any] | None:
        """Die Sitzung, vor der der Benutzer gerade sitzt: sichtbar und in den letzten 10 min benutzt. Sonst None."""
        jetzt = self._zeit()
        for s in self.sitzungen():
            if self._ist_da(s, jetzt):
                return s
        return None

    @staticmethod
    def _ist_da(s: dict[str, Any], jetzt: float) -> bool:
        """Sitzt jemand vor dieser Sitzung? Sichtbar und in den letzten 10 min benutzt."""
        return bool(s.get("sichtbar")) and jetzt - float(s.get("zuletzt_aktiv", 0)) <= AGENT_ZEIGT_AKTIV_S

    def nachholen(self, sitzung: dict[str, Any]) -> int:
        """Liefert vorgemerkte Mitteilungen an diese Sitzung aus, wenn jemand davor sitzt. Gibt die Zahl zurück.

        Ältester zuerst, jede genau einmal: `LPOP` entnimmt atomar, zwei Replikate oder zwei Geräte teilen sich die
        Liste, nie dieselbe Mitteilung. Abgelaufenes (über 24 h) wird verworfen. Scheitert das Senden, geht der Eintrag
        an den Anfang zurück und der Fehler weiter. Nachgeholtes ist still: keine Hinweistöne, kein Vorlesen."""
        if not self.nachholen_an or not self._ist_da(sitzung, self._zeit()):
            return 0
        r = self._r()
        sid = sitzung["sitzung"]
        wirksam = audio_wirksam(sitzung.get("audio"))
        n = 0
        for _ in range(AUSSTEHEND_MAX):
            roh = r.lpop(SCHL_AUSSTEHEND)
            if roh is None:
                break
            eintrag = _json_laden(roh)
            if not isinstance(eintrag, dict) or not isinstance(eintrag.get("zeigt"), dict):
                continue
            try:
                entstanden = float(eintrag.get("t"))
            except (TypeError, ValueError):
                continue
            if self._zeit() - entstanden > AUSSTEHEND_TTL_S:
                continue
            zeigt = {
                **eintrag["zeigt"],
                "nachgeholt": True,
                "entstanden": entstanden,
                "audio": {"modus": wirksam, "klang": False, "sprechen": False},
            }
            von = eintrag.get("von") if isinstance(eintrag.get("von"), str) else "agent"
            try:
                self.senden(sid, {"id": neue_befehls_id(), "art": "zeigt", "zeigt": zeigt, "von": von})
            except Exception:
                r.lpush(SCHL_AUSSTEHEND, roh)
                raise
            n += 1
        if n:
            logger.info("os: %d vorgemerkte Mitteilung(en) an %s ausgeliefert", n, sid)
        return n

    def ausstehend(self) -> int:
        """Wie viele Mitteilungen warten auf jemanden?"""
        return int(self._r().llen(SCHL_AUSSTEHEND) or 0)

    def _vormerken(
        self, zeigt: dict[str, Any], von: str, link: str | None, gekappt: bool
    ) -> dict[str, Any]:
        """Niemand ist da: die Mitteilung wartet bis zur nächsten Sitzung, vor der jemand sitzt."""
        weg = " Die Eingabe war zu groß (über 4000 Zeichen) und wurde weggelassen." if gekappt else ""
        if not self.nachholen_an:
            return {
                "zugestellt": False,
                "grund": "nicht_da",
                "rueckfall": "kanal",
                "link": link,
                "satz": "Der Benutzer sitzt gerade an keinem Gerät mit offener Shell (letzte 10 min). "
                "Nimm einen anderen Kanal oder heb es für später auf." + weg,
            }
        r = self._r()
        if not r.set(
            SCHL_ZEIGT + "ausstehend:" + _schluessel_hash("mitteilung", zeigt["titel"], zeigt["vorschau"]),
            "1",
            ex=AGENT_ZEIGT_DEDUPE_S,
            nx=True,
        ):
            return {
                "zugestellt": False,
                "grund": "doppelt",
                "vorgemerkt": True,
                "satz": "Dieselbe Mitteilung ist schon vorgemerkt.",
            }
        eintrag = {"zeigt": zeigt, "von": von, "t": self._zeit()}
        r.rpush(SCHL_AUSSTEHEND, json.dumps(eintrag, ensure_ascii=False, separators=(",", ":")))
        r.ltrim(SCHL_AUSSTEHEND, -AUSSTEHEND_MAX, -1)
        r.expire(SCHL_AUSSTEHEND, AUSSTEHEND_TTL_S)
        return {
            "zugestellt": False,
            "grund": "nicht_da",
            "vorgemerkt": True,
            "rueckfall": "vorgemerkt",
            "ausstehend": int(r.llen(SCHL_AUSSTEHEND) or 0),
            "link": link,
            "satz": "Der Benutzer sitzt gerade an keinem Gerät mit offener Shell. Die Mitteilung ist vorgemerkt und "
            "erscheint, sobald er die Shell öffnet (bis zu 24 h, ohne Ton). Du musst nichts weiter tun; nimm nur bei "
            "etwas Dringendem zusätzlich einen anderen Kanal." + weg,
        }

    def _ueber_kanal(self, zeigt: dict[str, Any]) -> dict[str, Any] | None:
        """Niemand ist da, die Mitteilung ist dringend: sofort über den Agenten in den Chat-Kanal des Besitzers.

        None: der Weg ist nicht vorhanden (Kanal aus oder keine Kopplung an den Agenten), es bleibt beim Vormerken.
        Mit `zugestellt`: erledigt (angekommen, oder vor kurzem schon gesendet). Nur `kanal_fehler`: der Weg ist
        da, aber es ging nicht (zu viele in kurzer Zeit, Kanal nicht eingerichtet oder gestört), dann wird vorgemerkt.
        """
        weg = self._kanal_weg or angemeldeter_kanal()
        if not self.kanal_an or weg is None:
            return None
        r = self._r()
        merke = SCHL_ZEIGT + "kanal:" + _schluessel_hash("mitteilung", zeigt["titel"], zeigt["vorschau"])
        if not r.set(merke, "1", ex=KANAL_DEDUPE_S, nx=True):
            return {
                "zugestellt": False,
                "grund": "doppelt",
                "weg": "kanal",
                "satz": "Dieselbe dringende Mitteilung ging vor weniger als 10 min schon in den Chat-Kanal.",
            }
        n = r.incr(SCHL_RATE + "kanal")
        if n == 1:
            r.expire(SCHL_RATE + "kanal", AGENT_ZEIGT_RATE_S)
        if n > KANAL_RATE_MAX:
            r.delete(merke)
            return {"kanal_fehler": "zu_viele"}
        teile = [zeigt["titel"], zeigt.get("vorschau") or ""]
        if str(zeigt.get("link") or "").startswith(("http://", "https://")):
            teile.append(zeigt["link"])
        try:
            antwort = weg("\n".join(x for x in teile if x)[:KANAL_TEXT_MAX])
        except Exception as exc:  # noqa: BLE001 — der Weg zum Agenten darf die Mitteilung nie verlieren
            logger.warning("os: Chat-Kanal: %s", text(f"{type(exc).__name__}: {exc}", 200))
            r.delete(merke)
            return {"kanal_fehler": "nicht_zugestellt"}
        name = text((antwort or {}).get("kanal"), 20) if isinstance(antwort, dict) else ""
        return {
            "zugestellt": True,
            "weg": "kanal",
            **({"kanal": name} if name else {}),
            "satz": "Niemand sitzt an der Shell und es war dringend: die Mitteilung ging sofort in den Chat-Kanal "
            "des Benutzers" + (f" ({name})" if name else "") + ". Du musst nichts weiter tun.",
        }

    def mitteilen(
        self,
        titel: Any,
        inhalt: Any = None,
        ziel: Any = None,
        eingabe: Any = None,
        dringlichkeit: Any = None,
        quelle: Any = None,
        von: str = "agent",
    ) -> dict[str, Any]:
        """Der Agent meldet sich von selbst: als Karte auf dem Gerät, vor dem der Benutzer sitzt — mit Hinweiston
        oder Stimme nach dessen Ton-Modus. Ist er an keinem Gerät, wird die Mitteilung vorgemerkt und erscheint, sobald
        er die Shell öffnet (`vorgemerkt: true`, `rueckfall: "vorgemerkt"`, Abschnitt „Nachholen“ oben); ist das
        Nachholen aus, sagt `rueckfall: kanal` dem Agenten, dass er einen anderen Weg (Chat, Mail) nehmen muss."""
        t = text(titel, 80)
        if not t:
            raise ValueError("titel fehlt (ein kurzer Satz, worum es geht)")
        d = "normal" if dringlichkeit is None else dringlichkeit
        if d not in DRINGLICHKEITEN:
            raise ValueError("dringlichkeit ist niedrig, normal oder hoch")
        z = self.ziel_normalisiert(ziel) if ziel not in (None, "") else "agent"
        if eingabe is not None and not isinstance(eingabe, dict):
            raise ValueError("eingabe muss ein Objekt sein (die Argumente der App)")
        if (
            eingabe is not None
            and len(json.dumps(eingabe, ensure_ascii=False)) > ARGUMENTE_MAX_BYTES
        ):
            raise ValueError("eingabe ist zu groß (über 16 KB)")
        eingabe, gekappt = eingabe_kappen(eingabe)
        q = text(quelle, 40) or None
        vorschau = text(inhalt, 300) or None
        link = deeplink(z, eingabe or None, self.basis_url)
        zeigt: dict[str, Any] = {
            "ziel": z,
            "app": z[4:] if z.startswith("app:") else None,
            "titel": t,
            "untertitel": q,
            "symbol": None,
            "ton": None,
            "vorschau": vorschau,
            "eingabe": eingabe or None,
            "link": link,
            "art": "mitteilung",
            "dringlichkeit": d,
        }
        s = self.anwesend()
        if s is None:
            kanal: dict[str, Any] | None = None
            if d == "hoch":
                kanal = self._ueber_kanal(zeigt)
                if kanal is not None and ("zugestellt" in kanal):
                    return kanal  # im Chat angekommen (oder dort schon vor kurzem): nichts mehr vormerken
            ergebnis = self._vormerken(zeigt, von, link, gekappt)
            if kanal:
                ergebnis.update(kanal)
                ergebnis["satz"] += " Der Weg in den Chat-Kanal hat nicht geklappt."
            return ergebnis
        sid = s["sitzung"]
        geraet = s.get("geraet") or "dem Gerät"
        r = self._r()
        if not r.set(
            SCHL_ZEIGT + sid + ":" + _schluessel_hash("mitteilung", t, vorschau),
            "1",
            ex=AGENT_ZEIGT_DEDUPE_S,
            nx=True,
        ):
            return {
                "zugestellt": False,
                "grund": "doppelt",
                "sitzung": sid,
                "geraet": geraet,
                "satz": f"Dieselbe Mitteilung stand vor weniger als 10 min schon auf {geraet}.",
            }
        n = r.incr(SCHL_RATE + sid)
        if n == 1:
            r.expire(SCHL_RATE + sid, AGENT_ZEIGT_RATE_S)
        if n > AGENT_ZEIGT_RATE_MAX and d != "hoch":
            return {
                "zugestellt": False,
                "grund": "zu_viele",
                "rueckfall": "gebuendelt",
                "sitzung": sid,
                "geraet": geraet,
                "satz": f"Auf {geraet} standen in 10 min schon {AGENT_ZEIGT_RATE_MAX} Mitteilungen. "
                "Heb es für später auf.",
            }
        wirksam = audio_wirksam(s.get("audio"))
        aus = ausgabe_fuer(wirksam, d)
        zeigt["audio"] = {"modus": wirksam, **aus}
        self.senden(sid, {"id": neue_befehls_id(), "art": "zeigt", "zeigt": zeigt, "von": von})
        wie = (
            "vorgelesen" if aus["sprechen"] else ("mit Hinweiston" if aus["klang"] else "ohne Ton")
        )
        return {
            "zugestellt": True,
            "sitzung": sid,
            "geraet": geraet,
            "audio": wirksam,
            "klang": aus["klang"],
            "sprechen": aus["sprechen"],
            "satz": f"Auf {geraet} eingeblendet, {wie} (Ton-Modus {wirksam})."
            + (EINGABE_GEKAPPT if gekappt else ""),
            **({"eingabe_weggelassen": True} if gekappt else {}),
        }

    def _nachholen_fuer(self, sitzung: str) -> int:
        """Nachholen für eine gemeldete Sitzung (beim Verbindungsaufbau des Stroms)."""
        gespeichert = _json_laden(self._r().get(SCHL_SITZUNG + sitzung))
        if not isinstance(gespeichert, dict):
            return 0
        return self.nachholen(gespeichert)

    # ── Strom (SSE) ─────────────────────────────────────────────────────────────────────────
    async def strom(
        self, client: Any, sitzung: str, nach: str | None = None, bekannt: bool = True
    ) -> AsyncIterator[str]:
        """Server-Sent Events für eine Sitzung. Der Aufrufer besitzt und schließt `client`."""
        schluessel = SCHL_BEFEHLE + sitzung
        erstverbindung = nach is None
        letzte = nach or "0-0"
        beginn = time.monotonic()
        lesen_ms = max(1, int(min(PING_S, STROM_LESEN_S) * 1000))
        letzter_ping = time.monotonic()
        yield "retry: 3000\n\n"
        yield sse_ereignis(
            "hallo", {"sitzung": sitzung, "ablauf_s": SITZUNG_TTL_S, "bekannt": bekannt}
        )
        # Wer die Shell öffnet, bekommt sofort, was über Nacht vorgemerkt wurde (die Befehle liegen im Stream, den die
        # Schleife gleich liest). Ein Fehler hier stört den Strom nicht.
        if bekannt and self.nachholen_an:
            try:
                await asyncio.to_thread(self._nachholen_fuer, sitzung)
            except Exception as exc:  # noqa: BLE001
                logger.warning("os: Nachholen beim Strom %s: %s", sitzung, exc)
        # Endet nach STROM_MAX_S oder sobald der Server herunterfährt (HERUNTER) — dann endet die Antwort sauber,
        # der Browser verbindet sich mit Last-Event-ID beim nächsten Pod neu.
        while time.monotonic() - beginn < STROM_MAX_S and not HERUNTER.is_set():
            try:
                antwort = await client.xread({schluessel: letzte}, count=20, block=lesen_ms)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("os: Strom %s: %s", sitzung, exc)
                yield sse_ereignis("abbruch", {"grund": "redis"})
                return
            if not antwort:
                if time.monotonic() - letzter_ping >= PING_S:
                    letzter_ping = time.monotonic()
                    yield ": ping\n\n"
                continue
            for eid, felder in _eintraege(antwort):
                letzte = eid
                befehl = _json_laden(felder.get("d"))
                if not isinstance(befehl, dict):
                    continue
                try:
                    alter = max(0.0, self._zeit() - float(felder.get("t") or self._zeit()))
                except ValueError:
                    alter = 0.0
                if alter > BEFEHL_MAX_ALTER_S or (
                    erstverbindung and alter > ERSTVERBINDUNG_ALTER_S
                ):
                    continue
                befehl["alter_s"] = round(alter, 2)
                yield sse_ereignis("befehl", befehl, eid=eid)
                letzter_ping = time.monotonic()


# ── Herunterfahren ────────────────────────────────────────────────────────────────────────────
# Gesetzt, sobald der Server SIGTERM/SIGINT bekommt (`haken_herunterfahren`); die Ströme enden dann.
HERUNTER = threading.Event()


def haken_herunterfahren() -> bool:
    """uvicorn soll beim Beenden des Pods nicht auf offene Ströme warten.

    Der Server wartet beim Herunterfahren auf jede offene Antwort. Ein Strom, der bis zu 10 min läuft, hielte
    das Beenden bis zum SIGKILL von Kubernetes auf (nach 30 s, davon 5 s preStop): die Plugins räumten nie
    auf, und jede Auslieferung dauerte je Pod eine halbe Minute länger. Gemessen mit offenem Strom: 45 s nach
    SIGTERM kein Ende; ohne Strom 0,2 s. Wie sse-starlette ergänzen wir `Server.handle_exit` um ein Flag, das
    die Ströme lesen. Einmalig und idempotent; es muss vor `uvicorn.run` geschehen (`os_routen()` läuft beim
    Bauen der App). Liefert false, wenn uvicorn fehlt oder `handle_exit` anders aussieht.
    """
    try:
        from uvicorn.server import Server  # noqa: PLC0415 — nur im Betrieb nötig
    except ImportError:
        return False
    original = getattr(Server, "handle_exit", None)
    if not callable(original):
        logger.warning(
            "os: uvicorn.Server.handle_exit fehlt — offene Ströme halten das Beenden auf"
        )
        return False
    if getattr(original, "_os_bruecke_haken", False):
        return True

    def handle_exit(self: Any, *args: Any, **kwargs: Any) -> Any:
        HERUNTER.set()
        return original(self, *args, **kwargs)

    handle_exit._os_bruecke_haken = True  # type: ignore[attr-defined]
    Server.handle_exit = handle_exit  # type: ignore[method-assign]
    return True


def _json_laden(wert: Any) -> Any:
    if wert is None:
        return None
    try:
        return json.loads(wert)
    except (TypeError, ValueError):
        return None


def _vor(sekunden: float) -> str:
    s = max(0, int(sekunden))
    if s < 5:
        return "gerade eben"
    if s < 90:
        return f"vor {s} s"
    if s < 5400:
        return f"vor {round(s / 60)} min"
    return f"vor {round(s / 3600)} h"


def _lage_eintrag(
    s: dict[str, Any], jetzt: float, *, mit_schema: bool, flaechen: bool
) -> dict[str, Any]:
    bildschirme = s.get("bildschirme") or []
    aktiv = s.get("bildschirm", 0)
    name = next((b.get("name") for b in bildschirme if b.get("index") == aktiv), "") or (
        "Start" if aktiv == 0 else f"Bildschirm {aktiv}"
    )
    werkzeuge = []
    for w in s.get("werkzeuge", []):
        e = {
            "name": w["name"],
            "beschreibung": w.get("beschreibung", ""),
            "lesend": bool(w.get("lesend")),
        }
        if mit_schema and w.get("eingabe"):
            e["eingabe"] = w["eingabe"]
        werkzeuge.append(e)
    out: dict[str, Any] = {
        "sitzung": s["sitzung"],
        "geraet": s.get("geraet"),
        "art": s.get("art"),
        "zuletzt_aktiv_vor_s": max(0, int(jetzt - float(s.get("zuletzt_aktiv", jetzt)))),
        "gemeldet_vor_s": max(0, int(jetzt - float(s.get("gemeldet", jetzt)))),
        "sichtbar": bool(s.get("sichtbar")),
        "seite": s.get("seite"),
        "anruf_offen": bool(s.get("anruf")),
        "agent_vorne": bool(s.get("agent_vorne")),
        "bildschirm": {"index": aktiv, "name": name},
        "bildschirme": bildschirme,
        "fenster": [
            {
                "id": f["id"],
                "titel": f.get("titel"),
                "art": f.get("art"),
                "bildschirm": f.get("bildschirm"),
                "bildschirm_name": f.get("bildschirm_name"),
                "vorne": bool(f.get("vorne")),
                "minimiert": bool(f.get("min")),
            }
            for f in s.get("fenster", [])
        ],
        "werkzeuge": werkzeuge,
        "flaechen_anzahl": len(s.get("flaechen", [])),
        "audio": {**audio_bereinigen(s.get("audio")), "wirksam": audio_wirksam(s.get("audio"))},
    }
    if flaechen:
        out["flaechen"] = s.get("flaechen", [])
    return out


def _lage_satz(s: dict[str, Any] | None, jetzt: float, anzahl: int) -> str:
    if s is None:
        return "Die Shell ist gerade nirgends offen."
    sichtbar = [f for f in s.get("fenster", []) if not f.get("min")]
    namen = [
        (f.get("titel") or f["id"]) + (" (vorn)" if f.get("vorne") else "") for f in sichtbar[:6]
    ]
    satz = f"Die Shell ist auf {s.get('geraet')} offen, zuletzt benutzt {_vor(jetzt - float(s.get('zuletzt_aktiv', jetzt)))}"
    satz += f": {', '.join(namen)}." if namen else " — kein Fenster offen."
    if anzahl > 1:
        satz += f" Dazu {anzahl - 1} weitere Sitzung{'en' if anzahl > 2 else ''}."
    if s.get("anruf"):
        satz += " Ein Anruf läuft."
    return satz


# ── Standard-Instanz ─────────────────────────────────────────────────────────────────────────
_STANDARD: Bruecke | None = None


def standard(cfg: dict[str, Any] | None = None) -> Bruecke:
    global _STANDARD
    if _STANDARD is None:
        _STANDARD = Bruecke.aus_umgebung(cfg)
    return _STANDARD


def setze_standard(b: Bruecke | None) -> None:
    """Tests (und das Plugin mit eigener Config) setzen die Instanz."""
    global _STANDARD
    _STANDARD = b


# ── REST-Handler (an build_app() gehängt) ─────────────────────────────────────────────────────
def _fehler(status: int, nachricht: str, kind: str = "bad_request") -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "error": nachricht, "kind": kind})


async def _body_json(request: Request) -> tuple[Any, JSONResponse | None]:
    roh = await request.body()
    if len(roh) > MELDUNG_MAX_BYTES:
        return None, _fehler(413, "Anfrage zu groß", "zu_gross")
    try:
        return json.loads(roh or b"null"), None
    except ValueError:
        return None, _fehler(400, "ungültiges JSON")


async def rest_os_melden(request: Request) -> Response:
    """POST /hub/os/melden — Zustand einer OS-Sitzung (Fenster, Werkzeuge) für 90 s merken."""
    daten, fehler = await _body_json(request)
    if fehler is not None:
        return fehler
    try:
        return JSONResponse(await asyncio.to_thread(standard().melden, daten))
    except ValueError as exc:
        return _fehler(400, str(exc))
    except Exception as exc:  # noqa: BLE001 — Redis weg: ehrlich 503, der Browser versucht es später
        logger.warning("os: melden: %s", exc)
        return _fehler(503, "Redis nicht erreichbar", "redis")


async def rest_os_antwort(request: Request) -> Response:
    """POST /hub/os/antwort — das Ergebnis eines Befehls (zeigen / ausfuehren)."""
    daten, fehler = await _body_json(request)
    if fehler is not None:
        return fehler
    try:
        return JSONResponse(await asyncio.to_thread(standard().antwort_ablegen, daten))
    except ValueError as exc:
        return _fehler(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("os: antwort: %s", exc)
        return _fehler(503, "Redis nicht erreichbar", "redis")


async def _schliessen(client: Any) -> None:
    try:
        zu = getattr(client, "aclose", None) or client.close
        ergebnis = zu()
        if inspect.isawaitable(ergebnis):
            await ergebnis
    except Exception:  # noqa: BLE001
        pass


async def rest_os_strom(request: Request) -> Response:
    """GET /hub/os/strom?sitzung=&geraet= — Server-Sent Events mit den Befehlen für diese Sitzung."""
    try:
        sitzung = sitzung_pruefen(request.query_params.get("sitzung"))
    except ValueError as exc:
        return _fehler(400, str(exc))
    nach = (request.headers.get("last-event-id") or request.query_params.get("nach") or "").strip()
    if not STREAM_ID_MUSTER.match(nach):
        nach = ""
    b = standard()
    client = b.async_client()
    try:
        bekannt = bool(await client.exists(SCHL_SITZUNG + sitzung))
    except Exception as exc:  # noqa: BLE001
        await _schliessen(client)
        logger.warning("os: strom: %s", exc)
        return _fehler(503, "Redis nicht erreichbar", "redis")
    return StreamingResponse(
        b.strom(client, sitzung, nach or None, bekannt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx nicht puffern lassen
        },
        background=BackgroundTask(_schliessen, client),
    )


def os_routen() -> list[Route]:
    haken_herunterfahren()  # offene Ströme dürfen das Herunterfahren nicht aufhalten
    return [
        Route("/hub/os/strom", rest_os_strom, methods=["GET"]),
        Route("/hub/os/melden", rest_os_melden, methods=["POST"]),
        Route("/hub/os/antwort", rest_os_antwort, methods=["POST"]),
    ]
