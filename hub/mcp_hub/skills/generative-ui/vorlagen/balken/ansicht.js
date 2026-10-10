// Vorlage „balken“: waagerechte (gestapelte) Balken, sortierbar, Teile ein- und ausblendbar.
(() => {
  const { el, svg } = GUI;
  let daten = {}, sortierung = null;
  const aus = new Set();
  const wurzel = document.getElementById("v");

  const teileVon = (d) => {
    if (Array.isArray(d.teile) && d.teile.length) return d.teile.filter((t) => t && t.schluessel);
    const schluessel = [...new Set((d.reihen || []).flatMap((r) => Object.keys(r.werte || {})))];
    return schluessel.length ? schluessel.map((s) => ({ schluessel: s, name: s })) : [{ schluessel: "wert", name: d.einheit || "Wert" }];
  };
  const werteVon = (r) => (r.werte && typeof r.werte === "object" ? r.werte : { wert: r.wert });

  function zeichnen() {
    const d = daten, teile = teileVon(d), sichtbar = teile.filter((t) => !aus.has(t.schluessel));
    const summe = (r) => sichtbar.reduce((s, t) => s + (Number(werteVon(r)[t.schluessel]) || 0), 0);
    let reihen = (Array.isArray(d.reihen) ? d.reihen : []).filter((r) => r && r.name != null);
    if (sortierung === "wert") reihen = [...reihen].sort((a, b) => summe(b) - summe(a));
    else if (sortierung === "name") reihen = [...reihen].sort((a, b) => String(a.name).localeCompare(String(b.name), "de"));
    const max = Math.max(1, ...reihen.map(summe));
    const B = 680, L = Math.min(220, 24 + 7.2 * Math.max(4, ...reihen.map((r) => String(r.name).length))), R = 64, H = 24, G = 8;
    const grafik = svg("svg", { class: "b-diagramm", viewBox: `0 0 ${B} ${Math.max(1, reihen.length) * (H + G) + 4}`, role: "img", "aria-label": d.ueberschrift || "Balkendiagramm" });
    reihen.forEach((r, i) => {
      const y = i * (H + G) + 2, werte = werteVon(r);
      const text = sichtbar.filter((t) => werte[t.schluessel]).map((t) => `${GUI.zahl(werte[t.schluessel])} ${t.name || t.schluessel}`).join(", ") || "0";
      const g = svg("g", { class: "b-zeile" + (r.frage ? " gui-klickbar" : ""), tabindex: r.frage ? 0 : null, role: r.frage ? "button" : null, "aria-label": `${r.name}: ${text}` },
        svg("title", { text: `${r.name}: ${text}` }),
        svg("rect", { class: "b-grund", x: 0, y: y - 2, width: B, height: H + 4, rx: 6, fill: "transparent" }),
        svg("text", { class: "t", x: L - 10, y: y + H / 2, "text-anchor": "end", "dominant-baseline": "central" }, String(r.name)));
      let x = L;
      for (const t of sichtbar) {
        const w0 = Number(werte[t.schluessel]) || 0; if (w0 <= 0) continue;
        const w = (B - L - R) * w0 / max;
        g.append(svg("rect", { class: `b-teil ${GUI.rampe(t.ton || r.ton || (sichtbar.length > 1 ? "" : "info"))}`, x, y, width: Math.max(w, 2), height: H, rx: 4, "stroke-width": 0.5 }));
        x += w;
      }
      g.append(svg("text", { class: "ts", x: x + 8, y: y + H / 2, "dominant-baseline": "central" }, GUI.zahl(summe(r)) + (d.einheit && sichtbar.length === 1 ? ` ${d.einheit}` : "")));
      if (r.frage) {
        g.addEventListener("click", () => GUI.fragen(r.frage));
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); GUI.fragen(r.frage); } });
      }
      grafik.append(g);
    });

    const leiste = el("div", { class: "gui-leiste" });
    if (teile.length > 1) {
      const legende = el("div", { class: "gui-leiste b-legende", role: "group", "aria-label": "Teile zeigen" }, teile.map((t) => {
        const box = el("input", { type: "checkbox", checked: !aus.has(t.schluessel), onchange: (e) => { e.target.checked ? aus.delete(t.schluessel) : aus.add(t.schluessel); zeichnen(); } });
        return el("label", {}, box, svg("svg", { viewBox: "0 0 10 10", "aria-hidden": "true" }, svg("rect", { class: GUI.rampe(t.ton), width: 10, height: 10, rx: 2 })), t.name || t.schluessel);
      }));
      leiste.append(legende);
    }
    const wahl = el("select", { id: "b-sort", onchange: (e) => { sortierung = e.target.value; zeichnen(); } },
      [["wert", "nach Wert"], ["name", "nach Name"], ["keine", "wie geliefert"]].map(([v, t]) => el("option", { value: v, selected: v === sortierung, text: t })));
    leiste.append(el("label", { for: "b-sort", text: "Sortieren" }), wahl);
    wurzel.replaceChildren(...GUI.kopf(d), leiste, grafik, ...GUI.fuss(d));
  }

  GUI.beiDaten((d) => {
    const neu = !daten.reihen;
    daten = d || {};
    if (neu) {
      sortierung = ["wert", "name", "keine"].includes(daten.sortierung) ? daten.sortierung : "wert";
      for (const t of teileVon(daten)) if (t.aus) aus.add(t.schluessel);
    }
    zeichnen();
  });
})();
