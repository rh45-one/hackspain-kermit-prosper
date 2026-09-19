"""What the agent itself recorded about a call, read without trusting it.

A wire-only harness can see that it sent six seconds of speech and that the
agent answered with a greeting: it cannot see whether the agent *heard* it.
The agent's own audit trail can, so the tester reads it - optionally, by path,
never by importing or reaching into the agent's checkout.

Two rules keep this honest:

- It is agent-provided evidence, not a contract. The layout can change and the
  only consequence is that the diagnosis says "unavailable".
- It never decides a verdict. It decides whether the verdict is *attributable
  to the model*: a call where the caller's speech never arrived must be
  reported as an agent-side failure, not scored against the model.

Partial and corrupt lines are skipped: an audit file is appended to while the
call is still running, and a half-written line is not a reason to fail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Below this, there was not enough caller speech to judge the agent.
MIN_CALLER_SPEECH_S = 2.0
# Characters per second of caller speech below which the transcript looks
# truncated rather than merely short (a heuristic, and reported as one).
MIN_CHARS_PER_SECOND = 2.0


@dataclass
class AgentAudit:
    """What the agent's audit trail says about one call."""

    available: bool
    path: Path | None = None
    caller_text: str = ""
    assistant_text: str = ""
    stages: tuple[str, ...] = ()
    actions_queued: int = 0
    submissions_succeeded: int = 0
    submissions_failed: int = 0
    ended: bool = False

    @property
    def caller_chars(self) -> int:
        return len(self.caller_text.strip())


@dataclass
class CallerAudioDiagnosis:
    """Why a call with caller speech produced no usable caller transcript."""

    kind: Literal["agent_failure", "truncated", "unavailable"]
    message: str

    @property
    def blocks_model_scoring(self) -> bool:
        """True when the fault is upstream of the model, so a verdict is unfair."""
        return self.kind in ("agent_failure", "truncated")

    def __str__(self) -> str:
        return self.message


def agent_audit_dir_for(call_id: str, base: Path | str) -> Path | None:
    """Accept either the agent's data dir or its `calls` dir, or say no."""
    base = Path(base)
    for candidate in (base, base / "calls"):
        if (candidate / f"{call_id}.jsonl").is_file():
            return candidate
    return None


def read_agent_audit(call_id: str, calls_dir: Path | str) -> AgentAudit:
    """Read `<calls_dir>/<call_id>.jsonl` if it exists, tolerating bad lines."""
    path = Path(calls_dir) / f"{call_id}.jsonl"
    if not path.is_file():
        return AgentAudit(available=False)
    audit = AgentAudit(available=True, path=path)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        event = record.get("event")
        data = record.get("data")
        data = data if isinstance(data, dict) else {}
        if event == "transcript":
            text = data.get("text")
            if not isinstance(text, str):
                continue
            if data.get("role") == "caller":
                audit.caller_text += text
            elif data.get("role") == "assistant":
                audit.assistant_text += text
        elif event == "pipeline_stage":
            stage = data.get("stage")
            if isinstance(stage, str) and stage not in audit.stages:
                audit.stages = (*audit.stages, stage)
        elif event == "action_queued":
            audit.actions_queued += 1
        elif event == "submitted":
            audit.submissions_succeeded += 1
        elif event == "submit_failed":
            audit.submissions_failed += 1
        elif event in ("flush_done", "socket_stop"):
            audit.ended = True
    return audit


def diagnose_caller_audio(caller_seconds: float, audit: AgentAudit) -> CallerAudioDiagnosis | None:
    """Explain a call where the caller spoke and the agent recorded nothing.

    Returns None when the call looks ordinary, so a healthy run stays quiet.
    """
    if caller_seconds < MIN_CALLER_SPEECH_S:
        return None
    if not audit.available:
        return CallerAudioDiagnosis(
            kind="unavailable",
            message=(
                f"el tester envió {caller_seconds:.1f}s de voz del caller y no hay "
                "auditoría del agente para contrastar (pasá --agent-audit-dir para "
                "diagnosticar si el agente escuchó)"
            ),
        )
    rate = audit.caller_chars / max(caller_seconds, 0.1)
    if audit.caller_chars == 0:
        return CallerAudioDiagnosis(
            kind="agent_failure",
            message=(
                f"FALLA DEL LADO DEL AGENTE: el tester envió {caller_seconds:.1f}s de voz "
                f"y el agente no registró ni un carácter de transcript del caller "
                f"(saludó {len(audit.assistant_text.strip())} caracteres igual). "
                "No es una medición del modelo: la señal de entrada no llegó."
            ),
        )
    if rate < MIN_CHARS_PER_SECOND:
        return CallerAudioDiagnosis(
            kind="truncated",
            message=(
                f"TRANSCRIPT TRUNCADO: {caller_seconds:.1f}s de voz del caller produjeron "
                f"solo {audit.caller_chars} caracteres ({rate:.1f}/s). "
                "Probable falla de entrada del agente antes de puntuar el modelo."
            ),
        )
    return None
