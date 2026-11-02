/**
 * Einstellungen › Meldungen (28.10.2026): je Quelle an/aus, Mail-Ordner, Systemmitteilungen, „Nicht stören“ mit Zeitfenster, Ruhe von Agent.
 * Gilt in diesem Browser bzw. dieser Hülle (localStorage `fyos:os:meldungen`). Logik: lib/os/meldungen-einstellungen.ts.
 */
import { For, Show, createSignal, type JSX } from 'solid-js';
import { QUELLEN, QUELLEN_NAME, type MeldungenEinstellungen, type Quelle } from '~/lib/os/meldungen-einstellungen';
import { aendereEinstellungen, dienst, einstellungen, ruht, system } from '~/lib/os/meldungen-produktiv';
import { kannErlaubnisAnfragen, umgebungLesen, waehleBruecke } from '~/lib/os/meldungen-system';
import { KNOPF, SchalterZeile, Zeile } from './bausteine';
import { tr } from '~/lib/i18n';

const QUELLEN_UNTER: Record<Quelle, string> = {
  agent: 'Neue Antworten von Agent, solange ihr Fenster nicht vorn ist.',
  freigabe: 'Neue offene Freigaben des Runners. Hohes Risiko bleibt stehen, bis du es bestätigst.',
  stoerung: 'Störungen aus dem Bus (Knoten, Dienste, Cluster). Bleiben stehen, bis du sie bestätigst.',
  termin: 'Termine, zehn Minuten vorher und wenn sie beginnen.',
  mail: 'Neue ungelesene Mails: Absender und Betreff, nie ein Textauszug.',
};

const MAIL_ORDNER: ReadonlyArray<{ id: string; name: string }> = [
  { id: 'INBOX', name: 'Posteingang' },
  { id: 'IMPORTANT', name: 'Wichtig' },
  { id: 'STARRED', name: 'Markiert' },
];

function aendern(f: (e: MeldungenEinstellungen) => MeldungenEinstellungen): void {
  aendereEinstellungen(f);
}

export default function MeldungenEinstellen(): JSX.Element {
  const e = einstellungen;
  const [antwort, setAntwort] = createSignal('');
  const weg = () => waehleBruecke(umgebungLesen());
  const wegText = () => {
    const u = umgebungLesen();
    if (u.huelle) return 'Über die Desktop-App (Mitteilungszentrale des Systems).';
    if (!u.notification) return 'Dieser Browser kennt keine Systemmitteilungen; es bleibt bei Toasts und Glocke.';
    if (u.notification.permission === 'granted') return 'Über den Browser (Erlaubnis erteilt).';
    if (u.notification.permission === 'denied') return 'Der Browser hat Mitteilungen für diese Seite abgelehnt; in den Seiteneinstellungen des Browsers wieder erlauben.';
    return 'Der Browser hat noch nicht gefragt. Mit dem Knopf unten erlaubst du Mitteilungen.';
  };
  const ordnerSchalten = (id: string) =>
    aendern((x) => {
      const hat = x.mailOrdner.includes(id);
      const neu = hat ? x.mailOrdner.filter((o) => o !== id) : [...x.mailOrdner, id];
      return { ...x, mailOrdner: neu.length ? neu : x.mailOrdner };
    });

  return (
    <div data-meldungen-einstellen>
      <For each={QUELLEN}>
        {(q) => (
          <SchalterZeile
            name={QUELLEN_NAME[q]}
            unter={QUELLEN_UNTER[q]}
            an={e().quellen[q]}
            onKlick={() => aendern((x) => ({ ...x, quellen: { ...x.quellen, [q]: !x.quellen[q] } }))}
          />
        )}
      </For>
      <Show when={e().quellen.mail}>
        <Zeile titel={tr('Mail-Ordner')} unter={tr('Aus welchen Ordnern neue Mails gemeldet werden (mindestens einer).')} darunter>
          <div class="flex flex-wrap gap-3" role="group" aria-label={tr('Mail-Ordner')}>
            <For each={MAIL_ORDNER}>
              {(o) => (
                <label class="inline-flex min-h-11 items-center gap-2 text-sm md:min-h-8">
                  <input type="checkbox" checked={e().mailOrdner.includes(o.id)} onChange={() => ordnerSchalten(o.id)} />
                  {o.name}
                </label>
              )}
            </For>
          </div>
        </Zeile>
      </Show>

      <SchalterZeile
        name="Systemmitteilungen"
        unter={tr('Wenn FYOS OS im Hintergrund ist, zeigt auch das System eine Mitteilung (ab „normal“). {0}', wegText())}
        an={e().system}
        onKlick={() => aendern((x) => ({ ...x, system: !x.system }))}
      />
      <SchalterZeile
        name={tr('Absender und Betreff in Systemmitteilungen zeigen')}
        unter={tr('Aus (Vorgabe): Das System zeigt nur „Neue Mail“ bzw. „Agent hat geschrieben“, auch auf dem Sperrbildschirm. Die Toasts im OS zeigen weiter Absender, Betreff und einen kurzen Auszug von des Agenten Nachricht, nie einen Mailtext.')}
        an={e().systemDetails}
        onKlick={() => aendern((x) => ({ ...x, systemDetails: !x.systemDetails }))}
      />
      <Show when={kannErlaubnisAnfragen(umgebungLesen())}>
        <Zeile titel="Browser-Erlaubnis" unter={tr('Der Browser fragt erst, wenn du hier klickst.')}>
          <button type="button" class={KNOPF} onClick={() => void system.erlaubnisAnfragen().then((r) => setAntwort(r))}>
            {tr('Mitteilungen erlauben')}
          </button>
          <Show when={antwort()}>
            <p role="status" class="m-0 mt-1 text-xs text-(--color-fg-muted)">{tr('Antwort des Browsers:')}{' '}{antwort()}</p>
          </Show>
        </Zeile>
      </Show>
      <Zeile titel={tr('Probe')} unter={weg() === 'keine' ? tr('Zeigt eine Test-Meldung im OS (ohne Systemmitteilung, solange keine Brücke da ist).') : tr('Zeigt eine Test-Meldung; liegt das Fenster im Hintergrund, kommt auch eine Systemmitteilung.')}>
        <button
          type="button"
          class={KNOPF}
          onClick={() =>
            dienst.melde({ quelle: 'agent', schluessel: `probe-${Date.now()}`, stufe: 'normal', titel: 'FYOS OS Test', text: 'So sieht eine Meldung aus.' })
          }
        >
          {tr('Test-Meldung zeigen')}
        </button>
      </Zeile>

      <SchalterZeile
        name="Nicht stören"
        unter={tr('Meldungen landen nur im Verlauf (Glocke), ohne Toast und ohne Systemmitteilung.')}
        an={e().nichtStoeren.manuell}
        onKlick={() => aendern((x) => ({ ...x, nichtStoeren: { ...x.nichtStoeren, manuell: !x.nichtStoeren.manuell } }))}
      />
      <SchalterZeile
        name={tr('Nicht stören nach Uhrzeit')}
        unter={tr('Jeden Tag im Zeitfenster.')}
        an={e().nichtStoeren.zeit}
        onKlick={() => aendern((x) => ({ ...x, nichtStoeren: { ...x.nichtStoeren, zeit: !x.nichtStoeren.zeit } }))}
      />
      <Show when={e().nichtStoeren.zeit}>
        <Zeile titel={tr('Zeitfenster')} unter={tr('Auch über Mitternacht (22:00 bis 07:00).')} darunter>
          <div class="flex flex-wrap items-center gap-3 text-sm">
            <label class="inline-flex items-center gap-2">
              {tr('von')}
              <input type="time" value={e().nichtStoeren.von} class="min-h-9 rounded-lg border border-(--color-border) bg-transparent px-2" onChange={(ev) => aendern((x) => ({ ...x, nichtStoeren: { ...x.nichtStoeren, von: ev.currentTarget.value || x.nichtStoeren.von } }))} />
            </label>
            <label class="inline-flex items-center gap-2">
              {tr('bis')}
              <input type="time" value={e().nichtStoeren.bis} class="min-h-9 rounded-lg border border-(--color-border) bg-transparent px-2" onChange={(ev) => aendern((x) => ({ ...x, nichtStoeren: { ...x.nichtStoeren, bis: ev.currentTarget.value || x.nichtStoeren.bis } }))} />
            </label>
          </div>
        </Zeile>
      </Show>
      <SchalterZeile
        name={tr('Kritisches durchbricht')}
        unter={tr('Störungen und Freigaben mit hohem Risiko kommen auch bei „Nicht stören“ durch.')}
        an={e().nichtStoeren.kritischDurchbrechen}
        onKlick={() => aendern((x) => ({ ...x, nichtStoeren: { ...x.nichtStoeren, kritischDurchbrechen: !x.nichtStoeren.kritischDurchbrechen } }))}
      />
      <SchalterZeile
        name={tr('Ruhe von Agent beachten')}
        unter={tr('Ruht Agent (Ruhe-Schalter oder Spielmodus), gilt das wie „Nicht stören“. Der Schalter wird nur gelesen. Jetzt: {0}.', ruht() ? tr('Agent ruht') : 'keine Ruhe')}
        an={e().ruheBeachten}
        onKlick={() => aendern((x) => ({ ...x, ruheBeachten: !x.ruheBeachten }))}
      />
    </div>
  );
}
