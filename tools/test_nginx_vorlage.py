"""nginx-Vorlage der Shell: die Durchreichen zum Agenten (Runner unter /api/agent/) und zu den gebauten Ansichten des
Hubs. Laeuft in der CI als Werkzeug-Test (pytest tools).

`nginx -t` prueft die Vorlage nicht (sie wird erst beim Start des Containers gerendert); diese Tests halten fest,
was die Durchreichen tun muessen. Seit 0.2.1 gibt es keinen Weg /agent mehr (der alte Agent ist entfernt).
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


def test_kein_weg_agent_mehr():
    # 0.2.1: das Gateway des alten Agenten unter /agent ist entfernt; nur /api/agent/ fuehrt zum Agenten (Runner)
    assert not re.search(r"^\s*location [^\n]*/agent\(", TEXT, re.M)
    assert not re.search(r"^\s*location [~=^ ]*/agent[ /]", TEXT, re.M)
    assert "18789" not in TEXT and "gateway" not in TEXT.lower()
    assert "fyos_agent_csp" not in TEXT


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


def test_dateien_nur_get_und_put_ohne_puffer():
    # Hoch- und Herunterladen einer Datei: genau dieser Weg, nur GET und PUT, der Körper wird durchgereicht statt
    # zwischengespeichert; die Größe begrenzt der Hub (FYOS_DATEIEN_MAX_MB), nicht eine zweite, stille Grenze im nginx
    d = _location("= /hub-api/dateien/datei")
    assert re.search(r"^\s*limit_except GET PUT \{ deny all; \}$", d, re.M)
    assert re.search(r"^\s*proxy_pass \$\{FYOS_HUB_UPSTREAM\}/hub/dateien/datei\$is_args\$args;$", d, re.M)
    assert re.search(r"^\s*proxy_request_buffering off;$", d, re.M)
    assert re.search(r"^\s*client_max_body_size 0;$", d, re.M)
    assert TEXT.index("location = /hub-api/dateien/datei") < TEXT.index("location ^~ /hub-api/ { return 404; }")


def test_nur_fyos_variablen_fuer_envsubst():
    # Das Bild ersetzt nur FYOS_-Variablen (NGINX_ENVSUBST_FILTER); eigene nginx-Variablen duerfen so nicht heissen
    for name in re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", TEXT):
        if name.startswith("FYOS_"):
            assert name in ("FYOS_HUB_UPSTREAM", "FYOS_AGENT_UPSTREAM", "FYOS_AGENT_TOKEN"), name


def test_fehlender_agent_haelt_die_shell_nicht_auf():
    # Trockenlauf 0.2.0: ohne einen Dienst brach nginx mit „host not found in upstream“ ab. Der Agent wird deshalb je
    # Anfrage aufgelöst, mit dem Resolver des Bilds.
    assert re.search(r"^\s*resolver \$\{NGINX_LOCAL_RESOLVERS\} valid=10s ipv6=off;$", TEXT, re.M)
    assert "NGINX_ENVSUBST_FILTER=FYOS_|NGINX_LOCAL_RESOLVERS" in (VORLAGE.parent.parent / "Dockerfile").read_text()
    assert not re.search(r"^\s*proxy_pass \$\{FYOS_AGENT_UPSTREAM", TEXT, re.M)


def test_runner_unter_api_agent():
    # Seit 0.2.0: die native Agent-App spricht den Runner über /api/agent/…; das Präfix fällt weg, nginx meldet sich an,
    # die Anmeldung des Browsers kommt nicht durch, SSE ohne Puffer.
    r = _location("^~ /api/agent/")
    assert re.search(r"^\s*set \$fyos_agent \$\{FYOS_AGENT_UPSTREAM\};$", r, re.M)
    assert re.search(r"^\s*rewrite \^/api/agent/\(\.\*\)\$ /\$1 break;$", r, re.M)
    assert re.search(r"^\s*proxy_pass \$fyos_agent;$", r, re.M)
    assert re.search(r'^\s*proxy_set_header Authorization "Bearer \$\{FYOS_AGENT_TOKEN\}";$', r, re.M)
    assert re.search(r"^\s*proxy_set_header Cookie \"\";$", r, re.M)
    assert re.search(r"^\s*proxy_buffering off;$", r, re.M)
