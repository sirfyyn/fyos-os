# Nachtarbeit: nachts erledigen, morgens meldet die Shell „erledigt“

Der Agent arbeitet nachts von selbst. Morgens, wenn jemand die Shell öffnet, steht eine Karte da:
„Notizen geordnet“ mit der Uhrzeit, zu der er fertig war („heute Nacht, 03:12“). Dazu gehören drei Teile:

| Teil | Was | Wo |
|---|---|---|
| Auslöser | ein Cron-Auftrag des Agenten (OpenClaw), nachts | [`tools/nachtauftrag.py`](../tools/nachtauftrag.py) |
| Meldung | das Hub-Werkzeug `os.mitteilen`; ist niemand da, wartet die Mitteilung in Redis | [`hub/mcp_hub/plugins/os.py`](../hub/mcp_hub/plugins/os.py), [`hub/mcp_hub/os_bruecke.py`](../hub/mcp_hub/os_bruecke.py) |
| Anzeige | die Shell meldet sich beim Hub, holt ab und zeigt die Karte | [`web/src/lib/os/bruecke.ts`](../web/src/lib/os/bruecke.ts), [`web/src/components/os/Mitteilungen.tsx`](../web/src/components/os/Mitteilungen.tsx) |

## Ablauf

1. Um 03:00 startet der Cron-Auftrag „Nachtauftrag: Notizen ordnen“ in einer eigenen Sitzung des Agenten (kein Chat, keine
   Zustellung an einen Kanal).
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
Das Werkzeug legt den Auftrag als nativen Cron-Auftrag im Agenten an. Wiederholbar: Es trägt einen festen Schlüssel, ein
zweiter Aufruf legt nichts doppelt an. Steht der Auftrag schon da, aber mit einem älteren Auftragstext (etwa aus der Zeit,
als er noch einen Ordner im Workspace las), zieht der Aufruf nur den Text nach (`openclaw cron edit <id> --message …`);
Zeitplan und Id bleiben.

```
python3 tools/nachtauftrag.py                                  # Docker Compose, täglich 03:00
python3 tools/nachtauftrag.py --um 02:30 --zeitzone Europe/Berlin
python3 tools/nachtauftrag.py --in "kubectl -n fyos exec agent-0 --"   # Kubernetes
python3 tools/nachtauftrag.py --trocken                        # nur zeigen, was gerufen würde
python3 tools/nachtauftrag.py --entfernen
```

`--in` ist der Befehl, der ein Programm im Agenten-Container ausführt (Vorgabe `docker compose exec -T agent`). Der
Agent braucht dafür sein Modell (`FYOS_MODELL_*`) und den Hub (`FYOS_HUB_URL`), beides gehört zu seiner normalen
Einrichtung. Der Auftrag erscheint im Hub unter `mcp.zeitplan` (nächster Lauf, letztes Ergebnis).

Eigene Nachtaufträge gehen genauso: `openclaw cron add --cron "0 3 * * *" --session isolated --no-deliver --message "…"`
und am Ende der Aufgabe `os.mitteilen`. Die Anleitung dazu steht im Skill `nachtarbeit` (Teil des Kerns).

## Woher die Notizen kommen

Der Notizzettel (Plugin `beispiel_app`) liegt im Hub, in Redis. Der Nachtauftrag liest ihn mit `beispiel_app.zeigen`
(`hub__call_tool`, `tool: "beispiel_app.zeigen"`); die Antwort hat `anzahl` und `notizen` mit `id`, `text` und `zeit`.
Dasselbe Werkzeug ist für den Agenten sichtbar; `beispiel_app.lesen`, `hinzufuegen` und `loeschen` sind nur für die
Oberfläche da.

Warum nicht ein Notizen-Ordner im Workspace des Agenten (so las der Auftrag zuerst): Eine isolierte Cron-Sitzung des Agenten hat kein Werkzeug, das einen
Ordner auflistet. `read` liest nur Dateien und lehnt ein Verzeichnis mit „… is a directory“ ab, ein Shell-Werkzeug (`exec`)
fand die Suche dort nicht (`tool_search` lieferte nichts), und `dateien.liste` im Hub sieht das Dateivolumen des Hubs, nicht den Workspace des Agenten. Der
Agent kannte also keine Dateinamen, riet sie (eine Sammeldatei, eine README, ein Platzhalter), bekam jeweils „nicht gefunden“ und hielt
den vollen Ordner für leer. Pfad und Arbeitsverzeichnis waren richtig (`/home/node/.openclaw/workspace`, die Dateien
lesbar). Was ein Nachtauftrag verarbeiten soll, gehört darum hinter ein Hub-Werkzeug, das die Daten liefert, nicht in
einen Ordner, den der Agent nur raten könnte. Und ein Auftrag meldet „leer“ nur, wenn das Werkzeug „leer“ gesagt hat.

## Zum Filmen und Ausprobieren: jetzt sofort

```
python3 tools/nachtauftrag.py --jetzt
```

Legt den Auftrag an, falls es ihn noch nicht gibt, lässt ihn einmal laufen und wartet bis zum Ende (einige Minuten, so
lange braucht das Modell). Ist die Shell währenddessen geschlossen, öffnet man sie danach: Die Karte erscheint mit der
Uhrzeit der Entstehung. Zum Filmen der Szene ist das der Weg: Shell schließen oder den Tab im Hintergrund lassen, den
Auftrag mit `--jetzt` laufen lassen, die Shell wieder öffnen.

## Das Werkzeug `os.mitteilen`

```
os.mitteilen {titel, text?, ziel?, eingabe?, dringlichkeit?, quelle?}
```

`titel` (bis 80 Zeichen) und `text` (bis 300) müssen Stunden später ohne Zusammenhang verständlich sein. `ziel`
öffnet beim Klick eine Fläche (Vorgabe: der Chat mit dem Agenten). Die Antwort:

| Antwort | Bedeutung |
|---|---|
| `zugestellt: true` | die Karte steht auf dem Gerät, vor dem jemand sitzt |
| `zugestellt: true`, `weg: "kanal"`, `kanal` | niemand da, aber `dringlichkeit: hoch`: ging sofort über den Agenten in den Chat-Kanal des Besitzers (Telegram, WhatsApp oder Matrix); nichts wartet |
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
  höchstens 6 je 10 Minuten (danach wird vorgemerkt). Er braucht die Kopplung an den Agenten und mindestens einen
  eingerichteten Kanal ([`KOPPLUNG-OPENCLAW.md`](KOPPLUNG-OPENCLAW.md) §3); ohne beides bleibt es beim Vormerken.

## Prüfen

- Hub: `hub/tests/test_os.py` (Vormerken, Obergrenze, Verfall, genau einmal ausliefern) und
  `hub/tests/test_einstiegspunkte.py`.
- Auslöser: `tools/test_nachtauftrag.py`.
- Shell: `web/tests/unit/os-bruecke.test.ts`, `web/tests/unit/os-mitteilung.test.tsx`, `web/tests/unit/os-shell.test.tsx`.
