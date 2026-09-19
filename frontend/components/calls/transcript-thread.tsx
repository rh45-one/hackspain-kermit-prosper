"use client";

import { useEffect, useRef } from "react";

import type { LiveCall, TranscriptLine } from "@/lib/types";
import { cn } from "@/lib/utils";

function speakerLabel(role: TranscriptLine["role"]) {
  return role === "agent" ? "Asistente de citas" : "Persona que llama";
}

export function TranscriptThread({
  call,
  variant = "full",
}: {
  call: LiveCall;
  variant?: "preview" | "full";
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const preview = variant === "preview";

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) {
      return;
    }
    scroller.scrollTop = scroller.scrollHeight;
  }, [call.callId, call.transcript.length, variant]);

  return (
    <div
      ref={scrollerRef}
      className={cn(
        "min-h-0 overflow-y-auto",
        preview
          ? "pointer-events-none h-44 rounded-[10px] border border-mist/80 bg-fog p-3"
          : "min-h-0 flex-1 bg-fog/70 px-4 py-4 sm:px-6 sm:py-5",
      )}
    >
      {call.transcript.length === 0 ? (
        <p className="text-[13px] text-quiet">Esperando a que empiece la conversación…</p>
      ) : (
        <ol
          className={cn("flex flex-col", preview ? "space-y-2" : "space-y-3")}
          aria-label="Conversación"
        >
          {call.transcript.map((line, index) => (
            <li
              key={`${call.callId}-${index}`}
              className={cn(
                "max-w-[42rem] rounded-[10px] px-3 py-2 text-[13px] leading-[1.5] sm:text-[14px]",
                line.role === "agent"
                  ? "border border-mist bg-canvas-white text-graphite"
                  : "border-l-2 border-ember-orange bg-ivory text-steel",
                !preview && "animate-in fade-in slide-in-from-bottom-1 duration-300",
              )}
            >
              <p className="mb-1 font-heading text-[11px] tracking-[0.04em] text-quiet uppercase">
                {speakerLabel(line.role)}
              </p>
              <p className="break-words">{line.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
