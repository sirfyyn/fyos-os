"""shell — die Arbeitsfläche der FYOS-Shell als Hub-Werkzeuge.

Zwei Seiten, ein Zustand:
  * Die Shell (Browser) meldet ihre Anordnung (`merken`) und holt Befehle ab (`abholen`).
  * Der Agent (jeder MCP-Client) liest sie (`zustand`) und ordnet sie (`befehl`).

So weiss der Agent, was gerade offen ist, kann Flaechen oeffnen, schliessen und minimieren —
und die Anordnung liegt im Hub, nicht nur im Browser: Handy und Rechner sehen dieselbe.

Ablage über `mcp_hub.kv`: Redis (`REDIS_URL`), ohne Redis der Speicher des Prozesses:
    fyos:shell:anordnung   JSON {fenster, agent, verfuegbar, ts}        (30 Tage)
    fyos:shell:befehle     Liste von JSON-Befehlen, hoechstens 20        (10 Minuten)

Flaechen-IDs: `seite:<slug>` · `app:<mcp-name>` · `nativ:<name>` · `agent` — nichts anderes wird angenommen.

Die Shell hat Bildschirme (0 = Start, dahinter Arbeitsbildschirme) und ein 12er-Raster je Bildschirm: Fenster
tragen `spalten`, `zeilen`, `neueZeile`. `merken` nimmt `bildschirme` und `aktiv` mit; `fenster` bleibt die flache
Liste aller Fenster (fuer Agenten). Der Befehl bewirkt nur, was die Shell sowieso darf (offen/zu/minimiert); sie
fuehrt ihn aus, nicht der Hub. Die Werkzeuge schreiben keine Daten der Flaechen selbst.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .. import kv
from ..plugin import HubPlugin, ToolDescriptor

SCHLUESSEL_ANORDNUNG = "fyos:shell:anordnung"
SCHLUESSEL_BEFEHLE = "fyos:shell:befehle"
SCHLUESSEL_PLAETZE = "fyos:shell:plaetze"
PLAETZE_MAX = 12
NAME_MUSTER = re.compile(r"^[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9 \-]{1,29}$")
ANORDNUNG_TTL_S = 30 * 24 * 3600
BEFEHLE_TTL_S = 600
BEFEHLE_MAX = 20
FENSTER_MAX = 16
AKTIONEN = ("oeffnen", "schliessen", "minimieren", "wiederherstellen", "bildschirm")
ID_MUSTER = re.compile(
    r"^(agent|seite:[a-z0-9][a-z0-9\-/_]{0,60}|app:[a-z0-9][a-z0-9_]{0,80}|nativ:[a-z0-9][a-z0-9_\-]{0,60})$"
)
BILDSCHIRME_MAX = 9
SPALTEN = (3, 12)
ZEILEN = (4, 24)
_TAGS_LESEN = ["shell", "read", "flaeche"]
_TAGS_SCHREIBEN = ["shell", "write", "flaeche"]


def _redis():
    return kv.klient()


def gueltiger_name(x: Any) -> bool:
    return isinstance(x, str) and bool(NAME_MUSTER.match(x))


def gueltige_id(x: Any) -> bool:
    return isinstance(x, str) and bool(ID_MUSTER.match(x))


def _zahl(x: Any, grenzen: tuple[int, int]) -> int | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return max(grenzen[0], min(grenzen[1], int(round(x))))


def fenster_pruefen(roh: Any, gesehen: set[str] | None = None) -> list[dict[str, Any]]:
    """Nur bekannte Felder und gueltige IDs; keine Doppelten; hoechstens FENSTER_MAX.

    Raster (seit 03.10.): `spalten` 3–12, `zeilen` 4–24, `neueZeile`. Altes `breit` wird zu 12 Spalten.
    """
    out: list[dict[str, Any]] = []
    gesehen = gesehen if gesehen is not None else set()
    for w in roh if isinstance(roh, list) else []:
        if not isinstance(w, dict) or not gueltige_id(w.get("id")) or w["id"] in gesehen:
            continue
        gesehen.add(w["id"])
        f: dict[str, Any] = {"id": w["id"], "min": bool(w.get("min"))}
        spalten = _zahl(w.get("spalten"), SPALTEN)
        if spalten is None and w.get("breit") is True:
            spalten = SPALTEN[1]
        if spalten is not None:
            f["spalten"] = spalten
            f["zeilen"] = _zahl(w.get("zeilen"), ZEILEN) or 10
        if w.get("neueZeile") is True:
            f["neueZeile"] = True
        out.append(f)
    return out[:FENSTER_MAX]


def bildschirme_pruefen(roh: Any) -> list[dict[str, Any]]:
    """Arbeitsbildschirme: Name, ID, Fenster; jede Flaeche nur einmal ueber alle; hoechstens 9."""
    out: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for b in roh if isinstance(roh, list) else []:
        if not isinstance(b, dict) or len(out) >= BILDSCHIRME_MAX:
            continue
        name = str(b.get("name") or "").strip()[:30] or f"Bildschirm {len(out) + 1}"
        bid = str(b.get("id") or "")[:40] or f"b{len(out) + 1}"
        out.append({"id": bid, "name": name, "fenster": fenster_pruefen(b.get("fenster"), gesehen)})
    return out


class ShellPlugin(HubPlugin):
    name = "shell"
    description = (
        "FYOS-Shell: welche Flaechen offen sind lesen und Flaechen oeffnen, schliessen, minimieren "
        "(die Shell fuehrt es aus). Die Anordnung liegt im Hub."
    )
    version = "0.1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self._r = None  # Tests setzen eine Attrappe

    def register(self) -> None:
        return None

    def redis(self):
        return self._r if self._r is not None else _redis()

    def health(self) -> dict[str, Any]:
        try:
            self.redis().ping()
            return {"ok": True, "status": "ok"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "status": "unhealthy", "error": str(e)[:120]}

    def describe_tools(self) -> list[ToolDescriptor]:
        leer = {"type": "object", "properties": {}, "additionalProperties": False}
        return [
            ToolDescriptor(
                name="zustand",
                title="Was ist offen?",
                description=(
                    "Zeigt die Arbeitsflaeche der FYOS-Shell: offene und minimierte Flaechen (in Reihenfolge), "
                    "die Bildschirme (0 = Start mit der Zentrale, dahinter Arbeitsbildschirme, `aktiv`), ob der "
                    "Agent-Dock offen ist, und welche Flaechen es gibt (`verfuegbar`, mit id und Titel). "
                    "IDs: seite:<name> · app:<name> · nativ:<name> · agent."
                ),
                input_schema=leer,
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="befehl",
                title="Flaeche oeffnen oder schliessen",
                description=(
                    "Bittet die Shell, eine Flaeche zu oeffnen, zu schliessen, zu minimieren oder zurueckzuholen, "
                    "oder (aktion `bildschirm`) zu einem Bildschirm zu wechseln (`name` oder `index`, 0 = Start). "
                    "Die Shell fuehrt es innerhalb weniger Sekunden aus, wenn sie offen ist. `flaeche` ist eine ID "
                    "aus `shell.zustand`.verfuegbar (z. B. seite:uebersicht, app:werkstatt__suchen, nativ:notizen). "
                    "Aendert nur die Anordnung, keine Daten."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "aktion": {"type": "string", "enum": list(AKTIONEN)},
                        "flaeche": {
                            "type": "string",
                            "description": "seite:<name> | app:<name> | nativ:<name> | agent",
                        },
                        "name": {"type": "string", "maxLength": 30},
                        "index": {"type": "integer", "minimum": 0, "maximum": BILDSCHIRME_MAX},
                    },
                    "required": ["aktion"],
                    "additionalProperties": False,
                },
                tags=_TAGS_SCHREIBEN,
            ),
            ToolDescriptor(
                name="plaetze",
                title="Arbeitsplaetze",
                description="Die gespeicherten Arbeitsplaetze (benannte Anordnungen, z. B. Morgen, Haus, Betrieb) mit ihren Flaechen.",
                input_schema=leer,
                tags=_TAGS_LESEN,
            ),
            ToolDescriptor(
                name="platz_laden",
                title="Arbeitsplatz wechseln",
                description="Bittet die Shell, einen gespeicherten Arbeitsplatz zu laden (ersetzt die offenen Flaechen). `name` aus shell.plaetze.",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 2, "maxLength": 30}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                tags=_TAGS_SCHREIBEN,
            ),
            ToolDescriptor(
                name="platz_speichern",
                title="Arbeitsplatz speichern",
                description=(
                    "Speichert eine Anordnung unter einem Namen (hoechstens 12 Arbeitsplaetze; ein vorhandener Name wird "
                    "ueberschrieben). Ohne `fenster` wird die aktuelle Anordnung der Shell gespeichert."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 2, "maxLength": 30},
                        "fenster": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                tags=_TAGS_SCHREIBEN,
            ),
            ToolDescriptor(
                name="platz_entfernen",
                title="Arbeitsplatz entfernen",
                description="Entfernt einen gespeicherten Arbeitsplatz (nur die Anordnung, keine Daten der Flaechen).",
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 2, "maxLength": 30}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                tags=_TAGS_SCHREIBEN,
            ),
            ToolDescriptor(
                name="merken",
                title="Anordnung melden (Shell)",
                description=(
                    "Nur fuer die Shell selbst: meldet die aktuelle Anordnung (fenster, agent, verfuegbar). "
                    "Nicht fuer Modelle gedacht."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "fenster": {"type": "array", "items": {"type": "object"}},
                        "bildschirme": {"type": "array", "items": {"type": "object"}},
                        "aktiv": {"type": "integer", "minimum": 0, "maximum": BILDSCHIRME_MAX},
                        "agent": {"type": "boolean"},
                        "verfuegbar": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["fenster"],
                    "additionalProperties": False,
                },
                tags=_TAGS_SCHREIBEN,
            ),
            ToolDescriptor(
                name="abholen",
                title="Befehle abholen (Shell)",
                description="Nur fuer die Shell selbst: holt die wartenden Befehle ab und leert die Warteschlange.",
                input_schema=leer,
                tags=_TAGS_SCHREIBEN,
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if method == "zustand":
            return self.zustand()
        if method == "befehl":
            return self.befehl(args)
        if method == "merken":
            return self.merken(args)
        if method == "plaetze":
            return self.plaetze()
        if method == "platz_laden":
            return self.platz_laden(args)
        if method == "platz_speichern":
            return self.platz_speichern(args)
        if method == "platz_entfernen":
            return self.platz_entfernen(args)
        if method == "abholen":
            return self.abholen()
        raise ValueError(f"shell hat kein Werkzeug {method!r}")

    def zustand(self) -> dict[str, Any]:
        roh = self.redis().get(SCHLUESSEL_ANORDNUNG)
        if not roh:
            return {
                "bekannt": False,
                "fenster": [],
                "agent": False,
                "verfuegbar": [],
                "hinweis": "Die Shell hat sich noch nicht gemeldet (Shell im Browser öffnen).",
            }
        d = json.loads(roh)
        return {
            "bekannt": True,
            "alter_s": int(time.time() - d.get("ts", 0)),
            **{k: d.get(k) for k in ("fenster", "bildschirme", "aktiv", "agent", "verfuegbar")},
        }

    def merken(self, args: dict[str, Any]) -> dict[str, Any]:
        verf = [
            {"id": v["id"], "titel": str(v.get("titel") or "")[:60]}
            for v in (args.get("verfuegbar") if isinstance(args.get("verfuegbar"), list) else [])
            if isinstance(v, dict) and gueltige_id(v.get("id"))
        ][:200]
        bildschirme = bildschirme_pruefen(args.get("bildschirme"))
        aktiv = args.get("aktiv")
        d = {
            "fenster": fenster_pruefen(args.get("fenster")),
            "bildschirme": bildschirme,
            "aktiv": aktiv if isinstance(aktiv, int) and 0 <= aktiv <= len(bildschirme) else 0,
            "agent": bool(args.get("agent")),
            "verfuegbar": verf,
            "ts": time.time(),
        }
        self.redis().set(
            SCHLUESSEL_ANORDNUNG, json.dumps(d, ensure_ascii=False), ex=ANORDNUNG_TTL_S
        )
        return {"ok": True, "fenster": len(d["fenster"])}

    def befehl(self, args: dict[str, Any]) -> dict[str, Any]:
        aktion, flaeche = args.get("aktion"), args.get("flaeche")
        if aktion not in AKTIONEN:
            raise ValueError(f"aktion muss eine von {AKTIONEN} sein")
        eintrag: dict[str, Any] = {"aktion": aktion, "ts": time.time()}
        if aktion == "bildschirm":
            name, index = args.get("name"), args.get("index")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= BILDSCHIRME_MAX:
                eintrag["index"] = index
            elif isinstance(name, str) and name.strip():
                eintrag["name"] = name.strip()[:30]
            else:
                raise ValueError("bildschirm: name oder index (0 = Start) angeben")
            ziel = eintrag.get("name", eintrag.get("index"))
        else:
            if not gueltige_id(flaeche):
                raise ValueError("flaeche: seite:<name>, app:<name>, nativ:<name> oder agent")
            eintrag["flaeche"] = flaeche
            ziel = flaeche
        r = self.redis()
        r.rpush(SCHLUESSEL_BEFEHLE, json.dumps(eintrag))
        r.ltrim(SCHLUESSEL_BEFEHLE, -BEFEHLE_MAX, -1)
        r.expire(SCHLUESSEL_BEFEHLE, BEFEHLE_TTL_S)
        bekannt = self.zustand()
        return {
            "ok": True,
            "vorgemerkt": f"{aktion} {ziel}",
            "shell_gemeldet": bekannt["bekannt"],
            "hinweis": None
            if bekannt["bekannt"]
            else "Die Shell ist nicht offen; der Befehl gilt 10 Minuten.",
        }

    def plaetze(self) -> dict[str, Any]:
        roh = self.redis().hgetall(SCHLUESSEL_PLAETZE) or {}
        out = []
        for name in sorted(roh):
            try:
                out.append({"name": name, "fenster": fenster_pruefen(json.loads(roh[name]))})
            except ValueError:
                continue
        return {"plaetze": out}

    def platz_speichern(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not gueltiger_name(name):
            raise ValueError("name: 2-30 Zeichen, Buchstaben, Ziffern, Leerzeichen, Bindestrich")
        r = self.redis()
        if args.get("fenster") is not None:
            fenster = fenster_pruefen(args.get("fenster"))
        else:
            roh = r.get(SCHLUESSEL_ANORDNUNG)
            if not roh:
                raise ValueError(
                    "Die Shell hat sich noch nicht gemeldet — nichts zu speichern (Shell im Browser öffnen)"
                )
            fenster = fenster_pruefen(json.loads(roh).get("fenster"))
        if not fenster:
            raise ValueError("Keine Flaechen offen — ein leerer Arbeitsplatz ist keiner")
        vorhanden = r.hgetall(SCHLUESSEL_PLAETZE) or {}
        if name not in vorhanden and len(vorhanden) >= PLAETZE_MAX:
            raise ValueError(f"Schon {PLAETZE_MAX} Arbeitsplaetze — erst einen entfernen")
        r.hset(SCHLUESSEL_PLAETZE, name, json.dumps(fenster, ensure_ascii=False))
        return {
            "ok": True,
            "name": name,
            "fenster": len(fenster),
            "ueberschrieben": name in vorhanden,
        }

    def platz_entfernen(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not gueltiger_name(name):
            raise ValueError("name ungueltig")
        return {"ok": True, "entfernt": bool(self.redis().hdel(SCHLUESSEL_PLAETZE, name))}

    def platz_laden(self, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not gueltiger_name(name):
            raise ValueError("name ungueltig")
        r = self.redis()
        if not r.hexists(SCHLUESSEL_PLAETZE, name):
            raise ValueError(f"Arbeitsplatz {name!r} gibt es nicht — shell.plaetze zeigt alle")
        r.rpush(
            SCHLUESSEL_BEFEHLE, json.dumps({"aktion": "platz", "name": name, "ts": time.time()})
        )
        r.ltrim(SCHLUESSEL_BEFEHLE, -BEFEHLE_MAX, -1)
        r.expire(SCHLUESSEL_BEFEHLE, BEFEHLE_TTL_S)
        return {"ok": True, "vorgemerkt": f"platz {name}"}

    def abholen(self) -> dict[str, Any]:
        r = self.redis()
        roh = r.lrange(SCHLUESSEL_BEFEHLE, 0, -1)
        if roh:
            r.delete(SCHLUESSEL_BEFEHLE)
        out = []
        for z in roh:
            try:
                b = json.loads(z)
            except ValueError:
                continue
            if b.get("aktion") == "bildschirm":
                # „bildschirm“ hat keine Fläche; der Zweig darunter würde ihn verwerfen
                index, name = b.get("index"), b.get("name")
                if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= BILDSCHIRME_MAX:
                    out.append({"aktion": "bildschirm", "index": index})
                elif isinstance(name, str) and name.strip():
                    out.append({"aktion": "bildschirm", "name": name.strip()[:30]})
            elif b.get("aktion") in AKTIONEN and gueltige_id(b.get("flaeche")):
                out.append({"aktion": b["aktion"], "flaeche": b["flaeche"]})
            elif b.get("aktion") == "platz" and gueltiger_name(b.get("name")):
                out.append({"aktion": "platz", "name": b["name"]})
        return {"befehle": out}
