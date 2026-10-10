// Vorlage „status“: Zählung je Zustand, Gruppen, Filter „nur Probleme“, Probleme zuerst.
(() => {
  const { el } = GUI;
  const RANG = { schlecht: 0, warn: 1, info: 2, gut: 3, aus: 4 };
  const NAME = { schlecht: "Fehler", warn: "Warnung", info: "Hinweis", gut: "in Ordnung", aus: "aus" };
  let daten = {}, nurProbleme = false;
  const wurzel = document.getElementById("v");

  function zeichnen() {
    const d = daten;
    const alle = (Array.isArray(d.eintraege) ? d.eintraege : []).filter((e) => e && e.name != null)
      .map((e) => ({ ...e, ton: GUI.ton(e.zustand) }));
    const zaehl = {}; for (const e of alle) zaehl[e.ton] = (zaehl[e.ton] || 0) + 1;
    const probleme = (zaehl.schlecht || 0) + (zaehl.warn || 0);
    const liste = (nurProbleme ? alle.filter((e) => e.ton === "schlecht" || e.ton === "warn") : alle)
      .sort((a, b) => RANG[a.ton] - RANG[b.ton] || String(a.name).localeCompare(String(b.name), "de"));
    const gruppen = new Map();
    for (const e of liste) { const g = e.gruppe || ""; if (!gruppen.has(g)) gruppen.set(g, []); gruppen.get(g).push(e); }
    const zusammenfassung = el("div", { class: "gui-leiste", role: "status" },
      Object.keys(RANG).filter((t) => zaehl[t]).map((t) => el("span", { class: "gui-ton", "data-ton": t, text: `${zaehl[t]} ${NAME[t]}` })));
    const filter = probleme && probleme < alle.length ? el("label", {},
      el("input", { type: "checkbox", checked: nurProbleme, onchange: (e) => { nurProbleme = e.target.checked; zeichnen(); } }), " Nur Probleme") : null;
    const inhalt = [...gruppen].flatMap(([g, eintraege]) => [
      g ? el("h3", { class: "s-gruppe", text: g }) : null,
      el("ul", { class: "s-liste" }, eintraege.map((e) => {
        const li = el("li", { class: "gui-karte s-eintrag" + (e.frage ? " gui-klickbar" : "") },
          el("div", { class: "s-kopf" }, el("span", { class: "s-name", title: String(e.name), text: String(e.name) }),
            el("span", { class: "gui-ton", "data-ton": e.ton, text: String(e.zustand) })),
          e.text ? el("span", { class: "s-text", text: String(e.text) }) : null);
        if (e.frage) {
          li.tabIndex = 0; li.setAttribute("role", "button");
          li.addEventListener("click", () => GUI.fragen(e.frage));
          li.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); GUI.fragen(e.frage); } });
        }
        return li;
      })),
    ]).filter(Boolean);
    wurzel.replaceChildren(...GUI.kopf(d), zusammenfassung, ...(filter ? [el("div", { class: "gui-leiste" }, filter)] : []), ...inhalt, ...GUI.fuss(d));
  }

  GUI.beiDaten((d) => { daten = d || {}; zeichnen(); });
})();
