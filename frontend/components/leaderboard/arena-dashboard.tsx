"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { LeaderboardDashboard } from "@/components/leaderboard/leaderboard-dashboard";
import { PageHeader } from "@/components/layout/page-header";
import { ProblemCatalog } from "@/components/problems/problem-catalog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type ArenaTab = "results" | "problems";

function parseTab(value: string | null): ArenaTab {
  return value === "problems" ? "problems" : "results";
}

export function ArenaDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));

  return (
    <div>
      <PageHeader kicker="FrontDesk Arena" title="Arena">
        Resultados de auditoría y catálogo de problemas del harness. Los
        combates miden al defensor; el roster describe qué se evalúa.
      </PageHeader>

      <Tabs
        value={tab}
        onValueChange={(value) => {
          const next = parseTab(value);
          const href =
            next === "problems"
              ? "/leaderboard?tab=problems"
              : "/leaderboard";
          router.replace(href, { scroll: false });
        }}
        className="gap-6 sm:gap-8"
      >
        <TabsList
          data-reveal=""
          data-delay="1"
          className="h-auto rounded-xl border border-mist bg-canvas-white p-1 shadow-[var(--shadow-sm)]"
        >
          <TabsTrigger
            value="results"
            className="rounded-lg px-4 py-2 font-heading text-[14px] data-active:bg-graphite data-active:text-canvas-white data-active:shadow-sm"
          >
            Resultados
          </TabsTrigger>
          <TabsTrigger
            value="problems"
            className="rounded-lg px-4 py-2 font-heading text-[14px] data-active:bg-graphite data-active:text-canvas-white data-active:shadow-sm"
          >
            Problemas
          </TabsTrigger>
        </TabsList>

        <TabsContent value="results" className="mt-0 outline-none">
          <LeaderboardDashboard embedded />
        </TabsContent>
        <TabsContent value="problems" className="mt-0 outline-none">
          <ProblemCatalog embedded />
        </TabsContent>
      </Tabs>
    </div>
  );
}
