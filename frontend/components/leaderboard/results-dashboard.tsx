"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { cn } from "@/lib/utils";

/**
 * Lo que ha pasado de verdad en las llamadas, contado sin adornos.
 *
 * Cada número de aquí sale de una traza que el agente escribió durante una
 * llamada. Ninguno está calculado sobre un escenario de ejemplo, y cuando no
 * hay llamadas la página lo dice en vez de rellenar el hueco: un cuadro de
 * mandos que enseña ceros es honesto, y uno que enseña datos de mentira
 * contamina todo lo demás que sí es cierto.
 *
 * Y lo pide en vivo, cada cinco segundos. Una llamada que entra mientras
 * alguien mira la pantalla tiene que aparecer en la pantalla — si hay que
 * recargar para verla, el cuadro de mandos es una foto, y una foto de hace
 * diez minutos delante de un jurado es lo mismo que un dato inventado.
 */
const POLL_MS = 5000;
export type RealCall = {
  call_id: string;
  status: string;
  headline?: string;
  patient?: string;
  started_at?: string;
  ended_at?: string;
  duration_seconds?: number;
  turns?: number;
  submissions_ok?: number;
  submissions_failed?: number;
  medical_emergency?: boolean;
};


/* --------------------------------------------------------------- gráficas */
/*
 * SVG a mano y no una librería de gráficas.
 *
 * Son tres formas sencillas sobre treinta puntos: una librería serían
 * doscientos kilobytes en el paquete para dibujar rectángulos, y además
 * traería su propia paleta peleándose con la de la casa. Aquí los colores
 * son los mismos tokens que usa el grafo, así que las dos pantallas se
 * parecen porque están hechas de lo mismo, no porque alguien las igualó.
 */

const INK = {
  booked: "#4c8c78",
  plain: "#b4b9b5",
  failed: "#e76432",
  line: "#b08b3a",
};

/** Un anillo con la proporción de llamadas que acaban en cita. */
function OutcomeRing({ booked, failed, total }: { booked: number; failed: number; total: number }) {
  const size = 132;
  const stroke = 16;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const safe = Math.max(total, 1);
  const bookedArc = (booked / safe) * circumference;
  const failedArc = (failed / safe) * circumference;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
         aria-label={`${booked} de ${total} llamadas acabaron en cita`}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={INK.plain}
              strokeWidth={stroke} opacity={0.35} />
      <circle
        cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={INK.booked}
        strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={`${bookedArc} ${circumference - bookedArc}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray 600ms cubic-bezier(0.16,1,0.3,1)" }}
      />
      {failed > 0 ? (
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={INK.failed}
          strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${failedArc} ${circumference - failedArc}`}
          transform={`rotate(${-90 + (booked / safe) * 360} ${size / 2} ${size / 2})`}
        />
      ) : null}
      <text x="50%" y="47%" textAnchor="middle" className="fill-graphite"
            style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.04em" }}>
        {total ? Math.round((booked / total) * 100) : 0}%
      </text>
      <text x="50%" y="63%" textAnchor="middle" className="fill-quiet" style={{ fontSize: 10.5 }}>
        acaban en cita
      </text>
    </svg>
  );
}

/** Cuántas llamadas por hora. Las horas vacías se dibujan, que también dicen algo. */
function HourlyBars({ calls }: { calls: RealCall[] }) {
  const byHour = new Map<string, { total: number; booked: number }>();
  for (const call of calls) {
    const hour = (call.started_at ?? "").slice(11, 13);
    if (!hour) continue;
    const cell = byHour.get(hour) ?? { total: 0, booked: 0 };
    cell.total += 1;
    if ((call.submissions_ok ?? 0) > 0) cell.booked += 1;
    byHour.set(hour, cell);
  }
  const hours = [...byHour.entries()].sort(([a], [b]) => a.localeCompare(b));
  if (hours.length === 0) return null;
  const peak = Math.max(...hours.map(([, cell]) => cell.total));
  const width = 100;
  const height = 74;
  const gap = 3;
  const barWidth = Math.max(4, (width - gap * (hours.length - 1)) / hours.length);

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height + 12}`} className="w-full" role="img"
           aria-label="Llamadas por hora">
        {hours.map(([hour, cell], index) => {
          const x = index * (barWidth + gap);
          const total = (cell.total / peak) * height;
          const booked = (cell.booked / peak) * height;
          return (
            <g key={hour}>
              <rect x={x} y={height - total} width={barWidth} height={total} rx={1.5}
                    fill={INK.plain} opacity={0.5} />
              {booked > 0 ? (
                <rect x={x} y={height - booked} width={barWidth} height={booked} rx={1.5}
                      fill={INK.booked} />
              ) : null}
              <text x={x + barWidth / 2} y={height + 9} textAnchor="middle"
                    className="fill-quiet" style={{ fontSize: 4.5 }}>
                {hour}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/**
 * Turnos contra duración. Cada punto es una llamada.
 *
 * Es la gráfica que más dice de las tres, porque la nube tiene forma: las
 * llamadas que acaban en cita están arriba a la derecha —más turnos, más
 * tiempo— y las que se caen pronto se amontonan en la esquina. Un paciente
 * identificado y una cita cerrada cuestan minuto y medio, y eso no se ve en
 * ninguna media.
 */
function TurnsAgainstTime({ calls }: { calls: RealCall[] }) {
  const points = calls.filter((c) => (c.turns ?? 0) > 0 && (c.duration_seconds ?? 0) > 0);
  if (points.length < 2) return null;
  const maxTurns = Math.max(...points.map((c) => c.turns ?? 0));
  const maxSeconds = Math.max(...points.map((c) => c.duration_seconds ?? 0));
  const width = 100;
  const height = 74;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img"
         aria-label="Turnos contra duración de cada llamada">
      {[0.25, 0.5, 0.75].map((fraction) => (
        <line key={fraction} x1={0} x2={width} y1={height * fraction} y2={height * fraction}
              stroke={INK.plain} strokeWidth={0.3} opacity={0.4} />
      ))}
      {points.map((call) => {
        const x = ((call.duration_seconds ?? 0) / maxSeconds) * (width - 4) + 2;
        const y = height - ((call.turns ?? 0) / maxTurns) * (height - 4) - 2;
        const ok = (call.submissions_ok ?? 0) > 0;
        const bad = (call.submissions_failed ?? 0) > 0;
        return (
          <circle
            key={call.call_id}
            cx={x}
            cy={y}
            r={ok ? 2.4 : 1.8}
            fill={bad ? INK.failed : ok ? INK.booked : INK.plain}
            opacity={ok || bad ? 0.95 : 0.55}
          >
            <title>
              {`${call.turns} turnos · ${Math.round(call.duration_seconds ?? 0)} s · ${
                ok ? "cita creada" : "sin cita"
              }`}
            </title>
          </circle>
        );
      })}
    </svg>
  );
}

function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[14px] border border-mist bg-canvas-white p-4 shadow-[var(--shadow-sm)]">
      <p className="font-heading text-[11px] leading-none tracking-[0.07em] text-brass uppercase">
        {title}
      </p>
      <p className="mt-1.5 mb-3 text-[12px] leading-[1.4] text-quiet">{note}</p>
      {children}
    </div>
  );
}

function Stat({
  value,
  label,
  note,
  tone,
}: {
  value: string;
  label: string;
  note?: string;
  tone?: "warn";
}) {
  return (
    <div className="rounded-[14px] border border-mist bg-canvas-white px-4 py-3.5 shadow-[var(--shadow-sm)]">
      <p
        className={cn(
          "font-heading text-[26px] leading-none tracking-[-0.04em]",
          tone === "warn" ? "text-[#a33f19]" : "text-graphite",
        )}
      >
        {value}
      </p>
      <p className="mt-2 font-heading text-[11px] leading-none tracking-[0.07em] text-brass uppercase">
        {label}
      </p>
      {note ? <p className="mt-1.5 text-[12px] leading-[1.4] text-quiet">{note}</p> : null}
    </div>
  );
}

function minutes(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

export function ResultsDashboard() {
  const [calls, setCalls] = useState<RealCall[]>([]);
  const [reachable, setReachable] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [at, setAt] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/live/calls", { cache: "no-store" });
      if (!response.ok) {
        setReachable(false);
        return;
      }
      const body = (await response.json()) as RealCall[] | { calls?: RealCall[] };
      setCalls(Array.isArray(body) ? body : (body.calls ?? []));
      setReachable(true);
      setAt(new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } catch {
      setReachable(false);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const ended = calls.filter((c) => c.status !== "active");
  const booked = calls.filter((c) => (c.submissions_ok ?? 0) > 0);
  const failed = calls.filter((c) => (c.submissions_failed ?? 0) > 0);
  const emergencies = calls.filter((c) => c.medical_emergency);
  const withDuration = calls.filter((c) => (c.duration_seconds ?? 0) > 0);
  const averageSeconds = withDuration.length
    ? withDuration.reduce((sum, c) => sum + (c.duration_seconds ?? 0), 0) / withDuration.length
    : 0;
  const withTurns = calls.filter((c) => (c.turns ?? 0) > 0);
  const averageTurns = withTurns.length
    ? withTurns.reduce((sum, c) => sum + (c.turns ?? 0), 0) / withTurns.length
    : 0;
  const rate = calls.length ? Math.round((booked.length / calls.length) * 100) : 0;

  return (
    <div className="pb-24">
      <PageHeader kicker="Clínica Arenal" title="Lo que ha pasado en las llamadas">
        Cada número de esta página sale de una traza que el agente escribió durante una llamada
        de verdad — duración, turnos, si acabó en cita, si se detectó una urgencia. No hay
        escenarios de ejemplo: si no ha habido llamadas, aquí no hay nada que enseñar.
      </PageHeader>

      <div className="mb-6 flex items-center gap-3">
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-2 rounded-full border border-mist px-4 py-2 text-[13px] text-steel transition-colors hover:border-graphite hover:text-graphite"
        >
          <RefreshCw className="size-3.5" /> Actualizar
        </button>
        <span className="font-mono text-[12px] tabular-nums text-quiet">
          {at ? `leído a las ${at} · se refresca solo` : "leyendo…"}
        </span>
      </div>

      {!reachable ? (
        <p className="mb-8 rounded-xl border border-[#e76432]/30 bg-[#e76432]/5 px-4 py-3 text-[13px] text-[#a33f19]">
          El panel no puede leer las llamadas del agente. Revisa AGENT_HTTP_BASE_URL y OPS_TOKEN.
        </p>
      ) : null}

      <div className="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          value={String(calls.length)}
          label="Llamadas"
          note={`${ended.length} terminadas · ${calls.length - ended.length} en curso`}
        />
        <Stat
          value={`${rate}%`}
          label="Acaban en cita"
          note={`${booked.length} de ${calls.length} con una acción aceptada por Prosper`}
        />
        <Stat
          value={averageSeconds ? minutes(averageSeconds) : "—"}
          label="Duración media"
          note={averageTurns ? `${averageTurns.toFixed(1)} turnos de media` : "sin datos todavía"}
        />
        <Stat
          value={String(emergencies.length)}
          label="Urgencias detectadas"
          note={
            emergencies.length
              ? "la llamada se cortó y se derivó"
              : "ninguna en las llamadas guardadas"
          }
          tone={emergencies.length ? "warn" : undefined}
        />
      </div>

      <div className="mb-10 grid gap-3 lg:grid-cols-3">
        <Panel title="En qué acaban" note={`${booked.length} con cita · ${calls.length - booked.length} sin ella`}>
          <div className="flex items-center justify-center py-1">
            <OutcomeRing booked={booked.length} failed={failed.length} total={calls.length} />
          </div>
        </Panel>
        <Panel title="A qué horas llaman" note="en verde, las que acabaron en cita">
          <HourlyBars calls={calls} />
        </Panel>
        <Panel
          title="Turnos contra duración"
          note="cada punto una llamada; las de cita se van arriba a la derecha"
        >
          <TurnsAgainstTime calls={calls} />
        </Panel>
      </div>

      {failed.length > 0 ? (
        <p className="mb-8 rounded-xl border border-mist bg-fog px-4 py-3 text-[13px] text-steel">
          {failed.length}{" "}
          {failed.length === 1 ? "llamada tuvo" : "llamadas tuvieron"} un envío rechazado por la
          plataforma. Están abajo, y son las que hay que mirar primero.
        </p>
      ) : null}

      <section aria-label="Llamadas">
        <h2 className="mb-1 font-heading text-[15px] text-graphite">Una por una</h2>
        <p className="mb-4 text-[13px] text-steel">
          Las más recientes primero. La cabecera es lo que el agente entendió que le pedían.
        </p>

        {calls.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-mist px-5 py-8 text-center text-[14px] text-steel">
            {loaded
              ? "Todavía no hay llamadas guardadas en este despliegue."
              : "Leyendo las llamadas del agente…"}
          </p>
        ) : (
          <ul className="grid gap-1.5">
            {calls.slice(0, 40).map((call) => {
              const ok = (call.submissions_ok ?? 0) > 0;
              const bad = (call.submissions_failed ?? 0) > 0;
              return (
                <li
                  key={call.call_id}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-mist bg-canvas-white px-4 py-3"
                >
                  <span
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      bad ? "bg-[#e76432]" : ok ? "bg-[#4c8c78]" : "bg-steel/40",
                    )}
                    aria-hidden
                  />
                  <span className="font-mono text-[11px] tabular-nums text-quiet">
                    {(call.started_at ?? "").slice(11, 16) || "—"}
                  </span>
                  <span
                    className={cn(
                      "text-[14px]",
                      call.headline && !call.headline.startsWith("Todavía sin")
                        ? "text-graphite"
                        : "text-quiet",
                    )}
                  >
                    {call.headline && !call.headline.startsWith("Todavía sin")
                      ? call.headline
                      : "sin decisión registrada"}
                  </span>
                  {call.patient ? (
                    <span className="text-[13px] text-steel">{call.patient}</span>
                  ) : null}
                  {call.medical_emergency ? (
                    <span className="rounded-full bg-[#e76432]/10 px-2 py-0.5 text-[11px] text-[#a33f19]">
                      urgencia
                    </span>
                  ) : null}
                  <span className="ml-auto flex items-center gap-3 font-mono text-[11px] tabular-nums text-quiet">
                    {call.turns ? <span>{call.turns} turnos</span> : null}
                    {call.duration_seconds ? <span>{minutes(call.duration_seconds)}</span> : null}
                    <span className={cn(bad && "text-[#a33f19]")}>
                      {bad ? "envío rechazado" : ok ? "cita creada" : "sin cita"}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
