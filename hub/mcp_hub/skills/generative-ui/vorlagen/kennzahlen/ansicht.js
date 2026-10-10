// Vorlage „kennzahlen“: Kacheln mit Wert, Ton und kleinem Verlauf.
GUI.beiDaten((d) => {
  d = d || {};
  const { el, svg } = GUI;
  const kacheln = (Array.isArray(d.kacheln) ? d.kacheln : []).map((k) => {
    const ton = k.ton ? GUI.ton(k.ton) : "";
    const wert = typeof k.wert === "number"
      ? GUI.zahl(k.wert, { minimumFractionDigits: k.nachkomma ?? 0, maximumFractionDigits: k.nachkomma ?? 2 })
      : String(k.wert ?? "–");
    const kinder = [
      el("span", { class: "k-titel", text: k.titel || "" }),
      el("span", { class: "k-wert" }, wert, k.einheit ? el("small", { text: k.einheit }) : null),
    ];
    const v = Array.isArray(k.verlauf) ? k.verlauf.filter((x) => Number.isFinite(x)) : [];
    if (v.length > 1) {
      const min = Math.min(...v), max = Math.max(...v), spanne = max - min || 1;
      const punkte = v.map((x, i) => `${(i / (v.length - 1)) * 100},${28 - ((x - min) / spanne) * 24 - 2}`).join(" ");
      kinder.push(svg("svg", { class: "k-verlauf", viewBox: "0 0 100 28", preserveAspectRatio: "none", role: "img", "aria-label": `Verlauf ${k.titel || ""}: ${GUI.zahl(v[0])} bis ${GUI.zahl(v[v.length - 1])}` },
        svg("polyline", { points: punkte })));
    }
    if (k.hinweis) kinder.push(el("span", { class: "k-hinweis", text: k.hinweis }));
    const kachel = el("div", { class: "gui-karte k-kachel" + (k.frage ? " gui-klickbar" : ""), "data-ton": ton || null }, kinder);
    if (k.frage) {
      kachel.tabIndex = 0; kachel.setAttribute("role", "button");
      kachel.addEventListener("click", () => GUI.fragen(k.frage));
      kachel.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); GUI.fragen(k.frage); } });
    }
    return kachel;
  });
  document.getElementById("v").replaceChildren(...GUI.kopf(d), el("div", { class: "gui-raster", role: "status" }, kacheln), ...GUI.fuss(d));
});
