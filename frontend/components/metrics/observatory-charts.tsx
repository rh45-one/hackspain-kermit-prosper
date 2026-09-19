"use client";

import { type CSSProperties, type PointerEvent, useState } from "react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import {
  HOURLY_LOAD,
  outcomeMix,
} from "@/lib/metrics";
import { OUTCOME_STYLES } from "@/lib/outcomes";
import { CALL_CAPACITY, type ReceptionOutcome } from "@/lib/types";

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
  const liveCalls = HOURLY_LOAD.map((point) => point.sockets);
  const closedJobs = HOURLY_LOAD.map((point) => point.submissions);
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
    selectedX > innerWidth / 2 ? selectedX - 146 : selectedX + 10;

  return (
    <svg
      viewBox={`0 0 ${innerWidth + padX * 2} ${height + 20}`}
      className="h-auto w-full touch-pan-y overflow-visible outline-none"
      role="img"
      aria-label="Llamadas a la vez y gestiones cerradas por hora"
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
        d={linePath(liveCalls, max, innerWidth, height, padX)}
        data-chart-line="primary"
        pathLength="1"
        fill="none"
        stroke={EMBER}
        strokeWidth="2"
        strokeDasharray="1"
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={linePath(closedJobs, max, innerWidth, height, padX)}
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
          aria-label={`${point.hour}:00, ${point.sockets} llamadas a la vez, ${point.submissions} gestiones cerradas`}
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
              width="136"
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
              {selected.sockets} a la vez · {selected.submissions} cerradas
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
    <svg
      viewBox="0 0 120 120"
      className="mx-auto size-36"
      role="img"
      aria-label="Líneas de recepción ocupadas"
    >
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
        líneas
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
        const label =
          OUTCOME_STYLES[row.key as ReceptionOutcome]?.label ?? row.key;
        return (
          <li key={row.key} data-outcome-row="">
            <button
              type="button"
              aria-pressed={active}
              onClick={() => setSelected(active ? null : row.key)}
              className="group w-full rounded-md px-1 py-1 text-left transition-colors duration-200 hover:bg-fog focus-visible:outline-none"
            >
              <span className="mb-1.5 flex justify-between font-heading text-[13px] text-graphite">
                <span>{label}</span>
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
  const { activeCount, calls, demo } = useFrontdesk();
  const summaries = calls.flatMap((call) =>
    call.diagnostic ? [call.diagnostic] : [],
  );
  const liveMetrics = [
    [
      "Gestiones enviadas bien",
      summaries.reduce((sum, item) => sum + (item.submissions_succeeded ?? 0), 0),
    ],
    [
      "Gestiones con error",
      summaries.reduce((sum, item) => sum + (item.submissions_failed ?? 0), 0),
    ],
    [
      "Llamadas con plan B",
      summaries.filter((item) => item.fallback_action_added).length,
    ],
  ] as const;

  return (
    <div>
      {demo ? null : (
        <dl className="mb-4 grid gap-4 sm:grid-cols-3">
          {liveMetrics.map(([label, value]) => (
            <div
              key={label}
              className="surface rounded-[18px] p-[var(--card-padding)]"
            >
              <dt className="text-[13px] text-quiet">{label} · últimos registros</dt>
              <dd className="mt-2 font-heading text-2xl">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div data-visible="true" className="grid gap-4 lg:grid-cols-3">
        <article className="surface rounded-[18px] p-[var(--card-padding)] lg:col-span-3">
          <p className="font-heading text-[17px] text-graphite">
            Actividad del día
          </p>
          <p className="mt-1 text-[13px] text-steel">
            Cuántas personas están al teléfono a la vez{" "}
            <span className="text-ember-orange">—</span> y cuántas gestiones
            se cierran <span className="text-brass">- -</span> · hora de Madrid
          </p>
          <div className="mt-7">
            <LoadChart />
          </div>
        </article>
        <article className="surface rounded-[18px] p-[var(--card-padding)]">
          <p className="font-heading text-[17px] text-graphite">
            Líneas ocupadas
          </p>
          <CapacityRing active={activeCount} />
          <p className="text-center text-[13px] text-steel">
            Hay sitio para {CALL_CAPACITY} llamadas a la vez
          </p>
        </article>
        <article className="surface rounded-[18px] p-[var(--card-padding)] lg:col-span-2">
          <p className="font-heading text-[17px] text-graphite">
            Cómo acabaron las gestiones
          </p>
          <p className="mt-1 text-[13px] text-steel">
            Lo que el asistente dejó registrado al colgar.
          </p>
          <div className="mt-7">
            <OutcomeBars />
          </div>
        </article>
      </div>
    </div>
  );
}
