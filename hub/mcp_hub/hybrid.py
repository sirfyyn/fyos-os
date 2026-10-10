"""Hybrid-Stufe der Werkzeugsuche: Wortwertung + BM25 + Embeddings, verschmolzen per RRF.

Ablauf je Anfrage: die Wortwertung (``server.rangliste``) liefert ihre Liste; dazu kommen eine BM25-Rangfolge und die
Embedding-Rangfolge (Kosinus gegen die Katalog-Vektoren). RRF (k=60) mischt die drei. Die Antwort enthaelt die
Worttreffer plus die besten ``ZUSATZ`` aus BM25 und Embedding — die Liste waechst also nicht auf den ganzen Katalog.

Die Embeddings kommen von einem OpenAI-kompatiblen Dienst (``POST <basis>/v1/embeddings``), eingestellt mit
``HUB_SUCHE_EMBED_URL`` (oder ``FYOS_EMBED_URL``) und optional ``HUB_SUCHE_EMBED_MODEL``. Modelle, die fuer Anfrage und
Dokument verschiedene Vorsaetze verlangen, stellt man ueber ``HUB_SUCHE_ANFRAGE_FORMAT`` und
``HUB_SUCHE_DOKUMENT_FORMAT`` ein (``{q}`` bzw. ``{n}`` und ``{t}`` als Platzhalter; Vorgabe: roher Text).

Rueckfall: ohne Dienst, solange die Katalog-Vektoren noch entstehen oder wenn der Einbetter nicht binnen
``HUB_SUCHE_EMBED_TIMEOUT_S`` antwortet, gibt ``mische`` None und die Suche bleibt reine Wortwertung. Nach
einem Fehler ruht der Einbetter ``PAUSE_S`` Sekunden, damit nicht jede Suche den Timeout abwartet.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import urllib.request
from collections import Counter, OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

EMBED_URL = (os.getenv("HUB_SUCHE_EMBED_URL") or os.getenv("FYOS_EMBED_URL") or "").strip().rstrip("/")
EMBED_MODELL = (os.getenv("HUB_SUCHE_EMBED_MODEL") or os.getenv("FYOS_EMBED_MODEL") or "embedding").strip()
TIMEOUT_S = float(os.getenv("HUB_SUCHE_EMBED_TIMEOUT_S", "0.5"))
PAUSE_S = 60.0
NEUVERSUCH_S = 300.0
RRF_K = 60
ZUSATZ = 10
STAPEL = 16

# Formate fuer Anfrage und Dokument; Vorgabe: roher Text (manche Modelle verlangen Vorsaetze, siehe oben).
ANFRAGE = os.getenv("HUB_SUCHE_ANFRAGE_FORMAT") or "{q}"
DOKUMENT = os.getenv("HUB_SUCHE_DOKUMENT_FORMAT") or "{n} {t}"

_UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _tok(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", s.lower().translate(_UML)) if len(w) > 1]


def _namenwoerter(name: str) -> str:
    return name.replace(".", " ").replace("_", " ")


def _doctext(t: dict[str, Any], n: int = 1000) -> str:
    return (t.get("description") or "").strip().replace("\n", " ")[:n]


def _norm(v: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / s for x in v]


try:
    import numpy as _np
except ImportError:  # pragma: no cover — ohne numpy rechnet math.sumprod
    _np = None

try:
    _skalar = math.sumprod  # Python >= 3.12
except AttributeError:  # pragma: no cover
    def _skalar(a: list[float], b: list[float]) -> float:
        return sum(map(float.__mul__, a, b))


def rrf_werte(*listen: list[str], k: int = RRF_K) -> dict[str, float]:
    s: Counter[str] = Counter()
    for liste in listen:
        for r, n in enumerate(liste):
            s[n] += 1.0 / (k + r + 1)
    return dict(s)


def rrf(*listen: list[str], k: int = RRF_K) -> list[str]:
    s = rrf_werte(*listen, k=k)
    return [n for n, _ in sorted(s.items(), key=lambda p: (-p[1], p[0]))]


class _Bm25:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self.namen = [t["name"] for t in tools]
        # Name doppelt: er ist das staerkste Signal (wie in R2 gemessen).
        docs = [_tok(_namenwoerter(t["name"]) * 2 + " " + _doctext(t)) for t in tools]
        self.laengen = [len(d) for d in docs]
        self.avg = (sum(self.laengen) / len(docs)) if docs else 1.0
        self.df = Counter(w for d in docs for w in set(d))
        self.tf = [Counter(d) for d in docs]

    def rang(self, query: str, k1: float = 1.2, b: float = 0.75) -> list[str]:
        q = _tok(query)
        n = len(self.tf)
        werte = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w in tf:
                    idf = math.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5))
                    s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * self.laengen[i] / self.avg))
            werte.append(s)
        return [self.namen[i] for i in sorted(range(n), key=lambda i: (-werte[i], self.namen[i])) if werte[i] > 0]


def _post_embeddings(texte: list[str], timeout: float) -> list[list[float]]:
    kopf = {"Content-Type": "application/json"}
    if os.getenv("FYOS_EMBED_KEY"):
        kopf["Authorization"] = "Bearer " + os.environ["FYOS_EMBED_KEY"]
    req = urllib.request.Request(
        EMBED_URL + "/v1/embeddings",
        data=json.dumps({"model": EMBED_MODELL, "input": texte}).encode(),
        headers=kopf,
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (Adresse aus der Konfiguration)
        daten = json.loads(r.read())["data"]
    return [_norm(d["embedding"]) for d in sorted(daten, key=lambda d: d["index"])]


class Hybrid:
    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self._bm25: _Bm25 | None = None
        self._bm25_schluessel: tuple[str, ...] = ()
        self._vektoren: dict[str, list[float]] = {}  # Dokumenttext -> Vektor (ueberlebt Katalogwechsel)
        self._baut = False
        self._bau_fehler_bis = 0.0
        self._pause_bis = 0.0
        self._anfragen: OrderedDict[str, list[float]] = OrderedDict()
        self._texte: list[str] = []
        self._texte_schluessel: tuple = ()
        self._matrix_paar: tuple | None = None

    @property
    def an(self) -> bool:
        return bool(EMBED_URL)

    # ── Katalog ──────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _text(t: dict[str, Any]) -> str:
        return DOKUMENT.format(n=_namenwoerter(t["name"]), t=_doctext(t))

    def _bm25_fuer(self, tools: list[dict[str, Any]]) -> _Bm25:
        schluessel = tuple(t["name"] for t in tools)
        with self._sperre:
            if self._bm25 is None or schluessel != self._bm25_schluessel:
                self._bm25 = _Bm25(tools)
                self._bm25_schluessel = schluessel
            return self._bm25

    def vorwaermen(self, tools: list[dict[str, Any]]) -> None:
        """Fehlende Katalog-Vektoren im Hintergrund holen (nie blockierend)."""
        if not self.an:
            return
        fehlend = [x for x in dict.fromkeys(self._text(t) for t in tools) if x not in self._vektoren]
        with self._sperre:
            if not fehlend or self._baut or time.monotonic() < self._bau_fehler_bis:
                return
            self._baut = True
        threading.Thread(target=self._baue, args=(fehlend,), name="hub-suche-vektoren", daemon=True).start()

    def _baue(self, texte: list[str]) -> None:
        t0 = time.monotonic()
        try:
            for i in range(0, len(texte), STAPEL):
                stapel = texte[i:i + STAPEL]
                for text, v in zip(stapel, _post_embeddings(stapel, timeout=120)):
                    self._vektoren[text] = v
            logger.info("hub-suche: %d Katalog-Vektoren in %.1f s", len(texte), time.monotonic() - t0)
        except Exception as exc:  # noqa: BLE001
            self._bau_fehler_bis = time.monotonic() + NEUVERSUCH_S
            logger.warning("hub-suche: Katalog-Vektoren unvollstaendig (%s) — Wortwertung bis zum Neuversuch", exc)
        finally:
            with self._sperre:
                self._baut = False

    # ── Anfrage ──────────────────────────────────────────────────────────────────────────────────────────
    def _anfrage_vektor(self, query: str) -> list[float] | None:
        if query in self._anfragen:
            self._anfragen.move_to_end(query)
            return self._anfragen[query]
        if time.monotonic() < self._pause_bis:
            return None
        try:
            v = _post_embeddings([ANFRAGE.format(q=query)], timeout=TIMEOUT_S)[0]
        except Exception as exc:  # noqa: BLE001
            self._pause_bis = time.monotonic() + PAUSE_S
            logger.warning("hub-suche: Einbetter antwortet nicht (%s) — %ds nur Wortwertung", exc, int(PAUSE_S))
            return None
        self._anfragen[query] = v
        while len(self._anfragen) > 512:
            self._anfragen.popitem(last=False)
        return v

    def _werte(self, qv: list[float], texte: list[str]) -> list[float]:
        """Kosinus gegen alle Katalog-Vektoren. Mit numpy (optional) ist das deutlich schneller als die reine
        Python-Summe."""
        if _np is None:
            return [_skalar(qv, self._vektoren[x]) for x in texte]
        paar = self._matrix_paar
        if paar is None or paar[0] is not texte:
            paar = (texte, _np.asarray([self._vektoren[x] for x in texte], dtype=_np.float32))
            self._matrix_paar = paar
        return (paar[1] @ _np.asarray(qv, dtype=_np.float32)).tolist()

    def dicht_rang(self, tools: list[dict[str, Any]], query: str) -> list[str] | None:
        """Namen der ``tools`` nach Embedding-Kosinus, beste zuerst; None = nicht verfuegbar (kein Einbetter, Vektoren im
        Bau, Timeout) — der Aufrufer faellt auf die Wortsuche zurueck. Fuer Kataloge ausser den Hub-Werkzeugen
        (z. B. Werkstatt): eine eigene ``Hybrid``-Instanz je Katalog."""
        if not self.an or not query.strip() or not tools:
            return None
        schluessel = tuple((t["name"], len(t.get("description") or "")) for t in tools)
        if schluessel != self._texte_schluessel:
            self._texte, self._texte_schluessel = [self._text(t) for t in tools], schluessel
        if any(x not in self._vektoren for x in self._texte):
            self.vorwaermen(tools)
            return None
        qv = self._anfrage_vektor(query.strip())
        if qv is None:
            return None
        werte = self._werte(qv, self._texte)
        namen = [t["name"] for t in tools]
        return [namen[i] for i in sorted(range(len(namen)), key=lambda i: -werte[i])]

    def mische(self, tools: list[dict[str, Any]], query: str, wort: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        """RRF aus Wortwertung, BM25 und Embedding; None = Rueckfall auf die Wortwertung."""
        if not self.an or not query.strip() or not tools:
            return None
        schluessel = tuple((t["name"], len(t.get("description") or "")) for t in tools)
        if schluessel != self._texte_schluessel:
            self._texte, self._texte_schluessel = [self._text(t) for t in tools], schluessel
        texte = self._texte
        if any(x not in self._vektoren for x in texte):
            self.vorwaermen(tools)
            return None
        qv = self._anfrage_vektor(query.strip())
        if qv is None:
            return None
        namen = [t["name"] for t in tools]
        werte = self._werte(qv, texte)
        emb = [namen[i] for i in sorted(range(len(namen)), key=lambda i: -werte[i])]
        bm = self._bm25_fuer(tools).rang(query)
        wort_namen = [t["name"] for t in wort]
        behalten = set(wort_namen) | set(bm[:ZUSATZ]) | set(emb[:ZUSATZ])
        nach_name = {t["name"]: t for t in tools}
        werte = rrf_werte(wort_namen, bm, emb)
        geordnet = [n for n, _ in sorted(werte.items(), key=lambda p: (-p[1], p[0])) if n in behalten]
        for n in geordnet:
            nach_name[n]["_rrf"] = werte[n]  # fuer den Rangwert (suchrang); wird dort wieder entfernt
        return [nach_name[n] for n in geordnet]


HYBRID = Hybrid()
