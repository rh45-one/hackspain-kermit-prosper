"use client";

import { cn } from "@/lib/utils";

/**
 * The drawing surface both views share.
 *
 * Edges are SVG, nodes are HTML on top of them. Pure SVG would mean no text
 * truncation, no Tailwind and no focus ring; pure HTML would mean no curves.
 * Both layers use the same pixel space, so the two never drift apart.
 */
export function GraphCanvas({
  width,
  height,
  children,
  label,
}: {
  width: number;
  height: number;
  children: React.ReactNode;
  label: string;
}) {
  return (
    <div className="-mx-1 overflow-x-auto px-1 pb-2">
      <div
        role="group"
        aria-label={label}
        className="relative"
        style={{ width, height, minWidth: width }}
      >
        {children}
      </div>
    </div>
  );
}

/** The header that sits above a column of nodes. */
export function ColumnTitle({
  x,
  w,
  title,
  note,
  align = "left",
}: {
  x: number;
  w: number;
  title: string;
  note: string;
  align?: "left" | "right";
}) {
  return (
    <div
      className={cn("absolute top-0", align === "right" ? "text-right" : "text-left")}
      style={{ left: x, width: w }}
    >
      <p className="font-heading text-[11px] leading-none tracking-[0.09em] text-brass uppercase">
        {title}
      </p>
      <p className="mt-1.5 text-[11px] leading-none text-quiet">{note}</p>
    </div>
  );
}

/**
 * Keyframes for the two things that move: strokes drawing themselves in, and
 * the single `now` route breathing so it cannot be mistaken for the rest.
 *
 * Kept next to the only components that use them and prefixed, rather than
 * added to the app's shared stylesheet, which other people are editing today.
 */
export function GraphKeyframes() {
  return (
    <style>{`
@keyframes clinic-graph-draw {
  from { stroke-dashoffset: 1; }
  to { stroke-dashoffset: 0; }
}
@keyframes clinic-graph-fade {
  from { opacity: 0; }
}
@keyframes clinic-graph-breathe {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.clinic-graph-draw {
  stroke-dashoffset: 1;
  animation: clinic-graph-draw 900ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.clinic-graph-fade {
  animation: clinic-graph-fade 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.clinic-graph-breathe {
  animation: clinic-graph-breathe 2.4s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .clinic-graph-draw,
  .clinic-graph-fade,
  .clinic-graph-breathe {
    animation: none !important;
    stroke-dashoffset: 0 !important;
    opacity: 1 !important;
  }
}
`}</style>
  );
}
