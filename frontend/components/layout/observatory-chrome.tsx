"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ContactRound,
  Radio,
  SlidersHorizontal,
  Trophy,
} from "lucide-react";

import { ProntoMark } from "@/components/brand/pronto-mark";
import { useFrontdesk } from "@/components/frontdesk-provider";
import { formatMadrid } from "@/lib/timezone";
import { CALL_CAPACITY } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/calls", label: "Llamadas", icon: Radio, match: (path: string) => path === "/calls" || path.startsWith("/calls/") },
  {
    href: "/leaderboard",
    label: "Resultados",
    icon: Trophy,
    match: (path: string) =>
      path === "/leaderboard" || path.startsWith("/leaderboard/"),
  },
  {
    href: "/patients",
    label: "Clínica",
    icon: ContactRound,
    match: (path: string) =>
      path === "/patients" ||
      path.startsWith("/patients/") ||
      path === "/calendar" ||
      path.startsWith("/calendar/") ||
      path === "/directory" ||
      path.startsWith("/directory/"),
  },
  { href: "/settings", label: "Agente", icon: SlidersHorizontal, match: (path: string) => path === "/settings" || path.startsWith("/settings/") },
] as const;

export function ObservatoryChrome() {
  const pathname = usePathname();
  const { settings, tunnelConfigured, capacityLabel, activeCount,
    demo, connectionError, clinicError, loading } = useFrontdesk();
  const [now, setNow] = useState("");
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const tick = () => setNow(formatMadrid(new Date(), "HH:mm:ss"));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 8);
    queueMicrotask(update);
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b border-mist/90 bg-background/95 px-[var(--page-gutter)] backdrop-blur-md transition-[background-color,box-shadow] duration-300",
        scrolled && "bg-background/98 shadow-[0_10px_30px_rgb(29_33_31/0.06)]",
      )}
    >
      <div className="mx-auto flex h-[72px] max-w-[var(--page-max-width)] items-center justify-between gap-5">
        <Link
          href="/"
          className="group flex shrink-0 items-center gap-3 rounded-lg outline-none active:scale-[0.99]"
          aria-label="Pronto, ir al inicio"
        >
          <span className="grid size-9 place-items-center rounded-[10px] bg-graphite text-canvas-white shadow-sm transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-active:translate-y-0">
            <ProntoMark className="size-[22px]" />
          </span>
          <span>
            <span className="block font-heading text-[15px] leading-none tracking-[-0.04em] text-graphite">
              Pronto
            </span>
            <span className="mt-1.5 block font-heading text-[11px] leading-none tracking-[0.04em] text-steel">
              Clínica Arenal
            </span>
          </span>
        </Link>

        <nav className="hidden items-center gap-1 rounded-xl border border-mist bg-canvas-white p-1 shadow-[var(--shadow-sm)] md:flex">
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-3.5 py-2 font-heading text-[14px] leading-none text-steel transition-[color,background-color,box-shadow,transform] duration-200 hover:bg-fog hover:text-graphite focus-visible:outline-none active:scale-[0.97]",
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
            title={demo ? settings.tunnelUrl || "Sin enlace de prueba" : "Consulta en tiempo real"}
          >
            <span
              className={cn(
                "size-1.5 rounded-full bg-quiet/60",
                tunnelConfigured && "bg-brass",
              )}
            />
            {demo ? (tunnelConfigured ? "Enlace de prueba" : "Sin enlace de prueba") : "Consulta en vivo"}
          </p>
          <p className="hidden text-[11px] leading-none text-quiet xl:block">
            {now || "Hora Madrid"}
          </p>
          <span className="rounded-lg border border-mist bg-canvas-white px-3 py-2 font-heading text-[12px] leading-none text-graphite shadow-sm sm:px-3.5">
            <span className="mr-1.5 text-brass">●</span>
            <span className="sm:hidden">{activeCount}{demo ? `/${CALL_CAPACITY}` : " abiertas"}</span>
            <span className="hidden sm:inline">{capacityLabel}</span>
          </span>
        </div>
      </div>
      <nav className="mx-auto grid max-w-[var(--page-max-width)] grid-cols-4 border-t border-mist/80 md:hidden">
        {NAV.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group relative flex min-w-0 items-center justify-center gap-1.5 px-1 py-3 font-heading text-[11px] leading-none text-quiet transition-colors hover:text-graphite focus-visible:outline-none active:bg-ash/60 sm:text-[12px]",
                active && "text-graphite after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-ember-orange",
              )}
            >
              <Icon
                className={cn(
                  "size-3.5 shrink-0 transition-transform duration-200 group-active:scale-90",
                  active && "-translate-y-px",
                )}
                strokeWidth={1.8}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="mx-auto max-w-[var(--page-max-width)] py-2 text-[12px] text-steel" role="status">
        {demo ? "Modo demo · conversaciones de ejemplo" : loading ? "Conectando con el asistente…" :
          connectionError ? `Llamadas: ${connectionError}` : "Datos actualizados cada pocos segundos · solo lectura"}
        {!demo && clinicError ? <p role="alert">Clínica: {clinicError}</p> : null}
      </div>
    </header>
  );
}
