/**
 * Die Shell lädt Apps-Seite, Hilfe, Kontrollzentrum und Raum träge (lazy in components/os/Shell.tsx). Beim ersten
 * Öffnen im Testlauf muss Vite das Modul samt Abhängigkeiten erst übersetzen; auf einem ausgelasteten CI-Runner
 * dauerte das länger als das Zeitfenster von findBy (1 s), und „Unable to find role=button name /Notizen/" fiel
 * im ersten Test, der die Apps-Seite öffnete. Vorab in beforeAll geladen, löst lazy() danach sofort aus dem
 * Modulspeicher auf: die Tests messen dann die Shell, nicht den Übersetzer.
 */
export async function shellTeileVorladen(): Promise<void> {
  await Promise.all([
    import('~/components/os/Start'),
    import('~/components/os/Hilfe'),
    import('~/components/os/Tapete'),
    import('~/components/os/Kontrollzentrum'),
    import('~/components/os/Raum'),
  ]);
}
