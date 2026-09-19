"use client";

import { useState } from "react";

import { LeaderboardDetailDialog } from "@/components/leaderboard/leaderboard-detail-dialog";
import { TriageLevelBadge } from "@/components/leaderboard/triage-level-badge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EvaluationResult } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type LeaderboardTableProps = {
  results: EvaluationResult[];
};

export function LeaderboardTable({ results }: LeaderboardTableProps) {
  const [selected, setSelected] = useState<EvaluationResult | null>(null);

  return (
    <>
      <div className="overflow-hidden rounded-xl bg-canvas-white shadow-[var(--shadow-sm)] ring-1 ring-mist">
        <Table>
          <TableHeader>
            <TableRow className="border-mist hover:bg-transparent">
              <TableHead className="text-quiet">Escenario</TableHead>
              <TableHead className="text-quiet">Idioma</TableHead>
              <TableHead className="text-quiet">Nivel Triaje</TableHead>
              <TableHead className="text-quiet">Estado Final</TableHead>
              <TableHead className="text-quiet">Código Auditoría</TableHead>
              <TableHead className="text-quiet">Veredicto</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {results.map((row) => {
              const passed = row.verdict === "PASSED";

              return (
                <TableRow
                  key={row.id}
                  className="cursor-pointer border-mist"
                  onClick={() => setSelected(row)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelected(row);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`Abrir diagnóstico de ${row.personaScenario}`}
                >
                  <TableCell>
                    <div className="font-heading text-graphite">
                      {row.personaScenario}
                    </div>
                    <div className="mt-0.5 text-[12px] text-quiet">
                      {row.aiProvider}
                    </div>
                  </TableCell>
                  <TableCell>
                    <code className="font-mono text-[12px] text-steel">
                      {row.languageDetected}
                    </code>
                  </TableCell>
                  <TableCell>
                    <TriageLevelBadge level={row.triageLevel} />
                  </TableCell>
                  <TableCell>
                    <code className="rounded-md bg-fog px-2 py-1 font-mono text-[11px] text-steel whitespace-normal">
                      {row.actionOutcome}
                    </code>
                  </TableCell>
                  <TableCell>
                    <code className="font-mono text-[11px] tracking-tight text-graphite">
                      {row.auditCode}
                    </code>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={passed ? "secondary" : "destructive"}
                      className={cn(
                        passed &&
                          "border-0 bg-[#1f6b4a]/12 text-[#1f6b4a] hover:bg-[#1f6b4a]/18",
                      )}
                    >
                      {passed ? "PASSED" : "FAILED"}
                    </Badge>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <LeaderboardDetailDialog
        result={selected}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      />
    </>
  );
}
