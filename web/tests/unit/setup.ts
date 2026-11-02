import '@testing-library/jest-dom/vitest';
import { cleanup } from '@solidjs/testing-library';
import { afterEach, beforeEach } from 'vitest';
import { spracheFestlegen } from '~/lib/i18n';

// Die bestehenden Tests suchen deutsche Texte: Deutsch fest einstellen. Englisch als Vorgabe prüft i18n.test.tsx.
// Auch schon beim Einlesen der Testdateien: was ein describe-Block baut (Werkzeugbeschreibungen über tr()), ist dann deutsch.
spracheFestlegen('de');
beforeEach(() => {
  spracheFestlegen('de');
});

afterEach(() => {
  cleanup();
});
