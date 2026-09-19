"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { PageHeader } from "@/components/layout/page-header";

/**
 * What the screen says when the agent will not hand over the graph.
 *
 * It names the exact failure rather than "algo ha ido mal", because the three
 * ways this breaks — no token, wrong host, a deploy older than the route —
 * each have a different fix and the person reading this is the one who has to
 * apply it.
 */
export function GraphUnavailable({ detail, hint }: { detail: string; hint: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="The clinic graph">
        This screen draws the whole clinic and the eighteen ways a call can
        end without a booking. Right now the agent is not serving it.
      </PageHeader>
      <div className="max-w-[46rem] rounded-[16px] border border-ember-orange/30 bg-ivory px-5 py-5">
        <p className="font-heading text-[15px] text-graphite">{detail}</p>
        <p className="mt-2 text-[13.5px] leading-[1.6] text-steel">{hint}</p>
        <button
          type="button"
          onClick={() => start(() => router.refresh())}
          disabled={pending}
          className="mt-4 cursor-pointer rounded-full bg-graphite px-4 py-2 font-heading text-[13px] text-canvas-white transition-opacity duration-200 disabled:opacity-50"
        >
          {pending ? "Asking again…" : "Retry"}
        </button>
      </div>
    </div>
  );
}
