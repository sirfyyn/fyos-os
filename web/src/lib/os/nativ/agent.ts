/**
 * Native Fläche „Agent": die Oberfläche des Agenten-Runners — Gespräche, Live, Freigaben, Läufe und geteilter Zustand.
 * Spricht nur den Runner (über /api/agent, nginx leitet weiter). Den Anzeigenamen setzt `agentName()`
 * (lib/config.ts) zur Laufzeit. Komponente: components/os/nativ/Agent.tsx (Teile in agent/) · Logik: lib/agent-runner/.
 */
import type { NativEintrag } from '../nativ';

export const AGENT: NativEintrag[] = [
  {
    id: 'nativ:agent',
    titel: 'Agent',
    gruppe: 'Agent',
    kuerzel: 'Ag',
    breit: true,
    laden: () => import('~/components/os/nativ/Agent'),
  },
];
