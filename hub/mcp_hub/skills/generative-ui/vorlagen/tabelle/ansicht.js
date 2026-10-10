// Vorlage „tabelle“: sortierbar, durchsuchbar, Zahlen/Zeiten deutsch, Tonspalten als Abzeichen.
(() => {
  const { el } = GUI;
  let daten = {}, sortSchluessel = null, sortAb = false, suche = "";
  const wurzel = document.getElementById("v");
  const RANG = { schlecht: 0, warn: 1, info: 2, gut: 3, aus: 4 };

  const zelle = (s, wert) => {
    const typ = s.typ || "text";
    if (wert == null || wert === "") return el("td", { class: typ === "zahl" ? "t-zahl" : null, text: "–" });
    if (typ === "zahl") return el("td", { class: "t-zahl", text: GUI.zahl(wert, { maximumFractionDigits: s.nachkomma ?? 2, minimumFractionDigits: s.nachkomma ?? 0 }) + (s.einheit ? ` ${s.einheit}` : "") });
    if (typ === "zeit" || typ === "tag") return el("td", { text: GUI.zeit(wert, typ === "tag" ? "tag" : undefined) });
    if (typ === "ton") return el("td", {}, el("span", { class: "gui-ton", "data-ton": GUI.ton(wert), text: String(wert) }));
    return el("td", { text: String(wert) + (s.einheit ? ` ${s.einheit}` : "") });
  };
  const vergleich = (s) => (a, b) => {
    const x = a[s.schluessel], y = b[s.schluessel];
    if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
    if (s.typ === "zahl") return Number(x) - Number(y);
    if (s.typ === "zeit" || s.typ === "tag") return Date.parse(x) - Date.parse(y);
    if (s.typ === "ton") return (RANG[GUI.ton(x)] ?? 9) - (RANG[GUI.ton(y)] ?? 9);
    return String(x).localeCompare(String(y), "de", { numeric: true });
  };

  function zeichnen(fokus) {
    const d = daten, spalten = (Array.isArray(d.spalten) ? d.spalten : []).filter((s) => s && s.schluessel);
    let zeilen = Array.isArray(d.zeilen) ? d.zeilen.filter((z) => z && typeof z === "object") : [];
    const gesamt = zeilen.length;
    if (suche) {
      const q = suche.toLowerCase();
      zeilen = zeilen.filter((z) => spalten.some((s) => String(z[s.schluessel] ?? "").toLowerCase().includes(q)));
    }
    const s = spalten.find((x) => x.schluessel === sortSchluessel);
    if (s) { zeilen = [...zeilen].sort(vergleich(s)); if (sortAb) zeilen.reverse(); }
    const kopf = el("tr", {}, spalten.map((sp) => {
      const aktiv = sp.schluessel === sortSchluessel;
      return el("th", { class: sp.typ === "zahl" ? "t-zahl" : null, "aria-sort": aktiv ? (sortAb ? "descending" : "ascending") : null, scope: "col" },
        el("button", { type: "button", "data-spalte": sp.schluessel, onclick: () => {
          if (aktiv) sortAb = !sortAb; else { sortSchluessel = sp.schluessel; sortAb = sp.typ === "zahl" || sp.typ === "zeit" || sp.typ === "tag"; }
          zeichnen(sp.schluessel);
        } }, sp.name || sp.schluessel, aktiv ? (sortAb ? " ↓" : " ↑") : ""));
    }));
    const koerper = el("tbody", {}, zeilen.map((z) => {
      const tr = el("tr", { class: z.frage ? "gui-klickbar" : null }, spalten.map((sp) => zelle(sp, z[sp.schluessel])));
      if (z.frage) {
        tr.tabIndex = 0;
        tr.addEventListener("click", () => GUI.fragen(z.frage));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); GUI.fragen(z.frage); } });
      }
      return tr;
    }));
    const teile = [...GUI.kopf(d)];
    if (d.suche !== false && gesamt > 8) {
      const feld = el("input", { type: "search", id: "t-suche", class: "t-suche", placeholder: "Suchen …", value: suche, oninput: (e) => { suche = e.target.value; zeichnen("suche"); } });
      teile.push(el("div", { class: "gui-leiste" }, el("label", { for: "t-suche", text: "Suche" }), feld));
    }
    teile.push(el("div", { class: "t-huelle" }, el("table", {}, el("thead", {}, kopf), koerper)),
      el("p", { class: "t-anzahl", role: "status", text: suche ? `${zeilen.length} von ${gesamt} Einträgen` : `${gesamt} Einträge` }), ...GUI.fuss(d));
    wurzel.replaceChildren(...teile);
    if (fokus === "suche") { const f = document.getElementById("t-suche"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
    else if (fokus) { const b = wurzel.querySelector(`th button[data-spalte="${CSS.escape(fokus)}"]`); if (b) b.focus(); }
  }

  GUI.beiDaten((d) => {
    const neu = !daten.spalten;
    daten = d || {};
    if (neu && typeof daten.sortiert === "string" && daten.sortiert) {
      sortAb = daten.sortiert.startsWith("-"); sortSchluessel = daten.sortiert.replace(/^-/, "");
    }
    zeichnen();
  });
})();
