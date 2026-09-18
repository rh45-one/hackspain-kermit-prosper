"""ClinicReflow seam: the queue of reflow cases and patient decisions.

Files are the contract with the optimizer (docs/reflow-interface.md). The
voice agent reads a case before the negotiation call and writes the decision
after it; the optimizer polls and recalculates.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_OUTCOMES = {"accepted", "rejected", "counter_offered", "unreachable"}


def _reflow_dir(data_dir: str) -> Path:
    return Path(data_dir) / "reflow"


async def load_reflow_case(appointment_id: str, data_dir: str) -> dict[str, Any]:
    """Find the batch containing this appointment and return its slice."""
    for batch_path in sorted(_reflow_dir(data_dir).glob("*.json")):
        try:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for appt in batch.get("appointments", []):
            if appt.get("appointment_id") == appointment_id:
                return {
                    "batch_id": batch.get("batch_id"),
                    "unavailable_provider_id": batch.get("unavailable_provider_id"),
                    "reason": batch.get("reason"),
                    "appointment": appt,
                }
    raise FileNotFoundError(f"no reflow case for appointment {appointment_id!r}")


async def commit_reflow_decision(
    appointment_id: str,
    outcome: str,
    call_id: str,
    data_dir: str,
    accepted_alternative_id: str | None = None,
    counter_constraints: list[str] | None = None,
) -> dict[str, Any]:
    """Write the patient's decision for the optimizer to consume."""
    outcome = outcome.strip().lower()
    if outcome not in _OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(_OUTCOMES)}")
    if outcome == "accepted" and not accepted_alternative_id:
        raise ValueError("accepted decisions need accepted_alternative_id")
    # Locate the batch that owns this appointment.
    owning_batch: str | None = None
    for batch_path in sorted(_reflow_dir(data_dir).glob("*.json")):
        try:
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if any(a.get("appointment_id") == appointment_id for a in batch.get("appointments", [])):
            owning_batch = batch_path.stem
            break
    if owning_batch is None:
        raise FileNotFoundError(f"no reflow case for appointment {appointment_id!r}")
    decision = {
        "appointment_id": appointment_id,
        "outcome": outcome,
        "accepted_alternative_id": accepted_alternative_id,
        "counter_constraints": counter_constraints or [],
        "call_id": call_id,
        "decided_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    out_dir = _reflow_dir(data_dir) / owning_batch
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{appointment_id}.json"
    path.write_text(json.dumps(decision, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"saved": str(path), **decision}
