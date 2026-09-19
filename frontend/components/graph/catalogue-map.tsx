"use client";

import { useMemo } from "react";

import { ColumnTitle, GraphCanvas } from "@/components/graph/graph-canvas";
import {
  EDGE_INK,
  languageName,
  plural,
  specialtyLabel,
  TONE,
  type CatalogueLayout,
  type ClinicGraph,
  type GraphNode,
  type PlacedNode,
} from "@/lib/graph";
import { cn } from "@/lib/utils";

type Props = {
  graph: ClinicGraph;
  layout: CatalogueLayout;
  active: string | null;
  lit: Set<string> | null;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
};

/** Doctors reachable from a site or a specialty, and how many are on leave. */
function coverage(graph: ClinicGraph, id: string) {
  const ids = new Set(
    graph.edges
      .filter((e) => (e.kind === "works_at" || e.kind === "covers") && e.target === id)
      .map((e) => e.source),
  );
  const providers = graph.nodes.filter((n) => n.kind === "provider" && ids.has(n.id));
  return { total: providers.length, away: providers.filter((n) => !n.available).length };
}

function NodeCard({
  placed,
  graph,
  dim,
  selected,
  onHover,
  onSelect,
}: {
  placed: PlacedNode;
  graph: ClinicGraph;
  dim: boolean;
  selected: boolean;
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
}) {
  const node: GraphNode = placed.node;
  const ink = TONE[node.tone].ink;
  const away = !node.available;

  return (
    <button
      type="button"
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(node.id)}
      onBlur={() => onHover(null)}
      onClick={() => onSelect(node.id)}
      aria-pressed={selected}
      className={cn(
        "clinic-graph-fade absolute flex cursor-pointer flex-col justify-center overflow-hidden rounded-[11px] border bg-canvas-white px-3 text-left outline-none",
        "transition-[opacity,box-shadow,transform,border-color] duration-200 ease-out",
        "hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-brass/40",
        away ? "border-dashed border-mist bg-fog" : "border-mist",
        selected && "border-transparent shadow-[var(--shadow-md)]",
        dim && "opacity-25",
      )}
      style={{
        left: placed.x,
        top: placed.y,
        width: placed.w,
        height: placed.h,
        boxShadow: selected ? `0 0 0 1.5px ${ink}, var(--shadow-md)` : undefined,
        animationDelay: `${Math.min(placed.y, 520) * 0.35}ms`,
      }}
    >
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="size-1.5 shrink-0 rounded-full"
          style={{ background: away ? "transparent" : ink, boxShadow: away ? `inset 0 0 0 1.5px ${ink}66` : undefined }}
        />
        <span
          className={cn(
            "truncate font-heading text-[13px] leading-tight",
            away ? "text-quiet" : "text-graphite",
          )}
        >
          {node.kind === "specialty" ? specialtyLabel(node) : node.label}
        </span>
      </span>
      <Sub node={node} graph={graph} />
    </button>
  );
}

function Sub({ node, graph }: { node: GraphNode; graph: ClinicGraph }) {
  if (node.kind === "provider") {
    const languages = node.meta.languages ?? [];
    return (
      <span className="mt-1 flex items-center gap-1.5 pl-[14px]">
        {node.available ? null : (
          <span className="rounded-[4px] bg-ember-orange/12 px-1.5 py-px font-heading text-[9.5px] tracking-[0.06em] text-ember-orange uppercase">
            De baja
          </span>
        )}
        {languages.map((code) => (
          <span
            key={code}
            title={languageName(code)}
            className="rounded-[4px] bg-ash px-1.5 py-px font-mono text-[9.5px] tracking-[0.04em] text-steel uppercase"
          >
            {code}
          </span>
        ))}
      </span>
    );
  }

  const { total, away } = coverage(graph, node.id);
  return (
    <span className="mt-1 block truncate pl-[14px] text-[11px] leading-tight text-quiet">
      {node.kind === "site" && node.detail ? `${node.detail} · ` : ""}
      {total === 0 ? "no clinicians assigned" : plural(total, "clinician", "clinicians")}
      {away > 0 ? `, ${away} on leave` : ""}
    </span>
  );
}

export function CatalogueMap({ graph, layout, active, lit, onHover, onSelect }: Props) {
  // Lit strokes are painted after the dim ones so a highlighted path is never
  // buried under the forty-odd it is meant to stand out from.
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
      label="Who works where and who covers what"
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
            {group.map((edge, i) => (
              <path
                key={edge.id}
                className="clinic-graph-draw"
                d={edge.d}
                fill="none"
                pathLength={1}
                strokeDasharray={1}
                stroke={EDGE_INK[edge.kind]}
                strokeWidth={pass === 1 ? 2 : 1.1}
                strokeOpacity={lit ? (pass === 1 ? 0.95 : 0.07) : 0.24}
                strokeLinecap="round"
                style={{
                  animationDelay: `${120 + i * 9}ms`,
                  transition: "stroke-opacity 200ms ease, stroke-width 200ms ease",
                }}
              />
            ))}
          </g>
        ))}
      </svg>

      {layout.columns.map((column) => (
        <ColumnTitle
          key={column.id}
          x={column.x}
          w={column.w}
          title={column.title}
          note={column.note}
          align={column.id === "specialty" ? "right" : "left"}
        />
      ))}

      {layout.nodes.map((placed) => (
        <NodeCard
          key={placed.node.id}
          placed={placed}
          graph={graph}
          dim={Boolean(lit) && !lit?.has(placed.node.id)}
          selected={active === placed.node.id}
          onHover={onHover}
          onSelect={onSelect}
        />
      ))}
    </GraphCanvas>
  );
}
