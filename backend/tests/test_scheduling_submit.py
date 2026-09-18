"""Submitter tests: exact route/body, status handling, bounded retries, close."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest

from agent.scheduling.recorder import ActionRecorder
from agent.scheduling.submit import SubmitOutcome, Submitter

BOOK = {
    "route": "book",
    "patient_id": "P00042",
    "provider_id": "PR05",
    "location_id": "sur",
    "appointment_type_id": "review",
    "slot": "2026-09-24T16:30:07+02:00",
    "policy_id": "sanitas",
}


def make_submitter(handler: Any, **kwargs: Any) -> Submitter:
    return Submitter(
        "https://clinic.test",
        "pk-test",
        transport=httpx.MockTransport(handler),
        backoff_base=0.0,
        **kwargs,
    )


def test_route_body_and_api_key() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-api-key")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"call_id": "C1", "received_at": "x", "record": {"actions": []}}
        )

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "accepted"
    assert outcome.accepted
    assert captured["url"].endswith("/api/v1/submit/book")
    assert captured["key"] == "pk-test"
    assert captured["body"] == {
        "call_id": "C1",
        "patient_id": "P00042",
        "provider_id": "PR05",
        "location_id": "sur",
        "appointment_type_id": "review",
        "slot": "2026-09-24T16:30:00+02:00",
        "policy_id": "sanitas",
    }


def test_duplicate_409_is_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "already accepted"})

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "duplicate"
    assert outcome.accepted


@pytest.mark.parametrize("status", [404, 410])
def test_terminal_statuses_are_not_retried(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="closed")

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "terminal"
    assert outcome.http_status == status
    assert calls == 1


def test_422_is_a_data_bug_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"detail": "bad slot"})

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "data_bug"
    assert outcome.http_status == 422
    assert calls == 1


def test_5xx_is_retried_then_accepted() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(
            200, json={"call_id": "C1", "received_at": "x", "record": {"actions": []}}
        )

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "accepted"
    assert calls == 2


def test_transport_error_is_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            200, json={"call_id": "C1", "received_at": "x", "record": {"actions": []}}
        )

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "accepted"
    assert calls == 2


def test_5xx_exhausts_bounded_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    async def run() -> SubmitOutcome:
        async with make_submitter(handler, retries=2) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "failed"
    assert calls == 3


def test_other_4xx_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad request")

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "failed"
    assert calls == 1


def test_invalid_action_is_a_data_bug_without_http() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit({"route": "book", "patient_id": "P1"}, "C1")

    outcome = asyncio.run(run())
    assert outcome.status == "data_bug"
    assert calls == 0


def test_client_is_closed_after_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def run() -> bool:
        submitter = make_submitter(handler)
        async with submitter:
            assert not submitter.closed
        return submitter.closed

    assert asyncio.run(run())


def test_deadline_skips_without_http() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    async def run() -> SubmitOutcome:
        async with make_submitter(handler) as submitter:
            return await submitter.submit(BOOK, "C1", deadline=time.monotonic() - 1.0)

    outcome = asyncio.run(run())
    assert outcome.status == "skipped"
    assert calls == 0


def test_worst_case_fits_submission_window() -> None:
    submitter = Submitter("https://clinic.test", "pk", timeout=4.0, retries=2, backoff_base=0.25)
    assert submitter.worst_case_seconds < 30.0


class FakeSubmitter:
    """Deterministic stand-in used to test the recorder's flush policy."""

    def __init__(
        self,
        statuses: list[str],
        *,
        clock: list[float] | None = None,
        cost: float = 0.0,
    ) -> None:
        self.statuses = list(statuses)
        self.calls: list[tuple[str, str]] = []
        self.clock = clock
        self.cost = cost

    async def submit(
        self, action: dict[str, Any], call_id: str, *, deadline: float | None = None
    ) -> SubmitOutcome:
        self.calls.append((call_id, action.get("route", "")))
        if self.clock is not None:
            self.clock[0] += self.cost
        status = self.statuses.pop(0) if self.statuses else "accepted"
        return SubmitOutcome(route=action.get("route", ""), status=status)


def test_flush_reports_outcomes() -> None:
    recorder = ActionRecorder("C1")
    recorder.record(BOOK)
    recorder.record({"route": "no-action", "reason": "no_availability"})
    fake = FakeSubmitter(["accepted", "duplicate"])

    report = asyncio.run(recorder.flush(fake))

    assert report.accepted == 1
    assert report.duplicates == 1
    assert report.complete
    assert fake.calls == [("C1", "book"), ("C1", "no-action")]


def test_flush_stops_at_deadline() -> None:
    recorder = ActionRecorder("C1")
    for _ in range(3):
        recorder.record(BOOK)
    clock = [0.0]
    fake = FakeSubmitter(["accepted", "accepted", "accepted"], clock=clock, cost=20.0)

    report = asyncio.run(recorder.flush(fake, deadline=30.0, clock=lambda: clock[0]))

    assert report.accepted == 2
    assert report.skipped == 1
    assert not report.complete
    assert len(fake.calls) == 2


def test_twenty_independent_recorders_and_submissions() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["call_id"])
        return httpx.Response(
            200,
            json={"call_id": body["call_id"], "received_at": "x", "record": {"actions": []}},
        )

    async def run() -> list[tuple[int, int, int]]:
        recorders = [ActionRecorder(f"call-{index}") for index in range(20)]
        submitters = [make_submitter(handler) for _ in range(20)]
        for recorder in recorders:
            recorder.record(BOOK)
        try:
            reports = await asyncio.gather(
                *(
                    recorder.flush(submitter)
                    for recorder, submitter in zip(recorders, submitters, strict=True)
                )
            )
        finally:
            await asyncio.gather(*(submitter.close() for submitter in submitters))
        return [(report.accepted, report.failed, report.skipped) for report in reports]

    results = asyncio.run(run())
    assert results == [(1, 0, 0)] * 20
    assert sorted(seen) == sorted(f"call-{index}" for index in range(20))
