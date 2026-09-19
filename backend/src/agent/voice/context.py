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
    # Route-owned safety boundary. The browser simulator uses the real agent
    # pipeline but its synthetic call ids must never be sent to Prosper.
    submit_actions: bool = True

    # Identification state
    phone_hint_match: dict[str, Any] | None = None
    patient_candidates: list[dict[str, Any]] = field(default_factory=list)
    confirmed_patient: dict[str, Any] | None = None

    # Latest finalized caller utterance (server-owned; the only text Jev's
    # assess_current_turn is allowed to read). Written by add_transcript.
    latest_caller_turn: str | None = None
    # Jev's typed reading of that turn, refreshed in the background as each
    # caller turn finalises so the tools can quote it without paying for it.
    latest_decision: dict[str, Any] | None = None
    # Set once the caller has been asked whether they hold a second insurance
    # plan. A coverage refusal before that is a guess, not an answer.
    asked_about_second_plan: bool = False
    # Set by the ToolBox so every finalised caller turn is read by Jev in the
    # background. A plain callable, not a coroutine: the context must not own
    # a task or a sidecar, and add_transcript must never await anything.
    _on_caller_turn: Any = None

    # Per-call registries: tokens handed to the LLM, real values kept here.
    slot_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    appointment_registry: dict[str, dict[str, Any]] = field(default_factory=dict)
    _slot_seq: int = 0

    # Actions the call would have written (submitted at end of call).
    queued_actions: list[dict[str, Any]] = field(default_factory=list)
    submitted: bool = False

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
            self.latest_decision = None  # the old reading describes an old turn
            if self._on_caller_turn is not None:
                self._on_caller_turn(text)
        self.audit("transcript", {"role": role, "text": text})

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
                    # Which plans actually pay for THIS slot. Without it the
                    # billing plan is a guess, and the right slot billed
                    # against the wrong plan fails the case outright.
                    "payable_with": slot.get("payable_with") or [],
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
