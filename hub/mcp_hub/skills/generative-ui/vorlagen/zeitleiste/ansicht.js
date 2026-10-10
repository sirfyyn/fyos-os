// Vorlage „zeitleiste“: Ereignisse nach Tag, Reihenfolge umschaltbar, Ton als Punkt, Klick fragt nach.
(() => {
  const { el } = GUI;
  let daten = {}, neuZuerst = true;
  const wurzel = document.getElementById("v");
  const tagSchluessel = (t) => new Intl.DateTimeFormat("de-DE", { year: "numeric", month: "2-digit", day: "2-digit" }).format(t);

  function zeichnen() {
    const d = daten;
    const liste = (Array.isArray(d.ereignisse) ? d.ereignisse : [])
      .map((e) => ({ ...e, t: new Date(e && e.zeit) })).filter((e) => e.titel != null && !isNaN(e.t))
      .sort((a, b) => (neuZuerst ? b.t - a.t : a.t - b.t));
    const gruppen = [];
    for (const e of liste) {
      const k = tagSchluessel(e.t);
      if (!gruppen.length || gruppen[gruppen.length - 1].k !== k) gruppen.push({ k, t: e.t, eintraege: [] });
      gruppen[gruppen.length - 1].eintraege.push(e);
    }
    const knopf = el("button", { type: "button", onclick: () => { neuZuerst = !neuZuerst; zeichnen(); } }, neuZuerst ? "Älteste zuerst" : "Neueste zuerst");
    const inhalt = gruppen.flatMap((g) => [
      el("h3", { class: "z-tag", text: new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" }).format(g.t) }),
      el("ol", { class: "z-liste" }, g.eintraege.map((e) => {
        const li = el("li", { class: "z-eintrag" + (e.frage ? " gui-klickbar" : ""), "data-ton": e.ton ? GUI.ton(e.ton) : null },
          el("div", { class: "z-kopf" }, el("time", { class: "z-uhr", datetime: e.t.toISOString(), text: GUI.zeit(e.t, "uhr") }), el("span", { class: "z-titel", text: String(e.titel) })),
          e.text ? el("p", { class: "z-text", text: String(e.text) }) : null);
        if (e.frage) {
          li.tabIndex = 0; li.setAttribute("role", "button");
          li.addEventListener("click", () => GUI.fragen(e.frage));
          li.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); GUI.fragen(e.frage); } });
        }
        return li;
      })),
    ]);
    wurzel.replaceChildren(...GUI.kopf(d), ...(liste.length > 1 ? [el("div", { class: "gui-leiste" }, knopf)] : []),
      ...(inhalt.length ? inhalt : [el("p", { class: "gui-text", text: "Keine Ereignisse." })]), ...GUI.fuss(d));
  }

  GUI.beiDaten((d) => {
    const neu = !daten.ereignisse;
    daten = d || {};
    if (neu) neuZuerst = daten.reihenfolge !== "alt";
    zeichnen();
  });
})();
