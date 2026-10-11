"""umschlag — der gemeinsame Umschlag für Ereignisse zwischen Hub und OpenClaw-Agent.

Im Hub gibt es mehrere Familien von Ereignisströmen mit unterschiedlichen Feldschemas. Statt die Erzeuger umzubauen,
macht ein Normalisierer daraus einen Umschlag:

    {id, strom, thema, zeit, zeit_unix, schwere, quelle, verweis, von, daten}

    thema     Punktname, z. B. `itsm.kommentar`, `ci.lauf`, `node.critical`
    schwere   info | normal | hoch | kritisch
    quelle    wer es erzeugte (itsm, hub, gitea, …)
    verweis   Vorgang (INC-1234), Lauf-Nummer o. ä. — womit man das Ereignis wiederfindet
    von       Akteur, falls bekannt (Person, Agent, Werkzeug)
    daten     wenige kurze Werte; keine Inhalte (der Bus trägt Namen, keine Inhalte)

Familien (an Strom und Feldern erkannt):
    itsm       `fyos:itsm:events`: ticket_id, event, actor, detail, ts
    schleifen  `fyos:schleifen:ereignisse`, `fyos:erkunden:ereignisse`: art, …, ts
    bus        `fyos:events:<thema>` der Hub-Erzeuger: data = JSON, source
    thema      `fyos:events:*` mit topic/payload (JSON), ts, source
    flach      alles andere mit flachen Feldern: ticket, titel, assignee, ts; dazu die Sammelströme des Hub
               (`bus.tool.<plugin>.<methode>.<ok|fail>`, `fyos:live`, `fyos:entwicklung:ereignisse` mit Kurzfeldern und
               Zeit `t` in ms, `fyos:pane:dwell`)

Zeiten stehen als ISO-Text, Sekunden oder Millisekunden, auch als Zeichenkette.

Rein, ohne Netz, ohne Redis, nur Standardbibliothek: mit Feldern aus der Wirklichkeit testbar. Die Brücke zu OpenClaw
(`docs/KOPPLUNG-OPENCLAW.md`) und der Wecker des Hub-Plugins `openclaw` sprechen dieselbe Sprache:
  - Umschlag und `normalisieren(strom, id, felder)`
  - `EREIGNISARTEN`                             die Themen, die Erzeuger schreiben und Weckregeln nennen
  - `passt(thema, muster)`, `weckt_diese(umschlag, regeln)`
                                                Weckregeln: {thema: [...], nicht_von: [...], von: [...]}
  - `sitzungsschluessel(vorgang, agent)`, `vorgang_aus_schluessel(schluessel)`
                                                `agent:<id>:vorgang:<ID>`; die Kennung kommt aus dem Argument,
                                                aus `FYOS_AGENT` oder (ohne beides) ist `main` die OpenClaw-Vorgabe
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

SCHWEREN = ("info", "normal", "hoch", "kritisch")
_RANG = {s: i for i, s in enumerate(SCHWEREN)}
PRAEFIX_BUS = "fyos:events:"
STROM_ITSM = "fyos:itsm:events"
STROM_SCHLEIFEN = "fyos:schleifen:ereignisse"
STROM_ERKUNDEN = "fyos:erkunden:ereignisse"

#: Schweregrad-Wörter der Erzeuger → Umschlag.
_SCHWERE_WORT = {
    "info": "info", "low": "info", "gruen": "info", "ok": "info", "debug": "info",
    "normal": "normal", "medium": "normal", "gelb": "normal", "warn": "normal", "warning": "normal",
    "hoch": "hoch", "high": "hoch", "error": "hoch", "rot": "hoch",
    "kritisch": "kritisch", "critical": "kritisch", "crit": "kritisch", "fatal": "kritisch",
}
#: Vorgaben je Thema, wenn der Erzeuger keine Schwere nennt (Teilwort im Thema, erster Treffer gewinnt).
_THEMA_SCHWERE = (
    ("critical", "kritisch"), ("service_down", "hoch"), ("fehlgeschlagen", "hoch"), ("failed", "hoch"),
    ("errors", "hoch"), ("alert", "hoch"), ("recovered", "info"), ("document_added", "info"),
)


def schwerer(a: str, b: str) -> str:
    return a if _RANG.get(a, 1) >= _RANG.get(b, 1) else b


def _zeit_aus_id(eid: str) -> float | None:
    try:
        return int(str(eid).split("-", 1)[0]) / 1000.0
    except (TypeError, ValueError):
        return None


def _zeit(wert: Any) -> float | None:
    """Zeit als Unix-Sekunden. Erzeuger schreiben ISO-Text, Sekunden oder Millisekunden, auch als Zeichenkette."""
    if wert in (None, "") or isinstance(wert, bool):
        return None
    if isinstance(wert, str) and re.fullmatch(r"\d{9,16}(\.\d+)?", wert.strip()):
        wert = float(wert.strip())
    if isinstance(wert, (int, float)):
        if wert != wert or wert <= 0:
            return None
        s = float(wert) / (1000.0 if wert > 1e11 else 1.0)
        return s if s < 4e9 else None  # nach dem Jahr 2096 ist es keine Zeit mehr
    try:
        t = dt.datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


def zeit_unix(wert: Any) -> float | None:
    """Zeit in Sekunden (Unix) aus Zahl (Sekunden oder Millisekunden) oder ISO-Text; sonst None."""
    return _zeit(wert)


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat(timespec="seconds")


def _json(roh: Any) -> dict[str, Any]:
    if isinstance(roh, dict):
        return roh
    try:
        d = json.loads(roh) if roh else {}
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _kurz(wert: Any, n: int = 160) -> str:
    t = " ".join(str(wert if wert is not None else "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _schwere(wort: Any, thema: str, vorgabe: str = "normal") -> str:
    s = _SCHWERE_WORT.get(str(wort or "").strip().lower())
    if s:
        return s
    t = thema.lower()
    for teil, schwere in _THEMA_SCHWERE:
        if teil in t:
            return schwere
    return vorgabe


def _klein(d: dict[str, Any], schluessel: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in schluessel:
        v = d.get(k)
        if v is None or v == "":
            continue
        out[k] = v if isinstance(v, (int, float, bool)) else _kurz(v, 200)
    return out


def _umschlag(strom: str, eid: str, thema: str, zeit: float | None, schwere: str, quelle: str,
              verweis: Any = None, von: Any = None, daten: dict[str, Any] | None = None) -> dict[str, Any]:
    z = zeit if zeit is not None else (_zeit_aus_id(eid) or 0.0)
    return {
        "id": f"{strom}|{eid}",
        "strom": strom,
        "thema": thema,
        "zeit": _iso(z) if z else None,
        "zeit_unix": z,
        "schwere": schwere if schwere in SCHWEREN else "normal",
        "quelle": quelle,
        "verweis": str(verweis) if verweis not in (None, "") else None,
        "von": str(von).lower() if von not in (None, "") else None,
        "daten": daten or {},
    }


# ── Familien ────────────────────────────────────────────────────────────────
def aus_itsm(eid: str, f: dict[str, Any]) -> dict[str, Any] | None:
    """`fyos:itsm:events`. event=updated nennt die geänderten Felder (`assignee; status`), nicht ihre Werte."""
    ereignis = str(f.get("event") or "").strip().lower()
    if not ereignis or not f.get("ticket_id"):
        return None
    detail = str(f.get("detail") or "")
    felder = {x.strip() for x in detail.split(";")} if ereignis == "updated" else set()
    if ereignis == "updated":
        thema = "itsm.zugewiesen" if "assignee" in felder else "itsm.status" if "status" in felder else "itsm.aktualisiert"
    elif ereignis in ("created", "comment", "archived", "unarchived", "occurred"):
        thema = {"created": "itsm.neu", "comment": "itsm.kommentar", "occurred": "itsm.erneut"}.get(ereignis, f"itsm.{ereignis}")
    else:
        thema = f"itsm.{ereignis}"
    schwere = "normal"
    if ereignis == "created":
        m = detail.lower()
        schwere = "kritisch" if "severity=critical" in m else "hoch" if "severity=high" in m else \
            "info" if "severity=low" in m else "normal"
    daten = {"detail": _kurz(detail, 100)} if ereignis in ("created", "updated") else {}
    return _umschlag(STROM_ITSM, eid, thema, _zeit(f.get("ts")), schwere, "itsm", f.get("ticket_id"), f.get("actor"), daten)


def aus_schleifen(strom: str, eid: str, f: dict[str, Any]) -> dict[str, Any] | None:
    """`fyos:schleifen:ereignisse` (art=schalter|gelegenheit|anstoss|totmann …) und `fyos:erkunden:ereignisse`."""
    art = str(f.get("art") or "").strip().lower()
    if not art:
        return None
    pfx = "erkunden" if strom == STROM_ERKUNDEN else "schleifen"
    schwere = "hoch" if art == "totmann" else "info"
    daten = _klein(f, ("schleife", "zustand", "aktion", "bereich", "grund", "stunden", "workflow", "modus", "anzahl", "ok"))
    return _umschlag(strom, eid, f"{pfx}.{art}", _zeit(f.get("ts")), schwere, "hub", f.get("vorgang"), f.get("wer"), daten)


def aus_bus(strom: str, eid: str, f: dict[str, Any]) -> dict[str, Any] | None:
    """Hub-Erzeuger: `data` = JSON (mit oder ohne ts), `source`."""
    thema = strom[len(PRAEFIX_BUS):] if strom.startswith(PRAEFIX_BUS) else strom
    d = _json(f.get("data"))
    if d.get("title") and not d.get("titel"):
        d = {**d, "titel": d["title"]}  # manche Erzeuger schreiben englisch
    z = _zeit(d.get("ts") or d.get("zeit") or f.get("ts"))
    schwere = _schwere(d.get("schwere") or d.get("severity") or d.get("level"), thema)
    verweis = (d.get("verweis") or d.get("vorgang") or d.get("ticket") or d.get("entity_id") or d.get("aktion_id")
               or d.get("id") or d.get("name") or d.get("ziel"))
    # `von` ist bei einem Zustandswechsel (von/nach) der alte Zustand, sonst der Akteur: ein Zustandswechsel hat keinen
    von = d.get("wer") or d.get("actor") or (None if "nach" in d else d.get("von"))
    daten = _klein(d, ("art", "status", "zustand", "name", "workflow", "alter_h", "titel", "text", "ergebnis", "sha", "lauf",
                       "url", "jobs", "in_min", "grund", "fingerprint", "seit", "anzahl",
                       "entity_id", "domaene", "nach", "werkzeug", "ziel", "befehl", "profil", "aktion_id", "rc", "dauer_s",
                       "trocken", "typ", "v", "teile"))
    if "nach" in d and d.get("von") not in (None, ""):
        daten["von"] = d["von"] if isinstance(d["von"], (int, float, bool)) else _kurz(d["von"], 200)
    return _umschlag(strom, eid, thema, z, schwere, _kurz(f.get("source") or "hub", 40), verweis, von, daten)


def aus_thema(strom: str, eid: str, f: dict[str, Any]) -> dict[str, Any] | None:
    """Einträge mit `topic` und `payload` (JSON): ts, source, topic, payload, id."""
    thema = str(f.get("topic") or (strom[len(PRAEFIX_BUS):] if strom.startswith(PRAEFIX_BUS) else strom))
    p = _json(f.get("payload"))
    schwere = _schwere(p.get("severity") or p.get("schwere") or p.get("level"), thema)
    verweis = p.get("node") or p.get("service") or p.get("name") or p.get("ticket") or p.get("entity_id") or p.get("id")
    z = _zeit(f.get("ts")) or _zeit(p.get("ts"))
    return _umschlag(strom, eid, thema, z, schwere, _kurz(f.get("source") or "bus", 40), verweis,
                     p.get("actor"), _klein(p, ("node", "service", "status", "name", "reason", "titel", "title")))


def _thema_aus_strom(strom: str) -> str:
    """`fyos:events:freigabe.neu` → `freigabe.neu`; `fyos:live` → `live`; `fyos:pane:dwell` → `pane.dwell`; sonst unverändert."""
    if strom.startswith(PRAEFIX_BUS):
        return strom[len(PRAEFIX_BUS):]
    return strom[len("fyos:"):].replace(":", ".") if strom.startswith("fyos:") else strom


#: Kurzfelder der Sammelströme `fyos:live` (Plugin p, Methode m, Ergebnis s, Dauer d, Aufrufer w, Art a) und
#: `fyos:entwicklung:ereignisse` (Zeit t in ms, Art a, Quelle q, Projekt o, Werkzeug n, Dauer d).
STROM_LIVE = "fyos:live"
STROM_ENTWICKLUNG = "fyos:entwicklung:ereignisse"


def aus_flach(strom: str, eid: str, f: dict[str, Any]) -> dict[str, Any] | None:
    """Flache Felder: freigabe.* (ticket, titel, assignee, severity, ts), `bus.tool.<plugin>.<methode>.<ok|fail>` (plugin, method,
    status, latency_ms), `fyos:live` und `fyos:entwicklung:ereignisse` (Kurzfelder, Zeit `t` in ms), `fyos:pane:dwell` (pane, start)."""
    thema = _thema_aus_strom(strom)
    z = _zeit(f.get("ts") or f.get("t") or f.get("zeit") or f.get("start"))
    schwere = _schwere(f.get("severity") or f.get("schwere"), thema)
    quelle = _kurz(f.get("source") or f.get("q") or "bus", 40)
    verweis = f.get("ticket") or f.get("ticket_id")
    von = f.get("actor") or f.get("assignee")
    if strom == STROM_LIVE:
        verweis = ".".join(x for x in (f.get("p"), f.get("m")) if x) or None
        von = f.get("w")
        schwere = "info" if f.get("s") in (None, "ok") else "normal"
        daten = _klein({"plugin": f.get("p"), "methode": f.get("m"), "ergebnis": f.get("s"), "art": f.get("k") or f.get("a"),
                        "dauer_ms": f.get("d")}, ("plugin", "methode", "ergebnis", "art", "dauer_ms"))
        return _umschlag(strom, eid, thema, z, schwere, "hub", verweis, von, daten)
    if strom == STROM_ENTWICKLUNG:
        art = {"e": "eingabe", "w": "werkzeug", "z": "zug"}.get(str(f.get("a")), str(f.get("a") or ""))
        daten = _klein({"art": art, "werkzeug": f.get("n"), "dauer_ms": f.get("d"), "abgebrochen": f.get("x") == "1" or None},
                       ("art", "werkzeug", "dauer_ms", "abgebrochen"))
        return _umschlag(strom, eid, thema, z, "info", quelle, f.get("o"), None, daten)
    if f.get("plugin") and f.get("method"):  # bus.tool.*
        verweis = f"{f['plugin']}.{f['method']}"
        schwere = "info" if str(f.get("status")) == "ok" else "normal"
        return _umschlag(strom, eid, thema, z, schwere, _kurz(f.get("plugin"), 40), verweis, f.get("caller"),
                         _klein(f, ("plugin", "method", "status", "latency_ms")))
    if f.get("pane") and not verweis:
        verweis = f.get("pane")
    return _umschlag(strom, eid, thema, z, schwere, quelle, verweis, von,
                     _klein(f, ("titel", "assignee", "status", "waiting_for", "pane", "dauer_ms")))


def normalisieren(strom: str, eid: str, felder: dict[str, Any]) -> dict[str, Any] | None:
    """Ein Strom-Eintrag → Umschlag, oder None, wenn nichts Lesbares drinsteht. Wirft nie."""
    try:
        f = {str(k): v for k, v in (felder or {}).items()}
        if strom == STROM_ITSM:
            return aus_itsm(eid, f)
        if strom in (STROM_SCHLEIFEN, STROM_ERKUNDEN):
            return aus_schleifen(strom, eid, f)
        if "payload" in f and "topic" in f:
            return aus_thema(strom, eid, f)
        if "data" in f:
            return aus_bus(strom, eid, f)
        if f:
            return aus_flach(strom, eid, f)
    except Exception:  # noqa: BLE001 — ein krummer Eintrag darf den Leser nie stoppen
        return None
    return None


def passt(thema: str, muster: list[str] | tuple[str, ...]) -> bool:
    """Thema gegen Muster: exakt, `prefix.*` oder `*`."""
    for m in muster:
        if m == "*" or m == thema:
            return True
        if m.endswith(".*") and thema.startswith(m[:-1]):
            return True
    return False


def weckt_diese(u: dict[str, Any], regeln: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Die erste Weckregel, auf die der Umschlag passt, sonst None.

    Regel: {thema: [Muster], von: [Akteure]?, nicht_von: [Akteure]?, ...}. `nicht_von` hält eigene Spuren fern (kein Echo)."""
    for rg in regeln or []:
        if not passt(u["thema"], rg.get("thema") or []):
            continue
        if u.get("von") and u["von"] in [str(x).lower() for x in rg.get("nicht_von") or []]:
            continue
        if rg.get("von") and u.get("von") not in [str(x).lower() for x in rg["von"]]:
            continue
        return rg
    return None


#: Ereignisarten (Themen) des Umschlags. Wer ein Ereignis schreibt, nimmt eines dieser Themen; neue Themen sind erlaubt,
#: gehören aber hierher, damit Erzeuger, Weckregeln und Brücke dieselbe Sprache sprechen.
EREIGNISARTEN: dict[str, str] = {
    "itsm.neu": "Vorgang angelegt (Schwere aus severity)",
    "itsm.kommentar": "Kommentar an einem Vorgang (von = Akteur)",
    "itsm.zugewiesen": "Zuständigkeit geändert",
    "itsm.status": "Status geändert",
    "itsm.aktualisiert": "andere Felder geändert",
    "itsm.erneut": "Vorgang trat erneut auf",
    "ci.lauf": "abgeschlossener CI-Lauf auf main; daten.ergebnis = erfolg | fehler, workflow, lauf, sha",
    "flux.alert": "Flux-Objekt länger als N Minuten nicht bereit",
    "flux.ok": "Flux-Objekt wieder bereit",
    "backup.alt": "Backup zu alt (schwere hoch | kritisch)",
    "backup.ok": "Backup wieder frisch",
    "termin.gleich": "Termin beginnt in Kürze; nur daten.in_min, nie Titel oder Ort",
    "postfach.neu": "neue ungelesene Post; nur daten.anzahl, nie Absender oder Betreff",
    "dokumente.neu": "neue Dokumente im Eingang; nur daten.anzahl, nie Titel oder Inhalt",
    "quelle.stumm": "eine Quelle antwortet nicht mehr (daten.name, daten.art = adapter | wache | strom, daten.text, daten.seit)",
    "quelle.lebt": "die Quelle antwortet wieder",
    "node.critical": "Knoten kritisch",
    "node.recovered": "Knoten wieder gesund",
    "services.service_down": "Dienst ausgefallen",
    "services.service_recovered": "Dienst wieder da",
    "schleifen.totmann": "Schleife ohne Durchgang seit N Stunden",
    "seco.nachsehen": "ein Workflow sieht nach, wie er es sich vorgenommen hat (von der Weiche erzeugt)",
}

#: Vorgabe von OpenClaw selbst, wenn weder Argument noch Umgebung eine Kennung nennen.
AGENT_VORGABE = "main"
#: Vorgangsnummer: Präfix, Bindestrich, Zähler oder Kurzkennung (INC-1234, WB-1a2b3c4d).
_VORGANG = re.compile(r"^[A-Za-z]{2,6}-[A-Za-z0-9]{1,16}$")


def vorgang_gueltig(vorgang: str) -> bool:
    return bool(_VORGANG.match(str(vorgang).strip()))


def agent_kennung(agent: str | None = None) -> str:
    """Kennung des OpenClaw-Agenten: Argument, sonst Umgebung `FYOS_AGENT`, sonst die OpenClaw-Vorgabe `main`."""
    return (agent or os.getenv("FYOS_AGENT") or AGENT_VORGABE).strip()


def sitzungsschluessel(vorgang: str, agent: str | None = None) -> str:
    """Stabiler Sitzungsschlüssel zu einem Vorgang: `agent:<id>:vorgang:INC-1234` (Laufzeit = Vorgang)."""
    return f"agent:{agent_kennung(agent)}:vorgang:{str(vorgang).strip().upper()}"


def vorgang_aus_schluessel(schluessel: str) -> tuple[str, str] | None:
    """Umkehrung: `agent:wache:vorgang:INC-1234` → (`wache`, `INC-1234`); alles andere (z. B. `agent:wache:main`) → None."""
    teile = str(schluessel).split(":")
    if len(teile) == 4 and teile[0] == "agent" and teile[2] == "vorgang" and teile[1] and _VORGANG.match(teile[3]):
        return teile[1], teile[3].upper()
    return None
