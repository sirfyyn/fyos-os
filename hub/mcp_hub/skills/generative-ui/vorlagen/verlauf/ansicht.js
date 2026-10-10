// Vorlage „verlauf“: Linien über Zeit oder Zahl, Fadenkreuz mit Werten, Serien ein- und ausblendbar.
(() => {
  const { el, svg } = GUI;
  const FARBEN = ["info", "gut", "warn", "schlecht"], EXTRA = ["c-purple", "c-pink", "c-coral"];
  const aus = new Set();
  let daten = {};
  const wurzel = document.getElementById("v");

  const klasse = (s, i) => (s.ton ? GUI.rampe(s.ton) : i < FARBEN.length ? GUI.rampe(FARBEN[i]) : EXTRA[(i - FARBEN.length) % EXTRA.length]);
  const alsX = (x, zeit) => (zeit ? (typeof x === "number" ? x : Date.parse(x)) : Number(x));
  function schoeneTeilung(min, max, n) {
    const roh = (max - min) / Math.max(1, n), p = Math.pow(10, Math.floor(Math.log10(roh || 1))), f = roh / p;
    const schritt = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
    const aus = []; for (let v = Math.ceil(min / schritt) * schritt; v <= max + schritt * 1e-9; v += schritt) aus.push(+v.toFixed(10));
    return aus;
  }

  function zeichnen() {
    const d = daten, zeit = d.x !== "zahl", ein = d.einheit ? ` ${d.einheit}` : "";
    const serien = (Array.isArray(d.serien) ? d.serien : []).map((s, i) => ({
      name: String(s.name ?? `Reihe ${i + 1}`), klasse: klasse(s, i),
      punkte: (Array.isArray(s.punkte) ? s.punkte : []).map((p) => [alsX(p[0], zeit), Number(p[1])]).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1])).sort((a, b) => a[0] - b[0]),
    }));
    const sichtbar = serien.filter((s) => !aus.has(s.name) && s.punkte.length);
    const alle = sichtbar.flatMap((s) => s.punkte);
    const B = 680, H = 300, LI = 48, RE = 14, OB = 12, UN = 28;
    const grafik = svg("svg", { class: "l-diagramm", viewBox: `0 0 ${B} ${H}`, role: "img", "aria-label": d.ueberschrift || "Verlauf" });
    const info = el("div", { class: "l-info", role: "status" });
    if (alle.length) {
      let x0 = Math.min(...alle.map((p) => p[0])), x1 = Math.max(...alle.map((p) => p[0]));
      if (x0 === x1) { x0 -= 1; x1 += 1; }
      let y0 = Math.min(...alle.map((p) => p[1])), y1 = Math.max(...alle.map((p) => p[1]));
      if (d.y_ab_null !== false && y0 > 0) y0 = 0;
      if (y0 === y1) { y1 += 1; }
      const yt = schoeneTeilung(y0, y1, 5); y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1]);
      const sx = (x) => LI + (x - x0) / (x1 - x0) * (B - LI - RE), sy = (y) => H - UN - (y - y0) / (y1 - y0) * (H - OB - UN);
      const raster = svg("g", { class: "l-raster" }), achse = svg("g", { class: "l-achse" });
      for (const v of yt) {
        raster.append(svg("line", { x1: LI, x2: B - RE, y1: sy(v), y2: sy(v) }));
        achse.append(svg("text", { x: LI - 6, y: sy(v), "text-anchor": "end", "dominant-baseline": "central" }, GUI.zahl(v)));
      }
      const xt = zeit ? Array.from({ length: 5 }, (_, i) => x0 + (x1 - x0) * i / 4) : schoeneTeilung(x0, x1, 5);
      const ueberTage = x1 - x0 > 36 * 3600e3;
      xt.forEach((v, i) => achse.append(svg("text", { x: sx(v), y: H - 8, "text-anchor": i === 0 ? "start" : i === xt.length - 1 ? "end" : "middle" },
        zeit ? GUI.zeit(v, ueberTage ? "tag" : "uhr") : GUI.zahl(v))));
      grafik.append(raster, achse);
      for (const m of Array.isArray(d.marken) ? d.marken : []) {
        const x = alsX(m.x, zeit); if (!Number.isFinite(x) || x < x0 || x > x1) continue;
        grafik.append(svg("g", { class: "l-marke" }, svg("line", { x1: sx(x), x2: sx(x), y1: OB, y2: H - UN }), svg("text", { x: sx(x) + 4, y: OB + 10 }, String(m.name ?? ""))));
      }
      for (const s of sichtbar) grafik.append(svg("polyline", { class: `l-linie ${s.klasse}`, points: s.punkte.map((p) => `${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ") }));
      const kreuz = svg("g", { class: "l-kreuz", visibility: "hidden" });
      grafik.append(kreuz);
      const zeigen = (px) => {
        const x = x0 + (px - LI) / (B - LI - RE) * (x1 - x0);
        const naechste = sichtbar.map((s) => ({ s, p: s.punkte.reduce((a, b) => (Math.abs(b[0] - x) < Math.abs(a[0] - x) ? b : a)) }));
        const xn = naechste.length ? naechste[0].p[0] : x;
        kreuz.replaceChildren(svg("line", { x1: sx(xn), x2: sx(xn), y1: OB, y2: H - UN }),
          ...naechste.map(({ s, p }) => svg("circle", { class: s.klasse, cx: sx(p[0]), cy: sy(p[1]), r: 4 })));
        kreuz.setAttribute("visibility", "visible");
        info.replaceChildren(el("b", { text: zeit ? GUI.zeit(xn) : GUI.zahl(xn) }), " · ",
          ...naechste.flatMap(({ s, p }, i) => [i ? " · " : "", `${s.name}: ${GUI.zahl(p[1])}${ein}`]));
      };
      grafik.addEventListener("pointermove", (e) => { const r = grafik.getBoundingClientRect(); zeigen((e.clientX - r.left) / r.width * B); });
      grafik.addEventListener("pointerleave", () => { kreuz.setAttribute("visibility", "hidden"); info.textContent = ""; });
      grafik.append(svg("title", { text: sichtbar.map((s) => `${s.name}: ${s.punkte.length} Punkte, zuletzt ${GUI.zahl(s.punkte[s.punkte.length - 1][1])}${ein}`).join("; ") }));
    } else {
      info.textContent = "Keine Werte zum Zeichnen.";
    }
    const legende = serien.length > 1 ? el("div", { class: "gui-leiste l-legende", role: "group", "aria-label": "Serien zeigen" }, serien.map((s) => el("label", {},
      el("input", { type: "checkbox", checked: !aus.has(s.name), onchange: (e) => { e.target.checked ? aus.delete(s.name) : aus.add(s.name); zeichnen(); } }),
      svg("svg", { viewBox: "0 0 14 10", "aria-hidden": "true" }, svg("line", { class: `l-linie ${s.klasse}`, x1: 0, x2: 14, y1: 5, y2: 5 })), s.name))) : null;
    wurzel.replaceChildren(...GUI.kopf(d), ...(legende ? [legende] : []), grafik, info, ...GUI.fuss(d));
  }

  GUI.beiDaten((d) => { daten = d || {}; zeichnen(); });
})();
