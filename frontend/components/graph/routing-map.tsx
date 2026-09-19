"use client";

import { useMemo } from "react";

import { ColumnTitle, GraphCanvas } from "@/components/graph/graph-canvas";
import {
  plural,
  URGENCY,
  type Escalation,
  type RoutingLayout,
  type Urgency,
} from "@/lib/graph";
import { cn } from "@/lib/utils";

type Props = {
  layout: RoutingLayout;
  /** True when an urgency filter is on, so an empty listener says why. */
  filtered: boolean;
  active: string | null;
  lit: Set<string> | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
};

function breakdown(incoming: Escalation[]): string {
  const counts: Record<Urgency, number> = { now: 0, today: 0, queue: 0 };
  for (const escalation of incoming) counts[escalation.urgency] += 1;
  const parts = (Object.keys(counts) as Urgency[])
    .filter((key) => counts[key] > 0)
    .map((key) => `${counts[key]} ${URGENCY[key].word.toLowerCase()}`);
  return parts.join(" · ");
}

export function RoutingMap({ layout, filtered, active, lit, onHover, onSelect }: Props) {
  const [dimEdges, litEdges] = useMemo(() => {
    if (!lit) return [layout.edges, []];
    const on = layout.edges.filter((e) => e.source === active || e.target === active);
    const off = layout.edges.filter((e) => !on.includes(e));
    return [off, on];
  }, [layout.edges, lit, active]);

  return (
    <GraphCanvas
      width={layout.width}
      height={layout.height}
      label="The eighteen ways to end without a booking, and who hears about each"
    >
      <svg
        className="absolute inset-0 overflow-visible"
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        aria-hidden
      >
        {[dimEdges, litEdges].map((group, pass) => (
          <g key={pass}>
            {group.map((edge, i) => {
              const urgency = URGENCY[edge.urgency ?? "queue"];
              return (
                <path
                  key={edge.id}
                  className={cn(
                    "clinic-graph-fade",
                    edge.urgency === "now" && !lit && "clinic-graph-breathe",
                  )}
                  d={edge.d}
                  fill="none"
                  stroke={urgency.ink}
                  strokeWidth={pass === 1 ? urgency.width + 1 : urgency.width}
                  strokeDasharray={urgency.dash}
                  strokeOpacity={lit ? (pass === 1 ? 0.95 : 0.06) : edge.urgency === "now" ? 1 : 0.42}
                  strokeLinecap="round"
                  style={{
                    animationDelay: `${140 + i * 26}ms`,
                    transition: "stroke-opacity 200ms ease, stroke-width 200ms ease",
                  }}
                />
              );
            })}
          </g>
        ))}
      </svg>

      <ColumnTitle
        x={0}
        w={layout.reasons[0]?.w ?? 330}
        title="What can fail"
        note={`${plural(layout.reasons.length, "ending", "endings")} without a booking`}
      />
      <ColumnTitle
        x={layout.roles[0]?.x ?? 0}
        w={layout.roles[0]?.w ?? 286}
        title="Who answers"
        // Los dos números, porque el de arriba solo mentía por omisión: once
        // reciben rutas y el resto entra cuando una de esas once no puede, y
        // decir once a secas hacía que faltaran treinta y dos personas que
        // estaban dibujadas ahí al lado.
        note={`${layout.roles.length + layout.chain.length} people · ${layout.roles.length} receive routes`}
        align="right"
      />

      {layout.reasons.map((row) => {
        const urgency = URGENCY[row.escalation.urgency];
        const id = row.node.id;
        const dim = Boolean(lit) && !lit?.has(id);
        return (
          <button
            key={id}
            type="button"
            onMouseEnter={() => onHover(id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(id)}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(id)}
            aria-pressed={active === id}
            title={row.escalation.detail}
            className={cn(
              "clinic-graph-fade absolute flex cursor-pointer items-center gap-2.5 overflow-hidden rounded-[9px] border border-mist bg-canvas-white pr-3 pl-0 text-left outline-none",
              "transition-[opacity,box-shadow,transform,border-color,top,left] duration-300 ease-out",
              "hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-brass/40",
              active === id && "shadow-[var(--shadow-md)]",
              dim && "opacity-25",
            )}
            style={{
              left: row.x,
              top: row.y,
              width: row.w,
              height: row.h,
              boxShadow: active === id ? `0 0 0 1.5px ${urgency.ink}, var(--shadow-md)` : undefined,
              animationDelay: `${140 + (row.y % 900) * 0.4}ms`,
            }}
          >
            <span
              aria-hidden
              className="h-full w-[3px] shrink-0"
              style={{ background: urgency.ink }}
            />
            <span className="truncate font-heading text-[13px] leading-tight text-graphite">
              {row.node.label}
            </span>
            <span
              className="ml-auto shrink-0 rounded-[4px] px-1.5 py-px font-heading text-[9.5px] tracking-[0.06em] uppercase"
              style={{ background: `${urgency.ink}14`, color: urgency.ink }}
            >
              {urgency.word}
            </span>
          </button>
        );
      })}

      {layout.roles.map((seat) => {
        const id = seat.node.id;
        const dim = Boolean(lit) && !lit?.has(id);
        const orphan = seat.incoming.length === 0;
        return (
          <button
            key={id}
            type="button"
            onMouseEnter={() => onHover(id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(id)}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(id)}
            aria-pressed={active === id}
            className={cn(
              "clinic-graph-fade absolute flex cursor-pointer flex-col justify-center overflow-hidden rounded-[13px] border px-4 text-left outline-none",
              "transition-[opacity,box-shadow,transform,border-color,top,left] duration-300 ease-out",
              "hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-brass/40",
              orphan ? "border-dashed border-mist bg-fog" : "border-mist bg-canvas-white",
              active === id && "border-graphite/30 shadow-[var(--shadow-md)]",
              dim && "opacity-25",
            )}
            style={{
              left: seat.x,
              top: seat.y,
              width: seat.w,
              height: seat.h,
              animationDelay: `${260 + (seat.y % 900) * 0.3}ms`,
            }}
          >
            <span
              className={cn(
                "font-heading text-[15px] leading-tight",
                orphan ? "text-quiet" : "text-graphite",
              )}
            >
              {seat.node.label}
            </span>
            <span className="mt-1 line-clamp-2 text-[11.5px] leading-[1.35] text-steel">
              {seat.node.detail}
            </span>
            <span className="mt-1.5 font-mono text-[10.5px] tracking-[0.02em] text-quiet">
              {orphan
                ? filtered
                  ? "nothing with this filter"
                  : "no reason reaches them"
                : `${plural(seat.incoming.length, "route", "routes")} · ${breakdown(seat.incoming)}`}
            </span>
          </button>
        );
      })}

      {/*
        Las cadenas de cobertura: quién sustituye a quién.
        Más pequeñas y sin borde de aviso a propósito — a esta gente no le
        llega ninguna ruta y no es un problema, es que entran cuando falla el
        de al lado. Dibujarlas igual que a los que sí escuchan haría que
        cuarenta y tres cajas se leyeran como cuarenta y tres iguales.
      */}
      {layout.chain.map((seat) => {
        const id = seat.node.id;
        const dim = Boolean(lit) && !lit?.has(id);
        return (
          <button
            key={id}
            type="button"
            onMouseEnter={() => onHover(id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(id)}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(id)}
            aria-pressed={active === id}
            className={cn(
              "clinic-graph-fade absolute flex cursor-pointer flex-col justify-center overflow-hidden rounded-[11px] border px-3 text-left outline-none",
              "border-mist/70 bg-canvas-white/70",
              "transition-[opacity,box-shadow,transform,border-color,top,left] duration-300 ease-out",
              "hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-brass/40",
              active === id && "border-graphite/30 bg-canvas-white shadow-[var(--shadow-md)]",
              dim && "opacity-20",
            )}
            style={{
              left: seat.x,
              top: seat.y,
              width: seat.w,
              height: seat.h,
              animationDelay: `${320 + (seat.y % 900) * 0.3}ms`,
            }}
          >
            <span className="font-heading text-[13.5px] leading-tight text-graphite">
              {seat.node.label}
            </span>
            <span className="mt-0.5 line-clamp-2 text-[11px] leading-[1.3] text-steel">
              {seat.node.detail}
            </span>
          </button>
        );
      })}
    </GraphCanvas>
  );
}
