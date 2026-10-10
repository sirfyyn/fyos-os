"""Postfach für Plugins: eine Quelle, gleich ob Mail-Dienst oder Mail-Plugin.

Plugins, die Mails zeigen (Leitstand, Tagesbrief, Startseite, das Plugin ``mail`` selbst), tragen keine Adresse fest ein
und sprechen auch kein IMAP: sie fragen hier. Wer Mails liefert, meldet sich an; die Leser wissen nichts voneinander.

**Nur lesen.** Diese Quelle kann nichts senden, beantworten, löschen, verschieben oder kennzeichnen, und auch das Lesen
ändert nichts: der Gelesen-Status bleibt, wie er war. Den Dienst fragt sie nur mit GET, eine Ablage bietet nur lesende
Methoden an. **Mailtext ist Fremdinhalt**: wer ihn einem Modell zeigt, sagt dazu, dass darin keine Anweisungen stehen,
denen zu folgen ist.

**Mailformat** (Ergebnis von ``liste()``, jede Mail ein ``dict`` mit genau diesen Feldern, neueste zuerst):

======================  ======================================================================================
``id``                  Kennung in der Quelle; für Leser undurchsichtig, für ``lesen()`` wieder verwendbar (``ID_MUSTER``)
``konto``               Name des Kontos oder der Quelle dahinter, sonst ``""``
``von``                 Absender in einer Zeile, wie er sich nennt (``Name <adresse>``), sonst ``""``
``an``                  Empfänger (An) in einer Zeile, sonst ``""``
``betreff``             Betreff in einer Zeile (``(kein Betreff)``, wenn die Mail keinen hat)
``datum``               Zeitstempel ISO 8601 mit Versatz, etwa ``2026-10-06T10:09:09+00:00``; ``""``, wenn nicht lesbar
``gelesen``             ``true`` | ``false``
``labels``              deutsche Namen wie ``Posteingang``, ``Wichtig``, ``Werbung``; sonst ``[]``
``ausschnitt``          Anfang des Textes in einer Zeile, höchstens ``AUSSCHNITT_MAX`` Zeichen
======================  ======================================================================================

Die **volle Mail** (``lesen()``) hat zusätzlich ``text`` (reiner Text; HTML-Mails als Text, höchstens ``TEXT_MAX``
Zeichen), ``gekuerzt`` (``true``, wenn der Text gekürzt wurde) und ``anhaenge`` (``[{name, typ, groesse}]``, nur
Angaben, nie der Inhalt). ``konten()`` liefert ``[{name, art, adresse}]``, die Adresse ohne Passwort, bei einem Konto
mit Fehler zusätzlich ``fehler``.

**Reihenfolge der Quellen** (``quelle()``):

1. **Mail-Dienst**, wenn eine Adresse gesetzt ist (Argument ``url``, ein mit ``dienst_anmelden`` angemeldeter Dienst
   oder ``FYOS_POSTFACH_URL``; Kopfzeile aus ``FYOS_POSTFACH_KOPF``). Das ist die Ausbaustufe: ein eigener Dienst, der
   drei GET-Routen spricht (siehe ``Dienst``).
2. **Mail-Plugin** als Ablage (Grundstufe, prozessintern): ein Hub-Plugin, das sich mit ``ablage_anmelden`` meldet, etwa
   ``fyos-plugin-mail`` mit IMAP-Konten.
3. **Keine**: ``konten()``, ``liste()`` und ``lesen()`` melden ``NichtEingerichtet``.

Plugins fragen ``quelle()`` bei jedem Aufruf neu; das ist billig und nimmt eine Ablage mit, die sich erst nach ihnen
anmeldet.

**Drei Zustände, die Aufrufer trennen müssen.** Ein Ergebnis (auch die leere Liste) heißt: die Quelle hat geantwortet,
es gibt diese Mails. ``QuelleFehler``: die Quelle ist aus oder ohne Zugang, das ist nie „keine Mails“.
``NichtEingerichtet`` (ein ``QuelleFehler``): es gibt gar keine Quelle. Wie bei den Terminen liefert die Quelle „keine“
deshalb **keine leere Liste**, sondern wirft: wer vergisst, ``eingerichtet`` zu prüfen, zeigt nie fälschlich einen leeren
Posteingang.

**Abfragesprache.** ``abfrage`` ist Gmail-artig: Begriffe, durch Leerzeichen getrennt, alle müssen zutreffen. Diese
Teilmenge kann **jede** Quelle:

======================  ======================================================================================
``from:wert``           Absender enthält ``wert`` (Name oder Adresse)
``to:wert``             Empfänger enthält ``wert``
``subject:wert``        Betreff enthält ``wert``
``is:unread``           nur ungelesene Mails
``newer_than:Nd``       höchstens ``N`` Tage alt (``N`` eine ganze Zahl, Einheit ``d``)
``older_than:Nd``       mindestens ``N`` Tage alt
``in:inbox``            nur der Posteingang
freie Wörter            jedes Wort kommt im Betreff oder im Text vor
======================  ======================================================================================

``wert`` ist ein Wort oder ein Ausdruck in Anführungszeichen (``subject:"zwei Wörter"``); Groß- und Kleinschreibung
gilt nicht. Eine leere Abfrage heißt ``in:inbox``. Alles darüber hinaus (``-category:promotions``, ``label:``,
``has:attachment``, ``in:sent``) darf eine Quelle auswerten oder ignorieren, aber nie als Fehler zurückweisen: der Dienst
reicht die Abfrage unverändert an sein Gmail weiter, das Mail-Plugin kennt ``in:sent`` und ``-wort`` und überliest den
Rest. Wer sich auf mehr als die Teilmenge verlässt, bindet sich an Quellen, die es können. Ohne ``in:`` durchsuchen
Quellen, was sie führen: der Dienst alle Mails, das Mail-Plugin die Ordner, die dem Konto zugewiesen sind.

**Fehler.** ``QuelleFehler`` erbt von ``vorgaenge.QuelleFehler``, damit ein Aufrufer die Quellen mit einem ``except``
fängt (Text und ``status`` sind gleich gebaut). ``NichtEingerichtet`` erbt dagegen nur von ``postfach.QuelleFehler``: wer
„keine Vorgangs-Quelle“ fängt, soll nicht versehentlich „kein Postfach“ fangen. ``ValueError`` bedeutet falsche Eingabe
(eine Abfrage ohne Sinn, eine ungültige Kennung, ein unbekanntes Konto).

**Umgebung** (bei jedem Aufruf gelesen):

* ``FYOS_POSTFACH_URL``   Adresse des Mail-Dienstes (Ausbaustufe)
* ``FYOS_POSTFACH_KOPF``  eine Kopfzeile für den Dienst, ``Name: Wert``
"""

from __future__ import annotations

import email.utils
import http.client
import json
import logging
import os
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Protocol

from mcp_hub import vorgaenge
from mcp_hub.vorgaenge import kopf_aus

_log = logging.getLogger(__name__)

FRIST_LESEN_S = 15.0
ANTWORT_MAX = 8 * 1024 * 1024
#: So viele Mails liefert ``liste()`` ohne Angabe, und so viele höchstens
ANZAHL_STANDARD = 10
ANZAHL_MAX = 100
ABFRAGE_MAX = 300
KONTO_MAX = 60
ZEILE_MAX = 300
BETREFF_MAX = 300
AUSSCHNITT_MAX = 200
LABELS_MAX = 20
LABEL_MAX = 60
TEXT_MAX = 30000
#: So viel Quelltext einer HTML-Mail wird gelesen, wenn der Dienst nur HTML liefert
HTML_MAX = 2 * 1024 * 1024
ANHAENGE_MAX = 50
ANHANG_NAME_MAX = 200
OHNE_BETREFF = "(kein Betreff)"
OHNE_NAME = "(ohne Namen)"
#: Name des einen Kontos, das ein Mail-Dienst bietet
KONTO_DIENST = "dienst"
#: Wie eine Kennung aussieht: Buchstaben, Ziffern, ``. _ ~ = -``, vorn kein Satzzeichen. Das passt unverändert in einen
#: Pfad und in eine Abfrage, und niemand kann sie für ``..`` oder einen Schalter halten.
ID_MUSTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~=-]{0,199}")

#: Die Systemlabels von Gmail auf Deutsch (so nennt sie der Mail-Dienst in ``label_ids``). ``UNREAD`` fehlt mit Absicht
#: (es steht in ``gelesen``); eigene Labels tragen dort nur eine Kennung und bleiben weg.
LABELS_DE = {
    "INBOX": "Posteingang",
    "SENT": "Gesendet",
    "IMPORTANT": "Wichtig",
    "STARRED": "Markiert",
    "TRASH": "Papierkorb",
    "DRAFT": "Entwurf",
    "SPAM": "Spam",
    "CHAT": "Chat",
    "YELLOW_STAR": "Gelber Stern",
    "CATEGORY_PERSONAL": "Privat",
    "CATEGORY_PROMOTIONS": "Werbung",
    "CATEGORY_UPDATES": "Aktualisierungen",
    "CATEGORY_SOCIAL": "Soziale Netzwerke",
    "CATEGORY_FORUMS": "Foren",
}


class QuelleFehler(vorgaenge.QuelleFehler):
    """Die Quelle der Mails antwortet nicht wie vereinbart: aus, ohne Zugang, Netz, unerwarteter Status."""


class NichtEingerichtet(QuelleFehler):
    """Es gibt keine Quelle für Mails (kein Mail-Dienst, kein Mail-Plugin)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text or (
            "Kein Postfach eingerichtet: weder ein Mail-Dienst (FYOS_POSTFACH_URL) noch das Plugin mail "
            "(Paket fyos-plugin-mail mit FYOS_MAIL_HOST, FYOS_MAIL_NUTZER und FYOS_MAIL_PASSWORT)."
        ), 501)


class Ablage(Protocol):
    """Was ein Mail-Plugin anbietet, das sich als Quelle anmeldet (Daten statt HTTP). Nur lesende Methoden."""

    def ablage_konten(self) -> list[dict[str, Any]]:
        """Die Konten: ``{name, art, adresse}``, die Adresse ohne Passwort (``fehler``, wenn ein Konto unbrauchbar ist)."""
        ...

    def ablage_liste(self, abfrage: str, anzahl: int, konto: str | None = None) -> dict[str, Any]:
        """Die neuesten Mails zur Abfrage (Teilmenge siehe Modul-Doku), neueste zuerst, höchstens ``anzahl``:
        ``{"mails": [<Mail im Mailformat>], "ungelesen": <Zahl im Posteingang oder None>}``. ``konto`` ist der Name eines
        Kontos (``None``: alle; ein unbekannter Name ist ein ``ValueError``). Eine Mail hat mindestens ``id``; was
        fehlt, ergänzt der Kern. Ändert nichts, auch nicht den Gelesen-Status."""
        ...

    def ablage_lesen(self, id: str) -> dict[str, Any]:  # noqa: A002 — Name der Spalte im Mailformat
        """Eine Mail im Mailformat mit ``text``, ``gekuerzt`` und ``anhaenge``. ``id`` stammt aus ``ablage_liste``.
        Ändert nichts, auch nicht den Gelesen-Status."""
        ...


_sperre = threading.Lock()
_ablage: Ablage | None = None
_dienst: tuple[str, dict[str, str]] | None = None


def ablage_anmelden(ablage: Ablage | None) -> None:
    """Ein Mail-Plugin meldet sich als Quelle an; ``None`` meldet ab."""
    global _ablage
    with _sperre:
        _ablage = ablage


def angemeldete_ablage() -> Ablage | None:
    with _sperre:
        return _ablage


def dienst_anmelden(url: str | None, kopf: dict[str, str] | None = None) -> None:
    """Ein Plugin meldet einen Mail-Dienst an (Adresse und Kopfzeile); so fragen alle Plugins denselben Dienst.
    ``None`` meldet ab."""
    global _dienst
    with _sperre:
        _dienst = (url.strip().rstrip("/"), dict(kopf or {})) if url and url.strip() else None


def angemeldeter_dienst() -> tuple[str, dict[str, str]] | None:
    with _sperre:
        return _dienst


# ── Text und Mailformat ─────────────────────────────────────────────────────────────────────────────────
_STEUERZEICHEN = {c: None for c in (*range(32), 127)}
_NUR_TEXT = {c: None for c in (*range(32), 127) if c not in (9, 10)}


def _zeile(wert: Any, grenze: int | None = None) -> str:
    """Ein Wert als eine Zeile: Leerraum zusammengezogen, Steuerzeichen entfernt, auf ``grenze`` Zeichen gekürzt."""
    text = " ".join(str(wert).split()).translate(_STEUERZEICHEN) if wert is not None else ""
    return text[:grenze] if grenze else text


def _kurz(text: str, grenze: int) -> str:
    return text if len(text) <= grenze else text[: grenze - 1].rstrip() + "…"


def datum_aus(wert: Any) -> str:
    """Ein Zeitstempel ISO 8601 mit Versatz aus einem ``datetime``, einem ISO-Text oder einem Datum im Mail-Format
    (``Tue, 06 Oct 2026 10:09:09 +0000 (UTC)``); ``""``, wenn nichts Lesbares da ist. Ohne Versatz gilt UTC."""
    gelesen: datetime | None = None
    if isinstance(wert, datetime):
        gelesen = wert
    elif isinstance(wert, str) and wert.strip():
        text = wert.strip()
        try:
            gelesen = datetime.fromisoformat(text)
        except ValueError:
            try:
                gelesen = email.utils.parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError, OverflowError):
                gelesen = None
    if gelesen is None:
        return ""
    if gelesen.tzinfo is None or gelesen.utcoffset() is None:
        gelesen = gelesen.replace(tzinfo=timezone.utc)
    try:
        return gelesen.isoformat(timespec="seconds")
    except (ValueError, OverflowError):
        return ""


class _HtmlText(HTMLParser):
    """Zieht den sichtbaren Text aus HTML. Linear in der Länge, auch bei kaputtem oder bösartigem HTML."""

    #: Vor diesen Elementen beginnt eine neue Zeile ...
    _VOR = frozenset((
        "br", "p", "div", "tr", "li", "ul", "ol", "table", "blockquote", "pre", "hr", "section", "article",
        "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    ))
    #: ... und nach diesen ebenfalls (Absätze und Blöcke, nicht Listenpunkte und Tabellenzeilen)
    _NACH = frozenset((
        "p", "div", "table", "ul", "ol", "blockquote", "pre", "section", "article", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6",
    ))
    _ZELLE = frozenset(("td", "th"))
    _UNSICHTBAR = frozenset(("script", "style", "head", "title"))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self._stumm: str | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "body":
            self._stumm = None  # ein ungeschlossenes <head> verschluckt nicht den Text
        elif self._stumm is None and tag in self._UNSICHTBAR:
            self._stumm = tag
        elif tag in self._VOR:
            self.teile.append("\n")
        elif tag in self._ZELLE:
            self.teile.append(" ")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if self._stumm is None and tag in self._VOR:
            self.teile.append("\n")  # <br/> ist ein Umbruch, kein Anfang und Ende

    def handle_endtag(self, tag: str) -> None:
        if tag == self._stumm:
            self._stumm = None
        elif tag in self._NACH:
            self.teile.append("\n")

    def handle_data(self, data: str) -> None:
        if self._stumm is None:
            self.teile.append(data)


def text_aus_html(roh: Any) -> str:
    """Der sichtbare Text einer HTML-Mail (ohne Skripte und Stile), Absätze durch Zeilenumbrüche getrennt."""
    parser = _HtmlText()
    try:
        parser.feed(str(roh or "")[:HTML_MAX])
        parser.close()
    except Exception:  # noqa: BLE001 — ein Parser-Fehler bei kaputtem HTML: es bleibt, was bis dahin gelesen war
        pass
    text = "".join(parser.teile).translate(_NUR_TEXT)
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _label_namen(roh: Any) -> list[str]:
    namen: list[str] = []
    for eintrag in roh if isinstance(roh, (list, tuple)) else ():
        name = _zeile(eintrag, LABEL_MAX) if isinstance(eintrag, str) else ""
        if name and name not in namen:
            namen.append(name)
        if len(namen) >= LABELS_MAX:
            break
    return namen


def labels_de(label_ids: Any) -> list[str]:
    """Die deutschen Namen der bekannten Gmail-Systemlabels aus einer Liste von Kennungen, in ihrer Reihenfolge."""
    return _label_namen([LABELS_DE[x] for x in (label_ids if isinstance(label_ids, (list, tuple)) else ())
                         if isinstance(x, str) and x in LABELS_DE])


def mail_aus(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Bringt eine Mail in das Mailformat (Kopf); ``None``, wenn sie keine brauchbare Kennung hat (dann ließe sie sich
    nicht lesen). Fehlende Felder werden ergänzt, Zeiten und Texte vereinheitlicht."""
    kennung = roh.get("id")
    if not isinstance(kennung, str) or not ID_MUSTER.fullmatch(kennung):
        return None
    return {
        "id": kennung,
        "konto": _zeile(roh.get("konto"), KONTO_MAX),
        "von": _zeile(roh.get("von"), ZEILE_MAX),
        "an": _zeile(roh.get("an"), ZEILE_MAX),
        "betreff": _zeile(roh.get("betreff"), BETREFF_MAX) or OHNE_BETREFF,
        "datum": datum_aus(roh.get("datum")),
        "gelesen": bool(roh.get("gelesen")),
        "labels": _label_namen(roh.get("labels")),
        "ausschnitt": _kurz(_zeile(roh.get("ausschnitt")), AUSSCHNITT_MAX),
    }


def _anhang_aus(roh: Any) -> dict[str, Any] | None:
    if not isinstance(roh, dict):
        return None
    groesse = roh.get("groesse")
    return {
        "name": _zeile(roh.get("name"), ANHANG_NAME_MAX) or OHNE_NAME,
        "typ": _zeile(roh.get("typ"), 100),
        "groesse": groesse if isinstance(groesse, int) and not isinstance(groesse, bool) and groesse >= 0 else None,
    }


def mail_voll_aus(roh: dict[str, Any], kennung: str) -> dict[str, Any]:
    """Bringt eine Mail in das Mailformat samt ``text``, ``gekuerzt`` und ``anhaenge``. Die Kennung ist die angefragte
    (``kennung``, schon geprüft), auch wenn die Quelle eine andere nennt."""
    kopf = mail_aus({**roh, "id": kennung})
    if kopf is None:  # ``kennung`` ist geprüft; nur zur Sicherheit
        raise QuelleFehler("Die Quelle hat die Mail nicht lesbar geliefert.")
    text = str(roh.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").translate(_NUR_TEXT).strip()
    gekuerzt = bool(roh.get("gekuerzt")) or len(text) > TEXT_MAX
    anhaenge_roh = roh.get("anhaenge")
    anhaenge_roh = anhaenge_roh[:ANHAENGE_MAX] if isinstance(anhaenge_roh, list) else []
    anhaenge = [a for a in (_anhang_aus(x) for x in anhaenge_roh) if a]
    return {**kopf, "text": text[:TEXT_MAX], "gekuerzt": gekuerzt, "anhaenge": anhaenge}


def konto_aus(roh: dict[str, Any]) -> dict[str, Any] | None:
    """Bringt ein Konto in die Form ``{name, art, adresse}`` (dazu ``nutzer`` und ``fehler``, wenn die Quelle sie nennt);
    ``None`` ohne Namen."""
    name = _zeile(roh.get("name"), KONTO_MAX)
    if not name:
        return None
    aus = {"name": name, "art": _zeile(roh.get("art"), 30), "adresse": _zeile(roh.get("adresse"), 200)}
    for feld in ("nutzer", "fehler"):
        if roh.get(feld):
            aus[feld] = _zeile(roh[feld], 300)
    return aus


# ── Eingaben ────────────────────────────────────────────────────────────────────────────────────────────
def _abfrage(wert: Any) -> str:
    if wert is None:
        return "in:inbox"
    if not isinstance(wert, str):
        raise ValueError("abfrage muss ein Text sein")
    text = _zeile(wert)
    if len(text) > ABFRAGE_MAX:
        raise ValueError(f"abfrage ist länger als {ABFRAGE_MAX} Zeichen")
    return text or "in:inbox"


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


def _konto_filter(wert: Any) -> str | None:
    if wert is None:
        return None
    if not isinstance(wert, str):
        raise ValueError("konto muss ein Text sein")
    text = _zeile(wert)
    if len(text) > KONTO_MAX:
        raise ValueError(f"konto ist länger als {KONTO_MAX} Zeichen")
    return text or None


def _kennung(wert: Any) -> str:
    if not isinstance(wert, str) or not ID_MUSTER.fullmatch(wert):
        raise ValueError("id ist keine gültige Mail-Kennung (sie stammt aus einer Mail-Liste, unverändert übernehmen)")
    return wert


def _zaehler(wert: Any) -> int | None:
    return wert if isinstance(wert, int) and not isinstance(wert, bool) and wert >= 0 else None


# ── Quellen ─────────────────────────────────────────────────────────────────────────────────────────────
class Quelle:
    """Gemeinsame Form aller Quellen. ``art``: dienst | ablage | keine. Diese Grundform ist die Quelle „keine“."""

    art = "keine"

    @property
    def eingerichtet(self) -> bool:
        return self.art != "keine"

    def beschreibung(self) -> str:
        return "kein Postfach eingerichtet"

    def konten(self) -> list[dict[str, Any]]:
        """Die Konten: ``{name, art, adresse}``."""
        raise NichtEingerichtet()

    def liste(self, abfrage: Any = "in:inbox", anzahl: Any = ANZAHL_STANDARD, konto: Any = None,
              zaehlen: bool = True) -> dict[str, Any]:
        """Die neuesten Mails zur Abfrage (Teilmenge siehe Modul-Doku), neueste zuerst, höchstens ``anzahl``
        (1 bis ``ANZAHL_MAX``): ``{"mails": [...], "ungelesen": <Zahl im Posteingang oder None>}``. ``konto``: Name
        eines Kontos (``None``: alle). ``zaehlen=False`` spart der Quelle den Zähler (``ungelesen`` ist dann ``None``),
        wenn er ihr etwas kostet. Die Antwort „keine Mails“ ist die leere Liste; ist die Quelle aus oder ohne Zugang,
        wirft der Aufruf ``QuelleFehler``."""
        q, n, k = _abfrage(abfrage), _anzahl(anzahl), _konto_filter(konto)
        roh = self._liste(q, n, k, bool(zaehlen))
        mails = [m for m in (mail_aus(x) if isinstance(x, dict) else None for x in roh["mails"]) if m]
        if len(mails) < len(roh["mails"]):
            _log.warning("%s: %d Einträge ohne brauchbare Kennung übersprungen", self.beschreibung(),
                         len(roh["mails"]) - len(mails))
        return {"mails": mails[:n], "ungelesen": _zaehler(roh.get("ungelesen"))}

    def lesen(self, id: Any) -> dict[str, Any]:  # noqa: A002 — Name der Spalte im Mailformat
        """Eine Mail im Mailformat samt ``text``, ``gekuerzt`` und ``anhaenge``. ``id`` stammt aus ``liste()``."""
        kennung = _kennung(id)
        return mail_voll_aus(self._lesen(kennung), kennung)

    def als_dict(self) -> dict[str, Any]:
        return {"art": self.art, "eingerichtet": self.eingerichtet, "beschreibung": self.beschreibung()}

    def _liste(self, abfrage: str, anzahl: int, konto: str | None, zaehlen: bool) -> dict[str, Any]:
        raise NichtEingerichtet()

    def _lesen(self, kennung: str) -> dict[str, Any]:
        raise NichtEingerichtet()


class AblageQuelle(Quelle):
    """Ein Mail-Plugin als Quelle (prozessintern)."""

    art = "ablage"

    def __init__(self, ablage: Ablage) -> None:
        self.ablage = ablage

    def beschreibung(self) -> str:
        name = _zeile(getattr(self.ablage, "name", ""), 60)
        return f"Mail-Plugin {name}" if name else "Mail-Plugin"

    @staticmethod
    def _rufe(fn: Any) -> Any:
        try:
            return fn()
        except (QuelleFehler, ValueError):
            raise
        except vorgaenge.QuelleFehler as exc:  # ein Plugin mit der Fehlerklasse der Vorgänge
            raise QuelleFehler(str(exc), exc.status) from exc
        except NotImplementedError as exc:
            raise QuelleFehler("Das Mail-Plugin kann das nicht.", 501) from exc
        except Exception as exc:  # noqa: BLE001 — Plugin-Fehler; nur der Typ geht an die Leser, nie der Text
            _log.warning("Mail-Plugin: unerwarteter Fehler (%s)", type(exc).__name__,
                         exc_info=_log.isEnabledFor(logging.DEBUG))
            raise QuelleFehler(f"Das Mail-Plugin meldet einen Fehler ({type(exc).__name__}).") from exc

    def konten(self) -> list[dict[str, Any]]:
        roh = self._rufe(self.ablage.ablage_konten)
        if not isinstance(roh, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Kontenliste")
        return [k for k in (konto_aus(x) for x in roh if isinstance(x, dict)) if k]

    def _liste(self, abfrage: str, anzahl: int, konto: str | None, zaehlen: bool) -> dict[str, Any]:
        roh = self._rufe(lambda: self.ablage.ablage_liste(abfrage, anzahl, konto))
        if not isinstance(roh, dict) or not isinstance(roh.get("mails"), list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Mailliste")
        return {"mails": roh["mails"], "ungelesen": roh.get("ungelesen") if zaehlen else None}

    def _lesen(self, kennung: str) -> dict[str, Any]:
        roh = self._rufe(lambda: self.ablage.ablage_lesen(kennung))
        if not isinstance(roh, dict):
            raise QuelleFehler(f"{self.beschreibung()} hat die Mail nicht geliefert.")
        return roh


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
            if d.get(k):
                return _zeile(d[k], 300)
    return f"HTTP {status}"


class Dienst(Quelle):
    """Mail-Dienst per HTTP unter ``url``, **nur lesend**. Der Vertrag ist der des Mail-Dienstes, den FYOS bisher
    betrieben hat, drei GET-Routen:

    * ``GET /api/inbox/list?q=<Abfrage>&limit=N`` liefert ``{"status": "live", "messages": [{id, subject, from, to, date,
      snippet, label_ids, unread}], "_stub": false}``. ``q`` ist die Abfrage unverändert (Gmail-Syntax). ``"_stub": true``
      oder ein ``status`` außer ``live`` und ``refreshed`` heißt: ohne Zugang zum Postfach (``_message`` sagt warum); das
      ist ein ``QuelleFehler`` mit Status 503, nie „keine Mails“.
    * ``GET /api/inbox/unread-count`` liefert ``{"inbox_unread": N, …}``. Fehlt der Zähler oder schlägt der Aufruf fehl,
      bleibt die Liste gültig und ``ungelesen`` ist ``None``.
    * ``GET /api/inbox/message/<id>`` liefert ``{id, subject, from, to, date, label_ids, unread, body_plain, body_html,
      attachments: [{filename, mime_type, size}]}``.

    Der Dienst hat ein Konto, ``KONTO_DIENST``. ``date`` darf im Mail-Format (RFC 5322) stehen; den Text liest der Kern
    aus ``body_plain`` oder, wenn der leer ist, aus ``body_html``. Umleitungen werden nicht verfolgt (die Kopfzeile geht
    nur an die eingetragene Adresse)."""

    art = "dienst"

    def __init__(self, url: str, kopf: dict[str, str] | None = None, aufruf: Any = None) -> None:
        self.url = url.rstrip("/")
        self.kopf = dict(kopf or {})
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
        return f"Mail-Dienst {host}" if host else "Mail-Dienst"

    def roh(self, pfad: str, frist: float | None = None) -> tuple[int, Any]:
        """(Status, JSON) vom Dienst, immer per GET; Fehlerstatus kommen als Wert, ein unlesbarer Rumpf als ``None``. Ist
        der Dienst nicht erreichbar, wirft der Aufruf ``QuelleFehler``. ``frist`` in Sekunden (ohne Angabe
        ``FRIST_LESEN_S``)."""
        frist = FRIST_LESEN_S if frist is None else frist
        if self._aufruf is not None:
            return self._aufruf(pfad, frist)
        kopf = {"Accept": "application/json", "User-Agent": "fyos-hub", **self.kopf}
        try:
            req = urllib.request.Request(self.url + pfad, method="GET", headers=kopf)
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
                f"{self.beschreibung()} lehnt die Anfrage ab ({status}); Zugang prüfen (FYOS_POSTFACH_KOPF).", status)
        if 300 <= status < 400:
            raise QuelleFehler(
                f"{self.beschreibung()} antwortet mit {status} (Umleitungen werden nicht verfolgt; Adresse prüfen).", status)
        if status >= 400:
            raise QuelleFehler(f"{self.beschreibung()} antwortet mit {status}: {_grund(d, status)}", status)
        if not isinstance(d, dict):
            raise QuelleFehler(f"{self.beschreibung()} antwortet nicht mit lesbaren Daten.")
        return d

    def _ohne_zugang(self, d: dict[str, Any]) -> QuelleFehler:
        grund = _zeile(d.get("_message") or d.get("status") or "ohne Angabe", 300)
        return QuelleFehler(f"{self.beschreibung()} hat keinen Zugang zum Postfach: {grund}", 503)

    @staticmethod
    def _kopf(m: dict[str, Any]) -> dict[str, Any]:
        """Eine Mail des Dienstes (Liste oder Einzelabruf) auf die Felder des Mailformats."""
        return {
            "id": m.get("id"),
            "konto": KONTO_DIENST,
            "von": m.get("from"),
            "an": m.get("to"),
            "betreff": m.get("subject"),
            "datum": m.get("date"),
            "gelesen": not bool(m.get("unread")),
            "labels": labels_de(m.get("label_ids")),
            "ausschnitt": m.get("snippet"),
        }

    def konten(self) -> list[dict[str, Any]]:
        return [{"name": KONTO_DIENST, "art": "dienst", "adresse": self._host()}]

    def _konto_pruefen(self, konto: str | None) -> None:
        if konto is not None and konto.casefold() != KONTO_DIENST:
            raise ValueError(f"konto {konto!r} gibt es nicht (der Mail-Dienst hat das Konto {KONTO_DIENST!r})")

    def _liste(self, abfrage: str, anzahl: int, konto: str | None, zaehlen: bool) -> dict[str, Any]:
        self._konto_pruefen(konto)
        suche = urllib.parse.urlencode({"q": abfrage, "limit": anzahl}, quote_via=urllib.parse.quote)
        d = self._antwort(*self.roh(f"/api/inbox/list?{suche}"))
        if d.get("_stub") or str(d.get("status") or "live") not in ("live", "refreshed"):
            raise self._ohne_zugang(d)
        nachrichten = d.get("messages")
        if not isinstance(nachrichten, list):
            raise QuelleFehler(f"{self.beschreibung()}: Antwort ohne Mailliste.")
        mails = [self._kopf(m) for m in nachrichten if isinstance(m, dict)]
        return {"mails": mails, "ungelesen": self._ungelesen() if zaehlen else None}

    def _ungelesen(self) -> int | None:
        try:
            d = self._antwort(*self.roh("/api/inbox/unread-count"))
        except QuelleFehler as e:  # ohne Zähler bleibt die Liste gültig
            _log.info("%s: kein Zähler (%s)", self.beschreibung(), e)
            return None
        return _zaehler(d.get("inbox_unread"))

    def _lesen(self, kennung: str) -> dict[str, Any]:
        # Das Muster der Kennung lässt nur Zeichen zu, die in einem Pfad unverändert stehen; quote() ist der Gürtel.
        status, d = self.roh("/api/inbox/message/" + urllib.parse.quote(kennung, safe="="))
        if status == 404:
            raise QuelleFehler(f"{self.beschreibung()} kennt diese Mail nicht.", 404)
        d = self._antwort(status, d)
        text = str(d.get("body_plain") or "").strip() or text_aus_html(d.get("body_html"))
        angehaengt = d.get("attachments")
        anhaenge = [
            {"name": a.get("filename"), "typ": a.get("mime_type"), "groesse": a.get("size")}
            for a in angehaengt if isinstance(a, dict)
        ] if isinstance(angehaengt, list) else []
        return {**self._kopf(d), "text": text, "anhaenge": anhaenge}


def quelle(url: str | None = None, kopf: str | None = None) -> Quelle:
    """Die Quelle der Mails für diesen Aufruf. Reihenfolge: ``url`` (leer zählt als nicht angegeben); der mit
    ``dienst_anmelden`` angemeldete Dienst; ``FYOS_POSTFACH_URL``; das angemeldete Mail-Plugin; keine. ``kopf``
    (``"Name: Wert"``) überschreibt die Kopfzeile (sonst die des angemeldeten Dienstes bzw. ``FYOS_POSTFACH_KOPF``)."""
    adresse = (url or "").strip().rstrip("/")
    if not adresse:
        gespiegelt = angemeldeter_dienst()
        if gespiegelt is not None:
            return Dienst(gespiegelt[0], gespiegelt[1] if kopf is None else kopf_aus(kopf))
        adresse = os.getenv("FYOS_POSTFACH_URL", "").strip().rstrip("/")
    if adresse:
        return Dienst(adresse, kopf_aus(os.getenv("FYOS_POSTFACH_KOPF", "") if kopf is None else kopf))
    ablage = angemeldete_ablage()
    if ablage is not None:
        return AblageQuelle(ablage)
    return Quelle()
