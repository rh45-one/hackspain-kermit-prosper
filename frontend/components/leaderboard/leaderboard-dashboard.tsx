import { LeaderboardKpis } from "@/components/leaderboard/leaderboard-kpis";
import { LeaderboardTable } from "@/components/leaderboard/leaderboard-table";
import { PageHeader } from "@/components/layout/page-header";
import { MOCK_EVALUATION_RESULTS } from "@/lib/mock-data";

export function LeaderboardDashboard() {
  const results = MOCK_EVALUATION_RESULTS;

  return (
    <div>
      <PageHeader kicker="FrontDesk Arena" title="Leaderboard">
        Combates de auditoría: defensores frente a escenarios de ataque
        telefónico. Pasa el ratón por el icono de cada KPI para ver objetivo
        operativo. Pulsa una fila para el diagnóstico del motor.
      </PageHeader>

      <section className="mb-8 sm:mb-10" aria-label="Métricas de evaluación">
        <LeaderboardKpis results={results} />
      </section>

      <section aria-label="Tabla de combates">
        <div className="mb-4 flex items-end justify-between gap-4">
          <h2 className="font-heading text-[15px] text-graphite">
            Tabla de combates
          </h2>
          <p className="font-heading text-[12px] text-quiet">
            {results.length} evaluaciones · clic para deep dive
          </p>
        </div>
        <LeaderboardTable results={results} />
      </section>
    </div>
  );
}
