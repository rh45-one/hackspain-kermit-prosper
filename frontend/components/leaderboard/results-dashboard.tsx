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
                  <span className="text-[14px] text-graphite">
                    {call.headline || "Sin resumen"}
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
