import { ResultsDashboard } from "@/components/leaderboard/results-dashboard";

/**
 * Resultados, de las llamadas que han pasado de verdad.
 *
 * Esta página enseñaba `MOCK_EVALUATION_RESULTS`: escenarios inventados con
 * notas inventadas. En una demo eso es peor que no tener página — cualquiera
 * que pregunte "¿esto de dónde sale?" se lleva la respuesta equivocada, y a
 * partir de ahí duda del resto, que sí es real.
 *
 * Los datos los pide el cliente a `/api/live/calls`, el proxy de este origen,
 * y se refrescan solos. En el servidor sería una foto del momento en que se
 * pintó la página; una llamada que entra mientras alguien la mira tiene que
 * aparecer sin recargar.
 */
export const metadata = {
  title: "Resultados · Clínica Arenal",
  description: "Cómo se ha comportado el agente en las llamadas que han pasado de verdad.",
};

export default function LeaderboardPage() {
  return <ResultsDashboard />;
}
