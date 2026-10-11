// Prüfstand für die Vorlage „diagramm“ (test_gui_diagramm.py): lädt ansicht.js unter Node (ohne GUI-Rahmen, nur die
// Rechenfunktionen) und rechnet die Fälle aus der JSON-Datei. Aufruf: node gui_diagramm_pruefstand.js <ansicht.js> <faelle.json>
// Fälle: {"name": …, "spec": …} → rendern; {"name": …, "svg": "<svg …"} → pruefenSvg. Ausgabe: JSON mit den Ergebnissen je Name.
const fs = require("fs");
const kern = require(process.argv[2]);
const faelle = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const aus = {};
for (const f of faelle) {
  if ("svg" in f) aus[f.name] = { verstoesse: kern.pruefenSvg(f.svg) };
  else aus[f.name] = kern.rendern(f.spec);
}
process.stdout.write(JSON.stringify(aus));
