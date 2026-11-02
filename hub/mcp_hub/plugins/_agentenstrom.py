"""Agentenstrom `fyos:agent` — Ereignisvertrag eines Agenten-Runners.

Ein Agenten-Runner (ein Modell-Agent im RPC-Modus, etwa als Systemdienst) übersetzt die Ereignisse
seiner Sitzung in den Redis-Strom `fyos:agent` des Hubs. Alle Betrachter — Matrix, Vorgangssystem,
Oberflächen, Chat — lesen nur diesen Strom; ein SSE-/App-Kanal ist Projektion, kein zweiter Speicher:
typisierte Agenten-Ereignisse, Part-Typen, Werkzeug-FSM `pending → running → completed|error`,
Autonomie `proposal` als Vorgabe.

Der Weg auf den Hub ist die Meldestrecke `POST /hub/agent/melden` (Plugin `agent`); der Runner
braucht keinen Zugang zu Redis, nur der Hub schreibt in den Strom.

Dieses Modul ist die einzige Quelle für Feldnamen, Graphie und Kürzungsregel. Es nutzt nur die
Standardbibliothek, damit ein Runner dieselbe Datei verwenden kann wie die Betrachter im Hub.

Eisenharte Regel: ein Ereignis trägt Typ, Agenten-ID, Sitzungs-ID, Sequenz, Zeit und die
gekürzte Nutzlast — keine Geheimnisse, keine vollständigen Werkzeug-Argumente. Wer ein Feld
ergänzt, ergänzt es für alle Betrachter und zieht Tests und ADR mit.

Felder je Eintrag (alles Zeichenketten, wie Redis sie liefert):
    t            Zeit in Millisekunden seit 1970 (Ende des Schritts)
    v            Vertragsversion ("1")
    typ          Ereignisart (siehe ARTEN; `connected` ist SSE-Rahmen, kein Stromereignis)
    a            Agenten-ID, klein (^[a-z0-9_-]{1,32}$), z. B. "agent"
    s            Sitzungs-ID (^[A-Za-z0-9._:-]{1,64}$)
    q            Sequenz je Sitzung, aufsteigend ab 1 (Ordnung bei gleicher t)

Je typ (optionale Felder fehlen, wenn leer; Textfelder gekürzt mit "…"):
    part.updated id, pt (text|reasoning|tool|step); delta ≤ 2000 (text/reasoning, wird vom
                 Betrachter angehängt — Form bleibt erhalten); st (pending|running|completed|
                 error), wz, args (JSON-Vorschau ≤ 300, Geheimnisse ersetzt), ergebnis ≤ 1000,
                 vertr "0" für ungeprüfte Quellen — (tool); label ≤ 200, phase start|finish
                 — (step)
    part.done    id
    plan.update  schritte: JSON, höchstens 20 Schritte {id, label ≤ 200, state pending|active|
                 done}
    proposal     id, aktion ≤ 200, risiko (low|medium|high), kontext ≤ 600, zerstoererisch "1",
                 optionen (Kommaliste aus once|session|always|deny)
    ui_request   id, methode (select|confirm|input|editor|notify|setStatus|setWidget|setTitle),
                 nutzlast: JSON-Vorschau ≤ 2000, Geheimnisse ersetzt
    usage        modell ≤ 80, tier (light|normal|heavy), ctx, ctx_max (Ganzzahlen ≥ 0),
                 kosten_micro_eur (optional, Ganzzahl ≥ 0)
    session.idle —
    error        nachricht ≤ 600, art ≤ 40
    ruhe         an "1"|"0" (Schalter), pausiert "1"|"0" (Ruhe oder Spielmodus), stufe normal|tief
                 (Vorgabe normal), quelle ≤ 20 (etwa schalter|nachtruhe|spielmodus), grund ≤ 200,
                 bis ≤ 40 (ISO-Zeitpunkt), von ≤ 40 — der Ruhe-Schalter eines Runners; an und
                 pausiert sind Pflicht, alles andere optional

Kürzungsregel: Steuerzeichen fallen weg (in mehrzeiligen Texten bleiben Zeilenumbruch und
Tabulator erhalten), einzeilige Felder werden zusammengezogen, Textfelder auf ihre Obergrenze
gekürzt (Marke "…" zählt mit). `args` und `nutzlast` werden vor der Kürzung als kompaktes JSON
gegossen und Geheimnis-Felder (token|secret|passwor|schlüssel|key) durch "…" ersetzt. Ein
Eintrag bleibt unter 12 000 Zeichen; würde er größer, weicht das jeweils größte kürzbare Feld.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

STROM = "fyos:agent"
VERTRAG = "1"
#: Obergrenze (ungefähr, `MAXLEN ~`): viele kleine Deltas je Zug — das reicht für etwa einen Tag Betrieb.
MAXLEN = 50_000

#: Obergrenzen der Meldestrecke (`POST /hub/agent/melden`): je Anfrage höchstens EREIGNISSE_MAX
#: Ereignisse und BODY_MAX_BYTES Zeichen. Ein Runner liest dieselben Zahlen und
#: hält seine Flush-Grenze deutlich darunter — so können die beiden Seiten nicht auseinanderlaufen.
EREIGNISSE_MAX = 200
BODY_MAX_BYTES = 64 * 1024

ARTEN = (
    "part.updated",
    "part.done",
    "plan.update",
    "proposal",
    "ui_request",
    "usage",
    "session.idle",
    "error",
    "ruhe",
)
RUHE_STUFEN = ("normal", "tief")
PART_TYPEN = ("text", "reasoning", "tool", "step")
WERKZEUG_ZUSTAENDE = ("pending", "running", "completed", "error")
PHASEN = ("start", "finish")
SCHRITT_ZUSTAENDE = ("pending", "active", "done")
RISIKEN = ("low", "medium", "high")
OPTIONEN = ("once", "session", "always", "deny")
UI_METHODEN = (
    "select",
    "confirm",
    "input",
    "editor",
    "notify",
    "setStatus",
    "setWidget",
    "setTitle",
)
TIERS = ("light", "normal", "heavy")

DELTA_MAX = 2000
ERGEBNIS_MAX = 1000
ARGS_MAX = 300
NUTZLAST_MAX = 2000
LABEL_MAX = 200
AKTION_MAX = 200
KONTEXT_MAX = 600
NACHRICHT_MAX = 600
ART_MAX = 40
GRUND_MAX = 200
MODELL_MAX = 80
SCHRITTE_MAX = 20
PLAN_JSON_MAX = 8192
GESAMT_MAX = 12_000
KUERZUNG = "…"

_AGENT = re.compile(r"^[a-z0-9_-]{1,32}$")
_SITZUNG = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_AGENT_UNERLAUBT = re.compile(r"[^a-z0-9_-]")
_ID_UNERLAUBT = re.compile(r"[^A-Za-z0-9._:-]")
_WERKZEUG_UNERLAUBT = re.compile(r"[^A-Za-z0-9_.:-]")
#: Einzeilig: alles inklusive Zeilenumbruch fällt; mehrzeilig: nur echte Steuerzeichen, \n und \t bleiben.
_EINZEILIG = re.compile(r"[\x00-\x1f\x7f]")
_MEHRZEILIG = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
#: Geheimnis-Felder in JSON-Vorschauen (bewusst übererfasst: jeder Schlüssel mit "key" u. Ä. zählt).
_GEHEIM = re.compile(
    r'(?i)("[^"]*(?:token|secret|passwor|schl(?:ü|ue)ssel|key)[^"]*")\s*:\s*(?:"(?:[^"\\]|\\.)*"|[^,}\]\s]+)'
)


def _kurzen(s: str, grenze: int) -> str:
    """Auf `grenze` Zeichen kürzen; die Marke "…" zählt mit."""
    if len(s) <= grenze:
        return s
    if grenze <= 1:
        return s[:grenze]
    return s[: grenze - 1] + KUERZUNG


def _text(wert: Any, grenze: int, *, einzeln: bool = False) -> str:
    """Textfeld: Steuerzeichen weg, einzeilige Felder zusammengezogen, dann gekürzt.

    Mehrzeilige Texte behalten ihre Form — auch führende und abschließende Zeilenumbrüche,
    denn Deltas werden vom Betrachter angehängt.
    """
    if wert is None:
        return ""
    s = str(wert)
    s = _EINZEILIG.sub(" ", s) if einzeln else _MEHRZEILIG.sub("", s)
    if einzeln:
        s = " ".join(s.split())
    return _kurzen(s, grenze)


def _agent(wert: Any) -> str:
    """Agenten-ID: klein, nur [a-z0-9_-], höchstens 32 Zeichen."""
    s = _AGENT_UNERLAUBT.sub("", str(wert or "").lower())[:32]
    if not _AGENT.match(s):
        raise ValueError(f"Agenten-ID unbrauchbar: {wert!r}")
    return s


def _kennung(wert: Any) -> str:
    """Teil-/Schritt-Kennung: unerlaubte Zeichen weg, höchstens 64 Zeichen."""
    return _ID_UNERLAUBT.sub("", str(wert if wert is not None else ""))[:64]


def _werkzeug(wert: Any) -> str:
    """Werkzeugname: einzeilig, wie Aufrufe im Hub ("plugin.werkzeug")."""
    return _WERKZEUG_UNERLAUBT.sub("", _text(wert, 64, einzeln=True))


def _ohne_geheimnisse(s: str) -> str:
    """Geheimnis-Felder einer JSON-Vorschau durch "…" ersetzen."""
    return _GEHEIM.sub(r'\1:"…"', s)


def _vorschau(wert: Any, grenze: int) -> str:
    """JSON-Vorschau für `args`/`nutzlast`: kompakt, Geheimnisse ersetzt, dann gekürzt."""
    try:
        s = json.dumps(wert, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        s = _text(wert, grenze * 2)
    return _kurzen(_ohne_geheimnisse(_MEHRZEILIG.sub("", s)), grenze)


def _zahl(r: dict[str, Any], schluessel: str) -> int | None:
    """Ganzzahl ≥ 0 aus dem Ereignis; None, wenn nicht gesetzt."""
    w = r.get(schluessel)
    if w is None:
        return None
    if isinstance(w, bool) or not isinstance(w, (int, float)):
        raise ValueError(f"{schluessel} muss eine Zahl sein: {w!r}")
    if w != w or w < 0:  # NaN oder negativ
        raise ValueError(f"{schluessel} darf nicht negativ sein: {w!r}")
    return int(w)


def _teil(e: dict[str, str], typ: str, r: dict[str, Any]) -> None:
    """Typspezifische Felder anfügen und prüfen."""
    if typ == "part.updated":
        kennung = _kennung(r.get("id"))
        if not kennung:
            raise ValueError("part.updated ohne id")
        pt = str(r.get("pt") or "")
        if pt not in PART_TYPEN:
            raise ValueError(f"unbekannter Part-Typ: {pt!r}")
        e["id"] = kennung
        e["pt"] = pt
        if pt in ("text", "reasoning"):
            delta = _text(r.get("delta"), DELTA_MAX)
            if not delta:
                raise ValueError(f"part.updated({pt}) ohne delta")
            e["delta"] = delta
        elif pt == "tool":
            wz = _werkzeug(r.get("wz"))
            if wz:
                e["wz"] = wz
            st = str(r.get("st") or "")
            if st:
                if st not in WERKZEUG_ZUSTAENDE:
                    raise ValueError(f"unbekannter Werkzeug-Zustand: {st!r}")
                e["st"] = st
            if r.get("args") is not None:
                e["args"] = _vorschau(r.get("args"), ARGS_MAX)
            ergebnis = _text(r.get("ergebnis"), ERGEBNIS_MAX)
            if ergebnis:
                e["ergebnis"] = ergebnis
            if not any(k in e for k in ("wz", "st", "args", "ergebnis")):
                raise ValueError(
                    "part.updated(tool) trägt weder Werkzeug, Zustand, Argumente noch Ergebnis"
                )
            if r.get("vertr") is False or r.get("vertr") == "0":
                e["vertr"] = "0"
        else:  # step
            label = _text(r.get("label"), LABEL_MAX)
            if not label:
                raise ValueError("part.updated(step) ohne label")
            phase = str(r.get("phase") or "")
            if phase not in PHASEN:
                raise ValueError(f"unbekannte Phase: {phase!r}")
            e["label"] = label
            e["phase"] = phase
    elif typ == "part.done":
        kennung = _kennung(r.get("id"))
        if not kennung:
            raise ValueError("part.done ohne id")
        e["id"] = kennung
    elif typ == "plan.update":
        schritte = r.get("schritte")
        if not isinstance(schritte, list) or not schritte:
            raise ValueError("plan.update ohne Schritte")
        sauber: list[dict[str, str]] = []
        for schritt in schritte[:SCHRITTE_MAX]:
            if not isinstance(schritt, dict):
                raise ValueError(f"Schritt ist kein Objekt: {schritt!r}")
            sid = _kennung(schritt.get("id"))
            label = _text(schritt.get("label"), LABEL_MAX)
            zustand = str(schritt.get("state") or "")
            if not sid or not label or zustand not in SCHRITT_ZUSTAENDE:
                raise ValueError(f"unbrauchbarer Schritt: {schritt!r}")
            sauber.append({"id": sid, "label": label, "state": zustand})
        e["schritte"] = _kurzen(
            json.dumps(sauber, ensure_ascii=False, separators=(",", ":")), PLAN_JSON_MAX
        )
    elif typ == "proposal":
        kennung = _kennung(r.get("id"))
        aktion = _text(r.get("aktion"), AKTION_MAX)
        risiko = str(r.get("risiko") or "")
        if not kennung or not aktion:
            raise ValueError("proposal ohne id oder aktion")
        if risiko not in RISIKEN:
            raise ValueError(f"unbekanntes Risiko: {risiko!r}")
        e["id"] = kennung
        e["aktion"] = aktion
        e["risiko"] = risiko
        kontext = _text(r.get("kontext"), KONTEXT_MAX)
        if kontext:
            e["kontext"] = kontext
        if r.get("zerstoererisch"):
            e["zerstoererisch"] = "1"
        optionen = r.get("optionen")
        if optionen is not None:
            liste = (
                [str(o) for o in optionen]
                if isinstance(optionen, (list, tuple))
                else [str(optionen)]
            )
            if not liste or any(o not in OPTIONEN for o in liste):
                raise ValueError(f"unbekannte Optionen: {optionen!r}")
            e["optionen"] = ",".join(liste)
    elif typ == "ui_request":
        kennung = _kennung(r.get("id"))
        methode = str(r.get("methode") or "")
        if not kennung or methode not in UI_METHODEN:
            raise ValueError(
                f"ui_request ohne id oder mit unbekannter Methode: {r.get('methode')!r}"
            )
        e["id"] = kennung
        e["methode"] = methode
        if r.get("nutzlast") is not None:
            e["nutzlast"] = _vorschau(r.get("nutzlast"), NUTZLAST_MAX)
    elif typ == "usage":
        modell = _text(r.get("modell"), MODELL_MAX, einzeln=True)
        tier = str(r.get("tier") or "")
        if not modell or tier not in TIERS:
            raise ValueError(f"usage ohne Modell oder mit unbekanntem Tier: {r.get('tier')!r}")
        e["modell"] = modell
        e["tier"] = tier
        for schluessel in ("ctx", "ctx_max", "kosten_micro_eur"):
            zahl = _zahl(r, schluessel)
            if zahl is not None:
                e[schluessel] = str(zahl)
    elif typ == "error":
        nachricht = _text(r.get("nachricht"), NACHRICHT_MAX)
        if not nachricht:
            raise ValueError("error ohne Nachricht")
        e["nachricht"] = nachricht
        art = _text(r.get("art"), ART_MAX, einzeln=True)
        if art:
            e["art"] = art
    elif typ == "ruhe":
        stufe = str(r.get("stufe") or "normal")
        if stufe not in RUHE_STUFEN:
            raise ValueError(f"ruhe mit unbekannter Stufe: {r.get('stufe')!r}")
        for schluessel in ("an", "pausiert"):
            wert = r.get(schluessel)
            if wert not in (True, False, "1", "0", 1, 0):
                raise ValueError(f"ruhe: {schluessel} muss ein Wahrheitswert sein: {wert!r}")
            e[schluessel] = "1" if wert in (True, "1", 1) else "0"
        e["stufe"] = stufe
        for schluessel, grenze in (("quelle", 20), ("grund", GRUND_MAX), ("bis", 40), ("von", 40)):
            text = _text(r.get(schluessel), grenze, einzeln=True)
            if text:
                e[schluessel] = text
    # session.idle trägt nichts weiter.


def _passen(e: dict[str, str]) -> dict[str, str]:
    """Harte Obergrenze für den ganzen Eintrag: das größte kürzbare Feld weicht zuerst."""
    kuerzbar = [k for k in e if k not in ("t", "v", "typ", "a", "s", "q")]
    while sum(len(w) for w in e.values()) > GESAMT_MAX and kuerzbar:
        gross = max(kuerzbar, key=lambda k: len(e[k]))
        wert = e[gross]
        if len(wert) <= len(KUERZUNG):
            kuerzbar.remove(gross)
            continue
        kern = wert[: -len(KUERZUNG)] if wert.endswith(KUERZUNG) else wert
        e[gross] = _kurzen(kern, max(len(KUERZUNG) + 1, len(kern) // 2))
    return e


def eintrag(ereignis: dict[str, Any], jetzt_ms: int | None = None) -> dict[str, str]:
    """Rohes Ereignis -> Eintrag für den Strom. Wirft ValueError bei Verstößen gegen den Vertrag."""
    if not isinstance(ereignis, dict):
        raise ValueError("Ereignis muss ein Objekt sein")
    typ = str(ereignis.get("typ") or "")
    if typ not in ARTEN:
        raise ValueError(f"unbekannter Typ: {typ!r}")
    agent = _agent(ereignis.get("agent"))
    sitzung = _text(ereignis.get("sitzung"), 64, einzeln=True)
    if not _SITZUNG.match(sitzung):
        raise ValueError(f"Sitzungs-ID unbrauchbar: {ereignis.get('sitzung')!r}")
    q = ereignis.get("q")
    if isinstance(q, bool) or not isinstance(q, int) or q < 1:
        raise ValueError(f"Sequenz fehlt oder ist keine Zahl ab 1: {q!r}")
    t = ereignis.get("t")
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        t = jetzt_ms if jetzt_ms is not None else int(time.time() * 1000)
    e: dict[str, str] = {
        "t": str(int(t)),
        "v": VERTRAG,
        "typ": typ,
        "a": agent,
        "s": sitzung,
        "q": str(q),
    }
    _teil(e, typ, ereignis)
    return _passen(e)


def senden(r: Any, ereignis: dict[str, Any], jetzt_ms: int | None = None) -> str:
    """Einen Eintrag schreiben (XADD, `MAXLEN ~`). Fehler bleiben beim Aufrufer (fail-safe dort)."""
    e = eintrag(ereignis, jetzt_ms)
    return str(r.xadd(STROM, e, maxlen=MAXLEN, approximate=True))


def ablegen(r: Any, eintraege: list[dict[str, str]]) -> int:
    """Vorab geprüfte Einträge in einer Pipeline schreiben; liefert die Zahl."""
    if not eintraege:
        return 0
    pipe = r.pipeline()
    for e in eintraege:
        pipe.xadd(STROM, e, maxlen=MAXLEN, approximate=True)
    pipe.execute()
    return len(eintraege)


def senden_viele(r: Any, ereignisse: list[dict[str, Any]], jetzt_ms: int | None = None) -> int:
    """Mehrere Einträge in einer Pipeline; prüft alle vorher, schreibt dann. Liefert die Zahl.

    Ein unbrauchbares Ereignis bricht mit seinem laufenden Index ab — die Meldestrecke legt
    den Fehler damit auf ein einzelnes Ereignis statt auf die ganze Botschaft."""
    eintraege: list[dict[str, str]] = []
    for i, x in enumerate(ereignisse):
        try:
            eintraege.append(eintrag(x, jetzt_ms))
        except ValueError as fehler:
            raise ValueError(f"Ereignis {i}: {fehler}") from fehler
    return ablegen(r, eintraege)


# ── Lesen (GET /hub/agent/strom, 2026-10-18) ───────────────────────────

#: Je Abruf höchstens so viele Einträge (ein Zug sind viele kleine Deltas).
LESEN_ANZAHL_MAX = 500
#: Blockierend höchstens so lange (die lange Redis-Verbindung hat WARTE_MAX_S + 5 s Socket-Frist).
LESEN_WARTE_MAX_S = 25

_LESE_ID = re.compile(r"^(\$|0|\d{1,20}-\d{1,20})$")


def lese_id(wert: Any) -> str:
    """Leseposition prüfen: "$" (nur Neues), "0" (alles, was noch im Strom liegt) oder eine Strom-ID."""
    s = str(wert or "$")
    if not _LESE_ID.match(s):
        raise ValueError("nach: $, 0 oder eine Strom-ID wie 1792270000000-0")
    return s


def lesen(r: Any, nach: str, warte_s: float, anzahl: int, agent: str, sitzung: str | None = None) -> dict[str, Any]:
    """Einträge des Agenten nach `nach` lesen, höchstens `warte_s` blockierend. Liefert {eintraege, letzte}.

    Jeder Eintrag sind die Felder aus dem Strom plus `sid` (Strom-ID); `id` bleibt die Teil-ID des Ereignisses.

    Wie beim Eingang rückt `letzte` auch über Einträge anderer Agenten oder Sitzungen vor; bei `nach == "$"`
    ohne Treffer ist `letzte` die aktuelle Spitze, damit der nächste Abruf nichts verpasst."""
    nach = lese_id(nach)
    warte_ms = int(max(0.0, min(float(warte_s), LESEN_WARTE_MAX_S)) * 1000)
    anzahl = max(1, min(int(anzahl), LESEN_ANZAHL_MAX))
    if nach == "$":
        spitze = r.xrevrange(STROM, count=1)
        nach = spitze[0][0] if spitze else "0"
    antwort = r.xread({STROM: nach}, count=anzahl, block=warte_ms or None)
    eintraege: list[dict[str, Any]] = []
    letzte = nach
    for _name, liste in antwort or []:
        for sid, felder in liste:
            letzte = sid
            if felder.get("a") != agent or (sitzung and felder.get("s") != sitzung):
                continue
            eintraege.append({**felder, "sid": sid})  # `id` ist die Teil-ID des Ereignisses
    return {"eintraege": eintraege, "letzte": letzte}

