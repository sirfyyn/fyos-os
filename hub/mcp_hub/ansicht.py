"""ansicht — knappe und ausführliche Ansicht für Modelle.

Modelle sollen nicht mit Token zugeschüttet werden, sondern effizient finden, was sie brauchen. Große Listen
(Workloads, Bestände, Übersichten, ein Katalog ohne Suchwort) gingen sonst ungekürzt ans Modell. Diese Schicht sitzt
einmal im Hub und gilt damit für jedes Werkzeug, ohne dass ein Plugin etwas tun muss:

  kurz      Ergebnisse über dem Budget werden gekürzt: Listen zeigen die ersten Einträge mit ihren Kernfeldern,
            dazu Anzahl und alle verfügbaren Felder; lange Texte werden abgeschnitten. Kleine Ergebnisse bleiben,
            wie sie sind. Das volle Ergebnis liegt 15 min unter einer `ergebnis_id`.
  mehr      `hub__mehr` holt aus dieser Ablage gezielt nach — Pfad, Felder, Filter, Suche, Seite —, ohne das
            Werkzeug noch einmal zu rufen.
  lernen    Felder, die über `hub__mehr` nachgefragt werden, merkt sich der Hub je Werkzeug und Liste; ab der
            zweiten Nachfrage stehen sie in der kurzen Ansicht von selbst. `hub__ansicht_merken` legt eine Sicht
            ausdrücklich ab. Was 30 Tage niemand nutzt, verfällt (Redis-TTL) — Neues kommt dazu, Altes geht.
  Plugins   können eine Sicht mitliefern: `meta["kurz"] = {"<pfad>": ["feld", ...]}` am Werkzeug.

Die Oberflächen (REST `/hub/call`, `/hub/app-call`, `structuredContent` der App-Werkzeuge) bekommen weiter alles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: Zeichenbudget der kurzen Ansicht (≈ 1 Token je 3–4 Zeichen). Je Aufrufer überschreibbar.
BUDGET = int(os.getenv("HUB_ANSICHT_BUDGET", "4000"))
#: Teilzeichenkette im Aufrufer (AUFRUFER, z. B. "mcp:meinclient") → Budget. Vorgabe: keine Sonderfälle;
#: Modelle mit kleinem Kontext trägt man hier oder zur Laufzeit mit `BUDGET_JE_AUFRUFER["name"] = 3000` ein.
BUDGET_JE_AUFRUFER: dict[str, int] = {}
#: Wie lange ein volles Ergebnis abrufbar bleibt (Sekunden).
ABLAGE_SEKUNDEN = 15 * 60
#: Gelernte Sichten verfallen, wenn 30 Tage niemand sie nutzt.
SICHT_SEKUNDEN = 30 * 24 * 3600
#: Ab so vielen Nachfragen gehört ein Feld zur kurzen Ansicht.
LERN_SCHWELLE = 2

#: Felder, die in Listen fast immer tragen — Name, Zustand, Grund. Reihenfolge = Vorrang.
KERN = (
    "id", "name", "titel", "title", "key", "tool", "status", "zustand", "state", "phase", "ok", "ready",
    "healthy", "grund", "reason", "fehler", "error", "art", "kind", "typ", "type", "namespace", "knoten",
    "node", "wert", "value", "jetzt", "einheit", "anzahl", "count", "satz", "summary", "zusammenfassung",
    "dringlich", "prioritaet",
)
#: Stufen der Kürzung: (Einträge je Liste, Zeichen je Text, Tiefe). Die erste, die ins Budget passt, gilt.
#: Erst Einträge und Texte, die Tiefe zuletzt — sonst verliert eine Liste in einer Liste ihre Felder ganz.
STUFEN = ((8, 200, 6), (5, 140, 6), (3, 100, 6), (2, 60, 6), (2, 40, 4), (1, 40, 3), (1, 30, 2))

#: Nach einem Redis-Fehler so lange nur im Speicher des Pods.
REDIS_PAUSE_S = 60.0

_ID = re.compile(r"^[0-9a-f]{16}$")


# ── Ablage (Redis, mehrere Hub-Prozesse teilen sie; ohne Redis im Speicher des Pods) ─────────────────────────


class Ablage:
    def __init__(self, redis: Any = None) -> None:
        self._redis = redis
        self._redis_versucht = redis is not None
        self._speicher: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._aus_bis = 0.0

    def _gestoert(self, was: str, schluessel: str, exc: Exception) -> None:
        """Redis hakt: 60 s lang nur im Pod, statt bei jedem Zugriff das Zeitlimit abzuwarten."""
        self._aus_bis = time.time() + REDIS_PAUSE_S
        logger.info("ansicht: Redis %s %s: %s — %g s nur im Pod", was, schluessel, exc, REDIS_PAUSE_S)

    def redis(self) -> Any:
        if self._aus_bis > time.time():
            return None
        if not self._redis_versucht:
            self._redis_versucht = True
            try:
                import redis  # noqa: PLC0415 — im Hub-Image vorhanden

                url = os.getenv("REDIS_URL")
                if not url:
                    logger.info("ansicht: kein REDIS_URL — Ablage nur im Pod")
                    return None
                self._redis = redis.Redis.from_url(url, socket_timeout=2, decode_responses=True)
            except Exception as exc:  # noqa: BLE001
                logger.info("ansicht: kein Redis (%s) — Ablage nur im Pod", exc)
        return self._redis

    def setzen(self, schluessel: str, wert: str, sekunden: int) -> None:
        r = self.redis()
        if r is not None:
            try:
                r.set(schluessel, wert, ex=sekunden)
                return
            except Exception as exc:  # noqa: BLE001
                self._gestoert("set", schluessel, exc)
        with self._lock:
            self._speicher[schluessel] = (time.time() + sekunden, wert)
            if len(self._speicher) > 256:  # die ältesten zuerst
                for k in sorted(self._speicher, key=lambda k: self._speicher[k][0])[:64]:
                    self._speicher.pop(k, None)

    def holen(self, schluessel: str) -> str | None:
        r = self.redis()
        if r is not None:
            try:
                wert = r.get(schluessel)
                if wert is not None:
                    return wert
            except Exception as exc:  # noqa: BLE001
                self._gestoert("get", schluessel, exc)
        with self._lock:
            ablauf, wert = self._speicher.get(schluessel, (0.0, None))
        return wert if ablauf > time.time() else None

    def zaehlen(self, schluessel: str, feld: str, um: int, sekunden: int) -> None:
        r = self.redis()
        if r is not None:
            try:
                r.hincrby(schluessel, feld, um)
                r.expire(schluessel, sekunden)
                return
            except Exception as exc:  # noqa: BLE001
                self._gestoert("hincrby", schluessel, exc)
        with self._lock:
            _, alt = self._speicher.get(schluessel, (0.0, "{}"))
            d = json.loads(alt or "{}")
            d[feld] = int(d.get(feld, 0)) + um
            self._speicher[schluessel] = (time.time() + sekunden, json.dumps(d))

    def zaehlen_viele(self, schluessel: str, um: dict[str, int], sekunden: int) -> None:
        """Mehrere Felder eines Zählers in einem Rutsch (Redis-Pipeline) — für die Messung je Aufruf."""
        r = self.redis()
        if r is not None:
            try:
                pipe = r.pipeline()
                for feld, n in um.items():
                    pipe.hincrby(schluessel, feld, n)
                pipe.expire(schluessel, sekunden)
                pipe.execute()
                return
            except Exception as exc:  # noqa: BLE001
                self._gestoert("pipeline", schluessel, exc)
        for feld, n in um.items():
            self.zaehlen(schluessel, feld, n, sekunden)

    def zaehler(self, schluessel: str) -> dict[str, int]:
        r = self.redis()
        if r is not None:
            try:
                return {k: int(v) for k, v in (r.hgetall(schluessel) or {}).items()}
            except Exception as exc:  # noqa: BLE001
                self._gestoert("hgetall", schluessel, exc)
        with self._lock:
            ablauf, wert = self._speicher.get(schluessel, (0.0, "{}"))
        return {k: int(v) for k, v in json.loads(wert or "{}").items()} if ablauf > time.time() else {}


ABLAGE = Ablage()


# ── Messung: was die kurze Ansicht je Aufrufer spart (damit die Ersparnis messbar ist) ─────────────

#: Tageszähler leben so lange; gezeigt werden die letzten Tage nach Wahl.
MESS_SEKUNDEN = 35 * 24 * 3600


def _mess_schluessel(tag: str) -> str:
    return f"hub:ansichtmessung:{tag}"


def _heute(jetzt: datetime | None = None) -> str:
    return (jetzt or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def messen(aufrufer: str | None, *, voll: int = 0, kurz: int = 0, gekuerzt: bool = False, nachgeholt: int = 0) -> None:
    """Ein Modell-Aufruf (voll/kurz in Zeichen) oder ein Nachholen über `hub__mehr` (nachgeholt) — nur Zähler, keine Inhalte."""
    wer = (aufrufer or "unbekannt").replace("|", "/")[:60]
    um = {"aufrufe": 1, "voll": voll, "kurz": kurz, "gekuerzt": int(gekuerzt)} if not nachgeholt else {"mehr": 1, "nachgeholt": nachgeholt}
    try:
        ABLAGE.zaehlen_viele(_mess_schluessel(_heute()), {f"{wer}|{k}": int(v) for k, v in um.items() if v}, MESS_SEKUNDEN)
    except Exception as exc:  # noqa: BLE001 — Messen darf keinen Aufruf scheitern lassen
        logger.info("ansicht: Messung %s: %s", wer, exc)


def messung(tage: int = 7, jetzt: datetime | None = None) -> dict[str, Any]:
    """Summe der letzten `tage` Tage je Aufrufer: Zeichen voll gegen kurz plus Nachgeholtes."""
    jetzt = jetzt or datetime.now(timezone.utc)
    summen: dict[str, dict[str, int]] = {}
    for i in range(max(1, tage)):
        for schluessel, n in ABLAGE.zaehler(_mess_schluessel(_heute(jetzt - timedelta(days=i)))).items():
            wer, _, feld = schluessel.rpartition("|")
            if wer:
                summen.setdefault(wer, {})[feld] = summen.get(wer, {}).get(feld, 0) + n

    def zeile(wer: str, s: dict[str, int]) -> dict[str, Any]:
        voll, bekommen = s.get("voll", 0), s.get("kurz", 0) + s.get("nachgeholt", 0)
        return {"aufrufer": wer, "aufrufe": s.get("aufrufe", 0), "gekuerzt": s.get("gekuerzt", 0),
                "zeichen_voll": voll, "zeichen_kurz": s.get("kurz", 0), "mehr": s.get("mehr", 0),
                "zeichen_nachgeholt": s.get("nachgeholt", 0),
                "gespart_prozent": round(100 * (1 - bekommen / voll), 1) if voll else None}

    zeilen = sorted((zeile(w, s) for w, s in summen.items()), key=lambda z: -z["zeichen_voll"])
    gesamt: dict[str, int] = {}
    for s in summen.values():
        for k, v in s.items():
            gesamt[k] = gesamt.get(k, 0) + v
    return {"tage": tage, "aufrufer": zeilen, "gesamt": zeile("alle", gesamt),
            "hinweis": "Zeichen ≈ Tokens × 3–4. gespart = 1 − (kurz + nachgeholt) / voll; nur Aufrufe von Modellen."}


def budget_fuer(aufrufer: str | None) -> int:
    wer = (aufrufer or "").lower()
    for teil, b in BUDGET_JE_AUFRUFER.items():
        if teil in wer:
            return b
    return BUDGET


def _laenge(x: Any) -> int:
    return len(json.dumps(x, ensure_ascii=False, default=str, separators=(",", ":")))


def _pfad_muster(pfad: str) -> str:
    """`deployments.3.pods` → `deployments.pods`: Sichten gelten je Liste, nicht je Eintrag."""
    return ".".join(t for t in pfad.split(".") if t and not t.isdigit())


# ── Gelernte und mitgelieferte Sichten ────────────────────────────────────────────────────────────────


def _sicht_schluessel(tool: str) -> str:
    return f"hub:ansicht:{tool}"


def sicht(tool: str, plugin_sicht: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Felder je Listenpfad, die in der kurzen Ansicht stehen: mitgeliefert + gelernt (ab LERN_SCHWELLE)."""
    felder: dict[str, list[str]] = {k: list(v) for k, v in (plugin_sicht or {}).items()}
    for schluessel, n in ABLAGE.zaehler(_sicht_schluessel(tool)).items():
        if n < LERN_SCHWELLE or "|" not in schluessel:
            continue
        pfad, feld = schluessel.split("|", 1)
        liste = felder.setdefault(pfad, [])
        if feld not in liste:
            liste.append(feld)
    return felder


def sicht_bericht(tool: str, plugin_sicht: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Was Modelle von diesem Werkzeug in der kurzen Ansicht sehen und warum — für die MCP-App.

    Je Feld: Listenpfad, Herkunft (`plugin` = mitgeliefert, `gelernt` = ab LERN_SCHWELLE Nachfragen, `lernt` = gefragt,
    aber noch darunter) und Zahl der Nachfragen. Ohne Eintrag gelten die Kernfelder (`KERN`).
    """
    felder: dict[tuple[str, str], dict[str, Any]] = {}
    for pfad, liste in (plugin_sicht or {}).items():
        for f in liste:
            felder[(pfad, f)] = {"pfad": pfad, "feld": f, "herkunft": "plugin", "nachfragen": 0}
    for schluessel, n in ABLAGE.zaehler(_sicht_schluessel(tool)).items():
        if "|" not in schluessel:
            continue
        pfad, feld = schluessel.split("|", 1)
        e = felder.setdefault((pfad, feld), {"pfad": pfad, "feld": feld, "herkunft": "lernt", "nachfragen": 0})
        e["nachfragen"] = n
        if e["herkunft"] != "plugin" and n >= LERN_SCHWELLE:
            e["herkunft"] = "gelernt"
    rang = {"plugin": 0, "gelernt": 1, "lernt": 2}
    return {
        "felder": sorted(felder.values(), key=lambda e: (rang[e["herkunft"]], e["pfad"], -e["nachfragen"], e["feld"])),
        "kern": list(KERN),
        "budget": {"standard": BUDGET, **BUDGET_JE_AUFRUFER},
        "schwelle": LERN_SCHWELLE,
        "verfall_tage": SICHT_SEKUNDEN // 86400,
    }


def lernen(tool: str, pfad: str, felder: list[str], gewicht: int = 1) -> None:
    for f in felder:
        ABLAGE.zaehlen(_sicht_schluessel(tool), f"{_pfad_muster(pfad)}|{f}", gewicht, SICHT_SEKUNDEN)


def merken(tool: str, pfad: str, felder: list[str]) -> dict[str, Any]:
    """Ausdrücklich abgelegte Sicht: zählt sofort über der Schwelle."""
    felder = [str(f) for f in felder if str(f).strip()][:30]
    if not felder:
        return {"ok": False, "error": "felder fehlt", "kind": "bad_request"}
    lernen(tool, pfad, felder, gewicht=LERN_SCHWELLE)
    return {"ok": True, "tool": tool, "pfad": _pfad_muster(pfad), "felder": felder,
            "gilt": f"ab jetzt in der kurzen Ansicht; verfällt nach {SICHT_SEKUNDEN // 86400} Tagen ohne Nutzung"}


# ── Kürzen ────────────────────────────────────────────────────────────────────────────────────────────


def _projizieren(eintrag: dict[str, Any], extra: list[str]) -> dict[str, Any]:
    gewaehlt = [k for k in extra if k in eintrag]
    gewaehlt += [k for k in KERN if k in eintrag and k not in gewaehlt]
    if not extra:  # verschachtelte Listen nicht still verlieren (sonst bleibt fast das ganze Budget ungenutzt)
        gewaehlt += [k for k, v in eintrag.items() if isinstance(v, list) and v and k not in gewaehlt][:2]
    if not gewaehlt:  # unbekannte Form: die ersten einfachen Felder
        gewaehlt = [k for k, v in eintrag.items() if not isinstance(v, (dict, list))][:4] or list(eintrag)[:3]
    return {k: eintrag[k] for k in gewaehlt[: max(6, len(extra))]}


def _kuerze(x: Any, stufe: tuple[int, int, int], sicht_: dict[str, list[str]], pfad: str,
            listen: dict[str, dict[str, Any]]) -> Any:
    n_liste, n_text, tiefe = stufe
    if isinstance(x, str):
        return x if len(x) <= n_text else x[:n_text] + f"… (+{len(x) - n_text} Zeichen)"
    if isinstance(x, dict):
        if tiefe <= 0:
            return {"_felder": list(x)[:20]}
        return {k: _kuerze(v, (n_liste, n_text, tiefe - 1), sicht_, f"{pfad}.{k}" if pfad else str(k), listen)
                for k, v in x.items()}
    if isinstance(x, list):
        muster = _pfad_muster(pfad)
        dicts = [e for e in x if isinstance(e, dict)]
        alle_felder: list[str] = []
        for e in dicts[:50]:
            alle_felder += [k for k in e if k not in alle_felder]
        teile = x[:n_liste]
        if dicts:
            teile = [_projizieren(e, sicht_.get(muster, [])) if isinstance(e, dict) else e for e in teile]
        gezeigt = [_kuerze(e, (n_liste, n_text, tiefe - 1), sicht_, f"{pfad}.{i}", listen)
                   for i, e in enumerate(teile)]
        if len(x) > n_liste or (dicts and any(len(t) < len(e) for t, e in zip(teile, x) if isinstance(e, dict))):
            listen[pfad or "."] = {"anzahl": len(x), "gezeigt": len(gezeigt), "felder": alle_felder[:40]}
        if len(x) > n_liste:
            gezeigt.append(f"… +{len(x) - n_liste} weitere")
        return gezeigt
    return x


def _verdichten(listen: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Gleiche Feldlisten nur einmal nennen; spätere Listen verweisen auf den ersten Pfad.

    Beispiel: eine Liste von Gruppen nennt dieselben Felder in jeder Gruppe neu — das kostet Budget.
    """
    erste: dict[tuple[str, ...], str] = {}
    out: dict[str, dict[str, Any]] = {}
    for pfad, e in listen.items():
        schluessel = tuple(e.get("felder") or ())
        if schluessel and schluessel in erste:
            out[pfad] = {**e, "felder": f"wie {erste[schluessel]}"}
        else:
            erste.setdefault(schluessel, pfad)
            out[pfad] = e
    return out


def ablegen(tool: str, args: dict[str, Any] | None, voll: Any) -> str:
    text = json.dumps({"tool": tool, "args": args or {}, "voll": voll}, ensure_ascii=False, default=str)
    eid = hashlib.sha256(text.encode()).hexdigest()[:16]
    ABLAGE.setzen(f"hub:ergebnis:{eid}", text, ABLAGE_SEKUNDEN)
    return eid


def abgelegt(eid: str) -> dict[str, Any] | None:
    if not _ID.match(eid or ""):
        return None
    text = ABLAGE.holen(f"hub:ergebnis:{eid}")
    return json.loads(text) if text else None


def kurz(tool: str, args: dict[str, Any] | None, voll: Any, *, budget: int = BUDGET,
         plugin_sicht: dict[str, list[str]] | None = None, aufrufer: str | None = None) -> tuple[Any, dict[str, Any] | None]:
    """(Ergebnis für das Modell, Begleitinfo oder None). Passt `voll` ins Budget, bleibt es unverändert.

    Mit `aufrufer` zählt der Aufruf in der Messung (`messung()`); ohne bleibt er ungezählt (Tests, interne Wege).
    """
    groesse = _laenge(voll)
    if groesse <= budget:
        if aufrufer is not None:
            messen(aufrufer, voll=groesse, kurz=groesse)
        return voll, None
    sicht_ = sicht(tool, plugin_sicht)
    gekuerzt: Any = None
    listen: dict[str, dict[str, Any]] = {}
    for stufe in STUFEN:
        listen = {}
        gekuerzt = _kuerze(voll, stufe, sicht_, "", listen)
        listen = _verdichten(listen)
        if _laenge(gekuerzt) + _laenge(listen) <= budget:
            break
    else:  # selbst die knappste Stufe ist zu groß: nur noch die Gestalt
        listen = {k: v for k, v in list(listen.items())[:12]}
        gekuerzt = {"_felder": list(voll)[:40]} if isinstance(voll, dict) else {"_anzahl": len(voll) if isinstance(voll, list) else None}
    eid = ablegen(tool, args, voll)
    info = {
        "ansicht": "kurz",
        "ergebnis_id": eid,
        "zeichen_voll": groesse,
        "listen": listen,
        "mehr": "hub__mehr(ergebnis_id, pfad, felder, filter, suche, limit, cursor) holt gezielt nach; "
        "ansicht='voll' liefert alles. Nachgefragte Felder stehen künftig von selbst in der kurzen Ansicht.",
    }
    if aufrufer is not None:
        messen(aufrufer, voll=groesse, kurz=_laenge(gekuerzt) + _laenge(info), gekuerzt=True)
    return gekuerzt, info


# ── Nachholen ─────────────────────────────────────────────────────────────────────────────────────────


def _gehe(x: Any, pfad: str) -> Any:
    for teil in [t for t in re.split(r"[.\[\]]+", pfad or "") if t]:
        if isinstance(x, list) and teil.lstrip("-").isdigit():
            x = x[int(teil)]
        elif isinstance(x, dict) and teil in x:
            x = x[teil]
        else:
            raise KeyError(teil)
    return x


def _passt(e: Any, filter_: dict[str, Any] | None, suche: str) -> bool:
    if suche and suche.lower() not in json.dumps(e, ensure_ascii=False, default=str).lower():
        return False
    for feld, soll in (filter_ or {}).items():
        ist = e.get(feld) if isinstance(e, dict) else None
        if isinstance(soll, str) and isinstance(ist, str):
            if soll.lower() not in ist.lower():
                return False
        elif ist != soll:
            return False
    return True


def mehr(eintrag: dict[str, Any], *, pfad: str = "", felder: list[str] | None = None,
         filter_: dict[str, Any] | None = None, suche: str = "", limit: int = 20, cursor: int = 0,
         budget: int = BUDGET) -> dict[str, Any]:
    tool = str(eintrag.get("tool") or "")
    try:
        knoten = _gehe(eintrag.get("voll"), pfad)
    except (KeyError, IndexError, ValueError) as exc:
        return {"ok": False, "error": f"Pfad {pfad!r} gibt es nicht ({exc})", "kind": "bad_request"}
    felder = [str(f) for f in (felder or []) if str(f).strip()]
    antwort: dict[str, Any] = {"ok": True, "tool": tool, "pfad": pfad}
    if isinstance(knoten, list):
        treffer = [e for e in knoten if _passt(e, filter_, suche)]
        limit = max(1, min(int(limit or 20), 200))
        cursor = max(0, int(cursor or 0))
        seite = treffer[cursor : cursor + limit]
        if felder:
            seite = [{k: e.get(k) for k in felder if k in e} if isinstance(e, dict) else e for e in seite]
            if any(isinstance(e, dict) for e in knoten):
                lernen(tool, pfad, felder)
        antwort |= {"anzahl": len(knoten), "treffer": len(treffer), "cursor": cursor, "eintraege": seite,
                    "weiter": cursor + limit if cursor + limit < len(treffer) else None}
    elif isinstance(knoten, dict) and felder:
        antwort["wert"] = {k: knoten.get(k) for k in felder if k in knoten}
    else:
        antwort["wert"] = knoten
    # Auch das Nachgeholte bleibt im Rahmen: großzügiger, aber gedeckelt.
    gross = budget * 3
    if _laenge(antwort) > gross:
        teil = antwort.pop("eintraege", None) if "eintraege" in antwort else antwort.pop("wert", None)
        gekuerzt, info = kurz(tool, None, teil, budget=gross - _laenge(antwort) - 600, plugin_sicht=None)
        antwort["eintraege" if isinstance(teil, list) else "wert"] = gekuerzt
        if info:
            antwort["gekuerzt"] = {"listen": info["listen"], "tipp": "felder, filter oder limit enger setzen"}
    return antwort


# ── Leichte Suche ─────────────────────────────────────────────────────────────────────────────────────


def einzeiler(text: str | None, n: int = 140) -> str:
    zeilen = (text or "").strip().splitlines()
    z = zeilen[0].strip() if zeilen else ""
    satz = re.split(r"(?<=[.!?])\s", z, maxsplit=1)[0]
    return satz[:n]


# Alltagswörter führen auf die Wörter in den Werkzeugnamen; ein Suchwort trifft, wenn es selbst ODER eines seiner
# Synonyme vorkommt. Der Kern kennt nur seine eigenen Begriffe; Plugins ergänzen die Tabelle mit
# `ansicht.SYNONYME.update({...})`.
SYNONYME: dict[str, tuple[str, ...]] = {
    "skript": ("werkstatt",), "script": ("werkstatt",), "programm": ("werkstatt",),
    "plugin": ("mcp",), "werkzeug": ("mcp",), "werkzeuge": ("mcp",), "tool": ("mcp",), "tools": ("mcp",),
    "anleitung": ("skills",), "wissen": ("skills",), "howto": ("skills",),
    "protokoll": ("audit",), "historie": ("audit",), "nutzung": ("audit",),
}

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# Füllwörter aus ganzen Fragen („wo ist mein handy“): „ist“ steckt in „liste“, „mein“ in „allgemein“ —
# sie drängten das gesuchte Werkzeug nach hinten. Besteht die Suche nur aus ihnen, bleiben sie.
FUELLWOERTER = frozenset(
    "wo ist sind mein meine meinen mir mich ich du der die das den dem ein eine einen und oder was wie wer "
    "zeig zeige gerade jetzt bitte gibt es hab habe hat auf im in an von zu für fuer mit noch schon "
    "where is are my me the a an and or what how show".split()
)


def suchwoerter(query: str) -> list[str]:
    """Kleingeschriebene Suchwörter ohne Füllwörter (außer die Suche besteht nur aus Füllwörtern)."""
    alle = [w for w in (query or "").lower().split() if w]
    kern = [w for w in alle if _norm(w) not in FUELLWOERTER]
    return kern or alle


def _norm(text: str) -> str:
    return (text or "").lower().translate(_UMLAUTE)


def _wort_wert(n: str, b: str, wort: str) -> int:
    """3 = im Namen, 1 = in der Beschreibung, 0 = gar nicht (Wort oder Synonym)."""
    formen = (wort, *SYNONYME.get(wort, ()))
    if any(f in n for f in formen):
        return 3
    if any(f in b for f in formen):
        return 1
    return 0


def treffer_wert(name: str, beschreibung: str, woerter: list[str], *, teil: bool = False) -> int:
    """Grobe Rangfolge: Treffer im Namen zählen dreifach. 0 = kein Treffer.

    Ohne ``teil`` müssen alle Wörter vorkommen; mit ``teil`` reicht eins (Rückfall, wenn sonst nichts trifft) —
    dann zählt jedes getroffene Wort zehnfach, damit mehr getroffene Wörter vor Namenstreffern stehen.
    """
    n, b = _norm(name), _norm(beschreibung)
    wert = getroffen = 0
    for w in woerter:
        einzeln = _wort_wert(n, b, _norm(w))
        if not einzeln and not teil:
            return 0
        wert += einzeln
        getroffen += bool(einzeln)
    if teil:
        return getroffen * 10 + wert if getroffen else 0
    return wert or 1
