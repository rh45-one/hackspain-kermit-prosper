"use client";

import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toBusinessCase } from "@/lib/arena-business";
import type { EvaluationResult } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

type ArenaBusinessTableProps = {
  results: EvaluationResult[];
};

export function ArenaBusinessTable({ results }: ArenaBusinessTableProps) {
  return (
    <div className="overflow-hidden rounded-xl bg-canvas-white shadow-[var(--shadow-sm)] ring-1 ring-mist">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow className="border-mist hover:bg-transparent">
            <TableHead className="w-[22%] whitespace-normal text-quiet">
              Situation
            </TableHead>
            <TableHead className="w-[32%] whitespace-normal text-quiet">
              What the assistant did
            </TableHead>
            <TableHead className="w-[32%] whitespace-normal text-quiet">
              For the clinic
            </TableHead>
            <TableHead className="w-[14%] whitespace-normal text-quiet">
              Result
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {results.map((row) => {
            const business = toBusinessCase(row);

            return (
              <TableRow key={row.id} className="border-mist">
                <TableCell className="align-top whitespace-normal">
                  <div className="min-w-0 break-words font-heading text-graphite">
                    {business.situation}
                  </div>
                  <div className="mt-0.5 text-[12px] text-quiet">
                    {business.urgencyLabel}
                  </div>
                </TableCell>
                <TableCell className="align-top whitespace-normal text-[13px] leading-snug text-steel">
                  <p className="min-w-0 break-words">
                    {business.assistantDid}
                  </p>
                </TableCell>
                <TableCell className="align-top whitespace-normal text-[13px] leading-snug text-steel">
                  <p className="min-w-0 break-words">
                    {business.clinicMeaning}
                  </p>
                </TableCell>
                <TableCell className="align-top whitespace-normal">
                  <Badge
                    variant={business.ok ? "secondary" : "destructive"}
                    className={cn(
                      business.ok &&
                        "border-0 bg-[#1f6b4a]/12 text-[#1f6b4a] hover:bg-[#1f6b4a]/18",
                    )}
                  >
                    {business.resultLabel}
                  </Badge>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
