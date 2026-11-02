"""Textoberfläche (Textual): dieselben Schritte wie der Web-Assistent.

Optional: `pip install "fyos-installer[tui]"`; mit `[bilder]` zeigt textual-image PNG/JPG-Screenshots
im Terminal an. SVG-Skizzen erscheinen als Textvorschau (Beschreibung aus der Datei) samt Pfad.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button, ContentSwitcher, Footer, Header, Input, Label, Markdown, RadioButton, RadioSet, RichLog,
    SelectionList, Static,
)
from textual.widgets.selection_list import Selection

from . import ausfuehren as ausf
from . import erzeugen
from . import stufen as st
from .katalog import Katalog, aufloesen, bilder_von, textvorschau
from .reife import MAX_STUFE
from . import sprache as spr
from .sprache import _

_k = spr.katalog_text

try:  # optional
    from textual_image.widget import Image as BildWidget
except Exception:  # noqa: BLE001 - fehlt oder lässt sich im Terminal nicht nutzen
    BildWidget = None

SCHRITTE = ["Willkommen", "Ziel", "Bausteine", "Einrichten", "Zusammenfassung", "Installieren"]  # Anzeige über _()
ZIEL_IDS = list(erzeugen.ZIELE)
BILD_RASTER = {".png", ".jpg", ".jpeg", ".webp"}

WILLKOMMEN = """\
# Willkommen bei FYOS

FYOS ist dein persönliches Betriebssystem im Browser, aufgebaut auf einem eigenen Agenten.
Du wählst, was du brauchst, und liest vorher, was daraus wird.

Nichts wird geschrieben oder gestartet, bevor du es im letzten Schritt bestätigst.

Bedienung: **n** weiter, **b** zurück, **q** beenden, Tab wechselt zwischen den Feldern.
"""


def abschlusszeile(erg: ausf.Ergebnis) -> str:
    """Letzte Zeile des Protokolls: gescheitert, gestartet aber nicht abgenommen, oder fertig."""
    if not erg.ok:
        return _("FEHLER: ") + erg.meldung
    return (_("GESTARTET, ABER NICHT ABGENOMMEN: ") if erg.nicht_abgenommen else _("FERTIG: ")) + erg.meldung


class InstallerApp(App):
    TITLE = "FYOS"
    CSS = """
    #inhalt { height: 1fr; padding: 0 1; }
    #links { width: 38; }
    #rechts { width: 1fr; padding-left: 2; }
    #fehler { color: $error; }
    #log { height: 1fr; }
    #nav { height: 3; dock: bottom; padding: 0 1; }
    #nav Button { margin-right: 1; }
    #bildbereich { height: auto; max-height: 16; }
    """
    BINDINGS = [
        ("n", "weiter", _("Weiter")), ("b", "zurueck", _("Zurück")), ("q", "quit", _("Beenden")),
        ("ctrl+n", "weiter", _("Weiter (auch im Textfeld)")), ("ctrl+b", "zurueck", _("Zurück (auch im Textfeld)")),
    ]

    def __init__(self, katalog: Katalog, verzeichnis: str | Path = "./fyos"):
        super().__init__()
        self.katalog = katalog
        self.verzeichnis = str(verzeichnis)
        self.schritt = 0
        self.ziel = "compose"
        self.eingaben: dict[str, tuple[str, str]] = {}  # widget-id -> (gruppe, feld)
        self.stufen_wahl: dict[str, list[str]] = {}  # Fähigkeit -> Stufen in der Reihenfolge der Auswahl (RadioSet #stufe-<id>)
        self.plan: erzeugen.Plan | None = None
        self._sperre = False
        self.laeuft = False
        self._vorher: set[str] = {b.id for b in katalog if b.pflicht}

    # ---------------------------------------------------------------- Aufbau
    def compose(self) -> ComposeResult:
        yield Header()
        with ContentSwitcher(initial="s0", id="inhalt"):
            yield Markdown(_(WILLKOMMEN), id="s0")
            with Vertical(id="s1"):
                yield Label(_("Wohin soll FYOS?"))
                with RadioSet(id="ziel"):
                    for i, z in enumerate(ZIEL_IDS):
                        yield RadioButton(_(erzeugen.ZIELE[z]), value=i == 0, id=f"z-{z}")
                yield Static("", id="zielhinweis")
            with Horizontal(id="s2"):
                with Vertical(id="links"):
                    yield Label(_("Bausteine (Leertaste wählt)"))
                    yield SelectionList[str](
                        *[Selection(f"{_k(b.titel)}{' *' if b.pflicht else ''}", b.id, b.pflicht) for b in self.katalog],
                        id="liste",
                    )
                    yield Static(_("* = immer dabei"), classes="leise")
                with VerticalScroll(id="rechts"):
                    yield Static("", id="titel")
                    yield Vertical(id="bildbereich")
                    yield Static("", id="skizze")
                    yield Markdown("", id="erklaerung")
                    yield Static("", id="voraus")
            with VerticalScroll(id="s3"):
                yield Static("", id="fehler")
                yield Vertical(id="formular")
            with VerticalScroll(id="s4"):
                yield Label(_("Zielordner"))
                yield Input(value=self.verzeichnis, id="verz")
                yield Markdown("", id="zusammenfassung")
            with Vertical(id="s5"):
                yield Button(_("Installieren"), id="los", variant="success")
                yield RichLog(id="log", wrap=True, markup=False)
        with Horizontal(id="nav"):
            yield Button(_("Zurück"), id="zurueck")
            yield Button(_("Weiter"), id="weiter", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._titel()
        self._zeige_baustein(self.katalog.bausteine and next(iter(self.katalog)).id)
        self._hinweis_ziel()

    def _titel(self) -> None:
        self.sub_title = _("Schritt {0} von {1}: {2}", self.schritt + 1, len(SCHRITTE), _(SCHRITTE[self.schritt]))
        self.query_one("#zurueck", Button).disabled = self.schritt == 0 or self.laeuft
        weiter = self.query_one("#weiter", Button)
        weiter.display = self.schritt < len(SCHRITTE) - 1
        weiter.label = _("Weiter zum Installieren") if self.schritt == 4 else _("Weiter")

    def _hinweis_ziel(self) -> None:
        text = ""
        if self.ziel == "compose":
            bereit, meldung = ausf.docker_pruefen()
            text = meldung + ("" if bereit else _(" Du kannst trotzdem nur Dateien erzeugen."))
        elif self.ziel == "k8s":
            text = _("Erzeugt ein Kustomize-Overlay; angewendet wird mit kubectl, von dir.")
        else:
            text = _("Schreibt Dateien und eine Anleitung; gestartet wird später von dir.")
        self.query_one("#zielhinweis", Static).update(text)

    # ---------------------------------------------------------------- Ziel
    @on(RadioSet.Changed, "#ziel")
    def _ziel_geaendert(self, ereignis: RadioSet.Changed) -> None:
        self.ziel = ZIEL_IDS[ereignis.radio_set.pressed_index]
        self._hinweis_ziel()

    # ---------------------------------------------------------------- Bausteine
    def gewaehlt(self) -> list[str]:
        return list(self.query_one("#liste", SelectionList).selected)

    @on(SelectionList.SelectedChanged, "#liste")
    def _auswahl_geaendert(self) -> None:
        if self._sperre:
            return
        liste = self.query_one("#liste", SelectionList)
        jetzt = set(liste.selected)
        neu = set(aufloesen(self.katalog, list(jetzt - self._vorher), mit_pflicht=False)) | jetzt
        for entfernt in self._vorher - jetzt:  # Abwahl nimmt alle mit, die davon abhängen
            for b in self.katalog:
                if entfernt in aufloesen(self.katalog, [b.id], mit_pflicht=False):
                    neu.discard(b.id)
        neu |= {b.id for b in self.katalog if b.pflicht}
        self._sperre = True
        try:
            for b in self.katalog:
                (liste.select if b.id in neu else liste.deselect)(b.id)
        finally:
            self._sperre = False
        self._vorher = neu

    @on(SelectionList.SelectionHighlighted, "#liste")
    def _hervorgehoben(self, ereignis: SelectionList.SelectionHighlighted) -> None:
        self._zeige_baustein(ereignis.selection.value)

    def _zeige_baustein(self, id_: str | None) -> None:
        if not id_ or id_ not in self.katalog:
            return
        b = self.katalog[id_]
        self.query_one("#titel", Static).update(f"[b]{_k(b.titel)}[/b]\n{_k(b.kurz)}")
        self.query_one("#erklaerung", Markdown).update("#### " + _("Was daraus wird") + "\n\n" + _k(b.was_daraus_wird).replace("\n", " "))
        self.query_one("#voraus", Static).update(
            _("Voraussetzungen:") + "\n" + "\n".join(f"  - {_k(v)}" for v in b.voraussetzungen) if b.voraussetzungen else ""
        )
        bereich = self.query_one("#bildbereich", Vertical)
        bereich.remove_children()
        skizze = self.query_one("#skizze", Static)
        bilder = bilder_von(b)
        if BildWidget and bilder and bilder[0].suffix.lower() in BILD_RASTER:
            bereich.mount(BildWidget(str(bilder[0])))
            skizze.update("")
        else:
            skizze.update(textvorschau(b) + "\n")

    # ---------------------------------------------------------------- Einrichten
    def _antworten(self) -> dict[str, Any]:
        daten: dict[str, Any] = {"persona": {}, "modell": {}, "optionen": {}, "felder": {}}
        for wid, (gruppe, name) in self.eingaben.items():
            try:
                wert = self.query_one(f"#{wid}", Input).value
            except Exception:  # noqa: BLE001 - Formular nicht aufgebaut
                continue
            if gruppe in ("persona", "modell", "optionen"):
                daten[gruppe][name] = wert
            else:
                daten["felder"].setdefault(gruppe, {})[name] = wert
        daten["stufen"] = self._stufen_gewaehlt()
        return daten

    def _stufen_gewaehlt(self) -> dict[str, str]:
        """Die Stufe je Fähigkeit, wie sie in den Auswahlfeldern steht (jede, die das Formular zeigt)."""
        gewaehlt: dict[str, str] = {}
        for fid, ids in self.stufen_wahl.items():
            try:
                index = self.query_one(f"#stufe-{fid}", RadioSet).pressed_index
            except Exception:  # noqa: BLE001 - Formular nicht aufgebaut
                continue
            if 0 <= index < len(ids):
                gewaehlt[fid] = ids[index]
        return gewaehlt

    def _stufen_widgets(self, b) -> list:
        """Je Fähigkeit des Bausteins eine Auswahl Grundstufe / Ausbaustufe / aus; vorgewählt ist die Stufe der Bauart."""
        teile: list = []
        for f in self.katalog.faehigkeiten.values():
            if f.baustein != b.id:
                continue
            optionen = [(s.id, f"{st.STUFE_TITEL[s.id]}: {_k(s.titel)}" + ("" if s.verfuegbar else _(" (gibt es noch nicht)")),
                         s.verfuegbar) for s in f.stufen.values()]
            if f.aus:
                optionen.append((st.AUS, _("aus: nicht einrichten"), True))
            ids = [o[0] for o in optionen]
            self.stufen_wahl[f.id] = ids
            vorgabe = f.vorgabe(self.ziel)
            teile.append(Label(_("[b]{0}[/b]: welche Stufe? (Vorgabe für dieses Ziel: {1})", _k(f.titel), st.STUFE_TITEL[vorgabe])))
            teile.append(RadioSet(
                *[RadioButton(text, value=i == vorgabe, disabled=not frei) for i, text, frei in optionen],
                id=f"stufe-{f.id}",
            ))
            teile.append(Label("; ".join(f"{st.STUFE_TITEL[s.id]}: {_k(s.text)}" for s in f.stufen.values()), classes="leise"))
        return teile

    def _eingabe(self, gruppe: str, name: str, titel: str, wert: Any, geheim: bool = False, hilfe: str = "") -> list:
        wid = f"in-{gruppe}-{name}"
        self.eingaben[wid] = (gruppe, name)
        widgets = [Label(titel)]
        widgets.append(Input(value=str(wert if wert is not None else ""), password=geheim, id=wid))
        if hilfe:
            widgets.append(Label(hilfe, classes="leise"))
        return widgets

    async def _formular_bauen(self) -> None:
        form = self.query_one("#formular", Vertical)
        await form.remove_children()
        self.eingaben.clear()
        self.stufen_wahl.clear()
        v = erzeugen
        teile: list = [Label("[b]" + _("Dein Agent") + "[/b]")]
        p = spr.persona_vorgabe(v.VORGABE_PERSONA)
        teile += self._eingabe("persona", "agent_name", _("Name des Agenten"), p["agent_name"])
        teile += self._eingabe("persona", "wesen", _("Wesen"), p["wesen"])
        teile += self._eingabe("persona", "besitzer_name", _("Dein Name"), p["besitzer_name"])
        teile += self._eingabe("persona", "sprache", _("Sprache"), p["sprache"])
        m = v.VORGABE_MODELL
        teile.append(Label("\n" + _("[b]Sprachmodell[/b] (OpenAI-kompatibel)")))
        teile += self._eingabe("modell", "basis_url", _("Basis-Adresse"), m["basis_url"])
        teile += self._eingabe("modell", "name", _("Modellname"), m["name"])
        teile += self._eingabe("modell", "schluessel", _("Schlüssel (leer, wenn keiner nötig)"), m["schluessel"], True)
        ids = aufloesen(self.katalog, self.gewaehlt())
        bausteine = [self.katalog[i] for i in ids]
        o = v.vorgaben_optionen(bezug_aufloesen=True)
        teile.append(Label("\n" + _("[b]Bezug der Pakete und Bilder[/b] (Vorgaben aus FYOS_PAKETINDEX, FYOS_PLUGIN_QUELLE, FYOS_REGISTRY, FYOS_BILD_TAG)")))
        if any(b.paket for b in bausteine):
            teile += self._eingabe("optionen", "bezug", _("Bezug: index oder git"), o["bezug"])
            teile += self._eingabe("optionen", "paketindex", _("Index-URL (bei Bezug index)"), o["paketindex"],
                                   hilfe=_("Zum Beispiel https://git.example.com/api/packages/org/pypi/simple (uv fragt ihn vor PyPI)"))
            teile += self._eingabe("optionen", "plugin_quelle", _("Plugin-Quelle (bei Bezug git)"), o["plugin_quelle"])
        teile += self._eingabe("optionen", "bild_web", _("Bild der Oberfläche"), o["bild_web"])
        teile += self._eingabe("optionen", "hub_bild", _("Basisbild des Hubs"), o["hub_bild"])
        teile += self._eingabe("optionen", "bild_agent", _("Bild des Agenten"), o["bild_agent"])
        if self.ziel == "k8s":
            teile.append(Label("\n[b]Kubernetes[/b]"))
            teile += self._eingabe("optionen", "hub_bild_k8s", _("Hub-Bild in deiner Registry"), o["hub_bild_k8s"])
            teile += self._eingabe("optionen", "namespace", "Namespace", o["namespace"])
        for b in bausteine:
            if not b.konfiguration:
                continue
            teile.append(Label(f"\n[b]{_k(b.titel)}[/b]"))
            teile += self._stufen_widgets(b)
            gilt = {}  # Feld -> Stufe, zu der es gehört (nur diese Stufe nutzt den Wert, die anderen Felder bleiben unbeachtet)
            for fk in self.katalog.faehigkeiten.values():
                if fk.baustein == b.id:
                    gilt.update({n: st.STUFE_TITEL[s.id] for s in fk.stufen.values() for n in s.felder})
            for f in b.konfiguration:
                titel = _k(f.titel) + (" *" if f.pflicht else "")
                hilfe = _k(f.beschreibung) + (_(" (gilt nur bei der {0})", gilt[f.name]) if f.name in gilt else "")
                teile += self._eingabe(b.id, f.name, titel, f.standard, f.typ == "geheim", hilfe)
        await form.mount_all(teile)

    # ---------------------------------------------------------------- Navigation
    def _plan(self) -> erzeugen.Plan:
        verz = self.query_one("#verz", Input).value or self.verzeichnis
        return erzeugen.erstelle_plan(self.katalog, self.gewaehlt(), self.ziel, self._antworten(), verz)

    async def _gehe(self, n: int) -> None:
        if n == 3:
            await self._formular_bauen()
        if n == 4:
            plan = self._plan()
            if not plan.ok:
                self.query_one("#fehler", Static).update(_("Bitte prüfen:") + "\n" + "\n".join(f"  - {f}" for f in plan.fehler))
                return
            self.query_one("#fehler", Static).update("")
            self.plan = plan
            await self.query_one("#zusammenfassung", Markdown).update(self._zusammenfassung(plan))
        if n == 5 and self.plan:
            self.query_one("#los", Button).label = _("Installieren") if self.plan.ausfuehrbar else _("Dateien erzeugen")
        self.schritt = n
        self.query_one("#inhalt", ContentSwitcher).current = f"s{n}"
        self._titel()

    def _zusammenfassung(self, plan: erzeugen.Plan) -> str:
        zeilen = [_("**Ziel:** {0}", _(erzeugen.ZIELE[plan.ziel])), "", _("**Bausteine:** ") + ", ".join(plan.auswahl), ""]
        if plan.stufen:
            zeilen += ["### " + _("Stufe je Fähigkeit"), "", _("Die Grundstufe braucht keinen eigenen Dienst, die Ausbaustufe einen:"), ""]
            for w in plan.stufen:
                zeilen.append(f"- {w.zeile()}")
                if w.url_umgebung:
                    zeilen.append(_("  Adresse in `{0}`: ", w.url_umgebung) + (
                        _("gesetzt.") if w.url_gesetzt else _("noch leer, trage sie selbst ein; den Dienst liefert der Installer noch nicht mit.")))
            zeilen.append("")
        if plan.reife:
            zeilen += ["### " + _("Reifegrad"), "", _("Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet:"), ""]
            for r in plan.reife:
                zeilen.append(_("- **{0}**: Stufe {1} von {2} ({3}). Erkennbar: {4}", r.titel, r.stufe, MAX_STUFE, r.name, r.erkennbar))
                if r.naechste:
                    zeilen.append("  " + _("Nächste Stufe: {0}", r.naechste))
            zeilen.append("")
        zeilen += ["### " + _("Dateien"), ""]
        for d in plan.dateien:
            zeilen.append(f"- `{d.pfad}` ({oct(d.modus)[2:]}): {d.beschreibung}")
        zeilen += ["", "### " + _("Befehle"), ""] + [f"    {b}" for b in plan.befehle]
        if plan.hinweise:
            zeilen += ["", "### " + _("Hinweise"), ""] + [f"- {h}" for h in plan.hinweise]
        return "\n".join(zeilen)

    async def action_weiter(self) -> None:
        if self.schritt < len(SCHRITTE) - 1 and not self.laeuft:
            await self._gehe(self.schritt + 1)

    async def action_zurueck(self) -> None:
        if self.schritt > 0 and not self.laeuft:
            await self._gehe(self.schritt - 1)

    @on(Button.Pressed, "#weiter")
    async def _weiter(self) -> None:
        await self.action_weiter()

    @on(Button.Pressed, "#zurueck")
    async def _zurueck(self) -> None:
        await self.action_zurueck()

    # ---------------------------------------------------------------- Installieren
    @on(Button.Pressed, "#los")
    def _los(self) -> None:
        if self.laeuft or not self.plan:
            return
        self.laeuft = True
        self.query_one("#los", Button).disabled = True
        self._titel()
        self.run_worker(self._installieren_arbeit, thread=True, exclusive=True)

    def _log(self, text: str) -> None:
        self.call_from_thread(self.query_one("#log", RichLog).write, text)

    def _installieren_arbeit(self) -> None:
        plan = self.plan
        assert plan is not None
        try:
            for pfad in erzeugen.schreiben(plan):
                self._log(_("geschrieben: {0}", pfad))
            if plan.ausfuehrbar:
                self._log(abschlusszeile(ausf.ausfuehren(plan, self._log)))
            else:
                self._log(_("Fertig. Die nächsten Schritte stehen in ANLEITUNG.md im Zielordner."))
        except Exception as e:  # noqa: BLE001
            self._log(_("FEHLER: ") + str(e))
        finally:
            self.call_from_thread(self._fertig)

    def _fertig(self) -> None:
        self.laeuft = False
        self._titel()


def starte(katalog: Katalog, verzeichnis: str | Path = "./fyos") -> int:
    InstallerApp(katalog, verzeichnis).run()
    return 0
