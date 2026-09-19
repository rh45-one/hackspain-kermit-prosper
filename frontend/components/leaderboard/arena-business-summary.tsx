import { businessSummary } from "@/lib/arena-business";
import type { EvaluationResult } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type ArenaBusinessSummaryProps = {
  results: EvaluationResult[];
};

type SummaryCard = {
  id: string;
  label: string;
  value: string;
  hint: string;
  tone: "good" | "warn" | "neutral";
};

export function ArenaBusinessSummary({ results }: ArenaBusinessSummaryProps) {
  const summary = businessSummary(results);

  const cards: SummaryCard[] = [
    {
      id: "pass-rate",
      label: "Tests passed",
      value: `${summary.passRate}%`,
      hint: `${summary.passed} of ${summary.total} scenarios`,
      tone: summary.passRate >= 80 ? "good" : summary.passRate >= 50 ? "neutral" : "warn",
    },
    {
      id: "review",
      label: "Cases to review",
      value: String(summary.failed),
      hint:
        summary.failed === 0
          ? "No misses in this round"
          : "Need a reception call",
      tone: summary.failed === 0 ? "good" : "warn",
    },
    {
      id: "response",
      label: "Response time",
      value: summary.responseLabel,
      hint: summary.responseHint,
      tone:
        summary.responseLabel === "Snappy"
          ? "good"
          : summary.responseLabel === "Slow"
            ? "warn"
            : "neutral",
    },
    {
      id: "rules",
      label: "Rule compliance",
      value: `${summary.rulesOkRate}%`,
      hint: "Without skipping clinic policy",
      tone: summary.rulesOkRate === 100 ? "good" : "warn",
    },
  ];

  return (
    <section aria-label="Summary for directors">
      <p className="mb-6 max-w-2xl text-[15px] leading-relaxed text-steel sm:mb-8 sm:text-[16px]">
        {summary.headline}
      </p>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 sm:gap-5">
        {cards.map((card) => (
          <div
            key={card.id}
            className="rounded-xl bg-canvas-white px-5 py-5 shadow-[var(--shadow-sm)] ring-1 ring-mist"
          >
            <p className="font-heading text-[11px] tracking-[0.06em] text-quiet uppercase">
              {card.label}
            </p>
            <p
              className={cn(
                "mt-3 font-heading text-[clamp(1.75rem,3vw,2.35rem)] leading-none tracking-[-0.04em]",
                card.tone === "good" && "text-[#1f6b4a]",
                card.tone === "warn" && "text-ember-orange",
                card.tone === "neutral" && "text-graphite",
              )}
            >
              {card.value}
            </p>
            <p className="mt-3 text-[13px] leading-snug text-steel">{card.hint}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
