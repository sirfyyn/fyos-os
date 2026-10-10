/**
 * Allein — eine Fläche allein im Tab (`/os/allein/?ziel=…`).
 *
 * Was „In neuem Tab öffnen“ im OS zeigt: dieselbe Fläche wie im Fenster (Seite, Hub-App oder native Fläche, gebaut
 * vom selben `Inhalt`), auf der Kulisse des OS, ohne Seitenleiste. Oben links „Zurück“ — zum OS-Tab, aus dem sie
 * kam, sonst zum offenen OS-Tab, sonst wird dieser Tab das OS (lib/os/allein.ts).
 *
 * Hub-Apps und native Flächen wachsen mit ihrem Inhalt und die Seite scrollt; eine Seite (eigenes Dokument) füllt
 * den Platz unter dem Kopf und scrollt für sich — wie im Fenster.
 */
import { Show, createEffect, createMemo, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { apps as hubApps, type McpApp } from '~/lib/mcp-apps/host';
import { konfigurationLaden, systemName } from '~/lib/config';
import { alleinAdresse, zielAufloesen, zurueckZumOs } from '~/lib/os/allein';
import { alleFlaechen } from '~/lib/os/flaechen';
import { OEFFNEN, eingabeLesen, osZielAus, type OsZiel } from '~/lib/os/oeffnen';
import { AppAktionen, AppTitel } from './AppRahmen';
import { Inhalt } from './Fenster';
import Kulisse from './Kulisse';

const SCHMAL = '(max-width: 767px)';

export default function Allein(): JSX.Element {
  const suche = new URLSearchParams(location.search);
  // `id` als zweiter Name: so hießen Links aus dem ersten Entwurf
  const roh = suche.get('ziel') ?? suche.get('id') ?? '';
  // Ein Pfad kommt von einer direkt aufgerufenen Seite: `/apps/mcp/?app=x` ist die App,
  // `/os/?offen=…` die Fläche, alles andere eine Seite
  const alsPfad = roh.startsWith('/') ? osZielAus(roh, location) : null;
  const ziel = alsPfad?.ziel ?? roh;
  const eingabe = alsPfad?.eingabe ?? eingabeLesen(suche.get('eingabe'));

  const [appListe, setAppListe] = createSignal<McpApp[] | null>(null);
  const [schmal, setSchmal] = createSignal(typeof matchMedia === 'function' && matchMedia(SCHMAL).matches);
  const treffer = createMemo(() => {
    const t = zielAufloesen(alleFlaechen(appListe() ?? []), ziel, eingabe);
    // Eine Seite mit genau der aufgerufenen Adresse laden (Unterseite, Filter, Eintrag), nicht nur ihrem Einstieg
    return t && ziel.startsWith('/') && t.f.pfad ? { ...t, f: { ...t.f, pfad: roh } } : t;
  });
  /** Hub nicht erreichbar: eine App-Fläche ist dann nicht „unbekannt“, sondern gerade nicht zu laden */
  const [hubFehler, setHubFehler] = createSignal(false);
  // Erst „gibt es nicht“ sagen, wenn auch die Hub-Apps da sind (eine App-Fläche kennt man erst dann)
  const unbekannt = () => !treffer() && (appListe() !== null || !ziel.startsWith('app:')) && !(hubFehler() && ziel.startsWith('app:'));
  const laedt = () => !treffer() && appListe() === null && ziel.startsWith('app:');
  const f = () => treffer()?.f;

  onMount(() => {
    void konfigurationLaden();
    void hubApps(true)
      .catch(() => {
        setHubFehler(true);
        return [] as McpApp[];
      })
      .then(setAppListe);
    // Links und ui/open-link aus der Fläche (fyos:oeffnen): hier allein weiter, nicht als alte Seite
    const oeffnen = (e: Event) => {
      const d = (e as CustomEvent<OsZiel | undefined>).detail;
      if (!d || typeof d.ziel !== 'string') return;
      e.preventDefault();
      location.assign(alleinAdresse(d.ziel, d.eingabe));
    };
    window.addEventListener(OEFFNEN, oeffnen);
    onCleanup(() => window.removeEventListener(OEFFNEN, oeffnen));
    if (typeof matchMedia === 'function') {
      const m = matchMedia(SCHMAL);
      const neu = () => setSchmal(m.matches);
      m.addEventListener('change', neu);
      onCleanup(() => m.removeEventListener('change', neu));
    }
  });

  createEffect(() => {
    document.title = f() ? `${f()!.titel} · ${systemName()}` : systemName();
  });

  const seite = () => f()?.art === 'seite' || f()?.art === 'agent';
  const zurueck = () => void zurueckZumOs(f()?.id ?? (ziel || undefined));

  return (
    <div
      class="relative flex flex-col"
      classList={{ 'h-full': seite(), 'min-h-full': !seite() }}
      data-allein={f()?.id ?? ''}
    >
      {/* Die Kulisse bleibt stehen, während die Seite scrollt */}
      <div class="pointer-events-none fixed inset-0 z-0">
        <Kulisse />
      </div>

      <header class="os-glas os-allein-kopf sticky top-0 z-10 m-3 mb-0 flex min-h-11 items-center gap-2 rounded-[var(--os-radius)] px-2 md:mx-5">
        <button
          type="button"
          class="os-knopf os-allein-zurueck"
          title="Zurück ins OS"
          aria-label="Zurück ins OS"
          onClick={zurueck}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
          <span>{systemName()}</span>
        </button>
        <Show when={f()}>
          <div class="min-w-0 flex-1">
            <AppTitel f={f()!} />
          </div>
          <Show when={f()!.art === 'hubapp'}>
            <div class="os-app-aktionen" role="group" aria-label={`${f()!.titel}: Aktionen`}>
              <AppAktionen f={f()!} start={treffer()?.start} />
            </div>
          </Show>
        </Show>
      </header>

      <main class="relative z-[1] flex min-h-0 flex-1 flex-col p-3 md:px-5 md:pb-5">
        <Show
          when={f()}
          fallback={
            <>
              <Show when={laedt()}>
                <p class="m-auto text-sm opacity-70" role="status">Lädt …</p>
              </Show>
              <Show when={hubFehler() && !treffer() && ziel.startsWith('app:')}>
                <div class="os-glas m-auto max-w-md rounded-[var(--os-radius)] p-6 text-center" role="alert">
                  <p class="m-0 text-base">Der Hub antwortet gerade nicht, die App lässt sich nicht laden.</p>
                  <button type="button" class="os-knopf mt-4 px-3" onClick={() => location.reload()}>Neu laden</button>
                </div>
              </Show>
              <Show when={unbekannt()}>
                <div class="os-glas m-auto max-w-md rounded-[var(--os-radius)] p-6 text-center">
                  <p class="m-0 text-base">Diese Fläche gibt es nicht (mehr).</p>
                  <button type="button" class="os-knopf mt-4 px-3" onClick={zurueck}>Zurück ins OS</button>
                </div>
              </Show>
            </>
          }
        >
          {/* Dieselbe Hülle wie ein Fenster: Glas, und eingebettete Seiten erkennen sich als „im OS“ */}
          <section class="os-glas os-fenster os-fokus relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden" data-fenster={f()!.id} aria-label={f()!.titel}>
            <div class="flex min-h-0 flex-1 flex-col" data-kontext="inhalt">
              <Inhalt f={f()!} ziehen={false} oeffne={(id) => location.assign(alleinAdresse(id))} schmal={schmal()} start={treffer()?.start} />
            </div>
          </section>
        </Show>
      </main>
    </div>
  );
}
