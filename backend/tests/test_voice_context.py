"""Per-call state tests: identity binding, lifecycle, registries."""
from __future__ import annotations

from agent.orgs import DEFAULT_ORG_ID
from agent.voice.context import CallContext


def make_ctx(tmp_path, **kwargs) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"), **kwargs)


def test_provisional_call_id_gets_own_audit_file(tmp_path):
    ctx = make_ctx(tmp_path)

    assert ctx.call_id.startswith("local-")
    assert (tmp_path / "data" / DEFAULT_ORG_ID / "calls" / f"{ctx.call_id}.jsonl").exists()


def test_set_call_id_moves_audit_trail_to_callsid(tmp_path):
    ctx = make_ctx(tmp_path)
    provisional = ctx.call_id
    ctx.audit("before_start", {})

    ctx.set_call_id("CA-real-sid")
    ctx.audit("after_start", {})

    new_path = tmp_path / "data" / DEFAULT_ORG_ID / "calls" / "CA-real-sid.jsonl"
    old_path = tmp_path / "data" / DEFAULT_ORG_ID / "calls" / f"{provisional}.jsonl"
    assert ctx.call_id == "CA-real-sid"
    assert new_path.exists()
    assert not old_path.exists()
    body = new_path.read_text(encoding="utf-8")
    assert "before_start" in body and "after_start" in body and "call_id_bound" in body


def test_set_call_id_is_idempotent_and_ignores_empty(tmp_path):
    ctx = make_ctx(tmp_path)

    ctx.set_call_id("")
    assert ctx.call_id.startswith("local-")
    ctx.set_call_id("CA-1")
    ctx.set_call_id("CA-1")
    assert ctx.call_id == "CA-1"


def test_mark_stopped_flushes_once(tmp_path):
    ctx = make_ctx(tmp_path)

    ctx.mark_stopped()
    ctx.mark_stopped()
    ctx.mark_stopped()

    path = tmp_path / "data" / DEFAULT_ORG_ID / "calls" / f"{ctx.call_id}.jsonl"
    events = [line for line in path.read_text(encoding="utf-8").splitlines() if "socket_stop" in line]
    assert len(events) == 1
    assert ctx.stopped is True


def test_slot_registry_tokens_are_per_call(tmp_path):
    ctx = make_ctx(tmp_path)
    slots = [
        {"provider_id": "PR05", "start_time": "2026-09-24T16:30:00+02:00", "appointment_type_id": "review"},
        {"provider_id": "PR06", "start_time": "2026-09-24T17:00:00+02:00", "appointment_type_id": "first"},
    ]

    labelled = ctx.register_slots(slots)

    assert [l["token"] for l in labelled] == ["s1", "s2"]
    assert ctx.slot_registry["s2"]["provider_id"] == "PR06"


def test_transcript_is_recorded_and_audited(tmp_path):
    ctx = make_ctx(tmp_path)

    ctx.add_transcript("caller", "Hola")
    ctx.add_transcript("assistant", "Buenas tardes")

    assert ctx.transcript == [
        {"role": "caller", "text": "Hola"},
        {"role": "assistant", "text": "Buenas tardes"},
    ]
    path = tmp_path / "data" / DEFAULT_ORG_ID / "calls" / f"{ctx.call_id}.jsonl"
    assert "Hola" in path.read_text(encoding="utf-8")


# ---- start-received signal (from_number hint handshake) ---------------------


async def test_wait_for_start_returns_true_once_marked(tmp_path):
    ctx = CallContext(data_dir=str(tmp_path / "data"))

    ctx.mark_start_received()

    assert ctx.start_received.is_set()
    assert await ctx.wait_for_start(timeout=0.1) is True


async def test_wait_for_start_times_out_without_start(tmp_path):
    ctx = CallContext(data_dir=str(tmp_path / "data"))

    assert await ctx.wait_for_start(timeout=0.05) is False
    assert not ctx.start_received.is_set()


async def test_late_start_wakes_a_waiting_caller(tmp_path):
    import asyncio

    ctx = CallContext(data_dir=str(tmp_path / "data"))

    async def late_start() -> None:
        await asyncio.sleep(0.05)
        ctx.mark_start_received()

    task = asyncio.create_task(late_start())
    assert await ctx.wait_for_start(timeout=1.0) is True
    await task


async def test_start_signal_is_per_context(tmp_path):
    ctx_a = CallContext(data_dir=str(tmp_path / "a"))
    ctx_b = CallContext(data_dir=str(tmp_path / "b"))

    ctx_a.mark_start_received()

    assert ctx_a.start_received is not ctx_b.start_received
    assert not ctx_b.start_received.is_set()


async def test_mark_start_received_is_idempotent(tmp_path):
    ctx = CallContext(data_dir=str(tmp_path / "data"))

    ctx.mark_start_received()
    ctx.mark_start_received()

    assert ctx.start_received.is_set()
