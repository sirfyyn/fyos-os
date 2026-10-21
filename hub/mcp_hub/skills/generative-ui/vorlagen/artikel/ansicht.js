// Vorlage „artikel“ (20.10.2026): ruhige Lesespalte für einen Artikel aus lesen.artikel — Kopf mit Quelle, Datum und
// Lesezeit, dann die Absätze; „Im Browser öffnen“ geht über openLink (nur https).
(() => {
  const { el } = GUI;
  const wurzel = document.getElementById("v");
  const KNOTEN = { h: "h3", li: "li", zitat: "blockquote", p: "p" };

  function zeichnen(d) {
    d = d || {};
    const absaetze = Array.isArray(d.absaetze) ? d.absaetze.filter((a) => a && a.text) : [];
    const meta = [d.quelle, d.datum ? GUI.zeit(d.datum, "tag") : "", d.autor, d.lesezeit ? `${d.lesezeit} min Lesezeit` : ""]
      .filter(Boolean).map((t) => el("span", { text: String(t) }));
    const original = /^https:/i.test(d.url || "")
      ? el("button", { type: "button", class: "a-original", onclick: () => window.openLink(d.url).catch(() => {}) }, "Im Browser öffnen ↗")
      : null;
    // Aufeinanderfolgende Aufzählungspunkte in eine Liste
    const inhalt = [];
    let liste = null;
    for (const a of absaetze) {
      const art = KNOTEN[a.art] ? a.art : "p";
      if (art === "li") {
        if (!liste) { liste = el("ul", { class: "a-liste" }); inhalt.push(liste); }
        liste.append(el("li", { text: String(a.text) }));
        continue;
      }
      liste = null;
      inhalt.push(el(KNOTEN[art], { class: `a-${art}`, text: String(a.text) }));
    }
    wurzel.replaceChildren(
      el("header", { class: "a-kopf" },
        meta.length ? el("p", { class: "a-meta" }, meta) : null,
        el("h1", { class: "a-titel", text: String(d.titel || "Artikel") }),
        d.einleitung && !absaetze.some((a) => a.text === d.einleitung) ? el("p", { class: "a-einleitung", text: String(d.einleitung) }) : null),
      d.hinweis ? el("p", { class: "a-hinweis", role: "status", text: String(d.hinweis) }) : null,
      el("div", { class: "a-text" }, inhalt),
      original ? el("footer", { class: "a-fuss" }, original) : null,
    );
  }

  GUI.beiDaten(zeichnen);
})();
