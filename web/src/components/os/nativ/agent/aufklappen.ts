/**
 * aufklappen.ts — merkt, welche Zeilen des Verlaufs aufgeklappt sind, unter ihrem Schlüssel.
 * Die Zeilen werden beim Schreiben ständig neu gebaut (jedes Text-Delta ändert die letzte); der Zustand liegt deshalb
 * nicht in der Zeile, sondern hier, und überlebt das.
 */
import { createSignal } from 'solid-js';

export function aufklappen() {
  const [offen, setOffen] = createSignal<Record<string, boolean>>({});
  return {
    ist: (schluessel: string): boolean => !!offen()[schluessel],
    umschalten: (schluessel: string): void => {
      setOffen((o) => ({ ...o, [schluessel]: !o[schluessel] }));
    },
    setze: (schluessel: string, an: boolean): void => {
      setOffen((o) => ({ ...o, [schluessel]: an }));
    },
  };
}

export type Aufklapp = ReturnType<typeof aufklappen>;
