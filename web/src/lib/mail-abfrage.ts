/**
 * Abfragen an den Mail-Dienst (Ordner neben dem Posteingang, z. B. Gesendet, und die Suche dort
 * gingen nicht). Die Liste lud immer nur die letzten Mails ohne Ordner, der Browser filterte danach: andere Ordner
 * zeigten den Posteingang, die Suche fand nur, was schon geladen war. `/api/inbox/list?q=` nimmt Gmail-Abfragen
 * (in:sent, is:starred, category:updates, subject:…), also baut die Oberfläche sie aus Ordner und Suchtext.
 */
const ORDNER_ABFRAGE: Record<string, string> = {
  INBOX: 'in:inbox',
  SENT: 'in:sent',
  DRAFT: 'in:drafts',
  DRAFTS: 'in:drafts',
  TRASH: 'in:trash',
  SPAM: 'in:spam',
  STARRED: 'is:starred',
  IMPORTANT: 'is:important',
  UNREAD: 'is:unread',
  CHAT: 'in:chats',
};

/** Gmail-Abfrage zu einem Ordner der Seitenleiste (Systemordner, Kategorien, eigene Labels). */
export function ordnerAbfrage(id: string): string {
  const k = id.toUpperCase();
  const fest = ORDNER_ABFRAGE[k];
  if (fest) return fest;
  const kat = /^CATEGORY_([A-Z]+)$/.exec(k);
  if (kat) return `category:${kat[1]!.toLowerCase()}`;
  // Eigene Labels heißen im Dienst nach ihrem Namen („Unterlagen/Ebay“), nicht nach der ID; die Seitenleiste führt sie
  // nicht als Ordner (sie hängen am Label-Knopf), der Rückfall bleibt für Ordner mit sprechendem Namen.
  return `label:"${id}"`;
}

/** Suchtext, der an den Dienst geht: die Sondermarken (★snoozed★, ★pinned★) bleiben im Browser. */
export function dienstSuche(s: string): string {
  const t = s.trim();
  return t.startsWith('★') ? '' : t;
}

/** Die ganze Abfrage: Ordner zuerst, dann der Suchtext. */
export const listenAbfrage = (ordner: string, suche: string): string =>
  [ordnerAbfrage(ordner), dienstSuche(suche)].filter(Boolean).join(' ');
