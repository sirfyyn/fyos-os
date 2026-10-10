/**
 * AppRahmen — der Fensterkopf einer Hub-App im OS.
 *
 * Der Kopf einer App trägt ihr Gesicht (Symbol und Titel, wie im Katalog und im Start) und drei ruhige Aktionen
 * wie die Werkzeugleiste eines Mac-Fensters:
 *
 *   Agent fragen             gibt Name, aktuelle Eingabe und Modellkontext der App weiter (lib/os/app-aktionen.ts)
 *   Link kopieren            Deeplink mit der aktuellen Eingabe; „Link kopiert" erscheint kurz im Kopf neben den Aktionen
 *   An den Start heften      nur für Apps, die beim Laden nichts auslösen (lesend, ohne Pflichtfelder)
 *
 * Dieselben Aktionen stehen oben im Fenstermenü (Raster.tsx); der Fensterkopf selbst (Ampel, ⋯, Ziehen) bleibt
 * in Fenster.tsx.
 */
import { Show, createSignal, onCleanup, onMount, type JSX } from 'solid-js';
import { istAngepinnt, pinsBeobachten } from '~/lib/mcp-apps/pins';
import type { StartZustand } from '~/lib/os/anordnung';
import { agentName } from '~/lib/config';
import { appFragen, heften, kannHeften, linkKopieren, rueckmeldung } from '~/lib/os/app-aktionen';
import type { Flaeche } from '~/lib/os/flaechen';
import Symbol, { Glyphe } from './Symbol';

/** Symbol und Titel der App; die Zeile darunter (Untertitel) erscheint beim Darüberfahren. */
export function AppTitel(p: { f: Flaeche }): JSX.Element {
  return (
    <div class="os-app-titel" title={p.f.untertitel || undefined}>
      <Symbol id={p.f.id} gruppe={p.f.gruppe} class="os-app-symbol" />
      <h2 class="os-fenstertitel">{p.f.titel}</h2>
    </div>
  );
}

/** Die Aktionen als Knöpfe mit Symbol. Auf schmalen Köpfen bleibt „Agent fragen"; der Rest steht im ⋯-Menü. */
export function AppAktionen(p: { f: Flaeche; start?: StartZustand }): JSX.Element {
  const [geheftet, setGeheftet] = createSignal(false);
  onMount(() => {
    const lesen = () => setGeheftet(!!p.f.appName && istAngepinnt(p.f.appName));
    lesen();
    onCleanup(pinsBeobachten(lesen));
  });
  const meldung = () => {
    const m = rueckmeldung();
    return m && m.id === p.f.id ? m : null;
  };
  const kopiert = () => meldung()?.text === 'Link kopiert';

  return (
    <>
      <button
        type="button"
        class="os-knopf os-app-aktion os-app-agent"
        aria-label={`${p.f.titel}: ${agentName()} fragen`}
        title={`${agentName()} fragen`}
        onClick={() => void appFragen(p.f, p.start)}
      >
        <Glyphe name="sparkles" class="os-app-glyphe" />
      </button>
      <button
        type="button"
        class="os-knopf os-app-aktion os-app-zweit"
        classList={{ 'os-app-gut': kopiert() }}
        aria-label={`${p.f.titel}: Link kopieren`}
        title="Link kopieren"
        onClick={() => void linkKopieren(p.f, p.start)}
      >
        <Glyphe name={kopiert() ? 'check' : 'link'} class="os-app-glyphe" />
      </button>
      <Show when={kannHeften(p.f)}>
        <button
          type="button"
          class="os-knopf os-app-aktion os-app-zweit"
          classList={{ 'os-app-an': geheftet() }}
          aria-pressed={geheftet()}
          aria-label={`${p.f.titel}: ${geheftet() ? 'vom Start lösen' : 'an den Start heften'}`}
          title={geheftet() ? 'Vom Start lösen' : 'An den Start heften'}
          onClick={() => void heften(p.f)}
        >
          <Glyphe name={geheftet() ? 'pin-off' : 'pin'} class="os-app-glyphe" />
        </button>
      </Show>
      {/* Rückmeldung: bleibt als Fläche im Dokument, damit Screenreader sie vorlesen; sichtbar nur mit Text */}
      <span class="os-app-melder" role="status" aria-live="polite" data-art={meldung()?.art} data-an={meldung() ? '' : undefined}>
        <Show when={meldung()}>
          {(m) => (
            <>
              <Glyphe name={m().art === 'ok' ? 'check' : 'info'} class="os-app-glyphe" />
              {m().text}
            </>
          )}
        </Show>
      </span>
    </>
  );
}
