---
name: nachtarbeit
description: Wenn Arbeit nachts oder sonst ohne den Benutzer laufen soll und er das Ergebnis später in der Shell sehen will (Cron-Auftrag, Nachtlauf, "mach das über Nacht", "melde dich, wenn du fertig bist"). Wie ein Nachtauftrag entsteht, wie du in einem Lauf ohne Benutzer arbeitest und wie du mit os.mitteilen meldest, auch wenn niemand da ist.
ausloeser: nachts, über nacht, nachtauftrag, nachtlauf, cron, zeitplan, morgens melden, erledigt melden, os.mitteilen, mitteilung, vorgemerkt, notizen ordnen
fuer: [agent]
---

# Nachtarbeit: nachts erledigen, morgens melden

Ein Nachtauftrag ist Arbeit, die ohne den Benutzer läuft und deren Ergebnis er später sieht. Er besteht aus zwei Teilen:
dem **Cron-Auftrag** (wann und was) und der **Mitteilung** am Ende (os.mitteilen).

## 1. Wie ein Nachtauftrag entsteht

Nichts erfindet Arbeit: Der Heartbeat ist aus, und du legst **keinen Zeitplan für dich selbst** an. Ein Nachtauftrag ist die
Entscheidung des Besitzers. Er legt ihn mit dem Werkzeug des Repos an:

```
python3 tools/nachtauftrag.py                  # Compose: täglich 03:00, Beispiel „Notizen ordnen“
python3 tools/nachtauftrag.py --jetzt          # dazu sofort einmal laufen lassen
python3 tools/nachtauftrag.py --in "kubectl -n fyos exec agent-0 --" --um 02:30     # Kubernetes
```

Das ist `openclaw cron add` im Agenten-Container (Sitzung `isolated`, fester Schlüssel, wiederholbar). Eigene Aufträge
gehen genauso: `openclaw cron add --cron "0 3 * * *" --session isolated --no-deliver --message "…"`. Sag dem Benutzer
den Befehl und frag, wann er laufen soll; leg ihn nicht selbst an. Der Auftrag erscheint in `mcp.zeitplan`.

## 2. Wie du im Nachtlauf arbeitest

- **Niemand antwortet.** Frag nichts zurück. Fehlt etwas, entscheide das Kleine selbst (Kleines selbst, Schweres fragt der
  Mensch) und tu das Schwere nicht; schreib stattdessen in die Mitteilung, was liegen blieb.
- **Kein Chat, kein Kanal.** Die Ruhezeit gilt (22:00 bis 07:00): nachts geht keine proaktive Chatnachricht hinaus. Gemeldet
  wird nur über `os.mitteilen`.
- **Daten aus dem Hub, nicht aus Ordnern.** In einer isolierten Cron-Sitzung kannst du keinen Ordner auflisten (`read` liest
  nur Dateien). Wer Dateinamen rät, bekommt „nicht gefunden“ und hält einen vollen Ordner für leer. Hol die Daten über ein
  Hub-Werkzeug (die Notizen: `beispiel_app.zeigen`) und melde „leer“ nur, wenn das Werkzeug „leer“ sagt; scheitert der
  Aufruf, melde den Fehler.
- **Genau eine Mitteilung am Ende** (bei vielen Teilaufgaben eine je Ergebnis, nie eine je Zwischenschritt).

## 3. Die Mitteilung

```
os.mitteilen {titel, text?, ziel?, eingabe?, dringlichkeit?, quelle?}
```

- `titel` (≤ 80 Zeichen) und `text` (≤ 300) müssen **Stunden später ohne Kontext** verständlich sein: nicht „Fertig“,
  sondern „Notizen geordnet: 12 Notizen, 3 Themen, 2 offen“.
- `quelle: "Nacht"`, `dringlichkeit: "niedrig"` (nachts nie Ton, auch später nicht). `hoch` nur, wenn der Benutzer
  geweckt werden darf; die Ruhezeit schützt ihn nicht, wenn du es setzt.
- `ziel` öffnet beim Klick eine Fläche, z. B. die App mit dem Ergebnis (`app:meine_app__zeigen`, `eingabe` dazu).
  Ohne `ziel` öffnet die Karte den Chat mit dir.

Die Antwort sagt, was geschah:

| Antwort | Bedeutung | Was du tust |
|---|---|---|
| `zugestellt: true` | jemand sitzt vor der Shell, die Karte steht da | nichts |
| `zugestellt: false`, `vorgemerkt: true` | niemand da; die Mitteilung **wartet bis zu 24 h** und erscheint ohne Ton mit der Uhrzeit der Entstehung („heute Nacht, 03:12“), sobald die Shell geöffnet wird | nichts, das ist der Normalfall nachts |
| `zugestellt: true`, `weg: kanal` | niemand an der Shell, aber `dringlichkeit: hoch`: ging sofort in den Chat des Benutzers | nichts; `hoch` nur für Dringendes (etwas ist kaputt, eine Frist läuft ab) |
| `kanal_fehler` | dringend, der Chat-Weg ging nicht; die Mitteilung ist vorgemerkt | nichts |
| `grund: doppelt` | dieselbe Mitteilung steht schon da | nichts |
| `rueckfall: gebuendelt` | zu viele in kurzer Zeit | Ergebnisse in eine Mitteilung fassen |
| `rueckfall: kanal` | niemand da und nichts wird vorgemerkt (Nachholen ist aus) | Ergebnis im Workboard oder in einer Notiz hinterlassen |

Es kommen höchstens 20 vorgemerkte Mitteilungen zusammen; die ältesten fallen heraus. Fasse also zusammen.

## 4. Prüfen

- `mcp.zeitplan` zeigt den Auftrag mit nächstem Lauf und Ergebnis des letzten.
- `os.lage` zeigt, ob eine Shell offen ist. `os.mitteilen` bei offener Shell erscheint sofort; ohne sie wartet es.
- Ein Probelauf: `python3 tools/nachtauftrag.py --jetzt`, danach die Shell öffnen.
