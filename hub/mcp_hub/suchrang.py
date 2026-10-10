"""suchrang — Rangfolge der Werkzeugsuche (hub__search_tools, GET /hub/search) und der Werkstattsuche.

Eine reine Teilstring-Suche liefert zu viele Treffer (»ci« steckt in »cipher«), kennt keinen Wortrand, keine
Gewichtung der Felder und keine Obergrenze. Diese Rangfolge macht es anders:

* **Wortgrenzen.** Ein Suchwort trifft ein Wort des Textes ganz, am Anfang (ab 4 Zeichen, »skript« in »skripte«) oder
  — ab 5 Zeichen — als Teil eines langen Wortes (»werkzeug« in »anwendungswerkzeuge«). Kurze Wörter (»ci«, »log«)
  treffen nur ganze Wörter (und die Mehrzahl auf »s«).
* **Felder gewichtet (BM25F):** Name/ID zählt dreifach, Titel doppelt, Zweck/Beschreibung einfach. Selten vorkommende
  Wörter zählen mehr (IDF); wer mehr der Suchwörter trifft, steht vor dem, der nur eines mehrfach trifft.
* **Alle Wörter zuerst:** Treffen Werkzeuge alle Suchwörter, kommen nur diese; sonst die besten Teiltreffer
  (``teil``) — wie bisher.
* **Rangwert** 0..1 (bester = 1) und eine Obergrenze (Vorgabe 10); ``voll``/``limit`` holt mehr.

Reine Standardbibliothek.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from . import ansicht

K1 = 1.2
LIMIT = 10
_NICHT_WORT = re.compile(r"[^a-z0-9]+")


def tokens(text: str | None) -> list[str]:
    """Kleingeschriebene Wörter ohne Umlaute; ``_ . / - :`` trennen (``ci_laeufe`` -> ``ci``, ``laeufe``)."""
    return [t for t in _NICHT_WORT.split(ansicht._norm(text or "")) if t]


def passt(wort: str, token: str) -> float:
    """Wie gut ein Suchwort ein Wort des Textes trifft: 1,0 ganz, 0,7 Anfang/Mehrzahl, 0,5 Teil eines langen Wortes."""
    if wort == token:
        return 1.0
    n = len(wort)
    if n <= 3:
        return 0.7 if token == wort + "s" else 0.0
    if token.startswith(wort) or (len(token) >= 4 and wort.startswith(token)):
        return 0.7
    if n >= 5 and wort in token:
        return 0.5
    return 0.0


class Bm25F:
    """BM25 über Dokumente mit mehreren gewichteten Feldern. ``dokumente`` = Liste von {Feld: Text}."""

    def __init__(self, dokumente: list[dict[str, str]], gewichte: dict[str, float], b: dict[str, float] | None = None):
        self.gewichte = gewichte
        self.b = b or {}
        self.tf: list[dict[str, Counter]] = []
        self.laenge: list[dict[str, int]] = []
        for d in dokumente:
            tf = {f: Counter(tokens(d.get(f))) for f in gewichte}
            self.tf.append(tf)
            self.laenge.append({f: sum(c.values()) for f, c in tf.items()})
        n = max(1, len(dokumente))
        self.mittel = {f: max(1.0, sum(l[f] for l in self.laenge) / n) for f in gewichte}
        self.vokabular: set[str] = set()
        self.df: Counter = Counter()
        for tf in self.tf:
            woerter = set().union(*(c.keys() for c in tf.values()))
            self.vokabular |= woerter
            self.df.update(woerter)
        self.n = len(dokumente)

    def formen(self, wort: str, synonyme: tuple[str, ...] = ()) -> dict[str, float]:
        """Wörter des Vokabulars, die das Suchwort (oder ein Synonym) trifft, mit Gewicht."""
        m: dict[str, float] = {}
        for rang, f in enumerate((wort, *synonyme)):
            for v in self.vokabular:
                g = passt(f, v) * (1.0 if rang == 0 else 0.8)
                if g > m.get(v, 0.0):
                    m[v] = g
        return m

    def werte(self, woerter: list[str], synonyme: dict[str, tuple[str, ...]] | None = None) -> tuple[list[float], list[int]]:
        """(Wert, Zahl getroffener Suchwörter) je Dokument."""
        synonyme = synonyme or {}
        wert = [0.0] * self.n
        getroffen = [0] * self.n
        for w in woerter:
            m = self.formen(w, synonyme.get(w, ()))
            if not m:
                continue
            docs_mit = [i for i in range(self.n) if any(any(v in c for v in m) for c in self.tf[i].values())]
            if not docs_mit:
                continue
            idf = math.log(1 + (self.n - len(docs_mit) + 0.5) / (len(docs_mit) + 0.5))
            for i in docs_mit:
                tfk = 0.0
                for f, gw in self.gewichte.items():
                    roh = sum(g * self.tf[i][f].get(v, 0) for v, g in m.items())
                    if roh:
                        b = self.b.get(f, 0.5)
                        tfk += gw * roh / (1 - b + b * self.laenge[i][f] / self.mittel[f])
                if tfk:
                    wert[i] += idf * tfk * (K1 + 1) / (K1 + tfk)
                    getroffen[i] += 1
        return wert, getroffen


def rang_aus_werten(werte: list[float], getroffen: list[int], n_woerter: int) -> tuple[list[int], bool]:
    """Indizes bester zuerst. Treffen welche ALLE Wörter, nur diese; sonst die Teiltreffer (zweiter Wert True)."""
    voll = [i for i, g in enumerate(getroffen) if n_woerter and g >= n_woerter]
    teil = False
    if voll:
        wahl = voll
    else:
        wahl = [i for i, g in enumerate(getroffen) if g > 0]
        teil = n_woerter > 1 and bool(wahl)
    # Teiltreffer: mehr getroffene Wörter vor höherem Wert
    wahl.sort(key=lambda i: (-getroffen[i], -werte[i], i) if teil else (-werte[i], i))
    return wahl, teil


# ── Werkzeuge des Hubs ─────────────────────────────────────────────────────────────────────────────────


def rangliste(
    alle: list[dict[str, Any]],
    query: str,
    hybrid: Any = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Werkzeuge zur Suche, bestes zuerst; zweiter Wert True = nur Teiltreffer (MCP- und REST-Suche).

    ``alle`` = Katalog (Dicts mit name, description); ``hybrid`` = Hybrid-Stufe (``mcp_hub.hybrid.HYBRID``) oder None.
    Jedes Ergebnis trägt ``wert`` (0..1, bester = 1).
    """
    woerter = ansicht.suchwoerter(query)
    treffer: list[dict[str, Any]] = []
    teil = False
    for teil in (False, True):
        bewertet = [(ansicht.treffer_wert(t["name"], t.get("description") or "", woerter, teil=teil), t) for t in alle]
        sortiert = [(w, t) for w, t in sorted(bewertet, key=lambda p: (-p[0], p[1]["name"])) if w > 0]
        treffer = [t for _, t in sortiert]
        if treffer or len(woerter) < 2:
            break
    gemischt = hybrid.mische(alle, query, treffer) if hybrid is not None else None
    if gemischt is not None:
        liste, ist_teil = gemischt, bool(gemischt) and (teil or not treffer)
        roh = {t["name"]: t.get("_rrf", 0.0) for t in liste}
    else:
        liste, ist_teil = treffer, teil and bool(treffer)
        roh = {t["name"]: float(w) for w, t in sortiert} if treffer else {}
    _wert_setzen(liste, roh)
    return liste, ist_teil


def _wert_setzen(liste: list[dict[str, Any]], roh: dict[str, float]) -> None:
    """Rangwert 0..1 = Wert des Treffers durch den des besten (Hybrid: RRF-Wert; sonst Wortwertung)."""
    top = max((roh.get(t["name"], 0.0) for t in liste), default=0.0) or 1.0
    for t in liste:
        t["wert"] = round(roh.get(t["name"], 0.0) / top, 2)
        t.pop("_rrf", None)


# ── Werkstatt-Skripte ──────────────────────────────────────────────────────────────────────────────────

SKRIPT_FELDER = {"id": 3.0, "titel": 2.0, "zweck": 1.0}
SKRIPT_B = {"id": 0.3, "titel": 0.5, "zweck": 0.75}
#: Gewicht der Dichte-Rangfolge gegen die Wortsuche im RRF (1,5 hat sich bewährt)
DICHT_GEWICHT = 1.5
DICHT_TIEFE = 10
#: Findet die Wortsuche nichts, zeigt die Dichtesuche höchstens so viele ähnliche Skripte (als solche gekennzeichnet)
AEHNLICH_MAX = 3


def skript_dokument(e: dict[str, Any]) -> dict[str, Any]:
    """Skript als Katalogeintrag der Hybrid-Stufe (Name = id, Beschreibung = Titel + Zweck)."""
    return {"name": e["id"], "description": f"{e.get('titel') or ''}. {e.get('zweck') or ''}"}


def skripte_rang(
    eintraege: list[dict[str, Any]],
    q: str,
    hybrid: Any = None,
    synonyme: dict[str, tuple[str, ...]] | None = None,
) -> tuple[list[tuple[dict[str, Any], float, str]], bool]:
    """Werkstatt-Skripte zu ``q``: [(Eintrag, Rangwert 0..1, Art)] bester zuerst.

    Art ``wort`` = die Wortsuche (BM25F) trifft, ``aehnlich`` = nur die Dichtesuche (Embeddings) hält es für
    verwandt. Zweiter Wert True = nur Teiltreffer (nicht alle Suchwörter). Ohne ``hybrid`` oder wenn der Einbetter
    nicht antwortet, gilt allein die Wortsuche.
    """
    woerter = [t for w in ansicht.suchwoerter(q) for t in tokens(w)]
    if not woerter or not eintraege:
        return [], False
    docs = [{"id": e["id"], "titel": e.get("titel") or "", "zweck": e.get("zweck") or ""} for e in eintraege]
    idx = Bm25F(docs, SKRIPT_FELDER, SKRIPT_B)
    werte, getroffen = idx.werte(woerter, synonyme if synonyme is not None else ansicht.SYNONYME)
    reihe, teil = rang_aus_werten(werte, getroffen, len(woerter))
    wort_ids = [eintraege[i]["id"] for i in reihe]
    nach_id = {e["id"]: e for e in eintraege}
    dicht = hybrid.dicht_rang([skript_dokument(e) for e in eintraege], q) if hybrid is not None else None
    if dicht is None:
        if not reihe:
            return [], False
        top = max(werte[i] for i in reihe) or 1.0
        return [(eintraege[i], round(werte[i] / top, 2), "wort") for i in reihe], teil
    if not wort_ids:
        if len(woerter) < 2:
            return [], False  # ein einzelnes Wort ohne Wortbezug (»ci«, »modell«): ehrlich nichts, nicht Ratetreffer
        rest = dicht[:AEHNLICH_MAX]
        return [(nach_id[n], round(1.0 / (1 + 0.1 * k), 2), "aehnlich") for k, n in enumerate(rest)], False
    s: dict[str, float] = {}
    for gewicht, liste in ((1.0, wort_ids), (DICHT_GEWICHT, dicht[:DICHT_TIEFE])):
        for r, n in enumerate(liste):
            s[n] = s.get(n, 0.0) + gewicht / (60 + r + 1)
    geordnet = sorted(s.items(), key=lambda p: (-p[1], p[0]))
    top = geordnet[0][1]
    wort = set(wort_ids)
    return [(nach_id[n], round(w / top, 2), "wort" if n in wort else "aehnlich") for n, w in geordnet], teil


