"""TLS-Kontext für die HTTP-Aufrufe ans Gateway des Agenten (und an den Vorgangs-Dienst).

Vorgabe: prüfen, mit den System-Zertifikaten. Zwei Stellschrauben für interne Netze mit selbstsigniertem
Zertifikat (Konfigschlüssel in Klammern, die Konfiguration gewinnt vor der Umgebung):

    FYOS_AGENT_CA              Pfad zu einer CA- oder Zertifikatsdatei (PEM), wird zu den System-Zertifikaten
                               hinzugefügt (``agent_ca``); die Prüfung bleibt an, auch Name und Laufzeit
    FYOS_AGENT_TLS_PRUEFEN     ``false`` schaltet die Prüfung ab (``agent_tls_pruefen``), nur für interne Netze

Ist beides gesetzt, gilt die CA (es wird geprüft). Nur für ``https://``-Adressen; bei ``http://`` ändert sich nichts.
"""

from __future__ import annotations

import os
import ssl
from typing import Any

_AUS = {"0", "false", "no", "nein", "off", "aus"}


def pruefen_aus_text(wert: Any, vorgabe: bool = True) -> bool:
    if isinstance(wert, bool):
        return wert
    text = str(wert if wert is not None else "").strip().lower()
    if not text:
        return vorgabe
    return text not in _AUS


def kontext(ca: str | None = None, pruefen: Any = None) -> ssl.SSLContext | None:
    """``None`` heißt: Vorgabe von urllib (prüfen mit System-Zertifikaten). Fehler in der CA-Datei fallen auf, statt still
    ungeprüft zu verbinden (``FileNotFoundError``/``ssl.SSLError``)."""
    ca = (ca if ca is not None else os.getenv("FYOS_AGENT_CA", "")).strip()
    if pruefen is None:
        pruefen = os.getenv("FYOS_AGENT_TLS_PRUEFEN", "")
    if ca:
        return ssl.create_default_context(cafile=ca)
    if not pruefen_aus_text(pruefen):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None
