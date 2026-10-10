"""Vorgänge ↔ Workboard-Karten: Abbildung und Abgleichsplan (reine Logik, ohne Netz).

Zwei Betriebsarten (docs/KOPPLUNG-OPENCLAW.md):

* **Spiegel**: Es gibt einen Vorgangs-Dienst (``FYOS_VORGAENGE_URL``). Er ist die Wahrheit; das Workboard zeigt seine
  offenen Vorgänge als Karten auf einem eigenen Board ohne Automation. Änderungen an einer Karte in OpenClaw gehen
  zurück in den Vorgang, mit zwei Riegeln: eine Freigabe (Karte verlässt ``review``) entscheidet nie das Workboard,
  sondern der Freigabeweg; und ``closed`` setzt nur der Vorgangs-Dienst.
* **Ablage**: Ohne Vorgangs-Dienst ist das Workboard selbst die Ablage. Der Hub bietet denselben Vorgangs-Vertrag
  (``GET/POST /tickets``, ``POST /tickets/{id}/comments``, ``PATCH /tickets/{id}``) auf Basis der Karten an.

Status: Karten kennen ``triage backlog todo scheduled ready running review blocked done``, Vorgänge
``new triage in_progress waiting_approval resolved closed``. Jeder Vorgangs-Status hat eine Klasse von Karten-Status,
die ihm entsprechen; nur ein Status außerhalb der Klasse ist eine Abweichung. ``ready`` setzt der Abgleich nie: das
ist der Status, den ein Dispatch-Durchgang des Workboards abholt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KARTEN_STATUS = ("triage", "backlog", "todo", "scheduled", "ready", "running", "review", "blocked", "done")
VORGANG_STATUS = ("new", "triage", "in_progress", "waiting_approval", "resolved", "closed")
OFFEN = ("new", "triage", "in_progress", "waiting_approval")
PRIORITAETEN = ("low", "normal", "high", "urgent")

#: Karten-Status, die einem Vorgangs-Status entsprechen.
KLASSE: dict[str, frozenset[str]] = {
    "new": frozenset({"triage"}),
    "triage": frozenset({"triage", "backlog", "todo", "scheduled", "ready"}),
    "in_progress": frozenset({"running", "blocked"}),
    "waiting_approval": frozenset({"review"}),
    "resolved": frozenset({"done"}),
    "closed": frozenset({"done"}),
}
#: Karten-Status, den der Abgleich für einen Vorgangs-Status setzt.
KARTE_FUER: dict[str, str] = {
    "new": "triage",
    "triage": "backlog",
    "in_progress": "running",
    "waiting_approval": "review",
    "resolved": "done",
    "closed": "done",
}
#: Vorgangs-Status einer Karte in der Ablage (Lesen).
VORGANG_FUER: dict[str, str] = {
    "triage": "new",
    "backlog": "triage",
    "todo": "triage",
    "scheduled": "triage",
    "ready": "triage",
    "running": "in_progress",
    "blocked": "in_progress",
    "review": "waiting_approval",
    "done": "resolved",
}
#: Ziel im Vorgang, wenn jemand in OpenClaw eine gespiegelte Karte verschiebt (nie ``closed``, nie ``new``).
RUECKWEG: dict[str, str] = {
    "triage": "triage",
    "backlog": "triage",
    "todo": "triage",
    "scheduled": "triage",
    "ready": "triage",
    "running": "in_progress",
    "blocked": "in_progress",
    "review": "waiting_approval",
    "done": "resolved",
}

LABEL_PRAEFIX = "vorgang:"
MANDANT = "fyos"
TITEL_MAX = 180
NOTIZ_MAX = 4000
LABEL_MAX = 40
_ID_FORM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,30}$")


def vorgang_id_der_karte(karte: dict[str, Any]) -> str | None:
    for label in karte.get("labels") or []:
        if isinstance(label, str) and label.startswith(LABEL_PRAEFIX):
            return label[len(LABEL_PRAEFIX):] or None
    return None


def prioritaet(wert: Any) -> str:
    """Priorität eines Vorgangs (frei: p1, P2, critical, hoch …) als Karten-Priorität."""
    w = str(wert or "").strip().lower()
    if not w:
        return "normal"
    if w in PRIORITAETEN:
        return w
    if w in ("p1", "1", "critical", "kritisch", "urgent", "dringend", "sev1", "blocker"):
        return "urgent"
    if w in ("p2", "2", "high", "hoch", "major", "sev2"):
        return "high"
    if w in ("p4", "4", "5", "p5", "low", "niedrig", "minor", "trivial"):
        return "low"
    return "normal"


def typ(vorgang: dict[str, Any]) -> str:
    roh = vorgang.get("type") or vorgang.get("typ") or str(vorgang.get("id") or "").split("-", 1)[0]
    return re.sub(r"[^a-z0-9]", "", str(roh).lower())[:12] or "vorgang"


def _kurz(text: Any, grenze: int) -> str:
    t = str(text or "")
    return t if len(t) <= grenze else t[: grenze - 1] + "…"


def titel(vorgang: dict[str, Any]) -> str:
    return _kurz(f"[{vorgang.get('id')}] {' '.join(str(vorgang.get('title') or '').split())}".strip(), TITEL_MAX)


def notizen(vorgang: dict[str, Any], link: str = "") -> str:
    teile = [str(vorgang.get("description") or "").strip()]
    if vorgang.get("waiting_for"):
        teile.append(f"Wartet auf: {vorgang['waiting_for']}")
    fuss = f"FYOS-Vorgang {vorgang.get('id')} (Status {vorgang.get('status')})"
    teile.append(f"{fuss}: {link}" if link else fuss)
    return _kurz("\n\n".join(t for t in teile if t), NOTIZ_MAX)


def link(vorlage: str, vorgang_id: str) -> str:
    return vorlage.replace("{id}", vorgang_id) if vorlage and "{id}" in vorlage else ""


def karte_anlegen(vorgang: dict[str, Any], board: str, link_vorlage: str = "") -> dict[str, Any]:
    """Parameter für ``workboard.cards.create`` (gleicher Idempotenzschlüssel = keine Doppelkarte)."""
    vid = str(vorgang["id"])
    verweis = link(link_vorlage, vid)
    p: dict[str, Any] = {
        "title": titel(vorgang),
        "notes": notizen(vorgang, verweis),
        "status": KARTE_FUER.get(str(vorgang.get("status")), "backlog"),
        "priority": prioritaet(vorgang.get("priority")),
        "labels": [_kurz(f"{LABEL_PRAEFIX}{vid}", LABEL_MAX), _kurz(f"typ:{typ(vorgang)}", LABEL_MAX)],
        "boardId": board,
        "tenant": MANDANT,
        "idempotencyKey": f"{LABEL_PRAEFIX}{vid}",
    }
    if verweis:
        p["sourceUrl"] = verweis
    return p


@dataclass
class Schritt:
    """Ein Schritt des Abgleichs. ``art``: anlegen | aendern | verschieben | zurueck | kommentar."""

    art: str
    vorgang: str
    karte: str | None = None
    daten: dict[str, Any] = field(default_factory=dict)
    grund: str = ""


def plan(
    vorgaenge: dict[str, dict[str, Any]],
    karten: list[dict[str, Any]],
    stand: dict[str, dict[str, Any]],
    board: str,
    link_vorlage: str = "",
    erledigt: dict[str, str] | None = None,
) -> list[Schritt]:
    """Schritte, die Workboard und Vorgangs-Dienst angleichen.

    vorgaenge  offene Vorgänge des Dienstes, nach ID
    karten     Karten des Spiegel-Boards (``workboard.cards.list``)
    stand      je Karten-ID der zuletzt gesehene Stand ``{"u": updatedAt, "s": status, "e": updatedAt eigener Schreibung}``
    erledigt   Status von Vorgängen, die nicht mehr offen sind (nachgeschlagen), nach ID
    """
    schritte: list[Schritt] = []
    erledigt = erledigt or {}
    nach_vorgang: dict[str, dict[str, Any]] = {}
    for k in karten:
        vid = vorgang_id_der_karte(k)
        if vid and vid not in nach_vorgang:
            nach_vorgang[vid] = k

    for vid, v in sorted(vorgaenge.items()):
        if not _ID_FORM.match(vid):
            continue
        status = str(v.get("status") or "")
        k = nach_vorgang.get(vid)
        if k is None:
            schritte.append(Schritt("anlegen", vid, daten=karte_anlegen(v, board, link_vorlage)))
            continue
        kid = str(k.get("id"))
        ks = str(k.get("status") or "")
        alt = stand.get(kid) or {}
        fremd = bool(alt) and k.get("updatedAt") not in (alt.get("u"), alt.get("e"))
        klasse = KLASSE.get(status, frozenset())
        if ks not in klasse:
            if fremd and alt.get("s") == "review" and status == "waiting_approval":
                # Riegel: eine Freigabe entscheidet der Freigabeweg, nicht das Verschieben einer Karte.
                schritte.append(Schritt("kommentar", vid, kid, {"text": (
                    f"In OpenClaw wurde die Karte von „review“ nach „{ks}“ verschoben. Die Freigabe bleibt offen; "
                    "entscheiden geht über den Freigabeweg (Chat oder Vorgang).")}, "riegel_freigabe"))
                schritte.append(Schritt("verschieben", vid, kid, {"status": KARTE_FUER[status]}, "riegel_freigabe"))
            elif fremd and ks in RUECKWEG and RUECKWEG[ks] != status:
                schritte.append(Schritt("zurueck", vid, kid, {"status": RUECKWEG[ks], "erwartet": status,
                                                              "von": alt.get("s"), "nach": ks}, "openclaw"))
            elif status in KARTE_FUER:
                schritte.append(Schritt("verschieben", vid, kid, {"status": KARTE_FUER[status]}, "vorgang"))
        aenderung: dict[str, Any] = {}
        if str(k.get("title") or "") != titel(v):
            aenderung["title"] = titel(v)
        if prioritaet(v.get("priority")) != str(k.get("priority") or "normal"):
            aenderung["priority"] = prioritaet(v.get("priority"))
        soll_notizen = notizen(v, link(link_vorlage, vid))
        if str(k.get("notes") or "") != soll_notizen:
            aenderung["notes"] = soll_notizen
        if aenderung:
            schritte.append(Schritt("aendern", vid, kid, aenderung, "vorgang"))

    for vid, k in sorted(nach_vorgang.items()):
        if vid in vorgaenge:
            continue
        if str(k.get("status") or "") != "done" and erledigt.get(vid) in ("resolved", "closed", "unbekannt"):
            schritte.append(Schritt("verschieben", vid, str(k.get("id")), {"status": "done"}, "erledigt"))
    return schritte


# ── Ablage: Karten als Vorgänge ─────────────────────────────────────────────────────────────────

ABLAGE_PRAEFIX = "WB-"


def ablage_id(karte: dict[str, Any]) -> str:
    """Kurze, im Chat schreibbare ID einer Karte: ``WB-`` und die ersten acht Zeichen der Karten-UUID."""
    return ABLAGE_PRAEFIX + str(karte.get("id") or "").replace("-", "")[:8].lower()


def vorgang_aus_karte(karte: dict[str, Any]) -> dict[str, Any]:
    """Eine Karte in der Form des Vorgangs-Vertrags (für ``/hub/vorgaenge``)."""
    meta = karte.get("metadata") if isinstance(karte.get("metadata"), dict) else {}
    status = VORGANG_FUER.get(str(karte.get("status") or ""), "triage")
    if meta.get("archivedAt"):
        status = "closed"
    return {
        "id": vorgang_id_der_karte(karte) or ablage_id(karte),
        "karte": karte.get("id"),
        "title": karte.get("title") or "",
        "description": karte.get("notes") or "",
        "status": status,
        "karten_status": karte.get("status"),
        "priority": karte.get("priority") or "normal",
        "labels": list(karte.get("labels") or []),
        "source_url": karte.get("sourceUrl") or "",
        "created_at": karte.get("createdAt"),
        "updated_at": karte.get("updatedAt"),
        "waiting_for": "",
        "quelle": "workboard",
    }


_AKTEUR_TEXT = re.compile(r"^([\w.@-]{1,40}): (.+)$", re.DOTALL)


def verlauf_aus_karte(karte: dict[str, Any], grenze: int = 20) -> list[dict[str, Any]]:
    """Die Kommentare einer Karte als Verlauf des Vertrags, neueste zuerst. ``akteur: text`` (so schreibt der Hub)
    wird zu ``actor`` und ``detail``."""
    meta = karte.get("metadata") if isinstance(karte.get("metadata"), dict) else {}
    kommentare = [c for c in meta.get("comments") or [] if isinstance(c, dict)]
    eintraege = []
    for c in reversed(kommentare):  # das Workboard hängt neue Kommentare hinten an
        body = str(c.get("body") or "")
        treffer = _AKTEUR_TEXT.match(body)
        akteur, text = (treffer.group(1), treffer.group(2)) if treffer else (str(c.get("author") or ""), body)
        eintraege.append({"ts": c.get("createdAt"), "event": "comment", "actor": akteur, "detail": text,
                          "id": c.get("id")})
    return eintraege[:max(0, grenze)]


def karte_zur_id(karten: list[dict[str, Any]], vorgang_id: str) -> dict[str, Any] | None:
    vid = str(vorgang_id or "").strip()
    if not vid:
        return None
    for k in karten:
        if vid in (str(k.get("id")), vorgang_id_der_karte(k), ablage_id(k)):
            return k
    return None
