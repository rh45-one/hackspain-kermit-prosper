"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Phone, Play, RefreshCw, Zap } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { cn } from "@/lib/utils";

/**
 * La cola de lo que va mal, y quién se ha hecho cargo.
 *
 * Dos cosas que esta pantalla enseña y que no se ven en ningún otro sitio:
 *
 * 1. **Quién lo ha decidido.** Cada incidencia lleva a una persona, y esa
 *    persona la eligió o la ruta configurada de la clínica o Jev leyendo la
 *    frase. Saber cuál de las dos importa más que el nombre: una ruta acierta
 *    siempre lo mismo y Jev acierta lo que la ruta no puede distinguir.
 * 2. **Que abstenerse es una respuesta.** Cuando Jev no ve a nadie
 *    claramente mejor, contesta la ruta — y aquí se dice, en vez de
 *    enseñar el mismo resultado como si lo hubiera pensado.
 *
 * El botón de llamar no marca nada: abre la misma página de llamada que el
 * QR del grafo, con el motivo, la persona y la frase dentro. Marcar un
 * teléfono es un producto con consentimiento y factura.
 */
type Incident = {
  id: string;
  reason: string;
  reason_label: string;
  summary: string;
  assigned_to: string;
  assigned_name: string;
  assigned_role: string;
  urgency: string;
  status: string;
  source: string;
  call_id: string;
  note: string;
  created_at: string;
};

const URGENCY: Record<string, { word: string; dot: string; rank: number }> = {
  now: { word: "Ahora", dot: "bg-[#e76432]", rank: 0 },
  today: { word: "Hoy", dot: "bg-[#b08b3a]", rank: 1 },
  queue: { word: "En cola", dot: "bg-steel/60", rank: 2 },
};

const POLL_MS = 4000;

export function IncidentBoard({ callBase }: { callBase: string }) {
  const [rows, setRows] = useState<Incident[]>([]);
  const [open, setOpen] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [lastDecision, setLastDecision] = useState<string>("");

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/live/incidents", { cache: "no-store" });
      if (!response.ok) {
        setError("El panel no puede leer las incidencias del agente.");
        return;
      }
      const body = (await response.json()) as { incidents?: Incident[]; open?: number };
      setRows(body.incidents ?? []);
      setOpen(body.open ?? 0);
      setError("");
    } catch {
      setError("No se puede hablar con el agente.");
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const act = useCallback(
    async (payload: Record<string, unknown>) => {
      setBusy(true);
      try {
        const response = await fetch("/api/incidents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const body = (await response.json().catch(() => ({}))) as {
          decided_by?: string;
          confidence?: number;
          assigned_name?: string;
        };
        if (payload.action === "simulate" && body.assigned_name) {
          setLastDecision(
            body.decided_by === "jev"
              ? `Jev se la ha dado a ${body.assigned_name} · confianza ${body.confidence?.toFixed(2)}`
              : `Jev no lo ha tenido claro: la ruta se la ha dado a ${body.assigned_name}`,
          );
        }
        await load();
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  // El modo automático: una cada seis segundos, que es lo que tarda alguien
  // en leer la anterior. Más rápido llena la pantalla y no se ve nada.
  const autoRef = useRef(auto);
  autoRef.current = auto;
  useEffect(() => {
    if (!auto) return;
    const timer = window.setInterval(() => {
      if (autoRef.current) void act({ action: "simulate" });
    }, 6000);
    return () => window.clearInterval(timer);
  }, [auto, act]);

  const live = rows.filter((r) => r.status !== "closed");
  const done = rows.filter((r) => r.status === "closed");
  live.sort(
    (a, b) =>
      (URGENCY[a.urgency]?.rank ?? 9) - (URGENCY[b.urgency]?.rank ?? 9) ||
      b.created_at.localeCompare(a.created_at),
  );

  return (
    <div className="pb-24">
      <PageHeader kicker="Clínica Arenal" title="Lo que va mal ahora mismo">
        Cada llamada que acaba sin cita deja una incidencia aquí, asignada a quien dicen las
        rutas de la clínica — la misma persona a la que llamaría el agente. Cuando la ruta no
        basta para distinguir quién, lo decide Jev leyendo lo que ha pasado, y la tarjeta dice
        cuál de los dos ha contestado.
      </PageHeader>

      <div className="mb-8 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void act({ action: "simulate" })}
          className="inline-flex items-center gap-2 rounded-full bg-graphite px-4 py-2.5 text-[14px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <Zap className="size-3.5" /> Lanzar una incidencia
        </button>
        <button
          type="button"
          onClick={() => setAuto((on) => !on)}
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-[14px] transition-colors",
            auto
              ? "border-graphite bg-canvas-white text-graphite"
              : "border-mist text-steel hover:border-graphite hover:text-graphite",
          )}
        >
          <Play className="size-3.5" /> {auto ? "Parar el goteo" : "Que vayan entrando"}
        </button>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center gap-2 rounded-full border border-mist px-4 py-2.5 text-[14px] text-steel transition-colors hover:border-graphite hover:text-graphite"
        >
          <RefreshCw className="size-3.5" /> Actualizar
        </button>
        <span className="ml-auto font-mono text-[12px] tabular-nums text-steel">
          {open} abiertas
        </span>
      </div>

      {lastDecision ? (
        <p className="mb-6 rounded-xl border border-mist bg-canvas-white px-4 py-3 text-[13px] text-graphite">
          {lastDecision}
        </p>
      ) : null}
      {error ? (
        <p className="mb-6 rounded-xl border border-[#e76432]/30 bg-[#e76432]/5 px-4 py-3 text-[13px] text-[#a33f19]">
          {error}
        </p>
      ) : null}

      {live.length === 0 && !error ? (
        <p className="rounded-2xl border border-dashed border-mist px-5 py-8 text-center text-[14px] text-steel">
          Nada roto ahora mismo. Lanza una para ver el reparto.
        </p>
      ) : null}

      <ul className="grid gap-3">
        {live.map((row) => {
          const urgency = URGENCY[row.urgency] ?? URGENCY.queue;
          const byJev = row.note.startsWith("Jev:");
          const callUrl = `${callBase}?reason=${encodeURIComponent(row.reason)}&person=${encodeURIComponent(row.assigned_to)}&situation=${encodeURIComponent(row.summary)}`;
          return (
            <li
              key={row.id}
              className="rounded-2xl border border-mist bg-canvas-white p-5 shadow-[var(--shadow-sm)]"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <span className={cn("size-2 rounded-full", urgency.dot)} aria-hidden />
                <span className="font-heading text-[11px] tracking-[0.07em] text-brass uppercase">
                  {urgency.word}
                </span>
                <span className="text-[12px] text-quiet">{row.reason_label}</span>
                {row.source === "agent" ? (
                  <span className="rounded-full border border-mist px-2 py-0.5 text-[11px] text-steel">
                    de una llamada
                  </span>
                ) : null}
                <span className="ml-auto font-mono text-[11px] tabular-nums text-quiet">
                  {row.created_at.slice(11, 16)}
                </span>
              </div>

              <p className="mt-2.5 text-[15px] leading-[1.5] text-graphite">
                {row.summary || row.reason_label}
              </p>

              <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-mist pt-3.5">
                <span
                  className={cn(
                    "rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide",
                    byJev ? "bg-graphite text-white" : "border border-mist text-steel",
                  )}
                >
                  {byJev ? "Jev" : "Ruta"}
                </span>
                <span className="font-heading text-[15px] text-graphite">
                  {row.assigned_name || row.assigned_to || "sin asignar"}
                </span>
                {row.assigned_role ? (
                  <span className="text-[13px] text-steel">{row.assigned_role}</span>
                ) : null}
                <span className="text-[12px] text-quiet">{row.note}</span>

                <div className="ml-auto flex items-center gap-2">
                  <a
                    href={callUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full border border-mist px-3 py-1.5 text-[13px] text-graphite transition-colors hover:border-graphite"
                  >
                    <Phone className="size-3.5" /> Llamarle
                  </a>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act({ action: "status", id: row.id, status: "closed" })}
                    className="inline-flex items-center gap-1.5 rounded-full border border-mist px-3 py-1.5 text-[13px] text-steel transition-colors hover:border-graphite hover:text-graphite disabled:opacity-50"
                  >
                    <Check className="size-3.5" /> Resuelta
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {done.length > 0 ? (
        <section className="mt-10">
          <h2 className="mb-3 font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
            Resueltas · {done.length}
          </h2>
          <ul className="grid gap-1.5">
            {done.slice(0, 12).map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-baseline gap-x-3 rounded-xl border border-mist/60 bg-fog px-4 py-2.5 text-[13px] text-steel"
              >
                <span className="text-quiet">{row.created_at.slice(11, 16)}</span>
                <span className="text-graphite">{row.summary || row.reason_label}</span>
                <span className="ml-auto text-quiet">
                  {row.assigned_name || row.assigned_to}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
