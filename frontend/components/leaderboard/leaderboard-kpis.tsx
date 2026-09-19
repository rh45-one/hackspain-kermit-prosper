"use client";

import { CircleHelp } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  LATENCY_PENALTY_MS,
  latencyP90,
  type EvaluationResult,
} from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type LeaderboardKpisProps = {
  results: EvaluationResult[];
};

type KpiCard = {
  id: string;
  label: string;
  value: string;
  target: string;
  tooltip: string;
  accent: string;
};

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function computeKpis(results: EvaluationResult[]) {
  return {
    latencyMs: latencyP90(results),
    ttftMs: Math.round(average(results.map((r) => r.ttft))),
    wer: average(results.map((r) => r.wer)),
    falseInterruptRate: average(results.map((r) => r.falseInterruptions)),
    constraintRate: average(results.map((r) => r.constraintViolationRate)),
  };
}

export function LeaderboardKpis({ results }: LeaderboardKpisProps) {
  const { latencyMs, ttftMs, wer, falseInterruptRate, constraintRate } =
    computeKpis(results);

  const cards: KpiCard[] = [
    {
      id: "latency-e2e",
      label: "Latencia End-to-End",
      value: `${latencyMs} ms`,
      target: "Target: < 900ms",
      tooltip:
        "Tiempo total de respuesta del agente. Si supera el umbral, los usuarios perciben lentitud y empiezan a interrumpir. Objetivo: < 900ms",
      accent:
        latencyMs > LATENCY_PENALTY_MS
          ? "text-ember-orange"
          : "text-[#1f6b4a]",
    },
    {
      id: "ttft",
      label: "TTFT",
      value: `${ttftMs} ms`,
      target: "Target: < 300ms",
      tooltip:
        "Tiempo que tarda el modelo en generar la primera palabra. Objetivo: < 300ms",
      accent: ttftMs > 300 ? "text-ember-orange" : "text-[#1f6b4a]",
    },
    {
      id: "wer",
      label: "WER",
      value: `${wer.toFixed(1)}%`,
      target: "Target: < 5.0%",
      tooltip:
        "Tasa de error en la transcripción de voz a texto. Afecta a la captura de DNIs o nombres. Objetivo: < 5.0%",
      accent: wer > 5 ? "text-ember-orange" : "text-[#1f6b4a]",
    },
    {
      id: "false-interruptions",
      label: "Falsas Interrupciones",
      value: `${falseInterruptRate.toFixed(1)}%`,
      target: "Target: < 2.0%",
      tooltip:
        "Frecuencia con la que la IA se calla por error debido a ruido de fondo o estática en la línea. Objetivo: < 2.0%",
      accent:
        falseInterruptRate > 2 ? "text-ember-orange" : "text-[#1f6b4a]",
    },
    {
      id: "constraint-violations",
      label: "Violaciones de Seguridad",
      value: `${constraintRate.toFixed(1)}%`,
      target: "Target: 0.0%",
      tooltip:
        "Errores de integridad en base de datos, como condiciones de carrera o reservas dobles. Objetivo: 0.0%",
      accent:
        constraintRate === 0 ? "text-[#1f6b4a]" : "text-ember-orange",
    },
  ];

  return (
    <TooltipProvider delayDuration={200}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 sm:gap-5">
        {cards.map((card) => (
          <Card
            key={card.id}
            className="border-0 bg-canvas-white shadow-[var(--shadow-sm)] ring-1 ring-mist"
          >
            <CardHeader className="pb-0">
              <CardDescription className="flex items-center gap-1.5 font-heading text-[11px] tracking-[0.06em] text-quiet uppercase">
                <span className="min-w-0 truncate">{card.label}</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex size-4 shrink-0 items-center justify-center rounded-full text-quiet transition-colors hover:text-graphite focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      aria-label={`Qué es ${card.label}`}
                      onClick={(event) => event.preventDefault()}
                    >
                      <CircleHelp className="size-3.5" strokeWidth={1.8} />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    sideOffset={6}
                    className="max-w-[16rem] px-3 py-2 text-left leading-relaxed text-balance"
                  >
                    {card.tooltip}
                  </TooltipContent>
                </Tooltip>
              </CardDescription>
              <CardTitle
                className={cn(
                  "mt-2 font-heading text-[clamp(1.75rem,3vw,2.25rem)] leading-none tracking-[-0.04em]",
                  card.accent,
                )}
              >
                {card.value}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{card.target}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </TooltipProvider>
  );
}
