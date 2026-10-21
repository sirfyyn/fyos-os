/**
 * Raum Büro (components/raeume/RaumBuero.tsx): Leiste nach Thema (Post, Zeit, Geld), kompakte Hub-Apps als Apps, die
 * großen Seiten nur, wenn ein Plugin sie registriert hat; fehlt etwas, steht „Noch nicht eingerichtet.“ da.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@solidjs/testing-library';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '~/lib/api/client';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';

const hub = vi.hoisted(() => ({ namen: [] as string[] }));
vi.mock('~/lib/mcp-apps/host', () => ({ apps: async () => hub.namen.map((name) => ({ name })) }));
vi.mock('~/components/apps/AppEingebettet', () => ({
  default: (p: { name: string }) => {
    const name = p.name;
    return <div data-testid="app" data-name={name} />;
  },
}));
const hubMock = vi.fn();
vi.mock('~/lib/hub', () => ({ hub: (...a: unknown[]) => hubMock(...a) }));
vi.mock('~/components/os/Fenster', () => ({
  Inhalt: (p: { f: { id: string; pfad?: string } }) => {
    const f = p.f;
    return <div data-testid="seite" data-id={f.id} data-pfad={f.pfad} />;
  },
}));

import RaumBuero, { EINTRAEGE } from '~/components/raeume/RaumBuero';

const seite = (slug: string, titel: string) => ({ id: `seite:${slug}`, titel, gruppe: 'Test', art: 'seite' as const, kuerzel: titel.slice(0, 2), pfad: `/${slug}/` });

beforeEach(() => {
  localStorage.clear();
  hubMock.mockReset();
  hubMock.mockResolvedValue({});
  hub.namen = ['posteingang__zeigen', 'termine__zeigen', 'dokumente__eingang'];
  registerZuruecksetzen();
  registriereFlaechen({ flaechen: [seite('kalender', 'Kalender'), seite('finanzen', 'Finanzen'), seite('dokumente', 'Dokumente')] });
});
afterEach(() => {
  cleanup();
  registerZuruecksetzen();
});

const zeigen = (schmal = false) => render(() => <RaumBuero oeffne={vi.fn()} schmal={schmal} heim={vi.fn()} />);
const knopf = (id: string) => document.querySelector(`[data-buero="${id}"]`) as HTMLButtonElement;

describe('Raum Büro', () => {
  it('gliedert nach Post, Zeit, Geld und beginnt mit der Mail', async () => {
    zeigen();
    expect([...document.querySelectorAll('[data-buero-gruppe]')].map((g) => g.getAttribute('data-buero-gruppe'))).toEqual(['Post', 'Zeit', 'Geld']);
    expect((await screen.findByTestId('app')).dataset.name).toBe('posteingang__zeigen');
  });

  it('wechselt zwischen Apps und Seiten, ohne die vorige stehen zu lassen', async () => {
    zeigen();
    fireEvent.click(knopf('termine'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('termine__zeigen'));
    fireEvent.click(knopf('kalender'));
    expect(screen.queryByTestId('app')).toBeNull();
    expect(screen.getByTestId('seite').dataset.id).toBe('seite:kalender');
    fireEvent.click(knopf('finanzen'));
    expect(screen.getByTestId('seite').dataset.id).toBe('seite:finanzen');
    fireEvent.click(knopf('eingang'));
    await waitFor(() => expect(screen.getByTestId('app').dataset.name).toBe('dokumente__eingang'));
  });

  it('jede Seite des Büros zeigt sich, sobald ein Plugin sie registriert hat', () => {
    zeigen();
    for (const e of EINTRAEGE.filter((x) => x.inhalt.art === 'seite')) {
      fireEvent.click(knopf(e.id));
      expect(screen.getByTestId('seite').dataset.pfad, e.id).toBeTruthy();
    }
  });

  it('eine Seite, die kein Plugin registriert hat, sagt „Noch nicht eingerichtet.“', () => {
    registerZuruecksetzen();
    zeigen();
    fireEvent.click(knopf('kalender'));
    expect(screen.queryByTestId('seite')).toBeNull();
    expect(document.querySelector('[data-buero-mitte="kalender"] [data-nicht-eingerichtet]')!.textContent).toContain('Noch nicht eingerichtet.');
  });

  it('eine App, die der Hub nicht kennt, sagt „Noch nicht eingerichtet.“', async () => {
    hub.namen = [];
    zeigen();
    await waitFor(() => expect(document.querySelector('[data-buero-mitte="mail"] [data-nicht-eingerichtet]')).toBeTruthy());
  });

  it('merkt sich die Wahl; im Büro ist nichts bloß geplant', () => {
    zeigen();
    fireEvent.click(knopf('kampagnen'));
    expect(document.querySelector('[data-buero-mitte="kampagnen"]')).toBeTruthy();
    expect(localStorage.getItem('fyos.raum.buero')).toBe('kampagnen');
    expect(EINTRAEGE.filter((e) => e.inhalt.art === 'geplant')).toEqual([]);
  });

  it('Serienmails: Listen, letzte Kampagnen und Sendungen heute aus post.zustand, Link nur über https', async () => {
    hubMock.mockImplementation((tool: string) =>
      Promise.resolve(
        tool === 'post.zustand'
          ? {
              quelle_ok: true,
              satz: 'Der Versanddienst antwortet: 1 Liste mit zusammen 1 Abonnent, 1 Kampagne.',
              listen: [{ id: 3, name: 'Intern', art: 'private', abonnenten: 1 }],
              kampagnen: [{ id: 9, name: 'Herbstbrief', betreff: 'Neues aus dem Verein', status: 'draft', gesendet: 0, von: 4 }],
              heute: { gesendet: 2, grenze: 30 },
              link: 'https://post.example.org',
            }
          : {},
      ),
    );
    zeigen();
    fireEvent.click(knopf('kampagnen'));
    await waitFor(() => expect(document.querySelector('[data-post-satz]')!.textContent).toContain('1 Liste'));
    expect(document.querySelector('[data-post-heute]')!.textContent).toContain('2 von 30');
    const liste = document.querySelector('[data-post-liste]')!;
    expect(liste.textContent).toContain('Intern');
    expect(liste.textContent).toContain('privat');
    expect(liste.textContent).toContain('1 Abonnent');
    const k = document.querySelector('[data-post-kampagne="draft"]')!;
    expect(k.textContent).toContain('Herbstbrief');
    expect(k.textContent).toContain('Entwurf');
    expect((document.querySelector('[data-post-link]') as HTMLAnchorElement).href).toBe('https://post.example.org/');
    expect(hubMock).toHaveBeenCalledWith('post.zustand', {});
  });

  it('Serienmails: Antwort ohne Verbindung zeigt den Satz und keine Zahlen, ein http-Link wird nicht gezeigt', async () => {
    hubMock.mockImplementation((tool: string) =>
      Promise.resolve(tool === 'post.zustand' ? { quelle_ok: false, satz: 'Der Versanddienst antwortet gerade nicht.', link: 'http://post.example' } : {}),
    );
    zeigen();
    fireEvent.click(knopf('kampagnen'));
    await waitFor(() => expect(document.querySelector('[data-post-satz]')!.textContent).toContain('antwortet gerade nicht'));
    expect(document.querySelector('[data-post-listen]')).toBeNull();
    expect(document.querySelector('[data-post-link]')).toBeNull();
  });

  it('Serienmails: ohne Plugin oder ohne Tag „flaeche“ steht „Noch nicht eingerichtet.“ da (403)', async () => {
    hubMock.mockImplementation((tool: string) => (tool === 'post.zustand' ? Promise.reject(new ApiError(403, undefined, 'kein Flächen-Werkzeug')) : Promise.resolve({})));
    zeigen();
    fireEvent.click(knopf('kampagnen'));
    await waitFor(() => expect(document.querySelector('[data-buero-gesperrt="post.zustand"]')).toBeTruthy());
    expect(document.querySelector('[data-buero-gesperrt="post.zustand"]')!.textContent).toContain('Noch nicht eingerichtet.');
  });

  it('Bestellungen: Liste aus bestellungen.liste, „kommt heute“ fällt auf, Zeitraum lädt neu', async () => {
    hubMock.mockImplementation((tool: string, args: { tage?: number }) =>
      Promise.resolve(
        tool === 'bestellungen.liste'
          ? {
              erreichbar: true,
              satz: `2 Mails zu Bestellungen in ${args.tage} Tagen (Onlineshop, Paketdienst).`,
              eintraege: [
                { shop: 'Paketdienst', haendler: 'Beispielhandel GmbH', status: 'kommt_heute', betreff: 'Ihre Sendung kommt heute', datum: '2026-10-21T06:00:00+02:00' },
                { shop: 'Onlineshop', status: 'versandt', betreff: 'Ihre Sendung ist unterwegs', datum: '2026-10-20T09:00:00+02:00' },
              ],
            }
          : {},
      ),
    );
    zeigen();
    fireEvent.click(knopf('bestellungen'));
    await waitFor(() => expect(document.querySelector('[data-bestellungen-satz]')!.textContent).toContain('30 Tagen'));
    const heute = document.querySelector('[data-bestellung="kommt_heute"]')!;
    expect(heute.textContent).toContain('Beispielhandel GmbH');
    expect(heute.textContent).toContain('über Paketdienst');
    expect(heute.textContent).toContain('kommt heute');
    fireEvent.click(screen.getByRole('button', { name: '7 Tage' }));
    await waitFor(() => expect(document.querySelector('[data-bestellungen-satz]')!.textContent).toContain('7 Tagen'));
    expect(hubMock).toHaveBeenLastCalledWith('bestellungen.liste', { tage: 7 });
  });

  it('Tagesbrief: Satz und Abschnitte aus brief.heute, Adressen werden Links', async () => {
    hubMock.mockImplementation((tool: string) =>
      Promise.resolve(
        tool === 'brief.heute'
          ? {
              satz: 'Guten Morgen, Mittwoch 21.10.: 2 Punkte für heute.',
              erzeugt: '2026-10-21T06:19:26Z',
              abschnitte: [
                { titel: 'Wetter', zeilen: ['Heute 10 bis 13 Grad, Regen.'] },
                { titel: 'Nachrichten', zeilen: ['Ein Artikel https://example.org/artikel'] },
              ],
            }
          : {},
      ),
    );
    zeigen();
    fireEvent.click(knopf('tagesbrief'));
    await waitFor(() => expect(document.querySelector('[data-tagesbrief-satz]')!.textContent).toContain('2 Punkte'));
    expect(document.querySelector('[data-tagesbrief-abschnitt="Wetter"]')!.textContent).toContain('13 Grad');
    const link = document.querySelector('[data-tagesbrief-abschnitt="Nachrichten"] a') as HTMLAnchorElement;
    expect(link.href).toBe('https://example.org/artikel');
    expect(screen.getByRole('button', { name: 'Neu bauen' })).toBeTruthy();
  });

  it('ohne Plugin oder Tag flaeche sagen beide Ansichten „Noch nicht eingerichtet.“', async () => {
    hubMock.mockRejectedValue(new ApiError(404, undefined, 'unbekanntes Werkzeug'));
    zeigen();
    fireEvent.click(knopf('bestellungen'));
    await waitFor(() => expect(document.querySelector('[data-buero-gesperrt="bestellungen.liste"]')).toBeTruthy());
    fireEvent.click(knopf('tagesbrief'));
    await waitFor(() => expect(document.querySelector('[data-buero-gesperrt="brief.heute"]')).toBeTruthy());
  });

  it('ist die Quelle weg, steht der Satz des Plugins da statt eines Fehlers', async () => {
    hubMock.mockResolvedValue({ erreichbar: false, eintraege: [], satz: 'Der Dienst antwortet mit 400.' });
    zeigen();
    fireEvent.click(knopf('bestellungen'));
    await waitFor(() => expect(document.querySelector('[data-bestellungen-satz]')!.textContent).toContain('Der Dienst antwortet mit 400.'));
    expect(document.querySelector('[data-bestellung]')).toBeNull();
  });

  it('im schmalen Fenster steht die Leiste als eine Reihe oben', () => {
    zeigen(true);
    expect(document.querySelector('[data-buero-gruppe]')).toBeNull();
    expect(document.querySelectorAll('[data-buero]').length).toBe(EINTRAEGE.length);
  });
});
