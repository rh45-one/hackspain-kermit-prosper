import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PROBLEMS } from "@/lib/problems/catalog";
import type { ProblemBrief } from "@/lib/problems/types";
import { cn } from "@/lib/utils";

function publicCountLabel(problem: ProblemBrief): string {
  if (problem.diagnostic && problem.burstSize) {
    return `0 (1 burst)`;
  }
  return String(problem.publicCaseCount);
}

export function ProblemCatalog({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const openCount = PROBLEMS.filter((problem) => problem.open).length;

  return (
    <div>
      {!embedded ? (
        <PageHeader kicker="Drill" title="Problems">
          Eighteen problems, seventeen scored. This screen is the roadmap:
          closed ones are read, not marked. Pronto does not call the harness.
        </PageHeader>
      ) : (
        <p className="mb-6 max-w-2xl text-[14px] leading-relaxed text-steel sm:mb-8">
          Eighteen problems, seventeen scored. Harness roadmap: closed ones
          are read, not marked. Pronto does not call the harness.
        </p>
      )}

      <p
        data-reveal=""
        data-delay={embedded ? undefined : "1"}
        className="mb-8 font-heading text-[13px] text-steel sm:mb-10"
      >
        <span className="text-brass">{openCount} open</span>
        <span className="mx-2 text-mist">·</span>
        {PROBLEMS.length} on the roster
        <span className="mx-2 text-mist">·</span>
        no Call button
      </p>

      <section
        data-reveal=""
        data-delay={embedded ? undefined : "2"}
        className="surface overflow-hidden rounded-[18px]"
      >
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow className="border-mist hover:bg-transparent">
              <TableHead className="w-14 font-heading text-[13px] text-quiet">
                #
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Problem
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                problem_id
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Public
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Weight
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Status
              </TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {PROBLEMS.map((problem) => (
              <TableRow
                key={problem.id}
                className={cn(
                  "animate-in fade-in border-mist duration-200 hover:bg-fog",
                  !problem.open && "text-quiet",
                )}
              >
                <TableCell className="font-mono text-steel">
                  {problem.number}
                </TableCell>
                <TableCell>
                  <Link
                    href={`/problems/${problem.id}`}
                    className="block outline-none"
                  >
                    <div
                      className={cn(
                        "font-heading text-[16px]",
                        problem.open ? "text-graphite" : "text-steel",
                      )}
                    >
                      {problem.title}
                    </div>
                    <div className="text-[13px] text-quiet">{problem.titleEs}</div>
                  </Link>
                </TableCell>
                <TableCell className="font-mono text-[13px] text-steel">
                  {problem.id}
                </TableCell>
                <TableCell className="text-steel">
                  {publicCountLabel(problem)}
                </TableCell>
                <TableCell>
                  {problem.diagnostic || problem.weight == null ? (
                    <span className="text-[13px] text-quiet">diagnostic</span>
                  ) : (
                    <span className="font-heading text-graphite">
                      {problem.weight}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={
                      problem.open
                        ? "border-0 bg-ivory text-brass"
                        : "border-0 bg-ash text-quiet"
                    }
                  >
                    {problem.open ? "Open" : "Closed"}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button variant="outline" size="sm" asChild>
                    <Link href={`/problems/${problem.id}`}>View</Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
