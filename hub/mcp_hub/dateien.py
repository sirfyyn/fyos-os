"""Dateien für Plugins: ein Verzeichnis als gemeinsame Ablage, mit Papierkorb und früheren Fassungen.

Apps und Agent teilen sich Dateien, ohne dass jedes Plugin eigenen Speicher erfindet. Die **Grundstufe** ist ein
Verzeichnis auf dem Rechner des Hubs (in Compose ein Volume, in Kubernetes ein PersistentVolumeClaim). Wer die Ablage
später auf einen Netzspeicher (WebDAV, oCIS, TrueNAS-Freigabe) legen will, ändert nur, was hinter ``quelle()`` steckt;
die Werkzeuge des Plugins ``dateien`` und alle Leser bleiben gleich.

**Eine Wurzel, nichts außerhalb.** Jeder Pfad ist relativ zur Wurzel und wird zuerst geprüft: kein ``..``, kein
Backslash, keine Steuerzeichen, kein Name unter dem reservierten Ordner ``.fyos``. Danach läuft der Weg Stück für Stück
durch: ein Symlink an irgendeiner Stelle wird abgelehnt (nicht aufgelöst), Symlinks in der Ablage erscheinen weder in
Listen noch in der Suche. Die Wurzel selbst darf ein Symlink oder Mountpunkt sein. Geschrieben wird atomar (erst eine
Zwischendatei unter ``.fyos/tmp``, dann ``rename``), eine Datei ist nie halb da.

**Größendeckel.** Eine Datei darf höchstens ``FYOS_DATEIEN_MAX_MB`` Megabyte groß sein (Vorgabe 25). Vor dem Schreiben
muss außerdem noch Platz auf dem Datenträger sein. Text liest ``lesen()`` höchstens ``TEXT_ZEICHEN_MAX`` Zeichen weit.

**Versionen.** Überschreibt ``schreiben(…, ueberschreiben=True)`` eine Datei, bleibt die alte Fassung als Version
erhalten (die letzten ``FYOS_DATEIEN_VERSIONEN``, Vorgabe 10; ``0`` schaltet sie ab). Versionen hängen am Pfad und
folgen einer verschobenen Datei oder einem verschobenen Ordner.

**Papierkorb.** ``loeschen()`` löscht nie endgültig: Datei oder Ordner wandern nach ``.fyos/papierkorb/<id>`` und lassen
sich mit ``wiederherstellen()`` zurückholen. Was länger als ``FYOS_DATEIEN_PAPIERKORB_TAGE`` Tage (Vorgabe 30) darin
liegt, räumt das nächste Löschen weg.

**Ein Schreiber.** Mehrere Hub-Replikate auf demselben Verzeichnis sind nicht vorgesehen; die Sperre gilt innerhalb
eines Prozesses. Der Hub läuft mit einer Replika.

**Dateiinhalt ist Fremdinhalt.** Wer ihn einem Modell zeigt, sagt dazu, dass darin keine Anweisungen stehen, denen zu
folgen ist (das Plugin ``dateien`` hängt diesen Hinweis an jede Textantwort).

**Fehler.** ``Fehler`` (ein ``ValueError``) ist falsche Eingabe oder ein Zustand, der sich mit anderer Eingabe ändert:
``NichtGefunden`` (404), ``Existiert`` (409), ``ZuGross`` (413). ``QuelleFehler`` (erbt von ``vorgaenge.QuelleFehler``):
die Ablage ist nicht nutzbar (nicht beschreibbar, Datenträger voll). ``NichtEingerichtet`` (ein ``QuelleFehler``, Status
501): es ist kein Verzeichnis eingetragen. Wie bei Terminen, Mails und Dokumenten liefert die Quelle „keine“ keine leere
Liste, sondern wirft.

**Umgebung** (bei jedem Aufruf gelesen):

* ``FYOS_DATEIEN``                  Verzeichnis der Ablage (wird angelegt, wenn es fehlt)
* ``FYOS_DATEIEN_MAX_MB``           größte Datei in Megabyte (Vorgabe 25)
* ``FYOS_DATEIEN_VERSIONEN``        wie viele frühere Fassungen je Datei (Vorgabe 10)
* ``FYOS_DATEIEN_PAPIERKORB_TAGE``  wie lange der Papierkorb behält (Vorgabe 30)

Ein Plugin kann das Verzeichnis auch in seiner Konfiguration nennen und mit ``verzeichnis_anmelden`` eintragen; das
geht der Umgebung vor.
"""

from __future__ import annotations

import base64
import codecs
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from mcp_hub import vorgaenge

#: Reservierter Ordner in der Wurzel: Papierkorb, Versionen, Zwischendateien. Nie in Listen, nie als Pfad nutzbar.
VERWALTUNG = ".fyos"
PFAD_MAX = 400
NAME_MAX = 200
VORGABE_MAX_MB = 25
VORGABE_VERSIONEN = 10
VORGABE_PAPIERKORB_TAGE = 30
#: So viele Zeichen Text liefert ``lesen()`` höchstens
TEXT_ZEICHEN_MAX = 200_000
#: Bilder bis zu dieser Größe liefert ``vorschau()`` (Basis-64 im Ergebnis)
VORSCHAU_MAX = 6 * 1024 * 1024
#: Einträge einer Liste (der Rest wird als ``gekuerzt`` gemeldet)
LISTE_MAX = 1000
#: Suche: so viele Treffer, so viele Dateien prüfen, so große Textdateien durchsuchen
SUCHE_TREFFER_MAX = 50
SUCHE_DATEIEN_MAX = 5000
SUCHE_TEXT_MAX = 1_000_000
ABFRAGE_MIN = 2
ABFRAGE_MAX = 200
#: Reserve auf dem Datenträger, die nach dem Schreiben bleiben muss
PLATZ_RESERVE = 20 * 1024 * 1024

_ID_PAPIERKORB = re.compile(r"^\d{9,12}-[0-9a-f]{6}$")
_ID_VERSION = re.compile(r"^\d{10,22}$")

#: Dateiendung → Medientyp. Eigene Tabelle vor ``mimetypes``: gleiche Antworten auf jedem Rechner.
_TYPEN = {
    ".txt": "text/plain", ".log": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown",
    ".csv": "text/csv", ".tsv": "text/tab-separated-values", ".json": "application/json",
    ".yaml": "application/yaml", ".yml": "application/yaml", ".toml": "application/toml", ".ini": "text/plain",
    ".xml": "application/xml", ".html": "text/html", ".htm": "text/html", ".css": "text/css",
    ".js": "text/javascript", ".mjs": "text/javascript", ".ts": "text/x-typescript", ".tsx": "text/x-typescript",
    ".py": "text/x-python", ".rs": "text/x-rust", ".go": "text/x-go", ".sh": "text/x-shellscript",
    ".sql": "text/x-sql", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif", ".bmp": "image/bmp", ".pdf": "application/pdf",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".mp4": "video/mp4",
    ".webm": "video/webm", ".mov": "video/quicktime", ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
}
_TEXT_ANWENDUNG = {
    "application/json", "application/yaml", "application/toml", "application/xml", "application/javascript",
    "image/svg+xml",
}
BILD_TYPEN = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp", "image/svg+xml")


class QuelleFehler(vorgaenge.QuelleFehler):
    """Die Ablage ist nicht nutzbar: nicht beschreibbar, Datenträger voll, Zugriff verweigert."""


class NichtEingerichtet(QuelleFehler):
    """Es ist kein Verzeichnis für die Dateien eingetragen."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text or (
            "Keine Dateiablage eingerichtet: FYOS_DATEIEN auf ein Verzeichnis setzen, das der Hub beschreiben darf "
            "(in Compose und Kubernetes ist das ein Volume)."
        ), 501)


class Fehler(ValueError):
    """Falsche Eingabe oder ein Zustand der Ablage, der der Eingabe widerspricht. ``status`` sagt dem REST-Weg, welcher."""

    status = 400
    kind = "bad_arguments"


class NichtGefunden(Fehler):
    status = 404
    kind = "not_found"


class Existiert(Fehler):
    status = 409
    kind = "existiert"


class ZuGross(Fehler):
    status = 413
    kind = "zu_gross"


# ── Pfade ────────────────────────────────────────────────────────────────────


def normalisiere(pfad: Any, *, wurzel_ok: bool = False) -> str:
    """Pfad als relative Zeichenkette mit ``/`` ohne Anfang und Ende. Lehnt alles ab, was aus der Ablage hinausführen
    oder in die Verwaltung greifen könnte. ``wurzel_ok``: der leere Pfad (die Wurzel selbst) ist erlaubt."""
    if pfad is None:
        pfad = ""
    if not isinstance(pfad, str):
        raise Fehler("pfad muss Text sein")
    if len(pfad) > PFAD_MAX:
        raise Fehler(f"pfad ist zu lang ({len(pfad)} Zeichen, höchstens {PFAD_MAX})")
    if any(ord(c) < 32 or ord(c) == 127 for c in pfad):
        raise Fehler("pfad enthält Steuerzeichen")
    if "\\" in pfad:
        raise Fehler("Backslash ist im Pfad nicht erlaubt (Trenner ist /)")
    teile: list[str] = []
    for t in pfad.split("/"):
        if t in ("", "."):
            continue
        if t == "..":
            raise Fehler("'..' ist im Pfad nicht erlaubt")
        if len(t) > NAME_MAX or len(t.encode("utf-8")) > 255:
            raise Fehler(f"ein Name im Pfad ist zu lang (höchstens {NAME_MAX} Zeichen)")
        teile.append(t)
    if teile and teile[0].lower() == VERWALTUNG:
        raise Fehler(f"{VERWALTUNG} ist für die Ablage reserviert")
    if not teile and not wurzel_ok:
        raise Fehler("pfad fehlt")
    return "/".join(teile)


def mime_fuer(name: str) -> str:
    """Medientyp nach der Endung des Namens (``application/octet-stream``, wenn unbekannt)."""
    ende = os.path.splitext(name)[1].lower()
    if ende in _TYPEN:
        return _TYPEN[ende]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def ist_text(probe: bytes, mime: str = "") -> bool:
    """Ist das Text? Nach dem Medientyp, sonst am Anfang des Inhalts: kein NUL-Byte und gültiges UTF-8."""
    if mime.startswith("text/") or mime in _TEXT_ANWENDUNG:
        return b"\x00" not in probe
    if b"\x00" in probe:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(probe, final=False)
    except UnicodeDecodeError:
        return False
    return True


def _eltern(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _schluessel(rel: str) -> str:
    return hashlib.sha256(rel.encode("utf-8")).hexdigest()[:24]


# ── Die Ablage ───────────────────────────────────────────────────────────────


class Verzeichnis:
    """Eine Ablage auf einem Verzeichnis. Alle Pfade sind relativ zur Wurzel (siehe ``normalisiere``)."""

    def __init__(
        self,
        wurzel: str | Path,
        *,
        max_bytes: int = VORGABE_MAX_MB * 1024 * 1024,
        versionen: int = VORGABE_VERSIONEN,
        papierkorb_tage: int = VORGABE_PAPIERKORB_TAGE,
    ) -> None:
        roh = Path(wurzel).expanduser()
        try:
            roh.mkdir(parents=True, exist_ok=True)
            self.wurzel = roh.resolve()
        except OSError as e:
            raise QuelleFehler(f"Die Dateiablage lässt sich nicht anlegen oder öffnen ({e.strerror or type(e).__name__})") from e
        if not self.wurzel.is_dir():
            raise QuelleFehler("Die Dateiablage ist kein Verzeichnis")
        self.max_bytes = max(1, int(max_bytes))
        self.versionen_max = max(0, int(versionen))
        self.papierkorb_tage = max(0, int(papierkorb_tage))
        self._sperre = threading.RLock()

    # -- Wege -----------------------------------------------------------------

    def _abs(self, rel: str) -> Path:
        """Pfad auf dem Datenträger. Ein Symlink an irgendeiner Stelle des Wegs wird abgelehnt, nicht aufgelöst."""
        p = self.wurzel
        for t in rel.split("/") if rel else []:
            p = p / t
            if p.is_symlink():
                raise Fehler("Verknüpfungen (Symlinks) folgt die Ablage nicht")
        return p

    def _verwaltung(self, *teile: str) -> Path:
        return self.wurzel.joinpath(VERWALTUNG, *teile)

    def _datei(self, rel: str) -> Path:
        p = self._abs(rel)
        if p.is_dir():
            raise Fehler(f"„{rel}“ ist ein Ordner, keine Datei")
        if not p.is_file():
            raise NichtGefunden(f"Es gibt keine Datei „{rel}“")
        return p

    def datei_pfad(self, pfad: Any) -> tuple[Path, str]:
        """Pfad einer vorhandenen Datei auf dem Datenträger (für Herunterladen) und ihr normalisierter Name."""
        rel = normalisiere(pfad)
        return self._datei(rel), rel

    def _eintrag(self, rel: str, st: os.stat_result, ordner: bool) -> dict[str, Any]:
        name = rel.rsplit("/", 1)[-1]
        return {
            "name": name,
            "pfad": rel,
            "art": "ordner" if ordner else "datei",
            "groesse": None if ordner else st.st_size,
            "geaendert": int(st.st_mtime),
            "typ": None if ordner else mime_fuer(name),
        }

    # -- Lesen ----------------------------------------------------------------

    def liste(self, pfad: Any = "") -> dict[str, Any]:
        """Inhalt eines Ordners, Ordner zuerst, dann nach Name. Ist ``pfad`` eine Datei, ist es ihr Ordner und die Datei
        steht unter ``auswahl``."""
        rel = normalisiere(pfad, wurzel_ok=True)
        auswahl = None
        p = self._abs(rel)
        if rel and p.is_file():
            auswahl, rel = rel, _eltern(rel)
            p = self._abs(rel)
        if not p.exists():
            raise NichtGefunden(f"Es gibt keinen Ordner „{rel}“")
        if not p.is_dir():
            raise Fehler(f"„{rel}“ ist kein Ordner")
        ordner: list[dict[str, Any]] = []
        dateien: list[dict[str, Any]] = []
        gesamt = 0
        with os.scandir(p) as it:
            for e in it:
                if e.is_symlink() or (not rel and e.name.lower() == VERWALTUNG):
                    continue
                try:
                    ist_ordner = e.is_dir(follow_symlinks=False)
                    if not ist_ordner and not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                gesamt += 1
                (ordner if ist_ordner else dateien).append(self._eintrag(f"{rel}/{e.name}" if rel else e.name, st, ist_ordner))
        ordner.sort(key=lambda x: x["name"].casefold())
        dateien.sort(key=lambda x: x["name"].casefold())
        eintraege = (ordner + dateien)[:LISTE_MAX]
        return {
            "pfad": rel,
            "eltern": _eltern(rel) if rel else None,
            "auswahl": auswahl,
            "eintraege": eintraege,
            "gesamt": gesamt,
            "gekuerzt": gesamt > len(eintraege),
        }

    def info(self, pfad: Any) -> dict[str, Any]:
        """Eintrag einer Datei oder eines Ordners (Name, Größe, Zeit, Typ)."""
        rel = normalisiere(pfad)
        p = self._abs(rel)
        if not p.exists():
            raise NichtGefunden(f"Es gibt „{rel}“ nicht")
        return self._eintrag(rel, p.stat(), p.is_dir())

    def lesen(self, pfad: Any, *, version: Any = None, max_zeichen: int = TEXT_ZEICHEN_MAX) -> dict[str, Any]:
        """Eine Datei: Text (bis ``max_zeichen`` Zeichen) oder bei Binärem nur die Angaben. ``version`` liest eine
        frühere Fassung (Kennung aus ``versionen()``)."""
        rel = normalisiere(pfad)
        p = self._version_pfad(rel, version) if version else self._datei(rel)
        st = p.stat()
        mime = mime_fuer(rel)
        out: dict[str, Any] = {
            "pfad": rel, "name": rel.rsplit("/", 1)[-1], "groesse": st.st_size, "geaendert": int(st.st_mtime),
            "typ": mime, "version": str(version) if version else None,
        }
        try:
            fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as e:
            raise QuelleFehler(f"Die Datei lässt sich nicht öffnen ({e.strerror or type(e).__name__})") from e
        with os.fdopen(fd, "rb") as f:
            kopf = f.read(8192)
            if not ist_text(kopf, mime):
                return {**out, "art": "binaer", "text": None, "gekuerzt": False}
            roh = kopf + f.read(max(0, max_zeichen * 4 + 4 - len(kopf)))
        text = roh.decode("utf-8", errors="replace")
        return {**out, "art": "text", "text": text[:max_zeichen], "gekuerzt": st.st_size > len(roh) or len(text) > max_zeichen}

    def vorschau(self, pfad: Any) -> dict[str, Any]:
        """Bytes eines Bildes (bis ``VORSCHAU_MAX``) für die Anzeige in einer App: ``{typ, groesse, daten_base64}``."""
        rel = normalisiere(pfad)
        p = self._datei(rel)
        mime = mime_fuer(rel)
        if mime not in BILD_TYPEN:
            raise Fehler(f"Für „{rel}“ gibt es keine Bildvorschau ({mime})")
        gross = p.stat().st_size
        if gross > VORSCHAU_MAX:
            raise ZuGross(f"Das Bild ist für die Vorschau zu groß ({gross // 1024} KB, höchstens {VORSCHAU_MAX // 1024} KB)")
        try:
            fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as f:
                roh = f.read(VORSCHAU_MAX + 1)
        except OSError as e:
            raise QuelleFehler(f"Die Datei lässt sich nicht öffnen ({e.strerror or type(e).__name__})") from e
        return {"pfad": rel, "typ": mime, "groesse": len(roh), "daten_base64": base64.b64encode(roh).decode("ascii")}

    # -- Schreiben ------------------------------------------------------------

    def _platz_pruefen(self, bytes_: int) -> None:
        try:
            frei = shutil.disk_usage(self.wurzel).free
        except OSError:
            return
        if frei < bytes_ + PLATZ_RESERVE:
            raise QuelleFehler("Auf dem Datenträger der Dateiablage ist nicht genug Platz")

    def _mkdir(self, ordner: Path) -> None:
        try:
            ordner.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError) as e:
            raise Fehler("Ein Teil des Pfads ist eine Datei, kein Ordner") from e
        except OSError as e:
            raise QuelleFehler(f"Der Ordner lässt sich nicht anlegen ({e.strerror or type(e).__name__})") from e

    def schreiben(self, pfad: Any, daten: bytes, *, ueberschreiben: bool = False, trocken: bool = False) -> dict[str, Any]:
        """Legt eine Datei an oder ersetzt sie (``ueberschreiben``; die alte Fassung bleibt als Version). Fehlende Ordner
        im Pfad entstehen mit. ``trocken``: nur prüfen und sagen, was geschähe."""
        rel = normalisiere(pfad)
        if not isinstance(daten, (bytes, bytearray)):
            raise Fehler("daten müssen Bytes sein")
        if len(daten) > self.max_bytes:
            raise ZuGross(f"Die Datei ist zu groß ({len(daten) // 1024} KB, höchstens {self.max_bytes // 1024} KB)")
        ziel = self._abs(rel)
        vorhanden = os.path.lexists(ziel)
        if vorhanden and ziel.is_dir():
            raise Fehler(f"„{rel}“ ist ein Ordner")
        if vorhanden and not ueberschreiben:
            raise Existiert(f"„{rel}“ gibt es schon — mit ueberschreiben: true kommt eine neue Fassung, die alte bleibt als Version")
        plan = {
            "pfad": rel, "groesse": len(daten), "neu": not vorhanden, "ersetzt": vorhanden,
            "version_gesichert": vorhanden and self.versionen_max > 0,
        }
        if trocken:
            return plan
        self._platz_pruefen(len(daten))
        with self._sperre:
            self._mkdir(ziel.parent)
            if os.path.lexists(ziel) and ziel.is_dir():
                raise Fehler(f"„{rel}“ ist ein Ordner")
            if os.path.lexists(ziel):
                self._version_sichern(rel, ziel)
            tmp = self._zwischendatei()
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                with os.fdopen(fd, "wb") as f:
                    f.write(daten)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, ziel)
            except OSError as e:
                raise QuelleFehler(f"Die Datei lässt sich nicht schreiben ({e.strerror or type(e).__name__})") from e
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return plan

    def ordner_anlegen(self, pfad: Any, *, trocken: bool = False) -> dict[str, Any]:
        rel = normalisiere(pfad)
        p = self._abs(rel)
        if os.path.lexists(p):
            if not p.is_dir():
                raise Existiert(f"„{rel}“ ist eine Datei")
            return {"pfad": rel, "neu": False}
        if not trocken:
            with self._sperre:
                self._mkdir(p)
        return {"pfad": rel, "neu": True}

    def _zwischendatei(self) -> Path:
        ordner = self._verwaltung("tmp")
        self._mkdir(ordner)
        return ordner / f"{time.time_ns()}-{secrets.token_hex(4)}"

    def verschieben(self, von: Any, nach: Any, *, trocken: bool = False) -> dict[str, Any]:
        """Verschiebt oder benennt um (Datei oder Ordner). ``nach`` darf es noch nicht geben."""
        rv, rn = normalisiere(von), normalisiere(nach)
        if rv == rn:
            raise Fehler("von und nach sind derselbe Pfad")
        quelle = self._abs(rv)
        if not os.path.lexists(quelle):
            raise NichtGefunden(f"Es gibt „{rv}“ nicht")
        ordner = quelle.is_dir()
        if ordner and rn.startswith(rv + "/"):
            raise Fehler("Ein Ordner lässt sich nicht in sich selbst verschieben")
        ziel = self._abs(rn)
        if os.path.lexists(ziel):
            raise Existiert(f"„{rn}“ gibt es schon")
        plan = {"von": rv, "nach": rn, "art": "ordner" if ordner else "datei"}
        if trocken:
            return plan
        with self._sperre:
            self._mkdir(ziel.parent)
            if os.path.lexists(ziel):
                raise Existiert(f"„{rn}“ gibt es schon")
            try:
                os.rename(quelle, ziel)
            except OSError as e:
                raise QuelleFehler(f"Verschieben geht nicht ({e.strerror or type(e).__name__})") from e
            self._versionen_folgen(rv, rn, ordner)
        return plan

    def loeschen(self, pfad: Any, *, trocken: bool = False) -> dict[str, Any]:
        """Legt eine Datei oder einen Ordner in den Papierkorb (``wiederherstellen`` holt sie zurück)."""
        rel = normalisiere(pfad)
        p = self._abs(rel)
        if not os.path.lexists(p):
            raise NichtGefunden(f"Es gibt „{rel}“ nicht")
        ordner = p.is_dir()
        plan: dict[str, Any] = {"pfad": rel, "art": "ordner" if ordner else "datei"}
        if ordner:
            plan["dateien"] = sum(len(fs) for _d, _o, fs in _begrenzt_gehen(p, 10_000))
        if trocken:
            return plan
        with self._sperre:
            self._papierkorb_leeren()
            pid = f"{int(time.time())}-{secrets.token_hex(3)}"
            korb = self._verwaltung("papierkorb", pid)
            self._mkdir(korb)
            try:
                os.rename(p, korb / "inhalt")
                (korb / "meta.json").write_text(
                    json.dumps({"pfad": rel, "art": plan["art"], "geloescht": int(time.time())}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as e:
                shutil.rmtree(korb, ignore_errors=True)
                raise QuelleFehler(f"Löschen geht nicht ({e.strerror or type(e).__name__})") from e
        return {**plan, "papierkorb_id": pid}

    # -- Papierkorb -----------------------------------------------------------

    def papierkorb(self) -> list[dict[str, Any]]:
        """Was im Papierkorb liegt, zuletzt Gelöschtes zuerst."""
        wurzel = self._verwaltung("papierkorb")
        if not wurzel.is_dir():
            return []
        out = []
        for d in wurzel.iterdir():
            if not _ID_PAPIERKORB.match(d.name) or not os.path.lexists(d / "inhalt"):
                continue
            meta = _json(d / "meta.json")
            inhalt = d / "inhalt"
            try:
                groesse = inhalt.stat().st_size if inhalt.is_file() else None
            except OSError:
                groesse = None
            pfad = str(meta.get("pfad") or d.name)
            out.append({
                "id": d.name, "pfad": pfad, "name": pfad.rsplit("/", 1)[-1], "art": meta.get("art") or "datei",
                "geloescht": int(meta.get("geloescht") or d.name.split("-", 1)[0]), "groesse": groesse,
            })
        out.sort(key=lambda x: x["geloescht"], reverse=True)
        return out

    def wiederherstellen(self, id: Any, nach: Any = None, *, trocken: bool = False) -> dict[str, Any]:  # noqa: A002
        """Holt etwas aus dem Papierkorb zurück, an den alten Platz oder nach ``nach``. Den Platz darf es noch nicht geben."""
        if not isinstance(id, str) or not _ID_PAPIERKORB.match(id):
            raise Fehler("id ist keine Kennung aus dem Papierkorb")
        korb = self._verwaltung("papierkorb", id)
        inhalt = korb / "inhalt"
        if not os.path.lexists(inhalt):
            raise NichtGefunden(f"Im Papierkorb gibt es „{id}“ nicht")
        meta = _json(korb / "meta.json")
        rel = normalisiere(nach if nach else meta.get("pfad"))
        ziel = self._abs(rel)
        if os.path.lexists(ziel):
            raise Existiert(f"„{rel}“ gibt es schon — mit nach: einen anderen Platz nennen")
        plan = {"id": id, "pfad": rel, "art": meta.get("art") or "datei"}
        if trocken:
            return plan
        with self._sperre:
            self._mkdir(ziel.parent)
            if os.path.lexists(ziel):
                raise Existiert(f"„{rel}“ gibt es schon")
            try:
                os.rename(inhalt, ziel)
            except OSError as e:
                raise QuelleFehler(f"Wiederherstellen geht nicht ({e.strerror or type(e).__name__})") from e
            shutil.rmtree(korb, ignore_errors=True)
        return plan

    def _papierkorb_leeren(self) -> None:
        if not self.papierkorb_tage:
            return
        wurzel = self._verwaltung("papierkorb")
        if not wurzel.is_dir():
            return
        grenze = time.time() - self.papierkorb_tage * 86400
        for d in wurzel.iterdir():
            if not _ID_PAPIERKORB.match(d.name) or int(d.name.split("-", 1)[0]) >= grenze:
                continue
            pfad = _json(d / "meta.json").get("pfad")
            shutil.rmtree(d, ignore_errors=True)
            if isinstance(pfad, str) and pfad and not os.path.lexists(self.wurzel / pfad):
                shutil.rmtree(self._verwaltung("versionen", _schluessel(pfad)), ignore_errors=True)

    # -- Versionen ------------------------------------------------------------

    def _version_ordner(self, rel: str) -> Path:
        return self._verwaltung("versionen", _schluessel(rel))

    def _version_sichern(self, rel: str, ziel: Path) -> None:
        if not self.versionen_max:
            return
        ordner = self._version_ordner(rel)
        self._mkdir(ordner)
        try:
            shutil.copy2(ziel, ordner / str(time.time_ns()))
        except OSError as e:
            raise QuelleFehler(f"Die alte Fassung lässt sich nicht sichern ({e.strerror or type(e).__name__})") from e
        alle = sorted((f for f in ordner.iterdir() if _ID_VERSION.match(f.name)), key=lambda f: int(f.name))
        for alt in alle[: max(0, len(alle) - self.versionen_max)]:
            try:
                alt.unlink()
            except OSError:
                pass

    def _versionen_folgen(self, von: str, nach: str, ordner: bool) -> None:
        """Eine verschobene Datei (oder jede Datei eines verschobenen Ordners) nimmt ihre Versionen mit."""
        paare = [(von, nach)]
        if ordner:
            ziel = self.wurzel / nach
            paare = []
            for wurzel, _ds, fs in _begrenzt_gehen(ziel, 10_000):
                for f in fs:
                    rel_neu = Path(wurzel, f).relative_to(self.wurzel).as_posix()
                    paare.append((von + rel_neu[len(nach):], rel_neu))
        for alt, neu in paare:
            quelle, ziel = self._version_ordner(alt), self._version_ordner(neu)
            if quelle.is_dir() and not ziel.exists():
                try:
                    ziel.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(quelle, ziel)
                except OSError:
                    pass

    def _version_pfad(self, rel: str, version: Any) -> Path:
        if not isinstance(version, (str, int)) or not _ID_VERSION.match(str(version)):
            raise Fehler("version ist keine Kennung aus versionen()")
        p = self._version_ordner(rel) / str(version)
        if not p.is_file():
            raise NichtGefunden(f"Zu „{rel}“ gibt es die Version {version} nicht")
        return p

    def versionen(self, pfad: Any) -> list[dict[str, Any]]:
        """Frühere Fassungen einer Datei, neueste zuerst."""
        rel = normalisiere(pfad)
        ordner = self._version_ordner(rel)
        if not ordner.is_dir():
            return []
        out = []
        for f in ordner.iterdir():
            if not _ID_VERSION.match(f.name):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"version": f.name, "groesse": st.st_size, "zeit": int(int(f.name) / 1e9)})
        out.sort(key=lambda x: int(x["version"]), reverse=True)
        return out

    def version_zurueck(self, pfad: Any, version: Any, *, trocken: bool = False) -> dict[str, Any]:
        """Setzt eine frühere Fassung als aktuelle ein; die jetzige bleibt ihrerseits als Version erhalten."""
        rel = normalisiere(pfad)
        p = self._version_pfad(rel, version)
        daten = p.read_bytes()
        plan = self.schreiben(rel, daten, ueberschreiben=True, trocken=True)
        if not trocken:
            self.schreiben(rel, daten, ueberschreiben=True)
        return {**plan, "version": str(version)}

    # -- Suchen ---------------------------------------------------------------

    def suchen(self, abfrage: Any, pfad: Any = "", *, inhalt: bool = True, anzahl: int = 20) -> dict[str, Any]:
        """Dateien und Ordner nach Namen finden, bei Text auch im Inhalt. Alle Wörter der Abfrage müssen vorkommen,
        im Pfad oder im Text (Groß- und Kleinschreibung gilt nicht)."""
        if not isinstance(abfrage, str):
            raise Fehler("abfrage muss Text sein")
        woerter = abfrage.casefold().split()
        text = " ".join(woerter)
        if len(text) < ABFRAGE_MIN:
            raise Fehler(f"abfrage ist zu kurz (mindestens {ABFRAGE_MIN} Zeichen)")
        if len(text) > ABFRAGE_MAX:
            raise Fehler(f"abfrage ist zu lang (höchstens {ABFRAGE_MAX} Zeichen)")
        anzahl = max(1, min(int(anzahl), SUCHE_TREFFER_MAX))
        start_rel = normalisiere(pfad, wurzel_ok=True)
        start = self._abs(start_rel)
        if not start.is_dir():
            raise NichtGefunden(f"Es gibt keinen Ordner „{start_rel}“")
        treffer: list[dict[str, Any]] = []
        geprueft = 0
        gekuerzt = False
        for wurzel, ordner_namen, datei_namen in os.walk(start, followlinks=False):
            rel_wurzel = Path(wurzel).relative_to(self.wurzel).as_posix()
            rel_wurzel = "" if rel_wurzel == "." else rel_wurzel
            ordner_namen[:] = sorted(
                (d for d in ordner_namen
                 if not os.path.islink(os.path.join(wurzel, d)) and not (not rel_wurzel and d.lower() == VERWALTUNG)),
                key=str.casefold,
            )
            for name, ist_ordner in [(d, True) for d in ordner_namen] + [(f, False) for f in sorted(datei_namen, key=str.casefold)]:
                voll = os.path.join(wurzel, name)
                if os.path.islink(voll):
                    continue
                geprueft += 1
                rel = f"{rel_wurzel}/{name}" if rel_wurzel else name
                if all(w in rel.casefold() for w in woerter):
                    st = os.stat(voll, follow_symlinks=False)
                    treffer.append({**self._eintrag(rel, st, ist_ordner), "treffer": "name", "auszug": None, "zeile": None})
                elif inhalt and not ist_ordner:
                    gefunden = self._im_text(voll, rel, woerter)
                    if gefunden:
                        treffer.append(gefunden)
                if len(treffer) >= anzahl or geprueft >= SUCHE_DATEIEN_MAX:
                    gekuerzt = True
                    break
            if gekuerzt:
                break
        return {"abfrage": text, "pfad": start_rel, "treffer": treffer, "geprueft": geprueft, "gekuerzt": gekuerzt}

    def _im_text(self, voll: str, rel: str, woerter: list[str]) -> dict[str, Any] | None:
        try:
            st = os.stat(voll, follow_symlinks=False)
            if not stat_ist_datei(st) or st.st_size > SUCHE_TEXT_MAX:
                return None
            mime = mime_fuer(rel)
            if mime in BILD_TYPEN[:-1] or mime.startswith(("audio/", "video/")) or mime in ("application/pdf", "application/zip"):
                return None
            fd = os.open(voll, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as f:
                roh = f.read(SUCHE_TEXT_MAX + 1)
        except OSError:
            return None
        if not ist_text(roh[:8192], mime):
            return None
        text = roh.decode("utf-8", errors="replace")
        klein = text.casefold()
        # Alle Wörter müssen irgendwo vorkommen, im Namen oder im Text (Name und Inhalt zählen zusammen)
        if not all(w in klein or w in rel.casefold() for w in woerter):
            return None
        stelle = next((klein.find(w) for w in woerter if w in klein), 0)
        zeile_nr = text.count("\n", 0, stelle) + 1
        anfang = text.rfind("\n", 0, stelle) + 1
        ende = text.find("\n", stelle)
        zeile = text[anfang: ende if ende != -1 else len(text)].strip()
        return {
            **self._eintrag(rel, st, False), "treffer": "inhalt",
            "auszug": zeile[:200] + ("…" if len(zeile) > 200 else ""), "zeile": zeile_nr,
        }

    # -- Zustand --------------------------------------------------------------

    def zustand(self) -> dict[str, Any]:
        try:
            frei = shutil.disk_usage(self.wurzel).free
        except OSError:
            frei = None
        return {
            "beschreibbar": os.access(self.wurzel, os.W_OK),
            "frei_mb": None if frei is None else int(frei // (1024 * 1024)),
            "max_mb": self.max_bytes // (1024 * 1024) or 1,
            "versionen": self.versionen_max,
            "papierkorb_tage": self.papierkorb_tage,
        }


def stat_ist_datei(st: os.stat_result) -> bool:
    import stat as _stat  # noqa: PLC0415

    return _stat.S_ISREG(st.st_mode)


def _json(pfad: Path) -> dict[str, Any]:
    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _begrenzt_gehen(start: Path, grenze: int):
    """``os.walk`` ohne Symlinks, das nach ``grenze`` Dateien aufhört."""
    n = 0
    for wurzel, ordner, dateien in os.walk(start, followlinks=False):
        ordner[:] = [d for d in ordner if not os.path.islink(os.path.join(wurzel, d))]
        dateien = [f for f in dateien if not os.path.islink(os.path.join(wurzel, f))]
        yield wurzel, ordner, dateien
        n += len(dateien)
        if n >= grenze:
            return


# ── Quelle ───────────────────────────────────────────────────────────────────

_sperre = threading.Lock()
_angemeldet: str | None = None
_verzeichnisse: dict[tuple[str, int, int, int], Verzeichnis] = {}


def verzeichnis_anmelden(pfad: str | Path | None) -> None:
    """Ein Plugin trägt das Verzeichnis aus seiner Konfiguration ein; es geht der Umgebung vor. ``None`` meldet ab."""
    global _angemeldet
    with _sperre:
        _angemeldet = str(pfad).strip() if pfad and str(pfad).strip() else None


def angemeldetes_verzeichnis() -> str | None:
    with _sperre:
        return _angemeldet


def _zahl(name: str, vorgabe: int) -> int:
    try:
        wert = int(os.getenv(name, "").strip())
    except ValueError:
        return vorgabe
    return wert if wert >= 0 else vorgabe


def quelle() -> Verzeichnis:
    """Die Ablage dieser Installation. Fragt bei jedem Aufruf neu (billig); wirft ``NichtEingerichtet``, wenn kein
    Verzeichnis eingetragen ist, und ``QuelleFehler``, wenn es sich nicht öffnen lässt."""
    pfad = angemeldetes_verzeichnis() or os.getenv("FYOS_DATEIEN", "").strip()
    if not pfad:
        raise NichtEingerichtet()
    mb = max(1, _zahl("FYOS_DATEIEN_MAX_MB", VORGABE_MAX_MB))
    versionen = _zahl("FYOS_DATEIEN_VERSIONEN", VORGABE_VERSIONEN)
    tage = _zahl("FYOS_DATEIEN_PAPIERKORB_TAGE", VORGABE_PAPIERKORB_TAGE)
    schluessel = (pfad, mb, versionen, tage)
    with _sperre:
        v = _verzeichnisse.get(schluessel)
        if v is None:
            v = _verzeichnisse[schluessel] = Verzeichnis(
                pfad, max_bytes=mb * 1024 * 1024, versionen=versionen, papierkorb_tage=tage
            )
        return v
