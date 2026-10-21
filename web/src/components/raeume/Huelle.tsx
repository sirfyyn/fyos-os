/**
 * Gemeinsame Bausteine der Raum-Hüllen: Leiste mit Einträgen, eine Hub-App in der Mitte, eine Seite, die ein Plugin
 * registriert hat, und der ehrliche Satz, wenn nichts da ist.
 *
 * Grundsatz: Ein Raum zeigt nur, was eingerichtete Plugins liefern. Fehlt das Plugin (das Werkzeug ist im Hub nicht
 * bekannt, der Hub antwortet nicht, die Seite ist nicht registriert), steht „Noch nicht eingerichtet.“ da und der Raum
 * bleibt benutzbar.
 */
import { For, Show, createResource, splitProps, type JSX } from 'solid-js';
import AppEingebettet from '~/components/apps/AppEingebettet';
import { Laedt } from '~/components/einstellungen/bausteine';
import { Inhalt as SeitenInhalt } from '~/components/os/Fenster';
import { apps } from '~/lib/mcp-apps/host';
import { registrierteFlaechen } from '~/lib/os/register';

export const NICHT_EINGERICHTET = 'Noch nicht eingerichtet.';

/** Der Satz für alles, was kein eingerichtetes Plugin liefert; `detail` sagt, was fehlt. */
export function NichtEingerichtet(p: { detail?: string } & JSX.HTMLAttributes<HTMLDivElement>): JSX.Element {
  const [eigen, rest] = splitProps(p, ['detail', 'class']);
  return (
    <div class={`m-auto flex max-w-prose flex-col gap-1 px-4 py-6 text-center ${eigen.class ?? ''}`} role="status" data-nicht-eingerichtet {...rest}>
      <p class="m-0 text-sm text-(--color-fg)">{NICHT_EINGERICHTET}</p>
      <Show when={eigen.detail}>
        <p class="m-0 text-xs leading-relaxed text-(--color-fg-muted)">{eigen.detail}</p>
      </Show>
    </div>
  );
}

/** Ein Bereich, für den es noch keine Fläche gibt: sagt, woraus er kommen wird. */
export function Geplant(p: { titel?: string; quelle: string }): JSX.Element {
  return (
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-3">
      <Show when={p.titel}>
        <h1 class="m-0 text-2xl font-bold text-(--color-fg)">{p.titel}</h1>
      </Show>
      <p class="m-0 max-w-prose text-sm leading-relaxed text-(--color-fg-muted)">Noch nicht gebaut. Hier kommt zusammen: {p.quelle}.</p>
    </div>
  );
}

/**
 * Eine Hub-App als Mitte des Raums. `name` ist der Werkzeugname (`<plugin>__<werkzeug>`); `oder` ein zweiter Name, der
 * gilt, wenn der erste im Hub fehlt. Gibt es keinen von beiden, steht „Noch nicht eingerichtet.“ da.
 */
export function HubApp(p: {
  name: string;
  oder?: string;
  titel: string;
  schluessel: string;
  ohneKopf?: boolean;
  fuellen?: boolean;
}): JSX.Element {
  const [liste] = createResource(
    () => [p.name, p.oder] as const,
    async ([name, oder]): Promise<{ gefunden?: string } | null> => {
      try {
        const alle = await apps(true);
        const treffer = alle.find((a) => a.name === name) ?? (oder ? alle.find((a) => a.name === oder) : undefined);
        return { gefunden: treffer?.name };
      } catch {
        return null;
      }
    },
  );
  return (
    <Show when={!liste.loading || liste.latest} fallback={<div class="m-auto"><Laedt /></div>}>
      <Show
        when={liste.latest?.gefunden}
        keyed
        fallback={
          <NichtEingerichtet
            detail={
              liste.latest === null
                ? 'Der Hub antwortet gerade nicht.'
                : `${p.titel}: Im Hub fehlt das Werkzeug ${p.name}${p.oder ? ` (oder ${p.oder})` : ''}.`
            }
          />
        }
      >
        {(n) => <AppEingebettet name={n} titel={p.titel} ohneKopf={p.ohneKopf} fuellen={p.fuellen} schluessel={p.schluessel} />}
      </Show>
    </Show>
  );
}

/** Eine Seite, die ein Plugin über `registriereFlaechen` eingebracht hat (`art: 'seite'` mit `pfad`), fest im Raum. */
export function SeitenFlaeche(p: { id: string; oeffne: (id: string) => void; schmal: boolean }): JSX.Element {
  const flaeche = () => registrierteFlaechen().find((f) => f.id === p.id && f.art === 'seite' && !!f.pfad);
  return (
    <Show when={flaeche()} keyed fallback={<NichtEingerichtet detail={`Die Seite ${p.id} bringt ein Plugin mit (registriereFlaechen).`} />}>
      {(f) => (
        <div class="relative min-h-0 flex-1">
          <SeitenInhalt f={f} ziehen={false} oeffne={p.oeffne} schmal={p.schmal} fest />
        </div>
      )}
    </Show>
  );
}

export interface LeistenEintrag {
  id: string;
  titel: string;
  /** Eine Zeile unter dem Titel in der Leiste */
  zeile: string;
  gruppe: string;
  /** Hinweis „geplant“ neben dem Titel */
  geplant?: boolean;
}

/**
 * Die Leiste eines Raums: Einträge nach Gruppen, im schmalen Fenster eine Reihe. Jeder Knopf trägt `data-<kennung>="<id>"`,
 * jede Gruppe `data-<kennung>-gruppe="<Name>"`.
 */
export function EintragLeiste(p: {
  eintraege: readonly LeistenEintrag[];
  gruppen: readonly string[];
  gewaehlt: string;
  waehle: (id: string) => void;
  schmal: boolean;
  kennung: string;
}): JSX.Element {
  const knopf = (e: LeistenEintrag) => (
    <button
      type="button"
      {...{ [`data-${p.kennung}`]: e.id }}
      aria-current={e.id === p.gewaehlt ? 'page' : undefined}
      onClick={() => p.waehle(e.id)}
      class="flex w-full flex-col items-start rounded-[9px] px-2.5 py-2 text-left transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-(--color-accent)"
      classList={{
        'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)': e.id === p.gewaehlt,
        'text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] hover:text-(--color-fg)': e.id !== p.gewaehlt,
      }}
    >
      <span class="flex w-full items-center gap-2 text-[0.85rem]">
        <span class="flex-1 truncate">{e.titel}</span>
        <Show when={e.geplant}>
          <span class="text-[11px] text-(--color-fg-muted)">geplant</span>
        </Show>
      </span>
      <Show when={!p.schmal}>
        <span class="truncate text-[11px] text-(--color-fg-muted)">{e.zeile}</span>
      </Show>
    </button>
  );
  return (
    <Show
      when={!p.schmal}
      fallback={
        <ul class="m-0 flex list-none flex-row gap-0.5 p-0 whitespace-nowrap">
          <For each={p.eintraege}>{(e) => <li>{knopf(e)}</li>}</For>
        </ul>
      }
    >
      <For each={p.gruppen}>
        {(g) => (
          <section aria-label={g} class="mb-3 flex flex-col gap-0.5" {...{ [`data-${p.kennung}-gruppe`]: g }}>
            <span class="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">{g}</span>
            <ul class="m-0 flex list-none flex-col gap-0.5 p-0">
              <For each={p.eintraege.filter((e) => e.gruppe === g)}>{(e) => <li>{knopf(e)}</li>}</For>
            </ul>
          </section>
        )}
      </For>
    </Show>
  );
}

/** Gemerkte Wahl eines Raums (Eintrag oder Bereich) aus dem Browser; ohne Speicher oder bei Unbekanntem `vorgabe`. */
export function gemerkteWahl(schluessel: string, gueltig: (id: string) => boolean, vorgabe: string): string {
  try {
    const id = localStorage.getItem(schluessel);
    if (id && gueltig(id)) return id;
  } catch {
    /* ohne Speicher: Vorgabe */
  }
  return vorgabe;
}

export function wahlMerken(schluessel: string, id: string): void {
  try {
    localStorage.setItem(schluessel, id);
  } catch {
    /* gilt dann nur bis zum Schließen */
  }
}
