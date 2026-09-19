"""Twilio Media Streams serializer that sniffs harness handshake events.

The Prosper harness speaks Twilio's Media Streams wire format but is not
Twilio: there is no REST API to hang up, and the `start` event carries the
call identity (callSid, streamSid, from_number). The stock pipecat
TwilioFrameSerializer ignores those events and requires a stream_sid up
front, so this subclass captures them into a CallContext and keeps
auto_hang_up off — the harness owns the call lifecycle.

Audio stays at the wire's native 8 kHz end to end (transport, VAD, STT, TTS
and pipeline params all run at 8 kHz), so the serializer's µ-law <-> PCM
conversion never engages a resampler. This matters: pipecat 1.11 creates
its stream resamplers with soxr quality "VHQ", and soxr 1.0.0 VHQ buffers
chunks and only emits in delayed bursts, which leaves the agent deaf in
real time. With in_rate == out_rate the resampler is bypassed entirely.
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pipecat.frames.frames import AudioRawFrame, Frame, InputAudioRawFrame
from pipecat.serializers.twilio import TwilioFrameSerializer

from agent.voice.context import CallContext


class ProsperTwilioSerializer(TwilioFrameSerializer):
    """Twilio Media Streams serializer wired to a per-call CallContext."""

    def __init__(self, ctx: CallContext) -> None:
        # stream_sid is patched when the harness `start` event arrives.
        # auto_hang_up stays off: the harness owns the call lifecycle and no
        # Twilio REST call is ever made (the base class only hangs up when
        # auto_hang_up is enabled, which requires Twilio credentials).
        super().__init__(
            stream_sid=ctx.stream_sid or "",
            params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
        )
        self._ctx = ctx

    async def serialize(self, frame: Frame) -> str | bytes | None:
        payload = await super().serialize(frame)
        if payload and isinstance(frame, AudioRawFrame):
            self._ctx.measure_wire_audio("out_serialized", frame.audio)
        return payload

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message: dict[str, Any] = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.debug("dropping unparseable websocket message")
            return None

        event = message.get("event")
        if event == "start":
            start = message.get("start", {}) or {}
            params = start.get("customParameters") or {}
            self._ctx.set_call_id(start.get("callSid") or params.get("call_id") or self._ctx.call_id)
            self._ctx.stream_sid = start.get("streamSid") or self._ctx.stream_sid
            # Absent from_number means withheld caller id: a hint, never identity.
            self._ctx.from_number = params.get("from_number")
            self._stream_sid = self._ctx.stream_sid or ""
            # Release the pipeline's bounded wait: start identity is complete.
            self._ctx.mark_start_received()
            logger.info(
                "call start captured: call_id={} from_number_present={}",
                self._ctx.call_id,
                self._ctx.from_number is not None,
            )
            return None
        if event == "stop":
            self._ctx.mark_stopped()
            return None
        if event in ("connected", "heartbeat"):
            return None
        if event == "media":
            self._ctx.mark_pipeline_stage("caller_audio_received")
        # media / dtmf / anything else: stock Twilio handling.
        frame = await super().deserialize(data)
        if isinstance(frame, InputAudioRawFrame):
            self._ctx.measure_wire_audio("in_decoded", frame.audio)
        return frame
