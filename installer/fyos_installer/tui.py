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
from .katalog import Katalog, aufloesen, bilder_von, textvorschau
from .reife import MAX_STUFE

try:  # optional
    from textual_image.widget import Image as BildWidget
except Exception:  # noqa: BLE001 - fehlt oder lässt sich im Terminal nicht nutzen
    BildWidget = None

SCHRITTE = ["Willkommen", "Ziel", "Bausteine", "Einrichten", "Zusammenfassung", "Installieren"]
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
        return "FEHLER: " + erg.meldung
    return ("GESTARTET, ABER NICHT ABGENOMMEN: " if erg.nicht_abgenommen else "FERTIG: ") + erg.meldung


class InstallerApp(App):
    TITLE = "FYOS einrichten"
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
        ("n", "weiter", "Weiter"), ("b", "zurueck", "Zurück"), ("q", "quit", "Beenden"),
        ("ctrl+n", "weiter", "Weiter (auch im Textfeld)"), ("ctrl+b", "zurueck", "Zurück (auch im Textfeld)"),
    ]

    def __init__(self, katalog: Katalog, verzeichnis: str | Path = "./fyos"):
        super().__init__()
        self.katalog = katalog
        self.verzeichnis = str(verzeichnis)
        self.schritt = 0
        self.ziel = "compose"
        self.eingaben: dict[str, tuple[str, str]] = {}  # widget-id -> (gruppe, feld)
        self.plan: erzeugen.Plan | None = None
        self._sperre = False
        self.laeuft = False
        self._vorher: set[str] = {b.id for b in katalog if b.pflicht}

    # ---------------------------------------------------------------- Aufbau
    def compose(self) -> ComposeResult:
        yield Header()
        with ContentSwitcher(initial="s0", id="inhalt"):
            yield Markdown(WILLKOMMEN, id="s0")
            with Vertical(id="s1"):
                yield Label("Wohin soll FYOS?")
                with RadioSet(id="ziel"):
                    for i, z in enumerate(ZIEL_IDS):
                        yield RadioButton(erzeugen.ZIELE[z], value=i == 0, id=f"z-{z}")
                yield Static("", id="zielhinweis")
            with Horizontal(id="s2"):
                with Vertical(id="links"):
                    yield Label("Bausteine (Leertaste wählt)")
                    yield SelectionList[str](
                        *[Selection(f"{b.titel}{' *' if b.pflicht else ''}", b.id, b.pflicht) for b in self.katalog],
                        id="liste",
                    )
                    yield Static("* = immer dabei", classes="leise")
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
                yield Label("Zielordner")
                yield Input(value=self.verzeichnis, id="verz")
                yield Markdown("", id="zusammenfassung")
            with Vertical(id="s5"):
                yield Button("Installieren", id="los", variant="success")
                yield RichLog(id="log", wrap=True, markup=False)
        with Horizontal(id="nav"):
            yield Button("Zurück", id="zurueck")
            yield Button("Weiter", id="weiter", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._titel()
        self._zeige_baustein(self.katalog.bausteine and next(iter(self.katalog)).id)
        self._hinweis_ziel()

    def _titel(self) -> None:
        self.sub_title = f"Schritt {self.schritt + 1} von {len(SCHRITTE)}: {SCHRITTE[self.schritt]}"
        self.query_one("#zurueck", Button).disabled = self.schritt == 0 or self.laeuft
        weiter = self.query_one("#weiter", Button)
        weiter.display = self.schritt < len(SCHRITTE) - 1
        weiter.label = "Weiter zum Installieren" if self.schritt == 4 else "Weiter"

    def _hinweis_ziel(self) -> None:
        text = ""
        if self.ziel == "compose":
            bereit, meldung = ausf.docker_pruefen()
            text = meldung + ("" if bereit else " Du kannst trotzdem nur Dateien erzeugen.")
        elif self.ziel == "k8s":
            text = "Erzeugt ein Kustomize-Overlay; angewendet wird mit kubectl, von dir."
        else:
            text = "Schreibt Dateien und eine Anleitung; gestartet wird später von dir."
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
        self.query_one("#titel", Static).update(f"[b]{b.titel}[/b]\n{b.kurz}")
        self.query_one("#erklaerung", Markdown).update("#### Was daraus wird\n\n" + b.was_daraus_wird.replace("\n", " "))
        self.query_one("#voraus", Static).update(
            "Voraussetzungen:\n" + "\n".join(f"  - {v}" for v in b.voraussetzungen) if b.voraussetzungen else ""
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
        return daten

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
        v = erzeugen
        teile: list = [Label("[b]Dein Agent[/b]")]
        p = v.VORGABE_PERSONA
        teile += self._eingabe("persona", "agent_name", "Name des Agenten", p["agent_name"])
        teile += self._eingabe("persona", "wesen", "Wesen", p["wesen"])
        teile += self._eingabe("persona", "besitzer_name", "Dein Name", p["besitzer_name"])
        teile += self._eingabe("persona", "sprache", "Sprache", p["sprache"])
        m = v.VORGABE_MODELL
        teile.append(Label("\n[b]Sprachmodell[/b] (OpenAI-kompatibel)"))
        teile += self._eingabe("modell", "basis_url", "Basis-Adresse", m["basis_url"])
        teile += self._eingabe("modell", "name", "Modellname", m["name"])
        teile += self._eingabe("modell", "schluessel", "Schlüssel (leer, wenn keiner nötig)", m["schluessel"], True)
        ids = aufloesen(self.katalog, self.gewaehlt())
        bausteine = [self.katalog[i] for i in ids]
        o = v.vorgaben_optionen(bezug_aufloesen=True)
        teile.append(Label("\n[b]Bezug der Pakete und Bilder[/b] (Vorgaben aus FYOS_PAKETINDEX, FYOS_PLUGIN_QUELLE, FYOS_REGISTRY)"))
        if any(b.paket for b in bausteine):
            teile += self._eingabe("optionen", "bezug", "Bezug: index oder git", o["bezug"])
            teile += self._eingabe("optionen", "paketindex", "Index-URL (bei Bezug index)", o["paketindex"],
                                   hilfe="Zum Beispiel https://git.example.com/api/packages/org/pypi/simple (uv fragt ihn vor PyPI)")
            teile += self._eingabe("optionen", "plugin_quelle", "Plugin-Quelle (bei Bezug git)", o["plugin_quelle"])
        teile += self._eingabe("optionen", "bild_web", "Bild der Oberfläche", o["bild_web"])
        teile += self._eingabe("optionen", "hub_bild", "Basisbild des Hubs", o["hub_bild"])
        teile += self._eingabe("optionen", "bild_agent", "Bild des Agenten", o["bild_agent"])
        if self.ziel == "k8s":
            teile.append(Label("\n[b]Kubernetes[/b]"))
            teile += self._eingabe("optionen", "hub_bild_k8s", "Hub-Bild in deiner Registry", o["hub_bild_k8s"])
            teile += self._eingabe("optionen", "namespace", "Namespace", o["namespace"])
        for b in bausteine:
            if not b.konfiguration:
                continue
            teile.append(Label(f"\n[b]{b.titel}[/b]"))
            for f in b.konfiguration:
                titel = f.titel + (" *" if f.pflicht else "")
                teile += self._eingabe(b.id, f.name, titel, f.standard, f.typ == "geheim", f.beschreibung)
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
                self.query_one("#fehler", Static).update("Bitte prüfen:\n" + "\n".join(f"  - {f}" for f in plan.fehler))
                return
            self.query_one("#fehler", Static).update("")
            self.plan = plan
            await self.query_one("#zusammenfassung", Markdown).update(self._zusammenfassung(plan))
        if n == 5 and self.plan:
            self.query_one("#los", Button).label = "Installieren" if self.plan.ausfuehrbar else "Dateien erzeugen"
        self.schritt = n
        self.query_one("#inhalt", ContentSwitcher).current = f"s{n}"
        self._titel()

    def _zusammenfassung(self, plan: erzeugen.Plan) -> str:
        zeilen = [f"**Ziel:** {erzeugen.ZIELE[plan.ziel]}", "", "**Bausteine:** " + ", ".join(plan.auswahl), ""]
        if plan.reife:
            zeilen += ["### Reifegrad", "", "Vier Schichten mit je drei Stufen, aus deiner Auswahl abgeleitet:", ""]
            for r in plan.reife:
                zeilen.append(f"- **{r.titel}**: Stufe {r.stufe} von {MAX_STUFE} ({r.name}). Erkennbar: {r.erkennbar}")
                if r.naechste:
                    zeilen.append(f"  Nächste Stufe: {r.naechste}")
            zeilen.append("")
        zeilen += ["### Dateien", ""]
        for d in plan.dateien:
            zeilen.append(f"- `{d.pfad}` ({oct(d.modus)[2:]}): {d.beschreibung}")
        zeilen += ["", "### Befehle", ""] + [f"    {b}" for b in plan.befehle]
        if plan.hinweise:
            zeilen += ["", "### Hinweise", ""] + [f"- {h}" for h in plan.hinweise]
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
                self._log(f"geschrieben: {pfad}")
            if plan.ausfuehrbar:
                self._log(abschlusszeile(ausf.ausfuehren(plan, self._log)))
            else:
                self._log("Fertig. Die nächsten Schritte stehen in ANLEITUNG.md im Zielordner.")
        except Exception as e:  # noqa: BLE001
            self._log(f"FEHLER: {e}")
        finally:
            self.call_from_thread(self._fertig)

    def _fertig(self) -> None:
        self.laeuft = False
        self._titel()


def starte(katalog: Katalog, verzeichnis: str | Path = "./fyos") -> int:
    InstallerApp(katalog, verzeichnis).run()
    return 0
