/**
 * AppEingebettet — eine Hub-App fest in eine fyos-web-Seite einbetten.
 *
 * Gegenstück zu AngepinnteApps (die der Betrachter wählt): hier legt die Seite fest, welche
 * App sie trägt, z. B. der Dokument-Eingang auf der Dokumente-Seite. Die Oberfläche läuft im
 * Sandbox-iframe des Hosts und lädt erst, wenn sie sichtbar wird. Fällt der Hub aus oder
 * gibt es die App nicht, steht eine Zeile da — die Seite selbst bleibt unberührt.
 */
import { createSignal, onCleanup, onMount, Show } from 'solid-js';
import { agentFragen } from '~/lib/os/agent-fragen';
import { aktuellesTheme, appCall, appEinhaengen, apps } from '~/lib/mcp-apps/host';
import { aufrufbar } from '~/lib/mcp-apps/pins';
import type { StartZustand } from '~/lib/os/anordnung';

/**
 * `start`: Startzustand aus einem Deeplink (Werkzeug + Eingabe, Vertrag 2). Es zählt nur ein lesendes Werkzeug
 * mit derselben Oberfläche wie `name` — alles andere öffnet die Anfangsansicht, nie läuft damit etwas Schreibendes.
 * `schluessel`: unter ihm merkt der Host die aktuelle Ansicht (App-Rahmen: Link kopieren, Agent fragen).
 */
export default function AppEingebettet(props: {
  name: string;
  titel?: string;
  hoehe?: number;
  fuellen?: boolean;
  /**
   * Im OS-Fenster: die App bestimmt ihre Höhe selbst (size-changed, wie im Chat) und das Fenster wächst mit —
   * es scrollt nur die Fläche, nicht jede App für sich. Durchsichtig auf dem Glas wie `fuellen`.
   */
  wachsen?: boolean;
  start?: StartZustand;
  schluessel?: string;
}) {
  const [hoehe, setHoehe] = createSignal(props.hoehe ?? 160);
  const [fehler, setFehler] = createSignal('');
  // Bis die App ihre Höhe meldet, steht ein Platzhalter da (sonst stünde eine leere Karte
  // ohne Hinweis da); kommt nach 10 s nichts, steht da, was los ist, und ein Knopf zum Neuversuch.
  const [bereit, setBereit] = createSignal(false);
  const [zuLang, setZuLang] = createSignal(false);
  let zeitgeber: ReturnType<typeof setTimeout> | undefined;
  onCleanup(() => clearTimeout(zeitgeber));
  let rahmen: HTMLIFrameElement | undefined;
  let abmelden: (() => void) | undefined;
  // Zählt die Ladeversuche. Wer nach einem `await` merkt, dass inzwischen ein neuer Versuch läuft oder das Fenster
  // zu ist, räumt hinter sich auf, statt einen Listener stehen zu lassen (`abmelden` ist während des Wartens noch leer).
  let versuch = 0;
  const wenigBewegung = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  onCleanup(() => {
    versuch++;
    abmelden?.();
    abmelden = undefined;
  });
  // Auf dem Glas eines OS-Fensters (füllend oder wachsend): ohne eigene Karte, Hinweise ruhig in der Mitte
  const glas = () => !!(props.fuellen || props.wachsen);

  async function laden() {
    const mein = ++versuch;
    // „Erneut versuchen“ beginnt sauber: alter Listener ab, Fehler und Bereitschaft zurück
    abmelden?.();
    abmelden = undefined;
    setFehler('');
    setBereit(false);
    setZuLang(false);
    clearTimeout(zeitgeber);
    zeitgeber = setTimeout(() => { if (!bereit()) setZuLang(true); }, 10_000);
    try {
      const liste = await apps(true);
      if (mein !== versuch) return;
      const kopf = liste.find((a) => a.name === props.name);
      if (!kopf) return setFehler(`App ${props.name} gibt es im Hub nicht (mehr).`);
      const s = props.start;
      const mitglied = s
        ? liste.find((a) => a.name === s.werkzeug && a.scope === 'READ' && a._meta?.ui?.resourceUri === kopf._meta?.ui?.resourceUri)
        : undefined;
      const app = mitglied ?? kopf;
      const args = mitglied && s ? s.eingabe : {};
      // Ein Link löst nie etwas Schreibendes aus, und beim Öffnen läuft nichts von
      // selbst, was Angaben braucht, die niemand gemacht hat. Aufgerufen wird nur ein lesendes Werkzeug, dessen
      // Pflichtfelder die Eingabe vollständig belegt; sonst öffnet die App ohne Ergebnis (nur `tool-input`) und
      // holt ihre Anfangsansicht selbst — das tun alle Apps der Brücke nach 1,5 s (`App.start` → `holen()`).
      const ergebnis = aufrufbar(app, args) ? await appCall(app.name, args) : undefined;
      if (mein !== versuch) return;
      if (ergebnis?.isError) setFehler(ergebnis.content[0]?.text ?? 'Fehler');
      if (!rahmen) return;
      const ab = await appEinhaengen(rahmen, {
        app,
        args,
        ergebnis,
        theme: aktuellesTheme,
        schluessel: props.schluessel,
        fuellen: props.fuellen,
        sichtbar: !!props.wachsen,
        // Im OS-Fenster darf die App dem Agenten etwas schreiben (`ui/message`); auf einer gewöhnlichen Seite nicht
        onMessage: props.schluessel
          ? (text) => agentFragen({ text, kontext: { app: app.name, titel: props.titel ?? app.titel ?? app.title ?? app.name }, quelle: 'app' })
          : undefined,
        onHeight: (h) => { setBereit(true); setZuLang(false); setHoehe(h); },
      });
      if (mein !== versuch) return ab(); // Fenster zu oder neuer Versuch, während die App einhing
      abmelden = ab;
    } catch (e) {
      if (mein !== versuch) return;
      setFehler(`Hub nicht erreichbar: ${String((e as Error).message || e)}`);
    }
  }

  onMount(() => {
    if (typeof IntersectionObserver === 'undefined' || !rahmen) return void laden();
    const beobachter = new IntersectionObserver((e) => {
      if (e.some((x) => x.isIntersecting)) {
        beobachter.disconnect();
        void laden();
      }
    });
    beobachter.observe(rahmen);
    onCleanup(() => beobachter.disconnect());
  });

  // Im OS-Fenster liegt die App durchsichtig auf dem Glas: bis sie bereit ist, steht der Hinweis ruhig in der
  // Mitte, dann blendet sie ein — kein Aufblitzen eines halb geladenen Rahmens. Wachsend hält der Platzhalter
  // eine Mindesthöhe, bis die App ihre Höhe meldet.
  return (
    <section
      aria-label={props.titel ?? props.name}
      class={props.fuellen
        ? 'relative flex h-full min-h-0 flex-col'
        : props.wachsen
          ? 'relative flex flex-col'
          : 'rounded-xl border border-(--color-border) bg-(--color-card) p-3'}
      style={props.wachsen && !bereit() ? { 'min-height': '12rem' } : undefined}
    >
      <Show when={props.titel}>
        <h2 class="mb-2 text-xs font-semibold tracking-wide text-(--color-fg-muted) uppercase">{props.titel}</h2>
      </Show>
      <Show when={fehler()}>
        <p
          class={glas()
            ? 'm-4 rounded-xl border border-(--color-warn)/40 bg-(--color-warn-soft) px-3.5 py-2.5 text-sm'
            : 'text-xs text-(--color-warn)'}
        >
          {fehler()}
        </p>
      </Show>
      <Show when={!bereit() && !fehler()}>
        <div
          role="status"
          aria-live="polite"
          class={glas()
            ? 'pointer-events-none absolute inset-0 z-[1] flex items-center justify-center gap-2.5 p-6 text-center text-sm text-(--color-fg-muted)'
            : 'mb-2 text-xs text-(--color-fg-muted)'}
        >
          {zuLang() ? (
            <span class="flex flex-col items-center">
              {props.titel ?? 'Die App'} konnte nicht geladen werden.
              <button
                type="button"
                class="pointer-events-auto mt-3 inline-flex min-h-8 items-center rounded-full border border-(--color-border) bg-(--color-card) px-3.5 text-(--color-fg) hover:bg-(--color-card-hover) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
                onClick={() => void laden()}
              >
                Erneut versuchen
              </button>
            </span>
          ) : (
            <>
              <span aria-hidden="true" class="inline-block size-3.5 animate-spin rounded-full border-2 border-(--color-fg-muted)/25 border-t-(--color-accent)" />
              <span>{props.titel ?? 'App'} wird geladen …</span>
            </>
          )}
        </div>
      </Show>
      <iframe
        ref={rahmen}
        title={props.titel ?? props.name}
        style={{
          width: '100%',
          height: props.fuellen ? '100%' : `${hoehe()}px`,
          flex: props.fuellen ? '1 1 0' : undefined,
          'min-height': props.fuellen ? '0' : undefined,
          border: '0',
          background: 'transparent',
          opacity: bereit() ? 1 : 0,
          transition: wenigBewegung() ? undefined : 'opacity 0.35s ease',
        }}
      />
    </section>
  );
}
