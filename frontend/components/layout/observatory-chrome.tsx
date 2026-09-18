"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, CalendarDays, ContactRound, Radio, SlidersHorizontal } from "lucide-react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { formatMadrid } from "@/lib/timezone";
import { CALL_CAPACITY } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/calls", label: "Llamadas", icon: Radio },
  { href: "/calendar", label: "Calendario", icon: CalendarDays },
  { href: "/patients", label: "Pacientes", icon: ContactRound },
  { href: "/settings", label: "Agente", icon: SlidersHorizontal },
] as const;

export function ObservatoryChrome() {
  const pathname = usePathname();
  const { settings, tunnelConfigured, capacityLabel, activeCount } = useFrontdesk();
  const [now, setNow] = useState("");

  useEffect(() => {
    const tick = () => setNow(formatMadrid(new Date(), "HH:mm:ss"));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b border-mist/90 bg-background/95 px-[var(--page-gutter)] backdrop-blur-md">
      <div className="mx-auto flex h-[72px] max-w-[var(--page-max-width)] items-center justify-between gap-5">
        <Link
          href="/calls"
          className="group flex shrink-0 items-center gap-3 rounded-lg outline-none"
          aria-label="ClinicReflow, ir al monitor"
        >
          <span className="grid size-9 place-items-center rounded-[10px] bg-graphite text-canvas-white shadow-sm transition-transform duration-200 group-hover:-translate-y-0.5">
            <Activity className="size-4" strokeWidth={1.8} />
          </span>
          <span>
            <span className="block font-heading text-[11px] leading-none tracking-[0.04em] text-brass uppercase">
              ClinicReflow
            </span>
            <span className="mt-1.5 block font-heading text-[15px] leading-none text-graphite">
              Clínica Arenal
            </span>
          </span>
        </Link>

        <nav className="hidden items-center gap-1 rounded-xl border border-mist bg-canvas-white p-1 shadow-[var(--shadow-sm)] md:flex">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-3.5 py-2 font-heading text-[14px] leading-none text-steel transition-[color,background-color,box-shadow] duration-200 hover:bg-fog hover:text-graphite focus-visible:outline-none",
                  active && "bg-graphite text-canvas-white shadow-sm hover:bg-graphite hover:text-canvas-white",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-3 sm:gap-5">
          <p
            className={cn(
              "hidden items-center gap-2 font-heading text-[12px] leading-none text-quiet lg:flex",
              tunnelConfigured && "text-steel",
            )}
            title={settings.tunnelUrl || "Sin túnel"}
          >
            <span
              className={cn(
                "size-1.5 rounded-full bg-quiet/60",
                tunnelConfigured && "bg-brass",
              )}
            />
            {tunnelConfigured ? "Túnel listo" : "Sin túnel"}
          </p>
          <p className="hidden font-mono text-[11px] leading-none text-quiet xl:block">
            {now || "Europe/Madrid"}
          </p>
          <span className="rounded-lg border border-mist bg-canvas-white px-3 py-2 font-heading text-[12px] leading-none text-graphite shadow-sm sm:px-3.5">
            <span className="mr-1.5 text-brass">●</span>
            <span className="sm:hidden">{activeCount}/{CALL_CAPACITY}</span>
            <span className="hidden sm:inline">{capacityLabel}</span>
          </span>
        </div>
      </div>
      <nav className="mx-auto grid max-w-[var(--page-max-width)] grid-cols-4 border-t border-mist/80 md:hidden">
        {NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "relative flex min-w-0 items-center justify-center gap-1.5 px-1 py-3 font-heading text-[11px] leading-none text-quiet transition-colors hover:text-graphite focus-visible:outline-none sm:text-[12px]",
                active && "text-graphite after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-ember-orange",
              )}
            >
              <Icon className="size-3.5 shrink-0" strokeWidth={1.8} />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
