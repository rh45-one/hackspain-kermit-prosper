import { ArenaBusinessSummary } from "@/components/leaderboard/arena-business-summary";
import { ArenaBusinessTable } from "@/components/leaderboard/arena-business-table";
import { ArenaDeveloperInsights } from "@/components/leaderboard/arena-developer-insights";
import { PageHeader } from "@/components/layout/page-header";
import { MOCK_EVALUATION_RESULTS } from "@/lib/mock-data";

export function LeaderboardDashboard() {
  const results = MOCK_EVALUATION_RESULTS;

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Reception results">
        How the booking assistant behaves on hard calls: emergencies, attempts
        to skip rules, and identity. Written for directors and reception —
        no engine jargon.
      </PageHeader>

      <div className="mb-10 sm:mb-14">
        <ArenaBusinessSummary results={results} />
      </div>

      <section className="mb-12 sm:mb-16" aria-label="Round cases">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-heading text-[15px] text-graphite">
              Cases in this round
            </h2>
            <p className="mt-1 text-[13px] text-steel">
              A plain summary of each scenario. Technical detail is below.
            </p>
          </div>
          <p className="font-heading text-[12px] text-quiet">
            {results.length} scenarios evaluated
          </p>
        </div>
        <ArenaBusinessTable results={results} />
      </section>

      <ArenaDeveloperInsights results={results} />
    </div>
  );
}
