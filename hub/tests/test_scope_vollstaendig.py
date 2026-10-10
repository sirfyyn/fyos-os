"""Jedes Werkzeug im Hub muss seinen scope nennen.

## Warum

`hub__map` zeigt pro Werkzeug einen scope (READ/WRITE/DESTRUCTIVE/EXEC/EXTERN).
Das ist die Gefahrenanzeige, an der ein Agent entscheidet, ob er etwas aufruft.
`scope_from_tags()` liefert "UNKNOWN", wenn kein Scope-Tag da ist — bewusst
fail-visible, damit ein ungetaggtes Werkzeug nicht faelschlich als `read`
durchgeht.

Ein Werkzeug ohne scope-Tag meldete frueher UNKNOWN, darunter
ein Werkzeug, das ein beliebiges installiertes Programm mit beliebigen
Argumenten ausfuehrt. Eine Karte, die ein Viertel ihrer Eintraege mit "weiss
nicht" beschriftet, ist als Entscheidungsgrundlage wertlos — und der gefaehrlichste
Eintrag sah aus wie jeder andere.

## Warum ueber die Plugin-Klassen und nicht ueber die Registry

Die Registry braucht Cluster und Env; in der CI laedt sie nur einen Bruchteil.
Eine Pruefung, die nur 24 von 72 Werkzeugen sieht, meldet gruen, waehrend die
Haelfte ungeprueft ist. Deshalb hier derselbe Weg wie im k8s-Vertragstest:
`config = {}` -> `register()` -> `describe_tools()`, ueber alle Plugin-Dateien.

Wer ein Werkzeug ergaenzt, ergaenzt einen Scope-Tag. Wer nicht weiss welchen:
`read` nur, wenn der Aufruf nachweislich nichts veraendert.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib

import pytest

from mcp_hub.plugin import HubPlugin
from mcp_hub.registry import scope_from_tags

_PLUGDIR = pathlib.Path(__file__).resolve().parents[1] / "plugins"


def _alle_werkzeuge() -> list[tuple[str, list[str]]]:
    """(tool-id, tags) ueber alle Plugin-Dateien im Repo — ohne Cluster."""
    raus: list[tuple[str, list[str]]] = []
    for pfad in sorted(_PLUGDIR.glob("*.py")):
        if pfad.name.startswith("__"):
            continue
        modname = f"mcp_hub.plugins.{pfad.stem}"
        try:
            mod = importlib.import_module(modname)
        except Exception:  # noqa: BLE001 — ein Plugin ohne Abhaengigkeiten uebergehen
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, HubPlugin) or obj is HubPlugin:
                continue
            if obj.__module__ != modname:
                continue
            try:
                p = obj()
                p.config = {}
                p.register()
                tools = p.describe_tools()
            except Exception:  # noqa: BLE001
                continue
            for t in tools:
                raus.append((f"{p.name}.{t.name}", list(getattr(t, "tags", None) or [])))
    return raus




def test_die_probe_erkennt_ein_fehlendes_tag():
    """Selbstprobe 2 — wuerde die Pruefung ueberhaupt Nein sagen koennen?"""
    assert scope_from_tags(["irgendwas", "ohne-scope"]) == "UNKNOWN"
    assert scope_from_tags([]) == "UNKNOWN"
    assert scope_from_tags(None) == "UNKNOWN"
    # und die scharfste Wirkung gewinnt, nicht die erste
    assert scope_from_tags(["read", "destructive"]) == "DESTRUCTIVE"


def test_kein_werkzeug_ohne_scope():
    """Der Kern."""
    werkzeuge = _alle_werkzeuge()
    ohne = [name for name, tags in werkzeuge if scope_from_tags(tags) == "UNKNOWN"]
    assert not ohne, (
        f"{len(ohne)} von {len(werkzeuge)} Werkzeugen melden scope=UNKNOWN und "
        f"erscheinen in hub__map ohne Gefahrenanzeige: {sorted(ohne)}"
    )


