"""Alarme im Agenten-Eingang — Alertmanager-Webhook → `fyos:agent:eingang`.

Ein Agenten-Runner kann ohne Modell auf Ereignisse mit `quelle: alarm` und `schwere: hoch` reagieren
(Reflexe). Dieses Modul macht aus einer Alertmanager-Benachrichtigung (Webhook, Format v4) solche
Ereignisse und entprellt sie, damit eine Wiederholung (`repeat_interval`) den Agenten nicht ein zweites
Mal weckt.

Abbildung je Alarm:
    severity critical/page → hoch · error/warning → mittel · info → niedrig
    severity none, Watchdog, InfoInhibitor → übersprungen (Herzschläge des Stacks, kein Alarm)
    text   "<alertname>: <summary>" (+ description, + wo: namespace/pod/instance), ≤ TEXT_MAX
    bezug  "am:<fingerprint>" — derselbe Alarm behält dieselbe Kennung, auch beim Beheben
    von    "alertmanager"

Entprellen (Redis, `MERK_PREFIX<fingerprint>` mit Ablauf `MERK_S`):
    firing   nur, wenn der Alarm noch nicht gemerkt ist oder seine Schwere gestiegen ist
    resolved nur, wenn er vorher eingeworfen wurde — dann als "Behoben: …" mit Schwere niedrig,
             und die Merke fällt weg
Ein Alarm, der länger als `MERK_S` feuert, kommt danach einmal neu — Absicht: der Agent soll
nicht vergessen, dass er noch steht.

Nur Standardbibliothek; die Redis-Verbindung kommt von außen (Plugin `agent`).
"""

from __future__ import annotations

import re
from typing import Any

from . import _agenteneingang as eingang

#: severity-Label (Prometheus-Konvention) → Schwere im Eingang. Fehlt das Label: mittel.
SCHWERE_JE_SEVERITY = {
    "critical": "hoch",
    "page": "hoch",
    "error": "mittel",
    "warning": "mittel",
    "info": "niedrig",
}
#: Gehören zum Stack selbst und feuern immer (kube-prometheus-stack) — nie in den Eingang.
STILL = frozenset({"Watchdog", "InfoInhibitor"})
RANG = {"niedrig": 0, "mittel": 1, "hoch": 2}

MERK_PREFIX = "fyos:agent:alarm:"
#: Wie lange ein eingeworfener Alarm als bekannt gilt (6 h; Alertmanager wiederholt meist alle 4 h).
MERK_S = 6 * 3600
#: Mehr Alarme je Benachrichtigung werden nicht einzeln eingeworfen (ein Sturm ist ein Ereignis).
ALARME_MAX = 20

_FINGERABDRUCK = re.compile(r"[^A-Za-z0-9]")


def _schwere(labels: dict[str, Any]) -> str | None:
    severity = str(labels.get("severity") or "").strip().lower()
    if severity == "none":
        return None
    return SCHWERE_JE_SEVERITY.get(severity, "mittel")


def _wo(labels: dict[str, Any]) -> str:
    teile = []
    for schluessel in ("namespace", "pod", "instance", "node", "job"):
        wert = str(labels.get(schluessel) or "").strip()
        if wert:
            teile.append(f"{schluessel}={wert}")
        if len(teile) == 3:
            break
    return ", ".join(teile)


def _kennung(alarm: dict[str, Any], labels: dict[str, Any]) -> str:
    fingerabdruck = _FINGERABDRUCK.sub("", str(alarm.get("fingerprint") or ""))[:40]
    if not fingerabdruck:  # ältere Alertmanager ohne fingerprint: aus Name und Ort
        fingerabdruck = _FINGERABDRUCK.sub("", f"{labels.get('alertname')}{_wo(labels)}")[:40]
    return fingerabdruck or "unbekannt"


def ereignis(alarm: Any) -> dict[str, Any] | None:
    """Ein Alarm aus dem Webhook → Rohereignis für `_agenteneingang.eintrag` (oder None)."""
    if not isinstance(alarm, dict):
        return None
    labels = alarm.get("labels") if isinstance(alarm.get("labels"), dict) else {}
    hinweise = alarm.get("annotations") if isinstance(alarm.get("annotations"), dict) else {}
    name = str(labels.get("alertname") or "").strip()
    schwere = _schwere(labels)
    if not name or name in STILL or schwere is None:
        return None
    zusammen = str(hinweise.get("summary") or hinweise.get("message") or "").strip()
    text = f"{name}: {zusammen}" if zusammen else name
    beschreibung = str(hinweise.get("description") or "").strip()
    if beschreibung and beschreibung != zusammen:
        text += f"\n{beschreibung}"
    wo = _wo(labels)
    if wo:
        text += f"\n({wo})"
    behoben = str(alarm.get("status") or "firing") == "resolved"
    return {
        "quelle": "alarm",
        "schwere": "niedrig" if behoben else schwere,
        "text": ("Behoben: " + text if behoben else text)[: eingang.TEXT_MAX],
        "bezug": f"am:{_kennung(alarm, labels)}",
        "von": "alertmanager",
        "_behoben": behoben,
        "_schwere_alarm": schwere,
    }


def aus_alertmanager(
    r: Any, nutzlast: Any, jetzt_ms: int, agent: str = eingang.VORGABE_AGENT
) -> dict[str, Any]:
    """Eine Alertmanager-Benachrichtigung einwerfen. Liefert {eingeworfen, uebersprungen}.

    Wirft ValueError, wenn die Nutzlast kein Alertmanager-Webhook ist."""
    if not isinstance(nutzlast, dict) or not isinstance(nutzlast.get("alerts"), list):
        raise ValueError("Alertmanager-Webhook erwartet: {version, status, alerts: […]}")
    alarme = nutzlast["alerts"]
    eingeworfen: list[dict[str, str]] = []
    uebersprungen = 0
    feuernd = [a for a in alarme if isinstance(a, dict) and a.get("status") != "resolved"]
    if len(feuernd) > ALARME_MAX:
        # Sturm: ein Sammelereignis statt zwanzig, mit der höchsten Schwere der Gruppe.
        es = [e for e in (ereignis(a) for a in feuernd) if e]
        if es:
            hoechste = max((e["schwere"] for e in es), key=RANG.__getitem__)
            namen = sorted({e["text"].split(":", 1)[0] for e in es})
            gruppe = _FINGERABDRUCK.sub("", str(nutzlast.get("groupKey") or ""))[-32:] or "sturm"
            roh = {
                "quelle": "alarm",
                "schwere": hoechste,
                "von": "alertmanager",
                "bezug": f"am:gruppe:{gruppe}",
                "text": f"{len(es)} Alarme auf einmal: "
                + ", ".join(namen)[: eingang.TEXT_MAX - 40],
            }
            if _merken(r, f"gruppe:{gruppe}", hoechste):
                eingeworfen.append(
                    {"id": _einwerfen(r, roh, jetzt_ms, f"gruppe:{gruppe}", agent), "bezug": roh["bezug"]}
                )
            else:
                uebersprungen += len(es)
        return {
            "eingeworfen": eingeworfen,
            "uebersprungen": uebersprungen + len(alarme) - len(feuernd),
        }
    for alarm in alarme:
        e = ereignis(alarm)
        if e is None:
            uebersprungen += 1
            continue
        kennung = e["bezug"][3:]
        behoben, schwere = e.pop("_behoben"), e.pop("_schwere_alarm")
        if behoben:
            if r.get(MERK_PREFIX + kennung) is None:
                uebersprungen += (
                    1  # nie eingeworfen (oder schon gemeldet): der Agent braucht kein „behoben“
                )
                continue
            sid = eingang.einwerfen(r, e, jetzt_ms, agent)
            r.delete(MERK_PREFIX + kennung)
        elif _merken(r, kennung, schwere):
            sid = _einwerfen(r, e, jetzt_ms, kennung, agent)
        else:
            uebersprungen += 1
            continue
        eingeworfen.append({"id": sid, "bezug": e["bezug"]})
    return {"eingeworfen": eingeworfen, "uebersprungen": uebersprungen}


def _einwerfen(r: Any, roh: dict[str, Any], jetzt_ms: int, kennung: str, agent: str) -> str:
    """Einwerfen; scheitert es, fällt die frische Merke wieder weg — sonst schluckte die Merke den
    Wiederholversuch von Alertmanager (der bei 5xx erneut sendet)."""
    try:
        return eingang.einwerfen(r, roh, jetzt_ms, agent)
    except Exception:
        r.delete(MERK_PREFIX + kennung)
        raise


def _merken(r: Any, kennung: str, schwere: str) -> bool:
    """True, wenn der Alarm neu ist oder seine Schwere gestiegen ist (dann wird er gemerkt)."""
    schluessel = MERK_PREFIX + kennung
    if r.set(schluessel, schwere, nx=True, ex=MERK_S):
        return True
    alt = r.get(schluessel)
    if isinstance(alt, bytes):
        alt = alt.decode("utf-8", "replace")
    if alt in RANG and RANG[schwere] > RANG[alt]:
        r.set(schluessel, schwere, ex=MERK_S)
        return True
    return False
