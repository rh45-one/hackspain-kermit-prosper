"""Offline tests for the privacy-safe terminal call diagnostic."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent.ops import console
from agent.voice.context import CallContext
from agent.voice.flush import flush_call


class FakeSubmitter:
    """Accepts submissions without a network request."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key

    async def post_route(self, action, call_id, *, deadline=None) -> None:
        return None

    async def close(self) -> None:
        return None


class Settings:
    prosper_api_base_url = "https://prosper.example"
    prosper_api_key = "pk-test"
    submit_window_seconds = 30


def summary_of(ctx: CallContext) -> dict:
    records = [json.loads(line) for line in Path(ctx._audit_path).read_text().splitlines()]
    return next(record["data"] for record in records if record["event"] == "call_outcome_summary")


async def flush(ctx: CallContext, monkeypatch) -> None:
    import agent.scheduling.submit as submit_module

    monkeypatch.setattr(submit_module, "Submitter", FakeSubmitter)
    await flush_call(ctx, Settings())


async def test_silent_call_records_missing_audio_reason(tmp_path, monkeypatch):
    ctx = CallContext(data_dir=str(tmp_path / "data"), call_id="CA-silent")
    ctx.mark_pipeline_stage("client_connected")

    await flush(ctx, monkeypatch)

    assert summary_of(ctx) == {
        "stages": ["client_connected", "submission_attempted"],
        "queued_action_count": 0,
        "fallback_action_added": True,
        "empty_action_reason": "no_caller_audio",
        "submission_configured": True,
        "submissions_succeeded": 1,
        "submissions_failed": 0,
    }


async def test_tool_failure_explains_empty_action_queue(tmp_path, monkeypatch):
    ctx = CallContext(data_dir=str(tmp_path / "data"), call_id="CA-tool-failure")
    ctx.mark_pipeline_stage("caller_audio_received")
    ctx.add_transcript("caller", "Necesito una cita")
    ctx.mark_pipeline_stage("tool_failed")

    await flush(ctx, monkeypatch)

    summary = summary_of(ctx)
    assert summary["empty_action_reason"] == "tool_failure"
    assert summary["fallback_action_added"] is True


async def test_queued_action_has_no_empty_action_reason(tmp_path, monkeypatch):
    ctx = CallContext(data_dir=str(tmp_path / "data"), call_id="CA-booked")
    ctx.queued_actions.append({"route": "no-action", "reason": "no_availability"})

    await flush(ctx, monkeypatch)

    summary = summary_of(ctx)
    assert summary["queued_action_count"] == 1
    assert summary["fallback_action_added"] is False
    assert summary["empty_action_reason"] is None


async def test_ops_call_list_exposes_diagnostic_summary(tmp_path, monkeypatch):
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    (calls_dir / "CA-ops.jsonl").write_text(
        json.dumps({"event": "action_queued", "data": {"route": "book"}})
        + "\n"
        + json.dumps(
            {
                "event": "call_outcome_summary",
                "data": {"empty_action_reason": "no_assistant_response"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(console, "settings", lambda: SimpleNamespace(calls_dir=str(calls_dir)))

    assert await console.calls() == [
        {
            "call_id": "CA-ops",
            "actions": 1,
            "summary": {"empty_action_reason": "no_assistant_response"},
        }
    ]
