"""The agent-audit cross-check: who failed, the model or the input path.

The live run against the main backend produced exactly the case this guards
against: the tester sent seconds of clear caller speech, the agent answered
with a greeting, and the audit trail contained no caller transcript at all.
Scoring that call against the model would report a model failure for a broken
input path. These tests pin the reading and the diagnosis, both offline.
"""
from __future__ import annotations

import json

from evaluator.harness.agent_audit import (
    AgentAudit,
    agent_audit_dir_for,
    diagnose_caller_audio,
    read_agent_audit,
)

CALL = "tester-abc123"


def _write(tmp_path, lines: list[object]) -> str:
    path = tmp_path / f"{CALL}.jsonl"
    path.write_text(
        "\n".join(line if isinstance(line, str) else json.dumps(line) for line in lines),
        encoding="utf-8",
    )
    return str(tmp_path)


def test_missing_audit_is_reported_as_unavailable(tmp_path):
    audit = read_agent_audit(CALL, tmp_path)
    assert audit.available is False
    assert audit.path is None
    assert audit.caller_chars == 0


def test_partial_and_foreign_events_are_skipped(tmp_path):
    calls_dir = _write(
        tmp_path,
        [
            {"event": "transcript", "data": {"role": "caller", "text": "Hola"}},
            '{"event": "transcript", "data": {"role": "calle',  # half-written
            "null",
            "[1, 2, 3]",
            {"event": "transcript", "data": {"role": "caller", "text": 42}},
            {"event": "unknown_event", "data": {"anything": True}},
            {"event": "transcript", "data": {"role": "assistant", "text": " ¿En qué puedo ayudarle?"}},
            {"event": "action_queued", "data": {"route": "no-action"}},
            {"event": "submitted", "data": {"route": "no-action"}},
            {"event": "submit_failed", "data": {"route": "book"}},
            {"event": "pipeline_stage", "data": {"stage": "caller_audio_received"}},
            {"event": "pipeline_stage", "data": {"stage": "caller_audio_received"}},
            {"event": "flush_done", "data": {}},
        ],
    )
    audit = read_agent_audit(CALL, calls_dir)
    assert audit.available is True
    assert audit.caller_text == "Hola"
    assert audit.assistant_text.strip() == "¿En qué puedo ayudarle?"
    assert audit.stages == ("caller_audio_received",)
    assert audit.actions_queued == 1
    assert audit.submissions_succeeded == 1
    assert audit.submissions_failed == 1
    assert audit.ended is True


def test_audit_with_no_events_is_still_available(tmp_path):
    calls_dir = _write(tmp_path, ['{"event":'])
    audit = read_agent_audit(CALL, calls_dir)
    assert audit.available is True
    assert audit.caller_chars == 0
    assert audit.ended is False


def test_audit_dir_accepts_the_data_dir_or_the_calls_dir(tmp_path):
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / f"{CALL}.jsonl").write_text("{}\n", encoding="utf-8")
    assert agent_audit_dir_for(CALL, tmp_path) == calls
    assert agent_audit_dir_for(CALL, calls) == calls
    assert agent_audit_dir_for("other-call", tmp_path) is None


def test_too_little_speech_is_not_judged():
    audit = AgentAudit(available=True)
    assert diagnose_caller_audio(0.5, audit) is None


def test_no_audit_available_points_at_the_flag():
    diagnosis = diagnose_caller_audio(8.0, AgentAudit(available=False))
    assert diagnosis is not None
    assert diagnosis.kind == "unavailable"
    assert not diagnosis.blocks_model_scoring
    assert "8.0s" in diagnosis.message
    assert "--agent-audit-dir" in diagnosis.message


def test_speech_sent_with_no_caller_transcript_is_an_agent_failure():
    audit = AgentAudit(available=True, assistant_text="Clínica Arenal, buenos días.")
    diagnosis = diagnose_caller_audio(14.0, audit)
    assert diagnosis is not None
    assert diagnosis.kind == "agent_failure"
    assert diagnosis.blocks_model_scoring
    assert "FALLA DEL LADO DEL AGENTE" in diagnosis.message
    assert "14.0s" in diagnosis.message
    assert "No es una medición del modelo" in diagnosis.message


def test_truncated_transcript_is_flagged_before_scoring():
    audit = AgentAudit(available=True, caller_text="Hola")
    diagnosis = diagnose_caller_audio(14.0, audit)
    assert diagnosis is not None
    assert diagnosis.kind == "truncated"
    assert diagnosis.blocks_model_scoring
    assert "TRANSCRIPT TRUNCADO" in diagnosis.message


def test_a_healthy_call_stays_quiet():
    audit = AgentAudit(
        available=True,
        caller_text=(
            "Hola, buenas tardes, quería pedir una cita de medicina general "
            "para Marta Ruiz Gómez con documento 12345678Z."
        ),
        assistant_text="Claro, ¿le viene bien el lunes a las nueve?",
    )
    assert diagnose_caller_audio(14.0, audit) is None


def test_short_speech_with_a_short_transcript_is_not_flagged():
    # A two-second "sí, perfecto" is complete, not truncated.
    audit = AgentAudit(available=True, caller_text="Sí, perfecto")
    assert diagnose_caller_audio(2.0, audit) is None
