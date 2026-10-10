// Vorlage „vergleich“: Karten je Option plus Matrix der Kriterien, bester Zahlenwert je Kriterium hervorgehoben.
GUI.beiDaten((d) => {
  d = d || {};
  const { el } = GUI;
  const optionen = (Array.isArray(d.optionen) ? d.optionen : []).filter((o) => o && o.name != null);
  let kriterien = (Array.isArray(d.kriterien) ? d.kriterien : []).filter((k) => k && k.schluessel);
  if (!kriterien.length) kriterien = [...new Set(optionen.flatMap((o) => Object.keys(o.merkmale || {})))].map((s) => ({ schluessel: s, name: s }));

  const karten = el("div", { class: "gui-raster vg-karten" }, optionen.map((o) => {
    const karte = el("article", { class: "gui-karte vg-karte" + (o.frage ? " gui-klickbar" : ""), "data-empfohlen": o.empfohlen ? "" : null },
      el("h3", { text: String(o.name) }),
      o.empfohlen ? el("span", {}, el("span", { class: "gui-ton", "data-ton": "gut", text: "Empfehlung" })) : null,
      o.text ? el("p", { text: o.text }) : null);
    if (o.frage) {
      karte.tabIndex = 0; karte.setAttribute("role", "button");
      karte.addEventListener("click", () => GUI.fragen(o.frage));
      karte.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); GUI.fragen(o.frage); } });
    }
    return karte;
  }));

  const bester = (k) => {
    if (!k.besser) return null;
    const werte = optionen.map((o) => Number((o.merkmale || {})[k.schluessel])).filter(Number.isFinite);
    if (werte.length < 2) return null;
    return k.besser === "hoch" ? Math.max(...werte) : Math.min(...werte);
  };
  const wert = (k, v, best) => {
    if (typeof v === "boolean") return el("td", {}, el("span", { class: "gui-ton", "data-ton": v ? "gut" : "aus", text: v ? "ja" : "nein" }));
    if (typeof v === "number") return el("td", { class: "vg-zahl", "data-bester": best != null && v === best ? "" : null,
      text: GUI.zahl(v) + (k.einheit ? ` ${k.einheit}` : "") + (best != null && v === best ? " ★" : "") });
    return el("td", { text: v == null || v === "" ? "–" : String(v) });
  };
  const matrix = kriterien.length ? el("div", { class: "vg-matrix" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Kriterium" }), optionen.map((o) => el("th", { scope: "col", "data-empfohlen": o.empfohlen ? "" : null, text: String(o.name) })))),
    el("tbody", {}, kriterien.map((k) => {
      const best = bester(k);
      const name = (k.name || k.schluessel) + (k.besser ? (k.besser === "hoch" ? " (höher besser)" : " (niedriger besser)") : "");
      return el("tr", {}, el("th", { scope: "row", text: name }), optionen.map((o) => wert(k, (o.merkmale || {})[k.schluessel], best)));
    })))) : null;

  document.getElementById("v").replaceChildren(...GUI.kopf(d), karten, ...(matrix ? [matrix] : []), ...GUI.fuss(d));
});
