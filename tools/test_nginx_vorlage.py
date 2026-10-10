"""nginx-Vorlage der Shell: die Durchreiche zum Agent-Gateway. Laeuft in der CI als Werkzeug-Test (pytest tools).

Drei Fehler machten den Chat im Fenster der Shell unbenutzbar (Testserver, 09.10.2026), keiner faellt beim Bau auf:
das Gateway wies angehaengte Herkunftskoepfe mit 403 `proxy_attribution_required` ab, ohne das Praefix `/agent`
antwortete es 404, und seine Rahmen-Sperre (X-Frame-Options DENY, frame-ancestors 'none') blockierte das Fenster.
`nginx -t` prueft die Vorlage nicht (sie wird erst beim Start des Containers gerendert); diese Tests halten fest,
was die Durchreiche tun muss.
"""
from __future__ import annotations

import re
from pathlib import Path

VORLAGE = Path(__file__).resolve().parent.parent / "web" / "nginx" / "default.conf.template"
TEXT = VORLAGE.read_text(encoding="utf-8")


def _location(kopf: str) -> str:
    """Rumpf der Location mit genau diesem Kopf (ohne verschachtelte Bloecke)."""
    m = re.search(r"^\s*location " + re.escape(kopf) + r" \{\n(.*?)^\s*\}", TEXT, re.M | re.S)
    assert m, f"location {kopf} fehlt"
    return m.group(1)


AGENT = _location(r"~ ^/agent(/|$)")


def _gesetzt(kopf: str) -> str | None:
    m = re.search(r"^\s*proxy_set_header " + re.escape(kopf) + r" (.+);", AGENT, re.M | re.I)
    return m.group(1).strip() if m else None


def test_praefix_bleibt_erhalten():
    # proxy_pass ohne Pfad: /agent/… geht unveraendert ans Gateway (basePath /agent)
    assert re.search(r"^\s*proxy_pass \$\{FYOS_AGENT_UPSTREAM\};", AGENT, re.M)


def test_herkunftskoepfe_werden_gestrichen():
    for kopf in ("Forwarded", "X-Real-IP", "X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host"):
        assert _gesetzt(kopf) == '""', f"{kopf} muss leer gesetzt sein"
    assert "$proxy_add_x_forwarded_for" not in AGENT


def test_websocket_und_host():
    assert _gesetzt("Upgrade") == "$http_upgrade"
    assert _gesetzt("Host") == "$host"


def test_einbettung_nur_im_eigenen_ursprung():
    assert re.search(r"^\s*proxy_hide_header X-Frame-Options;", AGENT, re.M)
    assert re.search(r"^\s*proxy_hide_header Content-Security-Policy;", AGENT, re.M)
    assert re.search(r'^\s*add_header X-Frame-Options "SAMEORIGIN" always;', AGENT, re.M)
    assert re.search(r"^\s*add_header Content-Security-Policy \$fyos_agent_csp always;", AGENT, re.M)
    karte = re.search(r"^map \$upstream_http_content_security_policy \$fyos_agent_csp \{\n(.*?)^\}", TEXT,
                      re.M | re.S)
    assert karte and "frame-ancestors 'none'" in karte.group(1) and "frame-ancestors 'self'" in karte.group(1)


def test_agent_location_steht_vor_den_regex_locations_fuer_dateien():
    # nginx nimmt die erste passende Regex-Location: /agent/….svg darf nicht bei den statischen Dateien landen
    agent = TEXT.index("location ~ ^/agent(/|$)")
    andere = [m.start() for m in re.finditer(r"location ~\*? ", TEXT) if m.start() != agent]
    assert andere, "keine weiteren Regex-Locations gefunden"
    assert all(agent < a for a in andere), "eine Regex-Location steht vor /agent"


def test_nur_fyos_variablen_fuer_envsubst():
    # Das Bild ersetzt nur FYOS_-Variablen (NGINX_ENVSUBST_FILTER); eigene nginx-Variablen duerfen so nicht heissen
    for name in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", TEXT):
        if name.startswith("FYOS_"):
            assert name in ("FYOS_HUB_UPSTREAM", "FYOS_AGENT_UPSTREAM"), name
