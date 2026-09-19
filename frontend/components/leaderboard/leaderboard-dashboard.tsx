import { ArenaBusinessSummary } from "@/components/leaderboard/arena-business-summary";
import { ArenaBusinessTable } from "@/components/leaderboard/arena-business-table";
import { ArenaDeveloperInsights } from "@/components/leaderboard/arena-developer-insights";
import { PageHeader } from "@/components/layout/page-header";
import { MOCK_EVALUATION_RESULTS } from "@/lib/mock-data";

export function LeaderboardDashboard() {
  const results = MOCK_EVALUATION_RESULTS;

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Resultados de la recepción">
        Resumen de cómo el asistente de citas se comporta ante llamadas difíciles:
        urgencias, intentos de saltarse reglas e identidad. Pensado para dirección
        y recepción — sin jerga técnica.
      </PageHeader>

      <div className="mb-10 sm:mb-14">
        <ArenaBusinessSummary results={results} />
      </div>

      <section className="mb-12 sm:mb-16" aria-label="Casos de la ronda">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-heading text-[15px] text-graphite">
              Casos de esta ronda
            </h2>
            <p className="mt-1 text-[13px] text-steel">
              Resumen claro de cada escenario. El detalle técnico está abajo.
            </p>
          </div>
          <p className="font-heading text-[12px] text-quiet">
            {results.length} escenarios evaluados
          </p>
        </div>
        <ArenaBusinessTable results={results} />
      </section>

      <ArenaDeveloperInsights results={results} />
    </div>
  );
}
