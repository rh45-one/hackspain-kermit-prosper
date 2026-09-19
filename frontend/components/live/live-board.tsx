"use client";

import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import {
  clockTime,
  formatDuration,
  STATUS_STYLES,
  type LiveCallDetail,
  type LiveCallRow,
} from "@/lib/live";
import { cn } from "@/lib/utils";

const REFRESH_MS = 3000;

/** One poll of a live resource, with the panel's own error wording. */
async function load<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/live/${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const body: { detail?: string } = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function StatusBadge({ status }: { status: LiveCallRow["status"] }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 font-heading text-[11px] tracking-[0.04em] uppercase",
        STATUS_STYLES[status],
      )}
    >
      {status === "en curso" ? (
        <span className="size-1.5 animate-pulse rounded-full bg-ember-orange" />
      ) : null}
      {status}
    </span>
  );
}

function CallDetail({ callId }: { callId: string }) {
  const [detail, setDetail] = useState<LiveCallDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function refresh() {
      try {
        const data = await load<LiveCallDetail>(`calls/${callId}`, controller.signal);
        if (controller.signal.aborted) return;
        setDetail(data);
        setError(null);
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Error de conexión");
      } finally {
        if (!controller.signal.aborted) {
          timer = window.setTimeout(() => void refresh(), REFRESH_MS);
        }
      }
    }
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [callId]);

  if (error) {
    return <p className="text-[13px] text-ember-orange">{error}</p>;
  }
  if (!detail) {
    return <p className="text-[13px] text-quiet">Cargando la llamada…</p>;
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section>
        <h3 className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
          Qué ha hecho el agente
        </h3>
        {detail.events.length === 0 ? (
          <p className="mt-3 text-[13px] text-quiet">
            Todavía no hay ninguna gestión registrada en esta llamada.
          </p>
        ) : (
          <ol className="mt-3 space-y-2.5">
            {detail.events.map((event, index) => (
              <li key={`${event.at}-${index}`} className="flex gap-3 text-[14px] leading-[1.5]">
                <span className="shrink-0 font-mono text-[12px] text-quiet">{event.at}</span>
                <span className="text-graphite">{event.text}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section>
        <h3 className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
          Conversación
        </h3>
        <ol className="mt-3 max-h-[26rem] space-y-2.5 overflow-y-auto pr-1">
          {detail.conversation.map((turn, index) => (
            <li
              key={index}
              className={cn(
                "rounded-[10px] px-3 py-2 text-[13px] leading-[1.5]",
                turn.speaker === "agente"
                  ? "border border-mist bg-canvas-white text-graphite"
                  : "border-l-2 border-ember-orange bg-ivory text-steel",
              )}
            >
              <p className="mb-1 font-heading text-[11px] tracking-[0.04em] text-quiet uppercase">
                {turn.speaker}
              </p>
              <p className="break-words">{turn.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

export function LiveBoard() {
  const [calls, setCalls] = useState<LiveCallRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openCallId, setOpenCallId] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string>("—");

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function refresh() {
      try {
        const data = await load<LiveCallRow[]>("calls", controller.signal);
        if (controller.signal.aborted) return;
        setCalls(data);
        setError(null);
        setUpdatedAt(new Intl.DateTimeFormat("es-ES", {
          hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Europe/Madrid",
        }).format(new Date()));
      } catch (caught) {
        if (controller.signal.aborted) return;
        setError(caught instanceof Error ? caught.message : "Error de conexión");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          timer = window.setTimeout(() => void refresh(), REFRESH_MS);
        }
      }
    }
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  const toggle = useCallback((callId: string) => {
    setOpenCallId((current) => (current === callId ? null : callId));
  }, []);

  const ongoing = calls.filter((call) => call.status === "en curso").length;

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Llamadas en directo">
        {ongoing === 1 ? "1 llamada ahora mismo." : `${ongoing} llamadas ahora mismo.`}{" "}
        Se actualiza sola cada tres segundos. Última comprobación: {updatedAt}.
      </PageHeader>

      {error ? (
        <p className="mb-5 rounded-[12px] border border-ember-orange/30 bg-ivory px-4 py-3 text-[13px] text-ember-orange">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="text-[13px] text-quiet">Conectando con el agente…</p>
      ) : calls.length === 0 && !error ? (
        <p className="text-[13px] text-quiet">
          Todavía no ha entrado ninguna llamada. Esta pantalla se actualizará sola en cuanto suene el teléfono.
        </p>
      ) : (
        <ul className="space-y-3">
          {calls.map((call) => {
            const open = openCallId === call.call_id;
            return (
              <li
                key={call.call_id}
                className={cn(
                  "rounded-[16px] border border-mist bg-canvas-white shadow-[var(--shadow-sm)] transition-colors",
                  open && "border-brass/35 bg-ivory/30",
                  call.medical_emergency && "border-ember-orange/45",
                )}
              >
                <button
                  type="button"
                  onClick={() => toggle(call.call_id)}
                  aria-expanded={open}
                  className="flex w-full cursor-pointer flex-col gap-3 rounded-[16px] p-5 text-left outline-none focus-visible:ring-2 focus-visible:ring-brass/35 sm:p-6"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-heading text-[15px] text-graphite">
                      {call.patient ?? "Llamante sin identificar"}
                    </span>
                    <span className="flex items-center gap-2">
                      {call.medical_emergency ? (
                        <span className="inline-flex items-center rounded-full bg-ember-orange px-2.5 py-1 font-heading text-[11px] tracking-[0.04em] text-canvas-white uppercase">
                          Posible urgencia
                        </span>
                      ) : null}
                      <StatusBadge status={call.status} />
                    </span>
                  </div>
                  <p className="text-[14px] leading-[1.5] text-steel">{call.headline}</p>
                  <p className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-quiet">
                    <span>Entró a las {clockTime(call.started_at)}</span>
                    <span>Duración {formatDuration(call.duration_seconds)}</span>
                    <span>{call.turns} intervenciones</span>
                    {call.submissions_failed > 0 ? (
                      <span className="text-ember-orange">
                        {call.submissions_failed} envío(s) fallido(s)
                      </span>
                    ) : null}
                  </p>
                </button>
                {open ? (
                  <div className="border-t border-mist px-5 py-5 sm:px-6">
                    <CallDetail key={call.call_id} callId={call.call_id} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
