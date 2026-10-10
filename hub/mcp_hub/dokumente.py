"""Dokumente für Plugins: eine Quelle, gleich ob Dokumenten-Dienst oder Plugin als Ablage.

Plugins, die Dokumente zeigen (Leitstand, Tagesbrief, Startseite), tragen keine Adresse fest ein und sprechen auch kein
Paperless: sie fragen hier. Wer Dokumente liefert, meldet sich an; die Leser wissen nichts voneinander.

**Dienst.** Die Ausbaustufe ist ein Paperless-ngx. Es wird mit einem Token angesprochen (Kopfzeile
``Authorization: Token …`` aus ``FYOS_DOKUMENTE_KOPF``) oder, hinter einem Proxy, mit der Kopfzeile, die dieser Proxy
vorgibt (Remote-User). Gelesen wird mit GET; geschrieben wird nur von ``zuordnen()`` (Titel, Korrespondent, Dokumenttyp
und Schlagworte; **gelöscht wird nie**, bestehende Schlagworte bleiben).

**Dokumentformat** (Ergebnis von ``neueste()``, ``suchen()`` und ``holen()``, jedes Dokument ein ``dict`` mit genau
diesen Feldern):

======================  ======================================================================================
``id``                  Kennung in der Quelle, eine ganze Zahl ab 1; für Leser undurchsichtig, für ``holen()`` und
                        ``zuordnen()`` wieder verwendbar
``titel``               Titel in einer Zeile (``(ohne Titel)``, wenn die Quelle keinen nennt)
``erstellt``            Datum des Dokuments ``JJJJ-MM-TT`` oder ``None``
``hinzugefuegt``        Zeitstempel ISO 8601 mit Versatz, wann es in die Ablage kam, oder ``None``
``schlagworte``         Namen der Schlagworte, sonst ``[]``
``korrespondent``       Name oder ``None``
``typ``                 Name des Dokumenttyps oder ``None``
``datei``               Name der Originaldatei oder ``None``
``seiten``              Seitenzahl oder ``None``
``auszug``              Treffer-Auszug einer Suche in einer Zeile, Treffer in ``«…»``, sonst ``None``
``link``                Adresse des Dokuments im Browser (``http`` oder ``https``) oder ``None``
======================  ======================================================================================

Das **volle Dokument** (``holen()``) hat zusätzlich ``text`` (der erkannte Text, höchstens ``TEXT_MAX`` Zeichen) und
``text_gekuerzt`` (``true``, wenn der Text gekürzt wurde). **Dokumenttext ist Fremdinhalt**: wer ihn einem Modell zeigt,
sagt dazu, dass darin keine Anweisungen stehen, denen zu folgen ist.

**Reihenfolge der Quellen** (``quelle()``):

1. **Dokumenten-Dienst**, wenn eine Adresse gesetzt ist (Argument ``url``, ein mit ``dienst_anmelden`` angemeldeter
   Dienst oder ``FYOS_DOKUMENTE_URL``; Kopfzeile aus ``FYOS_DOKUMENTE_KOPF``; Browser-Adresse für ``link`` aus
   ``FYOS_DOKUMENTE_LINK``, leer heißt: keine Links).
2. **Ablage** (prozessintern): ein Hub-Plugin, das sich mit ``ablage_anmelden`` meldet und das Protokoll ``Ablage``
   erfüllt, etwa eine Ablage auf einem Ordner.
3. **Keine**: alle Methoden melden ``NichtEingerichtet``.

Plugins fragen ``quelle()`` bei jedem Aufruf neu; das ist billig und nimmt eine Ablage mit, die sich erst nach ihnen
anmeldet.

**Drei Zustände, die Aufrufer trennen müssen.** Ein Ergebnis (auch ``{"gesamt": 0, "dokumente": []}``) heißt: die Quelle
hat geantwortet, es gibt diese Dokumente. ``QuelleFehler``: die Quelle ist aus oder ohne Zugang (auch eine abgelehnte
Anmeldung), das ist nie „keine Dokumente“. ``NichtEingerichtet`` (ein ``QuelleFehler``): es gibt gar keine Quelle. Wie
bei den Terminen und Mails liefert die Quelle „keine“ deshalb **keine leere Liste**, sondern wirft.

**Abfragesprache.** ``abfrage`` von ``suchen()`` ist ein Text von 2 bis ``ABFRAGE_MAX`` Zeichen; Wörter, durch Leerzeichen
getrennt, müssen im Titel, in den Schlagworten oder im erkannten Text vorkommen. Der Dienst reicht den Text unverändert an
die Volltextsuche von Paperless weiter (dort gelten auch Feldsuchen wie ``tag:rechnung``); eine Ablage wertet mindestens
die Wörter aus.

**Fehler.** ``QuelleFehler`` erbt von ``vorgaenge.QuelleFehler``, damit ein Aufrufer die Quellen mit einem ``except``
fängt (Text und ``status`` sind gleich gebaut). ``NichtEingerichtet`` erbt dagegen nur von ``dokumente.QuelleFehler``.
``ValueError`` bedeutet falsche Eingabe (eine zu kurze Abfrage, eine ungültige Kennung, eine Änderung ohne Inhalt). Die
Kopfzeile und das Token stehen nie in einer Meldung, einem Log oder einem Ergebnis.

**Umgebung** (bei jedem Aufruf gelesen):

* ``FYOS_DOKUMENTE_URL``   Adresse des Dokumenten-Dienstes (Paperless-ngx), nur Wurzel ohne ``/api``
* ``FYOS_DOKUMENTE_KOPF``  eine Kopfzeile für den Dienst, ``Name: Wert`` (geheim), etwa ``Authorization: Token …``
* ``FYOS_DOKUMENTE_LINK``  Adresse desselben Dienstes im Browser; leer = keine Links
"""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from mcp_hub import vorgaenge
from mcp_hub.postfach import datum_aus
from mcp_hub.vorgaenge import kopf_aus

_log = logging.getLogger(__name__)

FRIST_LESEN_S = 15.0
FRIST_SCHREIBEN_S = 20.0
#: Die Suche von Paperless liefert den ganzen erkannten Text jedes Treffers mit; deshalb großzügig
ANTWORT_MAX = 32 * 1024 * 1024
#: So viele Dokumente liefert ``neueste()`` und ``suchen()`` ohne Angabe, und so viele höchstens
ANZAHL_STANDARD = 10
ANZAHL_MAX = 50
ABFRAGE_MIN = 2
ABFRAGE_MAX = 300
TITEL_MAX = 300
NAME_MAX = 100
DATEI_MAX = 300
AUSZUG_MAX = 400
SCHLAGWORTE_MAX = 30
#: So viele Schlagworte kann ``zuordnen()`` auf einmal hinzufügen
HINZU_MAX = 8
TEXT_MAX = 20_000
OHNE_TITEL = "(ohne Titel)"
#: Wie lange der Dienst Namen von Schlagworten, Korrespondenten und Typen im Speicher hält (Sekunden)
NAMEN_FRIST_S = 300.0
_NAMEN_SEITE = 1000
_NAMEN_SEITEN_MAX = 5
_FELDER = "id,title,created,added,tags,correspondent,document_type,original_file_name,page_count"
_ARTEN = ("tags", "correspondents", "document_types")
_ARTEN_NAME = {"tags": "Schlagwort", "correspondents": "Korrespondent", "document_types": "Typ"}
_AENDERUNG_FELDER = ("titel", "korrespondent", "typ", "schlagworte_hinzu")


class QuelleFehler(vorgaenge.QuelleFehler):
    """Die Quelle der Dokumente antwortet nicht wie vereinbart: aus, ohne Zugang, Netz, unerwarteter Status."""


class NichtEingerichtet(QuelleFehler):
    """Es gibt keine Quelle für Dokumente (kein Dokumenten-Dienst, keine Ablage)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text or (
            "Keine Dokumentenablage eingerichtet: FYOS_DOKUMENTE_URL auf die Adresse eines Paperless-ngx setzen und in "
            "FYOS_DOKUMENTE_KOPF das Token angeben (Authorization: Token …)."
        ), 501)


class Ablage(Protocol):
    """Was ein Plugin anbietet, das sich als Quelle anmeldet (Daten statt HTTP).

    Die vier ersten Methoden sind Pflicht. ``ablage_namen`` und ``ablage_zuordnen`` sind optional: fehlt eine, meldet die
    Quelle „kann diese Ablage nicht“ (Status 501), statt zu raten. Dokumente sind ``dict`` im Dokumentformat; was fehlt,
    ergänzt der Kern."""

    def ablage_neueste(self, anzahl: int) -> dict[str, Any]:
        """Die zuletzt hinzugefügten Dokumente, neueste zuerst, höchstens ``anzahl``:
        ``{"gesamt": <Zahl aller Dokumente>, "dokumente": [<Dokument>]}``. Ein Dokument hat mindestens ``id``."""
        ...

    def ablage_suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        """Dokumente zur Abfrage (mindestens zwei Zeichen), die besten zuerst, höchstens ``anzahl``:
        ``{"gesamt": <Zahl der Treffer>, "dokumente": [...]}``."""
        ...

    def ablage_holen(self, id: int) -> dict[str, Any]:  # noqa: A002 — Name der Spalte im Dokumentformat
        """Ein Dokument im Dokumentformat mit ``text`` (der Kern kürzt). ``id`` stammt aus einer Liste."""
        ...

    def ablage_unsortiert(self) -> int | None:
        """Wie viele Dokumente weder Korrespondent noch Typ haben, oder ``None``, wenn die Ablage das nicht zählt."""
        ...

    # Optional:
    #   def ablage_namen(self) -> dict[str, list[str]]:
    #       """Die vorhandenen Namen: ``{"schlagworte": [...], "korrespondenten": [...], "typen": [...]}``."""
    #   def ablage_zuordnen(self, id: int, aenderung: dict[str, Any], vorschau: bool) -> dict[str, Any]:
    #       """Setzt Titel, Korrespondent, Typ und fügt Schlagworte hinzu (``aenderung`` ist geprüft: ``titel``,
    #       ``korrespondent``, ``typ``, ``schlagworte_hinzu``); mit ``vorschau`` ändert sie nichts. Antwort wie bei
    #       ``Quelle.zuordnen``: ``vorher`` und, ohne Vorschau, ``nachher`` als Dokumente, dazu ``aendert`` und
    #       ``wird_angelegt`` (Vorschau) oder ``angelegt``."""


_sperre = threading.Lock()
_ablage: Ablage | None = None
_dienst: tuple[str, dict[str, str], str] | None = None
_namen_stand: dict[str, tuple[float, dict[str, dict[int, str]]]] = {}


def ablage_anmelden(ablage: Ablage | None) -> None:
    """Ein Plugin meldet sich als Quelle an; ``None`` meldet ab."""
    global _ablage
    with _sperre:
        _ablage = ablage


def angemeldete_ablage() -> Ablage | None:
    with _sperre:
        return _ablage


def dienst_anmelden(url: str | None, kopf: dict[str, str] | None = None, link: str | None = None) -> None:
    """Ein Plugin meldet einen Dokumenten-Dienst an (Adresse, Kopfzeile, Browser-Adresse); so fragen alle Plugins
    denselben Dienst. ``None`` meldet ab."""
    global _dienst
    with _sperre:
        _dienst = (url.strip().rstrip("/"), dict(kopf or {}), (link or "").strip()) if url and url.strip() else None


def angemeldeter_dienst() -> tuple[str, dict[str, str], str] | None:
    """``(Adresse, Kopfzeile, Browser-Adresse)`` des angemeldeten Dienstes oder ``None``."""
    with _sperre:
        return _dienst


def namen_vergessen() -> None:
    """Wirft die gemerkten Namen aller Dienste weg (die nächste Frage liest sie neu)."""
    with _sperre:
        _namen_stand.clear()


# ── Text und Dokumentformat ─────────────────────────────────────────────────────────────────────────────
_STEUERZEICHEN = {c: None for c in (*range(32), 127)}
_NUR_TEXT = {c: None for c in (*range(32), 127) if c not in (9, 10)}
_TAG = re.compile(r"\d{4}-\d{2}-\d{2}")
#: Ein Treffer ist kurz; die Grenze hält die Suche linear, auch bei bösartigem Eingang
_TREFFER = re.compile(r'<(?:b|span class="match[^"]{0,40}")>(.{0,600}?)</(?:b|span)>', re.DOTALL)
#: So viel vom Auszug wird überhaupt angesehen
_AUSZUG_ROH_MAX = 4000
_ETIKETT = re.compile(r"<[^<>]{0,200}>")


def _zeile(wert: Any, grenze: int | None = None) -> str:
    """Ein Wert als eine Zeile: Leerraum zusammengezogen, Steuerzeichen entfernt, auf ``grenze`` Zeichen gekürzt."""
    text = " ".join(str(wert).split()).translate(_STEUERZEICHEN) if wert is not None else ""
    return text[:grenze] if grenze else text


def _kurz(text: str, grenze: int) -> str:
    return text if len(text) <= grenze else text[: grenze - 1].rstrip() + "…"


def _zaehler(wert: Any) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and wert >= 0 else None


def _id_aus(wert: Any) -> int | None:
    """Eine Kennung (ganze Zahl ab 1, auch als Ziffernfolge) oder ``None``."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, int):
        return wert if 1 <= wert < 10**12 else None
    if isinstance(wert, str) and wert.isascii() and wert.isdigit() and len(wert) <= 12:
        return _id_aus(int(wert))
    return None


def auszug_aus(roh: Any) -> str | None:
    """Der Treffer-Auszug von Paperless als eine Zeile: Treffer (``<b>…</b>``, früher ``<span class="match">…</span>``)
    stehen in ``«…»``, sonstiges HTML fällt weg. ``None``, wenn nichts da ist."""
    if not isinstance(roh, str) or not roh.strip():
        return None
    text = _TREFFER.sub(lambda m: "«" + m.group(1) + "»", roh[:_AUSZUG_ROH_MAX])
    text = html.unescape(_ETIKETT.sub("", text))
    return _kurz(_zeile(text), AUSZUG_MAX) or None


def _link(wert: Any) -> str | None:
    text = _zeile(wert, 500)
    return text if re.match(r"https?://[^\s/]+", text, re.IGNORECASE) else None


def _namen_liste(roh: Any, grenze: int = NAME_MAX) -> list[str]:
    namen: list[str] = []
    for eintrag in roh if isinstance(roh, (list, tuple)) else ():
        name = _zeile(eintrag, grenze) if isinstance(eintrag, (str, int)) and not isinstance(eintrag, bool) else ""
        if name and name not in namen:
            namen.append(name)
        if len(namen) >= SCHLAGWORTE_MAX:
            break
    return namen


def dokument_aus(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Bringt ein Dokument in das Dokumentformat (Kopf); ``None``, wenn es keine brauchbare Kennung hat (dann ließe es
    sich nicht lesen). Fehlende Felder werden ergänzt, Zeiten und Texte vereinheitlicht."""
    kennung = _id_aus(roh.get("id"))
    if kennung is None:
        return None
    erstellt = _zeile(roh.get("erstellt"), 40)
    return {
        "id": kennung,
        "titel": _zeile(roh.get("titel"), TITEL_MAX) or OHNE_TITEL,
        "erstellt": erstellt[:10] if _TAG.match(erstellt) else None,
        "hinzugefuegt": datum_aus(roh.get("hinzugefuegt")) or None,
        "schlagworte": _namen_liste(roh.get("schlagworte")),
        "korrespondent": _zeile(roh.get("korrespondent"), NAME_MAX) or None,
        "typ": _zeile(roh.get("typ"), NAME_MAX) or None,
        "datei": _zeile(roh.get("datei"), DATEI_MAX) or None,
        "seiten": _zaehler(roh.get("seiten")),
        "auszug": _kurz(_zeile(roh.get("auszug")), AUSZUG_MAX) or None,
        "link": _link(roh.get("link")),
    }


def dokument_voll_aus(roh: dict[str, Any], kennung: int) -> dict[str, Any]:
    """Bringt ein Dokument in das Dokumentformat samt ``text`` und ``text_gekuerzt``. Die Kennung ist die angefragte
    (schon geprüft), auch wenn die Quelle eine andere nennt."""
    kopf = dokument_aus({**roh, "id": kennung})
    if kopf is None:  # ``kennung`` ist geprüft; nur zur Sicherheit
        raise QuelleFehler("Die Quelle hat das Dokument nicht lesbar geliefert.")
    text = str(roh.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").translate(_NUR_TEXT).strip()
    return {**kopf, "text": text[:TEXT_MAX], "text_gekuerzt": bool(roh.get("text_gekuerzt")) or len(text) > TEXT_MAX}


# ── Eingaben ────────────────────────────────────────────────────────────────────────────────────────────
def _abfrage(wert: Any) -> str:
    if not isinstance(wert, str):
        raise ValueError("abfrage muss ein Text sein")
    text = _zeile(wert)
    if len(text) < ABFRAGE_MIN:
        raise ValueError(f"abfrage braucht mindestens {ABFRAGE_MIN} Zeichen")
    if len(text) > ABFRAGE_MAX:
        raise ValueError(f"abfrage ist länger als {ABFRAGE_MAX} Zeichen")
    return text


def _anzahl(wert: Any) -> int:
    if isinstance(wert, bool) or not isinstance(wert, (int, str)):
        raise ValueError("anzahl muss eine ganze Zahl sein")
    try:
        n = int(wert)
    except ValueError:
        raise ValueError("anzahl muss eine ganze Zahl sein") from None
    if not 1 <= n <= ANZAHL_MAX:
        raise ValueError(f"anzahl muss zwischen 1 und {ANZAHL_MAX} liegen")
    return n


def _kennung(wert: Any) -> int:
    kennung = _id_aus(wert)
    if kennung is None:
        raise ValueError("id ist keine gültige Dokument-Kennung (eine ganze Zahl ab 1 aus einer Dokumentliste)")
    return kennung


def _name(wert: Any, feld: str, grenze: int) -> str:
    if not isinstance(wert, str):
        raise ValueError(f"{feld} muss ein Text sein")
    text = _zeile(wert)
    if len(text) < 2:
        raise ValueError(f"{feld} braucht mindestens 2 Zeichen")
    if len(text) > grenze:
        raise ValueError(f"{feld} ist länger als {grenze} Zeichen")
    return text


def pruefe_aenderung(wert: Any) -> dict[str, Any]:
    """Prüft die Änderung für ``zuordnen()``: ``titel``, ``korrespondent``, ``typ`` (Texte) und ``schlagworte_hinzu``
    (Liste von höchstens ``HINZU_MAX`` Namen). Mindestens ein Feld; Unbekanntes und Leeres ist ein ``ValueError``.
    Liefert die bereinigte Änderung."""
    if not isinstance(wert, dict):
        raise ValueError("aenderung muss ein Objekt sein")
    fremd = sorted(str(k) for k in wert if k not in _AENDERUNG_FELDER)
    if fremd:
        raise ValueError(f"unbekannte Felder in aenderung: {', '.join(fremd)} (erlaubt: {', '.join(_AENDERUNG_FELDER)})")
    aus: dict[str, Any] = {}
    if wert.get("titel") is not None:
        aus["titel"] = _name(wert["titel"], "titel", TITEL_MAX)
    if wert.get("korrespondent") is not None:
        aus["korrespondent"] = _name(wert["korrespondent"], "korrespondent", NAME_MAX)
    if wert.get("typ") is not None:
        aus["typ"] = _name(wert["typ"], "typ", NAME_MAX)
    if wert.get("schlagworte_hinzu") is not None:
        roh = wert["schlagworte_hinzu"]
        if not isinstance(roh, list) or len(roh) > HINZU_MAX:
            raise ValueError(f"schlagworte_hinzu muss eine Liste mit höchstens {HINZU_MAX} Namen sein")
        namen: list[str] = []
        for eintrag in roh:
            name = _name(eintrag, "schlagwort", 60)
            if name.casefold() not in {n.casefold() for n in namen}:
                namen.append(name)
        if namen:
            aus["schlagworte_hinzu"] = namen
    if not aus:
        raise ValueError("nichts zu ändern: titel, korrespondent, typ oder schlagworte_hinzu angeben")
    return aus


# ── Quellen ─────────────────────────────────────────────────────────────────────────────────────────────
class Quelle:
    """Gemeinsame Form aller Quellen. ``art``: dienst | ablage | keine. Diese Grundform ist die Quelle „keine“."""

    art = "keine"

    @property
    def eingerichtet(self) -> bool:
        return self.art != "keine"

    def beschreibung(self) -> str:
        return "keine Dokumentenablage eingerichtet"

    def neueste(self, anzahl: Any = ANZAHL_STANDARD) -> dict[str, Any]:
        """Die zuletzt hinzugefügten Dokumente, neueste zuerst, höchstens ``anzahl`` (1 bis ``ANZAHL_MAX``):
        ``{"gesamt": <Zahl aller Dokumente>, "dokumente": [...]}``. Die Antwort „keine Dokumente“ ist die leere Liste;
        ist die Quelle aus oder ohne Zugang, wirft der Aufruf ``QuelleFehler``."""
        n = _anzahl(anzahl)
        return self._liste_aus(self._neueste(n), n)

    def suchen(self, abfrage: Any, anzahl: Any = ANZAHL_STANDARD) -> dict[str, Any]:
        """Dokumente zur Abfrage (siehe Modul-Doku), die besten zuerst, höchstens ``anzahl``:
        ``{"gesamt": <Zahl der Treffer>, "dokumente": [...]}``; ``auszug`` zeigt den Treffer, wenn die Quelle ihn nennt."""
        q, n = _abfrage(abfrage), _anzahl(anzahl)
        return self._liste_aus(self._suchen(q, n), n)

    def holen(self, id: Any) -> dict[str, Any]:  # noqa: A002 — Name der Spalte im Dokumentformat
        """Ein Dokument im Dokumentformat samt ``text`` und ``text_gekuerzt``. ``id`` stammt aus einer Liste."""
        kennung = _kennung(id)
        return dokument_voll_aus(self._holen(kennung), kennung)

    def unsortiert(self) -> int | None:
        """Wie viele Dokumente weder Korrespondent noch Typ haben, über alle Dokumente; ``None``, wenn die Quelle das
        nicht zählt oder der Zähler ausfällt (die Listen bleiben gültig)."""
        return _zaehler(self._unsortiert())

    def namen(self) -> dict[str, list[str]]:
        """Die vorhandenen Namen, sortiert: ``{"schlagworte": [...], "korrespondenten": [...], "typen": [...]}``."""
        roh = self._namen()
        if not isinstance(roh, dict):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Namen.")
        return {
            feld: sorted(_namen_liste(roh.get(feld), NAME_MAX), key=str.casefold)
            for feld in ("schlagworte", "korrespondenten", "typen")
        }

    def zuordnen(self, id: Any, aenderung: Any, vorschau: Any = False) -> dict[str, Any]:  # noqa: A002
        """Setzt Titel, Korrespondent und Typ und fügt Schlagworte hinzu (``aenderung``: siehe ``pruefe_aenderung``).
        Gelöscht wird nichts, bestehende Schlagworte bleiben, fehlende Korrespondenten, Typen und Schlagworte werden
        angelegt. Mit ``vorschau`` ändert der Aufruf nichts und sagt, was geschehen würde.

        Antwort mit Vorschau: ``{"vorschau": True, "id", "vorher": <Dokument>, "aendert": {…}, "wird_angelegt": ["Typ X"]}``;
        ohne: ``{"vorschau": False, "id", "vorher", "nachher": <Dokument>, "angelegt": [...]}``."""
        kennung, a, nur = _kennung(id), pruefe_aenderung(aenderung), bool(vorschau)
        return self._zuordnung_aus(self._zuordnen(kennung, a, nur), kennung, nur)

    def als_dict(self) -> dict[str, Any]:
        return {"art": self.art, "eingerichtet": self.eingerichtet, "beschreibung": self.beschreibung()}

    # Von der Quelle zu füllen --------------------------------------------------------------------------
    def _neueste(self, anzahl: int) -> dict[str, Any]:
        raise NichtEingerichtet()

    def _suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        raise NichtEingerichtet()

    def _holen(self, kennung: int) -> dict[str, Any]:
        raise NichtEingerichtet()

    def _unsortiert(self) -> Any:
        raise NichtEingerichtet()

    def _namen(self) -> Any:
        raise NichtEingerichtet()

    def _zuordnen(self, kennung: int, aenderung: dict[str, Any], vorschau: bool) -> Any:
        raise NichtEingerichtet()

    # Gemeinsame Abbildung -------------------------------------------------------------------------------
    def _liste_aus(self, roh: Any, n: int) -> dict[str, Any]:
        if not isinstance(roh, dict) or not isinstance(roh.get("dokumente"), list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Dokumentliste.")
        dokumente = [d for d in (dokument_aus(x) if isinstance(x, dict) else None for x in roh["dokumente"]) if d]
        if len(dokumente) < len(roh["dokumente"]):
            _log.warning("%s: %d Einträge ohne brauchbare Kennung übersprungen", self.beschreibung(),
                         len(roh["dokumente"]) - len(dokumente))
        dokumente = dokumente[:n]
        gesamt = _zaehler(roh.get("gesamt"))
        return {"gesamt": max(gesamt, len(dokumente)) if gesamt is not None else len(dokumente), "dokumente": dokumente}

    def _zuordnung_aus(self, roh: Any, kennung: int, vorschau: bool) -> dict[str, Any]:
        if not isinstance(roh, dict):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort auf das Zuordnen ist nicht lesbar.")

        def dok(wert: Any) -> dict[str, Any] | None:
            return dokument_aus(wert) if isinstance(wert, dict) else None

        aus: dict[str, Any] = {"vorschau": vorschau, "id": kennung, "vorher": dok(roh.get("vorher"))}
        listen = (("wird_angelegt",) if vorschau else ("angelegt",))
        if vorschau:
            roh_aendert = roh.get("aendert") if isinstance(roh.get("aendert"), dict) else {}
            aus["aendert"] = {k: v for k, v in roh_aendert.items() if k in _AENDERUNG_FELDER}
        else:
            aus["nachher"] = dok(roh.get("nachher"))
        for name in listen:
            aus[name] = [_zeile(x, 120) for x in roh.get(name) or [] if isinstance(x, str)][:40]
        return aus


class AblageQuelle(Quelle):
    """Ein Plugin als Quelle (prozessintern)."""

    art = "ablage"

    def __init__(self, ablage: Ablage) -> None:
        self.ablage = ablage

    def beschreibung(self) -> str:
        name = _zeile(getattr(self.ablage, "name", ""), 60)
        return f"Dokumenten-Ablage {name}" if name else "Dokumenten-Ablage"

    @staticmethod
    def _rufe(fn: Any) -> Any:
        try:
            return fn()
        except (QuelleFehler, ValueError):
            raise
        except vorgaenge.QuelleFehler as exc:  # ein Plugin mit der Fehlerklasse der Vorgänge
            raise QuelleFehler(str(exc), exc.status) from exc
        except NotImplementedError as exc:
            raise QuelleFehler("Die Dokumenten-Ablage kann das nicht.", 501) from exc
        except Exception as exc:  # noqa: BLE001 — Plugin-Fehler; nur der Typ geht an die Leser, nie der Text
            _log.warning("Dokumenten-Ablage: unerwarteter Fehler (%s)", type(exc).__name__,
                         exc_info=_log.isEnabledFor(logging.DEBUG))
            raise QuelleFehler(f"Die Dokumenten-Ablage meldet einen Fehler ({type(exc).__name__}).") from exc

    def _optional(self, name: str) -> Any:
        fn = getattr(self.ablage, name, None)
        if not callable(fn):
            raise QuelleFehler(f"{self.beschreibung()} kann das nicht ({name} fehlt).", 501)
        return fn

    def _neueste(self, anzahl: int) -> dict[str, Any]:
        return self._rufe(lambda: self.ablage.ablage_neueste(anzahl))

    def _suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        return self._rufe(lambda: self.ablage.ablage_suchen(abfrage, anzahl))

    def _holen(self, kennung: int) -> dict[str, Any]:
        roh = self._rufe(lambda: self.ablage.ablage_holen(kennung))
        if not isinstance(roh, dict):
            raise QuelleFehler(f"{self.beschreibung()} hat das Dokument nicht geliefert.")
        return roh

    def _unsortiert(self) -> Any:
        try:
            return self._rufe(self.ablage.ablage_unsortiert)
        except QuelleFehler as e:  # ohne Zähler bleiben die Listen gültig
            _log.info("%s: kein Zähler (%s)", self.beschreibung(), e)
            return None

    def _namen(self) -> Any:
        fn = self._optional("ablage_namen")
        return self._rufe(fn)

    def _zuordnen(self, kennung: int, aenderung: dict[str, Any], vorschau: bool) -> Any:
        fn = self._optional("ablage_zuordnen")
        return self._rufe(lambda: fn(kennung, dict(aenderung), vorschau))


class _KeineUmleitung(urllib.request.HTTPRedirectHandler):
    """Folgt keiner Umleitung: die Kopfzeile des Dienstes geht an die eingetragene Adresse und an keine andere."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_OFFEN = urllib.request.build_opener(_KeineUmleitung)


def _netzfehler(e: BaseException) -> str:
    ursache = e.reason if isinstance(e, urllib.error.URLError) and isinstance(e.reason, BaseException) else e
    if isinstance(ursache, TimeoutError):
        return "Zeitüberschreitung"
    if isinstance(ursache, ConnectionRefusedError):
        return "Verbindung abgelehnt"
    if isinstance(ursache, socket.gaierror):
        return "Name nicht aufgelöst"
    if isinstance(ursache, ssl.SSLError):
        return "TLS-Fehler"
    return type(ursache).__name__


def _grund(d: Any, status: int) -> str:
    if isinstance(d, dict):
        for k in ("detail", "error", "fehler", "hinweis", "_message"):
            if isinstance(d.get(k), str) and d[k]:
                return _zeile(d[k], 300)
    return f"HTTP {status}"


class Dienst(Quelle):
    """Paperless-ngx per HTTP unter ``url``. Gelesen wird mit GET, geschrieben nur von ``zuordnen()`` (POST für fehlende
    Korrespondenten, Typen und Schlagworte, PATCH für das Dokument). Gebraucht werden diese Routen:

    * ``GET /api/documents/?ordering=-added&page_size=N&fields=…`` und ``GET /api/documents/?query=<Text>&page_size=N``
      liefern ``{"count": N, "results": [{id, title, created, added, tags, correspondent, document_type,
      original_file_name, page_count, __search_hit__: {highlights}}]}``. ``created`` darf ein Datum oder ein Zeitstempel
      sein, die Markierung der Treffer ``<b>`` oder ``<span class="match">``.
    * ``GET /api/documents/<id>/`` liefert dasselbe Dokument mit ``content`` (dem erkannten Text).
    * ``GET /api/documents/?correspondent__isnull=1&document_type__isnull=1&page_size=1&fields=id`` zählt die
      unsortierten Dokumente (``count``). Fällt der Zähler aus, bleibt die Liste gültig.
    * ``GET /api/tags/``, ``/api/correspondents/`` und ``/api/document_types/`` (``page_size=1000``) liefern die Namen zu
      den Kennungen; der Kern merkt sie ``NAMEN_FRIST_S`` Sekunden.
    * ``PATCH /api/documents/<id>/`` und ``POST /api/tags/`` (``correspondents``, ``document_types``) mit ``{"name": …}``.

    Umleitungen werden nicht verfolgt (die Kopfzeile geht nur an die eingetragene Adresse)."""

    art = "dienst"

    def __init__(self, url: str, kopf: dict[str, str] | None = None, aufruf: Any = None, link: str = "") -> None:
        self.url = url.rstrip("/")
        self.kopf = dict(kopf or {})
        self.link = _link(link.strip().rstrip("/")) if isinstance(link, str) else None
        self._aufruf = aufruf

    def _host(self) -> str:
        try:
            teile = urllib.parse.urlsplit(self.url)
            host, port = teile.hostname, teile.port
        except ValueError:
            return ""
        if not host:
            return ""
        if ":" in host:  # IPv6
            host = f"[{host}]"
        return f"{host}:{port}" if port else host

    def beschreibung(self) -> str:
        host = self._host()
        return f"Paperless {host}" if host else "Paperless"

    def roh(self, pfad: str, frist: float | None = None, methode: str = "GET", koerper: Any = None) -> tuple[int, Any]:
        """(Status, JSON) vom Dienst; Fehlerstatus kommen als Wert, ein unlesbarer Rumpf als ``None``. Ist der Dienst nicht
        erreichbar, wirft der Aufruf ``QuelleFehler``. ``frist`` in Sekunden (ohne Angabe ``FRIST_LESEN_S``, beim
        Schreiben ``FRIST_SCHREIBEN_S``). Geschrieben wird nur mit POST und PATCH."""
        if methode not in ("GET", "POST", "PATCH"):
            raise ValueError(f"Methode {methode} gibt es hier nicht")
        frist = (FRIST_LESEN_S if methode == "GET" else FRIST_SCHREIBEN_S) if frist is None else frist
        if self._aufruf is not None:
            return self._aufruf(pfad, frist, methode, koerper)
        kopf = {"Accept": "application/json", "User-Agent": "fyos-hub", **self.kopf}
        daten = None
        if koerper is not None:
            daten = json.dumps(koerper).encode()
            kopf["Content-Type"] = "application/json"
        try:
            req = urllib.request.Request(self.url + pfad, data=daten, method=methode, headers=kopf)
        except ValueError:
            raise QuelleFehler(f"{self.beschreibung()}: die Adresse ist keine gültige URL (http:// oder https://).") from None
        try:
            with _OFFEN.open(req, timeout=frist) as r:  # noqa: S310 — Adresse aus der Konfiguration
                roh, status = r.read(ANTWORT_MAX + 1), r.status
        except urllib.error.HTTPError as e:
            roh, status = (e.read(65536) if e.fp else b""), e.code
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            raise QuelleFehler(f"{self.beschreibung()} nicht erreichbar ({_netzfehler(e)}).") from e
        if len(roh) > ANTWORT_MAX:
            raise QuelleFehler(f"{self.beschreibung()}: die Antwort ist zu groß.")
        try:
            return status, json.loads(roh.decode() or "{}")
        except ValueError:
            return status, None

    def _antwort(self, status: int, d: Any) -> dict[str, Any]:
        """Die Antwort als Objekt oder ein ``QuelleFehler`` mit dem Grund."""
        if status in (401, 403):
            raise QuelleFehler(
                f"{self.beschreibung()} lehnt die Anmeldung ab (Token prüfen: FYOS_DOKUMENTE_KOPF).", status)
        if 300 <= status < 400:
            raise QuelleFehler(
                f"{self.beschreibung()} antwortet mit {status} (Umleitungen werden nicht verfolgt; Adresse prüfen).", status)
        if status >= 400:
            raise QuelleFehler(f"{self.beschreibung()} antwortet mit {status}: {_grund(d, status)}", status)
        if not isinstance(d, dict):
            raise QuelleFehler(f"{self.beschreibung()} antwortet nicht mit lesbaren Daten.")
        return d

    # Namen -----------------------------------------------------------------------------------------------
    def _schluessel(self) -> str:
        """Unter diesem Schlüssel merkt der Kern die Namen: Adresse und Kopfzeile, ohne die Kopfzeile preiszugeben."""
        roh = json.dumps([self.url, sorted(self.kopf.items())]).encode()
        return hashlib.sha256(roh).hexdigest()

    def _namen_lesen(self) -> dict[str, dict[int, str]]:
        karte: dict[str, dict[int, str]] = {}
        for art in _ARTEN:
            eintraege: dict[int, str] = {}
            for seite in range(1, _NAMEN_SEITEN_MAX + 1):
                d = self._antwort(*self.roh(f"/api/{art}/?page_size={_NAMEN_SEITE}&page={seite}"))
                ergebnisse = d.get("results")
                if not isinstance(ergebnisse, list):
                    raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Namensliste ({art}).")
                for x in ergebnisse:
                    kennung = _id_aus(x.get("id")) if isinstance(x, dict) else None
                    if kennung is not None and isinstance(x.get("name"), str):
                        eintraege[kennung] = _zeile(x["name"], NAME_MAX)
                if not d.get("next"):
                    break
            karte[art] = eintraege
        return karte

    def _karte(self, frisch: bool = False) -> dict[str, dict[int, str]]:
        schluessel = self._schluessel()
        with _sperre:
            gemerkt = None if frisch else _namen_stand.get(schluessel)
        if gemerkt is not None and time.monotonic() - gemerkt[0] < NAMEN_FRIST_S:
            return gemerkt[1]
        karte = self._namen_lesen()
        with _sperre:
            if len(_namen_stand) >= 16:
                _namen_stand.clear()
            _namen_stand[schluessel] = (time.monotonic(), karte)
        return karte

    def _namen_vergessen(self) -> None:
        with _sperre:
            _namen_stand.pop(self._schluessel(), None)

    # Dokumente -------------------------------------------------------------------------------------------
    def _dokument(self, d: dict[str, Any], karte: dict[str, dict[int, str]]) -> dict[str, Any]:
        """Ein Dokument von Paperless (Liste oder Einzelabruf) auf die Felder des Dokumentformats."""
        treffer = d.get("__search_hit__")
        schlagworte = [
            karte["tags"].get(t, str(t))
            for t in (d.get("tags") if isinstance(d.get("tags"), list) else [])
            if isinstance(t, int) and not isinstance(t, bool)
        ]
        korr, typ = _id_aus(d.get("correspondent")), _id_aus(d.get("document_type"))
        kennung = _id_aus(d.get("id"))
        return {
            "id": d.get("id"),
            "titel": d.get("title"),
            "erstellt": d.get("created"),
            "hinzugefuegt": d.get("added"),
            "schlagworte": schlagworte,
            "korrespondent": karte["correspondents"].get(korr) if korr is not None else None,
            "typ": karte["document_types"].get(typ) if typ is not None else None,
            "datei": d.get("original_file_name"),
            "seiten": d.get("page_count"),
            "auszug": auszug_aus(treffer.get("highlights")) if isinstance(treffer, dict) else None,
            "link": f"{self.link}/documents/{kennung}/details" if self.link and kennung is not None else None,
        }

    def _seite(self, abfrage: dict[str, Any], anzahl: int) -> dict[str, Any]:
        suche = urllib.parse.urlencode({**abfrage, "page_size": anzahl}, quote_via=urllib.parse.quote)
        d = self._antwort(*self.roh(f"/api/documents/?{suche}"))
        ergebnisse = d.get("results")
        if not isinstance(ergebnisse, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Dokumentliste.")
        karte = self._karte()
        return {"gesamt": d.get("count"), "dokumente": [self._dokument(x, karte) for x in ergebnisse if isinstance(x, dict)]}

    def _neueste(self, anzahl: int) -> dict[str, Any]:
        return self._seite({"ordering": "-added", "fields": _FELDER}, anzahl)

    def _suchen(self, abfrage: str, anzahl: int) -> dict[str, Any]:
        return self._seite({"query": abfrage}, anzahl)

    def _lesen_roh(self, kennung: int) -> dict[str, Any]:
        status, d = self.roh(f"/api/documents/{kennung}/")
        if status == 404:
            raise QuelleFehler(f"{self.beschreibung()} kennt dieses Dokument nicht.", 404)
        return self._antwort(status, d)

    def _holen(self, kennung: int) -> dict[str, Any]:
        d = self._lesen_roh(kennung)
        return {**self._dokument(d, self._karte()), "text": d.get("content") or ""}

    def _unsortiert(self) -> Any:
        suche = urllib.parse.urlencode({"correspondent__isnull": 1, "document_type__isnull": 1, "page_size": 1, "fields": "id"})
        try:
            return self._antwort(*self.roh(f"/api/documents/?{suche}")).get("count")
        except QuelleFehler as e:  # ohne Zähler bleibt die Liste gültig
            _log.info("%s: kein Zähler (%s)", self.beschreibung(), e)
            return None

    def _namen(self) -> Any:
        karte = self._karte()
        return {"schlagworte": list(karte["tags"].values()), "korrespondenten": list(karte["correspondents"].values()),
                "typen": list(karte["document_types"].values())}

    # Zuordnen --------------------------------------------------------------------------------------------
    def _schreiben(self, methode: str, pfad: str, koerper: dict[str, Any]) -> dict[str, Any]:
        status, d = self.roh(pfad, None, methode, koerper)
        if status in (400, 422):
            raise ValueError(f"{self.beschreibung()} lehnt die Änderung ab: {_grund(d, status)}")
        if status == 404:
            raise QuelleFehler(f"{self.beschreibung()} kennt diese Stelle nicht ({pfad.split('/')[2]}).", 404)
        return self._antwort(status, d)

    @staticmethod
    def _gefunden(karte: dict[str, dict[int, str]], art: str, name: str) -> int | None:
        for kennung, vorhanden in karte[art].items():
            if vorhanden.casefold() == name.casefold():
                return kennung
        return None

    def _id_zu_namen(self, karte: dict[str, dict[int, str]], art: str, name: str, anlegen: bool,
                     angelegt: list[str]) -> int | None:
        """Kennung zum Namen (ohne Groß-/Kleinschreibung). Fehlt er, wird er vorgemerkt und, mit ``anlegen``, angelegt."""
        kennung = self._gefunden(karte, art, name)
        if kennung is not None:
            return kennung
        angelegt.append(f"{_ARTEN_NAME[art]} {name}")
        if not anlegen:
            return None
        neu = self._schreiben("POST", f"/api/{art}/", {"name": name})
        kennung = _id_aus(neu.get("id"))
        if kennung is None:
            raise QuelleFehler(f"{self.beschreibung()} hat {_ARTEN_NAME[art]} {name} ohne Kennung angelegt.")
        karte[art][kennung] = name
        self._namen_vergessen()
        return kennung

    def _zuordnen(self, kennung: int, aenderung: dict[str, Any], vorschau: bool) -> dict[str, Any]:
        doc = self._lesen_roh(kennung)
        karte = self._karte(frisch=True)
        vorher = self._dokument(doc, karte)
        koerper: dict[str, Any] = {}
        angelegt: list[str] = []
        anlegen = not vorschau
        if "titel" in aenderung:
            koerper["title"] = aenderung["titel"]
        if "korrespondent" in aenderung:
            i = self._id_zu_namen(karte, "correspondents", aenderung["korrespondent"], anlegen, angelegt)
            if i is not None:
                koerper["correspondent"] = i
        if "typ" in aenderung:
            i = self._id_zu_namen(karte, "document_types", aenderung["typ"], anlegen, angelegt)
            if i is not None:
                koerper["document_type"] = i
        if "schlagworte_hinzu" in aenderung:
            ids = [t for t in (doc.get("tags") if isinstance(doc.get("tags"), list) else []) if isinstance(t, int)]
            for name in aenderung["schlagworte_hinzu"]:
                i = self._id_zu_namen(karte, "tags", name, anlegen, angelegt)
                if i is not None and i not in ids:
                    ids.append(i)
            koerper["tags"] = ids
        if vorschau:
            return {"vorher": vorher, "aendert": dict(aenderung), "wird_angelegt": angelegt}
        neu = self._schreiben("PATCH", f"/api/documents/{kennung}/", koerper)
        return {"vorher": vorher, "nachher": self._dokument(neu, self._karte()), "angelegt": angelegt}


def quelle(url: str | None = None, kopf: str | None = None, link: str | None = None) -> Quelle:
    """Die Quelle der Dokumente für diesen Aufruf. Reihenfolge: ``url`` (leer zählt als nicht angegeben); der mit
    ``dienst_anmelden`` angemeldete Dienst; ``FYOS_DOKUMENTE_URL``; die angemeldete Ablage; keine. ``kopf``
    (``"Name: Wert"``) überschreibt die Kopfzeile (sonst die des angemeldeten Dienstes bzw. ``FYOS_DOKUMENTE_KOPF``),
    ``link`` die Browser-Adresse (sonst die des angemeldeten Dienstes bzw. ``FYOS_DOKUMENTE_LINK``)."""
    adresse = (url or "").strip().rstrip("/")
    if not adresse:
        gespiegelt = angemeldeter_dienst()
        if gespiegelt is not None:
            return Dienst(gespiegelt[0], gespiegelt[1] if kopf is None else kopf_aus(kopf),
                          link=gespiegelt[2] if link is None else link)
        adresse = os.getenv("FYOS_DOKUMENTE_URL", "").strip().rstrip("/")
    if adresse:
        return Dienst(adresse, kopf_aus(os.getenv("FYOS_DOKUMENTE_KOPF", "") if kopf is None else kopf),
                      link=os.getenv("FYOS_DOKUMENTE_LINK", "") if link is None else link)
    ablage = angemeldete_ablage()
    if ablage is not None:
        return AblageQuelle(ablage)
    return Quelle()
