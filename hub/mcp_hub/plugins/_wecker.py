"""_wecker — der Hub weckt den Agenten, wenn etwas geschieht (docs/KOPPLUNG-OPENCLAW.md, „Wecken“).

Ohne Wecker arbeitet ein Agent nur, wenn jemand mit ihm spricht oder ein Zeitplan läuft. Der Wecker liest im Takt die
Quellen des Hubs (Vorgänge, Termine, Postfach, Dokumente, dazu frei benannte Ereignisströme), macht aus jedem neuen
Ereignis einen Umschlag (``mcp_hub.umschlag``) und weckt den Agenten über die Brücke (``fyos.wecken``):

* Ein Vorgangsereignis weckt die **Sitzung dieses Vorgangs** (``agent:<id>:vorgang:<ID>``), damit der Agent dort mit
  dem Verlauf des Vorgangs weiterarbeitet. Alles andere weckt seine Hauptsitzung.
* Der Weckruf trägt nur Namen und Nummern, nie Inhalte (kein Betreff, keine Kommentare, keine Titel). Der Agent liest
  im Hub nach.
* Weckregeln legen fest, was weckt: ``thema`` (exakt, ``prefix.*`` oder ``*``), ``min_schwere``, ``nicht_von``
  (eigene Spuren wecken nie: kein Echo), ``ziel`` (``vorgang`` | ``haupt``), ``modus`` (``jetzt`` | ``naechster``)
  und ``max_pro_stunde``.
* Flussschutz: höchstens ``max_pro_minute`` Weckrufe insgesamt, je Regel ``max_pro_stunde``; mehrere Ereignisse
  desselben Ziels in einem Schlag werden zu einem Weckruf. Was nicht sofort darf, wartet bis ``max_alter_s`` und fällt
  dann mit Vermerk im Verlauf weg. Scheitert ein Weckruf, versucht der nächste Schlag es erneut (dreimal).

Die erste Runde einer Quelle legt nur den Ausgangsstand fest (nichts Altes weckt). Der Stand liegt im Hub-Speicher.
Rein bis auf ``speicher`` und die Quellen, die hereingereicht werden: testbar ohne Netz.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable

from .. import umschlag as U

logger = logging.getLogger(__name__)

STAND_SCHLUESSEL = "fyos:openclaw:wecker:stand"
STROM = "fyos:openclaw:wecken"
STROM_MAX = 1000
VERLAUF_MAX = 100
GESEHEN_MAX = 1000
VERSUCHE_MAX = 3
EIGENE_AKTEURE = ("openclaw", "agent")
PRIORITAET_SCHWERE = {"urgent": "critical", "high": "high", "low": "low"}


def vorgaben_regeln(eigene: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Die Weckregeln, wenn nichts anderes eingetragen ist."""
    nicht_von = sorted({str(x).strip().lower() for x in (*eigene, *EIGENE_AKTEURE) if str(x).strip()})
    return [
        {"name": "vorgang", "thema": ["itsm.neu", "itsm.kommentar", "itsm.zugewiesen", "itsm.erneut"],
         "nicht_von": nicht_von, "ziel": "vorgang", "modus": "jetzt", "max_pro_stunde": 30},
        {"name": "termin", "thema": ["termin.gleich"], "ziel": "haupt", "modus": "jetzt", "max_pro_stunde": 12},
        {"name": "eingang", "thema": ["postfach.neu", "dokumente.neu"], "ziel": "haupt", "modus": "naechster",
         "max_pro_stunde": 12},
        {"name": "dringend", "thema": ["*"], "min_schwere": "hoch", "nicht_von": nicht_von, "ziel": "haupt",
         "modus": "jetzt", "max_pro_stunde": 12},
    ]


def regeln_pruefen(roh: Any, eigene: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Regeln aus der Konfiguration: fehlerhafte Einträge fallen mit Warnung weg; ohne Eintrag gelten die Vorgaben."""
    if not isinstance(roh, list) or not roh:
        return vorgaben_regeln(eigene)
    regeln: list[dict[str, Any]] = []
    for i, r in enumerate(roh):
        if not isinstance(r, dict) or not isinstance(r.get("thema"), list) or not r["thema"]:
            logger.warning("openclaw: Weckregel %s ohne thema übergangen", i + 1)
            continue
        ziel = str(r.get("ziel") or "haupt")
        modus = str(r.get("modus") or "jetzt")
        schwere = str(r.get("min_schwere") or "")
        if ziel not in ("vorgang", "haupt") or modus not in ("jetzt", "naechster") or (schwere and schwere not in U.SCHWEREN):
            logger.warning("openclaw: Weckregel %s hat ungültige Werte, übergangen", i + 1)
            continue
        try:
            stunde = max(1, int(r.get("max_pro_stunde", 30)))
        except (TypeError, ValueError):
            stunde = 30
        regeln.append({
            "name": str(r.get("name") or f"regel{i + 1}")[:40],
            "thema": [str(x) for x in r["thema"]],
            "nicht_von": [str(x).lower() for x in (r.get("nicht_von") or [])],
            "von": [str(x).lower() for x in (r.get("von") or [])],
            "min_schwere": schwere, "ziel": ziel, "modus": modus, "max_pro_stunde": stunde,
            "weiche": bool(r.get("weiche")),
        })
    return regeln or vorgaben_regeln(eigene)


def _eid(zeit: float, *teile: Any) -> str:
    return f"{int(zeit * 1000)}-" + "-".join(str(t) for t in teile if t not in (None, ""))


def _itsm(vid: str, ereignis: str, akteur: Any, detail: str, zeit: float) -> dict[str, Any] | None:
    return U.normalisieren(U.STROM_ITSM, _eid(zeit, vid, ereignis), {
        "ticket_id": vid, "event": ereignis, "actor": akteur or "", "detail": detail, "ts": zeit})


def _bus(thema: str, zeit: float, daten: dict[str, Any], quelle: str, *teile: Any) -> dict[str, Any] | None:
    return U.normalisieren(U.PRAEFIX_BUS + thema, _eid(zeit, *teile), {
        "source": quelle, "data": json.dumps({**daten, "ts": zeit})})


# ── Quellen ─────────────────────────────────────────────────────────────────────────────────

class VorgangsQuelle:
    """Vorgänge: neu, Zuständigkeit, Status, Kommentare. Liest ``offen()``; Verlauf nur bei geänderten Vorgängen."""

    name = "vorgaenge"

    def __init__(self, quelle: Callable[[], Any], rueckblick_s: float = 60.0) -> None:
        self._quelle = quelle
        self._rueckblick = rueckblick_s

    def lies(self, stand: dict[str, Any], jetzt: float) -> list[dict[str, Any]]:
        q = self._quelle()
        if q is None or not getattr(q, "eingerichtet", False):
            return []
        tickets = [t for t in q.offen(200) if isinstance(t, dict) and str(t.get("id") or "").strip()]
        alt = stand.get("t")
        erst = not isinstance(alt, dict)
        alt = {} if erst else alt
        neu: dict[str, Any] = {}
        ereignisse: list[dict[str, Any]] = []
        for t in tickets:
            vid = str(t["id"]).strip()
            status, zustaendig, stempel = str(t.get("status") or ""), str(t.get("assignee") or ""), str(t.get("updated_at") or "")
            vorher = alt.get(vid)
            k = float(vorher["k"]) if isinstance(vorher, dict) and "k" in vorher else jetzt - self._rueckblick
            neu[vid] = {"s": status, "a": zustaendig, "u": stempel, "k": k}
            if erst:
                continue
            if not isinstance(vorher, dict):
                schwere = PRIORITAET_SCHWERE.get(str(t.get("priority") or "").lower())
                e = _itsm(vid, "created", t.get("created_by") or t.get("actor") or t.get("reporter"),
                          f"severity={schwere}" if schwere else "", jetzt)
                if e:
                    ereignisse.append(e)
                neu[vid]["k"] = jetzt
                continue
            if vorher.get("s") != status:
                e = _itsm(vid, "updated", None, "status", jetzt)
                ereignisse += [e] if e else []
            if vorher.get("a") != zustaendig:
                e = _itsm(vid, "updated", None, "assignee", jetzt)
                ereignisse += [e] if e else []
            if vorher.get("u") != stempel or vorher.get("s") != status or vorher.get("a") != zustaendig:
                # Einträge ohne lesbare Zeit lassen sich nicht von alten unterscheiden und wecken deshalb nie.
                kommentare = sorted(
                    ((ts, x) for x in (q.verlauf(vid, 10) or [])
                     if isinstance(x, dict) and str(x.get("event") or "").lower() == "comment"
                     and (ts := U.zeit_unix(x.get("ts") or x.get("created_at"))) is not None),
                    key=lambda paar: paar[0])
                for ts, eintrag in kommentare:
                    if ts <= k:
                        continue
                    e = _itsm(vid, "comment", eintrag.get("actor"), "", ts)
                    ereignisse += [e] if e else []
                neu[vid]["k"] = max([k] + [ts for ts, _ in kommentare])
        stand["t"] = neu
        return ereignisse


class TerminQuelle:
    """Termine: ``termin.gleich``, wenn einer in höchstens ``vorlauf_min`` Minuten beginnt (nur die Minuten, nie Titel)."""

    name = "termine"

    def __init__(self, quelle: Callable[[], Any], vorlauf_min: float = 10.0) -> None:
        self._quelle = quelle
        self._vorlauf = vorlauf_min

    def lies(self, stand: dict[str, Any], jetzt: float) -> list[dict[str, Any]]:
        q = self._quelle()
        if q is None or not getattr(q, "eingerichtet", False):
            return []
        gemeldet = {k: v for k, v in (stand.get("gemeldet") or {}).items() if isinstance(v, (int, float)) and v > jetzt - 86400}
        ereignisse: list[dict[str, Any]] = []
        for t in q.anstehende(1) or []:
            if not isinstance(t, dict) or t.get("ganztaegig"):
                continue
            beginn = U.zeit_unix(t.get("start"))
            if beginn is None or not -60 <= beginn - jetzt <= self._vorlauf * 60:
                continue
            schluessel = f"{t.get('id')}|{t.get('start')}"
            if schluessel in gemeldet:
                continue
            gemeldet[schluessel] = jetzt
            kurz = hashlib.sha1(schluessel.encode()).hexdigest()[:8]  # noqa: S324 — nur eine Kennung
            e = _bus("termin.gleich", jetzt, {"in_min": max(0, round((beginn - jetzt) / 60))}, "termine", kurz)
            ereignisse += [e] if e else []
        stand["gemeldet"] = gemeldet
        return ereignisse


class PostfachQuelle:
    """Postfach: ``postfach.neu`` mit der Zahl neuer ungelesener Mails (nie Absender oder Betreff)."""

    name = "postfach"

    def __init__(self, quelle: Callable[[], Any]) -> None:
        self._quelle = quelle

    def lies(self, stand: dict[str, Any], jetzt: float) -> list[dict[str, Any]]:
        q = self._quelle()
        if q is None or not getattr(q, "eingerichtet", False):
            return []
        mails = (q.liste("in:inbox", 20, None, False) or {}).get("mails") or []
        ids = [str(m["id"]) for m in mails if isinstance(m, dict) and m.get("id") and not m.get("gelesen")]
        gesehen = stand.get("gesehen")
        stand["gesehen"] = (ids + [i for i in (gesehen or []) if i not in ids])[:200]
        if gesehen is None:
            return []
        neu = [i for i in ids if i not in gesehen]
        e = _bus("postfach.neu", jetzt, {"anzahl": len(neu)}, "postfach", neu[0][:12]) if neu else None
        return [e] if e else []


class DokumentQuelle:
    """Dokumente: ``dokumente.neu`` mit der Zahl neuer Dokumente (nie Titel oder Inhalt)."""

    name = "dokumente"

    def __init__(self, quelle: Callable[[], Any]) -> None:
        self._quelle = quelle

    def lies(self, stand: dict[str, Any], jetzt: float) -> list[dict[str, Any]]:
        q = self._quelle()
        if q is None or not getattr(q, "eingerichtet", False):
            return []
        dokumente = (q.neueste(10) or {}).get("dokumente") or []
        ids = [str(d["id"]) for d in dokumente if isinstance(d, dict) and d.get("id") is not None]
        gesehen = stand.get("gesehen")
        stand["gesehen"] = (ids + [i for i in (gesehen or []) if i not in ids])[:200]
        if gesehen is None:
            return []
        neu = [i for i in ids if i not in gesehen]
        e = _bus("dokumente.neu", jetzt, {"anzahl": len(neu)}, "dokumente", neu[0]) if neu else None
        return [e] if e else []


def _eid_teile(eid: str) -> tuple[int, int]:
    ms, _, folge = str(eid).partition("-")
    try:
        return int(ms), int(folge or 0)
    except ValueError:
        return 0, 0


class StromQuelle:
    """Frei benannte Ereignisströme (Redis-Streams): jeder neue Eintrag wird ein Umschlag (``umschlag.normalisieren``)."""

    def __init__(self, speicher: Callable[[], Any], strom: str, anzahl: int = 50) -> None:
        self._speicher = speicher
        self.strom = strom
        self.name = "strom:" + strom
        self._anzahl = anzahl

    def lies(self, stand: dict[str, Any], jetzt: float) -> list[dict[str, Any]]:
        eintraege = list(self._speicher().xrevrange(self.strom, count=self._anzahl) or [])
        if not eintraege:
            return []
        neueste = eintraege[0][0]
        letzte = stand.get("letzte")
        stand["letzte"] = neueste
        if letzte is None:
            return []
        ereignisse = []
        for eid, felder in reversed(eintraege):
            if _eid_teile(eid) > _eid_teile(letzte):
                e = U.normalisieren(self.strom, eid, dict(felder))
                if e:
                    ereignisse.append(e)
        return ereignisse


# ── Der Wecker ──────────────────────────────────────────────────────────────────────────────

class Wecker:
    def __init__(self, *, quellen: list[Any], regeln: list[dict[str, Any]], schicken: Callable[[dict[str, Any]], Any],
                 speicher: Callable[[], Any] | None = None, agent: str = U.AGENT_VORGABE,
                 uhr: Callable[[], float] = time.time, max_pro_minute: int = 10, max_alter_s: float = 900.0,
                 weiche: Callable[[dict[str, Any]], tuple[bool, str]] | None = None) -> None:
        self.quellen = quellen
        self._weiche = weiche
        self.regeln = regeln
        self._schicken = schicken
        self._speicher = speicher
        self.agent = agent
        self._uhr = uhr
        self.max_pro_minute = max(1, int(max_pro_minute))
        self.max_alter_s = max_alter_s
        self._sperre = threading.RLock()
        self._stand: dict[str, Any] | None = None
        self._gesehen: deque[str] = deque(maxlen=GESEHEN_MAX)
        self._gesehen_menge: set[str] = set()
        self._offen: list[dict[str, Any]] = []
        self._minute: deque[float] = deque()
        self._stunde: dict[str, deque[float]] = {}
        self.verlauf: deque[dict[str, Any]] = deque(maxlen=VERLAUF_MAX)
        self.zaehler: dict[str, int] = {"schlaege": 0, "ereignisse": 0, "ignoriert": 0, "geweckt": 0, "fehler": 0,
                                        "verworfen": 0, "quellfehler": 0, "ruhig": 0}
        self.letzter_fehler = ""
        self.letzter_schlag = 0.0

    # Stand ------------------------------------------------------------------------------------
    def _stand_laden(self) -> dict[str, Any]:
        if self._stand is None:
            stand: dict[str, Any] = {}
            if self._speicher is not None:
                try:
                    for name, roh in (self._speicher().hgetall(STAND_SCHLUESSEL) or {}).items():
                        try:
                            wert = json.loads(roh)
                        except ValueError:
                            continue
                        if isinstance(wert, dict):
                            stand[name] = wert
                except Exception as exc:  # noqa: BLE001 — ohne Stand beginnt jede Quelle neu mit ihrem Ausgangsstand
                    logger.debug("openclaw: Wecker-Stand nicht lesbar: %s", exc)
            self._stand = stand
        return self._stand

    def _stand_sichern(self, stand: dict[str, Any]) -> None:
        if self._speicher is None or not stand:
            return
        try:
            self._speicher().hset(STAND_SCHLUESSEL, mapping={k: json.dumps(v) for k, v in stand.items()})
        except Exception as exc:  # noqa: BLE001
            logger.debug("openclaw: Wecker-Stand nicht gesichert: %s", exc)

    # Regeln -----------------------------------------------------------------------------------
    def regel_fuer(self, u: dict[str, Any]) -> dict[str, Any] | None:
        for r in self.regeln:
            if not U.passt(u["thema"], r.get("thema") or []):
                continue
            von = u.get("von")
            if von and von in [str(x).lower() for x in r.get("nicht_von") or []]:
                continue
            if r.get("von") and von not in [str(x).lower() for x in r["von"]]:
                continue
            if r.get("min_schwere") and U.SCHWEREN.index(u["schwere"]) < U.SCHWEREN.index(r["min_schwere"]):
                continue
            return r
        return None

    # Schlag -----------------------------------------------------------------------------------
    def schlag(self) -> dict[str, Any]:
        """Ein Durchgang: Quellen lesen, Regeln anwenden, wecken. Wirft nie; gibt die Zahlen des Schlags zurück."""
        with self._sperre:
            jetzt = self._uhr()
            self.zaehler["schlaege"] += 1
            self.letzter_schlag = jetzt
            stand = self._stand_laden()
            neu_gelesen = 0
            for quelle in self.quellen:
                try:
                    ereignisse = quelle.lies(stand.setdefault(quelle.name, {}), jetzt)
                except Exception as exc:  # noqa: BLE001 — eine kranke Quelle hält die anderen nicht auf
                    self.zaehler["quellfehler"] += 1
                    self.letzter_fehler = f"{quelle.name}: {type(exc).__name__}: {str(exc)[:160]}"
                    logger.debug("openclaw: Wecker-Quelle %s: %s", quelle.name, exc)
                    continue
                for u in ereignisse:
                    if u["id"] in self._gesehen_menge:
                        continue
                    if len(self._gesehen) == self._gesehen.maxlen:
                        self._gesehen_menge.discard(self._gesehen[0])
                    self._gesehen.append(u["id"])
                    self._gesehen_menge.add(u["id"])
                    neu_gelesen += 1
                    self.zaehler["ereignisse"] += 1
                    regel = self.regel_fuer(u)
                    if regel is None:
                        self.zaehler["ignoriert"] += 1
                        continue
                    if regel.get("weiche") and self._weiche is not None:
                        try:
                            wecken, grund = self._weiche(u)
                        except Exception as exc:  # noqa: BLE001 -- die Weiche darf das Wecken nie aufhalten
                            wecken, grund = True, f"Weiche: {type(exc).__name__}"
                        if not wecken:
                            self.zaehler["ruhig"] += 1
                            self._vermerk(jetzt, [{"u": u, "regel": regel}], "ruhig", grund)
                            continue
                    self._offen.append({"u": u, "regel": regel, "seit": jetzt, "versuche": 0})
            self._stand_sichern(stand)
            geweckt = self._abarbeiten(jetzt)
            return {"gelesen": neu_gelesen, "geweckt": geweckt, "wartend": len(self._offen)}

    def _ziel(self, eintrag: dict[str, Any]) -> tuple[str, str]:
        u, regel = eintrag["u"], eintrag["regel"]
        verweis = u.get("verweis") or ""
        if regel["ziel"] == "vorgang" and verweis and U.vorgang_gueltig(verweis):
            return verweis.upper(), regel["modus"]
        return "", regel["modus"]

    def _frei(self, regel: dict[str, Any], jetzt: float) -> bool:
        stunde = self._stunde.setdefault(regel["name"], deque())
        while stunde and stunde[0] <= jetzt - 3600:
            stunde.popleft()
        while self._minute and self._minute[0] <= jetzt - 60:
            self._minute.popleft()
        return len(stunde) < regel["max_pro_stunde"] and len(self._minute) < self.max_pro_minute

    def _abarbeiten(self, jetzt: float) -> int:
        gruppen: dict[tuple[str, str], list[dict[str, Any]]] = {}
        rest: list[dict[str, Any]] = []
        for e in self._offen:
            if jetzt - e["seit"] > self.max_alter_s or e["versuche"] >= VERSUCHE_MAX:
                self._vermerk(jetzt, [e], "verworfen", "zu alt" if e["versuche"] < VERSUCHE_MAX else self.letzter_fehler)
                self.zaehler["verworfen"] += 1
                continue
            gruppen.setdefault(self._ziel(e), []).append(e)
        geweckt = 0
        for (vorgang, modus), eintraege in gruppen.items():
            regel = eintraege[0]["regel"]
            if not self._frei(regel, jetzt):
                rest += eintraege
                continue
            text = beschreibe([e["u"] for e in eintraege], vorgang)
            params: dict[str, Any] = {"text": text, "modus": modus}
            if vorgang:
                params["vorgang"] = vorgang
            try:
                self._schicken(params)
            except Exception as exc:  # noqa: BLE001 — der nächste Schlag versucht es wieder
                self.zaehler["fehler"] += 1
                self.letzter_fehler = f"{type(exc).__name__}: {str(exc)[:200]}"
                for e in eintraege:
                    e["versuche"] += 1
                rest += eintraege
                self._vermerk(jetzt, eintraege, "fehler", self.letzter_fehler)
                continue
            self._stunde.setdefault(regel["name"], deque()).append(jetzt)
            self._minute.append(jetzt)
            self.zaehler["geweckt"] += 1
            geweckt += 1
            self._vermerk(jetzt, eintraege, "geweckt", "")
        self._offen = rest
        return geweckt

    def _vermerk(self, jetzt: float, eintraege: list[dict[str, Any]], ergebnis: str, fehler: str) -> None:
        u = eintraege[0]["u"]
        vorgang, modus = self._ziel(eintraege[0])
        zeile = {"zeit": round(jetzt, 3), "ergebnis": ergebnis, "regel": eintraege[0]["regel"]["name"],
                 "thema": u["thema"], "verweis": u.get("verweis"), "von": u.get("von"), "schwere": u["schwere"],
                 "ziel": f"agent:{self.agent}:vorgang:{vorgang}" if vorgang else f"agent:{self.agent}:main",
                 "modus": modus, "n": len(eintraege), "fehler": fehler or None}
        self.verlauf.append(zeile)
        if self._speicher is not None:
            try:
                self._speicher().xadd(STROM, {k: str(v) for k, v in zeile.items() if v not in (None, "")},
                                      maxlen=STROM_MAX, approximate=True)
            except Exception as exc:  # noqa: BLE001
                logger.debug("openclaw: Weckverlauf nicht gesichert: %s", exc)

    def zustand(self, grenze: int = 20) -> dict[str, Any]:
        with self._sperre:
            return {
                "zaehler": dict(self.zaehler),
                "wartend": len(self._offen),
                "letzter_fehler": self.letzter_fehler or None,
                "letzter_schlag": self.letzter_schlag or None,
                "quellen": [q.name for q in self.quellen],
                "regeln": [dict(r) for r in self.regeln],
                "verlauf": list(self.verlauf)[-max(1, min(int(grenze), VERLAUF_MAX)):][::-1],
            }


def beschreibe(umschlaege: list[dict[str, Any]], vorgang: str = "") -> str:
    """Text des Weckrufs aus Namen und Nummern (nie aus Inhalten)."""
    if len(umschlaege) > 1:
        themen = ", ".join(dict.fromkeys(u["thema"] for u in umschlaege))
        wo = f"Vorgang {vorgang}" if vorgang else "Hub"
        return f"{len(umschlaege)} neue Ereignisse ({themen}) zu: {wo}. Sieh im Hub nach und handle nach dem Stand."
    u = umschlaege[0]
    von = f" von {u['von']}" if u.get("von") else ""
    thema = u["thema"]
    if thema == "itsm.neu":
        return f"Neuer Vorgang {u['verweis']} (Schwere {u['schwere']}){von}. Lies ihn im Hub und handle nach seinem Stand."
    if thema == "itsm.kommentar":
        return f"Neuer Kommentar{von} im Vorgang {u['verweis']}. Lies den Vorgang im Hub und antworte dort, wenn es nötig ist."
    if thema == "itsm.zugewiesen":
        return f"Die Zuständigkeit im Vorgang {u['verweis']} hat sich geändert. Sieh im Hub nach, ob du etwas tun sollst."
    if thema == "itsm.status":
        return f"Der Status des Vorgangs {u['verweis']} hat sich geändert. Sieh im Hub nach."
    if thema == "termin.gleich":
        return f"Ein Termin beginnt in {u['daten'].get('in_min', '?')} Minuten. Sieh in den Kalender des Hubs und bereite vor, was nötig ist."
    if thema == "postfach.neu":
        return f"{u['daten'].get('anzahl', '?')} neue ungelesene Mails. Sieh im Postfach des Hubs nach."
    if thema == "dokumente.neu":
        return f"{u['daten'].get('anzahl', '?')} neue Dokumente im Eingang. Sieh in der Dokumentenablage des Hubs nach."
    wo = f", Verweis {u['verweis']}" if u.get("verweis") else ""
    return f"Ereignis {thema} (Schwere {u['schwere']}){wo}. Sieh im Hub nach und handle nach dem Stand."
