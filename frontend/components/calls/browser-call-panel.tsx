"use client";

import { Phone, PhoneOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useBrowserCall } from "@/lib/use-browser-call";
import { cn } from "@/lib/utils";

export function BrowserCallPanel() {
  const { online, inCall, busy, message, tone, toggleCall } = useBrowserCall();

  return (
    <section
      id="llamar"
      data-reveal=""
      className="mb-[var(--section-gap)] scroll-mt-[10rem] rounded-[20px] border border-mist bg-canvas-white p-5 shadow-[var(--shadow-sm)] sm:p-8"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-3 flex items-center gap-2.5 font-heading text-[11px] leading-none tracking-[0.08em] text-brass uppercase">
            <span className="h-px w-5 bg-brass/70" />
            Your line
          </p>
          <h2 className="font-heading text-[clamp(1.6rem,3vw,2.25rem)] leading-none tracking-[-0.04em] text-graphite">
            Talk to reception.
          </h2>
          <p className="mt-3 max-w-xl text-[14px] leading-relaxed text-steel sm:text-[15px]">
            Call from the browser. Nothing is sent to Prosper: same voice
            pipe, in test mode.
          </p>
        </div>
        <p
          className={cn(
            "flex items-center gap-2 font-heading text-[12px] font-medium",
            online ? "text-[#1f7a3a]" : "text-[#b42318]",
          )}
          role="status"
          aria-live="polite"
        >
          <span
            className={cn(
              "inline-block size-2 rounded-full",
              online ? "status-dot-online" : "status-dot-offline",
            )}
            aria-hidden="true"
          />
          {online ? "Online" : "Offline"}
        </p>
      </div>

      <div className="mt-6 flex flex-col gap-3 border-t border-mist pt-6 sm:flex-row sm:items-center">
        <Button
          type="button"
          size="lg"
          variant={inCall ? "outline" : "default"}
          aria-pressed={inCall}
          disabled={busy}
          onClick={toggleCall}
          className={cn(inCall && "border-[#d8caa9] text-destructive hover:bg-ash")}
        >
          {inCall ? <PhoneOff className="size-4" /> : <Phone className="size-4" />}
          {inCall ? "Hang up" : "Start call"}
        </Button>
        <p
          className={cn(
            "font-heading text-[13px] font-medium",
            tone === "error" && "text-destructive",
            tone === "active" && "text-ember-orange",
            tone === "neutral" && "text-brass",
          )}
          role="status"
          aria-live="polite"
        >
          {message}
        </p>
      </div>
      <p className="mt-3 text-[12px] text-quiet">
        We will ask for the microphone when you start. HTTPS or localhost required.
      </p>
    </section>
  );
}
