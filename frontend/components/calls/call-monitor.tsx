"use client";

import { useEffect, useRef } from "react";
import { Hand, PhoneOff } from "lucide-react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { PageHeader } from "@/components/layout/page-header";
import { ObservatoryCharts } from "@/components/metrics/observatory-charts";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CALL_CAPACITY, type LiveCall, type TurnState } from "@/lib/types";
import { cn } from "@/lib/utils";

const TURN_LABEL: Record<TurnState, string> = {
  listening: "Escuchando",
  speaking: "Agente habla",
  "barge-in": "Barge-in",
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
  onHandover,
}: {
  call: LiveCall;
  onHandover: (callId: string) => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [call.transcript.length]);

  const ended = call.status === "ended";

  return (
    <article
      className={cn(
        "flex h-full flex-col rounded-[16px] border border-mist bg-canvas-white p-5 shadow-[var(--shadow-sm)] transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-md)] sm:p-7",
        ended && "opacity-60",
      )}
    >
      <div className="mb-5 flex items-start justify-between gap-5">
        <div className="min-w-0">
          <p className="truncate font-heading text-[15px] text-graphite">
            {call.callId}
          </p>
          <p className="mt-1 text-[13px] text-quiet">
            {call.socketId} · {call.virtualPhone}
          </p>
        </div>
        {ended ? (
          <span className="shrink-0 font-heading text-[13px] text-ember-orange">
            DIVERTED
          </span>
        ) : (
          <TurnMark turn={call.turn} />
        )}
      </div>
      <ScrollArea className="h-44 rounded-[10px] border border-mist/80 bg-fog p-3">
        <div className="space-y-2">
          {call.transcript.length === 0 ? (
            <p className="text-[13px] text-quiet">Esperando audio…</p>
          ) : (
            call.transcript.map((line, index) => (
              <p
                key={`${call.callId}-${index}`}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-[13px] leading-[1.45]",
                  line.role === "agent"
                    ? "bg-canvas-white text-graphite"
                    : "border-l-2 border-ember-orange bg-ivory text-steel",
                )}
              >
                <span className="mr-1 font-heading text-[13px] text-quiet">
                  {line.role === "agent" ? "IA" : "Paciente"}
                </span>
                {line.text}
              </p>
            ))
          )}
          <div ref={bottom} />
        </div>
      </ScrollArea>
      <dl className="mt-5 grid grid-cols-2 gap-x-5 gap-y-4 text-[12px] sm:grid-cols-3">
        <div>
          <dt className="text-quiet">Nombre</dt>
          <dd className="mt-1 truncate text-graphite">
            {call.entities.name ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-quiet">DNI</dt>
          <dd className="mt-1 truncate font-mono text-graphite">
            {call.entities.nationalId ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-quiet">Tipo</dt>
          <dd className="mt-1 truncate text-graphite">
            {call.entities.appointmentType ?? "—"}
          </dd>
        </div>
      </dl>
      <div className="mt-6">
        <Button
          variant={ended ? "outline" : "default"}
          disabled={ended}
          onClick={() => onHandover(call.callId)}
        >
          {ended ? <PhoneOff /> : <Hand />}
          {ended ? "Control tomado" : "Tomar el control"}
        </Button>
      </div>
    </article>
  );
}

function EmptySlot({ index }: { index: number }) {
  return (
    <div className="flex min-h-32 flex-col justify-between rounded-[16px] border border-dashed border-[#cfd3cc] bg-fog/70 p-5 text-quiet sm:p-7">
      <span className="size-2 rounded-full bg-mist" />
      <div>
        <p className="font-mono text-[11px]">{String(index + 1).padStart(2, "0")}</p>
        <p className="font-heading text-[13px]">Hueco libre</p>
      </div>
    </div>
  );
}

export function CallMonitor() {
  const { calls, takeControl, activeCount } = useFrontdesk();
  const slots = Array.from({ length: CALL_CAPACITY }, (_, index) => calls[index]);

  return (
    <div>
      <PageHeader kicker="Observatorio en vivo" title="Monitor de llamadas">
        Hasta diez sockets concurrentes. Transcripción y entidades en vivo,
        datos simulados. {activeCount} activas ahora.
      </PageHeader>
      <div className="mb-[var(--section-gap)]">
        <ObservatoryCharts />
      </div>
      <div className="mb-5 flex items-end justify-between gap-5">
        <div>
          <p className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
            Actividad en tiempo real
          </p>
          <h2 className="mt-2 text-[clamp(1.6rem,3vw,2.25rem)] leading-none">
            Canales de llamada
          </h2>
        </div>
        <p className="hidden font-mono text-[11px] text-quiet sm:block">
          {activeCount}/{CALL_CAPACITY} ocupados
        </p>
      </div>
      <div
        className="grid grid-cols-1 gap-4 rounded-[20px] border border-mist bg-ash/70 p-3 sm:p-5 xl:grid-cols-2 2xl:grid-cols-3"
      >
        {slots.map((call, index) =>
          call ? (
            <CallCard key={call.callId} call={call} onHandover={takeControl} />
          ) : (
            <EmptySlot key={`empty-${index}`} index={index} />
          ),
        )}
      </div>
    </div>
  );
}
