"use client";

import { type CSSProperties, type PointerEvent, useState } from "react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import {
  bargeInCount,
  FLUSH_P50_SECONDS,
  FLUSH_WITHIN_WINDOW,
  HOURLY_LOAD,
  outcomeMix,
  refusalReasons,
} from "@/lib/metrics";
import { CALL_CAPACITY } from "@/lib/types";

const EMBER = "#e76432";
const BRASS = "#806b36";
const MIST = "#dcdfd9";
const GRAPHITE = "#1d211f";
const QUIET = "#777e78";

function linePath(
  values: number[],
  max: number,
  width: number,
  height: number,
  padX = 0,
): string {
  if (values.length < 2) {
    return "";
  }
  return values
    .map((value, index) => {
      const x = padX + (index / (values.length - 1)) * width;
      const y = height - (value / max) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

function LoadChart() {
  const innerWidth = 560;
  const height = 130;
  const padX = 14;
  const max = CALL_CAPACITY;
  const sockets = HOURLY_LOAD.map((point) => point.sockets);
  const submissions = HOURLY_LOAD.map((point) => point.submissions);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [pinnedIndex, setPinnedIndex] = useState<number | null>(null);
  const selectedIndex = hoveredIndex ?? pinnedIndex;

  function xAt(index: number) {
    return padX + (index / (HOURLY_LOAD.length - 1)) * innerWidth;
  }

  function yAt(value: number) {
    return height - (value / max) * height;
  }

  function pointFromPointer(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    return Math.round(ratio * (HOURLY_LOAD.length - 1));
  }

  const selected =
    selectedIndex === null ? null : HOURLY_LOAD[selectedIndex];
  const selectedX = selectedIndex === null ? 0 : xAt(selectedIndex);
  const tooltipX =
    selectedX > innerWidth / 2 ? selectedX - 126 : selectedX + 10;

  return (
    <svg
      viewBox={`0 0 ${innerWidth + padX * 2} ${height + 20}`}
      className="h-auto w-full touch-pan-y overflow-visible outline-none"
      role="img"
      aria-label="Sockets concurrentes y envíos por hora"
      onPointerMove={(event) => setHoveredIndex(pointFromPointer(event))}
      onPointerLeave={() => setHoveredIndex(null)}
      onPointerDown={(event) => {
        const index = pointFromPointer(event);
        setPinnedIndex((current) => (current === index ? null : index));
      }}
    >
      {[0.25, 0.5, 0.75, 1].map((share) => (
        <line
          key={share}
          x1={padX}
          x2={innerWidth + padX}
          y1={height * share}
          y2={height * share}
          stroke={MIST}
          strokeWidth="0.5"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      <path
        d={linePath(sockets, max, innerWidth, height, padX)}
        data-chart-line="primary"
        pathLength="1"
        fill="none"
        stroke={EMBER}
        strokeWidth="2"
        strokeDasharray="1"
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={linePath(submissions, max, innerWidth, height, padX)}
        data-chart-line="secondary"
        pathLength="1"
        fill="none"
        stroke={BRASS}
        strokeWidth="1.5"
        strokeDasharray="0.012 0.012"
        vectorEffect="non-scaling-stroke"
      />
      {HOURLY_LOAD.map((point, index) => (
        <circle
          key={`point-${point.hour}`}
          data-chart-point=""
          cx={xAt(index)}
          cy={yAt(point.sockets)}
          r={selectedIndex === index ? 3.5 : 2}
          fill={selectedIndex === index ? "#fffefb" : EMBER}
          stroke={EMBER}
          strokeWidth={selectedIndex === index ? 2 : 0}
          style={{ "--point-index": index } as CSSProperties}
          tabIndex={0}
          role="button"
          aria-label={`${point.hour}:00, ${point.sockets} sockets, ${point.submissions} envíos`}
          onFocus={() => setPinnedIndex(index)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setPinnedIndex(index);
            }
          }}
        />
      ))}
      {selected ? (
        <g className="pointer-events-none">
          <line
            x1={selectedX}
            x2={selectedX}
            y1="0"
            y2={height}
            stroke={GRAPHITE}
            strokeOpacity="0.18"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
          <g transform={`translate(${tooltipX} 5)`}>
            <rect
              width="116"
              height="39"
              rx="6"
              fill="#fffefb"
              stroke={MIST}
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
            <text x="9" y="15" fill={GRAPHITE} fontSize="9" fontWeight="600">
              {selected.hour}:00
            </text>
            <text x="9" y="29" fill={QUIET} fontSize="8">
              {selected.sockets} sockets · {selected.submissions} envíos
            </text>
          </g>
        </g>
      ) : null}
      {HOURLY_LOAD.map((point, index) =>
        index % 2 === 0 ? (
          <text
            key={point.hour}
            x={padX + (index / (HOURLY_LOAD.length - 1)) * innerWidth}
            y={height + 16}
            textAnchor="middle"
            fill={QUIET}
            fontSize="10"
          >
            {point.hour}h
          </text>
        ) : null,
      )}
    </svg>
  );
}

function CapacityRing({ active }: { active: number }) {
  const radius = 46;
  const share = Math.min(active / CALL_CAPACITY, 1);
  const offset = 1 - share;

  return (
    <svg viewBox="0 0 120 120" className="mx-auto size-36" role="img" aria-label="Capacidad">
      <circle
        cx="60"
        cy="60"
        r={radius}
        fill="none"
        stroke={MIST}
        strokeWidth="5"
      />
      <circle
        cx="60"
        cy="60"
        r={radius}
        fill="none"
        stroke={EMBER}
        strokeWidth="5"
        strokeLinecap="round"
        data-chart-ring=""
        pathLength="1"
        strokeDasharray="1"
        style={{ "--ring-offset": offset } as CSSProperties}
        transform="rotate(-90 60 60)"
      />
      <text
        x="60"
        y="56"
        textAnchor="middle"
        fill={GRAPHITE}
        fontSize="22"
        fontFamily="var(--font-polysans), sans-serif"
      >
        {active}/{CALL_CAPACITY}
      </text>
      <text x="60" y="74" textAnchor="middle" fill={QUIET} fontSize="9">
        sockets
      </text>
    </svg>
  );
}

function OutcomeBars() {
  const mix = outcomeMix();
  const [selected, setSelected] = useState<string | null>(null);
  const strokes: Record<string, string> = {
    BOOKED: BRASS,
    CANCELLED: GRAPHITE,
    REFUSED: QUIET,
    DIVERTED: EMBER,
  };

  return (
    <ul className="space-y-3">
      {mix.map((row) => {
        const active = selected === row.key;
        return (
        <li key={row.key} data-outcome-row="">
          <button
            type="button"
            aria-pressed={active}
            onClick={() => setSelected(active ? null : row.key)}
            className="group w-full rounded-md px-1 py-1 text-left transition-colors duration-200 hover:bg-fog focus-visible:outline-none"
          >
            <span className="mb-1.5 flex justify-between font-heading text-[13px] text-graphite">
              <span>{row.key}</span>
              <span className="text-quiet tabular-nums">
                {row.count}
                <span
                  className={`ml-1.5 inline-block overflow-hidden align-bottom text-[11px] transition-[max-width,opacity] duration-200 ${
                    active ? "max-w-12 opacity-100" : "max-w-0 opacity-0"
                  }`}
                >
                  {Math.round(row.share * 100)}%
                </span>
              </span>
            </span>
            <span className="block h-1 overflow-hidden rounded-full bg-mist">
              <span
                data-outcome-fill=""
                className="block h-full rounded-full transition-[filter] duration-200 group-hover:brightness-90"
                style={{
                  width: `${Math.max(row.share * 100, row.count ? 4 : 0)}%`,
                  background: strokes[row.key],
                }}
              />
            </span>
          </button>
        </li>
        );
      })}
    </ul>
  );
}

export function ObservatoryCharts() {
  const { activeCount, calls, appointments } = useFrontdesk();
  const refusals = refusalReasons(appointments);
  const barges = bargeInCount(calls);
  const flushPct = Math.round(FLUSH_WITHIN_WINDOW * 100);

  return (
    <div data-reveal="fade">
      <div className="grid gap-4 lg:grid-cols-3">
        <article
          data-reveal=""
          className="surface rounded-[18px] p-[var(--card-padding)] lg:col-span-3"
        >
          <p className="font-heading text-[17px] text-graphite">Carga de sockets</p>
          <p className="mt-1 text-[12px] text-quiet">
            Concurrentes <span className="text-ember-orange">—</span> envíos{" "}
            <span className="text-brass">- -</span> · Europe/Madrid
          </p>
          <div className="mt-7">
            <LoadChart />
          </div>
        </article>
        <article
          data-reveal=""
          data-delay="1"
          className="surface rounded-[18px] p-[var(--card-padding)]"
        >
          <p className="font-heading text-[17px] text-graphite">Capacidad</p>
          <CapacityRing active={activeCount} />
          <p className="text-center text-[12px] text-quiet">
            Techo 10 · el backend admite 10–20
          </p>
        </article>
        <article
          data-reveal=""
          data-delay="2"
          className="surface rounded-[18px] p-[var(--card-padding)] lg:col-span-2"
        >
          <p className="font-heading text-[17px] text-graphite">
            Resultado del agente
          </p>
          <p className="mt-1 text-[13px] text-quiet">
            Verbos cerrados del record.
          </p>
          <div className="mt-7">
            <OutcomeBars />
          </div>
        </article>
      </div>

      <dl
        data-reveal=""
        data-delay="2"
        className="mt-4 grid grid-cols-1 overflow-hidden rounded-[14px] border border-mist bg-canvas-white text-[12px] shadow-[var(--shadow-sm)] sm:grid-cols-3"
      >
        <div className="p-5 sm:border-r sm:border-mist">
          <dt className="font-heading tracking-[0.04em] text-quiet uppercase">Flush &lt; 30s</dt>
          <dd className="mt-1.5 font-heading text-[18px] text-graphite">
            {flushPct}%
            <span className="ml-2 text-[13px] text-quiet">
              p50 {FLUSH_P50_SECONDS.toFixed(1)}s
            </span>
          </dd>
        </div>
        <div className="border-t border-mist p-5 sm:border-t-0 sm:border-r">
          <dt className="font-heading tracking-[0.04em] text-quiet uppercase">Recusas</dt>
          <dd className="mt-1.5 text-steel">
            {refusals.length === 0
              ? "—"
              : refusals.map((item) => item.label).join(" · ")}
          </dd>
        </div>
        <div className="border-t border-mist p-5 sm:border-t-0">
          <dt className="font-heading tracking-[0.04em] text-quiet uppercase">Barge-in vivo</dt>
          <dd className="mt-1.5 font-heading text-[18px] text-ember-orange">
            {barges}
          </dd>
        </div>
      </dl>
    </div>
  );
}
