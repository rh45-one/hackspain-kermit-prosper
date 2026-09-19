"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { LeaderboardKpis } from "@/components/leaderboard/leaderboard-kpis";
import { LeaderboardTable } from "@/components/leaderboard/leaderboard-table";
import type { EvaluationResult } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type ArenaDeveloperInsightsProps = {
  results: EvaluationResult[];
};

export function ArenaDeveloperInsights({ results }: ArenaDeveloperInsightsProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <section
      aria-label="Insights para desarrolladores"
      className="rounded-xl bg-fog/60 ring-1 ring-mist"
    >
      <button
        type="button"
        className="flex w-full items-start justify-between gap-4 px-5 py-5 text-left transition-colors hover:bg-fog sm:px-6 sm:py-6"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((current) => !current)}
      >
        <div className="min-w-0">
          <p className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
            Insights para desarrolladores
          </p>
          <h2 className="mt-2 font-heading text-[18px] tracking-[-0.03em] text-graphite sm:text-[20px]">
            Telemetría y tabla técnica de combates
          </h2>
          <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-steel sm:text-[14px]">
            Latencia, TTFT, WER, interrupciones, códigos de auditoría y veredictos
            del motor. Misma información de siempre; pensada para ingeniería y
            auditoría fina.
          </p>
        </div>
        <ChevronDown
          className={cn(
            "mt-1 size-5 shrink-0 text-quiet transition-transform duration-200",
            open && "rotate-180",
          )}
          strokeWidth={1.8}
          aria-hidden
        />
      </button>

      {open ? (
        <div id={panelId} className="border-t border-mist px-5 pb-6 pt-5 sm:px-6 sm:pb-8">
          <section className="mb-8 sm:mb-10" aria-label="Métricas de evaluación">
            <LeaderboardKpis results={results} />
          </section>

          <section aria-label="Tabla de combates">
            <div className="mb-4 flex items-end justify-between gap-4">
              <h3 className="font-heading text-[15px] text-graphite">
                Tabla de combates
              </h3>
              <p className="font-heading text-[12px] text-quiet">
                {results.length} evaluaciones · clic para deep dive
              </p>
            </div>
            <LeaderboardTable results={results} />
          </section>
        </div>
      ) : null}
    </section>
  );
}
