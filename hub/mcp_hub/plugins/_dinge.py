"""Dinge und Übergaben — was sich zwischen Apps ziehen lässt und was beim Ablegen passiert.

Ein **Ding** ist etwas, das eine App zeigt und das einen Namen und eine Kennung hat: eine Notiz, eine Datei, ein Vorgang.
Eine App meldet seinen **Typ** an (`registriere_ding`): menschlicher Name, die App, die es zeigt (Fläche), das lesende
Werkzeug, das ein einzelnes Ding liefert, und wie dessen Kennungsargument heißt. Die Shell bekommt das Register mit
`GET /hub/apps` (Felder `dinge` und `uebergaben`); danach darf die Oberfläche der App ein Ding ziehbar machen
(`App.ziehbar`, ui/_bruecke.js) und die Shell weiß, wohin man es ziehen kann.

Eine **Übergabe** sagt, was geschieht, wenn ein Ding eines Typs auf das Fenster einer anderen App fällt
(`registriere_uebergabe`): welches Werkzeug der Ziel-App läuft, wie die Felder des Dings seine Argumente füllen
(`abbildung`) und ein kurzer Satz, was passiert (`wirkung`, steht als Hinweis am Fenster, bevor man loslässt). Die Übergabe
legt nichts selbst an: die Ziel-App zeigt den Trockenlauf des Werkzeugs und fragt (`App.beantragen`), erst „Ja“ führt aus.
Paare ohne Übergabe bieten nur an, den Agenten zu fragen.

`abbildung` ist eine Tabelle Argument → Wert. Ein Text darf Platzhalter in geschweiften Klammern tragen: `{id}` und `{label}`
(Kennung und Anzeigename des gezogenen Dings, immer da) und jedes Feld, das der Typ in `felder` nennt (es kommt aus dem
Ergebnis des lesenden Werkzeugs). Andere Werte (Zahlen, Wahrheitswerte) gelten, wie sie sind. Mehr gibt es nicht: keine
Schleifen, keine Berechnung — was ein Feld berechnen muss, berechnet das lesende Werkzeug des Typs.

Registrieren geschieht beim Import des Plugins, nach `registriere_app`:

    registriere_ding("notiz", "Notiz", flaeche="beispiel_app", lesen="beispiel_app.lesen", felder=("text",))
    registriere_uebergabe("datei", "beispiel_app", "beispiel_app.hinzufuegen", {"text": "Datei {id}"}, "Als Notiz merken")

Was die Shell bekommt, prüft `fuer_shell`: eine Übergabe, deren Typ, App oder Werkzeug nicht (mehr) da ist, fällt weg.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from . import _identitaet

logger = logging.getLogger(__name__)

TYP_MUSTER = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
FELD_MUSTER = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
WERKZEUG_MUSTER = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
PLATZHALTER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

#: Felder, die jedes gezogene Ding hat: Kennung und Anzeigename.
GRUNDFELDER = ("id", "label")
NAME_MAX = 40
WIRKUNG_MAX = 120
WERT_MAX = 2000
ARGUMENTE_MAX = 12

#: Typ → Eintrag (`name`, `flaeche`, `lesen`, `id_argument`, `felder`).
DINGE: dict[str, dict[str, Any]] = {}
#: (Quelltyp, Ziel-App) → Eintrag (`werkzeug`, `abbildung`, `wirkung`). Je Paar eine Übergabe; neu anmelden überschreibt.
UEBERGABEN: dict[tuple[str, str], dict[str, Any]] = {}


def registriere_ding(
    typ: str,
    name: str,
    flaeche: str,
    lesen: str | None = None,
    id_argument: str = "id",
    felder: tuple[str, ...] | list[str] = (),
) -> None:
    """Meldet den Typ eines ziehbaren Dings an.

    `typ` kleingeschrieben mit Ziffern und „-“ (`notiz`, `datei`); `name` die Einzahl für Menschen („Notiz“); `flaeche` der
    Schlüssel der App, die das Ding zeigt (wie bei `registriere_app`, die App muss schon angemeldet sein); `lesen` das
    lesende Werkzeug der App (`<plugin>.<name>`, mit Tag `flaeche`), das ein Ding zu seiner Kennung liefert, `id_argument`
    der Name von dessen Kennungsargument; `felder` die Felder dieses Ergebnisses, die Übergaben einsetzen dürfen.
    Wiederholtes Anmelden überschreibt. Ungültige Angaben werfen `ValueError` (ein Fehler des Plugins, beim Import sichtbar).
    """
    if not isinstance(typ, str) or not TYP_MUSTER.fullmatch(typ):
        raise ValueError(f"Ding-Typ {typ!r}: klein geschrieben, Buchstaben, Ziffern und „-“, höchstens 32 Zeichen")
    if not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX:
        raise ValueError(f"Ding {typ!r}: name fehlt oder ist länger als {NAME_MAX} Zeichen")
    if flaeche not in _identitaet.APPS:
        raise ValueError(f"Ding {typ!r}: die App {flaeche!r} ist nicht angemeldet (erst registriere_app)")
    if lesen is not None and not WERKZEUG_MUSTER.fullmatch(str(lesen)):
        raise ValueError(f"Ding {typ!r}: lesen muss <plugin>.<werkzeug> heißen, nicht {lesen!r}")
    if not isinstance(id_argument, str) or not FELD_MUSTER.fullmatch(id_argument):
        raise ValueError(f"Ding {typ!r}: id_argument {id_argument!r} ist kein Argumentname")
    liste = list(felder)
    for f in liste:
        if not isinstance(f, str) or not FELD_MUSTER.fullmatch(f) or f in GRUNDFELDER:
            raise ValueError(f"Ding {typ!r}: Feld {f!r} ist ungültig (id und label gibt es immer)")
    DINGE[typ] = {"name": name.strip(), "flaeche": flaeche, "lesen": lesen, "id_argument": id_argument, "felder": liste}


def platzhalter(abbildung: dict[str, Any]) -> set[str]:
    """Alle Namen in `{…}` aus den Textwerten einer Abbildung."""
    namen: set[str] = set()
    for wert in abbildung.values():
        if isinstance(wert, str):
            namen.update(PLATZHALTER.findall(wert))
    return namen


def registriere_uebergabe(
    quelltyp: str,
    ziel_app: str,
    werkzeug: str,
    abbildung: dict[str, Any],
    wirkung: str,
) -> None:
    """Meldet an, was geschieht, wenn ein Ding vom Typ `quelltyp` auf das Fenster der App `ziel_app` fällt.

    `werkzeug` ist ein Werkzeug des Plugins der Ziel-App (`<plugin>.<name>`) — am besten ein schreibendes mit Trockenlauf
    und `bestaetigt`, denn die Ziel-App zeigt dessen Plan und fragt, bevor es läuft. `abbildung` füllt seine Argumente
    (Argument → Wert, Texte mit `{id}`, `{label}`, `{feld}`), `wirkung` ist der Satz am Fenster („Als Datei ablegen“).
    Der Typ muss beim Anmelden noch nicht da sein (Plugins laden in beliebiger Reihenfolge); `fuer_shell` prüft später.
    """
    if not isinstance(quelltyp, str) or not TYP_MUSTER.fullmatch(quelltyp):
        raise ValueError(f"Übergabe: Quelltyp {quelltyp!r} ist kein Ding-Typ")
    if not isinstance(ziel_app, str) or not ziel_app:
        raise ValueError("Übergabe: ziel_app fehlt")
    if not isinstance(werkzeug, str) or not WERKZEUG_MUSTER.fullmatch(werkzeug):
        raise ValueError(f"Übergabe: werkzeug muss <plugin>.<werkzeug> heißen, nicht {werkzeug!r}")
    if not isinstance(wirkung, str) or not wirkung.strip() or len(wirkung) > WIRKUNG_MAX:
        raise ValueError(f"Übergabe: wirkung fehlt oder ist länger als {WIRKUNG_MAX} Zeichen")
    if not isinstance(abbildung, dict) or len(abbildung) > ARGUMENTE_MAX:
        raise ValueError(f"Übergabe: abbildung ist eine Tabelle mit höchstens {ARGUMENTE_MAX} Einträgen")
    for arg, wert in abbildung.items():
        if not isinstance(arg, str) or not FELD_MUSTER.fullmatch(arg):
            raise ValueError(f"Übergabe: Argument {arg!r} ist kein Argumentname")
        if isinstance(wert, str):
            if len(wert) > WERT_MAX:
                raise ValueError(f"Übergabe: Wert von {arg!r} ist länger als {WERT_MAX} Zeichen")
            if "{" in PLATZHALTER.sub("", wert) or "}" in PLATZHALTER.sub("", wert):
                raise ValueError(f"Übergabe: Wert von {arg!r} hat eine „{{“ oder „}}“, die kein Platzhalter ist")
        elif not isinstance(wert, (int, float, bool)):
            raise ValueError(f"Übergabe: Wert von {arg!r} ist Text, Zahl oder Wahrheitswert, nicht {type(wert).__name__}")
    UEBERGABEN[(quelltyp, ziel_app)] = {"werkzeug": werkzeug, "abbildung": dict(abbildung), "wirkung": wirkung.strip()}


def ausfuellen(abbildung: dict[str, Any], werte: dict[str, Any]) -> dict[str, Any]:
    """Setzt die Felder eines Dings in eine Abbildung ein (so wie die Shell es tut): die Argumente für das Zielwerkzeug.

    `werte` hat mindestens `id` und `label`. Ein Platzhalter ohne Wert wirft `ValueError` — lieber keine Übergabe als eine mit
    einem Loch. Werte, die keine Texte sind, gehen unverändert durch.
    """

    def ersetze(m: re.Match[str]) -> str:
        name = m.group(1)
        wert = werte.get(name)
        if wert is None or isinstance(wert, (dict, list)):
            raise ValueError(f"Das Feld {name!r} fehlt")
        return str(wert)

    return {arg: PLATZHALTER.sub(ersetze, wert) if isinstance(wert, str) else wert for arg, wert in abbildung.items()}


def _haupt(app: str) -> str | None:
    """Hauptwerkzeug einer App im Format `<plugin>__<name>` (die Fläche in der Shell heißt `app:<das>`)."""
    return _identitaet.HAUPTWERKZEUG.get(app)


def _plugin_der_app(app: str) -> str | None:
    haupt = _haupt(app)
    return haupt.split("__", 1)[0] if haupt else None


def fuer_shell(werkzeug_ok: Callable[[str], bool] | None = None) -> dict[str, Any]:
    """Das Register für die Shell: `{"dinge": {typ: {...}}, "uebergaben": [{...}]}` (Felder in der Schreibweise des Browsers).

    `werkzeug_ok(<plugin>.<name>)` sagt, ob der Hub dieses Werkzeug als Flächen-Werkzeug kennt (im Hub: Tag `flaeche` oder
    Oberfläche); ohne die Funktion gelten alle als da (Tests). Was nicht passt, bleibt weg und steht einmal im Protokoll:
    ein Typ ohne App mit Fenster oder ohne lesbares Werkzeug, eine Übergabe ohne Typ, ohne Ziel-App, mit einem Werkzeug
    eines anderen Plugins oder mit einem Platzhalter, den der Typ nicht liefert.
    """
    ok = werkzeug_ok or (lambda _fqtn: True)
    dinge: dict[str, Any] = {}
    for typ, d in sorted(DINGE.items()):
        haupt = _haupt(d["flaeche"])
        if not haupt:
            logger.warning("Ding %r: die App %r hat kein Hauptwerkzeug, die Shell kann sie nicht öffnen", typ, d["flaeche"])
            continue
        if d["lesen"] and not ok(d["lesen"]):
            logger.warning("Ding %r: das lesende Werkzeug %r kennt der Hub nicht als Flächen-Werkzeug", typ, d["lesen"])
            continue
        eintrag: dict[str, Any] = {"name": d["name"], "flaeche": f"app:{haupt}", "idArgument": d["id_argument"], "felder": list(d["felder"])}
        if d["lesen"]:
            eintrag["lesen"] = d["lesen"].replace(".", "__", 1)
        dinge[typ] = eintrag
    uebergaben: list[dict[str, Any]] = []
    for (typ, ziel), u in sorted(UEBERGABEN.items()):
        d = DINGE.get(typ)
        haupt = _haupt(ziel)
        if typ not in dinge or d is None or not haupt:
            continue  # Typ oder Ziel (noch) nicht da: kein Fehler, das Plugin kann später laden
        if u["werkzeug"].split(".", 1)[0] != _plugin_der_app(ziel):
            logger.warning("Übergabe %s → %s: %r gehört nicht zum Plugin der Ziel-App", typ, ziel, u["werkzeug"])
            continue
        if not ok(u["werkzeug"]):
            logger.warning("Übergabe %s → %s: das Werkzeug %r kennt der Hub nicht als Flächen-Werkzeug", typ, ziel, u["werkzeug"])
            continue
        fehlt = platzhalter(u["abbildung"]) - set(GRUNDFELDER) - set(d["felder"])
        if fehlt:
            logger.warning("Übergabe %s → %s: der Typ liefert die Felder %s nicht", typ, ziel, ", ".join(sorted(fehlt)))
            continue
        uebergaben.append(
            {
                "quelle": typ,
                "ziel": f"app:{haupt}",
                "werkzeug": u["werkzeug"].replace(".", "__", 1),
                "abbildung": dict(u["abbildung"]),
                "wirkung": u["wirkung"],
            }
        )
    return {"dinge": dinge, "uebergaben": uebergaben}
