"""Stufe je Fähigkeit: Grundstufe, Ausbaustufe oder aus, und was der Installer daraus macht.

Eine Fähigkeit (Vorgänge, Termine, Postfach lesen, Post senden, Dokumente) gehört zu einem Baustein und kennt bis zu
zwei Stufen (`katalog_stufen.yaml`, Begriffe in `docs/REBUILD.md`):

    Grundstufe   ohne eigenen Dienst: eine Ablage im Hub, CalDAV oder ICS direkt, IMAP direkt.
    Ausbaustufe  ein eigener Dienst, den der Hub über eine Adresse erreicht (`FYOS_TERMINE_URL` und ähnlich).
    aus          nichts davon einrichten; die Fähigkeit meldet ehrlich »nicht eingerichtet«.

Die Vorgabe richtet sich nach der Bauart: Kubernetes wählt die Ausbaustufe, Docker Compose die Grundstufe. Jede
Fähigkeit lässt sich einzeln umstellen (Assistent, Textoberfläche, `--stufe NAME=STUFE`, `stufen:` in der
Antwortdatei). Gibt es bei einer Fähigkeit keine Grundstufe, bleiben Ausbau und aus.

Die Wahl wirkt auf die Felder: Nur die Felder der gewählten Stufe werden abgefragt und geschrieben. Bei der Grundstufe
fehlt jede Adresse eines Dienstes, das Plugin nimmt den direkten Weg. Bei der Ausbaustufe steht die Adresse in der
Umgebung des Hubs. Einen Dienst dazu liefert der Installer heute noch nicht mit; fehlt die Adresse, sagt der Plan das
und nennt die Variable. Erfunden wird nichts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from . import sprache as spr
from .katalog import _ID, Feld, Katalog, KatalogFehler, _feld

GRUND, AUSBAU, AUS = "grund", "ausbau", "aus"
STUFEN = (GRUND, AUSBAU, AUS)
_STUFE_TITEL = {GRUND: "Grundstufe", AUSBAU: "Ausbaustufe", AUS: "aus"}


class _StufenTitel(dict):
    """Anzeigename der Stufe in der aktiven Sprache (Grundstufe/basic tier, Ausbaustufe/extended tier, aus/off)."""

    def __getitem__(self, k: str) -> str:
        return spr._(_STUFE_TITEL[k])


STUFE_TITEL = _StufenTitel(_STUFE_TITEL)
_k = spr.katalog_text
#: Welche Stufe eine Bauart ohne ausdrückliche Wahl vorzieht. »Nur Dateien« hat das Layout von Docker Compose.
VORGABE_JE_ZIEL = {"compose": GRUND, "dateien": GRUND, "k8s": AUSBAU}
#: Wohin der Nutzer eine fehlende Adresse einträgt.
EINTRAGEN_IN = {
    "compose": ".env", "dateien": ".env",
    "k8s": "kustomization.yaml (Adresse) und secrets.yaml (Kopfzeile)",
}


@dataclass(frozen=True)
class Stufe:
    id: str  # grund | ausbau
    titel: str  # Kurzname, zum Beispiel »CalDAV und ICS direkt«
    text: str  # ein bis zwei Sätze: was das heißt
    felder: tuple[str, ...] = ()  # Felder des Bausteins, die nur in dieser Stufe gelten
    neue_felder: tuple[Feld, ...] = ()  # Felder, die der Baustein bekommt, falls sie ihm fehlen
    url: str = ""  # Feld mit der Adresse des Dienstes (nur Ausbau)
    verfuegbar: bool = True  # False: die Stufe ist geplant, aber noch nicht gebaut


@dataclass(frozen=True)
class Faehigkeit:
    id: str
    titel: str
    kurz: str
    baustein: str
    stufen: dict[str, Stufe] = field(default_factory=dict)
    aus: bool = False  # darf man die Fähigkeit ganz ausschalten?

    def moegliche(self) -> list[str]:
        """Die Stufen, die man wählen kann, in der Reihenfolge Grund, Ausbau, aus."""
        erg = [s for s in (GRUND, AUSBAU) if s in self.stufen and self.stufen[s].verfuegbar]
        return erg + ([AUS] if self.aus else [])

    def vorgabe(self, ziel: str) -> str:
        """Die Stufe, die ohne Wahl gilt: die der Bauart, sonst die andere, sonst aus."""
        moeglich = self.moegliche()
        wunsch = VORGABE_JE_ZIEL.get(ziel, GRUND)
        if wunsch in moeglich:
            return wunsch
        echte = [s for s in moeglich if s != AUS]
        return echte[0] if echte else AUS

    def alle_felder(self) -> set[str]:
        return {n for s in self.stufen.values() for n in s.felder}

    def als_dict(self) -> dict[str, Any]:
        """Für den Web-Assistenten: Stufen mit Feldern, Vorgabe je Bauart und die wählbaren Stufen."""
        return {
            "id": self.id, "titel": _k(self.titel), "kurz": _k(self.kurz), "baustein": self.baustein, "aus": self.aus,
            "stufen": [
                {"id": s.id, "name": STUFE_TITEL[s.id], "titel": _k(s.titel), "text": _k(s.text),
                 "felder": list(s.felder), "verfuegbar": s.verfuegbar}
                for s in self.stufen.values()
            ],
            "moegliche": self.moegliche(),
            "vorgabe": {ziel: self.vorgabe(ziel) for ziel in VORGABE_JE_ZIEL},
        }


@dataclass
class Wahl:
    """Die Stufe, die für eine Fähigkeit gilt, und woher sie kommt."""

    faehigkeit: Faehigkeit
    stufe: str
    vorgabe: bool = True  # False: ausdrücklich gewählt
    url_umgebung: str = ""  # bei Ausbau: die Variable mit der Adresse
    url_gesetzt: bool = False

    @property
    def stufe_titel(self) -> str:
        return STUFE_TITEL[self.stufe]

    @property
    def was(self) -> str:
        s = self.faehigkeit.stufen.get(self.stufe)
        return _k(s.titel) if s else spr._("nicht eingerichtet")

    def zeile(self) -> str:
        herkunft = spr._("Vorgabe") if self.vorgabe else spr._("von dir gewählt")
        return f"{_k(self.faehigkeit.titel)}: {self.stufe_titel} ({herkunft}), {self.was}"

    def als_dict(self) -> dict[str, Any]:
        f = self.faehigkeit
        return {
            "id": f.id, "titel": _k(f.titel), "baustein": f.baustein, "stufe": self.stufe,
            "stufe_titel": self.stufe_titel, "vorgabe": self.vorgabe, "was": self.was,
            "umgebung": self.url_umgebung, "adresse_gesetzt": self.url_gesetzt,
        }


# ---------------------------------------------------------------- Laden


def _stufe(roh: Any, id_: str, ort: str, fehler: list[str]) -> Stufe | None:
    ort = f"{ort}.{id_}"
    if not isinstance(roh, dict):
        fehler.append(f"{ort}: Stufe muss ein Objekt sein")
        return None
    n0 = len(fehler)
    titel, text = roh.get("titel"), roh.get("text")
    for name, wert in (("titel", titel), ("text", text)):
        if not isinstance(wert, str) or not wert.strip():
            fehler.append(f"{ort}: '{name}' muss ein nichtleerer Text sein")
    verfuegbar = roh.get("verfuegbar", True)
    if not isinstance(verfuegbar, bool):
        fehler.append(f"{ort}: 'verfuegbar' muss wahr oder falsch sein")
        verfuegbar = True
    felder_roh = roh.get("felder", []) or []
    if not isinstance(felder_roh, list):
        fehler.append(f"{ort}: 'felder' muss eine Liste sein")
        felder_roh = []
    namen: list[str] = []
    neue: list[Feld] = []
    for eintrag in felder_roh:
        if isinstance(eintrag, str):
            namen.append(eintrag)
        else:
            feld = _feld(eintrag, ort, fehler)
            if feld:
                namen.append(feld.name)
                neue.append(feld)
    if len(set(namen)) != len(namen):
        fehler.append(f"{ort}: Feldnamen kommen doppelt vor")
    url = roh.get("url", "") or ""
    if url and (id_ != AUSBAU or url not in namen):
        fehler.append(f"{ort}: 'url' gibt es nur bei der Ausbaustufe und muss eines ihrer Felder sein")
    if len(fehler) > n0:
        return None
    spr.lerne_texte(roh.get("en"), {"titel": titel, "text": text})
    return Stufe(id_, titel.strip(), text.strip(), tuple(namen), tuple(neue), url, verfuegbar)


def parse(daten: Any, herkunft: str = "katalog_stufen") -> list[Faehigkeit]:
    """Prüft das geladene YAML und liefert die Fähigkeiten. Wirft KatalogFehler mit allen Befunden."""
    fehler: list[str] = []
    roh = daten.get("faehigkeiten") if isinstance(daten, dict) else None
    if not isinstance(roh, list) or not roh:
        raise KatalogFehler(f"{herkunft}: 'faehigkeiten' muss eine nichtleere Liste sein")
    erg: list[Faehigkeit] = []
    for nr, e in enumerate(roh, 1):
        if not isinstance(e, dict):
            fehler.append(f"{herkunft}: Eintrag {nr} muss ein Objekt sein")
            continue
        id_ = e.get("id")
        if not isinstance(id_, str) or not _ID.match(id_):
            fehler.append(f"{herkunft}: Eintrag {nr}: 'id' fehlt oder ist ungültig ({id_!r})")
            continue
        ort = f"{herkunft}: {id_}"
        n0 = len(fehler)
        texte = {}
        for name in ("titel", "kurz", "baustein"):
            wert = e.get(name)
            if not isinstance(wert, str) or not wert.strip():
                fehler.append(f"{ort}: '{name}' muss ein nichtleerer Text sein")
            else:
                texte[name] = wert.strip()
        aus = e.get("aus", False)
        if not isinstance(aus, bool):
            fehler.append(f"{ort}: 'aus' muss wahr oder falsch sein")
            aus = False
        stufen_roh = e.get("stufen")
        stufen: dict[str, Stufe] = {}
        if not isinstance(stufen_roh, dict) or not stufen_roh:
            fehler.append(f"{ort}: 'stufen' braucht mindestens grund oder ausbau")
        else:
            for sid, sroh in stufen_roh.items():
                if sid not in (GRUND, AUSBAU):
                    fehler.append(f"{ort}: unbekannte Stufe '{sid}' (erlaubt: {GRUND}, {AUSBAU}; aus ist die Option 'aus')")
                elif (s := _stufe(sroh, sid, ort, fehler)):
                    stufen[sid] = s
        if len(fehler) > n0:
            continue
        stufen = {s: stufen[s] for s in (GRUND, AUSBAU) if s in stufen}
        spr.lerne_texte(e.get("en"), {"titel": texte["titel"], "kurz": texte["kurz"]})
        f = Faehigkeit(id_, texte["titel"], texte["kurz"], texte["baustein"], stufen, aus)
        if not any(s.verfuegbar for s in stufen.values()):
            fehler.append(f"{ort}: mindestens eine Stufe muss verfügbar sein")
            continue
        erg.append(f)
    ids = [f.id for f in erg]
    for i in {x for x in ids if ids.count(x) > 1}:
        fehler.append(f"{herkunft}: id '{i}' kommt doppelt vor")
    if fehler:
        raise KatalogFehler("\n".join(fehler))
    return erg


def lade_datei(pfad: str | Path) -> list[Faehigkeit]:
    try:
        daten = yaml.safe_load(Path(pfad).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise KatalogFehler(f"{pfad}: nicht lesbar ({e})") from e
    return parse(daten, Path(pfad).name)


def verbinde(katalog: Katalog, faehigkeiten: Iterable[Faehigkeit]) -> None:
    """Hängt die Fähigkeiten an den Katalog. Felder, die der Baustein nicht hat, werden angelegt, wenn die Stufe sie
    beschreibt; sonst wird die Stufe um sie gekürzt. Fehlt der Baustein ganz, entfällt die Fähigkeit. Beides steht in
    `katalog.hinweise`, damit ein ersetzter Katalogeintrag (Plugin-Paket, `--katalog`) nicht still etwas verliert."""
    for f in faehigkeiten:
        if f.baustein not in katalog:
            katalog.hinweise.append(f"Fähigkeit '{f.id}' entfällt: der Baustein '{f.baustein}' ist nicht im Katalog")
            continue
        b = katalog[f.baustein]
        for s in f.stufen.values():
            vorhanden = {x.name for x in b.konfiguration}
            for neu in s.neue_felder:
                if neu.name not in vorhanden:
                    b.konfiguration.append(neu)
        vorhanden = {x.name for x in b.konfiguration}
        stufen = {}
        for sid, s in f.stufen.items():
            fehlt = [n for n in s.felder if n not in vorhanden]
            if fehlt:
                katalog.hinweise.append(
                    f"Fähigkeit '{f.id}': dem Baustein '{b.id}' ({b.herkunft}) fehlen die Felder {', '.join(fehlt)}; "
                    f"sie gelten nicht für die {STUFE_TITEL[sid]}"
                )
                s = replace(s, felder=tuple(n for n in s.felder if n in vorhanden),
                            url="" if s.url in fehlt else s.url)
            stufen[sid] = s
        katalog.faehigkeiten[f.id] = replace(f, stufen=stufen)


# ---------------------------------------------------------------- Wählen und anwenden


def stufen_als_text(daten: Mapping[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (daten or {}).items() if v is not None and str(v).strip()}


def waehle(
    katalog: Katalog, auswahl: Iterable[str], ziel: str, wunsch: Any = None,
) -> tuple[list[Wahl], list[str], list[str]]:
    """Die Stufe je Fähigkeit der gewählten Bausteine. `wunsch` ist `{fähigkeit: stufe}` (Antwortdatei, `--stufe`,
    Assistent); was fehlt, bekommt die Vorgabe der Bauart. Liefert die Wahlen, die Fehler und die Hinweise."""
    fehler: list[str] = []
    hinweise: list[str] = []
    if wunsch is None:
        wunsch = {}
    if not isinstance(wunsch, Mapping):
        fehler.append(spr._("Antworten: 'stufen' muss ein Objekt aus Fähigkeit und Stufe sein"))
        wunsch = {}
    wunsch = stufen_als_text(wunsch)
    gewaehlt = set(auswahl)
    for name in wunsch:
        if name not in katalog.faehigkeiten:
            fehler.append(spr._("Unbekannte Fähigkeit '{0}' bei den Stufen (bekannt: {1})", name, ", ".join(katalog.faehigkeiten)))
    wahlen: list[Wahl] = []
    for f in katalog.faehigkeiten.values():
        if f.baustein not in gewaehlt:
            if f.id in wunsch:
                hinweise.append(spr._(
                    "Die Stufe für {0} wird ignoriert: der Baustein '{1}' ist nicht gewählt.", _k(f.titel), f.baustein
                ))
            continue
        if f.id not in wunsch:
            wahlen.append(Wahl(f, f.vorgabe(ziel), True))
            continue
        stufe = wunsch[f.id].lower()
        grund = _warum_nicht(f, stufe)
        if grund:
            fehler.append(f"{_k(f.titel)}: {grund}")
        else:
            wahlen.append(Wahl(f, stufe, False))
    return wahlen, fehler, hinweise


def _warum_nicht(f: Faehigkeit, stufe: str) -> str:
    """Leer, wenn die Stufe wählbar ist, sonst der Grund in einem Satz."""
    moeglich = f.moegliche()
    if stufe not in STUFEN:
        return spr._("die Stufe '{0}' gibt es nicht (erlaubt: {1})", stufe, ", ".join(STUFEN))
    if stufe in moeglich:
        return ""
    waehlbar = spr._(" oder ").join(moeglich)
    if stufe == AUS:
        return spr._("lässt sich nicht ausschalten; wähle {0}", waehlbar)
    s = f.stufen.get(stufe)
    if s is None:
        return spr._("hat keine {0}; wähle {1}", STUFE_TITEL[stufe], waehlbar)
    return spr._("die {0} ({1}) gibt es noch nicht; wähle {2}", STUFE_TITEL[stufe], _k(s.titel), waehlbar)


def anwenden(
    katalog: Katalog, wahlen: list[Wahl], werte: dict[str, tuple[Any, bool, Any]], ziel: str,
) -> list[str]:
    """Wirkt die Wahl auf die Feldwerte (`werte`: Umgebungsvariable -> (Wert, geheim, Baustein)) und liefert die Hinweise.

    Felder einer Stufe, die nicht gilt, werden geleert und damit nicht geschrieben. Bei der Ausbaustufe bleibt die
    Variable mit der Adresse in der Umgebung stehen, auch leer, damit klar ist, wo sie hingehört."""
    hinweise: list[str] = []
    for w in wahlen:
        f = w.faehigkeit
        b = katalog[f.baustein]
        felder = {x.name: x for x in b.konfiguration}
        aktiv = set(f.stufen[w.stufe].felder) if w.stufe in f.stufen else set()
        for sid, s in f.stufen.items():
            for name in s.felder:
                if name in aktiv:
                    continue
                env = b.umgebungsname(felder[name])
                wert, geheim, baustein = werte.get(env, ("", False, b))
                if wert and str(wert) != str(felder[name].standard):
                    hinweise.append(spr._(
                        "{0}: Das Feld »{1}« gehört zur {2} und wird bei {3} nicht verwendet.",
                        _k(f.titel), _k(felder[name].titel), STUFE_TITEL[sid],
                        w.stufe_titel if w.stufe == AUS else spr._("der ") + w.stufe_titel,
                    ))
                werte[env] = ("", geheim, baustein)
        if w.stufe == AUSBAU and f.stufen[AUSBAU].url in felder:
            s = f.stufen[AUSBAU]
            env = b.umgebungsname(felder[s.url])
            w.url_umgebung = env
            w.url_gesetzt = bool(str(werte.get(env, ("", 0, 0))[0]).strip())
            if w.url_gesetzt:
                hinweise.append(spr._(
                    "{0}, Ausbaustufe: Der Hub fragt den Dienst unter {1}. Den Dienst selbst ({2}) "
                    "liefert der Installer noch nicht mit; er muss laufen und erreichbar sein.",
                    _k(f.titel), env, _k(s.titel),
                ))
            else:
                ohne = (spr._("Ohne eigenen Dienst wähle die Grundstufe.") if GRUND in f.moegliche()
                        else spr._("Eine Grundstufe ohne Dienst gibt es hier nicht."))
                hinweise.append(spr._(
                    "{0}, Ausbaustufe: Den Dienst ({1}) liefert der Installer noch nicht mit; trage "
                    "{2} selbst ein, in {3}. Solange die Adresse fehlt, gilt »{4}« als nicht eingerichtet. {5}",
                    _k(f.titel), _k(s.titel), env, spr._(EINTRAGEN_IN.get(ziel, ".env")), _k(f.titel), ohne,
                ))
    return hinweise


def zeilen(wahlen: Iterable[Wahl]) -> list[str]:
    """Die Wahl in Textzeilen für Kommandozeile, Textoberfläche und Anleitung."""
    return [w.zeile() for w in wahlen]


def beschreibe_katalog(katalog: Katalog) -> list[str]:
    """Die Fähigkeiten mit ihren Stufen und Vorgaben als Textzeilen (`--liste`)."""
    zeilen_: list[str] = []
    for f in katalog.faehigkeiten.values():
        stufen = ", ".join(
            f"{s.id}: {_k(s.titel)}" + ("" if s.verfuegbar else spr._(" (noch nicht vorhanden)"))
            for s in f.stufen.values()
        )
        zeilen_.append(
            f"{f.id:<10} [{f.baustein}] {_k(f.titel)}: {stufen}{', aus' if f.aus else ''}; "
            + spr._("Vorgabe Compose {0}, Kubernetes {1}", f.vorgabe("compose"), f.vorgabe("k8s"))
        )
    return zeilen_
