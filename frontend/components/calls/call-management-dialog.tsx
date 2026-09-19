"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import {
  ArrowRightLeft,
  Hand,
  Pause,
  PhoneOff,
  Send,
  UserRound,
  XIcon,
} from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";

import { TranscriptThread } from "@/components/calls/transcript-thread";
import { useFrontdesk } from "@/components/frontdesk-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  callCardElementId,
  callDisplayName,
  callLineLabel,
  formatElapsed,
} from "@/lib/call-format";
import { DEFAULT_CALL_CONTROL, type LiveCall } from "@/lib/types";
import { cn } from "@/lib/utils";

const UNWIRED = "This action is not available yet. It will land once the line is wired.";

function StatusDot({ live }: { live: boolean }) {
  return (
    <span
      className={cn(
        "size-1.5 rounded-full",
        live ? "bg-ember-orange" : "bg-quiet/70",
      )}
      aria-hidden
    />
  );
}

export function CallManagementDialog({
  call,
  onClose,
}: {
  call: LiveCall | null;
  onClose: () => void;
}) {
  const {
    demo,
    takeControl,
    takeOperatorControl,
    releaseOperatorControl,
    pauseAutomation,
    sendOperatorMessage,
    controlFor,
  } = useFrontdesk();
  const titleId = useId();
  const descriptionId = useId();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sendStatus, setSendStatus] = useState<{
    callId: string;
    message: string;
  } | null>(null);

  const open = call !== null;
  const control = call ? controlFor(call.callId) : DEFAULT_CALL_CONTROL;
  const draft = call ? (drafts[call.callId] ?? "") : "";
  const sendHint =
    call && sendStatus?.callId === call.callId ? sendStatus.message : null;
  const ended = call?.status === "ended";
  const live = call?.status === "active";
  const held = control.heldByOperator;
  const canTake = Boolean(call) && !ended && !held;
  const composerEnabled = Boolean(call) && !ended && held;
  const blockBackdropClose = draft.trim().length > 0 || held;

  useEffect(() => {
    if (!open) {
      return;
    }
    const tick = () => setNowMs(Date.now());
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [open, call?.callId]);

  useEffect(() => {
    if (!held || ended) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      composerRef.current?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [call?.callId, ended, held]);

  const setDraft = (value: string) => {
    if (!call) {
      return;
    }
    setDrafts((current) => ({ ...current, [call.callId]: value }));
    setSendStatus(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      onClose();
    }
  };

  const guardDismiss = (event: { preventDefault: () => void }) => {
    if (blockBackdropClose) {
      event.preventDefault();
    }
  };

  const submitDraft = () => {
    if (!call || !composerEnabled) {
      return;
    }
    const text = draft.trim();
    if (!text) {
      return;
    }
    const result = sendOperatorMessage(call.callId, text);
    if (!result.ok) {
      setSendStatus({ callId: call.callId, message: result.error });
    }
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitDraft();
    }
  };

  const displayName = callDisplayName(call?.entities.name);
  const duration = call ? formatElapsed(call.startedAt, nowMs) : "—";
  const controllerLabel = ended
    ? "Conversation closed"
    : held
      ? "Reception is holding it"
      : "The booking assistant is holding it";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogPortal>
        <DialogOverlay className="bg-graphite/42 supports-backdrop-filter:backdrop-blur-[6px]" />
        <DialogPrimitive.Content
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          onPointerDownOutside={guardDismiss}
          onInteractOutside={guardDismiss}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (call) {
              document.getElementById(callCardElementId(call.callId))?.focus();
            }
          }}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex w-[min(85vw,1120px)] max-w-[calc(100%-1.25rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden border border-mist bg-canvas-white text-graphite shadow-[var(--shadow-md)] outline-none",
            "h-[min(85dvh,840px)] rounded-[18px] duration-200 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            "max-md:inset-0 max-md:h-dvh max-md:w-full max-md:max-w-none max-md:translate-x-0 max-md:translate-y-0 max-md:rounded-none",
            "md:h-[min(82dvh,800px)]",
          )}
        >
          {call ? (
            <div className="grid min-h-0 flex-1 grid-rows-[minmax(14rem,1fr)_minmax(0,auto)] lg:grid-cols-[minmax(0,1fr)_18.5rem] lg:grid-rows-none">
              <div className="flex min-h-0 min-w-0 flex-col">
                <header className="flex shrink-0 items-start justify-between gap-4 border-b border-mist px-5 py-4 sm:px-6">
                  <div className="min-w-0">
                    <p className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
                      Conversation
                    </p>
                    <DialogTitle
                      id={titleId}
                      className="mt-1 truncate text-[clamp(1.35rem,2.4vw,1.85rem)] leading-none"
                    >
                      {displayName}
                    </DialogTitle>
                    <DialogDescription
                      id={descriptionId}
                      className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-quiet"
                    >
                      <span className="inline-flex items-center gap-1.5 text-steel">
                        <StatusDot live={Boolean(live)} />
                        {live ? "On the phone now" : ended ? "They hung up" : "Status unclear"}
                      </span>
                      <span>{callLineLabel(call.socketId)}</span>
                      <span>{call.virtualPhone}</span>
                      <span>{duration}</span>
                    </DialogDescription>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Close call management"
                    onClick={onClose}
                  >
                    <XIcon />
                  </Button>
                </header>

                <div className="flex shrink-0 items-center justify-between gap-3 border-b border-mist bg-fog/50 px-5 py-2.5 lg:hidden">
                  <p className="min-w-0 truncate font-heading text-[13px] text-steel">
                    {controllerLabel}
                  </p>
                  {canTake ? (
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => takeOperatorControl(call.callId)}
                    >
                      <Hand />
                      Take control
                    </Button>
                  ) : held && !ended ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => releaseOperatorControl(call.callId)}
                    >
                      Hand back to the assistant
                    </Button>
                  ) : null}
                </div>

                <TranscriptThread call={call} variant="full" />

                <div className="shrink-0 border-t border-mist bg-canvas-white px-4 py-3 sm:px-5">
                  <label className="sr-only" htmlFor={`composer-${call.callId}`}>
                    Manual reply
                  </label>
                  <div className="flex items-end gap-2.5">
                    <Textarea
                      ref={composerRef}
                      id={`composer-${call.callId}`}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={onComposerKeyDown}
                      disabled={!composerEnabled}
                      rows={2}
                      placeholder={
                        ended
                          ? "The conversation is closed."
                          : held
                            ? "Write a reply. Enter sends, Shift+Enter for a new line."
                            : "Take control to reply."
                      }
                      className="min-h-[4.5rem] resize-none"
                    />
                    <Button
                      type="button"
                      size="icon"
                      aria-label="Send reply"
                      disabled={!composerEnabled || draft.trim().length === 0}
                      onClick={submitDraft}
                    >
                      <Send />
                    </Button>
                  </div>
                  <p className="mt-2 text-[12px] text-quiet">
                    {sendHint ??
                      (ended
                        ? "This call no longer accepts intervention."
                        : composerEnabled
                          ? "Your messages are saved here. Live send will be wired later."
                          : held
                            ? controllerLabel
                            : "The assistant stays in charge until you take control.")}
                  </p>
                </div>
              </div>

              <aside className="flex min-h-0 max-h-[34vh] flex-col gap-5 overflow-y-auto border-t border-mist bg-fog/40 px-5 py-5 lg:max-h-none lg:border-t-0 lg:border-l">
                <div>
                  <p className="font-heading text-[11px] tracking-[0.08em] text-brass uppercase">
                    Control
                  </p>
                  <p className="mt-2 font-heading text-[16px] leading-snug text-graphite transition-colors duration-200">
                    {controllerLabel}
                  </p>
                  <p className="mt-1 text-[13px] leading-snug text-quiet">
                    {ended
                      ? "This call no longer accepts intervention."
                      : held
                        ? "The assistant is paused. You reply from here."
                        : "The booking assistant is talking to the person on the line."}
                  </p>
                </div>

                {canTake ? (
                  <Button
                    type="button"
                    className="hidden w-full lg:inline-flex"
                    onClick={() => takeOperatorControl(call.callId)}
                  >
                    <Hand />
                    Take control
                  </Button>
                ) : held && !ended ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="hidden w-full lg:inline-flex"
                    onClick={() => releaseOperatorControl(call.callId)}
                  >
                    Hand back to the assistant
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="outline"
                    className="hidden w-full lg:inline-flex"
                    disabled
                  >
                    <PhoneOff />
                    Control taken
                  </Button>
                )}

                <div>
                  <p className="mb-3 font-heading text-[13px] text-quiet">
                    What it is capturing
                  </p>
                  <dl className="space-y-3 text-[13px]">
                    <div>
                      <dt className="text-quiet">Caller</dt>
                      <dd className="mt-0.5 break-words text-graphite">
                        {call.entities.name ?? "Not said yet"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-quiet">ID</dt>
                      <dd className="mt-0.5 truncate font-mono text-graphite">
                        {call.entities.nationalId ?? "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-quiet">Asking for</dt>
                      <dd className="mt-0.5 break-words text-graphite">
                        {call.entities.appointmentType ?? "To confirm"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-quiet">Line</dt>
                      <dd className="mt-0.5 text-graphite">
                        {callLineLabel(call.socketId)}
                      </dd>
                    </div>
                  </dl>
                </div>

                <div className="grid grid-cols-1 gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start"
                    disabled={!demo || ended}
                    onClick={() =>
                      pauseAutomation(call.callId, !control.automationPaused)
                    }
                  >
                    <Pause />
                    {control.automationPaused
                      ? "Let the assistant talk again"
                      : "Pause the assistant"}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start"
                    disabled
                    title={UNWIRED}
                  >
                    <ArrowRightLeft />
                    Transfer
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start"
                    disabled
                    title={UNWIRED}
                  >
                    <UserRound />
                    Assign
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-start"
                    disabled={!demo || ended}
                    onClick={() => takeControl(call.callId)}
                  >
                    <PhoneOff />
                    End conversation
                  </Button>
                </div>
              </aside>
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPortal>
    </Dialog>
  );
}
