"""desktop — der Hyprland-Desktop eines Rechners als Teil von FYOS: Fenster sehen, Programme starten, Bildschirm ansehen.

Das Plugin spricht mit dem Dienst ``fyos-oeffnen`` auf dem Desktop-Rechner (dieselbe Gegenstelle wie „Öffnen mit“ in
``dateien``, siehe ``mcp_hub/oeffnen.py``). Damit sieht der Agent, was auf dem Desktop des Rechners offen ist, und kann nach
Bestätigung etwas starten, nach vorn holen oder schließen. Der Dienst nimmt nie einen freien Befehl an: gestartet wird
nur, was in seiner Konfiguration unter ``starter`` steht.

Werkzeuge (``desktop.<name>``):
    lage       Arbeitsfläche, Bildschirm (Größe, Takt, Skala), Zahl der Fenster, Modus (mac | gross)
    fenster    offene Fenster mit Adresse, Klasse, Titel, Arbeitsfläche
    starter    Programme, die der Hub starten darf
    bild       Bildschirmfoto (klein, PNG in Basis 64)
    starten    einen Starter ausführen
    fokus      ein Fenster nach vorn holen
    schliessen ein Fenster schließen (es bittet sich selbst zu schließen)
    eingabe    Stand der Freigabe für Computer Use (frei oder gesperrt, Rest in Sekunden)
    uebernehmen der Mensch übernimmt den Desktop des Agenten (der Agent ruht) oder gibt ihn zurück
    klick      auf einen Punkt des Bildschirmfotos klicken (nur mit Freigabe)
    tippen     Text tippen (nur mit Freigabe)
    taste      Taste oder Kombination drücken, Zusatz nur ctrl und shift (nur mit Freigabe)
    scrollen   Mausrad drehen (nur mit Freigabe)

Alles Schreibende folgt dem Vertrag aus ``docs/ERWEITERN.md`` §2.8: ``__dry_run__`` zeigt den Plan, ein echter Lauf
braucht ``bestaetigt: true``. Ausnahme ist die Eingabe (klick, tippen, taste, scrollen): sie hat eine eigene Schranke. Der
Dienst führt sie nur aus, solange ein Mensch am Rechner die Freigabe gesetzt hat (zehn Minuten, rote Anzeige in der Leiste);
ohne sie antwortet das Werkzeug „gesperrt“. Kein Werkzeug gibt frei: das kann nur, wer am Rechner sitzt.

Jedes Werkzeug nimmt ``ziel``: ``mensch`` (Vorgabe) ist der Desktop des Menschen, ``agent`` ist der eigene, kopflose Desktop des
Agenten (sway als eigener Nutzer). Dort gilt keine Freigabe; übernimmt der Mensch, ruht der Agent (Antwort „gesperrt“). Ein Fenster
des Agenten-Desktops trägt eine Adresse der Form ``g5``; wer nur die Adresse nennt, trifft damit das richtige Ziel.

Konfiguration (Plugin ``desktop``)::

    config:
      gegenstelle: "http://rechner:18445"      # oder FYOS_OEFFNEN_GEGENSTELLE
      token_env: FYOS_OEFFNEN_TOKEN          # Vorgabe; das Token steht nie in der Konfiguration
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .. import oeffnen
from ..plugin import HubPlugin, ResourceDescriptor, ToolDescriptor, build_dry_run_result, is_dry_run
from . import _arbeit, _dinge, _identitaet
from ._oberflaeche import oberflaeche

log = logging.getLogger(__name__)

NICHT_BESTAETIGT = "Das ändert den Desktop: erst mit `__dry_run__: true` den Plan ansehen, dann mit bestaetigt: true ausführen."
ADRESSE = re.compile(r"^(0x[0-9a-f]{1,16}|g[0-9]{1,9})$")  # 0x… auf dem Desktop des Menschen, g… auf dem Desktop des Agenten
EINGABE = ("klick", "tippen", "taste", "scrollen")
BILD_GRENZE = 2_000_000
UI_URI = "ui://fyos/desktop.html"
UI_DATEI = "desktop.html"
DING_TYP = "desktop-fenster"

_identitaet.registriere_app(
    "desktop",
    {
        "titel": "Desktop",
        "untertitel": "Fenster, Programme und Bildschirm des Arbeitsrechners",
        "symbol": "monitor",
        "ton": 215,
        "kategorie": "System",
    },
    datei=UI_DATEI,
    hauptwerkzeug="desktop__zeigen",
    art="anwendung",
)
# Ein offenes Fenster des Desktops ist ein Ding: man zieht es auf eine andere App oder auf den Agenten, ohne dass etwas geschieht,
# bis jemand es bestätigt. (Der Typ heißt nicht „fenster“: das ist in der Shell schon die Art, ein App-Fenster zu ziehen.)
_dinge.registriere_ding(DING_TYP, "Desktop-Fenster", flaeche="desktop", lesen="desktop.fenster_lesen", id_argument="adresse", felder=("klasse", "titel"))


ZIEL = {"enum": ["mensch", "agent"], "description": "mensch = Desktop des Menschen (Vorgabe), agent = eigener Desktop des Agenten (ohne Freigabe; ruht, wenn der Mensch übernommen hat)"}
SKALA = {"type": "number", "minimum": 0.1, "maximum": 1, "description": "Skala des Bildschirmfotos, auf dem x und y gemessen sind (wie bei desktop.bild, Vorgabe 0.3)"}
KOORD = {"type": "number", "minimum": 0, "maximum": 20000}


def eingabe_werkzeuge() -> list[ToolDescriptor]:
    """Die Werkzeuge für Computer Use: kein Plan nötig, die Schranke ist die Freigabe am Rechner; `__dry_run__` zeigt nur, was sie täten."""

    def w(name: str, titel: str, beschreibung: str, eigenschaften: dict, pflicht: list[str]) -> ToolDescriptor:
        return ToolDescriptor(
            name=name, title=titel, tags=["desktop", "exec"],
            description=beschreibung + " Auf dem Desktop des Menschen (ziel mensch) läuft es nur, solange ein Mensch am Rechner Computer Use freigegeben hat "
                        "(sonst „gesperrt“); auf dem Desktop des Agenten (ziel agent) frei, außer der Mensch hat übernommen. "
                        "Mit `__dry_run__: true` kommt nur die Beschreibung der Aktion.",
            input_schema={"type": "object", "properties": {"ziel": ZIEL, **eigenschaften}, "required": pflicht, "additionalProperties": False},
        )

    return [
        w("klick", "Desktop: klicken", "Klickt auf den Punkt (x, y) eines Bildschirmfotos, das mit derselben skala gemacht wurde (desktop.bild).",
          {"x": KOORD, "y": KOORD, "skala": SKALA, "taste": {"enum": ["links", "rechts", "mitte"]}, "doppelt": {"type": "boolean"}}, ["x", "y"]),
        w("tippen", "Desktop: tippen", "Tippt Text in das Fenster mit dem Fokus (höchstens 500 Zeichen, Zeilenumbruch drückt Return).",
          {"text": {"type": "string", "minLength": 1, "maxLength": 500}}, ["text"]),
        w("taste", "Desktop: Taste drücken", "Drückt eine Taste oder Kombination mit ctrl und/oder shift, etwa ctrl+l, Return, shift+Tab, F5. "
          "Kein alt, kein super.", {"kombi": {"type": "string", "maxLength": 40}}, ["kombi"]),
        w("scrollen", "Desktop: scrollen", "Dreht das Mausrad (dy negativ = nach oben, höchstens 20 Rasten); mit x und y erst dorthin zeigen.",
          {"dy": {"type": "integer", "minimum": -20, "maximum": 20}, "dx": {"type": "integer", "minimum": -20, "maximum": 20},
           "x": KOORD, "y": KOORD, "skala": SKALA}, []),
    ]


class DesktopPlugin(HubPlugin):
    name = "desktop"
    description = "Desktop eines Rechners: offene Fenster, Starter, Bildschirmfoto; Starten, Fokus und Schließen nach Bestätigung."
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.config = dict(config or {})
        self._gegenstelle: tuple[tuple[str, str], oeffnen.Gegenstelle] | None = None
        ui = self.config.get("ui_verzeichnis")
        self._ui_verzeichnis = ui if ui else None

    def register(self) -> None:
        """Nichts anzumelden: die Gegenstelle wird erst beim ersten Aufruf aus Konfiguration und Umgebung gelesen."""

    def health(self) -> dict[str, Any]:
        try:
            d = self._gegenstelle_holen().anfrage("GET", "/lage")
        except oeffnen.NichtEingerichtet:
            return {"ok": True, "status": "nicht eingerichtet", "eingerichtet": False}
        except oeffnen.OeffnenFehler as e:
            return {"ok": False, "status": "unhealthy", "reason": str(e)[:200]}
        return {"ok": True, "status": "healthy", "eingerichtet": True, "modus": d.get("modus"), "fenster": d.get("fenster")}

    # ── Gegenstelle ──────────────────────────────────────────────────────────
    def _gegenstelle_holen(self) -> oeffnen.Gegenstelle:
        """Die Gegenstelle aus Konfiguration und Umgebung; bleibt zwischen Aufrufen erhalten."""
        try:
            g = oeffnen.aus_konfiguration(self.config)
        except oeffnen.NichtEingerichtet as e:
            raise oeffnen.NichtEingerichtet(str(e).replace("„Öffnen mit“", "Der Desktop")) from None
        if self._gegenstelle and self._gegenstelle[0] == g.schluessel:
            return self._gegenstelle[1]
        self._gegenstelle = (g.schluessel, g)
        return g

    # ── Beschreibung ─────────────────────────────────────────────────────────
    def describe_tools(self) -> list[ToolDescriptor]:
        bestaetigt = {"type": "boolean", "description": "Echter Lauf: vorher den Plan (`__dry_run__`) ansehen und bestätigen lassen"}
        adresse = {"type": "string", "pattern": "^(0x[0-9a-f]{1,16}|g[0-9]{1,9})$", "description": "Fensteradresse aus desktop.fenster, etwa 0x6491740897c0 (g5 auf dem Desktop des Agenten)"}

        def werkzeug(name: str, titel: str, beschreibung: str, eigenschaften: dict, pflicht: list[str], tags: list[str]):
            return ToolDescriptor(
                name=name, title=titel, description=beschreibung,
                input_schema={"type": "object", "properties": {"ziel": ZIEL, **eigenschaften}, "required": pflicht, "additionalProperties": False},
                tags=["desktop", "flaeche", *tags], meta=_arbeit.meta(UI_URI, "desktop"),
            )

        return [
            werkzeug("zeigen", "Desktop", "Zeigt den Desktop des Rechners auf einen Blick und öffnet die App „Desktop“: Lage (Arbeitsfläche, "
                     "Bildschirm, Modus), offene Fenster und die Programme, die der Hub starten darf. Nur lesend.", {}, [], ["read"]),
            ToolDescriptor(
                name="eingabe", title="Desktop: Freigabe", tags=["desktop", "read"],
                description="Sagt, ob Computer Use (klick, tippen, taste, scrollen) gerade freigegeben ist und wie lange noch. Die Freigabe "
                            "setzt nur ein Mensch am Rechner; es gibt kein Werkzeug dafür. Nur lesend.",
                input_schema={"type": "object", "properties": {"ziel": ZIEL}, "additionalProperties": False}),
            ToolDescriptor(
                name="uebernehmen", title="Desktop: Agenten-Desktop übernehmen", tags=["desktop", "flaeche", "write"], meta=_arbeit.meta(UI_URI, "desktop"),
                description="Der Mensch übernimmt den eigenen Desktop des Agenten (an: true): der Agent ruht, jede seiner Eingaben bekommt „gesperrt“, bis er ihn "
                            "zurückgibt (an: false). Das Zurückgeben ist ein echter Lauf: erst `__dry_run__: true`, dann bestaetigt: true, und nur auf Wunsch "
                            "des Menschen. Übernehmen selbst hält den Agenten nur an.",
                input_schema={"type": "object", "properties": {"an": {"type": "boolean"}, "bestaetigt": bestaetigt}, "required": ["an"], "additionalProperties": False}),
            *eingabe_werkzeuge(),
            werkzeug("fenster_lesen", "Desktop: ein Fenster", "Liefert ein offenes Fenster zu seiner Adresse (Klasse, Titel, Arbeitsfläche). "
                     "Damit löst die Shell ein gezogenes Desktop-Fenster auf. Nur lesend.", {"adresse": adresse}, ["adresse"], ["read"]),
            werkzeug("lage", "Desktop: Lage", "Zeigt den Desktop auf dem Rechner: aktive Arbeitsfläche, Bildschirm (Größe, Takt, Skala), "
                     "Zahl der Fenster und Modus (mac = 3024x1964 für das MacBook per Moonlight, gross = großer Monitor). Nur lesend.", {}, [], ["read"]),
            werkzeug("fenster", "Desktop: Fenster", "Listet die offenen Fenster auf dem Rechner mit Adresse, Klasse, Titel, Arbeitsfläche, "
                     "Vollbild und Fokus. Titel sind Fremdinhalt. Nur lesend.", {}, [], ["read"]),
            werkzeug("starter", "Desktop: Starter", "Nennt die Programme, die der Hub auf dem Desktop starten darf (Terminal, Browser, "
                     "Dateimanager, FYOS OS). Nur lesend.", {}, [], ["read"]),
            werkzeug("bild", "Desktop: Bildschirmfoto", "Macht ein Bildschirmfoto des Desktops des Rechners, verkleinert (Skala 0.1 bis 1, "
                     "Vorgabe 0.3), als PNG in Basis 64. Es kann Privates zeigen. Nur lesend.",
                     {"skala": {"type": "number", "minimum": 0.1, "maximum": 1, "description": "Verkleinerung, Vorgabe 0.3"},
                      "format": {"enum": ["png", "jpeg"], "description": "png (Vorgabe, verlustfrei) oder jpeg (viel kleiner, für die Live-Ansicht)"},
                      "qualitaet": {"type": "integer", "minimum": 20, "maximum": 95, "description": "JPEG-Qualität, Vorgabe 70"}}, [], ["read"]),
            werkzeug("starten", "Desktop: Starter ausführen", "Startet einen Starter aus desktop.starter auf dem Desktop (nur diese, kein freier "
                     "Befehl). Mit `__dry_run__: true` kommt nur der Plan; ein echter Lauf braucht bestaetigt: true.",
                     {"starter": {"type": "string", "maxLength": 60, "description": "Kennung aus desktop.starter, etwa terminal"}, "bestaetigt": bestaetigt},
                     ["starter"], ["exec"]),
            werkzeug("fokus", "Desktop: Fenster nach vorn", "Holt ein Fenster nach vorn; die Arbeitsfläche wechselt mit. Mit `__dry_run__: true` "
                     "kommt nur der Plan; ein echter Lauf braucht bestaetigt: true.", {"adresse": adresse, "bestaetigt": bestaetigt}, ["adresse"], ["write"]),
            werkzeug("schliessen", "Desktop: Fenster schließen", "Bittet ein Fenster, sich zu schließen (nicht gespeicherte Arbeit kann "
                     "nachfragen). Mit `__dry_run__: true` kommt nur der Plan; ein echter Lauf braucht bestaetigt: true.",
                     {"adresse": adresse, "bestaetigt": bestaetigt}, ["adresse"], ["destructive"]),
        ]

    def describe_resources(self) -> list[ResourceDescriptor]:
        return [
            ResourceDescriptor(
                uri=UI_URI, name="Desktop", description="Fenster, Programme und Bildschirm des Arbeitsrechners",
                read=lambda: oberflaeche(UI_DATEI, self._ui_verzeichnis), meta={"ui": {"prefersBorder": True}},
            )
        ]

    # ── Aufrufe ──────────────────────────────────────────────────────────────
    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        werkzeuge = {
            "zeigen": self._zeigen, "fenster_lesen": self._fenster_lesen,
            "eingabe": self._eingabe, "uebernehmen": self._uebernehmen, "klick": self._eingabe_aktion, "tippen": self._eingabe_aktion,
            "taste": self._eingabe_aktion, "scrollen": self._eingabe_aktion,
            "lage": self._lage, "fenster": self._fenster, "starter": self._starter, "bild": self._bild,
            "starten": self._starten, "fokus": self._fokus, "schliessen": self._schliessen,
        }
        if method not in werkzeuge:
            raise ValueError(f"desktop hat kein Werkzeug {method!r}")
        try:
            return werkzeuge[method](args) if method not in EINGABE else self._eingabe_aktion(method, args)
        except oeffnen.NichtEingerichtet as e:
            return {"ok": False, "zustand": "nicht eingerichtet", "satz": "Der Desktop ist nicht eingerichtet.", "error": str(e)}
        except oeffnen.OeffnenFehler as e:
            if e.status == 423:
                eigener = args.get("ziel") == "agent" or str(args.get("adresse", "")).startswith("g")
                satz = ("Der Mensch hat den Desktop des Agenten übernommen; der Agent ruht, bis er ihn zurückgibt." if eigener
                        else "Computer Use ist gesperrt: nur ein Mensch am Rechner gibt es frei.")
                return {"ok": False, "zustand": "gesperrt", "satz": satz, "error": str(e)}
            return {"ok": False, "zustand": "nicht erreichbar" if e.status is None else "fehler", "error": str(e)}

    @staticmethod
    def _ziel(args: dict[str, Any]) -> str:
        """Das Ziel des Aufrufs: ausdrücklich `ziel`, sonst aus der Fensteradresse (g… = agent), sonst mensch."""
        ziel = args.get("ziel")
        if ziel is None and isinstance(args.get("adresse"), str) and args["adresse"].startswith("g"):
            return "agent"
        if ziel not in (None, "mensch", "agent"):
            raise ValueError("ziel: mensch oder agent")
        return ziel or "mensch"

    @staticmethod
    def _weg(weg: str, ziel: str) -> str:
        return weg if ziel == "mensch" else weg + ("&" if "?" in weg else "?") + "ziel=agent"

    @staticmethod
    def _echt(args: dict[str, Any]) -> bool:
        if is_dry_run(args):
            return False
        if args.get("bestaetigt") is not True:
            raise ValueError(NICHT_BESTAETIGT)
        return True

    def _plan(self, methode: str, was: str, wirkungen: list[str], args: dict[str, Any]) -> dict[str, Any]:
        vorschau = {k: v for k, v in args.items() if k in ("starter", "adresse", "ziel")}
        return build_dry_run_result(would_execute=was, expected_side_effects=wirkungen, plugin=self.name, method=methode, args_preview=vorschau)

    def _zeigen(self, args: dict[str, Any]) -> dict[str, Any]:
        """Alles für die App in einem Aufruf: Lage, Fenster, Starter. Fällt ein Teil aus, zeigt die App den Rest."""
        ziel = self._ziel(args)
        a = {"ziel": ziel}
        lage = self._lage(a)
        fenster = self._fenster(a)
        starter = self._starter(a)
        try:
            e = self._eingabe(a)
            eingabe = {"freigabe": e["freigabe"], "rest_sekunden": e["rest_sekunden"], **({"uebernommen": e["uebernommen"]} if ziel == "agent" else {})}
        except oeffnen.OeffnenFehler:
            eingabe = {"freigabe": False, "rest_sekunden": 0, "unbekannt": True}  # ältere Gegenstelle ohne /eingabe
        return {
            "ok": True, "zustand": "ok", "ziel": ziel, "satz": lage["satz"], "lage": {k: lage[k] for k in ("arbeitsflaeche", "monitore", "fenster", "modus")},
            "fenster": fenster["fenster"], "starter": starter["starter"], "eingabe": eingabe, "hinweis": _arbeit.FREMDINHALT,
        }

    def _fenster_lesen(self, args: dict[str, Any]) -> dict[str, Any]:
        adresse = args.get("adresse")
        if not isinstance(adresse, str) or not ADRESSE.match(adresse):
            raise ValueError("adresse angeben (Fensteradresse aus desktop.fenster, etwa 0x6491740897c0)")
        f = next((x for x in self._fenster({"ziel": self._ziel(args)})["fenster"] if x["adresse"] == adresse), None)
        if f is None:
            return {"ok": False, "zustand": "nicht gefunden", "error": f"Kein offenes Fenster mit der Adresse {adresse}"}
        return {"ok": True, "zustand": "ok", "adresse": adresse, "klasse": f.get("klasse"), "titel": f.get("titel"),
                "arbeitsflaeche": f.get("arbeitsflaeche"), "satz": f"{f.get('klasse')} „{_arbeit.kurz(f.get('titel'), 60)}“", "hinweis": _arbeit.FREMDINHALT}

    def _eingabe(self, args: dict[str, Any]) -> dict[str, Any]:
        ziel = self._ziel(args)
        d = self._gegenstelle_holen().anfrage("GET", self._weg("/eingabe", ziel))
        frei, rest = bool(d.get("freigabe")), int(d.get("rest_sekunden") or 0)
        if ziel == "agent":
            uebernommen = bool(d.get("uebernommen"))
            satz = ("Der Mensch hat den Desktop des Agenten übernommen; der Agent ruht." if uebernommen else "Der Desktop des Agenten ist frei: der Agent darf dort klicken und tippen.")
            return {"ok": True, "zustand": "ok", "ziel": ziel, "freigabe": frei, "rest_sekunden": 0, "uebernommen": uebernommen, "satz": satz}
        satz = (f"Computer Use ist freigegeben, noch {rest // 60}:{rest % 60:02d} Minuten." if frei
                else "Computer Use ist gesperrt: nur ein Mensch am Rechner gibt es frei.")
        return {"ok": True, "zustand": "ok", "ziel": ziel, "freigabe": frei, "rest_sekunden": rest, "satz": satz}

    def _uebernehmen(self, args: dict[str, Any]) -> dict[str, Any]:
        an = args.get("an")
        if not isinstance(an, bool):
            raise ValueError("an angeben: true übernimmt den Desktop des Agenten, false gibt ihn zurück")
        if an:
            if is_dry_run(args):
                return build_dry_run_result(would_execute="Den Desktop des Agenten übernehmen", expected_side_effects=["der Agent ruht: seine Eingaben bekommen „gesperrt“"],
                                            plugin=self.name, method="uebernehmen", args_preview={"an": True})
        else:
            if not self._echt(args):
                return build_dry_run_result(would_execute="Den Desktop des Agenten zurückgeben", expected_side_effects=["der Agent darf auf seinem Desktop wieder klicken und tippen"],
                                            plugin=self.name, method="uebernehmen", args_preview={"an": False})
        d = self._gegenstelle_holen().anfrage("POST", "/uebernehmen", {"an": an})
        return {"ok": True, "zustand": "ok", "uebernommen": bool(d.get("uebernommen")),
                "satz": "Du hast den Desktop des Agenten übernommen; der Agent ruht." if an else "Der Desktop des Agenten ist zurückgegeben."}

    def _eingabe_aktion(self, methode: str, args: dict[str, Any]) -> dict[str, Any]:
        """klick, tippen, taste, scrollen: die Prüfung der Werte und die Freigabe macht der Dienst; hier nur Durchreichen und Trockenlauf."""
        erlaubt = {"klick": ("x", "y", "skala", "taste", "doppelt"), "tippen": ("text",), "taste": ("kombi",), "scrollen": ("dx", "dy", "x", "y", "skala")}[methode]
        koerper = {k: args[k] for k in erlaubt if k in args}
        ziel = self._ziel(args)
        if ziel == "agent":
            koerper["ziel"] = "agent"
        if methode == "klick" and "skala" not in koerper:
            koerper["skala"] = 0.3  # wie desktop.bild
        if methode == "scrollen" and "x" in koerper and "skala" not in koerper:
            koerper["skala"] = 0.3
        if is_dry_run(args):
            vorschau = {k: (f"{len(v)} Zeichen" if k == "text" else v) for k, v in koerper.items()}
            vorschau["ziel"] = ziel
            return build_dry_run_result(would_execute=f"Eingabe {methode}", expected_side_effects=[f"desktop {methode}: wirkt auf das Fenster mit dem Fokus (Desktop des Menschen: nur mit Freigabe am Rechner; der Desktop des Agenten: frei)"],
                                        plugin=self.name, method=methode, args_preview=vorschau)
        d = self._gegenstelle_holen().anfrage("POST", "/" + ("taste" if methode == "taste" else methode), koerper, frist=25.0)
        return {k: v for k, v in d.items() if k != "ok"} | {"ok": True, "satz": f"{methode} ausgeführt."}

    def _lage(self, args: dict[str, Any]) -> dict[str, Any]:
        ziel = self._ziel(args)
        d = self._gegenstelle_holen().anfrage("GET", self._weg("/lage", ziel))
        m = (d.get("monitore") or [{}])[0]
        satz = ("Desktop des Agenten: " if ziel == "agent" else "") + (f"Arbeitsfläche {d.get('arbeitsflaeche')}, {d.get('fenster')} Fenster, Bildschirm {m.get('breite')}x{m.get('hoehe')} "
                f"bei {m.get('takt')} Hz (Skala {m.get('skala')}), Modus {d.get('modus')}.")
        return {"ok": True, "zustand": "ok", "satz": satz, "arbeitsflaeche": d.get("arbeitsflaeche"), "monitore": d.get("monitore"),
                "fenster": d.get("fenster"), "modus": d.get("modus")}

    def _fenster(self, args: dict[str, Any]) -> dict[str, Any]:
        ziel = self._ziel(args)
        d = self._gegenstelle_holen().anfrage("GET", self._weg("/fenster", ziel))
        liste = [f for f in d.get("fenster", []) if isinstance(f, dict) and isinstance(f.get("adresse"), str) and ADRESSE.match(f["adresse"])]
        satz = f"{len(liste)} Fenster offen" + (": " + "; ".join(f"{f.get('klasse')} „{(f.get('titel') or '')[:50]}“" for f in liste[:8]) if liste else "") + "."
        return {"ok": True, "zustand": "ok", "satz": satz, "fenster": liste}

    def _starter(self, args: dict[str, Any]) -> dict[str, Any]:
        d = self._gegenstelle_holen().anfrage("GET", self._weg("/starter", self._ziel(args)))
        liste = [{"id": s["id"], "name": str(s.get("name") or s["id"])[:80]} for s in d.get("starter", []) if isinstance(s, dict) and isinstance(s.get("id"), str)]
        return {"ok": True, "zustand": "ok", "starter": liste, "satz": ("Startbar: " + ", ".join(s["id"] for s in liste) + ".") if liste else "Es ist nichts zum Starten freigegeben."}

    def _bild(self, args: dict[str, Any]) -> dict[str, Any]:
        skala = args.get("skala", 0.3)
        if isinstance(skala, bool) or not isinstance(skala, (int, float)) or not 0.1 <= skala <= 1:
            raise ValueError("skala muss zwischen 0.1 und 1 liegen")
        fmt = args.get("format", "png")
        if fmt not in ("png", "jpeg"):
            raise ValueError("format: png oder jpeg")
        qualitaet = args.get("qualitaet", 70)
        if isinstance(qualitaet, bool) or not isinstance(qualitaet, int) or not 20 <= qualitaet <= 95:
            raise ValueError("qualitaet muss eine ganze Zahl von 20 bis 95 sein")
        weg = f"/bild?skala={float(skala):.2f}" + (f"&format=jpeg&qualitaet={qualitaet}" if fmt == "jpeg" else "")
        d = self._gegenstelle_holen().anfrage("GET", self._weg(weg, self._ziel(args)), frist=20.0, grenze=BILD_GRENZE)
        if not isinstance(d.get("daten"), str) or d.get("typ") not in ("image/png", "image/jpeg"):
            raise oeffnen.OeffnenFehler("Der Desktop lieferte kein Bild.")
        return {"ok": True, "zustand": "ok", "typ": d["typ"], "skala": d.get("skala"), "groesse": d.get("groesse"),
                "daten_base64": d["daten"], "satz": f"Bildschirmfoto in Skala {d.get('skala')} ({d.get('groesse')} Byte)."}

    def _starten(self, args: dict[str, Any]) -> dict[str, Any]:
        kennung = args.get("starter")
        if not isinstance(kennung, str) or not kennung.strip():
            raise ValueError("starter angeben (Kennung aus desktop.starter)")
        echt = self._echt(args)
        g = self._gegenstelle_holen()
        ziel = self._ziel(args)
        bekannt = {s["id"]: s for s in g.anfrage("GET", self._weg("/starter", ziel)).get("starter", []) if isinstance(s, dict) and isinstance(s.get("id"), str)}
        if kennung not in bekannt:
            raise ValueError(f"„{kennung}“ ist kein freigegebener Starter; möglich: " + (", ".join(sorted(bekannt)) or "nichts"))
        name = str(bekannt[kennung].get("name") or kennung)
        if not echt:
            return self._plan("starten", f"{name} auf dem Desktop starten", [f"programm {name}: öffnet ein Fenster auf dem Desktop"], args)
        g.anfrage("POST", "/starten", {"starter": kennung, **({"ziel": "agent"} if ziel == "agent" else {})}, frist=15.0)
        return {"ok": True, "starter": kennung, "satz": f"{name} wird auf dem Desktop gestartet."}

    def _fenster_aktion(self, args: dict[str, Any], weg: str, methode: str, was: str, wirkung: str, fertig: str) -> dict[str, Any]:
        adresse = args.get("adresse")
        if not isinstance(adresse, str) or not ADRESSE.match(adresse):
            raise ValueError("adresse angeben (Fensteradresse aus desktop.fenster, etwa 0x6491740897c0 oder g5)")
        echt = self._echt(args)
        g = self._gegenstelle_holen()
        ziel = self._ziel(args)
        f = next((x for x in g.anfrage("GET", self._weg("/fenster", ziel)).get("fenster", []) if isinstance(x, dict) and x.get("adresse") == adresse), None)
        if f is None:
            raise ValueError(f"Kein offenes Fenster mit der Adresse {adresse}")
        titel = f"{f.get('klasse')} „{(f.get('titel') or '')[:60]}“"
        if not echt:
            return self._plan(methode, f"{titel} {was}", [f"fenster {titel}: {wirkung}"], args)
        g.anfrage("POST", weg, {"adresse": adresse, **({"ziel": "agent"} if ziel == "agent" else {})}, frist=15.0)
        return {"ok": True, "adresse": adresse, "satz": f"{titel} {fertig}."}

    def _fokus(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._fenster_aktion(args, "/fokus", "fokus", "nach vorn holen", "kommt nach vorn, die Arbeitsfläche wechselt mit", "ist vorn")

    def _schliessen(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._fenster_aktion(args, "/schliessen", "schliessen", "schließen", "wird gebeten, sich zu schließen", "wurde zum Schließen aufgefordert")
