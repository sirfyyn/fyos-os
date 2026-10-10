# SVG-Diagramme in gebauten Ansichten

Nach dem Skill `svg-diagrams` von Open Intelligent UI (CopilotKit, MIT), für `gui.bauen` angepasst. Das SVG steht im
`html`. Statische Diagramme brauchen kein `js`. CSS-Animationen gehören in `css`, nicht in ein `<style>` im SVG.

## Wann

- **Ablauf**: Schritte, Entscheidungen, Pipelines. Eine Richtung, oben nach unten oder links nach rechts.
- **Aufbau**: Was steckt worin (Architektur, Cluster, Komponenten). Verschachtelte Rechtecke, höchstens drei Ebenen.
- **Anschauung**: „Wie funktioniert X eigentlich?“ Freie Formen, Farbe zeigt Stärke (warm = aktiv, kühl = ruhend),
  Beschriftungen am Rand mit Hinweislinien.

## Raster

```svg
<svg width="100%" viewBox="0 0 680 H" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="t d">
  <title id="t">Kurzer Titel</title><desc id="d">Ein Satz, was das Diagramm zeigt.</desc>
  <defs>
    <marker id="pfeil" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  …
</svg>
```

- Die Breite ist 680 im viewBox, dazu `width="100%"`. Damit skaliert das SVG mit.
- **H** = unterstes Element (y + Höhe) + 40. Rechne es aus, statt zu raten.
- Der Inhalt liegt zwischen x 40 und 640 und zwischen y 40 und H − 40. Der Hintergrund bleibt durchsichtig.

## Regeln

- Schrift in zwei Größen: 14 px für Titel, 12 px für Zusätze. Zwei Stärken: 400 und 500. Satzschreibung.
- Text in einem Kasten bekommt `text-anchor="middle"` und `dominant-baseline="central"`.
- **Breite** eines Kastens = max(Zeichen × 8 bei 14 px, Zeichen × 7 bei 12 px) + 48.
- Kastenhöhe: einzeilig 44, zweizeilig 56. Gleichartige Kästen sind gleich hoch.
- Abstand zwischen Kästen mindestens 60, innen 24. Höchstens 4–5 Knoten je Reihe, bei mehr in Teildiagramme aufteilen.
- Linien: Rahmen 0,5, Pfeile 1,5. **Jeder Verbinder-Pfad bekommt `fill="none"`**, sonst wird er ein schwarzer Fleck.
- Pfeile kreuzen keine fremden Kästen. Leite sie um, mit L-Knick.
- Farbe trägt Bedeutung, nicht Reihenfolge. Nimm 2 bis 3 Rampen je Diagramm: warm für aktiv oder wichtig, kühl für
  ruhig, grau für Gerüst.

## Klassen statt Hex-Werte (folgen dem Thema)

```svg
<g class="c-blue">
  <rect x="230" y="20" width="220" height="56" rx="8" stroke-width="0.5"/>
  <text class="th" x="340" y="38" text-anchor="middle" dominant-baseline="central">Anfrage</text>
  <text class="ts" x="340" y="56" text-anchor="middle" dominant-baseline="central">POST /api/daten</text>
</g>
<line class="arr" x1="340" y1="76" x2="340" y2="100" marker-end="url(#pfeil)"/>
```

- Rampen: `c-purple c-teal c-coral c-pink c-gray c-blue c-green c-amber c-red`. Sie färben Füllung, Linie und Text.
- Neutral: `.box` (Fläche `--bg2`, Linie `--b`), `.arr` (Pfeil), `.leader` (gestrichelte Hinweislinie), `.node`
  (klickbar, mit Hover).
- Freier Text: `.t` (14 px), `.ts` (12 px, leiser), `.th` (14 px, 500). Ohne Klasse braucht Text `fill`, denn SVG ist
  sonst schwarz. Dann nimm `fill="var(--color-text-primary)"`.

## Prüfen vor dem Abschicken

1. Stimmt H, und liegt nichts rechts von 640 oder unter H − 40?
2. Passt jeder Text in seinen Kasten?
3. Läuft kein Pfeil durch einen Kasten?
4. Haben alle Pfade `fill="none"` und aller Text eine Farbe?
5. Gibt es `<title>`/`<desc>` oder einen Text daneben?

Ist das Thema groß, nimm lieber mehrere kleine SVGs (3 bis 5 Knoten) mit Text dazwischen. Das erste zeigt den Überblick,
die weiteren vergrößern Ausschnitte. Kündige nur Diagramme an, die du auch lieferst.
