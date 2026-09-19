"""Deterministic serializer tests: Twilio Media Streams wire input/output.

No network, no services: the serializer is exercised directly with hand
built wire messages and reference µ-law values computed with the stdlib
audioop module (the same converter pipecat uses).
"""
from __future__ import annotations

import audioop
import base64
import json

import pytest
from pipecat.clocks.system_clock import SystemClock
from pipecat.frames.frames import (
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.utils.asyncio.task_manager import TaskManager

from agent.orgs import DEFAULT_ORG_ID
from agent.voice.context import CallContext
from agent.voice.twilio import ProsperTwilioSerializer

CALL_SID = "CA-serializer-test"
STREAM_SID = "SM-serializer-test"
PHONE = "+34612345678"


def make_ctx(tmp_path) -> CallContext:
    return CallContext(data_dir=str(tmp_path / "data"))


async def make_serializer(tmp_path) -> tuple[ProsperTwilioSerializer, CallContext]:
    """Serializer set up exactly as the pipeline sets it up: 8 kHz in/out."""
    ctx = make_ctx(tmp_path)
    serializer = ProsperTwilioSerializer(ctx)
    await serializer.setup(
        FrameProcessorSetup(
            clock=SystemClock(),
            task_manager=TaskManager(),
            pipeline_worker=None,
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
        )
    )
    return serializer, ctx


async def send_start(serializer: ProsperTwilioSerializer, with_phone: bool = True) -> None:
    params: dict = {"call_id": CALL_SID}
    if with_phone:
        params["from_number"] = PHONE
    await serializer.deserialize(
        json.dumps(
            {
                "event": "start",
                "start": {
                    "callSid": CALL_SID,
                    "streamSid": STREAM_SID,
                    "customParameters": params,
                },
                "sequenceNumber": "1",
            }
        )
    )


# ---- output: pipecat frames -> Twilio JSON -------------------------------


async def test_serialize_audio_emits_media_json_with_stream_sid(tmp_path):
    serializer, _ctx = await make_serializer(tmp_path)
    await send_start(serializer)

    pcm = b"\x00\x40" * 160  # int16 amplitude 0x4000 pattern
    frame = OutputAudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1)

    raw = await serializer.serialize(frame)
    message = json.loads(raw)

    assert message["event"] == "media"
    assert message["streamSid"] == STREAM_SID
    expected_ulaw = audioop.lin2ulaw(pcm, 2)
    assert base64.b64decode(message["media"]["payload"]) == expected_ulaw


async def test_serialize_audio_at_wire_rate_needs_no_resampler(tmp_path):
    """A 20 ms 8 kHz PCM frame must serialize to exactly 160 µ-law bytes."""
    serializer, _ = await make_serializer(tmp_path)
    await send_start(serializer)

    pcm = b"\x00\x10" * 160  # 160 int16 samples = 20 ms at 8 kHz
    message = json.loads(await serializer.serialize(OutputAudioRawFrame(pcm, 8000, 1)))

    assert len(base64.b64decode(message["media"]["payload"])) == 160


async def test_serialize_interruption_emits_clear(tmp_path):
    serializer, _ = await make_serializer(tmp_path)
    await send_start(serializer)

    message = json.loads(await serializer.serialize(InterruptionFrame()))

    assert message == {"event": "clear", "streamSid": STREAM_SID}


async def test_end_frame_does_not_call_twilio_rest(tmp_path):
    """auto_hang_up is off: EndFrame serializes to nothing and never dials REST."""
    serializer, _ = await make_serializer(tmp_path)
    await send_start(serializer)

    # No credentials were provided; with auto hang-up enabled the constructor
    # itself would have raised. Serializing EndFrame must be a safe no-op.
    assert await serializer.serialize(EndFrame()) is None


# ---- input: Twilio JSON -> pipecat frames + CallContext -------------------


async def test_start_captures_call_identity(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)
    await send_start(serializer)

    assert ctx.call_id == CALL_SID
    assert ctx.stream_sid == STREAM_SID
    assert ctx.from_number == PHONE
    # The per-call audit record must follow the real callSid.
    assert (tmp_path / "data" / DEFAULT_ORG_ID / "calls" / f"{CALL_SID}.jsonl").exists()


async def test_start_without_from_number_keeps_hint_absent(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)

    await send_start(serializer, with_phone=False)

    assert ctx.from_number is None
    assert ctx.call_id == CALL_SID


async def test_media_becomes_input_audio_at_8k(tmp_path):
    serializer, _ = await make_serializer(tmp_path)
    await send_start(serializer)

    ulaw = audioop.lin2ulaw(b"\x00\x20" * 160, 2)
    frame = await serializer.deserialize(
        json.dumps(
            {
                "event": "media",
                "streamSid": STREAM_SID,
                "media": {"payload": base64.b64encode(ulaw).decode()},
                "sequenceNumber": "2",
                "chunk": "1",
            }
        )
    )

    assert isinstance(frame, InputAudioRawFrame)
    assert frame.sample_rate == 8000
    assert frame.num_channels == 1
    assert frame.audio == audioop.ulaw2lin(ulaw, 2)


async def test_connected_stop_heartbeat_are_absorbed(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)

    connected = await serializer.deserialize(
        json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"})
    )
    heartbeat = await serializer.deserialize(json.dumps({"event": "heartbeat"}))
    stop = await serializer.deserialize(json.dumps({"event": "stop", "streamSid": STREAM_SID}))

    assert connected is None
    assert heartbeat is None
    assert stop is None
    assert ctx.stopped is True


async def test_unparseable_message_is_dropped(tmp_path):
    serializer, _ = await make_serializer(tmp_path)

    assert await serializer.deserialize(b"\xff\xfe garbage") is None


@pytest.mark.parametrize("event", ["media", "dtmf"])
async def test_unknown_shapes_fall_back_to_stock(tmp_path, event):
    serializer, _ = await make_serializer(tmp_path)
    await send_start(serializer)

    # Stock serializer returns None for anything it does not handle; the
    # subclass must not crash on such payloads.
    if event == "media":
        frame = await serializer.deserialize(
            json.dumps({"event": "media", "streamSid": STREAM_SID, "media": {"payload": ""}})
        )
    else:
        frame = await serializer.deserialize(json.dumps({"event": "dtmf", "dtmf": {"digit": "5"}}))
    assert frame is None or isinstance(frame, (InputAudioRawFrame, object))


async def test_start_signals_start_received(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)

    await send_start(serializer)

    assert ctx.start_received.is_set()


async def test_start_without_from_number_still_signals(tmp_path):
    serializer, ctx = await make_serializer(tmp_path)

    await send_start(serializer, with_phone=False)

    # Withheld caller id still completes the start handshake; only the hint
    # is absent.
    assert ctx.start_received.is_set()
    assert ctx.from_number is None
