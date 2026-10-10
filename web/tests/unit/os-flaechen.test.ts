import { afterEach, describe, expect, it } from 'vitest';
import { alleFlaechen, appFlaecheZu, flaecheZu, gruppiert, hubFlaechen, kuerzelVon, standardPlaetze } from '~/lib/os/flaechen';
import { registerZuruecksetzen, registriereFlaechen } from '~/lib/os/register';

const ui = (uri: string) => ({ ui: { resourceUri: uri } });
const app = (name: string, extra: Record<string, unknown> = {}) =>
  ({ name, tool: name.replace('__', '.'), title: name, description: '', inputSchema: {}, _meta: ui(`ui://${name}`), scope: 'READ', ...extra }) as never;
const werk = (name: string, scope = 'READ', required: string[] = []) =>
  app(name, { title: `Werkstatt — ${name.split('__')[1]}`, scope, inputSchema: { required }, _meta: ui('ui://fyos/werkstatt.html') });

afterEach(() => registerZuruecksetzen());

describe('Flächenverzeichnis', () => {
  it('ohne Registrierung gibt es nur die eingebauten Flächen: Einstellungen und Agent', () => {
    const ids = alleFlaechen([]).map((f) => f.id);
    expect(ids).toContain('nativ:einstellungen');
    expect(ids).toContain('agent');
    expect(ids.every((id) => id === 'agent' || id.startsWith('nativ:'))).toBe(true);
  });

  it('nimmt Hub-Apps von selbst auf, der Agent ist immer da, jede Kennung kommt einmal vor', () => {
    const l = alleFlaechen([app('notizen__liste', { title: 'Notizen' })]);
    expect(l.find((f) => f.id === 'app:notizen__liste')?.gruppe).toBe('Apps');
    expect(l.find((f) => f.id === 'agent')?.breit).toBe(true);
    expect(new Set(l.map((f) => f.id)).size).toBe(l.length);
  });

  it('Werkzeuge mit derselben Oberfläche sind eine Fläche (vier Werkzeuge, eine Kachel)', () => {
    const w = (name: string, titel: string) => ({ name, tool: name.replace('__', '.'), title: titel, description: '', inputSchema: {}, _meta: ui('ui://fyos/werkstatt.html'), scope: 'READ' });
    const l = hubFlaechen([w('werkstatt__suchen', 'Werkstatt — suchen'), w('werkstatt__beschreiben', 'Werkstatt — beschreiben'), w('werkstatt__zeigen', 'Werkstatt — zeigen')] as never);
    expect(l).toHaveLength(1);
    expect(l[0]!.titel).toBe('Werkstatt');
  });

  it('Hub-Apps stehen in der Gruppe, die ein Plugin zuweist; Unbekanntes unter „Apps"', () => {
    registriereFlaechen({ gruppen: { reihenfolge: ['Arbeit'], plugin: { notizen: 'Arbeit' }, app: { kalender__heute: 'Zeit' } } });
    const l = hubFlaechen([app('notizen__liste'), app('kalender__heute'), app('neu__etwas')]);
    expect(Object.fromEntries(l.map((f) => [f.id, f.gruppe]))).toEqual({
      'app:notizen__liste': 'Arbeit',
      'app:kalender__heute': 'Zeit',
      'app:neu__etwas': 'Apps',
    });
  });

  it('gruppiert und sucht', () => {
    const l = alleFlaechen([app('notizen__liste', { title: 'Notizen' })]);
    expect(gruppiert(l, 'notizen')[0]!.flaechen[0]!.id).toBe('app:notizen__liste');
    expect(gruppiert(l, 'gibt-es-nicht')).toEqual([]);
    expect(hubFlaechen([])).toEqual([]);
  });

  it('Kürzel aus dem Titel', () => {
    expect(kuerzelVon('Braucht dich')).toBe('Bd');
    expect(kuerzelVon('Notizen')).toBe('No');
  });
});

describe('Hub-Apps mit Gesicht', () => {
  it('trägt Titel, Untertitel und Kategorie des Hubs in die Fläche', () => {
    const [f] = hubFlaechen([app('haus__favoriten', { titel: 'Haus', untertitel: 'Szenen schalten', kategorie: 'Zuhause' })]);
    expect(f).toMatchObject({ titel: 'Haus', untertitel: 'Szenen schalten', kategorie: 'Zuhause', appName: 'haus__favoriten', mitglieder: ['haus__favoriten'] });
  });

  it('leitet sie ohne Felder vom Hub ab', () => {
    const [f] = hubFlaechen([app('leitstand__lagebild', { title: 'Lagebild', description: 'Das Lagebild (App): Ampel und Fristen.' })]);
    expect(f).toMatchObject({ titel: 'Lagebild', untertitel: 'Ampel und Fristen' });
  });

  it('startbar (anheftbar): lesend, ohne Pflichtfelder und nur als einziges Werkzeug seiner Oberfläche', () => {
    const l = hubFlaechen([
      app('haus__favoriten'),
      app('haus__schalten', { scope: 'WRITE' }),
      app('dokumente__vorschlag', { inputSchema: { required: ['id'] } }),
      werk('werkstatt__suchen'),
      werk('werkstatt__ausfuehren', 'WRITE', ['id']),
    ]);
    expect(Object.fromEntries(l.map((f) => [f.appName, f.startbar]))).toEqual({
      haus__favoriten: true,
      haus__schalten: false,
      dokumente__vorschlag: false,
      werkstatt__suchen: false, // Gruppe: würde beim Laden etwas starten, was dahinter steht
    });
  });

  it('appFlaecheZu findet die Fläche zu der App selbst und zu jedem Werkzeug mit derselben Oberfläche', () => {
    const l = alleFlaechen([werk('werkstatt__suchen'), werk('werkstatt__ausfuehren', 'WRITE', ['id']), app('haus__favoriten')]);
    expect(appFlaecheZu(l, 'werkstatt__suchen')?.id).toBe('app:werkstatt__suchen');
    expect(appFlaecheZu(l, 'werkstatt__ausfuehren')?.id).toBe('app:werkstatt__suchen');
    expect(appFlaecheZu(l, 'haus__favoriten')?.id).toBe('app:haus__favoriten');
    expect(appFlaecheZu(l, 'gibt__es_nicht')).toBeUndefined();
  });

  it('die Suche im Start findet Apps auch über ihre Zeile und Kategorie', () => {
    const l = alleFlaechen([app('haus__favoriten', { titel: 'Haus', untertitel: 'Szenen und Lieblingsgeräte schalten', kategorie: 'Zuhause' })]);
    const treffer = (q: string) => gruppiert(l, q).flatMap((g) => g.flaechen.map((f) => f.id));
    expect(treffer('lieblingsgeräte')).toEqual(['app:haus__favoriten']);
    expect(treffer('zuhause')).toContain('app:haus__favoriten');
    expect(treffer('einstellungen')).not.toContain('app:haus__favoriten');
  });
});

describe('Registrierte Flächen', () => {
  const seite = (id: string, titel: string, gruppe = 'Arbeit') => ({ id, titel, gruppe, art: 'seite' as const, kuerzel: kuerzelVon(titel), pfad: `/${id.split(':')[1]}/` });

  it('Gruppen stehen in der registrierten Reihenfolge vor den eingebauten', () => {
    registriereFlaechen({ flaechen: [seite('seite:wiki', 'Wiki', 'Wissen'), seite('seite:notizen', 'Notizen', 'Arbeit')], gruppen: { reihenfolge: ['Arbeit', 'Wissen'] } });
    const g = gruppiert(alleFlaechen([])).map((x) => x.gruppe);
    expect(g.slice(0, 2)).toEqual(['Arbeit', 'Wissen']);
    expect(g).toContain('Agent');
  });

  it('Aliasse führen alte Kennungen auf die heutige Fläche', () => {
    registriereFlaechen({ flaechen: [seite('seite:notizen', 'Notizen')], alias: { 'seite:memo': 'seite:notizen' } });
    const l = alleFlaechen([]);
    expect(flaecheZu(l, 'seite:memo')?.id).toBe('seite:notizen');
    expect(flaecheZu(l, 'seite:gibt-es-nicht')).toBeUndefined();
  });

  it('Standardplätze (Vorlagen) kommen von den Plugins', () => {
    expect(standardPlaetze()).toEqual([]);
    registriereFlaechen({ standardPlaetze: [{ name: 'Morgen', ids: ['seite:notizen'] }] });
    expect(standardPlaetze()).toEqual([{ name: 'Morgen', ids: ['seite:notizen'] }]);
  });
});
