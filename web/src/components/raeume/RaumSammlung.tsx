/**
 * Raum Sammlung: alles, was entsteht, an einem Ort. Rechts die Typen, in der Mitte die gewählte Sicht.
 *
 * Die Sammlung ist eine Sicht über vorhandene Lese-Werkzeuge, kein neuer Speicher. „Zuletzt entstanden“ mischt die
 * gebauten Ansichten (gui.zeigen) und die Geschichten (geschichten.liste, wenn ein Plugin sie liefert); Dateien und
 * Dokumente kommen als ihre Apps. Was noch kein Flächen-Werkzeug hat, steht ehrlich als „geplant“ da. Fehlt eine Quelle,
 * zeigt die andere trotzdem ihre Stücke.
 */
import { For, Match, Show, Switch, createMemo, createResource, createSignal, type JSX } from 'solid-js';
import { type RaumProps, RaumRahmen } from '~/components/os/Raum';
import { Geplant, HubApp, NICHT_EINGERICHTET } from '~/components/raeume/Huelle';
import { gesperrt } from '~/components/raeume/freigabe';
import { hub } from '~/lib/hub';
import { imOsOeffnen } from '~/lib/os/oeffnen';
import { gebietsschema, tr, zahlFormat } from '~/lib/i18n';

type Art = { art: 'liste'; typ: StueckTyp | null } | { art: 'app'; name: string } | { art: 'geplant'; quelle: string };
interface Typ {
  id: string;
  titel: string;
  stichworte: string;
  inhalt: Art;
}

export type StueckTyp = 'ansicht' | 'geschichte';

export const TYPEN: readonly Typ[] = [
  { id: 'zuletzt', titel: 'Zuletzt entstanden', stichworte: 'alles neu neueste', inhalt: { art: 'liste', typ: null } },
  { id: 'ansichten', titel: 'Ansichten', stichworte: 'gui gebaut diagramm ansicht', inhalt: { art: 'liste', typ: 'ansicht' } },
  { id: 'geschichten', titel: 'Geschichten', stichworte: 'schreiben kapitel text', inhalt: { art: 'liste', typ: 'geschichte' } },
  { id: 'dateien', titel: 'Dateien', stichworte: 'ablage ordner datei pdf bild', inhalt: { art: 'app', name: 'dateien__liste' } },
  { id: 'dokumente', titel: 'Dokumente', stichworte: 'eingang brief scan', inhalt: { art: 'app', name: 'dokumente__eingang' } },
  { id: 'berichte', titel: 'Berichte', stichworte: 'wissen ablage bericht agent', inhalt: { art: 'geplant', quelle: 'abgelegte Berichte der Agenten; dafür fehlt noch ein Flächen-Werkzeug' } },
  { id: 'bilder', titel: 'Bilder', stichworte: 'fotos medien bild', inhalt: { art: 'geplant', quelle: 'erzeugte und abgelegte Bilder (Medien-Fläche, Raum Atelier)' } },
  { id: 'mappen', titel: 'Eigene Mappen', stichworte: 'mappe ordnen sammeln von wem', inhalt: { art: 'geplant', quelle: 'dem Register der Dinge (registriere_ding): jedes Stück mit Typ, Quelle, Ersteller, Zeit und Beleg' } },
];

export interface Stueck {
  typ: StueckTyp;
  id: string;
  titel: string;
  text: string;
  zeit: string;
}

interface Ansichten {
  ansichten?: { id: string; titel?: string; beschreibung?: string; angelegt?: string }[];
}
interface Geschichten {
  geschichten?: { id: string; titel?: string | null; geaendert?: string | null; woerter?: number; kapitel?: number; status?: string | null }[];
}

/** Ansichten und Geschichten zu einer Liste, neueste zuerst. */
export function stueckeAus(a: Ansichten | undefined, g: Geschichten | undefined): Stueck[] {
  const aus: Stueck[] = [];
  for (const v of a?.ansichten ?? []) {
    aus.push({ typ: 'ansicht', id: v.id, titel: v.titel || tr('Ansicht ohne Titel'), text: v.beschreibung ?? '', zeit: v.angelegt ?? '' });
  }
  for (const s of g?.geschichten ?? []) {
    const teile = [s.kapitel ? tr('{0} Kapitel', s.kapitel) : '', s.woerter ? tr('{0} Wörter', zahlFormat(s.woerter)) : '', s.status ?? ''].filter(Boolean);
    aus.push({ typ: 'geschichte', id: s.id, titel: s.titel || tr('Geschichte ohne Titel'), text: teile.join(' · '), zeit: s.geaendert ?? '' });
  }
  return aus.sort((x, y) => (y.zeit || '').localeCompare(x.zeit || ''));
}

/** Nach Typ und Suchwörtern (alle müssen in Titel oder Text vorkommen) filtern. */
export function filtere(liste: readonly Stueck[], typ: StueckTyp | null, q: string): Stueck[] {
  const woerter = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return liste.filter((s) => (!typ || s.typ === typ) && woerter.every((w) => `${s.titel} ${s.text}`.toLowerCase().includes(w)));
}

const TYP_NAME: Record<StueckTyp, string> = { ansicht: 'Ansicht', geschichte: 'Geschichte' };

function zeitText(iso: string): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(gebietsschema(), { day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
}

const SCHLUESSEL = 'fyos.raum.sammlung';

function gemerkt(): { typ: string; raster: boolean } {
  try {
    const roh = JSON.parse(localStorage.getItem(SCHLUESSEL) ?? '{}') as { typ?: string; raster?: boolean };
    return { typ: TYPEN.some((t) => t.id === roh.typ) ? roh.typ! : 'zuletzt', raster: roh.raster !== false };
  } catch {
    return { typ: 'zuletzt', raster: true };
  }
}

/** Eine Quelle laden: Antwort, `null` (Fehler) oder `gesperrt` (Werkzeug fehlt oder nicht freigegeben). */
type Quelle<T> = { daten: T } | { fehler: 'gesperrt' | 'aus' };
const quelleHolen = <T,>(tool: string): Promise<Quelle<T>> =>
  hub<T>(tool, {}).then(
    (daten): Quelle<T> => ({ daten }),
    (e: unknown): Quelle<T> => ({ fehler: gesperrt(e) ? 'gesperrt' : 'aus' }),
  );

export default function RaumSammlung(p: RaumProps): JSX.Element {
  const start = gemerkt();
  const [typ, setTyp] = createSignal(start.typ);
  const [raster, setRaster] = createSignal(start.raster);
  const [suche, setSuche] = createSignal('');
  const merken = () => {
    try {
      localStorage.setItem(SCHLUESSEL, JSON.stringify({ typ: typ(), raster: raster() }));
    } catch {
      /* gilt dann nur bis zum Schließen */
    }
  };
  const waehle = (id: string) => {
    setTyp(id);
    merken();
  };

  const aktuell = () => TYPEN.find((t) => t.id === typ()) ?? TYPEN[0]!;
  const istListe = () => aktuell().inhalt.art === 'liste';

  // Beide Quellen unabhängig: fällt eine aus, zeigt die andere trotzdem ihre Stücke.
  const [ansichten] = createResource(() => quelleHolen<Ansichten>('gui.zeigen'));
  const [geschichten] = createResource(() => quelleHolen<Geschichten>('geschichten.liste'));
  const laedt = () => ansichten.loading || geschichten.loading;
  const daten = <T,>(q: Quelle<T> | undefined): T | undefined => (q && 'daten' in q ? q.daten : undefined);
  const alle = createMemo(() => stueckeAus(daten(ansichten()), daten(geschichten())));
  const fehler = (q: Quelle<unknown> | undefined) => (q && 'fehler' in q ? q.fehler : undefined);
  // Nicht erreichbar ist eine Quelle, die ausfiel; gesperrt (Werkzeug fehlt) heißt nur: nicht eingerichtet
  const ausgefallen = () => [fehler(ansichten()) === 'aus' ? tr('Ansichten') : '', fehler(geschichten()) === 'aus' ? tr('Geschichten') : ''].filter(Boolean);
  const keineQuelle = () => !laedt() && !!fehler(ansichten()) && !!fehler(geschichten());
  const sichtbar = createMemo(() => {
    const i = aktuell().inhalt;
    return filtere(alle(), i.art === 'liste' ? i.typ : null, suche());
  });

  const zaehle = (t: StueckTyp | null) => alle().filter((s) => !t || s.typ === t).length;

  const oeffneStueck = (s: Stueck) => {
    const ziel = s.typ === 'ansicht' ? 'app:gui__zeigen' : 'app:geschichten__liste';
    if (!imOsOeffnen({ ziel, eingabe: { id: s.id }, vorn: true })) p.oeffne(ziel);
  };

  const leiste = (
    <>
      <input
        type="search"
        aria-label={tr('In der Sammlung suchen')}
        placeholder={tr('In der Sammlung suchen')}
        value={suche()}
        onInput={(e) => {
          setSuche(e.currentTarget.value);
          if (!istListe()) waehle('zuletzt');
        }}
        class="mb-2 h-9 w-full rounded-[10px] border border-(--color-border) bg-[color-mix(in_oklab,var(--color-fg)_5%,transparent)] px-3 text-sm text-(--color-fg) placeholder:text-(--color-fg-muted) focus-visible:outline-2 focus-visible:outline-(--color-accent)"
        classList={{ 'max-w-xs': p.schmal }}
      />
      <Show when={!p.schmal}>
        <span class="px-2.5 pt-1 pb-2 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">{tr('Typen')}</span>
      </Show>
      <ul class="m-0 flex list-none gap-0.5 p-0" classList={{ 'flex-col': !p.schmal, 'flex-row whitespace-nowrap': p.schmal }}>
        <For each={TYPEN}>
          {(t) => (
            <li>
              <button
                type="button"
                data-typ={t.id}
                aria-current={t.id === typ() ? 'page' : undefined}
                onClick={() => waehle(t.id)}
                class="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-2 text-left text-[0.85rem] transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-(--color-accent)"
                classList={{
                  'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)': t.id === typ(),
                  'text-(--color-fg-muted) hover:bg-[color-mix(in_oklab,var(--color-fg)_7%,transparent)] hover:text-(--color-fg)': t.id !== typ(),
                }}
              >
                <span class="flex-1">{t.titel}</span>
                <Switch>
                  <Match when={t.inhalt.art === 'geplant'}>
                    <span class="text-[11px] text-(--color-fg-muted)">geplant</span>
                  </Match>
                  <Match when={t.inhalt.art === 'liste' && !laedt()}>
                    <span class="text-[11px] text-(--color-fg-muted) tabular-nums">{zaehle((t.inhalt as { typ: StueckTyp | null }).typ)}</span>
                  </Match>
                </Switch>
              </button>
            </li>
          )}
        </For>
      </ul>
      <Show when={!p.schmal}>
        <span class="px-2.5 pt-4 pb-1 text-[11px] font-semibold tracking-[0.08em] text-(--color-fg-muted) uppercase">{tr('Von wem')}</span>
        <p class="m-0 px-2.5 text-xs leading-relaxed text-(--color-fg-muted)">{tr('Geplant: Wer ein Stück gemacht hat (Mensch oder Agent), kommt mit dem Register der Dinge.')}</p>
      </Show>
    </>
  );

  return (
    <RaumRahmen titel={tr('Sammlung')} leiste={leiste} leisteName={tr('Typen der Sammlung')} schmal={p.schmal} heim={p.heim} fuellen={aktuell().inhalt.art === 'app'}>
      <div class="mx-auto flex w-full max-w-5xl min-h-0 flex-1 flex-col gap-4 px-4 py-5" data-sammlung-typ={aktuell().id}>
        <div class="flex items-center gap-3">
          <h1 class="m-0 flex-1 text-2xl font-bold text-(--color-fg)">{aktuell().titel}</h1>
          <Show when={istListe()}>
            <div class="flex gap-0.5 rounded-[10px] border border-(--color-border) p-0.5" role="group" aria-label={tr('Darstellung')}>
              <For each={[{ wert: true, name: 'Raster' }, { wert: false, name: 'Liste' }]}>
                {(o) => (
                  <button
                    type="button"
                    aria-pressed={raster() === o.wert}
                    onClick={() => {
                      setRaster(o.wert);
                      merken();
                    }}
                    class="rounded-[8px] px-3 py-1 text-[0.8rem] transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-(--color-accent)"
                    classList={{
                      'bg-[color-mix(in_oklab,var(--color-fg)_16%,transparent)] text-(--color-fg)': raster() === o.wert,
                      'text-(--color-fg-muted) hover:text-(--color-fg)': raster() !== o.wert,
                    }}
                  >
                    {o.name}
                  </button>
                )}
              </For>
            </div>
          </Show>
        </div>
        <Switch>
          <Match when={istListe()}>
            <Show when={keineQuelle() && !ausgefallen().length}>
              <p class="m-0 text-sm text-(--color-fg-muted)" role="status" data-nicht-eingerichtet>{NICHT_EINGERICHTET}</p>
            </Show>
            <Show when={ausgefallen().length && !laedt()}>
              <p class="m-0 text-sm text-(--color-fg-muted)" role="status">{tr('Nicht erreichbar:')}{' '}{ausgefallen().join(', ')}.</p>
            </Show>
            <Show when={!laedt()} fallback={<p class="m-0 text-sm text-(--color-fg-muted)">{tr('Lädt …')}</p>}>
              <Show
                when={sichtbar().length}
                fallback={
                  <Show when={!keineQuelle()}>
                    <p class="m-0 text-sm text-(--color-fg-muted)">{suche().trim() ? tr('Nichts passt zur Suche.') : tr('Hier ist noch nichts entstanden.')}</p>
                  </Show>
                }
              >
                <ul
                  class="m-0 list-none p-0"
                  classList={{ 'grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3': raster(), 'flex flex-col gap-1': !raster() }}
                  data-sammlung-liste
                >
                  <For each={sichtbar()}>
                    {(s) => (
                      <li>
                        <button
                          type="button"
                          data-stueck={`${s.typ}:${s.id}`}
                          onClick={() => oeffneStueck(s)}
                          class="flex w-full flex-col gap-1 rounded-[12px] border border-(--color-border) text-left transition-colors duration-150 hover:bg-[color-mix(in_oklab,var(--color-fg)_6%,transparent)] focus-visible:outline-2 focus-visible:outline-(--color-accent)"
                          classList={{ 'h-full p-3.5': raster(), 'px-3 py-2': !raster() }}
                        >
                          <span class="flex items-center gap-2 text-[11px] text-(--color-fg-muted)">
                            <span class="font-semibold tracking-[0.06em] uppercase">{TYP_NAME[s.typ]}</span>
                            <span class="ml-auto tabular-nums">{zeitText(s.zeit)}</span>
                          </span>
                          <span class="text-[0.95rem] font-semibold text-(--color-fg)">{s.titel}</span>
                          <Show when={s.text}>
                            <span class="text-[0.8rem] text-(--color-fg-muted)" classList={{ 'line-clamp-3': raster(), truncate: !raster() }}>{s.text}</span>
                          </Show>
                        </button>
                      </li>
                    )}
                  </For>
                </ul>
              </Show>
            </Show>
          </Match>
          {/* keyed: HubApp liest den Namen nur beim Einhängen, ohne keyed bliebe beim Wechsel zwischen zwei Apps die erste stehen */}
          <Match when={aktuell().inhalt.art === 'app' && aktuell().inhalt} keyed>
            {(a) => (
              <div class="flex min-h-0 flex-1 flex-col">
                <HubApp name={(a as { name: string }).name} titel={aktuell().titel} fuellen schluessel={`raum-sammlung:${aktuell().id}`} />
              </div>
            )}
          </Match>
          <Match when={aktuell().inhalt.art === 'geplant' && aktuell().inhalt}>
            {(g) => <Geplant quelle={(g() as { quelle: string }).quelle} />}
          </Match>
        </Switch>
      </div>
    </RaumRahmen>
  );
}
