"use client";

import { useState } from "react";

import { CallManagementDialog } from "@/components/calls/call-management-dialog";
import { TranscriptThread } from "@/components/calls/transcript-thread";
import { useFrontdesk } from "@/components/frontdesk-provider";
import { PageHeader } from "@/components/layout/page-header";
import { ObservatoryCharts } from "@/components/metrics/observatory-charts";
import {
  callCardElementId,
  callDisplayName,
  callLineLabel,
} from "@/lib/call-format";
import { CALL_CAPACITY, type LiveCall, type TurnState } from "@/lib/types";
import { cn } from "@/lib/utils";

const TURN_LABEL: Record<TurnState, string> = {
  listening: "Escuchando",
  speaking: "El asistente habla",
  "barge-in": "Le interrumpen",
};

function TurnMark({ turn }: { turn: TurnState }) {
  return (
    <span
      className={cn(
        "font-heading text-[13px] leading-none",
        turn === "barge-in" && "text-ember-orange",
        turn === "speaking" && "text-brass",
        turn === "listening" && "text-quiet",
      )}
    >
      {TURN_LABEL[turn]}
    </span>
  );
}

function CallCard({
  call,
  demo,
  selected,
  onOpen,
}: {
  call: LiveCall;
  demo: boolean;
  selected: boolean;
  onOpen: (callId: string) => void;
}) {
  const ended = call.status === "ended";
  const name = callDisplayName(call.entities.name);
  const line = callLineLabel(call.socketId);

  return (
    <article
      className={cn(
        "h-full rounded-[16px] border border-mist bg-canvas-white shadow-[var(--shadow-sm)] transition-[transform,box-shadow,border-color,background-color] duration-200",
        "hover:-translate-y-0.5 hover:border-[#c6cac3] hover:bg-fog/40 hover:shadow-[var(--shadow-md)]",
        ended && "opacity-60",
        selected && "border-brass/35 bg-ivory/40 hover:bg-ivory/55",
      )}
    >
      <button
        type="button"
        id={callCardElementId(call.callId)}
        onClick={() => {
          window.setTimeout(() => onOpen(call.callId), 0);
        }}
        aria-haspopup="dialog"
        aria-expanded={selected}
        aria-label={`Abrir conversación con ${name}`}
        className="group flex h-full w-full cursor-pointer flex-col rounded-[16px] p-5 text-left outline-none focus-visible:ring-2 focus-visible:ring-brass/35 sm:p-7"
      >
        <div className="mb-5 flex items-start justify-between gap-5">
          <div className="min-w-0">
            <p className="truncate font-heading text-[15px] text-graphite">
              {name}
            </p>
            <p className="mt-1 truncate text-[13px] text-quiet">
              {line} · {call.virtualPhone}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            {ended ? (
              <span className="font-heading text-[13px] text-ember-orange">
                {demo ? "Pasada a persona" : "Finalizada"}
              </span>
            ) : call.status === "unknown" ? (
              <span className="text-[13px] text-quiet">Sin estado claro</span>
            ) : !demo ? (
              <span className="text-[13px] text-quiet">En curso</span>
            ) : (
              <TurnMark turn={call.turn} />
            )}
            <span className="font-heading text-[12px] text-quiet opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">
              Ver detalle
            </span>
          </div>
        </div>
        <TranscriptThread call={call} variant="preview" />
        <dl className="mt-5 grid grid-cols-2 gap-x-5 gap-y-4 text-[12px] sm:grid-cols-3">
          <div>
            <dt className="text-quiet">Quién llama</dt>
            <dd className="mt-1 truncate text-graphite">
              {call.entities.name ?? "Aún no lo ha dicho"}
            </dd>
          </div>
          <div>
            <dt className="text-quiet">Documento</dt>
            <dd className="mt-1 truncate font-mono text-graphite">
              {call.entities.nationalId ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-quiet">Qué pide</dt>
            <dd className="mt-1 truncate text-graphite">
              {call.entities.appointmentType ?? "Por confirmar"}
            </dd>
          </div>
        </dl>
        {!demo && call.diagnostic ? (
          <p className="mt-4 text-[13px] text-steel">
            Gestiones enviadas bien: {call.diagnostic.submissions_succeeded ?? 0}.
            {" "}Con error: {call.diagnostic.submissions_failed ?? 0}.
            {call.diagnostic.empty_action_reason
              ? ` Nota: ${call.diagnostic.empty_action_reason}.`
              : ""}
          </p>
        ) : null}
      </button>
    </article>
  );
}

function EmptySlot({ index }: { index: number }) {
  return (
    <div className="flex min-h-32 flex-col justify-between rounded-[16px] border border-dashed border-[#cfd3cc] bg-fog/70 p-5 text-quiet sm:p-7">
      <span className="size-2 rounded-full bg-mist" />
      <div>
        <p className="font-heading text-[13px]">
          Línea {String(index + 1).padStart(2, "0")}
        </p>
        <p className="mt-1 text-[13px]">Libre · esperando una llamada</p>
      </div>
    </div>
  );
}

export function CallMonitor() {
  const { calls, activeCount, demo } = useFrontdesk();
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const slots = Array.from(
    { length: demo ? CALL_CAPACITY : Math.max(calls.length, 1) },
    (_, index) => calls[index],
  );
  const selectedCall =
    calls.find((call) => call.callId === selectedCallId) ?? null;

  return (
    <div>
      <PageHeader kicker="Recepción en vivo" title="Llamadas">
        {demo
          ? "Aquí ves cómo el asistente de citas atiende el teléfono: escucha, habla con la persona y deja apuntado lo que va entendiendo (nombre, documento, tipo de cita)."
          : "Últimas llamadas atendidas por el asistente de citas, con la conversación y el resultado de cada gestión."}{" "}
        Ahora mismo hay {activeCount}{" "}
        {activeCount === 1 ? "llamada abierta" : "llamadas abiertas"}.
      </PageHeader>
      <div className="mb-[var(--section-gap)]">
        <ObservatoryCharts />
      </div>
      <div
        data-reveal=""
        className="mb-5 flex items-end justify-between gap-5"
      >
        <div>
          <p className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
            Ahora mismo
          </p>
          <h2 className="mt-2 text-[clamp(1.6rem,3vw,2.25rem)] leading-none">
            Líneas de recepción
          </h2>
          <p className="mt-2 max-w-xl text-[14px] text-steel">
            Cada tarjeta es una conversación. Pulsa una para oír el hilo o
            tomar el control si hace falta una persona.
          </p>
        </div>
        <p className="hidden text-[13px] text-quiet sm:block">
          {activeCount} de {CALL_CAPACITY} líneas ocupadas
        </p>
      </div>
      <div
        data-reveal=""
        data-delay="1"
        className="grid grid-cols-1 gap-4 rounded-[20px] border border-mist bg-ash/70 p-3 sm:p-5 xl:grid-cols-2 2xl:grid-cols-3"
      >
        {slots.map((call, index) =>
          call ? (
            <CallCard
              key={call.callId}
              call={call}
              demo={demo}
              selected={call.callId === selectedCallId}
              onOpen={setSelectedCallId}
            />
          ) : (
            <EmptySlot key={`empty-${index}`} index={index} />
          ),
        )}
      </div>
      <CallManagementDialog
        call={selectedCall}
        onClose={() => setSelectedCallId(null)}
      />
    </div>
  );
}
