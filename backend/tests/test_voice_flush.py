"""Submission flush tests: exactly-once semantics, window discipline, offline guard.

The Submitter is replaced with a fake, so no HTTP request ever leaves the
process. Submitter's own retry/409 behaviour is covered by the scheduling
module's tests.
"""
from __future__ import annotations

from typing import ClassVar

import pytest

from agent.voice.context import CallContext
from agent.voice.flush import flush_call

BOOK_ACTION = {
    "route": "book",
    "patient_id": "P00042",
    "provider_id": "PR05",
    "location_id": "sur",
    "appointment_type_id": "review",
    "slot": "2026-09-24T16:30:00+02:00",
    "policy_id": "sanitas",
}


class FakeSubmitter:
    """Records post_route calls; never touches the network."""

    instances: ClassVar[list[FakeSubmitter]] = []

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.calls: list[dict] = []
        self.closed = False
        FakeSubmitter.instances.append(self)

    async def post_route(self, action: dict, call_id: str, *, deadline: float | None = None):
        self.calls.append({"action": dict(action), "call_id": call_id, "deadline": deadline})

    async def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_submitter(monkeypatch):
    """Swap in the fake wherever flush_call resolves Submitter at call time."""
    FakeSubmitter.instances = []
    import agent.scheduling.submit as submit_module

    monkeypatch.setattr(submit_module, "Submitter", FakeSubmitter)
    return FakeSubmitter


def make_ctx(tmp_path, actions: list[dict] | None = None) -> CallContext:
    ctx = CallContext(data_dir=str(tmp_path / "data"), call_id="CA-flush-test")
    ctx.queued_actions = list(actions or [])
    return ctx


class _Settings:
    prosper_api_base_url = "https://prosper.example"
    prosper_api_key = "pk-test"
    submit_window_seconds = 30


async def test_flush_posts_every_queued_action_with_deadline(tmp_path, fake_submitter):
    ctx = make_ctx(tmp_path, [BOOK_ACTION, {"route": "cancel", "appointment_id": "A-1"}])

    await flush_call(ctx, _Settings())

    submitter = FakeSubmitter.instances[-1]
    assert [c["call_id"] for c in submitter.calls] == ["CA-flush-test", "CA-flush-test"]
    assert submitter.calls[0]["action"]["route"] == "book"
    assert submitter.calls[1]["action"]["appointment_id"] == "A-1"
    # The submission window deadline is handed to the submitter.
    assert all(c["deadline"] is not None for c in submitter.calls)
    assert submitter.closed is True  # httpx client never leaks


async def test_flush_runs_exactly_once(tmp_path, fake_submitter):
    ctx = make_ctx(tmp_path, [BOOK_ACTION])

    await flush_call(ctx, _Settings())
    await flush_call(ctx, _Settings())
    await flush_call(ctx, _Settings())

    submitter = FakeSubmitter.instances[-1]
    assert len(submitter.calls) == 1


async def test_flush_of_silent_call_falls_back_to_no_action(tmp_path, fake_submitter):
    ctx = make_ctx(tmp_path, [])

    await flush_call(ctx, _Settings())

    submitter = FakeSubmitter.instances[-1]
    assert len(submitter.calls) == 1
    assert submitter.calls[0]["action"] == {"route": "no-action", "reason": "out_of_scope"}


async def test_flush_without_api_key_never_posts(tmp_path):
    """Offline mode: no key, no Submitter instance, no outbound request."""
    FakeSubmitter.instances = []

    ctx = make_ctx(tmp_path, [BOOK_ACTION])
    settings = _Settings()
    settings.prosper_api_key = ""

    await flush_call(ctx, settings)

    assert FakeSubmitter.instances == []
    assert ctx.submitted is True
    assert ctx.queued_actions == [BOOK_ACTION]  # action preserved for later inspection


async def test_flush_skips_unknown_route_but_keeps_flushing(tmp_path, fake_submitter):
    ctx = make_ctx(tmp_path, [{"route": "teleport"}, BOOK_ACTION])

    await flush_call(ctx, _Settings())

    submitter = FakeSubmitter.instances[-1]
    assert [c["action"]["route"] for c in submitter.calls] == ["book"]
