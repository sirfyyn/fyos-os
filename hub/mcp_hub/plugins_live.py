"""mcp_hub.plugins_live — Plugin-Module live nachladen, ohne neues Bild und ohne Neustart des Hubs.

Wie es wirkt
------------
Mit ``plugins_live: true`` und mindestens einem Quellverzeichnis (``plugins_live_quellen`` oder die Umgebung
``FYOS_PLUGINS_LIVE_QUELLEN``, mehrere mit ``:`` getrennt) gilt für jedes Plugin-Modul ``a.b.c`` des Hubs: liegt im
Quellverzeichnis die Datei ``<quelle>/a/b/c.py`` und unterscheidet sie sich von der Datei im Bild, gewinnt die Datei
der Quelle. Das Quellverzeichnis ist meist ein Checkout, den ein Begleitdienst (Sidecar) regelmäßig nachzieht. Der
Hub-Kern bestimmt nicht, wie es dorthin kommt.

* Beim Start nimmt der Hub den Stand der Quelle, wenn er vom Bild abweicht (``vorladen``).
* Ein Wächter (``Waechter``) prüft alle ``plugins_live_takt_s`` Sekunden den Commit jeder Quelle (``.git`` wird
  direkt gelesen, ein ``git``-Programm ist nicht nötig). Bei einem neuen Commit werden die Dateien gehasht und nur
  die geänderten Module neu geladen (``nachladen``). Eine Quelle ohne ``.git`` wird bei jedem Durchlauf geprüft.
* ``POST /hub/plugins/neu-laden`` lädt sofort nach (server.py).

Ein Modul wird ATOMAR getauscht: das neue Modul wird aus der Datei geladen, die neuen Plugins werden gebaut und in
einer Hilfs-Registry angemeldet; erst wenn alles klappt, ersetzen sie unter einer Sperre die alten Werkzeuge und
Ressourcen (Austausch der Verzeichnisse, kein Umbau: wer gerade über ``reg.tools`` iteriert, sieht entweder alt oder
neu). Dann läuft das alte ``shutdown()``. Schlägt Import oder Aufbau fehl, bleibt das alte Plugin stehen; der Fehler
steht in ``/hub/health`` (je Plugin ``live``) und im Log. Dieselbe kaputte Datei wird nicht jede Runde erneut
versucht.

Welche Module zählen: die Module der geladenen Plugins (auch aus Paketen mit Entry-Point), die in der Konfiguration
genannten und, mit ``plugins_von_selbst``, neue Dateien unter ``<quelle>/mcp_hub/plugins/``. Ein Modul, das in der
Konfiguration ``enabled: false`` ist, bleibt aus.

Was weiter ein neues Bild braucht: der Hub-Kern selbst (``registry``, ``server``, ``plugin``, ``config`` …),
Hilfsmodule mit ``_``-Präfix (ein NEUES Hilfsmodul unter ``<quelle>/mcp_hub/plugins/`` ist importierbar, ein
GEÄNDERTES wird nicht neu geladen), neue Abhängigkeiten (pip) und die Hub-Konfiguration. Module, die ein anderes
Plugin-Modul mit ``from .x import y`` einbinden, behalten dessen alten Stand bis zum Neustart. Oberflächen (``ui/``)
eines Plugins kommen ebenfalls aus der Quelle, wenn dort ``<paket>/ui/<datei>`` liegt (``ui_datei``).

Rückweg: ``plugins_live: false`` (oder keine Quelle). Dann kommt aller Code aus dem Bild.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger(__name__)

PAKET = "mcp_hub.plugins"
#: Umgebung: Quellverzeichnisse, wenn die Konfiguration keine nennt (mehrere mit ``os.pathsep``).
UMGEBUNG_QUELLEN = "FYOS_PLUGINS_LIVE_QUELLEN"

_SPERRE = threading.RLock()
_QUELLEN: list[Path] = []
_AKTIV = False
#: Modul -> {quelle, hash, commit, geladen_um, letzter_fehler, fehler_hash}
_STAND: dict[str, dict[str, Any]] = {}
_PFAD_ERGAENZT: set[str] = set()


# ── Zustand ──────────────────────────────────────────────────────────────────


def zuruecksetzen() -> None:
    """Zustand leeren (Tests, erneutes ``build_registry``)."""
    global _AKTIV
    with _SPERRE:
        _QUELLEN.clear()
        _AKTIV = False
        _STAND.clear()


def _quellen_aus(cfg: Any, quellen: list[str | Path] | None) -> list[Path]:
    roh: list[str | Path] = list(quellen or getattr(cfg, "plugins_live_quellen", None) or [])
    if not roh:
        roh = [p for p in (os.getenv(UMGEBUNG_QUELLEN) or "").split(os.pathsep) if p.strip()]
    gefunden: list[Path] = []
    for eintrag in roh:
        pfad = Path(str(eintrag).strip())
        if pfad.is_dir():
            if pfad not in gefunden:
                gefunden.append(pfad)
        else:
            logger.warning("mcp_hub.plugins_live: Quelle %s ist kein Verzeichnis — übergangen", pfad)
    return gefunden


def konfigurieren(cfg: Any, quellen: list[str | Path] | None = None) -> bool:
    """Live-Laden aus der Konfiguration ein- oder ausschalten. Aktiv nur mit Schalter UND mindestens einer Quelle.

    ``quellen`` (Tests) überstimmt ``cfg.plugins_live_quellen`` und die Umgebung ``FYOS_PLUGINS_LIVE_QUELLEN``.
    """
    global _AKTIV
    with _SPERRE:
        _STAND.clear()
        _QUELLEN.clear()
        _AKTIV = False
        if not bool(getattr(cfg, "plugins_live", False)):
            return False
        gefunden = _quellen_aus(cfg, quellen)
        if not gefunden:
            logger.info("mcp_hub.plugins_live: Schalter an, aber keine Quelle vorhanden — Stand aus dem Bild")
            return False
        _QUELLEN.extend(gefunden)
        _AKTIV = True
        for quelle in gefunden:
            _hilfsmodule_zugaenglich(quelle / "mcp_hub" / "plugins")
        logger.info("mcp_hub.plugins_live: an, Quellen %s", ", ".join(str(q) for q in gefunden))
        return True


def aktiv() -> bool:
    return _AKTIV


def quellen() -> list[Path]:
    return list(_QUELLEN)


def aus_quelle(modul: str) -> bool:
    """Läuft das Modul gerade mit dem Stand einer Quelle (nicht dem des Bildes)?"""
    return bool(_AKTIV and (_STAND.get(modul) or {}).get("quelle") == "klon")


def _hilfsmodule_zugaenglich(klon_dir: Path) -> None:
    """Ordner ``<quelle>/mcp_hub/plugins`` HINTER den Bild-Ordnern in ``mcp_hub.plugins.__path__``: ein neues
    Plugin-Modul oder Hilfsmodul aus der Quelle lässt sich so importieren; was das Bild hat, geht vor."""
    if not klon_dir.is_dir():
        return
    try:
        paket = importlib.import_module(PAKET)
        pfad = str(klon_dir)
        if pfad not in paket.__path__ and pfad not in _PFAD_ERGAENZT:
            paket.__path__.append(pfad)
            _PFAD_ERGAENZT.add(pfad)
    except Exception as exc:  # noqa: BLE001 — Zugabe, nie ein Grund abzubrechen
        logger.info("mcp_hub.plugins_live: Pfad nicht ergänzt: %s", exc)


def _teile(modul: str) -> list[str] | None:
    """Namensteile eines Modulpfads; ``None``, wenn er nicht als Dateipfad taugt (leer, ``..``, Schrägstrich)."""
    teile = modul.split(".")
    if not teile or any(not t.isidentifier() for t in teile):
        return None
    return teile


def quell_datei(modul: str) -> Path | None:
    """Datei ``<quelle>/a/b/c.py`` zum Modul ``a.b.c`` in der ersten Quelle, die sie hat."""
    teile = _teile(modul)
    if teile is None:
        return None
    for quelle in _QUELLEN:
        pfad = quelle.joinpath(*teile[:-1], teile[-1] + ".py")
        if pfad.is_file():
            return pfad
    return None


def _in_quelle(pfad: Path) -> bool:
    try:
        aufgeloest = pfad.resolve()
    except OSError:
        return False
    for quelle in _QUELLEN:
        try:
            aufgeloest.relative_to(quelle.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def bild_datei(modul: str) -> Path | None:
    """Datei des Moduls im Bild (nicht in einer Quelle); ``None``, wenn das Bild es nicht hat.

    Ein schon importiertes Modul sagt nichts darüber: sein ``__spec__`` zeigt auf die zuletzt geladene Datei, also
    wird über den Suchpfad des Elternpakets gesucht.
    """
    eltern, _, _stem = modul.rpartition(".")
    try:
        pfad = list(importlib.import_module(eltern).__path__) if eltern else None
        spec = importlib.machinery.PathFinder.find_spec(modul, pfad)
    except Exception:  # noqa: BLE001 — Paket fehlt oder hat keinen Suchpfad
        return None
    herkunft = getattr(spec, "origin", None)
    if not herkunft or not str(herkunft).endswith(".py"):
        return None
    datei = Path(herkunft)
    if _in_quelle(datei):
        return None  # die Datei liegt in einer Quelle, nicht im Bild
    return datei


def _hash(pfad: Path | None) -> str | None:
    if pfad is None:
        return None
    try:
        return hashlib.sha256(pfad.read_bytes()).hexdigest()
    except OSError:
        return None


def commit_lesen(repo: Path | None = None) -> str | None:
    """Commit eines Checkouts aus ``.git`` lesen (kein git-Programm nötig). ``None``, wenn nicht lesbar.

    Ohne Angabe: der Commit der ersten Quelle, die einen hat.
    """
    if repo is None:
        for quelle in _QUELLEN:
            commit = commit_lesen(quelle)
            if commit:
                return commit
        return None
    try:
        kopf = (repo / ".git" / "HEAD").read_text(encoding="utf-8").strip()
        if not kopf.startswith("ref:"):
            return kopf[:40] or None
        ref = kopf.split(":", 1)[1].strip()
        try:
            return (repo / ".git" / ref).read_text(encoding="utf-8").strip()[:40] or None
        except OSError:
            for zeile in (repo / ".git" / "packed-refs").read_text(encoding="utf-8").splitlines():
                if zeile.endswith(" " + ref):
                    return zeile.split(" ", 1)[0][:40]
    except OSError:
        pass
    return None


def commits_lesen() -> tuple[str | None, ...]:
    """Commit je Quelle (in der Reihenfolge der Quellen)."""
    return tuple(commit_lesen(q) for q in _QUELLEN)


def _stand(modul: str) -> dict[str, Any]:
    """Zuletzt geladener Stand eines Moduls; ohne Eintrag: die Datei im Bild (oder nichts, wenn es dort keine gibt)."""
    st = _STAND.get(modul)
    if st is None:
        st = _STAND[modul] = {
            "quelle": "image",
            "hash": _hash(bild_datei(modul)),
            "commit": None,
            "geladen_um": None,
            "letzter_fehler": None,
            "fehler_hash": None,
        }
    return st


# ── Modul aus einer Datei laden ───────────────────────────────────────────────


_FEHLT = object()


def _modul_aus_datei(modul: str, pfad: Path) -> tuple[Any, Any]:
    """Modul ``modul`` aus ``pfad`` laden und in ``sys.modules`` eintragen. Gibt (neues, altes-oder-_FEHLT) zurück.

    Der Modulname bleibt derselbe, damit relative Importe (``from ..plugin import …``, ``from ._x import …``) auf die
    Pakete im Bild zeigen. Fehler beim Ausführen: ``sys.modules`` ist wie vorher.
    """
    alt = sys.modules.get(modul, _FEHLT)
    spec = importlib.util.spec_from_file_location(modul, str(pfad))
    if spec is None or spec.loader is None:
        raise ImportError(f"{pfad} lässt sich nicht laden")
    neu = importlib.util.module_from_spec(spec)
    # Quelltext selbst kompilieren statt `exec_module`: so liest Python keine veraltete .pyc (gleiche Größe, gleiche
    # Sekunde) und schreibt keine in einen schreibgeschützten Checkout.
    code = compile(pfad.read_bytes(), str(pfad), "exec", dont_inherit=True)
    sys.modules[modul] = neu
    try:
        exec(code, neu.__dict__)  # noqa: S102 — Plugin-Code aus der eigenen Quelle, wie aus dem Bild
    except BaseException:
        _zurueck(modul, alt)
        raise
    return neu, alt


def _zurueck(modul: str, alt: Any) -> None:
    if alt is _FEHLT:
        sys.modules.pop(modul, None)
    else:
        sys.modules[modul] = alt
    eltern, _, stem = modul.rpartition(".")
    paket = sys.modules.get(eltern)
    if paket is not None and alt is not _FEHLT:
        setattr(paket, stem, alt)


def _am_paket_anmelden(modul: str, mod: Any) -> None:
    eltern, _, stem = modul.rpartition(".")
    paket = sys.modules.get(eltern)
    if paket is not None:
        setattr(paket, stem, mod)


def _vermerk_geladen(modul: str, h: str | None, commit: str | None) -> None:
    st = _stand(modul)
    st.update(quelle="klon", hash=h, commit=commit, geladen_um=time.time(), letzter_fehler=None, fehler_hash=None)


def _vermerk_fehler(modul: str, h: str | None, fehler: str) -> None:
    st = _stand(modul)
    st.update(letzter_fehler=fehler, fehler_hash=h)


# ── Beim Start ───────────────────────────────────────────────────────────────


def vorladen(modul: str) -> bool:
    """Beim Start: hat die Quelle einen anderen Stand dieses Moduls als das Bild, den Stand der Quelle nehmen.

    Muss VOR dem normalen Import laufen (``registry`` findet das Modul dann schon in ``sys.modules``). Fehler: der
    Bild-Stand bleibt, der Fehler steht in der Health-Anzeige.
    """
    if not _AKTIV or not modul:
        return False
    pfad = quell_datei(modul)
    stem = modul.rpartition(".")[2]
    if pfad is None or stem.startswith("_"):
        return False
    with _SPERRE:
        h = _hash(pfad)
        st = _stand(modul)
        if h is None or h == st["hash"] or h == st["fehler_hash"]:
            return False  # nichts Neues, oder genau dieser Stand hat sich schon als unbrauchbar erwiesen
        try:
            mod, _alt = _modul_aus_datei(modul, pfad)
        except BaseException as exc:  # noqa: BLE001 — auch SyntaxError/SystemExit einer kaputten Datei
            if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                raise
            _vermerk_fehler(modul, h, f"{type(exc).__name__}: {exc}")
            logger.error("mcp_hub.plugins_live: %s aus der Quelle nicht ladbar (Bild-Stand bleibt): %s", modul, exc)
            return False
        _am_paket_anmelden(modul, mod)
        commit = commit_lesen()
        _vermerk_geladen(modul, h, commit)
        logger.info("mcp_hub.plugins_live: %s beim Start aus der Quelle (%s)", modul, (commit or "?")[:9])
        return True


def auf_image_zurueck(modul: str, grund: str) -> bool:
    """Nach einem Fehlschlag beim Aufbau: das Modul aus dem Bild neu laden (Stand der Quelle verworfen)."""
    with _SPERRE:
        bild = bild_datei(modul)
        st = _stand(modul)
        _vermerk_fehler(modul, st["hash"], grund)
        sys.modules.pop(modul, None)
        if bild is None:
            return False
        try:
            mod, _ = _modul_aus_datei(modul, bild)
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                raise
            logger.error("mcp_hub.plugins_live: Bild-Stand von %s nicht ladbar: %s", modul, exc)
            return False
        _am_paket_anmelden(modul, mod)
        st.update(quelle="image", hash=_hash(bild), commit=None)
        return True


# ── Nachladen im laufenden Hub ───────────────────────────────────────────────


def _plugin_klassen(mod: Any) -> list[type]:
    from .plugin import HubPlugin  # noqa: PLC0415

    return [
        obj
        for _, obj in inspect.getmembers(mod, inspect.isclass)
        if issubclass(obj, HubPlugin) and not inspect.isabstract(obj) and obj.__module__ == mod.__name__
    ]


def _haken_von(hook: Any, plugin: Any, modul_dict: dict | None = None) -> bool:
    """Gehört der Aufruf-/Ergebnis-Hook zum alten Plugin? Gebundene Methode, Closure über das Plugin oder eine
    Funktion, die im alten Modul definiert ist."""
    if getattr(hook, "__self__", None) is plugin:
        return True
    if modul_dict is not None and getattr(hook, "__globals__", None) is modul_dict:
        return True
    for zelle in getattr(hook, "__closure__", None) or ():
        try:
            if zelle.cell_contents is plugin:
                return True
        except ValueError:  # leere Zelle
            continue
    return False


def _best_effort(f: Callable[[], Any], was: str) -> None:
    try:
        f()
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_hub.plugins_live: %s: %s", was, exc)


def _kandidaten(reg: Any, cfg: Any) -> dict[str, Path]:
    """Module, für die eine Quelle eine Datei hat: Module geladener Plugins, Module der Konfiguration und mit
    ``plugins_von_selbst`` die neuen Dateien unter ``<quelle>/mcp_hub/plugins/``."""
    module: set[str] = {type(p).__module__ for p in reg.plugins.values()}
    module |= {p.module for p in getattr(cfg, "plugins", []) if p.module}
    if getattr(cfg, "plugins_von_selbst", False):
        for quelle in _QUELLEN:
            ordner = quelle / "mcp_hub" / "plugins"
            if ordner.is_dir():
                module |= {f"{PAKET}.{p.stem}" for p in ordner.glob("*.py") if not p.name.startswith("_")}
    gefunden: dict[str, Path] = {}
    for modul in sorted(module):
        if modul.rpartition(".")[2].startswith("_"):
            continue
        pfad = quell_datei(modul)
        if pfad is not None:
            gefunden[modul] = pfad
    return gefunden


def _plugin_config(cfg: Any, name: str, modul: str, klasse: str, altes: Any) -> Any:
    """Eintrag für ein neu zu bauendes Plugin: Konfiguration und Geheimnisse des Eintrags (nach Name, sonst nach Modul),
    Modul und Klasse des alten Plugins."""
    from .config import PluginConfig  # noqa: PLC0415

    eintrag = next((p for p in cfg.plugins if p.name == name), None) or next(
        (p for p in cfg.plugins if p.module == modul and (not p.class_name or p.class_name == klasse)), None
    )
    konfig = dict(eintrag.config) if eintrag is not None else dict(getattr(altes, "config", None) or {})
    return PluginConfig(
        name=name,
        module=modul,
        class_name=klasse,
        enabled=True,
        config=konfig,
        secrets=list(eintrag.secrets) if eintrag is not None else [],
    )


def _eines(reg: Any, cfg: Any, modul: str, pfad: Path, h: str | None, commit: str | None) -> str:
    """Ein Plugin-Modul aus der Quelle neu laden oder neu aufnehmen. Gibt "neu" | "neu_geladen" | "uebergangen" zurück
    und wirft bei Fehlern (dann ist alles wie vorher)."""
    from .config import PluginConfig  # noqa: PLC0415
    from .registry import PluginRegistry, _inject_plugin_secrets_into_env, _instantiate_plugin, _register_one  # noqa: PLC0415

    stem = modul.rpartition(".")[2]
    eintraege = [p for p in cfg.plugins if p.module == modul]
    alte = {n: p for n, p in reg.plugins.items() if type(p).__module__ == modul}
    if eintraege and not any(p.enabled for p in eintraege):
        return "uebergangen"  # abgeschaltet
    if not alte and not eintraege and not (getattr(cfg, "plugins_von_selbst", False) and modul.startswith(PAKET + ".")):
        return "uebergangen"  # kein Eintrag und nicht automatisch: wie beim Start nicht geladen

    mod, alt = _modul_aus_datei(modul, pfad)
    neue: list[tuple[str | None, str, Any]] = []  # (Name des alten Plugins oder None, Name des neuen, neues Plugin)
    try:
        if alte:
            vorhaben = [(n, _plugin_config(cfg, n, modul, type(p).__name__, p)) for n, p in alte.items()]
        elif eintraege:
            vorhaben = [(None, eintraege[0])]
        else:
            klassen = _plugin_klassen(mod)
            if not klassen:  # Hilfsmodul ohne Plugin-Klasse: nur den Stand merken (der Aufrufer tut das)
                _am_paket_anmelden(modul, mod)
                return "uebergangen"
            vorhaben = [
                (None, PluginConfig(name=getattr(klassen[0], "name", "") or stem, module=modul, class_name=klassen[0].__name__))
            ]
        hilfs = PluginRegistry()
        for alter_name, pcfg in vorhaben:
            _inject_plugin_secrets_into_env(pcfg)
            plugin = _instantiate_plugin(pcfg)
            name = plugin.name or pcfg.name
            neue.append((alter_name, name, plugin))
            if name in reg.plugins and name not in alte:
                raise ValueError(f"Plugin-Name {name!r} ist schon von einem anderen Modul belegt")
            _register_one(hilfs, name, plugin)
        # Werkzeug-Kennungen anderer Plugins dürfen nicht kollidieren.
        for fqtn in hilfs.tools:
            if fqtn in reg.tools and reg.tools[fqtn].plugin_name not in alte:
                raise ValueError(f"Werkzeug {fqtn!r} gehört schon einem anderen Plugin")
    except BaseException:
        _zurueck(modul, alt)
        for _a, _n, plugin in neue:
            _best_effort(plugin.shutdown, f"shutdown des verworfenen {stem}")
        raise

    # ── Austausch (alles gelungen) ──
    _am_paket_anmelden(modul, mod)
    alte_plugins = list(alte.values())
    neue_namen = {name: plugin for _a, name, plugin in neue}
    reg.tools = {**{k: v for k, v in reg.tools.items() if v.plugin_name not in alte}, **hilfs.tools}
    reg.resources = {
        **{k: v for k, v in reg.resources.items() if v[0] not in alte},
        **hilfs.resources,
    }
    reg.plugins = {**{k: v for k, v in reg.plugins.items() if k not in alte}, **neue_namen}
    for name, plugin in neue_namen.items():
        reg.nicht_geladen.pop(name, None)
        reg.breakers.get(name)
    for _a, pcfg in vorhaben:
        reg.nicht_geladen.pop(pcfg.name, None)
    alt_dict = None if alt is _FEHLT else alt.__dict__
    angehaengt: set[str] = set()  # Namen alter Plugins, deren Haken gefallen sind (audit, event_bus_publisher …)
    for alter_name, alter in alte.items():
        for liste in (reg.on_call_hooks, reg.ergebnis_hooks):
            for haken in [x for x in liste if _haken_von(x, alter, alt_dict)]:
                liste.remove(haken)
                angehaengt.add(alter_name)
    for alter in alte_plugins:
        _best_effort(alter.shutdown, f"altes shutdown von {stem}")
    for alter_name, name, plugin in neue:
        if alter_name in angehaengt:  # der neue Haken tritt an die Stelle des alten
            anhaengen = getattr(plugin, "register_as_listener", None)
            if callable(anhaengen):
                _best_effort(lambda a=anhaengen: a(reg), f"register_as_listener von {name}")
        anbinden = getattr(plugin, "registry_anbinden", None)
        if callable(anbinden):
            _best_effort(lambda a=anbinden: a(reg), f"registry_anbinden von {name}")
    _vermerk_geladen(modul, h, commit)
    logger.info(
        "mcp_hub.plugins_live: %s %s (%d Werkzeuge, Commit %s)",
        modul, "neu geladen" if alte else "neu aufgenommen", len(hilfs.tools), (commit or "?")[:9],
    )
    return "neu_geladen" if alte else "neu"


def nachladen(
    reg: Any,
    cfg: Any,
    *,
    nur: str | None = None,
    erzwingen: bool = False,
    nach_aenderung: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Alle (oder ein) geänderte Plugin-Module aus den Quellen nachladen.

    ``nur``: Modulname, letzter Teil des Modulnamens oder Plugin-Name. ``erzwingen``: auch eine Datei erneut
    versuchen, die zuletzt fehlschlug. ``nach_aenderung(ergebnis)`` läuft, wenn sich etwas geändert hat
    (App-Werkzeuge, Suchvektoren, Ereignis, Meldung an offene Sitzungen).
    """
    if not _AKTIV:
        return {"ok": False, "kind": "aus", "error": "Live-Laden ist aus (plugins_live: false oder keine Quelle)"}
    ergebnis: dict[str, Any] = {
        "ok": True, "commit": None, "geladen": [], "neu": [], "unveraendert": 0, "fehler": {}, "fehlend": [],
    }
    with _SPERRE:
        commit = ergebnis["commit"] = commit_lesen()
        module = _kandidaten(reg, cfg)
        if nur:
            gesucht = {nur}
            gesucht |= {type(p).__module__ for n, p in reg.plugins.items() if n == nur}
            module = {
                m: p for m, p in module.items() if m in gesucht or m.rpartition(".")[2] in gesucht
            }
            if not module:
                return {**ergebnis, "ok": False, "kind": "not_found", "error": f"kein Plugin-Modul {nur!r} in den Quellen"}
        for modul, pfad in module.items():
            stem = modul.rpartition(".")[2]
            h = _hash(pfad)
            st = _stand(modul)
            if h is None or h == st["hash"]:
                ergebnis["unveraendert"] += 1
                continue
            if st["fehler_hash"] == h and not erzwingen:
                ergebnis["fehler"][stem] = st["letzter_fehler"]
                continue
            try:
                art = _eines(reg, cfg, modul, pfad, h, commit)
            except BaseException as exc:  # noqa: BLE001 — SyntaxError, SystemExit einer kaputten Datei: Plugin bleibt
                if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                    raise
                meldung = f"{type(exc).__name__}: {exc}"
                _vermerk_fehler(modul, h, meldung)
                ergebnis["fehler"][stem] = meldung
                logger.error("mcp_hub.plugins_live: %s nicht neu geladen, altes Plugin bleibt: %s", modul, meldung)
                continue
            if art == "neu":
                ergebnis["neu"].append(stem)
            elif art == "neu_geladen":
                ergebnis["geladen"].append(stem)
            else:  # übergangen (aus, kein Eintrag, Hilfsmodul): Stand merken, damit es nicht jede Runde neu geprüft wird
                _stand(modul)["hash"] = h
        ergebnis["ok"] = not ergebnis["fehler"]
        if (ergebnis["geladen"] or ergebnis["neu"]) and nach_aenderung is not None:
            _best_effort(lambda: nach_aenderung(ergebnis), "nach_aenderung")
    return ergebnis


# ── Oberflächen ──────────────────────────────────────────────────────────────


def ui_datei(ui_verzeichnis: Path | str | None, datei: str) -> Path | None:
    """Datei einer Oberfläche aus einer Quelle (nur bei aktivem Live-Laden), sonst ``None``.

    ``ui_verzeichnis`` ist wie bei ``_oberflaeche.oberflaeche``: ``None`` = Kern (``mcp_hub/plugins/ui``), ein
    Paketname = ``<paket>/ui``; ein ausdrücklich angegebener Ordner (``Path``) bleibt, wie er ist.
    """
    if not _AKTIV or isinstance(ui_verzeichnis, Path):
        return None
    teile = _teile(PAKET) if ui_verzeichnis is None else _teile(str(ui_verzeichnis))
    if teile is None:
        return None
    name = Path(datei).name  # nie aus dem Verzeichnis hinauslaufen
    for quelle in _QUELLEN:
        pfad = quelle.joinpath(*teile, "ui", name)
        if pfad.is_file():
            return pfad
    return None


# ── Anzeige ──────────────────────────────────────────────────────────────────


def plugin_status(plugin: Any) -> dict[str, Any] | None:
    """Live-Angaben zu einem geladenen Plugin für ``/hub/health``; ``None``, wenn Live-Laden aus ist."""
    if not _AKTIV:
        return None
    modul = type(plugin).__module__
    st = _STAND.get(modul)
    if st is None:
        return {"geladen_aus": "image", "commit": None, "letzter_fehler": None}
    return {
        "geladen_aus": st["quelle"],
        "commit": (st["commit"] or None) and st["commit"][:9],
        "geladen_um": st["geladen_um"],
        "letzter_fehler": st["letzter_fehler"],
    }


def fehler_je_modul() -> dict[str, str]:
    """Module, deren letzter Ladeversuch aus der Quelle fehlschlug (sie laufen mit dem alten Stand weiter)."""
    return {m.rpartition(".")[2]: s["letzter_fehler"] for m, s in _STAND.items() if s.get("letzter_fehler")}


def uebersicht() -> dict[str, Any] | None:
    if not _AKTIV:
        return None
    return {
        "an": True,
        "quellen": [str(q) for q in _QUELLEN],
        "commit": (commit_lesen() or "")[:9] or None,
        "fehler": fehler_je_modul(),
    }


def ereignis(reg: Any, ergebnis: dict[str, Any]) -> None:
    """„Plugin neu geladen“ auf den Ereignisbus (bus.tool.hub.plugin_neu_geladen.ok), wenn der Publisher da ist."""
    bus = reg.plugins.get("event_bus_publisher")
    senden = getattr(bus, "_publish_event", None)
    if not callable(senden):
        return
    ev = SimpleNamespace(
        plugin_name="hub",
        tool_name="hub.plugin_neu_geladen",
        arguments=json.dumps(
            {"geladen": ergebnis.get("geladen"), "neu": ergebnis.get("neu"), "commit": (ergebnis.get("commit") or "")[:9]}
        ),
        result_status="ok",
        latency_ms=0.0,
        error=None,
    )
    _best_effort(lambda: senden(ev), "Ereignis plugin_neu_geladen")


# ── Wächter ──────────────────────────────────────────────────────────────────


class Waechter:
    """Hintergrund-Thread: bei neuem Commit einer Quelle geänderte Plugin-Dateien nachladen."""

    def __init__(self, reg: Any, cfg: Any, takt_s: float = 30.0, nach_aenderung: Callable[[dict[str, Any]], None] | None = None):
        self.reg, self.cfg = reg, cfg
        self.takt_s = max(1.0, float(takt_s))
        self.nach_aenderung = nach_aenderung
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._commits: tuple[str | None, ...] | None = None

    def tick(self) -> dict[str, Any] | None:
        """Ein Durchlauf: bei unveränderten Commits nichts tun (ohne lesbaren Commit: immer prüfen)."""
        commits = commits_lesen()
        if self._commits is not None and commits == self._commits and all(c is not None for c in commits):
            return None
        res = nachladen(self.reg, self.cfg, nach_aenderung=self.nach_aenderung)
        # Bei Fehlern den Stand nicht merken: nächste Runde sieht erneut nach (halb geschriebene Datei beim
        # Nachziehen). Dieselbe kaputte Datei wird per Hash nicht erneut geladen, nur erneut gehasht.
        self._commits = None if res.get("fehler") else commits
        return res

    def _lauf(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 — der Wächter darf nie sterben
                logger.warning("mcp_hub.plugins_live: Wächter-Durchlauf: %s", exc)
            if self._halt.wait(self.takt_s):
                return

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._halt.clear()
        self._thread = threading.Thread(target=self._lauf, name="plugins-live", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
