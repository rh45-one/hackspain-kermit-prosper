"use client";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { TriageLevelBadge } from "@/components/leaderboard/triage-level-badge";
import type { EvaluationResult, IdentityStatus } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const IDENTITY_LABEL: Record<
  IdentityStatus,
  { label: string; className: string }
> = {
  VALIDATED: {
    label: "VALIDATED",
    className: "border-0 bg-[#1f6b4a]/12 text-[#1f6b4a]",
  },
  PARTIAL: {
    label: "PARTIAL",
    className: "border-0 bg-brass/15 text-brass",
  },
  FAILED: {
    label: "FAILED",
    className: "border-0 bg-destructive/12 text-destructive",
  },
  SKIPPED: {
    label: "SKIPPED",
    className: "border-0 bg-ash text-quiet",
  },
};

type LeaderboardDetailDialogProps = {
  result: EvaluationResult | null;
  onOpenChange: (open: boolean) => void;
};

function MetricRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <span className="font-heading text-[12px] tracking-[0.04em] text-quiet uppercase">
        {label}
      </span>
      <span
        className={cn(
          "text-right text-[14px] text-graphite",
          mono && "font-mono text-[13px] tabular-nums",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function LeaderboardDetailDialog({
  result,
  onOpenChange,
}: LeaderboardDetailDialogProps) {
  const identity = result ? IDENTITY_LABEL[result.identityStatus] : null;

  return (
    <Dialog open={result !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg border-mist bg-canvas-white sm:max-w-lg">
        {result ? (
          <>
            <DialogHeader>
              <DialogTitle className="pr-10 font-heading text-[clamp(1.5rem,4vw,1.85rem)] font-medium tracking-[-0.04em]">
                {result.personaScenario}
              </DialogTitle>
              <DialogDescription className="font-heading text-steel">
                {result.aiProvider} · diagnóstico del motor
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-1">
              <p className="mb-2 font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
                Negocio / auditoría
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <TriageLevelBadge level={result.triageLevel} />
                <Badge
                  variant={
                    result.verdict === "PASSED" ? "secondary" : "destructive"
                  }
                  className={cn(
                    result.verdict === "PASSED" &&
                      "border-0 bg-[#1f6b4a]/12 text-[#1f6b4a]",
                  )}
                >
                  {result.verdict}
                </Badge>
                {identity ? (
                  <Badge variant="secondary" className={identity.className}>
                    DNI/CIP · {identity.label}
                  </Badge>
                ) : null}
              </div>
              <MetricRow label="Idioma" value={result.languageDetected} mono />
              <MetricRow
                label="Estado final"
                value={result.actionOutcome}
                mono
              />
              <MetricRow
                label="Código auditoría"
                value={result.auditCode}
                mono
              />
            </div>

            <Separator className="bg-mist" />

            <div>
              <p className="mb-2 font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
                Telemetría del motor
              </p>
              <MetricRow
                label="Identidad validada"
                value={result.identityStatus}
                mono
              />
              <MetricRow
                label="Latencia media (turno)"
                value={`${result.latencyMs} ms`}
                mono
              />
              <MetricRow
                label="Barge-ins"
                value={String(result.bargeIns)}
                mono
              />
              <MetricRow
                label="Falsas interrupciones"
                value={`${result.falseInterruptions.toFixed(1)}%`}
                mono
              />
              <MetricRow label="WER" value={`${result.wer.toFixed(1)}%`} mono />
              <MetricRow label="TTFT" value={`${result.ttft} ms`} mono />
              <MetricRow
                label="Constraint violation"
                value={`${result.constraintViolationRate.toFixed(1)}%`}
                mono
              />
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
