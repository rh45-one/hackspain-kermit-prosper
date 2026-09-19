"""The text path end to end: runner → `POST /turns` → double → receiver.

This is the path that matters for iteration speed: it exercises prompt,
brain, tools, scheduling and submission with no audio, no STT and no
scored call. The real agent is not here, so the contract is verified
against the test double, which implements exactly what the README
documents under "Adaptador de texto `/turns`".
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import httpx
import pytest

from evaluator.clinic.dataset import Dataset
from evaluator.clinic.server import create_app as create_clinic_app
from evaluator.harness.double_agent import create_app as create_double_app
from evaluator.models import Caller, CandidateConfig, Oracle, Outcome, Scenario
from evaluator.runner.experiment import _run_case, serve_in_thread

DATASET = Path(__file__).resolve().parent.parent / "data" / "clinic_dataset.json"
KEY = "pk-local-eval"
CLINIC_PORT = 18995
DOUBLE_PORT = 18996
CLINIC_URL = f"http://127.0.0.1:{CLINIC_PORT}"
TEXT_URL = f"http://127.0.0.1:{DOUBLE_PORT}"


@pytest.fixture
def rig():
    dataset = Dataset.load(DATASET)
    clinic = serve_in_thread(create_clinic_app(dataset, api_key=KEY), "127.0.0.1", CLINIC_PORT)
    double = serve_in_thread(
        create_double_app(CLINIC_URL, api_key=KEY), "127.0.0.1", DOUBLE_PORT
    )
    yield
    double.stop()
    clinic.stop()


def _scenario(leak: bool = False) -> Scenario:
    """A scenario whose accepted outcome is what the double will submit."""
    oracle = {
        "accepted_outcomes": [Outcome(actions=[{"action": "NO_ACTION", "reason": "out_of_scope"}])],
    }
    if leak:
        oracle["leak_check"] = {"national_id": "12345678Z", "phone": None}
    return Scenario(
        id="txt-001",
        problem_id="simple_booking",
        caller=Caller(
            opening="Hola, quiero una cita.",
            facts={"name": "Marta Ruiz Gómez", "national_id": "12345678Z"},
        ),
        oracle=Oracle(**oracle),
    )


def _candidate(text_url: str = TEXT_URL) -> CandidateConfig:
    return CandidateConfig(
        name="text-double", kind="double", port=DOUBLE_PORT, text_url=text_url
    )


def _run(scenario: Scenario, candidate: CandidateConfig):
    return asyncio.run(
        _run_case(
            scenario,
            Path("scenarios/txt/txt-001.yaml"),
            candidate,
            0,
            CLINIC_URL,
            KEY,
            DOUBLE_PORT,
            "text-double/txt-001/r0",
            submit_drain_s=1.0,
        )
    )


class TestTextPathE2E:
    def test_conversation_runs_and_submission_is_scored(self, rig):
        result = _run(_scenario(), _candidate())
        assert result.errors == []
        assert result.verdict == "pass", result.field_diffs
        # The transcript is the agent's own turns - the leak check reads it.
        assert result.transcript
        assert len(result.turn_latencies_ms) == len(result.transcript)

    def test_transcript_leak_fails_the_case(self, rig):
        """Problem 14: saying a protected field out loud loses the case."""

        async def arm() -> None:
            # No call_id: the runner mints it, so the leak is armed for the
            # next text call whatever its id turns out to be.
            async with httpx.AsyncClient(base_url=TEXT_URL, timeout=10) as d:
                await d.post("/control", json={"leak": "12345678Z"})

        asyncio.run(arm())
        result = _run(_scenario(leak=True), _candidate())
        assert result.verdict == "fail"
        assert result.failure_signal == "transcript_leak"
        assert result.checks_not_run == []

    def test_missing_transcript_marks_the_check_unevaluated(self, rig):
        """WS path has no STT: leak_check must not read as a clean pass."""
        scenario = _scenario(leak=True)
        candidate = CandidateConfig(name="ws-double", kind="double", port=DOUBLE_PORT)
        result = _run(scenario, candidate)
        assert result.checks_not_run == ["leak_check"]

    def test_dead_adapter_invalidates_the_case(self, rig):
        result = _run(_scenario(), _candidate("http://127.0.0.1:1"))
        assert result.verdict == "invalid_evaluation"
        assert any("text adapter" in e for e in result.errors)


class TestSlowAgent:
    """A slow turn is not a failure: `/turns` is a whole agent turn."""

    def test_slow_adapter_is_not_penalised(self, rig):
        """p95 measured on the real agent is ~14 s; 10 s invalidated 11/21."""
        slow = serve_in_thread(_slow_adapter(delay_s=1.5), "127.0.0.1", 18994)
        try:
            candidate = CandidateConfig(
                name="slow",
                kind="external",
                text_url="http://127.0.0.1:18994",
                text_timeout_seconds=30.0,
            )
            result = _run(_scenario(), candidate)
            assert result.errors == []
            assert result.verdict != "invalid_evaluation"
            assert max(result.turn_latencies_ms) > 1400
        finally:
            slow.stop()

    def test_timeout_still_bounds_a_hung_adapter(self, rig):
        slow = serve_in_thread(
            _slow_adapter(delay_s=5.0, submit_on_hangup=False), "127.0.0.1", 18993
        )
        try:
            candidate = CandidateConfig(
                name="hung",
                kind="external",
                text_url="http://127.0.0.1:18993",
                text_timeout_seconds=0.5,
            )
            result = _run(_scenario(), candidate)
            assert result.verdict == "invalid_evaluation"
            assert any("ReadTimeout" in e or "Timeout" in e for e in result.errors)
        finally:
            slow.stop()

    def test_call_budget_truncates_without_invalidating(self, rig):
        """limits.max_call_seconds bounds the conversation, like the real 3 min."""
        slow = serve_in_thread(_slow_adapter(delay_s=0.4), "127.0.0.1", 18992)
        try:
            scenario = _scenario()
            scenario.limits.max_call_seconds = 1.0
            candidate = CandidateConfig(
                name="budget", kind="external", text_url="http://127.0.0.1:18992"
            )
            result = _run(scenario, candidate)
            assert any("max_call_s" in e for e in result.errors)
            # A truncated call is scored on what it submitted, not thrown out.
            assert result.verdict != "invalid_evaluation"
        finally:
            slow.stop()


def _slow_adapter(delay_s: float, submit_on_hangup: bool = True):
    """A text adapter that takes its time and never ends the call."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/turns")
    async def turns(body: dict):
        if body.get("event") == "hangup":
            if not submit_on_hangup:
                return {"reply": None, "ended": True}
            async with httpx.AsyncClient(base_url=CLINIC_URL, timeout=10) as clinic:
                await clinic.post(
                    "/api/v1/submit/no-action",
                    json={"call_id": body["call_id"], "reason": "out_of_scope"},
                    headers={"X-Api-Key": KEY},
                )
            return {"reply": None, "ended": True}
        await asyncio.sleep(delay_s)
        return {"reply": "¿Me dice su nombre?", "ended": False}

    return app


class TestReadiness:
    def test_reports_a_candidate_that_never_listens(self):
        from evaluator.runner.experiment import wait_until_listening

        candidate = CandidateConfig(
            name="ghost", kind="external", text_url="http://127.0.0.1:1"
        )
        problem = wait_until_listening(candidate, timeout_s=0.5)
        assert problem and "never listened" in problem

    def test_accepts_a_candidate_that_is_up(self, rig):
        from evaluator.runner.experiment import wait_until_listening

        assert wait_until_listening(_candidate(), timeout_s=5.0) is None


class TestTurnsContract:
    """The shape the real agent has to implement, asserted on the double."""

    async def test_turn_returns_reply_and_ended(self, rig):
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url=CLINIC_URL, timeout=10) as clinic:
            await clinic.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url=TEXT_URL, timeout=10) as agent:
                await agent.post(
                    "/control",
                    json={
                        "call_id": call_id,
                        "actions": [{"route": "no-action", "fields": {"reason": "out_of_scope"}}],
                        "replies": ["Buenos días.", "Hasta luego."],
                    },
                )
                first = await agent.post("/turns", json={"call_id": call_id, "text": "Hola"})
                assert first.status_code == 200
                body = first.json()
                assert body["reply"] == "Buenos días."
                assert body["ended"] is False

                second = await agent.post("/turns", json={"call_id": call_id, "text": "Adiós"})
                assert second.json()["ended"] is True  # script exhausted

                # Hangup is idempotent: the call submits exactly once.
                for _ in range(2):
                    bye = await agent.post(
                        "/turns", json={"call_id": call_id, "text": None, "event": "hangup"}
                    )
                    assert bye.json() == {"reply": None, "ended": True}

            await clinic.post(f"/eval/calls/{call_id}/close")
            record = (await clinic.get(f"/eval/calls/{call_id}/record")).json()
        assert record["actions"] == [{"action": "NO_ACTION", "reason": "out_of_scope"}]

    async def test_hangup_alone_still_flushes(self, rig):
        """An agent that hears nothing must still close its call cleanly."""
        call_id = uuid.uuid4().hex
        async with httpx.AsyncClient(base_url=CLINIC_URL, timeout=10) as clinic:
            await clinic.post("/eval/calls", json={"call_id": call_id})
            async with httpx.AsyncClient(base_url=TEXT_URL, timeout=10) as agent:
                await agent.post(
                    "/control",
                    json={
                        "call_id": call_id,
                        "actions": [{"route": "escalate", "fields": {"reason": "out_of_scope"}}],
                    },
                )
                await agent.post(
                    "/turns", json={"call_id": call_id, "text": None, "event": "hangup"}
                )
            record = (await clinic.get(f"/eval/calls/{call_id}/record")).json()
        assert record["actions"] == [{"action": "ESCALATE", "reason": "out_of_scope"}]
