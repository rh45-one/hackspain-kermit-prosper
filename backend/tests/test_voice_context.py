"""Per-call state tests: identity binding, lifecycle, registries."""
from __future__ import annotations

from agent.voice.context import CallContext


def make_ctx(tmp_path, **kwargs) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"), **kwargs)


def test_provisional_call_id_gets_own_audit_file(tmp_path):
    ctx = make_ctx(tmp_path)

    assert ctx.call_id.startswith("local-")
    assert (tmp_path / "data" / "calls" / f"{ctx.call_id}.jsonl").exists()


def test_set_call_id_moves_audit_trail_to_callsid(tmp_path):
    ctx = make_ctx(tmp_path)
    provisional = ctx.call_id
    ctx.audit("before_start", {})

    ctx.set_call_id("CA-real-sid")
    ctx.audit("after_start", {})

    new_path = tmp_path / "data" / "calls" / "CA-real-sid.jsonl"
    old_path = tmp_path / "data" / "calls" / f"{provisional}.jsonl"
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

    path = tmp_path / "data" / "calls" / f"{ctx.call_id}.jsonl"
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
    path = tmp_path / "data" / "calls" / f"{ctx.call_id}.jsonl"
    assert "Hola" in path.read_text(encoding="utf-8")
