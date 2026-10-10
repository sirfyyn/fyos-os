/**
 * SitzungsBanner — ein Streifen oben, wenn die Anmeldung abgelaufen ist oder das Netz fehlt.
 *
 * Vorher sah eine abgelaufene Sitzung in jeder Pane aus wie „Backend nicht erreichbar"
 * oder wie eine leere Liste.
 * „Neu anmelden" lädt die Seite neu — der vorgeschaltete Anmelde-Proxy leitet zur Anmeldung und wieder zurück.
 */
import { createSignal, onCleanup, onMount, Show } from 'solid-js';
import { SITZUNG_EREIGNIS, sitzungAbgelaufen } from '~/lib/api/transport';
import { OFFLINE_EREIGNIS, netzWaechterInstallieren } from '~/lib/api/netz-waechter';

export default function SitzungsBanner() {
  const [abgelaufen, setAbgelaufen] = createSignal(false);
  const [offline, setOffline] = createSignal(false);

  onMount(() => {
    netzWaechterInstallieren();
    setAbgelaufen(sitzungAbgelaufen());
    setOffline(!navigator.onLine);
    const sitzung = () => setAbgelaufen(true);
    const netz = (e: Event) => setOffline(!(e as CustomEvent<{ online: boolean }>).detail.online);
    window.addEventListener(SITZUNG_EREIGNIS, sitzung);
    window.addEventListener(OFFLINE_EREIGNIS, netz);
    onCleanup(() => {
      window.removeEventListener(SITZUNG_EREIGNIS, sitzung);
      window.removeEventListener(OFFLINE_EREIGNIS, netz);
    });
  });

  return (
    <Show when={abgelaufen() || offline()}>
      <div
        role="alert"
        class="fixed inset-x-0 top-0 z-[1000] flex items-center justify-center gap-3 px-4 py-2 text-sm font-medium"
        style={{
          background: offline() ? 'var(--color-warn, #b26a00)' : 'var(--color-error, #c0392b)',
          color: '#fff',
        }}
      >
        <Show
          when={!offline()}
          fallback={<span>Kein Netz — Anzeigen können veraltet sein. Es geht weiter, sobald die Verbindung zurück ist.</span>}
        >
          <span>Anmeldung abgelaufen — Daten werden nicht mehr geladen.</span>
          <button
            type="button"
            class="rounded bg-white/20 px-3 py-1 hover:bg-white/30"
            onClick={() => location.reload()}
          >
            Neu anmelden
          </button>
        </Show>
      </div>
    </Show>
  );
}
