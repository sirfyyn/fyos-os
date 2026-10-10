"""nginx-Vorlage der Shell: die Durchreichen zum Agent-Gateway und zu den gebauten Ansichten des Hubs. Laeuft in der CI
als Werkzeug-Test (pytest tools).

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


# Gebaute Ansichten (Plugin gui): /hub/gui/<id> und /hub/gui/<id>/daten gehen durch, sonst nichts unter /hub/.
GUI_AUSDRUCK = "^/hub/gui/(?<fyos_gui_id>g-[0-9a-f]{12})(?<fyos_gui_daten>/daten)?$"
GUI_KOPF = f'~ "{GUI_AUSDRUCK}"'
GUI = _location(GUI_KOPF)


def _an_den_hub(pfad: str) -> str | None:
    """Was die Shell dem Hub für einen Pfad schickt (nginx vergleicht den dekodierten, normalisierten Pfad): Location
    und `rewrite` nachgebildet; None, wenn die Location nicht greift. Python schreibt benannte Gruppen (?P<…>)."""
    m = re.search(GUI_AUSDRUCK.replace("(?<", "(?P<"), pfad)
    return f"/hub/gui/{m['fyos_gui_id']}{m['fyos_gui_daten'] or ''}" if m else None


def test_ansichten_nur_lesend_und_umgeschrieben():
    # nur GET (und damit HEAD); dem Hub geht die umgeschriebene Form ohne Abfrageteil zu, nicht die Anfrage, wie sie ankam
    assert re.search(r"^\s*limit_except GET \{ deny all; \}$", GUI, re.M)
    assert re.search(r"^\s*rewrite \^ /hub/gui/\$fyos_gui_id\$fyos_gui_daten\? break;$", GUI, re.M)
    assert re.search(r"^\s*proxy_pass \$\{FYOS_HUB_UPSTREAM\};$", GUI, re.M)


def test_ansichten_dem_hub_geht_nur_die_saubere_form_zu():
    assert _an_den_hub("/hub/gui/g-0123456789ab") == "/hub/gui/g-0123456789ab"
    assert _an_den_hub("/hub/gui/g-0123456789ab/daten") == "/hub/gui/g-0123456789ab/daten"
    # `$` greift in PCRE wie in Python auch vor einem Zeilenumbruch am Ende (%0A im Pfad); weiter geht trotzdem nur
    # die saubere Form
    assert _an_den_hub("/hub/gui/g-0123456789ab\n") == "/hub/gui/g-0123456789ab"
    for pfad in ("/hub/call", "/hub/mehr", "/hub/gui/", "/hub/gui/g-0123456789ab/", "/hub/gui/g-0123456789AB",
                 "/hub/gui/g-0123456789abc", "/hub/gui/g-0123456789ab/daten/x", "/hub/gui/g-0123456789ab/call",
                 "/x/hub/gui/g-0123456789ab", "/hub-api/gui/g-0123456789ab"):
        assert _an_den_hub(pfad) is None, pfad


def test_zum_hub_fuehren_nur_browser_weg_und_ansichten():
    bloecke = re.findall(r"^[ \t]*location (.+?) \{\n([\s\S]*?)^[ \t]*\}", TEXT, re.M)
    zum_hub = [kopf for kopf, rumpf in bloecke if "${FYOS_HUB_UPSTREAM}" in rumpf]
    assert GUI_KOPF in zum_hub
    assert all(k.startswith("= /hub-api/") for k in zum_hub if k != GUI_KOPF), zum_hub
    assert not re.search(r"^\s*location (\^~ |= )?/hub/", TEXT, re.M)  # kein Präfix-Weg auf /hub/


def test_nur_fyos_variablen_fuer_envsubst():
    # Das Bild ersetzt nur FYOS_-Variablen (NGINX_ENVSUBST_FILTER); eigene nginx-Variablen duerfen so nicht heissen
    for name in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", TEXT):
        if name.startswith("FYOS_"):
            assert name in ("FYOS_HUB_UPSTREAM", "FYOS_AGENT_UPSTREAM"), name
