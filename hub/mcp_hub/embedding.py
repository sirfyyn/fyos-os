"""embedding — Texte in Vektoren verwandeln, über jeden OpenAI-kompatiblen Endpunkt (`/v1/embeddings`).

Der Hub bringt kein Modell mit. Wer Vektorsuche (Audit-Recall, Werkzeugsuche) möchte, zeigt auf einen Dienst, der
`POST <basis>/v1/embeddings` mit `{"model": …, "input": …}` versteht (llama.cpp-Server, vLLM, Ollama mit
OpenAI-Pfad, LiteLLM, ein Cloud-Anbieter …):

    FYOS_EMBED_URL     Basisadresse, z. B. http://localhost:8081  (leer = keine Vektoren, Textsuche genügt)
    FYOS_EMBED_MODEL   Modellname, den der Dienst erwartet (Vorgabe: embedding)
    FYOS_EMBED_KEY     Bearer-Schlüssel, falls der Dienst einen verlangt (optional)
    FYOS_EMBED_DOKUMENT_VORSATZ / FYOS_EMBED_ANFRAGE_VORSATZ
                       Texte, die vor ein Dokument bzw. eine Suchanfrage gestellt werden (manche Modelle
                       verlangen z. B. „search_document: “ und „search_query: “). Vorgabe: leer, Text roh.

Fehler sind nie fatal: ohne Dienst oder bei einer Störung liefert `embed` None, und der Aufrufer fällt auf Textsuche
beziehungsweise den Puffer zurück.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MODELL_VORGABE = "embedding"


@dataclass(frozen=True)
class Ziel:
    """Sammlung (Qdrant) und Modell, mit denen gerade gelesen und geschrieben wird."""

    sammlung: str
    modell: str = MODELL_VORGABE

    @property
    def eg2(self) -> bool:  # Altname: es gibt nur noch ein Modell je Installation
        return False


def embed_url() -> str:
    return (os.getenv("FYOS_EMBED_URL") or "").strip().rstrip("/")


def embed_modell() -> str:
    return (os.getenv("FYOS_EMBED_MODEL") or MODELL_VORGABE).strip()


def vorbereiten(text: str, art: str = "dokument") -> str:
    """Text für das Modell: optionaler Vorsatz je Art (`dokument` oder `anfrage`)."""
    schluessel = "FYOS_EMBED_ANFRAGE_VORSATZ" if art == "anfrage" else "FYOS_EMBED_DOKUMENT_VORSATZ"
    return (os.getenv(schluessel) or "") + text


def embed(
    text: str,
    basis: Optional[str] = None,
    modell: Optional[str] = None,
    art: str = "dokument",
    timeout: float = 5.0,
) -> Optional[list[float]]:
    """Vektor zu `text`, oder None (kein Dienst eingerichtet, Fehler, unerwartete Antwort)."""
    basis = (basis if basis is not None else embed_url()).rstrip("/")
    if not basis:
        return None
    if not basis.lower().startswith(("http://", "https://")):
        return None
    kopf = {"content-type": "application/json"}
    schluessel = os.getenv("FYOS_EMBED_KEY") or ""
    if schluessel:
        kopf["authorization"] = f"Bearer {schluessel}"
    koerper = json.dumps({"model": modell or embed_modell(), "input": vorbereiten(text, art)}).encode()
    anfrage = urllib.request.Request(f"{basis}/v1/embeddings", data=koerper, headers=kopf, method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as r:  # noqa: S310 -- Adresse aus der Konfiguration
            daten = json.loads(r.read().decode())
        vektor = (daten.get("data") or [{}])[0].get("embedding")
        if not isinstance(vektor, list):
            return None
        return [float(x) for x in vektor]
    except Exception as exc:  # noqa: BLE001 -- nie fatal
        logger.debug("embedding: %s", exc)
        return None
