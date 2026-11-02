# SVG diagrams in built views

Based on the skill `svg-diagrams` of Open Intelligent UI (CopilotKit, MIT), adapted for `gui.bauen`. The SVG goes in
`html`. Static diagrams need no `js`. CSS animations belong in `css`, not in a `<style>` inside the SVG.

## When

- **Flow**: steps, decisions, pipelines. One direction, top to bottom or left to right.
- **Structure**: what is inside what (architecture, clusters, components). Nested rectangles, at most three levels.
- **Illustration**: "How does X actually work?" Free shapes, colour shows intensity (warm = active, cool = resting),
  labels at the edge with leader lines.

## Grid

```svg
<svg width="100%" viewBox="0 0 680 H" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="t d">
  <title id="t">Short title</title><desc id="d">One sentence on what the diagram shows.</desc>
  <defs>
    <marker id="pfeil" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  …
</svg>
```

- The width is 680 in the viewBox, plus `width="100%"`. That way the SVG scales along.
- **H** = lowest element (y + height) + 40. Calculate it instead of guessing.
- The content lies between x 40 and 640 and between y 40 and H − 40. The background stays transparent.

## Rules

- Text in two sizes: 14 px for titles, 12 px for additions. Two weights: 400 and 500. Sentence case.
- Text in a box gets `text-anchor="middle"` and `dominant-baseline="central"`.
- **Width** of a box = max(characters × 8 at 14 px, characters × 7 at 12 px) + 48.
- Box height: one line 44, two lines 56. Boxes of the same kind have the same height.
- Distance between boxes at least 60, padding 24. At most 4–5 nodes per row; with more, split into partial diagrams.
- Lines: frames 0.5, arrows 1.5. **Every connector path gets `fill="none"`**, otherwise it becomes a black blot.
- Arrows do not cross foreign boxes. Route them around, with an L bend.
- Colour carries meaning, not order. Use 2 to 3 ramps per diagram: warm for active or important, cool for calm, grey
  for scaffolding.

## Classes instead of hex values (they follow the theme)

```svg
<g class="c-blue">
  <rect x="230" y="20" width="220" height="56" rx="8" stroke-width="0.5"/>
  <text class="th" x="340" y="38" text-anchor="middle" dominant-baseline="central">Request</text>
  <text class="ts" x="340" y="56" text-anchor="middle" dominant-baseline="central">POST /api/daten</text>
</g>
<line class="arr" x1="340" y1="76" x2="340" y2="100" marker-end="url(#pfeil)"/>
```

- Ramps: `c-purple c-teal c-coral c-pink c-gray c-blue c-green c-amber c-red`. They colour fill, line and text.
- Neutral: `.box` (surface `--bg2`, line `--b`), `.arr` (arrow), `.leader` (dashed leader line), `.node` (clickable,
  with hover).
- Free text: `.t` (14 px), `.ts` (12 px, quieter), `.th` (14 px, 500). Without a class, text needs `fill`, because SVG
  is black otherwise. Then use `fill="var(--color-text-primary)"`.

## Check before sending

1. Is H right, and is nothing to the right of 640 or below H − 40?
2. Does every text fit into its box?
3. Does no arrow run through a box?
4. Do all paths have `fill="none"` and all text a colour?
5. Is there a `<title>`/`<desc>` or a text next to it?

If the topic is large, prefer several small SVGs (3 to 5 nodes) with text in between. The first shows the overview,
the others enlarge parts. Announce only diagrams you actually deliver.
