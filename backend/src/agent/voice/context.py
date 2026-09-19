"""Per-call state. One CallContext per socket; nothing shared across calls."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# How long the pipeline waits for the harness `start` event after client
# connect before giving up on the from_number hint.
START_WAIT_SECONDS = 0.5


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class CallContext:
    """Everything a single phone call owns: identity, registries, audit."""

    data_dir: str = "./data"
    call_id: str = field(default_factory=lambda: f"local-{int(time.time() * 1000)}")
    stream_sid: str = ""
    from_number: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    stopped: bool = False

    # Identification state
    phone_hint_match: dict[str, Any] | None = None
    patient_candidates: list[dict[str, Any]] = field(default_factory=list)
    confirmed_patient: dict[str, Any] | None = None

    # Latest finalized caller utterance (server-owned; the only text Jev's
    # assess_current_turn is allowed to read). Written by add_transcript.
    latest_caller_turn: str | None = None

    # Per-call registries: tokens handed to the LLM, real values kept here.
    slot_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    appointment_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    _slot_seq: int = 0

    # Actions the call would have written (submitted at end of call).
    queued_actions: list[dict[str, Any]] = field(default_factory=list)
    submitted: bool = False

    # Privacy-safe progress signals used to explain terminal silent calls.
    # They never retain transcript text, tool arguments, or patient details.
    pipeline_stages: set[str] = field(default_factory=set)
    pipeline_error: bool = False
    outcome_summary_emitted: bool = False

    # Transcript + audit
    transcript: list[dict[str, str]] = field(default_factory=list)
    _audit_path: Path | None = None

    # Set when the call ends so in-flight sidecar work (Jev) aborts promptly.
    cancel_token: asyncio.Event = field(default_factory=asyncio.Event)

    # Set by the serializer once the harness `start` event is captured; the
    # pipeline waits on it (bounded) before using the from_number hint.
    start_received: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        calls_dir = Path(self.data_dir) / "calls"
        calls_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path = calls_dir / f"{self.call_id}.jsonl"
        self.audit("call_context_created", {"from_number": self.from_number})

    # ---- identity --------------------------------------------------------
    def set_call_id(self, call_id: str) -> None:
        """Bind the harness callSid when the start event arrives.

        The context is created with a provisional id before the harness
        speaks; once callSid is known the audit trail moves with it so the
        per-call record lives at data/calls/<call_id>.jsonl.
        """
        if not call_id or call_id == self.call_id:
            return
        old_path = self._audit_path
        self.call_id = call_id
        new_path = Path(self.data_dir) / "calls" / f"{call_id}.jsonl"
        if old_path is not None and old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
        self._audit_path = new_path
        self.audit("call_id_bound", {})

    def mark_start_received(self) -> None:
        """Signal that the harness `start` event has been captured."""
        if not self.start_received.is_set():
            self.start_received.set()
            self.audit("start_received", {"from_number_present": self.from_number is not None})

    async def wait_for_start(self, timeout: float = START_WAIT_SECONDS) -> bool:
        """Wait up to `timeout` for the start event. True when it arrived."""
        if self.start_received.is_set():
            return True
        try:
            await asyncio.wait_for(self.start_received.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    # ---- audit -----------------------------------------------------------
    def audit(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self._audit_path is None:
            return
        record = {"ts": _utcnow(), "event": event, "data": data or {}}
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add_transcript(self, role: str, text: str) -> None:
        self.transcript.append({"role": role, "text": text})
        if role == "caller":
            # Finalized caller text: the ONLY transcript Jev may ever see.
            self.latest_caller_turn = text
            self.mark_pipeline_stage("caller_transcribed")
        elif role == "assistant":
            self.mark_pipeline_stage("assistant_responded")
        self.audit("transcript", {"role": role, "text": text})

    def mark_pipeline_stage(self, stage: str) -> None:
        """Record a privacy-safe milestone once for the call diagnostic."""
        if stage not in self.pipeline_stages:
            self.pipeline_stages.add(stage)
            self.audit("pipeline_stage", {"stage": stage})

    def mark_pipeline_error(self) -> None:
        """Remember a terminal pipeline failure without recording its payload."""
        self.pipeline_error = True
        self.mark_pipeline_stage("pipeline_error")

    def emit_outcome_summary(
        self,
        *,
        actions_before_flush: int,
        fallback_action_added: bool,
        submissions_succeeded: int,
        submissions_failed: int,
        submission_configured: bool,
    ) -> None:
        """Write one terminal, PII-free explanation of the call outcome."""
        if self.outcome_summary_emitted:
            return
        self.outcome_summary_emitted = True

        stages = sorted(self.pipeline_stages)
        empty_action_reason: str | None = None
        if actions_before_flush == 0:
            if self.pipeline_error:
                empty_action_reason = "pipeline_error"
            elif "tool_failed" in self.pipeline_stages:
                empty_action_reason = "tool_failure"
            elif "caller_audio_received" not in self.pipeline_stages:
                empty_action_reason = "no_caller_audio"
            elif "caller_transcribed" not in self.pipeline_stages:
                empty_action_reason = "no_caller_transcript"
            elif "assistant_responded" not in self.pipeline_stages:
                empty_action_reason = "no_assistant_response"
            else:
                empty_action_reason = "no_action_queued"

        self.audit(
            "call_outcome_summary",
            {
                "stages": stages,
                "queued_action_count": actions_before_flush,
                "fallback_action_added": fallback_action_added,
                "empty_action_reason": empty_action_reason,
                "submission_configured": submission_configured,
                "submissions_succeeded": submissions_succeeded,
                "submissions_failed": submissions_failed,
            },
        )

    # ---- registries ------------------------------------------------------
    def register_slots(self, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Store availability slots and return token-labelled summaries."""
        labelled = []
        for slot in slots:
            self._slot_seq += 1
            token = f"s{self._slot_seq}"
            self.slot_registry[token] = slot
            labelled.append(
                {
                    "token": token,
                    "provider_name": slot.get("provider_name"),
                    "provider_id": slot.get("provider_id"),
                    "location_id": slot.get("location_id"),
                    "start_time": slot.get("start_time"),
                    "duration_minutes": slot.get("duration_minutes"),
                    "appointment_type_id": slot.get("appointment_type_id"),
                }
            )
        return labelled

    def register_appointments(self, appointments: list[dict[str, Any]]) -> None:
        for appt in appointments:
            self.appointment_registry[appt.get("appointment_id", "")] = appt

    # ---- lifecycle -------------------------------------------------------
    def mark_stopped(self) -> None:
        if not self.stopped:
            self.stopped = True
            self.cancel_token.set()  # abort in-flight Jev work
            self.audit("socket_stop", {"elapsed_s": round(time.monotonic() - self.started_at, 1)})

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at
