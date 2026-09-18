"use client";

import { useEffect, useRef } from "react";
import { Hand, PhoneOff } from "lucide-react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CALL_CAPACITY, type LiveCall, type TurnState } from "@/lib/types";
import { cn } from "@/lib/utils";

const TURN_LABEL: Record<TurnState, string> = {
  listening: "Escuchando",
  speaking: "Agente habla",
  "barge-in": "Barge-in",
};

function TurnBadge({ turn }: { turn: TurnState }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        turn === "barge-in" && "border-orange-300 bg-orange-50 text-orange-800",
        turn === "speaking" && "border-teal-200 bg-teal-50 text-teal-800",
        turn === "listening" && "border-slate-200 bg-slate-50 text-slate-700",
      )}
    >
      {TURN_LABEL[turn]}
    </Badge>
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
    <Card className={cn("h-full", ended && "opacity-70")}>
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="font-mono text-sm">{call.callId}</CardTitle>
            <CardDescription>
              {call.socketId} · {call.virtualPhone}
            </CardDescription>
          </div>
          {ended ? (
            <Badge className="border-orange-200 bg-orange-100 text-orange-800">
              DIVERTED
            </Badge>
          ) : (
            <TurnBadge turn={call.turn} />
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <ScrollArea className="h-40 rounded-md bg-slate-50 p-2">
          <div className="space-y-2">
            {call.transcript.length === 0 ? (
              <p className="px-1 text-xs text-slate-400">Esperando audio…</p>
            ) : (
              call.transcript.map((line, index) => (
                <p
                  key={`${call.callId}-${index}`}
                  className={cn(
                    "rounded-md px-2 py-1 text-xs leading-relaxed",
                    line.role === "agent"
                      ? "bg-white text-slate-800"
                      : "bg-teal-50 text-teal-950",
                  )}
                >
                  <span className="mr-1 font-medium">
                    {line.role === "agent" ? "IA" : "Paciente"}
                  </span>
                  {line.text}
                </p>
              ))
            )}
            <div ref={bottom} />
          </div>
        </ScrollArea>
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-md bg-slate-50 p-2">
            <dt className="text-slate-500">Nombre</dt>
            <dd className="truncate font-medium text-slate-900">
              {call.entities.name ?? "—"}
            </dd>
          </div>
          <div className="rounded-md bg-slate-50 p-2">
            <dt className="text-slate-500">DNI</dt>
            <dd className="truncate font-mono font-medium text-slate-900">
              {call.entities.nationalId ?? "—"}
            </dd>
          </div>
          <div className="rounded-md bg-slate-50 p-2">
            <dt className="text-slate-500">Tipo</dt>
            <dd className="truncate font-medium text-slate-900">
              {call.entities.appointmentType ?? "—"}
            </dd>
          </div>
        </dl>
      </CardContent>
      <CardFooter>
        <Button
          size="sm"
          variant={ended ? "secondary" : "default"}
          disabled={ended}
          onClick={() => onHandover(call.callId)}
        >
          {ended ? <PhoneOff /> : <Hand />}
          {ended ? "Control tomado" : "Tomar el control"}
        </Button>
      </CardFooter>
    </Card>
  );
}

function EmptySlot({ index }: { index: number }) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white/60 text-slate-400">
      <p className="text-xs tracking-wide uppercase">Hueco {index + 1}</p>
      <p className="text-sm">Libre</p>
    </div>
  );
}

export function CallMonitor() {
  const { calls, takeControl, activeCount } = useFrontdesk();
  const slots = Array.from({ length: CALL_CAPACITY }, (_, index) => calls[index]);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          Monitor de llamadas
        </h2>
        <p className="text-sm text-slate-500">
          Hasta 10 sockets concurrentes. Transcripción y entidades en vivo
          (datos simulados). {activeCount} activas ahora.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
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
