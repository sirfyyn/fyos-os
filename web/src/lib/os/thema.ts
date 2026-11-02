/**
 * thema.ts — Hell/Dunkel/Automatisch für das OS, dieselben Schlüssel wie ThemeDock
 * (`fyos-theme-mode`, Legacy `fyos-theme` fürs FOUC-Skript). Offene Seiten in Fenstern ziehen über
 * das `storage`-Ereignis nach (BaseLayout, eingebettet).
 */
export type ThemaWahl = 'dark' | 'light' | 'auto';

const auto = (): 'dark' | 'light' => {
  const h = new Date().getHours();
  return h >= 7 && h < 19 ? 'light' : 'dark';
};

export function themaWahl(): ThemaWahl {
  try {
    const m = localStorage.getItem('fyos-theme-mode');
    if (m === 'auto') return 'auto';
    if (m === 'manual:light') return 'light';
  } catch {
    /* ohne Speicher: dunkel */
  }
  return 'dark';
}

export function themaSetzen(w: ThemaWahl): void {
  const wirklich = w === 'auto' ? auto() : w;
  try {
    localStorage.setItem('fyos-theme-mode', w === 'auto' ? 'auto' : `manual:${w}`);
    localStorage.setItem('fyos-theme', wirklich);
  } catch {
    /* gilt bis zum Neuladen */
  }
  document.documentElement.dataset.theme = wirklich;
}
