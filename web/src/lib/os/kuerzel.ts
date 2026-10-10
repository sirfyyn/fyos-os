/** Zwei Buchstaben für das Symbol einer Fläche, wenn keine Glyphe da ist (Anfangsbuchstaben der ersten zwei Wörter). */
export const kuerzelVon = (titel: string): string => {
  const w = titel.replace(/[^\p{L}\p{N} ]/gu, '').trim().split(/\s+/);
  const k = w.length > 1 ? (w[0]![0]! + w[1]![0]!) : (w[0] ?? '??').slice(0, 2);
  return k.charAt(0).toUpperCase() + k.slice(1).toLowerCase();
};
