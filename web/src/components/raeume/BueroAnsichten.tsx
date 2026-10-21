/**
 * Native Ansichten im Raum Büro: Bestellungen aus `bestellungen.liste`, Serienmails aus `post.zustand` und der
 * Tagesbrief aus `brief.heute`. Die Werkzeuge liefern Plugins; sie haben keine eigene Hub-App, aber eine klare Antwort,
 * eine kleine Ansicht reicht (Vorbild MatrixVerlauf). Sie brauchen im Hub den Tag `flaeche`, sonst (oder wenn das Plugin
 * fehlt) steht „Noch nicht eingerichtet.“ da.
 */
import { For, Show, createResource, createSignal, type JSX } from 'solid-js';
import { NichtEingerichtet } from '~/components/raeume/Huelle';
import { agentName } from '~/lib/config';
import { hub } from '~/lib/hub';
import { gesperrt } from './freigabe';

// ── Bestellungen ────────────────────────────────────────────────────────────

export interface Bestellung {
  shop: string;
  status: string;
  betreff: string;
  datum: string;
  haendler?: string;
}
interface BestellungenAntwort {
  erreichbar?: boolean;
  eintraege?: Bestellung[];
  satz?: string;
  anzahl?: number;
}

/** Status aus dem Plugin, als Wort für Menschen; „kommt heute“ und „abholbereit“ fallen auf. */
export const STATUS_WORT: Record<string, string> = {
  bestellt: 'bestellt',
  versandt: 'unterwegs',
  kommt_heute: 'kommt heute',
  abholbereit: 'abholbereit',
  zugestellt: 'zugestellt',
  storniert: 'storniert',
  erstattet: 'erstattet',
  verkauft: 'verkauft',
  beleg: 'Beleg',
};
const AUFFAELLIG = new Set(['kommt_heute', 'abholbereit']);
export const ZEITRAEUME = [7, 30, 90] as const;

const tag = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });
};

function Freigabe(p: { werkzeug: string; wofuer: string }): JSX.Element {
  return (
    <NichtEingerichtet
      detail={`${p.wofuer}: Das Werkzeug ${p.werkzeug} fehlt im Hub oder ist für den Browser nicht freigegeben (Tag „flaeche“). Sobald ein Plugin es liefert, erscheint hier der Inhalt.`}
      data-buero-gesperrt={p.werkzeug}
    />
  );
}

export function Bestellungen(): JSX.Element {
  const [tage, setTage] = createSignal<number>(30);
  const [daten, { refetch }] = createResource(tage, (t) => hub<BestellungenAntwort>('bestellungen.liste', { tage: t }));
  // Eine fehlgeschlagene Ressource wirft beim Lesen: nur lesen, wenn es etwas gibt
  const wert = () => (daten.state === 'ready' || daten.state === 'refreshing' ? daten() : undefined);
  const liste = () => wert()?.eintraege ?? [];
  const zu = () => daten.state === 'errored' && gesperrt(daten.error);

  return (
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-5" data-bestellungen>
      <div class="flex flex-wrap items-baseline gap-3">
        <h1 class="m-0 flex-1 text-2xl font-bold text-(--color-fg)">Bestellungen</h1>
        <div class="flex items-center gap-1" role="group" aria-label="Zeitraum">
          <For each={ZEITRAEUME}>
            {(t) => (
              <button
                type="button"
                class="os-knopf h-8 px-3 text-xs"
                aria-pressed={tage() === t}
                classList={{ 'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)]': tage() === t }}
                onClick={() => setTage(t)}
              >
                {t} Tage
              </button>
            )}
          </For>
        </div>
        <button type="button" class="os-knopf" aria-label="Neu laden" title="Neu laden" onClick={() => void refetch()}>
          ↻
        </button>
      </div>
      <Show when={!zu()} fallback={<Freigabe werkzeug="bestellungen.liste" wofuer="Die Bestell-Liste" />}>
        <Show when={!daten.error} fallback={<p role="status" class="m-0 text-sm text-(--color-warn)">Die Bestellungen sind gerade nicht erreichbar.</p>}>
          <Show when={wert()} fallback={<p role="status" class="m-0 text-sm text-(--color-fg-muted)">Lese die Mails der letzten {tage()} Tage …</p>}>
            <p class="m-0 text-sm text-(--color-fg-muted)" role="status" data-bestellungen-satz>
              {wert()?.satz}
            </p>
            <Show when={liste().length}>
              <ol class="m-0 flex list-none flex-col divide-y divide-(--color-border) p-0">
                <For each={liste()}>
                  {(b) => (
                    <li class="flex items-start gap-3 py-2.5" data-bestellung={b.status}>
                      <span class="w-12 shrink-0 pt-0.5 text-xs text-(--color-fg-muted)">{tag(b.datum)}</span>
                      <span class="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span class="text-sm text-(--color-fg)">
                          <b class="font-semibold">{b.haendler ?? b.shop}</b>
                          <Show when={b.haendler}>
                            <span class="text-(--color-fg-muted)"> über {b.shop}</span>
                          </Show>
                        </span>
                        <span class="truncate text-xs text-(--color-fg-muted)">{b.betreff}</span>
                      </span>
                      <span
                        class="shrink-0 rounded-full border px-2 py-0.5 text-[11px]"
                        classList={{
                          'border-(--color-accent) text-(--color-accent)': AUFFAELLIG.has(b.status),
                          'border-(--color-border) text-(--color-fg-muted)': !AUFFAELLIG.has(b.status),
                        }}
                      >
                        {STATUS_WORT[b.status] ?? b.status}
                      </span>
                    </li>
                  )}
                </For>
              </ol>
            </Show>
          </Show>
        </Show>
      </Show>
      <p class="m-0 text-[11px] text-(--color-fg-muted)">Aus den Kopfzeilen der Mails zu Bestellungen. Nur lesen.</p>
    </div>
  );
}

// ── Serienmails ─────────────────────────────────────────────────────────────

export interface PostListe {
  id?: number;
  name: string;
  art?: string;
  abonnenten?: number;
}
export interface PostKampagne {
  id?: number;
  name: string;
  betreff?: string;
  status?: string;
  gesendet?: number | null;
  von?: number | null;
  angelegt?: string;
}
interface PostAntwort {
  quelle_ok?: boolean;
  listen?: PostListe[];
  kampagnen?: PostKampagne[];
  heute?: { gesendet?: number | null; grenze?: number };
  mitteilung_vorhanden?: boolean;
  link?: string;
  satz?: string;
}

/** Status der Kampagnen im Versanddienst, als Wort für Menschen. */
export const KAMPAGNE_STATUS: Record<string, string> = {
  draft: 'Entwurf',
  scheduled: 'geplant',
  running: 'läuft',
  paused: 'pausiert',
  cancelled: 'abgebrochen',
  finished: 'versendet',
};
const LISTEN_ART: Record<string, string> = { private: 'privat', public: 'öffentlich' };

export function Post(): JSX.Element {
  const [daten, { refetch }] = createResource(() => hub<PostAntwort>('post.zustand', {}));
  const wert = () => (daten.state === 'ready' || daten.state === 'refreshing' ? daten() : undefined);
  const zu = () => daten.state === 'errored' && gesperrt(daten.error);
  const ok = () => wert()?.quelle_ok === true;
  const link = () => {
    const l = wert()?.link;
    return l && l.startsWith('https://') ? l : undefined;
  };

  return (
    <div class="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-5" data-post>
      <div class="flex flex-wrap items-baseline gap-3">
        <h1 class="m-0 flex-1 text-2xl font-bold text-(--color-fg)">Serienmails</h1>
        <Show when={link()}>
          {(l) => (
            <a class="os-knopf h-8 px-3 text-xs" href={l()} target="_blank" rel="noopener noreferrer" data-post-link>
              Im Versanddienst öffnen
            </a>
          )}
        </Show>
        <button type="button" class="os-knopf" aria-label="Neu laden" title="Neu laden" onClick={() => void refetch()}>
          ↻
        </button>
      </div>
      <Show when={!zu()} fallback={<Freigabe werkzeug="post.zustand" wofuer="Der Zustand des Versanddienstes" />}>
        <Show when={!daten.error} fallback={<p role="status" class="m-0 text-sm text-(--color-warn)">Der Versanddienst ist gerade nicht erreichbar.</p>}>
          <Show when={wert()} fallback={<p role="status" class="m-0 text-sm text-(--color-fg-muted)">Frage den Versanddienst …</p>}>
            <p class="m-0 text-sm text-(--color-fg-muted)" role="status" data-post-satz classList={{ 'text-(--color-warn)': !ok() }}>
              {wert()?.satz}
            </p>
            <Show when={ok()}>
              <Show when={wert()?.heute?.gesendet != null}>
                <p class="m-0 text-sm text-(--color-fg)" data-post-heute>
                  Heute <b class="font-semibold">{wert()?.heute?.gesendet}</b> von {wert()?.heute?.grenze} Sendungen.
                </p>
              </Show>
              <section class="flex flex-col gap-1" aria-label="Listen" data-post-listen>
                <h2 class="m-0 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">Listen</h2>
                <ul class="m-0 flex list-none flex-col divide-y divide-(--color-border) p-0">
                  <For each={wert()?.listen ?? []} fallback={<li class="py-2 text-sm text-(--color-fg-muted)">Keine Listen.</li>}>
                    {(l) => (
                      <li class="flex items-baseline gap-3 py-2" data-post-liste>
                        <span class="min-w-0 flex-1 truncate text-sm text-(--color-fg)">{l.name}</span>
                        <span class="text-xs text-(--color-fg-muted)">{LISTEN_ART[l.art ?? ''] ?? l.art}</span>
                        <span class="w-24 shrink-0 text-right text-xs text-(--color-fg-muted)">
                          {l.abonnenten ?? 0} {l.abonnenten === 1 ? 'Abonnent' : 'Abonnenten'}
                        </span>
                      </li>
                    )}
                  </For>
                </ul>
              </section>
              <section class="flex flex-col gap-1" aria-label="Kampagnen" data-post-kampagnen>
                <h2 class="m-0 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">Letzte Kampagnen</h2>
                <ul class="m-0 flex list-none flex-col divide-y divide-(--color-border) p-0">
                  <For each={wert()?.kampagnen ?? []} fallback={<li class="py-2 text-sm text-(--color-fg-muted)">Noch keine Kampagne.</li>}>
                    {(k) => (
                      <li class="flex items-start gap-3 py-2.5" data-post-kampagne={k.status}>
                        <span class="flex min-w-0 flex-1 flex-col gap-0.5">
                          <span class="truncate text-sm text-(--color-fg)">{k.name}</span>
                          <Show when={k.betreff}>
                            <span class="truncate text-xs text-(--color-fg-muted)">{k.betreff}</span>
                          </Show>
                        </span>
                        <Show when={k.von}>
                          <span class="shrink-0 text-xs text-(--color-fg-muted)">
                            {k.gesendet ?? 0} von {k.von}
                          </span>
                        </Show>
                        <span class="shrink-0 rounded-full border border-(--color-border) px-2 py-0.5 text-[11px] text-(--color-fg-muted)">
                          {KAMPAGNE_STATUS[k.status ?? ''] ?? k.status}
                        </span>
                      </li>
                    )}
                  </For>
                </ul>
              </section>
            </Show>
          </Show>
        </Show>
      </Show>
      <p class="m-0 text-[11px] text-(--color-fg-muted)">Nur lesen, ohne Adressen. Kampagnen starten Menschen im Versanddienst selbst.</p>
    </div>
  );
}

// ── Tagesbrief ──────────────────────────────────────────────────────────────

export interface Abschnitt {
  titel: string;
  zeilen: string[];
}
interface BriefAntwort {
  satz?: string;
  abschnitte?: Abschnitt[];
  erzeugt?: string;
}

const ADRESSE = /(https?:\/\/\S+)/;

/** Eine Zeile des Briefs; eine Adresse darin wird ein Link (die Nachrichten tragen ihre Quelle so). */
export function zeile(text: string): JSX.Element {
  const teile = text.split(ADRESSE);
  return (
    <>
      <For each={teile}>
        {(t) =>
          ADRESSE.test(t) ? (
            <a href={t} target="_blank" rel="noreferrer" class="break-all text-(--color-accent) underline-offset-2 hover:underline">
              {t.replace(/^https?:\/\//, '').slice(0, 60)}
            </a>
          ) : (
            t
          )
        }
      </For>
    </>
  );
}

const uhrzeit = (iso?: string) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
};

export function Tagesbrief(): JSX.Element {
  const [daten, { refetch }] = createResource(() => hub<BriefAntwort>('brief.heute', {}, { zeitMs: 60_000 }));
  const wert = () => (daten.state === 'ready' || daten.state === 'refreshing' ? daten() : undefined);
  const zu = () => daten.state === 'errored' && gesperrt(daten.error);

  return (
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-5" data-tagesbrief>
      <div class="flex items-baseline gap-3">
        <h1 class="m-0 flex-1 text-2xl font-bold text-(--color-fg)">Tagesbrief</h1>
        <Show when={wert()?.erzeugt}>
          <span class="text-xs text-(--color-fg-muted)">Stand {uhrzeit(wert()?.erzeugt)}</span>
        </Show>
        <button type="button" class="os-knopf" aria-label="Neu bauen" title="Neu bauen" onClick={() => void refetch()}>
          ↻
        </button>
      </div>
      <Show when={!zu()} fallback={<Freigabe werkzeug="brief.heute" wofuer="Der Tagesbrief" />}>
        <Show when={!daten.error} fallback={<p role="status" class="m-0 text-sm text-(--color-warn)">Der Tagesbrief lässt sich gerade nicht bauen.</p>}>
          <Show when={wert()} fallback={<p role="status" class="m-0 text-sm text-(--color-fg-muted)">Baue den Brief aus den eingerichteten Quellen …</p>}>
            <p class="m-0 text-base text-(--color-fg)" data-tagesbrief-satz>
              {wert()?.satz}
            </p>
            <div class="grid grid-cols-[repeat(auto-fit,minmax(16rem,1fr))] gap-3">
              <For each={wert()?.abschnitte ?? []}>
                {(a) => (
                  <section class="flex flex-col gap-1.5 rounded-xl border border-(--color-border) p-3" aria-label={a.titel} data-tagesbrief-abschnitt={a.titel}>
                    <h2 class="m-0 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">{a.titel}</h2>
                    <ul class="m-0 flex list-none flex-col gap-1 p-0">
                      <For each={a.zeilen}>{(z) => <li class="text-sm leading-relaxed text-(--color-fg)">{zeile(z)}</li>}</For>
                    </ul>
                  </section>
                )}
              </For>
            </div>
          </Show>
        </Show>
      </Show>
      <p class="m-0 text-[11px] text-(--color-fg-muted)">Derselbe Brief, den {agentName()} morgens zustellt. Hier nur gebaut, nicht gesendet.</p>
    </div>
  );
}
