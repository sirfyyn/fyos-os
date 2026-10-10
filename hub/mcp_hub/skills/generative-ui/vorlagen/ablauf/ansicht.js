// Vorlage „ablauf“: Kästen mit Pfeilen, senkrecht oder waagerecht in Zeilen (Raster aus references/svg-diagramme.md).
(() => {
  const { el, svg } = GUI;
  let daten = {};
  const wurzel = document.getElementById("v");
  const FARBEN = ["purple", "teal", "coral", "pink", "gray", "blue", "green", "amber", "red"];

  function zeichnen() {
    const d = daten;
    const schritte = (Array.isArray(d.schritte) ? d.schritte : []).filter((s) => s && s.titel != null);
    const breit = d.richtung === "waagerecht";
    const B = 680, KW = breit ? 180 : 300, KH = 56, LUECKE = breit ? 40 : 34;
    const proZeile = breit ? Math.max(1, Math.min(schritte.length, Math.floor((B + LUECKE) / (KW + LUECKE)))) : 1;
    const zeilen = Math.ceil(schritte.length / proZeile);
    const H = zeilen * KH + (zeilen - 1) * LUECKE + 8;
    const grafik = svg("svg", { class: "a-diagramm", viewBox: `0 0 ${B} ${H}`, role: "img", "aria-label": (d.ueberschrift ? d.ueberschrift + ": " : "") + schritte.map((s) => s.titel).join(" → ") },
      svg("defs", {}, svg("marker", { id: "a-pfeil", viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" },
        svg("path", { d: "M2 1L8 5L2 9", fill: "none", style: "stroke: var(--color-text-secondary)", "stroke-width": 1.5, "stroke-linecap": "round", "stroke-linejoin": "round" }))));
    const ort = (i) => {
      const z = Math.floor(i / proZeile), sp = i % proZeile;
      const genutzt = Math.min(proZeile, schritte.length - z * proZeile);
      const links = (B - (genutzt * KW + (genutzt - 1) * LUECKE)) / 2;
      return { x: links + sp * (KW + LUECKE), y: 4 + z * (KH + LUECKE) };
    };
    schritte.forEach((s, i) => {
      const { x, y } = ort(i);
      if (i > 0) {
        const v = ort(i - 1);
        const pfad = v.y === y
          ? `M${v.x + KW} ${y + KH / 2} L${x - 2} ${y + KH / 2}`
          : breit ? `M${v.x + KW / 2} ${v.y + KH} L${v.x + KW / 2} ${v.y + KH + LUECKE / 2} L${x + KW / 2} ${v.y + KH + LUECKE / 2} L${x + KW / 2} ${y - 2}`
            : `M${x + KW / 2} ${v.y + KH} L${x + KW / 2} ${y - 2}`;
        grafik.append(svg("path", { class: "arr", d: pfad, "marker-end": "url(#a-pfeil)" }));
      }
      const farbe = FARBEN.includes(s.farbe) ? `c-${s.farbe}` : s.ton ? GUI.rampe(s.ton) : "c-gray";
      const g = svg("g", { class: `a-schritt ${farbe}` + (s.frage ? " gui-klickbar node" : ""), tabindex: s.frage ? 0 : null, role: s.frage ? "button" : null },
        svg("title", { text: s.text ? `${s.titel}: ${s.text}` : s.titel }),
        svg("rect", { x, y, width: KW, height: KH, rx: 8, "stroke-width": 0.5 }),
        svg("text", { class: "th", x: x + KW / 2, y: y + (s.text ? KH / 2 - 9 : KH / 2), "text-anchor": "middle", "dominant-baseline": "central" }, String(s.titel)),
        s.text ? svg("text", { class: "ts", x: x + KW / 2, y: y + KH / 2 + 11, "text-anchor": "middle", "dominant-baseline": "central" }, String(s.text)) : null);
      if (s.frage) {
        g.addEventListener("click", () => GUI.fragen(s.frage));
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); GUI.fragen(s.frage); } });
      }
      grafik.append(g);
    });
    wurzel.replaceChildren(...GUI.kopf(d), grafik, ...GUI.fuss(d));
  }

  GUI.beiDaten((d) => { daten = d || {}; zeichnen(); });
})();
