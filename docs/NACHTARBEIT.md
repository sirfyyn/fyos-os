# Nachtarbeit: nachts erledigen, morgens meldet die Shell „erledigt“

Der Agent arbeitet nachts von selbst. Morgens, wenn jemand die Shell öffnet, steht eine Karte da:
„Notizen geordnet“ mit der Uhrzeit, zu der er fertig war („heute Nacht, 03:12“). Dazu gehören drei Teile:

| Teil | Was | Wo |
|---|---|---|
| Auslöser | ein Takt des Agenten (Runner, `takt.eintraege` in `agent-runner.json`), nachts | `agent-runner.json` (fyos-agent/runner/README.md) |
| Meldung | das Hub-Werkzeug `os.mitteilen`; ist niemand da, wartet die Mitteilung in Redis | [`hub/mcp_hub/plugins/os.py`](../hub/mcp_hub/plugins/os.py), [`hub/mcp_hub/os_bruecke.py`](../hub/mcp_hub/os_bruecke.py) |
| Anzeige | die Shell meldet sich beim Hub, holt ab und zeigt die Karte | [`web/src/lib/os/bruecke.ts`](../web/src/lib/os/bruecke.ts), [`web/src/components/os/Mitteilungen.tsx`](../web/src/components/os/Mitteilungen.tsx) |

## Ablauf

1. Um 03:00 weckt ein Takt des Runners den Agenten mit dem Auftrag „Notizen ordnen“ (kein Chat, keine Zustellung an
   einen Kanal).
2. Der Agent liest den Notizzettel über das Hub-Werkzeug `beispiel_app.zeigen` (nicht aus Dateien im Workspace, siehe
   unten „Woher die Notizen kommen“), fasst die Notizen zusammen und ruft zum Schluss genau einmal `os.mitteilen` im Hub.
   „Keine neuen Notizen“ meldet er nur bei leerem Notizzettel; scheitert das Lesen, meldet er „Notizzettel nicht
   erreichbar“.
3. Sitzt jemand vor einer offenen Shell (sichtbar, in den letzten 10 Minuten benutzt), erscheint die Karte sofort.
   Sonst antwortet das Werkzeug `vorgemerkt: true`: Die Mitteilung liegt in Redis (Liste `fyos:os:ausstehend`, höchstens
   20, 24 Stunden).
4. Die Shell meldet sich als Sitzung der OS-Brücke, alle 5 Sekunden im sichtbaren Tab. Die erste Meldung nach dem Öffnen
   liefert die vorgemerkten Mitteilungen aus, älteste zuerst, jede genau einmal, ohne Ton. Die Karte trägt die Uhrzeit der
   Entstehung und bleibt 30 Sekunden stehen (eine gewöhnliche 10).

Nachts weckt nichts jemanden: Vorgemerktes spielt weder Hinweiston noch Stimme.

## Einrichten

Ein Nachtauftrag ist eine Entscheidung des Besitzers; der Agent legt sich keine Zeitpläne an, und der Hub startet keine.
Der Auslöser ist ein eigener Takt des Runners in `agent-runner.json` (die Vorlage des Installers schaltet den
eingebauten Tagesrhythmus mit `"takt": {"an": false}` aus):

```json
"takt": {
  "an": true,
  "zone": "Europe/Berlin",
  "eintraege": [
    {"id": "nacht-notizen", "um": "03:00", "fenster_min": 120, "schleife": "arbeit", "art": "melden",
     "text": "Nachtauftrag Notizen: Lies den Notizzettel mit beispiel_app.zeigen, fasse ihn zusammen und melde mit os.mitteilen (quelle Nacht, dringlichkeit niedrig)."}
  ]
}
```

Eigene Einträge ersetzen den eingebauten Rhythmus (`takt.mit_standard: true` nimmt ihn dazu); nach der Änderung den
Agenten neu starten (`docker compose restart agent`). Der Runner weckt nur, wenn das Tor seiner Schleife offen ist
(Hub-Werkzeug `schleifen.darf`); ein Hub ohne dieses Werkzeug hält das Tor zu, der Takt verfällt dann still. Am Ende der
Aufgabe steht `os.mitteilen`. Die Anleitung für den Agenten steht im Skill `nachtarbeit` (Teil des Kerns).

## Woher die Notizen kommen

Der Notizzettel (Plugin `beispiel_app`) liegt im Hub, in Redis. Der Nachtauftrag liest ihn mit `beispiel_app.zeigen`
(`hub__call_tool`, `tool: "beispiel_app.zeigen"`); die Antwort hat `anzahl` und `notizen` mit `id`, `text` und `zeit`.
Dasselbe Werkzeug ist für den Agenten sichtbar; `beispiel_app.lesen`, `hinzufuegen` und `loeschen` sind nur für die
Oberfläche da.

Was ein Nachtauftrag verarbeiten soll, gehört hinter ein Hub-Werkzeug, das die Daten liefert, nicht in einen Ordner,
dessen Dateinamen der Agent nur raten könnte. Und ein Auftrag meldet „leer“ nur, wenn das Werkzeug „leer“ gesagt hat.

## Das Werkzeug `os.mitteilen`

```
os.mitteilen {titel, text?, ziel?, eingabe?, dringlichkeit?, quelle?}
```

`titel` (bis 80 Zeichen) und `text` (bis 300) müssen Stunden später ohne Zusammenhang verständlich sein. `ziel`
öffnet beim Klick eine Fläche (Vorgabe: der Chat mit dem Agenten). Die Antwort:

| Antwort | Bedeutung |
|---|---|
| `zugestellt: true` | die Karte steht auf dem Gerät, vor dem jemand sitzt |
| `zugestellt: true`, `weg: "kanal"`, `kanal` | niemand da, aber `dringlichkeit: hoch`: ging sofort über einen angemeldeten Chat-Weg (`os_bruecke.kanal_anmelden`); nichts wartet |
| `vorgemerkt: true`, `rueckfall: "vorgemerkt"` | niemand da; die Mitteilung wartet bis zu 24 Stunden |
| `kanal_fehler` (mit `vorgemerkt`) | dringend, aber der Chat-Weg ging nicht (`zu_viele`, `nicht_zugestellt`); sie wartet auf die Shell |
| `grund: "doppelt"` | dieselbe Mitteilung steht schon da oder wartet schon |
| `rueckfall: "gebuendelt"` | mehr als 6 in 10 Minuten; zusammenfassen |
| `rueckfall: "kanal"` | niemand da und Nachholen ist aus; einen anderen Weg nehmen |

Die Werkzeuge `os.lage`, `os.zeigen` und `os.ausfuehren` gehören zum selben Plugin (siehe
[`HUB-VERTRAG.md`](HUB-VERTRAG.md) §3 für das Protokoll).

## Einstellungen

| Einstellung | Wirkung |
|---|---|
| `REDIS_URL` | nötig; ohne Redis keine Sitzungen und nichts, was warten kann (`os.lage` meldet `redis`) |
| `OS_NACHHOLEN=aus` oder Plugin-Config `nachholen: false` | Mitteilungen nicht vormerken; `os.mitteilen` antwortet dann `rueckfall: "kanal"` |
| `OS_KANAL=aus` oder Plugin-Config `kanal: false` | Dringendes (`hoch`) geht ohne Gerät nicht in den Chat, sondern wird wie alles andere vorgemerkt |
| `OS_AGENT_AUFRUFER` | Namen, die als Agent gelten (Vorgabe `agent*`) |
| Mitteilungen „stumm“ / „aus“ in der Shell | die Karte erscheint dann nicht; vorgemerkt ist sie trotzdem ausgeliefert und damit verbraucht |

## Grenzen

- Höchstens 20 Mitteilungen warten, die ältesten fallen heraus; nach 24 Stunden verfällt jede. Die Shell zeigt höchstens
  drei Karten übereinander (die neuesten). Wer mehr zu melden hat, fasst zusammen.
- Die Shell muss einmal geöffnet werden: Erst eine Sitzung mit einer Meldung holt Vorgemerktes ab. Eine native App ohne
  Strom meldet mit `abholen: true` und bekommt es in der Antwort, so wie die Shell.
- Die Uhrzeit auf der Karte ist die Ortszeit des Geräts.
- Der Chat-Weg ist für Dringendes da, nicht zum Ablegen: dieselbe Mitteilung höchstens einmal je 10 Minuten, insgesamt
  höchstens 6 je 10 Minuten (danach wird vorgemerkt). Er braucht ein Plugin, das einen Chat-Weg anmeldet
  (`kanal_anmelden`); die Distribution bringt keines mit, dann bleibt es beim Vormerken. Matrix als Meldeweg für
  Freigaben richtet der Runner selbst ein (`pi_durable.freigabe_meldung.kanaele` in `agent-runner.json`).

## Prüfen

- Hub: `hub/tests/test_os.py` (Vormerken, Obergrenze, Verfall, genau einmal ausliefern) und
  `hub/tests/test_einstiegspunkte.py`.
- Shell: `web/tests/unit/os-bruecke.test.ts`, `web/tests/unit/os-mitteilung.test.tsx`, `web/tests/unit/os-shell.test.tsx`.
