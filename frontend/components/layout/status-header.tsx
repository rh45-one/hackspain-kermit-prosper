"use client";

import { useEffect, useState } from "react";
import { Radio } from "lucide-react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { Badge } from "@/components/ui/badge";
import { formatMadrid } from "@/lib/timezone";

export function StatusHeader() {
  const { settings, tunnelConfigured, capacityLabel, activeCount } =
    useFrontdesk();
  const [now, setNow] = useState("");

  useEffect(() => {
    const tick = () => setNow(formatMadrid(new Date(), "HH:mm:ss"));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-slate-200 bg-white px-6">
      <div className="flex min-w-0 items-center gap-3">
        <span
          className={
            tunnelConfigured
              ? "inline-flex shrink-0 items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium whitespace-nowrap text-emerald-800 ring-1 ring-emerald-100"
              : "inline-flex shrink-0 items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium whitespace-nowrap text-slate-600 ring-1 ring-slate-200"
          }
        >
          <span
            className={
              tunnelConfigured
                ? "size-1.5 rounded-full bg-emerald-500"
                : "size-1.5 rounded-full bg-slate-400"
            }
          />
          {tunnelConfigured ? "Túnel listo" : "Sin túnel"}
        </span>
        {tunnelConfigured ? (
          <span className="hidden font-mono text-xs text-slate-500 lg:inline">
            {settings.tunnelUrl}
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-3">
        <Badge
          variant="outline"
          className={
            activeCount > 0
              ? "border-teal-200 bg-teal-50 text-teal-900"
              : undefined
          }
        >
          <Radio className="size-3" />
          {capacityLabel}
        </Badge>
        <span className="shrink-0 font-mono text-xs text-slate-500">
          {now ? `${now} Madrid` : "Europe/Madrid"}
        </span>
      </div>
    </header>
  );
}
